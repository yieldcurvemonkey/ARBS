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
    idx = _idx(4)
    led = pd.DataFrame({
        "carry": [0.0, 100.0, 100.0, 100.0],
        "harvest": 0.0, "mtm": 0.0, "cross": 0.0,
        "initiate_dv01_usd": [100_000.0, 0.0, 0.0, 0.0],
        "hedge_dv01_usd": 0.0, "roll_dv01_usd": 0.0,
    }, index=idx)
    sched = CostSchedule(initiate_bp=0.875)
    got = X.breakeven_cost_multiplier(_FakeResult(None, 1.0, led), sched)
    assert got == pytest.approx(300.0 / (0.875 * 100_000.0))


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


# --------------------------------------------------------------- panel wiring


def _wire_fake_market(monkeypatch, n=800, seed=41):
    idx = _idx(n)
    rng = np.random.default_rng(seed)
    fake_greeks = pd.DataFrame({
        "spread_bp": np.cumsum(rng.normal(0, 1.0, n)) - 50.0,
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


def test_the_realized_vol_is_the_trailing_window_a_hand_computation_gives(monkeypatch):
    """Derivation check, not a bound: the size input and the valuation
    denominator are the same trailing statistic, computed one way."""
    g, _ = _wire_fake_market(monkeypatch)
    built = X.build_signal_panel("USD", {}, X.headline_pair("USD"),
                                 start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1))
    want = g["spread_bp"].diff().rolling(
        X.REALIZED_WINDOW, min_periods=X.REALIZED_WINDOW).std(ddof=1)
    got = built["panel"]["spread_vol_bp_day"]
    assert got.dropna().sub(want.dropna()).abs().max() < 1e-12
    assert got.iloc[:X.REALIZED_WINDOW].isna().all()
    # a centred window would be defined at the head; a trailing one is not
    assert int(got.notna().sum()) == len(g) - X.REALIZED_WINDOW


def test_be_over_realized_is_breakeven_over_realized_not_the_other_way(monkeypatch):
    """It sets the SIGN: inverted, every cheap day reads rich and vice versa."""
    g, _ = _wire_fake_market(monkeypatch)
    built = X.build_signal_panel("USD", {}, X.headline_pair("USD"),
                                 start=dt.date(2020, 1, 1), end=dt.date(2021, 1, 1))
    p = built["panel"]
    ratio = (p["be_over_realized"] * p["realized_vol_bp_day"]
             / p["breakeven_bp_day"]).dropna()
    assert np.allclose(ratio.to_numpy(), 1.0)
    assert float(p["be_over_realized"].dropna().median()) > 0.0


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
                            {"spread_bp": [1.0], "breakeven_h25": [1.0],
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
