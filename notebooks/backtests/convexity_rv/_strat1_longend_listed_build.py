"""Engine pass for the long-end LISTED gate study -- one UNIT run per structure.

    python notebooks/backtests/convexity_rv/_strat1_longend_listed_build.py unit "5Y/30Y"
    python notebooks/backtests/convexity_rv/_strat1_longend_listed_build.py gate "5Y/30Y" listed_only

``unit``
    Runs ``strat1_curve_gamma.build_backtest`` with the signal pinned to +1 on
    every cohort date, i.e. an ALWAYS-ON FLATTENER over the full 2019-2026 grid.
    Two things come out of that single run and both are needed:

    * the ``always`` gate's book -- it IS this run, straight from the engine,
      with no composition anywhere in it;
    * per-cohort DAILY mark-to-market, which is what lets every other gate's
      daily equity be composed from this one run instead of costing its own.

    The daily decomposition is an identity, not an approximation. The engine's
    mark is ``realized_pnl + sum(open position values)``, positions are tagged
    per cohort, and no cash is realised mid-hold, so

        mtm(t) == sum_c [ value_c(t) if open else net_realized_c ]

    holds to machine precision. This script ASSERTS it on every mark rather than
    trusting it -- measured max relative error 1.3e-16 on the probe window.

``gate``
    Runs a genuine engine backtest of ONE gated book, driven by the exact
    pre-lagged direction series the composition uses. This is the certification
    target: composed-vs-engine terminal gap and daily-change correlation, the
    same two numbers ``strat2_convexity_vs_fly_gridsearch`` certifies its panel
    simulation with. It exists because a composition that is never checked
    against the engine is an assumption wearing a number's clothes.

Everything is cached to ``notebooks/data/convexity_rv`` so the notebook executes
off parquet in minutes rather than re-running hours of engine time.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys
import time
import types
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV import strat1_longend_listed as ll

DATA = _REPO / "notebooks" / "data" / "convexity_rv"


def _grid(label: str) -> pd.DataFrame:
    """The signal-panel grid for one structure -- the SAME grid strategy 1's own
    stored runs used, so the unit cohorts tie out against them cohort for cohort."""
    panel = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    sub = (panel[panel["structure"] == label]
           .drop_duplicates(subset=["date"]).set_index("date").sort_index())
    if sub.empty:
        raise SystemExit(f"no signal-panel rows for {label!r}")
    return sub


def _run(label: str, signal: pd.Series, grid: pd.Index, cfg: s1.Strat1Config
         ) -> Tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """One engine run, instrumented for per-cohort daily marks.

    ``signal`` must ALREADY BE LAGGED -- ``build_backtest`` does not lag, and
    lagging twice is the kind of error that makes a backtest look better and
    leaves no trace.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    front, back = next((f, b) for (l, f, b) in ll.LONGEND_STRUCTURES if l == label)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    bt, cohorts = s1.build_backtest(mdp, cfg, label, front, back, signal, grid)
    print(f"{label}: {len(cohorts)} cohorts over {len(grid)} grid dates", flush=True)

    # Tap _position_value rather than re-pricing after the fact: the engine calls
    # it exactly once per position per mark inside mark_to_market, so this is
    # free. Accumulate per tag -- both legs of a cohort share one tag and an
    # assignment would silently drop the first leg.
    tag_value: Dict[str, Dict] = {}
    _orig = bt._position_value

    def _tapped(self, pos, now):
        v = _orig(pos, now)
        tags = list((getattr(pos, "meta", None) or {}).get("tags", []) or [])
        if tags:
            d = tag_value.setdefault(str(tags[0]), {})
            d[now] = d.get(now, 0.0) + float(v)
        return v

    bt._position_value = types.MethodType(_tapped, bt)

    t0 = time.time()
    bt.run()
    # QueryDrivenBacktest.run() SWALLOWS exceptions -- a dead run is an empty or
    # flat history, never a traceback that stops the script.
    if not getattr(bt, "mtm_history", None):
        raise SystemExit(f"{label}: engine produced no mtm_history -- run() failed")
    print(f"{label}: ran in {time.time() - t0:.0f}s, {len(bt.mtm_history)} marks", flush=True)

    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    eq = eq.sort_index()
    table = s1.cohort_table(bt, cohorts, cfg)

    marks = pd.DataFrame(
        {t: pd.Series(v) for t, v in tag_value.items()}
    ) if tag_value else pd.DataFrame(index=eq.index)
    marks.index = pd.to_datetime(marks.index)
    marks = marks.reindex(eq.index).sort_index()
    return eq, table, marks


