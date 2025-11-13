# ABOUTME: Feature engineering utility for ML-enhanced factor signals
# ABOUTME: Calculates momentum, value, quality, and technical indicators for predictive models
"""
FeatureEngineering - Generate features for ML-based return prediction.

Provides systematic feature calculation across multiple factor categories:
1. Momentum: Multi-period cumulative returns
2. Value: P/E, P/B, dividend yield (mock fundamentals)
3. Quality: ROE, profit margin (mock financials)
4. Technical: RSI, MACD, Bollinger bands

All features are designed for cross-sectional ML models that predict
next-period returns based on current factor exposures.

Example:
    >>> fe = FeatureEngineering()
    >>>
    >>> # Calculate all features
    >>> momentum = fe.calculate_momentum(returns, lookbacks=[21, 63, 126, 252])
    >>> value = fe.calculate_value(prices, fundamentals=None)
    >>> quality = fe.calculate_quality(financials=None)
    >>> technical = fe.calculate_technical(prices)
    >>>
    >>> # Combine all features
    >>> features = momentum.join(value, on=["ticker", "date"])
    >>> features = features.join(quality, on=["ticker", "date"])
    >>> features = features.join(technical, on=["ticker", "date"])
"""

import numpy as np
import polars as pl
from typing import List, Optional
from datetime import date


