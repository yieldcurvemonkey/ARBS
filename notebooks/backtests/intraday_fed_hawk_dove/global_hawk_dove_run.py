"""Run the global central-bank speaker hawk/dove backtest end to end.

Six legs, each trading its own front-end STIR future on rateslib STIRFuture
objects through the existing QueryDrivenBacktest pattern:

    FED  SR3  3M SOFR      (CME)        barchart
    ECB  IM   3M EURIBOR   (ICE)        barchart   + Norges / Riksbank speakers
    BOE  J8   3M SONIA     (ICE)        barchart
    BOJ  T0   3M TONA                   RECONSTRUCTED from the Citi Velocity curve
    BOC  RG   3M CORRA     (MX)         barchart
    SNB  J2   3M SARON     (Eurex)      barchart

    python global_hawk_dove_run.py --stage all --bucket peer
"""

from __future__ import annotations

import argparse
import datetime
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
STANCES_JSON = HERE / "research_stances.json"

BT_START = "2021-01-01"
BT_END = "2026-08-07"
SCORE_METRIC = "trailing_5_avg"
ENTRY_OFFSET = datetime.timedelta(minutes=-45)
EXIT_OFFSET = datetime.timedelta(minutes=180)
BASE_BPV = 100_000.0
CONTRACT_RANK = 3
BLACKOUT_BD = 1
MAX_STALENESS_MIN = 45
BANKS = ["FED", "ECB", "BOE", "BOJ", "BOC", "SNB"]


def _p(*a):
    print(*a, flush=True)


def make_bucketer_factory(scores: pd.DataFrame, mode: str):
    """mode -> (bank -> bucket_fn). One place so every stage agrees."""
    stances = G.load_researched_stances(STANCES_JSON) if mode in ("researched", "blended") else {}
    if mode in ("researched", "blended") and not stances:
        raise SystemExit(
            f"--bucket {mode} needs {STANCES_JSON.name}; run the research workflow first.")

    def factory(bank: str):
        if mode == "absolute":
            return lambda _s, x, _d: G.absolute_bucket(x)
        if mode == "percentile":
            return G.make_percentile_bucketer(scores, bank, SCORE_METRIC)
        if mode == "peer":
            return G.make_peer_relative_bucketer(
                scores, bank, SCORE_METRIC,
                fallback=G.make_percentile_bucketer(scores, bank, SCORE_METRIC))
        if mode == "researched":
            return G.make_researched_bucketer(stances, bank)
        if mode == "blended":
            return G.make_blended_bucketer(
                G.make_peer_relative_bucketer(
                    scores, bank, SCORE_METRIC,
                    fallback=G.make_percentile_bucketer(scores, bank, SCORE_METRIC)),
                G.make_researched_bucketer(stances, bank))
        raise ValueError(mode)

    return factory


