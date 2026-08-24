"""Tests for the expected-sentiment SR3 study.

Every test name is a sentence stating the invariant, and every docstring says
what breaks silently without it. Where a defect was actually measured, the
number is in the docstring.

Two anti-vacuity idioms are used throughout, because a test that passes with the
guard deleted has tested nothing:

* a paired test proves the guard FIRES on a deliberately broken input;
* a fixture asserts it is discriminating before the thing under test reads it.
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
RV = REPO / "notebooks" / "rv"
for _p in (str(REPO), str(RV)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_detachment_grid as GR  # noqa: E402
import fed_detachment_prices as PX  # noqa: E402
import fed_expected_sentiment as E  # noqa: E402
import fed_expected_sentiment_run as R  # noqa: E402


# ---- fixtures -------------------------------------------------------------
@pytest.fixture(scope="module")
def weeks() -> pd.DatetimeIndex:
    return pd.date_range("2020-01-03", periods=200, freq="W-FRI")


@pytest.fixture(scope="module")
def zc(weeks) -> pd.Series:
    rng = np.random.default_rng(7)
    x = np.cumsum(rng.normal(size=len(weeks))) * 0.2
    return pd.Series(x, index=weeks, name="z_composite")


@pytest.fixture(scope="module")
def panel():
    """The real SR3 settle panel, or a skip. Never a synthetic stand-in.

    A synthetic panel would let the roll tests pass against contracts that do
    not roll the way the real ones do, which is the property under test.
    """
    PX.seed_local_cache()
    syms = PX.sr3_universe(pd.Timestamp("2019-01-01").date(),
                           pd.Timestamp("2026-08-24").date(), max_rank=4)
    p = PX.settle_panel(syms)
    if p.empty or p.shape[1] < 10:
        pytest.skip("SR3 settle cache is cold; run fed_detachment_refresh_settles.py")
    return p


@pytest.fixture(scope="module")
def sessions(panel):
    return np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")


# ---- the alignment arithmetic --------------------------------------------
def test_lags_implement_the_documented_lead_arithmetic():
    """``(lead, horizon) -> (near, far)`` is the derivation in the docstring.

    If the data leads Fedspeak by L weeks, sentiment at t+h tracks the composite
    at t-(L-h), so the forecast of the change over the hold is
    ``C_{t-(L-h)} - C_{t-L}``. Getting this backwards -- the obvious
    ``zc.shift(k)`` sweep -- makes the signal gratuitously stale and turns a
    defended axis into a nuisance parameter.
    """
    cases = {
        (11, 4): (7, 11),
        (5, 4): (1, 5),
        (5, 8): (0, 5),
        (2, 4): (0, 2),
        (2, 1): (1, 2),
        (0, 4): (0, 4),      # no lead: the window is the holding period itself
        (0, 1): (0, 1),
    }
    for (lw, h), want in cases.items():
        cfg = dataclasses.replace(E.PRIMARY, lead_w=lw, horizon_w=h)
        assert cfg.lags() == want, f"lead {lw}, horizon {h}"


def test_lag_near_is_never_negative_and_never_equals_lag_far():
    """A negative near lag would read the future; near == far would make ``chg``
    the difference of a value with itself, i.e. a constant zero signal that
    still occupies a grid cell and still gets counted as a trial."""
    for lw in range(0, 30):
        for h in range(1, 15):
            near, far = dataclasses.replace(E.PRIMARY, lead_w=lw,
                                            horizon_w=h).lags()
            assert near >= 0
            assert far > near


# ---- the sign convention --------------------------------------------------
def test_hot_data_with_direction_follow_PAYS_ie_shorts_the_future(zc, sessions):
    """``s > 0`` means hot data; FOLLOW means expect hawkish Fedspeak; a hawkish
    Fed means the front end sells off; so the position is SHORT the future.

    ``side`` is the PRICE side, so short is ``-1``. This is the study's whole
    sign convention in one assertion. The desk's most repeated defect class is
    two studies sharing a knob name with opposite meanings -- ``DetachConfig.sign``
    means FADE at +1, this study's ``direction`` means FOLLOW at +1 -- so the
    convention is pinned rather than described.
    """
    s = pd.Series([2.0] * 30, index=zc.index[:30])
    cfg = dataclasses.replace(E.PRIMARY, threshold=0.0, horizon_w=4, direction=1)
    tr = E.schedule_trades(s, cfg, sessions)
    assert len(tr) > 0
    assert (tr["side"] == -1).all(), "hot data + follow must be SHORT the future"

    cold = pd.Series([-2.0] * 30, index=zc.index[:30])
    tr2 = E.schedule_trades(cold, cfg, sessions)
    assert (tr2["side"] == +1).all(), "cold data + follow must be LONG the future"

    faded = dataclasses.replace(cfg, direction=-1)
    tr3 = E.schedule_trades(s, faded, sessions)
    assert (tr3["side"] == +1).all(), "direction=-1 must reverse every side"


def test_the_borrowed_best_of_both_sign_maps_to_this_studys_direction():
    """``GR.best_of_both`` returns +1 for what it calls "fade": ``side = +sign(d)``.

    In this study a positive signal is hot data and going LONG the future on hot
    data is fading the data, so the borrowed +1 IS this study's
    ``direction = -1``. The league's ``direction`` column is written from that
    correspondence, and a reader who assumed the two +1s agreed would read every
    row of the league backwards.
    """
    d = np.array([1.0] * 40)
    r = np.array([10.0] * 40)          # long the future always wins
    sr, sgn, idx, p = GR.best_of_both(d, r, threshold=0.0, horizon=1,
                                      cost_bp=0.0, n_weeks=40, min_trades=8)
    assert sgn == 1, "the winning reading here is side=+sign(d), i.e. long"
    assert p.mean() > 0
    # and that is this study's direction = -1 (fade the data)
    assert (-1 if sgn > 0 else 1) == -1


def test_ois2y_long_profits_when_the_rate_falls(sessions):
    """The non-futures leg must mean the same thing by "long" as the futures do,
    or a cell's sign silently changes meaning when the structure changes."""
    idx = pd.date_range("2021-01-04", periods=60, freq="B")
    rate = pd.Series(np.linspace(4.0, 3.0, len(idx)), index=idx)  # rate FALLING
    sess = np.asarray(idx.values, dtype="datetime64[ns]")
    trades = pd.DataFrame([{"signal_date": idx[0], "entry_date": idx[1],
                            "exit_date": idx[40], "signal": -1.0, "side": 1}])
    cfg = dataclasses.replace(E.PRIMARY, structure="ois2y")
    book, _ = E.price_trades(trades, pd.DataFrame(), cfg, rate=rate)
    assert len(book) == 1
    assert book["pnl_bp_gross"].iloc[0] > 0, "long must profit on a falling rate"


