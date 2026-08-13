"""Refined: NOTES and BONDS only, split by seasoning. Bills quote differently and polluted T0.

The question is specifically about OFF-THE-RUN coupon Treasuries — the GSS universe excludes
on-the-runs by design. If FedInvest matrix-prices the seasoned issues, THOSE are where the
fingerprints must appear.
"""
import os, sys, io, logging, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-rvx")
import numpy as np, pandas as pd
logging.basicConfig(level=logging.ERROR)
from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher
from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
from BT.gss_fly.data import LocalReferenceProvider

dates = [datetime.datetime(2025, m, d) for m, d in
         [(1,15),(2,19),(3,19),(4,16),(5,21),(6,18),(7,16),(8,20),(9,17),(10,15)]]
fi = FedInvestDataFetcher()
prov = LocalReferenceProvider()
rows = []
for dt in dates:
    df = fi.runner(dates=[dt]).get(dt)
    if df is None or df.empty:
        continue
    ref = prov(dt.date())[["cusip", "rank", "oi", "issue_date", "maturity_date"]]
    m = df.merge(ref, on="cusip", how="inner")
    m["date"] = dt
    rows.append(m)
A = pd.concat(rows, ignore_index=True)
for c in ("bid_price", "offer_price", "eod_price"):
    A[c] = pd.to_numeric(A[c], errors="coerce")
A = A[A["type"].str.contains("NOTE|BOND", case=False, na=False)].dropna(
    subset=["bid_price", "offer_price", "eod_price"])
A = A[(A.bid_price > 50) & (A.offer_price > 50)]
A["spread32"] = (A.offer_price - A.bid_price) * 32
A["seasoning_d"] = (pd.to_datetime(A.date) - pd.to_datetime(A.issue_date)).dt.days
A["bucket"] = pd.cut(A["rank"], [-1, 0, 2, 6, 999],
                     labels=["OTR (rank 0)", "rank 1-2", "rank 3-6", "deep off-run (7+)"])

print(f"P2: {len(A)} note/bond observations over {A.date.nunique()} dates, "
      f"{A.cusip.nunique()} cusips", flush=True)

def grid_frac(x, denom):
    f = (x * denom) % 1
    return float(((f < 1e-6) | (f > 1 - 1e-6)).mean())

print("\n=== by seasoning bucket ===", flush=True)
out = []
for b, g in A.groupby("bucket", observed=True):
    out.append({
        "bucket": b, "n": len(g), "cusips": g.cusip.nunique(),
        "spread_32nds_med": g.spread32.median(),
        "spread_32nds_p95": g.spread32.quantile(.95),
        "bid_on_1/32": grid_frac(g.bid_price, 32),
        "bid_on_1/64": grid_frac(g.bid_price, 64),
        "eod_on_1/32": grid_frac(g.eod_price, 32),
        "eod_is_mid": float(((g.eod_price - (g.bid_price + g.offer_price) / 2).abs() < 1e-9).mean()),
        "spread_distinct": g.spread32.round(4).nunique(),
    })
print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:.4f}"), flush=True)

print("\n=== spread as a function of maturity — a MODEL would make this deterministic ===", flush=True)
A["ttm"] = (pd.to_datetime(A.maturity_date) - pd.to_datetime(A.date)).dt.days / 365.25
tb = A.groupby(pd.cut(A.ttm, [0, 2, 5, 10, 20, 32]), observed=True)["spread32"].agg(
    ["median", "std", "count"])
print(tb.to_string(), flush=True)
print("\n  A deterministic spread would show std ~ 0 within each maturity bucket.", flush=True)

print("\n=== same bond, does its spread VARY across dates? ===", flush=True)
v = A.groupby("cusip")["spread32"].agg(["nunique", "count", "std"])
v = v[v["count"] >= 5]
print(f"  {len(v)} bonds seen on >=5 dates: median distinct spreads {v['nunique'].median():.1f}, "
      f"median sd {v['std'].median():.4f} (32nds)", flush=True)
print(f"  bonds whose spread NEVER changes: {(v['nunique'] == 1).mean():.3f}", flush=True)
print("P2DONE", flush=True)
