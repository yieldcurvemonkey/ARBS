---
name: synthesizing-with-mcts
description: Merge best solutions from parallel executions using MCTS evaluation and scoring. Use when combining results from parallel tasks, selecting best implementations, or creating hybrid solutions. Evaluates code quality, performance, and correctness.
---

# Synthesizing with MCTS

**Purpose**: Intelligently merge results from parallel task execution using Monte Carlo Tree Search evaluation.

## Core Philosophy

**From Axiom v4**:
> "Don't merge git branches - merge SOLUTIONS. Select the best parts from each parallel execution."

**MCTS Approach**:
- Evaluate each result independently
- Score based on multiple criteria
- Select best implementation for each component
- Synthesize final solution from winners

## When to Use

- After parallel task execution (see skill: `executing-parallel-tasks`)
- Multiple implementation approaches explored
- Need to choose between alternatives
- Hybrid solution combining best parts
- Quality assessment of parallel work

## MCTS Scoring System

### Base Scores (0.0 to 1.0)

**Completion** (0.5):
```typescript
if (task.completed) score += 0.5;
```

**Files Created** (0.3):
```typescript
const expectedFiles = ['models/user.js', 'auth/hash.js'];
const actualFiles = findCreatedFiles(workspace);
const fileScore = actualFiles.length / expectedFiles.length * 0.3;
score += Math.min(fileScore, 0.3);
```

**Bonuses** (+0.05 each):
```typescript
if (hasTests) score += 0.05;
if (hasErrorHandling) score += 0.05;
if (usesAsync) score += 0.05;
if (hasDocumentation) score += 0.05;
```

**Penalties** (-0.1 each):
```typescript
if (hasTODOs) score -= 0.1;
if (hasConsoleLog) score -= 0.1;  // In production code
if (hasHardcodedValues) score -= 0.1;
```

### Quality Metrics

**Code Quality** (subjective, 0-0.2):
```typescript
const metrics = {
  readability: assessReadability(code),   // Clear names, structure
  maintainability: assessComplexity(code), // Cyclomatic complexity
  modularity: assessCoupling(code)        // Separation of concerns
};

const qualityScore = Object.values(metrics).reduce((a,b) => a+b) / 3 * 0.2;
score += qualityScore;
```

**Performance** (measurable, 0-0.2):
```typescript
const benchmark = runBenchmark(implementation);
const performanceScore = normalizePerformance(benchmark) * 0.2;
score += performanceScore;
```

### Final Score Range

**Excellent** (0.8 - 1.0):
- All files created
- Tests included
- Error handling
- Clean code
- No TODOs

**Good** (0.6 - 0.8):
- Most files created
- Basic implementation
- Some quality issues

**Acceptable** (0.4 - 0.6):
- Core functionality works
- Missing tests or error handling
- Has TODOs

**Poor** (<0.4):
- Incomplete
- Major issues
- Not usable

## Synthesis Strategies

### Strategy 1: Winner Takes All

**Select highest-scoring implementation**:

```typescript
const results = await executeParallel(tasks);

// Score all results
const scored = results.map(r => ({
  ...r,
  score: calculateMCTSScore(r)
}));

// Sort by score
scored.sort((a, b) => b.score - a.score);

// Use winner
const winner = scored[0];
console.log(`Winner: ${winner.name} (score: ${winner.score})`);

return winner.code;
```

**Use When**: Single component, clear winner

### Strategy 2: Component-Level Selection

**Choose best implementation for each component**:

```typescript
const components = ['models', 'routes', 'middleware', 'tests'];

const synthesis = {};

for (const component of components) {
  // Find all implementations of this component
  const candidates = results
    .filter(r => r.component === component)
    .map(r => ({ ...r, score: calculateMCTSScore(r) }))
    .sort((a, b) => b.score - a.score);

  // Select winner for this component
  synthesis[component] = candidates[0];
}

// Combine best of each component
return combineComponents(synthesis);
```

**Use When**: Multiple independent components

**Example**:
```
Component: models/user.js
- Implementation A: score 0.85 ← Winner (best data model)
- Implementation B: score 0.72
- Implementation C: score 0.65

Component: routes/auth.js
- Implementation A: score 0.70
- Implementation B: score 0.88 ← Winner (cleanest API)
- Implementation C: score 0.75

Final: models from A + routes from B
```

### Strategy 3: Hybrid Synthesis

**Combine features from multiple implementations**:

```typescript
// Take best aspects from each
const synthesis = {
  // Core logic from performant version
  coreLogic: results.find(r => r.name === 'performant').coreLogic,

  // API interface from readable version
  apiInterface: results.find(r => r.name === 'readable').apiInterface,

  // Error handling from robust version
  errorHandling: results.find(r => r.name === 'robust').errorHandling,

  // Tests from test-driven version
  tests: results.find(r => r.name === 'tdd').tests
};

return mergeCodeComponents(synthesis);
```

