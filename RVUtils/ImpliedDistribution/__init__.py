"""SFR Options Implied Distribution Extraction.

Two complementary approaches for inferring market-implied probability distributions
from 3M SOFR futures options:

1. **Breeden-Litzenberger**: Smoothing spline on call prices → 2nd derivative → RND
2. **Gaussian Mixture**: Weighted sum of scenario-specific Normals → scenario weights

Usage::

    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
    from RVUtils.ImpliedDistribution import SFRImpliedDistribution, FedScenarioConfig

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    smile = mdp.fetch_sabr_smile({
        "symbol": "SFRZ27",
        "as_of": datetime.date(2026, 3, 6),
        "strike_offsets_bps": "listed",
    })
    scenarios = FedScenarioConfig.default_sofr_scenarios(
        current_rate=4.33, n_cuts_range=[-1, 0, 1, 2, 3, 5, 9]
    )
    dist = SFRImpliedDistribution(scenario_config=scenarios)
    snapshot = dist.extract(smile)

    from RVUtils.ImpliedDistribution import plot_snapshot_dashboard
    plot_snapshot_dashboard(snapshot)
"""

from RVUtils.ImpliedDistribution._strip_utils import STRIP_PRESETS, resolve_strip_symbols
from RVUtils.ImpliedDistribution._types import (
    AnnotatedResult,
    BreedenLitzenbergerResult,
    FedScenarioConfig,
    FOMCPathState,
    FOMCPathStateConfig,
    GaussianMixtureResult,
    ImpliedDistributionSnapshot,
    JointContractFitDiagnostics,
    JointDistributionComparison,
    JointDistributionSnapshot,
    RNDInput,
    ScenarioDefinition,
    StripComparisonResult,
    ViewMetadata,
)
from RVUtils.ImpliedDistribution.implied_distribution import SFRImpliedDistribution
from RVUtils.ImpliedDistribution._joint_plotting import (
    plot_conditional_distribution,
    plot_empirical_copula,
    plot_joint_comparison_dashboard,
    plot_joint_contour,
    plot_joint_probability_change_heatmap,
    plot_joint_probability_heatmap,
    plot_linear_combination_distribution,
)
from RVUtils.ImpliedDistribution.plotting import (
    plot_distribution_change,
    plot_gaussian_mixture,
    plot_rnd_comparison,
    plot_rnd_density,
    plot_scenario_probabilities,
    plot_scenario_weights_bar,
    plot_scenario_weights_timeseries,
    plot_snapshot_dashboard,
    plot_strip_distribution_change,
    plot_sfr_smile,
    plot_sabr_smiles,
)

__all__ = [
    "SFRImpliedDistribution",
    "AnnotatedResult",
    "FedScenarioConfig",
    "FOMCPathState",
    "FOMCPathStateConfig",
    "ScenarioDefinition",
    "RNDInput",
    "BreedenLitzenbergerResult",
    "GaussianMixtureResult",
    "ImpliedDistributionSnapshot",
    "JointContractFitDiagnostics",
    "JointDistributionSnapshot",
    "JointDistributionComparison",
    "StripComparisonResult",
    "ViewMetadata",
    "STRIP_PRESETS",
    "resolve_strip_symbols",
    "plot_distribution_change",
    "plot_rnd_density",
    "plot_scenario_probabilities",
    "plot_gaussian_mixture",
    "plot_scenario_weights_bar",
    "plot_scenario_weights_timeseries",
    "plot_rnd_comparison",
    "plot_snapshot_dashboard",
    "plot_strip_distribution_change",
    "plot_joint_probability_heatmap",
    "plot_joint_probability_change_heatmap",
    "plot_conditional_distribution",
    "plot_linear_combination_distribution",
    "plot_empirical_copula",
    "plot_joint_contour",
    "plot_joint_comparison_dashboard",
    "plot_sfr_smile",
    "plot_sabr_smiles",
]
