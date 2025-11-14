# Agent Documentation Standards Guide

Created: 2025-11-14
Purpose: Unified standards for all agents working on ARBS documentation

## Overview

This guide provides instructions for agents analyzing, consolidating, and generating documentation. All agents must follow these standards to ensure consistency across the documentation system.

## Agent Types and Responsibilities

### Type 1: Analysis Agent

**Purpose**: Analyze markdown files and extract metadata

**Input**: Path to markdown file(s)

**Tasks**:
1. Extract file metadata (lines, words, commit history)
2. Identify category (essential, active, design, reference, completed_task, outdated, redundant, orphan)
3. Find references (to/from code and other docs)
4. Assess quality and relevance
5. Identify consolidation opportunities

**Output Format**:
```json
{
  "file": "path/to/file.md",
  "analysis": {
    "lines": 234,
    "words": 1543,
    "git_history": {
      "first_commit": "2024-01-15",
      "last_modified": "2025-11-14",
      "commit_count": 47,
      "recent_activity": true
    },
    "references": {
      "referenced_by_code": ["Backtest/__init__.py:5"],
      "referenced_by_docs": ["docs/getting-started.md:12"],
      "references_to_code": ["Backtest/Backtest.py:73"],
      "references_to_docs": ["CLAUDE.md", "docs/architecture/overview.md"]
    },
    "category": "active_docs",
    "quality_assessment": {
      "has_emojis": false,
      "has_checkboxes": true,
      "has_opinions": false,
      "clarity": "high",
      "completeness": "sufficient",
      "vm_executable": true
    },
    "recommendations": {
      "action": "keep_and_update",
      "reason": "Current API documentation with active references",
      "consolidate_with": [],
      "updates_needed": ["Remove checkboxes", "Add installation prerequisites"]
    }
  }
}
```

**Quality Criteria**:
- **Factual**: Document states facts, not opinions ("implements X" not "elegantly implements X")
- **Clear**: Sufficient detail for clean VM execution with no context
- **Concise**: No unnecessary adjectives or filler words
- **Formatted**: No emojis, minimal checkboxes, clean markdown
- **Linked**: References to code use file:line format
- **Current**: Reflects actual code state as of analysis date

**Category Definitions**:
- `essential`: Core project docs (README, CLAUDE.md, CONTRIBUTING)
- `active_docs`: Current API docs, user guides, architecture
- `design`: Design decisions that remain relevant
- `reference`: Book summaries, paper summaries
- `completed_task`: Phase summaries, migration complete docs, task records
- `outdated`: Superseded by newer docs or no longer accurate
- `redundant`: Duplicate content found elsewhere
- `orphan`: No references, no recent updates, unclear purpose

### Type 2: Consolidation Agent

**Purpose**: Merge related documents into unified documentation

**Input**: List of files to consolidate + target file path

**Tasks**:
1. Read all source documents
2. Extract unique information from each
3. Identify overlapping content
4. Create unified document structure
5. Write consolidated document following standards
6. Create archive references

**Output Format**:
```json
{
  "consolidation_id": "grinold-kahn-docs",
  "source_files": [
    "GRINOLD_KAHN_DETAILED_SPECS.md",
    "GRINOLD_KAHN_FRAMEWORK.md",
    "docs/books/grinold_kahn_equity_notes_part1_foundations.md"
  ],
  "target_file": "docs/architecture/grinold-kahn.md",
  "actions_taken": {
    "sections_created": [
      "Overview",
      "Mathematical Framework",
      "Implementation",
      "Code Examples",
      "References"
    ],
    "unique_content_preserved": {
      "GRINOLD_KAHN_DETAILED_SPECS.md": ["IC calculation details", "Covariance estimation"],
      "GRINOLD_KAHN_FRAMEWORK.md": ["Alpha generation formula"],
      "docs/books/grinold_kahn_equity_notes_part1_foundations.md": ["Fundamental Law derivation"]
    },
    "redundant_content_removed": [
      "Duplicate IC definitions across 3 files",
      "Repeated alpha formula in 2 files"
    ],
    "archive_files": [
      "docs/archive/completed-tasks/GRINOLD_KAHN_DETAILED_SPECS.md",
      "docs/archive/completed-tasks/GRINOLD_KAHN_FRAMEWORK.md"
    ]
  },
  "validation": {
    "all_links_work": true,
    "code_references_verified": true,
    "mermaid_syntax_valid": true
  }
}
```

