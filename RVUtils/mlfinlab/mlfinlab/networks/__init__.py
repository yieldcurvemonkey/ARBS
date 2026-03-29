"""
Tools to visualise and filter networks of complex systems.
"""

from mlfinlab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "DashGraph": ("mlfinlab.networks.dash_graph", "DashGraph"),
        "PMFGDash": ("mlfinlab.networks.dash_graph", "PMFGDash"),
        "DualDashGraph": ("mlfinlab.networks.dual_dash_graph", "DualDashGraph"),
        "Graph": ("mlfinlab.networks.graph", "Graph"),
        "MST": ("mlfinlab.networks.mst", "MST"),
        "ALMST": ("mlfinlab.networks.almst", "ALMST"),
        "PMFG": ("mlfinlab.networks.pmfg", "PMFG"),
        "generate_mst_server": ("mlfinlab.networks.visualisations", "generate_mst_server"),
        "create_input_matrix": ("mlfinlab.networks.visualisations", "create_input_matrix"),
        "generate_almst_server": ("mlfinlab.networks.visualisations", "generate_almst_server"),
        "generate_mst_almst_comparison": ("mlfinlab.networks.visualisations", "generate_mst_almst_comparison"),
    },
)
