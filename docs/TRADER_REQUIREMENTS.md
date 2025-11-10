# Quantitative Macro & Interest Rate Trader Requirements

**Purpose**: Practical requirements for backtesting futures and swaps strategies based on industry research.

**Date**: 2025-11-10

**Note**: This document focuses on what traders actually need, not theoretical features.

---

## 1. Core Metrics & Risk

### Essential Metrics (Must Have)

**DV01 (Dollar Value of 01)**
- Change in portfolio value for 1bp rate move
- Critical for daily risk monitoring and position sizing
- Must support: single instrument, portfolio-level, per-tenor breakdown
- Traders need this calculated at multiple levels:
  - Individual position
  - Strategy level (e.g., all steepeners)
  - Total book
  - By maturity bucket (0-2Y, 2-5Y, 5-10Y, 10Y+)

**PV01 / DV01 Distinction**
- PV01: Present value change per bp (used by dealers)
- DV01: Dollar value change per bp (used by traders)
- Implementation: Both should be available, DV01 is primary for trading desks

**Carry & Roll-Down**
- **Carry**: Yield spread to risk-free rate (P&L from time decay)
- **Roll-Down**: Capital gain from rolling down the curve
- **Critical assumption**: Freeze yield curve at inception for backtesting
- Must calculate over different horizons (1D, 1W, 1M, 3M)
- Formula: (Clean Price_t1 + Accrued_t1 + Coupons) - (Clean Price_t0 + Accrued_t0)

**Gamma / Convexity**
- Second-order sensitivity to rate changes
- Important for large positions and risk limits
- Less critical for daily backtesting than for live risk

**NPV / MTM**
- Mark-to-market in dollars
- Daily P&L calculation
- Variation margin for futures (daily settlement)

### Performance Metrics (Standard)

**Sharpe Ratio**
- Risk-adjusted return (return per unit of risk)
- Industry standard for strategy comparison
- Should be calculated over multiple periods (1M, 3M, 6M, 1Y, inception)

**Maximum Drawdown**
- Largest peak-to-trough decline
- Critical for understanding worst-case scenarios
- Need both $ and % drawdown

**Win Rate**
- Percentage of profitable trades
- Less meaningful for macro strategies (few large trades) than high-frequency

**Sortino Ratio** (Optional but useful)
- Like Sharpe but only penalizes downside volatility
- More relevant for asymmetric strategies

---

## 2. Trading Strategies

### Curve Strategies

**Steepeners**
- Long back end, short front end
- Profit when curve steepens (long-short spread widens)
- Implementation: Must be duration-neutral
- Convention: Named by longest leg (buy 2s5s steepener = receive 5Y, pay 2Y)

**Flatteners**
- Short back end, long front end
- Profit when curve flattens
- Common trade: 2s10s, 5s30s

**Butterflies (Fly Trades)**
- Body + two wings
- Example: -1 x 5Y, +2 x 7Y, -1 x 10Y
- Profit from curve curvature changes
- Two slope positions combined: one steepener + one flattener

### SOFR Futures Structures

**Outright Positions**
- Single contract (e.g., SFRZ4)
- Directional rate view

**Calendar Spreads**
- Front vs back contract (e.g., SFRZ4 - SFRH5)
- Express view on front-back relationship
- Used for roll management

**Pack Spreads**
- 4 consecutive quarterly contracts
- Colors: WHITE (0-1Y), RED (1-2Y), GREEN (2-3Y), BLUE (3-4Y), GOLD (4-5Y)
- Trade different blocks of the curve
- Example: Buy RED pack = buy SFRM5, SFRU5, SFRZ5, SFRH6

**Pack vs Pack**
- WHITE-RED, RED-GREEN spreads
- Express curve steepness over 1-year segments

**Bundles**
- 8 consecutive quarterly contracts (2 packs)
- Longer-term positioning

### Basis Strategies

**Futures-Swap Basis**
- Trade difference between futures implied rate and swap rate
- Convexity adjustment: ~1bp per quarter
- Critical calculation: (100 - Avg Futures Price) - Swap Rate
- Must account for pack rounding to tick (typically 0.25bp tick)

**TED Spread** (Historical)
- Treasury vs Eurodollar (now SOFR)
- Credit risk / liquidity premium
- Rising TED = rising counterparty risk

---

## 3. P&L Attribution

### Daily P&L Decomposition (Essential)

Traders need to understand WHERE P&L comes from:

**1. Carry**
- P&L from time decay (theta)
- Accrued interest / coupon income
- Repo funding cost (if applicable)

