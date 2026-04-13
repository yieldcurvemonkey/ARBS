"""
Convert notebooks to scripts, patch dates, and run directly.
Avoids Jupyter kernel overhead + captures output inline.
"""
import json
import os
import re
import sys
import traceback
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"

ARBS_ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ARBS_ROOT)
sys.path.insert(0, str(Path(__file__).parent))

import nest_asyncio
nest_asyncio.apply()

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend

SCRIPT_DIR = Path(__file__).parent.resolve()
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


def nb_to_script(nb_path: Path) -> str:
    """Convert notebook to Python script, patching dates."""
    with open(nb_path, encoding="utf-8") as f:
        nb = json.load(f)

    lines = []
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            src = "".join(cell["source"])
            # Patch dates
            src = re.sub(r'START\s*=\s*datetime\.datetime\([^)]+\)', f'START = {TARGET_START}', src)
            src = re.sub(r'END\s*=\s*datetime\.datetime\([^)]+\)', f'END = {TARGET_END}', src)
            # Remove IPython display() calls — use print instead
            src = src.replace("display(", "print(")
            lines.append(src)
            lines.append("")  # blank line between cells

    script = "\n".join(lines)

    # Ensure nest_asyncio and path are at the top
    preamble = f"""import nest_asyncio
nest_asyncio.apply()
import sys, os
sys.path.insert(0, r'{ARBS_ROOT}')
sys.path.insert(0, r'{SCRIPT_DIR}')
import matplotlib
matplotlib.use('Agg')
"""
    # Remove any existing nest_asyncio imports to avoid duplication
    script = script.replace("import nest_asyncio\nnest_asyncio.apply()\n\n", "")
    script = script.replace("import nest_asyncio\nnest_asyncio.apply()\n", "")

    return preamble + "\n" + script


def run_notebook(nb_name: str) -> dict:
    """Convert and run a single notebook as a script."""
    nb_path = SCRIPT_DIR / nb_name
    result = {"notebook": nb_name, "status": "unknown", "error": None}

    print(f"\n{'='*70}", flush=True)
    print(f"RUNNING: {nb_name}", flush=True)
    print(f"{'='*70}", flush=True)

    try:
        script = nb_to_script(nb_path)
    except Exception as e:
        result["status"] = "CONVERT_ERROR"
        result["error"] = str(e)
        print(f"  CONVERT ERROR: {e}", flush=True)
        return result

    # Save script for debugging
    script_path = SCRIPT_DIR / "_run_outputs" / nb_name.replace(".ipynb", ".py")
    script_path.parent.mkdir(exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    # Force reload _usd_swaps_common to pick up fixes between runs
    if "_usd_swaps_common" in sys.modules:
        del sys.modules["_usd_swaps_common"]

    # Execute in isolated namespace
    ns = {"__name__": "__main__", "__file__": str(nb_path)}
    try:
        exec(compile(script, str(nb_path), "exec"), ns)
        result["status"] = "OK"
        print(f"  COMPLETED OK", flush=True)
    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()

    return result


def main():
    print(f"SDR Notebook Script Runner", flush=True)
    print(f"Date range: 2026-01-10 to 2026-04-10", flush=True)
    print(f"Working directory: {SCRIPT_DIR}", flush=True)

    results = []
    for nb_name in NOTEBOOKS:
        r = run_notebook(nb_name)
        results.append(r)
        import gc
        gc.collect()  # Free memory between notebooks

    # Summary
    print(f"\n\n{'='*70}", flush=True)
    print("SUMMARY", flush=True)
    print(f"{'='*70}", flush=True)
    ok = sum(1 for r in results if r["status"] == "OK")
    errors = sum(1 for r in results if r["status"] != "OK")
    print(f"  OK: {ok}/{len(results)}", flush=True)
    print(f"  Errors: {errors}/{len(results)}", flush=True)

    for r in results:
        icon = "OK" if r["status"] == "OK" else "FAIL"
        print(f"  [{icon}] {r['notebook']}: {r['status']}", flush=True)
        if r["error"]:
            err_short = r["error"][:200].encode("ascii", errors="replace").decode("ascii")
            print(f"       {err_short}", flush=True)

    # Save summary
    summary_path = SCRIPT_DIR / "_run_outputs" / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSummary saved to: {summary_path}", flush=True)

    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
