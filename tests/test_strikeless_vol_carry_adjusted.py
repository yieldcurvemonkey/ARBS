"""Task 25 — carry-adjusted vol Column A, and its denominator guard.

Assertions are hand-arithmetic, never the implementation's own output.
"""
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol import vol_metrics as vm


def _spread_series(n: int = 200, step: float = 2.0) -> pd.Series:
    # alternating +step/-step bp changes: daily std is exactly `step` in the
    # large-window limit; use ddof=1 exact value below instead of the limit.
    changes = np.tile([step, -step], n // 2)
    return pd.Series(100.0 + np.cumsum(changes))


def test_column_a_hand_arithmetic():
    spread = _spread_series()
    sv = vm.spread_vol_bp_day(spread, window=63)
    carry = pd.Series(10.0, index=spread.index)  # +10 bp/yr, constant
    ratio = vm.carry_over_spread_vol(carry, sv)
    # hand value: daily changes are +/-2.0 alternating; rolling 63 sample std
    sample = pd.Series(np.tile([2.0, -2.0], 100)[:63])
    expected_sv = float(sample.std(ddof=1))
    expected = 10.0 / (expected_sv * np.sqrt(252.0))
    assert ratio.dropna().iloc[0] == pytest.approx(expected, rel=1e-9)
    assert ratio.attrs["measure"] == "carry_ratio"
    assert ratio.attrs["underlying"] == vm.UNDERLYING_SPREAD


def test_column_a_refuses_rate_vol():
    rates = pd.Series(np.linspace(0.04, 0.045, 200))
    rv = vm.realized_vol_bp_day(rates, window=63)
    with pytest.raises(ValueError, match="SPREAD vol"):
        vm.carry_over_spread_vol(pd.Series(1.0, index=rates.index), rv)


def test_column_a_refuses_unlabelled_hand_rolled():
    spread = _spread_series()
    hand_rolled = spread.diff().rolling(63).std()  # no builder, no label
    with pytest.raises(ValueError, match="labelled None"):
        vm.carry_over_spread_vol(pd.Series(1.0, index=spread.index), hand_rolled)


def test_column_a_is_the_mirror_of_column_b_guard():
    """The same series that Column A REQUIRES is the one Column B REFUSES."""
    spread = _spread_series()
    sv = vm.spread_vol_bp_day(spread, window=63)
    be = pd.Series(1.0, index=spread.index)
    vm.carry_over_spread_vol(pd.Series(1.0, index=spread.index), sv)  # accepted
    with pytest.raises(ValueError):
        vm.be_over_realized(be, sv)  # refused without explicit denominator


def test_zero_and_negative_denominator_is_nan_not_inf():
    spread = pd.Series(np.zeros(100))  # zero vol
    sv = vm.spread_vol_bp_day(spread, window=63)
    ratio = vm.carry_over_spread_vol(pd.Series(5.0, index=spread.index), sv)
    assert ratio.dropna().empty  # all NaN, no inf


def test_mutation_denominator_annualisation():
    """If the annualisation were dropped (the natural mutation), the hand value
    moves by sqrt(252) and the exact-equality test above must fail. Verify the
    checker catches it by computing the mutant here and asserting inequality."""
    spread = _spread_series()
    sv = vm.spread_vol_bp_day(spread, window=63)
    good = vm.carry_over_spread_vol(pd.Series(10.0, index=spread.index), sv)
    mutant = (10.0 / sv).dropna().iloc[0]  # no sqrt(252)
    assert mutant != pytest.approx(good.dropna().iloc[0], rel=1e-3)
