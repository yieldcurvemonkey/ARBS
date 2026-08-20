"""Amount outstanding and Fed SOMA holdings per CUSIP -- the index-weight denominator.

Why this is a separate, monthly build
-------------------------------------
Every "is the fund over- or under-weight" signal needs a benchmark weight to be
over- or under-weight *against*, and for an ICE US Treasury index that benchmark is the
market value of the bond's publicly held amount outstanding within the maturity band.
So the panel needs, per CUSIP: amount outstanding, and how much of it the Federal
Reserve owns.

``FixedRateBondsMDP.get_bond_reference_data(..., {"append_free_float": True})`` returns
exactly that, but it is a live API round trip per as-of date (measured 3-5 s), which is
two to four hours across the study window. It is also *nearly constant* between those
calls: an issue's outstanding amount changes only at auction or reopening, and SOMA
holdings move weekly and gradually. Sampling **monthly and holding the last value** is
therefore accurate to within a few days of the reopening calendar, at 1/20th the cost.

Which denominator is right is not assumed
-----------------------------------------
ICE's US Treasury index family weights on publicly held par -- i.e. **excluding SOMA** --
while the naive choice is total outstanding. The difference is not small: SOMA held a
fifth to a third of some long issues over this sample, and it is *concentrated* in
particular CUSIPs rather than spread evenly, so the two benchmarks disagree most exactly
where this study looks.

Rather than picking one from memory, :func:`benchmark_fit` regresses the fund's actual
published weights on each candidate and reports which one the fund's own book is
consistent with. That turns a methodology assumption into a measurement, and it doubles
as a check that the whole benchmark-weight construction is right -- if neither candidate
explains the fund's weights, the error is upstream of the choice.
"""

from __future__ import annotations

import datetime
import os
import pathlib
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance.bond_panel import panel_dir

FLOAT_COLS = (
    "cusip", "outstanding_amt", "soma_holdings", "free_float",
    "portion_stripped_amt", "portion_unstripped_amt",
)


def sample_dates(start: datetime.date, end: datetime.date, *, freq: str = "MS") -> list[datetime.date]:
    """Month starts, plus the final date so the panel reaches the end of the window."""
    ds = [ts.date() for ts in pd.date_range(start, end, freq=freq)]
    if not ds or ds[-1] != end:
        ds.append(end)
    return ds


def build(
    start: datetime.date,
    end: datetime.date,
    *,
    freq: str = "MS",
    show_progress: bool = True,
    out_path: Optional[pathlib.Path] = None,
) -> pd.DataFrame:
    import tqdm

    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    dates = sample_dates(start, end, freq=freq)
    it = tqdm.tqdm(dates, desc="FLOAT", unit="asof") if show_progress else dates

    frames = []
    for d in it:
        try:
            ref = mdp.get_bond_reference_data(as_of_date=d, kwargs={"append_free_float": True})
        except Exception as exc:
            print(f"  {d}: FAILED {type(exc).__name__}: {exc}", flush=True)
            continue
        if ref is None or ref.empty:
            continue
        cols = [c for c in FLOAT_COLS if c in ref.columns]
        if "cusip" not in cols:
            continue
        f = ref[cols].copy()
        f["cusip"] = f["cusip"].astype(str)
        f["asof"] = pd.Timestamp(d)
        frames.append(f)

    if not frames:
        raise RuntimeError("No reference frames returned for the whole window.")
    out = pd.concat(frames, ignore_index=True)
    for c in out.columns:
        if c not in ("cusip", "asof"):
            out[c] = pd.to_numeric(out[c], errors="coerce")

    path = out_path or (panel_dir() / "float_panel.parquet")
    out.to_parquet(path, index=False)
    if show_progress:
        print(f"\nwrote {path}  ({len(out):,} rows, {out['asof'].nunique()} as-ofs, "
              f"{out['cusip'].nunique():,} CUSIPs)", flush=True)
    return out


def load(path: Optional[pathlib.Path] = None) -> pd.DataFrame:
    p = path or (panel_dir() / "float_panel.parquet")
    df = pd.read_parquet(p)
    df["asof"] = pd.to_datetime(df["asof"])
    return df


