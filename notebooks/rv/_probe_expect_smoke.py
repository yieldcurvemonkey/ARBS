"""Smoke test the expected-sentiment stack end to end on a small rotation budget.

Runs the SR3 sample with a deliberately tiny null so wiring errors surface in
seconds rather than after a full grid.  Prints every intermediate shape.
"""
from __future__ import annotations

import io
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fed_expected_sentiment as E  # noqa: E402
import fed_expected_sentiment_run as R  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)


def line(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78, flush=True)


line("0. config + derived lags")
print(E.PRIMARY.describe().to_string(index=False))
print("\nlags() over the (lead, horizon) plane -- (near, far):")
import dataclasses  # noqa: E402
rows = []
for lw in E.LEADS_W:
    for h in E.HORIZONS_W:
        c = dataclasses.replace(E.PRIMARY, lead_w=lw, horizon_w=h)
        rows.append({"lead_w": lw, "horizon_w": h, "near": c.lags()[0],
                     "far": c.lags()[1]})
print(pd.DataFrame(rows).pivot(index="lead_w", columns="horizon_w",
                               values=["near", "far"]).to_string())

line("1. composite")
zc, prov = E.load_composite()
print(zc.dropna().shape, zc.dropna().index.min(), zc.dropna().index.max())
print({k: v for k, v in prov.items() if k in ("source", "built", "weeks", "legs")})

line("2. signals")
for r in ("level", "chg"):
    for lw in E.LEADS_W:
        c = dataclasses.replace(E.PRIMARY, reading=r, lead_w=lw)
        s = E.build_signal(zc, c)
        print(f"  {r:6s} L={lw:2d} h={c.horizon_w}  lags{c.lags()}  n={len(s):4d}  "
              f"{s.index.min().date()}..{s.index.max().date()}  "
              f"mean {s.mean():+.3f} sd {s.std():.3f}")

line("3. G-X1 trailing gate")
probes = list(zc.dropna().index[-400::40])
for r in ("level", "chg"):
    c = dataclasses.replace(E.PRIMARY, reading=r)
    g = E.gate_trailing_signal(zc, c, probe_dates=probes)
    print(f"  {r}: {len(g)} probes, worst |diff| {g['abs_diff'].max():.3e}")

line("4. SR3 sample, tiny null")
res = R.run_sample(label="SR3-smoke", structures=("out2", "out3"),
                   readings=("level", "chg"), leads=(0, 5),
                   thresholds=(0.0, 1.0), horizons=(1, 4),
                   rotation_draws=40, show_progress=False,
                   with_family=False, with_deflation=False)
print("support:", len(res["support"]), res["support"][0].date(), res["support"][-1].date())
print("\ncoverage gate:\n", res["coverage_gate"].to_string(index=False))
print("\nroll placebo (rank 3):")
rp = {k: v for k, v in res["roll_placebo"].items() if k != "series"}
for k, v in rp.items():
    print(f"   {k}: {v}")

print("\nPRIMARY discrete:", res["primary"]["discrete_score"])
print("PRIMARY reasons:", res["primary"]["discrete_reasons"])
print("PRIMARY weekly:", res["primary"]["weekly_score"])
print("PRIMARY weekly reasons:", res["primary"]["weekly_reasons"])
print("roll gate discrete:", res["primary"]["roll_gate_discrete"])
print("roll gate weekly:", res["primary"]["roll_gate_weekly"])

print("\nleague head:\n", res["league"].sort_values("sharpe", ascending=False)
      .head(8).to_string(index=False))
print("\nbest:", res["best_sharpe"], res["best_cell"])
print("null:", res["null_summary"])
print("p_rotation:", res["p_rotation"])

line("5. headline")
print(R.headline(res).to_string())

line("6. weekly book sample rows")
bb = res["primary"]["weekly_book"]
print(bb.head(6).to_string(index=False))
print("...")
print(bb.tail(4).to_string(index=False))
print("rolled weeks:", int(bb["rolled"].sum()), "of", len(bb))
print("cost total:", bb["cost_bp"].sum())

print("\nSMOKE OK", flush=True)
