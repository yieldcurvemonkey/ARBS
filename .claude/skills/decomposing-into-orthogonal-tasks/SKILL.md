---
name: decomposing-into-orthogonal-tasks
description: Break complex work into 5-10 minute orthogonal tasks that can execute in parallel without conflicts. Use when facing large projects, need parallel execution, or preventing research spirals. Creates tasks that modify different files with no shared state.
---

# Decomposing Into Orthogonal Tasks

**Purpose**: Break complex work into small, independent tasks that can run in parallel.

## Core Philosophy

**From Axiom v4**:
> "Break everything into 5-10 minute orthogonal tasks, outsource as many as required, then recombine."

**Why This Works**:
- **5-10 minutes**: Too short to drift into research mode
- **Orthogonal**: No dependencies, no conflicts, true parallelism
- **Measurable**: File creation as success metric
- **Interruptible**: Can kill bad paths before completion

## When to Use

- Complex projects with multiple components
- Need for parallel execution (speed)
- Risk of research spirals or planning loops
- Multiple approaches to explore simultaneously
- Large monolithic tasks that feel overwhelming

## What Makes Tasks Orthogonal

### ✓ Orthogonal (Good)

**Different files, no dependencies**:
```
Task 1: Create models/user.js - Schema only
Task 2: Create auth/hash.js - Password functions only
Task 3: Create routes/auth.js - Route structure, mock responses
Task 4: Create middleware/verify.js - JWT verification only
Task 5: Create tests/auth.test.js - Unit tests, mock everything
```

Each creates different files. Can run simultaneously. No conflicts possible.

### ✗ Not Orthogonal (Bad)

**Same files, dependencies, shared state**:
```
Task 1: Create user.js with schema
Task 2: Add validation to user.js      ← Conflict! Same file
Task 3: Create auth using user.js      ← Dependency!
Task 4: Refactor user.js structure     ← Conflict! Same file
```

Tasks modify same files or depend on each other. Must run sequentially.

## Decomposition Patterns

### Pattern 1: By Component (Files)

**Example**: "Build REST API with authentication"

**Orthogonal Decomposition**:
```
1. models/user.js (5 min)
   - User schema only
   - No business logic
   - No dependencies

2. auth/password.js (5 min)
   - Hash function
   - Verify function
   - Pure functions, no state

3. routes/auth.js (10 min)
   - POST /register route
   - POST /login route
   - Mock responses (hardcode for now)

4. middleware/authenticate.js (10 min)
   - JWT verification middleware
   - Mock user for testing
   - No database calls yet

5. tests/auth.test.js (10 min)
   - Test hash/verify
   - Test routes with supertest
   - Mock everything

[RESERVE TASK - runs after others complete]
6. integration.js (10 min)
   - Wire together components
   - Replace mocks with real calls
   - Integration tests
```

**Why This Works**:
- Tasks 1-5 are truly independent
- All run in parallel
- Integration task waits for completion

### Pattern 2: By Layer (Vertical Slices)

**Example**: "Implement user profile feature"

**Orthogonal Decomposition**:
```
1. database-layer.js (5 min)
   - SQL migrations only
   - Table definitions
   - No queries

2. data-access.js (10 min)
   - CRUD functions
   - Mock database responses
   - Pure data layer

3. business-logic.js (10 min)
   - Validation rules
   - Business constraints
   - No database calls (use mocks)

4. api-routes.js (10 min)
   - REST endpoints
   - Mock business layer
   - OpenAPI spec

5. frontend-component.tsx (10 min)
   - React component
   - Mock API calls
   - UI only

[RESERVE TASK]
6. wire-layers.js (10 min)
   - Connect all layers
   - Replace mocks
   - E2E test
```

### Pattern 3: By Approach (Exploration)

**Example**: "Optimize database query performance"

**Orthogonal Approaches** (all run in parallel):
```
1. approach-indexing.js (10 min)
   - Add database indexes
   - Measure query time
   - Document tradeoffs

2. approach-caching.js (10 min)
   - Implement Redis cache
   - Measure hit rate
   - Document tradeoffs

3. approach-query-rewrite.js (10 min)
   - Rewrite SQL query
   - Use query planner
   - Document complexity

4. approach-denormalization.js (10 min)
   - Add computed columns
   - Update triggers
   - Document maintenance cost

[SYNTHESIS TASK - see skill: synthesizing-with-mcts]
5. choose-best-approach (5 min)
   - Compare performance metrics
   - Evaluate tradeoffs
   - Select winner or hybrid
```

## Decomposition Process

### Step 1: Identify Orthogonal Dimensions

**Questions to ask**:
- What files will be created?
- What components are independent?
- What can be mocked to remove dependencies?
- What layers exist (data, logic, API, UI)?
- What alternative approaches exist?

### Step 2: Create 5-10 Minute Tasks

**For each task, define**:
```markdown
## Task: [Name]

**Time**: 5-10 minutes
**Creates**: [specific files]
**Dependencies**: None (or list reserve tasks)
**Success**: Files created, no TODOs, has implementation
**Mocks**: [what to mock to remove dependencies]
```

**Example**:
```markdown
## Task: Create Password Hashing Module

**Time**: 5 minutes
**Creates**: auth/password.js
**Dependencies**: None
**Success**:
  - hash() function implemented
  - verify() function implemented
  - Uses bcrypt
  - No TODOs
**Mocks**: N/A (pure crypto functions)
```

### Step 3: Identify Reserve Tasks

**Reserve tasks** run after orthogonal tasks complete:
- Integration
- Wiring components
- Replacing mocks with real implementations
- End-to-end testing

**Mark clearly**:
```markdown
[RESERVE TASK - depends on tasks 1-5]
```

### Step 4: Define Success Criteria

