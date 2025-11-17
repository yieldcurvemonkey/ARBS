# Audience Analysis: CLAUDE.md

## Executive Summary
CLAUDE.md serves two distinct audiences with conflicting information access patterns:
- **Claude Code**: Needs actionable patterns and decision trees; skims for context
- **Human Developers**: Needs setup first, then reference during development

Current structure optimizes for Claude Code but leaves humans without clear onboarding path.

---

## Claude Code (AI Assistant) Needs

### Primary Requirements (Extract Immediately)
1. **Architecture Pattern Recognition**
   - Three-layer design (BT / Query / MDP)
   - Adapter pattern for products
   - Data flow per timestep
   - *Currently:* Sections 1-2 provide this well

2. **Quick Decision Trees**
   - "Where does a new feature go?" → adapter-driven answer
   - "What files must I modify?" → mapped in Key Design Patterns
   - "How do queries work?" → code example provided
   - *Currently:* Scattered across sections, not consolidated

3. **Context Constraints (Implicit)**
   - Python 3.12+
   - Frozen dataclasses (immutable, hashable)
   - Two backend systems (QL vs RL parity)
   - No formal testing framework
   - *Currently:* Buried in sections 3-5; not emphasized

4. **Common Tasks as Structured Procedures**
   - "Adding New Curve Source" → 5 steps
   - "Adding New Value Metric" → 4 steps
   - "Modifying Product Structures" → 3 steps
   - *Currently:* Present but treated equally to other sections

### Secondary Requirements
- Notebook examples for validation patterns
- Troubleshooting mappings (symptom → cause → fix)
- Backend parity thresholds (0.1-1bp tolerance)
- File reference map for quick navigation

### Current Strengths
- Data flow diagram (visual pattern)
- Code examples for primary usage pattern
- Task-based procedures

### Current Weaknesses
- No "quick start for Claude" section
- Architecture buried under setup instructions
- No explicit decision tree for feature placement
- Troubleshooting section appears late (section 8)

---

## Human Developers Needs

### Onboarding Phase (First 30 minutes)
**Critical information in order:**

1. **What is ARBS?** (Section 1 ✓ covers this)
2. **How do I get it running?** (Section 2, but structure is wrong)
   - *Need:* Setup → Test → Done in under 10 commands
   - *Current:* 3 subsections spread across 40 lines
   - *Issue:* "Verify Installation" and "Running Tests" are out of logical order
3. **What do I do with it?** (Section 3)
   - *Need:* "Your first backtest" walkthrough
   - *Current:* "Key Design Patterns" (abstract)
4. **Where do I look for what?** (Section 10 ✓ provides this)

### Development Phase (Ongoing Reference)
**What they pull up repeatedly:**

1. **Code conventions** (Section 7)
   - Frozen dataclasses behavior
   - Risk weights vs notional
   - Label/signature format

2. **Common tasks** (Section 5)
   - Exact procedure for new curve/metric/structure
   - File locations with paths

3. **Troubleshooting** (Section 6)
   - Symptom → diagnosis → fix
   - Examples with specific files

4. **Important files reference** (Section 9)
   - Always opened in sidebar
   - Needs brief description per file

### Secondary Needs
- Testing approach (Section 6 explains no formal tests exist)
- Backend differences (QL vs RL)
- Caching strategy when to use ZODB

### Current Strengths
- All critical files listed with one-line descriptions
- Troubleshooting section is practical
- Code examples are complete and runnable

### Current Weaknesses
- **Onboarding path is broken**: Environment setup → Architecture → Tasks → Testing
  - Humans want: Setup → Hello World → Reference material
- **No "first backtest" guide**
- Important files listed but not discovered in learning order
- Development workflow section (2.3) is too brief

---

## Section Priority by Audience

### Claude Code Priority Order
```
1. Core Architecture (understand system design)
2. Key Design Patterns (make decisions)
3. Common Tasks (structured procedures)
4. Important Files Reference (lookup during implementation)
5. Troubleshooting (validate assumptions)
6. Backend Systems (understand implementation details)
7. Code Conventions (follow patterns)
8. Essential Commands (only if needed for validation)
9. Testing Strategy (understand validation approach)
10. Development Notes (context only)
```

