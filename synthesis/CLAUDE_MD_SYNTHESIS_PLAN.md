# CLAUDE.md Synthesis Plan - Parallel Decomposition with Phoenix Protocol

**Date**: 2025-11-17
**Objective**: Combine two completely different CLAUDE.md files into optimal synthesis
**Method**: Orthogonal task decomposition with parallel execution and Phoenix monitoring
**Time Budget**: 5-10 minutes per task, ~60 minutes total

## Source Analysis

### Source A: Local CLAUDE.md (335 lines)
**Type**: Technical reference for ARBS codebase
**Content**:
- Repository overview (ARBS backtesting system)
- Three-layer architecture (BT/Query/MDP)
- Data flow diagrams
- Environment setup (venv, pip, requirements.txt)
- Essential commands (testing, development)
- Curve definitions and market data providers
- Troubleshooting guide

**Audience**: New developers learning the ARBS codebase
**Tone**: Technical documentation, reference manual

### Source B: Origin/Main CLAUDE.md (346 lines)
**Type**: Development philosophy and coding rules for working with Peter
**Content**:
- Rule #1: Permission required for rule exceptions
- Rule #2: Extend, never create new systems
- MVP philosophy (measurement over performance)
- TDD workflow
- Architecture status (582 tests, returns-first design)
- Relationship guidelines ("Don't glaze me")
- Coding standards (YAGNI, naming, git workflow)
- Debugging framework (systematic root cause)

**Audience**: Claude Code working with Peter on ANY project
**Tone**: Prescriptive rules, partnership principles, project status

## Synthesis Strategy

**Goal**: Create ONE CLAUDE.md that serves BOTH purposes:
1. **Universal Section**: Peter's rules and philosophy (apply to ALL projects)
2. **ARBS-Specific Section**: Technical documentation for this codebase

**Structure**:
```markdown
# Claude Development Guidelines

## Part 1: Universal Rules (from Source B)
- Rule #1, Rule #2
- MVP philosophy
- Coding standards
- Relationship dynamics
- TDD, git workflow, debugging

## Part 2: ARBS Project Context (synthesized)
- Current architecture status (from Source B)
- Project goals and philosophy (from Source B)
- Test coverage status (from Source B)

## Part 3: ARBS Technical Reference (from Source A)
- Repository overview
- Architecture layers
- Setup instructions
- Essential commands
- Troubleshooting
```

## Phoenix Protocol - Toxic Pattern Detection

**Rules to Monitor During Execution**:

### Rule 1: No Concatenation
**Pattern**: "I'll just paste both files together with a divider"
**Detection**: Check if synthesis is >600 lines (should be ~400-450)
**Intervention**: STOP - Require actual synthesis, not concatenation

### Rule 2: No Information Loss
**Pattern**: "I'll drop the less important parts to save space"
**Detection**: Missing sections from either source
**Intervention**: STOP - Every section must be represented or explicitly discussed

### Rule 3: No Research Spiral
**Pattern**: "Let me analyze the philosophical implications of..."
**Detection**: Task taking >10 minutes without producing output file
**Intervention**: KILL - Produce file or abort

### Rule 4: No Duplication
**Pattern**: Saying the same thing in different words from both sources
**Detection**: Redundant sections (e.g., two "testing" sections)
**Intervention**: MERGE - Synthesize into single best version

### Rule 5: File Creation Required
**Pattern**: "I analyzed the files and here's my conclusion..."
**Detection**: No .md file created
**Intervention**: KILL - Must produce actual markdown files

## Orthogonal Task Decomposition

### Phase 1: Parallel Content Extraction (5 tasks, run simultaneously)

#### Task 1: Extract Universal Rules
**Time**: 5 minutes
**Creates**: `synthesis/01-universal-rules.md`
**Source**: Origin/main CLAUDE.md
**Content**:
- Rule #1 (permission for exceptions)
- Rule #2 (extend, don't create)
- Foundational rules section
- Relationship dynamics ("Don't glaze me", "think of partner as Peter")
**Success**: File exists, no TODOs, complete rules extracted
**Phoenix**: Monitor for completeness - did we get ALL rules?

