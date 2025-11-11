# PDF Processing Plan: Building the ARBS Mathematical Reference Manual

**Created**: 2025-11-11
**Purpose**: Extract and structure mathematical foundations from research PDFs into comprehensive reference documentation

---

## Objectives

1. **Inventory** all existing and needed PDFs
2. **Download** relevant arXiv papers and research documents
3. **Process** PDFs systematically using Claude's PDF reading capabilities
4. **Structure** extracted content into domain-specific markdown reference manuals
5. **Cross-reference** mathematical concepts with ARBS implementations

---

## Current PDF Inventory

### Existing PDFs (1)

| File | Size | Location | Status |
|------|------|----------|--------|
| **Grinold-Kahn Active Portfolio Management (1999)** | 6.1 MB | `docs/books/Grinold-Kahn-Active-Portfolio-Management-1999.pdf` | ✅ Downloaded, Reference created |

**Coverage**: 621 pages covering:
- Fundamental Law of Active Management (IR = IC × √N)
- Alpha generation and scaling
- Covariance estimation and shrinkage
- Mean-variance optimization
- Performance analysis (IC, Sharpe, Information Ratio)

---

## PDFs to Download

### Priority 1: Core Portfolio Optimization (6 papers)

**Covariance Estimation & Shrinkage**:

1. **Ledoit-Wolf Shrinkage with Unknown Mean** (2023)
   - arXiv: 2304.07045
   - URL: https://arxiv.org/pdf/2304.07045
   - Relevance: Direct implementation in `Risk/Covariance/LedoitWolfShrinkage.py`
   - Extract: Shrinkage formula, target selection, asymptotic properties

2. **Shrinkage Estimation with High Frequency Data** (2016)
   - arXiv: 1611.06753
   - URL: https://arxiv.org/pdf/1611.06753
   - Relevance: Time-series covariance for rates data
   - Extract: High-frequency adjustments, autocorrelation handling

3. **Covariance Matrix Estimation under Total Positivity** (2019)
   - arXiv: 1909.04222
   - URL: https://arxiv.org/pdf/1909.04222
   - Relevance: Alternative covariance estimation method
   - Extract: Total positivity constraints, portfolio selection applications

**Transaction Costs & Optimization**:

4. **Portfolio Optimization with Quadratic Transaction Costs** (2020)
   - arXiv: 2001.01612
   - URL: https://arxiv.org/pdf/2001.01612
   - Relevance: Future ARBS enhancement for realistic backtests
   - Extract: Quadratic cost formulation, optimal rebalancing

5. **Cost-aware Portfolios in Large Universe** (Dec 2024)
   - arXiv: 2412.11575
   - URL: https://arxiv.org/pdf/2412.11575
   - Relevance: Scaling optimization to many assets
   - Extract: Well-conditioned covariance, transaction cost modeling

6. **Fast Successive QP for Mean-Variance** (2022)
   - arXiv: 2212.06983
   - URL: https://arxiv.org/pdf/2212.06983
   - Relevance: Computational efficiency for optimizer
   - Extract: Algorithm improvements, numerical stability

### Priority 2: Alpha Generation & Signal Processing (4 papers)

7. **AlphaForge: Mining Formulaic Alpha Factors** (June 2024)
   - arXiv: 2406.18394
   - URL: https://arxiv.org/pdf/2406.18394
   - Relevance: Signal combination methodology (IC, ICIR)
   - Extract: Factor evaluation metrics, combination strategies

8. **101 Formulaic Alphas** (Kakushadze, 2016)
   - arXiv: 1601.00991
   - URL: https://arxiv.org/pdf/1601.00991
   - Relevance: Alpha signal examples for rates/futures
   - Extract: Formulaic patterns, carry/momentum/value signals

9. **AlphaAgent: LLM-Driven Alpha Mining** (Feb 2025)
   - arXiv: 2502.16789
   - URL: https://arxiv.org/pdf/2502.16789
   - Relevance: Alpha decay, overfitting prevention
   - Extract: Regularization techniques, factor crowding

10. **Automate Strategy Finding with LLM** (Sept 2024)
    - arXiv: 2409.06289
    - URL: https://arxiv.org/pdf/2409.06289
    - Relevance: Information Coefficient calculation and interpretation
    - Extract: IC metrics, strategy evaluation

### Priority 3: Risk Modeling & Performance (3 papers)

