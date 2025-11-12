# Phase 4B: Real Data Loading & Validation

## 🎯 What We're Trying to Achieve

**Goal**: Validate the three sector risk model implementations against real S&P 500 data to verify paper claims.

**Current Status**:
- ✅ All 120 tests passing (107 unit + 13 integration)
- ✅ Three sector covariance models implemented (BlockDiagonal, TwoStep, StochasticBlock)
- ✅ Portfolio validation framework implemented
- ✅ Validated on synthetic data (proof of correctness)
- ❌ NOT validated on real market data (cannot verify paper claims yet)

**This Phase**: Load real S&P 500 data (2015-2023) and run portfolio validation to verify paper claims.

---

## 📋 Summary of What We Worked On

### Phase 4A - Implementation & Synthetic Validation

1. **Fixed False Claims in Documentation**
   - Changed status from "VALIDATED" to "IMPLEMENTATION COMPLETE, VALIDATION INCOMPLETE"
   - Removed unverified claims about improvements
   - Added warnings that results were on synthetic data only

2. **Created Portfolio Validation Framework**
   - `tests/validation/portfolio_performance_validation.py`
   - Implements minimum variance portfolio optimization
   - Measures: HHI, Leverage, RDI, Sharpe ratio, R²_out
   - Validated on synthetic data successfully

3. **Created Multiple Data Source Loaders**
   - `load_alphavantage.py` - Alpha Vantage API (recommended)
   - `load_quandl.py` - Nasdaq Data Link (Quandl)
   - `load_yahoo_cookies.py` - Yahoo Finance with cookies
   - `load_csv_manual.py` - Manual CSV upload
   - `README_DATA_LOADING.md` - Instructions

4. **Key Learning**
   - Cannot validate paper claims without real market data
   - Synthetic data proves code correctness but not research validity
   - Need to be honest about what's validated vs what's not

---

## 🚀 Exact Instructions for THIS Branch

### Step 1: Check Current Branch Status

```bash
cd /home/user/ARBS
git status
git branch --show-current
```

**Expected**: You should be on `claude/reassess-papers-status-011CV4KysG3JmBR8arH5J4dz`

### Step 2: Commit Any Remaining Changes

```bash
git add tests/validation/
git status  # Verify what will be committed
git commit -m "docs: Add detailed data loading instructions and phase summary"
```

### Step 3: Push to Remote

```bash
git push -u origin claude/reassess-papers-status-011CV4KysG3JmBR8arH5J4dz
```

**CRITICAL**: Retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s) if network errors occur.

### Step 4: Try Loading Real Data

Try these scripts IN ORDER until one succeeds:

#### Option 1: Alpha Vantage (Recommended)

```bash
# Get free API key: https://www.alphavantage.co/support/#api-key
export ALPHAVANTAGE_API_KEY="your_key_here"
python tests/validation/load_alphavantage.py
```

**Expected Output**:
```
ALPHA VANTAGE LOADER
================================================================================
API Key: **********your_last_4_chars
Total tickers: 40

[Technology]
  ✓ AAPL: 2268 days
  ✓ MSFT: 2268 days
  ...

✓ Saved to tests/validation/sp500_real_data.parquet
```

#### Option 2: Nasdaq Data Link (Quandl)

```bash
# Get free API key: https://data.nasdaq.com/sign-up
export NASDAQ_DATA_LINK_API_KEY="your_key_here"
python tests/validation/load_quandl.py
```

#### Option 3: Yahoo Finance with Cookies

```bash
# 1. Visit finance.yahoo.com in browser
# 2. Install browser extension "Get cookies.txt"
# 3. Export cookies, save as tests/validation/cookies.txt
# 4. Run:
python tests/validation/load_yahoo_cookies.py
```

#### Option 4: Manual CSV Upload (Always Works)

