# Orthogonal Task Breakdown: AlphaVantage Data Pipeline

**Created**: 2025-11-14
**Status**: Ready for parallel execution
**Branch**: claude/next-phase-01EqwdS3CUR9K1dEnuN8VeCt

## Current State

✅ **Complete**: SQLite Cache Infrastructure (Stream 1)
- SQLiteCache.py (480 lines, full CRUD)
- 21 comprehensive tests
- Schema migrations ready

❌ **Remaining**: API Client, Data Provider, Adapters, Examples, Integration

## Orthogonal Task Groups

### Group A: Independent API Components (ALL PARALLEL)

**Task A1: Rate Limiter**
- **Time**: 10 minutes
- **Creates**: `Data/Providers/RateLimiter.py`
- **Dependencies**: None
- **Mocks**: N/A (pure logic)
- **Success**:
  - `RateLimiter` class with sliding window algorithm
  - `acquire()` method blocks until request allowed
  - `can_make_request()` returns bool
  - `wait_time()` returns seconds to wait
  - Tracks requests per minute (5) and per day (25)
  - No TODOs
  - Pure Python, no external API calls

**Task A2: AlphaVantage Client**
- **Time**: 10 minutes
- **Creates**: `Data/Providers/AlphaVantageClient.py`
- **Dependencies**: None (mocks RateLimiter initially)
- **Mocks**: RateLimiter (hardcode waits for now)
- **Success**:
  - `AlphaVantageClient` class
  - `get_daily_adjusted(symbol)` - returns DataFrame
  - `get_intraday(symbol, interval)` - returns DataFrame
  - `get_forex_daily(from, to)` - returns DataFrame
  - Uses requests library for HTTP
  - Parses JSON to Polars DataFrame
  - Error handling for bad symbols, rate limits
  - No TODOs

**Task A3: Rate Limiter Tests**
- **Time**: 10 minutes
- **Creates**: `tests/unit/data/test_rate_limiter.py`
- **Dependencies**: None (Task A1 runs parallel)
- **Mocks**: time.time() for deterministic tests
- **Success**:
  - Test sliding window logic
  - Test minute limits (5 requests)
  - Test daily limits (25 requests)
  - Test wait time calculation
  - Test concurrent request handling
  - 10+ tests covering edge cases
  - All tests pass

**Task A4: AlphaVantage Client Tests**
- **Time**: 10 minutes
- **Creates**: `tests/unit/data/test_alphavantage_client.py`
- **Dependencies**: None (Task A2 runs parallel)
- **Mocks**: HTTP responses (responses library)
- **Success**:
  - Test get_daily_adjusted() parsing
  - Test get_intraday() parsing
  - Test get_forex_daily() parsing
  - Test API error handling (404, 500, rate limit)
  - Test invalid symbol handling
  - Mock all HTTP calls (no real API usage)
  - 10+ tests
  - All tests pass

### Group B: Data Provider (Depends on Group A, but can START with mocks)

**Task B1: Data Provider**
- **Time**: 15 minutes
- **Creates**: `Data/DataProvider.py`
- **Dependencies**: None initially (mocks cache + API)
- **Mocks**: SQLiteCache (simple dict), AlphaVantageClient (fixed data)
- **Success**:
  - `DataProvider` class
  - `get_equity_prices(symbol, start, end)` - cache-first logic
  - `get_forex_rates(from, to, start, end)` - cache-first logic
  - `get_futures_prices(contract, start, end)` - cache-first logic
  - Algorithm: check cache → fetch API if needed → update cache
  - Force refresh option
  - No TODOs
  - Has interface for real cache/API (will wire later)

**Task B2: Data Provider Tests**
- **Time**: 10 minutes
- **Creates**: `tests/unit/data/test_data_provider.py`
- **Dependencies**: None (Task B1 runs parallel)
- **Mocks**: SQLiteCache + AlphaVantageClient
- **Success**:
  - Test cache hit (no API call)
  - Test cache miss (API called, cache updated)
  - Test partial cache (API for missing dates)
  - Test stale cache (force refresh)
  - Test rate limit handling
  - All mocked (no real cache or API)
  - 10+ tests
  - All tests pass

