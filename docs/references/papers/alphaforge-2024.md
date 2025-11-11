# ABOUTME: Reference document for AlphaForge paper on formulaic alpha mining and dynamic factor combination
# ABOUTME: Covers IC metrics, factor combination methods, and entry/exit criteria relevant to ARBS SignalCombiner

# AlphaForge: A Framework to Mine and Dynamically Combine Formulaic Alpha Factors

## Paper Metadata

**Title:** AlphaForge: A Framework to Mine and Dynamically Combine Formulaic Alpha Factors

**Authors:** Hao Shi¹, Weili Song², Xinting Zhang¹, Jiahe Shi³, Cuicui Luo¹*, Xiang Ao⁵, Hamid Arian⁶, Luis Seco⁷

**Affiliations:**
- ¹University of the Chinese Academy of Sciences, Beijing, China
- ²Renaissance Era Investment Management Co., Ltd, Beijing, China
- ³Shangqiu Normal University, Shangqiu, China
- ⁵Institute of Computing Technology, University of Chinese Academy of Sciences, Beijing, China
- ⁶York University, Toronto, Canada
- ⁷University of Toronto, Toronto, Canada

**arXiv ID:** arXiv:2406.18394v5 [q-fin.CP]

**Publication Date:** December 12, 2024

**GitHub:** https://github.com/DulyHao/AlphaForge

---

## Abstract

The complexity of financial data, characterized by its variability and low signal-to-noise ratio, necessitates advanced methods in quantitative investment that prioritize both performance and interpretability. Transitioning from early manual extraction to genetic programming, the most advanced approach in the alpha factor mining domain currently employs reinforcement learning to mine a set of combination factors with fixed weights.

However, the performance of resultant alpha factors exhibits inconsistency, and the inflexibility of fixed factor weights proves insufficient in adapting to the dynamic nature of financial markets. To address this issue, this paper proposes a two-stage formulaic alpha generating framework **AlphaForge**, for alpha factor mining and factor combination.

This framework employs a generative-predictive neural network to generate factors, leveraging the robust spatial exploration capabilities inherent in deep learning while concurrently preserving diversity. The combination model within the framework incorporates the temporal performance of factors for selection and dynamically adjusts the weights assigned to each component alpha factor.

Experiments conducted on real-world datasets demonstrate that our proposed model outperforms contemporary benchmarks in formulaic alpha factor mining. Furthermore, our model exhibits a notable enhancement in portfolio returns within the realm of quantitative investment and real money investment.

---

## IC Metrics: Information Coefficient and ICIR

### Information Coefficient (IC)

The **Information Coefficient (IC)** represents the time-series average of Pearson's correlation coefficient between the factor value at time $t$ and the stock returns to be predicted:

$$
IC(f, X, Y) = \mathbb{E}_t[\rho(v_t, y_t)] = \frac{1}{T} \sum_{t=1}^{T} \rho(v_t, y_t)
$$

where:
- $f$ is the alpha factor
- $v_t = f(X_t) \in \mathbb{R}^n$ is the factor value for $n$ stocks at time $t$
- $y_t \in \mathbb{R}^n$ is the vector of future returns for $n$ stocks at time $t$
- $\rho(v_t, y_t)$ is the Pearson correlation coefficient for each cross-section
- $T$ is the total number of trading days

**Interpretation:** The IC describes the overall stock-picking ability of the factor. Higher absolute IC values indicate superior stock-picking performance. The correlation $\rho(v_t, y_t)$ for each cross-section depicts the relationship between the factor value and the subsequent period's return.

**Sign Handling:** The absolute value of IC is used in factor evaluation because a negative IC factor can be transformed into a positive IC factor by reversing the sign of the factor values.

### IC Information Ratio (ICIR)

The **ICIR** measures the consistency and stability of the IC over time. While the exact formula is not provided in the main paper text, it is conceptually defined as:

$$
ICIR = \frac{\text{Mean}(IC)}{\text{StdDev}(IC)}
$$

The ICIR represents the risk-adjusted information content of a factor, similar to a Sharpe ratio but applied to the IC time series. Higher ICIR indicates more consistent factor performance.

### Rank IC and Rank ICIR

**Rank IC** uses Spearman rank correlation instead of Pearson correlation to address the instability of Pearson correlation. This makes the metric more robust to outliers and non-linear relationships. The paper notes that "the inclusion of RankIC is necessary to complement the measurement indicators because of the instability of pearson correlation."

