# Proposed CLAUDE.md Structure

## Section 1: Peter's Rules (The Foundation)
**From**: synthesis/01-universal-rules.md
**Content**:
- Rule #1 - The Permission Principle
- Rule #2 - The Extend-Not-Create Principle
- Foundational Rules (doing it right, honesty, calling Peter "Peter")
- Our Relationship dynamics (colleague model, pushing back, using the journal)
- Proactiveness guidelines
- Version Control rules (critical: push immediately after every commit)
- Writing Code standards (small changes, readability, no code rewriting without permission)
- Naming conventions
- Code Comments rules
- Test Driven Development
- Testing standards
- Issue Tracking via TodoWrite
- Systematic Debugging Framework (4 phases)
- Learning and Memory Management
- Designing Software (YAGNI)

**Rationale**: Peter's rules are the constitutional layer - they govern HOW work happens. They must be first and unambiguous. These aren't suggestions or guidelines; they're the operating principles of our collaboration. Everything else is execution detail within this framework.

---

## Section 2: Project MVP Philosophy & Current Status
**From**: synthesis/05-project-status.md (intro) + synthesis/02-dev-workflow.md (TDD section intro)
**Content**:
- Project Overview (what is ARBS)
- Three-Layer Architecture (high-level sketch)
- Current Test Coverage (1214 tests passing)
- Key Design Patterns (product adapters, frozen dataclasses, query pattern)
- Environment Setup Quick Reference
- "Quick Validation" command block

**Rationale**: Before diving into technical details, the reader needs context: What are we building? Is it working? This section says "yes, here's the proof, here's the essence." It's a landing zone that lets someone know they're in the right place.

---

## Section 3: Essential Development Workflow
**From**: synthesis/02-dev-workflow.md (complete)
**Content**:
- Quick Start (Every Session)
- TDD Workflow (Test → Implement → Refactor) with code examples
- Testing Standards for ARBS (4 test types with commands)
- Systematic Debugging (4 Phases: Investigation, Pattern Analysis, Hypothesis, Implementation)
- Git Workflow (Commit Frequency, Push Immediately)
- Code Review Process
- Learning and Memory Management
- Expand-Then-Compress Coding (for complex features)
- Anti-Patterns (7 toxic patterns to avoid)
- Quick Command Reference (all copyable commands)

**Rationale**: This is the "how to execute" layer. When Peter says "implement X," this section is the manual. It's ordered: setup → develop → test → commit → learn. Each subsection is actionable. This section is where the rubber meets the road.

---

## Section 4: ARBS Technical Architecture
**From**: synthesis/03-arbs-architecture.md (complete)
**Content**:
- Repository Overview (modular design characteristics)
- Three-Layer Design (deep dive: BT/, Query/, MDP/)
- Data Flow Diagram and Detailed Explanation
- Key Design Patterns (Product Adapters, Curve Definitions, Query-Driven Pattern, Caching)
- Backend Systems (QuantLib and RatesLib with parity tolerance)
- Code Conventions (frozen dataclasses, risk weights vs. notional, labels/signatures)
- Essential Files Reference (organized by layer)
- Extension Points (adding new products/curves/metrics)
- Architecture Benefits (modularity, extensibility, consistency, performance)

**Rationale**: This is the "reference layer" for developers doing substantial work. They need to understand the three-layer design to know where to add code. It's comprehensive but comes AFTER the workflow sections so they can actually use it.

---

## Section 5: Technical Commands & Setup Details
**From**: synthesis/04-technical-commands.md (complete)
**Content**:
- Environment Setup (Python 3.12+, virtual environment, dependencies)
- Running Tests (quick validation, integration testing with notebooks)
- Development Workflow Commands (interactive development, code validation, path setup)
- Common Development Tasks (adding curve source, value metric, structure type)
- Troubleshooting Commands (missing fixings, non-deterministic MTM, calendar misalignment, performance)
- Converting Notebooks to Scripts
- Important Files Reference (organized by function, with absolute paths)
- Query-Driven Pattern Example (minimal working example)
- Code Conventions (frozen dataclasses, risk weights, labels)
- Testing Strategy
- Development Notes

**Rationale**: This is pure reference material. Every command is copy-pasteable. Files have absolute paths. It's the "look it up" section when you're stuck or need to verify something.

---

## Table of Contents Structure (Proposed)

