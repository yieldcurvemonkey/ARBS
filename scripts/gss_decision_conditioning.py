"""Decision-space conditioning: how much of the book does one parameter step change?

This is the part of "how ill-conditioned is this strategy" that the data can actually answer.
Which trades a configuration takes is a **deterministic** function of its parameters — there is no
estimation error in it, and no amount of extra data would change the answer. Performance is the
opposite: at ~154 active marks the annualised-Sharpe standard error is 0.87 while the whole
cross-config spread is ~1.4, so nothing can be ranked on it.

It is also cheap, because it needs no pricing. ``GSSSignalEngine`` is a pure function of the panel
and the config; running its decision loop over the grid yields the ENTER/EXIT log directly, so a
construction costs one 267s scan and essentially nothing else.

READING THE OUTPUT

``jaccard`` is |A ∩ B| / |A ∪ B| over ``(fly_id, entry_date)`` against the incumbent.

* **J ≳ 0.9** — a nuisance knob. The book is the same book; the parameter is not load-bearing.
* **J ≈ 0.5** — the knob redefines the book. The strategy cannot be specified without pinning it,
  and any performance number quoted for "the strategy" is really a number for one arbitrary choice.
* **J ≲ 0.2** — one step of this knob produces a different strategy entirely.

The **exact vs date-tolerant** pair is the second reading. A large gap (low exact, high tolerant)
means the knob moves the *timing* of a stable trade set; a small gap means it moves the *set*.
Those are different findings and the single number cannot distinguish them.

    conda run -n stir python scripts/gss_decision_conditioning.py --workers 20
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly.conditioning import trade_set_jaccard  # noqa: E402
from BT.gss_fly.data import build_curve_panel, ust_business_days  # noqa: E402
from gss_grid import (CONSTRUCTION_LEVELS, INCUMBENT_CONSTRUCTION, INCUMBENT_GATE,  # noqa: E402
                      make_cfg, valid_construction)

#: gate rays through the incumbent — the levels the user specifically asked about
GATE_RAYS: List[Tuple[str, Any]] = [
    ("backtest.entry_zsig_bp", v) for v in (1.0, 1.5, 2.0, 2.5, 3.5)
] + [
    ("costs.repo_penalty_bp", v) for v in (0.25, 0.5, 1.0, 1.5, 2.0)
] + [
    ("backtest.exit_abs_z", v) for v in (0.25, 1.0)
] + [
    ("backtest.require_turning_point", False),
    ("backtest.reentry_cooldown_days", 0), ("backtest.reentry_cooldown_days", 20),
    ("backtest.max_concurrent", 5), ("backtest.max_concurrent", 25),
]

_W: Dict[str, Any] = {}


def _init(cache: str, start: str, end: str):
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days(start, end)
    _W["panel"] = build_curve_panel(days, mdp, cache_path=Path(cache), show_progress=False)


def _decisions(construction: Dict[str, Any], gates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run the DECISION layer only — no pricing — for one construction across several gates."""
    from BT.gss_fly.signals import build_bond_signals
    from BT.gss_fly.strategy import GSSSignalEngine, scan_candidates

    panel = _W["panel"]
    cfg0 = make_cfg(construction, INCUMBENT_GATE)
    sig = build_bond_signals(panel.s2c, cfg0.signal)["signal"]
    t0 = time.time()
    cands = scan_candidates(GSSSignalEngine(panel, sig, cfg0), panel.dates)
    scan_s = time.time() - t0

    out = []
    for gate in gates:
        eng = GSSSignalEngine(panel, sig, make_cfg(construction, gate), candidates=cands)
        for d in panel.dates:
            eng(d)
        log = pd.DataFrame(eng.log) if eng.log else pd.DataFrame(columns=["date", "event", "fly_id"])
        out.append({"construction": construction, "gate": gate, "log": log, "scan_s": scan_s,
                    "n_enter": int((log["event"] == "ENTER").sum()) if len(log) else 0})
    return out


