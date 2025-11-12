# Sector Rotation Model - Orthogonal Task Decomposition Plan
## Parallel Execution Design for Multi-Agent Implementation

**Purpose**: Decompose sector rotation implementation into orthogonal tasks for parallel execution
**Principle**: Each task modifies different files, no shared state, clear interfaces
**Target**: 5-10 minute focused work per task
**Date**: 2025-11-11

---

## Task Decomposition Philosophy

### Orthogonality Requirements
1. **File Isolation**: Each task writes to different files (no conflicts)
2. **No Dependencies**: Tasks can execute simultaneously
3. **Clear Interfaces**: Well-defined inputs/outputs for integration
4. **Testable**: Each task produces testable output
5. **Focused**: Single responsibility, achievable in 5-10 minutes

### Integration Strategy
After parallel execution completes:
1. **Syntax Validation**: All files compile/import successfully
2. **Interface Verification**: Components connect via defined APIs
3. **Integration Tests**: End-to-end pipeline tests
4. **Performance Validation**: Meet paper's benchmark Sharpe ratios

---

## Orthogonal Task Groups

### Group A: Factor Calculation Components (4 tasks)
### Group B: Signal Generation Components (3 tasks)
### Group C: Data Providers (2 tasks)
### Group D: Portfolio Construction (2 tasks)
### Group E: Testing Infrastructure (3 tasks)
### Group F: Integration & Documentation (2 tasks)

**Total**: 16 orthogonal tasks

---

## GROUP A: Factor Calculation Components

### Task A1: Momentum Factor Calculator
**File**: `Signals/SectorRotation/MomentumFactor.py`

**Objective**: Implement MOM_nM momentum factor calculation

**Mathematical Spec**:
```python
MOM_nM = sum(past n*21 days returns) - sum(past 0.1*n*21 days returns)
```

**Implementation Requirements**:
```python
# ABOUTME: Calculates momentum factors for sector rotation strategies.
# ABOUTME: Implements MOM_nM with configurable lookback periods (Yang & Shi 2023).

import polars as pl
from typing import Optional

class MomentumFactor:
    """
    Momentum factor calculator for sector rotation.

    Implements MOM_nM = cumulative returns over n months, excluding recent 10%.
    Default: MOM_7M (optimal from paper).
    """

    def __init__(
        self,
        lookback_months: int = 7,
        exclusion_pct: float = 0.10,
        trading_days_per_month: int = 21
    ):
        """
        Initialize momentum factor calculator.

        Parameters:
            lookback_months: Number of months for cumulative return (default: 7)
            exclusion_pct: Percentage of recent period to exclude (default: 0.10)
            trading_days_per_month: Trading days per month (default: 21)
        """
        pass

    def calculate(
        self,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate momentum factor for each sector.

        Parameters:
            returns_df: DataFrame with columns [ticker, date, return]

        Returns:
            DataFrame with columns [ticker, date, momentum_factor]
        """
        pass

    def _validate_sufficient_history(self, returns_df: pl.DataFrame) -> None:
        """Validate sufficient history for lookback period."""
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_momentum_factor.py`

**Dependencies**:
- Input: Polars DataFrame (ticker, date, return)
- Output: Polars DataFrame (ticker, date, momentum_factor)

**Acceptance Criteria**:
- ✅ MOM_7M formula correctly implemented
- ✅ Handles 1M-12M lookback periods
- ✅ Excludes recent 10% of period
- ✅ Handles missing data gracefully
- ✅ All unit tests pass

---

### Task A2: Reversion Factor Calculator
**File**: `Signals/SectorRotation/ReversionFactor.py`

**Objective**: Implement REV_nD short-term reversion factor

**Mathematical Spec**:
```python
REV_nD = -sum(past n days returns)
```

**Implementation Requirements**:
```python
# ABOUTME: Calculates short-term reversion factors for sector rotation.
# ABOUTME: Implements REV_nD contrarian signals (Yang & Shi 2023).

import polars as pl

class ReversionFactor:
    """
    Short-term reversion factor calculator for sector rotation.

    Implements REV_nD = negative cumulative returns over n days.
    Default: REV_30D (optimal from paper).
    """

    def __init__(self, lookback_days: int = 30):
        """
        Initialize reversion factor calculator.

        Parameters:
            lookback_days: Number of days for cumulative return (default: 30)
        """
        pass

    def calculate(
        self,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate reversion factor for each sector.

        Parameters:
            returns_df: DataFrame with columns [ticker, date, return]

        Returns:
            DataFrame with columns [ticker, date, reversion_factor]
        """
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_reversion_factor.py`

**Dependencies**:
- Input: Polars DataFrame (ticker, date, return)
- Output: Polars DataFrame (ticker, date, reversion_factor)

**Acceptance Criteria**:
- ✅ REV_30D formula correctly implemented
- ✅ Negates cumulative return
- ✅ Handles 5D-55D lookback periods
- ✅ All unit tests pass

---

### Task A3: Cross-Sectional Neutralizer
**File**: `Signals/SectorRotation/CrossSectionalNeutralizer.py`

**Objective**: Implement cross-sectional z-score normalization

**Mathematical Spec**:
```python
X_neutral = (X - mean(X across sectors)) / std(X across sectors)
```

**Implementation Requirements**:
```python
# ABOUTME: Normalizes factors cross-sectionally for sector rotation.
# ABOUTME: Implements z-score transformation with mean=0, std=1.

import polars as pl
from typing import List

class CrossSectionalNeutralizer:
    """
    Cross-sectional factor neutralization (z-score normalization).

    Normalizes factors to mean=0, std=1 within each time period.
    Preserves ranking while making factors comparable.
    """

    def __init__(self, min_sectors: int = 2):
        """
        Initialize neutralizer.

        Parameters:
            min_sectors: Minimum sectors required for normalization (default: 2)
        """
        pass

    def neutralize(
        self,
        factor_df: pl.DataFrame,
        factor_columns: List[str]
    ) -> pl.DataFrame:
        """
        Neutralize factors cross-sectionally.

        Parameters:
            factor_df: DataFrame with columns [ticker, date, factor1, factor2, ...]
            factor_columns: List of column names to neutralize

        Returns:
            DataFrame with neutralized factors (mean=0, std=1 per date)
        """
        pass

    def _validate_sufficient_sectors(
        self,
        factor_df: pl.DataFrame,
        date: str
    ) -> None:
        """Validate sufficient sectors for normalization at each date."""
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_cross_sectional_neutral.py`

