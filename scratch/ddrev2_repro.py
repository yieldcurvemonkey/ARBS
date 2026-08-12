"""Concrete repros for the defects claimed in the ladder-module review."""
import datetime
import traceback

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import health, ladder, provenance
from SDRUtils.dealer_direction import types as T


def hdr(n):
    print("\n" + "=" * 72 + f"\n{n}\n" + "=" * 72)


# --- R1: rolling_recycling_kappa short history loses its columns ----------
hdr("R1 rolling_recycling_kappa on history shorter than the window")
idx = pd.date_range("2026-01-01", periods=30, freq="D").date
s = pd.Series(np.where(np.arange(30) % 2 == 0, 1.0, -1.0), index=pd.Index(idx))
out = health.rolling_recycling_kappa(s, s, window_days=90, step_days=10)
print("columns:", list(out.columns), " len:", len(out))
try:
    out["kappa"]
    print("kappa readable")
except KeyError as e:
    print("KeyError on out['kappa']:", e)
print("contrast, the empty-input branch:",
      list(health.rolling_recycling_kappa(pd.Series(dtype=float),
                                          pd.Series(dtype=float)).columns))


# --- R2: imputed_notional_fraction with a renamed flag column -------------
hdr("R2 imputed_notional_fraction, notional_imputed column absent")
prov = pd.DataFrame({"unit_key": list("ABCD"),
                     "notional_imputed_flag": [True, False, False, False]})
m = health.imputed_notional_fraction(prov)
print("no weights -> value:", m.value, "status:", m.status, "(silent NO_DATA)")
try:
    health.imputed_notional_fraction(
        prov, weights=pd.Series([700.0, 100.0, 100.0, 100.0], index=list("ABCD")))
except Exception as e:
    print("with weights ->", type(e).__name__, e)


# --- R3: pricing_success_by_stratum, BASIS alarm silently disabled --------
hdr("R3 pricing_success_by_stratum, index column named neither way")
as_of = datetime.date(2026, 6, 10)
legs = pd.DataFrame({
    "as_of_date": [as_of] * 2, "effective_date": [as_of] * 2,
    "is_capped_flag": [False] * 2,
    "index_name": ["BASIS", "BASIS"],
    "priced": [True, True],
})
out = health.pricing_success_by_stratum(legs).set_index("stratum")
print(out[["n", "n_priced", "status"]])
print("BASIS status with two PRICED basis legs:", out.loc["BASIS", "status"])
print("CAPPED status:", out.loc["CAPPED", "status"])


# --- R4: krd rows for units not in `units` vanish unaccounted -------------
hdr("R4 risk rows for an unknown unit are dropped with no exclusion row")
u = T.Unit(unit_key="A", kind=conv.OUTRIGHT, legs=pd.DataFrame({"trade_id": ["t"]}),
           package_id=None, rate_index="SOFR", as_of_date=as_of,
           venue_class=T.VENUE_D2C,
           clocks=T.Clocks(pricing=pd.Timestamp("2026-06-10T14:00Z"),
                           execution=pd.Timestamp("2026-06-10T14:00Z"),
                           event=pd.Timestamp("2026-06-10T14:00Z"),
                           visibility=pd.Timestamp("2026-06-10T15:00Z"),
                           visibility_source="APPENDIX_C_ESTIMATE"))
call = T.DirectionCall(unit_key="A", rule=conv.RULE_RATE, deviation_bps=2.0,
                       p=0.9, signed_weight=conv.signed_weight(0.9), dealer_sign=1)
krd = pd.DataFrame([
    {"unit_key": "A", "bucket_space": "IRS_KRD", "bucket_key": "5Y",
     "dv01_if_received": 1000.0},
    {"unit_key": "GHOST", "bucket_space": "IRS_KRD", "bucket_key": "5Y",
     "dv01_if_received": 9_000_000.0},
])
rows, excl = ladder.unit_ladder_rows([u], [call], krd)
print("rows:", list(rows["unit_key"]), " excluded:", list(excl["unit_key"]))
print("9,000,000 of DV01 left the pipeline with no name")


# --- R5: duplicate Unit objects double-count ------------------------------
hdr("R5 the same Unit twice -> counted twice, no error")
rows, excl = ladder.unit_ladder_rows([u, u], [call], krd.iloc[:1])
agg = ladder.aggregate(rows)
print(agg[["n_units", "delta_dv01", "abs_dv01"]].to_string(index=False))
print("(calls ARE dup-checked; units are not)")


# --- R6: a unit dropped inside the ladder is IN_LADDER in the coverage ----
hdr("R6 the provenance seam: a ladder-stage drop is counted IN_LADDER")
u2 = T.Unit(unit_key="B", kind=conv.OUTRIGHT, legs=pd.DataFrame({"trade_id": ["t"]}),
            package_id=None, rate_index="SOFR", as_of_date=as_of,
            venue_class=T.VENUE_D2C, clocks=u.clocks)
call2 = T.DirectionCall(unit_key="B", rule=conv.RULE_RATE, deviation_bps=2.0,
                        p=0.9, signed_weight=conv.signed_weight(0.9), dealer_sign=1)
rows, excl = ladder.unit_ladder_rows([u, u2], [call, call2], krd.iloc[:1])
print("B has no risk row -> ladder excludes it:", list(excl["failure_reason"]))
provs = [provenance.build(x, None, c, pricing_clock_field="execution_timestamp")
         for x, c in ((u, call), (u2, call2))]
tab = provenance.coverage_table(provenance.to_frame(provs),
                                dv01=pd.Series({"A": 1000.0, "B": 1000.0}))
print(tab.to_string(index=False))
print("B is reported IN_LADDER although the ladder threw it out")


# --- R7: a zero-DV01 unit is a silent zero share --------------------------
hdr("R7 coverage_table: dv01 == 0.0 is accepted where NaN is refused")
p = pd.DataFrame([{"unit_key": "A", "failure_reason": None},
                  {"unit_key": "B", "failure_reason": T.EXCL_NO_CURVE}])
tab = provenance.coverage_table(p, dv01=pd.Series({"A": 1000.0, "B": 0.0}))
print(tab.to_string(index=False))
print("EXCL_NO_CURVE reports a 0.0% share; the error text says exactly this "
      "is what must not happen")


# --- R8: horizon_days > n crashes -----------------------------------------
hdr("R8 d2d_recycling_kappa with horizon_days longer than the sample")
short = pd.Series([1.0, -1.0, 1.0],
                  index=pd.Index(pd.date_range("2026-01-01", periods=3).date))
try:
    health.d2d_recycling_kappa(short, short, horizon_days=5, n_bootstrap=0)
except Exception as e:
    print(type(e).__name__, e)


# --- R9: the flagship kappa test does not reach the kappa formula ---------
hdr("R9 kappa==hit_rate survives the F-20 test (degenerate short-circuit)")
n = 200
one = pd.Series([1.0] * n, index=pd.Index(pd.date_range("2026-01-01", periods=n).date))
res = health.d2d_recycling_kappa(one, one, horizon_days=1, n_bootstrap=0)
print("both series all +1 -> degenerate:", res.degenerate,
      "kappa:", res.kappa, "(returned by the degenerate branch, "
      "never by the kappa formula)")


# --- R10: a bounded NEAREST policy reads as the strict in-session branch --
hdr("R10 is_overnight_hole ignores method=")
print("nearest/60s ->", health.is_overnight_hole(
    "method=nearest max_lag=60s allow_future=True on_miss=none"))
print("i.e. the shipped either-direction rule that serves 1.09% of legs a "
      "FUTURE curve is classified as the strict in-session branch")
