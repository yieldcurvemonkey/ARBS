---
name: interrupting-toxic-loops
description: Detect and interrupt toxic completion patterns where work proceeds without value delivery. Use when catching research spirals, endless planning without execution, or positive reinforcement without code changes. Implements Phoenix interrupt system at MCTS orchestration level.
---

# Interrupting Toxic Loops

**Purpose**: Orchestrate interrupt monitoring across multiple parallel work branches using MCTS decision framework.

## When to Use

- Managing multiple parallel implementation approaches
- Orchestrating complex projects with many subtasks
- Need systematic detection of unproductive work across all branches
- Coordinating team or multi-agent work
- Meta-level oversight of execution quality

## Relationship to Phoenix Interrupting

**This skill**: MCTS-level orchestration and branch management
**`phoenix-interrupting` skill**: Individual task-level interrupt monitoring

```
interrupting-toxic-loops (this skill)
  └─ Manages multiple branches
      ├─ Branch A: using phoenix-interrupting
      ├─ Branch B: using phoenix-interrupting
      └─ Branch C: using phoenix-interrupting
```

Use this skill when you need to:
- Compare progress across multiple approaches
- Kill underperforming branches
- Reallocate effort to winning branches
- Detect system-wide patterns (all branches showing same toxicity)

Use `phoenix-interrupting` when you need to:
- Monitor single task execution
- Set checkpoints within one implementation
- Detect individual drift patterns

## Multi-Branch Interrupt System

### 1. Branch Initialization

**For each approach/subtask**:
```markdown
Branch: [Name/Description]
- Goal: [Specific, measurable outcome]
- Success criteria: [How to know it worked]
- Timeout: [Maximum time before interrupt]
- Phoenix monitoring: [Y/N]
- File change tracking: [Which files should change]
```

### 2. Parallel Monitoring

**Track across all branches**:
- File changes per branch
- Time elapsed per branch
- Research vs implementation ratio per branch
- Value delivered per branch
- Resource consumption per branch

### 3. Comparative Interrupt Logic

**Interrupt conditions**:

**Absolute Thresholds** (per branch):
- No file changes after 5 minutes → Interrupt candidate
- Read/Grep ratio > 10:1 vs Write/Edit → Research spiral
- "Successfully" without code → Toxic completion

**Relative Thresholds** (across branches):
- Branch A delivers 3x value of Branch B → Kill Branch B
- Branch C shows same toxicity pattern as killed Branch D → Pre-emptive kill
- All branches in research mode → Systemic problem, reset all

### 4. Branch Lifecycle Management

**Branch states**:
- **Active**: Currently executing with monitoring
- **Suspended**: Paused for comparison with other branches
- **Killed**: Terminated, shadow data extracted
- **Promoted**: Chosen as primary approach
- **Merged**: Combined with another successful branch

**State transitions**:
```
Active → Suspended (checkpoint for comparison)
Active → Killed (toxic pattern detected)
Active → Promoted (clear winner emerges)
Suspended → Active (resume after comparison)
Suspended → Killed (comparison shows inferior)
```

## MCTS Integration

Use MCTS framework (see skill: `analyzing-with-mcts`) to manage branches:

### Selection
- Which branch to continue working on?
- Balance exploitation (winning approach) and exploration (new approaches)
- UCB1 score includes interrupt data

### Expansion
- When to spawn new branch?
- Triggered by: all branches toxic, or winning branch needs variation

### Simulation
- Quick evaluation of branch promise
- Use interrupt data as primary signal

### Backpropagation
- Update branch value based on outcomes
- Share learning across similar future branches

## Practical Implementation

### Example: Implementing New Feature

**Initialize branches**:
```markdown
Branch A: REST API approach
- Goal: Working endpoint with tests
- Timeout: 30 minutes
- Phoenix: Yes

Branch B: GraphQL approach
- Goal: Working query with schema
- Timeout: 30 minutes
- Phoenix: Yes

Branch C: gRPC approach
- Goal: .proto + basic service
- Timeout: 30 minutes
- Phoenix: Yes
```

**Monitor (5-minute checkpoint)**:
```markdown
Branch A (15 min elapsed):
- Files changed: 3 (endpoint, test, types)
- Progress: Endpoint working, tests failing
- Verdict: Continue

Branch B (15 min elapsed):
- Files changed: 1 (schema only)
- Progress: Still reading GraphQL docs
- Verdict: Interrupt candidate (research spiral)

Branch C (15 min elapsed):
- Files changed: 0
- Progress: "Successfully analyzed gRPC patterns"
- Verdict: KILL (toxic completion without code)
```

**Action**:
- Kill Branch C immediately (extract shadow data: "gRPC has steep learning curve")
- Suspend Branch B (might be viable but needs tighter scope)
- Promote Branch A (clear progress, continue with momentum)

### Example: Complex Refactoring

**Initialize branches**:
```markdown
Branch A: Incremental migration
Branch B: Big-bang rewrite
Branch C: Strangler fig pattern
```

**Monitor (10-minute checkpoint)**:
```markdown
Branch A: 50 files changed, tests passing incrementally
Branch B: 0 files changed, "designed new architecture"
Branch C: 5 files changed, new system running parallel

Interrupt decision:
- KILL Branch B (planning loop)
- CONTINUE Branch A (proven progress)
- CONTINUE Branch C (promising, different approach than A)
```

## Checklist

- [ ] All active branches identified and initialized
- [ ] Success criteria defined for each branch
- [ ] Phoenix monitoring enabled per branch
- [ ] Checkpoint intervals set (recommend 5-10 minutes)
- [ ] Comparison metrics defined (file changes, value delivery)
- [ ] Kill criteria established (absolute and relative)
- [ ] Shadow data extraction plan for killed branches
- [ ] Promotion criteria for winning branch

## Common Mistakes

**Sunk Cost Fallacy**: Continuing branch because of time invested
- **Fix**: Use MCTS backpropagation - past time is irrelevant, only future value matters

**Premature Branch Killing**: Interrupting before fair evaluation
- **Fix**: Minimum 2-3 checkpoints before comparison-based killing

**No Shadow Data Extraction**: Deleting failed branches without learning
- **Fix**: Always document "What this branch taught us" before killing

**Analysis Paralysis**: Spending more time comparing than executing
- **Fix**: Interrupt comparisons are themselves checkpoint-monitored (meta-interrupt)

## Related Skills

- `phoenix-interrupting` - Individual branch monitoring (use within this)
- `analyzing-with-mcts` - Decision framework for branch management
- `expanding-then-compressing` - Generate branches to monitor
- `evaluating-alpha-beta-gamma` - Apply at different timeframes

## Advanced Topics

See resources in this skill folder:
- `advanced-1-multi-agent-orchestration.md` - Coordinating multiple AI agents
- `advanced-2-resource-allocation.md` - Dynamic effort distribution across branches
- `advanced-3-pattern-recognition.md` - Detecting systemic vs local toxicity
