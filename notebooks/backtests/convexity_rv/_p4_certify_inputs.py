r"""Block 5, step 1: certify every carried-forward input BEFORE anything is built on it.

A copied panel is a hypothesis until it is re-priced.  This script does the
re-price and the three coverage checks the Citi-framework pre-registration needs
to freeze its thresholds:

  0. CA panel tie-out -- a random date sample re-priced through
     ``IRSwapsTB.sfr_cvx_adj`` and compared cell by cell.
  1. Leg panel tie-out -- the spot 2y/5y/10y par rates and the ATMF normal vols
     the fair-value fit and the model level are built on.
  2. CFTC positioning coverage back to 2021 and the SIGN of ``dealer_net``,
     because the note's entry conjunction contains "dealers structurally long
     futures" and a threshold on a series whose sign convention is assumed is a
     coin flip wearing a citation.
  3. Window arithmetic -- the panel dates, the IMM rolls on both clocks, and the
     span the null bars will be computed against.

Output: notebooks/data/convexity_rv/p4_input_certification.json + a report.
"""
from __future__ import annotations

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
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CURVE = "USD-SOFR-1D"
OUT: dict = {}


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
CA.index = pd.to_datetime(CA.index)
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
print(f"CA {CA.shape} {CA.index.min().date()}..{CA.index.max().date()}   "
      f"legs {LEGS.shape} {LEGS.index.min().date()}..{LEGS.index.max().date()}   "
      f"common {len(IDX)}")
OUT["n_common_dates"] = int(len(IDX))
OUT["window"] = [str(IDX.min().date()), str(IDX.max().date())]

COLOURS = ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS")

# ---------------------------------------------------------------------------
sec("0. CA panel tie-out -- the copied artifact, re-priced")
# ---------------------------------------------------------------------------
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402

rng = np.random.default_rng(20260824)
sample = sorted(pd.DatetimeIndex(rng.choice(IDX, size=6, replace=False)))
tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
rows = []
for d in sample:
    got = tb.sfr_cvx_adj(list(COLOURS), d.date(), d.date())
    for lab in COLOURS:
        c = U.ca_col(lab)
        fresh = float(got[c].iloc[0]) if c in got.columns and len(got) else np.nan
        rows.append({"date": d.date(), "label": lab,
                     "panel": float(CA.loc[d, c]), "fresh": fresh})
tie = pd.DataFrame(rows)
tie["diff"] = tie["fresh"] - tie["panel"]
print(tie.round(8).to_string(index=False))
ca_err = float(tie["diff"].abs().max())
print(f"\nmax |fresh - panel| = {ca_err:.10f} bp over {len(tie)} cells "
      f"on {len(sample)} dates")
OUT["ca_reprice_max_abs_diff_bp"] = ca_err
OUT["ca_reprice_cells"] = int(len(tie))
OUT["ca_reprice_dates"] = [str(d.date()) for d in sample]
assert ca_err < 1e-6, "the carried CA panel does not re-price -- stop here"

# ---------------------------------------------------------------------------
sec("1. Leg panel tie-out -- the fair-value regressors and the model vol")
# ---------------------------------------------------------------------------
from Query.Unified.UnifiedQuery import UnifiedQuery  # noqa: E402
from Query.Unified.registry import UnifiedValue  # noqa: E402
from TB.TimeseriesBuilder import TimeseriesBuilder  # noqa: E402

leg_cols = [f"{CURVE} {t} OUTRIGHT RATE" for t in ("2Y", "5Y", "10Y")]
qs = [UnifiedQuery(curve=CURVE, tenor=t, value=UnifiedValue.IRS_RATE)
      for t in ("2Y", "5Y", "10Y")]
lo, hi = sample[0].date(), sample[-1].date()
fresh_legs = TimeseriesBuilder().get_timeseries(
    start=lo, end=hi, queries=qs, n_jobs=3, routers={"IRS": tb})
fresh_legs.index = pd.to_datetime(fresh_legs.index)
rows = []
for d in sample:
    for c in leg_cols:
        f = (float(fresh_legs.loc[d, c])
             if d in fresh_legs.index and c in fresh_legs.columns else np.nan)
        rows.append({"date": d.date(), "col": c.replace(CURVE + " ", ""),
                     "panel": float(LEGS.loc[d, c]), "fresh": f})
ltie = pd.DataFrame(rows)
ltie["diff"] = ltie["fresh"] - ltie["panel"]
print(ltie.round(8).to_string(index=False))
leg_err = float(ltie["diff"].abs().max())
print(f"\nmax |fresh - panel| = {leg_err:.10f} percent over {len(ltie)} cells")
OUT["leg_reprice_max_abs_diff_pct"] = leg_err
tb.close()

vol_cols = [f"{CURVE} {s} STRADDLE BUY ATMF NVOL"
            for s in ("1Yx1Y", "2Yx1Y", "3Yx1Y", "4Yx1Y", "5Yx1Y")]
print("\nATMF normal-vol coverage over the common window:")
cov = {c.replace(CURVE + " ", ""): float(LEGS.loc[IDX, c].notna().mean())
       for c in vol_cols}
