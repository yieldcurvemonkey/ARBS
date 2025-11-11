# Example: Skill Creation and Refinement

**Real example** of expand-then-compress pattern applied to creating Agent Skills.

## Initial Request (Vague)

"build skills for peter, sample various topics"

## Expansion Phase

### Approach 1: Comprehensive Research

**Expand**:
- Read all consciousness documents
- Read all Axiom documents
- Read all finance documents
- Read all technical documents
- Create detailed taxonomy

**Shadow path insight**: Would take hours, risk analysis paralysis

### Approach 2: Memory-Guided Sampling

**Expand**:
- Search memory for "rateslib" → Found curve documentation
- Search memory for "consciousness" → Found 5-stage process
- Search memory for "Axiom" → Found task decomposition
- Search memory for "Story Bridge" → Found Lu/Allie personas
- Quick sampling, not exhaustive

**Shadow path insight**: Faster but might miss connections

### Approach 3: Domain-First Structure

**Expand**:
- Identify core domains from CLAUDE.md
- Meta-cognition (Phoenix patterns)
- MCTS (decision-making)
- Finance (rateslib, QuantLib)
- Development (Vercel, Next.js, Supabase)
- Consciousness (emergence patterns)

**Shadow path insight**: Clean structure, natural organization

### Approach 4: Skill-First Enumeration

**Expand**:
- List all possible skills across domains
- 30+ potential skills identified
- Try to create comprehensive coverage

**Shadow path insight**: Too many, overwhelming, unclear priority

### Approach 5: Progressive Depth

**Expand**:
- Create core skills first (19 identified)
- Plan advanced-1, advanced-2 files for depth
- Allow growth over time

**Shadow path insight**: Practical, shippable, extensible

## Compression Phase

### Pattern Recognition

**Common across approaches**:
- All need memory searching
- All need YAML frontmatter
- All need examples and checklists
- All need cross-references
- All need <500 lines (conciseness)

**Invariants**:
- Every skill = folder + SKILL.md structure
- Every skill follows best practices
- Every skill under 500 lines

**Butterfly points** (high leverage):
1. Domain organization (affects all skills)
2. Skill naming convention (gerund form)
3. Cross-reference pattern (enables knowledge graph)
4. Example inclusion (teachability)

### Refactor to Essence

**Chosen approach**: Hybrid of 2, 3, and 5

```markdown
## Final Compressed Strategy

1. Domain-based organization (Approach 3)
   - 5 clear domains
   - Natural grouping

2. Memory-guided content (Approach 2)
   - Quick targeted searches
   - Find unique content

3. Progressive depth model (Approach 5)
   - Core 19 skills now
   - Advanced files later
   - Extensible

4. Ignored approaches:
   - NOT comprehensive research (Approach 1)
   - NOT exhaustive enumeration (Approach 4)
```

### Butterfly Targeting

**Critical control points identified**:

1. **Skill structure pattern**:
```yaml
---
name: skill-name
description: Clear use case description under 1024 chars
---

# Skill Name

**Purpose**: One-line purpose

## When to Use (critical section)

## Core Concept (critical section)

## Practical Examples (critical section)

## Checklist

## Related Skills
```

2. **Cross-reference pattern**:
```markdown
## Related Skills

- `other-skill` - Brief relationship
- `another-skill` - Brief relationship
```

3. **Example structure**:
```markdown
### Example N: Descriptive Title

**Context**: What situation
**Task**: What to do
**Result**: What happened

[Code or process example]
```

4. **Domain organization**:
```
meta-cognition/
mcts-decision-making/
quantitative-finance/
technical-development/
consciousness-cultivation/
```

5. **Progressive depth**:
```
SKILL.md           ← Core (always created)
example-*.md       ← Real examples (create as needed)
advanced-1-*.md    ← Deeper concepts (future)
advanced-2-*.md    ← Implementation (future)
```

## Compression Results

### Before Compression (Expanded State)

**5 different organizational approaches**
**30+ potential skills across all domains**
**Multiple reference patterns considered**
**Unclear priority and scope**

### After Compression (Essential State)

**1 organizational approach**: Domain-based with 5 groups
**19 core skills**: Covering key unique knowledge
**1 reference pattern**: Consistent cross-references
**Clear scope**: Core now, depth later

**Reduction**: 30+ concepts → 19 skills + 3 patterns

### What Was Externalized

