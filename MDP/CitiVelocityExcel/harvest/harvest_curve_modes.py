r"""Bounded live harvest of everything the three curve modes need from the add-in.

Run from the repo root, one stage group at a time::

    <env>/python.exe MDP/CitiVelocityExcel/harvest/harvest_curve_modes.py --stages A
    <env>/python.exe MDP/CitiVelocityExcel/harvest/harvest_curve_modes.py --stages D,B
    ...

Why this exists and why it is shaped like this
----------------------------------------------
Everything live goes through a human-logged-in Excel. It can be closed or log out
at any moment and a restart costs ~13 minutes of silent add-in login, so the
design rule is: **harvest first, persist immediately, then do all analysis
offline against what was banked.** Every stage writes its series into the
:class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache` and its evidence into a
JSONL log the moment the call returns, so an Excel that dies mid-run costs only
the stage in flight.

The stages are ordered by information-per-call, not by narrative order, for the
same reason:

===== ==== =================================================================
stage call  what it settles
===== ==== =================================================================
``A``   ~11 the wire itself: what zone the timestamps are in, whether the
            intraday ``yyyyMMddHHmm`` bound form is honoured, what ``CVLATEST``
            and ``CVSNAP`` actually return, and what a *dead* series looks like
            through the live primitive (``EUR_EONIA``)
``D``    3  Citi's own published forwards for all 20 curves. THREE calls, and
            they are what makes the +/-1bp tie-out an independent check rather
            than a repricing of the curve's own inputs. Deliberately early.
``B``   20  the EOD par grid per currency, with history
``C``   21  intraday: one activity-window fingerprint call across all 20, then
            a one-minute full grid per currency over a bounded window
``E``    3  how far back one-minute history actually reaches, all 20 at once
``F``   20  the live primitive across all 20 full par grids
``S``    1  ``CVSTREAM`` - LAST, alone, from its own client, because it is the
            one call the hermetic fake cannot model and the one most likely to
            be RTD-shaped (i.e. still writing when we tear the workbook down,
            which is a known Excel-killer)
===== ==== =================================================================

Discipline
----------
* Every Excel access goes through :class:`CitiVelocityExcelClient`. No second
  write path exists here - the spacing and teardown rules that keep the user's
  process alive live in that client, and duplicating them is how they drift.
* An :class:`AsyncTimeoutError` **aborts the process without closing the
  workbook**. A formula that has not settled may still resolve later into a tall
  block, so both writing near it and tearing it down are crash triggers. Leaving
  it alone is the only safe response; the next invocation gets a fresh workbook.
* Nothing here retries a failed connect in a loop. If Excel is gone, the run
  records that and stops.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:  # probe script only; never in library code
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from MDP.CitiVelocityExcel import tags as T  # noqa: E402
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient  # noqa: E402
from MDP.CitiVelocityExcel.errors import AsyncTimeoutError  # noqa: E402

#: The 20 curves, in the order the report should read.
INDICES: Tuple[str, ...] = T.OIS_INDICES

#: Known-good controls. Nothing in a stage is trusted if these do not serve.
CONTROLS = (
    "RATES.OIS.USD_SOFR.PAR.10Y",
    "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y",
)

#: The forward points fetched for every curve. Chosen to span the grid: a short
#: expiry into a short and a long tenor, a mid expiry into two, and one long
#: forward - so an interpolation error at either end of the curve shows up.
FWD_POINTS: Tuple[Tuple[str, str], ...] = (
    ("1Y", "1Y"),
    ("1Y", "10Y"),
    ("2Y", "5Y"),
    ("5Y", "5Y"),
    ("5Y", "10Y"),
    ("10Y", "10Y"),
)

OUT_DIR = _REPO_ROOT / "MDP" / "CitiVelocityExcel" / "harvest" / "live_curve_modes"


# ------------------------------------------------------------------ #
#                          evidence plumbing                         #
# ------------------------------------------------------------------ #


def _jsonable(obj: Any) -> Any:
    """Coerce anything the add-in or pandas hands back into JSON."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (datetime.datetime, datetime.date, pd.Timestamp)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, pd.Series):
        return {"n": int(obj.size), "first": _jsonable(obj.index.min()), "last": _jsonable(obj.index.max())}
    return repr(obj)


def _display(path: pathlib.Path) -> str:
    """Repo-relative when it is inside the repo, absolute otherwise (tmp dirs)."""
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


