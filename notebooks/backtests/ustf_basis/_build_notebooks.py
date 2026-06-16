"""Generate the four UST-futures basis strategy notebooks (config-driven)."""
import os

import nbformat as nbf
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = os.path.dirname(__file__)

HEADER = (
    "import sys, os\n"
    "REPO = r\"C:\\\\Users\\\\chris\\\\clee\\\\ARBS\"\n"
    "if REPO not in sys.path:\n"
    "    sys.path.insert(0, REPO)\n"
    "import datetime\n"
    "import pandas as pd\n"
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "pd.options.display.float_format = lambda x: f'{x:,.2f}'\n"
)

TENORS = '["TU", "FV", "TY", "US"]'
DATES = "START, END = datetime.date(2024, 6, 1), datetime.date(2026, 5, 31)"
SPEC = "SPECIALNESS_BPS = {\"TU\": 5.0, \"FV\": 8.0, \"TY\": 10.0, \"US\": 12.0}  # CTD repo specialness"


def write(name, cells):
    nb = new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as f:
        nbf.write(nb, f)
    print("wrote", path)


# ---------------------------------------------------------------- Notebook 1
nb1 = [
    new_markdown_cell(
        "# 01 — Systematic CTD Basis (cash-and-carry)\n\n"
        "**Trade.** Long the basis = **buy the CTD cash bond** (financed in repo) and **sell CF-weighted futures** "
        "(= cash-and-carry = *long* the delivery optionality + carry). Short the basis = the reverse. We hold the "
        "front-contract CTD basis **continuously, rolling each quarter**, across TU/FV/TY/US, and mark to market daily.\n\n"
        "**PnL** (long basis, per day):\n"
        "`daily = cash_MTM(+) + futures_VM(short) + coupon_accrual(+) − repo_financing(−)`  "
        "≈ `(face/100)·Δ(grossbasis = B − cf·F) + (coupon − repo)`.\n\n"
        "**Financing.** SOFR GC proxy (`load_us_treasury_gc_fixing_pct`) **− CTD specialness**, ACT/360, on the cash "
        "leg's daily dirty value. Cash leg priced with QuantLib (FedInvest); futures + CTD/CF from `USTFuturesMDP`.\n\n"
        "Built on the new `USTFutureBasis` Query object + `USTFutureBasisHandler` and the "
        "`BT.signals.ustf_basis.run_ustf_basis_backtest` runner."
    ),
    new_code_cell(
        HEADER
        + "from BT.signals.ustf_basis import UstfBasisConfig, run_ustf_basis_backtest, plot_pnl\n"
    ),
    new_code_cell(
        "# ---- config ----\n"
        f"{DATES}\n"
        f"TENORS = {TENORS}\n"
        f"{SPEC}\n"
        "BOND_FACE = 100_000_000.0   # cash face per tenor; futures CF-weighted to it\n"
        "TX_COST_32NDS = 0.5         # round-trip basis cost per roll\n\n"
        "cfg_long = UstfBasisConfig(tenors=TENORS, start=START, end=END, direction=+1,\n"
        "                           bond_face=BOND_FACE, specialness_bps=SPECIALNESS_BPS,\n"
        "                           tx_cost_32nds=TX_COST_32NDS, show_progress=True)\n"
        "cfg_short = UstfBasisConfig(tenors=TENORS, start=START, end=END, direction=-1,\n"
        "                            bond_face=BOND_FACE, specialness_bps=SPECIALNESS_BPS,\n"
        "                            tx_cost_32nds=TX_COST_32NDS, show_progress=True)"
    ),
    new_code_cell("res_long = run_ustf_basis_backtest(cfg_long)\nres_long.combined.tail()"),
    new_code_cell("fig = plot_pnl(res_long, title='Systematic LONG CTD basis — daily MTM PnL')"),
    new_code_cell("res_short = run_ustf_basis_backtest(cfg_short)\nfig = plot_pnl(res_short, title='Systematic SHORT CTD basis — daily MTM PnL')"),
    new_markdown_cell("## PnL decomposition (long sleeve)\nTotal = price/convergence + carry (coupons − financing)."),
    new_code_cell(
        "fin = pd.DataFrame({t: c['financing'] for t, c in res_long.components_by_tenor.items()}).ffill().fillna(0.0).sum(axis=1)\n"
        "cpn = pd.DataFrame({t: c['coupons'] for t, c in res_long.components_by_tenor.items()}).ffill().fillna(0.0).sum(axis=1)\n"
        "total = res_long.combined\n"
        "price = (total - fin.reindex(total.index).ffill().fillna(0.0) - cpn.reindex(total.index).ffill().fillna(0.0))\n"
        "fig, ax = plt.subplots(figsize=(13, 6))\n"
        "ax.plot(total.index, total, label='TOTAL', color='black', lw=2)\n"
        "ax.plot(price.index, price, label='price / convergence', lw=1.2)\n"
        "ax.plot(cpn.index, cpn, label='coupons (+)', lw=1.2)\n"
        "ax.plot(fin.index, fin, label='financing (−)', lw=1.2)\n"
        "ax.axhline(0, color='grey', lw=0.6); ax.legend(); ax.grid(alpha=0.3)\n"
        "ax.set_title('Long CTD basis — PnL decomposition (combined book)'); ax.set_ylabel('cumulative $')\n"
        "plt.show()"
    ),
    new_markdown_cell("## Summary"),
    new_code_cell(
        "def summary(res, label):\n"
        "    rows = []\n"
        "    for t, s in res.mtm_by_tenor.items():\n"
        "        dd = s.diff().fillna(0.0)\n"
        "        sharpe = (dd.mean() / dd.std() * np.sqrt(252)) if dd.std() else float('nan')\n"
        "        rows.append({'sleeve': label, 'tenor': t, 'total_pnl': s.iloc[-1] if len(s) else float('nan'),\n"
        "                     'ann_sharpe': sharpe, 'days': len(s)})\n"
        "    return pd.DataFrame(rows)\n"
        "pd.concat([summary(res_long, 'long'), summary(res_short, 'short')], ignore_index=True)"
    ),
]
write("01_systematic_ctd_basis.ipynb", nb1)

