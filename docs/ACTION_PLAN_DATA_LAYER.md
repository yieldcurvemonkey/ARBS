# Data Layer Action Plan

**Date**: 2025-11-14
**Based On**: Parallel codebase assessment (4 agents)
**Status**: Awaiting Peter's direction

---

## TL;DR

**The architecture is already correct.** ✅

- Backtest never loads data directly ✅
- Data loaders are separate CLI scripts ✅
- Adapters properly use MDP interface ✅
- SQLiteCache implemented and tested ✅

**No critical fixes needed.** The question is: What optional enhancements do we want?

---

## What EXISTS and Works

| Component | Status | Action |
|-----------|--------|--------|
| 8 data loader scripts | ✅ Working | None needed |
| 4 Market Data Providers (ZODB) | ✅ Working | None needed |
| FuturesAdapter | ✅ Exemplary | None needed |
| EquityAdapter | ✅ Exemplary | None needed |
| Backtest classes | ✅ Correct | None needed |
| SQLiteCache | ✅ Implemented | None needed |
| Architecture docs | ✅ Cleaned up | None needed |

---

## What DOESN'T Exist (Optional Enhancements)

### 1. CachedMarketDataProvider (SQLite-backed MDP)

**Purpose**: MDP that reads from SQLiteCache (read-only)

**Pros**:
- Unified caching (all sources → SQLite)
- Strict separation (MDP can't fetch)
- Matches documented architecture

**Cons**:
- Validation scripts don't need it (use parquet)
- Production uses ZODB-backed MDPs (already working)
- Adds complexity for minimal benefit

**Effort**: 2 hours (implement + test)

**Peter's Decision**: ❓ Build it or skip it?

---

### 2. Enhanced AlphaVantage Loader

**Purpose**: Improve existing `load_alphavantage.py`

**Enhancements**:
- Smart caching (check before fetch)
- Incremental updates (only new dates)
- CLI arguments (--update, --force-refresh)
- Progress reporting
- Rate limiter utility

**Current State**: Basic loader works, just not fancy

**Effort**: 3 hours (enhance + rate limiter + test)

**Peter's Decision**: ❓ Enhance or keep simple?

---

### 3. Workflow Examples

**Purpose**: Show proper 2-step workflow (load → backtest)

**Content**:
- Step 1: Run data loader
- Step 2: Run backtest with cached data
- Shows proper separation

**Current State**: Examples exist but don't demonstrate pattern clearly

**Effort**: 1 hour (write example + docs)

**Peter's Decision**: ❓ Add examples or skip?

---

### 4. Read-Only Mode for YahooFinanceMDP

**Purpose**: Prevent API calls during backtest

**Issue**: YahooFinanceMDP can fetch on cache miss (soft violation)

**Options**:
- **A**: Add strict mode (error on cache miss)
- **B**: Document expected behavior
- **C**: Accept current behavior (cache-first is good enough)

**Effort**: 2 hours for option A, 0 hours for B/C

**Peter's Decision**: ❓ Which option?

---

## Recommended Next Steps

### Option 1: Validate & Done ✅ (Recommended)

**Time**: 1 hour

**Steps**:
1. Run existing validation workflow (load + validate)
2. Run existing backtest examples
3. Confirm everything works
4. Document: "Architecture is correct, no changes needed"
5. Move to next priority

**Rationale**: Architecture is correct, don't fix what isn't broken

---

### Option 2: Build All Enhancements 🔨

**Time**: 8 hours

**Steps**:
1. CachedMarketDataProvider (2h)
2. Enhanced AlphaVantage loader (3h)
3. Workflow examples (1h)
4. Read-only MDP mode (2h)

**Rationale**: Make everything perfect and documented

---

### Option 3: Cherry-Pick Enhancements 🍒

**Time**: Variable (2-5 hours)

**Steps**:
1. Pick highest value items (Peter decides)
2. Implement chosen enhancements
3. Skip low-value items

**Rationale**: Balance polish vs progress

---

## Questions for Peter

1. **Do we need to build anything?**
   - Architecture is correct
   - Components work
   - What's the goal?

2. **If yes, what's the priority?**
   - CachedMarketDataProvider?
   - Enhanced loaders?
   - Workflow examples?
   - Read-only mode?

3. **Or should we validate and move on?**
   - Run tests
   - Confirm it works
   - Focus on next phase (Bloomberg? CME? Strategy implementation?)

---

## My Recommendation

**Option 1: Validate & Move On** ✅

**Reasoning**:
1. Architecture is already correct
2. Components are working
3. No critical gaps
4. Enhancements are polish, not functionality
5. Time better spent on new features (Bloomberg, CME, strategy work)

**Validation Steps**:
```bash
# 1. Test data loading
export ALPHAVANTAGE_API_KEY="QLGCJCCK8X4ZY6VC"
python tests/validation/load_alphavantage.py

# 2. Test validation
python tests/validation/validate_on_real_data.py

# 3. Test backtest examples
python examples/run_minimal_backtest.py

# 4. Confirm: Everything works ✅
```

**Then**: Move to next priority (what's more important - Bloomberg integration? Strategy development? Performance optimization?)

---

## If Peter Wants Enhancements

**Priority Order** (my suggestion):

1. **Workflow Examples** (1h) - High educational value, low effort
2. **Enhanced AlphaVantage Loader** (3h) - Nice QoL, shows best practices
3. **CachedMarketDataProvider** (2h) - Completes the picture, matches docs
4. **Read-Only MDP Mode** (2h) - Strict enforcement, probably unnecessary

**Rationale**: Start with high value/low effort, add others if time permits

---

## Next Action

**Waiting for Peter's direction**:

- [ ] Validate current setup and move on? (Option 1)
- [ ] Build all enhancements? (Option 2)
- [ ] Build specific enhancements? (Option 3 - which ones?)
- [ ] Something else entirely?

---

## Files to Review

1. **Full Assessment**: `docs/CODEBASE_ASSESSMENT_DATA_LAYER.md`
2. **Architecture Guide**: `docs/DATA_LAYER_ARCHITECTURE.md`
3. **Implementation Plan**: `docs/ALPHAVANTAGE_DATA_LAYER_PLAN_CORRECTED.md`
4. **This Action Plan**: `docs/ACTION_PLAN_DATA_LAYER.md`

All committed and pushed to: `claude/next-phase-01EqwdS3CUR9K1dEnuN8VeCt`
