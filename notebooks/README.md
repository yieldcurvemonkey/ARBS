# ARBS Jupyter Notebooks for Researchers

Welcome to the ARBS notebook collection! These interactive notebooks are designed for researchers and analysts who want to use the ARBS framework **without writing code**.

## 📚 Notebooks Overview

### **Part 1: Getting Started (01-04)**

#### 1. Getting Started (`01_getting_started.ipynb`)
**Start here if you're new to ARBS!**

- Learn how to load pre-built trading strategies
- Run your first backtest
- Understand key performance metrics
- Modify basic parameters
- Visualize results

**Time**: 15-20 minutes | **Prerequisites**: None | **Difficulty**: ⭐ Beginner

---

#### 2. Strategy Comparison (`02_strategy_comparison.ipynb`)
**Compare multiple strategies side-by-side**

- Test different strategy types (carry, momentum, multi-signal)
- Create comparison tables and charts
- Analyze risk-return profiles
- Identify which strategy is best for your needs

**Time**: 20-30 minutes | **Prerequisites**: Notebook 01 | **Difficulty**: ⭐ Beginner

---

#### 3. Parameter Tuning (`03_parameter_tuning.ipynb`)
**Find optimal strategy settings**

- Systematic parameter testing
- Grid search for best combinations
- Visualize parameter sensitivity
- Test robustness across market conditions
- Avoid overfitting pitfalls

**Time**: 30-40 minutes | **Prerequisites**: Notebooks 01-02 | **Difficulty**: ⭐⭐ Intermediate

---

#### 4. Results Analysis (`04_results_analysis.ipynb`)
**Deep dive into performance analytics**

- Create professional performance tear sheets
- Calculate advanced risk metrics (VaR, CVaR, Calmar ratio)
- Analyze portfolio composition and turnover
- Export PDF reports and CSV data
- Publication-quality visualizations

**Time**: 30-40 minutes | **Prerequisites**: Notebooks 01-03 | **Difficulty**: ⭐⭐ Intermediate

---

### **Part 2: Component Integration (05)**

#### 5. Cross-Asset Integration (`05_cross_asset_integration.ipynb`)
**How different components work together**

- Cluster-aware portfolio construction
- Volatility dispersion trading
- Currency carry signals
- ML-enhanced factors
- CVaR tail risk constraints

**Time**: 40-50 minutes | **Prerequisites**: Notebooks 01-04 | **Difficulty**: ⭐⭐⭐ Advanced

---

### **Part 3: Complete Strategy Demonstrations (06-15)**

#### 6. Carry Strategy (`06_carry_strategy_complete.ipynb`) 🔥
**End-to-end carry trading for futures**

**Strategy**: Calendar spread carry (contango/backwardation)
**Key Insight**: Contracts with higher carry outperform over time

- Yield curve structure across regimes
- Annualized carry signal calculation
- IC × Vol × Z alpha generation
- Complete backtest with TearSheet
- Sensitivity analysis (risk aversion)

**Time**: 45 minutes | **Difficulty**: ⭐⭐ Intermediate | **IC Target**: 0.03-0.06

---

#### 7. Momentum Strategy (`07_momentum_strategy_complete.ipynb`) 🔥
**Multi-period time-series and cross-sectional momentum**

**Strategy**: Trend-following across multiple lookbacks
**Key Insight**: Past winners continue winning (Moskowitz 2012)

- 4 lookback periods (5, 10, 20, 60 days)
- TSMOM vs XSMOM comparison
- 3 signal combination methods
- Transaction cost sensitivity
- Turnover analysis

**Time**: 50 minutes | **Difficulty**: ⭐⭐⭐ Advanced | **Turnover**: High

---

#### 8. Multi-Factor Strategy (`08_multi_factor_strategy.ipynb`) 🔥
**Combining carry + momentum + mean reversion**

**Strategy**: Diversified multi-factor approach
**Key Insight**: Combining uncorrelated signals improves Sharpe (Fundamental Law)

- 3 independent factors
- Signal correlation matrix
- Equal-weight vs IC-weighted
- Performance attribution
- IC decomposition

**Time**: 45 minutes | **Difficulty**: ⭐⭐⭐ Advanced | **Sharpe Improvement**: ~40%

---

