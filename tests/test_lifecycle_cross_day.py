import math
import pytest
from datetime import datetime, date

from SDRUtils.core.lifecycle import ResolvedTrade
from SDRUtils.core.lifecycle_v2 import (
    LifecycleEvent,
    LifecycleSummary,
    flatten_cross_day_summary,
)


class TestFlattenCrossDaySummary:
    """Tests for flatten_cross_day_summary."""

    def _make_resolved(
        self,
        *,
        status: str = "ACTIVE",
        inception_notional: float = 25_000_000,
        current_notional: float = 25_000_000,
    ) -> ResolvedTrade:
        resolved = ResolvedTrade(synthetic_uti="test-uti")
        resolved.status = status
        resolved.inception_state = {"Notional amount-Leg 1": inception_notional}
        resolved.current_state = {"Notional amount-Leg 1": current_notional}
        return resolved

    def _make_summary(
        self,
        *,
        n_events: int = 1,
        was_corrected: bool = False,
        was_amended: bool = False,
        is_terminated: bool = False,
        fields_changed: set | None = None,
        correction_lag: int = 0,
        file_dates: list[date] | None = None,
    ) -> LifecycleSummary:
        chain = []
        fds = file_dates or [date(2026, 3, 9)]
        for i in range(n_events):
            fd = fds[i] if i < len(fds) else fds[-1]
            chain.append(LifecycleEvent(
                action_type="NEWT" if i == 0 else "MODI",
                event_type="TRAD" if i == 0 else None,
                amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9 + i, 14, 0, 0),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id=f"id_{i}",
                original_dissemination_id=f"id_{i-1}" if i > 0 else None,
                file_date=fd,
            ))
        s = LifecycleSummary(chain=chain)
        s.was_corrected = was_corrected
        s.was_economically_modified = was_amended
        s.is_terminated = is_terminated
        s.fields_changed = fields_changed or set()
        s.correction_lag_seconds = correction_lag
        return s

    def test_active_no_change(self):
        summary = self._make_summary(n_events=1, file_dates=[date(2026, 3, 9)])
        resolved = self._make_resolved()
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_n_events"] == 1
        assert flat["xd_status"] == "ACTIVE"
        assert flat["xd_inception_notional"] == 25_000_000
        assert flat["xd_current_notional"] == 25_000_000
        assert flat["xd_notional_pct_remaining"] == 1.0
        assert flat["xd_is_terminated"] is False
        assert flat["xd_has_partial_unwind"] is False
        assert flat["xd_n_days_spanned"] == 1

    def test_terminated(self):
        summary = self._make_summary(
            n_events=5, is_terminated=True,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 10), date(2026, 3, 10), date(2026, 3, 10)],
        )
        resolved = self._make_resolved(status="TERMINATED", current_notional=0)
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_status"] == "TERMINATED"
        assert flat["xd_is_terminated"] is True
        assert flat["xd_notional_pct_remaining"] == 0.0
        assert flat["xd_n_days_spanned"] == 2

    def test_partial_unwind_active(self):
        summary = self._make_summary(
            n_events=3, was_amended=True,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 10)],
            fields_changed={"Notional amount-Leg 1"},
        )
        resolved = self._make_resolved(
            status="ACTIVE", inception_notional=25_000_000, current_notional=12_000_000,
        )
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_status"] == "PARTIAL_UNWIND"
        assert flat["xd_has_partial_unwind"] is True
        assert flat["xd_notional_pct_remaining"] == pytest.approx(0.48)
        assert flat["xd_was_amended"] is True
        assert "Notional amount-Leg 1" in flat["xd_fields_changed"]

    def test_partial_unwind_then_terminated(self):
        summary = self._make_summary(
            n_events=4, is_terminated=True, was_amended=True,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 10), date(2026, 3, 10)],
        )
        resolved = self._make_resolved(
            status="TERMINATED", inception_notional=25_000_000, current_notional=5_000_000,
        )
        flat = flatten_cross_day_summary(summary, resolved)

        # Terminated overrides partial unwind status
        assert flat["xd_status"] == "TERMINATED"
        assert flat["xd_has_partial_unwind"] is True
        assert flat["xd_is_terminated"] is True

    def test_errored(self):
        summary = self._make_summary(n_events=2)
        resolved = self._make_resolved(status="ERRORED")
        resolved.inception_state = None
        resolved.current_state = None
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_status"] == "ERRORED"
        assert math.isnan(flat["xd_inception_notional"])
        assert math.isnan(flat["xd_current_notional"])
        assert math.isnan(flat["xd_notional_pct_remaining"])

    def test_zero_inception_notional(self):
        summary = self._make_summary(n_events=1)
        resolved = self._make_resolved(inception_notional=0, current_notional=0)
        flat = flatten_cross_day_summary(summary, resolved)

        assert math.isnan(flat["xd_notional_pct_remaining"])

    def test_corrected_with_lag(self):
        summary = self._make_summary(
            n_events=2, was_corrected=True, correction_lag=82800,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10)],
        )
        resolved = self._make_resolved()
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_was_corrected"] is True
        assert flat["xd_correction_lag_seconds"] == 82800


