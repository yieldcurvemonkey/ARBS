"""F4-conditional gate — 50bp risk-reversal mean-reversion (skew RV).

The 2025-10-08 desk ticket's signal: the ±50bp payer−receiver skew ranked
against its 1-year history; extreme decile → fade toward normal. Gate: for
gamma/belly cells with CM-1-measured costs, non-overlapping |percentile
extreme| fires → forward RR reversion at 21bd vs the 4-leg round trip
(RR = 2 legs + the vega-neutralising ATM straddle ≈ 2 more; charged as
2 x (2 x CM1 half-spread) + straddle legs at the same line — conservative
double of the straddle since wings are less liquid than ATM).

Scope: this gates the skew-RV MEAN-REVERSION expression only; the primer's
conditional trades as directional-view vehicles are out of mandate.

Run: conda run -n stir python scripts/f4b_skew_rr_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
CELLS = [("3M", "2Y"), ("3M", "10Y"), ("6M", "10Y"), ("1Y", "10Y"), ("2Y", "10Y")]
CM1_HALF = {"3M": 0.38, "6M": 0.25, "1Y": 0.21, "2Y": 0.23}
WIN = 252


def main() -> None:
    vol = pd.read_parquet(DATA / "vol_panel.parquet")
    vol = vol[~vol["atm_only"]]
    print("F4-conditional — 50bp RR fade gate (non-overlapping extreme-decile fires):")
    for exp, ten in CELLS:
        g = vol[(vol["expiry"] == exp) & (vol["tenor"] == ten)]
        p = g.pivot_table(index="date", columns="offset_bp", values="vol_bp",
                          aggfunc="last").sort_index()
        if 50.0 not in p.columns or -50.0 not in p.columns:
            continue
        rr = p[50.0] - p[-50.0]  # payer minus receiver, annual bp
        rank = rr.rolling(WIN, min_periods=126).apply(
            lambda w: (w[:-1] < w[-1]).mean(), raw=True)
        mu = rr.rolling(WIN, min_periods=126).mean()
        # 4-leg RT: RR wings 2 legs + vega-neutral straddle ~2 legs; wings at 2x ATM line
        rt = 2.0 * (2.0 * 2.0 * CM1_HALF[exp]) / 2.0 + 2.0 * CM1_HALF[exp]
        rt = 2.0 * CM1_HALF[exp] * (2.0 * 2.0 + 2.0) / 2.0  # = 3 x RT_atm; conservative
        idx = rr.index
        fires, i = [], 0
        rk = rank.to_numpy()
        while i < len(idx) - 21:
            if np.isfinite(rk[i]) and (rk[i] <= 0.10 or rk[i] >= 0.90):
                fires.append(i)
                i += 21
            else:
                i += 1
        revs = []
        for i in fires:
            d0 = rr.iloc[i] - mu.iloc[i]
            if i + 21 < len(idx) and np.isfinite(rr.iloc[i + 21]):
                revs.append(float(np.sign(d0) * (rr.iloc[i] - rr.iloc[i + 21])))
        if not revs:
            continue
        med = float(np.median(revs))
        print(f"  {exp}x{ten}: {len(fires)} fires | RR sd {rr.std():.2f}bp | "
              f"med rev 21bd {med:+.2f}bp vs RT {rt:.2f}bp ({med / rt:+.2f}x) | "
              f"frac>RT {np.mean([r > rt for r in revs]):.0%}")
    print("\n(gate only; panel arithmetic, no rateslib anchor — stated)")


if __name__ == "__main__":
    main()
