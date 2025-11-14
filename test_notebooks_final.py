#!/usr/bin/env python3
"""
Test notebook execution - final version with proper path handling.

This script changes to the notebooks directory before executing cells,
so that the notebook's own path setup (Path.cwd().parent) works correctly.
"""

import json
import sys
import os
from pathlib import Path

def test_notebook_sequential(notebook_filename: str, max_cells: int = 8) -> dict:
    """
    Test notebook by executing cells sequentially with shared namespace.

    Args:
        notebook_filename: Just the filename (e.g., '10_vol_arbitrage_strategy.ipynb')
        max_cells: Maximum number of cells to test

    Returns:
        Dict with test results
    """
    print(f"\n{'='*80}")
    print(f"Testing: {notebook_filename}")
    print(f"{'='*80}\n")

    try:
        with open(notebook_filename, 'r') as f:
            nb = json.load(f)

        code_cells = [c for c in nb['cells'] if c['cell_type'] == 'code']
        print(f"Found {len(code_cells)} code cells")
        print(f"Testing first {min(max_cells, len(code_cells))} cells...\n")

        # Shared namespace for all cells
        exec_globals = {
            '__name__': '__main__',
        }

        errors = []
        cells_executed = 0

        for i, cell in enumerate(code_cells[:max_cells]):
            # Properly join source with newlines
            if isinstance(cell['source'], list):
                source = '\n'.join(cell['source'])
            else:
                source = cell['source']

            print(f"Cell {i+1}/{min(max_cells, len(code_cells))}...")

            # Skip cells with plotting or interactive display
            skip_patterns = [
                'plt.show()', 'display(', '.show()',
                'sns.heatmap', 'plt.tight_layout',
                'plt.plot', 'plt.figure', 'plt.subplot'
            ]
            if any(pattern in source for pattern in skip_patterns):
                print(f"  ⊘ Skipped (contains plotting/display)")
                continue

            # Skip empty cells
            if not source.strip():
                print(f"  ⊘ Skipped (empty)")
                continue

            try:
                exec(source, exec_globals)
                print(f"  ✓ Executed successfully")
                cells_executed += 1
            except Exception as e:
                error_msg = f"Cell {i+1}: {type(e).__name__}: {str(e)[:200]}"
                errors.append(error_msg)
                print(f"  ✗ Error: {type(e).__name__}")
                print(f"     {str(e)[:150]}")
                break

        # Summary
        print(f"\n{'='*80}")
        if errors:
            print(f"❌ FAILED: {len(errors)} error(s) found")
            for error in errors:
                print(f"  • {error}")
            return {'status': 'FAILED', 'errors': errors, 'cells_tested': cells_executed}
        else:
            print(f"✅ PASSED: All {cells_executed} tested cells executed successfully")
            return {'status': 'PASSED', 'errors': [], 'cells_tested': cells_executed}

    except Exception as e:
        print(f"\n❌ FAILED: Could not process notebook")
        print(f"Error: {type(e).__name__}: {str(e)}")
        return {'status': 'FAILED', 'errors': [str(e)], 'cells_tested': 0}

if __name__ == '__main__':
    # Change to notebooks directory so Path.cwd().parent points to ARBS root
    script_dir = Path(__file__).parent
    notebooks_dir = script_dir / 'notebooks'

    if not notebooks_dir.exists():
        print(f"Error: notebooks directory not found at {notebooks_dir}")
        sys.exit(1)

    # Change working directory to notebooks/
    os.chdir(notebooks_dir)
    print(f"Working directory: {Path.cwd()}")
    print(f"Parent directory: {Path.cwd().parent}")
    print()

    notebooks_to_test = [
        '10_vol_arbitrage_strategy.ipynb',
        '12_risk_parity_strategy.ipynb',
        '13_stat_arb_pairs_trading.ipynb',
        '15_adaptive_strategy_selection.ipynb',
    ]

    results = {}
    for notebook in notebooks_to_test:
        results[notebook] = test_notebook_sequential(notebook, max_cells=8)

    # Final summary
    print(f"\n{'='*80}")
    print("FINAL SUMMARY")
    print(f"{'='*80}\n")

    passed = sum(1 for r in results.values() if r['status'] == 'PASSED')
    failed = len(results) - passed

    for notebook, result in results.items():
        status_symbol = '✅' if result['status'] == 'PASSED' else '❌'
        cells_info = f"({result.get('cells_tested', 0)} cells)"
        print(f"{status_symbol} {notebook}: {result['status']} {cells_info}")

    print(f"\nTotal: {passed} passed, {failed} failed out of {len(results)} notebooks\n")

    if passed == len(results):
        print("🎉 ALL NOTEBOOKS PASSED! 🎉\n")

    # Exit with error code if any failed
    sys.exit(0 if failed == 0 else 1)
