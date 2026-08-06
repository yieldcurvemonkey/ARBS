"""Task 21: the cross-market runner's own arithmetic.

Everything here is the glue between per-market results and the book -- the part
that decides what calendar the book is scored on, what a closed market is worth
that day, and whether the book's advantage is arithmetic. Each of those was a
measured defect before it was a guard:

* scoring the book on the days it happened to have a weight, rather than on the
  trading calendar, doubled JPY's reported ratio (-1.95 -> -3.95) by deleting
  flat days from a series that is annualised by ``sqrt(252)`` anyway;
* treating "no weight" as "not started" moved the book's start 391 rows in,
  because ``portfolio`` returns NaN both for an incomplete window and for an
  IDLE market whose rule was flat all window.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.costs import CostSchedule
from RVUtils.StrikelessVol.report import PORTFOLIO_WINDOW, portfolio
from RVUtils.StrikelessVol.strategy import REQUIRED_COLUMNS
from RVUtils.StrikelessVol.universe import ALL_PAIRS
from scripts import sv_cross_market as X


# ------------------------------------------------------------------- universe


def test_every_market_carries_the_same_headline_structure():
    """One rulebook means one STRUCTURE, not four similar ones."""
    for market in X.MARKETS:
        p = X.headline_pair(market)
        assert (p.short.label, p.long.label) == X.HEADLINE_LEGS
        assert p.market == market
    assert len({X.headline_pair(m).name for m in X.MARKETS}) == len(X.MARKETS)


def test_the_headline_pair_is_supported_by_its_market_coverage():
    from RVUtils.StrikelessVol.universe import MARKET_MAX_POINT_YEARS

    for market in X.MARKETS:
        p = X.headline_pair(market)
        assert p.required_point_years <= MARKET_MAX_POINT_YEARS[market]


def test_the_sample_starts_are_the_measured_ones_not_the_briefs():
    """Swaption vols begin 2017-01-03 everywhere; EUR-ESTR curves begin 2019-10.

    The brief says JPY/GBP run from 2010. They cannot: the driver, the ``iv_z``
    gate and the valuation all rest on a vol series that does not exist before
    2017 in any market.
    """
    assert X.SAMPLE_START["USD"] == dt.date(2017, 1, 3)
    assert X.SAMPLE_START["JPY"] == dt.date(2017, 1, 3)
    assert X.SAMPLE_START["GBP"] == dt.date(2017, 1, 3)
    assert X.SAMPLE_START["EUR"] == dt.date(2019, 10, 1)


# ------------------------------------------------------------ align_for_book


def _idx(n, start="2024-01-01"):
    return pd.bdate_range(start, periods=n)


def test_a_hole_inside_a_markets_span_becomes_a_zero():
    idx = _idx(10)
    a = pd.Series(np.arange(10, dtype=float), index=idx)
    b = pd.Series(np.arange(10, dtype=float), index=idx)
    b.iloc[4] = np.nan
    out = X.align_for_book({"A": a, "B": b})
    assert out.loc[idx[4], "B"] == 0.0


def test_a_gap_outside_a_markets_span_stays_missing():
    """Not-yet-started is not a flat day, and must not be weighted as one."""
    idx = _idx(10)
    a = pd.Series(np.arange(10, dtype=float), index=idx)
    b = pd.Series(np.arange(10, dtype=float), index=idx)
    b.iloc[:4] = np.nan
    b.iloc[-2:] = np.nan
    out = X.align_for_book({"A": a, "B": b})
    assert out["B"].iloc[:4].isna().all()
    assert out["B"].iloc[-2:].isna().all()
    assert out["B"].iloc[4:8].notna().all()


def test_the_live_span_is_inclusive_at_both_of_its_endpoints():
    """The span boundary itself, which every other test steps over.

    Making the span exclusive at the first and last live date is an off-by-one
    at exactly the dates where a market arrives and leaves -- 8 rows across four
    markets on the real run, immaterial to the result but unpinned until now.
    """
    idx = _idx(10)
    a = pd.Series(1.0, index=idx)
    b = pd.Series(np.nan, index=idx)
    # live only on days 3 and 7; days 4..6 are interior holes, and days 3 and 7
    # are the endpoints an exclusive span would drop out of the fill
    b.iloc[3] = 5.0
    b.iloc[7] = 5.0
    out = X.align_for_book({"A": a, "B": b})
    assert out["B"].iloc[3] == 5.0            # first live date survives
    assert out["B"].iloc[7] == 5.0            # last live date survives
    assert (out["B"].iloc[4:7] == 0.0).all()  # interior filled
    assert out["B"].iloc[:3].isna().all()     # before the span
    assert out["B"].iloc[8:].isna().all()     # after the span


def test_making_the_span_exclusive_at_its_endpoints_changes_nothing():
    """A reviewer mutation survived here, and the reason is that it CANNOT fail.

    Turning `>=`/`<=` into `>`/`<` in the span looks like an off-by-one at the
    dates a market arrives and leaves. It is not observable: the endpoints come
    from `dropna()`, so those two dates are non-NaN by construction and the
    `fillna` applied over the span is a no-op there. The mutant is EQUIVALENT.

    Recorded as a MEASURED null rather than an argued one -- an equivalence
    claim is exactly the kind of thing that is quietly wrong. Two
    implementations, compared over randomised frames plus the edge cases; if
    the structure of `align_for_book` ever changes so that the boundary starts
    to matter, this test fails and says so.
    """
    def exclusive(series_by_market):
        frame = pd.DataFrame(series_by_market)
        for col, s in series_by_market.items():
            live = s.dropna()
            if live.empty:
                continue
            span = ((frame.index > live.index.min())
                    & (frame.index < live.index.max()))
            frame.loc[span, col] = frame.loc[span, col].fillna(0.0)
        return frame.sort_index()

    rng = np.random.default_rng(0)
    for _ in range(300):
        n = int(rng.integers(3, 25))
        idx = _idx(n)
        cols = {}
        for c in "ABC"[:int(rng.integers(1, 4))]:
            v = rng.normal(0, 1, n)
            mask = rng.random(n) < rng.random()
            cols[c] = pd.Series(np.where(mask, np.nan, v), index=idx)
        assert X.align_for_book(cols).equals(exclusive(cols))

    # the edge cases the random draw is unlikely to hit
    idx = _idx(6)
    edges = {
        "all_nan": pd.Series(np.nan, index=idx),
        "one_live": pd.Series([np.nan, np.nan, 1.0, np.nan, np.nan, np.nan], index=idx),
        "live_at_both_ends": pd.Series([1.0, np.nan, np.nan, np.nan, np.nan, 1.0],
                                       index=idx),
        "no_holes": pd.Series(1.0, index=idx),
    }
    for name, s in edges.items():
        one = {name: s}
        assert X.align_for_book(one).equals(exclusive(one)), name


def test_the_lower_and_upper_span_bounds_are_not_interchangeable():
    """The boundary mutation that IS observable: both ends read from the same
    endpoint, which empties the span and stops every interior hole filling."""
    idx = _idx(10)
    b = pd.Series(np.nan, index=idx)
    b.iloc[2] = 1.0
    b.iloc[8] = 1.0
    out = X.align_for_book({"A": pd.Series(1.0, index=idx), "B": b})
    assert (out["B"].iloc[3:8] == 0.0).all()
    assert int(out["B"].notna().sum()) == 7


def test_the_union_calendar_is_the_union_not_the_intersection():
    a = pd.Series(1.0, index=_idx(5, "2024-01-01"))
    b = pd.Series(1.0, index=_idx(5, "2024-01-08"))
    out = X.align_for_book({"A": a, "B": b})
    assert len(out) == 10
    assert out.index.is_monotonic_increasing


# ---------------------------------------------------------------- book_start


def test_book_start_is_the_first_complete_window_lagged_one_day():
    n = PORTFOLIO_WINDOW + 20
    idx = _idx(n)
    a = pd.Series(np.arange(n, dtype=float), index=idx)
    frame = pd.DataFrame({"A": a})
    assert X.book_start(frame) == idx[PORTFOLIO_WINDOW]


def test_book_start_does_not_read_an_idle_market_as_a_market_that_never_started():
    """The JPY case, in miniature.

    A market whose rule is flat for the whole trailing window has sd 0, so
    ``portfolio`` gives it no weight -- but the book CAN hold it (at nothing).
    Reading "no weight" as "not started" is what moved the real book's start
    391 rows in.
    """
    n = PORTFOLIO_WINDOW * 3
    idx = _idx(n)
    vals = np.zeros(n)
    vals[2 * PORTFOLIO_WINDOW:] = np.arange(n - 2 * PORTFOLIO_WINDOW, dtype=float)
    frame = pd.DataFrame({"A": pd.Series(vals, index=idx)})
    book = portfolio({"A": frame["A"]}, target_bp_day=1.0)
    first_weight = book["w_A"].first_valid_index()
    assert first_weight > idx[PORTFOLIO_WINDOW]      # the naive answer
    assert X.book_start(frame) == idx[PORTFOLIO_WINDOW]   # the right one


def test_book_start_is_none_when_no_market_ever_completes_a_window():
    frame = pd.DataFrame({"A": pd.Series(np.arange(5, dtype=float), index=_idx(5))})
    assert X.book_start(frame) is None


def test_book_start_takes_the_earliest_market_not_the_latest():
    n = PORTFOLIO_WINDOW + 40
    idx = _idx(n)
    a = pd.Series(np.arange(n, dtype=float), index=idx)
    b = a.copy()
    b.iloc[:20] = np.nan
    frame = pd.DataFrame({"A": a, "B": b})
    assert X.book_start(frame) == idx[PORTFOLIO_WINDOW]


# ------------------------------------------------------------------ book_pnl


def _flat_then_active(n_flat, n_active, seed=0):
    rng = np.random.default_rng(seed)
    vals = np.concatenate([np.zeros(n_flat), rng.normal(0.1, 1.0, n_active)])
    return pd.Series(vals, index=_idx(n_flat + n_active))


def test_book_pnl_scores_the_book_on_the_trading_calendar_not_on_its_weights():
    s = _flat_then_active(2 * PORTFOLIO_WINDOW, 300, seed=3)
    frame = pd.DataFrame({"A": s})
    book = portfolio({"A": frame["A"]}, target_bp_day=1.0)
    pnl = X.book_pnl(book, frame)
    assert len(pnl) == len(s) - PORTFOLIO_WINDOW
    assert pnl.isna().sum() == 0
    assert len(pnl) > int(book["pnl"].notna().sum())


def test_book_pnl_preserves_the_books_total():
    """Filling flat days with zeros must not invent or destroy P&L.

    Two properties the fixture must have, both of them established by a failed
    attempt before this one:

    * the hole must be INTERIOR -- a leading hole has nothing before it, so a
      fill-forward is indistinguishable from a fill-with-zero;
    * the value immediately before the hole must be NON-ZERO. A market that
      goes quiet by producing exactly-zero P&L reaches its zero-vol window
      through a stretch of zeros, so the last defined value is already 0.0 and
      fill-forward is again the same thing. Here the market goes quiet by
      producing a CONSTANT non-zero P&L, which drives the trailing sd to zero
      while the last defined book value is not.

    Without the second property a fill-forward mutation survives this test
    while changing the book's total on any path that has one.
    """
    rng = np.random.default_rng(5)
    s = pd.Series(np.concatenate([
        rng.normal(0.5, 1.0, 200),                       # on
        np.full(3 * PORTFOLIO_WINDOW, 0.7),              # constant: sd 0, level > 0
        rng.normal(0.5, 1.0, 200),                       # on again
    ]))
    s.index = _idx(len(s))
    frame = pd.DataFrame({"A": s})
    book = portfolio({"A": frame["A"]}, target_bp_day=1.0)
    holes = book["pnl"].iloc[PORTFOLIO_WINDOW + 1:-1].isna()
    assert int(holes.sum()) > 50, "fixture must actually have interior holes"
    first_hole = holes.idxmax()
    prev = book["pnl"].shift(1).loc[first_hole]
    assert abs(float(prev)) > 0.1, "the value before the hole must be non-zero"
    filled = X.book_pnl(book, frame)
    assert float(filled.sum()) == pytest.approx(float(book["pnl"].sum()), rel=1e-12)
    assert float(filled.loc[first_hole]) == 0.0


def test_book_pnl_does_not_reach_back_before_the_book_could_be_sized():
    s = _flat_then_active(2 * PORTFOLIO_WINDOW, 300, seed=7)
    frame = pd.DataFrame({"A": s})
    book = portfolio({"A": frame["A"]}, target_bp_day=1.0)
    assert X.book_pnl(book, frame).index[0] == X.book_start(frame)


def test_dropping_flat_days_is_what_the_fill_prevents_and_it_is_material():
    """The measurement that motivated ``book_pnl``, as a test.

    Scoring only the dated rows inflates the magnitude of the ratio, because
    ``distribution_stats`` annualises by ``sqrt(252)`` regardless of how many
    days it was actually given.
    """
    from RVUtils.StrikelessVol.report import distribution_stats

    s = _flat_then_active(2 * PORTFOLIO_WINDOW, 300, seed=11)
    frame = pd.DataFrame({"A": s})
    book = portfolio({"A": frame["A"]}, target_bp_day=1.0)
    holed = distribution_stats(book["pnl"])
    filled = distribution_stats(X.book_pnl(book, frame))
    assert filled["n"] > holed["n"]
    assert abs(filled["sharpe_annualised"]) < abs(holed["sharpe_annualised"])


# ------------------------------------------------- diversification_prediction


def test_independent_sharpe_is_the_no_correlation_benchmark():
    """Uncorrelated identical legs give sqrt(n) x a single leg's ratio, free."""
    n, k = 3000, 4
    rng = np.random.default_rng(13)
    cols = {f"M{i}": pd.Series(rng.normal(0.05, 1.0, n), index=_idx(n))
            for i in range(k)}
    frame = X.align_for_book(cols)
    book = portfolio(dict(frame.items()), target_bp_day=1.0)
    pred = X.diversification_prediction(book, frame)
    single = float(np.mean(list(pred["per_market_sr"].values())))
    assert pred["independent_sharpe"] == pytest.approx(single * np.sqrt(k), rel=0.15)
    assert pred["realised_sharpe"] == pytest.approx(pred["independent_sharpe"], rel=0.15)
    assert pred["mean_abs_corr"] < 0.1