**ARBS Relevance:** These metrics are directly applicable to ARBS's signal evaluation framework:
- See `/home/user/ARBS/src/signals/base.py` for `BaseSignal.calculate_ic()` method
- See `/home/user/ARBS/src/signals/evaluation.py` for IC calculation utilities
- The `SignalCombiner` in `/home/user/ARBS/src/signals/combination.py` could use ICIR for dynamic weighting

---

## Factor Combination Methods

AlphaForge introduces a **dynamic factor combination model** that contrasts with traditional fixed-weight approaches. The key innovation is adapting factor weights based on recent performance.

### Traditional Approach (Fixed Weights)

Prior methods (e.g., reinforcement learning approaches) generate a set of alpha factors with **fixed combination weights**:

$$
\text{Mega-Alpha}_t = \sum_{i=1}^{k} w_i \cdot f_i(X_t)
$$

where $w_i$ are constant weights determined during training and $k$ is the total number of factors.

**Limitation:** Fixed weights cannot adapt to:
- The cyclic nature of each alpha factor's stock selection capability
- Potential for reversal over time (factors becoming ineffective or negatively correlated)
- Market regime changes and style shifts

### AlphaForge Dynamic Combination (Algorithm 2)

The dynamic approach reassesses and reweights factors at each time step:

**Step 1: Factor Reassessment**

At each trading day $t$, using data from the preceding $n$ days, calculate performance metrics for each factor $f \in Z$ (factor zoo):

- $IC_t^\rho(f)$: Recent IC over lookback window
- $ICIR_t^{\hat{\rho}}(f)$: Recent ICIR over lookback window

**Step 2: Factor Selection (Entry Criteria)**

Select factors that meet minimum thresholds:

$$
Z_t = \{f \in Z : IC_t^\rho(f) > IC' \text{ AND } ICIR_t^{\hat{\rho}}(f) > ICIR'\}
$$

where $IC'$ and $ICIR'$ are configurable threshold parameters.

**Step 3: Top-N Selection**

Sort $Z_t$ based on $IC_t^\rho(f)$ and select the top $N$ factors:

$$
Z_t^{(N)} = \text{Top-N}(Z_t, \text{sorted by } IC_t^\rho)
$$

**Step 4: Weight Optimization**

Fit a linear regression model using the selected factors to predict returns:

$$
\hat{y}_t = \beta_0 + \sum_{i=1}^{N} \beta_i \cdot f_i(X_t)
$$

The regression coefficients $\{\beta_i\}$ become the dynamic weights for that trading day.

**Step 5: Prediction**

Generate the Mega-Alpha signal for day $t$:

$$
\text{Mega-Alpha}_t = \text{Model.Predict}(X_t) = \sum_{i=1}^{N} \beta_i \cdot f_i(X_t)
$$

### Key Advantages

1. **Temporal Adaptability:** Weights adjust to current market conditions
2. **Factor Timing:** Inactive or reversed factors are excluded dynamically
3. **Efficiency:** Achieves "mine as much as you use" - all mined factors can contribute when effective
4. **Interpretability:** Linear model maintains explainability required in investment practice

**ARBS Relevance:** This dynamic combination approach could enhance `/home/user/ARBS/src/signals/combination.py`:
- Current `SignalCombiner` may use fixed weights or simple averaging
- Could implement rolling IC-based reweighting
- Factor selection based on recent performance (similar to factor timing)
- See `AlphaGenerator` in `/home/user/ARBS/src/signals/alpha.py` for IC-based scaling

---

## Factor Evaluation: Entry and Exit Criteria

### Entry Criteria (Factor Mining Stage)

During the factor mining process (Algorithm 1), new candidate factors must pass strict entry criteria to be added to the factor zoo $Z$:

$$
\pi(x, Z, X, Y) = \begin{cases}
|IC(f, X, Y)| & \text{if } f \text{ is valid and } \psi(f, Z, X, Y) < CORR' \\
0 & \text{otherwise}
\end{cases}
$$

where:
- $f = \text{parse}(x)$ is the operational formula parsed from the one-hot matrix representation $x$
- $Z$ is the existing factor zoo
- $\psi(f, Z, X, Y)$ computes the maximum absolute correlation between $f$ and each existing factor in $Z$
- $CORR'$ is a manually set correlation threshold

**Validity Check:** A factor is "valid" if:
1. The formula is syntactically correct
2. It can be evaluated on the data without errors (no division by zero, invalid operations, etc.)

**Three Fundamental Entry Requirements:**

