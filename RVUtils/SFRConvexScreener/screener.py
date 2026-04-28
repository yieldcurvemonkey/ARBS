"""Top-level orchestrator for the SFR Convex Linear Structure Screener.

The single entry point ``build_snapshot(config, as_of=...)`` runs the full
pipeline: load market data → enumerate structures → BL marginals → joint
distributions (common-state + Gaussian copula + perfect correlation) →
metrics → IV/RV diagnostics → historical comparison → composite score →
ranked snapshot.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from RVUtils.ImpliedDistribution import (
    FedScenarioConfig,
    FOMCPathStateConfig,
    JointDistributionSnapshot,
    SFRImpliedDistribution,
)
from RVUtils.SFRConvexScreener._carry import structure_pnl_from_rates_bp
from RVUtils.SFRConvexScreener._distributions import (
    PerContractDistribution,
    extract_bl_marginals,
    payoff_pdf_common_state,
    payoff_pdf_historical_gaussian_copula,
    payoff_pdf_perfect_correlation,
)
from RVUtils.SFRConvexScreener._historical import (
    historical_asymmetry_summary,
    rolling_structure_payoffs_bp,
)
from RVUtils.SFRConvexScreener._ivrv import iv_rv_diagnostic, realized_vol_bp
from RVUtils.SFRConvexScreener._market_data import load_market_data
from RVUtils.SFRConvexScreener._metrics import (
    PayoffMetrics,
    metrics_from_pdf,
    metrics_from_samples,
)
from RVUtils.SFRConvexScreener._scoring import composite_score_series
from RVUtils.SFRConvexScreener._types import (
    JointMethod,
    Leg,
    SFRConvexScreenerConfig,
    SFRConvexScreenerSnapshot,
    StructureResult,
)
from RVUtils.SFRConvexScreener._universe import enumerate_structures

logger = logging.getLogger(__name__)


def _historical_correlation_matrix(
    price_panel: pd.DataFrame, *, window: int
) -> pd.DataFrame:
    if price_panel.empty:
        cols = list(price_panel.columns)
        return pd.DataFrame(np.eye(len(cols)), index=cols, columns=cols) if cols else pd.DataFrame()
    rate_panel = 100.0 - price_panel
    daily_changes = rate_panel.diff().dropna(how="any").tail(window)
    if len(daily_changes) < 5:
        cols = list(price_panel.columns)
        return pd.DataFrame(np.eye(len(cols)), index=cols, columns=cols)
    return daily_changes.corr()


def _calibrate_joint(
    smiles: Dict[str, Any],
    *,
    as_of: datetime.date,
    current_rate: float,
) -> Optional[JointDistributionSnapshot]:
    """Calibrate the common-state joint snapshot via the existing
    ``SFRImpliedDistribution.extract_joint`` entry point.

    Returns ``None`` if calibration fails — the caller falls back to copula /
    perfect-correlation paths.
    """
    if not smiles:
        return None
    try:
        scenarios = FedScenarioConfig.default_sofr_scenarios(current_rate=current_rate)
        dist = SFRImpliedDistribution(scenario_config=scenarios)
        state_cfg = FOMCPathStateConfig.default_templated_paths(current_rate=current_rate)
        return dist.extract_joint(smiles, state_config=state_cfg)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Joint calibration failed; falling back to copula only: %s", exc
        )
        return None


def _config_summary(config: SFRConvexScreenerConfig) -> Dict[str, Any]:
    return {
        "universe_size": config.universe_size,
        "calendar_gaps": list(config.calendar_gaps),
        "fly_gaps": list(config.fly_gaps),
        "joint_methods": [m.value for m in config.joint_methods],
        "primary_joint_method": config.primary_joint_method.value,
        "correlation_window": config.correlation_window,
        "n_simulations": config.n_simulations,
        "horizon_days": config.horizon_days,
        "score_weights": list(config.score_weights),
    }


def _iv_bp_from_bl(bl) -> float:
    """Approximate single-leg IV (annualised, bp) from BL std + tte."""
    tte = max(bl.input.time_to_expiry, 1e-6)
    return float(bl.std_rate * 100.0 / np.sqrt(tte))


def build_snapshot(
    config: SFRConvexScreenerConfig, *, as_of: datetime.date,
) -> SFRConvexScreenerSnapshot:
    md = load_market_data(config, as_of=as_of)
    structures = enumerate_structures(md.symbols, config)
    if not structures:
        return SFRConvexScreenerSnapshot(
            as_of=as_of,
            results=(),
            config_summary=_config_summary(config),
            run_warnings=tuple(list(md.warnings) + ["no structures enumerated"]),
        )

    # 1. BL marginals
    marginals: Dict[str, PerContractDistribution] = extract_bl_marginals(md.smiles)

    # 2. Joint snapshot (common-state)
    current_rate = float("nan")
    if not md.futures_df.empty and "rate" in md.futures_df.columns:
        front_rate = md.futures_df["rate"].dropna()
        if not front_rate.empty:
            current_rate = float(front_rate.iloc[0])
    if not np.isfinite(current_rate):
        current_rate = 4.33

    joint_snapshot = (
        _calibrate_joint(md.smiles, as_of=as_of, current_rate=current_rate)
        if JointMethod.COMMON_STATE in config.joint_methods
        else None
    )

    # 3. Historical correlation
    corr = _historical_correlation_matrix(md.price_panel, window=config.correlation_window)
    rng = np.random.default_rng(config.random_seed)

    # 4. Per-structure analytics
    intermediates: List[Dict[str, Any]] = []
    for s in structures:
        if any(leg.contract not in marginals for leg in s.legs):
            logger.warning("skipping %s — missing marginal", s.structure_id)
            continue

        metrics_by_method: Dict[str, PayoffMetrics] = {}
        if JointMethod.COMMON_STATE in config.joint_methods and joint_snapshot is not None:
            try:
                outcomes_bp, probs = payoff_pdf_common_state(s.legs, joint=joint_snapshot)
                metrics_by_method["common_state"] = metrics_from_pdf(outcomes_bp, probs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("common-state PDF failed for %s: %s", s.structure_id, exc)

        if JointMethod.HISTORICAL_GAUSSIAN_COPULA in config.joint_methods:
            try:
                samples = payoff_pdf_historical_gaussian_copula(
                    s.legs,
                    marginals=marginals,
                    corr_matrix=corr,
                    n_sim=config.n_simulations,
                    rng=rng,
                )
                metrics_by_method["historical_gaussian_copula"] = metrics_from_samples(samples)
            except Exception as exc:  # noqa: BLE001
                logger.warning("copula PDF failed for %s: %s", s.structure_id, exc)

        if JointMethod.PERFECT_CORRELATION in config.joint_methods:
            try:
                outcomes_bp, probs = payoff_pdf_perfect_correlation(s.legs, marginals=marginals)
                metrics_by_method["perfect_correlation"] = metrics_from_pdf(outcomes_bp, probs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("perfect-corr PDF failed for %s: %s", s.structure_id, exc)

        if not metrics_by_method:
            logger.warning("no metrics produced for %s — skipping", s.structure_id)
            continue

        primary_method = config.primary_joint_method.value
        if primary_method not in metrics_by_method:
            primary_method = next(iter(metrics_by_method))

        # Carry / roll: TODO Phase 5 — wire IRSwapQuery via curve_handle.
        carry_bp = float("nan")
        rolldown_bp = float("nan")

        # IV/RV per leg
        ivrv: List = []
        for leg in s.legs:
            bl = marginals[leg.contract].bl
            iv_bp = _iv_bp_from_bl(bl)
            try:
                rate_series = (100.0 - md.price_panel[leg.contract]).diff() * 100.0
            except KeyError:
                rate_series = pd.Series(dtype=float)
            rv_bp = realized_vol_bp(rate_series.tail(21))
            ivrv.append(iv_rv_diagnostic(leg.contract, iv_bp=iv_bp, rv_bp=rv_bp))

        # Historical realized payoff
        hist = None
        try:
            payoff_series = rolling_structure_payoffs_bp(
                md.price_panel, legs=s.legs, horizon_days=config.horizon_days,
            )
            hist = historical_asymmetry_summary(
                payoff_series,
                current_rn_asymmetry=metrics_by_method[primary_method].asymmetry_ratio,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("historical comparison failed for %s: %s", s.structure_id, exc)

        # Per-leg warnings (BL caveats)
        leg_warnings: List[str] = []
        for leg in s.legs:
            bl = marginals[leg.contract].bl
            for w in bl.warnings:
                leg_warnings.append(f"{leg.contract}::{w}")

        intermediates.append(
            {
                "structure_def": s,
                "metrics_by_method": metrics_by_method,
                "primary_method": primary_method,
                "carry_3m_bp": carry_bp,
                "rolldown_3m_bp": rolldown_bp,
                "iv_rv_diagnostics": tuple(ivrv),
                "historical": hist,
                "warnings": tuple(leg_warnings),
            }
        )

    if not intermediates:
        return SFRConvexScreenerSnapshot(
            as_of=as_of,
            results=(),
            config_summary=_config_summary(config),
            run_warnings=tuple(list(md.warnings) + ["no structures yielded metrics"]),
        )

    # 5. Composite score (cross-sectional z over primary metrics)
    score_rows = []
    for r in intermediates:
        prim = r["metrics_by_method"][r["primary_method"]]
        carry_term = r["carry_3m_bp"] if np.isfinite(r["carry_3m_bp"]) else 0.0
        score_rows.append(
            {
                "structure_id": r["structure_def"].structure_id,
                "asymmetry": prim.asymmetry_ratio,
                "p_profit": prim.p_profit,
                "ev_carry": prim.mean_bp + carry_term,
                "tail_ratio": prim.tail_ratio,
            }
        )
    score_df = pd.DataFrame(score_rows).set_index("structure_id")
    score_df = score_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    scores = composite_score_series(
        score_df,
        weights=config.score_weights,
        columns=("asymmetry", "p_profit", "ev_carry", "tail_ratio"),
    )
    scores_sorted = scores.sort_values(ascending=False)
    rank_lookup = {sid: i + 1 for i, sid in enumerate(scores_sorted.index)}
    score_lookup = scores.to_dict()

    final = []
    for r in intermediates:
        sid = r["structure_def"].structure_id
        final.append(
            StructureResult(
                structure_def=r["structure_def"],
                metrics_by_method=r["metrics_by_method"],
                primary_method=r["primary_method"],
                carry_3m_bp=r["carry_3m_bp"],
                rolldown_3m_bp=r["rolldown_3m_bp"],
                iv_rv_diagnostics=r["iv_rv_diagnostics"],
                historical=r["historical"],
                warnings=r["warnings"],
                composite_score=float(score_lookup.get(sid, float("nan"))),
                rank=int(rank_lookup.get(sid, 0)),
            )
        )
    final.sort(key=lambda r: r.rank if r.rank > 0 else 1_000_000)

    return SFRConvexScreenerSnapshot(
        as_of=as_of,
        results=tuple(final),
        config_summary=_config_summary(config),
        run_warnings=md.warnings,
    )
