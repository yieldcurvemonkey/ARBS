"""Is the 1.55 bp intraday richness residual a real level, or Citi quote noise?

It is 3.6x the 0.434 bp the daily FedInvest study measured on the same kind of
cross-section, and a bigger number is exactly what a hopeful reading wants, so it
has to be tested rather than banked. The repo's own ``residual_quality`` states
the discriminator: a genuine per-bond richness residual runs 0.85-0.99 lag-1
autocorrelation, because a bond does not become cheap and rich again overnight.
Near zero means pricing noise, and a mean-reversion signal fitted to noise
reverts beautifully in sample and pays the spread out of sample.
"""

import pathlib

import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402
from RVUtils.ETFRebalance.curve import fit_residuals, residual_quality  # noqa: E402

uni = pd.read_csv(DATA / "intraday_universe.csv")
uni["maturity_date"] = pd.to_datetime(uni["maturity_date"])
meta = uni.rename(columns={"coupon": "cpn"})[["isin", "cusip", "maturity_date", "cpn"]]

q = CitiVeloQuotes(offline=True)
frame = q.frame([f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)], "HOURLY")
frame = frame[frame.index >= "2021-01-01"]
idx = pd.Series(frame.index)
sub = frame[(idx.dt.hour == 15).to_numpy()]          # the 16:00 New York mark
sub = sub[~pd.Series(sub.index).dt.normalize().duplicated(keep="last").to_numpy()]
long = sub.stack().rename("ytm").reset_index()
long.columns = ["stamp", "tag", "ytm"]
long["isin"] = long["tag"].str.split(".").str[2]
long = long.merge(meta, on="isin", how="left")
long["date"] = pd.to_datetime(long["stamp"]).dt.normalize()
long["ttm"] = (long["maturity_date"] - long["stamp"]).dt.days / 365.25
long = long[(long["ttm"] > 0) & long["ytm"].notna() & long["cpn"].notna()]
long = long[long.groupby("date")["cusip"].transform("size") >= 20]

r = fit_residuals(long, deg=3, x_axis="ttm", include_coupon=True, robust=True, y_col="ytm")
qual = residual_quality(r)
pd.set_option("display.width", 200)
print(f"{len(qual)} bonds with a residual series at the 16:00 New York mark")
print(qual.describe().round(4).to_string())
print("\nlag-1 autocorrelation: median %.3f, 10th pct %.3f, 90th pct %.3f"
      % (qual["autocorr_1"].median(), qual["autocorr_1"].quantile(0.1),
         qual["autocorr_1"].quantile(0.9)))
print("per-bond residual SD: median %.3f bp" % qual["sd_bp"].median())
verdict = ("REAL persistent richness (the repo's own band for a genuine series is 0.85-0.99)"
           if qual["autocorr_1"].median() >= 0.85 else
           "NOISE-dominated - the level cannot be traded and the dispersion is not a pond")
print("VERDICT:", verdict)
qual.to_csv(DATA / "intraday_residual_quality.csv")
print("wrote intraday_residual_quality.csv")
