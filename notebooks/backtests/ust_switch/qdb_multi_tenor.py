"""Every-cycle olds-vs-currents switch through QueryDrivenBacktest, per tenor.

What this runs
--------------
One QDB engine pass per tenor (2/3/5/7/10/20/30), trading the O-vs-CT switch EVERY
auction cycle -- the most frequent natural signal this trade has: long the old, short the
current, enter roll+1bd, exit next-roll+1bd, roll into the new pair the same day. Monthly
tenors trade ~190 cycles, quarterly ~65.

Equity is natively in bp: each leg is sized to $1 of DV01 per bp (``bpv=+/-1``), so a
dollar of book P&L IS a basis point of spread on a DV01-matched switch.

How QDB is made safe for this trade (each of these was measured, not assumed):

* **Pinned CUSIPs, never aliases.** A held alias position gets re-marked against the NEW
  issue's price on the OLD issue's cashflow schedule after every auction
  (``FixedRateBondValue._rebuild_pricer``). Every cycle's legs are resolved to concrete
  CUSIPs at entry from the same ranking function the study uses, and tagged per cycle so
  the unwind matches exactly that pair.
* **The time grid excludes gated days.** QDB's pricer path has none of the study's data
  gates, so a FedInvest ``CLEAN_PRICE=0`` day (283 of them; yields to 8145%) would mark
  straight through the equity curve as a thousands-of-bp spike. The grid is the GATED
  panel's date set per tenor, minus any day the gate dropped for any rank<=3 CUSIP.
* **Fees at unwind.** ``UnwindPositionsAction``-style meta fee, split across the cycle's
  two legs, totalling the SR1170 round trip (stressed table inside March 2020). Exit-only
  charging is exactly right here: one full spread per leg per completed round trip.
* **Swallowed timesteps are counted.** ``run()`` wraps each step in a bare except; a
  pricing failure leaves a hole in ``mtm_history``, not an error. Holes are reported and
  forward-filled for plotting only.

What QDB structurally cannot see, and the overlay
-------------------------------------------------
QDB marks total-return NPV: price + coupon accrual/pull-to-par. It has no financing hook
of any kind, so its equity is a **zero-financing** book. That is not a nuisance, it is
the study's headline measured a second way: the cross-check verified (corr 0.97, residual
<= 0.05bp) that QDB-minus-vectorised equals the cross-leg (y/D) accrual, so the missing
term is exactly the financing differential

    -[ (gc*100 - special)_L / D_L  -  (gc*100 - special)_S / D_S ] * dt/360   [bp]

computed here from the prepared panel for the held CUSIPs and added as a second line.
The gap between the two lines on every figure is the money a flat-financing backtest
invents.

Restartable: a tenor whose parquet exists is skipped. Figures are built from whatever
parquets exist, so a partial run yields partial figures.

    <env>/python.exe notebooks/backtests/ust_switch/qdb_multi_tenor.py            # run + figures
    <env>/python.exe notebooks/backtests/ust_switch/qdb_multi_tenor.py --figures  # figures only
"""

from __future__ import annotations

import argparse
import datetime
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

from RVUtils.USTSwitch.costs import CostModel, is_stressed  # noqa: E402
from RVUtils.USTSwitch.data import gate_ytm, load_prepared  # noqa: E402
from RVUtils.USTSwitch.engine import roll_dates  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "_out" / "qdb"
FIGS = HERE / "_out" / "figs"
TENORS = (2, 3, 5, 7, 10, 20, 30)


# ------------------------------------------------------------------ schedule