### Group C: Adapter Layer (Can run PARALLEL to A & B)

**Task C1: Equity Adapter**
- **Time**: 10 minutes
- **Creates**: `Adapter/EquityAdapter.py`
- **Dependencies**: None (mocks DataProvider)
- **Mocks**: DataProvider (returns fixed DataFrame)
- **Success**:
  - `EquityAdapter` class
  - `convert(symbols, as_of, lookback)` - returns standardized DataFrame
  - `get_returns(symbols, start, end)` - returns returns matrix
  - Output format: [date, ticker, return] for Backtest
  - Handles missing data gracefully
  - No TODOs
  - Interface ready for real DataProvider

**Task C2: Equity Adapter Tests**
- **Time**: 10 minutes
- **Creates**: `tests/unit/adapter/test_equity_adapter.py`
- **Dependencies**: None (Task C1 runs parallel)
- **Mocks**: DataProvider
- **Success**:
  - Test conversion to standard format
  - Test returns calculation (log returns)
  - Test multiple symbols
  - Test missing data handling
  - Test date alignment
  - All mocked
  - 8+ tests
  - All tests pass

### Group D: Documentation (COMPLETELY INDEPENDENT)

**Task D1: Setup Guide**
- **Time**: 10 minutes
- **Creates**: `docs/DATA_PIPELINE_SETUP.md`
- **Dependencies**: None
- **Success**:
  - How to get AlphaVantage API key
  - Setting up SQLite database
  - First-time data fetch walkthrough
  - Cache management best practices
  - Rate limit strategies
  - Troubleshooting common issues
  - No TODOs

**Task D2: API Reference**
- **Time**: 10 minutes
- **Creates**: `docs/DATA_PROVIDER_API.md`
- **Dependencies**: None
- **Success**:
  - Complete API reference for DataProvider
  - Caching strategy explanation
  - Usage examples for equity, futures, forex
  - Cache coverage API
  - Staleness detection API
  - Error handling guide
  - No TODOs

**Task D3: Example Script**
- **Time**: 10 minutes
- **Creates**: `examples/run_backtest_with_real_data.py`
- **Dependencies**: None (will use API when available)
- **Success**:
  - Complete working example
  - Shows setup (cache + API client + data provider)
  - Fetches real equity data (AAPL, MSFT, GOOGL)
  - Runs backtest with MomentumSignal
  - Shows results (Sharpe, returns, IC)
  - Demonstrates cache benefits (first vs second run)
  - Comments explain rate limiting
  - No TODOs

---

## Reserve Tasks (Run AFTER groups complete)

**Reserve R1: Wire Real Components**
- **Time**: 5 minutes
- **Depends**: A1, A2, B1
- **Action**: Wire DataProvider with real SQLiteCache + AlphaVantageClient
- **Changes**:
  - DataProvider.__init__ accepts real cache + API
  - Remove mock implementations
  - Update tests to use real cache (temp DB)

**Reserve R2: Wire Adapter**
- **Time**: 5 minutes
- **Depends**: B1, C1, R1
- **Action**: Wire EquityAdapter with real DataProvider
- **Changes**:
  - EquityAdapter accepts real DataProvider
  - Remove mocks
  - Update tests

**Reserve R3: Integration Tests**
- **Time**: 10 minutes
- **Depends**: R1, R2
- **Creates**: `tests/integration/test_data_provider_live.py`
- **Action**: Test with real AlphaVantage API
- **Success**:
  - Mark with @pytest.mark.integration
  - Use real API key from environment
  - Test 1-2 symbols (respect rate limits)
  - Verify caching works end-to-end
  - Test multiple requests hit cache
  - All tests pass

**Reserve R4: Update FuturesAdapter**
- **Time**: 5 minutes
- **Depends**: R1
- **Action**: Add optional data_provider parameter to FuturesAdapter
- **Changes**:
  - FuturesAdapter(mdp, data_provider=None)
  - If data_provider: use real data
  - If None: use mock (backwards compatible)
  - Update tests

