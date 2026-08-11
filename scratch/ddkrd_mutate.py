"""Mutate krd.py and confirm the test file actually catches each defect.

A test that survives a mutation is not testing the line it appears to test.
Runs the real pytest against a temporarily patched module and always restores.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path("C:/Users/chris/clee/ARBS-dd")
SRC = ROOT / "SDRUtils/dealer_direction/krd.py"
TESTS = "tests/test_dealer_direction_krd.py"
PY = "C:/Users/chris/anaconda3/envs/stir/python.exe"

MUTATIONS = [
    ("drop the RL_DELTA_TO_FUTURES_EQ flip",
     "return {p: conv.RL_DELTA_TO_FUTURES_EQ * raw[p] for p in model.pillars}",
     "return {p: raw[p] for p in model.pillars}"),
    ("make the flip per-bucket (the stir_flow HISTORY bug)",
     "return {p: conv.RL_DELTA_TO_FUTURES_EQ * raw[p] for p in model.pillars}",
     "return {p: (-1.0 if _years(p) < 5 else 1.0) * raw[p] for p in model.pillars}"),
    ("drop the per-leg received sign",
     "notional = -int(sign) * abs(float(leg[\"notional\"]))",
     "notional = -abs(float(leg[\"notional\"]))"),
    ("take the notional's sign from the tape",
     "notional = -int(sign) * abs(float(leg[\"notional\"]))",
     "notional = -int(sign) * float(leg[\"notional\"])"),
    ("ignore the rule when orienting the legs",
     "return conv.dealer_received_signs(kind, n_legs, rule, conv.DEALER_RECEIVED)",
     "return conv.dealer_received_signs(kind, n_legs, conv.RULE_RATE, "
     "conv.DEALER_RECEIVED)"),
    ("sign the profile with the call instead of the hypothesis",
     "return conv.dealer_received_signs(kind, n_legs, rule, conv.DEALER_RECEIVED)",
     "return conv.dealer_received_signs(kind, n_legs, rule, conv.DEALER_PAID)"),
    ("cache the solver per day instead of per block",
     "return (et.date(), (et.hour * 60 + et.minute) // int(block_minutes))",
     "return (et.date(), 0)"),
    ("price past-start legs without the published fixings",
     "handle = model.risk_handle_fixed if effective < ref else model.risk_handle",
     "handle = model.risk_handle"),
    ("skip the bucket-grid validation",
     "else validate_pillars(pillars))",
     "else tuple(str(p).upper() for p in pillars))"),
    ("drop the block lookahead guard",
     "elif _lookahead_seconds(model.anchor, instant) > 0.0:",
     "elif False:"),
    ("make the dust floor absolute instead of relative",
     "floor = self.dust_frac * sum(abs(v) for v in profile.values())",
     "floor = self.dust_frac"),
    ("emit the buckets in an arbitrary order",
     "for p in model.pillars}",
     "for p in sorted(model.pillars)}"),
]


def run() -> tuple[int, str]:
    out = subprocess.run(
        [PY, "-m", "pytest", TESTS, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    tail = [ln for ln in out.stdout.splitlines()
            if ln.startswith("FAILED") or " passed" in ln or " failed" in ln]
    return out.returncode, " | ".join(tail[-6:])


def main() -> int:
    original = SRC.read_text(encoding="utf-8")
    backup = pathlib.Path(tempfile.gettempdir()) / "krd_backup.py"
    backup.write_text(original, encoding="utf-8")
    survivors = []
    try:
        code, summary = run()
        print(f"[baseline] rc={code}  {summary}")
        if code != 0:
            print("baseline is not green; aborting")
            return 1
        for name, old, new in MUTATIONS:
            if old not in original:
                print(f"[SKIP] {name}: anchor not found -- {old[:60]!r}")
                survivors.append(name + " (anchor missing)")
                continue
            SRC.write_text(original.replace(old, new, 1), encoding="utf-8")
            code, summary = run()
            verdict = "CAUGHT" if code != 0 else "SURVIVED"
            if code == 0:
                survivors.append(name)
            print(f"[{verdict}] {name}\n           {summary}")
    finally:
        SRC.write_text(original, encoding="utf-8")
        shutil.copy(backup, SRC)
    print("\nsurvivors:", survivors or "none")
    return 0 if not survivors else 2


if __name__ == "__main__":
    sys.exit(main())
