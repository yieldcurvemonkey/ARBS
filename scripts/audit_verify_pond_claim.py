"""AUDIT (refutation pass): verify the claimed POND-ESTIMATOR defect at s3_f7_gate.py:296.

Claim under test: the pond is estimated on the ~18-22 NON-OVERLAPPING episodes the P&L
constructor produces, when 206-335 eligible entries / 622 windows are available; on the
better estimators 2-5-10 clears 1.0x, so "all 5 flies < 0.79x" is FALSE and the stated
REASON for the flies' death is wrong.

Sections:
  A  rebuild the panel cold and reproduce the gate's own pond table
  B  the three estimators side by side + bootstrap of the gate's n-sample median
  C  IS IT BIAS OR NOISE?  phase-sweep the non-overlap lock (every start offset)
     and compare the gate's single greedy phase against the phase distribution
  D  VERDICT IMPACT: does the pond prune anything?  what happens to step (ii)?
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

# ------------------------------------------------------------------ panel (cold)
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
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    P[sig] = dict(
        x=x, z=z,
        shock=g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q),
        persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
        & (z.shift(1).abs() >= g.Z_ENTRY),
        rt=g.round_trips(sig))

gate = pd.read_parquet(OUT / "f7_gate.parquet")


def eligible(sig, h, mask=None, lag=1):
    """Every eligible entry index (no lock), with its |move| and signal-direction gross."""
    x, z = P[sig]["x"], P[sig]["z"]
    ok = (P[sig]["persistent"] if mask is None else mask).reindex(x.index).fillna(False).to_numpy()
    xv, zv, n = x.to_numpy(), z.to_numpy(), len(x)
    rows = []
    for i in range(g.Z_WIN, n - lag - h):
        if not ok[i]:
            continue
        side = -np.sign(zv[i])
        if side == 0:
            continue
        e, xo = xv[i + lag], xv[i + lag + h]
        rows.append((i, float(abs(xo - e)), float(side * (xo - e)), float(zv[i])))
    return pd.DataFrame(rows, columns=["i", "abs_move_bp", "gross_bp", "z"])


def greedy_from(el, h, start_pos, lag=1):
    """Non-overlapping subset of `el` (already index-sorted) starting at row start_pos."""
    keep, busy = [], -1
    for r in el.itertuples(index=False):
        if r.i < el["i"].iloc[start_pos] or r.i <= busy:
            continue
        keep.append(r.Index if hasattr(r, "Index") else None)
        busy = r.i + lag + h
    # rebuild by position (itertuples lost the label)
    keep, busy = [], -1
    for pos in range(start_pos, len(el)):
        i = int(el["i"].iloc[pos])
        if i <= busy:
            continue
        keep.append(pos)
        busy = i + lag + h
    return el.iloc[keep]


print("=" * 100)
print("A  COLD REBUILD -- reproduce the gate's own pond numbers")
print("=" * 100)
rows = []
for sig in uni:
    for h in g.HORIZONS:
        tr = g.episodes(P[sig]["x"], P[sig]["z"], P[sig]["persistent"], h)
        gv = gate[(gate.signature == sig) & (gate.h == h) & (gate.book == "all")].iloc[0]
        rows.append({"sig": sig, "h": h, "n_cold": len(tr),
                     "amove_cold": round(float(tr["abs_move_bp"].median()), 4),
                     "n_gate": int(gv["n"]), "amove_gate": round(float(gv["abs_move_med"]), 4),
                     "match": bool(len(tr) == int(gv["n"])
                                   and abs(tr["abs_move_bp"].median() - gv["abs_move_med"]) < 1e-9)})
A = pd.DataFrame(rows)
print(A.to_string(index=False))
print(f"\ncold rebuild reproduces the committed gate table on all {len(A)} cells: {bool(A['match'].all())}")

print()
print("=" * 100)
print("B  THE THREE ESTIMATORS + bootstrap of the gate's own n-sample median")
print("=" * 100)
rows = []
for sig in uni:
    rt = P[sig]["rt"]["rt_cm2"]
    for h in g.HORIZONS:
        el = eligible(sig, h)
        gv = gate[(gate.signature == sig) & (gate.h == h) & (gate.book == "all")].iloc[0]
        mv = (P[sig]["x"].shift(-h) - P[sig]["x"]).dropna().abs()
        rng = np.random.default_rng(1)
        arr = el["abs_move_bp"].to_numpy()
        bs = np.array([np.median(rng.choice(arr, int(gv["n"]), replace=True)) for _ in range(2000)])
        rows.append({"sig": sig, "h": h, "legs": len(sig.split("-")),
                     "gate_n": int(gv["n"]), "gate_pond": round(gv["abs_move_med"] / rt, 3),
                     "elig_n": len(el), "elig_pond": round(el["abs_move_bp"].median() / rt, 3),
                     "unc_n": len(mv), "unc_pond": round(mv.median() / rt, 3),
                     "boot_p05": round(np.percentile(bs, 5) / rt, 3),
                     "boot_p95": round(np.percentile(bs, 95) / rt, 3)})
B = pd.DataFrame(rows)
print(B.to_string(index=False))
fl = B[B["legs"] == 3]
print("\nFLIES only, max pond across the three estimators at each h:")
for h in g.HORIZONS:
    s = fl[fl["h"] == h]
    print(f"  h={h:>2}: gate max {s['gate_pond'].max():.3f} | elig max {s['elig_pond'].max():.3f} "
          f"| uncond max {s['unc_pond'].max():.3f}   "
          f"(#flies >=1.0x: gate {int((s['gate_pond']>=1).sum())}, "
          f"elig {int((s['elig_pond']>=1).sum())}, uncond {int((s['unc_pond']>=1).sum())})")

print()
print("=" * 100)
print("C  BIAS OR NOISE?  phase-sweep the non-overlap lock over every start offset")
print("=" * 100)
rows = []
for sig in uni:
    rt = P[sig]["rt"]["rt_cm2"]
    for h in g.HORIZONS:
        el = eligible(sig, h)
        if el.empty:
            continue
        meds, ns = [], []
        seen = set()
        for p in range(len(el)):
            sub = greedy_from(el, h, p)
            key = tuple(sub["i"].tolist())
            if key in seen:
                continue
            seen.add(key)
            meds.append(float(sub["abs_move_bp"].median()))
            ns.append(len(sub))
        meds = np.array(meds)
        gv = gate[(gate.signature == sig) & (gate.h == h) & (gate.book == "all")].iloc[0]
        rows.append({"sig": sig, "h": h,
                     "gate_pond": round(gv["abs_move_med"] / rt, 3),
                     "n_phases": len(meds), "mean_n": round(float(np.mean(ns)), 1),
                     "phase_med_pond": round(float(np.median(meds)) / rt, 3),
                     "phase_p05": round(float(np.percentile(meds, 5)) / rt, 3),
                     "phase_p95": round(float(np.percentile(meds, 95)) / rt, 3),
                     "elig_pond": round(el["abs_move_bp"].median() / rt, 3),
                     "gate_pctile_in_phases": round(float((meds <= gv["abs_move_med"]).mean()), 3)})
C = pd.DataFrame(rows)
print(C.to_string(index=False))
print("\nIf the greedy lock were BIASED LOW, gate_pctile_in_phases would sit near 0 systematically.")
print(f"  median percentile of the gate's own phase within the phase distribution: "
      f"{C['gate_pctile_in_phases'].median():.3f}")
print(f"  phase-median pond vs elig pond (all cells): "
      f"median ratio {float((C['phase_med_pond']/C['elig_pond']).median()):.3f}")

print()
print("=" * 100)
print("D  VERDICT IMPACT")
print("=" * 100)
inc = pd.read_parquet(OUT / "f7_gate_increment.parquet")
print("\nD1 does the pond prune the universe the increment is computed on?")
print(f"   signatures in the universe : {len(uni)}")
for h in g.HORIZONS:
    s = inc[inc["h"] == h]
    print(f"   h={h:>2}: increment rows = {len(s)}  -> signatures present: {sorted(s['signature'])}")
print("   -> step (ii) is computed for EVERY signature; the pond filters nothing in code.")

print("\nD2 the cells the claim says should have lived: flies at h=21")
cols = ["signature", "h", "n_shock", "n_noshock", "gross_med_shock", "gross_med_noshock",
        "gross_med_all", "incr_gross_vs_noshock", "net_mean_1x_shock"]
sub = inc[(inc["h"] == 21) & (inc["signature"].str.count("-") == 2)]
sub = sub.assign(rt_cm2=[P[s]["rt"]["rt_cm2"] for s in sub["signature"]])
print(sub[cols + ["rt_cm2"]].to_string(index=False))

print("\nD3 the SPREADS -- which PASS the pond by 2.0-4.9x -- at h=21")
sub2 = inc[(inc["h"] == 21) & (inc["signature"].str.count("-") == 1)]
sub2 = sub2.assign(rt_cm2=[P[s]["rt"]["rt_cm2"] for s in sub2["signature"]])
print(sub2[cols + ["rt_cm2"]].to_string(index=False))

print("\nD4 headline increment medians recomputed on the committed increment table")
for h in g.HORIZONS:
    s = inc[inc["h"] == h]
    print(f"   h={h:>2}  median incr vs noshock {s['incr_gross_vs_noshock'].median():+.3f}bp   "
          f"median shock net@1x {s['net_mean_1x_shock'].median():+.3f}bp   "
          f"positive incr {int((s['incr_gross_vs_noshock']>0).sum())}/{len(s)}")
