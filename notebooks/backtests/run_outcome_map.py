"""Convert, execute and verify the outcome-map notebooks in dependency order.

Same pattern as ``run_linvol_grid``'s notebook stage: ``# %%`` sources ->
_py2nb -> nbconvert --execute --inplace -> _verify_nb (zero error outputs, zero
unrun cells). The atlas lives under ``notebooks/rv``; the league and autopsy sit
with the harness under ``notebooks/backtests``.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RV = HERE.parent / "rv"

ORDER = [
    (RV, "outcome_map_atlas"),
    (HERE, "outcome_map_league"),
    (HERE, "outcome_map_autopsy"),
]


def sh(cmd, cwd, timeout=5400):
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main(argv=None) -> int:
    names = ORDER if not argv else [x for x in ORDER
                                    if any(a in x[1] for a in argv)]
    failures = []
    for d, name in names:
        t0 = time.time()
        rc, log = sh([sys.executable, str(HERE / "_py2nb.py"), f"{name}.py"], d)
        if rc != 0:
            print(f"FAIL convert {name}\n{log[-1500:]}", flush=True)
            failures.append(name)
            continue
        rc, log = sh(["jupyter", "nbconvert", "--to", "notebook", "--execute",
                      "--inplace", "--ExecutePreprocessor.timeout=5400",
                      f"{name}.ipynb"], d)
        if rc != 0:
            print(f"FAIL execute {name} ({time.time() - t0:.0f}s)\n"
                  f"{log[-3000:]}", flush=True)
            failures.append(name)
            continue
        print(f"OK {name} ({time.time() - t0:.0f}s)", flush=True)
    bad = 0
    for d, name in names:
        if not (d / f"{name}.ipynb").exists():
            continue
        rc, log = sh([sys.executable, str(HERE / "_verify_nb.py"),
                      f"{name}.ipynb"], d)
        print(log.strip(), flush=True)
        bad += rc != 0
    return 1 if (failures or bad) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
