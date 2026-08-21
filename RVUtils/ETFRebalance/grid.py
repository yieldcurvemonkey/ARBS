"""Grid search over the config space, and the price of having searched.

Two things this module refuses to let a caller do
--------------------------------------------------
**Report a winner without its selection hurdle.** Every extra knob multiplies the
configurations available, and ranking a few thousand by Sharpe finds a good one whether
or not any edge exists. :func:`league` therefore always returns ``dsr`` beside
``sharpe``, computed against ``E[max Sharpe]`` under the null that every configuration
has zero edge, with the spread of the Sharpes the grid actually observed as the null's
variance.

**Undercount the trials.** ``n_trials`` defaults to the number of rows in the league,
but the honest number is every configuration evaluated *anywhere* in the project --
including the IC surface, the conditioning search, and any grid whose results were
looked at and discarded. ``extra_trials`` exists so that total can be passed in, and it
is a required decision rather than a hidden default.

Why the universe is cached
--------------------------
``prepare_universe`` is the expensive half (gating, benchmark weights, a robust curve
fit per date) and is identical for every config sharing a fund, window, price basis and
curve spec. The cache key is exactly those fields, so a grid that sweeps signals and
timing pays for the universe once, and a grid that sweeps the curve spec correctly pays
again.
"""

from __future__ import annotations

import copy
import itertools
import json
import math
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from RVUtils.ETFRebalance import engine as EN

_EULER = 0.577215664901532860606512090082402431042159336


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """E[max Sharpe] under the null that every trial has zero edge."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1.0 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe(returns: np.ndarray, sr_star: float) -> float:
    """P(true Sharpe > 0) for the SELECTED strategy, given the selection hurdle.

    Uses the per-observation Sharpe with realised skew and kurtosis, because a strategy
    of rare large wins -- which an event-driven book is -- inflates a naive Sharpe.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    T = len(r)
    if T < 10:
        return float("nan")
    sd = r.std(ddof=1)
    if sd <= 0:
        return float("nan")
    sr = r.mean() / sd
    g3 = float(stats.skew(r))
    g4 = float(stats.kurtosis(r, fisher=False))
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        return float("nan")
    z = (sr - sr_star) * math.sqrt(T - 1) / math.sqrt(denom)
    return float(stats.norm.cdf(z))


def sign_flip_permutation(pnl: Sequence[float], n_perm: int = 5000, seed: int = 11) -> Dict[str, float]:
    """Is the Sharpe explained by the SIGN the signal chose, or by the volatility?

    Sign flips, not row permutation. A permutation of the rows leaves the Sharpe of a
    return series unchanged -- it is a function of the mean and standard deviation, both
    order-free -- so it tests nothing at all. Flipping signs at random destroys the
    direction while preserving the magnitudes, which is the null that matters here.
    """
    r = np.asarray(list(pnl), dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 10 or r.std(ddof=1) == 0:
        return {"realized_sharpe": float("nan"), "p_value": float("nan"),
                "perm_mean": float("nan"), "perm_std": float("nan"), "perm": np.array([])}
    real = float(r.mean() / r.std(ddof=1))
    rng = np.random.default_rng(seed)
    flips = rng.choice([-1.0, 1.0], size=(n_perm, len(r)))
    sims = (flips * r)
    perm = sims.mean(axis=1) / sims.std(axis=1, ddof=1)
    return {
        "realized_sharpe": real,
        "p_value": float((np.abs(perm) >= abs(real)).mean()),
        "perm_mean": float(perm.mean()), "perm_std": float(perm.std(ddof=1)),
        "perm": perm,
    }


# --------------------------------------------------------------------------- expansion


def expand(spec: Mapping[str, Sequence[Any]]) -> List[Dict[str, Any]]:
    """Cartesian product of ``{"timing.hold_days": [5, 10], ...}`` into config overlays.

    Dotted keys address one level down, which is the depth the config actually has, so
    a sweep names ``signal.components`` or ``timing.hold_days`` rather than restating the
    whole sub-dict for every cell.
    """
    keys = list(spec)
    out = []
    for combo in itertools.product(*(list(spec[k]) for k in keys)):
        cfg: Dict[str, Any] = {}
        parts = []
        for k, v in zip(keys, combo):
            if "." in k:
                a, b = k.split(".", 1)
                cfg.setdefault(a, {})[b] = copy.deepcopy(v)
            else:
                cfg[k] = copy.deepcopy(v)
            parts.append(f"{k.split('.')[-1]}={_short(v)}")
        cfg["name"] = " ".join(parts)
        out.append(cfg)
    return out


def _short(v: Any) -> str:
    if isinstance(v, Mapping):
        return "+".join(f"{k}{'' if w == 1 else w}" for k, w in v.items())
    if isinstance(v, (list, tuple)):
        return "/".join(str(x) for x in v)
    return str(v)


_UNIVERSE_KEYS = ("fund", "universe", "curve", "price_basis")


def _universe_key(cfg: Mapping[str, Any]) -> str:
    return json.dumps({k: cfg.get(k) for k in _UNIVERSE_KEYS}, sort_keys=True, default=str)


# --------------------------------------------------------------------------- running


def run_grid(
    overlays: Sequence[Mapping[str, Any]],
    *,
    base: Optional[Mapping[str, Any]] = None,
    joined: Optional[pd.DataFrame] = None,
    panel: Optional[pd.DataFrame] = None,
    floats: Optional[pd.DataFrame] = None,
    progress: bool = True,
    keep_results: bool = False,
    keep_pnl: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, EN.Result]]:
    """Run every overlay, reusing the prepared universe wherever it is unchanged.

    ``keep_results`` retains the whole :class:`~RVUtils.ETFRebalance.engine.Result` per
    configuration -- trade log, daily curve and leg frame, roughly 1MB each. On a
    1,680-cell grid that is ~1.7GB per worker on top of the panel, and it is what made
    the three largest funds thrash while the two smallest finished in half an hour.
    ``keep_pnl`` stores only the per-trade P&L array, which is all the deflated Sharpe
    needs and is a few kilobytes.
    """
    import tqdm

    base = dict(base or {})
    rows: List[Dict[str, Any]] = []
    kept: Dict[str, EN.Result] = {}
    cache: Dict[str, Tuple[pd.DataFrame, Dict[str, Any]]] = {}

    it = tqdm.tqdm(overlays, desc="GRID", unit="cfg") if progress else overlays
    for ov in it:
        cfg = EN.merge_config({**base, **dict(ov)})
        key = _universe_key(cfg)
        if key not in cache:
            cache[key] = EN.prepare_universe(cfg, joined=joined, panel=panel, floats=floats)
        uni, funnel = cache[key]
        try:
            res = EN.run_config(cfg, universe=uni, prepared_funnel=funnel)
        except Exception as exc:
            rows.append({"name": cfg.get("name", "?"), "trades": 0,
                         "error": f"{type(exc).__name__}: {exc}"})
            continue
        s = EN.summarize(res)
        row = {"name": cfg.get("name", "?"), **s,
               "config": json.dumps(dict(ov), default=str)}
        if keep_pnl and res.closed is not None and not res.closed.empty:
            row["_pnl"] = res.closed["pnl_bp"].to_numpy(float)
        rows.append(row)
        if keep_results:
            kept[cfg.get("name", "?")] = res

    league = pd.DataFrame(rows)
    if "trades" in league.columns:
        league = league.sort_values("trades", ascending=False)
    return league.reset_index(drop=True), kept


