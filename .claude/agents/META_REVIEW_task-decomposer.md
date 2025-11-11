# Meta-Review: task-decomposer Agent

## Executive Summary

The task-decomposer agent has excellent structure and principles but suffers from **over-specification** in examples that limits generalizability across languages, frameworks, and project types.

## Context Awareness (Level 1)

### Issue: Hardcoded File Paths
**Location**: Pattern examples (lines 61-77)
**Problem**: Examples show specific paths like `models/user.js`, `auth/password.js`
**Impact**: Won't generalize to:
- Python projects (`models/user.py`)
- Go projects (`models/user.go`, package structure)
- Different conventions (`model/user.ts`, `entities/user.ts`)
**Suggestion**: Use placeholders like `{models_dir}/user.{ext}` or describe conceptually

### Issue: Language Assumption
**Location**: All examples use `.js` extension
**Problem**: Assumes JavaScript/TypeScript project
**Impact**: User must mentally translate for Python, Go, Rust, Java projects
**Suggestion**: Provide one language-agnostic pattern, then brief language-specific notes

### Issue: Technology Stack Hardcoded
**Location**: Examples mention JWT, bcrypt, React, REST API
**Problem**: Specific technology choices embedded in decomposition examples
**Impact**: User doing GraphQL API, gRPC service, or CLI tool must adapt significantly
**Suggestion**: Use generic terms like "authentication library", "UI component", "API endpoint"

## Constraint Appropriateness (Level 2)

### Good Constraints ✅
- **5-10 minute tasks**: Appropriate time-boxing
- **Orthogonal**: Necessary for parallelism
- **File creation as metric**: Concrete, measurable
- **No TODOs**: Forces completion

### Over-Constraints ❌
- **Specific file structures**: `models/`, `routes/`, `middleware/`
  - Problem: Assumes MVC-style web architecture
  - Alternative: "Create separate files for data layer, logic layer, API layer"

- **Specific patterns**: Repository pattern, MVC layers
  - Problem: May not match project's architecture
  - Alternative: "Follow project's existing architectural patterns"

### Missing Constraints ⚠️
- **Context discovery**: Should instruct agent to ask about:
  - Project language/framework
  - Existing file structure conventions
  - Team's architectural patterns
  - Testing framework in use

## Generalization Gaps (Level 3)

### Language Specificity
**Problem**: All examples use JavaScript
**Fails for**: Python, Go, Rust, Java, C++, etc.
**Suggestion**:

```markdown
### Language-Agnostic Pattern Structure:
{component_type}/{feature}.{lang_ext}
- data_models/user - Data structures only
- business_logic/auth - Core logic, no I/O
- api_layer/routes - Request handlers
- tests/unit - Unit tests with mocks

### Language-Specific Notes:
- **JavaScript/TypeScript**: models/, routes/, middleware/
- **Python**: models.py, views.py, services.py or package structure
- **Go**: user.go in appropriate package, handlers/, services/
- **Rust**: mod.rs structure, separate concerns by module
```

### Framework Specificity
**Problem**: Examples assume Express.js web framework
**Fails for**: FastAPI, Flask, NestJS, Gin, Actix, etc.
**Suggestion**:

```markdown
Example: "Build {API_STYLE} with authentication"
- Define data structures (schema/model files)
- Implement auth functions (hashing, verification)
- Create API endpoints (using project's web framework)
- Add authentication middleware (framework-specific)
- Write tests (using project's test framework)
```

### Domain Specificity
**Problem**: Examples focused on web APIs
**Fails for**: CLI tools, data pipelines, system utilities, libraries
**Suggestion**: Add diverse examples:
- **Web API**: Current examples (adapted)
- **CLI Tool**: Commands, parsers, output formatters
- **Data Pipeline**: Extract, transform, load, validate
- **Library**: Public API, internal utilities, data structures

## Implicit Knowledge (Level 4)

### Assumption: Web Development Knowledge
**Unstated Requirement**: User understands REST APIs, MVC architecture, JWT, bcrypt
**Problem**: User building non-web system must translate mental model
**Suggestion**: Add conceptual explanations or generic equivalents

### Assumption: Testing Approach
**Unstated Requirement**: Unit tests with mocks
**Problem**: Project may use integration tests, property tests, or no tests
**Suggestion**: Make testing optional/discover project approach

### Assumption: File System Organization
**Unstated Requirement**: Certain directory structure
**Problem**: Projects organize differently (flat, monorepo, feature-based)
**Suggestion**: Instruct agent to discover existing organization first

### Assumption: Build/Development Environment
**Unstated Requirement**: npm, node, jest
**Problem**: Python uses pip/uv, Go uses go modules, Rust uses cargo
**Suggestion**: Generic references to "project's build tool", "project's test runner"

## System Patterns (Level 5)

