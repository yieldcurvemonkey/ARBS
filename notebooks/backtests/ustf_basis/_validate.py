"""Quick validation of the basis runner across a roll boundary (throwaway)."""
import datetime

import pandas as pd

from BT.signals.ustf_basis import UstfBasisConfig, contract_segments, run_ustf_basis_backtest, GOVT_CAL

START, END = datetime.date(2025, 8, 11), datetime.date(2025, 9, 19)

# show the roll calendar
import pandas as pd
dates = [d.date() for d in pd.bdate_range(START, END)]
segs = contract_segments("TY", dates, roll_days=6, cal=GOVT_CAL)
print("segments:", [(s.symbol, str(s.start), str(s.end)) for s in segs])

cfg = UstfBasisConfig(tenors=["TY"], start=START, end=END, bond_face=100_000_000.0, direction=1, show_progress=True)
res = run_ustf_basis_backtest(cfg)

mtm = res.mtm_by_tenor["TY"]
grid = res.time_grid_dates
fin = res.components_by_tenor["TY"]["financing"]
cpn = res.components_by_tenor["TY"]["coupons"]

print(f"\ngrid days = {len(grid)}, mtm days = {len(mtm)}")
gaps = sorted(set(grid) - set(mtm.index))
print(f"gaps = {gaps}")
print(f"final cumulative MTM PnL = ${mtm.iloc[-1]:,.0f}")
print(f"final financing (cost)   = ${fin.iloc[-1]:,.0f}")
print(f"final coupons            = ${cpn.iloc[-1]:,.0f}")
# price/convergence component = total - realized(financing+coupons)
price = mtm - fin.reindex(mtm.index).ffill().fillna(0.0) - cpn.reindex(mtm.index).ffill().fillna(0.0)
print(f"final price/convergence  = ${price.iloc[-1]:,.0f}")
print(f"max |daily pnl|          = ${mtm.diff().abs().max():,.0f}")
print(f"# closed trades (roll)   = {len(res.backtests['TY'].portfolio.closed_positions_log)}")

assert len(mtm) == len(grid), f"MTM GAPS: {gaps}"
assert fin.iloc[-1] < 0.0, "long-basis financing should be a cost"

# --- save a real sample figure (cached data; no Barchart) ---
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.makedirs(os.path.join(os.path.dirname(__file__), "_results"), exist_ok=True)
out = os.path.join(os.path.dirname(__file__), "_results", "sample_ty_long_basis_aug_sep_2025.png")
fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[2, 1], sharex=True)
a1.plot(mtm.index, mtm.values, color="black", lw=2, label="TOTAL")
price = mtm - fin.reindex(mtm.index).ffill().fillna(0.0) - cpn.reindex(mtm.index).ffill().fillna(0.0)
a1.plot(price.index, price.values, lw=1.2, label="price / convergence")
a1.plot(cpn.index, cpn.values, lw=1.2, label="coupons (+)")
a1.plot(fin.index, fin.values, lw=1.2, label="financing (−)")
a1.axhline(0, color="grey", lw=0.6); a1.legend(); a1.grid(alpha=0.3)
a1.set_title("Sample: TY LONG CTD basis — $100mm — Aug–Sep 2025 (rolls TYU25→TYZ25)")
a1.set_ylabel("cumulative PnL ($)")
a2.bar(mtm.index, mtm.diff().fillna(0.0).values, width=1.0, color="steelblue")
a2.set_ylabel("daily PnL ($)"); a2.grid(alpha=0.3)
fig.tight_layout()
import os as _os
_os.makedirs(_os.path.dirname(out), exist_ok=True)
fig.savefig(out, dpi=110)
print(f"saved {out}")
print("\nVALIDATION OK")