def _job(args):
    construction, gates, label = args
    try:
        rows = _decisions(construction, gates)
        for r in rows:
            r["label"] = label
        return rows
    except Exception as exc:  # noqa: BLE001
        return [{"label": label, "error": f"{type(exc).__name__}: {exc}", "log": pd.DataFrame(),
                 "construction": construction, "gate": {}, "n_enter": 0, "scan_s": np.nan}]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default="notebooks/data/gss_fly/panel_cached")
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 4))
    ap.add_argument("--tolerance-days", type=int, default=3)
    ap.add_argument("--out", default="notebooks/data/gss_fly/decision_conditioning.csv")
    args = ap.parse_args()

    # construction rays: one knob one step off the incumbent
    jobs = [(dict(INCUMBENT_CONSTRUCTION), [dict(INCUMBENT_GATE)], "BASE")]
    for knob, levels in CONSTRUCTION_LEVELS.items():
        for lv in levels:
            if lv == INCUMBENT_CONSTRUCTION[knob]:
                continue
            c = dict(INCUMBENT_CONSTRUCTION)
            c[knob] = lv
            if valid_construction(c):
                jobs.append((c, [dict(INCUMBENT_GATE)], f"{knob}={lv}"))
    # gate rays all share the incumbent construction, so they ride on ONE scan
    gate_cfgs = []
    for knob, lv in GATE_RAYS:
        g = dict(INCUMBENT_GATE)
        g[knob] = lv
        gate_cfgs.append(g)
    jobs.append((dict(INCUMBENT_CONSTRUCTION), gate_cfgs, "GATES"))

    print(f"GDC: {len(jobs)} scan jobs ({len(gate_cfgs)} gate rays share one), "
          f"{args.workers} workers", flush=True)

    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    collected: List[Dict[str, Any]] = []
    t0 = time.time()
    with ctx.Pool(args.workers, initializer=_init,
                  initargs=(args.cache, args.start, args.end)) as pool:
        for i, rows in enumerate(pool.imap_unordered(_job, jobs), 1):
            collected.extend(rows)
            print(f"GDC: {i}/{len(jobs)} ({(time.time()-t0)/60:.1f} min)", flush=True)

    base = next((r["log"] for r in collected if r.get("label") == "BASE"), None)
    if base is None or base.empty:
        print("GDC: no baseline log — cannot compute Jaccard", flush=True)
        return 1
    n_base = int((base["event"] == "ENTER").sum())
    print(f"GDC: baseline has {n_base} entries", flush=True)

    rows = []
    for r in collected:
        if r.get("error"):
            rows.append({"knob": r["label"], "error": r["error"]})
            continue
        label = r["label"]
        if label == "GATES":
            diff = [k for k, v in r["gate"].items() if INCUMBENT_GATE.get(k) != v]
            label = f"{diff[0]}={r['gate'][diff[0]]}" if diff else "BASE(gate)"
        rows.append({
            "knob": label.split("=")[0],
            "setting": label,
            "n_enter": r["n_enter"],
            "jaccard_exact": trade_set_jaccard(base, r["log"], tolerance_days=0),
            "jaccard_tol": trade_set_jaccard(base, r["log"], tolerance_days=args.tolerance_days),
        })
    tbl = pd.DataFrame(rows)
    tbl = tbl[tbl["setting"] != "BASE"] if "setting" in tbl else tbl
    tbl["timing_vs_set"] = tbl["jaccard_tol"] - tbl["jaccard_exact"]

    per_knob = (tbl.groupby("knob")
                .agg(steps=("setting", "count"),
                     min_jaccard=("jaccard_exact", "min"),
                     median_jaccard=("jaccard_exact", "median"),
                     median_tol=("jaccard_tol", "median"),
                     timing_gap=("timing_vs_set", "median"),
                     n_enter_min=("n_enter", "min"), n_enter_max=("n_enter", "max"))
                .sort_values("median_jaccard"))

    print("\n=== DECISION-SPACE CONDITIONING (Jaccard of the trade set vs the incumbent) ===",
          flush=True)
    print(per_knob.to_string(), flush=True)
    print("\n  J>=0.9 nuisance | J~0.5 the knob redefines the book | J<=0.2 a different strategy",
          flush=True)
    print("  timing_gap = tolerant - exact; large means the knob moves WHEN, not WHICH.", flush=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    tbl.to_csv(args.out, index=False)
    print(f"\nGDC: rows -> {args.out}", flush=True)
    print("GDCDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
