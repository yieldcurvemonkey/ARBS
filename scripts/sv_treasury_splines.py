"""Per-date Treasury par-curve splines for Task 16's H2 discriminator.

``spline_map(dates) -> dict[datetime.date, CashSpline]`` builds (or retrieves
from a durable on-disk cache) a :class:`~MDP.FixedRateBonds.cash_spline.CashSpline`
for every requested date, fit from ``FixedRateBondsMDP(source=
"USTS_FEDINVEST_WSJ_LIVE-RL")`` pricers -- i.e. the rateslib bond-pricer
backend, per the brief.

Cached to ``notebooks/data/strikeless_vol/ust_splines.pkl``: refitting a
decade of splines twice is wasted hours (this is a genuinely slow, one-time
build -- see "Runtime" below).

Two gaps in the pointed-to interface, both confirmed empirically before
writing this module (not merely inferred from reading it)
----------------------------------------------------------------------------
The brief points at ``Query.FixedRateBonds.spline_values
.expand_pricer_universe_for_spline`` and ``compute_spline_for_date`` for "the
pricer-universe plumbing". Both are used here, but neither works out of the
box for this exact source string.

1. ``expand_pricer_universe_for_spline`` cannot be made to preserve an RL
   pricer backend for this source: its delegate,
   ``carry_roll._infer_universe_source``, decides the backend from
   ``pricer.meta().get("source")`` -- and for a pricer built via
   ``FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL").get_pricer(...)``,
   that meta ``"source"`` key is a data-provenance tag (``"fedinvest"`` /
   ``"wsj_intraday"``), never the MDP source string. Seeding ``pricers`` with
   a real RL pricer therefore does NOT make the inference pick RL: it falls
   through the same as an empty seed dict, to the function's hard-coded
   default, ``"USTS_FEDINVEST_WSJ_LIVE-QL"``. Verified directly against the
   running MDP: ``expand_pricer_universe_for_spline(pricers=<a genuine RL
   CT10 pricer>, as_of_date=...)`` returns a dict of ``QLFixedRateBondPricer``
   objects, not ``RLFixedRateBondPricer``. Separately,
   ``FixedRateBondsMDP.get_bond_reference_data`` only recognises
   ``"USTS_FEDINVEST_WSJ_LIVE-QL"`` and ``"USTS_WEBULL_WSJ_LIVE-RL"`` -- not
   the FEDINVEST-RL source this task names -- and returns ``None`` for it, so
   a from-scratch reference-data-only re-implementation using an RL-sourced
   MDP instance doesn't work either.

   Worked around: ``expand_pricer_universe_for_spline`` exists to discover
   the CUSIP universe for a date (its documented job -- "ensures the pricer
   dict covers the full UST universe needed for cross-sectional fitting"),
   but its own final step -- building a full ``QLFixedRateBondPricer`` for
   every CUSIP just so the caller can read off the dict *keys* -- is 4-5x
   the cost of the reference-data-and-filter logic that actually determines
   the universe (measured: ~6-7s vs ~1.3-1.5s per date). ``_ust_universe_
   cusips`` below inlines that upstream filter (``get_bond_reference_data``
   -> drop ``record_date`` -> ``ttm >= min_ttm`` -> exclude ranks 0/1/2 ->
   dedupe on cusip -- the exact steps ``carry_roll
   .expand_pricer_universe_for_carry_roll`` performs before its own
   ``get_pricer`` call) and stops there, never building the QL pricers at
   all. Verified, not assumed: cross-checked against
   ``expand_pricer_universe_for_spline``'s own returned keys on 4 dates
   spanning the window (2020-03-12 pre-COVID, 2021-01-04 near-zero-rate,
   2023-03-10 SVB-week inversion, 2025-11-20 recent) -- identical CUSIP sets
   every time (262/265/279/298 cusips, exact set equality). Genuine RL
   pricers are then fetched for that CUSIP set from an explicit
   ``FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")`` instance. The
   actual yields the spline is fit to are therefore RL, as the brief
   specifies.

2. ``compute_spline_for_date`` (and ``FixedRateBondsMDP.fetch_cash_spline``,
   which shares the same pattern) builds its per-bond ``ttm`` column via
   ``pricer.time_to_maturity()``. For ``RLFixedRateBondPricer`` this method
   calls ``rateslib.dcf(start, end, convention)`` with only 3 positional
   args; the installed rateslib (2.1.1) raises unconditionally for the
   "actacticma" convention USTs use: ``ValueError: `termination` must be
   supplied with specified `convention`.`` -- confirmed with a minimal,
   pricer-free repro (``rl.dcf(rl.dt(2021,1,4), rl.dt(2028,11,30),
   "actacticma")`` alone raises the identical error) and confirmed this is
   NOT date-dependent (every RL pricer, every date, fails identically; the
   two "successful" dates seen while developing this module were reading a
   pre-existing on-disk spline cache built by unrelated, unaffected
   QL-backend prior work, not evidence RL was actually working). Every OTHER
   accessor on ``RLFixedRateBondPricer`` (``ytm``, ``dirty_price``, ``bpv``,
   ``mod_duration``...) builds a full ``rl.FixedRateBond(...)`` object first
   and calls a higher-level method on it, which is unaffected -- only
   ``time_to_maturity``'s direct, under-specified ``rl.dcf`` call is broken.
   This is a pre-existing bug in shared pricer-backend code
   (``Query/FixedRateBonds/backends/rateslib/RLFixedRateBondPricer.py``,
   outside this task's file list) and is not fixed here.

   Worked around: this module never calls ``pricer.time_to_maturity()``.
   ``_bond_rows_from_pricers`` below computes ``ttm`` itself as
   ``(pricer.maturity_date() - as_of_date).days / 365.0`` -- a plain
   Act/365 year fraction. This differs from the (intended, but broken)
   Act/Act-ICMA fraction by at most a few hundredths of a year for a bond
   mid-coupon-period, immaterial to a curve spanning 0.5-30y with
   ``min_ttm=1.0`` filtering, and confirmed by inspection: the resulting
   curves are historically sane (near-zero short rates 2021-01-04, a
   strongly inverted curve 2023-03-10 during the SVB week, both matching
   the real UST market on those dates). ``compute_spline_for_date`` is
   still used for its CACHE (``get_cached_spline``/``put_cached_spline``,
   keyed on ``(as_of_date, config_hash)`` -- not backend-tagged, so a hit
   may legitimately be a prior QL-backend fit; this is accepted, since QL
   and RL price the same FedInvest quotes under the same day-count spec and
   should agree, not because backend provenance is untracked by design) via
   a thin local re-implementation, ``_fit_spline_local``, that shares its
   caching calls but supplies the corrected ``ttm``.

Runtime
-------
Reference data (the historical CUSIP/issuance list) is cached by
``update_reference_data`` keyed to TODAY's date, not the historical as-of
date being priced -- so it costs one fetch total, not one per requested date.
The per-date cost that remains is a FedInvest EOD-price fetch plus building
~250-300 ``RLFixedRateBondPricer`` objects. ``FedInvestDataFetcher.runner``
accepts a batch of dates and caches to a *shared* on-disk cache keyed purely
by date (``LayeredCacheMixin.default_cache_path("FedInvest_Prices_Cache")``,
independent of which ``FixedRateBondsMDP`` instance -- QL discovery pass or
RL pricing pass -- touches it), so ``_prewarm_fedinvest`` below fetches every
requested date's prices ONCE before the main per-date loop; both the
QL-backend universe-discovery call and the RL-backend pricer fetch then hit
that same warm cache rather than each re-issuing network requests. Measured
on a single cold date: several seconds, dominated by per-CUSIP Python pricer
construction, not network I/O -- so the remaining per-date cost does not
disappear with prefetching, and a full ~1,382-business-day build (the UMEP
usable window, 2021-01-04..2026-08-03) is genuinely a multi-hour job. This is
exactly why the result is pickled to disk rather than recomputed per run.
"""
from __future__ import annotations

