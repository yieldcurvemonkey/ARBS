"""Run the linear-vs-vol backtest grid -> league.parquet (+ winner logs).

Families:
  A  bucket convergence (hedged channel-1 engine, generalized signals)
  B  modal 25bp butterfly (long fly = short dispersion), fixed strikes
  C  off-lattice tail verticals (outermost boundary claims)
  E  decomposed ICS residual (10:6 futures package)
  P1/P2 placebos for the family-A winner class (Gaussian tree, wrong calendar)

Family D (cross-expiry conditional) is EXCLUDED by design: section F3
measured the one-Bernoulli deconvolution residual at a third of the mass —
running configs on a signal measured that weak is trial-count inflation.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd

from linvol_grid_common import (
    OUT, boundary_signal_frame, build_ladders, claim_series, fly_series,
    gaussian_tree_gaps, ics_cost_fn, ics_residual_series, league_row,
    load_panels, run_ics_backtest, run_package_backtest, select_boundaries,
    shifted_ladders,
)
from RVUtils.MeetingProb import split_meetings
from RVUtils.MeetingProb.backtest import run_channel1_backtest
from MDP.STIRFutures._sofr_option_contracts import sofr_option_last_trade_date

OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()
P = load_panels()
LADDERS, JUMPS = build_ladders(P["mon"])
SIG = boundary_signal_frame(P)
print(f"setup {time.time() - t0:.0f}s: sig rows {len(SIG)}", flush=True)


def cm_lookup_factory(ladders):
    def cm_lookup(d, sym):
        lad = ladders.get(d)
        return split_meetings(d, sym, lad) if lad else None
    return cm_lookup


def fwd_lookup(ts, sym):
    try:
        return float(P["fwd_idx"].loc[(pd.Timestamp(ts), sym)])
    except KeyError:
        return np.nan


# ---------------------------------------------------------------------------
# vertical mark cache for family A (fixed strikes per (sym, boundary))
# ---------------------------------------------------------------------------
_vm_cache = {}


def vert_marks_for(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in frame.drop_duplicates(["symbol", "boundary_rate"]).iterrows():
        key = (r["symbol"], float(r["boundary_rate"]))
        if key not in _vm_cache:
            s = claim_series(P["q_idx"], r["symbol"], r["right"],
                             float(r["k_lo"]), float(r["k_hi"]))
            if s is not None:
                # engine prices per PROBABILITY UNIT: claim_bp / width * 100
                s = s / float(r["width_bp"]) * 100.0
            _vm_cache[key] = s
        s = _vm_cache[key]
        if s is None:
            continue
        f = pd.DataFrame({"as_of": s.index, "unit_bp": s.to_numpy()})
        f["symbol"], f["boundary_rate"] = key
        rows.append(f)
    return (pd.concat(rows, ignore_index=True) if rows else
            pd.DataFrame(columns=["as_of", "symbol", "boundary_rate",
                                  "unit_bp"]))


def family_A(sig, ladders, tag="A", jumps=None) -> tuple:
    jumps = JUMPS if jumps is None else jumps
    cm_lookup = cm_lookup_factory(ladders)
    rows, best = [], {}
    classes = ("mode_flank", "outer", "largest")
    bands = ((0, 30), (30, 60), (0, 60), (0, 90))
    for bc in classes:
        for lo, hi in bands:
            for gated in (True, False):
                sel = select_boundaries(sig, boundary_class=bc, dte_lo=lo,
                                        dte_hi=hi, gated=gated)
                if not gated:
                    sel = sel.copy()
                    sel["gate"] = True
                    sel["channel"] = "channel1"
                vm = vert_marks_for(sel)
                for thr in (0.04, 0.06, 0.08, 0.10):
                    for dirn in ("fade", "momentum"):
                        trades = run_channel1_backtest(
                            sel, vm, jumps, cm_lookup, fwd_lookup,
                            entry_min_gap=thr, entry_min_t=0.0,
                            lag=1, direction=dirn)
                        cfg = dict(family=tag, boundary=bc, dte=f"{lo}-{hi}",
                                   gated=gated, thr=thr, direction=dirn)
                        rows.append(league_row(
                            trades, cfg,
                            cost_fn=lambda x, m: m * x.cost_bp))
                        best[len(rows) - 1] = trades
    return rows, best


def family_B() -> tuple:
    mon, bd = P["mon"], P["bd"]
    rows, best = [], {}
    # per (symbol, month): first monitored session -> modal bucket + deficit
    m = mon.copy()
    m["ym"] = m["as_of"].dt.to_period("M")
    firsts = m.sort_values("as_of").groupby(["symbol", "ym"]).head(1)
    ent_rows = []
    for _, r in firsts.iterrows():
        g = bd[(bd["as_of"] == r["as_of"]) & (bd["symbol"] == r["symbol"])]
        g = g.sort_values("boundary_rate")
        if len(g) < 3:
            continue
        pt, pl = g["p_tree"].to_numpy(), g["p_listed"].to_numpy()
        mass_t, mass_l = pt[:-1] - pt[1:], pl[:-1] - pl[1:]
        k = int(np.argmax(mass_t))
        center_rate = (g["boundary_rate"].to_numpy()[k]
                       + g["boundary_rate"].to_numpy()[k + 1]) / 2.0
        k_center = round((100.0 - center_rate) * 4) / 4.0   # 0.25 grid
        fwd = float(r["forward_rate"])
        right = "C" if k_center >= 100.0 - fwd else "P"
        ent_rows.append({
            "as_of": r["as_of"], "symbol": r["symbol"],
            "k_center": k_center, "right": right,
            "deficit": float(mass_t[k] - mass_l[k]),
            "dte": float(r["days_to_expiry"]),
        })
    entries = pd.DataFrame(ent_rows)
    print(f"family B entry candidates: {len(entries)}", flush=True)

    def mark_fn(row):
        return fly_series(P["q_idx"], row["symbol"], row["right"],
                          float(row["k_center"]))

    bands = ((30, 60), (60, 90), (90, 135), (135, 400))
    for lo, hi in bands:
        for thr in (0.0, 0.10, 0.20):
            sub = entries[(entries["dte"] >= lo) & (entries["dte"] < hi)
                          & (entries["deficit"] >= thr)]
            for hold, tagh in ((20, "20d"), (600, "expiry")):
                for dirn in ("long", "short"):
                    trades = run_package_backtest(
                        sub, mark_fn, P["all_dates"], direction=dirn,
                        lag=1, hold_sessions=hold, dte_floor=3,
                        expiry_lookup=sofr_option_last_trade_date)
                    cfg = dict(family="B", boundary="modal_fly",
                               dte=f"{lo}-{hi}", gated=False, thr=thr,
                               direction=("short_disp" if dirn == "long"
                                          else "long_disp"),
                               hold=tagh)
                    rows.append(league_row(trades, cfg))
                    best[len(rows) - 1] = trades
    return rows, best


def family_C() -> tuple:
    rows, best = [], {}
    outer = SIG[SIG["is_outer"]].copy()
    hi_b = outer.loc[outer.groupby(["as_of", "symbol"])["boundary_rate"]
                     .idxmax()]
    lo_b = outer.loc[outer.groupby(["as_of", "symbol"])["boundary_rate"]
                     .idxmin()]

    def mk(row):
        s = claim_series(P["q_idx"], row["symbol"], row["right"],
                         float(row["k_lo"]), float(row["k_hi"]))
        return (s, 2) if s is not None else None

    bands = ((0, 60), (60, 135), (135, 400))
    for side, frame in (("above", hi_b), ("below", lo_b)):
        for lo, hi in bands:
            for thr in (0.04, 0.06):
                sub = frame[(frame["days_to_expiry"] >= lo)
                            & (frame["days_to_expiry"] < hi)
                            & (frame["gap"].abs() >= thr)
                            & frame["gate"]]
                for sell in (True, False):
                    # above-tail claim rich => sell = short claim;
                    # below-tail rich shows as gap<0 on the claim => sell
                    # the tail = LONG the claim
                    dirn = ("short" if (sell and side == "above")
                            or (not sell and side == "below") else "long")
                    trades = run_package_backtest(
                        sub, mk, P["all_dates"], direction=dirn, lag=1,
                        hold_sessions=600, dte_floor=3,
                        expiry_lookup=sofr_option_last_trade_date)
                    cfg = dict(family="C", boundary=f"tail_{side}",
                               dte=f"{lo}-{hi}", gated=True, thr=thr,
                               direction="sell_tail" if sell else "buy_tail")
                    rows.append(league_row(trades, cfg))
                    best[len(rows) - 1] = trades
    return rows, best


def family_E() -> tuple:
    resid = ics_residual_series(P, LADDERS,
                                sorted(P["mon"]["symbol"].unique()))
    resid.to_parquet(OUT / "ics_residuals.parquet", index=False)
    print(f"family E residual rows: {len(resid)}", flush=True)
    rows, best = [], {}
    for thr in (2.0, 3.0):
        for turn in (True, False):
            for dirn in ("fade", "momentum"):
                trades = run_ics_backtest(
                    resid, P["all_dates"], threshold_bp=thr,
                    include_turn=turn, direction=dirn)
                cfg = dict(family="E", boundary="ics_resid", dte="n/a",
                           gated=True, thr=thr, direction=dirn,
                           turn_included=turn)
                rows.append(league_row(trades, cfg, cost_fn=ics_cost_fn))
                best[len(rows) - 1] = trades
    return rows, best


def dump(rows, trades_map, name):
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / f"league_{name}.parquet", index=False)
    # persist the single best row's trade log for the autopsy
    live = df[df["n_trades"] > 0]
    if not live.empty:
        i = int(live["net_1x_bp"].idxmax())
        tl = trades_map.get(i, [])
        recs = []
        for x in tl:
            recs.append({
                "symbol": x.symbol, "entry": x.entry, "exit": x.exit,
                "gross_bp": x.gross_bp,
                "net_1x_bp": (x.gross_bp - x.cost_bp(1.0)
                              if callable(getattr(x, "cost_bp", None))
                              else x.net_bp),
                "exit_reason": getattr(x, "exit_reason", ""),
            })
        pd.DataFrame(recs).to_parquet(OUT / f"trades_{name}_best.parquet",
                                      index=False)
    print(f"[{name}] {len(df)} rows, "
          f"best net1x {df['net_1x_bp'].max():+.1f}bp "
          f"({time.time() - t0:.0f}s)", flush=True)
    return df


rows_a, best_a = family_A(SIG, LADDERS)
la = dump(rows_a, best_a, "A")
rows_b, best_b = family_B()
lb = dump(rows_b, best_b, "B")
rows_c, best_c = family_C()
lc = dump(rows_c, best_c, "C")
rows_e, best_e = family_E()
le = dump(rows_e, best_e, "E")

# placebos on family A (the hedged convergence family)
sig_p1 = gaussian_tree_gaps(SIG, P["mon"])
rows_p1, _ = family_A(sig_p1, LADDERS, tag="P1_gauss")
lp1 = dump(rows_p1, {}, "P1")
lad_p2 = shifted_ladders(LADDERS)
jumps_p2 = pd.DataFrame(
    [{"as_of": pd.Timestamp(d), "effective": m.effective, "jump_bp": m.jump_bp}
     for d, lad in lad_p2.items() for m in lad])
rows_p2, _ = family_A(SIG, lad_p2, tag="P2_calendar", jumps=jumps_p2)
lp2 = dump(rows_p2, {}, "P2")

league = pd.concat([la, lb, lc, le, lp1, lp2], ignore_index=True)
league.to_parquet(OUT / "league.parquet", index=False)
print(f"LEAGUE: {len(league)} rows "
      f"({(league['family'].isin(['A','B','C','E'])).sum()} real, "
      f"{len(lp1) + len(lp2)} placebo) in {time.time() - t0:.0f}s", flush=True)
