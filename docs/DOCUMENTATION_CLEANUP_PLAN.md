# Documentation Cleanup & Auto-Generation Plan

Created: 2025-11-14
Branch: `claude/docs-cleanup-autogen-<session-id>`

## Objective

Analyze 164 markdown files, consolidate redundant content, create indexed structure, and generate architecture diagrams from code.

## Current Inventory

```bash
$ find . -name "*.md" -type f | grep -v "/\." | grep -v venv | wc -l
164

$ find . -name "*.md" -type f | grep -v "/\." | grep -v venv | xargs wc -l | tail -1
109825 total
```

**File Distribution**:
- Root level: 12 files
- docs/: 45 files
- docs/books/grinold_kahn_markdown/: 37 files
- docs/design/: 8 files
- docs/papers/: 50+ files
- docs/references/: 12 files
- Other: ~10 files

## Documentation Standards

All documentation must:
- State facts, not opinions
- Include no emojis, checkboxes, or unnecessary formatting
- Provide sufficient detail for execution on clean VM with no context
- Link to source code with file:line references where applicable
- Be indexed in central `docs/INDEX.md`

## Phase 1: Parallel Document Analysis

### Task 1.1: Inventory All Markdown Files

Create comprehensive inventory with metadata:

**Script**: `scripts/docs/analyze_all_markdown.py`

**For each file**, extract:
- Full path
- Line count, word count
- First commit date (`git log --follow --diff-filter=A`)
- Last modified date (`git log -1 --follow`)
- Number of commits (`git log --follow --oneline | wc -l`)
- Files that reference this doc (`grep -r "filename" --include="*.py" --include="*.md"`)
- Files this doc references (extract markdown links)
- Category (inferred from path and content)

**Output**: `docs/analysis/inventory.json`

```json
{
  "analyzed_at": "2025-11-14T19:30:00Z",
  "total_files": 164,
  "total_lines": 109825,
  "files": [
    {
      "path": "README.md",
      "lines": 234,
      "words": 1543,
      "first_commit": "2024-01-15",
      "last_modified": "2025-11-14",
      "commit_count": 47,
      "referenced_by_code": ["Backtest/__init__.py:5"],
      "referenced_by_docs": ["docs/getting-started.md:12"],
      "references": ["CLAUDE.md", "docs/architecture/overview.md"],
      "category": "root_essential"
    },
    {
      "path": "POLARS_MIGRATION_COMPLETE.md",
      "lines": 156,
      "words": 892,
      "first_commit": "2024-08-15",
      "last_modified": "2024-08-20",
      "commit_count": 3,
      "referenced_by_code": [],
      "referenced_by_docs": [],
      "references": ["POLARS_MIGRATION_PLAN.md"],
      "category": "completed_task"
    }
  ]
}
```

**Execution**:
```bash
python scripts/docs/analyze_all_markdown.py > docs/analysis/inventory.json
```

### Task 1.2: Categorize Documents

Based on inventory, categorize each file:

**Categories**:
- `essential`: README.md, CLAUDE.md, CONTRIBUTING.md
- `active_docs`: Current API docs, user guides, architecture
- `design`: Design decisions, still relevant
- `reference`: Book summaries, paper summaries
- `completed_task`: Phase summaries, migration complete docs
- `outdated`: Superseded by newer docs
- `redundant`: Duplicate content
- `orphan`: No references, no recent updates

**Script**: `scripts/docs/categorize_docs.py`

**Output**: `docs/analysis/categorization.json`

```json
{
  "essential": ["README.md", "CLAUDE.md"],
  "active_docs": ["docs/BACKTEST_UNIFIED_API.md", ...],
  "design": ["docs/design/BACKTEST_UNIFICATION_PLAN.md", ...],
  "reference": ["docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md", ...],
  "completed_task": ["POLARS_MIGRATION_COMPLETE.md", "PHASE_3_COMPLETION_SUMMARY.md", ...],
  "outdated": ["docs/GENERIC_BACKTEST_PROGRESS.md", ...],
  "redundant": ["GRINOLD_KAHN_FRAMEWORK.md", "docs/GRINOLD_KAHN_DETAILED_SPECS.md", ...],
  "orphan": ["docs/old_design.md", ...]
}
```

### Task 1.3: Identify Consolidation Groups

Find related documents that should be merged:

**Consolidation Groups**:

