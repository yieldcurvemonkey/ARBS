"""Kink-ledger screen: one row per KINK_GRID point, sorted by |edge|.

Builds the CvxSuite C2 kink screen (RVUtils/CvxSuite/kink_screen.py — the
kink_ledger.md section-6 row: convexity-adjusted residuals x OU/FPT x
repriced rent x cube vol x frontiers x two-book split) for one date, against
the offline curve store and the local swaption cube. Prints the ledger table
with the ``=== GATE ... ===`` lines and a two-book summary.

    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/kink_ledger_screen.py --date 2026-08-21
    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/kink_ledger_screen.py --date live
    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/kink_ledger_screen.py --date live --json

Offline discipline: ARBS_SUPABASE_ENABLED=0 before any repo import; the
curve request carries ``"offline": True`` and the pricer must be
store-backed (``meta()["from_curve_store"]``); ARBS_CACHE_DIR is never set
here (unset resolves to the platformdirs cache where the cube lives).
``--date live`` walks back from the newest leg-history date (up to 5
sessions) to the newest date the curve store can serve. Exit code 2 when
nothing priced — a screen that priced nothing is a failure, not a flat
answer. A book label here is a screen classification, never an aliveness
claim (L-0088 stands).
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
import json
import time

import numpy as np
import pandas as pd

PARQUET = REPO / "docs" / "cvxsuite" / "leg_history.parquet"
LIVE_WALKBACK = 5


def _pricer_for(date: dt.date):
    """Offline store-backed CITIVELO_EXCEL pricer, or (None, reason)."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    try:
        p = IRSwapsMDP(source="CITIVELO_EXCEL").get_data(
            {"curve_name": "USD-SOFR-1D", "timestamp": date, "offline": True})
    except Exception as exc:  # noqa: BLE001 — a cold store is a report, not a crash
        return None, f"curve store error for {date}: {exc!r}"
    if p is None:
        return None, f"curve store miss for {date} (get_data returned None)"
    if p.meta().get("from_curve_store") is not True:
        return None, f"pricer for {date} is not store-backed; refusing"
    return p, ""


def _resolve_date(arg: str, hist_index: pd.DatetimeIndex):
    """(asof Timestamp, pricer) or (None, reasons). live = newest servable."""
    if arg.strip().lower() == "live":
        reasons = []
        for ts in hist_index[::-1][:LIVE_WALKBACK]:
            p, why = _pricer_for(ts.date())
            if p is not None:
                return ts, p, reasons
            reasons.append(why)
        return None, None, reasons
    ts = pd.Timestamp(arg).normalize()
    if ts not in hist_index:
        return None, None, [
            f"{ts.date()} is not a leg-history date (last: {hist_index[-1].date()})"]
    p, why = _pricer_for(ts.date())
    return (ts, p, []) if p is not None else (None, None, [why])


def _fmt(df: pd.DataFrame) -> str:
    """The ledger table, sorted by |edge_bp| descending, NaN last."""
    cols = ["tag", "adj_bp", "residual_xsec", "residual_pca", "sign_agree",
            "zs", "pctl_3y", "carry_bp_day", "e_fpt_d", "p_hit", "e_rev_bp",
            "rac_net",
            "gamma_usd_per_bp2", "sigma_be_bp_day", "be_status",
            "sigma_impl_bp_day", "sigma_rlzd_bp_day", "be_over_rv",
            "off_value_carry", "off_carry_vol", "edge_bp", "book"]
    out = df[cols].copy()
    order = out["edge_bp"].abs().sort_values(ascending=False, na_position="last")
    out = out.loc[order.index]
    ren = {"residual_xsec": "res_x", "residual_pca": "res_pca",
           "sign_agree": "agree", "carry_bp_day": "carry/d",
           "e_fpt_d": "e_fpt", "e_rev_bp": "e_rev",
           "gamma_usd_per_bp2": "gamma",
           "sigma_be_bp_day": "sig_be", "be_status": "be_st",
           "sigma_impl_bp_day": "sig_impl", "sigma_rlzd_bp_day": "sig_rlzd",
           "off_value_carry": "off_vc", "off_carry_vol": "off_cv"}
    out = out.rename(columns=ren)
    with pd.option_context("display.width", 260, "display.max_columns", 99,
                           "display.float_format", lambda v: f"{v:,.2f}"):
        return out.to_string()


