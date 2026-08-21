"""Daily per-CUSIP UST panel: price, yield, duration, and a MEASURED bid-offer.

Why this exists next to ``FixedRateBondsMDP``
---------------------------------------------
The MDP builds a ``QLFixedRateBondPricer`` object per (date, CUSIP) and caches it. That
is the right shape for a query API and the wrong shape for a 2,700-day x 300-CUSIP
panel: 800,000 pricer constructions, measured at ~33 s per cold date, is a day of wall
clock for numbers that are three QuantLib calls each.

This module goes at the same data by the shorter path -- pull FedInvest's raw daily
price file (the fetcher the MDP itself uses, sharing its disk cache), build **one**
``ql.FixedRateBond`` per CUSIP, and reprice it across every date -- using the repo's own
conventions verbatim from ``QUANTLIB_FRB_DEFINITIONS["USTS"]``
(ActualActual.ISMA, UnitedStates.GovernmentBond, ModifiedFollowing, Semiannual, T+1).
It is checked against the MDP rather than trusted: :func:`tie_out_against_mdp` prices a
sample of dates both ways and reports the distribution of differences.

The bid-offer is half the point
-------------------------------
FedInvest publishes ``bid_price`` and ``offer_price`` per CUSIP per day. That is a
**dated, per-security, per-day quoted spread from an official source**, which is a far
better cost model than anything else available here:

* ``BT/gss_fly/config.py`` keys a half-spread on time to maturity, so two bonds of the
  same maturity and different age cost the same -- and age is exactly what this study
  trades.
* SR1170 Table 3 keys on off-the-run rank, which is the right axis, but its
  "further off-the-run" bucket for the 30-year sector is **166.98 price bp**, and every
  bond TLT owns sits in that bucket. Measured here, the same sector's actual daily
  quoted spread is **2.7-8.0 price bp** -- twenty to sixty times tighter. SR1170's tail
  is dominated by odd lots in genuinely dead issues; adopting it as the base case would
  kill this study by construction rather than by evidence. It is kept as the pessimistic
  bound in ``costs.py``, not as the default.

Two data defects this module gates, both previously measured in ARBS
--------------------------------------------------------------------
**eod_price = 0.00 for every bond on some days.** Confirmed still live: 9 whole dates in
a 56-day sample served ``eod_price = 0`` for all 349 coupon issues while bid and offer
were fine. A yield solved off a zero price comes out at 605-5,408% and caches as a valid
number. The panel therefore prices off the **mid of a two-sided bid/offer** wherever one
exists -- one consistent basis across the study window -- and carries ``eod_price``
alongside for reconciliation.

**offer_price = 0.00 inside a bond's last year.** The mirror-image defect, found by
building the panel: 1,441 of the 1,543 rows under six months to maturity had no offer.
Averaging a real bid with a zero offer gave a mid of ~50 on a par bond, a yield of
3.1e+20 % and a modified duration of 5.3e-21. So "two-sided" is checked rather than
assumed, and the fallback ladder (eod, then the single live side) is stamped in
``price_source`` so a caller can demand the two-sided sample and get exactly it. The
fallback only fires inside a bond's final year, which this study does not trade.

**QuantLib solves some yields onto the wrong root** (2015-01-02, 912828G38: -2.1158%
against a clean price of 101.19). One such row turned a rank spread from
``sd 0.86bp, autocorr +0.92`` into ``sd 18.9bp, autocorr +0.01`` -- into apparent white
noise. Gated cross-sectionally against the same-day maturity-neighbourhood median, which
needs no view on what yields were possible in a decade, only on how far apart two bonds
of similar maturity can be.
"""

from __future__ import annotations

import datetime
import os
import pathlib
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from utils.storage_paths import repo_store

#: Deviation from the same-day local-maturity median beyond which a yield is refused.
YIELD_GATE_BP = 100.0

#: Neighbourhood half-width, in years of remaining maturity, used to form that median.
YIELD_GATE_WINDOW_Y = 1.5

PANEL_ENV = "ARBS_ETF_PANEL_DIR"


def panel_dir() -> pathlib.Path:
    d = repo_store("notebooks", "backtests", "etf_rebalance", "_data", env_var=PANEL_ENV)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _defs():
    from Query.FixedRateBonds.backends.quantlib.ql_frb_definitions_map import (
        QUANTLIB_FRB_DEFINITIONS,
    )
    return QUANTLIB_FRB_DEFINITIONS["USTS"]


