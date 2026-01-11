"""
Tests for SDR trade event resolution and phantom trade prevention.

These tests verify that the lifecycle resolution correctly handles:
1. Semantic anchor selection (prefer NEWT by timestamp)
2. Amendment indicator handling for MODI actions
3. Lifecycle replay with different action types
4. ResolvedTrade metadata tracking
5. Phantom trade prevention (no double counting)
"""

import pandas as pd
import pytest
from datetime import datetime, date

from SDRUtils.core.graph_resolver import (
    assign_synthetic_uti,
    build_synthetic_uti_mapping,
    _normalize_identifier,
    _select_semantic_anchor,
)
from SDRUtils.core.lifecycle import (
    replay_lifecycle,
    replay_lifecycle_full,
    ResolvedTrade,
    ECONOMICS_FIELDS,
    _update_state,
    _is_null_value,
)


class TestNormalizeIdentifier:
    """Tests for identifier normalization."""

    def test_normalize_none(self):
        assert _normalize_identifier(None) is None

    def test_normalize_nan(self):
        import numpy as np
        assert _normalize_identifier(np.nan) is None
        assert _normalize_identifier(float("nan")) is None

    def test_normalize_empty_string(self):
        assert _normalize_identifier("") is None
        assert _normalize_identifier("   ") is None

    def test_normalize_valid_string(self):
        assert _normalize_identifier("123456") == "123456"
        assert _normalize_identifier("  123456  ") == "123456"

    def test_normalize_numeric(self):
        assert _normalize_identifier(123456) == "123456"


class TestSemanticAnchor:
    """Tests for semantic anchor selection."""

    def test_prefers_newt_by_timestamp(self):
        """Should prefer the earliest NEWT by timestamp."""
        component = {"id1", "id2", "id3"}
        id_to_action = {"id1": "MODI", "id2": "NEWT", "id3": "NEWT"}
        id_to_timestamp = {
            "id1": pd.Timestamp("2026-01-07 21:00:00"),
            "id2": pd.Timestamp("2026-01-07 21:51:19"),  # Earlier NEWT
            "id3": pd.Timestamp("2026-01-07 22:00:00"),  # Later NEWT
        }
        anchor = _select_semantic_anchor(component, id_to_action, id_to_timestamp)
        assert anchor == "id2"

    def test_falls_back_to_earliest_timestamp_without_newt(self):
        """Should use earliest timestamp if no NEWT in component."""
        component = {"id1", "id2", "id3"}
        id_to_action = {"id1": "MODI", "id2": "CORR", "id3": "MODI"}
        id_to_timestamp = {
            "id1": pd.Timestamp("2026-01-07 22:00:00"),
            "id2": pd.Timestamp("2026-01-07 21:00:00"),  # Earliest
            "id3": pd.Timestamp("2026-01-07 23:00:00"),
        }
        anchor = _select_semantic_anchor(component, id_to_action, id_to_timestamp)
        assert anchor == "id2"

    def test_falls_back_to_min_without_timestamps(self):
        """Should use lexicographic min if no timestamps available."""
        component = {"id3", "id1", "id2"}
        id_to_action = {}
        id_to_timestamp = {}
        anchor = _select_semantic_anchor(component, id_to_action, id_to_timestamp)
        assert anchor == "id1"