### Human Developer Priority Order
```
1. Repository Overview (what is this?)
2. Essential Commands → Environment Setup (get it running)
3. Quick Validation (did I install correctly?)
4. First Backtest Example (hands-on experience)
5. Important Files Reference (map the codebase)
6. Common Tasks (extend it)
7. Key Design Patterns (understand how)
8. Code Conventions (follow patterns)
9. Troubleshooting (debug it)
10. Backend Systems (deep dive later)
11. Testing Strategy (validation approach)
12. Development Notes (context)
```

---

## Quick Reference Requirements

### What Claude Code Needs Immediately
- **Architecture diagram** (current: text-only data flow) → Add visual
- **Decision tree**: "Where should I add this feature?" → Add quick chart
- **File structure map**: `Query/<Product>/adapter.py` pattern → Explicit
- **Task procedures**: Numbered steps with file paths → All present, needs highlighting

### What Humans Need Immediately
- **Getting Started in 5 steps** → Create new section 2.1 before architecture
- **First Query Example** → Runnable code that doesn't require CME data
- **File navigation guide** → Show how files map to typical development task
- **When to read each section** → Add section annotations: "Read on Day 1" vs "Reference during development"

### What Both Need
- **Architecture glossary**: OUTRIGHT/CURVE/FLY/RATE/NPV/BPV defined clearly (currently scattered)
- **File reference with icons**:
  - `adapter.py` → Always one per product
  - `*Definition*.py` → Always contains metadata
  - `*Query.py` → Always user-facing interface
- **Decision matrix**: Given "I want to...", which files do I modify?

---

## Recommended Restructuring

### Current Structure (Human-Hostile)
```
Intro → Architecture → Setup → Tests → Design → Tasks → Code → Backends → Troubleshooting
```

### Proposed Dual-Audience Structure
```
[FOR EVERYONE]
1. What is ARBS (5-minute overview)
2. Core Architecture (3-layer mental model)

[FOR HUMANS STARTING OUT]
3. Getting Started (5 commands, verify, done)
4. Your First Backtest (complete, runnable example)
5. File Navigation Guide (how to find things)

[FOR BOTH - DURING DEVELOPMENT]
6. Common Tasks (procedures with file locations)
7. Design Patterns (understand the idioms)
8. Code Conventions (follow these)

[FOR CLAUDE CODE - OPTIMIZATION]
9. Quick Decision Tree (where should this code go?)
10. Architecture Details (deep understanding)

[FOR BOTH - EMERGENCY]
11. Troubleshooting (symptom→fix)
12. Important Files Reference (quick lookup)

[CONTEXT]
13. Backend Systems (deep dive)
14. Testing Strategy (validation approach)
15. Development Notes (status/constraints)
```

---

## Implementation Suggestions

### For Claude Code Extraction
Add at top of file:
```markdown
### Quick Navigation for Claude Code
- **Understand the pattern**: Go to "Core Architecture" (Section 2)
- **Make a decision**: Go to "Quick Decision Tree" (new section after 8)
- **Implement a feature**: See "Common Tasks" (Section 5)
- **Validate your work**: Go to "Testing Strategy" (Section 6)
```

### For Human Onboarding
Add before "Essential Commands":
```markdown
## Getting Started (5 minutes)
[Linear walkthrough: setup → verify → first query]
```

### For Both
Add "Section Guide" comment:
```markdown
## Key Design Patterns ← Read on Day 1 (humans) / Before implementation (Claude)
## Troubleshooting ← Reference when debugging
## Important Files ← Keep this window open during development
```

---

## Metrics for Success

| Goal | Current | Target |
|------|---------|--------|
| Time for human to run first test | ~20 min (scattered) | <5 min (linear path) |
| Time for Claude to understand architecture | ~2 min (good) | <1 min (clear decision tree) |
| Time to find where a feature goes | ~5 min (scattered) | <1 min (decision matrix) |
| Time to troubleshoot a bug | ~10 min (good) | <3 min (symptom lookup) |
| Files referenced per task | 3-5 | Should be <3 |

---

## Conclusion

**Current state**: CLAUDE.md optimizes for Claude Code (architecture first) at the expense of human onboarding.

**Opportunity**: Reorganize without losing content. Add:
1. Clear human onboarding path (sections 2-4)
2. Quick decision tree for Claude (architecture patterns)
3. Annotation for when each section is useful
4. Decision matrix: "I want to X → modify files Y, Z"

**Effort**: 60 minutes to restructure + test with both audiences.

**Impact**: 5x faster onboarding for humans, 2x faster decision-making for Claude Code.
