---
argument-hint: "<agent/system to review>"
---

@meta-reviewer

Perform meta-cognitive review of:

{{arg}}

Analyze from multiple levels:
1. **Context Awareness**: What context exists at runtime?
2. **Constraint Appropriateness**: Too rigid or too loose?
3. **Generalization**: Works across languages/frameworks/domains?
4. **Implicit Knowledge**: What assumptions are baked in?
5. **Meta Patterns**: System-wide patterns and consistency

Focus on:
- Hardcoded values that should be parameters
- Over-constraining instructions
- Missing context discovery
- Language/framework specificity
- Adaptability across scenarios

Provide:
- 🔴 Critical fixes (must address)
- 🟡 Important improvements (should address)
- 🔵 Enhancements (nice to have)
- ✅ Strengths to preserve
