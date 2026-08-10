"""Decoupled curve acquisition for the dealer-direction backfill.

The classifier's cost is dominated by building one curve per distinct
``(curve_name, snapped_minute)`` lazily inside each leg's pricing call (~77% of
wall time, almost all network I/O). This module separates *acquisition* from
*classification*:

- :func:`enumerate_curve_demand` computes the exact set of curves a day needs.
- :func:`warm_pricer` builds them concurrently and pre-populates a
  :class:`~SDRUtils.stir_flow.pricing.CurvePricer` handle cache.

Warming uses a **thread** pool, not processes: the work is network-bound (the
GIL is released during Supabase/Barchart I/O), so threads overlap the waits
while keeping the math byte-for-byte identical (each build is the same
``_get_curve`` call, just concurrent) and avoiding Windows ``spawn`` cost and
pickling of the lock/diskcache/HTTP-laden builder. Concurrency is capped to
stay clear of the known Barchart 429 storm on ``BARCHART_STIRF-RL``.
"""
from __future__ import annotations

import concurrent.futures as _cf

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow.pricing import snap_timestamp


def unit_curve_and_snap(unit):
    """``(curve_name, snapped_ts)`` for a unit, exactly as ``_unit_meta`` derives.

    Single source of truth so the demand set and the classifier price against
    identical curve snapshots (bit-identical mandate).
    """
    first = unit.legs.iloc[0]
    curve_name = config.CURVE_FOR[first["rate_index_clean"]]
    snap = snap_timestamp(first.get("original_execution_timestamp"),
                          first["execution_timestamp"])
    return curve_name, snap


def enumerate_curve_demand(units):
    """Deduplicated set of ``(curve_name, snapped_ts)`` a day's units require."""
    return {unit_curve_and_snap(u) for u in units}


def _bulk_seed(pricer, todo, n_jobs):
    """Seed ``pricer._handles`` with one ``bulk_get_data`` call per curve.

    WHY THIS EXISTS. The per-minute path costs one Barchart request PER
    INSTRUMENT PER MINUTE: 24 instruments for the SOFR ladder curve, 36 for the
    FF one. Barchart's intraday origin allows ~55 requests per rolling minute, so
    a single curve-minute consumes roughly the whole quota and a 479-minute day
    needs ~28,700 requests — about eight hours of quota per trading day even with
    perfect pacing. The rate limiter is constructed per ``barchart_timeseries_api``
    call rather than per process, so running several warm threads across several
    day-workers simply bursts through the ceiling and parks every worker in
    ``Retry-After`` sleeps: measured ~5% CPU with 19 sockets open and no progress.

    ``bulk_get_data`` fetches the WHOLE session once (``full_day_intraday``) and
    reuses those bars across every requested minute, so the same day costs ~60
    requests instead of ~28,700, then persists the calibrated day into the local
    CurveStore so any re-run is a local Parquet read. This mattered because the
    SOFR ladder curve had exactly ONE day in the store against the FF curve's
    1376: every SOFR minute missed, and the barchart single-point path never
    writes back, so it would have missed forever.

    Value-identical to the per-minute path: both end at the same
    ``_build_barchart_stirf_rl_curve`` over the same calibrated nodes. Pinned by a
    network golden in tests/test_stir_curve_warm.py.

    Returns the number of handles seeded. Any failure is swallowed: the caller's
    per-minute pass then rebuilds whatever is still missing, so a bulk problem can
    only cost time, never correctness.
    """
    import collections

    import pandas as pd

    by_curve = collections.defaultdict(list)
    for cn, ts in todo:
        by_curve[cn].append(ts)

    seeded = 0
    for cn, ts_list in by_curve.items():
        try:
            # bulk_get_data POPS from the request dict, so hand it a fresh one.
            # The pricer's own curve_kwargs go in: a warmed handle is served from
            # the cache thereafter, so seeding on different terms than
            # ``CurvePricer.handle`` would build under silently overrides them.
            curves = pricer._mdp.bulk_get_data({
                **getattr(pricer, "curve_kwargs", {}),
                "curve_name": cn,
                "timestamps": sorted(ts_list),
                "n_jobs": int(n_jobs),
                "calibration_executor": "thread",
            })
        except Exception:
            continue
        # match on timestamp VALUE: the batch path may key by a different but
        # equal timestamp type than the tuple key the pricer caches under
        got = {}
        for key, handle in (curves or {}).items():
            try:
                got[pd.Timestamp(key)] = handle
            except (TypeError, ValueError):
                continue
        for ts in ts_list:
            handle = got.get(pd.Timestamp(ts))
            if handle is not None:
                pricer._handles[(cn, ts)] = handle
                seeded += 1
    return seeded


def warm_pricer(pricer, demand, max_workers=8, on_error="skip", bulk=True):
    """Build every curve in ``demand`` into ``pricer._handles``.

    Two stages. First one ``bulk_get_data`` per curve, which turns ~479 vendor
    round trips per curve-day into ~1 (see ``_bulk_seed``). Then the original
    per-minute thread pool mops up whatever bulk did not cover.

    Failures are isolated (key left absent) so the classifier falls back to its
    normal lazy build and emits the usual ``PRICING_ERROR`` flag — unchanged
    behavior. Returns counts ``{"built", "reused", "failed", "bulk_seeded"}``.
    """
    todo = [k for k in demand if k not in pricer._handles]
    reused = len(demand) - len(todo)
    if not todo:
        return {"built": 0, "reused": reused, "failed": 0, "bulk_seeded": 0}

    bulk_seeded = _bulk_seed(pricer, todo, max_workers) if bulk else 0
    todo = [k for k in todo if k not in pricer._handles]

    built = failed = 0
    if todo:
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            # ``pricer.build``, not ``_get_curve`` - the warmer writes straight
            # into ``_handles``, so building on any other terms than the ones
            # ``handle`` would use silently overrides the pricer's policy for
            # every minute it warms.
            futs = {ex.submit(pricer.build, cn, ts): (cn, ts) for cn, ts in todo}
            for fut in _cf.as_completed(futs):
                key = futs[fut]
                try:
                    pricer._handles[key] = fut.result()
                    built += 1
                except Exception:
                    failed += 1
                    if on_error != "skip":
                        raise
    return {"built": built, "reused": reused, "failed": failed,
            "bulk_seeded": bulk_seeded}
