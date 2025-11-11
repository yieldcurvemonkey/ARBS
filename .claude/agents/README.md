
# Peter's Personal Agent System

A comprehensive multi-agent system for efficient software development, embodying axiom principles natively.

## Philosophy

This agent system implements the core ideas from axiom-mcp WITHOUT using axiom-mcp tools:

1. **5-10 Minute Tasks**: Too short for research drift
2. **Orthogonal Decomposition**: True parallelism, no dependencies
3. **Concrete Deliverables**: Files created = success metric
4. **Toxic Loop Interruption**: Detect and stop planning spirals
5. **No TODOs Policy**: Full implementation or nothing

## Agent Catalog

### 🎯 Core Workflow Agents

#### task-decomposer
**Purpose**: Break complex tasks into 5-10 min orthogonal chunks
**Model**: Sonnet
**When to use**: Starting any complex feature or system
**Skills used**: `decomposing-into-orthogonal-tasks`

**Example**:
```bash
/decompose "build REST API with authentication"
```

Output:
- Parallel tasks (different files, no dependencies)
- Reserve tasks (integration after parallel completion)
- Success criteria per task
- Mock strategy for orthogonality

---

#### parallel-executor
**Purpose**: Orchestrate parallel task execution with intervention
**Model**: Sonnet
**When to use**: After task decomposition
**Skills used**: `executing-parallel-tasks`, `interrupting-toxic-loops`, `phoenix-interrupting`

**Example**:
```bash
/parallel [decomposed tasks]
```

Monitors for:
- Planning without implementation (>5 min, no files)
- Research spirals ("let's analyze", "best approach")
- TODO accumulation
- Stub implementations (signatures without logic)

**Intervention**: Sends steering messages to redirect agents

---

#### integration-synthesizer
**Purpose**: Merge parallel results into cohesive systems
**Model**: Sonnet
**When to use**: After parallel execution completes
**Skills used**: `synthesizing-with-mcts`

**Example**:
```bash
/integrate "components from parallel execution"
```

Tasks:
1. Wire components together
2. Replace mocks with real implementations
3. Create integration layer
4. Write integration tests
5. Verify end-to-end flow

---

### 🔍 Discovery & Research Agents

#### scout
**Purpose**: Fast codebase exploration and discovery
**Model**: Haiku (for speed)
**When to use**: Unfamiliar codebase, finding specific implementations
**Tools**: Read, Grep, Glob, Bash (read-only)

**Example**:
```bash
/scout "find authentication implementation"
```

Output:
- Exact file:line locations
- Relevant code snippets
- Dependency relationships
- Architectural patterns

**Speed optimized**: Uses Haiku, minimal reads, stops when found

---

#### ai-docs-fetcher
**Purpose**: Fetch current library documentation via Context7
**Model**: Sonnet
**When to use**: Working with unfamiliar libraries, need API docs
**Tools**: Context7 MCP (resolve-library-id, get-library-docs), Write

**Example**:
```bash
/docs "next.js app router"
```

Output:
- Reference docs in `.claude/references/`
- Common patterns and examples
- API reference with working code
- Best practices and gotchas

**Library Coverage**:
- React ecosystem (Next.js, React Query, Zustand)
- Backend (Express, FastAPI, NestJS)
- Testing (Playwright, Jest, React Testing Library)
- Database & Auth (Supabase, Prisma, NextAuth)

---

### 🛠️ Specialized Builder Agents

#### mcp-builder
**Purpose**: Build MCP servers in TypeScript/Python
**Model**: Sonnet
**When to use**: Creating new MCP integrations

**Example**:
```bash
/build-mcp "GitHub issue tracker with labels and milestones"
```

Creates:
- Complete project structure
- Tool definitions with schemas
- Error handling and validation
- Environment configuration
- README and build scripts
- MCP Inspector ready

---

#### code-reviewer
**Purpose**: Comprehensive code review
**Model**: Sonnet
**When to use**: After implementation, before merge