11. **Deep Declarative Risk Budgeting Portfolios** (April 2025)
    - arXiv: 2504.19980
    - URL: https://arxiv.org/pdf/2504.19980
    - Relevance: Alternative to mean-variance (risk parity)
    - Extract: Risk budgeting formulas, comparison with MVO

12. **Inverse Portfolio Optimization** (Oct 2024)
    - arXiv: 2510.06986
    - URL: https://arxiv.org/pdf/2510.06986
    - Relevance: Understanding risk aversion parameters
    - Extract: Risk aversion calibration, parameter recovery

13. **The Exploratory Multi-Asset** (May 2025)
    - arXiv: 2505.07537
    - URL: https://arxiv.org/pdf/2505.07537
    - Relevance: Multi-asset portfolio context
    - Extract: Asset allocation, cross-asset risk modeling

### Priority 4: Advanced Topics (3 papers)

14. **Robust Covariance and CVaR Constraints** (June 2024)
    - arXiv: 2406.00610
    - URL: https://arxiv.org/pdf/2406.00610
    - Relevance: Risk constraints beyond variance
    - Extract: CVaR formulation, robust optimization

15. **Decision-Focused Learning for GMV Portfolio** (August 2025)
    - arXiv: 2508.10776
    - URL: https://arxiv.org/pdf/2508.10776
    - Relevance: Covariance estimation for specific objectives
    - Extract: Objective-aligned estimation, decision-focused learning

16. **Optimal Data Splitting for Cross-Validation** (Sept 2025)
    - arXiv: 2503.15186
    - URL: https://arxiv.org/pdf/2503.15186
    - Relevance: Backtesting methodology, overfitting prevention
    - Extract: Cross-validation strategies, holdout methods

---

## PDF Processing Methodology

### Phase 1: Download and Organize (2 hours)

**Tasks**:
1. Download all 16 PDFs from arXiv
2. Verify downloads (file size, readability)
3. Organize into subdirectories:
   ```
   docs/books/
   └── Grinold-Kahn-Active-Portfolio-Management-1999.pdf

   docs/papers/
   ├── covariance-estimation/
   │   ├── ledoit-wolf-unknown-mean-2023.pdf
   │   ├── shrinkage-high-frequency-2016.pdf
   │   └── total-positivity-2019.pdf
   ├── transaction-costs/
   │   ├── quadratic-costs-2020.pdf
   │   ├── cost-aware-large-universe-2024.pdf
   │   └── fast-qp-2022.pdf
   ├── alpha-generation/
   │   ├── alphaforge-2024.pdf
   │   ├── 101-alphas-2016.pdf
   │   ├── alphaagent-2025.pdf
   │   └── llm-strategy-finding-2024.pdf
   ├── risk-modeling/
   │   ├── risk-budgeting-2025.pdf
   │   ├── inverse-optimization-2024.pdf
   │   └── multi-asset-2025.pdf
   └── advanced/
       ├── robust-cvar-2024.pdf
       ├── decision-focused-learning-2025.pdf
       └── optimal-cross-validation-2025.pdf
   ```
4. Create `.gitignore` entry if PDFs are too large for repo

### Phase 2: Content Extraction (Agent-Driven, ~8 hours)

**Process per PDF**:
1. **Agent reads PDF** using Read tool (supports PDF natively)
2. **Extract key sections**:
   - Abstract and introduction
   - Mathematical formulations (equations, theorems, algorithms)
   - Empirical results (performance metrics, comparisons)
   - Code snippets or pseudocode
   - Figures and tables (descriptions, not images)
3. **Structure into markdown**:
   - H1: Paper title
   - H2: Sections from paper
   - H3: Subsections
   - Code blocks for equations (LaTeX or pseudocode)
   - Tables for results
4. **Cross-reference ARBS code**:
   - Link formulas to implementations
   - Note differences or simplifications
   - Identify gaps (not yet implemented)

