"""F2 gate — gamma-sector IV/RV conditioning (family F2), premium-marked.

The JPM desk rule (Aug-2026 pack: don't buy vol when implied/21d-realized > 1
everywhere) and the Citi gamma-cycle result both claim the IV/RV ratio times
short-gamma harvest. Gate, before any strategy: simulate NON-OVERLAPPING 21bd
short ATM straddles (sell, daily delta-hedge, unwind), premium-marked off the
cube + locus panel with CM-1 entry/exit costs, at the gamma loci (1M/3M/6M x
10Y and 3M/6M x 2Y), entries every 21bd 2020-02..2026-06; then split realized
net by the ENTRY-day IV/RV quartile (trailing 21d realized of the matching
forward, lag-1). Descriptive; the Nordea prior-killer bars long-expiry selling
- these are all <=6M expiries.

Run: conda run -n stir python scripts/sv_f2_gamma_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import math
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.premium_mark import straddle_delta, straddle_premium_usd
from RVUtils.StrikelessVol.straddle_book import SmileSurface

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
LOCI = [("1M", "10Y"), ("3M", "10Y"), ("6M", "10Y"), ("3M", "2Y"), ("6M", "2Y")]
HOLD = 21
CM1_HALF = {"1M": 0.71, "3M": 0.38, "6M": 0.25}
_EXP_Y = {"1M": 1 / 12, "3M": 0.25, "6M": 0.5}


def main() -> None:
    vol = pd.read_parquet(DATA / "vol_panel.parquet")
    locus = pd.read_parquet(DATA / "locus_panel_USD.parquet")
    surfaces = {}
    rows = []
    for exp, ten in LOCI:
        cell_vol = vol[(vol["tenor"] == ten) & (~vol["atm_only"])]
        if ten not in surfaces:
            surfaces[ten] = {pd.Timestamp(d): SmileSurface(g, tenor=ten)
                             for d, g in cell_vol.groupby("date")}
        surf = surfaces[ten]
        key = f"{exp.lower()}{ten.lower()}"
        fwd = locus[f"fwd_{key}"].dropna()
        ann = locus[f"ann_{key}"]
        atm = cell_vol[(cell_vol["expiry"] == exp) & (cell_vol["offset_bp"] == 0.0)]
        iv = atm.set_index("date")["vol_bp"].sort_index()
        rv = (fwd * 1e4).diff().rolling(21, min_periods=21).std() * math.sqrt(252)
        ratio = (iv / rv).shift(1)  # LAG-1 conditioning
        idx = fwd.index
        exp_yrs = _EXP_Y[exp]
        i = 21  # room for the ratio window
        while i + HOLD < len(idx):
            d0 = idx[i]
            if d0 not in surf or not np.isfinite(ratio.get(d0, np.nan)):
                i += HOLD
                continue
            F0, A0 = float(fwd[d0]), float(ann[d0])
            try:
                v0 = surf[d0].vol(expiry_yrs=exp_yrs, offset_bp=0.0)
            except (ValueError, KeyError):
                i += HOLD
                continue
            K = F0
            prem_prev = straddle_premium_usd(forward=F0, strike=K, vol_bp_annual=v0,
                                             tte_yrs=exp_yrs, annuity_per_bp=A0)
            entry_prem = prem_prev
            delta_prev, F_prev = 0.0, F0
            pnl = 0.0
            ok = True
            for k in range(1, HOLD + 1):
                d = idx[i + k]
                if d not in surf or not np.isfinite(fwd.get(d, np.nan)):
                    ok = False
                    break
                F_t, A_t = float(fwd[d]), float(ann[d])
                tte = max(exp_yrs - k / 252.0, 1e-6)
                try:
                    v_t = surf[d].vol(expiry_yrs=tte, offset_bp=(K - F_t) * 1e4)
                except (ValueError, KeyError):
                    ok = False
                    break
                prem_t = straddle_premium_usd(forward=F_t, strike=K, vol_bp_annual=v_t,
                                              tte_yrs=tte, annuity_per_bp=A_t)
                pnl += -(prem_t - prem_prev) + delta_prev * (F_t - F_prev) * 1e4 * A_t
                delta_prev = straddle_delta(forward=F_t, strike=K, vol_bp_annual=v_t,
                                            tte_yrs=tte)
                F_prev, prem_prev = F_t, prem_t
            if ok:
                # vega$ at entry for cost + normalisation
                p_up = straddle_premium_usd(forward=F0, strike=K, vol_bp_annual=v0 + 0.5,
                                            tte_yrs=exp_yrs, annuity_per_bp=A0)
                p_dn = straddle_premium_usd(forward=F0, strike=K, vol_bp_annual=v0 - 0.5,
                                            tte_yrs=exp_yrs, annuity_per_bp=A0)
                vega = p_up - p_dn
                cost = 2.0 * CM1_HALF[exp] * vega
                rows.append({"locus": f"{exp}x{ten}", "date": d0,
                             "ivrv": float(ratio[d0]), "iv": float(iv.get(d0, np.nan)),
                             "gross_usd": pnl, "net_usd": pnl - cost,
                             "net_volbp": (pnl - cost) / vega,
                             "entry_prem_usd": entry_prem})
            i += HOLD

    df = pd.DataFrame(rows)
    df.to_parquet(DATA / "f2_gamma_gate.parquet", index=False)
    pd.set_option("display.width", 220)
    for locus_name, g in df.groupby("locus"):
        g = g.dropna(subset=["ivrv"])
        g["q"] = pd.qcut(g["ivrv"], 4, labels=["q1_low", "q2", "q3", "q4_high"])
        agg = g.groupby("q", observed=True)["net_volbp"].agg(["count", "median", "mean"])
        spread = float(g[g["q"] == "q4_high"]["net_volbp"].median()
                       - g[g["q"] == "q1_low"]["net_volbp"].median())
        print(f"\n{locus_name}: short-straddle 21bd net (vol bp of vega), by entry IV/RV quartile")
        print(agg.to_string(float_format=lambda x: f"{x:7.3f}"))
        print(f"  q4-q1 spread: {spread:+.3f} vol bp | unconditional median "
              f"{float(g['net_volbp'].median()):+.3f}, hit {float((g['net_volbp']>0).mean()):.0%}")
    print("\nwrote f2_gamma_gate.parquet")


if __name__ == "__main__":
    main()
