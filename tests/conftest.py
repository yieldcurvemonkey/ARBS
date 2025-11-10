"""
Pytest configuration and shared fixtures for ARBS backtesting tests.

This module provides common fixtures used across unit, integration, and golden tests.
Following TDD principles, fixtures are designed to be:
- Isolated: Each test gets fresh state
- Composable: Fixtures can depend on other fixtures
- Realistic: Mock data mirrors production data structures
"""

import pytest
from datetime import datetime, date, timedelta
from pathlib import Path
import json
from typing import Dict, List, Any
from dataclasses import dataclass, field


# =============================================================================
# Directory and Path Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def tests_dir(project_root) -> Path:
    """Return the tests directory."""
    return project_root / "tests"


@pytest.fixture(scope="session")
def fixtures_dir(tests_dir) -> Path:
    """Return the fixtures directory."""
    fixture_path = tests_dir / "fixtures"
    fixture_path.mkdir(exist_ok=True)
    return fixture_path


@pytest.fixture(scope="session")
def golden_dir(tests_dir) -> Path:
    """Return the golden files directory."""
    golden_path = tests_dir / "golden" / "data"
    golden_path.mkdir(parents=True, exist_ok=True)
    return golden_path


# =============================================================================
# Date Fixtures
# =============================================================================

@pytest.fixture
def base_date() -> date:
    """Return a standard base date for testing."""
    return date(2024, 1, 15)  # Monday, mid-month


@pytest.fixture
def date_range(base_date) -> List[date]:
    """Return a 1-year date range for backtesting."""
    start = base_date
    end = start + timedelta(days=365)
    dates = []
    current = start
    while current <= end:
        # Business days only (simple check)
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


@pytest.fixture
def quarterly_dates(base_date) -> List[date]:
    """Return quarterly IMM dates (Mar, Jun, Sep, Dec third Wednesdays)."""
    year = base_date.year
    imm_dates = []
    for month in [3, 6, 9, 12]:
        # Find third Wednesday of month
        first_day = date(year, month, 1)
        # Find first Wednesday
        days_until_wed = (2 - first_day.weekday()) % 7
        first_wed = first_day + timedelta(days=days_until_wed)
        third_wed = first_wed + timedelta(weeks=2)
        imm_dates.append(third_wed)
    return imm_dates


# =============================================================================
# Mock Market Data Fixtures
# =============================================================================

@dataclass
class MockCurve:
    """Mock curve for testing without full pricer setup."""
    name: str
    currency: str
    as_of: date
    rates: Dict[str, float]  # tenor -> rate (e.g., "3M" -> 0.0525)

    def rate(self, tenor: str) -> float:
        """Get rate for a given tenor."""
        return self.rates.get(tenor, 0.05)  # Default 5%


@pytest.fixture
def mock_usd_curve(base_date) -> MockCurve:
    """Return a mock USD curve with realistic rates."""
    return MockCurve(
        name="USD-SOFR",
        currency="USD",
        as_of=base_date,
        rates={
            "1M": 0.0535,
            "3M": 0.0540,
            "6M": 0.0545,
            "1Y": 0.0520,
            "2Y": 0.0480,
            "5Y": 0.0450,
            "10Y": 0.0430,
            "30Y": 0.0420,
        }
    )


@pytest.fixture
def mock_eur_curve(base_date) -> MockCurve:
    """Return a mock EUR curve with realistic rates."""
    return MockCurve(
        name="EUR-ESTR",
        currency="EUR",
        as_of=base_date,
        rates={
            "1M": 0.0385,
            "3M": 0.0390,
            "6M": 0.0395,
            "1Y": 0.0370,
            "2Y": 0.0340,
            "5Y": 0.0320,
            "10Y": 0.0310,
            "30Y": 0.0305,
        }
    )


@dataclass
class MockFuturesPrice:
    """Mock futures price data."""
    contract: str  # e.g., "EDZ4"
    price: float
    date: date
    settlement_price: float = None
    volume: int = 0
    open_interest: int = 0

    def __post_init__(self):
        if self.settlement_price is None:
            self.settlement_price = self.price


@pytest.fixture
def mock_ed_prices(base_date) -> Dict[str, MockFuturesPrice]:
    """Return mock Eurodollar futures prices."""
    # Typical Eurodollar curve: front higher (inverted), back lower
    contracts = {
        "EDZ4": 94.50,  # Dec 2024 - 5.50%
        "EDH5": 94.75,  # Mar 2025 - 5.25%
        "EDM5": 95.00,  # Jun 2025 - 5.00%
        "EDU5": 95.20,  # Sep 2025 - 4.80%
        "EDZ5": 95.35,  # Dec 2025 - 4.65%
        "EDH6": 95.50,  # Mar 2026 - 4.50%
        "EDM6": 95.60,  # Jun 2026 - 4.40%
        "EDU6": 95.70,  # Sep 2026 - 4.30%
    }

    return {
        contract: MockFuturesPrice(
            contract=contract,
            price=price,
            date=base_date,
            volume=50000,
            open_interest=200000
        )
        for contract, price in contracts.items()
    }


# =============================================================================
# Mock Pricer Fixtures
# =============================================================================

@dataclass
class MockPricer:
    """Mock pricer for testing without full backend setup."""
    curve: MockCurve
    futures_prices: Dict[str, MockFuturesPrice] = field(default_factory=dict)

    def npv(self, priceable) -> float:
        """Mock NPV calculation."""
        # Simple mock: return random but deterministic value
        hash_val = hash(str(priceable))
        return float((hash_val % 100000) - 50000)  # Range: -50k to +50k

    def dv01(self, priceable) -> float:
        """Mock DV01 calculation."""
        # Rough estimate: 1bp of 1M notional per year of duration
        return 100.0  # $100 per bp

    def rate(self, priceable) -> float:
        """Mock rate for a swap."""
        return 0.045  # 4.5%

    def futures_price(self, contract: str) -> float:
        """Mock futures price lookup."""
        if contract in self.futures_prices:
            return self.futures_prices[contract].price
        return 95.0  # Default