import datetime
import logging
import pickle
import tempfile
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

from RVUtils.StrikelessVol.panels import PANEL_DIR

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = PANEL_DIR / "ust_splines.pkl"

__all__ = ["spline_map", "DEFAULT_CACHE_PATH"]


def _is_ust_business_day(d: datetime.date) -> bool:
    """US government-bond calendar business-day check (QuantLib), used to
    skip holidays before ever attempting a pricer fetch.

    Without this, a holiday date (e.g. MLK Day, Juneteenth) still yields a
    non-empty CUSIP universe from reference data, so ``get_pricer`` is
    attempted for every CUSIP; each one individually discovers there is no
    FedInvest snapshot and falls through to a per-CUSIP WSJ-intraday retry
    before giving up. Measured: one holiday date this way costs ~2 minutes
    (vs. ~1-2s for the calendar check) -- over a multi-year business-day
    range (``pd.bdate_range`` does not know about market holidays, only
    weekends) that is roughly 9-10 dates/year of pure waste. Confirmed this
    calendar correctly flags the observed failures (2024-01-15 MLK Day,
    2023-06-19 Juneteenth) as non-business days before relying on it here.
    """
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    return cal.isBusinessDay(ql.Date(d.day, d.month, d.year))


def _load_cache(cache_path: Path) -> Dict[datetime.date, object]:
    if cache_path.exists():
        try:
            with open(cache_path, "rb") as f:
                return pickle.load(f)
        except Exception:
            logger.warning("Failed to load spline cache at %s -- rebuilding", cache_path, exc_info=True)
    return {}


