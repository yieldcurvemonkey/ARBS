# ARBS Jupyter Notebooks - START HERE

## Welcome!

You have just received comprehensive documentation for all 11 Jupyter notebooks in the ARBS (Arbitrage Rate Based Systems) project. This document will guide you to the right place based on your needs.

---

## Three Documentation Files Available

### 1. **NOTEBOOKS_COMPREHENSIVE_GUIDE.md** (59 KB, 2,240+ lines)
   **Use this when**: You want deep, detailed information about every aspect of the notebooks
   
   **Contains**:
   - Complete analysis of all 11 notebooks
   - 10 documentation points for each notebook:
     1. Purpose and learning objectives
     2. Key concepts demonstrated
     3. Data sources and requirements
     4. Step-by-step walkthroughs with code
     5. Results and insights
     6. Code examples and techniques
     7. Integration with ARBS modules
     8. How to run each notebook
     9. Dependencies and prerequisites
     10. Outputs and visualizations
   - Architecture overview
   - Common patterns and best practices
   - Troubleshooting guide
   - Performance considerations

### 2. **NOTEBOOKS_INDEX.md** (11 KB, 400+ lines)
   **Use this when**: You need quick reference, navigation, or learning paths
   
   **Contains**:
   - Summary table of all 11 notebooks
   - Three learning paths (Beginner, Intermediate, Advanced)
   - Notebooks organized by category
   - Key concepts quick reference
   - Data sources matrix
   - ARBS module usage patterns
   - Common code patterns
   - Quick troubleshooting links

### 3. **NOTEBOOKS_SUMMARY.txt** (16 KB)
   **Use this when**: You want executive overview or quick facts
   
   **Contains**:
   - Project statistics
   - Notebooks organized by category
   - Key concepts and metrics reference
   - ARBS modules usage matrix
   - Data sources and providers
   - Learning path summaries
   - Common code patterns
   - Performance characteristics
   - Troubleshooting reference

---

## Quick Navigation

### I'm New to ARBS - Where Do I Start?

1. **Read first**: NOTEBOOKS_SUMMARY.txt (5 minutes)
   - Get oriented on the project
   - Understand the 11 notebooks at a glance

2. **Choose path**: NOTEBOOKS_INDEX.md - "Learning Path Recommendations" (10 minutes)
   - Beginner Path: 3-4 hours to master basics
   - Intermediate Path: 6-8 hours for advanced analysis
   - Advanced Path: 8-10 hours for strategy development

3. **Follow path**: Execute notebooks in order, using NOTEBOOKS_COMPREHENSIVE_GUIDE.md for details

### I Know ARBS - I Need Info on Specific Notebooks

1. **Find notebook**: NOTEBOOKS_INDEX.md - "Notebook Catalog by Category"
2. **Get details**: NOTEBOOKS_COMPREHENSIVE_GUIDE.md - Find section for that notebook
3. **Run it**: Follow "How to Run" instructions in comprehensive guide

### I Need Quick Code Reference

1. **Check**: NOTEBOOKS_INDEX.md - "Common Code Patterns" section
2. **Or search**: NOTEBOOKS_COMPREHENSIVE_GUIDE.md for specific pattern
3. **Copy/modify**: Adapt patterns to your needs

### I'm Having Problems

1. **Quick help**: NOTEBOOKS_SUMMARY.txt - "Troubleshooting Reference"
2. **Detailed help**: NOTEBOOKS_COMPREHENSIVE_GUIDE.md - "Troubleshooting" section
3. **Find data issue**: NOTEBOOKS_INDEX.md - "Data Sources Reference"

---

## The 11 Notebooks at a Glance

**Foundations** (Start here)
- curve_builds.ipynb - Learn curve construction
- simple_irswaps_backtest.ipynb - Basic backtesting

**Data Collection**
- timeseries_builder.ipynb - Historical data collection
- intraday_swaps.ipynb - Minute-level data

**Analytics**
- usts_rv.ipynb - Treasury curves and volatility
- sfr_cvx.ipynb - STIR futures analysis
- curve_risk_model.ipynb - Portfolio risk measurement

**Pricing**
- fomc_pricer.ipynb - FOMC-dated instrument pricing
- medium_term_swap_pricer.ipynb - Complex curves

**Strategies** (Advanced)
- month_end_irswaps_backtest.ipynb - Seasonality strategy
- fomc_fly_backtest.ipynb - FOMC meeting strategy

---

## Documentation Statistics

| Metric | Value |
|--------|-------|
| Total Lines of Documentation | 2,240+ |
| Code Examples | 150+ |
| Notebooks Analyzed | 11 |
| Data Sources Covered | 6 |
| ARBS Modules Documented | 5 |
| Learning Paths Provided | 3 |

---

## What You'll Learn

### Fixed Income Basics
- Interest rate curve construction
- Swap pricing and valuation
- Bond analysis and YTM calculations
- Asset-swap spread analysis

### Advanced Analytics
- Realized volatility calculations
- Regression analysis (OLS, TLS, Deming)
- Seasonality pattern detection
- Curve interpolation (B-spline, LOESS)

### Risk Measurement
- Key rate duration calculations
- Portfolio Greeks (delta, gamma, vega)
- Risk basis functions
- Sensitivities to curve movements