def build_schedule(panel: pd.DataFrame, amap: pd.DataFrame, tenor: int) -> tuple:
    """(grid_dates, cycles). Each cycle: entry/exit dates, pinned cusips, fee."""
    p = panel[panel["tenor"] == tenor]
    dates = pd.DatetimeIndex(sorted(p["date"].unique()))
    by_dr = p.set_index(["date", "rank"]).sort_index()

    rolls = roll_dates(amap, tenor)
    rolls = rolls[(rolls >= dates.min()) & (rolls <= dates.max())]
    cm = CostModel()

    def bd(d, n):
        pos = dates.searchsorted(d, side="left") + n
        return dates[pos] if 0 <= pos < len(dates) else None

    cycles, skipped = [], 0
    for i in range(len(rolls) - 1):
        entry = bd(rolls[i], 1)
        exit_ = bd(rolls[i + 1], 1)
        if entry is None or exit_ is None or exit_ <= entry:
            skipped += 1
            continue
        try:
            r_y = by_dr.loc[(entry, 0)]
            r_o = by_dr.loc[(entry, 1)]
        except KeyError:
            skipped += 1
            continue
        if isinstance(r_y, pd.DataFrame):
            r_y = r_y.iloc[0]
        if isinstance(r_o, pd.DataFrame):
            r_o = r_o.iloc[0]
        fee = cm.round_trip_yield_bp(
            tenor, 1, 0, float(r_o["MOD_DURATION"]), float(r_y["MOD_DURATION"]),
            stressed=is_stressed(entry) or is_stressed(exit_),
        )
        cycles.append(
            {"i": i, "entry": entry, "exit": exit_, "roll": rolls[i],
             "cusip_old": str(r_o["cusip"]), "cusip_young": str(r_y["cusip"]),
             "fee_bp": float(fee)}
        )

    # Align QDB's information set with the vectorised engine's: a cycle only ever marks
    # on days where BOTH its legs have a gated panel row, and its exit steps BACK to the
    # last such day. Without this, QDB prices through days the panel could not -- measured
    # consequence: on 2023-12-04 the 20y old leg printed a ~50bp-rich mark (4.02% vs a
    # 4.52% market) that passed the 100bp cross-rank gate while the young leg's row was
    # absent entirely; the vectorised engine's per-CUSIP date intersection skipped the
    # day, but QDB unwound ON it and baked +15.3bp into realized -- 6x the tenor's true
    # annual P&L, from one mark.
    by_cusip_dates = {c: set(g) for c, g in p.groupby("cusip")["date"]}
    kept, grid_days = [], set()
    for c in cycles:
        valid = by_cusip_dates.get(c["cusip_old"], set()) & by_cusip_dates.get(c["cusip_young"], set())
        ok = [d for d in dates if c["entry"] <= d <= c["exit"] and d in valid]
        if len(ok) < 3:
            skipped += 1
            continue
        c["entry"], c["exit"] = ok[0], ok[-1]
        kept.append(c)
        grid_days.update(ok)
    # The grid is the UNION of the cycles' own valid day-sets, not the tenor's full date
    # list. A day one cycle's legs cannot price may be another cycle's (adjusted) entry
    # day, so filtering the shared list would silently kill that entry; the union keeps
    # each cycle's days independent. Days outside every cycle carry no positions and add
    # nothing but flat equity, so losing them costs nothing.
    return pd.DatetimeIndex(sorted(grid_days)), kept, skipped


# ------------------------------------------------------------------ QDB


class SwitchScheduleAction:
    """One action serving the whole schedule: entries add the cycle's pinned pair,
    exits unwind it by tag with the cycle's fee. Implements the QAction protocol."""

    risk = None

    def __init__(self, cycles):
        from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
        from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

        self._FRBQ, self._V = FixedRateBondQuery, FixedRateBondValue
        self.entries = {}
        self.exits = {}
        for c in cycles:
            self.entries.setdefault(c["entry"].date(), []).append(c)
            self.exits.setdefault(c["exit"].date(), []).append(c)

    def __call__(self, *, now, backtest, info):
        from BT.query_order import QueryOrder, UnwindOrder

        d = now.date()
        orders = []
        for c in self.entries.get(d, ()):
            tag = f"cyc{c['i']}"
            for cusip, bpv in ((c["cusip_old"], 1.0), (c["cusip_young"], -1.0)):
                q = self._FRBQ(cusip=cusip, value=self._V.NPV,
                               structure_kwargs={"bpv": bpv}, tags=(tag,))
                orders.append(QueryOrder(timestamp=now, query=q,
                                         meta={"action": "add_query", "cycle": c["i"]}))
        for c in self.exits.get(d, ()):
            tag = f"cyc{c['i']}"

            def pred(p, _tag=tag):
                tags = set(p.meta.get("tags", []))
                tags.update(getattr(p.source_query, "tags", ()) or ())
                return _tag in tags

            orders.append(UnwindOrder(timestamp=now, selector=pred,
                                      meta={"action": "unwind", "fee": c["fee_bp"]}))
        return orders


