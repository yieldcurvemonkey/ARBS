# Crucial Insights: Sector Risk Models → Global Macro Trading

**Date**: 2025-11-12
**Branch**: `claude/sector-risk-model-research-011CV41RojiVnaUFqthNnozq`
**Status**: ⚠️ CRITICAL - These insights fundamentally reframe this research

---

## 🎯 Core Insight: Equity Sectors = Global Macro Currencies

The substantial analogy between sector trading and global macro fixed income is **not obvious** and provides a powerful lens for reading academic equity research and applying it to macro portfolios.

### The Mapping

```
EQUITY MARKETS                 GLOBAL MACRO FIXED INCOME
─────────────                  ─────────────────────────
Sector (e.g., Tech)       →    Currency (e.g., USD)
Stock (e.g., NVDA)        →    Tenor/Maturity (e.g., 10Y)
Sector correlation        →    Currency correlation
Within-sector correlation →    Yield curve structure (2Y-5Y-10Y-30Y)
Cross-sector correlation  →    Cross-currency correlation (USD-EUR)
```

### Concrete Example

**In Equity Terms:**
- **Tech Sector** contains: AAPL (2Y), MSFT (5Y), NVDA (10Y), GOOGL (30Y)
- **Consumer Sector** contains: WMT, TGT, COST, etc.
- **Energy Sector** contains: XOM, CVX, etc.

**In Macro Terms:**
- **USD Currency** contains: 2Y, 5Y, 10Y, 30Y maturities
- **GBP Currency** contains: 2Y, 5Y, 10Y, 30Y maturities
- **CNY Currency** contains: 2Y, 5Y, 10Y, 30Y maturities

**Defensive/Inverse Mapping:**
- Energy sector (defensive, counter-cyclical) ≈ CNY or safe-haven currencies

---

## 📊 Covariance Matrix Structure

### Visual Representation

```
Covariance Matrix Grid:
                USD_2Y  USD_5Y  USD_10Y  USD_30Y | EUR_2Y  EUR_5Y  EUR_10Y  EUR_30Y | GBP_2Y  ...
USD_2Y          [                                ]|[                                ]|[
USD_5Y          [    USD-USD diagonal block      ]|[    USD-EUR off-diagonal        ]|[
USD_10Y         [    (within-currency)           ]|[    (cross-currency)            ]|[
USD_30Y         [                                ]|[                                ]|[
─────────────────────────────────────────────────┼─────────────────────────────────┼─────────
EUR_2Y          [                                ]|[                                ]|[
EUR_5Y          [    EUR-USD off-diagonal        ]|[    EUR-EUR diagonal block      ]|[
EUR_10Y         [    (cross-currency)            ]|[    (within-currency)           ]|[
EUR_30Y         [                                ]|[                                ]|[
─────────────────────────────────────────────────┼─────────────────────────────────┼─────────
GBP_2Y          [                                ]|[                                ]|[
...
```

### Interpretation

**Diagonal Blocks** (e.g., USD-USD):
- Capture **yield curve structure** within a currency
- High correlations expected (curve parallel shifts, twists, butterflies)
- Papers 1 & 2 model this with **block-diagonal Ψ**

**Off-Diagonal Blocks** (e.g., USD-EUR):
- Capture **cross-currency correlations**
- Paper 2 (BlockDiagonal) assumes these are ZERO → too strong for macro
- Paper 3 (StochasticBlock) allows **non-zero** → crucial for global macro
- Real example: EUR 2Y vs USD 30Y might have small but non-zero correlation

---

## 🚨 Critical Trading Constraint: Butterfly Across Currencies

### The Constraint

> **"You can't be short the 5 year on 2-5-10 butterfly in EVERY currency"**

### What This Means

**2-5-10 Butterfly Definition:**
```
Butterfly = Long 2Y + Long 10Y - 2×Short 5Y
```

