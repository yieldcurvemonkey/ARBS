r"""Measure what a ``t-1min`` curve request on the Citi minute store actually returns.

Why this exists
---------------
Dealer-direction inference reprices a printed swap against the curve one minute
*before* the print, and reads which side of mid the trade landed. That inference
is only as good as the snapshot it prices against: a curve served from *after*
the trade already contains the print's own market impact, which biases the call
toward whatever the trade actually was.

``IRSwapsMDP._load_citivelo_excel_minute_store_point`` selects with
``(stamps - wanted).abs().argmin()`` over a ``(D, D-1, D+1)`` window and applies
no staleness bound at all. This script quantifies the consequence over the real
population of requests the direction work will make - every eligible leg on the
``_v3`` SDR tape, snapped by production's own ``snap_timestamp`` - rather than a
synthetic uniform grid.

Stages (each writes a parquet/CSV under ``--out`` and can be re-run alone)
-------------------------------------------------------------------------
``demand``   pull ``(rate_index, execution minute, n_legs)`` from the tape.
``density``  per stored day: snapshot count, session start/end, gap profile.
``lag``      the core measurement - for every distinct requested minute, what the
             current rule serves, what a backward-only rule would serve, the
             signed lag of each, and whether the served snapshot even belongs to
             the requested calendar day.
``verify``   probe validation: call the *real* loader on sampled requests and
             assert it serves exactly what ``lag`` predicted.
``bp``       translate lag into basis points by repricing 2Y/5Y/10Y/30Y par swaps
             on the served snapshot against the true nearest-preceding one.
``session``  split every request into "Citi never published this minute" vs
             "Citi published it and we do not hold it", and emit the repair
             work-list for the days that stop before the session does.
``report``   the summary tables that go into the written report.

Sign convention, fixed once and used everywhere
-----------------------------------------------
``lag = requested - served``. **Positive = the served snapshot predates the
request (stale, the normal case). Negative = the served snapshot is from the
FUTURE relative to the request.** Note that ``IRSwapsMDP._assert_snapshot_fresh``
computes the same quantity and only raises when ``lag > limit`` - it is therefore
structurally blind to negative lag, which is a second reason it cannot be reused
here unchanged, independent of its 12-hour default being the wrong magnitude.

Running it
----------
``python scripts/citivelo_minute_lag_audit.py all --out <dir>`` with
``ARBS_SUPABASE_ENABLED=0`` set. Uses the **local** ``CurveStore`` (the Supabase
mirror lags by hundreds of days and is missing Fed Funds entirely).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import zoneinfo
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# The measurement must not push or pull the Supabase L2 mirror.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

UTC = datetime.timezone.utc

#: rate_index_clean -> the IRSwaps curve name the direction work prices it on.
CURVE_FOR_INDEX = {
    "SOFR": "USD-SOFR-1D",
    "FED_FUNDS": "USD-FEDFUNDS-1D",
}

#: Par tenors used for the basis-point translation.
BP_TENORS = ("2Y", "5Y", "10Y", "30Y")


def _asset(curve_name: str) -> str:
    return f"{curve_name}-CITIVELOEXCELMIN"


# --------------------------------------------------------------------------- #
#                                stage: demand                                #
# --------------------------------------------------------------------------- #


def stage_demand(out: Path, start: str, end: str) -> pd.DataFrame:
    """``(rate_index, execution_minute_utc, n_legs)`` for the eligible universe.

    The filters are ``trade_selection.ELIGIBLE_LEGS_SQL``'s verbatim - the same
    population the direction classifier signs. Aggregated to the minute in SQL
    because 2.0M legs collapse to ~0.5M distinct minutes, and the snapshot a
    request resolves to depends only on the minute.

    ``date_trunc('minute', ...)`` on a ``timestamptz`` truncates in the session
    zone, which is safe for minute granularity because every zone in play is a
    whole number of minutes from UTC. The ``t-1min`` snap itself is applied in
    Python by production's own ``snap_timestamp`` rather than in SQL, so the DST
    and NaT rules cannot diverge from what the classifier does.
    """
    import psycopg2

    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    sql = f"""
    SELECT l.rate_index_clean AS rate_index,
           date_trunc('minute', COALESCE(l.original_execution_timestamp,
                                         l.execution_timestamp)) AS exec_minute,
           count(*) AS n_legs
    FROM {LEGS_TABLE} l
    WHERE l.as_of_date BETWEEN %(start)s AND %(end)s
      AND l.economic_class = 'ECONOMIC_FLOW'
      AND l.contributes_to_flow = true
      AND l.venue = 'D2C'
      AND l.rate_index_clean IN ('SOFR', 'FED_FUNDS')
      AND l.fixed_rate IS NOT NULL
    GROUP BY 1, 2
    """
    url = resolve_pg_url()
    frames: List[pd.DataFrame] = []
    # Chunked by quarter: a single 2.5-year scan on the pooler is exactly the
    # shape of read that dies to a statement timeout when the tape pipeline is
    # migrating schema underneath it.
    for lo, hi in _quarters(start, end):
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '900s'")
                cur.execute(sql, {"start": lo, "end": hi})
                cols = [c.name for c in cur.description]
                frames.append(pd.DataFrame(cur.fetchall(), columns=cols))
        print(f"  demand {lo}..{hi}: {len(frames[-1]):,} minutes", flush=True)
    df = pd.concat(frames, ignore_index=True)
    df["exec_minute"] = pd.to_datetime(df["exec_minute"], utc=True)
    df = df.groupby(["rate_index", "exec_minute"], as_index=False)["n_legs"].sum()
    _write(df, out / "demand.parquet")
    return df


def _quarters(start: str, end: str) -> List[Tuple[str, str]]:
    lo = pd.Timestamp(start).date()
    hi = pd.Timestamp(end).date()
    spans = []
    cur = lo
    while cur <= hi:
        nxt = min(hi, (pd.Timestamp(cur) + pd.DateOffset(months=3) - pd.Timedelta(days=1)).date())
        spans.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt + datetime.timedelta(days=1)
    return spans


# --------------------------------------------------------------------------- #
#                                stage: density                               #
# --------------------------------------------------------------------------- #


def stage_density(out: Path, curves: Sequence[str]) -> pd.DataFrame:
    """Per stored day: how many snapshots, when the session ran, how gappy.

    Reads only the ``timestamp_utc`` column out of each partition. "Day present"
    is emphatically not "1-minute data available", and a count alone does not
    separate 240 evenly-spaced snapshots from 240 that stop at 11:58 - so the
    session bounds and the gap profile are recorded beside the count.
    """
    import pyarrow.parquet as pq

    from Caching.curve_store import CurveStore

    store = CurveStore.default()
    rows = []
    for curve in curves:
        asset = _asset(curve)
        days = sorted(store.available_dates(asset))
        print(f"  density {asset}: {len(days)} days", flush=True)
        for day in days:
            pdir = store.raw_partition_dir(asset, day)
            stamps: List[np.ndarray] = []
            try:
                files = [e.path for e in os.scandir(pdir) if e.name.endswith(".parquet")]
            except (FileNotFoundError, NotADirectoryError):
                files = []
            for f in files:
                tbl = pq.read_table(f, columns=["timestamp_utc"])
                stamps.append(tbl.column("timestamp_utc").to_pandas().values)
            if not stamps:
                continue
            s = pd.to_datetime(pd.Series(np.concatenate(stamps)), utc=True).sort_values()
            gaps = s.diff().dropna().dt.total_seconds()
            rows.append(
                {
                    "curve": curve,
                    "asset": asset,
                    "local_date": day,
                    "n_snapshots": int(len(s)),
                    "first_utc": s.iloc[0],
                    "last_utc": s.iloc[-1],
                    "median_gap_s": float(gaps.median()) if len(gaps) else np.nan,
                    "max_gap_s": float(gaps.max()) if len(gaps) else np.nan,
                    "p90_gap_s": float(gaps.quantile(0.90)) if len(gaps) else np.nan,
                    "n_duplicate_stamps": int(len(s) - s.nunique()),
                }
            )
    df = pd.DataFrame(rows)
    _write(df, out / "density.parquet")
    return df


# --------------------------------------------------------------------------- #
#                                  stage: lag                                 #
# --------------------------------------------------------------------------- #


def _resolve_wanted(ts) -> Tuple[str, Optional[datetime.datetime]]:
    """Production's own request resolution, so the audit cannot drift from it.

    Returns ``(mode, wanted)``. ``mode != "intraday"`` means the minute store is
    never consulted at all: ``resolve_request`` sends exact-midnight ET to the
    **EOD** branch, which serves that calendar day's *close* - a curve up to
    sixteen hours in the future of the request. ``snap_timestamp`` produces
    exactly midnight for any trade printed in the 00:01:00-00:01:59 ET minute.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import from_wire_naive, resolve_request

    r = resolve_request(ts)
    if r.mode != "intraday" or r.wire_instant is None:
        return r.mode, None
    return "intraday", from_wire_naive(r.wire_instant)


