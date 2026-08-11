"""Execute the two notebooks in place, with no cell timeout.

``jupyter nbconvert``'s ExecutePreprocessor defaults to a 30-second cell
timeout, and the grid cells run for tens of minutes -- so an unattended
execution fails in the middle and leaves a half-run notebook that still looks
plausible. ``timeout=None`` and ``allow_errors=False`` together mean the run
either completes or stops at the first failing cell with its traceback in the
saved notebook.

    python run_notebooks.py                 # both
    python run_notebooks.py backtest        # just the configurable one
    python run_notebooks.py grid
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).parent
NOTEBOOKS = {
    "mdp": HERE / "econ_release_fade_mdp_backtest.ipynb",
    "backtest": HERE / "econ_release_fade_backtest.ipynb",
    "grid": HERE / "econ_release_fade_gridsearch.ipynb",
    "paramsearch": HERE / "econ_release_fade_paramsearch.ipynb",
}


def run(path: Path) -> bool:
    print(f"\n=== executing {path.name} ===", flush=True)
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(
        nb,
        timeout=None,            # NOT the 30s default -- grid cells run for minutes
        kernel_name="python3",
        resources={"metadata": {"path": str(HERE)}},
        allow_errors=False,
    )
    t0 = time.time()
    try:
        client.execute()
        ok = True
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {str(e)[:2000]}", flush=True)
        ok = False
    finally:
        nbformat.write(nb, path)
    print(f"=== {path.name}: {'OK' if ok else 'FAILED'} in {time.time()-t0:.0f}s ===", flush=True)
    return ok


if __name__ == "__main__":
    which = sys.argv[1:] or list(NOTEBOOKS)
    results = {k: run(NOTEBOOKS[k]) for k in which}
    print("\n" + "  ".join(f"{k}={'OK' if v else 'FAILED'}" for k, v in results.items()))
    sys.exit(0 if all(results.values()) else 1)
