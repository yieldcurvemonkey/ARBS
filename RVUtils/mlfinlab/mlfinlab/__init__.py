"""
MlFinlab helps portfolio managers and traders who want to leverage the power of machine learning by providing
reproducible, interpretable, and easy to use tools.

Adding MlFinLab to your companies pipeline is like adding a department of PhD researchers to your team.
"""

from mlfinlab._lazy import attach_lazy_exports

__version__ = "0.4.1"

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "cross_validation": ("mlfinlab.cross_validation", None),
        "data_structures": ("mlfinlab.data_structures", None),
        "datasets": ("mlfinlab.datasets", None),
        "multi_product": ("mlfinlab.multi_product", None),
        "filters": ("mlfinlab.filters", None),
        "labeling": ("mlfinlab.labeling", None),
        "fracdiff": ("mlfinlab.features.fracdiff", None),
        "sample_weights": ("mlfinlab.sample_weights", None),
        "sampling": ("mlfinlab.sampling", None),
        "bet_sizing": ("mlfinlab.bet_sizing", None),
        "util": ("mlfinlab.util", None),
        "structural_breaks": ("mlfinlab.structural_breaks", None),
        "feature_importance": ("mlfinlab.feature_importance", None),
        "ensemble": ("mlfinlab.ensemble", None),
        "clustering": ("mlfinlab.clustering", None),
        "microstructural_features": ("mlfinlab.microstructural_features", None),
        "backtests": ("mlfinlab.backtest_statistics.backtests", None),
        "backtest_statistics": ("mlfinlab.backtest_statistics.statistics", None),
        "networks": ("mlfinlab.networks", None),
        "data_generation": ("mlfinlab.data_generation", None),
        "regression": ("mlfinlab.regression", None),
    },
)