class Evidence:
    """Append-only JSONL log plus a per-stage JSON summary.

    Written on every call rather than at the end, because the failure mode this
    whole script is shaped around is the process losing Excel partway through.
    """

    def __init__(self, out_dir: pathlib.Path, stage: str):
        self.dir = out_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stage = stage
        self.path = self.dir / "evidence.jsonl"
        self.records: List[Dict[str, Any]] = []

    def log(self, event: str, **fields: Any) -> Dict[str, Any]:
        record = {
            "stage": self.stage,
            "event": event,
            "wall_local": datetime.datetime.now().isoformat(timespec="seconds"),
            "wall_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            **{k: _jsonable(v) for k, v in fields.items()},
        }
        self.records.append(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return record

    def summary(self, name: str, payload: Any) -> None:
        path = self.dir / f"{name}.json"
        path.write_text(json.dumps(_jsonable(payload), indent=1), encoding="utf-8")
        print(f"    -> {_display(path)}")


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ------------------------------------------------------------------ #
#                          fetch + persist                           #
# ------------------------------------------------------------------ #


def fetch_and_bank(
    client: CitiVelocityExcelClient,
    cache: CitiVeloTagCache,
    ev: Evidence,
    tags: Sequence[str],
    freq: str,
    *,
    label: str,
    price_point: str = "CLOSE",
    **kw: Any,
) -> Dict[str, pd.Series]:
    """One ``CVTSHIST`` request, written straight into the cache before returning.

    The banking is the point: the analysis phases run offline against the cache,
    so a series that is fetched but not persisted is a series that has to be
    fetched again from an Excel that may no longer be there.
    """
    before = client.calls
    started = time.time()
    series = client.fetch_timeseries(list(tags), freq, price_point=price_point, **kw)
    elapsed = time.time() - started
    failures = client.last_failures()

    for tag, s in series.items():
        if s is not None and len(s):
            cache.write(tag, freq, s, price_point=price_point)

    ev.log(
        "cvtshist",
        label=label,
        freq=freq,
        price_point=price_point,
        kwargs={k: _jsonable(v) for k, v in kw.items()},
        n_tags=len(tags),
        n_served=len(series),
        n_failed=len(failures),
        calls=client.calls - before,
        elapsed_s=round(elapsed, 2),
        first_stamp=(min(s.index.min() for s in series.values()) if series else None),
        last_stamp=(max(s.index.max() for s in series.values()) if series else None),
        failures=dict(list(failures.items())[:8]),
        sample={t: float(s.iloc[-1]) for t, s in list(series.items())[:4]},
    )
    print(
        f"    {label:<34} {len(series):>3}/{len(tags):<3} served, "
        f"{client.calls - before} call(s), {elapsed:5.1f}s"
        + (f", {len(failures)} failed" if failures else "")
    )
    return series


# ------------------------------------------------------------------ #
#                               stages                               #
# ------------------------------------------------------------------ #


def stage_controls(client: CitiVelocityExcelClient, cache: CitiVeloTagCache, ev: Evidence) -> bool:
    """Refuse to trust anything below if the known-good tags do not serve."""
    _rule("controls")
    verdicts = client.validate(list(CONTROLS), period="1M")
    for tag, verdict in verdicts.items():
        print(f"  {verdict:<10} {tag}")
    ok = all(v == "valid" for v in verdicts.values())
    ev.log("controls", verdicts=verdicts, ok=ok)
    if not ok:
        print("  CONTROLS FAILED - nothing below this line would be trustworthy.")
    return ok


def stage_a(client: CitiVelocityExcelClient, cache: CitiVeloTagCache, ev: Evidence) -> None:
    """The wire: timezone, bound formats, and what the point-read functions return."""
    out: Dict[str, Any] = {}

    # -- A1. CVNOW / CVTODAY against three clocks -----------------------
    _rule("A1. CVNOW / CVTODAY vs the wall clock")
    for fn in ("CVNOW()", "CVTODAY()"):
        local = datetime.datetime.now()
        utc = datetime.datetime.now(datetime.timezone.utc)
        try:
            value, rows = client.evaluate_formula(f"={fn}", rows_needed=4)
        except Exception as exc:  # noqa: BLE001 - an unentitled function is data
            print(f"  {fn:<12} RAISED {type(exc).__name__}: {exc}")
            ev.log("scalar_fn", fn=fn, error=f"{type(exc).__name__}: {exc}")
            continue
        from MDP.CitiVelocityExcel.block_parser import coerce_excel_datetime

        parsed = coerce_excel_datetime(value)
        if parsed is None and rows:
            for row in rows:
                for cell in row:
                    parsed = parsed or coerce_excel_datetime(cell)
        print(f"  {fn:<12} raw={value!r}  parsed={parsed}")
        print(f"               local(ET)={local:%Y-%m-%d %H:%M:%S}  utc={utc:%Y-%m-%d %H:%M:%S}")
        if parsed is not None:
            print(f"               parsed - local = {(parsed - local).total_seconds() / 3600:+.2f} h")
            print(f"               parsed - utc   = {(parsed - utc.replace(tzinfo=None)).total_seconds() / 3600:+.2f} h")
        out[fn] = {
            "raw": _jsonable(value),
            "raw_type": type(value).__name__,
            "parsed": _jsonable(parsed),
            "local": local.isoformat(),
            "utc": utc.isoformat(),
            "rows": _jsonable(rows[:4]),
        }
        ev.log("scalar_fn", fn=fn, **out[fn])

    # -- A2. CVLATEST, including a KNOWN DEAD series --------------------
    _rule("A2. CVLATEST - value, stamp, and what a dead curve looks like")
    latest_tags = [
        "RATES.OIS.USD_SOFR.PAR.10Y",
        "RATES.OIS.EUR_EUROSTR.PAR.10Y",
        "RATES.OIS.GBP_SONIA.PAR.10Y",
        "RATES.OIS.JPY_TONAR.PAR.10Y",
        "RATES.OIS.AUD_AONIA.PAR.10Y",
        # EONIA is discontinued. If CVLATEST hands back a year-old print with no
        # signal that it is stale, "live" is a lie for that curve - and that is
        # exactly the silent-staleness failure the review has to hunt for.
        "RATES.OIS.EUR_EONIA.PAR.10Y",
    ]
    local = datetime.datetime.now()
    try:
        latest = client.latest(latest_tags)
        print(f"  wall clock at call: {local:%Y-%m-%d %H:%M:%S} ET")
        for tag in latest_tags:
            value, stamp = latest.get(tag, (None, None))
            lag = None if stamp is None else (local - stamp).total_seconds() / 60.0
            print(
                f"  {tag.split('.')[2]:<16} {('%.6f' % value) if value is not None else 'None':>12}"
                f"  stamp={stamp}  lag={'n/a' if lag is None else f'{lag:8.1f} min'}"
            )
        out["cvlatest"] = {
            "wall_local": local.isoformat(),
            "result": {t: (_jsonable(v[0]), _jsonable(v[1])) for t, v in latest.items()},
        }
        ev.log("cvlatest", **out["cvlatest"])
    except Exception as exc:  # noqa: BLE001
        print(f"  CVLATEST RAISED {type(exc).__name__}: {exc}")
        ev.log("cvlatest", error=f"{type(exc).__name__}: {exc}")

    # -- A3. the one-minute series, and the per-currency activity window -
    _rule("A3. MI01 over the last 2 days - stamp cadence and session window")
    fingerprint_tags = [
        "RATES.OIS.USD_SOFR.PAR.10Y",
        "RATES.OIS.GBP_SONIA.PAR.10Y",
        "RATES.OIS.JPY_TONAR.PAR.10Y",
        "RATES.OIS.AUD_AONIA.PAR.10Y",
    ]
    mi01 = fetch_and_bank(
        client, cache, ev, fingerprint_tags, "MI01", label="A3 MI01 2D fingerprint", period="2D"
    )
    session: Dict[str, Any] = {}
    for tag, s in mi01.items():
        by_day = s.groupby(s.index.date)
        rows = {
            str(day): {
                "n": int(len(g)),
                "first": g.index.min().strftime("%H:%M"),
                "last": g.index.max().strftime("%H:%M"),
            }
            for day, g in by_day
        }
        session[tag] = rows
        idx = str(tag).split(".")[2]
        print(f"  {idx:<16} {len(s):>5} rows")
        for day, r in list(rows.items())[-3:]:
            print(f"      {day}  {r['n']:>4} rows  {r['first']} .. {r['last']}")
    out["mi01_session_windows"] = session

    # -- A4. does CVTSHIST honour an INTRADAY window? -------------------
    _rule("A4. explicit yyyyMMddHHmm bounds on a 1-hour window (inferred, never measured)")
    probe_day = _last_weekday(datetime.date.today() - datetime.timedelta(days=1))
    w_start = datetime.datetime.combine(probe_day, datetime.time(10, 0))
    w_end = datetime.datetime.combine(probe_day, datetime.time(11, 0))
    windowed = fetch_and_bank(
        client,
        cache,
        ev,
        ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.OIS.USD_SOFR.PAR.2Y"],
        "MI01",
        label="A4 MI01 1h window",
        start=w_start,
        end=w_end,
    )
    honoured: Optional[bool] = None
    for tag, s in windowed.items():
        inside = s[(s.index >= pd.Timestamp(w_start)) & (s.index <= pd.Timestamp(w_end))]
        honoured = len(s) > 0 and len(inside) == len(s)
        print(
            f"  {tag}: {len(s)} rows, {s.index.min()} .. {s.index.max()}; "
            f"{len(inside)} inside [{w_start:%H:%M}, {w_end:%H:%M}]"
        )
    print(
        "  -> intraday bounds "
        + (
            "HONOURED"
            if honoured
            else ("IGNORED - CVTSHIST does not take yyyyMMddHHmm" if honoured is False else "UNKNOWN (no rows)")
        )
    )
    out["intraday_bounds"] = {
        "start": w_start.isoformat(),
        "end": w_end.isoformat(),
        "honoured": honoured,
        "rows": {t: int(len(s)) for t, s in windowed.items()},
        "spans": {t: [_jsonable(s.index.min()), _jsonable(s.index.max())] for t, s in windowed.items()},
    }
    ev.log("intraday_bounds", **out["intraday_bounds"])

    # -- A5. the DST boundary: named zone or fixed offset? --------------
    _rule("A5. the 2026-03-08 US spring-forward - named zone vs fixed offset")
    dst = fetch_and_bank(
        client,
        cache,
        ev,
        ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.OIS.EUR_EUROSTR.PAR.10Y"],
        "HOURLY",
        label="A5 HOURLY across US DST",
        start=datetime.datetime(2026, 3, 5, 0, 0),
        end=datetime.datetime(2026, 3, 12, 0, 0),
    )
    dst_report: Dict[str, Any] = {}
    for tag, s in dst.items():
        hours = sorted({t.hour for t in s.index})
        per_day = {
            str(day): sorted({t.hour for t in g.index})
            for day, g in s.groupby(s.index.date)
        }
        dst_report[tag] = {"hours_seen": hours, "per_day": per_day, "n": int(len(s))}
        print(f"  {tag}: {len(s)} rows, distinct hours {hours}")
        for day, hh in per_day.items():
            print(f"      {day}  {len(hh):>2} hours: {hh[0]:02d}..{hh[-1]:02d}")
    out["dst_probe"] = dst_report

    # -- A6. CVSNAP: as-of or nearest, and which zone is the request in? -
    _rule("A6. CVSNAP - as-of vs nearest, and whether the REQUEST is in the same zone")
    snap_tags = [
        "RATES.OIS.USD_SOFR.PAR.10Y",
        "RATES.OIS.USD_SOFR.PAR.2Y",
        "RATES.OIS.GBP_SONIA.PAR.10Y",
    ]
    snap_out: Dict[str, Any] = {}
    for label, when in (
        ("mid-session", datetime.datetime.combine(probe_day, datetime.time(10, 30))),
        ("+1 hour", datetime.datetime.combine(probe_day, datetime.time(11, 30))),
        ("overnight gap", datetime.datetime.combine(probe_day, datetime.time(3, 17))),
    ):
        try:
            snap = client.snapshot(snap_tags, when)
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:<14} RAISED {type(exc).__name__}: {exc}")
            ev.log("cvsnap", label=label, when=when, error=f"{type(exc).__name__}: {exc}")
            continue
        print(f"  {label:<14} when={when:%Y-%m-%d %H:%M}")
        for tag in snap_tags:
            value, stamp = snap.get(tag, (None, None))
            print(f"      {tag.rsplit('.', 2)[-2]:>4}.{tag.rsplit('.', 1)[-1]:<4} "
                  f"{('%.6f' % value) if value is not None else 'None':>12}   stamp={stamp}")
        snap_out[label] = {
            "when": when.isoformat(),
            "result": {t: (_jsonable(v[0]), _jsonable(v[1])) for t, v in snap.items()},
        }
        ev.log("cvsnap", label=label, **snap_out[label])
    out["cvsnap"] = snap_out

    # Cross-check CVSNAP against the one-minute series we just banked.
    ref = windowed.get("RATES.OIS.USD_SOFR.PAR.10Y")
    if ref is not None and "mid-session" in snap_out:
        target = pd.Timestamp(datetime.datetime.combine(probe_day, datetime.time(10, 30)))
        le = ref[ref.index <= target]
        ge = ref[ref.index >= target]
        snap_value = snap_out["mid-session"]["result"].get("RATES.OIS.USD_SOFR.PAR.10Y", (None, None))[0]
        print(f"\n  cross-check at {target}:")
        print(f"      CVSNAP                 {snap_value}")
        print(f"      MI01 last at or before {None if le.empty else (le.index[-1], float(le.iloc[-1]))}")
        print(f"      MI01 first at or after {None if ge.empty else (ge.index[0], float(ge.iloc[0]))}")
        out["cvsnap_crosscheck"] = {
            "target": target.isoformat(),
            "cvsnap": snap_value,
            "mi01_asof": None if le.empty else [le.index[-1].isoformat(), float(le.iloc[-1])],
            "mi01_next": None if ge.empty else [ge.index[0].isoformat(), float(ge.iloc[0])],
        }

    ev.summary("stage_a_wire", out)


