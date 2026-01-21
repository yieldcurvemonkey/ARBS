# SDR Lifecycle State Machine Refactor - Migration Guide

## Overview

The lifecycle replay system has been refactored to properly separate **market state** from **regulatory state**. This fixes critical bugs in volume counting, package detection, and market analytics caused by late-arriving CORR and MODI events.

## What Changed

### Core Problem Fixed

**Before**: CORR and MODI (Amendment=False) events would overwrite `current_state` hours after execution, corrupting "what the market saw" at trade time.

**After**:
- `inception_state` is immutable and captures what was disseminated at trade time
- `current_state` reflects the final regulatory state after all updates
- All lifecycle events are tracked in separate audit trails

### New Fields in `ResolvedTrade`

```python
@dataclass
class ResolvedTrade:
    # ... existing fields ...

    # NEW: Audit trails
    amendments: List[Dict[str, Any]]  # MODI with Amendment=True (market events)
    corrections: List[Dict[str, Any]]  # CORR events with timestamps
    updates: List[Dict[str, Any]]      # MODI with Amendment=False (late data fills)

    # NEW: Novation tracking
    prior_uti: Optional[str]           # For NEWT-NOVA → original trade linkage
    event_type: Optional[str]          # "TRAD" or "NOVA"

    # NEW: Helper properties
    @property
    def is_market_volume(self) -> bool

    @property
    def has_amendments(self) -> bool

    @property
    def has_corrections(self) -> bool
```

### Volume Counting Rules

```python
# COUNT as market volume
if resolved_trade.is_market_volume:
    # This is NEWT-TRAD
    volume = resolved_trade.inception_notional

# DO NOT COUNT
# - NEWT-NOVA (transferred risk, not new)
# - MODI-TRAD with Amendment=False (late data)
# - CORR (error corrections)
```

### Event Type Classification

| Action | Event Type | Amendment | Disseminated? | Market Event? | Count Volume? |
|--------|-----------|-----------|---------------|---------------|---------------|
| NEWT | TRAD | - | YES | YES | ✅ YES |
| MODI | TRAD | True | YES | YES (renegotiation) | ❌ NO (use inception) |
| MODI | TRAD | False | NO | NO (late data fill) | ❌ NO |
| CORR | - | - | YES | NO (fixes error) | ❌ NO |
| TERM | NOVA | - | YES | YES | ❌ NO (termination) |
| MODI | NOVA | True | YES | YES (partial novation) | ❌ NO |
| NEWT | NOVA | - | YES | NO (transferred risk) | ❌ NO |

## Migration Checklist

### ✅ Compatible Code (No Changes Needed)

If your code uses:
- `resolved_trade.current_state` for regulatory reporting
- `resolved_trade.inception_state` for volume calculation
- `resolved_trade.is_active` for status checks
- `resolved_trade.is_new_trade` for filtering NEWT events

**No changes required** - these fields work exactly as before.

### ⚠️ Code That May Need Updates

#### 1. Volume Calculation

**Before:**
```python
# ❌ WRONG: Uses current_state (corrupted by late CORR)
volume = sum(t.current_notional for t in trades if t.is_new_trade)
```

**After:**
```python
# ✅ CORRECT: Uses inception_state + market volume filter
volume = sum(t.inception_notional for t in trades if t.is_market_volume)
```

#### 2. Package Detection

**Before:**
```python
# ❌ WRONG: Uses current_state (strike may have been corrected)
if abs(trade.current_state['Strike Price'] - 4.25) < 0.001:
    # Package detection logic
```

**After:**
```python
# ✅ CORRECT: Uses inception_state (what market saw)
if abs(trade.inception_state['Strike Price'] - 4.25) < 0.001:
    # Package detection logic
```

#### 3. Audit Trail Access

**New functionality:**
```python
# Check if trade had corrections
if resolved_trade.has_corrections:
    for corr in resolved_trade.corrections:
        timestamp = corr['timestamp']
        data = corr['data']
        print(f"Correction at {timestamp}: {data['Strike Price']}")

# Check if trade had amendments (market events)
if resolved_trade.has_amendments:
    for amend in resolved_trade.amendments:
        timestamp = amend['timestamp']
        data = amend['data']
        print(f"Amendment at {timestamp}: {data['Notional amount-Leg 1']}")
```

#### 4. Novation Tracking

**New functionality:**
```python
# Track novation chains
if resolved_trade.event_type == "NOVA" and resolved_trade.prior_uti:
    original_trade = find_trade_by_uti(resolved_trade.prior_uti)
    print(f"Trade {resolved_trade.synthetic_uti} novated from {original_trade.synthetic_uti}")
```