1. **Grinold-Kahn Documentation** (15 files):
   - GRINOLD_KAHN_DETAILED_SPECS.md
   - GRINOLD_KAHN_FRAMEWORK.md
   - GRINOLD_KAHN_IMPLEMENTATION_GAP_ANALYSIS.md
   - docs/books/grinold_kahn_equity_notes_part1_foundations.md
   - docs/books/grinold_kahn_equity_notes_part2_valuation.md
   - docs/books/grinold_kahn_equity_notes_part3_forecasting.md
   - docs/books/grinold_kahn_equity_notes_part4_implementation.md
   - docs/design/GRINOLD_KAHN_KNOWLEDGE_GRAPH.md
   - (others)
   - **Target**: `docs/architecture/grinold-kahn-framework.md`

2. **Backtest Documentation** (8 files):
   - BACKTEST_UNIFICATION_TASK.md
   - docs/GENERIC_BACKTEST_IMPLEMENTATION_PLAN.md
   - docs/GENERIC_BACKTEST_MIGRATION_PLAN.md
   - docs/GENERIC_BACKTEST_PROGRESS.md
   - docs/design/BACKTEST_UNIFICATION_PLAN.md
   - **Keep**: docs/BACKTEST_UNIFIED_API.md (current)
   - **Archive**: Planning/progress docs
   - **Target**: docs/architecture/backtest-evolution.md (historical)

3. **Phase Summaries** (12 files):
   - PHASE1_COMPLETE_SUMMARY.md
   - PHASE_3_COMPLETION_SUMMARY.md
   - PHASE_4_COMPLETION_SUMMARY.md
   - SESSION_SUMMARY_2025-11-11.md
   - (others)
   - **Target**: CHANGELOG.md

4. **Migration Documents** (4 files):
   - POLARS_MIGRATION_PLAN.md
   - POLARS_MIGRATION_COMPLETE.md
   - **Target**: docs/archive/migrations/polars-migration.md

5. **Book Chunks** (37 files):
   - docs/books/grinold_kahn_markdown/grinold_kahn_chunk_001-032.md
   - **Action**: Keep INDEX.md, archive individual chunks

**Output**: `docs/analysis/consolidation-plan.json`

## Phase 2: Documentation Structure

### Target Structure

```
/
├── README.md                          # Project overview
├── CLAUDE.md                          # Development guidelines
├── CONTRIBUTING.md                    # How to contribute
├── CHANGELOG.md                       # Project history
├── docs/
│   ├── INDEX.md                       # Central documentation index
│   │
│   ├── architecture/
│   │   ├── overview.md               # System architecture
│   │   ├── class-hierarchy.md        # Auto-generated Mermaid
│   │   ├── data-flow.md              # Auto-generated Mermaid
│   │   ├── module-dependencies.md    # Auto-generated Mermaid
│   │   ├── grinold-kahn.md          # Consolidated GK docs
│   │   └── backtest-design.md        # Backtest architecture
│   │
│   ├── user-guides/
│   │   ├── installation.md           # Setup on clean VM
│   │   ├── quickstart.md             # First backtest
│   │   ├── creating-strategies.md    # Strategy development
│   │   ├── custom-signals.md         # Signal development
│   │   └── extending-risk-models.md  # Risk model extension
│   │
│   ├── api-reference/                 # Auto-generated from code
│   │   ├── backtest.md
│   │   ├── signals.md
│   │   ├── risk.md
│   │   ├── optimizer.md
│   │   ├── portfolio.md
│   │   └── query.md
│   │
│   ├── design/                        # Design decisions
│   │   ├── returns-first.md
│   │   ├── query-signal-bridges.md
│   │   └── portfolio-composition.md
│   │
│   ├── references/
│   │   ├── papers.md                 # Research paper summaries
│   │   └── books.md                  # Book summaries
│   │
│   └── archive/                       # Historical documents
│       ├── completed-tasks/
│       ├── migrations/
│       ├── phase-summaries/
│       └── book-chunks/
```

### Central Index Structure

**File**: `docs/INDEX.md`

