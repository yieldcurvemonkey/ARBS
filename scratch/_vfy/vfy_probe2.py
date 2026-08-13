"""Second probe set: the R10b re-do on a genuinely out-of-session instant,
the section-C rationale claims, the section-G minors, and new-defect probes
against the code the fix introduced."""
import datetime
import inspect

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import health, ladder, provenance, snapshot
from SDRUtils.dealer_direction import types as T


def hdr(n):
    print("\n" + "=" * 74 + f"\n{n}\n" + "=" * 74)


def raises(fn, *a, **k):
    try:
        return None, fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return e, None


hdr("R10b REDO -- pick instants by what in_session() actually says")
for label, ts in [("10:00 ET Tue", pd.Timestamp("2026-06-09T14:00Z")),
                  ("00:30 ET", pd.Timestamp("2026-06-09T04:30Z")),
                  ("23:30 ET", pd.Timestamp("2026-06-10T03:30Z")),
                  ("19:33 ET", pd.Timestamp("2026-06-09T23:33Z"))]:
    ins = snapshot.in_session("USD-SOFR-1D", ts)
    pol = snapshot.policy_for("USD-SOFR-1D", ts)
    d = pol.describe()
    hole = health.is_overnight_hole(d)
    flag = "OK" if hole == (not ins) else "MISMATCH"
    print(f"  {label:14} in_session={ins!s:5} hole={hole!s:5} {flag:9} {d}")
print("expectation: hole is the complement of in_session on the real policies")

hdr("SECTION C -- the rationale numbers, read off the live objects")
r_over = health._overnight_threshold().rationale
print("overnight rationale has 161:", "161" in r_over, " has 128:", "128" in r_over)
lag_rats = {}
prov = pd.DataFrame({"unit_key": ["A"],
                     "snapshot_policy": ["method=asof max_lag=7200s "
                                         "allow_future=False on_miss=raise"],
                     "snapshot_lag_seconds": [60.0]})
for m in health.snapshot_lag_metrics(prov):
    lag_rats[m.name] = m.threshold.rationale
p90 = lag_rats.get("overnight_hole_lag_p90_seconds", "")
print("hour-00 rationale says 7/7:", "7/7" in p90,
      " still claims a population:", "population is served" in p90)
imp_doc = inspect.getdoc(health.imputed_notional_fraction) or ""
print("imputed docstring band 1.55-3.57:", "1.55-3.57" in imp_doc,
      " old 1.7-3.6 gone:", "1.7-3.6" not in imp_doc)
roll_doc = inspect.getdoc(health.rolling_recycling_kappa) or ""
print("rolling docstring: 90.7% now attributed to 63 days:",
      "90.7% is the figure for 63 days" in roll_doc)
kap_doc = inspect.getdoc(health._kappa) or ""
print("_kappa docstring drops the false 'chance rate 1' claim:",
      "does not\nneed the chance rate to reach 1" in kap_doc.replace("**", "")
      or "does not need the chance rate to reach 1" in " ".join(kap_doc.split()))
print("-- and the same 128 elsewhere in the tree (scope check) --")
sess_doc = inspect.getdoc(snapshot.policy_for) or ""
print("snapshot.policy_for STILL says '128 such SOFR days':",
      "128 such SOFR days" in sess_doc)

hdr("SECTION G minors -- were they fixed?")
e, r = raises(provenance.annuity_dv01_proxy, notional=1e8, tenor_years=10.0,
              flat_rate=0.0)
print("G4 annuity_dv01_proxy(flat_rate=0) ->",
      f"{type(e).__name__}: {e}" if e else f"{r:,.1f}  (limit A(x)->x)")
s = pd.Series([1.0, -1.0], index=pd.Index(pd.date_range("2026-01-01", periods=2).date))
e, r = raises(health.rolling_recycling_kappa, s, s, n_bootstrap=10)
print("G5 rolling_recycling_kappa(n_bootstrap=10) ->",
      f"{type(e).__name__}: {str(e)[:80]}" if e else "accepted")
src = inspect.getsource(health.rolling_recycling_kappa)
print("G6 _align_daily result still only length-tested:",
      "x, _y = _align_daily(d2c, d2d)" in src)

hdr("NEW-DEFECT PROBE 1 -- merge_ladder_exclusions with two reasons for one unit")
prov1 = pd.DataFrame([{"unit_key": "A", "failure_reason": None}])
two = pd.DataFrame([{"unit_key": "A", "failure_reason": T.EXCL_DEAD_ZONE},
                    {"unit_key": "A", "failure_reason": T.EXCL_PRICING_ERROR}])
