"""Cross-currency basis relative-value book, ported from jpm_pfin/RVPF.

Self-contained: nothing here imports from :mod:`BT.gss_fly`. The only shared dependency is
:mod:`RVUtils.PortfolioOpt`, which is generic infrastructure rather than strategy code.

The instrument is a forward-starting cross-currency basis swap. ARBS quotes it directly (Citi's
``RATES.XCCY_OIS_SWAP`` carries a full forward x tenor grid), so the multi-curve bootstrap the
original hand-rolled is not reproduced -- ``MDP/CitiVelocityExcel/xccy`` already does it properly
in both rateslib and QuantLib.
"""

from BT.xccy_rv.config import (
    DEFAULT_PAIRS,
    DEFAULT_POINTS,
    BacktestConfig,
    OptimizerConfig,
    SignalConfig,
    XccyConfig,
)
from BT.xccy_rv.data import (
    BankedRVPFSource,
    CitiXccySource,
    XccyPanel,
    XccySource,
    xccy_basis_tag,
)
from BT.xccy_rv.product import (
    PRODUCT,
    XccyBasisLeg,
    XccyBasisQuery,
    XccyBasisStructure,
    XccyBasisValue,
    XccyPanelMDP,
)
from BT.xccy_rv.signals import build_signals, clip_outliers, combine_alpha, realized_vol

__all__ = [
    "XccyConfig", "SignalConfig", "OptimizerConfig", "BacktestConfig",
    "DEFAULT_PAIRS", "DEFAULT_POINTS",
    "XccyPanel", "XccySource", "BankedRVPFSource", "CitiXccySource", "xccy_basis_tag",
    "build_signals", "combine_alpha", "clip_outliers", "realized_vol",
    "XccyBasisQuery", "XccyBasisValue", "XccyBasisStructure", "XccyBasisLeg",
    "XccyPanelMDP", "PRODUCT",
]


def __getattr__(name):
    if name in {"run_panel_backtest", "run_qdb_backtest", "PanelResult", "QDBResult", "information_ratio"}:
        from BT.xccy_rv import backtest as _bt
        return getattr(_bt, name)
    if name in {"XccyAllocator", "build_xccy_trigger", "no_trade_band_step",
                "XccyRebalanceAction", "XccyUnwindAction"}:
        from BT.xccy_rv import strategy as _st
        return getattr(_st, name)
    raise AttributeError(name)
