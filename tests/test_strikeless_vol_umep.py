import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.panels import umep_panel


def test_umep_panel_wraps_the_existing_tfp_history(monkeypatch):
    # r_squared values are deliberately above the degenerate-fit floor
    # (_TFP_FIT_R_SQUARED_FLOOR = 0.955) -- this test exercises the rename/
    # passthrough behavior, not the filter (see
    # test_umep_panel_excludes_degenerate_fit_rows for that).
    fake = pd.DataFrame(
        {
            "tfp": [2.0, 4.3],
            "zds": [-10.0, -12.0],
            "slope": [-2.0, -4.3],
            "r_squared": [0.97, 0.98],
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
    assert out.attrs["umep_excluded_degenerate_days"] == 0


def test_umep_panel_is_empty_safe(monkeypatch):
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: pd.DataFrame())
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2024, 2, 1))
    assert out.empty


def test_umep_panel_excludes_degenerate_fit_rows(monkeypatch, caplog):
    """A row whose cross-sectional fit is near-degenerate (r_squared below the
    floor) must be dropped, logged, and counted -- not silently returned with
    an absurd umep_bp_per_year, per the Task 6 fix report's diagnosis (7/639
    real days with non-monotonic per-tenor durations and r_squared < 0.9520,
    versus >= 0.9618 on every clean day)."""
    fake = pd.DataFrame(
        {
            "tfp": [4.05, -3_697_683.0, 4.17],
            "zds": [-8.0, -467503.4, -9.0],
            "slope": [-4.05, 3_697_683.0, -4.17],
            "r_squared": [0.9963, 0.931088, 0.9945],
            "mmss_30Y": [-73.5, -86913.1, -73.0],
        },
        index=pd.DatetimeIndex(["2026-07-08", "2026-07-09", "2026-07-14"]),
    )
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: fake)

    with caplog.at_level("WARNING", logger="RVUtils.StrikelessVol.panels"):
        out = umep_panel(dt.date(2026, 7, 1), dt.date(2026, 7, 31))

    assert list(out.index.date) == [dt.date(2026, 7, 8), dt.date(2026, 7, 14)]
    assert out["umep_bp_per_year"].abs().max() < 100
    assert out.attrs["umep_excluded_degenerate_days"] == 1
    assert any("2026-07-09" in rec.message for rec in caplog.records)


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.db
def test_real_umep_rises_over_the_2024_2026_window_and_sign_is_recorded():
    """Dallas Fed WP 2613: the funding premium roughly doubled by Feb 2026.

    The panel is expected to be clean under umep_panel's degenerate-fit floor
    (_TFP_FIT_R_SQUARED_FLOOR = 0.955): as of 2026-08-03, 7 of 639 raw days
    (2026-07-09, 07-10, 07-13, 07-17, 07-20, 07-24, 07-27) fail it and are
    excluded -- see the Task 6 fix report for the diagnosis (non-monotonic
    per-tenor modified durations, r_squared < 0.9520 on all seven, every other
    day >= 0.9618).
    """
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2026, 8, 3))
    assert len(out) > 300
    # no residual degenerate blow-ups: every remaining row is a well-conditioned fit
    assert (out["r_squared"] >= 0.9).all()
    assert out["umep_bp_per_year"].abs().max() < 100
    early = out["umep_bp_per_year"].head(60).mean()
    late = out["umep_bp_per_year"].tail(60).mean()
    assert np.isfinite(early) and np.isfinite(late)
    # record the observed direction; the assertion is that it is measurable and
    # monotone in the published direction, not that it hits a target value
    assert late > early
