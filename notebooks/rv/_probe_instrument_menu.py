"""Which SFR instrument carries a LEVEL view best, per unit of cost.

The signal is a level signal -- receive the front end -- so the instrument
question is: how much of a strip move does each structure capture, and what does
capturing it cost. Packs are included because a pack is quoted as the average of
its legs, so it costs the SAME 0.50bp of its own quote as an outright while
diversifying single-contract basis risk across four.

All roll-safe: every horizon change reads the same contracts at both ends.
"""
from __future__ import annotations

import io
import pathlib
import pickle
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fed_detachment_prices as PX  # noqa: E402
import sfr_flattener_structuring as S  # noqa: E402

pd.set_option("display.width", 200)
rates = S.rate_panel()
idx = rates.index[rates.index >= pd.Timestamp("2019-09-27")]
H = 21          # the window the betas are measured over
H8 = 42         # ~2 months, the trade horizon

MENU = {
    "OUT r1 (U26)": [1], "OUT r2 (Z26)": [2], "OUT r3 (H27)": [3],
    "OUT r4 (M27)": [4], "OUT r5 (U27)": [5], "OUT r6 (Z27)": [6],
    "OUT r7 (H28)": [7], "OUT r8 (M28)": [8],
    "WHITE pack r1-4": [1, 2, 3, 4],
    "RED pack r5-8": [5, 6, 7, 8],
    "mid pack r3-6": [3, 4, 5, 6],
    "8-bundle r1-8": [1, 2, 3, 4, 5, 6, 7, 8],
}
LEVEL = [1, 2, 3, 4, 5, 6, 7, 8]


def basket(t, u, ranks):
    """Mean rate change in bp across a basket, on contracts fixed at t."""
    syms = [PX.rank_symbol(t.date(), r) for r in ranks]
    exp = min(pd.Timestamp(PX.contract_window(s).end) for s in syms)
    if exp <= u:
        return None
    try:
        d = [(rates.at[u, s] - rates.at[t, s]) * 100.0 for s in syms]
    except KeyError:
        return None
    return float(np.mean(d)) if all(np.isfinite(d)) else None


for horizon, tag in ((H, "21bd"), (H8, "42bd (~2 months)")):
    recs = {k: [] for k in MENU}
    lev = []
    for k in range(len(idx) - horizon):
        t, u = idx[k], idx[k + horizon]
        L = basket(t, u, LEVEL)
        if L is None:
            continue
        vals = {name: basket(t, u, rs) for name, rs in MENU.items()}
        if any(v is None for v in vals.values()):
            continue
        lev.append(L)
        for name, v in vals.items():
            recs[name].append(v)
    Lv = np.asarray(lev)
    rows = []
    for name, rs in MENU.items():
        y = np.asarray(recs[name])
        if y.size < 50:
            continue
        beta = float(np.polyfit(Lv, y, 1)[0])
        # a pack is quoted as the AVERAGE of its legs: n contracts, n x the risk,
        # so 2 * 0.25 * n / n = 0.50bp of the pack quote, same as an outright
        cost = 0.50
        rows.append({
            "instrument": name, "n_legs": len(rs), "n": int(y.size),
            "beta_to_level": beta, "cost_bp": cost,
            "beta_per_bp_cost": beta / cost,
            "sd_move_bp": float(y.std(ddof=1)),
            "bp_on_a_25bp_rally": -beta * 25.0,      # rally = level falls
            "net_of_cost": -beta * 25.0 - cost,
            "capture_ratio": abs(beta) / (float(y.std(ddof=1)) + 1e-9),
        })
    T = pd.DataFrame(rows).sort_values("beta_per_bp_cost", ascending=False)
    print("\n" + "=" * 92)
    print(f"INSTRUMENT MENU -- level capture per unit cost, horizon {tag}")
    print("=" * 92)
    print(T.to_string(index=False))

print("\n" + "=" * 92)
print("FOR CONTRAST: the two-leg calendar spreads, same measure")
print("=" * 92)
rows = []
for i, j in ((3, 5), (3, 6), (5, 8), (1, 3)):
    bw = S.both_ways(rates, i, j, horizon_bd=H)
    if "beta_all" not in bw:
        continue
    rows.append({"instrument": f"spread r{i}-r{j}", "beta_to_level": bw["beta_all"],
                 "cost_bp": S.SPREAD_ROUND_TRIP_BP,
                 "beta_per_bp_cost": bw["beta_all"] / S.SPREAD_ROUND_TRIP_BP,
                 "bp_on_a_25bp_rally": -bw["beta_all"] * 25.0,
                 "net_of_cost": -bw["beta_all"] * 25.0 - S.SPREAD_ROUND_TRIP_BP})
print(pd.DataFrame(rows).to_string(index=False))
print("\n  A spread's beta to the level is small BY CONSTRUCTION -- that is what a")
print("  spread is for. It is the wrong instrument for a level view, and it costs")
print("  twice as much to hold.")

print("\n" + "=" * 92)
print("PR #501's 8-WEEK SLICE, BY STRUCTURE (what the signal itself preferred)")
print("=" * 92)
pk = pathlib.Path(r"C:/Users/chris/clee/ARBS-fdx/notebooks/rv/"
                  r"fed_expected_sentiment_results.pkl")
if pk.exists():
    R = pickle.load(open(pk, "rb"))
    r = R["SR3"]
    lg = r["league"]
    h8 = lg[(lg["horizon_w"] == 8) & lg["sharpe"].notna()]
    g = (h8.groupby("structure")
           .agg(cells=("sharpe", "size"), median_sharpe_wk=("sharpe", "median"),
                best_sharpe_wk=("sharpe", "max"),
                median_avg_bp=("avg_bp", "median"),
                median_trades=("trades", "median"))
           .sort_values("median_sharpe_wk", ascending=False))
    g["null_median"] = r["null_summary"]["median"]
    g["best_beats_null"] = g["best_sharpe_wk"] > r["null_summary"]["median"]
    print(g.to_string())
    print("\n  Every one of them is below the null median -- this ranks structures")
    print("  WITHIN a dead grid, so read it as 'where the noise was least bad',")
    print("  not as a selection.")
else:
    print("  #501 pickle not found")
print("\nDONE", flush=True)
