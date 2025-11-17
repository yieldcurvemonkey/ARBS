# ARBS Development Workflow

**Purpose**: Step-by-step actionable guide for developing, testing, and deploying code in ARBS.

**Time to Master**: 15 minutes. Reference as needed during development.

---

## Quick Start (Every Session)

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Verify environment
python test_basic_workflow.py

# 3. Set Python path for clean imports
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 4. Start development
```

---

## TDD Workflow (Test → Implement → Refactor)

### Step 1: Write the Test FIRST
Do NOT skip this step. Writing tests before implementation prevents:
- Implementing the wrong thing
- Toxic completion loops (finishing without real progress)
- Non-deterministic behavior

**For ARBS (no formal test framework)**:
```python
# Create test_my_feature.py
import sys
sys.path.insert(0, '.')

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure

# ARRANGE: Set up test data
curve_name = "USD-SOFR-1D"
tenor = "5Y"

# ACT: Create query
query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    tenor=tenor,
    curve=curve_name
)

# ASSERT: Verify behavior
assert query.tenor == "5Y", f"Expected 5Y, got {query.tenor}"
assert query.curve == curve_name, f"Expected {curve_name}, got {query.curve}"

print("✓ Test passed")
```

**Run the test**:
```bash
python test_my_feature.py
# Expected: FAILS (red)
```

### Step 2: Implement Minimal Code
Write ONLY enough code to pass the test. Resist the urge to "complete" it.

```python
# In Query/IRSwaps/IRSwapQuery.py
class IRSwapQuery:
    def __init__(self, structure, tenor, curve, ...):
        self.tenor = tenor
        self.curve = curve
        # ... rest of implementation
```

**Run the test again**:
```bash
python test_my_feature.py
# Expected: PASSES (green)
```

### Step 3: Refactor (Clean Up)
Now that tests pass, improve code quality WITHOUT changing behavior:
- Remove duplication
- Improve naming
- Extract helper functions
- Add docstrings

**After each refactor**, re-run tests:
```bash
python test_my_feature.py
# Expected: Still PASSES (green)
```

### Validation Checklist
- [ ] Test written BEFORE implementation
- [ ] Test initially failed (red)
- [ ] Implementation passes test (green)
- [ ] Code is refactored for clarity
- [ ] All tests still pass (green)

---

## Testing Standards for ARBS

### 1. Curve Build Tests
Validate curve construction against known reference:

```bash
# Quick validation (no market data needed)
python -c "
import sys
sys.path.insert(0, '.')
from definitions.IRSwaps import CURVE_DEFINITIONS
print(f'Available curves: {len(CURVE_DEFINITIONS)}')
print('Sample curves:', list(CURVE_DEFINITIONS.keys())[:3])
"
```

**What to check**:
- Curve name is in CURVE_DEFINITIONS
- Day counter matches backend (ACT/360 vs. 30/360)
- Calendar is correct (NYC holidays)
- Par rates are within 0.1-1bp of reference (Bloomberg/CME)

### 2. Structure Resolution Tests
Verify query packages resolve correctly:

```python
# Test that fly structure weights sum to 1.0
query_2y = IRSwapQuery(..., tenor="2Y")
query_3y = IRSwapQuery(..., tenor="3Y")
query_5y = IRSwapQuery(..., tenor="5Y")

fly = query_2y + query_5y - 2*query_3y
package = fly.resolve_package(pricer)

total_weight = sum(w for _, w in package)
assert abs(total_weight - 1.0) < 1e-10, f"Weights don't sum to 1.0: {total_weight}"
```

### 3. Backend Parity Tests
Compare QuantLib vs. RatesLib valuations:

```python
# Use same curve timestamp and pillar instruments
# Compare NPV and PV01 outputs
# Tolerance: ~0.1bp for par rates, ~$100 for large notionals
```

### 4. Integration Tests (Notebooks)
Run Jupyter notebooks to validate end-to-end workflows:

```bash
# Convert notebook to script (already verified to work)
jupyter nbconvert --to python month_end_irswaps_backtest.ipynb
python month_end_irswaps_backtest.py  # Should run 99%+ completion

