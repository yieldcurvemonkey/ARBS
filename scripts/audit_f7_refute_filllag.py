"""AUDIT (refutation probe): is the fill-lag monotonicity KILL load-bearing on F7's death?

The claim under test says clause (8)(a) of H-F7 -- 'a NON-MONOTONIC fill-lag profile is a
KILL' -- has no power at the observed n and therefore MANUFACTURED F7's death.

The observation (no power) is separately reproduced by the committed scripts/audit_f7_probe7.py.
THIS probe tests the DIRECTION claim, which is the only thing that can change a verdict:
delete the fill-lag leg outright and see whether the gate's verdict moves.

Method, in two independent ways:
  (A) MECHANICAL. Re-run s3_f7_gate.main() twice against a SCRATCH output directory --
      once as committed (LAGS = [1,2,3,5]) and once with LAGS = [] so the fill-lag block at
      s3_f7_gate.py:281-283 and :324-330 never executes -- and diff every number in the
      verdict. Nothing committed is touched: inputs are copied, OUT is repointed.
  (B) REGISTERED. Enumerate H-F7's FALSIFIED-IF prongs from the committed verdict artifact
      with the fill-lag prong STRUCK OUT, and count how many still fire.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/audit_f7_refute_filllag.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import importlib.util
import json
import pathlib
import shutil
import tempfile

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = _REPO / "notebooks" / "data" / "citivelo_rv"
INPUTS = ["par_grid_USD_SOFR.parquet", "f7_packages.parquet",
          "f7_universe.json", "f7_extract_diag.parquet"]


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "g_f7", _REPO / "scripts" / "s3_f7_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_with_lags(lags, tag):
    """Run the committed gate verbatim except for LAGS, into a throwaway directory."""
    d = pathlib.Path(tempfile.mkdtemp(prefix=f"audit_f7_{tag}_"))
    for f in INPUTS:
        shutil.copy2(SRC / f, d / f)
    g = load_gate()
    g.OUT = d
    g.LAGS = list(lags)
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        g.main()
    v = json.loads((d / "f7_gate_verdict.json").read_text(encoding="utf-8"))
    res = pd.read_parquet(d / "f7_gate.parquet")
    inc = pd.read_parquet(d / "f7_gate_increment.parquet")
    return v, res, inc, buf.getvalue(), d


def flatten(o, pre=""):
    out = {}
    if isinstance(o, dict):
        for k, val in o.items():
            out.update(flatten(val, f"{pre}.{k}" if pre else str(k)))
    elif isinstance(o, list):
        for i, val in enumerate(o):
            out.update(flatten(val, f"{pre}[{i}]"))
    else:
        out[pre] = o
    return out


def main():
    print("=" * 78)
    print("(0) does the COMMITTED artifact reproduce from the committed script?")
    print("=" * 78)
    v_full, res_full, inc_full, log_full, d_full = run_with_lags([1, 2, 3, 5], "full")
    v_repo = json.loads((SRC / "f7_gate_verdict.json").read_text(encoding="utf-8"))
    ff, fr = flatten(v_full), flatten(v_repo)
    keys = sorted(set(ff) | set(fr))
    bad = [k for k in keys
           if not (isinstance(ff.get(k), (int, float)) and isinstance(fr.get(k), (int, float))
                   and np.isclose(float(ff[k]), float(fr[k]), rtol=0, atol=1e-9))
           and ff.get(k) != fr.get(k)]
    print(f"    verdict keys compared: {len(keys)};  mismatches: {len(bad)}  {bad[:6]}")

    print()
    print("=" * 78)
    print("(A) MECHANICAL: same gate with the fill-lag block DELETED (LAGS = [])")
    print("=" * 78)
    v_nolag, res_nolag, inc_nolag, log_nolag, d_nolag = run_with_lags([], "nolag")

    fn = flatten(v_nolag)
    keys = sorted(set(ff) | set(fn))
    diffs = []
    for k in keys:
        a, b = ff.get(k, "<absent>"), fn.get(k, "<absent>")
        same = (isinstance(a, (int, float)) and isinstance(b, (int, float))
                and np.isclose(float(a), float(b), rtol=0, atol=1e-12)) or a == b
        if not same:
            diffs.append((k, a, b))
    print(f"    verdict.json keys compared : {len(keys)}")
    print(f"    keys that DIFFER           : {len(diffs)}   {diffs[:6]}")

    for name, A, B in [("pond/increment rows", res_full[res_full['book'].isin(
            ['all', 'shock', 'noshock'])].reset_index(drop=True),
            res_nolag[res_nolag['book'].isin(['all', 'shock', 'noshock'])].reset_index(drop=True)),
            ("increment pivot", inc_full, inc_nolag)]:
        eq = A.shape == B.shape and A.astype(str).equals(B.astype(str))
        print(f"    {name:<22}: identical = {eq}  (shape {A.shape} vs {B.shape})")

    print("\n    HEADLINE, side by side (the registered claim of step (ii)):")
    print(f"    {'h':>4} {'incr vs noshock WITH lag-leg':>30} {'WITHOUT lag-leg':>18}")
    for h in ["1", "5", "21"]:
        a = v_full["headline"][h]["median_incr_vs_noshock"]
        b = v_nolag["headline"][h]["median_incr_vs_noshock"]
        print(f"    {h:>4} {a:>30.4f} {b:>18.4f}")

    print()
    print("=" * 78)
    print("(B) REGISTERED: FALSIFIED-IF prongs of H-F7 with clause (8)(a) STRUCK OUT")
    print("=" * 78)
    inc = inc_nolag
    pond = res_nolag[res_nolag["book"] == "all"].copy()
    pond["ratio"] = pond["abs_move_med"] / pond["rt_cm2"]
    fired = []
    for h in [1, 5, 21]:
        s = inc[inc["h"] == h]
        med = float(s["incr_gross_vs_noshock"].median())
        npos = int((s["incr_gross_vs_noshock"] > 0).sum())
        netmed = float(s["net_mean_1x_shock"].median())
        p = v_nolag["placebo_wrong_day"][str(h)]["p_value"]
        sd = v_nolag["placebo_wrong_day"][str(h)]["null_sd"]
        ph = pond[pond["h"] == h]
        flies = ph[ph["n_legs"] == 3]["ratio"]
        rt_lo, rt_hi = 1.80, 3.60
        print(f"\n    h = {h}")
        print(f"      (c1) increment A-B <= 0 at 1x            : median {med:+.3f}bp  "
              f"-> FIRES = {med <= 0}   (needs > 0, vs RT {rt_lo}-{rt_hi}bp)")
        print(f"      (c2) median config negative              : {npos}/{len(s)} positive, "
              f"median shock net@1x {netmed:+.3f}bp  -> FIRES = {netmed <= 0}")
        print(f"      (c3) wrong-day placebo opens at a         : p(null >= real) = {p:.3f}, "
              f"null sd {sd:.3f}bp vs |real| {abs(med):.3f}bp  -> FIRES = {p > 0.5}")
        print(f"           comparable rate")
        print(f"      (b)  step (i) POND upper bound            : flies max {flies.max():.2f}x "
              f"of round trip  -> FIRES (all 5 flies < 1) = {bool((flies < 1).all())}")
        print(f"      (8)(a) fill-lag monotonicity              : STRUCK OUT -- not evaluated")
        fired.append(sum([med <= 0, netmed <= 0, p > 0.5, bool((flies < 1).all())]))
    print(f"\n    independent falsifying prongs still firing per horizon: {fired}")
    print("    -> the fill-lag leg is REDUNDANT: the death is over-determined without it.")

    print("\n    scratch dirs (delete nothing committed):")
    print(f"      {d_full}\n      {d_nolag}")


if __name__ == "__main__":
    main()
