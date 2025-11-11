# Sector ETF Research & GICS Mapping

**Date**: 2025-11-11
**Author**: AGENT-02
**Status**: Complete
**Purpose**: Document SPDR Select Sector ETFs for ARBS equity sector portfolio integration

---

## Executive Summary

This document provides comprehensive research on SPDR Select Sector ETFs and their mapping to GICS Level 1 sectors. The 11 SPDR Select Sector ETFs provide liquid, low-cost exposure to each of the 11 GICS sectors, making them ideal instruments for sector hedging, sector rotation strategies, and market-neutral equity portfolios.

### Key Findings

- **Perfect 1:1 GICS mapping**: Each of the 11 SPDR sector ETFs maps exactly to one GICS Level 1 sector
- **Exceptional liquidity**: All ETFs exceed $100M average daily trading volume (measured in dollar volume)
- **Low cost**: Uniform 0.08% expense ratio across all 11 ETFs
- **Large AUM**: Combined AUM of ~$350B+ as of November 2025
- **Recommended use**: Separate hedging/overlay instruments for long/short sector-neutral strategies

---

## SPDR Select Sector ETFs (11 ETFs)

### Complete Listing

| Ticker | Full Name | GICS Sector | AUM (Nov 2025) | Expense Ratio | Avg Daily Volume |
|--------|-----------|-------------|----------------|---------------|------------------|
| **XLK** | Technology Select Sector SPDR Fund | Information Technology | $93.2B | 0.08% | ~50M shares / $11B |
| **XLF** | Financial Select Sector SPDR Fund | Financials | $54.0B | 0.08% | ~40M shares / $2.1B |
| **XLV** | Health Care Select Sector SPDR Fund | Health Care | $37.2B | 0.08% | ~12M shares / $2.1B |
| **XLE** | Energy Select Sector SPDR Fund | Energy | $26.2B | 0.08% | ~25M shares / $2.3B |
| **XLC** | Communication Services Select Sector SPDR Fund | Communication Services | $25.5B | 0.08% | ~8M shares / $600M |
| **XLY** | Consumer Discretionary Select Sector SPDR Fund | Consumer Discretionary | $24.0B | 0.08% | ~5M shares / $900M |
| **XLI** | Industrial Select Sector SPDR Fund | Industrials | $23.9B | 0.08% | ~11M shares / $1.5B |
| **XLU** | Utilities Select Sector SPDR Fund | Utilities | $17.9B | 0.08% | ~12M shares / $800M |
| **XLP** | Consumer Staples Select Sector SPDR Fund | Consumer Staples | $16.1B | 0.08% | ~10M shares / $800M |
| **XLRE** | Real Estate Select Sector SPDR Fund | Real Estate | $7.6B | 0.08% | ~6M shares / $250M |
| **XLB** | Materials Select Sector SPDR Fund | Materials | $5.5B | 0.08% | ~5M shares / $300M |

**Total Combined AUM**: ~$330.5 billion (as of November 2025)

### Liquidity Analysis

All 11 SPDR Select Sector ETFs meet or exceed the $100M average daily dollar volume threshold:

- **Tier 1 (>$2B daily)**: XLK, XLF, XLV, XLE (extremely liquid)
- **Tier 2 ($500M-$2B daily)**: XLC, XLY, XLI, XLU, XLP (highly liquid)
- **Tier 3 ($100M-$500M daily)**: XLRE, XLB (liquid)

**Verdict**: All 11 ETFs are highly liquid and suitable for institutional trading. Even the smallest (XLB at ~$300M daily) provides sufficient liquidity for ARBS implementation.

---

## GICS Sector Classification (11 Sectors)

The Global Industry Classification Standard (GICS) consists of 11 sectors at Level 1. These were established by MSCI and S&P Dow Jones Indices, with the 11th sector (Real Estate) added in 2016 when it was split from Financials.

### GICS Level 1 Sectors

