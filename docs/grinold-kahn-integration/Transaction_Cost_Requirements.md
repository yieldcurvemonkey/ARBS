# Transaction Cost Implementation Requirements

**Created**: 2025-11-17
**Purpose**: Complete specification for adding transaction costs to ARBS

## Executive Summary

ARBS currently lacks transaction cost modeling, which creates unrealistic backtests. This document specifies the mathematical models, data requirements, and integration points for comprehensive transaction cost implementation.

## 1. Cost Components Overview

### 1.1 Fixed Costs (Per Transaction)
- **Commissions**: Broker fees per trade
- **Exchange Fees**: Trading venue charges
- **Clearing Fees**: Clearinghouse charges
- **Regulatory Fees**: SEC, FINRA fees

### 1.2 Variable Costs (Proportional to Size)
- **Bid-Ask Spread**: Half-spread cost on entry/exit
- **Market Impact**: Price movement from order
- **Timing Risk**: Adverse price movement during execution
- **Opportunity Cost**: Unfilled portions of orders

### 1.3 Special Costs (Situation-Specific)
- **Borrow Costs**: For short positions
- **Financing Costs**: Leverage charges
- **Currency Conversion**: FX spreads for cross-currency

## 2. Mathematical Models

### 2.1 Basic Linear Model

**Formula**:
```
Cost = Commission + (Spread/2) × Notional
```

**Parameters**:
- Commission: $0.001-0.005 per share (equities)
- Spread: 1-10 bps for liquid instruments

**When to Use**:
- Small orders (< 1% ADV)
- Liquid instruments only
- Quick estimates

### 2.2 Square-Root Market Impact Model

**Formula**:
```
Cost = Spread/2 + σ × γ × Sign(Q) × √(|Q|/ADV)
```

**Parameters**:
- σ: Daily volatility (10-30% annually)
- γ: Market impact coefficient (0.1-0.3)
- Q: Trade size (shares or notional)
- ADV: Average daily volume

**Calibration**:
- γ ≈ 0.1 for liquid stocks
- γ ≈ 0.2 for mid-cap
- γ ≈ 0.3 for small-cap

### 2.3 Almgren-Chriss Model

**Formula**:
```
Cost = ε(v) + η(v) + λσ²T
```

Where:
- ε(v): Permanent impact = γ × v
- η(v): Temporary impact = (1/2) × η × σ × √(v/V)
- λσ²T: Timing risk penalty

**Parameters**:
- v: Trading rate (shares/time)
- V: Daily volume
- T: Trading horizon
- λ: Risk aversion

### 2.4 Implementation Shortfall Components

**Total Implementation Shortfall**:
```
IS = (P_decision - P_final) × Side
   = Delay_cost + Trading_cost + Opportunity_cost
```

**Component Formulas**:
```
Delay_cost = (P_arrival - P_decision) × Shares_total
Trading_cost = Σ(P_execution_i - P_arrival) × Shares_i
Opportunity_cost = (P_final - P_arrival) × Shares_unfilled
```

## 3. Asset-Class Specific Models

### 3.1 Futures (STIR/Bond Futures)

**Round-Trip Costs**:
```
Cost_RT = 2 × (Commission + 0.5 × Tick_size) + Roll_cost
```

**Typical Values**:
- SOFR futures: 0.25-0.5 ticks + $0.50-1.50 commission
- Treasury futures: 0.5-1 tick + $1.50-2.50 commission
- Roll cost: 0-2 ticks depending on curve

### 3.2 Interest Rate Swaps

**Cost Structure**:
```
Cost = Bid_ask_spread + CVA/DVA + Initial_margin_cost
```

**Typical Spreads**:
- USD swaps: 0.25-0.5 bps (2Y), 0.5-1 bp (10Y), 1-2 bps (30Y)
- Cross-currency: 2-5 bps additional

### 3.3 Corporate Bonds

**Formula**:
```
Cost = (Bid_ask_spread/2) × (1 + Size_factor)
Size_factor = max(0, log(Trade_size/Average_trade) / 2)
```

**Typical Spreads**:
- IG bonds: 5-25 bps
- HY bonds: 25-100 bps
- Distressed: 100-500 bps

## 4. Short Selling Costs

### 4.1 Borrow Rate Model

**Annual Cost**:
```
Borrow_cost = Rate × Notional × (Days/365)
```

**Rate Tiers**:
- General Collateral (GC): 0.3-0.5%
- Easy to Borrow: 0.5-2%
- Hard to Borrow: 2-10%
- Special: 10-100%+

### 4.2 Recall Risk Cost

**Expected Cost**:
```
Recall_cost = P(recall) × Cost_to_replace
```

Where:
- P(recall) increases with borrow rate
- Cost_to_replace = spread + market impact of covering

### 4.3 Regulatory Costs

**Additional Charges**:
- Locate fees: $0.001-0.01 per share
- Reg SHO charges: Variable
- Buy-in risk: Catastrophic tail risk

## 5. Integration Points in ARBS

### 5.1 Optimizer Integration

**Modified Objective Function**:
```
maximize: w'α - (λ/2)w'Σw - C(w, w_prev)
```

Where C(w, w_prev) is transaction cost from rebalancing

**Turnover Penalty**:
```
C(w, w_prev) = Σ cost_model(|w_i - w_prev_i|)
```

### 5.2 Backtest Integration

**At Each Rebalance**:
```
1. Calculate target weights (w_target)
2. Calculate turnover: Δw = w_target - w_current
3. Calculate costs: C = cost_model(Δw)
4. Adjust returns: r_net = r_gross - C
5. Update portfolio with net returns
```

### 5.3 Signal Generation Integration

**Net Alpha Calculation**:
```
α_net = α_gross - E[transaction_cost]
```

