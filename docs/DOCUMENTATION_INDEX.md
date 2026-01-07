# ARBS Project - Comprehensive Documentation Index

**Awesome Rates Backtesting System (ARBS)**
Complete Documentation Library

Last Updated: 2025-11-10
Version: 1.0

---

## 📚 Quick Navigation

| For... | Start Here | Then Read |
|--------|-----------|-----------|
| **New Users** | [Quick Start Guide](QUICK_START_GUIDE.md) → [Getting Started](GETTING_STARTED.md) | [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md) |
| **Developers** | [Project Overview](#project-overview) → [Architecture](#architecture-overview) | [Module Documentation](#core-modules) |
| **Researchers** | [Notebooks Guide](NOTEBOOKS_DOCUMENTATION_START_HERE.md) | [RVUtils Analytics](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md) |
| **System Admins** | [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md) → [Setup Checklist](SETUP_CHECKLIST.md) | [Caching Configuration](CACHING_MODULE_ANALYSIS.md) |
| **Quick Reference** | [Cheat Sheets](#quick-reference-guides) | [API References](#api-documentation) |

---

## 📖 Table of Contents

1. [Project Overview](#project-overview)
2. [Getting Started](#getting-started)
3. [Installation & Setup](#installation--setup)
4. [Architecture Overview](#architecture-overview)
5. [Core Modules](#core-modules)
6. [Supporting Modules](#supporting-modules)
7. [Notebooks & Examples](#notebooks--examples)
8. [API Documentation](#api-documentation)
9. [Quick Reference Guides](#quick-reference-guides)
10. [Advanced Topics](#advanced-topics)
11. [Troubleshooting](#troubleshooting)
12. [Contributing & Extending](#contributing--extending)
13. [External Resources](#external-resources)

---

## 🎯 Project Overview

### What is ARBS?

ARBS (Awesome Rates Backtesting System) is a **product-agnostic, adapter-based backtesting framework** for pricing and evaluating interest rate derivatives. Built with Python 3.13, it separates product logic from core engines through a clean adapter pattern.

### Key Features

- **Product-Agnostic Design**: Core backtesting engine works with any product via adapters
- **Multiple Data Sources**: CME, SDR, GSQUANT, and more
- **Dual Curve Backends**: QuantLib and RatesLib support
- **Persistent Caching**: ZODB-based caching for performance
- **Comprehensive Analytics**: 15+ interpolation methods, regression, hedging utilities
- **Modular Architecture**: Clean separation of concerns

### Documentation

- **Main README**: [README.md](README.md) - Original project documentation (17.7 KB)
- **Documentation Summary**: [DOCUMENTATION_SUMMARY.md](DOCUMENTATION_SUMMARY.md) - Overview of all modules

### Project Statistics

- **Total Python Code**: 56,684 lines across 121 files
- **Documentation**: 20,000+ lines across 50+ files
- **Modules**: 7 core modules + 4 supporting modules
- **Notebooks**: 11 Jupyter notebooks with examples
- **Dependencies**: 23+ external libraries

---

## 🚀 Getting Started

### For First-Time Users

1. **Quick Start** (5 minutes)
   - [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) - Get up and running immediately

2. **Getting Started** (30 minutes)
   - [GETTING_STARTED.md](GETTING_STARTED.md) - Comprehensive introduction with learning paths

3. **First Backtest** (15 minutes)
   - [Notebooks Getting Started](NOTEBOOKS_DOCUMENTATION_START_HERE.md) - Run your first backtest

### Learning Paths

**Beginner Path** (3-4 hours)
1. Read [GETTING_STARTED.md](GETTING_STARTED.md)
2. Follow [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)
3. Try `simple_irswaps_backtest.ipynb` notebook
4. Read [BT Quick Reference](docs/BT_QUICK_REFERENCE.md)

**Intermediate Path** (6-8 hours)
1. Complete Beginner Path
2. Study [Query Module Guide](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md)
3. Read [MDP Analysis](docs/MDP_COMPREHENSIVE_ANALYSIS.md)
4. Work through `month_end_irswaps_backtest.ipynb`
5. Explore [TB Module](TB_MODULE_DOCUMENTATION.md)

**Advanced Path** (10-15 hours)
1. Complete Intermediate Path
2. Deep dive into [Caching Architecture](CACHING_MODULE_ANALYSIS.md)
3. Study [RVUtils Analytics](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md)
4. Implement custom products following [Query Extension Guide](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md#extending-the-system)
5. Build custom strategies with `fomc_fly_backtest.ipynb`

---

## 🔧 Installation & Setup

### Installation Documentation

| Document | Purpose | Time |
|----------|---------|------|
| [README_INSTALLATION.md](README_INSTALLATION.md) | Quick installation overview | 5 min |
| [INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md) | Complete installation reference | 1 hour |
| [INSTALLATION_GUIDE_INDEX.md](INSTALLATION_GUIDE_INDEX.md) | Navigation for installation docs | - |
| [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) | Interactive verification checklist | 15 min |

### Configuration Files

**Example Configurations** (Ready to copy):
- `.env.example` - Environment variables
- `config/settings.example.yaml` - YAML configuration
- `Dockerfile.example` - Docker container
- `docker-compose.example.yml` - Docker Compose
- `arbs-backtest.service.example` - Systemd service
- `arbs-backtest.timer.example` - Systemd timer

### Dependency Files

- `requirements.txt` - Original dependencies
- `requirements-prod.txt` - Production dependencies
- `requirements-dev.txt` - Development tools
- `requirements-ci.txt` - CI/CD dependencies

### Quick Install

```bash
# Clone and install
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
python3.13 -m venv arbs_env
source arbs_env/bin/activate
pip install -r requirements.txt

# Verify installation
python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓ Ready!')"
```

See [INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md) for complete instructions.

---

## 🏗️ Architecture Overview

### System Architecture

ARBS follows a **layered architecture** with clean separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│  User Code / Jupyter Notebooks                          │
├─────────────────────────────────────────────────────────┤
│  Backtesting Engines (BT)                               │
│  - QueryDrivenBacktest                                  │
│  - EventDrivenBacktest                                  │
├─────────────────────────────────────────────────────────┤
│  Product Abstraction Layer (Query)                      │
│  - BaseQuery (ABC)                                      │
│  - Product Adapters (IRS, Bonds, etc.)                 │
├─────────────────────────────────────────────────────────┤
│  Market Data Providers (MDP)                            │
│  - CME EOD, SDR Intraday, GSQUANT                      │
├─────────────────────────────────────────────────────────┤
│  Curve Backends                                         │
│  - QuantLib    - RatesLib                              │
├─────────────────────────────────────────────────────────┤
│  Persistent Caching (ZODB)                             │
└─────────────────────────────────────────────────────────┘
```

### Key Design Patterns

- **Adapter Pattern**: Product-agnostic query interface
- **Strategy Pattern**: Composable triggers and actions
- **Provider Pattern**: Pluggable market data sources
- **Repository Pattern**: ZODB persistent storage
- **Factory Pattern**: Curve and pricer builders

### Documentation

- [Architecture Deep Dive](README.md#architecture) - Detailed architecture explanation
- [Data Flow Diagrams](CACHING_ARCHITECTURE_DIAGRAMS.md) - Visual system flows

---

## 🎯 Core Modules

### 1. BT (Backtesting Engine)

**Purpose**: Event loop orchestration, order execution, portfolio accounting, P&L tracking

**Documentation**:
- 📘 [BT_MODULE_DOCUMENTATION.md](docs/BT_MODULE_DOCUMENTATION.md) (2,286 lines) - Complete reference
- 📄 [BT_QUICK_REFERENCE.md](docs/BT_QUICK_REFERENCE.md) (223 lines) - Quick lookup
- 📑 [BT_DOCUMENTATION_INDEX.md](docs/BT_DOCUMENTATION_INDEX.md) (289 lines) - Navigation
- 📋 [README_BT_DOCUMENTATION.txt](docs/README_BT_DOCUMENTATION.txt) (352 lines) - Overview

**Key Classes**:
- `QueryDrivenBacktest` - Product-agnostic backtesting with queries
- `EventDrivenBacktest` - General-purpose backtesting with concrete instruments
- `QueryStrategy` - Compose triggers and actions
- `QueryPortfolio` - Track resolved query positions
- `Trigger`, `Action` - Event-driven strategy components

**Code Location**: `BT/` directory (14 files, ~1,500 LOC)

**When to Read**: Required for anyone running backtests

---

### 2. Query (Product Abstraction)

**Purpose**: Product-agnostic query interface and adapter pattern

**Documentation**:
- 📘 [QUERY_MODULE_COMPREHENSIVE_GUIDE.md](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md) (2,399 lines) - Complete guide
- 📄 [QUERY_QUICK_REFERENCE.md](docs/QUERY_QUICK_REFERENCE.md) (315 lines) - Quick reference
- 📑 [QUERY_DOCUMENTATION_SUMMARY.md](docs/QUERY_DOCUMENTATION_SUMMARY.md) (478 lines) - Summary

**Key Concepts**:
- `BaseQuery` - Product-agnostic query ABC
- `ProductAdapter` - Adapter registration and base class
- `Structure Map` - Define product structures (OUTRIGHT, FLY, CURVE, etc.)
- `Value Map` - Define value calculations (RATE, NPV, PV01, etc.)
- Product Implementations: IRSwaps, FixedRateBonds

**Code Location**: `Query/` directory (45+ files, ~2,500 LOC)

**When to Read**: Required for extending with new products or understanding query resolution

---

### 3. MDP (Market Data Providers)

**Purpose**: Historical and point-in-time curve construction from multiple sources

**Documentation**:
- 📘 [MDP_COMPREHENSIVE_ANALYSIS.md](docs/MDP_COMPREHENSIVE_ANALYSIS.md) (1,514 lines) - Complete analysis
- 📄 [MDP_SUMMARY.md](docs/MDP_SUMMARY.md) (381 lines) - Quick summary

**Supported Sources**:
- **CME EOD**: End-of-day swap rates (QuantLib & RatesLib)
- **SDR Intraday**: Real-time swap rates from SDR
- **GSQUANT**: Goldman Sachs Quant data
- **Fixed Income**: FedInvest, WSJ, Webull, Public.com

**Key Classes**:
- `MarketDataProvider[T]` - Abstract base class
- `IRSwapsMDP` - Interest rate swaps provider
- `FixedRateBondsMDP` - Treasury and bond provider

**Code Location**: `MDP/` directory (50+ files, ~3,000 LOC)

**When to Read**: Required for adding new data sources or understanding curve construction

---

### 4. Caching (Persistent Storage)

**Purpose**: ZODB-based persistent caching for expensive curve constructions and valuations

**Documentation**:
- 📘 [CACHING_MODULE_ANALYSIS.md](CACHING_MODULE_ANALYSIS.md) (1,253 lines) - Technical analysis
- 📊 [CACHING_ARCHITECTURE_DIAGRAMS.md](CACHING_ARCHITECTURE_DIAGRAMS.md) (646 lines) - Architecture diagrams
- 💡 [CACHING_EXAMPLES_AND_TROUBLESHOOTING.md](CACHING_EXAMPLES_AND_TROUBLESHOOTING.md) (998 lines) - Examples & troubleshooting
- 📑 [CACHING_DOCUMENTATION_INDEX.md](CACHING_DOCUMENTATION_INDEX.md) (451 lines) - Navigation
- 📋 [CACHING_DOCUMENTATION_SUMMARY.txt](CACHING_DOCUMENTATION_SUMMARY.txt) - Executive summary

**Key Features**:
- ZODB FileStorage with ACID guarantees
- B-Tree indexing for large datasets
- Connection pooling and thread safety
- Deterministic key generation
- Reference counting and lifecycle management

**Code Location**: `Caching/` directory (4 files, ~900 LOC)

**When to Read**: Required for performance optimization and understanding determinism

---

## 🔌 Supporting Modules

### 5. RVUtils (Analytics & Research)

**Purpose**: Research utilities for rates analysis (interpolation, regression, hedging, visualization)

**Documentation**:
- 📘 [RVUTILS_COMPREHENSIVE_DOCUMENTATION.md](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md) (1,738 lines) - Complete reference
- 📄 [RVUTILS_QUICK_REFERENCE.md](RVUTILS_QUICK_REFERENCE.md) (385 lines) - Quick reference
- 📑 [RVUTILS_DOCUMENTATION_INDEX.md](RVUTILS_DOCUMENTATION_INDEX.md) - Navigation
- 📋 [README_RVUTILS_DOCUMENTATION.txt](README_RVUTILS_DOCUMENTATION.txt) - Overview

**Key Capabilities**:
- **15+ Interpolation Methods**: Nelson-Siegel, Svensson, Smith-Wilson, splines
- **Regression**: OLS, WLS, GLS, TLS, PCR
- **Seasonality**: Month-end and quarter-end patterns
- **Hedging**: ARBL hedge ratio calculation
- **Visualization**: Dual-axis plots, OU forecasting bands

**Code Location**: `RVUtils/` directory (20 files, ~1,500 LOC)

**When to Read**: For analytics, curve fitting, and quantitative research

---

### 6. TB (Toolbox)

**Purpose**: Bulk evaluation over time grids with parallel execution and caching

**Documentation**:
- 📘 [TB_MODULE_DOCUMENTATION.md](TB_MODULE_DOCUMENTATION.md) (2,129 lines) - Complete reference
- 📄 [TB_MODULE_QUICK_REFERENCE.md](TB_MODULE_QUICK_REFERENCE.md) (378 lines) - Quick reference
- 📑 [TB_MODULE_INDEX.md](TB_MODULE_INDEX.md) - Navigation
- 📑 [DOCUMENTATION_SUMMARY.md](DOCUMENTATION_SUMMARY.md) - Summary

**Key Classes**:
- `IRSwapsTB` - Bulk IRS evaluation with threading and ZODB
- `FixedRateBondsTB` - Bulk bond evaluation
- `TimeseriesBuilder` - Build time-series from queries

**Code Location**: `TB/` directory (4 files, ~600 LOC)

**When to Read**: For batch processing and time-series analysis

---

### 7. Definitions (Product Metadata)

**Purpose**: Curve definitions, calendars, conventions, reference rates

**Documentation**:
- 📘 [DEFINITIONS_COMPREHENSIVE_REFERENCE.md](docs/DEFINITIONS_COMPREHENSIVE_REFERENCE.md) (1,556 lines) - Complete reference
- 📄 [README_DEFINITIONS.md](docs/README_DEFINITIONS.md) (447 lines) - Getting started
- 📑 [DEFINITIONS_INDEX.md](docs/DEFINITIONS_INDEX.md) (586 lines) - Navigation & FAQ
- 📋 [DEFINITIONS_DOCUMENTATION_SUMMARY.md](docs/DEFINITIONS_DOCUMENTATION_SUMMARY.md) (364 lines) - Summary

**Coverage**:
- **9+ Curve Definitions**: USD-SOFR, USD-OIS, EUR-EURIBOR, CAD-CORRA, etc.
- **Conventions**: Day count (ACT/360, ACT/365F, 30E/360), calendars, payment lags
- **SDR UPI Codes**: Complete mappings for all curves
- **Reference Rates**: SOFR, EURIBOR, ESTR, CORRA, TONAR

**Code Location**: `definitions/` directory (2 files, ~250 LOC)

**When to Read**: For understanding market conventions and adding new curves

---

### 8. Utils (Utilities)

**Purpose**: Helper functions for date conversion, formatting, and common operations

**Documentation**:
- 📘 [UTILS_MODULE_DOCUMENTATION.md](UTILS_MODULE_DOCUMENTATION.md) (1,744 lines) - Complete reference
- 📄 [UTILS_QUICK_REFERENCE.md](UTILS_QUICK_REFERENCE.md) (500+ lines) - Quick reference
- 📑 [UTILS_DOCUMENTATION_INDEX.md](UTILS_DOCUMENTATION_INDEX.md) (400+ lines) - Navigation
- 📋 [UTILS_DOCUMENTATION_SUMMARY.txt](UTILS_DOCUMENTATION_SUMMARY.txt) - Summary

**Key Utilities**:
- **40+ Functions**: Date/tenor conversions, QuantLib bridges, formatting
- **7 Utility Modules**: ql_utils, misc, visualization, serialization
- **Interpolation Support**: 28 algorithm variants

**Code Location**: `utils/` directory (multiple files, ~1,300 LOC)

**When to Read**: For understanding helper functions and date operations

---

## 📓 Notebooks & Examples

### Notebook Documentation

- 📘 [NOTEBOOKS_COMPREHENSIVE_GUIDE.md](NOTEBOOKS_COMPREHENSIVE_GUIDE.md) (2,240+ lines) - Complete guide
- 📄 [NOTEBOOKS_DOCUMENTATION_START_HERE.md](NOTEBOOKS_DOCUMENTATION_START_HERE.md) - Entry point
- 📑 [NOTEBOOKS_INDEX.md](NOTEBOOKS_INDEX.md) (400+ lines) - Quick reference
- 📋 [NOTEBOOKS_SUMMARY.txt](NOTEBOOKS_SUMMARY.txt) - Executive summary

### Available Notebooks (11 Total)

**Getting Started**:
1. `simple_irswaps_backtest.ipynb` - Minimal working example (15 min)
2. `month_end_irswaps_backtest.ipynb` - Month-end strategy (30 min)

**Advanced Strategies**:
3. `fomc_fly_backtest.ipynb` - FOMC gap-fly trading (1 hour)
4. `fomc_fly_backtest.py` - Python script version

**Analytics & Research**:
5. `curve_risk_model.ipynb` - Risk modeling (760 KB, advanced)
6. `medium_term_swap_pricer.ipynb` - Swap pricing (741 KB)
7. `usts_rv.ipynb` - UST realized volatility
8. `timeseries_builder.ipynb` - Bulk time-series construction

**Technical Deep Dives**:
9. `curve_builds.ipynb` - Curve building examples
10. `intraday_swaps.ipynb` - Intraday pricing
11. `sfr_cvx.ipynb` - STIR/SFR convexity adjustment

### Learning Paths

**Beginner Path** (3-4 hours):
- Start: `simple_irswaps_backtest.ipynb`
- Then: `month_end_irswaps_backtest.ipynb`
- Finally: `timeseries_builder.ipynb`

**Intermediate Path** (6-8 hours):
- Complete Beginner Path
- Add: `curve_builds.ipynb`
- Add: `medium_term_swap_pricer.ipynb`
- Add: `fomc_pricer.ipynb`

**Advanced Path** (8-10 hours):
- Complete Intermediate Path
- Add: `fomc_fly_backtest.ipynb`
- Add: `curve_risk_model.ipynb`
- Add: `intraday_swaps.ipynb`

---

## 📚 API Documentation

### Quick API References

| Module | Quick Reference | Complete API |
|--------|----------------|--------------|
| **BT** | [BT Quick Reference](docs/BT_QUICK_REFERENCE.md) | [BT Module Docs](docs/BT_MODULE_DOCUMENTATION.md) |
| **Query** | [Query Quick Reference](docs/QUERY_QUICK_REFERENCE.md) | [Query Module Guide](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md) |
| **MDP** | [MDP Summary](docs/MDP_SUMMARY.md) | [MDP Analysis](docs/MDP_COMPREHENSIVE_ANALYSIS.md) |
| **Caching** | [Examples](CACHING_EXAMPLES_AND_TROUBLESHOOTING.md) | [Caching Analysis](CACHING_MODULE_ANALYSIS.md) |
| **RVUtils** | [RVUtils Quick Ref](RVUTILS_QUICK_REFERENCE.md) | [RVUtils Docs](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md) |
| **TB** | [TB Quick Reference](TB_MODULE_QUICK_REFERENCE.md) | [TB Module Docs](TB_MODULE_DOCUMENTATION.md) |
| **Definitions** | [Definitions Index](docs/DEFINITIONS_INDEX.md) | [Definitions Reference](docs/DEFINITIONS_COMPREHENSIVE_REFERENCE.md) |
| **Utils** | [Utils Quick Ref](UTILS_QUICK_REFERENCE.md) | [Utils Documentation](UTILS_MODULE_DOCUMENTATION.md) |

### Common API Patterns

**Running a Backtest**:
```python
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
import Query.IRSwaps.adapter  # Register IRS adapter

# Create backtest
bt = QueryDrivenBacktest(
    time_grid=TimeGrid([...]),
    mdp=IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic"),
    strategy=QueryStrategy(triggers=[...])
)

# Run and analyze
bt.run()
print(bt.mtm_history)
```

See [BT Quick Reference](docs/BT_QUICK_REFERENCE.md) for more examples.

---

## ⚡ Quick Reference Guides

### Cheat Sheets

| Topic | Document | Purpose |
|-------|----------|---------|
| **Installation** | [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) | 5-minute setup |
| **Backtesting** | [BT_QUICK_REFERENCE.md](docs/BT_QUICK_REFERENCE.md) | Common backtest patterns |
| **Queries** | [QUERY_QUICK_REFERENCE.md](docs/QUERY_QUICK_REFERENCE.md) | Query construction |
| **Analytics** | [RVUTILS_QUICK_REFERENCE.md](RVUTILS_QUICK_REFERENCE.md) | Analytics functions |
| **Bulk Evaluation** | [TB_MODULE_QUICK_REFERENCE.md](TB_MODULE_QUICK_REFERENCE.md) | Batch processing |
| **Utilities** | [UTILS_QUICK_REFERENCE.md](UTILS_QUICK_REFERENCE.md) | Helper functions |
| **Setup** | [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) | Verification checklist |

### Common Tasks

**Task: Run a simple backtest**
- See: [BT Quick Reference](docs/BT_QUICK_REFERENCE.md) → "Simple Query-Driven Backtest"

**Task: Add a new curve definition**
- See: [Definitions Reference](docs/DEFINITIONS_COMPREHENSIVE_REFERENCE.md) → "Adding New Curves"

**Task: Extend with new product**
- See: [Query Module Guide](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md) → "Extending the System"

**Task: Optimize performance**
- See: [Caching Examples](CACHING_EXAMPLES_AND_TROUBLESHOOTING.md) → "Performance Tuning"

**Task: Build time-series**
- See: [TB Quick Reference](TB_MODULE_QUICK_REFERENCE.md) → "Bulk Evaluation"

---

## 🎓 Advanced Topics

### Architecture & Design

- [System Architecture](README.md#architecture) - Layered architecture overview
- [Adapter Pattern](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md#product-adapters) - Product abstraction
- [Caching Architecture](CACHING_ARCHITECTURE_DIAGRAMS.md) - 12 detailed diagrams
- [Data Flow](CACHING_ARCHITECTURE_DIAGRAMS.md#sequence-diagrams) - Sequence diagrams

### Performance Optimization

- [Caching Best Practices](CACHING_MODULE_ANALYSIS.md#best-practices) - Optimization strategies
- [Parallel Execution](TB_MODULE_DOCUMENTATION.md#parallel-execution) - Threading patterns
- [Memory Management](CACHING_MODULE_ANALYSIS.md#performance-characteristics) - Memory optimization
- [Bulk Operations](TB_MODULE_QUICK_REFERENCE.md#performance-tips) - Batch processing

### Extending the System

- [Adding New Products](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md#extending-with-swaptions) - Complete Swaption example
- [Adding Data Sources](docs/MDP_COMPREHENSIVE_ANALYSIS.md#adding-new-sources) - Step-by-step guide
- [Custom Value Metrics](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md#value-map) - Define new metrics
- [Custom Triggers](docs/BT_MODULE_DOCUMENTATION.md#triggers) - Event-driven logic

### Research & Analytics

- [Curve Fitting Methods](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md#interpolation-methods) - 15+ methods
- [Statistical Analysis](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md#statistical-analysis) - OU process, volatility
- [Hedging Strategies](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md#hedging-utilities) - Hedge ratio calculation
- [Seasonality Analysis](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md#seasonality-decomposition) - Pattern detection

---

## 🔧 Troubleshooting

### Common Issues

**Installation Issues**:
- See: [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md) → Section 3: "Dependency Troubleshooting"
- See: [Setup Checklist](SETUP_CHECKLIST.md) → Verification steps

**Backtesting Issues**:
- See: [BT Documentation](docs/BT_MODULE_DOCUMENTATION.md) → "Troubleshooting"
- See: [Query Quick Reference](docs/QUERY_QUICK_REFERENCE.md) → "Troubleshooting"

**Caching Issues**:
- See: [Caching Examples](CACHING_EXAMPLES_AND_TROUBLESHOOTING.md) → Section 3-4
- Common: Lock contention, cache invalidation, memory usage

**Data Source Issues**:
- See: [MDP Summary](docs/MDP_SUMMARY.md) → "Common Issues"
- Common: Missing fixings, curve bootstrap failures, API authentication

**Performance Issues**:
- See: [TB Documentation](TB_MODULE_DOCUMENTATION.md) → "Performance Optimization"
- See: [Caching Best Practices](CACHING_MODULE_ANALYSIS.md#best-practices)

### Debug Guides

| Issue Type | Document | Section |
|------------|----------|---------|
| Installation | [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md) | Section 9 |
| Backtesting | [BT Docs](docs/BT_MODULE_DOCUMENTATION.md) | Troubleshooting |
| Queries | [Query Quick Ref](docs/QUERY_QUICK_REFERENCE.md) | Troubleshooting |
| Caching | [Caching Examples](CACHING_EXAMPLES_AND_TROUBLESHOOTING.md) | Sections 3-5 |
| Data Sources | [MDP Summary](docs/MDP_SUMMARY.md) | Common Issues |
| Performance | [TB Docs](TB_MODULE_DOCUMENTATION.md) | Section 8 |
| Notebooks | [Notebooks Index](NOTEBOOKS_INDEX.md) | Troubleshooting |

---

## 🤝 Contributing & Extending

### Extension Guides

**Add a New Product** (e.g., Swaptions):
1. Read: [Query Extension Guide](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md#extending-with-swaptions)
2. Define: Query, Structure, Value classes
3. Implement: Product adapter
4. Register: Adapter with decorator
5. Test: With existing backtesting engine

**Add a New Data Source**:
1. Read: [MDP Extension Guide](docs/MDP_COMPREHENSIVE_ANALYSIS.md#adding-new-sources)
2. Create: Data fetcher
3. Implement: Curve builder
4. Register: With IRSwapsMDP or FixedRateBondsMDP
5. Test: Historical data fetching

**Add a New Curve Definition**:
1. Read: [Definitions Guide](docs/DEFINITIONS_COMPREHENSIVE_REFERENCE.md#adding-new-curves)
2. Define: Metadata (calendar, day count, conventions)
3. Implement: QuantLib builder
4. Implement: RatesLib builder
5. Test: Curve construction

**Add Custom Analytics**:
1. Read: [RVUtils Documentation](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md)
2. Implement: Analysis function
3. Document: Parameters and usage
4. Add: Unit tests
5. Integrate: With existing utilities

### Development Setup

See [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md) → "Development vs Production" section for:
- Development environment setup
- Testing framework
- Code quality tools
- Git workflow
- CI/CD integration

### Documentation Standards

All modules in ARBS follow consistent documentation standards:
- **Comprehensive Guide**: Full technical reference (1,500-2,500 lines)
- **Quick Reference**: Common patterns and API (300-500 lines)
- **Index/Navigation**: Topic-based navigation (300-600 lines)
- **Summary**: Executive overview and statistics

When contributing:
- Update relevant documentation
- Add code examples
- Include troubleshooting tips
- Cross-reference related docs

---

## 🌐 External Resources

### Official Documentation

**ZODB (Object Database)**:
- [Official Tutorial](https://zodb.org/en/latest/tutorial.html)
- [Advanced Guide](https://zodb.org/en/latest/articles/ZODB2.html)
- [GitHub Repository](https://github.com/zopefoundation/ZODB)
- [Tutorials Point Guide](https://www.tutorialspoint.com/python_data_persistence/data_persistence_zodb.htm)

**QuantLib (Pricing Library)**:
- [Yield Curve Bootstrapping](https://www.implementingquantlib.com/2013/10/chapter-3-part-3-of-n-bootstrapping.html)
- [Python Cookbook](https://leanpub.com/quantlibpythoncookbook/read)
- [Term Structures Guide](http://gouthamanbalaraman.com/blog/quantlib-term-structure-bootstrap-yield-curve.html)
- [Official Documentation](https://www.quantlib.org/docs.shtml)

**RatesLib (Fixed Income Library)**:
- [Official Site](https://rateslib.com/)
- [GitHub Repository](https://github.com/attack68/rateslib)
- [Documentation](https://rateslib.com/py/en/1.5.x/i_about.html)
- [PyPI Package](https://pypi.org/project/rateslib/)

### Market Conventions

**SOFR & OIS**:
- [SOFR OIS Pricing](https://btrm.org/wp-content/uploads/2024/03/BTRM-WP15_SOFR-OIS-Curve-Construction_Dec-2020.pdf)
- [ARRC User's Guide to SOFR](https://www.newyorkfed.org/medialibrary/Microsites/arrc/files/2021/users-guide-to-sofr2021-update.pdf)
- [CME Term SOFR Methodology](https://www.cmegroup.com/market-data/files/cme-term-sofr-reference-rates-benchmark-methodology.pdf)

**SDR & UPI**:
- [CME SDR UPI Implementation](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457319121/UPI+Implementation+-+FAQ)
- [Clarus FT SDR Analysis](https://www.clarusft.com/sdr-trading-venues-and-packages/)
- [OpenGamma Conventions Guide](https://quant.opengamma.io/Interest-Rate-Instruments-and-Market-Conventions.pdf)

### Academic Papers

**Nelson-Siegel-Svensson**:
- [Python Implementation Guide](https://thepythonlab.medium.com/advanced-yield-curve-modeling-in-python-implementing-nelson-siegel-and-svensson-models-ad8112c7d433)
- [PyPI Package](https://pypi.org/project/nelson-siegel-svensson/)
- [GitHub Implementations](https://github.com/luphord/nelson_siegel_svensson)

**Interest Rate Derivatives**:
- [Ametrano & Bianchetti: Multiple Interest Rate Curves](http://ssrn.com/abstract=2219548)
- Darbyshire: "Pricing and Trading Interest Rate Derivatives"

### Community Resources

- **Stack Exchange**: [Quantitative Finance](https://quant.stackexchange.com/questions/tagged/quantlib+python)
- **GitHub Issues**: Report bugs and request features
- **Medium Tutorials**: Various authors on QuantLib and RatesLib

---

## 📊 Documentation Statistics

### Coverage Summary

| Module | Files | Lines of Code | Documentation Lines | Doc/Code Ratio |
|--------|-------|---------------|---------------------|----------------|
| **BT** | 14 | 1,500 | 3,150 | 2.1:1 |
| **Query** | 45+ | 2,500 | 3,200 | 1.3:1 |
| **MDP** | 50+ | 3,000 | 2,000 | 0.7:1 |
| **Caching** | 4 | 900 | 3,350 | 3.7:1 |
| **RVUtils** | 20 | 1,500 | 2,650 | 1.8:1 |
| **TB** | 4 | 600 | 2,900 | 4.8:1 |
| **Definitions** | 2 | 250 | 2,500 | 10:1 |
| **Utils** | 7+ | 1,300 | 3,000 | 2.3:1 |
| **Notebooks** | 11 | 3,800 MB | 3,200 | - |
| **Installation** | - | - | 5,500 | - |
| **TOTAL** | 121 | 56,684 | 31,450+ | 0.55:1 |

### Documentation Files

- **Comprehensive Guides**: 11 files (15,000+ lines)
- **Quick References**: 8 files (3,500+ lines)
- **Indexes & Navigation**: 10 files (4,000+ lines)
- **Summaries & Overviews**: 9 files (3,500+ lines)
- **Configuration Examples**: 8 files
- **Notebooks Documentation**: 4 files (3,500+ lines)
- **Installation Guides**: 6 files (5,500+ lines)

**Total Documentation**: 50+ files with 30,000+ lines

---

## 📝 Documentation Maintenance

### Last Updated

- **Date**: 2025-11-10
- **Version**: 1.0
- **Commit**: Initial comprehensive documentation
- **Branch**: `claude/document-project-review-011CUzdXhua2623FvTcCc1ob`

### Maintenance Notes

**Keeping Documentation Current**:
1. Update documentation when adding new features
2. Maintain consistent structure across modules
3. Keep examples working and tested
4. Cross-reference related documentation
5. Update statistics and coverage metrics

**Documentation Standards**:
- Each module has 3-4 documentation files
- Comprehensive guide (1,500-2,500 lines)
- Quick reference (300-500 lines)
- Navigation/index (300-600 lines)
- Summary/overview (optional)

**Review Checklist**:
- [ ] All links working (no orphaned docs)
- [ ] Code examples tested
- [ ] API signatures up to date
- [ ] Cross-references accurate
- [ ] Version numbers current

---

## 🎯 Next Steps

### For New Users

1. **Start Here**: [GETTING_STARTED.md](GETTING_STARTED.md)
2. **Install**: [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)
3. **First Backtest**: [Notebooks Getting Started](NOTEBOOKS_DOCUMENTATION_START_HERE.md)
4. **Learn More**: Choose a [Learning Path](#learning-paths)

### For Developers

1. **Understand Architecture**: [Architecture Overview](#architecture-overview)
2. **Study Core Modules**: [BT](docs/BT_MODULE_DOCUMENTATION.md), [Query](docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md), [MDP](docs/MDP_COMPREHENSIVE_ANALYSIS.md)
3. **Review Examples**: [Notebooks](NOTEBOOKS_COMPREHENSIVE_GUIDE.md)
4. **Extend System**: [Contributing Guide](#contributing--extending)

### For Researchers

1. **Analytics Tools**: [RVUtils Documentation](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md)
2. **Example Notebooks**: [Notebooks Index](NOTEBOOKS_INDEX.md)
3. **Curve Fitting**: [Interpolation Methods](RVUTILS_COMPREHENSIVE_DOCUMENTATION.md#interpolation-methods)
4. **Time-Series Analysis**: [TB Module](TB_MODULE_DOCUMENTATION.md)

### For System Admins

1. **Installation**: [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md)
2. **Configuration**: [Setup Checklist](SETUP_CHECKLIST.md)
3. **Deployment**: [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md) → "Development vs Production"
4. **Monitoring**: [Caching Module](CACHING_MODULE_ANALYSIS.md) → Performance section

---

## 📧 Support & Contact

- **Issues**: Report bugs on GitHub Issues
- **Questions**: See [Troubleshooting](#troubleshooting) section first
- **Contributions**: See [Contributing Guide](#contributing--extending)
- **Documentation**: All docs in this repository

---

## 📜 License

See project LICENSE file for details.

---

**End of Documentation Index**

*This comprehensive index provides navigation to all ARBS documentation. Start with your role-specific guide above, or explore topics of interest. All documentation is cross-referenced and linked for easy navigation.*
