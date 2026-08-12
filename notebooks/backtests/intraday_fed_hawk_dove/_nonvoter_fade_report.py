"""The notebook's strategy, with the non-voting presidents traded backwards.

The active config in `usd_fomc_configurable_backtest.ipynb` trades VOTERS only:
receive before a dove, pay before a hawk, 3rd quarterly SR3, T-60/T+240, no
trades inside 10 days of a meeting, from 2022. This runs that book and three
others that differ from it only in what is done with the speakers the published
rotation gives no vote this year:

    A  voters only                      the notebook, unchanged
    B  non-voters, as read              the other half of the roster, straight
    C  non-voters, FADED                pay before their doves, receive before
                                        their hawks  (== -1 x B, by construction)
    D  voters + non-voters FADED        the combined book, one position at a time
    E  everyone, as read                the control: what if the label is a label
    F  voters FADED + non-voters as read  the mirror, which should be bad

D is the answer to the question. It is NOT A + C: the one-position-at-a-time
rule runs on the combined book, so a non-voter's position can sit in front of a
voter's speech and take the slot. That displacement is counted below, in trades
and in basis points, because it is the price of the extra book.

Everything is priced from the same cached minute bars, by the same causal gate,
on the same events. The only thing that changes is the sign.
"""

from __future__ import annotations

import io
import json
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
GCB = Path(r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(GCB))          # the ARBS package, as the notebook loads it
sys.path.insert(0, str(HERE))         # ...the study modules from here

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

import global_hawk_dove_common as G
import global_hawk_dove_grid as GRID
import hawk_dove_config as HC

CACHE = HERE / "_global_cache"
pd.set_option("display.width", 200, "display.max_columns", 40)

# ---------------------------------------------------------------------------
# The notebook's active config, verbatim.
# ---------------------------------------------------------------------------
CONFIG = {
    "name": "voters only (the notebook)",
    "bank": "FED",
    "instrument": {"kind": "outright", "rank": 3},
    "timing": {"entry_offset_min": -60, "exit_offset_min": 240,
               "max_staleness_min": 45, "retime_synthetic": False},
    "filters": {"start": "2022-01-01", "end": None, "voters": "voters",
                "roles": None, "speakers_include": None, "speakers_exclude": None,
                "timestamp_source": "all", "min_abs_bucket": 1, "direction": "both",
                "era": "SR3", "days_to_fomc_max": None, "days_to_fomc_min": 10,
                "weekdays": None},
    "flip": "none",
    "sizing": "equal",
    "cost_bp": 0,
}


def cfg(name, **over):
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in CONFIG.items()}
    out["name"] = name
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


BOOKS = {
    "A voters only (the notebook)": cfg("A voters only (the notebook)"),
    "B non-voters, as read": cfg("B non-voters, as read",
                                 filters={"voters": "nonvoters"}),
    "C non-voters, FADED": cfg("C non-voters, FADED",
                               filters={"voters": "nonvoters"}, flip="nonvoters"),
    "D voters + non-voters FADED": cfg("D voters + non-voters FADED",
                                       filters={"voters": "all"}, flip="nonvoters"),
    "E everyone, as read": cfg("E everyone, as read", filters={"voters": "all"}),
    "F voters FADED + non-voters as read": cfg("F voters FADED + non-voters as read",
                                               filters={"voters": "all"}, flip="voters"),
}

HEAD = "A voters only (the notebook)"
COMB = "D voters + non-voters FADED"


def rule(t=""):
    print("\n" + "=" * 78)
    if t:
        print(t)
        print("=" * 78)


def perf(df, label):
    if df is None or df.empty:
        return {"book": label, "trades": 0}
    s = G.summarize(df)
    p = df.pnl_bp
    return {"book": label, "trades": s["trades"], "total_bp": round(s["total"], 2),
            "avg_bp": round(s["avg"], 4), "hit": round(s["hit_rate"], 4),
            "sharpe": round(s["sharpe"], 3),
            "sr_per_trade": round(p.mean() / p.std(ddof=1), 4) if p.std(ddof=1) else 0.0,
            "t_stat": round(s["t_stat"], 3), "max_dd": round(s["max_dd"], 2),
            "tpy": round(s["trades_per_year"], 1)}


