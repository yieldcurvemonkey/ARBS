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


def warm_pricer(pricer, demand, max_workers=8, on_error="skip"):
    """Concurrently build every curve in ``demand`` into ``pricer._handles``.

    Failures are isolated (key left absent) so the classifier falls back to its
    normal lazy build and emits the usual ``PRICING_ERROR`` flag — unchanged
    behavior. Returns counts ``{"built", "reused", "failed"}``.
    """
    todo = [k for k in demand if k not in pricer._handles]
    reused = len(demand) - len(todo)
    if not todo:
        return {"built": 0, "reused": reused, "failed": 0}
    built = failed = 0
    with _cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(pricer._mdp._get_curve, curve_name=cn, timestamp=ts): (cn, ts)
                for cn, ts in todo}
        for fut in _cf.as_completed(futs):
            key = futs[fut]
            try:
                pricer._handles[key] = fut.result()
                built += 1
            except Exception:
                failed += 1
                if on_error != "skip":
                    raise
    return {"built": built, "reused": reused, "failed": failed}
