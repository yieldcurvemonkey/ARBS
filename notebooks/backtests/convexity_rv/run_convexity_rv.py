"""Build, execute and verify the three convexity relative-value backtests.

Follows the house driver pattern (``notebooks/backtests/run_sfr_rv_lab.py``):
convert each percent-format source to a notebook, execute it in place, then
verify the executed notebooks programmatically -- zero cell errors, zero unrun
cells -- rather than trusting exit codes.

The three strategies, each from a specific research note:

``strat1_curve_gamma``
    JPM, *An option by any other name: Sourcing cheap convexity in the long end
    of the curve* (03-Feb-2017). Long-end forward flatteners as an options-like
    payoff, priced against swaptions.

``strat2_sofr_convexity``
    Citi's STIR futures convexity-adjustment screen, ported ED -> SFR, traded
    against a 2s5s10s butterfly hedge.

``strat3_strikeless_vol``
    Citi, *US Rates Vol Lab: Trading long-dated convexity* (09-May-2019).
    Delta-hedged long-dated forward flatteners -- long convexity that pays
    theta -- plus the grid search over pair and hedge threshold.

Usage::

    conda run -n stir python notebooks/backtests/convexity_rv/run_convexity_rv.py
    conda run -n stir python notebooks/backtests/convexity_rv/run_convexity_rv.py --only strat3
    conda run -n stir python notebooks/backtests/convexity_rv/run_convexity_rv.py --no-exec

Notebooks are executed SERIALLY and each builds swap curves day by day, so a
full run is measured in tens of minutes, not seconds.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent          # notebooks/backtests -- holds _py2nb.py / _verify_nb.py
REPO = HERE.parents[2]

#: execution order; the grid search runs last because it is much the slowest.
NOTEBOOKS = [
    "strat1_curve_gamma_backtest",
    "strat2_sofr_convexity_backtest",
    "strat2_q20_deep_packs",
    "strat3_strikeless_vol_backtest",
    "strat3_strikeless_vol_gridsearch",
]

#: ``strat2_q20_deep_packs`` reads panels built by
#: ``scripts/strat2_q20_build.py``. Build them first on a cold machine; the
#: notebook raises on a missing parquet rather than rebuilding silently, because
#: the build enumerates the local SR3 diskcache and its coverage is the result.

#: nbconvert timeout per notebook, seconds. The grid search needs the headroom.
EXEC_TIMEOUT = 10800


def sh(cmd: list[str], cwd: Path, timeout: int = 14400) -> tuple[int, str]:
    env = dict(os.environ)
    # Never let a cache miss escalate into a live COM fetch against the user's
    # signed-in Excel add-in during an unattended run.
    env.setdefault("ARBS_SUPABASE_ENABLED", "0")
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None,
                    help="run only these notebook stems (substring match)")
    ap.add_argument("--no-exec", action="store_true",
                    help="convert and verify without re-executing")
    a = ap.parse_args(argv)

    names = NOTEBOOKS
    if a.only:
        names = [n for n in NOTEBOOKS if any(o in n for o in a.only)]
    print(f"notebooks: {names}", flush=True)

    failures: list[str] = []
    for name in names:
        py, nb = HERE / f"{name}.py", HERE / f"{name}.ipynb"
        if not py.exists():
            print(f"SKIP {name}: no source", flush=True)
            continue
        t0 = time.time()
        rc, log = sh([sys.executable, str(TOOLS / "_py2nb.py"), str(py)], cwd=HERE)
        if rc != 0:
            print(f"FAIL convert {name}\n{log[-2000:]}", flush=True)
            failures.append(name)
            continue
        if not a.no_exec:
            rc, log = sh([sys.executable, "-m", "nbconvert", "--to", "notebook",
                          "--execute", "--inplace",
                          f"--ExecutePreprocessor.timeout={EXEC_TIMEOUT}",
                          nb.name], cwd=HERE)
            if rc != 0:
                print(f"FAIL execute {name} ({time.time() - t0:.0f}s)\n"
                      f"{log[-3000:]}", flush=True)
                failures.append(name)
                continue
        print(f"OK {name} ({time.time() - t0:.0f}s)", flush=True)

    print("\n=== verification ===", flush=True)
    present = [f"{n}.ipynb" for n in names if (HERE / f"{n}.ipynb").exists()]
    rc = 0
    if present:
        rc, log = sh([sys.executable, str(TOOLS / "_verify_nb.py")] + present, cwd=HERE)
        print(log.strip(), flush=True)
    else:
        print("no executed notebooks to verify", flush=True)

    if failures:
        print(f"\nFAILED: {failures}", flush=True)
    return 1 if (failures or rc != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