**Dependencies**:
- Input: Polars DataFrame (ticker, date, factor1, ..., factorN)
- Output: Polars DataFrame (ticker, date, factor1_neutral, ..., factorN_neutral)

**Acceptance Criteria**:
- ✅ Z-score formula correctly implemented
- ✅ Mean ≈ 0, std ≈ 1 per time period
- ✅ Preserves ranking
- ✅ Handles edge cases (constant values, outliers)
- ✅ All unit tests pass

---

### Task A4: Fundamental Factor Processor
**File**: `Signals/SectorRotation/FundamentalProcessor.py`

**Objective**: Process and validate fundamental factor data

**Implementation Requirements**:
```python
# ABOUTME: Processes fundamental factor data for sector rotation.
# ABOUTME: Validates schema, handles missing data, computes derived ratios.

import polars as pl
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class FundamentalFactors:
    """Fundamental factors for sector analysis."""
    PE: str = "PE"
    PB: str = "PB"
    EV_Sales: str = "EV_Sales"
    EV_EBIT: str = "EV_EBIT"
    EV_EBITDA: str = "EV_EBITDA"
    Dividend_Yield: str = "Dividend_Yield"
    Gross_Margin: str = "Gross_Margin"
    Operating_Margin: str = "Operating_Margin"
    Profit_Margin: str = "Profit_Margin"
    ROA: str = "ROA"
    ROE: str = "ROE"

    def all_factors(self) -> List[str]:
        """Return list of all factor names."""
        return [
            self.PE, self.PB, self.EV_Sales, self.EV_EBIT, self.EV_EBITDA,
            self.Dividend_Yield, self.Gross_Margin, self.Operating_Margin,
            self.Profit_Margin, self.ROA, self.ROE
        ]

class FundamentalProcessor:
    """
    Fundamental factor data processor.

    Validates schema, handles missing data, computes derived ratios.
    Prepares fundamental data for neural network prediction.
    """

    def __init__(self):
        """Initialize fundamental processor."""
        self.factors = FundamentalFactors()

    def process(
        self,
        fundamental_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Process fundamental factor data.

        Parameters:
            fundamental_df: Raw fundamental data with columns
                           [ticker, date, PE, PB, ..., ROE]

        Returns:
            Processed DataFrame with validated factors
        """
        pass

    def validate_schema(self, df: pl.DataFrame) -> None:
        """Validate fundamental data has required columns."""
        pass

    def handle_missing_values(self, df: pl.DataFrame) -> pl.DataFrame:
        """Handle missing values (forward fill quarterly data)."""
        pass

    def handle_outliers(
        self,
        df: pl.DataFrame,
        z_threshold: float = 3.0
    ) -> pl.DataFrame:
        """
        Handle extreme outliers (cap at z_threshold std devs).

        Parameters:
            df: Fundamental data
            z_threshold: Number of standard deviations for clipping

        Returns:
            DataFrame with outliers handled
        """
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_fundamental_factors.py`

**Dependencies**:
- Input: Polars DataFrame (ticker, date, PE, PB, ..., ROE)
- Output: Validated Polars DataFrame

**Acceptance Criteria**:
- ✅ Schema validation (all 10 factors present)
- ✅ Missing value handling
- ✅ Outlier detection and handling
- ✅ All unit tests pass

---

## GROUP B: Signal Generation Components

### Task B1: Sector Momentum Signal
**File**: `Signals/SectorRotation/SectorMomentumSignal.py`

**Objective**: Implement momentum signal class (BaseSignal subclass)

**Implementation Requirements**:
```python
# ABOUTME: Momentum signal generator for sector rotation strategies.
# ABOUTME: Inherits from BaseSignal, integrates with ARBS architecture.

import polars as pl
from Signals.BaseSignal import BaseSignal
from Signals.SectorRotation.MomentumFactor import MomentumFactor
from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

class SectorMomentumSignal(BaseSignal):
    """
    Sector momentum signal generator.

    Calculates MOM_7M factor, neutralizes cross-sectionally, generates signals.
    Inherits from BaseSignal for ARBS integration.
    """

    def __init__(
        self,
        lookback_months: int = 7,
        exclusion_pct: float = 0.10
    ):
        """
        Initialize sector momentum signal.

        Parameters:
            lookback_months: Momentum lookback period (default: 7)
            exclusion_pct: Recent period exclusion (default: 0.10)
        """
        super().__init__()
        self.momentum_calculator = MomentumFactor(lookback_months, exclusion_pct)
        self.neutralizer = CrossSectionalNeutralizer()

    def calculate(
        self,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate momentum signals for sectors.

        Parameters:
            returns_df: Returns DataFrame with columns [ticker, date, return]

        Returns:
            Signal DataFrame with columns [ticker, date, signal]
            Signal = neutralized momentum factor (z-score)
        """
        # 1. Calculate momentum factor
        # 2. Neutralize cross-sectionally
        # 3. Return as signal
        pass

    def get_positions(
        self,
        signal_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Convert signals to positions (required by BaseSignal).

        Parameters:
            signal_df: Signal DataFrame from calculate()

        Returns:
            Position DataFrame with columns [ticker, date, position]
            Position is signal value (not discrete long/short yet)
        """
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_sector_signals.py`

**Dependencies**:
- Imports: `BaseSignal`, `MomentumFactor`, `CrossSectionalNeutralizer`
- Input: Returns DataFrame
- Output: Signal DataFrame

