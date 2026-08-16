"""Artifact builder for the strategy-1 THREE-WAY study (curve vs swaption vs listed).

The three-way study needs almost no new heavy computation, and that is a design
decision rather than an accident:

* the **signal panel** already exists. ``strat1_listed_signal_panel.parquet``
  carries, on every (date, structure) row, the curve breakeven, the
  sector-matched 1Yx2Y swaption ATMF and the horizon-matched listed SFR ATM --
  all three already in bp/day. Rebuilding it here would create a second set of
  numbers that could disagree with the first for no reason.
* the **cohort P&L** already exists too. ``strat1_listed_cohorts_*.parquet``
  carries every cohort's realised P&L together with the ``direction`` it was
  traded in. Swap NPV is linear in ``bpv``, so the P&L of the same cohort held
  the other way round is the exact negation, and every gate mode can be scored
  off one stored run instead of one engine pass per mode.

That second claim is load-bearing, so this script VERIFIES it rather than
asserting it: ``verify`` re-runs one structure with a constant flattener signal
and ties the result out cohort-by-cohort against the stored mixed-direction run.

Usage (from the repo root, conda env ``stir``)::

    python notebooks/backtests/convexity_rv/_strat1_threeway_build.py verify
    python notebooks/backtests/convexity_rv/_strat1_threeway_build.py panels
    python notebooks/backtests/convexity_rv/_strat1_threeway_build.py all

NETWORK: nothing here touches a listed-option MDP or ``sabr_smile``. Everything
is read from local parquet; the single ``verify`` run uses the local
``CITIVELO_EXCEL`` swap-curve store.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from RVUtils.ConvexityRV import strat1_threeway as tw

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)

CFG = tw.Strat1ThreeWayConfig()

PANEL = DATA / "strat1_listed_signal_panel.parquet"
TW_PANEL = DATA / "strat1_threeway_panel.parquet"
TW_BASIS = DATA / "strat1_threeway_basis.parquet"
TW_BOOKS = DATA / "strat1_threeway_books.parquet"
TW_VERIFY = DATA / "strat1_threeway_linearity.json"


def safe(label: str) -> str:
    return label.replace("/", "-").replace(" ", "_")


def load_panel() -> pd.DataFrame:
    if not PANEL.exists():
        raise SystemExit(f"missing {PANEL} -- run _strat1_listed_build.py first")
    p = pd.read_parquet(PANEL)
    p["date"] = pd.to_datetime(p["date"])
    return p


def load_cohorts() -> dict:
    out = {}
    for label, _f, _b in CFG.structures:
        p = DATA / f"strat1_listed_cohorts_{safe(label)}.parquet"
        if p.exists():
            out[label] = pd.read_parquet(p)
    return out


# --------------------------------------------------------------- verification


def verify_linearity(label: str = "2Yx2Y/3Yx2Y") -> None:
    """Re-run ONE structure as a pure flattener and tie out against the stored run.

    The stored run traded a mixed book (62 steepeners, 43 flatteners for
    2Yx2Y/3Yx2Y). If NPV is linear in ``bpv`` -- which is the whole basis for
    scoring every gate mode off one engine pass -- then for every cohort::

        gross(flattener) == direction_stored * gross(stored)

    to machine precision. Anything else and the derivation in
    ``strat1_threeway.apply_gate`` is invalid and this script says so instead of
    quietly proceeding.
    """
    from RVUtils.ConvexityRV import strat1_listed as sl

    panel = load_panel()
    stored = load_cohorts().get(label)
    if stored is None:
        raise SystemExit(f"no stored cohort table for {label!r}")

    front, back = next((f, b) for (l, f, b) in CFG.structures if l == label)
    sub = panel[panel["structure"] == label].set_index("date").sort_index()
    cached = DATA / f"strat1_threeway_unit_cohorts_{safe(label)}.parquet"

    if cached.exists():
        # The engine pass is deterministic and takes ~4 minutes; re-running it to
        # recompute a summary would be a slower way to get the same answer.
        fresh = pd.read_parquet(cached)
        for c in ("entry", "exit"):
            fresh[c] = pd.to_datetime(fresh[c])
        print(f"{label}: reusing cached unit-flattener run ({len(fresh)} cohorts)",
              flush=True)
    else:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        # Constant flattener, put through the IDENTICAL lag the stored run used.
        unit_signal = pd.Series(1.0, index=sub.index).shift(1).fillna(0.0)
        lcfg = sl.Strat1ListedConfig()
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        bt, cohorts = sl.build_backtest(
            mdp, lcfg.curve_config(), label, front, back, unit_signal, sub.index)
        print(f"{label}: unit-flattener run, {len(cohorts)} cohorts "
              f"(stored had {len(stored)})", flush=True)
        t0 = time.time()
        bt.run()
        if not getattr(bt, "mtm_history", None):
            raise SystemExit(f"{label}: engine produced no mtm_history -- run() failed")
        print(f"{label}: ran in {time.time() - t0:.0f}s", flush=True)
        fresh = sl.cohort_table(bt, cohorts, lcfg.curve_config())
        fresh.to_parquet(cached, index=False)
    m = stored.merge(fresh, on="entry", suffixes=("_stored", "_unit"))
    both = m[m["closed_stored"] & m["closed_unit"]].copy()
    both["implied_unit"] = both["direction_stored"] * both["gross_pnl_bp_stored"]
    err = (both["gross_pnl_bp_unit"] - both["implied_unit"]).abs()

    # The unit run opens a cohort on EVERY weekly grid date; the stored run
    # skipped the dates whose lagged listed signal was 0. So stored entries must
    # be a SUBSET of unit entries, and each extra date must be one where no gate
    # mode would have traded anyway -- otherwise the derived books have a hole.
    se = set(pd.to_datetime(stored["entry"]))
    fe = set(pd.to_datetime(fresh["entry"]))
    extra = sorted(fe - se)
    three = tw.threeway_frame(panel, CFG).xs(label, level="structure")
    extra_gates = {}
    for d in extra:
        prev = three.index[three.index < d]
        extra_gates[str(d.date())] = (
            {m: float(three.loc[prev[-1], f"gate_{m}"]) for m in tw.GATE_MODES}
            if len(prev) else "no prior grid day (first date -- lagged to flat)")

    res = {
        "structure": label,
        "n_cohorts_stored": int(len(stored)),
        "n_cohorts_unit": int(len(fresh)),
        "n_matched_closed": int(len(both)),
        "max_abs_err_bp": float(err.max()) if len(err) else float("nan"),
        "median_abs_err_bp": float(err.median()) if len(err) else float("nan"),
        "stored_entries_subset_of_unit": bool(not (se - fe)),
        "extra_unit_entries": [str(d.date()) for d in extra],
        "extra_entry_gates": extra_gates,
        "no_gate_wanted_the_extra_dates": all(
            g == "no prior grid day (first date -- lagged to flat)"
            or all(v == 0.0 for v in g.values())
            for g in extra_gates.values()),
        "linearity_holds": bool(len(err) and err.max() < 1e-6),
    }
    print(json.dumps(res, indent=2))
    TW_VERIFY.write_text(json.dumps(res, indent=2), encoding="utf-8")
    if not res["linearity_holds"]:
        raise SystemExit("LINEARITY CHECK FAILED -- do not use apply_gate()")
    if not (res["stored_entries_subset_of_unit"] and res["no_gate_wanted_the_extra_dates"]):
        raise SystemExit("COHORT COVERAGE GAP -- a gate mode wants a cohort the "
                         "stored run never opened; derived books would be incomplete")
    print("linearity holds: gate books may be derived from the stored cohort tables")


# -------------------------------------------------------------------- panels


def build_panels() -> None:
    panel = load_panel()
    three = tw.threeway_frame(panel, CFG)
    three.reset_index().to_parquet(TW_PANEL, index=False)
    print(f"three-way panel: {len(three)} rows, "
          f"{three.index.get_level_values('date').nunique()} dates", flush=True)

    basis = tw.basis_frame(panel, CFG)
    basis.reset_index().to_parquet(TW_BASIS, index=False)
    print(f"basis series: {len(basis)} dates", flush=True)

    coh = load_cohorts()
    books = tw.all_gate_books(three, coh, CFG)
    books.to_parquet(TW_BOOKS, index=False)
    print(f"gate books: {len(books)} cohort-rows across "
          f"{books['gate_mode'].nunique()} modes x {books['structure'].nunique()} structures",
          flush=True)


def build_all() -> None:
    build_panels()
    verify_linearity()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "verify":
        verify_linearity(*(sys.argv[2:3] or []))
    elif cmd == "panels":
        build_panels()
    elif cmd == "all":
        build_all()
    else:
        raise SystemExit(f"unknown command {cmd!r}")