#### 9. Mean Reversion Strategy (`09_mean_reversion_strategy.ipynb`) 🔥
**Ornstein-Uhlenbeck process with z-score entry/exit**

**Strategy**: Statistical arbitrage via mean reversion
**Key Insight**: Stop-losses are CRITICAL (prevents catastrophic losses)

- Half-life estimation
- Bollinger bands
- Entry threshold optimization
- Sector-neutral positioning
- Stop-loss implementation
- Regime detection (4 indicators)

**Time**: 60 minutes | **Difficulty**: ⭐⭐⭐⭐ Expert | **Risk**: High without stops

---

#### 10. Volatility Arbitrage (`10_vol_arbitrage_strategy.ipynb`)
**IV/RV ratio dispersion trading**

**Strategy**: Exploit IV/RV convergence in correlated pairs
**Key Insight**: Highly correlated assets (ρ > 0.85) should have converging ratios

- Implied vs realized volatility
- Correlation filtering
- Delta-neutral positioning
- Greeks analysis (vega)
- VIX regime performance

**Time**: 45 minutes | **Difficulty**: ⭐⭐⭐ Advanced | **Market**: Options-like

---

#### 11. Sector Rotation (`11_sector_rotation_strategy.ipynb`)
**Economic cycle-driven sector allocation**

**Strategy**: Tactical sector allocation by economic cycle
**Key Insight**: Cyclical sectors outperform in early/mid cycle, defensives in late/recession

- 11 GICS sectors
- Momentum + reversion signals
- Risk parity allocation
- Transition matrix analysis
- Drawdown by regime

**Time**: 50 minutes | **Difficulty**: ⭐⭐⭐ Advanced | **Focus**: Macro-driven

---

#### 12. Risk Parity (`12_risk_parity_strategy.ipynb`)
**Equal risk contribution portfolio**

**Strategy**: Alternative to mean-variance optimization
**Key Insight**: Use when alphas are weak or uncertain

- Naive risk parity (inverse volatility)
- Equal Risk Contribution (ERC)
- Correlation adjustment
- Leverage calculation
- Rebalancing analysis

**Time**: 40 minutes | **Difficulty**: ⭐⭐⭐ Advanced | **When**: Weak IC

---

#### 13. Statistical Arbitrage Pairs (`13_stat_arb_pairs_trading.ipynb`) 🔥
**Cointegration-based pairs trading**

**Strategy**: Market-neutral statistical arbitrage
**Key Insight**: Exploit mean-reversion in cointegrated pairs (β ≈ 0)

- Engle-Granger + Johansen tests
- Spread construction
- Half-life calculation
- Dollar-neutral sizing
- Correlation breakdown detection
- Market-neutral verification

**Time**: 55 minutes | **Difficulty**: ⭐⭐⭐⭐ Expert | **Beta**: ≈ 0 (market-neutral)

---

#### 14. ML-Enhanced Factors (`14_ml_enhanced_factors.ipynb`)
**Random Forest vs traditional factors**

**Strategy**: Machine learning factor prediction
**Key Insight**: ML adds value when non-linear interactions exist

- 15+ engineered features
- Random Forest vs Linear
- Time-series cross-validation
- Walk-forward testing
- Feature importance
- When ML works vs fails

**Time**: 50 minutes | **Difficulty**: ⭐⭐⭐⭐ Expert | **Warning**: Overfitting risk

---

#### 15. Adaptive Strategy Selection (`15_adaptive_strategy_selection.ipynb`) 🔥
**Regime-based meta-strategy**

**Strategy**: Adapt strategy to market conditions
**Key Insight**: No single strategy works always

- Hidden Markov Model
- 3 regimes: low-vol, trending, ranging
- 3 allocation methods
- Out-of-sample validation
- Mis-classification cost analysis

**Time**: 60 minutes | **Difficulty**: ⭐⭐⭐⭐⭐ Expert | **Type**: Meta-strategy

---

## 🎯 Quick Selection Guide

### **By Experience Level**

**Beginners** (⭐)
- Start with 01, 02
- Focus on understanding concepts
- Don't skip to advanced notebooks

**Intermediate** (⭐⭐-⭐⭐⭐)
- Try 03, 04, 05, 06, 07, 08, 10, 11, 12
- Good foundation in finance
- Comfortable with statistics

