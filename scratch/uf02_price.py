"""Reprice sampled tape prints so the upfront rule can be measured against them.

One script, several populations (``--set``), all priced identically: the Citi
minute curve, ``snapshot.pricing_timestamp`` for the clock, T-1min, and the
session-branched policy (strict in session, bounded ``asof`` outside it).

The output carries BOTH ``dev_bps`` (printed rate minus mid) and
``npv_implied_dev_bps`` (``-npv_pay / pv01``). They must be equal: ``npv_pay``
is the NPV to the fixed *payer*, ``(mid - R)*A``, and ``pv01 = A*1e-4``. If they
come out with opposite signs then ``IRSwapValue.NPV`` is in the receiver frame
and the frozen classifier's ``itm_side = PAID if npv_pay > 0`` is inverted --
which is the single assumption the whole upfront rule rests on, so it is
measured rather than assumed.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import snapshot

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dd_common                                                  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

COLS = """
    l.trade_id, l.as_of_date, l.execution_timestamp, l.original_execution_timestamp,
    l.event_timestamp, l.event_timestamp_granularity, l.lifecycle_type,
    l.economic_class, l.effective_date, l.expiration_date, l.notional,
    l.fixed_rate, l.rate_index_clean, l.tenor_years, l.tenor_label,
    l.other_payment_ufro, l.other_payment_uwin, l.is_capped, l.is_block,
    l.is_off_market, l.trade_type, l.package_id,
    p.n_package_legs, p.package_transaction_price AS pkg_ptp
"""

SANE = """
    l.fixed_rate IS NOT NULL AND abs(l.fixed_rate) < 1.0 AND l.notional < 1e11
    AND l.notional > 0 AND l.effective_date IS NOT NULL
    AND l.expiration_date IS NOT NULL AND l.expiration_date > l.as_of_date
    AND l.rate_index_clean IN ('SOFR','FED_FUNDS')
    AND l.trade_type = 'OUTRIGHT' AND coalesce(p.n_package_legs, 1) <= 1
"""

FLOW = """
    l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
    AND l.lifecycle_type='NEW_TRADE'
"""

SETS = {
    # The headline population: a fee is present and the rate is NOT an outlier,
    # so the rate rule and the upfront rule both apply and must agree (F-10).
    "flow_fee": f"{FLOW} AND NOT l.is_off_market AND l.other_payment_ufro > 0 AND NOT l.is_capped",
    # Known answer: F-15 measured median (printed - mid) = +0.021 bp on this
    # population. If the harness cannot reproduce that, nothing else it says
    # is worth reading.
    "onmkt_control": f"{FLOW} AND NOT l.is_off_market AND coalesce(l.other_payment_ufro,0) = 0 AND NOT l.is_capped",
    # Where the fee is doing the work: the rate IS an outlier and a fee is present.
    "offmkt_fee": f"{FLOW} AND l.is_off_market AND l.other_payment_ufro > 0 AND NOT l.is_capped",
    # The cap test, and its size-matched control.
    "capped_fee": f"{FLOW} AND l.other_payment_ufro > 0 AND l.is_capped",
    "uncapped_big_fee": (f"{FLOW} AND l.other_payment_ufro > 0 AND NOT l.is_capped "
                         "AND l.notional >= 2.5e8"),
    # Terminations. UWIN is empty on this tape (15 rows in 2.33M); the fee lives
    # in UFRO. Kept as its own population regardless.
    "term_fee": ("l.lifecycle_type='TERMINATION' AND l.economic_class='ECONOMIC_FLOW' "
                 "AND l.other_payment_ufro > 0 AND NOT l.is_capped"),
    "term_seasoned": ("l.lifecycle_type='TERMINATION' AND l.economic_class='ECONOMIC_FLOW' "
                      "AND l.other_payment_ufro > 0 AND NOT l.is_capped "
                      "AND l.effective_date < l.as_of_date - 30"),
}


def sample(conn, where: str, modulus: int) -> pd.DataFrame:
    sql = f"""
      SELECT {COLS}
      FROM {LEGS_TABLE} l LEFT JOIN {PACKAGES_TABLE} p USING (package_id)
      WHERE {where} AND {SANE}
        AND abs(hashtext(l.trade_id)) %% %(m)s = %(k)s
      ORDER BY l.trade_id
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # The remainder has to be inside the modulus -- `= 7` with `%% 2` selects
        # nothing at all, silently, and an empty sample looks like an empty
        # universe rather than like a broken predicate.
        return pd.read_sql(sql, conn, params={"m": modulus, "k": 7 % modulus})


