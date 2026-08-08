"""Capture / compare a bit-exact reference of the Citi Velocity read path.

    <env>/python.exe scripts/perf/citivelo_reference_capture.py capture --out <dir>
    <env>/python.exe scripts/perf/citivelo_reference_capture.py compare --ref <dir> --out <dir>

``compare`` fails loudly on ANY difference: values are compared with
``assert_frame_equal(check_exact=True)`` and curves are compared by a SHA-256 of
the raw IEEE-754 bytes of their node discount factors, so a one-ulp change is a
failure, not a rounding note.

Two levels are captured because they fail differently:

* **curve level** - node dates, discount-factor bytes, the fixings series' bytes
  and the whole ``meta_data`` dict. Catches a store fast path that serves the
  wrong snapshot, a cache that leaks a later date's fixings into an earlier
  request, or a lost metadata field.
* **frame level** - what ``TimeseriesBuilder`` actually returns. Catches the
  pricing layer.

The TB mapping cache is bypassed with a throwaway ``cache_stem`` per run: with it
on, an 841-point minute request returns in 0.13 s from cached rows and compares
a cache against itself.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import datetime
import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

NYC = pytz.timezone("America/New_York")

CURVES = [
    "USD-SOFR-1D",
    "EUR-ESTR-1D",
    "GBP-SONIA-1D",
    "CAD-CORRA-1D",
    "JPY-TONAR-1D-LCH",
]

EOD_START = datetime.date(2026, 6, 1)
EOD_END = datetime.date(2026, 7, 31)

#: One full minute session (the 841-point benchmark) plus a second currency and
#: a second day, so a day-frame cache keyed on the wrong thing shows up. The
#: stride is the request frequency: the headline day is asked for minute by
#: minute, the corroborating ones on a coarser grid so the capture stays inside
#: a coffee break.
INTRADAY_DAYS = [
    ("USD-SOFR-1D", datetime.date(2026, 7, 22), "1min"),
    ("USD-SOFR-1D", datetime.date(2026, 7, 23), "7min"),
    ("EUR-ESTR-1D", datetime.date(2026, 7, 22), "7min"),
    ("GBP-SONIA-1D", datetime.date(2026, 7, 22), "7min"),
    ("CAD-CORRA-1D", datetime.date(2026, 7, 22), "13min"),
    ("JPY-TONAR-1D-LCH", datetime.date(2026, 7, 22), "13min"),
]

EOD_TENORS = ["2Y", "5Y", "10Y", "30Y", "5Yx5Y"]
INTRADAY_TENORS = ["5Y", "10Y", "5Yx5Y"]
SPREADS = ["2y/10y"]
FLIES = ["2y/5y/10y"]


# ------------------------------------------------------------------ #
#                              digests                               #
# ------------------------------------------------------------------ #


def _f64_digest(values) -> str:
    arr = np.asarray(list(values), dtype="float64")
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _series_digest(s: pd.Series) -> dict[str, Any]:
    if s is None or len(s) == 0:
        return {"n": 0, "first": None, "last": None, "sha": None}
    return {
        "n": int(len(s)),
        "first": str(s.index.min()),
        "last": str(s.index.max()),
        "sha": _f64_digest(s.to_numpy(dtype="float64")),
        "index_sha": hashlib.sha256(
            np.asarray(pd.DatetimeIndex(s.index).asi8, dtype="int64").tobytes()
        ).hexdigest(),
    }


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v if isinstance(v, (str, int, float, bool, type(None))) else repr(v)


def _curve_digest(curve: Any) -> dict[str, Any]:
    nodes = curve.nodes()
    return {
        "meta": _jsonable(dict(getattr(curve, "_meta_data", {}) or {})),
        "n_nodes": len(nodes),
        "node_dates_sha": hashlib.sha256(
            "|".join(str(d) for d in nodes).encode()
        ).hexdigest(),
        "dfs_sha": _f64_digest(nodes.values()),
        "fixings": _series_digest(getattr(curve, "_fixings", None)),
    }


# ------------------------------------------------------------------ #
#                              capture                               #
# ------------------------------------------------------------------ #


def _mdp():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    return IRSwapsMDP(source="citivelo_excel_rl")


def _tb(mdp):
    from TB.IRSwapsTB import IRSwapsTB

    stem = f"perfref_{uuid.uuid4().hex[:12]}"
    tb = IRSwapsTB(mdp, show_tqdm=False, use_ts_cache=False, cache_stem=stem)
    return tb


def _drop_tb(tb) -> None:
    try:
        path = Path(getattr(tb, "_cache_path", ""))
        tb.close()
        if path and path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _queries(curve: str, tenors: list[str], spreads: list[str], flies: list[str]):
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    qs = [
        IRSwapQuery(curve=curve, tenor=t, value=IRSwapValue.RATE, name=f"{curve}|{t}|RATE")
        for t in tenors
    ]
    qs += [
        IRSwapQuery(curve=curve, tenor=s, value=IRSwapValue.RATE, name=f"{curve}|{s}|RATE")
        for s in spreads + flies
    ]
    # PV01 exercises a value that DOES depend on the struck fixed rate and the
    # notional, so a "RATE-only" shortcut cannot hide behind it.
    qs += [
        IRSwapQuery(
            curve=curve, tenor=tenors[0], value=IRSwapValue.PV01,
            structure_kwargs={"notional": 1_000_000},
            name=f"{curve}|{tenors[0]}|PV01",
        )
    ]
    return qs


#: A swap struck on the March IMM date: on every reference date captured here
#: its first annual accrual period has STARTED but not yet paid, so pricing it
#: consumes published fixings and nothing else in the case list does. Measured
#: 2026-08-08: this prices on USD; currencies whose Citi fixing tail is stale
#: (CAD was three months behind) raise, identically before and after, and are
#: simply absent from the frame.
_SEASONED_EFFECTIVE = datetime.date(2026, 3, 20)
_SEASONED_MATURITY = datetime.date(2031, 3, 20)


def _seasoned_queries(curve: str):
    """A swap whose first accrual period has already elapsed -> needs fixings."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    label = f"seasoned-{_SEASONED_EFFECTIVE}x{_SEASONED_MATURITY}"
    return [
        IRSwapQuery(
            curve=curve,
            effective_date=_SEASONED_EFFECTIVE,
            maturity_date=_SEASONED_MATURITY,
            value=IRSwapValue.RATE,
            name=f"{curve}|{label}|RATE",
        ),
        IRSwapQuery(
            curve=curve,
            effective_date=_SEASONED_EFFECTIVE,
            maturity_date=_SEASONED_MATURITY,
            value=IRSwapValue.NPV,
            structure_kwargs={"notional": 1_000_000, "fixed_rate": 0.03},
            name=f"{curve}|{label}|NPV",
        ),
        # Par-struck NPV: exercises the fixed rate that build_irswap itself
        # chooses, which is the number the duplicate-par-rate change touches.
        IRSwapQuery(
            curve=curve,
            effective_date=_SEASONED_EFFECTIVE,
            maturity_date=_SEASONED_MATURITY,
            value=IRSwapValue.NPV,
            structure_kwargs={"notional": 1_000_000},
            name=f"{curve}|{label}|NPV-par",
        ),
    ]


