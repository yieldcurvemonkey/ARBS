r"""Known-answer tests for the two new estimators, run BEFORE they touch real data.

A checking tool that is itself wrong reports success and hides the thing it was built
to find. So: the as-of resolver is run against a hand-built tape whose correct answer
is written down, and the Roll estimator is run against a synthetic bid-ask bounce whose
true spread is known by construction. Both are also run against a MUTATION -- a
deliberately broken version -- which must fail, because a test that passes on broken
code is not a test.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance.intraday_panel import asof_marks, roll_spread  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)
    if not ok:
        FAILS.append(name)


# --------------------------------------------------------------- 1. the as-of rule

def test_asof() -> None:
    # A two-day tape with prints placed so every rule has a distinct right answer.
    ts = pd.to_datetime([
        "2026-03-02 09:28", "2026-03-02 09:31",           # 09:30 -> the 09:28 print
        "2026-03-02 14:58", "2026-03-02 15:00",           # 15:00 -> the 15:00 print, 0 stale
        "2026-03-02 15:58",                               # 16:00 -> 15:58, 2 min stale
        "2026-03-02 23:50",                               # day 2's 09:30 must NOT use this
        "2026-03-03 11:05",
    ])
    vals = np.arange(len(ts), dtype=float)
    s = pd.Series(vals, index=ts)
    m = asof_marks(s, ("09:30", "15:00", "16:00", "17:00"), cap_min=240)
    m = m.set_index(["date", "mark_time"])

    d1, d2 = pd.Timestamp("2026-03-02"), pd.Timestamp("2026-03-03")

    check("asof takes the last print AT OR BEFORE, never the next one",
          m.loc[(d1, "09:30"), "value"] == 0.0,
          f"got {m.loc[(d1, '09:30'), 'value']} (09:31 print is 1.0 and must not be used)")
    check("a print exactly AT the mark is used and is 0 minutes stale",
          m.loc[(d1, "15:00"), "value"] == 3.0 and m.loc[(d1, "15:00"), "stale_min"] == 0.0)
    check("staleness is the real gap",
          m.loc[(d1, "16:00"), "stale_min"] == 2.0,
          f"got {m.loc[(d1, '16:00'), 'stale_min']}")
    check("SAME-DAY guard: day 2's 09:30 is absent, not day 1's 23:50",
          (d2, "09:30") not in m.index)
    check("day 2's 15:00 uses day 2's 11:05 print (235 min stale, inside the 240 cap)",
          m.loc[(d2, "15:00"), "value"] == 6.0 and
          abs(m.loc[(d2, "15:00"), "stale_min"] - 235.0) < 1e-9)
    check("the 240-minute cap bites: day 2 has no 17:00 mark (355 min would be needed)",
          (d2, "17:00") not in m.index)

    # MUTATION: a 'nearest' resolver instead of 'backward'. The 09:30 answer must change.
    mut = pd.merge_asof(
        pd.DataFrame({"target_ts": [pd.Timestamp("2026-03-02 09:30")]}),
        pd.DataFrame({"print_ts": ts, "value": vals}),
        left_on="target_ts", right_on="print_ts", direction="nearest")
    check("MUTATION check: a 'nearest' resolver really would give a different answer",
          float(mut["value"].iloc[0]) == 1.0,
          "so the backward test above is discriminating, not vacuous")


# ------------------------------------------------------------------ 2. Roll (1984)

def test_roll() -> None:
    rng = np.random.default_rng(20260820)
    n = 60_000
    p0, sigma_bp, true_s_bp = 100.0, 3.0, 8.0     # efficient-price vol and spread, price bp

    eff = p0 * np.exp(np.cumsum(rng.normal(0, sigma_bp * 1e-4, n)))
    side = rng.choice([-1.0, 1.0], size=n)
    obs = eff * (1.0 + side * (true_s_bp * 1e-4) / 2.0)
    contig = np.ones(n, bool)

    s, cov, npair = roll_spread(obs, contig)
    err = abs(s - true_s_bp) / true_s_bp
    check("Roll recovers a KNOWN synthetic spread within 5%",
          err < 0.05, f"true {true_s_bp:.3f} -> {s:.3f} price bp ({err*100:.2f}% off, "
                      f"cov {cov:.4e}, {npair:,} pairs)")

    # A pure random walk has no bounce: the autocovariance must not be reliably negative.
    walk = p0 * np.exp(np.cumsum(rng.normal(0, sigma_bp * 1e-4, n)))
    s0, cov0, _ = roll_spread(walk, contig)
    check("Roll is NaN or tiny on a spreadless random walk",
          (not np.isfinite(s0)) or s0 < 0.5,
          f"got {s0} (cov {cov0:.4e}) -- a large number here would mean the estimator "
          f"manufactures a spread from volatility")

    # The estimator must SEE the spread level, not just its sign.
    obs2 = eff * (1.0 + side * (2 * true_s_bp * 1e-4) / 2.0)
    s2, _, _ = roll_spread(obs2, contig)
    check("doubling the true spread doubles the estimate",
          abs(s2 / s - 2.0) < 0.05, f"{s:.3f} -> {s2:.3f} price bp (ratio {s2/s:.3f})")

    # MUTATION: ignore the contiguity mask, splice two unrelated sessions together.
    a = p0 * np.exp(np.cumsum(rng.normal(0, sigma_bp * 1e-4, 1000)))
    a = a * (1.0 + rng.choice([-1.0, 1.0], 1000) * (true_s_bp * 1e-4) / 2.0)
    b = a * 1.05                                      # a 5% overnight gap
    spliced = np.concatenate([a, b])
    flag = np.ones(2 * len(a), bool)
    flag[len(a)] = False                              # the gap is NOT contiguous
    s_guard, _, _ = roll_spread(spliced, flag)
    s_naive, _, _ = roll_spread(spliced, np.ones(2 * len(a), bool))
    check("MUTATION check: dropping the contiguity guard changes the answer",
          abs(s_guard - s_naive) > 1e-9,
          f"guarded {s_guard:.3f} vs naive {s_naive:.3f} price bp")


if __name__ == "__main__":
    test_asof()
    print()
    test_roll()
    print()
    print(f"{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
    raise SystemExit(1 if FAILS else 0)
