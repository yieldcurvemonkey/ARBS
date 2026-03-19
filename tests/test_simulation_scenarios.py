import datetime

import pytest

from Simulation.scenarios import CompositeScenario, MarketState, TimeDecay, UnderlyingShift, VolShift


def _base_state() -> MarketState:
    return MarketState(
        forward=95.75,
        vol_normal=0.0050,
        discount=0.998,
        tte=0.25,
        eval_date=datetime.date(2026, 3, 16),
    )


class TestUnderlyingShift:
    def test_positive_shift(self):
        state = _base_state()
        result = UnderlyingShift(shift=1.0).mutate(state)
        assert result.forward == pytest.approx(96.75)
        assert result.vol_normal == state.vol_normal
        assert result.discount == state.discount
        assert result.tte == state.tte
        assert result.eval_date == state.eval_date

    def test_negative_shift(self):
        state = _base_state()
        result = UnderlyingShift(shift=-2.5).mutate(state)
        assert result.forward == pytest.approx(93.25)

    def test_zero_shift_is_identity(self):
        state = _base_state()
        assert UnderlyingShift(shift=0.0).mutate(state) == state


class TestVolShift:
    def test_positive_vol_shift(self):
        state = _base_state()
        result = VolShift(shift_bps=10.0).mutate(state)
        assert result.vol_normal == pytest.approx(0.0050 + 10.0 * 0.0001)

    def test_negative_vol_shift(self):
        state = _base_state()
        result = VolShift(shift_bps=-5.0).mutate(state)
        assert result.vol_normal == pytest.approx(0.0050 - 5.0 * 0.0001)


class TestTimeDecay:
    def test_time_decay_reduces_tte(self):
        state = _base_state()
        result = TimeDecay(days=30).mutate(state)
        assert result.tte == pytest.approx(0.25 - 30.0 / 365.0)
        assert result.eval_date == datetime.date(2026, 4, 15)

    def test_time_decay_floors_at_zero(self):
        state = _base_state()
        result = TimeDecay(days=365).mutate(state)
        assert result.tte == 0.0

    def test_zero_days_is_identity(self):
        state = _base_state()
        assert TimeDecay(days=0).mutate(state) == state


class TestCompositeScenario:
    def test_applies_axes_sequentially(self):
        state = _base_state()
        composite = CompositeScenario(
            axes=(
                UnderlyingShift(shift=1.0),
                TimeDecay(days=7),
            )
        )
        result = composite.mutate(state)
        assert result.forward == pytest.approx(96.75)
        assert result.tte == pytest.approx(0.25 - 7.0 / 365.0)
        assert result.eval_date == datetime.date(2026, 3, 23)

    def test_empty_composite_is_identity(self):
        state = _base_state()
        assert CompositeScenario().mutate(state) == state

    def test_nested_composites(self):
        state = _base_state()
        inner = CompositeScenario(axes=(UnderlyingShift(shift=1.0),))
        outer = CompositeScenario(axes=(inner, VolShift(shift_bps=5.0)))
        result = outer.mutate(state)
        assert result.forward == pytest.approx(96.75)
        assert result.vol_normal == pytest.approx(0.0050 + 5.0 * 0.0001)


class TestImmutability:
    def test_market_state_is_frozen(self):
        state = _base_state()
        with pytest.raises(AttributeError):
            state.forward = 100.0

    def test_scenario_axis_is_frozen(self):
        axis = UnderlyingShift(shift=1.0)
        with pytest.raises(AttributeError):
            axis.shift = 2.0