```bash
# 1. Go to finance.yahoo.com
# 2. Search each ticker (AAPL, MSFT, etc.)
# 3. Historical Data > Download Data
# 4. Save to tests/validation/data/TICKER.csv
# 5. Run:
mkdir -p tests/validation/data
# ... download CSVs to data/ directory ...
python tests/validation/load_csv_manual.py
```

#### Option 5: Direct Yahoo (Will Likely Fail)

```bash
python tests/validation/load_real_data.py
# Expected: 429 rate limit errors
```

### Step 5: Verify Data Was Created

```bash
ls -lh tests/validation/sp500_real_data.parquet
```

**Expected**: File exists, ~5-10 MB size

### Step 6: Inspect the Data

```python
python -c "
import polars as pl
df = pl.read_parquet('tests/validation/sp500_real_data.parquet')
print(f'Tickers: {df[\"ticker\"].n_unique()}')
print(f'Observations: {len(df):,}')
print(f'Date range: {df[\"date\"].min()} to {df[\"date\"].max()}')
print(f'Sectors: {df[\"sector\"].n_unique()}')
print(f'\nColumns: {df.columns}')
print(f'\nFirst few rows:\n{df.head()}')
"
```

**Expected Output**:
```
Tickers: 40
Observations: 90,720
Date range: 2015-01-02 to 2023-12-29
Sectors: 8

Columns: ['ticker', 'date', 'close', 'return', 'sector']

First few rows:
shape: (5, 5)
┌────────┬────────────┬────────┬──────────┬────────────┐
│ ticker ┆ date       ┆ close  ┆ return   ┆ sector     │
│ ---    ┆ ---        ┆ ---    ┆ ---      ┆ ---        │
│ str    ┆ str        ┆ f64    ┆ f64      ┆ str        │
╞════════╪════════════╪════════╪══════════╪════════════╡
│ AAPL   ┆ 2015-01-02 ┆ 109.33 ┆ null     ┆ Technology │
│ AAPL   ┆ 2015-01-05 ┆ 106.25 ┆ -0.02817 ┆ Technology │
│ AAPL   ┆ 2015-01-06 ┆ 106.26 ┆ 0.00009  ┆ Technology │
│ AAPL   ┆ 2015-01-07 ┆ 107.75 ┆ 0.01402  ┆ Technology │
│ AAPL   ┆ 2015-01-08 ┆ 111.89 ┆ 0.03841  ┆ Technology │
└────────┴────────────┴────────┴──────────┴────────────┘
```

### Step 7: Run Validation on Real Data

```bash
python tests/validation/validate_on_real_data.py
```

**Expected Output**:
```
================================================================================
LOADING REAL S&P 500 DATA
================================================================================

Data file: tests/validation/sp500_real_data.parquet
Size: 7.2 MB

✓ Loaded 90,720 observations
✓ Tickers: 40
✓ Date range: 2015-01-02 to 2023-12-29
✓ Sectors: 8

Train/Test Split:
  Training: 1516 days (2015-01-02 to 2021-01-15)
  Test: 748 days (2021-01-19 to 2023-12-29)

================================================================================
RUNNING PORTFOLIO PERFORMANCE VALIDATION ON REAL DATA
================================================================================

[Running models...]

================================================================================
COMPARISON TABLE - REAL S&P 500 DATA
================================================================================

Model                          HHI        Leverage   RDI        Sharpe     R²_out
--------------------------------------------------------------------------------
1. Sample Covariance           0.XXXX     XX.XX      X.XXX      X.XXX      X.XXX
2. Ledoit-Wolf                 0.XXXX     XX.XX      X.XXX      X.XXX      X.XXX
3. BlockDiagonal (Paper 2)     0.XXXX     XX.XX      X.XXX      X.XXX      X.XXX
4. TwoStep (Paper 1)           0.XXXX     XX.XX      X.XXX      X.XXX      X.XXX
5. StochasticBlock (Paper 3)   0.XXXX     XX.XX      X.XXX      X.XXX      X.XXX

================================================================================
PAPER CLAIMS VS ACTUAL RESULTS (REAL DATA)
================================================================================

📊 Paper 1 (García-Medina - TwoStep)
   Claim: 'Best diversification and leverage'
   HHI: X.XXXX vs Baseline X.XXXX
   → +XX.X% change
   Leverage: XX.XX vs Baseline XX.XX
   → +XX.X% change
   Verdict: ✅ VALIDATED or ❌ NOT VALIDATED

...

✓ Results saved to tests/validation/validation_results_real_data.txt
```

