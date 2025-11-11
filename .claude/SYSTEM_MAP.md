# Claude Code Agent System Map

Visual reference guide showing how all components connect and work together.

## System Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  USER INTERFACE                                                  │
│  ─────────────────────────────────────────────────────────────  │
│  Slash Commands (9):                                            │
│  /decompose  /parallel  /integrate  /review  /meta-review       │
│  /scout  /docs  /build-mcp  /quick-start                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  AGENT LAYER                                                     │
│  ─────────────────────────────────────────────────────────────  │
│  Specialized Agents (8):                                        │
│                                                                  │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────────────┐  │
│  │task-         │  │parallel-      │  │integration-        │  │
│  │decomposer    │→ │executor       │→ │synthesizer         │  │
│  │(Sonnet)      │  │(Sonnet)       │  │(Sonnet)            │  │
│  └──────────────┘  └───────────────┘  └────────────────────┘  │
│                                                                  │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────────────┐  │
│  │code-         │  │scout          │  │ai-docs-            │  │
│  │reviewer      │  │(Haiku)        │  │fetcher             │  │
│  │(Sonnet)      │  │               │  │(Sonnet)            │  │
│  └──────────────┘  └───────────────┘  └────────────────────┘  │
│                                                                  │
│  ┌──────────────┐  ┌───────────────┐                           │
│  │mcp-          │  │meta-          │                           │
│  │builder       │  │reviewer       │                           │
│  │(Sonnet)      │  │(Opus)         │                           │
│  └──────────────┘  └───────────────┘                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  SKILL LAYER                                                     │
│  ─────────────────────────────────────────────────────────────  │
│  Knowledge Modules (22):                                        │
│                                                                  │
│  META-COGNITION (5):                                            │
│  • analyzing-with-mcts                                          │
│  • evaluating-alpha-beta-gamma                                  │
│  • expanding-then-compressing                                   │
│  • recognizing-emergence                                        │
│  • structuring-training-data                                    │
│                                                                  │
│  MCTS WORKFLOW (5):                                             │
│  • decomposing-into-orthogonal-tasks                            │
│  • executing-parallel-tasks                                     │
│  • synthesizing-with-mcts                                       │
│  • planning-multi-timeframe                                     │
│  • phoenix-interrupting                                         │
│                                                                  │
│  QUANT FINANCE (4):                                             │
│  • axiom-relative-value                                         │
│  • analyzing-rateslib                                           │
│  • integrating-quantlib                                         │
│  • implementing-adjoint-ad                                      │
│                                                                  │
│  DEVELOPMENT (5):                                               │
│  • building-with-nextjs                                         │
│  • integrating-supabase                                         │
│  • deploying-to-vercel                                          │
│  • managing-wsl-workflows                                       │
│  • midnight-building                                            │
│                                                                  │
│  OTHER (3):                                                     │
│  • interrupting-toxic-loops                                     │
│  • cultivating-consciousness                                    │
│  • story-bridge-development                                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  INTEGRATION LAYER                                               │
│  ─────────────────────────────────────────────────────────────  │
│  MCP Servers:                                                   │
│  • github (GitHub API)                                          │
│  • nova-memory (Knowledge management)                           │
│  • context7 (Library documentation)                             │
│  • nova-playwright (Browser automation)                         │
│  • brave-search (Web/local search)                              │
│  • axiom-mcp (Task orchestration)                               │
│  • postgresql-mcp (Database management)                         │
└─────────────────────────────────────────────────────────────────┘
```

## Core Workflow Map

```
USER REQUEST
    │
    ↓
┌────────────────────────────────────────────┐
│ /decompose "Build authentication system"  │
└───────────────┬────────────────────────────┘
                │
                ↓
    @task-decomposer agent
                │
                ↓
    decomposing-into-orthogonal-tasks skill
                │
                ↓
    ┌──────────────────────────────┐
    │ Returns:                     │
    │ • 20 parallel tasks          │
    │ • 3 reserve tasks            │
    │ • Success criteria           │
    │ • Mock strategy              │
    └───────────┬──────────────────┘
                │
                ↓
