"""
Run all SDR analytics notebooks with patched date range.
Usage: conda run -n stir python _run_all.py
"""
import json
import os
import re
import sys
import tempfile
import traceback
import io
from pathlib import Path
from datetime import datetime

# Fix Windows encoding issue with tqdm/unicode chars
os.environ["PYTHONIOENCODING"] = "utf-8"

# Ensure ARBS project root is on sys.path so SDRUtils etc are importable
ARBS_ROOT = str(Path(__file__).resolve().parents[2])
if ARBS_ROOT not in sys.path:
    sys.path.insert(0, ARBS_ROOT)
os.environ["PYTHONPATH"] = ARBS_ROOT + os.pathsep + os.environ.get("PYTHONPATH", "")

import nbformat
from nbconvert.preprocessors import ExecutePreprocessor

# Target date range
TARGET_START = "datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)"
TARGET_END = "datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)"

NOTEBOOKS = [
    "01_flow_decomposition.ipynb",
    "02_volume_regime.ipynb",
    "03_liquidity_scoring.ipynb",
    "04_spreadover_analytics.ipynb",
    "05_sofr_ff_basis.ipynb",
    "06_cme_lch_basis.ipynb",
    "07_compression_analytics.ipynb",
    "08_block_cap_analysis.ipynb",
    "09_tenor_maturity.ipynb",
    "10_event_flow.ipynb",
    "11_fomc_swaps.ipynb",
]

SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = SCRIPT_DIR / "_run_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


PATH_INJECT = f'sys.path.insert(0, r"{ARBS_ROOT}")\n'

def patch_dates(source: str) -> str:
    """Replace START/END date assignments with target range."""
    # Match: START = datetime.datetime(...)
    source = re.sub(
        r'START\s*=\s*datetime\.datetime\([^)]+\)',
        f'START = {TARGET_START}',
        source,
    )
    # Match: END = datetime.datetime(...)
    source = re.sub(
        r'END\s*=\s*datetime\.datetime\([^)]+\)',
        f'END = {TARGET_END}',
        source,
    )
    return source


NEST_ASYNCIO_INJECT = "import nest_asyncio\nnest_asyncio.apply()\n"

def patch_first_cell(nb):
    """Inject ARBS root into sys.path and nest_asyncio in first code cell."""
    for cell in nb.cells:
        if cell.cell_type == "code":
            # Inject nest_asyncio if not already present
            if "nest_asyncio" not in cell.source:
                cell.source = NEST_ASYNCIO_INJECT + cell.source
            # Inject ARBS root path
            if "sys.path.insert" in cell.source:
                cell.source = cell.source.replace(
                    'sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))',
                    f'sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))\n{PATH_INJECT}',
                )
            else:
                cell.source = f"import sys, os\n{PATH_INJECT}\n" + cell.source
            break


def run_notebook(nb_name: str) -> dict:
    """Execute a single notebook, return result dict."""
    nb_path = SCRIPT_DIR / nb_name
    result = {"notebook": nb_name, "status": "unknown", "error": None, "outputs": []}

    print(f"\n{'='*70}")
    print(f"RUNNING: {nb_name}")
    print(f"{'='*70}")

    try:
        with open(nb_path, encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)
    except Exception as e:
        result["status"] = "READ_ERROR"
        result["error"] = str(e)
        print(f"  ERROR reading: {e}")
        return result

    # Patch dates in code cells and inject project root path
    patch_first_cell(nb)
    for cell in nb.cells:
        if cell.cell_type == "code":
            cell.source = patch_dates(cell.source)

    # Execute
    ep = ExecutePreprocessor(
        timeout=1800,  # 30 min per cell — data loading for 12-month range is slow
        kernel_name="python3",
        allow_errors=True,
    )

    try:
        ep.preprocess(nb, {"metadata": {"path": str(SCRIPT_DIR)}})
    except Exception as e:
        result["status"] = "EXECUTION_ERROR"
        result["error"] = str(e)
        print(f"  EXECUTION ERROR: {e}")
        traceback.print_exc()
        # Still try to extract outputs

    # Extract text outputs and errors from cells
    cell_errors = []
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        for output in cell.get("outputs", []):
            if output.get("output_type") == "stream":
                text = output.get("text", "")
                if text.strip():
                    clean_text = text.strip().encode("ascii", errors="replace").decode("ascii")
                    result["outputs"].append(f"[Cell {i}] {clean_text}")
                    print(f"  [Cell {i}] {clean_text[:200]}")
            elif output.get("output_type") == "error":
                ename = output.get("ename", "")
                evalue = output.get("evalue", "")
                tb = "\n".join(output.get("traceback", []))
                err_msg = f"[Cell {i}] {ename}: {evalue}"
                cell_errors.append(err_msg)
                result["outputs"].append(f"ERROR {err_msg}")
                print(f"  ERROR [Cell {i}] {ename}: {evalue}")
                # Print abbreviated traceback
                for line in output.get("traceback", [])[-3:]:
                    # Strip ANSI codes
                    clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                    clean = clean.encode("ascii", errors="replace").decode("ascii")
                    print(f"    {clean[:200]}")

    if cell_errors:
        result["status"] = "CELL_ERRORS"
        result["error"] = "; ".join(cell_errors)
    elif result["status"] == "unknown":
        result["status"] = "OK"

    # Save executed notebook
    out_path = OUTPUT_DIR / nb_name
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            nbformat.write(nb, f)
        print(f"  Saved: {out_path}")
    except Exception as e:
        print(f"  WARNING: Could not save output notebook: {e}")

    return result


def main():
    print(f"SDR Notebook Runner")
    print(f"Date range: 2025-04-10 to 2026-04-10")
    print(f"Working directory: {SCRIPT_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")

    results = []
    for nb_name in NOTEBOOKS:
        r = run_notebook(nb_name)
        results.append(r)

    # Summary
    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    ok = sum(1 for r in results if r["status"] == "OK")
    errors = sum(1 for r in results if r["status"] != "OK")
    print(f"  OK: {ok}/{len(results)}")
    print(f"  Errors: {errors}/{len(results)}")

    for r in results:
        icon = "OK" if r["status"] == "OK" else "FAIL"
        print(f"  [{icon}] {r['notebook']}: {r['status']}")
        if r["error"]:
            print(f"       {r['error'][:200]}")

    # Save results JSON
    results_path = OUTPUT_DIR / "results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")

    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