**Acceptance Criteria**:
- ✅ Inherits from BaseSignal
- ✅ Implements required methods (calculate, get_positions)
- ✅ Integrates MomentumFactor + neutralization
- ✅ Returns correct DataFrame schema
- ✅ All unit tests pass

---

### Task B2: Sector Reversion Signal
**File**: `Signals/SectorRotation/SectorReversionSignal.py`

**Objective**: Implement reversion signal class (BaseSignal subclass)

**Implementation Requirements**:
```python
# ABOUTME: Short-term reversion signal generator for sector rotation.
# ABOUTME: Inherits from BaseSignal, implements contrarian strategy.

import polars as pl
from Signals.BaseSignal import BaseSignal
from Signals.SectorRotation.ReversionFactor import ReversionFactor
from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

class SectorReversionSignal(BaseSignal):
    """
    Sector reversion signal generator.

    Calculates REV_30D factor, neutralizes cross-sectionally, generates signals.
    Implements contrarian (mean-reversion) strategy.
    """

    def __init__(self, lookback_days: int = 30):
        """
        Initialize sector reversion signal.

        Parameters:
            lookback_days: Reversion lookback period (default: 30)
        """
        super().__init__()
        self.reversion_calculator = ReversionFactor(lookback_days)
        self.neutralizer = CrossSectionalNeutralizer()

    def calculate(
        self,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate reversion signals for sectors.

        Parameters:
            returns_df: Returns DataFrame with columns [ticker, date, return]

        Returns:
            Signal DataFrame with columns [ticker, date, signal]
            Signal = neutralized reversion factor (z-score)
        """
        pass

    def get_positions(
        self,
        signal_df: pl.DataFrame
    ) -> pl.DataFrame:
        """Convert signals to positions (required by BaseSignal)."""
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_sector_signals.py` (shared)

**Dependencies**:
- Imports: `BaseSignal`, `ReversionFactor`, `CrossSectionalNeutralizer`
- Input: Returns DataFrame
- Output: Signal DataFrame

**Acceptance Criteria**:
- ✅ Inherits from BaseSignal
- ✅ Implements required methods
- ✅ Integrates ReversionFactor + neutralization
- ✅ All unit tests pass

---

### Task B3: Fundamental Signal (Neural Network)
**File**: `Signals/SectorRotation/FundamentalSignal.py`

**Objective**: Implement fundamental signal with neural network predictor

**Implementation Requirements**:
```python
# ABOUTME: Fundamental-based signal generator using neural network.
# ABOUTME: Predicts sector returns from fundamental factors (Yang & Shi 2023).

import polars as pl
from typing import Optional
from pathlib import Path
from Signals.BaseSignal import BaseSignal
from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor
from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

class FundamentalSignal(BaseSignal):
    """
    Fundamental-based signal generator with neural network.

    Uses 10 fundamental factors to predict next-quarter sector returns.
    Neural network: 2 hidden layers (5 nodes each), trained on historical data.
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        train_if_missing: bool = False
    ):
        """
        Initialize fundamental signal.

        Parameters:
            model_path: Path to pre-trained model file (optional)
            train_if_missing: Train new model if no saved model exists
        """
        super().__init__()
        self.processor = FundamentalProcessor()
        self.neutralizer = CrossSectionalNeutralizer()
        self.model = self._load_or_train_model(model_path, train_if_missing)

    def calculate(
        self,
        fundamental_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate fundamental signals using neural network.

        Parameters:
            fundamental_df: Fundamental data with columns
                          [ticker, date, PE, PB, ..., ROE]

        Returns:
            Signal DataFrame with columns [ticker, date, signal]
            Signal = probability of positive next-quarter return [0, 1]
        """
        # 1. Process fundamentals
        # 2. Neutralize cross-sectionally
        # 3. Predict with neural network
        # 4. Return probabilities as signals
        pass

    def get_positions(
        self,
        signal_df: pl.DataFrame
    ) -> pl.DataFrame:
        """Convert probability signals to positions."""
        pass

    def _load_or_train_model(
        self,
        model_path: Optional[Path],
        train_if_missing: bool
    ):
        """
        Load pre-trained model or train new one.

        Model Architecture:
            - Input: 10 features (fundamental factors)
            - Hidden Layer 1: 5 nodes, ReLU activation
            - Hidden Layer 2: 5 nodes, ReLU activation
            - Output: 2 nodes, Sigmoid activation (binary classification)
            - Solver: Quasi-Newton (LBFGS)
            - Regularization: L2 (alpha=0.5)
        """
        pass

    def train(
        self,
        training_data: pl.DataFrame,
        validation_data: pl.DataFrame
    ) -> None:
        """
        Train neural network model.

        Parameters:
            training_data: Historical fundamental data + next-quarter returns
            validation_data: Validation set for hyperparameter tuning
        """
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_sector_signals.py` (shared)

**Dependencies**:
- Imports: `BaseSignal`, `FundamentalProcessor`, `CrossSectionalNeutralizer`
- External: `scikit-learn` MLPClassifier
- Input: Fundamental DataFrame
- Output: Signal DataFrame (probabilities)

**Acceptance Criteria**:
- ✅ Inherits from BaseSignal
- ✅ Neural network architecture matches paper (2×5 hidden layers)
- ✅ Outputs probabilities in [0, 1]
- ✅ Can load pre-trained model or train new one
- ✅ All unit tests pass

---

## GROUP C: Data Provider Components

### Task C1: Fundamental Data Query
**File**: `Query/Fundamentals/FundamentalQuery.py`

**Objective**: Create fundamental data query interface

