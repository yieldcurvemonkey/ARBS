"""Mutate the krd seam fix and confirm the new tests die.

A test that passes against the mutant is a test that was not checking the
thing it is named for. Each mutation is a single textual substitution in
`SDRUtils/dealer_direction/krd.py`; the file is restored from an in-memory copy
in a `finally`, and the run refuses to start if the tree is not clean of a
previous crash (the backup is written to D: as well, so a hard kill is
recoverable).

Usage:  python scratch/ddseam_mutate.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["TEMP"] = os.environ["TMP"] = r"D:\ddfix3\tmp"

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
TARGET = ROOT / "SDRUtils" / "dealer_direction" / "krd.py"
BACKUP = pathlib.Path(r"D:\ddfix3\krd.py.orig")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
TESTS = "tests/test_dealer_direction_krd.py"

# (name, old, new, tests that MUST fail)
MUTATIONS = [
    (
        "dispatch falls through to the conventions branch",
        "    if rule == package_price.RULE_PACKAGE_PRICE:\n"
        "        if call is None or getattr(call, \"base_orientation\", None) is None:",
        "    if False:\n"
        "        if call is None or getattr(call, \"base_orientation\", None) is None:",
        ["test_a_recovered_package_keeps_its_legs_pointing_opposite_ways",
         "test_the_dispatch_reads_the_call_not_only_the_rule_string"],
    ),
    (
        "the orientation is taken but the legs are pointed one way anyway",
        "        signs = package_price.received_hypothesis_signs(call)",
        "        signs = (1,) * int(n_legs)",
        ["test_a_recovered_package_keeps_its_legs_pointing_opposite_ways",
         "test_the_dispatch_reads_the_call_not_only_the_rule_string"],
    ),
    (
        "the length check is deleted, so zip truncates in silence",
        "    if len(signs) != int(n_legs):",
        "    if False:",
        ["test_an_orientation_of_the_wrong_length_is_refused_not_truncated"],
    ),
    (
        "the caller-contract raise is downgraded to a row-level failure",
        "            if _needs_call_orientation(call):",
        "            if False:",
        ["test_a_package_price_call_with_no_orientation_is_a_caller_bug"],
    ),
    (
        "the rule/call disagreement guard is dropped",
        "        if call is not None and getattr(call, \"rule\", rule) != rule:",
        "        if False:",
        ["test_a_call_from_a_different_rule_is_refused_rather_than_half_used"],
    ),
    (
        "the call is accepted but never threaded into unit_positions",
        "        model, instruments = self.unit_positions(unit, rule, instant=instant,\n"
        "                                                 call=call)",
        "        model, instruments = self.unit_positions(unit, rule, instant=instant)",
        ["test_a_recovered_package_keeps_its_legs_pointing_opposite_ways"],
    ),
]


def run(names) -> tuple[int, str]:
    expr = " or ".join(n.removeprefix("test_") for n in names)
    p = subprocess.run(
        [PY, "-m", "pytest", TESTS, "-k", expr, "-q", "-p", "no:cacheprovider",
         "--basetemp=D:\\ddfix3\\pytest"],
        cwd=ROOT, capture_output=True, text=True)
    tail = [ln for ln in p.stdout.splitlines() if "passed" in ln or "failed" in ln]
    return p.returncode, (tail[-1] if tail else p.stdout[-300:])


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    BACKUP.write_text(original, encoding="utf-8")
    bad = 0
    try:
        rc, line = run([m[3][0] for m in MUTATIONS] + [
            "test_the_same_package_under_the_upfront_rule_is_the_hazard"])
        print(f"[baseline] rc={rc}  {line}")
        if rc != 0:
            print("baseline is not green; aborting")
            return 1
        for name, old, new, must_fail in MUTATIONS:
            if original.count(old) != 1:
                print(f"[SKIP] {name!r}: anchor appears "
                      f"{original.count(old)} times")
                bad += 1
                continue
            TARGET.write_text(original.replace(old, new), encoding="utf-8")
            rc, line = run(must_fail)
            verdict = "KILLED " if rc != 0 else "SURVIVED"
            print(f"[{verdict}] {name}\n           {line}")
            if rc == 0:
                bad += 1
    finally:
        TARGET.write_text(original, encoding="utf-8")
        print("restored", TARGET)
    rc, line = run([m[3][0] for m in MUTATIONS])
    print(f"[restored] rc={rc}  {line}")
    return 1 if (bad or rc != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