```markdown
# ARBS Documentation Index

## Getting Started

- [Installation](user-guides/installation.md) - Setup instructions for clean VM
- [Quick Start](user-guides/quickstart.md) - Run your first backtest
- [Contributing](../CONTRIBUTING.md) - Development guidelines

## Architecture

- [System Overview](architecture/overview.md) - High-level design
- [Class Hierarchy](architecture/class-hierarchy.md) - Class inheritance (auto-generated)
- [Data Flow](architecture/data-flow.md) - Signal → Portfolio flow (auto-generated)
- [Module Dependencies](architecture/module-dependencies.md) - Import graph (auto-generated)
- [Grinold-Kahn Framework](architecture/grinold-kahn.md) - GK implementation
- [Backtest Design](architecture/backtest-design.md) - Backtest architecture

## User Guides

- [Creating Strategies](user-guides/creating-strategies.md) - Strategy development workflow
- [Custom Signals](user-guides/custom-signals.md) - Implementing signals
- [Extending Risk Models](user-guides/extending-risk-models.md) - Risk model development

## API Reference

- [Backtest](api-reference/backtest.md) - Backtest.Backtest class (auto-generated)
- [Signals](api-reference/signals.md) - Signal classes (auto-generated)
- [Risk Models](api-reference/risk.md) - Risk estimation (auto-generated)
- [Optimizers](api-reference/optimizer.md) - Portfolio optimization (auto-generated)
- [Portfolio](api-reference/portfolio.md) - Portfolio classes (auto-generated)
- [Query System](api-reference/query.md) - Query workflow (auto-generated)

## Design Decisions

- [Returns-First Design](design/returns-first.md) - Why returns over prices
- [Query-Signal Bridges](design/query-signal-bridges.md) - Bridging workflows
- [Portfolio Composition](design/portfolio-composition.md) - Nested portfolios

## References

- [Research Papers](references/papers.md) - Relevant academic papers
- [Books](references/books.md) - Book summaries

## Archive

- [Completed Tasks](archive/completed-tasks/) - Historical task documentation
- [Migrations](archive/migrations/) - Migration records
- [Phase Summaries](archive/phase-summaries/) - Development phases
```

## Phase 3: Auto-Generation Tools

### Tool 1: Class Diagram Generator

**Script**: `scripts/docs/generate_class_diagrams.py`

**Algorithm**:
1. Parse Python files with `ast` module
2. Extract class definitions and inheritance
3. Extract public methods and key attributes
4. Generate Mermaid `classDiagram` syntax
5. Write to `docs/architecture/class-hierarchy.md`

**Usage**:
```bash
python scripts/docs/generate_class_diagrams.py
```

**Output Example**:
```markdown
# Class Hierarchy

Auto-generated: 2025-11-14 19:30:00
Source: Backtest/, Signals/, Risk/, Optimizer/, Asset/

## Backtest System

[Mermaid diagram showing BaseBacktest → Backtest with methods]

## Signal System

[Mermaid diagram showing BaseSignal → CarrySignal, MomentumSignal, etc.]

## Source Code References

- Backtest.Backtest: [Backtest/Backtest.py:73-642](../Backtest/Backtest.py#L73)
- BaseSignal: [Signals/Base/BaseSignal.py:27-241](../Signals/Base/BaseSignal.py#L27)
```

### Tool 2: Data Flow Diagram Generator

**Script**: `scripts/docs/generate_flow_diagrams.py`

**Algorithm**:
1. Define key workflows manually (templates)
2. Extract method calls from code with `ast`
3. Verify flow matches actual code
4. Generate Mermaid `flowchart` syntax
5. Write to `docs/architecture/data-flow.md`

**Workflows**:
- Signal-based backtest: Backtest.run() → adapter → signals → alpha → optimizer → result
- Query-based backtest: Backtest.run_from_queries() → MDP → queries → MTM → result
- Grinold-Kahn optimization: signals → z-scores → alphas → covariance → weights

**Usage**:
```bash
python scripts/docs/generate_flow_diagrams.py
```

### Tool 3: Module Dependency Graph

**Script**: `scripts/docs/generate_dependency_graph.py`

**Algorithm**:
1. Parse all Python files
2. Extract `import` and `from X import Y` statements
3. Build dependency graph
4. Generate Mermaid `graph` syntax
5. Write to `docs/architecture/module-dependencies.md`

**Usage**:
```bash
python scripts/docs/generate_dependency_graph.py
```

### Tool 4: API Reference Generator

**Script**: `scripts/docs/generate_api_docs.py`

**Algorithm**:
1. Use `pdoc` or custom parser
2. Extract docstrings from classes and methods
3. Format as markdown with code examples
4. Include source code links (file:line)
5. Write to `docs/api-reference/*.md`

**Usage**:
```bash
python scripts/docs/generate_api_docs.py
```

### Master Regeneration Command

**Makefile**:
```makefile
docs:
	python scripts/docs/generate_class_diagrams.py
	python scripts/docs/generate_flow_diagrams.py
	python scripts/docs/generate_dependency_graph.py
	python scripts/docs/generate_api_docs.py
	@echo "Documentation regenerated"
```

**Usage**:
```bash
make docs
```

## Phase 4: Execution on Clean VM

### Prerequisites

```bash
# Python 3.11+
python --version

# Git
git --version
```

### Step 1: Clone and Branch

