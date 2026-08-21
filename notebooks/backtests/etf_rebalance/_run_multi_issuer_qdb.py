"""Mark the AGGREGATE book through QueryDrivenBacktest, as a check on the fast engine.

Why a subset rather than the whole book
----------------------------------------
The QDB reprices every leg through ``FixedRateBondsMDP`` on every marking day, which is
minutes per hundred packages against milliseconds for the vectorised engine. The question
it answers is not "what did the strategy earn" -- the fast engine answers that, and this
book is dead by a margin no marking model changes -- it is "does the fast engine's
``-dR`` plus yield-space carry agree with a dirty-NPV repricing that books coupon cash".
That is a property of the marking, so a representative slice settles it.

Two things this script does that are not optional
--------------------------------------------------
**Both sides on the same price basis.** The QDB prices through the MDP, which solves its
yields off FedInvest's ``eod_price``; the panel prices off the mid of the two-sided quote.
Those are a genuine basis, not noise, and a butterfly cancels the level and leaves exactly
that basis -- on the March 2023 SVB week it showed up as a 13x daily disagreement. So the
fast engine is run with ``price_basis="eod"`` for the comparison, and the comparison is
then about the two marking models rather than about the two price sources.

**Three signed outright legs, never a FLY structure.** ``FixedRateBondStructure._build_fly``
re-signs the package from ``sign(bpv)``, which put 15 of 35 flies backwards on a prior
book. ``BT/signals/etf_rebalance.py`` already books outrights; this script must not undo
that, and it reads ``mtm_history`` rather than the closed log because the closed log's
``realized_pnl`` is the price leg only and hides coupon cash.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import pandas as pd  # noqa: E402

from BT.signals import etf_rebalance as QDB  # noqa: E402
from RVUtils.ETFRebalance import aggregate as AG  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402

pd.set_option("display.width", 220)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-trades", type=int, default=20)
    ap.add_argument("--column", default=None,
                    help="aggregate column to trade; default = the grid's best by gross")
    ap.add_argument("--sign", type=float, default=None)
    ap.add_argument("--hold", type=int, default=21)
    ap.add_argument("--prefix", default="mi")
    a = ap.parse_args()
    t0 = time.time()

    grid_path = os.path.join(DATA_DIR, f"{a.prefix}_grid.csv")
    column, sign = a.column, a.sign
    if column is None and os.path.exists(grid_path):
        g = pd.read_csv(grid_path)
        g = g[g["kind"] == "aggregate"].sort_values("gross_avg_bp", ascending=False)
        best = json.loads(g.iloc[0]["config"])
        column = best["signal"]["kwargs"]["precomputed"]["column"]
        sign = best["signal"]["kwargs"]["precomputed"]["sign"]
        a.hold = int(best["timing"]["hold_days"])
        print(f"headline config from the grid: {g.iloc[0]['name']}")
    if column is None:
        column = AG.column_name("own", "coupon_long", 0.25)
        sign = -1.0
    print(f"column={column} sign={sign:+.0f} hold={a.hold}")

    panel = FP.asof_join(BP.load(), FP.load())
    cfg0 = EN.merge_config({"fund": "TLT",
                            "universe": {"start": "2016-01-01",
                                         "ttm_min": AG.COMMON_BAND[0],
                                         "ttm_max": AG.COMMON_BAND[1]},
                            "price_basis": "eod"})
    uni, funnel = EN.prepare_universe(cfg0, panel=panel)
    uni = uni[uni["date"] >= pd.Timestamp("2016-01-01")].reset_index(drop=True)

    fs = column.split("__")[1]
    width = 0.25 if "w025" in column else (0.5 if "w05" in column else 1.0)
    built = AG.build_ladders(uni, fund_sets=(fs,), widths=(width,),
                             combines=("book", "equal"), align_starts=False, verbose=False)
    start = built["ladder_start"]
    uni2 = AG.attach_many(uni, built["specs"])
    uni2 = uni2[uni2["date"] >= start].reset_index(drop=True)
    if column not in uni2.columns:
        raise KeyError(f"{column} not built; available: {sorted(built['specs'])}")

    cfg = {
        "name": "qdb_tieout", "fund": "TLT", "price_basis": "eod",
        "universe": {"start": str(start.date()), "ttm_min": AG.COMMON_BAND[0],
                     "ttm_max": AG.COMMON_BAND[1]},
        "signal": {"components": {"precomputed": 1.0}, "z_mode": "raw",
                   "kwargs": {"precomputed": {"column": column, "sign": float(sign)}}},
        "timing": {"hold_days": int(a.hold), "exec_lag": 1, "entry_every": 21},
        "structure": {"n_positions": 3, "both_sides": True, "min_abs_score": 0.0},
    }
    res = EN.run_config(cfg, universe=uni2, prepared_funnel=funnel, keep_segments=True)
    print(f"fast engine: {len(res.closed)} trades  [{time.time()-t0:.0f}s]")

    sub = res.closed.sort_values("opened_at").head(a.n_trades)
    legs = res.legs[res.legs.trade_id.isin(sub.trade_id)]
    dates = res.daily.loc[(res.daily["date"] >= sub["opened_at"].min())
                          & (res.daily["date"] <= sub["closed_at"].max()), "date"]
    print(f"QDB slice: {len(sub)} packages, {len(legs)} legs, {len(dates)} marking days")

    #: charge_fee=False on BOTH sides -- the fast segment curve is gross, so the QDB must
    #: be too, or the comparison is between a gross curve and a net one.
    out = QDB.run_qdb(sub, legs, dates=dates, charge_fee=False, show_progress=True,
                      name="mi_tieout")
    fast = QDB.fast_daily_for(res.segments, sub["trade_id"], dates)
    j = QDB.tie_out(fast, out["daily"])
    rep = QDB.tie_out_report(j)
    print("\n" + pd.Series(rep).to_frame("fast vs QDB").round(4).to_string())

    checks = [
        ("levels agree to under 1bp", abs(rep["end_gap_bp"]) < 1.0,
         f"{rep['end_gap_bp']:+.4f} bp"),
        ("daily changes positively related", (rep["daily_change_corr"] or 0) > 0.3,
         f"corr {rep['daily_change_corr']:.4f} (the PATH is not expected to match: the "
         f"QDB books coupon cash, the fast engine one carry term)"),
        ("no marking holes", out["holes"] == 0, str(out["holes"])),
        ("QDB booked the packages", len(out["closed_log"]) > 0,
         f"{len(out['closed_log'])} closed legs"),
        ("QDB P&L is not identically zero", abs(float(out["equity"].iloc[-1])) > 1e-9,
         f"{float(out['equity'].iloc[-1]):+.4f} bp"),
    ]
    print()
    for nm, good, v in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {nm:34s} {v}")

    pd.DataFrame([{**rep, "column": column, "sign": sign, "hold": a.hold,
                   "n_packages": len(sub),
                   **{f"check_{i}": bool(g) for i, (_, g, _) in enumerate(checks)}}]).to_csv(
        os.path.join(DATA_DIR, f"{a.prefix}_qdb_tieout.csv"), index=False)
    j.reset_index().to_csv(os.path.join(DATA_DIR, f"{a.prefix}_qdb_curves.csv"), index=False)
    print(f"\nwrote {a.prefix}_qdb_tieout.csv / {a.prefix}_qdb_curves.csv  "
          f"[{(time.time()-t0)/60:.1f} min]")
    return 0 if all(g for _, g, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
