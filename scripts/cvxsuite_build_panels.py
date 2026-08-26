r"""Build the historical CvxSuite signal panels for the two W3 QDB strategies.

    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/cvxsuite_build_panels.py \
        --start 2021-01-04 --end 2026-08-22

Writes, under docs/cvxsuite/:
    leg_panel.parquet          (date, leg)  rate_bp/dv01/gamma/roll_1y/roll_1d
                               — strat3-form leg labels ("10Yx10Y"), one
                               ``leg_metrics`` reprice per leg per served day
    harvest_panel.parquet      (date, pair) — the cvx_kink_harvest contract
                               (be_over_rv, zs, rac_net + components)
    dislocation_panel.parquet  (date, point) — the cvx_fly_dislocation
                               contract (zs, sign_agree, tag, edge_bp, legs,
                               weights + components)

The leg panel is the only expensive piece (one offline store-backed curve
per business day through ``BT.signals.cvx_strikeless.build_curve_map`` —
refuse-today + reference-date + ``from_curve_store`` guards — then four
``leg_metrics`` repricing passes).  The script MEASURES the rate on
``--estimate-days`` first and, if the projected full build exceeds
``--max-minutes`` (default 45), FALLS BACK to ``--fallback-start``
(2023-01-03) AND SAYS SO — the task's pre-authorised alternative.

The harvest/dislocation statistics run over the FULL leg-history span
(2019-01-02..) so the 756-day windows are warm before the leg-panel window
starts; carry/be_over_rv columns are NaN off the leg-panel window (including
the ~120-business-day realized-vol warmup at its start) — refusals, never
zeros.  Offline discipline: ARBS_SUPABASE_ENABLED=0 before any repo import;
every curve request carries ``"offline": True``; ARBS_CACHE_DIR is never set
here.  Exit 2 when nothing was built.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import argparse
import datetime as dt
import time

import numpy as np
import pandas as pd

OUT_DIR = REPO / "docs" / "cvxsuite"
LEG_HISTORY = OUT_DIR / "leg_history.parquet"
LEG_PANEL = OUT_DIR / "leg_panel.parquet"
HARVEST = OUT_DIR / "harvest_panel.parquet"
DISLOCATION = OUT_DIR / "dislocation_panel.parquet"


def _bdays(start: dt.date, end: dt.date) -> list[dt.date]:
    return [d.date() for d in pd.bdate_range(start, end)]


def _nan_share(df: pd.DataFrame) -> pd.Series:
    return df.isna().mean().round(4)


def _sample(df: pd.DataFrame, n: int = 3) -> str:
    """n spread-out sample rows, all columns, fixed-point."""
    if len(df) == 0:
        return "(empty)"
    pos = [len(df) // 4, len(df) // 2, len(df) - 1][:n]
    with pd.option_context("display.width", 300, "display.max_columns", 99,
                           "display.float_format", lambda v: f"{v:,.4f}"):
        return df.iloc[sorted(set(pos))].to_string()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", type=dt.date.fromisoformat,
                    default=dt.date(2021, 1, 4))
    ap.add_argument("--end", type=dt.date.fromisoformat,
                    default=dt.date(2026, 8, 22))
    ap.add_argument("--fallback-start", type=dt.date.fromisoformat,
                    default=dt.date(2023, 1, 3),
                    help="leg-panel start if the measured estimate exceeds --max-minutes")
    ap.add_argument("--estimate-days", type=int, default=10)
    ap.add_argument("--max-minutes", type=float, default=45.0)
    ap.add_argument("--n-jobs", type=int, default=1,
                    help="bulk_get_data n_jobs (estimate runs at the same value)")
    ap.add_argument("--chunk-days", type=int, default=60)
    a = ap.parse_args(argv)

    from RVUtils.CvxSuite import panels as P

    if not LEG_HISTORY.exists():
        print(f"FATAL: {LEG_HISTORY} absent — warm the leg history first "
              "(scripts/cvxsuite_warm_legs.py)")
        return 2
    hist = pd.read_parquet(LEG_HISTORY)
    print(f"leg history: {hist.shape[0]} dates x {hist.shape[1]} legs, "
          f"{hist.index[0].date()} .. {hist.index[-1].date()}")

    # ---- 1. measured cost estimate on the window's last N business days ----
    days_full = _bdays(a.start, a.end)
    est_days = days_full[-int(a.estimate_days):]
    print(f"\n=== ESTIMATE: {len(est_days)} days "
          f"({est_days[0]}..{est_days[-1]}) at n_jobs={a.n_jobs} ===", flush=True)
    t0 = time.time()
    est_panel = P.build_leg_panel(est_days, P.HARVEST_LEGS, n_jobs=a.n_jobs,
                                  chunk_days=a.chunk_days, progress=False)
    est_elapsed = time.time() - t0
    est_served = est_panel.index.get_level_values("date").nunique()
    rate = est_elapsed / max(1, est_served)
    projected_min = rate * len(days_full) / 60.0
    print(f"estimate: {est_served}/{len(est_days)} days served in "
          f"{est_elapsed:.1f}s -> {rate:.2f}s/day; projected full build "
          f"({len(days_full)} bdays {a.start}..{a.end}) = {projected_min:.1f} min")

    start_used = a.start
    if projected_min > a.max_minutes:
        start_used = a.fallback_start
        days_full = _bdays(start_used, a.end)
        print(f"*** PROJECTED {projected_min:.1f} min EXCEEDS the "
              f"{a.max_minutes:.0f}-minute budget: building the pre-authorised "
              f"FALLBACK WINDOW {start_used}..{a.end} "
              f"({len(days_full)} bdays, ~{rate * len(days_full) / 60.0:.1f} min) "
              "instead — SAYING SO, per the task. ***")
    else:
        print(f"window kept: {start_used}..{a.end}")

    # ---- 2. leg panel (the expensive, repriced block) ----------------------
    print(f"\n=== LEG PANEL: {len(days_full)} bdays, legs {list(P.HARVEST_LEGS)} ===",
          flush=True)
    t0 = time.time()
    leg_panel = P.build_leg_panel(days_full, P.HARVEST_LEGS, n_jobs=a.n_jobs,
                                  chunk_days=a.chunk_days, progress=True)
    t_leg = time.time() - t0
    n_days_served = leg_panel.index.get_level_values("date").nunique()
    n_legs = leg_panel.index.get_level_values("leg").nunique()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    leg_panel.to_parquet(LEG_PANEL)
    print(f"leg panel: {len(leg_panel):,} rows = {n_days_served} days x "
          f"{n_legs} legs in {t_leg / 60.0:.1f} min "
          f"({t_leg / max(1, n_days_served):.2f}s/day) -> {LEG_PANEL}")
    cov = n_days_served / max(1, len(days_full))
    print(f"=== GATE leg-panel coverage === {n_days_served}/{len(days_full)} "
          f"requested bdays served ({cov:.1%}; misses are holidays/unwarmed "
          f"store days, dropped never zero-filled) "
          f"{'PASS' if cov >= 0.90 else 'WARN'}")
    if len(leg_panel) == 0:
        print("FATAL: empty leg panel")
        return 2

    # ---- 3. harvest panel --------------------------------------------------
    print(f"\n=== HARVEST PANEL: pairs {list(P.HARVEST_PAIRS)} ===", flush=True)
    harvest = P.build_harvest_panel(hist, pairs=P.HARVEST_PAIRS,
                                    leg_panel=leg_panel)
    harvest.to_parquet(HARVEST)
    hd = harvest.index.get_level_values("date")
    print(f"harvest panel: {harvest.shape[0]:,} rows x {harvest.shape[1]} cols, "
          f"{hd.min().date()} .. {hd.max().date()} -> {HARVEST}")
    print("=== GATE harvest screen pairs === PASS (all pairs served — the "
          "silent-skip assert in panels._screen_block enforces this)")
    print(f"=== GATE harvest index names === {list(harvest.index.names)} "
          f"{'PASS' if list(harvest.index.names) == ['date', 'pair'] else 'FAIL'}")
    print("\nharvest NaN shares:")
    print(_nan_share(harvest).to_string())
    gated = harvest.dropna(subset=["be_over_rv", "zs", "rac_net"])
    print(f"rows with all three gate inputs finite: {len(gated):,} / {len(harvest):,}")
    print("\nharvest sample rows:")
    print(_sample(harvest))

    # ---- 4. dislocation panel ----------------------------------------------
    print("\n=== DISLOCATION PANEL: KINK_GRID interior (15 points) ===", flush=True)
    t0 = time.time()
    disl = P.build_dislocation_panel(hist)
    disl.to_parquet(DISLOCATION)
    dd = disl.index.get_level_values("date")
    print(f"dislocation panel: {disl.shape[0]:,} rows x {disl.shape[1]} cols, "
          f"{dd.min().date()} .. {dd.max().date()} in {time.time() - t0:.1f}s "
          f"-> {DISLOCATION}")
    print(f"=== GATE dislocation index names === {list(disl.index.names)} "
          f"{'PASS' if list(disl.index.names) == ['date', 'point'] else 'FAIL'}")
    carry_1y1y_nan = disl.xs("1y1y", level="point")["carry_bp_day"].isna().all()
    print(f"=== GATE strip carry === 1y1y NaN (spot wing, by design): "
          f"{'PASS' if carry_1y1y_nan else 'FAIL'}")
    last_day = dd.max()
    tags = disl.xs(last_day, level="date")["tag"].value_counts().to_dict()
    print(f"=== GATE zone tags === {tags} "
          f"{'PASS' if tags == {'clean': 11, 'convexity': 3, 'meeting': 1} else 'FAIL'}")
    print("=== POLARITY (binding) === zs>0 = fly level high = belly CHEAP; the "
          "fade of zs>0 is the RECEIVE-belly side — consistent with "
          "cvx_fly_dislocation's direction = -1 if zs>0 (verified; see the "
          "panels.py seam note)")
    print("\ndislocation NaN shares:")
    print(_nan_share(disl).to_string())
    dg = disl.dropna(subset=["zs", "sign_agree", "edge_bp"])
    print(f"rows with zs+sign_agree+edge finite: {len(dg):,} / {len(disl):,}")
    n_cand = int(((dg['zs'].abs() >= 2.0) & (dg['sign_agree'] != 0)
                  & (dg['tag'] == 'clean') & (dg['edge_bp'] > 1.0)).sum())
    print(f"rows passing the frozen dislocation gates (|z|>=2, agree, clean, "
          f"edge>1): {n_cand:,}")
    print("\ndislocation sample rows:")
    print(_sample(disl))

    print("\nDONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
