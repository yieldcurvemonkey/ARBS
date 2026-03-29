"""Time-series-based statistical arbitrage tools."""

from arbitragelab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "AutoARIMAForecast": (
            "arbitragelab.time_series_approach.arima_predict",
            "AutoARIMAForecast",
        ),
        "get_trend_order": (
            "arbitragelab.time_series_approach.arima_predict",
            "get_trend_order",
        ),
        "QuantileTimeSeriesTradingStrategy": (
            "arbitragelab.time_series_approach.quantile_time_series",
            "QuantileTimeSeriesTradingStrategy",
        ),
        "OUModelOptimalThresholdBertram": (
            "arbitragelab.time_series_approach.ou_optimal_threshold_bertram",
            "OUModelOptimalThresholdBertram",
        ),
        "OUModelOptimalThresholdZeng": (
            "arbitragelab.time_series_approach.ou_optimal_threshold_zeng",
            "OUModelOptimalThresholdZeng",
        ),
    },
)
