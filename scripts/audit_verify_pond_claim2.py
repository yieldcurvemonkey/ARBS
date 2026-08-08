"""AUDIT addendum: (E) effective sample size of the "335 eligible entries" estimator,
(F) does ANY cell clear its round trip on the shock book, (G) the pond's load on the verdict.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import importlib.util
import json
import pathlib

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
spec = importlib.util.spec_from_file_location("g", _REPO / "scripts" / "s3_f7_gate.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 80)

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg_all["file_date"])))

P = {}
for sig in uni:
    x = g.structure_series(par, sig).reindex(common).dropna()
    z = g.zscore(x, g.Z_WIN)
    P[sig] = dict(x=x, z=z,
                  persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                  & (z.shift(1).abs() >= g.Z_ENTRY),
                  rt=g.round_trips(sig))

print("=" * 100)
print("E  EFFECTIVE SAMPLE SIZE of the 'zero cost, 335 samples' estimator (2-5-10, h=21)")
print("=" * 100)
sig, h, lag = "2-5-10", 21, 1
x, z = P[sig]["x"], P[sig]["z"]
ok = P[sig]["persistent"].reindex(x.index).fillna(False).to_numpy()
xv, zv, n = x.to_numpy(), z.to_numpy(), len(x)
idxs, mv = [], []
for i in range(g.Z_WIN, n - lag - h):
    if not ok[i] or np.sign(zv[i]) == 0:
        continue
    idxs.append(i)
    mv.append(abs(xv[i + lag + h] - xv[i + lag]))
idxs, mv = np.array(idxs), np.array(mv)
rt = P[sig]["rt"]["rt_cm2"]
print(f"eligible entries n = {len(idxs)}   pond(all-eligible) = {np.median(mv)/rt:.3f}x")
# how many DISTINCT non-overlapping windows can those entries actually resolve?
busy, k = -1, 0
for i in idxs:
    if i <= busy:
        continue
    k += 1
    busy = i + lag + h
print(f"maximum NON-OVERLAPPING windows those same entries support = {k}")
print(f"-> the 335 'samples' are {len(idxs)/k:.1f} overlapping reads of ~{k} independent moves; "
      f"they are NOT free information.")
# lag-1 autocorrelation of the |move| series over consecutive eligible entries
s = pd.Series(mv)
print(f"autocorr of |move| across consecutive eligible entries: "
      f"lag1 {s.autocorr(1):.3f}  lag5 {s.autocorr(5):.3f}  lag21 {s.autocorr(21):.3f}")
# block bootstrap (moving block, length = h+lag) of the all-eligible median
rng = np.random.default_rng(11)
L = h + lag
nb = int(np.ceil(len(mv) / L))
bs = []
for _ in range(4000):
    starts = rng.integers(0, max(1, len(mv) - L), nb)
    samp = np.concatenate([mv[s0:s0 + L] for s0 in starts])[:len(mv)]
    bs.append(np.median(samp))
bs = np.array(bs) / rt
print(f"MOVING-BLOCK bootstrap (block = h+lag = {L}) of the ALL-ELIGIBLE pond: "
      f"point {np.median(mv)/rt:.3f}  p05 {np.percentile(bs,5):.3f}  p95 {np.percentile(bs,95):.3f}")
print("   -> the 'better' estimator's own honest CI also straddles 1.0x.")

print()
print("=" * 100)
print("F  does ANY cell clear its round trip on the book the claim is about?")
print("=" * 100)
gate = pd.read_parquet(OUT / "f7_gate.parquet")
c = gate[gate["book"].isin(["all", "shock", "noshock"])].copy()
c["gross_over_rt"] = (c["gross_med"] / c["rt_cm2"]).round(3)
c["netmean_1x"] = c["net_mean_1x"].round(3)
best = c.sort_values("gross_over_rt", ascending=False).head(8)
print(best[["signature", "h", "book", "n", "gross_med", "rt_cm2", "gross_over_rt",
            "netmean_1x", "sharpe_per_trade", "hit"]].to_string(index=False))
print(f"\ncells with gross_med >= rt_cm2 (i.e. would pay for the round trip): "
      f"{int((c['gross_over_rt'] >= 1.0).sum())} of {len(c)}")
print(f"cells with net_mean_1x > 0: {int((c['net_mean_1x'] > 0).sum())} of {len(c)}")
sh = c[c["book"] == "shock"]
print(f"SHOCK book only: max gross/rt = {sh['gross_over_rt'].max():.3f} "
      f"({sh.loc[sh['gross_over_rt'].idxmax(), 'signature']} h="
      f"{int(sh.loc[sh['gross_over_rt'].idxmax(), 'h'])}); "
      f"max net_mean_1x = {sh['net_mean_1x'].max():+.3f}bp")

print()
print("=" * 100)
print("G  counterfactual: DELETE the pond step entirely. Does the verdict move?")
print("=" * 100)
inc = pd.read_parquet(OUT / "f7_gate_increment.parquet")
v = json.loads((OUT / "f7_gate_verdict.json").read_text())
for h in g.HORIZONS:
    s = inc[inc["h"] == h]
    onlyclear = s[s["signature"].str.count("-") == 1]     # the 5 spreads: pond-PASSING set
    print(f"  h={h:>2}  ALL 10 sigs: median incr {s['incr_gross_vs_noshock'].median():+.3f}bp, "
          f"median shock net@1x {s['net_mean_1x_shock'].median():+.3f}bp   ||  "
          f"POND-PASSING spreads only: median incr "
          f"{onlyclear['incr_gross_vs_noshock'].median():+.3f}bp, "
          f"median shock net@1x {onlyclear['net_mean_1x_shock'].median():+.3f}bp")
print("\n  placebo (unchanged by any pond estimator -- it is computed on the increment):")
for k, d in v["placebo_wrong_day"].items():
    print(f"    h={k:>2}  real {d['real']:+.3f}  null sd {d['null_sd']:.3f}  "
          f"p(null >= real) = {d['p_value']:.3f}")
