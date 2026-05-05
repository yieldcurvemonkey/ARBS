"""SR3 RND vs ZQ FedWatch tree distribution-comparison screener.

Daily screener that compares (a) the risk-neutral density implied by SR3
options on 3M SOFR futures (Breeden-Litzenberger via JPM Tech Appendix A)
against (b) the discrete probability tree implied by ZQ Fed Funds futures
via the CME FedWatch methodology, then surfaces residuals after a
calibrated SOFR-EFFR basis adjustment + day-weighted meeting-variance
decomposition.

Spec: ``docs/plans/2026-05-04-sr3-zq-distribution-screener.md`` (TBD).
Prototype validation: ``scripts/_sr3_zq_distribution_prototype_20260504.py``
+ extended backfill in ``scripts/_sr3_zq_extended_backfill.py``.

**Public entry point:**

    from RVUtils.SR3ZQDistributionScreener import build_snapshot, ScreenerConfig
    snap = build_snapshot(ScreenerConfig(), as_of=datetime.date(2026, 5, 4))
    df = snap.to_dataframe()  # one row per (contract, signal) pair

**Modules:**
    - ``_types``          dataclasses for config, FedWatch tree, signal records
    - ``_fedwatch``       ZQ-anchored binary-tree builder per CME methodology
    - ``_variance``       day-weighted meeting variance + decomposition
    - ``_signals``        the four trade signals (vol cone / skew / tail /
                          cross-quarter residual)
    - ``_regime``         calm/stress/pivot/hike classifier
    - ``_lambda_opt``     λ-grid optimizer for BL smoothing param
    - ``_output``         parquet + JSON sidecar persistence
    - ``screener``        ``build_snapshot`` orchestrator
"""

from RVUtils.SR3ZQDistributionScreener._types import (
    DistributionScreenerConfig,
    FedWatchTree,
    MeetingNode,
    MonthState,
    RegimeBucket,
    SignalRecord,
    TradeFlag,
    TradeFlagKind,
)
from RVUtils.SR3ZQDistributionScreener._fedwatch import build_fedwatch_tree
from RVUtils.SR3ZQDistributionScreener._variance import (
    day_weighted_meeting_variance_bp2,
    meeting_nodes_from_states,
)
from RVUtils.SR3ZQDistributionScreener._signals import compute_signals
from RVUtils.SR3ZQDistributionScreener._regime import classify_regime
from RVUtils.SR3ZQDistributionScreener._lambda_opt import (
    optimize_smoothing_lambda,
)
from RVUtils.SR3ZQDistributionScreener._output import (
    ScreenerSnapshot,
    snapshot_to_dataframe,
    write_snapshot,
)
from RVUtils.SR3ZQDistributionScreener.screener import build_snapshot

__all__ = [
    "DistributionScreenerConfig",
    "FedWatchTree",
    "MeetingNode",
    "MonthState",
    "RegimeBucket",
    "ScreenerSnapshot",
    "SignalRecord",
    "TradeFlag",
    "TradeFlagKind",
    "build_fedwatch_tree",
    "build_snapshot",
    "classify_regime",
    "compute_signals",
    "day_weighted_meeting_variance_bp2",
    "meeting_nodes_from_states",
    "optimize_smoothing_lambda",
    "snapshot_to_dataframe",
    "write_snapshot",
]