**Implementation Requirements**:
```python
# ABOUTME: Query interface for sector fundamental data.
# ABOUTME: Defines structure for fundamental factor queries.

from dataclasses import dataclass
from datetime import date
from typing import Optional
from Query.BaseQuery import BaseQuery

@dataclass(frozen=True)
class FundamentalQuery(BaseQuery):
    """
    Query for sector fundamental data.

    Retrieves quarterly fundamental factors (PE, PB, margins, returns, etc.)
    for GICS sector indices.
    """

    ticker: str  # Sector ticker or name
    sector: str  # GICS Level 1 sector name
    start_date: date
    end_date: date
    frequency: str = "quarterly"  # Fundamental data is quarterly

    def col_name(self) -> str:
        """Return column name for this query."""
        return f"{self.ticker}_fundamentals"

    def eval_expression(self) -> str:
        """Return evaluation expression."""
        return f"FundamentalQuery({self.ticker}, {self.sector}, {self.frequency})"

    def validate(self) -> None:
        """Validate query parameters."""
        if self.frequency != "quarterly":
            raise ValueError("Fundamental data must be quarterly frequency")
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
```

**Test File**: `tests/unit/query/fundamentals/test_fundamental_query.py`

**Dependencies**:
- Imports: `BaseQuery`
- Output: Frozen dataclass (query specification)

**Acceptance Criteria**:
- ✅ Inherits from BaseQuery
- ✅ Frozen dataclass (immutable)
- ✅ Implements required methods (col_name, eval_expression)
- ✅ Validates quarterly frequency
- ✅ All unit tests pass

---

### Task C2: Fundamental Data Adapter
**File**: `Adapter/FundamentalAdapter.py`

**Objective**: Adapter to convert FundamentalQuery results to DataFrame

**Implementation Requirements**:
```python
# ABOUTME: Adapter for fundamental data query results.
# ABOUTME: Converts FundamentalQuery results to standardized DataFrame format.

import polars as pl
from typing import List
from Query.Fundamentals.FundamentalQuery import FundamentalQuery

class FundamentalAdapter:
    """
    Adapter for fundamental data.

    Converts FundamentalQuery results to standardized DataFrame:
    - Columns: [ticker, date, PE, PB, EV_Sales, ..., ROE, sector]
    - Quarterly frequency
    - Wide format (one row per sector-date)
    """

    def __init__(self):
        """Initialize fundamental adapter."""
        pass

    def convert(
        self,
        queries: List[FundamentalQuery],
        mdp_results: dict
    ) -> pl.DataFrame:
        """
        Convert query results to DataFrame.

        Parameters:
            queries: List of FundamentalQuery objects
            mdp_results: Results from MarketDataProvider

        Returns:
            DataFrame with columns:
                - ticker (str)
                - date (datetime)
                - PE, PB, EV_Sales, EV_EBIT, EV_EBITDA (float)
                - Dividend_Yield (float)
                - Gross_Margin, Operating_Margin, Profit_Margin (float)
                - ROA, ROE (float)
                - sector (str)
        """
        pass

    def _validate_output(self, df: pl.DataFrame) -> None:
        """Validate output DataFrame has required schema."""
        pass
```

**Test File**: `tests/unit/adapter/test_fundamental_adapter.py`

**Dependencies**:
- Imports: `FundamentalQuery`
- Input: List of queries + MDP results dict
- Output: Polars DataFrame

**Acceptance Criteria**:
- ✅ Converts query results to DataFrame
- ✅ Correct schema (11 fundamental factors + ticker/date/sector)
- ✅ Quarterly frequency maintained
- ✅ All unit tests pass

---

## GROUP D: Portfolio Construction Components

### Task D1: Sector Long-Short Portfolio Constructor
**File**: `Portfolio/SectorLongShortPortfolio.py`

**Objective**: Construct long/short sector rotation portfolio from signals

**Implementation Requirements**:
```python
# ABOUTME: Constructs long/short sector rotation portfolios.
# ABOUTME: Implements top-bottom ranking strategy with equal weighting.

import polars as pl
from typing import Tuple

class SectorLongShortPortfolio:
    """
    Sector rotation long/short portfolio constructor.

    Strategy:
        - Rank sectors by signal
        - Long top N sectors (equal-weighted)
        - Short bottom N sectors (equal-weighted)
        - Dollar-neutral (longs = shorts)
    """

    def __init__(
        self,
        n_long: int = 3,
        n_short: int = 3,
        equal_weighted: bool = True
    ):
        """
        Initialize portfolio constructor.

        Parameters:
            n_long: Number of sectors to long (default: 3)
            n_short: Number of sectors to short (default: 3)
            equal_weighted: Equal weighting within buckets (default: True)
        """
        self.n_long = n_long
        self.n_short = n_short
        self.equal_weighted = equal_weighted

    def construct(
        self,
        signal_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Construct portfolio weights from signals.

        Parameters:
            signal_df: Signal DataFrame with columns [ticker, date, signal]

        Returns:
            Portfolio DataFrame with columns [ticker, date, weight]
            - Top N: positive weights (sum to 1.0)
            - Bottom N: negative weights (sum to -1.0)
            - Middle: zero weights
            - Dollar-neutral: sum(weights) = 0
        """
        pass

    def _rank_signals(
        self,
        signal_df: pl.DataFrame,
        date: str
    ) -> pl.DataFrame:
        """Rank sectors by signal for given date."""
        pass

    def _calculate_weights(
        self,
        ranked_df: pl.DataFrame
    ) -> pl.DataFrame:
        """Calculate equal weights for long/short buckets."""
        pass

    def _validate_dollar_neutrality(self, weights_df: pl.DataFrame) -> None:
        """Validate portfolio is dollar-neutral per date."""
        pass
```

**Test File**: `tests/unit/signals/sector_rotation/test_sector_portfolio.py`

**Dependencies**:
- Input: Signal DataFrame
- Output: Weight DataFrame

**Acceptance Criteria**:
- ✅ Long top N, short bottom N sectors
- ✅ Equal weighting within buckets
- ✅ Dollar-neutral (sum weights = 0)
- ✅ Handles tied signals deterministically
- ✅ All unit tests pass

---

### Task D2: Sector Rotation Backtest Runner
**File**: `Backtest/SectorRotationBacktest.py`

