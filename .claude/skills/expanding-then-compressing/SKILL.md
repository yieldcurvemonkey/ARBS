---
name: expanding-then-compressing
description: Apply Shadow Monte Carlo exploration - implement 3-5 different approaches, explore orthogonal solutions, then compress to essence. Use when facing complex implementation decisions, exploring design spaces, or identifying butterfly points (small changes with large impacts).
---

# Expanding-Then-Compressing

**Pattern**: Expand exploration space first, then compress to optimal solution.

## When to Use

- Complex implementation with multiple valid approaches
- Unfamiliar problem domain requiring exploration
- Need to identify "butterfly points" (high-leverage parameters)
- Risk of premature optimization or local maxima
- Trade-offs between different solution characteristics

## Two-Phase Process

### Phase 1: EXPAND (Exploration)

**Goal**: Generate diverse approaches to understand the solution space.

**Steps**:
1. **Generate 3-5 Different Implementations**
   - Try orthogonal solutions (different algorithms/patterns)
   - Don't optimize yet - let complexity emerge naturally
   - Include "shadow paths" - implementations you might not use but teach you something

2. **Shadow MC Principle**
   - Run parallel explorations like MCTS branches
   - Each path reveals constraints and opportunities
   - Failed paths are data, not waste
   - The "shadow" implementations inform the final choice

3. **Set Phoenix Interrupts** (see skill: `phoenix-interrupting`)
   - Every 5 minutes check: "Is this path toxic?"
   - Kill branches showing endless complexity without value
   - Let critical insight interrupt positive completion bias

**Example - Daily Overnight Forwards**:
```python
# Method 1: Direct calculation
forwards = [curve.rate(d, d+1day) for d in dates]

# Method 2: Using dual numbers
forwards = [curve.forward_rate(d) for d in dates]

# Method 3: Finite differences
forwards = np.diff(np.log(dfs)) * 365

# Method 4: Analytical derivatives
forwards = -curve.zero_rate_derivatives(dates)
```

### Phase 2: COMPRESS (Optimization)

**Goal**: Reduce to minimal complexity that preserves functionality.

**Steps**:
1. **Pattern Recognition**
   - Identify common patterns across all implementations
   - Find the invariants - what stays constant across approaches
   - Recognize the "butterfly points" - small changes with large impacts

2. **Refactor to Essence**
   - Remove redundancy discovered through expansion
   - Combine best aspects of different paths
   - Compress to minimal complexity
   - Externalize variation points to configuration (YAML/JSON)

3. **Butterfly Targeting**
   - Identify the 3-5 critical control points
   - These are the "knobs" that control system behavior
   - Everything else becomes fixed infrastructure

**Example - Compressed Result**:
```yaml
# All methods reduce to configuration
daily_forwards:
  method: analytical  # or direct, dual, finite_diff
  convention: act360
  dates: {start: 2024-01-01, end: 2025-01-01}
```

## Implementation Checklist

- [ ] Defined problem and success criteria clearly
- [ ] Generated at least 3 different approaches
- [ ] Implemented or prototyped each approach
- [ ] Set Phoenix interrupt checkpoints (5-10 min intervals)
- [ ] Identified common patterns across approaches
- [ ] Recognized butterfly points (high-leverage parameters)
- [ ] Compressed to minimal implementation
- [ ] Externalized variation to configuration
- [ ] Tested compressed solution maintains functionality

## Common Mistakes

**Premature Compression**: Jumping to "best" solution without exploration
- **Fix**: Force yourself to implement at least 3 approaches first

**Ignoring Shadow Paths**: Dismissing "failed" approaches too quickly
- **Fix**: Document what each approach teaches, even failures

**Missing Butterfly Points**: Not identifying high-leverage parameters
- **Fix**: Track which small changes caused large behavior shifts

**Over-Engineering Compression**: Making configuration too flexible
- **Fix**: Only externalize parameters that actually vary in practice

## Related Skills

- `phoenix-interrupting` - Use during expansion to kill toxic paths
- `analyzing-with-mcts` - MCTS framework for evaluating approaches
- Domain-specific skills apply this pattern:
  - `analyzing-rateslib` (quantitative finance)
  - `building-with-nextjs` (web development)
  - `cultivating-consciousness` (AI development)

## Advanced Topics

For deeper patterns, see resources in this skill folder:
- `advanced-1-shadow-paths.md` - Structuring parallel explorations
- `advanced-2-butterfly-detection.md` - Identifying high-leverage parameters
- `advanced-3-compression-patterns.md` - Common compression architectures
