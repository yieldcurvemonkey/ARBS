"""Top-level orchestrator for SR3 vs ZQ distribution-comparison screener.

``build_snapshot(config, as_of)`` runs the full pipeline:
    1. Resolve SR3 contracts (from config or auto-pick nearest 3 quarterlies)
    2. For each contract:
        a. Fetch ZQ prices over the relevant months
        b. Build FedWatch tree
        c. Compute day-weighted meeting variance
        d. Fetch SABR smile, extract RND (with optional λ optimization)
        e. Decompose variance, compute skew + tail mass
        f. Classify regime
    3. Compute cross-quarter term-structure signal across all contracts
    4. Emit per-contract trade flags
    5. Return ``ScreenerSnapshot``
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Callable, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import (
    _imm_cutoff,
    _next_contracts,
)
from MDP.STIRFutures._sofr_option_contracts import _contract_expiry_date
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig as _AsymConfig
from SDRUtils.analytics.fomc import load_fomc_schedule

from RVUtils.SR3ZQDistributionScreener._fedwatch import (
    build_fedwatch_tree,
    contract_for_month,
    months_in_range,
)
from RVUtils.SR3ZQDistributionScreener._lambda_opt import (
    optimize_smoothing_lambda,
)
from RVUtils.SR3ZQDistributionScreener._output import ScreenerSnapshot
from RVUtils.SR3ZQDistributionScreener._regime import classify_regime
from RVUtils.SR3ZQDistributionScreener._signals import (
    compute_signals,
    signal_cross_quarter,
)
from RVUtils.SR3ZQDistributionScreener._types import (
    DistributionScreenerConfig,
    RegimeBucket,
    SignalRecord,
)
from RVUtils.SR3ZQDistributionScreener._variance import (
    day_weighted_meeting_variance_bp2,
    meeting_nodes_from_states,
)

logger = logging.getLogger(__name__)


def _resolve_contracts(
    config: DistributionScreenerConfig, *, as_of: datetime.date
) -> List[str]:
    if config.sr3_contracts:
        return list(config.sr3_contracts)
    candidates = _next_contracts(
        start_date=as_of,
        prefix="SFR",
        count=8,
        valid_months=[3, 6, 9, 12],
        cutoff_fn=_imm_cutoff,
    )
    out = []
    for c in candidates:
        try:
            expiry = _contract_expiry_date(c[-3:])
        except Exception:
            continue
        dte = (expiry - as_of).days
        if config.dte_floor <= dte <= config.dte_ceiling:
            out.append(c)
    return out[:4]


def _zq_months_for_ref(
    as_of: datetime.date,
    ref_start: datetime.date,
    ref_end: datetime.date,
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Pad ref_end by one month for FedWatch anchor-month coverage."""
    start = (as_of.year, as_of.month)
    y, m = ref_end.year, ref_end.month + 1
    if m == 13:
        m = 1
        y += 1
    return start, (y, m)


def _fetch_zq_prices(
    *,
    symbols: List[str],
    as_of: datetime.date,
    futures_source: str,
) -> dict:
    fut_mdp = STIRFutureMDP(source=futures_source)
    snap = fut_mdp.get_data({"symbols": symbols, "timestamp": as_of})
    out: dict = {}
    for sym in symbols:
        pricers = snap.get(sym) or []
        if pricers:
            p = pricers[0]
            price = getattr(p, "_price", None) or getattr(p, "price", None)
            if price is not None:
                try:
                    out[sym] = float(price)
                except (TypeError, ValueError):
                    pass
    return out


