"""Sharpe-optimised grid search over QueryDrivenBacktest marks: all rank pairs, bond
switches and matched-maturity-SOFR-swap boxes.

What a "config" is
------------------
(tenor, pair, instrument, direction, entry_offset, exit_rule, z-filter[, swap_cost]).

* ``instrument="bond"``: the micro switch itself -- long old / short young (direction
  flips it), daily P&L = the QDB per-cycle marks from ``qdb_allpairs.py``.
* ``instrument="mms"``: the same switch HEDGED with matched-maturity SOFR swaps -- the
  box (old bond vs its matched swap) minus (young bond vs its matched swap). Its daily
  P&L = bond marks + direction * d(s_old - s_young)*100 from ``build_mms_rates.py``.
  This removes the curve-slope component that contaminates the raw spread (the older
  bond matures 1-3 months earlier), which is the study's known confound at 2y-10y where
  the raw rank pickup is NEGATIVE. MMS cycles exist only where SOFR does (2018-04+).

Every daily mark is a QueryDrivenBacktest mark. The grid recombines WHICH days each
variant is in the market (entry offsets clip leading days, exits clip trailing days,
filters drop whole cycles) -- it never re-prices. Costs are charged at each variant's own
boundaries: SR1170 round trip at the durations prevailing on the variant's entry day,
stressed table inside March 2020, plus (for MMS) a stated swap execution assumption of
0.25bp full spread per swap leg (0.5bp per box round trip), with a frictionless-swap
variant carried as the upper bound.

Financing: the QDB marks are zero-financing (the engine has no hook); the per-issue
differential (modelled specialness, JPM-tied) is accrued over each variant's held days,
exactly as validated against the vectorised engine at the 10Y (-1.358 vs -1.36 over 16y).

Deflation counts every configuration evaluated. The verdict taxonomy is the repo's.

    <env>/python.exe notebooks/backtests/ust_switch/qdb_gridsearch.py
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import pathlib
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")
import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from RVUtils.BasisVsVol.analytics import (  # noqa: E402
    expected_max_sharpe,
    max_drawdown,
    newey_west_tstat,
    sharpe,
)
from RVUtils.BasisVsVol.analytics import deflated_sharpe as dsr_prob_fn  # noqa: E402
from RVUtils.USTSwitch.costs import CostModel, is_stressed  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
SEGS = HERE / "_out" / "qdb_allpairs"
MMS = HERE / "_out" / "mms_rates"
OUT = HERE / "_out" / "qdb_grid"
FIGS = HERE / "_out" / "figs"

TENORS = (2, 3, 5, 7, 10, 20, 30)
PAIRS = ("CTvO", "CTvOO", "CTvOOO", "OvOO", "OvOOO", "OOvOOO")
ENTRY_OFFSETS = (0, 1, 3, 5, 10)
EXITS = ("next_roll", "fix10", "fix21", "fix42")
ZFILTERS = (None, (250, 1.0))
SWAP_RT_BP = 0.5  # per box round trip: 0.25bp full spread x 2 swap legs. Stated, not measured.
SOFR_FLOOR = pd.Timestamp("2018-04-02")


# ------------------------------------------------------------------ per-(tenor,pair) prep


class PairData:
    """Everything the grid needs about one (tenor, pair), precomputed once."""

    def __init__(self, tenor: int, pair: str, panel: pd.DataFrame, mms: pd.DataFrame | None):
        self.tenor, self.pair = tenor, pair
        segs = pd.read_parquet(SEGS / f"segs_{tenor}_{pair}.parquet")
        meta = pd.read_parquet(SEGS / f"meta_{tenor}_{pair}.parquet")
        segs["date"] = pd.to_datetime(segs["date"])
        for c in ("entry", "exit", "roll", "next_roll"):
            meta[c] = pd.to_datetime(meta[c])
        self.meta = meta.set_index("cycle_i")

        p = panel[panel["tenor"] == tenor]
        by_cd = p.set_index(["cusip", "date"]).sort_index()
        piv = p.pivot_table(index="date", columns="rank", values="YTM", aggfunc="first")
        ry, ro = int(meta["rank_young"].iloc[0]), int(meta["rank_old"].iloc[0])
        spread = (piv[ro] - piv[ry]) * 100.0 if ro in piv.columns and ry in piv.columns else None
        if spread is not None:
            mu = spread.shift(1).rolling(250, min_periods=60).mean()
            sd = spread.shift(1).rolling(250, min_periods=60).std(ddof=1)
            self.z = (spread - mu) / sd
        else:
            self.z = pd.Series(dtype=float)

        # Per-cycle arrays: dates, bond pnl, financing accrual, swap correction, durations.
        self.cycles = {}
        for ci, m in self.meta.iterrows():
            seg = segs[segs["cycle_i"] == ci].sort_values("date")
            dates = pd.DatetimeIndex(seg["date"])
            pnl = seg["pnl_bp"].to_numpy()
            try:
                L = by_cd.loc[m["cusip_old"]].reindex(dates)
                S = by_cd.loc[m["cusip_young"]].reindex(dates)
            except KeyError:
                continue
            dt_days = np.diff(dates.values).astype("timedelta64[D]").astype(float)
            dt_days = np.concatenate([[0.0], dt_days])
            with np.errstate(all="ignore"):
                rate = -(
                    (L["gc_pct"].to_numpy() * 100.0 - L["special_used_bp"].to_numpy())
                    / L["MOD_DURATION"].to_numpy()
                    - (S["gc_pct"].to_numpy() * 100.0 - S["special_used_bp"].to_numpy())
                    / S["MOD_DURATION"].to_numpy()
                )
            fin = np.nan_to_num(rate) * dt_days / 360.0

            swap = None
            if mms is not None:
                so = mms[mms["cusip"] == m["cusip_old"]].set_index("date")["par_rate_pct"].reindex(dates)
                sc = mms[mms["cusip"] == m["cusip_young"]].set_index("date")["par_rate_pct"].reindex(dates)
                gap = (so - sc) * 100.0
                if gap.notna().mean() > 0.9 and dates[0] >= SOFR_FLOOR:
                    swap = np.nan_to_num(gap.interpolate(limit_area="inside").diff().to_numpy())

            self.cycles[ci] = {
                "dates": dates, "pnl": pnl, "fin": fin, "swap": swap,
                "D_old": np.nan_to_num(L["MOD_DURATION"].to_numpy()),
                "D_young": np.nan_to_num(S["MOD_DURATION"].to_numpy()),
                "roll": m["roll"], "ry": ry, "ro": ro,
            }


# ------------------------------------------------------------------ one config


def run_config(pd_: PairData, instrument: str, direction: int, entry_off: int,
               exit_rule: str, zf, swap_cost: float, cm: CostModel):
    daily_idx, daily_val, trades = [], [], []
    for ci, c in pd_.cycles.items():
        if instrument == "mms" and c["swap"] is None:
            continue
        n = len(c["dates"])
        e = entry_off
        if e >= n - 1:
            continue
        if exit_rule == "next_roll":
            x = n - 1
        else:
            x = min(e + int(exit_rule[3:]), n - 1)
        if x <= e:
            continue

        if zf is not None:
            zv = pd_.z.get(c["dates"][e], np.nan)
            if not np.isfinite(zv):
                continue
            if direction > 0 and zv < zf[1]:
                continue
            if direction < 0 and zv > -zf[1]:
                continue

        pnl = direction * c["pnl"][e + 1 : x + 1]
        pnl = pnl + direction * c["fin"][e + 1 : x + 1]
        if instrument == "mms":
            pnl = pnl + direction * c["swap"][e + 1 : x + 1]

        D_o = c["D_old"][e] or np.nanmean(c["D_old"]) or 1.0
        D_y = c["D_young"][e] or np.nanmean(c["D_young"]) or 1.0
        stressed = is_stressed(c["dates"][e]) or is_stressed(c["dates"][x])
        rt = cm.round_trip_yield_bp(pd_.tenor, c["ro"], c["ry"], D_o, D_y, stressed=stressed)
        if instrument == "mms":
            rt += swap_cost
        pnl = pnl.copy()
        pnl[0] -= rt / 2.0
        pnl[-1] -= rt / 2.0

        daily_idx.append(c["dates"][e + 1 : x + 1])
        daily_val.append(pnl)
        trades.append({"cycle_i": ci, "entry": c["dates"][e], "exit": c["dates"][x],
                       "net_bp": float(pnl.sum()), "cost_bp": float(rt)})
    if not trades:
        return None
    daily = pd.Series(np.concatenate(daily_val),
                      index=pd.DatetimeIndex(np.concatenate([i.values for i in daily_idx])))
    daily = daily.groupby(level=0).sum().sort_index()
    tr = pd.DataFrame(trades)
    return daily, tr


def summarize(name, tenor, pair, instrument, direction, entry_off, exit_rule, zf,
              swap_cost, daily: pd.Series, tr: pd.DataFrame):
    t_nw, _ = newey_west_tstat(daily)
    yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    return {
        "name": name, "tenor": tenor, "pair": pair, "instrument": instrument,
        "direction": direction, "entry_offset": entry_off, "exit_rule": exit_rule,
        "z": "z" if zf else "", "swap_cost": swap_cost if instrument == "mms" else 0.0,
        "n_trades": len(tr), "years": round(yrs, 1),
        "net_bp": float(tr["net_bp"].sum()),
        "net_bp_per_trade": float(tr["net_bp"].mean()),
        "cost_bp_per_trade": float(tr["cost_bp"].mean()),
        "hit_rate": float((tr["net_bp"] > 0).mean()),
        "sharpe": float(sharpe(daily)),
        "t_stat_nw": float(t_nw),
        "max_dd_bp": float(max_drawdown(daily.cumsum())),
        "breakeven_cost_mult": float((tr["net_bp"].sum() + tr["cost_bp"].sum()) / tr["cost_bp"].sum())
        if tr["cost_bp"].sum() > 0 else np.nan,
    }


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-trades", type=int, default=8)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    panel = pd.read_parquet(HERE / "_data" / "prepared_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    from RVUtils.USTSwitch.data import select_financing

    panel = select_financing(panel, "modelled")

    cm = CostModel()
    rows, daily_by_name = [], {}
    t0 = time.time()
    for tenor in TENORS:
        mms_path = MMS / f"mms_rates_{tenor}.parquet"
        mms = None
        if mms_path.exists():
            mms = pd.read_parquet(mms_path)
            mms["date"] = pd.to_datetime(mms["date"])
        for pair in PAIRS:
            if not (SEGS / f"segs_{tenor}_{pair}.parquet").exists():
                continue
            pdata = PairData(tenor, pair, panel, mms)
            instruments = ["bond"] + (["mms"] if mms is not None else [])
            for inst in instruments:
                swap_costs = (0.0, SWAP_RT_BP) if inst == "mms" else (0.0,)
                for sc, direction, e, xr, zf in itertools.product(
                        swap_costs, (1, -1), ENTRY_OFFSETS, EXITS, ZFILTERS):
                    zlab = "_z" if zf else ""
                    sclab = f"_sc{sc:g}" if inst == "mms" else ""
                    name = (f"{tenor}Y_{pair}_{inst}{sclab}_"
                            f"{'LO' if direction > 0 else 'LC'}_e{e}_{xr}{zlab}")
                    res = run_config(pdata, inst, direction, e, xr, zf, sc, cm)
                    if res is None:
                        continue
                    daily, tr = res
                    if len(tr) < a.min_trades:
                        continue
                    rows.append(summarize(name, tenor, pair, inst, direction, e, xr, zf,
                                          sc, daily, tr))
                    daily_by_name[name] = daily
        print(f"{tenor}Y done ({time.time() - t0:.0f}s, {len(rows)} configs so far)", flush=True)

    league = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)
    league.to_csv(OUT / "league.csv", index=False)

    # deflation: DSR against the whole search
    n_trials = len(rows)
    sr = league["sharpe"].astype(float)
    sr_var = float(np.nanvar(sr, ddof=1))
    league["dsr_prob"] = [
        dsr_prob_fn(daily_by_name[nm], n_trials, sr_var) if nm in daily_by_name else np.nan
        for nm in league["name"]
    ]
    league["verdict"] = np.where(
        (league["net_bp_per_trade"] > 0) & (league["dsr_prob"] >= 0.95), "ALIVE",
        np.where(league["net_bp_per_trade"] > 0, "SELECTION-ARTIFACT", "DEAD"))
    league.to_csv(OUT / "league_deflated.csv", index=False)

    # effective trials on a rank-stratified subsample
    from RVUtils.USTSwitch.analytics import deflate_with_effective_trials

    eff = deflate_with_effective_trials(daily_by_name)
    with open(OUT / "effective_trials.json", "w") as f:
        json.dump({k: (float(v) if isinstance(v, (int, float)) else str(v))
                   for k, v in eff.items()}, f, indent=2)

    # save winners' daily series for figures
    top = league.head(40)
    pd.DataFrame({nm: daily_by_name[nm].cumsum() for nm in top["name"] if nm in daily_by_name}
                 ).to_parquet(OUT / "top_equity.parquet")

    print(f"\n{len(league)} configs scored, trials {n_trials}, sr_var {sr_var:.3f}, "
          f"E[maxSR|null] {expected_max_sharpe(n_trials, sr_var):.2f}")
    cols = ["name", "n_trades", "net_bp_per_trade", "cost_bp_per_trade", "hit_rate",
            "sharpe", "t_stat_nw", "dsr_prob", "breakeven_cost_mult", "verdict"]
    print("\nTOP 25 BY SHARPE:")
    print(league.head(25)[cols].round(4).to_string(index=False))
    print(f"\nverdicts:\n{league['verdict'].value_counts().to_string()}")
    print("\nby instrument (best sharpe):")
    print(league.groupby("instrument")["sharpe"].max().round(3).to_string())
    if eff:
        print("\neffective-trials deflation:")
        for k, v in eff.items():
            print(f"  {k:28s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
