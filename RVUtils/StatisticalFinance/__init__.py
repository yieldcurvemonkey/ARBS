"""Statistical inference for trading strategies.

Five families of tool, each answering a question a Sharpe ratio cannot.

``permutation``  Resample market data so that the ONLY thing destroyed is
                 temporal ordering. Log returns keep their marginal
                 distribution, bars keep their own geometry, instruments keep
                 their correlation, and every window keeps its first and last
                 price. A null built this way is a null the strategy has to beat
                 on the market's own terms.

``mcpt``         Monte Carlo permutation tests for one strategy: in-sample
                 overfit (re-run everything on permuted data), timing skill
                 (permute returns, hold decisions), picking skill (permute the
                 cross-section, hold the time path).

``family``       Multiple testing across a searched family: selection-bias
                 adjusted p-value for the winner, a conservative upper bound for
                 every rank, and the Romano-Wolf stepdown with strong familywise
                 error control.

``deflated_sharpe``
                 The Bailey / Lopez de Prado Probabilistic and Deflated Sharpe
                 ratios: the probability the true Sharpe clears a bar, corrected
                 for skew, kurtosis, sample length, and the expected maximum of a
                 search of N trials. Complements ``ras`` -- DSR prices the search
                 parametrically through N and the cross-trial variance, where RAS
                 measures the penalty on the actual family. Read both.

``ras``          The Rademacher Anti-Serum -- a finite-sample lower bound on the
                 true Sharpe after paying for the search, with the penalty
                 measured on the actual family rather than assumed from its size.

Reference: https://quantpylib.hangukquant.com/learn/statistical_finance/
(permutation sampling after Masters; Romano-Wolf after Romano & Wolf 2005; RAS
after Paleologo, *The Elements of Quantitative Investing*).

Every entry point takes an explicit ``numpy.random.Generator``. Nothing here
reads the global RNG, because a seed set once at the top of a notebook stops
meaning anything the moment a second consumer draws from it.
"""

from RVUtils.StatisticalFinance.deflated_sharpe import (
    EULER_MASCHERONI,
    MIN_OBS,
    annualised_to_per_period,
    deflated_sharpe_from_sharpes,
    deflated_sharpe_of_best,
    deflated_sharpe_ratio,
    effective_trials,
    effective_trials_from_corr,
    expected_max_sharpe,
    min_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_moments,
    sharpe_std_error,
)
from RVUtils.StatisticalFinance.family import (
    FamilyTestResult,
    romano_wolf,
    selection_bias_pvalue,
    topk_upper_bound,
)
from RVUtils.StatisticalFinance.mcpt import (
    PermutationResult,
    permutation_test,
    picker_pvalue,
    sharpe_of_book,
    shared_sign_flip_null,
    shuffle_weights_on_eligibles,
    timer_pvalue,
)
from RVUtils.StatisticalFinance.permutation import (
    permutation_index,
    permute_bars,
    permute_multi_bars,
    permute_multi_prices,
    permute_price,
    permute_series_within_groups,
)
from RVUtils.StatisticalFinance.ras import (
    RASResult,
    empirical_rademacher_complexity,
    ras_bound,
    standardize_returns,
)

__all__ = [
    # permutation
    "permutation_index", "permute_price", "permute_multi_prices",
    "permute_bars", "permute_multi_bars", "permute_series_within_groups",
    # mcpt
    "PermutationResult", "permutation_test", "timer_pvalue", "picker_pvalue",
    "sharpe_of_book", "shuffle_weights_on_eligibles", "shared_sign_flip_null",
    # family
    "selection_bias_pvalue", "topk_upper_bound", "romano_wolf", "FamilyTestResult",
    # ras
    "standardize_returns", "empirical_rademacher_complexity", "ras_bound", "RASResult",
    # deflated sharpe
    "EULER_MASCHERONI", "MIN_OBS", "sharpe_moments", "probabilistic_sharpe_ratio",
    "sharpe_std_error", "expected_max_sharpe", "deflated_sharpe_ratio", "effective_trials",
    "effective_trials_from_corr", "deflated_sharpe_of_best", "deflated_sharpe_from_sharpes",
    "min_track_record_length", "annualised_to_per_period",
]
