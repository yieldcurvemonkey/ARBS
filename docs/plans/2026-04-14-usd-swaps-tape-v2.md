# USD Swap Tape v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the USD swap SDR trade tape page with a lifecycle-complete dashboard powered by `SDRUtils.analytics.trade_tape.TradeTape`. Design doc: [`2026-04-14-usd-swaps-tape-v2-design.md`](2026-04-14-usd-swaps-tape-v2-design.md). Consult it for schemas, UX specs, and visual tokens — this plan is the task-by-task build sequence.

**Architecture:** (a) new Python ingest `ingest_usdswaps_tape.py` writes TradeTape output to two new Postgres tables + display view; (b) new `/api/usd-swaps-tape-v2/*` routes serve cursor-paginated enriched rows and sidecar aggregates; (c) new `features/usd-swaps-tape-v2/` feature directory mirrors swaption-tape structure with fresh copy-and-adapt; (d) cutover via parallel `/usd-swaps-v2` route during soak, then one-line page-import flip.

**Tech Stack:** Python (pandas, SQLAlchemy, psycopg2), Postgres, Next.js 15 App Router, TypeScript, React 19, PrimeReact, Tailwind v4, recharts, lucide-react, pg node driver.

**Env:** `conda activate stir` for all Python commands. `cd SDRUtils/dashboard && npm <cmd>` for all Node/Next commands.

**Phases / checkpoints:**

- **Phase A** — Python ingest + schema (Tasks 1-6). Checkpoint: run full ingest end-to-end on a sample day; verify rows in psql.
- **Phase B** — Next.js API routes (Tasks 7-17). Checkpoint: every route responds correctly to curl.
- **Phase C** — Frontend types + hooks (Tasks 18-26). Checkpoint: hooks tested in isolation with Jest.
- **Phase D** — Frontend main table (Tasks 27-32). Checkpoint: table renders sample data with lifecycle row treatment.
- **Phase E** — Header + filters (Tasks 33-36). Checkpoint: filter state round-trips via URL.
- **Phase F** — Sidecars (Tasks 37-43). Checkpoint: each sidecar filters main table via URL.
- **Phase G** — Orchestration + cutover (Tasks 44-48). Checkpoint: Puppeteer E2E passes; page cutover.

Each phase ends with a commit and a manual smoke test. Do not proceed to the next phase until the checkpoint test passes.

---

## Phase A — Python ingest + schema

### Task 1: Create schema SQL and write migration test

**Files:**
- Create: `SDRUtils/_swappulse_scripts/_tape_schema.py` — holds `TAPE_SCHEMA_SQL` constant
- Create: `tests/test_ingest_usdswaps_tape_schema.py`

**Step 1: Write the failing test**

```python
# tests/test_ingest_usdswaps_tape_schema.py
import pytest
from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts._tape_schema import TAPE_SCHEMA_SQL


@pytest.fixture
def test_engine(pg_test_url):
    engine = create_engine(pg_test_url)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS arbs_usd_swap_tape_legs_v1 CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS arbs_usd_swap_tape_packages_v1 CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS arbs_usd_swap_tape_ingestion_runs_v1 CASCADE"))
        conn.execute(text("DROP VIEW IF EXISTS arbs_usd_swap_tape_display_v1"))
        conn.commit()
    return engine


def test_schema_creates_all_objects(test_engine):
    with test_engine.connect() as conn:
        conn.execute(text(TAPE_SCHEMA_SQL))
        conn.commit()
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name LIKE 'arbs_usd_swap_tape_%'
            ORDER BY table_name
        """))
        tables = [r[0] for r in result]
    assert "arbs_usd_swap_tape_legs_v1" in tables
    assert "arbs_usd_swap_tape_packages_v1" in tables
    assert "arbs_usd_swap_tape_ingestion_runs_v1" in tables


def test_schema_is_idempotent(test_engine):
    with test_engine.connect() as conn:
        conn.execute(text(TAPE_SCHEMA_SQL))
        conn.execute(text(TAPE_SCHEMA_SQL))  # second run must not fail
        conn.commit()


def test_display_view_exists(test_engine):
    with test_engine.connect() as conn:
        conn.execute(text(TAPE_SCHEMA_SQL))
        conn.commit()
        result = conn.execute(text("""
            SELECT 1 FROM information_schema.views
            WHERE table_name = 'arbs_usd_swap_tape_display_v1'
        """))
        assert result.fetchone() is not None
```

**Step 2: Run test, verify it fails with ModuleNotFoundError**

```
conda activate stir && pytest tests/test_ingest_usdswaps_tape_schema.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'SDRUtils._swappulse_scripts._tape_schema'`.

**Step 3: Implement `_tape_schema.py` with the full DDL**

Transcribe the exact column list from the design doc §4.2 and §4.3 into a single `TAPE_SCHEMA_SQL` string. Include:

- `CREATE EXTENSION IF NOT EXISTS pgcrypto;`
- `CREATE TABLE IF NOT EXISTS arbs_usd_swap_tape_packages_v1 (...);`
- `CREATE TABLE IF NOT EXISTS arbs_usd_swap_tape_legs_v1 (...);` with `FK package_id REFERENCES arbs_usd_swap_tape_packages_v1(package_id)`
- `CREATE TABLE IF NOT EXISTS arbs_usd_swap_tape_ingestion_runs_v1 (...)` with fields from design §11.1.
- All indexes listed in design §13.
- `CREATE OR REPLACE VIEW arbs_usd_swap_tape_display_v1 AS SELECT p.*, l.legs_json, ml.manual_package_id, ml.user_comment, ml.link_reason, ml.tags, ml.link_metrics, ml.created_by AS link_created_by, ml.created_at AS link_created_at FROM arbs_usd_swap_tape_packages_v1 p LEFT JOIN LATERAL (SELECT jsonb_agg(jsonb_build_object(...) ORDER BY leg_order) AS legs_json FROM arbs_usd_swap_tape_legs_v1 l WHERE l.package_id = p.package_id) l ON TRUE LEFT JOIN arbs_usd_swap_manual_links_v2 ml ON ml.link_id = p.manual_link_id;`

Pattern after the existing `SCHEMA_SQL` in `SDRUtils/_swappulse_scripts/ingest_usdswaps.py`.

**Step 4: Run tests; verify pass**

```
conda activate stir && pytest tests/test_ingest_usdswaps_tape_schema.py -v
```
Expected: 3 passed.

**Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/_tape_schema.py tests/test_ingest_usdswaps_tape_schema.py
git commit -m "feat(tape-ingest): schema for tape packages/legs tables + display view"
```

---

### Task 2: Fixture DataFrame covering every lifecycle type

**Files:**
- Create: `tests/fixtures/tape_lifecycle_fixtures.py`

**Step 1: Define a fixture-building function**

```python
# tests/fixtures/tape_lifecycle_fixtures.py
"""Sample DataFrames covering every lifecycle type for tape ingest tests."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pandas as pd


def _row(**kw) -> dict:
    base = {
        "trade_id": "T_0",
        "package_id": "P_0",
        "execution_timestamp": datetime(2026, 4, 14, 14, 30, tzinfo=timezone.utc),
        "effective_date": "2026-04-16",
        "expiration_date": "2031-04-16",
        "notional": 100_000_000.0,
        "notional_currency": "USD",
        "risk": 50_000.0,
        "fixed_rate": 0.045,
        "tenor_years": 5.0,
        "tenor_label": "5Y",
        "forward_start_years": 0.0,
        "forward_label": "Spot",
        "is_forward": False,
        "event_action": "NEWT",
        "event_type": None,
        "platform_identifier": "BLOOM-SEF",
        "cleared": "CLEARED",
        "upi_underlier_name": "USD-SOFR-COMPOUND",
        "unique_product_identifier": "QWERTYUIOP",
        "package_type": "OUTRIGHT",
        "package_indicator": False,
        "package_transaction_spread": None,
        "block_trade_election_indicator": False,
        "is_notional_capped": False,
        "non_standardized_term_indicator": False,
        "other_payment_type": None,
        "other_payment_amount": None,
    }
    base.update(kw)
    return base


def sample_classified_df() -> pd.DataFrame:
    """Return a DF with one row per lifecycle type the tape must show."""
    rows: List[dict] = [
        # NEW_RISK (baseline NEWT)
        _row(trade_id="T_NEWT_1", package_id="P_NEWT_1"),
        # UNWIND (forward_start_years < -0.02)
        _row(trade_id="T_UNW_1", package_id="P_UNW_1",
             forward_start_years=-0.05, forward_label="Unwind"),
        # COMPRESSION via event_type
        _row(trade_id="T_CMP_1", package_id="P_CMP_1",
             event_action="TERM", event_type="COMP"),
        # TERMINATION (non-compression TERM)
        _row(trade_id="T_TERM_1", package_id="P_TERM_1",
             event_action="TERM", event_type=None),
        # NOVATION_BORN (NOVA + NEWT)
        _row(trade_id="T_NOVA_BORN_1", package_id="P_NOVA_1",
             event_action="NEWT", event_type="NOVA"),
        # NOVATION_TERMINATED (NOVA + TERM)
        _row(trade_id="T_NOVA_TERM_1", package_id="P_NOVA_1",
             event_action="TERM", event_type="NOVA"),
        # RESET_OPTIMIZATION (tenor < 0.5 + specific conditions)
        _row(trade_id="T_RST_1", package_id="P_RST_1",
             tenor_years=0.25, tenor_label="3M"),
        # CORRECTION
        _row(trade_id="T_CORR_1", package_id="P_CORR_1",
             event_action="CORR"),
        # CLEARING_TERMINATION
        _row(trade_id="T_CLR_1", package_id="P_CLR_1",
             event_action="TERM", event_type="CLRG"),
        # EXERCISE_BORN
        _row(trade_id="T_XERC_1", package_id="P_XERC_1",
             event_action="NEWT", event_type="EXER"),
        # Block
        _row(trade_id="T_BLK_1", package_id="P_BLK_1",
             block_trade_election_indicator=True),
        # Capped
        _row(trade_id="T_CAP_1", package_id="P_CAP_1",
             is_notional_capped=True),
        # Off-date
        _row(trade_id="T_ODT_1", package_id="P_ODT_1",
             tenor_years=6.87, tenor_label="6Y",
             expiration_date="2032-07-22"),
        # 2-leg CURVE package
        _row(trade_id="T_CURVE_2Y", package_id="P_CURVE_1",
             tenor_years=2.0, tenor_label="2Y",
             package_type="CURVE", package_indicator=True),
        _row(trade_id="T_CURVE_10Y", package_id="P_CURVE_1",
             tenor_years=10.0, tenor_label="10Y",
             package_type="CURVE", package_indicator=True),
        # FOMC-dated (fomc-meeting tenor logic lives in TradeTape)
        _row(trade_id="T_FOMC_1", package_id="P_FOMC_1",
             effective_date="2026-04-29", expiration_date="2026-06-17"),
    ]
    return pd.DataFrame(rows)
```

**Step 2: Commit**

```bash
git add tests/fixtures/tape_lifecycle_fixtures.py
git commit -m "test(tape-ingest): fixture DF covering every lifecycle type"
```

No test to run; this is a fixture reused by later tasks.

---

### Task 3: TradeTape round-trip — classified DF → enriched DF → row count check

**Files:**
- Create: `tests/test_trade_tape_on_fixture.py`

**Step 1: Write the test**

```python
# tests/test_trade_tape_on_fixture.py
"""Verify TradeTape emits one enriched row per classified input row."""
import pytest

from SDRUtils.analytics.trade_tape import TradeTape
from tests.fixtures.tape_lifecycle_fixtures import sample_classified_df


def test_compute_preserves_row_count():
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    assert len(tape) == len(df)


def test_compute_has_all_expected_columns():
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    for col in [
        "trade_id", "package_id", "execution_timestamp", "execution_session",
        "tape_label", "tenor_display", "trade_type", "venue", "ccp",
        "rate_index_clean", "is_new_risk", "is_unwind", "is_compression",
        "is_reset_optimization", "is_ufro", "is_block", "is_off_date",
        "lifecycle_type", "quality_flags",
    ]:
        assert col in tape.columns, f"missing column: {col}"


def test_each_lifecycle_row_has_correct_flag():
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    by_id = tape.set_index("trade_id")
    assert by_id.loc["T_UNW_1", "is_unwind"]
    # Add the rest per the flag semantics in trade_tape.py.
```

**Step 2: Run; resolve any fixture/class mismatches**

```
conda activate stir && pytest tests/test_trade_tape_on_fixture.py -v
```

This test exists to pin the expected contract between the fixture and TradeTape. If TradeTape's current behavior differs (e.g., column naming), update the fixture or open a follow-up — do NOT silently adjust TradeTape.

**Step 3: Commit**

```bash
git add tests/test_trade_tape_on_fixture.py
git commit -m "test(tape-ingest): TradeTape round-trip on lifecycle fixture"
```

---

### Task 4: Ingest write-path — `ingest_usdswaps_tape.py` skeleton + unit test

**Files:**
- Create: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`
- Create: `tests/test_ingest_usdswaps_tape_writepath.py`

**Step 1: Write the failing test**

```python
# tests/test_ingest_usdswaps_tape_writepath.py
import pytest
from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts._tape_schema import TAPE_SCHEMA_SQL
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    write_tape_rows, run_ingest,
)
from tests.fixtures.tape_lifecycle_fixtures import sample_classified_df


@pytest.fixture
def test_engine(pg_test_url):
    engine = create_engine(pg_test_url)
    with engine.connect() as conn:
        # Reset tape tables; assume manual-links table already exists via existing schema
        for obj in [
            "arbs_usd_swap_tape_display_v1",
            "arbs_usd_swap_tape_legs_v1",
            "arbs_usd_swap_tape_packages_v1",
            "arbs_usd_swap_tape_ingestion_runs_v1",
        ]:
            conn.execute(text(f"DROP TABLE IF EXISTS {obj} CASCADE") if "tape_display" not in obj
                         else text(f"DROP VIEW IF EXISTS {obj}"))
        conn.execute(text(TAPE_SCHEMA_SQL))
        conn.commit()
    return engine


def test_write_tape_rows_persists_all_lifecycle_types(test_engine):
    from SDRUtils.analytics.trade_tape import TradeTape
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    write_tape_rows(test_engine, tape, as_of_date="2026-04-14")
    with test_engine.connect() as conn:
        n_legs = conn.execute(text(
            "SELECT COUNT(*) FROM arbs_usd_swap_tape_legs_v1"
        )).scalar()
        n_pkgs = conn.execute(text(
            "SELECT COUNT(*) FROM arbs_usd_swap_tape_packages_v1"
        )).scalar()
    assert n_legs == len(tape)
    # Package count = unique package_id
    assert n_pkgs == tape["package_id"].nunique()


def test_write_is_idempotent(test_engine):
    from SDRUtils.analytics.trade_tape import TradeTape
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    write_tape_rows(test_engine, tape, as_of_date="2026-04-14")
    write_tape_rows(test_engine, tape, as_of_date="2026-04-14")
    with test_engine.connect() as conn:
        n_legs = conn.execute(text(
            "SELECT COUNT(*) FROM arbs_usd_swap_tape_legs_v1"
        )).scalar()
    assert n_legs == len(tape)  # no duplication
```

**Step 2: Run — expect failure on missing module**

```
conda activate stir && pytest tests/test_ingest_usdswaps_tape_writepath.py -v
```

**Step 3: Implement the module skeleton + write functions**

```python
# SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py
"""USD swap tape v2 ingestion.

Runs TradeTape.compute() against the output of the classification
pipeline and persists enriched per-trade + per-package rows to the
arbs_usd_swap_tape_* tables for the Next.js dashboard.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from SDRUtils.analytics.trade_tape import TradeTape
from ._tape_schema import TAPE_SCHEMA_SQL


LEG_COLUMNS: tuple[str, ...] = (
    # hoisted columns — keep in sync with _tape_schema.py
    # Full list per design doc §4.2
    "trade_id", "package_id", "as_of_date", "execution_timestamp",
    "execution_session", "execution_hour_et",
    "tenor_years", "tenor_label", "tenor_display",
    "forward_start_years", "forward_label", "forward_bucket",
    "effective_date", "expiration_date",
    "notional", "notional_currency", "risk", "fixed_rate",
    "trade_type", "rate_index_clean", "venue", "ccp", "platform_identifier",
    "tape_label", "upi_reset_freq", "upi_notional_schedule", "upi_delivery_type",
    "is_new_risk", "is_unwind", "is_compression", "is_compression_spec",
    "is_reset_optimization", "is_novation", "is_novation_born",
    "is_novation_terminated", "is_exercise_born", "is_clearing_termination",
    "lifecycle_type", "lc_n_events", "lc_status",
    "is_ufro", "is_off_market", "is_capped", "is_block", "is_off_date",
    "is_mac", "is_spreadover", "is_asset_swap", "is_non_standard_term",
    "quality_flags",
    "is_fomc_dated", "fomc_meeting_label", "fomc_proximity",
    "is_month_end", "is_quarter_end",
    "cluster_id", "cluster_size", "is_multi_meeting_cluster",
    "xd_status", "xd_n_events", "xd_notional_pct_remaining",
    "xd_is_terminated", "xd_has_partial_unwind",
    "manual_link_id",
)