---

## Execution Strategy

### Phase 1: Launch All Orthogonal Tasks (Parallel)
```bash
# All can start simultaneously - no dependencies

Agent 1 → Task A1 (RateLimiter.py)
Agent 2 → Task A2 (AlphaVantageClient.py)
Agent 3 → Task A3 (test_rate_limiter.py)
Agent 4 → Task A4 (test_alphavantage_client.py)
Agent 5 → Task B1 (DataProvider.py with mocks)
Agent 6 → Task B2 (test_data_provider.py)
Agent 7 → Task C1 (EquityAdapter.py with mocks)
Agent 8 → Task C2 (test_equity_adapter.py)
Agent 9 → Task D1 (DATA_PIPELINE_SETUP.md)
Agent 10 → Task D2 (DATA_PROVIDER_API.md)
Agent 11 → Task D3 (run_backtest_with_real_data.py)
```

**Expected time**: 15 minutes (longest task duration)
**vs Sequential**: 115 minutes (sum of all tasks)

### Phase 2: Reserve Tasks (Sequential)
```bash
R1 → Wire real components (5 min)
R2 → Wire adapter (5 min)
R3 → Integration tests (10 min)
R4 → Update FuturesAdapter (5 min)
```

**Expected time**: 25 minutes

### Phase 3: Validation
- Run full test suite (unit + integration)
- Verify example works with real API
- Check rate limiting
- Commit and push

**Expected time**: 10 minutes

---

## Total Timeline

- Phase 1 (Parallel): 15 minutes
- Phase 2 (Reserve): 25 minutes
- Phase 3 (Validation): 10 minutes

**Total**: ~50 minutes
**vs Sequential**: ~150 minutes

**Speedup**: 3x faster with parallelization

---

## Orthogonality Verification

✅ **Group A tasks**: All create different files, no dependencies
✅ **Group B tasks**: Mock dependencies, create different files
✅ **Group C tasks**: Mock dependencies, create different files
✅ **Group D tasks**: Pure documentation, no code dependencies

✅ **No file conflicts**: Each task creates unique files
✅ **No shared state**: All use mocks initially
✅ **True parallelism**: Can run all 11 tasks simultaneously

---

## Success Criteria

**Per Task**:
- [ ] Files created as specified
- [ ] No TODO comments in code
- [ ] Actual implementation (not stubs)
- [ ] Tests pass (if test task)
- [ ] Follows project style guide

**Overall**:
- [ ] All 11 orthogonal tasks complete
- [ ] All 4 reserve tasks complete
- [ ] Full test suite passes (unit + integration)
- [ ] Example runs successfully
- [ ] Documentation is complete
- [ ] Rate limiting works
- [ ] Caching reduces API calls by >95%

---

## Agent Assignments

Using Task tool with `subagent_type="general-purpose"`:

```python
# Launch all in single message for true parallelism
tasks = [
    ("Task A1: RateLimiter", "task_a1_prompt"),
    ("Task A2: AlphaVantage Client", "task_a2_prompt"),
    # ... etc for all 11 tasks
]

# Single message with 11 Task tool calls
```

---

## Risk Mitigation

**Risk**: Mock interfaces don't match real implementations
- **Mitigation**: Define clear interfaces upfront
- **Mitigation**: Reserve tasks validate integration

**Risk**: API rate limit exhaustion during integration tests
- **Mitigation**: Mark integration tests with @pytest.mark.integration
- **Mitigation**: Limit to 1-2 symbols

**Risk**: Tasks finish at different times
- **Mitigation**: Reserve tasks wait for all groups
- **Mitigation**: Use git to track completion

**Risk**: Agent failures or timeouts
- **Mitigation**: Each task is <15 minutes
- **Mitigation**: Can restart individual failed tasks

---

## Next Steps

1. ✅ Commit current work (SQLiteCache)
2. ✅ Push to remote
3. ✅ Create orthogonal task breakdown (this file)
4. → Review with Peter
5. → Launch 11 parallel agents
6. → Execute reserve tasks
7. → Validate and commit
