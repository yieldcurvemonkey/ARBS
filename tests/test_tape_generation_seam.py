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


def test_no_v2_tape_literals_remain_in_python():
    """No ARBS Python source may name a _v2 tape object literally.

    A constant change does not reach a hardcoded string. The one legal
    exception is the shared, unversioned manual-links table.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "SDRUtils"
    pattern = re.compile(r"arbs_usd_swap_(?!manual_links)\w*_v2")
    offenders: list[str] = []
    for fp in root.rglob("*.py"):
        if fp.name in {"_tape_schema.py", "ingest_usdswaps.py"}:
            continue  # v1 rollback DDL; classification tables stay on v2
        for i, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and "tape" in line:
                offenders.append(f"{fp.relative_to(root)}:{i}: {line.strip()[:90]}")
    assert offenders == [], "hardcoded _v2 tape literals:\n" + "\n".join(offenders)


def test_migration_cols_target_the_current_generation():
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import _LATEST_MIGRATION_COLS

    tables = {t for t, _ in _LATEST_MIGRATION_COLS}
    assert tables, "_LATEST_MIGRATION_COLS is empty"
    assert all(t.endswith(f"_{tt.TAPE_GENERATION}") for t in tables), sorted(tables)


def test_ensure_schema_calls_the_writer_guard():
    import inspect

    from SDRUtils._swappulse_scripts import ingest_usdswaps_tape as m

    src = inspect.getsource(m.ensure_schema)
    assert "assert_writable_generation()" in src


def test_risk_population_guard_is_still_wired():
    """PR #344's guard must survive the refactor.

    A transient curve failure yields all-NaN pv01. Without this guard the
    run publishes NULL risk and reports success -- the 2026-07-06 incident.
    """
    import inspect

    from SDRUtils._swappulse_scripts import ingest_usdswaps_tape as m

    assert hasattr(m, "_assert_risk_populated")
    callers = [
        name for name, fn in vars(m).items()
        if callable(fn) and getattr(fn, "__module__", None) == m.__name__
        and "_assert_risk_populated(" in inspect.getsource(fn)
        and name != "_assert_risk_populated"
    ]
    assert callers, "_assert_risk_populated is defined but never called"
