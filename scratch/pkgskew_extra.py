"""Three hardening checks the headline leans on.

10a  per-bucket exclusion rate month by month -- does each ladder level's
     retention factor hold still, or does it drift?
10b  venue EVIDENCE tier behind the "PKG-4+ is 97.9% D2C" claim (exact join on
     the cached package_id set, not an n_package_legs>=4 approximation)
10c  is the PKG-4+ package price a real number or a placeholder?
"""
from __future__ import annotations

import os
import pathlib
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd

CACHE = pathlib.Path(os.environ.get("PKGSKEW_CACHE", r"D:\pkgskew_cache"))
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 400)
pd.set_option("display.max_columns", 40)
pd.set_option("display.float_format", lambda v: f"{v:,.3f}")

BUCKETS = ["0-1Y", "1-2Y", "2-3Y", "3-5Y", "5-7Y", "7-10Y",
           "10-15Y", "15-20Y", "20-30Y", "30Y+"]


def load(kind):
    fs = sorted(CACHE.glob(f"{kind}_*.parquet"))
    assert len(fs) == 30, f"expected 30 {kind} chunks, found {len(fs)}"
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)


def hdr(s):
    print("\n" + "=" * 100)
    print(s)
    print("=" * 100)


def main() -> int:
    legs = load("legs")
    units = load("units")
    legs["month"] = pd.to_datetime(legs["as_of_date"]).dt.to_period("M")

    # ---------------------------------------------------------------- 10a
    hdr("10a. PER-BUCKET EXCLUSION RATE, MONTH BY MONTH (complete months "
        "2024-07..2026-07)")
    piv = legs.pivot_table(index="month", columns="tenor_bucket", values="dv01",
                           aggfunc="sum", observed=True, fill_value=0.0)
    keptp = legs[legs["exclusion"].isna()].pivot_table(
        index="month", columns="tenor_bucket", values="dv01", aggfunc="sum",
        observed=True, fill_value=0.0)
    rate = 100 * (1 - keptp.reindex_like(piv).fillna(0.0) / piv)
    rate = rate[BUCKETS].loc["2024-07":"2026-07"]
    x = np.arange(len(rate))
    rows = []
    for b in BUCKETS:
        y = rate[b].to_numpy()
        b1, b0 = np.polyfit(x, y, 1)
        res = y - (b0 + b1 * x)
        se = np.sqrt((res ** 2).sum() / (len(x) - 2) / ((x - x.mean()) ** 2).sum())
        rows.append({"bucket": b, "mean_%": y.mean(), "sd_pp": y.std(ddof=1),
                     "min_%": y.min(), "max_%": y.max(),
                     "range_pp": y.max() - y.min(),
                     "trend_pp_yr": 12 * b1, "t": b1 / se})
    out = pd.DataFrame(rows).set_index("bucket")
    print(out)
    print(f"\n  worst per-bucket sd: {out['sd_pp'].max():.2f} pp "
          f"({out['sd_pp'].idxmax()});  median sd {out['sd_pp'].median():.2f} pp")
    print(f"  |t| on the monthly trend exceeds 2 in: "
          f"{list(out.index[out['t'].abs() > 2])}")
    print("\n  for scale: the CROSS-BUCKET spread of the mean rate is "
          f"{out['mean_%'].max() - out['mean_%'].min():.2f} pp, against a "
          f"median within-bucket month-to-month sd of {out['sd_pp'].median():.2f} pp")
    print("\n  full monthly matrix")
    print(rate.round(1))

    # ---------------------------------------------------------------- 10b/c
    import psycopg2
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
    from SDRUtils.dealer_direction.universe import classify_venue, venue_evidence

    p_pid, p_ptp = CACHE / "x_pid.parquet", CACHE / "x_ptp.parquet"
    if p_pid.exists() and p_ptp.exists():
        pid, ptp = pd.read_parquet(p_pid), pd.read_parquet(p_ptp)
    else:
        conn = psycopg2.connect(resolve_pg_url())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pid = pd.read_sql(
                f"SELECT package_id, min(platform_identifier) pid, "
                f"count(DISTINCT platform_identifier) n_pid FROM {LEGS_TABLE} "
                "GROUP BY 1", conn)
            ptp = pd.read_sql(
                f"SELECT package_id, package_transaction_price ptp_val, "
                f"ptp_price_notation, package_transaction_spread pts_val "
                f"FROM {PACKAGES_TABLE}", conn)
        conn.close()
        pid.to_parquet(p_pid, index=False)
        ptp.to_parquet(p_ptp, index=False)

    u = units.merge(pid, on="package_id", how="left").merge(
        ptp, on="package_id", how="left")
    assert u["pid"].notna().sum() + u["pid"].isna().sum() == len(units)

    hdr("10b. VENUE EVIDENCE TIER behind the PKG-4+ D2C claim")
    p4 = u[u["excl_class"] == "PKG4"].copy()
    kp = u[u["excl_class"] == "KEPT"].copy()
    for name, s in (("PKG-4+", p4), ("RETAINED", kp)):
        s = s.copy()
        s["vclass"] = [classify_venue(p) for p in s["pid"]]
        s["eviden"] = [venue_evidence(p) for p in s["pid"]]
        tot = s["dv01_proxy"].sum()
        print(f"\n  {name}  DV01 {tot:,.0f}")
        g = (s.groupby(["vclass", "eviden"], observed=True)["dv01_proxy"]
              .agg(["size", "sum"]))
        g["dv01_%"] = 100 * g["sum"] / tot
        print(g.sort_values("sum", ascending=False))
    print("\n  top platform_identifier for PKG-4+ by DV01")
    p4["vclass"] = [classify_venue(p) for p in p4["pid"]]
    print(p4.groupby("pid", observed=True)
            .agg(n=("dv01_proxy", "size"), dv01=("dv01_proxy", "sum"),
                 vclass=("vclass", "first"))
            .assign(pct=lambda t: 100 * t["dv01"] / p4["dv01_proxy"].sum())
            .sort_values("dv01", ascending=False).head(12))

    hdr("10c. IS THE PKG-4+ PACKAGE PRICE A REAL NUMBER?")
    v = p4["ptp_val"]
    print(f"  PKG-4+ units {len(p4):,};  package-level PTP non-null "
          f"{v.notna().sum():,} ({100 * v.notna().mean():.2f}%)")
    nn = v.dropna()
    print(f"  exactly 0.0      {int((nn == 0).sum()):,} "
          f"({100 * (nn == 0).mean():.2f}% of non-null)   "
          f"DV01 share {100 * p4.loc[p4['ptp_val'] == 0, 'dv01_proxy'].sum() / p4['dv01_proxy'].sum():.2f}%")
    print(f"  |value| > 1e12   {int((nn.abs() > 1e12).sum()):,}")
    print(f"  negative         {int((nn < 0).sum()):,} ({100 * (nn < 0).mean():.2f}%)")
    print("\n  quantiles of non-zero |PTP|")
    print(nn[nn != 0].abs().describe(percentiles=[.01, .1, .5, .9, .99]))
    print("\n  ptp_price_notation mix on PKG-4+ (units / DV01 %)")
    g = p4.groupby("ptp_price_notation", dropna=False, observed=True)[
        "dv01_proxy"].agg(["size", "sum"])
    g["dv01_%"] = 100 * g["sum"] / p4["dv01_proxy"].sum()
    print(g)
    print("\n  for contrast, notation mix on the RETAINED population")
    g2 = kp.groupby("ptp_price_notation", dropna=False, observed=True)[
        "dv01_proxy"].agg(["size", "sum"])
    g2["dv01_%"] = 100 * g2["sum"] / kp["dv01_proxy"].sum()
    print(g2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
