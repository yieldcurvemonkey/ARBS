"""CvxSuite — the production join layer for the convexity-RV framework.

One package that composes the verified kernels (ConvexityRV, CurveFlyScreener,
INGCurve, mean_reversion, StatisticalFinance, the swaption cube store) into:

* the **kink ledger screen** (``kink_screen`` + ``scripts/kink_ledger_screen.py``)
  — PCA/xsec residuals on the 1y-forward grid, convexity-adjusted, with the
  four rent numbers per point (docs/convexityrv/kink_ledger.md section 6);
* the **breakeven board** (``board`` + ``scripts/breakeven_board.py``)
  — every wrapper's sigma_BE / sigma_rlzd and sigma_impl / sigma_rlzd on one
  bp/day axis (the Convexity Ledger's gap #1);
* the **QDB reference strategies** (``BT/signals/cvx_*.py``)
  — strikeless-vol resize harvest, kink harvest overlay, fly dislocation book.

Design doc: docs/cvxsuite/DESIGN.md.  Module ownership is one concern per
file; C1 modules (carry, vols, ou, residuals, frontiers, gates, rent, books,
grids) do not import each other — only kernels; kink_screen and board compose
them.  Everything stated as a number in docstrings here was measured on this
machine or is quoted with attribution.
"""

from __future__ import annotations

__all__ = [
    "grids",
    "carry",
    "vols",
    "ou",
    "residuals",
    "frontiers",
    "gates",
    "rent",
    "books",
    "kink_screen",
    "board",
]
