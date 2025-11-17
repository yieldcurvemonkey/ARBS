# Cross-Reference Integration Points (Synthesis 01-05)

Maps critical connections between architecture sections, commands, rules, workflow, and status.

---

## Cross-Reference: Permission & Extension Principles → Development Workflow

**Appears in**:
- `01-universal-rules.md` (Rule #1, Rule #2)
- `02-dev-workflow.md` (TDD workflow, systematic debugging)

**Link from**: `02-dev-workflow.md` (TDD Workflow section)

**Link to**: `01-universal-rules.md` (Rule #1, Rule #2)

**Transition text**:
"When implementing features via TDD, always follow the Extension-Not-Create principle (Rule #2 from Universal Rules). Before writing a test, ask: 'Can I add this to an existing class?' If you're tempted to create new systems or 'New' classes, STOP and get explicit permission first per Rule #1."

---

## Cross-Reference: Three-Layer Architecture → Query-Driven Pattern Commands

**Appears in**:
- `03-arbs-architecture.md` (Core Architecture section)
- `04-technical-commands.md` (Query-Driven Pattern Example)

**Link from**: `04-technical-commands.md` (Query-Driven Pattern Example section)

**Link to**: `03-arbs-architecture.md` (Query/Adapter Layer, Data Flow sections)

**Transition text**:
"This pattern is built on the three-layer architecture: the Query layer (where IRSwapQuery lives) communicates with the MDP (Market Data Layer) via the BaseQuery interface. See Architecture section 03 for how these layers interact during the data flow."

---

## Cross-Reference: Systematic Debugging → Common Development Tasks

**Appears in**:
- `02-dev-workflow.md` (Systematic Debugging section)
- `04-technical-commands.md` (Troubleshooting Commands)

**Link from**: `04-technical-commands.md` (Troubleshooting Commands section)

**Link to**: `02-dev-workflow.md` (Systematic Debugging, Phase 1-4 section)

**Transition text**:
"When debugging issues like 'Calendar Misalignment' or 'Non-Deterministic MTM', follow the four-phase systematic debugging framework detailed in the Development Workflow (Phase 1: Root Cause Investigation through Phase 4: Implementation). Never guess or add workarounds—trace the actual value."

---

## Cross-Reference: Curve Definitions Metadata → Testing Standards

**Appears in**:
- `03-arbs-architecture.md` (Curve Definitions section, line 169-187)
- `02-dev-workflow.md` (Testing Standards for ARBS section)
- `04-technical-commands.md` (Important Files Reference, line 236)

**Link from**: `02-dev-workflow.md` (Curve Build Tests subsection)

**Link to**: `03-arbs-architecture.md` (Curve Definitions section) & `04-technical-commands.md` (Important Files Reference)

**Transition text**:
"Curve definitions are the single source of truth for conventions (see `definitions/IRSwaps.py` in Architecture section 03, line 169). When validating curve builds, check three things: is the curve in CURVE_DEFINITIONS, do day counters match (ACT/360 vs. 30/360), and is the calendar correct. This is documented at commands reference line 236."

---

## Cross-Reference: Backend Parity Tolerance → Integration Testing

**Appears in**:
- `03-arbs-architecture.md` (Backend Parity subsection, line 273-290)
- `02-dev-workflow.md` (Testing Standards, Backend Parity Tests subsection)
- `04-technical-commands.md` (Testing Strategy section)

**Link from**: `02-dev-workflow.md` (Backend Parity Tests section)

**Link to**: `03-arbs-architecture.md` (Backend Parity subsection)

**Transition text**:
"Backend parity is critical: QuantLib and RatesLib should agree within 0.1-1bp. The Architecture section (line 273) details common misalignments—'US Government Bond' vs 'nyc' calendar names. When par rates drift, use the verification process from Architecture section 280-284 before assuming a bug."

---

## Cross-Reference: TDD Workflow → Commit Message Format & Frequency

**Appears in**:
- `02-dev-workflow.md` (TDD Workflow section, Git Workflow section)
- `01-universal-rules.md` (Version Control rules, line 60-64)

**Link from**: `01-universal-rules.md` (Version Control section)

**Link to**: `02-dev-workflow.md` (Git Workflow, Commit Message Format section)

**Transition text**:
"Per the Version Control rules, YOU MUST commit frequently throughout development (line 60). The Git Workflow section of 02-dev-workflow.md shows exactly how: every 15-30 minutes of development, run `git status`, review changes with `git diff`, stage files, and commit with descriptive messages following the format: `<type>: <subject>`. Examples include 'feat: Add USD-SONIA curve' and 'fix: Calendar mismatch between QuantLib and RatesLib backends.'"

---

## Cross-Reference: Product Adapters → Adding New Structures Commands

**Appears in**:
- `03-arbs-architecture.md` (Product Adapters section, line 125-165)
- `04-technical-commands.md` (Common Development Tasks, Adding a New IRS Structure Type)

**Link from**: `04-technical-commands.md` (Common Development Tasks section)

**Link to**: `03-arbs-architecture.md` (Product Adapters section)

**Transition text**:
"To add a new IRS structure type, you must understand how product adapters work (see Architecture section 03, lines 125-165). Structure Maps define how abstract structures (OUTRIGHT/CURVE/FLY) map to concrete instruments. Follow the Architecture's explanation first, then execute the four-step implementation process in commands section."

---

## Cross-Reference: Environment Setup → Verification Testing → Quick Validation

**Appears in**:
- `04-technical-commands.md` (Environment Setup & Verify Installation sections)
- `05-project-status.md` (Usage Pattern Examples, Quick Validation subsection)

**Link from**: `05-project-status.md` (Usage Pattern Examples)

**Link to**: `04-technical-commands.md` (Verify Installation section)

**Transition text**:
"After completing environment setup (commands section lines 13-28), verify your installation by running `python test_basic_workflow.py`. This quick validation tests query creation, arithmetic, MDP requests, and curve lookups in ~1 second. Expected output should show ✓ marks for all checks per commands section line 40."

---

## Cross-Reference: ZODB Caching Strategy → Cache Invalidation Anti-Pattern

**Appears in**:
- `03-arbs-architecture.md` (Caching Strategy section, line 216-234)
- `02-dev-workflow.md` (Anti-Patterns section, Cache Invalidation point)

**Link from**: `02-dev-workflow.md` (Anti-Patterns section, #6 Cache Invalidation)

**Link to**: `03-arbs-architecture.md` (Caching Strategy section)

**Transition text**:
"ZODB caching is critical for performance but easily breaks if invalidation is skipped. The architecture uses recipe hashes to version curves (see Architecture section line 229). The anti-pattern to avoid: modifying curve recipes without bumping the cache namespace. Always see Caching/ZODBCacheMixin.py after recipe changes, or stale curves will cause non-deterministic P&L."

---

## Summary Table

| Topic | File 01 | File 02 | File 03 | File 04 | File 05 |
|-------|---------|---------|---------|---------|---------|
| **Permissions & Rules** | Rules #1, #2 | TDD workflow | — | — | — |
| **Architecture** | — | Debugging phases | Three-layer design | Command structure | Status overview |
| **Curve Definitions** | — | Testing validation | Single source of truth | File reference | — |
| **Backend Parity** | — | Parity tests | Tolerance specs | Troubleshooting | Testing strategy |
| **Product Adapters** | — | — | Detailed patterns | New structure steps | Pattern examples |
| **Git Workflow** | Version control rules | Commit format | — | Commands | — |
| **ZODB Caching** | — | Anti-patterns | Invalidation strategy | Troubleshooting | Dependencies |
| **Environment** | — | Setup section | — | Setup commands | Usage examples |

---

**Created**: 2025-11-17
**Purpose**: Enable cross-navigation and prevent duplicate information in synthesis documentation
