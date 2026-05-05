"""End-to-end smoke test for the STIR Asymmetric Screener.

Marked ``@pytest.mark.live`` because it hits live market data via MDP.
Run explicitly with::

    conda run -n stir pytest tests/test_stir_asym_screener_smoke.py -m live -q

Verifies that against the as_of below, at least one candidate surfaces
that resembles one of the spec §8 reference trades.
"""

from __future__ import annotations

import datetime

import pytest


@pytest.mark.live
def test_smoke_sfr_2026_04_28_wing_and_wide_vertical_surface_candidates():
    from RVUtils.STIRAsymmetricScreener import (
        ArchetypeType,
        ScreenerConfig,
        build_snapshot,
    )

    config = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        archetypes=(ArchetypeType.WING, ArchetypeType.WIDE_VERTICAL),
        dte_floor=30,
        dte_ceiling=200,
    )

    snap = build_snapshot(config, as_of=datetime.date(2026, 4, 28))
    if not snap.results:
        # Live data unavailable on this run — skip rather than fail the suite.
        pytest.skip(
            f"Live data unavailable on 2026-04-28; warnings={snap.run_warnings[:3]}"
        )

    df = snap.to_dataframe()

    # Spec §7 columns present
    expected_cols = {
        "structure_type",
        "underlying",
        "expiry_date",
        "asymmetry_ratio",
        "composite_score",
    }
    missing = expected_cols - set(df.columns)
    assert not missing, f"Missing columns: {missing}"

    # At least one candidate has valid composite score
    assert df["composite_score"].notna().any()

    # At least one wing or wide_vertical structure on a SOFR quarterly
    sfr_wings = df[
        df["underlying"].str.startswith("SFR")
        & df["structure_type"].isin(["wing", "wide_vertical"])
    ]
    assert (
        len(sfr_wings) >= 1
    ), f"Expected at least one SFR wing or wide vertical; got {len(sfr_wings)}"


@pytest.mark.live
def test_smoke_full_archetype_set_runs_without_error():
    """Run the screener with all 8 archetypes — confirms the pipeline doesn't
    crash on any structure-specific logic."""
    from RVUtils.STIRAsymmetricScreener import ScreenerConfig, build_snapshot

    config = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        dte_floor=30,
        dte_ceiling=120,
    )
    snap = build_snapshot(config, as_of=datetime.date(2026, 4, 28))
    # Whether or not any result passes the gates, the call must not raise.
    assert isinstance(snap.results, tuple)