def main() -> None:
    n = G.load_bar_cache(CACHE / "bars.pkl")
    with open(CACHE / "events_manual_raw.pkl", "rb") as f:
        raw = pickle.load(f)["FED"]["events"]
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    print(f"raw event book {len(raw)} events   bar cache {n:,} symbol-days")
    print("\nconfig (the notebook's, with `flip` and `voters` as the only edits):")
    print(json.dumps({k: v for k, v in CONFIG.items() if k != "name"},
                     indent=2, default=str))

    # -- the voting rotation must be KNOWN, not assumed ---------------------
    rule("0. who is a non-voter here")
    attrs = [HC.event_attrs(e) for e in raw]
    unknown = sum(1 for a in attrs if a["is_voter"] is None)
    print(f"events whose voting status is unknown: {unknown}  "
          f"(a 'nonvoters' filter and a 'nonvoters' flip both refuse to guess)")
    nv_roles = pd.Series([a["role"] for a in attrs if a["is_voter"] is False]).value_counts()
    print("roles of every non-voter in the raw book:")
    print(nv_roles.to_string())
    assert unknown == 0, "unknown voting status present — the two books are not complements"

    # -- run every book -----------------------------------------------------
    rule("1. the books")
    res = {k: HC.run_config(c, raw, mdp) for k, c in BOOKS.items()}
    tbl = pd.DataFrame([perf(r.closed, k) for k, r in res.items()]).set_index("book")
    print(tbl.to_string())
    print("\nsharpe is annualised by trade frequency, so a book that trades more often")
    print("scores higher for the same edge per trade — read sr_per_trade alongside it.")

    A, B, C = res[HEAD].closed, res["B non-voters, as read"].closed, res["C non-voters, FADED"].closed
    D, E = res[COMB].closed, res["E everyone, as read"].closed

    # -- the funnel ---------------------------------------------------------
    rule("2. what the combined book actually trades")
    f_ = res[COMB].funnel
    row = {"raw events": f_["raw"]}
    row.update({f"filtered: {k}": v for k, v in sorted(f_["filter_drops"].items(),
                                                       key=lambda x: -x[1])})
    row["after filters"] = f_["after_filters"]
    row.update({f"re-time: {k}": v for k, v in f_["retime_drops"].items() if v})
    row["after overlap rule"] = f_["after_retime_overlap"]
    for rk, reasons in f_["gate_reasons"].items():
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            row[f"gate rank {rk}: {k}"] = v
    row["TRADEABLE"] = len(D)
    print(pd.Series(row).to_frame("D").to_string())
    print(f"\nbars missing: {f_['n_missing_bars']} of {f_['coverage']['wanted']} symbol-days")
    assert f_["n_missing_bars"] == 0

    # -- displacement -------------------------------------------------------
    rule("3. the combined book is NOT the voters' book plus extra trades")
    d_v, d_n = D[D.is_voter == True], D[D.is_voter == False]      # noqa: E712
    lost = A[~A.tag.isin(D.tag)]
    gained_nv = C[~C.tag.isin(D.tag)]
    print(f"voter trades      standalone {len(A):4d}   inside D {len(d_v):4d}   "
          f"displaced {len(lost):3d}")
    print(f"non-voter trades  standalone {len(C):4d}   inside D {len(d_n):4d}   "
          f"displaced {len(gained_nv):3d}")
    print(f"\nthe {len(lost)} voter speeches a non-voter's position was sitting in front of")
    print(f"were worth {lost.pnl_bp.sum():+.2f}bp in the standalone voter book "
          f"({lost.pnl_bp.mean():+.4f}bp/trade)")
    print(f"the non-voter trades that survived into D are worth "
          f"{d_n.pnl_bp.sum():+.2f}bp faded ({d_n.pnl_bp.mean():+.4f}bp/trade)")
    print(f"\nnaive A + C would read {A.pnl_bp.sum() + C.pnl_bp.sum():+.2f}bp; "
          f"D actually books {D.pnl_bp.sum():+.2f}bp "
          f"({D.pnl_bp.sum() - A.pnl_bp.sum() - C.pnl_bp.sum():+.2f}bp of that gap "
          f"is the overlap rule)")

    # -- where D's pnl comes from ------------------------------------------
    rule("4. inside the combined book")
    parts = pd.DataFrame([perf(d_v, "  voters, as read"), perf(d_n, "  non-voters, FADED"),
                          perf(D, "D total")]).set_index("book")
    print(parts.to_string())
    print(f"\nthe fade contributes {d_n.pnl_bp.sum():+.2f}bp of D's "
          f"{D.pnl_bp.sum():+.2f}bp on {len(d_n)}/{len(D)} of the trades")

    # -- is the fade itself real? ------------------------------------------
    rule("5. is the non-voter drift real, or is it zero?")
    p = B.pnl_bp.to_numpy(float)
    se = p.std(ddof=1) / np.sqrt(len(p))
    print(f"non-voters as read : {len(p)} trades   {p.mean():+.4f} +- {se:.4f} bp/trade "
          f"(1 s.e.)   t = {p.mean()/se:+.3f}")
    print(f"faded              : {-p.mean():+.4f} bp/trade   t = {-p.mean()/se:+.3f}")
    rng = np.random.default_rng(20260812)
    boot = np.array([rng.choice(p, size=len(p), replace=True).mean() for _ in range(20000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"20k bootstrap 95% CI on the non-voter mean: [{lo:+.4f}, {hi:+.4f}] bp/trade")
    print(f"  P(mean < 0) = {(boot < 0).mean():.4f}")
    sf = G.sign_flip_permutation(C, n_perm=20000)
    print(f"\nsign-flip permutation on the FADED non-voter book: realised Sharpe "
          f"{sf['realized_sharpe']:+.3f}   null {sf['perm_mean']:+.3f} +- {sf['perm_std']:.3f}"
          f"   p = {sf['p_value']:.4f}")
    sfD = G.sign_flip_permutation(D, n_perm=20000)
    print(f"sign-flip permutation on D:                     realised Sharpe "
          f"{sfD['realized_sharpe']:+.3f}   null {sfD['perm_mean']:+.3f} +- {sfD['perm_std']:.3f}"
          f"   p = {sfD['p_value']:.4f}")

    # -- is "non-voter" a special partition? -------------------------------
    rule("6. would flipping ANY 155 trades have done as well?")
    Es = E.sort_values(["opened_at", "tag"]).reset_index(drop=True)
    isnv = (Es.is_voter == False).to_numpy()                        # noqa: E712
    pe = Es.pnl_bp.to_numpy(float)
    k = int(isnv.sum())
    real_total = pe.sum() - 2 * pe[isnv].sum()
    rng2 = np.random.default_rng(11)
    idx = np.arange(len(pe))
    draws = np.empty(20000)
    for i in range(20000):
        s = rng2.choice(idx, size=k, replace=False)
        draws[i] = pe.sum() - 2 * pe[s].sum()
    pct = float((draws >= real_total).mean())
    print(f"flipping the {k} non-voter trades in the whole-book run gives "
          f"{real_total:+.2f}bp")
    print(f"flipping a RANDOM {k} of the {len(pe)} gives {draws.mean():+.2f} "
          f"+- {draws.std():.2f}bp   (20k draws)")
    print(f"the non-voter partition is better than {1 - pct:.1%} of random ones "
          f"-> one-sided p = {pct:.4f}")
    print("this is the question that matters: is 'no vote' a real seam in the book,")
    print("or just one of many ways to cut 155 trades out of 504?")

    # -- concentration ------------------------------------------------------
    rule("7. who is the fade actually trading?")
    spk = (B.groupby("speaker").pnl_bp.agg(["count", "sum", "mean"])
           .sort_values("sum").round(3))
    spk.columns = ["trades", "total_bp_as_read", "avg_bp_as_read"]
    print(spk.to_string())
    top = spk.head(3)
    print(f"\nthe 3 biggest contributors are {list(top.index)}: "
          f"{top.total_bp_as_read.sum():+.1f}bp of {B.pnl_bp.sum():+.1f}bp "
          f"on {int(top.trades.sum())}/{len(B)} trades")

    # -- through time -------------------------------------------------------
    rule("8. through time")
    yr = pd.DataFrame({
        "A voters": A.groupby("year").pnl_bp.sum(),
        "C non-voters FADED": C.groupby("year").pnl_bp.sum(),
        "D combined": D.groupby("year").pnl_bp.sum(),
        "C trades": C.groupby("year").pnl_bp.count(),
    }).round(2)
    print(yr.to_string())
    for nm, df in [("A", A), ("C", C), ("D", D)]:
        mid = len(df) // 2
        h1, h2 = G.summarize(df.iloc[:mid]), G.summarize(df.iloc[mid:])
        print(f"{nm}: 1st half {h1['avg']:+.4f}bp/trade ({h1['trades']}t)   "
              f"2nd half {h2['avg']:+.4f}bp/trade ({h2['trades']}t)")

    # -- costs --------------------------------------------------------------
    rule("9. costs")
    COSTS = [0.0, 0.125, 0.25, 0.375, 0.5, 0.75, 1.0]
    cost_df = pd.DataFrame(
        [{"cost_bp_rt": c, **{k: round(r.closed.pnl_bp_gross.sum() - c * len(r.closed), 1)
                              for k, r in res.items() if not r.closed.empty}}
         for c in COSTS]).set_index("cost_bp_rt")
    print(cost_df.to_string())
    print("\nbreak-even round trip (bp per trade, = gross edge per trade):")
    for k, r in res.items():
        if not r.closed.empty:
            print(f"  {k:38s} {r.closed.pnl_bp_gross.mean():+.4f}   "
                  f"({len(r.closed)} trades)")

    # -- does the fade survive a change of instrument? ----------------------
    rule("10. the same question on every warm instrument")
    warm = [rk for rk in range(1, 9)
            if HC.check_coverage(
                HC.retime(HC.apply_filters(raw, BOOKS[COMB]["filters"])[0],
                          G.CB_CONFIGS["FED"], -60, 240, False)[0],
                G.CB_CONFIGS["FED"], [rk])["ok"]]
    cat = HC.catalogue(max(warm) if warm else 3)
    insts = ([{"kind": "outright", "rank": r} for r in warm] +
             [{"structure": s.name} for s in cat.values()
              if s.kind != "outright" and set(s.ranks) <= set(warm)])
    rows = []
    for i in insts:
        nm = i.get("structure") or f"OUT_{i['rank']}"
        rb = HC.run_config(cfg(f"{nm} B", filters={"voters": "nonvoters"},
                               instrument=i), raw, mdp).closed
        rd = HC.run_config(cfg(f"{nm} D", filters={"voters": "all"},
                               flip="nonvoters", instrument=i), raw, mdp).closed
        ra = HC.run_config(cfg(f"{nm} A", instrument=i), raw, mdp).closed
        rows.append({
            "instrument": nm,
            "A_avg": round(ra.pnl_bp.mean(), 4) if len(ra) else np.nan,
            "A_t": round(G.summarize(ra)["t_stat"], 2) if len(ra) else np.nan,
            "nonvoter_avg_as_read": round(rb.pnl_bp.mean(), 4) if len(rb) else np.nan,
            "nonvoter_t": round(G.summarize(rb)["t_stat"], 2) if len(rb) else np.nan,
            "D_avg": round(rd.pnl_bp.mean(), 4) if len(rd) else np.nan,
            "D_t": round(G.summarize(rd)["t_stat"], 2) if len(rd) else np.nan,
            "D_sharpe": round(G.summarize(rd)["sharpe"], 3) if len(rd) else np.nan,
            "D_trades": len(rd),
        })
    inst_tbl = pd.DataFrame(rows).set_index("instrument")
    print(inst_tbl.to_string())
    neg = inst_tbl.nonvoter_avg_as_read < 0
    print(f"\nnon-voter drift is negative (so the fade pays) on "
          f"{int(neg.sum())}/{len(inst_tbl)} instruments; "
          f"significant at |t|>2 on {int((inst_tbl.nonvoter_t.abs() > 2).sum())}")

    # -- and a change of window? -------------------------------------------
    rule("11. the same question on every entry/exit window")
    ENTRY, EXIT = [-120, -60, -45, -15, 0], [30, 60, 120, 180, 240]
    g_nv = pd.DataFrame(index=ENTRY, columns=EXIT, dtype=float)
    g_d = pd.DataFrame(index=ENTRY, columns=EXIT, dtype=float)
    g_n = pd.DataFrame(index=ENTRY, columns=EXIT, dtype=float)
    for e in ENTRY:
        for x in EXIT:
            t = {"entry_offset_min": e, "exit_offset_min": x}
            rb = HC.run_config(cfg("b", filters={"voters": "nonvoters"}, timing=t),
                               raw, mdp).closed
            rd = HC.run_config(cfg("d", filters={"voters": "all"}, flip="nonvoters",
                                   timing=t), raw, mdp).closed
            g_nv.loc[e, x] = rb.pnl_bp.mean() if len(rb) else np.nan
            g_d.loc[e, x] = G.summarize(rd)["sharpe"] if len(rd) else np.nan
            g_n.loc[e, x] = len(rd)
    print("non-voter edge AS READ, bp/trade (negative => the fade pays):")
    print(g_nv.round(3).to_string())
    print(f"negative in {int((g_nv < 0).sum().sum())}/{g_nv.size} windows")
    print("\ncombined book D, annualised Sharpe:")
    print(g_d.round(2).to_string())

    # -- outputs ------------------------------------------------------------
    rule("12. artefacts")
    tbl.to_csv(CACHE / "usd_fomc_nvfade_books.csv")
    inst_tbl.to_csv(CACHE / "usd_fomc_nvfade_instruments.csv")
    log = D[["opened_at", "closed_at", "speaker", "role", "is_voter", "era", "symbol",
             "structure", "direction", "flip", "bucket", "days_to_fomc",
             "timestamp_source", "d_rate_bp", "pnl_bp"]].copy()
    log["cum_bp"] = log.pnl_bp.cumsum()
    log.to_csv(CACHE / "usd_fomc_nvfade_trades_D.csv", index=False)
    pd.Series({"config": json.dumps(BOOKS[COMB], default=str),
               **{k: (round(float(v), 4) if isinstance(v, (int, float, np.floating))
                      else str(v)) for k, v in G.summarize(D).items()}}
              ).to_frame("value").to_csv(CACHE / "usd_fomc_nvfade_D_summary.csv")

    fig, axes = plt.subplots(2, 1, figsize=(15, 9), gridspec_kw={"height_ratios": [2, 1]})
    ax = axes[0]
    for nm, df, col, lw in [("A  voters only (the notebook)", A, "darkslateblue", 2.0),
                            ("C  non-voters, FADED", C, "seagreen", 1.5),
                            ("D  voters + non-voters FADED", D, "crimson", 2.0),
                            ("E  everyone, as read", E, "grey", 1.2),
                            ("B  non-voters, as read", B, "indianred", 1.0)]:
        if not df.empty:
            ax.plot(df.opened_at.values, df.pnl_bp.cumsum().values, lw=lw, color=col,
                    label=f"{nm}  ({len(df)}t, {df.pnl_bp.sum():+.0f}bp)")
    ax.axhline(0, color="k", lw=.6)
    ax.legend(fontsize=9)
    ax.grid(alpha=.3)
    ax.set_ylabel("cumulative bp per unit gross risk")
    sD = G.summarize(D)
    ax.set_title(
        "Intraday FED Speaker Strategy - Rec before Doves / Pay before Hawks for VOTERS,\n"
        "the OPPOSITE for non-voting Presidents - no trades within 10d of a meeting\n"
        f"D: {sD['trades']} trades | PnL {sD['total']:.1f}bp | avg {sD['avg']:.3f} | "
        f"hit {sD['hit_rate']:.2%} | Sharpe {sD['sharpe']:.3f} | t {sD['t_stat']:.3f} | "
        f"maxDD {sD['max_dd']:.1f}", fontsize=11, pad=10)
    ax = axes[1]
    span = D.opened_at.max() - D.opened_at.min()
    w = span / min(len(D), 400)
    ax.bar(D.opened_at.values, D.pnl_bp.values, width=w, alpha=.75,
           color=["seagreen" if v > 0 else "indianred" for v in D.pnl_bp])
    ax.axhline(0, color="k", lw=.6)
    ax.set_ylabel("per-trade bp (D)")
    ax.grid(alpha=.3)
    plt.tight_layout()
    png = CACHE / "usd_fomc_nvfade.png"
    plt.savefig(png, dpi=110)
    print(f"wrote {CACHE / 'usd_fomc_nvfade_books.csv'}")
    print(f"wrote {CACHE / 'usd_fomc_nvfade_instruments.csv'}")
    print(f"wrote {CACHE / 'usd_fomc_nvfade_trades_D.csv'}")
    print(f"wrote {png}")

    # -- what the search cost ----------------------------------------------
    rule("13. what this run cost in trials")
    print(f"configurations priced here: {len(BOOKS) + 3 * len(inst_tbl) + 2 * 25}")
    print("The sign flip is not a free hypothesis: B was already on the notebook's")
    print("filter table, so C is that same number read with a minus in front of it.")
    print("Treat D as one more trial on an examined book, not as a discovery.")


if __name__ == "__main__":
    main()
