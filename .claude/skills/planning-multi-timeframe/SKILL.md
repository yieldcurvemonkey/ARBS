---
name: planning-multi-timeframe
description: Create plans that explicitly address immediate execution, tactical adjustments, and strategic positioning. Use when complex projects require coordination across different time horizons or when balancing urgency with long-term architecture.
---

# Planning Multi-Timeframe

**Purpose**: Create execution plans that explicitly coordinate Alpha (immediate), Beta (tactical), and Gamma (strategic) horizons.

## When to Use

- Complex projects spanning weeks to months
- Need to balance shipping speed with quality and architecture
- Team coordination requiring different time perspectives
- Product development with immediate, near-term, and long-term goals
- Technical debt management while delivering features

## Planning Structure

### Three-Horizon Plan Template

```markdown
# Project: [Name]

## Alpha Horizon (This Week)
**Goal**: Ship value and learn

### Immediate Wins (Today/Tomorrow)
- [ ] [Specific deliverable - must produce working code]
- [ ] [Quick win that validates approach]
- [ ] [Unblock critical path]

### This Week's Sprint
- [ ] [Feature/capability to deliver by Friday]
- [ ] [Key learning to validate]
- [ ] [Risk to retire]

**Phoenix Checkpoints**: Every 5 minutes during execution
**Success Metric**: [Measurable outcome by end of week]

## Beta Horizon (This Month)
**Goal**: Build sustainable, quality foundation

### Quality Gates
- [ ] [Test coverage target]
- [ ] [Performance requirement]
- [ ] [Documentation standard]

### Technical Debt Payoff
- [ ] [Alpha hack to refactor]
- [ ] [Code quality improvement]
- [ ] [Architecture alignment]

### Capability Building
- [ ] [Core feature set completion]
- [ ] [Integration with existing systems]
- [ ] [Team knowledge sharing]

**Review Cadence**: Weekly assessment of Beta progress
**Success Metric**: [Sustainable velocity, maintainable codebase]

## Gamma Horizon (This Quarter/Year)
**Goal**: Strategic positioning and optionality

### Architectural Objectives
- [ ] [Platform capability]
- [ ] [Scalability milestone]
- [ ] [Technical differentiation]

### Strategic Optionality
- [ ] [Future capability enabled by current work]
- [ ] [Flexibility preserved]
- [ ] [Ecosystem alignment]

### Long-term Investment
- [ ] [Framework choice]
- [ ] [Infrastructure decision]
- [ ] [Build vs buy evaluation]

**Review Cadence**: Monthly strategic review
**Success Metric**: [Options preserved, competitive positioning]
```

## Planning Process

### Step 1: Define the Vision (Gamma)

**Start with strategic goal**:
- Where does this need to be in 6-12 months?
- What capabilities must exist?
- What optionality must be preserved?

**Avoid**: Detailed Gamma planning (requirements will change)
**Focus**: Direction, principles, optionality

### Step 2: Identify Beta Milestones

**Work backward from Gamma**:
- What needs to be solid in 4 weeks to enable Gamma?
- What quality standards must be met?
- What technical debt is blocking?

**Avoid**: Rigid Beta schedule (discovery happens)
**Focus**: Quality gates, capability checkpoints

### Step 3: Plan Alpha Execution

**Immediate next steps**:
- What ships this week?
- What validates our assumptions fastest?
- What unblocks the most future work?

**Avoid**: Big Alpha commitments (things change fast)
**Focus**: Learning, momentum, value delivery

### Step 4: Identify Cross-Horizon Dependencies

**Map connections**:
- Alpha work that enables Beta quality
- Beta capabilities required for Gamma strategy
- Gamma decisions that constrain Beta/Alpha

**Example**:
```markdown
Gamma Decision: Use PostgreSQL (strategic)
  ↓ Constrains
Beta Work: Build proper schema, migrations, indexes
  ↓ Enables
Alpha Execution: Can ship features trusting Beta foundation
```

### Step 5: Set Review Cadences

**Alpha Reviews**: Daily or every 5 minutes (phoenix interrupts)
**Beta Reviews**: Weekly assessment
**Gamma Reviews**: Monthly strategic check

**Review questions**:
- Is Alpha delivering value and learning?
- Is Beta maintaining quality and sustainability?
- Is Gamma still the right direction given new information?

## Integration Patterns

