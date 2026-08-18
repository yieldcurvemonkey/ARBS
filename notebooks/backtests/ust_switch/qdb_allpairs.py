"""All-pairs olds/currents switches through QueryDrivenBacktest: the marks layer.

Runs every rank pair among CT/O/OO/OOO (CTvO, CTvOO, CTvOOO, OvOO, OvOOO, OOvOOO) on
every tenor through the QDB engine, and stores **per-cycle daily P&L segments** that the
grid search (``qdb_gridsearch.py``) recombines into parameter variants.

Why parity-split passes
-----------------------
The grid needs each cycle's daily marks ATTRIBUTED to that cycle. A single every-cycle
book is ambiguous on cycle boundaries: with entry roll+0 and exit next-roll+1, consecutive
cycles overlap two days and the second overlap day mixes the old pair's final move with
the new pair's first. Splitting cycles by parity (odd-index cycles in one QDB pass, even
in the other) removes every overlap -- cycle i and cycle i+2 cannot touch even when i+1
was skipped -- so each pass's daily mtm delta belongs to exactly one cycle, exactly.

Spans are [roll+0, next_roll+1]: the widest window any grid variant needs. Entry-offset
variants clip leading days; the next-roll exit variant uses the final day; fixed-hold
variants clip trailing days (capped at the cycle end, stated in the grid layer).

Fees are NOT charged here. The grid layer charges the SR1170 round trip at each VARIANT'S
entry and exit -- charging QDB's unwind fee too would double-count, and different variants
of the same cycle have different durations at entry.

Everything else (pinned CUSIPs, information-set alignment to days both legs price, gated
grid) is inherited from ``qdb_multi_tenor.py``, where each safeguard's necessity was
measured -- most recently the 2023-12-04 20y mark, ~50bp rich and inside the 100bp gate,
which QDB unwound into for +15.3bp on a book whose true annual P&L is ~2bp.

    <env>/python.exe notebooks/backtests/ust_switch/qdb_allpairs.py            # all 84 passes
    <env>/python.exe notebooks/backtests/ust_switch/qdb_allpairs.py --tenors 10 --pairs 0-1
"""

from __future__ import annotations

import argparse
import datetime
import itertools
import os
import pathlib
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from RVUtils.USTSwitch.data import load_prepared, select_financing  # noqa: E402
from RVUtils.USTSwitch.engine import RANK_LABEL, roll_dates  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
STORE = HERE / "_out" / "qdb_allpairs"
TENORS = (2, 3, 5, 7, 10, 20, 30)
PAIRS = tuple(itertools.combinations(range(4), 2))  # (rank_young, rank_old)


def pair_label(ry: int, ro: int) -> str:
    return f"{RANK_LABEL[ry]}v{RANK_LABEL[ro]}"


# ------------------------------------------------------------------ schedule


def build_schedule(panel: pd.DataFrame, amap: pd.DataFrame, tenor: int,
                   ry: int, ro: int, parity: int) -> tuple:
    """Cycles of one parity for one (tenor, pair), spans [roll+0, next_roll+1]."""
    p = panel[panel["tenor"] == tenor]
    dates = pd.DatetimeIndex(sorted(p["date"].unique()))
    by_dr = p.set_index(["date", "rank"]).sort_index()

    rolls = roll_dates(amap, tenor)
    rolls = rolls[(rolls >= dates.min()) & (rolls <= dates.max())]

    def bd(d, n):
        pos = dates.searchsorted(d, side="left") + n
        return dates[pos] if 0 <= pos < len(dates) else None

    by_cusip_dates = {c: set(g) for c, g in p.groupby("cusip")["date"]}
    cycles, grid_days, skipped = [], set(), 0
    for i in range(len(rolls) - 1):
        if i % 2 != parity:
            continue
        entry = bd(rolls[i], 0)
        exit_ = bd(rolls[i + 1], 1)
        if entry is None or exit_ is None or exit_ <= entry:
            skipped += 1
            continue
        try:
            r_y = by_dr.loc[(entry, ry)]
            r_o = by_dr.loc[(entry, ro)]
        except KeyError:
            skipped += 1
            continue
        if isinstance(r_y, pd.DataFrame):
            r_y = r_y.iloc[0]
        if isinstance(r_o, pd.DataFrame):
            r_o = r_o.iloc[0]
        cusip_y, cusip_o = str(r_y["cusip"]), str(r_o["cusip"])
        valid = by_cusip_dates.get(cusip_o, set()) & by_cusip_dates.get(cusip_y, set())
        ok = [d for d in dates if entry <= d <= exit_ and d in valid]
        if len(ok) < 3:
            skipped += 1
            continue
        cycles.append({"i": i, "roll": rolls[i], "next_roll": rolls[i + 1],
                       "entry": ok[0], "exit": ok[-1],
                       "cusip_old": cusip_o, "cusip_young": cusip_y})
        grid_days.update(ok)
    return pd.DatetimeIndex(sorted(grid_days)), cycles, skipped


# ------------------------------------------------------------------ QDB pass