**Advanced** (⭐⭐⭐⭐-⭐⭐⭐⭐⭐)
- Explore 09, 13, 14, 15
- Strong quantitative background
- Familiar with advanced concepts

### **By Strategy Type**

**Directional (Trend)**
- 06: Carry Strategy
- 07: Momentum Strategy
- 11: Sector Rotation

**Mean Reversion**
- 09: Mean Reversion Strategy
- 10: Volatility Arbitrage
- 13: Statistical Arbitrage Pairs

**Portfolio Construction**
- 08: Multi-Factor Strategy
- 12: Risk Parity
- 15: Adaptive Strategy Selection

**Advanced Techniques**
- 05: Cross-Asset Integration
- 14: ML-Enhanced Factors

### **By Time Commitment**

**Quick (30-45 minutes)**
- 01, 02, 06, 08, 10, 12

**Medium (45-55 minutes)**
- 03, 04, 05, 07, 09, 11, 13, 14

**In-Depth (60+ minutes)**
- 09, 15

---

## 🚀 Quick Start

### Installation

```bash
# 1. Install Jupyter
pip install jupyter notebook

# 2. Install dependencies
pip install numpy pandas polars matplotlib seaborn scipy scikit-learn cvxpy

# 3. Navigate to notebooks
cd /path/to/ARBS/notebooks

# 4. Launch Jupyter
jupyter notebook
```

### Running Notebooks

1. Open `01_getting_started.ipynb` first
2. Press `Shift + Enter` to run each cell
3. Follow the progression: 01 → 02 → 03 → 04 → then choose strategy notebooks

---

## 📖 Learning Paths

### **Path 1: Quick Start (3 hours)**
```
01 → 02 → 06 (Carry) → 07 (Momentum) → 08 (Multi-Factor)
```
**Goal**: Understand basic backtesting and main strategy types

### **Path 2: Complete Foundation (6 hours)**
```
01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 11 → 12
```
**Goal**: Comprehensive understanding of framework and strategies

### **Path 3: Advanced Quant (10 hours)**
```
All notebooks 01-15 in order
```
**Goal**: Expert-level mastery of all strategies and techniques

### **Path 4: Specific Strategy Deep Dive**
```
01 → 02 → [Your chosen strategy notebook] → Related notebooks
```
**Examples**:
- **Pairs Trading**: 01 → 02 → 13 → 09
- **Machine Learning**: 01 → 02 → 14 → 08
- **Regime-Based**: 01 → 02 → 15 → 11

---

## 💡 What You'll Learn

### Core Concepts (All Notebooks)
- Backtesting methodology
- Information Coefficient (IC)
- Sharpe ratio and risk-adjusted returns
- Alpha generation (IC × Vol × Z)
- Portfolio optimization
- Transaction costs
- Performance analysis

### Strategy-Specific Concepts
| Strategy | Key Concepts |
|----------|-------------|
| Carry (06) | Contango/backwardation, yield curves, calendar spreads |
| Momentum (07) | TSMOM, XSMOM, lookback periods, turnover |
| Multi-Factor (08) | Signal correlation, Fundamental Law, attribution |
| Mean Reversion (09) | OU process, half-life, stop-losses, regime detection |
| Vol Arb (10) | IV/RV ratio, Greeks, correlation filtering |
| Sector Rotation (11) | Economic cycles, sector correlations, transition matrices |
| Risk Parity (12) | ERC, marginal risk contribution, leverage |
| Pairs Trading (13) | Cointegration, market-neutral, spread trading |
| ML Factors (14) | Feature engineering, cross-validation, overfitting |
| Adaptive (15) | HMM, regime detection, meta-strategies |

---

## 📊 Strategy Performance Characteristics

| Notebook | Typical Sharpe | IC Range | Turnover | Complexity |
|----------|----------------|----------|----------|------------|
| 06 Carry | 0.5-1.0 | 0.03-0.06 | Low | Medium |
| 07 Momentum | 0.4-0.8 | 0.02-0.05 | High | Medium |
| 08 Multi-Factor | 0.7-1.2 | 0.05-0.08 | Medium | High |
| 09 Mean Rev | 0.6-1.0 | 0.04-0.07 | Very High | Very High |
| 10 Vol Arb | 0.5-0.9 | 0.03-0.06 | Medium | High |
| 11 Sector Rot | 0.6-1.1 | 0.04-0.07 | Medium | High |
| 12 Risk Parity | 0.4-0.8 | N/A | Low | Medium |
| 13 Pairs | 0.7-1.2 | 0.05-0.09 | High | Very High |
| 14 ML Factors | 0.6-1.4 | 0.04-0.10 | Medium | Very High |
| 15 Adaptive | 0.8-1.3 | Varies | Medium | Very High |

