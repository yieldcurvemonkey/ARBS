# ARBS Source Code Documentation Index

**Generated:** November 10, 2025  
**Project:** Arbitrage Backtesting System (ARBS)  
**Total Analysis:** 121 Python files, 28,342 lines of code across 8 major modules

---

## Overview

This documentation package provides a comprehensive source code mapping of the ARBS project, including complete directory structure, file descriptions, dependencies, and visual architecture diagrams.

### What's Included

Three detailed documentation files have been created:

1. **SOURCE_CODE_TREE_VISUALIZATION.md** (34 KB)
   - Complete ASCII directory tree with file statistics
   - Module descriptions and layer architecture
   - Comprehensive dependency graph
   - Entry points and interfaces
   - Configuration and design patterns

2. **SOURCE_CODE_ARCHITECTURE_DIAGRAMS.md** (15 KB)
   - 13 detailed Mermaid diagrams
   - System architecture overview
   - Data flow visualizations
   - Module hierarchy and dependencies
   - Workflow pipelines

3. **SOURCE_CODE_QUICK_REFERENCE.md** (13 KB)
   - Quick lookup tables
   - Import path cheat sheet
   - Common workflows
   - Error solutions
   - Performance tips

---

## Quick Navigation

### For Different Use Cases

#### I want to understand the overall architecture
Start here: **SOURCE_CODE_TREE_VISUALIZATION.md**
- Read: "Module Descriptions" section
- Review: "Architecture Diagram (Mermaid)" section
- Understand: "Key Interfaces" section

#### I want to write code/extend the system
Start here: **SOURCE_CODE_QUICK_REFERENCE.md**
- Read: "Import Path Cheat Sheet"
- Read: "Common Workflows"
- Check: "Directory Navigation" for extension points

#### I want detailed data flows and connections
Start here: **SOURCE_CODE_ARCHITECTURE_DIAGRAMS.md**
- View: "System Architecture Overview"
- View: "Data Flow - IR Swaps Backtest"
- View: "Module Dependency Tree"

#### I want file statistics and metadata
Start here: **SOURCE_CODE_TREE_VISUALIZATION.md**
- Read: "Complete Directory Structure (ASCII Tree)"
- Read: "File Statistics"
- Check: "Largest Files by Line Count"

#### I need to debug an error
Start here: **SOURCE_CODE_QUICK_REFERENCE.md**
- Read: "Common Errors & Solutions"
- Check: "Testing/Debugging Commands"
- Review: "Import Path Cheat Sheet" for module access

---

## Document Structure Breakdown

### SOURCE_CODE_TREE_VISUALIZATION.md

| Section | Content |
|---------|---------|
| ASCII TREE | Complete directory structure with all 121 files, organized hierarchically with file sizes and line counts |
| MODULE DESCRIPTIONS | Layer-by-layer explanation of 8 modules and their purposes |
| MERMAID ARCHITECTURE | Full system architecture diagram showing all major components |
| FILE STATISTICS | Largest files, distribution by module, complexity metrics |
| ENTRY POINTS | Scripts and notebooks that serve as entry points |
| DEPENDENCY GRAPH | Tree showing how modules depend on each other |
| KEY INTERFACES | Python signatures for main abstract classes |
| MODULE INTERDEPENDENCIES | Critical path through the system |
| TESTING ENTRY POINTS | Available backtest strategies |
| CONFIGURATION | Environment variables and setup |
| ARCHITECTURE NOTES | Design patterns and extensibility points |

### SOURCE_CODE_ARCHITECTURE_DIAGRAMS.md

