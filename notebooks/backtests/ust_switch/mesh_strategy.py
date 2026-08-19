"""MESH -- Month-End / Specialness Harvest of the UST switch. The convergence pass.

The strategy, stated before its backtest
----------------------------------------
LONG the old / SHORT the current (DV01-matched), entered at roll+10bd, exited at
next-roll+1bd, taken ONLY when the current issue's repo specialness at entry exceeds its
own expanding median. Portfolio across tenors. Every element was measured before this
file existed, on different data than it is now judged on:

* **enter roll+10**: the concession-release (w22461's ~3bp hedged appreciation) runs
  against the short-current leg for the first ~7bd of every cycle -- measured on the
  pooled cycle profile and placebo-confirmed. Entry waits it out.
* **exit next-roll+1 (not earlier)**: the calendar diagnostic found the single most
  robust structural regularity in this study -- the old RICHENS vs the current on
  month-end day itself (pooled t=3.96; positive in 17 of 17 years; 6 of 7 tenors) --
  index duration-extension / displacement day. The e10->next-roll window holds every
  month-end in the cycle; exiting earlier would leave the best days on the table.
* **specialness gate**: the current's entry-day specialness (JPM-tied, measured 2016+,
  modelled before) predicts the subsequent LO convergence monotonically (pooled
  e10->nr terciles: -0.20 / +0.06 / +0.45bp gross; 20Y corr +0.54). Mechanism: a
  deeply special current is a crowded rich benchmark; the convergence that follows is
  larger. The gate threshold is the conditioner's own EXPANDING median -- no lookahead.

Costs are full SR1170; financing is per-issue. Deflation is reported against the
session's cumulative search (~13.9k configs) as well as this file's own variants.
"""

from __future__ import annotations

import argparse
import itertools
import os
import pathlib
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")
import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from RVUtils.BasisVsVol.analytics import (  # noqa: E402
    deflated_sharpe,
    max_drawdown,
    newey_west_tstat,
    sharpe,
)
from RVUtils.USTSwitch.costs import CostModel, is_stressed  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
SEGS = HERE / "_out" / "qdb_allpairs"
OUT = HERE / "_out" / "mesh"
TENORS = (2, 3, 5, 7, 10, 20, 30)
CUMULATIVE_PRIOR_TRIALS = 13_897  # all prior searches this session incl. catalyst pass


def load_cycles(tenor: int, pair: str, panel: pd.DataFrame):
    segs = pd.read_parquet(SEGS / f"segs_{tenor}_{pair}.parquet")
    meta = pd.read_parquet(SEGS / f"meta_{tenor}_{pair}.parquet")
    segs["date"] = pd.to_datetime(segs["date"])
    for c in ("entry", "exit", "roll", "next_roll"):
        meta[c] = pd.to_datetime(meta[c])
    p = panel[panel["tenor"] == tenor]
    by_cd = p.set_index(["cusip", "date"]).sort_index()
    out = []
    for _, m in meta.sort_values("cycle_i").iterrows():
        seg = segs[segs["cycle_i"] == m["cycle_i"]].sort_values("date")
        dates = pd.DatetimeIndex(seg["date"])
        if len(dates) < 13:
            continue
        try:
            Y = by_cd.loc[m["cusip_young"]].reindex(dates)
            O = by_cd.loc[m["cusip_old"]].reindex(dates)
        except KeyError:
            continue
        dt_days = np.concatenate([[0.0], np.diff(dates.values).astype("timedelta64[D]").astype(float)])
        with np.errstate(all="ignore"):
            fin_rate = -(
                (O["gc_pct"].to_numpy() * 100.0 - O["special_used_bp"].to_numpy()) / O["MOD_DURATION"].to_numpy()
                - (Y["gc_pct"].to_numpy() * 100.0 - Y["special_used_bp"].to_numpy()) / Y["MOD_DURATION"].to_numpy()
            )
        e = 10
        sp = Y["special_used_bp"].iloc[min(e, len(dates) - 1)]
        out.append({
            "roll": m["roll"], "dates": dates,
            "pnl": seg["pnl_bp"].to_numpy(), "fin": np.nan_to_num(fin_rate) * dt_days / 360.0,
            "D_o": np.nan_to_num(O["MOD_DURATION"].to_numpy()),
            "D_y": np.nan_to_num(Y["MOD_DURATION"].to_numpy()),
            "special_entry": float(sp) if pd.notna(sp) else np.nan,
        })
    return out