**Agent Workflow**:
```python
# For each PDF:
# 1. Read PDF
content = Read(pdf_path)

# 2. Extract to structured markdown
markdown = agent.process(
    prompt=f"""
    Extract mathematical content from this PDF:

    Focus on:
    1. Key equations and formulas (use LaTeX in code blocks)
    2. Algorithms (pseudocode in code blocks)
    3. Empirical results (tables)
    4. Cross-reference to ARBS components

    Create markdown with:
    - H1: Paper title and citation
    - H2: Main sections
    - H3: Subsections
    - Code blocks: ``` for LaTeX equations
    - Tables: markdown tables
    - ARBS cross-refs: file paths where relevant

    Paper content:
    {content}
    """
)

# 3. Save to docs/references/
Write(f"docs/references/{paper_name}.md", markdown)
```

### Phase 3: Synthesis into Reference Manuals (4 hours)

**Create 5 comprehensive reference manuals** combining extracted content:

1. **COVARIANCE_ESTIMATION_REFERENCE.md**
   - Combines: Grinold-Kahn Ch3, Ledoit-Wolf papers, shrinkage papers
   - Sections:
     - Sample covariance (formula, properties, issues)
     - Shrinkage methods (linear, nonlinear)
     - Target selection (constant correlation, diagonal, identity, factor model)
     - Asymptotic properties
     - ARBS implementations (cross-refs to `Risk/Covariance/*`)

2. **PORTFOLIO_OPTIMIZATION_REFERENCE.md**
   - Combines: Grinold-Kahn Ch14, QP papers, transaction cost papers
   - Sections:
     - Mean-variance optimization (Markowitz 1952)
     - Quadratic programming formulation
     - Constraints (budget, long-only, position limits, leverage)
     - Transaction costs (proportional, quadratic)
     - Numerical methods and stability
     - ARBS implementations (cross-refs to `Optimizer/*`)

3. **ALPHA_GENERATION_REFERENCE.md**
   - Combines: Grinold-Kahn Ch5-13, alpha factor papers, IC papers
   - Sections:
     - Fundamental Law (IR = IC × √N)
     - Alpha scaling (IC × Vol × Z)
     - Information Coefficient (definition, calculation, interpretation)
     - Signal types (carry, momentum, mean reversion, value)
     - Signal combination (equal weight, IC weight, optimization)
     - Alpha decay and overfitting
     - ARBS implementations (cross-refs to `Signals/*`, `AlphaGenerator/*`)

4. **PERFORMANCE_ANALYSIS_REFERENCE.md**
   - Combines: Grinold-Kahn Ch17, performance papers
   - Sections:
     - Information Ratio (formula, interpretation)
     - Sharpe Ratio (risk-adjusted return)
     - IC metrics (IC, Rank IC, ICIR)
     - Attribution analysis (factor, timing, selection)
     - Statistical significance (t-statistics, multiple testing)
     - ARBS implementations (cross-refs to `Analysis/TearSheet.py`)

5. **RISK_MODELING_REFERENCE.md**
   - Combines: Grinold-Kahn Ch3, risk papers, CVaR papers
   - Sections:
     - Volatility estimation (EWMA, GARCH)
     - Covariance estimation (see COVARIANCE_ESTIMATION_REFERENCE.md)
     - Risk decomposition (systematic, idiosyncratic)
     - Risk budgeting and parity
     - Downside risk (CVaR, max drawdown)
     - ARBS implementations (cross-refs to `Risk/*`, `VolatilityEstimator/*`)

### Phase 4: Quality Control & Integration (2 hours)

**Tasks**:
1. **Verify mathematical accuracy**:
   - Check equations against original PDFs
   - Verify LaTeX rendering
   - Confirm citation accuracy

2. **Validate ARBS cross-references**:
   - Ensure file paths are correct
   - Link implementations to theory
   - Identify missing implementations

3. **Update main documentation**:
   - Add references to README.md
   - Update `docs/references/Grinold-Kahn-Active-Portfolio-Management.md`
   - Create index of all reference manuals

4. **Test examples**:
   - Verify code snippets are runnable
   - Check that formulas match implementations
   - Confirm expected outputs

---

## Automation: PDF Processing Script

### Script Location
`scripts/process_pdfs.py`

### Script Functionality

```python
#!/usr/bin/env python3
"""
ABOUTME: Process research PDFs into structured markdown reference manuals
ABOUTME: Uses Claude agent to read PDFs and extract mathematical content
"""

import os
from pathlib import Path
from typing import List, Dict
import subprocess

# PDF inventory
PDFS_TO_DOWNLOAD = {
    'covariance-estimation': [
        ('2304.07045', 'ledoit-wolf-unknown-mean-2023.pdf'),
        ('1611.06753', 'shrinkage-high-frequency-2016.pdf'),
        ('1909.04222', 'total-positivity-2019.pdf'),
    ],
    'transaction-costs': [
        ('2001.01612', 'quadratic-costs-2020.pdf'),
        ('2412.11575', 'cost-aware-large-universe-2024.pdf'),
        ('2212.06983', 'fast-qp-2022.pdf'),
    ],
    'alpha-generation': [
        ('2406.18394', 'alphaforge-2024.pdf'),
        ('1601.00991', '101-alphas-2016.pdf'),
        ('2502.16789', 'alphaagent-2025.pdf'),
        ('2409.06289', 'llm-strategy-finding-2024.pdf'),
    ],
    'risk-modeling': [
        ('2504.19980', 'risk-budgeting-2025.pdf'),
        ('2510.06986', 'inverse-optimization-2024.pdf'),
        ('2505.07537', 'multi-asset-2025.pdf'),
    ],
    'advanced': [
        ('2406.00610', 'robust-cvar-2024.pdf'),
        ('2508.10776', 'decision-focused-learning-2025.pdf'),
        ('2503.15186', 'optimal-cross-validation-2025.pdf'),
    ],
}

def download_arxiv_pdfs(base_dir: Path):
    """Download all PDFs from arXiv"""
    for category, papers in PDFS_TO_DOWNLOAD.items():
        cat_dir = base_dir / 'papers' / category
        cat_dir.mkdir(parents=True, exist_ok=True)

        for arxiv_id, filename in papers:
            url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            output_path = cat_dir / filename

            if output_path.exists():
                print(f"✓ {filename} already exists")
                continue

            print(f"Downloading {filename}...")
            subprocess.run(['curl', '-L', '-o', str(output_path), url], check=True)
            print(f"✓ Downloaded {filename}")

def create_processing_agents():
    """
    Create agent tasks to process PDFs

    Returns list of agent invocation commands that can be run
    via Claude Code Task tool
    """
    # This would be implemented to generate Task tool calls
    # for each PDF to be processed
    pass

if __name__ == '__main__':
    base_dir = Path('/home/user/ARBS/docs')

    # Phase 1: Download PDFs
    print("Phase 1: Downloading PDFs...")
    download_arxiv_pdfs(base_dir)

    # Phase 2-4 would be implemented as agent workflows
    print("\nNext: Use agent mode to process PDFs")
    print("See PDF_PROCESSING_PLAN.md for details")
```

---

## Timeline

| Phase | Duration | Description |
|-------|----------|-------------|
| **Phase 1** | 2 hours | Download and organize all PDFs |
| **Phase 2** | 8 hours | Agent-driven content extraction (16 PDFs × 30 min each) |
| **Phase 3** | 4 hours | Synthesize into 5 reference manuals |
| **Phase 4** | 2 hours | Quality control and integration |
| **Total** | 16 hours | Complete mathematical reference library |

---

## Expected Output

### Directory Structure After Processing
```
docs/
├── books/
│   └── Grinold-Kahn-Active-Portfolio-Management-1999.pdf
├── papers/
│   ├── covariance-estimation/ (3 PDFs)
│   ├── transaction-costs/ (3 PDFs)
│   ├── alpha-generation/ (4 PDFs)
│   ├── risk-modeling/ (3 PDFs)
│   └── advanced/ (3 PDFs)
├── references/
│   ├── Grinold-Kahn-Active-Portfolio-Management.md (existing)
│   ├── [16 individual paper references].md (extracted)
│   ├── COVARIANCE_ESTIMATION_REFERENCE.md (synthesized)
│   ├── PORTFOLIO_OPTIMIZATION_REFERENCE.md (synthesized)
│   ├── ALPHA_GENERATION_REFERENCE.md (synthesized)
│   ├── PERFORMANCE_ANALYSIS_REFERENCE.md (synthesized)
│   └── RISK_MODELING_REFERENCE.md (synthesized)
└── PDF_PROCESSING_PLAN.md (this file)
```

### Benefits

1. **Comprehensive mathematical foundation** for all ARBS components
2. **Cross-referenced** theory ↔ implementation
3. **Searchable** markdown (vs locked PDFs)
4. **Version controlled** knowledge base
5. **Onboarding resource** for new developers
6. **Research reference** for strategy development
7. **Gap analysis** - identify missing implementations

---

## Next Steps

1. **Review this plan** with Peter
2. **Execute Phase 1** - Download PDFs (2 hours)
3. **Create processing agents** - Set up agent workflows for extraction
4. **Process in batches** - 3-4 PDFs at a time to avoid fatigue
5. **Synthesize manuals** - Combine extracted content into references
6. **Commit to repo** - Add all documentation to version control

---

**Status**: PLAN COMPLETE, READY FOR EXECUTION
**Owner**: Claude + Peter
**Priority**: HIGH (foundational documentation)