PACKAGE_COLUMNS: tuple[str, ...] = (
    "package_id", "manual_link_id", "as_of_date",
    "execution_start", "execution_end",
    "package_structure", "package_type", "package_tenors",
    "n_package_legs", "legs_count",
    "total_notional", "gross_notional", "total_risk", "gross_risk",
    "weighted_fixed_rate", "min_fixed_rate", "max_fixed_rate",
    "has_spread", "package_transaction_spread",
    "rate_index_clean", "venue", "ccp", "execution_session",
    "is_new_risk", "is_unwind",
    "is_compression_any", "is_ufro_any", "is_block_any", "is_capped_any",
    "is_off_date_any", "is_termination_any", "is_novation_any",
    "is_reset_optimization_any", "is_clearing_termination_any", "is_correction_any",
    "lifecycle_mix",
    "is_fomc_dated", "fomc_meeting_label",
    "cluster_id", "cluster_size",
    "tape_label",
)


def _to_jsonb(value: Any) -> Any:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def build_package_rows(tape: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the per-trade TradeTape output into one row per package_id."""
    # Implementation: groupby package_id, compute aggregates per the
    # column list above; rolled-up flags use .any(); lifecycle_mix is a dict
    # of lifecycle_type value_counts; tape_label picks most-descriptive leg.
    # See design doc §4.3 for exact semantics.
    raise NotImplementedError


def write_tape_rows(engine: Engine, tape: pd.DataFrame, as_of_date: str) -> dict:
    """Upsert leg + package rows in a single transaction. Returns stats."""
    # Implementation: derive package_df via build_package_rows;
    # use INSERT ... ON CONFLICT (primary key) DO UPDATE for idempotency;
    # Write in order: packages FIRST (legs FK references them), then legs.
    raise NotImplementedError


def run_ingest(
    pg_url: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True,
) -> int:
    """Full pipeline: load classified df → TradeTape.compute() → write → record run."""
    raise NotImplementedError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-url", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    return run_ingest(
        pg_url=args.pg_url,
        start_date=args.start_date,
        end_date=args.end_date,
        use_cache=not args.no_cache,
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4: Implement `build_package_rows` and `write_tape_rows`**

Follow the column list and aggregation semantics from design §4.3. Use SQLAlchemy `Connection.execute(text(sql), rows_as_dicts)` with `INSERT ... ON CONFLICT ... DO UPDATE SET ...` for idempotency. Use a single transaction wrapping packages-then-legs writes.

**Step 5: Run tests to green**

```
conda activate stir && pytest tests/test_ingest_usdswaps_tape_writepath.py -v
```

**Step 6: Commit**

```bash
git add SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py tests/test_ingest_usdswaps_tape_writepath.py
git commit -m "feat(tape-ingest): write-path for tape packages/legs with idempotent upsert"
```

---

### Task 5: Manual-link join + `run_ingest` end-to-end test

**Files:**
- Modify: `tests/test_ingest_usdswaps_tape_writepath.py`
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`

**Step 1: Extend test**

Add:

```python
def test_manual_link_joins_through_display_view(test_engine):
    """An existing manual_link_id on a package must surface via the display view."""
    from SDRUtils.analytics.trade_tape import TradeTape
    # Given: a manual-link row exists for two trade_ids belonging to the same package
    with test_engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO arbs_usd_swap_manual_links_v2
              (manual_package_id, package_type, linked_trade_ids, created_by)
            VALUES ('MP_TEST_1', 'CURVE',
                    ARRAY['T_CURVE_2Y','T_CURVE_10Y'], 'tester')
        """))
        conn.commit()
    df = sample_classified_df()
    tape = TradeTape(df=df, raw_df=None).compute(use_cache=False)
    # Attach manual_link_id on rows whose trade_id is in the link's array
    # (production code does this via Python-side lookup before write_tape_rows)
    # ...fill in per run_ingest's implementation...
    # Then query the display view; the package row must carry manual_package_id
    ...


def test_run_ingest_records_run(test_engine):
    # Assert a row is inserted into arbs_usd_swap_tape_ingestion_runs_v1
    ...
```

**Step 2: Implement the manual-link lookup in `run_ingest`**

Join `arbs_usd_swap_manual_links_v2` on `linked_trade_ids` containment; attach `manual_link_id` to the enriched DF before calling `write_tape_rows`.

**Step 3: Implement the runs-table observability row**

Open a `run` row before ingest, close it with `status`, `rows_in`, `rows_out`, `cache_hit`, elapsed, `failed_rows` JSONB.

**Step 4: Run tests; commit**

```
conda activate stir && pytest tests/test_ingest_usdswaps_tape_writepath.py -v
git add -A && git commit -m "feat(tape-ingest): manual-link join + ingestion-run observability"
```

---

### Task 6: Phase A checkpoint — run ingest end-to-end on a recent day

**Files:** (none — this is a smoke test)

**Step 1: Run against a recent classified day**

```
conda activate stir
python -m SDRUtils._swappulse_scripts.ingest_usdswaps_tape \
  --pg-url "$DATABASE_URL" \
  --start-date 2026-04-14 --end-date 2026-04-14
```

**Step 2: Verify in psql**

```sql
SELECT status, rows_in, rows_out, failed_rows, cache_hit
FROM arbs_usd_swap_tape_ingestion_runs_v1 ORDER BY started_at DESC LIMIT 1;

SELECT lifecycle_type, COUNT(*)
FROM arbs_usd_swap_tape_legs_v1
WHERE as_of_date = '2026-04-14'
GROUP BY 1 ORDER BY 2 DESC;

SELECT package_type, COUNT(*)
FROM arbs_usd_swap_tape_packages_v1
WHERE as_of_date = '2026-04-14'
GROUP BY 1 ORDER BY 2 DESC;

SELECT * FROM arbs_usd_swap_tape_display_v1
WHERE as_of_date = '2026-04-14' ORDER BY execution_start DESC LIMIT 3;
```

**Acceptance criteria:**

- `status = 'success'` in runs table
- ≥ 5 distinct `lifecycle_type` values visible
- Display view returns rows with populated `legs_json`, `tape_label`, `trade_type`
- No row has NULL `tape_label` or `risk`

**Step 3: Proceed to Phase B only when checkpoint passes.**

---

## Phase B — Next.js API routes

### Task 7: API lib + `resolveDisplayView`

**Files:**
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts`
- Create: `SDRUtils/dashboard/src/lib/__tests__/usd-swaps-tape-v2.test.ts`

**Step 1: Write the test**

```ts
// SDRUtils/dashboard/src/lib/__tests__/usd-swaps-tape-v2.test.ts
import { resolveDisplayView } from '../usd-swaps-tape-v2'
jest.mock('../db', () => ({
  query: jest.fn(async (_sql: string, params: any[]) => ({
    rows: [{ rel: params[0] === 'arbs_usd_swap_tape_display_v1' ? 'arbs_usd_swap_tape_display_v1' : null }],
  })),
}))

describe('resolveDisplayView', () => {
  it('returns the v1 view when it exists', async () => {
    const { view, columns } = await resolveDisplayView()
    expect(view).toBe('arbs_usd_swap_tape_display_v1')
    expect(columns).toContain('d.tape_label')
    expect(columns).toContain('d.lifecycle_mix')
    expect(columns).toContain('d.legs_json')
  })
})
```

**Step 2: Run — fail on missing module**

```
cd SDRUtils/dashboard && npm run test -- --testPathPatterns=usd-swaps-tape-v2
```

**Step 3: Implement `usd-swaps-tape-v2.ts`**

Pattern exactly after `usd-swaps-tape.ts`:

```ts
import { query } from '@/lib/db'
import type { UsdSwapTapeRow } from '@/features/usd-swaps-tape-v2/types'

const DISPLAY_VIEW = 'arbs_usd_swap_tape_display_v1'

const COLUMNS = [
  'd.package_id', 'd.package_type', 'd.as_of_date',
  'd.execution_start', 'd.execution_end',
  'd.package_structure', 'd.package_tenors',
  'd.n_package_legs', 'd.legs_count',
  'd.total_notional', 'd.gross_notional',
  'd.total_risk', 'd.gross_risk',
  'd.weighted_fixed_rate', 'd.min_fixed_rate', 'd.max_fixed_rate',
  'd.has_spread', 'd.package_transaction_spread',
  'd.rate_index_clean', 'd.venue', 'd.ccp', 'd.execution_session',
  // ...every column per design §5.1 response shape
  'd.legs_json',
  'd.manual_package_id', 'd.user_comment', 'd.link_reason', 'd.tags',
  'd.link_metrics', 'd.link_created_by', 'd.link_created_at',
].join(', ')

export async function resolveDisplayView() {
  const result = await query<{ rel: string | null }>(
    'SELECT to_regclass($1) AS rel', [DISPLAY_VIEW]
  )
  if (!result.rows[0]?.rel) {
    throw new Error(
      `tape display view ${DISPLAY_VIEW} not found — run ingest_usdswaps_tape`
    )
  }
  return { view: DISPLAY_VIEW, columns: COLUMNS }
}

export type { UsdSwapTapeRow }
```

**Step 4: Run tests; commit**

