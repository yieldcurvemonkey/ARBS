"""Independent re-run of the review's R1-R11 against the FIXED code, plus
probes for defects the fix could have introduced. Reads only; edits nothing.

Each block prints VERDICT lines so the transcript is the evidence.
"""
import datetime
import traceback

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import health, ladder, provenance, snapshot
from SDRUtils.dealer_direction import types as T


def hdr(n):
    print("\n" + "=" * 74 + f"\n{n}\n" + "=" * 74)


def raises(fn, *a, **k):
    try:
        r = fn(*a, **k)
        return None, r
    except Exception as e:  # noqa: BLE001
        return e, None


as_of = datetime.date(2026, 6, 10)
CLOCKS = T.Clocks(pricing=pd.Timestamp("2026-06-10T14:00Z"),
                  execution=pd.Timestamp("2026-06-10T14:00Z"),
                  event=pd.Timestamp("2026-06-10T14:00Z"),
                  visibility=pd.Timestamp("2026-06-10T15:00Z"),
                  visibility_source="APPENDIX_C_ESTIMATE")


def unit(k):
    return T.Unit(unit_key=k, kind=conv.OUTRIGHT,
                  legs=pd.DataFrame({"trade_id": ["t"]}), package_id=None,
                  rate_index="SOFR", as_of_date=as_of,
                  venue_class=T.VENUE_D2C, clocks=CLOCKS)


def call(k, p=0.9):
    return T.DirectionCall(unit_key=k, rule=conv.RULE_RATE, deviation_bps=2.0,
                           p=p, signed_weight=conv.signed_weight(p),
                           dealer_sign=1)


EMPTY_EXCL = pd.DataFrame(columns=ladder.EXCLUSION_COLUMNS)

# ---------------------------------------------------------------- R1
hdr("R1 rolling_recycling_kappa, history shorter than the window")
idx = pd.date_range("2026-01-01", periods=30, freq="D").date
s = pd.Series(np.where(np.arange(30) % 2 == 0, 1.0, -1.0), index=pd.Index(idx))
out = health.rolling_recycling_kappa(s, s, window_days=90, step_days=10)
e, _ = raises(lambda: out["kappa"])
print("columns:", list(out.columns), "len:", len(out))
print("out['kappa'] ->", "KeyError" if e else "readable, empty")
empty_branch = list(health.rolling_recycling_kappa(pd.Series(dtype=float),
                                                   pd.Series(dtype=float)).columns)
print("no-data branch columns:", empty_branch)
print("VERDICT R1:", "FIXED" if (e is None and list(out.columns) == empty_branch
                                 and len(empty_branch) == 7) else "NOT FIXED")

# ---------------------------------------------------------------- R2
hdr("R2 imputed_notional_fraction, notional_imputed renamed")
prov = pd.DataFrame({"unit_key": list("ABCD"),
                     "notional_imputed_flag": [True, False, False, False]})
e1, r1 = raises(health.imputed_notional_fraction, prov)
e2, r2 = raises(health.imputed_notional_fraction, prov,
                weights=pd.Series([700.0, 100.0, 100.0, 100.0], index=list("ABCD")))
print("no weights ->", type(e1).__name__ if e1 else f"value={r1.value} status={r1.status}")
print("  msg:", str(e1)[:110] if e1 else "")
print("with weights ->", type(e2).__name__ if e2 else f"value={r2.value}")
print("  msg:", str(e2)[:110] if e2 else "")
empty_ok = health.imputed_notional_fraction(pd.DataFrame()).status
print("empty frame still NO_DATA (not an error):", empty_ok)
print("VERDICT R2:", "FIXED" if (isinstance(e1, ValueError)
                                 and isinstance(e2, ValueError)
                                 and empty_ok == health.NO_DATA) else "NOT FIXED")

# ---------------------------------------------------------------- R3
hdr("R3 pricing_success_by_stratum, is_capped / index column renamed")
legs = pd.DataFrame({"as_of_date": [as_of] * 2, "effective_date": [as_of] * 2,
                     "is_capped_flag": [False] * 2,
                     "index_name": ["BASIS", "BASIS"], "priced": [True, True]})
