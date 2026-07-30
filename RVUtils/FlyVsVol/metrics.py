"""Fly settlement distribution metrics and the per-triple snapshot builder."""
from __future__ import annotations

import datetime
from typing import Optional

import numpy as np

from RVUtils.FlyVsVol._types import (
    ContractMarginal,
    FlyDefinition,
    FlySnapshot,
    FlyVsVolConfig,
    PathDistribution,
)
from RVUtils.FlyVsVol.coupling import comonotone_grid, gaussian_copula_sample

__all__ = ["path_metrics", "build_fly_snapshot"]

_PHI_QUANTILES = (1, 5, 25, 50, 75, 95, 99)
_DN_REPORT_MIN_PROB = 0.005


def path_metrics(
    rates: np.ndarray,
    *,
    move_size_bp: float = 25.0,
    tail_lo: float = 0.15,
    tail_hi: float = 0.85,
) -> PathDistribution:
    """Distribution of ``phi = (2*belly - front - back)*100`` over joint scenarios.

    ``rates``: ``(n, 3)`` scenario matrix in percent (any coupling, equal weights).
    Move counts are ``N_k = round(D_k / move_size)``; tails are cut on the *back
    leg's* empirical quantiles so the definition is coupling-agnostic.
    """
    rates = np.asarray(rates, dtype=float)
    if rates.ndim != 2 or rates.shape[1] != 3:
        raise ValueError(f"rates must be (n, 3), got {rates.shape}")
    front, belly, back = rates[:, 0], rates[:, 1], rates[:, 2]
    d1 = belly - front
    d2 = back - belly
    phi = (d1 - d2) * 100.0

    move = move_size_bp / 100.0
    n1 = np.round(d1 / move).astype(int)
    n2 = np.round(d2 / move).astype(int)
    dn = n1 - n2

    n = len(phi)
    dn_vals, dn_counts = np.unique(dn, return_counts=True)
    dn_table = {int(j): float(c) / n for j, c in zip(dn_vals, dn_counts)}
    e_phi_given = {
        int(j): float(phi[dn == j].mean())
        for j in dn_vals
        if dn_table[int(j)] >= _DN_REPORT_MIN_PROB
    }

    def _tail_slope(mask: np.ndarray) -> float:
        if mask.sum() < 10:
            return float("nan")
        x = back[mask]
        A = np.column_stack([x, np.ones(mask.sum())])
        slope_bp_per_pct = np.linalg.lstsq(A, phi[mask], rcond=None)[0][0]
        return float(slope_bp_per_pct / 100.0)  # bp phi per bp back leg

    lo_cut, hi_cut = np.quantile(back, [tail_lo, tail_hi])
    return PathDistribution(
        e_phi_bp=float(phi.mean()),
        phi_median_bp=float(np.percentile(phi, 50)),
        p_phi_gt0=float((phi > 0).mean()),
        phi_quantiles_bp={p: float(np.percentile(phi, p)) for p in _PHI_QUANTILES},
        e_d1_bp=float(d1.mean() * 100),
        e_d2_bp=float(d2.mean() * 100),
        e_n1=float(n1.mean()),
        e_n2=float(n2.mean()),
        prob_delta=float((dn > 0).mean() - (dn < 0).mean()),
        p_dn_pos=float((dn > 0).mean()),
        p_dn_neg=float((dn < 0).mean()),
        p_dn_zero=float((dn == 0).mean()),
        dn_table=dn_table,
        e_phi_given_dn_bp=e_phi_given,
        tail_slope_upper=_tail_slope(back >= hi_cut),
        tail_slope_lower=_tail_slope(back <= lo_cut),
    )


def _quality(legs, config: FlyVsVolConfig):
    flags = []
    for m in legs:
        if abs(m.forward_residual_bp) > config.max_abs_forward_residual_bp:
            flags.append(
                f"{m.symbol}: |forward_residual_bp|={abs(m.forward_residual_bp):.2f}"
                f" > {config.max_abs_forward_residual_bp}"
            )
        if m.pre_normalization_mass > config.max_pre_normalization_mass:
            flags.append(
                f"{m.symbol}: pre_normalization_mass={m.pre_normalization_mass:.4f}"
                f" > {config.max_pre_normalization_mass} (butterfly arb in fit)"
            )
        if m.ghost_mass_fraction > config.max_ghost_mass_fraction:
            flags.append(
                f"{m.symbol}: ghost_mass_fraction={m.ghost_mass_fraction:.4f}"
                f" > {config.max_ghost_mass_fraction} (tails are extrapolation)"
            )
    return (len(flags) == 0, tuple(flags))


def build_fly_snapshot(
    front: ContractMarginal,
    belly: ContractMarginal,
    back: ContractMarginal,
    *,
    config: FlyVsVolConfig = FlyVsVolConfig(),
    corr: Optional[np.ndarray] = None,
    rng: Optional[np.random.Generator] = None,
    as_of: Optional[datetime.date] = None,
) -> FlySnapshot:
    """Assemble Tier-1 marginal metrics + Tier-2 comonotone (+ optional copula)."""
    legs = (front, belly, back)
    f1, f2, f3 = (m.forward_rate for m in legs)
    fly_bp = (2 * f2 - f1 - f3) * 100.0
    med = [m.median for m in legs]
    mode = [m.mode for m in legs]
    mean = [m.mean for m in legs]

    como = path_metrics(
        comonotone_grid(legs, n=config.n_quantiles),
        move_size_bp=config.move_size_bp,
        tail_lo=config.tail_lo,
        tail_hi=config.tail_hi,
    )
    copula = None
    if corr is not None and np.all(np.isfinite(np.asarray(corr, dtype=float))):
        copula = path_metrics(
            gaussian_copula_sample(
                legs, np.asarray(corr, dtype=float),
                n_sim=config.n_copula_sims,
                rng=rng or np.random.default_rng(config.copula_seed),
            ),
            move_size_bp=config.move_size_bp,
            tail_lo=config.tail_lo,
            tail_hi=config.tail_hi,
        )

    fly_median_path_bp = (2 * med[1] - med[0] - med[2]) * 100.0
    quality_ok, flags = _quality(legs, config)
    if as_of is None:
        as_of = next((m.as_of for m in legs if m.as_of is not None), None)

    return FlySnapshot(
        fly=FlyDefinition(front.symbol, belly.symbol, back.symbol),
        as_of=as_of,
        forwards=(f1, f2, f3),
        spread1_bp=(f2 - f1) * 100.0,
        spread2_bp=(f3 - f2) * 100.0,
        fly_bp=fly_bp,
        fly_mean_bp=(2 * mean[1] - mean[0] - mean[2]) * 100.0,
        fly_median_path_bp=fly_median_path_bp,
        fly_mode_path_bp=(2 * mode[1] - mode[0] - mode[2]) * 100.0,
        tail_rent_bp=fly_bp - fly_median_path_bp,
        heuristic_prob=fly_bp / config.move_size_bp,
        comonotone=como,
        copula=copula,
        quality_ok=quality_ok,
        quality_flags=flags,
        legs=legs,
    )
