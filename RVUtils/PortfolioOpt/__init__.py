"""Portfolio optimization for ARBS.

Before this, ``BT/`` had no optimizer, no margin model and no capital model: every strategy in the
estate sized itself. :class:`Optimizer` is a mean-variance solver with transaction costs, market
impact and nine constraint families, ported from an outside estate — see
``RVUtils/PortfolioOpt/_optimizer_core.py`` for the full provenance note and the one inherited
defect.

It is deliberately asset-class agnostic: it takes alphas, covariances and costs, and knows nothing
about what is being traded.

>>> from RVUtils.PortfolioOpt import Optimizer, Panel3D
>>> opt = Optimizer()
>>> holdings = opt.mean_variance(alphas, covariances, risk_aversion=1750.0)   # doctest: +SKIP
"""

from RVUtils.PortfolioOpt._optimizer_core import Optimizer
from RVUtils.PortfolioOpt.panel3d import Panel3D, as_panel3d

__all__ = ["Optimizer", "Panel3D", "as_panel3d"]
