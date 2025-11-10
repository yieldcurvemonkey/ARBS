# Research Papers Directory

This directory contains PDF copies of research papers referenced in `PORTFOLIO_MANAGEMENT_RESEARCH.md`.

## Download Instructions

Use the following commands to download papers from arXiv:

```bash
# 2025 Papers (Priority 1)
wget -O 2509_Caner_AIMLPortfolio.pdf https://arxiv.org/pdf/2509.25456.pdf
wget -O 2510_Xue_AttentionRL.pdf https://arxiv.org/pdf/2510.06466.pdf
wget -O 2509_Ramirez_HRP_LatAm.pdf https://arxiv.org/pdf/2509.03712.pdf
wget -O 2508_Kang_RLBHRP.pdf https://arxiv.org/pdf/2508.11856.pdf
wget -O 2509_Chen_AdaptiveAlpha.pdf https://arxiv.org/pdf/2509.01393.pdf
wget -O 2508_Luan_DeepLearning.pdf https://arxiv.org/pdf/2508.14656.pdf
wget -O 2508_Ding_AlphaEval.pdf https://arxiv.org/pdf/2508.13174.pdf
wget -O 2508_Chen_SentimentMV.pdf https://arxiv.org/pdf/2508.16378.pdf
wget -O 2505_Li_MultiAssetSAC.pdf https://arxiv.org/pdf/2505.07537.pdf
wget -O 2412_Fan_CostAware.pdf https://arxiv.org/pdf/2412.11575.pdf
wget -O 2509_IncreaseAlpha.pdf https://arxiv.org/pdf/2509.16707.pdf
wget -O 2505_SparseMV.pdf https://arxiv.org/pdf/2505.10099.pdf
```

## Naming Convention

Format: `YYMM_FirstAuthor_ShortTitle.pdf`

- `YY` = Year (25 = 2025, 24 = 2024)
- `MM` = Month (01-12)
- `FirstAuthor` = Last name of first author
- `ShortTitle` = Descriptive short title (no spaces, CamelCase)

## Top 5 Papers for ARBS Implementation

### 1. RL-BHRP (Aug 2025) - `2508_Kang_RLBHRP.pdf`
**arXiv**: 2508.11856
**Impact**: +120% vs +91% benchmark (2020-2025)
**Key**: Combines HRP stability with RL adaptability (PPO)

### 2. Cost-aware Portfolios (Dec 2024/Aug 2025) - `2412_Fan_CostAware.pdf`
**arXiv**: 2412.11575
**Impact**: Better rebalancing performance with explicit transaction costs
**Key**: Proportional + quadratic costs, cardinality (L0) constraint

### 3. Attention-Enhanced RL (Oct 2025) - `2510_Xue_AttentionRL.pdf`
**arXiv**: 2510.06466
**Impact**: Outperforms baselines in Sharpe + terminal wealth
**Key**: Cross-sectional attention, Dirichlet policy, transaction costs

### 4. AlphaEval Framework (Aug 2025) - `2508_Ding_AlphaEval.pdf`
**arXiv**: 2508.13174
**Impact**: Comprehensive alpha evaluation beyond IC
**Key**: 5 dimensions (predictive, stable, robust, logical, diverse)

### 5. AI+ML Practitioner's Guide (Sept 2025) - `2509_Caner_AIMLPortfolio.pdf`
**arXiv**: 2509.25456
**Impact**: Best Sharpe across 5 time periods
**Key**: Nodewise regression + Global Minimum Variance (GMV)

## Quick Reference by Topic

### Covariance Estimation
- `2509_Caner_AIMLPortfolio.pdf` - Nodewise regression (precision matrix)
- `2407_CovarianceAnalysis.pdf` - L1+L2 shrinkage (2024)
- `2305_PrecisionVsShrinkage.pdf` - Comparative analysis (2023)

### Alpha Signals & IC
- `2508_Ding_AlphaEval.pdf` - 5-dimensional evaluation
- `2509_Chen_AdaptiveAlpha.pdf` - PPO-based weighting
- `2508_Luan_DeepLearning.pdf` - Behavioral factors + deep learning

### Portfolio Optimization
- `2508_Kang_RLBHRP.pdf` - HRP + RL adaptive
- `2510_Xue_AttentionRL.pdf` - Attention mechanisms
- `2412_Fan_CostAware.pdf` - Transaction costs

### Fixed Income & Factor Models
- `2212_TensorPCA.pdf` - Tensor PCA (2022, updated 2025)
- `2212_FunctionalPCA.pdf` - Term structure (2022)
- `1911_ChineseBonds.pdf` - 3-factor validation (2019)

### Transaction Costs
- `2412_Fan_CostAware.pdf` - Proportional + quadratic
- `2403_DeepRL_MV.pdf` - Rebalancing frequency (2024)
- `2510_Xue_AttentionRL.pdf` - Reward function penalties

## Download Status

- [ ] 2509_Caner_AIMLPortfolio.pdf
- [ ] 2510_Xue_AttentionRL.pdf
- [ ] 2509_Ramirez_HRP_LatAm.pdf
- [ ] 2508_Kang_RLBHRP.pdf
- [ ] 2509_Chen_AdaptiveAlpha.pdf
- [ ] 2508_Luan_DeepLearning.pdf
- [ ] 2508_Ding_AlphaEval.pdf
- [ ] 2508_Chen_SentimentMV.pdf
- [ ] 2505_Li_MultiAssetSAC.pdf
- [ ] 2412_Fan_CostAware.pdf

## Notes

Papers are stored locally for offline reference during implementation. Always check arXiv for the most recent version before citing.

Last Updated: 2025-11-10
