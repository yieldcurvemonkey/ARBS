"""Does dd_nb's self-test actually fail when the pipeline is broken?

A checking tool that is itself wrong reports success and hides the thing it was
built to find. Four mutations, each aimed at a failure mode this repo has
actually been bitten by; every one must make `_selftest` return non-zero.

Runs against a THROWAWAY cache dir -- a monkeypatch does not change
`source_digest`, so a mutated stage sharing the real cache would poison it.

    python scratch/nbhelp_mutate.py
"""
from __future__ import annotations

import contextlib
import io
import os
import pathlib
import shutil
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"

REPO = r"C:\Users\chris\clee\ARBS-dd"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "notebooks", "dealer_direction"))

import pandas as pd  # noqa: E402

import dd_nb  # noqa: E402
from SDRUtils.dealer_direction import conventions as conv  # noqa: E402
from SDRUtils.dealer_direction import package_price as pp  # noqa: E402

MUT_CACHE = pathlib.Path("D:/ddnb_cache_mut")
REAL = dd_nb.CACHE_DIR


def _cfg():
    return dd_nb.config(cache_dir=MUT_CACHE, out_dir=MUT_CACHE / "out")


def _seed_legs():
    """Copy the legs parquet across so a mutation run does not re-hit the tape."""
    (MUT_CACHE / "legs").mkdir(parents=True, exist_ok=True)
    for p in (REAL / "legs").glob("legs_*.parquet"):
        shutil.copy2(p, MUT_CACHE / "legs" / p.name)


def run(label: str, patch) -> bool:
    """Apply `patch`, run the self-test, restore. True when the test FAILED."""
    if MUT_CACHE.exists():
        shutil.rmtree(MUT_CACHE, ignore_errors=True)
    _seed_legs()
    dd_nb._SOURCE_HASH = None
    undo = patch()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = dd_nb._selftest(_cfg())
        caught = rc != 0
        why = ""
        for line in buf.getvalue().splitlines():
            if line.startswith("FAILED:"):
                why = line[:220]
    except BaseException as exc:                              # noqa: BLE001
        caught, why = True, f"raised {type(exc).__name__}: {str(exc)[:180]}"
    finally:
        undo()
    print(f"  [{'CAUGHT ' if caught else 'MISSED!'}] {label}")
    if why:
        print(f"      {why}")
    return caught


# --- M1: weight by p instead of 2p-1 ---------------------------------------
def m1():
    orig = conv.signed_weight

    def bad(p):
        return float(p)                       # the exact mistake 2p-1 prevents
    conv.signed_weight = bad
    orig_pcp = dd_nb.P.direction_probability

    def bad_dp(dev, fit, delta=dd_nb.P.DEAD_ZONE_DELTA):
        c = orig_pcp(dev, fit, delta)
        return dd_nb.dataclasses.replace(c, signed_weight=float(c.p))
    dd_nb.P.direction_probability = bad_dp

    def undo():
        conv.signed_weight = orig
        dd_nb.P.direction_probability = orig_pcp
    return undo


# --- M2: route PKG on (kind, n_legs, rule) alone, as s2 does ---------------
def m2():
    orig = dd_nb.route_rule

    def bad(unit):
        rule = conv.RULE_UPFRONT if unit.upfront is not None else conv.RULE_RATE
        try:
            conv.base_orientation(unit.kind, unit.n_legs, rule)
        except conv.UnorientableUnit:
            return None
        return rule
    dd_nb.route_rule = bad
    return lambda: setattr(dd_nb, "route_rule", orig)


# --- M3: a stage quietly returns an empty frame ----------------------------
def m3():
    orig = dd_nb.krd_frame

    def bad(*a, **k):
        out = orig(*a, **k)
        out.krd = out.krd.iloc[0:0]
        return out
    dd_nb.krd_frame = bad
    return lambda: setattr(dd_nb, "krd_frame", orig)


# --- M4: drop the recovered package orientation (the krd seam) -------------
def m4():
    orig = dd_nb._package_call

    def bad(base, calls, key, r, unit, legs, fit):
        got = orig(base, calls, key, r, unit, legs, fit)
        if calls and calls[-1].unit_key == key \
                and calls[-1].rule == pp.RULE_PACKAGE_PRICE \
                and calls[-1].base_orientation is not None:
            calls[-1] = dd_nb.dataclasses.replace(
                calls[-1], base_orientation=(1,) * int(r["n_legs"]))
        return got
    dd_nb._package_call = bad
    return lambda: setattr(dd_nb, "_package_call", orig)


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    print("mutation testing dd_nb._selftest")
    results = [
        run("M1  signed_weight = p instead of 2p-1", m1),
        run("M2  PKG routed on (kind, n_legs, rule) -- s2's own bug", m2),
        run("M3  krd_frame returns an empty frame", m3),
        run("M4  recovered package orientation replaced by (1,)*n", m4),
    ]
    shutil.rmtree(MUT_CACHE, ignore_errors=True)
    n = sum(results)
    print(f"\n{n}/{len(results)} mutations caught")
    raise SystemExit(0 if n == len(results) else 1)