# ---------------------------------------------------------------- Notebook 2
nb2 = [
    new_markdown_cell(
        "# 02 — Net-basis / BNOC relative-value signal\n\n"
        "**Idea.** BNOC (basis net of carry = net basis) is the market price of the short's **delivery options**. "
        "Trade it relative-value: **BUY the basis when BNOC is cheap** vs its trailing history (long optionality), "
        "**SELL when rich**. Mean-reversion z-score with hysteresis, per tenor; positions roll automatically with the "
        "front contract. Same correct PnL + repo financing as NB1.\n\n"
        "Uses `build_basis_panel` (daily CTD basis metrics, cached) + `bnoc_zscore_signal` + "
        "`run_ustf_basis_signal_backtest`."
    ),
    new_code_cell(
        HEADER
        + "from BT.signals.ustf_basis import (UstfBasisConfig, build_basis_panel, bnoc_zscore_signal,\n"
        "                                   run_ustf_basis_signal_backtest, plot_pnl)\n"
        "from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP"
    ),
    new_code_cell(
        f"{DATES}\n"
        f"TENORS = {TENORS}\n"
        f"{SPEC}\n"
        "Z_WINDOW, Z_ENTRY, Z_EXIT = 60, 1.0, 0.25\n"
        "cfg = UstfBasisConfig(tenors=TENORS, start=START, end=END, bond_face=100_000_000.0,\n"
        "                      specialness_bps=SPECIALNESS_BPS, tx_cost_32nds=0.5, show_progress=True)\n"
        "mdp = USTFuturesMDP(source='BARCHART_USTF-RL')"
    ),
    new_markdown_cell("Build (and cache) the daily basis panels, then run the signal backtest."),
    new_code_cell(
        "panels = {t: build_basis_panel(t, START, END, roll_days=cfg.roll_days_before_first_notice, mdp=mdp) for t in TENORS}\n"
        "signal = bnoc_zscore_signal(window=Z_WINDOW, z_entry=Z_ENTRY, z_exit=Z_EXIT)\n"
        "res = run_ustf_basis_signal_backtest(cfg, signal, mdp=mdp, panels=panels)\n"
        "fig = plot_pnl(res, title='Net-basis (BNOC) RV signal — daily MTM PnL')"
    ),
    new_markdown_cell("## BNOC z-score and position (example tenor)"),
    new_code_cell(
        "t = 'TY'\n"
        "panel = panels[t]; s = panel['bnoc'].astype(float)\n"
        "mu = s.rolling(Z_WINDOW, min_periods=20).mean(); sd = s.rolling(Z_WINDOW, min_periods=20).std()\n"
        "z = (s - mu) / sd\n"
        "pos = res.signals_by_tenor[t]\n"
        "fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 7), sharex=True, height_ratios=[2, 1])\n"
        "a1.plot(z.index, z, lw=1); a1.axhline(Z_ENTRY, color='r', ls='--', lw=0.8); a1.axhline(-Z_ENTRY, color='g', ls='--', lw=0.8)\n"
        "a1.axhline(0, color='grey', lw=0.5); a1.set_title(f'{t} BNOC z-score'); a1.grid(alpha=0.3)\n"
        "a2.plot(pos.index, pos, drawstyle='steps-post'); a2.set_ylabel('position'); a2.set_yticks([-1, 0, 1]); a2.grid(alpha=0.3)\n"
        "plt.show()"
    ),
]
write("02_net_basis_bnoc_signal.ipynb", nb2)

