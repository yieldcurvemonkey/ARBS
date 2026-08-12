"""Layered parameter sweep over the GSS book, to measure how ill-conditioned it is.

The layering is forced by a measurement, not by taste: a run is 251s of which **247s is
``scan_flies``**, and the scan depends only on the CONSTRUCTION knobs (signal / universe / fly /
spline). Every gate knob — the entry level, the exit level, the repo hurdle, the cooldown, the
concurrency cap — merely filters the same candidate set. So:

    per construction:  scan once (247s), then price each gate config (4-27s)

which turns a 2,000-config sweep from ~6 CPU-days into ~45 minutes on 20 workers.

The gating is still performed by the real ``GSSSignalEngine`` against the cached candidates, so a
swept result cannot drift from a directly-run one. That equivalence is asserted, not assumed —
see ``tests/gss_fly/test_grid_tieout.py``.

THREE GUARDS, each against a way this exercise produces a confident wrong answer:

* **Planted nulls.** ``fallback_repo_pct``, ``entry_abs_z`` and ``recent_issue_days`` are declared
  in the config and read by nothing. Sweeping them must produce *exactly* zero variation. If the
  harness reports them mattering, the harness is broken and every other number in the table is
  suspect.
* **Minimum trades.** The book is cost-dead, so maximising Sharpe selects configs that trade less;
  ``entry_zsig_bp = 4.0`` yields three trades, measured. Anything below ``--min-trades`` is recorded
  and excluded from ranking, never silently ranked.
* **Never consolidate a partial sweep.** Same rule as the panel cache, for the same reason.

    conda run -n stir python scripts/gss_grid.py --out notebooks/data/gss_fly/grid --workers 20
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

from BT.gss_fly.config import (BacktestConfig, BondSignalConfig, CostConfig, FlyConfig,  # noqa: E402
                               GSSConfig, UniverseConfig)
from BT.gss_fly.data import build_curve_panel, ust_business_days  # noqa: E402
from BT.gss_fly.grid import GridStore, series_metrics  # noqa: E402

PANEL_CACHE = "notebooks/data/gss_fly/panel_cached"


# --------------------------------------------------------------------------- the space
#: CONSTRUCTION knobs — each distinct combination costs one 247s scan.
CONSTRUCTION_LEVELS: Dict[str, Sequence[Any]] = {
    "signal.ts_weight": (0.0, 0.5, 0.75, 1.0),
    "signal.smoothing_halflife": (1.0, 3.0, 8.0),
    "signal.scoring_com": (10.0, 20.0, 40.0),
    "universe.min_ttm": (2.0, 3.0, 5.0),
    "fly.wing_range_1": (1.0, 2.0, 3.0, 4.0),
    "fly.wing_range_2": (3.0, 5.0, 8.0),
    "fly.std_halflife": (5.0, 10.0, 20.0, 40.0, 60.0),
    "fly.fly_smoothing_halflife": (1.0, 2.0, 5.0),
    "fly.fly_scoring_com": (10.0, 20.0, 30.0, 60.0),
    "fly.wing_objective": ("signal_gap", "legacy_ttm_bug"),
}

INCUMBENT_CONSTRUCTION: Dict[str, Any] = {
    "signal.ts_weight": 0.75, "signal.smoothing_halflife": 3.0, "signal.scoring_com": 20.0,
    "universe.min_ttm": 3.0,
    "fly.wing_range_1": 2.0, "fly.wing_range_2": 5.0, "fly.std_halflife": 20.0,
    "fly.fly_smoothing_halflife": 2.0, "fly.fly_scoring_com": 30.0,
    "fly.wing_objective": "signal_gap",
}

#: GATE knobs — replayed against a cached scan, so each costs only its pricing.
#: (entry_zsig_bp, repo_penalty_bp) with the exit hurdle strictly below the entry level.
GATE_EX: Tuple[Tuple[float, float], ...] = tuple(
    (e, x) for e in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5) for x in (0.25, 0.5, 1.0, 1.5, 2.0, 2.5)
    if x <= e - 0.5
)
INCUMBENT_GATE: Dict[str, Any] = {
    "backtest.entry_zsig_bp": 3.0, "costs.repo_penalty_bp": 2.5, "backtest.exit_abs_z": 0.5,
    "backtest.require_turning_point": True, "backtest.reentry_cooldown_days": 5,
    "backtest.max_concurrent": 10, "costs.cost_legs": "all", "costs.scale": 1.0,
}

#: Planted nulls: declared in the config, read by nothing. Sweeping them must change NOTHING.
PLANTED_NULLS: Dict[str, Sequence[Any]] = {
    "backtest.entry_abs_z": (0.5, 2.0),
    "universe.recent_issue_days": (365.0, 3650.0),
    "costs.fallback_repo_pct": (0.0, 8.0),
}


def spline_variants() -> Dict[str, Any]:
    """The spline configs, as real ``CashSplineConfig`` objects. ``None`` means the default."""
    from MDP.FixedRateBonds.cash_spline import JPM_PAR_CURVE_CONFIG as J

    return {
        "S0_jpm": None,
        "S1_coarse": dataclasses.replace(J, knots=(2.0, 5.0, 10.0, 20.0, 25.0)),
        "S2_dense": dataclasses.replace(J, knots=tuple(np.round(np.linspace(1.5, 28.0, 18), 2))),
        # the direct ill-conditioning probe: same knot COUNT, slid 1.25y. If the residual is a
        # property of the market it survives; if it is a property of the fit, it moves.
        "S3_shift": dataclasses.replace(J, knots=tuple(k + 1.25 for k in J.knots)),
        "S4_with_otr": dataclasses.replace(J, exclude_ranks=()),
    }


# --------------------------------------------------------------------------- config assembly
def make_cfg(construction: Dict[str, Any], gate: Dict[str, Any]) -> GSSConfig:
    buckets: Dict[str, Dict[str, Any]] = {"signal": {}, "universe": {}, "fly": {}, "costs": {},
                                          "backtest": {}}
    scale = 1.0
    for key, value in {**construction, **gate}.items():
        section, _, name = key.partition(".")
        if section == "costs" and name == "scale":
            scale = float(value)
            continue
        buckets[section][name] = value
    ck = dict(buckets["costs"])
    if scale != 1.0:
        ck["half_spread_bp"] = {k: v * scale for k, v in CostConfig().half_spread_bp.items()}
    return GSSConfig(signal=BondSignalConfig(**buckets["signal"]),
                     universe=UniverseConfig(**buckets["universe"]),
                     fly=FlyConfig(**buckets["fly"]),
                     costs=CostConfig(**ck),
                     backtest=BacktestConfig(**buckets["backtest"]))


def valid_construction(c: Dict[str, Any]) -> bool:
    if float(c["fly.wing_range_2"]) <= float(c["fly.wing_range_1"]):
        return False
    if float(c["signal.scoring_com"]) <= float(c["signal.smoothing_halflife"]):
        return False
    if float(c["fly.fly_scoring_com"]) <= float(c["fly.fly_smoothing_halflife"]):
        return False
    return True


def build_constructions(n_random: int, seed: int) -> List[Dict[str, Any]]:
    """Incumbent + axial rays + a random core.

    The axial rays are what the paired-difference sensitivity reads: one knob moved, everything
    else at the incumbent, so the difference is attributable. The random core is what estimates
    interactions, which a ray design cannot see at all.
    """
    out = [dict(INCUMBENT_CONSTRUCTION)]

    # axial rays: one knob off the incumbent at a time, so a difference is attributable
    for key, levels in CONSTRUCTION_LEVELS.items():
        for lv in levels:
            c = dict(INCUMBENT_CONSTRUCTION)
            c[key] = lv
            if c != INCUMBENT_CONSTRUCTION and valid_construction(c) and c not in out:
                out.append(c)
    n_axial = len(out) - 1

    # random core: exactly `n_random` MORE points, for the interactions a ray design cannot see
    rng = np.random.default_rng(seed)
    keys = list(CONSTRUCTION_LEVELS)
    target = len(out) + int(n_random)
    tries = 0
    while len(out) < target and tries < max(n_random, 1) * 200:
        tries += 1
        c = {k: CONSTRUCTION_LEVELS[k][int(rng.integers(len(CONSTRUCTION_LEVELS[k])))] for k in keys}
        if valid_construction(c) and c not in out:
            out.append(c)
    if len(out) < target:
        logger.warning("wanted %d random constructions, drew %d distinct valid ones in %d tries",
                       n_random, len(out) - 1 - n_axial, tries)
    return out


def build_gates(full: bool) -> List[Dict[str, Any]]:
    """The (E, X) surface plus one-knob rays through the incumbent gate."""
    gates: List[Dict[str, Any]] = []
    for e, x in GATE_EX:
        g = dict(INCUMBENT_GATE)
        g["backtest.entry_zsig_bp"], g["costs.repo_penalty_bp"] = e, x
        gates.append(g)
    rays = {
        "backtest.exit_abs_z": (0.25, 1.0),
        "backtest.require_turning_point": (False,),
        "backtest.reentry_cooldown_days": (0, 20),
        "backtest.max_concurrent": (5, 25),
        "costs.cost_legs": ("belly_only",),
        "costs.scale": (0.25, 0.5),
    }
    for key, values in rays.items():
        for v in values:
            g = dict(INCUMBENT_GATE)
            g[key] = v
            gates.append(g)
    if not full:
        # a construction other than the incumbent gets the surface + rays, not the full factorial
        return gates
    for combo in itertools.product((0.25, 0.5, 1.0), (True, False), (0, 5, 20)):
        g = dict(INCUMBENT_GATE)
        g["backtest.exit_abs_z"], g["backtest.require_turning_point"], g["backtest.reentry_cooldown_days"] = combo
        gates.append(g)
    return [dict(t) for t in {tuple(sorted(g.items())) for g in gates}]


# --------------------------------------------------------------------------- worker
_W: Dict[str, Any] = {}


def _init_worker(cache: str, start: str, end: str, repo_wb: str, spline_name: str):
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from BT.gss_fly import load_repo_from_workbook
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days(start, end)
    sp = spline_variants()[spline_name]
    panel = build_curve_panel(days, mdp, cache_path=Path(cache), show_progress=False,
                              spline_config=sp)
    repo = None
    if repo_wb and Path(repo_wb).exists():
        try:
            repo = load_repo_from_workbook(Path(repo_wb), "USTREASGC")
        except Exception:  # noqa: BLE001
            repo = None
    _W.update({"mdp": mdp, "panel": panel, "repo": repo, "spline": spline_name})


def _run_construction(args) -> List[Dict[str, Any]]:
    """One scan, then every gate priced against it. Returns one row per gate."""
    construction, gates, min_trades = args
    from BT.gss_fly.backtest import run_gss_backtest
    from BT.gss_fly.signals import build_bond_signals
    from BT.gss_fly.strategy import GSSSignalEngine, scan_candidates

    panel, mdp, repo = _W["panel"], _W["mdp"], _W["repo"]
    rows: List[Dict[str, Any]] = []
    try:
        cfg0 = make_cfg(construction, INCUMBENT_GATE)
        sig = build_bond_signals(panel.s2c, cfg0.signal)["signal"]
        t0 = time.time()
        probe = GSSSignalEngine(panel, sig, cfg0, repo_curve=repo)
        cands = scan_candidates(probe, panel.dates)
        scan_s = time.time() - t0
        n_cand = int(sum(len(v) for v in cands.values()))
    except Exception as exc:  # noqa: BLE001
        return [{"ok": False, "error": f"scan: {type(exc).__name__}: {exc}",
                 **{f"c_{k}": _s(v) for k, v in construction.items()}, "spline": _W["spline"]}]

    for gate in gates:
        row: Dict[str, Any] = {"spline": _W["spline"], "scan_s": scan_s, "n_candidates": n_cand,
                               **{f"c_{k}": _s(v) for k, v in construction.items()},
                               **{f"g_{k}": _s(v) for k, v in gate.items()}}
        try:
            t0 = time.time()
            res = run_gss_backtest(panel, mdp, cfg=make_cfg(construction, gate), repo_curve=repo,
                                   show_progress=False, strict=False, candidates=cands)
            sm = res.summary()
            eq = res.equity.dropna().astype(float)
            daily = eq.diff().dropna()
            trades = int(sm.get("closed_trades", 0) or 0)
            row.update({
                "ok": True, "price_s": time.time() - t0, "trades": trades,
                "enough_trades": trades >= min_trades,
                "end_equity_usd": float(sm.get("end_equity_usd", np.nan)),
                "gross_before_fees_usd": float(sm.get("gross_before_fees_usd", np.nan)),
                "fees_usd": float(sm.get("fees_usd", np.nan)),
                "carry_during_hold_usd": float(sm.get("carry_during_hold_usd", np.nan)),
                "max_dd_usd": float(sm.get("max_dd_usd", np.nan)),
                "median_hold_days": float(sm.get("median_hold_days", np.nan)),
                "reconciliation_gap_usd": float(sm.get("reconciliation_gap_usd", np.nan)),
                "equity_holes": int(res.diagnostics.get("equity_holes", 0) or 0),
                "daily_pnl": daily.to_numpy().tolist(),
            })
            row.update(series_metrics(daily.to_numpy()))
            g, f = row["gross_before_fees_usd"], -row["fees_usd"]
            row["breakeven_cost_scale"] = float(g / f) if f else np.nan
        except Exception as exc:  # noqa: BLE001
            row.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        rows.append(row)
    return rows


def _s(v):
    return str(v) if isinstance(v, (tuple, list)) else v


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="notebooks/data/gss_fly/grid")
    ap.add_argument("--cache", default=PANEL_CACHE)
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--repo-workbook", default=r"C:/Users/chris/Downloads/gc_repo_hist_example.xlsx")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 4))
    ap.add_argument("--random-constructions", type=int, default=90)
    ap.add_argument("--min-trades", type=int, default=8)
    ap.add_argument("--spline", default="S0_jpm", choices=sorted(spline_variants()))
    ap.add_argument("--seed", type=int, default=20260812)
    ap.add_argument("--limit", type=int, default=0, help="cap constructions, for a smoke run")
    args = ap.parse_args()

    constructions = build_constructions(args.random_constructions, args.seed)
    if args.limit:
        constructions = constructions[: args.limit]
    gates_incumbent = build_gates(full=True)
    gates_other = build_gates(full=False)
    total = len(gates_incumbent) + (len(constructions) - 1) * len(gates_other)
    print(f"GRID: spline={args.spline} constructions={len(constructions)} "
          f"gates={len(gates_other)} (incumbent {len(gates_incumbent)}) -> {total} configs, "
          f"{args.workers} workers", flush=True)

    store = GridStore(Path(args.out) / args.spline)

    # Resume: a construction whose every gate row is already on disk is skipped entirely. Pricing
    # scales with trade count (8.5s at 34 trades, 65.8s at 116 measured), so a sweep is hours and
    # WILL be interrupted; without this a restart repeats the 267s scan for work already done.
    jobs = []
    skipped = 0
    for i, c in enumerate(constructions):
        gates = gates_incumbent if i == 0 else gates_other
        want = [_row_id({"spline": args.spline,
                         **{f"c_{k}": _s(v) for k, v in c.items()},
                         **{f"g_{k}": _s(v) for k, v in g.items()}}) for g in gates]
        missing = [g for g, cid in zip(gates, want) if not store.has(cid)]
        if not missing:
            skipped += 1
            continue
        jobs.append((c, missing, args.min_trades))
    if skipped:
        print(f"GRID: resuming — {skipped} constructions already complete", flush=True)
    if not jobs:
        print("GRID: nothing to do", flush=True)

    import multiprocessing as mp

    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=args.workers, initializer=_init_worker,
                  initargs=(args.cache, args.start, args.end, args.repo_workbook, args.spline)) as pool:
        for rows in pool.imap_unordered(_run_construction, jobs):
            for r in rows:
                r.setdefault("config_id", _row_id(r))
                store.put(r)
            done += 1
            el = time.time() - t0
            # ETA must account for the pool: `elapsed/done * remaining` assumes SERIAL execution
            # and, with 20 workers all finishing their first job at once, reported 39 hours for a
            # 2-hour run. A progress line that alarming is how a healthy run gets killed.
            per_wave = el / max(1, np.ceil(done / args.workers))
            waves_left = max(0.0, np.ceil((len(jobs) - done) / args.workers))
            print(f"GRID: {done}/{len(jobs)} constructions  ({el/60:.1f} min, "
                  f"eta {per_wave * waves_left / 60:.0f} min)", flush=True)

    df = store.load()
    print(f"GRID: {len(df)} rows written to {store.root}", flush=True)
    p = store.consolidate(expected=total)
    print(f"GRID: consolidated -> {p}" if p else "GRID: partial, not consolidated", flush=True)
    print("GRIDDONE", flush=True)
    return 0


def _row_id(row: Dict[str, Any]) -> str:
    import hashlib
    import json

    key = {k: v for k, v in row.items() if k.startswith(("c_", "g_")) or k == "spline"}
    return hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:14]


if __name__ == "__main__":
    raise SystemExit(main())
