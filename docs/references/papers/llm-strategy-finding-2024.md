# ABOUTME: LLM-driven alpha mining framework using multi-agent evaluation and IC-based signal selection
# ABOUTME: Three-stage approach: seed alpha generation, multi-agent filtering, and weight optimization

# Automate Strategy Finding with LLM in Quant Investment

**Authors**: Zhizhuo Kou, Holam Yu, Junyu Luo, Jingshu Peng, Xujia Li, Chengzhong Liu, Juntao Dai, Lei Chen, Sirui Han, Yike Guo

**Institutions**:
- The Hong Kong University of Science and Technology
- The Hong Kong University of Science and Technology (Guangzhou)
- Peking University

**Publication**: arXiv:2409.06289v4 [q-fin.PM], November 2025

**Code**: https://github.com/kouzhizhuo/Automate-Strategy-Finding-with-LLM-in-Quant-investment

---

## Abstract

This paper presents a novel three-stage framework leveraging Large Language Models (LLMs) within a risk-aware multi-agent system for automated strategy finding in quantitative finance. The approach addresses the brittleness of traditional deep learning models by:

1. **Alpha Generation**: Employing prompt-engineered LLMs to generate executable alpha factor candidates across diverse financial data
2. **Multi-Agent Evaluation**: Implementing multimodal agent-based evaluation that filters factors based on market status and predictive quality while maintaining category balance
3. **Dynamic Optimization**: Deploying dynamic weight optimization that adapts to market conditions

The framework achieved **53.17% cumulative return** on SSE50 (Jan 2023-Jan 2024) compared to the benchmark's -11.73%, demonstrating superior risk-adjusted performance and downside protection.

**Key Innovation**: Extends LLM capabilities to quantitative trading by automating the complete pipeline from signal discovery to portfolio construction without human intervention.

---

## 1. Information Coefficient (IC) Calculation

### 1.1 Definition

The Information Coefficient is the **fundamental measure of alpha quality**, defined as the correlation between predicted alphas and actual returns:

$$IC = \sigma(u, v)$$

where:
- $\sigma(u, v)$ is the correlation coefficient between predicted alphas $u$ and actual future returns $v$
- Higher IC indicates stronger predictive relationships

### 1.2 IC in Alpha Evaluation

The paper uses IC in two contexts:

#### Confidence Score Evaluation
Assesses the statistical reliability of each alpha factor:

$$\theta_{ij} = \mathbb{E}\left[IC(\alpha_{ij}^{(t)} | \mathcal{M}^{(t)})\right]$$

where:
- $\theta_{ij}$ = confidence score for alpha $\alpha_{ij}$
- $\mathcal{M}^{(t)}$ = market conditions at time $t$
- $\mathbb{E}[\cdot]$ = expected value across various market environments

**Interpretation**: Higher confidence scores indicate more consistent performance across market regimes.

#### Alpha Selection Criterion

The optimal seed alpha set is selected by combining confidence (IC-based) and risk evaluations:

$$\alpha_{ij}^* = \arg\max_{\alpha_{ij}} [w_c \cdot \theta_{ij} + w_r \cdot \rho_{ij}]$$

where:
- $w_c$ = weight for confidence score (IC-based)
- $w_r$ = weight for risk preference
- $\rho_{ij}$ = risk score from risk evaluation

### 1.3 Empirical IC Results

The paper reports IC values by alpha category:

| Category | Mean IC (SAF) | Mean IC (Selected) | Improvement |
|----------|---------------|-------------------|-------------|
| Momentum | 0.0092 | 0.0208 | +126% |
| Mean Reversion | 0.0135 | 0.0187 | +39% |
| Volatility | 0.0177 | 0.0258 | +46% |
| Fundamental | 0.0118 | 0.0192 | +63% |
| Growth | 0.0146 | 0.0217 | +49% |

**Key Finding**: The LLM-driven multi-agent selection process consistently achieves higher IC values across all categories compared to the full seed alpha factory.

### 1.4 IC Benchmarks

The paper cites established IC benchmarks:
- IC > 0.05: Good predictive power
- IC > 0.10: Very good predictive power
- IC > 0.15: Exceptional (rare in practice)

**Example**: Table 3 shows a 12-alpha combination with weighted IC of **-0.0587** (note: negative IC indicates short signal), with individual alphas ranging from IC = -0.0225 to IC = 0.0278.

