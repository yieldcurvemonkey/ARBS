---
argument-hint: ""
---

# Peter's Agent System - Quick Start

Your personal multi-agent system for efficient development.

## Available Agents

### 🎯 Core Workflow Agents
- **task-decomposer**: Break complex tasks into 5-10 min orthogonal chunks
- **parallel-executor**: Run tasks in parallel, intervene on toxic patterns
- **integration-synthesizer**: Merge parallel results into cohesive systems

### 🔍 Discovery & Research
- **scout**: Fast codebase exploration and pattern discovery
- **ai-docs-fetcher**: Fetch current library documentation via Context7

### 🛠️ Specialized Builders
- **mcp-builder**: Build MCP servers in TypeScript/Python
- **code-reviewer**: Comprehensive code review (security, performance, quality)

## Quick Commands

```bash
/decompose "build REST API with authentication"
/parallel [after decomposition]
/integrate [after parallel execution]

/scout "find authentication implementation"
/docs "next.js app router"
/review src/auth/password.js
/build-mcp "GitHub issue tracker"
```

## Axiom Principles (Native)

All agents embody these principles WITHOUT using axiom-mcp tools:

1. **5-10 Minute Tasks**: Too short to drift into research
2. **Orthogonal Execution**: No dependencies, true parallelism
3. **Concrete Deliverables**: Files created = success
4. **Interrupt Toxic Loops**: Stop planning, force implementation
5. **No TODOs**: Implement fully or not at all

## Typical Workflow

```
1. @task-decomposer: Break down complex task
   ↓
2. @parallel-executor: Run orthogonal tasks
   ↓ (monitor and intervene if needed)
3. @integration-synthesizer: Wire components
   ↓
4. @code-reviewer: Review integrated system
```

## Example: Build Feature

```bash
# Step 1: Decompose
/decompose "user profile feature with edit, avatar upload, and settings"

# Step 2: Execute parallel (agent creates 3-5 files simultaneously)
/parallel [tasks from decomposition]

# Step 3: Integrate
/integrate "profile components from parallel execution"

# Step 4: Review
/review src/features/profile/
```

## Agent Communication

Agents can @mention each other:
- `@scout` can feed findings to `@task-decomposer`
- `@task-decomposer` output goes to `@parallel-executor`
- `@parallel-executor` output goes to `@integration-synthesizer`
- `@code-reviewer` reviews any agent's output

## Skills Integration

Agents automatically use relevant skills:
- `decomposing-into-orthogonal-tasks`
- `executing-parallel-tasks`
- `synthesizing-with-mcts`
- `interrupting-toxic-loops`
- `phoenix-interrupting`

## Tips

- Use `/scout` before `/decompose` for unfamiliar codebases
- Use `/docs` when working with new libraries
- Use `/review` after integration, before merging
- Intervene early: 2-3 minutes of planning = send steering message
- No TODOs allowed: full implementation or nothing

## Memory Integration

All agent work is tracked in nova-memory for future reference.

---

**Remember**: Agents embody axiom principles natively. They prevent research spirals, enforce concrete deliverables, and interrupt toxic patterns automatically.