e1, r1 = raises(health.pricing_success_by_stratum, legs)
print("both renamed ->", type(e1).__name__ if e1 else "returned a frame")
print("  msg:", str(e1)[:130] if e1 else "")
e2, r2 = raises(health.pricing_success_by_stratum,
                legs.rename(columns={"is_capped_flag": "is_capped"}))
print("index only renamed ->", type(e2).__name__ if e2 else "returned a frame")
print("  msg:", str(e2)[:130] if e2 else "")
# and the happy path still works, both index spellings
for col in ("rate_index", "rate_index_clean"):
    good = legs.rename(columns={"is_capped_flag": "is_capped", "index_name": col})
    o = health.pricing_success_by_stratum(good).set_index("stratum")
    print(f"  happy path {col}: BASIS ->", o.loc["BASIS", "status"],
          " CAPPED ->", o.loc["CAPPED", "status"])
print("VERDICT R3:", "FIXED" if (isinstance(e1, ValueError)
                                 and isinstance(e2, ValueError)) else "NOT FIXED")

# ---------------------------------------------------------------- R4
hdr("R4 risk rows for a unit not in `units`")
krd = pd.DataFrame([
    {"unit_key": "A", "bucket_space": "IRS_KRD", "bucket_key": "5Y",
     "dv01_if_received": 1000.0},
    {"unit_key": "GHOST", "bucket_space": "IRS_KRD", "bucket_key": "5Y",
     "dv01_if_received": 9_000_000.0},
])
e, r = raises(ladder.unit_ladder_rows, [unit("A")], [call("A")], krd)
print("->", type(e).__name__ if e else f"rows={list(r[0]['unit_key'])} excl={list(r[1]['unit_key'])}")
print("  msg:", str(e)[:160] if e else "")
print("  carries the 9,000,000 in the message:", "9,000,000" in str(e))
print("VERDICT R4:", "FIXED" if isinstance(e, ValueError) else "NOT FIXED")

# ---------------------------------------------------------------- R5
hdr("R5 the same Unit passed twice")
e, r = raises(ladder.unit_ladder_rows, [unit("A"), unit("A")], [call("A")],
              krd.iloc[:1])
if e is None:
    agg = ladder.aggregate(r[0])
    print(agg[["n_units", "delta_dv01", "abs_dv01"]].to_string(index=False))
print("->", type(e).__name__ if e else "no error")
print("  msg:", str(e)[:160] if e else "")
print("VERDICT R5:", "FIXED" if isinstance(e, ValueError) else "NOT FIXED")

# ---------------------------------------------------------------- R6
hdr("R6 a ladder-stage drop must not be reported IN_LADDER")
units = [unit("A"), unit("B")]
calls = [call("A"), call("B")]
rows, excl = ladder.unit_ladder_rows(units, calls, krd.iloc[:1])  # B has no risk
print("ladder excluded B:", list(zip(excl["unit_key"], excl["failure_reason"])))
provs = provenance.to_frame(
    [provenance.build(u, None, c, pricing_clock_field="execution_timestamp")
     for u, c in zip(units, calls)])
print("provenance failure_reason as build writes it:", list(provs["failure_reason"]))
e, _ = raises(provenance.coverage_table, provs, dv01=pd.Series({"A": 1000.0, "B": 1000.0}))
print("coverage_table WITHOUT ladder_excluded ->", type(e).__name__, str(e)[:90])
tab = provenance.coverage_table(provs, dv01=pd.Series({"A": 1000.0, "B": 1000.0}),
                                ladder_excluded=excl).set_index("reason")
print(tab.to_string())
b_in_ladder = provenance.IN_LADDER in tab.index and tab.loc[provenance.IN_LADDER, "n_units"] == 2
print("VERDICT R6:", "FIXED" if (isinstance(e, TypeError)
                                 and T.EXCL_PRICING_ERROR in tab.index
                                 and not b_in_ladder) else "NOT FIXED")

