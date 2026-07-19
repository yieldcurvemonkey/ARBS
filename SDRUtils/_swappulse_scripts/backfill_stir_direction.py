"""Backfill STIR dealer-direction classifications + tick-size calibration.

POC (spec 2026-07-12): classify --classify-date; calibrate ticks over
[--calib-start, --calib-end]. Writes ONLY arbs_stir_direction_v1 /
arbs_stir_tick_size_v1.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values as _execute_values

from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import (
    DIRECTION_TABLE, TICK_TABLE, ensure_schema,
)
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow import config, tick_size
from SDRUtils.stir_flow.classifier import classify_unit
from SDRUtils.stir_flow.curve_warm import (
    enumerate_curve_demand, unit_curve_and_snap, warm_pricer,
)
from SDRUtils.stir_flow.confidence import (
    TickStats, apply_tick_rule, score_off_market, score_on_market,
)
from SDRUtils.stir_flow.pricing import CurvePricer
from SDRUtils.stir_flow.trade_selection import (
    ALL_PKG_LEGS_SQL, ELIGIBLE_LEGS_SQL, build_units, is_excluded_unit,
)

DIRECTION_COLUMNS = [
    "unit_key", "trade_id", "package_id", "as_of_date", "execution_timestamp",
    "trade_type", "rate_index_clean", "curve_name", "curve_timestamp",
    "is_off_market", "classification_method", "curve_mid", "curve_mid_spread_bps",
    "fixed_rate", "traded_spread_bps", "spread_to_mid_bps", "repriced_npv",
    "repriced_pv01", "reported_opa", "reported_ptp", "dealer_direction",
    "dealer_bought", "direction_confidence", "p_flip", "dealer_charge",
    "dealer_charge_bps", "structure_dv01", "notional", "dv01", "tenor_query",
    "tenor_bucket", "dv01_bucket", "curve_suspect_trade", "quality_flags",
]
EMPTY_DIRECTION_ROW = {c: None for c in DIRECTION_COLUMNS}


def _unit_meta(unit):
    first = unit.legs.iloc[0]
    curve_name, snap = unit_curve_and_snap(unit)   # single source of truth
    bucket = tick_size.tenor_bucket_for(first)
    total_dv01 = float(unit.legs["risk"].abs().sum())
    return first, curve_name, snap, bucket, total_dv01


def classify_units(units, pricer, tick_lookup, prev_rate_lookup):
    rows = []
    for unit in units:
        first, curve_name, snap, bucket, total_dv01 = _unit_meta(unit)
        row = dict(EMPTY_DIRECTION_ROW)
        row.update(
            unit_key=unit.unit_key,
            trade_id=first["trade_id"] if unit.kind == "OUTRIGHT" else None,
            package_id=unit.package_id,
            as_of_date=first["as_of_date"],
            execution_timestamp=first["execution_timestamp"],
            trade_type=unit.kind,
            rate_index_clean=first["rate_index_clean"],
            curve_name=curve_name,
            curve_timestamp=snap,
            is_off_market=unit.is_off_market,
            dealer_direction="UNKNOWN",
            fixed_rate=float(first["fixed_rate"]) if unit.kind == "OUTRIGHT" else None,
            notional=float(unit.legs["notional"].sum()),
            dv01=total_dv01,
            tenor_bucket=bucket,
            dv01_bucket=config.assign_dv01_bucket(total_dv01),
            tenor_query=f"{first['effective_date']}->{unit.legs.iloc[-1]['expiration_date']}",
            quality_flags=[],
        )
        try:
            pricings = []
            for _, leg in unit.legs.iterrows():
                fixed = float(leg["fixed_rate"]) if unit.is_off_market else None
                pricings.append(pricer.price_leg(
                    curve_name, snap, leg["effective_date"], leg["expiration_date"],
                    notional=float(leg["notional"]), fixed_rate=fixed,
                ))
            res = classify_unit(unit, pricings)
            for f in ("classification_method", "dealer_direction", "dealer_bought",
                      "curve_mid", "curve_mid_spread_bps", "traded_spread_bps",
                      "spread_to_mid_bps", "repriced_npv", "repriced_pv01",
                      "reported_opa", "reported_ptp", "dealer_charge",
                      "dealer_charge_bps", "structure_dv01"):
                row[f] = getattr(res, f)
            row["quality_flags"] = list(res.quality_flags)

            stats = tick_lookup(bucket, unit.kind, row["dv01_bucket"]) or TickStats(
                None, None, config.futures_tick_bps(
                    first["rate_index_clean"], first["special_tenor_type"]))
            if res.dealer_direction != "UNKNOWN":
                if unit.is_off_market:
                    dec = score_off_market(res.dealer_charge_bps, stats)
                else:
                    dec = score_on_market(res.spread_to_mid_bps,
                                          stats, bool(first.get("is_block")))
                    if dec.use_tick_rule:
                        prev = prev_rate_lookup(bucket, unit.kind,
                                                first["execution_timestamp"])
                        tr = apply_tick_rule(float(first["fixed_rate"]) * 100.0, prev)
                        if tr is not None:
                            row["dealer_direction"] = tr
                            row["classification_method"] = "TICK_RULE"
                row["direction_confidence"] = dec.confidence
                row["p_flip"] = dec.p_flip
                row["curve_suspect_trade"] = dec.curve_suspect_trade
        except Exception as exc:  # noqa: BLE001 - per-unit isolation by design
            row["quality_flags"] = list(row["quality_flags"]) + [f"PRICING_ERROR:{exc}"]
        rows.append(row)
    return rows


def write_direction_rows(conn, rows):
    if not rows:
        return
    cols = DIRECTION_COLUMNS
    sql = (
        f"INSERT INTO {DIRECTION_TABLE} ({', '.join(cols)}) VALUES %s "
        f"ON CONFLICT (unit_key) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "unit_key")
    )
    values = [tuple(_sanitize(r.get(c)) for c in cols) for r in rows]
    with conn.cursor() as cur:
        _execute_values(cur, sql, values)
    conn.commit()


TICK_COLUMNS = [
    "tenor_bucket", "structure_type", "dv01_bucket", "as_of_date",
    "futures_min_tick_bps", "mean_tick_bps", "median_tick_bps", "p25_tick_bps",
    "p75_tick_bps", "tick_sample_count", "mean_dealer_charge_bps",
    "median_dealer_charge_bps", "edge_sample_count", "disp_vw", "disp_jns",
    "curve_suspect", "amihud", "total_dv01_traded", "trade_count", "window_days",
]


def _sanitize(val):
    if val is None:
        return None
    if isinstance(val, float) and val != val:
        return None
    try:
        import numpy as np
        if isinstance(val, (np.floating, np.bool_)):
            return None if np.isnan(val) else val.item()
        if isinstance(val, np.integer):
            return val.item()
    except (TypeError, ValueError):
        pass
    return val


def write_tick_rows(conn, stats_df):
    if stats_df is None or stats_df.empty:
        return
    df = stats_df.copy()
    for c in TICK_COLUMNS:
        if c not in df:
            df[c] = None
    df = df[TICK_COLUMNS]
    sql = (
        f"INSERT INTO {TICK_TABLE} ({', '.join(TICK_COLUMNS)}) VALUES %s "
        f"ON CONFLICT (tenor_bucket, structure_type, dv01_bucket, as_of_date) "
        f"DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in TICK_COLUMNS
                    if c not in ("tenor_bucket", "structure_type",
                                 "dv01_bucket", "as_of_date"))
    )
    rows = [tuple(_sanitize(v) for v in r) for r in df.itertuples(index=False)]
    with conn.cursor() as cur:
        _execute_values(cur, sql, rows)
    conn.commit()


def _load_frames(conn, start, end):
    eligible = pd.read_sql(ELIGIBLE_LEGS_SQL, conn, params={"start": start, "end": end})
    pkg_ids = sorted(set(eligible.loc[eligible["n_package_legs"].fillna(1) > 1,
                                      "package_id"].dropna()))
    all_legs = eligible.head(0)
    if pkg_ids:
        all_legs = pd.read_sql(ALL_PKG_LEGS_SQL, conn,
                               params={"package_ids": pkg_ids})
    return eligible, all_legs


def _onmarket_prints(eligible):
    df = eligible.copy()
    df["off"] = (df["other_payment_ufro"].fillna(0).abs() > 0) | (
        df["pkg_ptp"].abs() > config.PTP_USD_FLOOR)
    on = df[~df["off"] & (df["n_package_legs"].fillna(1) <= 1)].copy()
    on["tenor_bucket"] = on.apply(tick_size.tenor_bucket_for, axis=1)
    on["structure_type"] = "OUTRIGHT"
    on["rate_pct"] = on["fixed_rate"].astype(float) * 100.0
    on["dv01"] = on["risk"].abs()
    return on[on["tenor_bucket"] != "UNMAPPED"]


def run_calibration(conn, start, end, mode):
    eligible, _ = _load_frames(conn, start, end)
    prints = _onmarket_prints(eligible)
    pairs = tick_size.build_tick_pairs(prints)
    prints["s2m_bps"] = float("nan")   # ticks-only: no mids
    disp = tick_size.compute_dispersion(prints)
    daily = disp[["tenor_bucket", "structure_type", "as_of_date",
                  "vwap_rate_pct", "total_dv01"]]
    amih = tick_size.compute_amihud(daily)
    offmkt = pd.DataFrame(columns=["tenor_bucket", "structure_type", "dv01_bucket",
                                   "as_of_date", "dealer_charge_bps"])
    if mode == "full":
        raise NotImplementedError(
            "full calibration mode is a follow-up; POC uses ticks-only + "
            "07/10 classification-day dispersion")
    stats = tick_size.compute_bucket_stats(pairs, prints, offmkt)
    stats = stats.merge(
        disp[["tenor_bucket", "structure_type", "as_of_date",
              "disp_vw", "disp_jns", "curve_suspect", "trade_count", "total_dv01"]]
        .rename(columns={"total_dv01": "total_dv01_traded"}),
        on=["tenor_bucket", "structure_type", "as_of_date"], how="left")
    stats = stats.merge(
        amih[["tenor_bucket", "structure_type", "as_of_date", "amihud"]],
        on=["tenor_bucket", "structure_type", "as_of_date"], how="left")
    stats["window_days"] = (pd.Timestamp(end) - pd.Timestamp(start)).days
    return stats


def _build_lookups(stats):
    med = {}
    if stats is not None and len(stats):
        for _, r in stats.iterrows():
            med[(r["tenor_bucket"], r["structure_type"], r["dv01_bucket"])] = r.to_dict()

    def tick_lookup(bucket, kind, dv01_bucket):
        r = med.get((bucket, kind, dv01_bucket))
        if r is None:
            r = med.get((bucket, kind, "ALL"))
        if r is None:
            return None
        ftb = r.get("futures_min_tick_bps")
        if ftb is None or (isinstance(ftb, float) and ftb != ftb):
            ftb = 0.25
        return TickStats(
            median_tick_bps=r.get("median_tick_bps"),
            disp_jns=r.get("disp_jns"),
            futures_tick_bps=float(ftb),
        )
    return tick_lookup


def _build_prev_rate_lookup(prints):
    idx = {}
    for key, g in prints.groupby(["tenor_bucket", "structure_type"]):
        g = g.sort_values("execution_timestamp")
        idx[key] = list(zip(g["execution_timestamp"], g["rate_pct"]))

    def prev_rate_lookup(bucket, kind, ts):
        series = idx.get((bucket, kind), [])
        prev = None
        for t, r in series:
            if t >= ts:
                break
            prev = r
        return prev
    return prev_rate_lookup


def run_classification(conn, classify_date, stats, limit=0, dry_run=False,
                       warm_jobs=8, warm=True):
    eligible, all_legs = _load_frames(conn, classify_date, classify_date)
    units, skipped = [], []
    for u in build_units(eligible, all_legs):
        reason = is_excluded_unit(u.legs)
        (skipped if reason else units).append((u, reason) if reason else u)
    if limit:
        units = units[:limit]
    prints = _onmarket_prints(eligible)
    pricer = CurvePricer()
    if warm and units:
        # Decouple curve acquisition: build every needed (curve, minute) snapshot
        # concurrently up front so classify_units prices against a warm handle
        # cache instead of building curves lazily one leg at a time.
        demand = enumerate_curve_demand(units)
        wr = warm_pricer(pricer, demand, max_workers=warm_jobs)
        print(f"warmed curves: built={wr['built']} reused={wr['reused']} "
              f"failed={wr['failed']} (demand={len(demand)})")
    rows = classify_units(units, pricer,
                          _build_lookups(stats), _build_prev_rate_lookup(prints))
    print(f"classified {len(rows)} units; skipped {len(skipped)} "
          f"({pd.Series([r for _, r in skipped]).value_counts().to_dict() if skipped else {}})")
    if not dry_run:
        write_direction_rows(conn, rows)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg-url", default=None)
    ap.add_argument("--classify-date", required=True)
    ap.add_argument("--calib-start", required=True)
    ap.add_argument("--calib-end", required=True)
    ap.add_argument("--calib-mode", choices=["ticks-only", "full"], default="ticks-only")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--warm-jobs", type=int, default=8,
                    help="thread pool size for concurrent curve warming")
    ap.add_argument("--no-warm", action="store_true",
                    help="disable curve pre-warming (legacy lazy per-leg path)")
    args = ap.parse_args()

    conn = psycopg2.connect(resolve_pg_url(args.pg_url))
    ensure_schema(conn)
    stats = run_calibration(conn, args.calib_start, args.calib_end, args.calib_mode)
    if not args.dry_run:
        write_tick_rows(conn, stats)
    print(f"tick stats rows: {len(stats)}")
    rows = run_classification(conn, args.classify_date, stats,
                              limit=args.limit, dry_run=args.dry_run,
                              warm_jobs=args.warm_jobs, warm=not args.no_warm)
    summary = pd.DataFrame(rows)["dealer_direction"].value_counts().to_dict()
    print(f"direction summary: {json.dumps(summary)}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