```
# CLAUDE.md

## Table of Contents
1. [Peter's Rules](#peters-rules) - How we work together
2. [Project Overview](#project-overview) - What ARBS is and how to verify it works
3. [Development Workflow](#development-workflow) - How to build, test, and commit
4. [Technical Architecture](#technical-architecture) - How ARBS is structured
5. [Commands & Setup Reference](#commands--setup-reference) - Copy-pasteable commands and paths

---

## Peter's Rules
### The Permission Principle
### The Extend-Not-Create Principle
### Foundational Rules
### Our Relationship
### Proactiveness
### Web Searching
### Version Control (CRITICAL: Push Immediately)
### Writing Code
### Naming
### Code Comments
### Test Driven Development (TDD)
### Testing Standards
### Issue Tracking
### Systematic Debugging Process
### Learning and Memory Management
### Designing Software

---

## Project Overview
### What is ARBS?
### Three-Layer Architecture (Bird's Eye)
### Proof of Working: Test Coverage & Commands
### Key Design Patterns at a Glance
### Quick Validation (15 seconds)

---

## Development Workflow
### Quick Start (Every Session)
### TDD Workflow
### Testing Standards for ARBS
### Systematic Debugging (When Things Break)
### Git Workflow (Commit Frequency, Push Immediately)
### Code Review Process
### Learning and Memory Management
### Expand-Then-Compress Coding
### Anti-Patterns (Don't Do These)
### Quick Command Reference

---

## Technical Architecture
### Repository Overview
### Three-Layer Design
  - Backtesting Layer
  - Query/Adapter Layer
  - Market Data Layer
### Data Flow (Per Timestep)
### Key Design Patterns
  - Product Adapters
  - Curve Definitions
  - Query-Driven Pattern
  - Caching Strategy
### Backend Systems
  - QuantLib Backend
  - RatesLib Backend
  - Backend Parity
### Code Conventions
### Essential Files Reference
### Extension Points
### Architecture Benefits

---

## Commands & Setup Reference
### Environment Setup
### Running Tests
### Development Workflow Commands
### Common Development Tasks
### Troubleshooting Commands
### Converting Notebooks to Scripts
### Important Files Reference
### Query-Driven Pattern Example
### Code Conventions
### Testing Strategy
### Development Notes
```

---

## Key Design Decisions

### 1. Rules First (Not Last)
**Why**: Peter's rules are the operating system of our collaboration. Everything else is application code running on top. They must be visible immediately, non-negotiable, and clear.

### 2. Workflow Early (Before Diving Into Architecture)
**Why**: A developer's first question is "how do I build something?" They need TDD, debugging, git rhythm, and testing BEFORE understanding the architecture. These are the "meta-rules" about execution.

### 3. Architecture As Reference, Not As Learning Tool
**Why**: The architecture section is deep and comprehensive, but comes AFTER workflow. By then, readers know HOW to work and are ready to understand WHERE code goes.

### 4. Commands At The End (Always Grepable)
**Why**: Commands are tools, not learning material. They go at the end where they can be easily found, copied, and executed. Absolute paths, organized by function.

### 5. Section Boundaries Are Hard
**Why**: Each section stands alone. Rules don't bleed into workflow. Workflow examples reference architecture. Architecture has no opinions about HOW to work (that's workflow's job). Commands reference files by absolute path.

---

## Scanability Features

1. **H2 Headers for Sections**: `## Section Name` - major dividers
2. **H3 Headers for Topics**: `### Topic Name` - subsections within sections
3. **H4 Headers for Details**: `#### Detail` - specific patterns/extensions
4. **Code Blocks for Executables**: All commands have backtick blocks, copy-ready
5. **Bold for Emphasis**: Critical rules in **bold**
6. **Tables of Contents**: Top-level TOC + section-level outline
7. **Consistent Organization**: Rules → Overview → Workflow → Architecture → Reference

---

## Estimated Size

- **Peter's Rules**: ~2,500 lines (includes all foundational content)
- **Project Overview**: ~500 lines (introduces ARBS concisely)
- **Development Workflow**: ~3,000 lines (TDD + debugging + git + examples)
- **Technical Architecture**: ~3,500 lines (deep dive into three layers + patterns)
- **Commands & Setup**: ~2,000 lines (reference material)

**Total**: ~11,500 lines (comprehensive, reference-grade documentation)

---

## Success Criteria

This structure succeeds when:
1. A new developer can read Section 1 and know HOW to work with Peter
2. Section 2 proves the system is alive and working
3. Section 3 is their first stop when building something
4. Section 4 answers "where does this code go?"
5. Section 5 is grepped for specific commands and paths
6. All sections link to each other consistently
7. No content appears in multiple sections (DRY principle)
