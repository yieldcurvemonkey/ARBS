"""Run the global (Fed/ECB/BOE/BOJ) intraday hawk-dove backtest end to end.

The notebook imports the same functions; this script exists so the pipeline can
be debugged and re-run headless, and so the expensive stages (calendar fetch,
data gate, backtest) can be cached to disk and reused by the notebook.

    python global_hawk_dove_run.py --stage all
"""

from __future__ import annotations

import argparse
import datetime
import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

import global_hawk_dove_common as G

HERE = Path(__file__).parent
CACHE = HERE / "_global_cache"
CACHE.mkdir(exist_ok=True)

SCORES_CSV = r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\global_hawk_dove_scores.csv"

# ----------------------------- config -----------------------------
BT_START = "2021-01-01"
BT_END = "2026-08-07"
SCORE_METRIC = "trailing_5_avg"
ENTRY_OFFSET = datetime.timedelta(minutes=-45)   # T-45m
EXIT_OFFSET = datetime.timedelta(minutes=180)    # T+180m
BASE_BPV = 100_000.0
CONTRACT_RANK = 3            # 3rd quarterly == the Fed notebook's IMM_3xIMM_4
BLACKOUT_BD = 1
MAX_STALENESS_MIN = 45
BANKS = ["FED", "ECB", "BOE", "BOJ"]


def _p(*a):
    print(*a, flush=True)


def stage_events(bucket_mode: str = "percentile") -> dict:
    """Calendar fetch + score join + filters + data gate. Cached to disk."""
    scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")

    # The gate calls barchart_timeseries_api directly, which does NOT go through
    # the MDP's layered disk cache - so without this every re-run re-fetches every
    # symbol-day from the network and eventually gets throttled to ~20s/request.
    n = G.load_bar_cache(CACHE / "bars.pkl")
    _p(f"bar cache: {n} symbol-days preloaded")

    out: dict = {}
    for bank in BANKS:
        cfg = G.CB_CONFIGS[bank]
        _p("\n" + "=" * 92)
        _p(f"{bank} — {cfg.label}   root={cfg.root}  tz={cfg.market_tz}")
        _p("=" * 92)

        raw = G.fetch_events(cfg, BT_START, BT_END)
        _p(f"  ForexFactory events: {len(raw)}")

        lookup = G.ScoreLookup(scores, bank, SCORE_METRIC)
        if bucket_mode == "absolute":
            bucket_fn = lambda _s, x, _d: G.absolute_bucket(x)  # noqa: E731
        else:
            bucket_fn = G.make_percentile_bucketer(scores, bank, SCORE_METRIC)
        blackout_fn = G.make_blackout_fn(cfg, BLACKOUT_BD)
        _p(f"  scored speakers: {len(lookup.speakers())}  "
           f"policy dates: {len(G.decision_dates(cfg))}")

        events, excl = G.build_trade_events(
            cfg, raw, lookup,
            entry_offset=ENTRY_OFFSET, exit_offset=EXIT_OFFSET,
            base_bpv=BASE_BPV, contract_rank=CONTRACT_RANK,
            bucket_fn=bucket_fn, blackout_fn=blackout_fn,
        )
        _p(f"  after filters: {len(events)}")
        for k, v in sorted(excl.items(), key=lambda x: -x[1]):
            _p(f"      excluded {k}: {v}")

        events, n_overlap = G.drop_overlaps(events)
        _p(f"  after overlap rule: {len(events)}  (dropped {n_overlap})")

        gated, reasons, diag = G.gate_events(
            events, cfg, mdp, max_staleness_min=MAX_STALENESS_MIN
        )
        _p(f"  after DATA GATE: {len(gated)}")
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            _p(f"      gated {k}: {v}")

        # the overlap rule must be re-applied: gating removed events, which can
        # free up windows, but it can never create an overlap, so this is a
        # no-op safety check rather than a second filter.
        gated, n2 = G.drop_overlaps(gated)
        if n2:
            _p(f"  post-gate overlap drop: {n2}")

        out[bank] = {"events": gated, "excluded": excl, "gate_reasons": reasons,
                     "diag": diag, "n_raw": len(raw)}

    fname = "events.pkl" if bucket_mode == "percentile" else f"events_{bucket_mode}.pkl"
    with open(CACHE / fname, "wb") as f:
        pickle.dump(out, f)
    n = G.save_bar_cache(CACHE / "bars.pkl")
    _p(f"\nwrote {CACHE / fname}   (bar cache: {n} symbol-days)")
    return out


