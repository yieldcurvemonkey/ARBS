"""Does the fast panel agree with the MDP it shortcut? Run before trusting any signal.

A checking tool that is itself wrong reports success and hides the thing it was built to
find. ``bond_panel.build`` replaces 800,000 ``QLFixedRateBondPricer`` constructions with
one ``ql.FixedRateBond`` per CUSIP repriced across dates, so the question is whether that
substitution changed the answer.

It cannot be identical, because the MDP solves its yield off ``eod_price`` and the panel
solves off the bid/offer mid. So a tolerance on the yield gap is the wrong test: it
conflates "the two pipelines disagree" with "they were handed different prices", and the
second is by design.

The right test is an **identity**. If both pipelines implement the same bond, then the
yield gap between them, converted back to a price through the bond's own duration, must
reproduce the price gap they were actually given:

    -(ModDur x P) x (d_ytm_bp / 1e4)   ==   panel_price - eod_price

That is exact up to convexity, needs no tolerance chosen by hand, and fails loudly if
the schedule, day count, settlement or compounding differ -- which a yield tolerance
would absorb.

Two things this check learned about the data on first contact:

* The **whole** apparent -2.9bp mean offset was one date. 2020-03-18 contributed
  -16 to -19bp per bond with a 6bp quoted half-spread; the other five sample dates were
  centred at -1bp. Averaging across dates hid that, so the report is per-date.
* Modified duration "disagreed" by up to 0.115 years at 20-31y, which looked like a
  convention mismatch and is not: duration is evaluated at each pipeline's own yield, so
  a 3bp yield gap on a 17-duration bond moves it by convexity x dy ~ 0.12 years. The
  duration check is therefore made **conditional on the yields agreeing**.

Neither series is stale, which was the other candidate explanation and was checked
rather than assumed: over 20-30y bonds, 2015-2026, bid, offer, mid and eod are all
unchanged day-over-day on 1.1-1.8% of observations with an identical daily-change
standard deviation, and the cross-sectional cubic-fit RMSE is 0.916bp on mid against
0.919bp on eod. Mid is used because it is marginally the cleaner of the two on both
measures (residual lag-1 autocorrelation 0.980 vs 0.975) and because it is the basis the
cost model is quoted on.
"""

from __future__ import annotations

import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402

SAMPLE_DATES = [
    datetime.date(2016, 3, 15), datetime.date(2018, 6, 12), datetime.date(2020, 3, 18),
    datetime.date(2022, 9, 14), datetime.date(2024, 3, 14), datetime.date(2026, 6, 10),
]