*Note: These are typical ranges with synthetic data. Real performance varies significantly.*

---

## ⚠️ Important Notes

### Data Source
All notebooks use **synthetic mock data** for demonstration. For production:
- Connect to real market data (Bloomberg, Reuters, etc.)
- Replace mock generators with actual data adapters
- Verify data quality and alignment

### Limitations
- Mock data does not reflect real market microstructure
- Results are for educational purposes only
- Always validate on real data before live trading
- Past performance ≠ future results

### Best Practices
1. **Understand before optimizing**
2. **Test robustness across regimes**
3. **Account for transaction costs**
4. **Validate out-of-sample**
5. **Monitor signal degradation**

---

## 🔗 Additional Resources

### Documentation
- [Main README](../README.md) - System overview
- [Documentation Assessment](../docs/DOCUMENTATION_ASSESSMENT.md) - Coverage analysis
- [Strategy Summary](../docs/STRATEGY_NOTEBOOKS_SUMMARY.md) - Detailed guide
- [Adding Custom Components](../docs/ADDING_CUSTOM_COMPONENTS.md) - Extend framework

### Python Examples
- `examples/` directory - 14 production-ready scripts
- All notebooks have corresponding Python examples

---

## 🎓 For Educators

These notebooks are suitable for:
- University courses in quantitative finance
- Research training for graduate students
- Professional development for analysts
- Team onboarding at quantitative firms

They can be used as:
- Interactive tutorials
- Homework assignments
- Research project templates
- Collaborative analysis sessions

**Recommended Course Structure**:
- **Week 1-2**: Notebooks 01-04 (Foundation)
- **Week 3-4**: Notebooks 05-08 (Core Strategies)
- **Week 5-6**: Notebooks 09-12 (Advanced Strategies)
- **Week 7-8**: Notebooks 13-15 (Expert Topics)
- **Week 9-10**: Student projects using framework

---

## 🏆 Next Steps

After completing the notebooks:

1. **Experiment**: Modify parameters and observe results
2. **Create Custom Signals**: See `docs/ADDING_CUSTOM_COMPONENTS.md`
3. **Use Real Data**: Connect market data providers
4. **Combine Strategies**: Build ensemble approaches
5. **Deploy to Production**: Follow best practices
6. **Share Research**: Publish findings!

---

## 📝 Notebook Index

| # | Name | Time | Difficulty | Type |
|---|------|------|------------|------|
| 01 | Getting Started | 20m | ⭐ | Tutorial |
| 02 | Strategy Comparison | 25m | ⭐ | Tutorial |
| 03 | Parameter Tuning | 35m | ⭐⭐ | Tutorial |
| 04 | Results Analysis | 35m | ⭐⭐ | Tutorial |
| 05 | Cross-Asset Integration | 45m | ⭐⭐⭐ | Components |
| 06 | Carry Strategy | 45m | ⭐⭐ | Strategy |
| 07 | Momentum Strategy | 50m | ⭐⭐⭐ | Strategy |
| 08 | Multi-Factor Strategy | 45m | ⭐⭐⭐ | Strategy |
| 09 | Mean Reversion | 60m | ⭐⭐⭐⭐ | Strategy |
| 10 | Volatility Arbitrage | 45m | ⭐⭐⭐ | Strategy |
| 11 | Sector Rotation | 50m | ⭐⭐⭐ | Strategy |
| 12 | Risk Parity | 40m | ⭐⭐⭐ | Strategy |
| 13 | Pairs Trading | 55m | ⭐⭐⭐⭐ | Strategy |
| 14 | ML Factors | 50m | ⭐⭐⭐⭐ | Strategy |
| 15 | Adaptive Selection | 60m | ⭐⭐⭐⭐⭐ | Meta-Strategy |

**Total Learning Time**: ~11 hours for all notebooks

---

Happy Analyzing! 🚀

*For questions, issues, or contributions, see the main repository README.*
