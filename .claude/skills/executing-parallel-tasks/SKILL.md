---
name: executing-parallel-tasks
description: Execute orthogonal tasks simultaneously with workspace isolation and progress monitoring. Use when running decomposed tasks in parallel, need fast iteration, or exploring multiple approaches. Includes timeout handling and automatic retries.
---

# Executing Parallel Tasks

**Purpose**: Run orthogonal tasks simultaneously with isolation, monitoring, and error handling.

## When to Use

- Tasks decomposed into orthogonal pieces (see skill: `decomposing-into-orthogonal-tasks`)
- Need speed through parallelization
- Exploring multiple approaches simultaneously (MCTS exploration)
- Testing different implementations
- Building independent components that merge later

## Core Principles

### Principle 1: Workspace Isolation

**Each task runs in isolated workspace**:
```
/tmp/task-1-workspace/
  ├── package.json
  ├── src/
  └── tests/

/tmp/task-2-workspace/
  ├── package.json
  ├── src/
  └── tests/
```

**Why**: Prevents file conflicts, enables true parallelism

**Avoid**:
```
/shared-workspace/
  ├── task-1-editing-user.js  ← Conflict!
  └── task-2-editing-user.js  ← Conflict!
```

### Principle 2: Observable Progress

**Monitor each task independently**:
- Real-time output streaming
- File creation detection
- Completion pattern matching
- Error detection

**Patterns indicating completion**:
```
"File created: src/auth.js"
"Successfully created models/user.js"
"✓ All tests passing"
Next prompt appears (">")
```

### Principle 3: Timeout and Interrupts

**Every task has**:
- Maximum execution time (default: 10 minutes)
- Interrupt capability (kill runaway processes)
- Automatic retry on failure (up to 3 attempts)

**Phoenix Integration** (see skill: `phoenix-interrupting`):
- 5-minute checkpoints
- File change detection
- Research spiral detection

### Principle 4: Failure Handling

**Strategies**:
1. **Retry**: Same task, fresh workspace (transient failures)
2. **Skip**: Mark as failed, continue others (optional task)
3. **Reserve**: Activate backup approach (critical task)
4. **Abort**: Stop all if prerequisite fails (rare)

## Execution Patterns

### Pattern 1: Pure Parallel (No Dependencies)

**All tasks run simultaneously**:

```typescript
const tasks = [
  { name: 'models', file: 'models/user.js', timeout: 5 },
  { name: 'auth', file: 'auth/password.js', timeout: 5 },
  { name: 'routes', file: 'routes/auth.js', timeout: 10 },
  { name: 'middleware', file: 'middleware/verify.js', timeout: 10 },
  { name: 'tests', file: 'tests/auth.test.js', timeout: 10 }
];

// Execute all in parallel
const results = await executeParallel(tasks);

// All complete or timeout independently
```

**Timeline**:
```
t=0:  All 5 tasks start simultaneously
t=5:  models and auth complete (5 min each)
t=10: routes, middleware, tests complete (10 min each)
```

### Pattern 2: Parallel + Reserve (Integration After)

**Reserve task waits for others**:

```typescript
const parallelTasks = [
  { name: 'component-1', file: 'comp1.js' },
  { name: 'component-2', file: 'comp2.js' },
  { name: 'component-3', file: 'comp3.js' }
];

const reserveTasks = [
  {
    name: 'integration',
    file: 'index.js',
    dependsOn: ['component-1', 'component-2', 'component-3']
  }
];

// Execute parallel tasks
const compResults = await executeParallel(parallelTasks);

// Then execute reserve tasks
const finalResults = await executeReserve(reserveTasks, compResults);
```

**Timeline**:
```
t=0:  comp1, comp2, comp3 start in parallel
t=10: All components complete
t=10: integration starts (with component results)
t=15: integration complete
```

### Pattern 3: Race (First Success Wins)

**Multiple approaches, best wins**:

```typescript
const approaches = [
  { name: 'minimal', prompt: 'Simplest implementation' },
  { name: 'robust', prompt: 'Error handling and validation' },
  { name: 'performant', prompt: 'Optimized for speed' }
];

// Execute all in parallel
const results = await executeRace(approaches);

// First to complete successfully wins
const winner = results.find(r => r.success);
```

**Use Cases**:
- Exploring different algorithms
- Testing implementation approaches
- Speed optimization (fastest wins)

### Pattern 4: Batch with Staggering

**Start tasks in batches to manage resources**:

```typescript
const allTasks = [...]; // 20 tasks

const batches = chunk(allTasks, 5); // 5 tasks per batch

for (const batch of batches) {
  await executeParallel(batch);
  // Next batch starts after previous completes
}
```

**Why**: Prevents resource exhaustion with many tasks

## Practical Implementation

### Implementation 1: Simple Parallel Execution

```bash
#!/bin/bash
# Execute tasks in parallel with bash

# Define tasks
tasks=(
  "node task1.js > logs/task1.log 2>&1"
  "node task2.js > logs/task2.log 2>&1"
  "node task3.js > logs/task3.log 2>&1"
)

# Start all in background
pids=()
for task in "${tasks[@]}"; do
  eval "$task" &
  pids+=($!)
done

# Wait for all to complete
for pid in "${pids[@]}"; do
  wait $pid
  echo "Task $pid completed"
done
```

### Implementation 2: Workspace Isolation

```typescript
import { spawn } from 'child_process';
import { mkdtempSync, rmSync } from 'fs';
import { join } from 'path';

async function executeInIsolation(task) {
  // Create temp workspace
  const workspace = mkdtempSync(join('/tmp', `task-${task.name}-`));

  try {
    // Execute task in workspace
    const result = await new Promise((resolve, reject) => {
      const proc = spawn('node', [task.script], {
        cwd: workspace,
        timeout: task.timeout * 60 * 1000
      });

      let output = '';
      proc.stdout.on('data', chunk => {
        output += chunk.toString();
        // Check for completion patterns
        if (output.includes('File created:')) {
          console.log(`${task.name}: File detected`);
        }
      });

      proc.on('exit', code => {
        resolve({ success: code === 0, output, workspace });
      });

      proc.on('error', reject);

      // Timeout handler
      setTimeout(() => {
        proc.kill('SIGTERM');
        reject(new Error('Timeout'));
      }, task.timeout * 60 * 1000);
    });

    return result;

  } finally {
    // Cleanup workspace
    if (!task.keepWorkspace) {
      rmSync(workspace, { recursive: true, force: true });
    }
  }
}
```

### Implementation 3: Progress Monitoring

```typescript
class TaskMonitor {
  constructor(task) {
    this.task = task;
    this.startTime = Date.now();
    this.filesCreated = [];
    this.checkpoints = [];
  }

  onOutput(chunk) {
    const output = chunk.toString();

    // Detect file creation
    const fileMatch = output.match(/File created: (.+)/);
    if (fileMatch) {
      this.filesCreated.push(fileMatch[1]);
      console.log(`✓ ${this.task.name}: ${fileMatch[1]}`);
    }

    // Detect TODOs (warning sign)
    if (output.includes('TODO:')) {
      console.warn(`⚠ ${this.task.name}: TODO detected`);
    }

    // Phoenix interrupt: no files after 5 min
    const elapsed = (Date.now() - this.startTime) / 60000;
    if (elapsed > 5 && this.filesCreated.length === 0) {
      console.error(`✗ ${this.task.name}: No files created after 5 min`);
      return { interrupt: true, reason: 'No progress' };
    }
  }

  getStatus() {
    return {
      elapsed: (Date.now() - this.startTime) / 60000,
      filesCreated: this.filesCreated.length,
      success: this.filesCreated.length > 0
    };
  }
}
```

### Implementation 4: Retry Logic

```typescript
async function executeWithRetry(task, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`${task.name}: Attempt ${attempt}/${maxRetries}`);

      const result = await executeInIsolation(task);

      if (result.success) {
        return result;
      }

      console.warn(`${task.name}: Attempt ${attempt} failed`);

    } catch (error) {
      console.error(`${task.name}: Attempt ${attempt} error: ${error.message}`);

      if (attempt === maxRetries) {
        throw new Error(`Task ${task.name} failed after ${maxRetries} attempts`);
      }

      // Exponential backoff
      await new Promise(resolve => setTimeout(resolve, 1000 * Math.pow(2, attempt)));
    }
  }
}
```

## Output Collection and Merge

### Collecting Results

```typescript
const results = await Promise.all(
  tasks.map(task => executeInIsolation(task))
);

// Group by success/failure
const successful = results.filter(r => r.success);
const failed = results.filter(r => !r.success);

console.log(`✓ Success: ${successful.length}/${results.length}`);
console.log(`✗ Failed: ${failed.length}/${results.length}`);
```

### Merging Workspaces

```typescript
// After all tasks complete, merge results
for (const result of successful) {
  // Copy files from isolated workspace to final location
  const files = findFiles(result.workspace);

  for (const file of files) {
    const destPath = join('final', result.task.name, file);
    copyFile(file, destPath);
  }
}
```