| Diagram # | Title | Shows |
|-----------|-------|-------|
| 1 | System Architecture Overview | High-level flow from data sources to results |
| 2 | Data Flow - IR Swaps Backtest | Step-by-step backtest execution |
| 3 | Module Dependency Tree | Package-level dependencies |
| 4 | IR Swaps Module Detail | IRSwaps module internals |
| 5 | Market Data Provider Hierarchy | MDP class hierarchy and sources |
| 6 | Backtesting Engine Flow | Query engine execution loop |
| 7 | Query Resolution Pipeline | How queries become values |
| 8 | Timeseries Builder Architecture | Results aggregation |
| 9 | RVUtils Analysis Tools | Analysis utilities structure |
| 10 | Data Source Integration | 8 data sources to pricing engines |
| 11 | Curve Building Pipeline | SDR_INTRADAY curve construction |
| 12 | Fixed Rate Bond Pricing | Bond pricing workflow |
| 13 | Caching Strategy | Pricer caching mechanisms |

### SOURCE_CODE_QUICK_REFERENCE.md

| Section | Purpose |
|---------|---------|
| Key Files at a Glance | 6 critical files and 3 base classes |
| Module Summary Table | 11 modules with file counts and purposes |
| Import Path Cheat Sheet | 4 common Python import patterns |
| Key Enums and Constants | Data structures for queries and data sources |
| File Dependency Quick Map | How key files depend on each other |
| Common Workflows | 4 step-by-step usage examples |
| Common Errors & Solutions | 5 typical problems and fixes |
| Performance Tips | 6 optimization suggestions |
| Directory Navigation | How to extend the system |
| Data Files & Caches | Where cached data is stored |
| Testing/Debugging Commands | Python snippets for testing |
| Quick Stats | Project metrics at a glance |
| Key Abbreviations | 25 common abbreviations explained |

---

## Key Statistics Summary

### Project Metrics
- **Total Python Files:** 121
- **Total Lines of Code:** 28,342
- **Average File Size:** 234 lines
- **Largest File:** regression.py (1,286 lines)
- **Number of Modules:** 8 major modules

### Distribution
- **definitions/:** 2 files (167 lines)
- **Query/Base/:** 6 files (329 lines)
- **Query/IRSwaps/:** 7 files (1,256 lines)
- **Query/FixedRateBonds/:** 7 files (633 lines)
- **MDP/IRSwaps/:** 40 files (9,421 lines) - LARGEST
- **MDP/FixedRateBonds/:** 7 files (3,532 lines)
- **BT/:** 15 files (946 lines)
- **TB/:** 4 files (1,986 lines)
- **Caching/:** 4 files (745 lines)
- **RVUtils/:** 18 files (7,142 lines)
- **utils/:** 2 files (330 lines)

### Top 5 Largest Files
1. WebullFintechFetcher.py - 1,337 lines
2. regression.py - 1,286 lines
3. plt_timeseries.py - 1,223 lines
4. FixedRateBondsMDP.py - 1,215 lines
5. SDRDataBuilder.py - 1,049 lines

---

## Architecture Layers

### Layer 1: Definitions (definitions/)
- Static product and curve definitions
- 20+ IR swap curves
- Bond product definitions

### Layer 2: Query (Query/)
- Product-agnostic query interface
- 2 product implementations (IRSwaps, FixedRateBonds)
- Structure and value metric enums
- Product adapters

### Layer 3: Market Data (MDP/)
- Abstract market data provider interface
- 8 data sources (CME, FRED, SDR, ERIS, Barchart, Webull, WSJ, FedInvest)
- 40 fetcher/builder files
- Curve caching

### Layer 4: Pricing (Query/backends/)
- 2 pricing engines (QuantLib, RatesLib)
- Bond and swap pricers
- Curve interpolation

### Layer 5: Backtesting (BT/)
- Query-driven backtest engine
- Portfolio tracking
- Strategy interface
- Execution engine

### Layer 6: Timeseries (TB/)
- Results aggregation
- Per-query timeseries building
- Curve snapshots
- Annotation handling

### Layer 7: Caching (Caching/)
- Multi-backend cache
- ZODB persistent storage
- Codec mapping

