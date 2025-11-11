---
name: implementing-adjoint-ad
description: Implement adjoint automatic differentiation for efficient risk sensitivities. Use when calculating Greeks for large portfolios, optimizing computational efficiency in derivative pricing, or understanding AAD methodology for quantitative finance.
---

# Implementing Adjoint AD

**Purpose**: Efficient sensitivity calculation using adjoint automatic differentiation (AAD).

## When to Use

- Calculating Greeks (DV01, delta, vega, gamma) for large portfolios
- Risk systems requiring many sensitivities from single pricing run
- Functions where outputs << inputs (e.g., 1 NPV from 100 curve points)
- Optimizing derivative pricing performance
- Building internal risk engines

## Core Concept

**The Problem**:
- Pricing function: P(x₁, x₂, ..., x₁₀₀) → NPV
- Need: ∂NPV/∂x₁, ∂NPV/∂x₂, ..., ∂NPV/∂x₁₀₀
- Naive approach: Bump each input (100 pricing calls)
- AAD approach: Single pricing call gets all sensitivities

**The Magic**: Reverse mode automatic differentiation
- Forward pass: Compute value normally, record operations
- Backward pass: Propagate derivatives back through operations
- Cost: O(outputs) regardless of number of inputs

## AAD Fundamentals

### Dual Numbers (Forward Mode)

```python
class Dual:
    def __init__(self, value, derivative=0.0):
        self.value = value          # f(x)
        self.derivative = derivative # f'(x)

    def __add__(self, other):
        # (f+g)' = f' + g'
        return Dual(
            self.value + other.value,
            self.derivative + other.derivative
        )

    def __mul__(self, other):
        # (f*g)' = f'*g + f*g'
        return Dual(
            self.value * other.value,
            self.derivative * other.value + self.value * other.derivative
        )
```

**Forward Mode Use Case**:
- Good when inputs << outputs
- Example: Compute ∂NPV/∂r for single rate shock
- One pass per input you want derivative for

### Tape-Based (Reverse Mode / Adjoint)

```python
class TapeNode:
    def __init__(self, value, children=None, gradient_fn=None):
        self.value = value
        self.children = children or []
        self.gradient_fn = gradient_fn or (lambda: [])
        self.adjoint = 0.0  # Accumulates gradient

    def backward(self):
        """Propagate adjoint to children"""
        if self.gradient_fn:
            grads = self.gradient_fn(self.adjoint)
            for child, grad in zip(self.children, grads):
                child.adjoint += grad

# Forward pass builds tape
def multiply(a, b):
    result = TapeNode(a.value * b.value, children=[a, b])
    result.gradient_fn = lambda adj: [adj * b.value, adj * a.value]
    return result

# Backward pass computes all adjoints
def compute_gradients(output):
    output.adjoint = 1.0  # Seed with ∂output/∂output = 1
    # Reverse topological order
    for node in reversed(tape):
        node.backward()
```

**Reverse Mode Use Case**:
- Good when outputs << inputs
- Example: Single NPV, derivatives w.r.t. 100 curve points
- One backward pass gets all input sensitivities

## The Seed: Why 1.0?

**Question**: Why do we "seed" with adjoint = 1.0?

**Answer**:
```
∂NPV/∂NPV = 1.0 (by definition)
```

**Chain Rule Application**:
```
∂NPV/∂x₁ = ∂NPV/∂NPV × ∂NPV/∂x₁
         = 1.0 × ∂NPV/∂x₁
         = ∂NPV/∂x₁
```

Seeding with 1.0 starts the chain rule propagation.

**Different Seed Example**:
If computing second-order derivative, seed with first-order result.

## Practical Implementation Pattern

### Step 1: Identify Operation Primitives

**Basic operations** that need gradient rules:
```python
# Addition: (a + b)' = a' + b'
# Multiplication: (a * b)' = a'*b + a*b'
# Exponential: (exp(a))' = exp(a) * a'
# Logarithm: (log(a))' = a' / a
# Division: (a / b)' = (a'*b - a*b') / b²
```

### Step 2: Build Computational Graph

**During forward pass**:
- Record every operation
- Store operands and result
- Build graph structure