```
cd SDRUtils/dashboard && npm run test -- --testPathPatterns=usd-swaps-tape-v2
git add -A && git commit -m "feat(dashboard): lib resolver for tape v2 display view"
```

---

### Task 8: Type stubs — `features/usd-swaps-tape-v2/types/trade.types.ts`

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/trade.types.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/index.ts`

**Step 1: Write types**

```ts
// SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/trade.types.ts
import type { SofrSwapTapeLeg, SofrSwapTapeRow } from '@/features/sofr-swaps-tape/types'

export type LifecycleType =
  | 'NEW_RISK' | 'UNWIND' | 'COMPRESSION' | 'TERMINATION'
  | 'NOVATION' | 'RESET_OPT' | 'CORRECTION' | 'CLEARING_TERM'
  | 'EXERCISE_BORN' | 'OTHER'

export type UsdSwapTapeLeg = SofrSwapTapeLeg & {
  tape_label?: string | null
  trade_type?: string | null
  tenor_display?: string | null
  venue?: string | null
  ccp?: string | null
  rate_index_clean?: string | null
  execution_session?: string | null
  lifecycle_type?: LifecycleType | null
  fomc_meeting_label?: string | null
  fomc_proximity?: string | null
  cluster_id?: string | null
  is_new_risk?: boolean | null
  is_unwind?: boolean | null
  is_compression?: boolean | null
  is_reset_optimization?: boolean | null
  is_ufro?: boolean | null
  is_off_market?: boolean | null
  is_capped?: boolean | null
  is_block?: boolean | null
  is_off_date?: boolean | null
  is_novation_born?: boolean | null
  is_novation_terminated?: boolean | null
  is_exercise_born?: boolean | null
  is_clearing_termination?: boolean | null
  is_non_standard_term?: boolean | null
  xd_is_terminated?: boolean | null
  xd_has_partial_unwind?: boolean | null
  xd_notional_pct_remaining?: number | null
  quality_flags?: string[] | null
}

export type UsdSwapTapeRow = SofrSwapTapeRow & {
  package_structure?: string | null
  trade_type?: string | null
  venue?: string | null
  ccp?: string | null
  rate_index_clean?: string | null
  execution_session?: string | null
  tape_label?: string | null
  fomc_meeting_label?: string | null
  is_fomc_dated?: boolean | null
  is_unwind?: boolean | null
  is_block_any?: boolean | null
  is_capped_any?: boolean | null
  is_off_date_any?: boolean | null
  is_compression_any?: boolean | null
  is_ufro_any?: boolean | null
  is_termination_any?: boolean | null
  is_novation_any?: boolean | null
  is_reset_optimization_any?: boolean | null
  is_clearing_termination_any?: boolean | null
  is_correction_any?: boolean | null
  cluster_id?: string | null
  cluster_size?: number | null
  lifecycle_mix?: Record<string, number> | null
  legs_json: UsdSwapTapeLeg[]
}

export type UsdSwapTapeResponse = {
  rows: UsdSwapTapeRow[]
  nextCursor: string | null
  hasMore: boolean
  latestExecutionStart: string | null
}
```

**Step 2: Create index barrel**

```ts
// SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/index.ts
export * from './trade.types'
// filter.types, chart.types, link.types, sidecar.types added in later tasks
```

**Step 3: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types
git commit -m "feat(tape-v2): types for enriched row + leg + response"
```

---

### Task 9: Main tape route — `GET /api/usd-swaps-tape-v2`

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.test.ts`

**Step 1: Write tests**

```ts
// SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.test.ts
import { GET } from '../route'
import { query } from '@/lib/db'

jest.mock('@/lib/db')
jest.mock('@/lib/usd-swaps-tape-v2', () => ({
  resolveDisplayView: jest.fn(async () => ({
    view: 'arbs_usd_swap_tape_display_v1',
    columns: 'd.*',
  })),
}))

const mockQuery = query as jest.MockedFunction<typeof query>

describe('GET /api/usd-swaps-tape-v2', () => {
  beforeEach(() => { mockQuery.mockReset() })

  it('returns rows with empty query', async () => {
    mockQuery.mockResolvedValue({ rows: [] } as any)
    const res = await GET(new Request('http://x/api/usd-swaps-tape-v2'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body).toEqual({ rows: [], hasMore: false, nextCursor: null, latestExecutionStart: null })
  })

  it('rejects cursor+since simultaneously', async () => {
    const res = await GET(new Request(
      'http://x/api/usd-swaps-tape-v2?cursor=2026-04-14&since=2026-04-14'
    ))
    expect(res.status).toBe(400)
  })

  it('default clean=false includes all lifecycle types (no clean WHERE)', async () => {
    mockQuery.mockResolvedValue({ rows: [] } as any)
    await GET(new Request('http://x/api/usd-swaps-tape-v2'))
    const sql = mockQuery.mock.calls[0][0] as string
    expect(sql).not.toMatch(/is_compression_any/i)
    expect(sql).not.toMatch(/is_unwind/i)
  })

  it('clean=true adds the noise-filter WHERE clause', async () => {
    mockQuery.mockResolvedValue({ rows: [] } as any)
    await GET(new Request('http://x/api/usd-swaps-tape-v2?clean=true'))
    const sql = mockQuery.mock.calls[0][0] as string
    expect(sql).toMatch(/NOT d\.is_unwind/)
    expect(sql).toMatch(/NOT d\.is_compression_any/)
    expect(sql).toMatch(/NOT d\.is_ufro_any/)
  })

  it('lifecycle=new_risk,unwind renders matching IN clause', async () => {
    mockQuery.mockResolvedValue({ rows: [] } as any)
    await GET(new Request('http://x/api/usd-swaps-tape-v2?lifecycle=new_risk,unwind'))
    // Expected: a CASE or OR-condition that filters to those two lifecycle types.
    // Exact form depends on implementation; assert the fields are referenced.
    const sql = mockQuery.mock.calls[0][0] as string
    expect(sql).toMatch(/is_new_risk|is_unwind/)
  })

  it('returns 500 on db error', async () => {
    mockQuery.mockRejectedValue(new Error('connection refused'))
    const res = await GET(new Request('http://x/api/usd-swaps-tape-v2'))
    expect(res.status).toBe(500)
  })
})
```

**Step 2: Run — fail on missing route**

**Step 3: Implement the route**

Start from `src/app/api/sofr-swaps-tape/route.ts` (copy whole file into new route dir). Change:

- View/columns source: `resolveDisplayView()` from `@/lib/usd-swaps-tape-v2`.
- `COLUMN_FILTER_FIELDS` extended with `trade_type, venue, ccp, session, rate_index, tape_label, fomc_meeting, lifecycle`.
- `COLUMN_FILTER_EXPRESSIONS` map: each new field maps to the same-named column on `d`.
- New helper `buildCleanTapeClause()` returns the WHERE fragment for `?clean=true`.
- New helper `buildCategoryFilter(field, csv)` for `lifecycle`, `tradeTypes`, `venues`, `ccps`, `sessions`, `rateIndex`, `tenors`, `fomcMeeting`.
- Compose all into the existing WHERE builder; existing cursor/since/global-filter logic unchanged.

Keep the response shape identical to `SofrSwapTapeResponse` (just richer rows).

**Step 4: Run tests green**

```
cd SDRUtils/dashboard && npm run test -- --testPathPatterns=usd-swaps-tape-v2
```

**Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__
git commit -m "feat(api): tape v2 main route with clean+lifecycle+category filters"
```

---

### Task 10: Risk-concentration route

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/risk-concentration/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/risk-concentration/__tests__/route.test.ts`

**Step 1: Write test**

```ts
import { GET } from '../route'
import { query } from '@/lib/db'

jest.mock('@/lib/db')
const mockQuery = query as jest.MockedFunction<typeof query>

describe('GET /risk-concentration', () => {
  it('returns groups sorted by abs(total_dv01)', async () => {
    mockQuery.mockResolvedValue({
      rows: [
        { value: 'SOFR Spot 5Y Outright', trade_count: 100, total_dv01: 1_200_000, total_notional: 1e10 },
        { value: 'SOFR Spot 10Y Unwind',  trade_count: 30,  total_dv01: -400_000,  total_notional: 4e9  },
      ],
    } as any)
    const res = await GET(new Request('http://x/r?groupBy=tape_label'))
    const body = await res.json()
    expect(body.groups).toHaveLength(2)
    expect(body.groups[0].value).toBe('SOFR Spot 5Y Outright')
  })

  it('rejects invalid groupBy', async () => {
    const res = await GET(new Request('http://x/r?groupBy=banana'))
    expect(res.status).toBe(400)
  })
})
```

**Step 2: Implement route**

```ts
// SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/risk-concentration/route.ts
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const GROUPABLE = {
  tape_label: 'l.tape_label',
  trade_type: 'l.trade_type',
  venue: 'l.venue',
  ccp: 'l.ccp',
  session: 'l.execution_session',
  tenor: 'l.tenor_label',
  rate_index: 'l.rate_index_clean',
  fomc_meeting: 'l.fomc_meeting_label',
} as const

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const groupBy = searchParams.get('groupBy') ?? 'tape_label'
  if (!(groupBy in GROUPABLE)) {
    return NextResponse.json({ error: `invalid groupBy: ${groupBy}` }, { status: 400 })
  }
  const date = searchParams.get('date') ?? new Date().toISOString().slice(0, 10)
  const clean = searchParams.get('clean') === 'true'
  const expr = GROUPABLE[groupBy as keyof typeof GROUPABLE]
  const whereClean = clean
    ? ' AND NOT l.is_unwind AND NOT l.is_compression AND NOT l.is_ufro AND NOT l.is_reset_optimization'
    : ''
  try {
    const result = await query(`
      SELECT ${expr} AS value,
             COUNT(*)::int AS trade_count,
             SUM(l.risk)::float AS total_dv01,
             SUM(l.notional)::float AS total_notional
      FROM arbs_usd_swap_tape_legs_v1 l
      WHERE l.as_of_date = $1::date
      ${whereClean}
        AND ${expr} IS NOT NULL
      GROUP BY ${expr}
      ORDER BY ABS(SUM(l.risk)) DESC NULLS LAST
      LIMIT 30
    `, [date])
    return NextResponse.json({ groups: result.rows })
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || 'failed' }, { status: 500 })
  }
}
```

**Step 3: Run tests; commit**

```bash
cd SDRUtils/dashboard && npm run test -- --testPathPatterns=risk-concentration
git add -A && git commit -m "feat(api): risk-concentration aggregation endpoint"
```

---

### Task 11: Packages route

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/packages/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/packages/__tests__/route.test.ts`