**Don't Trade If**:
```
α_net < min_alpha_threshold (typically 10-20 bps)
```

## 6. Data Requirements

### 6.1 Market Data
- **Bid-Ask Spreads**: Real-time or historical
- **Volume**: ADV, intraday profiles
- **Volatility**: Realized or implied
- **Market Depth**: Order book data

### 6.2 Execution Data
- **Historical Fills**: Price, size, time
- **Slippage History**: Expected vs actual
- **Market Impact**: Post-trade analysis

### 6.3 Cost Analytics
- **Borrow Rates**: By security, over time
- **Commission Schedules**: By broker, asset class
- **Historical Shortfall**: For calibration

## 7. Calibration Methods

### 7.1 Historical Calibration

**Regression Model**:
```
Actual_cost = β₀ + β₁×Spread + β₂×√(Size/ADV) + ε
```

**Steps**:
1. Collect historical execution data
2. Calculate realized costs
3. Regress against model features
4. Extract coefficients

### 7.2 Cross-Sectional Calibration

**By Liquidity Bucket**:
```
γ_bucket = median(cost_i / √(size_i/ADV_i))
```

For all trades in liquidity bucket

### 7.3 Dynamic Calibration

**Time-Varying Parameters**:
```
γ_t = γ_base × (1 + κ×VIX_t/VIX_avg)
```

Adjusts impact coefficient with market volatility

## 8. Validation Framework

### 8.1 Backtest Validation

**Test 1: Cost Attribution**
- Run backtest with/without costs
- Measure: Performance degradation
- Expected: 50-200 bps annually for active strategies

**Test 2: Turnover Analysis**
- Track: Actual turnover vs expected
- Validate: Cost scales with turnover

### 8.2 Model Validation

**Test 1: In-Sample Fit**
- Compare: Model predictions vs realized costs
- Metric: R² > 0.7 for good model

**Test 2: Out-of-Sample**
- Train: On historical data
- Test: On recent executions
- Metric: Mean absolute error < 2 bps

### 8.3 Stress Testing

**Scenarios**:
1. High volatility periods (VIX > 30)
2. Low liquidity (August, December)
3. Large positions (> 5% ADV)
4. Cascade effects (multiple strategies trading)

## 9. Implementation Phases

### Phase 1: Basic Linear Model (Week 1)
- Fixed costs (commissions, fees)
- Linear spread costs
- Simple integration with optimizer

### Phase 2: Market Impact (Week 2)
- Square-root impact model
- ADV-based scaling
- Volatility adjustment

### Phase 3: Short Costs (Week 3)
- Borrow rate integration
- Recall risk modeling
- Net alpha for shorts

### Phase 4: Advanced Models (Week 4)
- Almgren-Chriss implementation
- Multi-period optimization
- Timing risk penalties

### Phase 5: Calibration & Validation (Week 5)
- Historical calibration
- Model validation
- Performance attribution

## 10. Expected Impact on Strategy Performance

### 10.1 Performance Degradation

**Typical Impact by Strategy Type**:

| Strategy Type | Holding Period | Expected Cost Drag |
|--------------|---------------|-------------------|
| HFT | Minutes | 200-500 bps/year |
| Day Trading | Hours | 100-300 bps/year |
| Swing Trading | Days | 50-150 bps/year |
| Momentum | Weeks | 30-100 bps/year |
| Value | Months | 10-50 bps/year |
| Buy & Hold | Years | 1-10 bps/year |

### 10.2 Optimal Rebalancing Frequency

**Without Costs**:
```
Rebalance continuously (daily)
```

**With Costs**:
```
f_optimal = √(α_decay_rate / (2 × transaction_cost))
```

**Example**:
- α decay = 2%/month
- Transaction cost = 10 bps
- Optimal: Rebalance every 10 days

### 10.3 Position Sizing Impact

**Without Costs**:
```
All positions sized by alpha
```

**With Costs**:
```
Don't trade if: |α| < 2 × expected_cost
Reduce position if: |α| < 4 × expected_cost
```

## 11. Risk Management Considerations

### 11.1 Cost Budget

**Annual Cost Budget**:
```
Max_cost = Target_alpha × Cost_ratio
```

Where Cost_ratio typically 20-30%

### 11.2 Turnover Limits

**Hard Limits**:
```
Daily_turnover < 2 × Portfolio_value
Monthly_turnover < 10 × Portfolio_value
```

### 11.3 Liquidity Constraints

**Position Limits**:
```
Position_size < min(
    Risk_limit,
    0.10 × ADV,  # 10% of daily volume
    0.01 × Market_cap  # 1% of company
)
```

## 12. Reporting Requirements

### 12.1 Cost Analytics Dashboard

**Key Metrics**:
- Total costs (bps, $)
- Cost breakdown by component
- Cost vs alpha ratio
- Turnover statistics

### 12.2 Performance Attribution

**Attribution Formula**:
```
Total_return = Gross_alpha - Transaction_costs - Slippage - Financing
```

### 12.3 Best Execution Monitoring

**Metrics**:
- Implementation shortfall
- VWAP relative performance
- Hit rate (fills vs attempts)
- Reject rate analysis

## Summary

Transaction costs are the difference between paper profits and real returns. This comprehensive framework provides:

1. **Mathematical Models**: From simple linear to advanced Almgren-Chriss
2. **Asset-Specific Formulas**: Futures, swaps, bonds, equities
3. **Integration Points**: Optimizer, backtester, signals
4. **Calibration Methods**: Historical, cross-sectional, dynamic
5. **Validation Framework**: Ensuring models match reality

Expected impact: 50-200 bps annual cost for active strategies, requiring careful optimization of rebalancing frequency and position sizing to maintain positive net alpha.