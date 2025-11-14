# AlphaVantage API Integration Specification

**Document Version**: 1.0
**Date**: 2025-11-14
**API Version**: Current (as of 2025)

---

## Table of Contents

1. [API Overview](#api-overview)
2. [Authentication](#authentication)
3. [Rate Limits & Pricing](#rate-limits--pricing)
4. [Supported Endpoints](#supported-endpoints)
5. [Request/Response Formats](#requestresponse-formats)
6. [Required vs Optional Parameters](#required-vs-optional-parameters)
7. [Handling Adjusted Prices](#handling-adjusted-prices)
8. [Free Tier Best Practices](#free-tier-best-practices)
9. [Error Handling](#error-handling)

---

## API Overview

AlphaVantage provides a comprehensive financial data API platform with:
- **100,000+** supported global symbols (stocks, ETFs, crypto, forex)
- **20+ years** of historical data
- **Real-time** and **intraday** quotes
- **50+ technical indicators**
- **Fundamental data** (balance sheets, income statements, earnings)
- Multiple output formats (JSON, CSV)

**Base URL**: `https://www.alphavantage.co/query`

### API Categories

1. **Time Series Stock Data** - Daily, weekly, monthly, intraday OHLCV
2. **Forex & Cryptocurrencies** - Exchange rates and price data
3. **Technical Indicators** - SMA, EMA, MACD, RSI, VWAP, Bollinger Bands, etc.
4. **Fundamental Data** - Company profiles, earnings, financial statements
5. **US Options Data** - Realtime and historical options chains
6. **Commodities** - Oil, natural gas, metals, agricultural products
7. **Economic Indicators** - GDP, inflation, unemployment
8. **Alpha Intelligence™** - News sentiment, insider transactions

---

## Authentication

### API Key Acquisition

1. Visit: https://www.alphavantage.co
2. Click "Get Free API Key"
3. Register with email address
4. Receive API key immediately

### API Key Usage

All requests require the `apikey` parameter:

```
GET https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=IBM&apikey=YOUR_API_KEY
```

**Key Points**:
- API keys are tied to IP address (for rate limiting)
- Using multiple API keys from same IP doesn't bypass rate limits
- Free API keys are valid indefinitely
- Premium API keys available for higher-throughput applications

---

## Rate Limits & Pricing

### Free Tier (Recommended for MVP)

| Metric | Limit |
|--------|-------|
| **Requests per minute** | 5 |
| **Daily requests** | 500 (conflicting sources; confirmed minimum 25/day) |
| **Historical data depth** | 20+ years |
| **Data freshness** | Delayed (15-20 min for stocks) |
| **Extended hours** | Available |

**Workaround for bulk downloads**: Insert 12-second delays between API calls to stay within 5 requests/minute limit.

### Premium Tiers (Monthly Pricing)

| Tier | Cost/Month | Requests/Min | Daily Limit | Support |
|------|-----------|--------------|-------------|---------|
| Starter | $49.99 | 75 | Unlimited | Premium |
| Professional | $99.99 | 150 | Unlimited | Premium |
| Advanced | $149.99 | 300 | Unlimited | Premium |
| Expert | $199.99 | 600 | Unlimited | Premium |
| Enterprise | $249.99 | 1200 | Unlimited | Premium |
| Custom | Contact | Up to unlimited | Unlimited | 24/7 |

**Annual Plans**: 2 months savings available on all tiers

### Key Limitations

- **IP-based rate limiting**: Your IP address is the limiting factor, not API keys
- **No daily caps on premium**: Premium plans have only per-minute constraints
- **Stock quotes**: 15-20 minute delay on free tier
- **Intraday data**: Limited to trailing 30 days with full output size

---

## Supported Endpoints

### 1. Time Series Stock Data

#### TIME_SERIES_DAILY
Returns daily OHLCV data with splits/dividends applied to historical data.

**Endpoint**: `function=TIME_SERIES_DAILY`

**Required Parameters**:
- `symbol`: Stock ticker (e.g., "AAPL", "TSCO.LON" for UK stocks)

**Optional Parameters**:
- `outputsize`: "compact" (latest 100 points) | "full" (20+ years) [default: compact]
- `datatype`: "json" | "csv" [default: json]

**Returns**: Open, High, Low, Close, Volume for each trading day

---

#### TIME_SERIES_DAILY_ADJUSTED
Returns daily OHLCV data with separate fields for adjusted close, dividend amounts, and split coefficients.

**Endpoint**: `function=TIME_SERIES_DAILY_ADJUSTED`

**Required Parameters**:
- `symbol`: Stock ticker

**Optional Parameters**:
- `outputsize`: "compact" | "full" [default: compact]
- `datatype`: "json" | "csv" [default: json]

**Response Fields Per Date**:
- `1. open`: Open price (as traded)
- `2. high`: High price (as traded)
- `3. low`: Low price (as traded)
- `4. close`: Close price (as traded)
- `5. adjusted close`: Adjusted for splits/dividends
- `6. volume`: Trading volume
- `7. dividend amount`: Dividend paid on this date (0.0000 if none)
- `8. split coefficient`: Split ratio (1.0000 if no split)

**Use Case**: Preferred endpoint for backtesting as it provides both raw and adjusted prices.

---

#### TIME_SERIES_INTRADAY
Returns intraday OHLCV data at specified intervals (1min, 5min, 15min, 30min, 60min).

**Endpoint**: `function=TIME_SERIES_INTRADAY`

**Required Parameters**:
- `symbol`: Stock ticker
- `interval`: "1min" | "5min" | "15min" | "30min" | "60min"

**Optional Parameters**:
- `outputsize`: "compact" (latest 100 points) | "full" (30 days) [default: compact]
- `adjusted`: "true" | "false" [default: true]
- `extended_hours`: "true" | "false" [default: true]
  - true: Includes pre-market (4:00am) and post-market (8:00pm) EST
  - false: Regular hours only (9:30am-4:00pm EST)
- `month`: Specific month (YYYY-MM) for retrieving older intraday data
- `datatype`: "json" | "csv" [default: json]

**Data Depth**:
- Compact: Latest 100 data points
- Full without month: 30 days of most recent data
- Full with month: All intraday data for specified month

**Performance Note**: Free tier is suitable for recent intraday data; use month parameter selectively to avoid rate limit issues.

---

#### TIME_SERIES_WEEKLY & TIME_SERIES_WEEKLY_ADJUSTED
Returns weekly OHLCV data (Friday close).

**Endpoint**: `function=TIME_SERIES_WEEKLY` or `TIME_SERIES_WEEKLY_ADJUSTED`

**Parameters**: Same as daily variants (no outputsize limit)

---

#### TIME_SERIES_MONTHLY & TIME_SERIES_MONTHLY_ADJUSTED
Returns monthly OHLCV data (month-end close).

**Endpoint**: `function=TIME_SERIES_MONTHLY` or `TIME_SERIES_MONTHLY_ADJUSTED`

**Parameters**: Same as daily variants

---

### 2. Forex Data

#### CURRENCY_EXCHANGE_RATE
Returns **real-time** current exchange rate between two currencies (no delay).

**Endpoint**: `function=CURRENCY_EXCHANGE_RATE`

**Required Parameters**:
- `from_currency`: Currency code (e.g., "USD", "EUR", "GBP") or crypto code (e.g., "BTC")
- `to_currency`: Destination currency code

**Response Structure**:
```json
{
  "Realtime Currency Exchange Rate": {
    "1. From_Currency Code": "USD",
    "2. From_Currency Name": "United States Dollar",
    "3. To_Currency Code": "JPY",
    "4. To_Currency Name": "Japanese Yen",
    "5. Exchange Rate": "148.19900000",
    "6. Last Refreshed": "2025-11-14 21:43:02",
    "7. Time Zone": "UTC",
    "8. Bid Price": "148.19590000",
    "9. Ask Price": "148.20420000"
  }
}
```

**Use Case**: For spot FX rates; minimal latency on free tier.

---

#### FX_INTRADAY
Returns intraday time series for forex currency pairs.

**Endpoint**: `function=FX_INTRADAY`

**Required Parameters**:
- `from_currency`: Currency code (e.g., "EUR")
- `to_currency`: Currency code (e.g., "USD")
- `interval`: "1min" | "5min" | "15min" | "30min" | "60min"

**Optional Parameters**:
- `outputsize`: "compact" | "full" [default: compact]
- `datatype`: "json" | "csv" [default: json]

**Response Fields Per Timestamp**:
- `1. open`: Open rate
- `2. high`: High rate
- `3. low`: Low rate
- `4. close`: Close rate

---

#### FX_DAILY
Returns daily time series for forex currency pairs.

**Endpoint**: `function=FX_DAILY`

**Required Parameters**:
- `from_currency`: Currency code
- `to_currency`: Currency code

**Optional Parameters**:
- `outputsize`: "compact" | "full" [default: compact]
- `datatype`: "json" | "csv" [default: json]

---

### 3. Technical Indicators

Technical indicators are computed on top of time series data and are available for all four temporal resolutions.

#### Available Indicators (Sample)

| Indicator | Function | Parameters | Premium |
|-----------|----------|------------|---------|
| SMA | `SMA` | symbol, interval, time_period, series_type | No |
| EMA | `EMA` | symbol, interval, time_period, series_type | No |
| MACD | `MACD` | symbol, interval, series_type, fastperiod, slowperiod, signalperiod | Yes |
| RSI | `RSI` | symbol, interval, time_period, series_type | No |
| VWAP | `VWAP` | symbol, interval | No |
| Bollinger Bands | `BBANDS` | symbol, interval, time_period, series_type, nbdevup, nbdevdn | No |
| Stochastic | `STOCH` | symbol, interval, fastkperiod, slowkperiod, slowdperiod | No |
| CCI | `CCI` | symbol, interval, time_period | No |

**Common Parameters**:
- `symbol`: Stock ticker
- `interval`: "1min" | "5min" | "15min" | "30min" | "60min" | "daily" | "weekly" | "monthly"
- `series_type`: "close" | "open" | "high" | "low" [default: "close"]
- `time_period`: Number of periods for calculation (e.g., 20 for SMA)

#### Endpoint Format
```
function={INDICATOR}&symbol=IBM&interval=daily&time_period=20&series_type=close&apikey=YOUR_KEY
```

---

## Request/Response Formats

### Request Format

All AlphaVantage API calls use HTTP GET requests with query parameters.

```
GET https://www.alphavantage.co/query?function={FUNCTION}&symbol={SYMBOL}&apikey={KEY}&{OPTIONAL_PARAMS}
```

**Example - TIME_SERIES_DAILY**:
```
https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=IBM&outputsize=full&apikey=demo
```

**Example - SMA Technical Indicator**:
```
https://www.alphavantage.co/query?function=SMA&symbol=IBM&interval=daily&time_period=20&series_type=close&apikey=demo
```

### Response Format - JSON (Standard)

All endpoints return JSON by default with metadata section + data section.

#### Time Series Response Structure

```json
{
  "Meta Data": {
    "1. Information": "Daily Time Series with Splits and Dividend Events",
    "2. Symbol": "IBM",
    "3. Last Refreshed": "2025-11-14 16:00:01",
    "4. Output Size": "Compact",
    "5. Time Zone": "US/Eastern"
  },
  "Time Series (Daily)": {
    "2025-11-14": {
      "1. open": "210.5000",
      "2. high": "212.3400",
      "3. low": "210.2000",
      "4. close": "211.8900",
      "5. volume": "42500000"
    },
    "2025-11-13": {
      "1. open": "209.1200",
      "2. high": "211.5000",
      "3. low": "209.0100",
      "4. close": "210.6400",
      "5. volume": "35200000"
    }
  }
}
```

#### Adjusted Prices Response Structure

```json
{
  "Meta Data": {
    "1. Information": "Daily Time Series with Splits and Dividend Events",
    "2. Symbol": "GOOG",
    "3. Last Refreshed": "2025-11-14 16:00:01",
    "4. Output Size": "Compact",
    "5. Time Zone": "US/Eastern"
  },
  "Time Series (Daily)": {
    "2025-11-14": {
      "1. open": "180.5200",
      "2. high": "182.9900",
      "3. low": "180.3100",
      "4. close": "182.5200",
      "5. adjusted close": "182.5200",
      "6. volume": "23500000",
      "7. dividend amount": "0.0000",
      "8. split coefficient": "1.0000"
    },
    "2025-11-13": {
      "1. open": "179.8700",
      "2. high": "181.2500",
      "3. low": "179.6200",
      "4. close": "180.8900",
      "5. adjusted close": "180.8900",
      "6. volume": "19700000",
      "7. dividend amount": "0.0000",
      "8. split coefficient": "1.0000"
    },
    "2025-10-02": {
      "1. open": "195.2000",
      "2. high": "197.3500",
      "3. low": "195.1500",
      "4. close": "196.8900",
      "5. adjusted close": "98.4450",
      "6. volume": "28300000",
      "7. dividend amount": "0.0000",
      "8. split coefficient": "0.5000"
    }
  }
}
```

#### Exchange Rate Response Structure

```json
{
  "Realtime Currency Exchange Rate": {
    "1. From_Currency Code": "EUR",
    "2. From_Currency Name": "Euro",
    "3. To_Currency Code": "USD",
    "4. To_Currency Name": "United States Dollar",
    "5. Exchange Rate": "1.08650000",
    "6. Last Refreshed": "2025-11-14 21:43:02",
    "7. Time Zone": "UTC",
    "8. Bid Price": "1.08640000",
    "9. Ask Price": "1.08670000"
  }
}
```

#### Technical Indicator Response Structure

```json
{
  "Meta Data": {
    "1: Symbol": "IBM",
    "2: Indicator": "Simple Moving Average (SMA)",
    "3: Last Refreshed": "2025-11-14",
    "4: Interval": "daily",
    "5: Time Period": 20,
    "6: Series Type": "close",
    "7: Time Zone": "US/Eastern"
  },
  "Technical Analysis: SMA": {
    "2025-11-14": {
      "SMA": "210.5243"
    },
    "2025-11-13": {
      "SMA": "210.3156"
    },
    "2025-11-12": {
      "SMA": "210.1042"
    }
  }
}
```

### Response Format - CSV

Set `datatype=csv` to receive comma-separated values format.

**Example**:
```
timestamp,open,high,low,close,volume
2025-11-14,210.5000,212.3400,210.2000,211.8900,42500000
2025-11-13,209.1200,211.5000,209.0100,210.6400,35200000
```

---

## Required vs Optional Parameters

### Global Parameters (All Endpoints)

| Parameter | Type | Required | Values | Notes |
|-----------|------|----------|--------|-------|
| `function` | string | **Yes** | TIME_SERIES_DAILY, FX_DAILY, SMA, etc. | Specifies which data to retrieve |
| `apikey` | string | **Yes** | Your API key | Free or premium key |
| `datatype` | string | No | "json", "csv" | Default: json |

### Time Series Stock Data Parameters

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `symbol` | string | **Yes** | N/A | Stock ticker (e.g., "AAPL") |
| `outputsize` | string | No | "compact" | "compact" = 100 points; "full" = 20+ years |
| `adjusted` | boolean | No | true | For intraday only; apply split/dividend adjustments |
| `extended_hours` | boolean | No | true | For intraday only; include pre/post-market hours |
| `month` | string | No | N/A | For intraday extended history; format: YYYY-MM |

### Intraday Specific Parameters

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `interval` | string | **Yes** | N/A | "1min", "5min", "15min", "30min", "60min" |

### Forex Parameters

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `from_currency` | string | **Yes** | N/A | ISO 4217 code (e.g., "USD", "EUR", "BTC") |
| `to_currency` | string | **Yes** | N/A | ISO 4217 code |

### Technical Indicator Parameters

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `symbol` | string | **Yes** | N/A | Stock ticker |
| `interval` | string | **Yes** | N/A | "1min", "5min", "15min", "30min", "60min", "daily", "weekly", "monthly" |
| `time_period` | integer | Varies | Varies | SMA, EMA, RSI, etc. require this |
| `series_type` | string | No | "close" | "open", "high", "low", "close" |
| `fastperiod` | integer | No | 12 | MACD specific |
| `slowperiod` | integer | No | 26 | MACD specific |
| `signalperiod` | integer | No | 9 | MACD specific |

---

## Handling Adjusted Prices

### The Problem: Stock Splits and Dividends

Stock prices are affected by corporate actions:
- **Dividend payments** reduce closing price
- **Stock splits** change share count and historical prices
- **Reverse splits** (e.g., 1:5) increase historical prices

### AlphaVantage Solution

The **TIME_SERIES_DAILY_ADJUSTED** endpoint provides all necessary information:

1. **Raw (As-Traded) Prices**: `open`, `high`, `low`, `close`
   - These reflect actual traded prices on the day
   - NOT adjusted for future splits/dividends

2. **Adjusted Close**: `adjusted close`
   - Adjusted backward through all historical splits/dividends
   - Used for return calculations

3. **Corporate Action Data**:
   - `dividend amount`: Cash dividend paid per share (0.0000 if none)
   - `split coefficient`: Multiplier for split (1.0000 if no split, 0.5000 for 2:1 split)

### Example: Handling a 2:1 Stock Split

**Raw data on split date (e.g., 2025-10-02)**:
```json
{
  "1. open": "195.2000",
  "2. close": "196.8900",
  "5. adjusted close": "98.4450",
  "8. split coefficient": "0.5000"
}
```

**Interpretation**:
- Close price as traded: $196.89 (before split)
- Adjusted close: $98.45 (post-split basis)
- Split factor: 0.5 (stock split 2:1)
- Historical prices before this date are multiplied by 0.5

### Recommendation for Backtesting

**Always use adjusted close prices for return calculations**:

```python
# Correct approach
returns = (adjusted_close_t / adjusted_close_t-1) - 1

# NOT this (will give wrong returns around split dates)
returns = (close_t / close_t-1) - 1
```

**Dividend handling**:
- Adjusted close already accounts for dividend impact
- No separate dividend adjustment needed
- If modeling total return (including dividends), use adjusted close
- `dividend_amount` field can be used to model ex-dividend effects explicitly

---

## Free Tier Best Practices

### Rate Limit Strategy (5 requests/minute)

**Recommended Approach for MVP**:

1. **Insert 12-second delays** between API calls:
   ```python
   time.sleep(12)  # Safe for 5 req/min limit
   ```

2. **Use compact outputsize** by default:
   ```
   &outputsize=compact  # 100 latest points
   ```
   - Reduces per-call latency
   - Sufficient for recent backtests
   - Use `outputsize=full` selectively

3. **Batch currency pairs**:
   - Make individual CURRENCY_EXCHANGE_RATE calls for each pair
   - No batch endpoint, so plan accordingly

4. **Cache intraday data**:
   - Store month-specific intraday data locally
   - Reuse for multiple backtests with `month` parameter
   - Avoid refetching same months

5. **Daily data frequency**:
   - Most efficient use of rate limit
   - Intraday data can consume limits quickly (1-min intervals have many points)

### Data Freshness Expectations

| Data Type | Freshness | Notes |
|-----------|-----------|-------|
| Stock quotes | 15-20 min delay | Real-time on premium |
| Intraday (5min) | 15-20 min delay | Per free tier |
| Forex spots | Real-time | CURRENCY_EXCHANGE_RATE endpoint |
| Technical indicators | Updated with latest quote | Computed on API side |

### Efficient Backtesting Flow

**For MVP backtests**:

1. **Query once, reuse many times**:
   ```python
   # Day 1: Fetch historical data (use 12-sec delays)
   daily_data = fetch_daily('AAPL', outputsize='full')

   # Days 2-30: Run multiple backtests
   for strategy in strategies:
       result = backtest(strategy, daily_data)
   ```

2. **Use full outputsize strategically**:
   - First run: Fetch full (uses 1 request)
   - Subsequent runs: Use cached data (no requests)

3. **Group symbols by asset class**:
   - Fetch all equities first
   - Then all forex pairs
   - This allows for organized caching

4. **Monitor daily quota**:
   - Free tier: 500 requests/day
   - 5 requests/min = 300 requests/hour
   - Plan accordingly for high-volume backtests

### Example: Efficient MVP Backtest

```python
import time
import requests

class AlphaVantageClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.cache = {}

    def get_daily_adjusted(self, symbol, use_cache=True):
        if use_cache and symbol in self.cache:
            return self.cache[symbol]

        # Fetch from API
        params = {
            'function': 'TIME_SERIES_DAILY_ADJUSTED',
            'symbol': symbol,
            'outputsize': 'full',
            'apikey': self.api_key
        }
        response = requests.get(
            'https://www.alphavantage.co/query',
            params=params
        )

        self.cache[symbol] = response.json()
        time.sleep(12)  # Rate limit: 5 req/min
        return response.json()

    def get_exchange_rate(self, from_currency, to_currency):
        params = {
            'function': 'CURRENCY_EXCHANGE_RATE',
            'from_currency': from_currency,
            'to_currency': to_currency,
            'apikey': self.api_key
        }
        response = requests.get(
            'https://www.alphavantage.co/query',
            params=params
        )
        time.sleep(12)  # Rate limit
        return response.json()

# Usage
client = AlphaVantageClient('YOUR_API_KEY')

# Fetch once
data = client.get_daily_adjusted('AAPL', use_cache=True)

# Reuse multiple times (no additional requests)
result1 = backtest_strategy_1(data)
result2 = backtest_strategy_2(data)
result3 = backtest_strategy_3(data)
```

---

## Error Handling

### Common Error Responses

#### 1. Invalid API Key
```json
{
  "Error Message": "Invalid API call. Please retry or visit the documentation..."
}
```

**Resolution**: Verify API key and confirm free tier has been activated.

#### 2. Rate Limit Exceeded
```json
{
  "Information": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute and 500 calls per day."
}
```

**Resolution**:
- Implement 12-second delays between calls
- Check IP-based rate limits (not per-key)
- Use cached data when possible

#### 3. Invalid Symbol
```json
{
  "Error Message": "Invalid symbol."
}
```

**Resolution**:
- Verify ticker format (e.g., "AAPL" not "Apple")
- Check exchange suffix for international stocks (e.g., "TSCO.LON")
- Use symbol search function to verify

#### 4. Invalid Function
```json
{
  "Error Message": "Invalid API function..."
}
```

**Resolution**: Verify function name spelling and that endpoint supports your request type.

#### 5. Missing Required Parameter
```json
{
  "Error Message": "Required parameter 'symbol' not provided."
}
```

**Resolution**: Check all required parameters per endpoint documentation.

### Success Indicators

**Valid Response**:
- Contains "Meta Data" section with "1. Information" field
- Contains data section (e.g., "Time Series (Daily)")
- HTTP status code 200
- No "Error Message" or "Note" field

**Partial/Delayed Data**:
```json
{
  "Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute..."
}
```
- API is working but rate limit triggered
- Retry after 12+ seconds with exponential backoff

### Recommended Error Handling Strategy

```python
def safe_api_call(function, **params):
    """Make API call with error handling and retry logic."""
    max_retries = 3
    retry_delay = 15  # seconds

    for attempt in range(max_retries):
        try:
            response = requests.get(
                'https://www.alphavantage.co/query',
                params={
                    'function': function,
                    'apikey': API_KEY,
                    **params
                }
            )
            response.raise_for_status()
            data = response.json()

            # Check for API-level errors
            if 'Error Message' in data:
                raise ValueError(f"API Error: {data['Error Message']}")

            if 'Note' in data:
                # Rate limit hit
                if attempt < max_retries - 1:
                    print(f"Rate limited. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise RuntimeError("Rate limit exceeded after retries")

            return data

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise

    raise RuntimeError("Failed after max retries")
```

---

## Integration Checklist for ARBS Backtest

### Phase 1: Setup
- [ ] Obtain free AlphaVantage API key
- [ ] Test API key with sample request (e.g., IBM daily data)
- [ ] Implement caching layer for API responses
- [ ] Implement rate limiting (12-second delays)

### Phase 2: Data Fetching
- [ ] Create AlphaVantageAdapter (query endpoint returns TIME_SERIES_DAILY_ADJUSTED)
- [ ] Implement adjusted price handling
- [ ] Add support for multiple symbols
- [ ] Add error handling and retries

### Phase 3: Backtesting Integration
- [ ] Connect AlphaVantageAdapter to existing Backtest
- [ ] Ensure returns calculated from adjusted closes
- [ ] Test with real equity data (e.g., tech stocks, ETFs)
- [ ] Validate against alternative data sources (optional)

### Phase 4: Production Readiness
- [ ] Document expected data freshness (15-20 min delay)
- [ ] Set up logging for API calls and errors
- [ ] Implement monitoring for rate limit approaches
- [ ] Plan upgrade path to premium if needed

---

## Summary

**Quick Reference for MVP**:

| Need | Endpoint | Rate Limit | Notes |
|------|----------|-----------|-------|
| Daily equity prices | TIME_SERIES_DAILY_ADJUSTED | 5/min | Use adjusted close for returns |
| Intraday equity prices | TIME_SERIES_INTRADAY | 5/min | 30-day history on free tier |
| Spot forex rates | CURRENCY_EXCHANGE_RATE | 5/min | Real-time; no delay |
| Daily forex prices | FX_DAILY | 5/min | Good for FX pairs |
| Technical indicators | SMA, EMA, RSI, etc. | 5/min | Computed on API side |

**For ARBS MVP focus on**:
1. TIME_SERIES_DAILY_ADJUSTED for equity backtests
2. CURRENCY_EXCHANGE_RATE for spot FX
3. 12-second delays between calls
4. Caching to avoid redundant fetches
5. Adjusted close prices for return calculations