def stage_backtest(events_by_bank: dict) -> dict:
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    closed_by_bank: dict = {}
    for bank in BANKS:
        evs = events_by_bank[bank]["events"]
        _p(f"\n=== BACKTEST {bank}: {len(evs)} events ===")
        if not evs:
            _p("  no tradeable events — skipped")
            closed_by_bank[bank] = pd.DataFrame()
            continue
        closed = G.run_backtest(evs, mdp, name=f"hawkdove_{bank}")
        _p(f"  closed trades: {len(closed)}")
        closed_by_bank[bank] = closed

    with open(CACHE / "closed.pkl", "wb") as f:
        pickle.dump(closed_by_bank, f)
    _p(f"\nwrote {CACHE / 'closed.pkl'}")
    return closed_by_bank


def stage_prewarm(events_by_bank: dict, ranks=(1, 2, 3, 4, 5)) -> None:
    """Fetch minute bars for every contract rank the notebook's sweeps will touch.

    The notebook cannot do this itself: inside a Jupyter kernel the Barchart
    fetcher hits an already-running event loop and returns a coroutine, so every
    NEW symbol-day comes back empty. The entry/exit sweep is safe (it re-uses the
    baseline symbols) but the contract sweep asks for ranks 1,2,4,5 which have
    never been fetched - and would otherwise be silently computed from no data.
    """
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    n0 = G.load_bar_cache(CACHE / "bars.pkl")
    _p(f"bar cache: {n0} symbol-days preloaded")

    for bank in BANKS:
        evs = events_by_bank[bank]["events"]
        if not evs:
            continue
        cfg = G.CB_CONFIGS[bank]
        for rank in ranks:
            if rank == CONTRACT_RANK:
                continue  # already cached by the gate
            variant = G.rebuild_with_contract(evs, cfg, rank)
            before = len(G._BAR_CACHE)
            _p(f"  {bank} rank {rank}: {len(variant)} events ...")
            G.gate_events(variant, cfg, mdp, max_staleness_min=MAX_STALENESS_MIN,
                          show_progress=True)
            _p(f"    +{len(G._BAR_CACHE) - before} symbol-days")

    n = G.save_bar_cache(CACHE / "bars.pkl")
    _p(f"\nbar cache now {n} symbol-days ({n - n0} added)")
    if G.FETCH_FAILURES:
        _p(f"  WARNING: {len(G.FETCH_FAILURES)} fetches FAILED (not empty days)")
        for k, v in list(G.FETCH_FAILURES.items())[:5]:
            _p(f"    {k}: {v}")


def verify_directions(events_by_bank: dict, closed_by_bank: dict) -> None:
    """Independent end-to-end check that hawk really sells and dove really buys.

    The toy probe proved the ENCODING; this proves the PIPELINE. For every closed
    trade, reconcile the engine's P&L against the bar prices the gate recorded:

        pnl_bp  ==  side * (exit_px - entry_px) / 0.01

    A hawk (side=-1) must LOSE when the price rises. If the sign convention were
    inverted anywhere between the query and the position handler, every row here
    would fail, and it would be invisible in the headline Sharpe.
    """
    _p("\n" + "=" * 92)
    _p("DIRECTION CHECK — engine P&L vs the gated bar prices")
    _p("=" * 92)

    for bank, cl in closed_by_bank.items():
        if cl is None or cl.empty:
            continue
        evs = {e["tag"]: e for e in events_by_bank[bank]["events"]}
        rows = []
        for _, r in cl.iterrows():
            tag = next(iter(r["source_query"].tags), None)
            ev = evs.get(tag)
            if ev is None or "entry_bar_px" not in ev:
                continue
            expected = ev["side"] * (ev["exit_bar_px"] - ev["entry_bar_px"]) / 0.01
            rows.append({"tag": tag, "side": ev["side"], "expected_bp": expected,
                         "actual_bp": r["pnl_bp"],
                         "d_px": ev["exit_bar_px"] - ev["entry_bar_px"]})
        if not rows:
            continue
        chk = pd.DataFrame(rows)
        # integer contract rounding means bpv is approximate, so compare the SIGN
        # exactly and the magnitude to a tolerance.
        nonzero = chk[chk["d_px"].abs() > 1e-12]
        sign_ok = int((np.sign(nonzero["expected_bp"]) == np.sign(nonzero["actual_bp"])).sum())
        rel = ((chk["actual_bp"] - chk["expected_bp"]).abs()
               / chk["expected_bp"].abs().clip(lower=1e-9))
        _p(f"  {bank}: {len(chk)} reconciled | sign matches {sign_ok}/{len(nonzero)} "
           f"| median |rel err| {rel.median():.4f} | max {rel.max():.4f}")
        bad = nonzero[np.sign(nonzero["expected_bp"]) != np.sign(nonzero["actual_bp"])]
        if len(bad):
            _p(f"    ** {len(bad)} SIGN MISMATCHES **")
            _p(bad.head(5).to_string(index=False))

        # And the directional sanity statement in plain terms.
        hawks = chk[chk.side < 0]
        doves = chk[chk.side > 0]
        for lbl, sub in [("hawk (side=-1, SELL)", hawks), ("dove (side=+1, BUY)", doves)]:
            if sub.empty:
                continue
            up = sub[sub.d_px > 0]
            if len(up):
                _p(f"    {lbl}: on {len(up)} price-UP trades, "
                   f"{(up['actual_bp'] < 0).mean():.0%} lost money "
                   f"({'correct' if lbl.startswith('hawk') else 'should be 0%'})")