def price(df: pd.DataFrame) -> pd.DataFrame:
    strict = dd_common.make_pricer(dd_common.strict_policy(1.0))
    hole = dd_common.make_pricer(dd_common.hole_policy(2.0))
    out, t0 = [], time.time()
    for i, r in df.iterrows():
        rec = {c: r[c] for c in (
            "trade_id", "as_of_date", "rate_index_clean", "tenor_years",
            "tenor_label", "notional", "fixed_rate", "other_payment_ufro",
            "other_payment_uwin", "pkg_ptp", "is_capped", "is_block",
            "is_off_market", "lifecycle_type", "effective_date",
            "expiration_date")}
        curve = snapshot.CURVE_FOR[r["rate_index_clean"]]
        rec["curve"] = curve
        try:
            ts, field = snapshot.pricing_timestamp(r)
            instant = snapshot.snap_instant(ts)
            rec["clock_field"] = field
            rec["snap"] = str(instant)
            pricer = strict if snapshot.in_session(curve, instant) else hole
            rec["policy"] = "strict" if pricer is strict else "asof2h"
            lp = pricer.price_leg(curve, instant, r["effective_date"],
                                  r["expiration_date"], float(r["notional"]),
                                  float(r["fixed_rate"]))
            rec["mid_pct"] = lp.mid_pct
            rec["npv_pay"] = lp.npv_pay
            rec["pv01"] = lp.pv01
            rec["lag_s"] = snapshot.snapshot_lag_seconds(
                pricer.handle(curve, instant))
            rec["error"] = None
        except Exception as exc:                              # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"[:160]
        out.append(rec)
        if (i + 1) % 100 == 0:
            done = len(out)
            print(f"  {done}/{len(df)}  {(time.time()-t0)/done*1000:.0f} ms/print",
                  flush=True)
    res = pd.DataFrame(out)
    ok = res["error"].isna()
    res.loc[ok, "dev_bps"] = (res.loc[ok, "fixed_rate"] * 100.0
                              - res.loc[ok, "mid_pct"]) * 100.0
    res.loc[ok, "npv_implied_dev_bps"] = -res.loc[ok, "npv_pay"] / res.loc[ok, "pv01"].abs()
    res.loc[ok, "u_bps"] = res.loc[ok, "other_payment_ufro"] / res.loc[ok, "pv01"].abs()
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True, choices=sorted(SETS))
    ap.add_argument("--modulus", type=int, default=200,
                    help="1-in-N reproducible hash sample")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    conn = psycopg2.connect(resolve_pg_url())
    df = sample(conn, SETS[args.set], args.modulus)
    conn.close()
    if args.limit:
        df = df.iloc[:args.limit].copy()
    print(f"{args.set}: {len(df)} sampled rows, "
          f"{df['as_of_date'].nunique()} days")

    res = price(df.reset_index(drop=True))
    path = f"C:/Users/chris/clee/ARBS-dd/scratch/uf02_{args.set}.csv"
    res.to_csv(path, index=False)

    ok = res[res["error"].isna()]
    print(f"priced {len(ok)}/{len(res)}  -> {path}")
    if len(res) > len(ok):
        print(res.loc[res["error"].notna(), "error"].value_counts().head(6).to_string())
    if not len(ok):
        return
    # The frame check. These two must agree to float noise.
    d = (ok["dev_bps"] - ok["npv_implied_dev_bps"]).abs()
    print(f"\nNPV frame check |dev - npv_implied_dev|: median {d.median():.3e} bp, "
          f"p95 {d.quantile(0.95):.3e} bp, max {d.max():.3e} bp")
    corr = ok["dev_bps"].corr(ok["npv_implied_dev_bps"])
    print(f"corr(dev, npv_implied_dev) = {corr:+.6f}  "
          f"(-1 would mean IRSwapValue.NPV is the RECEIVER frame)")
    print(f"\ndev_bps: median {ok['dev_bps'].median():+.4f}  "
          f"IQR [{ok['dev_bps'].quantile(.25):+.4f}, {ok['dev_bps'].quantile(.75):+.4f}]  "
          f"frac>0 {(ok['dev_bps']>0).mean():.3f}")
    if ok["u_bps"].notna().any():
        print(f"u_bps  : median {ok['u_bps'].median():.4f}  "
              f"IQR [{ok['u_bps'].quantile(.25):.4f}, {ok['u_bps'].quantile(.75):.4f}]")


if __name__ == "__main__":
    main()