**Step 1: Test**

```ts
describe('GET /packages', () => {
  it('returns packages sorted by abs(total_risk)', async () => {
    mockQuery.mockResolvedValue({ rows: [
      { package_id: 'P1', package_structure: '2Y/5Y/10Y Curve', total_risk: 500_000, ... },
    ]} as any)
    const res = await GET(new Request('http://x/p?date=2026-04-14'))
    const body = await res.json()
    expect(body.packages[0].package_id).toBe('P1')
  })
})
```

**Step 2: Implement**

SQL:
```sql
SELECT package_id, package_structure, trade_type, n_package_legs, total_risk,
       total_notional, rate_index_clean, tape_label, execution_start
FROM arbs_usd_swap_tape_packages_v1
WHERE as_of_date = $1::date
  AND package_type != 'OUTRIGHT'            -- packages view focuses on multi-leg
ORDER BY ABS(total_risk) DESC NULLS LAST
LIMIT 100
```

Support `?sortBy=risk|notional|time|legs` and `?limit=` (max 500).

**Step 3: Tests green; commit**

```bash
git add -A && git commit -m "feat(api): packages sidecar endpoint"
```

---

### Task 12: FOMC clusters route

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/fomc-clusters/route.ts`
- Create: sibling `__tests__/route.test.ts`

**Step 1: Test — empty response when no FOMC trades**

```ts
it('returns empty array when no FOMC-dated trades', async () => {
  mockQuery.mockResolvedValue({ rows: [] } as any)
  const res = await GET(new Request('http://x/f?date=2026-04-14'))
  expect((await res.json()).meetings).toEqual([])
})

it('aggregates per fomc_meeting_label', async () => {
  mockQuery.mockResolvedValue({ rows: [
    { fomc_meeting_label: 'APR26', trade_count: 50, net_risk: 120_000, gross_notional: 5e9, has_multi_meeting_flow: false },
  ]} as any)
  const res = await GET(new Request('http://x/f?date=2026-04-14'))
  expect((await res.json()).meetings[0].fomc_meeting_label).toBe('APR26')
})
```

**Step 2: Implement** — SQL aggregates `GROUP BY fomc_meeting_label` over `tape_legs` with `is_fomc_dated = TRUE`. Compute `has_multi_meeting_flow` via `BOOL_OR(is_multi_meeting_cluster)`. Attach `meeting_date` via the FOMC schedule from `SDRUtils.analytics.fomc.load_fomc_schedule` — a small in-Node lookup table populated at API-build time (or a second query against `fomc_meetings` if such a table exists; if not, return `null` for `meeting_date` in v1 and file a follow-up).

**Step 3: Tests green; commit**

```bash
git add -A && git commit -m "feat(api): fomc-clusters sidecar endpoint"
```

---

### Task 13: Temporal clusters route

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/clusters/route.ts`
- Create: sibling `__tests__/route.test.ts`

**Step 1: Test + implement**

Returns clusters sorted by `start_ts`:

```sql
SELECT cluster_id,
       MIN(execution_timestamp) AS start_ts,
       MAX(execution_timestamp) AS end_ts,
       COUNT(*)::int AS trade_count,
       SUM(risk)::float AS total_risk,
       array_agg(DISTINCT tape_label ORDER BY tape_label) FILTER (WHERE tape_label IS NOT NULL) AS tape_labels
FROM arbs_usd_swap_tape_legs_v1
WHERE as_of_date = $1::date AND cluster_id IS NOT NULL
GROUP BY cluster_id
ORDER BY MIN(execution_timestamp)
```

Truncate `tape_labels` to top 5 before serialization.

**Step 2: Commit**

```bash
git add -A && git commit -m "feat(api): temporal clusters timeline endpoint"
```

---

### Task 14: Port flow-history + timeseries routes

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/flow-history/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/timeseries/route.ts`
- Create: sibling `__tests__/route.test.ts` files

**Step 1: Copy existing routes verbatim**

```bash
cp -r SDRUtils/dashboard/src/app/api/sofr-swaps-tape/flow-history \
      SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/
cp -r SDRUtils/dashboard/src/app/api/sofr-swaps-tape/timeseries \
      SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/
```

**Step 2: Rewrite any hardcoded view/table names to the v1 tape objects**

Global search each file for `arbs_usd_swap_display_items_v3`, `arbs_usd_swap_display_items_v4`, `arbs_usd_swap_packages_v2`, `arbs_usd_swap_legs_v2`; replace with `arbs_usd_swap_tape_display_v1`, `arbs_usd_swap_tape_packages_v1`, `arbs_usd_swap_tape_legs_v1` respectively.

**Step 3: Extend timeseries with `groupBy` param**

Accept `groupBy=package|tape_label|trade_type|tenor` and `value=<key>`. Default `groupBy=package` (current behavior). For `tape_label`, aggregate over all trades whose `tape_label = value`.

**Step 4: Tests**

At minimum: one test per route asserting 200 + expected response shape, plus one test asserting the new `groupBy=tape_label` path on timeseries.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat(api): port flow-history + timeseries to tape v2, add groupBy"
```

---

### Task 15: Manual-link endpoint re-exports

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/merge/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/unmerge/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/comment/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/tags/route.ts`

Each file is a single-line re-export:

```ts
// merge/route.ts
export { POST } from '../../sofr-swaps-tape/merge/route'
```

Confirm that existing sofr-swaps-tape POST handlers don't hardcode the view name in a way that breaks — they operate on `arbs_usd_swap_manual_links_v2` and `arbs_usd_swap_legs_v2` for manual `linked_trade_ids` validation. Since the tape ingest shares `trade_id`s with the legacy legs table, validation continues to work.

If a handler DOES hardcode a view name we don't want (e.g., joins to `arbs_usd_swap_display_items_v4` for name resolution), copy and adapt instead of re-export for that one route.

Commit:

```bash
git add -A && git commit -m "feat(api): tape v2 manual-link endpoints (re-export)"
```

---

### Task 16: Integration test — exercise every route against a real test DB

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/integration.test.ts`

**Step 1: Write an integration test** that:

- Uses the Node `pg` driver directly against a test Postgres (gate with `describe.skipIf(!process.env.PG_TEST_URL)`).
- Seeds the tape tables with ~20 rows using `tests/fixtures/tape_lifecycle_fixtures.py`-equivalent SQL inserts.
- Calls each route via `GET` handler directly with a `Request` object.
- Asserts response codes + row shape basics (no schema drift).

**Step 2: Run; commit**

```bash
cd SDRUtils/dashboard && PG_TEST_URL=... npm run test -- --testPathPatterns=integration
git add -A && git commit -m "test(api): integration suite for tape v2 endpoints"
```

---

### Task 17: Phase B checkpoint — curl every endpoint

**Files:** none.

**Step 1: Start the dev server**

```
cd SDRUtils/dashboard && npm run dev
```

**Step 2: Verify each endpoint returns 200 with expected shape**