def stage_events(bucket_mode: str, legs) -> dict:
    scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)
    barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
    n0 = G.load_bar_cache(CACHE / "bars.pkl")
    _p(f"bar cache: {n0} symbol-days preloaded")
    factory = make_bucketer_factory(scores, bucket_mode)

    out: dict = {}
    for bank in legs:
        cfg = G.CB_CONFIGS[bank]
        _p("\n" + "=" * 92)
        _p(f"{bank} — {cfg.label}   root={cfg.root} src={cfg.source} "
           f"ccy={cfg.ccy} tz={cfg.market_tz}  speakers from {cfg.banks}")
        _p("=" * 92)

        events, funnel = G.build_leg_events(
            cfg, scores, start=BT_START, end=BT_END,
            entry_offset=ENTRY_OFFSET, exit_offset=EXIT_OFFSET,
            base_bpv=BASE_BPV, contract_rank=CONTRACT_RANK,
            bucketer_factory=factory, blackout_bd=BLACKOUT_BD,
        )
        _p(f"  forexfactory rows={funnel['n_forexfactory_rows']}  "
           f"timed={funnel['n_timed']}  synthetic={funnel['n_synthetic']}")
        for k, v in sorted(funnel["forexfactory"].items(), key=lambda x: -x[1]):
            _p(f"      ff-excluded {k}: {v}")
        for k, v in sorted(funnel["synthetic"].items(), key=lambda x: -x[1]):
            _p(f"      syn-excluded {k}: {v}")

        events, n_ovl = G.drop_overlaps(events)
        _p(f"  after overlap rule: {len(events)}  (dropped {n_ovl})")

        gated, reasons, diag = G.gate(
            events, cfg, barchart, max_staleness_min=MAX_STALENESS_MIN)
        _p(f"  after DATA GATE: {len(gated)}")
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            _p(f"      gated {k}: {v}")
        if gated:
            ns = sum(1 for e in gated if e.get("timestamp_source") == "synthetic")
            _p(f"      of which synthetic-timestamp: {ns}  timed: {len(gated) - ns}")

        gated, _ = G.drop_overlaps(gated)
        out[bank] = {"events": gated, "funnel": funnel, "gate_reasons": reasons,
                     "diag": diag, "n_raw": funnel["n_forexfactory_rows"]}

    fname = "events.pkl" if bucket_mode == "peer" else f"events_{bucket_mode}.pkl"
    # MERGE rather than replace: running --legs BOJ must not silently reduce the
    # cached universe to one leg and invalidate every downstream stage.
    path = CACHE / fname
    if path.exists() and set(legs) != set(BANKS):
        try:
            with open(path, "rb") as f:
                prev = pickle.load(f)
            prev.update(out)
            out = prev
            _p(f"  merged into existing {fname} (legs now {sorted(out)})")
        except Exception:  # noqa: BLE001
            pass
    with open(path, "wb") as f:
        pickle.dump(out, f)
    n = G.save_bar_cache(CACHE / "bars.pkl")
    _p(f"\nwrote {CACHE / fname}   (bar cache: {n} symbol-days)")
    if G.FETCH_FAILURES:
        _p(f"  WARNING: {len(G.FETCH_FAILURES)} bar fetches FAILED (not empty days)")
    return out


def stage_prewarm(events_by_bank: dict, legs, ranks=(1, 2, 3, 4, 5)) -> None:
    """Warm every symbol-day the notebook's sweeps will ask for.

    A Jupyter kernel cannot fetch: the Barchart fetcher hits the live event loop
    and raises, and an empty frame is indistinguishable from a quiet day.
    """
    barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
    n0 = G.load_bar_cache(CACHE / "bars.pkl")
    _p(f"bar cache: {n0} symbol-days preloaded")

    for bank in legs:
        cfg = G.CB_CONFIGS[bank]
        if cfg.source != "barchart":
            continue
        evs = events_by_bank.get(bank, {}).get("events") or []
        if not evs:
            continue
        for rank in ranks:
            if rank == CONTRACT_RANK:
                continue
            variant = G.rebuild_with_contract(evs, cfg, rank)
            before = len(G._BAR_CACHE)
            _p(f"  {bank} rank {rank}: {len(variant)} events ...")
            G.gate_events(variant, cfg, barchart,
                          max_staleness_min=MAX_STALENESS_MIN, show_progress=True)
            _p(f"    +{len(G._BAR_CACHE) - before} symbol-days")

    n = G.save_bar_cache(CACHE / "bars.pkl")
    _p(f"\nbar cache now {n} symbol-days ({n - n0} added)")
    if G.FETCH_FAILURES:
        _p(f"  WARNING: {len(G.FETCH_FAILURES)} fetches FAILED")


def stage_backtest(events_by_bank: dict, legs) -> dict:
    barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
    closed: dict = {}
    for bank in legs:
        cfg = G.CB_CONFIGS[bank]
        evs = events_by_bank.get(bank, {}).get("events") or []
        _p(f"\n=== BACKTEST {bank}: {len(evs)} events ({cfg.source}) ===")
        if not evs:
            closed[bank] = pd.DataFrame()
            continue
        mdp = G.mdp_for_config(cfg, barchart)
        closed[bank] = G.run_backtest(evs, mdp, name=f"hawkdove_{bank}")
        _p(f"  closed trades: {len(closed[bank])}")

    # MERGE rather than replace, for the same reason stage_events does: running
    # --legs BOJ must not reduce the cached results to one leg and quietly
    # invalidate the pooled report.
    path = CACHE / "closed.pkl"
    if path.exists() and set(legs) != set(BANKS):
        try:
            with open(path, "rb") as f:
                prev = pickle.load(f)
            prev.update(closed)
            closed = prev
            _p(f"  merged into existing closed.pkl (legs now {sorted(closed)})")
        except Exception:  # noqa: BLE001
            pass
    with open(path, "wb") as f:
        pickle.dump(closed, f)
    _p(f"\nwrote {path}")
    return closed