class PassAction:
    risk = None

    def __init__(self, cycles):
        from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
        from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

        self._FRBQ, self._V = FixedRateBondQuery, FixedRateBondValue
        self.entries, self.exits = {}, {}
        for c in cycles:
            self.entries.setdefault(c["entry"].date(), []).append(c)
            self.exits.setdefault(c["exit"].date(), []).append(c)

    def __call__(self, *, now, backtest, info):
        from BT.query_order import QueryOrder, UnwindOrder

        d, orders = now.date(), []
        for c in self.entries.get(d, ()):
            tag = f"cyc{c['i']}"
            for cusip, bpv in ((c["cusip_old"], 1.0), (c["cusip_young"], -1.0)):
                q = self._FRBQ(cusip=cusip, value=self._V.NPV,
                               structure_kwargs={"bpv": bpv}, tags=(tag,))
                orders.append(QueryOrder(timestamp=now, query=q, meta={"action": "add_query"}))
        for c in self.exits.get(d, ()):
            tag = f"cyc{c['i']}"

            def pred(p, _t=tag):
                tags = set(p.meta.get("tags", []))
                tags.update(getattr(p.source_query, "tags", ()) or ())
                return _t in tags

            orders.append(UnwindOrder(timestamp=now, selector=pred,
                                      meta={"action": "unwind", "fee": 0.0}))
        return orders


def run_pass(panel, amap, tenor, ry, ro, parity):
    from BT.data_handler import TimeGrid
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import FlowSignalTriggerRequirements, Trigger
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    dates, cycles, skipped = build_schedule(panel, amap, tenor, ry, ro, parity)
    if not cycles:
        return None
    act = PassAction(cycles)
    fire = set(act.entries) | set(act.exits)
    trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda now, bt: now.date() in fire),
        actions=[act],
    )
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    strat = QueryStrategy(name=f"sw{tenor}-{ry}{ro}-{parity}", triggers=[trig], default_mdp=mdp)
    grid = [datetime.datetime.combine(pd.Timestamp(d).date(), datetime.time()) for d in dates]
    bt = QueryDrivenBacktest(time_grid=TimeGrid(grid), strategy=strat, mdp=mdp,
                             show_progress=False)
    bt.run()

    eq = pd.Series({pd.Timestamp(k): float(v) for k, v in bt.mtm_history.items()}).sort_index()
    holes = len(grid) - len(eq)
    eq = eq.reindex(pd.DatetimeIndex(dates)).ffill().fillna(0.0)
    d_eq = eq.diff().fillna(0.0)

    rows = []
    for c in cycles:
        seg = d_eq[(d_eq.index > c["entry"]) & (d_eq.index <= c["exit"])]
        rows.append(pd.DataFrame({
            "date": np.concatenate([[np.datetime64(c["entry"])], seg.index.values]),
            "pnl_bp": np.concatenate([[0.0], seg.values]),
            "cycle_i": c["i"],
        }))
    segs = pd.concat(rows, ignore_index=True)
    segs["tenor"], segs["pair"] = tenor, pair_label(ry, ro)
    meta = pd.DataFrame(cycles).rename(columns={"i": "cycle_i"})
    meta["tenor"], meta["pair"] = tenor, pair_label(ry, ro)
    meta["rank_young"], meta["rank_old"] = ry, ro
    return {"segs": segs, "meta": meta, "holes": holes, "skipped": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenors", default="")
    ap.add_argument("--pairs", default="", help="e.g. '0-1,0-2' as young-old")
    a = ap.parse_args(argv)
    STORE.mkdir(parents=True, exist_ok=True)

    panel, amap = load_prepared()
    panel = select_financing(panel, "modelled")

    tenors = tuple(int(x) for x in a.tenors.split(",")) if a.tenors else TENORS
    pairs = (tuple(tuple(int(v) for v in x.split("-")) for x in a.pairs.split(","))
             if a.pairs else PAIRS)

    t_all = time.time()
    for tenor, (ry, ro) in itertools.product(tenors, pairs):
        lab = pair_label(ry, ro)
        seg_path = STORE / f"segs_{tenor}_{lab}.parquet"
        if seg_path.exists():
            print(f"{tenor}Y {lab}: cached", flush=True)
            continue
        t0 = time.time()
        parts, metas, holes, skipped = [], [], 0, 0
        for parity in (0, 1):
            r = run_pass(panel, amap, tenor, ry, ro, parity)
            if r is None:
                continue
            parts.append(r["segs"])
            metas.append(r["meta"])
            holes += r["holes"]
            skipped += r["skipped"]
        if not parts:
            print(f"{tenor}Y {lab}: NO CYCLES", flush=True)
            continue
        segs = pd.concat(parts, ignore_index=True).sort_values(["cycle_i", "date"])
        meta = pd.concat(metas, ignore_index=True).sort_values("cycle_i")
        segs.to_parquet(seg_path, index=False)
        meta.to_parquet(STORE / f"meta_{tenor}_{lab}.parquet", index=False)
        print(f"{tenor}Y {lab}: {meta.shape[0]:3d} cycles  {len(segs):6d} day-rows  "
              f"holes {holes}  skipped {skipped}  ({time.time() - t0:.0f}s)", flush=True)
    print(f"\nall passes done in {(time.time() - t_all) / 60:.1f} min -> {STORE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