def capture_frames(out: Path) -> None:
    import logging

    from TB.TimeseriesBuilder import TimeseriesBuilder  # noqa: F401  (parity of imports)

    # A currency whose fixing tail is stale cannot price the seasoned case and
    # says so once per point. The rows are simply absent from the frame - which
    # is the behaviour being pinned - so the tracebacks are noise here.
    logging.getLogger("TB.IRSwapsTB").setLevel(logging.CRITICAL)
    logging.getLogger("IRSwapsTB").setLevel(logging.CRITICAL)

    mdp = _mdp()
    tb = _tb(mdp)
    frames: list[pd.DataFrame] = []
    try:
        for curve in CURVES:
            qs = _queries(curve, EOD_TENORS, SPREADS, FLIES) + _seasoned_queries(curve)
            df = tb.get_timeseries(
                start=EOD_START, end=EOD_END, queries=qs, ignore_cache_miss=True,
            )
            # get_timeseries returns the date as the INDEX; make it a column so
            # it is compared like any other value.
            df = df.reset_index()
            df["case"] = f"eod|{curve}"
            frames.append(df)
            print(f"  eod {curve}: {df.shape}", flush=True)

        for curve, day, freq in INTRADAY_DAYS:
            start = NYC.localize(datetime.datetime.combine(day, datetime.time(3, 0)))
            end = NYC.localize(datetime.datetime.combine(day, datetime.time(17, 0)))
            qs = _queries(curve, INTRADAY_TENORS, SPREADS, []) + _seasoned_queries(curve)
            df = tb.get_timeseries(
                start=start, end=end, queries=qs, freq=freq, ignore_cache_miss=True,
            )
            df = df.reset_index()
            df["case"] = f"intraday|{curve}|{day.isoformat()}|{freq}"
            frames.append(df)
            print(f"  intraday {curve} {day} {freq}: {df.shape}", flush=True)
    finally:
        _drop_tb(tb)

    full = pd.concat(frames, ignore_index=True, sort=False)
    full = full.sort_values(["case", "Date"], key=lambda s: s.map(str)).reset_index(drop=True)
    # ``Date`` is a datetime.date for EOD cases and a Timestamp for intraday
    # ones, so the concatenated column is object-dtype and parquet cannot type
    # it. repr() keeps the value AND the type visible, which is what should be
    # compared: a date silently becoming a midnight Timestamp is a real change.
    full["Date"] = full["Date"].map(repr)
    full.to_parquet(out / "frames.parquet", index=False)
    print(f"frames -> {out / 'frames.parquet'} {full.shape}")


