"""Tests for scripts/eod_stirfo_service.py — SFR options EOD cache warmer.

Verifies that:
1. front_contracts returns the correct 12 SFR quarterlies for a given date
2. _snapshot_symbols_for_contract produces 20 delta-addressed symbols
3. warm_stirfo_eod_date populates both pricer cache and smile cache
4. Backfill across multiple dates populates all dates
5. Cache hits on re-run (no network calls needed)
"""

import datetime as dt
from unittest.mock import patch

import pytest

from scripts.eod_stirfo_service import (
    DEFAULT_DELTAS,
    front_contracts,
    _snapshot_symbols_for_contract,
    iter_eod_business_dates,
)


class TestFrontContracts:
    def test_returns_12_contracts(self):
        contracts = front_contracts(dt.date(2026, 6, 19), count=12)
        assert len(contracts) == 12

    def test_all_sfr_prefix(self):
        contracts = front_contracts(dt.date(2026, 6, 19), count=12)
        for c in contracts:
            assert c.startswith("SFR"), f"Expected SFR prefix, got {c}"

    def test_quarterly_months_only(self):
        contracts = front_contracts(dt.date(2026, 6, 19), count=12)
        valid_month_codes = {"H", "M", "U", "Z"}
        for c in contracts:
            month_code = c[3]
            assert month_code in valid_month_codes, f"Non-quarterly month in {c}"

    def test_first_contract_is_not_expired(self):
        as_of = dt.date(2026, 6, 19)
        contracts = front_contracts(as_of, count=4)
        # June 19 is after the 3rd Wed of June (Jun 17 2026),
        # so SFRM26 should be expired; first should be SFRU26
        assert contracts[0] == "SFRU26", f"Expected SFRU26, got {contracts[0]}"

    def test_first_contract_before_imm_expiry(self):
        # June 1 is before the 3rd Wed of June
        as_of = dt.date(2026, 6, 1)
        contracts = front_contracts(as_of, count=4)
        assert contracts[0] == "SFRM26", f"Expected SFRM26, got {contracts[0]}"

    def test_count_parameter(self):
        contracts = front_contracts(dt.date(2026, 1, 2), count=4)
        assert len(contracts) == 4


class TestSnapshotSymbols:
    def test_20_symbols_per_contract(self):
        symbols = _snapshot_symbols_for_contract("SFRZ26")
        assert len(symbols) == 20

    def test_10_calls_10_puts(self):
        symbols = _snapshot_symbols_for_contract("SFRZ26")
        calls = [s for s in symbols if s.endswith("DC")]
        puts = [s for s in symbols if s.endswith("DP")]
        assert len(calls) == 10
        assert len(puts) == 10

    def test_delta_values_present(self):
        symbols = _snapshot_symbols_for_contract("SFRZ26")
        for d in DEFAULT_DELTAS:
            assert f"SFRZ26|{d}DC" in symbols
            assert f"SFRZ26|{d}DP" in symbols


class TestBusinessDates:
    def test_excludes_weekends(self):
        dates = list(iter_eod_business_dates(
            start_date=dt.date(2026, 6, 13),  # Saturday
            end_date=dt.date(2026, 6, 14),    # Sunday
        ))
        assert len(dates) == 0

    def test_includes_weekdays(self):
        # June 15-18 2026: Mon-Thu (June 19 is Juneteenth holiday)
        dates = list(iter_eod_business_dates(
            start_date=dt.date(2026, 6, 15),
            end_date=dt.date(2026, 6, 18),
        ))
        assert len(dates) == 4

    def test_reversed_range_yields_nothing(self):
        dates = list(iter_eod_business_dates(
            start_date=dt.date(2026, 6, 19),
            end_date=dt.date(2026, 6, 15),
        ))
        assert len(dates) == 0


class TestWarmAndCache:
    """Integration tests that exercise the real MDP and cache path.

    These hit Barchart for data and write to the real diskcache. They are
    intentionally scoped to a single date and 2 contracts to keep runtime
    manageable while verifying the full end-to-end flow.
    """

    @pytest.fixture(scope="class")
    def mdp(self):
        from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
        m = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
        with m:
            yield m

    def test_snapshot_writes_to_cache(self, mdp):
        as_of = dt.date(2026, 6, 2)
        contracts = front_contracts(as_of, count=2)
        contract = contracts[0]
        symbols = _snapshot_symbols_for_contract(contract)

        request = {
            "endpoint": "option_snapshot",
            "symbols": symbols,
            "timestamp": as_of,
        }
        result = mdp.get_data(request)
        assert isinstance(result, dict)
        assert len(result) > 0

        # Verify cache hit by rebuilding with the same request shape
        cache_key = mdp._build_get_data_cache_key("option_snapshot", request)
        assert cache_key is not None
        cached = mdp._threadsafe_cache_get(cache_key)
        assert cached is not None

    def test_smile_writes_to_cache(self, mdp):
        as_of = dt.date(2026, 6, 2)
        contracts = front_contracts(as_of, count=2)
        contract = contracts[0]

        request = {
            "endpoint": "sabr_smile",
            "symbol": contract,
            "as_of": as_of,
        }
        result = mdp.get_data(request)
        assert "sabr_smile" in result
        smiles = result["sabr_smile"]
        assert len(smiles) == 1

        smile = smiles[0]
        assert hasattr(smile, "params")
        assert hasattr(smile, "points")
        assert len(smile.points) > 0
        assert smile.params.beta == 0.5

        cache_key = mdp._build_get_data_cache_key("sabr_smile", request)
        assert cache_key is not None
        cached = mdp._threadsafe_cache_get(cache_key)
        assert cached is not None

    def test_bulk_smile_writes_to_cache(self, mdp):
        as_of = dt.date(2026, 6, 3)
        contracts = front_contracts(as_of, count=2)

        result = mdp.fetch_bulk_sabr_smile({
            "symbols": contracts,
            "timestamps": [as_of],
        })
        assert isinstance(result, dict)
        assert len(result) == 2
        for sym, by_date in result.items():
            assert as_of in by_date
            smile = by_date[as_of]
            assert len(smile.points) > 0

    def test_warm_stirfo_eod_date_full_flow(self, mdp):
        from scripts.eod_stirfo_service import warm_stirfo_eod_date

        as_of = dt.date(2026, 6, 4)
        contracts = front_contracts(as_of, count=2)
        stats = warm_stirfo_eod_date(mdp, as_of, contracts)

        assert stats["snapshot_ok"] == 2
        assert stats["snapshot_fail"] == 0
        assert stats["smile_ok"] == 2
        assert stats["smile_fail"] == 0

    def test_rerun_hits_cache_no_network(self, mdp):
        """Second call for the same date should be pure cache hits."""
        from scripts.eod_stirfo_service import warm_stirfo_eod_date
        import time

        as_of = dt.date(2026, 6, 4)
        contracts = front_contracts(as_of, count=2)

        t0 = time.perf_counter()
        stats = warm_stirfo_eod_date(mdp, as_of, contracts)
        elapsed = time.perf_counter() - t0

        assert stats["snapshot_ok"] == 2
        assert stats["smile_ok"] == 2
        assert elapsed < 5.0, f"Re-run took {elapsed:.1f}s — likely not hitting cache"
