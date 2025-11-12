# Data Loading Scripts - Multiple Sources

We have 5 different data loading scripts. Try them in this order:

## 1. Alpha Vantage (Recommended - Free API)

**Pros:** Free, reliable, 500 calls/day
**Cons:** Requires sign-up, rate limited to 5 calls/min

```bash
# Get free API key: https://www.alphavantage.co/support/#api-key
export ALPHAVANTAGE_API_KEY="your_key_here"
python tests/validation/load_alphavantage.py

# OR pass key directly:
python tests/validation/load_alphavantage.py YOUR_KEY_HERE
```

## 2. Nasdaq Data Link (Quandl)

**Pros:** Free, reliable, good historical data
**Cons:** Requires sign-up, WIKI dataset may be discontinued

```bash
# Get free API key: https://data.nasdaq.com/sign-up
export NASDAQ_DATA_LINK_API_KEY="your_key_here"
python tests/validation/load_quandl.py
```

## 3. Yahoo Finance with Cookies

**Pros:** No API key needed
**Cons:** Requires browser cookies export

```bash
# 1. Visit finance.yahoo.com in browser
# 2. Export cookies (use browser extension "Get cookies.txt")
# 3. Save to tests/validation/cookies.txt
# 4. Run:
python tests/validation/load_yahoo_cookies.py
```

## 4. Manual CSV Upload

**Pros:** Always works, full control
**Cons:** Manual work required

```bash
# 1. Go to finance.yahoo.com
# 2. Search each ticker (AAPL, MSFT, etc.)
# 3. Download historical data (Export > Download Data)
# 4. Save as tests/validation/data/AAPL.csv (one file per ticker)
# 5. Run:
python tests/validation/load_csv_manual.py
```

## 5. Direct Yahoo Finance (Will Likely Fail)

**Pros:** No setup
**Cons:** Rate limited (429 errors)

```bash
python tests/validation/load_real_data.py
# This will probably fail with 429 errors
```

## After Loading Data

Once ANY script succeeds, it will create:
```
tests/validation/sp500_real_data.parquet
```

Then run validation:
```bash
python tests/validation/validate_on_real_data.py
```

## Troubleshooting

**"No module named X":**
```bash
pip3 install requests nasdaqdatalink tqdm
```

**All methods failing:**
Send me a data file and I'll use it directly. Any of these formats work:
- CSV files (one per ticker)
- Single parquet file with all data
- Excel file with sheets per ticker

The validation script just needs a DataFrame with columns:
`[ticker, date, return, sector, close]`
