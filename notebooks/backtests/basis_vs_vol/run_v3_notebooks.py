"""Execute the V3 notebooks in place with nbclient.

    <env>/python.exe notebooks/backtests/basis_vs_vol/run_v3_notebooks.py

nbclient with timeout=None and allow_errors=False, following econ_release_fade/run_notebooks.py:
nbconvert's ExecutePreprocessor defaults to 30s, which kills a grid cell mid-run and leaves a
plausible-looking half-executed notebook on disk.
"""
import pathlib, sys
import nbformat
from nbclient import NotebookClient

HERE = pathlib.Path(__file__).resolve().parent
NBS = ["basis_v3_configurable_backtest.ipynb", "basis_v3_grid_search.ipynb"]

rc = 0
for name in NBS:
    p = HERE / name
    print(f"executing {name} ...", flush=True)
    nb = nbformat.read(p, as_version=4)
    client = NotebookClient(nb, timeout=None, kernel_name="python3",
                            resources={"metadata": {"path": str(HERE)}}, allow_errors=False)
    try:
        client.execute()
        print(f"  OK {name}", flush=True)
    except Exception as exc:
        rc = 1
        print(f"  FAILED {name}: {type(exc).__name__}: {str(exc)[:400]}", flush=True)
    finally:
        nbformat.write(nb, p)
sys.exit(rc)
