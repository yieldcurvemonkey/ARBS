"""Step 1: build the deletion / placebo / addition calendars from reference data alone,
and verify the deletion rule against TLT/TLH holdings.

No holdings are used to PREDICT anything here -- only reference data (issue_date,
maturity_date) which is known at issuance, years before any crossing. Holdings are used
only to check that the predicted date actually matches an observed flow.
"""
from __future__ import annotations

import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import float_panel as FP
from RVUtils.ETFRebalance import holdings_panel as HP
from MDP.ETFHoldings.universe import ISHARES

OUT = BP.panel_dir()


def month_end_trading_dates(panel_dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(panel_dates, index=panel_dates)
    me = s.groupby(s.dt.to_period("M")).max()
    return pd.DatetimeIndex(sorted(me.values))


def build_crossing_calendar(ref: pd.DataFrame, month_ends: pd.DatetimeIndex,
                            band: float) -> pd.DataFrame:
    """First month-end at which ttm crosses BELOW ``band``, requiring a prior month-end
    >= band to exist (so a bond issued already below band -- e.g. a fresh 20y original
    issue -- does not register as a phantom 'deletion': it was never in the fund).
    """
    rows = []
    me_arr = month_ends.values
    for r in ref.itertuples():
        iss, mat = r.issue_date, r.maturity_date
        if pd.isna(iss) or pd.isna(mat):
            continue
        mask = me_arr >= np.datetime64(iss)
        me_b = me_arr[mask]
        if len(me_b) < 2:
            continue
        ttm = (np.datetime64(mat) - me_b) / np.timedelta64(1, "D") / 365.25
        below = ttm < band
        cross_idx = None
        for i in range(1, len(below)):
            if below[i] and not below[i - 1]:
                cross_idx = i
                break
        if cross_idx is None:
            continue
        rows.append({
            "cusip": r.cusip, "issue_date": iss, "maturity_date": mat,
            "cpn": r.cpn, "oi": r.oi,
            "event_date": pd.Timestamp(me_b[cross_idx]),
            "ttm_at_event": ttm[cross_idx],
            "ttm_prior_month_end": ttm[cross_idx - 1],
        })
    return pd.DataFrame(rows)


def build_addition_calendar(ref: pd.DataFrame, month_ends: pd.DatetimeIndex,
                            oi_label: str = "30-Year") -> pd.DataFrame:
    """First month-end >= issue_date for genuinely NEW original-issue CUSIPs of a given
    tenor. One-sided (no pre-issue price history); labelled as auction-cycle measurement
    per the task's own caution about conflating deletion vs OTR/auction effects.
    """
    me_arr = month_ends.values
    sub = ref[ref["oi"].astype(str) == oi_label]
    rows = []
    for r in sub.itertuples():
        iss = r.issue_date
        if pd.isna(iss):
            continue
        mask = me_arr >= np.datetime64(iss)
        me_b = me_arr[mask]
        if len(me_b) < 1:
            continue
        rows.append({
            "cusip": r.cusip, "issue_date": iss, "maturity_date": r.maturity_date,
            "cpn": r.cpn, "oi": r.oi, "event_date": pd.Timestamp(me_b[0]),
        })
    return pd.DataFrame(rows)


def main():
    print("loading panel + reference...", flush=True)
    panel = BP.load()
    ref = BP.reference_frame()
    panel_dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    print(f"panel: {len(panel):,} rows, {len(panel_dates):,} dates "
          f"{panel_dates.min().date()} .. {panel_dates.max().date()}", flush=True)

    month_ends = month_end_trading_dates(panel_dates)
    print(f"month-end trading dates: {len(month_ends)}  "
          f"{month_ends.min().date()} .. {month_ends.max().date()}", flush=True)

    # buffer so a +/-60 business-day event window fits fully inside the panel
    buf_lo = panel_dates[60]
    buf_hi = panel_dates[-61]

    print("\n=== deletion calendar (20y band, TLT -> TLH) ===", flush=True)
    del20 = build_crossing_calendar(ref, month_ends, band=20.0)
    del20["usable_window"] = del20["event_date"].between(buf_lo, buf_hi)
    print(f"total crossing events found: {len(del20)}", flush=True)
    print(f"usable (+/-60bd window fits in panel): {del20['usable_window'].sum()}", flush=True)
    print(del20.sort_values("event_date")[["cusip", "oi", "issue_date", "maturity_date",
                                           "event_date", "ttm_prior_month_end", "ttm_at_event"]]
          .to_string(index=False), flush=True)
    del20.to_csv(OUT / "delcliff_deletion_calendar_20y.csv", index=False)

    print("\n=== placebo calendar (10y band, TLH -> IEF) ===", flush=True)
    del10 = build_crossing_calendar(ref, month_ends, band=10.0)
    del10["usable_window"] = del10["event_date"].between(buf_lo, buf_hi)
    print(f"total crossing events found: {len(del10)}", flush=True)
    print(f"usable: {del10['usable_window'].sum()}", flush=True)
    del10.to_csv(OUT / "delcliff_placebo_calendar_10y.csv", index=False)

    print("\n=== addition calendar (new 30y original issues -> TLT) ===", flush=True)
    add30 = build_addition_calendar(ref, month_ends, oi_label="30-Year")
    add30["usable_window"] = add30["event_date"] <= buf_hi
    print(f"total new-30y events: {len(add30)}, usable (+60bd fits): {add30['usable_window'].sum()}",
          flush=True)
    add30.to_csv(OUT / "delcliff_addition_calendar_30y.csv", index=False)

    # ------------------------------------------------------------------ holdings check
    print("\n=== verifying the 20y deletion rule against TLT/TLH holdings ===", flush=True)
    joined = HP.build(["TLT", "TLH"], panel=panel)
    floats = FP.load()

    # sanity: units. TLT total par should be O($40-50bn).
    tlt_par_by_date = joined[joined["ticker"] == "TLT"].groupby("date")["par"].sum()
    print(f"TLT total par, last date: ${tlt_par_by_date.iloc[-1]/1e9:.2f}bn "
          f"(sanity: should be ~$40-50bn)", flush=True)
    tlh_par_by_date = joined[joined["ticker"] == "TLH"].groupby("date")["par"].sum()
    print(f"TLH total par, last date: ${tlh_par_by_date.iloc[-1]/1e9:.2f}bn "
          f"(sanity: should be ~$10-12bn)", flush=True)

    hold_lo, hold_hi = joined["date"].min(), joined["date"].max()
    check = del20[del20["event_date"].between(hold_lo + pd.Timedelta(days=45),
                                               hold_hi - pd.Timedelta(days=45))].copy()
    print(f"\n{len(check)} deletion events fall inside holdings coverage "
          f"(with +/-45cd margin)", flush=True)

    ffl = floats.set_index(["cusip"]).sort_index()

    verify_rows = []
    for r in check.itertuples():
        ed = r.event_date
        pre_lo, pre_hi = ed - pd.Timedelta(days=17), ed - pd.Timedelta(days=3)
        post_lo, post_hi = ed + pd.Timedelta(days=3), ed + pd.Timedelta(days=17)

        def par_window(ticker, lo, hi):
            g = joined[(joined["ticker"] == ticker) & (joined["cusip"] == r.cusip)
                       & joined["date"].between(lo, hi)]
            return g["par"].mean() if not g.empty else np.nan

        tlt_pre = par_window("TLT", pre_lo, pre_hi)
        tlt_post = par_window("TLT", post_lo, post_hi)
        tlh_pre = par_window("TLH", pre_lo, pre_hi)
        tlh_post = par_window("TLH", post_lo, post_hi)

        f = floats[(floats["cusip"] == r.cusip) & (floats["asof"] <= ed)]
        free_float = f.sort_values("asof")["free_float"].iloc[-1] if not f.empty else np.nan

        verify_rows.append({
            "cusip": r.cusip, "event_date": ed,
            "tlt_par_pre": tlt_pre, "tlt_par_post": tlt_post,
            "tlt_par_sold": tlt_pre - tlt_post,
            "tlh_par_pre": tlh_pre, "tlh_par_post": tlh_post,
            "tlh_par_bought": tlh_post - tlh_pre,
            "free_float": free_float,
            "tlt_sold_pct_of_pre": (tlt_pre - tlt_post) / tlt_pre if tlt_pre else np.nan,
            "net_flow_pct_free_float": (
                ((tlt_pre - tlt_post) - (tlh_post - tlh_pre)) / free_float
                if free_float else np.nan
            ),
        })
    verify = pd.DataFrame(verify_rows)
    verify.to_csv(OUT / "delcliff_holdings_verification.csv", index=False)

    print(verify.to_string(index=False), flush=True)
    print("\nsummary:", flush=True)
    print(verify[["tlt_par_pre", "tlt_par_post", "tlt_sold_pct_of_pre",
                  "tlh_par_pre", "tlh_par_post", "net_flow_pct_free_float"]]
          .describe().to_string(), flush=True)

    print("\nwrote:")
    for f in ["delcliff_deletion_calendar_20y.csv", "delcliff_placebo_calendar_10y.csv",
              "delcliff_addition_calendar_30y.csv", "delcliff_holdings_verification.csv"]:
        print(f"  {OUT / f}")


if __name__ == "__main__":
    main()
