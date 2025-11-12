# Sector Rotation by Factor Model and Fundamental Analysis
## Mathematical Extraction and Implementation Guide

**Source**: Yang & Shi (2023), UC Davis, arXiv:2401.00001
**Downloaded**: 2025-11-11
**Purpose**: Implement sector rotation strategy using factor models + fundamental analysis

---

## 1. Sector Classification

**Standard**: MSCI Global Industry Classification Standard (GICS)
**Level 1 Sectors** (11 total):
1. Energy
2. Materials
3. Industrials
4. Consumer Discretionary
5. Consumer Staples
6. Health Care
7. Financials
8. Information Technology
9. Communication Services
10. Utilities
11. Real Estate

**Tracking**: S&P 500 GICS Sector Indices

---

## 2. Return Difference Opportunity

**Metric**: Quarterly Return Difference

```
Return_Diff = (Σ(top 3 sector returns) - Σ(bottom 3 sector returns)) / 3
```

**Empirical Results** (Monthly frequency):
- Mean: 13.06%
- Median: 11.85%
- Std Dev: 5.23%
- **Conclusion**: 50% of quarterly periods show >11.85% return difference

---

## 3. Momentum Factors

### 3.1 Factor Construction

**General Formula**:
```
MOM_nM = Σ(Past n×21 days) R_d - Σ(Past 0.1×n×21 days) R_d
```

Where:
- `n` = number of months (1-12)
- `R_d` = daily return
- Excludes most recent 10% of period to avoid short-term reversion

**Tested Lookback Periods**: 1M, 2M, 3M, 4M, 5M, 6M, 7M, 8M, 9M, 10M, 11M, 12M

### 3.2 Factor Returns (2017-2022)

| Factor  | Annual Return | Sharpe Ratio |
|---------|---------------|--------------|
| MOM_1M  | 2.13%         | 0.06         |
| MOM_2M  | -4.94%        | -0.14        |
| MOM_3M  | 11.54%        | 0.29         |
| MOM_4M  | -15.78%       | 0.41         |
| MOM_5M  | -17.88%       | 0.47         |
| MOM_6M  | 11.63%        | 0.35         |
| **MOM_7M** | **21.19%** | **0.62** |
| MOM_8M  | 18.69%        | 0.56         |
| MOM_9M  | 15.83%        | 0.43         |
| MOM_10M | 5.04%         | 0.12         |
| MOM_11M | 15.47%        | 0.40         |
| MOM_12M | 12.89%        | 0.33         |

**Optimal**: **MOM_7M** (7-month lookback, excluding last 0.7 months)

### 3.3 Portfolio Construction

1. Cross-sectional normalization (z-scores)
2. Rank sectors by factor exposure
3. **Long**: Top 2 sectors (highest momentum)
4. **Short**: Bottom 2 sectors (lowest momentum)
5. Equal-weighted within baskets
6. Monthly rebalancing

---

## 4. Short-Term Reversion Factors

### 4.1 Factor Construction

**General Formula**:
```
REV_nD = -Σ(Past n days) R_d
```

Where:
- `n` = number of days (5, 10, 15, ..., 55 in 5-day increments)
- Negative cumulative return (reversion principle)

### 4.2 Factor Returns (2002-2022)

| Factor   | Annual Return | Sharpe Ratio |
|----------|---------------|--------------|
| REV_5D   | -0.59%        | -0.0597      |
| REV_10D  | 2.94%         | 0.3320       |
| REV_15D  | 1.27%         | 0.1338       |
| REV_20D  | 0.72%         | 0.0715       |
| REV_25D  | 6.90%         | 0.7768       |
| **REV_30D** | **8.77%**  | **0.8735**   |
| REV_35D  | 1.35%         | 0.1288       |
| REV_40D  | -3.14%        | -0.3422      |
| REV_45D  | -6.94%        | -0.8417      |
| REV_50D  | -1.83%        | -0.5919      |
| REV_55D  | -5.17%        | -0.1863      |

