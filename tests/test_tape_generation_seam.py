from __future__ import annotations

import pytest

from SDRUtils._swappulse_scripts import _tape_tables as tt


def test_generation_is_v3():
    assert tt.TAPE_GENERATION == "v3"


def test_table_names_derive_from_generation():
    assert tt.PACKAGES_TABLE == "arbs_usd_swap_tape_packages_v3"
    assert tt.LEGS_TABLE == "arbs_usd_swap_tape_legs_v3"
    assert tt.RUNS_TABLE == "arbs_usd_swap_tape_ingestion_runs_v3"
    assert tt.DISPLAY_VIEW == "arbs_usd_swap_tape_display_v3"
    assert tt.OVERRIDES_TABLE == "arbs_usd_swap_tape_overrides_v3"
    assert tt.OVERRIDE_MEMBERS_TABLE == "arbs_usd_swap_tape_override_members_v3"
    assert tt.OVERRIDE_HISTORY_TABLE == "arbs_usd_swap_tape_override_history_v3"
    assert tt.NOTES_TABLE == "arbs_usd_swap_tape_notes_v3"
    assert tt.VWAP_TABLE == "arbs_usd_swap_vwap_daily_v3"
    assert tt.SIGNAL_TABLE == "arbs_usd_swap_tape_signal_v3"
    assert tt.QUALITY_VIEW == "arbs_usd_swap_tape_quality_daily_v3"


def test_manual_links_stays_unversioned():
    # Keyed by its own UUID and shared with the classification stage,
    # which stays on v2. Deliberately not part of the generation.
    assert tt.MANUAL_LINKS_TABLE == "arbs_usd_swap_manual_links_v2"


def test_index_infix_tracks_generation():
    # Index names are schema-global in Postgres, so they carry the
    # generation too. See test_tape_schema_generation.py for why.
    assert tt.IDX_INFIX == "v3"


def test_guard_allows_v3(monkeypatch):
    monkeypatch.setattr(tt, "TAPE_GENERATION", "v3")
    tt.assert_writable_generation()


def test_guard_refuses_v2(monkeypatch):
    monkeypatch.setattr(tt, "TAPE_GENERATION", "v2")
    monkeypatch.delenv("ARBS_ALLOW_V2_WRITES", raising=False)
    with pytest.raises(RuntimeError, match="run_swaptape"):
        tt.assert_writable_generation()


def test_guard_v2_requires_explicit_override(monkeypatch):
    monkeypatch.setattr(tt, "TAPE_GENERATION", "v2")
    monkeypatch.setenv("ARBS_ALLOW_V2_WRITES", "1")
    tt.assert_writable_generation()