## Key Insights

### CORR Behavior Change

**Before (BUG):**
```python
# CORR overwrote EVERYTHING in current_state
# This corrupted inception_state for analytics
state = _update_state(state, row_data, overwrite=True)
```

**After (FIXED):**
```python
# CORR updates current_state but is logged separately
# inception_state remains immutable
resolved.corrections.append({
    "timestamp": timestamp,
    "data": row_data.copy(),
})
state = _update_state(state, row_data, overwrite=True)
```

### Amendment vs Update Distinction

**Amendment (Amendment=True)**: Market event, disseminated, represents renegotiation
- Overwrites economics fields in `current_state`
- Logged in `amendments` list
- Does NOT mutate `inception_state`

**Update (Amendment=False)**: Late data fill, not disseminated, no market event
- Only fills null fields in `current_state`
- Logged in `updates` list
- Does NOT mutate `inception_state`

### Volume Stability Guarantee

```python
# Volume at T+1h and T+24h MUST be identical for T0 trades
# Even if CORR arrives between T+1h and T+24h

# At T+1h (before CORR)
volume_t1h = sum(t.inception_notional for t in trades if t.is_market_volume)

# At T+24h (after CORR)
volume_t24h = sum(t.inception_notional for t in trades if t.is_market_volume)

assert volume_t1h == volume_t24h  # ✅ PASSES NOW
```

## API Summary

### Use `inception_state` for:
- ✅ Volume calculation
- ✅ Package detection (clustering by strike, maturity, etc.)
- ✅ Market analytics ("what did the market see?")
- ✅ Pricing analytics at trade time
- ✅ Historical time-series (T+1h, T+1d snapshots)

### Use `current_state` for:
- ✅ Regulatory reporting (final corrected state)
- ✅ Trade validation (ensure all required fields filled)
- ✅ Current position reconciliation
- ✅ Error detection (compare inception vs current)

### Use audit trails for:
- ✅ Compliance monitoring (track all changes)
- ✅ Data quality debugging
- ✅ Amendment analysis (market renegotiations)
- ✅ Correction pattern analysis

## Testing

All existing tests pass without modification. New tests validate:

1. **Test 1**: NEWT → MODI (update) → CORR
   - `inception_state` unchanged by CORR
   - `current_state` reflects CORR

2. **Test 2**: Amendment (market event)
   - `amendments` list populated
   - Economics fields overwritten in `current_state`

3. **Test 3**: Full novation
   - `prior_uti` tracks original trade
   - `is_market_volume=False` for NEWT-NOVA

4. **Test 4**: Partial novation
   - `amendments` tracks notional reduction
   - New trade links back via `prior_uti`

## Questions & Answers

### Q: Should CORR affect `current_state` or only audit trail?

**A**: CORR affects both:
- Updates `current_state` (for regulatory compliance)
- Logged in `corrections` audit trail (for tracking)
- Does NOT affect `inception_state` (for market analytics)

### Q: How to expose inception vs current state in API?

**A**: Use the `ResolvedTrade` properties:
```python
# Market analytics endpoint
{
    "volume": trade.inception_notional,
    "market_event": trade.is_market_volume,
}

# Regulatory reporting endpoint
{
    "notional": trade.current_notional,
    "active": trade.is_active,
}
```

### Q: Retention policy for audit trail?

**A**: Same as `history` field - retained for the lifecycle of the `ResolvedTrade` object. Consider:
- Archiving to database for long-term audit
- Compressing older entries
- Separate retention for regulatory vs analytics

## Performance Impact

**Minimal**:
- New lists (`amendments`, `corrections`, `updates`) are append-only
- No additional iterations over messages
- `is_market_volume` property is O(1) lookup
- Memory overhead: ~3 extra lists per trade (typically 0-5 entries each)

## Breaking Changes

**None**: All existing code continues to work. New fields are:
- Optional (default to `None` or empty list)
- Backward compatible
- Additive only (no removals)

## Rollout Plan

1. ✅ **Phase 1**: Deploy new `lifecycle.py` (backward compatible)
2. **Phase 2**: Update volume calculation to use `is_market_volume`
3. **Phase 3**: Update package detection to use `inception_state`
4. **Phase 4**: Add audit trail monitoring dashboards
5. **Phase 5**: Validate volume stability in production

## Support

For questions or issues:
1. Check test cases in `tests/test_sdr_trade_events.py::TestDualStateModel`
2. Review this migration guide
3. File issue with `[LIFECYCLE]` prefix
