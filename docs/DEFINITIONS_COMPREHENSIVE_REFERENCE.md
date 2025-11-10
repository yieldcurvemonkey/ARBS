# ARBS Product Definitions - Comprehensive Reference Guide

**Version:** 1.0  
**Last Updated:** November 2025  
**Scope:** Complete documentation of IRSwaps curve definitions, Fixed Rate Bond definitions, market conventions, and best practices

---

## Table of Contents

1. [Overview](#overview)
2. [IRSwaps Curve Definitions (9 Curves)](#irswaps-curve-definitions)
3. [Calendar and Day Count Conventions](#calendars-and-day-count-conventions)
4. [Payment Lag and Settlement Conventions](#payment-lag-and-settlement-conventions)
5. [SDR UPI Codes and Mappings](#sdr-upi-codes)
6. [Reference Rate Definitions](#reference-rate-definitions)
7. [FixedRateBonds Definitions](#fixedrratebonds-definitions)
8. [How Definitions Are Used Throughout the System](#how-definitions-are-used)
9. [Adding New Curve Definitions](#adding-new-curve-definitions)
10. [Convention Mapping: QuantLib vs RatesLib](#convention-mappings)
11. [Best Practices for Maintaining Definitions](#best-practices)

---

## Overview

The ARBS system uses **product definitions** to specify the market conventions, settlement terms, and regulatory identifiers for financial instruments. These definitions serve as the single source of truth for:

- **Curve construction** (which calendars, day counters, and settlement days to use)
- **Pricing calculations** (payment frequency, payment lag, business conventions)
- **Regulatory reporting** (SDR UPI codes for cleared swaps)
- **Backend compatibility** (mapping to QuantLib and RatesLib libraries)

**Key Files:**
- `/home/user/ARBS/definitions/IRSwaps.py` - Main curve definitions (9 curves)
- `/home/user/ARBS/definitions/FixedRateBonds.py` - Bond definitions (1 product type)
- `/home/user/ARBS/Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py` - QuantLib mappings
- `/home/user/ARBS/Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py` - RatesLib mappings

---

## IRSwaps Curve Definitions

The system defines **9 interest rate swap curves** across 4 currencies. Each curve specifies:

### USD Curves (3)

#### 1. USD-SOFR-1D (SOFR Overnight Index Swap)

**Primary Use Case:** Fixed-for-floating OIS on the reformed Secured Overnight Financing Rate

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_OIS` | Overnight Indexed Swap (OIS) pricing model |
| **SingleorMultiCurrency** | Single Currency | USD-only (no cross-currency basis) |
| **ReferenceRate** | `USD-SOFR-OIS Compound` | SOFR compounded over fixing period |
| **NotionalCurrency** | USD | Notional in US Dollars |
| **ReferenceRateTermValue** | 1 | Floating leg reset frequency |
| **ReferenceRateTermUnit** | DAYS | Resets daily (O/N) |
| **NotionalSchedule** | Constant | Fixed notional throughout life |
| **DeliveryType** | PHYS | Physical settlement (not cash-settled) |
| **DayCounter** | ACT/360 | Actual/360 day count convention |
| **Calendar** | US Government Bond | US business day calendar |
| **BusinessConvention** | Modified Following | Unadjusted dates then modfollow |
| **Frequency** | Annual | Fixed/floating coupons paid annually |
| **PaymentLag** | 2 | Coupon paid 2 business days in arrears |
| **SettlementDays** | 2 | Trade settles T+2 |
| **SDR_UPIs** | `["QZXQ4R16245X", "QZPB5VSBGRCD"]` | Unique Product Identifiers for Dodd-Frank reporting |

**Market Context:**
- SOFR replaced LIBOR as the primary USD risk-free rate in 2023
- Typical market quotes: 2Y, 3Y, 5Y, 7Y, 10Y, 30Y maturities
- Central bank discount rate (used for Fed reserve management)

---

#### 2. USD-FEDFUNDS (Federal Funds OIS)

**Primary Use Case:** Fixed-for-floating OIS on Federal Funds

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_OIS` | OIS contract |
| **ReferenceRate** | `USD-Federal Funds-H.15-OIS-COMPOUND` | Fed Funds compounded daily |
| **NotionalCurrency** | USD | US Dollars |
| **DayCounter** | ACT/360 | Actual/360 |
| **Calendar** | US Government Bond | US business days |
| **PaymentLag** | 2 | 2 business day settlement |
| **SettlementDays** | 2 | T+2 |
| **SDR_UPIs** | `["QZFF9TXNNM7X", "QZ7HZS5V2LQS"]` | CME and LCH SEF identifiers |

**Market Context:**
- Older OIS standard, primarily used historically
- Fed Funds Effective Rate published by Federal Reserve
- Less liquid than SOFR OIS in current markets

---

#### 3. USD-OIS (Generic US OIS)

**Primary Use Case:** Umbrella definition for US overnight index swaps

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_OIS` | OIS |
| **ReferenceRate** | `USD-Federal Funds-H.15-OIS-COMPOUND` | Fed Funds compounded |
| **NotionalCurrency** | USD | US Dollars |
| **DayCounter** | ACT/360 | Actual/360 |
| **Calendar** | US Government Bond | US business days |
| **PaymentLag** | 2 | 2 business day settlement |
| **SettlementDays** | 2 | T+2 |
| **SDR_UPIs** | `["QZFF9TXNNM7X", "QZ7HZS5V2LQS"]` | Same as FEDFUNDS |

**Note:** USD-OIS and USD-FEDFUNDS share the same reference rate and conventions. Use USD-SOFR-1D for modern SOFR-based trades.

---

### CAD Curves (1)

#### 4. CAD-CORRA (CORRA OIS)

**Primary Use Case:** Fixed-for-floating OIS on Canadian Overnight Rate Average

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_OIS` | OIS contract |
| **SingleorMultiCurrency** | Single Currency | CAD-only |
| **ReferenceRate** | `CAD-CORRA-OIS-COMPOUND` | CORRA compounded overnight |
| **NotionalCurrency** | CAD | Canadian Dollars |
| **ReferenceRateTermValue** | 1 | Daily resets |
| **ReferenceRateTermUnit** | DAYS | O/N frequency |
| **DayCounter** | ACT/365F | Actual/365 Fixed |
| **Calendar** | Toronto | Toronto stock exchange calendar |
| **BusinessConvention** | Modified Following | Standard market convention |
| **Frequency** | Annual | Annual coupons |
| **PaymentLag** | 2 | 2 business day lag |
| **SettlementDays** | 2 | T+2 settlement |
| **SDR_UPIs** | `[]` | No current CORRA identifiers |

**Market Context:**
- CORRA is Bank of Canada's risk-free rate replacement
- Less liquid than USD SOFR or EUR ESTR
- Day count ACT/365F is standard for Canadian rates

---

### EUR Curves (4)

#### 5. EUR-EURIBOR-1M (1-Month EURIBOR)

**Primary Use Case:** Fixed-for-floating IBOR swap on 1-month EURIBOR

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_IBOR` | IBOR (tenored) swap |
| **SingleorMultiCurrency** | Single Currency | EUR-only |
| **ReferenceRate** | `EUR-EURIBOR/EUR-EURIBOR-1M` | 1-month EURIBOR fixing |
| **NotionalCurrency** | EUR | Euros |
| **ReferenceRateTermValue** | 1 | Reset monthly |
| **ReferenceRateTermUnit** | MONTHS | Monthly frequency |
| **DayCounter** | 30E/360 | 30E/360 (ISDA) convention |
| **Calendar** | TARGET | TARGET2 payment system calendar |
| **BusinessConvention** | Modified Following | ISDA standard |
| **Frequency** | Annual | Fixed/floating coupons annual |
| **PaymentLag** | 2 | 2 business day settlement |
| **SettlementDays** | 2 | T+2 |
| **SDR_UPIs** | `[]` | No EURIBOR SDR identifiers |

**Market Context:**
- EURIBOR is published by European Money Markets Institute (EMMI)
- 1M tenor less commonly traded vs 3M/6M
- 30E/360 is standard for EUR fixed income

---

#### 6. EUR-EURIBOR-3M (3-Month EURIBOR)

**Primary Use Case:** Fixed-for-floating IBOR swap on 3-month EURIBOR

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_IBOR` | IBOR swap |
| **ReferenceRate** | `EUR-EURIBOR/EUR-EURIBOR-3M` | 3-month EURIBOR |
| **ReferenceRateTermValue** | 3 | Quarterly reset |
| **ReferenceRateTermUnit** | MONTHS | 3-month tenor |
| **DayCounter** | 30E/360 | 30E/360 |
| **Calendar** | TARGET | TARGET2 calendar |
| **PaymentLag** | 2 | 2 business day settlement |
| **SettlementDays** | 2 | T+2 |

**Market Context:**
- Most liquid EUR IBOR swap tenor
- 3M EURIBOR being phased out (ESTR preferred for discounting)
- Still quoted by dealers for legacy portfolios

---

#### 7. EUR-EURIBOR-6M (6-Month EURIBOR)

**Primary Use Case:** Fixed-for-floating IBOR swap on 6-month EURIBOR

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_IBOR` | IBOR swap |
| **ReferenceRate** | `EUR-EURIBOR/EUR-EURIBOR-6M` | 6-month EURIBOR |
| **ReferenceRateTermValue** | 6 | Semi-annual reset |
| **ReferenceRateTermUnit** | MONTHS | 6-month tenor |
| **DayCounter** | 30E/360 | 30E/360 |
| **Calendar** | TARGET | TARGET2 calendar |
| **PaymentLag** | 2 | 2 business day settlement |
| **SettlementDays** | 2 | T+2 |

**Market Context:**
- Longer-dated EURIBOR index
- Used primarily for structured products and vanilla swaps
- Legacy market; ESTR-based swaps preferred for new trades

---

#### 8. EUR-ESTR (ESTR OIS)

**Primary Use Case:** Fixed-for-floating OIS on Euro Short-Term Rate

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_OIS` | OIS contract |
| **SingleorMultiCurrency** | Single Currency | EUR-only |
| **ReferenceRate** | `EUR-ESTR-OIS-COMPOUND` | ESTR compounded daily |
| **NotionalCurrency** | EUR | Euros |
| **ReferenceRateTermValue** | 1 | Daily reset |
| **ReferenceRateTermUnit** | DAYS | O/N frequency |
| **DayCounter** | ACT/360 | Actual/360 |
| **Calendar** | TARGET | TARGET2 calendar |
| **BusinessConvention** | Modified Following | ISDA standard |
| **Frequency** | Annual | Annual coupons |
| **PaymentLag** | 2 | 2 business day lag |
| **SettlementDays** | 2 | T+2 |
| **SDR_UPIs** | `[]` | No current identifiers |

**Market Context:**
- Replacement for EONIA (replaced June 2019)
- Preferred euro risk-free rate for discounting
- Published by ECB; widely adopted since 2020
- More liquid than EURIBOR OIS

---

### JPY Curves (1)

#### 9. JPY-TONAR (TONAR OIS)

**Primary Use Case:** Fixed-for-floating OIS on Tokyo Overnight Average Rate

| Field | Value | Description |
|-------|-------|-------------|
| **UseCase** | `Fixed_Float_OIS` | OIS contract |
| **SingleorMultiCurrency** | Single Currency | JPY-only |
| **ReferenceRate** | `JPY-TONAR-OIS-COMPOUND` | TONAR compounded daily |
| **NotionalCurrency** | JPY | Japanese Yen |
| **ReferenceRateTermValue** | 1 | Daily reset |
| **ReferenceRateTermUnit** | DAYS | O/N frequency |
| **DayCounter** | ACT/365F | Actual/365 Fixed |
| **Calendar** | Tokyo | Tokyo Stock Exchange calendar |
| **BusinessConvention** | Modified Following | ISDA standard |
| **Frequency** | Annual | Annual coupons |
| **PaymentLag** | 2 | 2 business day settlement |
| **SettlementDays** | 2 | T+2 |
| **SDR_UPIs** | `[]` | No current identifiers |

**Market Context:**
- Japanese risk-free rate; replaces TIBOR
- Published by BOJ via Japan Securities Depository Center
- Less liquid than USD/EUR OIS; widening basis trades common
- ACT/365F follows Japanese market convention

---

## Calendars and Day Count Conventions

### Calendars Used

The system uses **4 business day calendars**:

| Calendar Name | Location | Usage Curves | Description |
|---------------|----------|--------------|-------------|
| `US Government Bond` | USA | USD-SOFR-1D, USD-FEDFUNDS, USD-OIS | US holidays + Fed holidays |
| `TARGET` | Eurozone | EUR-EURIBOR-1M/3M/6M, EUR-ESTR | TARGET2 payment system holidays |
| `Toronto` | Canada | CAD-CORRA | Toronto Stock Exchange holidays |
| `Tokyo` | Japan | JPY-TONAR | Tokyo Stock Exchange holidays |

**How Calendars Work:**
- Used to determine business day adjustments
- When a coupon/settlement date falls on a non-business day, the **BusinessConvention** rule applies
- Affects effective dates, maturity dates, and payment scheduling

---

### Day Count Conventions

Day count conventions determine how interest accrual periods are calculated. Used in 3 conventions:

#### 1. ACT/360 (Actual/360)

**Used by:** USD-SOFR-1D, USD-FEDFUNDS, USD-OIS, EUR-ESTR

**Formula:** 
```
Accrual Days = Actual calendar days in period
Year Basis = 360 days
Accrued Interest = Coupon Rate × (Accrual Days / 360)
```

**Market Context:**
- Standard for US money markets and USD LIBOR/SOFR products
- Used for Federal Funds, SOFR, and ESTR (overnight rates)
- Slightly increases effective yield vs ACT/365F

**Example:**
- Period: Feb 15 - Mar 15 (Non-leap year)
- Days: 28 days
- Accrual: Coupon × (28/360) = Coupon × 0.07778

---

#### 2. ACT/365F (Actual/365 Fixed)

**Used by:** CAD-CORRA, JPY-TONAR

**Formula:**
```
Accrued Interest = Coupon Rate × (Accrual Days / 365)
```

**Market Context:**
- Standard in Canadian and Japanese markets
- Called "365F" because denominator is always 365 (not 366 in leap years)
- More conservative than ACT/360

**Example:**
- Same period: Feb 15 - Mar 15
- Days: 28 days
- Accrual: Coupon × (28/365) = Coupon × 0.07671

---

#### 3. 30E/360 (ISDA 30/360)

**Used by:** EUR-EURIBOR-1M, EUR-EURIBOR-3M, EUR-EURIBOR-6M

**Formula:**
```
Months = Ending Month - Starting Month
Days = (D2 - D1) if D2 >= 30, else (30 - D1) + 30 + (30 - D2)
      where D1 = Starting day (capped at 30)
      where D2 = Ending day (capped at 30)
Accrued Interest = Coupon Rate × (Days / 360)
```

**Market Context:**
- Standard European convention for IBOR-linked products
- Adjusts day counts: months have 30 days; Feb treated as 30-day month
- Conservative yield vs actual/360

**Example:**
- Feb 15 - Mar 31 (uses day 30 for both Feb and Mar)
- D1 = 15 (Feb), D2 = 30 (Mar)
- Days = 30 - 15 + 30 + 30 - 30 = 45 (vs. actual 44)

---

#### 4. ACT/ACT ISMA (Actual/Actual ISMA)

**Used by:** USTS (Fixed Rate Bonds)

**Formula:**
```
For each coupon period:
  Accrued = Days in Period / Days in Full Period × Coupon
```

**Market Context:**
- Standard for US Treasury bonds and corporate bonds
- Each period calculated separately based on actual days
- Matches accrual methodology for bonds vs swaps

---

### Day Count Summary Table

| Convention | Denominator | Leap Year | Market | Usage |
|-----------|-------------|-----------|--------|-------|
| ACT/360 | 360 | Actual | USD Money Markets | OIS (SOFR, FEDFUNDS) |
| ACT/365F | 365 | Always 365 | Canada, Japan | CORRA, TONAR |
| 30E/360 | 360 | Normalized | Eurozone | EURIBOR (legacy IBOR) |
| ACT/ACT ISMA | Variable | Actual | Bonds | US Treasuries |

---

## Payment Lag and Settlement Conventions

### Settlement Days (T+n)

**SettlementDays** specifies how many business days after trade date (T) the swap settles:

| Curve | Settlement | Meaning | Calendar Basis |
|-------|-----------|---------|-----------------|
| All USD curves | T+2 | 2 business days | US Government Bond |
| EUR curves | T+2 | 2 business days | TARGET2 |
| CAD-CORRA | T+2 | 2 business days | Toronto |
| JPY-TONAR | T+2 | 2 business days | Tokyo |

**Market Convention:**
- T+0 or T+1 settlements very rare (requires special authorization)
- T+2 is ISDA standard for OTC derivatives since 2015
- Some exchange-traded products settle T+1

**How it's used:**
```python
# In ARBS: calendar_advance(trade_date, settlement_days)
settlement_date = calendar.advance(trade_date, 2, ql.Days, BusinessConvention)
```

---

### Payment Lag (Arrears Settlement)

**PaymentLag** specifies how many business days after an accrual period ends that the coupon is paid:

| Field | Value | Meaning |
|-------|-------|---------|
| PaymentLag | 2 | Coupons paid 2 business days **after** accrual end date |

**Example Timeline (USD-SOFR-1D, Annual Frequency):**
```
Accrual Start: Jan 15, 2025
Accrual End:   Jan 15, 2026
Coupon Paid:   Jan 17, 2026 (Jan 15 + 2 business days)
```

**Market Convention:**
- 0 lag = Advanced/upfront coupon payment (rare)
- 1-2 lag = Standard for OTC swaps (arrears settlement)
- 3+ lag = Unusual; indicates specific trade terms

**Use in Pricing:**
```python
# Payment date = accrual_end + payment_lag business days
# Used to discount cash flows back to trade date
```

---

### Business Day Convention

All curves use **Modified Following** convention for date adjustments:

**Definition:**
1. Start with calculated date (e.g., coupon date)
2. If date is a business day → use it as-is
3. If date is non-business day → move **forward** to next business day
4. **Exception:** If moving forward changes the month, move **backward** to previous business day instead

**Example (USD-SOFR-1D, Jan 15 coupons):**
```
Calculated Date: Jan 15, 2025 (Wednesday) → Business day → Use Jan 15
Calculated Date: Jan 17, 2025 (Friday)    → Business day → Use Jan 17
Calculated Date: Jan 18, 2025 (Saturday)  → Non-business → Jan 21 (following Mon)
Calculated Date: Feb 1, 2025 (Saturday)   → Non-business → Jan 31 (back to Fri in Jan)
```

---

### Payment Frequency

All curves specify **Annual** payment frequency:

| Field | Value | Meaning |
|-------|-------|---------|
| Frequency | Annual | Coupons paid once per year |

**Implementation:**
- Fixed leg receives/pays 1 coupon per year
- Floating leg resets daily (O/N) but coupons still paid annually
- Accrual period = 1 year (12 months or 365/360 days)

**Exceptions:**
- EURIBOR curves: Could theoretically support 3M/6M payments (but defined as Annual)
- Future curves: Could add quarterly or semi-annual variants

---

## SDR UPI Codes

### What is an SDR UPI?

**SDR UPI** = **Unique Product Identifier** used for Dodd-Frank regulatory reporting

- 12-character alphanumeric code
- Assigned by International Derivatives Clearing Houses Organization (IDCHDO)
- Required for all cleared swap products in US (SEC/CFTC mandate)
- Links swap trades to a standardized product definition

### Current SDR UPI Mappings

Only USD curves have assigned UPIs. European and Asian curves are not yet standardized:

#### USD-SOFR-1D

| UPI | Issuer | Product Type | Notes |
|-----|--------|--------------|-------|
| `QZXQ4R16245X` | CME Clearing | SOFR 1D OIS Swap | Primary CME identifier |
| `QZPB5VSBGRCD` | LCH Ltd | SOFR 1D OIS Swap | Alternative LCH identifier |

**Market Impact:**
- Traders use both codes depending on clearing house
- CME dominant in US; LCH dominant in Europe
- Essential for post-trade UTI (Unique Trade Identifier) reporting

---

#### USD-FEDFUNDS & USD-OIS

| UPI | Issuer | Product Type | Notes |
|-----|--------|--------------|-------|
| `QZFF9TXNNM7X` | CME Clearing | Fed Funds OIS Swap | CME Code |
| `QZ7HZS5V2LQS` | LCH Ltd | Fed Funds OIS Swap | LCH Code |

**Market Context:**
- Legacy Fed Funds OIS less traded now
- SOFR OIS preferred for new trades
- UPIs remain active for risk management of old books

---

#### EUR/CAD/JPY Curves

| Currency | Curve | UPI | Status |
|----------|-------|-----|--------|
| EUR | EURIBOR-1M/3M/6M | None | Not cleared; bilateral OTC only |
| EUR | ESTR | None | ESTR OIS clearing not yet standardized |
| CAD | CORRA | None | Canadian derivatives less regulated |
| JPY | TONAR | None | Japanese clearing house uses different scheme |

**Future Outlook:**
- Expect UPI assignment for EUR/ESTR as clearing becomes standard
- CORRA and TONAR likely to remain bilateral

---

## Reference Rate Definitions

### Overview

Reference rates are the **underlying floating rate indices** on which swaps are priced. Each curve definition maps to one or more reference rates:

```
Curve Name → UseCase → ReferenceRate → Index Type
  ↓              ↓           ↓             ↓
USD-SOFR-1D → OIS → SOFR Compound → Overnight Indexed
EUR-EURIBOR-3M → IBOR → EURIBOR 3M → Tenored IBOR
```

---

### Reference Rate Types

#### 1. Overnight Indexed Rates (OIS)

Compound daily overnight rates over an accrual period:

**Curves:**
- USD-SOFR-1D: `USD-SOFR-OIS Compound / USD-SOFR-COMPOUND`
- USD-FEDFUNDS: `USD-Federal Funds-H.15-OIS-COMPOUND / USD-Federal Funds-OIS Compound`
- CAD-CORRA: `CAD-CORRA-OIS-COMPOUND / CAD-CORRA-COMPOUND`
- EUR-ESTR: `EUR-ESTR-OIS-COMPOUND / EUR-ESTR`
- JPY-TONAR: `JPY-TONAR-OIS-COMPOUND / JPY-TONAR`

**How OIS Compounding Works:**
```
Period: Jan 15 - Jan 16 (assume working day)
Daily O/N rate published by central bank: 5.00%

Compounded Rate = (1 + r1/360) × (1 + r2/360) × ... - 1

For annual period with compounding:
Coupon = Notional × Compounded Rate
```

**Characteristics:**
- No credit risk (collateralized; backed by central banks)
- Most liquid overnight funding rate
- Used for risk-free discounting in modern finance

---

#### 2. IBOR (Interbank Offered Rate)

Tenored fixings published at regular intervals:

**Curves:**
- EUR-EURIBOR-1M: `EUR-EURIBOR / EUR-EURIBOR-1M`
- EUR-EURIBOR-3M: `EUR-EURIBOR / EUR-EURIBOR-3M`
- EUR-EURIBOR-6M: `EUR-EURIBOR / EUR-EURIBOR-6M`

**How IBOR Works:**
```
Fixing Date: Jan 15 (Business Day)
EURIBOR 3M published at 10:45 AM Brussels time

Accrual Period: Jan 15 - Apr 15
Coupon = Notional × (EURIBOR-3M Rate + Basis Spread)

New fix published every business day for each tenor.
Traders quote "EURIBOR-3M + 15 bps" meaning +0.15%
```

**Characteristics:**
- Includes credit component (interbank lending risk)
- Legacy rate; being phased out in favor of RFRs
- Basis spreads: EURIBOR vs ESTR (credit risk premium)

**Tenors:**
- 1M EURIBOR: Used for short-term hedging
- 3M EURIBOR: Most actively traded; benchmark tenor
- 6M EURIBOR: Longer-dated legacy products

---

### SOFR (Secured Overnight Financing Rate) - Detailed

**Currency:** USD  
**Publisher:** Federal Reserve Bank of New York  
**Frequency:** Daily business day fixing  

**Definition:**
```
SOFR = Volume-weighted median rate of bilateral overnight 
       secured funding transactions in the US Treasury 
       repo market (published by Federal Reserve)
```

**Key Features:**
- Replaced LIBOR on June 17, 2023
- Based on actual market transactions (not survey-based)
- Includes haircuts and collateral considerations
- Published 8:00 AM ET (revised at 4:00 PM)

**Historical Background:**
- LIBOR was "statistically fabricated" by banks (Barclays scandal 2012)
- SOFR is transaction-based, reducing manipulation risk
- Adopted after LIBOR rate-fixing scandal

**Compounding Methods:**
```
Simple Compounding:
Rate = [∏(1 + rᵢ/360) - 1] × 360/d

Arithmetic Average:
Rate = (1/d) × Σ rᵢ

d = number of days in accrual period
rᵢ = SOFR fixing on day i
```

---

### EURIBOR (Euro Interbank Offered Rate) - Detailed

**Currency:** EUR  
**Publisher:** European Money Markets Institute (EMMI)  
**Frequency:** Daily business day fixing  

**Definition:**
```
EURIBOR = Average rate at which eurozone banks 
          lend unsecured funds to each other
```

**Tenors:**
- 1W, 2W (rare)
- 1M, 3M, 6M, 12M (most quoted)

**Characteristics:**
- Survey-based (20+ major banks report rates)
- Includes credit spread (bank counterparty risk)
- Basis between tenors varies with market conditions

**Example:**
```
Day 1: EURIBOR-3M = 4.25%
Day 2: EURIBOR-3M = 4.26%
Day 3: EURIBOR-3M = 4.24%

Compounded 3-month coupon uses daily fixings.
Fixed leg priced vs. 3M EURIBOR + agreed spread.
```

**Transition to ESTR:**
- ECB published ESTR since Oct 2019 as EURIBOR replacement
- Interbank cash market shrinking (banks prefer secured funding)
- Legacy EURIBOR swaps still actively traded; new deals use ESTR

---

### CORRA (Canadian Overnight Repo Rate Average)

**Currency:** CAD  
**Publisher:** Bank of Canada  
**Frequency:** Daily business day fixing  

**Definition:**
```
CORRA = Volume-weighted average repo rate in the 
        Canadian Government Securities Repo market
```

**Characteristics:**
- Transaction-based (similar to SOFR)
- Replaced CDOR (Canadian Dealer Offer Rate) for discounting
- Less liquid than SOFR (smaller market)
- Compounded daily for swap coupons

**Market Impact:**
- Canadian market smaller; basis trades with SOFR common
- USD/CAD cross-currency swaps important for hedging

---

### TONAR (Tokyo Overnight Average Rate)

**Currency:** JPY  
**Publisher:** BOJ (Bank of Japan) via JSDC  
**Frequency:** Daily business day fixing  

**Definition:**
```
TONAR = Volume-weighted average overnight 
        unsecured lending rate in Tokyo  
        interbank market
```

**Characteristics:**
- Successor to TIBOR (Yen LIBOR equivalent)
- Least liquid of major RFRs
- Often exhibits wide bid-ask spreads
- Basis trades with USD/JPY FX market

---

## FixedRateBonds Definitions

### USTS (US Treasury Securities)

Only **one bond definition** is currently defined:

| Field | Value | Description |
|-------|-------|-------------|
| **ProductName** | USTS | Generic identifier for US Treasuries |
| **NotionalCurrency** | USD | US Dollars |
| **DayCounter** | ACT/ACT ISMA | Actual/Actual ISMA convention |
| **Calendar** | US Government Bond | US business days |
| **BusinessConvention** | Modified Following | Standard date adjustment |
| **Frequency** | Semiannual | Coupons paid twice yearly |
| **SettlementDays** | 1 | T+1 settlement (faster than swaps) |
| **Redemption** | 100 | Par value at maturity |
| **Compounded** | True | Interest accrues daily; coupon pays semiannually |

### USTS Characteristics

**Payment Schedule:**
- Treasury coupons paid on the 15th of coupon months
- For example, 5-year bond: Jan 15 and Jul 15 each year
- If coupon date is non-business day: Modified Following adjustment

**Day Count:**
```
For each 6-month period:
Accrued Interest = Coupon × (Days in Period / Days in Full Period)

Example: Bond with 4% annual coupon
Period: Jan 15 - Jul 15, 2025
If Feb 29 (leap year): 181 actual days / 184 days in full period
Accrued = 2.0% × (Days Since Jan 15 / 181)
```

**Settlement:**
- T+1 settlement (faster than OTC swaps)
- Prices quoted as yield-to-maturity (YTM)
- Accrued interest added to clean price for dirty price

**Regulatory Context:**
- US Treasuries are the deepest, most liquid fixed income market
- Used as benchmark for risk-free discounting
- No credit risk (backed by US government)

---

## How Definitions Are Used Throughout the System

### Architecture Overview

Definitions flow through the ARBS system in this path:

```
definitions/
  ├─ IRSwaps.py (Generic Definitions)
  └─ FixedRateBonds.py
         ↓
Query/
  ├─ IRSwaps/
  │   ├─ backends/
  │   │   ├─ quantlib/
  │   │   │   └─ ql_curve_definitions_map.py (QuantLib Mappings)
  │   │   └─ rateslib/
  │   │       └─ rl_curve_definitions_map.py (RatesLib Mappings)
  │   ├─ QLIRSwapCurve.py (QL Curve Implementation)
  │   └─ RLIRSwapCurve.py (RL Curve Implementation)
  └─ FixedRateBonds/
      └─ backends/
          ├─ quantlib/ql_frb_definitions_map.py
          └─ rateslib/rl_frb_definitions_map.py
         ↓
MDP/ (Market Data Provider)
  └─ Constructs curves using definitions + market data
         ↓
Pricing Engine (QL or RL)
  └─ Builds swaps, calculates values, uses conventions
```

---

### 1. Curve Construction

When the MDP (Market Data Provider) builds a yield curve:

**Step 1: Fetch definition**
```python
# MDP code
curve_id = "USD-SOFR-1D"
definition = CURVE_DEFINITIONS[curve_id]

# Extract conventions
calendar = definition["Calendar"]           # "US Government Bond"
day_counter = definition["DayCounter"]     # "ACT/360"
settlement_days = definition["SettlementDays"]  # 2
```

**Step 2: Map to backend**
```python
# QL backend
ql_calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
ql_daycounter = ql.Actual360()
settlement_date = calendar.advance(today, settlement_days, ql.Days)
```

**Step 3: Build swap helpers**
```python
# From market data (CME, SDR, etc.)
market_data = {
    "2Y": 5.125,
    "5Y": 4.875,
    "10Y": 4.625
}

for tenor, rate in market_data.items():
    helper = ql.SwapRateHelper(
        rate=ql.QuoteHandle(ql.SimpleQuote(rate/100)),
        tenor=ql.Period(tenor),
        settlementDays=definition["SettlementDays"],
        calendar=ql_calendar,
        fixedLegFrequency=ql.Annual,
        fixedLegConvention=ql.ModifiedFollowing,
        fixedLegDayCount=ql_daycounter,
        iborIndex=ql.Sofr()
    )
    helpers.append(helper)
```

**Step 4: Build yield curve**
```python
# Use piecewise log-linear discount factor curve
curve = ql.PiecewiseLogLinearDiscount(
    settlement_days,
    ql_calendar,
    helpers,
    ql_daycounter
)
```

---

### 2. Swap Pricing

When pricing an interest rate swap:

**Step 1: Build swap object**
```python
# From ql_pricer.py
definition = QUANTLIB_CURVE_DEFINITIONS["USD-SOFR-1D"]

swap = ql.MakeOIS(
    fwdStart=ql.Period("2D"),           # Forward start (2D settlement)
    swapTenor=ql.Period("5Y"),          # 5-year maturity
    fixedRate=0.04,                     # 4% fixed coupon
    overnightIndex=ql.Sofr(),           # SOFR index
    settlementDays=definition["SettlementDays"],  # T+2
    calendar=definition["Calendar"],    # US holidays
    paymentCalendar=definition["Calendar"],
    fixedLegDayCount=definition["DayCounter"],  # ACT/360
    fixedLegConvention=definition["BusinessConvention"],  # ModFollowing
    paymentFrequency=definition["PaymentFrequency"],  # Annual
    paymentLag=definition["PaymentLag"],  # 2 days arrears
    nominal=1_000_000,
    receiveFixed=True,
    endOfMonth=False
)
```

**Step 2: Price swap**
```python
# Apply pricing engine
swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))

# Calculate metrics using definitions
fair_rate = swap.fairRate()  # Uses all conventions
npv = swap.NPV()             # Discounts using curve + conventions
pv01 = swap.legBPS(0, 1)     # Basis point value
```

---

### 3. Settlement Date Calculation

Settlement dates are calculated using calendar + settlement days:

```python
# In RLIRSwapCurve.py
trade_date = datetime(2025, 1, 13)  # Monday

# Lookup definition
defn = RATESLIB_CURVE_DEFINITIONS["USD-SOFR-1D"]
settlement_days = defn["SettlementDays"]  # 2
calendar = defn["Calendar"]               # "nyc"

# Advance trade date by 2 business days
settlement_date = rl.add_tenor(
    trade_date,
    tenor=f"{settlement_days}b",  # "2b" = 2 business days
    modifier=defn["BusinessConvention"],
    calendar=calendar
)
# Result: Jan 15, 2025 (skips weekend if needed)
```

---

### 4. Day Count Accrual

When calculating accrued interest:

```python
# For ACT/360 (USD OIS)
accrual_start = datetime(2025, 1, 15)
accrual_end = datetime(2026, 1, 15)
annual_coupon = 0.04  # 4%

day_counter = ql.Actual360()
days = day_counter.dayCount(accrual_start, accrual_end)
accrual_rate = days / 360.0
coupon_paid = 1_000_000 * annual_coupon * accrual_rate

# For 365 actual days: 1_000_000 × 0.04 × (365/360) = 40,555.56
```

```python
# For 30E/360 (EUR EURIBOR)
day_counter = ql.Thirty360(ql.Thirty360.EuropeanBondBasis)
days = day_counter.dayCount(accrual_start, accrual_end)
# Normalizes to exactly 360 days for annual coupon
```

---

## Adding New Curve Definitions

### Step-by-Step Process

To add a new curve to the system (e.g., GBP SONIA):

#### Step 1: Add to Main Definitions

**File:** `/home/user/ARBS/definitions/IRSwaps.py`

```python
CURVE_DEFINITIONS = {
    # ... existing curves ...
    
    "GBP-SONIA": {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": "GBP-SONIA-OIS-COMPOUND/GBP-SONIA",
        "NotionalCurrency": "GBP",
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": "DAYS",
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": "ACT/365F",  # Standard for GBP
        "Calendar": "London Stock Exchange",  # London holidays
        "BusinessConvention": "Modified Following",
        "Frequency": "Annual",
        "PaymentLag": 1,  # GBP sometimes T+1
        "SettlementDays": 0,  # SONIA settlements same-day
        "SDR_UPIs": ["QZXXXXX"],  # Assign if available
    },
}
```

---

#### Step 2: Add QuantLib Mapping

**File:** `/home/user/ARBS/Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py`

```python
QUANTLIB_CURVE_DEFINITIONS: Dict[str, Dict] = {
    # ... existing curves ...
    
    "GBP-SONIA": {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": ql.Sonia,  # QuantLib's SONIA index
        "NotionalCurrency": ql.GBPCurrency(),
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": ql.Days,
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": ql.Actual365Fixed(),  # ACT/365F
        "Calendar": ql.UnitedKingdom(ql.UnitedKingdom.Exchange),  # LSE
        "BusinessConvention": ql.ModifiedFollowing,
        "PaymentFrequency": ql.Annual,
        "PaymentLag": 1,
        "SettlementDays": 0,
        "SDR_UPIs": ["QZXXXXX"],
    },
}

# Verify the mapping
for k in QUANTLIB_CURVE_DEFINITIONS.keys():
    assert k in CURVE_DEFINITIONS, f"Missing {k} in base definitions"
```

---

#### Step 3: Add RatesLib Mapping

**File:** `/home/user/ARBS/Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py`

```python
RATESLIB_CURVE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    # ... existing curves ...
    
    "GBP-SONIA": {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": "gbp_irs",  # RatesLib's GBP IRS spec
        "ReferenceRate2": "gbp_stir",  # For futures
        "ReferenceRate3": "gbp_stir1",  # For 1-month futures
        "NotionalCurrency": "gbp",
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": "days",
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": "act365f",  # RatesLib notation
        "Calendar": "lse",  # London Stock Exchange
        "BusinessConvention": "mf",  # RatesLib notation
        "PaymentFrequency": "1y",
        "PaymentLag": 1,
        "SettlementDays": 0,
        "SDR_UPIs": ["QZXXXXX"],
    },
}

# Verify
for k in RATESLIB_CURVE_DEFINITIONS.keys():
    assert k in CURVE_DEFINITIONS
```

---

#### Step 4: Add MDP Support

**File:** `/home/user/ARBS/MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/CMEFetcher.py`

Add curve to the list of curves fetched from market data:

```python
SUPPORTED_CURVES = {
    "USD-SOFR-1D": {...},
    "CAD-CORRA": {...},
    "EUR-ESTR": {...},
    "JPY-TONAR": {...},
    "GBP-SONIA": {  # Add this
        "source": "LIFFE",  # Ice Futures Europe
        "tenor_map": {
            "2Y": "SONIA2Y",
            "5Y": "SONIA5Y",
            # ... etc
        }
    }
}
```

---

#### Step 5: Validation Tests

Create tests to verify the new definition:

```python
# test_gbp_sonia.py

def test_gbp_sonia_definition():
    """Verify GBP-SONIA is properly defined."""
    from definitions.IRSwaps import CURVE_DEFINITIONS
    assert "GBP-SONIA" in CURVE_DEFINITIONS
    
    defn = CURVE_DEFINITIONS["GBP-SONIA"]
    assert defn["NotionalCurrency"] == "GBP"
    assert defn["DayCounter"] == "ACT/365F"
    assert defn["SettlementDays"] == 0
    
def test_gbp_sonia_quantlib_mapping():
    """Verify QuantLib mapping exists."""
    from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
    assert "GBP-SONIA" in QUANTLIB_CURVE_DEFINITIONS
    
    ql_defn = QUANTLIB_CURVE_DEFINITIONS["GBP-SONIA"]
    import QuantLib as ql
    assert isinstance(ql_defn["DayCounter"], ql.DayCounter)
    assert isinstance(ql_defn["Calendar"], ql.Calendar)

def test_gbp_sonia_rateslib_mapping():
    """Verify RatesLib mapping exists."""
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
    assert "GBP-SONIA" in RATESLIB_CURVE_DEFINITIONS
```

---

### Checklist for Adding New Curves

- [ ] Add entry to `CURVE_DEFINITIONS` in `definitions/IRSwaps.py`
- [ ] Add QuantLib mapping to `ql_curve_definitions_map.py`
- [ ] Add RatesLib mapping to `rl_curve_definitions_map.py`
- [ ] Update MDP to support the curve (if available from market data source)
- [ ] Add SDR UPI codes if applicable
- [ ] Test curve construction with sample market data
- [ ] Test swap pricing (NPV, PV01, fair rate)
- [ ] Update documentation
- [ ] Add unit tests to regression suite

---

## Convention Mappings: QuantLib vs RatesLib

The system supports two pricing backends. Definitions must map cleanly to both.

### Key Mapping Differences

| Concept | Base Definition | QuantLib | RatesLib | Notes |
|---------|-----------------|----------|----------|-------|
| **Calendar** | String name | `ql.Calendar` object | String code | QL requires instantiation |
| **DayCounter** | String notation | `ql.DayCounter` object | String code | RL uses shorthand |
| **Currency** | 3-letter code | `ql.Currency()` object | String code | "GBP" → ql.GBPCurrency() |
| **Business Convention** | String | `ql.BusinessDayConvention` enum | String code | "Modified Following" → "mf" |
| **Settlement Days** | Integer | `ql.Days` enum | String tenor | 2 → "2b" in RatesLib |

---

### Calendar Mapping

| Base Definition | QuantLib | RatesLib | Implementation |
|---|---|---|---|
| US Government Bond | `ql.UnitedStates(ql.UnitedStates.GovernmentBond)` | `"nyc"` | US Fed holidays + NYSE |
| TARGET | `ql.TARGET()` | `"tgt"` | Eurozone T2 holidays |
| Toronto | `ql.Canada(ql.Canada.TSX)` | `"toronto"` | TSX holidays |
| Tokyo | `ql.Japan()` | `"tyo"` | Tokyo SE holidays |
| London Stock Exchange | `ql.UnitedKingdom(ql.UnitedKingdom.Exchange)` | `"lse"` | LSE holidays |

---

### Day Count Mapping

| Base Definition | QuantLib | RatesLib | Formula |
|---|---|---|---|
| ACT/360 | `ql.Actual360()` | `"act360"` | Days / 360 |
| ACT/365F | `ql.Actual365Fixed()` | `"act365f"` | Days / 365 |
| 30E/360 | `ql.Thirty360(ql.Thirty360.EuropeanBondBasis)` | `"30e360"` | Normalized days / 360 |
| ACT/ACT ISMA | `ql.ActualActual(ql.ActualActual.ISMA)` | `"actact_isda"` | Period-dependent |

---

### Reference Rate Mapping

When building swap indices, map to backend implementations:

```python
# Base Definition (generic)
"ReferenceRate": "USD-SOFR-OIS Compound/USD-SOFR-COMPOUND"

# QuantLib Mapping
"ReferenceRate": ql.Sofr

# RatesLib Mapping
"ReferenceRate": "usd_irs"  # Built-in spec
```

**How RatesLib Works:**
```python
# RatesLib uses predefined "specs" for common products
import rateslib as rl

# Spec defines curve, fixing, conventions all together
usd_irs = rl.CurveSpec(
    curve="usd_irs",  # Curve identifier
    index="sofr",     # Underlying index
    ...               # All conventions built-in
)
```

---

### Business Convention Mapping

| Base Definition | QuantLib | RatesLib |
|---|---|---|
| Modified Following | `ql.ModifiedFollowing` | `"mf"` |
| Following | `ql.Following` | `"f"` |
| Preceding | `ql.Preceding` | `"p"` |
| Unadjusted | `ql.Unadjusted` | `"u"` |

**Usage in Swap Building:**

```python
# QuantLib
swap = ql.MakeVanillaSwap(
    fixedLegConvention=ql.ModifiedFollowing,  # Enum value
    ...
)

# RatesLib (built into spec)
swap = rl.IRS(
    spec="usd_irs",  # Convention already embedded
    ...
)
```

---

### Payment Frequency Mapping

| Base Definition | QuantLib | RatesLib |
|---|---|---|
| Annual | `ql.Annual` | `"1y"` |
| Semiannual | `ql.Semiannual` | `"6m"` |
| Quarterly | `ql.Quarterly` | `"3m"` |
| Monthly | `ql.Monthly` | `"1m"` |

---

## Best Practices for Maintaining Definitions

### 1. Consistency Between Backends

**Rule:** If a definition exists, it must be mappable to both QuantLib AND RatesLib.

**How to enforce:**
```python
# In both ql_curve_definitions_map.py and rl_curve_definitions_map.py

for k in QUANTLIB_CURVE_DEFINITIONS.keys():
    assert k in CURVE_DEFINITIONS, f"QL def {k} missing from base"

for k in RATESLIB_CURVE_DEFINITIONS.keys():
    assert k in CURVE_DEFINITIONS, f"RL def {k} missing from base"
```

**Current Status:**
- QuantLib: USD curves only (3 curves)
- RatesLib: 5 curves (USD, CAD, EUR-ESTR, JPY)
- EUR-EURIBOR curves: NOT YET MAPPED to RatesLib

**Action Items:**
- [ ] Add RL mappings for EUR-EURIBOR curves
- [ ] Add QL mappings for CAD-CORRA and JPY-TONAR

---

### 2. Documentation Standards

Each new definition should include:

**In Docstring:**
```python
"GBP-SONIA": {
    # GBP Sterling Overnight Index Average (SONIA)
    #
    # Specifications:
    #   - Use Case: OIS (Overnight Indexed Swap)
    #   - Underlying: Bank of England SONIA rate
    #   - Compounding: Daily
    #   - Settlement: T+0 (same-day settlement; fastest of all major RFRs)
    #
    # Market Context:
    #   - Replaced LIBOR on Jan 1, 2022
    #   - Widely used for GBP hedging; LSE-listed products
    #   - Narrow spreads to other GBP rates
    #
    # Historical Notes:
    #   - SONIA published since 1997 (BoE backwards calculation)
    #   - Became LIBOR replacement 2020 (FSB recommendation)
    #   - T+0 settlement unique among major RFRs
    ...
}
```

---

### 3. Version Control

Track changes to definitions:

```python
# At top of definitions file
__VERSION__ = "1.0"
__LAST_MODIFIED__ = "2025-11-10"
__CHANGELOG__ = """
v1.0 (Nov 2025):
  - Added 9 initial curves (3 USD, 1 CAD, 3 EUR, 1 JPY)
  - Initial USTS bond definition
  
v1.1 (TBD):
  - Add GBP-SONIA
  - Add AUD-RBA (Australian RBA cash rate)
  - Add CHF-SARON (Swiss average rate overnight)
"""
```

---

### 4. Validation on Load

Validate definitions when the module is imported:

```python
# At end of definitions/IRSwaps.py

def validate_definitions():
    """Ensure all curve definitions are well-formed."""
    required_fields = [
        "UseCase",
        "NotionalCurrency",
        "DayCounter",
        "Calendar",
        "BusinessConvention",
        "SettlementDays",
        "Frequency",
        "PaymentLag",
    ]
    
    for curve_name, defn in CURVE_DEFINITIONS.items():
        missing = [f for f in required_fields if f not in defn]
        if missing:
            raise ValueError(f"Curve {curve_name} missing fields: {missing}")
        
        # Validate types
        assert isinstance(defn["SettlementDays"], int), \
            f"{curve_name}: SettlementDays must be int"
        assert isinstance(defn["PaymentLag"], int), \
            f"{curve_name}: PaymentLag must be int"

validate_definitions()
```

---

### 5. Test Coverage

Maintain comprehensive tests for definitions:

```python
# test_definitions.py

def test_all_curves_defined():
    """Every referenced curve exists."""
    from definitions.IRSwaps import CURVE_DEFINITIONS
    expected = {
        "USD-SOFR-1D", "USD-FEDFUNDS", "USD-OIS",
        "CAD-CORRA",
        "EUR-EURIBOR-1M", "EUR-EURIBOR-3M", "EUR-EURIBOR-6M", "EUR-ESTR",
        "JPY-TONAR",
    }
    assert set(CURVE_DEFINITIONS.keys()) == expected

def test_quantlib_definitions_complete():
    """QuantLib has all critical curves."""
    from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
    # USD curves must be supported
    assert "USD-SOFR-1D" in QUANTLIB_CURVE_DEFINITIONS
    assert "USD-OIS" in QUANTLIB_CURVE_DEFINITIONS

def test_rateslib_definitions_complete():
    """RatesLib has OIS curves."""
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
    # OIS curves (preferred for modern pricing)
    assert "USD-SOFR-1D" in RATESLIB_CURVE_DEFINITIONS
    assert "EUR-ESTR" in RATESLIB_CURVE_DEFINITIONS

def test_day_counter_consistency():
    """Day counters match market conventions."""
    from definitions.IRSwaps import CURVE_DEFINITIONS
    
    # OIS curves use ACT/360 (except JPY/CAD)
    assert CURVE_DEFINITIONS["USD-SOFR-1D"]["DayCounter"] == "ACT/360"
    assert CURVE_DEFINITIONS["EUR-ESTR"]["DayCounter"] == "ACT/360"
    
    # IBOR curves use 30E/360
    assert CURVE_DEFINITIONS["EUR-EURIBOR-3M"]["DayCounter"] == "30E/360"
    
    # JPY/CAD use ACT/365F
    assert CURVE_DEFINITIONS["JPY-TONAR"]["DayCounter"] == "ACT/365F"
    assert CURVE_DEFINITIONS["CAD-CORRA"]["DayCounter"] == "ACT/365F"
```

---

### 6. Migration Strategy

When updating a definition (e.g., LIBOR → SOFR):

**Phase 1: Add New Definition**
```python
"USD-SOFR-1D": { ... },  # New definition
"USD-LIBOR-3M": { ... }, # Keep old for backwards compatibility
```

**Phase 2: Update All Usages**
- Point MDP to use new curve
- Update backtests to use new curve
- Mark old curve as deprecated

**Phase 3: Deprecation Period**
- Old curve still works but issues warnings
- Give users time to update trades

**Phase 4: Removal**
- Remove old definition after 1+ year

---

### 7. Documentation Maintenance

Keep documentation in sync:

**When adding a new curve:**
1. Update `CURVE_DEFINITIONS` with full docstrings
2. Update this guide (definitions reference)
3. Add entry to README.md
4. Update MDP documentation
5. Update pricing engine documentation

**When changing an existing curve:**
1. Document what changed and why
2. Note if breaking change (requires code updates)
3. Notify users via changelog
4. Update all dependent documentation

---

### 8. SDR UPI Management

SDR UPI codes are critical for regulatory reporting:

**When adding a new curve:**
1. Check with IDCHDO for assigned UPI codes
2. Contact clearing houses (CME, LCH, etc.)
3. Verify codes are correct format (12 alphanumeric)
4. Test in production with actual SDR submissions

**Format Validation:**
```python
import re

def validate_sdr_upi(upi: str) -> bool:
    """Verify UPI is 12 alphanumeric characters."""
    pattern = r"^[A-Z0-9]{12}$"
    return bool(re.match(pattern, upi))

assert validate_sdr_upi("QZXQ4R16245X")
```

---

## Conclusion

The definitions module is the **foundation** of consistent pricing across ARBS. Key takeaways:

1. **Definitions are centralized** - Single source of truth for conventions
2. **Dual backend support** - QuantLib for QL backends, RatesLib for RL
3. **Extensible** - Adding new curves follows a clear 5-step process
4. **Well-documented** - Each definition includes fields and market context
5. **Validated** - Assertions ensure consistency between backends
6. **Regulatory-aware** - SDR UPI codes for Dodd-Frank reporting

For questions or additions:
- Check existing definitions for similar products
- Follow the checklist for new curves
- Run validation tests before deploying
- Update documentation when changing conventions

---

## Appendix A: Reference Rate Characteristics Summary

| Rate | Currency | Type | Liquidity | Basis | Use |
|------|----------|------|-----------|-------|-----|
| **SOFR** | USD | OIS | Very High | Tight | Modern discounting |
| **Fed Funds** | USD | OIS | Medium | Variable | Legacy/repo markets |
| **EURIBOR** | EUR | IBOR | High | Wide (credit) | Legacy swaps |
| **ESTR** | EUR | OIS | High | Tight | Modern EU discounting |
| **CORRA** | CAD | OIS | Medium | Variable | CAD hedging |
| **TONAR** | JPY | OIS | Low | Wide | JPY funding |

---

## Appendix B: File Locations

**Definitions:**
- Base definitions: `/home/user/ARBS/definitions/IRSwaps.py`
- Bond definitions: `/home/user/ARBS/definitions/FixedRateBonds.py`

**Mappings:**
- QL Curves: `/home/user/ARBS/Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py`
- RL Curves: `/home/user/ARBS/Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py`
- QL Bonds: `/home/user/ARBS/Query/FixedRateBonds/backends/quantlib/ql_frb_definitions_map.py`
- RL Bonds: `/home/user/ARBS/Query/FixedRateBonds/backends/rateslib/rl_frb_definitions_map.py`

**Usage:**
- Pricing: `/home/user/ARBS/Query/IRSwaps/backends/quantlib/ql_pricer.py`
- Curve building: `/home/user/ARBS/Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py`
- MDP: `/home/user/ARBS/MDP/IRSwaps/`

---

**End of Document**

