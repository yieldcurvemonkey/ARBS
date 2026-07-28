"""
Pytest configuration and shared fixtures for ARBS tests.

Provides:
- Mock market data providers
- Sample time grids
- Fixture data for curves and instruments
- Test-database URL resolution for integration tests
"""

import datetime
import os
import pandas as pd
import pytest
from typing import Any, Dict, List, Tuple
from dataclasses import dataclass


@pytest.fixture(autouse=True, scope="session")
def _isolate_stirfo_raw_eod_cache(tmp_path_factory):
    """Keep the STIR option raw-EOD disk cache out of the developer's real cache.

    ``STIRFutureOptionMDP`` memoises full-history Barchart frames in a diskcache under
    ``LayeredCacheMixin.default_cache_path``. Tests that monkeypatch the fetcher return
    small synthetic frames, and those were being written straight into that shared cache
    — so a test run could leave e.g. a one-bar ``SQZ30`` entry behind that a later *real*
    query would slice to zero rows. Point the cache at a per-session temp dir instead.
    """
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    path = tmp_path_factory.mktemp("stirfo_raw_eod_cache")
    # _RAW_EOD_CACHE_STEM is a class attribute read through self, and the diskcache handle
    # itself is per-instance, so overriding the stem is enough to redirect every MDP built
    # during the session.
    original_stem = STIRFutureOptionMDP._RAW_EOD_CACHE_STEM
    STIRFutureOptionMDP._RAW_EOD_CACHE_STEM = f"pytest_{original_stem}_{path.name}"
    try:
        yield
    finally:
        STIRFutureOptionMDP._RAW_EOD_CACHE_STEM = original_stem


@pytest.fixture(autouse=True)
def _reset_pandas_copy_on_write():
    """Force pd.options.mode.copy_on_write = False before every test.

    pandas_ta (imported transitively by BT.signals modules) sets
    copy_on_write = True at module scope in pandas_ta/core.py.  That
    happens during pytest collection — before any fixture runs — so
    saving-and-restoring the "original" value is ineffective (original
    is already True by the time the first fixture fires).

    Resetting unconditionally to False before each test ensures that
    mms.py:332 ``m &= ...`` never hits a read-only numpy buffer, and
    the BT tests themselves do not depend on CoW being True at the time
    their test bodies execute.
    """
    pd.options.mode.copy_on_write = False
    yield
    # no teardown — the next test's setup performs the reset


@pytest.fixture
def pg_test_url() -> str:
    """Return the test Postgres URL, skipping the test if unavailable.

    Reads ``PG_TEST_URL`` (preferred) or falls back to ``DATABASE_URL``.
    Tests that require a live Postgres instance (e.g. tape ingest schema
    migrations, API integration tests) consume this fixture. When neither
    env var is set, the test is skipped so contributors without a local
    Postgres can still run the rest of the suite.
    """
    url = os.environ.get("PG_TEST_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("PG_TEST_URL / DATABASE_URL not set; skipping DB test")
    return url

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

    def handle(self):
        """Return self to satisfy handle() calls in value maps."""
        return self

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

    def build_stirf(
        self,
        fwd: str | None = None,
        tenor: str | None = None,
        effective_date: datetime.date | None = None,
        maturity_date: datetime.date | None = None,
        fixed_rate: float | None = None,
        notional: float | None = None,
        bpv: float | None = None,
        is_ser: bool | None = False,
    ) -> "MockSTIRFuture":
        tenor_label = tenor or "3M"
        resolved_notional = notional or (bpv / 0.0001 if bpv is not None else 1_000_000)
        rate = fixed_rate if fixed_rate is not None else self.par_rate(tenor_label)
        return MockSTIRFuture(
            tenor=tenor_label,
            notional=resolved_notional,
            fixed_rate=rate,
            effective_date=effective_date,
            maturity_date=maturity_date,
            is_ser=is_ser or False,
        )

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

    def analytic_delta(self, instrument: Any) -> float:
        return self.pv01(instrument)

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


@dataclass
class MockSTIRFuture:
    """Mock STIR future instrument."""

    tenor: str
    notional: float
    fixed_rate: float
    effective_date: datetime.date | None = None
    maturity_date: datetime.date | None = None
    is_ser: bool = False

    @property
    def tenor_years(self) -> float:
        return MockPricer._parse_tenor(self.tenor)

    def npv(self, curves=None):
        return self.notional * (self.fixed_rate or 0) * self.tenor_years * 0.01

    def analytic_delta(self, curves=None):
        return self.notional * self.tenor_years * 0.0001

    def rate(self, curves=None):
        return self.fixed_rate


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
