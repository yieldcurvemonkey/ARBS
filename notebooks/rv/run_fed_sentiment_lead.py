"""Build, execute and verify the data-surprise -> Fedspeak lead notebook.

Follows the house driver pattern (``notebooks/backtests/convexity_rv/run_convexity_rv.py``):
convert the percent-format source to a notebook, execute it in place, then
**verify the executed notebook programmatically** -- zero cell errors, zero
unrun cells -- rather than trusting the exit code. nbconvert will complete
happily on a notebook whose cells all carry tracebacks, and a notebook whose
cells never ran is not a deliverable either.

Usage::

    conda run -n stir python notebooks/rv/run_fed_sentiment_lead.py
    conda run -n stir python notebooks/rv/run_fed_sentiment_lead.py --no-exec

The run is dominated by bootstraps and surrogate nulls -- roughly 20,000 lag
curves -- so budget ten to fifteen minutes, not seconds. ``timeout=None`` is
deliberate: nbclient's 30-second default kills the null cells.

The handover asked for ``scripts/_build_*_notebook.py`` and
``scripts/_check_notebook.py``. Neither exists in this repo; ``_py2nb.py`` and
``_verify_nb.py`` under ``notebooks/backtests`` are the current house tools and
do exactly those two jobs, so they are used instead of adding a third pair.
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

STEM = "fed_sentiment_lead"


def _run(cmd: list[str], cwd: Path) -> int:
    print(f"$ {' '.join(cmd)}   (cwd={cwd})", flush=True)
    return subprocess.call(cmd, cwd=str(cwd))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-exec", action="store_true", help="convert and verify only")
    args = ap.parse_args(argv)

    src = HERE / f"{STEM}.py"
    nb = HERE / f"{STEM}.ipynb"
    if not src.exists():
        print(f"MISSING source {src}")
        return 1

    rc = _run([sys.executable, str(TOOLS / "_py2nb.py"), str(src)], REPO)
    if rc:
        return rc

    if not args.no_exec:
        t0 = time.time()
        code = (
            "import nbformat, sys;"
            "from nbclient import NotebookClient;"
            f"p=r'{nb}';"
            "n=nbformat.read(p, as_version=4);"
            "NotebookClient(n, timeout=None, kernel_name='python3',"
            f" resources={{'metadata': {{'path': r'{HERE}'}}}}).execute();"
            "nbformat.write(n, p)"
        )
        rc = _run([sys.executable, "-c", code], HERE)
        print(f"execution finished in {time.time() - t0:.0f}s (rc={rc})")

    # verification is the gate, not the exit code above
    # _verify_nb globs relative to cwd, so hand it a repo-relative path
    rc_verify = _run(
        [sys.executable, str(TOOLS / "_verify_nb.py"), str(nb.relative_to(REPO)).replace("\\", "/")],
        REPO,
    )
    return rc_verify


if __name__ == "__main__":
    raise SystemExit(main())