**Objective**: Backtest runner for sector rotation strategies

**Implementation Requirements**:
```python
# ABOUTME: Backtesting framework for sector rotation strategies.
# ABOUTME: Integrates signals, portfolio construction, and performance analysis.

import polars as pl
from typing import Dict, Optional
from Signals.BaseSignal import BaseSignal
from Portfolio.SectorLongShortPortfolio import SectorLongShortPortfolio
from Portfolio.Portfolio import Portfolio
from Analysis.TearSheet import TearSheet

class SectorRotationBacktest:
    """
    Sector rotation strategy backtester.

    Integrates:
        - Signal generation (momentum, reversion, fundamental)
        - Portfolio construction (long/short)
        - Performance tracking (TearSheet)
    """

    def __init__(
        self,
        signal: BaseSignal,
        portfolio_constructor: SectorLongShortPortfolio,
        rebalance_frequency: str = "monthly"
    ):
        """
        Initialize backtest runner.

        Parameters:
            signal: Signal generator (SectorMomentumSignal, etc.)
            portfolio_constructor: Portfolio constructor
            rebalance_frequency: Rebalancing frequency (default: monthly)
        """
        self.signal = signal
        self.portfolio_constructor = portfolio_constructor
        self.rebalance_frequency = rebalance_frequency

    def run(
        self,
        returns_df: pl.DataFrame,
        start_date: str,
        end_date: str
    ) -> Dict:
        """
        Run backtest.

        Parameters:
            returns_df: Returns DataFrame with columns [ticker, date, return]
            start_date: Backtest start date
            end_date: Backtest end date

        Returns:
            Results dictionary:
                - portfolio_returns: Portfolio return time series
                - holdings: Historical holdings
                - tear_sheet: TearSheet analysis
                - metrics: Performance metrics (Sharpe, IC, etc.)
        """
        pass

    def _generate_signals(
        self,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """Generate signals using configured signal generator."""
        pass

    def _construct_portfolios(
        self,
        signal_df: pl.DataFrame
    ) -> pl.DataFrame:
        """Construct portfolios from signals."""
        pass

    def _calculate_portfolio_returns(
        self,
        weights_df: pl.DataFrame,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """Calculate portfolio returns from weights and sector returns."""
        pass

    def _generate_tear_sheet(
        self,
        portfolio_returns: pl.DataFrame
    ) -> TearSheet:
        """Generate performance tear sheet."""
        pass
```

**Test File**: `tests/integration/test_sector_rotation_pipeline.py`

**Dependencies**:
- Imports: `BaseSignal`, `SectorLongShortPortfolio`, `Portfolio`, `TearSheet`
- Input: Returns DataFrame
- Output: Backtest results dict

**Acceptance Criteria**:
- ✅ Runs end-to-end backtest
- ✅ Integrates signal → portfolio → returns
- ✅ Produces TearSheet
- ✅ Handles monthly rebalancing
- ✅ All integration tests pass

---

## GROUP E: Testing Infrastructure Components

### Task E1: Sector Rotation Test Fixtures
**File**: `tests/fixtures/sector_rotation_fixtures.py`

**Objective**: Create reusable test fixtures for sector rotation tests

**Implementation Requirements**:
```python
# ABOUTME: Test fixtures for sector rotation strategy tests.
# ABOUTME: Provides mock data and helper functions for unit/integration tests.

import pytest
import polars as pl
import numpy as np
from datetime import datetime, timedelta
from typing import List

@pytest.fixture
def mock_sector_returns():
    """
    Generate mock daily returns for 11 GICS sectors.

    Returns:
        DataFrame with columns [ticker, date, return]
        - 11 sectors × 252 trading days
        - Different trend/volatility per sector
    """
    sectors = [
        "XLE",   # Energy
        "XLB",   # Materials
        "XLI",   # Industrials
        "XLY",   # Consumer Discretionary
        "XLP",   # Consumer Staples
        "XLV",   # Health Care
        "XLF",   # Financials
        "XLK",   # Information Technology
        "XLC",   # Communication Services
        "XLU",   # Utilities
        "XLRE"   # Real Estate
    ]
    # Generate mock returns with different characteristics
    pass

@pytest.fixture
def mock_fundamental_data():
    """
    Generate mock quarterly fundamental data for 11 sectors.

    Returns:
        DataFrame with columns [ticker, date, PE, PB, ..., ROE, sector]
        - 11 sectors × 20 quarters (5 years)
    """
    pass

@pytest.fixture
def mock_trained_nn_model(tmp_path):
    """
    Generate pre-trained neural network model for testing.

    Returns:
        Path to saved model file
    """
    pass

def assert_dataframe_schema(
    df: pl.DataFrame,
    required_columns: List[str]
) -> None:
    """
    Assert DataFrame has required columns.

    Parameters:
        df: DataFrame to validate
        required_columns: List of required column names

    Raises:
        AssertionError if schema is incorrect
    """
    pass

def assert_dollar_neutral(
    weights_df: pl.DataFrame,
    tolerance: float = 1e-6
) -> None:
    """
    Assert portfolio weights are dollar-neutral per date.

    Parameters:
        weights_df: DataFrame with columns [ticker, date, weight]
        tolerance: Numerical tolerance for zero sum
    """
    pass

def assert_cross_sectional_normalized(
    factor_df: pl.DataFrame,
    factor_columns: List[str],
    tolerance: float = 1e-2
) -> None:
    """
    Assert factors are cross-sectionally normalized (mean=0, std=1).

    Parameters:
        factor_df: DataFrame with factor columns
        factor_columns: List of factor column names
        tolerance: Tolerance for mean=0, std=1
    """
    pass
```

**Test File**: Tests use these fixtures (no separate test file)

**Dependencies**:
- External: `pytest`, `polars`, `numpy`
- Output: Pytest fixtures

**Acceptance Criteria**:
- ✅ Fixtures generate valid mock data
- ✅ Helper functions validate common patterns
- ✅ Reusable across all test files
- ✅ Well-documented

