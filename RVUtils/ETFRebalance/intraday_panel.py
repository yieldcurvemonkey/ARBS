r"""A timestamp-aware UST panel off the warmed Citi minute tape, and its cost anchors.

What this is
------------
``bond_panel.py`` gives one row per (date, CUSIP): FedInvest's daily file, one mark a
day, at whatever time of day that file represents. This module gives one row per
(date, CUSIP, **mark_time**), off the ``MI01`` minute layer that
``scripts/etf_intraday_backfill.py`` warmed, together with a richness residual from the
**same** local robust coupon-adjusted cubic the daily study used
(``curve.fit_residuals(deg=3, x_axis="ttm", include_coupon=True, robust=True)``),
refitted independently **at every timestamp**. Comparing a 15:00 residual to a 16:00
residual is then a comparison of two curves fitted to two instants, not a comparison of
one curve to itself.

The as-of rule, and why it cannot look forward
----------------------------------------------
A mark at time ``T`` is **the last print at or before T, on the same calendar day**.
Never a nearest match: the minute tape's median gap is two minutes, so a nearest-match
15:00 mark is routinely a 15:01 print, and one minute of the future inside a
one-hour measurement is a third of the object being measured when the seam moves
0.79 bp and the cross-section moves 0.12 bp.

Two guards beyond "backward":

* **same-day**. A backward search with a wide tolerance answers a 09:30 request on a
  Monday with Friday's 16:58 print. The merge is done against a tolerance and then the
  result is *dropped* unless the print's own calendar day equals the target's.
* **staleness is carried, not hidden**. ``stale_min_ytm`` / ``stale_min_px`` record how
  many minutes old each mark is. Resolution runs with a generous cap
  (:data:`RESOLVE_CAP_MIN`) so the distribution is observable; the study's own
  freshness rule is applied downstream by masking on those columns
  (:func:`fresh_mask`), which means the rule can be changed without rebuilding and,
  more importantly, means a 16:15 mark that is really a 15:58 print is a **fact in the
  panel** rather than something the builder silently smoothed over.

What is NOT computed intraday
-----------------------------
``mod_dur`` is merged from the daily FedInvest panel, not re-solved per timestamp. It is
used only to convert a price-bp spread into a yield-bp cost; a 20-31y modified duration
moves by order 1e-4 years across a trading day, and a duration that far out matters to
the fourth significant figure of a cost, not the first. Re-solving it would add 850,000
QuantLib calls to buy nothing. Stated here so no caller reads ``mod_dur`` as an intraday
quantity.

The three cost anchors
----------------------
Cost is a swept parameter whose level is contested, so three independent estimates are
built side by side rather than one being chosen:

1. **FedInvest bid/offer** -- dated, per-CUSIP, per-day, two-sided *quotes* from an
   official source. Already in the daily panel; the default in ``costs.py``.
2. **Roll (1984)** -- ``S = 2 sqrt(-cov(dP_t, dP_{t-1}))``, estimated per bond per month
   from this very minute tape. Independent of FedInvest in every respect: different
   source, different instrument (marks rather than quotes), different estimator.
3. **SR1170 Table 3** -- the pessimistic bound, from executions.

Their disagreement is the point. See :func:`roll_spread` for what Roll can and cannot
mean on a tape of marks.
"""

from __future__ import annotations

import datetime
import pathlib
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from . import curve as CV
from .intraday import LONG_END_YIELD_BAND, UNIVERSE_CSV, universe

__all__ = [
    "MARK_TIMES",
    "RESOLVE_CAP_MIN",
    "FRESH_MAX_MIN",
    "CURVE_CFG",
    "asof_marks",
    "build_panel",
    "fresh_mask",
    "add_fit_variants",
    "FIT_VARIANTS",
    "load_panel",
    "roll_spread",
    "roll_by_bond_month",
    "PANEL_COLUMNS",
]

DATA = (pathlib.Path(__file__).resolve().parents[2]
        / "notebooks" / "backtests" / "etf_rebalance" / "_data")

#: New York clock times the panel is struck at. 15:00 (the cash desks' mark) and 16:00
#: (the ETF's NAV strike and share close) are the two STRUCTURAL priors this study was
#: built around; the rest are context and controls, not candidates.
MARK_TIMES: tuple[str, ...] = (
    "09:30", "10:00", "11:00", "12:00", "13:00", "14:00",
    "15:00", "15:30", "16:00", "16:15", "17:00",
)