def run_tenor_qdb(panel, amap, tenor: int) -> dict:
    from BT.data_handler import TimeGrid
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import FlowSignalTriggerRequirements, Trigger
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    dates, cycles, skipped = build_schedule(panel, amap, tenor)
    if not cycles:
        return {}
    sched = SwitchScheduleAction(cycles)
    fire_days = set(sched.entries) | set(sched.exits)

    trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda now, bt: now.date() in fire_days
        ),
        actions=[sched],
    )
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    strat = QueryStrategy(name=f"switch-{tenor}y", triggers=[trig], default_mdp=mdp)
    grid = [datetime.datetime.combine(pd.Timestamp(d).date(), datetime.time()) for d in dates]
    bt = QueryDrivenBacktest(time_grid=TimeGrid(grid), strategy=strat, mdp=mdp,
                             show_progress=False)
    t0 = time.time()
    bt.run()
    elapsed = time.time() - t0

    eq = pd.Series({pd.Timestamp(k): float(v) for k, v in bt.mtm_history.items()}).sort_index()
    holes = len(grid) - len(eq)
    eq = eq.reindex(pd.DatetimeIndex(dates)).ffill().fillna(0.0)

    # per-cycle net from the closed-positions ledger (realized is already net of fee)
    closed = pd.DataFrame(bt.portfolio.closed_positions_log)
    per_cycle = pd.DataFrame()
    if not closed.empty:
        closed["cycle"] = closed["source_query"].map(
            lambda q: next(iter(getattr(q, "tags", ()) or ()), "")
        )
        per_cycle = closed.groupby("cycle").agg(
            net_bp=("realized_pnl", "sum"),
            gross_bp=("gross_realized_pnl", "sum"),
            fee_bp=("fee_allocated", "sum"),
            n_legs=("realized_pnl", "size"),
        ).reset_index()
    return {"tenor": tenor, "dates": dates, "cycles": cycles, "equity": eq,
            "holes": holes, "skipped": skipped, "per_cycle": per_cycle,
            "elapsed": elapsed}


# ------------------------------------------------------------------ financing overlay


def financing_adjustment(panel: pd.DataFrame, tenor: int, cycles) -> pd.Series:
    """Daily bp the QDB book is missing: the per-issue financing differential.

    QDB's NPV marks contain the (y/D) accrual on both legs (verified against the
    vectorised engine at corr 0.97); what they cannot contain is the repo leg. Long a
    special issue you FINANCE it below GC (a benefit); short one you LEND at below GC
    (a cost). r = gc - special/100 per leg, and the book is long old / short young.
    """
    p = panel[panel["tenor"] == tenor]
    by_cd = p.set_index(["cusip", "date"]).sort_index()
    adj = {}
    for c in cycles:
        try:
            L = by_cd.loc[c["cusip_old"]].loc[c["entry"]:c["exit"]]
            S = by_cd.loc[c["cusip_young"]].loc[c["entry"]:c["exit"]]
        except KeyError:
            continue
        idx = L.index.intersection(S.index)
        if len(idx) < 2:
            continue
        L, S = L.loc[idx], S.loc[idx]
        yf = pd.Series(idx, index=idx).diff().dt.days.astype(float) / 360.0

        def r_over_d(x):
            return (x["gc_pct"] * 100.0 - x["special_used_bp"]) / x["MOD_DURATION"]

        daily = (-(r_over_d(L) - r_over_d(S)) * yf).fillna(0.0)
        for ts, v in daily.items():
            adj[ts] = adj.get(ts, 0.0) + float(v)
    return pd.Series(adj).sort_index()


# ------------------------------------------------------------------ frequency variant