def verify_directions(events_by_bank: dict, closed_by_bank: dict) -> None:
    """Hawk must SELL. Reconcile engine P&L against the gate's own marks."""
    _p("\n" + "=" * 92)
    _p("DIRECTION CHECK")
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
            rows.append({"side": ev["side"],
                         "d_px": ev["exit_bar_px"] - ev["entry_bar_px"],
                         "pnl_bp": r["pnl_bp"]})
        if not rows:
            continue
        d = pd.DataFrame(rows)
        up = d[d.d_px > 0]
        if up.empty:
            continue
        hawk = up[up.side < 0]
        dove = up[up.side > 0]
        _p(f"  {bank}: on price-UP trades  hawk/short lost "
           f"{(hawk.pnl_bp < 0).mean() if len(hawk) else float('nan'):.0%} (n={len(hawk)}), "
           f"dove/long lost {(dove.pnl_bp < 0).mean() if len(dove) else float('nan'):.0%} "
           f"(n={len(dove)})")


def report(closed_by_bank: dict) -> None:
    _p("\n" + "=" * 92)
    _p("RESULTS — bp per unit of risk (realized_pnl / bpv)")
    _p("=" * 92)
    rows = []
    for bank, cl in closed_by_bank.items():
        if cl is None or cl.empty:
            rows.append({"bank": bank, "trades": 0})
            continue
        s = G.summarize(cl)
        s["bank"] = bank
        s["ccy"] = cl["ccy"].iloc[0]
        s["local_pnl"] = cl["realized_pnl"].sum()
        rows.append(s)
    df = pd.DataFrame(rows)
    cols = ["bank", "ccy", "trades", "total", "avg", "hit_rate", "sharpe",
            "t_stat", "max_dd", "local_pnl"]
    _p(df[[c for c in cols if c in df.columns]].round(4).to_string(index=False))

    frames = [c for c in closed_by_bank.values() if c is not None and not c.empty]
    if not frames:
        return
    pooled = pd.concat(frames, ignore_index=True).sort_values("opened_at").reset_index(drop=True)
    s = G.summarize(pooled)
    _p("\n--- POOLED ---")
    for k, v in s.items():
        _p(f"  {k:16s} {v}")
    perm = G.sign_flip_permutation(pooled)
    _p(f"\n  permutation p={perm['p_value']:.4f}  realized SR {perm['realized_sharpe']:.3f} "
       f"vs null {perm['perm_mean']:.3f}+-{perm['perm_std']:.3f}")

    if "timestamp_source" in pooled.columns:
        _p("\n--- by timestamp provenance ---")
        for src, sub in pooled.groupby("timestamp_source"):
            ss = G.summarize(sub)
            _p(f"  {src:14s} n={ss['trades']:4d} total={ss['total']:+8.2f}bp "
               f"avg={ss['avg']:+.4f} SR={ss['sharpe']:+.2f}")

    _p("\n--- hawk vs dove ---")
    for lbl, sub in pooled.groupby("direction"):
        _p(f"  {lbl:20s} n={len(sub):4d} total={sub['pnl_bp'].sum():+8.2f}bp "
           f"avg={sub['pnl_bp'].mean():+.4f}bp hit={sub['profitable'].mean():.1%}")

    pooled.to_csv(CACHE / "pooled_trades.csv", index=False)
    _p(f"\nwrote {CACHE / 'pooled_trades.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["events", "prewarm", "backtest", "report", "all"])
    ap.add_argument("--bucket", default="peer",
                    choices=["peer", "percentile", "researched", "blended", "absolute"])
    ap.add_argument("--legs", default=",".join(BANKS))
    args = ap.parse_args()
    legs = [x.strip().upper() for x in args.legs.split(",") if x.strip()]

    fname = "events.pkl" if args.bucket == "peer" else f"events_{args.bucket}.pkl"
    if args.stage in ("events", "all"):
        ev = stage_events(args.bucket, legs)
    else:
        with open(CACHE / fname, "rb") as f:
            ev = pickle.load(f)

    if args.stage == "events":
        return
    if args.stage == "prewarm":
        stage_prewarm(ev, legs)
        return

    if args.stage in ("backtest", "all"):
        cl = stage_backtest(ev, legs)
    else:
        with open(CACHE / "closed.pkl", "rb") as f:
            cl = pickle.load(f)

    verify_directions(ev, cl)
    report(cl)


if __name__ == "__main__":
    main()