def stage_d(client: CitiVelocityExcelClient, cache: CitiVeloTagCache, ev: Evidence) -> None:
    """Citi's own published forwards for all 20 curves - the independent tie-out."""
    _rule("D. RATES.OIS.<idx>.FWD.<expiry>.<tenor> for all 20 curves")
    tags: List[str] = []
    for idx in INDICES:
        for expiry, tenor in FWD_POINTS:
            tags.append(f"RATES.OIS.{idx}.FWD.{expiry}.{tenor}")
    print(f"  {len(tags)} forward tags across {len(INDICES)} curves")
    series = fetch_and_bank(client, cache, ev, tags, "DAILY", label="D FWD grid", period="3M")

    per_index: Dict[str, Any] = {}
    for idx in INDICES:
        served = {
            f"{e}x{t}": float(series[f"RATES.OIS.{idx}.FWD.{e}.{t}"].iloc[-1])
            for e, t in FWD_POINTS
            if f"RATES.OIS.{idx}.FWD.{e}.{t}" in series
        }
        last = {
            f"{e}x{t}": series[f"RATES.OIS.{idx}.FWD.{e}.{t}"].index.max().isoformat()
            for e, t in FWD_POINTS
            if f"RATES.OIS.{idx}.FWD.{e}.{t}" in series
        }
        per_index[idx] = {"n_served": len(served), "latest": served, "last_stamp": last}
        print(f"  {idx:<16} {len(served)}/{len(FWD_POINTS)}  " + ", ".join(f"{k}={v:.4f}" for k, v in served.items()))
    ev.summary("stage_d_forwards", per_index)


