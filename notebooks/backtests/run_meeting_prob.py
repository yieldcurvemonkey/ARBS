"""Convert, execute and verify the meeting-prob notebooks in dependency order.

Same pattern as run_sfr_rv_lab.py: ``# %%`` sources -> _py2nb -> nbconvert
--execute --inplace -> _verify_nb (zero error outputs, zero unrun cells).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

ORDER = [
    "meeting_prob_tieout",
    "meeting_prob_feasibility",
    "meeting_prob_channel1",
    "meeting_prob_summary",
]


def sh(cmd, timeout=5400):
    p = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main(argv=None) -> int:
    names = ORDER if not argv else [n for n in ORDER if any(a in n for a in argv)]
    failures = []
    for name in names:
        t0 = time.time()
        rc, log = sh([sys.executable, str(HERE / "_py2nb.py"), f"{name}.py"])
        if rc != 0:
            print(f"FAIL convert {name}\n{log[-1500:]}", flush=True)
            failures.append(name)
            continue
        rc, log = sh(["jupyter", "nbconvert", "--to", "notebook", "--execute",
                      "--inplace", "--ExecutePreprocessor.timeout=5400",
                      f"{name}.ipynb"])
        if rc != 0:
            print(f"FAIL execute {name} ({time.time() - t0:.0f}s)\n"
                  f"{log[-2500:]}", flush=True)
            failures.append(name)
            continue
        print(f"OK {name} ({time.time() - t0:.0f}s)", flush=True)
    rc, log = sh([sys.executable, str(HERE / "_verify_nb.py")]
                 + [f"{n}.ipynb" for n in names
                    if (HERE / f"{n}.ipynb").exists()])
    print(log.strip(), flush=True)
    return 1 if (failures or rc != 0) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