def test_ois2y_without_a_rate_series_raises_RuntimeError_not_KeyError():
    """``compare``-style callers catch RuntimeError only. A KeyError from a
    missing input kills a whole run instead of reporting one bad row."""
    trades = pd.DataFrame([{"signal_date": pd.Timestamp("2021-01-01"),
                            "entry_date": pd.Timestamp("2021-01-04"),
                            "exit_date": pd.Timestamp("2021-02-01"),
                            "signal": 1.0, "side": 1}])
    cfg = dataclasses.replace(E.PRIMARY, structure="ois2y")
    with pytest.raises(RuntimeError, match="needs a rate series"):
        E.price_trades(trades, pd.DataFrame(), cfg, rate=None)


# ---- the fill -------------------------------------------------------------
def test_the_fill_is_the_NEXT_session_not_the_signal_session(sessions):
    """A fill on the signal session lets the entry price be the very print the
    signal was computed from. ``project_cavf_grid_verdict`` measured that
    same-day fills harvest mark noise; it is not a free robustness knob."""
    weeks = pd.DatetimeIndex(pd.Series(sessions[::5]).dt.normalize())[:20]
    out = E.gate_fill_is_next_session(sessions, E.PRIMARY, probe_weeks=weeks)
    assert bool(out["strictly_after"].all())
    assert (out["fill"] > out["signal_friday"]).all()


def test_entry_lag_zero_snaps_BACK_and_the_gate_does_not_assert_on_it(sessions):
    """Lag 0 is the same-day-fill SENSITIVITY and must actually be same-day, not
    silently the next session -- otherwise the sensitivity measures nothing."""
    cfg = dataclasses.replace(E.PRIMARY, entry_lag_sessions=0)
    on = pd.Timestamp(sessions[100])
    got = E._shift_sessions(sessions, on, cfg.entry_lag_sessions)
    assert got == on
    weeks = [pd.Timestamp(s) for s in sessions[100:110]]
    out = E.gate_fill_is_next_session(sessions, cfg, probe_weeks=weeks)
    assert not out["strictly_after"].any()