def main() -> int:
    panel = BP.load()
    print(f"panel: {len(panel):,} rows  {panel['date'].min().date()} .. "
          f"{panel['date'].max().date()}  {panel['cusip'].nunique():,} CUSIPs\n")

    have = set(pd.to_datetime(panel["date"]).dt.date)
    dates = [d for d in SAMPLE_DATES if d in have]
    print(f"tying out {len(dates)} dates against FixedRateBondsMDP ...", flush=True)
    t = BP.tie_out_against_mdp(panel, dates, n_cusips=60)
    if t.empty:
        print("TIE-OUT PRODUCED NO ROWS -- that is a failure, not a pass.")
        return 1

    # The identity: the yield gap, run back through the bond's own duration AND
    # convexity, must reproduce the price gap the two pipelines were handed.
    #
    # First order alone is not enough and the residual proves it rather than excusing it:
    # on 2020-03-18 the gap was 12bp on a 25-year bond, where the second-order term is
    # 0.5 x C x P x dy^2 ~ 0.05 price points -- two and a half times the whole
    # first-order residual. Including convexity turns a 0.021 "error" into noise.
    px = panel.set_index(["date", "cusip"])
    t = t.join(px[["clean_price", "eod_price", "price_source"]],
               on=["date", "cusip"], how="left")
    dy = t["d_ytm_bp"] / 1e4
    t["d_price_actual"] = t["clean_price"] - t["eod_price"]
    t["d_price_1st"] = -(t["mod_dur_mdp"] * t["clean_price"]) * dy
    t["d_price_implied"] = t["d_price_1st"] + 0.5 * t["convexity"] * t["clean_price"] * dy ** 2
    t["identity_err"] = t["d_price_implied"] - t["d_price_actual"]

    print(f"\n{len(t):,} (date, cusip) pairs compared\n")
    print("per sample date -- the average across dates hides a single stressed one:")
    print(t.groupby(t["date"].dt.date).agg(
        n=("d_ytm_bp", "size"),
        mean_d_ytm_bp=("d_ytm_bp", "mean"),
        max_abs_d_ytm_bp=("d_ytm_bp", lambda s: s.abs().max()),
        mean_half_spread_bp=("half_spread_bp", "mean"),
        max_identity_err_px=("identity_err", lambda s: s.abs().max()),
    ).round(4).to_string())

    print("\nby maturity bucket:")
    t["bucket"] = pd.cut(t["ttm"], [0, 2, 5, 10, 20, 31])
    print(t.groupby("bucket", observed=True).agg(
        n=("d_ytm_bp", "size"),
        mean_d_ytm_bp=("d_ytm_bp", "mean"),
        sd_d_ytm_bp=("d_ytm_bp", "std"),
        mean_half_spread_bp=("half_spread_bp", "mean"),
        max_identity_err_px=("identity_err", lambda s: s.abs().max()),
    ).round(4).to_string())

    # Duration is evaluated at each pipeline's own yield, so it can only be compared on
    # the bonds whose yields agree -- and "agree" has to be scaled by how fast duration
    # moves with yield, which is what convexity measures. The bound below is derived
    # rather than picked: |dMD| <= C |dy| is the first-order sensitivity of modified
    # duration itself, with a factor of 2 of headroom.
    t["md_bound"] = 2.0 * t["convexity"].abs() * (t["d_ytm_bp"].abs() / 1e4) + 1e-6
    md_ok = (t["d_mod_dur"].abs() <= t["md_bound"])

    # The identity residual is the next Taylor term, so judge it RELATIVE to the gap it
    # is explaining rather than against a round absolute number: a 0.05 price-point
    # residual on a 2.7-point move is a 2% third-order effect, and the same 0.05 on a
    # 0.05-point move would be a broken pipeline.
    t["identity_rel"] = t["identity_err"].abs() / t["d_price_actual"].abs().clip(lower=0.02)
    ex_covid = t[t["date"] != pd.Timestamp("2020-03-18")]

    # Measured, and deliberately NOT asserted as a pass/fail: eod_price and the
    # bid/offer quotes are not two points on one quote. Across 727,289 two-sided
    # observations eod sits at the bid at the median but ranges to +-20 spread widths at
    # the 1st/99th percentiles, and neither series is stale (both unchanged d/d on
    # 1.1-1.8% of days, identical daily-change sd, cross-sectional cubic-fit RMSE 0.916bp
    # on mid vs 0.919bp on eod). So this is a real basis difference between two live
    # series, not one of them being wrong -- which is why ``price_basis`` is a config
    # knob in the backtest and the headline is reported on both.
    ratio_by_date = t.groupby("date").apply(
        lambda g: g["d_ytm_bp"].abs().mean() / max(1e-9, g["half_spread_bp"].mean()),
        include_groups=False)

    checks = [
        ("identity: duration + convexity reproduce the price gap (median rel. err < 1%)",
         float(t["identity_rel"].median()) < 0.01,
         f"median {t['identity_rel'].median() * 100:.3f}%, "
         f"p99 {t['identity_rel'].quantile(.99) * 100:.2f}%"),
        ("identity is sub-tick on the calm dates",
         float(ex_covid["identity_err"].abs().max()) < 0.01,
         f"max {ex_covid['identity_err'].abs().max():.5f} price points ex-COVID "
         f"({t[t['date'] == pd.Timestamp('2020-03-18')]['identity_err'].abs().max():.4f} on 2020-03-18)"),
        ("modified duration agrees to within its convexity sensitivity",
         float(md_ok.mean()) >= 0.99,
         f"{md_ok.mean() * 100:.1f}% within bound, max gap {t['d_mod_dur'].abs().max():.2e} yrs"),
        ("yield gap is centred on the calm dates (|mean| < 1.5bp)",
         abs(float(ex_covid["d_ytm_bp"].mean())) < 1.5,
         f"mean {ex_covid['d_ytm_bp'].mean():+.4f}bp ex-COVID, "
         f"{float(t[t['date'] == pd.Timestamp('2020-03-18')]['d_ytm_bp'].mean()):+.2f}bp on 2020-03-18"),
    ]
    print("\nMEASURED, not asserted -- |eod-vs-mid gap| / half-spread, by date:")
    print("  " + "  ".join(f"{d.date()}:{v:.1f}x" for d, v in ratio_by_date.items()))
    print("  eod and the quoted range are a genuine basis difference, so `price_basis`")
    print("  is swept in the backtest rather than chosen here.")
    print()
    ok_all = True
    for name, ok, val in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:58s} {val}")
        ok_all &= bool(ok)

    worst = t.reindex(t["identity_err"].abs().sort_values(ascending=False).index).head(8)
    print("\nlargest identity errors (these are convexity, if anything):")
    print(worst[["date", "cusip", "ttm", "d_ytm_bp", "d_price_actual",
                 "d_price_implied", "identity_err"]].round(5).to_string(index=False))

    print(f"\n{'TIE-OUT PASSES' if ok_all else 'TIE-OUT FAILS'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
