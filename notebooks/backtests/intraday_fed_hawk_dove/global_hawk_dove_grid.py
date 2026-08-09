"""Instrument and parameter grid search for the global hawk/dove study.

Searches over
    * the STRUCTURE traded  - outrights, calendar spreads, butterflies, packs,
      built from the 1st..Nth quarterly IMM contracts
    * the entry / exit window
    * the labelling scheme

and ranks by Sharpe. The whole point of the exercise is that ranking by Sharpe
across thousands of configurations finds a high Sharpe WHETHER OR NOT any signal
exists, so every result here is reported with a Deflated Sharpe Ratio that prices
in how many configurations were tried.

Mechanics: prices for every contract rank at every event's entry and exit are
gathered ONCE into a price panel; after that a configuration is arithmetic, so a
few thousand of them cost seconds rather than a few thousand backtests. The
arithmetic is the same closed form the position handler uses, validated against
the engine on the baseline book to the tick.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

import global_hawk_dove_common as G


# ===========================================================================
# Structures
# ===========================================================================
@dataclass(frozen=True)
class Structure:
    """A traded package, expressed in RATE space.

    ``legs`` are (contract_rank, weight) with weights on the RATE of each
    contract, so a positive total weight is a position that gains when rates
    rise. ``hawk`` therefore always takes the structure with side +1 and dove
    with -1, and the search asks which package best expresses the view rather
    than which sign to use.
    """
    name: str
    kind: str
    legs: tuple           # ((rank, weight), ...)

    @property
    def ranks(self) -> tuple:
        return tuple(r for r, _ in self.legs)

    @property
    def gross(self) -> float:
        return sum(abs(w) for _, w in self.legs)


def build_structures(max_rank: int = 6) -> List[Structure]:
    out: List[Structure] = []
    for n in range(1, max_rank + 1):
        out.append(Structure(f"OUT_{n}", "outright", ((n, 1.0),)))
    # calendar spreads: adjacent and two apart, long the back rate (steepener)
    for gap in (1, 2):
        for n in range(1, max_rank + 1 - gap):
            m = n + gap
            out.append(Structure(f"SPR_{n}_{m}", "spread", ((n, -1.0), (m, 1.0))))
    # butterflies: 2*belly - wings, the standard curvature trade
    for n in range(1, max_rank - 1):
        b, k = n + 1, n + 2
        out.append(Structure(f"FLY_{n}_{b}_{k}", "fly", ((n, -1.0), (b, 2.0), (k, -1.0))))
    # packs: the average of four consecutive contracts
    for n in range(1, max_rank - 2):
        out.append(Structure(f"PACK_{n}", "pack",
                             tuple((n + i, 0.25) for i in range(4))))
    return out


# ===========================================================================
# Price panel
# ===========================================================================
def build_price_panel(
    events: List[dict],
    cfg: G.CBConfig,
    barchart_mdp,
    ranks: Sequence[int],
    *,
    max_staleness_min: int = 45,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Entry/exit price for every event at every contract rank.

    Gating is re-run per rank because a different contract can be illiquid on a
    day the baseline one traded; an event only survives where EVERY rank it needs
    has a causal mark, which is enforced later by dropping rows with NaNs.
    """
    frames = []
    for rank in ranks:
        variant = G.rebuild_with_contract(events, cfg, rank)
        gated, _reasons, _diag = G.gate(
            variant, cfg, barchart_mdp,
            max_staleness_min=max_staleness_min, show_progress=show_progress)
        if not gated:
            continue
        frames.append(pd.DataFrame([{
            "tag": e["tag"], "rank": rank,
            "entry_px": e["entry_bar_px"], "exit_px": e["exit_bar_px"],
        } for e in gated]))
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    panel = long.pivot(index="tag", columns="rank", values=["entry_px", "exit_px"])
    return panel