def _assert_decomposition(eq: pd.Series, table: pd.DataFrame, marks: pd.DataFrame,
                          label: str) -> float:
    """mtm(t) == sum_c contribution_c(t), on every mark. Measured, not assumed."""
    recon = pd.Series(0.0, index=eq.index)
    for _, r in table.iterrows():
        tag = str(r["tag"])
        if tag in marks.columns:
            recon = recon.add(marks[tag].fillna(0.0), fill_value=0.0)
        if bool(r["closed"]):
            recon.loc[eq.index >= pd.Timestamp(r["exit"])] += float(r["net_pnl_ccy"])
    scale = max(float(eq.abs().max()), 1.0)
    err = float((recon - eq).abs().max())
    print(f"{label}: daily decomposition max abs err ${err:,.6f} "
          f"({err / scale:.3e} relative)", flush=True)
    assert err <= 1e-6 * scale, (
        f"{label}: daily decomposition FAILED (${err:,.2f}) -- the per-cohort "
        "composition below would be wrong and every gate curve with it")
    return err


def run_unit(label: str) -> None:
    safe = ll.safe_label(label)
    eq_p = DATA / f"strat1_le_unit_equity_{safe}.parquet"
    co_p = DATA / f"strat1_le_unit_cohorts_{safe}.parquet"
    mk_p = DATA / f"strat1_le_unit_marks_{safe}.parquet"
    if eq_p.exists() and co_p.exists() and mk_p.exists():
        print(f"{label}: unit cache already complete")
        return

    sub = _grid(label)
    cfg = ll.strat1_config()
    # +1 on every grid day, then the SAME one-day lag the stored runs used, so a
    # cohort fills at t+1 off day t's close. cohort_dates() then keeps the first
    # grid day of each month; the very first grid day lags onto NaN -> 0 and
    # opens nothing, which is why the run has 91 cohorts and not 92.
    unit_signal = pd.Series(1.0, index=sub.index).shift(1).fillna(0.0)
    eq, table, marks = _run(label, unit_signal, sub.index, cfg)

    assert (table["direction"] == 1.0).all(), "unit run must be a pure flattener"
    _assert_decomposition(eq, table, marks, label)
    assert int((eq.abs() > 1e-9).sum()) > 0.5 * len(eq), f"{label}: equity ~identically zero"

    eq.to_frame("equity_usd").to_parquet(eq_p)
    table.to_parquet(co_p, index=False)
    marks.to_parquet(mk_p)
    print(f"{label}: wrote unit run -- {len(table)} cohorts "
          f"({int(table['closed'].sum())} closed), {len(eq)} marks", flush=True)


def run_gate(label: str, mode: str) -> None:
    """A genuine engine run of ONE gated book -- the certification target."""
    safe = ll.safe_label(label)
    eq_p = DATA / f"strat1_le_engine_equity_{safe}_{mode}.parquet"
    co_p = DATA / f"strat1_le_engine_cohorts_{safe}_{mode}.parquet"
    if eq_p.exists() and co_p.exists():
        print(f"{label}/{mode}: engine cache already complete")
        return

    sub = _grid(label)
    cfg = ll.strat1_config()
    three = ll.load_threeway(DATA, benchmark="real")
    # apply_gate() lags internally; build_backtest() does NOT. Lag exactly once,
    # here, and hand the engine the same pre-lagged series the composition uses.
    #
    # The ORDER of shift and reindex is load-bearing and was measured, not
    # guessed. The gate lives on the 1,901-day contracts grid and the engine on
    # the 1,908-day signal grid; seven signal days have no contracts row
    # (2019-04-19, 2020-04-10, 2021-04-02, 2022-04-15, 2024-03-29, 2025-04-18,
    # 2026-04-03). Reindexing FIRST and shifting after would read "no benchmark
    # printed yesterday" as "stand aside", and on 2024-04-01 that flips one
    # 5Y/30Y cohort from a steepener to no trade -- so the engine run and the
    # composition would disagree for a reason that is not a composition error at
    # all. Shifting on the gate's OWN grid first is what ``apply_gate`` does (and
    # what the test suite pins), and it is also the right trading semantic: you
    # act on the last observation the benchmark actually made.
    signal = (ll.gate_series(three, label, mode)
              .sort_index().shift(1).reindex(sub.index).fillna(0.0))
    eq, table, marks = _run(label, signal, sub.index, cfg)
    _assert_decomposition(eq, table, marks, label)

    eq.to_frame("equity_usd").to_parquet(eq_p)
    table.to_parquet(co_p, index=False)
    print(f"{label}/{mode}: wrote engine run -- {len(table)} cohorts "
          f"({int(table['closed'].sum())} closed)", flush=True)