#: How far back the as-of resolve is allowed to reach, in minutes. Deliberately loose:
#: this is the observation window for the staleness distribution, not the study's
#: freshness rule.
RESOLVE_CAP_MIN = 240

#: The freshness rule the study applies downstream. A mark carried more than half an
#: hour is not a mark at that time.
FRESH_MAX_MIN = 30

#: Verbatim the daily study's curve configuration. Any change here makes every number
#: in this module incomparable with ``RESULTS.md`` and with the backfill's ceiling.
CURVE_CFG = dict(deg=3, x_axis="ttm", include_coupon=True, robust=True, y_col="ytm")

#: A date needs this many priced bonds before a cross-sectional curve is fitted to it.
MIN_BONDS_PER_FIT = 20


# ------------------------------------------------------------------ as-of resolution

#: Minutes to add to a cached stamp to reach the moment the bar's value actually holds.
#: Citi's HOURLY bars are START-stamped and carry their own close: the value at stamp
#: ``H`` equals the MI01 print at ``H:59`` on 100.0% of 3,804 overlapping bond-day-hours
#: (``intraday.py``). Shifting the index by 59 minutes is what lets the SAME as-of
#: resolver serve both layers without a caller having to remember the convention -- and
#: it makes the staleness column honest: a 15:00 mark taken off the hourly layer is a
#: 14:59 print and reports 1 minute stale, which is the truth.
STAMP_OFFSET_MIN = {"MI01": 0, "HOURLY": 59}


def _series(cache, tag: str, freq: str, offset_min: int = 0) -> Optional[pd.Series]:
    s = cache.read(tag, freq, "CLOSE")
    if s is None or s.empty:
        return None
    s = s.dropna()
    if s.empty:
        return None
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if offset_min:
        s.index = pd.DatetimeIndex(s.index) + pd.Timedelta(minutes=int(offset_min))
    return s


