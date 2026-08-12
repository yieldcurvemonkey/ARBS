"""Independent mutation runner for the upfront verification.

Written from scratch rather than reusing either the reviewer's `mut_upfront.py`
or the fixer's `mut_upfront_v2.py`, because the thing being checked is whether
those two harnesses agree -- a shared runner would hide a disagreement in how
"red" is decided.

Two things the original runner gets wrong and this one does not:

* it calls returncode != 0 "red". pytest exits non-zero for a collection error
  and for the plugin's own `SystemExit("MUTATION PATTERN NOT FOUND")`, so a
  mutant that never ran is indistinguishable from one that was killed. Here a
  result is RED only if pytest printed "N failed", and a pattern that is absent
  from the source is reported MISSING before pytest is started at all.
* it takes the source path as a module constant. Here it is an argument, so the
  same mutant set can be run against the pre-fix (HEAD) source and the current
  one and the survivor sets compared.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

PLUGIN = r'''
import importlib, sys, types
SRC = {src!r}
OLD = {old!r}
NEW = {new!r}
src = open(SRC, encoding="utf-8").read()
if OLD != NEW:
    src = src.replace(OLD, NEW)
pkg = importlib.import_module("SDRUtils.dealer_direction")
mod = types.ModuleType("SDRUtils.dealer_direction.upfront")
mod.__file__ = SRC
mod.__package__ = "SDRUtils.dealer_direction"
sys.modules["SDRUtils.dealer_direction.upfront"] = mod
exec(compile(src, SRC, "exec"), mod.__dict__)
setattr(pkg, "upfront", mod)
'''

_TAIL = re.compile(r"(?:(\d+) failed)|(?:(\d+) passed)")


def load_mutations(path: str) -> dict:
    spec = importlib.util.spec_from_file_location("_mutset", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.MUTATIONS)


def run_one(name, old, new, src, test, tag):
    text = open(src, encoding="utf-8").read()
    n = text.count(old)
    if n == 0:
        return name, "MISSING", "pattern absent from source"
    if n > 1 and old != new:
        return name, "AMBIGUOUS", f"pattern occurs {n}x"
    plug_name = f"_plug_{tag}"
    plug = os.path.join(HERE, plug_name + ".py")
    with open(plug, "w", encoding="utf-8") as fh:
        fh.write(PLUGIN.format(src=src, old=old, new=new))
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0",
               PYTHONPATH=ROOT + os.pathsep + HERE)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", plug_name, "-q", test],
        cwd=ROOT, env=env, capture_output=True, text=True)
    out = r.stdout + r.stderr
    failed = passed = None
    for m in _TAIL.finditer(out):
        if m.group(1):
            failed = int(m.group(1))
        if m.group(2):
            passed = int(m.group(2))
    if failed:
        return name, "RED", f"{failed} failed / {passed} passed"
    if r.returncode == 0 and passed:
        return name, "GREEN", f"{passed} passed"
    return name, "ERROR", (out.strip().splitlines() or ["<no output>"])[-1][:160]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--mutset", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    muts = load_mutations(a.mutset)
    names = a.only or list(muts)
    survivors, missing = [], []
    for nm in names:
        old, new = muts[nm]
        nm, status, detail = run_one(nm, old, new, a.src, a.test, a.tag)
        print(f"{nm:44s} {status:9s} {detail}", flush=True)
        if status == "GREEN":
            survivors.append(nm)
        if status in ("MISSING", "AMBIGUOUS", "ERROR"):
            missing.append((nm, status))
    print(f"\nGREEN (survivors): {len(survivors)} {survivors}")
    print(f"NOT-RUN: {len(missing)} {missing}")


if __name__ == "__main__":
    main()