def business_days(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    return [
        ts.date() for ts in pd.date_range(start, end, freq="D")
        if cal.isBusinessDay(ql.Date(ts.day, ts.month, ts.year))
    ]


# --------------------------------------------------------------------------- reference

def reference_frame() -> pd.DataFrame:
    """The full fiscaldata UST reference table, **coupon securities only**.

    Bills, TIPS and FRNs are dropped here rather than downstream. A bill has no coupon
    schedule and would silently price as a zero-coupon bond of the wrong convention, and
    a TIPS real yield is not comparable to a nominal yield at the same maturity -- which
    is the comparison every signal in this study makes.
    """
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

    ref = update_reference_data(source="fiscaldata", force_refresh=False).copy()
    ref["cusip"] = ref["cusip"].astype(str)
    ref["cpn"] = pd.to_numeric(ref["cpn"], errors="coerce")
    ref["issue_date"] = pd.to_datetime(ref["issue_date"], errors="coerce")
    ref["maturity_date"] = pd.to_datetime(ref["maturity_date"], errors="coerce")

    def _truthy(col: str) -> pd.Series:
        if col not in ref.columns:
            return pd.Series(False, index=ref.index)
        return ref[col].astype(str).str.strip().str.lower().isin(["yes", "true", "1"])

    keep = (
        ref["cpn"].notna() & (ref["cpn"] > 0)
        & ref["issue_date"].notna() & ref["maturity_date"].notna()
        & ~_truthy("inflation_index_security")
        & ~_truthy("floating_rate")
    )
    return ref[keep].drop_duplicates(subset=["cusip"], keep="last").reset_index(drop=True)


def rank_frame(ref: pd.DataFrame, dates: Sequence[datetime.date]) -> pd.DataFrame:
    """(date, cusip) -> off-the-run rank and original-issue tenor.

    Uses ``_filter_and_rank_ref_df``, the MDP's own ranking function, so the ranks in
    this panel and the ranks any ``FixedRateBondQuery`` alias resolves to cannot drift.
    Rank 0 is the on-the-run; the roll happens one business day after the auction.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df

    # ``_filter_and_rank_ref_df`` compares its date columns against a plain
    # ``datetime.date``. fiscaldata hands those columns over as ``date`` objects, and
    # :func:`reference_frame` promotes them to ``datetime64`` so the rest of the panel
    # can merge on them -- which makes that comparison a TypeError. Hand the ranking
    # function the shape it expects rather than weakening the panel's dtypes.
    ranking_ref = ref.copy()
    for col in ("issue_date", "maturity_date", "auction_date"):
        if col in ranking_ref.columns and pd.api.types.is_datetime64_any_dtype(ranking_ref[col]):
            ranking_ref[col] = ranking_ref[col].dt.date

    rows = []
    for d in dates:
        r = _filter_and_rank_ref_df(ranking_ref, d)
        if r.empty:
            continue
        rows.append(pd.DataFrame({
            "date": pd.Timestamp(d),
            "cusip": r["cusip"].astype(str).values,
            "rank": r["rank"].astype(int).values,
            "oi": r["oi"].astype(str).values,
        }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


# --------------------------------------------------------------------------- prices

def raw_prices(
    dates: Sequence[datetime.date],
    *,
    max_concurrent: int = 8,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """FedInvest's daily price file for each date, long-format.

    Goes through ``FedInvestDataFetcher.runner``, the same code path and the same disk
    cache the MDP uses, so warming this warms the MDP too.
    """
    from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher

    fi = FedInvestDataFetcher()
    dts = [datetime.datetime(d.year, d.month, d.day) for d in dates]
    got = fi.runner(
        dates=dts,
        show_tqdm=show_tqdm,
        max_concurrent_tasks=max_concurrent,
        max_connections=max_concurrent,
        max_keepalive_connections=max_concurrent,
    )
    frames = []
    for dt, df in (got or {}).items():
        if df is None or getattr(df, "empty", True):
            continue
        f = df.copy()
        f["date"] = pd.Timestamp(dt.date())
        frames.append(f)
    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out["cusip"] = out["cusip"].astype(str)
    for c in ("bid_price", "offer_price", "eod_price", "coupon"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


# --------------------------------------------------------------------------- analytics

class BondCache:
    """One ``ql.FixedRateBond`` per CUSIP, built once and repriced across every date."""

    def __init__(self, ref: pd.DataFrame):
        import QuantLib as ql

        self._ql = ql
        self._d = _defs()
        self._meta = {
            str(r.cusip): (r.issue_date.date(), r.maturity_date.date(), float(r.cpn))
            for r in ref.itertuples()
            if pd.notna(r.issue_date) and pd.notna(r.maturity_date) and pd.notna(r.cpn)
        }
        self._bonds: Dict[str, object] = {}

    def __contains__(self, cusip: str) -> bool:
        return cusip in self._meta

    def bond(self, cusip: str):
        b = self._bonds.get(cusip)
        if b is not None:
            return b
        meta = self._meta.get(cusip)
        if meta is None:
            return None
        ql, d = self._ql, self._d
        iss, mat, cpn = meta
        sch = ql.Schedule(
            ql.Date(iss.day, iss.month, iss.year),
            ql.Date(mat.day, mat.month, mat.year),
            d["FrequencyPeriod"], d["Calendar"], d["BusinessConvention"],
            d["BusinessConvention"], ql.DateGeneration.Backward, False,
        )
        b = ql.FixedRateBond(
            d["SettlementDays"], 100.0, sch, [cpn / 100.0],
            d["DayCounter"], d["BusinessConvention"], d["Redemption"],
        )
        self._bonds[cusip] = b
        return b


def analytics_for_date(
    cache: BondCache,
    date: datetime.date,
    cusips: Sequence[str],
    clean_prices: Sequence[float],
) -> pd.DataFrame:
    """YTM (%), modified duration (years) and DV01 per $1mm face, for one date."""
    import QuantLib as ql

    d = _defs()
    ql_date = ql.Date(date.day, date.month, date.year)
    ql.Settings.instance().evaluationDate = ql_date
    settle = d["Calendar"].advance(ql_date, int(d["SettlementDays"]), ql.Days,
                                   d["BusinessConvention"])

    out_c, out_y, out_md, out_cx = [], [], [], []
    for cusip, px in zip(cusips, clean_prices):
        b = cache.bond(cusip)
        if b is None or not np.isfinite(px) or px <= 0:
            continue
        try:
            y = b.bondYield(ql.BondPrice(float(px), ql.BondPrice.Clean),
                            d["DayCounter"], d["Compounded"], d["Frequency"], settle)
            rate = ql.InterestRate(y, d["DayCounter"], d["Compounded"], d["Frequency"])
            md = ql.BondFunctions.duration(b, rate, ql.Duration.Modified)
            # Convexity is carried because a maturity butterfly is not convexity-neutral
            # even when it is DV01-neutral: the wings are three months either side of the
            # belly, so the structure is short or long gamma by construction and a large
            # yield move shows up in the P&L as something the signal did not predict.
            cx = ql.BondFunctions.convexity(b, rate)
        except Exception:
            continue
        out_c.append(cusip)
        out_y.append(y * 100.0)
        out_md.append(md)
        out_cx.append(cx)

    return pd.DataFrame({
        "date": pd.Timestamp(date), "cusip": out_c, "ytm": out_y,
        "mod_dur": out_md, "convexity": out_cx,
    })


# --------------------------------------------------------------------------- gates

def apply_yield_gate(panel: pd.DataFrame, *, gate_bp: float = YIELD_GATE_BP,
                     window_y: float = YIELD_GATE_WINDOW_Y) -> pd.DataFrame:
    """Flag yields that are implausible relative to their own maturity neighbourhood.

    Not a filter on the level of yields -- a filter on the *dispersion* within a
    maturity bucket on a single day. Two Treasuries whose maturities are within
    ``window_y`` of each other cannot be ``gate_bp`` apart in yield; when they are, one
    of them was solved onto the wrong root.
    """
    p = panel.copy()
    p["ttm_bucket"] = (p["ttm"] / max(1e-9, window_y)).round().astype("Int64")
    med = p.groupby(["date", "ttm_bucket"])["ytm"].transform("median")
    dev_bp = (p["ytm"] - med).abs() * 100.0
    n_in_bucket = p.groupby(["date", "ttm_bucket"])["ytm"].transform("size")
    # A bucket of one has no neighbourhood and cannot be judged; leave it alone.
    p["yield_gate_fail"] = (dev_bp > gate_bp) & (n_in_bucket >= 3)
    p["yield_dev_bp"] = dev_bp
    return p.drop(columns=["ttm_bucket"])


# --------------------------------------------------------------------------- builder

def build(
    start: datetime.date,
    end: datetime.date,
    *,
    max_concurrent: int = 8,
    show_progress: bool = True,
    out_path: Optional[pathlib.Path] = None,
) -> pd.DataFrame:
    """The whole panel, written to parquet and returned."""
    import tqdm

    dates = business_days(start, end)
    ref = reference_frame()
    if show_progress:
        print(f"reference: {len(ref):,} coupon USTs ever issued", flush=True)
        print(f"dates: {len(dates):,} business days {dates[0]} .. {dates[-1]}", flush=True)

    px = raw_prices(dates, max_concurrent=max_concurrent, show_tqdm=show_progress)
    if px.empty:
        raise RuntimeError("FedInvest returned nothing for the whole window.")
    if show_progress:
        print(f"raw prices: {len(px):,} rows over {px['date'].nunique():,} dates", flush=True)

    # ---------------------------------------------------------------- the price rule
    #
    # Price off the MID of a **two-sided** quote wherever one exists, so that every day
    # in the study window is on the same basis and no day silently switches.
    #
    # "Two-sided" has to be checked, not assumed. FedInvest publishes ``offer_price =
    # 0.00`` for bonds inside their last year -- 1,441 of 1,543 rows under six months to
    # maturity in a 56-day sample. Averaging a real bid with a zero offer produced a mid
    # of ~50 on a par bond, a yield of 3.1e+20 %, and a modified duration of 5.3e-21.
    # None of those is subtle, and all of them would have sailed into the panel: the
    # cross-sectional gate caught them only because it happened to be there.
    #
    # The fallback ladder is explicit and stamped in ``price_source``, so a downstream
    # filter can require ``mid`` and get exactly the two-sided-quote sample. It only ever
    # fires inside the last year of a bond's life, which this study does not trade.
    two_sided = px["bid_price"].gt(0) & px["offer_price"].gt(0)
    eod_ok = px["eod_price"].fillna(0.0).gt(0)
    one_side = px[["bid_price", "offer_price"]].where(lambda d: d.gt(0)).mean(axis=1)

    px["price_source"] = np.select(
        [two_sided, ~two_sided & eod_ok, ~two_sided & ~eod_ok & one_side.gt(0)],
        ["mid", "eod", "one_side"], default="none",
    )
    px["clean_price"] = np.select(
        [two_sided, ~two_sided & eod_ok],
        [(px["bid_price"] + px["offer_price"]) / 2.0, px["eod_price"]],
        default=one_side,
    )
    #: Quoted full spread in PRICE bp. NaN -- never 0 -- where there was no two-sided
    #: quote: a zero spread is a perfectly plausible cost and must not be confused with
    #: an unknown one.
    px["spread_price_bp"] = np.where(
        two_sided,
        (px["offer_price"] - px["bid_price"]) / px["clean_price"] * 1e4,
        np.nan,
    )
    px["eod_is_zero"] = ~eod_ok

    known = set(ref["cusip"])
    px = px[px["cusip"].isin(known) & px["clean_price"].gt(0)].copy()
    if show_progress:
        print(f"coupon USTs matched to reference: {len(px):,} rows", flush=True)
        print("price source: " + "  ".join(
            f"{k}={v:,}" for k, v in px["price_source"].value_counts().items()), flush=True)

    cache = BondCache(ref)
    frames, frames_eod = [], []
    it = px.groupby("date")
    if show_progress:
        it = tqdm.tqdm(it, total=px["date"].nunique(), desc="PRICING", unit="day")
    for d, chunk in it:
        frames.append(analytics_for_date(
            cache, d.date(), chunk["cusip"].tolist(), chunk["clean_price"].tolist()
        ))
        # Solve the eod basis EXACTLY rather than converting the price gap through a
        # duration. The two bases differ by many spread widths in stressed weeks, and a
        # butterfly cancels the level and leaves exactly that difference: a first-order
        # conversion left the fast engine and the QueryDrivenBacktest disagreeing 13x on
        # a single day of the March 2023 SVB week while agreeing to 0.01bp on the level.
        # The whole extra pass costs about a minute across 2,806 dates.
        eod = chunk["eod_price"].where(chunk["eod_price"] > 0)
        frames_eod.append(analytics_for_date(
            cache, d.date(), chunk["cusip"].tolist(), eod.tolist()
        ))
    an = pd.concat(frames, ignore_index=True)
    an_eod = pd.concat(frames_eod, ignore_index=True).rename(
        columns={"ytm": "ytm_eod", "mod_dur": "mod_dur_eod", "convexity": "convexity_eod"})
    an = an.merge(an_eod, on=["date", "cusip"], how="left")

    panel = px.merge(an, on=["date", "cusip"], how="left")
    meta = ref[["cusip", "cpn", "issue_date", "maturity_date"]]
    panel = panel.merge(meta, on="cusip", how="left")
    panel["ttm"] = (panel["maturity_date"] - panel["date"]).dt.days / 365.25
    panel["age"] = (panel["date"] - panel["issue_date"]).dt.days / 365.25

    rk = rank_frame(ref, [d.date() for d in sorted(panel["date"].unique())])
    panel = panel.merge(rk, on=["date", "cusip"], how="left")

    #: DV01 per $1mm face, in dollars. mod_dur is in years and prices are per 100.
    panel["dv01_per_mm"] = panel["mod_dur"] * panel["clean_price"] / 100.0 * 1e6 * 1e-4
    panel["spread_yield_bp"] = panel["spread_price_bp"] / panel["mod_dur"]

    panel = apply_yield_gate(panel)
    panel = panel[panel["ttm"] > 0].sort_values(["date", "ttm"]).reset_index(drop=True)

    out = out_path or (panel_dir() / "ust_panel.parquet")
    panel.to_parquet(out, index=False)
    if show_progress:
        print(f"\nwrote {out}  ({len(panel):,} rows, {panel['date'].nunique():,} dates, "
              f"{panel['cusip'].nunique():,} CUSIPs)", flush=True)
        print(f"gate: {int(panel['yield_gate_fail'].sum()):,} yields refused "
              f"({panel['yield_gate_fail'].mean() * 100:.3f}%)", flush=True)
        print(f"eod_price == 0 on {panel.groupby('date')['eod_is_zero'].all().sum():,} "
              f"whole dates (priced off mid regardless)", flush=True)
    return panel


def load(path: Optional[pathlib.Path] = None) -> pd.DataFrame:
    p = path or (panel_dir() / "ust_panel.parquet")
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    return df


# --------------------------------------------------------------------------- tie-out

def tie_out_against_mdp(panel: pd.DataFrame, dates: Sequence[datetime.date],
                        *, n_cusips: int = 40) -> pd.DataFrame:
    """Reprice a sample through ``FixedRateBondsMDP`` and report the difference.

    A fast path that is itself wrong reports success and hides what it was built to
    find. This is the check that the shortcut above did not change the answer. It cannot
    be exact: the MDP prices off ``eod_price`` and this panel prices off the bid/offer
    mid, so the difference is the eod-vs-mid basis and should be small and centred, not
    zero. What would be a real failure is a *systematic* gap or a fat tail.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    rows = []
    for d in dates:
        sub = panel[panel["date"] == pd.Timestamp(d)]
        # Compare like with like: only bonds the panel priced off a two-sided quote.
        # A bond on the eod fallback is priced off the MDP's own input, so including it
        # would flatter the comparison with rows that agree by construction.
        sub = sub[~sub["yield_gate_fail"] & sub["price_source"].eq("mid")].dropna(subset=["ytm"])
        if sub.empty:
            continue
        sub = sub.sample(min(n_cusips, len(sub)), random_state=7)
        pr = mdp.get_pricer(request=dict(cusips=sub["cusip"].tolist(), timestamp=d))
        for r in sub.itertuples():
            p = pr.get(r.cusip)
            if p is None:
                continue
            try:
                y_mdp, md_mdp = float(p.ytm()), float(p.mod_duration())
            except Exception:
                continue
            rows.append({
                "date": pd.Timestamp(d), "cusip": r.cusip, "ttm": r.ttm,
                "ytm_panel": r.ytm, "ytm_mdp": y_mdp,
                "d_ytm_bp": (r.ytm - y_mdp) * 100.0,
                "mod_dur_panel": r.mod_dur, "mod_dur_mdp": md_mdp,
                "d_mod_dur": r.mod_dur - md_mdp,
                "convexity": getattr(r, "convexity", np.nan),
                "half_spread_bp": r.spread_yield_bp / 2.0,
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-06-01")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--concurrency", type=int, default=8)
    a = ap.parse_args()
    build(
        datetime.date.fromisoformat(a.start),
        datetime.date.fromisoformat(a.end),
        max_concurrent=a.concurrency,
    )