### 1.5 ARBS Cross-Reference

The IC calculation methodology aligns with **ARBS implementation**:

**File**: `/home/user/ARBS/Signals/Utils/IC.py`

```python
def calculate_ic(forecasts: np.ndarray, actuals: np.ndarray) -> float:
    """
    Calculate Information Coefficient (Pearson correlation).

    IC = σ(forecasts, actuals)

    Matches the paper's definition: IC = σ(u, v)
    """
    # Implementation uses np.corrcoef for Pearson correlation
    ic = np.corrcoef(forecasts_clean, actuals_clean)[0, 1]
    return ic
```

**Key Functions**:
- `calculate_ic()` - Standard Pearson IC (matches paper's $\sigma(u, v)$)
- `calculate_rank_ic()` - Spearman rank IC (robust to outliers)
- `calculate_ic_significance()` - IC with p-value for statistical testing
- `calculate_ic_time_series()` - Rolling IC for stability analysis
- `calculate_ic_decay()` - IC halflife measurement

**Connection**: The paper's confidence score $\theta_{ij} = \mathbb{E}[IC]$ corresponds to ARBS's `calculate_ic_statistics()` which computes mean IC across time periods.

---

## 2. Strategy Evaluation Metrics

### 2.1 Primary Metrics

The paper evaluates strategies using:

#### Information Coefficient (IC)
- **Definition**: $IC = \sigma(u, v)$ (correlation between alphas and returns)
- **Usage**: Alpha selection and quality measurement

#### Sharpe Ratio
$$\text{Sharpe Ratio} = \frac{\mathbb{E}[R(\alpha^{(t)}) - R_f]}{\sqrt{\text{Var}[R(\alpha^{(t)})]}}$$

where:
- $R(\alpha^{(t)})$ = strategy return at time $t$
- $R_f$ = risk-free rate
- Measures risk-adjusted performance

### 2.2 Additional Risk Metrics

#### Sortino Ratio
Computes excess return per unit of **downside deviation** (only negative returns):

$$\text{Sortino} = \frac{\mathbb{E}[R - R_f]}{\sigma_{\text{downside}}}$$

**Purpose**: Evaluates only negative volatility, ignoring upside.

#### Calmar Ratio
$$\text{Calmar} = \frac{\text{Annualized Return}}{\text{Maximum Drawdown}}$$

**Purpose**: Measures reward relative to worst-case loss.

### 2.3 Performance Comparison (SSE50, 2023)

| Strategy | Final Return | Sharpe | Volatility | Sortino | Calmar |
|----------|-------------|--------|------------|---------|--------|
| **Ours (LLM)** | **53.17%** | **0.287** | **0.762%** | **0.208** | **1.052** |
| XGBoost | 9.53% | 0.038 | 1.019% | 0.067 | 0.103 |
| LightGBM | 7.13% | 0.030 | 0.993% | 0.053 | 0.066 |
| MLP | 3.11% | 0.013 | 0.960% | 0.023 | 0.043 |
| PPO (RL) | 2.87% | 0.013 | 0.886% | 0.024 | 0.017 |
| FinCon (LLM) | 22.47% | 0.077 | 1.196% | 0.126 | 0.232 |
| SEP (LLM) | 17.89% | 0.060 | 1.217% | 0.103 | 0.157 |
| SSE50 Benchmark | -13.22% | -0.063 | 0.859% | -0.111 | -0.043 |

**Key Observations**:
1. LLM framework outperforms all competitors on every metric
2. Lowest volatility (0.762%) despite highest returns
3. Best Calmar ratio (1.052) indicates superior drawdown protection
4. Benchmark had negative returns (-13.22%), making absolute outperformance even more significant

### 2.4 Cross-Market Robustness

#### CSI300 (China A-Shares)
| Period | Annual Return | Cumulative Return | Max Drawdown |
|--------|--------------|------------------|-------------|
| H1 2021 | 29.70% vs 7.31% | 11.91% vs 3.10% | -19.40% vs -10.86% |
| H1 2022 | 12.78% vs -30.37% | 5.29% vs -14.37% | -24.01% vs -28.59% |
| H1 2023 | 192.27% vs 9.13% | 59.03% vs 3.85% | -17.03% vs -8.44% |

#### SP500 (US Market)
| Period | Annual Return | Cumulative Return | Max Drawdown |
|--------|--------------|------------------|-------------|
| H1 2021 | 93.61% vs 29.67% | 35.19% vs 12.59% | -7.89% vs -4.23% |
| H1 2022 | 2.77% vs -44.22% | 1.25% vs -23.39% | -20.55% vs -23.51% |
| H1 2023 | 118.24% vs 35.22% | 42.78% vs 14.76% | -11.52% vs -7.75% |

**Key Finding**: Framework maintains positive returns during bear markets (H1 2022) when benchmarks decline significantly, demonstrating **counter-cyclical robustness**.

### 2.5 ARBS Relevance

The evaluation metrics align with **ARBS backtest framework**:

**Portfolio Analysis**:
- IC measurement → `/home/user/ARBS/Signals/Utils/IC.py`
- Sharpe ratio → Standard portfolio metric
- Drawdown analysis → Risk management

**Signal Quality**:
- The paper's multi-metric evaluation (IC + Sharpe + Sortino + Calmar) matches the comprehensive approach needed for ARBS signal validation
- Cross-market testing validates signal generalization

---

## 3. Multi-Agent Framework

### 3.1 Architecture Overview

The framework employs **two specialized agents** for alpha evaluation:

```
Seed Alpha Factory → Multi-Agent Evaluation → Weight Optimization
                     ├─ Confidence Score Agent (CSA)
                     └─ Risk Preference Agent (RPA)
```

### 3.2 Confidence Score Agent (CSA)

**Purpose**: Assesses statistical reliability of alpha factors

**Evaluation**:
$$\theta_{ij} = \mathbb{E}[IC(\alpha_{ij}^{(t)} | \mathcal{M}^{(t)})]$$

**Method**:
- Backtests each alpha across historical periods
- Computes IC across different market conditions
- Returns expected IC as confidence score

**Key Feature**: Focuses on **predictive consistency** rather than absolute magnitude.

### 3.3 Risk Preference Agent (RPA)

**Purpose**: Examines risk characteristics of alpha factors

**Evaluation**:
$$\rho_{ij} = f_{\text{risk}}(\alpha_{ij}^{(t)}, \mathcal{M}^{(t)})$$

**Method**:
- Evaluates alpha performance under different risk scenarios
- Considers:
  - Volatility contribution
  - Drawdown behavior
  - Tail risk exposure
  - Market regime sensitivity

**Key Feature**: Ensures selected alphas have desirable risk profiles beyond just predictive power.

### 3.4 Combined Selection Criterion

Alphas are scored by weighted combination:

$$\text{Final Score} = w_c \cdot \theta_{ij} + w_r \cdot \rho_{ij}$$

**Selection Rule**:
$$\text{if Final Score} > X \rightarrow \text{include } \alpha_{ij}$$

where $X$ is a predetermined confidence threshold.

### 3.5 Multimodal Data Integration

The agents process **five data types**:

| Data Type | Examples | Purpose |
|-----------|----------|---------|
| **Textual** | Financial reports, news, analyst research | Sentiment, fundamentals |
| **Numerical** | Price, volume, returns, volatility | Quantitative signals |
| **Visual** | K-line charts, technical patterns | Pattern recognition |
| **Audio** | Financial broadcasts, earnings calls | Tone analysis |
| **Video** | CCTV Securities channel, market news | Event detection |

**Key Innovation**: LLM processes all modalities to generate contextually-aware alpha selection.

### 3.6 Category-Based Selection Algorithm

```
Algorithm: Category-Based Alpha Selection

Input: Categories C = {C₁, ..., Cₘ}, threshold X
Output: Selected alphas A

1. For each category Cᵢ in C:
   2. Select best alphas Aᵢ from category
   3. For each alpha α in Aᵢ:
      4. risk_score = RPA(α)
      5. confidence_score = CSA(α)
      6. final_score = wᵣ · risk_score + wc · confidence_score
      7. If final_score > X:
         8. Add α to selected set A
9. Return A
```

**Key Property**: Ensures **category diversity** - each factor category (Momentum, Mean Reversion, etc.) contributes to final strategy.

### 3.7 Ablation Study Results

Tests impact of removing agents:

| Configuration | IC (In-Sample) | IC (Out-of-Sample) | Sharpe Ratio |
|--------------|----------------|-------------------|--------------|
| **Full Model** | **0.059** | **0.047** | **1.94** |
| Without CSA | 0.054 | 0.032 (-31.9%) | 1.51 (-22.5%) |
| Without RPA | 0.056 | 0.039 (-17.0%) | 1.34 (-30.9%) |

**Market Regime Performance** (Out-of-Sample IC):

| Configuration | Bull Market | Bear Market | Sideways Market |
|--------------|-------------|-------------|-----------------|
| **Full Model** | 0.051 | 0.042 | 0.045 |
| Without CSA | 0.046 | **0.021** (-50%) | 0.029 (-36%) |
| Without RPA | 0.049 | 0.028 (-33%) | 0.037 (-18%) |

**Key Finding**: CSA is **critical during bear markets** - removing it causes 50% IC degradation in adverse conditions.

### 3.8 ARBS Integration Potential

The multi-agent approach maps to **ARBS signal architecture**:

**Current ARBS**:
- Single signal evaluation → IC calculation
- Manual parameter tuning → Strategy configuration

**Paper's Enhancement**:
- Multi-agent evaluation → Automated quality assessment
- Market-conditional selection → Dynamic signal adaptation

**Implementation Path**:
1. **Confidence Agent** → Extend `/home/user/ARBS/Signals/Utils/IC.py` to compute expected IC across market regimes
2. **Risk Agent** → Create `/home/user/ARBS/Signals/Utils/RiskProfile.py` for signal risk assessment
3. **Selection Logic** → Implement weighted scoring in signal combiner

**Code Location**: `/home/user/ARBS/Signals/SignalCombiner.py` would integrate the dual-agent evaluation.

---

## 4. Alpha Generation Methodology

### 4.1 Seed Alpha Factory (SAF)

The paper generates **100 seed alphas** across **9 categories**:

| Category | Description | Example Alphas |
|----------|-------------|----------------|
| **Momentum** | Persistent trends | Price momentum, RSI momentum, MACD |
| **Mean Reversion** | Overreaction correction | Z-score reversion, Bollinger bands |
| **Volatility** | Price dispersion | ATR, standard deviation, Bollinger width |
| **Fundamental** | Company valuation | P/E ratio, earnings yield, dividend yield |
| **Liquidity** | Trading activity | Volume, turnover, Amihud illiquidity |
| **Quality** | Operational efficiency | Gross margin, ROE, debt-to-equity |
| **Growth** | Financial expansion | Revenue growth, EPS growth, asset growth |
| **Technical** | Price-volume patterns | Moving averages, RSI, MACD |
| **Macro** | Economic conditions | GDP growth, inflation, interest rates |

### 4.2 Alpha Representation

Alphas are formulated using two operator classes:

#### Cross-Section Operators
Process single time period data:
$$\alpha_{\text{cs}}^{(t)} = f_{\text{cs}}(X_i^{(t)})$$

**Example**: `(CLOSE - DELAY(CLOSE, 14))` - 14-day price change

#### Time-Series Operators
Analyze multiple periods:
$$\alpha_{\text{ts}}^{(t)} = f_{\text{ts}}(X_i^{(t)}, X_i^{(t-1)}, \ldots, X_i^{(t-n)})$$

**Example**: `(CLOSE - DELAY(SMA(CLOSE, 14), 7))` - Detrended price oscillator

#### Combined Formulation
$$\alpha_{ij}^{(t)} = w_{\text{cs}} \cdot f_{\text{cs}}(X_i^{(t)}) + w_{\text{ts}} \cdot f_{\text{ts}}(X_i^{(t)}, \ldots, X_i^{(t-n)})$$

### 4.3 LLM Prompting Strategy

**Input**: 11 financial research documents covering alpha mining techniques

**Prompt**: "Summarize the document information to help quantitative researchers build the Seed Alpha Factory according to traditional financial categories, ensuring that each category of seed alphas is independent."

**Output**: Structured alphas with:
- Category classification
- Mathematical formula
- Implementation code
- Expected behavior

### 4.4 Example: 12-Alpha Portfolio (SSE50 2023)

| # | Alpha Formula | Weight | IC |
|---|--------------|--------|-----|
| 1 | `(CLOSE - DELAY(CLOSE, 14))` | -0.146 | 0.021 |
| 2 | `(RSI - DELAY(RSI, 14))` | -1.027 | -0.023 |
| 3 | `(CLOSE - DELAY(SMA(CLOSE, 14), 7))` | -0.198 | 0.019 |
| 4 | `(MA(CLOSE, 20) - CLOSE)` | 0.056 | -0.019 |
| 5 | `(SMA(CLOSE, 20) - CLOSE)` | -0.945 | -0.019 |
| 6 | `(MAX(HIGH, 20) - CLOSE)` | -0.405 | -0.019 |
| 7 | `(100 - RSI)` | -0.320 | 0.019 |
| 8 | `(BOLL_UP - BOLL_DOWN) / SMA(CLOSE, 20)` | 3.619 | 0.028 |
| 9 | `STD(CLOSE, 10) / STD(CLOSE, 50)` | -0.183 | 0.024 |
| 10 | `VOLUME / MARKET_CAP` | -3.215 | -0.019 |
| 11 | `VOLUME * CLOSE` | -0.006 | 0.019 |
| 12 | `(EPS / DELAY(EPS, 1) - 1)` | -1.835 | -0.022 |

**Weighted Combination IC**: -0.059 (highly predictive short signal)

**Key Insight**: Some alphas have low individual IC but are critical - removing alpha #6 drops combination IC from -0.059 to -0.055 (7% degradation).

### 4.5 Dynamic Market Adaptation

The framework adapts alpha selection to market conditions:

**Case 1: Bull Market (SSE50 Jan-Dec 2023)**
Selected: Momentum and volume indicators
- Price momentum, RSI, MACD
- Volume momentum, On-Balance Volume

**Case 2: Bear Market (SSE50 Jan-Dec 2022)**
Selected: Volatility and fundamental factors
- ATR, Bollinger Bands
- Gross profit margin, P/E ratio

**Mechanism**: Multimodal context (financial reports + price charts + news) → LLM selects regime-appropriate alphas.

### 4.6 ARBS Implementation

The alpha formulation directly translates to **ARBS signal framework**:

**Existing Signals**:
- `/home/user/ARBS/Signals/Futures/MomentumSignal.py`
- `/home/user/ARBS/Signals/Futures/MeanReversionSignal.py`
- `/home/user/ARBS/Signals/Futures/CarrySignal.py`

**Paper's Contribution**:
1. **Systematic categorization** of 100+ alpha formulas
2. **Independence criterion** ensures signals are uncorrelated
3. **LLM-driven generation** could automate signal discovery in ARBS

**Potential Enhancement**:
Create `/home/user/ARBS/Signals/AlphaFactory.py` that:
- Implements the paper's 100 seed alphas
- Provides category-based selection
- Enables LLM-driven alpha discovery

---

## 5. Weight Optimization

### 5.1 Neural Network Architecture

The paper uses a **3-layer MLP** to optimize alpha weights:

```
Input Layer:     |A| nodes (one per selected alpha)
Hidden Layer:    10 nodes (ReLU activation)
Output Layer:    1 node (yield prediction)
```

**Training**:
- **Input**: Historical alpha values for each stock
- **Target**: Future returns (next period)
- **Loss**: Mean squared error between predicted and actual returns
- **Optimizer**: Gradient descent with backpropagation

### 5.2 Optimization Objective

$$w^* = \arg\min_w \mathbb{E}\left[\left(y_{t+1} - \sum_{j=1}^{|A|} w_j \cdot \alpha_j^{(t)}\right)^2\right]$$

where:
- $w^* = (w_1, \ldots, w_{|A|})$ are optimal weights
- $y_{t+1}$ is actual future return
- $\alpha_j^{(t)}$ is alpha value at time $t$

**Output**: The final weighted alpha strategy:
$$\alpha^{(t)} = \sum_{j=1}^{k} w_j \cdot \alpha_j^{(t)}$$

### 5.3 Sensitivity Analysis

**Optimal Hyperparameters**:
| Parameter | Optimal Value | Sharpe Ratio |
|-----------|--------------|--------------|
| Hidden nodes | **10** | **13.33** |
| Learning rate | **0.001** | 13.33 |
| Batch size | **32** | 13.33 |
| Regularization | **0.001** | 13.33 |

**Sensitivity Tests**:
- Hidden nodes: 5 → 9.69, **10 → 13.33**, 20 → 6.93
- Learning rate: 0.0005 → 7.03, **0.001 → 13.33**, 0.002 → 5.13
- Regularization: 0.0005 → -1.88, **0.001 → 13.33**, 0.002 → -6.91

**Key Finding**: Performance is highly sensitive to regularization - too little (0.0005) or too much (0.002) significantly degrades results.

### 5.4 Agent Weight Sensitivity

Optimal CSA/RPA weight ratio:

| Confidence Weight | Risk Weight | Sharpe (Bull) | Sharpe (Bear) | Sharpe (Overall) |
|------------------|-------------|---------------|---------------|------------------|
| 1.0 | 0.0 | 4.32 | 6.60 | 8.10 |
| 0.8 | 0.2 | -3.41 | -7.23 | -2.68 |
| **0.6** | **0.4** | **8.70** | **10.37** | **11.39** |
| 0.5 | 0.5 | -0.49 | -1.62 | -5.10 |
| 0.4 | 0.6 | -4.27 | -4.41 | -8.04 |
| 0.2 | 0.8 | 5.68 | 8.51 | 9.00 |
| 0.0 | 1.0 | -0.61 | 1.78 | -4.35 |

**Optimal**: 60% confidence, 40% risk → Sharpe 11.39 across all regimes

**Key Insight**: Pure confidence (1.0/0.0) or pure risk (0.0/1.0) perform poorly - **balanced combination is essential**.

### 5.5 ARBS Integration

The weight optimization aligns with **ARBS optimizer framework**:

**Current ARBS Approach**:
- Mean-variance optimization (Markowitz)
- Signal combination via `SignalCombiner`

**Paper's Enhancement**:
- Neural network learns **non-linear** relationships
- Adapts weights dynamically to market conditions
- Learns from multimodal data inputs

**Implementation Strategy**:
1. Extend `/home/user/ARBS/Optimizer/MeanVarianceOptimizer.py`
2. Add neural network option for weight optimization
3. Compare performance: Markowitz vs. MLP

**Caveat**: Neural network requires extensive training data and may overfit - use with robust validation.

---

## 6. ARBS Relevance and Implementation Roadmap

### 6.1 Direct Applicability

#### IC-Based Signal Evaluation ✅
**Current ARBS**: `/home/user/ARBS/Signals/Utils/IC.py`
- Already implements Pearson IC, Rank IC, significance testing
- Matches paper's $IC = \sigma(u, v)$ definition
- Ready for immediate use in alpha evaluation

**Enhancement from Paper**:
- **Expected IC** $\theta_{ij} = \mathbb{E}[IC | \mathcal{M}^{(t)}]$ across market regimes
- Add to `IC.py`:
  ```python
  def calculate_expected_ic(forecasts: pd.DataFrame,
                           actuals: pd.DataFrame,
                           market_conditions: pd.Series) -> dict:
      """
      Calculate expected IC conditioned on market states.

      Implements: θ_ij = E[IC(α_ij | M^(t))]
      """
      # Group by market regime, compute IC per regime
      # Return expected IC and regime-specific ICs
  ```

#### Multi-Signal Framework ✅
**Current ARBS**:
- `CarrySignal`, `MomentumSignal`, `MeanReversionSignal`
- `SignalCombiner` for weighted combinations

**Enhancement from Paper**:
- Expand to **9 signal categories** (currently have 3)
- Add: Volatility, Fundamental, Liquidity, Quality, Growth, Technical, Macro
- Each category independently tested (paper's independence criterion)

#### Strategy Factory Pattern ✅
**Current ARBS**: `/home/user/ARBS/Config/strategy_factory.py`
- YAML-based strategy configuration
- Factory pattern for component instantiation

**Enhancement from Paper**:
- **Seed Alpha Factory**: Pre-built library of 100 alpha formulas
- Category-based template selection
- LLM-driven alpha discovery (future work)

### 6.2 Implementation Roadmap

#### Phase 1: IC-Enhanced Evaluation (1-2 days)
```python
# File: /home/user/ARBS/Signals/Utils/IC.py

def calculate_expected_ic(
    signal: BaseSignal,
    returns: pd.DataFrame,
    market_regimes: pd.Series,
) -> dict:
    """
    Calculate expected IC across market regimes.

    Returns:
        {
            'expected_ic': float,  # E[IC|M]
            'regime_ics': {
                'bull': float,
                'bear': float,
                'sideways': float,
            },
            'regime_counts': {
                'bull': int,
                'bear': int,
                'sideways': int,
            }
        }
    """
    # Implementation: Group by regime, compute IC per group, take weighted average
```

#### Phase 2: Multi-Agent Selection (3-5 days)
```python
# File: /home/user/ARBS/Signals/Utils/AgentEvaluation.py

class ConfidenceScoreAgent:
    """
    Evaluates signal statistical reliability via IC analysis.

    Implements: θ_ij = E[IC(α_ij | M)]
    """

    def evaluate(self, signal: BaseSignal, market_data: pd.DataFrame) -> float:
        """Returns confidence score (expected IC)."""
        pass

class RiskPreferenceAgent:
    """
    Evaluates signal risk characteristics.

    Implements: ρ_ij = f_risk(α_ij, M)
    """

    def evaluate(self, signal: BaseSignal, market_data: pd.DataFrame) -> float:
        """Returns risk score (volatility, drawdown, tail risk)."""
        pass

class MultiAgentSelector:
    """
    Combines CSA and RPA for signal selection.

    Implements: final_score = w_c·θ + w_r·ρ
    """

    def select_signals(
        self,
        candidates: List[BaseSignal],
        threshold: float = 0.05,
        w_confidence: float = 0.6,
        w_risk: float = 0.4,
    ) -> List[BaseSignal]:
        """Returns signals exceeding combined score threshold."""
        pass
```

#### Phase 3: Seed Alpha Factory (5-7 days)
```python
# File: /home/user/ARBS/Signals/AlphaFactory.py

class AlphaFactory:
    """
    Repository of 100+ pre-built alpha signals organized by category.

    Categories:
    - Momentum: Persistent trends
    - Mean Reversion: Overreaction correction
    - Volatility: Price dispersion
    - Fundamental: Company valuation
    - Liquidity: Trading activity
    - Quality: Operational efficiency
    - Growth: Financial expansion
    - Technical: Price-volume patterns
    - Macro: Economic conditions
    """

    def get_category_alphas(self, category: str) -> List[BaseSignal]:
        """Returns all alphas in category."""
        pass

    def get_best_alpha_per_category(
        self,
        returns: pd.DataFrame,
        selection_method: str = 'multi_agent',
    ) -> Dict[str, BaseSignal]:
        """
        Select best alpha from each category using multi-agent evaluation.

        Ensures category diversity in final strategy.
        """
        pass
```

#### Phase 4: Neural Network Weight Optimization (3-5 days)
```python
# File: /home/user/ARBS/Optimizer/NeuralWeightOptimizer.py

class NeuralWeightOptimizer:
    """
    MLP-based weight optimization for signal combinations.

    Architecture:
    - Input: |signals| nodes (alpha values)
    - Hidden: 10 nodes (ReLU)
    - Output: 1 node (return prediction)

    Loss: MSE between predicted and actual returns
    """

    def __init__(
        self,
        n_signals: int,
        hidden_nodes: int = 10,
        learning_rate: float = 0.001,
        batch_size: int = 32,
        regularization: float = 0.001,
    ):
        pass

    def optimize(
        self,
        signal_values: pd.DataFrame,  # Historical alpha values
        returns: pd.Series,           # Actual future returns
    ) -> np.ndarray:
        """Returns optimized weights."""
        pass
```

### 6.3 Validation Strategy

#### Test Against Paper's Results
1. **Replicate SSE50 2023 backtest**:
   - Use same 12 alphas from Table 3
   - Compare IC, Sharpe, returns

2. **Verify IC improvements**:
   - Measure IC before/after multi-agent selection
   - Expect similar improvements to Table 2 (momentum: +126%, volatility: +46%, etc.)

3. **Cross-market validation**:
   - Test on US futures data
   - Verify robustness across regimes

#### Integration Tests
```python
# File: /home/user/ARBS/tests/integration/test_llm_framework.py

def test_multi_agent_selection():
    """Verify multi-agent selection improves IC."""
    # Generate 20 random signals
    # Select top 5 via multi-agent
    # Assert: selected_ic > random_ic

def test_category_diversity():
    """Verify category-based selection ensures diversity."""
    # Select alphas from AlphaFactory
    # Assert: selected signals span all 9 categories

def test_neural_weight_optimization():
    """Compare neural vs. Markowitz optimization."""
    # Train neural optimizer
    # Compare Sharpe: neural vs. mean-variance
```

### 6.4 Key Takeaways for ARBS

| Paper Contribution | ARBS Status | Action Required |
|-------------------|-------------|-----------------|
| **IC Calculation** | ✅ Implemented | Extend to expected IC across regimes |
| **Multi-Agent Selection** | ❌ Not implemented | Create CSA and RPA agents |
| **Category-Based Alphas** | ⚠️ Partial (3/9 categories) | Expand to 9 categories |
| **Seed Alpha Factory** | ❌ Not implemented | Build library of 100+ alphas |
| **Neural Weight Optimization** | ❌ Not implemented | Add as alternative to Markowitz |
| **Multimodal Data** | ⚠️ Text only (for news) | Consider audio/video/image data |

### 6.5 Critical Insights for ARBS Development

#### 1. IC as Primary Metric
**Paper's Evidence**: All alpha selection based on IC, not returns
- **ARBS Implication**: IC should be primary criterion in `SignalCombiner`
- **Implementation**: Weight signals by expected IC, not historical returns

#### 2. Category Independence
**Paper's Finding**: Independent signal categories (momentum, reversion, etc.) ensure robustness
- **ARBS Implication**: Correlation between `CarrySignal` and `MomentumSignal` should be tested
- **Implementation**: Add correlation matrix to `SignalCombiner` validation

#### 3. Market-Conditional Selection
**Paper's Success**: Different alphas for bull vs. bear markets
- **ARBS Implication**: Static signal weights may underperform
- **Implementation**: Regime-switching signal weights in `Portfolio`

#### 4. Multi-Metric Evaluation
**Paper's Approach**: IC + Sharpe + Sortino + Calmar
- **ARBS Implication**: Single-metric optimization (Sharpe only) is insufficient
- **Implementation**: Multi-objective optimization in backtest evaluation

#### 5. Ablation Testing is Critical
**Paper's Discovery**: Removing CSA causes 50% IC drop in bear markets
- **ARBS Implication**: Every component must be ablation-tested
- **Implementation**: Add ablation tests to `/home/user/ARBS/tests/integration/`

---

## 7. Limitations and Future Work

### 7.1 Acknowledged Limitations

1. **Document Quality Dependency**: System efficacy depends on input research quality, potentially perpetuating biases
2. **Limited Financial Intuition**: LLM-generated alphas occasionally lack practical feasibility
3. **Historical Persistence Assumption**: Multi-agent evaluation assumes persistent relationships between market conditions and alpha performance
4. **Equity Market Focus**: Validation primarily on equity markets; cross-asset applicability requires additional testing

### 7.2 Future Research Directions

- **Mixture of Experts (MoE)**: Improve learning efficiency with specialized expert networks
- **Adaptive Agents**: Dynamic agent architectures that evolve with market regimes
- **Transfer Learning**: Apply learned strategies across asset classes
- **Regulatory Compliance**: Address computational efficiency and regulation requirements

---

## 8. Key References

1. **Goodwin (1998)**: "The Information Ratio" - Foundational IC metric
2. **Sharpe (1994)**: "The Sharpe Ratio" - Risk-adjusted performance
3. **Kakushadze (2016)**: "101 Formulaic Alphas" - Alpha taxonomy
4. **Grinold & Kahn**: Active portfolio management framework (IC × BR architecture)

---

## 9. Conclusion

This paper demonstrates that **LLMs can successfully automate the complete alpha discovery pipeline** from signal generation to portfolio construction, achieving:

- **53.17% returns** vs. benchmark's -11.73% (SSE50 2023)
- **Consistent IC improvement** across all signal categories (+39% to +126%)
- **Cross-market robustness** (China CSI300/SSE50, US SP500)
- **Counter-cyclical performance** (positive returns during 2022 bear market)

The **three-stage framework**—Seed Alpha Factory, Multi-Agent Evaluation, Neural Weight Optimization—provides a scalable, adaptive architecture that extends LLM capabilities to quantitative trading.

For **ARBS**, the paper validates IC as the primary signal quality metric and demonstrates that multi-agent evaluation significantly improves signal selection. The category-based alpha organization ensures signal independence and portfolio robustness.

**Critical Implementation**: Extend ARBS's existing IC calculation (`/home/user/ARBS/Signals/Utils/IC.py`) with expected IC across market regimes, implement dual-agent evaluation (CSA + RPA), and expand signal library to 9 independent categories following the paper's taxonomy.
