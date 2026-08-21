"""Can aggregating issuers help, or is the aggregate just TLT diluted?

This runs BEFORE any historical data layer is built, because the answer decides whether
that layer is worth building. Cross-issuer history is expensive: neither State Street
nor Vanguard serves holdings by date (SSGA is current-day xlsx, Vanguard's asOfDate
parameter is silently ignored and always returns the latest month-end), so history would
have to come from SEC N-PORT at quarterly granularity.

The hypothesis worth paying for is NOT "more funds means more assets". TLT alone owns a
median 1.7% of float and the whole six-fund iShares complex 0.61% of total outstanding,
against the Fed's 17.8% -- another $21bn of ETF does not change that arithmetic.

The hypothesis is that **different issuers sample differently**. TLT holds roughly 32 of
~90 eligible bonds, so its active weight is dominated by its own sampling policy -- the
diagonal streaks in the ladder explorer, a portfolio shape rather than a dislocation. If
State Street and Vanguard sample on different rules, their idiosyncratic tilts partially
cancel in aggregate and what survives is the common component: what the passive complex
collectively must own. That would be a better-specified signal, not merely a bigger one.

So the test is:

1. **Breadth.** How many eligible bonds does each fund actually hold? A fund that holds
   nearly all of them has almost no active weight to contribute and cannot cancel
   anyone's noise.
2. **Independence.** Are the funds' active weights across 3-month buckets correlated?
   If SPTL and VGLT tilt the same way TLT does, aggregation adds nothing and the
   aggregate is TLT wearing a larger coat. If they are uncorrelated, aggregation is a
   genuine variance reduction.
3. **Footprint.** What does combined ownership of each bucket actually reach?

A negative answer here is worth as much as a positive one and costs a few minutes rather
than a data-engineering project.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402

SCRATCH = ("C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/"
           "db95725e-cd80-43a6-b75f-e720edafca78/scratchpad")

#: The long end, per the user's scope. 20y+ is where TLT, SPTL and VGLT overlap most and
#: is the segment the micro-fly trades.
BAND_LO = 20.0
WIDTH_Y = 0.25


def parse_ssga(path: str) -> tuple[datetime.date, pd.DataFrame]:
    """SSGA publishes an xlsx with a four-line preamble; ``Identifier`` is an ISIN."""
    raw = pd.read_excel(path, sheet_name=0, header=None)
    asof = None
    for i in range(min(8, len(raw))):
        cell = str(raw.iloc[i, 1])
        if "As of" in cell:
            asof = pd.Timestamp(cell.replace("As of", "").strip()).date()
            hdr = i + 2
            break
    if asof is None:
        raise RuntimeError("SSGA: no 'As of' line found; the layout changed")

    df = pd.read_excel(path, sheet_name=0, header=hdr)
    df = df[df["Name"].notna()].copy()
    # ISIN -> CUSIP. US + 9-char CUSIP + check digit, so the CUSIP is chars 2:11.
    ident = df["Identifier"].astype(str).str.strip()
    df["cusip"] = np.where(ident.str.startswith("US") & (ident.str.len() == 12),
                           ident.str[2:11], ident)
    df["par"] = pd.to_numeric(df["Par Value"], errors="coerce")
    df["mv"] = pd.to_numeric(df["Market Value"], errors="coerce")
    df["maturity"] = pd.to_datetime(df["Maturity"], errors="coerce")
    return asof, df[["cusip", "par", "mv", "maturity"]].dropna(subset=["cusip"])


def parse_vanguard(path: str) -> tuple[datetime.date, pd.DataFrame]:
    d = json.load(open(path, encoding="utf-8"))
    ents = d["fund"]["entity"]
    asof = pd.Timestamp(d["asOfDate"]).date()
    df = pd.DataFrame(ents)
    df["cusip"] = df["cusip"].astype(str).str.strip()
    df["par"] = pd.to_numeric(df["faceAmount"], errors="coerce")
    df["mv"] = pd.to_numeric(df["marketValue"], errors="coerce")
    df["maturity"] = pd.to_datetime(df["maturityDate"], errors="coerce")
    return asof, df[["cusip", "par", "mv", "maturity"]].dropna(subset=["cusip"])


def main() -> None:
    panel = BP.load()
    floats = FP.load()
    panel = FP.asof_join(panel, floats)
    panel["priced"] = panel["ytm"].notna() & ~panel["yield_gate_fail"].fillna(True)

    sptl_asof, sptl = parse_ssga(os.path.join(SCRATCH, "sptl.xlsx"))
    vglt_asof, vglt = parse_vanguard(os.path.join(SCRATCH, "vglt.json"))
    print(f"SSGA SPTL as-of {sptl_asof}  {len(sptl)} lines")
    print(f"VGD  VGLT as-of {vglt_asof}  {len(vglt)} lines\n")

    # One common date. SPTL is T-1 daily, so use its date and take TLT from the store on
    # the same day; VGLT is month-end and is compared on shape only, never on a date it
    # does not have.
    day = pd.Timestamp(sptl_asof)
    px = panel[panel["date"].eq(day)].copy()
    if px.empty:
        day = pd.Timestamp(panel["date"].max())
        px = panel[panel["date"].eq(day)].copy()
        print(f"(panel has no {sptl_asof}; using {day.date()})\n")

    tlt_h = HP.load_holdings(["TLT"])
    tlt_h = tlt_h[tlt_h["date"].eq(day)][["cusip", "par"]].rename(columns={"par": "par_TLT"})

    # The eligible long-end universe on that date, priced, from the panel.
    uni = px[px["ttm"].ge(BAND_LO) & px["priced"]].copy()
    uni["cusip"] = uni["cusip"].astype(str)
    print(f"eligible 20y+ universe on {day.date()}: {len(uni)} bonds, "
          f"outstanding ${uni['outstanding_amt'].sum()/1e9:,.0f}bn, "
          f"free float ${uni['free_float'].sum()/1e9:,.0f}bn\n")

    funds = {
        "TLT":  tlt_h.rename(columns={"par_TLT": "par"}),
        "SPTL": sptl[["cusip", "par"]],
        "VGLT": vglt[["cusip", "par"]],
    }

    # ---------------------------------------------------------------- breadth
    rows = []
    held = {}
    for tk, h in funds.items():
        h = h.copy()
        h["cusip"] = h["cusip"].astype(str)
        m = uni[["cusip", "ttm", "dv01_per_mm", "clean_price", "free_float",
                 "outstanding_amt"]].merge(h, on="cusip", how="left")
        m["par"] = m["par"].fillna(0.0)
        held[tk] = m
        n_held = int((m["par"] > 0).sum())
        rows.append({
            "fund": tk,
            "eligible": len(uni),
            "held": n_held,
            "breadth_pct": 100.0 * n_held / len(uni),
            "par_bn": m["par"].sum() / 1e9,
            "own_pct_float": 100.0 * m["par"].sum() / m["free_float"].sum(),
        })
    breadth = pd.DataFrame(rows)
    print("BREADTH -- how much of the eligible 20y+ board each fund actually owns")
    print(breadth.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print()

    # ---------------------------------------------------------------- buckets
    def bucketise(m: pd.DataFrame) -> pd.DataFrame:
        b = m.copy()
        b["bucket"] = np.floor((b["ttm"] - BAND_LO) / WIDTH_Y).astype(int)
        b["dv01"] = b["par"] / 1e6 * b["dv01_per_mm"]
        b["idx_dv01"] = b["free_float"] / 1e6 * b["dv01_per_mm"]
        g = b.groupby("bucket", as_index=False).agg(
            dv01=("dv01", "sum"), idx_dv01=("idx_dv01", "sum"),
            par=("par", "sum"), free_float=("free_float", "sum"))
        g["w_f"] = g["dv01"] / g["dv01"].sum()
        g["w_i"] = g["idx_dv01"] / g["idx_dv01"].sum()
        g["active_bp"] = (g["w_f"] - g["w_i"]) * 1e4
        return g

    lad = {tk: bucketise(m) for tk, m in held.items()}
    wide = None
    for tk, g in lad.items():
        s = g.set_index("bucket")["active_bp"].rename(tk)
        wide = s.to_frame() if wide is None else wide.join(s, how="outer")
    wide = wide.fillna(0.0)

    print("ACTIVE WEIGHT BY 3-MONTH BUCKET (bp of the fund's own DV01, vs free float)")
    print(f"buckets: {len(wide)}   gross one-way tilt per fund (bp):")
    for tk in wide.columns:
        print(f"   {tk:5s} {wide[tk].clip(lower=0).sum():8.1f}")
    print()

    print("INDEPENDENCE -- correlation of bucket active weights across issuers")
    print("  (near +1 means aggregating adds nothing; near 0 means tilts cancel)")
    print(wide.corr().to_string(float_format=lambda v: f"{v:+.3f}"))
    print()

    # ---------------------------------------------------------------- footprint
    agg = None
    for tk, m in held.items():
        s = m.set_index("cusip")["par"].rename(tk)
        agg = s.to_frame() if agg is None else agg.join(s, how="outer")
    agg = agg.fillna(0.0)
    agg["total"] = agg.sum(axis=1)
    ff = uni.set_index("cusip")["free_float"]
    agg = agg.join(ff, how="left")
    own = (agg["total"] / agg["free_float"]).replace([np.inf, -np.inf], np.nan) * 100

    print("FOOTPRINT -- combined ETF ownership as % of each bond's free float")
    print(f"   TLT alone   median {100*(agg['TLT']/agg['free_float']).median():.2f}%   "
          f"p90 {100*(agg['TLT']/agg['free_float']).quantile(.9):.2f}%")
    print(f"   all three   median {own.median():.2f}%   p90 {own.quantile(.9):.2f}%   "
          f"max {own.max():.2f}%")
    print(f"   uplift over TLT alone: "
          f"{own.median() / max(1e-9, 100*(agg['TLT']/agg['free_float']).median()):.2f}x")
    print()

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
    wide.to_csv(os.path.join(out, "multi_issuer_bucket_active.csv"))
    breadth.to_csv(os.path.join(out, "multi_issuer_breadth.csv"), index=False)
    print(f"wrote _data/multi_issuer_bucket_active.csv and _data/multi_issuer_breadth.csv")


if __name__ == "__main__":
    main()