# ---------------------------------------------------------------- R7 (G1)
hdr("R7/G1 coverage_table: dv01 == 0.0 accepted where NaN is refused")
p = pd.DataFrame([{"unit_key": "A", "failure_reason": None},
                  {"unit_key": "B", "failure_reason": T.EXCL_NO_CURVE}])
e, tab = raises(provenance.coverage_table, p,
                dv01=pd.Series({"A": 1000.0, "B": 0.0}),
                ladder_excluded=EMPTY_EXCL)
if e is None:
    print(tab.to_string(index=False))
print("->", type(e).__name__ if e else "accepted, 0.0% share reported")
print("VERDICT R7/G1:", "FIXED" if isinstance(e, ValueError) else "NOT FIXED")

# ---------------------------------------------------------------- R8
hdr("R8 d2d_recycling_kappa, horizon_days longer than the sample")
short = pd.Series([1.0, -1.0, 1.0],
                  index=pd.Index(pd.date_range("2026-01-01", periods=3).date))
e, r = raises(health.d2d_recycling_kappa, short, short, horizon_days=5,
              n_bootstrap=0)
print("->", type(e).__name__ + ": " + str(e)[:90] if e else f"status={r.status} n_pairs={r.n_pairs}")
print("VERDICT R8:", "FIXED" if (e is None and r.status == health.NO_DATA)
      else "NOT FIXED")

# ---------------------------------------------------------------- R9
hdr("R9 does the flagship F-20 test now reach the kappa formula?")
n = 200
one = pd.Series([1.0] * n,
                index=pd.Index(pd.date_range("2026-01-01", periods=n).date))
res = health.d2d_recycling_kappa(one, one, horizon_days=1, n_bootstrap=0)
print("both all +1 -> degenerate:", res.degenerate, "kappa:", res.kappa,
      "chance:", res.chance_rate, "(still the short-circuit)")
rng = np.random.default_rng(29)
m = 4000
x = np.where(rng.random(m) < 0.95, 1.0, -1.0)
y = np.where(rng.random(m) < 0.95, 1.0, -1.0)
ix = pd.Index(pd.date_range("2026-01-01", periods=m).date)
near = health.d2d_recycling_kappa(pd.Series(x, index=ix),
                                  pd.Series(np.r_[0.0, y[:-1]], index=ix),
                                  horizon_days=1, n_bootstrap=0)
print("95/5 both sides -> hit_rate:", round(near.hit_rate, 4),
      "kappa:", round(near.kappa, 4), "degenerate:", near.degenerate,
      "(goes THROUGH the formula)")
print("VERDICT R9: see mutation m6b (kappa == hit rate) below")

# ---------------------------------------------------------------- R10
hdr("R10 is_overnight_hole and the future-allowing policies")
cases = [
    ("method=nearest max_lag=60s allow_future=True on_miss=none", True),
    ("method=asof max_lag=60s allow_future=True on_miss=raise", True),
    ("method=nearest max_lag=unbounded allow_future=True on_miss=none", True),
    ("method=asof max_lag=60s allow_future=False on_miss=raise", False),
    ("method=nearest max_lag=60s allow_future=False on_miss=raise", False),
    ("method=asof max_lag=7200s allow_future=False on_miss=raise", True),
]
ok = True
for pol, want in cases:
    got = health.is_overnight_hole(pol)
    ok &= (got == want)
    print(f"  {got!s:5}  (want {want!s:5})  {pol}")
print("VERDICT R10:", "FIXED" if ok else "NOT FIXED")

hdr("R10b the PRODUCTION policy strings, not hand-written ones")
from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy, select_snapshot
strict = snapshot.policy_for("USD-SOFR-1D", pd.Timestamp("2026-06-10T14:00Z"))
night = snapshot.policy_for("USD-SOFR-1D", pd.Timestamp("2026-06-10T05:30Z"))
legacy = SnapshotPolicy.legacy()
for nm, pol in (("in-session", strict), ("out-of-session", night),
                ("legacy", legacy)):
    d = pol.describe()
    print(f"  {nm:16} {d!r} -> hole={health.is_overnight_hole(d)}")
prod_ok = (health.is_overnight_hole(strict.describe()) is False
           and health.is_overnight_hole(night.describe()) is True
           and health.is_overnight_hole(legacy.describe()) is True)
