# AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay

<!-- ABOUTME: Reference document for AlphaAgent (2025) paper on LLM-driven alpha mining with regularization -->
<!-- ABOUTME: Focuses on alpha decay prevention, regularization methods, and factor crowding avoidance relevant to ARBS -->

## Paper Metadata

- **Title**: AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay
- **Authors**: Ziyi Tang, Zechuan Chen, Jiarui Yang, Jiayao Mai, Yongsen Zheng, Keze Wang, Jinrui Chen, Liang Lin
- **Affiliations**: Sun Yat-sen University, University of New South Wales, Nanyang Technological University, CUHK Shenzhen
- **Conference**: KDD '25, August 3–7, 2025, Toronto, ON, Canada
- **arXiv**: 2502.16789v2 [cs.CE] 9 Jun 2025
- **DOI**: [10.1145/3711896.3736838](https://doi.org/10.1145/3711896.3736838)
- **Code**: [https://github.com/RndmVariableQ/AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent)

## Abstract

Alpha mining focuses on discovering predictive signals for future asset returns. However, **alpha decay** (where factors lose predictive power over time) poses a significant challenge:

1. **Overfitting Problem**: Traditional genetic programming methods are prone to rapid alpha decay due to susceptibility to overfitting through excessive data mining ("p-hacking")
2. **Factor Crowding Problem**: LLM-driven approaches often fail to impose regularization against factor homogenization, resulting in crowded signals and accelerated decay

**AlphaAgent** addresses these challenges through three key regularization mechanisms:

1. **Originality enforcement**: Similarity measure based on Abstract Syntax Trees (ASTs) against existing alphas
2. **Hypothesis-factor alignment**: LLM-evaluated semantic consistency between market hypotheses and generated factors
3. **Complexity control**: AST-based structural constraints preventing over-engineered constructions prone to overfitting

**Results**: Extensive evaluations on Chinese CSI 500 and U.S. S&P 500 markets (2021-2024) show AlphaAgent outperforms traditional and LLM-based methods:
- CSI 500: 11.0% annual excess return (IR=1.5), -9.36% MDD
- S&P 500: 8.74% annual excess return (IR=1.05), -9.10% MDD
- 81% higher effective factor ratio (hit ratio)
- 30% fewer tokens consumed
- Remarkable resistance to alpha decay across bull and bear markets

## Alpha Decay

### What Causes Alpha Decay?

Alpha decay arises from two main challenges:

#### 1. Overfitting Through Excessive Data Mining

- **P-hacking**: Spurious factors appear significant in backtests but decay rapidly in real-world applications
- **Traditional GP/RL limitations**: Overemphasize historical performance optimization while neglecting underlying financial and economic rationale
- **Consequence**: Factors show strong historical performance but experience rapid alpha decay when deployed in live markets

#### 2. Factor Crowding

- **Definition**: When too many investors adopt similar strategies
- **Mechanism**: Collective actions of market participants executing similar trades diminish the factors' predictive power
- **Market stress**: Can trigger sudden reversals during periods of market stress
- **Real-world example**: Size factor's underperformance in China's A-share market in early 2024, highlighting risks of concentrated positioning in popular factors

#### 3. LLM-Specific Challenges

Without proper constraints, LLMs suffer from:
- **Over-reliance on established factors**: RSI, momentum, value, size effects
- **Lack of novelty**: Predominantly replicate existing market inefficiencies already exploited by participants
- **Factor homogenization**: Generate similar factors that exacerbate crowding
- **Result**: In rapidly evolving markets, LLM-generated factors struggle to uncover novel alpha

### How to Prevent Alpha Decay

AlphaAgent prevents alpha decay through systematic regularization:

#### Core Philosophy

Balance three competing objectives:
1. **Originality**: Explore novel market inefficiencies
2. **Financial rationale**: Maintain theoretical soundness through hypothesis alignment
3. **Adaptability**: Adjust to evolving market conditions while avoiding overfitting

#### Mathematical Formulation

Standard alpha mining objective:

$$f^* = \arg\max_{f \in \mathcal{F}} \mathcal{L}(f(\mathbf{X}), \mathbf{y}) - \lambda \mathcal{R}(f)$$

AlphaAgent's regularized objective:

$$f^* = \arg\max_{f \in \mathcal{F}} \mathcal{L}(f(\mathbf{X}), \mathbf{y}) - \lambda \mathcal{R}_g(f, h)$$

where:
- $\mathcal{F}$: Space of all possible factor expressions
- $\mathbf{y}$: Ground-truth future returns
- $\mathcal{L}$: Performance metric (IC, IR, etc.)
- $h \in \mathcal{H}$: Market hypothesis providing domain-relevant insights
- $\mathcal{R}_g(f, h)$: Regularization term encompassing complexity, alignment, and novelty

#### Empirical Evidence

**Figure 4 Results** (CSI 500, 2020-2024):
- **Alpha158**: IC dropped from 0.036 to ~0.0, RankIC from 0.042 to ~0.0
- **GP**: IC dropped from 0.022 to ~0.0, RankIC from 0.020 to ~0.0
- **RSI**: Similar substantial decline in predictive power
- **AlphaAgent**: IC consistently around 0.02, RankIC around 0.025 throughout period

This demonstrates AlphaAgent's **superior sustainability** compared to traditional factors exhibiting strong alpha decay.

## Regularization Methods

### Overview

The regularization term $\mathcal{R}_g(f, h)$ encompasses three critical components:

$$\mathcal{R}_g(f, h) = \alpha_1 \cdot \text{SL}(f) + \alpha_2 \cdot \text{PC}(f) + \alpha_3 \cdot \text{ER}(f, h)$$

where:
- $\text{SL}(f)$: **Symbolic length** (AST complexity)
- $\text{PC}(f)$: **Parameter count** (free hyperparameters)
- $\text{ER}(f, h)$: **Enhanced regularization** capturing novelty and hypothesis alignment
- $\{\alpha_1, \alpha_2, \alpha_3\}$: Weighting coefficients for trading off objectives

### 1. Complexity Control

#### Symbolic Length (SL)

- **Measure**: Number of nodes in Abstract Syntax Tree (AST)
- **Rationale**: Simpler expressions are more interpretable and less prone to overfitting
- **Implementation**: Count operators and features in parsed expression

#### Parameter Count (PC)

- **Measure**: Number of free hyperparameters (window lengths, thresholds)
- **Rationale**: Fewer parameters reduce degrees of freedom, limiting overfitting potential
- **Trade-off**: Balance between expressiveness and parsimony

#### Operator Library Abstraction

- **Purpose**: Standardize mathematical and financial operations
- **Benefits**:
  - Consistent, well-defined set of operations for LLMs
  - Simplifies semantic alignment between operator compositions and market hypotheses
  - Bridges gap between high-level market insights and low-level implementation
  - More robust and maintainable factor generation

### 2. Novelty Enforcement (Originality)

#### AST-Based Similarity Metric

Pairwise factor similarity using largest common subtree:

$$s(f_i, f_j) = \max_{t_i \subseteq T(f_i), t_j \subseteq T(f_j)} \{|t_i| : t_i \cong t_j\}$$

where:
- $T(f)$: Abstract syntax tree representation of factor $f$
- $t_i, t_j$: Subtrees of $T(f_i)$ and $T(f_j)$
- $|t_i|$: Size of subtree (number of nodes)
- $t_i \cong t_j$: Structural isomorphism between subtrees

#### Originality Score

Compare against existing alpha zoo $\mathcal{Z} = \{\phi_1, \phi_2, ..., \phi_N\}$ (e.g., Alpha101):

$$S(f) = \max_{\phi \in \mathcal{Z}} s(f, \phi)$$

- **Higher score**: More similar to existing factors (potentially crowded)
- **Lower score**: More original (potentially unexploited market inefficiency)
- **Application**: Penalize factors with high similarity to established alphas

### 3. Hypothesis Alignment

#### Consistency Scoring Function

$$\mathcal{C}(h, d, f) = \alpha c_1(h, d) + (1 - \alpha) c_2(d, f)$$

where:
- $h$: Market hypothesis
- $d$: Factor description (natural language)
- $f$: Factor expression (mathematical/code)
- $c_1(h, d) \in [0, 1]$: Whether description $d$ is valid implementation of hypothesis $h$
- $c_2(d, f) \in [0, 1]$: Whether expression $f$ matches description $d$
- $\alpha = 0.5$: Weighting parameter

#### LLM-Based Evaluation

LLMs evaluate two critical alignments:
1. **Hypothesis → Description**: Does the factor description validly implement the market hypothesis?
2. **Description → Expression**: Does the mathematical expression accurately reflect its description?

**Example of misalignment**: If a factor claims to capture market liquidity dynamics in its description but contains no liquidity-related components (trading volume, bid-ask spread, market depth), it receives a low $c_2$ score.

### 4. Combined Enhanced Regularization

$$\text{ER}(f, h) = \beta_1 \cdot S(f) + \beta_2 \cdot \mathcal{C}(h, d, f) + \beta_3 \cdot \log(1 + |\mathcal{F}_f|)$$

where:
- $\beta_1, \beta_2, \beta_3$: Weighting coefficients
- $\mathcal{F}_f$: Set of raw features used in factor $f$'s expression
- $\log(1 + |\mathcal{F}_f|)$: Logarithmic penalty for excessive feature usage (promotes parsimony)

**Interpretation**:
- **Lower ER score** → Better factor quality
- First term: Penalizes similarity to existing factors
- Second term: Ensures hypothesis alignment
- Third term: Controls expression complexity

### 5. Abstract Syntax Tree (AST) Representation

#### Factor Parsing

Parsing procedure: $\mathcal{G} : (\mathcal{H}, \mathcal{X}) \to \mathcal{F}$

**Steps**:
1. **Identify key phrases** in hypothesis $h$ (e.g., "triangle pattern", "breakout")
2. **Map to operators** in operator library $\mathcal{O}$
3. **Assign parameters** (window size, threshold) based on $h$ or domain defaults
4. **Assemble AST** $T(f)$ capturing computational dependencies and execution flow

#### AST Structure

- **Leaf nodes**: Raw feature references (e.g., `$high`, `$low`, `$volume`)
- **Internal nodes**: Operator instances (e.g., `TS_MIN(.)`, `SMA(.)`)
- **Edges**: Data flow between operations

**Benefits**:
- Addresses inconsistent quality of LLM-generated code
- Avoids data format incompatibilities, package version inconsistencies
- Maintains semantic coherence
- Balances code executability with semantic consistency

## Factor Crowding

### Understanding Factor Crowding

**Definition**: When too many investors adopt similar strategies, their collective actions diminish the factors' predictive power.

### Mechanisms

1. **Market Impact**: Large-scale similar trading moves prices before all participants can execute
2. **Information Decay**: Widely-known inefficiencies get arbitraged away
3. **Liquidity Constraints**: Too many traders competing for same opportunities
4. **Stress Amplification**: During market stress, crowded positions face sudden reversals

### Real-World Evidence

**China A-Share Market (Early 2024)**:
- Size factor experienced significant underperformance
- Demonstrated risks of concentrated positioning in popular factors
- Highlighted need for factor diversification

**Alpha Decay Analysis** (Figure 4):
- **Alpha158**: Substantial decline from IC=0.036 to ~0.0 over 4 years
- **GP**: Rapid performance deterioration (IC from 0.022 to ~0.0)
- **RSI Indicator**: Significant degradation exemplifying crowding effect

### How AlphaAgent Avoids Factor Crowding

#### 1. Originality Enforcement

- **AST-based similarity metric** compares against Alpha101 and other established factor libraries
- **Penalty mechanism**: High similarity scores penalized in $\text{ER}(f, h)$ term
- **Result**: Encourages exploration of novel, less-exploited market inefficiencies

#### 2. Diverse Factor Generation

**Figure 5 Evidence** (IC evolution across 5 rounds):
- **AlphaAgent**: Increasing variance (expanding shaded region) suggests diverse factor exploration
- **RD-Agent**: Relatively stable, smaller variance indicates homogeneous candidates
- **Implication**: Wider exploration space leads to higher probability of discovering effective, uncrowded factors

#### 3. Hypothesis-Driven Exploration

- **Market hypotheses** $h \in \mathcal{H}$ guide factor construction with domain-relevant insights
- **Prevents over-reliance** on established factors (momentum, value, size effects)
- **Explores diverse** market inefficiency patterns:
  - Candlestick patterns
  - Fundamental analysis results
  - Market microstructure theories
  - Behavioral finance insights

#### 4. Empirical Results

**Ablation Study** (Figure 6, 100 rounds across CSI 500 and S&P 500):
- **Hit ratio**: 0.29 (AlphaAgent) vs 0.16 (w/o factor constraints) = **81% improvement**
- **Interpretation**: Factor modeling constraints significantly enhance quality and reduce crowding
- **Sustained performance**: Maintains stable IC/RankIC while traditional factors decay

## LLM Methodology

### Multi-Agent Framework

AlphaAgent implements a recurrent framework with three specialized LLM-powered agents:

#### 1. Idea Agent (Hypothesis Generation)

**Purpose**: Synthesize market hypotheses by integrating domain knowledge

**Structured Hypothesis Components**:
1. **Observations**: Empirical grounding through analysis of current market conditions or experimental results from previous rounds
2. **Knowledge**: Synthesis of:
   - Established financial theories (market efficiency, behavioral finance)
   - Empirical market intuitions (momentum, mean reversion)
   - Practitioners' conjectures from trading experience
3. **Justification**: Theoretical soundness linking observed patterns to underlying economic mechanisms
4. **Specification**: Implementation constraints (optional numeric/time-window parameters like "10-day high/low")

**Process**:
- **Initialization**: Generates seed hypothesis $h_0$ based on user-assigned research direction or market insight
- **Evolution**: Uses chain-of-thought reasoning to refine hypotheses based on feedback from eval agent
- **Iterative refinement**: Leverages $h_0$ as evolving anchor, driven by analysis of historical evolving traces

#### 2. Factor Agent (Factor Construction)

**Purpose**: Bridge theoretical market hypotheses and quantitative manifestations

**Multi-Stage Refinement Pipeline**:
1. **Multiple candidate generation**: Creates several implementations for each hypothesis
2. **Complexity filtering**: Applies AST-based complexity constraints
3. **Alignment filtering**: Ensures hypothesis-factor semantic consistency
4. **Originality checking**: Compares against existing factor libraries using AST similarity
5. **Iterative optimization**: Refines until satisfying originality, alignment, and complexity constraints

**Knowledge Base**:
- Maintains **evolving knowledge base** of successful and failed implementations
- **Failure categorization**: Hypothesis misalignment, structural complexity violations
- **Experiential learning**: Proactively avoids similar pitfalls in subsequent iterations
- **Historical reference**: Optimizes new factors by referencing similar historical cases

#### 3. Eval Agent (Evaluation and Feedback)

**Purpose**: Multi-dimensional evaluation and feedback generation

**Evaluation Aspects**:
1. **Predictive capability metrics**: IC, RankIC, ICIR (forecasting effectiveness)
2. **Return performance metrics**: AR, IR (profit-generating ability)
3. **Risk control metrics**: MDD, volatility (stability and robustness)

**Backtesting System**:
- Uses Qlib framework on CSI 500 (China) and S&P 500 (U.S.)
- Raw data: OHLCV only ($open, $high, $low, $close, $volume)
- LightGBM model (max depth 4) for next-day return forecasting
- Top-k dropout strategy: Select 50 top-ranked stocks, exclude 5 lowest
- Transaction costs: CSI 500 (0.0005 buy, 0.0015 sell), S&P 500 (0.0005 sell only)

**Feedback Loop**:
- **Evaluation history**: Tracks factors' performance over time
- **Pattern identification**: Identifies emerging patterns in successes and failures
- **Systematic feedback**: Provides insights to idea agent for hypothesis refinement
- **Closed-loop mechanism**: Continuously optimizes overall alpha mining process

### LLM Implementation Details

**Base Model**: GPT-3.5-turbo (also tested with GPT-4-turbo, Qwen-Plus, DeepSeek-R1)

**Model Comparison Results** (Figure 7, S&P 500 2021-2024):
- **GPT-3.5-turbo**: Good baseline performance, cost-effective
- **Qwen-Plus**: Improved over GPT-3.5-turbo
- **DeepSeek-R1** (reasoning LLM): Best performance
  - Highest ICIR: 0.0615
  - Highest AR: 9.19%
  - Lowest MDD: -6.50%

**Statistical Significance**: Student's t-test confirms AlphaAgent improvements over RD-Agent (p < 0.05 across all LLMs)

### Closed-Loop Autonomous Workflow

**Iterative Process** (Figure 1):
1. **Hypothesis Proposal** (Idea Agent) → Market insight $h$
2. **Factor Construction** (Factor Agent) → Candidate factors $\{f_1, f_2, ..., f_m\}$
3. **Evaluation** (Eval Agent) → Backtesting, executability, numerical stability
4. **Feedback Analysis** → Performance analysis guides next iteration
5. **Refinement** → Loop back to step 1 with refined insights

**Convergence Strategy**:
- Alternating optimization between $\mathcal{L}$ (performance) and $\mathcal{R}_g$ (regularization)
- Continues until locally optimal alpha found balancing predictive ability, domain soundness, and factor uniqueness

## ARBS Relevance

### 1. Preventing Signal Overfitting

#### Complexity-Based Regularization

**ARBS Application**:
```python
# In AlphaGenerator or signal construction
def calculate_regularization_penalty(signal_expression):
    """
    Penalize overly complex signals prone to overfitting.
    """
    ast_tree = parse_to_ast(signal_expression)
    symbolic_length = count_ast_nodes(ast_tree)
    parameter_count = count_free_parameters(ast_tree)

    # AlphaAgent-inspired penalty
    complexity_penalty = α1 * symbolic_length + α2 * parameter_count
    return complexity_penalty
```

**Key Insights**:
- **Simple signals** (low SL, low PC) generalize better to unseen data
- **Parameter parsimony** reduces degrees of freedom, limiting overfitting
- **AST-based metrics** provide objective complexity measures
- **Trade-off tuning**: Adjust $\{\alpha_1, \alpha_2\}$ based on validation performance

#### Feature Usage Control

From Equation 8: $\beta_3 \cdot \log(1 + |\mathcal{F}_f|)$

**ARBS Application**:
- Penalize signals using excessive features
- Logarithmic penalty encourages feature selection
- Promotes signals based on core, meaningful market data
- Reduces risk of spurious correlations from feature overload

### 2. Alpha Decay Detection

#### IC/RankIC Monitoring

**Key Metrics**:
- **IC (Information Coefficient)**: Correlation between predicted scores and actual returns
- **RankIC**: Spearman rank correlation (more robust to outliers)
- **ICIR**: IC mean / IC std dev (consistency of predictive power)

**ARBS Implementation**:
```python
# In TearSheet or analysis module
def monitor_alpha_decay(signal_returns, actual_returns, window_size=252):
    """
    Track IC stability over time to detect alpha decay.
    AlphaAgent showed stable IC ~0.02 over 4 years vs. traditional decay to ~0.0
    """
    ic_series = rolling_ic(signal_returns, actual_returns, window=window_size)

    # Decay indicators
    ic_trend = linear_regression_slope(ic_series)  # Negative = decay
    ic_stability = ic_series.std()  # Higher = less stable
    recent_vs_historical = ic_series[-252:].mean() / ic_series[:-252].mean()

    return {
        'ic_trend': ic_trend,
        'ic_stability': ic_stability,
        'performance_ratio': recent_vs_historical
    }
```

**Warning Thresholds**:
- **Trend**: Negative slope steeper than -0.001 per month
- **Stability**: IC std dev > 0.01
- **Performance ratio**: Recent IC < 0.7 × historical IC

#### Rolling Window Evaluation

**AlphaAgent Approach**:
- Yearly IC evaluation (Figure 4): 2020, 2021, 2022, 2023, 2024
- Traditional factors showed clear decay trajectory
- AlphaAgent maintained stability

**ARBS Application**:
- Evaluate signals on multiple rolling windows (1y, 6m, 3m)
- Compare recent vs. historical performance
- Flag signals with deteriorating predictive power
- Consider factor retirement or retraining

### 3. Avoiding Factor Crowding

#### Novelty Checking Against Signal Library

**ARBS Implementation**:
```python
# In signal development workflow
def check_signal_novelty(new_signal, signal_library):
    """
    Compute AST similarity against existing signals.
    High similarity = potentially crowded trade.
    """
    new_ast = parse_to_ast(new_signal)

    similarity_scores = []
    for existing_signal in signal_library:
        existing_ast = parse_to_ast(existing_signal)
        similarity = compute_ast_similarity(new_ast, existing_ast)
        similarity_scores.append(similarity)

    max_similarity = max(similarity_scores)

    # AlphaAgent penalizes high similarity in ER(f, h)
    if max_similarity > SIMILARITY_THRESHOLD:  # e.g., 0.7
        return {
            'novel': False,
            'max_similarity': max_similarity,
            'most_similar_signal': signal_library[np.argmax(similarity_scores)]
        }
    else:
        return {'novel': True, 'max_similarity': max_similarity}
```

**Signal Library**:
- Maintain library of established signals: CarrySignal, MomentumSignal, MeanReversionSignal
- Add widely-known factors: Alpha101, technical indicators
- Update with signals showing decay (likely crowded)

#### Diversity Metrics

**AlphaAgent Evidence** (Figure 5):
- Increasing variance across rounds = diverse exploration
- Stable variance = homogeneous factors (crowding risk)

**ARBS Application**:
- Track correlation matrix of active signals
- Target low pairwise correlations (< 0.5)
- Ensure signals capture different market inefficiencies
- SignalCombiner should verify diversity before combination

### 4. Hypothesis-Driven Signal Development

#### Financial Rationale First

**AlphaAgent Principle**: Every factor must align with market hypothesis $h$

**ARBS Application**:
```python
class HypothesisDrivenSignal(BaseSignal):
    """
    Signal must document underlying market hypothesis.
    AlphaAgent requires 4 components: observation, knowledge, justification, specification.
    """
    def __init__(self, hypothesis: dict):
        self.hypothesis = hypothesis
        self.validate_hypothesis()

    def validate_hypothesis(self):
        required_components = ['observation', 'knowledge', 'justification', 'specification']
        for component in required_components:
            if component not in self.hypothesis:
                raise ValueError(f"Missing hypothesis component: {component}")

    def generate(self):
        # Implementation guided by hypothesis['specification']
        pass
```

**Benefits**:
- Prevents pure data mining without economic rationale
- Reduces spurious signals from p-hacking
- Facilitates signal interpretation and debugging
- Aligns with Grinold-Kahn philosophy of informed active management

### 5. Regularized Signal Optimization

#### Multi-Objective Framework

**AlphaAgent Objective**: $f^* = \arg\max \mathcal{L}(f(\mathbf{X}), \mathbf{y}) - \lambda \mathcal{R}_g(f, h)$

**ARBS Adaptation**:
```python
# In AlphaGenerator or signal optimization
def optimize_signal_with_regularization(signal_candidates, returns, hypotheses):
    """
    Balance predictive performance with complexity/novelty constraints.
    """
    scores = []
    for signal, hypothesis in zip(signal_candidates, hypotheses):
        # Performance term
        ic = calculate_ic(signal, returns)
        sharpe = calculate_sharpe(signal, returns)
        performance_score = ic * sharpe

        # Regularization term
        complexity = calculate_complexity_penalty(signal)
        novelty = calculate_novelty_penalty(signal, SIGNAL_LIBRARY)
        alignment = evaluate_hypothesis_alignment(signal, hypothesis)
        regularization = α1*complexity + α2*novelty + α3*alignment

        # Combined objective
        total_score = performance_score - λ * regularization
        scores.append(total_score)

    return signal_candidates[np.argmax(scores)]
```

**Hyperparameter Tuning**:
- $\lambda$: Overall regularization strength (0.01 - 0.1)
- $\{\alpha_1, \alpha_2, \alpha_3\}$: Component weights (tune on validation set)
- Avoid pure performance maximization (leads to overfitting)

### 6. Practical Recommendations

#### Signal Development Workflow

1. **Start with hypothesis** (financial/economic rationale)
2. **Design signal** following hypothesis specification
3. **Check complexity** (AST nodes, parameter count)
4. **Verify novelty** against existing signal library
5. **Validate alignment** between hypothesis and implementation
6. **Backtest with regularization** penalty in objective
7. **Monitor for decay** using rolling IC/RankIC

#### Warning Signs of Overfitting/Decay

**Overfitting Indicators**:
- Very high in-sample IC (> 0.10) but poor out-of-sample
- Large number of parameters (> 5 free parameters)
- Complex expression (> 20 AST nodes for basic signal)
- High feature count (> 10 features)
- Perfect alignment with specific historical patterns

**Decay Indicators**:
- Declining IC trend over time (Figure 4 pattern)
- Increasing correlation with established factors
- Performance deterioration in recent periods
- Higher volatility of IC values

#### Integration with ARBS Architecture

**Returns Pipeline**:
- Add complexity regularization in `AlphaGenerator.generate()`
- Track AST metrics alongside IC/volatility scaling

**Signal Pipeline**:
- Extend `BaseSignal` with hypothesis documentation
- Add novelty checking in signal registration
- Maintain signal library for similarity comparison

**Risk Pipeline**:
- Monitor signal correlation matrix (factor crowding detection)
- Flag highly-correlated signal pairs
- Adjust covariance estimates for crowded factors

**Portfolio Construction**:
- Include regularization term in optimizer objective
- Penalize portfolios overweight in crowded signals
- Diversify across uncorrelated alpha sources

### 7. Key Takeaways for ARBS

1. **Complexity control prevents overfitting**: Use AST-based metrics (SL, PC) to regularize signals
2. **Novelty enforcement avoids crowding**: Compare new signals against library using structural similarity
3. **Hypothesis alignment ensures soundness**: Require financial rationale for every signal
4. **Decay monitoring enables adaptation**: Track IC/RankIC stability over rolling windows
5. **Multi-objective optimization balances trade-offs**: Don't maximize performance alone; include regularization
6. **Diversity is key to sustainability**: Maintain low correlation across signals
7. **Empirical validation**: AlphaAgent's 81% hit ratio improvement demonstrates regularization effectiveness

### 8. Limitations and Future Work

**Current Limitations**:
- AST similarity requires symbolic expressions (not applicable to black-box ML models)
- Hypothesis alignment needs LLM evaluation (computational cost)
- Optimal regularization weights $\{\alpha_i, \beta_i, \lambda\}$ require tuning

**Future ARBS Enhancements**:
- Automated regularization weight selection via cross-validation
- Extend AST similarity to portfolio composition patterns
- Integrate hypothesis documentation into signal development TDD workflow
- Build comprehensive signal library for novelty checking
- Develop alpha decay prediction model based on signal characteristics
