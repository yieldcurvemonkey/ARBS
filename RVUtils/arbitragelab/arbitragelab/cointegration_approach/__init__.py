"""Cointegration-based statistical arbitrage tools."""

from arbitragelab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "JohansenPortfolio": ("arbitragelab.cointegration_approach.johansen", "JohansenPortfolio"),
        "EngleGrangerPortfolio": (
            "arbitragelab.cointegration_approach.engle_granger",
            "EngleGrangerPortfolio",
        ),
        "MinimumProfit": (
            "arbitragelab.cointegration_approach.minimum_profit",
            "MinimumProfit",
        ),
        "CointegrationSimulation": (
            "arbitragelab.cointegration_approach.coint_sim",
            "CointegrationSimulation",
        ),
        "MultivariateCointegration": (
            "arbitragelab.cointegration_approach.multi_coint",
            "MultivariateCointegration",
        ),
        "SparseMeanReversionPortfolio": (
            "arbitragelab.cointegration_approach.sparse_mr_portfolio",
            "SparseMeanReversionPortfolio",
        ),
        "get_half_life_of_mean_reversion": (
            "arbitragelab.cointegration_approach.utils",
            "get_half_life_of_mean_reversion",
        ),
        "get_hurst_exponent": ("arbitragelab.cointegration_approach.utils", "get_hurst_exponent"),
    },
)