**Optimal**: **REV_30D** (30-day reversion)

---

## 5. Fundamental Factors

### 5.1 Factor List (Quarterly Data from Bloomberg)

**Valuation Ratios**:
1. **PE**: Price-to-Earnings
2. **PB**: Price-to-Book
3. **EV/Sales**: Enterprise Value / Sales
4. **EV/EBIT**: Enterprise Value / EBIT
5. **EV/EBITDA**: Enterprise Value / EBITDA

**Income/Yield**:
6. **Dividend Yield**: Annual dividends / Price

**Profitability Margins**:
7. **Gross Margin**: (Revenue - COGS) / Revenue
8. **Operating Margin**: Operating Income / Revenue
9. **Profit Margin**: (Revenue - Total Expenses) / Revenue

**Returns**:
10. **ROA**: Return on Assets = Net Income / Average Assets
11. **ROE**: Return on Equity = Net Income / Equity

### 5.2 Cross-Sectional Neutralization

**Formula**:
```
X_{i,t}_Neutral = (X_{i,t} - Mean(X_{i,t}, i=1 to 11)) / StdDev(X_{i,t}, i=1 to 11)
```

Where:
- `i` = sector index (1-11)
- `t` = time period (quarter)
- Normalizes factors to mean=0, std=1 within each quarter
- Makes factors comparable across sectors and time

### 5.3 Target Variable

**Next Quarter Return** (also cross-sectionally normalized):
```
Y_{i,t+1}_Neutral = (R_{i,t+1} - Mean(R_{i,t+1}, i=1 to 11)) / StdDev(R_{i,t+1}, i=1 to 11)
```

---

## 6. Neural Network Prediction Model

### 6.1 Architecture

**Structure**:
```
Input Layer:    10 features (fundamental factors)
Hidden Layer 1: 5 nodes, ReLU activation
Hidden Layer 2: 5 nodes, ReLU activation
Output Layer:   2 nodes (binary classification), Sigmoid activation
```

**Optimization**:
- Solver: Quasi-Newton methods (good for small samples)
- Regularization: L2 penalty with alpha=0.5
- Loss: Binary cross-entropy

### 6.2 Training Configuration

**Data Split**:
- Training: 60% (oldest data)
- Validation: 20% (middle data)
- Test: 20% (most recent data)
- **No shuffling** (maintains temporal structure)

**Target Classes**:
- Class 1: Positive next-quarter return
- Class 0: Negative next-quarter return

### 6.3 Hyperparameter Selection

**Grid Search Results** (validation accuracy):

Best performance with simpler models to avoid overfitting on small sample (~200 observations).

**Selected Parameters**:
- N (nodes per layer): 5
- Alpha (L2 penalty): 0.5
- Rationale: Balance between bias and variance on small sample

### 6.4 Model Performance

**Test Set Results**:
- Overall Accuracy: 64%
- Positive Return Winning Rate: 59% (22/37 correct)
- Negative Return Winning Rate: 72% (13/18 correct)

**Trading Performance** (Test Set: Sept 2020 - Sept 2021):
- Sharpe Ratio: **2.21**
- Strategy: Long top 3 probability sectors, short bottom 3

---

## 7. Portfolio Construction (Neural Network Signals)

### 7.1 Signal Generation

1. Input neutralized fundamental factors into trained model
2. Extract **probability** of positive return (sigmoid output)
3. Rank sectors by probability (1=highest, 11=lowest)

### 7.2 Position Sizing

**Long Positions**:
- Sectors ranked 1-3
- Equal-weighted allocation

**Short Positions**:
- Sectors ranked 9-11
- Equal-weighted allocation

**Dollar-Neutral**:
```
Total_Long = Total_Short
Net_Exposure = 0
```

### 7.3 Rebalancing

- Frequency: Monthly
- Aligned with quarterly fundamental data releases

---

## 8. Key Empirical Insights

### 8.1 Momentum vs Reversion

