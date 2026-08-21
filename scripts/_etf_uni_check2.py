import pandas as pd, datetime
from MDP.ETFHoldings import store as etf_store

pd.set_option("display.width", 200)
h = etf_store.load("TLT", start=datetime.date(2021, 1, 1))
h["CUSIP"] = h["CUSIP"].astype(str).str.upper()
h["Maturity"] = pd.to_datetime(h["Maturity"], errors="coerce")

for d in ("2021-01-04", "2021-06-01", "2022-01-03", "2024-01-02", "2026-08-19"):
    sub = h[h["date"] == pd.Timestamp(d)]
    tsy = sub[sub["Asset Class"] == "Fixed Income"]
    print(f"\n=== {d}: {len(sub)} rows, {len(tsy)} fixed income ===")
    if tsy.empty:
        continue
    print("maturity range:", tsy["Maturity"].min(), "->", tsy["Maturity"].max())
    print("n distinct cusip:", tsy["CUSIP"].nunique())
    print(tsy.sort_values("Maturity")[["CUSIP", "Maturity", "Coupon (%)", "Weight (%)"]]
          .head(6).to_string(index=False))

for c in ("912810QN1", "912810QU5", "912810RM2", "912810RT7"):
    sub = h[h["CUSIP"] == c]
    print(c, "dates:", sub["date"].nunique())

print("\nall distinct TLT fixed-income cusips and their date spans:")
fi = h[h["Asset Class"] == "Fixed Income"]
g = fi.groupby("CUSIP").agg(n=("date", "nunique"), first=("date", "min"), last=("date", "max"),
                            mat=("Maturity", "first"))
print(g.sort_values("mat").to_string())