def stage_b(
    client: CitiVelocityExcelClient,
    cache: CitiVeloTagCache,
    ev: Evidence,
    *,
    period: str = "1Y",
    only: Optional[Sequence[str]] = None,
) -> None:
    """The EOD par grid for every curve, with history."""
    _rule(f"B. EOD par grids, DAILY period={period}")
    report: Dict[str, Any] = {}
    order = list(only) if only else _usd_first(INDICES)
    for idx in order:
        grid_tags = [f"RATES.OIS.{idx}.PAR.{t}" for t in _par_axis(idx)]
        series = fetch_and_bank(client, cache, ev, grid_tags, "DAILY", label=f"B EOD {idx}", period=period)
        frame = pd.concat(series, axis=1).sort_index() if series else pd.DataFrame()
        report[idx] = _grid_report(idx, grid_tags, series, frame)
        _print_grid_report(idx, report[idx])
        ev.summary("stage_b_eod", report)  # rewritten after every currency
    ev.summary("stage_b_eod", report)


def stage_c(
    client: CitiVelocityExcelClient,
    cache: CitiVeloTagCache,
    ev: Evidence,
    *,
    only: Optional[Sequence[str]] = None,
) -> None:
    """Intraday: one session-window fingerprint call, then a per-curve MI01 grid.

    The per-curve window is derived from that fingerprint rather than fixed,
    because the twenty curves do not trade at the same time of day. Measured on
    2026-08-06/07 (stamps are America/New_York): JPY_TONAR ticks 19:00 ET through
    06:59 ET, AUD_AONIA 18:00 through 05:59 ET, GBP_SONIA 03:00 through 14:59 ET.
    A fixed NY-morning window would have returned zero rows for JPY and AUD and
    that would have read as "no intraday capability" when it is simply the middle
    of the Tokyo night.
    """
    report: Dict[str, Any] = {}

    # -- C1. all 20 activity windows in ONE call ------------------------
    _rule("C1. HOURLY 5D across all 20 curves - the session-window fingerprint")
    fp_tags = [f"RATES.OIS.{idx}.PAR.10Y" for idx in INDICES]
    hourly = fetch_and_bank(client, cache, ev, fp_tags, "HOURLY", label="C1 HOURLY 5D x20", period="5D")
    windows: Dict[str, Any] = {}
    last_tick: Dict[str, pd.Timestamp] = {}
    print(f"\n  {'index':<16}{'rows':>6}  {'session (ET hour of day)':<40}")
    for idx in INDICES:
        tag = f"RATES.OIS.{idx}.PAR.10Y"
        s = hourly.get(tag)
        if s is None or s.empty:
            windows[idx] = None
            print(f"  {idx:<16}{'-':>6}  (no intraday data)")
            continue
        hours = sorted({t.hour for t in s.index})
        last_tick[idx] = s.index.max()
        windows[idx] = {
            "n": int(len(s)),
            "hours": hours,
            "first": s.index.min().isoformat(),
            "last": s.index.max().isoformat(),
        }
        print(f"  {idx:<16}{len(s):>6}  {hours[0]:02d}:00 .. {hours[-1]:02d}:00   {hours}")
    report["session_windows"] = windows
    ev.summary("stage_c_intraday", report)

    # -- C2. a one-minute FULL grid per curve, in ITS OWN session -------
    _rule("C2. MI01 full par grid, in each curve's own two most recent trading hours")
    grids: Dict[str, Any] = {}
    for idx in list(only) if only else _usd_first(INDICES):
        anchor = last_tick.get(idx)
        if anchor is None:
            grids[idx] = {"skipped": "no HOURLY data, so no session window to aim at"}
            print(f"    {idx:<16} skipped - C1 found no intraday rows")
            continue
        w_end = anchor.to_pydatetime()
        w_start = w_end - datetime.timedelta(hours=2)
        grid_tags = [f"RATES.OIS.{idx}.PAR.{t}" for t in _par_axis(idx)]
        series = fetch_and_bank(
            client, cache, ev, grid_tags, "MI01",
            label=f"C2 MI01 {idx}", start=w_start, end=w_end,
        )
        frame = pd.concat(series, axis=1).sort_index() if series else pd.DataFrame()
        grids[idx] = _grid_report(idx, grid_tags, series, frame)
        grids[idx]["window"] = [w_start.isoformat(), w_end.isoformat()]
        _print_grid_report(idx, grids[idx])
        report["mi01_grids"] = grids
        ev.summary("stage_c_intraday", report)
    report["mi01_grids"] = grids
    ev.summary("stage_c_intraday", report)


