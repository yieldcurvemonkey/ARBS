r"""How far back does Citi serve INTRADAY, and can ``CVSNAP`` reach past it?

This settles the three facts a ten-year minute-resolution backfill depends on,
none of which is currently measured:

1. **Where each instrument's history actually starts.** SOFR OIS cannot have ten
   years - the index was first published in 2018 - and ESTR started in October
   2019. A backfill that silently delivers three years where ten were asked for
   is worse than one that says which curves can and cannot go the distance.
2. **``CVTSHIST``'s intraday RETENTION floor, per frequency.** The add-in
   downsamples by requested *span*, and that is already handled by
   :mod:`MDP.CitiVelocityExcel.windowed`. Retention is a different axis and has
   only ever been measured to about a year (``windowed.py``) or four
   (``docs/citivelo_intraday_ts_warm.md``). This walks a span-safe window back
   through a decade and measures the **median spacing** of what comes back,
   because a request past the floor returns a healthy-looking block of daily rows
   rather than an error.
3. **Whether ``CVSNAP`` reads a different store than ``CVTSHIST``.** ``CVSNAP``
   takes a ``yyyyMMddHHmm`` stamp and returns a bare value with **no timestamp**
   of its own, so it cannot say what it served. The decisive test is therefore a
   *pair*: two stamps on the same historical day, hours apart. If they are equal,
   ``CVSNAP`` is serving that day's single print and carries no intraday
   information at all - and a snap-driven backfill would manufacture flat curves
   that look like data. If they differ, it is genuinely intraday and the only
   remaining question is cost.

Read the answers as a BOUNDARY per curve and per frequency, never pooled. A
frequency that serves at five years and not at seven brackets the floor; an
average over both hides it.

Cost and etiquette
------------------
It TOUCHES EXCEL - the user's own signed-in process, which only a human restart
clears. Every stage is bounded and counted, the memory guard runs before
connecting, and the default full run is roughly 120 ``CV*`` calls at ~1-2 s each.

::

    python scripts/citivelo_snap_depth_probe.py --stage selfcheck
    python scripts/citivelo_snap_depth_probe.py --stage all --out probe.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
import time
import zoneinfo
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

log = logging.getLogger("citivelo-snap-depth-probe")

WIRE_TZ = "America/New_York"

#: Below the measured wedge point, same headroom the warms use.
WORKING_CEILING_MB = 3500.0


class Probe:
    """One curve family under test, and the session it publishes in."""

    def __init__(self, key: str, tag_10y: str, tag_2y: str, tz: str) -> None:
        self.key = key
        self.tag_10y = tag_10y
        self.tag_2y = tag_2y
        self.tz = tz

    def __repr__(self) -> str:  # pragma: no cover - operator sugar
        return f"<Probe {self.key} {self.tag_10y}>"


#: The five instruments the ten-year request names, plus the LCH TONAR variant
#: because ``JPY_TONAR`` and ``JPY_TONAR_LCH`` are different curves and only one
#: of them may retain intraday history.
PROBES: Tuple[Probe, ...] = (
    Probe("USD_SOFR", "RATES.OIS.USD_SOFR.PAR.10Y", "RATES.OIS.USD_SOFR.PAR.2Y", "America/New_York"),
    Probe("USD_FEDFUND", "RATES.OIS.USD_FEDFUND.PAR.10Y", "RATES.OIS.USD_FEDFUND.PAR.2Y", "America/New_York"),
    Probe("EUR_EUROSTR", "RATES.OIS.EUR_EUROSTR.PAR.10Y", "RATES.OIS.EUR_EUROSTR.PAR.2Y", "Europe/Berlin"),
    Probe("EUR_EURIBOR", "RATES.SWAP_LIBOR.EUR.PAR.10Y", "RATES.SWAP_LIBOR.EUR.PAR.2Y", "Europe/Berlin"),
    Probe("JPY_TONAR", "RATES.OIS.JPY_TONAR.PAR.10Y", "RATES.OIS.JPY_TONAR.PAR.2Y", "Asia/Tokyo"),
    Probe("JPY_TONAR_LCH", "RATES.OIS.JPY_TONAR_LCH.PAR.10Y", "RATES.OIS.JPY_TONAR_LCH.PAR.2Y", "Asia/Tokyo"),
    # Not one of the five requested curves, but the one that decides whether a
    # pre-2021 EURIBOR curve can be OIS-discounted at all: ESTR's intraday
    # history starts 2021-09-15 and EONIA is the euro OIS index before it.
    Probe("EUR_EONIA", "RATES.OIS.EUR_EONIA.PAR.10Y", "RATES.OIS.EUR_EONIA.PAR.2Y", "Europe/Berlin"),
)

#: How far back each stage walks, in years. Spread rather than contiguous: a
#: depth that serves and one that does not BRACKET the floor, and the bracket is
#: the answer. Refine with ``--depths`` once the bracket is known.
DEFAULT_DEPTHS: Tuple[float, ...] = (0.25, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0)

#: Span held strictly under each frequency's measured downsampling cliff, so a
#: coarse answer means RETENTION and not the span rule.
SAFE_SPAN_DAYS: Dict[str, int] = {"MI01": 4, "MI10": 30, "HOURLY": 60}

#: What each frequency is supposed to come back with.
TARGET_MINUTES: Dict[str, float] = {"MI01": 1.0, "MI10": 10.0, "HOURLY": 60.0}


# --------------------------------------------------------------------------- #
#                                  helpers                                     #
# --------------------------------------------------------------------------- #


def _business_day_back(years: float, *, anchor: Optional[datetime.date] = None) -> datetime.date:
    """A Wednesday roughly ``years`` back - mid-week, so holidays are unlikely."""
    base = (anchor or datetime.date.today()) - datetime.timedelta(days=round(years * 365.25))
    # Walk to the nearest Wednesday at or before ``base``.
    return base - datetime.timedelta(days=(base.weekday() - 2) % 7)


def _median_spacing_minutes(index: pd.Index) -> Optional[float]:
    if index is None or len(index) < 3:
        return None
    deltas = pd.Series(pd.DatetimeIndex(index)).diff().dropna()
    if deltas.empty:
        return None
    return float(deltas.median().total_seconds() / 60.0)


def _local_to_wire(day: datetime.date, hour: int, minute: int, tz: str) -> datetime.datetime:
    """The naive wire-zone (New York) instant of ``hour:minute`` local to ``tz``.

    This is the exact inverse of the wire->local bucketing the minute warm does,
    and it is the reason a snap grid can be expressed in a market's own session
    hours while the add-in is addressed in its own.
    """
    local = datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=zoneinfo.ZoneInfo(tz))
    return local.astimezone(zoneinfo.ZoneInfo(WIRE_TZ)).replace(tzinfo=None)


def _series_summary(series: Optional[pd.Series]) -> Dict[str, Any]:
    if series is None or len(series) == 0:
        return {"rows": 0}
    return {
        "rows": int(len(series)),
        "first": str(series.index.min()),
        "last": str(series.index.max()),
        "spacing_min": _median_spacing_minutes(series.index),
        "first_value": float(series.iloc[0]),
        "last_value": float(series.iloc[-1]),
    }


class CallCounter:
    """Every ``CV*`` call this probe makes, and what it cost."""

    def __init__(self) -> None:
        self.calls = 0
        self.seconds = 0.0

    def timed(self, fn, *args, **kwargs):
        started = time.time()
        try:
            return fn(*args, **kwargs)
        finally:
            self.calls += 1
            self.seconds += time.time() - started

    def as_dict(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "seconds": round(self.seconds, 1),
            "seconds_per_call": round(self.seconds / self.calls, 2) if self.calls else None,
        }


# --------------------------------------------------------------------------- #
#                                   stages                                     #
# --------------------------------------------------------------------------- #


def stage_selfcheck(client: Any, counter: CallCounter, probes: Sequence[Probe]) -> dict:
    """Run the measurement against inputs whose answers are already known.

    A checking tool that is itself wrong reports success and hides the thing it
    was built to find. Two requests with known answers, from
    ``MDP/CitiVelocityExcel/windowed.py``'s measured ladder:

    * ``MI01`` over 4 days -> **1-minute** spacing;
    * ``MI01`` over 30 days -> **10-minute** spacing (the span rule, not retention).

    If the second one comes back at 1 minute the spacing measurement is broken,
    or the add-in's ladder has changed, and every retention conclusion below is
    void either way.
    """
    tag = probes[0].tag_10y
    end = datetime.datetime.combine(_business_day_back(0.05), datetime.time(13, 0))
    out: Dict[str, Any] = {"tag": tag, "end": str(end)}

    for label, span_days, expect in (("narrow", 4, 1.0), ("wide", 30, 10.0)):
        start = end - datetime.timedelta(days=span_days)
        got = counter.timed(
            client.fetch_timeseries, [tag], freq="MI01", start=start, end=end
        )
        series = got.get(tag)
        summary = _series_summary(series)
        summary["expected_spacing_min"] = expect
        summary["agrees"] = (
            summary.get("spacing_min") is not None
            and abs(summary["spacing_min"] - expect) < 0.5 * expect
        )
        out[label] = summary
        log.info(
            "  selfcheck %-6s span=%2dd -> %s rows @ %s min (expected %s) %s",
            label, span_days, summary.get("rows"), summary.get("spacing_min"),
            expect, "OK" if summary["agrees"] else "DISAGREES",
        )

    out["ok"] = bool(out["narrow"]["agrees"] and out["wide"]["agrees"])
    return out


def stage_inception(client: Any, counter: CallCounter, probes: Sequence[Probe]) -> dict:
    """Where each instrument's DAILY history starts. One call, ``period='MAX'``.

    This is the ceiling on everything else: no intraday retention question is
    interesting before the instrument existed.
    """
    tags = [p.tag_10y for p in probes] + [p.tag_2y for p in probes]
    got = counter.timed(client.fetch_timeseries, tags, freq="DAILY", period="MAX")
    failures = dict(getattr(client, "last_failures", lambda: {})() or {})
    out: Dict[str, Any] = {"failures": failures, "curves": {}}
    for probe in probes:
        out["curves"][probe.key] = {
            "10Y": _series_summary(got.get(probe.tag_10y)),
            "2Y": _series_summary(got.get(probe.tag_2y)),
        }
        first = out["curves"][probe.key]["10Y"].get("first")
        log.info("  inception %-14s 10Y from %s (%s rows)",
                 probe.key, first, out["curves"][probe.key]["10Y"].get("rows"))
    # Keep the daily 10Y series - the snap stage compares against its closes.
    out["_daily"] = {p.key: got.get(p.tag_10y) for p in probes}
    return out


def stage_tshist(
    client: Any,
    counter: CallCounter,
    probes: Sequence[Probe],
    depths: Sequence[float],
    freqs: Sequence[str],
) -> dict:
    """Walk a span-safe window back through the decade, per frequency.

    All curves go in one request per (frequency, depth): they share the window,
    and batching them means a retention difference BETWEEN curves is measured on
    identical bounds rather than on two requests minutes apart.
    """
    tags = [p.tag_10y for p in probes]
    out: Dict[str, Any] = {}
    for freq in freqs:
        span = datetime.timedelta(days=SAFE_SPAN_DAYS[freq])
        target = TARGET_MINUTES[freq]
        per_depth: Dict[str, Any] = {}
        for years in depths:
            day = _business_day_back(years)
            end = datetime.datetime.combine(day, datetime.time(23, 59))
            start = end - span
            try:
                got = counter.timed(
                    client.fetch_timeseries, tags, freq=freq, start=start, end=end
                )
            except Exception as exc:  # noqa: BLE001 - a transport failure is not evidence
                per_depth[str(years)] = {"date": str(day), "transport_error": f"{type(exc).__name__}: {exc}"}
                log.warning("  %s @ %.2fy: TRANSPORT %s", freq, years, exc)
                continue
            block: Dict[str, Any] = {"date": str(day), "curves": {}}
            for probe in probes:
                summary = _series_summary(got.get(probe.tag_10y))
                spacing = summary.get("spacing_min")
                summary["served_at_requested_resolution"] = (
                    spacing is not None and spacing <= target * 1.5
                )
                block["curves"][probe.key] = summary
            per_depth[str(years)] = block
            served = [k for k, v in block["curves"].items()
                      if v.get("served_at_requested_resolution")]
            log.info("  %s @ %5.2fy (%s): full-resolution for %s",
                     freq, years, day, ",".join(served) or "NONE")
        out[freq] = per_depth
    return out


def stage_snap(
    client: Any,
    counter: CallCounter,
    probes: Sequence[Probe],
    depths: Sequence[float],
    daily: Optional[Dict[str, Any]] = None,
) -> dict:
    """The decisive test: two ``CVSNAP`` stamps on the same historical day.

    ``CVSNAP`` publishes no timestamp, so it cannot be asked what it served. The
    pair is what answers it:

    * **equal** -> the day's single print. No intraday content. A snap backfill
      here would produce flat curves that look exactly like real ones.
    * **different** -> genuinely intraday, and the design question becomes cost.

    Curves are grouped by session zone, because there is no single New York
    instant inside the USD, European and Tokyo sessions at once. Each group is
    asked at **09:30 and 15:00 in its own market's zone**, converted to the wire
    zone for the request.
    """
    by_zone: Dict[str, List[Probe]] = {}
    for probe in probes:
        by_zone.setdefault(probe.tz, []).append(probe)

    out: Dict[str, Any] = {}
    for years in depths:
        day = _business_day_back(years)
        block: Dict[str, Any] = {"date": str(day), "curves": {}}
        for tz, group in by_zone.items():
            tags = [p.tag_10y for p in group]
            values: Dict[str, Dict[str, Optional[float]]] = {p.key: {} for p in group}
            for label, (hour, minute) in (("am", (9, 30)), ("pm", (15, 0))):
                when = _local_to_wire(day, hour, minute, tz)
                try:
                    got = counter.timed(client.snapshot, tags, when)
                except Exception as exc:  # noqa: BLE001
                    for probe in group:
                        values[probe.key][label] = None
                        values[probe.key][f"{label}_error"] = f"{type(exc).__name__}: {exc}"
                    log.warning("  snap @ %.2fy %s %s: TRANSPORT %s", years, tz, label, exc)
                    continue
                for probe in group:
                    value, _stamp = got.get(probe.tag_10y, (None, None))
                    values[probe.key][label] = None if value is None else float(value)
                    values[probe.key][f"{label}_wire"] = str(when)

            for probe in group:
                record = values[probe.key]
                am, pm = record.get("am"), record.get("pm")
                record["differs"] = (
                    am is not None and pm is not None and abs(am - pm) > 1e-9
                )
                record["diff_bp"] = None if (am is None or pm is None) else round((pm - am) * 100.0, 4)
                # Anchor the level: the same date's DAILY close, if we have it.
                series = (daily or {}).get(probe.key)
                close = None
                if series is not None and len(series):
                    idx = pd.DatetimeIndex(series.index)
                    prior = idx[idx <= pd.Timestamp(day)]
                    if len(prior):
                        close = float(series.loc[prior.max()])
                record["daily_close"] = close
                record["pm_minus_close_bp"] = (
                    None if (pm is None or close is None) else round((pm - close) * 100.0, 4)
                )
                block["curves"][probe.key] = record
        out[str(years)] = block
        for key, record in block["curves"].items():
            log.info(
                "  snap @ %5.2fy (%s) %-14s am=%s pm=%s %s (close %s)",
                years, day, key, record.get("am"), record.get("pm"),
                "INTRADAY" if record.get("differs") else "FLAT/absent",
                record.get("daily_close"),
            )
    return out


def stage_crosscheck(client: Any, counter: CallCounter, probes: Sequence[Probe]) -> dict:
    """In the era where both serve, does ``CVSNAP`` equal the ``MI01`` row?

    This is the mechanism check. It has been run once before, on 2026-08-06, and
    agreed to the digit; re-running it here on the SAME dates the deep probe uses
    means a disagreement at depth can be attributed to depth rather than to a
    standing difference between the two functions.
    """
    day = _business_day_back(0.25)
    out: Dict[str, Any] = {"date": str(day), "curves": {}}
    for probe in probes:
        when_local_hour, when_local_min = 10, 30
        wire = _local_to_wire(day, when_local_hour, when_local_min, probe.tz)
        try:
            snapped = counter.timed(client.snapshot, [probe.tag_10y], wire)
            value, _ = snapped.get(probe.tag_10y, (None, None))
        except Exception as exc:  # noqa: BLE001
            out["curves"][probe.key] = {"transport_error": f"{type(exc).__name__}: {exc}"}
            continue
        try:
            got = counter.timed(
                client.fetch_timeseries,
                [probe.tag_10y],
                freq="MI01",
                start=wire - datetime.timedelta(hours=1),
                end=wire + datetime.timedelta(minutes=1),
            )
        except Exception as exc:  # noqa: BLE001
            out["curves"][probe.key] = {"snap": value, "transport_error": f"{type(exc).__name__}: {exc}"}
            continue
        series = got.get(probe.tag_10y)
        row = None
        if series is not None and len(series):
            idx = pd.DatetimeIndex(series.index)
            exact = idx[idx == pd.Timestamp(wire)]
            if len(exact):
                row = float(series.loc[exact[0]])
            else:
                prior = idx[idx <= pd.Timestamp(wire)]
                row = float(series.loc[prior.max()]) if len(prior) else None
        out["curves"][probe.key] = {
            "wire": str(wire),
            "snap": value,
            "mi01": row,
            "diff_bp": None if (value is None or row is None) else round((value - row) * 100.0, 5),
            "mi01_rows": 0 if series is None else int(len(series)),
        }
        log.info("  crosscheck %-14s snap=%s mi01=%s diff=%s bp",
                 probe.key, value, row, out["curves"][probe.key]["diff_bp"])
    return out


#: A window whose median spacing is at or under this is intraday at all - it
#: carries several prints inside one session rather than one print per day. The
#: distinction matters: below its dense-minute era ``USD_FEDFUND`` still serves
#: ~330 rows over four days at ~8-minute spacing, which is real intraday data and
#: which a "is the median one minute?" test calls empty. That mistake made a
#: DENSITY boundary look like a RETENTION boundary, and made ``CVSNAP`` look as
#: though it reached under it.
SPARSE_CEILING_MIN = 240.0


def _serves_at(
    client: Any,
    counter: CallCounter,
    tag: str,
    day: datetime.date,
    freq: str = "MI01",
    *,
    dense: bool = True,
) -> Tuple[bool, Dict[str, Any]]:
    """Does ``tag`` serve ``freq`` in the window ending ``day``?

    Two different questions, and conflating them is the trap this probe already
    fell into once:

    ``dense=True``
        Is it at the REQUESTED resolution - a median spacing at or under
        1.5x the frequency's target? This is the floor a one-minute cache can
        actually be built from.
    ``dense=False``
        Is there ANY intraday content - several prints per session, at whatever
        spacing the market gave? This is the true retention floor, and it sits
        materially deeper for some curves.
    """
    span = datetime.timedelta(days=SAFE_SPAN_DAYS[freq])
    end = datetime.datetime.combine(day, datetime.time(23, 59))
    try:
        got = counter.timed(
            client.fetch_timeseries, [tag], freq=freq, start=end - span, end=end
        )
    except Exception as exc:  # noqa: BLE001
        return False, {"transport_error": f"{type(exc).__name__}: {exc}"}
    summary = _series_summary(got.get(tag))
    spacing = summary.get("spacing_min")
    if not summary.get("rows") or spacing is None:
        return False, summary
    limit = TARGET_MINUTES[freq] * 1.5 if dense else SPARSE_CEILING_MIN
    return bool(spacing <= limit), summary


def stage_floor(
    client: Any,
    counter: CallCounter,
    probes: Sequence[Probe],
    freq: str = "MI01",
    tolerance_days: int = 21,
    anchor: Optional[datetime.date] = None,
) -> dict:
    """Bracket each curve's intraday retention floor, then ask ``CVSNAP`` below it.

    The coarse walk brackets the floor between two probe depths; this bisects
    inside that bracket to within ``tolerance_days`` and then asks the question
    the whole exercise exists for: **is there anything under the floor that
    ``CVSNAP`` can reach and ``CVTSHIST`` cannot?**

    A transport failure is recorded and treated as "unknown", never as "no data" -
    one dropped COM call read as a retention boundary is exactly how a wrong
    number gets written down as measured.
    """
    out: Dict[str, Any] = {"freq": freq, "tolerance_days": tolerance_days, "curves": {}}
    today = datetime.date.today()

    def _bisect(tag: str, dense: bool, log_label: str) -> Tuple[Optional[datetime.date], List[dict], Optional[datetime.date]]:
        lo = datetime.date(2008, 1, 2)   # believed too old to serve
        hi = anchor or _business_day_back(0.25)  # believed to serve
        trail: List[dict] = []
        ok_hi, summary_hi = _serves_at(client, counter, tag, hi, freq, dense=dense)
        trail.append({"date": str(hi), "serves": ok_hi, **summary_hi})
        if not ok_hi:
            return None, trail, None
        while (hi - lo).days > tolerance_days:
            mid = lo + datetime.timedelta(days=(hi - lo).days // 2)
            mid -= datetime.timedelta(days=(mid.weekday() - 2) % 7)  # nearest Wednesday back
            if mid <= lo or mid >= hi:
                break
            ok, summary = _serves_at(client, counter, tag, mid, freq, dense=dense)
            trail.append({"date": str(mid), "serves": ok, **summary})
            log.info("    %-9s %s -> %s", log_label, mid, "serves" if ok else "empty")
            if ok:
                hi = mid
            else:
                lo = mid
        return hi, trail, lo

    for probe in probes:
        log.info("  floor %s", probe.key)
        record: Dict[str, Any] = {}

        dense_floor, dense_trail, dense_lo = _bisect(probe.tag_10y, True, "dense")
        any_floor, any_trail, any_lo = _bisect(probe.tag_10y, False, "any")

        record["dense_probes"] = dense_trail
        record["any_probes"] = any_trail
        record["floor"] = None if dense_floor is None else str(dense_floor)
        record["floor_bracket"] = None if dense_floor is None else [str(dense_lo), str(dense_floor)]
        record["intraday_floor"] = None if any_floor is None else str(any_floor)
        record["intraday_floor_bracket"] = None if any_floor is None else [str(any_lo), str(any_floor)]
        record["years_of_minute"] = (
            None if dense_floor is None else round((today - dense_floor).days / 365.25, 2)
        )
        record["years_of_intraday"] = (
            None if any_floor is None else round((today - any_floor).days / 365.25, 2)
        )
        log.info(
            "  floor %-14s minute from %s (%s y), any intraday from %s (%s y)",
            probe.key, record["floor"], record["years_of_minute"],
            record["intraday_floor"], record["years_of_intraday"],
        )

        # Does CVSNAP see anything under the TRUE intraday floor? Everything
        # above this line has already established that a "no" from the dense
        # test is not a "no" from the store.
        below: List[Dict[str, Any]] = []
        base = any_floor or dense_floor
        if base is not None:
            for back_days in (30, 120, 365):
                day = base - datetime.timedelta(days=back_days)
                day -= datetime.timedelta(days=(day.weekday() - 2) % 7)
                values = []
                for hour, minute in ((9, 30), (12, 0), (15, 0)):
                    when = _local_to_wire(day, hour, minute, probe.tz)
                    try:
                        got = counter.timed(client.snapshot, [probe.tag_10y], when)
                        value, _ = got.get(probe.tag_10y, (None, None))
                    except Exception as exc:  # noqa: BLE001
                        values.append({"wire": str(when), "error": f"{type(exc).__name__}: {exc}"})
                        continue
                    values.append({"wire": str(when), "value": None if value is None else float(value)})
                served = [v.get("value") for v in values if v.get("value") is not None]
                below.append({
                    "date": str(day),
                    "days_below_floor": back_days,
                    "values": values,
                    "n_served": len(served),
                    "distinct": len(set(served)),
                })
                log.info(
                    "  floor %-14s %s (%d days below the INTRADAY floor): %d/3 snaps, %d distinct",
                    probe.key, day, back_days, len(served), len(set(served)),
                )
        record["snap_below_floor"] = below
        record["snap_reaches_deeper"] = any(
            b["n_served"] > 0 and b["distinct"] > 1 for b in below
        )
        out["curves"][probe.key] = record
    return out


#: The par grid a curve is actually solved from, per probe key. ``EUR_EURIBOR``
#: is not an OIS index and its tags live under a different family.
def _par_grid_for(key: str) -> List[str]:
    from MDP.CitiVelocityExcel.tags import ois_par_grid, swap_libor_par_grid

    if key == "EUR_EURIBOR":
        return list(swap_libor_par_grid("EUR"))
    return list(ois_par_grid(key))


def stage_coverage(
    client: Any,
    counter: CallCounter,
    probes: Sequence[Probe],
    depths: Sequence[float],
) -> dict:
    """How much of the 44-tenor PAR GRID survives at depth, not just the 10Y.

    Every retention number above was measured on one liquid tenor. A curve is
    solved from the whole grid, and a floor measured on the 10Y is worthless if
    the 40Y stops five years earlier - the build would silently fall back to a
    shorter node set and produce a curve that is a different object from the one
    the recent history holds.

    Rows are counted **per tenor**, and the report prints the shape of the
    shortfall rather than a mean, because losing the four longest tenors and
    losing forty scattered minutes are different problems.
    """
    out: Dict[str, Any] = {}
    for probe in probes:
        tags = _par_grid_for(probe.key)
        tenor_of = {t: t.rsplit(".", 1)[-1] for t in tags}
        per_depth: Dict[str, Any] = {}
        for years in depths:
            day = _business_day_back(years)
            end = datetime.datetime.combine(day, datetime.time(23, 59))
            start = end - datetime.timedelta(days=SAFE_SPAN_DAYS["MI01"])
            try:
                got = counter.timed(
                    client.fetch_timeseries, tags, freq="MI01", start=start, end=end
                )
            except Exception as exc:  # noqa: BLE001
                per_depth[str(years)] = {"date": str(day), "transport_error": f"{type(exc).__name__}: {exc}"}
                continue
            rows = {tenor_of[t]: int(len(s.dropna())) for t, s in got.items() if len(s.dropna())}
            best = max(rows.values()) if rows else 0
            # A tenor is "full" when it carries at least 90% of the busiest one.
            full = [t for t, n in rows.items() if best and n >= 0.9 * best]
            per_depth[str(years)] = {
                "date": str(day),
                "n_tags": len(tags),
                "n_served": len(rows),
                "n_full": len(full),
                "max_rows": best,
                "missing": sorted(set(tenor_of.values()) - set(rows), key=_tenor_years),
                "thin": sorted({t: n for t, n in rows.items() if best and n < 0.9 * best},
                               key=_tenor_years),
            }
            log.info(
                "  coverage %-14s @%5.2fy (%s): %2d/%2d tenors, %2d full, max %d rows%s",
                probe.key, years, day, len(rows), len(tags), len(full), best,
                ("  missing " + ",".join(per_depth[str(years)]["missing"][:8])) if per_depth[str(years)]["missing"] else "",
            )
        out[probe.key] = per_depth
    return out


def _tenor_years(tenor: str) -> float:
    try:
        unit = tenor[-1].upper()
        n = float(tenor[:-1])
    except (ValueError, IndexError):
        return 1e9
    return n * {"D": 1 / 365.25, "W": 7 / 365.25, "M": 1 / 12.0, "Y": 1.0}.get(unit, 1e9)


def stage_snapwalk(
    client: Any,
    counter: CallCounter,
    probes: Sequence[Probe],
    floors: Dict[str, Any],
    step_days: int = 21,
    steps: int = 8,
) -> dict:
    """Exactly how far below the ``CVTSHIST`` floor ``CVSNAP`` still answers.

    This is the only measurement that can justify a snap-driven acquisition path
    at all, and it has to separate three outcomes that a row count would merge:

    * **nothing served** - the store ends here for both functions;
    * **served, one distinct value** - a single daily print wearing three
      timestamps. Building minute curves off that manufactures a flat session
      that is indistinguishable from real data downstream;
    * **served, several distinct values** - genuine intraday content that
      ``CVTSHIST`` will not hand over. The only case worth writing a fetcher for.

    The walk starts one full bisection tolerance below the measured floor, so the
    first step is under it even at the worst case of the bracket.
    """
    out: Dict[str, Any] = {"step_days": step_days, "steps": steps, "curves": {}}
    for probe in probes:
        record = (floors.get("curves") or {}).get(probe.key) or {}
        floor_text = record.get("floor")
        if not floor_text:
            out["curves"][probe.key] = {"skipped": "no floor measured"}
            continue
        floor = datetime.date.fromisoformat(str(floor_text)[:10])
        walk: List[Dict[str, Any]] = []
        deepest_intraday: Optional[str] = None
        for step in range(1, steps + 1):
            day = floor - datetime.timedelta(days=step * step_days)
            day -= datetime.timedelta(days=(day.weekday() - 2) % 7)
            served: List[float] = []
            for hour, minute in ((9, 30), (12, 30), (15, 30)):
                when = _local_to_wire(day, hour, minute, probe.tz)
                try:
                    got = counter.timed(client.snapshot, [probe.tag_10y], when)
                    value, _ = got.get(probe.tag_10y, (None, None))
                except Exception:  # noqa: BLE001
                    continue
                if value is not None:
                    served.append(float(value))
            distinct = len(set(round(v, 9) for v in served))
            walk.append({
                "date": str(day), "days_below_floor": step * step_days,
                "n_served": len(served), "distinct": distinct, "values": served,
            })
            if distinct > 1:
                deepest_intraday = str(day)
            log.info("  snapwalk %-14s %s (-%3dd): %d/3 served, %d distinct",
                     probe.key, day, step * step_days, len(served), distinct)
            if len(served) == 0 and step >= 2 and walk[-2]["n_served"] == 0:
                # Two consecutive empty steps: the store has ended, not a hole.
                break
        out["curves"][probe.key] = {
            "floor": str(floor),
            "walk": walk,
            "deepest_intraday_below_floor": deepest_intraday,
            "extra_days": (
                None if deepest_intraday is None
                else (floor - datetime.date.fromisoformat(deepest_intraday)).days
            ),
        }
    return out


def stage_cvtick(client: Any, counter: CallCounter, probes: Sequence[Probe]) -> dict:
    """``CVTICK`` is entitled and has never been called. Does it reach deeper?

    The entitlement list in the design notes reads ``CVTSHIST CVSNAP CVLATEST
    CVMETADATA CVCURVE CVCURVEBOND CVSTREAM CVTICK CVNOW CVTODAY``. Every other
    entitled function has been exercised; this one has not, and it is the only
    remaining candidate for a store ``CVTSHIST`` does not expose.

    Argument shapes are unknown, so several are tried and each result is recorded
    verbatim. An add-in error is an answer; so is an empty block.
    """
    probe = probes[0]
    tag = probe.tag_10y
    recent = _business_day_back(0.25)
    deep = datetime.date(2015, 6, 10)
    out: Dict[str, Any] = {"tag": tag, "attempts": []}

    attempts: List[Tuple[str, str]] = [
        ("bare tag", f'=CVTICK("{tag}")'),
        ("tag + recent day", f'=CVTICK("{tag}","{recent:%Y%m%d}")'),
        ("tag + recent bounds",
         f'=CVTICK("{tag}","{recent:%Y%m%d}0900","{recent:%Y%m%d}0930")'),
        ("tag + deep bounds",
         f'=CVTICK("{tag}","{deep:%Y%m%d}0900","{deep:%Y%m%d}0930")'),
    ]
    for label, formula in attempts:
        try:
            rows, value, elapsed = counter.timed(
                client._write_and_read, formula, rows_needed=40, timeout=45.0
            )
            body = [list(r) for r in rows[:6]]
            record = {
                "label": label, "formula": formula, "seconds": round(elapsed, 2),
                "n_rows": len(rows), "head": body, "first_cell": repr(value)[:200],
            }
        except Exception as exc:  # noqa: BLE001
            record = {"label": label, "formula": formula, "error": f"{type(exc).__name__}: {exc}"}
        out["attempts"].append(record)
        log.info("  cvtick %-22s -> %s", label,
                 record.get("error") or f"{record.get('n_rows')} rows, first={record.get('first_cell')}")
    return out


def stage_mechanics(client: Any, counter: CallCounter, probes: Sequence[Probe]) -> dict:
    """What a snap-driven backfill would actually cost per instant.

    Three things decide the grid density: how many tags fit one ``CVSNAP``, how
    long a call takes, and how much Excel memory a hundred of them costs. The
    third is the one that ends a run.
    """
    from MDP.CitiVelocityExcel.tags import ois_par_grid

    day = _business_day_back(0.25)
    wire = _local_to_wire(day, 10, 30, "America/New_York")
    out: Dict[str, Any] = {"date": str(day), "wire": str(wire), "trials": []}

    grid_44 = ois_par_grid("USD_SOFR")
    trials: List[Tuple[str, List[str]]] = [
        ("1 tag", [PROBES[0].tag_10y]),
        ("44 tags (one par grid)", list(grid_44)),
    ]
    # Two par grids in one formula: does the add-in take a wider chunk?
    grid_88 = list(grid_44) + list(ois_par_grid("USD_FEDFUND"))
    trials.append(("88 tags (two par grids)", grid_88))

    original = getattr(client, "_chunk_size", None)
    for label, tags in trials:
        if original is not None:
            client._chunk_size = max(len(tags), 44)
        started = time.time()
        try:
            got = counter.timed(client.snapshot, tags, wire)
            served = sum(1 for v, _ in got.values() if v is not None)
            error = ""
        except Exception as exc:  # noqa: BLE001
            served, error = 0, f"{type(exc).__name__}: {exc}"
        elapsed = time.time() - started
        record = {
            "label": label,
            "n_tags": len(tags),
            "served": served,
            "seconds": round(elapsed, 2),
            "seconds_per_tag": round(elapsed / max(len(tags), 1), 4),
            "error": error,
            "excel_mb": client.excel_memory_mb(),
        }
        out["trials"].append(record)
        log.info("  mechanics %-24s %3d tags -> %3d served in %5.2fs (Excel %.0f MB) %s",
                 label, len(tags), served, elapsed, record["excel_mb"], error)
    if original is not None:
        client._chunk_size = original
    return out


# --------------------------------------------------------------------------- #
#                                   report                                     #
# --------------------------------------------------------------------------- #


def report(result: dict) -> str:
    lines: List[str] = [f"Citi Velocity snap/history depth probe - {result.get('probed_at')}"]

    check = result.get("selfcheck")
    if check:
        lines.append(
            f"\nSELF-CHECK: {'PASS' if check.get('ok') else 'FAIL'} "
            f"(4d -> {check['narrow'].get('spacing_min')}min, "
            f"30d -> {check['wide'].get('spacing_min')}min)"
        )
        if not check.get("ok"):
            lines.append("  Every retention conclusion below is VOID until this passes.")

    inception = result.get("inception")
    if inception:
        lines.append("\nINSTRUMENT INCEPTION (DAILY, period=MAX)")
        lines.append(f"  {'curve':<16}{'10Y from':<14}{'10Y to':<14}{'rows':>8}")
        for key, block in inception.get("curves", {}).items():
            ten = block.get("10Y", {})
            lines.append(
                f"  {key:<16}{str(ten.get('first'))[:10]:<14}{str(ten.get('last'))[:10]:<14}"
                f"{ten.get('rows', 0):>8}"
            )

    tshist = result.get("tshist")
    if tshist:
        lines.append("\nCVTSHIST RETENTION - median spacing served, in minutes")
        for freq, per_depth in tshist.items():
            lines.append(f"\n  {freq} (span held at {SAFE_SPAN_DAYS[freq]}d, target {TARGET_MINUTES[freq]:.0f}min)")
            keys = sorted(per_depth, key=float)
            header = f"    {'years back':<12}{'date':<13}"
            names = []
            for years in keys:
                names = list((per_depth[years].get("curves") or {}).keys())
                if names:
                    break
            header += "".join(f"{n:>16}" for n in names)
            lines.append(header)
            for years in keys:
                block = per_depth[years]
                if block.get("transport_error"):
                    lines.append(f"    {years:<12}{block.get('date',''):<13}TRANSPORT FAILED")
                    continue
                row = f"    {years:<12}{block.get('date',''):<13}"
                for name in names:
                    summary = (block.get("curves") or {}).get(name, {})
                    spacing = summary.get("spacing_min")
                    rows = summary.get("rows", 0)
                    cell = "-" if not rows else (f"{spacing:.0f}min x{rows}" if spacing else f"x{rows}")
                    row += f"{cell:>16}"
                lines.append(row)

    snap = result.get("snap")
    if snap:
        lines.append("\nCVSNAP AT DEPTH - two stamps on the same day (09:30 vs 15:00 local)")
        lines.append(f"  {'years':<8}{'date':<13}{'curve':<16}{'09:30':>12}{'15:00':>12}{'diff bp':>10}  verdict")
        for years in sorted(snap, key=float):
            block = snap[years]
            for key, record in (block.get("curves") or {}).items():
                am, pm = record.get("am"), record.get("pm")
                diff = record.get("diff_bp")
                verdict = (
                    "INTRADAY" if record.get("differs")
                    else ("absent" if am is None and pm is None else "FLAT - one print per day")
                )
                am_text = "-" if am is None else format(am, ".5f")
                pm_text = "-" if pm is None else format(pm, ".5f")
                diff_text = "-" if diff is None else format(diff, ".2f")
                lines.append(
                    f"  {years:<8}{block.get('date',''):<13}{key:<16}"
                    f"{am_text:>12}{pm_text:>12}{diff_text:>10}  {verdict}"
                )

    cross = result.get("crosscheck")
    if cross:
        lines.append(f"\nCVSNAP vs CVTSHIST MI01 at the same minute ({cross.get('date')})")
        for key, record in (cross.get("curves") or {}).items():
            lines.append(
                f"  {key:<16}snap={record.get('snap')}  mi01={record.get('mi01')}  "
                f"diff={record.get('diff_bp')} bp"
            )

    floor = result.get("floor")
    if floor:
        lines.append(f"\nINTRADAY RETENTION FLOORS ({floor.get('freq')}, bisected to "
                     f"+/-{floor.get('tolerance_days')}d) and what CVSNAP sees BELOW them")
        lines.append(
            f"  {'curve':<16}{'1-min from':<13}{'yrs':>5}   {'any intraday from':<19}{'yrs':>5}"
            f"   snap below the intraday floor"
        )
        for key, record in (floor.get("curves") or {}).items():
            below = record.get("snap_below_floor") or []
            summary = ", ".join(
                f"-{b['days_below_floor']}d: {b['n_served']}/3, {b['distinct']} distinct"
                for b in below
            )
            lines.append(
                f"  {key:<16}{str(record.get('floor')):<13}"
                f"{record.get('years_of_minute') or 0:>5}   "
                f"{str(record.get('intraday_floor')):<19}"
                f"{record.get('years_of_intraday') or 0:>5}   {summary}"
            )
        lines.append(
            "  'snap reaches deeper' is TRUE only where CVSNAP served MORE THAN ONE "
            "DISTINCT value below a floor CVTSHIST refuses: "
            + ", ".join(
                f"{k}={bool(v.get('snap_reaches_deeper'))}"
                for k, v in (floor.get("curves") or {}).items()
            )
        )

    walk = result.get("snapwalk")
    if walk:
        lines.append("\nHOW FAR BELOW THE CVTSHIST FLOOR CVSNAP STILL ANSWERS")
        lines.append(f"  {'curve':<16}{'floor':<13}{'deepest intraday':<20}{'extra':>8}")
        for key, record in (walk.get("curves") or {}).items():
            if record.get("skipped"):
                lines.append(f"  {key:<16}{record['skipped']}")
                continue
            extra = record.get("extra_days")
            lines.append(
                f"  {key:<16}{record.get('floor',''):<13}"
                f"{str(record.get('deepest_intraday_below_floor') or 'none'):<20}"
                f"{('+' + str(extra) + 'd') if extra else '-':>8}"
            )

    coverage = result.get("coverage")
    if coverage:
        lines.append("\nPAR-GRID COVERAGE AT DEPTH (MI01) - tenors served / full / total")
        for key, per_depth in coverage.items():
            lines.append(f"  {key}")
            for years in sorted(per_depth, key=float):
                block = per_depth[years]
                if block.get("transport_error"):
                    lines.append(f"    {years:<7}{block.get('date','')}  TRANSPORT FAILED")
                    continue
                lines.append(
                    f"    {years:<7}{block.get('date',''):<13}"
                    f"{block['n_served']:>3}/{block['n_full']:>3}/{block['n_tags']:<4}"
                    f"max {block['max_rows']:>5} rows"
                    + (f"   missing: {','.join(block['missing'][:10])}" if block["missing"] else "")
                )

    tick = result.get("cvtick")
    if tick:
        lines.append("\nCVTICK - the one entitled function never called")
        for attempt in tick.get("attempts", []):
            lines.append(
                f"  {attempt['label']:<22}"
                + (attempt.get("error") or
                   f"{attempt.get('n_rows')} rows, first cell {attempt.get('first_cell')}")
            )

    mech = result.get("mechanics")
    if mech:
        lines.append("\nCVSNAP COST")
        for trial in mech.get("trials", []):
            lines.append(
                f"  {trial['label']:<26}{trial['n_tags']:>4} tags  {trial['served']:>4} served  "
                f"{trial['seconds']:>6.2f}s  Excel {trial['excel_mb']:.0f} MB  {trial.get('error','')}"
            )

    calls = result.get("calls")
    if calls:
        lines.append(
            f"\n{calls['calls']} CV* calls, {calls['seconds']}s total, "
            f"{calls['seconds_per_call']}s per call. "
            f"Excel {result.get('mem_before')} -> {result.get('mem_after')} MB."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#                                    main                                      #
# --------------------------------------------------------------------------- #


def run(
    stages: Sequence[str],
    *,
    depths: Sequence[float],
    freqs: Sequence[str],
    probes: Sequence[Probe],
    ceiling_mb: float,
    known_floors: Optional[dict] = None,
    anchor: Optional[datetime.date] = None,
) -> dict:
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect, excel_memory_mb

    mem_before = assert_safe_to_connect(ceiling_mb, what="the Citi Velocity snap depth probe")
    log.info("Excel at %.0f MB before connecting (ceiling %.0f)", mem_before, ceiling_mb)

    counter = CallCounter()
    result: Dict[str, Any] = {
        "probed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "stages": list(stages),
        "depths": list(depths),
        "freqs": list(freqs),
        "probes": [p.key for p in probes],
        "mem_before": mem_before,
    }
    with CitiVelocityExcelClient.connect() as client:
        if "selfcheck" in stages:
            log.info("stage: selfcheck")
            result["selfcheck"] = stage_selfcheck(client, counter, probes)
            if not result["selfcheck"].get("ok"):
                log.error(
                    "SELF-CHECK FAILED - the spacing measurement does not reproduce the "
                    "known ladder. Stopping rather than recording void conclusions."
                )
                result["mem_after"] = excel_memory_mb()
                result["calls"] = counter.as_dict()
                return result

        daily = None
        if "inception" in stages:
            log.info("stage: inception")
            block = stage_inception(client, counter, probes)
            daily = block.pop("_daily", None)
            result["inception"] = block

        if "crosscheck" in stages:
            log.info("stage: crosscheck")
            result["crosscheck"] = stage_crosscheck(client, counter, probes)

        if "tshist" in stages:
            log.info("stage: tshist retention")
            result["tshist"] = stage_tshist(client, counter, probes, depths, freqs)

        if "snap" in stages:
            log.info("stage: snap at depth")
            result["snap"] = stage_snap(client, counter, probes, depths, daily)

        if "coverage" in stages:
            log.info("stage: par-grid coverage at depth")
            result["coverage"] = stage_coverage(client, counter, probes, depths)

        if "cvtick" in stages:
            log.info("stage: CVTICK")
            result["cvtick"] = stage_cvtick(client, counter, probes)

        if "floor" in stages:
            log.info("stage: intraday retention floor")
            result["floor"] = stage_floor(client, counter, probes, anchor=anchor)

        if "snapwalk" in stages:
            floors = result.get("floor") or known_floors or {}
            if not (floors.get("curves") if isinstance(floors, dict) else None):
                log.error("snapwalk needs floors: run --stage floor, or pass --floors-json")
            else:
                log.info("stage: how far below the floor CVSNAP answers")
                result["snapwalk"] = stage_snapwalk(client, counter, probes, floors)

        if "mechanics" in stages:
            log.info("stage: mechanics")
            result["mechanics"] = stage_mechanics(client, counter, probes)

        result["mem_after"] = client.excel_memory_mb()
    result["calls"] = counter.as_dict()
    return result


ALL_STAGES = (
    "selfcheck", "inception", "crosscheck", "tshist", "snap",
    "floor", "snapwalk", "coverage", "cvtick", "mechanics",
)


def _opt_anchor(text: Optional[str]) -> Optional[datetime.date]:
    """The date a floor bisection starts from, when 'recently' is not good enough.

    A RETIRED curve breaks the default anchor outright: ``EUR_EONIA`` stopped
    publishing on 2025-08-15, so a probe three months back finds nothing, the
    bisection concludes "serves nothing at all", and a real seven-year intraday
    history reads as absent.
    """
    return datetime.date.fromisoformat(text) if text else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--stage", nargs="*", default=["all"],
                   help=f"one or more of {', '.join(ALL_STAGES)}, or 'all'")
    p.add_argument("--depths", nargs="*", type=float, default=list(DEFAULT_DEPTHS),
                   help="years back to probe")
    p.add_argument("--freqs", nargs="*", default=["MI01", "MI10", "HOURLY"])
    p.add_argument("--curves", default="", help="comma-separated Probe keys; default all")
    p.add_argument("--ceiling-mb", type=float, default=WORKING_CEILING_MB)
    p.add_argument("--floors-json", type=pathlib.Path, default=None,
                   help="a previous run's JSON, to reuse its measured floors for --stage snapwalk")
    p.add_argument("--anchor", default=None,
                   help="ISO date the floor bisection starts from. Needed for a "
                        "RETIRED curve: EUR_EONIA stopped publishing 2025-08-15, so "
                        "the default 'three months ago' anchor finds nothing and the "
                        "bisection reports no floor at all.")
    p.add_argument("--out", type=pathlib.Path, default=None)
    args = p.parse_args(argv)

    stages = list(ALL_STAGES) if "all" in args.stage else list(args.stage)
    unknown = [s for s in stages if s not in ALL_STAGES]
    if unknown:
        p.error(f"unknown stage(s): {', '.join(unknown)}")

    probes = list(PROBES)
    if args.curves.strip():
        wanted = {c.strip().upper() for c in args.curves.split(",") if c.strip()}
        probes = [p_ for p_ in PROBES if p_.key.upper() in wanted]
        if not probes:
            p.error(f"no probe matches {args.curves!r}; known: {', '.join(x.key for x in PROBES)}")

    known_floors = None
    if args.floors_json:
        known_floors = (json.loads(args.floors_json.read_text(encoding="utf-8")) or {}).get("floor")

    result = run(
        stages,
        depths=args.depths,
        freqs=args.freqs,
        probes=probes,
        ceiling_mb=args.ceiling_mb,
        known_floors=known_floors,
        anchor=_opt_anchor(args.anchor),
    )
    print(report(result))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
