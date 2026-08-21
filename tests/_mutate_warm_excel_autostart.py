"""Reintroduce each defect and confirm its test goes red. Reverts after every case.

Run: python tests/_mutate_warm_excel_autostart.py

A test that passes on broken code is worse than no test, and this file is the only
thing that distinguishes the two. Each mutation below is a defect the reviewed code
could plausibly regress into -- a dropped latch, a forced restart, a swallowed
re-probe -- not a synthetic edit chosen because it is easy to detect.
"""
from __future__ import annotations

import io
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TARGET = REPO / "scripts" / "daily_cache_warmer.py"
TESTS = REPO / "tests" / "test_warm_excel_autostart.py"
PY = sys.executable

#: (label, find, replace, the test that must break)
MUTATIONS = [
    (
        "restart is forced, discarding unsaved work",
        "client = supervisor.restart_excel(ready_timeout=_CV_SIGNIN_TIMEOUT_S, logger=log)",
        "client = supervisor.restart_excel(ready_timeout=_CV_SIGNIN_TIMEOUT_S, logger=log, force=True)",
        "test_over_ceiling_restarts_and_never_forces",
    ),
    (
        "the one-repair latch is dropped, so a leak becomes a restart loop",
        "    if _EXCEL_REPAIR_ATTEMPTED:\n        return f\"{reason}; a repair was already attempted this run and did not stick\"\n    _EXCEL_REPAIR_ATTEMPTED = True",
        "    _EXCEL_REPAIR_ATTEMPTED = True",
        "test_only_one_repair_per_run",
    ),
    (
        "the post-repair ceiling re-probe is skipped",
        "    if mb >= _CV_MEMORY_CEILING_MB:\n        return (f\"repaired Excel but it came back at {mb:.0f} MB, still at or above the \"\n                f\"{_CV_MEMORY_CEILING_MB:.0f} MB ceiling\")",
        "    if False:\n        pass",
        "test_a_repair_that_relands_over_the_ceiling_still_blocks",
    ),
    (
        "a failed repair propagates instead of returning a reason",
        "    except Exception as exc:  # noqa: BLE001 - a failed repair is a SKIP, not a crash\n        return (f\"{reason}; tried to fix it and could not after \"\n                f\"{time.perf_counter() - t0:.0f}s ({type(exc).__name__}: {exc})\")",
        "    except ZeroDivisionError as exc:\n        return str(exc)",
        "test_a_failed_repair_is_a_reason_not_an_exception",
    ),
    (
        "an unreadable re-probe is treated as success",
        "    if mb is None or mb <= 0.0:\n        return \"repaired Excel but the memory probe still cannot see a running instance\"",
        "    if False:\n        pass",
        "test_an_unreadable_reprobe_blocks_rather_than_assuming_success",
    ),
    (
        "the login pane is never pressed, so a started Excel never signs in",
        "timeout=_CV_SIGNIN_TIMEOUT_S, press_login=True, logger=log",
        "timeout=_CV_SIGNIN_TIMEOUT_S, press_login=False, logger=log",
        "test_no_excel_is_started_and_signed_in",
    ),
    (
        "an absent Excel is routed to restart instead of launch",
        "            over_ceiling=False,\n        )",
        "            over_ceiling=True,\n        )",
        "test_preflight_routes_each_cause_to_its_own_repair",
    ),
]


def run(nodeid: str) -> bool:
    """True when the test PASSES."""
    p = subprocess.run(
        [PY, "-m", "pytest", f"{TESTS}::{nodeid}", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    return p.returncode == 0


def main() -> int:
    original = io.open(TARGET, encoding="utf-8").read()
    rows, escaped = [], 0
    try:
        for label, find, repl, nodeid in MUTATIONS:
            if find not in original:
                rows.append((label, nodeid, "FIND-MISSING"))
                escaped += 1
                continue
            io.open(TARGET, "w", encoding="utf-8", newline="").write(
                original.replace(find, repl, 1)
            )
            passed = run(nodeid)
            rows.append((label, nodeid, "ESCAPED" if passed else "caught"))
            if passed:
                escaped += 1
    finally:
        io.open(TARGET, "w", encoding="utf-8", newline="").write(original)

    width = max(len(r[0]) for r in rows)
    print(f"\n{'mutation'.ljust(width)}  {'test'.ljust(52)}  result")
    print("-" * (width + 64))
    for label, nodeid, res in rows:
        print(f"{label.ljust(width)}  {nodeid.ljust(52)}  {res}")
    print(f"\n{len(rows) - escaped}/{len(rows)} caught")
    if escaped:
        print("ESCAPED mutations are untested claims. Fix the test, not the verdict.")
    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