---

### Task E2: Performance Benchmark Tests
**File**: `tests/integration/test_performance_benchmarks.py`

**Objective**: Implement tests that validate paper's performance benchmarks

**Implementation Requirements**:
```python
# ABOUTME: Performance benchmark tests for sector rotation strategies.
# ABOUTME: Validates strategies replicate paper results (within tolerance).

import pytest
import polars as pl
from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal
from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal
from Signals.SectorRotation.FundamentalSignal import FundamentalSignal
from Portfolio.SectorLongShortPortfolio import SectorLongShortPortfolio
from Backtest.SectorRotationBacktest import SectorRotationBacktest

class TestMomentumBenchmark:
    """Test MOM_7M strategy replication."""

    def test_mom_7m_sharpe_ratio(self, real_sector_data_2017_2022):
        """
        Test MOM_7M achieves Sharpe > 0.4 (target: 0.62).

        Paper Result (2017-2022):
            - Annual Return: 21.19%
            - Sharpe Ratio: 0.62

        Tolerance:
            - Sharpe: 0.40-0.85 (±0.22)
        """
        # Setup
        signal = SectorMomentumSignal(lookback_months=7)
        portfolio = SectorLongShortPortfolio(n_long=2, n_short=2)
        backtest = SectorRotationBacktest(signal, portfolio)

        # Run
        results = backtest.run(
            real_sector_data_2017_2022,
            start_date="2017-01-01",
            end_date="2022-12-31"
        )

        # Assert
        assert results["metrics"]["sharpe_ratio"] > 0.40
        assert results["metrics"]["sharpe_ratio"] < 0.85

class TestReversionBenchmark:
    """Test REV_30D strategy replication."""

    def test_rev_30d_sharpe_ratio(self, real_sector_data_2002_2022):
        """
        Test REV_30D achieves Sharpe > 0.6 (target: 0.87).

        Paper Result (2002-2022):
            - Annual Return: 8.77%
            - Sharpe Ratio: 0.8735

        Tolerance:
            - Sharpe: 0.60-1.10 (±0.27)
        """
        pass

class TestFundamentalBenchmark:
    """Test neural network strategy replication."""

    def test_fundamental_nn_sharpe_ratio(
        self,
        real_fundamental_data_2020_2021
    ):
        """
        Test fundamental NN achieves Sharpe > 1.5 (target: 2.21).

        Paper Result (Sept 2020 - Sept 2021):
            - Sharpe Ratio: 2.21 (test set)

        Tolerance:
            - Sharpe: 1.50-3.00 (±0.71)

        Note: Short test period (1 year) → high variance.
        """
        pass

# Real data fixtures (requires actual data)
@pytest.fixture
def real_sector_data_2017_2022():
    """Load real S&P GICS sector data (2017-2022) via YahooFinanceMDP."""
    pass

@pytest.fixture
def real_sector_data_2002_2022():
    """Load real S&P GICS sector data (2002-2022) via YahooFinanceMDP."""
    pass

@pytest.fixture
def real_fundamental_data_2020_2021():
    """Load real fundamental data (Sept 2020 - Sept 2021)."""
    pass
```

**Test File**: This IS the test file

**Dependencies**:
- Imports: All signal/portfolio/backtest classes
- Data: Real sector data (via YahooFinanceMDP or similar)

**Acceptance Criteria**:
- ✅ Tests validate paper's Sharpe ratio benchmarks
- ✅ Reasonable tolerance bands (paper results may vary by data source)
- ✅ Can run with real data or skip if data unavailable
- ✅ Clear pass/fail criteria

---

### Task E3: Unit Test Implementation (Factor Tests)
**File**: `tests/unit/signals/sector_rotation/test_momentum_factor.py`
**File**: `tests/unit/signals/sector_rotation/test_reversion_factor.py`

**Objective**: Implement all unit tests from test specifications

**Implementation Requirements**:
Implement all test classes and methods defined in `sector_rotation_test_specifications.md`:
- `TestMomentumFactorConstruction`
- `TestMomentumSignalGeneration`
- `TestMomentumFactorReturns`
- `TestMomentumEdgeCases`
- `TestReversionFactorConstruction`
- `TestReversionSignalGeneration`
- `TestReversionFactorReturns`
- `TestReversionEdgeCases`

**Dependencies**:
- Imports: Factor calculation classes
- Fixtures: `mock_sector_returns`, etc.

**Acceptance Criteria**:
- ✅ All test methods implemented (not just pass stubs)
- ✅ Tests follow TDD: define expected behavior clearly
- ✅ Tests use fixtures and assertions effectively
- ✅ Coverage: 100% of factor calculation code

---

## GROUP F: Integration & Documentation

### Task F1: End-to-End Integration Test
**File**: `tests/integration/test_sector_rotation_pipeline.py`

**Objective**: Implement complete pipeline integration tests