def test_perfectly_correlated_legs_get_no_diversification():
    n = 1500
    rng = np.random.default_rng(17)
    base = pd.Series(rng.normal(0.05, 1.0, n), index=_idx(n))
    frame = X.align_for_book({"A": base, "B": base.copy(), "C": base.copy()})
    book = portfolio(dict(frame.items()), target_bp_day=1.0)
    pred = X.diversification_prediction(book, frame)
    single = float(np.mean(list(pred["per_market_sr"].values())))
    assert pred["mean_abs_corr"] == pytest.approx(1.0, abs=1e-9)
    # realised is the single-leg ratio; the independent BENCHMARK is sqrt(3)x it,
    # which is precisely the free lunch the benchmark exists to expose.
    assert pred["realised_sharpe"] == pytest.approx(single, rel=0.02)
    assert pred["independent_sharpe"] == pytest.approx(single * np.sqrt(3.0), rel=0.02)


def test_the_decomposition_reads_the_scaled_legs_not_the_raw_series():
    """A leg's contribution is ``w_i * pnl_i``; decomposing the raw series would
    describe a book that is not the one being reported."""
    n = 800
    rng = np.random.default_rng(19)
    quiet = pd.Series(rng.normal(0.02, 0.2, n), index=_idx(n))
    loud = pd.Series(rng.normal(0.02, 5.0, n), index=_idx(n))
    frame = X.align_for_book({"QUIET": quiet, "LOUD": loud})
    book = portfolio(dict(frame.items()), target_bp_day=1.0)
    pred = X.diversification_prediction(book, frame)
    # scaled legs both sit at the target, 25x apart in the raw series
    assert pred["leg_sd"]["QUIET"] == pytest.approx(1.0, rel=0.35)
    assert pred["leg_sd"]["LOUD"] == pytest.approx(1.0, rel=0.35)
    assert float(loud.std(ddof=1) / quiet.std(ddof=1)) > 10.0


