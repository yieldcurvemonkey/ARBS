"""Load and prepare the study's two panels into one analysis-ready frame."""

from __future__ import annotations

import pathlib
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from RVUtils.USTSwitch.carry import (
    JPM_END,
    JPM_START,
    apply_specialness_model,
    attach_financing,
    attach_gc_fallback,
    build_specialness_model,
    load_repo_panel,
)

DATA_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "ust_switch" / "_data"
)
PANEL_PATH = DATA_DIR / "bond_panel.parquet"
MAP_PATH = DATA_DIR / "alias_cusip_map.parquet"
PREPARED_PATH = DATA_DIR / "prepared_panel.parquet"


def load_prepared(
    *, rebuild: bool = False, repo_horizon: str = "1m"
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(prepared_panel, alias_map). Caches the prepared panel to parquet."""
    amap = pd.read_parquet(MAP_PATH)
    amap["date"] = pd.to_datetime(amap["date"])

    if PREPARED_PATH.exists() and not rebuild:
        p = pd.read_parquet(PREPARED_PATH)
        p["date"] = pd.to_datetime(p["date"])
        return p, amap

    if not PANEL_PATH.exists():
        raise FileNotFoundError(
            f"no bond panel at {PANEL_PATH}. Build it first:\n"
            f"  python notebooks/backtests/ust_switch/build_bond_panel.py"
        )
    panel = pd.read_parquet(PANEL_PATH)
    for c in ("date", "issue_date", "maturity_date"):
        panel[c] = pd.to_datetime(panel[c])

    # BEFORE anything else touches the yields. A solver-failure row propagates into the
    # specialness model, the term structure and every trade that spans it.
    panel = gate_ytm(panel)

    repo = load_repo_panel()
    panel = attach_financing(panel, repo, horizon=repo_horizon)
    panel = attach_gc_fallback(panel)

    model = build_specialness_model(panel)
    model = _sanity_check_model(model, panel)
    panel = apply_specialness_model(panel, model)

    # Two usable specialness columns, chosen per financing mode by the engine:
    #   special_bp        -- measured, NaN outside the JPM window
    #   special_bp_filled -- measured inside, modelled outside
    panel["special_actual_bp"] = panel["special_bp"].fillna(0.0)
    panel["special_modelled_bp"] = panel["special_bp_filled"].fillna(0.0)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PREPARED_PATH, index=False)
    model.to_parquet(DATA_DIR / "specialness_model.parquet", index=False)
    return panel, amap


def select_financing(panel: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Materialise ``special_used_bp`` for a financing mode.

    Done here rather than inside the engine so a config cannot silently run with the
    wrong column, and so the "actual" mode can also CLIP THE WINDOW -- reporting a
    2010-2016 result under a label that claims measured financing would be the same
    misrepresentation as reporting no financing at all.
    """
    out = panel.copy()
    if mode == "none":
        out["special_used_bp"] = 0.0
    elif mode == "actual":
        out["special_used_bp"] = out["special_actual_bp"]
        out = out[(out["date"] >= JPM_START) & (out["date"] <= JPM_END)]
    elif mode == "modelled":
        out["special_used_bp"] = out["special_modelled_bp"]
    else:
        raise ValueError(f"unknown financing mode {mode!r}")
    return out


def coverage_report(panel: pd.DataFrame) -> pd.DataFrame:
    """Per tenor: date span, rows, and what fraction has MEASURED financing."""
    g = panel.groupby("tenor").agg(
        first=("date", "min"),
        last=("date", "max"),
        days=("date", "nunique"),
        rows=("date", "size"),
        cusips=("cusip", "nunique"),
        ytm_nan=("YTM", lambda s: float(s.isna().mean())),
        financing_actual=("has_actual_financing", "mean"),
        mean_special_bp=("special_actual_bp", "mean"),
    )
    return g.round(4).reset_index()


#: A modelled specialness cell fitted from too few observations is the single most
#: dangerous number in this study, because it is applied to ~40% of the sample and it
#: moves the P&L directly. Measured on a deliberately-starved fit (one tenor, 19% actual
#: coverage, all of it inside the late-2016 squeeze) the model returned **73.8bp** for the
#: 10y on-the-run against a 9-year measured mean of 4.6bp -- a 16x overstatement that would
#: have made the short leg look ruinously expensive and killed every long-old cell for the
#: wrong reason. Guarded rather than trusted.
MIN_CELL_OBS = 30
MODEL_CAP_QUANTILE = 0.95


def _sanity_check_model(model: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Drop thin cells and cap the rest at the measured distribution's own tail."""
    out = model.copy()
    measured = panel.loc[panel["has_actual_financing"], "special_bp"].dropna()
    cap = float(measured.quantile(MODEL_CAP_QUANTILE)) if len(measured) else 0.0

    thin = out["count"] < MIN_CELL_OBS
    n_thin = int(thin.sum())
    # NaN, not 0: a thin cell has an UNKNOWN median, and apply_specialness_model falls
    # back to the (tenor, rank) level for it. Zeroing would hand the short leg free
    # financing, which is the direction that flatters a long-old switch.
    out.loc[thin, "special_bp_model"] = np.nan

    hot = out["special_bp_model"] > cap
    n_hot = int(hot.sum())
    out.loc[hot, "special_bp_model"] = cap

    print(f"[specialness model] {len(out)} cells fitted from {len(measured):,} measured "
          f"observations; p{int(MODEL_CAP_QUANTILE*100)} cap = {cap:.2f}bp")
    if n_thin:
        print(f"                    {n_thin} cells dropped (< {MIN_CELL_OBS} obs)")
    if n_hot:
        print(f"                    {n_hot} cells capped at the measured p95")
    keep = out.dropna(subset=["special_bp_model"])
    if len(keep):
        print("                    fitted median specialness by (tenor, rank), bp:")
        piv = keep.pivot_table(index="tenor", columns="rank", values="special_bp_model",
                               aggfunc="median")
        print(piv.round(2).to_string().replace("\n", "\n                    "))
    return out


#: Maximum plausible yield difference between two bonds of the same original-issue tenor
#: at adjacent ranks. Their maturities are one auction cycle apart -- at most ~3 months for
#: 10y/20y/30y and ~1 month at the front -- so even in the steepest curve regime on record
#: they cannot differ by a full percent. 100bp is therefore a catastrophe detector, not a
#: tuned threshold; nothing legitimate is anywhere near it.
MAX_CROSS_RANK_YTM_DEV_BP = 100.0
#: A US Treasury clean price. Observed range on the 2010-2026 panel: 79.9 (1st pct) to
#: 146.5 (max). 20/200 is a catastrophe bound, not a tuned one.
MIN_CLEAN_PRICE, MAX_CLEAN_PRICE = 20.0, 200.0
#: No UST has printed outside this. The 1981 peak was ~15%; the US never went negative.
MIN_YTM_PCT, MAX_YTM_PCT = -1.0, 25.0


def gate_ytm(panel: pd.DataFrame, *, verbose: bool = True) -> pd.DataFrame:
    """Drop bond-days whose yield is a solver failure rather than a market price.

    Measured on the 2015-16 slice: 2015-01-02 prints ``YTM = -2.1158%`` for the 10y
    on-the-run against a CLEAN PRICE of 101.19 and a 2.25% coupon. A negative yield on a
    premium-priced Treasury is not a market state -- the US never printed one in this
    sample -- it is QuantLib's yield solve landing on the wrong root.

    One such row is not a rounding nuisance. The rank1-rank0 spread that day reads
    **+422.7bp** against a true range of -1.6 to +1.5bp, and it turns the whole 2015-16
    series into what looks like white noise: standard deviation 18.9bp with lag-1
    autocorrelation 0.014. A backtest run over that panel would book a 422bp move on
    whichever trade happened to span the date, and no amount of tuning downstream would
    reveal why.

    The test is CROSS-SECTIONAL rather than a level bound, because it needs no view on what
    yields are possible in a given decade -- only on how far apart two nearly identical
    bonds can be. The median of the four ranks is robust to one bad leg by construction.

    Rows are DROPPED, not filled. The engine intersects each leg's dates, so a dropped day
    simply is not marked; forward-filling would invent a price and zero-filling would
    invent a return.
    """
    p = panel.copy()
    med = p.groupby(["date", "tenor"])["YTM"].transform("median")
    dev_bp = (p["YTM"] - med).abs() * 100.0
    bad_xrank = dev_bp > MAX_CROSS_RANK_YTM_DEV_BP

    # Two INDEPENDENT backstops. On the 2010-2026 panel they are redundant -- the
    # cross-rank test alone caught all 283 bad rows, i.e. the union equals its own count --
    # but redundancy here is luck, not design, and the luck is visible in the data:
    #
    #   2014-09-12, 2014-11-21, 2026-07-09: FedInvest returns CLEAN_PRICE = 0.00 for EVERY
    #   rank of a tenor at once, and QuantLib solves yields of 3917%, 1890%, 1727%, 1974%
    #   against them. The cross-rank test only fires because those four garbage numbers
    #   disagree with EACH OTHER. Had the solver failed identically on all four, the median
    #   would have been garbage too and nothing would have fired.
    #
    # So gate the price directly: a US Treasury does not trade at 0, and has never traded
    # below 20 or above 200 in this sample (observed range 79.9 at the 1st percentile to
    # 146.5 at the maximum). And bound the yield: no UST has ever printed outside
    # [-1%, 25%] -- the 1981 peak was ~15% and the US never went negative.
    bad_price = ~p["CLEAN_PRICE"].between(MIN_CLEAN_PRICE, MAX_CLEAN_PRICE)
    bad_ytm = ~p["YTM"].between(MIN_YTM_PCT, MAX_YTM_PCT)

    bad = bad_xrank | bad_price | bad_ytm
    n = int(bad.sum())
    if verbose:
        print(f"[ytm gate] dropping {n} bond-days of {len(p):,} ({n / max(len(p), 1):.4%})  "
              f"[cross-rank {int(bad_xrank.sum())} | price {int(bad_price.sum())} | "
              f"ytm-bound {int(bad_ytm.sum())}]")
        if n:
            show = p.loc[bad, ["date", "tenor", "rank", "cusip", "cpn", "CLEAN_PRICE", "YTM"]]
            print(show.head(12).to_string(index=False))
            print("  by tenor:", show.groupby("tenor").size().to_dict())
    return p[~bad].reset_index(drop=True)
