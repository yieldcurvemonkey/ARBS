"""Execution-vs-Event timestamp integration — Phase 3 tests.

Verifies analytics bucket on the original-execution anchor (CLAUDE.md
contract) rather than raw execution, via the trade_tape call sites. Uses a
frame where original and execution timestamps diverge so the anchor choice is
observable; existing fixtures (original == execution) already cover the
back-compat no-op case.
"""

import pandas as pd

from SDRUtils.analytics.trade_tape import TradeTape


def test_clustering_uses_original_execution_anchor():
    # Two trades 30 minutes apart in EXECUTION time (clearing-accept times)
    # but only 30 seconds apart in ORIGINAL execution (their shared alpha
    # struck seconds apart). With a 120s cluster gap, the correct economic
    # answer is one cluster — achievable only by bucketing on the original
    # anchor.
    df = pd.DataFrame({
        "trade_id": ["X1", "X2"],
        "execution_timestamp": pd.to_datetime(
            ["2026-03-11T09:00:00Z", "2026-03-11T09:30:00Z"], utc=True
        ),
        "original_execution_timestamp": pd.to_datetime(
            ["2026-03-09T14:00:00Z", "2026-03-09T14:00:30Z"], utc=True
        ),
    })
    out = TradeTape(df, cluster_gap_seconds=120)._enrich_rv(df.copy())
    assert out["cluster_id"].iloc[0] == out["cluster_id"].iloc[1]


def test_clustering_falls_back_to_execution_when_no_anchor():
    # No original_execution_timestamp column -> falls back to execution; the
    # two trades are 30 minutes apart -> distinct clusters.
    df = pd.DataFrame({
        "trade_id": ["Y1", "Y2"],
        "execution_timestamp": pd.to_datetime(
            ["2026-03-11T09:00:00Z", "2026-03-11T09:30:00Z"], utc=True
        ),
    })
    out = TradeTape(df, cluster_gap_seconds=120)._enrich_rv(df.copy())
    assert out["cluster_id"].iloc[0] != out["cluster_id"].iloc[1]
