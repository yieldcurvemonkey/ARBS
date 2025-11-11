# Python Covariance Estimation Implementation Sources

Survey of existing Python implementations for covariance matrix estimation, focusing on shrinkage methods and advanced techniques suitable for portfolio optimization.

Last Updated: 2025-11-11

---

## 1. Major Portfolio Optimization Libraries

### PyPortfolioOpt

**Repository:** https://github.com/robertmartin8/PyPortfolioOpt  
**Documentation:** https://pyportfolioopt.readthedocs.io/en/latest/  
**PyPI:** https://pypi.org/project/pyportfolioopt/  
**Version:** 1.5.4 (stable)

**Installation:**
```bash
pip install PyPortfolioOpt
```

**Python Support:** 3.8+  
**License:** MIT  
**Documentation Quality:** Good (comprehensive docs with examples)

**Covariance Methods Implemented:**

1. **Sample Covariance** (`sample_cov`)
   - Basic unbiased estimator (not recommended by authors)
   - High estimation error, lacks robustness

2. **Ledoit-Wolf Shrinkage** (`CovarianceShrinkage.ledoit_wolf()`)
   - Three shrinkage targets:
     - `constant_variance`: Diagonal matrix with mean variances
     - `single_factor`: Sharpe's single-index model
     - `constant_correlation`: Average correlation matrix
   - Automatic optimal shrinkage coefficient
   - **Recommended as default by authors**

3. **Oracle Approximating Shrinkage (OAS)** (`oracle_approximating`)
   - Lower MSE than Ledoit-Wolf for Gaussian data
   - Based on Chen et al. (2010)

4. **Manual Shrinkage** (`shrunk_covariance`)
   - User-specified shrinkage parameter (delta)

5. **Exponential Covariance** (`exp_cov`)
   - Weights recent data more heavily
   - Configurable span parameter (default 180 days)

6. **Semicovariance** (`semicovariance`)
   - Downside risk focus
   - Only considers returns below benchmark

7. **Minimum Covariance Determinant**
   - Robust to outliers (via sklearn)

**API Example:**
```python
from pypfopt import risk_models

# Method 1: Direct call
cov_matrix = risk_models.sample_cov(prices, frequency=252)

# Method 2: Ledoit-Wolf shrinkage (recommended)
from pypfopt.risk_models import CovarianceShrinkage
cs = CovarianceShrinkage(prices)
cov_matrix = cs.ledoit_wolf(shrinkage_target='constant_variance')

# Method 3: Unified interface
cov_matrix = risk_models.risk_matrix(prices, method='ledoit_wolf', 
                                     shrinkage_target='constant_correlation')
```

**Notes:**
- Wraps sklearn.covariance implementations
- Provides convenient DataFrame interface
- Good utilities: `cov_to_corr()`, `fix_nonpositive_semidefinite()`

---

### Riskfolio-Lib

**Repository:** https://github.com/dcajasn/Riskfolio-Lib  
**PyPI:** https://pypi.org/project/riskfolio-lib/  
**Version:** 7.0.1 (2025)

**Installation:**
```bash
pip install riskfolio-lib
```

**Python Support:** 3.9+  
**License:** BSD-3-Clause  
**Documentation Quality:** Good (comprehensive for portfolio optimization)

**Covariance Methods Implemented:**

1. **Historical Covariance** (`method_cov='hist'`)
2. **Graphical Lasso** (sparse precision estimation)
3. **j-Logo** (covariance estimation)
4. **Denoising** (RMT-based)
5. **Detoning** (RMT-based)
6. **Custom Matrix Support** (user-specified covariance)

**API Example:**
```python
import riskfolio as rp

# Create portfolio object
port = rp.Portfolio(returns=returns_df)

# Estimate covariance
port.assets_stats(method_cov='hist')  # or other methods

# Access covariance matrix
cov_matrix = port.cov
```

**Notes:**
- More focused on portfolio optimization than covariance estimation
- Advanced features: uncertainty sets, elliptical uncertainty
- Integrates with broader portfolio optimization workflow
- Less detailed documentation specifically for covariance methods