1. **Stock-Picking Ability:** $|IC(f, X, Y)|$ must be sufficiently high (implicit threshold in fitness function)
2. **Stability:** ICIR is used to filter for stable performance
3. **Diversity:** $\psi(f, Z, X, Y) < CORR'$ ensures low correlation with existing factors

The paper states: "A strict criterion is maintained to ensure that factors included in the library meet specific requirements. Incorporating domain knowledge, our criteria for factor entry comprise three fundamental aspects: IC and ICIR are used to filter the stock-picking ability and stability, the correlation of returns with existing factors in the library avoids overlapping with the stock-picking ability of existing factors."

### Exit Criteria (Factor Combination Stage)

At each trading day $t$, factors are dynamically selected or excluded based on recent performance:

**Exclusion Conditions:**

A factor $f$ is excluded from the combination at time $t$ if:

$$
IC_t^\rho(f) \leq IC' \quad \text{OR} \quad ICIR_t^{\hat{\rho}}(f) \leq ICIR'
$$

**Additional Exclusion (Top-N Filtering):**

Even if a factor passes the IC/ICIR thresholds, it may be excluded if it doesn't rank in the top $N$ factors by IC performance.

### Factor Performance Momentum

The paper cites empirical evidence for factor timing:

> "Due to the momentum effect observed in factor performance, factors that have demonstrated success in the past tend to exhibit positive performance in the future" (EHSANI and LINNAINMAA 2022)

This justifies using recent performance ($IC_t^\rho$, $ICIR_t^{\hat{\rho}}$) to predict near-term effectiveness.

### Case Study: Dynamic Weights Over Time

Tables 2 and 3 (page 6) show factor composition changes day-to-day:

**Day 1 to Day 2 Changes:**
- Only 5 of 10 factors used on Day 1 remained on Day 2
- Factor #3 changed weight from -0.00014 to +0.00168 (sign reversal)
- This demonstrates dynamic adaptation to factor effectiveness changes

**ARBS Relevance:** Entry/exit criteria could be implemented in ARBS:
- Add `should_include_signal()` method to `SignalCombiner` based on rolling IC/ICIR
- Implement correlation checks when adding new signals to avoid redundancy
- See `/home/user/ARBS/src/signals/base.py` for potential integration points
- Could enhance `StrategyFactory` in `/home/user/ARBS/src/strategy/factory.py` with dynamic signal filtering

---

## Empirical Results

### Dataset and Methodology

**Markets:** CSI300 and CSI500 (China A-share market)

**Time Period:** 2018-2022 (5-year test period with annual retraining)

**Training Approach:**
- Rolling window: Model retrained annually with updated data
- Training set example: 2010-01-01 to 2016-12-31
- Validation set example: 2017-01-01 to 2017-12-31
- Test set example: 2018-01-01 to 2018-12-31

**Label:** `Ref(VWAP, -21)/Ref(VWAP, -1) - 1` (21-day forward return based on VWAP)

**Experimental Setup:**
- Each model run 5 times to account for random seed effects
- Results reported with standard deviations

### Main Results (Table 1)

Performance comparison on CSI300 and CSI500 datasets:

| Method | CSI 300 IC (%) | CSI 300 RankIC (%) | CSI 500 IC (%) | CSI 500 RankIC (%) |
|--------|----------------|-------------------|----------------|-------------------|
| XGBoost | 0.41 | 1.63 | 0.33 | 2.87 |
| MLP | 1.22 (0.16) | 1.75 (0.28) | 1.94 (0.11) | 3.31 (0.23) |
| LightGBM | 0.84 | 1.85 | 1.75 | 3.81 |
| GP (Genetic Programming) | 1.29 (0.44) | 2.72 (0.58) | 0.37 (0.76) | 2.34 (1.07) |
| DSO (Deep Symbolic Opt) | 2.55 (0.69) | 3.88 (1.12) | 1.38 (0.57) | 4.56 (0.61) |
| RL (Reinforcement Learning) | 2.09 (0.26) | 2.72 (0.42) | 1.91 (0.49) | 4.03 (0.62) |
| Static (AlphaForge without dynamic combination) | 2.43 (0.57) | 3.67 (0.46) | 2.05 (0.29) | 4.48 (0.46) |
| **AlphaForge (Full)** | **4.40 (0.56)** | **5.89 (0.69)** | **2.84 (0.58)** | **5.57 (0.58)** |

**Key Findings:**

