import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.panels import umep_panel


def test_umep_panel_wraps_the_existing_tfp_history(monkeypatch):
    # dur_* columns are deliberately monotonic (non-decreasing with tenor) --
    # this test exercises the rename/passthrough behavior, not the
    # duration-monotonicity filter (see
    # test_umep_panel_excludes_degenerate_fit_rows for that).
    fake = pd.DataFrame(
        {
            "tfp": [2.0, 4.3],
            "zds": [-10.0, -12.0],
            "slope": [-2.0, -4.3],
            "r_squared": [0.97, 0.98],
            "mmss_30Y": [60.0, 74.6],
            "dur_2Y": [1.88, 1.89],
            "dur_3Y": [2.74, 2.75],
            "dur_5Y": [4.44, 4.45],
            "dur_7Y": [5.96, 5.97],
            "dur_10Y": [7.86, 7.87],
            "dur_30Y": [15.24, 15.30],
        },
        index=pd.DatetimeIndex(["2024-02-01", "2026-02-01"]),
    )
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: fake)

    out = umep_panel(dt.date(2024, 1, 1), dt.date(2026, 2, 1))

    assert "umep_bp_per_year" in out.columns
    assert out["umep_bp_per_year"].tolist() == [2.0, 4.3]
    assert out["zds_bp"].tolist() == [-10.0, -12.0]
    # r_squared is kept in the output as a diagnostic column, unfiltered
    assert out["r_squared"].tolist() == [0.97, 0.98]
    assert out.attrs["umep_excluded_degenerate_days"] == 0


def test_umep_panel_is_empty_safe(monkeypatch):
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: pd.DataFrame())
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2024, 2, 1))
    assert out.empty
    # the exclusion-count key must be present on every return path, not just
    # the normal one -- a caller checking out.attrs[...] should never KeyError
    assert out.attrs["umep_excluded_degenerate_days"] == 0


def test_umep_panel_excludes_degenerate_fit_rows(monkeypatch, caplog):
    """A row whose per-tenor modified duration is not non-decreasing with
    tenor must be dropped, logged (naming the inverted pair and both
    duration values), and counted -- not silently returned with an absurd
    umep_bp_per_year. Fixture values are the real 2026-07-08/09/14 numbers
    from the Task 6 fix report's diagnosis: 2026-07-09's dur_3Y (0.0592) is
    above its dur_5Y (0.0257), a physically impossible inversion for
    on-the-run Treasuries; 07-08 and 07-14 are real, duration-monotonic days.
    """
    fake = pd.DataFrame(
        {
            "tfp": [4.2255, -3_697_683.0, 4.3841],
            "zds": [-8.0, -467503.4, -9.0],
            "slope": [-4.2255, 3_697_683.0, -4.3841],
            "r_squared": [0.9963, 0.931088, 0.9948],
            "mmss_30Y": [-73.5, -86913.1, -73.0],
            "dur_2Y": [1.877, 0.0259, 1.861],
            "dur_3Y": [2.730, 0.0592, 2.714],
            "dur_5Y": [4.447, 0.0257, 4.431],
            "dur_7Y": [5.966, 0.0257, 5.950],
            "dur_10Y": [7.863, 0.1075, 7.846],
            "dur_30Y": [15.240, 0.1075, 15.202],
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
    warnings = [rec.message for rec in caplog.records]
    assert any("2026-07-09" in msg and "duration_monotonicity" in msg for msg in warnings)
    # the log must name the actual inverted pair and both values, not just
    # flag "something is wrong" -- diagnosable from the log alone
    assert any("dur_3Y" in msg and "dur_5Y" in msg for msg in warnings)


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.db
def test_real_umep_rises_over_the_2024_2026_window_and_sign_is_recorded():
    """Dallas Fed WP 2613: the funding premium roughly doubled by Feb 2026.

    The panel is expected to be clean under umep_panel's duration-monotonicity
    guard: as of 2026-08-03, exactly 7 of 639 raw days (2026-07-09, 07-10,
    07-13, 07-17, 07-20, 07-24, 07-27) have a per-tenor modified duration that
    decreases with tenor and are excluded -- see the Task 6 fix report for the
    diagnosis and the verification that this matches the original
    (superseded) r_squared-floor rule's exclusions exactly.
    """
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2026, 8, 3))
    assert len(out) > 300
    assert out.attrs["umep_excluded_degenerate_days"] == 7
    # no residual degenerate blow-ups: every remaining row is well-conditioned
    assert out["umep_bp_per_year"].abs().max() < 100
    early = out["umep_bp_per_year"].head(60).mean()
    late = out["umep_bp_per_year"].tail(60).mean()
    assert np.isfinite(early) and np.isfinite(late)
    # record the observed direction; the assertion is that it is measurable and
    # monotone in the published direction, not that it hits a target value
    assert late > early
