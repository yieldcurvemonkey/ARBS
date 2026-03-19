from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Optional

import numpy as np
import pandas as pd

from Query.Base.bachelier import bachelier_greeks_fd
from Simulation.extractors import BachelierExtractor, MarketStateExtractor, SwaptionExtractor, get_extractor
from Simulation.grid import ScenarioGrid
from Simulation.scenarios import MarketState


@dataclass
class SimulationResult:
    """Scenario grid evaluation output."""

    data: np.ndarray
    coordinates: dict[str, list[Any]]
    metrics: list[str]

    def to_dataframe(self, metric: Optional[str] = None) -> pd.DataFrame:
        selected_metric = metric or self.metrics[0]
        metric_idx = self.metrics.index(selected_metric)
        axis_names = list(self.coordinates.keys())

        if not axis_names:
            return pd.DataFrame([{selected_metric: self.data[(metric_idx,)]}])

        if len(axis_names) == 1:
            axis_name = axis_names[0]
            return pd.DataFrame(
                {selected_metric: self.data[:, metric_idx]},
                index=pd.Index(self.coordinates[axis_name], name=axis_name),
            )

        if len(axis_names) == 2:
            row_axis, col_axis = axis_names
            return pd.DataFrame(
                self.data[:, :, metric_idx],
                index=pd.Index(self.coordinates[row_axis], name=row_axis),
                columns=pd.Index(self.coordinates[col_axis], name=col_axis),
            )

        records: list[dict[str, Any]] = []
        coordinate_ranges = [range(len(values)) for values in self.coordinates.values()]
        for coord_index in itertools.product(*coordinate_ranges):
            row = {
                axis_name: self.coordinates[axis_name][axis_pos]
                for axis_name, axis_pos in zip(axis_names, coord_index)
            }
            row[selected_metric] = self.data[coord_index + (metric_idx,)]
            records.append(row)
        return pd.DataFrame.from_records(records)


class SimulationEngine:
    """Stateless scenario evaluator."""

    @staticmethod
    def evaluate(
        *,
        pricer: Any,
        package: list[Any],
        risk_weights: list[float],
        grid: ScenarioGrid,
        extractor: MarketStateExtractor,
        metrics: Optional[list[str]] = None,
        entry_cost: Optional[float] = None,
    ) -> SimulationResult:
        if len(package) != len(risk_weights):
            raise ValueError("package and risk_weights must have the same length")

        requested_metrics = list(metrics) if metrics is not None else (["pnl"] if entry_cost is not None else ["npv"])
        if "pnl" in requested_metrics and entry_cost is None:
            raise ValueError("entry_cost is required when requesting pnl")

        supported_metrics = {"npv", "pnl", "price", "delta", "gamma", "vega", "theta"}
        unknown = [metric for metric in requested_metrics if metric not in supported_metrics]
        if unknown:
            raise KeyError(f"Unsupported simulation metrics: {unknown}")

        base_states = [
            extractor.extract(_resolve_pricer(pricer, leg, index), leg)
            for index, leg in enumerate(package)
        ]
        results = np.empty(grid.shape + (len(requested_metrics),), dtype=float)
        greek_metrics = {"delta", "gamma", "vega", "theta"}
        need_greeks = any(metric in greek_metrics for metric in requested_metrics)

        for point_index, (_, scenario) in enumerate(grid.scenarios()):
            multi_idx = np.unravel_index(point_index, grid.shape) if grid.shape else ()
            npv = 0.0
            price = 0.0
            greek_totals = {name: 0.0 for name in greek_metrics}

            for leg_index, (leg, risk_weight, base_state) in enumerate(zip(package, risk_weights, base_states)):
                shocked_state = scenario.mutate(base_state)
                leg_price = float(extractor.reprice(shocked_state, leg))
                quantity = _leg_quantity(leg)

                npv += float(risk_weight) * quantity * leg_price
                price += float(risk_weight) * leg_price

                if need_greeks:
                    leg_greeks = _greeks_for_state(extractor, shocked_state, leg)
                    for greek_name, greek_value in leg_greeks.items():
                        greek_totals[greek_name] += float(risk_weight) * quantity * float(greek_value)

            for metric_idx, metric_name in enumerate(requested_metrics):
                if metric_name == "npv":
                    value = npv
                elif metric_name == "pnl":
                    value = npv - float(entry_cost)
                elif metric_name == "price":
                    value = price
                else:
                    value = greek_totals[metric_name]
                results[multi_idx + (metric_idx,)] = float(value)

        return SimulationResult(
            data=results,
            coordinates=grid.coordinates,
            metrics=requested_metrics,
        )