for k, v in cov.items():
    print(f"  {k:26s} {v:.4f}")
OUT["nvol_coverage"] = cov
assert min(cov.values()) > 0.98

# ---------------------------------------------------------------------------
sec("2. CFTC positioning -- coverage back to 2021 and the SIGN of dealer_net")
# ---------------------------------------------------------------------------
from RVUtils.ConvexityRV.ca_signals import (EnrichmentConfig,  # noqa: E402
                                            build_enrichment_panel)

cfg = EnrichmentConfig(start=str(IDX.min().date()), end=str(IDX.max().date()))
enr, prov = build_enrichment_panel(cfg)
enr.index = pd.to_datetime(enr.index)
pos = enr.reindex(IDX)[["dealer_net", "am_net", "lev_net"]].ffill()
print(f"provenance: {prov.get('dealer_net', '?')}")
print(f"coverage after ffill: "
      f"{ {c: round(float(pos[c].notna().mean()), 4) for c in pos.columns} }")
print(f"2021 coverage:        "
      f"{ {c: round(float(pos.loc[:'2021-12-31', c].notna().mean()), 4) for c in pos.columns} }")
print("\nlevels (mn contracts):")
print((pos / 1e6).describe().loc[["mean", "std", "min", "max"]].round(3).to_string())
client = pos["am_net"] + pos["lev_net"]
c_lvl = float(pos["dealer_net"].corr(client))
print(f"\ncorr(dealer_net, am_net + lev_net) in LEVELS  {c_lvl:+.4f}")
print("The note's mechanism is that dealers take the other side of client "
      "shorts, so a strongly NEGATIVE number here is the convention check: "
      "'dealers long futures' == dealer_net HIGH.")
OUT["cftc"] = {
    "provenance": prov.get("dealer_net", "?"),
    "coverage": {c: float(pos[c].notna().mean()) for c in pos.columns},
    "coverage_2021": {c: float(pos.loc[:"2021-12-31", c].notna().mean())
                      for c in pos.columns},
    "corr_dealer_vs_client_levels": c_lvl,
    "dealer_net_mean_mn": float(pos["dealer_net"].mean() / 1e6),
    "dealer_net_min_mn": float(pos["dealer_net"].min() / 1e6),
    "dealer_net_max_mn": float(pos["dealer_net"].max() / 1e6),
}

# Does a high dealer_net actually go with a wide CA?  The note asserts it; this
# is the number, reported before any threshold is frozen.
sig = LEGS.loc[IDX, f"{CURVE} 4Yx1Y STRADDLE BUY ATMF NVOL"].astype(float)
w_blues = U.time_weight_series(IDX, "BLUES")
vs_model = CA.loc[IDX, U.ca_col("BLUES")] - sig ** 2 * w_blues / 2e4
z_pos = ((pos["dealer_net"] - pos["dealer_net"].rolling(252, min_periods=126).mean())
         / pos["dealer_net"].rolling(252, min_periods=126).std(ddof=1))
j = pd.concat([vs_model.rename("vs"), z_pos.rename("z")], axis=1).dropna()
print(f"\nBLUES CA-vs-model against the 1Y z of dealer_net, n={len(j)}:")
print(f"  corr(levels) {j['vs'].corr(j['z']):+.4f}")
for lo_, hi_ in ((-9, -1), (-1, 0), (0, 1), (1, 9)):
    m = (j["z"] > lo_) & (j["z"] <= hi_)
    if m.any():
        print(f"  z in ({lo_:+.0f},{hi_:+.0f}]  n={int(m.sum()):4d}  "
              f"mean CA-vs-model {j.loc[m, 'vs'].mean():+.3f} bp")
print(f"  fraction of dates with dealer_net 1Y z >= +1.0: "
      f"{float((j['z'] >= 1.0).mean()):.4f}")
OUT["cftc"]["corr_vsmodel_vs_dealerz"] = float(j["vs"].corr(j["z"]))
OUT["cftc"]["frac_dealer_z_ge_1"] = float((j["z"] >= 1.0).mean())

# ---------------------------------------------------------------------------
sec("3. Window arithmetic -- rolls on both clocks, and the span")
# ---------------------------------------------------------------------------
ca_rolls = U.ca_roll_dates(IDX)
leg_rolls = U.leg_roll_dates(IDX)
both = set(ca_rolls) & set(leg_rolls)
print(f"CA rank-map rolls  {len(ca_rolls)}   IMM_k leg rolls {len(leg_rolls)}   "
      f"in common {len(both)}")
print(f"first/last CA roll {ca_rolls[0].date()} .. {ca_rolls[-1].date()}")
span = (IDX.max() - IDX.min()).days / 365.25
print(f"panel span {span:.3f} years over {len(IDX)} dates "
      f"({len(IDX) / span:.1f} dates/yr)")
OUT["rolls"] = {"ca": len(ca_rolls), "leg": len(leg_rolls), "common": len(both),
                "ca_roll_dates": [str(d.date()) for d in ca_rolls]}
OUT["panel_span_years"] = float(span)

(DATA / "p4_input_certification.json").write_text(json.dumps(OUT, indent=1))
print(f"\nwrote {DATA / 'p4_input_certification.json'}")
