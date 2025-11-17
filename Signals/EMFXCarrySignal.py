# ABOUTME: EM FX carry signal for emerging market currency trading (extends BaseSignal)
# ABOUTME: Interest rate differential carry trades with risk adjustment and UIP violation detection

"""
EM FX Carry Signal

Implements carry trade strategy for emerging market currencies based on
interest rate differentials and Uncovered Interest Parity (UIP) violations.

Extends BaseSignal for integration with Grinold-Kahn framework:
- Raw carry calculation per currency (_calculate_raw_signal)
- Cross-sectional z-score standardization (via BaseSignal)
- Information Coefficient (IC) tracking
- Signal history and metadata

Carry Trade Logic:
------------------
1. Borrow in low-yield currency (funding currency, typically USD)
2. Lend in high-yield currency (target EM currency)
3. Profit = interest differential - FX depreciation
4. UIP violation: High-yield currencies don't depreciate as much as theory predicts

Key Concepts:
-------------
- Carry: Interest rate differential (target rate - funding rate)
- Forward Premium: (Forward FX - Spot FX) / Spot FX
- UIP Violation: Carry - Forward Premium (alpha opportunity)
- Carry-to-Risk: Carry / FX Volatility (Sharpe-like ratio)

Applications:
-------------
- Long high-carry EM currencies vs USD
- Risk-adjusted carry (vol targeting)
- Cross-sectional EM FX strategies
- Tactical FX allocation

Usage:
------
    >>> from Signals.EMFXCarrySignal import EMFXCarrySignal
    >>> import polars as pl
    >>>
    >>> # Create signal
    >>> signal = EMFXCarrySignal(
    ...     funding_currency="USD",
    ...     lookback_days=60,
    ...     risk_adjust=True
    ... )
    >>>
    >>> # Prepare currency data (one per currency)
    >>> brl_data = pl.DataFrame({
    ...     "date": dates,
    ...     "interest_rate": [0.1375] * len(dates),  # 13.75% Brazil
    ...     "fx_rate": fx_rates_brl_usd,
    ...     "usd_rate": [0.055] * len(dates)  # 5.5% USD
    ... })
    >>>
    >>> # Generate cross-sectional signals (z-scores)
    >>> currency_data_list = [brl_data, try_data, mxn_data, zar_data]
    >>> z_scores = signal.generate_batch(
    ...     inst_data_list=currency_data_list,
    ...     market_data=None,
    ...     as_of=date(2024, 6, 1)
    ... )
    >>> # z_scores: array of z-scores (mean=0, std=1) for each currency
    >>>
    >>> # Generate portfolio weights (long/short)
    >>> currency_labels = ["BRL", "TRY", "MXN", "ZAR"]
    >>> weights = signal.generate_portfolio_weights_from_scores(z_scores, currency_labels)
    >>> # weights: {"BRL": 0.35, "TRY": 0.45, "MXN": -0.15, "ZAR": 0.10} (dollar-neutral)

References:
-----------
- Lustig, Roussanov, Verdelhan (2011): "Common Risk Factors in Currency Markets"
- Burnside, Eichenbaum, Rebelo (2011): "Carry Trade and Momentum in Currency Markets"
- Menkhoff, Sarno, Schmeling, Schrimpf (2012): "Carry Trades and Global FX Volatility"
"""

from datetime import date, timedelta
from typing import Dict, List, Optional, Any

import numpy as np
import polars as pl

from Signals.Base.BaseSignal import BaseSignal


