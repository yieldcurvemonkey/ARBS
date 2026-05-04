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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd

from RVUtils.ImpliedDistribution._breeden_litzenberger import extract_rnd_breeden_litzenberger
from RVUtils.ImpliedDistribution._data_prep import smile_to_rnd_input
from RVUtils.ImpliedDistribution._gaussian_mixture import extract_gaussian_mixture
from RVUtils.ImpliedDistribution._joint_calibration import calibrate_joint_distribution
from RVUtils.ImpliedDistribution._joint_export import (
    conditional_distribution_to_dataframe as _conditional_distribution_to_dataframe,
    joint_delta_to_dataframe as _joint_delta_to_dataframe,
    joint_marginal_to_dataframe as _joint_marginal_to_dataframe,
    joint_pair_matrix_to_dataframe as _joint_pair_matrix_to_dataframe,
    joint_state_probabilities_to_dataframe as _joint_state_probabilities_to_dataframe,
    linear_combination_to_dataframe as _linear_combination_to_dataframe,
    top_pair_cell_changes_to_dataframe as _top_pair_cell_changes_to_dataframe,
)
from RVUtils.ImpliedDistribution._types import (
    FedScenarioConfig,
    FOMCPathStateConfig,
    ImpliedDistributionSnapshot,
    JointDistributionComparison,
    JointDistributionSnapshot,
    StripComparisonResult,
)

if TYPE_CHECKING:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionSABRSmile


