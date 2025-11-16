# CLAUDE.md Violations Report

**Date**: 2025-11-14
**Scope**: All active documentation + code sample
**Method**: Systematic search for naming and content violations

---

## Documentation Filename Violations

### Temporal/Adjective Markers (7 files)

**VIOLATION**: Names contain temporal context or quality claims

1. **ALPHAVANTAGE_DATA_LAYER_PLAN_CORRECTED.md**
   - Marker: "CORRECTED" (implies there was an incorrect version)
   - Should be: `ALPHAVANTAGE_DATA_LAYER_PLAN.md` or `ALPHAVANTAGE_INTEGRATION.md`

2. **BACKTEST_UNIFIED_API.md**
   - Marker: "UNIFIED" (temporal - implies multiple versions were combined)
   - Should be: `BACKTEST_API.md` (just describe what it is)

3. **VERIFIED_INTEGRATIONS.md**
   - Marker: "VERIFIED" (temporal - claims verification happened)
   - Should be: `INTEGRATIONS.md` or `INTEGRATION_STATUS.md`

4. **design/AGENT_ORCHESTRATION_UNIFIED.md**
   - Marker: "UNIFIED" (temporal - we already fixed this!)
   - Should be: `design/AGENT_ORCHESTRATION.md`

5. **papers/COMPREHENSIVE_VERIFICATION.md**
   - Marker: "COMPREHENSIVE" (quality claim)
   - Should be: `papers/SECTOR_COVARIANCE_VERIFICATION.md` (what it verifies)

6. **papers/sector_risk_models/COMPLETE_TASK_BREAKDOWN.md**
   - Marker: "COMPLETE" (temporal/quality claim)
   - Should be: `papers/sector_risk_models/TASK_BREAKDOWN.md`

7. **papers/sector_risk_models/COMPREHENSIVE_ANALYSIS.md**
   - Marker: "COMPREHENSIVE" (quality claim)
   - Should be: `papers/sector_risk_models/ANALYSIS.md` or more specific topic

---

## Documentation Content Violations

### Temporal References (1 file)

**docs/RETURNS_VS_PRICES_ANALYSIS.md:3**
```markdown
**NOTE**: This analysis led to the returns-first architecture implemented in commit bf818d5 (2025-11-11).
All recommendations have been implemented. Document retained for architectural rationale.
```

**VIOLATION**: Comment explains what changed instead of what exists
**Fix**: Remove "This analysis led to" and "All recommendations have been implemented"
**Should say**:
```markdown
**Purpose**: Architectural rationale for returns-first design

This document explains why ARBS uses returns as the primary data structure instead of prices.
```

---

## Potential Multiple-File Violations

### Similar Purpose Files (Need Review)

**PLAN files** (multiple files with similar purposes):
- docs/MODULARITY_IMPROVEMENTS_PLAN.md
- docs/PDF_PROCESSING_PLAN.md
- docs/PHASE_4_PLAN.md
- docs/design/BACKTEST_UNIFICATION_PLAN.md
- docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md

**Question**: Are these different plans or versions of the same thing?
- If different phases/components → OK (different purposes)
- If overlapping scopes → VIOLATION (consolidate)

**SUMMARY files**:
- docs/PHASE_3_COMPLETION_SUMMARY.md
- docs/PHASE_4_COMPLETION_SUMMARY.md
- docs/STRATEGY_MODULARIZATION_SUMMARY.md
- docs/papers/SECTOR_ROTATION_SUMMARY.md

**Question**: Could these be ONE completion tracking document?
- Current: 4 separate summaries
- Better: Single IMPLEMENTATION_STATUS.md with all phases?

---

## Code Violations (Sample Check)

### ABOUTME Comments

**Checked** (sample of 2 files):
- ✅ Backtest/Backtest.py - Has proper ABOUTME
- ✅ Signals/Base/BaseSignal.py - Has proper ABOUTME

**Need Full Scan**: Check all .py files in production code

**Command to check**:
```bash
find . -name "*.py" -type f -path "./[A-Z]*/*.py" -exec sh -c 'head -1 "$1" | grep -q "ABOUTME:" || echo "$1"' _ {} \;
```

---

## Summary

### High Priority (User-Facing)
1. Rename BACKTEST_UNIFIED_API.md → BACKTEST_API.md
2. Fix RETURNS_VS_PRICES_ANALYSIS.md NOTE comment
3. Rename VERIFIED_INTEGRATIONS.md → INTEGRATIONS.md

### Medium Priority (Design Docs)
4. Rename ALPHAVANTAGE_DATA_LAYER_PLAN_CORRECTED.md
5. Rename AGENT_ORCHESTRATION_UNIFIED.md → AGENT_ORCHESTRATION.md
6. Rename COMPREHENSIVE_VERIFICATION.md → SECTOR_COVARIANCE_VERIFICATION.md

### Low Priority (Papers Subdirectory)
7. Rename COMPLETE_TASK_BREAKDOWN.md → TASK_BREAKDOWN.md
8. Rename COMPREHENSIVE_ANALYSIS.md → ANALYSIS.md

### Investigation Needed
9. Review PLAN files - consolidate if overlapping
10. Review SUMMARY files - consolidate if overlapping
11. Full code scan for missing ABOUTME comments

---

## Recommendation

Fix violations in order of user impact:
1. User-facing guides first (BACKTEST_UNIFIED_API, VERIFIED_INTEGRATIONS)
2. Design docs second
3. Papers subdirectory last (lower visibility)

Then investigate whether multiple PLAN/SUMMARY files violate "1 file, 1 purpose" rule.
