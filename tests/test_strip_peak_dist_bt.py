"""Tests for the implied-distribution mode divergence backtest."""
import datetime

import pytest

from RVUtils.StripPeak.distribution_backtest import build_mode_series


@pytest.mark.network
def test_build_mode_series_single_contract():
    """Build mode time series for SFRU26 over a short window (task-6 brief's
    Step-1 smoke test, verbatim dates/symbol). Strengthened from the brief's
    original ``len(modes) >= 1`` to an exact count -- both dates are known-good
    archived EOD settles (verified live; see task-6-report.md), so a silent
    single-date drop would be a real regression, not routine attrition.
    """
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    modes = build_mode_series(
        mdp,
        symbol="SFRU26",
        dates=[datetime.date(2026, 8, 20), datetime.date(2026, 8, 21)],
    )
    assert len(modes) == 2
    assert "mode_rate" in modes.columns
    assert "forward_rate" in modes.columns
    assert "gap_bp" in modes.columns

    # Not model-density fallback -- both dates have enough listed/OI-screened
    # strikes for the observed-premium (JPM) path.
    assert (modes["strike_source"] == "market_jpm").all()
    assert (modes["n_strikes"] > 10).all()


@pytest.mark.network
def test_build_mode_series_known_date_values():
    """Known-answer check for SFRU26 on 2026-08-21, cross-checked against
    Task 5's discrete butterfly grid (task-5-report.md: mode_yield=3.75,
    forward_yield=3.80, gap_bp=-5.0 on this exact date).

    The continuous BL mode lands at 3.7642% -- one Task-5 grid step (6.25bp)
    away from the discrete grid's 3.75%, and the BL density's value at 3.75%
    is 98.7% of its value at the true argmax (measured live; see
    task-6-report.md), i.e. a near-tie between adjacent grid cells rather than
    a sharp disagreement. `forward_rate` reproduces Task 5's `forward_yield`
    exactly (3.80) and `forward_residual_bp` is small (~-1.5bp), both signs of
    a well-calibrated fit on this liquid, near-dated contract -- contrast
    SFRU27 in test_build_mode_series_current_peak_contract below.
    """
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    modes = build_mode_series(mdp, symbol="SFRU26", dates=[datetime.date(2026, 8, 21)])
    assert len(modes) == 1
    row = modes.iloc[0]

    assert abs(row["mode_rate"] - 3.7642) < 0.01  # within 1bp
    assert abs(row["forward_rate"] - 3.80) < 0.001  # exact tie-out to Task 5's forward
    assert abs(row["gap_bp"] - (-3.577)) < 0.5
    assert row["strike_source"] == "market_jpm"
    assert row["n_strikes"] == 48
    # Well-calibrated fit: recovered mean reproduces the martingale forward to
    # within a couple of bp (contrast SFRU27's -12 to -18bp miss).
    assert abs(row["forward_residual_bp"]) < 5.0


@pytest.mark.network
def test_build_mode_series_current_peak_contract():
    """Task-6 deliverable: BL mode-vs-forward gap for SFRU27, the strip's
    current peak contract (same three dates and contract task-5-report.md
    used for its `mode_series` part (d): 2026-08-19/20/21).

    Task 5's discrete 6.25bp-body grid found the mode PINNED at exactly
    4.125% on all three dates (task-5-report.md part (d) table). This
    continuous BL variant does NOT reproduce that pin -- it lands at 3.99,
    4.06, 4.01 across the three dates (verified live; see task-6-report.md),
    7-11bp away and on the opposite side of the forward on two of the three
    dates. This is a real finding, not a bug in either variant: SFRU27 is
    ~13 months out with only 30 raw strikes surviving the OI/OTM screen (vs.
    48 for SFRU26), and Task 5's own report already flagged this contract's
    grid as thin (`sum(imp_prob)` 0.82-0.84 vs 2.00 for the front contract)
    and its 08-19 snapshot as a near-tie between two candidate modes. The BL
    density corroborates that: at each date the density near 4.125% is
    96-98% of the value at the true argmax (measured live) -- a broad, nearly
    flat plateau, not a sharp peak, so small methodology differences
    (discretization vs. spline smoothing/ghost wings) move the exact argmax
    by several bp without much density cost either way. `forward_residual_bp`
    (-12 to -18bp here, vs -1.5bp for SFRU26) is independent, cheap evidence
    the fit is on shakier ground for this contract -- the class docstring
    documents this as a diagnostic that "must be ~0", not an FYI.

    Net: use gap_bp from EITHER variant on SFRU27 as a rough, wide-error-bar
    read, not a precise number -- unlike SFRU26, where the two variants agree
    to ~1bp of each other. See task-6-report.md for the full comparison.
    """
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    dates = [datetime.date(2026, 8, 19), datetime.date(2026, 8, 20), datetime.date(2026, 8, 21)]
    series = build_mode_series(mdp, symbol="SFRU27", dates=dates)

    # No silent date drop-outs for this known-good window (same convention
    # vol_backtest.mode_series documents).
    assert len(series) == len(dates)
    assert list(series["as_of"]) == dates
    assert (series["symbol"] == "SFRU27").all()

    # Not a SABR-model fallback -- these are observed-premium densities, same
    # provenance as Task 5's grid (which reads listed/parity prices directly),
    # so the comparison below is apples-to-apples.
    assert (series["strike_source"] == "market_jpm").all()

    # Sanity range only, matching test_strip_peak_vol_bt.py's (2, 8) band --
    # SR3 rates across the whole strip sat in a 3-6% band throughout this study.
    assert (series["mode_rate"] > 2.0).all() and (series["mode_rate"] < 8.0).all()
    assert (series["forward_rate"] > 2.0).all() and (series["forward_rate"] < 8.0).all()

    # forward_rate exactly reproduces Task 5's forward_yield column
    # (task-5-report.md part (d)): 4.065, 4.070, 4.125.
    expected_forward = [4.065, 4.070, 4.125]
    for got, want in zip(series["forward_rate"], expected_forward):
        assert abs(got - want) < 0.001

    # The BL mode does NOT reproduce Task 5's 4.125 pin -- document the real
    # gap rather than asserting a false "close" claim (see docstring above).
    # Bound is loose (20bp) -- a regression guard against a materially
    # different divergence, not a precision claim.
    for mode_rate in series["mode_rate"]:
        assert abs(mode_rate - 4.125) < 0.20

    # Independent corroborating diagnostic for why: this fit's recovered mean
    # misses the martingale forward by double digits of bp on every date,
    # unlike SFRU26's ~1.5bp miss (test_build_mode_series_known_date_values).
    assert (series["forward_residual_bp"].abs() > 5.0).all()
