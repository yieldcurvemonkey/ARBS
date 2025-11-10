"""
Smoke tests to verify pytest setup and fixtures.

These tests ensure the testing infrastructure is working correctly.
Following TDD: These tests were written FIRST to validate the test framework.
"""

import pytest
from datetime import date, timedelta
from pathlib import Path


class TestPytestSetup:
    """Test that pytest is configured correctly."""

    def test_pytest_works(self):
        """Basic sanity check that pytest runs."""
        assert True

    def test_can_import_fixtures(self, base_date):
        """Test that conftest fixtures are accessible."""
        assert isinstance(base_date, date)
        assert base_date == date(2024, 1, 15)

    def test_project_root_fixture(self, project_root):
        """Test that project root fixture works."""
        assert isinstance(project_root, Path)
        assert project_root.exists()
        assert (project_root / "BT").exists()
        assert (project_root / "Query").exists()


class TestDateFixtures:
    """Test date-related fixtures."""

    def test_base_date(self, base_date):
        """Test base_date fixture provides expected date."""
        assert base_date == date(2024, 1, 15)
        assert base_date.weekday() == 0  # Monday

    def test_date_range(self, date_range):
        """Test date_range fixture provides business days."""
        assert len(date_range) > 250  # ~252 trading days per year
        assert len(date_range) < 265  # Account for leap years

        # Check all are weekdays
        for d in date_range:
            assert d.weekday() < 5, f"{d} is not a weekday"

    def test_quarterly_dates(self, quarterly_dates):
        """Test quarterly_dates fixture provides IMM dates."""
        assert len(quarterly_dates) == 4

        # Check months are March, June, September, December
        months = [d.month for d in quarterly_dates]
        assert months == [3, 6, 9, 12]

        # Check all are Wednesdays
        for d in quarterly_dates:
            assert d.weekday() == 2, f"{d} is not a Wednesday"


class TestMockMarketData:
    """Test mock market data fixtures."""

    def test_mock_usd_curve(self, mock_usd_curve):
        """Test USD curve fixture."""
        assert mock_usd_curve.currency == "USD"
        assert "3M" in mock_usd_curve.rates
        assert mock_usd_curve.rate("3M") == 0.0540

        # Test default rate
        assert mock_usd_curve.rate("99Y") == 0.05

    def test_mock_eur_curve(self, mock_eur_curve):
        """Test EUR curve fixture."""
        assert mock_eur_curve.currency == "EUR"
        assert "3M" in mock_eur_curve.rates
        assert mock_eur_curve.rate("3M") == 0.0390

    def test_mock_ed_prices(self, mock_ed_prices):
        """Test SOFR futures prices fixture."""
        assert "SFRZ4" in mock_ed_prices
        assert mock_ed_prices["SFRZ4"].price == 94.50
        assert mock_ed_prices["SFRZ4"].contract == "SFRZ4"

        # Test curve shape (inverted)
        assert mock_ed_prices["SFRZ4"].price < mock_ed_prices["SFRH5"].price
        assert mock_ed_prices["SFRH5"].price < mock_ed_prices["SFRM5"].price


class TestMockPricer:
    """Test mock pricer fixture."""

    def test_mock_pricer_curve(self, mock_pricer):
        """Test pricer has curve."""
        assert mock_pricer.curve is not None
        assert mock_pricer.curve.currency == "USD"

    def test_mock_pricer_futures_prices(self, mock_pricer):
        """Test pricer has futures prices."""
        price = mock_pricer.futures_price("SFRZ4")
        assert price == 94.50

        # Test default
        default_price = mock_pricer.futures_price("UNKNOWN")
        assert default_price == 95.0

    def test_mock_pricer_methods(self, mock_pricer):
        """Test pricer calculation methods."""
        dummy_priceable = "TEST"

        npv = mock_pricer.npv(dummy_priceable)
        assert isinstance(npv, float)

        dv01 = mock_pricer.dv01(dummy_priceable)
        assert dv01 == 100.0

        rate = mock_pricer.rate(dummy_priceable)
        assert rate == 0.045


class TestMockMDP:
    """Test mock MDP fixture."""

    def test_mock_mdp_get_pricer(self, mock_mdp, base_date):
        """Test MDP returns pricer."""
        class MockRequest:
            as_of = base_date

        pricer = mock_mdp.get_pricer(MockRequest())
        assert pricer is not None
        assert pricer.curve is not None

    def test_mock_mdp_call_count(self, mock_mdp, base_date):
        """Test MDP tracks calls."""
        class MockRequest:
            as_of = base_date

        initial_count = mock_mdp.call_count
        mock_mdp.get_pricer(MockRequest())
        assert mock_mdp.call_count == initial_count + 1


class TestGoldenFileHelper:
    """Test golden file helper."""

    def test_golden_helper_save_and_load(self, golden_helper, tmp_path):
        """Test saving and loading golden files."""
        # Use tmp_path for this test to avoid polluting golden dir
        from tests.conftest import GoldenFileHelper
        temp_helper = GoldenFileHelper(tmp_path)

        test_data = {"key": "value", "number": 42}
        temp_helper.save("test", test_data)

        assert temp_helper.exists("test")

        loaded = temp_helper.load("test")
        assert loaded == test_data

    def test_golden_helper_compare(self, tmp_path):
        """Test golden file comparison with tolerance."""
        from tests.conftest import GoldenFileHelper
        temp_helper = GoldenFileHelper(tmp_path)

        golden_data = {"price": 100.0, "dv01": 150.5}
        temp_helper.save("golden", golden_data)

        # Exact match
        assert temp_helper.compare("golden", {"price": 100.0, "dv01": 150.5})

        # Within tolerance
        assert temp_helper.compare(
            "golden",
            {"price": 100.0000001, "dv01": 150.5000001},
            tolerance=1e-6
        )

        # Outside tolerance
        assert not temp_helper.compare(
            "golden",
            {"price": 100.1, "dv01": 150.5},
            tolerance=1e-6
        )


@pytest.mark.unit
class TestSampleTrades:
    """Test sample trade generator."""

    def test_sample_trades_count(self, sample_trades):
        """Test that sample trades has expected count."""
        assert len(sample_trades) == 10

    def test_sample_trades_structure(self, sample_trades):
        """Test that sample trades have expected structure."""
        for trade in sample_trades:
            assert 'id' in trade
            assert 'date' in trade
            assert 'product' in trade
            assert 'quantity' in trade
            assert 'price' in trade

    def test_sample_trades_deterministic(self, sample_trades, base_date):
        """Test that sample trades are deterministic (same seed)."""
        from tests.conftest import generate_random_trades

        # Generate twice with same seed
        trades1 = generate_random_trades(10, base_date)
        trades2 = generate_random_trades(10, base_date)

        assert trades1 == trades2