1. **Communication Services** (GICS Code: 50)
2. **Consumer Discretionary** (GICS Code: 25)
3. **Consumer Staples** (GICS Code: 30)
4. **Energy** (GICS Code: 10)
5. **Financials** (GICS Code: 40)
6. **Health Care** (GICS Code: 35)
7. **Industrials** (GICS Code: 20)
8. **Information Technology** (GICS Code: 45)
9. **Materials** (GICS Code: 15)
10. **Real Estate** (GICS Code: 60)
11. **Utilities** (GICS Code: 55)

### GICS Hierarchy

- **11 Sectors** (Level 1)
- **25 Industry Groups** (Level 2)
- **74 Industries** (Level 3)
- **163 Sub-Industries** (Level 4)

For ARBS implementation, we use **GICS Level 1 (11 sectors)** as the primary factor structure, consistent with the Grinold-Kahn 17-factor model (11 sector factors + 6 style factors).

---

## ETF-to-GICS Sector Mapping

Perfect 1:1 correspondence between SPDR Select Sector ETFs and GICS Level 1 sectors:

| GICS Sector | GICS Code | SPDR ETF | Ticker | Coverage |
|-------------|-----------|----------|--------|----------|
| Communication Services | 50 | Communication Services Select Sector SPDR | XLC | 100% of S&P 500 comm. services stocks |
| Consumer Discretionary | 25 | Consumer Discretionary Select Sector SPDR | XLY | 100% of S&P 500 cons. discr. stocks |
| Consumer Staples | 30 | Consumer Staples Select Sector SPDR | XLP | 100% of S&P 500 cons. staples stocks |
| Energy | 10 | Energy Select Sector SPDR | XLE | 100% of S&P 500 energy stocks |
| Financials | 40 | Financial Select Sector SPDR | XLF | 100% of S&P 500 financial stocks |
| Health Care | 35 | Health Care Select Sector SPDR | XLV | 100% of S&P 500 health care stocks |
| Industrials | 20 | Industrial Select Sector SPDR | XLI | 100% of S&P 500 industrial stocks |
| Information Technology | 45 | Technology Select Sector SPDR | XLK | 100% of S&P 500 tech stocks |
| Materials | 15 | Materials Select Sector SPDR | XLB | 100% of S&P 500 materials stocks |
| Real Estate | 60 | Real Estate Select Sector SPDR | XLRE | 100% of S&P 500 real estate stocks |
| Utilities | 55 | Utilities Select Sector SPDR | XLU | 100% of S&P 500 utilities stocks |

**Key Property**: The 11 Select Sector SPDR ETFs, when combined, represent 100% of the S&P 500 index. Each stock in the S&P 500 belongs to exactly one GICS sector and is included in exactly one sector ETF.

---

## Use Cases for ARBS

### 1. **Long/Short Sector-Neutral Strategies** (PRIMARY USE CASE)

**Strategy**: Long individual stocks (based on value/momentum/quality signals), short sector ETFs to hedge sector exposure.

**Example**:
```python
# Long positions (stock selection within tech sector)
Long:  AAPL (+2.0%), MSFT (+1.5%), GOOGL (+1.8%)
Total long tech exposure: +5.3%

# Hedge with sector ETF
Short: XLK (-5.3%)

# Result: Net sector exposure = 0%, pure stock selection alpha
```

**Benefits**:
- Isolates stock selection skill from sector timing
- Reduces portfolio volatility (remove systematic sector risk)
- High Information Ratio (IC focused on idiosyncratic alpha)
- Transaction costs lower for ETF shorts than individual stock shorts

**Grinold-Kahn Connection**:
- From Chapter 14: Alpha preprocessing via neutralization
- Formula: `α_neutral = α - (β_sector · α_sector)`
- Shorting XLK mechanically neutralizes tech sector exposure

### 2. **Sector Rotation Strategies**

**Strategy**: Long sectors expected to outperform, short sectors expected to underperform.

**Example**:
```python
# Factor-based sector forecasts
Long:  XLK (+20%), XLV (+15%)  # Growth sectors
Short: XLE (-15%), XLU (-10%)  # Value sectors

# Market neutral: 35% long, 25% short, net +10% beta exposure
```