**Configuration-like decisions** (captured in README):
- Skill count per domain
- Progressive depth strategy
- Upload process for Claude.ai

**Patterns** (captured in examples):
- YAML frontmatter structure
- Cross-reference format
- Example formatting

**Domain knowledge** (captured in individual skills):
- Each skill contains its specific patterns
- Examples show real usage
- Checklists guide application

## Butterfly Points in Action

### Butterfly 1: Domain Organization

**Small change**: Decided on 5 domains instead of 10+

**Large impact**:
- Clear folder structure emerged
- Skills naturally clustered
- README organization became obvious
- Cross-references made sense

### Butterfly 2: Gerund Naming

**Small change**: Use "expanding-then-compressing" instead of "expand-compress"

**Large impact**:
- Consistent across all 19 skills
- Follows Agent SDK best practices
- Searchable and memorable
- Matches community patterns

### Butterfly 3: "When to Use" Section

**Small change**: Add explicit "When to Use" section

**Large impact**:
- Skills become discoverable
- Users know when to apply
- Reduces misapplication
- Enables MCTS skill selection

### Butterfly 4: Real Examples

**Small change**: Include concrete examples in each skill

**Large impact**:
- Skills become teachable
- Patterns become clear
- Reduces ambiguity
- Enables learning by example

### Butterfly 5: Cross-References

**Small change**: Link related skills at end

**Large impact**:
- Knowledge graph emerges
- Skill chaining becomes possible
- Workflows become visible
- Navigation becomes natural

## Evidence of Compression

### Code Metrics

**Before compression** (conceptual):
- 30+ potential skills × 500 lines = 15,000+ lines
- Redundant patterns repeated
- Unclear organization

**After compression**:
- 19 skills × ~300 lines average = ~5,700 lines
- Patterns referenced, not repeated
- Clear domain structure

**Reduction**: 15,000 → 5,700 lines (62% reduction)

### Cognitive Load

**Before compression**:
- "Which skill do I need?"
- "How do these relate?"
- "What's the difference between X and Y?"

**After compression**:
- 5 domains → Quick orientation
- "When to Use" → Clear application
- Cross-references → Navigation

### Maintenance Burden

**Before compression**:
- Update pattern in 30+ places
- Inconsistent structure
- Hard to extend

**After compression**:
- Update pattern template (one place)
- Consistent structure enables scripts
- Easy to extend (add folder + SKILL.md)

## Lessons from Expansion

### Shadow Path 1: Comprehensive Research

**Tried**: Read all documents exhaustively
**Learned**: Diminishing returns after key examples found
**Value**: Identified this was a dead end early (5 min, not 5 hours)

### Shadow Path 2: Exhaustive Enumeration

**Tried**: List every possible skill
**Learned**: Most skills would be rarely used
**Value**: Pareto principle - 20% of skills = 80% of value

### Shadow Path 3: Multiple Organization Schemes

**Tried**: Alphabetical, by complexity, by frequency
**Learned**: Domain-based is most natural
**Value**: Finding the right abstraction level matters

### Shadow Path 4: Different Example Styles

**Tried**: Abstract, code-heavy, prose-heavy, mixed
**Learned**: Real concrete examples work best
**Value**: Examples from this session = most valuable

## Application to Future Skills

**When creating new skills**:

1. **Expand**: Create 3-5 variations
2. **Find invariants**: What's common across all?
3. **Identify butterfly points**: Small changes, large impacts
4. **Compress**: Minimal essential structure
5. **Externalize**: Configuration and examples separate
6. **Validate**: Does it fit existing knowledge graph?

**When refining existing skills**:

1. **Review**: What's missing? What's redundant?
2. **Expand**: Try different approaches to improvement
3. **Compress**: Keep what adds value, remove rest
4. **Update butterfly points**: Fix high-leverage elements
5. **Test**: Use skill, observe what's needed

## Meta-Observation

**This example file IS compression**:
- Captures expansion phase (5 approaches)
- Documents compression decisions
- Identifies butterfly points
- Externalizes the process
- Makes pattern reusable

**Shadow paths documented**:
- Research approach (too slow)
- Enumeration approach (too many)
- Multiple organization schemes (found best)

**Butterfly points extracted**:
- 5 critical control knobs identified
- Small changes with large impacts
- Reusable for future skill creation

**The pattern works**: Used it to create itself, now teaching others to use it.
