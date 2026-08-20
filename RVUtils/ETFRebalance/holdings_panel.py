"""Join scraped ETF holdings to the UST panel, and build the constant-maturity ladder.

The three quantities this module exists to produce
--------------------------------------------------
**1. Par per ETF share.** A fund's par holding of a CUSIP moves for two unrelated
reasons: the fund grew or shrank, and the manager traded. Dividing par by shares
outstanding removes the first. Measured on TLT over 2026-06 to 2026-08, the raw daily
``sum |dPar|`` was $0.2-2.0bn on ordinary days and $5.7bn on 2026-08-07 -- a day whose
share count then rose 10% into the next session. In par-per-share the same day is
12.5 against a typical 1.0-1.9, so the normalisation removes most but **not all** of a
creation: an in-kind basket is not a pro-rata slice of the book. Creation days are
therefore also flagged (:func:`flag_flow_days`) rather than assumed away.

**2. Active weight.** "Underweight" is meaningless without a benchmark. The benchmark
here is the bond's share of the market value of publicly held par within the fund's
index maturity band -- the ICE weighting rule -- and *which* outstanding measure to use
is settled by measurement in ``float_panel.benchmark_fit``, not by assumption.

**3. The constant-maturity bucket ladder.** Buckets are fixed offsets in *remaining
maturity* from the band's lower edge, so bucket 0 is always "about to be deleted" and
the top bucket is always "just issued", whatever the calendar says. That is what makes a
z-score of a bucket's weight comparable across ten years: the bucket keeps its economic
meaning while the bonds roll down through it.

The lag rule, which is not optional
-----------------------------------
A holdings document stamped ``as of Aug 19`` is published overnight. Nothing in it is
knowable at the Aug 19 close. Every function here that produces a tradeable signal takes
``exec_lag`` and shifts the holdings forward by it, and the default is 1 -- one full
business day, so a signal from the Aug 19 file trades at the Aug 20 close. This is the
same rule as "the last bar at or before T": an edge that only exists at lag 0 is an edge
that reads tomorrow's newspaper. ``exec_lag`` is a config knob so the grid can *show*
that, by running lag 0 alongside and letting the difference speak.
"""

from __future__ import annotations

import datetime
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from MDP.ETFHoldings import store as holdings_store
from MDP.ETFHoldings.universe import ETFSpec, spec
from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import float_panel as FP

#: Columns kept from the raw iShares document. Everything else is issuer metadata that
#: the ARBS reference data carries more reliably (and dated), so it is dropped rather
#: than silently preferred.
HOLDING_COLS = {
    "CUSIP": "cusip",
    "Par Value": "par",
    "Market Value": "mv",
    "Weight (%)": "w_fund_pct",
    "Price": "px_fund",
    "Mod. Duration": "mdur_fund",
    "YTM (%)": "ytm_fund",
    "Maturity": "maturity_fund",
    "Coupon (%)": "cpn_fund",
}


