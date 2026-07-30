"""Build, execute and verify the SFR kink-fade lab.

Same shape as ``run_sfr_fly_meanrev.py``: convert the ``# %%`` source to a
notebook, execute it in place, then verify the executed notebook
programmatically -- zero cell errors, zero unrun cells -- rather than trusting
an exit code.

Usage::

    conda run -n stir python notebooks/backtests/run_sfr_kink_fade.py
    conda run -n stir python notebooks/backtests/run_sfr_kink_fade.py --as-scripts
    conda run -n stir python notebooks/backtests/run_sfr_kink_fade.py --reset-league
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

NOTEBOOKS = ["sfr_kink_fade_backtest"]

DATA = REPO / "notebooks" / "data" / "sfr_kink_fade"

#: every CSV the lab writes. The league / sign / regime / shadow tables are
#: **upserted** per (framework, variant), so a stale row from a renamed
#: framework would otherwise survive forever and be counted in the verdict.
#: Kept in sync with the notebook by ``--check-outputs``.
OUTPUTS = ("league_table.csv", "league_table_sorted.csv", "sign_tests.csv",
           "regime_splits.csv", "shadow_tests.csv",
           "pond_test_3m.csv", "pond_test_6m.csv",
           "placebo_ic.csv", "placebo_backtest.csv", "symmetry_gate.csv",
           "symmetry_pond.csv")


def sh(cmd: list[str], cwd: Path, timeout: int = 7200) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--no-exec", action="store_true",
                    help="convert and verify without re-executing")
    ap.add_argument("--as-scripts", action="store_true",
                    help="run the .py sources directly (fast error check)")
    ap.add_argument("--reset-league", action="store_true")
    ap.add_argument("--check-outputs", action="store_true",
                    help="verify OUTPUTS matches what the last run actually wrote")
    ap.add_argument("--timeout", type=int, default=7200)
    a = ap.parse_args(argv)

    if a.check_outputs:
        on_disk = {p.name for p in DATA.glob("*.csv")} if DATA.exists() else set()
        missing, extra = sorted(set(OUTPUTS) - on_disk), sorted(on_disk - set(OUTPUTS))
        print(f"on disk: {len(on_disk)}   listed: {len(OUTPUTS)}", flush=True)
        if missing:
            print(f"  listed but never written: {missing}", flush=True)
        if extra:
            print(f"  written but not listed (would survive a reset): {extra}",
                  flush=True)
        return 1 if (missing or extra) else 0

    # The league table is upserted, so a run that renames a framework leaves the
    # old row behind. Always start clean unless explicitly told not to.
    if a.reset_league or not a.no_exec:
        DATA.mkdir(parents=True, exist_ok=True)
        for f in OUTPUTS:
            (DATA / f).unlink(missing_ok=True)
        print("lab outputs reset", flush=True)

    names = NOTEBOOKS
    if a.only:
        names = [n for n in NOTEBOOKS if any(o in n for o in a.only)]
    print(f"notebooks: {names}", flush=True)

    failures = []
    for name in names:
        py, nb = HERE / f"{name}.py", HERE / f"{name}.ipynb"
        if not py.exists():
            print(f"SKIP {name}: no source", flush=True)
            continue
        t0 = time.time()

        if a.as_scripts:
            rc, log = sh([sys.executable, py.name], cwd=HERE, timeout=a.timeout)
            tag = "OK" if rc == 0 else "FAIL"
            print(f"{tag} script {name} ({time.time() - t0:.0f}s)", flush=True)
            if rc != 0:
                print(log[-6000:], flush=True)
                failures.append(name)
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
                      f"{log[-6000:]}", flush=True)
                failures.append(name)
                continue
        print(f"OK {name} ({time.time() - t0:.0f}s)", flush=True)

    rc = 0
    if not a.as_scripts:
        print("\n=== verification ===", flush=True)
        rc, log = sh([sys.executable, str(HERE / "_verify_nb.py")]
                     + [f"{n}.ipynb" for n in names
                        if (HERE / f"{n}.ipynb").exists()], cwd=HERE)
        print(log.strip(), flush=True)
    if failures:
        print(f"\nFAILED: {failures}", flush=True)
    return 1 if (failures or rc != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
