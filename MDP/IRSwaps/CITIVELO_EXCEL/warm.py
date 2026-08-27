r"""Warm the CurveStore with historical EOD Citi Velocity curves.

One curve per business day per currency, built from the banked daily par grids and
written as a ``CurveSnapshot`` under the asset ``<curve_name>-CITIVELOEXCEL``.

Why a separate asset key
------------------------
Three different constructions of "the Citi curve" now exist in this repo - the
older workbook source (``USD-SOFR-1D-CITIVELO``, ~930 warmed partitions and the
dealer-ladder study depend on it), this EOD source, and the ``CVSTREAM`` daemon
(``-CITIVELOSTREAM``). They are built from different data by different code. The
repo has a recorded incident where two variants shared one key and *which answer
you got depended on cache state*, so each gets its own.

Why it runs offline
-------------------
Everything it needs is already in the tag cache: one ``CVTSHIST`` per currency
fetched 21 years of daily history (2005-01-03 onward). The warm therefore needs no
Excel at all, which is what makes it re-runnable and safe to interrupt.

What "enough tenors" means
--------------------------
The full 44-tenor grid is a recent thing. Measured on the banked history: USD has
5,540 daily rows but only 1,835 where **all 44** tenors print. Requiring all 44
would throw away two thirds of the history for no reason - a curve calibrated to
30 tenors is a perfectly good curve, it just interpolates over slightly wider
gaps. So the gate is ``min_tenors`` (default 20) and the tenor count is recorded
on every day written, so a consumer can filter on it rather than discover it.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

__all__ = ["WarmStat", "DEFAULT_ASSET_SUFFIX", "warm_curve", "warm_many", "warm_status"]

_logger = logging.getLogger(__name__)

#: See the module docstring: never shared with the other two Citi curve sources.
DEFAULT_ASSET_SUFFIX = "CITIVELOEXCEL"

DEFAULT_MIN_TENORS = 20


@dataclass
class WarmStat:
    """What one currency's warm did."""

    curve_name: str
    citi_index: str
    asset: str
    written: int = 0
    skipped_existing: int = 0
    skipped_sparse: int = 0
    failed: int = 0
    first: Optional[datetime.date] = None
    last: Optional[datetime.date] = None
    worst_reprice_bp: float = 0.0
    errors: List[str] = field(default_factory=list)
    #: The last day the BANKED par grid holds, set only when this curve wrote
    #: nothing BECAUSE the requested window starts after the grid ends.
    #:
    #: A structured field rather than a parsed error string, because the caller
    #: turns it into an exit code and matching on prose is how an exit code
    #: silently stops meaning anything. ``None`` means "this curve's emptiness is
    #: not explained by a stale grid" - either it wrote, or it failed for some
    #: other reason - and the two must not be conflated: a stale grid is a human
    #: harvest away from fixed, and everything else here is a defect.
    stale_grid: Optional[datetime.date] = None

    def describe(self) -> str:
        span = f"{self.first} .. {self.last}" if self.first else "-"
        return (
            f"{self.curve_name:<20}{self.written:>7} written{self.skipped_existing:>8} kept"
            f"{self.skipped_sparse:>8} sparse{self.failed:>7} failed   {span}"
            f"   worst reprice {self.worst_reprice_bp:.2e} bp"
        )


def asset_for(curve_name: str) -> str:
    return f"{str(curve_name).strip().upper()}-{DEFAULT_ASSET_SUFFIX}"


def _par_frame(citi_index: str, *, quotes: Any) -> pd.DataFrame:
    """The whole banked daily par grid for one curve, tenor-columned."""
    from MDP.CitiVelocityExcel import tags as T

    grid = T.ois_par_grid(citi_index)
    frame = quotes.frame(
        grid, "DAILY", start=datetime.date(2005, 1, 1), end=datetime.date.today()
    )
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.rename(columns={t: t.rsplit(".", 1)[-1] for t in frame.columns})
    return frame.sort_index()