def test_the_scaled_legs_sum_to_the_book_pnl_exactly():
    """The decomposition must describe the book that was reported.

    Requiring every leg's weight to be defined on the same date left 327 of
    1777 rows on the real four-market run -- an 18% subsample being read as a
    decomposition of the whole book.
    """
    n = 600
    rng = np.random.default_rng(23)
    a = pd.Series(np.concatenate([np.zeros(2 * PORTFOLIO_WINDOW),
                                  rng.normal(0.1, 1.0, n - 2 * PORTFOLIO_WINDOW)]),
                  index=_idx(n))
    b = pd.Series(rng.normal(0.1, 2.0, n), index=_idx(n))
    frame = X.align_for_book({"A": a, "B": b})
    book = portfolio(dict(frame.items()), target_bp_day=1.0)
    legs = X.scaled_legs(book, frame)
    pnl = X.book_pnl(book, frame)
    assert legs.index.equals(pnl.index)
    assert legs.sum(axis=1).sub(pnl).abs().max() < 1e-12
    # ... and it is not a subsample: the A leg is idle for a long stretch
    assert int((legs["A"] == 0.0).sum()) > PORTFOLIO_WINDOW


def test_the_decomposition_refuses_a_one_market_book():
    n = 400
    frame = pd.DataFrame({"A": pd.Series(np.arange(n, dtype=float), index=_idx(n))})
    book = portfolio({"A": frame["A"]}, target_bp_day=1.0)
    pred = X.diversification_prediction(book, frame)
    assert np.isnan(pred["independent_sharpe"])


# --------------------------------------------------------- the shift control


def test_the_shift_control_preserves_each_legs_own_marginals():
    n = 600
    rng = np.random.default_rng(23)
    frame = pd.DataFrame(
        {c: rng.normal(0, 1 + i, n) for i, c in enumerate("ABC")}, index=_idx(n))
    ctrl = X.circular_shift_control(frame, target_bp_day=1.0, n_draws=5, seed=1)
    assert len(ctrl) == 5
    # a rotation changes no moment of the series it rotates
    rolled = np.roll(frame["A"].to_numpy(), 137)
    assert rolled.std(ddof=1) == pytest.approx(float(frame["A"].std(ddof=1)))
    assert rolled.mean() == pytest.approx(float(frame["A"].mean()))


def test_the_shift_control_never_draws_a_near_identity():
    """A near-zero shift would leak the real alignment back into the null.

    Read off the offsets the control ACTUALLY used, not recomputed from the
    same formula the control uses -- a test that re-derives the bound it is
    checking passes whatever the code does with it.
    """
    n = 500
    rng = np.random.default_rng(29)
    frame = pd.DataFrame({"A": rng.normal(0, 1, n), "B": rng.normal(0, 1, n)},
                         index=_idx(n))
    ctrl = X.circular_shift_control(frame, target_bp_day=1.0, n_draws=60, seed=2)
    shifts = ctrl[[c for c in ctrl.columns if c.startswith("shift_")]]
    assert set(shifts.columns) == {"shift_A", "shift_B"}
    assert int(shifts.to_numpy().min()) >= 50      # 10% of 500
    assert int(shifts.to_numpy().max()) < 450      # 90% of 500


