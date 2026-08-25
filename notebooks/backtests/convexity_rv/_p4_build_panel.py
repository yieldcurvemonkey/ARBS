r"""Panel builder for the Citi-framework backtest (block 5).

Source note: Citi Research, *NA Rates Trade Idea*, **09 Feb 2017**, Bikbov &
Williams, "Sell Blues convexity adjustments, hedged" (``print (12).pdf``), and
its origin, *US Rates Weekly*, **13 Jan 2017** (``print (15/18).pdf``).

Same shape as ``_p3_citi_repro_panel.py`` -- and deliberately so, because the
reproduction's own path is the known answer ``citi_fv`` is pinned against -- but
over the **full CA window 2021-01-04..2026-08-21** rather than the
reproduction's 2022 start, and with three additions the backtest needs:

* the twenty SR3 **outright** CAs, so the note's literal 13-row Figure-20 strip
  (rolling 1y packs at every quarterly front rank) can be built as a display
  diagnostic alongside the five tradeable colour packs;
* ``is_roll`` on the union of BOTH roll clocks;
* CFTC TFF positioning back to 2021, release-lagged 3 business days.

Everything here is assembled from artifacts that have already been certified
against a fresh re-price (``_p4_certify_inputs.py``: CA max |diff| 0.0 bp,
``_p4_leg_vintage_diff.py``: every carried leg column exact on 1,409 of 1,409
dates), plus one swaption-store read and the constant-maturity forward legs.

Output: notebooks/data/convexity_rv/p4_citi.parquet
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CURVE = "USD-SOFR-1D"
START, END = dt.date(2021, 1, 4), dt.date(2026, 8, 21)
COLOURS = ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS")
#: The brief's own IMM starts plus each colour's own front contract.
IMM_STARTS = (1, 2, 5, 9, 13, 17)
CM_STARTS = ("1Y", "2Y", "3Y")
#: The note's Figure 3/4 quantity, kept so the reproduction's figures can be
#: redrawn on the wider window.
RR_EXPIRY, RR_TENOR, RR_OFFSET = "3M", "10Y", 25.0


def main() -> None:
    t0 = time.time()
    ca = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
    ca.index = pd.to_datetime(ca.index)
    legs = pd.read_parquet(DATA / "p2_legs.parquet")
    legs.index = pd.to_datetime(legs.index)
    idx = ca.index.intersection(legs.index)
    idx = idx[(idx >= pd.Timestamp(START)) & (idx <= pd.Timestamp(END))]
    print(f"{len(idx)} dates {idx.min().date()}..{idx.max().date()}")

    out = pd.DataFrame(index=idx)
    for lab in COLOURS:
        l = lab.lower()
        out[f"{l}_ca_bp"] = ca.loc[idx, U.ca_col(lab)]
        out[f"{l}_w"] = U.time_weight_series(idx, lab).to_numpy()
        out[f"{l}_t1mean"] = U.mean_t1_series(idx, lab).to_numpy()
        k = U.matched_imm_rank(lab)
        out[f"{l}_fwd1y_pct"] = legs.loc[idx, f"{CURVE} IMM_{k}x1y OUTRIGHT RATE"]

    # The outright strip -- display only.  A pack CA built as the mean of four
    # outright CAs sits within 0.06-0.08 bp of the true pack for
    # GREENS/BLUES/GOLDS (measured) but inherits the outrights' own noise, so it
    # is a screen row, never a traded object.
    for r in range(1, 21):
        c = f"{CURVE} SFR{r} OUTRIGHT CVX_ADJ"
        if c in ca.columns:
            out[f"sfr{r}_ca_bp"] = ca.loc[idx, c]

    for t in ("2Y", "5Y", "10Y"):
        out[f"r{t.lower()}_pct"] = legs.loc[idx, f"{CURVE} {t} OUTRIGHT RATE"]
    for k in IMM_STARTS:
        for t in ("2y", "5y", "10y"):
            c = f"{CURVE} IMM_{k}x{t} OUTRIGHT RATE"
            if c in legs.columns:
                out[f"imm{k}_{t}_pct"] = legs.loc[idx, c]
            else:
                print(f"  MISSING {c}")
    for sh in ("1Yx1Y", "2Yx1Y", "3Yx1Y", "4Yx1Y", "5Yx1Y"):
        out[f"nvol_{sh.lower().replace('x', '')}"] = legs.loc[
            idx, f"{CURVE} {sh} STRADDLE BUY ATMF NVOL"]

    # Roll dates on BOTH clocks.  The CA rank map advances ON the IMM date and
    # an IMM_k swap leg the business day BEFORE; 22 each, zero in common.
    rolls = set(U.ca_roll_dates(idx)) | set(U.leg_roll_dates(idx))
    out["is_roll"] = [d in rolls for d in idx]
    out["is_ca_roll"] = [d in set(U.ca_roll_dates(idx)) for d in idx]
    print(f"roll dates: {int(out['is_roll'].sum())} on the union of two clocks")

    # ---- constant-maturity forward fly starts ---------------------------
    print(f"fetching {len(CM_STARTS) * 3} constant-maturity forward legs ...")
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    qs = [UnifiedQuery(curve=CURVE, tenor=f"{a}x{t}", value=UnifiedValue.IRS_RATE)
          for a in CM_STARTS for t in ("2Y", "5Y", "10Y")]
    # Year-chunked, like every other panel build in this package.  A single
    # multi-year span request returns DIFFERENT par rates for the same dates
    # (measured: up to 1.2 bp on the 10y), so the request shape is part of the
    # convention and is not a free choice.
    frames = []
    for y in range(START.year, END.year + 1):
        a = max(START, dt.date(y, 1, 1))
        b = min(END, dt.date(y, 12, 31))
        if a > b:
            continue
        df = TimeseriesBuilder().get_timeseries(start=a, end=b, queries=qs,
                                                n_jobs=9, routers={"IRS": tb})
        df.index = pd.to_datetime(df.index)
        frames.append(df)
        print(f"  {y}: {df.shape}")
    fwd = pd.concat(frames).sort_index()
    fwd = fwd[~fwd.index.duplicated(keep="last")]
    for a in CM_STARTS:
        for t in ("2Y", "5Y", "10Y"):
            c = f"{CURVE} {a}x{t} OUTRIGHT RATE"
            if c in fwd.columns:
                out[f"cm{a.lower()}_{t.lower()}_pct"] = fwd[c].reindex(idx)
            else:
                print(f"  MISSING {c}")
    tb.close()

    # ---- the 3m10y 25bp-out risk reversal -------------------------------
    try:
        from RVUtils.ConvexityRV import swaption_cube as SC
        print(f"reading the vol store for {RR_EXPIRY}x{RR_TENOR} ...")
        vp = SC.load_vol_panel([(RR_EXPIRY, RR_TENOR)], START, END)
        vp["date"] = pd.to_datetime(vp["date"])
        g = vp[(vp["expiry"] == RR_EXPIRY) & (vp["tenor"] == RR_TENOR)]
        wide = g.pivot_table(index="date", columns="offset_bp", values="vol_bp")
        if all(o in wide.columns for o in (-RR_OFFSET, 0.0, RR_OFFSET)):
            out["rr_3m10y_bp"] = (wide[RR_OFFSET] - wide[-RR_OFFSET]).reindex(idx)
            out["atm_3m10y_bp"] = wide[0.0].reindex(idx)
            print(f"  coverage {float(out['rr_3m10y_bp'].notna().mean()):.3f}")
        else:
            print(f"  the store lacks the +/-{RR_OFFSET:.0f}bp offsets")
    except Exception as exc:                                    # noqa: BLE001
        print(f"  risk reversal unavailable: {type(exc).__name__}: {exc}")

    # ---- CFTC positioning ------------------------------------------------
    from RVUtils.ConvexityRV.ca_signals import (EnrichmentConfig,
                                                build_enrichment_panel)
    cfg = EnrichmentConfig(start=str(idx.min().date()), end=str(idx.max().date()))
    enr, prov = build_enrichment_panel(cfg)
    enr.index = pd.to_datetime(enr.index)
    for c in ("dealer_net", "am_net", "lev_net"):
        if c in enr.columns:
            out[c] = enr[c].reindex(idx).ffill()
    print(f"  CFTC provenance: {prov.get('dealer_net', '?')}")

    out.to_parquet(DATA / "p4_citi.parquet")
    meta = {
        "source_note": "Citi Research, NA Rates Trade Idea, 'Sell Blues "
                       "convexity adjustments, hedged', 09 Feb 2017, Bikbov & "
                       "Williams (print (12).pdf); origin US Rates Weekly, "
                       "13 Jan 2017 (print (15/18).pdf)",
        "window": [str(idx.min().date()), str(idx.max().date())],
        "n_dates": int(len(idx)),
        "n_columns": int(out.shape[1]),
        "colours": list(COLOURS),
        "imm_starts": list(IMM_STARTS),
        "cm_starts": list(CM_STARTS),
        "n_roll_dates_union": int(out["is_roll"].sum()),
        "cftc_provenance": prov.get("dealer_net", "?"),
        "elapsed_s": round(time.time() - t0, 1),
        "inputs_certified_by": ["_p4_certify_inputs.py", "_p4_leg_vintage_diff.py"],
    }
    (DATA / "p4_citi_meta.json").write_text(json.dumps(meta, indent=1))
    print(f"\nwrote {DATA / 'p4_citi.parquet'}  {out.shape}")
    print("thinnest 12 columns:")
    print(out.notna().sum().sort_values().head(12).to_string())
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