### Step 8: Commit the Real Data & Results

```bash
git add tests/validation/sp500_real_data.parquet
git add tests/validation/validation_results_real_data.txt
git add tests/validation/DATA_LOADING_INSTRUCTIONS.md
git status  # Verify files
git commit -m "feat: Add real S&P 500 data and validation results"
git push -u origin claude/reassess-papers-status-011CV4KysG3JmBR8arH5J4dz
```

---

## 🔄 What to Do If Scripts Fail

### If ALL scripts fail to load data:

**Option A: Manual Data Upload**
1. Download this sample dataset: [provide your own S&P 500 data]
2. Save as `tests/validation/sp500_real_data.parquet`
3. Required format: Polars/Pandas DataFrame with columns:
   - `ticker` (str): Stock ticker (e.g., "AAPL")
   - `date` (str): Date in YYYY-MM-DD format
   - `close` (float): Closing price
   - `return` (float): Daily return (price pct change)
   - `sector` (str): Sector name
4. Skip to Step 7 (run validation)

**Option B: Use Your Own Data Source**
1. Create new loader script following the pattern in existing loaders
2. Must output to `sp500_real_data.parquet`
3. Must have columns: [ticker, date, close, return, sector]
4. Date range: 2015-2023 (or similar multi-year period)
5. Minimum 30 tickers across 5+ sectors

### If Validation Script Fails:

**Error: "No module named X"**
```bash
pip3 install numpy pandas polars scikit-learn scipy pytest matplotlib
```

**Error: "Real data file not found"**
- Go back to Step 4 and successfully load data first

**Error: "Insufficient data"**
- Check you have at least 900 days of data per ticker
- Check date range covers 2015-2023 or similar period

**Error: Type errors in covariance fit**
- Verify data has exactly these columns: [ticker, date, close, return, sector]
- Verify `return` column is float, not string
- Verify no null values in return column (except first row per ticker)

---

## 🎯 Prompt to Initiate Next Phase (NEW BRANCH)

Once the data is successfully loaded and validation is complete, create a new branch for Phase 5:

```bash
cd /home/user/ARBS
git checkout main  # or your main branch
git pull origin main
git checkout -b claude/phase-5-analysis-and-documentation-XXXXXX  # Use your session ID

# Or if continuing from current branch:
git checkout -b claude/phase-5-analysis-and-documentation-XXXXXX
```

### Phase 5 Prompt for Claude:

```
We've successfully loaded real S&P 500 data and run portfolio validation comparing three sector risk models against baseline approaches.

Your task for Phase 5:

1. Analyze the validation results in tests/validation/validation_results_real_data.txt
2. Compare actual results to paper claims:
   - Paper 1 (García-Medina 2024): TwoStep claims "best diversification and leverage"
   - Paper 2 (Žignić 2024): BlockDiagonal claims "excellent out-of-sample Sharpe ratios"
   - Paper 3 (Chen 2025): StochasticBlock claims "captures cross-sector correlations"
3. Update all documentation with ACTUAL verified results (no more unverified claims)
4. Create a final report summarizing:
   - Which paper claims were validated ✅
   - Which paper claims were NOT validated ❌
   - Performance differences vs baseline (quantified)
   - Recommendations for production use
5. Update EXECUTIVE_SUMMARY.md with final status

Be brutally honest. If paper claims don't hold on real data, document that clearly. We want truth, not confirmation bias.

Files to analyze:
- tests/validation/validation_results_real_data.txt (primary results)
- tests/validation/sp500_real_data.parquet (the data used)

Files to update:
- docs/papers/sector_risk_models/EXECUTIVE_SUMMARY.md
- docs/PHASE_4_COMPLETION_SUMMARY.md
- docs/ACTUAL_VALIDATION_RESULTS.md (replace synthetic results with real results)

Create new file:
- docs/FINAL_VALIDATION_REPORT.md (comprehensive analysis)
```

