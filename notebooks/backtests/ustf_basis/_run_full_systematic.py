"""Full 2y systematic CTD basis run (long + short sleeves, TU/FV/TY/US).

Runs in the background; saves per-tenor cumulative MTM + components + figures to
notebooks/backtests/ustf_basis/_results/. Processes TY first so the headline graph
is available soonest. Re-runs are cheap once the MDP caches are warm.
"""
import datetime
import os
import sys
import traceback

import pandas as pd

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

from BT.signals.ustf_basis import UstfBasisConfig, run_ustf_basis_backtest, plot_pnl, UstfBasisResult
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

RESULTS = os.path.join(os.path.dirname(__file__), "_results")
os.makedirs(RESULTS, exist_ok=True)

START = datetime.date(2024, 6, 1)
END = datetime.date(2026, 5, 31)
TENORS = ["TY", "US", "FV", "TU"]            # TY first (headline)
SPECIALNESS_BPS = {"TU": 5.0, "FV": 8.0, "TY": 10.0, "US": 12.0}
BOND_FACE = 100_000_000.0
TX_COST_32NDS = 0.5

mdp = USTFuturesMDP(source="BARCHART_USTF-RL")


def _log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_side(direction, label):
    mtm = {}
    fin = {}
    cpn = {}
    for tenor in TENORS:
        _log(f"=== {label} {tenor} ===")
        try:
            cfg = UstfBasisConfig(
                tenors=[tenor],
                start=START,
                end=END,
                direction=direction,
                bond_face=BOND_FACE,
                specialness_bps=SPECIALNESS_BPS,
                tx_cost_32nds=TX_COST_32NDS,
                show_progress=True,
            )
            res = run_ustf_basis_backtest(cfg, mdp=mdp)
            s = res.mtm_by_tenor[tenor]
            mtm[tenor] = s
            fin[tenor] = res.components_by_tenor[tenor]["financing"]
            cpn[tenor] = res.components_by_tenor[tenor]["coupons"]
            _log(f"{label} {tenor}: days={len(s)} final=${s.iloc[-1]:,.0f} "
                 f"fin=${fin[tenor].iloc[-1]:,.0f} cpn=${cpn[tenor].iloc[-1]:,.0f}")
            # incremental save
            pd.DataFrame(mtm).to_parquet(os.path.join(RESULTS, f"systematic_{label}_mtm.parquet"))
            pd.DataFrame(fin).to_parquet(os.path.join(RESULTS, f"systematic_{label}_financing.parquet"))
            pd.DataFrame(cpn).to_parquet(os.path.join(RESULTS, f"systematic_{label}_coupons.parquet"))
        except Exception as e:
            _log(f"FAILED {label} {tenor}: {e}")
            traceback.print_exc()
    return mtm, fin, cpn


def save_figure(mtm, label):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        df = pd.DataFrame(mtm).sort_index().ffill()
        fig, ax = plt.subplots(figsize=(13, 7))
        for col in df.columns:
            ax.plot(df.index, df[col], label=col, lw=1.3)
        combined = df.ffill().fillna(0.0).sum(axis=1)
        ax.plot(combined.index, combined.values, label="COMBINED", color="black", lw=2.0)
        ax.axhline(0.0, color="grey", lw=0.6)
        ax.set_title(f"UST futures basis — systematic {label} CTD basis (2y daily MTM PnL)")
        ax.set_ylabel("cumulative PnL ($)")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(RESULTS, f"systematic_{label}.png"), dpi=110)
        _log(f"saved figure systematic_{label}.png")
    except Exception as e:
        _log(f"figure save failed for {label}: {e}")


if __name__ == "__main__":
    _log("START full systematic 2y run")
    long_mtm, long_fin, long_cpn = run_side(+1, "long")
    save_figure(long_mtm, "long")
    short_mtm, short_fin, short_cpn = run_side(-1, "short")
    save_figure(short_mtm, "short")

    # summary
    rows = []
    for label, mtm, fin, cpn in [("long", long_mtm, long_fin, long_cpn), ("short", short_mtm, short_fin, short_cpn)]:
        for t in mtm:
            rows.append({
                "sleeve": label, "tenor": t, "days": len(mtm[t]),
                "total_pnl": float(mtm[t].iloc[-1]) if len(mtm[t]) else float("nan"),
                "financing": float(fin[t].iloc[-1]) if len(fin[t]) else 0.0,
                "coupons": float(cpn[t].iloc[-1]) if len(cpn[t]) else 0.0,
            })
    pd.DataFrame(rows).to_csv(os.path.join(RESULTS, "systematic_summary.csv"), index=False)
    _log("DONE full systematic 2y run")