def select_current(stamps_ns: np.ndarray, wanted_ns: np.ndarray) -> np.ndarray:
    """Positional ``argmin(|stamps - wanted|)`` - the rule in production today.

    ``np.argmin`` returns the FIRST minimum, which is what
    ``pandas.Series.values.argmin()`` does, so equidistant snapshots break the
    same way they break in ``_load_citivelo_excel_minute_store_point``. The
    window is deliberately left unsorted and in ``(D, D-1, D+1)`` order, because
    that order is what decides those ties.
    """
    out = np.empty(len(wanted_ns), dtype=np.int64)
    step = 512
    for i in range(0, len(wanted_ns), step):
        chunk = wanted_ns[i : i + step]
        out[i : i + step] = np.abs(stamps_ns[None, :] - chunk[:, None]).argmin(axis=1)
    return out


def select_backward(stamps_ns: np.ndarray, wanted_ns: np.ndarray) -> np.ndarray:
    """Positional index of the latest stamp at or before each request, else -1.

    Ties (the same instant stored twice, which overlapping re-warmed partitions
    really do produce - see ``_reconstruct_rows_by_position``) resolve to the
    FIRST positional occurrence. With the window in ``(D, D-1, D+1)`` order that
    prefers the requested day's own copy over a neighbour's, which is the
    preference a caller asking for that day would state if asked.
    """
    out = np.full(len(wanted_ns), -1, dtype=np.int64)
    step = 512
    for i in range(0, len(wanted_ns), step):
        chunk = wanted_ns[i : i + step]
        d = stamps_ns[None, :] - chunk[:, None]          # served - wanted
        ok = d <= 0
        masked = np.where(ok, d, np.iinfo(np.int64).min)
        pos = masked.argmax(axis=1)                       # largest (least negative)
        any_ok = ok.any(axis=1)
        out[i : i + step] = np.where(any_ok, pos, -1)
    return out