#### Task 2: Extract Development Workflow
**Time**: 10 minutes
**Creates**: `synthesis/02-dev-workflow.md`
**Source**: Origin/main CLAUDE.md
**Content**:
- TDD process
- Git workflow (commit often, push immediately)
- Code review process
- Testing standards
- Debugging framework (4-phase systematic)
**Success**: File exists, workflow is actionable
**Phoenix**: Monitor for "just copying" - should synthesize into clear workflow

#### Task 3: Extract ARBS Architecture
**Time**: 10 minutes
**Creates**: `synthesis/03-arbs-architecture.md`
**Source**: Local CLAUDE.md
**Content**:
- Three-layer design (BT/Query/MDP)
- Data flow diagram
- Core architecture explanation
- Design patterns (adapter pattern)
**Success**: File exists, architecture is clear and complete
**Phoenix**: Monitor for missing architectural concepts

#### Task 4: Extract Technical Commands
**Time**: 10 minutes
**Creates**: `synthesis/04-technical-commands.md`
**Source**: Local CLAUDE.md
**Content**:
- Environment setup (venv, pip)
- Running tests
- Development workflow commands
- Common tasks (adding curves, value metrics, structures)
**Success**: File exists, commands are copy-pasteable
**Phoenix**: Monitor for incomplete command sequences

#### Task 5: Extract Project Status
**Time**: 5 minutes
**Creates**: `synthesis/05-project-status.md`
**Source**: Origin/main CLAUDE.md
**Content**:
- Current architecture version (V4)
- Test count (582 tests, 1214 in latest)
- MVP status (measurement over performance)
- Architecture improvements applied
- Future enhancements (optional)
**Success**: File exists, status is current and accurate
**Phoenix**: Monitor for outdated information

### Phase 2: Parallel Analysis (4 tasks, run simultaneously)

#### Task 6: Conflict Resolution Analysis
**Time**: 5 minutes
**Creates**: `synthesis/06-conflicts.md`
**Analysis**: Where do sources contradict?
**Output**:
- List of conflicts (if any)
- Resolution strategy for each
- Precedence rules (which source wins)
**Success**: All conflicts identified and resolved
**Phoenix**: Monitor for missed conflicts

#### Task 7: Structure Design
**Time**: 5 minutes
**Creates**: `synthesis/07-structure.md`
**Analysis**: Optimal section ordering
**Output**:
- Table of contents
- Section flow justification
- Navigation strategy
**Success**: Clear logical flow defined
**Phoenix**: Monitor for poor organization

#### Task 8: Audience Analysis
**Time**: 5 minutes
**Creates**: `synthesis/08-audience.md`
**Analysis**: Who reads what, when
**Output**:
- Primary audience: Claude Code
- Secondary audience: Human developers
- Section relevance to each audience
- Quick-reference needs
**Success**: Clear audience understanding
**Phoenix**: Monitor for forgetting primary audience (Claude)

#### Task 9: Integration Points
**Time**: 5 minutes
**Creates**: `synthesis/09-integration.md`
**Analysis**: How to weave sources together naturally
**Output**:
- Transition strategies between sections
- Cross-references needed
- Shared concepts (link them)
**Success**: Integration strategy defined
**Phoenix**: Monitor for jarring transitions

### Phase 3: Synthesis (RESERVE TASK - runs after Phase 1 & 2 complete)

#### Task 10: Synthesize Final CLAUDE.md
**Time**: 15 minutes
**Depends on**: Tasks 1-9
**Creates**: `CLAUDE.md` (final)
**Process**:
1. Start with structure from Task 7
2. Insert universal rules (Task 1)
3. Add development workflow (Task 2)
4. Integrate project status (Task 5)
5. Add ARBS architecture (Task 3)
6. Add technical commands (Task 4)
7. Apply conflict resolutions (Task 6)
8. Implement integration points (Task 9)
9. Optimize for audience (Task 8)
**Success**:
- Single coherent CLAUDE.md file
- ~400-450 lines (not simple concatenation)
- No information loss from either source
- Clear section boundaries
- Logical flow for readers
**Phoenix**: Monitor for:
- Concatenation (>500 lines = suspicious)
- Information loss (missing sections)
- Poor transitions
- Duplication

### Phase 4: Validation (2 tasks, run in parallel)