**For each task**:
- Files that should exist
- No TODO comments
- Has actual implementation (not just stubs)
- Tests pass (if applicable)

## Common Decomposition Patterns

### API/REST

```
models/      - Data schemas only
routes/      - Route handlers, mock data
middleware/  - Auth, validation, error handling
tests/       - Unit tests, mock everything
config/      - Environment variables
[RESERVE] integration/ - Wire together
```

### Frontend Feature

```
components/  - React/Vue components, mock API
state/       - Redux/Pinia stores, mock actions
api/         - API client, mock responses
styles/      - CSS/styled-components
tests/       - Component tests, mock everything
[RESERVE] integration.tsx - Wire real API
```

### Data Pipeline

```
extract.js   - Get raw data, mock source
transform.js - Clean data, use sample
load.js      - Insert data, mock target
validate.js  - Check quality, use fixtures
schedule.js  - Cron config only
[RESERVE] pipeline.js - Connect all stages
```

### Algorithm Optimization

```
approach-1-brute-force.js    - Naive implementation
approach-2-divide-conquer.js - Recursive approach
approach-3-dynamic-prog.js   - Memoization
approach-4-greedy.js         - Heuristic
benchmark.js                 - Performance tests
[SYNTHESIS] choose-best.js   - Compare and select
```

## Anti-Patterns

### ❌ Sequential Disguised as Parallel

```
Task 1: Design database schema      ← Research/planning
Task 2: Implement based on schema   ← Depends on Task 1
Task 3: Test implementation          ← Depends on Task 2
```

**Fix**: Make truly orthogonal by mocking dependencies.

### ❌ Shared File Modification

```
Task 1: Add user routes to api.js
Task 2: Add auth routes to api.js    ← Conflict!
Task 3: Add admin routes to api.js   ← Conflict!
```

**Fix**: Separate files per task, merge in reserve task.

### ❌ Too Long (>10 minutes)

```
Task: Implement complete authentication system (30 min)
```

**Fix**: Break into orthogonal components as shown in Pattern 1.

### ❌ Too Short (<5 minutes)

```
Task: Add one line of code to config.js (1 min)
```

**Fix**: Combine with related tasks or isn't worth parallelization.

### ❌ Research/Planning Tasks

```
Task 1: Research best authentication approach
Task 2: Design API architecture
Task 3: Evaluate database options
```

**Fix**: Use expanding-then-compressing skill, or make concrete:
```
Task 1: Implement JWT auth approach
Task 2: Implement session auth approach
Task 3: Implement OAuth approach
[SYNTHESIS] Compare implementations
```

## Integration with Other Skills

**Use with**:
- `executing-parallel-tasks` - Run decomposed tasks simultaneously
- `synthesizing-with-mcts` - Merge results from parallel tasks
- `phoenix-interrupting` - Monitor each task for toxic completion
- `expanding-then-compressing` - Decompose during expansion phase
- `interrupting-toxic-loops` - Orchestrate parallel decomposed tasks

**Workflow**:
```
1. decomposing-into-orthogonal-tasks (this skill)
   ↓ Creates task list
2. executing-parallel-tasks
   ↓ Runs all tasks
3. synthesizing-with-mcts
   ↓ Merges best results
4. Final integrated solution
```

## Checklist

- [ ] Complex task identified
- [ ] Orthogonal dimensions found (files, components, approaches)
- [ ] Each subtask is 5-10 minutes
- [ ] Each subtask creates different files
- [ ] No dependencies between subtasks (mocked if needed)
- [ ] Reserve tasks identified for integration
- [ ] Success criteria defined (files, no TODOs, implementation)
- [ ] Ready for parallel execution

## Examples from Axiom

### Example 1: LRU Cache Implementation

**Orthogonal Decomposition**:
```
1. cache.js (5 min)
   - get() and set() only
   - Array-based storage
   - No eviction logic

2. lru.js (10 min)
   - Eviction algorithm
   - Least-recently-used tracking
   - Standalone, testable

3. ttl.js (10 min)
   - Time-based expiration
   - Timestamp tracking
   - Independent timer logic

4. tests/cache.test.js (10 min)
   - Test get/set
   - Mock time for TTL tests
   - Test eviction scenarios

[RESERVE]
5. integrated-cache.js (5 min)
   - Combine cache + lru + ttl
   - Wire eviction and expiration
   - Integration tests
```

### Example 2: Trading Strategy Implementation

**Orthogonal Decomposition**:
```
1. data/market-data.js (5 min)
   - Mock market data provider
   - Fixed test data
   - Interface only

2. signals/momentum.js (10 min)
   - Momentum indicator
   - Use fixed data
   - Pure calculation

3. signals/mean-reversion.js (10 min)
   - Mean reversion indicator
   - Use fixed data
   - Independent from momentum

4. execution/order-manager.js (10 min)
   - Mock order placement
   - Log orders only
   - No real trading

5. backtest/simulator.js (10 min)
   - Replay historical data
   - Calculate P&L
   - Use mock execution

[RESERVE]
6. live-strategy.js (10 min)
   - Wire real market data
   - Combine signals
   - Real order execution
   - Risk management
```

## Related Skills

- `executing-parallel-tasks` - Execute decomposed tasks
- `synthesizing-with-mcts` - Merge parallel results
- `phoenix-interrupting` - Monitor individual tasks
- `expanding-then-compressing` - Explore then decompose
- `planning-multi-timeframe` - Decompose across time horizons

## Advanced Topics

See resources in this skill folder:
- `advanced-1-dependency-analysis.md` - Identifying true dependencies
- `advanced-2-mocking-strategies.md` - How to mock to enable orthogonality
- `advanced-3-synthesis-patterns.md` - Merging orthogonal results