# Expected output: portfolio MTM, P&L history, no crashes
```

### Test Verification Commands
```bash
# Validate imports work
python -c "
import sys
sys.path.insert(0, '.')
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
print('✓ Imports successful')
"

# Quick query arithmetic test
python test_basic_workflow.py

# Integration test (requires market data)
jupyter nbconvert --to python month_end_irswaps_backtest.ipynb
python month_end_irswaps_backtest.py
```

---

## Systematic Debugging (4 Phases)

Use this framework when something breaks. It's designed to prevent assumptions.

### Phase 1: ROOT CAUSE INVESTIGATION
Stop trying to fix. Find the actual problem first.

**Action Steps**:
1. Reproduce the error consistently
   ```bash
   # Run failing test multiple times
   for i in {1..3}; do python test_failing.py; done
   ```

2. Isolate the smallest case that reproduces it
   ```python
   # Strip down to minimal reproduction
   # Remove market data, external dependencies, timing
   # Reduce to 5-10 lines that fail
   ```

3. Verify your assumption with instrumentation
   ```python
   # Add print statements (not pdb) to trace execution
   print(f"DEBUG: curve_name={curve_name}, type={type(curve_name)}")
   print(f"DEBUG: CURVE_DEFINITIONS keys: {list(CURVE_DEFINITIONS.keys())[:3]}")
   ```

4. DON'T assume. Trace the actual value
   ```python
   # Wrong: "The calendar must be wrong"
   # Right: "Let me print what calendar was loaded"
   print(f"Loaded calendar: {pricer.calendar}")
   ```

**Exit Phase 1 when**: You can explain the symptom with evidence (print statements, logs).

### Phase 2: PATTERN ANALYSIS
Find ALL instances of the problem pattern, not just the one that failed.

**Action Steps**:
1. Search for related code
   ```bash
   grep -r "CURVE_DEFINITIONS" Query/
   grep -r "\.calendar" MDP/
   ```

2. List all places where this could fail
   ```python
   # If calendar mismatch causes failures, find all calendar uses:
   # - definitions/IRSwaps.py (definitions)
   # - ql_curve_definitions_map.py (QuantLib mapping)
   # - rl_curve_definitions_map.py (RatesLib mapping)
   # - backends/quantlib/ql_pricer.py (usage)
   # - backends/rateslib/RLIRSwapCurve.py (usage)
   ```

3. Check consistency across backends
   ```bash
   # QuantLib and RatesLib should agree on calendars
   grep -n "USD Government Bond" Query/IRSwaps/backends/
   grep -n "nyc" Query/IRSwaps/backends/
   ```

**Exit Phase 2 when**: You have a list of 3-5 related files that could all have the same issue.

### Phase 3: HYPOTHESIS TESTING
Form a testable hypothesis about the root cause.

**Action Steps**:
1. State your hypothesis clearly
   ```
   "Settlement date mismatch: QuantLib uses 'US Government Bond' calendar
   but RatesLib uses 'nyc'. On T+2 settlement, they differ on weekends."
   ```

2. Design a test that would prove/disprove it
   ```python
   # Test hypothesis: holidays differ between backends
   from QuantLib import UnitedStates, Calendar
   ql_cal = UnitedStates(UnitedStates.Settlement)

   from rateslib.calendars import add_currency
   rl_cal = add_currency("USD")

   # Compare holidays in 2024
   import pandas as pd
   dates = pd.date_range("2024-01-01", "2024-12-31", freq="D")
   ql_holidays = {d for d in dates if not ql_cal.isBusinessDay(d)}
   rl_holidays = {d for d in dates if not rl_cal.isBusinessDay(d)}

   if ql_holidays != rl_holidays:
       print(f"Calendars differ: {ql_holidays - rl_holidays}")
       return HYPOTHESIS_CONFIRMED
   ```

3. Run the test
   ```bash
   python test_hypothesis.py
   ```

**Exit Phase 3 when**: Hypothesis is confirmed or disproven with evidence.

### Phase 4: IMPLEMENTATION
Only now do you fix the code.

**Action Steps**:
1. Apply minimal fix (addresses root cause, nothing more)
   ```python
   # If QuantLib/RatesLib calendars differ:
   # FIX: Update definitions/IRSwaps.py to use consistent calendar string
   CURVE_DEFINITIONS["USD-SOFR-1D"] = {
       "calendar": "US Government Bond",  # Use QuantLib name (primary backend)
       ...
   }
   # Update RatesLib backend to translate: "US Government Bond" → "nyc"
   ```

2. Verify original failing test now passes
   ```bash
   python test_failing.py
   ```

3. Verify you didn't break anything else
   ```bash
   python test_basic_workflow.py
   ```

4. Run integration tests
   ```bash
   jupyter nbconvert --to python month_end_irswaps_backtest.ipynb
   python month_end_irswaps_backtest.py
   ```

**Critical Rule**: If Phase 4 doesn't pass Phase 3's test, go back to Phase 3. Do NOT guess.

---

## Git Workflow (Commit Frequency, Push Immediately)

### Principle
Small, frequent commits = easy to debug later. Large batches = impossible to bisect.

### The Rhythm

**Every 15-30 minutes of development, commit**:
```bash
# 1. Check what changed
git status

