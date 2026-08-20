r"""Why FedInvest's daily change is only 0.71-correlated with the market that made it.

All three strike-time readings agree on 11:00-12:00 New York, but they also agree that
only about half of FedInvest's daily level change is explained by Citi's path
(regression R2 0.52, peak daily correlation 0.71, fitted slope 0.94-0.96). The slope near
one says FedInvest is not mis-scaled; the correlation says it carries extra variance. A
wrong-root yield would do this, and it was the first suspect -- but the gate flags
**0 of 157,887** rows on this universe, so that is measured out.

The remaining candidate that fits a slope of one, a correlation of 0.7, and a clean
cross-section is STALENESS: a file that repeats a bond's price on some days posts a zero
change and then a double change, which inflates the variance of the daily change and puts
NEGATIVE autocorrelation into it, without biasing its level or disturbing the
cross-section on any single day.

That is a testable prediction, and it is tested here rather than asserted:

* the fraction of bond-days whose FedInvest clean price is EXACTLY the previous business
  day's (and the same for Citi, which bounds how much of it is a real unchanged market);
* the lag-1 autocorrelation of the daily change -- strongly negative for a stale-then-
  catch-up series, near zero for a clean one;
* the ratio of the two sources' daily-change volatility, which staleness inflates.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402

DATA = IP.DATA


def main() -> int:
    pd.set_option("display.width", 220)
    p = IP.load_panel("MI01")
    cus = set(p["cusip"])
    d = BP.load()
    d = d[d["cusip"].isin(cus) & d["ytm"].notna() & d["price_source"].eq("mid")]
    d = d.sort_values(["cusip", "date"])

    g = d.groupby("cusip")
    prev_date, prev_px, prev_y = g["date"].shift(1), g["clean_price"].shift(1), g["ytm"].shift(1)
    has = prev_date.notna()
    gap = np.full(len(d), -1, int)
    gap[has.to_numpy()] = np.busday_count(
        prev_date[has].values.astype("datetime64[D]"),
        d.loc[has.to_numpy(), "date"].values.astype("datetime64[D]"))
    ok = (gap == 1) & has.to_numpy()
    dd = d[ok].copy()
    dd["d_fed_bp"] = (d["ytm"][ok] - prev_y[ok]) * 100.0
    dd["px_unchanged"] = (d["clean_price"][ok] == prev_px[ok])
    dd["bid_unchanged"] = (d["bid_price"][ok] == g["bid_price"].shift(1)[ok])

    print(f"FedInvest, {len(dd):,} consecutive-business-day bond pairs, "
          f"{dd['date'].nunique():,} dates")
    print(f"  clean price EXACTLY unchanged day over day : "
          f"{dd['px_unchanged'].mean()*100:.2f}%")
    print(f"  bid  price EXACTLY unchanged day over day  : "
          f"{dd['bid_unchanged'].mean()*100:.2f}%")
    whole = dd.groupby("date")["px_unchanged"].mean()
    print(f"  whole-file days with >90% prices unchanged : "
          f"{(whole > 0.9).sum():,} of {len(whole):,} ({(whole > 0.9).mean()*100:.2f}%)")

    # the same on Citi, at the strike time we identified, as the market's own baseline
    c = p[p["is_fresh"] & p["mark_time"].eq("12:00")][["date", "cusip", "ytm", "clean_price"]]
    c = c.sort_values(["cusip", "date"])
    gc = c.groupby("cusip")
    pdte, ppx, py = gc["date"].shift(1), gc["clean_price"].shift(1), gc["ytm"].shift(1)
    hasc = pdte.notna()
    gapc = np.full(len(c), -1, int)
    gapc[hasc.to_numpy()] = np.busday_count(
        pdte[hasc].values.astype("datetime64[D]"),
        c.loc[hasc.to_numpy(), "date"].values.astype("datetime64[D]"))
    okc = (gapc == 1) & hasc.to_numpy()
    cc = c[okc].copy()
    cc["d_citi_bp"] = (c["ytm"][okc] - py[okc]) * 100.0
    cc["px_unchanged"] = (c["clean_price"][okc] == ppx[okc])
    print(f"\nCiti at 12:00, {len(cc):,} pairs")
    print(f"  clean price EXACTLY unchanged day over day : "
          f"{cc['px_unchanged'].mean()*100:.2f}%   <- the market's own baseline")

    lf = dd.groupby("date")["d_fed_bp"].mean().sort_index()
    lc = cc.groupby("date")["d_citi_bp"].mean().sort_index()
    idx = lf.index.intersection(lc.index)
    lf, lc = lf.loc[idx], lc.loc[idx]
    rows = [{
        "series": "FedInvest daily level change", "n": int(len(lf)),
        "sd_bp": float(lf.std()), "autocorr_1": float(lf.autocorr(1)),
        "autocorr_2": float(lf.autocorr(2)),
    }, {
        "series": "Citi 12:00 daily level change", "n": int(len(lc)),
        "sd_bp": float(lc.std()), "autocorr_1": float(lc.autocorr(1)),
        "autocorr_2": float(lc.autocorr(2)),
    }]
    q = pd.DataFrame(rows)
    print("\nDAILY LEVEL CHANGE of the 20-31y basket, both sources, same dates:")
    print(q.round(4).to_string(index=False))
    print(f"\n  variance ratio fed/citi : {(lf.std()/lc.std())**2:.3f}")
    print(f"  corr                    : {lf.corr(lc):.4f}")

    # A stale-then-catch-up series has a negative lag-1 autocorrelation in its change.
    # Sum the two-day change instead: staleness cancels over two days, so if the
    # correlation jumps when both sides are aggregated to two days, staleness is the cause.
    f2 = lf.rolling(2).sum().dropna()
    c2 = lc.rolling(2).sum().dropna()
    j = pd.concat([f2, c2], axis=1).dropna()
    f5 = lf.rolling(5).sum().dropna()
    c5 = lc.rolling(5).sum().dropna()
    j5 = pd.concat([f5, c5], axis=1).dropna()
    print(f"\n  corr at 1-day horizon   : {lf.corr(lc):.4f}")
    print(f"  corr at 2-day horizon   : {j.iloc[:, 0].corr(j.iloc[:, 1]):.4f}")
    print(f"  corr at 5-day horizon   : {j5.iloc[:, 0].corr(j5.iloc[:, 1]):.4f}")
    print("  (rising with horizon => the disagreement is TIMING/STALENESS, which "
          "cancels;\n   flat => it is independent noise, which does not)")

    out = pd.DataFrame([{
        "fed_px_unchanged_frac": float(dd["px_unchanged"].mean()),
        "fed_bid_unchanged_frac": float(dd["bid_unchanged"].mean()),
        "citi_px_unchanged_frac": float(cc["px_unchanged"].mean()),
        "fed_level_sd_bp": float(lf.std()), "citi_level_sd_bp": float(lc.std()),
        "fed_level_autocorr1": float(lf.autocorr(1)),
        "citi_level_autocorr1": float(lc.autocorr(1)),
        "corr_1d": float(lf.corr(lc)),
        "corr_2d": float(j.iloc[:, 0].corr(j.iloc[:, 1])),
        "corr_5d": float(j5.iloc[:, 0].corr(j5.iloc[:, 1])),
        "whole_file_stale_days": int((whole > 0.9).sum()),
        "dates": int(len(whole)),
    }])
    out.T.rename(columns={0: "value"}).to_csv(DATA / "ipanel_fedinvest_quality.csv")
    q.to_csv(DATA / "ipanel_fedinvest_quality_series.csv", index=False)
    print("\nwrote ipanel_fedinvest_quality.csv, ipanel_fedinvest_quality_series.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
