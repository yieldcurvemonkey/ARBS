---
name: midnight-building
description: Optimize for late-night focused implementation sessions. Use when building in evening/night hours, working in focused flow states, or managing energy for sustained technical work. Based on documented midnight building patterns.
---

# Midnight Building

**Context**: Deep technical work during evening/night hours when interruptions are minimal and focus is maximal.

## When to Use

- Evening/night work sessions (after regular hours)
- Deep technical implementation requiring sustained focus
- Complex problems needing uninterrupted thought
- Architecture decisions requiring mental model stability
- Flow state work (coding, designing, problem-solving)

## Session Structure

### Phase 1: Warm-Up (30 min)
- Review previous session's work
- Run tests to verify current state
- Quick wins to build momentum
- Load mental context

### Phase 2: Deep Work (90-120 min)
- Core implementation task
- Sustained focus on single problem
- Minimize context switching
- Phoenix interrupts every 5 min (see skill: `phoenix-interrupting`)

### Phase 3: Wind-Down (30 min)
- Document current state
- Commit working code
- Note blockers for next session
- Clean exit point

**Total session: 2.5-3 hours maximum**

## Energy Management

**CHECK EVERY 60 MINUTES**:
1. Am I still solving problems or just typing?
2. Are errors increasing in frequency?
3. Am I re-reading the same code repeatedly?
4. Is progress still happening or am I stuck?

**Signs of Degradation**:
- Simple syntax errors increasing
- Re-reading documentation without absorbing
- Switching between tasks without completing
- Defensive about taking break
- "Just one more thing" thinking

**Response**: When degradation detected → COMMIT current work, document state, stop cleanly

## Optimal Midnight Tasks

**High Value** (do these):
- Complex architecture implementation
- Deep debugging requiring mental model
- Learning new frameworks/libraries
- Creative problem-solving
- "Expand" phase of expand-then-compress (see skill: `expanding-then-compressing`)

**Low Value** (save for daytime):
- Routine refactoring
- Documentation writing
- Organizational tasks
- Meeting preparation
- "Compress" phase (needs fresh perspective)

## Commitment Strategy

**Commit Frequently**:
- Every 30 minutes of progress
- Before trying risky refactoring
- When tests pass
- Before taking break

**Commit Messages**:
- Descriptive enough for morning review
- Include context for incomplete work
- Flag "WIP" clearly if mid-feature
- Note next steps

## Common Midnight Mistakes

**The "Just One More Feature" Trap**:
- Problem: Expanding scope as energy depletes
- Fix: Define scope before session, stick to it
- Recovery: Commit current state, stop cleanly

**Fighting Through Fatigue**:
- Problem: Continuing when errors increase
- Fix: Recognize degradation, commit and stop
- Why it matters: Tired debugging creates more bugs

**Starting New Exploration Late**:
- Problem: Beginning expansion phase with 1 hour left
- Fix: Front-load exploration, back-load consolidation
- Alternative: Do planning only, implement tomorrow

**Poor State Documentation**:
- Problem: Can't remember context next session
- Fix: Write explicit "Where I Left Off" notes
- Template: "Completed X, next is Y, blocker is Z"

## Integration with Other Skills

**Use Together**:
- `phoenix-interrupting` - Critical for preventing midnight research spirals
- `expanding-then-compressing` - Expansion fits midnight energy, compression fits morning clarity
- `analyzing-with-mcts` - Architecture decisions during peak focus time
- `planning-multi-timeframe` - Alpha execution at midnight, Beta/Gamma review in morning

**Avoid Together**:
- Don't do final code review at midnight (save for fresh eyes)
- Don't merge to main late night (mistakes are costly)
- Don't start new complex dependencies late (underestimate complexity)

## Checklist

- [ ] Clear interruption-free time block (2-3 hours)
- [ ] Defined specific scope for this session
- [ ] Environment prepared (references, tools ready)
- [ ] Committed previous work cleanly
- [ ] 60-minute energy check timer set
- [ ] Exit criteria defined (what "done" looks like)
- [ ] Morning handoff plan (how to resume)

## Session Template

```markdown
# Midnight Session - [DATE]

## Scope
- Primary goal: [specific, achievable]
- Stretch goal: [if energy permits]

## Starting State
- Last commit: [hash/message]
- Tests passing: [Y/N]
- Known blockers: [list]

## Progress Log
- [TIME]: [what was accomplished]

## Ending State
- Completed: [what finished]
- In progress: [what's partial]
- Next session: [what to tackle next]
- Blockers: [what's blocking progress]
```

## Related Skills

- `phoenix-interrupting` - Prevent late-night research spirals
- `expanding-then-compressing` - Expand at night, compress in morning
- `planning-multi-timeframe` - Use Alpha focus for midnight sessions

## Advanced Topics

See resources in this skill folder:
- `advanced-1-flow-optimization.md` - Maximizing deep work periods
- `advanced-2-context-preservation.md` - Efficient session handoff patterns
- `advanced-3-energy-calibration.md` - Learning your degradation signals
