"""
Pytest configuration and shared fixtures for ARBS tests.

Provides:
- Mock market data providers
- Sample time grids
- Fixture data for curves and instruments
"""

import datetime
import pytest
from typing import Any, Dict, List, Tuple
from dataclasses import dataclass

# Mock pricer that returns predictable values
@dataclass
class MockPricer:
    """
    Mock pricer for testing without QuantLib/RatesLib dependencies.

    Simulates a basic interest rate curve with linear rates.
    """
    curve_name: str
    as_of_date: datetime.date
    base_rate: float = 0.05  # 5% base rate

    def id(self) -> str:
        """Return curve identifier to satisfy structure builders."""
        return self.curve_name

    def reference_date(self) -> datetime.date:
        """Expose a reference date for date-based builders."""
        return self.as_of_date

    def build_irswap(
        self,
        fwd: str | None = None,
        tenor: str | None = None,
        effective_date: datetime.date | None = None,
        maturity_date: datetime.date | None = None,
        fixed_rate: float | None = None,
        notional: float | None = None,
        bpv: float | None = None,
    ) -> "MockInstrument":
        """Return a simple mock IRS instrument."""
        tenor_label = tenor or "1Y"
        resolved_notional = notional or (bpv / 0.0001 if bpv is not None else 1_000_000)
        rate = fixed_rate if fixed_rate is not None else self.par_rate(tenor_label)
        return MockInstrument(tenor=tenor_label, notional=resolved_notional, rate=rate)

    def fair_rate(self, instrument: "MockInstrument") -> float:
        """Return a mock fair rate for value calculations."""
        return self.par_rate(instrument.tenor)

    def par_rate(self, tenor: str) -> float:
        """Return mock par rate based on tenor."""
        tenor_years = self._parse_tenor(tenor)
        # Simple upward-sloping curve with small magnitude (in decimals)
        return 0.001 + (tenor_years * 0.00001)

    def npv(self, instrument: Any) -> float:
        """Return mock NPV."""
        # Simple NPV based on notional and rate
        notional = getattr(instrument, 'notional', 1_000_000)
        rate = getattr(instrument, 'rate', self.base_rate)
        tenor_years = getattr(instrument, 'tenor_years', 5)
        return notional * rate * tenor_years * 0.01  # Simplified

    def pv01(self, instrument: Any) -> float:
        """Return mock PV01 (dollar value of 1bp move)."""
        notional = getattr(instrument, 'notional', 1_000_000)
        tenor_years = getattr(instrument, 'tenor_years', 5)
        return notional * tenor_years * 0.0001

    def resolve_pricable(self, pricable: Any, risk_weight: float = 1.0) -> Any:
        """Resolve a generic pricable by scaling."""
        if hasattr(pricable, 'notional'):
            pricable.notional *= risk_weight
        return pricable

    @staticmethod
    def _parse_tenor(tenor: str) -> float:
        """Parse tenor string to years (e.g., '5Y' -> 5.0, '6M' -> 0.5)."""
        tenor = tenor.upper().strip()
        if tenor.endswith('Y'):
            return float(tenor[:-1])
        elif tenor.endswith('M'):
            return float(tenor[:-1]) / 12.0
        elif tenor.endswith('W'):
            return float(tenor[:-1]) / 52.0
        elif tenor.endswith('D'):
            return float(tenor[:-1]) / 365.0
        return 5.0  # default


@dataclass
class MockInstrument:
    """Mock instrument for testing."""
    tenor: str
    notional: float
    rate: float
    side: str = "receive"  # receive or pay

    @property
    def tenor_years(self) -> float:
        """Parse tenor to years."""
        return MockPricer._parse_tenor(self.tenor)


class MockMDP:
    """
    Mock Market Data Provider for testing.

    Returns MockPricer instances without requiring real market data.
    """

    def __init__(self, source: str = "MOCK", base_rate: float = 0.05):
        self.source = source
        self.base_rate = base_rate

    def get_pricer(self, request: Dict[str, Any]) -> MockPricer:
        """
        Return a mock pricer for the given request.

        Args:
            request: Dict with keys like 'curve_name', 'timestamp'

        Returns:
            MockPricer instance
        """
        curve_name = request.get('curve_name', 'MOCK-CURVE')
        timestamp = request.get('timestamp', datetime.date.today())

        if isinstance(timestamp, datetime.datetime):
            timestamp = timestamp.date()

        return MockPricer(
            curve_name=curve_name,
            as_of_date=timestamp,
            base_rate=self.base_rate
        )


@pytest.fixture
def mock_mdp():
    """Provide a mock market data provider."""
    return MockMDP(source="MOCK-TEST", base_rate=0.05)


@pytest.fixture
def simple_time_grid():
    """Provide a simple time grid of 5 business days."""
    from BT.data_handler import TimeGrid
    dates = [
        datetime.datetime(2025, 1, 6),   # Monday
        datetime.datetime(2025, 1, 7),   # Tuesday
        datetime.datetime(2025, 1, 8),   # Wednesday
        datetime.datetime(2025, 1, 9),   # Thursday
        datetime.datetime(2025, 1, 10),  # Friday
    ]
    return TimeGrid(dates)


@pytest.fixture
def monthly_time_grid():
    """Provide a monthly time grid for one quarter."""
    from BT.data_handler import TimeGrid
    dates = [
        datetime.datetime(2025, 1, 31),
        datetime.datetime(2025, 2, 28),
        datetime.datetime(2025, 3, 31),
    ]
    return TimeGrid(dates)


@pytest.fixture
def sample_curve_names():
    """Provide sample curve names for testing."""
    return [
        "USD-SOFR-1D",
        "USD-FEDFUNDS",
        "EUR-ESTR",
        "GBP-SONIA",
    ]