#: Two one-hour probe windows per date, in America/New_York. One window is not
#: enough: measured 2026-08-06/07, JPY_TONAR ticks 19:00-06:59 ET and AUD_AONIA
#: 18:00-05:59 ET, so a NY-morning-only probe reports "no intraday history" for
#: every Asian curve when it is simply the middle of their night. The 02:00 ET
#: window sits inside the session of all six Asia/Pacific curves at once
#: (JPY x3, AUD, NZD, SGD, THB) and the 10:00 ET one inside every other.
_DEPTH_WINDOWS: Tuple[Tuple[str, datetime.time], ...] = (
    ("NY 10:00", datetime.time(10, 0)),
    ("Asia 02:00", datetime.time(2, 0)),
)


def stage_e(client: CitiVelocityExcelClient, cache: CitiVeloTagCache, ev: Evidence) -> None:
    """How far back one-minute history actually reaches - all 20 curves per call."""
    _rule("E. MI01 depth probes - 20 curves per call, two session windows per date")
    today = datetime.date.today()
    probes = [
        ("~1 month", _last_weekday(today - datetime.timedelta(days=30))),
        ("~6 months", _last_weekday(today - datetime.timedelta(days=182))),
        ("~1 year", _last_weekday(today - datetime.timedelta(days=365))),
        ("~3 years", _last_weekday(today - datetime.timedelta(days=1095))),
        ("~5 years", _last_weekday(today - datetime.timedelta(days=1826))),
    ]
    tags = [f"RATES.OIS.{idx}.PAR.10Y" for idx in INDICES]
    depth: Dict[str, Any] = {}
    for label, day in probes:
        merged: Dict[str, int] = {}
        for wlabel, wtime in _DEPTH_WINDOWS:
            start = datetime.datetime.combine(day, wtime)
            end = start + datetime.timedelta(hours=1)
            series = fetch_and_bank(
                client, cache, ev, tags, "MI01",
                label=f"E depth {label} {day} {wlabel}", start=start, end=end,
            )
            for idx in INDICES:
                tag = f"RATES.OIS.{idx}.PAR.10Y"
                if tag in series:
                    merged[idx] = max(merged.get(idx, 0), int(len(series[tag])))
        depth[label] = {"date": day.isoformat(), "served": merged}
        print(f"  {label:<11} {day}  {len(merged)}/{len(INDICES)} curves have one-minute history")
        missing = [i for i in INDICES if i not in merged]
        if missing:
            print(f"      none: {missing}")
        ev.summary("stage_e_depth", depth)
    ev.summary("stage_e_depth", depth)