---

## 📊 What the Data Should Look Like

### File Format
- **Filename**: `sp500_real_data.parquet`
- **Location**: `tests/validation/sp500_real_data.parquet`
- **Format**: Apache Parquet (Polars/Pandas compatible)
- **Size**: ~5-10 MB (40 tickers × 2,268 days × 5 columns)

### Schema (REQUIRED)

```python
{
    "ticker": "str",     # Stock ticker symbol (e.g., "AAPL", "MSFT")
    "date": "str",       # Date in YYYY-MM-DD format (e.g., "2015-01-02")
    "close": "float",    # Closing price (e.g., 109.33)
    "return": "float",   # Daily return = (close_t / close_t-1) - 1 (e.g., 0.02817)
    "sector": "str",     # Sector classification (e.g., "Technology")
}
```

### Required Characteristics

**Coverage**:
- **Tickers**: Minimum 30, target 40
- **Sectors**: Minimum 5, target 8
  - Technology (AAPL, MSFT, NVDA, GOOGL, META)
  - Financials (JPM, BAC, WFC, GS, MS)
  - Healthcare (UNH, JNJ, LLY, ABBV, MRK)
  - Consumer Discretionary (AMZN, TSLA, HD, MCD, NKE)
  - Industrials (UNP, HON, CAT, BA, RTX)
  - Consumer Staples (PG, KO, PEP, WMT, COST)
  - Energy (XOM, CVX, COP, SLB, EOG)
  - Utilities (NEE, DUK, SO, D, AEP)
- **Date Range**: 2015-01-01 to 2023-12-31 (9 years, ~2,268 trading days)
- **Observations**: ~90,000 (40 tickers × 2,268 days)

**Data Quality**:
- No gaps in date series (all trading days present)
- First return for each ticker is null/NaN (no previous price)
- All other returns are valid floats
- Returns are decimal (0.02817 = 2.817% gain, not 2.817)
- Sector names are consistent across all tickers

### Example Inspection

```python
import polars as pl

df = pl.read_parquet('tests/validation/sp500_real_data.parquet')

# Check schema
assert set(df.columns) == {'ticker', 'date', 'close', 'return', 'sector'}

# Check coverage
assert df['ticker'].n_unique() >= 30
assert df['sector'].n_unique() >= 5
assert df['date'].min() <= '2016-01-01'
assert df['date'].max() >= '2023-01-01'

# Check data quality
assert df.filter(pl.col('return').is_not_nan()).height > 85000
assert df.filter(pl.col('close') <= 0).height == 0  # No negative/zero prices

print("✅ Data validation passed!")
```

---

## 🧠 What I Learned (Claude's Notes)

### Critical Insights

1. **Honesty in Documentation**:
   - I initially made unverified claims (tests passing = implementation validated)
   - Peter caught this immediately: "how can you do that with synthetic data?"
   - Lesson: Code correctness ≠ research validation
   - Must be explicit about what's proven vs what's claimed

2. **Data Source Challenges**:
   - Yahoo Finance rate limits (429 errors) are real and strict
   - Calling APIs one-by-one without delays = immediate rate limiting
   - Need multiple fallback data sources for robustness
   - Free API tiers exist but require planning (Alpha Vantage, Quandl)