def structure_pnl_bp(panel: pd.DataFrame, st: Structure) -> pd.Series:
    """Δ(structure rate) in bp per event, before the trade's own direction.

    price = 100 - rate, so a rate change in bp is -(Δprice)/0.01. The structure's
    rate move is the weighted sum of its legs'.
    """
    total = None
    for rank, w in st.legs:
        try:
            e = panel[("entry_px", rank)]
            x = panel[("exit_px", rank)]
        except KeyError:
            return pd.Series(dtype=float)
        d_rate_bp = -(x - e) / 0.01
        total = w * d_rate_bp if total is None else total + w * d_rate_bp
    return total


# ===========================================================================
# Deflated Sharpe
# ===========================================================================
_EULER = 0.5772156649015329


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """E[max Sharpe] under the null that every trial has zero edge."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    e = math.e
    z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * e))
    return math.sqrt(sr_variance) * ((1.0 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe(returns: np.ndarray, sr_star: float) -> float:
    """P(true Sharpe > 0) for the SELECTED strategy, given the selection hurdle.

    Bailey & Lopez de Prado. Uses the per-observation Sharpe and the realised
    skew/kurtosis, because a strategy of rare large wins - which is exactly what
    an event study looks like - inflates a naive Sharpe.
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


# ===========================================================================
# The grid
# ===========================================================================
def run_grid(
    panels: Dict[str, pd.DataFrame],
    meta: Dict[str, pd.DataFrame],
    structures: Sequence[Structure],
    *,
    cost_bp: float = 0.0,
) -> pd.DataFrame:
    """Score every (structure) against every leg's panel and pool.

    ``meta`` carries per-event side/bucket/timestamps keyed by tag.
    """
    rows = []
    for st in structures:
        legs_pnl = []
        for bank, panel in panels.items():
            if panel is None or panel.empty:
                continue
            m = meta[bank]
            d_rate = structure_pnl_bp(panel, st)
            if d_rate.empty:
                continue
            j = m.join(d_rate.rename("d_rate_bp"), how="inner").dropna(subset=["d_rate_bp"])
            if j.empty:
                continue
            # hawk (+1) profits when the structure's rate rises
            pnl = j["side_rate"] * j["d_rate_bp"] * j["size"]
            gross = st.gross or 1.0
            legs_pnl.append(pd.DataFrame({
                "bank": bank, "opened_at": j["opened_at"],
                "pnl_bp": pnl / gross - cost_bp,
                "timestamp_source": j.get("timestamp_source", "forexfactory"),
            }))
        if not legs_pnl:
            continue
        allp = pd.concat(legs_pnl, ignore_index=True).sort_values("opened_at")
        r = allp["pnl_bp"].to_numpy(float)
        if len(r) < 20:
            continue
        sd = r.std(ddof=1)
        sr_obs = r.mean() / sd if sd > 0 else 0.0
        yrs = max((allp["opened_at"].max() - allp["opened_at"].min()).days / 365.25, 1e-9)
        tpy = len(r) / yrs
        rows.append({
            "structure": st.name, "kind": st.kind, "legs": len(st.legs),
            "trades": len(r), "total_bp": r.sum(), "avg_bp": r.mean(),
            "hit": float((r > 0).mean()),
            "sharpe_ann": sr_obs * math.sqrt(tpy),
            "sr_per_trade": sr_obs,
            "t_stat": sr_obs * math.sqrt(len(r)),
            "skew": float(stats.skew(r)), "kurt": float(stats.kurtosis(r, fisher=False)),
            "_returns": r,
        })
    return pd.DataFrame(rows)


def add_deflated(grid: pd.DataFrame, n_trials: Optional[int] = None) -> pd.DataFrame:
    """Attach the Deflated Sharpe, using the spread of Sharpes actually observed
    across the grid as the null's variance - the honest way to price the search."""
    if grid.empty:
        return grid
    n = int(n_trials or len(grid))
    var_sr = float(np.var(grid["sr_per_trade"].to_numpy(float), ddof=1)) if len(grid) > 1 else 0.0
    sr_star = expected_max_sharpe(var_sr, n)
    out = grid.copy()
    out["n_trials"] = n
    out["sr_star"] = sr_star
    out["dsr"] = [deflated_sharpe(r, sr_star) for r in out["_returns"]]
    return out.sort_values("sharpe_ann", ascending=False)