---

## 2. Scikit-learn Built-in Methods

**Documentation:** https://scikit-learn.org/stable/modules/covariance.html  
**Version:** 1.7.2 (current stable)

**Installation:**
```bash
pip install scikit-learn
```

**Python Support:** 3.9+  
**License:** BSD-3-Clause  
**Documentation Quality:** Excellent

**Covariance Estimators:**

1. **EmpiricalCovariance**
   - Basic MLE estimator
   - Works well when n >> p

2. **ShrunkCovariance**
   - Manual shrinkage with user-defined coefficient
   - Formula: Σ_shrunk = (1-α)Σ̂ + α(TrΣ̂/p)Id

3. **LedoitWolf**
   - Automatic optimal shrinkage coefficient
   - Based on Ledoit & Wolf (2004)
   - Very efficient, well-conditioned

4. **OAS (Oracle Approximating Shrinkage)**
   - Better MSE than LedoitWolf under Gaussian assumption
   - Chen et al. methodology

5. **GraphicalLasso / GraphicalLassoCV**
   - L1 penalty for sparse precision matrix
   - Recovers conditional independence structure
   - Effective for small samples

6. **MinCovDet (Minimum Covariance Determinant)**
   - Robust to outliers
   - FastMCD algorithm

**API Example:**
```python
from sklearn.covariance import LedoitWolf, OAS, GraphicalLassoCV

# Ledoit-Wolf
lw = LedoitWolf(store_precision=True, assume_centered=False)
lw.fit(X)
cov_matrix = lw.covariance_
shrinkage = lw.shrinkage_

# OAS
oas = OAS()
oas.fit(X)
cov_matrix = oas.covariance_

# Graphical Lasso with cross-validation
model = GraphicalLassoCV()
model.fit(X)
cov_matrix = model.covariance_
precision_matrix = model.precision_
```

**Notes:**
- Industry standard, well-tested
- Excellent performance characteristics
- Comprehensive benchmarking examples
- Mature, actively maintained

---

## 3. Specialized Shrinkage Packages

### nonlinshrink

**PyPI:** https://pypi.org/project/nonlinshrink/  
**GitHub:** https://github.com/matzhaugen/analytic_shrinkage  
**Version:** 0.7 (Nov 2019)

**Installation:**
```bash
pip install nonlinshrink
```

**Python Support:** Python 3  
**License:** MIT  
**Documentation Quality:** Poor (minimal docs, use docstrings)

**Method:**
- Nonlinear analytic shrinkage from Ledoit & Wolf (2018)
- "Analytical Nonlinear Shrinkage of Large-Dimensional Covariance Matrices"

**API Example:**
```python
import numpy as np
import nonlinshrink as nls

# Generate data
data = np.random.multivariate_normal(np.zeros(p), sigma, n)

# Apply nonlinear shrinkage
sigma_tilde = nls.shrink_cov(data)
```

**Notes:**
- **Package appears inactive** (last update 2019)
- Limited weekly downloads (23)
- No known security issues
- Simple, focused implementation
- Consider more maintained alternatives

---

### covShrinkage

**GitHub:** https://github.com/pald22/covShrinkage  
**Version:** Not on PyPI (GitHub only)

**Installation:**
```bash
git clone https://github.com/pald22/covShrinkage
cd covShrinkage
python setup.py install
```

**Python Support:** Not specified  
**License:** MIT  
**Documentation Quality:** Poor (method descriptions only, no usage examples)

**Methods Implemented:**

**Linear Shrinkage:**
- `cov1Para`: One-parameter target
- `cov2Para`: Two-parameter target
- `covCor`: Constant-correlation matrix
- `covDiag`: Diagonal matrix
- `covMarket`: One-factor market model

**Nonlinear Shrinkage:**
- `GIS`: Geometric-inverse shrinkage
- `LIS`: Linear-inverse shrinkage
- `QIS`: Quadratic-inverse shrinkage

