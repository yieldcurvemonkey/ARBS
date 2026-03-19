from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Iterator

from Simulation.scenarios import CompositeScenario, ScenarioAxis


@dataclass(frozen=True)
class ScenarioGrid:
    """Cartesian grid of scenario axis parameter values."""

    axes: list[tuple[type[ScenarioAxis], str, list[Any]]]

    def scenarios(self) -> Iterator[tuple[tuple[Any, ...], CompositeScenario]]:
        if not self.axes:
            yield (), CompositeScenario()
            return

        value_lists = [values for _, _, values in self.axes]
        for coordinates in itertools.product(*value_lists):
            axes = tuple(
                axis_cls(**{param_name: value})
                for (axis_cls, param_name, _), value in zip(self.axes, coordinates)
            )
            yield tuple(coordinates), CompositeScenario(axes=axes)

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(len(values) for _, _, values in self.axes)

    @property
    def axis_names(self) -> list[str]:
        return [f"{axis_cls.__name__}.{param_name}" for axis_cls, param_name, _ in self.axes]

    @property
    def coordinates(self) -> dict[str, list[Any]]:
        return {
            f"{axis_cls.__name__}.{param_name}": list(values)
            for axis_cls, param_name, values in self.axes
        }