**2. Roll-Down**
- P&L from rolling down the curve (unchanged curve)
- Depends on curve slope

**3. Rate Changes**
- P&L from parallel shifts
- Directional exposure

**4. Curve Changes**
- Steepening/flattening contribution
- Curvature changes

**5. Spread Changes**
- Basis widening/tightening
- Pack spread moves

**6. Realized P&L**
- From closed positions
- Variation margin received (futures)

**Formula**:
```
Daily P&L = Carry + Roll-Down + Rate_Delta + Curve_Delta + Spread_Delta + Realized
```

### Why This Matters

- Traders need to know if strategy is working as intended
- Carry strategies should make money from carry, not from lucky rate moves
- Risk managers need to verify P&L sources match risk exposures
- Post-mortem analysis of losing trades

---

## 4. Data Requirements

### Pricing Data (EOD Focus)

**SOFR Futures**
- Settlement prices (official CME close)
- Volume and open interest (for liquidity assessment)
- Implied rates (100 - price)
- Pack prices (4-contract average, rounded to tick)

**Interest Rate Swaps**
- Par swap rates at key tenors (1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 30Y)
- SOFR OIS curve
- Basis spreads (if trading cross-currency or -tenor)

**Reference Rates**
- SOFR daily fixings (for forward curve building)
- EFFR (Effective Fed Funds Rate)
- Historical Fed target rate

**Meeting Dates (Critical for Macro)**
- FOMC meeting dates (8 per year)
- Meeting "gap" periods for positioning
- Fed Funds futures probabilities (CME FedWatch)

### Market Microstructure (Lower Priority for Daily Backtester)

- Bid-ask spreads (useful for transaction costs)
- Intraday data (NOT needed for daily backtester)
- Exchange formats (Globex /SR3 vs pit SFR) → NOT NEEDED, just use SFR

---

## 5. Risk Management

### Position Limits

**DV01 Limits**
- Most common limit type for rates desks
- Example: Max $100k DV01 per strategy, $500k total book
- Must aggregate across products (futures + swaps)

**Notional Limits**
- Secondary to DV01 for rates products
- More relevant for credit products

**Concentration Limits**
- Max position in single contract
- Max position in single maturity bucket

### Margin Requirements

**Futures Margin**
- Initial margin: ~3% of contract value (varies by exchange)
- Variation margin: Daily settlement
- Example: SFR contract at 95.00 = 95 × $2,500 × qty
  - Initial margin per contract: ~$2,850
  - Variation margin: Price change × $2,500 × qty

**Swaps Margin** (Post-2020 UMR Rules)
- Initial margin for non-cleared swaps (complex, skip for now)
- Variation margin: Daily exchange
- For cleared swaps: Similar to futures (daily VM)

**Margin Backtesting**
- Track margin calls over time
- Ensure margin coverage >99% of moves
- Critical for sizing: "How much capital do I need to run this strategy?"

### Position Sizing

**Fixed Fractional**
- Risk fixed % of capital per trade (1-2%)
- Common for discretionary traders

**Volatility-Based**
- Scale position inversely with volatility
- More aggressive when markets are calm

**Kelly Criterion** (Advanced)
- Optimal position size = (Win Prob × Avg Win - Loss Prob × Avg Loss) / Avg Loss
- Often too aggressive, use fractional Kelly (e.g., 25% Kelly)

---

## 6. Accounting & Settlement

### Futures Settlement

**Daily Mark-to-Market**
- Variation margin settled daily
- Cash flow = (Price_t1 - Price_t0) × multiplier × quantity
- Compounding effect: Gains are re-invested immediately

**Roll Management**
- Must roll positions before expiry
- Common: Roll 2-3 days before third Wednesday (IMM)
- Roll cost = Calendar spread (front - back)

### Swap Settlement

**Standard Settlement (T+2)**
- Most swaps settle 2 business days after trade
- Upfront payments (if any) on settlement date
- Periodic coupons on schedule

**Daily Reset OIS**
- SOFR OIS compounds daily
- No interim cash flows (only at maturity)

---

## 7. Convexity Adjustments

### Why Needed

Futures settle daily (mark-to-market) while swaps/FRAs settle at maturity. This creates a convexity bias:

- **When rates fall**: Swap gains discounted at lower rates (worth more)
- **When rates rise**: Swap losses discounted at higher rates (cost less)
- **Net effect**: Swaps are worth more than futures equivalent

### Calculation

**Rule of Thumb**: ~1bp per quarter