class EMFXCarrySignal(BaseSignal):
    """
    EM FX carry signal based on interest rate differentials.

    Extends BaseSignal to provide:
    - Interest differential calculation (carry)
    - FX volatility adjustment (risk-adjusted carry)
    - Cross-sectional z-score normalization
    - UIP violation detection
    - IC tracking and signal history

    Attributes:
        funding_currency: Low-yield funding currency (default: "USD")
        lookback_days: Historical window for volatility (default: 60)
        risk_adjust: Whether to adjust for FX volatility (default: True)
        long_threshold: Z-score threshold for long positions (default: 0.5)
        short_threshold: Z-score threshold for short positions (default: -0.5)
    """

    def __init__(
        self,
        funding_currency: str = "USD",
        lookback_days: int = 60,
        risk_adjust: bool = True,
        long_threshold: float = 0.5,
        short_threshold: float = -0.5,
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize EM FX carry signal.

        Parameters:
            funding_currency: Low-yield funding currency (default: "USD")
            lookback_days: Historical window for volatility calculation (default: 60 days)
            risk_adjust: If True, adjust carry by FX volatility (default: True)
            long_threshold: Z-score threshold for long positions (default: 0.5)
            short_threshold: Z-score threshold for short positions (default: -0.5)
            standardize: If True, return z-scored alphas (default: True)
            track_history: If True, store signal generation history (default: True)
        """
        # Initialize BaseSignal
        super().__init__(
            name="em_fx_carry",
            standardize=standardize,
            track_history=track_history,
        )

        # Store EM FX carry specific parameters
        self.funding_currency = funding_currency
        self.lookback_days = lookback_days
        self.risk_adjust = risk_adjust
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw carry signal for a single currency.

        This method is called by BaseSignal.generate() and generate_batch().
        It computes the carry value (potentially risk-adjusted) for one EM currency.

        Parameters:
            inst_data: DataFrame with columns: date, interest_rate, fx_rate, usd_rate (optional)
                      Must contain historical data for lookback window
            market_data: Not used for EM FX carry (all data is currency-specific)
            as_of: Calculation date (must be within inst_data date range)

        Returns:
            Raw carry value (before cross-sectional standardization)
            If risk_adjust=True: carry-to-risk ratio (carry / FX vol)
            If risk_adjust=False: simple carry (target rate - funding rate)

        Raises:
            ValueError: If missing required columns or insufficient data
        """
        # Validate columns
        required_cols = ["date", "interest_rate", "fx_rate"]
        missing = [col for col in required_cols if col not in inst_data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Filter to lookback window
        start_date = as_of - timedelta(days=self.lookback_days)
        window_data = inst_data.filter(
            (pl.col("date") >= start_date) & (pl.col("date") <= as_of)
        )

        if window_data.height < 20:
            raise ValueError(
                f"Insufficient data: {window_data.height} observations "
                f"(need at least 20 for volatility calculation)"
            )

        # Get current interest rate (as of date)
        current = window_data.filter(pl.col("date") == as_of)
        if current.height == 0:
            # Use most recent if exact date not available
            current = window_data.sort("date").tail(1)

        target_rate = float(current["interest_rate"][0])

        # Get funding rate
        if "usd_rate" in current.columns:
            funding_rate = float(current["usd_rate"][0])
        else:
            # Default fallback if not provided
            funding_rate = 0.055  # 5.5% default USD rate

        # Calculate carry (interest differential)
        carry = self._calculate_interest_differential(target_rate, funding_rate)

        # Risk adjustment if requested
        if self.risk_adjust:
            # Calculate FX returns
            fx_data = self._calculate_fx_returns(window_data, "fx_rate")
            fx_data = fx_data.filter(pl.col("fx_return").is_not_nan())

            if fx_data.height < 20:
                # Not enough data for vol calculation, return raw carry
                return float(carry)

            # Calculate volatility
            fx_vol = self._calculate_fx_volatility(fx_data)

            # Risk-adjusted carry (Sharpe-like ratio)
            carry = self._calculate_carry_to_risk(carry, fx_vol)

        return float(carry)

    # -------------------------------------------------------------------------
    # Helper Methods (Carry Calculation)
    # -------------------------------------------------------------------------

    def _calculate_interest_differential(
        self,
        target_rate: float,
        funding_rate: float
    ) -> float:
        """
        Calculate interest rate differential (carry).

        Args:
            target_rate: Target currency interest rate (annual)
            funding_rate: Funding currency interest rate (annual)

        Returns:
            Interest differential (carry) as decimal
        """
        return target_rate - funding_rate

    def _calculate_forward_premium(
        self,
        spot_rate: float,
        forward_rate: float
    ) -> float:
        """
        Calculate forward premium/discount.

        Args:
            spot_rate: Spot FX rate (target currency per funding currency)
            forward_rate: Forward FX rate

        Returns:
            Forward premium as decimal (positive = premium, negative = discount)
        """
        if spot_rate <= 0:
            return 0.0

        return (forward_rate - spot_rate) / spot_rate

    def _calculate_fx_volatility(
        self,
        fx_history: pl.DataFrame,
        return_column: str = "fx_return"
    ) -> float:
        """
        Calculate annualized FX volatility from returns.

        Args:
            fx_history: DataFrame with FX returns
            return_column: Name of return column

        Returns:
            Annualized volatility as decimal

        Raises:
            ValueError: If insufficient data
        """
        if fx_history.height < 20:
            raise ValueError(f"Insufficient data for volatility: {fx_history.height} observations")

        returns = fx_history[return_column].to_numpy()

        # Calculate standard deviation
        vol_daily = np.std(returns, ddof=1)

        # Annualize: vol_annual = vol_daily * sqrt(252)
        vol_annual = vol_daily * np.sqrt(252)

        return float(vol_annual)

    def _calculate_carry_to_risk(
        self,
        carry: float,
        fx_volatility: float
    ) -> float:
        """
        Calculate carry-to-risk ratio (Sharpe-like metric).

        Args:
            carry: Interest rate differential
            fx_volatility: Annualized FX volatility

        Returns:
            Carry-to-risk ratio
        """
        if fx_volatility <= 1e-10:
            # Handle zero volatility
            return 0.0 if carry == 0 else np.sign(carry) * 100.0

        return carry / fx_volatility

    def _check_uip_violation(
        self,
        interest_differential: float,
        forward_premium: float
    ) -> float:
        """
        Check Uncovered Interest Parity (UIP) violation.

        UIP states: Forward premium = Interest differential
        Violation: Alpha opportunity exists

        Args:
            interest_differential: Interest rate diff (target - funding)
            forward_premium: Forward FX premium

        Returns:
            UIP violation magnitude (positive = carry opportunity)
        """
        # UIP violation = interest_diff - forward_premium
        # If positive: High-yield currency expected to depreciate less than forward implies
        return interest_differential - forward_premium

    def _calculate_realized_carry(
        self,
        annual_carry: float,
        days_held: int
    ) -> float:
        """
        Calculate realized carry for holding period.

        Args:
            annual_carry: Annual interest differential
            days_held: Number of days position was held

        Returns:
            Realized carry for period
        """
        return annual_carry * (days_held / 365.0)

    def _calculate_fx_returns(
        self,
        fx_rates: pl.DataFrame,
        rate_column: str = "fx_rate"
    ) -> pl.DataFrame:
        """
        Calculate FX returns from spot rates.

        Args:
            fx_rates: DataFrame with FX spot rates
            rate_column: Name of FX rate column

        Returns:
            DataFrame with added "fx_return" column
        """
        # Sort by date
        fx_rates = fx_rates.sort("date")

        # Calculate log returns
        rates = fx_rates[rate_column].to_numpy()
        log_returns = np.diff(np.log(rates))

        # Add returns to dataframe (first return is NaN)
        result = fx_rates.clone()
        return_series = [np.nan] + log_returns.tolist()
        result = result.with_columns(
            pl.Series("fx_return", return_series)
        )

        return result

    # -------------------------------------------------------------------------
    # Portfolio Construction Helpers
    # -------------------------------------------------------------------------

    def generate_portfolio_weights_from_scores(
        self,
        z_scores: np.ndarray,
        currency_labels: List[str],
        equal_weight: bool = False
    ) -> Dict[str, float]:
        """
        Generate dollar-neutral portfolio weights from z-scores.

        This is a helper method for portfolio construction after generate_batch().

        Args:
            z_scores: Array of z-scores from generate_batch()
            currency_labels: List of currency codes (same order as z_scores)
            equal_weight: If True, equal weight longs/shorts. If False, proportional

        Returns:
            Dict of portfolio weights (sum = 0 for dollar neutral)
        """
        # Convert to dict for easier manipulation
        signals = {currency: float(z_scores[i]) for i, currency in enumerate(currency_labels)}

        return self.generate_portfolio_weights(signals, equal_weight)

    def generate_portfolio_weights(
        self,
        signals: Dict[str, float],
        equal_weight: bool = False
    ) -> Dict[str, float]:
        """
        Generate dollar-neutral portfolio weights from carry signals.

        Args:
            signals: Dict of normalized carry signals
            equal_weight: If True, equal weight longs/shorts. If False, proportional

        Returns:
            Dict of portfolio weights (sum = 0 for dollar neutral)
        """
        weights = {}

        # Classify into long/short/neutral
        longs = {k: v for k, v in signals.items() if v > self.long_threshold}
        shorts = {k: v for k, v in signals.items() if v < self.short_threshold}

        if equal_weight:
            # Equal weight within longs and shorts
            if len(longs) > 0:
                long_weight = 1.0 / len(longs)
                for currency in longs:
                    weights[currency] = long_weight

            if len(shorts) > 0:
                short_weight = -1.0 / len(shorts)
                for currency in shorts:
                    weights[currency] = short_weight
        else:
            # Proportional to signal strength
            if len(longs) > 0:
                long_total = sum(longs.values())
                for currency, signal in longs.items():
                    weights[currency] = signal / long_total if long_total > 0 else 0.0

            if len(shorts) > 0:
                short_total = sum(abs(s) for s in shorts.values())
                for currency, signal in shorts.items():
                    weights[currency] = signal / short_total if short_total > 0 else 0.0

        # Add neutrals as zero weight
        for currency in signals:
            if currency not in weights:
                weights[currency] = 0.0

        # Ensure dollar neutral (adjust if needed)
        total = sum(weights.values())
        if abs(total) > 1e-6:
            # Normalize to sum to zero
            adjustment = total / len(weights)
            for currency in weights:
                weights[currency] -= adjustment

        return weights

    def get_top_carry_currencies(
        self,
        signals: Dict[str, float],
        top_n: int = 5
    ) -> List[str]:
        """
        Get top N currencies by carry signal.

        Args:
            signals: Dict of carry signals (z-scores)
            top_n: Number of top currencies to return

        Returns:
            List of currency codes sorted by carry (descending)
        """
        sorted_currencies = sorted(signals.items(), key=lambda x: x[1], reverse=True)
        return [currency for currency, _ in sorted_currencies[:top_n]]

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"EMFXCarrySignal("
            f"name='{self.name}', "
            f"funding={self.funding_currency}, "
            f"lookback={self.lookback_days}, "
            f"risk_adjust={self.risk_adjust}, "
            f"standardize={self.standardize}"
            f")"
        )
