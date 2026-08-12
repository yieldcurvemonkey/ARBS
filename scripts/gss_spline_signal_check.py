"""Is a spline change moving the SIGNAL, or just cascading through the argmax?

**Run this before drawing any conclusion from a trade-set Jaccard across fits.** Measured on S0 vs
S3 (knots slid 1.25y): Jaccard **0.045** but corr(s2c) **0.983** and Spearman **0.944**. The signal
barely moved and the book was rewritten anyway, because selection is a hard top-N over ~173
near-tied candidates a day and 0.26bp of perturbation — a seventh of a standard deviation —
reorders the top of the list.

A trade-set Jaccard **cannot distinguish** "the signal changed" from "the ranking reshuffled". Both
produce a low number, and the difference between them is the difference between an unfixable
strategy and a fixable selection rule. This script measures the discriminating quantity: the s2c
values themselves.

    corr(s2c) high, Jaccard low  ->  the SELECTION is chaotic; the signal is fine (fixable:
                                     rank-average across fits, require a gap to the next-best
                                     candidate, or size by conviction instead of top-N)
    corr(s2c) low                ->  the residual genuinely depends on the fit; the signal is
                                     reading its own estimator

    conda run -n stir python scripts/gss_spline_signal_check.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly.conditioning import trade_set_jaccard  # noqa: E402
from BT.gss_fly.data import build_curve_panel, spline_config_id, ust_business_days  # noqa: E402
from gss_grid import spline_variants  # noqa: E402


def _compare(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    cols = a.columns.intersection(b.columns)
    idx = a.index.intersection(b.index)
    A, B = a.loc[idx, cols], b.loc[idx, cols]
    per_date, ranks = [], []
    for t in idx:
        x, y = A.loc[t], B.loc[t]
        m = x.notna() & y.notna()
        if m.sum() > 10 and x[m].std() > 0 and y[m].std() > 0:
            per_date.append(float(np.corrcoef(x[m], y[m])[0, 1]))
            ranks.append(float(x[m].rank().corr(y[m].rank(), method="spearman")))
    xf, yf = A.to_numpy(float).ravel(), B.to_numpy(float).ravel()
    m = np.isfinite(xf) & np.isfinite(yf)
    return {
        "corr_median": float(np.median(per_date)) if per_date else np.nan,
        "corr_p05": float(np.percentile(per_date, 5)) if per_date else np.nan,
        "spearman_median": float(np.median(ranks)) if ranks else np.nan,
        "mean_abs_diff_bp": float(np.mean(np.abs(xf[m] - yf[m]))) if m.any() else np.nan,
        "sd_base_bp": float(xf[m].std()) if m.any() else np.nan,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default="notebooks/data/gss_fly/panel_cached")
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--base", default="S0_jpm")
    args = ap.parse_args()

    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days(args.start, args.end)
    sv = spline_variants()
    logs = Path("notebooks/data/gss_fly/spline_logs")

    # Load ONLY what is already built. `build_curve_panel` will happily BUILD a missing panel,
    # which turns a "check" into a silent 21-minute refit — observed, on S4_with_otr. A diagnostic
    # that quietly does twenty minutes of work is one you stop trusting to run.
    panels = {}
    for name, cfg in sv.items():
        sub = Path(args.cache) if cfg is None else Path(args.cache) / f"spline_{spline_config_id(cfg)}"
        if not (sub / "s2c.parquet").exists() and not any((sub / "days").glob("*.spline.parquet")
                                                          if (sub / "days").exists() else []):
            print(f"SIG: {name} not built — skipping "
                  f"(scripts/gss_spline_panels.py --spline {name})", flush=True)
            continue
        try:
            panels[name] = build_curve_panel(days, mdp, cache_path=Path(args.cache),
                                             show_progress=False, spline_config=cfg)
        except Exception as exc:  # noqa: BLE001 — an unbuilt variant is absent, not fatal
            print(f"SIG: {name} unavailable ({type(exc).__name__})", flush=True)

    base = panels.get(args.base)
    if base is None:
        print(f"SIG: base panel {args.base} unavailable", flush=True)
        return 1

    base_log = pd.read_parquet(logs / f"{args.base}.parquet") if (logs / f"{args.base}.parquet").exists() else None

    rows = []
    for name, p in panels.items():
        r = {"spline": name, "n_dates": len(p.dates), "median_rmse_bp": float(p.rmse.median())}
        r.update(_compare(base.s2c, p.s2c))
        lp = logs / f"{name}.parquet"
        if base_log is not None and lp.exists():
            r["trade_jaccard"] = trade_set_jaccard(base_log, pd.read_parquet(lp))
        rows.append(r)

    t = pd.DataFrame(rows).sort_values("corr_median")
    print("\n=== SIGNAL vs SELECTION across spline fits ===", flush=True)
    print(t.to_string(index=False, float_format=lambda v: f"{v:.4f}"), flush=True)
    print("\n  corr high + Jaccard low => the SELECTION is chaotic, not the signal.", flush=True)
    print("  Only a LOW corr would mean the residual depends on the fit.", flush=True)
    out = Path("notebooks/data/gss_fly/spline_signal_check.csv")
    t.to_csv(out, index=False)
    print(f"\nSIG: -> {out}\nSIGDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