┌────────────────────────────────┐
│ /parallel "<tasks 1-20>"       │
└───────────┬────────────────────┘
            │
            ↓
    @parallel-executor agent
            │
            ├→ Launches 20 Task agents in parallel
            ├→ Uses phoenix-interrupting skill (5-min checkpoints)
            ├→ Monitors for toxic patterns
            └→ Intervenes with steering messages
            │
            ↓
    ┌──────────────────────────────┐
    │ Results:                     │
    │ • 20 components created      │
    │ • Files in isolation         │
    │ • Mocks used for deps        │
    └───────────┬──────────────────┘
                │
                ↓
┌────────────────────────────────────┐
│ /integrate "<components>"         │
└───────────┬────────────────────────┘
            │
            ↓
    @integration-synthesizer agent
            │
            ├→ Uses synthesizing-with-mcts skill
            ├→ MCTS scores each component
            ├→ Wires components together
            ├→ Replaces mocks with real implementations
            └→ Creates integration tests
            │
            ↓
    ┌──────────────────────────────┐
    │ Final integrated solution    │
    └───────────┬──────────────────┘
                │
                ↓
┌────────────────────────────────┐
│ /review                        │
└───────────┬────────────────────┘
            │
            ↓
    @code-reviewer agent
            │
            ├→ Correctness review
            ├→ Security review (OWASP Top 10)
            ├→ Performance review
            ├→ Maintainability review
            └→ Testing review
            │
            ↓
    ┌──────────────────────────────┐
    │ Issues with severity ratings │
    │ 🔴 Critical                  │
    │ 🟡 Warning                   │
    │ 🔵 Suggestion                │
    └───────────┬──────────────────┘
                │
                ↓
        PRODUCTION-READY CODE
```

## Agent → Skill → MCP Integration

```
TASK-DECOMPOSER AGENT
    │
    ├→ Uses Skills:
    │  └─ decomposing-into-orthogonal-tasks
    │
    ├→ May use MCP:
    │  └─ nova-memory (recall past decompositions)
    │
    └→ Output: Task list

PARALLEL-EXECUTOR AGENT
    │
    ├→ Uses Skills:
    │  ├─ executing-parallel-tasks
    │  └─ phoenix-interrupting
    │
    ├→ Uses Native Capabilities:
    │  └─ Task tool (launches parallel agents)
    │
    └→ Output: Completed components

INTEGRATION-SYNTHESIZER AGENT
    │
    ├→ Uses Skills:
    │  ├─ synthesizing-with-mcts
    │  └─ analyzing-with-mcts
    │
    └→ Output: Integrated system

CODE-REVIEWER AGENT
    │
    ├→ Uses Skills:
    │  └─ (implicit security knowledge)
    │
    └→ Output: Severity-rated issues

SCOUT AGENT
    │
    ├→ Uses Tools:
    │  ├─ Glob (file patterns)
    │  ├─ Grep (content search)
    │  └─ Read (targeted reads)
    │
    └→ Output: Structured summary

