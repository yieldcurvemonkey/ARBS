"""Artifact builder for the strategy-1 THREE-WAY study on the **LONG END**.

The short-end (SFR) three-way study was capped at 517 dates by the SFR panel and
ran on SFR-sector structures. The constant-maturity UST harvest removed both
limits: curve, swaption AND listed now all cover 2019-01..2026-08, and the
structures are the ones strategy 1 actually recommends. This script builds the
artifacts for that run.

Nothing here recomputes a curve number. Both heavy inputs already exist:

* the **long-end listed panel** (``strat1_listed_longend_panel.parquet``, 62,333
  rows = date x structure x benchmark), built by ``_strat1_listed_build.py
  longend``. It carries the curve breakeven, the 1Yx30Y swaption ATMF and the
  listed ABPV, all three already in bp/day, for twelve (root, constant maturity)
  benchmarks.
* the **stored strategy-1 cohort tables** (``strat1_cohorts_*.parquet``), one per
  long-end structure, 88 monthly cohorts each with the ``direction`` they were
  traded in.

The gate books are derived arithmetically from those stored cohorts rather than
by one engine pass per gate mode. Swap NPV is linear in ``bpv`` so that identity
is exact -- but it is load-bearing, and on the long end it is load-bearing in
exactly ONE place: three of the four structures were traded with
``direction == +1`` on all 88 cohorts (strategy 1's signal never went short
there), so for them the "unit flattener" run is the stored run and the identity
is trivial. **5Y/30Y is the only structure whose stored book is mixed** (45
flatteners, 43 steepeners), so it is the only one where the negation identity
does real work -- and it is the one ``verify`` re-runs against the engine.

Usage (from the repo root, conda env ``stir``)::

    python notebooks/backtests/convexity_rv/_strat1_threeway_longend_build.py verify
    python notebooks/backtests/convexity_rv/_strat1_threeway_longend_build.py panels
    python notebooks/backtests/convexity_rv/_strat1_threeway_longend_build.py all

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

CFG = tw.longend_config()

LONGEND_PANEL = DATA / "strat1_listed_longend_panel.parquet"
TW_PANEL = DATA / "strat1_threeway_longend_panel.parquet"
TW_BASIS = DATA / "strat1_threeway_longend_basis.parquet"
TW_BOOKS = DATA / "strat1_threeway_longend_books.parquet"
TW_SWEEP = DATA / "strat1_threeway_longend_sweep.csv"
TW_VERIFY = DATA / "strat1_threeway_longend_linearity.json"
TW_VERDICT = DATA / "strat1_threeway_longend_verdict.json"

#: The structure whose stored book is MIXED, and therefore the only one on which
#: the linearity identity and the signal lag can actually be tested.
MIXED_STRUCTURE = "5Y/30Y"


def safe(label: str) -> str:
    return label.replace("/", "-").replace(" ", "_")


def load_longend_panel() -> pd.DataFrame:
    if not LONGEND_PANEL.exists():
        raise SystemExit(f"missing {LONGEND_PANEL} -- run _strat1_listed_build.py longend")
    p = pd.read_parquet(LONGEND_PANEL)
    p["date"] = pd.to_datetime(p["date"])
    return p


def load_cohorts() -> dict:
    """Strategy 1's OWN stored long-end cohort tables, keyed by structure label."""
    out = {}
    for label, _f, _b in CFG.structures:
        p = DATA / f"strat1_cohorts_{safe(label)}.parquet"
        if p.exists():
            out[label] = pd.read_parquet(p)
    return out


# --------------------------------------------------------------- verification


