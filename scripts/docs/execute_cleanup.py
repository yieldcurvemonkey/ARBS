#!/usr/bin/env python3
# ABOUTME: Executes radical documentation cleanup - deletes junk, consolidates redundant docs
# ABOUTME: Reduces 107 files to ~10 essential documentation files

import os
import shutil
from pathlib import Path

REPO_ROOT = Path("/home/user/ARBS")

# Files to DELETE (development artifacts, not documentation)
DELETE_FILES = [
    # Phase summaries
    "docs/PHASE1_COMPLETE_SUMMARY.md",
    "docs/PHASE_3_COMPLETION_SUMMARY.md",
    "docs/PHASE_4_COMPLETION_SUMMARY.md",
    "docs/PHASE_4_PLAN.md",
    "docs/SESSION_HANDOFF_NEXT_STEPS.md",
    "docs/SESSION_SUMMARY_2025-11-11.md",
    "docs/phase3_common_patterns_analysis.md",

    # Migration docs
    "POLARS_MIGRATION_COMPLETE.md",
    "POLARS_MIGRATION_PLAN.md",
    "docs/GENERIC_BACKTEST_MIGRATION_PLAN.md",
    "docs/MVP_EQUITY_SECTOR_COMPLETE.md",
    "docs/STRATEGY_MODULARIZATION_SUMMARY.md",
    "docs/STRATEGY_NOTEBOOKS_SUMMARY.md",
    "docs/workflows/ARXIV_INTEGRATION_SUMMARY.md",
    "tasks/migration_progress.md",

    # Progress/assessment snapshots
    "docs/GENERIC_BACKTEST_PROGRESS.md",
    "docs/HONEST_NOTEBOOK_ASSESSMENT.md",
    "docs/FINAL_VERIFICATION_RESULTS.md",
    "docs/ACTUAL_VALIDATION_RESULTS.md",
    "docs/ABSTRACTION_VERIFICATION.md",
    "docs/NOTEBOOK_VERIFICATION_RESULTS.md",
    "docs/NOTEBOOKS_FIXED_ASSESSMENT.md",
    "docs/DOCUMENTATION_ASSESSMENT.md",
    "ARCHITECTURE_RECOMMENDATIONS.md",
    "IMPLEMENTATION_NOTE.md",

    # Completed/orphaned plans
    "BACKTEST_UNIFICATION_TASK.md",
    "FLAW_REMEDIATION_PLAN.md",
    "docs/GENERIC_BACKTEST_IMPLEMENTATION_PLAN.md",
    "docs/MODULARITY_IMPROVEMENTS_PLAN.md",
    "docs/DETAILED_UNDERSTANDING_PLAN.md",
    "docs/NEXT_STEPS_PARALLEL_PLAN.md",
    "docs/PDF_PROCESSING_PLAN.md",
    "docs/ACTION_PLAN_DATA_LAYER.md",
    "docs/ALPHAVANTAGE_DATA_LAYER_PLAN_CORRECTED.md",
    "docs/ALPHAVANTAGE_INTEGRATION_SPEC.md",
    "docs/CODEBASE_ASSESSMENT_DATA_LAYER.md",

    # Redundant docs (keep only primary)
    "docs/GRINOLD_KAHN_DETAILED_SPECS.md",  # Keep FRAMEWORK
    "docs/GRINOLD_KAHN_IMPLEMENTATION_GAP_ANALYSIS.md",  # Keep FRAMEWORK
    "docs/BACKTESTING_FUTURES_SWAPS_PLAN.md",  # Keep UNIFIED_API
    "docs/MODULARITY_REVIEW_AND_STRATEGY_TYPES.md",  # Keep USER_GUIDE
    "docs/STRATEGY_MODULARIZATION_DESIGN.md",  # Keep USER_GUIDE

    # Misc orphans
    "docs/AGENT_DOCUMENTATION_STANDARDS.md",
    "docs/SCHEMA_INDEX.md",
    "docs/VERIFIED_INTEGRATIONS.md",
    "docs/ORTHOGONAL_TASK_DECOMPOSITION.md",
    "docs/PAPER_IMPLEMENTATION_FIDELITY.md",
    "docs/CRITICAL_GAPS_AND_NEXT_STEPS.md",
    "docs/CROSS_ASSET_CONCURRENCY_ANALYSIS.md",
    "tasks/notes-to-claude.md",
    "tests/validation/DATA_LOADING_INSTRUCTIONS.md",
    "CODEBASE_ANALYSIS.md",
    "INSTALLATION_STATUS.md",
    "TODO.md",
]

def execute_cleanup(dry_run=True):
    """Execute documentation cleanup"""

    deleted = []
    not_found = []

    print(f"# Documentation Cleanup\n")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}\n")

    for file_path in DELETE_FILES:
        full_path = REPO_ROOT / file_path

        if full_path.exists():
            if dry_run:
                print(f"Would delete: {file_path}")
                deleted.append(file_path)
            else:
                full_path.unlink()
                print(f"Deleted: {file_path}")
                deleted.append(file_path)
        else:
            not_found.append(file_path)

    print(f"\n## Summary")
    print(f"Files to delete: {len(DELETE_FILES)}")
    print(f"Files found: {len(deleted)}")
    print(f"Files not found: {len(not_found)}")

    if not_found:
        print(f"\n## Not Found:")
        for f in not_found:
            print(f"- {f}")

    return deleted, not_found

if __name__ == '__main__':
    import sys
    dry_run = '--execute' not in sys.argv
    execute_cleanup(dry_run=dry_run)
