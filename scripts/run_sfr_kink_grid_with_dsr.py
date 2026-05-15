"""SFR kink-fade grid search + Deflated Sharpe gate.

Runs the SFR kink-fade backtest across a parameter grid, then applies the
Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio as a hard gate on
strategy entry. Only configurations whose DSR probability exceeds the
threshold are reported as "survivors".

Usage::

    conda run -n stir python scripts/run_sfr_kink_grid_with_dsr.py \\
        [--threshold 0.95] [--max-configs N] [--out PATH] [--results-pickle PATH]

If `--results-pickle` is supplied and points to an existing pickle of
backtest results (list of dicts with `daily_pnl`), the script skips the
backtest and only applies the gate. Otherwise the script runs the full
grid (slow — see `_gs_results.txt` for an indicative duration).
"""
from __future__ import annotations

import argparse
import datetime
import os
import pickle
import sys
import time
import warnings
from itertools import product
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import numpy as np
import pandas as pd
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BT.signals.deflated_sharpe import apply_dsr_gate, expected_max_sharpe_null
from BT.signals.sfr_kink_fade import compute_pca_residual_rates, run_backtest
from BT.signals.sfr_cal_spread_rv import SFRCalSpreadRVConfig, load_rate_panel
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.TimeseriesBuilder import TimeseriesBuilder


NYC = pytz.timezone("America/New_York")


# ─────────────────────────────────────────────────────────────────────
# Grid definition (mirrors notebooks/backtests/sfr_kink_fade_grid_search.ipynb)
# ─────────────────────────────────────────────────────────────────────

BASE_CONFIG = {
    "source": "BARCHART_STIRF-RL",
    "curve": "USD-SOFR-1D-Q12STIRT",
    "n_contracts": 12,
    "constant_maturity": True,
    "vol_window": 20,
    "carry_horizon": 1,
    "percentile_window": 60,
    "halflife_window": 120,
    "no_duplicate_structures": True,
    "belly_bpv": 100_000,
    "regime_max_adf_pvalue": None,
    "regime_min_halflife_days": 3.0,
    "regime_max_halflife_days": 120.0,
}

GRID = {
    "structures": [
        ["bf_3m"],
        ["bf_6m"],
        ["df_3m"],
        ["bf_3m", "df_3m"],
    ],
    "zscore_window": [20, 40, 60, 120],
    "entry_min_zscore": [1.0, 1.5, 2.0, 2.5],
    "exit_preset": [
        {"exit_mean_reversion": True,  "exit_stop_loss_sd": None, "exit_take_profit_zscore": None, "exit_max_holding_days": 44},
        {"exit_mean_reversion": True,  "exit_stop_loss_sd": 2.0,  "exit_take_profit_zscore": None, "exit_max_holding_days": 22},
        {"exit_mean_reversion": False, "exit_stop_loss_sd": None, "exit_take_profit_zscore": None, "exit_max_holding_days": 10},
        {"exit_mean_reversion": False, "exit_stop_loss_sd": None, "exit_take_profit_zscore": None, "exit_max_holding_days": 21},
        {"exit_mean_reversion": False, "exit_stop_loss_sd": 2.0,  "exit_take_profit_zscore": 0.5,  "exit_max_holding_days": 22},
    ],
    "regime_preset": [
        {"regime_fomc_blackout_days": None, "regime_halflife_gated": False, "regime_vol_filter": False, "signal_mode": "zscore"},
        {"regime_fomc_blackout_days": 5,    "regime_halflife_gated": False, "regime_vol_filter": False, "signal_mode": "zscore"},
        {"regime_fomc_blackout_days": 5,    "regime_halflife_gated": True,  "regime_vol_filter": False, "signal_mode": "zscore"},
        {"regime_fomc_blackout_days": 5,    "regime_halflife_gated": False, "regime_vol_filter": False, "signal_mode": "pca_residual"},
    ],
    "max_concurrent_trades": [3, 5],
}

EXIT_LABELS = ["MR_44d", "MR+S2_22d", "Fix_10d", "Fix_21d", "TP05+S2_22d"]
REGIME_LABELS = ["NoFilter", "FOMC5", "FOMC5+HL", "FOMC5+PCA"]


