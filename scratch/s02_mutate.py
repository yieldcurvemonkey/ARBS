"""Mutation check: break the code four ways and confirm the right test fails.

A test suite that passes is not evidence until it has been shown to fail. Each
mutation reintroduces a defect that is silent in production.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path(r"C:/Users/chris/clee/ARBS-dd/SDRUtils/dealer_direction/lineage.py")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
ROOT = r"C:/Users/chris/clee/ARBS-dd"

MUTATIONS = [
    # (name, find, replace, test that must fail)
    ("reintroduce the Execution-Timestamp mask",
     '    df["file_date"] = _as_date(day)',
     '    df["file_date"] = _as_date(day)\n'
     '    df = df[df[EXEC_TS].dt.date == _as_date(day)]',
     "test_a_lifecycle_row_older_than_the_file_survives_the_fetch"),
    ("single-hop resolution only",
     "            cur, hops = nxt, hops + 1",
     "            cur, hops = nxt, hops + 1\n            break",
     "test_chained_partial_terminations_walk_all_the_way_to_the_newt"),
    ("read the slice mtime as UTC",
     '    local = pd.Timestamp(datetime.datetime(*stamp)).tz_localize(SLICE_MEMBER_TZ)',
     '    local = pd.Timestamp(datetime.datetime(*stamp)).tz_localize("UTC")',
     "test_the_zip_member_mtime_is_eastern_and_comes_back_as_utc"),
    ("carry the ENTRY fee rule over to unwinds",
     "    customer_is_itm = u < abs(f)",
     "    customer_is_itm = u > abs(f)",
     "test_the_unwind_fee_rule_is_the_reverse_of_the_entry_fee_rule"),
    ("let the ledger be the resume authority",
     "        return [_as_date(d) for d in days if self.rows_for(d) == 0]",
     "        led = self.read_ledger()\n"
     "        return [_as_date(d) for d in days if _as_date(d).isoformat() not in led]",
     "test_resume_is_keyed_to_the_target_set_not_the_ledger"),
]

original = SRC.read_text(encoding="utf-8")
ok = True
try:
    for name, find, repl, test in MUTATIONS:
        assert original.count(find) == 1, f"mutation anchor not unique: {name!r} ({original.count(find)})"
        SRC.write_text(original.replace(find, repl), encoding="utf-8")
        r = subprocess.run([PY, "-m", "pytest",
                            f"tests/test_dealer_direction_lineage.py::{test}", "-q"],
                           cwd=ROOT, capture_output=True, text=True)
        failed = r.returncode != 0
        print(f"[{'OK  ' if failed else 'HOLE'}] {name}: {test} -> "
              f"{'FAILED as required' if failed else 'STILL PASSED - the test does not cover it'}")
        if not failed:
            ok = False
finally:
    SRC.write_text(original, encoding="utf-8")
    print("restored", SRC)

r = subprocess.run([PY, "-m", "pytest", "tests/test_dealer_direction_lineage.py", "-q"],
                   cwd=ROOT, capture_output=True, text=True)
print("clean suite after restore:", r.stdout.strip().splitlines()[-1])
sys.exit(0 if ok and r.returncode == 0 else 1)
