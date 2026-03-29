"""Machine-learning-based approaches."""

from arbitragelab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "OPTICSDBSCANPairsClustering": (
            "arbitragelab.ml_approach.optics_dbscan_pairs_clustering",
            "OPTICSDBSCANPairsClustering",
        ),
        "TAR": ("arbitragelab.ml_approach.tar", "TAR"),
        "FeatureExpander": ("arbitragelab.ml_approach.feature_expander", "FeatureExpander"),
        "RegressorCommittee": (
            "arbitragelab.ml_approach.regressor_committee",
            "RegressorCommittee",
        ),
        "ThresholdFilter": ("arbitragelab.ml_approach.filters", "ThresholdFilter"),
        "CorrelationFilter": ("arbitragelab.ml_approach.filters", "CorrelationFilter"),
        "VolatilityFilter": ("arbitragelab.ml_approach.filters", "VolatilityFilter"),
        "MultiLayerPerceptron": (
            "arbitragelab.ml_approach.neural_networks",
            "MultiLayerPerceptron",
        ),
        "RecurrentNeuralNetwork": (
            "arbitragelab.ml_approach.neural_networks",
            "RecurrentNeuralNetwork",
        ),
        "PiSigmaNeuralNetwork": (
            "arbitragelab.ml_approach.neural_networks",
            "PiSigmaNeuralNetwork",
        ),
    },
)
