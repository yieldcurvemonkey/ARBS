"""Reproduce the coverage report's own numbers from the cache. Gate, not a report.

If any line here misses, the split is wrong and every downstream table is too.
Reference: scratch/_rep_full.txt (610-day run, 2024-03-01..2026-08-07).
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd

CACHE = pathlib.Path(os.environ.get("PKGSKEW_CACHE", r"D:\pkgskew_cache"))
pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 300)

REF_UNITS = {
    "UNORIENTABLE_PKG": (272373, 768706, 39.973637),
    "UNSUPPORTED_INDEX": (52672, 54470, 1.700227),
    "PRICING_ERROR": (19212, 19341, 0.626532),
    "NO_FIXED_RATE": (8006, 10164, 0.584493),
    "RISK_IMPLAUSIBLE": (2735, 3080, 0.121421),
    "NOT_ECONOMIC_FLOW": (302, 307, 0.026550),
    "STANDARD_COUPON": (145, 153, 0.010449),
}
REF_DETAIL = {
    "PKG-4+": (46946, 505455, 22.567462),
    "SPREADOVER": (106125, 106125, 6.040688),
    "MATCHED_MATURITY": (57182, 57182, 3.915588),
    "INVOICE": (31693, 31693, 3.062897),
    "SPREADOVER_CURVE": (17694, 35388, 1.964164),
    "SPREADOVER_FLY": (7181, 21543, 1.355278),
    "INVOICE_SWITCH": (2454, 4908, 0.497916),
    "MATCHED_MATURITY_CURVE": (2486, 4972, 0.397581),
    "INVOICE_CALENDAR": (396, 792, 0.122521),
    "MATCHED_MATURITY_FLY": (216, 648, 0.049543),
}
REF_VENUE_KEPT = {"D2C": (1001795, 1325463), "D2D": (45742, 108266),
                  "VENUE_UNKNOWN": (34856, 36831)}


def load(kind):
    fs = sorted(CACHE.glob(f"{kind}_*.parquet"))
    assert len(fs) == 30, f"expected 30 {kind} chunks, found {len(fs)}"
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)


def chk(label, got, want, tol=0.0):
    ok = abs(got - want) <= tol
    print(f"  {'OK ' if ok else 'MISS'}  {label:<52} got {got:>18,.6f}  "
          f"want {want:>18,.6f}")
    return ok


def main() -> int:
    units = load("units")
    legs = load("legs")
    ok = True

    print("=== totals ===")
    ok &= chk("units", len(units), 1_437_838)
    ok &= chk("legs", len(legs), 2_326_781)
    kept = units["exclusion"].isna()
    ok &= chk("kept units", int(kept.sum()), 1_082_393)
    ok &= chk("kept units %", 100 * kept.mean(), 75.28, tol=0.005)
    tot = units["dv01_proxy"].sum()
    ok &= chk("DV01 proxy total", tot, 80_660_906_449, tol=1.0)
    ok &= chk("DV01 proxy kept", units.loc[kept, "dv01_proxy"].sum(),
              45_941_783_080, tol=1.0)
    ok &= chk("DV01 proxy kept %", 100 * units.loc[kept, "dv01_proxy"].sum() / tot,
              56.96, tol=0.005)
    ok &= chk("sentinel units", int(units["has_sentinel"].sum()), 55)
    ok &= chk("leg DV01 sum == unit DV01 sum", legs["dv01"].sum(), tot, tol=1.0)
    ok &= chk("days", units["as_of_date"].nunique(), 610)

    print("\n=== exclusions by pinned constant ===")
    g = units.groupby("exclusion", dropna=True, observed=True).agg(
        n_units=("dv01_proxy", "size"), n_legs=("n_legs", "sum"),
        dv01=("dv01_proxy", "sum"))
    for k, (nu, nl, pct) in REF_UNITS.items():
        r = g.loc[k]
        ok &= chk(f"{k} units", int(r.n_units), nu)
        ok &= chk(f"{k} legs", int(r.n_legs), nl)
        ok &= chk(f"{k} DV01 %", 100 * r.dv01 / tot, pct, tol=1e-5)

    print("\n=== UNORIENTABLE_PKG by detail ===")
    un = units[units["exclusion"] == "UNORIENTABLE_PKG"]
    g = un.groupby("exclusion_detail", observed=True).agg(
        n_units=("dv01_proxy", "size"), n_legs=("n_legs", "sum"),
        dv01=("dv01_proxy", "sum"))
    for k, (nu, nl, pct) in REF_DETAIL.items():
        r = g.loc[k]
        ok &= chk(f"{k} units", int(r.n_units), nu)
        ok &= chk(f"{k} legs", int(r.n_legs), nl)
        ok &= chk(f"{k} DV01 %", 100 * r.dv01 / tot, pct, tol=1e-5)

    print("\n=== excl_class partition (must exhaust) ===")
    g = units.groupby("excl_class", observed=True).agg(
        n_units=("dv01_proxy", "size"), n_legs=("n_legs", "sum"),
        dv01=("dv01_proxy", "sum"))
    g["dv01_pct"] = 100 * g["dv01"] / tot
    print(g)
    ok &= chk("excl_class units sum", int(g["n_units"].sum()), 1_437_838)
    ok &= chk("PKG4 DV01 %", g.loc["PKG4", "dv01_pct"], 22.567462, tol=1e-5)
    ok &= chk("ASSETSWAP DV01 %", g.loc["ASSETSWAP", "dv01_pct"],
              39.973637 - 22.567462, tol=1e-5)

    print("\n=== venue, kept units ===")
    gv = units[kept].groupby("venue_class", observed=True).agg(
        n_units=("dv01_proxy", "size"), n_legs=("n_legs", "sum"))
    for k, (nu, nl) in REF_VENUE_KEPT.items():
        ok &= chk(f"kept {k} units", int(gv.loc[k, "n_units"]), nu)
        ok &= chk(f"kept {k} legs", int(gv.loc[k, "n_legs"]), nl)

    print("\n=== annuity-spread cut ties back to the leg total ===")
    sp = load("spread")
    ok &= chk("spread DV01 total", sp["dv01"].sum(), tot, tol=1.0)
    for c in ("KEPT", "PKG4", "ASSETSWAP", "OTHER_EXCL"):
        ok &= chk(f"spread {c}", sp.loc[sp["excl_class"] == c, "dv01"].sum(),
                  float(g.loc[c, "dv01"]), tol=1.0)

    print("\n=== leg-level bucket coverage ===")
    nb = legs["tenor_bucket"].isna().sum()
    print(f"  legs with no tenor bucket: {nb:,} "
          f"carrying {legs.loc[legs['tenor_bucket'].isna(), 'dv01'].sum():,.0f} DV01 "
          f"({100 * legs.loc[legs['tenor_bucket'].isna(), 'dv01'].sum() / tot:.4f}%)")

    print("\n" + ("ALL CHECKS PASS" if ok else "*** VALIDATION FAILED ***"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