def build_grid() -> list[dict]:
    configs: list[dict] = []
    for structs, zw, z, (ei, exit_p), (ri, regime_p), max_ct in product(
        GRID["structures"],
        GRID["zscore_window"],
        GRID["entry_min_zscore"],
        enumerate(GRID["exit_preset"]),
        enumerate(GRID["regime_preset"]),
        GRID["max_concurrent_trades"],
    ):
        cfg = dict(BASE_CONFIG)
        cfg["structures"] = list(structs)
        cfg["zscore_window"] = zw
        cfg["entry_min_zscore"] = z
        cfg["max_concurrent_trades"] = max_ct
        cfg.update(exit_p)
        cfg.update(regime_p)
        cfg["_label"] = (
            f"{'+'.join(structs)}|zw{zw}|z{z}|"
            f"{EXIT_LABELS[ei]}|{REGIME_LABELS[ri]}|ct{max_ct}"
        )
        configs.append(cfg)
    return configs


# ─────────────────────────────────────────────────────────────────────
# Data loading + grid execution
# ─────────────────────────────────────────────────────────────────────

def load_data(data_start: str, bt_start: str, bt_end: str):
    print("=" * 70)
    print("LOADING DATA")
    print("=" * 70)
    curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    ts_builder = TimeseriesBuilder()

    sfr_config = SFRCalSpreadRVConfig(
        n_contracts=12, zscore_window=60, vol_window=20,
        constant_maturity=True, source="BARCHART_STIRF-RL",
        curve="USD-SOFR-1D-Q12STIRT",
    )

    start = NYC.localize(datetime.datetime.fromisoformat(data_start).replace(hour=18))
    rates = load_rate_panel(
        sfr_config, start=start, end=bt_end,
        curve_mdp=curve_mdp, ts_builder=ts_builder,
    )
    print(f"Rate panel: {rates.shape[0]} dates x {rates.shape[1]} contracts")

    print("Computing PCA residual rates...")
    pca_residual_rates = compute_pca_residual_rates(rates, n_components=3, window=252)
    print("Done.")

    bt_start_dt = NYC.localize(datetime.datetime.fromisoformat(bt_start).replace(hour=17))
    bt_end_dt = (
        NYC.localize(datetime.datetime.now())
        if bt_end == "live"
        else NYC.localize(datetime.datetime.fromisoformat(bt_end).replace(hour=17))
    )
    bt_dates = pd.bdate_range(bt_start_dt, bt_end_dt, tz=NYC)
    bt_datetimes = [d.to_pydatetime() for d in bt_dates]
    print(f"Backtest: {len(bt_datetimes)} steps ({bt_start_dt.date()} -> {bt_end_dt.date()})")

    return curve_mdp, rates, pca_residual_rates, bt_datetimes


def run_grid(configs, rates, curve_mdp, bt_datetimes, pca_residual_rates) -> list[dict]:
    print("\n" + "=" * 70)
    print(f"GRID SEARCH ({len(configs)} configs)")
    print("=" * 70)
    results: list[dict] = []
    t0 = time.time()
    for i, cfg in enumerate(configs):
        label = cfg.pop("_label")
        try:
            res = run_backtest(
                cfg, rates, curve_mdp, bt_datetimes,
                pca_residual_rates=pca_residual_rates,
            )
            res["label"] = label
        except Exception as e:
            res = {"label": label, "sharpe": np.nan, "error": str(e),
                   "daily_pnl": [], "sr_per_period": 0.0,
                   "T_obs": 0, "skew": 0.0, "kurt": 3.0,
                   "n_trades": 0, "n_closed": 0}
        results.append(res)

        if (i + 1) % 25 == 0 or i == len(configs) - 1:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(configs) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{len(configs)}] {elapsed:.0f}s elapsed, ~{eta:.0f}s ETA")
    return results


# ─────────────────────────────────────────────────────────────────────
# Gate application + reporting
# ─────────────────────────────────────────────────────────────────────