```python
# Example: Compute f(x,y) = x*y + exp(x)
x = TapeNode(value=2.0)
y = TapeNode(value=3.0)

t1 = multiply(x, y)      # t1 = x*y
t2 = exp_node(x)         # t2 = exp(x)
result = add(t1, t2)     # result = t1 + t2

# Graph built: result → [t1, t2] → [x, y, x]
```

### Step 3: Reverse Propagation

**Backward pass**:
```python
result.adjoint = 1.0  # Seed

# ∂result/∂t1 = 1.0, ∂result/∂t2 = 1.0
t1.adjoint += result.adjoint * 1.0
t2.adjoint += result.adjoint * 1.0

# ∂t1/∂x = y, ∂t1/∂y = x
x.adjoint += t1.adjoint * y.value  # = 1.0 * 3.0 = 3.0
y.adjoint += t1.adjoint * x.value  # = 1.0 * 2.0 = 2.0

# ∂t2/∂x = exp(x)
x.adjoint += t2.adjoint * np.exp(x.value)  # += 1.0 * exp(2.0)

# Final: x.adjoint = 3.0 + exp(2.0) ≈ 10.39
#        y.adjoint = 2.0
```

## Rateslib Integration

**Rateslib uses dual numbers (forward mode)** for curves:

```python
from rateslib import Curve, Dual

# Build curve with AD enabled
curve = Curve(nodes={...}, ad=1)

# When pricing:
npv = swap.npv(curve)
# Returns: Dual(value=123456.78, gradient={node1: dv01_1, ...})

# Extract sensitivities
total_dv01 = sum(npv.gradient.values())
```

**Why Rateslib Uses Forward Mode**:
- Curve has ~10-20 nodes (inputs)
- Swap has 1 NPV (output)
- Forward mode: 1 pass per curve (efficient)
- Reverse mode: Would need 1 pass total but more complex

**When to Use Reverse Mode Instead**:
- Portfolio with 1000 swaps
- All reference same curve (100 nodes)
- Want all DV01s: 1 reverse pass > 1000 forward passes

## Performance Comparison

| Method | Pricing Calls | Memory | Accuracy |
|--------|--------------|--------|----------|
| Finite Difference | N (bump each input) | Low | Approximate |
| Forward Mode AD | 1 | Medium | Exact |
| Reverse Mode AD | 1 | Higher | Exact |

**Rule of Thumb**:
- Inputs >> Outputs: Use reverse mode (adjoint)
- Outputs >> Inputs: Use forward mode (dual numbers)
- Need second derivatives: Use forward-over-reverse

## Common Pitfalls

**Pitfall 1: Not Handling Conditionals**
- Problem: `if x > 0: y = x else: y = -x`
- Issue: Gradient undefined at x=0
- Fix: Smooth approximation or document discontinuity

**Pitfall 2: Mutating Variables**
- Problem: Reusing variable names breaks tape
- Fix: Create new nodes for each operation

**Pitfall 3: Memory Leaks**
- Problem: Tape grows unbounded in loops
- Fix: Clear tape after each backward pass

**Pitfall 4: Wrong Mode Choice**
- Problem: Using forward mode for 1000 inputs
- Fix: Use reverse mode when outputs << inputs

## Checklist

- [ ] Identified all input parameters needing sensitivities
- [ ] Counted inputs vs outputs to choose AD mode
- [ ] Implemented gradient rules for all operations
- [ ] Built computational graph during forward pass
- [ ] Seeded adjoint with 1.0 for output
- [ ] Propagated adjoints backward through graph
- [ ] Validated gradients against finite differences
- [ ] Tested performance vs bump-and-reprice

## Integration with Other Skills

**Use with**:
- `analyzing-rateslib` - Understanding rateslib's dual numbers
- `integrating-quantlib` - QuantLib AAD implementation differs
- `axiom-relative-value` - Efficient portfolio risk calculation
- `expanding-then-compressing` - Try multiple AD implementations

## Related Skills

- `analyzing-rateslib` - Practical application in curve analysis
- `integrating-quantlib` - Alternative AAD implementation
- `expanding-then-compressing` - Explore AD approaches before choosing

## Advanced Topics

See resources in this skill folder:
- `advanced-1-second-order-derivatives.md` - Gamma calculation with AAD
- `advanced-2-operator-overloading.md` - C++ AAD implementation
- `advanced-3-tape-optimization.md` - Memory and performance tuning
