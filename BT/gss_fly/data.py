"""Curve data for the GSS butterfly book.

Two independent sources, because they answer different questions:

* :func:`build_curve_panel` — the **backtest** path. Per date it fits the ARBS cash spline and
  keeps the per-bond yield error, which is the ARBS equivalent of GSS's ``FittedZspread``. Runs
  entirely offline off ``USTS_FEDINVEST_WSJ_LIVE-QL``; no Excel, no add-in.
* :func:`fetch_curveset_snapshot` — the **CVSNAP** path. Pulls the whole UST curveset at one
  instant from Citi Velocity and merges the reference data onto it, so a curve can be reconstructed
  as it stood at a timestamp rather than at a close.

The snapshot path carries a guard worth naming: Citi's point-in-time read resolves *as-of*, so a
request for an instant the wire never published silently returns an earlier one. Every snapshot
here is returned with the stamp it actually resolved to, and :func:`fetch_curveset_snapshot` will
refuse a resolution further from the request than ``max_staleness``.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from BT.gss_fly.config import GSSConfig, UniverseConfig

logger = logging.getLogger(__name__)

__all__ = [
    "CurvePanel",
    "build_curve_panel",
    "ust_business_days",
    "apply_universe_filter",
    "fetch_curveset_snapshot",
    "warm_bond_snapshots",
    "LocalReferenceProvider",
    "local_reference_data",
    "BOND_SNAPSHOT_VALUES",
]

#: The Citi bond values worth pulling for a curveset snapshot. ``PRICE`` is clean and ``DURATION``
#: is modified — both established previously against Citi's own field dictionary.
BOND_SNAPSHOT_VALUES = ("YIELD", "PRICE", "DURATION", "DV01", "ASW", "ZSPREAD")

#: Dates that failed in this process. Not persisted — see the note at its use site.
_FAILED_DAYS: set = set()


@dataclass
class CurvePanel:
    """Dates × bonds panels plus the per-date reference frame.

    ``s2c`` is the spline yield error in bp: **positive means cheap** (the bond yields more than
    the fitted curve says it should). GSS's ``FittedZspread`` has the same orientation.
    """

    s2c: pd.DataFrame
    ytm: pd.DataFrame
    ttm: pd.DataFrame
    reference: pd.DataFrame  # long: date, cusip, ttm, maturity, cpn, rank, issue_date, ...
    rmse: pd.Series

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.s2c.index)

    def curve_on(self, when) -> pd.DataFrame:
        """The per-bond frame for one date, indexed by cusip: ttm, maturity, cpn, rank, s2c."""
        ts = pd.Timestamp(when)
        ref = self.reference[self.reference["date"] == ts]
        if ref.empty:
            return pd.DataFrame(columns=["ttm", "maturity", "cpn", "rank", "s2c"])
        out = ref.set_index("cusip").copy()
        if ts in self.s2c.index:
            out["s2c"] = self.s2c.loc[ts].reindex(out.index)
        else:
            out["s2c"] = np.nan
        return out

    def summary(self) -> str:
        return (
            f"CurvePanel {len(self.s2c)} dates {self.dates.min().date()}..{self.dates.max().date()}, "
            f"{self.s2c.shape[1]} bonds, median RMSE {self.rmse.median():.2f}bp"
        )


def ust_business_days(start, end) -> List[datetime.date]:
    """Trading days on the UST government-bond calendar.

    ``pd.bdate_range`` gives weekdays, which includes market holidays. The source never serves a
    holiday, so a panel asked for one retries it on every chunked call and, because the fetcher
    hangs rather than 404s, one Labor Day is enough to stall an entire warm — observed, twice.
    A holiday also never resolves, which under ``consolidate="complete"`` blocks the consolidated
    cache forever.

    Derive the day set from the calendar the market actually keeps, not from ``bdate_range``.
    """
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    out: List[datetime.date] = []
    for ts in pd.bdate_range(start, end):
        d = ts.date()
        if cal.isBusinessDay(ql.Date(d.day, d.month, d.year)):
            out.append(d)
    return out


def _maturity_years(maturity_date, asof) -> float:
    try:
        return (pd.Timestamp(maturity_date) - pd.Timestamp(asof)).days / 365.25
    except Exception:
        return float("nan")


def build_curve_panel(
    dates: Sequence[datetime.date],
    mdp,
    *,
    cache_path: Optional[Path] = None,
    show_progress: bool = True,
    consolidate: str = "complete",
    workers: int = 1,
    local_reference: bool = True,
) -> CurvePanel:
    """Fit the cash spline on every date and assemble the dates × bonds panels.

    ``mdp`` is a :class:`~MDP.FixedRateBonds.FixedRateBondsMDP.FixedRateBondsMDP`. A date whose
    spline fails is skipped and logged rather than aborting the panel — a missing day costs one
    observation, an aborted panel costs the run.

    **The per-day cache is what makes this usable.** Acquisition here is I/O-bound, not
    compute-bound: the steady state is ~1.7s/day but every thirty-odd days the upstream stalls for
    minutes at a time, so a 507-day panel runs for an hour at single-digit CPU. Writing the whole
    panel only at the end meant any interruption in that hour — a kill, a hung fetch, a machine
    reboot — threw away every completed day and the next attempt started from zero. So each day is
    written to ``cache_path/days`` as it completes and a rerun fetches only what is missing. The
    consolidated panel is still written at the end, and a consolidated cache is still preferred on
    read because loading five parquets beats loading a thousand.

    ``consolidate`` governs the consolidated write, and the default is the safe one:

    * ``"complete"`` (default) — write it only when every requested date resolved. An incomplete
      panel that consolidates is worse than no cache at all: the consolidated file is preferred on
      read, so every later run loads the short panel and never retries the missing days, and a
      transient upstream stall becomes a permanent hole in the backtest without saying so.
    * ``"never"`` — build and return, but leave only the per-day files. This is what a **chunked**
      warm must use. A caller warming ``days[:n]`` in growing prefixes is asking about a prefix, not
      about the panel; if a prefix consolidated, it would be served forever as if it were the whole
      range. That is the same defect as above, arrived at from the other direction.
    * ``"always"`` — bake the panel including its gaps, for a range whose missing dates are known to
      be real rather than transient.

    ``workers > 1`` fetches days on a thread pool. This is worth doing because the work is not
    compute: a serial build sits at ~2% CPU holding a single connection to the Treasury host, so the
    hour is one remote server answering one request at a time. Days are absorbed in **date order**
    regardless of completion order, so the panel is identical to a serial build — a property worth
    stating because the reference frame is a concatenation and would otherwise inherit whichever
    day happened to finish first.
    """
    if consolidate not in ("complete", "never", "always"):
        raise ValueError(f"consolidate must be complete|never|always, got {consolidate!r}")
    dates = [pd.Timestamp(d).date() for d in dates]
    day_dir: Optional[Path] = None
    if cache_path is not None:
        cache_path = Path(cache_path)
        if (cache_path / "s2c.parquet").exists():
            logger.info("curve panel cache hit: %s", cache_path)
            return _load_panel(cache_path)
        day_dir = cache_path / "days"
        day_dir.mkdir(parents=True, exist_ok=True)

    s2c_rows: Dict[pd.Timestamp, pd.Series] = {}
    ytm_rows: Dict[pd.Timestamp, pd.Series] = {}
    ttm_rows: Dict[pd.Timestamp, pd.Series] = {}
    ref_frames: List[pd.DataFrame] = []
    rmse: Dict[pd.Timestamp, float] = {}

    todo = list(dates)
    if day_dir is not None:
        # A day counts as resumed only once it has actually LOADED. A file that exists but does not
        # read — a torn write, a half-flushed parquet — must fall through to the fetch path, not be
        # silently dropped from both the cache and the work list.
        resumed: List[datetime.date] = []
        for d in dates:
            if not _day_files(day_dir, d)[0].exists():
                continue
            day = _load_day(day_dir, d)
            if day is None:
                continue
            ts, spline_frame, ref = day
            _absorb_day(ts, spline_frame, ref, s2c_rows, ytm_rows, ttm_rows, rmse, ref_frames)
            resumed.append(d)
        todo = [d for d in dates if d not in set(resumed)]
        if resumed:
            logger.info("resuming: %d of %d days already cached in %s", len(resumed), len(dates), day_dir)

    # A date that already failed in THIS process is not retried. A chunked warm calls the builder
    # on growing prefixes, so without this a single date the source will not serve is re-attempted
    # on every chunk — and because the fetcher hangs rather than erroring, one such date stalls the
    # whole warm. Scoped to the process, not persisted: a transient failure must still be retried
    # by the next run, and a negative result written to disk is exactly the trap that consolidating
    # a partial panel was.
    if _FAILED_DAYS:
        skip = [d for d in todo if d in _FAILED_DAYS]
        if skip:
            logger.info("skipping %d date(s) that already failed this run: %s", len(skip),
                        ", ".join(str(d) for d in skip[:5]))
        todo = [d for d in todo if d not in _FAILED_DAYS]

    # One universe read serves every date, so the per-date reference fetch disappears entirely --
    # both here and inside `fetch_cash_spline`, which makes the same call before it fits.
    reference_fn = None
    stack = contextlib.ExitStack()
    if todo and local_reference:
        try:
            reference_fn = stack.enter_context(local_reference_data(mdp))
        except Exception as exc:  # noqa: BLE001 — fall back rather than fail the build
            logger.warning("local reference universe unavailable (%s); falling back to per-date fetch", exc)

    # The provider must stay bound for the whole fetch loop, not just while the results generator
    # is constructed — the generator is lazy, so the spline calls happen inside this block.
    with stack:
        if workers > 1 and todo:
            results = _fetch_days_concurrently(todo, mdp, workers, show_progress, reference_fn)
        else:
            iterator = todo
            if show_progress:
                try:
                    import tqdm

                    iterator = tqdm.tqdm(todo, desc="GSS curve panel", unit="day")
                except ImportError:
                    pass
            results = ((d, _fetch_day(d, mdp, reference_fn)) for d in iterator)

        for d, fetched in results:
            if fetched is None:
                _FAILED_DAYS.add(d)
                continue
            frame, ref = fetched
            _absorb_day(pd.Timestamp(d), frame, ref, s2c_rows, ytm_rows, ttm_rows, rmse, ref_frames)
            if day_dir is not None:
                _save_day(day_dir, d, frame, ref)

    if not s2c_rows:
        raise RuntimeError("no dates produced a spline — check the MDP source and the date range")

    s2c = pd.DataFrame(s2c_rows).T.sort_index()
    ytm = pd.DataFrame(ytm_rows).T.sort_index() if ytm_rows else pd.DataFrame(index=s2c.index)
    ttm = pd.DataFrame(ttm_rows).T.sort_index()
    reference = pd.concat(ref_frames, ignore_index=True)
    panel = CurvePanel(s2c=s2c, ytm=ytm, ttm=ttm, reference=reference, rmse=pd.Series(rmse).sort_index())

    _assert_reference_is_usable(panel)

    missing = [d for d in dates if pd.Timestamp(d) not in s2c_rows]
    if missing:
        logger.warning(
            "curve panel incomplete: %d of %d dates did not resolve (first %s, last %s)",
            len(missing), len(dates), missing[0], missing[-1],
        )
    if cache_path is not None:
        if consolidate == "never":
            logger.debug("consolidated cache suppressed (consolidate='never')")
        elif missing and consolidate == "complete":
            logger.info(
                "consolidated cache NOT written — %d dates still missing. The per-day cache in %s "
                "is kept, so a rerun refetches only those dates.",
                len(missing), cache_path / "days",
            )
        else:
            _save_panel(panel, cache_path)
    return panel


class LocalReferenceProvider:
    """Derive each date's bond reference frame locally instead of fetching it per date.

    ``FixedRateBondsMDP.get_bond_reference_data`` calls ``_fetch_fiscaldata`` directly and so
    bypasses the reference cache entirely — a 350-day panel made 350 HTTP round-trips to
    fiscaldata for what is **one static universe file**. A bond's identity does not change: its
    coupon, issue date, auction date and maturity are fixed at auction, and the only thing that
    varies by date is which bonds are alive and how they rank within their on-the-run bucket. Both
    are local computations over the universe.

    ``update_reference_data("fiscaldata")`` already caches that universe (1,785 rows, all issues
    back to 1982 — matured bonds are retained, so historical dates reconstruct correctly), and
    ``_rl_prefetch_intraday`` already derives per-date frames from it this way.

    **The boundary rule was measured, not assumed.** Against 48 reference frames built by the
    fetched path, ``issue_date <= as_of < maturity_date`` reproduces all 48 exactly — membership
    and on-the-run rank. Neither boundary is the one ``_filter_and_rank_ref_df`` uses: its strict
    ``issue_date < as_of`` drops a bond on its issue day, which cascades (181 ranks moved on
    2024-09-03), and its ``maturity_date >= as_of`` keeps a bond on the day it matures. Those are
    not cosmetic for this book — with ``exclude_ranks=(0,)``, whether a new issue is present
    decides whether the *previous* on-the-run is rank 0 and dropped, or rank 1 and traded.
    """

    def __init__(self, *, force_refresh: bool = False):
        from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

        self.universe = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
        self._roll = self._roll_dates(self.universe)
        logger.info("local reference universe: %d issues, no per-date fetch", len(self.universe))

    @staticmethod
    def _roll_dates(ref: pd.DataFrame):
        """On-the-run roll takes effect the business day after auction; issue_date is the fallback."""
        if "auction_date" in ref.columns and ref["auction_date"].notna().any():
            from MDP.FixedRateBonds.FixedRateBondsMDP import _roll_dates_for

            return _roll_dates_for(ref)
        return ref["issue_date"]

    @staticmethod
    def _ttm_years(maturity, as_of) -> float:
        """Time to maturity on **ActualActual(ISDA)**, which is what the fetched path returns.

        Not a detail. `days/365.25` differs by up to 1.4e-3 years — about half a day — and
        `min_ttm` is a hard cutoff at exactly 3.0, so the wrong convention silently moves bonds
        in and out of the tradeable universe near the boundary. Verified to 0.0 against six
        fetched reference frames.
        """
        import QuantLib as ql

        a, m = pd.Timestamp(as_of), pd.Timestamp(maturity)
        return ql.ActualActual(ql.ActualActual.ISDA).yearFraction(
            ql.Date(a.day, a.month, a.year), ql.Date(m.day, m.month, m.year)
        )

    def __call__(self, as_of: datetime.date) -> pd.DataFrame:
        ref = self.universe
        eligible = (
            (self._roll < as_of)
            & (ref["issue_date"] <= as_of)      # a bond IS tradeable on its issue day
            & (ref["maturity_date"] > as_of)    # and is NOT on the day it matures
        )
        out = ref[eligible].copy()
        out["rank"] = out.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1
        # `ttm` is NOT in the cached universe — it is per-date, so the fetched path computes it and
        # the universe file cannot carry it. Omitting it does not fail loudly: `apply_universe_filter`
        # skips a missing column, but once ANY date in the panel supplies one the concatenated frame
        # has the column with NaN for every other date, and `NaN >= min_ttm` is False. That silently
        # emptied the tradeable universe on 284 of 332 dates while the panel still reported 343 bonds
        # and the backtest still produced plausible-looking numbers.
        out["ttm"] = [self._ttm_years(m, as_of) for m in out["maturity_date"]]
        return out


@contextlib.contextmanager
def local_reference_data(mdp, provider: Optional["LocalReferenceProvider"] = None):
    """Serve ``mdp.get_bond_reference_data`` from the local universe for the duration of the block.

    Replacing the call in the panel builder only removes half the waste: ``fetch_cash_spline``
    calls ``get_bond_reference_data`` itself before fitting, so a cold spline pays the same 1.62s
    uncached fiscaldata round-trip regardless of what the builder does. Binding the provider onto
    the instance covers both.

    Scoped and restored on exit, because this mutates an object the caller owns — a permanent
    monkeypatch would change the behaviour of every other consumer of that MDP without saying so.
    """
    provider = provider or LocalReferenceProvider()
    original = mdp.get_bond_reference_data

    def _local(as_of_date, kwargs=None, **_):
        # cme_tcf asks a different question of a different source; leave it to the original
        if kwargs and kwargs.get("cme_tcf"):
            return original(as_of_date=as_of_date, kwargs=kwargs)
        return provider(as_of_date)

    mdp.get_bond_reference_data = _local
    try:
        yield provider
    finally:
        mdp.get_bond_reference_data = original


def _fetch_day(d: datetime.date, mdp, reference_fn=None):
    """Fetch one day's spline and reference frame. ``None`` if either leg fails.

    Both fetches for a date live here so the threaded and serial paths run *identical* code — the
    only difference between them is which thread calls this function.
    """
    ts = pd.Timestamp(d)
    try:
        spline = mdp.fetch_cash_spline(d)
    except Exception as exc:  # noqa: BLE001 — logged, not hidden
        logger.warning("spline failed on %s: %s: %s", d, type(exc).__name__, exc)
        return None
    if spline is None or spline.yield_errors is None or spline.yield_errors.empty:
        logger.warning("spline empty on %s", d)
        return None

    frame = spline.to_frame().reset_index()
    if "cusip" not in frame.columns:
        frame = frame.rename(columns={frame.columns[0]: "cusip"})
    frame = frame.copy()
    frame["rmse"] = float(spline.rmse) if spline.rmse is not None else np.nan

    try:
        ref = reference_fn(d) if reference_fn is not None else mdp.get_bond_reference_data(as_of_date=d)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reference data failed on %s: %s", d, exc)
        return None
    ref = ref.copy()
    ref["date"] = ts
    if "maturity_date" in ref.columns:
        ref["maturity"] = ref["maturity_date"].map(lambda m: _maturity_years(m, d))
    if "issue_date" in ref.columns:
        ref["seasoning_days"] = ref["issue_date"].map(
            lambda i: (pd.Timestamp(d) - pd.Timestamp(i)).days if pd.notna(i) else np.nan
        )
    return frame, ref


def _fetch_days_concurrently(todo, mdp, workers: int, show_progress: bool, reference_fn=None):
    """Fetch days on a thread pool, yielding them **in date order**.

    Acquisition here is not compute — a serial build sits at ~2% CPU with a single open connection
    to the Treasury host, so the wall clock is almost entirely one remote server's response time and
    threads buy close to linear speedup. The GIL is not in the way of that.

    Yielding in input order is what keeps the result identical to the serial build: the panel's
    reference frame is a concatenation, so completion order would otherwise leak into the output.
    ``executor.map`` preserves input order regardless of which day finishes first.
    """
    from concurrent.futures import ThreadPoolExecutor

    todo = list(todo)
    bar = None
    if show_progress:
        try:
            import tqdm

            bar = tqdm.tqdm(total=len(todo), desc=f"GSS curve panel x{workers}", unit="day")
        except ImportError:
            pass

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for d, fetched in zip(todo, pool.map(lambda x: _fetch_day(x, mdp, reference_fn), todo)):
            if bar is not None:
                bar.update(1)
            yield d, fetched
    if bar is not None:
        bar.close()


#: Columns `apply_universe_filter` gates on. A column that is present but null does not disable the
#: gate — it fails it, for every row.
_UNIVERSE_COLUMNS = ("ttm", "cpn", "rank")


def _assert_reference_is_usable(panel: CurvePanel) -> None:
    """Refuse a panel whose reference frame cannot support the universe filter.

    This exists because the failure it catches was completely silent. When the local reference
    provider omitted ``ttm``, the concatenated frame still *had* the column — supplied by the days
    that came from the fetched path — and it was NaN for every other date. ``apply_universe_filter``
    skips a **missing** column but applies a **null** one, and ``NaN >= min_ttm`` is False, so the
    tradeable universe was empty on 284 of 332 dates. Nothing failed: the panel still reported 343
    bonds and a 1.94bp RMSE, the backtest still ran, and it still produced entirely plausible
    numbers — computed from the 48 usable dates alone.

    So: a gating column that is present must be populated on essentially every date.
    """
    ref = panel.reference
    if ref.empty or "date" not in ref.columns:
        return
    n_dates = ref["date"].nunique()
    for col in _UNIVERSE_COLUMNS:
        if col not in ref.columns:
            continue
        good = ref.loc[ref[col].notna(), "date"].nunique()
        if good < n_dates:
            raise RuntimeError(
                f"reference column {col!r} is null on {n_dates - good} of {n_dates} dates. "
                f"`apply_universe_filter` gates on it, and a null gate excludes every bond rather "
                f"than being skipped, so those dates would silently trade nothing. "
                f"This usually means a reference source did not populate {col!r}."
            )


def _absorb_day(
    ts: pd.Timestamp,
    frame: pd.DataFrame,
    ref: pd.DataFrame,
    s2c_rows: Dict[pd.Timestamp, pd.Series],
    ytm_rows: Dict[pd.Timestamp, pd.Series],
    ttm_rows: Dict[pd.Timestamp, pd.Series],
    rmse: Dict[pd.Timestamp, float],
    ref_frames: List[pd.DataFrame],
) -> None:
    """Fold one day's spline frame and reference frame into the panel accumulators.

    Shared by the fetch path and the cache-resume path so a resumed panel is assembled by exactly
    the same code as a freshly built one — a resume that assembles differently is a resume that
    silently changes the answer.
    """
    s2c_rows[ts] = pd.Series(frame["yield_error_bp"].to_numpy(), index=frame["cusip"])
    if "observed" in frame.columns:
        ytm_rows[ts] = pd.Series(frame["observed"].to_numpy(), index=frame["cusip"])
    ttm_rows[ts] = pd.Series(frame["ttm"].to_numpy(), index=frame["cusip"])
    rmse[ts] = float(frame["rmse"].iloc[0]) if "rmse" in frame.columns and len(frame) else np.nan
    ref_frames.append(_normalise_datetimes(ref))


def _normalise_datetimes(ref: pd.DataFrame) -> pd.DataFrame:
    """Pin every datetime column to nanosecond resolution.

    A parquet round-trip re-resolves datetimes — a ``date`` column written as ``datetime64[s]``
    comes back as ``datetime64[ms]``. The values are unchanged, so nothing fails loudly, but a
    reference frame concatenated from cached and freshly-fetched days would then carry a resolution
    that depends on which days happened to be cached. Anything that later joins or compares on
    those columns inherits that dependency.
    """
    out = ref.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].astype("datetime64[ns]")
    return out


def _day_files(day_dir: Path, d: datetime.date) -> Tuple[Path, Path]:
    stamp = pd.Timestamp(d).strftime("%Y-%m-%d")
    return day_dir / f"{stamp}.spline.parquet", day_dir / f"{stamp}.ref.parquet"


def _save_day(day_dir: Path, d: datetime.date, frame: pd.DataFrame, ref: pd.DataFrame) -> None:
    spline_p, ref_p = _day_files(day_dir, d)
    # Reference first, spline second: the spline file is what the resume scan looks for, so it must
    # not exist unless its partner does. Writing it last makes a torn write recoverable instead of
    # producing a day that claims to be cached and then fails to load.
    ref.to_parquet(ref_p.with_suffix(".tmp"))
    ref_p.with_suffix(".tmp").replace(ref_p)
    frame.to_parquet(spline_p.with_suffix(".tmp"))
    spline_p.with_suffix(".tmp").replace(spline_p)


def _load_day(day_dir: Path, d: datetime.date):
    spline_p, ref_p = _day_files(day_dir, d)
    try:
        frame = pd.read_parquet(spline_p)
        ref = pd.read_parquet(ref_p)
    except Exception as exc:  # noqa: BLE001 — a corrupt day is refetched, not fatal
        logger.warning("cached day %s unreadable (%s); refetching", d, exc)
        return None
    return pd.Timestamp(d), frame, ref


def _save_panel(panel: CurvePanel, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    panel.s2c.to_parquet(path / "s2c.parquet")
    panel.ytm.to_parquet(path / "ytm.parquet")
    panel.ttm.to_parquet(path / "ttm.parquet")
    panel.reference.to_parquet(path / "reference.parquet")
    panel.rmse.to_frame("rmse").to_parquet(path / "rmse.parquet")
    logger.info("wrote curve panel cache -> %s", path)


def _load_panel(path: Path) -> CurvePanel:
    return CurvePanel(
        s2c=pd.read_parquet(path / "s2c.parquet"),
        ytm=pd.read_parquet(path / "ytm.parquet"),
        ttm=pd.read_parquet(path / "ttm.parquet"),
        reference=pd.read_parquet(path / "reference.parquet"),
        rmse=pd.read_parquet(path / "rmse.parquet")["rmse"],
    )


def apply_universe_filter(curve: pd.DataFrame, cfg: Optional[UniverseConfig] = None) -> pd.DataFrame:
    """``select_eligible_bonds`` — coupon, time-to-maturity, seasoning, and rank."""
    cfg = cfg or UniverseConfig()
    out = curve
    if "cpn" in out.columns:
        out = out[out["cpn"] < cfg.max_coupon]
    if "ttm" in out.columns:
        out = out[out["ttm"] >= cfg.min_ttm]
    if "seasoning_days" in out.columns:
        out = out[(out["seasoning_days"].isna()) | (out["seasoning_days"] >= cfg.min_seasoning_days)]
    if "rank" in out.columns and cfg.exclude_ranks:
        out = out[~out["rank"].isin(cfg.exclude_ranks)]
    return out


# --------------------------------------------------------------------------- CVSNAP curveset
def fetch_curveset_snapshot(
    when,
    *,
    isins: Optional[Sequence[str]] = None,
    reference: Optional[pd.DataFrame] = None,
    values: Sequence[str] = BOND_SNAPSHOT_VALUES,
    quotes=None,
    freq: str = "DAILY",
    max_staleness: Optional[datetime.timedelta] = None,
    strict: bool = True,
) -> pd.DataFrame:
    """The whole UST curveset at one instant, with reference data merged on.

    This is the CVSNAP path. It returns one row per bond and one column per requested Citi value,
    joined to whatever reference frame is supplied (cusip/isin, ttm, maturity, coupon, rank).

    Parameters
    ----------
    when
        The instant to resolve. Citi resolves **as-of**, so the value returned may pre-date the
        request; the resolved stamp is attached as the ``snap_stamp`` column.
    max_staleness
        Refuse (``strict``) or warn when the resolution is further back than this. Defaults to one
        day for daily data and fifteen minutes for intraday — the nearest-snapshot trap is silent
        otherwise and will happily serve yesterday's curve for today's request.

    Raises
    ------
    RuntimeError
        When the Citi Excel bridge is unavailable. That is not recoverable in-process: the add-in
        only registers its UDFs inside a human-authenticated Excel.
    """
    from MDP.CitiVelocityExcel import tags as cv_tags

    when = pd.Timestamp(when)
    if max_staleness is None:
        max_staleness = datetime.timedelta(days=1) if str(freq).upper().startswith("D") else datetime.timedelta(minutes=15)

    if isins is None:
        if reference is None:
            raise ValueError("supply either isins= or reference=")
        col = "isin" if "isin" in reference.columns else "cusip"
        isins = reference[col].dropna().astype(str).unique().tolist()

    if quotes is None:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()

    tag_map: Dict[str, Tuple[str, str]] = {}
    for isin in isins:
        for v in values:
            try:
                tag_map[cv_tags.bond(isin, v)] = (isin, v)
            except Exception:  # noqa: BLE001 — an unknown value for this bond is not fatal
                continue
    if not tag_map:
        raise ValueError("no resolvable bond tags were built")

    try:
        frame = quotes.frame(
            list(tag_map.keys()),
            freq,
            start=when - datetime.timedelta(days=10),
            end=when,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Citi Velocity snapshot unavailable ({type(exc).__name__}: {exc}). The bridge attaches "
            "to a human-authenticated Excel with the Velocity add-in signed in; it cannot spawn one."
        ) from exc

    if frame is None or frame.empty:
        raise RuntimeError(f"Citi returned no rows for the curveset at {when}")

    idx = pd.DatetimeIndex(frame.index)
    usable = idx[idx <= when]
    if len(usable) == 0:
        raise RuntimeError(f"no quote at or before {when}; earliest is {idx.min()}")
    stamp = usable.max()
    lag = when - stamp
    if lag > max_staleness:
        msg = (
            f"curveset snapshot for {when} resolved to {stamp} ({lag} stale, limit {max_staleness}). "
            "Citi resolves as-of, so this is an older curve, not the one requested."
        )
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)

    row = frame.loc[stamp]
    records: Dict[str, Dict[str, float]] = {}
    for tag, (isin, value) in tag_map.items():
        if tag not in row.index:
            continue
        v = row[tag]
        if pd.isna(v):
            continue
        records.setdefault(isin, {})[value.lower()] = float(v)

    out = pd.DataFrame.from_dict(records, orient="index")
    out.index.name = "isin"
    out = out.reset_index()
    out["snap_stamp"] = stamp
    out["snap_request"] = when

    if reference is not None:
        col = "isin" if "isin" in reference.columns else "cusip"
        out = out.merge(reference.rename(columns={col: "isin"}), on="isin", how="left")

    return out


def warm_bond_snapshots(
    isins: Sequence[str],
    start,
    end,
    *,
    values: Sequence[str] = BOND_SNAPSHOT_VALUES,
    quotes=None,
    freq: str = "DAILY",
    chunk: int = 200,
) -> Dict[str, int]:
    """Pull and cache the bond history so later snapshots resolve from disk.

    Returns ``{tag_family: rows}``. Chunked because the add-in wedges on very wide requests — a
    528-column fetch has been observed to take Excel to 5 GB.
    """
    from MDP.CitiVelocityExcel import tags as cv_tags

    if quotes is None:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()

    all_tags: List[str] = []
    for isin in isins:
        for v in values:
            try:
                all_tags.append(cv_tags.bond(isin, v))
            except Exception:  # noqa: BLE001
                continue

    counts: Dict[str, int] = {}
    for i in range(0, len(all_tags), chunk):
        block = all_tags[i : i + chunk]
        try:
            frame = quotes.frame(block, freq, start=start, end=end)
        except Exception as exc:  # noqa: BLE001 — one bad block must not kill the warm
            logger.warning("warm block %d-%d failed: %s", i, i + len(block), exc)
            continue
        counts[f"block_{i}"] = 0 if frame is None else int(frame.notna().sum().sum())
        logger.info("warmed %d tags (%d..%d), %s rows", len(block), i, i + len(block), counts[f"block_{i}"])
    return counts