def test_gate_fill_is_next_session_FIRES_when_the_fill_is_same_day(sessions,
                                                                   monkeypatch):
    """The paired anti-vacuity test: break the fill and require the gate to
    catch it. Without this, the gate could be a no-op and every run would pass."""
    monkeypatch.setattr(E, "_shift_sessions", lambda sess, on, lag: on)
    weeks = [pd.Timestamp(s) for s in sessions[100:105]]
    with pytest.raises(AssertionError, match="G-X2 FAILED"):
        E.gate_fill_is_next_session(sessions, E.PRIMARY, probe_weeks=weeks)


# ---- trailing-only --------------------------------------------------------
def test_every_reading_is_computable_in_real_time(zc):
    """G-X1 over the whole composition. A rolling OLS, a shift and a z-score are
    each individually trailing; assembling them is where a leak gets in."""
    probes = list(zc.index[60::20])
    for reading in ("level", "chg"):
        cfg = dataclasses.replace(E.PRIMARY, reading=reading)
        out = E.gate_trailing_signal(zc, cfg, probe_dates=probes)
        assert not out.empty
        assert float(out["abs_diff"].max()) == 0.0


def test_gate_trailing_signal_FIRES_on_a_deliberately_leaky_signal(zc, monkeypatch):
    """Plant a leak -- a signal that reads the LAST value of the whole series --
    and require the gate to catch it."""
    real = E.build_signal

    def leaky(z, cfg, zs=None):
        s = real(z, cfg, zs)
        return s + float(z.dropna().iloc[-1])     # depends on the future

    monkeypatch.setattr(E, "build_signal", leaky)
    with pytest.raises(AssertionError, match="G-X1 FAILED"):
        E.gate_trailing_signal(zc, E.PRIMARY, probe_dates=list(zc.index[60::20]))


def test_a_truncated_history_yields_the_same_fit_prediction(zc, weeks):
    """``fit`` runs a rolling OLS, which is the reading most likely to leak.
    Tested separately because it needs a second series."""
    rng = np.random.default_rng(11)
    zs = pd.Series(np.cumsum(rng.normal(size=len(weeks))) * 0.2, index=weeks)
    cfg = dataclasses.replace(E.PRIMARY, reading="fit", lead_w=5, horizon_w=4,
                              reg_window_w=52, sent_z_min_w=12)
    out = E.gate_trailing_signal(zc, cfg, probe_dates=list(weeks[80::20]), zs=zs)
    assert not out.empty
    assert float(out["abs_diff"].max()) < 1e-9


# ---- the roll -------------------------------------------------------------
def test_the_naive_rank_column_fabricates_drift_at_every_roll(panel, sessions):
    """The placebo, on a construction whose answer is known in advance.

    Run FIRST, before the measurement is pointed at the real book: a checking
    tool that is itself wrong reports success. Measured on the real panel over
    2018-2026 (33 rolls): the naive fixed-rank weekly difference has a signed
    mean of about +4.6bp on roll weeks against -0.8bp elsewhere, and the gap to
    the same-contract change is about +6.6bp per roll week and +218bp in total.
    """
    weeks = pd.date_range("2018-05-11", "2026-08-21", freq="W-FRI")
    out = E.roll_placebo(panel, weeks, sessions, rank=3)
    assert out["roll_weeks"] >= 30
    # the known answer: the two constructions must agree EXACTLY off the rolls
    assert out["fabricated_on_flat_weeks_bp"] == 0.0
    # ... and disagree materially on them
    assert abs(out["fabricated_mean_bp"]) > 3.0
    assert out["naive_roll_abs_median_bp"] > 2 * out["naive_flat_abs_median_bp"]


