"""Stage 6 - the bias the whole design rests on: (printed rate - mid) in bp.

Direction is inferred from the SIGN of this quantity: printed above mid means the
dealer received fixed. So a systematic non-zero median does not degrade the call,
it INVERTS a share of it - if the median sat at, say, +0.3 bp, then every print
between 0 and +0.3 bp would be labelled "dealer received" when the balanced
reading is the opposite. Dispersion is survivable; a median offset is not.

Sample: on-market SOFR OUTRIGHTs, new risk, inside Citi's published session,
priced under ``SnapshotPolicy.strict(minutes=1)`` so no curve postdates its own
print. Drawn deterministically by ``hashtext(trade_id) mod N`` across the whole
v3 span rather than ``ORDER BY random()``, which is neither reproducible nor
guaranteed to give a stable row order.

Three cuts, because a single median cannot distinguish the explanations:

  * by TENOR - a day-count / roll / spot-lag convention error grows with tenor;
    a mid that is simply mis-timed does not.
  * by VENUE - D2C prints should straddle mid roughly evenly if the population
    is balanced; a D2C-only skew is a market fact, not a pricing bug.
  * against a MINUS-ONE-MINUTE control curve. If the median moves with the
    curve's timestamp it is a timing artefact; if it does not, it is convention.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import psycopg2

from dd_common import CURVE_FOR, curve_meta, make_pricer, strict_policy
from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import publishes
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow import config
from SDRUtils.stir_flow.pricing import snap_timestamp

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)

TARGET = 200
CURVE = "USD-SOFR-1D"


def draw(conn) -> pd.DataFrame:
    sql = f"""
      SELECT trade_id, as_of_date, execution_timestamp, original_execution_timestamp,
             effective_date, expiration_date, notional, fixed_rate, tenor_years,
             tenor_label, platform_identifier, venue, is_block, is_off_date
      FROM {LEGS_TABLE}
      WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
        AND rate_index_clean = 'SOFR'
        AND coalesce(trade_type,'') = 'OUTRIGHT'
        AND NOT is_off_market AND NOT is_mac AND NOT is_spreadover
        AND NOT is_asset_swap AND NOT coalesce(is_unwind,false)
        AND coalesce(is_new_risk, true)
        AND fixed_rate IS NOT NULL AND effective_date IS NOT NULL
        AND expiration_date IS NOT NULL AND notional IS NOT NULL
        AND tenor_years BETWEEN 0.5 AND 31
        AND mod(abs(hashtext(trade_id)), 1999) = 7
      ORDER BY execution_timestamp
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def main() -> None:
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    conn = psycopg2.connect(resolve_pg_url())
    pool = draw(conn)
    conn.close()
    print(f"hash-drawn pool: {len(pool)} on-market SOFR outrights, "
          f"{pool['as_of_date'].min()} .. {pool['as_of_date'].max()}")

    pool["snap"] = pd.to_datetime(pd.Series([
        snap_timestamp(a, b) for a, b in
        zip(pool["original_execution_timestamp"], pool["execution_timestamp"])
    ]), utc=True).dt.tz_convert("America/New_York")
    pool["publishes"] = [publishes(CURVE, t) for t in pool["snap"]]
    ins = pool[pool["publishes"]].reset_index(drop=True)
    print(f"in Citi's published session: {len(ins)} "
          f"({len(ins)/len(pool):.1%}); out of session {len(pool)-len(ins)}")

    # An even spread over the pool's own time order, not the first N (which
    # would be 2024 only) and not a fresh random draw (which would not be
    # reproducible).
    if len(ins) > TARGET:
        idx = np.linspace(0, len(ins) - 1, TARGET).round().astype(int)
        ins = ins.iloc[np.unique(idx)].reset_index(drop=True)
    print(f"pricing {len(ins)} prints across {ins['as_of_date'].nunique()} distinct days")

    pricer = make_pricer(strict_policy(1))
    ctrl = make_pricer(strict_policy(1))
    rows = []
    for i, r in ins.iterrows():
        snap = r["snap"]
        rec = {"trade_id": r["trade_id"], "as_of_date": r["as_of_date"],
               "tenor_years": float(r["tenor_years"]), "tenor_label": r["tenor_label"],
               "platform": r["platform_identifier"], "venue": r["venue"],
               "is_block": bool(r["is_block"]), "is_off_date": bool(r["is_off_date"]),
               "snap_et": snap.strftime("%Y-%m-%d %H:%M"),
               "printed_pct": float(r["fixed_rate"]) * 100.0}
        try:
            h = pricer.handle(CURVE, snap.to_pydatetime())
            lp = pricer.price_leg(CURVE, snap.to_pydatetime(), r["effective_date"],
                                  r["expiration_date"], float(r["notional"]))
            rec["mid_pct"] = lp.mid_pct
            rec["pv01"] = lp.pv01
            rec["lag_s"] = curve_meta(h)["lag_signed_s"]
            rec["diff_bp"] = (rec["printed_pct"] - lp.mid_pct) * 100.0
        except SnapshotMiss as exc:
            rec["error"] = f"SnapshotMiss {str(exc)[:60]}"
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        # control: the SAME print against the curve one minute earlier
        prev = snap - pd.Timedelta(minutes=1)
        try:
            lp2 = ctrl.price_leg(CURVE, prev.to_pydatetime(), r["effective_date"],
                                 r["expiration_date"], float(r["notional"]))
            rec["diff_bp_m1"] = (rec["printed_pct"] - lp2.mid_pct) * 100.0
        except Exception:  # noqa: BLE001
            pass
        rows.append(rec)
        if (i + 1) % 25 == 0:
            print(f"  ... {i+1}/{len(ins)}")

    out = pd.DataFrame(rows)
    out.to_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_bias200.csv", index=False)
    d = out["diff_bp"].dropna()
    print(f"\npriced {len(d)}/{len(out)}; failures: "
          f"{out['error'].notna().sum() if 'error' in out else 0}")
    if "error" in out and out["error"].notna().any():
        print(out.loc[out["error"].notna(), ["trade_id", "snap_et", "error"]].head(10).to_string())

    def stats(x: pd.Series, label: str) -> None:
        x = x.dropna()
        if len(x) < 5:
            print(f"  {label:22s} n={len(x):4d}  (too few)")
            return
        print(f"  {label:22s} n={len(x):4d}  median {x.median():+.4f}  "
              f"IQR [{x.quantile(.25):+.4f}, {x.quantile(.75):+.4f}] "
              f"(w={x.quantile(.75)-x.quantile(.25):.3f})  "
              f"|d|<=0.1bp {(x.abs() <= 0.1).mean():5.1%}  "
              f"frac>0 {(x > 0).mean():5.1%}  "
              f"p05 {x.quantile(.05):+.3f} p95 {x.quantile(.95):+.3f}")

    print("\n=== (printed - mid), basis points ===")
    stats(d, "ALL")
    print("\nby tenor bucket:")
    bucket = pd.cut(out["tenor_years"], [0, 1.01, 2.01, 5.01, 10.01, 31],
                    labels=["<=1Y", "1-2Y", "2-5Y", "5-10Y", "10-30Y"])
    for b in bucket.cat.categories:
        stats(out.loc[bucket == b, "diff_bp"], str(b))
    print("\nby venue:")
    for v, g in out.groupby(out["venue"].fillna("<null>")):
        stats(g["diff_bp"], str(v))
    print("\nD2C whitelist vs rest (config.D2C_PLATFORM_WHITELIST):")
    is_d2c = out["platform"].isin(config.D2C_PLATFORM_WHITELIST)
    stats(out.loc[is_d2c, "diff_bp"], "D2C whitelist")
    stats(out.loc[~is_d2c, "diff_bp"], "other platforms")
    print("\nblock vs non-block:")
    stats(out.loc[out["is_block"], "diff_bp"], "block")
    stats(out.loc[~out["is_block"], "diff_bp"], "non-block")
    print("\nby year:")
    yr = pd.to_datetime(out["as_of_date"]).dt.year
    for y, g in out.groupby(yr):
        stats(g["diff_bp"], str(y))

    print("\n=== control: same prints, curve one minute EARLIER ===")
    stats(out["diff_bp_m1"], "t-1min curve")
    both = out[["diff_bp", "diff_bp_m1"]].dropna()
    if len(both) > 5:
        shift = (both["diff_bp_m1"] - both["diff_bp"])
        print(f"  median shift from moving the curve back one minute: "
              f"{shift.median():+.4f} bp (IQR {shift.quantile(.25):+.4f}..{shift.quantile(.75):+.4f})")
        print("  -> a median that barely moves is a CONVENTION statement, not a timing one")

    # A median offset is only alarming relative to the dispersion it sits in.
    if len(d) >= 20:
        se = d.std(ddof=1) / np.sqrt(len(d))
        print(f"\nmedian {d.median():+.4f} bp; mean {d.mean():+.4f} +/- {se:.4f} (1 s.e.)  "
              f"-> mean is {abs(d.mean()/se):.1f} s.e. from zero")
        print(f"sign split: {(d>0).sum()} above mid / {(d<0).sum()} below / {(d==0).sum()} exact")


if __name__ == "__main__":
    main()
