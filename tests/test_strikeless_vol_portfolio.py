"""``report.portfolio`` -- the risk-parity book across markets.

Four of these come from the Task 21 brief. The fourth,
``test_diversification_reduces_volatility``, is **corrected**: as written it
asserted ``out["pnl"].std() < max(a.std(), b.std())`` on two independent
unit-vol series at ``target_bp_day=1.0``, where each weight is ~1.0 and the book
is ~``a + b`` with sd ~``sqrt(2)``. The book is NOISIER than either leg, not
quieter -- diversification lowers the vol of a book *per unit of gross risk*,
not below its own largest component. The real property is pinned here instead
(strictly below the SUM of the scaled legs, and ~``sqrt(n)`` for independent
legs), which is a statement that can be false and is checked numerically.
"""
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.report import portfolio


def _series(mu, sd, n=500, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mu, sd, n), index=pd.bdate_range("2024-01-01", periods=n))


# --------------------------------------------------------------- the brief's four


def test_portfolio_risk_weights_the_noisier_market_down():
    out = portfolio({"USD": _series(0, 1.0, seed=1), "JPY": _series(0, 4.0, seed=2)},
                    target_bp_day=1.0)
    assert out["w_USD"].iloc[-1] > out["w_JPY"].iloc[-1]
    # And by the right amount: the weight is target / trailing sd, so a market
    # with 4x the vol gets 1/4 the weight. Pinning the RATIO is what separates
    # `target / vol` from `target / vol**2` (which would order them identically
    # and give 16x) or from any other monotone decreasing function of vol.
    ratio = float(out["w_USD"].iloc[-1] / out["w_JPY"].iloc[-1])
    assert ratio == pytest.approx(4.0, rel=0.25)


def test_portfolio_pnl_is_the_weighted_sum():
    a, b = _series(0, 1.0, seed=3), _series(0, 1.0, seed=4)
    out = portfolio({"A": a, "B": b}, target_bp_day=1.0)
    expected = out["w_A"] * a + out["w_B"] * b
    assert out["pnl"].dropna().sub(expected.dropna()).abs().max() < 1e-9
    # The comparison above is only meaningful if there is something to compare:
    # both sides are NaN through the warm-up, and an all-NaN difference has an
    # `abs().max()` of NaN, which is not < 1e-9 -- but a zero-length one is also
    # not caught. Pin that the overlap is the whole post-warm-up sample.
    assert len(out["pnl"].dropna()) == len(a) - 63


def test_caps_are_respected():
    out = portfolio({"USD": _series(0, 0.1, seed=5), "EUR": _series(0, 4.0, seed=6)},
                    target_bp_day=1.0, caps={"USD": 0.5})
    assert out["w_USD"].max() <= 0.5 + 1e-12
    # A cap that never binds is trivially "respected". The uncapped weight on a
    # 0.1-sd market at target 1.0 is ~10, so this cap is ~20x below where the
    # weight would otherwise sit -- and it must BIND, on every dated row.
    uncapped = portfolio({"USD": _series(0, 0.1, seed=5), "EUR": _series(0, 4.0, seed=6)},
                         target_bp_day=1.0)
    assert uncapped["w_USD"].min() > 0.5
    held = out["w_USD"].dropna()
    assert len(held) > 0
    assert np.allclose(held.to_numpy(), 0.5)
    # The capped weight is the one that pays: pnl must be built from it, not
    # from the uncapped weight it was clipped from.
    a = _series(0, 0.1, seed=5)
    b = _series(0, 4.0, seed=6)
    expected = out["w_USD"] * a + out["w_EUR"] * b
    assert out["pnl"].dropna().sub(expected.dropna()).abs().max() < 1e-9


def test_diversification_reduces_volatility():
    """CORRECTED from the brief -- see this module's docstring.

    Two independent unit-vol legs at ``target_bp_day=1.0`` are each weighted to
    ~1.0, so the book is ~``a + b``: its sd is ~sqrt(2), i.e. ABOVE either leg
    and BELOW their sum. That gap is what diversification is.
    """
    a, b = _series(0, 1.0, seed=7), _series(0, 1.0, seed=8)
    out = portfolio({"A": a, "B": b}, target_bp_day=1.0)
    leg_a = (out["w_A"] * a).dropna()
    leg_b = (out["w_B"] * b).dropna()
    book = out["pnl"].dropna()
    assert book.std() < leg_a.std() + leg_b.std()
    assert book.std() == pytest.approx(np.sqrt(2.0), rel=0.15)
    # The brief's assertion, recorded as measured-false rather than deleted.
    assert not (book.std() < max(a.std(), b.std()))


# ------------------------------------------------------- causality and the units


def test_todays_weight_cannot_know_todays_volatility():
    """The ``shift(1)``. Without it the last weight moves when the last P&L does."""
    a = _series(0, 1.0, seed=11)
    b = _series(0, 1.0, seed=12)
    base = portfolio({"A": a, "B": b}, target_bp_day=1.0)
    shocked = a.copy()
    shocked.iloc[-1] = 500.0
    after = portfolio({"A": shocked, "B": b}, target_bp_day=1.0)
    assert after["w_A"].iloc[-1] == pytest.approx(float(base["w_A"].iloc[-1]))
    # ... and the shock DOES reach the weight one day later, so this is a lag
    # rather than the series being ignored. One extra row is enough to see it.
    a2 = pd.concat([shocked, pd.Series([0.0], index=[shocked.index[-1] + pd.offsets.BDay(1)])])
    b2 = pd.concat([b, pd.Series([0.0], index=[b.index[-1] + pd.offsets.BDay(1)])])
    later = portfolio({"A": a2, "B": b2}, target_bp_day=1.0)
    assert later["w_A"].iloc[-1] < 0.5 * float(base["w_A"].iloc[-1])


