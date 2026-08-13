"""Where do GSS candidates die? A gate-by-gate funnel over the cached panel.

Three entries in 332 days is not a result, it is a question: is the book genuinely that selective,
or is something upstream starving it? A backtest that trades three times cannot distinguish "the
signal is rare" from "a filter is broken", and both look identical in the summary table.

So count survivors at each gate, per date, and report where the population collapses. The same
scan the engine runs, with no positions and no state, so the counts are the gates alone.

    conda run -n stir python scripts/gss_funnel.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly import GSSConfig, build_curve_panel  # noqa: E402
from BT.gss_fly.data import apply_universe_filter, ust_business_days  # noqa: E402
from BT.gss_fly.flies import scan_flies  # noqa: E402
from BT.gss_fly.signals import build_bond_signals  # noqa: E402
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--cache", default="notebooks/data/gss_fly/panel_cached")
    args = ap.parse_args()

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days(args.start, args.end)
    panel = build_curve_panel(days, mdp, cache_path=Path(args.cache), show_progress=False)
    print(f"FUNNEL: {panel.summary()}", flush=True)

    cfg = GSSConfig()
    signal = build_bond_signals(panel.s2c, cfg.signal)["signal"]  # the blended TS/XS frame

    rows = []
    for ts in panel.dates:
        curve = panel.curve_on(ts)
        if curve.empty:
            continue
        n_bonds = len(curve)
        curve = curve.rename(columns={"s2c": "_s2c"})
        curve["signal"] = signal.loc[ts].reindex(curve.index) if ts in signal.index else np.nan
        elig = apply_universe_filter(curve, cfg.universe)
        if elig.empty or not elig["signal"].notna().any():
            rows.append({"date": ts, "bonds": n_bonds, "eligible": len(elig), "flies": 0,
                         "zsig_pass": 0, "turn_pass": 0, "zsig_max": np.nan, "std_med": np.nan})
            continue

        flies = scan_flies(elig, s2c_panel=panel.s2c, yield_panel=panel.ytm, asof=ts, cfg=cfg.fly)
        zsig = np.array([f.zsig_bp for f in flies], dtype=float) if flies else np.array([])
        zpass = [f for f in flies if f.zsig_bp > cfg.backtest.entry_zsig_bp]
        tpass = [f for f in zpass if np.isfinite(f.d_abs_z) and f.d_abs_z < 0]
        rows.append({
            "date": ts,
            "bonds": n_bonds,
            "eligible": len(elig),
            "flies": len(flies),
            "zsig_pass": len(zpass),
            "turn_pass": len(tpass),
            "zsig_max": float(np.nanmax(zsig)) if zsig.size else np.nan,
            "std_med": float(np.nanmedian([f.std_bp for f in flies])) if flies else np.nan,
        })

    df = pd.DataFrame(rows).set_index("date")
    print(f"FUNNEL: dates={len(df)}", flush=True)
    print("FUNNEL: MEAN PER DATE", flush=True)
    for c in ("bonds", "eligible", "flies", "zsig_pass", "turn_pass"):
        print(f"   {c:>10}: mean {df[c].mean():9.1f}   median {df[c].median():8.1f}   "
              f"dates with >0: {(df[c] > 0).sum():4d}/{len(df)}", flush=True)
    print(f"   {'zsig_max':>10}: mean {df['zsig_max'].mean():9.2f}bp  median {df['zsig_max'].median():8.2f}bp  "
          f"p90 {df['zsig_max'].quantile(0.9):.2f}bp", flush=True)
    print(f"   {'std_med':>10}: median {df['std_med'].median():8.2f}bp  (the vol in ZSig)", flush=True)
    print(f"FUNNEL: gate is ZSig > {cfg.backtest.entry_zsig_bp}bp; "
          f"turning point required = {cfg.backtest.require_turning_point}", flush=True)
    kill = 100.0 * (1 - df["turn_pass"].sum() / max(df["zsig_pass"].sum(), 1))
    print(f"FUNNEL: the turning-point gate alone removes {kill:.1f}% of ZSig survivors", flush=True)
    out = Path("notebooks/data/gss_fly/funnel.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    print(f"FUNNEL: wrote {out}", flush=True)
    print("FUNNELDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