**Constraint Interpretation:**
- If you're short 5Y vs (2Y, 10Y) in USD, **you can't also be short 5Y in EUR, GBP, JPY, etc.**
- This is a **risk management override**, not just an optimization constraint
- It's like saying "you can't be short BP (oil stock) if you're already short TSLA" in equity terms

### Why This Matters for Risk Models

1. **Paper 2 (BlockDiagonal)** with pure block-diagonal structure **cannot enforce this constraint**
   - USD block and EUR block are independent
   - Optimizer might short 5Y in every currency if signals align

2. **Paper 3 (StochasticBlock)** with inter-block correlations **can capture this**
   - Off-diagonal blocks create cross-currency dependencies
   - Shorting 5Y in USD increases risk sensitivity to 5Y in EUR
   - This acts as a natural "sanity check override"

3. **Portfolio Construction Layer** needs explicit constraints:
   ```python
   # Pseudo-constraint
   sum(weights[currency][tenor] for currency in currencies if tenor == "5Y") >= -max_short_exposure
   ```

---

## 🔄 Mean Reversion: Sectors vs ETF = Global RV

### Equity Analogy

**Sector Mean Reversion Trading:**
- Trade individual tech stocks (AAPL, NVDA) vs Tech ETF (XLK)
- When NVDA outperforms XLK → expect mean reversion
- Capture relative value within sector while hedging broad sector risk

### Macro Translation

**Global Relative Value Across Currencies:**
- Trade individual currency tenors (USD 10Y, EUR 10Y) vs global aggregate
- When USD 10Y rich vs global 10Y average → expect mean reversion
- Capture relative value within tenor structure while hedging global rate risk

### Factor Decomposition

**Common Factors** (extracted via PCA in FactorExtractor):
1. **Global level factor** (like market beta in equity)
   - All rates move together (risk-on/risk-off)

2. **Global slope factor**
   - Yield curves steepen/flatten globally

3. **Currency-specific factors**
   - USD-specific shocks, EUR-specific shocks

**Idiosyncratic Component** (Ψ in block-diagonal structure):
- Mean-reverting deviations from factor model
- **This is where alpha lives** in global macro RV strategies

### Alpha Generation Pipeline

```
Raw Signals (Z-scores)
    ↓
Factor Decomposition (remove global sentiment)
    ↓
Residuals (mean-reverting RV opportunities)
    ↓
Scaled Alphas (IC × Vol × Z)
    ↓
Risk Model (sector/currency block structure)
    ↓
Portfolio Weights (with butterfly constraints)
```

---

## 📈 How Each Paper Maps to Macro Trading

### Paper 1 (García-Medina): Two-Step Hierarchical + RMT

**Equity Use Case:**
- GICS Level 1 → Level 2 → Level 3 (e.g., Technology → Software → Cloud Services)
- Hierarchical clustering discovers sub-sector structure
- RMT filtering removes noise from correlation estimates

**Macro Translation:**
- **Region → Currency → Tenor** structure
  - Americas: USD (2Y, 5Y, 10Y, 30Y), CAD (...)
  - Europe: EUR (...), GBP (...)
  - Asia: JPY (...), CNY (...)
- Hierarchical clustering discovers regional correlation patterns
- RMT particularly useful when T ≈ p (short history, many instruments)

**When to Use:**
- Multi-level macro portfolios (regional + currency + tenor)
- Want to discover structure from data (not impose it)
- Short sample periods relative to number of instruments

---

### Paper 2 (Žignić): Block-Diagonal Factor Model

**Equity Use Case:**
- Predefined GICS sectors
- Within-sector correlations captured in Ψ_m blocks
- Cross-sector correlations assumed zero (strong assumption)

**Macro Translation:**
- **Currency blocks are independent**
  - USD block: captures 2Y-5Y-10Y-30Y curve dynamics
  - EUR block: independent EUR curve dynamics
  - Assumes USD and EUR are uncorrelated (too strong!)

**When to Use:**
- Single-currency portfolios (e.g., only trading USD curve)
- Well-defined currency groupings with minimal cross-correlations
- Baseline/benchmark model (minimum viable)

