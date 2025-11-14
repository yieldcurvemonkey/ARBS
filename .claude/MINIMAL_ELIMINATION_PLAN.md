# Minimal* Elimination Plan - Orthogonal Task Breakdown

**Created**: 2025-11-14
**Urgency**: IMMEDIATE - Execute NOW
**Goal**: Remove ALL instances of "minimal" anything from codebase

---

## Core Principle

**MinimalBacktest was a temporary MVP class. Generic Backtest is the production implementation.**

ALL code should use `Backtest` (generic), not `MinimalBacktest`.

---

## Affected Files (49 total)

Found by: `grep -r "MinimalBacktest\|from.*Minimal\|import.*Minimal"`

### Categories

1. **Examples** (1 file):
   - `examples/run_minimal_backtest.py`

2. **Tests** (2 files):
   - `tests/unit/backtest/test_minimal_backtest.py`
   - `tests/unit/backtest/test_backtest.py` (may reference minimal)
   - `tests/integration/test_multi_signal_strategy.py`

3. **Implementation** (2 files):
   - `Backtest/MinimalBacktest.py` (DELETE)
   - `Backtest/__init__.py` (remove export)

4. **Notebooks** (10 files):
   - `notebooks/01_getting_started.ipynb`
   - `notebooks/02_strategy_comparison.ipynb`
   - `notebooks/03_parameter_tuning.ipynb`
   - `notebooks/04_results_analysis.ipynb`
   - `notebooks/05_cross_asset_integration.ipynb`
   - `notebooks/06_carry_strategy_complete.ipynb`
   - `notebooks/07_momentum_strategy_complete.ipynb`
   - `notebooks/10_vol_arbitrage_strategy.ipynb`
   - `notebooks/12_risk_parity_strategy.ipynb`

5. **Documentation** (34 files):
   - `CLAUDE.md` (CRITICAL - update MVP philosophy)
   - `docs/*.md` (various references)

---

## Orthogonal Task Breakdown

### Task 1: Fix Examples Directory

**Files**: 1 file
- `examples/run_minimal_backtest.py`

**Action**:
1. Rename to `examples/run_backtest.py`
2. Change `from Backtest.MinimalBacktest import MinimalBacktest` → `from Backtest.Backtest import Backtest`
3. Change `MinimalBacktest(...)` → `Backtest(...)`
4. Update all docstrings/comments

**Success**: Example runs with Backtest

**Orthogonality**: Only touches examples/ directory

---

### Task 2: Fix Unit Tests

**Files**: 2 files
- `tests/unit/backtest/test_minimal_backtest.py`
- `tests/unit/backtest/test_backtest.py`

**Action**:
1. Delete `test_minimal_backtest.py` entirely (redundant with test_backtest.py)
2. In `test_backtest.py`: Remove any MinimalBacktest references
3. Ensure all tests use generic Backtest

**Success**: Unit tests pass with only generic Backtest

**Orthogonality**: Only touches tests/unit/backtest/

---

### Task 3: Fix Integration Tests

**Files**: 1 file
- `tests/integration/test_multi_signal_strategy.py`

**Action**:
1. Change imports: MinimalBacktest → Backtest
2. Update instantiation
3. Verify test still passes

**Success**: Integration test uses generic Backtest

**Orthogonality**: Only touches tests/integration/

---

### Task 4: Fix Notebooks

