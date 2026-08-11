"""Monte Carlo permutation tests for a single strategy.

Three questions, three different things held fixed. Getting the wrong one gives
an answer to a question nobody asked.

**In-sample overfit.** Permute the market data, re-run the ENTIRE trading
machinery -- signal, optimiser, sizing, the lot -- and ask how often it does as
well on noise. The null is that the system has no predictive power at all and
the backtest is fitted to the sample. This is the expensive one: every draw is a
full backtest.

**Timer's p-value.** Permute the returns in time, hold the DECISIONS fixed. The
null is that the strategy has no timing skill, and any profit came from static
exposure to drift. Cheap, because nothing is re-run.

**Picker's p-value.** Permute which instrument each weight is attached to at
each date, hold the time path of decisions fixed. The null is no selection
skill. Only meaningful for a cross-sectional book.

All three share the p-value

    p̂ = (1 + #{ψ⁽ⁱ⁾ ≥ ψ_obs}) / (M + 1)

The ``1 +`` in both places is not a fudge. Without it a test with M draws can
report p = 0, which claims more certainty than M draws can support; with it the
smallest attainable p-value is 1/(M+1), which is exactly the resolution the
experiment bought.

Follows https://quantpylib.hangukquant.com/learn/statistical_finance/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "PermutationResult",
    "permutation_test",
    "shuffle_weights_on_eligibles",
    "timer_pvalue",
    "picker_pvalue",
    "sharpe_of_book",
]


@dataclass
class PermutationResult:
    """The outcome of a permutation test, with the null kept so it can be seen."""

    observed: float
    null: np.ndarray
    p_value: float
    n_draws: int
    n_failed: int = 0
    label: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def null_mean(self) -> float:
        return float(np.mean(self.null)) if len(self.null) else float("nan")

    @property
    def null_std(self) -> float:
        return float(np.std(self.null, ddof=1)) if len(self.null) > 1 else float("nan")

    @property
    def percentile(self) -> float:
        """Where the observed statistic sits inside its own null, in percent."""
        if not len(self.null):
            return float("nan")
        return float((self.null < self.observed).mean() * 100.0)

    @property
    def resolution(self) -> float:
        """The smallest p-value this many draws could have produced."""
        return 1.0 / (self.n_draws + 1)

    def summary(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "observed": self.observed,
            "null_mean": self.null_mean,
            "null_std": self.null_std,
            "percentile": self.percentile,
            "p_value": self.p_value,
            "draws": self.n_draws,
            "failed_draws": self.n_failed,
            "resolution": self.resolution,
        }

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (f"PermutationResult({self.label!r}: observed={self.observed:.5f}, "
                f"null={self.null_mean:.5f}+-{self.null_std:.5f}, "
                f"p={self.p_value:.4f} over {self.n_draws} draws)")


def _pvalue(observed: float, null: np.ndarray) -> float:
    if not len(null):
        return float("nan")
    return float((1 + int(np.sum(np.asarray(null) >= observed))) / (len(null) + 1))


def permutation_test(statistic: Callable[..., float],
                     permuter: Callable[..., Dict[str, Any]],
                     *,
                     draws: int = 1000,
                     rng: Optional[np.random.Generator] = None,
                     label: str = "",
                     skip_failed: bool = True,
                     show_progress: bool = False,
                     **kwargs: Any) -> PermutationResult:
    """The generic driver: statistic on real data, then on ``draws`` permutations.

    ``permuter(rng=..., **kwargs)`` returns a new kwargs dict for ``statistic``.

    A draw that raises is COUNTED, not silently dropped. A permutation test whose
    null quietly lost half its draws to exceptions reports a p-value computed
    from a different M than the one it claims, and the direction of that bias is
    not knowable from the outside.
    """
    rng = rng or np.random.default_rng()
    observed = float(statistic(**kwargs))

    null: list = []
    n_failed = 0
    it = range(int(draws))
    if show_progress:
        try:
            from tqdm.auto import tqdm
            it = tqdm(it, desc=label or "permutation")
        except Exception:  # noqa: BLE001
            pass

    for _ in it:
        try:
            payload = permuter(rng=rng, **kwargs)
            null.append(float(statistic(**payload)))
        except Exception:  # noqa: BLE001
            n_failed += 1
            if not skip_failed:
                raise

    arr = np.asarray(null, dtype=float)
    arr = arr[np.isfinite(arr)]
    return PermutationResult(observed=observed, null=arr, p_value=_pvalue(observed, arr),
                             n_draws=len(arr), n_failed=n_failed, label=label)


# ===========================================================================
# Statistics
# ===========================================================================
def sharpe_of_book(pnl: Sequence[float]) -> float:
    """Sharpe per trade -- mean over standard deviation, no annualisation.

    Annualising inside a permutation statistic is a mistake worth naming: the
    permuted book can have a different number of trades, and multiplying by
    sqrt(trades per year) would then compare two numbers that were scaled
    differently. The unscaled ratio is invariant to that.
    """
    p = np.asarray(pnl, dtype=float)
    p = p[np.isfinite(p)]
    if len(p) < 2:
        return 0.0
    sd = p.std(ddof=1)
    return float(p.mean() / sd) if sd > 0 else 0.0


# ===========================================================================
# Timer / picker: permute the returns, hold the decisions
# ===========================================================================
def shuffle_weights_on_eligibles(weights: pd.DataFrame, eligibles: pd.DataFrame,
                                 rng: np.random.Generator,
                                 method: str = "time") -> pd.DataFrame:
    """Shuffle weights only where the instrument was ELIGIBLE.

    Shuffling across ineligible cells would hand the null strategy positions in
    instruments that did not exist or could not be traded on that date, which
    makes the null easier to beat and the p-value optimistic.

    ``method="time"`` permutes each instrument's weights along time (the timing
    null). ``method="xs"`` permutes across instruments within each date (the
    picking null).
    """
    if method not in ("time", "xs"):
        raise ValueError("method must be 'time' or 'xs'")
    w = weights.to_numpy(dtype=float, copy=True)
    e = eligibles.to_numpy()

    if method == "time":
        for j in range(w.shape[1]):
            mask = np.flatnonzero(e[:, j])
            if len(mask) > 1:
                w[mask, j] = rng.permutation(w[mask, j])
    else:
        for i in range(w.shape[0]):
            mask = np.flatnonzero(e[i, :])
            if len(mask) > 1:
                w[i, mask] = rng.permutation(w[i, mask])

    return pd.DataFrame(w, index=weights.index, columns=weights.columns)


def timer_pvalue(pnl: Sequence[float], side: Sequence[float], *,
                 draws: int = 1000, rng: Optional[np.random.Generator] = None,
                 statistic: Callable[[np.ndarray], float] = sharpe_of_book,
                 label: str = "timer") -> PermutationResult:
    """Timing skill for a book of independent event trades.

    Each trade has a realised move and a side the strategy chose. Permuting
    which move each side received -- holding the multiset of both fixed --
    destroys the pairing and nothing else. Under the null the strategy had no
    idea which way any particular event would go.

    Note what this does NOT test. It cannot tell a real edge from a stable
    directional bias in the sample: a book that is long throughout a rally
    scores well here. Pair it with a sign-flip test, which fixes the opposite
    thing.
    """
    rng = rng or np.random.default_rng()
    p = np.asarray(pnl, dtype=float)
    s = np.asarray(side, dtype=float)
    if len(p) != len(s):
        raise ValueError("pnl and side must be the same length")
    # The signed P&L is side * move, so the move each trade saw is pnl / side.
    with np.errstate(divide="ignore", invalid="ignore"):
        move = np.where(s != 0, p / s, 0.0)

    observed = float(statistic(p))
    null = np.empty(int(draws))
    for i in range(int(draws)):
        null[i] = statistic(s * rng.permutation(move))
    return PermutationResult(observed=observed, null=null, p_value=_pvalue(observed, null),
                             n_draws=int(draws), label=label)


def shared_sign_flip_null(x: np.ndarray | pd.DataFrame, *, draws: int = 1000,
                          rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """A (draws x N) null of per-column Sharpes, from SHARED Rademacher flips.

    The null is "the direction each strategy took on each date carried nothing".
    Each draw multiplies every row by the same random +1/-1 and recomputes each
    column's Sharpe.

    Two properties make this the right family null for a grid of backtests.

    *A row PERMUTATION would be useless here.* A column's mean and standard
    deviation are both invariant to reordering its rows, so permuting dates
    leaves every Sharpe exactly unchanged and the "null" would be a point mass
    on the observed value. Only the sign flip moves the statistic.

    *The flip is SHARED across columns.* Two configurations that trade the same
    releases the same way are flipped together, so the null keeps their
    correlation. Flipping each column independently would pretend the family was
    N independent experiments and inflate the maximum of the null, making the
    resulting p-values far too forgiving of a correlated grid.

    ``x`` is (T dates x N strategies); NaN means "did not trade that date" and is
    treated as a zero contribution to that column only.
    """
    arr = x.to_numpy(dtype=float) if isinstance(x, pd.DataFrame) else np.asarray(x, float)
    if arr.ndim == 1:
        arr = arr[:, None]
    rng = rng or np.random.default_rng()
    T, N = arr.shape

    mask = np.isfinite(arr)
    vals = np.where(mask, arr, 0.0)
    n = mask.sum(axis=0).astype(float)                       # trades per column
    n_safe = np.where(n > 1, n, np.nan)

    out = np.full((int(draws), N), np.nan)
    for i in range(int(draws)):
        eps = rng.choice(np.array([-1.0, 1.0]), size=(T, 1))
        f = vals * eps
        s1 = f.sum(axis=0)
        s2 = (f * f).sum(axis=0)
        mean = s1 / n_safe
        var = (s2 - n_safe * mean ** 2) / (n_safe - 1)
        sd = np.sqrt(np.where(var > 0, var, np.nan))
        out[i] = mean / sd
    return out


def picker_pvalue(returns: pd.DataFrame, weights: pd.DataFrame,
                  eligibles: Optional[pd.DataFrame] = None, *,
                  leverage: Optional[pd.Series] = None,
                  draws: int = 1000, rng: Optional[np.random.Generator] = None,
                  label: str = "picker") -> PermutationResult:
    """Selection skill: permute which instrument each weight belongs to, per date."""
    rng = rng or np.random.default_rng()
    if eligibles is None:
        # Eligible means TRADEABLE that day, not HELD that day. Defaulting to
        # `weights != 0` would leave a concentrated book with one eligible cell
        # per row, and permuting a single element is the identity -- the null
        # would come back exactly equal to the observed and the test would
        # report p = 1.0 for a strategy with perfect foresight. Measured.
        eligibles = returns.notna()
    lev = (leverage if leverage is not None
           else pd.Series(1.0, index=returns.index)).to_numpy(dtype=float)
    r = returns.fillna(0.0).to_numpy(dtype=float)

    def _stat(w: np.ndarray) -> float:
        return sharpe_of_book(lev * np.einsum("ij,ij->i", w, r))

    observed = _stat(weights.to_numpy(dtype=float))
    null = np.empty(int(draws))
    for i in range(int(draws)):
        null[i] = _stat(shuffle_weights_on_eligibles(
            weights, eligibles, rng, method="xs").to_numpy(dtype=float))
    return PermutationResult(observed=observed, null=null, p_value=_pvalue(observed, null),
                             n_draws=int(draws), label=label)