**API:**
```python
# Input: Y (N×p raw data matrix), k (demeaning parameter)
# Output: sigmahat (p×p covariance estimator)
# Exact API not documented
```

**Notes:**
- 10 Python files with various methods
- Academic implementation
- Limited documentation
- Not pip-installable
- Consider for research/comparison only

---

## 4. Graphical Models & Sparse Estimation

### skggm

**GitHub:** https://github.com/skggm/skggm  
**Documentation:** https://skggm.github.io/skggm/  
**PyPI:** https://pypi.org/project/skggm/

**Installation:**
```bash
# Requires NumPy, SciPy, Cython, LAPACK
pip install skggm
```

**Python Support:** 2.7, 3.6.x  
**License:** MIT  
**Documentation Quality:** Good (comprehensive tour at skggm.github.io)

**Methods Implemented:**

1. **QuicGraphicalLasso**
   - QUIC algorithm for sparse inverse covariance
   - Scalar or matrix penalties
   - Fast implementation

2. **QuicGraphicalLassoCV**
   - Cross-validation for model selection

3. **QuicGraphicalLassoEBIC**
   - Extended Bayesian Information Criteria

4. **AdaptiveGraphicalLasso**
   - Two-step adaptive penalization

5. **ModelAverage**
   - Bootstrap-based ensemble stability selection

**API Example:**
```python
from inverse_covariance import QuicGraphicalLassoCV

model = QuicGraphicalLassoCV()
model.fit(X)

covariance = model.covariance_
precision = model.precision_
lambda_opt = model.lam_
```

**Features:**
- Matrix-valued penalty support (beyond sklearn)
- Parallelization (joblib, Spark)
- Regularization path exploration
- Profiling/benchmarking tools

**Notes:**
- Focused on Gaussian graphical models
- Learning conditional independence structures
- More specialized than general covariance estimation
- Good for high-dimensional sparse problems

---

## 5. Random Matrix Theory

### pyRMT

**GitHub:** https://github.com/GGiecold/pyRMT  
**PyPI:** https://pypi.org/project/pyRMT/  
**Version:** 0.1.0

**Installation:**
```bash
pip install pyRMT
```

**Python Support:** Python 2 and 3  
**License:** MIT  
**Documentation Quality:** Poor (no usage examples, refer to docstrings)

**Methods:**
- Cleaning schemes for noisy correlation matrices
- Optimal shrinkage
- Rotationally-invariant estimator
- Based on Ledoit-Wolf and Bun-Bouchaud-Potters work

**API Example:**
```python
import pyRMT
# Refer to docstrings for specific usage
# No clear examples in documentation
```

**Notes:**
- **Appears inactive** (last commit Aug 2021)
- 2 open PRs, 3 open issues
- Improved out-of-sample risk for Markowitz portfolios
- Consider scikit-rmt as alternative

---

### scikit-rmt

**GitHub:** https://github.com/AlejandroSantorum/scikit-rmt  
**Documentation:** https://scikit-rmt.readthedocs.io/  
**PyPI:** https://pypi.org/project/scikit-rmt/  
**Version:** 1.0.0 (updated 2025)

**Installation:**
```bash
pip install scikit-rmt
```

**Python Support:** 3.8 - 3.12  
**License:** BSD-3-Clause  
**Documentation Quality:** Good (comprehensive ReadTheDocs)

**Features:**

**Random Matrix Ensembles:**
- Gaussian (GOE, GUE, GSE)
- Wishart (WRE, WCE, WQE)
- Manova (MRE, MCE, MQE)
- Circular (COE, CUE, CSE)

**Covariance Estimation:**
- Sample estimator
- Finite-sample Optimal (FSOpt) estimator
- Empirical Bayesian estimator

**Spectral Laws:**
- Wigner Semicircle Distribution
- Marchenko-Pastur Distribution
- Tracy-Widom Distribution