3. **Validation Framework**:
   - Portfolio metrics (HHI, Leverage, Sharpe) tell different stories
   - Need to compare MULTIPLE metrics to validate claims
   - Out-of-sample testing is critical (67/33 train/test split)
   - Synthetic data shows "code works", real data shows "paper claim holds"

4. **Paper Claims Are Hypotheses**:
   - Papers claim improvements based on their data
   - Must verify on OUR data with OUR implementation
   - Possible outcomes: ✅ validated, ❌ not validated, 🤷 inconclusive
   - All three outcomes are valuable scientific results

### What I'm Trying to Achieve Once Data Is Uploaded

**Immediate Goal**: Run `validate_on_real_data.py` and get numerical results comparing the three sector risk models to baseline approaches on real S&P 500 data.

**Analysis Goal**: Determine which paper claims hold up:
- Does TwoStep really give best diversification (lowest HHI)?
- Does BlockDiagonal really give excellent Sharpe ratios?
- Does StochasticBlock really capture cross-sector correlations better?

**Documentation Goal**: Replace all "we claim" language with "we measured" language. Update executive summary with honest, quantified results.

**Decision Goal**: Based on real validation results, recommend:
- Which estimator to use in production (if any)
- Under what conditions each estimator performs well
- Whether further research/tuning is needed
- Whether any papers' claims are contradicted by our data

---

## 📁 Key Files Reference

### Data Loading Scripts
- `tests/validation/load_alphavantage.py` - Alpha Vantage API loader
- `tests/validation/load_quandl.py` - Nasdaq Data Link loader
- `tests/validation/load_yahoo_cookies.py` - Yahoo with cookies loader
- `tests/validation/load_csv_manual.py` - Manual CSV loader
- `tests/validation/README_DATA_LOADING.md` - Detailed instructions

### Validation Scripts
- `tests/validation/validate_on_real_data.py` - Main validation runner
- `tests/validation/portfolio_performance_validation.py` - Validation framework

### Documentation (Current State)
- `docs/papers/sector_risk_models/EXECUTIVE_SUMMARY.md` - Implementation status
- `docs/PHASE_4_COMPLETION_SUMMARY.md` - Phase 4 summary
- `docs/ACTUAL_VALIDATION_RESULTS.md` - Synthetic data results (to be replaced)

### Documentation (To Create in Phase 5)
- `docs/FINAL_VALIDATION_REPORT.md` - Comprehensive real data analysis

---

## ✅ Success Criteria for This Phase

**Minimum Success** (Required):
- [ ] One data loading script successfully creates sp500_real_data.parquet
- [ ] Data has required schema: [ticker, date, close, return, sector]
- [ ] Data covers 2015-2023 with 30+ tickers across 5+ sectors
- [ ] validate_on_real_data.py runs without errors
- [ ] validation_results_real_data.txt is created with results
- [ ] All files committed and pushed to remote branch

**Full Success** (Target):
- [ ] Data has 40 tickers across 8 sectors
- [ ] All 5 models complete successfully
- [ ] Clear verdict for each paper (✅ validated or ❌ not validated)
- [ ] Results are quantified with percentage improvements vs baseline
- [ ] Ready to merge and start Phase 5 (analysis and documentation)

---

## 🎬 Quick Start (TL;DR)

```bash
# 1. Try Alpha Vantage (get free key first)
export ALPHAVANTAGE_API_KEY="your_key"
python tests/validation/load_alphavantage.py

# 2. Verify data
ls -lh tests/validation/sp500_real_data.parquet

# 3. Run validation
python tests/validation/validate_on_real_data.py

# 4. Check results
cat tests/validation/validation_results_real_data.txt

# 5. Commit and push
git add tests/validation/
git commit -m "feat: Add real S&P 500 data and validation results"
git push -u origin claude/reassess-papers-status-011CV4KysG3JmBR8arH5J4dz
```

If Alpha Vantage fails, try the other loaders in order (see detailed instructions above).

Good luck! 🚀