#### Task 11: Content Validation
**Time**: 5 minutes
**Creates**: `synthesis/11-validation-content.md`
**Checks**:
- [ ] All Rule #1, Rule #2 content preserved
- [ ] All ARBS architecture content preserved
- [ ] All setup commands preserved
- [ ] All workflow guidance preserved
- [ ] No section from either source was dropped
**Success**: Checklist 100% complete
**Phoenix**: Monitor for "looks good enough" - must be rigorous

#### Task 12: Quality Validation
**Time**: 5 minutes
**Creates**: `synthesis/12-validation-quality.md`
**Checks**:
- [ ] Sections flow logically
- [ ] No duplicate content
- [ ] Tone is consistent
- [ ] Commands are accurate
- [ ] Cross-references work
- [ ] Length is reasonable (400-500 lines)
**Success**: All quality checks pass
**Phoenix**: Monitor for skipping quality checks

## Parallel Execution Strategy

### Wave 1: Content Extraction (Tasks 1-5)
**Execute simultaneously**: All 5 tasks create different files
**Time**: 10 minutes (longest task)
**Monitoring**: Phoenix checks every 5 minutes for file creation

### Wave 2: Analysis (Tasks 6-9)
**Execute simultaneously**: All 4 tasks create different files
**Time**: 5 minutes
**Monitoring**: Phoenix checks for analysis paralysis

### Wave 3: Synthesis (Task 10)
**Execute alone**: Depends on all previous tasks
**Time**: 15 minutes
**Monitoring**: Phoenix checks every 5 minutes for:
- Is actual synthesis happening? (not just copying)
- Is file growing? (progress indicator)
- Are TODOs being left? (incompleteness)

### Wave 4: Validation (Tasks 11-12)
**Execute simultaneously**: Different validation aspects
**Time**: 5 minutes
**Monitoring**: Phoenix checks for rigor

## Success Metrics

**Quantitative**:
- [ ] Final CLAUDE.md is 400-500 lines (not 600+)
- [ ] Zero information loss (all sections accounted for)
- [ ] Zero TODOs in final file
- [ ] All 12 task files created
- [ ] Total time <60 minutes

**Qualitative**:
- [ ] A new developer can understand ARBS from this file
- [ ] Claude knows Peter's rules from this file
- [ ] File flows logically (not jarring transitions)
- [ ] No redundant content
- [ ] Professional tone maintained

## Phoenix Interrupt Thresholds

**Time-based**:
- Task >15 minutes without output → KILL
- Total process >90 minutes → STOP and review

**Content-based**:
- Simple concatenation detected → INTERRUPT, require synthesis
- Information loss detected → INTERRUPT, require inclusion
- TODO comments in final → INTERRUPT, require completion
- Duplicate sections → INTERRUPT, require merge

**Quality-based**:
- Poor transitions → FLAG for revision
- Inconsistent tone → FLAG for revision
- Missing cross-references → FLAG for addition

## Execution Commands

```bash
# Create synthesis workspace
mkdir -p synthesis/

# Execute Wave 1 (parallel)
# Launch 5 parallel agents for tasks 1-5
# Each produces synthesis/0X-*.md

# Execute Wave 2 (parallel)
# Launch 4 parallel agents for tasks 6-9
# Each produces synthesis/0X-*.md

# Execute Wave 3 (serial)
# Single agent for task 10
# Produces CLAUDE.md

# Execute Wave 4 (parallel)
# Launch 2 parallel agents for tasks 11-12
# Each produces synthesis/1X-*.md
```

## Deliverables

1. **synthesis/** directory with 12 markdown files (tasks 1-12)
2. **CLAUDE.md** - Final synthesized file
3. **CLAUDE_MD_SYNTHESIS_PLAN.md** - This file (documentation)
4. **Validation report** - From tasks 11-12

## Risk Mitigation

**Risk**: Agent just concatenates both files
**Mitigation**: Phoenix rule checking file length + manual review

**Risk**: Information loss during synthesis
**Mitigation**: Task 11 validates all content preserved

**Risk**: Poor quality synthesis
**Mitigation**: Task 12 validates quality metrics

**Risk**: Research spiral instead of execution
**Mitigation**: Phoenix 10-minute timeout per task

**Risk**: Tasks not actually orthogonal (conflicts)
**Mitigation**: Tasks 1-5 create different files, no shared state

## Next Steps

1. Review this plan with Peter
2. Launch parallel execution
3. Monitor with Phoenix protocol
4. Synthesize results
5. Validate quality
6. Commit final CLAUDE.md