- **Short-term (1-2 months)**: Reversion effect dominates (negative momentum returns)
- **Medium-term (7-8 months)**: Momentum effect dominates (positive returns)
- **Optimal momentum**: 7 months, excluding recent 10%
- **Optimal reversion**: 30 days

### 8.2 Sector-Specific Patterns

**IT Sector**:
- Highest ROA and ROE
- High gross margin (>40%)
- Benefits from momentum strategies

**Energy Sector**:
- Lowest margins historically
- Sharp declines in 2016 (policy shift) and 2020 (COVID)
- High volatility in valuation ratios

**Real Estate**:
- High PE and EV/Sales (overvalued signal)
- Lower PB ratio
- Defensive characteristics

**Utilities**:
- Highest gross margins (>40%)
- Negative correlation with Energy sector
- Stable, mean-reverting behavior

### 8.3 Fundamental Factor Predictability

**Most Informative**:
- EV/EBITDA (coefficient 0.1235)
- PB Ratio (coefficient -0.1763)
- Dividend Yield (coefficient -0.1986, negative relationship)

**Least Informative**:
- PE Ratio (coefficient 0.0333)
- Operating Margin (coefficient 0.1004)

---

## 9. Implementation Considerations

### 9.1 Data Requirements

**Time-Series Data** (Daily):
- Sector index prices (for momentum/reversion)
- 12-month+ history for momentum factors

**Fundamental Data** (Quarterly):
- PE, PB, EV/Sales, EV/EBIT, EV/EBITDA
- Dividend Yield
- Gross Margin, Operating Margin, Profit Margin
- ROA, ROE
- Available from Bloomberg, FactSet, or similar

### 9.2 Model Training Requirements

**Sample Size**:
- Minimum ~200 observations (11 sectors × ~20 quarters)
- Quarterly rebalancing suitable for fundamental data frequency
- Neural network requires careful regularization to avoid overfitting

**Validation Approach**:
- Walk-forward testing (no shuffling)
- Out-of-sample test on most recent data
- Monitor for regime changes

### 9.3 Limitations Noted by Authors

1. **Cross-sectional neutralization**: May not capture time-series trends within sectors
2. **Small sample size**: 5 years of quarterly data = limited observations
3. **Fundamental data staleness**: Quarterly updates lag market moves
4. **Model generalization**: Trained on 2017-2022 (specific regime)

---

## 10. Grinold-Kahn Connection

### 10.1 Information Coefficient (IC)

Not explicitly calculated in the paper, but can be derived from:
```
IC ≈ correlation(factor_score, next_period_return)
```

From scatter plots (page 12), visible weak-to-moderate linear relationships.

### 10.2 Fundamental Law of Active Management

```
IR = IC × sqrt(Breadth)
```

Where:
- **IC**: Forecasting skill (correlation of signal to return)
- **Breadth**: Number of independent bets
- **IR**: Information Ratio (Sharpe ratio of active returns)

For sector rotation:
- Breadth = ~11 sectors (somewhat correlated)
- Effective breadth lower due to sector correlations
- IR = 2.21 (test set) suggests high IC or effective breadth

### 10.3 Transfer Coefficient

Not explicitly addressed, but implicit in:
- Portfolio construction rules (long top 3, short bottom 3)
- Equal weighting within buckets
- Constraints prevent full alpha capture

---

## 11. Extensions for ARBS Architecture

### 11.1 Integration Points

**Existing Components**:
1. **Query/Equities**: Already supports sector classification ✓
2. **Adapter/EquityAdapter**: Converts to returns DataFrame ✓
3. **Returns/ReturnsCalculator**: Computes period returns ✓
4. **Signals**: Add `MomentumSectorSignal`, `ReversionSectorSignal`, `FundamentalSignal`
5. **Alpha/AlphaGenerator**: Scale signals by IC × Vol × Z
6. **Risk**: Sector-aware covariance (block diagonal structure)
7. **Optimizer**: Mean-variance with sector constraints
8. **Portfolio**: Composite portfolio by sector