### Layer 8: Analysis (RVUtils/)
- 10+ curve interpolation methods
- Statistical regression (1,286 lines)
- Timeseries plotting (1,223 lines)
- Volatility and seasonality analysis

---

## How to Use This Documentation

### Step 1: Understand the System
1. Read: SOURCE_CODE_TREE_VISUALIZATION.md → "Module Descriptions"
2. View: SOURCE_CODE_ARCHITECTURE_DIAGRAMS.md → Diagram 1 & 2
3. Check: SOURCE_CODE_QUICK_REFERENCE.md → "Module Summary Table"

### Step 2: Explore Specific Areas
Choose your focus area and go to the relevant document:
- **Data sources:** Tree → "MDP/" section + Diagrams 10, 11
- **Pricing:** Tree → "Query/backends/" section + Architecture notes
- **Backtesting:** Diagrams 2, 6 + Quick Reference → "Common Workflows"
- **Results:** Diagram 8 + Tree → "TimeseriesBuilder" section
- **Analysis:** Diagram 9 + Tree → "RVUtils/" section

### Step 3: Find Specific Files
Use ASCII tree in SOURCE_CODE_TREE_VISUALIZATION.md to locate any file by:
- Module name
- Function name (via search)
- File size (for complexity assessment)

### Step 4: Understand Dependencies
- For class inheritance: Diagrams 4, 5
- For module dependencies: Diagram 3
- For data flow: Diagram 2
- For quick reference: Quick Reference → "File Dependency Quick Map"

### Step 5: Get Started Coding
Follow SOURCE_CODE_QUICK_REFERENCE.md:
1. Pick your use case from "Common Workflows"
2. Copy the code example
3. Consult "Key Enums and Constants" if needed
4. Check "Import Path Cheat Sheet" for module locations

---

## Frequently Looked Up Topics

### Finding the Main Backtest Loop
Files: `BT/query_engine.py` (194 lines)  
Diagram: #6 - Backtesting Engine Flow  
Quick Ref: "Common Workflows" → "Running Custom Strategy"

### Understanding Curve Building
Files: `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/` (multiple)  
Diagram: #11 - Curve Building Pipeline  
Size: ~4,000 lines total

### Adding a New Data Source
Quick Ref: "Directory Navigation" → "To add a new curve"  
Files: `MDP/IRSwaps/CME_NY_EOD_LIVE/` (example structure)

### Debugging Curve Issues
Quick Ref: "Common Errors & Solutions"  
Testing: "Testing/Debugging Commands"  
Diagram: #1 - System Architecture Overview

### Running a Backtest
Quick Ref: "Common Workflows" → "Running FOMC Butterfly Backtest"  
Example: `fomc_fly_backtest.py` (197 lines)  
Diagram: #2 - Data Flow

### Understanding Query Resolution
Diagram: #7 - Query Resolution Pipeline  
Tree: "Query/Base/BaseQuery.py" description  
Code: `Query/IRSwaps/IRSwapQuery.py` (413 lines)

### Analyzing Results
Tree: "TB/" module description  
Diagram: #8 - Timeseries Builder Architecture  
Tools: `RVUtils/` (analysis utilities)

---

## Cross-References

### Files Referenced in Multiple Documents

**BaseQuery.py**
- Tree: Module Descriptions → Layer 1
- Diagrams: #3 (dependency), #6 (backtest), #7 (resolution)
- Quick Ref: Import Path → "Running a Backtest"

**IRSwapsMDP.py**
- Tree: Module Descriptions → Layer 2, File Statistics (rank 7)
- Diagrams: #1, #2, #5, #10
- Quick Ref: Import Path → "Running a Backtest", "Accessing Curves"

**QueryDrivenBacktest**
- Tree: Entry Points, Critical Path
- Diagrams: #1, #2, #6
- Quick Ref: Common Workflows

**TimeseriesBuilder.py**
- Tree: File Statistics (rank 10 largest), Entry Points
- Diagrams: #8
- Quick Ref: Quick Stats

