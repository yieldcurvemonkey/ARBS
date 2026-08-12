"""Hand-trace ONE real trade from the tape row to the rendered word.

A sign that renders inverted teaches the reader the wrong thing permanently,
and it does it while looking completely plausible -- two independent
inversions were caught during the backend work, one in the core convention
module and one in a notebook that printed a raw decimal with a "%" appended.

So this prints every number at every seam for a single decisive print, and
recomputes ``p`` from the logistic BY HAND rather than calling the module that
produced it. Its output is pasted into
``tests/test_dealer_direction_sign_trace.py`` as pinned constants, so the trace
runs in the offline gate afterwards.

    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ddfe07_sign_trace.py [DAY]
"""
from __future__ import annotations

import json
import math
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S  # noqa: E402
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE  # noqa: E402
from SDRUtils._swappulse_scripts.backfill_dealer_direction import (  # noqa: E402
    direction_label,
)
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402
from SDRUtils.dealer_direction import conventions as conv  # noqa: E402


def _read(conn, sql, **params):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params or None)


def main(day: str | None) -> int:
    conn = psycopg2.connect(resolve_pg_url())

    # A single-leg OUTRIGHT decided by the rate rule, as far from mid as we
    # have, so the call is unambiguous and every intermediate number is large
    # enough to read.
    where = "AND u.as_of_date = %(d)s" if day else ""
    u = _read(conn, f"""
        SELECT * FROM {S.UNIT_TABLE} u
        WHERE u.rule = 'RATE_VS_MID'
          AND u.kind = 'OUTRIGHT'
          AND u.exclusion_reason IS NULL
          AND u.p IS NOT NULL
          AND u.p > 0.98
          AND u.rate_index = 'SOFR'
          AND u.n_legs = 1
          {where}
        ORDER BY abs(u.total_delta_dv01) DESC NULLS LAST
        LIMIT 1
    """, **({"d": day} if day else {}))
    if u.empty:
        print("no decisive OUTRIGHT found; has `publish` run?")
        return 2
    r = u.iloc[0]
    pkg = str(r["package_id"])

    legs = _read(conn, f"""
        SELECT trade_id, package_id, leg_order, as_of_date, fixed_rate,
               notional, effective_date, expiration_date, tenor_years,
               execution_timestamp, event_timestamp, rate_index_clean,
               platform_identifier, venue, is_block, is_capped, trade_type
        FROM {LEGS_TABLE} WHERE package_id = %(p)s ORDER BY leg_order
    """, p=pkg)

    buckets = _read(conn, f"""
        SELECT bucket_key, dv01_if_received, delta_dv01, signed_weight
        FROM {S.UNIT_BUCKET_TABLE} WHERE package_id = %(p)s
        ORDER BY bucket_key
    """, p=pkg)
    conn.close()

    p = float(r["p"])
    w = float(r["signed_weight"])
    dev = float(r["deviation_bps"])
    tau = float(r["tau_bps"])
    b0 = float(r["mid_bias_bps"])
    leg = legs.iloc[0]

    # ---- 1. the tape row ------------------------------------------------
    print("=" * 74)
    print("SEAM 1  the tape")
    print("=" * 74)
    print(f"  package_id        {pkg}")
    print(f"  trade_id          {leg['trade_id']}")
    print(f"  as_of_date        {leg['as_of_date']}")
    print(f"  fixed_rate        {float(leg['fixed_rate']):.8f}  "
          f"(decimal fraction = {float(leg['fixed_rate']) * 100:.5f}%)")
    print(f"  notional          {float(leg['notional']):,.0f}")
    print(f"  tenor_years       {float(leg['tenor_years']):.4f}")
    print(f"  execution ts      {leg['execution_timestamp']}")
    print(f"  platform / venue  {leg['platform_identifier']} / {leg['venue']}")

    # ---- 2. price against mid -------------------------------------------
    traded_pct = float(leg["fixed_rate"]) * 100.0
    mid_pct = traded_pct - dev / 100.0        # dev is in bp of the quoted price
    print()
    print("=" * 74)
    print("SEAM 2  price against the repriced mid")
    print("=" * 74)
    print(f"  curve             {r['curve_name']} @ {r['curve_timestamp']}")
    print(f"  policy            {r['snapshot_policy']}  "
          f"lag {r['snapshot_lag_seconds']}s")
    print(f"  traded            {traded_pct:.6f} %")
    print(f"  mid (implied)     {mid_pct:.6f} %")
    print(f"  deviation_bps     {dev:+.6f} bp   "
          f"(traded {'ABOVE' if dev > 0 else 'BELOW'} mid)")
    print("  conventions.structure_price(rates_pct, OUTRIGHT, 1, RATE_VS_MID)")
    print(f"    quote weights   {conv.quote_weights('OUTRIGHT', 1, conv.RULE_RATE)}")
    print(f"    base orientation{conv.base_orientation('OUTRIGHT', 1, conv.RULE_RATE)}"
          "   (+1 = pay fixed)")

    # ---- 3. the probability, recomputed BY HAND -------------------------
    z = (dev - b0) / tau
    p_hand = 1.0 / (1.0 + math.exp(-z))
    w_hand = 2.0 * p_hand - 1.0
    print()
    print("=" * 74)
    print("SEAM 3  deviation -> probability, recomputed by hand")
    print("=" * 74)
    print(f"  tau_bucket        {r['tau_bucket']}")
    print(f"  b0 (mid bias)     {b0:+.8f} bp")
    print(f"  tau               {tau:.8f} bp")
    print(f"  z = (dev-b0)/tau  ({dev:+.8f} - {b0:+.8f}) / {tau:.8f} "
          f"= {z:+.8f}")
    print(f"  p  = 1/(1+e^-z)   {p_hand:.12f}    stored {p:.12f}   "
          f"|diff| {abs(p - p_hand):.3e}")
    print(f"  2p-1              {w_hand:+.12f}   stored {w:+.12f}  "
          f"|diff| {abs(w - w_hand):.3e}")
    print(f"  conventions.signed_weight(p) = {conv.signed_weight(p):+.12f}")
    print(f"  dealer_side(dev-b0) = {conv.dealer_side(dev - b0):+d}   "
          f"stored dealer_sign {int(r['dealer_sign']):+d}")

    # ---- 4. the sign, in words ------------------------------------------
    print()
    print("=" * 74)
    print("SEAM 4  the sign becomes a word")
    print("=" * 74)
    print("  convention: customer pays fixed -> dealer RECEIVED fixed")
    print("              -> dealer long duration -> delta_dv01 > 0")
    print(f"  printed {'ABOVE' if dev > 0 else 'BELOW'} mid "
          f"=> customer {'PAID' if dev > 0 else 'RECEIVED'} fixed "
          f"=> dealer {'RECEIVED' if dev > 0 else 'PAID'}")
    print(f"  dealer_sign       {int(r['dealer_sign']):+d}")
    print(f"  direction_label   {direction_label(r['dealer_sign'], None)}")
    print(f"  DB dealer_direction  {r['dealer_direction']}")

    # ---- 5. the risk ----------------------------------------------------
    print()
    print("=" * 74)
    print("SEAM 5  the signed key-rate profile")
    print("=" * 74)
    print(buckets.to_string(index=False))
    tot_r = float(buckets["dv01_if_received"].sum())
    tot_d = float(buckets["delta_dv01"].sum())
    print(f"  sum dv01_if_received {tot_r:+,.2f}")
    print(f"  sum delta_dv01       {tot_d:+,.2f}   "
          f"(= {w:+.6f} x {tot_r:+,.2f} = {w * tot_r:+,.2f})")
    print(f"  stored total_delta_dv01 {float(r['total_delta_dv01']):+,.2f}")
    same = (tot_d > 0) == (int(r["dealer_sign"]) > 0)
    print(f"  sign(delta_dv01) agrees with dealer_sign: {same}")

    # ---- the fixture ----------------------------------------------------
    fixture = {
        "package_id": pkg,
        "trade_id": str(leg["trade_id"]),
        "as_of_date": str(leg["as_of_date"]),
        "fixed_rate": float(leg["fixed_rate"]),
        "notional": float(leg["notional"]),
        "tenor_years": float(leg["tenor_years"]),
        "deviation_bps": dev,
        "mid_bias_bps": b0,
        "tau_bps": tau,
        "p": p,
        "signed_weight": w,
        "dealer_sign": int(r["dealer_sign"]),
        "dealer_direction": str(r["dealer_direction"]),
        "rule": str(r["rule"]),
        "tau_bucket": str(r["tau_bucket"]),
        "curve_name": str(r["curve_name"]),
        "snapshot_policy": str(r["snapshot_policy"]),
        "total_dv01_if_received": tot_r,
        "total_delta_dv01": tot_d,
        "buckets": buckets.to_dict("records"),
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "ddfe07_sign_trace_fixture.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(fixture, fh, indent=2, default=str)
    print(f"\nfixture -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
