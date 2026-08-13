"""Build a panel under an alternate spline fit, and compare the book it produces.

THE QUESTION. The GSS signal is a ~1-3bp yield residual against a fitted curve, measured on
OFF-THE-RUN bonds — `exclude_ranks=(0,)` drops the on-the-runs by design. If the fit itself
manufactures part of that residual, the signal is reading the interpolator rather than the market,
and its mean-reversion would be mechanical.

`S3_shift` is the sharpest probe: the SAME NUMBER of knots, slid 1.25 years. Nothing about the
market changed, only where the spline is allowed to bend. If the trade set survives, the residual
is a property of the bonds. If it moves, the residual is partly a property of the fit — and no
amount of parameter tuning fixes that, because the signal would be measuring the wrong thing.

Each refit is ~19 minutes for 332 days, so panels are built one process per spline and cached
under their own directory (the day cache is keyed by date; sharing one would interleave fits).

    conda run -n stir python scripts/gss_spline_panels.py --spline S3_shift
    conda run -n stir python scripts/gss_spline_panels.py --compare
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly.conditioning import trade_set_jaccard  # noqa: E402
from BT.gss_fly.data import build_curve_panel, spline_config_id, ust_business_days  # noqa: E402
from gss_grid import INCUMBENT_CONSTRUCTION, INCUMBENT_GATE, make_cfg, spline_variants  # noqa: E402

CACHE = "notebooks/data/gss_fly/panel_cached"


def _panel(name: str, start: str, end: str, workers: int):
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days(start, end)
    sp = spline_variants()[name]
    t0 = time.time()
    panel = build_curve_panel(days, mdp, cache_path=Path(CACHE), show_progress=False,
                              spline_config=sp, workers=workers)
    return mdp, panel, time.time() - t0, sp


def _decisions(panel, mdp):
    """The incumbent book's ENTER/EXIT log under this panel — decision layer only, no pricing."""
    from BT.gss_fly.signals import build_bond_signals
    from BT.gss_fly.strategy import GSSSignalEngine, scan_candidates

    cfg = make_cfg(INCUMBENT_CONSTRUCTION, INCUMBENT_GATE)
    sig = build_bond_signals(panel.s2c, cfg.signal)["signal"]
    cands = scan_candidates(GSSSignalEngine(panel, sig, cfg), panel.dates)
    eng = GSSSignalEngine(panel, sig, cfg, candidates=cands)
    for d in panel.dates:
        eng(d)
    return pd.DataFrame(eng.log) if eng.log else pd.DataFrame(columns=["date", "event", "fly_id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spline", default="")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    if args.spline:
        name = args.spline
        mdp, panel, el, sp = _panel(name, args.start, args.end, args.workers)
        print(f"SP[{name}]: {panel.summary()}  built in {el/60:.1f} min  "
              f"id={spline_config_id(sp)}", flush=True)
        # A variant whose panel is bit-identical to the baseline is not a variant. Say so rather
        # than reporting it as an axis that did not matter.
        log = _decisions(panel, mdp)
        n = int((log["event"] == "ENTER").sum()) if len(log) else 0
        out = Path("notebooks/data/gss_fly/spline_logs")
        out.mkdir(parents=True, exist_ok=True)
        log.to_parquet(out / f"{name}.parquet")
        pd.Series({"median_rmse_bp": float(panel.rmse.median()),
                   "s2c_std_bp": float(np.nanstd(panel.s2c.to_numpy())),
                   "n_entries": n, "dates": len(panel.dates)}).to_json(out / f"{name}.json")
        print(f"SP[{name}]: median RMSE {panel.rmse.median():.3f}bp  "
              f"s2c sd {np.nanstd(panel.s2c.to_numpy()):.3f}bp  entries {n}", flush=True)
        print("SPDONE", flush=True)
        return 0

    if args.compare:
        d = Path("notebooks/data/gss_fly/spline_logs")
        base_p = d / "S0_jpm.parquet"
        if not base_p.exists():
            print("SP: baseline S0_jpm log missing", flush=True)
            return 1
        base = pd.read_parquet(base_p)
        rows = []
        for p in sorted(d.glob("*.parquet")):
            name = p.stem
            log = pd.read_parquet(p)
            meta = {}
            j = d / f"{name}.json"
            if j.exists():
                meta = pd.read_json(j, typ="series").to_dict()
            rows.append({
                "spline": name,
                "median_rmse_bp": meta.get("median_rmse_bp", np.nan),
                "s2c_std_bp": meta.get("s2c_std_bp", np.nan),
                "n_entries": int((log["event"] == "ENTER").sum()) if len(log) else 0,
                "jaccard_vs_S0": trade_set_jaccard(base, log, tolerance_days=0),
                "jaccard_tol3": trade_set_jaccard(base, log, tolerance_days=3),
            })
        t = pd.DataFrame(rows).sort_values("jaccard_vs_S0")
        print("\n=== SPLINE SENSITIVITY — does the signal survive a change of FIT? ===", flush=True)
        print(t.to_string(index=False), flush=True)
        print("\n  S3_shift is the key row: SAME knot count, slid 1.25y. A low Jaccard there means",
              flush=True)
        print("  the residual is partly an artifact of where the spline bends, not of the market.",
              flush=True)
        t.to_csv("notebooks/data/gss_fly/spline_sensitivity.csv", index=False)
        print("SPDONE", flush=True)
        return 0

    print("SP: pass --spline NAME or --compare", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
