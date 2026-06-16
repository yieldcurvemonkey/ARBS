"""NB-02 (BNOC RV) + NB-04 (CTD-switch) end-to-end, clean serial run.

Builds the daily basis panels (cache-served off the warm basket cache), runs both
signal backtests, and saves figures + summaries to _results/. Monitor via the parquet
/ png artifacts (conda buffers stdout).
"""
import datetime
import os
import traceback

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from BT.signals.ustf_basis import (
    UstfBasisConfig,
    bnoc_zscore_signal,
    build_basis_panel,
    ctd_optionality_signal,
    run_ustf_basis_signal_backtest,
)
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

RESULTS = os.path.join(os.path.dirname(__file__), "_results")
os.makedirs(RESULTS, exist_ok=True)

START, END = datetime.date(2024, 6, 1), datetime.date(2026, 5, 31)
TENORS = ["TY", "US", "FV", "TU"]
SPEC = {"TU": 5.0, "FV": 8.0, "TY": 10.0, "US": 12.0}
mdp = USTFuturesMDP(source="BARCHART_USTF-RL")


def log(m):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {m}", flush=True)


def save_fig(res, label, title):
    df = pd.DataFrame(res.mtm_by_tenor).sort_index().ffill()
    fig, ax = plt.subplots(figsize=(13, 7))
    for c in df.columns:
        ax.plot(df.index, df[c], label=c, lw=1.2)
    combined = df.ffill().fillna(0.0).sum(axis=1)
    ax.plot(combined.index, combined.values, label="COMBINED", color="black", lw=2.0)
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_title(title)
    ax.set_ylabel("cumulative PnL ($)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, f"{label}.png"), dpi=110)
    df.to_parquet(os.path.join(RESULTS, f"{label}_mtm.parquet"))
    log(f"saved {label}.png")


def summarize(res, label):
    rows = []
    for t, s in res.mtm_by_tenor.items():
        sig = res.signals_by_tenor.get(t)
        # trades = sign changes in the desired-position series
        nflips = int((sig.fillna(0).diff().fillna(0) != 0).sum()) if sig is not None else 0
        rows.append({"strategy": label, "tenor": t, "days": len(s),
                     "total_pnl": float(s.iloc[-1]) if len(s) else float("nan"),
                     "position_changes": nflips,
                     "closed_trades": len(res.backtests[t].portfolio.closed_positions_log)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    log("START signal strategies (NB-02, NB-04)")

    panels = {}
    for t in TENORS:
        try:
            log(f"=== panel {t} ===")
            p = build_basis_panel(t, START, END, roll_days=6, mdp=mdp, show_progress=True)
            panels[t] = p
            cov = len(p)
            log(f"panel {t}: rows={cov}  bnoc[min,max]=[{p['bnoc'].min():.3f},{p['bnoc'].max():.3f}]")
        except Exception as e:
            log(f"panel {t} FAILED: {e}")
            traceback.print_exc()

    cfg = UstfBasisConfig(tenors=TENORS, start=START, end=END, bond_face=100_000_000.0,
                          specialness_bps=SPEC, tx_cost_32nds=0.5, show_progress=True)

    summaries = []
    try:
        log("=== NB-02 BNOC RV signal ===")
        res2 = run_ustf_basis_signal_backtest(cfg, bnoc_zscore_signal(window=60, z_entry=1.0, z_exit=0.25), mdp=mdp, panels=panels)
        save_fig(res2, "bnoc_signal", "Net-basis (BNOC) RV signal — 2y daily MTM PnL")
        summaries.append(summarize(res2, "bnoc_rv"))
        log(f"BNOC combined final = ${res2.combined.iloc[-1]:,.0f}")
    except Exception as e:
        log(f"NB-02 FAILED: {e}")
        traceback.print_exc()

    try:
        log("=== NB-04 CTD-switch / optionality signal ===")
        res4 = run_ustf_basis_signal_backtest(cfg, ctd_optionality_signal(vol_window=21, vol_quantile=0.6, irr_gap_max=0.10), mdp=mdp, panels=panels)
        save_fig(res4, "ctd_switch_signal", "CTD-switch / optionality (long-only) — 2y daily MTM PnL")
        summaries.append(summarize(res4, "ctd_switch"))
        log(f"CTD-switch combined final = ${res4.combined.iloc[-1]:,.0f}")
    except Exception as e:
        log(f"NB-04 FAILED: {e}")
        traceback.print_exc()

    if summaries:
        out = pd.concat(summaries, ignore_index=True)
        out.to_csv(os.path.join(RESULTS, "signal_summary.csv"), index=False)
        log("\n" + out.to_string(index=False))
    log("DONE signal strategies")