**Consolidation Standards**:
- Preserve all unique technical information
- Remove duplicate explanations
- Use canonical names from codebase
- Link to actual code (file:line)
- Structure: Overview → Details → Examples → References
- Archive source files, don't delete

### Type 3: Generation Agent

**Purpose**: Auto-generate documentation from code

**Input**: Module/package path + generation type (class-diagram | flow-chart | dependency-graph | api-reference)

**Tasks**:
1. Parse Python code (AST or docstring extraction)
2. Extract relevant information
3. Generate markdown with Mermaid diagrams
4. Include source code links
5. Validate output

**Output Format**:
```json
{
  "generation_type": "class-diagram",
  "source_modules": ["Backtest/", "Signals/", "Risk/"],
  "output_file": "docs/architecture/class-hierarchy.md",
  "metadata": {
    "generated_at": "2025-11-14T19:30:00Z",
    "classes_found": 47,
    "inheritance_chains": 12,
    "mermaid_blocks": 4
  },
  "validation": {
    "mermaid_syntax_valid": true,
    "all_classes_have_source_links": true,
    "inheritance_verified": true
  },
  "sample_output": "```mermaid\nclassDiagram\n  BaseSignal <|-- CarrySignal\n  BaseSignal <|-- MomentumSignal\n```"
}
```

**Generation Standards**:

**Class Diagrams**:
- Include inheritance relationships
- Show public methods and key attributes
- Group by subsystem (Backtest, Signals, Risk, etc.)
- Link to source: `[ClassName](../path/to/file.py#L123)`