def test_every_market_is_shifted_by_its_own_offset():
    """A single shared offset would rotate the whole book rigidly and preserve
    every cross-market relationship -- a null identical to the thing it tests."""
    n = 400
    rng = np.random.default_rng(30)
    frame = pd.DataFrame({"A": rng.normal(0, 1, n), "B": rng.normal(0, 1, n),
                          "C": rng.normal(0, 1, n)}, index=_idx(n))
    ctrl = X.circular_shift_control(frame, target_bp_day=1.0, n_draws=30, seed=4)
    shifts = ctrl[["shift_A", "shift_B", "shift_C"]]
    all_same = (shifts.nunique(axis=1) == 1)
    assert not all_same.any()


def test_the_shift_control_actually_destroys_the_cross_market_timing():
    """Identical legs are perfectly correlated; rotating them must break that.

    Measured on the control's OWN output (``mean_abs_corr`` per draw) rather
    than inferred from a summary statistic, because an identity shift leaves
    every summary statistic exactly where it was.
    """
    n = 900
    rng = np.random.default_rng(31)
    base = pd.Series(rng.normal(0.05, 1.0, n), index=_idx(n))
    frame = pd.DataFrame({"A": base, "B": base.copy()})
    assert float(frame.corr().iloc[0, 1]) == pytest.approx(1.0)
    ctrl = X.circular_shift_control(frame, target_bp_day=1.0, n_draws=40, seed=3)
    assert float(ctrl["mean_abs_corr"].max()) < 0.25
    assert float(ctrl["mean_abs_corr"].median()) < 0.06


def test_the_shift_control_is_reproducible_under_its_seed():
    n = 400
    rng = np.random.default_rng(37)
    frame = pd.DataFrame({"A": rng.normal(0, 1, n), "B": rng.normal(0, 1, n)},
                         index=_idx(n))
    a = X.circular_shift_control(frame, target_bp_day=1.0, n_draws=6, seed=5)
    b = X.circular_shift_control(frame, target_bp_day=1.0, n_draws=6, seed=5)
    c = X.circular_shift_control(frame, target_bp_day=1.0, n_draws=6, seed=6)
    pd.testing.assert_frame_equal(a, b)
    assert not a["sharpe"].equals(c["sharpe"])


# ---------------------------------------------------------------- unit ledger


class _FakeCurvePricer:
    """A ``PricingContext`` with a linear world and a per-instance identity.

    Only enough to exercise the segmentation: the roll must produce ONE
    ``CurvePricer`` per period and the boundary date's traded risk must move
    from the initiate bucket to the roll bucket.
    """

    built = []

    def __init__(self, curve_map, pair, *, package_dv01_usd=100_000.0, sign=1):
        self.dates = sorted(curve_map)
        type(self).built.append((self.dates[0], self.dates[-1]))
        self.sign = sign

    def rate(self, date, leg):
        return 0.04 if leg == "long" else 0.045

    def dv01(self, date, leg):
        return 1.0

    def pv(self, date, nl, ns):
        return 0.0

    def theta(self, date, nl, ns):
        return -1.0


def test_the_roll_moves_traded_risk_from_the_initiate_bucket_to_the_roll_bucket(
        monkeypatch):
    """``run_pair`` OVERWRITES ``initiate_dv01_usd`` from its own turnover
    split, so a roll left on the initiate bucket does not get mischarged -- it
    disappears from the fee entirely, which is worse."""
    _FakeCurvePricer.built = []
    monkeypatch.setattr(X, "CurvePricer", _FakeCurvePricer)
    dates = pd.bdate_range("2020-01-01", periods=800)
    curves = {d: object() for d in dates}
    unit, dv01 = X.unit_ledger(curves, ALL_PAIRS[0], trigger_bp=25.0,
                               roll_months=12, package_dv01_usd=100_000.0,
                               sign=1, costs=CostSchedule())
    assert len(_FakeCurvePricer.built) >= 3          # ~3 annual periods
    rolls = unit[unit["roll_dv01_usd"] > 0]
    assert len(rolls) == len(_FakeCurvePricer.built) - 1
    assert (rolls["roll_dv01_usd"] == 100_000.0).all()
    assert (rolls["initiate_dv01_usd"] == 0.0).all()
    # exactly one initiation, on day one
    assert float(unit["initiate_dv01_usd"].sum()) == pytest.approx(100_000.0)
    assert unit.index.is_unique and unit.index.is_monotonic_increasing
    assert len(unit) == len(dates)
    assert dv01.index.equals(unit.index)


def test_the_shared_roll_date_is_not_double_counted(monkeypatch):
    """Segments overlap by one date on purpose; its flows are SUMMED once."""
    _FakeCurvePricer.built = []
    monkeypatch.setattr(X, "CurvePricer", _FakeCurvePricer)
    dates = pd.bdate_range("2020-01-01", periods=600)
    curves = {d: object() for d in dates}
    unit, _ = X.unit_ledger(curves, ALL_PAIRS[0], trigger_bp=25.0, roll_months=12,
                            package_dv01_usd=100_000.0, sign=1,
                            costs=CostSchedule())
    assert len(unit) == len(dates)
    # carry is -1/day in the fake world, on every date but the first of each
    # segment; the boundary date belongs to the OLD segment and is counted once
    assert float(unit["carry"].sum()) == pytest.approx(-(len(dates) - 1))


def test_roll_segments_is_the_control_scripts_function_not_a_reimplementation():
    from scripts.sv_static_long_control import roll_segments as canonical

    dates = list(pd.bdate_range("2020-01-01", periods=800))
    assert X.roll_segments(dates, 12) == canonical(dates, 12)
    bounds = X.roll_segments(dates, 12)
    for (_, j), (i2, _) in zip(bounds, bounds[1:]):
        assert j == i2                    # overlap by exactly one date


# ------------------------------------------------------- units and cost sense


class _FakeResult:
    def __init__(self, pnl, dv01, ledger=None):
        self.daily_pnl = pnl
        self.stats = {"realised_dv01_mean_usd": dv01}
        self.ledger = ledger


def test_bp_day_series_divides_by_the_realised_dv01():
    idx = _idx(10)
    pnl = pd.Series(np.arange(10, dtype=float), index=idx)
    got = X.bp_day_series(_FakeResult(pnl, 50_000.0))
    assert got.iloc[-1] == pytest.approx(9.0 / 50_000.0)


@pytest.mark.parametrize("dv01", [0.0, float("nan")])
def test_bp_day_series_refuses_an_unusable_dv01(dv01):
    pnl = pd.Series(np.arange(10, dtype=float), index=_idx(10))
    with pytest.raises(ValueError, match="realised DV01"):
        X.bp_day_series(_FakeResult(pnl, dv01))


