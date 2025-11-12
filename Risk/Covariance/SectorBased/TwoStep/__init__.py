# ABOUTME: Two-step covariance estimator combining hierarchical clustering and RMT filtering
# ABOUTME: Best performer from García-Medina (2024) with superior diversification metrics

from Risk.Covariance.SectorBased.TwoStep.RandomMatrixFilter import RandomMatrixFilter

__all__ = ["RandomMatrixFilter", "TwoStepCovariance"]

# Lazy import to avoid circular dependencies
def __getattr__(name):
    if name == "TwoStepCovariance":
        from Risk.Covariance.SectorBased.TwoStep.TwoStepCovariance import TwoStepCovariance
        return TwoStepCovariance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
