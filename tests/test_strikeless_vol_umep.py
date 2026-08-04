import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.panels import umep_panel


def test_umep_panel_wraps_the_existing_tfp_history(monkeypatch):
    fake = pd.DataFrame(
        {
            "tfp": [2.0, 4.3],
            "zds": [-10.0, -12.0],
            "slope": [-2.0, -4.3],
            "r_squared": [0.9, 0.95],
            "mmss_30Y": [60.0, 74.6],
        },
        index=pd.DatetimeIndex(["2024-02-01", "2026-02-01"]),
    )
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: fake)

    out = umep_panel(dt.date(2024, 1, 1), dt.date(2026, 2, 1))

    assert "umep_bp_per_year" in out.columns
    assert out["umep_bp_per_year"].tolist() == [2.0, 4.3]
    assert out["zds_bp"].tolist() == [-10.0, -12.0]


def test_umep_panel_is_empty_safe(monkeypatch):
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: pd.DataFrame())
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2024, 2, 1))
    assert out.empty


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.db
def test_real_umep_rises_over_the_2024_2026_window_and_sign_is_recorded():
    """Dallas Fed WP 2613: the funding premium roughly doubled by Feb 2026."""
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2026, 8, 3))
    assert len(out) > 300
    early = out["umep_bp_per_year"].head(60).mean()
    late = out["umep_bp_per_year"].tail(60).mean()
    assert np.isfinite(early) and np.isfinite(late)
    # record the observed direction; the assertion is that it is measurable and
    # monotone in the published direction, not that it hits a target value
    assert late > early
