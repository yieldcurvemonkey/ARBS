---
name: evaluating-alpha-beta-gamma
description: Coordinate decisions across three timeframes - Alpha (immediate/hours), Beta (tactical/days), Gamma (strategic/months). Use when decisions have different implications at different time horizons or when balancing short-term execution with long-term goals.
---

# Evaluating Alpha-Beta-Gamma

**Framework**: Multi-timeframe decision analysis across three horizons.

## The Three Timeframes

### Alpha Horizon (Hours to Days)
**Focus**: Immediate execution and tactical wins

**Questions**:
- What can I ship today?
- What's blocking progress right now?
- What quick win builds momentum?
- What's the minimum viable implementation?

**Characteristics**:
- Fast feedback loops
- Reversible decisions preferred
- Optimize for learning and iteration
- Tolerate technical debt if it unblocks

**Example Alpha Decisions**:
- Which API endpoint to implement first
- Whether to hardcode vs configure for MVP
- Use library X vs library Y for prototype
- Write test now vs defer to refactor

### Beta Horizon (Days to Weeks)
**Focus**: Tactical sustainability and quality

**Questions**:
- Will this be maintainable next week?
- What's the refactoring cost?
- How does this impact the team?
- What's the testing strategy?

**Characteristics**:
- Balance speed and quality
- Consider maintenance burden
- Technical debt must have payoff plan
- Integration with existing systems matters

**Example Beta Decisions**:
- API design that accommodates future features
- Test coverage strategy
- Code organization and module boundaries
- Performance optimization priorities

### Gamma Horizon (Months to Years)
**Focus**: Strategic positioning and architecture

**Questions**:
- Where is this system going?
- What capabilities enable future options?
- What are the architectural implications?
- How does this align with long-term vision?

**Characteristics**:
- Optionality is valuable
- Flexibility costs less than rigidity
- Consider ecosystem evolution
- Platform decisions matter greatly

**Example Gamma Decisions**:
- Database choice (SQL vs NoSQL)
- Monolith vs microservices
- Framework selection
- Build vs buy for core capabilities

## When to Use

- Decision has different implications at different time scales
- Short-term and long-term goals seem in conflict
- Need to justify technical debt or architectural investment
- Balancing shipping speed with sustainability
- Evaluating whether to refactor or continue with existing approach

## Evaluation Process

### Step 1: Analyze at Each Timeframe

**For each option, evaluate**:

```markdown
## Option: [Description]

### Alpha Impact (hours-days)
- Delivery speed: [fast/medium/slow]
- Learning value: [high/medium/low]
- Risk: [high/medium/low]
- Reversibility: [easy/hard/impossible]

### Beta Impact (days-weeks)
- Maintenance cost: [high/medium/low]
- Technical debt: [acceptable/concerning/blocking]
- Team velocity impact: [positive/neutral/negative]
- Quality implications: [strong/adequate/weak]

### Gamma Impact (months-years)
- Architectural alignment: [strong/neutral/poor]
- Future optionality: [increases/neutral/decreases]
- Ecosystem fit: [good/adequate/problematic]
- Strategic value: [high/medium/low]
```

### Step 2: Identify Tensions

**Common patterns**:
- **Alpha-Beta tension**: Fast now vs maintainable later
- **Beta-Gamma tension**: Good enough now vs architected for future
- **Alpha-Gamma alignment**: Quick win that opens strategic options

### Step 3: Make Explicit Trade-offs

**Decision patterns**:

**Optimize Alpha** (when):
- Learning is more valuable than perfection
- Requirements are uncertain
- Speed to market is critical
- Reversible decision

**Optimize Beta** (when):
- Foundation is shaky
- Team velocity degrading
- Technical debt accumulating
- Quality issues emerging

**Optimize Gamma** (when):
- Platform decision
- Hard to reverse later
- Strategic positioning matters
- Long-term differentiation

**Balance All Three** (when):
- Mission-critical systems
- Multiple stakeholders
- Complex interdependencies
- Mature products

## Practical Examples

### Example 1: Authentication System

**Alpha**: Hardcode API keys for MVP
- Fast: 1 hour to ship
- Learning: Validates user workflow
- Risk: Security concern but isolated environment
- Reversible: Easy to replace

**Beta**: Implement JWT with basic auth
- Maintenance: Standard patterns, team knows this
- Technical debt: None if done right
- Velocity: Unlocks other features
- Quality: Production-ready

**Gamma**: OAuth2 with identity provider
- Architecture: Industry standard, scales
- Optionality: Enables SSO, enterprise features
- Ecosystem: Integrates with auth ecosystem
- Strategic: Professional product requirement

**Decision**: Alpha for first 2 weeks (learn user flows), Beta by month 1 (production ready), Gamma when enterprise customers appear

### Example 2: Database Choice

**Alpha**: SQLite with JSON fields
- Fast: No setup, ships with app
- Learning: Validates data model
- Risk: Migration later but data is small
- Reversible: Can export to real DB

**Beta**: PostgreSQL with proper schema
- Maintenance: Well-understood operations
- Technical debt: None
- Velocity: Enables complex queries
- Quality: Production-grade

**Gamma**: Distributed database or specialized store
- Architecture: Prepared for scale
- Optionality: Handles future scenarios
- Ecosystem: Requires specialized knowledge
- Strategic: Might be premature

**Decision**: Beta (PostgreSQL) - Alpha is too limiting, Gamma is premature optimization

## Integration with Other Skills

**Use with**:
- `analyzing-with-mcts` - Run MCTS at each timeframe
- `planning-multi-timeframe` - Create plans addressing all horizons
- `midnight-building` - Alpha execution during night sessions
- `expanding-then-compressing` - Explore options before choosing timeframe focus

## Checklist

- [ ] Identified the decision to be made
- [ ] Evaluated implications at Alpha horizon
- [ ] Evaluated implications at Beta horizon
- [ ] Evaluated implications at Gamma horizon
- [ ] Identified tensions between timeframes
- [ ] Made explicit trade-off based on current context
- [ ] Documented decision rationale for future reference
- [ ] Set review point to re-evaluate if context changes

## Common Mistakes

**Premature Gamma Optimization**: Building for scale you don't have
- **Fix**: Start with Beta quality, upgrade to Gamma when actually needed

**Ignoring Beta**: Jumping from Alpha hacks to Gamma architecture
- **Fix**: Beta is where most systems should live most of the time

**Perpetual Alpha**: Never paying down technical debt
- **Fix**: Schedule explicit Beta refactoring sprints

**Single-Timeframe Thinking**: Evaluating only one horizon
- **Fix**: Force yourself to consider all three even if one dominates

## Related Skills

- `analyzing-with-mcts` - Multi-timeframe MCTS
- `planning-multi-timeframe` - Create multi-horizon plans
- `phoenix-interrupting` - Alpha interrupt cycles

## Advanced Topics

See resources in this skill folder:
- `advanced-1-timeframe-transitions.md` - When and how to shift between horizons
- `advanced-2-debt-payoff-planning.md` - Managing Alpha debt with Beta/Gamma payoff
- `advanced-3-strategic-optionality.md` - Gamma decisions that preserve future options