def test_roll_placebo_ASSERTS_when_its_own_measurement_is_broken():
    """The placebo's known-answer half, exercised on a frame built to break it.

    On a week with no contract change the two constructions are the same
    arithmetic and must agree bit for bit; a disagreement means an off-by-one
    between the mark dates and the symbol dates, which would silently rescale
    the roll-week number the placebo exists to produce. Without this test the
    assertion could be deleted and every run would still pass.
    """
    good = pd.DataFrame({"d_naive_bp": [1.0, 2.0, 3.0],
                         "d_true_bp": [1.0, 2.0, 3.0],
                         "rolled": [False, False, True]})
    assert E.assert_flat_weeks_agree(good) == 0.0

    broken = good.copy()
    broken.loc[1, "d_true_bp"] = 2.5        # a flat week that disagrees
    with pytest.raises(AssertionError, match="roll_placebo is broken"):
        E.assert_flat_weeks_agree(broken)


def test_roll_placebo_flat_week_identity_is_not_vacuous(panel, sessions):
    """...and the real placebo must actually HAVE flat weeks to check.

    If every week were a roll week the identity above would hold vacuously.
    """
    weeks = pd.date_range("2018-05-11", "2026-08-21", freq="W-FRI")
    out = E.roll_placebo(panel, weeks, sessions, rank=3)
    flat = out["series"].loc[~out["series"]["rolled"]]
    assert len(flat) > 300, "the identity must be checked on hundreds of weeks"
    assert flat["d_true_bp"].notna().sum() > 300


def test_no_priced_row_ever_differences_two_contracts(panel, sessions, zc):
    """G-X3, checked against the settle panel rather than asserted in prose."""
    weeks = pd.date_range("2019-01-04", "2026-08-21", freq="W-FRI")
    s = pd.Series(np.sin(np.arange(len(weeks)) / 6.0), index=weeks)
    cfg = dataclasses.replace(E.PRIMARY, threshold=0.0, horizon_w=4)
    tr = E.schedule_trades(s, cfg, sessions)
    bookA, _ = E.price_trades(tr, panel, cfg)
    bookB, _ = E.weekly_book(s, panel, cfg, sessions)
    for bk, nm in ((bookA, "discrete"), (bookB, "weekly")):
        out = E.gate_no_roll_jump(bk, name=nm, panel=panel)
        assert out["marks_checked"] > 50, "the fixture must actually check marks"
        assert out["worst_mark_diff"] == 0.0


def test_gate_no_roll_jump_FIRES_when_a_mark_comes_from_another_contract(panel,
                                                                         sessions):
    """Corrupt one exit price and require the gate to name it."""
    weeks = pd.date_range("2021-01-08", "2024-12-27", freq="W-FRI")
    s = pd.Series(np.sin(np.arange(len(weeks)) / 6.0), index=weeks)
    cfg = dataclasses.replace(E.PRIMARY, threshold=0.0, horizon_w=4)
    book, _ = E.weekly_book(s, panel, cfg, sessions)
    assert len(book) > 20
    book = book.copy()
    book.loc[book.index[5], "exit_px"] = float(book.loc[book.index[5], "exit_px"]) + 0.25
    with pytest.raises(AssertionError, match="G-X3 FAILED"):
        E.gate_no_roll_jump(book, name="mutated", panel=panel)


def test_a_trade_whose_contract_expires_inside_the_hold_is_dropped_and_counted(panel,
                                                                               sessions):
    """A 26-week hold on rank 1 CAN cross expiry: the measured minimum margin is
    85 days = 12.1 weeks, not the 13 the price module's docstring claims. The
    explicit guard is the only thing standing between that and a P&L computed
    across two contracts."""
    weeks = pd.date_range("2021-01-08", "2024-12-27", freq="W-FRI")
    s = pd.Series(1.0, index=weeks)
    cfg = dataclasses.replace(E.PRIMARY, structure="out1", horizon_w=26,
                              threshold=0.0)
    tr = E.schedule_trades(s, cfg, sessions)
    assert len(tr) > 5
    book, reasons = E.price_trades(tr, panel, cfg)
    assert reasons.get("contract expires inside the hold", 0) > 0, (
        "the fixture must contain a crossing trade for this to test anything")
    assert len(book) < len(tr)