def load_holdings(tickers: Sequence[str], start=None, end=None) -> pd.DataFrame:
    """Tidy holdings: one row per (ticker, date, cusip), Treasuries only."""
    raw = holdings_store.load(list(tickers), start=start, end=end)
    if raw.empty:
        return raw

    keep = raw["Asset Class"].astype(str).str.strip().eq("Fixed Income")
    df = raw[keep].copy()

    out = pd.DataFrame({"ticker": df["ticker"], "date": pd.to_datetime(df["date"])})
    for src, dst in HOLDING_COLS.items():
        out[dst] = df[src] if src in df.columns else np.nan
    out["shares_out"] = pd.to_numeric(df["shares_outstanding"], errors="coerce")
    out["sector"] = df["Sector"].astype(str) if "Sector" in df.columns else ""

    out["cusip"] = out["cusip"].astype(str).str.strip()
    for c in ("par", "mv", "w_fund_pct", "px_fund", "mdur_fund", "ytm_fund", "cpn_fund"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["maturity_fund"] = pd.to_datetime(out["maturity_fund"], errors="coerce")

    # A CUSIP can appear twice in one document (different lots). Sum the position; take
    # the first of the per-security attributes, which are identical across the rows.
    agg = {"par": "sum", "mv": "sum", "w_fund_pct": "sum", "shares_out": "first",
           "px_fund": "first", "mdur_fund": "first", "ytm_fund": "first",
           "maturity_fund": "first", "cpn_fund": "first", "sector": "first"}
    out = out.groupby(["ticker", "date", "cusip"], as_index=False).agg(agg)

    out["par_per_share"] = out["par"] / out["shares_out"].replace(0, np.nan)
    out["w_fund"] = out["w_fund_pct"] / 100.0
    return out.sort_values(["ticker", "date", "cusip"]).reset_index(drop=True)


def flag_flow_days(holdings: pd.DataFrame, *, threshold: float = 0.02) -> pd.DataFrame:
    """Per (ticker, date): share-count change, and whether it was a big creation day.

    A "big" day is not a nuisance to be discarded -- it is a different signal, because a
    creation basket is chosen by the AP and a redemption basket by the manager. It is
    separated so that a rebalance signal is not quietly reading a flow one.
    """
    f = (holdings.groupby(["ticker", "date"], as_index=False)["shares_out"].first()
         .sort_values(["ticker", "date"]))
    f["d_shares"] = f.groupby("ticker")["shares_out"].diff()
    f["flow_pct"] = f["d_shares"] / f.groupby("ticker")["shares_out"].shift()
    f["is_flow_day"] = f["flow_pct"].abs() >= threshold
    f["fund_par"] = holdings.groupby(["ticker", "date"])["par"].sum().values
    return f


# --------------------------------------------------------------------------- the join

def build(
    tickers: Sequence[str],
    *,
    panel: Optional[pd.DataFrame] = None,
    floats: Optional[pd.DataFrame] = None,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
) -> pd.DataFrame:
    """Holdings joined to prices, reference data and outstanding amounts.

    Left join on the HOLDINGS side deliberately. A CUSIP the fund holds but the panel
    cannot price is a hole that must stay visible: dropping it here would silently
    reduce the fund's measured book and make every weight in that bucket too large.
    """
    h = load_holdings(tickers, start=start, end=end)
    if h.empty:
        raise RuntimeError(f"No stored holdings for {list(tickers)}. Run the backfill.")

    p = (panel if panel is not None else BP.load()).copy()
    p["date"] = pd.to_datetime(p["date"])
    p["cusip"] = p["cusip"].astype(str)

    f = floats if floats is not None else FP.load()
    p = FP.asof_join(p, f)

    # ``ytm_eod``/``mod_dur_eod``/``convexity_eod`` are carried through deliberately.
    # The universe's prices come from THIS join, not from the panel the caller may have
    # repriced, so without them a ``price_basis="eod"`` request silently produced an
    # identical book -- the knob looked like it worked and tested nothing.
    cols = ["date", "cusip", "ytm", "mod_dur", "convexity", "clean_price", "eod_price",
            "ytm_eod", "mod_dur_eod", "convexity_eod",
            "spread_price_bp", "spread_yield_bp", "price_source", "yield_gate_fail",
            "ttm", "age", "cpn", "issue_date", "maturity_date", "rank", "oi",
            "dv01_per_mm", "outstanding_amt", "soma_holdings", "free_float",
            "float_stale_days"]
    cols = [c for c in cols if c in p.columns]
    m = h.merge(p[cols], on=["date", "cusip"], how="left")

    m["priced"] = m["ytm"].notna() & ~m["yield_gate_fail"].fillna(True)
    m["dv01"] = m["par"] / 1e6 * m["dv01_per_mm"]
    m["dv01_per_share"] = m["dv01"] / m["shares_out"].replace(0, np.nan)
    return m


# --------------------------------------------------------------------------- benchmark

def benchmark_weights(
    panel: pd.DataFrame,
    sp: ETFSpec,
    *,
    outstanding: str = "ex_soma",
) -> pd.DataFrame:
    """Index weight per (date, cusip): market value share within the fund's band.

    ``outstanding``: ``ex_soma`` (publicly held, the ICE rule) or ``total``.
    """
    if sp.maturity_band is None:
        raise ValueError(f"{sp.ticker} has no maturity band, so it has no index weight.")
    lo, hi = sp.maturity_band

    p = panel[panel["ttm"].between(lo, hi, inclusive="left") & panel["priced"]].copy() \
        if "priced" in panel.columns else \
        panel[panel["ttm"].between(lo, hi, inclusive="left")].copy()

    out_amt = p["outstanding_amt"]
    if outstanding == "ex_soma":
        out_amt = (out_amt - p["soma_holdings"].fillna(0.0)).clip(lower=0.0)
    elif outstanding != "total":
        raise ValueError(f"outstanding must be 'ex_soma' or 'total', got {outstanding!r}")

    p["idx_mv"] = out_amt * p["clean_price"] / 100.0
    p["idx_dv01"] = out_amt / 1e6 * p["dv01_per_mm"]
    tot_mv = p.groupby("date")["idx_mv"].transform("sum")
    tot_dv01 = p.groupby("date")["idx_dv01"].transform("sum")
    p["w_index"] = p["idx_mv"] / tot_mv.replace(0, np.nan)
    p["w_index_dv01"] = p["idx_dv01"] / tot_dv01.replace(0, np.nan)
    p["in_index"] = True
    return p[["date", "cusip", "w_index", "w_index_dv01", "idx_mv", "idx_dv01", "in_index"]]


def with_active_weight(
    joined: pd.DataFrame,
    universe: pd.DataFrame,
    sp: ETFSpec,
    *,
    outstanding: str = "ex_soma",
    weight_basis: str = "dv01",
) -> pd.DataFrame:
    """Attach index weight and active weight to every index-eligible CUSIP.

    Outer join on purpose. A bond in the index that the fund does **not** hold has an
    active weight of exactly minus its index weight, and it is the single most
    underweight name on the board. An inner join would drop precisely the observations
    the signal is about.
    """
    bench = benchmark_weights(universe, sp, outstanding=outstanding)
    h = joined[joined["ticker"] == sp.ticker]

    m = bench.merge(h, on=["date", "cusip"], how="outer", suffixes=("", "_h"))
    m["ticker"] = sp.ticker
    m["in_index"] = m["in_index"].fillna(False)
    m["held"] = m["par"].fillna(0.0) > 0

    for c in ("par", "mv", "dv01", "w_fund"):
        if c in m.columns:
            m[c] = m[c].fillna(0.0)

    #: The fund's own weights are RE-NORMALISED over the Treasuries in the document
    #: rather than taken from ``Weight (%)`` directly: the published weight is a share
    #: of net assets and includes the cash line, so a fund holding 1.5% cash would show a
    #: systematic 1.5% "underweight" spread evenly across the board. That is a constant,
    #: not a dislocation, and it would enter every z-score as one.
    tot_mv = m.groupby("date")["mv"].transform("sum")
    tot_dv01 = m.groupby("date")["dv01"].transform("sum")
    m["w_fund_mv"] = m["mv"] / tot_mv.replace(0, np.nan)
    m["w_fund_dv01"] = m["dv01"] / tot_dv01.replace(0, np.nan)

    if weight_basis == "dv01":
        m["w_f"], m["w_i"] = m["w_fund_dv01"], m["w_index_dv01"]
    elif weight_basis == "mv":
        m["w_f"], m["w_i"] = m["w_fund_mv"], m["w_index"]
    else:
        raise ValueError(f"weight_basis must be 'dv01' or 'mv', got {weight_basis!r}")

    m["active_w"] = m["w_f"] - m["w_i"]
    #: Ownership: what share of the bond's publicly held par this fund owns. The
    #: scarcity channel -- distinct from active weight, which is about the fund's
    #: internal allocation.
    denom = m["free_float"] if outstanding == "ex_soma" else m["outstanding_amt"]
    m["ownership"] = m["par"] / denom.replace(0, np.nan)
    return m.sort_values(["date", "ttm"]).reset_index(drop=True)


# --------------------------------------------------------------------------- the ladder

def bucket_index(ttm: pd.Series, sp: ETFSpec, *, width_y: float = 0.25) -> pd.Series:
    """Constant-maturity bucket, counted UP from the index's deletion boundary.

    Bucket 0 is the last ``width_y`` of maturity before the fund must sell -- the
    deletion bucket -- and it keeps that meaning on every date in the sample. Above the
    band it saturates rather than running away, so a 30-year issued into a 20+ band gets
    the top bucket and not an unbounded index.
    """
    lo = sp.band_low if sp.band_low is not None else 0.0
    hi = sp.band_high if sp.band_high is not None else np.inf
    k = np.floor((ttm - lo) / width_y)
    if np.isfinite(hi):
        k = k.clip(lower=-1, upper=np.floor((hi - lo) / width_y))
    return k.astype("Float64")


def ladder(
    active: pd.DataFrame,
    sp: ETFSpec,
    *,
    width_y: float = 0.25,
    weight_basis: str = "dv01",
) -> pd.DataFrame:
    """Per (date, bucket): the fund's weight, the index weight, and the gap.

    This is the risk ladder the study is named for -- "where is TLT relative to where it
    has been, bucket by bucket" -- with the crucial difference that "where it has been"
    is measured against the index rather than against its own past level, so a bucket
    that is small because the Treasury stopped issuing into it does not read as a
    dislocation.
    """
    a = active.copy()
    a["bucket"] = bucket_index(a["ttm"], sp, width_y=width_y)
    a = a[a["bucket"].notna()]

    g = a.groupby(["date", "bucket"], as_index=False).agg(
        w_f=("w_f", "sum"), w_i=("w_i", "sum"),
        par=("par", "sum"), mv=("mv", "sum"), dv01=("dv01", "sum"),
        idx_mv=("idx_mv", "sum"), idx_dv01=("idx_dv01", "sum"),
        n_index=("in_index", "sum"), n_held=("held", "sum"),
        ttm_mid=("ttm", "median"),
    )
    g["active_w"] = g["w_f"] - g["w_i"]
    #: Relative, not absolute. A 20bp absolute gap means something different in a bucket
    #: carrying 5% of the index than in one carrying 0.5%, and the ladder spans both.
    g["active_rel"] = g["active_w"] / g["w_i"].replace(0, np.nan)
    return g.sort_values(["date", "bucket"]).reset_index(drop=True)


# --------------------------------------------------------------------------- lag

def apply_exec_lag(df: pd.DataFrame, *, exec_lag: int, date_col: str = "date",
                   by: Iterable[str] = ("cusip",)) -> pd.DataFrame:
    """Stamp each observation with the first date it could have been TRADED on.

    Implemented as a shift along the panel's own date axis rather than a calendar offset,
    so a holiday or a missing file moves the tradeable date to the next date that
    actually exists instead of to a day with no price.
    """
    if exec_lag < 0:
        raise ValueError("exec_lag must be >= 0")
    dates = np.sort(df[date_col].unique())
    nxt = {d: (dates[i + exec_lag] if i + exec_lag < len(dates) else pd.NaT)
           for i, d in enumerate(dates)}
    out = df.copy()
    out["trade_date"] = out[date_col].map(nxt)
    return out[out["trade_date"].notna()]