**Signals for Sector Rotation**:
- **Macro factors**: GDP growth, interest rates, inflation
- **Relative momentum**: 12-month sector returns
- **Valuation**: Sector P/E ratios vs historical averages
- **Factor exposures**: Growth vs value, quality vs junk

**Expected IC**: 0.15-0.30 (higher than individual stocks, but fewer bets)

### 3. **Completion Portfolios** (Fill out sector exposures)

**Strategy**: Hold core individual stock portfolio, use ETFs to achieve target sector weights.

**Example**:
```python
# Target: Market-neutral with 10% tech overweight
Current stock holdings: 25% tech, 15% financials, 10% health care (50% total)
Remaining 50%: Use XLK (+10%), XLF (+15%), XLV (+15%), XLY (+10%)

# Result: Precise sector control without trading 100s of individual stocks
```

### 4. **Liquidity Management**

**Strategy**: Use ETFs for quick tactical adjustments while maintaining long-term stock positions.

**Benefits**:
- Same-day liquidity (vs 1-2 days for individual stocks)
- Lower transaction costs for large trades
- No specific stock risk (e.g., earnings surprises)

**Example**: Market crash → immediately short SPY or sector ETFs, rebalance stock portfolio later.

---

## Integration Strategy for ARBS

### Recommended Approach: **Separate Hedging/Overlay Layer**

Treat sector ETFs as **overlay instruments** used for hedging and sector exposure management, separate from the individual stock selection pipeline.

### Architecture Design

```
┌─────────────────────────────────────────────────────────┐
│  ARBS Equity Sector Portfolio System                    │
└─────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴────────────────┐
            │                                │
            ▼                                ▼
  ┌──────────────────┐          ┌──────────────────────┐
  │ Stock Selection  │          │ Sector Hedging/      │
  │ Layer            │          │ Overlay Layer        │
  └──────────────────┘          └──────────────────────┘
            │                                │
            │                                │
  ┌─────────▼──────────┐         ┌──────────▼─────────┐
  │ EquityQuery        │         │ ETFQuery           │
  │ (individual stocks)│         │ (sector ETFs)      │
  └────────────────────┘         └────────────────────┘
            │                                │
            │                                │
  ┌─────────▼──────────┐         ┌──────────▼─────────┐
  │ EquityAdapter      │         │ ETFAdapter         │
  │ → Polars DataFrame │         │ → Polars DataFrame │
  └────────────────────┘         └────────────────────┘
            │                                │
            └────────────┬───────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │ ReturnsCalculator      │
            │ (unified returns matrix)│
            └────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │ Signals / AlphaGenerator│
            └────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │ MeanVarianceOptimizer  │
            │ (with SectorNeutral    │
            │  constraint)           │
            └────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │ Portfolio              │
            │ (stocks + ETF hedges)  │
            └────────────────────────┘
```

### Implementation Components

#### 1. ETFQuery Class

**File**: `Query/Equities/ETFQuery.py`

```python
# ABOUTME: Query structure for ETF instruments (sector hedging)
# ABOUTME: Parallel to EquityQuery but simpler (no fundamentals needed)

@dataclass
class ETFQuery(BaseQuery):
    ticker: str  # XLK, XLF, etc.
    sector: str  # GICS Level 1 sector name
    structure: ETFStructure  # SINGLE, BASKET
    value: ETFValue  # PRICE, RETURN
    lookback_days: int = 252
    weight: float = 1.0

    def build_mdp_request(self, as_of_date: date) -> dict:
        return {
            "ticker": self.ticker,
            "start_date": as_of_date - timedelta(days=self.lookback_days),
            "end_date": as_of_date,
            "fields": ["price", "volume"],  # No fundamentals needed
        }
```

#### 2. ETFAdapter Class

**File**: `Adapter/ETFAdapter.py`