def asof_marks(s: pd.Series, mark_times: Sequence[str] = MARK_TIMES,
               cap_min: int = RESOLVE_CAP_MIN) -> pd.DataFrame:
    """``(date, mark_time) -> value, stale_min`` by a backward, same-day as-of.

    Returns a long frame with columns ``date``, ``mark_time``, ``value``, ``ts``
    (the timestamp of the print actually used) and ``stale_min``.
    """
    idx = pd.DatetimeIndex(s.index)
    prints = pd.DataFrame({"ts": idx, "value": s.to_numpy(float)}).sort_values("ts")
    days = pd.DatetimeIndex(np.unique(idx.normalize()))

    frames = []
    for mt in mark_times:
        hh, mm = (int(x) for x in mt.split(":"))
        tgt = pd.DataFrame({"target_ts": days + pd.Timedelta(hours=hh, minutes=mm)})
        # right_on keeps the PRINT's own stamp as a column, which is what makes the
        # staleness and the same-day guard computable at all -- an on= merge would
        # overwrite it with the target's.
        m2 = pd.merge_asof(tgt, prints.rename(columns={"ts": "print_ts"}),
                           left_on="target_ts", right_on="print_ts",
                           direction="backward",
                           tolerance=pd.Timedelta(minutes=cap_min))
        m2 = m2.dropna(subset=["print_ts", "value"])
        if m2.empty:
            continue
        # SAME-DAY guard: a backward search with a 4h tolerance would answer an 09:30
        # request with the previous session's last print whenever the day opens late.
        same_day = m2["print_ts"].dt.normalize() == m2["target_ts"].dt.normalize()
        m2 = m2[same_day]
        if m2.empty:
            continue
        frames.append(pd.DataFrame({
            "date": m2["target_ts"].dt.normalize().to_numpy(),
            "mark_time": mt,
            "value": m2["value"].to_numpy(float),
            "ts": m2["print_ts"].to_numpy(),
            "stale_min": ((m2["target_ts"] - m2["print_ts"]).dt.total_seconds()
                          / 60.0).to_numpy(float),
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["date", "mark_time", "value", "ts", "stale_min"])


def fresh_mask(panel: pd.DataFrame, max_min: float = FRESH_MAX_MIN,
               *, require_price: bool = True) -> pd.Series:
    """Rows whose mark is no more than ``max_min`` minutes stale."""
    ok = panel["stale_min_ytm"].le(max_min)
    if require_price:
        ok = ok & panel["stale_min_px"].le(max_min)
    return ok.fillna(False)


# ------------------------------------------------------------------------- the panel

def build_panel(
    *,
    freq: str = "MI01",
    mark_times: Sequence[str] = MARK_TIMES,
    cap_min: int = RESOLVE_CAP_MIN,
    daily_panel: Optional[pd.DataFrame] = None,
    out_path: Optional[pathlib.Path] = None,
    show_progress: bool = True,
) -> pd.DataFrame:
    """The whole timestamp-aware panel, fitted, written to parquet and returned."""
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

    uni = universe()
    cache = CitiVeloTagCache()

    parts = []
    for n, row in enumerate(uni.itertuples(index=False), start=1):
        isin, cusip = str(row.isin), str(row.cusip)
        got = {}
        for value, short in (("YIELD", "ytm"), ("PRICE", "clean_price")):
            s = _series(cache, f"RATES.BOND.{isin}.{value}", freq)
            if s is None:
                continue
            m = asof_marks(s, mark_times, cap_min)
            if m.empty:
                continue
            got[short] = m.rename(columns={
                "value": short, "stale_min": f"stale_min_{'ytm' if short == 'ytm' else 'px'}",
                "ts": f"ts_{'ytm' if short == 'ytm' else 'px'}"})
        if not got:
            continue
        if "ytm" in got and "clean_price" in got:
            df = got["ytm"].merge(got["clean_price"], on=["date", "mark_time"], how="outer")
        else:
            df = list(got.values())[0]
        df["cusip"] = cusip
        df["isin"] = isin
        parts.append(df)
        if show_progress and n % 20 == 0:
            print(f"  {n}/{len(uni)} bonds  rows so far {sum(len(p) for p in parts):,}",
                  flush=True)

    if not parts:
        raise RuntimeError(f"no {freq} data found for any bond in the universe")
    panel = pd.concat(parts, ignore_index=True)

    meta = uni.rename(columns={"coupon": "cpn"})[
        ["cusip", "isin", "maturity_date", "issue_date", "cpn",
         "in_reference_band", "held_by_tlt"]]
    panel = panel.merge(meta, on=["cusip", "isin"], how="left")
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ttm"] = (panel["maturity_date"] - panel["date"]).dt.days / 365.25
    panel["age"] = (panel["date"] - panel["issue_date"]).dt.days / 365.25

    # Possibility gate. sanity.US_TREASURY_BANDS is calibrated on the whole curve and
    # admits every bad cell this layer contains; LONG_END_YIELD_BAND does not.
    lo, hi = LONG_END_YIELD_BAND
    bad = panel["ytm"].notna() & ((panel["ytm"] < lo) | (panel["ytm"] > hi))
    panel["ytm_gate_fail"] = bad
    panel.loc[bad, "ytm"] = np.nan

    # ------------------------------------------------------- the daily FedInvest join
    if daily_panel is None:
        from . import bond_panel as BP
        daily_panel = BP.load()
    d = daily_panel[daily_panel["cusip"].isin(set(panel["cusip"]))]
    keep = ["date", "cusip", "ytm", "clean_price", "mod_dur", "convexity",
            "spread_price_bp", "rank", "price_source", "dv01_per_mm"]
    keep = [c for c in keep if c in d.columns]
    d = d[keep].rename(columns={
        "ytm": "ytm_fedinvest", "clean_price": "clean_price_fedinvest"})
    panel = panel.merge(d, on=["date", "cusip"], how="left")

    # ------------------------------------------------------------------- the fits
    panel = panel.sort_values(["date", "mark_time", "ttm"]).reset_index(drop=True)
    panel["resid_bp"] = np.nan
    panel["fit_rmse_bp"] = np.nan
    panel["resid_bp_band"] = np.nan
    panel["n_bonds_fit"] = 0

    fittable = panel["ytm"].notna() & panel["cpn"].notna() & panel["ttm"].gt(0)
    for mt in mark_times:
        sel = fittable & panel["mark_time"].eq(mt)
        sub = panel.loc[sel, ["date", "cusip", "ytm", "ttm", "cpn"]].copy()
        if sub.empty:
            continue
        n = sub.groupby("date")["cusip"].transform("size")
        sub = sub[n >= MIN_BONDS_PER_FIT]
        if sub.empty:
            continue
        r = CV.fit_residuals(sub, **CURVE_CFG)
        key = pd.MultiIndex.from_frame(r[["date", "cusip"]])
        pk = pd.MultiIndex.from_frame(panel.loc[sel, ["date", "cusip"]])
        panel.loc[sel, "resid_bp"] = pd.Series(
            r["resid_bp"].to_numpy(), index=key).reindex(pk).to_numpy()
        panel.loc[sel, "fit_rmse_bp"] = pd.Series(
            r["fit_rmse_bp"].to_numpy(), index=key).reindex(pk).to_numpy()
        cnt = r.groupby("date")["cusip"].size()
        panel.loc[sel, "n_bonds_fit"] = panel.loc[sel, "date"].map(cnt).fillna(0).to_numpy()

        # Band-only refit. 912810FT0 (Feb-2036) is the one universe member outside the
        # 2039+ reference band and sits ~3y in x-space from the next bond; a cubic
        # fitted with it present is partly fitted TO it. Robust weighting mitigates,
        # it does not eliminate, so both residuals are carried and the difference is
        # measurable rather than assumed away.
        band = panel.loc[sel, "in_reference_band"].fillna(False).to_numpy()
        subb = panel.loc[sel, ["date", "cusip", "ytm", "ttm", "cpn"]][band].dropna(
            subset=["ytm", "cpn"])
        if not subb.empty:
            nb = subb.groupby("date")["cusip"].transform("size")
            subb = subb[nb >= MIN_BONDS_PER_FIT]
            if not subb.empty:
                rb = CV.fit_residuals(subb, **CURVE_CFG)
                kb = pd.MultiIndex.from_frame(rb[["date", "cusip"]])
                panel.loc[sel, "resid_bp_band"] = pd.Series(
                    rb["resid_bp"].to_numpy(), index=kb).reindex(pk).to_numpy()

    panel["mark_freq"] = freq
    panel["is_fresh"] = fresh_mask(panel)

    out = out_path or (DATA / f"ipanel_{freq.lower()}.parquet")
    panel.to_parquet(out, index=False)
    if show_progress:
        print(f"\nwrote {out}  ({len(panel):,} rows, {panel['date'].nunique():,} dates, "
              f"{panel['cusip'].nunique()} CUSIPs, {panel['mark_time'].nunique()} marks)",
              flush=True)
    return panel


#: Three curve fits are carried, because the fit UNIVERSE moves the residual more than
#: any signal in this study does, and the number is meaningless without saying which.
#:
#: ``resid_bp``        every bond that priced -- the widest, and what the backfill's
#:                     ceiling was computed on. The x-range is ttm 9.5..30y because the
#:                     universe is "ever held by TLT since 2021" and a bond TLT bought at
#:                     20y is now 15y. A cubic across twenty years of maturity leaves a
#:                     residual containing curve SHAPE it could not bend to.
#: ``resid_bp_band``   the 96 bonds inside the 2039+ reference band, i.e. the same set
#:                     minus 912810FT0 (Feb-2036), which sits three years from its
#:                     nearest neighbour in x and is a leverage point on a cubic.
#: ``resid_bp_tlt19``  ttm >= 19y only -- TLT's own index band. THIS is the fit that is
#:                     comparable with the daily study's 0.434 bp, because that study
#:                     fitted 20-30y. Comparing any of the other two to 0.434 compares
#:                     two different curves and calls the difference intraday noise.
FIT_VARIANTS = {
    "resid_bp": None,
    "resid_bp_band": "band",
    "resid_bp_tlt19": 19.0,
}


def add_fit_variants(panel: pd.DataFrame, *, show_progress: bool = True) -> pd.DataFrame:
    """(Re)fit every variant in :data:`FIT_VARIANTS`, per (mark_time, date)."""
    p = panel
    fittable = p["ytm"].notna() & p["cpn"].notna() & p["ttm"].gt(0)
    for col, rule in FIT_VARIANTS.items():
        p[col] = np.nan
        if col == "resid_bp":
            p["fit_rmse_bp"] = np.nan
            p["n_bonds_fit"] = 0
        for mt in sorted(p["mark_time"].unique()):
            sel = fittable & p["mark_time"].eq(mt)
            if rule == "band":
                sel = sel & p["in_reference_band"].fillna(False)
            elif rule is not None:
                sel = sel & p["ttm"].ge(float(rule))
            sub = p.loc[sel, ["date", "cusip", "ytm", "ttm", "cpn"]].copy()
            if sub.empty:
                continue
            n = sub.groupby("date")["cusip"].transform("size")
            sub = sub[n >= MIN_BONDS_PER_FIT]
            if sub.empty:
                continue
            r = CV.fit_residuals(sub, **CURVE_CFG)
            key = pd.MultiIndex.from_frame(r[["date", "cusip"]])
            pk = pd.MultiIndex.from_frame(p.loc[sel, ["date", "cusip"]])
            p.loc[sel, col] = pd.Series(
                r["resid_bp"].to_numpy(), index=key).reindex(pk).to_numpy()
            if col == "resid_bp":
                p.loc[sel, "fit_rmse_bp"] = pd.Series(
                    r["fit_rmse_bp"].to_numpy(), index=key).reindex(pk).to_numpy()
                cnt = r.groupby("date")["cusip"].size()
                p.loc[sel, "n_bonds_fit"] = p.loc[sel, "date"].map(cnt).fillna(0).to_numpy()
        if show_progress:
            print(f"  fitted {col}: {int(p[col].notna().sum()):,} rows", flush=True)
    return p


def load_panel(freq: str = "MI01", path: Optional[pathlib.Path] = None) -> pd.DataFrame:
    p = path or (DATA / f"ipanel_{freq.lower()}.parquet")
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ------------------------------------------------------------------- Roll (1984)

def roll_spread(prices: np.ndarray, contiguous: np.ndarray) -> tuple[float, float, int]:
    """Roll's effective spread from one series of prices, in PRICE bp.

    ``S = 2 sqrt(-cov(dP_t, dP_{t-1}))``. ``contiguous[i]`` says whether the change into
    observation ``i`` is usable (same session, gap under the cap), so only lag-1 pairs
    whose BOTH changes are usable enter the covariance -- otherwise an overnight gap and
    the first print of a session become a "price change pair" and the estimator measures
    the calendar.

    Returns ``(spread_price_bp, raw_cov, n_pairs)``. ``spread`` is NaN when the
    autocovariance is positive, which is not a failure to report as zero: a positive
    autocovariance means the data contain no bid-ask bounce the estimator can see, and
    silently flooring it at zero would turn "undefined" into "free".
    """
    p = np.asarray(prices, float)
    if p.size < 4:
        return np.nan, np.nan, 0
    dp = np.diff(p) / p[:-1] * 1e4          # price bp returns
    ok = np.asarray(contiguous, bool)[1:]   # change into i is usable
    pair = ok[:-1] & ok[1:]
    if pair.sum() < 20:
        return np.nan, np.nan, int(pair.sum())
    a, b = dp[:-1][pair], dp[1:][pair]
    cov = float(np.mean(a * b) - np.mean(a) * np.mean(b))
    s = 2.0 * np.sqrt(-cov) if cov < 0 else np.nan
    return s, cov, int(pair.sum())


def roll_by_bond_month(
    isins: Iterable[str],
    *,
    freq: str = "MI01",
    session: tuple[int, int] = (8, 17),
    max_gap_min: int = 5,
    drop_zero_changes: bool = False,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Roll's spread per (isin, month), from the cached minute PRICE tape.

    ``session`` restricts to New York hours -- the stamps are America/New_York, measured
    five independent ways in ``intraday.py``. ``max_gap_min`` refuses a "change" spanning
    a hole; ``drop_zero_changes`` collapses runs of an unchanged mark first, which is the
    variant that answers "is the negative autocovariance real bounce, or is it a stale
    mark alternating with a fresh one".
    """
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

    cache = CitiVeloTagCache()
    rows = []
    for n, isin in enumerate(isins, start=1):
        s = _series(cache, f"RATES.BOND.{isin}.PRICE", freq)
        if s is None:
            continue
        idx = pd.DatetimeIndex(s.index)
        lo, hi = session
        keep = (idx.hour >= lo) & (idx.hour < hi)
        s = s[keep]
        if s.empty:
            continue
        df = pd.DataFrame({"ts": pd.DatetimeIndex(s.index), "px": s.to_numpy(float)})
        if drop_zero_changes:
            df = df[df["px"].ne(df["px"].shift())]
        df["day"] = df["ts"].dt.normalize()
        gap = df["ts"].diff().dt.total_seconds() / 60.0
        same_day = df["day"].eq(df["day"].shift())
        df["contig"] = same_day & gap.le(max_gap_min)
        df["month"] = df["ts"].dt.to_period("M")
        for month, g in df.groupby("month"):
            sp, cov, npair = roll_spread(g["px"].to_numpy(), g["contig"].to_numpy())
            rows.append({"isin": isin, "month": month.to_timestamp(),
                         "roll_price_bp": sp, "autocov": cov, "n_pairs": npair,
                         "n_prints": len(g), "px_med": float(g["px"].median())})
        if show_progress and n % 25 == 0:
            print(f"  roll {n} bonds, {len(rows):,} bond-months", flush=True)
    return pd.DataFrame(rows)


PANEL_COLUMNS = {
    "date": "calendar date of the mark, New York (tz-naive; the tape's stamps ARE New York)",
    "mark_time": "New York clock time the row is struck at, e.g. '15:00'",
    "cusip": "US Treasury CUSIP",
    "isin": "the Citi tag's ISIN, = 'US' + cusip + arithmetic check digit",
    "ytm": "yield to maturity in PERCENT, semi-annual, as Citi serves RATES.BOND.<isin>.YIELD",
    "clean_price": "clean price per 100, RATES.BOND.<isin>.PRICE",
    "ts_ytm": "timestamp of the yield print actually used (<= date+mark_time, same day)",
    "ts_px": "timestamp of the price print actually used",
    "stale_min_ytm": "minutes between ts_ytm and the mark time. 0 = a print at the mark",
    "stale_min_px": "minutes between ts_px and the mark time",
    "is_fresh": f"stale_min_ytm and stale_min_px both <= {FRESH_MAX_MIN} minutes",
    "ytm_gate_fail": "the raw Citi yield was outside LONG_END_YIELD_BAND and was NaN'd",
    "cpn": "coupon in percent, from the fiscaldata reference table",
    "maturity_date": "maturity",
    "issue_date": "issue date",
    "ttm": "years to maturity, (maturity - date)/365.25",
    "age": "years since issue",
    "in_reference_band": "maturity inside the study's 2039-01-01..2057 reference band",
    "held_by_tlt": "ever held by TLT 2021-01-04..2026-08-19 per MDP.ETFHoldings",
    "resid_bp": ("richness vs a local robust coupon-adjusted cubic fitted TO THIS "
                 "TIMESTAMP's cross-section (deg=3, x=ttm, coupon regressor, Huber). "
                 "POSITIVE = yields more than the curve says = CHEAP"),
    "resid_bp_band": ("the same residual from a fit restricted to in_reference_band "
                      "bonds -- i.e. dropping 912810FT0 (Feb-2036), an x-space leverage point"),
    "resid_bp_tlt19": ("the same residual from a fit restricted to ttm >= 19y, TLT's own "
                       "index band. THE ONLY ONE COMPARABLE WITH THE DAILY STUDY'S 0.434 bp"),
    "fit_rmse_bp": "RMSE of that timestamp's curve fit, bp",
    "n_bonds_fit": "how many bonds entered that timestamp's fit",
    "ytm_fedinvest": "the daily FedInvest panel's yield for the same (date, cusip), percent",
    "clean_price_fedinvest": "the FedInvest bid/offer MID clean price",
    "mod_dur": "modified duration from the DAILY panel. NOT an intraday quantity",
    "convexity": "convexity from the daily panel",
    "spread_price_bp": "FedInvest's published full bid-offer spread that day, PRICE bp",
    "rank": "off-the-run rank that day (0 = on-the-run)",
    "price_source": "how the daily panel priced that row ('mid' = two-sided quote)",
    "dv01_per_mm": "DV01 per $1mm face, dollars, from the daily panel",
    "mark_freq": "the Citi frequency the marks came from ('MI01' or 'HOURLY')",
}