**Flow Charts**:
- Show actual method call sequences
- Verify flow matches code (don't invent)
- Use descriptive labels
- Include decision points

**Dependency Graphs**:
- Parse import statements only
- Show module-level dependencies
- Identify circular dependencies
- Group by package

**API Reference**:
- Extract docstrings verbatim
- Include method signatures
- Show parameter types and return types
- Include usage examples from docstrings
- Link to source code

### Type 4: Validation Agent

**Purpose**: Verify documentation quality and correctness

**Input**: File path(s) to validate

**Tasks**:
1. Check markdown syntax
2. Validate all links (internal and to code)
3. Validate Mermaid diagrams
4. Check code references exist
5. Verify examples run
6. Check formatting standards

**Output Format**:
```json
{
  "file": "docs/architecture/grinold-kahn.md",
  "validation_results": {
    "markdown_syntax": {
      "valid": true,
      "issues": []
    },
    "links": {
      "total": 23,
      "valid": 22,
      "broken": [
        {
          "link": "docs/old-file.md",
          "line": 45,
          "reason": "File not found"
        }
      ]
    },
    "code_references": {
      "total": 15,
      "valid": 15,
      "broken": []
    },
    "mermaid_diagrams": {
      "total": 3,
      "valid": 3,
      "syntax_errors": []
    },
    "formatting": {
      "has_emojis": false,
      "has_opinions": false,
      "uses_checkboxes": false,
      "clear_structure": true
    }
  },
  "overall_status": "pass",
  "issues_found": 1,
  "recommendations": ["Fix broken link at line 45"]
}
```

**Validation Rules**:
- All internal links must resolve
- All code references must point to existing files/lines
- Mermaid syntax must be valid (use mermaid-cli or parser)
- No emojis in technical documentation
- No opinion words (elegant, beautiful, powerful, etc.)
- No temporal references (recently, newly, old, legacy)
- No implementation details in names (ZodValidator, MCPWrapper)

## Documentation Writing Standards

### Structure Template

Every documentation file must follow this structure:

```markdown
# Title

[2-line summary of what this document covers]

## Overview

[High-level explanation of the topic]

## Prerequisites

[What reader needs to know/install before reading]

## Details

[Technical details, broken into subsections]

### Subsection 1
### Subsection 2

## Examples

[Concrete examples with code]

## Source Code References

- [ComponentName](../path/to/file.py#L123-L456)

## Related Documentation

- [Related Doc 1](./other-doc.md)

---

Last updated: 2025-11-14
```

### Language Standards

**Required**:
- Use present tense ("implements" not "will implement")
- Use active voice ("Backtest runs signals" not "signals are run")
- State facts ("uses LedoitWolf shrinkage" not "elegantly uses")
- Be specific ("requires Python 3.11+" not "requires recent Python")

**Forbidden**:
- Emojis (✅ ❌ 🚀 etc.)
- Checkboxes in prose (use bullet points instead)
- Opinion words (elegant, beautiful, powerful, robust, sophisticated)
- Temporal context (new, old, recently, legacy, improved, enhanced)
- Unnecessary adjectives (very, highly, extremely)
- Implementation details in names (unless they're actual class names)

**Code References**:
```markdown
Good: [Backtest.run()](../Backtest/Backtest.py#L234-L567)
Bad: [Backtest.run()](../Backtest/Backtest.py)
Bad: The backtest runner
```

**Examples**:
```markdown
Good: "The optimizer solves mean-variance optimization using CVXPY."
Bad: "The optimizer elegantly solves the complex mean-variance optimization problem using the powerful CVXPY library."

Good: "Backtest.run() executes signal workflow"
Bad: "The recently refactored Backtest.run() method now executes our improved signal workflow"

Good: "Requires Python 3.11 or later"
Bad: "Requires a recent version of Python"
```

## Feedback Protocol

### Real-Time Progress Updates

Each agent must report progress every 5 minutes:

```json
{
  "agent_id": "analysis-agent-003",
  "task": "analyzing-markdown-files",
  "batch": "files-21-30",
  "progress": {
    "total_files": 10,
    "completed": 7,
    "current_file": "docs/BACKTEST_UNIFIED_API.md",
    "estimated_completion": "2025-11-14T19:45:00Z"
  },
  "issues": [],
  "status": "in_progress"
}
```

### Completion Report

When agent finishes:

```json
{
  "agent_id": "analysis-agent-003",
  "task": "analyzing-markdown-files",
  "batch": "files-21-30",
  "status": "complete",
  "results": {
    "files_analyzed": 10,
    "categories": {
      "active_docs": 6,
      "outdated": 2,
      "redundant": 2
    },
    "recommendations": {
      "keep": 6,
      "archive": 2,
      "consolidate": 2
    }
  },
  "output_file": "docs/analysis/batch-21-30.json",
  "duration_seconds": 342
}
```

### Error Report

If agent encounters errors:

```json
{
  "agent_id": "generation-agent-002",
  "task": "generate-class-diagrams",
  "status": "error",
  "error": {
    "type": "ParseError",
    "message": "Cannot parse Signals/Base/BaseSignal.py:234 - syntax error",
    "file": "Signals/Base/BaseSignal.py",
    "line": 234,
    "recoverable": false
  },
  "partial_results": {
    "classes_processed": 12,
    "output_file": null
  },
  "recommendation": "Fix syntax error in source file before retrying"
}
```

## Coordination Between Agents

### Shared State Files

All agents read/write to shared JSON files:

**docs/analysis/state.json**:
```json
{
  "last_updated": "2025-11-14T19:30:00Z",
  "phase": "analysis",
  "batches": {
    "1-10": "complete",
    "11-20": "in_progress",
    "21-30": "pending"
  },
  "files_by_category": {
    "essential": 2,
    "active_docs": 34,
    "outdated": 12
  },
  "consolidation_groups": []
}
```

### Locking Protocol

Before modifying shared state:
1. Check if state file is locked (`state.lock` exists)
2. Wait if locked (max 30 seconds)
3. Create lock file
4. Read state
5. Modify state
6. Write state
7. Remove lock file

### Inter-Agent Dependencies

**Sequential Dependencies**:
- Analysis → Consolidation (must analyze before consolidating)
- Consolidation → Validation (must consolidate before validating)

**Parallel Safe**:
- Multiple analysis agents on different files
- Multiple generation agents on different modules
- Multiple validation agents on different files

## Commit and Push Guidelines

### Commit Frequency

Commit after each major milestone:
- After each batch of 10 files analyzed
- After each consolidation group completed
- After each auto-generation tool run
- After validation passes

### Commit Message Format

```
docs: [action] [scope]

[Summary of changes]

Details:
- [Detail 1]
- [Detail 2]

Files: [N] changed, [+X/-Y] lines
```

**Examples**:
```
docs: analyze markdown files batch 1-10

Analyzed first 10 markdown files for categorization and quality.

Details:
- 6 active docs identified
- 2 outdated docs flagged for archival
- 2 redundant docs identified for consolidation

Files: 1 changed, +245 lines
```

```
docs: consolidate Grinold-Kahn documentation

Merged 8 separate Grinold-Kahn documents into single reference.

Details:
- Created docs/architecture/grinold-kahn.md
- Preserved unique content from all sources
- Archived source files to docs/archive/
- Added source code links (12 references)

Files: 9 changed, +456/-2134 lines
```

### Push After Every Commit

ALWAYS push immediately after committing:
```bash
git push -u origin $(cat .branch-name)
```

VMs are ephemeral - commits only exist locally until pushed.

## Quality Checklist

Before marking work complete, verify:

**Analysis Agents**:
- [ ] All requested files analyzed
- [ ] Output JSON is valid
- [ ] Categories assigned with justification
- [ ] References extracted (to/from code and docs)
- [ ] Quality assessment completed
- [ ] Recommendations provided

**Consolidation Agents**:
- [ ] All source content reviewed
- [ ] Unique information preserved
- [ ] Redundancy eliminated
- [ ] Target file follows structure template
- [ ] Source files archived (not deleted)
- [ ] All links validated
- [ ] Code references verified

**Generation Agents**:
- [ ] Code parsed successfully
- [ ] Mermaid syntax validated
- [ ] Source code links included
- [ ] Output file follows template
- [ ] Metadata header included
- [ ] Examples tested (if applicable)

**Validation Agents**:
- [ ] All links checked
- [ ] All code references verified
- [ ] Mermaid diagrams validated
- [ ] Formatting standards enforced
- [ ] Issues documented
- [ ] Recommendations provided

## Common Pitfalls to Avoid

### For All Agents

**Don't**:
- Add opinions or subjective assessments
- Use emojis or excessive formatting
- Reference temporal context (new, old, recently)
- Skip validation steps
- Assume files exist without checking
- Modify shared state without locking
- Forget to push after committing

**Do**:
- State facts only
- Use clean, concise language
- Verify all references
- Report errors immediately
- Follow feedback protocol
- Coordinate via shared state
- Push after every commit

### For Analysis Agents

**Don't**:
- Categorize based on file name alone
- Ignore git history
- Miss cross-references
- Assume content is current without verification

**Do**:
- Read file content completely
- Check git log for activity
- Search for references (grep)
- Verify code references point to existing code

### For Consolidation Agents

**Don't**:
- Delete unique information
- Create new structure without template
- Merge unrelated content
- Break existing links unnecessarily

**Do**:
- Preserve all unique technical details
- Follow structure template
- Update links in other files
- Archive source files properly

### For Generation Agents

**Don't**:
- Invent information not in code
- Skip validation
- Create invalid Mermaid syntax
- Forget source code links

**Do**:
- Parse code directly (AST/docstrings)
- Validate output
- Test Mermaid rendering
- Include file:line references

### For Validation Agents

**Don't**:
- Skip checking code references
- Assume links work without testing
- Ignore formatting issues
- Pass validation with known issues

**Do**:
- Check every link
- Verify every code reference
- Enforce formatting standards
- Report all issues found

## Success Metrics

**Agent Performance**:
- Analysis: 10 files per 30 minutes
- Consolidation: 1 group per 45 minutes
- Generation: 1 module per 45 minutes
- Validation: 20 files per 30 minutes

**Quality Metrics**:
- Zero broken links in final documentation
- Zero invalid Mermaid diagrams
- Zero formatting violations
- 100% code references verified
- All files indexed in docs/INDEX.md

**Process Metrics**:
- Commits every 10 files or 1 hour (whichever comes first)
- Pushes after every commit
- Progress updates every 5 minutes
- Error reports within 1 minute of error

## Tools and Dependencies

**Required**:
- Python 3.11+
- Git 2.0+
- grep, find, wc (standard Unix tools)

**Python Packages**:
- `ast` (standard library - for parsing Python)
- `json` (standard library - for structured data)
- `pathlib` (standard library - for file paths)
- `subprocess` (standard library - for git commands)
- `pdoc3` (for API documentation generation)
- `mermaid-cli` (for Mermaid validation)

**Installation**:
```bash
pip install pdoc3 mermaid-cli
```

## Example Agent Workflows

### Analysis Agent Workflow

```python
# Pseudo-code for analysis agent

def analyze_markdown_file(filepath):
    # 1. Read file
    content = read_file(filepath)

    # 2. Extract metadata
    lines = count_lines(content)
    words = count_words(content)

    # 3. Git history
    first_commit = git_log_first_commit(filepath)
    last_modified = git_log_last_commit(filepath)
    commit_count = git_log_count(filepath)

    # 4. Find references
    referenced_by_code = grep_in_python_files(filename)
    referenced_by_docs = grep_in_markdown_files(filename)
    references_to = extract_markdown_links(content)

    # 5. Categorize
    category = categorize(filepath, content, commit_count, referenced_by_code)

    # 6. Quality assessment
    quality = assess_quality(content)

    # 7. Recommendations
    recommendations = generate_recommendations(category, quality, references_to)

    # 8. Output
    return {
        "file": filepath,
        "analysis": {
            "lines": lines,
            "words": words,
            "git_history": {...},
            "references": {...},
            "category": category,
            "quality_assessment": quality,
            "recommendations": recommendations
        }
    }
```

### Consolidation Agent Workflow

```python
# Pseudo-code for consolidation agent

def consolidate_documents(source_files, target_file):
    # 1. Read all sources
    contents = [read_file(f) for f in source_files]

    # 2. Extract unique information
    unique_sections = extract_unique_content(contents)

    # 3. Build consolidated structure
    consolidated = build_document(
        template="docs/templates/architecture.md",
        sections=unique_sections
    )

    # 4. Add metadata
    consolidated = add_metadata(
        consolidated,
        sources=source_files,
        generated_at=now()
    )

    # 5. Write target
    write_file(target_file, consolidated)

    # 6. Archive sources
    for source in source_files:
        archive_path = f"docs/archive/{source}"
        move_file(source, archive_path)

    # 7. Validate
    validation = validate_document(target_file)

    # 8. Output
    return {
        "consolidation_id": generate_id(),
        "source_files": source_files,
        "target_file": target_file,
        "validation": validation
    }
```

## References

- [CLAUDE.md](../CLAUDE.md) - Development guidelines
- [DOCUMENTATION_CLEANUP_PLAN.md](./DOCUMENTATION_CLEANUP_PLAN.md) - Overall cleanup plan
- [Python AST documentation](https://docs.python.org/3/library/ast.html)
- [Mermaid documentation](https://mermaid.js.org/)

---

Last updated: 2025-11-14