def parity_equities(res: dict) -> pd.DataFrame:
    """Every-cycle vs every-other-cycle (odd/even), from the same QDB book.

    Cycles are sequential and non-overlapping except the shared boundary day, on which
    the old pair is unwound (its final P&L realizes) and the new pair enters flat -- so
    each daily equity increment belongs to exactly one cycle, boundary day to the OLD.
    "Every other cycle" is then the cumulative sum of alternate cycles' increments; no
    re-run and no re-marking, which keeps the comparison exact.
    """
    eq = res["equity"]
    d_eq = eq.diff().fillna(eq.iloc[0] if len(eq) else 0.0)
    owner = pd.Series(-1, index=eq.index)
    for c in res["cycles"]:
        # (entry, exit]: entry day belongs to the PREVIOUS cycle (this one enters flat)
        mask = (eq.index > c["entry"]) & (eq.index <= c["exit"])
        owner[mask] = c["i"]
    out = pd.DataFrame(index=eq.index)
    # Guard on owner >= 0 in BOTH parities: Python's -1 % 2 == 1, so an unguarded odd
    # mask would sweep ownerless days (pre-first-entry, swallowed-timestep fills) into
    # the odd book.
    out["every_cycle"] = d_eq.where(owner >= 0, 0.0).cumsum()
    out["odd_cycles"] = d_eq.where((owner >= 0) & (owner % 2 == 1), 0.0).cumsum()
    out["even_cycles"] = d_eq.where((owner >= 0) & (owner % 2 == 0), 0.0).cumsum()
    return out


# ------------------------------------------------------------------ figures