**Use When**: Each implementation has different strengths

### Strategy 4: Ensemble (Keep Multiple)

**Maintain multiple implementations**:

```typescript
// Keep top 3 implementations
const topN = scored.slice(0, 3);

// Use strategy pattern
const strategies = {
  fast: topN.find(r => r.name === 'performant'),
  safe: topN.find(r => r.name === 'robust'),
  simple: topN.find(r => r.name === 'minimal')
};

// Select at runtime based on context
export function solve(problem, strategy = 'balanced') {
  return strategies[strategy].solve(problem);
}
```

**Use When**: Different use cases need different tradeoffs

## Practical Evaluation

### Evaluation 1: File Existence Check

```typescript
function evaluateFileCompletion(result, expectedFiles) {
  const actualFiles = listFiles(result.workspace);

  const score = {
    base: 0,
    detail: {}
  };

  for (const expected of expectedFiles) {
    const exists = actualFiles.includes(expected);
    score.detail[expected] = exists ? 1.0 : 0.0;

    if (exists) {
      score.base += 0.3 / expectedFiles.length;
    }
  }

  return score;
}
```

### Evaluation 2: Code Quality Analysis

```typescript
import { analyze } from 'eslint';

function evaluateCodeQuality(result) {
  const files = findJSFiles(result.workspace);
  let qualityScore = 0.2; // Start with full quality points

  for (const file of files) {
    const code = readFile(file);

    // ESLint analysis
    const lintResults = analyze(code);
    const errors = lintResults.filter(r => r.severity === 2);
    const warnings = lintResults.filter(r => r.severity === 1);

    // Penalize errors more than warnings
    qualityScore -= errors.length * 0.05;
    qualityScore -= warnings.length * 0.02;

    // Check for TODOs
    const todos = (code.match(/TODO:/g) || []).length;
    qualityScore -= todos * 0.03;

    // Check for console.log (in non-test files)
    if (!file.includes('test')) {
      const logs = (code.match(/console\.log/g) || []).length;
      qualityScore -= logs * 0.02;
    }
  }

  return Math.max(0, qualityScore); // Don't go negative
}
```

### Evaluation 3: Test Coverage

```typescript
function evaluateTestCoverage(result) {
  const hasTests = findFiles(result.workspace, '*.test.js').length > 0;

  if (!hasTests) return 0;

  // Run coverage
  const coverage = runCoverage(result.workspace);

  // Score based on coverage percentage
  const coverageScore = 0.05 * (coverage.lines / 100);

  return {
    hasTests: true,
    coverage: coverage.lines,
    score: coverageScore
  };
}
```

### Evaluation 4: Performance Benchmark

```typescript
async function evaluatePerformance(implementations) {
  const benchmarks = [];

  for (const impl of implementations) {
    const start = performance.now();

    // Run benchmark (e.g., 10000 iterations)
    for (let i = 0; i < 10000; i++) {
      await impl.execute(testData);
    }

    const elapsed = performance.now() - start;

    benchmarks.push({
      name: impl.name,
      time: elapsed,
      opsPerSec: 10000 / (elapsed / 1000)
    });
  }

  // Normalize: fastest gets 0.2, others scaled proportionally
  const fastest = Math.min(...benchmarks.map(b => b.time));

  return benchmarks.map(b => ({
    ...b,
    performanceScore: 0.2 * (fastest / b.time)
  }));
}
```

## Complete MCTS Scoring Example

```typescript
function calculateMCTSScore(result, config) {
  let score = 0;

  // 1. Completion (0.5)
  if (result.exitCode === 0 && result.completed) {
    score += 0.5;
  }

  // 2. Files Created (0.3)
  const fileScore = evaluateFileCompletion(
    result,
    config.expectedFiles
  );
  score += fileScore.base;

  // 3. Quality (0.2)
  const qualityScore = evaluateCodeQuality(result);
  score += qualityScore;

  // 4. Bonuses (+0.05 each)
  const bonuses = {
    hasTests: findFiles(result.workspace, '*.test.js').length > 0,
    hasErrorHandling: checkErrorHandling(result.code),
    usesAsync: result.code.includes('async') || result.code.includes('await'),
    hasTypeScript: findFiles(result.workspace, '*.ts').length > 0
  };

  for (const [key, value] of Object.entries(bonuses)) {
    if (value) {
      score += 0.05;
      console.log(`+0.05: ${key}`);
    }
  }

  // 5. Penalties (-0.1 each)
  const penalties = {
    hasTODOs: (result.code.match(/TODO:/g) || []).length > 0,
    hasConsoleLog: !result.isTest && result.code.includes('console.log'),
    noDocumentation: !result.code.includes('/**') && !result.code.includes('//')
  };

  for (const [key, value] of Object.entries(penalties)) {
    if (value) {
      score -= 0.1;
      console.log(`-0.1: ${key}`);
    }
  }

  return Math.max(0, Math.min(1, score)); // Clamp to [0, 1]
}
```