def verify_linearity(label: str = MIXED_STRUCTURE) -> None:
    """Re-run ONE structure as a pure flattener and tie out against the stored run.

    For every matched, closed cohort::

        gross(flattener) == direction_stored * gross(stored)

    to machine precision, or the derivation in ``strat1_threeway.apply_gate`` is
    invalid and this script says so instead of quietly proceeding.

    ``5Y/30Y`` is the default and the right default: it is the only long-end
    structure whose stored directions are mixed, so it is the only one where the
    identity is not the trivial ``+1 * x == x``.
    """
    from RVUtils.ConvexityRV import strat1_curve_gamma as s1

    panel = load_longend_panel()
    stored = load_cohorts().get(label)
    if stored is None:
        raise SystemExit(f"no stored cohort table for {label!r}")

    front, back = next((f, b) for (l, f, b) in CFG.structures if l == label)
    # One row per date for this structure: the long-end panel repeats each
    # (date, structure) once per benchmark, and the CURVE side is identical
    # across them.
    sub = (panel[panel["structure"] == label]
           .drop_duplicates(subset=["date"]).set_index("date").sort_index())
    cached = DATA / f"strat1_threeway_longend_unit_cohorts_{safe(label)}.parquet"

    # Strategy 1's OWN config, not a three-way one: the stored cohorts were built
    # with it, so the cohort grid, horizon, package DV01 and costs must match it
    # exactly or the tie-out compares two different experiments.
    s1cfg = s1.Strat1Config(structures=CFG.structures)
    if cached.exists():
        fresh = pd.read_parquet(cached)
        for c in ("entry", "exit"):
            fresh[c] = pd.to_datetime(fresh[c])
        print(f"{label}: reusing cached unit-flattener run ({len(fresh)} cohorts)",
              flush=True)
    else:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        # Constant flattener, through the IDENTICAL lag the stored run used.
        unit_signal = pd.Series(1.0, index=sub.index).shift(1).fillna(0.0)
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        bt, cohorts = s1.build_backtest(
            mdp, s1cfg, label, front, back, unit_signal, sub.index)
        print(f"{label}: unit-flattener run, {len(cohorts)} cohorts "
              f"(stored had {len(stored)})", flush=True)
        t0 = time.time()
        bt.run()
        if not getattr(bt, "mtm_history", None):
            raise SystemExit(f"{label}: engine produced no mtm_history -- run() failed")
        print(f"{label}: ran in {time.time() - t0:.0f}s", flush=True)
        fresh = s1.cohort_table(bt, cohorts, s1cfg)
        fresh.to_parquet(cached, index=False)

    m = stored.merge(fresh, on="entry", suffixes=("_stored", "_unit"))
    both = m[m["closed_stored"] & m["closed_unit"]].copy()
    both["implied_unit"] = both["direction_stored"] * both["gross_pnl_bp_stored"]
    err = (both["gross_pnl_bp_unit"] - both["implied_unit"]).abs()

    # ---------------------------------------------------------------- coverage
    # The unit run opens a cohort on EVERY monthly grid date; the stored run
    # skipped dates whose LAGGED signal was 0. Stored entries must therefore be a
    # SUBSET of unit entries, and the difference has to be explained rather than
    # waved at.
    #
    # The explanation must be read off STRATEGY 1's OWN grid, not the three-way
    # grid. They are not the same grid: the curve store has rows on days the
    # exchange is shut, so 2024-03-29 (Good Friday) exists in
    # strat1_signal_panel.parquet but not in the listed panel. Asking the
    # three-way frame "what was the gate on the day before 2024-04-01?" answers
    # for 2024-03-28 and reports a live gate, while the stored run actually
    # lagged onto 2024-03-29 -- where the swaption cube is empty, so its signal
    # was 0 and the cohort was never opened. Evaluating the check on the wrong
    # grid turns a data hole into a phantom disagreement.
    se = set(pd.to_datetime(stored["entry"]))
    fe = set(pd.to_datetime(fresh["entry"]))
    extra = sorted(fe - se)

    s1grid = (_as_s1_panel()[lambda d: d["structure"] == label]
              .set_index("date").sort_index())
    three = tw.threeway_frame(
        tw.select_longend_benchmark(panel, role="primary", cm_days=30), CFG
    ).xs(label, level="structure")

    unit_by_entry = fresh.set_index("entry")
    detail = {}
    for d in extra:
        prev = s1grid.index[s1grid.index < d]
        lagged = prev[-1] if len(prev) else None
        row = s1grid.loc[lagged] if lagged is not None else None
        gates = ({mo: float(three.loc[three.index[three.index < d][-1], f"gate_{mo}"])
                  for mo in tw.GATE_MODES}
                 if len(three.index[three.index < d]) else None)
        u = unit_by_entry.loc[d] if d in unit_by_entry.index else None
        detail[str(d.date())] = {
            "stored_lagged_onto": (str(lagged.date()) if lagged is not None else None),
            "stored_signal_there": (float(row["signal"]) if row is not None else None),
            "swaption_atmf_there": (None if row is None or not np.isfinite(row["atmf_vol_bp_day"])
                                    else float(row["atmf_vol_bp_day"])),
            "why_skipped": ("swaption ATMF is NaN on the lagged date, so strategy 1's "
                            "own signal was 0 and no cohort opened"
                            if row is not None and not np.isfinite(row["atmf_vol_bp_day"])
                            else "lagged signal was 0 for another reason"),
            "in_listed_grid": bool(lagged is not None and lagged in three.index),
            "gate_on_threeway_grid": gates,
            "unit_gross_bp_if_it_had_opened": (float(u["gross_pnl_bp"])
                                               if u is not None and bool(u["closed"]) else None),
            "gated_gross_bp_if_it_had_opened": (
                float(gates["both"] * u["gross_pnl_bp"])
                if (u is not None and bool(u["closed"]) and gates) else None),
        }

    omitted = [v["gated_gross_bp_if_it_had_opened"] for v in detail.values()
               if v["gated_gross_bp_if_it_had_opened"] is not None
               and v["gate_on_threeway_grid"]["both"] != 0.0]

    res = {
        "structure": label,
        "why_this_structure": (
            "the only long-end structure with a MIXED stored book "
            f"({int((stored['direction'] > 0).sum())} flatteners, "
            f"{int((stored['direction'] < 0).sum())} steepeners); on the other "
            "three every stored direction is +1 and the identity is trivial."),
        "n_cohorts_stored": int(len(stored)),
        "n_cohorts_unit": int(len(fresh)),
        "n_matched_closed": int(len(both)),
        "n_stored_steepeners": int((stored["direction"] < 0).sum()),
        "max_abs_err_bp": float(err.max()) if len(err) else float("nan"),
        "median_abs_err_bp": float(err.median()) if len(err) else float("nan"),
        "linearity_holds": bool(len(err) and err.max() < 1e-6),
        "stored_entries_subset_of_unit": bool(not (se - fe)),
        "extra_unit_entries": [str(d.date()) for d in extra],
        "extra_entry_detail": detail,
        "all_extras_explained_by_missing_swaption": all(
            v["swaption_atmf_there"] is None for v in detail.values()),
        # what the omission is worth, MEASURED off the unit run rather than assumed
        "n_omitted_cohorts_a_gate_would_have_traded": len(omitted),
        "omitted_gated_gross_bp": omitted,
        "omission_note": (
            "these cohorts are omitted IDENTICALLY from every gate mode, because "
            "every mode is scored on the same stored cohort set. The gate "
            "COMPARISON is therefore unaffected; only the absolute level of each "
            "gate's P&L is, by the amounts above."),
    }
    printable = {k: v for k, v in res.items() if k != "extra_entry_detail"}
    print(json.dumps(printable, indent=2))
    for d, v in detail.items():
        print(f"  {d}: lagged onto {v['stored_lagged_onto']} "
              f"(swaption {'MISSING' if v['swaption_atmf_there'] is None else 'present'}, "
              f"stored signal {v['stored_signal_there']}), "
              f"gate would have been {None if not v['gate_on_threeway_grid'] else v['gate_on_threeway_grid']['both']}, "
              f"worth {v['gated_gross_bp_if_it_had_opened']} bp gross")
    TW_VERIFY.write_text(json.dumps(res, indent=2), encoding="utf-8")

    if not res["linearity_holds"]:
        raise SystemExit("LINEARITY CHECK FAILED -- do not use apply_gate()")
    if not res["stored_entries_subset_of_unit"]:
        raise SystemExit("COHORT COVERAGE GAP -- the stored run opened a cohort the "
                         "unit run did not; the two grids disagree")
    if not res["all_extras_explained_by_missing_swaption"]:
        raise SystemExit("UNEXPLAINED COHORT GAP -- an entry the stored run skipped "
                         "is not explained by a missing swaption quote")
    print("\nlinearity holds exactly; every skipped entry is explained by a missing "
          "swaption quote on the lagged date, and the omission is identical across "
          "gate modes")


