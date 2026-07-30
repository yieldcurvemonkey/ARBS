"""Build, execute and verify the whole SR3 RV lab.

Merges the panel parts, converts every framework source to a notebook, executes
each one in place, then verifies the executed notebooks programmatically (zero
cell errors, zero unrun cells) rather than trusting exit codes. The summary
notebook runs last because it reads the league table the others write.

Usage::

    conda run -n stir python notebooks/backtests/run_sfr_rv_lab.py
    conda run -n stir python notebooks/backtests/run_sfr_rv_lab.py --only skew_basis
    conda run -n stir python notebooks/backtests/run_sfr_rv_lab.py --no-merge
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

#: execution order — the summary must come last (it reads the league table)
FRAMEWORKS = [
    "sfr_rv_lab_skew_basis",
    "sfr_rv_lab_digital_calendars",
    "sfr_rv_lab_gamma_theta",
    "sfr_rv_lab_wing_convexity",
    "sfr_rv_lab_meeting_lattice",
    "sfr_rv_lab_fly_vs_straddle",
    "sfr_rv_lab_event_studies",
    "sfr_rv_lab_midcurve",
    "sfr_rv_lab_summary",
]


def sh(cmd: list[str], cwd: Path, timeout: int = 7200) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None,
                    help="run only these framework stems (suffix match)")
    ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--no-exec", action="store_true",
                    help="convert and verify without re-executing")
    ap.add_argument("--reset-league", action="store_true",
                    help="delete the league table first (full clean rebuild)")
    a = ap.parse_args(argv)

    data = REPO / "notebooks" / "data" / "sfr_rv_lab"
    if not a.no_merge:
        for out in (data, REPO / "notebooks" / "data" / "sfr_rv_lab_mc"):
            if not (out / "parts").exists():
                continue
            print(f"merging parts in {out}", flush=True)
            rc, log = sh([sys.executable,
                          str(REPO / "notebooks" / "rv" / "build_sfr_rv_panels.py"),
                          "--start", "2024-07-01", "--end", "2026-07-28",
                          "--merge", "--out-dir", str(out)], cwd=REPO)
            print(log.strip()[-800:], flush=True)

    if a.reset_league:
        for f in ("league_table.csv", "sign_tests.csv", "league_table_sorted.csv"):
            (data / f).unlink(missing_ok=True)
        print("league table reset", flush=True)

    names = FRAMEWORKS
    if a.only:
        names = [n for n in FRAMEWORKS if any(o in n for o in a.only)]
    print(f"frameworks: {names}", flush=True)

    failures = []
    for name in names:
        py, nb = HERE / f"{name}.py", HERE / f"{name}.ipynb"
        if not py.exists():
            print(f"SKIP {name}: no source", flush=True)
            continue
        t0 = time.time()
        rc, log = sh([sys.executable, str(HERE / "_py2nb.py"), py.name], cwd=HERE)
        if rc != 0:
            print(f"FAIL convert {name}\n{log[-2000:]}", flush=True)
            failures.append(name)
            continue
        if not a.no_exec:
            rc, log = sh(["jupyter", "nbconvert", "--to", "notebook", "--execute",
                          "--inplace", "--ExecutePreprocessor.timeout=5400",
                          nb.name], cwd=HERE)
            if rc != 0:
                print(f"FAIL execute {name} ({time.time() - t0:.0f}s)\n"
                      f"{log[-3000:]}", flush=True)
                failures.append(name)
                continue
        print(f"OK {name} ({time.time() - t0:.0f}s)", flush=True)

    print("\n=== verification ===", flush=True)
    rc, log = sh([sys.executable, str(HERE / "_verify_nb.py")]
                 + [f"{n}.ipynb" for n in names if (HERE / f"{n}.ipynb").exists()],
                 cwd=HERE)
    print(log.strip(), flush=True)
    if failures:
        print(f"\nFAILED: {failures}", flush=True)
    return 1 if (failures or rc != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
