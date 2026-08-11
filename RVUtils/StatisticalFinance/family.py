"""Multiple testing across a family of strategies.

A grid search does not produce one result, it produces the maximum of several
hundred. The distribution of a maximum is not the distribution of a draw, and
comparing the winner against a single-strategy null is the single most common
way a backtest reports a discovery that is not there.

Three instruments, increasing in power:

**Selection-bias adjusted p-value.** Under each permutation, take the BEST of
the whole family. The observed winner is compared against that distribution of
maxima. This is exactly the right null for "I searched 2,000 configurations and
this one was best".

**Upper bound for the k-th signal.** Reuses the same distribution of maxima for
lower ranks, which is conservative -- the k-th best does not have to beat the
best of the family -- but needs no extra computation.

**Romano-Wolf stepdown.** Walks down the ranking, shrinking the competing set
as hypotheses are rejected, so the reference distribution for the k-th
hypothesis is the maximum over only the hypotheses not yet rejected. Strictly
more powerful than the upper bound, with strong control of the familywise error
rate. Romano & Wolf (2005), https://www.jstor.org/stable/2669893.

Follows https://quantpylib.hangukquant.com/learn/statistical_finance/.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "selection_bias_pvalue",
    "topk_upper_bound",
    "romano_wolf",
    "FamilyTestResult",
]


def _as_null_matrix(null: np.ndarray | pd.DataFrame) -> np.ndarray:
    arr = null.to_numpy(dtype=float) if isinstance(null, pd.DataFrame) else np.asarray(null, float)
    if arr.ndim != 2:
        raise ValueError("the null must be a (draws x strategies) matrix")
    return arr


def selection_bias_pvalue(observed: Sequence[float],
                          null: np.ndarray | pd.DataFrame) -> float:
    """p-value for the BEST of a family, against the family's own maximum.

    ``null`` is (M draws x n strategies): every strategy re-run on every
    permutation. The reference distribution is the row-wise maximum, so the
    question asked is "how often does a family of worthless strategies produce
    a best-of that beats my best-of".
    """
    obs = np.asarray(observed, dtype=float)
    arr = _as_null_matrix(null)
    if arr.shape[1] != len(obs):
        raise ValueError(f"null has {arr.shape[1]} strategies, observed has {len(obs)}")
    maxima = np.nanmax(arr, axis=1)
    best = float(np.nanmax(obs))
    return float((1 + int(np.sum(maxima >= best))) / (len(maxima) + 1))


def topk_upper_bound(observed: Sequence[float], null: np.ndarray | pd.DataFrame,
                     k: Optional[int] = None) -> pd.DataFrame:
    """Conservative p-values for every rank, from one distribution of maxima.

        p₀⁽ᵏ⁾ = (1 + #{ψ⁽¹⁾₍ⱼ₎ ≥ ψ_obs⁽ᵏ⁾}) / (M + 1)

    Conservative because the k-th best strategy is judged against the maximum of
    the whole family rather than against the maximum of what it actually
    competed with. Equality holds at k = 1. Use ``romano_wolf`` when the extra
    power matters.
    """
    obs = np.asarray(observed, dtype=float)
    arr = _as_null_matrix(null)
    maxima = np.nanmax(arr, axis=1)
    order = np.argsort(-obs, kind="stable")
    ranked = obs[order]
    k = len(obs) if k is None else int(k)
    rows = []
    for r in range(min(k, len(obs))):
        p = float((1 + int(np.sum(maxima >= ranked[r]))) / (len(maxima) + 1))
        rows.append({"rank": r + 1, "strategy": int(order[r]), "observed": float(ranked[r]),
                     "p_upper_bound": p})
    return pd.DataFrame(rows).set_index("rank")


@dataclass
class FamilyTestResult:
    table: pd.DataFrame
    n_strategies: int
    n_draws: int
    alpha: float

    @property
    def n_rejected(self) -> int:
        return int(self.table["reject"].sum())

    @property
    def rejected(self) -> pd.DataFrame:
        return self.table[self.table["reject"]]

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (f"FamilyTestResult({self.n_rejected}/{self.n_strategies} rejected at "
                f"alpha={self.alpha}, {self.n_draws} draws)")


def romano_wolf(observed: Sequence[float], null: np.ndarray | pd.DataFrame,
                *, alpha: float = 0.05,
                names: Optional[Sequence] = None) -> FamilyTestResult:
    """Romano-Wolf stepdown with strong familywise error rate control.

    Given observed statistics ordered T₍₁₎ ≥ … ≥ T₍ₘ₎ and a null matrix of the
    same statistics under M resamples:

        V_j⁽ⁱ⁾  = max_{j ≤ k ≤ m} T₍ₖ₎⁽ⁱ⁾            stepdown maxima
        p̃₍ⱼ₎   = (1 + #{V_j⁽ⁱ⁾ ≥ T₍ⱼ₎,obs}) / (M+1)
        p̂₍₁₎   = p̃₍₁₎,  p̂₍ⱼ₎ = max(p̂₍ⱼ₋₁₎, p̃₍ⱼ₎)   monotonicity

    Two details decide whether this is Romano-Wolf or something that merely
    looks like it.

    The null columns are reordered by the OBSERVED ranking, not re-ranked within
    each resample. Re-ranking per resample would compare the j-th observed
    hypothesis against the j-th best of the null, which is a different and
    incorrect reference.

    The monotonicity step is not cosmetic. The stepdown maxima shrink as the
    competing set shrinks, so raw p-values can fall as rank worsens; without the
    running maximum a worse strategy could be reported as more significant than
    a better one, and FWER control would be lost.
    """
    obs = np.asarray(observed, dtype=float)
    arr = _as_null_matrix(null)
    m = len(obs)
    if arr.shape[1] != m:
        raise ValueError(f"null has {arr.shape[1]} strategies, observed has {m}")
    M = arr.shape[0]

    order = np.argsort(-obs, kind="stable")     # descending, ties keep input order
    ranked_obs = obs[order]
    ranked_null = arr[:, order]

    # Suffix maxima along the ranking: V[:, j] = max over ranks j..m-1.
    V = np.flip(np.maximum.accumulate(np.flip(ranked_null, axis=1), axis=1), axis=1)

    raw = np.empty(m)
    for j in range(m):
        raw[j] = (1 + int(np.sum(V[:, j] >= ranked_obs[j]))) / (M + 1)

    adj = np.maximum.accumulate(raw)

    labels = list(names) if names is not None else list(range(m))
    table = pd.DataFrame({
        "rank": np.arange(1, m + 1),
        "strategy": [labels[i] for i in order],
        "observed": ranked_obs,
        "p_raw": raw,
        "p_adjusted": adj,
        "reject": adj <= alpha,
    }).set_index("rank")
    return FamilyTestResult(table=table, n_strategies=m, n_draws=M, alpha=float(alpha))
