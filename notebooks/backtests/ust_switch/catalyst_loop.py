"""Catalyst-conditioned auction-release switch: the loop-engineering pass.

The candidate and why it is pre-specified, not mined
----------------------------------------------------
Everything in this file is the SAME trade: **long the new current / short the old
(CTvO, DV01-matched), entered at the roll, exited around the ISSUE date** -- the exact
window over which Boyarchenko-Lucca-Veldkamp (w22461) measure ~3bp of hedged
post-auction appreciation on 494 auctions, and the window whose sign this study has
already measured three independent ways (cycle profile, placebo asymmetry, intraday
overnight release). For front-end notes the issue date IS month-end -- the release window
and the index-inclusion window are the same days, so "auction catalyst" and "month-end
rebalancing catalyst" are one trade at 2y/3y/5y/7y, not two.

The unconditional version is measured and DEAD (gross +0.3-0.9bp vs ~1bp round trip,
full 2010-2026 window). The paper's own cross-section says where the payoff lives:
appreciation is larger when the auction was more heavily conceded and demand is
stronger, and its distribution is positively skewed. So the loop conditions entry on
two EX-ANTE observables of exactly that:

* ``selloff``  -- the OLD bond's yield change over the 5bd into the roll (same CUSIP, no
  splice): how much the sector cheapened into the auction. Bigger concession ->
  bigger expected release.
* ``special``  -- the NEW issue's specialness at entry (JPM-tied panel; modelled
  pre-2016-08): the collateral market's measure of demand for the new bond. Also a
  carry TAILWIND for this direction: long the special issue finances below GC.

Thresholds are EXPANDING quantiles of each conditioner's own past (>=8 prior cycles),
never the full sample -- a threshold that knows the future is a backtest of hindsight.

Deflation is reported against this file's own trial count AND the session's cumulative
search; both numbers printed, neither hidden.
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
OUT = HERE / "_out" / "catalyst"
FIGS = HERE / "_out" / "figs"

TENORS = (2, 3, 5, 7, 10, 20, 30)
#: cumulative configurations evaluated across this session's searches, for the honest
#: deflation denominator: 8,716 (all-pairs) + 5,040 (new-issue) + 36 placebos + this file.
CUMULATIVE_PRIOR_TRIALS = 13_792


# ------------------------------------------------------------------ data prep


def load_pair(tenor: int, panel: pd.DataFrame):
    segs = pd.read_parquet(SEGS / f"segs_{tenor}_CTvO.parquet")
    meta = pd.read_parquet(SEGS / f"meta_{tenor}_CTvO.parquet")
    segs["date"] = pd.to_datetime(segs["date"])
    for c in ("entry", "exit", "roll", "next_roll"):
        meta[c] = pd.to_datetime(meta[c])
    p = panel[panel["tenor"] == tenor]
    by_cd = p.set_index(["cusip", "date"]).sort_index()
    issue_of = p.groupby("cusip")["issue_date"].first()

    cycles = []
    for _, m in meta.sort_values("cycle_i").iterrows():
        seg = segs[segs["cycle_i"] == m["cycle_i"]].sort_values("date")
        dates = pd.DatetimeIndex(seg["date"])
        if len(dates) < 4:
            continue
        try:
            Y = by_cd.loc[m["cusip_young"]].reindex(dates)   # the NEW current (long leg)
            O = by_cd.loc[m["cusip_old"]].reindex(dates)     # the old (short leg)
        except KeyError:
            continue
        dt_days = np.concatenate([[0.0], np.diff(dates.values).astype("timedelta64[D]").astype(float)])
        with np.errstate(all="ignore"):
            fin_rate = -(
                (O["gc_pct"].to_numpy() * 100.0 - O["special_used_bp"].to_numpy()) / O["MOD_DURATION"].to_numpy()
                - (Y["gc_pct"].to_numpy() * 100.0 - Y["special_used_bp"].to_numpy()) / Y["MOD_DURATION"].to_numpy()
            )
        # conditioners, strictly ex-ante at the entry mark
        old_hist = by_cd.loc[m["cusip_old"]]["YTM"] if m["cusip_old"] in by_cd.index.get_level_values(0) else None
        selloff = np.nan
        if old_hist is not None:
            h = old_hist.loc[: dates[0]].dropna()
            if len(h) >= 6:
                selloff = (h.iloc[-1] - h.iloc[-6]) * 100.0  # bp over the 5bd into the roll
        special = float(Y["special_used_bp"].iloc[0]) if pd.notna(Y["special_used_bp"].iloc[0]) else np.nan

        iss = issue_of.get(m["cusip_young"], pd.NaT)
        cycles.append({
            "cycle_i": int(m["cycle_i"]), "roll": m["roll"], "dates": dates,
            # LO-signed marks from the store; the LC trade negates them
            "pnl_lo": seg["pnl_bp"].to_numpy(),
            "fin_lo": np.nan_to_num(fin_rate) * dt_days / 360.0,
            "D_o": np.nan_to_num(O["MOD_DURATION"].to_numpy()),
            "D_y": np.nan_to_num(Y["MOD_DURATION"].to_numpy()),
            "issue": pd.Timestamp(iss) if pd.notna(iss) else pd.NaT,
            "selloff": selloff, "special": special,
        })
    return cycles


# ------------------------------------------------------------------ one variant


def run_variant(tenor, cycles, cond: str, mode: str, exit_rule: str, cm: CostModel):
    """LC release trade, entry roll+0. Returns (daily bp Series, trades DataFrame)."""
    hist = []  # conditioner history for expanding thresholds
    daily_idx, daily_val, trades = [], [], []
    for c in cycles:
        cval = c[cond] if cond != "none" else 0.0
        take = True
        if cond != "none":
            if not np.isfinite(cval):
                take = False
            else:
                prior = [h for h in hist if np.isfinite(h)]
                hist.append(cval)
                if len(prior) < 8:
                    take = False
                else:
                    thr = np.quantile(prior, {"p50": 0.5, "p75": 0.75}[mode])
                    take = cval > thr
        if not take:
            continue

        dates, n = c["dates"], len(c["dates"])
        if exit_rule.startswith("issue"):
            if pd.isna(c["issue"]):
                continue
            k = int(exit_rule[5:] or 0)
            target = c["issue"]
            x = int(dates.searchsorted(target, side="left")) + k
            x = min(max(x, 2), n - 1)
        else:
            x = min(int(exit_rule[3:]), n - 1)
        pnl = -c["pnl_lo"][1 : x + 1] - c["fin_lo"][1 : x + 1]  # LC = negate the LO book
        rt = cm.round_trip_yield_bp(
            tenor, 1, 0, c["D_o"][0] or 1.0, c["D_y"][0] or 1.0,
            stressed=is_stressed(dates[0]) or is_stressed(dates[x]),
        )
        pnl = pnl.copy()
        pnl[0] -= rt / 2.0
        pnl[-1] -= rt / 2.0
        daily_idx.append(dates[1 : x + 1])
        daily_val.append(pnl)
        trades.append({"tenor": tenor, "roll": c["roll"], "entry": dates[0], "exit": dates[x],
                       "held_bd": x, "net_bp": float(pnl.sum()), "cost_bp": float(rt),
                       "cond_val": cval})
    if not trades:
        return None
    daily = pd.Series(np.concatenate(daily_val),
                      index=pd.DatetimeIndex(np.concatenate([i.values for i in daily_idx])))
    return daily.groupby(level=0).sum().sort_index(), pd.DataFrame(trades)


def summarize(name, daily, tr):
    t_nw, _ = newey_west_tstat(daily)
    return {"name": name, "n_trades": len(tr),
            "net_bp": round(float(tr["net_bp"].sum()), 2),
            "net_bp_per_trade": round(float(tr["net_bp"].mean()), 4),
            "cost_bp_per_trade": round(float(tr["cost_bp"].mean()), 3),
            "hit_rate": round(float((tr["net_bp"] > 0).mean()), 3),
            "avg_held_bd": round(float(tr["held_bd"].mean()), 1),
            "sharpe": round(float(sharpe(daily)), 3),
            "t_stat_nw": round(float(t_nw), 2),
            "max_dd_bp": round(float(max_drawdown(daily.cumsum())), 2)}


# ------------------------------------------------------------------ main loop


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    panel = pd.read_parquet(HERE / "_data" / "prepared_panel.parquet")
    for c in ("date", "issue_date", "maturity_date"):
        panel[c] = pd.to_datetime(panel[c])
    from RVUtils.USTSwitch.data import select_financing

    panel = select_financing(panel, "modelled")
    cm = CostModel()

    by_tenor = {}
    for t in TENORS:
        cyc = load_pair(t, panel)
        if a.start:
            cyc = [c for c in cyc if c["dates"][0] >= pd.Timestamp(a.start)]
        by_tenor[t] = cyc
        print(f"{t}Y: {len(cyc)} cycles", flush=True)

    CONDS = [("none", "-"), ("selloff", "p50"), ("selloff", "p75"),
             ("special", "p50"), ("special", "p75")]
    EXITS = ("issue1", "issue3", "fix5")

    rows, dailies, trades_all = [], {}, {}
    for t, (cond, mode), xr in itertools.product(TENORS, CONDS, EXITS):
        res = run_variant(t, by_tenor[t], cond, mode, xr, cm)
        if res is None:
            continue
        daily, tr = res
        if len(tr) < 8:
            continue
        name = f"{t}Y_LC_{cond}{'' if mode == '-' else mode}_{xr}"
        rows.append(summarize(name, daily, tr) | {"tenor": t, "cond": cond, "mode": mode,
                                                  "exit": xr})
        dailies[name] = daily
        trades_all[name] = tr
    league = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)

    n_here = len(rows)
    sr_var = float(np.nanvar(league["sharpe"], ddof=1))
    league["dsr_here"] = [deflated_sharpe(dailies[nm], n_here, sr_var) for nm in league["name"]]
    league["dsr_cumulative"] = [
        deflated_sharpe(dailies[nm], CUMULATIVE_PRIOR_TRIALS + n_here, sr_var)
        for nm in league["name"]]
    league.to_csv(OUT / "catalyst_league.csv", index=False)

    print(f"\n{n_here} variants  (cumulative session trials {CUMULATIVE_PRIOR_TRIALS + n_here})")
    cols = ["name", "n_trades", "net_bp_per_trade", "cost_bp_per_trade", "hit_rate",
            "avg_held_bd", "sharpe", "t_stat_nw", "dsr_here", "dsr_cumulative"]
    print(league.head(30)[cols].round(3).to_string(index=False))

    # ---- portfolio of the best UNIFORM rule (same rule every tenor, chosen by MEAN
    # sharpe across tenors -- a rule, not a cell, to resist cherry-picking)
    rule_stats = (league.groupby(["cond", "mode", "exit"])
                  .agg(mean_sharpe=("sharpe", "mean"), n_tenors=("sharpe", "size"),
                       mean_hit=("hit_rate", "mean"))
                  .sort_values("mean_sharpe", ascending=False))
    print("\nuniform rules ranked by MEAN Sharpe across tenors:")
    print(rule_stats.round(3).to_string())
    best_rule = rule_stats.index[0]
    picks = [f"{t}Y_LC_{best_rule[0]}{'' if best_rule[1] == '-' else best_rule[1]}_{best_rule[2]}"
             for t in TENORS]
    picks = [p for p in picks if p in dailies]
    port = pd.concat([dailies[p] for p in picks], axis=1).fillna(0.0).sum(axis=1)
    port_tr = pd.concat([trades_all[p] for p in picks], ignore_index=True)
    port.to_frame("pnl_bp").to_parquet(OUT / "portfolio_daily.parquet")
    port_tr.to_csv(OUT / "portfolio_trades.csv", index=False)
    ps = summarize("PORTFOLIO_" + "_".join(str(x) for x in best_rule), port, port_tr)
    print("\n=== PORTFOLIO (best uniform rule, all tenors) ===")
    for k, v in ps.items():
        print(f"  {k:20s} {v}")
    t_nw, _ = newey_west_tstat(port)
    yrs = (port.index[-1] - port.index[0]).days / 365.25
    print(f"  trades/year          {len(port_tr) / yrs:.1f}")
    print(f"  dsr vs cumulative    "
          f"{deflated_sharpe(port, CUMULATIVE_PRIOR_TRIALS + n_here, sr_var):.4f}")

    # split-half
    mid = port.index[len(port) // 2]
    for lab, seg in (("H1", port[port.index <= mid]), ("H2", port[port.index > mid])):
        print(f"  {lab}: sharpe {sharpe(seg):+.3f}  total {seg.sum():+.1f}bp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
