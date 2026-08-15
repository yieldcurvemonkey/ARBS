"""Stale-settle detection on the SOFR futures leg.

Why this exists, and why ``CA >= 0`` is not enough.

A negative convexity adjustment is a no-arbitrage violation and therefore an
unmissable error. But it is only the *visible tail* of the staleness
distribution: a deferred contract whose settle is a day old will usually leave
the pack's adjustment positive, pass the sign filter, and still be wrong.

The damage is worse in a P&L panel than in a screen. Grid P&L is simulated as

    dPnL = -(dCA_bp) * CA_DV01          [short-convexity position]

so a quote that sticks for k days and then catches up in one print books **zero
P&L for k days and the whole accumulated move as a one-day gain or loss**. That
is not noise that averages out -- it is a fabricated return series with
artificially low variance and artificially fat one-day jumps, which is precisely
the combination that manufactures Sharpe. A grid cell can look excellent purely
by trading a data artefact.

Three detectors, all on the raw futures price panel rather than on the
adjustment, because that is where the defect lives:

``repeat_price``
    The contract's price is unchanged from the previous observation while a
    liquid reference (the front contract) moved. One day of this is common for a
    genuinely quiet deferred contract; it is flagged, not condemned.

``stale_run``
    ``min_run`` or more consecutive unchanged prints. This is the one that
    creates the accumulate-then-jump pattern.

``jump_after_stale``
    A large move on the first print *after* a stale run -- the catch-up. These
    are the individual days that carry the fabricated P&L, and they are the rows
    to exclude from a return series.

The intended use is not to repair the data but to *quantify what the result
depends on*: run the grid with and without the flagged days and report both. If
a cell's Sharpe collapses when catch-up days are dropped, that cell was trading
the data error.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "flag_stale_prices",
    "pack_staleness",
    "staleness_summary",
    "DEFAULT_MIN_RUN",
    "DEFAULT_JUMP_BP",
]

#: Consecutive unchanged prints that constitute a stale run.
DEFAULT_MIN_RUN = 2

#: A move this large (bp) on the first print after a stale run is a catch-up.
DEFAULT_JUMP_BP = 3.0


def flag_stale_prices(
    prices: pd.DataFrame,
    *,
    reference: Optional[str] = None,
    min_run: int = DEFAULT_MIN_RUN,
    jump_bp: float = DEFAULT_JUMP_BP,
    reference_move_bp: float = 0.5,
) -> pd.DataFrame:
    """Per-contract staleness flags for a ``date x contract`` price panel.

    ``prices`` is in futures price points (100 - rate), so a 1bp rate move is
    0.01 price points; everything below is converted to bp internally.

    ``reference`` names the liquid contract used to establish that the market
    actually moved. Defaults to the column with the fewest unchanged prints,
    which is the front contract in any normal panel.

    Returns a long frame with one row per (date, contract) and the boolean
    columns ``repeat_price``, ``stale_run``, ``jump_after_stale``, ``any_flag``.
    """
    if prices.empty:
        return pd.DataFrame(columns=["date", "contract", "repeat_price", "stale_run",
                                     "jump_after_stale", "any_flag"])

    px = prices.sort_index()
    d_bp = px.diff() * 100.0  # price points -> bp of rate (magnitude)

    if reference is None:
        unchanged = (d_bp.abs() < 1e-9).sum()
        reference = unchanged.idxmin()
    ref_moved = d_bp[reference].abs() >= reference_move_bp

    frames: List[pd.DataFrame] = []
    for col in px.columns:
        s = d_bp[col]
        unchanged = s.abs() < 1e-9
        # A repeat only counts when the market demonstrably moved.
        repeat = unchanged & ref_moved & s.notna()

        # Length of the current run of unchanged prints.
        grp = (~unchanged).cumsum()
        run_len = unchanged.groupby(grp).cumsum()
        stale_run = unchanged & (run_len >= min_run) & ref_moved

        # The first print after a stale run, if it is a big move.
        prev_stale = stale_run.shift(1, fill_value=False)
        jump = prev_stale & (s.abs() >= jump_bp)

        frames.append(pd.DataFrame({
            "date": px.index,
            "contract": col,
            "repeat_price": repeat.to_numpy(),
            "stale_run": stale_run.to_numpy(),
            "jump_after_stale": jump.to_numpy(),
        }))

    out = pd.concat(frames, ignore_index=True)
    out["any_flag"] = out[["repeat_price", "stale_run", "jump_after_stale"]].any(axis=1)
    return out


def pack_staleness(
    flags: pd.DataFrame,
    pack_members: dict,
) -> pd.DataFrame:
    """Roll contract-level flags up to packs.

    ``pack_members`` maps a pack label to the sequence of contract symbols in it.
    A pack inherits a flag if ANY of its four legs carries it -- the pack rate is
    a mean, so one stale leg contaminates the whole adjustment.
    """
    if flags.empty:
        return pd.DataFrame(columns=["date", "pack", "repeat_price", "stale_run",
                                     "jump_after_stale", "any_flag", "n_stale_legs"])
    idx = flags.set_index(["date", "contract"])
    rows = []
    for pack, members in pack_members.items():
        members = list(members)
        sub = idx.reindex(
            pd.MultiIndex.from_product([sorted(flags["date"].unique()), members],
                                       names=["date", "contract"])
        )
        g = sub.groupby(level="date")
        rows.append(pd.DataFrame({
            "date": g.size().index,
            "pack": pack,
            "repeat_price": g["repeat_price"].any().to_numpy(),
            "stale_run": g["stale_run"].any().to_numpy(),
            "jump_after_stale": g["jump_after_stale"].any().to_numpy(),
            "n_stale_legs": g["stale_run"].sum().to_numpy(),
        }))
    out = pd.concat(rows, ignore_index=True)
    out["any_flag"] = out[["repeat_price", "stale_run", "jump_after_stale"]].any(axis=1)
    return out


def staleness_summary(flags: pd.DataFrame, by: str = "contract") -> pd.DataFrame:
    """Share of observations carrying each flag, grouped by *by*."""
    if flags.empty:
        return pd.DataFrame()
    cols = ["repeat_price", "stale_run", "jump_after_stale", "any_flag"]
    g = flags.groupby(by)[cols].mean()
    g["n"] = flags.groupby(by).size()
    return g.sort_values("any_flag", ascending=False)