1. **Formulaic vs ML Methods:** Formulaic methods (GP, RL, DSO, AlphaForge) generally outperform black-box ML methods (XGBoost, MLP, LightGBM) on interpretability
2. **Dynamic vs Static:** Full AlphaForge significantly outperforms "Static" version (81% improvement in CSI300 IC: 4.40% vs 2.43%)
3. **Consistency:** Standard deviations show reasonable consistency across runs
4. **Best Performance:** AlphaForge achieves highest IC and RankIC on both datasets

### Pool Size Analysis (Figure 2)

Tested pool sizes: [1, 10, 20, 50, 100]

**Findings:**
- Non-monotonic relationship between pool size and performance
- **Optimal pool size: N = 10 factors**
- Increasing beyond 10 factors shows diminishing returns

**Interpretation:** "At any given time, approximately 10 factors capture the most relevant price information. Thus, further increasing the factor library size could potentially yield diminishing returns."

### Ablation Study

Comparing components:
- **"Static":** Alpha factor mining with fixed-weight combination (RL-style)
- **"Dynamic" (Full AlphaForge):** Mining + dynamic combination

Results confirm efficacy of both:
1. Generative-predictive mining model outperforms previous state-of-the-art
2. Dynamic combination model significantly improves over static approach

### Simulated Trading Results

**Trading Strategy:**
- Universe: CSI300 stocks
- Position: Top 50 stocks with highest Mega-Alpha scores
- Weighting: Equal-weighted daily
- Rebalancing constraint: Maximum 5 stock changes per day (to reduce transaction costs)
- Period: January 1, 2018 to December 31, 2022 (5 years)

**Results (Figure 3, bottom panel):**
- AlphaForge achieves highest cumulative returns among all methods
- Consistently outperforms GP, RL, DSO baselines
- Demonstrates robustness over 5-year period

### Real Money Investment Results

**Account Details:**
- Investment: 3 million RMB
- Universe: CSI500
- Period: ~9 months (until paper submission)

**Results (Figure 3, top panel):**
- **Excess return vs CSI500: +21.68%**
- Real account validation confirms simulation results translate to live trading

**ARBS Relevance:**
- Provides empirical evidence for IC-based factor combination
- Optimal pool size (~10 factors) could inform `SignalCombiner` configuration
- Dynamic weighting shows clear benefits over static approaches
- Real money results validate the approach for production systems

---

## ARBS Integration Recommendations

### 1. Signal Combination (SignalCombiner)

**Current State:** `/home/user/ARBS/src/signals/combination.py`

**AlphaForge Insights:**
- Implement rolling IC/ICIR calculation for each signal
- Dynamic signal selection based on recent performance thresholds
- Top-N ranking mechanism (optimal N ≈ 10 per AlphaForge results)
- Linear regression for weight determination instead of fixed weights

**Proposed Enhancement:**
```python
class DynamicSignalCombiner:
    def __init__(self, lookback_days: int = 20,
                 ic_threshold: float = 0.02,
                 icir_threshold: float = 0.5,
                 max_signals: int = 10):
        self.lookback_days = lookback_days
        self.ic_threshold = ic_threshold
        self.icir_threshold = icir_threshold
        self.max_signals = max_signals

    def select_signals(self, signal_zoo, returns_history):
        # Calculate rolling IC and ICIR for each signal
        # Filter by thresholds
        # Rank by IC and select top N
        # Return selected signals
        pass

    def fit_weights(self, selected_signals, returns):
        # Use linear regression to determine optimal weights
        # Return weight vector
        pass
```

### 2. IC-Based Weighting (AlphaGenerator)

**Current State:** `/home/user/ARBS/src/signals/alpha.py`

**AlphaForge Formula:** $\alpha = IC \times \text{Vol} \times Z$

**Enhancement:** Incorporate time-varying IC estimates:
- Use rolling window IC instead of static IC
- Recompute IC periodically (daily or weekly)
- Scale alphas dynamically based on recent factor performance

### 3. Factor Entry Criteria

**New Feature:** Factor validation and correlation checking

**Implementation Location:** `/home/user/ARBS/src/signals/base.py`

**Criteria to Implement:**
1. **Validity:** Signal produces valid values (no NaN, inf)
2. **IC Threshold:** $|IC| > IC_{\text{min}}$ (e.g., 0.02)
3. **ICIR Threshold:** $ICIR > ICIR_{\text{min}}$ (e.g., 0.5)
4. **Correlation Threshold:** Max correlation with existing signals < 0.8

### 4. Factor Exit Criteria

**New Feature:** Dynamic signal filtering in backtests

**Implementation Location:** `/home/user/ARBS/src/backtest/minimal.py`