def stage_l(client: CitiVelocityExcelClient, cache: CitiVeloTagCache, ev: Evidence) -> None:
    """Capture the RAW ``CVLATEST`` block, so "it returns nothing" has a reason.

    The typed :meth:`CitiVelocityExcelClient.latest` wrapper reported
    ``(None, None)`` for all six OIS ``PAR.10Y`` tags on 2026-08-07 10:47 ET. That
    is enough to disqualify it as the live primitive, but not enough to say
    whether the function is unentitled, mis-shaped, or genuinely empty for this
    family - and the difference matters if anyone reaches for it again.
    """
    _rule("L. the RAW CVLATEST block")
    for formula in (
        '=CVLATEST("RATES.OIS.USD_SOFR.PAR.10Y")',
        '=CVLATEST("RATES.OIS.USD_SOFR.PAR.10Y,RATES.OIS.GBP_SONIA.PAR.10Y")',
    ):
        try:
            value, rows = client.evaluate_formula(formula, rows_needed=8, timeout=120.0)
        except Exception as exc:  # noqa: BLE001
            print(f"  {formula}\n    RAISED {type(exc).__name__}: {exc}")
            ev.log("cvlatest_raw", formula=formula, error=f"{type(exc).__name__}: {exc}")
            continue
        print(f"  {formula}")
        print(f"    settled value: {value!r} ({type(value).__name__})")
        print(f"    block        : {len(rows)} row(s)")
        for row in rows[:8]:
            print(f"      {row}")
        ev.log(
            "cvlatest_raw", formula=formula, value=_jsonable(value),
            value_type=type(value).__name__, n_rows=len(rows), rows=_jsonable(rows[:8]),
        )