def _gates(df: pd.DataFrame) -> bool:
    """Print the === GATE === lines; returns False only on a units breach."""
    from RVUtils.CvxSuite import gates as g
    from RVUtils.CvxSuite.vols import units_median_guard

    ok = True
    rlzd = df["sigma_rlzd_bp_day"]
    try:
        units_median_guard(rlzd)
        print(f"=== GATE units_median_guard(sigma_rlzd) === PASS  "
              f"median={np.nanmedian(rlzd):.2f} bp/day in [0.5, 40]")
    except ValueError as exc:
        print(f"=== GATE units_median_guard(sigma_rlzd) === FAIL  {exc}")
        ok = False

    dg = g.degeneracy_gate(rlzd)
    n_fail = int((~dg).sum())
    fails = list(df.index[~dg])
    print(f"=== GATE degeneracy (sigma_rlzd >= 0.25 bp/day) === "
          f"{int(dg.sum())}/{len(df)} pass"
          + (f"  FAILING: {fails}" if n_fail else ""))

    nan_impl = list(df.index[df["sigma_impl_bp_day"].isna()])
    expected = {"1y", "40y10y"}
    note = ("as designed (1y: expiry 0 < 1M axis; 40y10y: expiry 40 > 30Y axis)"
            if set(nan_impl) == expected else
            f"UNEXPECTED (design expects exactly {sorted(expected)})")
    print(f"=== GATE cube support === {len(nan_impl)} NaN sigma_impl of "
          f"{len(df)}: {nan_impl} — {note}")

    lev = df.attrs.get("fit_diag", {}).get("leverage", {})
    hi = {k: v for k, v in lev.items() if k >= 27.0}
    lev_s = ", ".join(f"k={k:g}: h={v:.3f}" for k, v in sorted(hi.items()))
    print(f"=== GATE spline leverage (k >= 27, cubic extension) === {lev_s}")

    print(f"=== CA === mode={df.attrs.get('ca_mode')}  "
          f"sigma cells ffilled={df.attrs.get('ca_cells_ffilled')} "
          f"(sigma-space, per-column limit)  "
          f"pca refits={df.attrs.get('pca_info', {}).get('n_refits')}  "
          f"cos_prev={ {k: (round(v, 4) if np.isfinite(v) else v) for k, v in df.attrs.get('pca_info', {}).get('cos_prev', {}).items()} }")
    errs = df.attrs.get("leg_roll_errors", {})
    if errs:
        print(f"=== WARN leg_roll errors === {errs}")
    return ok


def _summary(df: pd.DataFrame) -> str:
    lines = ["", "--- two-book summary " + "-" * 47]
    for book in ("harvest", "dislocation"):
        rows = df[df["book"] == book]
        if len(rows) == 0:
            lines.append(f"{book:12s}: none")
            continue
        for lab, r in rows.iterrows():
            lines.append(
                f"{book:12s}: {lab:8s} tag={r['tag']:9s} z={r['zs']:+.2f} "
                f"be/rv={r['be_over_rv']:.2f} rac_net={r['rac_net']:+.2f}bp "
                f"edge={r['edge_bp']:+.2f}bp")
    lines.append(f"{'none':12s}: {int((df['book'] == 'none').sum())} rows")
    return "\n".join(lines)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", default="live",
                   help="YYYY-MM-DD, or 'live' for the newest servable session")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable records instead of the report")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    if not PARQUET.exists():
        print(f"NOTHING PRICED: leg history parquet missing at {PARQUET}")
        return 2
    leg_hist = pd.read_parquet(PARQUET)

    asof, pricer, reasons = _resolve_date(a.date, leg_hist.index)
    if pricer is None:
        print("NOTHING PRICED: no servable date")
        for r in reasons:
            print(f"  - {r}")
        return 2

    from Caching.swaption_cube_store import SwaptionCubeStore
    from RVUtils.CvxSuite.kink_screen import KinkScreenCfg, build_kink_screen

    store = SwaptionCubeStore.default()
    cfg = KinkScreenCfg()
    t0 = time.perf_counter()
    df = build_kink_screen(asof, leg_hist_bp=leg_hist, pricer=pricer,
                           cube_store=store, cfg=cfg)
    elapsed = time.perf_counter() - t0

    n_priced = int(df["theta_usd_day"].notna().sum())
    if a.json:
        payload = {
            "asof": asof.date().isoformat(),
            "elapsed_s": round(elapsed, 1),
            "cost_bp": df.attrs.get("cost_bp"),
            "ca_mode": df.attrs.get("ca_mode"),
            "ca_cells_ffilled": df.attrs.get("ca_cells_ffilled"),
            "frontier_value_carry": df.attrs.get("frontier_value_carry"),
            "frontier_carry_vol": df.attrs.get("frontier_carry_vol"),
            "rows": json.loads(df.reset_index().to_json(orient="records")),
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0 if n_priced else 2

    print(f"KINK LEDGER SCREEN — {asof.date()}  "
          f"(build {elapsed:.1f}s, history {leg_hist.index[0].date()}..{asof.date()}, "
          f"cost 1x = {df.attrs.get('cost_bp')}bp RT)")
    print(f"sorted by |edge_bp| = |E[rev]*p_hit - |carry/d|*E[FPT] - cost|; "
          f"zs = z(fly 2b-f-k): zs>0 = fly above its 3y mean (belly cheap; "
          f"fade = receive belly); residual>0 = CHEAP; all vols bp/day\n")
    print(_fmt(df))
    print()
    units_ok = _gates(df)
    fvc = df.attrs.get("frontier_value_carry", {})
    fcv = df.attrs.get("frontier_carry_vol", {})
    print(f"=== frontiers === value-carry slope={fvc.get('slope'):.3f} "
          f"r2={fvc.get('r2'):.3f} n={fvc.get('n'):.0f} | "
          f"carry-vol slope={fcv.get('slope'):.3f} r2={fcv.get('r2'):.3f} "
          f"n={fcv.get('n'):.0f}")
    print(_summary(df))
    if not units_ok:
        raise SystemExit(
            "sigma_rlzd failed the units median guard — a bp/yr series has "
            "crossed the ledger boundary; every downstream number is suspect")
    if n_priced == 0:
        print("\nNOTHING PRICED: every fly theta is NaN (curve could not "
              "express the packages)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
