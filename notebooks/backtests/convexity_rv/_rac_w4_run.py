r"""Workflow 4, first end-to-end run through QueryDrivenBacktest.

Config is deliberately a single defensible baseline, not a grid: the grid is
simulated on panels afterwards and only its top cells are certified through the
engine, per the house rule that a grid must never loop QDB per cell.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from RVUtils.ConvexityRV import rac_backtest as B  # noqa: E402
from RVUtils.ConvexityRV import rac_signal as R  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"

EXIT_PCT = 0.35
MIN_HOLD = 21
MAX_HOLD = 252

sys.stdout.reconfigure(line_buffering=True)
t0 = time.time()
cfg = R.RacConfig()
panel = pd.read_parquet(DATA / "rac_screen_panel.parquet")
sig = R.build_signal_panel(panel, cfg)
d = sig.index.get_level_values("date")
sig = sig[(d >= pd.Timestamp(cfg.start)) & (d <= pd.Timestamp(cfg.end))]
state = R.entry_state(sig, cfg)

eps = B.episodes_from_state(state, exit_pct=EXIT_PCT, rac_pct=sig["rac_pct"],
                            max_hold_days=MAX_HOLD, min_hold_days=MIN_HOLD)
dates = sorted(set(sig.index.get_level_values("date")))
print(f"{len(eps)} episodes over {len(dates)} dates  ({time.time()-t0:.0f}s)")

mdp = IRSwapsMDP(source="CITIVELO_EXCEL")

probe = B.sign_probe(mdp, dates[len(dates) // 2].date())
print(f"sign probe: {probe}")
assert probe["is_flattener"], "bpv<0 is not a flattener on this engine"
assert abs(probe["sum"]) < 1.0, f"package is not DV01-neutral: {probe['sum']}"

for half_spread, tag in ((0.25, "base"), (0.0, "zero_cost")):
    t1 = time.time()
    bt, eq = B.run_backtest(eps, dates, mdp=mdp, half_spread_bp=half_spread,
                            show_progress=False)
    ret = eq.diff().dropna()
    ann = float(ret.mean() / ret.std() * np.sqrt(252.0)) if ret.std() > 0 else float("nan")
    span = (dates[-1] - dates[0]).days / 365.25
    print(f"\n=== half_spread {half_spread}bp ({tag}) ===")
    print(f"  terminal   {eq.iloc[-1]:>16,.0f}")
    print(f"  ann Sharpe {ann:>16.3f}   span {span:.2f}y")
    print(f"  max DD     {float((eq - eq.cummax()).min()):>16,.0f}")
    print(f"  n marks    {len(eq):>16,}   ({time.time()-t1:.0f}s)")
    eq.to_frame("equity").to_parquet(DATA / f"rac_w4_equity_{tag}.parquet")

    closed = getattr(getattr(bt, "portfolio", bt), "closed_positions_log", None)
    if closed is not None and len(closed):
        # The log carries live ResolvedQueryPosition objects (rl.IRS handles and
        # the source query), which pyarrow cannot infer a type for. Project to
        # the scalar columns rather than dropping the log.
        rows = []
        for c in closed:
            d = dict(c) if isinstance(c, dict) else dict(getattr(c, "__dict__", {}))
            pos = d.get("position")
            meta = getattr(pos, "meta", {}) or {}
            rows.append({
                "opened": getattr(pos, "opened", None),
                "closed": d.get("closed") or d.get("date"),
                "pnl": d.get("pnl") or d.get("realized_pnl"),
                "fee": d.get("fee"),
                "tags": ",".join(meta.get("tags", []) or []),
                "entry_npv": meta.get("entry_npv"),
            })
        cl = pd.DataFrame(rows)
        for col in ("opened", "closed"):
            cl[col] = pd.to_datetime(cl[col], errors="coerce")
        print(f"  closed legs {len(cl):,}   realised "
              f"{pd.to_numeric(cl['pnl'], errors='coerce').sum():,.0f}")
        cl.to_parquet(DATA / f"rac_w4_closed_{tag}.parquet")

meta = {"episodes": len(eps), "dates": len(dates),
        "exit_pct": EXIT_PCT, "min_hold": MIN_HOLD, "max_hold": MAX_HOLD,
        "cfg": cfg.to_dict(), "sign_probe": probe}
(DATA / "rac_w4_run.json").write_text(json.dumps(meta, indent=1, default=str))
print(f"\ntotal {time.time()-t0:.0f}s")