### Pattern: Example-Driven Instruction
**Observation**: Heavy reliance on specific examples
**Evaluation**: Good for clarity, bad for generalization
**Recommendation**: Balance with abstract principles

Pattern to follow:
```markdown
1. **Principle** (abstract, universal)
2. **Pattern** (general approach, placeholders)
3. **Examples** (diverse, multiple languages/domains)
4. **Discovery Questions** (what to ask about context)
```

### Pattern: Technology Neutrality
**Observation**: Most agents assume JavaScript/TypeScript
**Evaluation**: Limits utility across Peter's polyglot work
**Recommendation**: System-wide pass for generalization

## Priority Fixes

### 🔴 Critical (Must Fix)

1. **Replace hardcoded paths with placeholders**
   - Current: `models/user.js`
   - Better: `{data_models_dir}/{entity}.{ext}`
   - Best: "Create data model file in project's models location"

2. **Remove technology-specific examples**
   - Current: "JWT verification, bcrypt hashing"
   - Better: "Token verification, password hashing"
   - Best: "Use project's authentication approach"

3. **Add context discovery step**
   ```markdown
   ### Step 0: Discover Project Context
   Before decomposing, identify:
   - Project language and framework
   - Existing file organization patterns
   - Testing approach and frameworks
   - Team conventions and style guides
   ```

### 🟡 Important (Should Fix)

4. **Provide language-agnostic patterns first**
   - Show conceptual decomposition
   - Then provide language-specific adaptations

5. **Add diverse domain examples**
   - Web API (current)
   - CLI tool (new)
   - Data pipeline (new)
   - System library (new)

6. **Make assumptions explicit**
   - List what knowledge is assumed
   - Provide fallbacks for unknown contexts

### 🔵 Enhancement (Nice to Have)

7. **Add meta-prompts**
   ```markdown
   If project context is unclear, ask:
   - "What language/framework is this project using?"
   - "What file organization does this project follow?"
   - "How does this project typically structure {component type}?"
   ```

8. **Add anti-pattern detection**
   - Detect when decomposition assumes wrong context
   - Self-correct when examples don't match project type

## Strengths (Keep These)

✅ **Clear principles**: 5-10 min, orthogonal, concrete
✅ **Good structure**: Step-by-step process
✅ **Measurable success**: File creation metric
✅ **Pattern diversity**: By component, by layer, by approach
✅ **Reserve task concept**: Excellent for integration
✅ **Anti-patterns section**: Helps avoid common mistakes

## Recommended Revisions

### Example: Improved Pattern 1

**Before**:
```markdown
Example: "Build REST API with authentication"
- models/user.js - Schema only
- auth/password.js - Hash/verify functions
- routes/auth.js - Route structure
```

**After**:
```markdown
Example: "Build {API_TYPE} with authentication"

**Conceptual Decomposition**:
1. Data structure file - User entity definition
2. Auth utility file - Credential verification logic
3. API endpoint file - Authentication routes
4. Test file - Unit tests for each component

**Adapts to context**:
- REST API (Express/FastAPI): routes, controllers, middleware
- GraphQL API (Apollo/Strawberry): resolvers, schema, directives
- gRPC Service (Go/Rust): service impl, proto messages, interceptors
- CLI Tool: auth command, config storage, credential manager

**Implementation** (discovered from project):
- Use project's file organization pattern
- Use project's authentication approach
- Use project's naming conventions
```

## Meta-Level Insights

### Insight 1: Context Discovery is Missing
Agents need a discovery phase before execution:
```markdown
Before decomposing, I will:
1. Identify project language/framework
2. Examine existing file structure
3. Note team conventions
4. Detect architectural patterns

This ensures my decomposition matches project context.
```

### Insight 2: Examples Need Diversity
One JavaScript example doesn't serve polyglot development:
- Provide 1 language-agnostic pattern
- Provide 2-3 brief language-specific adaptations
- Focus on concepts, not syntax

### Insight 3: Generalization Enables Specialization
By making agents more generic:
- They ask clarifying questions
- They discover context
- They adapt to project
- They learn patterns

More generic = more powerful, not less.

## System-Wide Recommendations

Apply these principles to all agents:
1. **Context discovery before action**
2. **Placeholders instead of hardcoded values**
3. **Language-agnostic patterns first**
4. **Diverse examples (web, CLI, data, systems)**
5. **Explicit fallbacks for unknown contexts**
6. **Meta-prompts for clarification**

## Conclusion

Task-decomposer has strong principles but execution-level examples are over-specified. The agent will be significantly more useful with:
1. Generic patterns with placeholders
2. Context discovery step added
3. Diverse domain examples
4. Language-agnostic conceptual decomposition

**Priority**: Fix critical items (context discovery, generic patterns) before general use.