def simulate_package(
    *,
    query: Any,
    pricer: Any,
    grid: ScenarioGrid,
    metrics: Optional[list[str]] = None,
    include_pnl: bool = True,
) -> SimulationResult:
    """Resolve a query into a package and simulate it across a scenario grid."""

    package, risk_weights = query.resolve_package(pricer_or_curve=pricer)
    value_map = query.build_value_map(
        pricer_or_curve=pricer,
        package=package,
        risk_weights=risk_weights,
    )

    extractor = get_extractor(query.product)
    entry_cost = None
    if include_pnl:
        value_id = _entry_value_id(query)
        entry_cost = value_map.apply(value=value_id)
        if metrics is None:
            metrics = ["pnl"]

    return SimulationEngine.evaluate(
        pricer=pricer,
        package=package,
        risk_weights=risk_weights,
        grid=grid,
        extractor=extractor,
        metrics=metrics,
        entry_cost=entry_cost,
    )


def _resolve_pricer(pricer: Any, leg: Any, index: int) -> Any:
    if not isinstance(pricer, Mapping):
        return pricer

    symbol = _leg_symbol(leg)
    if symbol and symbol in pricer:
        return _coerce_pricer_entry(pricer[symbol], fallback_index=index)

    matched: list[Any] = []
    flattened: list[Any] = []
    for entry in pricer.values():
        for candidate in _iter_pricer_entries(entry):
            flattened.append(candidate)
            if symbol and _leg_symbol(candidate) == symbol:
                matched.append(candidate)

    if len(matched) == 1:
        return matched[0]
    if 0 <= index < len(flattened):
        return flattened[index]

    raise KeyError(f"Could not resolve scenario pricer for symbol={symbol!r}")


def _coerce_pricer_entry(entry: Any, fallback_index: int) -> Any:
    if isinstance(entry, list):
        if not entry:
            raise KeyError("Empty pricer list entry encountered")
        if len(entry) == 1:
            return entry[0]
        if 0 <= fallback_index < len(entry):
            return entry[fallback_index]
        return entry[0]
    return entry


def _iter_pricer_entries(entry: Any) -> list[Any]:
    if isinstance(entry, list):
        return list(entry)
    return [entry]


def _leg_symbol(obj: Any) -> str:
    symbol_attr = getattr(obj, "symbol", None)
    if symbol_attr is None:
        return ""
    return str(symbol_attr() if callable(symbol_attr) else symbol_attr).strip().upper()


def _leg_quantity(leg: Any) -> float:
    quantity_attr = getattr(leg, "quantity", None)
    if quantity_attr is None:
        return 1.0
    return float(quantity_attr() if callable(quantity_attr) else quantity_attr)


def _greeks_for_state(
    extractor: MarketStateExtractor,
    state: MarketState,
    leg: Any,
) -> dict[str, float]:
    if isinstance(extractor, (BachelierExtractor, SwaptionExtractor)):
        right = leg.right() if hasattr(leg, "right") else extractor._leg_right(leg)
        delta, gamma, vega, theta = bachelier_greeks_fd(
            right=right,
            strike=float(leg.strike() if hasattr(leg, "strike") and callable(leg.strike) else leg.strike),
            forward=float(state.forward),
            vol_normal=float(state.vol_normal),
            tte=float(state.tte),
            discount=float(state.discount),
        )
        return {
            "delta": float(delta),
            "gamma": float(gamma),
            "vega": float(vega),
            "theta": float(theta),
        }

    p0 = float(extractor.reprice(state, leg))
    h_f = 0.01
    h_v = max(1e-4, abs(float(state.vol_normal)) * 0.01) if state.vol_normal is not None else 1e-4
    dt = 1.0 / 365.0

    up_f = float(extractor.reprice(replace(state, forward=float(state.forward) + h_f), leg))
    dn_f = float(extractor.reprice(replace(state, forward=float(state.forward) - h_f), leg))
    delta = (up_f - dn_f) / (2.0 * h_f)
    gamma = (up_f - 2.0 * p0 + dn_f) / (h_f * h_f)

    current_vol = float(state.vol_normal or 0.0)
    up_v = float(extractor.reprice(replace(state, vol_normal=current_vol + h_v), leg))
    dn_v = float(extractor.reprice(replace(state, vol_normal=max(current_vol - h_v, 1e-8)), leg))
    vega = (up_v - dn_v) / (2.0 * h_v)

    current_tte = max(float(state.tte or 0.0), 1e-6)
    up_t = float(extractor.reprice(replace(state, tte=current_tte + dt), leg))
    dn_t = float(extractor.reprice(replace(state, tte=max(current_tte - dt, 1e-6)), leg))
    theta = (up_t - dn_t) / (2.0 * dt)

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "vega": float(vega),
        "theta": float(theta),
    }


def _entry_value_id(query: Any) -> Any:
    value_id = query.default_mtm_value_id()
    if value_id is None:
        raise ValueError("query.default_mtm_value_id() returned None; cannot compute entry cost")

    name = str(getattr(value_id, "name", "")).upper()
    if name == "PRICE":
        enum_cls = type(value_id)
        if hasattr(enum_cls, "NPV"):
            return enum_cls.NPV
    return value_id
