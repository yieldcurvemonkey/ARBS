"""Which instant to price at, and which curve is allowed to answer.

Three separate problems live here and each has a measured failure behind it:

1. **Which reported timestamp is the trade time** -- not always field #96.
2. **How far back a snapshot may be served from** -- session-dependent, not a
   single tolerance.
3. **Which instants are unaskable** -- exact midnight, and the 00:xx ET hour.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytz

from SDRUtils.stir_flow.pricing import as_intraday_instant, is_ambiguous_midnight

NY = pytz.timezone("America/New_York")

#: Curve names on the citivelo minute source, by tape ``rate_index_clean``.
#: NOT ``stir_flow.config.CURVE_FOR``, which holds Barchart names.
CURVE_FOR = {
    "SOFR": "USD-SOFR-1D",
    "FED_FUNDS": "USD-FEDFUNDS-1D",
}

#: The MDP source. **Must be an RL token.** ``IRSwapsMDP._build_citivelo_excel_curve``
#: gates ``_store_eligible`` on ``backend == "rl"``, so a ``-QL`` spelling never
#: consults the minute store at all and a strict policy then misses on *every*
#: request -- which is indistinguishable from a cold store, and was.
CURVE_SOURCE = "CITIVELO_EXCEL"

#: The old source, kept so the logic tie-out can hold the curve constant while
#: varying the code. See LEDGER D11: the two measurements each vary one thing.
LEGACY_CURVE_SOURCE = "BARCHART_STIRF-RL"

#: Citi publishes nothing between 23:00 and 00:59 ET. Outside the session a
#: bounded backward ``asof`` is accepted; the desk priced that at 0.24-0.29 bp
#: median, <=1.43 bp max -- roughly 3x cheaper than an equivalent 120-minute
#: stretch of the trading day, and stale rather than circular.
OUT_OF_SESSION_MAX_LAG = datetime.timedelta(hours=2)

#: Inside the session, the snapshot must be the minute asked for.
IN_SESSION_MAX_LAG = datetime.timedelta(minutes=1)

# --- pricing-clock provenance values --------------------------------------
CLOCK_EXECUTION = "execution_timestamp"
CLOCK_EVENT = "event_timestamp"
CLOCK_EOD_FALLBACK = "event_timestamp_date_only"


class NoPricingInstant(ValueError):
    """The row does not carry a usable trade time."""


def pricing_timestamp(row) -> tuple[pd.Timestamp | datetime.date, str]:
    """The instant to price at, and which field it came from.

    **Field #96 is not the trade time on a lifecycle print.** The spec defines
    Execution timestamp as "the date and time a transaction was originally
    executed... This data element remains unchanged throughout the life of the
    UTI", and Appendix F Example 3 shows it exactly: a TERM-ETRM row carries
    event timestamp ``2019-12-12T14:57:10Z`` against execution timestamp
    ``2018-04-01T14:15:36Z`` -- twenty months stale. Pricing that row at #96
    values an unwind against a curve from years before the unwind.

    Confirmed independently on live data: for the 613 raw terminations that
    resolve to a tape row, the termination's own Execution Timestamp equals the
    *original's* execution timestamp to under a second in 95.3% of cases.

    So: rows that mint a new UTI keep #96 (for them #30 equals it anyway);
    every other row prices on #30.

    The midnight trap has a second entrance here. Spec footnote 39 says #30 may
    carry ``00:00:00`` when the time portion is unavailable, and
    ``event_timestamp_granularity`` records that. A date-only #30 cannot be
    nudged into an instant -- there is no instant to nudge -- so it is returned
    as a ``datetime.date``, which every curve source unambiguously reads as
    end-of-day. That is a deliberate, flagged degradation rather than a
    fabricated intraday time, and the caller records
    :data:`CLOCK_EOD_FALLBACK` in provenance so the row can be gated out.
    """
    mints_new_uti = _mints_new_uti(row)
    if mints_new_uti:
        ts = _first_present(row, "original_execution_timestamp", "execution_timestamp")
        field = CLOCK_EXECUTION
    else:
        ts = _first_present(row, "event_timestamp")
        field = CLOCK_EVENT
        if ts is None:
            # No event stamp on a lifecycle row: #96 is the only thing left and
            # it is known-stale. Refuse rather than price against it silently.
            raise NoPricingInstant(
                f"lifecycle row {row.get('trade_id')!r} has no event_timestamp, "
                "and its execution_timestamp is frozen at the original trade"
            )
    if ts is None:
        raise NoPricingInstant(f"row {row.get('trade_id')!r} carries no usable trade time")

    granularity = row.get("event_timestamp_granularity")
    if field == CLOCK_EVENT and _is_date_only(ts, granularity):
        # The reported date, in the frame it was reported in. Converting to New
        # York first would hand back the PREVIOUS calendar day for a 00:00:00Z
        # stamp, i.e. a whole day of lookbehind introduced by a timezone.
        t = pd.Timestamp(ts)
        t = t.tz_convert("UTC") if t.tzinfo is not None else t
        return t.date(), CLOCK_EOD_FALLBACK
    return pd.Timestamp(ts), field


def _mints_new_uti(row) -> bool:
    """Does this print create a new UTI, making #96 the event time?

    ``NEWT`` does, including ``NEWT-NOVA`` / ``-COMP`` / ``-CLRG`` / ``-EXER``.
    ``TERM`` / ``MODI`` / ``CORR`` / ``EROR`` / ``REVI`` do not.

    The tape does not persist raw action type -- the area guide is explicit
    that aggregators must never re-parse it -- so this reads the enrichment:
    ``lifecycle_type`` plus the economic class. ``NEW_TRADE`` is the
    UTI-minting case.
    """
    lifecycle = row.get("lifecycle_type")
    if lifecycle is None or (isinstance(lifecycle, float) and lifecycle != lifecycle):
        # Unknown lifecycle: assume it is NOT a new trade, because that routes
        # to #30, and #30 is correct for a NEWT row too (it equals #96 there).
        # The reverse default would price an unrecognised lifecycle row against
        # a years-stale curve.
        return False
    return str(lifecycle) == "NEW_TRADE"


def _first_present(row, *cols):
    for c in cols:
        v = row.get(c)
        if v is not None and not pd.isna(v):
            return v
    return None


def _is_date_only(ts, granularity) -> bool:
    """Is this event stamp really a date, reported as ``00:00:00``?

    Tested **in the reported frame (UTC), not converted to New York.** Spec
    footnote 39 says "if the time portion is not available, report
    '00:00:00'", and that zero is written in the field's own UTC clock. A
    genuine 00:00:00Z converts to 19:00 or 20:00 ET, so converting first makes
    the test never fire -- which is what the first draft did.

    The mirror error is just as easy: an ordinary 20:00 ET print *is*
    00:00:00Z, so this test alone would call it date-only. That is why
    ``event_timestamp_granularity`` is consulted first and wins when it is
    populated; the wall-clock test is only the fallback for rows where the
    enrichment did not record a granularity.
    """
    if granularity is not None and not pd.isna(granularity):
        return str(granularity).upper() in {"DATE", "DAY", "DATE_ONLY"}
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC")
    return (t.hour, t.minute, t.second, t.microsecond) == (0, 0, 0, 0)


def snap_instant(trade_ts):
    """Floor the trade time to the minute in New York, then step back one.

    The T-1min rule. Kept in ``America/New_York`` throughout and deliberately
    **not** normalised to UTC: ``is_ambiguous_midnight`` tests the wall clock of
    whatever object it is handed, so an ordinary 20:00 ET snap is 00:00 UTC and
    trips ``CurvePricer``'s midnight guard with "which is exactly midnight".
    That fired for real on 2026-03-31.

    A ``datetime.date`` passes straight through -- it already means end-of-day
    to every source, which is the deliberate degradation
    :func:`pricing_timestamp` chose for a date-only event stamp.
    """
    if isinstance(trade_ts, datetime.date) and not isinstance(trade_ts, datetime.datetime):
        return trade_ts
    t = pd.Timestamp(trade_ts)
    et = t.tz_convert(NY) if t.tzinfo is not None else NY.localize(t.to_pydatetime())
    et = et.replace(second=0, microsecond=0) - pd.Timedelta(minutes=1)
    return as_intraday_instant(
        NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))
    )


def alternative_snaps(trade_ts, offsets=(5, 30)):
    """The same instant at ``-5s`` and ``-30s``, for the snap-sensitivity test.

    T-1min is the stated rule, but it is one arbitrary choice. If classification
    differs materially at five seconds, that is worth knowing before a ladder is
    built on it. Returns ``{seconds: instant}``; midnight-nudged like the main
    rule, and date-only inputs return empty because there is no sub-minute
    structure to vary.
    """
    if isinstance(trade_ts, datetime.date) and not isinstance(trade_ts, datetime.datetime):
        return {}
    t = pd.Timestamp(trade_ts)
    et = t.tz_convert(NY) if t.tzinfo is not None else NY.localize(t.to_pydatetime())
    out = {}
    for secs in offsets:
        shifted = et - pd.Timedelta(seconds=secs)
        out[secs] = as_intraday_instant(
            NY.localize(datetime.datetime(
                shifted.year, shifted.month, shifted.day,
                shifted.hour, shifted.minute, shifted.second,
            ))
        )
    return out


def in_session(curve_name: str, instant) -> bool:
    """Is this instant inside Citi's publication session for this curve?

    Delegates to the measured session model rather than re-deriving it. The
    week runs on a UTC clock (Sunday 21:00 to Friday 21:59) and the day on a
    New York one (01:00-22:59 ET), which is not a rule anyone would guess.

    ``curve_name`` is required, not optional -- the session is a property of
    the curve Citi is publishing, and ``citi_session.publishes`` takes it.
    """
    if isinstance(instant, datetime.date) and not isinstance(instant, datetime.datetime):
        return False
    from MDP.IRSwaps.CITIVELO_EXCEL import citi_session

    return bool(citi_session.publishes(curve_name, pd.Timestamp(instant)))


def policy_for(curve_name: str, instant):
    """The snapshot policy this instant is allowed to be answered under.

    **Branch on the session, do not set a global tolerance.** Accepting
    two-hour staleness overnight is defensible -- Citi publishes nothing
    between 23:00 and 00:59 ET, so the alternative is losing every print in the
    00:xx hour permanently, and a stale curve is at least not circular. But the
    same tolerance applied globally admits two-hour staleness at 10:00 on a
    Tuesday, which is worth 2.63 bp at p90.

    That is not a hypothetical. On 2026-06-01 there is a 30-minute *in-session*
    gap: a global ``max_lag=2h`` serves a probe at 19:33 ET from a curve 15
    minutes stale, while this branch refuses it. And on the night after a
    truncated session (128 such SOFR days), the 2h bound is what stops a 4.5
    hour reach-back.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy

    if in_session(curve_name, instant):
        return SnapshotPolicy.strict(minutes=int(IN_SESSION_MAX_LAG.total_seconds() // 60))
    return SnapshotPolicy(
        method="asof",
        max_lag=OUT_OF_SESSION_MAX_LAG,
        allow_future=False,
        on_miss="raise",
    )


def snapshot_lag_seconds(handle) -> float | None:
    """Realised staleness of the served curve, from the handle's own metadata.

    ``RLIRSwapCurve`` exposes ``.meta()``, **not** ``.meta_data``. A
    ``getattr(handle, "meta_data", None)`` returns ``None`` silently, so every
    lag reads as missing while the prices look perfectly fine -- a whole strict
    run reported ``lag=None`` on every row and was otherwise indistinguishable
    from a correct one. The session branch *relies* on this value, so a silent
    ``None`` is a monitoring failure, not a cosmetic one.
    """
    meta = None
    getter = getattr(handle, "meta", None)
    if callable(getter):
        try:
            meta = getter()
        except Exception:  # noqa: BLE001 - metadata must never break pricing
            meta = None
    if meta is None:
        meta = getattr(handle, "_meta_data", None) or getattr(handle, "meta_data", None)
    if not isinstance(meta, dict):
        return None
    for key in ("snapshot_lag_signed_seconds", "snapshot_lag_seconds"):
        if key in meta and meta[key] is not None:
            return float(meta[key])
    return None


def served_from_future(handle) -> bool | None:
    """Did the served snapshot come from after the instant asked for?

    Always ``False`` under a backward-only policy. Checked anyway, because a
    curve from after the print contains the print, which makes the direction
    call circular in the one way this whole exercise exists to prevent.
    """
    meta = None
    getter = getattr(handle, "meta", None)
    if callable(getter):
        try:
            meta = getter()
        except Exception:  # noqa: BLE001
            meta = None
    if not isinstance(meta, dict):
        return None
    v = meta.get("snapshot_served_from_future")
    return None if v is None else bool(v)


__all__ = [
    "CLOCK_EOD_FALLBACK", "CLOCK_EVENT", "CLOCK_EXECUTION", "CURVE_FOR",
    "CURVE_SOURCE", "IN_SESSION_MAX_LAG", "LEGACY_CURVE_SOURCE",
    "NoPricingInstant", "OUT_OF_SESSION_MAX_LAG", "alternative_snaps",
    "in_session", "is_ambiguous_midnight", "policy_for", "pricing_timestamp",
    "served_from_future", "snap_instant", "snapshot_lag_seconds",
]
