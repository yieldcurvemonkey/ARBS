"""Check the config engine against an answer already known.

A configurable backtest is a checking tool, and a checking tool that is itself
wrong reports success and hides what it was built to find. So before any new
number is believed: run DEFAULT_CONFIG — which is exactly the hand-labelled
study's parameters — from the RAW event book and require it to reproduce the
published run.

Known answers, from `usd_fomc_manual_labels_backtest.ipynb`:
    events after the overlap rule   796
    events after the data gate      788
    closed trades (engine)          783
    window                          2019-01-09 -> 2026-08-07

Then three properties that must hold if the plumbing is right:
    * a filter that excludes nothing must return the baseline book exactly
    * a filter's kept + dropped must equal what went in
    * the direction convention must survive: hawk is SHORT the future, so a
      hawk trade profits when the price falls
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
FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}   {detail}", flush=True)
    if not ok:
        FAILS.append(name)


def main() -> None:
    G.load_bar_cache(CACHE / "bars.pkl")
    with open(CACHE / "events_manual_raw.pkl", "rb") as f:
        raw = pickle.load(f)["FED"]["events"]
    with open(CACHE / "closed_manual.pkl", "rb") as f:
        engine = pickle.load(f)["FED"]
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    print(f"raw events {len(raw)}   engine trades {len(engine)}   "
          f"bar cache {len(G._BAR_CACHE)}")

    print("\n--- DEFAULT_CONFIG must reproduce the published run ---")
    res = HC.run_config(HC.DEFAULT_CONFIG, raw, mdp)
    f_ = res.funnel
    check("no bars missing", f_["n_missing_bars"] == 0, f"{f_['n_missing_bars']}")
    check("overlap rule leaves 796", f_["after_retime_overlap"] == 796,
          f"got {f_['after_retime_overlap']}")
    check("gate leaves 788", len(res.closed) == 788, f"got {len(res.closed)}")
    check("window starts 2019-01-09",
          str(res.closed.opened_at.min().date()) == "2019-01-09",
          str(res.closed.opened_at.min()))
    check("window ends 2026-08-07",
          str(res.closed.opened_at.max().date()) == "2026-08-07",
          str(res.closed.opened_at.max()))

    print("\n--- and must agree with the ENGINE trade by trade ---")
    eng = engine.copy()
    eng["tag"] = [next(iter(q.tags), None) for q in eng["source_query"]]
    j = res.closed.merge(eng[["tag", "pnl_bp"]].rename(columns={"pnl_bp": "engine_bp"}),
                         on="tag", how="inner")
    d = (j["pnl_bp"] - j["engine_bp"]).abs()
    check("every engine trade is matched", len(j) == len(eng), f"{len(j)}/{len(eng)}")
    # NOT equality. 64 of 783 differ by exactly one tick, and _probe14 accounts for
    # all 64: the engine resolves a timestamp to the NEAREST bar, which on those is
    # one that had not printed yet (42 at the exit, 22 at the entry, 0 unexplained).
    # This path is always at-or-before. So the requirement is one tick, unbiased.
    check("P&L within one tick everywhere", bool((d <= 1.0 + 1e-6).all()),
          f"max diff {d.max():.3f}bp, {(d >= 1e-9).sum()} differ")
    check("the tick difference is not a bias",
          abs((j['pnl_bp'] - j['engine_bp']).mean()) < 0.1,
          f"mean {(j['pnl_bp'] - j['engine_bp']).mean():+.4f}bp")
    print(f"    totals: config {j.pnl_bp.sum():+.3f}bp  engine {j.engine_bp.sum():+.3f}bp")
    extra = res.closed[~res.closed.tag.isin(eng.tag)]
    print(f"    {len(extra)} gated events the engine did not book "
          f"(total {extra.pnl_bp.sum():+.3f}bp) — the engine resolves a few to the "
          f"same tick and books nothing")

    print("\n--- filters ---")
    r_all = HC.run_config({"name": "no-op filter", "filters": {"voters": "all"}}, raw, mdp)
    check("a no-op filter changes nothing", len(r_all.closed) == len(res.closed),
          f"{len(r_all.closed)} vs {len(res.closed)}")

    kept, drops = HC.apply_filters(raw, HC.merge({"filters": {"voters": "voters"}})["filters"])
    check("kept + dropped == input", len(kept) + sum(drops.values()) == len(raw),
          f"{len(kept)}+{sum(drops.values())} vs {len(raw)}")

    r_v = HC.run_config({"name": "voters", "filters": {"voters": "voters"}}, raw, mdp)
    r_n = HC.run_config({"name": "nonvoters", "filters": {"voters": "nonvoters"}}, raw, mdp)
    print(f"    voters {len(r_v.closed)} trades, nonvoters {len(r_n.closed)}, "
          f"baseline {len(res.closed)}")
    check("voters + nonvoters <= baseline is FALSE (overlaps re-resolve)",
          len(r_v.closed) + len(r_n.closed) >= len(res.closed),
          f"{len(r_v.closed)}+{len(r_n.closed)} vs {len(res.closed)}")
    # the point of filtering before the overlap rule: a voters-only book trades
    # MORE voter events than a voters-only split of the mixed book does
    post_hoc = res.closed[res.closed.is_voter == True]
    check("filter-first beats post-hoc split on voter count",
          len(r_v.closed) > len(post_hoc), f"{len(r_v.closed)} vs {len(post_hoc)}")

    print("\n--- direction convention ---")
    c = res.closed
    up = c[c.d_rate_bp > 0]           # the structure's RATE rose
    hawk = up[up.bucket > 0]
    dove = up[up.bucket < 0]
    check("hawks profit when rates rise", bool((hawk.pnl_bp > 0).all()),
          f"{(hawk.pnl_bp > 0).mean():.0%} of {len(hawk)}")
    check("doves lose when rates rise", bool((dove.pnl_bp < 0).all()),
          f"{(dove.pnl_bp < 0).mean():.0%} of {len(dove)}")

    print("\n--- instruments ---")
    for spec in [{"kind": "outright", "rank": 1}, {"kind": "outright", "rank": 3},
                 {"structure": "SPR_2_3"}, {"structure": "FLY_2_3_4"},
                 {"structure": "PACK_1"}]:
        try:
            r = HC.run_config({"name": str(spec), "instrument": spec}, raw, mdp)
            print(f"    {str(spec):34s} {len(r.closed):4d} trades  "
                  f"{r.closed.pnl_bp.sum():+8.2f}bp  "
                  f"SR {r.summary.get('sharpe', float('nan')):+.3f}")
        except RuntimeError as e:
            print(f"    {str(spec):34s} COLD CACHE: {str(e).splitlines()[0][:70]}")

    print("\n--- timing knob ---")
    for em, xm in [(-45, 180), (-15, 60), (-120, 240)]:
        r = HC.run_config({"name": f"{em}/{xm}",
                           "timing": {"entry_offset_min": em, "exit_offset_min": xm}},
                          raw, mdp)
        print(f"    T{em:+4d}/T{xm:+4d}  {len(r.closed):4d} trades  "
              f"{r.closed.pnl_bp.sum():+8.2f}bp  "
              f"SR {r.summary.get('sharpe', float('nan')):+.3f}")

    print("\n--- cost and sizing ---")
    r_c = HC.run_config({"name": "cost", "cost_bp": 0.25}, raw, mdp)
    check("cost subtracts exactly cost_bp per trade",
          abs((res.closed.pnl_bp.sum() - r_c.closed.pnl_bp.sum())
              - 0.25 * len(res.closed)) < 1e-6,
          f"{res.closed.pnl_bp.sum() - r_c.closed.pnl_bp.sum():.4f}")
    r_s = HC.run_config({"name": "sized", "sizing": "conviction"}, raw, mdp)
    check("conviction sizing scales by |bucket|",
          bool(np.allclose(r_s.closed.set_index("tag").pnl_bp,
                           (res.closed.set_index("tag").pnl_bp
                            * res.closed.set_index("tag").abs_bucket))),
          "")

    print("\n--- coverage refusal is loud, not silent ---")
    try:
        HC.run_config({"name": "cold", "instrument": {"kind": "outright", "rank": 12}},
                      raw, mdp)
        check("a cold rank raises", False, "it did not")
    except RuntimeError as e:
        check("a cold rank raises", True, str(e).splitlines()[0][:60])

    print("\n" + "=" * 70)
    print(f"{len(FAILS)} FAILURES" if FAILS else "ALL CHECKS PASSED")
    for f in FAILS:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
