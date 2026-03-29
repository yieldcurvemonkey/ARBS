"""Codependence measures."""

from arbitragelab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "angular_distance": ("arbitragelab.codependence.correlation", "angular_distance"),
        "absolute_angular_distance": (
            "arbitragelab.codependence.correlation",
            "absolute_angular_distance",
        ),
        "squared_angular_distance": (
            "arbitragelab.codependence.correlation",
            "squared_angular_distance",
        ),
        "distance_correlation": ("arbitragelab.codependence.correlation", "distance_correlation"),
        "get_mutual_info": ("arbitragelab.codependence.information", "get_mutual_info"),
        "get_optimal_number_of_bins": (
            "arbitragelab.codependence.information",
            "get_optimal_number_of_bins",
        ),
        "variation_of_information_score": (
            "arbitragelab.codependence.information",
            "variation_of_information_score",
        ),
        "get_dependence_matrix": (
            "arbitragelab.codependence.codependence_matrix",
            "get_dependence_matrix",
        ),
        "get_distance_matrix": (
            "arbitragelab.codependence.codependence_matrix",
            "get_distance_matrix",
        ),
        "spearmans_rho": ("arbitragelab.codependence.gnpr_distance", "spearmans_rho"),
        "gpr_distance": ("arbitragelab.codependence.gnpr_distance", "gpr_distance"),
        "gnpr_distance": ("arbitragelab.codependence.gnpr_distance", "gnpr_distance"),
        "optimal_transport_dependence": (
            "arbitragelab.codependence.optimal_transport",
            "optimal_transport_dependence",
        ),
    },
)