def gate_and_report(results: list[dict], threshold: float) -> pd.DataFrame:
    df = pd.DataFrame(results)
    print("\n" + "=" * 70)
    print(f"DEFLATED SHARPE GATE  (threshold={threshold:.2f})")
    print("=" * 70)
    print(f"Total trials: {len(df)}")

    # Apply the gate using the empirical cross-trial Sharpe variance.
    gated = apply_dsr_gate(df, returns_col="daily_pnl", threshold=threshold)

    sr0 = float(gated["dsr_sr0"].iloc[0]) if len(gated) else float("nan")
    sr_var_empirical = float(
        np.var(gated.loc[gated["T_obs"] >= 3, "sr_per_period"], ddof=1)
    ) if (gated["T_obs"] >= 3).sum() >= 2 else 0.0
    print(f"Empirical per-period Sharpe variance across trials: {sr_var_empirical:.6f}")
    print(f"Benchmark per-period SR0 (E[max] under null, N={len(gated)}): {sr0:.5f}")
    print(f"Equivalent annualised SR0: {sr0 * np.sqrt(252):.3f}")

    survivors = gated[gated["dsr_pass"]].copy()
    survivors = survivors.sort_values("dsr_prob", ascending=False)
    print(f"\nSurvivors (dsr_prob >= {threshold:.2f}): {len(survivors)} / {len(gated)} "
          f"({len(survivors) / max(len(gated), 1):.1%})")

    if len(survivors):
        cols = ["label", "sharpe", "dsr_prob", "dsr_z", "sr_per_period",
                "skew", "kurt", "T_obs", "final_mtm", "max_dd", "n_closed"]
        print("\nTOP SURVIVORS BY DSR PROBABILITY:")
        for _, row in survivors[cols].head(20).iterrows():
            print(
                f"  {row['label']:55s}  "
                f"DSR={row['dsr_prob']:.3f}  z={row['dsr_z']:+.2f}  "
                f"Sharpe={row['sharpe']:+.2f}  skew={row['skew']:+.2f}  kurt={row['kurt']:.2f}  "
                f"MTM=${row['final_mtm']:>14,.0f}  N={int(row['n_closed']):>3d}"
            )
    else:
        print("\n  (none — no configuration survives the gate)")

    # Why didn't the top-Sharpe configs survive?
    top_by_sharpe = gated.sort_values("sharpe", ascending=False).head(10)
    print("\nTOP 10 BY OBSERVED SHARPE (regardless of DSR):")
    for _, row in top_by_sharpe.iterrows():
        flag = "PASS" if row["dsr_pass"] else "FAIL"
        print(
            f"  [{flag}] {row['label']:55s}  "
            f"Sharpe={row['sharpe']:+.2f}  DSR={row['dsr_prob']:.3f}  "
            f"skew={row['skew']:+.2f}  kurt={row['kurt']:.2f}  T={int(row['T_obs'])}"
        )

    return gated


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=float, default=0.95,
                   help="DSR probability threshold for the entry gate (default 0.95).")
    p.add_argument("--max-configs", type=int, default=None,
                   help="Cap the number of configs (useful for smoke runs).")
    p.add_argument("--results-pickle", type=str, default=None,
                   help="Path to a pre-computed results pickle. Skips backtesting "
                        "and only applies the gate.")
    p.add_argument("--out", type=str, default=None,
                   help="Path to write the gated results DataFrame (CSV or pickle).")
    p.add_argument("--save-raw", type=str, default=None,
                   help="If running the grid, dump raw results to this pickle "
                        "(so the gate can be re-applied later without re-running).")
    p.add_argument("--data-start", type=str, default="2024-01-01")
    p.add_argument("--bt-start", type=str, default="2024-06-01")
    p.add_argument("--bt-end", type=str, default="live")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.results_pickle:
        print(f"Loading pre-computed results from {args.results_pickle}")
        with open(args.results_pickle, "rb") as f:
            results = pickle.load(f)
    else:
        configs = build_grid()
        if args.max_configs is not None:
            configs = configs[: args.max_configs]
            print(f"Capped grid to {len(configs)} configs")

        curve_mdp, rates, pca_residual_rates, bt_datetimes = load_data(
            args.data_start, args.bt_start, args.bt_end,
        )
        results = run_grid(configs, rates, curve_mdp, bt_datetimes, pca_residual_rates)

        if args.save_raw:
            with open(args.save_raw, "wb") as f:
                pickle.dump(results, f)
            print(f"Raw results saved to {args.save_raw}")

    gated = gate_and_report(results, threshold=args.threshold)

    if args.out:
        out_path = Path(args.out)
        # Drop the heavy daily_pnl column for CSV; keep it for pickle.
        if out_path.suffix.lower() == ".csv":
            gated.drop(columns=["daily_pnl"], errors="ignore").to_csv(out_path, index=False)
        else:
            gated.to_pickle(out_path)
        print(f"\nGated results saved to {out_path}")


if __name__ == "__main__":
    main()
