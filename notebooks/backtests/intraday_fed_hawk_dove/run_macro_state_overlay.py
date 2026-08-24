"""Build, execute, verify and audit the macro-state overlay notebook.

The house driver pattern: convert the percent-format source with ``_py2nb.py``,
execute it in place with nbclient, then **verify the executed notebook
programmatically** -- zero cell errors, zero unrun cells -- rather than trusting
the exit code, and finally require every figure asserted in the findings block to
have been produced by a cell.

Usage::

    conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/run_macro_state_overlay.py
    conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/run_macro_state_overlay.py --no-exec

**Run the report first.** The notebook reads
``_signal_overlay_results.pkl`` and does no backtesting of its own, so it
executes in seconds; the expensive part is a separate process that needs the
warm bar cache and cannot fetch::

    conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/_signal_overlay_report.py

That takes about a minute. Run ``_probe20_signal_knob.py`` before either --
it is the known-answer check that ``mode="off"`` reproduces the module as it was
before the knob existed, trade for trade.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TOOLS = REPO / "notebooks" / "backtests"

STEM = "usd_fed_macro_state_overlay"


def _run(cmd: list[str], cwd: Path) -> int:
    print(f"$ {' '.join(cmd)}   (cwd={cwd})", flush=True)
    return subprocess.call(cmd, cwd=str(cwd))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-exec", action="store_true", help="convert only")
    args = ap.parse_args(argv)

    src = HERE / f"{STEM}.py"
    nb = HERE / f"{STEM}.ipynb"
    if not src.exists():
        print(f"MISSING source {src}")
        return 1

    rc = _run([sys.executable, str(TOOLS / "_py2nb.py"), str(src)], REPO)
    if rc:
        return rc
    if args.no_exec:
        print("converted only; the notebook has no outputs so verification and "
              "the number audit would both fail by construction")
        return 0

    t0 = time.time()
    rc = _run([sys.executable, "-c", (
        "import nbformat, pathlib;"
        "from nbclient import NotebookClient;"
        f"p = pathlib.Path(r'{nb}');"
        "nbf = nbformat.read(p, as_version=4);"
        "NotebookClient(nbf, timeout=None, kernel_name='python3',"
        f" resources={{'metadata': {{'path': r'{HERE}'}}}}).execute();"
        "nbformat.write(nbf, p)")], REPO)
    print(f"execution finished in {time.time() - t0:.0f}s (rc={rc})", flush=True)

    # _verify_nb globs its argument, and pathlib refuses to glob a non-relative
    # pattern, so the path has to go in relative to the cwd the command runs in
    ok = _run([sys.executable, str(TOOLS / "_verify_nb.py"),
               str(nb.relative_to(REPO)).replace("\\", "/")], REPO)
    audit = _run([sys.executable, str(HERE / "_audit_macro_state_overlay_numbers.py"),
                  str(nb)], REPO)
    return rc or ok or audit


if __name__ == "__main__":
    raise SystemExit(main())
