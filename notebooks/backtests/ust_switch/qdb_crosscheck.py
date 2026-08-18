"""Run one switch through the repo's own ``QueryDrivenBacktest`` and reconcile.

Why this is a cross-check and not the engine
--------------------------------------------
The study's grid runs on a purpose-built vectorised engine. That was not a preference:

* **QDB cannot hold this position by alias.** ``FixedRateBondsMDP`` keys its pricer dict by
  the alias it was asked for, so ``_can_resolve_from_pricer_keys`` short-circuits
  resolution and a held ``O10/CT10`` position stores the ALIAS as its identity. Every
  subsequent mark re-resolves it against that day's reference data, and
  ``FixedRateBondValue._rebuild_pricer`` then keeps the HELD leg's issue/maturity/coupon
  while taking clean_price and ytm from the NEW issue -- the old bond's cashflow schedule
  priced at the new issue's quote. There is no auto-roll machinery to save you:
  ``mark_to_market`` passes ``auto_roll`` and the FRB handler ignores it,
  ``meta["rolls"]`` is created and never written, and ``ConstantMaturityRollTrigger`` is
  never constructed anywhere in the repo.
* **QDB has no per-leg financing hook.** ``UnwindPositionsAction.fee`` is the only cost
  parameter in the engine: a flat currency amount, charged at exit only, divided across
  every matched position. A switch needs a daily, per-issue repo rate on each leg.
* **Speed.** 3,360 configurations x 4,158 days through the QuantLib pricer is not a grid
  search, it is a weekend.

So this file does what ``basis_v3`` does in its own section 11: takes ONE configuration,
runs it through QDB with **explicit CUSIPs pinned at entry** (never aliases, which is what
makes it safe), and checks the two engines agree on the price leg. Agreement there means
the vectorised engine's spread arithmetic matches the repo's pricer-driven marks; the
carry and cost layers sit outside QDB entirely and are validated against JPM elsewhere.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from BT.data_handler import TimeGrid  # noqa: E402
from BT.query_actions import AddQueryAction, UnwindPositionsAction  # noqa: E402
from BT.query_engine import QueryDrivenBacktest  # noqa: E402
from BT.query_strategy import QueryStrategy  # noqa: E402
from BT.triggers import DateTriggerRequirements, Trigger  # noqa: E402
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery  # noqa: E402
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue  # noqa: E402
from RVUtils.USTSwitch.costs import CostModel  # noqa: E402
from RVUtils.USTSwitch.data import load_prepared, select_financing  # noqa: E402
from RVUtils.USTSwitch.engine import SwitchConfig, run_switch  # noqa: E402

pd.set_option("display.width", 220)
OUT = pathlib.Path(__file__).resolve().parent / "_out"


def run_one_qdb(trade: pd.Series, tenor: int, *, dv01_per_bp: float = 1.0):
    """One switch, entry to exit, through QueryDrivenBacktest on pinned CUSIPs.

    Sized so each leg carries ``dv01_per_bp`` dollars of DV01, matching the vectorised
    engine's convention, via ``structure_kwargs={"bpv": ...}``. Long the OLD leg, short
    the YOUNG one.
    """
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

    entry = pd.Timestamp(trade["entry"]).to_pydatetime()
    exit_ = pd.Timestamp(trade["exit"]).to_pydatetime()
    grid_days = pd.bdate_range(entry, exit_).to_pydatetime().tolist()

    long_q = FixedRateBondQuery(
        cusip=str(trade["cusip_old"]),
        value=FixedRateBondValue.NPV,
        structure_kwargs={"bpv": dv01_per_bp},
        tags=("switch",),
    )
    short_q = FixedRateBondQuery(
        cusip=str(trade["cusip_young"]),
        value=FixedRateBondValue.NPV,
        structure_kwargs={"bpv": -dv01_per_bp},
        tags=("switch",),
    )

    enter = Trigger(
        trigger_requirements=DateTriggerRequirements(dates=[entry.date()]),
        actions=[AddQueryAction(query=long_q), AddQueryAction(query=short_q)],
    )
    leave = Trigger(
        trigger_requirements=DateTriggerRequirements(dates=[exit_.date()]),
        actions=[UnwindPositionsAction(match_tag="switch", fee=0.0)],
    )

    strat = QueryStrategy(name="ust-switch-crosscheck", triggers=[enter, leave], default_mdp=mdp)
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(grid_days), strategy=strat, mdp=mdp, show_progress=False
    )
    bt.run()

    # run() wraps each timestep in a bare `except Exception as e: print(e)`, so a pricing
    # failure silently DROPS the whole day from mtm_history rather than raising. A hole is
    # indistinguishable from a flat day unless it is checked for.
    covered = len(bt.mtm_history)
    if covered < len(grid_days):
        print(f"  !! QDB produced {covered} marks for {len(grid_days)} grid days "
              f"-- {len(grid_days) - covered} timesteps were swallowed")

    eq = pd.Series(
        {pd.Timestamp(k): v for k, v in bt.mtm_history.items()}, name="qdb_equity_usd"
    ).sort_index()
    return bt, eq


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    panel_raw, amap = load_prepared()

    cfg = SwitchConfig(
        tenor=10, rank_young=0, rank_old=1, direction=1,
        entry_offset=1, exit_rule="next_roll", exit_offset=1,
        financing_mode="none",   # QDB carries no financing, so compare the PRICE leg only
        cost_multiplier=0.0,     # and no costs
    )
    panel = select_financing(panel_raw, "none")
    res = run_switch(panel, amap, cfg, cost_model=CostModel(multiplier=0.0))
    if res.trades.empty:
        print("vectorised engine produced no trades")
        return 1

    # Recent trades: FedInvest coverage is best there, so a mismatch is a real
    # disagreement rather than a data hole in one engine and not the other.
    sample = res.trades.tail(6)
    rows = []
    for _, tr in sample.iterrows():
        print(f"\n--- cycle entered {pd.Timestamp(tr['entry']).date()} "
              f"exit {pd.Timestamp(tr['exit']).date()}  "
              f"LONG {tr['cusip_old']} / SHORT {tr['cusip_young']} ---")
        try:
            bt, eq = run_one_qdb(tr, cfg.tenor)
        except Exception as exc:
            print(f"  QDB FAILED: {type(exc).__name__}: {exc}")
            continue
        if eq.empty:
            print("  QDB produced no marks")
            continue
        # mtm_history is CUMULATIVE equity (realized + open), not per-step P&L.
        qdb_pnl_usd = float(eq.iloc[-1] - eq.iloc[0])
        vec_pnl_bp = float(tr["price_bp"])
        rows.append(
            {
                "entry": pd.Timestamp(tr["entry"]).date(),
                "exit": pd.Timestamp(tr["exit"]).date(),
                "qdb_pnl_usd_per_dv01": qdb_pnl_usd,
                "vec_price_bp": vec_pnl_bp,
                "diff": qdb_pnl_usd - vec_pnl_bp,
                "n_marks": len(eq),
            }
        )
        print(f"  QDB  {qdb_pnl_usd:+10.4f}   vectorised {vec_pnl_bp:+10.4f}   "
              f"diff {qdb_pnl_usd - vec_pnl_bp:+10.4f}")

    if not rows:
        print("\nno comparable cycles -- cross-check inconclusive")
        return 1
    cmp = pd.DataFrame(rows)
    cmp.to_csv(OUT / "qdb_crosscheck.csv", index=False)
    print("\n=== QDB vs vectorised engine, price leg only ===")
    print(cmp.round(4).to_string(index=False))
    corr = cmp["qdb_pnl_usd_per_dv01"].corr(cmp["vec_price_bp"])
    print(f"\ncorr {corr:.4f}   mean abs diff {cmp['diff'].abs().mean():.4f}   "
          f"max abs diff {cmp['diff'].abs().max():.4f}")
    print(
        "\nA DV01-matched position of $1/bp per leg makes a dollar of P&L equal a basis\n"
        "point of spread, so these two columns are the same quantity measured two ways:\n"
        "QDB marks each bond's NPV through the QuantLib pricer and differences it, while\n"
        "the vectorised engine differences the yield spread directly."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