**API Example:**
```python
from skrmt.ensemble import GaussianEnsemble
from skrmt.covariance import analytical_shrinkage

# Sample from ensemble
ensemble = GaussianEnsemble(beta=1, n=100)
matrices = ensemble.sample(size=10)

# Compute spectral density
eigenvalues = np.linalg.eigvalsh(matrices[0])

# Covariance estimation
cov_estimate = analytical_shrinkage(data, method='fso')
```

**Notes:**
- **Most actively maintained RMT package** for 2025
- Modern Python support (3.8-3.12)
- Comprehensive documentation
- Good for research and practical applications
- Spectral analysis tools

---

## 6. Cutting-Edge Research Implementations

### ERSE (Eigenvector Rotation Shrinkage Estimator)

**Paper:** "Covariance Matrix Estimation for Positively Correlated Assets"  
**arXiv:** https://arxiv.org/html/2507.01545  
**Published:** July 2025  
**Implementation:** **No public code available yet**

**Method:**
- Rotation-equivariant estimator for positively correlated assets
- Paired Eigenvector Rotation (PER) technique
- Iterative optimization preserving orthogonality

**Performance:**
- 10.52% variance reduction vs linear shrinkage
- 12.46% variance reduction vs nonlinear shrinkage
- Tested on Ken French factor portfolios

**Status:**
- Very recent publication (July 2025)
- No GitHub repository found
- May require implementation from paper
- Consider contacting authors for code

**Recommendation:** Monitor for code release or implement from paper if needed for positively correlated asset portfolios.

---

### WeSpeR (Weighted sample covariance Spectrum Retrieval)

**GitHub:** https://www.github.com/nlcvbo/WeSpeR  
**Paper:** https://arxiv.org/abs/2410.14413  
**Published:** Oct 2024, revised Aug 2025  
**Implementation:** Available (PyTorch)

**Installation:**
```bash
git clone https://www.github.com/nlcvbo/WeSpeR
# Installation instructions in repository
```

**Python Support:** Requires PyTorch  
**License:** Check repository  
**Documentation Quality:** Academic paper + code comments

**Method:**
- Nonlinear shrinkage for weighted sample covariance
- Three algorithms: Low-dimensional (LD), Medium-dimensional (MD), High-dimensional (HD)
- Significantly faster for dimensions > 1000
- PyTorch module with analytical derivatives
- Integrates with automatic differentiation

**Features:**
- Backward function analytically computing derivatives
- Uses PyTorch optimizers (default: Adam)
- Can be integrated in larger optimization problems
- Handles weighted observations (not just equal-weighted)

**API Example:**
```python
import torch
from wesper import WeSpeR  # Hypothetical import

# Initialize WeSpeR module
wesper = WeSpeR(dimension=dim, regime='HD')  # or 'LD', 'MD'

# Compute shrinkage
cov_estimate = wesper(weighted_data)

# Use in optimization (differentiable)
loss = some_loss_function(cov_estimate)
loss.backward()  # Analytical derivatives
```

**Notes:**
- **Cutting-edge** (2025 revision)
- PyTorch integration enables ML workflows
- Handles weighted covariance (important for time-series)
- Good for high-dimensional problems (>1000)
- Requires familiarity with PyTorch

**Recommendation:** Excellent choice for modern ML-integrated workflows with large dimensions.

---

## Comparison Summary

### Best for General Use

| Package | Best For | Pros | Cons |
|---------|----------|------|------|
| **sklearn.covariance** | Default choice | Mature, well-tested, excellent docs | Basic methods only |
| **PyPortfolioOpt** | Portfolio optimization | Easy API, good defaults, DataFrame support | Wraps sklearn, fewer advanced methods |
| **scikit-rmt** | RMT applications | Modern (2025), good docs, Python 3.8-3.12 | More academic focus |

### Best for Advanced Methods