# ---------------------------------------------------------------- Notebook 3
nb3 = [
    new_markdown_cell(
        "# 03 — Calendar / roll spread (front vs back futures)\n\n"
        "**Trade.** The quarterly **roll**: front-contract price minus back-contract price. Futures-only (no cash leg / "
        "no repo financing) — PnL is tick variation margin on both legs. Driven by the 3-month tail repo and the "
        "front/back CTD yield spread. We enter the spread a few days before each roll and exit at the roll, per tenor.\n\n"
        "Uses the existing `USTFuture` CURVE structure via `run_ustf_calendar_roll_backtest`."
    ),
    new_code_cell(HEADER + "from BT.signals.ustf_basis import UstfBasisConfig, run_ustf_calendar_roll_backtest, plot_pnl"),
    new_code_cell(
        f"{DATES}\n"
        f"TENORS = {TENORS}\n"
        "cfg = UstfBasisConfig(tenors=TENORS, start=START, end=END, show_progress=True)\n"
        "ENTRY_DAYS_BEFORE_ROLL = 5\n"
        "CALENDAR_CONTRACTS = 100\n"
        "LONG_FRONT = True   # long front / short back (short the deferred)"
    ),
    new_code_cell(
        "res = run_ustf_calendar_roll_backtest(cfg, entry_days_before_roll=ENTRY_DAYS_BEFORE_ROLL,\n"
        "                                      calendar_contracts=CALENDAR_CONTRACTS, long_front=LONG_FRONT)\n"
        "fig = plot_pnl(res, title='Calendar / roll spread — daily MTM PnL')"
    ),
]
write("03_calendar_roll_spread.ipynb", nb3)

# ---------------------------------------------------------------- Notebook 4
nb4 = [
    new_markdown_cell(
        "# 04 — CTD-switch / delivery optionality\n\n"
        "**Idea.** The basis is *long* the short's delivery options (quality/switch, timing, end-of-month). Harvest that "
        "optionality: go **long the basis** when the option looks **cheap and likely to pay** — net basis at/below its "
        "trailing mean, **elevated realised futures vol**, and a **small CTD-vs-runner-up IRR gap** (a CTD switch is near). "
        "Long-only proxy, per tenor, with the same correct PnL + financing.\n\n"
        "> Simplified, transparent proxy for the optionality/switch trade (full wild-card/EOM valuation is out of scope). "
        "Uses `build_basis_panel` (with `irr_gap`) + `ctd_optionality_signal`."
    ),
    new_code_cell(
        HEADER
        + "from BT.signals.ustf_basis import (UstfBasisConfig, build_basis_panel, ctd_optionality_signal,\n"
        "                                   run_ustf_basis_signal_backtest, plot_pnl)\n"
        "from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP"
    ),
    new_code_cell(
        f"{DATES}\n"
        f"TENORS = {TENORS}\n"
        f"{SPEC}\n"
        "cfg = UstfBasisConfig(tenors=TENORS, start=START, end=END, bond_face=100_000_000.0,\n"
        "                      specialness_bps=SPECIALNESS_BPS, tx_cost_32nds=0.5, show_progress=True)\n"
        "mdp = USTFuturesMDP(source='BARCHART_USTF-RL')\n"
        "VOL_WINDOW, VOL_Q, IRR_GAP_MAX = 21, 0.6, 0.10"
    ),
    new_code_cell(
        "panels = {t: build_basis_panel(t, START, END, roll_days=cfg.roll_days_before_first_notice, mdp=mdp) for t in TENORS}\n"
        "signal = ctd_optionality_signal(vol_window=VOL_WINDOW, vol_quantile=VOL_Q, irr_gap_max=IRR_GAP_MAX)\n"
        "res = run_ustf_basis_signal_backtest(cfg, signal, mdp=mdp, panels=panels)\n"
        "fig = plot_pnl(res, title='CTD-switch / optionality (long-only) — daily MTM PnL')"
    ),
    new_markdown_cell("## Diagnostics (example tenor): IRR gap to runner-up + realised vol"),
    new_code_cell(
        "t = 'TY'; panel = panels[t]\n"
        "rv = panel['future_price'].astype(float).pct_change().rolling(VOL_WINDOW, min_periods=10).std()\n"
        "fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(13, 9), sharex=True)\n"
        "a1.plot(panel.index, panel['irr_gap']); a1.axhline(IRR_GAP_MAX, color='r', ls='--', lw=0.8); a1.set_title(f'{t} CTD−runner-up IRR gap (small ⇒ switch risk)'); a1.grid(alpha=0.3)\n"
        "a2.plot(rv.index, rv); a2.set_title('realised futures vol'); a2.grid(alpha=0.3)\n"
        "a3.plot(res.signals_by_tenor[t].index, res.signals_by_tenor[t], drawstyle='steps-post'); a3.set_ylabel('position'); a3.set_yticks([0, 1]); a3.grid(alpha=0.3)\n"
        "plt.show()"
    ),
]
write("04_ctd_switch_optionality.ipynb", nb4)
print("ALL NOTEBOOKS BUILT")