def asof_join(daily: pd.DataFrame, floats: pd.DataFrame) -> pd.DataFrame:
    """Attach the most recent float observation at or before each panel date.

    Backward as-of on purpose. A forward fill from the *next* monthly sample would put
    an amount outstanding into the panel before the reopening that created it -- a
    lookahead of up to a month in exactly the variable the signals divide by.
    """
    # Idempotent. Callers legitimately hold a panel that has already been joined (the
    # notebook does it once and hands the result down), and a second merge_asof on a
    # frame that already carries ``asof`` silently suffixes it to ``asof_x``/``asof_y``
    # and takes the staleness column with it.
    if "asof" in daily.columns and "outstanding_amt" in daily.columns:
        out = daily.copy()
        if "float_stale_days" not in out.columns:
            out["float_stale_days"] = (out["date"] - out["asof"]).dt.days
        return out

    d = daily.sort_values("date").copy()
    f = floats.sort_values("asof").copy()
    d["cusip"] = d["cusip"].astype(str)
    f["cusip"] = f["cusip"].astype(str)
    out = pd.merge_asof(
        d, f, left_on="date", right_on="asof", by="cusip", direction="backward",
    )
    out["float_stale_days"] = (out["date"] - out["asof"]).dt.days
    return out


def benchmark_fit(
    holdings: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    ticker: str,
    band: tuple[float, float],
    dates: Optional[Sequence[pd.Timestamp]] = None,
) -> pd.DataFrame:
    """Which outstanding measure explains the fund's published weights?

    For each sampled date, build both candidate benchmark weights over the band-eligible
    universe -- market value of TOTAL outstanding, and of outstanding EX-SOMA -- and
    regress the fund's own ``Weight (%)`` on each. Reports R^2, slope and the mean
    absolute weight error in bp, per candidate.

    A fund that samples rather than replicates will not fit either perfectly. What the
    table is for is the *comparison*: the candidate the index actually uses should fit
    materially better, and if neither fits at all then the band, the universe filter or
    the join is wrong and no amount of picking between them will help.
    """
    h = holdings[holdings["ticker"] == ticker].copy()
    h["date"] = pd.to_datetime(h["date"])
    h["cusip"] = h[("CUSIP" if "CUSIP" in h.columns else "cusip")].astype(str)
    if "w_fund" not in h.columns:
        wcol = "Weight (%)" if "Weight (%)" in h.columns else "w_fund_pct"
        h["w_fund"] = pd.to_numeric(h[wcol], errors="coerce") / 100.0

    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"])
    lo, hi = band

    use_dates = list(dates) if dates is not None else sorted(
        set(h["date"].unique()) & set(p["date"].unique())
    )
    rows = []
    for d in use_dates:
        pd_ = p[(p["date"] == d) & p["ttm"].between(lo, hi) & ~p["yield_gate_fail"]]
        hd = h[h["date"] == d]
        if pd_.empty or hd.empty:
            continue
        pd_ = pd_.copy()
        pd_["mv_total"] = pd_["outstanding_amt"] * pd_["clean_price"] / 100.0
        pd_["mv_exsoma"] = (
            (pd_["outstanding_amt"] - pd_["soma_holdings"].fillna(0.0)).clip(lower=0.0)
            * pd_["clean_price"] / 100.0
        )
        for label, col in (("total_outstanding", "mv_total"), ("ex_soma", "mv_exsoma")):
            tot = pd_[col].sum()
            if not np.isfinite(tot) or tot <= 0:
                continue
            bench = pd_.assign(w_bench=pd_[col] / tot)[["cusip", "w_bench"]]
            j = hd.merge(bench, on="cusip", how="inner").dropna(subset=["w_fund", "w_bench"])
            if len(j) < 5:
                continue
            x, y = j["w_bench"].to_numpy(float), j["w_fund"].to_numpy(float)
            slope = float(np.dot(x, y) / max(1e-18, np.dot(x, x)))   # through the origin
            resid = y - slope * x
            ss_tot = float(((y - y.mean()) ** 2).sum())
            rows.append({
                "date": d, "benchmark": label, "n_matched": len(j),
                "n_index": len(pd_), "n_fund": len(hd),
                "slope": slope,
                "r2": 1.0 - float((resid ** 2).sum()) / max(1e-18, ss_tot),
                "mae_weight_bp": float(np.abs(resid).mean() * 1e4),
                "fund_weight_covered": float(j["w_fund"].sum()),
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-06-01")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--freq", default="MS")
    a = ap.parse_args()
    build(datetime.date.fromisoformat(a.start), datetime.date.fromisoformat(a.end), freq=a.freq)