class SFRImpliedDistribution:
    """Orchestrator for SFR options implied distribution extraction.

    Defaults follow the JPM raw-premium Breeden-Litzenberger workflow:
    observed OTM premiums, put-call parity, ``OI >= 100``, a literal
    ``1e-4`` smoothing parameter, 10 ghost points, and native 25bp bins.
    Pass ``use_sabr_vols=True`` and ``sabr_extrapolation=True`` for the
    older ARBS SABR-resampled smooth-tail hybrid.

    Caveats and known limitations
    -----------------------------
    * **Bachelier European pricing only.** SR3 options are American on the
      future, but for short-dated instruments the early-exercise premium is
      small and ignored here. Avoid relying on this module for options with
      less than ~10 business days to expiry.
    * **Wing extrapolation uses linear "ghost" anchor points** at the ends of
      the strike grid - not SVI or rational interpolation. If callers opt into
      SABR resampling, tails are also sensitive to the SABR beta/rho/nu
      parameters; check ``BreedenLitzenbergerResult.warnings`` for truncation
      or clipping flags before relying on extreme percentiles.
    * **Default rate floor is 0.0.** This truncates the SOFR density below
      zero. Mass lost to truncation is reported in
      ``BreedenLitzenbergerResult.warnings``; the reported ``mean_rate`` /
      ``std_rate`` are computed on the truncated domain.
    * **Spline 2nd-derivative artefacts.** Sparse strike grids and aggressive
      smoothing parameters can yield small negative density at the wings.
      Negative mass is clipped silently if it is below 0.01% of total mass and
      reported in ``warnings`` otherwise.
    * **Gaussian-mixture optimizer.** SLSQP can fail to converge on
      ill-conditioned smiles; failures and high-RMSE fits are flagged in
      ``GaussianMixtureResult.warnings``.

    Legacy SABR note
    ---------------------------------
    The old ARBS SABR-smoothed hybrid can still be selected with
    ``use_sabr_vols=True`` and ``sabr_extrapolation=True``. In that mode,
    the spline mechanics still use the same 4th-order spline, smoothing
    parameter 1e-4, 10 ghost points per side, and 25bp bins.
    """

    def __init__(
        self,
        scenario_config: Optional[FedScenarioConfig] = None,
        *,
        smoothing_param: float = 1e-4,
        scale_smoothing_by_n: bool = False,
        spline_order: int = 4,
        n_ghost_points: int = 10,
        ghost_extension_bps: float = 5.0,
        bin_width_bps: float = 25.0,
        use_sabr_vols: bool = False,
        sabr_extrapolation: bool = False,
        sabr_rate_floor: float = 0.0,
        sabr_rate_ceiling_nstdev: float = 6.0,
        sabr_n_strikes: int = 200,
        raw_market_open_interest_min: Optional[float] = 100.0,
        raw_market_otm_only: bool = True,
        optimize_mixture_stds: bool = True,
        initial_mixture_std_bps: float = 30.0,
    ):
        self.scenario_config = scenario_config
        self.smoothing_param = smoothing_param
        self.scale_smoothing_by_n = scale_smoothing_by_n
        self.spline_order = spline_order
        self.n_ghost_points = n_ghost_points
        self.ghost_extension_bps = ghost_extension_bps
        self.bin_width_bps = bin_width_bps
        self.use_sabr_vols = use_sabr_vols
        self.sabr_extrapolation = sabr_extrapolation
        self.sabr_rate_floor = sabr_rate_floor
        self.sabr_rate_ceiling_nstdev = sabr_rate_ceiling_nstdev
        self.sabr_n_strikes = sabr_n_strikes
        self.raw_market_open_interest_min = raw_market_open_interest_min
        self.raw_market_otm_only = raw_market_otm_only
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
        config = scenario_config or self.scenario_config

        # scenarios_only: skip BL, use only GM scenario weights as the distribution
        if config is not None and config.scenarios_only:
            run_bl = False
            run_gm = True

        rnd_input = smile_to_rnd_input(
            smile,
            use_sabr_vols=self.use_sabr_vols,
            sabr_extrapolation=self.sabr_extrapolation,
            sabr_rate_floor=self.sabr_rate_floor,
            sabr_rate_ceiling_nstdev=self.sabr_rate_ceiling_nstdev,
            sabr_n_strikes=self.sabr_n_strikes,
            raw_market_open_interest_min=self.raw_market_open_interest_min,
            raw_market_otm_only=self.raw_market_otm_only,
        )

        bl_result = None
        gm_result = None

        if run_bl:
            bl_result = extract_rnd_breeden_litzenberger(
                rnd_input,
                smoothing_param=self.smoothing_param,
                scale_smoothing_by_n=self.scale_smoothing_by_n,
                spline_order=self.spline_order,
                n_ghost_points=self.n_ghost_points,
                ghost_extension_bps=self.ghost_extension_bps,
                bin_width_bps=self.bin_width_bps,
                rate_floor=self.sabr_rate_floor,
            )

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

    def compare_strip(
        self,
        smiles_before: Dict[str, "STIRFutureOptionSABRSmile"],
        smiles_after: Dict[str, "STIRFutureOptionSABRSmile"],
        *,
        symbols: Optional[Union[str, Sequence[str]]] = None,
        as_of: Optional[datetime.date] = None,
        scenario_config: Optional[FedScenarioConfig] = None,
        run_bl: bool = True,
        run_gm: bool = True,
    ) -> StripComparisonResult:
        """Compare implied distributions across a strip/bundle between two dates.

        Parameters
        ----------
        smiles_before : dict
            {symbol: STIRFutureOptionSABRSmile} for the earlier date.
        smiles_after : dict
            {symbol: STIRFutureOptionSABRSmile} for the later date.
        symbols : str or list of str, optional
            Strip preset (``"whites"``, ``"reds"``, ``"greens"``, ``"blues"``,
            ``"2y"``, ``"3y"``) or explicit symbol list. If None, uses the
            union of keys from both smile dicts (sorted).
        as_of : date, optional
            Reference date for resolving preset bundle names. Required when
            ``symbols`` is a preset string.
        scenario_config : FedScenarioConfig, optional
            Override the instance-level scenario config.
        run_bl, run_gm : bool
            Which approaches to run.

        Returns
        -------
        StripComparisonResult

        Usage::

            from RVUtils.ImpliedDistribution import SFRImpliedDistribution, resolve_strip_symbols

            # Option A: preset bundle
            syms = resolve_strip_symbols("whites", as_of=date2)
            smiles_d1 = {s: mdp.fetch_sabr_smile({...}) for s in syms}
            smiles_d2 = {s: mdp.fetch_sabr_smile({...}) for s in syms}
            result = dist.compare_strip(smiles_d1, smiles_d2, symbols="whites", as_of=date2)

            # Option B: explicit symbols
            result = dist.compare_strip(smiles_d1, smiles_d2, symbols=["SFRZ26", "SFRZ27"])

            # Option C: infer from dict keys
            result = dist.compare_strip(smiles_d1, smiles_d2)
        """
        strip_label: Optional[str] = None

        if symbols is not None:
            if isinstance(symbols, str) and not symbols.upper().startswith("SFR"):
                # Preset name
                from RVUtils.ImpliedDistribution._strip_utils import resolve_strip_symbols

                strip_label = symbols.lower()
                sym_list = resolve_strip_symbols(symbols, as_of=as_of)
            elif isinstance(symbols, str):
                sym_list = [symbols.upper()]
            else:
                sym_list = list(symbols)
        else:
            # Infer from smile dict keys
            sym_list = sorted(set(smiles_before.keys()) | set(smiles_after.keys()))

        snapshots_before: Dict[str, ImpliedDistributionSnapshot] = {}
        snapshots_after: Dict[str, ImpliedDistributionSnapshot] = {}

        for sym in sym_list:
            if sym in smiles_before:
                try:
                    snapshots_before[sym] = self.extract(
                        smiles_before[sym],
                        scenario_config=scenario_config,
                        run_bl=run_bl,
                        run_gm=run_gm,
                    )
                except Exception as exc:
                    import warnings

                    warnings.warn(f"Failed to extract distribution for {sym} (before): {exc}")

            if sym in smiles_after:
                try:
                    snapshots_after[sym] = self.extract(
                        smiles_after[sym],
                        scenario_config=scenario_config,
                        run_bl=run_bl,
                        run_gm=run_gm,
                    )
                except Exception as exc:
                    import warnings

                    warnings.warn(f"Failed to extract distribution for {sym} (after): {exc}")

        # Determine dates from first available snapshot
        date_before = next(
            (s.as_of for s in snapshots_before.values()), datetime.date.min
        )
        date_after = next(
            (s.as_of for s in snapshots_after.values()), datetime.date.min
        )

        return StripComparisonResult(
            symbols=sym_list,
            date_before=date_before,
            date_after=date_after,
            snapshots_before=snapshots_before,
            snapshots_after=snapshots_after,
            strip_label=strip_label,
        )

    def extract_joint(
        self,
        smiles_by_symbol: Dict[str, "STIRFutureOptionSABRSmile"],
        *,
        state_config: FOMCPathStateConfig,
        run_bl: bool = True,
        run_legacy_gm: bool = True,
    ) -> JointDistributionSnapshot:
        """Calibrate a shared common-state joint distribution across a basket."""
        if not smiles_by_symbol:
            raise ValueError("extract_joint requires at least one smile")

        rnd_inputs_by_symbol: Dict[str, Any] = {}
        contract_snapshots: Dict[str, ImpliedDistributionSnapshot] = {}

        for symbol, smile in smiles_by_symbol.items():
            sym = str(symbol).upper()
            rnd_inputs_by_symbol[sym] = smile_to_rnd_input(
                smile,
                use_sabr_vols=self.use_sabr_vols,
                sabr_extrapolation=self.sabr_extrapolation,
                sabr_rate_floor=self.sabr_rate_floor,
                sabr_rate_ceiling_nstdev=self.sabr_rate_ceiling_nstdev,
                sabr_n_strikes=self.sabr_n_strikes,
                raw_market_open_interest_min=self.raw_market_open_interest_min,
                raw_market_otm_only=self.raw_market_otm_only,
            )
            if run_bl or run_legacy_gm:
                try:
                    contract_snapshots[sym] = self.extract(
                        smile,
                        run_bl=run_bl,
                        run_gm=run_legacy_gm,
                    )
                except Exception as exc:
                    import warnings

                    warnings.warn(f"Failed to build legacy marginal snapshot for {sym}: {exc}")
                    contract_snapshots[sym] = ImpliedDistributionSnapshot(
                        symbol=sym,
                        as_of=smile.params.as_of,
                        bl_result=None,
                        gm_result=None,
                    )
            else:
                contract_snapshots[sym] = ImpliedDistributionSnapshot(
                    symbol=sym,
                    as_of=smile.params.as_of,
                    bl_result=None,
                    gm_result=None,
                )

        return calibrate_joint_distribution(
            rnd_inputs_by_symbol,
            contract_snapshots=contract_snapshots,
            state_config=state_config,
            optimize_stds=self.optimize_mixture_stds,
            initial_std_bps=self.initial_mixture_std_bps,
        )

    def compare_joint(
        self,
        smiles_before: Dict[str, "STIRFutureOptionSABRSmile"],
        smiles_after: Dict[str, "STIRFutureOptionSABRSmile"],
        *,
        symbols: Optional[Union[str, Sequence[str]]] = None,
        as_of: Optional[datetime.date] = None,
        state_config: FOMCPathStateConfig,
        run_bl: bool = True,
        run_legacy_gm: bool = True,
    ) -> JointDistributionComparison:
        """Compare a shared common-state joint distribution across two dates."""
        if symbols is not None:
            if isinstance(symbols, str) and not symbols.upper().startswith("SFR"):
                from RVUtils.ImpliedDistribution._strip_utils import resolve_strip_symbols

                sym_list = resolve_strip_symbols(symbols, as_of=as_of)
            elif isinstance(symbols, str):
                sym_list = [symbols.upper()]
            else:
                sym_list = [str(sym).upper() for sym in symbols]
        else:
            sym_list = sorted(set(smiles_before.keys()) & set(smiles_after.keys()))

        if not sym_list:
            raise ValueError("compare_joint requires at least one symbol present on both dates")

        missing_before = [sym for sym in sym_list if sym not in smiles_before]
        missing_after = [sym for sym in sym_list if sym not in smiles_after]
        if missing_before or missing_after:
            raise ValueError(
                f"Joint comparison requires all selected symbols on both dates. "
                f"Missing before={missing_before}, missing after={missing_after}"
            )

        snap_before = self.extract_joint(
            {sym: smiles_before[sym] for sym in sym_list},
            state_config=state_config,
            run_bl=run_bl,
            run_legacy_gm=run_legacy_gm,
        )
        snap_after = self.extract_joint(
            {sym: smiles_after[sym] for sym in sym_list},
            state_config=state_config,
            run_bl=run_bl,
            run_legacy_gm=run_legacy_gm,
        )
        return JointDistributionComparison(
            symbols=sym_list,
            date_before=snap_before.as_of,
            date_after=snap_after.as_of,
            snapshot_before=snap_before,
            snapshot_after=snap_after,
        )

    @staticmethod
    def strip_summary_to_dataframe(
        result: StripComparisonResult,
    ) -> pd.DataFrame:
        """Convert a strip comparison to a summary DataFrame.

        Returns DataFrame indexed by symbol with columns for forward rate,
        mean, std, skew, kurtosis at both dates, plus deltas.
        """
        rows = []
        for sym in result.symbols:
            snap1 = result.snapshots_before.get(sym)
            snap2 = result.snapshots_after.get(sym)
            row: Dict[str, Any] = {"symbol": sym}

            bl1 = snap1.bl_result if snap1 else None
            bl2 = snap2.bl_result if snap2 else None

            if bl1:
                row["fwd_before"] = bl1.input.forward_rate
                row["mean_before"] = bl1.mean_rate
                row["std_before"] = bl1.std_rate
                row["skew_before"] = bl1.skewness
            if bl2:
                row["fwd_after"] = bl2.input.forward_rate
                row["mean_after"] = bl2.mean_rate
                row["std_after"] = bl2.std_rate
                row["skew_after"] = bl2.skewness
            if bl1 and bl2:
                row["fwd_delta"] = bl2.input.forward_rate - bl1.input.forward_rate
                row["mean_delta"] = bl2.mean_rate - bl1.mean_rate
                row["std_delta"] = bl2.std_rate - bl1.std_rate
                row["skew_delta"] = bl2.skewness - bl1.skewness

            gm1 = snap1.gm_result if snap1 else None
            gm2 = snap2.gm_result if snap2 else None
            if gm1:
                for s, w in zip(gm1.scenarios, gm1.weights):
                    row[f"w_{s.label}_before"] = float(w)
            if gm2:
                for s, w in zip(gm2.scenarios, gm2.weights):
                    row[f"w_{s.label}_after"] = float(w)

            rows.append(row)
        return pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()

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

    @staticmethod
    def joint_state_probabilities_to_dataframe(snapshot: JointDistributionSnapshot) -> pd.DataFrame:
        return _joint_state_probabilities_to_dataframe(snapshot)

    @staticmethod
    def joint_pair_matrix_to_dataframe(
        snapshot: JointDistributionSnapshot,
        *,
        symbol_x: str,
        symbol_y: str,
    ) -> pd.DataFrame:
        return _joint_pair_matrix_to_dataframe(snapshot, symbol_x=symbol_x, symbol_y=symbol_y)

    @staticmethod
    def joint_marginal_to_dataframe(snapshot: JointDistributionSnapshot, *, symbol: str) -> pd.DataFrame:
        return _joint_marginal_to_dataframe(snapshot, symbol=symbol)

    @staticmethod
    def conditional_distribution_to_dataframe(
        snapshot: JointDistributionSnapshot,
        *,
        target_symbol: str,
        given_symbol: str,
        given_values: Optional[Sequence[float]] = None,
        given_range: Optional[Tuple[float, float]] = None,
    ) -> pd.DataFrame:
        return _conditional_distribution_to_dataframe(
            snapshot,
            target_symbol=target_symbol,
            given_symbol=given_symbol,
            given_values=given_values,
            given_range=given_range,
        )

    @staticmethod
    def linear_combination_to_dataframe(
        snapshot: JointDistributionSnapshot,
        *,
        weights: Dict[str, float],
    ) -> pd.DataFrame:
        return _linear_combination_to_dataframe(snapshot, weights=weights)

    @staticmethod
    def joint_delta_to_dataframe(
        comparison: JointDistributionComparison,
        *,
        symbol_x: str,
        symbol_y: str,
    ) -> pd.DataFrame:
        return _joint_delta_to_dataframe(comparison, symbol_x=symbol_x, symbol_y=symbol_y)

    @staticmethod
    def top_pair_cell_changes_to_dataframe(
        comparison: JointDistributionComparison,
        *,
        symbol_x: str,
        symbol_y: str,
        n: int = 10,
    ) -> pd.DataFrame:
        return _top_pair_cell_changes_to_dataframe(comparison, symbol_x=symbol_x, symbol_y=symbol_y, n=n)