@pytest.fixture
def mock_pricer(mock_usd_curve, mock_ed_prices) -> MockPricer:
    """Return a mock pricer with USD curve and futures prices."""
    return MockPricer(
        curve=mock_usd_curve,
        futures_prices=mock_ed_prices
    )


# =============================================================================
# Mock MDP Fixtures
# =============================================================================

class MockMDP:
    """Mock Market Data Provider for testing."""

    def __init__(self, curves: Dict[date, MockCurve]):
        self.curves = curves
        self.call_count = 0

    def get_pricer(self, request):
        """Return a mock pricer for the requested date."""
        self.call_count += 1
        as_of = request.as_of if hasattr(request, 'as_of') else list(self.curves.keys())[0]
        curve = self.curves.get(as_of)
        if curve is None:
            # Find closest date
            closest_date = min(self.curves.keys(), key=lambda d: abs((d - as_of).days))
            curve = self.curves[closest_date]
        return MockPricer(curve=curve)


@pytest.fixture
def mock_mdp(mock_usd_curve, date_range) -> MockMDP:
    """Return a mock MDP with curves for a date range."""
    # Create curves for each date (simplified: same rates, different as_of)
    curves = {
        d: MockCurve(
            name=mock_usd_curve.name,
            currency=mock_usd_curve.currency,
            as_of=d,
            rates=mock_usd_curve.rates.copy()
        )
        for d in date_range[::5]  # Every 5th day to reduce memory
    }
    return MockMDP(curves=curves)


# =============================================================================
# Portfolio and Position Fixtures
# =============================================================================

@dataclass
class MockPosition:
    """Mock position for testing."""
    id: str
    package: List[Any]
    weights: List[float]
    opened: datetime
    quantity: float = 1.0

    def npv(self, pricer) -> float:
        """Calculate NPV using pricer."""
        total = 0.0
        for priceable, weight in zip(self.package, self.weights):
            total += weight * pricer.npv(priceable)
        return total * self.quantity


@pytest.fixture
def mock_empty_portfolio():
    """Return an empty mock portfolio."""
    return []


@pytest.fixture
def mock_portfolio_with_positions(mock_position_irs):
    """Return a portfolio with sample positions."""
    return [mock_position_irs]


# =============================================================================
# Query Fixtures (for Query-based tests)
# =============================================================================

@pytest.fixture
def mock_position_irs():
    """Return a mock IRS position."""
    return MockPosition(
        id="IRS-001",
        package=["USD-5Y-SWAP"],  # Simplified representation
        weights=[1.0],
        opened=datetime(2024, 1, 15),
        quantity=1_000_000  # $1mm notional
    )


# =============================================================================
# Utilities for Golden File Testing
# =============================================================================

class GoldenFileHelper:
    """Helper for golden file operations."""

    def __init__(self, golden_dir: Path):
        self.golden_dir = golden_dir

    def save(self, name: str, data: Any):
        """Save data to a golden file."""
        filepath = self.golden_dir / f"{name}.json"
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def load(self, name: str) -> Any:
        """Load data from a golden file."""
        filepath = self.golden_dir / f"{name}.json"
        if not filepath.exists():
            raise FileNotFoundError(f"Golden file not found: {filepath}")
        with open(filepath, 'r') as f:
            return json.load(f)

    def exists(self, name: str) -> bool:
        """Check if a golden file exists."""
        return (self.golden_dir / f"{name}.json").exists()

    def compare(self, name: str, data: Any, tolerance: float = 1e-6) -> bool:
        """Compare data against golden file with tolerance."""
        golden_data = self.load(name)
        return self._deep_compare(data, golden_data, tolerance)

    def _deep_compare(self, a: Any, b: Any, tolerance: float) -> bool:
        """Deep comparison with tolerance for floats."""
        if isinstance(a, float) and isinstance(b, float):
            return abs(a - b) <= tolerance
        elif isinstance(a, dict) and isinstance(b, dict):
            if set(a.keys()) != set(b.keys()):
                return False
            return all(self._deep_compare(a[k], b[k], tolerance) for k in a.keys())
        elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) != len(b):
                return False
            return all(self._deep_compare(x, y, tolerance) for x, y in zip(a, b))
        else:
            return a == b


@pytest.fixture
def golden_helper(golden_dir) -> GoldenFileHelper:
    """Return a golden file helper."""
    return GoldenFileHelper(golden_dir)


# =============================================================================
# Parametrize Helpers
# =============================================================================

def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Register custom markers (already in pytest.ini, but good to have here too)
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "golden: Golden file tests")


# =============================================================================
# Test Data Generators
# =============================================================================

def generate_random_trades(count: int, base_date: date) -> List[Dict]:
    """Generate random trades for testing."""
    import random
    random.seed(42)  # Deterministic

    trades = []
    for i in range(count):
        trades.append({
            'id': f'TRADE-{i:04d}',
            'date': base_date + timedelta(days=random.randint(0, 365)),
            'product': random.choice(['IRS', 'FUTURE']),
            'quantity': random.uniform(1, 10) * 1_000_000,
            'price': random.uniform(90, 100),
        })
    return trades


@pytest.fixture
def sample_trades(base_date) -> List[Dict]:
    """Return sample trades for testing."""
    return generate_random_trades(10, base_date)