e, out = raises(provenance.merge_ladder_exclusions, prov1, two)
print("->", f"{type(e).__name__}: {str(e)[:90]}" if e
      else f"SILENT, kept {list(out['failure_reason'])} (dict(zip) keeps the LAST)")

hdr("NEW-DEFECT PROBE 2 -- coverage_table on an empty population")
e, out = raises(provenance.coverage_table, pd.DataFrame(columns=["unit_key",
                                                                 "failure_reason"]),
                dv01=pd.Series(dtype="float64"),
                ladder_excluded=pd.DataFrame(columns=ladder.EXCLUSION_COLUMNS))
print("empty prov + empty excl ->", "empty frame" if e is None else f"{type(e).__name__}: {e}")
e, out = raises(provenance.coverage_table, pd.DataFrame(columns=["unit_key",
                                                                 "failure_reason"]),
                dv01=pd.Series(dtype="float64"),
                ladder_excluded=pd.DataFrame([{"unit_key": "A",
                                               "failure_reason": T.EXCL_DEAD_ZONE}]))
print("empty prov + NON-empty excl ->",
      f"{type(e).__name__}: {str(e)[:80]}" if e else "SILENTLY returns an empty table")

hdr("NEW-DEFECT PROBE 3 -- does the orphan guard break the drop_dead_zone path?")
import SDRUtils.dealer_direction.conventions as conv
CL = T.Clocks(pricing=pd.Timestamp("2026-06-10T14:00Z"),
              execution=pd.Timestamp("2026-06-10T14:00Z"),
              event=pd.Timestamp("2026-06-10T14:00Z"),
              visibility=pd.Timestamp("2026-06-10T15:00Z"),
              visibility_source="APPENDIX_C_ESTIMATE")


def U(k):
    return T.Unit(unit_key=k, kind=conv.OUTRIGHT,
                  legs=pd.DataFrame({"trade_id": ["t"]}), package_id=None,
                  rate_index="SOFR", as_of_date=datetime.date(2026, 6, 10),
                  venue_class=T.VENUE_D2C, clocks=CL)


def C(k, p, dz=False):
    return T.DirectionCall(unit_key=k, rule=conv.RULE_RATE, deviation_bps=0.1,
                           p=p, signed_weight=conv.signed_weight(p),
                           dealer_sign=1 if p >= 0.5 else -1, in_dead_zone=dz)


k = pd.DataFrame([{"unit_key": x, "bucket_space": "IRS_KRD", "bucket_key": "5Y",
                   "dv01_if_received": 1000.0} for x in ("A", "B")])
rows, excl = ladder.unit_ladder_rows([U("A"), U("B")], [C("A", 0.9), C("B", 0.52, True)],
                                     k, drop_dead_zone=True)
print("drop_dead_zone still works: rows=", list(rows["unit_key"]),
      " excluded=", list(zip(excl["unit_key"], excl["failure_reason"])))
tab = provenance.coverage_table(
    pd.DataFrame([{"unit_key": "A", "failure_reason": None},
                  {"unit_key": "B", "failure_reason": None}]),
    dv01=pd.Series({"A": 1000.0, "B": 1000.0}),
    ladder_excluded=excl).set_index("reason")
print("and DEAD_ZONE now reaches the coverage table:", list(tab.index))

hdr("NEW-DEFECT PROBE 4 -- does degenerate=True over-fire on ordinary data?")
rng = np.random.default_rng(11)
n = 300
ix = pd.Index(pd.date_range("2026-01-01", periods=n).date)
x = np.where(rng.random(n) < 0.6, 1.0, -1.0)
y = np.where(rng.random(n) < 0.55, 1.0, -1.0)
res = health.d2d_recycling_kappa(pd.Series(x, index=ix),
                                 pd.Series(y, index=ix), n_bootstrap=0)
print("balanced-ish 60/55 -> degenerate:", res.degenerate, " status:", res.status)
allpos = pd.Series(np.ones(n), index=ix)
res2 = health.d2d_recycling_kappa(allpos, pd.Series(y, index=ix), n_bootstrap=0)
print("one side all +1     -> degenerate:", res2.degenerate,
      " chance:", round(res2.chance_rate, 3), " kappa:", round(res2.kappa, 6),
      " status:", res2.status)
print("(the review's C-5: single-degenerate used to report WARN, not ALARM)")