def report(closed_by_bank: dict) -> None:
    _p("\n" + "=" * 92)
    _p("RESULTS — P&L expressed in bp of favourable move (realized_pnl / bpv),")
    _p("which is the only unit in which USD, EUR and GBP trades can be pooled.")
    _p("=" * 92)

    rows = []
    for bank, cl in closed_by_bank.items():
        if cl is None or cl.empty:
            rows.append({"bank": bank, "trades": 0})
            continue
        s = G.summarize(cl)
        s["bank"] = bank
        s["local_ccy_pnl"] = cl["realized_pnl"].sum()
        s["ccy"] = cl["ccy"].iloc[0]
        rows.append(s)

    df = pd.DataFrame(rows)
    cols = ["bank", "ccy", "trades", "total", "avg", "hit_rate", "sharpe",
            "t_stat", "max_dd", "local_ccy_pnl", "first", "last"]
    _p(df[[c for c in cols if c in df.columns]].to_string(index=False))

    pooled = pd.concat([c for c in closed_by_bank.values()
                        if c is not None and not c.empty], ignore_index=True)
    if not pooled.empty:
        pooled = pooled.sort_values("opened_at").reset_index(drop=True)
        s = G.summarize(pooled)
        _p("\n--- POOLED (all banks, bp per unit risk) ---")
        for k, v in s.items():
            _p(f"  {k:16s} {v}")

        perm = G.sign_flip_permutation(pooled)
        _p(f"\n  permutation p-value (pooled): {perm['p_value']:.4f}  "
           f"realized SR {perm['realized_sharpe']:.3f} vs null "
           f"{perm['perm_mean']:.3f}±{perm['perm_std']:.3f}")

        _p("\n--- hawk vs dove (pooled) ---")
        for lbl, sub in pooled.groupby("direction"):
            _p(f"  {lbl:20s} n={len(sub):4d} total={sub['pnl_bp'].sum():+8.2f}bp "
               f"avg={sub['pnl_bp'].mean():+6.3f}bp hit={sub['profitable'].mean():.1%}")

        pooled.to_csv(CACHE / "pooled_trades.csv", index=False)
        _p(f"\nwrote {CACHE / 'pooled_trades.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["events", "backtest", "report", "prewarm", "all"])
    ap.add_argument("--bucket", default="percentile",
                    choices=["percentile", "absolute"])
    args = ap.parse_args()

    fname = "events.pkl" if args.bucket == "percentile" else f"events_{args.bucket}.pkl"
    if args.stage in ("events", "all"):
        ev = stage_events(args.bucket)
    else:
        with open(CACHE / fname, "rb") as f:
            ev = pickle.load(f)

    if args.stage == "events":
        return

    if args.stage == "prewarm":
        stage_prewarm(ev)
        return

    if args.stage in ("backtest", "all"):
        cl = stage_backtest(ev)
    else:
        with open(CACHE / "closed.pkl", "rb") as f:
            cl = pickle.load(f)

    verify_directions(ev, cl)
    report(cl)


if __name__ == "__main__":
    main()