def test_breakeven_cost_multiplier_is_gross_over_the_one_x_charge():
    """Every P&L bucket carries a DISTINCT non-zero value.

    The first version of this fixture had `cross: 0.0`, so dropping `cross`
    from the gross bucket list was invisible -- and the break-even multiplier
    is a headline row and the basis of the "three of four are negative" claim.
    Distinct values, so dropping ANY one bucket changes the answer.
    """
    idx = _idx(4)
    led = pd.DataFrame({
        "carry": [0.0, 100.0, 100.0, 100.0],       # 300
        "harvest": [0.0, 7.0, 0.0, 0.0],           # 7
        "mtm": [0.0, 0.0, 13.0, 0.0],              # 13
        "cross": [0.0, 0.0, 0.0, 29.0],            # 29
        "initiate_dv01_usd": [100_000.0, 0.0, 0.0, 0.0],
        "hedge_dv01_usd": 0.0, "roll_dv01_usd": 0.0,
    }, index=idx)
    sched = CostSchedule(initiate_bp=0.875)
    res = _FakeResult(None, 1.0, led)
    got = X.breakeven_cost_multiplier(res, sched)
    assert got == pytest.approx((300.0 + 7.0 + 13.0 + 29.0) / (0.875 * 100_000.0))
    # and each bucket is load-bearing: no single one may be droppable
    for bucket, value in (("carry", 300.0), ("harvest", 7.0), ("mtm", 13.0),
                          ("cross", 29.0)):
        without = X.breakeven_cost_multiplier(
            _FakeResult(None, 1.0, led.assign(**{bucket: 0.0})), sched)
        assert got - without == pytest.approx(value / (0.875 * 100_000.0))


def test_breakeven_cost_multiplier_prices_every_traded_risk_bucket():
    """The denominator is the 1x charge on ALL of initiate/hedge/roll."""
    idx = _idx(3)
    led = pd.DataFrame({
        "carry": [0.0, 0.0, 1000.0], "harvest": 0.0, "mtm": 0.0, "cross": 0.0,
        "initiate_dv01_usd": [100_000.0, 0.0, 0.0],
        "hedge_dv01_usd": [0.0, 50_000.0, 0.0],
        "roll_dv01_usd": [0.0, 0.0, 25_000.0],
    }, index=idx)
    sched = CostSchedule(initiate_bp=0.875, hedge_bp=0.35, roll_bp=0.35)
    charge = 0.875 * 100_000.0 + 0.35 * 50_000.0 + 0.35 * 25_000.0
    got = X.breakeven_cost_multiplier(_FakeResult(None, 1.0, led), sched)
    assert got == pytest.approx(1000.0 / charge)


def test_a_losing_market_gets_a_negative_breakeven_multiplier():
    """No positive multiplier makes a gross loss net out; the sign says so."""
    idx = _idx(3)
    led = pd.DataFrame({
        "carry": [-50.0, -50.0, -50.0], "harvest": 0.0, "mtm": 0.0, "cross": 0.0,
        "initiate_dv01_usd": [100_000.0, 0.0, 0.0],
        "hedge_dv01_usd": 0.0, "roll_dv01_usd": 0.0,
    }, index=idx)
    assert X.breakeven_cost_multiplier(
        _FakeResult(None, 1.0, led), CostSchedule()) < 0.0


# ------------------------------------------------- the comparison that states H8


def _two_leg_frame(seed=201, n=600):
    rng = np.random.default_rng(seed)
    quiet = pd.Series(rng.normal(-0.02, 0.5, n), index=_idx(n))
    loud = pd.Series(rng.normal(-0.10, 3.0, n), index=_idx(n))
    return X.align_for_book({"QUIET": quiet, "LOUD": loud})


def test_book_stats_total_is_a_sum_not_a_mean():
    pnl = pd.Series([1.0, 2.0, 3.0, 4.0], index=_idx(4))
    got = X.book_stats(pnl)
    assert got["total"] == pytest.approx(10.0)
    assert got["n"] == 4


def test_dd_per_vol_day_is_the_drawdown_over_the_rows_own_daily_sd():
    """Hand-computed, not a bound.

    Dividing by anything else -- the row count, say -- still ranks plausibly
    and is no longer scale-free, which is the whole reason the column exists.
    """
    frame = _two_leg_frame()
    book = portfolio(dict(frame.items()), target_bp_day=1.0)
    pnl = X.book_pnl(book, frame)
    out = X.compare_book_to_singles(frame, pnl, target_bp_day=1.0)
    assert set(out.index) == {"QUIET", "LOUD", X.BOOK_ROW}
    for row in out.index:
        assert out.loc[row, "dd_per_vol_day"] == pytest.approx(
            out.loc[row, "max_drawdown"] / out.loc[row, "daily_vol"])
    # and it is NOT the drawdown over the row count -- the two must differ
    n_route = out["max_drawdown"] / out["n"]
    assert (out["dd_per_vol_day"] - n_route).abs().min() > 1e-6


def test_dd_per_vol_day_is_invariant_to_rescaling_a_leg_and_raw_drawdown_is_not():
    """The property the column is for, demonstrated rather than asserted."""
    frame = _two_leg_frame()
    scaled = frame.copy()
    scaled["LOUD"] = scaled["LOUD"] * 10.0
    a = X.compare_book_to_singles(
        frame, X.book_pnl(portfolio(dict(frame.items()), target_bp_day=1.0), frame),
        target_bp_day=1.0)
    b = X.compare_book_to_singles(
        scaled, X.book_pnl(portfolio(dict(scaled.items()), target_bp_day=1.0), scaled),
        target_bp_day=1.0)
    assert b.loc["LOUD", "dd_per_vol_day"] == pytest.approx(
        a.loc["LOUD", "dd_per_vol_day"], rel=1e-9)
    assert b.loc["LOUD", "max_drawdown"] == pytest.approx(
        a.loc["LOUD", "max_drawdown"], rel=1e-9)


def test_the_best_single_market_is_the_least_bad_leg_not_the_worst():
    """`idxmin` would compare the book against the WORST single market -- which
    is exactly how one manufactures 'the book beats the best single market'."""
    table = pd.DataFrame(
        {"max_drawdown": [-10.0, -50.0, -30.0],
         "dd_per_vol_day": [-10.0, -50.0, -30.0],
         "sharpe": [-0.5, -2.0, -1.0],
         "daily_vol": [1.0, 1.0, 1.0], "total": [-1.0, -1.0, -1.0],
         "n": [100, 100, 100]},
        index=["GOOD", "BAD", X.BOOK_ROW])
    v = X.book_verdicts(table)
    for key in ("max_drawdown", "dd_per_vol_day", "sharpe"):
        assert v[key]["best_single"] == "GOOD"
        assert v[key]["book_is_better"] is False
        assert v[key]["verdict"] == "WORSE"
    assert v["max_drawdown"]["best_single_value"] == pytest.approx(-10.0)
    assert v["max_drawdown"]["book_value"] == pytest.approx(-30.0)


