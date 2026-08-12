"""Tie-out sweep driver: OLD stir_flow vs NEW dealer_direction, per day.

LEDGER D11 decomposes the tie-out into two measurements that each vary ONE
thing. This script produces the raw material for both, and nothing else -- all
metric work happens offline in ``tieout_analyse.py`` off the parquet this
writes, so a metric can be recomputed without repricing anything.

Per classification day it writes three frames to ``--out``:

``old/<date>.parquet``       a FRESH dry-run of the frozen pipeline. Not the
                             persisted table (LEDGER T-3: those rows came off
                             the _v2 tape and rateslib 2.1.1).
``new_bar/<date>.parquet``   the NEW package on the SAME curve
                             (``BARCHART_STIRF-RL``), the SAME unit set, and
                             the SAME snapshot instants -- the logic tie-out.
``new_citi/<date>.parquet``  the NEW package on the citivelo minute curve,
                             same units, same instants -- the curve effect.

WHAT IS HELD CONSTANT, AND HOW
------------------------------
* **The unit set.** Units come from ``stir_flow.trade_selection.build_units``
  filtered by ``is_excluded_unit``, then are *wrapped* into
  ``dealer_direction.types.Unit``. The new package's own universe module is not
  consulted: the join key must be the old system's unit definition or the
  comparison is against a different population.
* **The upfront routing.** ``Unit.upfront`` is set from the OLD
  ``trade_selection.resolve_upfront``, so ``want_npv`` in the new repricer fires
  on exactly the units the old classifier called off-market. New-native upfront
  resolution is deliberately out of scope for the logic tie-out.
* **The instant.** ``stir_flow.pricing.snap_timestamp`` (the old rule) is passed
  explicitly to ``price_unit(instant=...)``, and asserted equal to what the new
  ``snapshot.snap_instant`` would produce from the clock we hand it.
* **The curve object.** The new Barchart pricer's handle cache is seeded from
  the old pricer's, so both systems price against the *same* ``rl.Curve``
  instances, not merely against curves built on the same terms.
* **is_lifecycle=False everywhere.** The old system has no lifecycle concept;
  ``upfront.classify(is_lifecycle=True)`` negates orientation, so letting the
  new side detect lifecycle rows would manufacture inversions that are a scope
  difference, not a logic difference.

Resumability: a day is skipped when every requested output already exists.
Writes are tmp+rename so a killed run cannot leave a half-file that reads done.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import traceback

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.backfill_stir_direction import (  # noqa: E402
    _build_lookups, _build_prev_rate_lookup, _load_frames, _onmarket_prints,
    classify_units, run_calibration,
)
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402
from SDRUtils.dealer_direction import conventions as conv  # noqa: E402
from SDRUtils.dealer_direction import midprice, probability, snapshot, upfront as uf  # noqa: E402
from SDRUtils.dealer_direction import types as T  # noqa: E402
from SDRUtils.stir_flow import config as legacy_config  # noqa: E402
from SDRUtils.stir_flow import tick_size  # noqa: E402
from SDRUtils.stir_flow.curve_warm import (  # noqa: E402
    enumerate_curve_demand, unit_curve_and_snap, warm_pricer,
)
from SDRUtils.stir_flow.pricing import CurvePricer, snap_timestamp  # noqa: E402
from SDRUtils.stir_flow.trade_selection import (  # noqa: E402
    build_units, is_excluded_unit, resolve_upfront,
)

# The production chunking: calibration window ends the day BEFORE the chunk, so
# a day's tick stats never see its own future. Verbatim from
# scripts/backfill_dealer_ladder_window.sh.
CHUNKS = [
    ("2026-01-12", "2026-01-31", "2025-12-12", "2026-01-11"),
    ("2026-02-01", "2026-02-28", "2026-01-01", "2026-01-31"),
    ("2026-03-01", "2026-03-31", "2026-02-01", "2026-02-28"),
    ("2026-04-01", "2026-04-30", "2026-03-01", "2026-03-31"),
    ("2026-05-01", "2026-05-31", "2026-04-01", "2026-04-30"),
    ("2026-06-01", "2026-06-30", "2026-05-01", "2026-05-31"),
    ("2026-07-01", "2026-07-29", "2026-06-01", "2026-06-30"),
]


def chunk_for(day: datetime.date):
    for cs, ce, ks, ke in CHUNKS:
        if pd.Timestamp(cs).date() <= day <= pd.Timestamp(ce).date():
            return ks, ke
    raise ValueError(f"{day} is outside the chunked window")


# --------------------------------------------------------------------------
# unit wrapping
# --------------------------------------------------------------------------

def _tenor_years(legs) -> float:
    eff = pd.Timestamp(legs.iloc[0]["effective_date"])
    exp = pd.Timestamp(legs.iloc[-1]["expiration_date"])
    return (exp - eff).days / 365.25


def wrap_unit(old_unit) -> tuple:
    """``(types.Unit, snap)`` from a frozen-pipeline unit. Nothing is inferred."""
    first = old_unit.legs.iloc[0]
    snap = snap_timestamp(first.get("original_execution_timestamp"),
                          first["execution_timestamp"])
    # The clock we hand the Unit is the SAME field the old rule reads, so
    # snapshot.snap_instant(clocks.pricing) reproduces snap_timestamp exactly.
    raw = first.get("original_execution_timestamp")
    if raw is None or pd.isna(raw):
        raw = first["execution_timestamp"]
    raw = pd.Timestamp(raw)
    upfront_amt, upfront_src, _ = resolve_upfront(
        first.get("pkg_ptp"), list(old_unit.legs["other_payment_ufro"].fillna(0.0)))
    clocks = T.Clocks(pricing=raw, execution=pd.Timestamp(first["execution_timestamp"]),
                      event=raw, visibility=raw, visibility_source="TIEOUT_NA")
    u = T.Unit(
        unit_key=old_unit.unit_key,
        kind=old_unit.kind,
        legs=old_unit.legs,
        package_id=old_unit.package_id,
        rate_index=first["rate_index_clean"],
        as_of_date=pd.Timestamp(first["as_of_date"]).date(),
        venue_class=T.VENUE_D2C,
        clocks=clocks,
        upfront=upfront_amt,
        upfront_source=upfront_src,
        is_lifecycle=False,
        is_block=bool(first.get("is_block") or False),
        is_capped=bool(first.get("is_capped") or False),
    )
    return u, snap


# --------------------------------------------------------------------------
# the new-side pass
# --------------------------------------------------------------------------

def new_rows(units_wrapped, repricer, tag: str) -> list:
    out = []
    for old_unit, u, snap in units_wrapped:
        row = {
            "unit_key": u.unit_key, "kind": u.kind, "n_legs": len(u.legs),
            "rate_index": u.rate_index, "as_of_date": u.as_of_date,
            "snap": pd.Timestamp(snap), "source_tag": tag,
            "is_off_market_old": old_unit.is_off_market,
            "upfront": u.upfront, "upfront_source": u.upfront_source,
            "special_tenor_type": (u.legs.iloc[0].get("special_tenor_type") or "STANDARD"),
            "tenor_years": _tenor_years(u.legs),
            "is_block": u.is_block, "is_capped": u.is_capped,
        }
        row["tenor_band"] = probability.tenor_band(row["tenor_years"])
        try:
            rp = repricer.price_unit(u, instant=snap)
        except Exception as exc:  # noqa: BLE001 - per-unit isolation, as the old one
            row.update(failure="DRIVER_EXCEPTION",
                       failure_detail=f"{type(exc).__name__}: {str(exc)[:300]}")
            out.append(row)
            continue
        pr = rp.pricing
        row.update(
            curve_name=pr.curve_name,
            curve_timestamp=pr.curve_timestamp,
            snapshot_lag_seconds=pr.snapshot_lag_seconds,
            snapshot_policy=pr.snapshot_policy,
            leg_mid_pct=json.dumps([None if m is None else float(m)
                                    for m in pr.leg_mid_pct]),
            leg_pv01=json.dumps([None if p is None else float(p)
                                 for p in pr.leg_pv01]),
            npv_pay=pr.npv_pay, structure_dv01=pr.structure_dv01,
            failure=rp.failure, failure_detail=rp.failure_detail,
            flags=json.dumps(list(rp.flags)),
        )
        if rp.failure is not None:
            out.append(row)
            continue

        if u.upfront is None:
            # rate rule
            traded = [float(r) * 100.0 for r in u.legs["fixed_rate"]]
            mids = [float(m) for m in pr.leg_mid_pct]
            try:
                dev = (conv.structure_price(traded, u.kind, len(traded), conv.RULE_RATE)
                       - conv.structure_price(mids, u.kind, len(mids), conv.RULE_RATE))
            except conv.UnorientableUnit as exc:
                row.update(rule=conv.RULE_RATE, exclusion=T.EXCL_UNORIENTABLE,
                           failure_detail=str(exc)[:200])
                out.append(row)
                continue
            row.update(rule=conv.RULE_RATE, deviation_bps=dev,
                       dealer_sign=conv.dealer_side(dev))
        else:
            call = uf.classify(npv_pay=pr.npv_pay, upfront=u.upfront,
                               structure_dv01=pr.structure_dv01,
                               upfront_source=u.upfront_source,
                               is_lifecycle=False, is_capped=u.is_capped)
            row.update(rule=conv.RULE_UPFRONT, deviation_bps=call.edge_bps,
                       dealer_sign=call.dealer_sign, exclusion=call.exclusion,
                       uf_dev_bps=call.dev_bps, uf_upfront_bps=call.upfront_bps,
                       uf_residual_bps=call.residual_bps,
                       uf_flags=json.dumps(list(call.flags)))
        out.append(row)
    return out


# --------------------------------------------------------------------------
# per-day
# --------------------------------------------------------------------------

def _atomic_parquet(df: pd.DataFrame, path: str) -> None:
    # PID-unique tmp: several shards may be writing the same calibration file.
    tmp = f"{path}.{os.getpid()}.tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _obj(df: pd.DataFrame) -> pd.DataFrame:
    """Parquet-safe: list/dict columns -> json, everything else left alone."""
    out = df.copy()
    for c in out.columns:
        if out[c].map(lambda v: isinstance(v, (list, dict, tuple))).any():
            out[c] = out[c].map(lambda v: json.dumps(list(v))
                                if isinstance(v, (list, tuple)) else
                                (json.dumps(v) if isinstance(v, dict) else v))
    return out


def calib_stats(conn, ks: str, ke: str, out_root: str):
    path = os.path.join(out_root, "calib", f"{ks}_{ke}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    t0 = time.time()
    stats = run_calibration(conn, ks, ke, "ticks-only")
    print(f"  calibration {ks}..{ke}: {len(stats)} rows in {time.time() - t0:.1f}s",
          flush=True)
    _atomic_parquet(_obj(stats), path)
    return stats


def run_day(conn, day: datetime.date, out_root: str, sources: set, warm_jobs: int):
    ds = day.isoformat()
    paths = {
        "old": os.path.join(out_root, "old", f"{ds}.parquet"),
        "bar": os.path.join(out_root, "new_bar", f"{ds}.parquet"),
        "citi": os.path.join(out_root, "new_citi", f"{ds}.parquet"),
    }
    want = {"old"} | sources
    if all(os.path.exists(paths[k]) for k in want):
        print(f"{ds}: already done", flush=True)
        return "skip"

    t0 = time.time()
    ks, ke = chunk_for(day)
    stats = calib_stats(conn, ks, ke, out_root)

    eligible, all_legs = _load_frames(conn, ds, ds)
    if eligible.empty:
        for k in want:
            _atomic_parquet(pd.DataFrame({"unit_key": pd.Series(dtype=str)}), paths[k])
        print(f"{ds}: no eligible legs -> empty", flush=True)
        return "empty"

    units, skipped = [], []
    for u in build_units(eligible, all_legs):
        reason = is_excluded_unit(u.legs)
        (skipped if reason else units).append((u, reason) if reason else u)
    prints = _onmarket_prints(eligible)

    pricer = CurvePricer()
    if units:
        demand = enumerate_curve_demand(units)
        wr = warm_pricer(pricer, demand, max_workers=warm_jobs)
        print(f"{ds}: {len(units)} units, warm built={wr['built']} "
              f"reused={wr['reused']} bulk={wr['bulk_seeded']} failed={wr['failed']} "
              f"(demand={len(demand)}) {time.time() - t0:.1f}s", flush=True)

    # --- OLD ---------------------------------------------------------------
    t1 = time.time()
    rows = classify_units(units, pricer, _build_lookups(stats),
                          _build_prev_rate_lookup(prints))
    old_df = pd.DataFrame(rows)
    # carry the per-unit tick the knife-edge stratum needs, computed the way the
    # frozen pipeline computes it (config.futures_tick_bps + bucket median)
    tk = []
    for u in units:
        first = u.legs.iloc[0]
        b = tick_size.tenor_bucket_for(first)
        st = _build_lookups(stats)(b, u.kind, legacy_config.assign_dv01_bucket(
            float(u.legs["risk"].abs().sum())))
        ftb = legacy_config.futures_tick_bps(first["rate_index_clean"],
                                             first["special_tenor_type"])
        tk.append({"unit_key": u.unit_key, "futures_tick_bps": ftb,
                   "bucket_median_tick_bps": (getattr(st, "median_tick_bps", None)
                                              if st is not None else None),
                   "kind": u.kind, "is_block": bool(first.get("is_block") or False),
                   "is_capped": bool(first.get("is_capped") or False),
                   "special_tenor_type": first.get("special_tenor_type")})
    old_df = old_df.merge(pd.DataFrame(tk), on="unit_key", how="left",
                          suffixes=("", "_tk"))
    old_df["n_skipped"] = len(skipped)
    _atomic_parquet(_obj(old_df), paths["old"])
    t_old = time.time() - t1

    wrapped = []
    for u in units:
        wu, snap = wrap_unit(u)
        assert snapshot.snap_instant(wu.clocks.pricing) == snap, (
            f"{u.unit_key}: new snap_instant != old snap_timestamp")
        wrapped.append((u, wu, snap))

    # --- NEW on the SAME curve --------------------------------------------
    t_bar = t_citi = 0.0
    if "bar" in sources:
        t1 = time.time()
        sbp = midprice.SessionBranchPricer(source=snapshot.LEGACY_CURVE_SOURCE,
                                           mdp=pricer._mdp)
        legacy_pricer = sbp.pricer_for(midprice.POLICY_NONE)
        assert legacy_pricer.curve_kwargs == pricer.curve_kwargs, "terms differ"
        before = len(pricer._handles)
        legacy_pricer._handles.update(pricer._handles)   # the SAME curve objects
        rp = midprice.UnitRepricer(sbp, require_lag_telemetry=False)
        bar_df = pd.DataFrame(new_rows(wrapped, rp, "BARCHART"))
        after_new = len(legacy_pricer._handles)
        bar_df["seeded_handles"] = before
        bar_df["handles_after"] = after_new
        _atomic_parquet(_obj(bar_df), paths["bar"])
        t_bar = time.time() - t1
        if after_new > before:
            print(f"{ds}: WARNING new-bar built {after_new - before} extra handles",
                  flush=True)

    # --- NEW on the citivelo minute curve ---------------------------------
    if "citi" in sources:
        t1 = time.time()
        sbp2 = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
        rp2 = midprice.UnitRepricer(sbp2, require_lag_telemetry=False)
        with rp2.day_scope():
            citi_df = pd.DataFrame(new_rows(wrapped, rp2, "CITIVELO"))
        _atomic_parquet(_obj(citi_df), paths["citi"])
        t_citi = time.time() - t1

    pricer._handles.clear()
    print(f"{ds}: done units={len(units)} skipped={len(skipped)} "
          f"old={t_old:.1f}s bar={t_bar:.1f}s citi={t_citi:.1f}s "
          f"total={time.time() - t0:.1f}s", flush=True)
    return "ok"


def _free_gb(path: str = "C:\\") -> float:
    import shutil

    return shutil.disk_usage(path).free / 1e9


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=r"D:\tieout_cache")
    ap.add_argument("--sources", default="bar",
                    help="comma list of bar,citi (old is always produced)")
    ap.add_argument("--warm-jobs", type=int, default=8)
    ap.add_argument("--every", type=int, default=1, help="stride over business days")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--deadline-seconds", type=float, default=0.0,
                    help="stop launching new days after this much wall clock")
    ap.add_argument("--min-free-gb", type=float, default=1.0,
                    help="abort before a day if C: free space is below this")
    args = ap.parse_args()

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    for sub in ("old", "new_bar", "new_citi", "calib", "logs"):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)

    days = [d.date() for d in pd.bdate_range(args.start, args.end)][::args.every]
    days = days[args.shard::args.nshards]
    t_start = time.time()
    conn = psycopg2.connect(resolve_pg_url(None))
    conn.set_session(readonly=True)      # belt and braces: the tape DB is PROD
    rc = 0
    for day in days:
        if args.deadline_seconds and time.time() - t_start > args.deadline_seconds:
            print(f"[shard {args.shard}] deadline reached, stopping cleanly", flush=True)
            break
        free = _free_gb()
        if free < args.min_free_gb:
            print(f"[shard {args.shard}] ABORT: C: free {free:.2f} GB < "
                  f"{args.min_free_gb} GB floor", flush=True)
            rc = 2
            break
        try:
            run_day(conn, day, args.out, sources, args.warm_jobs)
        except Exception:  # noqa: BLE001
            rc = 1
            print(f"{day}: FAILED\n{traceback.format_exc()}", flush=True)
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                conn.close()
                conn = psycopg2.connect(resolve_pg_url(None))
                conn.set_session(readonly=True)
    conn.close()
    print(f"SWEEP DONE shard={args.shard} rc={rc} free={_free_gb():.2f}GB", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
