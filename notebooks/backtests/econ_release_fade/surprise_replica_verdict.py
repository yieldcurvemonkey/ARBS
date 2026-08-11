"""What the 40 placebo replicas say about the consensus-surprise strategy.

Reads the replica CSVs and runs the comparisons that survive scrutiny, plus one
that does not -- included because it looks like the strongest result in the
study and is not, and leaving it out would invite someone to rediscover it and
believe it.

The three questions, in increasing order of how much they can be trusted.

**Max against max** is the honest headline for a grid search. Both grids get to
pick their own best cell, so selection is charged to both sides. It is also very
noisy: a maximum over 3,264 cells is an extreme order statistic and its sampling
distribution is wide, which is why it can fail to separate books that clearly
differ on average.

**Rate of high-hit cells** is the same comparison with the noise taken out.
Instead of "is real's single best cell better than the placebo's single best
cell", it asks "does the real grid PRODUCE cells above 0.85 at a higher rate".
That is a property of the whole distribution, no cell is selected, and it is the
test this conclusion rests on. It is reported for all cells and again inside the
30-45 trade band, because every real cell above 0.85 has 32-41 trades and a high
hit rate is cheaper on a thin sample -- the any-day control happens to match the
real trade distribution almost exactly (41.0% thin against 42.5%), which is what
makes that conditioning credible rather than decorative.

**The winning cell against its own placebo twins** fixes one configuration and
asks whether it works on release days and not on other days. It returns 0 of 19
on both hit rate and P&L and is the most impressive number here. It is also
BIASED, and not slightly: the configuration was chosen because it was the real
grid's maximum, and the placebos are then scored at that same configuration
rather than at their own best. Selection is charged to one side only. It is
reported as an illustration of what the trade looks like, never as evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent))

import numpy as np
import pandas as pd

import econ_fade_common as G

pd.set_option("display.width", 220)

MIN_TRADES = 30
THIN = (30, 45)
HIT_THRESHOLDS = (0.80, 0.85, 0.87)
VARIANTS = ("clean", "any-day")


def _load(name: str):
    p = G.CACHE / f"surprise_replicas_{name}.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p)
    return d[d["trades"] >= MIN_TRADES]


def _exceed(observed: float, null: np.ndarray) -> float:
    """(1 + #{null >= observed}) / (n + 1) -- never zero, which is the point."""
    return (1 + int((null >= observed).sum())) / (len(null) + 1)


def max_against_max(real, rep, variant):
    g = rep.groupby("shift").agg(best_net=("net_bp", "max"), best_hit=("hit_rate", "max"))
    for col, obs in (("best_net", float(real.net_bp.max())),
                     ("best_hit", float(real.hit_rate.max()))):
        null = g[col].to_numpy()
        print(f"  [{variant:7s}] {col:9s} real {obs:+.4f}  replicas {null.min():+.4f}"
              f"..{null.max():+.4f} (med {np.median(null):+.4f})  "
              f"{int((null >= obs).sum())}/{len(null)} beat  p={_exceed(obs, null):.4f}")


def hit_rate_enrichment(real, rep, variant):
    """The test the conclusion rests on. A rate, not a selected cell."""
    for label, (r, p) in {
        "all": (real, rep),
        f"thin {THIN[0]}-{THIN[1]}": (
            real[real.trades.between(*THIN)], rep[rep.trades.between(*THIN)]),
    }.items():
        for t in HIT_THRESHOLDS:
            obs = float((r.hit_rate >= t).mean()) * 1000
            tot = p.groupby("shift").size()
            per = p[p.hit_rate >= t].groupby("shift").size().reindex(tot.index, fill_value=0)
            null = (per / tot * 1000).to_numpy()
            print(f"  [{variant:7s}] {label:10s} hit>={t:.2f}: real {obs:7.2f}/1000  "
                  f"replica med {np.median(null):6.2f} max {null.max():6.2f}  "
                  f"{int((null >= obs).sum())}/{len(null)} beat  p={_exceed(obs, null):.4f}")


def twin_test(real, variant, configs):
    """BIASED -- see the module docstring. Illustration only."""
    for cfg in configs:
        rv = real[real.config == cfg]
        d = _load(variant)
        if d is None or not len(rv):
            continue
        d = d[d.config == cfg]
        if not len(d):
            continue
        for col in ("hit_rate", "net_bp"):
            obs, null = float(rv[col].iloc[0]), d[col].to_numpy()
            print(f"  [{variant:7s}] {cfg}  {col:9s} real {obs:+.4f} vs twin median "
                  f"{np.median(null):+.4f}  {int((null >= obs).sum())}/{len(null)} beat  "
                  f"p={_exceed(obs, null):.4f}  (BIASED)")


def main():
    real = _load("real")
    if real is None:
        raise SystemExit("no surprise_replicas_real.csv -- run surprise_replicas.py first")
    print(f"real grid: {len(real):,} eligible cells, median {real.trades.median():.0f} trades, "
          f"best net {real.net_bp.max():+.4f}, best hit {real.hit_rate.max():.4f}\n")

    reps = {v: _load(v) for v in VARIANTS}
    reps = {v: d for v, d in reps.items() if d is not None}
    for v, d in reps.items():
        n = d["shift"].nunique()
        thin = float(d.trades.between(*THIN).mean()) * 100
        print(f"{v:8s}: {n} replicas, median {d.trades.median():.0f} trades, "
              f"{thin:.1f}% thin (real {float(real.trades.between(*THIN).mean()) * 100:.1f}%)")

    print("\n=== 1. max against max (honest, noisy) ===")
    for v, d in reps.items():
        max_against_max(real, d, v)

    print("\n=== 2. rate of high-hit cells (the test that carries the conclusion) ===")
    for v, d in reps.items():
        hit_rate_enrichment(real, d, v)

    print("\n=== 3. winning cell vs its own twins -- BIASED, illustration only ===")
    best = real.sort_values("hit_rate", ascending=False).head(2)["config"].tolist()
    for v in reps:
        twin_test(real, v, best)


if __name__ == "__main__":
    main()
