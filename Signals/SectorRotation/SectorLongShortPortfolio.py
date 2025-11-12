# ABOUTME: Long/short portfolio constructor for sector rotation strategies
# ABOUTME: Implements long top N, short bottom N with dollar-neutral weighting
"""
SectorLongShortPortfolio - Constructs long/short portfolio from sector signals.

Heuristic Portfolio Construction (Yang & Shi 2023):
- Long: Top N sectors (highest signals)
- Short: Bottom N sectors (lowest signals)
- Equal-weighted within long/short buckets
- Dollar-neutral (sum weights = 0)
- Paper default: N=3 (long top 3, short bottom 3)

Design Rationale:
- Simple heuristic avoids complex optimization
- Equal weighting prevents concentration risk
- Dollar-neutral eliminates market beta exposure
- Top/bottom selection exploits signal extremes

Example:
    >>> portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)
    >>>
    >>> # Sector signals (z-scores from momentum/reversion/fundamental)
    >>> tickers = ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV",
    ...            "XLF", "XLK", "XLC", "XLU", "XLRE"]
    >>> z_scores = np.array([
    ...     -1.5, -1.0, -0.5, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.5
    ... ])
    >>>
    >>> # Construct weights
    >>> weights = portfolio.construct_weights(tickers, z_scores)
    >>>
    >>> # weights = {
    >>> #     "XLRE": 0.333,  # Long (best)
    >>> #     "XLU": 0.333,   # Long
    >>> #     "XLC": 0.333,   # Long
    >>> #     ...              # Middle 5 sectors: 0.0
    >>> #     "XLI": -0.333,  # Short
    >>> #     "XLB": -0.333,  # Short
    >>> #     "XLE": -0.333,  # Short (worst)
    >>> # }
    >>>
    >>> # Check dollar-neutral: sum(weights.values()) ≈ 0
"""

from typing import Dict, List, Tuple
import numpy as np
import polars as pl


class SectorLongShortPortfolio:
    """
    Constructs long/short portfolio from sector signals.

    Selects top N and bottom N sectors based on signal ranking,
    equal-weights within buckets, ensuring dollar-neutrality.

    Attributes:
        n_long: Number of sectors to long (default: 3)
        n_short: Number of sectors to short (default: 3)
        leverage: Gross leverage (default: 1.0 = 100% long, 100% short)
    """

    def __init__(
        self,
        n_long: int = 3,
        n_short: int = 3,
        leverage: float = 1.0,
    ):
        """
        Initialize long/short portfolio constructor.

        Parameters:
            n_long: Number of sectors to long (default: 3)
                   Paper's default: 3 (top 3 sectors)
            n_short: Number of sectors to short (default: 3)
                    Paper's default: 3 (bottom 3 sectors)
            leverage: Gross leverage (default: 1.0)
                     1.0 = 100% long, 100% short
                     0.5 = 50% long, 50% short
        """
        self.n_long = n_long
        self.n_short = n_short
        self.leverage = leverage

    def construct_weights(
        self,
        tickers: List[str],
        signals: np.ndarray,
    ) -> Dict[str, float]:
        """
        Construct portfolio weights from sector signals.

        Algorithm:
        1. Rank sectors by signal (highest = best)
        2. Long top n_long sectors (equal-weighted)
        3. Short bottom n_short sectors (equal-weighted)
        4. Zero weight for middle sectors
        5. Ensure dollar-neutrality (sum weights = 0)

        Parameters:
            tickers: List of sector tickers (e.g., ["XLK", "XLE", ...])
            signals: Signal values (z-scores, probabilities, etc.)
                    Higher values = stronger signals

        Returns:
            Dictionary mapping ticker → weight
            Positive weights = long, negative weights = short
            Sum of weights = 0 (dollar-neutral)

        Raises:
            ValueError: If insufficient sectors for n_long + n_short
        """
        # Validate inputs
        if len(tickers) != len(signals):
            raise ValueError(
                f"tickers and signals must have same length: "
                f"{len(tickers)} vs {len(signals)}"
            )

        if len(tickers) < self.n_long + self.n_short:
            raise ValueError(
                f"Insufficient sectors: have {len(tickers)}, "
                f"need at least {self.n_long + self.n_short} "
                f"({self.n_long} long + {self.n_short} short)"
            )

        # Rank sectors by signal (descending)
        sorted_indices = np.argsort(signals)[::-1]  # Highest first
        sorted_tickers = [tickers[i] for i in sorted_indices]

        # Select top N for long, bottom N for short
        long_tickers = sorted_tickers[:self.n_long]
        short_tickers = sorted_tickers[-self.n_short:]

        # Calculate equal weights within buckets
        # Long side: leverage / n_long (e.g., 1.0 / 3 = 0.333 each)
        # Short side: -leverage / n_short (e.g., -1.0 / 3 = -0.333 each)
        long_weight = self.leverage / self.n_long
        short_weight = -self.leverage / self.n_short

        # Construct weight dictionary
        weights = {}
        for ticker in tickers:
            if ticker in long_tickers:
                weights[ticker] = long_weight
            elif ticker in short_tickers:
                weights[ticker] = short_weight
            else:
                weights[ticker] = 0.0  # Middle sectors

        return weights

    def weights_to_dataframe(self, weights: Dict[str, float]) -> pl.DataFrame:
        """
        Convert weights dictionary to Polars DataFrame.

        Parameters:
            weights: Dictionary mapping ticker → weight

        Returns:
            DataFrame with columns [ticker, weight]
        """
        tickers = list(weights.keys())
        weight_values = [weights[ticker] for ticker in tickers]

        return pl.DataFrame({
            "ticker": tickers,
            "weight": weight_values,
        })

    def get_portfolio_statistics(self, weights: Dict[str, float]) -> Dict[str, float]:
        """
        Calculate portfolio statistics from weights.

        Parameters:
            weights: Dictionary mapping ticker → weight

        Returns:
            Dictionary with statistics:
            - total_long: Sum of positive weights
            - total_short: Sum of negative weights (absolute value)
            - net_exposure: total_long + total_short (should be ~0 for dollar-neutral)
            - gross_exposure: total_long - total_short (total leverage)
            - n_long: Number of long positions
            - n_short: Number of short positions
        """
        long_weights = [w for w in weights.values() if w > 0]
        short_weights = [w for w in weights.values() if w < 0]

        total_long = sum(long_weights)
        total_short = sum(short_weights)  # Negative value

        return {
            "total_long": total_long,
            "total_short": abs(total_short),
            "net_exposure": total_long + total_short,  # Should be ~0
            "gross_exposure": total_long - total_short,  # Total leverage
            "n_long": len(long_weights),
            "n_short": len(short_weights),
        }

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"SectorLongShortPortfolio("
            f"long={self.n_long}, "
            f"short={self.n_short}, "
            f"leverage={self.leverage}"
            f")"
        )