def warm_curve(
    curve_name: str,
    *,
    quotes: Any = None,
    store: Any = None,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    min_tenors: int = DEFAULT_MIN_TENORS,
    force: bool = False,
    push_l2: bool = False,
    progress_every: int = 250,
) -> WarmStat:
    """Build and store one EOD curve per business day for ``curve_name``.

    Skips days already present unless ``force``. Never partially writes a day:
    ``CurveStore.write_day`` is atomic and content-addressed, so an interrupted
    run leaves whole days behind and re-running resumes.
    """
    import pytz

    from Caching.curve_store import CurveSnapshot, _to_date
    from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name

    entry = entry_for_curve_name(curve_name)
    stat = WarmStat(curve_name=entry.curve_name, citi_index=entry.citi_index,
                    asset=asset_for(entry.curve_name))

    if quotes is None:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes(offline=True)
    if store is None:
        from Caching.curve_store import CurveStore

        store = CurveStore.default()

    frame = _par_frame(entry.citi_index, quotes=quotes)
    if frame.empty:
        stat.errors.append("no banked daily par grid; run the harvest first")
        return stat
    banked_first, banked_last = frame.index[0].date(), frame.index[-1].date()
    if start is not None:
        frame = frame[frame.index.date >= start]
    if end is not None:
        frame = frame[frame.index.date <= end]
    # The window can empty a NON-empty grid, and that used to be silent: every
    # counter stayed 0, ``errors`` stayed empty, and the caller turned "wrote
    # nothing" into exit 1 with no reason anywhere. It is the commonest outcome
    # of all, because the nightly warm asks for TODAY and nothing on the nightly
    # schedule refreshes the DAILY par grid - only a manual harvest does.
    if frame.empty:
        # The DATE, recorded structurally, is what lets the caller tell this
        # apart from every other way a curve can write nothing. Set before the
        # message so the two can never disagree.
        #
        # Narrow on purpose: ONLY when the grid ends before the window begins.
        # An empty window whose grid extends past it is a different animal - a
        # caller asking for 1990, or a window inside a hole - and calling that
        # "stale, run the harvest" would send a human to do something that
        # cannot help.
        if start is not None and banked_last < start:
            stat.stale_grid = banked_last
        # Compact on purpose: this string is carried up into the warmer's SUMMARY
        # table, and the actionable half must survive the clip.
        stat.errors.append(
            f"no banked DAILY rows in {start}..{end}; the banked par grid ends "
            f"{banked_last} (spans from {banked_first}) - nothing on the nightly "
            f"schedule fetches DAILY par tags, run the harvest"
        )
        return stat

    from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import EOD_SNAP_TIME

    _CHI = pytz.timezone("America/Chicago")
    _NY = pytz.timezone("America/New_York")
    worst = 0.0

    for n, (stamp, row) in enumerate(frame.iterrows(), start=1):
        day = stamp.date()
        if not force and store.has_day(stat.asset, day):
            stat.skipped_existing += 1
            continue
        par = {t: float(v) for t, v in row.items() if pd.notna(v)}
        if len(par) < min_tenors:
            stat.skipped_sparse += 1
            continue
        try:
            rlc = build_rl_ois_curve(
                par_rates=par, ref_date=day, citi_index=entry.citi_index, min_tenors=min_tenors
            )
        except Exception as exc:  # noqa: BLE001 - one bad day must not stop 20 years
            stat.failed += 1
            if len(stat.errors) < 5:
                stat.errors.append(f"{day}: {type(exc).__name__}: {str(exc)[:120]}")
            continue

        handle = rlc.rl_pricing_curve
        raw = handle.nodes._nodes if hasattr(handle.nodes, "_nodes") else dict(handle.nodes)
        ordered = sorted(raw.keys())
        # The curve is an end-of-day object; stamp it at the instant Citi's daily
        # series is actually struck rather than at midnight, so an as-of read for
        # "that day" lands on it rather than before it. That instant is MEASURED
        # (15:00 New York) -- see `timestamps.EOD_SNAP_TIME`. It was a hardcoded
        # 17:00 until 2026-08-27, so rows written before then carry a 17:00 stamp;
        # the stamp is provenance only, nothing reconstructs or prices off it, and
        # reads are keyed on `trading_date`. Re-run with `force=True` to restamp.
        ts = _NY.localize(datetime.datetime.combine(day, EOD_SNAP_TIME))
        ts_utc = ts.astimezone(pytz.UTC)
        snapshot = CurveSnapshot(
            timestamp_utc=ts_utc,
            # `timestamp_local` is Chicago here, as in every other writer in this
            # repo; `session_minute` next to it is the wire-zone (New York) hour.
            # That pairing is pre-existing and left alone -- only the hour moved.
            timestamp_local=ts_utc.astimezone(_CHI),
            trading_date=day,
            session_minute=EOD_SNAP_TIME.hour * 60 + EOD_SNAP_TIME.minute,
            curve_name=stat.asset,
            cfg_hash="",
            reference_key=entry.curve_name,
            interpolation="log_linear",
            source_variant="CITIVELO_EXCEL_EOD",
            node_dates=[_to_date(d) for d in ordered],
            discount_factors=[float(raw[d]) for d in ordered],
        )
        store.write_day(stat.asset, day, [snapshot], overwrite=force, push_l2=push_l2)
        stat.written += 1
        stat.first = stat.first or day
        stat.last = day
        worst = max(worst, float(rlc.meta.get("max_reprice_error_bp") or 0.0))
        if progress_every and stat.written % progress_every == 0:
            _logger.info(
                "citivelo_excel warm: %s %d/%d days (%s)", entry.curve_name, n, len(frame), day
            )

    stat.worst_reprice_bp = worst
    return stat


def warm_many(
    curve_names: Sequence[str],
    **kwargs: Any,
) -> Dict[str, WarmStat]:
    """:func:`warm_curve` over several curves, sharing one quotes reader and store."""
    from Caching.curve_store import CurveStore
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    quotes = kwargs.pop("quotes", None) or CitiVeloQuotes(offline=True)
    store = kwargs.pop("store", None) or CurveStore.default()
    out: Dict[str, WarmStat] = {}
    for name in curve_names:
        stat = warm_curve(name, quotes=quotes, store=store, **kwargs)
        out[stat.curve_name] = stat
        print(stat.describe(), flush=True)
        for err in stat.errors:
            print(f"    {err}", flush=True)
    return out


def warm_status(curve_names: Sequence[str], *, store: Any = None) -> pd.DataFrame:
    """What is in the store for each curve."""
    if store is None:
        from Caching.curve_store import CurveStore

        store = CurveStore.default()
    rows = []
    for name in curve_names:
        asset = asset_for(name)
        try:
            days = store.available_dates(asset)
        except Exception as exc:  # noqa: BLE001
            rows.append({"curve_name": name, "asset": asset, "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append(
            {
                "curve_name": name,
                "asset": asset,
                "days": len(days),
                "first": days[0].isoformat() if days else None,
                "last": days[-1].isoformat() if days else None,
            }
        )
    return pd.DataFrame(rows)
