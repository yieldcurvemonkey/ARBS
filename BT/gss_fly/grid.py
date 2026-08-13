"""Parameter search over the GSS book, built to measure conditioning rather than to find a winner.

The question this serves is "how ill-conditioned is this strategy to its parameters", so the design
priorities are different from an optimiser's:

**Persist the whole daily P&L series per config, not just its summary.** Every conditioning metric
worth computing — era-split rank stability, deflated Sharpe with the observed cross-config variance,
a response surface — needs statistics that were not chosen in advance. 332 floats per config is
nothing; re-running the grid to add a metric is hours.

**Guard against the degenerate optimum.** This book is cost-dead, so a naive Sharpe search selects
configs that trade less: three trades that happen to win give a spectacular Sharpe. Any config below
``min_trades`` is recorded and flagged, never silently ranked.

**Resume, and never bake a partial answer.** Learned the hard way on this branch: each config is
written as it completes, a rerun skips what is already on disk, and a partial sweep is never
consolidated into something a later read would mistake for the whole.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from BT.gss_fly.config import (BacktestConfig, BondSignalConfig, CostConfig, FlyConfig, GSSConfig,
                               UniverseConfig)

logger = logging.getLogger(__name__)

__all__ = [
    "ConfigPoint", "config_id", "build_gss_config", "run_point", "GridStore",
    "sample_configs", "DEFAULT_SPACE", "SPLINE_VARIANTS",
]


# --------------------------------------------------------------------------- the space
#: Levels per knob. A dict of name -> list of values; the sampler draws jointly.
#: Names are ``section.field``; ``cost.scale`` is synthetic (multiplies the half-spread table).
DEFAULT_SPACE: Dict[str, Sequence[Any]] = {
    # --- signal
    "signal.ts_weight": (0.0, 0.5, 0.75, 1.0),
    "signal.smoothing_halflife": (1.0, 3.0, 8.0),
    "signal.scoring_com": (10.0, 20.0, 60.0),
    # --- universe
    "universe.min_ttm": (2.0, 3.0, 5.0),
    "universe.min_seasoning_days": (0.0, 50.0, 180.0),
    "universe.exclude_ranks": ((), (0,), (0, 1)),
    # --- fly construction
    "fly.wing_range_1": (1.0, 2.0, 3.0),
    "fly.wing_range_2": (3.0, 5.0, 8.0),
    "fly.std_halflife": (10.0, 20.0, 40.0),
    "fly.fly_smoothing_halflife": (1.0, 2.0, 5.0),
    "fly.fly_scoring_com": (15.0, 30.0, 60.0),
    "fly.wing_objective": ("signal_gap", "legacy_ttm_bug"),
    # --- the entry/exit LEVELS the question calls out
    "backtest.entry_zsig_bp": (0.5, 1.0, 1.5, 2.0, 3.0, 4.5),
    "backtest.exit_abs_z": (0.25, 0.5, 1.0),
    "backtest.require_turning_point": (True, False),
    "backtest.reentry_cooldown_days": (0, 5, 20),
    "backtest.max_concurrent": (5, 10, 25),
    # --- cost, incl. an explicit scale so "how much must execution improve" is answerable
    "costs.cost_legs": ("all", "belly_only"),
    "costs.scale": (0.25, 0.5, 1.0),
    "costs.repo_penalty_bp": (1.0, 2.5, 5.0),
}

#: Spline configs are expensive (a refit is ~19 min for 332 days), so they are an OUTER loop over a
#: small named set rather than a swept dimension. Each entry says what it tests.
SPLINE_VARIANTS: Dict[str, Dict[str, Any]] = {
    "jpm_par": {},  # the current default, unchanged
    "coarse_knots": {"knots": (2.0, 5.0, 10.0, 20.0)},          # does knot density create the residual?
    "dense_knots": {"knots": (1.5, 2.0, 3.0, 3.5, 5.0, 7.0, 8.5, 10.0, 12.5, 15.0,
                              17.5, 20.0, 22.5, 25.0, 27.5)},   # ...or destroy it?
    "degree2": {"degree": 2},                                    # smoothness of the fit
    "equal_weight": {"weighting": "equal"},                      # BPV weighting biases the long end
    "otr_included": {"exclude_ranks": ()},                       # OTRs anchor the curve
}


@dataclass(frozen=True)
class ConfigPoint:
    """One point in the search space: the knob values plus the spline variant name."""

    params: Dict[str, Any]
    spline: str = "jpm_par"

    def to_json(self) -> str:
        return json.dumps({"spline": self.spline, "params": _jsonable(self.params)}, sort_keys=True)


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def config_id(point: ConfigPoint) -> str:
    """Stable short id. Content-addressed so a resumed sweep matches by VALUE, not by position."""
    return hashlib.sha1(point.to_json().encode("utf-8")).hexdigest()[:12]


def build_gss_config(point: ConfigPoint) -> GSSConfig:
    """Materialise a :class:`GSSConfig` from a flat ``section.field`` mapping.

    ``costs.scale`` is synthetic: it multiplies every bucket in the half-spread table, which is the
    knob that answers "how much would execution have to improve", and it is applied here rather
    than inside the cost function so the cost function stays the one the book actually documents.
    """
    buckets: Dict[str, Dict[str, Any]] = {"signal": {}, "universe": {}, "fly": {}, "costs": {},
                                          "backtest": {}}
    scale = 1.0
    for key, value in point.params.items():
        section, _, fieldname = key.partition(".")
        if section == "costs" and fieldname == "scale":
            scale = float(value)
            continue
        if section not in buckets:
            raise KeyError(f"unknown config section {section!r} in {key!r}")
        buckets[section][fieldname] = value

    costs_kwargs = dict(buckets["costs"])
    base = CostConfig()
    if scale != 1.0:
        costs_kwargs["half_spread_bp"] = {k: v * scale for k, v in base.half_spread_bp.items()}

    return GSSConfig(
        signal=BondSignalConfig(**buckets["signal"]),
        universe=UniverseConfig(**buckets["universe"]),
        fly=FlyConfig(**buckets["fly"]),
        costs=CostConfig(**costs_kwargs),
        backtest=BacktestConfig(**buckets["backtest"]),
    )


# --------------------------------------------------------------------------- sampling
def sample_configs(
    space: Optional[Dict[str, Sequence[Any]]] = None,
    *,
    n: int = 400,
    seed: int = 20260812,
    splines: Sequence[str] = ("jpm_par",),
    exclude_invalid: bool = True,
) -> List[ConfigPoint]:
    """Draw ``n`` joint samples per spline variant, deduplicated.

    Random joint sampling rather than a full factorial: the space here is ~10^8 points, and for a
    SENSITIVITY study an unbiased joint sample estimates main effects and interactions far better
    per unit of compute than a coarse full grid does. The seed makes the draw reproducible; note
    that reproducibility here is of the SET, not of any positional assignment.
    """
    space = dict(space or DEFAULT_SPACE)
    rng = np.random.default_rng(seed)
    keys = sorted(space)
    seen, out = set(), []
    # generous cap: rejection for invalid combinations should not silently shrink the sample
    for _ in range(n * 40):
        if len([p for p in out if p.spline == splines[-1]]) >= n and len(out) >= n * len(splines):
            break
        params = {k: space[k][int(rng.integers(len(space[k])))] for k in keys}
        if exclude_invalid and not _valid(params):
            continue
        for sp in splines:
            pt = ConfigPoint(params=params, spline=sp)
            cid = config_id(pt)
            if cid in seen:
                continue
            seen.add(cid)
            out.append(pt)
        if len(out) >= n * len(splines):
            break
    return out


def _valid(params: Dict[str, Any]) -> bool:
    """Reject combinations that are degenerate rather than merely unusual."""
    w1 = float(params.get("fly.wing_range_1", 2.0))
    w2 = float(params.get("fly.wing_range_2", 5.0))
    if w2 <= w1:
        return False  # the long bucket must reach wider than the short one
    if float(params.get("universe.min_ttm", 3.0)) >= 10.0:
        return False
    # a scoring window shorter than the smoothing window scores noise it has just removed
    if float(params.get("signal.scoring_com", 20.0)) <= float(params.get("signal.smoothing_halflife", 3.0)):
        return False
    if float(params.get("fly.fly_scoring_com", 30.0)) <= float(params.get("fly.fly_smoothing_halflife", 2.0)):
        return False
    return True


# --------------------------------------------------------------------------- running one point
def run_point(
    point: ConfigPoint,
    panel,
    mdp,
    *,
    repo_curve=None,
    min_trades: int = 8,
) -> Dict[str, Any]:
    """Run one config and return its metrics plus the full daily P&L and trade series.

    Returns a dict; ``daily_pnl`` and ``trade_pnl`` are lists so the whole thing serialises. Errors
    are captured into the row rather than raised: one bad config must not end a sweep, and a
    silently missing row is indistinguishable from a config that was never tried.
    """
    from BT.gss_fly.backtest import run_gss_backtest

    cid = config_id(point)
    t0 = time.time()
    row: Dict[str, Any] = {"config_id": cid, "spline": point.spline,
                           **{f"p_{k}": _scalar(v) for k, v in point.params.items()}}
    try:
        cfg = build_gss_config(point)
        res = run_gss_backtest(panel, mdp, cfg=cfg, repo_curve=repo_curve,
                               show_progress=False, strict=False)
    except Exception as exc:  # noqa: BLE001
        row.update({"ok": False, "error": f"{type(exc).__name__}: {exc}", "elapsed_s": time.time() - t0})
        return row

    eq = res.equity.dropna().astype(float)
    daily = eq.diff().dropna()
    sm = res.summary()
    trades = int(sm.get("closed_trades", 0) or 0)

    row.update({
        "ok": True,
        "elapsed_s": time.time() - t0,
        "trades": trades,
        "enough_trades": trades >= min_trades,
        "marked_days": int(sm.get("marked_days", 0) or 0),
        "equity_holes": int(res.diagnostics.get("equity_holes", 0) or 0),
        "end_equity_usd": float(sm.get("end_equity_usd", np.nan)),
        "gross_before_fees_usd": float(sm.get("gross_before_fees_usd", np.nan)),
        "fees_usd": float(sm.get("fees_usd", np.nan)),
        "carry_during_hold_usd": float(sm.get("carry_during_hold_usd", np.nan)),
        "unwind_proceeds_usd": float(sm.get("unwind_proceeds_usd", np.nan)),
        "max_dd_usd": float(sm.get("max_dd_usd", np.nan)),
        "reconciliation_gap_usd": float(sm.get("reconciliation_gap_usd", np.nan)),
        "median_hold_days": float(sm.get("median_hold_days", np.nan)),
        # the series everything else is derived from, kept so a new metric needs no re-run
        "daily_pnl": daily.to_numpy().tolist(),
        "daily_index": [str(d.date()) for d in daily.index],
        "trade_pnl": (res.closed["realized_pnl"].astype(float).tolist()
                      if not res.closed.empty and "realized_pnl" in res.closed.columns else []),
    })
    row.update(series_metrics(daily.to_numpy()))
    # break-even cost scale: at what multiple of the charged fee does this config reach zero?
    gross, fees = row["gross_before_fees_usd"], -row["fees_usd"]
    row["breakeven_cost_scale"] = float(gross / fees) if fees else np.nan
    return row


def _scalar(v):
    return str(v) if isinstance(v, (tuple, list)) else v


def series_metrics(daily: np.ndarray, periods_per_year: int = 252) -> Dict[str, float]:
    """Sharpe and the moments the deflated Sharpe needs, from a daily P&L array."""
    d = np.asarray(daily, dtype=float)
    d = d[np.isfinite(d)]
    out: Dict[str, float] = {"n_obs": int(len(d))}
    if len(d) < 3 or d.std(ddof=1) == 0:
        out.update({"sharpe_ann": np.nan, "sharpe_per_period": np.nan,
                    "skew": np.nan, "kurtosis": np.nan, "mean_daily": np.nan, "sd_daily": np.nan})
        return out
    mu, sd = float(d.mean()), float(d.std(ddof=1))
    out["mean_daily"], out["sd_daily"] = mu, sd
    out["sharpe_per_period"] = mu / sd
    out["sharpe_ann"] = mu / sd * np.sqrt(periods_per_year)
    z = (d - mu) / sd
    out["skew"] = float((z ** 3).mean())
    out["kurtosis"] = float((z ** 4).mean())  # NON-excess, which is what the DSR formula wants
    # era split: the first-half / second-half Sharpes, for rank-stability across the grid
    half = len(d) // 2
    for name, seg in (("h1", d[:half]), ("h2", d[half:])):
        if len(seg) > 5 and seg.std(ddof=1) > 0:
            out[f"sharpe_ann_{name}"] = float(seg.mean() / seg.std(ddof=1) * np.sqrt(periods_per_year))
        else:
            out[f"sharpe_ann_{name}"] = np.nan
    return out


# --------------------------------------------------------------------------- persistence
class GridStore:
    """One parquet per config, so a sweep resumes and a partial sweep is never mistaken for whole.

    The same rule as the panel cache: the consolidated file is written only when every requested
    config is present, because a consolidated partial result is preferred on read and would silently
    become the answer.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.rows = self.root / "rows"
        self.rows.mkdir(parents=True, exist_ok=True)

    def has(self, cid: str) -> bool:
        return (self.rows / f"{cid}.parquet").exists()

    def put(self, row: Dict[str, Any]) -> None:
        p = self.rows / f"{row['config_id']}.parquet"
        tmp = p.with_suffix(".tmp")
        pd.DataFrame([_pack(row)]).to_parquet(tmp)
        tmp.replace(p)

    def load(self) -> pd.DataFrame:
        files = sorted(self.rows.glob("*.parquet"))
        if not files:
            return pd.DataFrame()
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)

    def consolidate(self, expected: int) -> Optional[Path]:
        df = self.load()
        if df.empty or len(df) < expected:
            logger.info("grid incomplete: %d of %d configs; not consolidating", len(df), expected)
            return None
        out = self.root / "grid.parquet"
        df.to_parquet(out)
        return out


def _pack(row: Dict[str, Any]) -> Dict[str, Any]:
    """Series become JSON so one row is one parquet row regardless of length."""
    r = dict(row)
    for k in ("daily_pnl", "daily_index", "trade_pnl"):
        if k in r:
            r[k] = json.dumps(_jsonable(r[k]))
    return r


def unpack_series(df: pd.DataFrame, column: str = "daily_pnl") -> Dict[str, np.ndarray]:
    return {cid: np.asarray(json.loads(s), dtype=float)
            for cid, s in zip(df["config_id"], df[column])}