## Monitoring Dashboard

**Real-time status**:

```
Parallel Execution Dashboard
============================

Task 1: models/user.js          [✓] Complete (4m 23s)
  Files: models/user.js
  Status: Tests passing

Task 2: auth/password.js        [✓] Complete (5m 01s)
  Files: auth/password.js, auth/password.test.js
  Status: All checks passed

Task 3: routes/auth.js          [⚠] In Progress (7m 15s)
  Files: routes/auth.js
  Status: TODO detected - monitoring

Task 4: middleware/verify.js    [✓] Complete (6m 45s)
  Files: middleware/verify.js
  Status: Implementation complete

Task 5: tests/auth.test.js      [✗] Failed (Timeout 10m)
  Files: tests/auth.test.js (incomplete)
  Status: Retrying (Attempt 2/3)

Overall: 3/5 complete | 1 in progress | 1 retrying
```

## Common Patterns

### Pattern: API Endpoints

```typescript
const endpoints = [
  { name: 'users', route: '/api/users', timeout: 5 },
  { name: 'auth', route: '/api/auth', timeout: 5 },
  { name: 'posts', route: '/api/posts', timeout: 5 }
];

// All endpoints built in parallel
const results = await executeParallel(endpoints);
```

### Pattern: Test Suites

```typescript
const testSuites = [
  { name: 'unit', script: 'npm run test:unit' },
  { name: 'integration', script: 'npm run test:integration' },
  { name: 'e2e', script: 'npm run test:e2e' }
];

// Run all test suites in parallel
const results = await executeParallel(testSuites);
```

### Pattern: Build Variants

```typescript
const builds = [
  { name: 'dev', env: { NODE_ENV: 'development' } },
  { name: 'prod', env: { NODE_ENV: 'production' } },
  { name: 'test', env: { NODE_ENV: 'test' } }
];

// Build all variants in parallel
const results = await executeParallel(builds);
```

## Integration with Other Skills

**Use with**:
- `decomposing-into-orthogonal-tasks` - Create task list for parallel execution
- `synthesizing-with-mcts` - Merge results after parallel execution
- `phoenix-interrupting` - Monitor individual task execution
- `interrupting-toxic-loops` - Orchestrate parallel branches
- `midnight-building` - Execute during focused sessions

**Workflow**:
```
1. decomposing-into-orthogonal-tasks
   ↓ Creates independent tasks
2. executing-parallel-tasks (this skill)
   ↓ Runs all simultaneously
3. synthesizing-with-mcts
   ↓ Merges best results
4. Integrated solution
```

## Checklist

- [ ] Tasks decomposed into orthogonal pieces
- [ ] Workspace isolation configured (temp directories)
- [ ] Timeout limits set (default: 10 min)
- [ ] Progress monitoring enabled (file detection)
- [ ] Retry logic configured (max 3 attempts)
- [ ] Output collection strategy defined
- [ ] Merge strategy planned (see: synthesizing-with-mcts)
- [ ] Resource limits considered (max parallel tasks)

## Common Pitfalls

**Pitfall 1: Non-Orthogonal Tasks**
- Problem: Tasks conflict on same files
- Fix: Use `decomposing-into-orthogonal-tasks` skill properly

**Pitfall 2: No Workspace Isolation**
- Problem: Tasks overwrite each other
- Fix: Isolated temp directories per task

**Pitfall 3: No Timeout**
- Problem: Hung tasks run forever
- Fix: Always set max execution time (10 min default)

**Pitfall 4: Ignoring Failed Tasks**
- Problem: Broken components merged into final result
- Fix: Only merge successful tasks, retry or skip failures

**Pitfall 5: Too Many Parallel Tasks**
- Problem: Resource exhaustion (CPU, memory)
- Fix: Batch execution (5-10 tasks per batch)

## Related Skills

- `decomposing-into-orthogonal-tasks` - Prepare tasks for execution
- `synthesizing-with-mcts` - Merge parallel results
- `phoenix-interrupting` - Individual task monitoring
- `interrupting-toxic-loops` - Parallel branch orchestration
- `analyzing-with-mcts` - Evaluate parallel approaches

## Advanced Topics

See resources in this skill folder:
- `advanced-1-resource-management.md` - CPU/memory limits
- `advanced-2-distributed-execution.md` - Execution across machines
- `advanced-3-failure-recovery.md` - Sophisticated retry strategies