---

## Recommended Reading Order

### For New Users
1. Quick Reference → "Module Summary Table"
2. Tree → "Module Descriptions"
3. Diagrams → #1 (System Overview)
4. Diagrams → #2 (Data Flow)
5. Quick Reference → "Common Workflows"

### For System Architects
1. Tree → "Complete Directory Structure"
2. Diagrams → All (1-13)
3. Tree → "Architecture Notes"
4. Tree → "Module Interdependencies"

### For Developers Extending the System
1. Quick Reference → "Directory Navigation"
2. Tree → Relevant module section
3. Quick Reference → "Import Path Cheat Sheet"
4. Diagrams → Relevant workflow diagram

### For Debugging Issues
1. Quick Reference → "Common Errors & Solutions"
2. Quick Reference → "Testing/Debugging Commands"
3. Diagrams → "Data Flow - IR Swaps Backtest" (#2)
4. Tree → Relevant module section

---

## File Location Reference

All documentation files are located in `/home/user/ARBS/`:

```
/home/user/ARBS/
├── SOURCE_CODE_TREE_VISUALIZATION.md      (34 KB, 948 lines)
├── SOURCE_CODE_ARCHITECTURE_DIAGRAMS.md   (15 KB, 709 lines)
├── SOURCE_CODE_QUICK_REFERENCE.md         (13 KB, 443 lines)
├── SOURCE_CODE_DOCUMENTATION_INDEX.md     (This file)
│
└── [Source code]
    ├── definitions/
    ├── Query/
    ├── MDP/
    ├── BT/
    ├── TB/
    ├── Caching/
    ├── RVUtils/
    ├── utils/
    └── [Notebooks & scripts]
```

---

## Document Statistics

| Document | Size | Lines | Type |
|----------|------|-------|------|
| Tree Visualization | 34 KB | 948 | Comprehensive |
| Architecture Diagrams | 15 KB | 709 | Visual |
| Quick Reference | 13 KB | 443 | Practical |
| **Total** | **62 KB** | **2,100** | **3 docs** |

---

## How This Was Generated

This documentation was automatically generated by:

1. **File discovery:** Found all 121 Python files using recursive search
2. **Metadata collection:** Calculated line counts and file sizes for each file
3. **Code analysis:** Read key files to understand purposes and dependencies
4. **Architecture mapping:** Traced imports and class hierarchies
5. **Documentation creation:** Generated 3 complementary documents with different focuses
6. **Cross-indexing:** Created links between related information

All information is derived from actual source code inspection and static analysis.

---

## Keeping Documentation Updated

When the codebase changes:

1. Add/remove files: Update ASCII tree in Tree Visualization
2. Change module structure: Update module hierarchy in Architecture Diagrams
3. Modify interfaces: Update Key Interfaces section in Tree
4. Add new data source: Update data source list in Diagrams #10
5. New entry points: Update Entry Points section in Tree

For bulk regeneration: Re-run file discovery and analysis tools.

---

## Support & Questions

For questions about:
- **What files do what:** See SOURCE_CODE_TREE_VISUALIZATION.md → ASCII TREE
- **How data flows:** See SOURCE_CODE_ARCHITECTURE_DIAGRAMS.md → Diagrams 1-13
- **How to use the code:** See SOURCE_CODE_QUICK_REFERENCE.md → Common Workflows
- **File dependencies:** See SOURCE_CODE_TREE_VISUALIZATION.md → DEPENDENCY GRAPH
- **Module purposes:** See SOURCE_CODE_TREE_VISUALIZATION.md → MODULE DESCRIPTIONS

---

**Generated:** November 10, 2025  
**Coverage:** 121 Python files, 28,342 lines of code  
**Modules:** 8 major, 11 total packages  
**Data Sources:** 8 integrated sources  
**Documentation Pages:** 4 (including this index)

