"""Extended SR3 vs ZQ backfill across 30+ regime points + λ-grid optimization.

Path 2 (regime-conditional historical percentiles): runs the pipeline
across the curated regime calendar (35 dates) and emits a long DataFrame
with a regime tag per row. Then computes per-regime quantiles for each
signal — the "is this residual unusual within regime?" question.

Path 3 (λ optimization): each date is fit twice — once at JPM's fixed
λ=1e-4 and once with λ-grid optimization over {1e-5, 5e-5, 1e-4, 5e-4,
1e-3}. Compares stability metrics across the two strategies.
"""

from __future__ import annotations

import datetime
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from scripts._sr3_zq_date_sampler import build_samples
from scripts._sr3_zq_distribution_lib import (
    SignalRecord,
    compute_distribution_signals,
)


# Coarse regime classifier — maps the curated label to one of {calm, stress, pivot, hike}.
_REGIME_BUCKET = {
    "2022 75bp era": "hike",
    "post-Sep22 75bp hike": "hike",
    "post-Nov22 75bp": "hike",
    "Dec22 cycle peak": "hike",
    "early-2023 calm": "calm",
    "pre-SVB calm": "calm",
    "SVB-day-before": "stress",
    "post-SVB stress peak": "stress",
    "SVB+1w recovering": "stress",
    "post-stress normalize": "calm",
    "post-May FOMC": "calm",
    "debt-ceiling stress": "stress",
    "summer calm": "calm",
    "pre-Jackson Hole": "calm",
    "Sep23 SEP shock": "pivot",
    "Nov23 hold": "calm",
    "early-2024 calm": "calm",
    "post-CPI hot": "pivot",
    "April hawkish reset": "pivot",
    "summer 2024": "calm",
    "yen carry unwind": "stress",
    "pre-Sep24 cut": "pivot",
    "pre-50bp cut": "pivot",
    "post-50bp cut": "pivot",
    "post-Nov24 cut": "calm",
    "Dec24 hawkish SEP": "pivot",
    "early-2025": "calm",
    "post-tariff shock": "stress",
    "summer 2025": "calm",
    "Sep25 cut restart": "pivot",
    "post-cut reset": "calm",
    "year-end 2025": "calm",
    "early-2026 calm": "calm",
    "April 2026 calm": "calm",
    "current": "calm",
}


def _record_to_row(rec: SignalRecord, regime_label: str, mode: str) -> Dict:
    return {
        "as_of": rec.as_of,
        "regime_label": regime_label,
        "regime_bucket": _REGIME_BUCKET.get(regime_label, "calm"),
        "mode": mode,
        "contract": rec.sr3_contract,
        "dte": rec.sr3_dte,
        "fwd_rate": round(rec.forward_rate, 4),
        "n_meetings": rec.n_meetings_in_period,
        "sr3_var_bp2": round(rec.sr3_total_var_bp2, 1),
        "zq_var_bp2": round(rec.zq_day_weighted_var_bp2, 2),
        "explained_bp2": round(rec.explained_var_bp2, 2),
        "residual_bp2": round(rec.residual_var_bp2, 1),
        "residual_ratio": round(rec.residual_to_explained_ratio, 2),
        "skew": round(rec.sr3_skew, 4),
        "kurt": round(rec.sr3_kurt, 2),
        "stability": rec.sr3_stability_flag,
        "smooth_pp": round(rec.smoothing_sensitivity_pp, 2),
        "order_pp": round(rec.order_sensitivity_pp, 2),
        "neg_pct": round(rec.negative_density_pct, 3),
        "n_strikes": rec.n_strikes_used,
        "source": rec.prices_source,
        "tail_-100bp": round(rec.tail_lower_100, 4),
        "tail_-75bp": round(rec.tail_lower_75, 4),
        "tail_-50bp": round(rec.tail_lower_50, 4),
        "tail_+50bp": round(rec.tail_upper_50, 4),
        "tail_+75bp": round(rec.tail_upper_75, 4),
        "tail_+100bp": round(rec.tail_upper_100, 4),
        "chosen_lambda": rec.chosen_lambda,
        "lambda_scores_json": json.dumps(
            {f"{k:.0e}": round(v, 3) for k, v in rec.lambda_scores.items()}
        ) if rec.lambda_scores else "",
    }


