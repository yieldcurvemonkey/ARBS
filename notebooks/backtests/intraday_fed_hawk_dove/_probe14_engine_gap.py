"""Where the closed form and the engine disagree, and which one is causal.

64 of 783 trades differ by up to 1.00bp. Both read the same minute bars, so the
difference is which BAR each one marks against:

  * the gate takes the last bar at-or-before the timestamp — causal by construction
  * the engine goes through STIRFutureMDP, which has its own resolution

This prints the disagreements with the bars around them, so the answer comes from
the data rather than from an argument about which code path looks more correct.
"""

from __future__ import annotations

import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

import global_hawk_dove_common as G
import hawk_dove_config as HC

HERE = Path(__file__).parent
CACHE = HERE / "_global_cache"


def main() -> None:
    G.load_bar_cache(CACHE / "bars.pkl")
    with open(CACHE / "events_manual_raw.pkl", "rb") as f:
        raw = pickle.load(f)["FED"]["events"]
    with open(CACHE / "closed_manual.pkl", "rb") as f:
        eng = pickle.load(f)["FED"].copy()
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")

    res = HC.run_config(HC.DEFAULT_CONFIG, raw, mdp)
    eng["tag"] = [next(iter(q.tags), None) for q in eng["source_query"]]
    j = res.closed.merge(
        eng[["tag", "pnl_bp", "opened_at", "closed_at"]].rename(
            columns={"pnl_bp": "engine_bp", "opened_at": "eng_open",
                     "closed_at": "eng_close"}),
        on="tag", how="inner")
    j["diff"] = j.pnl_bp - j.engine_bp
    bad = j[j["diff"].abs() > 1e-9].copy()
    print(f"{len(bad)} of {len(j)} disagree   total closed-form {j.pnl_bp.sum():+.2f}bp "
          f"vs engine {j.engine_bp.sum():+.2f}bp")

    print("\n--- do the two paths even agree on the TIMESTAMPS? ---")
    for c, ec in (("opened_at", "eng_open"), ("closed_at", "eng_close")):
        d = pd.to_datetime(j[c]) - pd.to_datetime(j[ec])
        print(f"  {c}: {(d != pd.Timedelta(0)).sum()} of {len(j)} differ, "
              f"max |gap| {d.abs().max()}")

    print("\n--- disagreements by era and symbol ---")
    print(bad.groupby("era").agg(n=("diff", "size"), mean_diff=("diff", "mean"),
                                 max_abs=("diff", lambda x: x.abs().max())).to_string())
    print(bad.groupby("symbol")["diff"].agg(["size", "mean"]).sort_values(
        "size", ascending=False).head(10).to_string())
    print(f"\n  |diff| distribution: {bad['diff'].abs().value_counts().head(8).to_dict()}")
    print(f"  signed mean {bad['diff'].mean():+.4f}bp — "
          f"{'one-sided, so it is a BIAS' if abs(bad['diff'].mean()) > 0.2 else 'roughly symmetric'}")

    print("\n--- WHICH bar does each path use? ---")
    # Hypothesis: the gate marks strictly at-or-before the timestamp, and the
    # engine's MDP resolves to the NEAREST bar, which can be a LATER one. If that
    # is right, then for every disagreement the engine's P&L is reproduced by some
    # combination of {prior bar, next bar} at entry and exit — and predominantly
    # by the one that uses a future bar. Test it rather than assert it.
    cfgF = G.CB_CONFIGS["FED"]
    filt, _ = HC.apply_filters(raw, HC.DEFAULT_CONFIG["filters"])
    timed, _ = HC.retime(filt, cfgF, -45, 180, False)
    gated, _r, _d = G.gate_events(G.rebuild_with_contract(timed, cfgF, 3), cfgF,
                                  mdp, max_staleness_min=45, show_progress=False)
    ev_by_tag = {e["tag"]: e for e in gated}

    combo_hits = {}
    unexplained = 0
    for _, r in bad.iterrows():
        ev = ev_by_tag.get(r.tag)
        bars = G._BAR_CACHE.get((ev["symbol"], ev["entry_ts"].date())) if ev else None
        if ev is None or bars is None or bars.empty:
            unexplained += 1
            continue
        idx = bars.index

        def px(ts, mode):
            sel = idx[idx <= ts] if mode == "prior" else idx[idx >= ts]
            if not len(sel):
                return None
            return float(bars.loc[sel.max() if mode == "prior" else sel.min(), "Close"])

        hit = None
        for me in ("prior", "next"):
            for mx in ("prior", "next"):
                pe, pxx = px(ev["entry_ts"], me), px(ev["exit_ts"], mx)
                if pe is None or pxx is None:
                    continue
                if abs(ev["side"] * (pxx - pe) / 0.01 - r.engine_bp) < 1e-6:
                    hit = f"entry={me}, exit={mx}"
                    break
            if hit:
                break
        if hit:
            combo_hits[hit] = combo_hits.get(hit, 0) + 1
        else:
            unexplained += 1
    print(f"  engine P&L reproduced by, out of {len(bad)} disagreements:")
    for k, v in sorted(combo_hits.items(), key=lambda x: -x[1]):
        print(f"    {k:26s} {v}")
    print(f"    unexplained by either bar   {unexplained}")
    print("  (the gate is always entry=prior, exit=prior — that is what causal means)")

    print("\n--- the first few, with the bars around them ---")
    by_tag = {e["tag"]: e for e in res.closed.to_dict("records")}
    ev_by_tag = {}
    for rank in [3]:
        cfg = G.CB_CONFIGS["FED"]
        filt, _ = HC.apply_filters(raw, HC.DEFAULT_CONFIG["filters"])
        timed, _ = HC.retime(filt, cfg, -45, 180, False)
        gated, _r, _d = G.gate_events(G.rebuild_with_contract(timed, cfg, rank), cfg,
                                      mdp, max_staleness_min=45, show_progress=False)
        ev_by_tag = {e["tag"]: e for e in gated}

    for _, r in bad.head(6).iterrows():
        ev = ev_by_tag.get(r.tag)
        if ev is None:
            continue
        bars = G._BAR_CACHE.get((ev["symbol"], ev["entry_ts"].date()))
        print(f"\n  {r.tag}  {ev['symbol']}  {ev['speaker']}  "
              f"diff {r['diff']:+.3f}bp (closed {r.pnl_bp:+.3f} vs engine {r.engine_bp:+.3f})")
        print(f"    entry {ev['entry_ts']}  gate px {ev['entry_bar_px']}")
        print(f"    exit  {ev['exit_ts']}  gate px {ev['exit_bar_px']}")
        if bars is not None and len(bars):
            for label, ts in (("entry", ev["entry_ts"]), ("exit", ev["exit_ts"])):
                idx = bars.index
                near = bars.loc[(idx >= ts - pd.Timedelta(minutes=3)) &
                                (idx <= ts + pd.Timedelta(minutes=3)), "Close"]
                print(f"    bars around {label}: "
                      + ", ".join(f"{t.strftime('%H:%M')}={v}" for t, v in near.items()))


if __name__ == "__main__":
    main()