def stage_f(
    client: CitiVelocityExcelClient,
    cache: CitiVeloTagCache,
    ev: Evidence,
    *,
    only: Optional[Sequence[str]] = None,
    lookback_days: int = 3,
) -> None:
    """The live-mode matrix: the newest complete par grid, and how stale it is.

    ``CVLATEST`` is NOT the primitive. Measured 2026-08-07 10:47 ET: it returned
    ``(None, None)`` for all six OIS ``PAR.10Y`` tags probed, including USD, while
    ``CVTSHIST`` at ``MI01`` served the same tags with a stamp one minute old. So
    "live" here is a trailing ``MI01`` window whose last complete row is the
    snapshot, which is both the freshest thing the add-in offers and the only one
    that comes with a timestamp - and a timestamp is what makes staleness
    detectable rather than silent.

    The lag is reported per currency and NOT hidden: outside its own session a
    curve's newest print is legitimately hours old, and a live request has to say
    so rather than present it as current.
    """
    _rule(f"F. live = newest complete MI01 row within {lookback_days}d, all 20 curves")
    report: Dict[str, Any] = {}
    for idx in list(only) if only else _usd_first(INDICES):
        grid_tags = [f"RATES.OIS.{idx}.PAR.{t}" for t in _par_axis(idx)]
        local = datetime.datetime.now()
        start = local - datetime.timedelta(days=lookback_days)
        series = fetch_and_bank(
            client, cache, ev, grid_tags, "MI01", label=f"F live {idx}", start=start
        )
        frame = pd.concat(series, axis=1).sort_index() if series else pd.DataFrame()
        rep = _grid_report(idx, grid_tags, series, frame)
        stamp = rep["last_stamp"]
        lag_min = None
        if stamp is not None:
            lag_min = (local - pd.Timestamp(stamp).to_pydatetime()).total_seconds() / 60.0
        rep["wall_local"] = local.isoformat()
        rep["lag_minutes"] = None if lag_min is None else round(lag_min, 1)
        report[idx] = rep
        print(
            f"    {idx:<16} {rep['n_served']:>2}/{rep['n_tags']:<2} tenors, "
            f"newest complete row {stamp}, "
            f"lag {'n/a' if lag_min is None else f'{lag_min:8.1f} min'}"
        )
        ev.log(
            "live_grid", index=idx,
            **{k: v for k, v in rep.items() if k not in {"last_row", "tenors_served"}},
        )
        ev.summary("stage_f_live", report)
    ev.summary("stage_f_live", report)


def stage_s(client: CitiVelocityExcelClient, cache: CitiVeloTagCache, ev: Evidence) -> None:
    """``CVSTREAM`` - one call, last, from its own client. See the module docstring.

    This is the one probe the hermetic fake cannot model, and the most likely to
    be an RTD function that keeps writing into the cell after the read. So it is
    deliberately the final thing the harvest does: everything else is already
    banked, and if the workbook has to be abandoned it costs nothing.
    """
    _rule("S. CVSTREAM - what is it?")
    tag = "RATES.OIS.USD_SOFR.PAR.10Y"
    for formula, note in (
        (f'=CVSTREAM("{tag}")', "single tag, no other arguments"),
    ):
        local = datetime.datetime.now()
        try:
            value, rows = client.evaluate_formula(formula, rows_needed=8, timeout=90.0)
        except Exception as exc:  # noqa: BLE001 - the answer IS the exception here
            print(f"  {note}: RAISED {type(exc).__name__}: {exc}")
            ev.log("cvstream", formula=formula, error=f"{type(exc).__name__}: {exc}")
            continue
        print(f"  {note}")
        print(f"    settled value : {value!r}  ({type(value).__name__})")
        print(f"    block         : {len(rows)} row(s)")
        for row in rows[:6]:
            print(f"      {row}")
        ev.log(
            "cvstream",
            formula=formula,
            wall_local=local.isoformat(),
            value=_jsonable(value),
            value_type=type(value).__name__,
            n_rows=len(rows),
            rows=_jsonable(rows[:8]),
        )
        # Does it keep ticking? Read the same block again after a pause. A point
        # read that is stable is CVLATEST-like; one that moves is RTD, and an RTD
        # cell is still writing when the workbook is torn down.
        time.sleep(20.0)
        try:
            value2, rows2 = client.evaluate_formula(formula, rows_needed=8, timeout=90.0)
            changed = _jsonable(rows2[:8]) != _jsonable(rows[:8])
            print(f"    re-read 20s later: {'CHANGED (streaming/RTD-like)' if changed else 'identical'}")
            ev.log("cvstream_reread", formula=formula, changed=changed, rows=_jsonable(rows2[:8]))
        except Exception as exc:  # noqa: BLE001
            print(f"    re-read RAISED {type(exc).__name__}: {exc}")
            ev.log("cvstream_reread", formula=formula, error=f"{type(exc).__name__}: {exc}")


# ------------------------------------------------------------------ #
#                               helpers                              #
# ------------------------------------------------------------------ #


def _par_axis(index: str) -> List[str]:
    """The catalog's tenor axis for one curve, as bare tenor tokens."""
    return [t.rsplit(".", 1)[-1] for t in T.ois_par_grid(index)]


def _usd_first(indices: Sequence[str]) -> List[str]:
    """USD_SOFR first: it is the one curve already proven to serve, so a pipeline
    bug shows up on call one rather than after nineteen wasted calls."""
    order = [i for i in indices if i == "USD_SOFR"]
    return order + [i for i in indices if i != "USD_SOFR"]


def _last_weekday(day: datetime.date) -> datetime.date:
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day