# ---- the always-on book's cost accounting ---------------------------------
def test_holding_the_same_side_in_the_same_contract_costs_nothing(panel, sessions):
    """An always-on book that charged a round trip every week would be paying
    for turnover it never did -- 52 round trips a year against about four."""
    weeks = pd.date_range("2022-01-07", "2023-12-29", freq="W-FRI")
    s = pd.Series(1.0, index=weeks)          # never changes its mind
    cfg = dataclasses.replace(E.PRIMARY, threshold=0.0, structure="out3")
    book, _ = E.weekly_book(s, panel, cfg, sessions)
    quiet = book.loc[~book["rolled"]].iloc[1:]     # skip the opening trade
    assert len(quiet) > 50
    assert float(quiet["cost_bp"].abs().max()) == 0.0


def test_a_side_change_costs_exactly_one_round_trip(panel, sessions):
    """Flipping long to short is TWO one-ways -- sell one to close, sell one to
    open -- which is 0.50bp on an outright, i.e. one round trip and not two.

    Charging two would double the cost of the only book that is always in the
    market, and this study's whole verdict turns on a cost comparison.
    """
    weeks = pd.date_range("2022-01-07", "2023-12-29", freq="W-FRI")
    s = pd.Series(np.where(np.arange(len(weeks)) % 20 < 10, 1.0, -1.0), index=weeks)
    cfg = dataclasses.replace(E.PRIMARY, threshold=0.0, structure="out3")
    book, _ = E.weekly_book(s, panel, cfg, sessions)
    flips = book["side"] != book["side"].shift(1)
    flips.iloc[0] = False
    changed = book.loc[flips & ~book["rolled"]]
    assert len(changed) > 5, "the fixture must contain side changes"
    assert np.allclose(changed["cost_bp"].to_numpy(float),
                       cfg.cost_bp_round_trip())
    assert cfg.cost_bp_round_trip() == pytest.approx(0.50)


def test_opening_from_flat_costs_only_one_side(panel, sessions):
    """Opening a position from flat is ONE one-way, not a round trip: the exit
    has not happened yet and charging for it here would double-count against
    the week the book actually closes."""
    weeks = pd.date_range("2022-01-07", "2023-12-29", freq="W-FRI")
    v = np.zeros(len(weeks)); v[10:] = 2.0          # flat, then long
    s = pd.Series(v, index=weeks)
    cfg = dataclasses.replace(E.PRIMARY, threshold=1.0, structure="out3")
    book, _ = E.weekly_book(s, panel, cfg, sessions)
    opened = book.loc[(book["side"] != 0) & (book["side"].shift(1).fillna(0) == 0)]
    assert len(opened) == 1, "the fixture must open exactly once"
    assert float(opened["cost_bp"].iloc[0]) == pytest.approx(
        0.5 * cfg.cost_bp_round_trip())


def test_a_roll_at_unchanged_side_costs_one_round_trip(panel, sessions):
    """Rolling a held position is a real cost and must not be free -- but it is
    also not two round trips."""
    weeks = pd.date_range("2022-01-07", "2024-12-27", freq="W-FRI")
    s = pd.Series(1.0, index=weeks)
    cfg = dataclasses.replace(E.PRIMARY, threshold=0.0, structure="out3")
    book, _ = E.weekly_book(s, panel, cfg, sessions)
    rolls = book.loc[book["rolled"]]
    assert len(rolls) >= 8, "the fixture must contain rolls"
    assert np.allclose(rolls["cost_bp"].to_numpy(float), 0.5)


def test_a_threshold_keeps_the_book_flat_and_flat_weeks_book_zero(panel, sessions):
    """A stand-aside must be a genuine zero-side week, not a zero-sized trade:
    a booked zero dilutes the hit rate and shrinks the standard deviation, which
    inflates the Sharpe of a book that did nothing."""
    weeks = pd.date_range("2022-01-07", "2023-12-29", freq="W-FRI")
    s = pd.Series(0.1, index=weeks)         # always below a 1-sigma gate
    cfg = dataclasses.replace(E.PRIMARY, threshold=1.0, structure="out3")
    book, reasons = E.weekly_book(s, panel, cfg, sessions)
    assert len(book) > 50
    assert (book["side"] == 0).all()
    assert float(book["pnl_bp"].abs().max()) == 0.0
    assert reasons["weeks_in_market"] == 0