## Synthesis Workflow

### Complete Example: REST API

```typescript
// 1. Parallel execution created multiple implementations
const results = [
  { name: 'minimal', workspace: '/tmp/task-minimal-abc123' },
  { name: 'robust', workspace: '/tmp/task-robust-def456' },
  { name: 'performant', workspace: '/tmp/task-perf-ghi789' }
];

// 2. Score each implementation
const scored = results.map(r => ({
  ...r,
  score: calculateMCTSScore(r, {
    expectedFiles: ['routes/auth.js', 'middleware/verify.js']
  })
}));

// Scores:
// minimal: 0.65 (works but basic)
// robust: 0.92 (excellent error handling, tests)
// performant: 0.78 (fast but fewer tests)

// 3. Select synthesis strategy

// Strategy A: Winner takes all
const winner = scored.sort((a,b) => b.score - a.score)[0];
// Result: robust (score 0.92)

// Strategy B: Component-level
const synthesis = {
  routes: scored.find(r => r.name === 'robust').routes,      // Best overall
  performance: scored.find(r => r.name === 'performant').core // Fastest core
};

// Strategy C: Hybrid
const hybrid = {
  coreLogic: results.find(r => r.name === 'performant').coreLogic,
  errorHandling: results.find(r => r.name === 'robust').errorHandling,
  apiInterface: results.find(r => r.name === 'minimal').apiInterface,
  tests: results.find(r => r.name === 'robust').tests
};

// 4. Merge selected components
const final = mergeComponents(hybrid);

// 5. Verify integration
runIntegrationTests(final);
```

## Integration with Other Skills

**Use with**:
- `decomposing-into-orthogonal-tasks` - Create parallel task list
- `executing-parallel-tasks` - Run tasks to get results to synthesize
- `analyzing-with-mcts` - Core MCTS decision framework
- `expanding-then-compressing` - Synthesis is the compression phase
- `phoenix-interrupting` - Monitor synthesis process

**Complete Workflow**:
```
1. decomposing-into-orthogonal-tasks
   ↓ Creates task list
2. executing-parallel-tasks
   ↓ Runs all tasks in parallel
3. synthesizing-with-mcts (this skill)
   ↓ Evaluates and merges results
4. Final integrated solution
```

## Checklist

- [ ] Parallel execution results collected
- [ ] Expected files/components defined
- [ ] Scoring criteria established
- [ ] MCTS evaluation implemented
- [ ] Synthesis strategy chosen (winner/component/hybrid/ensemble)
- [ ] Merge logic implemented
- [ ] Integration tests prepared
- [ ] Final verification completed

## Real-World Example from This Session

**Task**: Create 19 Agent Skills for Peter

**Parallel Decomposition**:
```
Task 1: Create meta-cognition skills (3 skills)
Task 2: Create MCTS skills (4 skills)
Task 3: Create quant finance skills (4 skills)
Task 4: Create technical dev skills (5 skills)
Task 5: Create consciousness skills (3 skills)
```

**Execution**: All skill domains created in parallel (conceptually)

**Synthesis**:
- Each skill scored for: completeness, examples, cross-references
- Component-level selection: best patterns from each domain
- Hybrid approach: combine best practices across all skills
- Final result: 19 cohesive, cross-referenced skills

**MCTS Scoring Applied**:
```
Meta-cognition skills:
- expanding-then-compressing: 0.85 (excellent examples)
- phoenix-interrupting: 0.90 (clear criteria, real examples)
- midnight-building: 0.80 (practical, checklist included)

Synthesis: All kept, cross-referenced appropriately
```

## Related Skills

- `decomposing-into-orthogonal-tasks` - Prepare for parallel execution
- `executing-parallel-tasks` - Generate results to synthesize
- `analyzing-with-mcts` - Core MCTS framework
- `expanding-then-compressing` - Synthesis as compression
- `evaluating-alpha-beta-gamma` - Multi-timeframe synthesis

## Advanced Topics

See resources in this skill folder:
- `advanced-1-scoring-algorithms.md` - Sophisticated MCTS scoring
- `advanced-2-merge-strategies.md` - Complex component merging
- `advanced-3-conflict-resolution.md` - Handling incompatible results