**Exit Conditions:**
- Recent IC falls below threshold
- Recent ICIR falls below threshold
- Factor not in top-N by IC ranking

### 5. Strategy Factory Integration

**Current State:** `/home/user/ARBS/src/strategy/factory.py`

**Enhancement:** Add dynamic combination strategy template

**YAML Configuration Example:**
```yaml
strategy:
  name: "dynamic_multi_signal"
  signals:
    - type: "carry"
    - type: "momentum"
    - type: "mean_reversion"
  combination:
    type: "dynamic"
    lookback_days: 20
    ic_threshold: 0.02
    icir_threshold: 0.5
    max_signals: 10
    refit_frequency: "daily"
```

### 6. Performance Monitoring

**New Feature:** Track IC/ICIR over time for each signal

**Benefits:**
- Monitor factor decay
- Identify regime changes
- Validate factor momentum hypothesis
- Inform signal retirement decisions

### 7. Key Takeaways for ARBS

1. **Dynamic > Static:** Time-varying weights significantly outperform fixed weights
2. **Factor Timing Works:** Recent performance predicts near-term effectiveness (momentum effect)
3. **Less is More:** Optimal factor count ~10 (diminishing returns beyond this)
4. **IC/ICIR Filtering:** Strict entry/exit criteria maintain signal quality
5. **Linear Interpretability:** Linear combination preserves explainability while performing well
6. **Correlation Control:** Ensuring low correlation among signals improves diversification
7. **Rolling Validation:** Annual retraining prevents overfitting to changing market conditions

---

## References

**Primary Citation:**

Shi, H., Song, W., Zhang, X., Shi, J., Luo, C., Ao, X., Arian, H., & Seco, L. (2024). AlphaForge: A Framework to Mine and Dynamically Combine Formulaic Alpha Factors. *arXiv preprint arXiv:2406.18394v5*.

**Key Related Work Cited:**

- EHSANI, S., & LINNAINMAA, J. T. (2022). Factor Momentum and the Momentum Factor. *The Journal of Finance*, 77(3), 1877-1919.
- Kakushadze, Z. (2016). 101 formulaic alphas. *Wilmott*, 2016(84), 72-81.
- Yu, S., et al. (2023). Generating Synergistic Formulaic Alpha Collections via Reinforcement Learning. *KDD '23*.

---

## Appendix: AlphaForge Algorithm Pseudocode

### Algorithm 1: Factor Mining Pipeline

```
Input: stock data X = {X_t}, Y = {y_t}
Output: Factor zoo Z = {f_1, ..., f_k}

Initialize Z = ∅
Sample randomized factors R = {x_1, ..., x_r}

while |Z| < TargetFactorNum:
    R_fitness = {π(x_1, Z, X, Y), ..., π(x_r, Z, X, Y)}

    # Train predictor P
    Train P with R and R_fitness

    # Train generator G
    for each epoch:
        z_1, z_2 ~ N(0, 1)
        x_1 = M(G(z_1)), x_2 = M(G(z_2))
        L(θ_G) = L_G(z_1, z_2, x_1, x_2, θ_P)
        θ_G ← GradientDescent(L(θ_G))

        Z_new = parse(x_1) ∪ parse(x_2)

        for f_new in Z_new:
            if f_new is qualified and f_new ∉ Z:
                Z ← Z ∪ {f_new}

        R ← R ∪ {x_1, x_2}

return Z
```

### Algorithm 2: Factor Combining Pipeline

```
Input: Factor zoo Z = {f_1, ..., f_k}, max factor number N,
       dataset X = {X_t}, Y = {y_t}
Output: Prediction Ŷ = {ŷ_t}

Ŷ ← ∅

for t ← 1 to T:
    Z_t = ∅

    # Evaluate and filter factors
    for all f ∈ Z:
        Calculate IC_t^ρ(f), ICIR_t^ρ̂(f)

        if IC_t^ρ(f) > IC' AND ICIR_t^ρ̂(f) > ICIR':
            Z_t ← Z_t ∪ {f}

    # Select top N factors
    Sort Z_t based on IC_t^ρ(f)
    Z_t^(N) = Top-N(Z_t)

    # Fit linear model and predict
    Model = LinearRegression(Z_t^(N), y_t)
    ŷ_t ← Model.Predict(X_t)
    Ŷ ← Ŷ ∪ ŷ_t

return Ŷ
```

---

*Document created: 2025-11-11*
*Last updated: 2025-11-11*
*ARBS Version: See git commit c82ba75*
