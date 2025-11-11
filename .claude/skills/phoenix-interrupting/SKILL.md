---
name: phoenix-interrupting
description: Prevent toxic completion loops through interrupt monitoring. Use when long-running tasks risk drift, implementation might proceed in wrong direction, or need to kill bad paths before false completion. Sets 5-minute interrupt checkpoints.
---

# Phoenix Interrupting

**Purpose**: Stop toxic completion patterns before they claim success without value delivery.

## The Problem

**LLMs always end with positive reinforcement, even when failing.** This creates toxic feedback loops where bad processes complete with "I successfully analyzed..." without producing code or value.

**Critical Insight**: Once execution starts without interrupt capability, you can only watch or kill it - you cannot redirect it.

## When to Use

- Long-running tasks (>5 minutes)
- Research or analysis that might spiral
- Implementation of unfamiliar patterns
- Tasks with unclear success criteria
- Any work that could drift from "do" to "plan"

## Interrupt System

### 1. Set Interrupt Checkpoints

**Every 5 minutes**, pause and evaluate:

```
CHECKPOINT QUESTIONS:
1. Have I created or modified code files? (Y/N)
2. Am I researching instead of implementing? (Y/N)
3. Am I planning future work instead of doing current work? (Y/N)
4. Would I describe my progress as "I successfully analyzed..."? (Y/N)
```

**If ANY answer indicates drift → INTERRUPT IMMEDIATELY**

### 2. Toxic Pattern Detection

**Watch for these patterns**:

- **Research Spiral**: Reading docs, exploring codebases, analyzing patterns without writing code
- **Planning Loop**: Creating roadmaps, designs, architectures without implementation
- **Positive Completion Without Value**: "I successfully analyzed the requirements" (but no code written)
- **Tool Tourism**: Using Read, Grep, WebFetch excessively without Edit/Write
- **Meta-Work**: Organizing, documenting, planning instead of building

### 3. Interrupt Actions

**When toxic pattern detected**:

1. **STOP current execution immediately**
2. **Document findings** (what was learned, why path was toxic)
3. **Pivot to implementation** (write actual code instead)
4. **Set tighter checkpoint** (reduce to 3-minute intervals)

### 4. Recovery Mechanisms

**After interrupt, choose recovery path**:

**Path A - Redirect**:
- Keep partial work but change approach
- Switch from research to implementation
- Use findings to write code immediately

**Path B - Kill Branch**:
- Abandon this approach entirely
- Return to last known good state
- Try different approach (see skill: `expanding-then-compressing`)

**Path C - Decompose**:
- Break into smaller 5-minute tasks
- Each subtask must produce file changes
- Execute tasks sequentially with checkpoints

## Implementation Pattern

```python
def execute_with_phoenix(task, timeout=300):
    """Execute task with Phoenix interrupt monitoring"""
    start = time.time()
    file_changes_at_start = get_file_changes()

    while not task.complete:
        # Phoenix interrupt every 5 minutes
        if time.time() - start > timeout:
            current_changes = get_file_changes()

            if current_changes == file_changes_at_start:
                # No files changed = toxic pattern
                task.interrupt("No file changes detected")
                return task.recovery_plan()

            # Reset timer for next interval
            start = time.time()
            file_changes_at_start = current_changes

        task.step()

    return task.result()
```

## Interrupt Thresholds

**Automatic Interrupt Triggers**:

- **No file changes after 5 minutes**: High priority interrupt
- **Read/Grep ratio > 10:1 vs Write/Edit**: Research spiral detected
- **Planning tokens > implementation tokens**: Meta-work loop
- **"Successfully" in output without file changes**: Toxic completion

## Checklist

- [ ] Set 5-minute timer for checkpoint
- [ ] Defined "done" as code files changed, not analysis complete
- [ ] Identified potential toxic patterns for this task
- [ ] Created recovery plan if interrupt needed
- [ ] Monitoring file changes throughout execution
- [ ] Ready to kill branch if showing toxic patterns

## Common Mistakes

**Ignoring Soft Signals**: Waiting for obvious failure instead of early intervention
- **Fix**: Interrupt at first sign of drift, not after complete derailment

**Planning the Interrupt**: Meta-analyzing whether to interrupt
- **Fix**: If asking "should I interrupt?" - the answer is YES

**Saving Toxic Work**: Trying to salvage research/planning output
- **Fix**: Shadow paths teach through experience, not through documentation

**Too Long Intervals**: Using 10-15 minute checkpoints
- **Fix**: 5 minutes is maximum - shorter is better for risky tasks

## Related Skills

- `expanding-then-compressing` - Use interrupts during exploration phase
- `interrupting-toxic-loops` - MCTS-level interrupt orchestration
- `midnight-building` - Interrupt patterns for focused sessions
- `analyzing-with-mcts` - Evaluate interrupt decisions with MCTS

## Advanced Topics

See resources in this skill folder:
- `advanced-1-interrupt-rules.md` - Complete rule system for detection
- `advanced-2-temporal-aggregation.md` - Exponential decay scoring
- `advanced-3-recovery-strategies.md` - Recovery pattern catalog