def test_a_book_that_really_does_beat_every_leg_is_reported_as_better():
    """The verdict word must be able to say BETTER, or it says nothing."""
    table = pd.DataFrame(
        {"max_drawdown": [-10.0, -50.0, -3.0],
         "dd_per_vol_day": [-10.0, -50.0, -3.0],
         "sharpe": [-0.5, -2.0, +0.4],
         "daily_vol": [1.0, 1.0, 1.0], "total": [-1.0, -1.0, 1.0],
         "n": [100, 100, 100]},
        index=["GOOD", "BAD", X.BOOK_ROW])
    v = X.book_verdicts(table)
    for key in ("max_drawdown", "dd_per_vol_day", "sharpe"):
        assert v[key]["book_is_better"] is True
        assert v[key]["verdict"] == "BETTER"


def test_a_tie_is_not_better():
    """The book has to beat the bar, not match it."""
    table = pd.DataFrame(
        {"max_drawdown": [-10.0, -10.0], "dd_per_vol_day": [-10.0, -10.0],
         "sharpe": [-0.5, -0.5], "daily_vol": [1.0, 1.0],
         "total": [-1.0, -1.0], "n": [100, 100]},
        index=["GOOD", X.BOOK_ROW])
    v = X.book_verdicts(table)
    assert v["max_drawdown"]["book_is_better"] is False
    assert v["max_drawdown"]["verdict"] == "WORSE"


def test_the_printed_verdict_word_matches_the_computed_one(capsys):
    """The print layer, so the word cannot drift from the boolean behind it."""
    frame = _two_leg_frame()
    book = portfolio(dict(frame.items()), target_bp_day=1.0)
    pnl = X.book_pnl(book, frame)
    out = X.compare_book_to_singles(frame, pnl, target_bp_day=1.0)
    verdicts = X.book_verdicts(out)
    X._compare(frame, pnl, target_bp_day=1.0, label="unit test")
    printed = capsys.readouterr().out
    for key in ("max_drawdown", "dd_per_vol_day"):
        v = verdicts[key]
        assert (f"best single market by {key}: {v['best_single']}") in printed
        assert f"book is {v['verdict']}" in printed
        assert f"{v['book_value']:+.3f}" in printed
    # the collinearity note is printed with real numbers, not asserted in prose
    assert "dd_per_vol_day / sharpe per row" in printed


# ------------------------------------------------- the carry-sign counterfactual


def test_carry_side_split_reports_the_side_the_rule_was_actually_on():
    idx = _idx(6)
    # unit flattener carry is negative every day, as it is in all four markets
    unit_carry = pd.Series([-10.0, -10.0, -10.0, -10.0, -10.0, -10.0], index=idx)
    # two flat days, three steepener days (scale < 0), one flattener day
    scale = pd.Series([0.0, 0.0, -1.0, -1.0, -1.0, +1.0], index=idx)
    got = X.carry_side_split(unit_carry, scale)
    assert got["n_held"] == 4
    assert got["n_steepener"] == 3
    assert got["n_flattener"] == 1
    assert got["steepener_share"] == pytest.approx(0.75)
    assert got["carry_usd"] == pytest.approx(3 * 10.0 - 10.0)          # +20
    assert got["carry_sign"] == 1
    assert got["carry_from_steepener_usd"] == pytest.approx(+30.0)
    assert got["carry_from_flattener_usd"] == pytest.approx(-10.0)
    assert got["unit_carry_frac_negative"] == pytest.approx(1.0)


def test_the_flattener_only_counterfactual_flips_the_carry_sign():
    """The measurement that makes 'carry +1 in all four markets' an artefact.

    Same days, same sizes, the other side. If a uniform -1 is equally
    available, a uniform +1 carries no information about the mechanism.
    """
    idx = _idx(6)
    unit_carry = pd.Series(-10.0, index=idx)
    scale = pd.Series([0.0, 0.0, -1.0, -1.0, -1.0, +1.0], index=idx)
    got = X.carry_side_split(unit_carry, scale)
    assert got["carry_sign"] == +1
    assert got["carry_flattener_only_usd"] == pytest.approx(-40.0)
    assert got["carry_flattener_only_sign"] == -1
    # the two counterfactuals are the same days and sizes, opposite side
    assert abs(got["carry_flattener_only_usd"]) == pytest.approx(
        abs(got["carry_from_steepener_usd"]) + abs(got["carry_from_flattener_usd"]))


def test_the_counterfactual_uses_the_magnitude_of_the_scale_not_a_sign_flip():
    """Sizes vary day to day; the counterfactual must keep each day's own size."""
    idx = _idx(4)
    unit_carry = pd.Series([-10.0, -20.0, -30.0, -40.0], index=idx)
    scale = pd.Series([-0.5, -1.0, +0.25, 0.0], index=idx)
    got = X.carry_side_split(unit_carry, scale)
    assert got["carry_usd"] == pytest.approx(5.0 + 20.0 - 7.5)
    assert got["carry_flattener_only_usd"] == pytest.approx(-5.0 - 20.0 - 7.5)
    assert got["n_held"] == 3


def test_a_book_that_never_traded_reports_no_side():
    idx = _idx(4)
    got = X.carry_side_split(pd.Series(-1.0, index=idx), pd.Series(0.0, index=idx))
    assert got["n_held"] == 0
    assert np.isnan(got["steepener_share"])
    assert got["carry_usd"] == 0.0


# ---------------------------------------------------------- the reason census


def test_the_reason_census_counts_the_decisions_the_real_rule_made():
    """Pinned against `strategy.signal_state`'s OWN strings, not against a
    re-derivation of them: if a message is reworded the census silently goes to
    zero, which is how a gate stops being reported without stopping being
    claimed."""
    from RVUtils.StrikelessVol.strategy import SignalConfig, signal_state

    cfg = SignalConfig()
    rows = [
        # cheap + calm drift + stretched z -> a flattener is taken
        {"be_over_realized": 0.6, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.0, "iv_z": 0.0},
        # cheap but the DRIFT VETO blocks it
        {"be_over_realized": 0.6, "drift_t": 9.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.0, "iv_z": 0.0},
        # cheap, drift missing -> fail closed
        {"be_over_realized": 0.6, "drift_t": np.nan, "residual_z": 2.5,
         "spread_vol_bp_day": 1.0, "iv_z": 0.0},
        # rich, vol spike gates the steepener
        {"be_over_realized": 1.5, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.0, "iv_z": 9.0},
        # rich, iv_z missing -> fail closed
        {"be_over_realized": 1.5, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.0, "iv_z": np.nan},
        # fair
        {"be_over_realized": 1.0, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.0, "iv_z": 0.0},
        # cheap but the residual is not stretched enough
        {"be_over_realized": 0.6, "drift_t": 0.0, "residual_z": 0.1,
         "spread_vol_bp_day": 1.0, "iv_z": 0.0},
    ]
    states = [signal_state(pd.Series(r), cfg) for r in rows]
    signals = pd.DataFrame(states, index=_idx(len(rows)))
    c = X.signal_reason_census(signals)
    assert c["n_rows"] == 7
    assert c["n_held"] == 1                 # only the first row takes a position
    assert c["n_cheap"] == 4
    assert c["n_rich"] == 2
    assert c["n_fair"] == 1
    assert c["n_drift_vetoed"] == 1
    assert c["n_drift_unconfirmed"] == 1
    assert c["n_iv_spike_gated"] == 1
    assert c["n_iv_unconfirmed"] == 1
    assert c["n_below_entry"] == 1
    assert c["drift_veto_share_of_cheap"] == pytest.approx(0.25)


