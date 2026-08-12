"""Probe 10: pick the stress days (FOMC + biggest intraday shape break), then test the
per-(rate_index, as_of_date) solver approximation against per-minute solvers."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl
from Caching.curve_store import CurveStore
from Query.IRSwaps._CENTRAL_BANK_DATES import central_bank_date_map

pd.set_option("display.width", 240)
ASSET = "USD-SOFR-1D-CITIVELOEXCELMIN"
LO, HI = datetime.date(2024, 3, 1), datetime.date(2026, 8, 7)

fomc = sorted({d for d, _ in central_bank_date_map("USD-SOFR-1D").values() if LO <= d <= HI})
print(f"FOMC decision dates in the tape window ({len(fomc)}):")
print("  " + ", ".join(str(d) for d in fomc))

store = CurveStore.default()


def day_shape(day):
    """Intraday range of the 2y and 10y continuous zero rate, in bp, from raw nodes."""
    raw = store.read_raw_nodes(ASSET, start=day, end=day)
    if raw is None or len(raw) < 20:
        return None
    out = {}
    for tag, yrs in (("2y", 2.0), ("10y", 10.0), ("30y", 30.0)):
        z = []
        for _, r in raw.iterrows():
            nd = np.array([(pd.Timestamp(d) - pd.Timestamp(r["node_dates"][0])).days
                           for d in r["node_dates"]], float)
            ln = np.log(np.asarray(r["discount_factors"], float))
            t = yrs * 365.0
            z.append(-np.interp(t, nd, ln) / (t / 365.0) * 1e4)
        z = np.array(z)
        out[tag] = z.max() - z.min()
    out["n"] = len(raw)
    return out


cands = list(fomc) + [datetime.date(2025, 4, 4), datetime.date(2025, 4, 7),
                      datetime.date(2025, 4, 9), datetime.date(2024, 8, 5),
                      datetime.date(2026, 3, 16)]
rows = []
for d in cands:
    s = day_shape(d)
    if s:
        rows.append(dict(day=d, is_fomc=d in fomc, **s))
df = pd.DataFrame(rows).sort_values("10y", ascending=False)
print("\nintraday zero-rate range (bp), biggest first:")
print(df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
df.to_csv("C:/Users/chris/clee/ARBS-dd/scratch/ddkrd_shape_days.csv", index=False)