print("VERDICT R10b (no regression on real strings):",
      "OK" if prod_ok else "REGRESSION")

hdr("R10c the docstring's select_snapshot claim, measured")
want_ns = pd.Timestamp("2026-06-10T14:00:00Z").value
stamps = np.array([pd.Timestamp("2026-06-10T13:59:30Z").value,   # 30s before
                   pd.Timestamp("2026-06-10T14:00:05Z").value])  # 5s after
p_asof = SnapshotPolicy(method="asof", max_lag=datetime.timedelta(seconds=60),
                        allow_future=False, on_miss="raise")
p_near = SnapshotPolicy(method="nearest", max_lag=datetime.timedelta(seconds=60),
                        allow_future=False, on_miss="raise")
sa = select_snapshot(stamps, want_ns, p_asof)
sn = select_snapshot(stamps, want_ns, p_near)
print("  asof    ->", None if sa is None else f"pos={sa.position} lag={sa.lag_seconds}s")
print("  nearest ->", None if sn is None else f"pos={sn.position} lag={sn.lag_seconds}s")
print("VERDICT R10c (nearest rejects rather than falls back):",
      "CLAIM HOLDS" if (sa is not None and sa.position == 0 and sn is None)
      else "CLAIM FALSE -> method= should be in the test")

# ---------------------------------------------------------------- R11
hdr("R11 provenance.build on a renamed UnitPricing")


class RenamedPricing:
    unit_key = "U"
    curve_name = "USD-SOFR-1D"
    curve_timestamp = pd.Timestamp("2026-06-10T13:59:00Z")
    lag_seconds = 41.0            # was snapshot_lag_seconds
    policy = "method=asof max_lag=60s allow_future=False on_miss=raise"


e, r = raises(provenance.build, unit("U"), RenamedPricing(), call("U"),
              pricing_clock_field="execution_timestamp")
print("->", type(e).__name__ if e else
      f"snapshot_policy={r.snapshot_policy!r} lag={r.snapshot_lag_seconds}")
print("  msg:", str(e)[:150] if e else "")
# each field renamed on its own
for f in ("curve_name", "curve_timestamp", "snapshot_lag_seconds",
          "snapshot_policy"):
    obj = type("P", (), {k: getattr(RenamedPricing, k, None)
                         for k in ("curve_name", "curve_timestamp")})()
    obj.curve_name = "C"
    obj.curve_timestamp = pd.Timestamp("2026-06-10T13:59:00Z")
    obj.snapshot_lag_seconds = 41.0
    obj.snapshot_policy = "method=asof max_lag=60s allow_future=False on_miss=raise"
    delattr(type(obj), f) if hasattr(type(obj), f) else None
    obj.__dict__.pop(f, None)
    ee, _ = raises(provenance.build, unit("U"), obj, call("U"),
                   pricing_clock_field="execution_timestamp")
    print(f"  drop {f:22} -> {type(ee).__name__ if ee else 'SILENT SENTINEL'}")
# a priced unit with an empty policy
priced_blank = T.UnitPricing(
    unit_key="U", curve_name="USD-SOFR-1D",
    curve_timestamp=pd.Timestamp("2026-06-10T13:59:00Z"),
    snapshot_lag_seconds=41.0, snapshot_policy="",
    leg_mid_pct=[3.94], leg_pv01=[4500.0], structure_dv01=4500.0)
e2, _ = raises(provenance.build, unit("U"), priced_blank, call("U"),
               pricing_clock_field="execution_timestamp")
print("  priced with snapshot_policy='' ->", type(e2).__name__, str(e2)[:80])
# and pricing=None still works: that is the whole reason the sentinels exist
p_none = provenance.build(unit("U"), None, call("U"),
                          pricing_clock_field="execution_timestamp")
print("  pricing=None still builds:", repr(p_none.snapshot_policy),
      p_none.snapshot_lag_seconds)
print("VERDICT R11:", "FIXED" if (isinstance(e, ValueError)
                                  and isinstance(e2, ValueError)) else "NOT FIXED")
