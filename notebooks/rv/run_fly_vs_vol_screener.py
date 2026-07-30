"""EOD fly-vs-vol screener over the live SFR option strip.

Fetches daily SABR smiles (Barchart EOD caches make reruns local), extracts BL
marginals, builds fly-vs-vol snapshots for every adjacent triple, z-scores the
gap series, and writes ``history.parquet`` + a reference-date monitor CSV.

Usage:
    conda run -n stir python notebooks/rv/run_fly_vs_vol_screener.py \
        --as-of 2026-07-27 --start 2025-06-02
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.FlyVsVol import (
    ContractMarginal,
    FlyVsVolConfig,
    adjacent_triples,
    historical_corr,
    history_zscores,
    run_fly_screener,
    screener_table,
)
from RVUtils.FlyVsVol.pairs import build_pair_history
from RVUtils.ImpliedDistribution import SFRImpliedDistribution, resolve_strip_symbols

ZSCORE_COLS = ["fly_bp", "tail_rent_bp", "skew_g_bp", "heuristic_gap", "phi_iqr_bp",
               "prob_delta"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--as-of", type=datetime.date.fromisoformat, required=True)
    p.add_argument("--start", type=datetime.date.fromisoformat, required=True)
    p.add_argument("--out-dir", type=Path, default=Path("notebooks/data/fly_vs_vol"))
    p.add_argument("--symbols", type=str, default=None,
                   help="comma-separated override; default resolve_strip_symbols('2y')")
    p.add_argument("--source", type=str, default="BARCHART_STIRFO-QL")
    return p.parse_args(argv)


def fetch_marginals(mdp, dist, symbols, dates):
    """{date: {symbol: ContractMarginal}} plus a forwards panel (date x symbol)."""
    by_date: dict = {}
    for sym in symbols:
        t0 = time.time()
        smiles = {}
        try:
            out = mdp.fetch_bulk_sabr_smile({
                "symbols": [sym],
                "timestamps": list(dates),
                "strike_offsets_bps": "listed",
            })
            smiles = out.get(sym, {}) or {}
        except Exception as exc:
            print(f"  {sym}: bulk failed ({type(exc).__name__}: {str(exc)[:100]}); "
                  f"per-date fallback", flush=True)
            for d in dates:
                try:
                    smiles[d] = mdp.fetch_sabr_smile({
                        "symbol": sym, "as_of": d, "strike_offsets_bps": "listed",
                    })
                except Exception:
                    continue
        n_ok = 0
        for d, smile in smiles.items():
            try:
                snap = dist.extract(smile)
            except Exception:
                continue
            if snap.bl_result is None:
                continue
            by_date.setdefault(d, {})[sym] = ContractMarginal.from_bl_result(
                sym, snap.bl_result, as_of=d
            )
            n_ok += 1
        print(f"  {sym}: {n_ok}/{len(dates)} dates extracted "
              f"({time.time() - t0:.0f}s)", flush=True)
    fwd = pd.DataFrame({
        d: {s: m.forward_rate for s, m in per.items()} for d, per in by_date.items()
    }).T.sort_index()
    return by_date, fwd


def main(argv=None):
    args = parse_args(argv)
    as_of, start = args.as_of, args.start
    symbols = (args.symbols.split(",") if args.symbols
               else resolve_strip_symbols("2y", as_of=as_of))
    dates = [d.date() for d in pd.bdate_range(start, as_of)]
    triples = adjacent_triples(symbols)
    print(f"strip: {symbols}", flush=True)
    print(f"triples: {[t.label for t in triples]}", flush=True)
    print(f"{len(dates)} business days {dates[0]} .. {dates[-1]}", flush=True)

    mdp = STIRFutureOptionMDP(source=args.source)
    dist = SFRImpliedDistribution(anchor_wings=True)
    config = FlyVsVolConfig()

    by_date, fwd_panel = fetch_marginals(mdp, dist, symbols, dates)
    if as_of not in by_date:
        print(f"FATAL: no marginals for reference date {as_of}", flush=True)
        return 1
    corr = historical_corr(fwd_panel)
    print("historical corr (daily diffs):", flush=True)
    print(corr.round(3).to_string(), flush=True)

    rows = []
    t0 = time.time()
    for d in sorted(by_date):
        snaps = run_fly_screener(
            by_date[d], triples, config=config,
            corr=corr if d == as_of else None, as_of=d,
        )
        for s in snaps:
            rows.append(s.to_row())
        if d == as_of:
            ref_snaps = snaps
    history = pd.DataFrame(rows)
    print(f"{len(history)} (date, triple) rows in {time.time() - t0:.0f}s", flush=True)

    history = history_zscores(
        history, ZSCORE_COLS,
        window=config.zscore_window, min_periods=config.zscore_min_periods,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    hist_path = args.out_dir / "history.parquet"
    history.to_parquet(hist_path, index=False)
    fwd_panel.rename_axis("as_of").to_parquet(args.out_dir / "forwards.parquet")

    # per-contract panel + curve-mode (pairs) screener
    contracts = pd.DataFrame([
        {
            "as_of": d, "symbol": sym,
            "forward_rate": m.forward_rate, "mean_rate": m.mean,
            "median_rate": m.median, "mm_bp": (m.mean - m.median) * 100,
            "fwd_resid_bp": m.forward_residual_bp,
            "pre_norm_mass": m.pre_normalization_mass,
            "ghost_frac": m.ghost_mass_fraction,
        }
        for d, per in by_date.items() for sym, m in per.items()
    ]).sort_values(["symbol", "as_of"])
    contracts.to_parquet(args.out_dir / "contracts.parquet", index=False)
    pair_hist = build_pair_history(contracts)
    pair_hist = history_zscores(
        pair_hist, ["pair_rent_bp", "pair_rent_skew_bp"],
        window=config.zscore_window, min_periods=config.zscore_min_periods,
    )
    pair_hist.to_parquet(args.out_dir / "pairs_history.parquet", index=False)

    monitor = screener_table(ref_snaps)
    zcols = [f"{c}_z" for c in ZSCORE_COLS] + [f"{c}_z_full" for c in ZSCORE_COLS]
    ref_hist = history[history["as_of"] == as_of].set_index("label")
    monitor = monitor.join(ref_hist[zcols])
    for snap in ref_snaps:
        if snap.copula is not None:
            monitor.loc[snap.fly.label, "copula_prob_delta"] = snap.copula.prob_delta
            monitor.loc[snap.fly.label, "copula_phi_iqr_bp"] = (
                snap.copula.phi_quantiles_bp[75] - snap.copula.phi_quantiles_bp[25]
            )
    csv_path = args.out_dir / f"screener_{as_of.isoformat()}.csv"
    monitor.to_csv(csv_path)

    with pd.option_context("display.width", 250, "display.max_columns", 60):
        core = ["fly_bp", "spread1_bp", "spread2_bp", "fly_median_path_bp",
                "tail_rent_bp", "skew_g_bp", "fit_residual_bp", "dominant_leg",
                "heuristic_prob", "prob_delta", "heuristic_gap",
                "p_dn_zero", "p_dn_pos", "phi_iqr_bp", "tail_slope_upper",
                "quality_ok"]
        print("\n=== fly-vs-vol monitor", as_of, "===", flush=True)
        print(monitor[core].round(3).to_string(), flush=True)
        zshow = [c for c in ("fly_bp_z", "tail_rent_bp_z", "skew_g_bp_z",
                             "heuristic_gap_z", "prob_delta_z", "phi_iqr_bp_z")
                 if c in monitor.columns]
        print("\n=== rolling z-scores (window "
              f"{config.zscore_window}) ===", flush=True)
        print(monitor[zshow + ["copula_prob_delta"]
                      if "copula_prob_delta" in monitor.columns else zshow]
              .round(2).to_string(), flush=True)
        flagged = [s for s in ref_snaps if not s.quality_ok]
        for s in flagged:
            print(f"\nquality flags {s.fly.label}:", flush=True)
            for f in s.quality_flags:
                print(f"  - {f}", flush=True)

    latest_pairs = pair_hist[pair_hist["as_of"] == as_of].set_index("label")
    if not latest_pairs.empty:
        with pd.option_context("display.width", 250):
            print(f"\n=== curve-mode (pairs) monitor {as_of} ===", flush=True)
            pcols = ["spread_bp", "median_spread_bp", "pair_rent_bp",
                     "pair_rent_skew_bp", "pair_fit_bp", "quality_ok",
                     "pair_rent_bp_z", "pair_rent_skew_bp_z"]
            print(latest_pairs[[c for c in pcols if c in latest_pairs.columns]]
                  .round(2).to_string(), flush=True)

    print(f"\nwrote {hist_path} and {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
