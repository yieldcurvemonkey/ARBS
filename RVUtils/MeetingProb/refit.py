"""Refit the meeting lattice to listed SR3 premiums; measure whether it is identified.

Free parameters: one mantissa ``q_m`` per resolved meeting (the probability of
the SECOND point of that meeting's ZQ support — the support itself, i.e. the
characteristic, is held fixed from ZQ) plus one smear width. The anchoring in
:mod:`atoms` keeps the distribution's mean pinned to the forward for ANY q, so
the fit sees only shape: exactly the object parity leaves free.

Identification is *measured, not assumed*: ``bootstrap_refit`` perturbs every
premium by a uniform half-tick and refits; the spread of the recovered q's is
the measurement error a signal must clear. A gap smaller than its own bootstrap
sigma is noise, whatever the z-score against history says.

EXCHANGEABILITY — the structural identification limit. For a quarterly SR3
option every resolved meeting has day weight 1, so the atom distribution
depends on the q's only through symmetric functions: meetings with equal
weights and equal supports are exchangeable, and the surface identifies the
distribution of the TOTAL move count N, never the per-meeting attribution. The
fit therefore carries a small ZQ-proximity regularizer: among the exchangeable
solutions it returns the one closest to ZQ's vector, which makes "which
meeting moved" an explicit parsimony choice rather than a numerical accident.
Per-meeting gaps are reported for monitoring, but the *identified* signal is
the N-space CDF (the boundary digitals in :mod:`monitor`).
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from RVUtils.MeetingProb.atoms import ContractMeetings, atom_distribution
from RVUtils.MeetingProb.pricer import price_option

__all__ = ["RefitResult", "refit_lattice", "bootstrap_refit", "select_quotes"]

#: SR3 option minimum tick is a quarter of a bp of price; half of it is the
#: canonical quote-noise scale for the bootstrap.
HALF_TICK_BP = 0.125


@dataclasses.dataclass
class RefitResult:
    q: np.ndarray                     # fitted mantissas, one per resolved meeting
    smear_bp: float
    sse: float                        # premium SSE (bp^2)
    rmse_bp: float
    n_quotes: int
    converged: bool
    q_zq: np.ndarray                  # ZQ's mantissas on the same support
    p_gap: np.ndarray                 # q - q_zq (prob of the larger move)
    var_opt_bp2: np.ndarray           # per-meeting event variance, fitted
    var_zq_bp2: np.ndarray            # per-meeting event variance, ZQ


def select_quotes(
    day_quotes: pd.DataFrame,
    forward_rate: float,
    *,
    max_abs_moneyness: float = 1.00,
    min_oi: float = 0.0,
) -> pd.DataFrame:
    """OTM listed quotes within +/-1.00%% of the forward, both rights.

    OTM only (puts above the forward IN RATE, calls below) mirrors the panel's
    own convention and keeps every quote a small number priced by the wing it
    describes rather than by intrinsic value.
    """
    g = day_quotes
    if min_oi > 0 and "oi" in g.columns:
        g = g[g["oi"] >= min_oi]
    m = g["strike_rate"] - forward_rate
    otm = ((g["right"] == "P") & (m > 0)) | ((g["right"] == "C") & (m < 0))
    out = g[otm & (m.abs() <= max_abs_moneyness)]
    return out.drop_duplicates(["right", "strike_rate"]).sort_values("strike_rate")


def _premium_vector(
    cm: ContractMeetings,
    forward_rate: float,
    q: np.ndarray,
    smear_bp: float,
    quotes: pd.DataFrame,
) -> np.ndarray:
    rates, probs = atom_distribution(cm, forward_rate, q=q)
    return np.array([
        price_option(rates, probs, r, k, smear_bp=smear_bp)
        for r, k in zip(quotes["right"].to_numpy(), quotes["strike_rate"].to_numpy())
    ])


def refit_lattice(
    cm: ContractMeetings,
    forward_rate: float,
    quotes: pd.DataFrame,
    *,
    smear_floor_bp: float = 1.0,
    smear_cap_bp: Optional[float] = None,
    fit_smear: bool = True,
    smear_bp: Optional[float] = None,
    q0: Optional[Sequence[float]] = None,
    ridge: float = 0.05,
) -> Optional[RefitResult]:
    """Least-squares fit of (q, smear) to listed premiums.

    ``smear_cap_bp`` defaults to the ZQ-implied outcome std of the unresolved
    meetings plus a diffusion allowance — the smear must not be free to eat the
    resolved meetings' variance.
    """
    R = cm.n_resolved
    if R == 0 or len(quotes) < R + 3:
        return None
    prem_mkt = quotes["premium_bp"].to_numpy(dtype=float)

    unresolved_std = float(np.sqrt(cm.unresolved_var_bp2))
    if smear_cap_bp is None:
        smear_cap_bp = max(unresolved_std + 6.0, smear_floor_bp + 0.5)

    q_zq = np.array([r.q_zq for r in cm.resolved])
    starts: List[np.ndarray] = []
    base0 = np.clip(q_zq if q0 is None else np.asarray(q0, dtype=float), 0.02, 0.98)
    starts.append(base0)
    starts.append(np.full(R, 0.5))

    def make_x(qv, sv):
        return np.concatenate([qv, [sv]]) if fit_smear else np.asarray(qv, dtype=float)

    def unpack(x):
        if fit_smear:
            return np.clip(x[:R], 0.0, 1.0), float(np.clip(x[R], smear_floor_bp,
                                                           smear_cap_bp))
        return np.clip(x, 0.0, 1.0), float(smear_bp if smear_bp is not None
                                           else smear_floor_bp)

    lo = np.concatenate([np.zeros(R), [smear_floor_bp]]) if fit_smear else np.zeros(R)
    hi = np.concatenate([np.ones(R), [smear_cap_bp]]) if fit_smear else np.ones(R)

    best = None
    s0 = float(np.clip(max(unresolved_std, 2.0), smear_floor_bp, smear_cap_bp))
    for st in starts:
        x0 = make_x(st, s0)
        try:
            def _resid(x):
                qv, sv = unpack(x)
                prem = _premium_vector(cm, forward_rate, qv, sv, quotes)
                # ZQ-proximity ridge: the tie-break among exchangeable optima
                # (see module docstring). Units are bp so it is a soft prior,
                # never a constraint the premiums cannot override.
                return np.concatenate([prem - prem_mkt,
                                       np.sqrt(ridge) * (qv - q_zq)])

            sol = least_squares(
                _resid, x0, bounds=(lo, hi), method="trf", xtol=1e-10,
                ftol=1e-10, max_nfev=400,
            )
        except Exception:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        return None

    qf, sf = unpack(best.x)
    resid = _premium_vector(cm, forward_rate, qf, sf, quotes) - prem_mkt
    sse = float(np.dot(resid, resid))
    var_opt = np.array([
        ((r.support[1] - r.support[0]) * 25.0 * r.weight) ** 2 * qf[i] * (1.0 - qf[i])
        for i, r in enumerate(cm.resolved)
    ])
    var_zq = np.array([
        ((r.support[1] - r.support[0]) * 25.0 * r.weight) ** 2 * r.q_zq * (1.0 - r.q_zq)
        for r in cm.resolved
    ])
    return RefitResult(
        q=qf, smear_bp=sf, sse=sse, rmse_bp=float(np.sqrt(sse / len(quotes))),
        n_quotes=int(len(quotes)), converged=bool(best.success),
        q_zq=q_zq, p_gap=qf - q_zq, var_opt_bp2=var_opt, var_zq_bp2=var_zq,
    )


def bootstrap_refit(
    cm: ContractMeetings,
    forward_rate: float,
    quotes: pd.DataFrame,
    *,
    n: int = 40,
    noise_bp: float = HALF_TICK_BP,
    seed: int = 7,
    **refit_kw,
) -> Optional[Dict[str, np.ndarray]]:
    """Half-tick premium noise -> distribution of the refit; the honesty panel.

    Returns per-meeting ``q_std`` (and the smear std). A P-gap is only evidence
    when it clears ~2x its own ``q_std``.
    """
    base = refit_lattice(cm, forward_rate, quotes, **refit_kw)
    if base is None:
        return None
    rng = np.random.default_rng(seed)
    qs, ss = [], []
    for _ in range(n):
        qt = quotes.copy()
        qt["premium_bp"] = (
            qt["premium_bp"].to_numpy()
            + rng.uniform(-noise_bp, noise_bp, len(qt))
        ).clip(min=0.0)
        r = refit_lattice(cm, forward_rate, qt, q0=base.q, **refit_kw)
        if r is not None:
            qs.append(r.q)
            ss.append(r.smear_bp)
    if len(qs) < max(5, n // 4):
        return None
    qs = np.vstack(qs)
    return {
        "q_mean": qs.mean(axis=0),
        "q_std": qs.std(axis=0, ddof=1),
        "smear_std": float(np.std(ss, ddof=1)),
        "n_ok": np.array([len(qs)]),
        "base_q": base.q,
        "base_smear": np.array([base.smear_bp]),
    }