def test_the_weight_is_trailing_not_full_sample():
    """A vol regime change must move the weight, and only after it happens."""
    n = 400
    idx = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.default_rng(21)
    vals = np.concatenate([rng.normal(0, 1.0, n // 2), rng.normal(0, 5.0, n - n // 2)])
    a = pd.Series(vals, index=idx)
    out = portfolio({"A": a}, target_bp_day=1.0, window=63)
    quiet = float(out["w_A"].iloc[n // 2 - 1])
    loud = float(out["w_A"].iloc[-1])
    assert quiet == pytest.approx(1.0, rel=0.3)
    assert loud == pytest.approx(0.2, rel=0.3)


def test_target_scales_the_book_linearly():
    a, b = _series(0, 1.0, seed=31), _series(0, 2.0, seed=32)
    one = portfolio({"A": a, "B": b}, target_bp_day=1.0)
    two = portfolio({"A": a, "B": b}, target_bp_day=2.0)
    assert two["pnl"].dropna().div(one["pnl"].dropna()).round(9).nunique() == 1
    assert float(two["pnl"].dropna().iloc[0] / one["pnl"].dropna().iloc[0]) == pytest.approx(2.0)


def test_the_book_realises_the_target_when_the_legs_are_independent():
    """The unit contract: ``target_bp_day`` is in the input series' own unit.

    With one market the book's sd IS the target, to sampling error. That is the
    only statement that makes the parameter's name true, and it is the reason
    the caller must feed bp/day rather than dollars.
    """
    a = _series(0, 3.0, n=2000, seed=41)
    out = portfolio({"A": a}, target_bp_day=1.0)
    assert float(out["pnl"].std()) == pytest.approx(1.0, rel=0.15)


# ------------------------------------------------------------ missing data, refusals


def test_a_market_that_has_not_started_yet_contributes_nothing():
    a = _series(0, 1.0, seed=51)
    b = _series(0, 1.0, seed=52).copy()
    b.iloc[:200] = np.nan
    out = portfolio({"A": a, "B": b}, target_bp_day=1.0)
    assert out["w_B"].iloc[:200].isna().all()
    early = out.index[100]
    assert out.loc[early, "pnl"] == pytest.approx(float(out.loc[early, "w_A"] * a.loc[early]))
    assert not np.isnan(out["w_B"].iloc[-1])


def test_a_hole_inside_a_market_blanks_its_weight_rather_than_reading_zero():
    """A missing day is missing, not a zero-P&L day.

    Cross-market calendars differ, so this is the property the caller has to
    reconcile deliberately: ``portfolio`` will not silently treat a market's
    holiday as a flat day and shrink its measured vol.
    """
    a = _series(0, 1.0, seed=61)
    b = _series(0, 1.0, seed=62).copy()
    b.iloc[300] = np.nan
    out = portfolio({"A": a, "B": b}, target_bp_day=1.0, window=63)
    assert out["w_B"].iloc[301:364].isna().all()
    assert not np.isnan(out["w_B"].iloc[365])
    # ... and the book still runs on the market that is there.
    assert not np.isnan(out["pnl"].iloc[310])


def test_a_zero_vol_market_gets_no_weight_rather_than_an_infinite_one():
    a = _series(0, 1.0, seed=71)
    flat = pd.Series(0.0, index=a.index)
    out = portfolio({"A": a, "FLAT": flat}, target_bp_day=1.0)
    assert out["w_FLAT"].isna().all()
    assert np.isfinite(out["pnl"].dropna()).all()


def test_it_refuses_an_empty_book():
    with pytest.raises(ValueError, match="at least one market"):
        portfolio({}, target_bp_day=1.0)


def test_it_refuses_a_non_positive_target():
    a = _series(0, 1.0, seed=81)
    with pytest.raises(ValueError, match="target_bp_day"):
        portfolio({"A": a}, target_bp_day=0.0)


def test_it_refuses_a_cap_on_a_market_that_is_not_in_the_book():
    """A misspelled cap is a cap that never binds, which reads as respected."""
    a = _series(0, 1.0, seed=91)
    with pytest.raises(ValueError, match="not in the book"):
        portfolio({"USD": a}, target_bp_day=1.0, caps={"USDD": 0.5})


def test_it_refuses_a_non_positive_cap():
    a = _series(0, 1.0, seed=92)
    with pytest.raises(ValueError, match="cap"):
        portfolio({"USD": a}, target_bp_day=1.0, caps={"USD": 0.0})


def test_pnl_is_a_sum_over_markets_not_an_average():
    a = _series(0, 1.0, seed=101)
    b = _series(0, 1.0, seed=102)
    c = _series(0, 1.0, seed=103)
    out = portfolio({"A": a, "B": b, "C": c}, target_bp_day=1.0)
    expected = out["w_A"] * a + out["w_B"] * b + out["w_C"] * c
    assert out["pnl"].dropna().sub(expected.dropna()).abs().max() < 1e-9
    # A mean would be a third of this; assert the level, not only the shape.
    assert float(out["pnl"].abs().mean()) > 1.5 * float((expected / 3.0).abs().mean())


def test_the_frame_carries_one_weight_column_per_market_and_pnl():
    a, b = _series(0, 1.0, seed=111), _series(0, 1.0, seed=112)
    out = portfolio({"USD": a, "JPY": b}, target_bp_day=1.0)
    assert set(out.columns) == {"w_USD", "w_JPY", "pnl"}
    assert out.index.equals(a.index)
