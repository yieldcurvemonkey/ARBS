"""Copula-based statistical arbitrage tools."""

from arbitragelab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "find_marginal_cdf": (
            "arbitragelab.copula_approach.copula_calculation",
            "find_marginal_cdf",
        ),
        "sic": ("arbitragelab.copula_approach.copula_calculation", "sic"),
        "aic": ("arbitragelab.copula_approach.copula_calculation", "aic"),
        "hqic": ("arbitragelab.copula_approach.copula_calculation", "hqic"),
        "construct_ecdf_lin": (
            "arbitragelab.copula_approach.copula_calculation",
            "construct_ecdf_lin",
        ),
        "scad_penalty": ("arbitragelab.copula_approach.copula_calculation", "scad_penalty"),
        "scad_derivative": (
            "arbitragelab.copula_approach.copula_calculation",
            "scad_derivative",
        ),
        "adjust_weights": (
            "arbitragelab.copula_approach.copula_calculation",
            "adjust_weights",
        ),
        "to_quantile": ("arbitragelab.copula_approach.copula_calculation", "to_quantile"),
        "fit_copula_to_empirical_data": (
            "arbitragelab.copula_approach.copula_calculation",
            "fit_copula_to_empirical_data",
        ),
        "archimedean": ("arbitragelab.copula_approach.archimedean", None),
        "elliptical": ("arbitragelab.copula_approach.elliptical", None),
        "mixed_copulas": ("arbitragelab.copula_approach.mixed_copulas", None),
        "PartnerSelection": (
            "arbitragelab.copula_approach.vine_copula_partner_selection",
            "PartnerSelection",
        ),
        "RVineCop": ("arbitragelab.copula_approach.vinecop_generate", "RVineCop"),
        "CVineCop": ("arbitragelab.copula_approach.vinecop_generate", "CVineCop"),
        "CVineCopStrat": (
            "arbitragelab.copula_approach.vinecop_strategy",
            "CVineCopStrat",
        ),
    },
)
