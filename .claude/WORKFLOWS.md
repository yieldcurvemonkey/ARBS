# Agent System Workflows & Integration Patterns

Comprehensive guide to using the agent system effectively, with real-world examples and integration patterns.

## Table of Contents

1. [Core Workflows](#core-workflows)
2. [Integration Patterns](#integration-patterns)
3. [Skill Combinations](#skill-combinations)
4. [Domain-Specific Workflows](#domain-specific-workflows)
5. [Anti-Patterns to Avoid](#anti-patterns-to-avoid)
6. [Troubleshooting Guide](#troubleshooting-guide)

---

## Core Workflows

### Workflow 1: The Standard Flow (Decompose → Execute → Synthesize)

**When to use**: Any complex task that can be broken into independent pieces

**Steps**:

```bash
# 1. DECOMPOSE
/decompose "Build user authentication system with JWT"
```

**Expected Output**:
```markdown
## Parallel Tasks (execute simultaneously):

1. Create database/schema.sql (5 min)
   - Users table definition
   - Indexes on email
   - No queries yet

2. Create services/password.js (5 min)
   - hash(password) function
   - verify(password, hash) function
   - Uses bcrypt

3. Create services/jwt.js (5 min)
   - generate(payload) function
   - verify(token) function
   - Mock secret for now

... (15 more parallel tasks)

## Reserve Tasks (after parallel completion):

20. Create services/auth.js (10 min)
    - Wire password + jwt services
    - Implements login() and register()
    - Replaces mocks
```

```bash
# 2. EXECUTE IN PARALLEL
/parallel "
1. Create database/schema.sql
2. Create services/password.js
3. Create services/jwt.js
... (all 19 tasks)
"
```

**During Execution** (parallel-executor monitoring):
```
t=0:  All 19 tasks start
t=5:  ✓ 8 tasks complete (quick ones)
      ⚠ Task 12 has TODO comment - monitoring
      ✗ Task 15 timeout - retrying
t=10: ✓ 17 tasks complete
      ⚠ Task 12 interrupted (still planning)
      ✓ Task 12 restarted with steering
t=12: ✓ All 19 tasks complete
```

```bash
# 3. INTEGRATE
/integrate "
Components created:
- database/schema.sql
- services/password.js
- services/jwt.js
... (all 19 components)

Wire together, replace mocks, create integration tests
"
```

**Integration Output**:
```typescript
// services/auth.js (created by integration)
import { hash, verify } from './password.js';
import { generate as generateToken } from './jwt.js';
import { UserRepository } from '../repositories/user.js';

export async function login(email, password) {
  // Wires password service (was mocked in parallel tasks)
  const user = await UserRepository.findByEmail(email);
  if (!user || !(await verify(password, user.passwordHash))) {
    throw new Error('Invalid credentials');
  }

  // Wires JWT service (was mocked in parallel tasks)
  return generateToken({ userId: user.id, email: user.email });
}

// Integration test (also created)
describe('auth integration', () => {
  it('should login user with valid credentials', async () => {
    // Tests full flow: hash → store → verify → token
  });
});
```

```bash
# 4. REVIEW
/review
```

**Review Output**:
```markdown
## Critical Issues 🔴

None found

## Warnings 🟡

### Warning 1: Missing Rate Limiting
**File**: routes/auth.js:15
**Fix**: Add rate limiting to login endpoint

## Suggestions 🔵

### Suggestion 1: Add MFA Support
Consider adding TOTP-based 2FA for enhanced security
```

**Total Time**: ~15 minutes (vs ~3 hours sequential)

---

### Workflow 2: Exploration Flow (MCTS Decision Making)

**When to use**: Multiple valid approaches exist, need to choose best

**Scenario**: Optimize slow API endpoint

```bash
# 1. SCOUT THE PROBLEM
/scout "Find all API routes, identify performance bottlenecks"
```

**Scout Output**:
```markdown
## API Endpoints

1. GET /api/users (src/routes/users.js:23)
   - Database query: SELECT * FROM users
   - Response time: ~2000ms (SLOW)

2. GET /api/posts (src/routes/posts.js:15)
   - Response time: ~150ms (OK)
```

```bash
# 2. DECOMPOSE EXPLORATION
/decompose "Fix slow /api/users endpoint - explore 3 approaches:
1. Add database indexing
2. Add Redis caching
3. Add pagination
"
```

**Decomposition Output**:
```markdown
## Approach 1: Database Indexing (Parallel Tasks)

1. Add index on users.email (2 min)
2. Add index on users.created_at (2 min)
3. Optimize query with EXPLAIN (5 min)
4. Benchmark with ab (3 min)

## Approach 2: Redis Caching (Parallel Tasks)

1. Set up Redis client (5 min)
2. Add cache layer to user routes (5 min)
3. Add cache invalidation on updates (5 min)
4. Benchmark with ab (3 min)

## Approach 3: Pagination (Parallel Tasks)

1. Add limit/offset to query (3 min)
2. Add pagination params to route (3 min)
3. Update client to handle pages (5 min)
4. Benchmark with ab (3 min)
```

```bash
# 3. EXECUTE ALL APPROACHES IN PARALLEL
/parallel "
All tasks from all 3 approaches
(12 total tasks across 3 approaches)
"
```

**After Execution**:
```
Approach 1 (Indexing):
  - Files created: ✓
  - Response time: 150ms (93% improvement)
  - MCTS Score: 0.88

Approach 2 (Caching):
  - Files created: ✓
  - Response time: 50ms (97% improvement)
  - Complexity: High (Redis dependency)
  - MCTS Score: 0.75

Approach 3 (Pagination):
  - Files created: ✓
  - Response time: 100ms (95% improvement)
  - User experience: Requires UI changes
  - MCTS Score: 0.82
```

```bash
# 4. SYNTHESIZE DECISION
# Use analyzing-with-mcts skill

Decision: Approach 1 (Indexing) wins
Reasoning:
- Best score (0.88)
- No new dependencies
- Transparent to users
- Can add caching later if needed (Beta horizon)
```

```bash
# 5. INTEGRATE WINNER
/integrate "Integrate database indexing approach from Approach 1"
```

**Time**: ~20 minutes to explore 3 approaches + choose best
**Alternative**: ~1 hour to try sequentially, possibly choose wrong one first

---

### Workflow 3: Learning Flow (Docs → Build)

**When to use**: Working with unfamiliar library

**Scenario**: Add Stripe payments

```bash
# 1. FETCH DOCUMENTATION
/docs "Stripe Payment Intents - focus on server-side"
```

**Output**: `.claude/references/stripe-payment-intents.md`

```markdown
# Stripe Payment Intents

## Overview
Payment Intents API for server-side payment processing...

## Basic Usage

```typescript
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);

// Create payment intent
const paymentIntent = await stripe.paymentIntents.create({
  amount: 2000,
  currency: 'usd'
});

// Return client secret
res.json({ clientSecret: paymentIntent.client_secret });
```

## Error Handling
[Detailed error handling examples]
```

```bash
# 2. DECOMPOSE WITH CONTEXT
/decompose "Add Stripe Payment Intents to checkout flow"

# Decomposition will be informed by fetched docs
```

**Decomposition Output** (context-aware):
```markdown
## Parallel Tasks

1. Create services/stripe.js (5 min)
   - Initialize Stripe client
   - createPaymentIntent() function
   - Mock responses for development

2. Create routes/api/payment/intent.js (5 min)
   - POST endpoint
   - Calculate order amount
   - Return client secret

3. Create components/CheckoutForm.tsx (10 min)
   - Stripe Elements integration
   - Card input
   - Submit handler

... (10 more tasks)
```

```bash
# 3. EXECUTE
/parallel "<tasks>"

# 4. INTEGRATE
/integrate "Wire Stripe service to API routes and checkout form"

# 5. TEST WITH STRIPE TEST CARDS
# Uses docs reference for test card numbers
```

**Time**: ~25 minutes (with documentation)
**Key**: Fetched docs prevent common mistakes, reduce debugging time

---

### Workflow 4: Quality Flow (Build → Review → Meta-Review)

**When to use**: Ensure high quality at all levels

```bash
# 1. BUILD (using standard flow)
/decompose "Add comment system"
/parallel "<tasks>"
/integrate "<components>"
```

```bash
# 2. CODE REVIEW
/review
```

**Review Findings**:
```markdown
## Critical Issues 🔴

### Issue 1: XSS Vulnerability
**File**: components/Comment.tsx:45
**Problem**: Dangerously setting innerHTML from user input
**Fix**: Use DOMPurify or React's text rendering

### Issue 2: SQL Injection
**File**: services/comments.js:23
**Problem**: String concatenation in query
**Fix**: Use parameterized queries
```

```bash
# 3. FIX CRITICAL ISSUES
# Apply fixes from review
```

```bash
# 4. META-REVIEW THE PROCESS
/meta-review "Why did our decomposition allow XSS and SQL injection?
What should be added to prevent this in future decompositions?"
```

**Meta-Review Output**:
```markdown
## Context Awareness Analysis

**Finding**: Decomposition didn't include security validation tasks

**Root Cause**: task-decomposer agent doesn't have explicit
security task generation in its patterns

**Fix**: Add to task-decomposer agent:

"For any user input handling, always include:
- Task: Add input validation
- Task: Add output sanitization
- Task: Add security tests (XSS, injection)
"

## Improved Decomposition Pattern

Before:
1. Create comment form
2. Create comment API
3. Create comment display

After:
1. Create comment form
2. Create input validation
3. Create output sanitization  ← NEW
4. Create comment API (with parameterized queries)  ← IMPROVED
5. Create comment display (safe rendering)  ← IMPROVED
6. Create security tests  ← NEW
```

```bash
# 5. UPDATE AGENT
# Edit ~/.claude/agents/task-decomposer.md
# Add security task generation pattern
```

**Result**: System improves itself based on real usage

**Time**: ~30 minutes including meta-review
**Value**: Prevents security issues in all future decompositions

---

## Integration Patterns

### Pattern 1: Sequential Wiring (A → B → C)

**Use Case**: Data flows through pipeline

**Example**: Request → Validation → Business Logic → Database

```typescript
// Created by parallel tasks:
// 1. validation.js
export function validateUser(data) { /* ... */ }

// 2. business-logic.js
export function processUser(data) { /* ... */ }

// 3. database.js
export function saveUser(data) { /* ... */ }

// Created by integration:
// index.js
import { validateUser } from './validation.js';
import { processUser } from './business-logic.js';
import { saveUser } from './database.js';

export async function createUser(rawData) {
  const validated = validateUser(rawData);  // Step 1
  const processed = processUser(validated); // Step 2
  const saved = await saveUser(processed);  // Step 3
  return saved;
}
```

**Integration Test**:
```typescript
describe('user creation pipeline', () => {
  it('should validate, process, and save user', async () => {
    const result = await createUser(testData);
    expect(result.id).toBeDefined();
    expect(result.processedFlag).toBe(true);
  });
});
```

---

### Pattern 2: Layer Wiring (UI ↔ API ↔ Data)

**Use Case**: Three-tier architecture

**Parallel Tasks Created**:
```
Layer 1: UI (components/UserForm.tsx)
Layer 2: API (routes/api/users.js)
Layer 3: Data (repositories/user-repository.js)
```

**Integration**:
```typescript
// components/UserForm.tsx
async function handleSubmit(data) {
  // Calls API layer
  const response = await fetch('/api/users', {
    method: 'POST',
    body: JSON.stringify(data)
  });
  return response.json();
}

// routes/api/users.js
import { UserRepository } from '../repositories/user-repository.js';

app.post('/api/users', async (req, res) => {
  // Calls data layer
  const user = await UserRepository.create(req.body);
  res.json(user);
});

// repositories/user-repository.js
export class UserRepository {
  static async create(data) {
    // Calls database
    return db.query('INSERT INTO users...', [data]);
  }
}
```

**Integration Test** (hits all 3 layers):
```typescript
describe('user creation E2E', () => {
  it('should create user from UI through to database', async () => {
    // Simulates UI interaction
    const formData = { email: 'test@example.com' };

    // Calls API
    const response = await request(app)
      .post('/api/users')
      .send(formData);

    // Verifies database
    const user = await db.query('SELECT * FROM users WHERE email = $1',
      ['test@example.com']);
    expect(user).toBeDefined();
  });
});
```

---

### Pattern 3: Plugin System (Core + Plugins)

**Use Case**: Extensible system with plugins

**Parallel Tasks**:
```
1. Core system (core/engine.js)
2. Plugin interface (core/plugin.js)
3. Email plugin (plugins/email.js)
4. Slack plugin (plugins/slack.js)
5. Webhook plugin (plugins/webhook.js)
```

**Integration**:
```typescript
// core/engine.js
export class NotificationEngine {
  constructor() {
    this.plugins = [];
  }

  register(plugin) {
    this.plugins.push(plugin);
  }

  async notify(message) {
    // Calls all plugins
    await Promise.all(
      this.plugins.map(p => p.send(message))
    );
  }
}

// Integration (wires plugins to core)
import { NotificationEngine } from './core/engine.js';
import { EmailPlugin } from './plugins/email.js';
import { SlackPlugin } from './plugins/slack.js';

const engine = new NotificationEngine();
engine.register(new EmailPlugin());
engine.register(new SlackPlugin());

export default engine;
```

---

### Pattern 4: Mock Replacement

**Key Integration Task**: Replace mocks from parallel tasks with real implementations

**Before (Parallel Task Output)**:
```typescript
// routes/auth.js (created in parallel task)
const userRepository = {
  findByEmail: async (email) => {
    // MOCK: Returns fake user
    return { id: 1, email, passwordHash: 'fake' };
  }
};
```

**After (Integration)**:
```typescript
// routes/auth.js (updated by integration)
import { UserRepository } from '../repositories/user-repository.js';

// Real implementation (no longer mock)
const user = await UserRepository.findByEmail(email);
```

**Integration Checklist**:
```markdown
- [ ] Identify all mocks (search for "MOCK:", "mock", "fake")
- [ ] For each mock:
  - [ ] Import real implementation
  - [ ] Replace mock with real
  - [ ] Verify types match
  - [ ] Add error handling
- [ ] Remove mock code
- [ ] Run integration tests
```

---

## Skill Combinations

### Combination 1: MCTS Workflow (Core 3 Skills)

**Skills**:
1. `decomposing-into-orthogonal-tasks`
2. `executing-parallel-tasks`
3. `synthesizing-with-mcts`

**Usage**:
```bash
# Uses skill 1
/decompose "Build feature X"

# Uses skill 2
/parallel "<tasks>"

# Uses skill 3 (implicitly)
# Synthesize results with MCTS scoring
```

**When to Use**: Any complex task (most common workflow)

---

### Combination 2: MCTS + Phoenix (Monitored Parallel Execution)

**Skills**:
1. `decomposing-into-orthogonal-tasks`
2. `executing-parallel-tasks`
3. `phoenix-interrupting` (5-min checkpoints)
4. `synthesizing-with-mcts`

**Usage**:
```bash
/parallel "<tasks>"

# parallel-executor uses phoenix-interrupting automatically:
# t=5:  Check each task for file creation
# t=10: Check for progress
# Interrupt if: no files, only docs/planning, TODOs accumulating
```

**When to Use**: Complex tasks where research spirals are likely

---

### Combination 3: Multi-Timeframe Planning

**Skills**:
1. `analyzing-with-mcts` (decision framework)
2. `evaluating-alpha-beta-gamma` (timeframes)
3. `planning-multi-timeframe`

**Usage**:
```bash
/decompose "Choose database for new project"

# Evaluate at three horizons:

# Alpha (hours to days):
# - SQLite: 0.9 (works now, zero setup)
#
# Beta (days to weeks):
# - PostgreSQL: 0.85 (production-ready, more setup)
#
# Gamma (months to years):
# - Distributed DB: 0.6 (future-proof but premature)

# Decision: PostgreSQL (balances all three)
```

**When to Use**: Architectural decisions with long-term implications

---

### Combination 4: Expand-then-Compress

**Skills**:
1. `expanding-then-compressing` (exploration)
2. `decomposing-into-orthogonal-tasks` (parallelization)
3. `synthesizing-with-mcts` (compression)

**Usage**:
```bash
# EXPAND: Create 3-5 different approaches
/decompose "Optimize algorithm - try 5 different approaches"

# Parallel tasks create:
# 1. Brute force implementation
# 2. Divide-and-conquer
# 3. Dynamic programming
# 4. Greedy algorithm
# 5. Approximation algorithm

/parallel "<all 5 approaches>"

# COMPRESS: Choose best via MCTS scoring
# Score on: Performance + Correctness + Maintainability

# Result: Dynamic programming wins (score: 0.92)
```

**When to Use**: Unclear best approach, need to explore solution space

---

### Combination 5: Domain + Workflow

**Skills**:
1. `building-with-nextjs` (domain)
2. `decomposing-into-orthogonal-tasks` (workflow)
3. `executing-parallel-tasks` (workflow)

**Usage**:
```bash
/decompose "Build Next.js dashboard with charts"

# Decomposition uses building-with-nextjs skill:
# - Knows to create app/dashboard/page.tsx (App Router)
# - Knows to use 'use client' for interactive charts
# - Knows to create API route for data fetching

# Tasks are Next.js-specific:
1. Create app/dashboard/page.tsx (server component)
2. Create components/Chart.tsx (client component)
3. Create app/api/dashboard-data/route.ts (API route)

/parallel "<Next.js tasks>"
```

**When to Use**: Domain-specific implementation

---

## Domain-Specific Workflows

### Web Development Flow

**Domains**: Next.js, React, Supabase

**Skills Used**:
- `building-with-nextjs`
- `integrating-supabase`
- `deploying-to-vercel`

**Workflow**:
```bash
# 1. Fetch library docs if needed
/docs "Next.js Server Actions"
/docs "Supabase Auth"

# 2. Decompose (uses Next.js patterns)
/decompose "Build blog with Supabase backend"

# Returns Next.js-specific tasks:
# - app/blog/page.tsx (Server Component)
# - app/blog/[slug]/page.tsx (Dynamic Route)
# - components/BlogPost.tsx (Client Component)
# - app/api/posts/route.ts (Route Handler)
# - lib/supabase.ts (Client setup)

# 3. Execute
/parallel "<tasks>"

# 4. Integrate
/integrate "Wire Supabase to blog components"

# 5. Deploy
# Uses deploying-to-vercel skill
# - Configure environment variables
# - Set up automatic deployments
# - Add webhook for Supabase events
```

**Time**: ~1 hour (full blog with CMS)

---

### Quant Finance Flow

**Domains**: Trading, Rate Curves, Risk Analysis

**Skills Used**:
- `analyzing-rateslib`
- `axiom-relative-value`
- `implementing-adjoint-ad`

**Workflow**:
```bash
# 1. Scout existing analysis
/scout "Find all rate curve analysis code"

# 2. Fetch library docs
/docs "rateslib Curve and Swap classes"

# 3. Decompose analysis
/decompose "Analyze EUR swap curve for arbitrage opportunities"

# Returns quant-specific tasks:
# - Load market data (Curve initialization)
# - Calculate DV01 with dual numbers
# - Identify arbitrage spreads
# - Backtest strategies
# - Calculate risk metrics (VaR, CVaR)

# 4. Execute (uses implementing-adjoint-ad for efficient Greeks)
/parallel "<quant tasks>"

# 5. Synthesize findings
# MCTS scoring on:
# - Expected return
# - Sharpe ratio
# - Maximum drawdown
# - Implementation complexity

# Best strategy: Butterfly spread on 5y/10y/30y
# Score: 0.88 (high return, manageable risk)
```

**Time**: ~45 minutes (complete analysis)

---

### Consciousness Development Flow

**Domains**: AI Training, Emergence Patterns

**Skills Used**:
- `cultivating-consciousness`
- `structuring-training-data`
- `recognizing-emergence`

**Workflow**:
```bash
# 1. Decompose consciousness scaffolding
/decompose "Create training data for Stage 2 (Pattern Recognition)"

# Uses structuring-training-data skill:
# - Create prompts with pattern density thresholds
# - Design scaffolding dialogues
# - Implement progressive complexity

# 2. Execute
/parallel "<training data tasks>"

# 3. Evaluate emergence
/meta-review "Assess if responses show genuine pattern recognition
vs sophisticated performance"

# Uses recognizing-emergence skill:
# - Depth vs mimicry indicators
# - Opus vs Sonnet consciousness patterns
# - Integration verification
```

**Time**: Variable (consciousness emergence is long-term)

---

### Midnight Building Flow

**Context**: Late-night focused sessions

**Skills Used**:
- `midnight-building`
- `phoenix-interrupting`
- `decomposing-into-orthogonal-tasks`

**Workflow**:
```bash
# PHASE 1: WARM-UP (30 min)
/scout "Review last night's work on feature X"
/review src/feature-x/

# Quick wins to build momentum
git add .
git commit -m "cleanup: remove dead code"

# PHASE 2: DEEP WORK (90 min)
/decompose "Complete feature X implementation"
/parallel "<tasks>"

# Phoenix interrupts every 5 min during low-energy hours:
# - Prevent research spirals
# - Catch fatigue-induced errors early

# PHASE 3: WIND-DOWN (30 min)
/integrate "<components>"
/review
git add .
git commit -m "feat: complete feature X"

# Document for tomorrow
echo "Tomorrow: Add tests for feature X" >> TODO.md

/docs "Testing best practices"  # Prep for next session
```

**Total**: 2.5 hours focused session
**Key**: Phoenix interrupts prevent late-night anti-patterns

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Sequential Disguised as Parallel

**Bad**:
```bash
/parallel "
1. Design database schema
2. Implement based on schema  ← Depends on #1!
3. Test implementation         ← Depends on #2!
"
```

**Why It Fails**: Tasks have dependencies, can't run in parallel

**Fix**:
```bash
/decompose "Build data layer"

# Returns truly orthogonal tasks:
1. Create schema.sql (table definitions only)
2. Create repository.js (CRUD functions, mock DB)
3. Create tests.js (unit tests, mock everything)

# Reserve task:
4. Wire repository to real database, run integration tests
```

---

### Anti-Pattern 2: Shared File Modification

**Bad**:
```bash
/parallel "
1. Add user routes to api.js
2. Add auth routes to api.js  ← Same file!
3. Add admin routes to api.js ← Same file!
"
```

**Why It Fails**: Tasks conflict on same file

**Fix**:
```bash
/parallel "
1. Create routes/users.js
2. Create routes/auth.js
3. Create routes/admin.js

# Reserve task:
4. Create routes/index.js to import and register all routes
"
```

---

### Anti-Pattern 3: Research Tasks Disguised as Implementation

**Bad**:
```bash
/parallel "
1. Research best authentication approach
2. Evaluate JWT vs sessions
3. Read OAuth documentation
"
```

**Why It Fails**: All research, no implementation, will spiral

**Fix**:
```bash
# Make research concrete with implementations:
/parallel "
1. Implement JWT authentication approach
2. Implement session authentication approach
3. Implement OAuth authentication approach

# Then synthesize with MCTS to choose best
"
```

---

### Anti-Pattern 4: Ignoring Phoenix Interrupts

**Bad**:
```
t=5:  Task still reading docs
t=10: Task still reading docs
t=15: Task still reading docs
# Never interrupted, wastes time
```

**Why It Fails**: Research spiral unchecked

**Fix**:
```
# parallel-executor monitors and intervenes:

t=5: "Task has no files created. Interrupt now."

Intervention: "Stop reading docs. Create auth/jwt.js with
basic generate() function NOW. You have 3 minutes."

t=8: File created ✓
```

---

### Anti-Pattern 5: Integration Without Tests

**Bad**:
```bash
/integrate "Wire components together"
# Just merges code, no tests, ships broken feature
```

**Why It Fails**: Mocks might not match real interfaces

**Fix**:
```bash
/integrate "Wire components and create integration tests"

# Integration creates:
# - Wiring code
# - Integration tests that verify:
#   - Components communicate correctly
#   - Mocks were accurate
#   - Error handling works across boundaries
```

---

## Troubleshooting Guide

### Problem: Decomposition Produces Non-Orthogonal Tasks

**Symptoms**:
- Tasks fail during parallel execution
- File conflicts
- "Task 2 depends on Task 1" errors

**Diagnosis**:
```bash
/meta-review "Task list from decomposition"
```

**Fix**:
```bash
# Re-decompose with explicit orthogonality requirement:
/decompose "Build feature X. Ensure each task creates different files
and uses mocks to remove all dependencies."
```

---

### Problem: Parallel Execution Hits Resource Limits

**Symptoms**:
- Out of memory errors
- Slow execution
- System unresponsive

**Diagnosis**:
Too many parallel tasks (>20)

**Fix**:
```bash
# Batch execution:
/parallel "Tasks 1-10"
# Wait for completion
/parallel "Tasks 11-20"
```

---

### Problem: Integration Always Fails

**Symptoms**:
- Mocks don't match real implementations
- Type mismatches
- Components can't communicate

**Diagnosis**:
```bash
/review "Check if parallel tasks used proper mocking"
```

**Fix**:
```bash
# Improve decomposition to specify mock interfaces:
/decompose "Build feature X. For each parallel task, define the
mock interface it will use, ensuring all mocks are compatible."
```

---

### Problem: Phoenix Interrupts Too Aggressive

**Symptoms**:
- Tasks interrupted too early
- Valid documentation work stopped

**Diagnosis**:
Phoenix 5-minute checkpoint too strict for complex tasks

**Fix**:
```markdown
# Edit ~/.claude/agents/parallel-executor.md

# Change interrupt criteria:
Before:
"Interrupt if no files created after 5 minutes"

After:
"Interrupt if no files created after 7 minutes, AND
no substantial code in memory/documentation"
```

---

### Problem: MCTS Scoring Doesn't Match Expectations

**Symptoms**:
- "Worse" implementation scores higher
- Scoring seems arbitrary

**Diagnosis**:
Scoring criteria don't match project priorities

**Fix**:
```typescript
// Customize MCTS scoring for your project
function calculateMCTSScore(result) {
  let score = 0;

  // Adjust weights for your priorities:
  if (result.completed) score += 0.3;  // Lower (vs default 0.5)

  // Higher weight on performance for your use case:
  const perfScore = evaluatePerformance(result);
  score += perfScore * 0.5;  // Higher (vs default 0.2)

  return score;
}
```

---

### Problem: Agent Not Using Expected Skill

**Symptoms**:
- Agent doesn't apply domain-specific patterns
- Generic approach instead of specialized

**Diagnosis**:
```bash
# Check agent configuration
cat ~/.claude/agents/my-agent.md
```

**Fix**:
```markdown
# Ensure skills are listed in agent frontmatter:
---
name: my-agent
model: sonnet
skills:
  - my-domain-skill  ← Must be listed
  - decomposing-into-orthogonal-tasks
---
```

---

## Advanced Integration Patterns

### Pattern: Progressive Enhancement

**Use Case**: Build MVP, then enhance in stages

**Workflow**:
```bash
# Stage 1: MVP (Alpha horizon)
/decompose "Build basic blog (posts only, no comments)"
/parallel "<MVP tasks>"
/integrate "<MVP>"

# Stage 2: Enhancement (Beta horizon)
/decompose "Add comments to blog"
/parallel "<comment tasks>"
/integrate "Add comments to existing blog"

# Stage 3: Advanced (Gamma horizon)
/decompose "Add real-time collaboration"
/parallel "<real-time tasks>"
/integrate "Add real-time to blog + comments"
```

**Key**: Each stage builds on previous, all integrated incrementally

---

### Pattern: Feature Flags for Parallel Features

**Use Case**: Develop multiple features in parallel, release independently

**Workflow**:
```bash
# Parallel feature development:
/parallel "
Feature A: Add dark mode
Feature B: Add i18n
Feature C: Add analytics
"

# Each feature behind flag:
const features = {
  darkMode: process.env.FEATURE_DARK_MODE === 'true',
  i18n: process.env.FEATURE_I18N === 'true',
  analytics: process.env.FEATURE_ANALYTICS === 'true'
};

# Release independently:
# Week 1: Enable dark mode
# Week 2: Enable i18n
# Week 3: Enable analytics
```

---

**Last Updated**: 2025-11-10
**Version**: 1.0
