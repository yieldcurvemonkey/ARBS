"""What does FedInvest's own quoted bid/offer imply, in BASIS POINTS of yield?

The GSS cost table is a "transparent default" — the source's calibrated one did not survive — and
it is the binding constraint on the whole strategy (costs 4.5x gross, m* ~ 0.21). FedInvest
publishes an actual bid and offer per bond, so the assumption is checkable: price the bid and the
offer to yield and read the half-spread straight off the wire.
"""
import os, sys, io, logging, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-rvx")
import numpy as np, pandas as pd, QuantLib as ql
logging.basicConfig(level=logging.ERROR)
from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher
from BT.gss_fly.data import LocalReferenceProvider
from BT.gss_fly.config import CostConfig

dates = [datetime.datetime(2025, m, d) for m, d in
         [(1,15),(3,19),(5,21),(7,16),(9,17),(10,15)]]
fi, prov = FedInvestDataFetcher(), LocalReferenceProvider()
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
dc = ql.ActualActual(ql.ActualActual.Bond)

def to_yield(price, cpn, mat, asof):
    try:
        a = ql.Date(asof.day, asof.month, asof.year)
        ql.Settings.instance().evaluationDate = a
        m = ql.Date(mat.day, mat.month, mat.year)
        if m <= a:
            return np.nan
        sched = ql.Schedule(a, m, ql.Period(ql.Semiannual), cal, ql.Unadjusted, ql.Unadjusted,
                            ql.DateGeneration.Backward, False)
        b = ql.FixedRateBond(1, 100.0, sched, [float(cpn) / 100.0], dc)
        return b.bondYield(ql.BondPrice(float(price), ql.BondPrice.Clean), dc, ql.Compounded, ql.Semiannual, a) * 1e4
    except Exception:
        return np.nan

rows = []
for dt in dates:
    df = fi.runner(dates=[dt]).get(dt)
    if df is None or df.empty:
        continue
    ref = prov(dt.date())[["cusip", "rank", "maturity_date"]]
    m = df.merge(ref, on="cusip", how="inner")
    m = m[m["type"].str.contains("NOTE|BOND", case=False, na=False)]
    for c in ("bid_price", "offer_price"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m = m[(m.bid_price > 50) & (m.offer_price > 50)].copy()
    m["asof"] = dt.date()
    rows.append(m)
A = pd.concat(rows, ignore_index=True)


A["y_bid"] = [to_yield(p, c, pd.Timestamp(mt).date(), a)
              for p, c, mt, a in zip(A.bid_price, A.coupon, A.maturity_date, A["asof"])]
A["y_off"] = [to_yield(p, c, pd.Timestamp(mt).date(), a)
              for p, c, mt, a in zip(A.offer_price, A.coupon, A.maturity_date, A["asof"])]
A["spread_bp"] = (A.y_bid - A.y_off).abs()          # bid price low -> yield high
A["half_bp"] = A.spread_bp / 2.0
A["ttm"] = (pd.to_datetime(A.maturity_date) - pd.to_datetime(A["asof"])).dt.days / 365.25
A = A[np.isfinite(A.half_bp) & (A.half_bp < 20)]

print(f"COST: {len(A)} quotes, {A.cusip.nunique()} bonds, {A["asof"].nunique()} dates", flush=True)
edges = sorted(CostConfig().half_spread_bp)
tbl = CostConfig().half_spread_bp
A["bucket"] = pd.cut(A.ttm, edges + [100], right=False,
                     labels=[f"{e:g}y+" for e in edges])
g = A.groupby("bucket", observed=True)["half_bp"].agg(["count", "median", "mean",
                                                       lambda s: s.quantile(.75),
                                                       lambda s: s.quantile(.95)])
g.columns = ["n", "median", "mean", "p75", "p95"]
g["GSS_assumed"] = [tbl[e] for e in edges if f"{e:g}y+" in g.index]
g["ratio_med"] = g["median"] / g["GSS_assumed"]
print("\n=== ONE-WAY half-spread in bp of yield, measured vs the GSS table ===", flush=True)
print(g.to_string(float_format=lambda v: f"{v:.3f}"), flush=True)
print(f"\nCOST: overall median half-spread {A.half_bp.median():.3f}bp   "
      f"assumed table spans {min(tbl.values()):.2f}-{max(tbl.values()):.2f}bp", flush=True)
# what the fly actually costs, weighted like a GSS fly (|w| sums to 2)
print(f"COST: a 3-leg fly at |w| sum 2 -> round trip ~= 4 x half-spread "
      f"= {4*A.half_bp.median():.2f}bp measured", flush=True)
print("COSTDONE", flush=True)
