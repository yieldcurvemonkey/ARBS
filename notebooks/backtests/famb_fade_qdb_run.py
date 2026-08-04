# %% [markdown]
# # The pre-registered fade on QueryDrivenBacktest — run + reconciliation
#
# The STRG75 Q1 richness fade (thr 4bp, exit 25%, hold ≤ 15 sessions, fade
# only, one open, lag-1 — parameters frozen in the 2026-08-04 findings)
# executed through the production backtest engine: positions are
# `STIRFutureOptionQuery` STRADDLE packages marked by the MDP's QL pricers,
# entries/exits fire through Triggers, portfolio and realized PnL are the
# engine's own bookkeeping.
#
# Two deliverables: (1) the engine run over the full sample, with house
# statistics; (2) trade-by-trade reconciliation against the research
# replay (`famb_common.intra_quarter_backtest`) on the identical signal
# panel — the port is only trustworthy if the two agree up to mark-source
# and cost-timing differences.

# %%
import sys

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(".")
import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from famb_fade_qdb import (PRE_REGISTERED, build_signal_panel,
                           closed_positions_frame, make_fade_backtest)
from famb_common import intra_quarter_backtest, n_contracts
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.SFRRVLab.stats import nw_tstat

print("pre-registered:", PRE_REGISTERED)
panel, holdings = build_signal_panel(return_holdings=True)
print(f"signal panel: {len(panel)} sessions, "
      f"{panel['as_of'].min().date()} -> {panel['as_of'].max().date()}, "
      f"{panel['symbol'].nunique()} holdings' symbols")

# %% [markdown]
# ## The engine run

# %%
mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
bt = make_fade_backtest(panel, mdp, contracts=1.0, show_progress=True)
bt.run()
cl = closed_positions_frame(bt)
print(f"\nclosed positions: {len(cl)}")
if len(cl):
    show = [c for c in ("opened_at", "closed_at", "realized_pnl") if
            c in cl.columns]
    print(cl[show].round(2).to_string(index=False))
    total = cl["realized_pnl"].sum()
    hit = (cl["realized_pnl"] > 0).mean()
    print(f"\nQDB: {len(cl)} trades  hit {hit:.0%}  "
          f"total ${total:+,.0f} per 1-lot "
          f"({total / 25.0:+.1f}bp premium equivalent)")

# %%
# mtm_history is the TOTAL account value (open MTM + cumulative realized) —
# verified: it ends at the sum of realized PnL with no open positions
equity = pd.Series(bt.mtm_history).sort_index()
daily = equity.diff().dropna()
sd = daily.std(ddof=1)
if len(daily) > 5 and sd > 0:
    print(f"engine equity: {equity.iloc[-1]:+,.0f} USD end, "
          f"{len(daily)} marked days, "
          f"Sharpe {daily.mean() / sd * np.sqrt(252):+.2f}, "
          f"NW t {nw_tstat(daily.to_numpy()):+.2f}, "
          f"maxDD {(equity - equity.cummax()).min():,.0f} USD")
else:
    print("equity series too short/flat to annualize")
fig, ax = plt.subplots(figsize=(11, 3.6))
ax.step(equity.index, equity.values, where="post", color="#1f4e79", lw=1.3)
ax.axhline(0, color="grey", lw=0.6)
ax.set_title("QDB equity (MTM + realized, $ per 1-lot package)")
ax.grid(alpha=0.25)
fig.autofmt_xdate()
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Reconciliation vs the research replay
#
# Same panel, same parameters, two engines. Replay marks = panel settle
# premiums; engine marks = MDP QL pricers at the NY close (same barchart
# EOD settles underneath). Costs: replay books a round trip per trade;
# the engine books both sides as the unwind fee. Agreement is expected to
# a few $ per trade; systematic gaps mean a port bug.

# %%
replay = intra_quarter_backtest(
    holdings, thr_bp=PRE_REGISTERED["thr_bp"],
    exit_frac=PRE_REGISTERED["exit_frac"],
    max_hold=PRE_REGISTERED["max_hold"], direction="fade",
    cost_mult=1.0, n_legs=n_contracts(PRE_REGISTERED["book"]))
rp = pd.DataFrame(replay)
rp["net_usd"] = rp["net_bp"] * 25.0
print(f"replay: {len(rp)} trades  total ${rp['net_usd'].sum():+,.0f}")

if len(cl) and len(rp):
    q = cl.copy()
    q["entry_d"] = (pd.to_datetime(q["opened_at"])
                    .dt.tz_localize(None).dt.normalize())
    rp["entry_d"] = pd.to_datetime(rp["entry"]).dt.normalize()
    m = rp.merge(q, on="entry_d", how="outer", suffixes=("_replay", "_qdb"),
                 indicator=True)
    matched = m[m["_merge"] == "both"]
    print(f"\nmatched on entry date: {len(matched)}/{max(len(rp), len(cl))}")
    if len(matched):
        comp = pd.DataFrame({
            "entry": matched["entry_d"].dt.date,
            "exit_replay": pd.to_datetime(matched["exit"]).dt.date,
            "exit_qdb": pd.to_datetime(matched["closed_at"]).dt.date,
            "replay_usd": matched["net_usd"].round(1),
            "qdb_usd": matched["realized_pnl"].round(1),
            "diff_usd": (matched["realized_pnl"]
                         - matched["net_usd"]).round(1),
        })
        print(comp.to_string(index=False))
        print(f"\nmean |diff| ${comp['diff_usd'].abs().mean():.1f}  "
              f"max |diff| ${comp['diff_usd'].abs().max():.1f}  "
              f"corr {np.corrcoef(comp['replay_usd'], comp['qdb_usd'])[0, 1]:.3f}")
    unmatched = m[m["_merge"] != "both"]
    if len(unmatched):
        print(f"\nunmatched entries ({len(unmatched)}):")
        print(unmatched[["entry_d", "_merge"]].to_string(index=False))

# %% [markdown]
# ## What the port is for
#
# The research replay stays the historical evidence; this engine is the
# forward instrument. Extending the TimeGrid forward day by day turns it
# into the pre-registered one-trial test: signals from the same lattice
# machinery, marks from the production pricers, no parameter left free.