def capture_curves(out: Path) -> None:
    mdp = _mdp()
    rows: dict[str, Any] = {}

    bdays = pd.bdate_range(EOD_START, EOD_END).to_pydatetime()
    eod_sample = [d.date() for d in bdays][::7]
    for curve in CURVES:
        for d in eod_sample:
            try:
                c = mdp.get_data({"curve_name": curve, "timestamp": d})
            except Exception as exc:  # noqa: BLE001 - a cold day is a legitimate miss
                rows[f"eod|{curve}|{d}"] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            rows[f"eod|{curve}|{d}"] = _curve_digest(c)

    for curve, day, _freq in INTRADAY_DAYS:
        base = NYC.localize(datetime.datetime.combine(day, datetime.time(3, 0)))
        # every 37th minute: a stride that is coprime with the hour, so it lands
        # inside, at and outside the published grid
        for i in range(0, 841, 37):
            t = base + datetime.timedelta(minutes=i)
            try:
                c = mdp.get_data({"curve_name": curve, "timestamp": t})
            except Exception as exc:  # noqa: BLE001
                rows[f"min|{curve}|{t.isoformat()}"] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            rows[f"min|{curve}|{t.isoformat()}"] = _curve_digest(c)

    (out / "curves.json").write_text(json.dumps(rows, indent=1, sort_keys=True))
    print(f"curves -> {out / 'curves.json'} ({len(rows)} points)")


def capture_fixings(out: Path) -> None:
    """Direct fixings_for digests, incl. the reference_date-leak shape."""
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import citi_index_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.fixings import fixings_for

    rows: dict[str, Any] = {}
    dates = [
        datetime.date(2019, 5, 15),
        datetime.date(2023, 1, 4),
        datetime.date(2026, 6, 1),
        datetime.date(2026, 7, 22),
        datetime.date(2026, 7, 31),
    ]
    # DESCENDING on purpose: a cache that filters a previously-cached, longer
    # series in place leaks later dates into the earlier request.
    for curve in CURVES:
        idx = citi_index_for_curve_name(curve)
        for d in sorted(dates, reverse=True):
            r = fixings_for(curve, idx, reference_date=d)
            rows[f"{curve}|{d}"] = {
                "source": r.source,
                "contributions": _jsonable(r.contributions),
                **_series_digest(r.series),
            }
    (out / "fixings.json").write_text(json.dumps(rows, indent=1, sort_keys=True))
    print(f"fixings -> {out / 'fixings.json'} ({len(rows)} points)")


# ------------------------------------------------------------------ #
#                              compare                               #
# ------------------------------------------------------------------ #


def compare(ref: Path, new: Path) -> int:
    failures = 0

    a = pd.read_parquet(ref / "frames.parquet")
    b = pd.read_parquet(new / "frames.parquet")
    try:
        pd.testing.assert_frame_equal(a, b, check_exact=True, check_dtype=True)
        print(f"OK  frames: {a.shape} identical (check_exact=True)")
    except AssertionError as exc:
        failures += 1
        print(f"FAIL frames:\n{exc}")
        _explain_frame_diff(a, b)

    for name in ("curves.json", "fixings.json"):
        ja = json.loads((ref / name).read_text())
        jb = json.loads((new / name).read_text())
        keys = sorted(set(ja) | set(jb))
        bad = [k for k in keys if ja.get(k) != jb.get(k)]
        if bad:
            failures += 1
            print(f"FAIL {name}: {len(bad)} of {len(keys)} differ")
            for k in bad[:10]:
                print(f"  - {k}\n      ref={ja.get(k)}\n      new={jb.get(k)}")
        else:
            print(f"OK  {name}: {len(keys)} entries identical")

    return failures


def _explain_frame_diff(a: pd.DataFrame, b: pd.DataFrame) -> None:
    if list(a.columns) != list(b.columns):
        print(f"  columns differ: ref-only={set(a.columns) - set(b.columns)} "
              f"new-only={set(b.columns) - set(a.columns)}")
        return
    if len(a) != len(b):
        print(f"  row count {len(a)} -> {len(b)}")
        return
    for col in a.columns:
        if a[col].dtype.kind == "f":
            diff = ~np.isclose(a[col].to_numpy(), b[col].to_numpy(), rtol=0, atol=0, equal_nan=True)
            if diff.any():
                i = int(np.argmax(diff))
                print(f"  {col}: {int(diff.sum())} differ, first at row {i}: "
                      f"{a[col].iloc[i]!r} -> {b[col].iloc[i]!r}")
        elif not a[col].equals(b[col]):
            print(f"  {col}: non-float column differs")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["capture", "compare"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.action == "capture":
        capture_fixings(out)
        capture_curves(out)
        capture_frames(out)
        return

    if not args.ref:
        raise SystemExit("compare needs --ref")
    capture_fixings(out)
    capture_curves(out)
    capture_frames(out)
    failures = compare(Path(args.ref), out)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
