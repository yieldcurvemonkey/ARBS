"""
ArbitrageLab helps portfolio managers and traders who want to leverage the power of
statistical arbitrage by providing reproducible, interpretable, and easy-to-use tools.
"""

from arbitragelab._lazy import attach_lazy_exports

__version__ = "1.0.0"

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "codependence": ("arbitragelab.codependence", None),
        "cointegration_approach": ("arbitragelab.cointegration_approach", None),
        "copula_approach": ("arbitragelab.copula_approach", None),
        "distance_approach": ("arbitragelab.distance_approach", None),
        "hedge_ratios": ("arbitragelab.hedge_ratios", None),
        "ml_approach": ("arbitragelab.ml_approach", None),
        "optimal_mean_reversion": ("arbitragelab.optimal_mean_reversion", None),
        "other_approaches": ("arbitragelab.other_approaches", None),
        "spread_selection": ("arbitragelab.spread_selection", None),
        "stochastic_control_approach": ("arbitragelab.stochastic_control_approach", None),
        "tearsheet": ("arbitragelab.tearsheet", None),
        "time_series_approach": ("arbitragelab.time_series_approach", None),
        "trading": ("arbitragelab.trading", None),
        "util": ("arbitragelab.util", None),
    },
)