class TestBuildSyntheticUtiMapping:
    """Tests for graph-based UTI clustering."""

    def test_clusters_related_messages(self):
        """Should cluster messages linked by Original Dissemination Identifier."""
        messages = pd.DataFrame({
            "Dissemination Identifier": ["NEWT1", "MODI1", "MODI2"],
            "Original Dissemination Identifier": ["", "NEWT1", "NEWT1"],
            "Action type": ["NEWT", "MODI", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
                pd.Timestamp("2026-01-07 23:00:00"),
            ],
        })
        mapping, components = build_synthetic_uti_mapping(messages)

        # All should map to NEWT1 (the NEWT anchor)
        assert mapping["NEWT1"] == "NEWT1"
        assert mapping["MODI1"] == "NEWT1"
        assert mapping["MODI2"] == "NEWT1"
        assert "NEWT1" in components
        assert set(components["NEWT1"]) == {"NEWT1", "MODI1", "MODI2"}

    def test_separate_components_for_unrelated_trades(self):
        """Should create separate components for unrelated trades."""
        messages = pd.DataFrame({
            "Dissemination Identifier": ["TRADE_A", "MODI_A", "TRADE_B", "MODI_B"],
            "Original Dissemination Identifier": ["", "TRADE_A", "", "TRADE_B"],
            "Action type": ["NEWT", "MODI", "NEWT", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
        })
        mapping, components = build_synthetic_uti_mapping(messages)

        assert mapping["TRADE_A"] == "TRADE_A"
        assert mapping["MODI_A"] == "TRADE_A"
        assert mapping["TRADE_B"] == "TRADE_B"
        assert mapping["MODI_B"] == "TRADE_B"
        assert len(components) == 2


class TestAssignSyntheticUti:
    """Tests for assigning synthetic UTIs to messages."""

    def test_assigns_synthetic_uti_column(self):
        """Should add Synthetic UTI column to DataFrame."""
        messages = pd.DataFrame({
            "Dissemination Identifier": ["NEWT1", "MODI1"],
            "Original Dissemination Identifier": ["", "NEWT1"],
            "Action type": ["NEWT", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
        })
        result = assign_synthetic_uti(messages)

        assert "Synthetic UTI" in result.columns
        assert result["Synthetic UTI"].iloc[0] == "NEWT1"
        assert result["Synthetic UTI"].iloc[1] == "NEWT1"

    def test_handles_orphan_records(self):
        """Should assign unique orphan IDs to messages without dissemination ID."""
        messages = pd.DataFrame({
            "Dissemination Identifier": [None, "TRADE1"],
            "Original Dissemination Identifier": ["", ""],
            "Action type": ["NEWT", "NEWT"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
        })
        result = assign_synthetic_uti(messages)

        assert result["Synthetic UTI"].iloc[0].startswith("orphan::")
        assert result["Synthetic UTI"].iloc[1] == "TRADE1"


class TestUpdateState:
    """Tests for state update logic."""

    def test_overwrite_replaces_values(self):
        """Overwrite mode should replace existing values."""
        state = {"field1": "old", "field2": "old"}
        row = {"field1": "new", "field2": "new"}
        result = _update_state(state, row, overwrite=True)
        assert result["field1"] == "new"
        assert result["field2"] == "new"

    def test_non_overwrite_fills_nulls_only(self):
        """Non-overwrite mode should only fill null values."""
        state = {"field1": "existing", "field2": None}
        row = {"field1": "new", "field2": "new", "field3": "new"}
        result = _update_state(state, row, overwrite=False)
        assert result["field1"] == "existing"  # Not overwritten
        assert result["field2"] == "new"  # Filled
        assert result["field3"] == "new"  # Added

    def test_economics_only_mode(self):
        """Economics-only mode should only overwrite economics fields."""
        state = {
            "Notional amount-Leg 1": "100",
            "Fixed rate-Leg 1": 0.04,
            "Platform identifier": "ISWV",
        }
        row = {
            "Notional amount-Leg 1": "200",
            "Fixed rate-Leg 1": 0.05,
            "Platform identifier": "NEW_PLATFORM",
        }
        result = _update_state(state, row, overwrite=True, economics_only=True)
        assert result["Notional amount-Leg 1"] == "200"  # Overwritten (economics)
        assert result["Fixed rate-Leg 1"] == 0.05  # Overwritten (economics)
        assert result["Platform identifier"] == "ISWV"  # Not overwritten


class TestIsNullValue:
    """Tests for null value detection."""

    def test_detects_none(self):
        assert _is_null_value(None) is True

    def test_detects_nan(self):
        import numpy as np
        assert _is_null_value(np.nan) is True
        assert _is_null_value(float("nan")) is True

    def test_detects_empty_string(self):
        assert _is_null_value("") is True
        assert _is_null_value("   ") is True

    def test_valid_values(self):
        assert _is_null_value(0) is False
        assert _is_null_value("value") is False
        assert _is_null_value(0.0) is False


class TestReplayLifecycle:
    """Tests for lifecycle replay logic."""

    def test_newt_initializes_state(self):
        """NEWT should initialize trade state."""
        messages = pd.DataFrame({
            "Action type": ["NEWT"],
            "Event timestamp": [pd.Timestamp("2026-01-07 21:00:00")],
            "Notional amount-Leg 1": ["100,000,000"],
            "Fixed rate-Leg 1": [0.04],
        })
        state, history = replay_lifecycle(messages)

        assert state is not None
        assert state["Active"] is True
        assert state["Notional amount-Leg 1"] == "100,000,000"
        assert state["Fixed rate-Leg 1"] == 0.04

    def test_modi_fills_nulls(self):
        """MODI should fill null values without overwriting."""
        messages = pd.DataFrame({
            "Action type": ["NEWT", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, False],
            "Notional amount-Leg 1": ["100,000,000", "200,000,000"],
            "Platform identifier": [None, "ISWV"],
        })
        state, history = replay_lifecycle(messages)

        # Notional should NOT be overwritten (Amendment indicator=False)
        assert state["Notional amount-Leg 1"] == "100,000,000"
        # Platform should be filled (was null)
        assert state["Platform identifier"] == "ISWV"

    def test_modi_with_amendment_indicator_overwrites_economics(self):
        """MODI with Amendment indicator=True should overwrite economics."""
        messages = pd.DataFrame({
            "Action type": ["NEWT", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, True],
            "Notional amount-Leg 1": ["100,000,000", "200,000,000"],
            "Fixed rate-Leg 1": [0.04, 0.05],
            "Platform identifier": ["ISWV", "NEW_PLATFORM"],
        })
        state, history = replay_lifecycle(messages)

        # Economics should be overwritten
        assert state["Notional amount-Leg 1"] == "200,000,000"
        assert state["Fixed rate-Leg 1"] == 0.05
        # Non-economics should NOT be overwritten
        assert state["Platform identifier"] == "ISWV"

    def test_corr_overwrites_all(self):
        """CORR should overwrite all fields."""
        messages = pd.DataFrame({
            "Action type": ["NEWT", "CORR"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, None],
            "Notional amount-Leg 1": ["100,000,000", "200,000,000"],
            "Platform identifier": ["ISWV", "NEW_PLATFORM"],
        })
        state, history = replay_lifecycle(messages)

        # All fields should be overwritten
        assert state["Notional amount-Leg 1"] == "200,000,000"
        assert state["Platform identifier"] == "NEW_PLATFORM"

    def test_term_sets_inactive(self):
        """TERM should set trade as inactive."""
        messages = pd.DataFrame({
            "Action type": ["NEWT", "TERM"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, None],
            "Notional amount-Leg 1": ["100,000,000", "100,000,000"],
        })
        state, history = replay_lifecycle(messages)

        assert state["Active"] is False

    def test_eror_invalidates_trade(self):
        """EROR should invalidate the trade entirely."""
        messages = pd.DataFrame({
            "Action type": ["NEWT", "EROR"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, None],
            "Notional amount-Leg 1": ["100,000,000", "100,000,000"],
        })
        state, history = replay_lifecycle(messages)

        assert state is None
        assert history == []

    def test_revi_reactivates_trade(self):
        """REVI should reactivate a terminated trade."""
        messages = pd.DataFrame({
            "Action type": ["NEWT", "TERM", "REVI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
                pd.Timestamp("2026-01-07 23:00:00"),
            ],
            "Amendment indicator": [None, None, None],
            "Notional amount-Leg 1": ["100,000,000", "100,000,000", "100,000,000"],
        })
        state, history = replay_lifecycle(messages)

        assert state["Active"] is True


class TestReplayLifecycleFull:
    """Tests for full lifecycle replay with ResolvedTrade output."""

    def test_creates_resolved_trade(self):
        """Should return a ResolvedTrade object with metadata."""
        messages = pd.DataFrame({
            "Dissemination Identifier": ["NEWT1", "MODI1"],
            "Action type": ["NEWT", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, False],
            "Notional amount-Leg 1": ["100,000,000", "100,000,000"],
        })
        resolved = replay_lifecycle_full(messages, "NEWT1")

        assert isinstance(resolved, ResolvedTrade)
        assert resolved.synthetic_uti == "NEWT1"
        assert resolved.message_ids == ["NEWT1", "MODI1"]
        assert resolved.status == "ACTIVE"
        assert resolved.is_new_trade is True
        assert resolved.is_lifecycle_update is True

    def test_tracks_inception_state(self):
        """Should track inception state from NEWT separately."""
        messages = pd.DataFrame({
            "Dissemination Identifier": ["NEWT1", "MODI1"],
            "Action type": ["NEWT", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, True],
            "Notional amount-Leg 1": ["100,000,000", "200,000,000"],
        })
        resolved = replay_lifecycle_full(messages, "NEWT1")

        # Inception state should have original notional
        assert resolved.inception_state is not None
        assert resolved.inception_state["Notional amount-Leg 1"] == "100,000,000"
        # Current state should have amended notional
        assert resolved.current_state is not None
        assert resolved.current_state["Notional amount-Leg 1"] == "200,000,000"

    def test_flags_missing_newt(self):
        """Should flag trades without NEWT action."""
        messages = pd.DataFrame({
            "Dissemination Identifier": ["MODI1", "MODI2"],
            "Action type": ["MODI", "MODI"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [False, False],
            "Notional amount-Leg 1": ["100,000,000", "100,000,000"],
        })
        resolved = replay_lifecycle_full(messages, "MODI1")

        assert "MISSING_NEWT" in resolved.quality_flags

    def test_errored_status(self):
        """Should set ERRORED status for EROR action."""
        messages = pd.DataFrame({
            "Dissemination Identifier": ["NEWT1", "EROR1"],
            "Action type": ["NEWT", "EROR"],
            "Event timestamp": [
                pd.Timestamp("2026-01-07 21:00:00"),
                pd.Timestamp("2026-01-07 22:00:00"),
            ],
            "Amendment indicator": [None, None],
            "Notional amount-Leg 1": ["100,000,000", "100,000,000"],
        })
        resolved = replay_lifecycle_full(messages, "NEWT1")

        assert resolved.status == "ERRORED"
        assert resolved.current_state is None


class TestPhantomTradePrevention:
    """
    Tests for phantom trade prevention using the exact example from the problem.

    The raw data has 7 messages (2 NEWT + 5 MODI) that represent only 2 option trades.
    """

    @pytest.fixture
    def swaption_straddle_messages(self):
        """Create the exact phantom trade scenario from the problem description."""
        return pd.DataFrame([
            # NEWT for PUT option
            {
                "Dissemination Identifier": "1655795162000000201",
                "Original Dissemination Identifier": "",
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Event timestamp": pd.Timestamp("2026-01-07 21:51:19", tz="UTC"),
                "Amendment indicator": None,
                "Notional amount-Leg 1": "100,000,000",
                "UPI FISN": "NA/O P Epn OIS USD",
                "Unique Product Identifier": "QZNLQ8T0N0SX",
            },
            # NEWT for CALL option
            {
                "Dissemination Identifier": "1655795161000000101",
                "Original Dissemination Identifier": "",
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Event timestamp": pd.Timestamp("2026-01-07 21:51:19", tz="UTC"),
                "Amendment indicator": None,
                "Notional amount-Leg 1": "100,000,000",
                "UPI FISN": "NA/O Call Epn OIS USD",
                "Unique Product Identifier": "QZZGWPNBF5R3",
            },
            # MODI for PUT (points to PUT NEWT)
            {
                "Dissemination Identifier": "1655894585000000101",
                "Original Dissemination Identifier": "1655795162000000201",
                "Action type": "MODI",
                "Event type": "TRAD",
                "Event timestamp": pd.Timestamp("2026-01-07 21:51:19", tz="UTC"),
                "Amendment indicator": False,
                "Notional amount-Leg 1": "100,000,000",
                "UPI FISN": "NA/O P Epn OIS USD",
                "Unique Product Identifier": "QZNLQ8T0N0SX",
            },
            # MODI for PUT (points to PUT NEWT)
            {
                "Dissemination Identifier": "1656268005000000101",
                "Original Dissemination Identifier": "1655795162000000201",
                "Action type": "MODI",
                "Event type": "TRAD",
                "Event timestamp": pd.Timestamp("2026-01-07 21:51:19", tz="UTC"),
                "Amendment indicator": False,
                "Notional amount-Leg 1": "100,000,000",
                "UPI FISN": "NA/O P Epn OIS USD",
                "Unique Product Identifier": "QZNLQ8T0N0SX",
            },
            # MODI for CALL (points to CALL NEWT)
            {
                "Dissemination Identifier": "1655795163000000301",
                "Original Dissemination Identifier": "1655795161000000101",
                "Action type": "MODI",
                "Event type": "TRAD",
                "Event timestamp": pd.Timestamp("2026-01-07 21:51:19", tz="UTC"),
                "Amendment indicator": False,
                "Notional amount-Leg 1": "100,000,000",
                "UPI FISN": "NA/O Call Epn OIS USD",
                "Unique Product Identifier": "QZZGWPNBF5R3",
            },
            # Another MODI for CALL (points to CALL NEWT)
            {
                "Dissemination Identifier": "1656192606000000601",
                "Original Dissemination Identifier": "1655795161000000101",
                "Action type": "MODI",
                "Event type": "TRAD",
                "Event timestamp": pd.Timestamp("2026-01-07 21:51:19", tz="UTC"),
                "Amendment indicator": False,
                "Notional amount-Leg 1": "100,000,000",
                "UPI FISN": "NA/O Call Epn OIS USD",
                "Unique Product Identifier": "QZZGWPNBF5R3",
            },
        ])

    def test_clustering_creates_two_trade_entities(self, swaption_straddle_messages):
        """7 messages should cluster into 2 trade entities (call + put)."""
        result = assign_synthetic_uti(swaption_straddle_messages)

        unique_utis = result["Synthetic UTI"].unique()
        assert len(unique_utis) == 2

    def test_semantic_anchor_is_newt_id(self, swaption_straddle_messages):
        """Synthetic UTIs should be the NEWT dissemination IDs."""
        result = assign_synthetic_uti(swaption_straddle_messages)

        unique_utis = set(result["Synthetic UTI"].unique())
        expected_anchors = {"1655795161000000101", "1655795162000000201"}
        assert unique_utis == expected_anchors

    def test_lifecycle_replay_produces_two_active_trades(self, swaption_straddle_messages):
        """Lifecycle replay should produce 2 active trades, not 7."""
        result = assign_synthetic_uti(swaption_straddle_messages)

        active_trades = 0
        for synthetic_uti, group in result.groupby("Synthetic UTI"):
            resolved = replay_lifecycle_full(
                group,
                synthetic_uti=str(synthetic_uti),
            )
            if resolved.is_active and resolved.is_new_trade:
                active_trades += 1

        assert active_trades == 2

    def test_total_notional_calculation(self, swaption_straddle_messages):
        """
        Correct volume calculation:
        - Naive (phantom): 7 messages * 100MM = 700MM
        - Correct (de-phantomed): 2 trades * 100MM = 200MM
        """
        result = assign_synthetic_uti(swaption_straddle_messages)

        # Naive sum (would cause phantom volume)
        naive_notional_count = len(swaption_straddle_messages)
        assert naive_notional_count == 6  # 6 messages with notional

        # Correct de-phantomed count
        unique_trades = result.groupby("Synthetic UTI").ngroups
        assert unique_trades == 2

        # Volume from resolved trades
        total_notional = 0
        for synthetic_uti, group in result.groupby("Synthetic UTI"):
            resolved = replay_lifecycle_full(group, str(synthetic_uti))
            if resolved.is_new_trade and resolved.current_state:
                notional_str = resolved.current_state.get("Notional amount-Leg 1", "0")
                notional = float(notional_str.replace(",", ""))
                total_notional += notional

        # Should be 200MM, not 600MM (6 * 100MM)
        assert total_notional == 200_000_000


class TestResolvedTradeProperties:
    """Tests for ResolvedTrade convenience properties."""

    def test_inception_notional(self):
        """Should extract inception notional from inception state."""
        resolved = ResolvedTrade(
            synthetic_uti="TEST1",
            inception_state={"Notional amount-Leg 1": 100_000_000},
            current_state={"Notional amount-Leg 1": 200_000_000},
        )
        assert resolved.inception_notional == 100_000_000
        assert resolved.current_notional == 200_000_000

    def test_is_active(self):
        """Should check ACTIVE status."""
        active = ResolvedTrade(synthetic_uti="TEST1", status="ACTIVE")
        terminated = ResolvedTrade(synthetic_uti="TEST2", status="TERMINATED")
        errored = ResolvedTrade(synthetic_uti="TEST3", status="ERRORED")

        assert active.is_active is True
        assert terminated.is_active is False
        assert errored.is_active is False

    def test_is_new_trade(self):
        """Should check for NEWT in actions."""
        with_newt = ResolvedTrade(
            synthetic_uti="TEST1",
            actions=[("NEWT", None), ("MODI", None)],
        )
        without_newt = ResolvedTrade(
            synthetic_uti="TEST2",
            actions=[("MODI", None), ("MODI", None)],
        )

        assert with_newt.is_new_trade is True
        assert without_newt.is_new_trade is False


class TestEconomicsFields:
    """Tests for economics field definitions."""

    def test_notional_fields_included(self):
        """Notional fields should be in economics."""
        assert "Notional amount-Leg 1" in ECONOMICS_FIELDS
        assert "Notional amount-Leg 2" in ECONOMICS_FIELDS

    def test_rate_fields_included(self):
        """Rate fields should be in economics."""
        assert "Fixed rate-Leg 1" in ECONOMICS_FIELDS
        assert "Fixed rate-Leg 2" in ECONOMICS_FIELDS
        assert "Spread-Leg 1" in ECONOMICS_FIELDS
        assert "Spread-Leg 2" in ECONOMICS_FIELDS

    def test_option_fields_included(self):
        """Option economics fields should be included."""
        assert "Strike Price" in ECONOMICS_FIELDS
        assert "Option Premium Amount" in ECONOMICS_FIELDS
        assert "Price" in ECONOMICS_FIELDS