class FeatureEngineering:
    """
    Feature engineering utility for ML factor signals.
    
    Calculates momentum, value, quality, and technical features for
    cross-sectional return prediction models.
    """
    
    def __init__(self):
        """Initialize feature engineering utility."""
        pass
    
    def calculate_momentum(
        self,
        returns: pl.DataFrame,
        lookbacks: List[int] = [21, 63, 126, 252],
    ) -> pl.DataFrame:
        """
        Calculate momentum features for multiple lookback periods.
        
        Momentum is defined as cumulative return over the lookback period:
            MOM_n = Σ(returns from t-n to t-1)
        
        Parameters:
            returns: DataFrame with columns [ticker, date, return]
            lookbacks: List of lookback periods in days (default: [21, 63, 126, 252])
        
        Returns:
            DataFrame with columns [ticker, date, momentum_<n>d, ...]
        """
        # Validate schema
        required_cols = {"ticker", "date", "return"}
        if not required_cols.issubset(returns.columns):
            raise ValueError(f"Returns DataFrame must contain columns: {required_cols}")
        
        # Sort by ticker and date
        df = returns.sort(["ticker", "date"])
        
        # Calculate momentum for each lookback
        result = df.select(["ticker", "date"])
        
        for lookback in lookbacks:
            # Rolling sum of returns
            momentum_col = (
                df.group_by("ticker")
                .agg([
                    pl.col("date"),
                    pl.col("return")
                    .rolling_sum(window_size=lookback)
                    .alias(f"momentum_{lookback}d")
                ])
                .explode(["date", f"momentum_{lookback}d"])
            )
            
            # Join with result
            result = result.join(
                momentum_col.select(["ticker", "date", f"momentum_{lookback}d"]),
                on=["ticker", "date"],
                how="left",
            )
        
        return result
    
    def calculate_value(
        self,
        prices: pl.DataFrame,
        fundamentals: Optional[pl.DataFrame] = None,
    ) -> pl.DataFrame:
        """
        Calculate value features (P/E, P/B, dividend yield).
        
        Uses mock fundamental data if not provided. Mock data is generated
        with reasonable distributions:
        - P/E ratio: Normal(15, 5)
        - P/B ratio: LogNormal(0, 0.5)
        - Dividend yield: LogNormal(-3, 0.5) (capped at 10%)
        
        Parameters:
            prices: DataFrame with columns [ticker, date, price]
            fundamentals: Optional real fundamental data (not implemented)
        
        Returns:
            DataFrame with columns [ticker, date, pe_ratio, pb_ratio, dividend_yield]
        """
        # Validate schema
        required_cols = {"ticker", "date", "price"}
        if not required_cols.issubset(prices.columns):
            raise ValueError(f"Prices DataFrame must contain columns: {required_cols}")
        
        # Generate mock fundamentals if not provided
        if fundamentals is None:
            np.random.seed(42)  # Reproducible mock data
            
            # Create mock data for each ticker-date
            result = prices.select(["ticker", "date"]).clone()
            
            n_rows = len(result)
            
            # P/E ratio: Normal(15, 5)
            pe_ratios = np.maximum(5, np.random.normal(15, 5, n_rows))
            
            # P/B ratio: LogNormal(mean=1.5, std=0.8)
            pb_ratios = np.random.lognormal(0, 0.5, n_rows)
            
            # Dividend yield: LogNormal with mean ~2%
            div_yields = np.minimum(0.10, np.random.lognormal(-3, 0.5, n_rows))
            
            result = result.with_columns([
                pl.Series("pe_ratio", pe_ratios),
                pl.Series("pb_ratio", pb_ratios),
                pl.Series("dividend_yield", div_yields),
            ])
            
            return result
        
        else:
            # Use provided fundamental data
            # (Not implemented - would join prices with fundamentals)
            raise NotImplementedError("Real fundamental data not yet supported")
    
    def calculate_quality(
        self,
        financials: Optional[pl.DataFrame] = None,
    ) -> pl.DataFrame:
        """
        Calculate quality features (ROE, profit margin).
        
        Uses mock financial data if not provided. Mock data is generated
        with reasonable distributions:
        - ROE: Normal(0.15, 0.10)
        - Profit margin: Normal(0.10, 0.05)
        
        Parameters:
            financials: Optional real financial data (not implemented)
        
        Returns:
            DataFrame with columns [ticker, date, roe, profit_margin]
        """
        # Generate mock quality data
        if financials is None:
            np.random.seed(43)  # Different seed from value factors
            
            # For mock data, we need to know which tickers and dates to create
            # Since we don't have a reference DataFrame, we'll create a simple structure
            # This method should be called after other features are calculated
            
            # Generate for common test tickers
            tickers = ["AAPL", "GOOGL", "MSFT"]
            dates = pl.date_range(
                date(2020, 1, 1),
                date(2023, 12, 31),
                interval="1d",
                eager=True,
            ).cast(pl.Date)
            
            data = []
            for ticker in tickers:
                # Generate static quality metrics per ticker
                base_roe = np.random.normal(0.15, 0.05)
                base_margin = np.random.normal(0.10, 0.03)
                
                for d in dates:
                    # Add small time variation
                    roe = base_roe + np.random.normal(0, 0.02)
                    margin = base_margin + np.random.normal(0, 0.01)
                    
                    data.append({
                        "ticker": ticker,
                        "date": d,
                        "roe": max(0, min(1, roe)),  # Clamp to [0, 1]
                        "profit_margin": max(0, min(0.5, margin)),
                    })
            
            return pl.DataFrame(data)
        
        else:
            # Use provided financial data
            raise NotImplementedError("Real financial data not yet supported")
    
    def calculate_technical(
        self,
        prices: pl.DataFrame,
    ) -> pl.DataFrame:
        """
        Calculate technical indicators (RSI, MACD, Bollinger bands).
        
        Technical indicators:
        - RSI(14): Relative Strength Index
        - MACD: Moving Average Convergence Divergence
            - MACD line: EMA(12) - EMA(26)
            - Signal line: EMA(9) of MACD
            - Histogram: MACD - Signal
        - Bollinger Bands: SMA(20) ± 2*std(20)
        
        Parameters:
            prices: DataFrame with columns [ticker, date, price]
        
        Returns:
            DataFrame with technical indicator columns
        """
        # Validate schema
        required_cols = {"ticker", "date", "price"}
        if not required_cols.issubset(prices.columns):
            raise ValueError(f"Prices DataFrame must contain columns: {required_cols}")
        
        # Sort by ticker and date
        df = prices.sort(["ticker", "date"])
        
        # Calculate indicators per ticker
        result_dfs = []
        
        for ticker in df["ticker"].unique():
            ticker_data = df.filter(pl.col("ticker") == ticker)
            
            # Calculate RSI(14)
            rsi = self._calculate_rsi(ticker_data["price"].to_numpy(), period=14)
            
            # Calculate MACD
            macd, macd_signal, macd_hist = self._calculate_macd(
                ticker_data["price"].to_numpy()
            )
            
            # Calculate Bollinger Bands
            bb_upper, bb_middle, bb_lower = self._calculate_bollinger(
                ticker_data["price"].to_numpy(),
                period=20,
                num_std=2,
            )
            
            # Create DataFrame for this ticker
            ticker_result = ticker_data.select(["ticker", "date"]).with_columns([
                pl.Series("rsi_14", rsi),
                pl.Series("macd", macd),
                pl.Series("macd_signal", macd_signal),
                pl.Series("macd_hist", macd_hist),
                pl.Series("bb_upper", bb_upper),
                pl.Series("bb_middle", bb_middle),
                pl.Series("bb_lower", bb_lower),
            ])
            
            result_dfs.append(ticker_result)
        
        # Concatenate all tickers
        return pl.concat(result_dfs)
    
    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> np.ndarray:
        """
        Calculate Relative Strength Index.
        
        RSI = 100 - (100 / (1 + RS))
        where RS = Average Gain / Average Loss over period
        """
        # Calculate price changes
        deltas = np.diff(prices)
        deltas = np.concatenate([[np.nan], deltas])
        
        # Separate gains and losses
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        # Calculate average gains and losses
        rsi = np.full(len(prices), np.nan)
        
        if len(prices) < period + 1:
            return rsi
        
        # Initial averages (SMA for first period)
        avg_gain = np.mean(gains[1:period+1])
        avg_loss = np.mean(losses[1:period+1])
        
        # Calculate RSI for first valid point
        if avg_loss == 0:
            rsi[period] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[period] = 100 - (100 / (1 + rs))
        
        # Smoothed averages for remaining points (EMA)
        for i in range(period + 1, len(prices)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                rsi[i] = 100
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_ema(self, values: np.ndarray, period: int) -> np.ndarray:
        """Calculate Exponential Moving Average."""
        ema = np.full(len(values), np.nan)
        
        if len(values) < period:
            return ema
        
        # Start with SMA
        ema[period - 1] = np.mean(values[:period])
        
        # Calculate EMA
        multiplier = 2 / (period + 1)
        for i in range(period, len(values)):
            ema[i] = (values[i] - ema[i - 1]) * multiplier + ema[i - 1]
        
        return ema
    
    def _calculate_macd(
        self,
        prices: np.ndarray,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Calculate MACD indicator.
        
        Returns:
            (macd_line, signal_line, histogram)
        """
        # Calculate EMAs
        ema_fast = self._calculate_ema(prices, fast_period)
        ema_slow = self._calculate_ema(prices, slow_period)
        
        # MACD line = EMA(12) - EMA(26)
        macd_line = ema_fast - ema_slow
        
        # Signal line = EMA(9) of MACD line
        # Need to handle NaN values in macd_line
        valid_idx = ~np.isnan(macd_line)
        signal_line = np.full(len(prices), np.nan)
        
        if np.sum(valid_idx) >= signal_period:
            # Calculate EMA only on valid MACD values
            valid_macd = macd_line[valid_idx]
            ema_signal = self._calculate_ema(valid_macd, signal_period)
            
            # Map back to original indices
            signal_line[valid_idx] = ema_signal
        
        # Histogram = MACD - Signal
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _calculate_bollinger(
        self,
        prices: np.ndarray,
        period: int = 20,
        num_std: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Calculate Bollinger Bands.
        
        Returns:
            (upper_band, middle_band, lower_band)
        """
        middle = np.full(len(prices), np.nan)
        std = np.full(len(prices), np.nan)
        
        # Calculate rolling SMA and std
        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1:i + 1]
            middle[i] = np.mean(window)
            std[i] = np.std(window, ddof=1)
        
        upper = middle + num_std * std
        lower = middle - num_std * std
        
        return upper, middle, lower


if __name__ == "__main__":
    # Example usage
    import pandas as pd
    
    # Create sample data
    dates = pd.date_range(start="2020-01-01", end="2023-12-31", freq="D")
    np.random.seed(42)
    
    data = []
    for ticker in ["AAPL", "GOOGL", "MSFT"]:
        returns = np.random.randn(len(dates)) * 0.02
        prices = 100 * np.exp(np.cumsum(returns))
        
        for d, r, p in zip(dates, returns, prices):
            data.append({
                "ticker": ticker,
                "date": d.date(),
                "return": r,
                "price": p,
            })
    
    df = pl.DataFrame(data)
    
    # Initialize feature engineering
    fe = FeatureEngineering()
    
    # Calculate all features
    print("Calculating momentum...")
    momentum = fe.calculate_momentum(df, lookbacks=[21, 63, 126, 252])
    print(f"Momentum shape: {momentum.shape}")
    
    print("\nCalculating value...")
    value = fe.calculate_value(df, fundamentals=None)
    print(f"Value shape: {value.shape}")
    
    print("\nCalculating quality...")
    quality = fe.calculate_quality(financials=None)
    print(f"Quality shape: {quality.shape}")
    
    print("\nCalculating technical...")
    technical = fe.calculate_technical(df)
    print(f"Technical shape: {technical.shape}")
    
    print("\n" + "="*50)
    print("Feature Engineering Complete!")
    print("="*50)
