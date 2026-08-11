"""Rademacher Anti-Serum: a finite-sample floor under a searched Sharpe.

A permutation test says whether an edge is distinguishable from noise. It does
not say how big the edge is once you pay for having searched. RAS does: it
returns a lower bound on the TRUE Sharpe that holds with probability 1 - delta,
in finite samples, without asymptotics.

    θ_n  ≥  θ̂_n  -  2R̂  -  3·sqrt(2·ln(2/δ)/T)  -  sqrt(2·ln(2N/δ)/T)

    θ̂_n                       the empirical Sharpe of strategy n
    2R̂                        the complexity penalty -- how much of a random
                               sign pattern the BEST of this family can fit
    3·sqrt(2·ln(2/δ)/T)        finite-sampling error
    sqrt(2·ln(2N/δ)/T)         the multiple-testing correction, in N
    δ                          1 - confidence
    N                          strategies tried, T periods

The interesting term is R̂, the empirical Rademacher complexity

    R̂ = E_ε [ sup_{1≤n≤N} (εᵀ xⁿ) / T ]

with ε uniform on {-1,+1}^T. It is estimated by drawing sign vectors and
averaging the best fit any strategy achieves. Crucially it is measured on the
ACTUAL family, so a set of near-identical configurations is charged far less
than the same count of independent ones -- unlike a Bonferroni or a naive
Deflated Sharpe, both of which price N alone and over-penalise a correlated
grid.

A strategy whose bound is above zero is "Rademacher positive".

Introduced by Paleologo, *The Elements of Quantitative Investing*; presentation
follows https://quantpylib.hangukquant.com/learn/statistical_finance/.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "standardize_returns",
    "empirical_rademacher_complexity",
    "ras_bound",
    "RASResult",
]


def standardize_returns(returns: np.ndarray | pd.DataFrame,
                        vol: Optional[np.ndarray | pd.DataFrame] = None,
                        ) -> np.ndarray:
    """Scale each strategy's returns so its mean IS its Sharpe.

        ζ̂_{t,n} = (wᵀ_{t,n} r_t) / sqrt(wᵀ_{t,n} Ω_t w_{t,n})

    The reference divides by the *instantaneous* volatility, which makes the
    observations comparable and closer to i.i.d. Pass ``vol`` (same shape) to do
    that. With ``vol=None`` each column is divided by its own full-sample
    standard deviation, which is the same normalisation evaluated once -- weaker,
    because it leaves volatility clustering in, and it is the honest default when
    no conditional volatility model is available.

    Either way the column mean equals the per-period Sharpe, which is what the
    bound is stated in.
    """
    x = returns.to_numpy(dtype=float) if isinstance(returns, pd.DataFrame) else np.asarray(returns, float)
    if x.ndim == 1:
        x = x[:, None]
    if vol is not None:
        v = vol.to_numpy(dtype=float) if isinstance(vol, pd.DataFrame) else np.asarray(vol, float)
        if v.ndim == 1:
            v = v[:, None]
        if v.shape != x.shape:
            raise ValueError(f"vol shape {v.shape} does not match returns {x.shape}")
        with np.errstate(divide="ignore", invalid="ignore"):
            out = np.where(v > 0, x / v, 0.0)
        return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)

    sd = np.nanstd(x, axis=0, ddof=1)
    sd = np.where(sd > 0, sd, np.nan)
    out = x / sd
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def empirical_rademacher_complexity(x: np.ndarray, *, draws: int = 1000,
                                    rng: Optional[np.random.Generator] = None,
                                    ) -> float:
    """R̂ = E_ε[ sup_n (εᵀ xⁿ)/T ], by Monte Carlo over sign vectors.

    ``x`` is (T x N) standardized returns. Each draw asks: of my N strategies,
    how well does the best one line up with this random pattern of +1/-1? A
    family that can fit any noise pattern scores high and is charged for it.
    """
    x = np.asarray(x, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    T, N = x.shape
    if T == 0 or N == 0:
        return float("nan")
    rng = rng or np.random.default_rng()

    total = 0.0
    # Blocked so a wide family does not materialise a (draws x T) and a
    # (draws x N) at once for large draws.
    block = max(1, min(int(draws), max(1, 2_000_000 // max(T, 1))))
    done = 0
    while done < draws:
        k = min(block, draws - done)
        eps = rng.choice(np.array([-1.0, 1.0]), size=(k, T))
        total += float(np.max(eps @ x, axis=1).sum()) / T
        done += k
    return total / draws


@dataclass
class RASResult:
    """The bound and every term that went into it, kept separate on purpose."""

    sharpe: np.ndarray
    bound: np.ndarray
    rademacher: float
    complexity_penalty: float
    sampling_error: float
    multiple_testing: float
    T: int
    N: int
    delta: float
    names: Optional[Sequence] = None

    @property
    def haircut(self) -> float:
        """Everything subtracted from the empirical Sharpe."""
        return self.complexity_penalty + self.sampling_error + self.multiple_testing

    def table(self) -> pd.DataFrame:
        idx = list(self.names) if self.names is not None else list(range(len(self.sharpe)))
        return pd.DataFrame({
            "sharpe": self.sharpe,
            "ras_lower_bound": self.bound,
            "rademacher_positive": self.bound > 0,
        }, index=idx).sort_values("ras_lower_bound", ascending=False)

    def terms(self) -> pd.Series:
        return pd.Series({
            "empirical Sharpe (best)": float(np.nanmax(self.sharpe)),
            "R_hat": self.rademacher,
            "complexity penalty 2*R_hat": self.complexity_penalty,
            "sampling error 3*sqrt(2ln(2/d)/T)": self.sampling_error,
            "multiple testing sqrt(2ln(2N/d)/T)": self.multiple_testing,
            "total haircut": self.haircut,
            "best RAS lower bound": float(np.nanmax(self.bound)),
            "T": self.T, "N": self.N, "delta": self.delta,
        })

    def __repr__(self) -> str:  # pragma: no cover - display only
        n_pos = int(np.sum(self.bound > 0))
        return (f"RASResult(N={self.N}, T={self.T}, R_hat={self.rademacher:.4f}, "
                f"haircut={self.haircut:.4f}, {n_pos} Rademacher-positive)")


def ras_bound(returns: np.ndarray | pd.DataFrame, *, delta: float = 0.05,
              draws: int = 1000, rng: Optional[np.random.Generator] = None,
              vol: Optional[np.ndarray | pd.DataFrame] = None,
              names: Optional[Sequence] = None,
              standardize: bool = True) -> RASResult:
    """The RAS lower bound for every strategy in a family.

    ``returns`` is (T periods x N strategies). Pass the WHOLE family, not just
    the winner: N and R̂ are both properties of what was searched, and computing
    the bound on the winner alone would silently set N = 1 and drop the very
    penalty the method exists to charge.
    """
    if isinstance(returns, pd.DataFrame) and names is None:
        names = list(returns.columns)
    x = standardize_returns(returns, vol) if standardize else (
        returns.to_numpy(dtype=float) if isinstance(returns, pd.DataFrame)
        else np.asarray(returns, float))
    if x.ndim == 1:
        x = x[:, None]
    T, N = x.shape
    if T < 2:
        raise ValueError("RAS needs at least two periods")

    r_hat = empirical_rademacher_complexity(x, draws=draws, rng=rng)
    complexity = 2.0 * r_hat
    sampling = 3.0 * math.sqrt(2.0 * math.log(2.0 / delta) / T)
    multiple = math.sqrt(2.0 * math.log(2.0 * N / delta) / T)

    sharpe = np.nanmean(x, axis=0)
    bound = sharpe - complexity - sampling - multiple
    return RASResult(sharpe=sharpe, bound=bound, rademacher=r_hat,
                     complexity_penalty=complexity, sampling_error=sampling,
                     multiple_testing=multiple, T=T, N=N, delta=float(delta), names=names)
