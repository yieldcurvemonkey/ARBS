"""The wide grid: every fund x every signal x every horizon, scored and deflated.

    python -m RVUtils.ETFRebalance._run_grid --funds TLT,TLH,IEF,IEI,GOVT --workers 10

Why the parallelism is over FUNDS and not over configurations
--------------------------------------------------------------
``prepare_universe`` is the expensive half -- gating, benchmark weights and a robust
curve fit per date -- and it is identical for every configuration sharing a fund, a
window, a price basis and a curve spec. Sharding by configuration would rebuild it in
every worker; sharding by fund builds it once per worker and then runs a few hundred
configurations against it in memory.

Trials are counted honestly
---------------------------
The league's ``n_trials`` is every configuration this file evaluated **plus** whatever is
passed in ``--extra-trials`` for the searches that happened elsewhere -- the IC surface,
the partial-IC surface, the conditioning cuts. A deflated Sharpe that counts only its own
grid is a deflated Sharpe that has been told the wrong number.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")))

# ------------------------------------------------------------------ the space

#: Single signals and blends. Both signs of every unsigned channel, because "follow the
#: flow" and "fade the flow" are different economic claims and neither is privileged.
SIGNALS: list[dict] = [
    {"active_w": 1.0}, {"active_w": -1.0},
    {"active_rel": 1.0}, {"active_rel": -1.0},
    {"active_chg": 1.0}, {"active_chg": -1.0},
    {"bucket_active": 1.0}, {"bucket_active": -1.0},
    {"bucket_hist_z": 1.0}, {"bucket_hist_z": -1.0},
    {"flow": 1.0}, {"flow": -1.0},
    {"ownership": 1.0}, {"ownership": -1.0},
    {"ownership_chg": 1.0}, {"ownership_chg": -1.0},
    {"not_held": 1.0},
    # calendar-only: the NULL. If these earn what the others earn, the scrape bought
    # nothing, and the only way to know is to score them in the same league.
    {"deletion": 1.0}, {"deletion": -1.0},
    {"addition": 1.0}, {"addition": -1.0},
    # the control, and the blends that ask whether the ETF data adds to it
    {"resid": 1.0},
    {"resid": 1.0, "active_w": 1.0},
    {"resid": 1.0, "active_w": 0.5},
    {"resid": 1.0, "bucket_active": 1.0},
    {"resid": 1.0, "deletion": 1.0},
    {"active_w": 1.0, "ownership": -1.0},
    {"bucket_active": 1.0, "flow": -1.0},
]

HOLDS = [5, 10, 21, 42, 63]
MIN_ABS = [0.0, 1.5, 2.5]
N_POS = [2, 5]
WINDOWS = [None, "month_end"]
LAGS = [1]                      # 2 is added only for the surviving cells, see --lag2


def build_overlays(lags=LAGS) -> list[dict]:
    out = []
    for comp, hold, mz, npos, win, lag in itertools.product(
            SIGNALS, HOLDS, MIN_ABS, N_POS, WINDOWS, lags):
        name = ("+".join(f"{k}{'' if w == 1 else w}" for k, w in comp.items())
                + f"|h{hold}|z{mz}|n{npos}|{win or 'any'}|lag{lag}")
        out.append({
            "name": name,
            "signal": {"components": comp},
            "timing": {"hold_days": hold, "entry_every": max(1, hold // 2),
                       "entry_window": win, "exec_lag": lag},
            "structure": {"min_abs_score": mz, "n_positions": npos},
        })
    return out


# ------------------------------------------------------------------ one fund


def run_fund(fund: str, start: str, out_dir: str, lags: tuple) -> str:
    from RVUtils.ETFRebalance import bond_panel as BP
    from RVUtils.ETFRebalance import engine as EN
    from RVUtils.ETFRebalance import float_panel as FP
    from RVUtils.ETFRebalance import grid as GR
    from RVUtils.ETFRebalance import holdings_panel as HP

    t0 = time.time()
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([fund], panel=panel)
    base = {"fund": fund, "universe": {"start": start}}

    overlays = build_overlays(list(lags))
    # keep_results=False. Holding every Result -- each carrying its trade log, daily curve
    # and leg frame -- costs roughly 1MB per configuration, so 1,680 of them is ~1.7GB per
    # worker on top of the panel. Measured: the two smallest funds finished in 34 and 38
    # minutes while the three largest were still running three hours later, thrashing.
    # The DSR needs only each configuration's per-trade P&L series, which is a few
    # kilobytes, so that is all that is kept.
    tbl, _ = GR.run_grid(overlays, base=base, joined=joined, panel=panel,
                         progress=False, keep_results=False, keep_pnl=True)
    tbl.insert(0, "fund", fund)

    lg = GR.league(tbl, extra_trials=0, min_trades=30)
    if not lg.empty:
        lg = GR.attach_dsr_from_pnl(lg, sr_star=float(lg["sr_star"].iloc[0]))
        tbl = tbl.merge(lg[["name", "sr_star", "clears_hurdle", "dsr"]], on="name", how="left")

    p = os.path.join(out_dir, f"grid_{fund}.parquet")
    tbl.to_parquet(p, index=False)
    print(f"[{fund}] {len(tbl)} configs in {(time.time() - t0)/60:.1f}m -> {p}", flush=True)
    return p


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", default="TLT,TLH,IEF,IEI,GOVT")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--extra-trials", type=int, default=0,
                    help="configurations searched OUTSIDE this grid (IC surfaces, cuts)")
    ap.add_argument("--lag2", action="store_true", help="also sweep exec_lag = 2")
    a = ap.parse_args(argv)

    from RVUtils.ETFRebalance import bond_panel as BP
    from RVUtils.ETFRebalance import grid as GR

    out_dir = str(BP.panel_dir())
    funds = [f.strip().upper() for f in a.funds.split(",") if f.strip()]
    lags = tuple(LAGS + ([2] if a.lag2 else []))
    n_per = len(build_overlays(list(lags)))
    print(f"{len(funds)} funds x {n_per} configurations = {len(funds) * n_per:,} runs", flush=True)

    paths = []
    with ProcessPoolExecutor(max_workers=min(a.workers, len(funds))) as ex:
        futs = {ex.submit(run_fund, f, a.start, out_dir, lags): f for f in funds}
        for fut in as_completed(futs):
            try:
                paths.append(fut.result())
            except Exception as exc:
                print(f"[{futs[fut]}] FAILED {type(exc).__name__}: {exc}", flush=True)

    if not paths:
        print("nothing produced")
        return 1

    allg = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    combined = os.path.join(out_dir, "grid_all.parquet")
    allg.to_parquet(combined, index=False)

    # One league across every fund, because a winner picked from five funds' grids was
    # selected from all of them.
    lg = GR.league(allg, extra_trials=a.extra_trials, min_trades=30)
    print(f"\n{'=' * 100}")
    print(f"{len(allg):,} configurations run, "
          f"{int(lg['n_trials_counted'].iloc[0]) if not lg.empty else 0} trials counted "
          f"(+{a.extra_trials} searched elsewhere)")
    if lg.empty:
        print("no configuration reached 30 trades")
        return 0
    print(f"selection hurdle sr* = {lg['sr_star'].iloc[0]:.4f} per trade\n")

    cols = ["fund", "name", "trades", "gross_avg_bp", "cost_avg_bp", "avg_bp",
            "sr_per_trade", "t_stat", "breakeven_cost_mult", "dsr", "clears_hurdle"]
    cols = [c for c in cols if c in lg.columns]
    print("TOP 20 BY SHARPE PER TRADE (net of the measured spread):")
    print(lg.head(20)[cols].round(4).to_string(index=False))

    print("\nTOP 15 BY GROSS EDGE (before execution -- what the signal is worth at all):")
    print(allg.sort_values("gross_avg_bp", ascending=False).head(15)[
        [c for c in cols if c in allg.columns]].round(4).to_string(index=False))

    alive = GR.alive(lg, dsr_min=0.95, min_trades=50)
    print(f"\nALIVE (DSR > 0.95, >= 50 trades, positive net of measured cost): "
          f"{len(alive)} of {len(lg)}")
    if len(alive):
        print(alive[cols].round(4).to_string(index=False))

    # The comparison the whole project turns on.
    def _is(row, keys):
        return any(k in str(row) for k in keys)

    hold_mask = allg["name"].str.contains(
        "active_w|active_rel|active_chg|bucket_|flow|ownership|not_held", regex=True)
    cal_mask = allg["name"].str.contains("deletion|addition", regex=True)
    ctl_mask = allg["name"].str.contains("resid", regex=True)
    print("\nBEST GROSS bp PER TRADE, by what the signal is allowed to read:")
    for lbl, m in (("holdings-based", hold_mask & ~ctl_mask),
                   ("calendar-only (the NULL)", cal_mask & ~ctl_mask),
                   ("richness control (no ETF data)", ctl_mask)):
        sub = allg[m & (allg["trades"].fillna(0) >= 30)]
        if sub.empty:
            print(f"  {lbl:34s} -- none")
            continue
        b = sub.loc[sub["gross_avg_bp"].idxmax()]
        print(f"  {lbl:34s} {b['gross_avg_bp']:+.4f} bp  "
              f"(net {b['avg_bp']:+.4f}, {int(b['trades'])} trades)  {b['name']}")
    print(f"\nwrote {combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