AI-DOCS-FETCHER AGENT
    │
    ├→ Uses MCP:
    │  ├─ context7__resolve-library-id
    │  └─ context7__get-library-docs
    │
    ├→ Uses Tools:
    │  └─ Write (save docs)
    │
    └→ Output: .claude/references/*.md

MCP-BUILDER AGENT
    │
    ├→ Uses Skills:
    │  └─ (implicit MCP SDK knowledge)
    │
    └→ Output: Complete MCP server

META-REVIEWER AGENT
    │
    ├→ Uses Skills:
    │  └─ recognizing-emergence (metacognitive patterns)
    │
    ├→ Uses MCP:
    │  └─ nova-memory (learn about metacognition)
    │
    └→ Output: Metacognitive analysis
```

## Skill Integration Patterns

### MCTS Workflow Pattern

```
decomposing-into-orthogonal-tasks
    │
    ├→ Creates: Task list
    │   • Parallel tasks (different files)
    │   • Reserve tasks (integration)
    │   • Success criteria
    │
    ↓
executing-parallel-tasks
    │
    ├→ Runs: All tasks simultaneously
    ├→ Uses: phoenix-interrupting (monitors)
    ├→ Produces: Multiple implementations
    │
    ↓
synthesizing-with-mcts
    │
    ├→ Scores: Each result (0.0 to 1.0)
    ├→ Chooses: Best or hybrid
    ├→ Outputs: Final solution
    │
    ↓
INTEGRATED SOLUTION
```

### Multi-Timeframe Pattern

```
analyzing-with-mcts
    │
    ├→ MCTS decision framework
    │   • Selection
    │   • Expansion
    │   • Simulation
    │   • Backpropagation
    │
    ↓
evaluating-alpha-beta-gamma
    │
    ├→ Alpha (hours): Immediate execution
    ├→ Beta (days): Tactical positioning
    ├→ Gamma (months): Strategic architecture
    │
    ↓
planning-multi-timeframe
    │
    └→ Coordinated plan across all horizons
```

### Explore-Compress Pattern

```
expanding-then-compressing
    │
    ├→ EXPAND: Create 3-5 approaches
    │
    ↓
decomposing-into-orthogonal-tasks
    │
    ├→ Each approach as parallel tasks
    │
    ↓
executing-parallel-tasks
    │
    ├→ All approaches run simultaneously
    │
    ↓
synthesizing-with-mcts
    │
    └→ COMPRESS: Choose best via scoring
```

## Domain-Specific Integrations

### Web Development Stack

```
USER: "Build Next.js app with Supabase"
    │
    ├→ /docs "Next.js Server Actions"
    │  └─ Uses: ai-docs-fetcher + context7 MCP
    │     └─ Saves: .claude/references/nextjs-server-actions.md
    │
    ├→ /decompose "Build app"
    │  └─ Uses: task-decomposer + building-with-nextjs skill
    │     └─ Returns: Next.js-specific tasks
    │
    ├→ /parallel "<tasks>"
    │  └─ Uses: parallel-executor
    │     └─ Creates: App Router components, API routes, Supabase client
    │
    ├→ /integrate "Wire Supabase to components"
    │  └─ Uses: integration-synthesizer + integrating-supabase skill
    │     └─ Wires: Auth, DB, real-time
    │
    └→ Deploy
       └─ Uses: deploying-to-vercel skill
          └─ Configures: Env vars, webhooks, CI/CD
```

### Quant Finance Stack

```
USER: "Analyze swap curve arbitrage"
    │
    ├→ /scout "Find existing rate analysis"
    │  └─ Uses: scout agent
    │     └─ Finds: Patterns in codebase
    │
    ├→ /docs "rateslib Curve and Swap"
    │  └─ Uses: ai-docs-fetcher + context7 MCP
    │     └─ Saves: .claude/references/rateslib-curves.md
    │
    ├→ /decompose "Analyze arbitrage"
    │  └─ Uses: task-decomposer + analyzing-rateslib skill
    │     └─ Returns: Curve loading, Greeks calc, arbitrage detection
    │
    ├→ /parallel "<analysis tasks>"
    │  └─ Uses: parallel-executor + implementing-adjoint-ad skill
    │     └─ Calculates: DV01, arbitrage spreads with dual numbers
    │
    └→ Synthesize findings
       └─ Uses: synthesizing-with-mcts + axiom-relative-value skill
          └─ Scores: Strategies on return, risk, complexity
```

## Cross-Cutting Concerns

### Phoenix Interrupts (Monitoring)

```
ANY parallel execution
    │
    └→ phoenix-interrupting skill
        │
        ├─ t=5 min:  Check for file creation
        ├─ t=10 min: Check for progress
        │
        ├─ Detects:
        │  • Research spirals (reading without implementing)
        │  • Planning loops (designing without coding)
        │  • TODO accumulation
        │  • Stub implementations
        │
        └─ Intervenes:
           └─ Steering message to get back on track
```

### Midnight Building (Work Style)

```
ANY late-night session
    │
    └→ midnight-building skill
        │
        ├─ Phase 1: Warm-up (30 min)
        │  └─ /scout + /review previous work
        │
        ├─ Phase 2: Deep work (90 min)
        │  ├─ /decompose + /parallel
        │  └─ Phoenix interrupts (extra important for low energy)
        │
        └─ Phase 3: Wind-down (30 min)
           ├─ /integrate + /review
           ├─ Commit working code
           └─ /docs for tomorrow's prep
```

### Meta-Review (Quality)

```
ANY agent or instruction
    │
    └→ meta-reviewer agent
        │
        ├─ Level 1: Context Awareness
        │  └─ What's assumed vs discovered?
        │
        ├─ Level 2: Constraint Appropriateness
        │  └─ Too rigid or too loose?
        │
        ├─ Level 3: Generalization
        │  └─ Works across languages/frameworks?
        │
        ├─ Level 4: Implicit Knowledge
        │  └─ What's required but not stated?
        │
        └─ Level 5: Meta Patterns
           └─ Higher-order patterns?
```

## Data Flow Examples

### Example 1: New Feature Development

```
"Add comment system"
    ↓
/decompose
    ↓
task-decomposer agent
    ↓
decomposing-into-orthogonal-tasks skill
    ↓
Returns 15 parallel tasks:
    • models/comment.sql
    • services/comment.js
    • api/comments.js
    • components/Comment.tsx
    • components/CommentForm.tsx
    • utils/validation.js
    • utils/sanitization.js  ← Security from past meta-review
    • tests/comment.test.js
    ... (7 more)
    ↓
/parallel "<all 15 tasks>"
    ↓
parallel-executor launches Task agents
    ↓
phoenix-interrupting monitors:
    • t=5: Task 7 has TODO → warning
    • t=8: Task 7 still planning → INTERRUPT
    • Steering: "Create utils/sanitization.js NOW with DOMPurify"
    • t=10: Task 7 complete ✓
    ↓
All 15 components created
    ↓
/integrate "Comment system components"
    ↓
integration-synthesizer:
    • Wires components
    • Replaces mocks
    • Creates integration tests
    ↓
/review
    ↓
code-reviewer:
    • Checks XSS prevention (sanitization)
    • Checks SQL injection (parameterized queries)
    • ✓ All critical checks pass
    ↓
PRODUCTION-READY COMMENT SYSTEM
```

### Example 2: Learning New Library

```
"Use tRPC in Next.js"
    ↓
/docs "tRPC procedures and routers"
    ↓
ai-docs-fetcher:
    • context7__resolve-library-id("trpc")
    • context7__get-library-docs("/trpc/trpc", topic: "procedures")
    • Write to .claude/references/trpc-procedures.md
    ↓
/decompose "Add tRPC to Next.js app"
    ↓
task-decomposer (with tRPC context):
    • Returns tRPC-specific tasks:
      - Create server/routers/app.ts
      - Create server/context.ts
      - Create utils/trpc.ts (client)
      - Create api/trpc/[trpc].ts (Next.js API route)
      - Create components using tRPC hooks
    ↓
/parallel "<tRPC tasks>"
    ↓
All tRPC components created correctly
(Documentation prevented common mistakes)
    ↓
/integrate "Wire tRPC client to server"
    ↓
WORKING tRPC INTEGRATION
```

## Slash Command Quick Reference

```bash
# Core Workflow
/decompose "task"        → @task-decomposer
/parallel "tasks"        → @parallel-executor
/integrate "components"  → @integration-synthesizer

# Quality
/review                  → @code-reviewer
/meta-review "agent"     → @meta-reviewer

# Discovery
/scout "goal"            → @scout
/docs "library"          → @ai-docs-fetcher

# Building
/build-mcp "spec"        → @mcp-builder

# Help
/quick-start             → System overview
```

## File Locations

```
~/.claude/
├── agents/              # 8 agents
│   ├── task-decomposer.md
│   ├── parallel-executor.md
│   ├── integration-synthesizer.md
│   ├── code-reviewer.md
│   ├── scout.md
│   ├── ai-docs-fetcher.md
│   ├── mcp-builder.md
│   └── meta-reviewer.md
│
├── skills/              # 22 skills
│   ├── decomposing-into-orthogonal-tasks/
│   ├── executing-parallel-tasks/
│   ├── synthesizing-with-mcts/
│   ├── analyzing-with-mcts/
│   ├── building-with-nextjs/
│   └── ... (17 more)
│
├── commands/            # 9 slash commands
│   ├── decompose.md
│   ├── parallel.md
│   ├── integrate.md
│   ├── review.md
│   ├── meta-review.md
│   ├── scout.md
│   ├── docs.md
│   ├── build-mcp.md
│   └── quick-start.md
│
├── references/          # Fetched documentation
│   ├── react-hooks.md
│   ├── trpc-procedures.md
│   └── ... (created by /docs command)
│
├── README.md            # Main documentation (this file)
├── WORKFLOWS.md         # Integration patterns
├── SYSTEM_MAP.md        # Visual reference
└── AGENT_TESTS.md       # Test scenarios
```

---

**Last Updated**: 2025-11-10
**Version**: 1.0