**Limitation for Macro:**
- Cannot capture cross-currency effects (EUR-USD correlation, carry trade unwinding)
- Risk of "short 5Y everywhere" problem

---

### Paper 3 (Chen): Stochastic Block with Inter-Block Correlations

**Equity Use Case:**
- Cross-sector dependencies (Tech-Finance correlation during market stress)
- Sanity check overrides (TSLA vs BP correlation even though different sectors)

**Macro Translation:**
- **Cross-currency correlations** (the key difference!)
  - EUR 2Y vs USD 30Y correlation (small but non-zero)
  - Flight-to-quality effects (USD strengthens, EUR weakens)
  - Carry trade unwinds (JPY strengthens when risk-off)

**When to Use:**
- **Multi-currency global macro portfolios** (THE PRIMARY USE CASE)
- Need to enforce cross-currency constraints (butterfly example)
- Capturing contagion and flight-to-quality dynamics

**Why This Is Critical:**
- Off-diagonal blocks in Ψ capture the "sanity check overrides" you mentioned
- Bayesian shrinkage on off-diagonal blocks prevents overfitting cross-correlations
- Alpha parameter controls sparsity (how much inter-block correlation to allow)

---

## 💡 Actionable Alpha Generation Insights

### 1. Factor Decomposition for Alpha Extraction

**Problem:** Raw signals contain both systematic risk (beta) and idiosyncratic alpha

**Solution from Papers:**
```
Returns = B·F + ε

where:
- B·F captures systematic factors (global sentiment, regional shocks)
- ε captures idiosyncratic deviations (mean-reverting, where alpha lives)
```

**Alpha Extraction:**
1. Extract factors via PCA (FactorExtractor)
2. Compute residuals ε = Y - B·F
3. Apply signals to residuals (not raw returns)
4. Residuals mean-revert faster → better IC → larger alpha magnitude

### 2. Risk Management for Butterfly Constraints

**Implementation Strategy:**

**Option A: Hard Constraints in Optimizer**
```python
# In MeanVarianceOptimizer
constraints = [
    # Can't short same tenor across all currencies
    {
        'type': 'ineq',
        'fun': lambda w: max_short_exposure + sum(w[idx] for idx in tenor_indices['5Y'])
    }
]
```

**Option B: Soft Constraints via Risk Model**
```python
# In StochasticBlockCovariance
# Inflate cross-currency correlations for same tenor
Ψ[USD_5Y, EUR_5Y] *= penalty_factor  # Makes shorting both more expensive
```

**Recommendation:** Use **Paper 3 (StochasticBlock)** to naturally capture this via inter-block correlations, PLUS explicit constraints for hard limits.

### 3. Hierarchical Risk Budgeting

**Equity Approach:**
- Allocate risk budget to sectors (Tech 30%, Finance 25%, etc.)
- Within each sector, allocate to stocks

**Macro Translation:**
- Allocate risk budget to **regions** (Americas 40%, Europe 35%, Asia 25%)
- Within each region, allocate to **currencies**
- Within each currency, allocate to **tenors** (curve positioning)

**Papers Support This:**
- Paper 1's hierarchical structure naturally enables multi-level risk budgeting
- Per-block shrinkage (Paper 2) ensures stable within-currency allocations

---

## 🎓 Reading Academic Papers Through Macro Lens

### Translation Guide

When reading equity sector papers, mentally translate:

| Equity Term | Macro Translation |
|-------------|-------------------|
| "Sector" | Currency |
| "Stock" | Tenor/Maturity |
| "GICS Level 1" | Region (Americas, Europe, Asia) |
| "GICS Level 2" | Currency (USD, EUR, GBP) |
| "GICS Level 3" | Tenor (2Y, 5Y, 10Y, 30Y) |
| "Market beta" | Global rates factor |
| "Sector rotation" | Currency rotation |
| "Stock-picking alpha" | Curve positioning alpha |
| "Concentration risk" | Over-exposure to single currency |
| "Diversification" | Cross-currency/tenor spread |