def _write_cache_atomic(cache: Dict[datetime.date, object], cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=cache_path.parent, prefix=f".{cache_path.stem}.", suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with open(tmp_path, "wb") as f:
            pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, cache_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _prewarm_fedinvest(usts_mdp, dates: Sequence[datetime.date], *, max_concurrent: int = 6, show_progress: bool = True) -> None:
    """Batch-fetch FedInvest EOD prices for every date into the shared disk
    cache (see module docstring) so the per-date loop below is a cache hit,
    not a fresh network round trip.

    Best-effort: any failure here just means the per-date loop falls back to
    its own (slower) sequential fetch -- it is never the only path to a
    correct result.
    """
    try:
        usts_mdp._ensure_pricer_cache()
    except Exception:
        pass
    try:
        timestamps = [datetime.datetime(d.year, d.month, d.day) for d in dates]
        usts_mdp.fi.runner(
            dates=timestamps,
            show_tqdm=show_progress,
            max_concurrent_tasks=max_concurrent,
            max_connections=max_concurrent,
            max_keepalive_connections=max_concurrent,
        )
    except Exception:
        logger.warning("FedInvest prewarm failed -- falling back to per-date fetch", exc_info=True)


def _ust_universe_cusips(as_of_date: datetime.date, *, min_ttm: float = 0.5) -> List[str]:
    """The CUSIP universe for ``as_of_date`` -- see module docstring, item 1.

    Inlines ``carry_roll.expand_pricer_universe_for_carry_roll``'s
    reference-data-and-filter logic (for the empty-seed-pricers case, which
    is all this module ever needs) without its final, expensive step of
    building a full pricer for every CUSIP just to read off the dict keys.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    ql_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    ref_df = ql_mdp.get_bond_reference_data(as_of_date=as_of_date)
    if ref_df is None or ref_df.empty:
        return []
    ref_df = ref_df.copy().drop(columns=["record_date"], errors="ignore")
    if "ttm" in ref_df.columns:
        ref_df["ttm"] = pd.to_numeric(ref_df["ttm"], errors="coerce")
        ref_df = ref_df[ref_df["ttm"] >= float(min_ttm)].copy()
    ref_df["cusip"] = ref_df["cusip"].astype(str)
    if "rank" in ref_df.columns:
        rank = pd.to_numeric(ref_df["rank"], errors="coerce")
        ref_df = ref_df.loc[~rank.isin([0, 1, 2])].copy()
    ref_df = ref_df.drop_duplicates(subset=["cusip"], keep="last")
    return ref_df["cusip"].tolist()


def _bond_rows_from_pricers(pricers: Dict[str, object], as_of_date: datetime.date) -> List[dict]:
    """Mirrors ``compute_spline_for_date``'s row construction, except ``ttm``
    is computed locally (Act/365, ``(maturity - as_of).days / 365.0``)
    instead of via the broken ``pricer.time_to_maturity()`` -- see the
    module docstring, item 2.
    """
    rows: List[dict] = []
    for cusip, pricer in pricers.items():
        try:
            ttm = (pricer.maturity_date() - as_of_date).days / 365.0
            ytm_val = float(pricer.ytm())
            meta = pricer.meta() if hasattr(pricer, "meta") else {}
            rank = None
            if isinstance(meta, dict):
                rank = meta.get("rank")
            elif hasattr(meta, "rank"):
                rank = meta.rank
            row: dict = {
                "cusip": str(meta.get("cusip", cusip) if isinstance(meta, dict) else cusip),
                "ttm": ttm,
                "ytm": ytm_val,
            }
            if rank is not None:
                row["rank"] = rank
            rows.append(row)
        except Exception:
            continue
    return rows


def _fit_spline_local(pricers: Dict[str, object], as_of_date: datetime.date, config=None):
    """Cache-aware spline fit for RL pricers, sharing ``compute_spline_for_date``'s
    disk cache but with the ``ttm`` workaround from ``_bond_rows_from_pricers``.
    """
    from MDP.FixedRateBonds.cash_spline import (
        CashSplineBuilder,
        JPM_PAR_CURVE_CONFIG,
        get_cached_spline,
        put_cached_spline,
    )

    if config is None:
        config = JPM_PAR_CURVE_CONFIG

    cached = get_cached_spline(as_of_date, config)
    if cached is not None:
        return cached

    if not pricers:
        return None

    rows = _bond_rows_from_pricers(pricers, as_of_date)
    if not rows:
        return None

    bond_df = pd.DataFrame(rows)
    builder = CashSplineBuilder(config)
    try:
        spline = builder.fit(
            ttm=bond_df["ttm"].to_numpy(),
            y=bond_df["ytm"].to_numpy(),
            cusips=bond_df["cusip"].to_numpy(),
            ranks=bond_df["rank"].to_numpy() if "rank" in bond_df.columns else None,
            weights=None,
            as_of_date=as_of_date,
        )
    except Exception:
        logger.warning("spline fit failed for %s", as_of_date, exc_info=True)
        return None

    put_cached_spline(spline)
    return spline


def spline_map(
    dates: Sequence[datetime.date],
    *,
    cache_path: Optional[Path] = None,
    show_progress: bool = True,
    checkpoint_every: int = 50,
    prewarm: bool = True,
) -> Dict[datetime.date, object]:
    """Build (or load from cache) ``{date: CashSpline}`` for every ``dates``.

    Dates the pricer universe cannot resolve (holidays, upstream gaps) are
    stored with a ``None`` value -- present, not silently missing, and not
    retried on every subsequent call. ``treasury_forwards.treasury_forward_panel``
    already skips ``None`` entries.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
    dates = sorted(set(dates))
    cache = _load_cache(cache_path)

    missing = [d for d in dates if d not in cache]
    if not missing:
        return {d: cache[d] for d in dates}

    holidays = [d for d in missing if not _is_ust_business_day(d)]
    for d in holidays:
        cache[d] = None
    missing = [d for d in missing if _is_ust_business_day(d)]
    if holidays:
        logger.info("spline_map: %d requested dates are UST-calendar holidays, skipped", len(holidays))

    if not missing:
        _write_cache_atomic(cache, cache_path)
        return {d: cache[d] for d in dates}

    logger.info("spline_map: %d/%d requested dates missing from cache", len(missing), len(dates))

    usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")

    if prewarm:
        _prewarm_fedinvest(usts_mdp, missing, show_progress=show_progress)

    iterator = missing
    if show_progress:
        from tqdm import tqdm

        iterator = tqdm(missing, desc="Fitting UST splines")

    built_since_checkpoint = 0
    n_done = 0
    t_start = time.time()
    for d in iterator:
        try:
            cusips = _ust_universe_cusips(d)
            if not cusips:
                cache[d] = None
                continue
            rl_pricers = usts_mdp.get_pricer({"cusips": cusips, "timestamp": d})
            spline = _fit_spline_local(rl_pricers, d)
            cache[d] = spline
        except Exception:
            logger.warning("spline_map: failed to build spline for %s", d, exc_info=True)
            cache[d] = None

        n_done += 1
        built_since_checkpoint += 1
        if checkpoint_every and built_since_checkpoint >= checkpoint_every:
            _write_cache_atomic(cache, cache_path)
            built_since_checkpoint = 0
            elapsed = time.time() - t_start
            print(
                f"PROGRESS: checkpoint {d.isoformat()} -- {n_done}/{len(missing)} attempted "
                f"({elapsed:.0f}s elapsed, {elapsed / max(n_done, 1):.2f}s/date)",
                flush=True,
            )

    _write_cache_atomic(cache, cache_path)
    return {d: cache[d] for d in dates}
