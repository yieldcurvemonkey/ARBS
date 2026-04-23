"""Write-path tests for ``ingest_usdswaps_tape``.

Skip gracefully when no test Postgres is available.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    attach_manual_links,
    build_leg_rows,
    build_package_rows,
    ensure_schema,
    write_tape_rows,
)
from SDRUtils._swappulse_scripts._tape_schema import (
    LEGS_TABLE,
    PACKAGES_TABLE,
    RUNS_TABLE,
    MANUAL_LINKS_TABLE,
)
from SDRUtils.analytics.trade_tape import TradeTape
from tests.fixtures.tape_lifecycle_fixtures import sample_classified_df


# --------------------------------------------------------------------------
# Shape-only unit tests (no DB required)
# --------------------------------------------------------------------------


def test_build_leg_rows_row_count_matches_tape():
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    legs = build_leg_rows(tape, as_of_date="2026-04-14")
    assert len(legs) == len(tape)


def test_build_leg_rows_columns_are_complete():
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import LEG_COLUMNS

    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    legs = build_leg_rows(tape, as_of_date="2026-04-14")
    for rec in legs:
        missing = [c for c in LEG_COLUMNS if c not in rec]
        assert not missing, f"missing keys: {missing}"


def test_build_package_rows_one_per_unique_package():
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    packages = build_package_rows(tape, as_of_date="2026-04-14")
    assert len(packages) == tape["package_id"].nunique()


def test_build_package_rows_curve_package_has_two_legs():
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    packages = build_package_rows(tape, as_of_date="2026-04-14")
    curve = next((p for p in packages if p["package_id"] == "P_CURVE_1"), None)
    assert curve is not None, "curve package missing"
    assert curve["legs_count"] == 2
    assert "2Y" in (curve.get("package_tenors") or "")
    assert "10Y" in (curve.get("package_tenors") or "")


def test_build_package_rows_lifecycle_mix_sums_correctly():
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    packages = build_package_rows(tape, as_of_date="2026-04-14")
    unw = next((p for p in packages if p["package_id"] == "P_UNW_1"), None)
    assert unw is not None
    assert unw["is_unwind"] is True
    assert unw["lifecycle_mix"].get("UNWIND", 0) >= 1


def test_build_rows_relabel_false_positive_sdr_package_as_outright():
    tape = pd.DataFrame(
        [
            {
                "trade_id": "T_FALSE_PACKAGE_1",
                "package_id": "P_FALSE_PACKAGE_1",
                "execution_timestamp": datetime(2026, 4, 9, 20, 56, 52, tzinfo=timezone.utc),
                "tenor_label": "10Y",
                "tenor_display": "10Y",
                "forward_label": "Spot",
                "package_type": "OUTRIGHT",
                "trade_type": "OUTRIGHT",
                "package_indicator": True,
                "n_package_legs": 1,
                "notional": 100_000_000.0,
                "risk": 20_000.0,
                "fixed_rate": 0.03829,
                "upi_delivery_type": "PHYS",
                "tape_label": "USD-SOFR-COMPOUND 1D Constant Spot 10Y Package PHYS",
                "leg_tape_label": "USD-SOFR-COMPOUND 1D Constant Spot 10Y Package PHYS",
            }
        ]
    )

    legs = build_leg_rows(tape, as_of_date="2026-04-09")
    packages = build_package_rows(tape, as_of_date="2026-04-09")

    assert legs[0]["tape_label"] == "USD-SOFR-COMPOUND 1D Constant Spot 10Y Outright PHYS"
    assert legs[0]["leg_tape_label"] == "USD-SOFR-COMPOUND 1D Constant Spot 10Y Outright PHYS"
    assert packages[0]["tape_label"] == "USD-SOFR-COMPOUND 1D Constant Spot 10Y Outright PHYS"
    assert packages[0]["package_indicator"] is True


# --------------------------------------------------------------------------
# DB-backed integration tests — skipped when no test Postgres is available
# --------------------------------------------------------------------------


@pytest.fixture
def test_engine(pg_test_url):
    engine = create_engine(pg_test_url)
    with engine.connect() as conn:
        for obj in (
            "DROP VIEW IF EXISTS arbs_usd_swap_tape_display_v1",
            f"DROP TABLE IF EXISTS {LEGS_TABLE} CASCADE",
            f"DROP TABLE IF EXISTS {PACKAGES_TABLE} CASCADE",
            f"DROP TABLE IF EXISTS {RUNS_TABLE} CASCADE",
        ):
            conn.execute(text(obj))
        conn.commit()
    ensure_schema(engine)
    return engine


def test_write_tape_rows_persists_all_lifecycle_types(test_engine):
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    stats = write_tape_rows(test_engine, tape, as_of_date="2026-04-14")
    assert stats["legs_written"] == len(tape)
    assert stats["packages_written"] == tape["package_id"].nunique()
    with test_engine.connect() as conn:
        n_legs = conn.execute(text(f"SELECT COUNT(*) FROM {LEGS_TABLE}")).scalar()
        n_pkgs = conn.execute(text(f"SELECT COUNT(*) FROM {PACKAGES_TABLE}")).scalar()
        curve_pkg_ind = conn.execute(
            text(
                f"""
                SELECT package_indicator
                FROM {PACKAGES_TABLE}
                WHERE package_id = 'P_CURVE_1'
                """
            )
        ).scalar()
    assert n_legs == len(tape)
    assert n_pkgs == tape["package_id"].nunique()
    assert curve_pkg_ind is True


def test_write_is_idempotent(test_engine):
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    write_tape_rows(test_engine, tape, as_of_date="2026-04-14")
    write_tape_rows(test_engine, tape, as_of_date="2026-04-14")
    with test_engine.connect() as conn:
        n_legs = conn.execute(text(f"SELECT COUNT(*) FROM {LEGS_TABLE}")).scalar()
    assert n_legs == len(tape)


def test_write_tape_rows_cleans_up_orphan_packages(test_engine):
    """A package row whose legs were re-assigned to a different package_id
    (e.g. a re-ingest under a changed detector) is garbage. The write path
    must clean it up so the dashboard doesn't render unexpandable rows.
    """
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    write_tape_rows(test_engine, tape, as_of_date="2026-04-14")

    # Simulate an orphan: insert a package row with no legs pointing at it.
    with test_engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {PACKAGES_TABLE}
                  (package_id, as_of_date, package_type, package_structure,
                   package_tenors, total_risk, gross_risk, total_notional,
                   gross_notional)
                VALUES
                  ('CURVE_ORPHAN_TEST', :asof, 'CURVE', '5Y/10Y CURVE',
                   '5Y/10Y', 40000, 40000, 100000000, 100000000)
                """
            ),
            {"asof": "2026-04-14"},
        )
        exists_before = conn.execute(
            text(
                f"SELECT COUNT(*) FROM {PACKAGES_TABLE} "
                f"WHERE package_id = 'CURVE_ORPHAN_TEST'"
            )
        ).scalar()
    assert exists_before == 1

    # Next write_tape_rows invocation should clean up the orphan.
    stats = write_tape_rows(test_engine, tape, as_of_date="2026-04-14")
    assert stats.get("orphan_packages_deleted", 0) >= 1

    with test_engine.connect() as conn:
        exists_after = conn.execute(
            text(
                f"SELECT COUNT(*) FROM {PACKAGES_TABLE} "
                f"WHERE package_id = 'CURVE_ORPHAN_TEST'"
            )
        ).scalar()
    assert exists_after == 0