```bash
curl -s "http://localhost:3000/api/usd-swaps-tape-v2?limit=5" | jq '.rows[0] | keys'
curl -s "http://localhost:3000/api/usd-swaps-tape-v2?clean=true&limit=5" | jq '.rows | length'
curl -s "http://localhost:3000/api/usd-swaps-tape-v2/risk-concentration?groupBy=tape_label" | jq '.groups[0]'
curl -s "http://localhost:3000/api/usd-swaps-tape-v2/packages?date=2026-04-14" | jq '.packages[0]'
curl -s "http://localhost:3000/api/usd-swaps-tape-v2/fomc-clusters?date=2026-04-14" | jq '.meetings'
curl -s "http://localhost:3000/api/usd-swaps-tape-v2/clusters?date=2026-04-14" | jq '.clusters[0]'
curl -s "http://localhost:3000/api/usd-swaps-tape-v2/flow-history?date=2026-04-14" | jq '.days[0]'
curl -s "http://localhost:3000/api/usd-swaps-tape-v2/timeseries?groupBy=tape_label&value=USD-SOFR-COMPOUND%201D%20Spot%205Y%20Outright&metric=risk&view=INTRADAY&range=1D" | jq '.points[0]'
```

Each should return 200 with populated payload. Proceed to Phase C on success.

---

## Phase C — Frontend types + hooks

### Task 18: Remaining type files + constants

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/filter.types.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/chart.types.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/link.types.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/sidecar.types.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/index.ts` (export all)

**Step 1: Types**

- `filter.types.ts` — `ColumnFilterMeta` (re-export from PrimeReact), `LifecycleChipState`, `FlagFilterState`, `CategoryFilter`.
- `chart.types.ts` — `TimeseriesMetricKey = 'notional' | 'risk' | 'trade_count' | 'fixed_rate'`; `TimeseriesViewKey = 'INTRADAY' | 'DAILY_CLOSE' | 'DAILY_OHLC'`; `TimeseriesPoint`, `OhlcPoint`.
- `link.types.ts` — re-export `ManualLink` from `@/features/sofr-swaps-tape/types`.
- `sidecar.types.ts` — `RiskConcentrationGroup`, `PackageSummary`, `FomcMeeting`, `TemporalCluster`.

**Step 2: Constants** — transcribe from design doc §3 §5.2 §8.3 (full `COLUMN_DEFS`, `TRADE_TYPE_TONES`, `FLAG_CHIP_TONES`, `LIFECYCLE_TONES`, `POLL_INTERVAL_MS`, `ROW_ESTIMATE_PX`, `EMPTY_VALUE`, `TIMESERIES_METRICS`, `TIMESERIES_VIEWS`).

**Step 3: Commit**

```bash
git add -A && git commit -m "feat(tape-v2): types + constants (colors, column defs, metrics)"
```

---

### Task 19: `useTradeTapeData` hook

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts`
- Create: sibling `useTradeTapeData.test.ts`

**Step 1: Write tests covering**

- Initial fetch returns rows + cursor.
- `since` poll upserts new rows by package_id without duplicating.
- Pagination via `cursor` appends rows.
- Abort on filter-param change.
- Error states: initial / poll / pagination.

**Step 2: Copy `features/swaptions-tape/hooks/useTradeTapeData.ts` as the starting point**

Adjust:

- Endpoint: `/api/usd-swaps-tape-v2`
- Response shape: `UsdSwapTapeResponse`
- Row key for upsert: `package_id` (unchanged).
- Add `flags`, `lifecycle`, `tradeTypes`, `venues`, `ccps`, `sessions`, `rateIndex`, `tenors`, `fomcMeeting`, `clean` to the request-building path (pass through from filter state).

**Step 3: Tests green; commit**

```bash
git add -A && git commit -m "feat(tape-v2): useTradeTapeData hook with cursor+poll+upsert"
```

---

### Task 20: `useColumnFilters` + `useFlagFilters` hooks

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useColumnFilters.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useFlagFilters.ts`
- Tests alongside each.

**Step 1: `useColumnFilters`** — copy from swaption; extend `SERVER_FILTER_FIELDS` to the extended set (task 9).

**Step 2: `useFlagFilters`** — new hook.

State shape:

```ts
interface FlagFilterState {
  lifecycle: Set<LifecycleType>           // default: all 9 selected
  tradeTypes: Set<string>                  // default: all
  venues: Set<'D2D'|'D2C'>                 // default: all
  ccps: Set<'LCH'|'CME'>                   // default: all
  sessions: Set<string>                    // default: all
  rateIndex: Set<'SOFR'|'FED_FUNDS'|'OTHER'> // default: all
  tenors: Set<string>                      // default: all
  fomcMeeting: string | null
  clean: boolean                           // default: false
}
```

API:

```ts
const {
  state,
  toggleLifecycle(t: LifecycleType),
  toggleTradeType, toggleVenue, toggleCcp, toggleSession, toggleRateIndex, toggleTenor,
  setFomcMeeting, setClean,
  applyCleanPreset(),   // unchecks UNW/CMP/UFRO/RST/NOVA_TERM/CLR + sets clean=true
  resetAll(),
  queryString,           // URL fragment to append
} = useFlagFilters()
```

State serialized to URL via `useSearchParams`/`router.replace` like `useColumnFilters`.

**Test** — toggle → URL round-trip; `applyCleanPreset` flips the expected set and sets `clean=true`.

**Step 3: Commit**

```bash
git add -A && git commit -m "feat(tape-v2): useColumnFilters + useFlagFilters (URL-synced)"
```

---

### Task 21: Row expansion + selection + saved-user hooks

**Files:**
- Create: `useRowExpansion.ts`, `useRowSelection.ts`, `useSavedUser.ts` (copy from swaption verbatim).

Test: `useRowExpansion` stores expanded state by `package_id` and survives rerender.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): row expansion / selection / saved-user hooks"
```

---

### Task 22: Manual-link + timeseries hooks (ports)

**Files:**
- Create: `useManualLinks.ts` (port from swaption, point endpoints at `/api/usd-swaps-tape-v2/{merge,unmerge,comment,tags}`).
- Create: `useTimeseriesData.ts` (port; add `groupBy`/`value` params to the fetch).

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): useManualLinks + useTimeseriesData ports"
```

---

### Task 23: New sidecar hooks

**Files:**
- Create: `useRiskConcentration.ts`, `usePackageBrowser.ts`, `useFomcClusters.ts`, `useTemporalClusters.ts`.

Each hook signature:

```ts
function useRiskConcentration(opts: {
  date: string
  groupBy: keyof typeof GROUPABLE
  flagFilters: FlagFilterState
}): { data: RiskConcentrationGroup[] | null; isLoading: boolean; error: Error | null; refetch: () => void }
```

Patterns follow `useTradeTapeData`: `AbortController`, debounce 150 ms when filter changes, re-query on `POLL_INTERVAL_MS` timer.

**Step 1: Implement + tests**

**Step 2: Commit**

```bash
git add -A && git commit -m "feat(tape-v2): sidecar data hooks (risk concentration, packages, fomc, clusters)"
```

---

### Task 24: Barrel — `hooks/index.ts`

```ts
export { useTradeTapeData } from './useTradeTapeData'
export { useColumnFilters } from './useColumnFilters'
export { useFlagFilters } from './useFlagFilters'
export { useRowExpansion } from './useRowExpansion'
export { useRowSelection } from './useRowSelection'
export { useSavedUser } from './useSavedUser'
export { useManualLinks } from './useManualLinks'
export { useTimeseriesData } from './useTimeseriesData'
export { useRiskConcentration } from './useRiskConcentration'
export { usePackageBrowser } from './usePackageBrowser'
export { useFomcClusters } from './useFomcClusters'
export { useTemporalClusters } from './useTemporalClusters'
```

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): hooks barrel"
```

---

### Task 25: Utility formatters

**Files:**
- Create: `features/usd-swaps-tape-v2/utils/format.ts` with:
  - `formatNotional(n, { compact?: boolean }): string`
  - `formatDv01(n, { signed?: boolean }): string`
  - `formatRate(n, opts?: { precision?: number }): string`
  - `formatRateRange(min, max): string`
  - `formatTenor(row): string` (respects `tenor_display`)
  - `formatTime(ts): string`
  - `formatClusterSuffix(size): string`

With unit tests for each — null inputs, edge cases (0, very large, negative).

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): number/time/tenor formatters + tests"
```

---

### Task 26: Phase C checkpoint — hook test suite

```bash
cd SDRUtils/dashboard && npm run test -- --testPathPatterns=features/usd-swaps-tape-v2
```

All hook + util tests green. Proceed to Phase D.

---

## Phase D — Frontend main table

### Task 27: `TapeLabelCell` component

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.tsx`
- Create: sibling `TapeLabelCell.test.tsx`

**Step 1: Write tests** — snapshot + DOM queries for:

- Simple outright (SOFR Spot 5Y Outright).
- Off-date (`~` prefix visible).
- FOMC-dated (APR26 chip amber).
- Block (BLK glyph).
- Unwind (UNW glyph).
- Combined: FOMC + block + off-date.

**Step 2: Implement**

