"""Probe 13: (a) fully-offline synthetic curve through build_delta_risk_ladder,
(b) the 00:xx ET block anchor / midnight trap, (c) FED_FUNDS par sanity vs EFFR."""
import os, sys, time, datetime
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl, pytz
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder

pd.set_option("display.width", 240)
NY = pytz.timezone("America/New_York")
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]

# ---------------- (a) offline synthetic curve ----------------
REF = rl.dt(2026, 6, 16)
ZERO = 0.04
nodes = {REF: 1.0}
for yrs in (0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 51):
    d = REF + datetime.timedelta(days=int(yrs * 365))
    nodes[d] = float(np.exp(-ZERO * yrs))
curve = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", modifier="mf",
                 interpolation="log_linear", id="USD-SOFR-1D")
h = RLIRSwapCurve("USD-SOFR-1D", curve, pd.Series(dtype=float),
                  {"requested_curve_name": "USD-SOFR-1D", "timestamp": pd.Timestamp("2026-06-16 12:00"),
                   "id": "USD-SOFR-1D"})
t0 = time.perf_counter()
rc, slv = build_delta_risk_ladder(P28, h, timestamp=pd.Timestamp("2026-06-16 12:00"))
print(f"[offline] built in {(time.perf_counter()-t0)*1000:.0f} ms  "
      f"labels match: {list(slv.instrument_labels) == P28}")
spot = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)


def krd(rcx, eff, mat, notl, frp):
    pkg = IRSwapQuery(curve="USD-SOFR-1D", effective_date=pd.Timestamp(eff).date(),
                      maturity_date=pd.Timestamp(mat).date(),
                      structure_kwargs={"notional": float(notl), "fixed_rate": frp / 100.0},
                      ).resolve_query(pd.Timestamp("2026-06-16 12:00"),
                                      pricer_or_curve=rcx).resolve_package(pricer_or_curve=rcx)[0]
    return rl.Portfolio(pkg).delta(solver=slv).iloc[:, 0]


d = krd(rc, spot, rl.add_tenor(spot, "10Y", "MF", "nyc"), 100e6, 4.0)
print(f"[offline] 10Y payer 100mm: sum={d.sum():,.1f}  "
      f"top={ {str(k[-1]): round(float(v),1) for k, v in d.items() if abs(v) > 50} }")

# affine + grad_s_Ploc equivalence, offline
scal = np.array(slv.pre_rate_scalars) / 100.0
crv = rc.handle()
unit = IRSwapQuery(curve="USD-SOFR-1D", effective_date=pd.Timestamp(spot).date(),
                   maturity_date=pd.Timestamp(rl.add_tenor(spot, "10Y", "MF", "nyc")).date(),
                   structure_kwargs={"notional": 1e6, "fixed_rate": 0.01},
                   ).resolve_query(pd.Timestamp("2026-06-16 12:00"),
                                   pricer_or_curve=rc).resolve_package(pricer_or_curve=rc)[0][0]
ga = np.asarray(slv.grad_s_Ploc(unit.leg1.npv(rate_curve=crv, disc_curve=crv, local=True)["usd"])) * scal
gf = np.asarray(slv.grad_s_Ploc(unit.leg2.npv(rate_curve=crv, disc_curve=crv, local=True)["usd"])) * scal
aff = 100.0 * (gf + 4.0 * ga)
print(f"[offline] affine vs delta max|diff| = {np.abs(aff - d.to_numpy(float)).max():.3e}")

# ---------------- (b) the 00:xx ET block anchor ----------------
from SDRUtils.stir_flow.pricing import as_intraday_instant, is_ambiguous_midnight
for wall in ("00:05", "00:59", "01:00", "13:37"):
    t = NY.localize(datetime.datetime(2026, 6, 16, int(wall[:2]), int(wall[3:])))
    floored = t.replace(minute=0, second=0, microsecond=0)
    print(f"[block] {wall} -> floor {floored}  ambiguous={is_ambiguous_midnight(floored)} "
          f" nudged={as_intraday_instant(floored)}")

# ---------------- (c) FED_FUNDS par sanity ----------------
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy
ts = pd.Timestamp("2026-06-16 11:00", tz=NY)
for idx in ("SOFR", "FED_FUNDS"):
    nm = CURVE_FOR[idx]
    h0 = make_pricer(strict_policy(1.0)).handle(nm, ts)
    meta = dict(h0._meta_data); meta["requested_curve_name"] = nm
    hh = RLIRSwapCurve(h0.id(), h0.handle(), h0.index().iloc[0:0], meta)
    rcx, slvx = build_delta_risk_ladder(["1M", "3M", "1Y", "2Y", "5Y", "10Y", "30Y"], hh, timestamp=ts)
    print(f"[{idx:9s}] par: " + "  ".join(
        f"{lab}={s:.4f}%" for lab, s in zip(slvx.instrument_labels, np.asarray(slvx.s))))
