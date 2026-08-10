"""Curve snapshot rule + IRSwapQuery pricing wrapper (spec sections 3-4)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytz

from SDRUtils.stir_flow import config

NY = pytz.timezone("America/New_York")


def as_intraday_instant(et_instant):
    """An ET instant that no curve API can mistake for "that day's close".

    **Exact midnight is overloaded and does not mean what this module means by
    it.** ``MDP/IRSwaps/CITIVELO_EXCEL/timestamps.py::resolve_request`` reads a
    datetime at exactly 00:00:00 as **end of day** - deliberately, because
    ``pd.Timestamp("2026-08-06")`` is the common spelling of "that day" and the
    add-in stamps its own DAILY rows at midnight. That rule is right for the API
    it belongs to and is not being changed here.

    But the snapshot rules in this package produce exact midnight from ordinary
    prints - ``snap_timestamp`` for anything printed in the 00:01 ET minute,
    ``book.snap_mtm`` for anything in the 00:00 ET minute - and they mean *an
    instant*. Handing that value to the citivelo_excel source routes it to the
    end-of-day branch, which serves **that day's close: roughly sixteen hours
    AFTER the print**. For dealer direction that is not staleness, it is
    lookahead - the close of day D contains the very trade being classified, so
    the inference becomes circular in the one way the whole exercise exists to
    prevent.

    Measured on the ``_v3`` tape: 256 SOFR legs and 3 Fed Funds legs snap to
    exact midnight. Small, and completely silent - no exception, no warning, a
    plausible curve.

    The fix is the escape hatch ``resolve_request`` itself documents: *"To
    request an intraday curve at exactly midnight - which is a real instant, if
    an illiquid one - ask for 00:00:01."* So this nudges **only** exact midnight,
    by one second, and returns every other instant untouched. At minute
    resolution the two are the same request: 00:00:00 and 00:00:01 fall in the
    same minute, and every selection rule - nearest or as-of - resolves them to
    the same stored snapshot. The only thing that changes is which *mode* the
    request is classified as, which is the entire bug.

    Not applied to a bare ``datetime.date``, which unambiguously means EOD to
    every source and is a legitimate thing to ask for.
    """
    if not is_ambiguous_midnight(et_instant):
        return et_instant
    # pytz's own advice is to normalise after arithmetic, but one second past
    # midnight cannot cross a US DST transition - those happen at 02:00 local -
    # so the offset the value was localised with is still the right one, and
    # normalising would be a no-op that implies otherwise.
    return et_instant + datetime.timedelta(seconds=1)


def is_ambiguous_midnight(ts) -> bool:
    """Would this value be read as end-of-day by a source that overloads midnight?

    ``True`` only for a wall-clock value at exactly 00:00:00.000. A
    ``datetime.date`` is not ambiguous - it means EOD to everything, on purpose.

    Two deliberate details:

    * The test is ``(hour, minute, second, microsecond)``, **not** including
      nanosecond, because that is exactly what ``resolve_request`` tests. The
      job here is to predict what the *consumer* will do, so matching its rule
      matters more than being independently stricter.
    * Only genuinely date-like inputs are considered. ``pd.Timestamp(42)`` is
      42 nanoseconds past the epoch - hour, minute, second and microsecond all
      zero - so parsing anything that pandas accepts would call a plain integer
      "midnight" and then fail trying to add a second to it. Found by a test
      that passed ``42`` on the way past.
    """
    import numpy as np

    if isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime):
        return False
    if not isinstance(ts, (datetime.datetime, np.datetime64, str)):
        return False
    try:
        t = pd.Timestamp(ts)
    except (TypeError, ValueError):
        return False                      # "live", and anything unparseable
    if t is pd.NaT:
        return False
    return (t.hour, t.minute, t.second, t.microsecond) == (0, 0, 0, 0)


def snap_timestamp(orig_ts, exec_ts):
    """The classifier's curve instant: floor the print to the minute, minus one.

    Routed through :func:`as_intraday_instant` so a print in the 00:01 ET minute
    - which floors-and-decrements to exactly midnight - cannot be read as a
    request for that day's close.
    """
    ts = orig_ts
    if ts is None or (isinstance(ts, float) and ts != ts) or pd.isna(ts):
        ts = exec_ts
    et = pd.Timestamp(ts).tz_convert(NY)
    et = et.replace(second=0, microsecond=0) - pd.Timedelta(minutes=1)
    return as_intraday_instant(
        NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))
    )


@dataclasses.dataclass
class LegPricing:
    mid_pct: float
    npv_pay: float | None
    pv01: float


class CurvePricer:
    """Memoised curve handles for the direction classifier.

    ``curve_kwargs`` is passed through to ``IRSwapsMDP._get_curve`` on every
    build, and is fixed for the life of the instance. That is deliberate: it is
    how a caller says "serve me a snapshot at or before this minute, within this
    tolerance, and raise if you cannot" (see
    ``MDP/IRSwaps/CITIVELO_EXCEL/snapshot_policy.SnapshotPolicy``), and a
    per-call spelling would be unsound here - ``_handles`` is keyed on
    ``(curve_name, ts)``, so the first caller's terms would be silently reused
    for the next caller's request for the same minute. Per-instance means the
    cache key and the terms cannot disagree.
    """

    def __init__(self, mdp=None, *, curve_kwargs: dict | None = None):
        if mdp is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            mdp = IRSwapsMDP(source=config.CURVE_SOURCE)
        self._mdp = mdp
        self._curve_kwargs = dict(curve_kwargs or {})
        self._handles: dict = {}

    @property
    def curve_kwargs(self) -> dict:
        """The terms every curve on this pricer is built under. Read-only copy."""
        return dict(self._curve_kwargs)

    def build(self, curve_name: str, ts):
        """Build one curve under this pricer's terms, WITHOUT touching the cache.

        Refuses a *datetime* at exactly midnight. Every timestamp reaching this
        pricer is meant to be an instant, and midnight is the one value a source
        may read as end-of-day instead - serving the day's close, hours after the
        print. :func:`as_intraday_instant` removes it at both producers
        (``snap_timestamp`` and ``book.snap_mtm``), so this guard should be
        unreachable; it exists because the next snapshot rule someone writes will
        not know about the collision, and a loud refusal here beats a plausible
        curve from sixteen hours in the future.

        Public because the warmer (``curve_warm.warm_pricer``) pre-populates
        ``_handles`` directly, and it must build on the same terms ``handle``
        would. It previously called ``_get_curve`` itself, which meant a pricer
        carrying a strict snapshot policy got its cache seeded with
        legacy-selected curves and then served them - the cache key and the terms
        disagreeing, which is the failure the per-instance design was chosen to
        avoid. One method, both callers.
        """
        self._reject_ambiguous(curve_name, ts)
        # Only pass `kwargs` when there is something to say. `mdp` is routinely a
        # stand-in - a fake in tests, a narrower wrapper in the backtests - and
        # widening the call for every caller in order to serve the one that set
        # curve_kwargs would break those for no gain.
        extra = {"kwargs": dict(self._curve_kwargs)} if self._curve_kwargs else {}
        return self._mdp._get_curve(curve_name=curve_name, timestamp=ts, **extra)

    @staticmethod
    def _reject_ambiguous(curve_name, ts) -> None:
        if not is_ambiguous_midnight(ts):
            return
        raise ValueError(
            f"CurvePricer was asked for {curve_name!r} at {ts!r}, which is exactly "
            "midnight. Sources that overload the timestamp argument read that as "
            "END OF DAY and serve the day's close - hours AFTER the instant you "
            "meant, which makes a direction call circular. Pass "
            "SDRUtils.stir_flow.pricing.as_intraday_instant(ts) for the instant, or "
            "a datetime.date if you genuinely want the close."
        )

    def handle(self, curve_name: str, ts):
        # Checked HERE, before the cache lookup, and not only inside `build`.
        # `curve_warm.warm_pricer` and `_bulk_seed` write straight into
        # `_handles`, so a pre-seeded key is returned without `build` ever
        # running - and a guard that only lives in `build` would be bypassed by
        # exactly the path most likely to carry a bad timestamp in bulk. Same
        # shape of hole as the curve_kwargs one this class already had.
        self._reject_ambiguous(curve_name, ts)
        key = (curve_name, ts)
        if key not in self._handles:
            self._handles[key] = self.build(curve_name, ts)
        return self._handles[key]

    def price_leg(self, curve_name, ts, effective_date, maturity_date,
                  notional, fixed_rate=None) -> LegPricing:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        h = self.handle(curve_name, ts)
        skw = {"notional": float(notional)}
        if fixed_rate is not None:
            skw["fixed_rate"] = float(fixed_rate)   # decimal in, decimal through
        q = IRSwapQuery(
            curve=curve_name,
            effective_date=pd.Timestamp(effective_date).date(),
            maturity_date=pd.Timestamp(maturity_date).date(),
            structure_kwargs=skw,
        ).resolve_query(ts, pricer_or_curve=h)
        pkg, rws = q.resolve_package(pricer_or_curve=h)
        vmap = q.build_value_map(pricer_or_curve=h, package=pkg, risk_weights=rws)
        mid = float(vmap.apply(value=IRSwapValue.RATE))
        npv = float(vmap.apply(value=IRSwapValue.NPV)) if fixed_rate is not None else None
        pv01 = float(vmap.apply(value=IRSwapValue.PV01))
        return LegPricing(mid_pct=mid, npv_pay=npv, pv01=pv01)