def _as_s1_panel() -> pd.DataFrame:
    """Strategy 1's own signal panel -- the grid the stored cohorts were built on."""
    p = DATA / "strat1_signal_panel.parquet"
    if not p.exists():
        raise SystemExit(f"missing {p}")
    d = pd.read_parquet(p)
    d["date"] = pd.to_datetime(d["date"])
    return d


# -------------------------------------------------------------------- panels


def build_panels() -> None:
    panel = load_longend_panel()

    sel = tw.select_longend_benchmark(panel, role="primary", cm_days=30)
    three = tw.threeway_frame(sel, CFG)
    three.reset_index().to_parquet(TW_PANEL, index=False)
    print(f"three-way panel (primary @ cm=30): {len(three)} rows, "
          f"{three.index.get_level_values('date').nunique()} dates", flush=True)

    basis = tw.longend_basis_frame(panel, CFG)
    basis.reset_index().to_parquet(TW_BASIS, index=False)
    print(f"basis series: {len(basis)} rows across "
          f"{basis['listed_symbol'].nunique()} benchmarks", flush=True)

    sweep = tw.benchmark_sweep_table(panel, CFG)
    sweep.to_csv(TW_SWEEP, index=False)
    print(f"benchmark sweep: {len(sweep)} (structure, benchmark) rows", flush=True)

    coh = load_cohorts()
    books = tw.all_gate_books(three, coh, CFG)
    books.to_parquet(TW_BOOKS, index=False)
    print(f"gate books: {len(books)} cohort-rows across "
          f"{books['gate_mode'].nunique()} modes x {books['structure'].nunique()} "
          "structures", flush=True)

    verdict = tw.longend_verdict(three, basis, sweep=sweep, books=books,
                                 cohorts=coh, cfg=CFG)
    TW_VERDICT.write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print("\n" + verdict["listed_information"]["verdict"], flush=True)


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
