"""Mutation check on the runner: make the empty day a silent skip and confirm
the abort test fails. That skip IS the six-days-of-data defect."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path(r"C:/Users/chris/clee/ARBS-dd/scripts/build_dd_lineage_store.py")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
ROOT = r"C:/Users/chris/clee/ARBS-dd"

FIND = """        df = lin.fetch_raw_day(d, root=root, force=force, zip_source=zip_source)
        if df.empty:
            raise lin.EmptyDTCCDay(f"{d}: cumulative file parsed to zero rows")"""
REPL = """        try:
            df = lin.fetch_raw_day(d, root=root, force=force, zip_source=zip_source)
        except lin.EmptyDTCCDay:
            continue"""
TEST = "test_the_runner_aborts_on_a_day_the_upstream_serves_nothing"

original = SRC.read_text(encoding="utf-8")
assert original.count(FIND) == 1
try:
    SRC.write_text(original.replace(FIND, REPL), encoding="utf-8")
    r = subprocess.run([PY, "-m", "pytest", f"tests/test_dealer_direction_lineage.py::{TEST}", "-q"],
                       cwd=ROOT, capture_output=True, text=True)
    print(f"[{'OK  ' if r.returncode else 'HOLE'}] silent skip of an empty day -> "
          f"{'test FAILED as required' if r.returncode else 'test STILL PASSED'}")
finally:
    SRC.write_text(original, encoding="utf-8")
r2 = subprocess.run([PY, "-m", "pytest", "tests/test_dealer_direction_lineage.py", "-q"],
                    cwd=ROOT, capture_output=True, text=True)
print("clean suite after restore:", r2.stdout.strip().splitlines()[-1])
sys.exit(0 if r.returncode and r2.returncode == 0 else 1)