# ---- tie-out between the two implementations ------------------------------
def test_the_discrete_book_ties_out_to_the_borrowed_grid_cell(panel, sessions, zc):
    """This module's ``schedule_trades`` + ``price_trades`` and the borrowed
    ``GR.run_cell`` over ``GR.build_return_bank`` are two independent
    implementations of the same book. They must agree trade for trade.

    Verifying the checker: without this, a bug in either one would be invisible,
    because the study reports the first and the grid searches the second.
    """
    weeks = pd.date_range("2019-01-04", "2026-08-21", freq="W-FRI")
    cfg = dataclasses.replace(E.PRIMARY, threshold=0.5, horizon_w=4,
                              structure="out3", direction=1)
    s = pd.Series(np.sin(np.arange(len(weeks)) / 9.0) * 1.3, index=weeks)

    tr = E.schedule_trades(s, cfg, sessions)
    mine, _ = E.price_trades(tr, panel, cfg)

    bank, _diag = GR.build_return_bank(panel, weeks, R.cost_carrier(cfg),
                                       horizons=(cfg.horizon_w,),
                                       structures=(cfg.structure,),
                                       entry_lag_sessions=cfg.entry_lag_sessions)
    r = bank[(cfg.structure, cfg.horizon_w)]
    # borrowed sign +1 = long on a positive signal = this study's direction -1,
    # so FOLLOW (direction +1) is the borrowed -1.
    idx, pnl = GR.run_cell(s.to_numpy(float), r, threshold=cfg.threshold,
                           horizon=cfg.horizon_w, sign=-cfg.direction,
                           cost_bp=cfg.cost_bp_round_trip())
    assert len(idx) >= 10, "the fixture must produce trades for this to test anything"
    # run_cell skips a week whose forward return is NaN; price_trades drops the
    # trade after the fact. Compare on the intersection of signal weeks.
    mine_by_week = dict(zip(pd.DatetimeIndex(mine["signal_date"]),
                            mine["pnl_bp"].astype(float)))
    theirs_by_week = {weeks[i]: float(p) for i, p in zip(idx, pnl)}
    shared = sorted(set(mine_by_week) & set(theirs_by_week))
    assert len(shared) >= 10
    diffs = [abs(mine_by_week[w] - theirs_by_week[w]) for w in shared]
    assert max(diffs) < 1e-9, f"worst tie-out diff {max(diffs):.3e}bp"


# ---- inference ------------------------------------------------------------
def test_rotation_offsets_exceed_twice_the_widest_alignment():
    """A rotation smaller than twice the widest lag can reproduce the true
    alignment, and the p-value then measures where the argmax sits rather than
    how big the effect is (``reference_rotation_null_self_match``)."""
    offs = E.rotation_offsets(400, max_lag=11, max_h=8)
    assert offs.size > 0
    assert offs.min() == 2 * (11 + 8) + 1
    assert E.rotation_offsets(50, max_lag=11, max_h=8).size == 0


def test_the_rotation_null_p_has_a_floor_it_reports():
    """Quoting p=0.001 off 40 surrogates is a 25x overstatement. The floor is
    1/(draws+1) and must be reported, not hidden."""
    idx = pd.date_range("2020-01-03", periods=300, freq="W-FRI")
    s = pd.Series(np.random.default_rng(3).normal(size=len(idx)), index=idx)
    null = E.rotation_null(s, lambda x: float(x.mean()), max_lag=2, max_h=1,
                           draws=25, rng=np.random.default_rng(1))
    assert null["n_offsets"] == 25
    assert np.isclose(null["p_floor"], 1 / 26)
    assert E.rotation_pvalue(1e9, null) == pytest.approx(1 / 26)


def test_sign_flip_is_two_sided_and_uniform_under_the_null():
    """A one-sided sign-flip on a symmetric null reports half the p it should."""
    rng = np.random.default_rng(5)
    ps = [E.sign_flip_pvalue(rng.normal(size=40), draws=2000,
                             rng=np.random.default_rng(i)) for i in range(60)]
    assert 0.02 < np.mean([p < 0.05 for p in ps]) < 0.20


def test_expected_max_sharpe_grows_with_the_number_of_trials():
    """The bar a searched winner must clear has to rise with the size of the
    search, or the deflation is not charging for the search at all."""
    a = E.expected_max_sharpe(0.05, 10)
    b = E.expected_max_sharpe(0.05, 2000)
    assert 0 < a < b
    assert E.expected_max_sharpe(0.05, 1) == 0.0