### Trading Strategies
- Seasonality-based strategies
- Carry-based entry/exit signals
- Fly spread trading
- FOMC-aware positioning

### Data Science
- Multi-source data integration
- High-frequency data handling
- Time series analysis
- Visualization techniques

---

## Key ARBS Concepts You'll Encounter

### Data Flow
```
Data Sources → MDP → Query → Pricing → TB → Analysis/BT
```

### Curve Types
- **USD-SOFR-1D**: SOFR OIS overnight forwards
- **USD-FEDFUNDS**: Federal Funds OIS
- Built from STIR futures, OIS swaps, bonds

### Structures
- **OUTRIGHT**: Single instrument
- **CURVE**: Two-leg spread (e.g., 2Y vs 10Y)
- **FLY**: Three-leg butterfly (e.g., 2Y/5Y/10Y)

### Values (Metrics)
- RATE, NPV, PV01, CVX_ADJ, MMSS, CARRY_BPS_RUNNING

---

## Getting Started Checklist

- [ ] Install Python 3.8+ with required libraries
- [ ] Read NOTEBOOKS_SUMMARY.txt for overview
- [ ] Choose learning path from NOTEBOOKS_INDEX.md
- [ ] Start with first notebook in your path
- [ ] Reference NOTEBOOKS_COMPREHENSIVE_GUIDE.md as needed
- [ ] Modify parameters and experiment
- [ ] Move through learning path sequentially

---

## Common Use Cases

**"I want to analyze Treasury curves"**
→ Start with usts_rv.ipynb, use NOTEBOOKS_COMPREHENSIVE_GUIDE.md Section 5

**"I want to build a trading strategy"**
→ Follow Advanced Path in NOTEBOOKS_INDEX.md

**"I need to understand interest rate risk"**
→ Start with curve_risk_model.ipynb, use Section 9 of comprehensive guide

**"I want to collect historical data"**
→ Use timeseries_builder.ipynb, see Section 2 of comprehensive guide

**"I'm having technical issues"**
→ See Troubleshooting in NOTEBOOKS_COMPREHENSIVE_GUIDE.md

---

## Pro Tips

1. **Start small**: Run notebooks on shorter date ranges first
2. **Parallelize**: Increase `n_jobs` parameter for faster data collection
3. **Cache data**: Avoid re-downloading when possible
4. **Test locally**: Modify parameters locally before production use
5. **Monitor memory**: Large timeseries can use significant RAM
6. **Refer often**: Bookmark NOTEBOOKS_INDEX.md for quick lookups
7. **Explore**: Try modifying curves, tenors, date ranges
8. **Document**: Add comments explaining your modifications

---

## File Locations

```
/home/user/ARBS/
├── NOTEBOOKS_COMPREHENSIVE_GUIDE.md  ← Full detailed reference
├── NOTEBOOKS_INDEX.md                 ← Quick reference & navigation
├── NOTEBOOKS_SUMMARY.txt              ← Executive summary
└── NOTEBOOKS_DOCUMENTATION_START_HERE.md  ← This file

Plus 11 Jupyter notebooks:
├── curve_builds.ipynb
├── timeseries_builder.ipynb
├── sfr_cvx.ipynb
├── intraday_swaps.ipynb
├── usts_rv.ipynb
├── fomc_pricer.ipynb
├── medium_term_swap_pricer.ipynb
├── month_end_irswaps_backtest.ipynb
├── curve_risk_model.ipynb
├── simple_irswaps_backtest.ipynb
└── fomc_fly_backtest.ipynb
```

---

## Next Steps

**Choose your path:**

1. **Immediate use** (5 min)
   - Read: NOTEBOOKS_SUMMARY.txt
   - Reference: NOTEBOOKS_INDEX.md

2. **Learning** (3-10 hours)
   - Pick path: NOTEBOOKS_INDEX.md
   - Execute: Notebooks in order
   - Consult: NOTEBOOKS_COMPREHENSIVE_GUIDE.md

3. **Deep dive** (1-2 days)
   - Read: Full NOTEBOOKS_COMPREHENSIVE_GUIDE.md
   - Practice: Modify and experiment
   - Build: Custom analyses

---

## Questions & Support

**For notebook details:**
- See NOTEBOOKS_COMPREHENSIVE_GUIDE.md

**For quick reference:**
- See NOTEBOOKS_INDEX.md

**For troubleshooting:**
- See Troubleshooting sections in either guide

**For code examples:**
- See Code Examples in comprehensive guide
- See Common Code Patterns in index

---

## Document Version

- **Created**: November 2025
- **Version**: 1.0
- **Notebooks Documented**: 11
- **Documentation Lines**: 2,240+
- **Code Examples**: 150+

---

## Ready to Begin?

1. Open NOTEBOOKS_SUMMARY.txt for orientation
2. Pick your learning path from NOTEBOOKS_INDEX.md
3. Start with first notebook, use NOTEBOOKS_COMPREHENSIVE_GUIDE.md for reference
4. Experiment, learn, and enjoy!

---

**Welcome to ARBS documentation!**

For detailed information, see the comprehensive guide. For quick lookups, use the index.