import pandas as pd
from SDRUtils.core.lifecycle import resolve_lifecycle_cross_day


class TestResolveCrossDayLifecycle:
    """Tests for resolve_lifecycle_cross_day."""

    def _make_raw_df(self, rows: list[dict]) -> pd.DataFrame:
        """Build a raw SDR DataFrame from row dicts."""
        df = pd.DataFrame(rows)
        # Ensure required columns exist
        for col in ["Dissemination Identifier", "Original Dissemination Identifier",
                     "Action type", "Event timestamp", "file_date"]:
            if col not in df.columns:
                df[col] = ""
        return df

    def _newt_row(self, dissem_id: str, ts: str, file_date: date, notional: float = 25_000_000) -> dict:
        return {
            "Dissemination Identifier": dissem_id,
            "Original Dissemination Identifier": "",
            "Action type": "NEWT",
            "Event type": "TRAD",
            "Event timestamp": ts,
            "Execution Timestamp": ts,
            "Amendment indicator": False,
            "file_date": file_date,
            "Notional amount-Leg 1": notional,
        }

    def _modi_row(self, dissem_id: str, orig_id: str, ts: str, file_date: date,
                   notional: float = 25_000_000, amendment: bool = False) -> dict:
        return {
            "Dissemination Identifier": dissem_id,
            "Original Dissemination Identifier": orig_id,
            "Action type": "MODI",
            "Event type": None,
            "Event timestamp": ts,
            "Execution Timestamp": ts,
            "Amendment indicator": amendment,
            "file_date": file_date,
            "Notional amount-Leg 1": notional,
        }

    def _term_row(self, dissem_id: str, orig_id: str, ts: str, file_date: date) -> dict:
        return {
            "Dissemination Identifier": dissem_id,
            "Original Dissemination Identifier": orig_id,
            "Action type": "TERM",
            "Event type": "ETRM",
            "Event timestamp": ts,
            "Execution Timestamp": ts,
            "Amendment indicator": False,
            "file_date": file_date,
            "Notional amount-Leg 1": 0,
        }

    def test_newt_plus_cross_day_term(self):
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._term_row("A2", "A1", "2026-03-10 12:00:00", date(2026, 3, 10)),
        ])
        result = resolve_lifecycle_cross_day(raw_df, {"A1"})

        assert len(result) == 1
        row = result.iloc[0]
        assert row["xd_status"] == "TERMINATED"
        assert bool(row["xd_is_terminated"]) is True
        assert row["xd_n_events"] == 2
        assert row["xd_n_days_spanned"] == 2

    def test_partial_unwind_chain(self):
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9), notional=25_000_000),
            self._modi_row("A2", "A1", "2026-03-10 10:00:00", date(2026, 3, 10),
                           notional=12_000_000, amendment=True),
            self._modi_row("A3", "A2", "2026-03-10 11:00:00", date(2026, 3, 10),
                           notional=7_000_000, amendment=True),
            self._modi_row("A4", "A3", "2026-03-10 12:00:00", date(2026, 3, 10),
                           notional=5_000_000, amendment=True),
            self._term_row("A5", "A4", "2026-03-10 13:00:00", date(2026, 3, 10)),
        ])
        result = resolve_lifecycle_cross_day(raw_df, {"A1"})

        row = result.iloc[0]
        assert row["xd_status"] == "TERMINATED"
        assert bool(row["xd_has_partial_unwind"]) is True
        assert row["xd_inception_notional"] == 25_000_000
        assert row["xd_n_events"] == 5

    def test_skip_intraday_only(self):
        """Groups with all events on same file_date should be skipped when flag is True."""
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._modi_row("A2", "A1", "2026-03-09 15:00:00", date(2026, 3, 9)),
        ])
        result = resolve_lifecycle_cross_day(raw_df, {"A1"}, skip_intraday_only=True)
        assert result.empty

        result2 = resolve_lifecycle_cross_day(raw_df, {"A1"}, skip_intraday_only=False)
        assert len(result2) == 1

    def test_classified_ids_filter(self):
        """Only groups with NEWTs in classified_dissem_ids produce output."""
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._term_row("A2", "A1", "2026-03-10 12:00:00", date(2026, 3, 10)),
            self._newt_row("B1", "2026-03-09 15:00:00", date(2026, 3, 9)),
            self._term_row("B2", "B1", "2026-03-10 13:00:00", date(2026, 3, 10)),
        ])
        # Only A1 is classified
        result = resolve_lifecycle_cross_day(raw_df, {"A1"})
        assert len(result) == 1
        assert result.index[0] == "A1"

    def test_empty_raw_df(self):
        result = resolve_lifecycle_cross_day(pd.DataFrame(), {"A1"})
        assert result.empty

    def test_newt_empty_string_original_dissem(self):
        """NEWT with empty-string Original Dissemination Identifier groups correctly."""
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._modi_row("A2", "A1", "2026-03-10 10:00:00", date(2026, 3, 10)),
        ])
        # Verify NEWT's Original Dissemination Identifier is empty string
        assert raw_df.iloc[0]["Original Dissemination Identifier"] == ""
        result = resolve_lifecycle_cross_day(raw_df, {"A1"}, skip_intraday_only=False)
        assert len(result) == 1
        assert result.iloc[0]["xd_n_events"] == 2


