"""Daily panels: forward par rates, implied vols, and the funding factor.

Panels are constant-maturity by construction (today's 10Y10Y is priced fresh
every day). Positions age; panels do not. Never join one to the other without
going through ``replication``, which owns the aging.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from RVUtils.StrikelessVol.conventions import slope_bp
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

logger = logging.getLogger(__name__)

PANEL_DIR = Path(__file__).resolve().parents[2] / "notebooks" / "data" / "strikeless_vol"

__all__ = ["PANEL_DIR", "forward_rate_panel", "spread_panel"]


def forward_rate_panel(
    curve_name: str,
    dates: Sequence[dt.date],
    legs: Iterable[ForwardLeg],
    *,
    source: str = "GSQUANT-RL",
    mdp=None,
    cache_path: Optional[str | Path] = None,
    show_progress: bool = False,
    max_missing_frac: float = 0.2,
) -> pd.DataFrame:
    """Constant-maturity forward par rates (decimals), one column per leg.

    Dates the provider cannot serve are dropped. They are never forward-filled:
    a filled day is a manufactured zero-change observation, and every realized
    vol and every changes-regression in this package would inherit the bias.

    ``max_missing_frac`` (default 0.2) guards against mistaking a systemic
    failure for a quiet market: a ``bdate_range`` legitimately contains market
    holidays no provider serves (~10/year in USD, roughly 4%; more in some
    other markets), so a small drop rate is normal. If the dropped fraction
    exceeds this threshold, or the panel would come back empty while dates
    were requested, that means the MDP or the pricing path broke for
    (almost) everything asked for -- not that a handful of holidays were
    skipped -- and this raises ``ValueError`` rather than silently returning
    a near-empty panel the caller has no way to distinguish from a calm one.

    ``show_progress`` is accepted but not yet wired up; reserved for a later
    task's progress bar on long bulk fetches.

    ``cache_path`` never serves or persists a partial row: a cached slice
    with any NaN in the requested columns is treated as a miss and
    re-fetched, and a merged write drops any row that is not complete across
    every column the file carries. See ``_write_panel_cache``.
    """
    legs = list(legs)
    dates = list(dates)
    wanted_labels = [leg.label for leg in legs]

    if cache_path and Path(cache_path).exists():
        cached = pd.read_parquet(cache_path)
        cached.index = pd.to_datetime(cached.index)
        wanted = pd.to_datetime(pd.Index(dates))
        has_all_dates = wanted.isin(cached.index).all()
        has_all_legs = set(wanted_labels).issubset(cached.columns)
        if has_all_dates and has_all_legs:
            slice_ = cached.loc[cached.index.isin(wanted), wanted_labels]
            # A row is complete or it is absent, never partial -- a NaN cell
            # (e.g. a legacy cache file, or one written outside this module)
            # is a miss, not a silent bad value served to the caller.
            if not slice_.isna().to_numpy().any():
                return slice_

    if mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source=source)

    curve_map = mdp.bulk_get_data({"curve_name": curve_name, "timestamps": dates})

    rows: List[dict] = []
    for ts, curve in curve_map.items():
        if ts == "live":
            raise ValueError(
                f"forward_rate_panel('{curve_name}'): bulk_get_data returned the "
                "'live' key -- one of the requested dates matched today and the "
                "MDP resolved it to the live snapshot, which cannot be placed on "
                "a DatetimeIndex here. Pass an explicit historical date instead."
            )
        if curve is None:
            logger.warning("skipping %s on %s: no curve returned", curve_name, ts)
            continue
        rec: dict = {}
        try:
            for leg in legs:
                swap = curve.build_irswap(fwd=leg.fwd, tenor=leg.tail)
                rec[leg.label] = float(curve.fair_rate(swap))
        except Exception:  # a curve that cannot price a leg contributes nothing
            logger.warning("skipping %s on %s", curve_name, ts, exc_info=True)
            continue
        rec["date"] = ts.date() if hasattr(ts, "date") else ts
        rows.append(rec)

    requested = len(dates)
    produced = len(rows)
    dropped = requested - produced
    missing_frac = (dropped / requested) if requested else 0.0
    logger.info(
        "forward_rate_panel('%s'): %d/%d requested dates produced rows "
        "(%d dropped, %.1f%% missing)",
        curve_name, produced, requested, dropped, missing_frac * 100.0,
    )
    if requested and (produced == 0 or missing_frac > max_missing_frac):
        date_range = f"{min(dates)}..{max(dates)}"
        raise ValueError(
            f"forward_rate_panel('{curve_name}', {date_range}): only "
            f"{produced}/{requested} requested dates produced rows ({dropped} "
            f"dropped, {missing_frac:.1%} missing, threshold "
            f"{max_missing_frac:.1%}). This looks like a systemic pricing "
            "failure, not ordinary holiday/weekend gaps."
        )

    if not rows:
        return pd.DataFrame(columns=wanted_labels)

    panel = pd.DataFrame(rows).set_index("date").sort_index()
    panel.index = pd.to_datetime(panel.index)
    panel = panel[wanted_labels]

    if cache_path:
        _write_panel_cache(panel, cache_path)
    return panel


def _write_panel_cache(panel: pd.DataFrame, cache_path: str | Path) -> None:
    """Persist ``panel`` to ``cache_path``, unioned with whatever is already
    on disk rather than overwritten.

    The natural incremental call pattern is "extend the panel by a day, same
    cache file". Overwriting would silently shrink the cache down to just the
    freshly fetched (possibly narrower) rows, forcing a full re-fetch of
    history the file already had on every subsequent call -- exactly the kind
    of redundant external fetch that has hit provider rate limits before in
    this repo. On any date/column overlap the freshly fetched value in
    ``panel`` wins.

    A narrower fetch (fewer legs than the file already carries) unions in new
    columns for its dates, which ``combine_first`` alone would leave NaN
    wherever the fresh fetch has no value. A row is complete or it is absent,
    never partial -- exactly the invariant the whole-date-drop logic above
    exists to protect -- so any row that is not complete across every column
    the merged file carries is dropped before writing. Those dates are not
    lost, only re-fetched on the next call that needs them; that is cheap
    next to a silent NaN sitting in a rate panel.
    """
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        existing = pd.read_parquet(cache_path)
        existing.index = pd.to_datetime(existing.index)
        combined = panel.combine_first(existing)
    else:
        combined = panel
    combined = combined.dropna(how="any")
    combined.sort_index().to_parquet(cache_path)


def spread_panel(rates: pd.DataFrame, pair: ForwardPair) -> pd.Series:
    """The pair's slope in bp: longer forward minus shorter forward."""
    short = rates[pair.short.label].astype(float)
    long_ = rates[pair.long.label].astype(float)
    out = pd.Series(
        slope_bp(short_rate=short, long_rate=long_),
        index=rates.index,
        name=pair.name,
    )
    return out