### 11.2 New Components Needed

**Fundamental Data Provider**:
- `Query/Fundamentals/FundamentalQuery.py`
- Quarterly data: PE, PB, EV/EBIT, etc.
- Cross-sectional neutralization

**Factor Signals**:
- `Signals/SectorMomentumSignal.py`: MOM_7M implementation
- `Signals/SectorReversionSignal.py`: REV_30D implementation
- `Signals/FundamentalSignal.py`: Neural network predictor

**Sector-Aware Risk**:
- `Risk/SectorBlockCovariance.py`: Block-diagonal structure
- Higher intra-sector correlation
- Lower cross-sector correlation

---

## 12. Success Criteria for Tests

### 12.1 Factor Construction Tests

```python
def test_momentum_7m_construction():
    """Test MOM_7M factor matches paper specification."""
    # Setup: 7 months + 0.7 months of daily data
    # Assert: Factor = sum(7M returns) - sum(last 0.7M returns)

def test_reversion_30d_construction():
    """Test REV_30D factor matches paper specification."""
    # Setup: 30 days of daily returns
    # Assert: Factor = -sum(30D returns)

def test_cross_sectional_neutralization():
    """Test factor neutralization produces mean=0, std=1."""
    # Setup: 11 sectors with different factor values
    # Assert: mean ≈ 0, std ≈ 1 (within tolerance)
```

### 12.2 Signal Generation Tests

```python
def test_momentum_signal_ranking():
    """Test momentum signal ranks sectors correctly."""
    # Setup: Known momentum values for sectors
    # Assert: Top momentum sectors get positive signals

def test_fundamental_signal_prediction():
    """Test fundamental model produces valid probabilities."""
    # Setup: Fundamental factors for 11 sectors
    # Assert: Probabilities in [0, 1], sum for binary classification
```

### 12.3 Portfolio Construction Tests

```python
def test_long_short_portfolio_construction():
    """Test portfolio goes long top 3, short bottom 3."""
    # Setup: Ranked signals for 11 sectors
    # Assert: weights[0:3] > 0, weights[8:11] < 0, weights[3:8] == 0

def test_dollar_neutrality():
    """Test portfolio maintains zero net exposure."""
    # Setup: Any signal configuration
    # Assert: sum(weights) ≈ 0
```

### 12.4 Performance Tests

```python
def test_momentum_factor_returns():
    """Test MOM_7M achieves reasonable returns."""
    # Setup: Historical sector data 2017-2022
    # Assert: Annual return > 10%, Sharpe > 0.4

def test_reversion_factor_returns():
    """Test REV_30D achieves reasonable returns."""
    # Setup: Historical sector data 2002-2022
    # Assert: Annual return > 5%, Sharpe > 0.5
```

### 12.5 Integration Tests

```python
def test_end_to_end_sector_rotation():
    """Test complete pipeline from data to portfolio."""
    # Setup: Historical sector prices + fundamentals
    # Assert: Portfolio trades, returns calculated, metrics computed
```

---

## 13. Mathematical Summary

**Core Innovation**: Combines time-series factors (momentum/reversion) with cross-sectional factors (fundamentals) for sector rotation.

**Key Equations**:

1. **Momentum**: `MOM_7M = Σ(147 days) R_d - Σ(15 days) R_d`
2. **Reversion**: `REV_30D = -Σ(30 days) R_d`
3. **Neutralization**: `X_Neutral = (X - μ) / σ` (cross-sectional)
4. **Neural Network**: `P(return>0) = sigmoid(W2·ReLU(W1·X + b1) + b2)`
5. **Portfolio**: Long top 3, short bottom 3, equal-weighted

**Performance Targets**:
- MOM_7M: Sharpe ~0.6
- REV_30D: Sharpe ~0.9
- Combined (NN): Sharpe ~2.2

---

**END OF MATHEMATICAL EXTRACTION**