**Implementation Requirements**:
```python
# ABOUTME: End-to-end integration tests for sector rotation pipeline.
# ABOUTME: Tests complete flow from data ingestion to performance analysis.

import pytest
from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal
from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal
from Signals.SectorRotation.FundamentalSignal import FundamentalSignal
from Portfolio.SectorLongShortPortfolio import SectorLongShortPortfolio
from Backtest.SectorRotationBacktest import SectorRotationBacktest
from Analysis.TearSheet import TearSheet

class TestSectorRotationPipeline:
    """End-to-end pipeline tests."""

    def test_momentum_pipeline_completes(self, mock_sector_returns):
        """
        Test momentum strategy runs end-to-end without errors.

        Pipeline:
            1. Generate momentum signals
            2. Construct long/short portfolio
            3. Calculate returns
            4. Produce tear sheet

        Assert:
            - Pipeline completes without exceptions
            - Returns DataFrame has expected shape
            - TearSheet contains metrics
        """
        # Initialize components
        signal = SectorMomentumSignal(lookback_months=7)
        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)
        backtest = SectorRotationBacktest(signal, portfolio)

        # Run pipeline
        results = backtest.run(
            mock_sector_returns,
            start_date="2022-01-01",
            end_date="2022-12-31"
        )

        # Assert results structure
        assert "portfolio_returns" in results
        assert "holdings" in results
        assert "tear_sheet" in results
        assert "metrics" in results

        # Assert metrics present
        assert "sharpe_ratio" in results["metrics"]
        assert "annual_return" in results["metrics"]
        assert "max_drawdown" in results["metrics"]

    def test_reversion_pipeline_completes(self, mock_sector_returns):
        """Test reversion strategy pipeline."""
        pass

    def test_fundamental_pipeline_completes(
        self,
        mock_sector_returns,
        mock_fundamental_data,
        mock_trained_nn_model
    ):
        """Test fundamental strategy pipeline."""
        pass

    def test_combined_signal_pipeline(
        self,
        mock_sector_returns,
        mock_fundamental_data
    ):
        """
        Test combined strategy (momentum + reversion + fundamental).

        Assert:
            - All three signals combine successfully
            - Combined Sharpe >= individual Sharpes (diversification)
        """
        pass

class TestARBSArchitectureCompliance:
    """Test integration with ARBS architecture."""

    def test_signals_inherit_base_signal(self):
        """Test all sector signals inherit from BaseSignal."""
        from Signals.BaseSignal import BaseSignal

        assert issubclass(SectorMomentumSignal, BaseSignal)
        assert issubclass(SectorReversionSignal, BaseSignal)
        assert issubclass(FundamentalSignal, BaseSignal)

    def test_uses_equity_query_and_adapter(self):
        """Test sector data uses EquityQuery/ETFQuery and EquityAdapter."""
        pass

    def test_uses_returns_calculator(self):
        """Test returns calculated via ReturnsCalculator."""
        pass

    # ... (other architecture compliance tests)
```

**Test File**: This IS the test file

**Dependencies**:
- Imports: All implemented components
- Fixtures: All mock data fixtures

**Acceptance Criteria**:
- ✅ Complete pipeline tests implemented
- ✅ Tests validate end-to-end flow
- ✅ ARBS architecture compliance verified
- ✅ All integration tests pass

---

### Task F2: Architecture Documentation & Implementation Guide
**File**: `docs/papers/sector_rotation_implementation_guide.md`

**Objective**: Document implementation aligned with ARBS architecture

**Implementation Requirements**:
```markdown
# Sector Rotation Implementation Guide
## Architecture Alignment with ARBS

### Overview
Implementation of sector rotation strategies (Yang & Shi 2023) within ARBS framework.

### Architecture Diagram

```
Data Layer:
    YahooFinanceMDP → EquityQuery/ETFQuery → EquityAdapter → Returns DataFrame

Factor Layer:
    Returns → MomentumFactor → CrossSectionalNeutralizer → Momentum Signal
    Returns → ReversionFactor → CrossSectionalNeutralizer → Reversion Signal
    Fundamentals → FundamentalProcessor → Neural Network → Fundamental Signal

Signal Layer:
    SectorMomentumSignal(BaseSignal)
    SectorReversionSignal(BaseSignal)
    FundamentalSignal(BaseSignal)
    ↓
    SignalCombiner (optional)

Portfolio Layer:
    Signals → SectorLongShortPortfolio → Weights
    Weights → Portfolio (composite asset)

Backtest Layer:
    SectorRotationBacktest → Portfolio Returns → TearSheet
```

### Component Mapping

| Paper Component | ARBS Component | File Path |
|----------------|----------------|-----------|
| MOM_7M Factor | MomentumFactor | Signals/SectorRotation/MomentumFactor.py |
| REV_30D Factor | ReversionFactor | Signals/SectorRotation/ReversionFactor.py |
| Cross-Sectional Z-Score | CrossSectionalNeutralizer | Signals/SectorRotation/CrossSectionalNeutralizer.py |
| Momentum Signal | SectorMomentumSignal | Signals/SectorRotation/SectorMomentumSignal.py |
| Reversion Signal | SectorReversionSignal | Signals/SectorRotation/SectorReversionSignal.py |
| Neural Network Predictor | FundamentalSignal | Signals/SectorRotation/FundamentalSignal.py |
| Long/Short Portfolio | SectorLongShortPortfolio | Portfolio/SectorLongShortPortfolio.py |
| Backtest Runner | SectorRotationBacktest | Backtest/SectorRotationBacktest.py |

### Grinold-Kahn Integration

#### Fundamental Law Application
```
IR = IC × sqrt(Breadth)
```

For sector rotation:
- **IC**: Information Coefficient from signal-return correlation
- **Breadth**: ~11 sectors (adjusted for correlation)
- **Transfer Coefficient**: Implicit in long/short portfolio construction

#### Alpha Generation
```
Alpha_i = IC × Vol_i × Z_i
```

Where:
- `IC`: Signal information coefficient (measured historically)
- `Vol_i`: Sector volatility forecast
- `Z_i`: Normalized signal (z-score)

Implemented via `AlphaGenerator.scale_alphas()`.

### Extension Points

New sector strategies can be added by:
1. Creating new `BaseSignal` subclass
2. Implementing `calculate()` and `get_positions()` methods
3. Adding to `SignalCombiner` if combining with existing signals

### Usage Examples

#### Example 1: Momentum Strategy
```python
from Signals.SectorRotation import SectorMomentumSignal
from Portfolio import SectorLongShortPortfolio
from Backtest import SectorRotationBacktest

# Initialize
signal = SectorMomentumSignal(lookback_months=7)
portfolio = SectorLongShortPortfolio(n_long=2, n_short=2)
backtest = SectorRotationBacktest(signal, portfolio)

# Run
results = backtest.run(returns_df, "2017-01-01", "2022-12-31")
print(f"Sharpe: {results['metrics']['sharpe_ratio']:.2f}")
```

#### Example 2: Combined Strategy
```python
from Signals.SectorRotation import (
    SectorMomentumSignal,
    SectorReversionSignal,
    FundamentalSignal
)
from Signals import SignalCombiner