def _compute_per_contract(
    *,
    sr3_contract: str,
    as_of: datetime.date,
    config: DistributionScreenerConfig,
) -> Tuple[Optional[SignalRecord], List[str]]:
    """Pipeline for one (as_of, sr3_contract). Returns (record, warnings)."""
    warnings: List[str] = []

    # Reference period
    try:
        expiry = _contract_expiry_date(sr3_contract[-3:])
    except Exception as exc:
        warnings.append(f"expiry_decode_failed:{sr3_contract}:{exc}")
        return None, warnings

    ref_start = expiry
    ref_end = expiry + datetime.timedelta(days=config.ref_period_days)
    ref_days = (ref_end - ref_start).days
    zq_range = _zq_months_for_ref(as_of, ref_start, ref_end)

    # ZQ prices
    months = months_in_range(
        datetime.date(zq_range[0][0], zq_range[0][1], 1),
        datetime.date(zq_range[1][0], zq_range[1][1], 1),
    )
    zq_symbols = [contract_for_month(y, m) for y, m in months]
    try:
        zq_prices = _fetch_zq_prices(
            symbols=zq_symbols, as_of=as_of, futures_source=config.futures_source
        )
    except Exception as exc:
        warnings.append(f"zq_fetch_failed:{exc}")
        return None, warnings
    if not zq_prices:
        warnings.append(f"no_zq_prices:{sr3_contract}")
        return None, warnings

    # FOMC schedule
    fomc_full = load_fomc_schedule("USD-SOFR-1D")
    fomc_full["effective_date"] = pd.to_datetime(fomc_full["effective_date"]).dt.date
    period_lo = datetime.date(zq_range[0][0], zq_range[0][1], 1)
    period_hi = datetime.date(zq_range[1][0], zq_range[1][1], 28)
    fomc_in_range = fomc_full[
        (fomc_full["effective_date"] >= period_lo)
        & (fomc_full["effective_date"] <= period_hi)
    ]

    # Build tree
    try:
        states = build_fedwatch_tree(
            zq_prices=zq_prices,
            fomc_schedule=fomc_in_range,
            months_range=zq_range,
        )
    except Exception as exc:
        warnings.append(f"fedwatch_failed:{sr3_contract}:{exc}")
        return None, warnings

    # Meeting nodes inside ref period
    meetings_in_period = sorted(
        m for m in fomc_in_range["effective_date"]
        if ref_start <= m <= ref_end
    )
    nodes = meeting_nodes_from_states(states, meetings_in_period)

    zq_var_bp2, _ = day_weighted_meeting_variance_bp2(
        nodes, ref_start=ref_start, ref_end=ref_end
    )

    # SR3 smile + RND (with optional λ optimization)
    opt_mdp = STIRFutureOptionMDP(source=config.options_source)
    try:
        smile = opt_mdp.fetch_sabr_smile(
            {"symbol": sr3_contract, "as_of": as_of, "strike_offsets_bps": "listed"}
        )
    except Exception as exc:
        warnings.append(f"smile_fetch_failed:{sr3_contract}:{exc}")
        return None, warnings

    try:
        if config.optimize_lambda:
            chosen_lambda, rnd, _ = optimize_smoothing_lambda(
                smile=smile, as_of=as_of, grid=config.lambda_grid,
            )
        else:
            chosen_lambda = config.rnd_smoothing_param
            asym_cfg = _AsymConfig()
            asym_cfg.rnd_smoothing_param = chosen_lambda
            asym_cfg.rnd_spline_order = config.rnd_spline_order
            asym_cfg.rnd_n_ghost_points = config.rnd_n_ghost_points
            rnd = extract_per_expiry_rnd(
                smile=smile, leg_market={}, config=asym_cfg, as_of=as_of
            )
    except Exception as exc:
        warnings.append(f"rnd_failed:{sr3_contract}:{exc}")
        return None, warnings

    sr3_total_var_bp2 = (rnd.std_rate * 100.0) ** 2
    fwd_rate_pct = 100.0 - smile.params.forward_price

    # Variance decomposition
    intermeeting_drift_var_bp2 = (config.intermeeting_daily_vol_bp ** 2) * ref_days
    basis_var_bp2 = config.basis_var_bp2
    explained = zq_var_bp2 + basis_var_bp2 + intermeeting_drift_var_bp2
    residual = sr3_total_var_bp2 - explained
    ratio = residual / explained if explained > 0 else float("nan")

    # Tail mass
    grid = rnd.strike_grid_rate
    pdf = rnd.density_pdf

    def _tail_below(threshold_pct):
        mask = grid <= threshold_pct
        return float(trapezoid(pdf[mask], grid[mask])) if mask.any() else 0.0

    def _tail_above(threshold_pct):
        mask = grid >= threshold_pct
        return float(trapezoid(pdf[mask], grid[mask])) if mask.any() else 0.0

    tail_lower_50 = _tail_below(fwd_rate_pct - 0.50)
    tail_lower_75 = _tail_below(fwd_rate_pct - 0.75)
    tail_lower_100 = _tail_below(fwd_rate_pct - 1.00)
    tail_upper_50 = _tail_above(fwd_rate_pct + 0.50)
    tail_upper_75 = _tail_above(fwd_rate_pct + 0.75)
    tail_upper_100 = _tail_above(fwd_rate_pct + 1.00)

    # Regime classification
    regime = classify_regime(
        residual_ratio=ratio,
        skew=rnd.skew,
        tail_upper_50bp=tail_upper_50,
        config=config,
    )

    # Copula coordinate. Wrapped because the measurement legitimately does not apply on
    # every session (fewer than two resolved meetings, a fractional day-weight, a mixed
    # hike/cut set), and an inapplicable measurement must not take the whole record down.
    lam = None
    try:
        from RVUtils.SR3ZQDistributionScreener._lambda_signal import (
            measure_lambda_from_rnd_record,
        )

        lam = measure_lambda_from_rnd_record(
            record=rnd,
            as_of=as_of,
            symbol=sr3_contract,
            zq_prices=zq_prices,
            fomc_schedule=fomc_in_range,
            expiry=expiry,
            non_meeting_vol_bp_per_sqrt_year=config.intermeeting_daily_vol_bp * (252.0 ** 0.5),
        )
        if not lam.ok:
            warnings.append(f"lambda_not_applicable:{sr3_contract}:{lam.reason}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"lambda_failed:{sr3_contract}:{exc}")

    # Per-contract flags (without cross-quarter — handled outside this fn)
    flags = compute_signals(
        residual_ratio=ratio,
        skew=rnd.skew,
        tail_upper_50bp=tail_upper_50,
        tail_lower_50bp=tail_lower_50,
        tail_upper_100bp=tail_upper_100,
        tail_lower_100bp=tail_lower_100,
        regime=regime,
        residual_ratios_by_contract=(),  # cross-quarter computed at orchestrator level
        config=config,
        lambda_wing=(lam.lambda_wing if lam is not None and lam.ok else float("nan")),
        lambda_prior=0.0,  # the independent coupling: the natural null, not a fitted prior
        # A daily screener has no trailing window of its own, so the z here is the raw
        # distance from the null in wing-mass units. A backtest standardises properly.
        lambda_z=(lam.lambda_wing if lam is not None and lam.ok else float("nan")),
        hard_violation_bp2=(lam.hard_violation_bp2 if lam is not None and lam.ok else 0.0),
        lambda_atom_spread=(lam.lambda_atom_spread if lam is not None and lam.ok else float("nan")),
    )

    record = SignalRecord(
        as_of=as_of,
        sr3_contract=sr3_contract,
        sr3_dte=(expiry - as_of).days,
        ref_start=ref_start,
        ref_end=ref_end,
        forward_price=float(smile.params.forward_price),
        forward_rate=fwd_rate_pct,
        n_meetings_in_period=len(nodes),
        fedwatch_meeting_labels=tuple(n.label for n in nodes),
        fedwatch_expected_changes_bp=tuple(n.expected_change_bp for n in nodes),
        sr3_total_var_bp2=float(sr3_total_var_bp2),
        zq_day_weighted_var_bp2=float(zq_var_bp2),
        intermeeting_drift_var_bp2=float(intermeeting_drift_var_bp2),
        basis_var_bp2=float(basis_var_bp2),
        explained_var_bp2=float(explained),
        residual_var_bp2=float(residual),
        residual_to_explained_ratio=float(ratio),
        sr3_skew=float(rnd.skew),
        sr3_kurt=float(rnd.kurt),
        tail_lower_50=tail_lower_50,
        tail_lower_75=tail_lower_75,
        tail_lower_100=tail_lower_100,
        tail_upper_50=tail_upper_50,
        tail_upper_75=tail_upper_75,
        tail_upper_100=tail_upper_100,
        lambda_wing=(lam.lambda_wing if lam is not None else float("nan")),
        lambda_wing_strict=(lam.lambda_wing_raw if lam is not None else float("nan")),
        lambda_var=(lam.lambda_var if lam is not None else float("nan")),
        lambda_atom_spread=(lam.lambda_atom_spread if lam is not None else float("nan")),
        lambda_ok=bool(lam.ok) if lam is not None else False,
        lambda_reason=(lam.reason if lam is not None else "lambda not computed"),
        wing_comonotone=(lam.wing_comonotone if lam is not None else float("nan")),
        wing_independent=(lam.wing_independent if lam is not None else float("nan")),
        wing_min_variance=(lam.wing_min_variance if lam is not None else float("nan")),
        wing_observed=(lam.wing_observed_absorbed if lam is not None else float("nan")),
        var_comonotone_bp2=(lam.var_comonotone_bp2 if lam is not None else float("nan")),
        var_independent_bp2=(lam.var_independent_bp2 if lam is not None else float("nan")),
        var_min_variance_bp2=(lam.var_min_variance_bp2 if lam is not None else float("nan")),
        hard_violation_bp2=(lam.hard_violation_bp2 if lam is not None else float("nan")),
        lambda_basis_var_share=(lam.basis_var_share if lam is not None else float("nan")),
        trough_peak_ratio=(lam.trough_peak_ratio if lam is not None else float("nan")),
        lambda_mode_prices=(lam.mode_prices if lam is not None else ()),
        lambda_marginals=(lam.marginals if lam is not None else ()),
        stability_flag=str(rnd.stability_flag),
        smoothing_sensitivity_pp=float(rnd.smoothing_sensitivity_pp),
        negative_density_pct=float(rnd.negative_density_pct),
        chosen_lambda=float(chosen_lambda),
        n_strikes_used=int(rnd.n_strikes_observed),
        prices_source=str(rnd.prices_source),
        regime_bucket=regime,
        flags=tuple(flags),
        warnings=tuple(warnings),
    )
    return record, warnings


def build_snapshot(
    config: DistributionScreenerConfig,
    *,
    as_of: datetime.date,
) -> ScreenerSnapshot:
    """Run the full SR3-vs-ZQ distribution-comparison pipeline."""
    contracts = _resolve_contracts(config, as_of=as_of)
    if not contracts:
        return ScreenerSnapshot(
            as_of=as_of,
            records=tuple(),
            config_summary={"contracts": []},
            run_warnings=("no_contracts_resolved",),
        )

    records: List[SignalRecord] = []
    warnings: List[str] = []
    for contract in contracts:
        rec, w = _compute_per_contract(
            sr3_contract=contract, as_of=as_of, config=config
        )
        warnings.extend(w)
        if rec is not None:
            records.append(rec)

    # Cross-quarter signal — runs across all valid records
    if len(records) >= config.cross_quarter_min_contracts:
        residual_ratios = [r.residual_to_explained_ratio for r in records]
        # Apply cross-quarter signal to the front contract (records[0])
        front_regime = records[0].regime_bucket
        cq_flag = signal_cross_quarter(
            residual_ratios_by_contract=residual_ratios,
            regime=front_regime,
            config=config,
        )
        if cq_flag is not None:
            # Append to front-contract flags
            updated = SignalRecord(
                **{
                    **records[0].__dict__,
                    "flags": records[0].flags + (cq_flag,),
                }
            )
            records[0] = updated

    return ScreenerSnapshot(
        as_of=as_of,
        records=tuple(records),
        config_summary={
            "sr3_contracts": [r.sr3_contract for r in records],
            "dte_floor": config.dte_floor,
            "dte_ceiling": config.dte_ceiling,
            "optimize_lambda": config.optimize_lambda,
            "basis_bp": config.basis_bp,
            "intermeeting_daily_vol_bp": config.intermeeting_daily_vol_bp,
        },
        run_warnings=tuple(warnings),
    )