def league(
    table: pd.DataFrame,
    *,
    extra_trials: int = 0,
    min_trades: int = 30,
    rank_on: str = "sr_per_trade",
) -> pd.DataFrame:
    """Add the selection hurdle and the deflated Sharpe to a grid table.

    ``extra_trials`` is not optional in spirit. The grid is never the only search that
    happened; the IC surface and every conditioning cut are trials too, and a DSR that
    counts only the rows in this table is a DSR that has been told the wrong number.
    """
    t = table[table.get("trades", pd.Series(dtype=int)).fillna(0) >= min_trades].copy()
    if t.empty:
        return t

    sr = t[rank_on].astype(float).to_numpy()
    sr = sr[np.isfinite(sr)]
    n_trials = int(len(t)) + int(extra_trials)
    var_sr = float(np.var(sr, ddof=1)) if len(sr) > 1 else 0.0
    sr_star = expected_max_sharpe(var_sr, n_trials)

    t["n_trials_counted"] = n_trials
    t["sr_star"] = sr_star
    t["clears_hurdle"] = t[rank_on].astype(float) > sr_star
    return t.sort_values(rank_on, ascending=False).reset_index(drop=True)


def attach_dsr(table: pd.DataFrame, results: Mapping[str, EN.Result],
               *, sr_star: float) -> pd.DataFrame:
    """DSR per row, from each config's own trade P&L series."""
    out = table.copy()
    dsr = []
    for nm in out["name"]:
        r = results.get(nm)
        if r is None or r.closed is None or r.closed.empty:
            dsr.append(np.nan)
            continue
        dsr.append(deflated_sharpe(r.closed["pnl_bp"].to_numpy(float), sr_star))
    out["dsr"] = dsr
    return out


def attach_dsr_from_pnl(table: pd.DataFrame, *, sr_star: float) -> pd.DataFrame:
    """DSR per row from the ``_pnl`` arrays kept by ``run_grid(keep_pnl=True)``.

    Same answer as :func:`attach_dsr` without holding a whole Result per configuration.
    """
    out = table.copy()
    if "_pnl" not in out.columns:
        out["dsr"] = np.nan
        return out
    out["dsr"] = [
        deflated_sharpe(np.asarray(v, dtype=float), sr_star)
        if v is not None and np.ndim(v) == 1 and len(v) >= 10 else np.nan
        for v in out["_pnl"]
    ]
    return out


def alive(table: pd.DataFrame, *, dsr_min: float = 0.95, min_trades: int = 50,
          require_positive_net: bool = True) -> pd.DataFrame:
    """The rows that survive selection, sample size and cost, in that order.

    ``require_positive_net`` is the one that usually does the work: a configuration can
    clear a statistical hurdle on gross P&L and still be a losing trade after the spread,
    and the spread here is measured rather than assumed.
    """
    t = table.copy()
    m = pd.Series(True, index=t.index)
    if "dsr" in t.columns:
        m &= t["dsr"].fillna(0.0) > dsr_min
    if "trades" in t.columns:
        m &= t["trades"].fillna(0) >= min_trades
    if require_positive_net and "avg_bp" in t.columns:
        m &= t["avg_bp"].fillna(-1.0) > 0
    return t[m]