### What to Look For

1. **Block structure assumptions**
   - Pure block-diagonal → Limited for multi-currency
   - Stochastic block → Good for global macro

2. **Factor count selection**
   - How many global factors? (Bai-Ng IC criterion)
   - Impacts how much variance attributed to systematic vs idiosyncratic

3. **Shrinkage methods**
   - Per-block shrinkage → Useful for within-currency stability
   - Cross-block shrinkage → Critical for cross-currency correlations

4. **Validation metrics**
   - Out-of-sample Sharpe ratio → Portfolio performance
   - HHI, Leverage → Concentration and short-selling
   - R²_out → Covariance forecast accuracy

---

## 🚀 Implementation Priorities for ARBS

### Phase 1 (Completed): All 3 Papers Implemented

✅ **Paper 1 (TwoStep)**: RandomMatrixFilter + TwoStepCovariance
✅ **Paper 2 (BlockDiagonal)**: BaiNgIC + HierarchicalSectorClustering + BlockDiagonalCovariance
✅ **Paper 3 (StochasticBlock)**: StochasticBlockCovariance with inter-block correlations

### Phase 2 (Next): Macro-Specific Extensions

1. **Currency-Tenor Data Adapter**
   ```python
   # Extend EquityAdapter to support:
   # - currency: USD, EUR, GBP, JPY, CNY
   # - tenor: 2Y, 5Y, 10Y, 30Y
   # - sector ≡ currency (for risk model compatibility)
   ```

2. **Butterfly Constraint Layer**
   ```python
   # Add to MeanVarianceOptimizer:
   # - Max short per tenor across currencies
   # - DV01 limits per currency
   # - Cardinality constraints (can't trade all tenors)
   ```

3. **Tenor Structure Validation**
   ```python
   # Sanity checks:
   # - No inverted curves unless explicitly allowed
   # - Cross-currency basis within reasonable bounds
   # - Correlation matrix eigenvalues > 0 (PD)
   ```

### Phase 3 (Future): Advanced Alpha Strategies

1. **Global Macro Carry**
   - Short-rate differential signals
   - Risk-adjusted with StochasticBlockCovariance

2. **Curve Positioning**
   - Butterfly signals per currency
   - Constrained by cross-currency butterfly limits

3. **Mean Reversion RV**
   - Residual-based signals (ε after factor extraction)
   - Target idiosyncratic deviations from factor model

---

## 🎯 Key Takeaways

### 1. This Research is Not Just About Equities

The sector risk model papers provide **foundational infrastructure for global macro fixed income portfolios**. The mapping is direct and powerful.

### 2. Paper 3 (StochasticBlock) is Critical for Macro

While Paper 2 (BlockDiagonal) is the minimum viable approach, **Paper 3's inter-block correlations are essential** for multi-currency portfolios to avoid the "short 5Y everywhere" problem.

### 3. Factor Decomposition Enables Alpha Extraction

The B·F + ε decomposition is not just a statistical convenience—it's the mechanism for separating systematic risk from mean-reverting idiosyncratic alpha.

### 4. Constraints are Risk Management, Not Optimization

The butterfly constraint ("can't short 5Y everywhere") is a **risk management override**, not an optimization parameter. The risk model should make violating it expensive, and the optimizer should enforce hard limits.

### 5. Mean Reversion Analogy is Powerful

Sector vs ETF mean reversion in equity markets **≡** tenor vs global aggregate mean reversion in macro markets. This framing enables direct application of equity sector rotation research to global macro RV strategies.

---

**Status**: ⚠️ These insights fundamentally inform Phase 3 (synthesis) and future macro extensions

**Next Steps**:
1. Commit this document
2. Reference it in Phase 3 synthesis
3. Design macro-specific extensions with these constraints in mind

**Captain Obvious > Colonel Stupid** ✓