def stage_lag(out: Path, demand: pd.DataFrame, density: pd.DataFrame) -> pd.DataFrame:
    """For every requested minute: what is served now, and what should be.

    One prepared ``day_window`` per requested local session - the same window
    object, in the same day order, that the loader itself builds - so the
    simulation exercises production's data, not a re-read of it.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.day_cache import day_window
    from Caching.curve_store import CurveStore
    from SDRUtils.stir_flow.pricing import snap_timestamp

    store = CurveStore.default()
    dens = density.set_index(["curve", "local_date"]) if len(density) else None

    records: List[Dict] = []
    for rate_index, curve in CURVE_FOR_INDEX.items():
        sub = demand[demand["rate_index"] == rate_index]
        if sub.empty:
            continue
        asset = _asset(curve)
        entry = entry_for_curve_name(curve)
        local_zone = zoneinfo.ZoneInfo(entry.local_timezone)

        # Production's snap rule, applied to each distinct execution minute.
        snaps = [snap_timestamp(t, None) for t in sub["exec_minute"]]
        modes_wanted = [_resolve_wanted(s) for s in snaps]

        rows = pd.DataFrame(
            {
                "curve": curve,
                "rate_index": rate_index,
                "exec_minute": sub["exec_minute"].values,
                "n_legs": sub["n_legs"].values,
                "snap": snaps,
                "mode": [m for m, _ in modes_wanted],
                "wanted": [w for _, w in modes_wanted],
            }
        )
        # Requests that never reach the minute store at all.
        offpath = rows[rows["mode"] != "intraday"].copy()
        for r in offpath.to_dict("records"):
            records.append(
                {
                    **{k: r[k] for k in ("curve", "rate_index", "exec_minute", "n_legs", "mode")},
                    "snap_utc": pd.Timestamp(r["snap"]).tz_convert("UTC"),
                    "local_date": pd.Timestamp(r["snap"]).tz_convert(local_zone).date(),
                    "outcome": "not_intraday",
                }
            )

        rows = rows[rows["mode"] == "intraday"].copy()
        rows["local_date"] = [w.astimezone(local_zone).date() for w in rows["wanted"]]
        rows["wanted_ns"] = [pd.Timestamp(w).tz_convert("UTC").value for w in rows["wanted"]]

        n_days = rows["local_date"].nunique()
        print(f"  lag {asset}: {len(rows):,} minutes over {n_days} sessions", flush=True)

        for i, (local_date, grp) in enumerate(rows.groupby("local_date", sort=True)):
            days = tuple(local_date + datetime.timedelta(days=o) for o in (0, -1, 1))
            window = day_window(store, asset, days)
            wanted_ns = grp["wanted_ns"].to_numpy(dtype=np.int64)
            base = {
                "curve": curve,
                "rate_index": rate_index,
                "local_date": local_date,
                "mode": "intraday",
                "day_present": store.has_day(asset, local_date),
                "window_rows": 0 if window.empty else int(len(window.stamps)),
            }
            if window.empty:
                for ex, nl, wns in zip(grp["exec_minute"], grp["n_legs"], wanted_ns):
                    records.append(
                        {**base, "exec_minute": ex, "n_legs": int(nl),
                         "snap_utc": pd.Timestamp(wns, tz="UTC"), "outcome": "empty_window"}
                    )
                continue

            stamps_ns = window.stamps.to_numpy(dtype="datetime64[ns]").astype(np.int64)
            pos_cur = select_current(stamps_ns, wanted_ns)
            pos_back = select_backward(stamps_ns, wanted_ns)

            served_cur = stamps_ns[pos_cur]
            served_back = np.where(pos_back >= 0, stamps_ns[np.maximum(pos_back, 0)], np.nan)

            cur_local = pd.DatetimeIndex(pd.to_datetime(served_cur, utc=True)).tz_convert(local_zone).date

            for j, (ex, nl) in enumerate(zip(grp["exec_minute"], grp["n_legs"])):
                lag_cur = (wanted_ns[j] - served_cur[j]) / 1e9
                has_back = pos_back[j] >= 0
                lag_back = (wanted_ns[j] - stamps_ns[pos_back[j]]) / 1e9 if has_back else np.nan
                records.append(
                    {
                        **base,
                        "exec_minute": ex,
                        "n_legs": int(nl),
                        "snap_utc": pd.Timestamp(int(wanted_ns[j]), tz="UTC"),
                        "outcome": "served",
                        "served_cur_utc": pd.Timestamp(int(served_cur[j]), tz="UTC"),
                        "lag_cur_s": float(lag_cur),
                        "served_cur_local_date": cur_local[j],
                        "same_day_cur": bool(cur_local[j] == local_date),
                        "served_back_utc": (
                            pd.Timestamp(int(stamps_ns[pos_back[j]]), tz="UTC") if has_back else pd.NaT
                        ),
                        "lag_back_s": float(lag_back) if has_back else np.nan,
                        "has_backward": bool(has_back),
                        "differs": bool(has_back and pos_back[j] != pos_cur[j]),
                        "pos_cur": int(pos_cur[j]),
                        "pos_back": int(pos_back[j]),
                    }
                )
            if i % 100 == 0:
                print(f"    .. {local_date} ({i}/{n_days})", flush=True)

    df = pd.DataFrame(records)
    if dens is not None and len(df):
        df = df.merge(
            density[["curve", "local_date", "n_snapshots", "max_gap_s", "median_gap_s",
                     "first_utc", "last_utc"]],
            on=["curve", "local_date"], how="left",
        )
    _write(df, out / "lag.parquet")
    return df


# --------------------------------------------------------------------------- #
#                                stage: verify                                #
# --------------------------------------------------------------------------- #


def stage_verify(out: Path, lag: pd.DataFrame, n: int = 24, seed: int = 20260809) -> pd.DataFrame:
    """Check the simulation against production, which is the only real oracle.

    A probe that reuses production's *functions* but not its *parameters* has
    already produced a confident wrong answer in this repo. So this does not
    compare code paths - it calls the real
    ``_load_citivelo_excel_minute_store_point`` and asserts the timestamp it
    hands back is byte-for-byte the one ``stage_lag`` predicted, on a sample
    stratified across dense days, sparse days, future-served cases and
    wrong-calendar-day cases.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    served = lag[lag["outcome"] == "served"].copy()
    rng = np.random.default_rng(seed)
    picks: List[pd.Series] = []

    strata = {
        "future_served": served[served["lag_cur_s"] < 0],
        "wrong_day": served[~served["same_day_cur"]],
        "sparse_day": served[served["n_snapshots"].fillna(0) < 200],
        "dense_day": served[served["n_snapshots"].fillna(0) >= 1000],
        "large_lag": served[served["lag_cur_s"] > 600],
        "typical": served[(served["lag_cur_s"] >= 0) & (served["lag_cur_s"] <= 120)],
    }
    per = max(2, n // max(1, len(strata)))
    for name, frame in strata.items():
        if frame.empty:
            print(f"  verify: stratum {name} is EMPTY", flush=True)
            continue
        idx = rng.choice(len(frame), size=min(per, len(frame)), replace=False)
        for k in idx:
            row = frame.iloc[int(k)].copy()
            row["stratum"] = name
            picks.append(row)

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL-RL")
    rows = []
    for row in picks:
        req = pd.Timestamp(row["snap_utc"]).tz_convert("America/New_York").to_pydatetime()
        curve = mdp._load_citivelo_excel_minute_store_point(
            curve_name=row["curve"], timestamp=req
        )
        meta = {} if curve is None else (curve.meta() or {})
        got = None if curve is None else pd.Timestamp(meta["timestamp"]).tz_convert("UTC")
        want = pd.Timestamp(row["served_cur_utc"])
        rows.append(
            {
                "stratum": row["stratum"],
                "curve": row["curve"],
                "requested": req,
                "predicted_served_utc": want,
                "production_served_utc": got,
                "match": bool(got is not None and got == want),
                "predicted_lag_s": row["lag_cur_s"],
                "production_lag_meta_s": meta.get("snapshot_lag_seconds"),
            }
        )
    df = pd.DataFrame(rows)
    _write(df, out / "verify.parquet")
    n_ok = int(df["match"].sum()) if len(df) else 0
    print(f"  verify: {n_ok}/{len(df)} predictions matched production", flush=True)
    return df


# --------------------------------------------------------------------------- #
#                                  stage: bp                                  #
# --------------------------------------------------------------------------- #


def stage_bp(out: Path, lag: pd.DataFrame, n: int = 300, seed: int = 20260809) -> pd.DataFrame:
    """What the lag is worth, in basis points, on real par swaps.

    A lag figure on its own tells nobody whether it matters. This reprices
    2Y/5Y/10Y/30Y par rates on the snapshot the current rule serves against the
    true nearest-preceding snapshot, through the same ``IRSwapQuery`` path a
    caller uses - so any convention error is common to both sides and the
    difference is the lag's own contribution.

    Sampling is **weighted by legs** within each stratum, because the question is
    "how much rate error does the tape actually eat", not "how much could it in
    principle".
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.day_cache import day_window
    from MDP.IRSwaps.CITIVELO_EXCEL.tie_out import query_par_rate
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Caching.curve_store import CurveStore

    from MDP.IRSwaps.CITIVELO_EXCEL import register as register_defs

    register_defs()

    cand = lag[(lag["outcome"] == "served") & lag["has_backward"] & lag["differs"]].copy()
    if cand.empty:
        print("  bp: no request differs between the two rules - nothing to price", flush=True)
        return pd.DataFrame()

    rng = np.random.default_rng(seed)
    strata = {
        "future_served": cand[cand["lag_cur_s"] < 0],
        "wrong_day": cand[~cand["same_day_cur"]],
        "backward_far": cand[(cand["lag_cur_s"] >= 0) & (cand["lag_back_s"] > 600)],
        "other": cand[(cand["lag_cur_s"] >= 0) & (cand["lag_back_s"] <= 600)],
    }
    per = max(1, n // max(1, len([f for f in strata.values() if not f.empty])))
    picks = []
    for name, frame in strata.items():
        if frame.empty:
            continue
        w = frame["n_legs"].to_numpy(dtype=float)
        w = w / w.sum()
        take = min(per, len(frame))
        idx = rng.choice(len(frame), size=take, replace=False, p=w if take < len(frame) else None)
        for k in np.atleast_1d(idx):
            r = frame.iloc[int(k)].copy()
            r["stratum"] = name
            picks.append(r)

    store = CurveStore.default()
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL-RL")
    rows = []
    for r in picks:
        curve_name = r["curve"]
        asset = _asset(curve_name)
        entry = entry_for_curve_name(curve_name)
        local_zone = zoneinfo.ZoneInfo(entry.local_timezone)
        local_date = r["local_date"]
        days = tuple(local_date + datetime.timedelta(days=o) for o in (0, -1, 1))
        window = day_window(store, asset, days)
        if window.empty:
            continue
        wanted = pd.Timestamp(r["snap_utc"]).tz_convert(local_zone).to_pydatetime()
        try:
            handles = mdp._reconstruct_rows_by_position(
                store=store, frame=window.frame,
                positions=sorted({int(r["pos_cur"]), int(r["pos_back"])}), workers=1,
            )
        except Exception as exc:  # noqa: BLE001 - a bad row is data, report it
            rows.append({"curve": curve_name, "error": str(exc)})
            continue
        h_cur = handles.get(int(r["pos_cur"]))
        h_back = handles.get(int(r["pos_back"]))
        if h_cur is None or h_back is None:
            continue

        out_row = {
            "stratum": r["stratum"], "curve": curve_name, "local_date": local_date,
            "snap_utc": r["snap_utc"], "n_legs": int(r["n_legs"]),
            "lag_cur_s": r["lag_cur_s"], "lag_back_s": r["lag_back_s"],
            "same_day_cur": bool(r["same_day_cur"]),
            "n_snapshots": r.get("n_snapshots"),
        }
        for label, handle, actual in (
            ("cur", h_cur, pd.Timestamp(r["served_cur_utc"]).tz_convert(local_zone).to_pydatetime()),
            ("back", h_back, pd.Timestamp(r["served_back_utc"]).tz_convert(local_zone).to_pydatetime()),
        ):
            wrapped = mdp._wrap_citivelo_excel_minute(
                curve_name=curve_name, asset=asset, local_zone=local_zone,
                wanted=wanted, actual=actual, rl_curve_handle=handle,
            )
            for tenor in BP_TENORS:
                try:
                    pct = query_par_rate(wrapped, curve_name=curve_name, tenor=tenor)
                except Exception as exc:  # noqa: BLE001
                    out_row[f"{label}_{tenor}"] = np.nan
                    out_row.setdefault("error", str(exc))
                else:
                    out_row[f"{label}_{tenor}"] = pct
        for tenor in BP_TENORS:
            a, b = out_row.get(f"cur_{tenor}"), out_row.get(f"back_{tenor}")
            out_row[f"diff_bp_{tenor}"] = (
                (a - b) * 100.0 if a is not None and b is not None and a == a and b == b else np.nan
            )
        rows.append(out_row)
        if len(rows) % 25 == 0:
            print(f"    bp .. {len(rows)}/{len(picks)}", flush=True)

    df = pd.DataFrame(rows)
    _write(df, out / "bp.parquet")
    return df


# --------------------------------------------------------------------------- #
#                               stage: session                                #
# --------------------------------------------------------------------------- #


def stage_session(out: Path, lag: pd.DataFrame) -> pd.DataFrame:
    """Split every requested minute into "Citi has nothing" vs "we did not fetch".

    This is the stage that answers whether the boundary contamination is worth
    chasing upstream. A minute Citi never published is a hard limit on which
    prints can be classified at all; a minute Citi published and we do not hold
    is a backlog. The store cannot tell them apart on its own - the stored day
    just stops - which is why ``CITIVELO_EXCEL/citi_session.py`` exists.

    Also emits the repair work-list: the days that stop before the session does.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import (
        UnknownSessionError,
        expected_minutes,
        is_truncated,
        publishes,
    )
    from Caching.curve_store import CurveStore

    import pyarrow.parquet as pq

    store = CurveStore.default()

    # ---- per stored day: what is there, and what should be ---------------
    day_rows: List[Dict] = []
    stamps_by_day: Dict[Tuple[str, datetime.date], set] = {}
    for curve in CURVE_FOR_INDEX.values():
        asset = _asset(curve)
        for day in sorted(store.available_dates(asset)):
            pdir = store.raw_partition_dir(asset, day)
            try:
                files = [e.path for e in os.scandir(pdir) if e.name.endswith(".parquet")]
            except FileNotFoundError:
                continue
            if not files:
                continue
            arr = np.concatenate(
                [pq.read_table(f, columns=["timestamp_utc"]).column("timestamp_utc")
                 .to_pandas().to_numpy() for f in files]
            )
            s = pd.to_datetime(pd.Series(arr), utc=True).sort_values()
            stamps_by_day[(curve, day)] = set(s.values)
            try:
                exp = expected_minutes(curve, day)
                trunc = bool(is_truncated(curve, day, pd.Timestamp(s.iloc[-1])))
            except UnknownSessionError:
                exp, trunc = 0, False
            gaps = s.diff().dropna().dt.total_seconds()
            median_gap = float(gaps.median()) if len(gaps) else np.nan
            completeness = float(len(s) / exp) if exp else np.nan
            # A coarse day and a truncated day are both "incomplete" and want
            # completely different work. The 2022-2023 era was published to us on
            # a TEN-MINUTE grid across the same 01:00-22:59 span - 132 rows, not
            # 1,320 - and re-fetching it at one minute is a different job from
            # completing a dense day that a chunk boundary cut short. Lumping
            # them into one list is how the second, smaller, and entirely
            # self-inflicted problem stays invisible behind the first.
            if median_gap >= 300:
                reason = "coarse_era"
            elif trunc:
                reason = "truncated_end"
            elif completeness == completeness and completeness < 0.97:
                reason = "interior_gaps"
            else:
                reason = "complete"
            day_rows.append(
                {
                    "curve": curve, "local_date": day, "weekday": day.strftime("%a"),
                    "stored": int(len(s)), "expected": int(exp),
                    "first_utc": pd.Timestamp(s.iloc[0]), "last_utc": pd.Timestamp(s.iloc[-1]),
                    "truncated": trunc, "median_gap_s": median_gap,
                    "completeness": completeness, "reason": reason,
                }
            )
    days = pd.DataFrame(day_rows)
    _write(days, out / "session_days.parquet")

    for curve, g in days.groupby("curve"):
        g24 = g[[d.year >= 2024 for d in g["local_date"]]]
        counts = g["reason"].value_counts().to_dict()
        print(f"  {curve}: {len(g)} stored days {counts}; "
              f"2024+ median completeness {g24['completeness'].median():.3f}", flush=True)

    # ---- per requested minute: which side of the line is it on -----------
    rows: List[Dict] = []
    idx = days.set_index(["curve", "local_date"]) if len(days) else None
    for r in lag.itertuples():
        snap = pd.Timestamp(r.snap_utc)
        curve = r.curve
        try:
            citi_has = publishes(curve, snap)
        except UnknownSessionError:
            citi_has = None
        key = (curve, r.local_date)
        rec = idx.loc[key] if idx is not None and key in idx.index else None
        if not citi_has:
            klass = "citi_publishes_nothing"
        elif rec is None:
            klass = "no_stored_day"
        elif snap < rec["first_utc"] or snap > rec["last_utc"]:
            klass = "in_session_outside_stored_span"
        elif np.datetime64(snap.tz_convert(None)) not in stamps_by_day.get(key, ()):
            klass = "in_session_interior_gap"
        else:
            klass = "exact_minute_present"
        rows.append(
            {"curve": curve, "klass": klass, "n_legs": int(r.n_legs),
             "lag_cur_s": getattr(r, "lag_cur_s", np.nan), "snap_utc": snap}
        )
    df = pd.DataFrame(rows)
    _write(df, out / "session_split.parquet")

    # ---- the repair work-list -------------------------------------------
    repair = days[days["reason"] != "complete"].copy()
    repair["missing_minutes"] = (repair["expected"] - repair["stored"]).clip(lower=0)
    repair = repair.sort_values(["curve", "reason", "local_date"])
    _write(repair, out / "session_repair_list.parquet")
    if len(repair):
        (out / "session_repair_list.csv").write_text(
            repair[["curve", "local_date", "weekday", "reason", "stored", "expected",
                    "missing_minutes", "median_gap_s"]].to_csv(index=False),
            encoding="utf-8",
        )
        for (curve, reason), g in repair.groupby(["curve", "reason"]):
            print(f"  repair {curve:18s} {reason:14s} {len(g):>4d} day(s), "
                  f"{int(g['missing_minutes'].sum()):>8,} missing minutes", flush=True)
    return df


# --------------------------------------------------------------------------- #
#                                stage: drift                                 #
# --------------------------------------------------------------------------- #


def stage_drift(
    out: Path,
    density: pd.DataFrame,
    lag: pd.DataFrame,
    n_days: int = 12,
    seed: int = 20260809,
) -> pd.DataFrame:
    """How many basis points a curve moves over an elapsed interval.

    This is the number that decides the tolerance, and it has to be measured
    rather than intuited: "60 seconds" is only defensible if 60 seconds of drift
    is small against the edge the direction call is trying to read (prints land
    within a basis point or two of mid).

    Method: on dense sessions, price 2Y/5Y/10Y/30Y par rates on every snapshot in
    two one-hour blocks (07:00-08:00 and 13:00-14:00 ET, the two busiest hours on
    the tape) plus a ten-minute grid across the whole session, then take
    ``|r(t) - r(t-delta)|`` for every pair that exists. Both sides of every pair
    are the same curve on the same day through the same pricing path, so
    convention bias cancels and what is left is the movement.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import register as register_defs
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.day_cache import single_day
    from MDP.IRSwaps.CITIVELO_EXCEL.tie_out import query_par_rate
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Caching.curve_store import CurveStore

    register_defs()
    store = CurveStore.default()
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL-RL")
    rng = np.random.default_rng(seed)

    traded = (
        lag[lag["outcome"] == "served"].groupby(["curve", "local_date"])["n_legs"].sum()
        if len(lag) else pd.Series(dtype=float)
    )

    rows = []
    for curve, dens in density.groupby("curve"):
        dense = dens[dens["n_snapshots"] >= 1000]
        if dense.empty:
            print(f"  drift {curve}: no dense day", flush=True)
            continue
        # Spread the sample across the span rather than clustering it, and keep
        # only days the tape actually traded on.
        dense = dense[
            [(curve, d) in traded.index for d in dense["local_date"]]
        ] if len(traded) else dense
        if dense.empty:
            continue
        dense = dense.sort_values("local_date").reset_index(drop=True)
        take = min(n_days, len(dense))
        pick = np.unique(np.linspace(0, len(dense) - 1, take).round().astype(int))
        days = [dense.loc[i, "local_date"] for i in pick]

        entry = entry_for_curve_name(curve)
        local_zone = zoneinfo.ZoneInfo(entry.local_timezone)
        asset = _asset(curve)

        for day in days:
            window = single_day(store, asset, day)
            if window.empty:
                continue
            stamps = window.stamps
            local = pd.DatetimeIndex(stamps).tz_convert(local_zone)
            minutes = local.hour * 60 + local.minute
            block = ((minutes >= 7 * 60) & (minutes < 8 * 60)) | (
                (minutes >= 13 * 60) & (minutes < 14 * 60)
            )
            grid = (minutes % 10) == 0
            keep = np.flatnonzero(block | grid)
            if len(keep) < 4:
                continue
            try:
                handles = mdp._reconstruct_rows_by_position(
                    store=store, frame=window.frame, positions=[int(i) for i in keep], workers=1,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    drift {curve} {day}: reconstruct failed ({exc})", flush=True)
                continue
            priced: Dict[int, Dict[str, float]] = {}
            for pos, handle in handles.items():
                actual = pd.Timestamp(stamps.iloc[pos]).tz_convert(local_zone).to_pydatetime()
                wrapped = mdp._wrap_citivelo_excel_minute(
                    curve_name=curve, asset=asset, local_zone=local_zone,
                    wanted=actual, actual=actual, rl_curve_handle=handle,
                )
                vals = {}
                for tenor in BP_TENORS:
                    try:
                        vals[tenor] = float(query_par_rate(wrapped, curve_name=curve, tenor=tenor))
                    except Exception:  # noqa: BLE001
                        vals[tenor] = np.nan
                priced[pos] = vals
            by_stamp = {
                int(pd.Timestamp(stamps.iloc[p]).value // 10**9): v for p, v in priced.items()
            }
            secs = sorted(by_stamp)
            for delta_min in (1, 2, 3, 5, 10, 15, 30, 60, 120, 240):
                d = delta_min * 60
                for s in secs:
                    if (s - d) not in by_stamp:
                        continue
                    a, b = by_stamp[s], by_stamp[s - d]
                    row = {"curve": curve, "local_date": day, "delta_min": delta_min,
                           "t_utc": pd.Timestamp(s, unit="s", tz="UTC")}
                    for tenor in BP_TENORS:
                        row[f"move_bp_{tenor}"] = (
                            abs(a[tenor] - b[tenor]) * 100.0
                            if a[tenor] == a[tenor] and b[tenor] == b[tenor] else np.nan
                        )
                    rows.append(row)
            print(f"    drift {curve} {day}: {len(keep)} snapshots priced", flush=True)

    df = pd.DataFrame(rows)
    _write(df, out / "drift.parquet")
    return df


# --------------------------------------------------------------------------- #
#                                stage: report                                #
# --------------------------------------------------------------------------- #


def _wq(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """Leg-weighted quantile: the tape's own distribution, not the minutes'."""
    ok = ~np.isnan(values)
    v, w = values[ok], weights[ok]
    if len(v) == 0:
        return float("nan")
    order = np.argsort(v)
    v, w = v[order], w[order]
    cw = np.cumsum(w) - 0.5 * w
    cw /= w.sum()
    return float(np.interp(q, cw, v))


#: Lag buckets the report histograms into. The negative bucket is deliberately
#: first and separate: "the curve came from after the trade" is a different kind
#: of wrong from "the curve is old", not a more extreme amount of the same thing.
_LAG_BUCKETS = (
    (-np.inf, 0.0, "future (served after the request)"),
    (0.0, 0.5, "exact minute"),
    (0.5, 60.0, "<= 1 min"),
    (60.0, 120.0, "1-2 min"),
    (120.0, 300.0, "2-5 min"),
    (300.0, 600.0, "5-10 min"),
    (600.0, 1800.0, "10-30 min"),
    (1800.0, 3600.0, "30-60 min"),
    (3600.0, np.inf, "> 1 h"),
)


def _bucketise(values: np.ndarray, weights: np.ndarray) -> Dict[str, float]:
    total = weights.sum()
    out: Dict[str, float] = {}
    for lo, hi, label in _LAG_BUCKETS:
        if label == "exact minute":
            sel = (values >= lo) & (values <= hi)
        elif lo == -np.inf:
            sel = values < hi
        else:
            sel = (values > lo) & (values <= hi)
        out[label] = float(weights[sel & ~np.isnan(values)].sum() / total) if total else np.nan
    return out


def stage_report(
    out: Path,
    lag: pd.DataFrame,
    density: pd.DataFrame,
    bp: pd.DataFrame,
    drift: Optional[pd.DataFrame] = None,
    session: Optional[pd.DataFrame] = None,
) -> Dict:
    summary: Dict = {"generated": datetime.datetime.now(UTC).isoformat(), "by_curve": {}}

    for curve, g in lag.groupby("curve"):
        s = g[g["outcome"] == "served"]
        w = s["n_legs"].to_numpy(dtype=float)
        lc = s["lag_cur_s"].to_numpy(dtype=float)
        lb = s["lag_back_s"].to_numpy(dtype=float)
        tot_legs = float(g["n_legs"].sum())
        entry = {
            "requested_minutes": int(len(g)),
            "legs": int(tot_legs),
            "legs_not_intraday": int(g.loc[g["outcome"] == "not_intraday", "n_legs"].sum()),
            "legs_empty_window": int(g.loc[g["outcome"] == "empty_window", "n_legs"].sum()),
            "legs_served": int(s["n_legs"].sum()),
            "frac_legs_future_served": float(s.loc[lc < 0, "n_legs"].sum() / tot_legs) if tot_legs else np.nan,
            "frac_legs_wrong_calendar_day": float(s.loc[~s["same_day_cur"], "n_legs"].sum() / tot_legs) if tot_legs else np.nan,
            "frac_legs_no_backward": float(s.loc[~s["has_backward"], "n_legs"].sum() / tot_legs) if tot_legs else np.nan,
            "frac_legs_rules_differ": float(s.loc[s["differs"], "n_legs"].sum() / tot_legs) if tot_legs else np.nan,
            "lag_cur_s": {f"p{int(q*100)}": _wq(lc, w, q) for q in (0.5, 0.9, 0.99)},
            "lag_cur_s_max": float(np.nanmax(lc)) if len(lc) else np.nan,
            "lag_cur_s_min": float(np.nanmin(lc)) if len(lc) else np.nan,
            "lag_back_s": {f"p{int(q*100)}": _wq(lb, w, q) for q in (0.5, 0.9, 0.99)},
            "lag_back_s_max": float(np.nanmax(lb)) if len(lb) else np.nan,
        }
        for thresh in (60, 120, 300, 600, 1800, 3600):
            entry[f"frac_legs_lag_back_gt_{thresh}s"] = (
                float(s.loc[lb > thresh, "n_legs"].sum() / tot_legs) if tot_legs else np.nan
            )
        entry["lag_cur_buckets_legs"] = _bucketise(lc, w)
        entry["lag_back_buckets_legs"] = _bucketise(lb, w)

        # Where the failures live: hour of the requested minute (curve-local) and
        # how dense the requested day was. Both are gates the direction work can
        # actually apply, so a finding concentrated in one of them is actionable
        # in a way an overall fraction is not.
        if len(s):
            local_hour = pd.DatetimeIndex(s["snap_utc"]).tz_convert("America/New_York").hour
            fut = s["lag_cur_s"].to_numpy(dtype=float) < 0
            by_hour = {}
            for h in range(24):
                m = local_hour == h
                legs_h = float(s.loc[m, "n_legs"].sum())
                if legs_h == 0:
                    continue
                by_hour[f"{h:02d}"] = {
                    "legs": int(legs_h),
                    "frac_legs": float(legs_h / tot_legs),
                    "frac_future": float(s.loc[m & fut, "n_legs"].sum() / legs_h),
                    "p99_lag_back_s": _wq(
                        s.loc[m, "lag_back_s"].to_numpy(dtype=float),
                        s.loc[m, "n_legs"].to_numpy(dtype=float), 0.99,
                    ),
                }
            entry["by_local_hour"] = by_hour

            dens_bins = [(0, 200), (200, 400), (400, 800), (800, 1000), (1000, 10**9)]
            by_dens = {}
            ns_ = s["n_snapshots"].fillna(0).to_numpy(dtype=float)
            for lo, hi in dens_bins:
                m = (ns_ >= lo) & (ns_ < hi)
                legs_d = float(s.loc[m, "n_legs"].sum())
                if legs_d == 0:
                    continue
                by_dens[f"{lo}-{hi if hi < 10**9 else 'inf'}"] = {
                    "legs": int(legs_d),
                    "frac_legs": float(legs_d / tot_legs),
                    "frac_future": float(s.loc[m & fut, "n_legs"].sum() / legs_d),
                    "frac_lag_back_gt_60s": float(
                        s.loc[m & (s["lag_back_s"] > 60), "n_legs"].sum() / legs_d
                    ),
                    "p99_lag_back_s": _wq(
                        s.loc[m, "lag_back_s"].to_numpy(dtype=float),
                        s.loc[m, "n_legs"].to_numpy(dtype=float), 0.99,
                    ),
                }
            entry["by_day_density"] = by_dens

            # What a strict caller actually gets to keep. Under ``asof`` the
            # future-served cases are gone by construction, so the only question
            # left is how many requests still have a snapshot inside the
            # tolerance - i.e. what the gate costs in legs.
            fitness = {}
            for tol in (60, 120, 300, 600, 1800, 3600):
                keep = s["has_backward"] & (s["lag_back_s"] <= tol)
                fitness[f"asof_within_{tol}s"] = {
                    "frac_legs_priced": float(s.loc[keep, "n_legs"].sum() / tot_legs),
                    "frac_legs_dropped": float(1.0 - s.loc[keep, "n_legs"].sum() / tot_legs),
                }
            # The same, restricted to the hours the feed is actually publishing.
            hours = pd.DatetimeIndex(s["snap_utc"]).tz_convert("America/New_York").hour
            in_session = (hours >= 1) & (hours <= 16)
            legs_session = float(s.loc[in_session, "n_legs"].sum())
            fitness["in_session_01_16_ET"] = {
                "frac_of_all_legs": float(legs_session / tot_legs),
                "frac_future_within": float(
                    s.loc[in_session & (s["lag_cur_s"] < 0), "n_legs"].sum() / legs_session
                ) if legs_session else np.nan,
                "frac_priced_asof_60s": float(
                    s.loc[in_session & s["has_backward"] & (s["lag_back_s"] <= 60),
                          "n_legs"].sum() / legs_session
                ) if legs_session else np.nan,
            }
            entry["fitness"] = fitness

        # Fitness is not uniform over the tape span, and the answer the next
        # session needs is "from when", not an average. Quarters, over ALL
        # outcomes - a quarter with no warmed curve at all is the most important
        # kind of unfit, and it is invisible in a table built from served rows.
        g = g.copy()
        g["quarter"] = pd.PeriodIndex(pd.DatetimeIndex(g["snap_utc"]), freq="Q").astype(str)
        by_q = {}
        for q, qg in g.groupby("quarter"):
            legs_q = float(qg["n_legs"].sum())
            qs = qg[qg["outcome"] == "served"]
            by_q[q] = {
                "legs": int(legs_q),
                "frac_no_curve": float(
                    qg.loc[qg["outcome"] != "served", "n_legs"].sum() / legs_q
                ),
                "frac_exact": float(
                    qs.loc[qs["lag_cur_s"] == 0, "n_legs"].sum() / legs_q
                ),
                "frac_future": float(qs.loc[qs["lag_cur_s"] < 0, "n_legs"].sum() / legs_q),
                "frac_priced_asof_60s": float(
                    qs.loc[qs["has_backward"] & (qs["lag_back_s"] <= 60), "n_legs"].sum() / legs_q
                ),
            }
        entry["by_quarter"] = by_q
        summary["by_curve"][curve] = entry

    if len(bp):
        bpsum = {}
        for tenor in BP_TENORS:
            col = f"diff_bp_{tenor}"
            if col not in bp:
                continue
            v = bp[col].to_numpy(dtype=float)
            v = v[~np.isnan(v)]
            if not len(v):
                continue
            bpsum[tenor] = {
                "n": int(len(v)),
                "mean_abs": float(np.mean(np.abs(v))),
                "p50_abs": float(np.percentile(np.abs(v), 50)),
                "p90_abs": float(np.percentile(np.abs(v), 90)),
                "max_abs": float(np.max(np.abs(v))),
            }
        summary["bp_all_strata"] = bpsum
        summary["bp_by_stratum"] = {
            str(k): {
                t: float(np.nanmean(np.abs(v[f"diff_bp_{t}"]))) for t in BP_TENORS if f"diff_bp_{t}" in v
            }
            for k, v in bp.groupby("stratum")
        }

    if len(density):
        summary["density"] = {
            str(curve): {
                "days": int(len(g)),
                "first": str(g["local_date"].min()),
                "last": str(g["local_date"].max()),
                "days_ge_1000": int((g["n_snapshots"] >= 1000).sum()),
                "days_ge_400": int((g["n_snapshots"] >= 400).sum()),
                "days_lt_200": int((g["n_snapshots"] < 200).sum()),
                "median_max_gap_s": float(g["max_gap_s"].median()),
            }
            for curve, g in density.groupby("curve")
        }

    if drift is not None and len(drift):
        summary["drift_bp_by_elapsed"] = {
            str(curve): {
                str(int(dm)): {
                    "n_pairs": int(len(g)),
                    **{
                        t: {
                            "p50": float(np.nanpercentile(g[f"move_bp_{t}"], 50)),
                            "p90": float(np.nanpercentile(g[f"move_bp_{t}"], 90)),
                            "p99": float(np.nanpercentile(g[f"move_bp_{t}"], 99)),
                            "max": float(np.nanmax(g[f"move_bp_{t}"])),
                        }
                        for t in BP_TENORS
                        if f"move_bp_{t}" in g and g[f"move_bp_{t}"].notna().any()
                    },
                }
                for dm, g in cg.groupby("delta_min")
            }
            for curve, cg in drift.groupby("curve")
        }
        summary["drift_days_sampled"] = {
            str(curve): sorted({str(d) for d in cg["local_date"]})
            for curve, cg in drift.groupby("curve")
        }

    if session is not None and len(session):
        # The question this answers: of the contamination, how much could a
        # better fetch remove, and how much is simply not published?
        sess: Dict = {}
        for curve, g in session.groupby("curve"):
            total = float(g["n_legs"].sum())
            fut_total = float(g.loc[g["lag_cur_s"] < 0, "n_legs"].sum())
            entry = {"legs": int(total), "future_served": int(fut_total), "by_class": {}}
            for klass, gg in g.groupby("klass"):
                n = float(gg["n_legs"].sum())
                fut = float(gg.loc[gg["lag_cur_s"] < 0, "n_legs"].sum())
                entry["by_class"][str(klass)] = {
                    "legs": int(n),
                    "frac_legs": n / total if total else np.nan,
                    "future_served": int(fut),
                    "frac_of_all_future_served": fut / fut_total if fut_total else np.nan,
                }
            recoverable = g[g["klass"].isin(
                ("in_session_outside_stored_span", "in_session_interior_gap", "no_stored_day")
            )]
            rec_fut = float(recoverable.loc[recoverable["lag_cur_s"] < 0, "n_legs"].sum())
            entry["recoverable_by_fetching"] = {
                "legs": int(recoverable["n_legs"].sum()),
                "frac_legs": float(recoverable["n_legs"].sum() / total) if total else np.nan,
                "future_served": int(rec_fut),
                "frac_of_all_future_served": rec_fut / fut_total if fut_total else np.nan,
            }
            sess[str(curve)] = entry
        summary["session_split"] = sess

    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return summary


# --------------------------------------------------------------------------- #


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        path.write_bytes(b"")
        print(f"  (empty) {path}", flush=True)
        return
    df.to_parquet(path, index=False)
    print(f"  wrote {len(df):,} rows -> {path}", flush=True)


#: Columns that are logically boolean but round-trip through parquet as object
#: dtype, because the non-``served`` rows carry no value for them. ``~col`` on an
#: object column silently produces integers (``~True -> -2``) instead of raising,
#: so they are coerced once on read rather than at each use site.
_BOOL_COLS = ("day_present", "same_day_cur", "has_backward", "differs")


def _read(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    df = pd.read_parquet(path)
    for col in _BOOL_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)
    return df


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "stage",
        choices=["demand", "density", "lag", "verify", "bp", "drift", "session",
                 "report", "all"],
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2024-03-01")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--bp-n", type=int, default=300)
    ap.add_argument("--verify-n", type=int, default=24)
    ap.add_argument("--drift-days", type=int, default=12)
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stage = args.stage
    curves = list(CURVE_FOR_INDEX.values())

    if stage in ("demand", "all"):
        stage_demand(out, args.start, args.end)
    if stage in ("density", "all"):
        stage_density(out, curves)
    if stage in ("lag", "all"):
        stage_lag(out, _read(out / "demand.parquet"), _read(out / "density.parquet"))
    if stage in ("verify", "all"):
        stage_verify(out, _read(out / "lag.parquet"), n=args.verify_n)
    if stage in ("bp", "all"):
        stage_bp(out, _read(out / "lag.parquet"), n=args.bp_n)
    if stage in ("drift", "all"):
        stage_drift(out, _read(out / "density.parquet"), _read(out / "lag.parquet"),
                    n_days=args.drift_days)
    if stage in ("session", "all"):
        stage_session(out, _read(out / "lag.parquet"))
    if stage in ("report", "all"):
        stage_report(out, _read(out / "lag.parquet"), _read(out / "density.parquet"),
                     _read(out / "bp.parquet"), _read(out / "drift.parquet"),
                     _read(out / "session_split.parquet"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