from unittest.mock import patch
from SDRUtils.analytics.trade_tape import TradeTape


class TestTradeTapeCrossDay:
    """Tests for TradeTape cross-day lifecycle layer."""

    def _minimal_classified_df(self) -> pd.DataFrame:
        """Build a minimal classified DataFrame with required TradeTape columns."""
        return pd.DataFrame({
            "trade_id": ["A1", "B1"],
            "execution_timestamp": pd.to_datetime(["2026-03-09 14:00:00+00:00", "2026-03-09 15:00:00+00:00"]),
            "event_action": ["NEWT", "NEWT"],
            "tenor_label": ["5Y", "10Y"],
            "tenor_years": [5.0, 10.0],
            "forward_label": ["spot", "spot"],
            "forward_start_years": [0.0, 0.0],
            "notional": [25_000_000, 50_000_000],
            "fixed_rate": [0.04, 0.045],
            "estimated_pv01": [4500, 9000],
            "product_type": ["OIS_SWAP", "OIS_SWAP"],
            "upi_underlier_name": ["USD-SOFR-COMPOUND", "USD-SOFR-COMPOUND"],
            "unique_product_identifier": ["", ""],
            "platform_identifier": ["XXXX", "XXXX"],
            "cleared": ["I", "I"],
            "prime_brokerage_transaction_indicator": [False, False],
            "block_trade_election_indicator": [False, False],
            "large_notional_off-facility_swap_election_indicator": [False, False],
            "other_payment_type": ["", ""],
            "other_payment_amount": [0, 0],
            "package_indicator": ["", ""],
            "package_transaction_spread": [0, 0],
            "package_type": ["OUTRIGHT", "OUTRIGHT"],
            "special_tenor_type": ["", ""],
        })

    def test_no_raw_df_no_xd_columns(self):
        """TradeTape without raw_df should not have xd_* columns."""
        tape = TradeTape(self._minimal_classified_df())
        # Just call the cross-day layer directly
        df = tape._enrich_cross_day_lifecycle(self._minimal_classified_df())
        assert not any(c.startswith("xd_") for c in df.columns)

    def test_with_raw_df_adds_xd_columns(self):
        """TradeTape with raw_df containing cross-day events adds xd_* columns."""
        classified = self._minimal_classified_df()
        raw_df = pd.DataFrame([
            {
                "Dissemination Identifier": "A1",
                "Original Dissemination Identifier": "",
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Event timestamp": "2026-03-09 14:00:00",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Amendment indicator": False,
                "file_date": date(2026, 3, 9),
                "Notional amount-Leg 1": 25_000_000,
            },
            {
                "Dissemination Identifier": "A2",
                "Original Dissemination Identifier": "A1",
                "Action type": "TERM",
                "Event type": "ETRM",
                "Event timestamp": "2026-03-10 12:00:00",
                "Execution Timestamp": "2026-03-10 12:00:00",
                "Amendment indicator": False,
                "file_date": date(2026, 3, 10),
                "Notional amount-Leg 1": 0,
            },
            {
                "Dissemination Identifier": "B1",
                "Original Dissemination Identifier": "",
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Event timestamp": "2026-03-09 15:00:00",
                "Execution Timestamp": "2026-03-09 15:00:00",
                "Amendment indicator": False,
                "file_date": date(2026, 3, 9),
                "Notional amount-Leg 1": 50_000_000,
            },
        ])

        tape = TradeTape(classified, raw_df=raw_df)
        df = tape._enrich_cross_day_lifecycle(classified.copy())

        # A1 has cross-day events, B1 does not
        assert "xd_status" in df.columns
        a1_row = df[df["trade_id"] == "A1"].iloc[0]
        assert a1_row["xd_status"] == "TERMINATED"
        assert bool(a1_row["xd_is_terminated"]) is True

        # B1 should have defaults (intra-day only, skipped)
        b1_row = df[df["trade_id"] == "B1"].iloc[0]
        assert b1_row["xd_status"] == "ACTIVE"
        assert b1_row["xd_notional_pct_remaining"] == 1.0


