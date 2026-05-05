"""Time-series backfill of SR3 vs ZQ distribution comparison signals.

Runs the prototype across 5 dates spanning known regime shifts:
    - 2023-02-21: pre-SVB calm
    - 2023-03-13: post-SVB stress (SVB closed Mar 10)
    - 2024-08-15: pre-Sep24 (50bp cut surprise)
    - 2024-09-19: post-Sep24 cut, pivot regime
    - 2026-05-04: current calm

Output: comparison table of all four signal residuals across regimes.
Tradeable signals should show meaningful regime sensitivity.
"""

from __future__ import annotations

import datetime
import logging
import sys
from typing import List

import pandas as pd

from scripts._sr3_zq_distribution_lib import (
    SignalRecord,
    compute_distribution_signals,
)


# (as_of, sr3_contract, ref_start, ref_end, zq_months_range, regime_label)
BACKFILL_DATES = [
    (
        datetime.date(2023, 2, 21),
        "SFRM23",
        datetime.date(2023, 6, 21),  # IMM Jun 2023
        datetime.date(2023, 9, 20),  # IMM Sep 2023
        ((2023, 1), (2023, 10)),
        "pre-SVB calm",
    ),
    (
        datetime.date(2023, 3, 13),
        "SFRM23",
        datetime.date(2023, 6, 21),
        datetime.date(2023, 9, 20),
        ((2023, 1), (2023, 10)),
        "post-SVB stress",
    ),
    (
        datetime.date(2024, 8, 15),
        "SFRZ24",
        datetime.date(2024, 12, 18),  # IMM Dec 2024
        datetime.date(2025, 3, 19),   # IMM Mar 2025
        ((2024, 6), (2025, 4)),
        "pre-Sep24 cut",
    ),
    (
        datetime.date(2024, 9, 19),
        "SFRZ24",
        datetime.date(2024, 12, 18),
        datetime.date(2025, 3, 19),
        ((2024, 6), (2025, 4)),
        "post-Sep24 50bp cut",
    ),
    (
        datetime.date(2026, 5, 4),
        "SFRU26",
        datetime.date(2026, 9, 16),
        datetime.date(2026, 12, 16),
        ((2026, 5), (2026, 12)),
        "current calm",
    ),
]


def main():
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.WARNING)

    records: List[tuple] = []  # (regime, SignalRecord)
    for as_of, contract, ref_start, ref_end, zq_range, regime in BACKFILL_DATES:
        print(f"\n[{regime}] {as_of} on {contract}", flush=True)
        try:
            rec = compute_distribution_signals(
                as_of=as_of,
                sr3_contract=contract,
                ref_start=ref_start,
                ref_end=ref_end,
                zq_months_range=zq_range,
            )
            records.append((regime, rec))
            print(
                f"  fwd_rate={rec.forward_rate:.4f}%  dte={rec.sr3_dte}  "
                f"meetings_in_period={rec.n_meetings_in_period}  "
                f"sr3_var={rec.sr3_total_var_bp2:.0f}bp²  "
                f"zq_var={rec.zq_day_weighted_var_bp2:.0f}bp²  "
                f"residual={rec.residual_var_bp2:.0f}bp² "
                f"({rec.residual_to_explained_ratio:.1f}× explained)",
                flush=True,
            )
            print(
                f"  skew={rec.sr3_skew:+.3f}  kurt={rec.sr3_kurt:.2f}  "
                f"stability={rec.sr3_stability_flag}",
                flush=True,
            )
            print(
                f"  tail ≤fwd-50bp: {rec.tail_lower_50:.3f}  "
                f"tail ≥fwd+50bp: {rec.tail_upper_50:.3f}",
                flush=True,
            )
        except Exception as exc:
            print(f"  FAILED: {exc}", flush=True)
            continue

    # Summary table
    if not records:
        print("\nNo records collected", flush=True)
        return

    rows = []
    for regime, r in records:
        rows.append(
            {
                "regime": regime,
                "as_of": r.as_of,
                "contract": r.sr3_contract,
                "dte": r.sr3_dte,
                "fwd_rate_%": round(r.forward_rate, 3),
                "sr3_var_bp2": round(r.sr3_total_var_bp2, 0),
                "zq_var_bp2": round(r.zq_day_weighted_var_bp2, 1),
                "drift_var_bp2": round(r.intermeeting_drift_var_bp2, 1),
                "explained_bp2": round(r.explained_var_bp2, 1),
                "residual_bp2": round(r.residual_var_bp2, 0),
                "ratio_×": round(r.residual_to_explained_ratio, 1),
                "skew": round(r.sr3_skew, 3),
                "kurt": round(r.sr3_kurt, 2),
                "tail_-50bp": round(r.tail_lower_50, 4),
                "tail_+50bp": round(r.tail_upper_50, 4),
                "tail_-100bp": round(r.tail_lower_100, 4),
                "tail_+100bp": round(r.tail_upper_100, 4),
                "stability": r.sr3_stability_flag,
                "smooth_pp": round(r.smoothing_sensitivity_pp, 2),
                "order_pp": round(r.order_sensitivity_pp, 2),
                "neg_pct": round(r.negative_density_pct, 2),
                "n_strikes": r.n_strikes_used,
                "source": r.prices_source,
            }
        )
    df = pd.DataFrame(rows)
    pd.set_option("display.max_colwidth", 200)
    pd.set_option("display.width", 250)

    print("\n" + "=" * 160, flush=True)
    print("SIGNAL COMPARISON ACROSS REGIMES", flush=True)
    print("=" * 160, flush=True)
    print(df.to_string(index=False), flush=True)

    # Save CSV
    out = "data/screener_results/sr3_zq_distribution_backfill.csv"
    import pathlib
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nWrote: {out}", flush=True)

    # Quick interpretation
    print("\n" + "=" * 80, flush=True)
    print("REGIME-SENSITIVITY INTERPRETATION", flush=True)
    print("=" * 80, flush=True)

    # Variance residual: how much does it move across regimes?
    res = df["residual_bp2"]
    print(f"\nVariance residual range: {res.min():.0f} → {res.max():.0f} bp² "
          f"(spread {res.max() - res.min():.0f}bp²)", flush=True)
    print(f"  Calm (pre-SVB, current):  {df.loc[df['regime'].str.contains('calm'), 'residual_bp2'].tolist()}", flush=True)
    print(f"  Stress (post-SVB):        {df.loc[df['regime'].str.contains('stress'), 'residual_bp2'].tolist()}", flush=True)
    print(f"  Pivot (post-Sep24):       {df.loc[df['regime'].str.contains('pivot|cut'), 'residual_bp2'].tolist()}", flush=True)

    # Skew sensitivity
    skew = df["skew"]
    print(f"\nSkew range: {skew.min():+.3f} → {skew.max():+.3f}", flush=True)

    # Tail sensitivity
    print(f"\nTail at -50bp range: {df['tail_-50bp'].min():.3f} → {df['tail_-50bp'].max():.3f}", flush=True)
    print(f"Tail at +50bp range: {df['tail_+50bp'].min():.3f} → {df['tail_+50bp'].max():.3f}", flush=True)


if __name__ == "__main__":
    main()