# 2. Review changes (ALWAYS review before committing)
git diff

# 3. Stage relevant files
git add Query/IRSwaps/adapter.py definitions/IRSwaps.py

# 4. Commit with descriptive message
git commit -m "Fix: IRSwap calendar alignment between QuantLib and RatesLib"

# 5. Push immediately (no batching!)
git push origin main
```

### Commit Message Format
```
<type>: <subject>

<body (optional)>
```

**Types**:
- `feat`: New feature (new curve, new structure type)
- `fix`: Bug fix (calendar mismatch, missing fixings)
- `refactor`: Code reorganization (no behavior change)
- `test`: New test or improved test coverage
- `docs`: Documentation updates
- `chore`: Dependencies, minor fixes

**Examples**:
```
feat: Add USD-SONIA curve source from SDR_INTRADAY

fix: Calendar mismatch between QuantLib and RatesLib backends

Symptoms: Settlement dates differ by 1-2 days on weekends
Root cause: "US Government Bond" vs. "nyc" calendar naming
Solution: Translate calendar names in RatesLib adapter

refactor: Extract curve builder into separate module

test: Add calendar parity tests for all backends
```

### Commit Checklist
- [ ] Changes are minimal (one concept per commit)
- [ ] Tests pass before committing
- [ ] Commit message is clear and references problem
- [ ] Pushed to origin immediately (no local commits)
- [ ] No large files committed (data, notebooks, logs)

---

## Code Review Process

### Self-Review (Before Push)

**Checklist**:
```bash
# 1. Run all tests
python test_basic_workflow.py
python test_my_feature.py

# 2. Check for obvious issues
git diff HEAD~1

# Questions to ask yourself:
# - Did I add TODO comments? (No - complete the work or revert)
# - Did I leave debug print statements? (No - remove them)
# - Does this match the existing code style? (Yes - check similar functions)
# - Is this the minimal change? (Yes - no over-engineering)
# - Would this pass review 6 months from now? (Yes - clear, documented)
```

### Peer Review (If Applicable)

When working with others:
1. Push to feature branch
2. Create PR with:
   - Description of what changed and why
   - Reference to issue/ticket
   - Steps to test
3. Wait for review before merging

**For solo work**: Use self-review checklist above.

---

## Learning and Memory Management

### Recording Findings

When you discover something useful:

1. **Add to CLAUDE.md** (if project-wide)
   ```markdown
   ### Issue: Calendar Mismatch (Found 2024-11-17)

   Problem: QuantLib uses "US Government Bond", RatesLib uses "nyc"

   Solution: Map in RatesLib adapter at runtime

   Files affected: Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py
   ```

2. **Add to docstrings** (if code-specific)
   ```python
   def map_calendar_name(ql_name: str) -> str:
       """Map QuantLib calendar names to RatesLib equivalents.

       QuantLib uses "US Government Bond" for USD settlement calendar.
       RatesLib uses "nyc". This function translates between them.

       Note: Do NOT use "US" calendar, it has different holiday rules.
       """
   ```

3. **Update definitions** (if operational knowledge)
   ```python
   CURVE_DEFINITIONS = {
       "USD-SOFR-1D": {
           # NOTE: Calendar name must match QuantLib naming convention
           # "nyc" will be translated to "US Government Bond" by adapter
           "calendar": "US Government Bond",
           ...
       }
   }
   ```

### Decision Journal

Keep track of WHY decisions were made (helps future debugging):

```python
# In comments near important code:

