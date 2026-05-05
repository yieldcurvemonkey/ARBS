"""Live smoke test for the SR3-vs-ZQ distribution-comparison screener.

Marked ``@pytest.mark.live`` because it hits Barchart for ZQ + SABR.
Run explicitly with::

    conda run -n stir pytest tests/test_sr3_zq_distribution_screener_smoke.py -m live -q
"""

from __future__ import annotations

import datetime

import pytest


@pytest.mark.live
def test_smoke_2026_05_04_pipeline_produces_at_least_one_record():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig,
        build_snapshot,
    )

    cfg = DistributionScreenerConfig(
        sr3_contracts=("SFRU26",),  # one contract for fast smoke
        optimize_lambda=False,        # skip λ optimization for speed
    )
    snap = build_snapshot(cfg, as_of=datetime.date(2026, 5, 4))
    if not snap.records:
        pytest.skip(f"Live data unavailable; warnings={snap.run_warnings[:3]}")

    rec = snap.records[0]
    assert rec.sr3_contract == "SFRU26"
    assert rec.n_meetings_in_period > 0
    assert rec.sr3_total_var_bp2 > 0
    # Stability flag is one of the documented values
    assert rec.stability_flag in {
        "stable", "unstable_smoothing", "unstable_order",
        "mass_violation", "negative_density", "parity_violation",
        "stale_reference_quarter",
    }
    # Regime is a known bucket
    from RVUtils.SR3ZQDistributionScreener import RegimeBucket
    assert rec.regime_bucket in set(RegimeBucket)