**Rigorous Approach**:
```
Convexity Adj = (Futures Implied Rate) - (Swap Rate)
```

For pack pricing:
1. Calculate pack average price = average of 4 futures prices
2. Round to tick (0.25bp = 0.0025) if >1 contract
3. Pack implied rate = 100 - pack average price
4. Compare to matched-maturity swap
5. Difference = convexity adjustment

**Typical Range**: 1-5 bps depending on maturity and volatility

### When It Matters

- Futures-swap arbitrage
- Hedging swaps with futures
- Pack spread trading
- Curve construction from futures

---

## 8. Implementation Priorities for ARBS

### Phase 1: Core Infrastructure ✅ DONE
- [x] Test infrastructure (pytest)
- [x] Generic accounting abstractions
- [x] Futures query objects

### Phase 2: Essential Calculations (NEXT)
- [ ] DV01 calculation (futures and swaps)
- [ ] NPV/MTM calculation
- [ ] Carry & roll-down (1D, 1M horizons)
- [ ] Implied rates (100 - price for futures)

### Phase 3: Structure Support (NEXT)
- [ ] Calendar spreads (pricing = front - back)
- [ ] Pack spreads (4-contract average, rounded)
- [ ] Butterfly spreads (curve + fly risk weights)
- [ ] Basis trades (futures vs swap)

### Phase 4: P&L Attribution (LATER)
- [ ] Daily P&L decomposition (carry, roll, rates, curve)
- [ ] Realized vs unrealized P&L
- [ ] Strategy-level aggregation

### Phase 5: Risk Management (LATER)
- [ ] DV01 limits and monitoring
- [ ] Margin calculation (initial + variation)
- [ ] Position sizing rules
- [ ] Drawdown tracking

### Phase 6: Advanced Features (MUCH LATER)
- [ ] Convexity adjustments (pack spreads vs swaps)
- [ ] Transaction costs (bid-ask, exchange fees)
- [ ] Optimal roll timing
- [ ] Kelly position sizing

---

## 9. What NOT to Build

Based on user feedback and daily backtesting focus:

**Don't Build:**
- ❌ Intraday data support (daily EOD is sufficient)
- ❌ Multiple contract format conversions (Globex /SR3 vs pit SFR → just use SFR)
- ❌ Exchange-specific logic (CME vs ICE → treat as fungible)
- ❌ Real-time streaming (backtesting is historical only)
- ❌ Exotic structures (floors, caps, swaptions) until core is solid
- ❌ Over-engineered abstractions that add complexity

**Keep It Simple:**
- Daily EOD backtesting
- One contract format (SFRZ4, not /SR3Z4)
- Clear, focused metrics
- Practical trader workflows

---

## 10. Validation Approach

### Golden Files

Create reference calculations for:
- DV01 of SFRZ4 at price 94.50 → $25 per contract
- Pack average: [94.50, 94.75, 95.00, 95.25] → 94.875 (no rounding for exact)
- Calendar spread: SFRZ4 @ 94.50, SFRH5 @ 94.75 → spread = -0.25 (or -25bp, or -$625)

### Backend Parity

If using multiple pricing engines (QuantLib, RatesLib):
- Test that DV01 matches within tolerance (1% difference OK)
- Test that NPV matches within $1
- Test that carry calculations are consistent

### Trader Validation

Most important: Can a trader understand the output?
- Column names are intuitive
- Units are clear (bps vs dollars vs %)
- P&L sign conventions match market (long futures = profit from price rising)

---

## 11. Recommended Reading

**CME Group Education**
- "Understanding STIR Futures" (includes convexity bias)
- "SOFR Futures and Options Globex Strategy Guide" (pack spreads, calendars)

**Industry Resources**
- Clarus FT blog (mechanics of swaps, spreads, butterflies)
- TraditionData (swap rate butterflies)

**Academic/Practitioner**
- "Fixed Income Securities" by Bruce Tuckman (classic)
- "Interest Rate Markets" by Siddhartha Jha (modern)

---

## 12. Summary: What Traders Actually Need

1. **Fast feedback**: Can I run a backtest in <10 seconds?
2. **Clear metrics**: DV01, carry, Sharpe ratio
3. **Strategy support**: Steepeners, flatteners, flies, packs, calendars
4. **P&L transparency**: Why did I make/lose money?
5. **Risk compliance**: Am I within DV01 limits?
6. **Easy to use**: Intuitive Query API, readable outputs
7. **Trustworthy**: Validated against known results

Everything else is secondary.