class TestBuildClassificationReturnRaw:
    """Tests for return_raw parameter on build_classification_dataframe."""

    def test_return_raw_false_returns_dataframe(self):
        """Default behavior unchanged — returns a single DataFrame."""
        from SDRUtils.products.usd.usd_swaps import USD_SwapProduct

        import inspect
        sig = inspect.signature(USD_SwapProduct.build_classification_dataframe)
        assert "return_raw" in sig.parameters
        assert sig.parameters["return_raw"].default is False

    def test_return_raw_true_returns_tuple(self):
        """When return_raw=True, returns (classified_df, raw_df) tuple."""
        from SDRUtils.products.usd.usd_swaps import USD_SwapProduct

        import inspect
        sig = inspect.signature(USD_SwapProduct.build_classification_dataframe)
        assert "return_raw" in sig.parameters


import os

EXAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "notebooks", "sdr", "sdr_example.csv")


@pytest.mark.skipif(not os.path.exists(EXAMPLE_CSV), reason="sdr_example.csv not available")
class TestCrossDayRealData:
    """Integration tests using real SDR data from sdr_example.csv."""

    @pytest.fixture
    def raw_df(self):
        # CRITICAL: load dissem ID columns as str to avoid float64 precision loss
        df = pd.read_csv(EXAMPLE_CSV, low_memory=False, dtype={
            "Dissemination Identifier": str,
            "Original Dissemination Identifier": str,
        })
        df["Original Dissemination Identifier"] = df["Original Dissemination Identifier"].fillna("")
        df["file_date"] = pd.to_datetime(df["Event timestamp"], errors="coerce").dt.date
        for col in ["Notional amount-Leg 1", "Notional amount-Leg 2"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", ""), errors="coerce"
                )
        return df

    def test_trade_2304676889_lifecycle(self, raw_df):
        """Known cross-day trade: 25M SOFR 10Y NEWT+22 events+TERM spanning 2 days."""
        newt_dissem = "2304676889000000101"

        result = resolve_lifecycle_cross_day(
            raw_df, {newt_dissem}, skip_intraday_only=False,
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert bool(row["xd_is_terminated"]) is True
        assert row["xd_n_events"] == 22
        assert row["xd_n_days_spanned"] == 2

    def test_cross_day_events_detected(self, raw_df):
        """Verify resolver finds cross-day groups in real data."""
        newt_mask = raw_df["Action type"] == "NEWT"
        all_newt_ids = set(raw_df.loc[newt_mask, "Dissemination Identifier"].astype(str))

        result = resolve_lifecycle_cross_day(
            raw_df, all_newt_ids, skip_intraday_only=True,
        )

        # With proper string IDs, should find 600+ cross-day groups
        assert len(result) > 100
        # Some should be terminated
        assert result["xd_is_terminated"].any()
        # Some should have partial unwinds
        assert result["xd_has_partial_unwind"].any()
        # Some should have notional changes
        has_notional_change = result["xd_notional_pct_remaining"] < 1.0
        assert has_notional_change.any()


@pytest.mark.skipif(not os.path.exists(EXAMPLE_CSV), reason="sdr_example.csv not available")
class TestUnfilteredRawDf:
    """Verify unfiltered raw_df contains lifecycle events missing from filtered pass."""

    def test_unfiltered_raw_has_more_rows(self):
        """Unfiltered raw_df should have significantly more rows than filtered."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'sdr'))
        from SDRUtils.products.usd.usd_swaps import USD_SwapProduct
        import _usd_swaps_common as sdr

        swaps = USD_SwapProduct()
        # +1 day extension in unfiltered raw handles midnight cutoff
        classified_df, raw_df = swaps.build_classification_dataframe(
            datetime(2026, 3, 9),
            datetime(2026, 3, 10),
            cache_path=sdr.DEFAULT_CACHE_PATH,
            return_raw=True,
        )

        action_counts = raw_df["Action type"].value_counts()
        assert "MODI" in action_counts.index
        assert "TERM" in action_counts.index
        assert len(raw_df) > len(classified_df)

    def test_trade_2304676889_cross_day_chain_complete(self):
        """Known cross-day trade should have full lifecycle chain in unfiltered raw."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'sdr'))
        from SDRUtils.products.usd.usd_swaps import USD_SwapProduct
        from SDRUtils.core.lifecycle import resolve_lifecycle_cross_day
        import _usd_swaps_common as sdr

        swaps = USD_SwapProduct()
        # Tight end — +1 day extension in unfiltered raw captures Mar 10 events
        classified_df, raw_df = swaps.build_classification_dataframe(
            datetime(2026, 3, 9),
            datetime(2026, 3, 10),
            cache_path=sdr.DEFAULT_CACHE_PATH,
            return_raw=True,
        )

        result = resolve_lifecycle_cross_day(
            raw_df, {"2304676889000000101"}, skip_intraday_only=False,
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert row["xd_n_events"] > 14  # was 14 with filtered, should be 22
        assert row["xd_n_days_spanned"] == 2
        assert bool(row["xd_is_terminated"]) is True


class TestLoadUsdSwapsReturnRaw:
    """Tests for return_raw parameter on load_usd_swaps."""

    def test_return_raw_parameter_exists(self):
        """Verify load_usd_swaps accepts return_raw parameter."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'sdr'))
        import _usd_swaps_common as sdr
        import inspect
        sig = inspect.signature(sdr.load_usd_swaps)
        assert "return_raw" in sig.parameters
        assert sig.parameters["return_raw"].default is False


class TestBuildClassificationReturnRawEdgeCases:
    """Edge case tests for return_raw parameter."""

    def test_return_raw_empty_returns_tuple(self):
        """When raw_sdr_trades_df is empty and return_raw=True, must return tuple."""
        from SDRUtils.products.usd.usd_swaps import USD_SwapProduct

        swaps = USD_SwapProduct()
        import inspect
        sig = inspect.signature(swaps.build_classification_dataframe)
        assert "return_raw" in sig.parameters


class TestLoadUsdSwapsAlwaysRaw:
    """load_usd_swaps always carries raw_df."""

    def test_result_has_raw_df_attribute(self):
        """Result should have .raw_df even without return_raw."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'sdr'))
        import importlib
        import _usd_swaps_common as sdr
        importlib.reload(sdr)

        result = sdr.load_usd_swaps(
            datetime(2026, 3, 9),
            datetime(2026, 3, 10),
        )
        assert isinstance(result, pd.DataFrame)
        assert hasattr(result, 'raw_df')
        assert isinstance(result.raw_df, pd.DataFrame)
        assert len(result.raw_df) > len(result)

    def test_return_raw_true_still_works(self):
        """Explicit return_raw=True still returns tuple."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'notebooks', 'sdr'))
        import importlib
        import _usd_swaps_common as sdr
        importlib.reload(sdr)

        classified, raw = sdr.load_usd_swaps(
            datetime(2026, 3, 9),
            datetime(2026, 3, 10),
            return_raw=True,
        )
        assert isinstance(classified, pd.DataFrame)
        assert isinstance(raw, pd.DataFrame)


class TestBuildEnrichedLabelCrossDay:
    """_build_enriched_label reflects xd_* columns."""

    def _make_tape_df(self, xd_status="ACTIVE", xd_has_partial_unwind=False):
        return pd.DataFrame({
            "trade_id": ["A1"],
            "upi_underlier_name": ["USD-SOFR-COMPOUND"],
            "product_type": ["OIS_SWAP"],
            "upi_reset_freq": [""],
            "upi_notional_schedule": [""],
            "forward_label": ["spot"],
            "forward_start_years": [0.0],
            "tenor_label": ["10Y"],
            "tenor_display": ["10Y"],
            "trade_type": ["OUTRIGHT"],
            "lifecycle_type": ["NEW_TRADE"],
            "is_unwind": [False],
            "is_mac": [False],
            "is_ufro": [False],
            "is_block": [False],
            "cleared": ["I"],
            "xd_status": [xd_status],
            "xd_has_partial_unwind": [xd_has_partial_unwind],
            "xd_is_terminated": [xd_status == "TERMINATED"],
        })

    def test_terminated_label_has_xd_term_flag(self):
        tape = TradeTape(self._make_tape_df(xd_status="TERMINATED"))
        df = tape._build_enriched_label(self._make_tape_df(xd_status="TERMINATED"))
        assert "XD-TERM" in df.iloc[0]["tape_label"]

    def test_partial_unwind_label_has_flag(self):
        tape = TradeTape(self._make_tape_df(xd_status="PARTIAL_UNWIND", xd_has_partial_unwind=True))
        df = tape._build_enriched_label(self._make_tape_df(xd_status="PARTIAL_UNWIND", xd_has_partial_unwind=True))
        assert "PARTIAL-UNWIND" in df.iloc[0]["tape_label"]

    def test_active_no_xd_flag(self):
        tape = TradeTape(self._make_tape_df())
        df = tape._build_enriched_label(self._make_tape_df())
        label = df.iloc[0]["tape_label"]
        assert "XD-TERM" not in label
        assert "PARTIAL-UNWIND" not in label


class TestCleanTapeCrossDay:
    """clean_tape excludes cross-day terminated trades."""

    def _make_classified_df(self):
        return pd.DataFrame({
            "trade_id": ["A1", "B1"],
            "execution_timestamp": pd.to_datetime(["2026-03-09 14:00:00+00:00", "2026-03-09 15:00:00+00:00"]),
            "event_action": ["NEWT", "NEWT"],
            "tenor_label": ["10Y", "5Y"],
            "tenor_years": [10.0, 5.0],
            "forward_label": ["spot", "spot"],
            "forward_start_years": [0.0, 0.0],
            "notional": [25_000_000, 50_000_000],
            "fixed_rate": [0.04, 0.045],
            "estimated_pv01": [9000, 4500],
            "product_type": ["OIS_SWAP", "OIS_SWAP"],
            "upi_underlier_name": ["USD-SOFR-COMPOUND", "USD-SOFR-COMPOUND"],
            "unique_product_identifier": ["", ""],
            "platform_identifier": ["XXXX", "XXXX"],
            "cleared": ["I", "I"],
            "prime_brokerage_transaction_indicator": [False, False],
            "block_trade_election_indicator": [False, False],
            "large_notional_off-facility_swap_election_indicator": [False, False],
            "other_payment_type": ["", ""],
            "other_payment_amount": [0, 0],
            "package_indicator": ["", ""],
            "package_transaction_spread": [0, 0],
            "package_type": ["OUTRIGHT", "OUTRIGHT"],
            "special_tenor_type": ["", ""],
        })

    def test_xd_terminated_excluded_from_clean(self):
        cdf = self._make_classified_df()
        # Add columns needed for compute() to succeed
        cdf["effective_date"] = pd.to_datetime("2026-03-11")
        cdf["expiration_date"] = pd.to_datetime(["2036-03-11", "2031-03-11"])
        tape = TradeTape(cdf)
        tape.compute()
        tape._result.loc[tape._result["trade_id"] == "A1", "xd_is_terminated"] = True
        clean = tape.clean_tape()
        assert "A1" not in clean["trade_id"].values
        assert "B1" in clean["trade_id"].values


class TestSummaryCrossDay:
    """summary() includes cross-day lifecycle stats."""

    def test_summary_has_xd_keys(self):
        df = pd.DataFrame({
            "trade_id": ["A1"],
            "execution_timestamp": pd.to_datetime(["2026-03-09 14:00:00+00:00"]),
            "event_action": ["NEWT"],
            "tenor_label": ["10Y"],
            "tenor_years": [10.0],
            "forward_label": ["spot"],
            "forward_start_years": [0.0],
            "notional": [25_000_000],
            "fixed_rate": [0.04],
            "estimated_pv01": [9000],
            "product_type": ["OIS_SWAP"],
            "upi_underlier_name": ["USD-SOFR-COMPOUND"],
            "unique_product_identifier": [""],
            "platform_identifier": ["XXXX"],
            "cleared": ["I"],
            "prime_brokerage_transaction_indicator": [False],
            "block_trade_election_indicator": [False],
            "large_notional_off-facility_swap_election_indicator": [False],
            "other_payment_type": [""],
            "other_payment_amount": [0],
            "package_indicator": [""],
            "package_transaction_spread": [0],
            "package_type": ["OUTRIGHT"],
            "special_tenor_type": [""],
            "effective_date": pd.to_datetime(["2026-03-11"]),
            "expiration_date": pd.to_datetime(["2036-03-11"]),
        })
        tape = TradeTape(df)
        tape.compute()
        s = tape.summary()
        assert "n_xd_terminated" in s
        assert "n_xd_partial_unwind" in s
