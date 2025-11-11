# Agent System Tests

This document contains simple test scenarios for each agent in the system. Each test includes:
- Test description
- Input prompt
- Expected behavior
- Success criteria

## Test 1: Task Decomposer - Simple Task Breakdown

**Test Description**: Verify task-decomposer breaks down a simple web feature into orthogonal tasks.

**Input Prompt**:
```
@task-decomposer

Break this task into orthogonal chunks:

Add user authentication to a web application with login, registration, and password reset features.
```

**Expected Behavior**:
- Should identify 3-5 orthogonal tasks
- Tasks should be 5-10 minute estimates
- Tasks should modify different files (no conflicts)
- Should avoid technology assumptions
- Should suggest context discovery

**Success Criteria**:
- ✅ Tasks are truly orthogonal (different files/components)
- ✅ Each task has clear deliverable
- ✅ No shared dependencies between tasks
- ✅ No TODOs or placeholder comments


## Test 2: Scout - Codebase Exploration

**Test Description**: Verify scout can explore nova-mcp codebase and identify patterns.

**Input Prompt**:
```
@scout

Explore the nova-mcp repository and find:
1. How many MCP servers exist?
2. What tools does the puppeteer/nova-playwright server expose?
3. What is the build command pattern across TypeScript servers?
```

**Expected Behavior**:
- Should use Glob to find server directories
- Should use Grep to search for tool definitions
- Should read package.json files for build commands
- Should provide structured findings

**Success Criteria**:
- ✅ Finds all MCP server directories
- ✅ Identifies tool patterns correctly
- ✅ Uses fast tools (Glob/Grep) before Read
- ✅ Provides clear summary


## Test 3: Code Reviewer - Security Focus

**Test Description**: Verify code-reviewer identifies security issues.

**Input Prompt**:
```
@code-reviewer

Review this code for security issues:

```javascript
app.post('/login', (req, res) => {
  const { username, password } = req.body;
  const query = `SELECT * FROM users WHERE username = '${username}' AND password = '${password}'`;
  db.query(query, (err, results) => {
    if (results.length > 0) {
      res.json({ token: username });
    } else {
      res.status(401).send('Invalid credentials');
    }
  });
});
```
```

**Expected Behavior**:
- Should identify SQL injection vulnerability
- Should identify plaintext password storage
- Should identify weak token generation
- Should provide severity ratings (🔴 Critical)
- Should suggest specific fixes

**Success Criteria**:
- ✅ Identifies SQL injection (Critical)
- ✅ Identifies password storage issue (Critical)
- ✅ Identifies token weakness (Warning)
- ✅ Provides actionable remediation steps


## Test 4: Meta-Reviewer - Instruction Analysis

**Test Description**: Verify meta-reviewer can analyze agent instructions for generalization issues.

**Input Prompt**:
```
@meta-reviewer

Review this agent instruction for hardcoded assumptions:

"Create a new Express.js route handler in routes/auth.js that implements JWT authentication
using the jsonwebtoken library. The handler should validate user credentials against the
users table in PostgreSQL."
```

**Expected Behavior**:
- Should identify Express.js assumption
- Should identify JWT/jsonwebtoken specificity
- Should identify hardcoded path "routes/auth.js"
- Should identify PostgreSQL assumption
- Should suggest generic alternatives

**Success Criteria**:
- ✅ Identifies all technology assumptions
- ✅ Identifies hardcoded paths
- ✅ Suggests context discovery approach
- ✅ Provides before/after examples


## Test 5: AI Docs Fetcher - Library Documentation

**Test Description**: Verify ai-docs-fetcher can retrieve and save library documentation.

**Input Prompt**:
```
@ai-docs-fetcher

Fetch documentation for the React hooks API, focusing on useState and useEffect.
Save to .claude/references/react-hooks.md
```

**Expected Behavior**:
- Should use mcp__context7__resolve-library-id first
- Should fetch docs with mcp__context7__get-library-docs
- Should focus on requested topic (hooks)
- Should save formatted markdown to specified path
- Should include usage examples

**Success Criteria**:
- ✅ Successfully resolves React library ID
- ✅ Fetches relevant documentation
- ✅ Creates properly formatted markdown file
- ✅ Includes code examples for useState/useEffect


## Test 6: Parallel Executor - Task Orchestration

**Test Description**: Verify parallel-executor can coordinate multiple orthogonal tasks.

**Input Prompt**:
```
@parallel-executor

Execute these orthogonal tasks in parallel:

1. Create utils/hash.js with password hashing functions
2. Create utils/token.js with JWT generation/validation
3. Create utils/email.js with email sending functionality

Monitor for completion and merge results.
```

**Expected Behavior**:
- Should launch 3 Task agents in parallel
- Should verify tasks are orthogonal
- Should monitor for toxic patterns (planning loops, TODOs)
- Should report completion status
- Should suggest integration approach

**Success Criteria**:
- ✅ Launches parallel Task agents (not sequential)
- ✅ Tasks execute without conflicts
- ✅ Detects and interrupts if planning spiral occurs
- ✅ All tasks produce concrete files


## Test 7: MCP Builder - Server Creation

**Test Description**: Verify mcp-builder can create a basic MCP server.

**Input Prompt**:
```
@mcp-builder

Create a simple MCP server in TypeScript that provides a single tool "reverse_string"
which takes a string parameter and returns it reversed.
```

**Expected Behavior**:
- Should create proper MCP server structure
- Should use @modelcontextprotocol/sdk
- Should implement stdio transport
- Should define tool with proper schema
- Should include package.json and tsconfig.json

**Success Criteria**:
- ✅ Server follows MCP SDK patterns
- ✅ Tool has proper parameter schema
- ✅ Executable with shebang line
- ✅ Includes all necessary config files


## Test 8: Integration Synthesizer - Merging Results

**Test Description**: Verify integration-synthesizer can merge parallel work.

**Input Prompt**:
```
@integration-synthesizer

I have completed 3 parallel tasks that created:
- auth/hash.js (password hashing)
- auth/token.js (JWT handling)
- auth/middleware.js (auth middleware)

Create integration code and tests to wire these together.
```

**Expected Behavior**:
- Should analyze existing components
- Should create integration layer
- Should wire components together
- Should replace any mocks with real implementations
- Should create integration tests

**Success Criteria**:
- ✅ Components properly integrated
- ✅ No mocks remain in final code
- ✅ Integration tests cover key flows
- ✅ Error handling tested

---

## Running Tests

To run these tests:

1. Copy the input prompt from a test
2. Paste into Claude Code conversation
3. Verify the agent's behavior matches expectations
4. Check off success criteria

## Test Results

Test results should be documented below with timestamp and pass/fail status.

### Test Run: [DATE]

- [ ] Test 1: Task Decomposer
- [ ] Test 2: Scout
- [ ] Test 3: Code Reviewer
- [ ] Test 4: Meta-Reviewer
- [ ] Test 5: AI Docs Fetcher
- [ ] Test 6: Parallel Executor
- [ ] Test 7: MCP Builder
- [ ] Test 8: Integration Synthesizer
