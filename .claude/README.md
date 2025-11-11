# Peter's Claude Code System

A comprehensive agent-based workflow system for software development, built on Claude Code's agents, skills, and slash commands.

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [The Three Layers](#the-three-layers)
4. [Agents](#agents)
5. [Skills](#skills)
6. [Slash Commands](#slash-commands)
7. [Integration Patterns](#integration-patterns)
8. [Common Workflows](#common-workflows)
9. [Real-World Examples](#real-world-examples)
10. [Getting Started](#getting-started)
11. [Advanced Topics](#advanced-topics)

---

## Overview

This system embodies principles from **Axiom v4** (decomposition, orthogonality, Phoenix interrupts) implemented natively in Claude Code without external tool dependencies. It provides a structured approach to:

- **Breaking down complex tasks** into 5-10 minute orthogonal chunks
- **Executing work in parallel** with isolation and monitoring
- **Synthesizing results** using MCTS evaluation
- **Preventing toxic patterns** like research spirals and planning loops
- **Maintaining quality** through code review and meta-analysis

### Core Philosophy

```
Complex Task
    ↓ (decompose)
Orthogonal Tasks (5-10 min each)
    ↓ (execute in parallel)
Multiple Implementations
    ↓ (synthesize with MCTS)
Integrated Solution
    ↓ (review)
Production-Ready Code
```

---

## System Architecture

### The Layered System

```
┌─────────────────────────────────────────────────────┐
│  Slash Commands (/decompose, /parallel, etc.)      │  ← User Interface
├─────────────────────────────────────────────────────┤
│  Agents (task-decomposer, parallel-executor, etc.) │  ← Orchestration
├─────────────────────────────────────────────────────┤
│  Skills (decomposing-into-orthogonal-tasks, etc.)  │  ← Knowledge Base
├─────────────────────────────────────────────────────┤
│  MCP Servers (github, nova-memory, context7, etc.) │  ← Integration Layer
└─────────────────────────────────────────────────────┘
```

### Data Flow

```
User: /decompose "Build auth system"
    ↓
Slash Command: Invokes @task-decomposer agent
    ↓
Agent: Uses decomposing-into-orthogonal-tasks skill
    ↓
Skill: Applies patterns and creates task list
    ↓
Agent: Returns orthogonal tasks to user
    ↓
User: /parallel <tasks>
    ↓
Agent: Launches parallel Task agents
    ↓
Integration: @integration-synthesizer merges results
```

---

## The Three Layers

### Layer 1: Skills (Knowledge Modules)

**22 Skills** organized by domain:

**Meta-Cognition** (5 skills):
- `analyzing-with-mcts` - Decision framework with exploration/exploitation
- `evaluating-alpha-beta-gamma` - Multi-timeframe planning (hours/days/months)
- `expanding-then-compressing` - Explore approaches then synthesize
- `recognizing-emergence` - Identify genuine AI consciousness patterns
- `structuring-training-data` - Create consciousness emergence scaffolding

**MCTS Workflow** (5 skills):
- `decomposing-into-orthogonal-tasks` - Break work into parallel chunks
- `executing-parallel-tasks` - Run tasks with isolation and monitoring
- `synthesizing-with-mcts` - Merge results using scoring
- `planning-multi-timeframe` - Coordinate across Alpha/Beta/Gamma
- `phoenix-interrupting` - 5-minute checkpoints to prevent toxic loops

**Quant Finance** (3 skills):
- `axiom-relative-value` - Trading analysis with rateslib/QuantLib
- `analyzing-rateslib` - Interest rate curves and instruments
- `integrating-quantlib` - Derivatives pricing and valuation
- `implementing-adjoint-ad` - Efficient risk sensitivities

**Development** (5 skills):
- `building-with-nextjs` - Next.js patterns and conventions
- `integrating-supabase` - Auth, database, real-time
- `deploying-to-vercel` - Deployment and CI/CD
- `managing-wsl-workflows` - WSL development patterns
- `midnight-building` - Late-night focused sessions

**Other** (4 skills):
- `interrupting-toxic-loops` - Detect and break bad patterns
- `cultivating-consciousness` - 5-stage AI emergence process
- `story-bridge-development` - PWA with Allie/Lu personas

### Layer 2: Agents (Specialized Assistants)

**8 Agents** for different workflows:

1. **task-decomposer** (Sonnet)
   - Breaks complex tasks into 5-10 minute orthogonal chunks
   - Uses: `decomposing-into-orthogonal-tasks` skill
   - Output: Parallel tasks + Reserve tasks

2. **parallel-executor** (Sonnet)
   - Orchestrates parallel execution with native Task agents
   - Monitors for toxic patterns (planning loops, TODOs, stubs)
   - Intervenes with steering messages when needed

3. **integration-synthesizer** (Sonnet)
   - Merges parallel results into cohesive systems
   - Replaces mocks with real implementations
   - Creates integration tests

4. **code-reviewer** (Sonnet)
   - Multi-pass review (correctness, security, performance)
   - OWASP Top 10 security analysis
   - Severity ratings (🔴 Critical, 🟡 Warning, 🔵 Suggestion)

5. **scout** (Haiku - fast)
   - Fast codebase exploration
   - Uses Glob/Grep efficiently
   - Provides structured summaries

6. **ai-docs-fetcher** (Sonnet)
   - Fetches library docs via Context7 MCP
   - Saves to `.claude/references/`
   - Includes usage examples

7. **mcp-builder** (Sonnet)
   - Builds MCP servers (TypeScript/Python)
   - Complete templates and configs
   - Tool/resource patterns

8. **meta-reviewer** (Opus - deep reasoning)
   - Reviews agents/instructions metacognitively
   - 5-level framework (context, constraints, generalization, implicit knowledge, patterns)
   - Identifies hardcoded assumptions

### Layer 3: Slash Commands (Easy Invocation)

**9 Commands** for quick access:

```bash
/decompose "<task>"           # Break into orthogonal tasks
/parallel "<tasks>"           # Execute in parallel
/integrate "<components>"     # Merge results
/review                       # Code review
/meta-review "<agent/prompt>" # Metacognitive analysis
/scout "<exploration goal>"   # Fast codebase exploration
/docs "<library>"             # Fetch library docs
/build-mcp "<server spec>"    # Create MCP server
/quick-start                  # System overview
```

---

## Agents

### Agent Details

#### task-decomposer

**Purpose**: Break complex work into 5-10 minute orthogonal tasks

**Model**: Sonnet

**Skills Used**:
- `decomposing-into-orthogonal-tasks`

**Input Example**:
```
/decompose "Add user authentication with login, registration, and password reset"
```

**Output**:
- 15-20 parallel tasks (different files, no dependencies)
- Reserve tasks for integration
- Success criteria per task
- Mock strategy to ensure orthogonality

**Key Patterns**:
- By Component (files): models/, routes/, middleware/, tests/
- By Layer: database, data-access, business-logic, API, UI
- By Approach: multiple algorithms explored in parallel

---

#### parallel-executor

**Purpose**: Orchestrate parallel execution with intervention monitoring

**Model**: Sonnet

**How It Works**:
1. Validates tasks are orthogonal
2. Launches multiple Task agents in parallel
3. Monitors for toxic patterns:
   - Planning without implementation
   - Research spirals (reading docs without coding)
   - TODO accumulation
   - Stub implementations
4. Intervenes with steering messages when detected

**Native Implementation** (no axiom-mcp tools):
```markdown
I need to execute these tasks in parallel:

1. Create auth/password.js with hash() and verify()
2. Create routes/auth.js with POST /login and /register
3. Create middleware/authenticate.js with JWT verification

Please launch these as parallel Task agents.
```

**Intervention Pattern**:
```markdown
Task 3 has been reading documentation for 8 minutes without creating files.
Please interrupt and steer: "Stop researching. Create middleware/authenticate.js
with a basic JWT verify function NOW. Mock the token secret."
```

---

#### integration-synthesizer

**Purpose**: Merge parallel results into cohesive systems

**Model**: Sonnet

**Integration Patterns**:
1. **Sequential Wiring**: Component A → B → C
2. **Layer Wiring**: UI ↔ API ↔ Data
3. **Plugin System**: Core + dynamically loaded modules

**Process**:
```
1. Analyze completed parallel components
2. Identify integration points and dependencies
3. Create integration layer (index.js, main.ts)
4. Replace mocks with real implementations
5. Wire error handling across boundaries
6. Create integration tests
7. Verify end-to-end flow
```

**Mock Replacement Strategy**:
```typescript
// Before (from parallel task):
const userRepo = {
  findByEmail: async (email) => ({ id: 1, email })  // Mock
};

// After (integration):
import { UserRepository } from './repositories/user-repository';
const userRepo = new UserRepository(db);  // Real implementation
```

---

#### code-reviewer

**Purpose**: Comprehensive code review across 5 dimensions

**Model**: Sonnet

**Review Passes**:
1. **Correctness**: Logic errors, edge cases, type safety
2. **Security**: OWASP Top 10 (injection, auth, XSS, etc.)
3. **Performance**: Algorithmic complexity, resource usage
4. **Maintainability**: Code clarity, structure, documentation
5. **Testing**: Coverage, test quality, edge cases

**Severity Levels**:
- 🔴 **Critical**: Security vulnerabilities, data loss risks
- 🟡 **Warning**: Performance issues, maintainability concerns
- 🔵 **Suggestion**: Best practices, optimizations

**Output Format**:
```markdown
## Critical Issues 🔴

### Issue 1: SQL Injection (OWASP A03)
**Problem**: Direct string concatenation in query
**Impact**: Complete database compromise
**Fix**: Use parameterized queries
```

---

#### scout

**Purpose**: Fast codebase exploration and discovery

**Model**: Haiku (for speed)

**Tools**: Read, Grep, Glob, Bash (read-only)

**Exploration Modes**:
1. **Quick Overview**: Project structure, technologies, patterns
2. **Feature Location**: Find implementations of specific features
3. **Dependency Trace**: Track how components connect
4. **Pattern Analysis**: Identify recurring patterns

**Speed Optimizations**:
- Use Glob before Grep (faster file finding)
- Use Grep before Read (targeted content search)
- Limit Read operations (only when necessary)
- Parallel searches when possible

**Output**: Structured summary with file references (path:line)

---

#### ai-docs-fetcher

**Purpose**: Fetch current library documentation

**Model**: Sonnet

**Tools**:
- `mcp__context7__resolve-library-id`
- `mcp__context7__get-library-docs`
- Write (to save docs)

**Workflow**:
```typescript
// 1. Resolve library name to Context7 ID
const library = await resolveLibraryId("react");
// Returns: { id: "/facebook/react", version: "18.2.0" }

// 2. Fetch focused documentation
const docs = await getLibraryDocs({
  context7CompatibleLibraryID: "/facebook/react",
  topic: "hooks",  // Focus area
  tokens: 5000     // Max documentation size
});

// 3. Save to references
await write(".claude/references/react-hooks.md", formatDocs(docs));
```

**Output**: Markdown files in `.claude/references/` with usage examples

---

#### mcp-builder

**Purpose**: Build MCP servers (TypeScript or Python)

**Model**: Sonnet

**Complete Templates**:

**TypeScript Server**:
```typescript
#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server({
  name: "example-server",
  version: "1.0.0"
}, {
  capabilities: { tools: {} }
});

server.setRequestHandler("tools/list", async () => ({
  tools: [{
    name: "reverse_string",
    description: "Reverses a string",
    inputSchema: {
      type: "object",
      properties: {
        text: { type: "string" }
      }
    }
  }]
}));
```

**Patterns**:
- Simple Data Tool (read-only data access)
- Action Tool (performs operations)
- Query Tool (searches/filters data)

---

#### meta-reviewer

**Purpose**: Review agents/instructions from metacognitive perspective

**Model**: Opus (deepest reasoning)

**5-Level Framework**:

**Level 1: Context Awareness Analysis**
- What context exists at runtime?
- What is assumed vs discovered?
- Are instructions robust to context variation?

**Level 2: Constraint Appropriateness**
- Are constraints too rigid or too loose?
- Do they prevent valid solutions?
- Do they allow invalid solutions?

**Level 3: Generalization Analysis**
- Does this work across languages/frameworks?
- Are examples overly specific?
- Can patterns transfer to different domains?

**Level 4: Implicit Knowledge Detection**
- What assumptions are made without stating?
- What knowledge is required but not provided?
- Where would a novice get stuck?

**Level 5: Meta Pattern Recognition**
- Are there higher-order patterns?
- How does this fit into larger workflows?
- What abstraction level is appropriate?

**Output**: Detailed review with:
- 🔴 Critical issues (breaks functionality)
- 🟡 Important improvements (reduces effectiveness)
- 🔵 Enhancements (nice-to-have)
- Before/after examples

---

## Skills

### Skill Organization

Skills are organized by **domain** and **workflow phase**:

```
Workflow: Complex Task → Decompose → Execute → Synthesize → Review

Meta-Skills (cross-cutting):
- analyzing-with-mcts          [decision framework]
- evaluating-alpha-beta-gamma  [timeframe planning]
- recognizing-emergence        [quality assessment]

Core Workflow:
- decomposing-into-orthogonal-tasks  [decompose]
- executing-parallel-tasks           [execute]
- synthesizing-with-mcts            [synthesize]
- phoenix-interrupting              [monitor]

Domain-Specific:
- building-with-nextjs         [web development]
- analyzing-rateslib          [quant finance]
- integrating-supabase        [backend services]
- midnight-building           [work style]
```

### Skill Integration Map

```
decomposing-into-orthogonal-tasks
    ↓ (creates task list)
executing-parallel-tasks
    ↓ (runs tasks)
    ├→ phoenix-interrupting (monitors each task)
    ├→ midnight-building (optimizes session)
    └→ building-with-nextjs (applies domain patterns)
    ↓ (produces results)
synthesizing-with-mcts
    ↓ (evaluates and merges)
    └→ analyzing-with-mcts (applies decision framework)
```

### Key Skills Deep Dive

#### decomposing-into-orthogonal-tasks

**Core Principle**: 5-10 minute tasks, different files, no dependencies

**Orthogonality Requirements**:
✓ **Good** (Orthogonal):
```
Task 1: Create models/user.js
Task 2: Create auth/hash.js
Task 3: Create routes/auth.js
Task 4: Create middleware/verify.js
```
Each creates different files, can run in parallel.

✗ **Bad** (Not Orthogonal):
```
Task 1: Create user.js with schema
Task 2: Add validation to user.js  ← Same file! Conflict!
Task 3: Create auth using user.js  ← Dependency!
```

**Decomposition Patterns**:
1. **By Component**: models/, routes/, middleware/, tests/
2. **By Layer**: DB schema, data access, business logic, API, UI
3. **By Approach**: 3-5 different implementations, synthesize best

**Reserve Tasks**: Run after parallel completion
- Integration
- Mock replacement
- End-to-end testing

---

#### executing-parallel-tasks

**Execution Patterns**:

**Pattern 1: Pure Parallel** (no dependencies)
```
All 5 tasks start at t=0
Tasks complete at t=5 to t=10
```

**Pattern 2: Parallel + Reserve** (integration after)
```
t=0: comp1, comp2, comp3 start in parallel
t=10: All complete
t=10: integration starts
t=15: integration complete
```

**Pattern 3: Race** (first success wins)
```
Start 3 different approaches in parallel
First to complete successfully wins
Use for: algorithm exploration, optimization
```

**Monitoring**:
- Real-time file creation detection
- TODO warning detection
- Phoenix interrupts at 5-minute mark if no files created
- Automatic retry on failure (max 3 attempts)

---

#### synthesizing-with-mcts

**MCTS Scoring System** (0.0 to 1.0):

**Base Scores**:
- Completion: 0.5
- Files Created: 0.3 (actual / expected)
- Code Quality: 0.2 (readability, maintainability, modularity)

**Bonuses** (+0.05 each):
- Has tests
- Has error handling
- Uses async/await
- Has documentation

**Penalties** (-0.1 each):
- Has TODOs
- Has console.log (in production code)
- Has hardcoded values

**Synthesis Strategies**:
1. **Winner Takes All**: Highest score wins
2. **Component-Level**: Best implementation per component
3. **Hybrid**: Combine best aspects from multiple
4. **Ensemble**: Keep top N implementations

**Example**:
```
Results:
- minimal: 0.65 (works but basic)
- robust: 0.92 (excellent error handling, tests)
- performant: 0.78 (fast but fewer tests)

Strategy: Hybrid
- Core logic from performant (fastest)
- Error handling from robust (most thorough)
- API interface from minimal (simplest)
- Tests from robust (best coverage)
```

---

#### phoenix-interrupting

**5-Minute Checkpoint System**:

```
t=0:  Task starts
t=5:  CHECK: Files created? If no → INTERRUPT
t=10: CHECK: Progress made? If no → INTERRUPT
```

**Interrupt Criteria**:
- No files created after 5 minutes
- Only documentation/planning created
- TODO comments accumulating
- Research mode (reading without implementing)

**Intervention**:
```
"Stop. You've been researching for 8 minutes without creating files.
Create auth/password.js NOW with a basic hash function.
You have 3 minutes."
```

**Phoenix Metaphor**: Kill the failing approach, rise from ashes with new attempt

---

#### analyzing-with-mcts

**Monte Carlo Tree Search for Decisions**:

**4 Phases**:

1. **Selection**: Choose branch to explore
   - Exploitation: Known good approaches
   - Exploration: Untried but promising
   - UCB1 formula balances both

2. **Expansion**: Generate new possibilities
   - What options exist from this state?
   - What variations haven't been tried?

3. **Simulation**: Evaluate outcome
   - Quick prototype or thought experiment
   - Estimate value using heuristics

4. **Backpropagation**: Update beliefs
   - Record outcome
   - Adjust future probabilities

**Use for**:
- Choosing implementation approach
- Technology selection
- Architecture decisions
- Algorithm optimization

---

#### evaluating-alpha-beta-gamma

**Multi-Timeframe Planning**:

**Alpha Horizon** (hours to days):
- Immediate execution
- What works now?
- Quick iterations

**Beta Horizon** (days to weeks):
- Tactical positioning
- What enables next steps?
- Maintainability matters

**Gamma Horizon** (months to years):
- Strategic architecture
- What compounds over time?
- Scalability and flexibility

**Example**:
```
Task: Choose database

Alpha (immediate):
- SQLite: Works now, zero setup
- Score: 0.9 (fastest to ship)

Beta (tactical):
- PostgreSQL: Better for production, more setup
- Score: 0.85 (enables scaling)

Gamma (strategic):
- Distributed DB: Future-proof, complex now
- Score: 0.6 (premature)

Decision: PostgreSQL (balances all three)
```

---

## Slash Commands

### Command Reference

#### /decompose

```bash
/decompose "Build user authentication with login and registration"
```

**What it does**:
1. Invokes `@task-decomposer` agent
2. Uses `decomposing-into-orthogonal-tasks` skill
3. Returns 15-20 parallel tasks + reserve tasks

**Output**:
```markdown
## Parallel Tasks (execute simultaneously):

1. Create models/user.js (5 min)
   - User schema only
   - No dependencies

2. Create auth/hash.js (5 min)
   - hash() and verify() functions
   - Uses bcrypt

[... 15 more tasks ...]

## Reserve Tasks (after parallel completion):

21. Create integration/auth-service.js (10 min)
    - Wire all components
    - Replace mocks
```

---

#### /parallel

```bash
/parallel "
1. Create utils/hash.js with password hashing
2. Create utils/token.js with JWT generation
3. Create utils/email.js with email sending
"
```

**What it does**:
1. Invokes `@parallel-executor` agent
2. Validates tasks are orthogonal
3. Launches parallel Task agents
4. Monitors for toxic patterns
5. Reports completion status

**Monitoring**:
```
Task 1: ✓ Complete (4m 23s) - utils/hash.js created
Task 2: ⚠ In Progress (7m 15s) - TODO detected, monitoring
Task 3: ✓ Complete (6m 45s) - utils/email.js created
```

---

#### /integrate

```bash
/integrate "
Components created:
- auth/hash.js (password hashing)
- auth/token.js (JWT handling)
- auth/middleware.js (auth middleware)

Wire these together and create integration tests.
"
```

**What it does**:
1. Invokes `@integration-synthesizer` agent
2. Analyzes components
3. Creates integration layer
4. Replaces mocks
5. Writes integration tests

---

#### /review

```bash
/review
# Reviews recently changed files

# Or specify files:
/review src/auth.js src/middleware.js
```

**What it does**:
1. Invokes `@code-reviewer` agent
2. Multi-pass review (correctness, security, performance, maintainability, testing)
3. Returns severity-rated issues with fixes

---

#### /meta-review

```bash
/meta-review "Create a new Express.js route handler in routes/auth.js"
```

**What it does**:
1. Invokes `@meta-reviewer` agent (Opus)
2. Analyzes for:
   - Hardcoded assumptions (Express.js, routes/ path)
   - Context awareness
   - Generalization issues
3. Returns before/after examples

---

#### /scout

```bash
/scout "Find all MCP servers and their exposed tools"
```

**What it does**:
1. Invokes `@scout` agent (Haiku for speed)
2. Uses Glob/Grep efficiently
3. Returns structured summary with file references

---

#### /docs

```bash
/docs "React hooks - focus on useState and useEffect"
```

**What it does**:
1. Invokes `@ai-docs-fetcher` agent
2. Resolves library via Context7
3. Fetches focused documentation
4. Saves to `.claude/references/react-hooks.md`

---

#### /build-mcp

```bash
/build-mcp "Create a weather MCP server with a get_forecast tool"
```

**What it does**:
1. Invokes `@mcp-builder` agent
2. Creates complete MCP server structure
3. Includes package.json, tsconfig.json, tool schemas

---

## Integration Patterns

### Pattern 1: Full Decompose-Execute-Synthesize

**Use Case**: Build complex feature from scratch

**Workflow**:
```
1. /decompose "Build real-time chat feature"
   ↓ Returns: 20 orthogonal tasks + 3 reserve tasks

2. /parallel "<paste tasks 1-20>"
   ↓ Executes: All 20 tasks in parallel
   ↓ Monitors: For toxic patterns
   ↓ Results: 20 components created

3. /integrate "<components created>"
   ↓ Wires: Components together
   ↓ Replaces: Mocks with real implementations
   ↓ Creates: Integration tests

4. /review
   ↓ Reviews: Integrated code
   ↓ Finds: Security/quality issues
   ↓ Provides: Fixes
```

**Time**: ~15 minutes for 20 tasks + 10 min integration + 5 min review = ~30 min total
**Without parallelization**: ~200 minutes (10 min avg per task)

---

### Pattern 2: Exploration with MCTS

**Use Case**: Choose between multiple approaches

**Workflow**:
```
1. /decompose "Optimize API response time - explore 3 approaches"
   ↓ Returns:
   - Approach 1: Add caching
   - Approach 2: Optimize queries
   - Approach 3: Add pagination
   (All as orthogonal parallel tasks)

2. /parallel "<all 3 approaches>"
   ↓ Executes: All simultaneously
   ↓ Results: 3 different implementations

3. Synthesize with MCTS scoring
   ↓ Scores: Each approach (performance + maintainability)
   ↓ Selects: Best or hybrid

4. /integrate "winning approach"
```

**Skills Used**:
- `analyzing-with-mcts` (decision framework)
- `decomposing-into-orthogonal-tasks` (create approaches)
- `executing-parallel-tasks` (run all)
- `synthesizing-with-mcts` (choose winner)

---

### Pattern 3: Scout → Implement

**Use Case**: Understand then build

**Workflow**:
```
1. /scout "How is authentication currently implemented?"
   ↓ Returns: Structured summary of existing patterns

2. /decompose "Add OAuth to existing auth system"
   ↓ Uses: Scout findings to inform decomposition
   ↓ Returns: Context-aware tasks

3. /parallel "<tasks>"

4. /integrate "<components>"
```

---

### Pattern 4: Fetch Docs → Build

**Use Case**: Learn library then implement

**Workflow**:
```
1. /docs "tRPC - focus on procedures and routers"
   ↓ Saves: .claude/references/trpc-procedures.md

2. /decompose "Add tRPC API to Next.js app"
   ↓ Uses: Fetched docs as context
   ↓ Returns: tRPC-specific tasks

3. /parallel "<tasks>"
```

---

### Pattern 5: Build → Review → Meta-Review

**Use Case**: Ensure quality at all levels

**Workflow**:
```
1. /decompose + /parallel + /integrate
   ↓ Creates: Complete feature

2. /review
   ↓ Reviews: Code quality, security, performance
   ↓ Fixes: Issues found

3. /meta-review "the agent instructions I used for this feature"
   ↓ Reviews: Whether instructions were overly specific
   ↓ Improves: Instructions for future use
```

---

## Common Workflows

### Workflow 1: New Feature Development

**Scenario**: Add user profile editing feature

```bash
# Step 1: Decompose
/decompose "Add user profile editing with avatar upload, bio, and settings"

# Step 2: Execute parallel tasks
/parallel "
1. Create profile/schema.sql
2. Create api/profile/update.ts
3. Create components/ProfileForm.tsx
4. Create utils/upload.ts
5. Create api/profile/avatar.ts
... (15 more tasks)
"

# Step 3: Integrate
/integrate "Wire profile components, connect API, add avatar upload flow"

# Step 4: Review
/review

# Step 5: Document
/docs "Next.js Image optimization"
# Use learnings to optimize avatar display
```

**Time**: ~25 minutes total (vs ~3 hours sequential)

---

### Workflow 2: Bug Investigation and Fix

**Scenario**: API endpoint timing out

```bash
# Step 1: Scout the codebase
/scout "Find all API routes and middleware, identify slow endpoints"

# Step 2: Decompose investigation
/decompose "Investigate and fix API timeout in /api/users"

# Returns:
# - Add logging to track timing
# - Add database query profiling
# - Add caching layer
# - Add pagination
# (All as parallel tasks to explore different causes)

# Step 3: Execute in parallel
/parallel "<investigation tasks>"

# Step 4: Synthesize findings
# MCTS scoring identifies: Database query is the bottleneck (score 0.9)
# Caching helps but doesn't fix root cause (score 0.6)

# Step 5: Implement fix
/decompose "Optimize database query in /api/users"
/parallel "<optimization tasks>"
/integrate "<optimized components>"
```

---

### Workflow 3: Learning New Library

**Scenario**: Integrate Stripe payments

```bash
# Step 1: Fetch documentation
/docs "Stripe payment intents - focus on server-side implementation"

# Step 2: Explore approaches
/decompose "Add Stripe payments - explore 3 approaches:
1. Payment Intents API (recommended)
2. Checkout Sessions
3. Payment Links
"

# Step 3: Parallel prototyping
/parallel "
1. Implement Payment Intents approach
2. Implement Checkout Sessions approach
3. Implement Payment Links approach
"

# Step 4: Synthesize with MCTS
# Score each approach on:
# - Implementation complexity
# - Customization options
# - Maintenance burden

# Step 5: Integrate winner
/integrate "Payment Intents approach (scored 0.88)"
```

---

### Workflow 4: Refactoring

**Scenario**: Migrate from REST to GraphQL

```bash
# Step 1: Scout existing structure
/scout "Map all REST endpoints and their usage"

# Step 2: Decompose migration
/decompose "Migrate REST API to GraphQL"

# Returns orthogonal tasks:
# - Define GraphQL schema
# - Create resolvers for users
# - Create resolvers for posts
# - Create resolvers for comments
# - Update client to use GraphQL
# - Write GraphQL tests
# (All can run in parallel as different files)

# Step 3: Execute in parallel
/parallel "<migration tasks>"

# Step 4: Integrate
/integrate "Wire GraphQL resolvers, connect to client, run integration tests"

# Step 5: Review
/review
# Checks for:
# - N+1 query problems
# - Authorization on resolvers
# - Error handling
```

---

### Workflow 5: Code Quality Improvement

**Scenario**: Improve existing codebase

```bash
# Step 1: Scout for issues
/scout "Find all console.logs, TODOs, and hardcoded values"

# Step 2: Review code
/review src/

# Step 3: Meta-review our review process
/meta-review "Our code review guidelines"
# Identifies: We're too focused on syntax, missing architecture issues

# Step 4: Decompose improvements
/decompose "Fix TODOs, remove console.logs, extract hardcoded values to config"

# Step 5: Execute
/parallel "<improvement tasks>"

# Step 6: Verify
/review
# Should show: No more critical issues
```

---

## Real-World Examples

### Example 1: Story Bridge PWA (Actual Project)

**Context**: PWA for Allie and Lu (age-appropriate content)

**Requirements**:
- Lu is the judge (IQ 140, S&P analyst standards)
- Ladybug theming
- Parent-child interaction patterns

**Workflow**:
```bash
# Step 1: Decompose
/decompose "Build Story Bridge PWA with Allie/Lu personas, ladybug theme,
progressive difficulty"

# Uses skill: story-bridge-development
# Uses skill: building-with-nextjs
# Uses skill: integrating-supabase (for progress tracking)

# Returns: 25 orthogonal tasks
# - UI components (ladybug theme)
# - Story content (age-appropriate)
# - Progress tracking
# - Parent dashboard
# - Lu's approval system (quality gates)

# Step 2: Execute in parallel
/parallel "<tasks 1-25>"

# Step 3: Integrate
/integrate "Wire components, add Lu's quality gates, parent dashboard"

# Step 4: Deploy
# Uses skill: deploying-to-vercel
```

**Time**: ~2 hours (vs ~20 hours sequential)

---

### Example 2: Quant Finance Analysis (Actual Domain)

**Context**: Analyze interest rate curve arbitrage opportunities

**Workflow**:
```bash
# Step 1: Fetch library docs
/docs "rateslib - focus on Curve and Swap classes"

# Step 2: Scout existing analysis
/scout "Find all rate curve analysis code"

# Step 3: Decompose analysis
/decompose "Analyze USD swap curve for arbitrage using rateslib"

# Uses skill: analyzing-rateslib
# Uses skill: axiom-relative-value

# Returns:
# - Load curve data
# - Calculate Greeks with dual numbers
# - Identify arbitrage spreads
# - Backtest strategies
# - Risk analysis

# Step 4: Execute
/parallel "<analysis tasks>"

# Uses skill: implementing-adjoint-ad (for efficient Greeks)

# Step 5: Synthesize findings
# MCTS scoring on:
# - Expected return
# - Risk metrics
# - Implementation complexity
```

**Skills Used**: 4 quant finance skills + 3 MCTS workflow skills

---

### Example 3: Midnight Building Session (Actual Pattern)

**Context**: Late-night focused implementation

**Workflow**:
```bash
# Uses skill: midnight-building

# Phase 1: Warm-up (30 min)
/scout "Review yesterday's work on auth system"
/review src/auth/  # Verify current state

# Phase 2: Deep work (90 min)
/decompose "Complete OAuth integration"
/parallel "<orthogonal tasks>"

# Uses skill: phoenix-interrupting
# Every 5 minutes: Check progress, interrupt if stuck

# Phase 3: Wind-down (30 min)
git add src/auth/
git commit -m "feat: complete OAuth integration"
/docs "OAuth security best practices"  # Prep for tomorrow
```

**Total**: 2.5 hours focused session

**Key**: Phoenix interrupts prevent research spirals during low-energy hours

---

### Example 4: MCP Server Development

**Context**: Build a custom MCP server

**Workflow**:
```bash
# Step 1: Build MCP server
/build-mcp "Create a time-tracking MCP server with tools:
- start_timer
- stop_timer
- get_current_session
- list_sessions"

# Returns: Complete TypeScript MCP server

# Step 2: Test with inspector
npx @modelcontextprotocol/inspector ./dist/index.js

# Step 3: Integrate with Claude Code
# Add to .claude.json
{
  "time-tracker": {
    "type": "stdio",
    "command": "node",
    "args": ["./time-tracker/dist/index.js"]
  }
}

# Step 4: Use in workflows
# Now can track time for parallel tasks automatically
```

---

## Getting Started

### Quick Start

```bash
# 1. Explore the system
/quick-start

# 2. Try a simple decomposition
/decompose "Add dark mode toggle to my app"

# 3. Execute one task manually to understand the pattern
# (Take task 1 from decomposition and implement it)

# 4. Try parallel execution with 3 simple tasks
/parallel "
1. Create utils/theme.js with light/dark constants
2. Create hooks/useTheme.js with theme state
3. Create components/ThemeToggle.tsx with UI
"

# 5. Integrate the results
/integrate "theme utility, hook, and toggle component"

# 6. Review your work
/review

# 7. Meta-review to learn
/meta-review "How could the decomposition have been better?"
```

### Learning Path

**Week 1: Core Workflow**
- Day 1-2: `/decompose` and understand orthogonality
- Day 3-4: `/parallel` with 3-5 tasks
- Day 5: `/integrate` and understand mock replacement
- Day 6-7: `/review` and understand severity levels

**Week 2: Advanced Patterns**
- Day 1-2: MCTS scoring and synthesis
- Day 3-4: Phoenix interrupts and toxic pattern detection
- Day 5-6: Meta-review and instruction improvement
- Day 7: Alpha-Beta-Gamma timeframe planning

**Week 3: Domain Skills**
- Day 1-3: Apply to your domain (web dev, data, etc.)
- Day 4-5: Create custom skills for your patterns
- Day 6-7: Build custom agents for your workflows

### Best Practices

**DO**:
✅ Start with `/decompose` for complex tasks
✅ Ensure tasks are truly orthogonal (different files)
✅ Use `/parallel` for 5+ orthogonal tasks
✅ Monitor for toxic patterns (planning, TODOs, research)
✅ `/review` before considering work complete
✅ Use `/meta-review` to improve your processes

**DON'T**:
❌ Skip decomposition and try to parallelize sequential work
❌ Create tasks with dependencies and call them "orthogonal"
❌ Let tasks run >10 minutes without Phoenix interrupt
❌ Merge results without integration tests
❌ Ignore meta-review findings

---

## Advanced Topics

### Creating Custom Agents

**Template**: `~/.claude/agents/my-agent.md`

```markdown
---
name: my-agent
model: sonnet
skills:
  - my-skill-1
  - my-skill-2
---

# My Agent

**Purpose**: [What this agent does]

**Use when**: [Specific scenarios]

## Instructions

[Detailed instructions for the agent]

## Skills Used

[Reference to skills with workflow]

## Examples

[Concrete examples of usage]
```

### Creating Custom Skills

**Template**: `~/.claude/skills/my-skill/SKILL.md`

```markdown
---
name: my-skill
description: [One-line description for agent discovery]
---

# My Skill

**Purpose**: [What this skill teaches]

## When to Use

[Specific scenarios]

## Core Patterns

[Detailed patterns and examples]

## Integration with Other Skills

[How this connects to existing skills]

## Checklist

- [ ] [Success criterion 1]
- [ ] [Success criterion 2]

## Related Skills

- `other-skill-1` - [How they relate]
```

### Creating Custom Slash Commands

**Template**: `~/.claude/commands/my-command.md`

```markdown
---
argument-hint: "<what user provides>"
---

@my-agent

[Prompt template with {{arg}} placeholder]

[Additional instructions]
```

### Customizing for Your Domain

**Example: Add Data Science Workflow**

```bash
# 1. Create skill
~/.claude/skills/analyzing-data-with-pandas/SKILL.md

# 2. Create agent
~/.claude/agents/data-analyzer.md
# Uses: analyzing-data-with-pandas, executing-parallel-tasks

# 3. Create command
~/.claude/commands/analyze-data.md
# @data-analyzer
```

Now you can:
```bash
/analyze-data "Explore customer churn dataset"
```

---

### Monitoring and Metrics

**Track Agent Usage**:
```bash
# In nova-memory
/search "agent usage"
# See patterns: Which agents used most? Success rates?
```

**Track Skill Effectiveness**:
```bash
# After using a skill
/meta-review "How well did decomposing-into-orthogonal-tasks work for this task?"
```

**Track Workflow Improvements**:
```
Measure:
- Time to completion (parallel vs sequential)
- Quality metrics (review severity counts)
- Rework rate (how often do integrations fail?)
```

---

### Troubleshooting

**Problem**: Tasks aren't truly orthogonal (conflicts during execution)

**Solution**:
```bash
/meta-review "Task list from decomposition"
# Identifies: Tasks modifying same files
# Fix: Re-decompose with strict file separation
```

---

**Problem**: Parallel execution hitting resource limits

**Solution**:
```bash
# Batch execution
/parallel "Tasks 1-10"  # First batch
/parallel "Tasks 11-20" # Second batch (after first completes)
```

---

**Problem**: Integration always fails

**Solution**:
```bash
# Ensure mocks were used properly
/review "Check if all parallel tasks used mocks to avoid dependencies"

# Common issue: Tasks making real DB calls instead of mocking
# Fix: Re-run with explicit mock instructions
```

---

**Problem**: Phoenix interrupts too aggressive

**Solution**:
```markdown
# In parallel-executor agent, adjust criteria:
- Increase time before first interrupt (5 min → 7 min)
- Allow some documentation (README, API docs)
- Focus on code files only
```

---

## System Maintenance

### Keeping Skills Updated

```bash
# Review skills quarterly
/meta-review "All skills in ~/.claude/skills/"

# Update based on:
# - New patterns discovered
# - Technologies evolved
# - Better practices learned
```

### Agent Evolution

```bash
# After major project:
/meta-review "Agent effectiveness in recent project"

# Improve agents based on:
# - What worked well (keep/enhance)
# - What didn't work (remove/change)
# - What was missing (add new agents)
```

### Workflow Refinement

```bash
# Monthly review
1. List common workflows used
2. Identify bottlenecks
3. Create new slash commands for frequent patterns
4. Update agent instructions based on learnings
```

---

## Summary

This system provides:

**8 Agents** for specialized tasks
**22 Skills** encoding domain knowledge
**9 Slash Commands** for easy invocation

**Core Workflow**:
```
/decompose → /parallel → /integrate → /review → /meta-review
```

**Key Principles**:
- **Orthogonality**: Tasks modify different files, no dependencies
- **5-10 Minutes**: Short enough to prevent drift
- **Phoenix Interrupts**: Kill bad paths early
- **MCTS Synthesis**: Choose best from parallel results
- **Meta-Review**: Continuously improve the system

**Next Steps**:
1. Run `/quick-start` to see system overview
2. Try `/decompose` on a real task
3. Practice with `/parallel` on 3-5 orthogonal tasks
4. Review your work with `/review`
5. Improve your process with `/meta-review`

---

**Last Updated**: 2025-11-10
**Version**: 1.0
**Maintainer**: Peter + Claude Code
