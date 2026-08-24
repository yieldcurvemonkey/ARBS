r"""Panel builder for the Citi *Sell Blues convexity adjustments, hedged* reproduction.

Source note: Citi Research, North America Rates Trade Idea, **09 Feb 2017**,
Ruslan Bikbov / Jason Williams — ``print (12).pdf`` in the corpus, extracted at
``docs/convexityrv/research/corpus2/g10-print-files.md`` section 4.

Everything the six figures need, on 2022-01-03..2026-08-21, assembled from
already-built artifacts plus one new read of the swaption-vol store:

  * Blues pack CA                      cavf_ca_panel.parquet (block 3 TB path)
  * 2y / 5y / 10y spot par swap rates  p2_legs.parquet
  * 3Yx1Y ATMF normal vol              p2_legs.parquet
  * 3Mx10Y smile, offsets +/-25bp      swaption_cube_store  <-- the only new read
  * CFTC TFF dealer / AM / lev net     ca_signals.build_enrichment_panel

The store carries EXACTLY the +/-25bp absolute strike offsets the note's Figure 3
uses (``skew_measure = NORMALABSOLUTE``), on 1,160 dates over the window, so the
risk reversal is the note's own quantity rather than an interpolation.

Output: notebooks/data/convexity_rv/p3_citi_repro.parquet
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402
from RVUtils.ConvexityRV import swaption_cube as SC  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
START, END = dt.date(2022, 1, 3), dt.date(2026, 8, 21)
CURVE = "USD-SOFR-1D"

#: The note's Figure 3/4 quantity: a 25bp-OUT risk reversal on 3m10y.
RR_EXPIRY, RR_TENOR, RR_OFFSET = "3M", "10Y", 25.0
#: The note's Figure 5 quantity: 3y1y implied vol against the fly.
VOL_EXPIRY, VOL_TENOR = "3Y", "1Y"

#: Fly START conventions to test against the CA. IMM starts are the brief's own
#: example (``IMM_1x2y/IMM_1x5y/IMM_1x10y``); 5/9/13/17 are the front contracts
#: of REDS/GREENS/BLUES/GOLDS, so a pack can be paired with a fly starting at
#: its own expiry. All come free from the leg panel.
IMM_STARTS = (1, 2, 5, 9, 13, 17)
#: Constant-maturity forward starts, fetched here.
CM_STARTS = ("1Y", "2Y", "3Y")


def main() -> None:
    ca = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
    legs = pd.read_parquet(DATA / "p2_legs.parquet")
    legs.index = pd.to_datetime(legs.index)
    idx = ca.index.intersection(legs.index)
    idx = idx[(idx >= pd.Timestamp(START)) & (idx <= pd.Timestamp(END))]
    print(f"{len(idx)} dates {idx.min().date()}..{idx.max().date()}")

    out = pd.DataFrame(index=idx)
    # Every pack colour, because the note's Figure 20 is a screen ACROSS the
    # strip and Figures 16/17 show two of them side by side.
    for lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
        out[f"{lab.lower()}_ca_bp"] = ca.loc[idx, U.ca_col(lab)]
        out[f"{lab.lower()}_w"] = U.time_weight_series(idx, lab).to_numpy()
        out[f"{lab.lower()}_t1mean"] = U.mean_t1_series(idx, lab).to_numpy()
        # the MATCHED forward 1y swap starting at the pack's own front IMM --
        # pack rate = CA/100 + this, which is what the note's realized-vol
        # column is computed on
        k = U.matched_imm_rank(lab)
        col = f"{CURVE} IMM_{k}x1y OUTRIGHT RATE"
        if col in legs.columns:
            out[f"{lab.lower()}_fwd1y_pct"] = legs.loc[idx, col]
    for t in ("2Y", "5Y", "10Y"):
        out[f"r{t.lower()}_pct"] = legs.loc[idx, f"{CURVE} {t} OUTRIGHT RATE"]

    # ---- forward-start fly legs -----------------------------------------
    # Citi's Figure 6 fits the CA on SPOT 2y/5y/10y. The natural extension is
    # to ask which START explains it best: the CA is a forward object, so a
    # spot fly is the one shape guaranteed not to sit where the risk is.
    # IMM starts come free from the leg panel; the constant-maturity ones are
    # fetched here.
    for k in IMM_STARTS:
        for t in ("2y", "5y", "10y"):
            c = f"{CURVE} IMM_{k}x{t} OUTRIGHT RATE"
            if c in legs.columns:
                out[f"imm{k}_{t}_pct"] = legs.loc[idx, c]
            else:
                print(f"  MISSING {c}")

    if CM_STARTS:
        print(f"fetching {len(CM_STARTS) * 3} constant-maturity forward legs ...")
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
        from Query.Unified.UnifiedQuery import UnifiedQuery
        from Query.Unified.registry import UnifiedValue
        from TB.IRSwapsTB import IRSwapsTB
        from TB.TimeseriesBuilder import TimeseriesBuilder

        tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
        qs = [UnifiedQuery(curve=CURVE, tenor=f"{a}x{t}",
                           value=UnifiedValue.IRS_RATE)
              for a in CM_STARTS for t in ("2Y", "5Y", "10Y")]
        fwd = TimeseriesBuilder().get_timeseries(
            start=idx.min().date(), end=idx.max().date(), queries=qs,
            n_jobs=12, routers={"IRS": tb})
        fwd.index = pd.to_datetime(fwd.index)
        for a in CM_STARTS:
            for t in ("2Y", "5Y", "10Y"):
                c = f"{CURVE} {a}x{t} OUTRIGHT RATE"
                if c in fwd.columns:
                    out[f"cm{a.lower()}_{t.lower()}_pct"] = fwd[c].reindex(idx)
                else:
                    print(f"  MISSING {c}")
        tb.close()
    for sh in ("1Yx1Y", "2Yx1Y", "3Yx1Y", "4Yx1Y", "5Yx1Y"):
        out[f"nvol_{sh.lower().replace('x', '')}"] = legs.loc[
            idx, f"{CURVE} {sh} STRADDLE BUY ATMF NVOL"]

    # roll dates on BOTH clocks -- the note excludes IMM-roll returns from its
    # realized-vol column, and the two clocks are one business day apart
    rolls = set(U.ca_roll_dates(idx)) | set(U.leg_roll_dates(idx))
    out["is_roll"] = [d in rolls for d in idx]


    # --- Figure 3: the 3m10y 25bp-out risk reversal --------------------------
    print(f"reading the vol store for {RR_EXPIRY}x{RR_TENOR} and "
          f"{VOL_EXPIRY}x{VOL_TENOR} ...")
    panel = SC.load_vol_panel([(RR_EXPIRY, RR_TENOR), (VOL_EXPIRY, VOL_TENOR)],
                              START, END)
    panel["date"] = pd.to_datetime(panel["date"])
    g = panel[(panel["expiry"] == RR_EXPIRY) & (panel["tenor"] == RR_TENOR)]
    wide = g.pivot_table(index="date", columns="offset_bp", values="vol_bp")
    missing = [o for o in (-RR_OFFSET, 0.0, RR_OFFSET) if o not in wide.columns]
    assert not missing, f"the store lacks offsets {missing}"
    out["rr_3m10y_bp"] = (wide[RR_OFFSET] - wide[-RR_OFFSET]).reindex(idx)
    out["atm_3m10y_bp"] = wide[0.0].reindex(idx)
    cov = float(out["rr_3m10y_bp"].notna().mean())
    print(f"  3m10y +/-{RR_OFFSET:.0f}bp risk reversal: {cov:.1%} of dates")

    gv = panel[(panel["expiry"] == VOL_EXPIRY) & (panel["tenor"] == VOL_TENOR)]
    out["nvol_3y1y_store"] = (gv[gv["offset_bp"] == 0.0]
                              .set_index("date")["vol_bp"].reindex(idx))

    # --- Figure 2: CFTC positioning ------------------------------------------
    try:
        from RVUtils.ConvexityRV.ca_signals import (EnrichmentConfig,
                                                    build_enrichment_panel)
        cfg = EnrichmentConfig(start=str(idx.min().date()),
                               end=str(idx.max().date()))
        enr, prov = build_enrichment_panel(cfg)
        for c in ("dealer_net", "am_net", "lev_net"):
            if c in enr.columns:
                out[c] = enr[c].reindex(idx).ffill()
        print("  CFTC provenance: " + prov.get("dealer_net", "?"))
    except Exception as exc:                                    # noqa: BLE001
        print(f"  CFTC unavailable: {type(exc).__name__}: {exc}")

    out.to_parquet(DATA / "p3_citi_repro.parquet")
    print(f"\nwrote {DATA / 'p3_citi_repro.parquet'}  {out.shape}")
    print("non-null coverage:")
    print(out.notna().mean().round(4).to_string())
    (DATA / "p3_citi_repro_meta.json").write_text(json.dumps({
        "source_note": "Citi Research, NA Rates Trade Idea, 'Sell Blues "
                       "convexity adjustments, hedged', 09 Feb 2017, "
                       "Bikbov & Williams (print (12).pdf)",
        "window": [str(idx.min().date()), str(idx.max().date())],
        "n_dates": len(idx),
        "rr_node": f"{RR_EXPIRY}x{RR_TENOR} +/-{RR_OFFSET:.0f}bp",
        "rr_coverage": cov,
    }, indent=1))


if __name__ == "__main__":
    main()