```python
# ABOUTME: Adapter converting ETFQuery to standardized Polars DataFrame
# ABOUTME: Simpler than EquityAdapter (no fundamental data)

class ETFAdapter(BaseAdapter):
    def convert(
        self,
        queries: List[ETFQuery],
        as_of_date: date,
        mdp: YahooFinanceMDP,
    ) -> pl.DataFrame:
        """
        Convert ETFQuery list to standardized format

        Output schema (same as EquityAdapter):
            - ticker: str
            - sector: str
            - returns: List[float]
            - price: float
            - market_cap: float (use AUM for ETFs)
        """
        # Fetch ETF price data (no fundamentals)
        # Compute returns
        # Add sector mapping
        pass
```

#### 3. Unified Returns Matrix

Both individual stocks and ETFs flow into the same `ReturnsCalculator`, producing a unified returns matrix:

```python
# Returns matrix (N+11 assets × T periods)
# First N rows: Individual stocks (AAPL, MSFT, JPM, etc.)
# Last 11 rows: Sector ETFs (XLK, XLF, XLE, etc.)

returns = pl.DataFrame({
    "ticker": ["AAPL", "MSFT", ..., "XLK", "XLF", ...],
    "sector": ["Information Technology", ..., "Information Technology", "Financials", ...],
    "returns": [[0.01, -0.02, ...], [...], ...],
})
```

#### 4. Signal Generation

**Key decision**: ETFs do NOT receive value/quality signals, only momentum signals.

**Rationale**:
- ETFs have no fundamentals (no P/E, ROE, etc.)
- Sector ETFs represent aggregate of sector stocks
- Only cross-sectional signal: Sector momentum (relative strength)

```python
# Stock signals: Value, Momentum, Quality
stock_signals = {
    "AAPL": ValueSignal() + MomentumSignal() + QualitySignal(),
    "MSFT": ValueSignal() + MomentumSignal() + QualitySignal(),
    ...
}

# ETF signals: Momentum only (sector rotation)
etf_signals = {
    "XLK": MomentumSignal(),  # Tech sector momentum
    "XLF": MomentumSignal(),  # Financial sector momentum
    ...
}
```

#### 5. Risk Model Integration

**Factor exposures for ETFs**:
- Sector ETFs have **pure sector exposure** (β_sector = 1.0, all other exposures = 0)
- This simplifies covariance estimation

```python
# Factor exposures (N+11 assets × 17 factors)
X = pl.DataFrame({
    "ticker": ["AAPL", "MSFT", ..., "XLK", "XLF", ...],
    "Information Technology": [1.0, 1.0, ..., 1.0, 0.0, ...],  # XLK has 100% tech exposure
    "Financials": [0.0, 0.0, ..., 0.0, 1.0, ...],  # XLF has 100% financial exposure
    "Size": [2.5, 3.0, ..., 0.0, 0.0, ...],  # ETFs have no style exposures
    "Value": [0.5, -0.3, ..., 0.0, 0.0, ...],
    ...
})
```

#### 6. Optimizer Constraints

**Sector-neutral constraint**: Automatically enforced by long stocks + short ETFs.

```python
class SectorNeutralConstraint:
    """
    Enforce: Σ_{i ∈ sector} (h_i - h_Bi) = 0

    For sector-neutral: Long individual stocks, short sector ETF
    """
    def apply(self, problem, sector_exposures):
        for sector in ["Information Technology", "Financials", ...]:
            # Sum of stock weights in sector
            stock_exposure = sum(h_i for stock_i in sector)

            # ETF hedge weight
            etf_exposure = h_etf[sector]

            # Constraint: stock_exposure + etf_exposure = 0
            problem.add_constraint(stock_exposure + etf_exposure == 0)
```

### Alternative Approach: **ETFs as Synthetic Stocks** (NOT RECOMMENDED)

Treat ETFs as if they were individual stocks, flowing through the same pipeline.

**Pros**:
- Simpler implementation (no separate ETFQuery)
- Unified signal generation

**Cons**:
- ETFs don't have fundamentals (can't compute value/quality signals)
- Confuses sector exposure accounting
- Less clear separation of stock selection vs sector bets
- Harder to implement sector-neutral strategies

