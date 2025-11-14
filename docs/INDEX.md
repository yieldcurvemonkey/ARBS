# ARBS Documentation Index

**Last Updated**: 2025-11-14

## Quick Start

- **README.md** - Project overview and setup
- **CLAUDE.md** - Development guidelines and architecture status
- **notebooks/README.md** - Jupyter notebook catalog (15 examples)

## Architecture

### Core Framework
- **GRINOLD_KAHN_FRAMEWORK.md** - Active Portfolio Management framework overview
- **GRINOLD_KAHN_DETAILED_SPECS.md** - Detailed technical specifications
- **PORTFOLIO_CONSTRUCTION_WORKFLOW.md** - End-to-end workflow examples
- **design/GRINOLD_KAHN_KNOWLEDGE_GRAPH.md** - Concept-to-code mapping
- **COMPOSABLE_PORTFOLIO_ARCHITECTURE.md** - Nested portfolio design

### Backtest System
- **BACKTEST_UNIFIED_API.md** - Primary backtest API documentation
- **FUTURES_BACKTESTING_GUIDE.md** - Futures-specific backtesting
- **workflows/ARXIV_TO_CODE_PLAN.md** - Research paper integration workflow

## User Guides

### Strategy Creation
- **USER_GUIDE_STRATEGY_CREATION.md** - Creating new strategies with YAML
- **ADDING_CUSTOM_COMPONENTS.md** - Extending signals, risk models, optimizers
- **guides/extending_risk_models.md** - Adding new covariance estimators

### Component Documentation
- **ALPHA_GENERATOR.md** - Converting signals to expected returns
- **RETURNS_CALCULATOR.md** - Price-to-returns conversion
- **VOLATILITY_ESTIMATOR.md** - Volatility forecasting
- **SECTOR_COVARIANCE_GUIDE.md** - Sector-based risk models
- **TEAR_SHEET.md** - Performance analysis
- **SIGNAL_COMBINATION_METHODS.md** - Multi-signal strategies
- **RETURNS_VS_PRICES_ANALYSIS.md** - Architectural rationale (returns-first design)

## Implementation Status

### Requirements
- **TRADER_REQUIREMENTS.md** - Trader UX requirements (Phases 2-6 pending)
- **FLAW_REMEDIATION_PLAN.md** - Known issues (75% complete)

### Completion Summaries
- **POLARS_MIGRATION_COMPLETE.md** - Pandas→Polars migration complete
- **ACTUAL_VALIDATION_RESULTS.md** - Recent test validation results
- **FINAL_VERIFICATION_RESULTS.md** - Notebook verification (4 notebooks)
- **HONEST_NOTEBOOK_ASSESSMENT.md** - Notebook quality assessment (10 notebooks)
- **PHASE_3_COMPLETION_SUMMARY.md** - Sector covariance implementation
- **PHASE_4_COMPLETION_SUMMARY.md** - Real data validation
- **PAPER_IMPLEMENTATION_FIDELITY.md** - Research paper implementation verification

## Design Documents

### Data Layer
- **DATA_LAYER_ARCHITECTURE.md** - Market data provider architecture
- **ALPHAVANTAGE_DATA_LAYER_PLAN_CORRECTED.md** - Alpha Vantage integration (40% complete)
- **SCHEMA_INDEX.md** - SQLite schema reference
- **design/YAHOO_FINANCE_MDP_DESIGN.md** - Yahoo Finance integration

### Strategy Frameworks
- **STRATEGY_MODULARIZATION_SUMMARY.md** - YAML-based strategy system
- **MODULARITY_IMPROVEMENTS_PLAN.md** - Factory pattern implementation
- **design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md** - Equity sector extension (15% complete)
- **design/AGENT_ORCHESTRATION_UNIFIED.md** - Multi-agent implementation (40% complete)
- **design/BACKTEST_UNIFICATION_PLAN.md** - Backtest unification proposal (not executed)

### Asset Abstractions
- **ASSET_ABSTRACTION_DESIGN.md** - Futures value structure (70% complete)
- **FUTURES_VALUE_STRUCTURE_DESIGN.md** - Tier 1 complete

## Workflows

- **scripts/README.md** - Utility scripts documentation

## Analysis & Planning

### Current Efforts
- **analysis/CLEANUP_EXECUTION_PLAN.md** - This cleanup effort
- **analysis/REVIEW_PROGRESS.md** - File-by-file review status
- **analysis/REVIEW_SYNTHESIS.md** - Comprehensive findings
- **analysis/START_HERE.md** - Session handoff guide

### Gap Analysis
- **CRITICAL_GAPS_AND_NEXT_STEPS.md** - Production readiness gaps
- **CROSS_ASSET_CONCURRENCY_ANALYSIS.md** - Recent concurrency analysis

## Reference Materials

### External Research
- **docs/references/** - Papers, books, research (32 files) - NOT indexed here
- **docs/research/** - Research notes (10 files) - NOT indexed here
- **docs/resources/** - Resources (2 files) - NOT indexed here

## Archive

Historical documents moved to **docs/archive/**:
- **completed-tasks/** - Finished work summaries (15 files)
- **sessions/** - Session handoff notes (2 files)
- **abandoned-plans/** - Unexecuted plans (6 files)
- **pending-research/** - Future research directions (1 file)
- **analysis-process/** - Analysis artifacts (4 files)

---

## Documentation Health

**Last Review**: 2025-11-14
**Total Active Docs**: 61 files (down from 127)
**Archived**: 28 files
**Deleted**: 18 files
**Critical Bugs Fixed**: 8
**Quality**: All code references verified

---

## Contributing to Documentation

When adding new documentation:

1. **Follow CLAUDE.md naming rules** - No temporal context ("new", "old", "enhanced")
2. **Add ABOUTME comments** - All files start with 2-line description
3. **Update this INDEX.md** - Add your document to appropriate section
4. **Cross-reference related docs** - Link to relevant documentation
5. **Test code examples** - Verify all examples actually work