# DECISION: Use ZODB caching for curve builds
# RATIONALE: Curves are expensive (30+ QL bootstrap iterations)
# and rarely change. Caching reduces backtest from 2h to 5min.
# TRADE-OFF: Adds complexity, requires cache invalidation on curve changes.
# INVALIDATION: Bump namespace in ZODBCacheMixin.py after recipe changes.

# See: Caching/ZODBCacheMixin.py, definitions/IRSwaps.py
```

### Quick Reference Checklist

When stuck, check these in order:

1. [ ] Is this curve in `definitions/IRSwaps.py`?
2. [ ] Do QuantLib and RatesLib agree on calendars?
3. [ ] Is the cache stale? (Try clearing cache keys)
4. [ ] Are fixings missing for this date range?
5. [ ] Is the day counter correct (ACT/360 vs. 30/360)?
6. [ ] Does this test pass in isolation vs. in backtest?

---

## Expand-Then-Compress Coding (For Complex Features)

Use this when building something with multiple possible implementations.

### Phase 1: EXPAND (Try 3-5 Approaches)

Example: Adding a new curve source

**Approach 1**: Direct QuantLib bootstrap
```python
# Pros: Simple, known to work
# Cons: Slow for large time grids
```

**Approach 2**: Pre-built RL recipes
```python
# Pros: Fast, community tested
# Cons: Less flexible, different interface
```

**Approach 3**: Hybrid (QL for calibration, RL for valuation)
```python
# Pros: Best of both
# Cons: Complex data conversion
```

**Interrupt at 5-10 minutes**: Which approach is toxic (endless complexity)?

### Phase 2: COMPRESS (Pick Winner)

1. Identify what's common across all approaches (interface)
2. Keep that, kill the rest
3. Document the choice and why

```python
# Use Approach 2 (RatesLib recipes) as primary
# Rationale: 50x faster, sufficient accuracy, large community
# Fallback: Approach 1 (QL) if RL recipes not available
# See: MDP/IRSwaps/IRSwapsMDP.py source routing
```

---

## Anti-Patterns (Don't Do These)

1. **Toxic Completion**: "I successfully analyzed..." without code
   - Fix: Always end development with working code or explicit rollback

2. **Research Spirals**: Endless investigation without implementation
   - Fix: Set 10-minute interrupt checkpoints. Kill branches that aren't converging.

3. **Ignored Test Failures**: Pushing code that doesn't pass tests
   - Fix: ALL tests must pass before committing. No exceptions.

4. **Batch Commits**: Large changes bundled together
   - Fix: Commit every 15-30 minutes. Should be easy to describe in one sentence.

5. **TODO Comments Left in Code**: Planning in code instead of doing it
   - Fix: Either complete the work or revert. No TODOs.

6. **Cache Invalidation After Changes**: Stale cache causing mysterious failures
   - Fix: ALWAYS bump cache namespace after curve recipe changes

7. **Assumption-Based Debugging**: "It must be X" without evidence
   - Fix: Use Phase 1-4 systematic debugging. Verify with print statements.

---

## Quick Command Reference

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Develop
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python test_basic_workflow.py         # Quick validation
python test_my_feature.py             # Feature test
git diff                              # Review changes

# Commit
git status
git add <files>
git commit -m "type: description"
git push origin main

# Debug
python -c "print(CURVE_DEFINITIONS.keys())"
jupyter nbconvert --to python notebook.ipynb
python notebook.py

# Clean up
rm -rf __pycache__
rm -f *.pyc
```

---

## Summary

1. **TDD**: Test first, implement minimal, refactor clean
2. **Testing**: Validate curves, structures, backends, integration
3. **Debugging**: 4 phases - investigate, analyze, hypothesize, fix
4. **Git**: Commit every 15-30 minutes, push immediately
5. **Code Review**: Self-review, check for TODOs and incomplete work
6. **Memory**: Document findings, record decisions, update references
7. **Complex Features**: Expand then compress - try approaches, pick winner

**Golden Rule**: Small, frequent, verified commits. Never batch, never assume, always test.