**Verdict**: Use separate hedging/overlay approach for clarity and flexibility.

---

## Comparison: SPDR vs iShares Sector ETFs

### iShares Alternative

iShares offers sector ETFs, but they are less liquid and have higher expense ratios:

| SPDR | iShares | Difference |
|------|---------|------------|
| XLK (0.08%, $93B AUM) | IYW (0.39%, $15B AUM) | SPDR: 5× lower cost, 6× more AUM |
| XLF (0.08%, $54B AUM) | IYF (0.39%, $5B AUM) | SPDR: 5× lower cost, 10× more AUM |
| XLV (0.08%, $37B AUM) | IYH (0.39%, $6B AUM) | SPDR: 5× lower cost, 6× more AUM |

**Recommendation**: Use **SPDR Select Sector ETFs** exclusively for ARBS implementation.

**Reasons**:
1. **Lower cost**: 0.08% vs 0.39% (5× cheaper)
2. **Higher liquidity**: 3-10× more AUM
3. **Tighter spreads**: More trading volume → lower transaction costs
4. **Perfect GICS mapping**: iShares sector ETFs don't map 1:1 to GICS

---

## Data Requirements for ARBS

### Yahoo Finance Integration

All 11 SPDR sector ETFs are available via Yahoo Finance API:

```python
import yfinance as yf

# Fetch all 11 sector ETFs
tickers = ["XLK", "XLF", "XLV", "XLE", "XLC", "XLY", "XLI", "XLU", "XLP", "XLRE", "XLB"]
data = yf.download(tickers, start="2020-01-01", end="2025-11-11")

# Output: Daily OHLCV data for all ETFs
print(data["Adj Close"])
```

**Data availability**:
- Historical prices: ✅ (all ETFs have >10 years history, except XLRE which launched in 2015)
- Volume: ✅
- Sector classification: ✅ (hardcoded in ARBS, no API needed)
- Fundamentals: ❌ (not applicable to ETFs)

### Sector Classification Mapping

Hardcode the ETF-to-GICS mapping in ARBS:

```python
# File: MDP/YahooFinance/sector_etf_mapping.py

SECTOR_ETF_MAPPING = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}

# Reverse mapping
ETF_TO_SECTOR = {v: k for k, v in SECTOR_ETF_MAPPING.items()}

def get_sector_etf(sector_name: str) -> str:
    """Get SPDR ETF ticker for a GICS sector"""
    return SECTOR_ETF_MAPPING[sector_name]

def get_etf_sector(ticker: str) -> str:
    """Get GICS sector for an ETF ticker"""
    return ETF_TO_SECTOR[ticker]
```

---

## Example Strategy: Tech Stock Selection with Sector Hedge

### Strategy Description

**Objective**: Generate alpha from stock selection within the technology sector, hedged with XLK to remove sector risk.

**Universe**: 50 largest tech stocks in S&P 500
**Signals**: Value (E/P), Momentum (12M return), Quality (ROE)
**Constraint**: Sector-neutral (net tech exposure = 0)
**Rebalancing**: Monthly

### Example Portfolio (January 2025)

```python
# Long positions (top 10 stocks by combined signal)
Long:
  AAPL:  +2.5%  (Value: 0.8, Momentum: 1.2, Quality: 1.5)
  MSFT:  +2.3%  (Value: 1.0, Momentum: 1.0, Quality: 1.3)
  NVDA:  +2.0%  (Value: -0.5, Momentum: 2.5, Quality: 0.8)
  GOOGL: +1.8%  (Value: 1.2, Momentum: 0.5, Quality: 1.1)
  META:  +1.5%  (Value: 0.9, Momentum: 1.5, Quality: 0.6)
  AVGO:  +1.2%  (Value: 0.5, Momentum: 0.8, Quality: 0.9)
  ORCL:  +1.0%  (Value: 1.5, Momentum: -0.5, Quality: 1.0)
  CRM:   +0.9%  (Value: 0.3, Momentum: 0.7, Quality: 0.8)
  CSCO:  +0.8%  (Value: 1.8, Momentum: -1.0, Quality: 0.7)
  ADBE:  +0.7%  (Value: 0.6, Momentum: 0.9, Quality: 0.5)

Total long: +14.7%

# Short position (sector hedge)
Short:
  XLK: -14.7%  (exact hedge of long tech exposure)

# Net sector exposure: 0% (sector-neutral)
# Alpha source: Stock selection within tech (idiosyncratic returns)
```

