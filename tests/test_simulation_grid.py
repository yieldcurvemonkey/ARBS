import pytest

from Simulation.grid import ScenarioGrid
from Simulation.scenarios import MarketState, TimeDecay, UnderlyingShift


class TestScenarioGrid:
    def test_shape(self):
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1, 0, 1]),
                (TimeDecay, "days", [0, 7, 14]),
            ]
        )
        assert grid.shape == (3, 3)

    def test_axis_names(self):
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1, 0, 1]),
                (TimeDecay, "days", [0, 7]),
            ]
        )
        assert grid.axis_names == ["UnderlyingShift.shift", "TimeDecay.days"]

    def test_scenarios_count(self):
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1, 0, 1]),
                (TimeDecay, "days", [0, 7]),
            ]
        )
        assert len(list(grid.scenarios())) == 6

    def test_scenarios_coordinates(self):
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1, 0]),
                (TimeDecay, "days", [0, 7]),
            ]
        )
        coords = [coord for coord, _ in grid.scenarios()]
        assert coords == [(-1, 0), (-1, 7), (0, 0), (0, 7)]

    def test_scenarios_mutate_correctly(self):
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [1.0]),
                (TimeDecay, "days", [7]),
            ]
        )
        scenarios = list(grid.scenarios())
        assert len(scenarios) == 1
        coords, composite = scenarios[0]
        assert coords == (1.0, 7)

        base = MarketState(forward=95.0, tte=0.25, eval_date=None, vol_normal=0.005, discount=0.998)
        result = composite.mutate(base)
        assert result.forward == pytest.approx(96.0)
        assert result.tte == pytest.approx(0.25 - 7.0 / 365.0)

    def test_1d_grid(self):
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [-2, -1, 0, 1, 2])])
        assert grid.shape == (5,)
        assert len(list(grid.scenarios())) == 5

    def test_coordinates_property(self):
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1, 0, 1]),
                (TimeDecay, "days", [0, 30]),
            ]
        )
        assert grid.coordinates == {
            "UnderlyingShift.shift": [-1, 0, 1],
            "TimeDecay.days": [0, 30],
        }