def main():
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.WARNING)

    samples = build_samples()
    print(f"=== Extended backfill across {len(samples)} dates ===\n", flush=True)

    rows: List[Dict] = []
    for i, s in enumerate(samples, 1):
        regime_bucket = _REGIME_BUCKET.get(s.regime_label, "calm")
        print(
            f"[{i:>2}/{len(samples)}] {s.as_of} ({regime_bucket:<7}) "
            f"{s.regime_label:<28}  {s.sr3_contract}",
            flush=True,
        )

        # Mode A: fixed λ (JPM default 1e-4)
        try:
            t0 = time.time()
            rec_fixed = compute_distribution_signals(
                as_of=s.as_of,
                sr3_contract=s.sr3_contract,
                ref_start=s.ref_start,
                ref_end=s.ref_end,
                zq_months_range=s.zq_months_range,
                optimize_lambda=False,
            )
            rows.append(_record_to_row(rec_fixed, s.regime_label, "fixed"))
            dt_fixed = time.time() - t0
            print(
                f"     fixed     skew={rec_fixed.sr3_skew:+.3f}  "
                f"resid={rec_fixed.residual_var_bp2:.0f}bp²  "
                f"tail-50={rec_fixed.tail_lower_50:.3f}/+50={rec_fixed.tail_upper_50:.3f}  "
                f"stable={rec_fixed.sr3_stability_flag}  ({dt_fixed:.1f}s)",
                flush=True,
            )
        except Exception as exc:
            print(f"     fixed FAILED: {exc}", flush=True)

        # Mode B: optimized λ
        try:
            t0 = time.time()
            rec_opt = compute_distribution_signals(
                as_of=s.as_of,
                sr3_contract=s.sr3_contract,
                ref_start=s.ref_start,
                ref_end=s.ref_end,
                zq_months_range=s.zq_months_range,
                optimize_lambda=True,
            )
            rows.append(_record_to_row(rec_opt, s.regime_label, "optimized"))
            dt_opt = time.time() - t0
            print(
                f"     optimized λ={rec_opt.chosen_lambda:.0e}  "
                f"skew={rec_opt.sr3_skew:+.3f}  "
                f"resid={rec_opt.residual_var_bp2:.0f}bp²  "
                f"tail-50={rec_opt.tail_lower_50:.3f}/+50={rec_opt.tail_upper_50:.3f}  "
                f"stable={rec_opt.sr3_stability_flag}  ({dt_opt:.1f}s)",
                flush=True,
            )
        except Exception as exc:
            print(f"     optimized FAILED: {exc}", flush=True)

    if not rows:
        print("\nNo rows collected", flush=True)
        return

    df = pd.DataFrame(rows)
    out_dir = Path("data/screener_results/sr3_zq_extended_backfill")
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "all.csv", index=False)
    print(f"\nWrote {len(df)} rows to {out_dir / 'all.csv'}", flush=True)

    # =================================================================
    # PATH 2: regime-conditional percentiles (fixed-λ subset)
    # =================================================================
    print("\n" + "=" * 90, flush=True)
    print("PATH 2: REGIME-CONDITIONAL PERCENTILES (fixed-λ)", flush=True)
    print("=" * 90, flush=True)

    df_fixed = df[df["mode"] == "fixed"].copy()
    pd.set_option("display.max_colwidth", 50)
    pd.set_option("display.width", 250)

    metrics = ["residual_bp2", "residual_ratio", "skew", "tail_-50bp", "tail_+50bp", "tail_-100bp", "tail_+100bp"]

    summary_rows = []
    for bucket in ["calm", "stress", "pivot", "hike"]:
        sub = df_fixed[df_fixed["regime_bucket"] == bucket]
        if sub.empty:
            continue
        row = {"regime": bucket, "n": len(sub)}
        for m in metrics:
            row[f"{m}_p25"] = round(sub[m].quantile(0.25), 4)
            row[f"{m}_p50"] = round(sub[m].quantile(0.50), 4)
            row[f"{m}_p75"] = round(sub[m].quantile(0.75), 4)
            row[f"{m}_max"] = round(sub[m].max(), 4)
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    print("\nRegime quantiles (p25 / p50 / p75 / max):", flush=True)
    for m in metrics:
        cols = ["regime", "n", f"{m}_p25", f"{m}_p50", f"{m}_p75", f"{m}_max"]
        print(f"\n  {m}:", flush=True)
        print(summary[cols].to_string(index=False), flush=True)

    # =================================================================
    # PATH 3: λ-strategy comparison
    # =================================================================
    print("\n" + "=" * 90, flush=True)
    print("PATH 3: λ-STRATEGY COMPARISON (fixed vs optimized)", flush=True)
    print("=" * 90, flush=True)

    df_opt = df[df["mode"] == "optimized"]
    if not df_opt.empty:
        # λ usage histogram
        print("\nλ chosen by optimizer (frequency):", flush=True)
        lambda_counts = df_opt["chosen_lambda"].value_counts().sort_index()
        for lam, count in lambda_counts.items():
            pct = 100.0 * count / len(df_opt)
            print(f"    λ={lam:.0e}:  {count:>3} dates  ({pct:>5.1f}%)", flush=True)

        # Stability flag improvement
        n_stable_fixed = (df_fixed["stability"] == "stable").sum()
        n_stable_opt = (df_opt["stability"] == "stable").sum()
        print(f"\nStability flag = 'stable':  fixed {n_stable_fixed}/{len(df_fixed)}  → opt {n_stable_opt}/{len(df_opt)}", flush=True)

        # Average smoothing-sensitivity
        print(
            f"Mean smoothing sensitivity (Δp pp):  "
            f"fixed {df_fixed['smooth_pp'].mean():.2f}  → opt {df_opt['smooth_pp'].mean():.2f}",
            flush=True,
        )
        print(
            f"Mean negative-density (%):  "
            f"fixed {df_fixed['neg_pct'].mean():.3f}  → opt {df_opt['neg_pct'].mean():.3f}",
            flush=True,
        )

        # Per-bucket optimal λ
        print("\nMost-frequent λ by regime:", flush=True)
        for bucket in ["calm", "stress", "pivot", "hike"]:
            sub = df_opt[df_opt["regime_bucket"] == bucket]
            if sub.empty:
                continue
            top = sub["chosen_lambda"].value_counts().head(3)
            print(f"  {bucket:<7}: {dict(top)}", flush=True)


if __name__ == "__main__":
    main()
