---
name: analyzing-with-mcts
description: Apply Monte Carlo Tree Search framework to complex decisions. Use when evaluating options with uncertain outcomes, multi-step planning, or exploring decision trees. Includes Alpha (hours), Beta (days), Gamma (months) timeframe analysis.
---

# Analyzing with MCTS

**Framework**: Monte Carlo Tree Search for decision analysis and planning.

## When to Use

- Complex decisions with multiple options and uncertain outcomes
- Multi-step planning requiring look-ahead
- Trade-offs between exploration (trying new approaches) and exploitation (using known good approaches)
- Decisions requiring both immediate and long-term consideration
- Need to systematically explore solution space

## MCTS Phases

### 1. Selection

**Choose which branch to explore** based on:
- **Exploitation**: Branches with known good outcomes
- **Exploration**: Under-explored branches that might be better
- **UCB1 Formula**: Balance exploration/exploitation

```
UCB1 = average_value + C * sqrt(ln(total_visits) / branch_visits)
```

**In Practice**:
- High-value approaches that worked before (exploitation)
- Untried approaches that might surprise (exploration)
- C parameter controls exploration intensity (typically 1.414)

### 2. Expansion

**Generate new possibilities** from selected branch:
- What options exist from this state?
- What are the natural next steps?
- Which variations haven't been tried?

**Pattern**: Use `expanding-then-compressing` skill here for implementation expansion

### 3. Simulation

**Evaluate outcome** of this branch:
- Fast forward to see where this leads
- Estimate value using heuristics or quick tests
- Don't need perfect evaluation, just comparative signal

**Quick Evaluation Heuristics**:
- Code written vs documentation written (value = code)
- Tests passing vs tests failing (value = passing)
- Progress toward goal vs research (value = progress)
- User value delivered vs technical debt (value = user value)

### 4. Backpropagation

**Update beliefs** about all decisions in this path:
- Record outcome for this branch
- Update parent branches
- Adjust future selection probabilities

**Implementation**: Keep notes on what worked/didn't work, apply to future similar decisions

## Alpha-Beta-Gamma Integration

Apply MCTS at three timeframes (see skill: `evaluating-alpha-beta-gamma`):

**Alpha Horizon (hours to days)**:
- Fast MCTS iterations
- Immediate outcomes matter most
- Quick simulations (prototype, test, measure)

**Beta Horizon (days to weeks)**:
- Medium MCTS iterations
- Tactical implications
- Consider maintenance burden

**Gamma Horizon (months to years)**:
- Slow MCTS iterations
- Strategic positioning
- Architectural implications

## Practical Application

### Example: Choosing Implementation Approach

**Selection**:
- Already tried: REST API (worked well for CRUD)
- Unexplored: GraphQL (might be better for complex queries)
- Unexplored: gRPC (might be faster for internal services)

**Expansion**:
- For GraphQL: What would schema look like? What client libraries?
- For gRPC: What .proto definitions? What tooling needed?

**Simulation**:
- GraphQL: Quick prototype of one query, measure complexity
- gRPC: Estimate learning curve + tooling setup time

**Backpropagation**:
- If GraphQL prototype reveals high complexity → reduce future probability
- If gRPC estimate shows quick win → increase future probability

### Decision Template

```markdown
## MCTS Decision: [Problem]

### Options
1. [Option A] - [brief description]
2. [Option B] - [brief description]
3. [Option C] - [brief description]

### Selection Criteria
- Exploitation: [what's worked before]
- Exploration: [what's untried but promising]

### Expansion
- [Option chosen]: [specific next steps]

### Simulation
- Quick test: [how to evaluate quickly]
- Expected outcome: [hypothesis]

### Actual Result
- Outcome: [what happened]
- Learning: [what this teaches]
- Impact on future: [how this changes strategy]
```

## Integration with Other Skills

**MCTS as Meta-Skill**:
- `expanding-then-compressing` - Use during Expansion phase
- `phoenix-interrupting` - Use during Simulation phase (kill bad branches)
- `evaluating-alpha-beta-gamma` - Apply MCTS at all three timeframes
- Domain skills - MCTS guides which approach to try:
  - `analyzing-rateslib` vs `integrating-quantlib`
  - `building-with-nextjs` vs alternative frameworks

## Checklist

- [ ] Identified multiple valid approaches (at least 3)
- [ ] Defined quick evaluation criteria
- [ ] Selected branch using exploitation/exploration balance
- [ ] Expanded selected branch with concrete next steps
- [ ] Simulated outcome with quick test or prototype
- [ ] Backpropagated learning to inform future decisions
- [ ] Documented what worked/didn't for future reference

## Common Mistakes

**Pure Exploitation**: Always choosing known approaches
- **Fix**: Force exploration of 1-2 untried options per decision cycle

**Pure Exploration**: Constantly trying new things
- **Fix**: Use UCB1 formula to balance with proven approaches

**Expensive Simulations**: Building full implementations to evaluate
- **Fix**: Quick prototypes, thought experiments, or asking experts

**No Backpropagation**: Not learning from outcomes
- **Fix**: Always document "what we learned" after each attempt

## Related Skills

- `evaluating-alpha-beta-gamma` - Multi-timeframe MCTS application
- `expanding-then-compressing` - Structured expansion in MCTS
- `planning-multi-timeframe` - Planning with MCTS insights

## Advanced Topics

See resources in this skill folder:
- `advanced-1-ucb1-formula.md` - Mathematical details of exploitation/exploration
- `advanced-2-simulation-heuristics.md` - Quick evaluation techniques
- `advanced-3-decision-trees.md` - Visualizing MCTS decision spaces