def test_deflated_sharpe_falls_when_the_bar_rises():
    r = np.random.default_rng(2).normal(0.15, 1.0, size=200)
    assert E.deflated_sharpe(r, 0.0) > E.deflated_sharpe(r, 0.30)


# ---- the grid wiring ------------------------------------------------------
def test_the_signal_bank_is_keyed_by_horizon_as_well_as_lead(zc):
    """Two cells that differ only in horizon read DIFFERENT signals, because the
    lag window is derived from (lead, horizon) together. A bank keyed only by
    (reading, lead) would silently give them the same signal -- which is exactly
    what the borrowed ``GR.run_grid`` would have done."""
    bank = R.build_signal_bank(zc, E.PRIMARY, readings=("chg",), leads=(11,),
                               horizons=(1, 4, 8))
    a = bank[("chg", 11, 1)].dropna()
    b = bank[("chg", 11, 4)].dropna()
    shared = a.index.intersection(b.index)
    assert len(shared) > 50
    assert not np.allclose(a.reindex(shared), b.reindex(shared))


def test_key_rows_points_every_cell_at_its_own_signal(zc):
    keys = R.cell_keys(readings=("chg",), leads=(0, 5), thresholds=(0.0,),
                       horizons=(1, 4), structures=("out3",))
    bank = R.build_signal_bank(zc, E.PRIMARY, readings=("chg",), leads=(0, 5),
                               horizons=(1, 4))
    rows, sig_keys = R.key_rows(keys, bank)
    assert len(rows) == len(keys)
    for j, (reading, lw, _t, h, _s) in enumerate(keys):
        assert sig_keys[rows[j]] == (reading, lw, h)


def test_the_coverage_gate_fires_on_an_unpriceable_structure():
    """``settle_panel`` returns only the contracts whose parquet exists, so a
    cold cache makes every futures structure all-NaN, every cell NaN, and the
    run still prints a complete grid with a p-value computed from whichever
    instrument happened to be readable."""
    support = pd.date_range("2022-01-07", periods=100, freq="W-FRI")
    bank = {("out3", 4): np.full(100, np.nan)}
    with pytest.raises(AssertionError, match="G-P3 FAILED"):
        R._gate_return_bank_coverage(bank, ("out3",), support)


def test_cost_carrier_never_leaks_the_detachment_studys_sign():
    """``DetachConfig.sign`` means FADE at +1 and this study's ``direction``
    means FOLLOW at +1. The carrier exists so that no caller reads one for the
    other; this pins that it carries costs and nothing else that matters."""
    cfg = dataclasses.replace(E.PRIMARY, cost_bp_one_way=0.125,
                              entry_lag_sessions=2, direction=-1)
    car = R.cost_carrier(cfg)
    assert car.cost_bp_one_way == 0.125
    assert car.entry_lag_sessions == 2
    assert car.sign == 1, "the carrier's sign is the DetachConfig default, unused"


def test_cost_is_per_contract_so_a_spread_costs_twice_an_outright():
    """``reference_sfr_fly_conventions``: the cost is per CONTRACT, not per leg
    of the quote. An outright round trip is 0.50bp, a 1x1 calendar spread is two
    contracts and 1.00bp, and a four-contract pack quoted as the average of its
    legs is 0.50bp of the pack quote -- four times the risk and four times the
    cost, so per unit of gross risk every same-sign basket costs the same."""
    def rt(name):
        return dataclasses.replace(E.PRIMARY, structure=name).cost_bp_round_trip()
    assert rt("out3") == pytest.approx(0.50)
    assert rt("spr1x3") == pytest.approx(1.00)
    assert rt("pack1") == pytest.approx(0.50)


# ---- episodes -------------------------------------------------------------
def test_episodes_collapse_a_long_one_sided_run_into_one_effective_observation():
    """A signal built from a heavily standardised macro series holds a view for
    months. A book of forty trades living in four episodes has an effective
    sample of four, and a t-stat computed on forty describes something that does
    not exist."""
    dates = pd.date_range("2022-01-07", periods=40, freq="W-FRI")
    book = pd.DataFrame({"entry_date": dates,
                         "side": [1] * 20 + [-1] * 20,
                         "pnl_bp": np.ones(40)})
    ep = E.episodes(book, gap_weeks=8)
    assert ep["episode"].nunique() == 2