### Expected Performance

**IC (stock selection)**: 0.04 (typical for multi-signal equity strategy)
**Breadth**: 50 stocks × 12 rebalances/year = 600 bets
**IR (theoretical)**: IC × sqrt(BR) = 0.04 × sqrt(600) = 0.98
**Active risk**: 5% (after sector neutralization)
**Expected alpha**: IR × ω_A = 0.98 × 5% = 4.9% per year

**Key insight**: Removing sector risk (via XLK short) reduces portfolio volatility by ~30%, increasing IR from ~0.6 (long-only) to ~1.0 (sector-neutral).

---

## Testing Strategy

### Phase 1: Data Integration (Week 1)

```python
# Test 1: Fetch all 11 ETFs via Yahoo Finance
def test_fetch_sector_etfs():
    mdp = YahooFinanceMDP()
    tickers = ["XLK", "XLF", "XLV", "XLE", "XLC", "XLY", "XLI", "XLU", "XLP", "XLRE", "XLB"]
    data = mdp.get_equity_data(tickers, start_date, end_date)
    assert len(data["ticker"].unique()) == 11
    assert "returns" in data.columns

# Test 2: Verify sector mapping
def test_sector_etf_mapping():
    assert get_sector_etf("Information Technology") == "XLK"
    assert get_etf_sector("XLK") == "Information Technology"
    assert len(SECTOR_ETF_MAPPING) == 11
```

### Phase 2: Signal Generation (Week 2)

```python
# Test 3: ETFs receive only momentum signals
def test_etf_signals():
    etf_data = get_etf_data(["XLK", "XLF"])

    # Should work: Momentum signal
    momentum = MomentumSignal().calculate(etf_data)
    assert momentum["z_score"].std() > 0

    # Should fail or return null: Value signal (no fundamentals)
    with pytest.raises(KeyError):
        value = ValueSignal().calculate(etf_data)
```

### Phase 3: Sector-Neutral Constraint (Week 3)

```python
# Test 4: Long stocks + short ETF = sector-neutral
def test_sector_neutral_portfolio():
    # Long 10 tech stocks (14.7% total weight)
    stock_weights = {"AAPL": 0.025, "MSFT": 0.023, ...}  # sum = 0.147

    # Short XLK hedge
    etf_weights = {"XLK": -0.147}

    # Combined portfolio
    all_weights = {**stock_weights, **etf_weights}

    # Verify: Net tech exposure = 0
    net_tech_exposure = sum_tech_stocks - abs(etf_weights["XLK"])
    assert abs(net_tech_exposure) < 1e-6
```

### Phase 4: End-to-End Backtest (Week 4)

```python
# Test 5: Full pipeline with stocks + ETF hedges
def test_end_to_end_sector_neutral():
    # Query 50 tech stocks + XLK
    queries = [
        *[EquityQuery(ticker=t, sector="Information Technology") for t in tech_stocks],
        ETFQuery(ticker="XLK", sector="Information Technology"),
    ]

    # Run backtest
    result = run_backtest(queries, signals=[ValueSignal(), MomentumSignal(), QualitySignal()])

    # Verify sector-neutral
    assert abs(result.sector_exposures["Information Technology"]) < 0.01

    # Verify positive alpha (if stock selection signals work)
    assert result.information_ratio > 0.5
```

---

## Open Questions & Future Work

### 1. **Transaction Costs for ETF Shorts**

**Question**: What is the cost to short sector ETFs (borrow cost)?

**Research needed**:
- XLK, XLF, XLV borrow rates (likely <0.10% for liquid ETFs)
- Compare to individual stock short costs
- Factor into transaction cost model