**Example**:
```bash
/review src/auth/password.js
```

Review passes:
1. **Correctness**: Logic, edge cases, null handling
2. **Security**: OWASP Top 10, SQL injection, XSS, auth
3. **Performance**: Algorithmic complexity, N+1 queries, caching
4. **Maintainability**: Naming, DRY, single responsibility
5. **Testing**: Coverage, edge cases, error paths

Severity levels:
- 🔴 **Critical**: Must fix (security, data corruption, crashes)
- 🟡 **Warning**: Should fix (performance, missing error handling)
- 🔵 **Suggestion**: Consider (refactoring, documentation)

---

## Workflow Patterns

### Pattern 1: New Feature Implementation

```bash
# 1. Understand existing code
/scout "authentication system"

# 2. Decompose feature
/decompose "add OAuth login alongside existing password auth"

# 3. Execute in parallel
/parallel [decomposed tasks]
# Monitor: Intervene if planning >3 min without files

# 4. Integrate components
/integrate "OAuth and password auth modules"

# 5. Review
/review src/auth/
```

### Pattern 2: New Library Integration

```bash
# 1. Fetch documentation
/docs "supabase authentication"

# 2. Decompose integration
/decompose "integrate Supabase auth with existing app"

# 3. Execute and integrate
/parallel [tasks]
/integrate [components]

# 4. Review
/review src/integrations/supabase/
```

### Pattern 3: MCP Server Development

```bash
# 1. Fetch MCP SDK docs
/docs "@modelcontextprotocol/sdk tools and resources"

# 2. Scout existing servers for patterns
/scout "MCP server implementations"

# 3. Build server
/build-mcp "Weather API integration with current conditions and forecast"

# 4. Review
/review mcp-servers/weather/
```

### Pattern 4: Codebase Exploration & Refactoring

```bash
# 1. Explore architecture
/scout "application architecture and patterns"

# 2. Find specific implementations
/scout "database query patterns"

# 3. Review existing code
/review src/database/

# 4. Plan refactoring
/decompose "refactor database layer to use repository pattern"
```

## Agent Communication

Agents can @mention each other:

```markdown
# Scout feeds decomposer
@scout find all authentication-related files

@task-decomposer use the files found by scout to decompose
adding OAuth support

# Decomposer feeds executor
@parallel-executor execute the decomposition above

# Executor feeds synthesizer
@integration-synthesizer merge the components created by parallel-executor
```

## Intervention Strategies

### When to Intervene

**Time-based**:
- 2-3 minutes: Planning without file creation
- 5 minutes: No concrete progress

**Pattern-based**:
- "Let's analyze" / "best approach would be"
- "We should research"
- TODO comments appearing
- Stub functions without logic

### How to Intervene

**Direct steering message**:
```
Stop planning. Create src/auth/oauth.js NOW with working implementation.
Use the pattern from src/auth/password.js.
```

**Clarification with examples**:
```
Here's what I need in the file:
- export async function loginWithOAuth(provider, token)
- Verify token with provider API
- Create or update user in database
- Return session token

Create it now.
```

**Interrupt and restart**:
```
[Press ESC to interrupt]

Let me rephrase: Create src/auth/oauth.js immediately.
The file should have [specific requirements].
No research, no planning, just implementation.
```

## Skills Integration

Agents automatically invoke relevant skills:

| Agent | Skills Used |
|-------|-------------|
| task-decomposer | decomposing-into-orthogonal-tasks |
| parallel-executor | executing-parallel-tasks, interrupting-toxic-loops, phoenix-interrupting |
| integration-synthesizer | synthesizing-with-mcts |
| scout | (native exploration) |
| code-reviewer | (native review patterns) |
| ai-docs-fetcher | (uses Context7 MCP) |
| mcp-builder | (uses MCP SDK patterns) |

## Success Metrics

### Task Completion
- ✅ **Files created**: Concrete output on filesystem
- ✅ **No TODOs**: Full implementation
- ✅ **Has logic**: Not just stubs
- ✅ **Tests pass**: If tests created
- ✅ **Integration works**: Components wire together