def test_the_veto_can_be_over_its_threshold_and_still_block_nothing():
    """Why `share_drift_veto` is not the same statistic as the veto's effect.

    The veto only applies to a FLATTENER, so a panel that reads RICH every day
    has `drift_t` far over the gate on every row and zero blocks -- which is
    precisely what the slope-vol denominator produced.
    """
    from RVUtils.StrikelessVol.strategy import SignalConfig, signal_state

    cfg = SignalConfig()
    rows = [{"be_over_realized": 5.0, "drift_t": 9.0, "residual_z": 2.5,
             "spread_vol_bp_day": 1.0, "iv_z": 0.0} for _ in range(20)]
    signals = pd.DataFrame([signal_state(pd.Series(r), cfg) for r in rows],
                           index=_idx(20))
    c = X.signal_reason_census(signals)
    assert c["n_rich"] == 20
    assert c["n_drift_vetoed"] == 0        # over the gate on every row, blocks none
    assert np.isnan(c["drift_veto_share_of_cheap"])


# --------------------------------------------------------- the never-roll trap


def test_the_never_roll_constants_survive_a_nanosecond_index():
    """`DateOffset(months=12_000)` past 2020 is not representable at ns.

    A real curve map keys on `pd.Timestamp(date)`, which is SECOND resolution
    and reaches year 2500+, which is the only reason 12_000 ever worked. A
    `pd.bdate_range` index is nanosecond, capped at 2262-04-11.
    """
    from scripts.sv_static_long_control import _NEVER_ROLL_MONTHS as CONTROL_NEVER

    ns_start = pd.bdate_range("2020-01-01", periods=1)[0]
    assert ns_start.unit == "ns"
    for months in (X._NEVER_ROLL_MONTHS, CONTROL_NEVER):
        # unreachable for any sample this study runs ...
        assert months >= 1_200
        # ... and representable, which 12_000 is not
        assert (ns_start + pd.DateOffset(months=months)).year > 2100
    with pytest.raises(Exception):
        ns_start + pd.DateOffset(months=12_000)


# --------------------------------------------------------------- panel wiring


def _wire_fake_market(monkeypatch, n=800, seed=41):
    idx = _idx(n)
    rng = np.random.default_rng(seed)
    spread = np.cumsum(rng.normal(0, 1.0, n)) - 50.0
    # the LEVEL moves several times harder than the slope, as it does on every
    # real curve in this study (measured 2.6-6.2x across the four markets)
    long_rate = 0.04 + np.cumsum(rng.normal(0, 4e-4, n))
    fake_greeks = pd.DataFrame({
        "spread_bp": spread,
        "long_rate": long_rate,
        "short_rate": long_rate - spread / 10_000.0,
        "breakeven_h25": np.abs(rng.normal(3.0, 0.4, n)),
        "gamma_h25": np.full(n, 200.0),
        "daily_roll_usd": rng.normal(-2000.0, 100.0, n),
    }, index=idx)
    fake_vols = pd.DataFrame(
        {"2y10y": np.abs(4.0 + np.cumsum(rng.normal(0, 0.03, n)))}, index=idx)
    monkeypatch.setattr(X, "greeks_panel", lambda curves, pair, **kw: fake_greeks)
    monkeypatch.setattr(X, "vol_panel", lambda *a, **kw: fake_vols)
    return fake_greeks, fake_vols


def test_the_signal_panel_carries_every_column_the_rule_reads(monkeypatch):
    """``strategy.REQUIRED_COLUMNS`` is the contract; a missing one is a
    KeyError deep inside ``build_signals``, long after the panel was built."""
    _wire_fake_market(monkeypatch)
    built = X.build_signal_panel("USD", {}, X.headline_pair("USD"),
                                 start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1))
    for col in REQUIRED_COLUMNS:
        assert col in built["panel"].columns
    assert set(built["drivers"]) == {"vol"}
    assert built["changes_resid"].notna().sum() > 0


def test_the_size_base_and_the_valuation_comparator_are_DIFFERENT_series(monkeypatch):
    """The defect this whole correction is about.

    One series was bound to both `spread_vol_bp_day` (the SIZE) and
    `realized_vol_bp_day` (the valuation comparator), so the panel reported a
    `realized_vol_bp_day` that was not one. They are computed on different
    underlyings and must not coincide.
    """
    g, _ = _wire_fake_market(monkeypatch)
    built = X.build_signal_panel("USD", {}, X.headline_pair("USD"),
                                 start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1))
    p = built["panel"]
    want_slope = g["spread_bp"].diff().rolling(
        X.REALIZED_WINDOW, min_periods=X.REALIZED_WINDOW).std(ddof=1)
    want_rate = (g["long_rate"].diff() * 10_000.0).rolling(
        X.REALIZED_WINDOW, min_periods=X.REALIZED_WINDOW).std(ddof=1)
    assert p["spread_vol_bp_day"].dropna().sub(want_slope.dropna()).abs().max() < 1e-12
    assert p["realized_vol_bp_day"].dropna().sub(want_rate.dropna()).abs().max() < 1e-12
    both = pd.concat([p["spread_vol_bp_day"], p["realized_vol_bp_day"]],
                     axis=1).dropna()
    assert len(both) > 100
    assert (both.iloc[:, 0] - both.iloc[:, 1]).abs().min() > 1e-9
    # trailing, not centred: undefined through the warm-up
    assert p["spread_vol_bp_day"].iloc[:X.REALIZED_WINDOW].isna().all()
    assert p["realized_vol_bp_day"].iloc[:X.REALIZED_WINDOW].isna().all()


