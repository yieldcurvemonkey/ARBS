"""Build, execute, verify and audit the expected-sentiment SR3 notebook.

The house driver pattern: convert the percent-format source with ``_py2nb.py``,
execute it in place with nbclient, then **verify the executed notebook
programmatically** -- zero cell errors, zero unrun cells -- rather than trusting
the exit code, and finally require every figure asserted in the findings block to
have been produced by a cell.

Usage::

    conda run -n stir python notebooks/rv/run_fed_expected_sentiment.py
    conda run -n stir python notebooks/rv/run_fed_expected_sentiment.py --no-exec

**Run the grids first.** The notebook reads
``fed_expected_sentiment_results.pkl`` and does no searching of its own, so it
executes in well under a minute; the expensive part is a separate process that
can be watched and killed::

    conda run -n stir python notebooks/rv/fed_expected_sentiment_grids.py

That takes about five minutes for all three samples. ``timeout=None`` here is
still deliberate -- nbclient's 30-second default would kill the plotting cells
on a cold kernel.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TOOLS = REPO / "notebooks" / "backtests"

STEM = "fed_expected_sentiment_rv"


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
    audit = _run([sys.executable, str(HERE / "_audit_fed_expected_sentiment_numbers.py"),
                  str(nb)], REPO)
    return rc or ok or audit


if __name__ == "__main__":
    raise SystemExit(main())