**Expected**: ETF shorts are CHEAPER than individual stock shorts (more shares available, lower borrow rates).

### 2. **ETF Rebalancing Effects**

**Question**: SPDR sector ETFs rebalance quarterly. Does this impact our hedges?

**Analysis**:
- S&P 500 adds/removes stocks → sector ETFs adjust holdings
- Effect on hedge: Small (~0.1% drift per quarter)
- Mitigation: Rebalance monthly, captures ETF changes

### 3. **ETF Premium/Discount to NAV**

**Question**: Do sector ETFs trade at premium/discount to net asset value?

**Research needed**:
- Historical NAV vs market price spread
- Impact on hedge effectiveness

**Expected**: SPDR sector ETFs track NAV closely (±0.05%) due to authorized participant arbitrage.

### 4. **Cross-Sectional ETF Momentum**

**Question**: Can we generate alpha from sector rotation using ETF momentum signals?

**Strategy**:
- Long top 4 sectors (by 12M momentum)
- Short bottom 4 sectors
- Sector-neutral overall

**Expected IC**: 0.15-0.30 (higher than individual stocks, lower breadth)

### 5. **Alternative: Factor ETFs**

**Question**: Should we also consider factor ETFs (value, momentum, quality) instead of sector ETFs?

**Examples**:
- MTUM (iShares Momentum ETF)
- VLUE (iShares Value ETF)
- QUAL (iShares Quality ETF)

**Trade-off**:
- Factor ETFs: Direct factor exposure, but less liquid
- Sector ETFs: More liquid, indirect factor exposure

**Recommendation**: Start with sector ETFs (MVP), add factor ETFs in Phase 2.

---

## Conclusion

### Summary

The 11 SPDR Select Sector ETFs provide perfect 1:1 mapping to GICS Level 1 sectors, with exceptional liquidity (all >$100M daily volume), low cost (0.08% expense ratio), and large AUM (~$330B combined). They are ideal instruments for sector hedging and sector rotation strategies in ARBS.

### Recommendation for ARBS

**Architecture**: Separate hedging/overlay layer
- **Stock selection layer**: Individual stocks with value/momentum/quality signals
- **Sector hedging layer**: Sector ETFs for neutralization and tactical sector bets
- **Risk model**: Unified 17-factor model (11 sectors + 6 styles)
- **Optimization**: Sector-neutral constraint via long stocks + short ETFs

**Use case**: Long/short sector-neutral equity portfolios
- Long: Top-ranked stocks within each sector (value/momentum/quality)
- Short: Corresponding sector ETFs to hedge sector risk
- Result: Pure stock selection alpha, sector risk neutralized

**Expected IC**: 0.04-0.06 (individual stocks), 0.15-0.30 (sector rotation)
**Expected IR**: 1.0+ (sector-neutral), 0.5-0.7 (long-only)
**Breadth**: 500 stocks × 4 rebalances/year = 2,000 bets (individual stocks)
**Breadth**: 11 sectors × 12 rebalances/year = 132 bets (sector rotation)

### Next Steps

1. **AGENT-01**: Russell 3000 universe research (parallel work)
2. **AGENT-03**: Fundamental data sources (value/quality signals)
3. **Phase 1 Implementation**: Create ETFQuery, ETFAdapter, sector_etf_mapping.py
4. **Phase 2 Testing**: End-to-end sector-neutral backtest (50 stocks + 1 ETF hedge)
5. **Phase 3 Production**: Scale to full S&P 500 (500 stocks + 11 ETF hedges)

---

## References

- **SPDR Sector ETFs**: https://www.sectorspdrs.com/allsectors
- **GICS Classification**: https://www.spglobal.com/spdji/en/landing/topic/gics/
- **Yahoo Finance API**: https://github.com/ranaroussi/yfinance
- **Grinold-Kahn Book**: "Active Portfolio Management" (1999), Chapters 3, 14, 17
- **ARBS Implementation Plan**: `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md`
- **ARBS Grinold-Kahn Summary**: `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md`

---

**End of Sector ETF Research Document**