### Pattern 1: Alpha → Beta Promotion

**Scenario**: Alpha prototype works well, needs to become Beta quality

**Process**:
1. Extract Alpha learning (what worked, what didn't)
2. Design Beta version (proper tests, documentation, refactoring)
3. Schedule Beta work (budget 2-3x Alpha time for quality)
4. Execute with Beta standards
5. Retire Alpha version

### Pattern 2: Beta → Gamma Evolution

**Scenario**: Beta capability proves valuable, becomes strategic

**Process**:
1. Identify why Beta matters strategically
2. Plan Gamma hardening (scale, reliability, ecosystem)
3. Don't rush (Beta can serve well while Gamma gestates)
4. Invest in Gamma only when strategic value is clear
5. Maintain Beta during Gamma development

### Pattern 3: Gamma Constraint → Beta/Alpha Adaptation

**Scenario**: Gamma strategic decision changes Beta/Alpha work

**Process**:
1. Communicate Gamma decision clearly
2. Identify Beta work now obsolete or newly required
3. Adjust Alpha priorities to align
4. Accept sunk costs (Gamma matters more than Beta perfection)
5. Document learning for future Gamma decisions

## Practical Examples

### Example 1: Building New Application

**Gamma** (6 months):
- Production-ready SaaS application
- Multi-tenant architecture
- Enterprise-grade security and compliance

**Beta** (1 month):
- Working authentication and authorization
- Core feature set with tests
- Deploy pipeline and monitoring
- Documentation for handoff

**Alpha** (This week):
- Single-tenant prototype with hardcoded auth
- One core workflow end-to-end
- Manual deployment to staging
- Learning: user workflow validation

**Cross-Horizon Dependencies**:
- Gamma choice of multi-tenant → Beta must design tenant isolation
- Beta authentication approach → Alpha can hardcode knowing Beta plan
- Alpha learning about user workflow → Might change Beta feature priority

### Example 2: Technical Debt Payoff

**Gamma** (Strategic):
- Sustainable codebase with <10% bug rate
- Team velocity increasing quarter-over-quarter
- Architecture supports future products

**Beta** (This month):
- Refactor authentication module (highest bug source)
- Increase test coverage from 40% to 60%
- Extract shared utilities to library
- Document architecture decisions

**Alpha** (This week):
- Fix top 3 authentication bugs
- Add tests for bug fixes
- Extract one utility to shared lib
- Quick win: proves refactoring value

**Execution**:
- Alpha wins justify Beta investment
- Beta quality enables Gamma sustainability
- Gamma vision guides Beta priorities

## Checklist

- [ ] Gamma strategic direction defined (but not over-specified)
- [ ] Beta quality gates and capabilities identified
- [ ] Alpha immediate wins planned for this week
- [ ] Cross-horizon dependencies mapped
- [ ] Review cadences established (Alpha: frequent, Beta: weekly, Gamma: monthly)
- [ ] Success metrics defined for each horizon
- [ ] Phoenix interrupts planned for Alpha execution
- [ ] Team aligned on all three horizons

## Common Mistakes

**Gamma Planning in Alpha Time**: Architecting for scale you don't have
- **Fix**: Use `evaluating-alpha-beta-gamma` to right-size effort per horizon

**No Beta Investment**: Jumping from Alpha hacks to Gamma vision
- **Fix**: Schedule explicit Beta quality work, resist feature pressure

**Rigid Multi-Month Plans**: Detailed Alpha/Beta work planned months ahead
- **Fix**: Plan Gamma direction, Beta milestones, Alpha details only

**Ignoring Cross-Horizon Dependencies**: Treating timeframes as independent
- **Fix**: Explicitly map how Gamma constrains Beta which enables Alpha

## Related Skills

- `evaluating-alpha-beta-gamma` - Evaluate decisions at each horizon
- `analyzing-with-mcts` - Apply MCTS at each timeframe
- `midnight-building` - Execute Alpha work in focused sessions
- `phoenix-interrupting` - Monitor Alpha execution
- `interrupting-toxic-loops` - Orchestrate multiple Alpha branches

## Advanced Topics

See resources in this skill folder:
- `advanced-1-horizon-synchronization.md` - Keeping all three horizons aligned as context changes
- `advanced-2-debt-management.md` - Strategic technical debt across horizons
- `advanced-3-team-coordination.md` - Different team members working different horizons
