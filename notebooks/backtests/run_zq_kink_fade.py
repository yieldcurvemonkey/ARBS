"""Build, execute and verify the ZQ (Fed Funds) kink-fade lab.

Same shape as ``run_sfr_kink_fade.py``: convert the ``# %%`` source, execute it
in place, then verify the executed notebook programmatically rather than
trusting an exit code.

Usage::

    conda run -n stir python notebooks/backtests/run_zq_kink_fade.py
    conda run -n stir python notebooks/backtests/run_zq_kink_fade.py --as-scripts
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

NOTEBOOKS = ["zq_kink_fade_backtest"]
DATA = REPO / "notebooks" / "data" / "zq_kink_fade"

#: every CSV the lab writes. The league / sign / regime / shadow tables are
#: upserted per (framework, variant), so a stale row from a renamed framework
#: would otherwise survive and be counted in the verdict.
OUTPUTS = ("league_table.csv", "league_table_sorted.csv", "sign_tests.csv",
           "regime_splits.csv", "zq_shadow_tests.csv", "cleanliness.csv",
           "oracle_spread_raw.csv", "oracle_fly_raw.csv",
           "oracle_by_exposure.csv", "residual_lambda_sweep.csv",
           "implied_jump_summary.csv", "curve_golden_test.csv")


def sh(cmd: list[str], cwd: Path, timeout: int = 7200) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-exec", action="store_true")
    ap.add_argument("--as-scripts", action="store_true")
    ap.add_argument("--check-outputs", action="store_true")
    ap.add_argument("--timeout", type=int, default=7200)
    a = ap.parse_args(argv)

    if a.check_outputs:
        on_disk = {p.name for p in DATA.glob("*.csv")} if DATA.exists() else set()
        missing, extra = sorted(set(OUTPUTS) - on_disk), sorted(on_disk - set(OUTPUTS))
        print(f"on disk: {len(on_disk)}   listed: {len(OUTPUTS)}", flush=True)
        if missing:
            print(f"  listed but never written: {missing}", flush=True)
        if extra:
            print(f"  written but not listed: {extra}", flush=True)
        return 1 if (missing or extra) else 0

    if not a.no_exec:
        DATA.mkdir(parents=True, exist_ok=True)
        for f in OUTPUTS:
            (DATA / f).unlink(missing_ok=True)
        print("lab outputs reset", flush=True)

    failures = []
    for name in NOTEBOOKS:
        py, nb = HERE / f"{name}.py", HERE / f"{name}.ipynb"
        if not py.exists():
            print(f"SKIP {name}: no source", flush=True)
            continue
        t0 = time.time()
        if a.as_scripts:
            rc, log = sh([sys.executable, py.name], cwd=HERE, timeout=a.timeout)
            print(f"{'OK' if rc == 0 else 'FAIL'} script {name} "
                  f"({time.time() - t0:.0f}s)", flush=True)
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
                     + [f"{n}.ipynb" for n in NOTEBOOKS
                        if (HERE / f"{n}.ipynb").exists()], cwd=HERE)
        print(log.strip(), flush=True)
    if failures:
        print(f"\nFAILED: {failures}", flush=True)
    return 1 if (failures or rc != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