def make_figures(results: dict, panel) -> None:
    from RVUtils.USTSwitch import figures as F

    plt = F.style()
    FIGS.mkdir(parents=True, exist_ok=True)
    tenors = [t for t in TENORS if t in results]

    # A. small multiples: flat-financing QDB vs net of per-issue financing
    fig, axes = plt.subplots(4, 2, figsize=(13, 13), sharex=False)
    axes = axes.ravel()
    for ax, t in zip(axes, tenors):
        r = results[t]
        ax.plot(r["equity"].index, r["equity"].values, color=F.PAL[1], lw=1.6,
                label="QDB book (zero financing)")
        ax.plot(r["adj_equity"].index, r["adj_equity"].values, color=F.PAL[2], lw=1.6,
                label="net of per-issue financing")
        ax.axhline(0, color=F.MUTED, lw=0.8)
        n = len(r["cycles"])
        ax.set_title(f"{t}Y  O-vs-CT, every cycle ({n} trades)", fontsize=10)
        ax.set_ylabel("bp")
    for ax in axes[len(tenors):]:
        ax.set_visible(False)
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Olds-vs-currents through QueryDrivenBacktest — cumulative P&L (bp), "
                 "long old / short current, SR1170 fees at unwind", fontsize=12, y=0.995)
    fig.tight_layout()
    fig.savefig(FIGS / "13_qdb_equity_smallmultiples.png", dpi=130,
                bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)

    # B. all tenors net-of-financing, one axis (same unit: bp)
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for i, t in enumerate(tenors, start=1):
        r = results[t]
        ax.plot(r["adj_equity"].index, r["adj_equity"].values,
                color=F.PAL[min(i, 8)], lw=1.6, label=f"{t}Y")
    ax.axhline(0, color=F.MUTED, lw=0.9)
    ax.set_ylabel("cumulative P&L (bp)")
    ax.set_title("Every-cycle switch, net of per-issue financing — all tenors (bp)")
    ax.legend(ncol=7, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGS / "14_qdb_equity_all_tenors_net.png", dpi=130,
                bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)

    # C. signal frequency: every cycle vs every-other (odd/even), zero-financing book
    fig, axes = plt.subplots(4, 2, figsize=(13, 13))
    axes = axes.ravel()
    for ax, t in zip(axes, tenors):
        par = results[t]["parity"]
        ax.plot(par.index, par["every_cycle"], color=F.PAL[1], lw=1.6, label="every cycle")
        ax.plot(par.index, par["odd_cycles"], color=F.PAL[2], lw=1.3, label="odd cycles only")
        ax.plot(par.index, par["even_cycles"], color=F.PAL[3], lw=1.3, label="even cycles only")
        ax.axhline(0, color=F.MUTED, lw=0.8)
        ax.set_title(f"{t}Y — signal frequency", fontsize=10)
        ax.set_ylabel("bp")
    for ax in axes[len(tenors):]:
        ax.set_visible(False)
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Every cycle vs every other cycle (same QDB book, alternate cycles), bp",
                 fontsize=12, y=0.995)
    fig.tight_layout()
    fig.savefig(FIGS / "15_qdb_signal_frequency.png", dpi=130,
                bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)
    print(f"figures -> {FIGS} (13/14/15_qdb_*.png)")


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--figures", action="store_true", help="figures only, from saved parquets")
    ap.add_argument("--tenors", default="")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    panel, amap = load_prepared()
    # modelled financing for the overlay (full window; measured inside the JPM span)
    from RVUtils.USTSwitch.data import select_financing

    panel = select_financing(panel, "modelled")

    # Days the gate dropped, per tenor: QDB must never mark on them (it has no gates).
    raw = pd.read_parquet(HERE / "_data" / "bond_panel.parquet")
    for c in ("date", "issue_date", "maturity_date"):
        raw[c] = pd.to_datetime(raw[c])
    gated = gate_ytm(raw, verbose=False)
    dropped = raw.merge(gated[["date", "cusip"]], on=["date", "cusip"],
                        how="left", indicator=True)
    dropped = dropped[dropped["_merge"] == "left_only"]
    bad_days = dropped.groupby("tenor")["date"].apply(set).to_dict()

    tenors = tuple(int(x) for x in a.tenors.split(",")) if a.tenors else TENORS
    results = {}
    for t in tenors:
        eq_path = OUT / f"qdb_equity_{t}.parquet"
        cyc_path = OUT / f"qdb_cycles_{t}.csv"
        if eq_path.exists() or a.figures:
            if not eq_path.exists():
                continue
            df = pd.read_parquet(eq_path)
            cyc = pd.read_csv(cyc_path, parse_dates=["entry", "exit", "roll"])
            results[t] = {
                "tenor": t, "equity": df["equity_bp"],
                "adj_equity": df["equity_net_financing_bp"],
                "parity": df[["every_cycle", "odd_cycles", "even_cycles"]],
                "cycles": cyc.to_dict("records"),
            }
            print(f"{t}Y: loaded ({len(cyc)} cycles)")
            continue

        p_t = panel[~panel["date"].isin(bad_days.get(t, set()))] if t in bad_days else panel
        print(f"\n=== {t}Y ===", flush=True)
        r = run_tenor_qdb(p_t, amap, t)
        if not r:
            print(f"{t}Y: no cycles")
            continue
        adj = financing_adjustment(p_t, t, r["cycles"])
        adj = adj.reindex(r["equity"].index).fillna(0.0).cumsum()
        r["adj_equity"] = r["equity"] + adj
        r["parity"] = parity_equities(r)

        df = pd.DataFrame({
            "equity_bp": r["equity"],
            "equity_net_financing_bp": r["adj_equity"],
            "every_cycle": r["parity"]["every_cycle"],
            "odd_cycles": r["parity"]["odd_cycles"],
            "even_cycles": r["parity"]["even_cycles"],
        })
        df.to_parquet(eq_path)
        pd.DataFrame(r["cycles"]).to_csv(cyc_path, index=False)
        if not r["per_cycle"].empty:
            r["per_cycle"].to_csv(OUT / f"qdb_percycle_{t}.csv", index=False)

        n = len(r["cycles"])
        fin = float(r["adj_equity"].iloc[-1])
        raw_eq = float(r["equity"].iloc[-1])
        print(f"{t}Y: {n} cycles, {r['holes']} swallowed timesteps, "
              f"{r['skipped']} skipped cycles, {r['elapsed']:.0f}s\n"
              f"     QDB book (zero-financing) : {raw_eq:+8.2f} bp "
              f"({raw_eq / max(n, 1):+.3f}/trade)\n"
              f"     net of per-issue financing: {fin:+8.2f} bp "
              f"({fin / max(n, 1):+.3f}/trade)", flush=True)
        results[t] = r

    if results:
        make_figures(results, panel)
        summary = pd.DataFrame([
            {"tenor": t,
             "n_trades": len(r["cycles"]),
             "qdb_zero_financing_bp": round(float(r["equity"].iloc[-1]), 3),
             "net_of_financing_bp": round(float(r["adj_equity"].iloc[-1]), 3),
             "net_per_trade_bp": round(float(r["adj_equity"].iloc[-1]) / max(len(r["cycles"]), 1), 4)}
            for t, r in sorted(results.items())
        ])
        summary.to_csv(OUT / "qdb_summary.csv", index=False)
        print("\n=== QDB every-cycle summary ===")
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
