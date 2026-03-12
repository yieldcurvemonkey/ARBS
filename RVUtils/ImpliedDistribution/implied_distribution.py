"""Main orchestrator for SFR options implied distribution extraction.

Usage (snapshot)::

    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
    from RVUtils.ImpliedDistribution import SFRImpliedDistribution, FedScenarioConfig

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    smile = mdp.fetch_sabr_smile({
        "symbol": "SFRZ27",
        "as_of": datetime.date(2026, 3, 6),
        "strike_offsets_bps": "listed",
    })

    scenarios = FedScenarioConfig.default_sofr_scenarios(
        current_rate=4.33, n_cuts_range=[-1, 0, 1, 2, 3, 5, 9]
    )
    dist = SFRImpliedDistribution(scenario_config=scenarios)
    snapshot = dist.extract(smile)

Usage (time-series)::

    smiles = mdp.fetch_bulk_sabr_smile({
        "symbols": ["SFRZ27"],
        "timestamps": [...],
        "strike_offsets_bps": "listed",
    })
    ts = dist.extract_timeseries(smiles["SFRZ27"])
    df = dist.scenario_weights_to_dataframe(ts)
"""

from __future__ import annotations

import datetime
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Tuple

import pandas as pd

from RVUtils.ImpliedDistribution._breeden_litzenberger import extract_rnd_breeden_litzenberger
from RVUtils.ImpliedDistribution._data_prep import smile_to_rnd_input
from RVUtils.ImpliedDistribution._gaussian_mixture import extract_gaussian_mixture
from RVUtils.ImpliedDistribution._types import (
    FedScenarioConfig,
    ImpliedDistributionSnapshot,
)

if TYPE_CHECKING:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionSABRSmile


class SFRImpliedDistribution:
    """Orchestrator for SFR options implied distribution extraction."""

    def __init__(
        self,
        scenario_config: Optional[FedScenarioConfig] = None,
        *,
        smoothing_param: float = 1e-4,
        spline_order: int = 4,
        n_ghost_points: int = 10,
        ghost_extension_bps: float = 5.0,
        bin_width_bps: float = 25.0,
        use_sabr_vols: bool = True,
        optimize_mixture_stds: bool = True,
        initial_mixture_std_bps: float = 30.0,
    ):
        self.scenario_config = scenario_config
        self.smoothing_param = smoothing_param
        self.spline_order = spline_order
        self.n_ghost_points = n_ghost_points
        self.ghost_extension_bps = ghost_extension_bps
        self.bin_width_bps = bin_width_bps
        self.use_sabr_vols = use_sabr_vols
        self.optimize_mixture_stds = optimize_mixture_stds
        self.initial_mixture_std_bps = initial_mixture_std_bps

    def extract(
        self,
        smile: "STIRFutureOptionSABRSmile",
        *,
        scenario_config: Optional[FedScenarioConfig] = None,
        run_bl: bool = True,
        run_gm: bool = True,
    ) -> ImpliedDistributionSnapshot:
        """Extract implied distribution from a single smile snapshot."""
        rnd_input = smile_to_rnd_input(smile, use_sabr_vols=self.use_sabr_vols)

        bl_result = None
        gm_result = None

        if run_bl:
            bl_result = extract_rnd_breeden_litzenberger(
                rnd_input,
                smoothing_param=self.smoothing_param,
                spline_order=self.spline_order,
                n_ghost_points=self.n_ghost_points,
                ghost_extension_bps=self.ghost_extension_bps,
                bin_width_bps=self.bin_width_bps,
            )

        config = scenario_config or self.scenario_config
        if run_gm and config is not None:
            gm_result = extract_gaussian_mixture(
                rnd_input,
                config.scenarios,
                optimize_stds=self.optimize_mixture_stds,
                initial_std_bps=self.initial_mixture_std_bps,
            )

        return ImpliedDistributionSnapshot(
            symbol=str(smile.symbol),
            as_of=smile.params.as_of,
            bl_result=bl_result,
            gm_result=gm_result,
        )

    def extract_timeseries(
        self,
        smiles_by_date: Dict[datetime.date, Any],
        *,
        scenario_config: Optional[FedScenarioConfig] = None,
        run_bl: bool = True,
        run_gm: bool = True,
    ) -> "OrderedDict[datetime.date, ImpliedDistributionSnapshot]":
        """Extract implied distributions for multiple dates.

        Parameters
        ----------
        smiles_by_date : dict
            {date: STIRFutureOptionSABRSmile} — e.g. from fetch_bulk_sabr_smile().
        """
        results: OrderedDict[datetime.date, ImpliedDistributionSnapshot] = OrderedDict()
        for as_of in sorted(smiles_by_date.keys()):
            smile = smiles_by_date[as_of]
            try:
                results[as_of] = self.extract(
                    smile,
                    scenario_config=scenario_config,
                    run_bl=run_bl,
                    run_gm=run_gm,
                )
            except Exception as exc:
                import warnings

                warnings.warn(f"Failed to extract distribution for {as_of}: {exc}")
        return results

    def compare(
        self,
        smile_before: "STIRFutureOptionSABRSmile",
        smile_after: "STIRFutureOptionSABRSmile",
        *,
        scenario_config: Optional[FedScenarioConfig] = None,
        run_bl: bool = True,
        run_gm: bool = True,
    ) -> Tuple["ImpliedDistributionSnapshot", "ImpliedDistributionSnapshot"]:
        """Extract distributions from two smiles (same contract, different dates).

        Returns (snapshot_before, snapshot_after) for use with
        ``plot_distribution_change()``.
        """
        snap_before = self.extract(smile_before, scenario_config=scenario_config, run_bl=run_bl, run_gm=run_gm)
        snap_after = self.extract(smile_after, scenario_config=scenario_config, run_bl=run_bl, run_gm=run_gm)
        return snap_before, snap_after

    @staticmethod
    def scenario_weights_to_dataframe(
        ts_results: "OrderedDict[datetime.date, ImpliedDistributionSnapshot]",
    ) -> pd.DataFrame:
        """Convert time-series of GM results to a DataFrame.

        Returns DataFrame indexed by date with one column per scenario label.
        """
        rows = []
        for as_of, snapshot in ts_results.items():
            if snapshot.gm_result is None:
                continue
            row: Dict[str, Any] = {"date": as_of}
            for scenario, weight in zip(snapshot.gm_result.scenarios, snapshot.gm_result.weights):
                row[scenario.label] = float(weight)
            row["rmse"] = float(snapshot.gm_result.rmse_price)
            row["fwd_rate"] = float(snapshot.gm_result.input.forward_rate)
            rows.append(row)
        return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()

    @staticmethod
    def summary_stats_to_dataframe(
        ts_results: "OrderedDict[datetime.date, ImpliedDistributionSnapshot]",
    ) -> pd.DataFrame:
        """Convert time-series of BL results to summary stats DataFrame."""
        rows = []
        for as_of, snapshot in ts_results.items():
            if snapshot.bl_result is None:
                continue
            bl = snapshot.bl_result
            rows.append(
                {
                    "date": as_of,
                    "forward_rate": bl.input.forward_rate,
                    "mean_rate": bl.mean_rate,
                    "std_rate": bl.std_rate,
                    "skewness": bl.skewness,
                    "kurtosis": bl.kurtosis,
                    "spline_residual": bl.spline_residual,
                }
            )
        return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()