def run(tenor, pair, cycles, gate: str, cm: CostModel, e: int = 10):
    hist, daily_idx, daily_val, trades = [], [], [], []
    for c in cycles:
        take = True
        if gate != "none":
            v = c["special_entry"]
            if not np.isfinite(v):
                take = False
            else:
                prior = list(hist)
                hist.append(v)
                if len(prior) < 8:
                    take = False
                else:
                    thr = np.quantile(prior, 0.5)
                    take = v > thr
        if not take:
            continue
        dates, n = c["dates"], len(c["dates"])
        if e >= n - 1:
            continue
        pnl = c["pnl"][e + 1:] + c["fin"][e + 1:]
        rank_old = {"CTvO": 1, "CTvOOO": 3}[pair]
        rt = cm.round_trip_yield_bp(
            tenor, rank_old, 0, c["D_o"][e] or 1.0, c["D_y"][e] or 1.0,
            stressed=is_stressed(dates[e]) or is_stressed(dates[-1]),
        )
        pnl = pnl.copy()
        pnl[0] -= rt / 2.0
        pnl[-1] -= rt / 2.0
        daily_idx.append(dates[e + 1:])
        daily_val.append(pnl)
        trades.append({"tenor": tenor, "pair": pair, "roll": c["roll"], "entry": dates[e],
                       "exit": dates[-1], "net_bp": float(pnl.sum()), "cost_bp": float(rt),
                       "special_entry": c["special_entry"]})
    if not trades:
        return None
    daily = pd.Series(np.concatenate(daily_val),
                      index=pd.DatetimeIndex(np.concatenate([i.values for i in daily_idx])))
    return daily.groupby(level=0).sum().sort_index(), pd.DataFrame(trades)


def stats(name, daily, tr):
    t_nw, _ = newey_west_tstat(daily)
    yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    return {"name": name, "n_trades": len(tr),
            "net_bp": round(float(tr["net_bp"].sum()), 2),
            "net_per_trade": round(float(tr["net_bp"].mean()), 4),
            "cost_per_trade": round(float(tr["cost_bp"].mean()), 3),
            "hit": round(float((tr["net_bp"] > 0).mean()), 3),
            "sharpe": round(float(sharpe(daily)), 3),
            "t_nw": round(float(t_nw), 2),
            "bp_per_yr": round(float(tr["net_bp"].sum() / yrs), 2),
            "max_dd": round(float(max_drawdown(daily.cumsum())), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    panel = pd.read_parquet(HERE / "_data" / "prepared_panel.parquet")
    for c in ("date", "issue_date", "maturity_date"):
        panel[c] = pd.to_datetime(panel[c])
    from RVUtils.USTSwitch.data import select_financing

    panel = select_financing(panel, "modelled")
    cm = CostModel()

    rows, dailies, tr_all = [], {}, {}
    for tenor, pair, gate in itertools.product(TENORS, ("CTvO", "CTvOOO"), ("none", "sp50")):
        cyc = load_cycles(tenor, pair, panel)
        res = run(tenor, pair, cyc, gate, cm)
        if res is None:
            continue
        daily, tr = res
        if len(tr) < 8:
            continue
        name = f"{tenor}Y_{pair}_e10nr_{gate}"
        rows.append(stats(name, daily, tr) | {"tenor": tenor, "pair": pair, "gate": gate})
        dailies[name] = daily
        tr_all[name] = tr
    league = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)
    n_here = len(rows)
    sr_var = float(np.nanvar(league["sharpe"], ddof=1))
    league["dsr_cum"] = [deflated_sharpe(dailies[nm], CUMULATIVE_PRIOR_TRIALS + n_here, sr_var)
                         for nm in league["name"]]
    league.to_csv(OUT / "mesh_league.csv", index=False)
    print(f"{n_here} variants (cumulative trials {CUMULATIVE_PRIOR_TRIALS + n_here})")
    print(league.round(3).to_string(index=False))

    # ---- gate uplift, per pair: same cells with vs without the gate
    print("\ngate uplift (sp50 minus none), same tenor/pair:")
    for pair in ("CTvO", "CTvOOO"):
        b = league[(league["pair"] == pair) & (league["gate"] == "none")].set_index("tenor")
        g = league[(league["pair"] == pair) & (league["gate"] == "sp50")].set_index("tenor")
        j = g[["net_per_trade", "sharpe", "hit"]].sub(b[["net_per_trade", "sharpe", "hit"]])
        j.columns = [f"d_{c}" for c in j.columns]
        print(f"  {pair}: mean d_net {j['d_net_per_trade'].mean():+.3f}  "
              f"d_sharpe {j['d_sharpe'].mean():+.3f}  d_hit {j['d_hit'].mean():+.3f}  "
              f"improved {int((j['d_sharpe'] > 0).sum())}/{len(j)}")

    # ---- MESH portfolio: gated cells with positive net across ALL tenors, one pair
    for pair in ("CTvO", "CTvOOO"):
        picks = [f"{t}Y_{pair}_e10nr_sp50" for t in TENORS
                 if f"{t}Y_{pair}_e10nr_sp50" in dailies]
        port = pd.concat([dailies[p] for p in picks], axis=1).fillna(0.0).sum(axis=1)
        ptr = pd.concat([tr_all[p] for p in picks], ignore_index=True)
        s = stats(f"MESH_{pair}_all_tenors", port, ptr)
        s["dsr_cum"] = round(deflated_sharpe(port, CUMULATIVE_PRIOR_TRIALS + n_here, sr_var), 4)
        mid = port.index[len(port) // 2]
        s["H1_sharpe"] = round(float(sharpe(port[port.index <= mid])), 3)
        s["H2_sharpe"] = round(float(sharpe(port[port.index > mid])), 3)
        print(f"\n=== {s['name']} ===")
        for k, v in s.items():
            print(f"  {k:16s} {v}")
        port.to_frame("pnl_bp").to_parquet(OUT / f"mesh_portfolio_{pair}.parquet")
        ptr.to_csv(OUT / f"mesh_trades_{pair}.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