```bash
cd ~
git clone https://github.com/pfin/ARBS.git
cd ARBS

# Create branch
BRANCH_NAME="claude/docs-cleanup-$(date +%s)"
git checkout -b "$BRANCH_NAME"
echo "$BRANCH_NAME" > .branch-name
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
pip install pdoc3 networkx
```

### Step 3: Analyze All Documentation

```bash
# Create analysis directory
mkdir -p docs/analysis scripts/docs

# Run analysis (outputs JSON)
python scripts/docs/analyze_all_markdown.py > docs/analysis/inventory.json

# Categorize documents
python scripts/docs/categorize_docs.py

# Identify consolidation groups
python scripts/docs/identify_consolidations.py
```

### Step 4: Review Analysis

```bash
# Generate human-readable report
python scripts/docs/generate_report.py > docs/analysis/REPORT.md

# Review
less docs/analysis/REPORT.md
```

### Step 5: Execute Cleanup

```bash
# Dry run first
python scripts/docs/execute_cleanup.py --dry-run

# Review changes
git status

# Execute
python scripts/docs/execute_cleanup.py

# Create new structure
python scripts/docs/create_structure.py
```

### Step 6: Generate Auto-Docs

```bash
make docs
```

### Step 7: Validate

```bash
# Validate all links
python scripts/docs/validate_links.py

# Validate Mermaid syntax
python scripts/docs/validate_mermaid.py
```

### Step 8: Commit and Push

```bash
git add -A
git commit -m "docs: comprehensive cleanup and auto-generation

Analysis Results:
- Analyzed: 164 markdown files (~110K lines)
- Archived: X completed task docs
- Consolidated: Y related documents
- Deleted: Z redundant files

New Structure:
- Central index at docs/INDEX.md
- Auto-generated class diagrams (Mermaid)
- Auto-generated flow charts (Mermaid)
- Auto-generated module dependency graphs (Mermaid)
- Auto-generated API reference docs
- Manual regeneration via 'make docs'

Result: Unified indexed documentation system
"

git push -u origin "$(cat .branch-name)"
```

## Orthogonal Task Breakdown

### Group A: Analysis Scripts (Parallel)

**A1**: scripts/docs/analyze_all_markdown.py (30 min)
**A2**: scripts/docs/categorize_docs.py (20 min)
**A3**: scripts/docs/identify_consolidations.py (20 min)
**A4**: scripts/docs/generate_report.py (15 min)

### Group B: Generation Scripts (Parallel)

**B1**: scripts/docs/generate_class_diagrams.py (45 min)
**B2**: scripts/docs/generate_flow_diagrams.py (45 min)
**B3**: scripts/docs/generate_dependency_graph.py (30 min)
**B4**: scripts/docs/generate_api_docs.py (45 min)

### Group C: Execution Scripts (Parallel)

**C1**: scripts/docs/execute_cleanup.py (30 min)
**C2**: scripts/docs/create_structure.py (20 min)
**C3**: scripts/docs/validate_links.py (20 min)
**C4**: scripts/docs/validate_mermaid.py (15 min)

### Group D: Content Consolidation (Sequential)

**D1**: Consolidate Grinold-Kahn docs → docs/architecture/grinold-kahn.md (45 min)
**D2**: Consolidate backtest docs → docs/architecture/backtest-design.md (30 min)
**D3**: Consolidate phase summaries → CHANGELOG.md (30 min)
**D4**: Create docs/INDEX.md (20 min)
**D5**: Create user guides from existing content (60 min)

## Timeline Estimate

**Phase 1 (Analysis)**: 2 hours
**Phase 2 (Structure)**: 2 hours
**Phase 3 (Auto-Gen)**: 4 hours
**Phase 4 (Execution)**: 1 hour

**Total**: 9 hours wall-clock time with parallelization

## Success Criteria

**Analysis Complete**:
- inventory.json exists with 164 files
- categorization.json categorizes all files
- consolidation-plan.json identifies merge groups

**Structure Complete**:
- docs/INDEX.md exists and links to all active docs
- All active docs accessible from index
- Archive directory contains historical docs

**Auto-Generation Working**:
- Class diagrams render in Mermaid
- Flow charts render in Mermaid
- Dependency graphs render in Mermaid
- API docs generated from docstrings
- Source code links work (file:line format)

**Validation Passing**:
- All internal links resolve
- All Mermaid syntax valid
- All code examples reference existing code
- No orphaned documents

**Final State**:
- Single command regenerates all auto-docs: `make docs`
- Clear navigation from README → docs/INDEX.md → any topic
- All documentation accurate as of commit date