def _grid_report(
    index: str,
    grid_tags: Sequence[str],
    series: Dict[str, pd.Series],
    frame: pd.DataFrame,
) -> Dict[str, Any]:
    """What one par-grid fetch actually delivered, tenor by tenor.

    ``n_complete_rows`` is the number of timestamps at which EVERY served tenor
    has a value - the rows a curve can actually be built from. A grid that serves
    44 tenors but never lines them up on one timestamp builds nothing.
    """
    served = {t: s for t, s in series.items() if s is not None and len(s)}
    tenors = [t.rsplit(".", 1)[-1] for t in grid_tags if t in served]
    last_row: Dict[str, float] = {}
    complete = 0
    last_stamp = None
    if not frame.empty:
        complete = int(frame.notna().all(axis=1).sum())
        full = frame[frame.notna().all(axis=1)]
        source = full if not full.empty else frame
        last_stamp = source.index.max()
        row = source.loc[last_stamp]
        last_row = {k.rsplit(".", 1)[-1]: float(v) for k, v in row.items() if pd.notna(v)}
    return {
        "n_tags": len(grid_tags),
        "n_served": len(served),
        "tenors_served": tenors,
        "tenors_missing": [t.rsplit(".", 1)[-1] for t in grid_tags if t not in served],
        "n_rows": 0 if frame.empty else int(len(frame)),
        "n_complete_rows": complete,
        "first_stamp": None if frame.empty else _jsonable(frame.index.min()),
        "last_stamp": _jsonable(last_stamp),
        "last_row": last_row,
    }


def _print_grid_report(index: str, rep: Dict[str, Any]) -> None:
    sample = {k: rep["last_row"].get(k) for k in ("2Y", "5Y", "10Y", "30Y") if k in rep["last_row"]}
    print(
        f"    {index:<16} {rep['n_served']:>2}/{rep['n_tags']:<2} tenors, "
        f"{rep['n_rows']:>5} rows ({rep['n_complete_rows']} complete), "
        f"last {rep['last_stamp']}  "
        + ", ".join(f"{k}={v:.5f}" for k, v in sample.items())
    )
    if rep["tenors_missing"]:
        print(f"      missing: {rep['tenors_missing']}")


# ------------------------------------------------------------------ #
#                                main                                #
# ------------------------------------------------------------------ #

_STAGES = {
    "A": stage_a,
    "B": stage_b,
    "C": stage_c,
    "D": stage_d,
    "E": stage_e,
    "F": stage_f,
    "L": stage_l,
    "S": stage_s,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--stages", default="A", help="comma-separated stage letters, e.g. 'D,B'")
    parser.add_argument("--period", default="1Y", help="history period for stage B")
    parser.add_argument("--only", default="", help="comma-separated Citi index tokens to restrict to")
    parser.add_argument("--skip-controls", action="store_true")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args()

    stages = [s.strip().upper() for s in args.stages.split(",") if s.strip()]
    only = [s.strip().upper() for s in args.only.split(",") if s.strip()] or None
    ev = Evidence(pathlib.Path(args.out), ",".join(stages))
    cache = CitiVeloTagCache()
    print(f"cache root: {cache.base_dir}")
    print(f"evidence  : {ev.path}")

    _rule("connect")
    try:
        client = CitiVelocityExcelClient.connect(
            attempts=1, readiness_timeout=120.0, poll_timeout=600.0
        )
    except Exception as exc:  # noqa: BLE001 - the report IS the exception
        print(f"FAILED: {type(exc).__name__}: {exc}")
        ev.log("connect", error=f"{type(exc).__name__}: {exc}")
        return 1
    print("connected")
    ev.log("connect", ok=True, stages=stages)

    abandoned = False
    try:
        if not args.skip_controls and not stage_controls(client, cache, ev):
            return 2
        for letter in stages:
            fn = _STAGES.get(letter)
            if fn is None:
                print(f"unknown stage {letter!r}; known: {sorted(_STAGES)}")
                continue
            kw: Dict[str, Any] = {}
            if letter == "B":
                kw["period"] = args.period
            if letter in {"B", "C", "F"} and only:
                kw["only"] = only
            fn(client, cache, ev, **kw)
        return 0
    except AsyncTimeoutError as exc:
        # A formula that never settled may STILL resolve, into a block of unknown
        # height. Writing near it is crash trigger 1 and tearing it down is
        # trigger 2, so this workbook is abandoned in place: not closed, not
        # cleared, not written to again. The next invocation gets a fresh one.
        abandoned = True
        print(f"\nASYNC TIMEOUT - abandoning this workbook without closing it.\n{exc}")
        ev.log("abandoned", reason=str(exc))
        traceback.print_exc()
        return 4
    except Exception:  # noqa: BLE001 - print and still tear down cleanly
        traceback.print_exc()
        ev.log("error", traceback=traceback.format_exc()[-4000:])
        return 3
    finally:
        print(f"\ntotal CV* calls this run: {client.calls}")
        ev.log("done", calls=client.calls, abandoned=abandoned)
        if not abandoned:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