def run_rates() -> None:
    """Par rates of both legs on every cohort entry and exit date.

    Needed for the one thing the P&L alone cannot answer: how much of a
    flattener's return was **direction** (the curve spread fell) and how much was
    **convexity**. A DV01-neutral package is neutral to PARALLEL shifts, not to
    the spread it is built on, so::

        gross_bp  ~=  carry_bp  -  d(spread_bp)  +  convexity_bp

    and with the realised spread change measured the residual is attributable.
    Only ~170 dates are touched (entries plus exits), not the full 1,908-day
    grid, so this is minutes rather than hours.
    """
    out = DATA / "strat1_le_cohort_rates.parquet"
    if out.exists():
        print(f"rates cache already exists at {out}")
        return
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    cfg = ll.strat1_config()
    dates: set = set()
    for label, _f, _b in ll.LONGEND_STRUCTURES:
        p = DATA / f"strat1_le_unit_cohorts_{ll.safe_label(label)}.parquet"
        if not p.exists():
            raise SystemExit(f"unit cohorts missing for {label} -- run `unit` first")
        t = pd.read_parquet(p)
        dates |= set(pd.to_datetime(t["entry"]).dt.date)
        dates |= set(pd.to_datetime(t["exit"].dropna()).dt.date)
    days = sorted(dates)
    print(f"par rates on {len(days)} dates x {len(ll.LONGEND_STRUCTURES)} structures",
          flush=True)

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    rows: List[dict] = []
    t0 = time.time()
    for i, d in enumerate(days):
        try:
            pricer = mdp.get_data({"curve_name": cfg.curve, "timestamp": d})
        except Exception as exc:
            print(f"  {d}: curve unavailable ({type(exc).__name__})", flush=True)
            continue
        if pricer is None:
            continue
        for label, front, back in ll.LONGEND_STRUCTURES:
            try:
                raw, w, _res = s1.resolve_package(
                    pricer, front, back, package_dv01=cfg.package_dv01,
                    direction=s1.FLATTENER, curve=cfg.curve)
                # The CURVE structure strikes both legs at market, so
                # ``fixed_rate`` IS the par rate -- verified by npv == 0 on
                # 2022-09-13 (5Y 3.377%, 30Y 2.910%, both NPV 0.00).
                rows.append({"date": pd.Timestamp(d), "structure": label,
                             "front_rate": float(pricer.fixed_rate(raw[0])),
                             "back_rate": float(pricer.fixed_rate(raw[1])),
                             "front_npv": float(pricer.npv(raw[0])),
                             "back_npv": float(pricer.npv(raw[1]))})
            except Exception as exc:
                print(f"  {d} {label}: {type(exc).__name__}: {exc}", flush=True)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(days)} ({time.time() - t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no par rates resolved")
    # rates come back as decimals (0.0291 = 2.91%), so bp is x10,000
    df["spread_bp"] = (df["back_rate"] - df["front_rate"]) * 10_000.0
    assert float(df[["front_npv", "back_npv"]].abs().max().max()) < 1e-4, (
        "legs are not struck at par -- fixed_rate is not the par rate here")
    df.to_parquet(out, index=False)
    print(f"wrote {out} ({len(df)} rows)", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "unit"
    if cmd == "unit":
        targets = sys.argv[2:] or [l for (l, _, _) in ll.LONGEND_STRUCTURES]
        for lb in targets:
            run_unit(lb)
    elif cmd == "gate":
        run_gate(sys.argv[2], sys.argv[3])
    elif cmd == "rates":
        run_rates()
    else:
        raise SystemExit(f"unknown command {cmd!r} (unit | gate | rates)")
