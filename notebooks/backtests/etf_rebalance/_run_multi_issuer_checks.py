"""Two checks on the REAL data, not on fixtures.

1. NO LOOKAHEAD: every row the as-of panel serves on date T came from a filing that was
   public on or before T, and the SPTL/VGLT contribution steps ~8 times a year rather than
   daily. The unit test proves the join rule; this proves the rule was applied to the
   actual N-PORT parquets.

2. THE RICHNESS CONTROL: the parent study's central finding was that the raw active-weight
   relationship is BACKWARDS and flips sign once the bond's own richness is controlled for.
   The aggregate signal has to be put through the same control, or a raw IC here is not
   comparable to the parent's numbers.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import aggregate as AG  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 220)
HORIZONS = (5, 10, 21, 42, 63)


def main() -> int:
    panel = FP.asof_join(BP.load(), FP.load())
    uni, funnel = EN.prepare_universe(EN.merge_config({
        "fund": "TLT",
        "universe": {"start": "2016-01-01", "ttm_min": 20.0, "ttm_max": 31.0}}), panel=panel)
    uni = uni[uni["date"] >= pd.Timestamp("2016-01-01")].reset_index(drop=True)
    dates = pd.DatetimeIndex(sorted(uni["date"].unique()))

    print("=" * 96)
    print("1. NO LOOKAHEAD, measured on the real N-PORT parquets")
    print("=" * 96)
    fs = AG.FUND_SETS["coupon_long"]
    obs = AG.load_observations(fs, end=dates.max())
    asof = AG.as_of_panel(obs, dates)

    #: The direct claim: on every panel date, the book being used was already public. Join
    #: the chosen obs_date back to its own available_from and compare.
    heads = (obs.groupby(["ticker", "obs_date"], as_index=False)["available_from"].max())
    chk = asof.merge(heads, on=["ticker", "obs_date"], how="left")
    bad = chk[chk["available_from"] > chk["date"]]
    print(f"  rows served                          {len(chk):,}")
    print(f"  rows whose filing was NOT yet public {len(bad):,}   <- must be 0")
    if len(bad):
        print(bad.head(10).to_string())
        return 1

    for t in ("SPTL", "VGLT"):
        g = asof[asof["ticker"] == t]
        steps = g.groupby("date")["obs_date"].first().drop_duplicates()
        per_year = g.groupby([g["date"].dt.year])["obs_date"].nunique()
        print(f"\n  {t}: {g['obs_date'].nunique()} distinct books over "
              f"{g['date'].nunique():,} panel dates")
        print(f"       distinct books in use per calendar year: "
              + "  ".join(f"{y}={n}" for y, n in per_year.items()))
        print(f"       staleness  median {g['stale_days'].median():.0f}d  "
              f"p90 {g['stale_days'].quantile(0.9):.0f}d  max {g['stale_days'].max()}d")

    #: And the counterfactual: what a panel keyed on the REGULATORY date would have served.
    naive = obs.rename(columns={"obs_date": "d"}).copy()
    naive_pick = pd.merge_asof(
        pd.DataFrame({"date": dates.astype("datetime64[ns]")}),
        (naive[naive["ticker"] == "SPTL"].groupby("d", as_index=False)["par"].sum()
         .rename(columns={"d": "obs_date"}).sort_values("obs_date")
         .assign(obs_date=lambda x: x["obs_date"].astype("datetime64[ns]"))),
        left_on="date", right_on="obs_date", direction="backward").dropna(subset=["obs_date"])
    honest = asof[asof["ticker"] == "SPTL"].groupby("date")["obs_date"].first()
    j = naive_pick.set_index("date")["obs_date"].to_frame("naive").join(
        honest.to_frame("honest"), how="inner").dropna()
    gap = (j["naive"] - j["honest"]).dt.days
    print(f"\n  SPTL: keying on the regulatory date instead would have served a book "
          f"{gap.median():.0f} days\n        NEWER on the median date (max {gap.max()}), "
          f"on {(gap > 0).mean()*100:.1f}% of dates. That is the lookahead.")

    print("\n" + "=" * 96)
    print("2. DOES THE AGGREGATE SURVIVE THE RICHNESS CONTROL?")
    print("=" * 96)
    built = AG.build_ladders(uni, fund_sets=("tlt_only", "coupon_long", "coupon_long_govt"),
                             widths=(0.25, 1.0), combines=("book",), verbose=False)
    U = AG.attach_many(uni, built["specs"])
    U = U[U["date"] >= built["ladder_start"]].reset_index(drop=True)
    U["z_resid"] = SIG.cross_sectional_z(U["resid_bp"], U["date"], robust=True).clip(-5, 5)
    U = IC.forward_residual_return(U, HORIZONS).sort_values(["cusip", "date"])

    cols = [c for c in built["specs"] if "floattwin" not in c]
    for c in cols + ["z_resid"]:
        U[c] = U.groupby("cusip")[c].shift(1)

    rows = []
    for c in cols:
        for h in HORIZONS:
            b_sig, b_ctl = [], []
            for _, g in U.groupby("date", sort=False):
                y = g[f"fwd_{h}"].to_numpy(float)
                X = np.column_stack([g[c].to_numpy(float), g["z_resid"].to_numpy(float)])
                ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
                if ok.sum() < 10:
                    continue
                A = np.column_stack([np.ones(ok.sum()), X[ok]])
                try:
                    beta, *_ = np.linalg.lstsq(A, y[ok], rcond=None)
                except np.linalg.LinAlgError:
                    continue
                b_sig.append(beta[1])
                b_ctl.append(beta[2])
            if len(b_sig) < 30:
                continue
            v = np.array(b_sig)
            rows.append({"signal": c, "horizon": h, "n_dates": len(v),
                         "beta_bp_per_z": float(v.mean()),
                         "t_hac": IC.newey_west_t(v, lags=max(1, h - 1)),
                         "ctrl_beta_bp_per_z": float(np.mean(b_ctl))})
    tab = pd.DataFrame(rows)
    print("\nbivariate beta on the forward richness residual, CONTROLLING for the bond's own")
    print("richness (bp per unit z of the signal):")
    print(tab.pivot_table(index="signal", columns="horizon",
                          values="beta_bp_per_z").round(5).to_string())
    print("\nNewey-West t:")
    print(tab.pivot_table(index="signal", columns="horizon",
                          values="t_hac").round(2).to_string())
    print("\nthe CONTROL's own beta (bp per z), for scale:")
    print(tab.pivot_table(index="signal", columns="horizon",
                          values="ctrl_beta_bp_per_z").round(4).iloc[:1].to_string())
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data",
                       "mi_partial_ic.csv")
    tab.to_csv(out, index=False)
    print("\nwrote mi_partial_ic.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