**Files**: 10 files
- All notebooks in notebooks/*.ipynb

**Action**:
1. Search each notebook for "MinimalBacktest" or "minimal"
2. Replace with "Backtest" / "generic"
3. Update imports in code cells
4. Update markdown explanations

**Success**: No "minimal" references in notebooks

**Orthogonality**: Only touches notebooks/

---

### Task 5: Fix Documentation (excluding CLAUDE.md)

**Files**: 33 docs files

**Action**:
1. Search all docs/*.md for "MinimalBacktest" or "minimal backtest"
2. Replace with "Backtest" or "generic backtest"
3. Update architecture diagrams
4. Update examples in docs

**Success**: No minimal references in docs (except CLAUDE.md handled separately)

**Orthogonality**: Only touches docs/ (excluding CLAUDE.md)

---

### Task 6: Update CLAUDE.md

**File**: 1 file (CRITICAL)
- `CLAUDE.md`

**Action**:
1. Remove all MVP "minimal" philosophy
2. Update to: "Build end-to-end backtest that measures correctly"
3. Change "MinimalBacktest" → "Backtest (generic)"
4. Update architecture section to show only Backtest
5. Remove backwards compatibility mentions
6. Update examples section

**Success**: CLAUDE.md describes only generic Backtest

**Orthogonality**: Only touches CLAUDE.md

---

### Task 7: Delete Implementation & Update Exports

**Files**: 2 files
- `Backtest/MinimalBacktest.py`
- `Backtest/__init__.py`

**Action**:
1. Delete `Backtest/MinimalBacktest.py` entirely
2. In `Backtest/__init__.py`: Remove MinimalBacktest from exports
3. Ensure only Backtest is exported

**Success**: MinimalBacktest.py deleted, only Backtest exported

**Orthogonality**: Only touches Backtest/ module

**CRITICAL**: Must run LAST (after all other tasks complete)

---

## Execution Strategy

### Phase 1: Parallel Migration (Tasks 1-6)

All can run simultaneously:

```
Agent 1 → Task 1 (examples/)
Agent 2 → Task 2 (tests/unit/)
Agent 3 → Task 3 (tests/integration/)
Agent 4 → Task 4 (notebooks/)
Agent 5 → Task 5 (docs/ excluding CLAUDE.md)
Agent 6 → Task 6 (CLAUDE.md)
```

**Time**: ~5-10 minutes per task (parallel)

### Phase 2: Delete Implementation (Task 7)

**MUST RUN AFTER** Phase 1 complete:

```
Agent 7 → Task 7 (delete Backtest/MinimalBacktest.py)
```

**Time**: 2 minutes

### Phase 3: Verification

1. Run all tests: `pytest tests/`
2. Grep for any remaining "minimal": `grep -ri minimal .`
3. Confirm 0 matches (except in git history)

**Time**: 5 minutes

---

## Search Patterns to Eliminate

All of these MUST be gone:

```python
# Imports
from Backtest.MinimalBacktest import MinimalBacktest
from Backtest import MinimalBacktest
import MinimalBacktest

# Instantiation
MinimalBacktest(...)
backtest = MinimalBacktest

# Documentation
"minimal backtest"
"MinimalBacktest"
"minimal MVP"
"minimal end-to-end"
```

Replace with:

```python
# Imports
from Backtest.Backtest import Backtest
from Backtest import Backtest

# Instantiation
Backtest(...)
backtest = Backtest

# Documentation
"backtest"
"Backtest"
"generic backtest"
"end-to-end backtest"
```

---

## Testing After Migration

### Must Pass

1. **Unit tests**: `pytest tests/unit/backtest/test_backtest.py`
2. **Integration tests**: `pytest tests/integration/`
3. **Example**: `python examples/run_backtest.py` (renamed)

### Must Fail

1. **Old test**: `pytest tests/unit/backtest/test_minimal_backtest.py` (should not exist)
2. **Import**: `from Backtest.MinimalBacktest import MinimalBacktest` (should fail)

---

## Success Criteria

- [ ] Zero files contain "MinimalBacktest"
- [ ] Zero files contain "minimal backtest" (case insensitive)
- [ ] `Backtest/MinimalBacktest.py` deleted
- [ ] All tests pass
- [ ] Example runs successfully
- [ ] CLAUDE.md updated (no MVP minimal philosophy)
- [ ] `grep -ri "minimalbacktest" .` returns 0 results (excluding .git/)

---

## Rollback Plan

If anything breaks:

1. All changes in one branch: `claude/next-phase-01EqwdS3CUR9K1dEnuN8VeCt`
2. Can revert commits individually
3. MinimalBacktest.py preserved in git history
4. Can cherry-pick working changes

---

## Agent Assignment

```python
tasks = [
    {
        "id": 1,
        "description": "Fix examples directory",
        "files": ["examples/run_minimal_backtest.py"],
        "agent": "general-purpose",
        "time": "5 min"
    },
    {
        "id": 2,
        "description": "Fix unit tests",
        "files": ["tests/unit/backtest/test_minimal_backtest.py",
                  "tests/unit/backtest/test_backtest.py"],
        "agent": "general-purpose",
        "time": "5 min"
    },
    {
        "id": 3,
        "description": "Fix integration tests",
        "files": ["tests/integration/test_multi_signal_strategy.py"],
        "agent": "general-purpose",
        "time": "5 min"
    },
    {
        "id": 4,
        "description": "Fix notebooks",
        "files": ["notebooks/*.ipynb"],
        "agent": "general-purpose",
        "time": "10 min"
    },
    {
        "id": 5,
        "description": "Fix documentation",
        "files": ["docs/*.md (excluding CLAUDE.md)"],
        "agent": "general-purpose",
        "time": "10 min"
    },
    {
        "id": 6,
        "description": "Update CLAUDE.md",
        "files": ["CLAUDE.md"],
        "agent": "general-purpose",
        "time": "5 min"
    }
]

# Task 7 runs AFTER all above complete
reserve_task = {
    "id": 7,
    "description": "Delete MinimalBacktest.py",
    "files": ["Backtest/MinimalBacktest.py", "Backtest/__init__.py"],
    "agent": "general-purpose",
    "time": "2 min",
    "depends_on": [1, 2, 3, 4, 5, 6]
}
```

---

## Immediate Next Action

Launch 6 parallel agents NOW for Tasks 1-6.

Wait for all to complete.

Then Task 7 (delete).

Then verify.

Then commit.