| Method Type | Package | Notes |
|-------------|---------|-------|
| **Linear Shrinkage** | sklearn LedoitWolf | Industry standard |
| **Nonlinear Shrinkage** | WeSpeR | Cutting-edge, PyTorch, weighted data |
| **Sparse/Graphical** | skggm | Conditional independence, high-dim sparse |
| **Robust** | sklearn MinCovDet | Outlier resistance |
| **RMT Cleaning** | scikit-rmt | Modern, actively maintained |

### Best for Research

| Application | Package | Reason |
|-------------|---------|--------|
| **Positive correlation** | ERSE (when available) | State-of-art for positively correlated assets |
| **Weighted covariance** | WeSpeR | Only method handling weighted samples |
| **High-dimensional** | WeSpeR, scikit-rmt | Optimized for dim > 1000 |
| **Benchmarking** | Multiple | Use sklearn + PyPortfolioOpt + scikit-rmt |

---

## Recommendations for Integration

### For Immediate Use

1. **sklearn.covariance.LedoitWolf** - Rock solid, well-tested
2. **PyPortfolioOpt** - If working with price DataFrames
3. **sklearn.covariance.GraphicalLassoCV** - For sparse structure

### For Research/Advanced

1. **WeSpeR** - Cutting-edge, PyTorch integration, weighted data
2. **scikit-rmt** - Modern RMT tools, actively maintained
3. **ERSE** - Monitor for code release (best for positive correlations)

### Implementation Strategy

**Phase 1: Baseline**
- Implement sklearn LedoitWolf (proven, stable)
- Compare with sample covariance
- Benchmark performance

**Phase 2: Comparison**
- Add OAS (sklearn)
- Add PyPortfolioOpt wrappers (constant_correlation target)
- Test semicovariance for downside risk

**Phase 3: Advanced**
- Integrate WeSpeR for weighted samples
- Consider GraphicalLasso for sparse structure
- Implement ERSE when code available

**Phase 4: RMT (Optional)**
- scikit-rmt for spectral analysis
- Denoising/detoning if needed
- Compare with Riskfolio-Lib methods

---

## License Compatibility

All major packages use permissive licenses compatible with most projects:

- **MIT:** PyPortfolioOpt, nonlinshrink, covShrinkage, pyRMT, skggm
- **BSD-3-Clause:** sklearn, Riskfolio-Lib, scikit-rmt
- **Check repo:** WeSpeR (likely permissive)

---

## Installation Quick Reference

```bash
# Essential packages
pip install scikit-learn
pip install PyPortfolioOpt

# Advanced packages
pip install scikit-rmt
pip install skggm
pip install riskfolio-lib

# Research packages
pip install nonlinshrink  # Consider alternatives
git clone https://github.com/pald22/covShrinkage
git clone https://www.github.com/nlcvbo/WeSpeR
```

---

## Next Steps

1. **Verify WeSpeR repository access** - Confirm installation and API
2. **Benchmark basic methods** - LedoitWolf, OAS, sample covariance
3. **Test on our data** - Futures returns with realistic dimensions
4. **Performance comparison** - Out-of-sample risk reduction
5. **Documentation** - Document chosen method and rationale

---

## References

### Key Papers

1. Ledoit & Wolf (2004) - "A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices"
2. Ledoit & Wolf (2018) - "Analytical Nonlinear Shrinkage of Large-Dimensional Covariance Matrices"
3. Chen et al. (2010) - Oracle Approximating Shrinkage
4. Bun, Bouchaud, Potters - Rotationally-invariant estimators
5. ERSE Paper (2025) - Eigenvector Rotation Shrinkage
6. WeSpeR Paper (2025) - Weighted sample covariance spectrum retrieval

### Package Documentation

- sklearn: https://scikit-learn.org/stable/modules/covariance.html
- PyPortfolioOpt: https://pyportfolioopt.readthedocs.io/en/latest/RiskModels.html
- scikit-rmt: https://scikit-rmt.readthedocs.io/
- skggm: https://skggm.github.io/skggm/

---

**Survey compiled:** 2025-11-11  
**For:** ARBS Futures/Swaps Backtesting Project  
**Focus:** Covariance estimation for portfolio optimization