# Combine signals
mom_signal = SectorMomentumSignal(lookback_months=7)
rev_signal = SectorReversionSignal(lookback_days=30)
fund_signal = FundamentalSignal(model_path="models/fundamental_nn.pkl")

combined = SignalCombiner(
    signals=[mom_signal, rev_signal, fund_signal],
    weights=[0.4, 0.3, 0.3]
)

# Backtest combined strategy
backtest = SectorRotationBacktest(combined, portfolio)
results = backtest.run(returns_df, "2017-01-01", "2022-12-31")
```

### Testing Strategy

1. **Unit Tests**: Individual components (factors, signals, neutralization)
2. **Integration Tests**: End-to-end pipeline
3. **Performance Tests**: Replicate paper's Sharpe ratios
4. **Stress Tests**: 2008 crisis, COVID crash

### Performance Expectations

| Strategy | Period | Target Sharpe | Tolerance |
|----------|--------|---------------|-----------|
| MOM_7M | 2017-2022 | 0.62 | 0.40-0.85 |
| REV_30D | 2002-2022 | 0.87 | 0.60-1.10 |
| Fundamental NN | 2020-2021 | 2.21 | 1.50-3.00 |

### Next Steps

1. Implement components in parallel (see task decomposition)
2. Run unit tests (TDD: tests first, then implementation)
3. Integration testing
4. Performance validation on real data
5. Production deployment

---
```

**Dependencies**:
- None (documentation only)

**Acceptance Criteria**:
- ✅ Clear architecture diagram
- ✅ Component mapping to paper
- ✅ Grinold-Kahn integration explained
- ✅ Usage examples provided
- ✅ Extension points documented

---

## Task Execution Summary

### Parallel Execution Groups

**Group A** (Factor Calculation) - 4 tasks:
- A1: MomentumFactor
- A2: ReversionFactor
- A3: CrossSectionalNeutralizer
- A4: FundamentalProcessor

**Group B** (Signal Generation) - 3 tasks:
- B1: SectorMomentumSignal
- B2: SectorReversionSignal
- B3: FundamentalSignal

**Group C** (Data Providers) - 2 tasks:
- C1: FundamentalQuery
- C2: FundamentalAdapter

**Group D** (Portfolio Construction) - 2 tasks:
- D1: SectorLongShortPortfolio
- D2: SectorRotationBacktest

**Group E** (Testing Infrastructure) - 3 tasks:
- E1: Sector Rotation Test Fixtures
- E2: Performance Benchmark Tests
- E3: Unit Test Implementation

**Group F** (Integration & Docs) - 2 tasks:
- F1: End-to-End Integration Test
- F2: Architecture Documentation

### Execution Plan

**Phase 1: Foundation (Groups A, C, E1)**
- Execute tasks A1-A4, C1-C2, E1 in parallel
- Duration: ~5-10 minutes per task = 40-80 minutes total (parallelized)
- Output: Factor calculators, data queries, test fixtures

**Phase 2: Signals (Groups B, E3)**
- Execute tasks B1-B3, E3 in parallel
- Depends on: Phase 1 complete
- Duration: ~5-10 minutes per task = 25-50 minutes total (parallelized)
- Output: Signal generators, unit tests

**Phase 3: Portfolio & Backtest (Group D, E2)**
- Execute tasks D1-D2, E2 in parallel
- Depends on: Phase 2 complete
- Duration: ~5-10 minutes per task = 20-40 minutes total (parallelized)
- Output: Portfolio construction, backtest runner, benchmark tests

**Phase 4: Integration (Group F)**
- Execute tasks F1-F2 in parallel
- Depends on: Phase 3 complete
- Duration: ~10-15 minutes per task = 20-30 minutes total (parallelized)
- Output: Integration tests, documentation

**Total Time (parallelized)**: ~105-200 minutes (~2-3 hours)
**Total Time (sequential)**: ~400-800 minutes (~7-13 hours)

**Speedup Factor**: ~4-6x via parallel execution

---

## Integration Checklist

After all tasks complete, verify:

### Syntactic Integration
- [ ] All files import successfully (`python -c "import Signals.SectorRotation"`)
- [ ] No circular imports
- [ ] Correct abstract class inheritance

### Semantic Integration
- [ ] Signal classes implement BaseSignal interface
- [ ] DataFrames have consistent schemas (ticker, date, ...)
- [ ] Factor outputs feed into signal inputs correctly

### Functional Integration
- [ ] End-to-end pipeline runs without errors
- [ ] Portfolio weights are dollar-neutral
- [ ] Returns calculated correctly

### Performance Integration
- [ ] Unit tests pass (100% of implemented tests)
- [ ] Integration tests pass
- [ ] Performance benchmarks met (within tolerance)

---

## Success Metrics

### Implementation Success
- ✅ All 16 tasks completed
- ✅ 0 linter/type errors
- ✅ 100% test coverage on new code
- ✅ All tests passing (unit + integration)

### Performance Success
- ✅ MOM_7M: Sharpe ratio > 0.4 (target: 0.62)
- ✅ REV_30D: Sharpe ratio > 0.6 (target: 0.87)
- ✅ Fundamental NN: Sharpe ratio > 1.5 (target: 2.21)

### Architecture Success
- ✅ All components inherit from ARBS base classes
- ✅ No modifications to existing core abstractions
- ✅ Extensible design (new signals easy to add)

---

**END OF ORTHOGONAL TASK DECOMPOSITION PLAN**

This plan enables:
1. **Parallel execution**: 16 independent tasks across 5-6 agents
2. **No conflicts**: Each task writes to different files
3. **Clear interfaces**: Well-defined inputs/outputs for integration
4. **Testable components**: Every task produces testable output
5. **Rapid implementation**: 2-3 hours parallelized vs 7-13 hours sequential
