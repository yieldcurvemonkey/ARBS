"""Engine passes for the factor-neutral sizing study -- ONE run per LEG.

    python notebooks/backtests/convexity_rv/_factor_neutral_build.py leg 30Y
    python notebooks/backtests/convexity_rv/_factor_neutral_build.py legs        # all 8
    python notebooks/backtests/convexity_rv/_factor_neutral_build.py greeks
    python notebooks/backtests/convexity_rv/_factor_neutral_build.py certify "5Y/30Y"

``leg`` / ``legs``
    Opens ONE outright leg at $100k DV01 on every cohort date of strategy 1's
    committed monthly schedule, holds a year, unwinds at fee 0, and caches the
    daily equity, the cohort table and the per-cohort daily marks. Because swap
    NPV is linear in notional, these eight mark matrices span every sizing the
    study compares -- see ``factor_neutral_sizing``'s module docstring.

``greeks``
    A LIGHT pass over the ~91 cohort entry dates only: each leg's gamma (second
    central difference of ``payoff_profile`` under +/-25bp parallel shifts) and
    its 1-year carry-and-roll. Needed to express any sizing at matched convexity
    and to price the hedge's own carry. Minutes, not hours.

``certify``
    A GENUINE three-leg ``QueryDrivenBacktest`` of the composed ``pc12_neutral``
    book -- same per-cohort weights the composition uses, fed to the engine as
    three tagged legs. Reproducing the old two-leg book from per-leg marks
    certifies the composition arithmetic; only this certifies the NEW weights.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys
import time
import types
from typing import Any, Dict, List

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from RVUtils.ConvexityRV import factor_neutral_sizing as fns
from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV import strat1_longend_listed as ll

DATA = _REPO / "notebooks" / "data" / "convexity_rv"


def _grid() -> pd.DatetimeIndex:
    """The signal-panel grid. Identical across all four structures -- asserted
    by ``fns.assert_shared_schedule`` before anything is composed."""
    panel = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    sub = (panel[panel["structure"] == "5Y/30Y"]
           .drop_duplicates(subset=["date"]).set_index("date").sort_index())
    if sub.empty:
        raise SystemExit("no signal-panel rows for 5Y/30Y")
    return sub.index


def run_leg(leg: str) -> None:
    safe = fns.safe_leg(leg)
    eq_p = DATA / f"fns_leg_equity_{safe}.parquet"
    co_p = DATA / f"fns_leg_cohorts_{safe}.parquet"
    mk_p = DATA / f"fns_leg_marks_{safe}.parquet"
    if eq_p.exists() and co_p.exists() and mk_p.exists():
        print(f"{leg}: cache already complete", flush=True)
        return

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    grid = _grid()
    cfg = ll.strat1_config()
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    eq, cohorts, marks = fns.run_leg(mdp, cfg, leg, grid)

    # The leg schedule must be bit-identical to the stored two-leg unit runs,
    # otherwise the composition is comparing different trades.
    ref = pd.read_parquet(DATA / "strat1_le_unit_cohorts_5Y-30Y.parquet")
    assert list(pd.to_datetime(cohorts["entry"])) == list(pd.to_datetime(ref["entry"])), (
        f"{leg}: cohort ENTRIES differ from the stored unit run")
    assert (list(pd.to_datetime(cohorts["exit"]).fillna(pd.Timestamp("2100-01-01")))
            == list(pd.to_datetime(ref["exit"]).fillna(pd.Timestamp("2100-01-01")))), (
        f"{leg}: cohort EXITS differ from the stored unit run")
    assert int((eq.abs() > 1e-9).sum()) > 0.5 * len(eq), f"{leg}: equity ~identically zero"

    eq.to_frame("equity_usd").to_parquet(eq_p)
    cohorts.to_parquet(co_p, index=False)
    marks.to_parquet(mk_p)
    print(f"{leg}: wrote {len(cohorts)} cohorts ({int(cohorts['closed'].sum())} closed), "
          f"{len(eq)} marks", flush=True)


def run_greeks() -> None:
    """Per-leg gamma and 1-year carry-and-roll on every cohort entry date.

    Gamma is the second central difference of the leg's own payoff profile under
    +/-25 bp parallel shifts -- the same repricing route ``curve_ops`` mandates,
    because ``GAMMA_01`` raises ``NotImplementedError`` on the rateslib backend.
    Carry comes from ``CARRY_AND_ROLL_BPS_RUNNING``, the independently validated
    path, so a sizing's carry cost is measured rather than modelled.

    Both are reported PER $1 of leg DV01, so any weighting composes linearly.
    """
    out = DATA / "fns_leg_greeks.parquet"
    if out.exists():
        print(f"greeks cache already exists at {out}", flush=True)
        return
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from RVUtils.ConvexityRV.curve_ops import payoff_profile

    cfg = ll.strat1_config()
    ref = pd.read_parquet(DATA / "strat1_le_unit_cohorts_5Y-30Y.parquet")
    days = sorted(set(pd.to_datetime(ref["entry"]).dt.date))
    print(f"greeks on {len(days)} entry dates x {len(fns.GREEK_LEGS)} legs", flush=True)

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    h = 25.0
    rows: List[Dict[str, Any]] = []
    t0 = time.time()
    for i, d in enumerate(days):
        try:
            pricer = mdp.get_data({"curve_name": cfg.curve, "timestamp": d})
        except Exception as exc:
            print(f"  {d}: curve unavailable ({type(exc).__name__})", flush=True)
            continue
        if pricer is None:
            continue
        for leg in fns.GREEK_LEGS:
            try:
                q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT,
                                value=IRSwapValue.NPV, tenor=leg, curve=cfg.curve,
                                structure_kwargs={"bpv": fns.UNIT_DV01})
                raw, w = q.resolve_package(pricer_or_curve=pricer)
                res = [pricer.resolve_pricable(s, risk_weight=wt) for s, wt in zip(raw, w)]
                prof = payoff_profile(pricer, res, [-h, 0.0, h], carry_ccy=0.0)
                gamma = float((prof[2] - 2.0 * prof[1] + prof[0]) / (h * h))
                carry = float(sum(float(wt) * float(
                    pricer.carry_and_roll_bps_running(lg, cfg.horizon))
                    for lg, wt in zip(raw, w)))
                rows.append({"date": pd.Timestamp(d), "leg": leg,
                             # per $1 of leg DV01
                             "gamma_per_dv01": gamma / fns.UNIT_DV01,
                             "carry_bp": carry,
                             "rate_pct": float(pricer.fixed_rate(raw[0]))})
            except Exception as exc:
                print(f"  {d} {leg}: {type(exc).__name__}: {exc}", flush=True)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(days)} ({time.time() - t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no greeks resolved")
    df.to_parquet(out, index=False)
    print(f"wrote {out} ({len(df)} rows)", flush=True)


def run_certify(structure: str) -> None:
    """A genuine 3-leg engine run of the composed ``pc12_neutral`` book."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    safe = fns.safe_leg(structure)
    eq_p = DATA / f"fns_certify_equity_{safe}.parquet"
    co_p = DATA / f"fns_certify_cohorts_{safe}.parquet"
    wt_p = DATA / "fns_cohort_weights.parquet"
    if eq_p.exists() and co_p.exists():
        print(f"{structure}: certify cache already complete", flush=True)
        return
    if not wt_p.exists():
        raise SystemExit(f"{wt_p} missing -- build the weights first "
                         "(notebook cell or fns.cohort_weights)")

    W = pd.read_parquet(wt_p)
    W = W[(W["structure"] == structure) & (W["sizing"] == "pc12_neutral")]
    if W.empty:
        raise SystemExit(f"no pc12_neutral weights for {structure}")

    grid = _grid()
    cfg = ll.strat1_config()
    triggers: List[Any] = []
    rows: List[Dict[str, Any]] = []
    for k, g in W.groupby("cohort", sort=True):
        entry = pd.Timestamp(g["entry"].iloc[0]).date()
        ex = g["exit"].iloc[0]
        exit_ = None if pd.isna(ex) else pd.Timestamp(ex).date()
        tag = f"cert_c{int(k):04d}"
        legs = [IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                            tenor=str(r["leg"]), curve=cfg.curve,
                            structure_kwargs={"bpv": float(r["dv01"])}, tags=(tag,))
                for _, r in g.iterrows() if abs(float(r["dv01"])) > 1e-9]
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[entry]),
            actions=[AddQueryAction(query=q, meta={"tags": [tag]}) for q in legs]))
        if exit_ is not None:
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[exit_]),
                actions=[UnwindPositionsAction(match_tag=tag, fee=0.0)]))
        rows.append({"tag": tag, "cohort": int(k), "entry": pd.Timestamp(entry),
                     "exit": pd.NaT if exit_ is None else pd.Timestamp(exit_),
                     "n_legs": len(legs)})

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    bt = QueryDrivenBacktest(time_grid=TimeGrid(list(grid)),
                             strategy=QueryStrategy(name="fns_certify", triggers=triggers),
                             mdp=mdp, show_progress=False)
    print(f"{structure}: 3-leg certify run, {len(rows)} cohorts", flush=True)
    t0 = time.time()
    bt.run()
    if not getattr(bt, "mtm_history", None):
        raise SystemExit(f"{structure}: engine produced no mtm_history -- run() failed")
    print(f"{structure}: ran in {time.time() - t0:.0f}s", flush=True)

    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    eq = eq.sort_index()
    by_tag: Dict[str, float] = {}
    for rec in (getattr(bt.portfolio, "closed_positions_log", []) or []):
        tags = list((rec.get("position_meta") or {}).get("tags", []) or [])
        if tags:
            by_tag[str(tags[0])] = by_tag.get(str(tags[0]), 0.0) + float(
                rec.get("gross_realized_pnl", 0.0))
    tab = pd.DataFrame(rows)
    tab["closed"] = [t in by_tag for t in tab["tag"]]
    tab["gross_pnl_ccy"] = [by_tag.get(t, float("nan")) for t in tab["tag"]]
    eq.to_frame("equity_usd").to_parquet(eq_p)
    tab.to_parquet(co_p, index=False)
    print(f"{structure}: wrote certify run ({int(tab['closed'].sum())} closed)", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "legs"
    if cmd == "leg":
        run_leg(sys.argv[2])
    elif cmd == "legs":
        for lg in fns.LEG_UNIVERSE:
            run_leg(lg)
    elif cmd == "greeks":
        run_greeks()
    elif cmd == "certify":
        run_certify(sys.argv[2] if len(sys.argv) > 2 else "5Y/30Y")
    else:
        raise SystemExit(f"unknown command {cmd!r} (leg | legs | greeks | certify)")