```tsx
// TapeLabelCell.tsx
import { LIFECYCLE_TONES, FLAG_CHIP_TONES } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'

type Props = { row: UsdSwapTapeRow }

export function TapeLabelCell({ row }: Props) {
  const indexColor =
    row.rate_index_clean === 'SOFR' ? 'bg-emerald-900/40 text-emerald-200' :
    row.rate_index_clean === 'FED_FUNDS' ? 'bg-amber-900/40 text-amber-200' :
    'bg-slate-800/60 text-slate-300'
  const tenor = row.legs_json?.[0]?.tenor_display ?? row.tenor_label ?? '—'
  const offDate = tenor.startsWith('~')
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap">
      <Chip className={indexColor}>{row.rate_index_clean ?? '—'}</Chip>
      {row.legs_json?.[0]?.upi_reset_freq && (
        <Chip className="bg-zinc-800/70 text-zinc-300">{row.legs_json[0].upi_reset_freq}</Chip>
      )}
      <span className="font-mono text-slate-100">
        {row.is_forward ? row.forward_label : 'Spot'} {offDate && <span className="text-yellow-300">~</span>}{tenor.replace('~','')}
      </span>
      <span className="text-slate-400 text-sm">{structureOf(row)}</span>
      {row.is_fomc_dated && row.fomc_meeting_label && (
        <Chip className="bg-amber-900/40 text-amber-200">⚡ {row.fomc_meeting_label}</Chip>
      )}
      {row.is_block_any && <InlineFlag>BLK</InlineFlag>}
      {row.is_unwind && <InlineFlag className="text-red-300">UNW</InlineFlag>}
      {row.is_ufro_any && <InlineFlag className="text-orange-300">OFF-MKT</InlineFlag>}
    </div>
  )
}
```

`Chip`, `InlineFlag`, `structureOf` are local helpers in the same file.

**Step 3: Tests green; commit**

```bash
git add -A && git commit -m "feat(tape-v2): TapeLabelCell hero component + snapshot tests"
```

---

### Task 28: `RowBadges` + lifecycle pill helpers

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeTable/RowBadges.tsx`
- Create: sibling `RowBadges.test.tsx`

Renders the Lifecycle column body from `row.lifecycle_mix` (pill stack `NEW·UNW·CMP…`) and the Flags column body from `row.is_block_any`, `row.is_ufro_any`, `row.is_capped_any`, `row.is_off_date_any`, plus per-package leg-derived flags.

Tests: snapshot per lifecycle combination; a11y labels present on pills.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): lifecycle + flag badge stack components"
```

---

### Task 29: `LegsSubTable`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeTable/LegsSubTable.tsx`
- Create: sibling test file.

Renders a nested PrimeReact `DataTable` over `row.legs_json` with per-leg columns (leg_order, lifecycle, exec ts, trade_id copy-on-click, tape_label via `TapeLabelCell` variant, tenor_display, notional, risk signed, rate, quality_flags, xd progress).

Tests: 2-leg curve package expands; cross-day progress bar renders when `xd_notional_pct_remaining < 1.0`.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): LegsSubTable for per-package expansion"
```

---

### Task 30: `columns.tsx` — table column definitions

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx`

Exports `getColumns(config)` returning an array of PrimeReact `<Column>` JSX elements. Each column body template uses the formatters + sub-components above. Row-class function maps lifecycle → Tailwind class stack per design §7.2:

```tsx
export function rowClassName(row: UsdSwapTapeRow): string {
  if (row.is_clearing_termination_any) return 'bg-red-950/40 border-l-2 border-red-500'
  if (row.is_unwind)                    return 'bg-red-950/25 text-red-100'
  if (row.is_termination_any && !row.is_compression_any) return 'bg-rose-950/30 text-rose-100'
  if (row.is_compression_any)           return 'bg-zinc-900/40 text-zinc-400 italic'
  if (row.is_novation_any)              return 'bg-purple-950/25 text-purple-100'
  if (row.is_reset_optimization_any)    return 'bg-neutral-900/40 text-neutral-500 text-xs'
  return ''                              // default
}
```

No tests for `columns.tsx` directly — covered by `TradeTapeTable` snapshot later.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): table column definitions + row class mapping"
```

---

### Task 31: `TradeTapeTable` container

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx`
- Create: sibling test with React Testing Library.

Wraps PrimeReact `DataTable` with:

- Virtual scroll (`virtualScrollerOptions={{ itemSize: ROW_ESTIMATE_PX }}`)
- `expandedRows` / `onRowToggle` from `useRowExpansion`
- `selection` / `onSelectionChange` from `useRowSelection`
- `rowExpansionTemplate={row => <LegsSubTable row={row} />}`
- `rowClassName={rowClassName}`
- `scrollable`, `scrollHeight="flex"`, `stripedRows={false}`

Props: `{ rows, loading, onLoadMore, hasMore, ... }`.

Tests: render 10 rows, click expander, assert sub-table visible; apply a row's unwind class.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): TradeTapeTable container with virtual scroll + expansion"
```

---

### Task 32: Phase D checkpoint — render sample data standalone

Create a tiny Storybook-style harness OR a temporary route `/usd-swaps-v2/table-dev` that feeds hard-coded sample rows into `TradeTapeTable`. Verify:

- Lifecycle row treatment renders correctly
- Package expansion works
- Virtual scroll is smooth at 500 rows
- Row class per lifecycle matches design §7.2

After manual verification, delete the temporary harness (or keep under `__dev__/`). Commit.

```bash
git add -A && git commit -m "test(tape-v2): manual harness confirms table + row treatment"
```

---

## Phase E — Header + filters

### Task 33: `CleanTapeToggle` + `FlagChips`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeHeader/CleanTapeToggle.tsx`
- Create: `features/usd-swaps-tape-v2/components/TradeTapeHeader/FlagChips.tsx`
- Sibling tests.

`CleanTapeToggle` — button bound to `useFlagFilters().applyCleanPreset` / `resetAll`; shows current state.

`FlagChips` — renders the Lifecycle pill row (Strip 3, design §8.1). Each pill is a button wired to `toggleLifecycle`. Dimmed when unchecked.

Tests: click pill → mock `toggleLifecycle` called with right arg.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): CleanTapeToggle + FlagChips lifecycle pill row"
```

---

### Task 34: `TradeTapeHeader`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeHeader/TradeTapeHeader.tsx`
- Sibling test.

Three-strip layout per design §8.1.

Props: `{ asOfDate, liveStatus, summary, onRefresh, onOpenFlowHistory, onOpenMethodology }` where `summary` is derived from current tape rows: `{ tradeCount, newRisk, grossDv01, grossNotional, packageCount, clusterCount, lifecycleCounts, rateIndexMix, tenorMix, topTradeType, burstMarker }`.

Each summary stat is a `<button>` that writes a default filter to the URL via props callback.

Tests: click "New Risk" stat → callback with `{ lifecycle: 'new_risk' }`.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): three-strip TradeTapeHeader with clickable summary stats"
```

---

### Task 35: `FilterChips` + `TradeTapeFilters`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/TradeTapeFilters/FilterChips.tsx`
- Create: `features/usd-swaps-tape-v2/components/TradeTapeFilters/TradeTapeFilters.tsx`
- Sibling tests.

`FilterChips` — chip bar for Lifecycle / Trade Type / Venue / CCP / Session / Rate Index. Each chip is a multi-select dropdown (PrimeReact `MultiSelect` styled to match chip aesthetic).

`TradeTapeFilters` — global search input + AND/OR operator toggle + Reset-all button + column-chooser trigger.

Tests: type in search → debounced state update after 250 ms; reset clears everything.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): filter chips + global filters bar"
```

---

### Task 36: Phase E checkpoint — URL round-trip

Manual test:

1. Start dev server, navigate to `/usd-swaps-v2/filters-dev` (temp harness or the real page if already scaffolded).
2. Toggle a Lifecycle pill → URL updates.
3. Reload page → pill state restored.
4. Click "New Risk" summary → lifecycle chip updates to NEW_RISK-only.
5. Click Clean Tape → expected preset applies.

Commit:

```bash
git add -A && git commit -m "test(tape-v2): confirms URL-sync round trip for all filter surfaces"
```

---

## Phase F — Sidecars

### Task 37: Port `TimeseriesChart`

**Files:**
- Copy `features/swaptions-tape/components/TradeTapeCharts/TimeseriesChart.tsx` → `features/usd-swaps-tape-v2/components/TradeTapeCharts/TimeseriesChart.tsx`
- Adjust metric set (see design §9.5).
- Add Group By selector (package / tape_label / trade_type / tenor).
- Wire to `useTimeseriesData` with extra params.
- Port/update tests.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): TimeseriesChart modal port with Group By extension"
```

---

### Task 38: Port `FlowHistoryGrid`

