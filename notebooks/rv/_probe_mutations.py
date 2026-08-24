"""Mutate the code each guard protects and confirm the guard FAILS.

A test that passes with the thing it checks deleted is not a test. Every file is
backed up, mutated, exercised and restored, and the restore is verified by
comparing bytes -- ``reference_killed_mutation_harness`` records that a killed
harness leaves the broken line in the source and that ``finally`` does not
survive a SIGTERM, so the byte check at the end is the part that matters.
"""
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
PY = r"C:\Users\chris\anaconda3\envs\stir\python.exe"

MUTATIONS = [
    # (file, find, replace, test that must now FAIL)
    ("notebooks/rv/fed_detachment_grid.py",
     "    if np.isfinite(sr_follow) and (not np.isfinite(sr_fade) or sr_follow > sr_fade):\n"
     "        return sr_follow, -1, idx, q\n    return sr_fade, 1, idx, p",
     "    if abs(sr_follow) > abs(sr_fade):\n"
     "        return sr_follow, -1, idx, q\n    return sr_fade, 1, idx, p",
     "test_best_of_both_does_not_pick_the_reading_the_flip_made_worse"),
    ("notebooks/rv/fed_detachment_grid.py",
     "    min_offset = 2 * (int(max_k) + int(max_h)) + 1",
     "    min_offset = (int(max_k) + int(max_h)) + 1",
     "test_rotation_offsets_exclude_every_alignment_the_grid_can_reach"),
    ("notebooks/rv/fed_detachment_prices.py",
     "RATE_SANE_BAND = (-1.0, 15.0)",
     "RATE_SANE_BAND = (-1.0, 1000.0)",
     "test_gate_rate_sanity_rejects_swaption_vol"),
    ("notebooks/rv/fed_detachment_data.py",
     "        if cfg.entry_lag_sessions == 0:",
     "        if True:",
     "test_the_fill_is_the_NEXT_session_not_the_signal_session"),
    ("notebooks/rv/fed_detachment_data.py",
     "        i = j\n    return pd.DataFrame(rows)",
     "        i = i + 1\n    return pd.DataFrame(rows)",
     "test_trades_do_not_overlap"),
    ("notebooks/rv/fed_detachment_engine.py",
     "    if contracts <= 0:",
     "    if False:",
     "test_negative_contracts_are_refused_outright"),
    ("notebooks/rv/fed_detachment_data.py",
     "        assert worst < 1e-9, (",
     "        assert worst < 1e9, (",
     "test_gate_trailing_detachment_actually_catches_a_leak"),
]


def run_test(name: str) -> bool:
    r = subprocess.run([PY, "-m", "pytest", "tests/test_fed_detachment.py",
                        "-k", name, "-q", "--no-header", "-x"],
                       cwd=str(REPO), capture_output=True, text=True)
    return r.returncode == 0


def main() -> int:
    backups = {}
    rows = []
    try:
        for rel, find, repl, test in MUTATIONS:
            p = REPO / rel
            if rel not in backups:
                backups[rel] = p.read_bytes()
            original = p.read_text(encoding="utf-8")
            if find not in original:
                rows.append((test, "PATTERN NOT FOUND", rel))
                continue
            p.write_text(original.replace(find, repl, 1), encoding="utf-8")
            failed = not run_test(test)
            p.write_bytes(backups[rel])
            rows.append((test, "guard is REAL (test failed)" if failed
                         else "*** VACUOUS: test still passes ***", rel))
            print(f"  {rows[-1][1]:38s} {test}", flush=True)
    finally:
        for rel, data in backups.items():
            (REPO / rel).write_bytes(data)

    ok = True
    for rel, data in backups.items():
        same = (REPO / rel).read_bytes() == data
        print(f"restored byte-identical: {same}  {rel}")
        ok &= same
    bad = [r for r in rows if not r[1].startswith("guard is REAL")]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} guards are real")
    for r in bad:
        print("  FAILED:", r)
    return 0 if ok and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
