"""Build, execute and verify the whole SFR butterfly mean-reversion lab.

Converts every framework source to a notebook, executes each in place, then
verifies the executed notebooks programmatically (zero cell errors, zero unrun
cells) rather than trusting exit codes. The summary and rules-of-thumb notebooks
run last because they read the league table the others write.

Usage::

    conda run -n stir python notebooks/backtests/run_sfr_fly_meanrev.py
    conda run -n stir python notebooks/backtests/run_sfr_fly_meanrev.py --only zscore
    conda run -n stir python notebooks/backtests/run_sfr_fly_meanrev.py --reset-league
    conda run -n stir python notebooks/backtests/run_sfr_fly_meanrev.py --as-scripts
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

#: execution order -- summary and rules of thumb must come last
FRAMEWORKS = [
    "sfr_fly_meanrev_zscore",
    "sfr_fly_meanrev_ou",
    "sfr_fly_meanrev_coint",
    "sfr_fly_meanrev_pca",
    "sfr_fly_meanrev_kalman",
    "sfr_fly_meanrev_curvefit",
    "sfr_fly_meanrev_xsection",
    "sfr_fly_meanrev_regime",
    "sfr_fly_meanrev_arblab",
    "sfr_fly_meanrev_weights",
    "sfr_fly_meanrev_summary",
    "sfr_fly_rules_of_thumb",
]

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"


def sh(cmd: list[str], cwd: Path, timeout: int = 7200) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None,
                    help="run only these framework stems (substring match)")
    ap.add_argument("--no-exec", action="store_true",
                    help="convert and verify without re-executing")
    ap.add_argument("--as-scripts", action="store_true",
                    help="run the .py sources directly (fast error check, no .ipynb)")
    ap.add_argument("--reset-league", action="store_true")
    ap.add_argument("--timeout", type=int, default=7200)
    a = ap.parse_args(argv)

    if a.reset_league:
        for f in ("league_table.csv", "sign_tests.csv", "league_table_sorted.csv",
                  "regime_splits.csv", "shadow_tests.csv", "rules_of_thumb.csv"):
            (DATA / f).unlink(missing_ok=True)
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

        if a.as_scripts:
            rc, log = sh([sys.executable, py.name], cwd=HERE, timeout=a.timeout)
            if rc != 0:
                print(f"FAIL script {name} ({time.time() - t0:.0f}s)\n{log[-4000:]}",
                      flush=True)
                failures.append(name)
            else:
                print(f"OK script {name} ({time.time() - t0:.0f}s)", flush=True)
            continue

        rc, log = sh([sys.executable, str(HERE / "_py2nb.py"), py.name], cwd=HERE)
        if rc != 0:
            print(f"FAIL convert {name}\n{log[-2000:]}", flush=True)
            failures.append(name)
            continue
        if not a.no_exec:
            rc, log = sh(["jupyter", "nbconvert", "--to", "notebook", "--execute",
                          "--inplace", "--ExecutePreprocessor.timeout=5400",
                          nb.name], cwd=HERE, timeout=a.timeout)
            if rc != 0:
                print(f"FAIL execute {name} ({time.time() - t0:.0f}s)\n"
                      f"{log[-4000:]}", flush=True)
                failures.append(name)
                continue
        print(f"OK {name} ({time.time() - t0:.0f}s)", flush=True)

    if not a.as_scripts:
        print("\n=== verification ===", flush=True)
        rc, log = sh([sys.executable, str(HERE / "_verify_nb.py")]
                     + [f"{n}.ipynb" for n in names if (HERE / f"{n}.ipynb").exists()],
                     cwd=HERE)
        print(log.strip(), flush=True)
    else:
        rc = 0
    if failures:
        print(f"\nFAILED: {failures}", flush=True)
    return 1 if (failures or rc != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