**Files:**
- Copy `features/sofr-swaps-tape/components/flowHistory.utils.ts` verbatim into `features/usd-swaps-tape-v2/components/TradeTapeCharts/flowHistory.utils.ts` (path-only change).
- Create: `features/usd-swaps-tape-v2/components/TradeTapeCharts/FlowHistoryGrid.tsx` — extract the flow-history UI code from `SofrSwapsTradeTape.tsx` into a reusable component.
- Tests.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): FlowHistoryGrid modal port"
```

---

### Task 39: `RiskConcentrationPanel`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/Sidecars/RiskConcentration/RiskConcentrationPanel.tsx`
- Sibling test.

Structure per design §9.1. GroupBy selector pill row; horizontal divergent bar list; clicking a row writes to filter state via a callback prop.

Tests: click row → callback called with `{ groupBy, value }`. Empty state renders when `data` is empty array.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): RiskConcentrationPanel sidecar"
```

---

### Task 40: `PackageBrowserPanel`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/Sidecars/PackageBrowser/PackageBrowserPanel.tsx`
- Sibling test.

Virtualized list (`@tanstack/react-virtual`). Sort selector. Package-type chip row. Click card → callback.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): PackageBrowserPanel sidecar"
```

---

### Task 41: `FomcClustersPanel`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/Sidecars/FomcClusters/FomcClustersPanel.tsx`
- Sibling test.

Horizontal strip of meeting cards per design §9.3. Empty-state when no FOMC trades. Click → callback.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): FomcClustersPanel sidecar"
```

---

### Task 42: `ClusterTimelineStrip`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/Sidecars/TemporalClusterTimeline/ClusterTimelineStrip.tsx`
- Sibling test.

SVG-based horizontal strip (height 48px). Each cluster bar: x = midpoint, width = duration, height = log(trade_count). Hover tooltip (PrimeReact Tooltip). Brushed-range selector via `onMouseDown`/`onMouseMove`/`onMouseUp`. Click → callback with `cluster_id`.

Tests: 3 clusters render; brush range fires `onRangeChange`.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): ClusterTimelineStrip (SVG) with hover + brush"
```

---

### Task 43: `ManualLinksDialog` port

**Files:**
- Copy from swaption feature dir (`ManualLinksDialog`).
- Adjust endpoint paths to `/api/usd-swaps-tape-v2/{merge,unmerge,comment,tags}`.
- Tests.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): ManualLinksDialog modal port"
```

---

## Phase G — Orchestration + cutover

### Task 44: `UsdSwapsMethodologyModal`

**Files:**
- Create: `features/usd-swaps-tape-v2/components/UsdSwapsMethodologyModal.tsx`

Short markdown-esque content explaining:
- TradeTape enrichment summary (classification, lifecycle, quality, package, FOMC, clustering)
- What `clean_tape()` hides
- Tape label composition
- Link to design doc in repo

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): methodology modal"
```

---

### Task 45: `UsdSwapsTradeTape` main container

**Files:**
- Create: `features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx`
- Create: `features/usd-swaps-tape-v2/index.ts`

Composition per design §6:

```tsx
'use client'
import { Suspense, useState } from 'react'
import { TradeTapeHeader } from './TradeTapeHeader/TradeTapeHeader'
import { FilterChips } from './TradeTapeFilters/FilterChips'
import { TradeTapeFilters } from './TradeTapeFilters/TradeTapeFilters'
import { ClusterTimelineStrip } from './Sidecars/TemporalClusterTimeline/ClusterTimelineStrip'
import { TradeTapeTable } from './TradeTapeTable/TradeTapeTable'
import { SidecarDrawer } from './Sidecars/SidecarDrawer'
import { useColumnFilters, useFlagFilters, useRowExpansion, useRowSelection, useTradeTapeData, ... } from '../hooks'
import { TimeseriesChart } from './TradeTapeCharts/TimeseriesChart'
import { FlowHistoryGrid } from './TradeTapeCharts/FlowHistoryGrid'
import { ManualLinksDialog } from './ManualLinksDialog/ManualLinksDialog'
import { UsdSwapsMethodologyModal } from './UsdSwapsMethodologyModal'

export default function UsdSwapsTradeTape() {
  const flagFilters = useFlagFilters()
  const columnFilters = useColumnFilters()
  const expansion = useRowExpansion()
  const selection = useRowSelection()
  const tape = useTradeTapeData({ flagFilters, columnFilters })
  const [activeModal, setActiveModal] = useState<'timeseries'|'flow-history'|'links'|'methodology'|null>(null)
  const [activeSidecar, setActiveSidecar] = useState<'risk'|'packages'|'fomc'|null>('risk')
  const [timelineVisible, setTimelineVisible] = useState(true)
  // wire cross-panel interactions via flagFilters/columnFilters setters
  // ...
  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100">
      <TradeTapeHeader /* ... */ />
      <FilterChips /* ... */ />
      <TradeTapeFilters /* ... */ />
      {timelineVisible && <ClusterTimelineStrip /* ... */ />}
      <div className="flex flex-1 overflow-hidden">
        <TradeTapeTable
          rows={tape.rows}
          loading={tape.isLoading}
          onLoadMore={tape.loadMore}
          hasMore={tape.hasMore}
          expansion={expansion}
          selection={selection}
          onOpenTimeseries={row => setActiveModal('timeseries')}
        />
        {activeSidecar && (
          <SidecarDrawer active={activeSidecar} onChange={setActiveSidecar} flagFilters={flagFilters} />
        )}
      </div>
      {activeModal === 'timeseries' && <TimeseriesChart onClose={() => setActiveModal(null)} />}
      {activeModal === 'flow-history' && <FlowHistoryGrid onClose={() => setActiveModal(null)} />}
      {activeModal === 'links' && <ManualLinksDialog onClose={() => setActiveModal(null)} />}
      {activeModal === 'methodology' && <UsdSwapsMethodologyModal onClose={() => setActiveModal(null)} />}
    </div>
  )
}
```

Also create `Sidecars/SidecarDrawer.tsx` — host for the four drawer sidecars (everything except the full-width timeline).

`index.ts`:
```ts
export { default } from './components/UsdSwapsTradeTape'
export * from './types'
```

Target main-container size ≤900 lines.

Commit:

```bash
git add -A && git commit -m "feat(tape-v2): main orchestrator + SidecarDrawer"
```

---

### Task 46: Parallel route `/usd-swaps-v2`

**Files:**
- Create: `SDRUtils/dashboard/src/app/usd-swaps-v2/page.tsx`

```tsx
import { Suspense } from 'react'
import UsdSwapsTradeTape from '@/features/usd-swaps-tape-v2'

export default function UsdSwapsV2Page() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading tape…</div>}>
      <UsdSwapsTradeTape />
    </Suspense>
  )
}
```

Add a banner link on `/usd-swaps` page: `"Try the new tape →"` pointing to `/usd-swaps-v2`.

```bash
git add -A && git commit -m "feat(tape-v2): parallel /usd-swaps-v2 route + banner on legacy page"
```

---

### Task 47: Puppeteer E2E

**Files:**
- Create: `SDRUtils/dashboard/__tests__/e2e/usd-swaps-v2.e2e.ts`

Scenarios from design §12.3:

- `/usd-swaps-v2` loads, first row visible within 5s.
- At least one row per lifecycle type is present when full data loaded (seed test DB via SQL before run).
- Click "Clean Tape" → row count drops; Lifecycle pills dim; URL contains `?clean=true`.
- Click APR26 FOMC card → table filters; URL contains `fomcMeeting=APR26`.
- Expand a package row → legs subtable visible.
- Open Timeseries modal from row action → chart renders; switch metric.
- Keyboard `/` focuses global search.

Run: `cd SDRUtils/dashboard && npm run test:e2e`.

```bash
git add -A && git commit -m "test(tape-v2): puppeteer E2E for golden paths"
```

---

### Task 48: Cutover + cleanup

**Files:**
- Modify: `SDRUtils/dashboard/src/app/usd-swaps/page.tsx` — change import to `@/features/usd-swaps-tape-v2`.
- Modify: `SDRUtils/dashboard/src/app/sofr-swaps/page.tsx` — ensure still redirects to `/usd-swaps`.
- Modify: `SDRUtils/dashboard/src/app/usd-swaps-v2/page.tsx` — redirect to `/usd-swaps` once cutover complete.

**Trader UAT checklist must be fully checked off (design §12.4) before running this task.**

```bash
git add -A && git commit -m "chore(tape-v2): cutover — /usd-swaps now serves the v2 tape"
```

**Follow-up (separate PR, not this plan):**

- Delete `features/sofr-swaps-tape/`
- Delete `features/usd-swaps-tape/`
- Delete `/api/sofr-swaps-tape/`
- Delete `/api/usd-swaps-tape/`
- File any TODOs surfaced during UAT

---

## Done.

Every task above is a 2–5 minute unit plus test plus commit. The implementation is chunked so each phase ends on a working state you can demo. If any step's output surprises you, stop and review before proceeding — do not plow through failing tests.