### Time Efficiency
- ⏱️ **Parallel tasks**: 5-10 minutes each
- ⏱️ **Integration**: 10-15 minutes
- ⏱️ **Total feature**: 30-60 minutes (vs hours of sequential work)

### Quality Indicators
- 🔒 **Security**: No OWASP Top 10 vulnerabilities
- ⚡ **Performance**: Appropriate algorithmic complexity
- 📚 **Maintainability**: Clear code, good naming
- ✅ **Tested**: Critical paths covered

## File Organization

```
~/.claude/
├── agents/
│   ├── README.md (this file)
│   ├── task-decomposer.md
│   ├── parallel-executor.md
│   ├── integration-synthesizer.md
│   ├── scout.md
│   ├── ai-docs-fetcher.md
│   ├── mcp-builder.md
│   └── code-reviewer.md
├── commands/
│   ├── decompose.md
│   ├── parallel.md
│   ├── integrate.md
│   ├── scout.md
│   ├── docs.md
│   ├── build-mcp.md
│   ├── review.md
│   └── quick-start.md
└── skills/
    ├── decomposing-into-orthogonal-tasks/
    ├── executing-parallel-tasks/
    ├── synthesizing-with-mcts/
    ├── interrupting-toxic-loops/
    └── phoenix-interrupting/
```

## Memory Integration

Agent work is automatically tracked in nova-memory:

```bash
# Search for previous decompositions
mcp__nova-memory__search_notes({ query: "decomposition REST API" })

# Review past integrations
mcp__nova-memory__search_notes({ query: "integration OAuth" })
```

## Quick Reference Card

```bash
# DISCOVERY
/scout "what you're looking for"
/docs "library topic"

# IMPLEMENTATION
/decompose "complex task"
/parallel [after decomposition]
/integrate [after parallel]

# QUALITY
/review path/to/code

# BUILDING
/build-mcp "server description"

# HELP
/quick-start
```

## Principles in Practice

### ✅ Do This
- Decompose > 20 min tasks into parallel chunks
- Intervene after 2-3 min of planning
- Demand file creation as success metric
- Replace mocks in integration phase
- Review before merging

### ❌ Don't Do This
- Let agents plan for >5 minutes
- Accept TODO comments
- Accept stub implementations
- Skip integration phase
- Merge without review

## Extension Points

### Adding New Agents

Create agent file in `~/.claude/agents/`:

```markdown
---
name: my-agent
description: What it does and when to use it
model: sonnet
tools: (optional comma-separated list)
---

# My Agent

[Agent instructions and patterns]
```

Create slash command in `~/.claude/commands/`:

```markdown
---
argument-hint: "<what user provides>"
---

@my-agent

{{arg}}
```

### Adding Skills Integration

Reference skills in agent instructions:

```markdown
You automatically use the `skill-name` skill for this work.
```

Skill will be invoked when agent is active.

## Troubleshooting

### Agent Not Found
- Check filename matches agent name
- Verify YAML frontmatter is valid
- Restart Claude Code

### Agent Not Following Instructions
- Make instructions more specific
- Add concrete examples
- Intervene with steering messages

### Parallel Execution Too Slow
- Verify tasks are truly orthogonal
- Check for hidden dependencies
- Reduce task scope to 5-10 minutes

### Integration Failing
- Ensure all parallel tasks completed
- Check for interface mismatches
- Verify mocks were replaced

## Future Enhancements

Planned additions:
- security-auditor agent (deep security analysis)
- performance-optimizer agent (profiling and optimization)
- test-writer agent (comprehensive test generation)
- refactoring-expert agent (safe code refactoring)
- deployment-specialist agent (CI/CD and infrastructure)

---

**Built with**: Claude Code, MCP, Nova Memory
**Philosophy**: Axiom principles (action over planning, orthogonal decomposition, concrete deliverables)
**License**: Personal use by Peter Findley
