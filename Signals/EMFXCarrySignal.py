# ABOUTME: EM FX carry signal for emerging market currency trading (NEW CAPABILITY)
# ABOUTME: Interest rate differential carry trades with risk adjustment and UIP violation detection

"""
EM FX Carry Signal

Implements carry trade strategy for emerging market currencies based on
interest rate differentials and Uncovered Interest Parity (UIP) violations.

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
    >>> # Prepare currency data
    >>> brl_data = pl.DataFrame({
    ...     "date": dates,
    ...     "interest_rate": [0.1375] * len(dates),  # 13.75% Brazil
    ...     "fx_rate": fx_rates_brl_usd,
    ...     "usd_rate": [0.055] * len(dates)  # 5.5% USD
    ... })
    >>>
    >>> # Evaluate multiple EM currencies
    >>> signals = signal.evaluate_multiple(
    ...     as_of_date=date(2024, 6, 1),
    ...     currency_data={"BRL": brl_data, "TRY": try_data, "MXN": mxn_data}
    ... )
    >>>
    >>> # Generate portfolio weights (long/short)
    >>> weights = signal.generate_portfolio_weights(signals)
    >>> # weights: {"BRL": 0.35, "TRY": 0.45, "MXN": -0.15, ...} (dollar-neutral)

References:
-----------
- Lustig, Roussanov, Verdelhan (2011): "Common Risk Factors in Currency Markets"
- Burnside, Eichenbaum, Rebelo (2011): "Carry Trade and Momentum in Currency Markets"
- Menkhoff, Sarno, Schmeling, Schrimpf (2012): "Carry Trades and Global FX Volatility"
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Literal

import numpy as np
import polars as pl


@dataclass
class EMFXCarrySignal:
    """
    EM FX carry signal based on interest rate differentials.

    Generates trading signals for emerging market currencies using:
    - Interest rate differentials (carry)
    - FX volatility (risk adjustment)
    - Cross-sectional ranking
    - UIP violation detection

    Attributes:
        funding_currency: Low-yield funding currency (default: "USD")
        lookback_days: Historical window for volatility (default: 60)
        risk_adjust: Whether to adjust for FX volatility (default: True)
        normalization: Signal normalization method ("z_score", "rank", "none")
        long_threshold: Z-score threshold for long positions (default: 0.5)
        short_threshold: Z-score threshold for short positions (default: -0.5)
    """

    funding_currency: str = "USD"
    lookback_days: int = 60
    risk_adjust: bool = True
    normalization: Literal["z_score", "rank", "none"] = "z_score"
    long_threshold: float = 0.5
    short_threshold: float = -0.5

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

    def evaluate_single(
        self,
        as_of_date: date,
        target_data: pl.DataFrame,
        funding_rate: float
    ) -> float:
        """
        Evaluate carry signal for a single currency.

        Args:
            as_of_date: Evaluation date
            target_data: DataFrame with columns: date, interest_rate, fx_rate
            funding_rate: Funding currency interest rate

        Returns:
            Carry signal (raw or risk-adjusted)

        Raises:
            ValueError: If required columns missing or insufficient data
        """
        # Validate columns
        required_cols = ["date", "interest_rate", "fx_rate"]
        missing = [col for col in required_cols if col not in target_data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Filter to lookback window
        start_date = as_of_date - timedelta(days=self.lookback_days)
        window_data = target_data.filter(
            (pl.col("date") >= start_date) & (pl.col("date") <= as_of_date)
        )

        if window_data.height < 20:
            raise ValueError(f"Insufficient data: {window_data.height} observations")

        # Get current interest rate
        current = window_data.filter(pl.col("date") == as_of_date)
        if current.height == 0:
            # Use most recent
            current = window_data.sort("date").tail(1)

        target_rate = float(current["interest_rate"][0])

        # Calculate carry
        carry = self._calculate_interest_differential(target_rate, funding_rate)

        # Risk adjustment if requested
        if self.risk_adjust:
            # Calculate FX returns
            fx_data = self._calculate_fx_returns(window_data, "fx_rate")
            fx_data = fx_data.filter(pl.col("fx_return").is_not_nan())

            # Calculate volatility
            fx_vol = self._calculate_fx_volatility(fx_data)

            # Risk-adjusted carry
            carry = self._calculate_carry_to_risk(carry, fx_vol)

        return float(carry)

    def evaluate_multiple(
        self,
        as_of_date: date,
        currency_data: Dict[str, pl.DataFrame],
        funding_rate: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Evaluate carry signals across multiple currencies.

        Args:
            as_of_date: Evaluation date
            currency_data: Dict mapping currency code -> DataFrame (date, interest_rate, fx_rate)
            funding_rate: Funding currency rate (if None, use from data)

        Returns:
            Dict mapping currency code -> signal score
        """
        raw_signals = {}

        for currency, data in currency_data.items():
            try:
                # Extract funding rate if not provided
                if funding_rate is None:
                    if "usd_rate" in data.columns:
                        rate_data = data.filter(pl.col("date") == as_of_date)
                        if rate_data.height > 0:
                            funding_rate = float(rate_data["usd_rate"][0])
                        else:
                            funding_rate = 0.05  # Default fallback
                    else:
                        funding_rate = 0.05  # Default fallback

                signal = self.evaluate_single(as_of_date, data, funding_rate)
                raw_signals[currency] = signal

            except Exception as e:
                print(f"Warning: Could not evaluate {currency}: {e}")
                raw_signals[currency] = 0.0

        # Normalize signals
        if self.normalization != "none":
            return self._normalize_signals(raw_signals)

        return raw_signals

    def _normalize_signals(
        self,
        raw_signals: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Normalize signals using z-score or rank.

        Args:
            raw_signals: Dict of raw signal values

        Returns:
            Dict of normalized signal values
        """
        if len(raw_signals) == 0:
            return {}

        values = np.array(list(raw_signals.values()))
        keys = list(raw_signals.keys())

        if self.normalization == "z_score":
            # Z-score normalization
            mean = np.mean(values)
            std = np.std(values, ddof=1) if len(values) > 1 else 1.0

            if std < 1e-10:
                std = 1.0

            normalized = (values - mean) / std

        elif self.normalization == "rank":
            # Rank normalization to [-1, 1]
            ranks = np.argsort(np.argsort(values))  # Ranks from 0 to N-1
            n = len(values)

            if n == 1:
                normalized = np.array([0.0])
            else:
                # Scale to [-1, 1]
                normalized = -1.0 + 2.0 * ranks / (n - 1)

        else:
            normalized = values

        return {key: float(val) for key, val in zip(keys, normalized)}

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
            signals: Dict of carry signals
            top_n: Number of top currencies to return

        Returns:
            List of currency codes sorted by carry (descending)
        """
        sorted_currencies = sorted(signals.items(), key=lambda x: x[1], reverse=True)
        return [currency for currency, _ in sorted_currencies[:top_n]]