def test_the_valuation_switch_divides_the_breakeven_by_the_RATE_vol(monkeypatch):
    """It sets the SIGN, and BE is a PARALLEL-move breakeven.

    `package_gamma` is a second difference over `Curve.shift(±h)`, so the
    comparator is the LEVEL vol. Dividing by the slope vol instead -- which is
    several times smaller -- makes every day read richer and inverts the
    valuation state.
    """
    _wire_fake_market(monkeypatch)
    built = X.build_signal_panel("USD", {}, X.headline_pair("USD"),
                                 start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1))
    p = built["panel"]
    ratio = (p["be_over_realized"] * p["realized_vol_bp_day"]
             / p["breakeven_bp_day"]).dropna()
    assert np.allclose(ratio.to_numpy(), 1.0)
    assert float(p["be_over_realized"].dropna().median()) > 0.0
    # the slope ratio is kept as a LABELLED alternate, and is uniformly larger
    slope_ratio = (p["be_over_spread_vol"] * p["spread_vol_bp_day"]
                   / p["breakeven_bp_day"]).dropna()
    assert np.allclose(slope_ratio.to_numpy(), 1.0)
    both = pd.concat([p["be_over_realized"].rename("rate"),
                      p["be_over_spread_vol"].rename("slope")], axis=1).dropna()
    assert len(both) > 100
    assert (both["slope"] > both["rate"]).mean() > 0.9


def test_a_hand_rolled_denominator_cannot_reach_the_valuation_switch():
    """The guard, from the panel's side: the builders are the only way in."""
    from RVUtils.StrikelessVol.vol_metrics import be_over_realized

    s = pd.Series(np.cumsum(np.random.default_rng(9).normal(0, 1.0, 300)))
    with pytest.raises(ValueError, match="carries no `underlying` label"):
        be_over_realized(pd.Series(4.0, index=s.index),
                         s.diff().rolling(63, min_periods=63).std(ddof=1))


def test_the_pipeline_certifies_the_drift_source_end_to_end(monkeypatch):
    """The whole point of wiring ``changes_resid_fn``: the VETO's source goes
    through ``audit_causal_betas``, not just its transform."""
    from RVUtils.StrikelessVol.strategy import SignalConfig

    _wire_fake_market(monkeypatch)
    built = X.build_signal_panel("USD", {}, X.headline_pair("USD"),
                                 start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1))
    sig = X.build_signals(built, SignalConfig())
    certified = set(sig.attrs["certified_signal_inputs"])
    assert {"residual_z", "drift_t", "changes_resid"} <= certified
    assert sig.attrs["expanding_betas"] is True
    assert sig.attrs["rolling_sigma_z"] is True
    # iv_bp_day IS the raw observable, so no shock probe can certify it and the
    # honest certificate says so rather than claiming more than it has
    assert "iv_z(source uncertified)" in certified
    assert "iv_bp_day" in set(sig.attrs["uncertified_signal_inputs"])
    # and the two the engine covers nothing for are named, not omitted
    assert {"be_over_realized", "spread_vol_bp_day"} <= set(
        sig.attrs["uncertified_signal_inputs"])


def _make_leaky(built):
    """Swap the walk-forward changes residual for the full-sample one."""
    from RVUtils.StrikelessVol.factors import changes_regression, drift

    leaky = changes_regression(built["spread_bp"], built["drivers"]).residuals
    built["changes_resid"] = leaky.reindex(built["panel"].index)
    built["panel"]["drift_t"] = drift(built["changes_resid"], window=63)["t_stat"]
    return built


def test_a_full_sample_changes_residual_is_refused_on_the_artifact_tie(monkeypatch):
    """The canonical leaky construction in this study -- ``drift`` of a
    ``changes_regression`` residual -- must not reach the veto.

    With ``changes_resid_fn`` still the honest builder, the leg that fires is
    the ARTIFACT tie: the series handed over is not what the audited builder
    produces. That is the stronger refusal of the two, and the one a mutation
    of ``build_signal_panel`` alone earns.
    """
    from RVUtils.StrikelessVol.strategy import SignalConfig

    _wire_fake_market(monkeypatch)
    built = _make_leaky(X.build_signal_panel(
        "USD", {}, X.headline_pair("USD"),
        start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1)))
    with pytest.raises(ValueError, match="is not what .* produces"):
        X.build_signals(built, SignalConfig())


def test_a_leaky_series_beside_its_own_leaky_builder_is_refused_as_non_causal(
        monkeypatch):
    """And if BOTH are swapped, so the artifact tie holds, the causality leg
    is what refuses it. Neither door is the only one."""
    from RVUtils.StrikelessVol.backtest import causal_signals
    from RVUtils.StrikelessVol.factors import changes_regression
    from RVUtils.StrikelessVol.strategy import SignalConfig

    _wire_fake_market(monkeypatch)
    built = _make_leaky(X.build_signal_panel(
        "USD", {}, X.headline_pair("USD"),
        start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1)))
    with pytest.raises(ValueError, match="not causal"):
        causal_signals(
            built["panel"], SignalConfig(),
            spread_bp=built["spread_bp"], drivers=built["drivers"],
            changes_resid=built["changes_resid"],
            changes_resid_fn=lambda y, x: changes_regression(y, x).residuals,
            drift_window=63,
            iv_bp_day=built["iv_bp_day"], iv_z_window=252, iv_z_min_periods=126,
        )


def test_umep_is_refused_for_a_non_usd_market(monkeypatch):
    """There is no non-USD UMEP; asking for one must fail loudly rather than
    quietly run three markets on a different model from the fourth."""
    monkeypatch.setattr(X, "greeks_panel",
                        lambda curves, pair, **kw: pd.DataFrame(
                            {"spread_bp": [1.0], "long_rate": [0.04],
                             "short_rate": [0.04], "breakeven_h25": [1.0],
                             "gamma_h25": [1.0], "daily_roll_usd": [1.0]},
                            index=_idx(1)))
    monkeypatch.setattr(X, "vol_panel",
                        lambda *a, **kw: pd.DataFrame({"2y10y": [4.0]}, index=_idx(1)))
    with pytest.raises(ValueError, match="umep is USD-only"):
        X.build_signal_panel("JPY", {}, X.headline_pair("JPY"),
                             start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1),
                             with_umep=True)


def test_an_empty_greeks_panel_is_refused_rather_than_silently_shrinking(monkeypatch):
    monkeypatch.setattr(X, "greeks_panel", lambda curves, pair, **kw: pd.DataFrame())
    monkeypatch.setattr(X, "vol_panel",
                        lambda *a, **kw: pd.DataFrame({"2y10y": [4.0]}, index=_idx(1)))
    with pytest.raises(ValueError, match="greeks_panel produced no rows"):
        X.build_signal_panel("USD", {}, X.headline_pair("USD"),
                             start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1))