def test_attach_manual_links_joins_trade_ids(test_engine):
    """Insert a manual link for the curve package, confirm trade_id mapping."""
    with test_engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {MANUAL_LINKS_TABLE}
                  (manual_package_id, package_type, linked_trade_ids, created_by)
                VALUES (:mpk, :pt, :ids, :cb)
                """
            ),
            {
                "mpk": "MP_TEST_CURVE",
                "pt": "CURVE",
                "ids": ["T_CURVE_2Y", "T_CURVE_10Y"],
                "cb": "pytest",
            },
        )
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    enriched = attach_manual_links(test_engine, tape)
    matched = enriched[enriched["trade_id"].isin(["T_CURVE_2Y", "T_CURVE_10Y"])]
    assert matched["manual_link_id"].notna().all()
    others = enriched[~enriched["trade_id"].isin(["T_CURVE_2Y", "T_CURVE_10Y"])]
    assert others["manual_link_id"].isna().all()


def test_run_ingest_records_run_row(test_engine, monkeypatch):
    """Smoke-test the observability lifecycle: start+finish rows land."""
    from SDRUtils._swappulse_scripts import ingest_usdswaps_tape as mod

    df = sample_classified_df()

    class _Fake:
        @staticmethod
        def load_usd_swaps(*a, **kw):  # noqa: D401
            return df, None

    monkeypatch.setitem(
        __import__("sys").modules,
        "notebooks.sdr._usd_swaps_common",
        _Fake,
    )
    rc = mod.run_ingest(
        pg_url=str(test_engine.url),
        start_date="2026-04-14",
        end_date="2026-04-14",
        use_cache=False,
    )
    assert rc == 0
    from sqlalchemy import text
    with test_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, rows_in, rows_out FROM "
                "arbs_usd_swap_tape_ingestion_runs_v1 ORDER BY run_id DESC LIMIT 1"
            )
        ).fetchone()
    assert row is not None
    assert row[0] == "success"
    assert row[1] == len(df)
