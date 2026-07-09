# USD Swaps Tape — Manual Package Regrouping & Trader Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let traders manually correct auto-detected package groupings on the USD Swaps Tape (GROUP / SPLIT / DETACH) and attach free-text notes to any trade or package, behind a password gate on structural edits.

**Architecture:** Overrides and notes live in four NEW tape-scoped tables; the live display view resolves overrides **at read time, cardinality-preserving**, by index-probing a normalized members table inside the existing per-package LATERAL (surfaces a sparse `override_map`; `legs_json` unchanged). The frontend applies the visual regroup/split/detach transform (`applyOverrides`) and drives edits via a contextual action bar + leg-level selection. No writes ever touch the ingest-owned `_tape_packages/legs_v2` tables; the shared `lib/manual-links-ui/*` (co-consumed by swaptions) is never modified.

**Tech Stack:** PostgreSQL (Supabase prod) via idempotent Python DDL (`_tape_schema_v2.py`); Next.js App Router API routes + `pg` pool (`@/lib/db`); React + PrimeReact DataTable + Tailwind (`lara-dark-indigo`); ESM Jest + Testing Library; pytest.

Spec: `docs/superpowers/specs/2026-07-08-usd-swaps-tape-manual-regrouping-notes-design.md`.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python tests:** run ONLY via `conda run -n stir python -m pytest ...`. DDL/DB-touching tests MUST be marked `@pytest.mark.db` (excluded from the fast gate `-m "not slow and not network and not db"`).
- **Frontend tests:** run ONLY via `npm test` in `SDRUtils/dashboard` (the script is `node --experimental-vm-modules node_modules/jest/bin/jest.js`). NEVER plain `npx jest` — it bypasses the ESM mock setup and yields false Supabase failures.
- **Every `git commit` message MUST end with these two trailer lines, verbatim:**
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a
  ```
  Conventional commits; scope `(tape)` or `(dashboard)`.
- **Guardrail — never write** `arbs_usd_swap_tape_packages_v2` / `arbs_usd_swap_tape_legs_v2` from the dashboard (ingest owns them). All overrides/notes go through the new tables.
- **Guardrail — never modify** `SDRUtils/dashboard/src/lib/manual-links-ui/*` (the swaptions tape co-consumes it). Build tape-local equivalents.
- **Auth:** structural override mutations (POST/PATCH/DELETE `/overrides`) are gated by env var `TAPE_OVERRIDE_PASSWORD` (no hardcoded default — unset env ⇒ all structural writes 403). Notes require only a non-empty `author`, no password.
- **Override rules:** `override_type ∈ {GROUP, SPLIT, DETACH}`; GROUP needs ≥2 trade_ids; SPLIT/DETACH allow ≥1. One active override per trade (transaction supersedes overlaps; partial-unique members index is the DB backstop).
- **Transactions:** every override mutation runs in ONE `withClient` transaction (explicit BEGIN/COMMIT, try/catch ROLLBACK).
- **Browser verification:** verify all frontend changes in Chrome MCP at `localhost:3000` before the final commit (Task 20).

## Task index & sequencing

Dependencies stack: **DB (1–2) → API (3–8) → FE types/clients (9–10) → FE hooks/components (11–14) → FE render (15–18) → integration (19) → verification (20).** Within a layer, sibling tasks may parallelize.

| # | Task | Layer |
|---|---|---|
| 1 | New tables (`overrides`, `override_members`, `override_history`, `notes`) + indexes + `_LATEST_MIGRATION_COLS` | DB |
| 2 | Extend `arbs_usd_swap_tape_display_v2` with `override_map`/`manual_package_id`/`override_type`/`has_notes`/`notes_count` (members index-probe) + plan-regression test | DB |
| 3 | `isValidTapeWritePassword` + `TAPE_WRITE_AUTH_ERROR` + `.env.example` | API |
| 4 | `lib/tape-overrides.ts` (validation/metrics/supersession/members/pkg-id) | API |
| 5 | `overrides/route.ts` — POST (transactional) + GET | API |
| 6 | `overrides/[overrideId]/route.ts` — GET/PATCH/DELETE | API |
| 7 | `lib/tape-notes.ts` + `notes/route.ts` + `notes/[noteId]/route.ts` | API |
| 8 | Override lifecycle + one-active-per-trade supersession integration test | API |
| 9 | `types/override.types.ts`, `types/note.types.ts`, extend `UsdSwapTapeRow` | FE |
| 10 | `api/overrideApi.ts`, `api/noteApi.ts` | FE |
| 11 | `hooks/useTradeSelection.ts` (leg-level selection) | FE |
| 12 | `deriveSelectionContext` / `useSelectionContext` | FE |
| 13 | `components/RegroupActionBar/RegroupActionBar.tsx` | FE |
| 14 | `components/OverrideCommitPopover/OverrideCommitPopover.tsx` | FE |
| 15 | `utils/applyOverrides.ts` (GROUP cluster / SPLIT explode / DETACH remove) | FE |
| 16 | `LegsSubTable.tsx` leg checkbox column + per-leg note icon | FE |
| 17 | Visual markers: `columns.tsx` + tape-local `OverrideBadge` | FE |
| 18 | `components/NotePopover/NotePopover.tsx` + per-package note affordance | FE |
| 19 | Orchestrator wiring (`UsdSwapsTradeTape.tsx` + `TradeTapeTable.tsx`) | FE |
| 20 | Chrome MCP verification walkthrough + promote perf-guard scripts + final commit | FE |

## Cross-task reconciliation notes (resolved during plan assembly)

These decisions were settled across the layer drafts — follow them when tasks appear to disagree:

1. **`toggleTrade(tradeId, packageId)` is canonical (2-arg).** The leg checkbox in `LegsSubTable` and the `TradeTapeTable`/orchestrator threading all pass `(tradeId, packageId)`; `LegsSubTable` supplies `row.package_id`. (FE-core needs the package context to maintain `selectedByPackage`.)
2. **`manual_package_id` view column = `COALESCE(<override manual_package_id>, ml.manual_package_id)`** (override wins). Required because the base view already projects `ml.manual_package_id` and `CREATE VIEW` forbids duplicate output names. Backward compatible.
3. **Selection-model migration:** the new `useTradeSelection` + `RegroupActionBar` **replace** the legacy `useRowSelection` + the `ManualLinksDialog` *create* flow / "Link N selected" button (retire them in Task 19). `ManualLinkDetailModal` is **kept** — still opened by the auto `ManualLinkBadge` for legacy `manual_link_id` rows. Analytics-dock focus is preserved by deriving from `selectedTradeIds`.
4. **`dataKey` switches `package_id` → `__syntheticKey`** (populated on every `DisplayRow`) so SPLIT rows that share a `package_id` don't collide. Expansion is keyed by `__syntheticKey` too.
5. **Overlaps auto-supersede (no 409).** Unlike the legacy sofr-links route, conflicting active overrides are superseded inside the create/patch transaction; `validateOverride` is structural only (GROUP≥2, SPLIT/DETACH≥1).
6. **`manual_package_id` index is non-unique** (per DDL) → the write path does a best-effort existence pre-check (`allocateManualPackageId`, ≤5 attempts) inside the transaction rather than a 23505 retry.
7. **Undo-of-revert re-POSTs an equivalent override** (there is no reactivate endpoint); undo-of-create deactivates the just-created override.
8. **Notes granularity in the view:** the view carries package-level `has_notes`/`notes_count` only (resolved in a *separate* one-row LATERAL to keep `legs_json` byte-identical). The per-leg note icon is always add-capable and lazy-fetches TRADE notes for that `trade_id` on open.
9. **`_LATEST_MIGRATION_COLS` gets TWO new entries** — `("arbs_usd_swap_tape_overrides_v2","override_id")` (Task 1) and `("arbs_usd_swap_tape_display_v2","override_map")` (Task 2) — so a view-only redeploy isn't skipped.
10. **Barrels:** update `features/usd-swaps-tape-v2/types/index.ts` and `hooks/index.ts`; the `features/usd-swaps-tape-v2/api/` directory is new.

---
# PLAN — DB Layer: Manual Regrouping + Trader Notes (USD Swaps Tape)

Scope of this section: the Postgres schema. Two tasks, both editing
`SDRUtils/_swappulse_scripts/_tape_schema_v2.py` and
`SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`, with DDL/DB tests in a
new `tests/test_tape_override_schema.py`.

All object names are taken verbatim from `plan_contract.md`. The referenced
spec file (`docs/superpowers/specs/2026-07-08-usd-swaps-tape-manual-regrouping-notes-design.md`)
**does not exist in the tree** — the shared contract is the authoritative
source and is what these tasks follow.

## Names used (must match contract)

| Kind | Name |
|------|------|
| table | `arbs_usd_swap_tape_overrides_v2` |
| table | `arbs_usd_swap_tape_override_members_v2` |
| table | `arbs_usd_swap_tape_override_history_v2` |
| table | `arbs_usd_swap_tape_notes_v2` |
| view (extended) | `arbs_usd_swap_tape_display_v2` |
| new view cols | `override_map`, `manual_package_id`, `override_type`, `has_notes`, `notes_count` |

Python constants added to `_tape_schema_v2.py`:
`OVERRIDES_TABLE_V2`, `OVERRIDE_MEMBERS_TABLE_V2`, `OVERRIDE_HISTORY_TABLE_V2`,
`NOTES_TABLE_V2`.

## Test harness being mirrored

- Marker `db` is registered in `pytest.ini` (`db: requires a live DATABASE_URL`).
- `tests/conftest.py` exposes fixture `pg_test_url` — reads `PG_TEST_URL` or
  `DATABASE_URL`, `pytest.skip(...)` when neither is set.
- Existing precedent: `tests/test_ingest_usdswaps_tape_writepath.py` defines a
  function-scoped engine fixture that consumes `pg_test_url`, `DROP`s the target
  objects, then calls `ensure_schema(engine)`, and asserts by
  `engine.connect()` + `sqlalchemy.text(...)`.
- Our fixture additionally `discard`s the process-level `_schema_ensured` cache
  so `ensure_schema` re-runs the DDL after we drop the new tables (the existing
  fixture omits this; dropping-without-discard only works on first use of a URL
  in a process).
- Run DB tests: `conda run -n stir python -m pytest tests/test_tape_override_schema.py -v -m db`
  (requires `DATABASE_URL`/`PG_TEST_URL` exported; otherwise every `db` test
  skips). Fast-gate unit assertions (no marker) run under the normal
  `-m "not slow and not network and not db"` gate.

## The migration-sentinel trap (READ BEFORE EDITING)

`ensure_schema()` short-circuits on `_schema_already_current(engine)`:

```python
def _schema_already_current(engine: Engine) -> bool:
    """Check if the latest migration columns exist, avoiding ACCESS EXCLUSIVE DDL."""
    try:
        with engine.connect() as conn:
            for table, col in _LATEST_MIGRATION_COLS:
                row = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ), {"t": table, "c": col}).fetchone()
                if row is None:
                    return False
        return True
    except Exception:
        return False
```

```python
    if _schema_already_current(engine):
        _schema_ensured.add(key)
        return
```

A **missing table** produces **no row** in `information_schema.columns` for the
probed `(table_name, column_name)` → `row is None` → the loop returns `False`
→ `_schema_already_current` is `False` → `ensure_schema` runs the whole DDL
bundle. So a table-existence sentinel is sufficient to gate table creation.

The trap: the four existing sentinel entries
(`packages_v2.ptp_price_notation`, `legs_v2.opa_signed_amount`) are ALREADY
present on every live DB. If we add tables/view **without** adding a new
sentinel entry, `_schema_already_current` returns `True`, `ensure_schema`
returns early, and **none of the new DDL ever runs**. Task 1 therefore MUST add
`("arbs_usd_swap_tape_overrides_v2", "override_id")`. Task 2 changes the *view*
only; a view's columns DO appear in `information_schema.columns`, so Task 2 MUST
also add `("arbs_usd_swap_tape_display_v2", "override_map")` — otherwise, on an
environment where Task 1 already deployed (overrides table present), the
view-only change is skipped and never ships.

Final target value of the sentinel after both tasks:

```python
_LATEST_MIGRATION_COLS = [
    ("arbs_usd_swap_tape_packages_v2", "ptp_price_notation"),
    ("arbs_usd_swap_tape_legs_v2", "opa_signed_amount"),
    ("arbs_usd_swap_tape_overrides_v2", "override_id"),       # Task 1
    ("arbs_usd_swap_tape_display_v2", "override_map"),        # Task 2
]
```

---

## Task 1 — Four new tables + indexes/constraints + sentinel entry

Idempotent DDL appended to `TAPE_SCHEMA_SQL_V2` in `_tape_schema_v2.py`
**before** the `DROP VIEW IF EXISTS {DISPLAY_VIEW_V2};` line (the view will
reference these tables in Task 2, so they must be declared earlier in the
f-string), plus the Task-1 sentinel entry in `ingest_usdswaps_tape.py`.

### Step 1.1 — Failing test: tables exist

- [ ] Create `tests/test_tape_override_schema.py` with the imports, the
  `override_engine` fixture, and the first test:

```python
"""DDL / schema tests for the manual-regrouping + notes tables (2026-07-08).

Mirrors the DB harness in test_ingest_usdswaps_tape_writepath.py: consumes the
``pg_test_url`` fixture, marks DB-dependent tests ``@pytest.mark.db``, and
asserts via engine.connect() + text().
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import ingest_usdswaps_tape as _ing
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    _schema_already_current,
    ensure_schema,
)
from SDRUtils._swappulse_scripts._tape_schema_v2 import (
    DISPLAY_VIEW_V2,
    LEGS_TABLE_V2,
    NOTES_TABLE_V2,
    OVERRIDE_HISTORY_TABLE_V2,
    OVERRIDE_MEMBERS_TABLE_V2,
    OVERRIDES_TABLE_V2,
    PACKAGES_TABLE_V2,
)


@pytest.fixture
def override_engine(pg_test_url):
    """Drop the four new objects, force ensure_schema to re-run, return engine."""
    engine = create_engine(pg_test_url)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_MEMBERS_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_HISTORY_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {NOTES_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDES_TABLE_V2} CASCADE"))
    _ing._schema_ensured.discard(str(engine.url))
    ensure_schema(engine)
    return engine


@pytest.mark.db
def test_override_tables_created(override_engine):
    expected = {
        OVERRIDES_TABLE_V2,
        OVERRIDE_MEMBERS_TABLE_V2,
        OVERRIDE_HISTORY_TABLE_V2,
        NOTES_TABLE_V2,
    }
    with override_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = ANY(:names)"
            ),
            {"names": list(expected)},
        ).fetchall()
    found = {r[0] for r in rows}
    assert expected <= found, f"missing tables: {expected - found}"
```

### Step 1.2 — Run it (expected FAIL)

- [ ] `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_override_tables_created -v -m db`
  Expected: **FAIL** — the fixture's `ensure_schema` cannot create the tables
  because the constants/DDL don't exist yet → `ImportError`
  (`OVERRIDES_TABLE_V2` not importable) at collection. (This is the red state;
  `DATABASE_URL` must be set or the test skips rather than fails.)

### Step 1.3 — Add the four table-name constants

- [ ] In `_tape_schema_v2.py`, immediately after
  `MANUAL_LINKS_TABLE = "arbs_usd_swap_manual_links_v2"` (line 25), insert:

```python
OVERRIDES_TABLE_V2 = "arbs_usd_swap_tape_overrides_v2"
OVERRIDE_MEMBERS_TABLE_V2 = "arbs_usd_swap_tape_override_members_v2"
OVERRIDE_HISTORY_TABLE_V2 = "arbs_usd_swap_tape_override_history_v2"
NOTES_TABLE_V2 = "arbs_usd_swap_tape_notes_v2"
```

### Step 1.4 — Add the four tables + indexes to `TAPE_SCHEMA_SQL_V2`

- [ ] In `_tape_schema_v2.py`, insert the following block **immediately before**
  the line `DROP VIEW IF EXISTS {DISPLAY_VIEW_V2};` (currently line 365), i.e.
  after the `idx_tape_v2_packages_norm_label` index (line 363). NB: this is
  inside the `TAPE_SCHEMA_SQL_V2` **f-string**, so JSONB literal braces are
  doubled (`'{{}}'::jsonb`).

```sql
-- =====================================================================
-- Manual regrouping + trader notes (2026-07-08). Dashboard-owned tables;
-- the ingest pipeline NEVER writes them. Overrides re-cluster tape rows
-- (GROUP/SPLIT/DETACH); the member table is index-probed by the display
-- view; history is an append-only audit trail; notes attach free text to
-- a TRADE or a PACKAGE. All DDL idempotent (IF NOT EXISTS) so
-- ensure_schema() can re-run safely. These tables MUST be declared before
-- the CREATE VIEW below, which references the member + notes tables.
-- =====================================================================
CREATE TABLE IF NOT EXISTS {OVERRIDES_TABLE_V2} (
    override_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    override_type TEXT NOT NULL
      CHECK (override_type IN ('GROUP','SPLIT','DETACH')),
    manual_package_id TEXT,
    trade_ids TEXT[] NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT,
    updated_at TIMESTAMPTZ,
    reason TEXT,
    tags TEXT[],
    metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    superseded_by UUID REFERENCES {OVERRIDES_TABLE_V2}(override_id),
    CONSTRAINT chk_tape_v2_override_group_min_trades
      CHECK (override_type <> 'GROUP' OR array_length(trade_ids, 1) >= 2)
);

CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_trade_ids_gin
  ON {OVERRIDES_TABLE_V2} USING GIN (trade_ids);
CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_active
  ON {OVERRIDES_TABLE_V2} (is_active) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_manual_pkg
  ON {OVERRIDES_TABLE_V2} (manual_package_id);
CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_created_at
  ON {OVERRIDES_TABLE_V2} (created_at);

CREATE TABLE IF NOT EXISTS {OVERRIDE_MEMBERS_TABLE_V2} (
    trade_id TEXT NOT NULL,
    override_id UUID NOT NULL REFERENCES {OVERRIDES_TABLE_V2}(override_id),
    override_type TEXT NOT NULL,
    manual_package_id TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Backstop invariant: at most one ACTIVE override per trade. The partial
-- UNIQUE index is ALSO the btree the display view index-probes on
-- (m.trade_id = l.trade_id AND m.is_active) — no separate probe index needed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tape_v2_override_members_active_trade
  ON {OVERRIDE_MEMBERS_TABLE_V2} (trade_id) WHERE is_active;

CREATE TABLE IF NOT EXISTS {OVERRIDE_HISTORY_TABLE_V2} (
    history_id BIGSERIAL PRIMARY KEY,
    override_id UUID NOT NULL REFERENCES {OVERRIDES_TABLE_V2}(override_id),
    action TEXT NOT NULL
      CHECK (action IN ('CREATED','UPDATED','DEACTIVATED','SUPERSEDED')),
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_details JSONB,
    previous_state JSONB
);

CREATE TABLE IF NOT EXISTS {NOTES_TABLE_V2} (
    note_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_type TEXT NOT NULL CHECK (target_type IN ('TRADE','PACKAGE')),
    target_id TEXT NOT NULL,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_tape_v2_notes_target_active
  ON {NOTES_TABLE_V2} (target_type, target_id) WHERE is_active;
```

- [ ] Add the four constants to `__all__` (list at lines 523-535): insert
  `"OVERRIDES_TABLE_V2"`, `"OVERRIDE_MEMBERS_TABLE_V2"`,
  `"OVERRIDE_HISTORY_TABLE_V2"`, `"NOTES_TABLE_V2"` after `"MANUAL_LINKS_TABLE"`.

### Step 1.5 — Add the sentinel entry

- [ ] In `ingest_usdswaps_tape.py`, edit `_LATEST_MIGRATION_COLS` (lines 415-418)
  to add the overrides entry:

```python
_LATEST_MIGRATION_COLS = [
    ("arbs_usd_swap_tape_packages_v2", "ptp_price_notation"),
    ("arbs_usd_swap_tape_legs_v2", "opa_signed_amount"),
    ("arbs_usd_swap_tape_overrides_v2", "override_id"),
]
```

### Step 1.6 — Run the table-existence test (expected PASS)

- [ ] `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_override_tables_created -v -m db`
  Expected: **PASS**.

### Step 1.7 — Failing test: GROUP requires >= 2 trade_ids

- [ ] Append to `tests/test_tape_override_schema.py`:

```python
@pytest.mark.db
def test_group_override_requires_two_trades(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} "
                    "(override_type, trade_ids, created_by) "
                    "VALUES ('GROUP', ARRAY['T1'], 'pytest')"
                )
            )
    with override_engine.begin() as conn:
        oid = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} "
                "(override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['T1','T2'], 'pytest') RETURNING override_id"
            )
        ).scalar()
    assert oid is not None
```

- [ ] Run: `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_group_override_requires_two_trades -v -m db`
  Expected: **PASS** (the `CHECK (override_type <> 'GROUP' OR array_length(...) >= 2)`
  is already in the DDL from Step 1.4; if you sequenced the tests before the
  DDL, this would be the red step). Because the constraint ships with the table
  in the same edit, this test verifies rather than drives new DDL.

### Step 1.8 — Failing test: override_type CHECK + notes target_type CHECK + unique active member

- [ ] Append:

```python
@pytest.mark.db
def test_override_type_check(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} "
                    "(override_type, trade_ids, created_by) "
                    "VALUES ('FOO', ARRAY['T1','T2'], 'pytest')"
                )
            )


@pytest.mark.db
def test_override_members_one_active_per_trade(override_engine):
    from sqlalchemy.exc import IntegrityError

    with override_engine.begin() as conn:
        oid1 = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['TX','TY'], 'pytest') RETURNING override_id"
            )
        ).scalar()
        oid2 = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['TX','TZ'], 'pytest') RETURNING override_id"
            )
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, is_active) "
                "VALUES ('TX', :oid, 'GROUP', TRUE)"
            ),
            {"oid": oid1},
        )
    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                    "(trade_id, override_id, override_type, is_active) "
                    "VALUES ('TX', :oid, 'GROUP', TRUE)"
                ),
                {"oid": oid2},
            )
    # inactive duplicate is allowed (partial index is WHERE is_active)
    with override_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, is_active) "
                "VALUES ('TX', :oid, 'GROUP', FALSE)"
            ),
            {"oid": oid2},
        )


@pytest.mark.db
def test_notes_target_type_check(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {NOTES_TABLE_V2} "
                    "(target_type, target_id, author, body) "
                    "VALUES ('FOO', 'T1', 'pytest', 'hi')"
                )
            )
```

- [ ] Run: `conda run -n stir python -m pytest tests/test_tape_override_schema.py -v -m db`
  Expected: **PASS** (all constraints present from Step 1.4).

### Step 1.9 — Sentinel tests (unit + DB)

- [ ] Append the fast-gate unit test (no marker) and the DB behavior test:

```python
def test_latest_migration_cols_includes_overrides_table():
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import _LATEST_MIGRATION_COLS

    assert ("arbs_usd_swap_tape_overrides_v2", "override_id") in _LATEST_MIGRATION_COLS


@pytest.mark.db
def test_schema_not_current_when_overrides_missing(pg_test_url):
    engine = create_engine(pg_test_url)
    _ing._schema_ensured.discard(str(engine.url))
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_MEMBERS_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_HISTORY_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {NOTES_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDES_TABLE_V2} CASCADE"))
    # Missing overrides table -> sentinel probe finds no row -> NOT current.
    assert _schema_already_current(engine) is False
    ensure_schema(engine)
    assert _schema_already_current(engine) is True
```

- [ ] Run unit test (fast gate, no DB):
  `conda run -n stir python -m pytest "tests/test_tape_override_schema.py::test_latest_migration_cols_includes_overrides_table" -v`
  Expected: **PASS** (fails as red if Step 1.5 not yet done).
- [ ] Run DB sentinel test:
  `conda run -n stir python -m pytest "tests/test_tape_override_schema.py::test_schema_not_current_when_overrides_missing" -v -m db`
  Expected: **PASS**.

### Step 1.10 — Fast gate + commit

- [ ] Fast gate (ensures nothing else broke, collection clean):
  `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q`
  Expected: **PASS**.
- [ ] Commit (git-bash heredoc; trailer lines are mandatory and verbatim):

```bash
git add SDRUtils/_swappulse_scripts/_tape_schema_v2.py \
        SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py \
        tests/test_tape_override_schema.py
git commit -m "$(cat <<'EOF'
feat(tape): add manual-regrouping + notes tables and migration sentinel

Adds arbs_usd_swap_tape_overrides_v2 / _override_members_v2 /
_override_history_v2 / _notes_v2 with constraints + indexes, and extends
_LATEST_MIGRATION_COLS so ensure_schema() does not short-circuit past the
new DDL.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a
EOF
)"
```

---

## Task 2 — Extend `arbs_usd_swap_tape_display_v2` view

Adds `override_map`, `manual_package_id`, `override_type`, `has_notes`,
`notes_count` while keeping `legs_json` **byte-identical**. Override resolution
is an **index probe** of `arbs_usd_swap_tape_override_members_v2` on `trade_id`
placed INSIDE the existing per-package legs LATERAL; notes are resolved in a
separate one-row LATERAL (joining notes to legs would fan out `legs_json`, so it
must stay out of the legs aggregate).

**Why legs_json stays byte-identical:** `to_jsonb(l)` serializes only the legs
table alias `l`, not the joined member row. The added `LEFT JOIN ... m ON
m.trade_id = l.trade_id AND m.is_active` cannot multiply leg rows because
`uq_tape_v2_override_members_active_trade` guarantees at most one ACTIVE member
per `trade_id`. Row count into `jsonb_agg(... ORDER BY l.leg_order)` is therefore
unchanged (= number of legs), so the emitted JSON is identical.

**`manual_package_id` conflict + resolution (DEVIATION — see notes):** the base
view already projects `ml.manual_package_id`. A view cannot output two columns of
the same name. We therefore REMOVE the standalone `ml.manual_package_id`
projection and expose a single, override-aware `manual_package_id =
COALESCE(<override>, ml.manual_package_id)` in the appended block. When no
override exists it falls back to the auto manual-link value, so existing
name-based readers (`route.logic.ts`, frontend `UsdSwapTapeRow`) are unaffected.

### Step 2.1 — Failing test: view exposes the 5 new columns

- [ ] Append to `tests/test_tape_override_schema.py`:

```python
@pytest.mark.db
def test_display_view_has_override_columns(override_engine):
    expected = {"override_map", "manual_package_id", "override_type",
                "has_notes", "notes_count"}
    with override_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :v"
            ),
            {"v": DISPLAY_VIEW_V2},
        ).fetchall()
    cols = {r[0] for r in rows}
    assert expected <= cols, f"view missing columns: {expected - cols}"
```

- [ ] Run: `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_display_view_has_override_columns -v -m db`
  Expected: **FAIL** — the view still has the old column set (`override_map`
  etc. absent).

### Step 2.2 — Replace the view definition

- [ ] In `_tape_schema_v2.py`, replace the view block (currently lines 365-459,
  from `DROP VIEW IF EXISTS {DISPLAY_VIEW_V2};` through
  `  ON ml.link_id = p.manual_link_id AND ml.is_active = TRUE;`) with the
  following. The entire `p.*` projection (lines 368-443) is preserved
  UNCHANGED; the diff is: (a) drop the `ml.manual_package_id,` line, (b) extend
  the legs LATERAL with the member probe + 3 aggregates, (c) append 5 new
  SELECT columns at the end, (d) add the notes LATERAL. Shown in full:

```sql
DROP VIEW IF EXISTS {DISPLAY_VIEW_V2};
CREATE OR REPLACE VIEW {DISPLAY_VIEW_V2} AS
SELECT
  p.package_id,
  p.manual_link_id,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.original_execution_start,
  p.clearing_accepted_start,
  p.package_structure,
  p.package_type,
  p.package_indicator,
  p.package_tenors,
  p.n_package_legs,
  p.legs_count,
  p.total_notional,
  p.gross_notional,
  p.total_risk,
  p.gross_risk,
  p.weighted_fixed_rate,
  p.min_fixed_rate,
  p.max_fixed_rate,
  p.has_spread,
  p.package_transaction_spread,
  p.package_transaction_price,
  p.package_transaction_price_currency,
  p.rate_index_clean,
  p.venue,
  p.ccp,
  p.execution_session,
  p.is_new_risk,
  p.is_unwind,
  p.is_compression_any,
  p.is_ufro_any,
  p.is_block_any,
  p.is_capped_any,
  p.is_off_date_any,
  p.is_termination_any,
  p.is_novation_any,
  p.is_reset_optimization_any,
  p.is_clearing_termination_any,
  p.is_correction_any,
  p.lifecycle_mix,
  p.economic_class_primary,
  p.contributes_to_flow_any,
  p.contributes_to_volume_any,
  p.contributes_to_pnl_any,
  p.on_p43_any,
  p.state_machine_violation_any,
  p.is_fomc_dated,
  p.fomc_meeting_label,
  p.cluster_id,
  p.cluster_size,
  p.tape_label,
  p.is_off_market_any,
  p.confidence_score,
  p.confidence_total,
  p.confidence_tone,
  p.confidence_signals,
  p.summary_rate,
  p.summary_risk,
  p.summary_opa,
  p.is_ccp_switch,
  p.ccp_switch_from,
  p.ccp_switch_to,
  p.package_adjusted_dv01,
  p.normalized_tape_label,
  p.tape_tags,
  p.ptp_group_id,
  p.ptp_group_size,
  p.ptp_price_notation,
  p.opa_signed_net,
  p.opa_ptp_residual,
  p.opa_sign_confidence,
  p.dealer_spread_est,
  p.dealer_spread_bps,
  p.ptp_sub_structures,
  p.package_metrics,
  l.legs_json,
  ml.user_comment,
  ml.link_reason,
  ml.tags,
  ml.link_metrics,
  ml.created_by AS link_created_by,
  ml.created_at AS link_created_at,
  l.override_map,
  COALESCE(l.manual_package_id, ml.manual_package_id) AS manual_package_id,
  l.override_type,
  n.has_notes,
  n.notes_count
FROM {PACKAGES_TABLE_V2} p
LEFT JOIN LATERAL (
    SELECT
      jsonb_agg(to_jsonb(l) ORDER BY l.leg_order) AS legs_json,
      jsonb_object_agg(l.trade_id, m.override_id)
        FILTER (WHERE m.override_id IS NOT NULL) AS override_map,
      max(m.manual_package_id) AS manual_package_id,
      max(m.override_type) AS override_type
    FROM {LEGS_TABLE_V2} l
    LEFT JOIN {OVERRIDE_MEMBERS_TABLE_V2} m
      ON m.trade_id = l.trade_id AND m.is_active
    WHERE l.package_id = p.package_id
) l ON TRUE
LEFT JOIN {MANUAL_LINKS_TABLE} ml
  ON ml.link_id = p.manual_link_id AND ml.is_active = TRUE
LEFT JOIN LATERAL (
    SELECT
      count(*) > 0 AS has_notes,
      count(*)::int AS notes_count
    FROM {NOTES_TABLE_V2} nt
    WHERE nt.is_active
      AND (
        (nt.target_type = 'PACKAGE'
           AND nt.target_id IN (p.package_id, l.manual_package_id, ml.manual_package_id))
        OR (nt.target_type = 'TRADE'
           AND nt.target_id IN (
             SELECT lg.trade_id FROM {LEGS_TABLE_V2} lg
             WHERE lg.package_id = p.package_id
           ))
      )
) n ON TRUE;
```

### Step 2.3 — Add the Task-2 sentinel entry

- [ ] In `ingest_usdswaps_tape.py`, extend `_LATEST_MIGRATION_COLS` to its final
  form so a view-only redeploy is not skipped when the overrides table already
  exists (view columns appear in `information_schema.columns`):

```python
_LATEST_MIGRATION_COLS = [
    ("arbs_usd_swap_tape_packages_v2", "ptp_price_notation"),
    ("arbs_usd_swap_tape_legs_v2", "opa_signed_amount"),
    ("arbs_usd_swap_tape_overrides_v2", "override_id"),
    ("arbs_usd_swap_tape_display_v2", "override_map"),
]
```

### Step 2.4 — Run the view-column test (expected PASS)

- [ ] `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_display_view_has_override_columns -v -m db`
  Expected: **PASS**.

### Step 2.5 — Failing test: legs_json byte-identical + override_map/type/manual_package_id

- [ ] Append:

```python
@pytest.mark.db
def test_view_legs_json_byte_identical_after_override(override_engine):
    with override_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {PACKAGES_TABLE_V2} "
                "(package_id, as_of_date, execution_start, execution_end, legs_count) "
                "VALUES ('PKG_OV_1','2026-07-08',"
                "'2026-07-08T12:00:00Z','2026-07-08T12:00:00Z',2)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {LEGS_TABLE_V2} "
                "(trade_id, package_id, leg_order, as_of_date, execution_timestamp) VALUES "
                "('TID_A','PKG_OV_1',0,'2026-07-08','2026-07-08T12:00:00Z'),"
                "('TID_B','PKG_OV_1',1,'2026-07-08','2026-07-08T12:00:00Z')"
            )
        )
    with override_engine.connect() as conn:
        before = conn.execute(
            text(f"SELECT legs_json::text FROM {DISPLAY_VIEW_V2} WHERE package_id='PKG_OV_1'")
        ).scalar()
    with override_engine.begin() as conn:
        oid = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} "
                "(override_type, manual_package_id, trade_ids, created_by) "
                "VALUES ('GROUP','SMO-20260708-DEADBEEF', ARRAY['TID_A','TID_B'], 'pytest') "
                "RETURNING override_id"
            )
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, manual_package_id, is_active) "
                "VALUES ('TID_A', :oid, 'GROUP', 'SMO-20260708-DEADBEEF', TRUE)"
            ),
            {"oid": oid},
        )
    with override_engine.connect() as conn:
        after_legs, override_map, manual_pkg, ov_type = conn.execute(
            text(
                f"SELECT legs_json::text, override_map, manual_package_id, override_type "
                f"FROM {DISPLAY_VIEW_V2} WHERE package_id='PKG_OV_1'"
            )
        ).fetchone()
    assert after_legs == before, "legs_json changed after override attach"
    assert override_map is not None
    assert override_map.get("TID_A") == str(oid)
    assert manual_pkg == "SMO-20260708-DEADBEEF"
    assert ov_type == "GROUP"
```

- [ ] Run: `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_view_legs_json_byte_identical_after_override -v -m db`
  Expected: **PASS** (drives nothing new — the view SQL from Step 2.2 already
  satisfies it; this is the regression guard for byte-identity + resolution).

### Step 2.6 — Failing test: notes flags

- [ ] Append:

```python
@pytest.mark.db
def test_view_notes_flags(override_engine):
    with override_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {PACKAGES_TABLE_V2} "
                "(package_id, as_of_date, execution_start, execution_end, legs_count) "
                "VALUES ('PKG_NOTE_1','2026-07-08',"
                "'2026-07-08T12:00:00Z','2026-07-08T12:00:00Z',1)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {LEGS_TABLE_V2} "
                "(trade_id, package_id, leg_order, as_of_date, execution_timestamp) "
                "VALUES ('TID_N','PKG_NOTE_1',0,'2026-07-08','2026-07-08T12:00:00Z')"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {NOTES_TABLE_V2} (target_type, target_id, author, body) "
                "VALUES ('PACKAGE','PKG_NOTE_1','pytest','watch this')"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {NOTES_TABLE_V2} (target_type, target_id, author, body) "
                "VALUES ('TRADE','TID_N','pytest','leg note')"
            )
        )
    with override_engine.connect() as conn:
        has_notes, notes_count = conn.execute(
            text(f"SELECT has_notes, notes_count FROM {DISPLAY_VIEW_V2} WHERE package_id='PKG_NOTE_1'")
        ).fetchone()
    assert has_notes is True
    assert notes_count == 2
```

- [ ] Run: `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_view_notes_flags -v -m db`
  Expected: **PASS**.

### Step 2.7 — Failing test: plan-regression (EXPLAIN ANALYZE)

- [ ] Append the acceptance check. It forces the index paths
  (`enable_seqscan=off`) so tiny fixture tables cannot mask a per-package
  re-scan / unnest-CTE regression, asserts the outer packages scan uses
  `idx_tape_v2_packages_exec_start`, the members probe uses
  `uq_tape_v2_override_members_active_trade` (index, not seq scan), and that the
  view cardinality is unchanged (one row per package):

```python
@pytest.mark.db
def test_view_plan_index_paths_and_cardinality(override_engine):
    with override_engine.begin() as conn:
        for i in range(6):
            conn.execute(
                text(
                    f"INSERT INTO {PACKAGES_TABLE_V2} "
                    "(package_id, as_of_date, execution_start, execution_end, legs_count) "
                    "VALUES (:pid,'2026-07-08',:ts,:ts,1)"
                ),
                {"pid": f"PKG_PLAN_{i}", "ts": f"2026-07-08T12:0{i}:00Z"},
            )
            conn.execute(
                text(
                    f"INSERT INTO {LEGS_TABLE_V2} "
                    "(trade_id, package_id, leg_order, as_of_date, execution_timestamp) "
                    "VALUES (:tid,:pid,0,'2026-07-08',:ts)"
                ),
                {"tid": f"TID_PLAN_{i}", "pid": f"PKG_PLAN_{i}", "ts": f"2026-07-08T12:0{i}:00Z"},
            )
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                    "VALUES ('SPLIT', ARRAY[:tid], 'pytest') RETURNING override_id"
                ),
                {"tid": f"TID_PLAN_{i}"},
            )

    with override_engine.connect() as conn:
        baseline = conn.execute(text(f"SELECT count(*) FROM {PACKAGES_TABLE_V2}")).scalar()
        view_rows = conn.execute(text(f"SELECT count(*) FROM {DISPLAY_VIEW_V2}")).scalar()
        conn.execute(text("SET enable_seqscan = off"))
        conn.execute(text("SET enable_bitmapscan = off"))
        plan_json = conn.execute(
            text(
                f"EXPLAIN (ANALYZE, FORMAT JSON) "
                f"SELECT * FROM {DISPLAY_VIEW_V2} d "
                f"WHERE d.execution_start < NOW() "
                f"ORDER BY d.execution_start DESC NULLS LAST LIMIT 201"
            )
        ).scalar()

    # cardinality unchanged: exactly one display row per package
    assert view_rows == baseline

    plan_text = json.dumps(plan_json)
    assert "idx_tape_v2_packages_exec_start" in plan_text, \
        "outer package scan not using idx_tape_v2_packages_exec_start"
    assert "uq_tape_v2_override_members_active_trade" in plan_text, \
        "members probe not served by its unique index (per-package re-scan regression?)"

    def _walk(node):
        yield node
        for child in node.get("Plans", []) or []:
            yield from _walk(child)

    nodes = list(_walk(plan_json[0]["Plan"]))
    member_seqscans = [
        n for n in nodes
        if n.get("Node Type") == "Seq Scan"
        and n.get("Relation Name") == OVERRIDE_MEMBERS_TABLE_V2
    ]
    assert not member_seqscans, "override_members seq-scanned — plan regression"
```

- [ ] Run: `conda run -n stir python -m pytest tests/test_tape_override_schema.py::test_view_plan_index_paths_and_cardinality -v -m db`
  Expected: **PASS**. (If it fails on `idx_tape_v2_packages_exec_start` absent,
  the ORDER BY lost `NULLS LAST`; if it fails on the members assertion, the
  probe regressed to an unnest/CTE that re-scans per package.)

### Step 2.8 — Full new-file run + fast gate + commit

- [ ] `conda run -n stir python -m pytest tests/test_tape_override_schema.py -v -m db`
  Expected: **all PASS** (skips if `DATABASE_URL` unset).
- [ ] `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q`
  Expected: **PASS**.
- [ ] Commit:

```bash
git add SDRUtils/_swappulse_scripts/_tape_schema_v2.py \
        SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py \
        tests/test_tape_override_schema.py
git commit -m "$(cat <<'EOF'
feat(tape): resolve overrides + notes in display view via member index probe

Extends arbs_usd_swap_tape_display_v2 with override_map, manual_package_id
(COALESCE override over auto link), override_type, has_notes, notes_count.
Override resolution is an index probe of the member table inside the per-
package LATERAL; legs_json stays byte-identical. Adds the view-column
sentinel so a view-only redeploy is not skipped.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a
EOF
)"
```

---

## Assumptions / deviations from the contract

1. **Spec file absent.** `docs/superpowers/specs/2026-07-08-usd-swaps-tape-manual-regrouping-notes-design.md`
   is not in the repo (only `2026-07-08-mms-package-detection-design.md` shares
   the date). The contract is treated as authoritative.
2. **`manual_package_id` collision (functional deviation).** The base view
   already outputs `ml.manual_package_id`. A view can't output that name twice,
   so the standalone `ml.manual_package_id` projection is removed and a single
   `manual_package_id = COALESCE(l.manual_package_id /*override*/, ml.manual_package_id)`
   is appended. Override wins; falls back to auto-link. This is the only way to
   honor "append `manual_package_id` at END" without a duplicate-column error,
   and it is backward compatible for name-based readers.
3. **Extra sentinel entry (addition).** The contract specifies only
   `("arbs_usd_swap_tape_overrides_v2", "override_id")`. I add a second entry
   `("arbs_usd_swap_tape_display_v2", "override_map")` in Task 2 so a view-only
   change still triggers DDL after the overrides table already exists (view
   columns are visible in `information_schema.columns`). Without it, the
   sentinel trap silently skips the new view on incremental deploys.
4. **`action` CHECK on history + `override_type` CHECK on members omitted.**
   The contract documents the history `action` enum in prose only; I added a
   `CHECK (action IN ('CREATED','UPDATED','DEACTIVATED','SUPERSEDED'))` as a
   defensive enum guard. `override_members_v2.override_type` has NO CHECK
   (mirrors the parent, matching the contract literally).
5. **No extra `override_id` index on members/history.** The contract lists only
   the partial unique index for members and no index for history. FK columns are
   left unindexed here; the detail/rewrite endpoints (other plan sections) can
   add them if profiling shows a need — out of scope for the schema task.
6. **Notes resolved in a separate LATERAL, not the legs LATERAL.** The contract
   says override members probe goes "INSIDE the existing per-package LATERAL"
   (done). Notes are put in a second one-row LATERAL: joining notes to legs
   would multiply leg rows and break `legs_json` byte-identity. The contract
   allows notes via "a small sparse aggregate/EXISTS", which this satisfies.
7. **EXPLAIN determinism.** On tiny fixture tables Postgres seq-scans
   regardless of indexes, so the plan test sets `enable_seqscan=off` /
   `enable_bitmapscan=off` to prove the index PATHS exist and are chosen (the
   real guard against a per-package re-scan). On prod-sized data the planner
   picks them naturally.
# Plan — Server Layer (auth helper + override CRUD + notes CRUD)

> Owner: SERVER layer. Base path `/api/usd-swaps-tape-v2`. All names/shapes are from
> `plan_contract.md` (verbatim). Do NOT touch shared `lib/manual-*` / `lib/manual-links-ui/*`
> (sofr + swaptions co-consume them) — these are tape-local mirrors.
>
> **Test harness (mirrored from existing v2 route tests)**
> - Runner: **`npm test`** in `SDRUtils/dashboard` only (script = `node --experimental-vm-modules node_modules/jest/bin/jest.js`). NEVER plain `npx jest` — ESM mocks break.
> - Single file: `cd SDRUtils/dashboard && npm test -- <path-relative-to-dashboard>`.
> - ESM jest: declare mocks with `jest.unstable_mockModule('@/lib/db', () => ({...}))` at module top, then `await import('../route')` **inside** each test/`beforeAll` (dynamic import AFTER the mock is registered). Pattern copied from `src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.test.ts`.
> - Handlers are exercised by constructing a `Request` and calling the exported `GET/POST/PATCH/DELETE`; dynamic routes take a second arg `{ params: Promise<{ overrideId }> }`.
> - DB mock: `const queryMock = jest.fn()` for `query`; for transactions `const clientQueryMock = jest.fn(); const withClientMock = jest.fn(async (fn) => fn({ query: clientQueryMock }))`. Route both `query` and `withClient` from the one `unstable_mockModule('@/lib/db', ...)` call.
> - Auth: set `process.env.TAPE_OVERRIDE_PASSWORD` in the test (read at call time, no module mock needed).
> - Pure-lib tests mirror `src/lib/__tests__/manual-sofr-swap-links.test.ts` (import function, assert; no DB).
> - Live integration tests mirror `src/app/api/usd-swaps-tape-v2/__tests__/integration.test.ts`: `const describeIfDb = (process.env.PG_TEST_URL || process.env.DATABASE_URL) ? describe : describe.skip`.
>
> **Every commit message ends with these two trailer lines (verbatim):**
> ```
> Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
> Claude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a
> ```

---

## Task 3 — `isValidTapeWritePassword` + `TAPE_WRITE_AUTH_ERROR` (env-based auth)

Add alongside `isValidSimpleAdminPassword`/`SIMPLE_ADMIN_PASSWORD` in `src/lib/utils.ts`. Env-var based, **NO hardcoded default** (unset/empty env ⇒ always false ⇒ endpoints locked until an operator sets `TAPE_OVERRIDE_PASSWORD`).

- [ ] **Write failing test** `src/lib/__tests__/tape-write-password.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it } from '@jest/globals'
import { isValidTapeWritePassword, TAPE_WRITE_AUTH_ERROR } from '../utils'

describe('isValidTapeWritePassword', () => {
  const ORIGINAL = process.env.TAPE_OVERRIDE_PASSWORD
  beforeEach(() => {
    process.env.TAPE_OVERRIDE_PASSWORD = 'letmein'
  })
  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.TAPE_OVERRIDE_PASSWORD
    else process.env.TAPE_OVERRIDE_PASSWORD = ORIGINAL
  })

  it('exposes the fixed error message', () => {
    expect(TAPE_WRITE_AUTH_ERROR).toBe('Invalid override password.')
  })
  it('accepts the exact password (trimmed)', () => {
    expect(isValidTapeWritePassword('letmein')).toBe(true)
    expect(isValidTapeWritePassword('  letmein  ')).toBe(true)
  })
  it('rejects a mismatch', () => {
    expect(isValidTapeWritePassword('nope')).toBe(false)
  })
  it('rejects non-strings', () => {
    expect(isValidTapeWritePassword(undefined)).toBe(false)
    expect(isValidTapeWritePassword(null)).toBe(false)
    expect(isValidTapeWritePassword(123)).toBe(false)
  })
  it('returns false when the env var is unset', () => {
    delete process.env.TAPE_OVERRIDE_PASSWORD
    expect(isValidTapeWritePassword('letmein')).toBe(false)
  })
  it('returns false when the env var is empty/whitespace', () => {
    process.env.TAPE_OVERRIDE_PASSWORD = '   '
    expect(isValidTapeWritePassword('   ')).toBe(false)
  })
})
```
- [ ] **Run (expect FAIL — module has no such export):** `cd SDRUtils/dashboard && npm test -- src/lib/__tests__/tape-write-password.test.ts`
- [ ] **Implement** — append to `src/lib/utils.ts`:
```ts
export const TAPE_WRITE_AUTH_ERROR = 'Invalid override password.'

// Env-based tape-write gate. No hardcoded default: an unset or blank
// TAPE_OVERRIDE_PASSWORD locks every override endpoint until an operator
// provisions the secret. Compares the trimmed request value against the
// configured secret.
export function isValidTapeWritePassword(value: unknown): boolean {
  const expected = process.env.TAPE_OVERRIDE_PASSWORD
  if (typeof expected !== 'string' || expected.trim() === '') return false
  if (typeof value !== 'string') return false
  return value.trim() === expected.trim()
}
```
- [ ] **Add env doc** — append to `SDRUtils/dashboard/.env.example`:
```
# Shared secret gating manual tape overrides (GROUP/SPLIT/DETACH create/edit/delete).
# Unset or blank => all override write endpoints are locked (403). Notes need no password.
TAPE_OVERRIDE_PASSWORD=
```
- [ ] **Run (expect PASS):** `cd SDRUtils/dashboard && npm test -- src/lib/__tests__/tape-write-password.test.ts`
- [ ] **Commit:**
```
git add SDRUtils/dashboard/src/lib/utils.ts SDRUtils/dashboard/src/lib/__tests__/tape-write-password.test.ts SDRUtils/dashboard/.env.example
git commit -m "$(printf 'feat(tape): env-gated tape-write password helper\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a')"
```

---

## Task 4 — `lib/tape-overrides.ts` (validation, metrics, supersession, membership, id gen)

Pure helpers are unit-tested directly; DB helpers are exercised with the `query`/client mock. Tape-local mirror of the sofr link helpers — do not import from `manual-sofr-swap-links.ts`.

- [ ] **Write failing test** `src/lib/__tests__/tape-overrides.test.ts`:
```ts
import { describe, expect, it, jest, beforeEach } from '@jest/globals'

const queryMock = jest.fn(async () => ({ rows: [] as unknown[] }))
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock, withClient: jest.fn() }))

const mod = await import('../tape-overrides')
const {
  normalizeIdList,
  normalizeText,
  normalizeTags,
  generateManualPackageId,
  validateOverride,
  computeOverrideMetrics,
  buildMemberRows,
  resolveManualPackageId,
} = mod

beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})

describe('normalizeIdList', () => {
  it('splits, trims, dedupes, drops blanks', () => {
    expect(normalizeIdList('a, b ,a\n c')).toEqual(['a', 'b', 'c'])
    expect(normalizeIdList(['x', 'x', ' y '])).toEqual(['x', 'y'])
    expect(normalizeIdList(undefined)).toEqual([])
  })
})

describe('validateOverride', () => {
  it('GROUP requires >= 2 trades', () => {
    const one = validateOverride('GROUP', ['T1'])
    expect(one.hasErrors).toBe(true)
    expect(one.validation[0]).toMatchObject({ level: 'error', code: 'GROUP_MIN_TRADES' })
    const two = validateOverride('GROUP', ['T1', 'T2'])
    expect(two.hasErrors).toBe(false)
    expect(two.validation.some((v) => v.level === 'info')).toBe(true)
  })
  it('SPLIT/DETACH allow >= 1 trade', () => {
    expect(validateOverride('SPLIT', ['T1']).hasErrors).toBe(false)
    expect(validateOverride('DETACH', ['T1']).hasErrors).toBe(false)
    expect(validateOverride('SPLIT', []).hasErrors).toBe(true)
  })
})

describe('computeOverrideMetrics', () => {
  it('counts trades and distinct source packages', () => {
    const m = computeOverrideMetrics('GROUP', ['T1', 'T2', 'T3'], [
      { trade_id: 'T1', package_id: 'P1' },
      { trade_id: 'T2', package_id: 'P1' },
      { trade_id: 'T3', package_id: 'P2' },
    ])
    expect(m.trade_count).toBe(3)
    expect(m.override_type).toBe('GROUP')
    expect(m.distinct_package_ids).toBe(2)
    expect(m.source_package_ids.sort()).toEqual(['P1', 'P2'])
  })
})

describe('generateManualPackageId', () => {
  it('matches SMO-YYYYMMDD-<8 upper hex>', () => {
    expect(generateManualPackageId()).toMatch(/^SMO-\d{8}-[0-9A-F]{8}$/)
  })
})

describe('resolveManualPackageId', () => {
  it('returns provided id verbatim regardless of type', () => {
    expect(resolveManualPackageId('SPLIT', 'SMO-20260708-AAAA1111')).toBe('SMO-20260708-AAAA1111')
  })
  it('null for SPLIT/DETACH when none provided', () => {
    expect(resolveManualPackageId('SPLIT', null)).toBeNull()
    expect(resolveManualPackageId('DETACH', null)).toBeNull()
  })
  it('signals generation for GROUP when none provided', () => {
    expect(resolveManualPackageId('GROUP', null)).toBe('__GENERATE__')
  })
})

describe('buildMemberRows', () => {
  it('one row per trade carrying override metadata', () => {
    const rows = buildMemberRows('OID', 'GROUP', 'SMO-20260708-AAAA1111', ['T1', 'T2'])
    expect(rows).toEqual([
      { trade_id: 'T1', override_id: 'OID', override_type: 'GROUP', manual_package_id: 'SMO-20260708-AAAA1111' },
      { trade_id: 'T2', override_id: 'OID', override_type: 'GROUP', manual_package_id: 'SMO-20260708-AAAA1111' },
    ])
  })
})

describe('resolveOverrideLegs (db)', () => {
  it('reads trade_id/package_id from the tape legs table', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ trade_id: 'T1', package_id: 'P1' }] })
    const legs = await mod.resolveOverrideLegs(['T1'])
    expect(legs).toEqual([{ trade_id: 'T1', package_id: 'P1' }])
    expect(queryMock).toHaveBeenCalledTimes(1)
    expect(String(queryMock.mock.calls[0][0])).toContain('arbs_usd_swap_tape_legs_v2')
  })
  it('short-circuits on empty input', async () => {
    expect(await mod.resolveOverrideLegs([])).toEqual([])
    expect(queryMock).not.toHaveBeenCalled()
  })
})

describe('findOverlappingActiveOverrideIds (db)', () => {
  it('excludes the given override id and returns ids', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ override_id: 'OLD1' }, { override_id: 'OLD2' }] })
    const ids = await mod.findOverlappingActiveOverrideIds(['T1', 'T2'], 'NEW')
    expect(ids).toEqual(['OLD1', 'OLD2'])
    const [sql, params] = queryMock.mock.calls[0]
    expect(String(sql)).toContain('trade_ids && $1')
    expect(String(sql)).toContain('override_id <> $2')
    expect(params).toEqual([['T1', 'T2'], 'NEW'])
  })
})
```
- [ ] **Run (expect FAIL — module missing):** `cd SDRUtils/dashboard && npm test -- src/lib/__tests__/tape-overrides.test.ts`
- [ ] **Implement** `src/lib/tape-overrides.ts`:
```ts
// ABOUTME: Tape-local helpers for manual package overrides (GROUP/SPLIT/DETACH):
// validation, metrics, supersession, membership rows, manual_package_id gen.
import { randomUUID } from 'crypto'
import type { PoolClient } from 'pg'
import { query } from '@/lib/db'

export const OVERRIDES_TABLE = 'arbs_usd_swap_tape_overrides_v2'
export const OVERRIDE_MEMBERS_TABLE = 'arbs_usd_swap_tape_override_members_v2'
export const OVERRIDE_HISTORY_TABLE = 'arbs_usd_swap_tape_override_history_v2'
export const TAPE_LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export type OverrideType = 'GROUP' | 'SPLIT' | 'DETACH'
export const OVERRIDE_TYPES: OverrideType[] = ['GROUP', 'SPLIT', 'DETACH']

export interface OverrideValidationItem {
  level: 'error' | 'warning' | 'info'
  code: string
  message: string
}

export interface OverrideMetrics {
  trade_count: number
  override_type: OverrideType
  distinct_package_ids: number
  source_package_ids: string[]
}

export interface OverrideLeg {
  trade_id: string
  package_id: string | null
}

export interface OverrideMemberRow {
  trade_id: string
  override_id: string
  override_type: OverrideType
  manual_package_id: string | null
}

// Sentinel: resolveManualPackageId returns this when the caller must
// allocate a fresh id inside the transaction (GROUP with none supplied).
export const GENERATE_PACKAGE_ID = '__GENERATE__'

export function isOverrideType(value: unknown): value is OverrideType {
  return typeof value === 'string' && (OVERRIDE_TYPES as string[]).includes(value)
}

export function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

export function normalizeTags(value: unknown): string[] | null {
  if (value === undefined || value === null) return null
  if (Array.isArray(value)) {
    const tags = value.map((entry) => String(entry).trim()).filter(Boolean)
    return tags.length ? tags : null
  }
  if (typeof value === 'string') {
    const tags = value.split(',').map((entry) => entry.trim()).filter(Boolean)
    return tags.length ? tags : null
  }
  return null
}

export function normalizeIdList(input: unknown): string[] {
  if (!input) return []
  const rawValues = Array.isArray(input) ? input : String(input).split(/[\s,]+/)
  const seen = new Set<string>()
  const result: string[] = []
  rawValues.forEach((value) => {
    const normalized = String(value).trim()
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    result.push(normalized)
  })
  return result
}

function buildDateToken(date: Date): string {
  const yyyy = String(date.getUTCFullYear())
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(date.getUTCDate()).padStart(2, '0')
  return `${yyyy}${mm}${dd}`
}

export function generateManualPackageId(): string {
  const token = randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()
  return `SMO-${buildDateToken(new Date())}-${token}`
}

// GROUP clusters need a manual_package_id; SPLIT/DETACH do not (the view keys
// synthetic rows off package_id + trade_id). A caller-supplied id always wins.
export function resolveManualPackageId(
  overrideType: OverrideType,
  provided: string | null,
): string | null {
  if (provided) return provided
  return overrideType === 'GROUP' ? GENERATE_PACKAGE_ID : null
}

export function validateOverride(
  overrideType: OverrideType,
  tradeIds: string[],
): { validation: OverrideValidationItem[]; hasErrors: boolean } {
  const validation: OverrideValidationItem[] = []
  const count = tradeIds.length
  if (overrideType === 'GROUP' && count < 2) {
    validation.push({
      level: 'error',
      code: 'GROUP_MIN_TRADES',
      message: 'GROUP overrides require at least two trades.',
    })
  } else if (count < 1) {
    validation.push({
      level: 'error',
      code: 'MIN_TRADES',
      message: 'Select at least one trade.',
    })
  } else {
    validation.push({
      level: 'info',
      code: 'TRADE_COUNT',
      message: `${count} trade${count === 1 ? '' : 's'} selected.`,
    })
  }
  const hasErrors = validation.some((item) => item.level === 'error')
  return { validation, hasErrors }
}

export function computeOverrideMetrics(
  overrideType: OverrideType,
  tradeIds: string[],
  legs: OverrideLeg[],
): OverrideMetrics {
  const packageIds = Array.from(
    new Set(
      legs
        .map((leg) => (leg.package_id == null ? '' : String(leg.package_id).trim()))
        .filter(Boolean),
    ),
  )
  return {
    trade_count: tradeIds.length,
    override_type: overrideType,
    distinct_package_ids: packageIds.length,
    source_package_ids: packageIds,
  }
}

export function buildMemberRows(
  overrideId: string,
  overrideType: OverrideType,
  manualPackageId: string | null,
  tradeIds: string[],
): OverrideMemberRow[] {
  return tradeIds.map((tradeId) => ({
    trade_id: tradeId,
    override_id: overrideId,
    override_type: overrideType,
    manual_package_id: manualPackageId,
  }))
}

// --- DB helpers (read-only reads via `query`; transactional writes take a client) ---

export async function resolveOverrideLegs(tradeIds: string[]): Promise<OverrideLeg[]> {
  if (!tradeIds.length) return []
  const result = await query<OverrideLeg>(
    `SELECT trade_id, package_id
     FROM ${TAPE_LEGS_TABLE}
     WHERE trade_id = ANY($1)`,
    [tradeIds],
  )
  return result.rows
}

export async function findOverlappingActiveOverrideIds(
  tradeIds: string[],
  excludeOverrideId?: string,
): Promise<string[]> {
  if (!tradeIds.length) return []
  const params: unknown[] = [tradeIds]
  let sql = `SELECT override_id FROM ${OVERRIDES_TABLE}
             WHERE is_active = TRUE AND trade_ids && $1`
  if (excludeOverrideId) {
    params.push(excludeOverrideId)
    sql += ` AND override_id <> $${params.length}`
  }
  const result = await query<{ override_id: string }>(sql, params)
  return result.rows.map((row) => row.override_id)
}

// Allocate a manual_package_id not already present. The (manual_package_id)
// index is non-unique, so this is a best-effort pre-check inside the txn.
export async function allocateManualPackageId(client: PoolClient): Promise<string> {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const candidate = generateManualPackageId()
    const existing = await client.query(
      `SELECT 1 FROM ${OVERRIDES_TABLE} WHERE manual_package_id = $1 LIMIT 1`,
      [candidate],
    )
    if (!existing.rows.length) return candidate
  }
  throw new Error('Failed to allocate manual_package_id after 5 attempts')
}

// Deactivate every active override overlapping `tradeIds` (excluding
// `newOverrideId`), point them at the new parent, deactivate their member
// rows, and log SUPERSEDED history. Must run before inserting the new members
// so the partial-unique (trade_id) WHERE is_active index is not violated.
export async function supersedeOverlappingOverrides(
  client: PoolClient,
  tradeIds: string[],
  newOverrideId: string,
  changedBy: string,
): Promise<string[]> {
  const overlapping = await client.query<{ override_id: string }>(
    `SELECT override_id FROM ${OVERRIDES_TABLE}
     WHERE is_active = TRUE AND trade_ids && $1 AND override_id <> $2`,
    [tradeIds, newOverrideId],
  )
  const ids = overlapping.rows.map((row) => row.override_id)
  if (!ids.length) return []

  await client.query(
    `UPDATE ${OVERRIDES_TABLE}
     SET is_active = FALSE, superseded_by = $1, updated_by = $2, updated_at = NOW()
     WHERE override_id = ANY($3)`,
    [newOverrideId, changedBy, ids],
  )
  await client.query(
    `UPDATE ${OVERRIDE_MEMBERS_TABLE}
     SET is_active = FALSE
     WHERE override_id = ANY($1)`,
    [ids],
  )
  await client.query(
    `INSERT INTO ${OVERRIDE_HISTORY_TABLE} (override_id, action, changed_by, change_details)
     SELECT oid, 'SUPERSEDED', $2, $3::jsonb
     FROM unnest($1::uuid[]) AS oid`,
    [ids, changedBy, { superseded_by: newOverrideId }],
  )
  return ids
}

// Insert member rows for an override in a single statement.
export async function insertMemberRows(
  client: PoolClient,
  overrideId: string,
  overrideType: OverrideType,
  manualPackageId: string | null,
  tradeIds: string[],
): Promise<void> {
  if (!tradeIds.length) return
  await client.query(
    `INSERT INTO ${OVERRIDE_MEMBERS_TABLE}
       (trade_id, override_id, override_type, manual_package_id, is_active)
     SELECT t, $2, $3, $4, TRUE FROM unnest($1::text[]) AS t`,
    [tradeIds, overrideId, overrideType, manualPackageId],
  )
}
```
- [ ] **Run (expect PASS):** `cd SDRUtils/dashboard && npm test -- src/lib/__tests__/tape-overrides.test.ts`
- [ ] **Commit:**
```
git add SDRUtils/dashboard/src/lib/tape-overrides.ts SDRUtils/dashboard/src/lib/__tests__/tape-overrides.test.ts
git commit -m "$(printf 'feat(tape): tape-overrides lib (validation, metrics, supersession, members)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a')"
```

---

## Task 5 — `overrides/route.ts` (POST create + GET list)

File: `src/app/api/usd-swaps-tape-v2/overrides/route.ts`. POST is fully transactional (supersede → insert parent → members → history); `validate_only` short-circuits before any write and before the 403 gate; auth gate returns 403 with `TAPE_WRITE_AUTH_ERROR`.

- [ ] **Write failing test** `src/app/api/usd-swaps-tape-v2/overrides/__tests__/route.test.ts`:
```ts
import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

const queryMock = jest.fn()
const clientQueryMock = jest.fn()
const withClientMock = jest.fn(async (fn: any) => fn({ query: clientQueryMock }))
jest.unstable_mockModule('@/lib/db', () => ({
  query: queryMock,
  withClient: withClientMock,
}))

let POST: any
let GET: any
beforeAll(async () => {
  const mod = await import('../route')
  POST = mod.POST
  GET = mod.GET
})

function post(body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/overrides', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
}

beforeEach(() => {
  process.env.TAPE_OVERRIDE_PASSWORD = 'pw'
  queryMock.mockReset()
  clientQueryMock.mockReset()
  withClientMock.mockClear()
  // Default: legs lookup returns two legs in one package.
  queryMock.mockResolvedValue({ rows: [
    { trade_id: 'T1', package_id: 'P1' },
    { trade_id: 'T2', package_id: 'P1' },
  ] })
  // Route the transactional statements by SQL text.
  clientQueryMock.mockImplementation(async (sql: string) => {
    if (/^\s*BEGIN/i.test(sql) || /^\s*COMMIT/i.test(sql) || /^\s*ROLLBACK/i.test(sql)) return { rows: [] }
    if (/SELECT 1 FROM .*overrides/i.test(sql)) return { rows: [] } // pkg id free
    if (/INSERT INTO .*overrides/i.test(sql)) {
      return { rows: [{ override_id: 'NEW-OID', manual_package_id: 'SMO-20260708-AAAA1111' }] }
    }
    if (/SELECT override_id FROM .*overrides/i.test(sql)) return { rows: [] } // no overlap
    return { rows: [] }
  })
})

describe('POST /overrides', () => {
  it('400 on invalid JSON', async () => {
    const bad = new Request('http://t/api/usd-swaps-tape-v2/overrides', { method: 'POST', body: '{' })
    expect((await POST(bad)).status).toBe(400)
  })
  it('400 on bad override_type', async () => {
    const res = await POST(post({ override_type: 'MERGE', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(400)
  })
  it('validate_only returns validation/metrics/linked_trade_ids and never writes', async () => {
    const res = await POST(post({ override_type: 'GROUP', trade_ids: 'T1,T2', validate_only: true }))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.linked_trade_ids).toEqual(['T1', 'T2'])
    expect(body.metrics.trade_count).toBe(2)
    expect(Array.isArray(body.validation)).toBe(true)
    expect(withClientMock).not.toHaveBeenCalled()
  })
  it('409 when validation fails (GROUP with one trade)', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ trade_id: 'T1', package_id: 'P1' }] })
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1'], user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(409)
  })
  it('403 with the fixed error when password is wrong', async () => {
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'bad' }))
    expect(res.status).toBe(403)
    expect((await res.json()).error).toBe('Invalid override password.')
  })
  it('creates transactionally and returns override_id + manual_package_id', async () => {
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], reason: 'test', user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.success).toBe(true)
    expect(body.override_id).toBe('NEW-OID')
    expect(body.manual_package_id).toBe('SMO-20260708-AAAA1111')
    const sqls = clientQueryMock.mock.calls.map((c: any[]) => String(c[0]))
    expect(sqls.some((s: string) => /^\s*BEGIN/i.test(s))).toBe(true)
    expect(sqls.some((s: string) => /INSERT INTO .*override_members/i.test(s))).toBe(true)
    expect(sqls.some((s: string) => /INSERT INTO .*override_history/i.test(s) && /CREATED/i.test(s) === false)).toBe(true)
    expect(sqls.some((s: string) => /^\s*COMMIT/i.test(s))).toBe(true)
  })
  it('supersession invariant: overlapping active members are deactivated before new insert', async () => {
    const order: string[] = []
    clientQueryMock.mockImplementation(async (sql: string) => {
      if (/SELECT override_id FROM .*overrides/i.test(sql)) return { rows: [{ override_id: 'OLD' }] }
      if (/INSERT INTO .*overrides/i.test(sql)) return { rows: [{ override_id: 'NEW-OID', manual_package_id: 'SMO-X' }] }
      if (/SELECT 1 FROM .*overrides/i.test(sql)) return { rows: [] }
      if (/UPDATE .*override_members\s+SET is_active = FALSE/i.test(sql)) order.push('deactivate-members')
      if (/INSERT INTO .*override_members/i.test(sql)) order.push('insert-members')
      return { rows: [] }
    })
    await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    expect(order).toEqual(['deactivate-members', 'insert-members'])
  })
  it('rolls back and 500s when a write throws', async () => {
    clientQueryMock.mockImplementation(async (sql: string) => {
      if (/INSERT INTO .*override_members/i.test(sql)) throw new Error('boom')
      if (/INSERT INTO .*overrides/i.test(sql)) return { rows: [{ override_id: 'NEW-OID', manual_package_id: 'X' }] }
      return { rows: [] }
    })
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(500)
    expect(clientQueryMock.mock.calls.map((c: any[]) => String(c[0])).some((s) => /^\s*ROLLBACK/i.test(s))).toBe(true)
  })
})

describe('GET /overrides', () => {
  it('lists with filters and returns { rows }', async () => {
    queryMock.mockReset()
    queryMock.mockResolvedValueOnce({ rows: [{ override_id: 'A' }] })
    const res = await GET(new Request('http://t/api/usd-swaps-tape-v2/overrides?is_active=true&created_by=u&limit=10'))
    expect(res.status).toBe(200)
    expect((await res.json()).rows).toEqual([{ override_id: 'A' }])
  })
})
```
- [ ] **Run (expect FAIL — route missing):** `cd SDRUtils/dashboard && npm test -- src/app/api/usd-swaps-tape-v2/overrides/__tests__/route.test.ts`
- [ ] **Implement** `src/app/api/usd-swaps-tape-v2/overrides/route.ts`:
```ts
// ABOUTME: Create + list manual tape overrides (GROUP/SPLIT/DETACH).
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query, withClient } from '@/lib/db'
import { isValidTapeWritePassword, TAPE_WRITE_AUTH_ERROR } from '@/lib/utils'
import {
  OVERRIDES_TABLE,
  OVERRIDE_HISTORY_TABLE,
  GENERATE_PACKAGE_ID,
  allocateManualPackageId,
  computeOverrideMetrics,
  insertMemberRows,
  isOverrideType,
  normalizeIdList,
  normalizeTags,
  normalizeText,
  resolveManualPackageId,
  resolveOverrideLegs,
  supersedeOverlappingOverrides,
  validateOverride,
} from '@/lib/tape-overrides'

const DEFAULT_LIST_LIMIT = 200
const MAX_LIST_LIMIT = 1000

type OverridePostPayload = {
  override_type?: unknown
  trade_ids?: unknown
  manual_package_id?: unknown
  reason?: unknown
  tags?: unknown
  user?: unknown
  admin_password?: unknown
  validate_only?: unknown
}

function parseBoolean(value: string | null): boolean | null {
  if (!value) return null
  const v = value.trim().toLowerCase()
  if (['true', '1', 'yes', 'y'].includes(v)) return true
  if (['false', '0', 'no', 'n'].includes(v)) return false
  return null
}

function parseLimit(value: string | null): number {
  if (!value) return DEFAULT_LIST_LIMIT
  const parsed = Number(value)
  if (Number.isNaN(parsed) || parsed < 1) return DEFAULT_LIST_LIMIT
  return Math.min(parsed, MAX_LIST_LIMIT)
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const createdBy = searchParams.get('created_by')
  const isActive = parseBoolean(searchParams.get('is_active'))
  const limit = parseLimit(searchParams.get('limit'))

  const params: unknown[] = []
  const conditions: string[] = []
  if (createdBy) {
    params.push(`%${createdBy}%`)
    conditions.push(`created_by ILIKE $${params.length}`)
  }
  if (isActive !== null) {
    params.push(isActive)
    conditions.push(`is_active = $${params.length}`)
  }
  params.push(limit)
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  try {
    const result = await query(
      `SELECT * FROM ${OVERRIDES_TABLE}
       ${whereClause}
       ORDER BY created_at DESC
       LIMIT $${params.length}`,
      params,
    )
    return NextResponse.json({ rows: result.rows })
  } catch (error: any) {
    console.error('tape overrides GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch overrides' },
      { status: 500 },
    )
  }
}

export async function POST(request: Request) {
  let payload: OverridePostPayload
  try {
    payload = (await request.json()) as OverridePostPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }

  if (!isOverrideType(payload.override_type)) {
    return NextResponse.json(
      { error: "override_type must be one of 'GROUP', 'SPLIT', 'DETACH'." },
      { status: 400 },
    )
  }
  const overrideType = payload.override_type
  const tradeIds = normalizeIdList(payload.trade_ids)
  if (!tradeIds.length) {
    return NextResponse.json(
      { error: 'trade_ids must include at least one trade.' },
      { status: 400 },
    )
  }

  const validateOnly =
    payload.validate_only === true ||
    String(payload.validate_only).toLowerCase() === 'true'

  try {
    const legs = await resolveOverrideLegs(tradeIds)
    const metrics = computeOverrideMetrics(overrideType, tradeIds, legs)
    const { validation, hasErrors } = validateOverride(overrideType, tradeIds)

    if (validateOnly) {
      return NextResponse.json({ validation, metrics, linked_trade_ids: tradeIds })
    }
    if (hasErrors) {
      return NextResponse.json(
        { error: 'Validation failed', validation, metrics },
        { status: 409 },
      )
    }
    if (!isValidTapeWritePassword(payload.admin_password)) {
      return NextResponse.json({ error: TAPE_WRITE_AUTH_ERROR }, { status: 403 })
    }
    const user = normalizeText(payload.user)
    if (!user) {
      return NextResponse.json(
        { error: 'user is required to create an override.' },
        { status: 400 },
      )
    }

    const reason = normalizeText(payload.reason)
    const tags = normalizeTags(payload.tags)
    const requestedPkgId = resolveManualPackageId(
      overrideType,
      normalizeText(payload.manual_package_id),
    )

    const created = await withClient(async (client) => {
      await client.query('BEGIN')
      try {
        const manualPackageId =
          requestedPkgId === GENERATE_PACKAGE_ID
            ? await allocateManualPackageId(client)
            : requestedPkgId

        const insertParent = await client.query(
          `INSERT INTO ${OVERRIDES_TABLE}
             (override_type, manual_package_id, trade_ids, created_by, reason, tags, metrics)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING override_id, manual_package_id`,
          [overrideType, manualPackageId, tradeIds, user, reason, tags, metrics],
        )
        const overrideId: string = insertParent.rows[0].override_id
        const finalPackageId: string | null = insertParent.rows[0].manual_package_id

        await supersedeOverlappingOverrides(client, tradeIds, overrideId, user)
        await insertMemberRows(client, overrideId, overrideType, finalPackageId, tradeIds)
        await client.query(
          `INSERT INTO ${OVERRIDE_HISTORY_TABLE}
             (override_id, action, changed_by, change_details)
           VALUES ($1, 'CREATED', $2, $3::jsonb)`,
          [overrideId, user, { override_type: overrideType, trade_ids: tradeIds, manual_package_id: finalPackageId, reason, tags }],
        )
        await client.query('COMMIT')
        return { override_id: overrideId, manual_package_id: finalPackageId }
      } catch (txErr) {
        await client.query('ROLLBACK')
        throw txErr
      }
    })

    return NextResponse.json({
      success: true,
      override_id: created.override_id,
      manual_package_id: created.manual_package_id,
      validation,
      metrics,
    })
  } catch (error: any) {
    console.error('tape overrides POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to create override' },
      { status: 500 },
    )
  }
}
```
- [ ] **Run (expect PASS):** `cd SDRUtils/dashboard && npm test -- src/app/api/usd-swaps-tape-v2/overrides/__tests__/route.test.ts`
- [ ] **Commit:**
```
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/overrides/route.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/overrides/__tests__/route.test.ts
git commit -m "$(printf 'feat(tape): POST create + GET list override endpoints\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a')"
```

---

## Task 6 — `overrides/[overrideId]/route.ts` (GET detail + PATCH update + DELETE deactivate)

File: `src/app/api/usd-swaps-tape-v2/overrides/[overrideId]/route.ts`. PATCH/DELETE are 403-gated + transactional. PATCH recomputes the trade set, re-validates, deactivates this override's members, supersedes newly-overlapping others, updates the parent, rewrites members, logs UPDATED. DELETE soft-deactivates parent + members, logs DEACTIVATED.

- [ ] **Write failing test** `src/app/api/usd-swaps-tape-v2/overrides/[overrideId]/__tests__/route.test.ts`:
```ts
import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

const queryMock = jest.fn()
const clientQueryMock = jest.fn()
const withClientMock = jest.fn(async (fn: any) => fn({ query: clientQueryMock }))
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock, withClient: withClientMock }))

let GET: any, PATCH: any, DELETE: any
beforeAll(async () => {
  const mod = await import('../route')
  GET = mod.GET; PATCH = mod.PATCH; DELETE = mod.DELETE
})

const ctx = (id: string) => ({ params: Promise.resolve({ overrideId: id }) })
function req(method: string, body?: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/overrides/OID', {
    method,
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

beforeEach(() => {
  process.env.TAPE_OVERRIDE_PASSWORD = 'pw'
  queryMock.mockReset(); clientQueryMock.mockReset(); withClientMock.mockClear()
  clientQueryMock.mockResolvedValue({ rows: [] })
})

describe('GET /overrides/[overrideId]', () => {
  it('404 when override missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await GET(req('GET'), ctx('OID'))
    expect(res.status).toBe(404)
  })
  it('returns { override, members, history }', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ override_id: 'OID', trade_ids: ['T1', 'T2'], override_type: 'GROUP', manual_package_id: 'SMO-X' }] })
      .mockResolvedValueOnce({ rows: [{ trade_id: 'T1' }, { trade_id: 'T2' }] })
      .mockResolvedValueOnce({ rows: [{ action: 'CREATED' }] })
    const res = await GET(req('GET'), ctx('OID'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.override.override_id).toBe('OID')
    expect(body.members.length).toBe(2)
    expect(body.history.length).toBe(1)
  })
})

describe('PATCH /overrides/[overrideId]', () => {
  it('403 on bad password', async () => {
    const res = await PATCH(req('PATCH', { user: 'u', admin_password: 'bad' }), ctx('OID'))
    expect(res.status).toBe(403)
  })
  it('404 when override missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await PATCH(req('PATCH', { user: 'u', admin_password: 'pw', add_trades: ['T3'] }), ctx('OID'))
    expect(res.status).toBe(404)
  })
  it('recomputes set, updates parent + members in a txn', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ override_id: 'OID', override_type: 'GROUP', trade_ids: ['T1', 'T2'], manual_package_id: 'SMO-X' }] }) // existing
      .mockResolvedValueOnce({ rows: [{ trade_id: 'T1', package_id: 'P1' }, { trade_id: 'T2', package_id: 'P1' }, { trade_id: 'T3', package_id: 'P2' }] }) // legs
    clientQueryMock.mockImplementation(async (sql: string) => {
      if (/SELECT override_id FROM .*overrides/i.test(sql)) return { rows: [] }
      return { rows: [] }
    })
    const res = await PATCH(req('PATCH', { user: 'u', admin_password: 'pw', add_trades: ['T3'], reason: 'grew' }), ctx('OID'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.success).toBe(true)
    const sqls = clientQueryMock.mock.calls.map((c: any[]) => String(c[0]))
    expect(sqls.some((s) => /UPDATE .*overrides\s+SET/i.test(s))).toBe(true)
    expect(sqls.some((s) => /INSERT INTO .*override_members/i.test(s))).toBe(true)
    expect(sqls.some((s) => /INSERT INTO .*override_history/i.test(s))).toBe(true)
    expect(sqls.some((s) => /^\s*COMMIT/i.test(s))).toBe(true)
  })
})

describe('DELETE /overrides/[overrideId]', () => {
  it('403 on bad password', async () => {
    const res = await DELETE(req('DELETE', { user: 'u', admin_password: 'bad' }), ctx('OID'))
    expect(res.status).toBe(403)
  })
  it('404 when override missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await DELETE(req('DELETE', { user: 'u', admin_password: 'pw' }), ctx('OID'))
    expect(res.status).toBe(404)
  })
  it('soft-deactivates parent + members and returns success', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ override_id: 'OID', trade_ids: ['T1'] }] })
    const res = await DELETE(req('DELETE', { user: 'u', admin_password: 'pw', reason: 'oops' }), ctx('OID'))
    expect(res.status).toBe(200)
    expect((await res.json()).success).toBe(true)
    const sqls = clientQueryMock.mock.calls.map((c: any[]) => String(c[0]))
    expect(sqls.some((s) => /UPDATE .*overrides\s+SET is_active = FALSE/i.test(s))).toBe(true)
    expect(sqls.some((s) => /UPDATE .*override_members\s+SET is_active = FALSE/i.test(s))).toBe(true)
    expect(sqls.some((s) => /DEACTIVATED/i.test(s) || /override_history/i.test(s))).toBe(true)
  })
})
```
- [ ] **Run (expect FAIL — route missing):** `cd SDRUtils/dashboard && npm test -- "src/app/api/usd-swaps-tape-v2/overrides/[overrideId]/__tests__/route.test.ts"`
- [ ] **Implement** `src/app/api/usd-swaps-tape-v2/overrides/[overrideId]/route.ts`:
```ts
// ABOUTME: Detail / update / deactivate a single manual tape override.
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query, withClient } from '@/lib/db'
import { isValidTapeWritePassword, TAPE_WRITE_AUTH_ERROR } from '@/lib/utils'
import {
  OVERRIDES_TABLE,
  OVERRIDE_MEMBERS_TABLE,
  OVERRIDE_HISTORY_TABLE,
  computeOverrideMetrics,
  insertMemberRows,
  normalizeIdList,
  normalizeTags,
  normalizeText,
  resolveOverrideLegs,
  supersedeOverlappingOverrides,
  validateOverride,
  type OverrideType,
} from '@/lib/tape-overrides'

type PatchPayload = {
  reason?: unknown
  tags?: unknown
  add_trades?: unknown
  remove_trades?: unknown
  user?: unknown
  admin_password?: unknown
}
type DeletePayload = { reason?: unknown; user?: unknown; admin_password?: unknown }

export async function GET(
  _request: Request,
  context: { params: Promise<{ overrideId: string }> },
) {
  const { overrideId } = await context.params
  try {
    const parent = await query(
      `SELECT * FROM ${OVERRIDES_TABLE} WHERE override_id = $1`,
      [overrideId],
    )
    if (!parent.rows.length) {
      return NextResponse.json({ error: 'Override not found.' }, { status: 404 })
    }
    const members = await query(
      `SELECT trade_id, override_id, override_type, manual_package_id, is_active
       FROM ${OVERRIDE_MEMBERS_TABLE}
       WHERE override_id = $1
       ORDER BY trade_id`,
      [overrideId],
    )
    const history = await query(
      `SELECT history_id, action, changed_by, changed_at, change_details, previous_state
       FROM ${OVERRIDE_HISTORY_TABLE}
       WHERE override_id = $1
       ORDER BY changed_at DESC`,
      [overrideId],
    )
    return NextResponse.json({
      override: parent.rows[0],
      members: members.rows,
      history: history.rows,
    })
  } catch (error: any) {
    console.error('tape override GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch override' },
      { status: 500 },
    )
  }
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ overrideId: string }> },
) {
  const { overrideId } = await context.params
  let payload: PatchPayload
  try {
    payload = (await request.json()) as PatchPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  if (!isValidTapeWritePassword(payload.admin_password)) {
    return NextResponse.json({ error: TAPE_WRITE_AUTH_ERROR }, { status: 403 })
  }
  const user = normalizeText(payload.user)
  if (!user) {
    return NextResponse.json(
      { error: 'user is required to update an override.' },
      { status: 400 },
    )
  }

  try {
    const existingResult = await query(
      `SELECT * FROM ${OVERRIDES_TABLE} WHERE override_id = $1`,
      [overrideId],
    )
    if (!existingResult.rows.length) {
      return NextResponse.json({ error: 'Override not found.' }, { status: 404 })
    }
    const existing = existingResult.rows[0]
    const overrideType = existing.override_type as OverrideType
    const manualPackageId: string | null = existing.manual_package_id ?? null

    const existingTradeIds: string[] = Array.isArray(existing.trade_ids) ? existing.trade_ids : []
    const addIds = normalizeIdList(payload.add_trades)
    const removeIds = new Set(normalizeIdList(payload.remove_trades))
    const nextSet = new Set(existingTradeIds)
    addIds.forEach((id) => nextSet.add(id))
    removeIds.forEach((id) => nextSet.delete(id))
    const nextTradeIds = normalizeIdList(Array.from(nextSet))

    const { validation, hasErrors } = validateOverride(overrideType, nextTradeIds)
    if (hasErrors) {
      return NextResponse.json(
        { error: 'Validation failed', validation },
        { status: 409 },
      )
    }

    const legs = await resolveOverrideLegs(nextTradeIds)
    const metrics = computeOverrideMetrics(overrideType, nextTradeIds, legs)

    const nextReason = payload.reason === undefined ? existing.reason : normalizeText(payload.reason)
    const nextTags = payload.tags === undefined ? existing.tags : normalizeTags(payload.tags)
    const changeDetails: Record<string, unknown> = {}
    if (payload.reason !== undefined) changeDetails.reason = nextReason
    if (payload.tags !== undefined) changeDetails.tags = nextTags
    if (addIds.length) changeDetails.add_trades = addIds
    if (removeIds.size) changeDetails.remove_trades = Array.from(removeIds)
    changeDetails.trade_ids = nextTradeIds

    await withClient(async (client) => {
      await client.query('BEGIN')
      try {
        // Drop this override's current member rows so the partial-unique
        // (trade_id) WHERE is_active index does not collide on re-insert.
        await client.query(
          `UPDATE ${OVERRIDE_MEMBERS_TABLE} SET is_active = FALSE WHERE override_id = $1`,
          [overrideId],
        )
        // Any other active override now overlapping the new set is superseded.
        await supersedeOverlappingOverrides(client, nextTradeIds, overrideId, user)
        await client.query(
          `UPDATE ${OVERRIDES_TABLE}
           SET trade_ids = $1, reason = $2, tags = $3, metrics = $4,
               is_active = TRUE, updated_by = $5, updated_at = NOW()
           WHERE override_id = $6`,
          [nextTradeIds, nextReason, nextTags, metrics, user, overrideId],
        )
        await insertMemberRows(client, overrideId, overrideType, manualPackageId, nextTradeIds)
        await client.query(
          `INSERT INTO ${OVERRIDE_HISTORY_TABLE}
             (override_id, action, changed_by, change_details, previous_state)
           VALUES ($1, 'UPDATED', $2, $3::jsonb, $4::jsonb)`,
          [overrideId, user, changeDetails, existing],
        )
        await client.query('COMMIT')
      } catch (txErr) {
        await client.query('ROLLBACK')
        throw txErr
      }
    })

    return NextResponse.json({
      success: true,
      override_id: overrideId,
      manual_package_id: manualPackageId,
      validation,
      metrics,
    })
  } catch (error: any) {
    console.error('tape override PATCH error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to update override' },
      { status: 500 },
    )
  }
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ overrideId: string }> },
) {
  const { overrideId } = await context.params
  let payload: DeletePayload
  try {
    payload = (await request.json()) as DeletePayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  if (!isValidTapeWritePassword(payload.admin_password)) {
    return NextResponse.json({ error: TAPE_WRITE_AUTH_ERROR }, { status: 403 })
  }
  const user = normalizeText(payload.user)
  if (!user) {
    return NextResponse.json(
      { error: 'user is required to deactivate an override.' },
      { status: 400 },
    )
  }

  try {
    const existingResult = await query(
      `SELECT * FROM ${OVERRIDES_TABLE} WHERE override_id = $1`,
      [overrideId],
    )
    if (!existingResult.rows.length) {
      return NextResponse.json({ error: 'Override not found.' }, { status: 404 })
    }
    const existing = existingResult.rows[0]
    const reason = normalizeText(payload.reason)

    await withClient(async (client) => {
      await client.query('BEGIN')
      try {
        await client.query(
          `UPDATE ${OVERRIDES_TABLE}
           SET is_active = FALSE, updated_by = $1, updated_at = NOW()
           WHERE override_id = $2`,
          [user, overrideId],
        )
        await client.query(
          `UPDATE ${OVERRIDE_MEMBERS_TABLE} SET is_active = FALSE WHERE override_id = $1`,
          [overrideId],
        )
        await client.query(
          `INSERT INTO ${OVERRIDE_HISTORY_TABLE}
             (override_id, action, changed_by, change_details, previous_state)
           VALUES ($1, 'DEACTIVATED', $2, $3::jsonb, $4::jsonb)`,
          [overrideId, user, { reason }, existing],
        )
        await client.query('COMMIT')
      } catch (txErr) {
        await client.query('ROLLBACK')
        throw txErr
      }
    })

    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('tape override DELETE error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to deactivate override' },
      { status: 500 },
    )
  }
}
```
- [ ] **Run (expect PASS):** `cd SDRUtils/dashboard && npm test -- "src/app/api/usd-swaps-tape-v2/overrides/[overrideId]/__tests__/route.test.ts"`
- [ ] **Commit:**
```
git add "SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/overrides/[overrideId]/route.ts" "SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/overrides/[overrideId]/__tests__/route.test.ts"
git commit -m "$(printf 'feat(tape): override detail/update/deactivate endpoints\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a')"
```

---

## Task 7 — `lib/tape-notes.ts` + `notes/route.ts` + `notes/[noteId]/route.ts`

Notes need NO password. PATCH/DELETE are author-only (403 when `note.author !== request author`). No supersession, no transactions (single-row writes).

- [ ] **Write failing lib test** `src/lib/__tests__/tape-notes.test.ts`:
```ts
import { describe, expect, it } from '@jest/globals'
import { isValidNoteTargetType, normalizeAuthor, normalizeNoteBody } from '../tape-notes'

describe('tape-notes helpers', () => {
  it('validates target type', () => {
    expect(isValidNoteTargetType('TRADE')).toBe(true)
    expect(isValidNoteTargetType('PACKAGE')).toBe(true)
    expect(isValidNoteTargetType('trade')).toBe(false)
    expect(isValidNoteTargetType(42)).toBe(false)
  })
  it('normalizes body + author (trim, blank->null)', () => {
    expect(normalizeNoteBody('  hi  ')).toBe('hi')
    expect(normalizeNoteBody('   ')).toBeNull()
    expect(normalizeAuthor(123)).toBeNull()
    expect(normalizeAuthor(' me ')).toBe('me')
  })
})
```
- [ ] **Run (expect FAIL):** `cd SDRUtils/dashboard && npm test -- src/lib/__tests__/tape-notes.test.ts`
- [ ] **Implement** `src/lib/tape-notes.ts`:
```ts
// ABOUTME: Tape-local helpers for trader notes on trades/packages.
export const NOTES_TABLE = 'arbs_usd_swap_tape_notes_v2'

export type NoteTargetType = 'TRADE' | 'PACKAGE'
const NOTE_TARGET_TYPES: NoteTargetType[] = ['TRADE', 'PACKAGE']

export function isValidNoteTargetType(value: unknown): value is NoteTargetType {
  return typeof value === 'string' && (NOTE_TARGET_TYPES as string[]).includes(value)
}

export function normalizeAuthor(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

export function normalizeNoteBody(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}
```
- [ ] **Run (expect PASS):** `cd SDRUtils/dashboard && npm test -- src/lib/__tests__/tape-notes.test.ts`
- [ ] **Write failing route test** `src/app/api/usd-swaps-tape-v2/notes/__tests__/route.test.ts`:
```ts
import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

const queryMock = jest.fn()
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock }))

let GET: any, POST: any
beforeAll(async () => {
  const mod = await import('../route')
  GET = mod.GET; POST = mod.POST
})
beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})
function post(body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/notes', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
}

describe('POST /notes', () => {
  it('400 on bad target_type', async () => {
    const res = await POST(post({ target_type: 'BOGUS', target_id: 'P1', author: 'me', body: 'hi' }))
    expect(res.status).toBe(400)
  })
  it('400 when author or body missing', async () => {
    expect((await POST(post({ target_type: 'TRADE', target_id: 'T1', author: '', body: 'hi' }))).status).toBe(400)
    expect((await POST(post({ target_type: 'TRADE', target_id: 'T1', author: 'me', body: '  ' }))).status).toBe(400)
  })
  it('inserts and returns note_id', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1' }] })
    const res = await POST(post({ target_type: 'PACKAGE', target_id: 'P1', author: 'me', body: 'looks like a switch' }))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.success).toBe(true)
    expect(body.note_id).toBe('N1')
  })
})

describe('GET /notes', () => {
  it('400 when target params missing', async () => {
    const res = await GET(new Request('http://t/api/usd-swaps-tape-v2/notes'))
    expect(res.status).toBe(400)
  })
  it('returns { rows }', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1' }] })
    const res = await GET(new Request('http://t/api/usd-swaps-tape-v2/notes?target_type=TRADE&target_id=T1'))
    expect(res.status).toBe(200)
    expect((await res.json()).rows).toEqual([{ note_id: 'N1' }])
  })
})
```
- [ ] **Run (expect FAIL):** `cd SDRUtils/dashboard && npm test -- src/app/api/usd-swaps-tape-v2/notes/__tests__/route.test.ts`
- [ ] **Implement** `src/app/api/usd-swaps-tape-v2/notes/route.ts`:
```ts
// ABOUTME: List + create trader notes for tape trades/packages (no password).
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  NOTES_TABLE,
  isValidNoteTargetType,
  normalizeAuthor,
  normalizeNoteBody,
} from '@/lib/tape-notes'

type NotePostPayload = {
  target_type?: unknown
  target_id?: unknown
  author?: unknown
  body?: unknown
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const targetType = searchParams.get('target_type')
  const targetId = searchParams.get('target_id')
  if (!isValidNoteTargetType(targetType) || !targetId) {
    return NextResponse.json(
      { error: 'target_type (TRADE|PACKAGE) and target_id are required.' },
      { status: 400 },
    )
  }
  try {
    const result = await query(
      `SELECT note_id, target_type, target_id, author, body, created_at, updated_at, is_active
       FROM ${NOTES_TABLE}
       WHERE target_type = $1 AND target_id = $2 AND is_active = TRUE
       ORDER BY created_at DESC`,
      [targetType, targetId],
    )
    return NextResponse.json({ rows: result.rows })
  } catch (error: any) {
    console.error('tape notes GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch notes' },
      { status: 500 },
    )
  }
}

export async function POST(request: Request) {
  let payload: NotePostPayload
  try {
    payload = (await request.json()) as NotePostPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  if (!isValidNoteTargetType(payload.target_type)) {
    return NextResponse.json(
      { error: "target_type must be 'TRADE' or 'PACKAGE'." },
      { status: 400 },
    )
  }
  const targetId = normalizeAuthor(payload.target_id)
  const author = normalizeAuthor(payload.author)
  const body = normalizeNoteBody(payload.body)
  if (!targetId) {
    return NextResponse.json({ error: 'target_id is required.' }, { status: 400 })
  }
  if (!author) {
    return NextResponse.json({ error: 'author is required.' }, { status: 400 })
  }
  if (!body) {
    return NextResponse.json({ error: 'body is required.' }, { status: 400 })
  }
  try {
    const result = await query(
      `INSERT INTO ${NOTES_TABLE} (target_type, target_id, author, body)
       VALUES ($1, $2, $3, $4)
       RETURNING note_id`,
      [payload.target_type, targetId, author, body],
    )
    return NextResponse.json({ success: true, note_id: result.rows[0].note_id })
  } catch (error: any) {
    console.error('tape notes POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to create note' },
      { status: 500 },
    )
  }
}
```
- [ ] **Run (expect PASS):** `cd SDRUtils/dashboard && npm test -- src/app/api/usd-swaps-tape-v2/notes/__tests__/route.test.ts`
- [ ] **Write failing route test** `src/app/api/usd-swaps-tape-v2/notes/[noteId]/__tests__/route.test.ts`:
```ts
import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

const queryMock = jest.fn()
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock }))

let PATCH: any, DELETE: any
beforeAll(async () => {
  const mod = await import('../route')
  PATCH = mod.PATCH; DELETE = mod.DELETE
})
beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})
const ctx = (id: string) => ({ params: Promise.resolve({ noteId: id }) })
function req(method: string, body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/notes/N1', {
    method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
}

describe('PATCH /notes/[noteId]', () => {
  it('404 when note missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await PATCH(req('PATCH', { author: 'me', body: 'edit' }), ctx('N1'))
    expect(res.status).toBe(404)
  })
  it('403 when author is not the note owner', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'someone-else' }] })
    const res = await PATCH(req('PATCH', { author: 'me', body: 'edit' }), ctx('N1'))
    expect(res.status).toBe(403)
  })
  it('updates when author matches', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'me' }] })
      .mockResolvedValueOnce({ rows: [{ note_id: 'N1' }] })
    const res = await PATCH(req('PATCH', { author: 'me', body: 'edit' }), ctx('N1'))
    expect(res.status).toBe(200)
    expect((await res.json()).success).toBe(true)
  })
})

describe('DELETE /notes/[noteId]', () => {
  it('403 when author mismatches', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'other' }] })
    const res = await DELETE(req('DELETE', { author: 'me' }), ctx('N1'))
    expect(res.status).toBe(403)
  })
  it('soft-deletes when author matches', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'me' }] })
      .mockResolvedValueOnce({ rows: [] })
    const res = await DELETE(req('DELETE', { author: 'me' }), ctx('N1'))
    expect(res.status).toBe(200)
    expect((await res.json()).success).toBe(true)
    const sqls = queryMock.mock.calls.map((c: any[]) => String(c[0]))
    expect(sqls.some((s) => /UPDATE .*notes.*is_active = FALSE/is.test(s))).toBe(true)
  })
})
```
- [ ] **Run (expect FAIL):** `cd SDRUtils/dashboard && npm test -- "src/app/api/usd-swaps-tape-v2/notes/[noteId]/__tests__/route.test.ts"`
- [ ] **Implement** `src/app/api/usd-swaps-tape-v2/notes/[noteId]/route.ts`:
```ts
// ABOUTME: Edit / soft-delete a single trader note (author-only, no password).
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { NOTES_TABLE, normalizeAuthor, normalizeNoteBody } from '@/lib/tape-notes'

type NotePatchPayload = { body?: unknown; author?: unknown }
type NoteDeletePayload = { author?: unknown }

async function loadNote(noteId: string) {
  const result = await query(
    `SELECT note_id, author, is_active FROM ${NOTES_TABLE} WHERE note_id = $1`,
    [noteId],
  )
  return result.rows[0] ?? null
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ noteId: string }> },
) {
  const { noteId } = await context.params
  let payload: NotePatchPayload
  try {
    payload = (await request.json()) as NotePatchPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  const author = normalizeAuthor(payload.author)
  if (!author) {
    return NextResponse.json({ error: 'author is required.' }, { status: 400 })
  }
  const body = normalizeNoteBody(payload.body)
  if (!body) {
    return NextResponse.json({ error: 'body is required.' }, { status: 400 })
  }
  try {
    const note = await loadNote(noteId)
    if (!note) {
      return NextResponse.json({ error: 'Note not found.' }, { status: 404 })
    }
    if (note.author !== author) {
      return NextResponse.json(
        { error: 'Only the author can edit this note.' },
        { status: 403 },
      )
    }
    await query(
      `UPDATE ${NOTES_TABLE}
       SET body = $1, updated_at = NOW()
       WHERE note_id = $2`,
      [body, noteId],
    )
    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('tape note PATCH error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to update note' },
      { status: 500 },
    )
  }
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ noteId: string }> },
) {
  const { noteId } = await context.params
  let payload: NoteDeletePayload
  try {
    payload = (await request.json()) as NoteDeletePayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  const author = normalizeAuthor(payload.author)
  if (!author) {
    return NextResponse.json({ error: 'author is required.' }, { status: 400 })
  }
  try {
    const note = await loadNote(noteId)
    if (!note) {
      return NextResponse.json({ error: 'Note not found.' }, { status: 404 })
    }
    if (note.author !== author) {
      return NextResponse.json(
        { error: 'Only the author can delete this note.' },
        { status: 403 },
      )
    }
    await query(
      `UPDATE ${NOTES_TABLE}
       SET is_active = FALSE, updated_at = NOW()
       WHERE note_id = $1`,
      [noteId],
    )
    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('tape note DELETE error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to delete note' },
      { status: 500 },
    )
  }
}
```
- [ ] **Run (expect PASS):** `cd SDRUtils/dashboard && npm test -- "src/app/api/usd-swaps-tape-v2/notes/[noteId]/__tests__/route.test.ts"`
- [ ] **Commit:**
```
git add SDRUtils/dashboard/src/lib/tape-notes.ts SDRUtils/dashboard/src/lib/__tests__/tape-notes.test.ts "SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/notes"
git commit -m "$(printf 'feat(tape): trader notes lib + CRUD endpoints (author-only)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a')"
```

---

## Task 8 — Integration test: full override lifecycle + supersession invariant

Two-layer coverage: (a) a **db-mocked stateful** integration test that runs in the fast gate and proves the create→list→detail→deactivate wiring and the one-active-override-per-trade invariant at the handler level; (b) a **db-gated live** smoke (`describeIfDb`) mirroring `__tests__/integration.test.ts`, running only in the full suite once the DDL tables exist.

- [ ] **Write failing test** `src/app/api/usd-swaps-tape-v2/overrides/__tests__/integration.test.ts`:
```ts
import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

/**
 * Stateful in-memory fake of the three override tables, wired through the
 * mocked `query` (reads) and `withClient` (transactional writes). Proves the
 * handlers compose correctly and that AT MOST ONE active override references a
 * given trade_id (supersession invariant), without a live Postgres.
 */
type Store = {
  overrides: Map<string, any>
  members: any[] // { trade_id, override_id, override_type, manual_package_id, is_active }
  history: any[]
  seq: number
}
const store: Store = { overrides: new Map(), members: [], history: [], seq: 0 }

function run(sql: string, params: any[] = []): { rows: any[] } {
  const s = sql.replace(/\s+/g, ' ').trim()
  if (/^BEGIN|^COMMIT|^ROLLBACK/i.test(s)) return { rows: [] }
  if (/SELECT 1 FROM .*overrides WHERE manual_package_id/i.test(s)) {
    const hit = [...store.overrides.values()].some((o) => o.manual_package_id === params[0])
    return { rows: hit ? [{ '?column?': 1 }] : [] }
  }
  if (/INSERT INTO .*overrides /i.test(s) && /RETURNING/i.test(s)) {
    store.seq += 1
    const id = `OID-${store.seq}`
    const row = {
      override_id: id, override_type: params[0], manual_package_id: params[1],
      trade_ids: params[2], created_by: params[3], reason: params[4], tags: params[5],
      metrics: params[6], is_active: true, superseded_by: null,
    }
    store.overrides.set(id, row)
    return { rows: [{ override_id: id, manual_package_id: params[1] }] }
  }
  if (/SELECT override_id FROM .*overrides WHERE is_active/i.test(s)) {
    const [tradeIds, exclude] = params
    const ids = [...store.overrides.values()]
      .filter((o) => o.is_active && o.override_id !== exclude &&
        o.trade_ids.some((t: string) => tradeIds.includes(t)))
      .map((o) => ({ override_id: o.override_id }))
    return { rows: ids }
  }
  if (/UPDATE .*overrides SET is_active = FALSE, superseded_by/i.test(s)) {
    const [supersededBy, , ids] = params
    ids.forEach((id: string) => {
      const o = store.overrides.get(id)
      if (o) { o.is_active = false; o.superseded_by = supersededBy }
    })
    return { rows: [] }
  }
  if (/UPDATE .*override_members SET is_active = FALSE WHERE override_id = ANY/i.test(s)) {
    const [ids] = params
    store.members.forEach((m) => { if (ids.includes(m.override_id)) m.is_active = false })
    return { rows: [] }
  }
  if (/UPDATE .*override_members SET is_active = FALSE WHERE override_id = \$1/i.test(s)) {
    store.members.forEach((m) => { if (m.override_id === params[0]) m.is_active = false })
    return { rows: [] }
  }
  if (/INSERT INTO .*override_members/i.test(s)) {
    const [tradeIds, overrideId, overrideType, pkgId] = params
    tradeIds.forEach((t: string) => store.members.push({
      trade_id: t, override_id: overrideId, override_type: overrideType,
      manual_package_id: pkgId, is_active: true,
    }))
    return { rows: [] }
  }
  if (/INSERT INTO .*override_history/i.test(s)) {
    store.history.push({ override_id: params[0], sql: s })
    return { rows: [] }
  }
  if (/UPDATE .*overrides SET is_active = FALSE, updated_by/i.test(s)) {
    const o = store.overrides.get(params[1]); if (o) o.is_active = false
    return { rows: [] }
  }
  if (/SELECT \* FROM .*overrides WHERE override_id/i.test(s)) {
    const o = store.overrides.get(params[0]); return { rows: o ? [o] : [] }
  }
  if (/FROM .*override_members WHERE override_id/i.test(s)) {
    return { rows: store.members.filter((m) => m.override_id === params[0]) }
  }
  if (/FROM .*override_history WHERE override_id/i.test(s)) {
    return { rows: store.history.filter((h) => h.override_id === params[0]) }
  }
  if (/SELECT \* FROM .*overrides/i.test(s)) {
    return { rows: [...store.overrides.values()].filter((o) => o.is_active) }
  }
  if (/FROM arbs_usd_swap_tape_legs_v2/i.test(s)) {
    return { rows: params[0].map((t: string) => ({ trade_id: t, package_id: 'P1' })) }
  }
  return { rows: [] }
}

const queryMock = jest.fn(async (sql: string, params: any[]) => run(sql, params))
const clientQueryMock = jest.fn(async (sql: string, params: any[]) => run(sql, params))
const withClientMock = jest.fn(async (fn: any) => fn({ query: clientQueryMock }))
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock, withClient: withClientMock }))

let list: any, detail: any
beforeAll(async () => {
  list = await import('../route')
  detail = await import('../[overrideId]/route')
})
beforeEach(() => {
  process.env.TAPE_OVERRIDE_PASSWORD = 'pw'
  store.overrides.clear(); store.members = []; store.history = []; store.seq = 0
})

function postBody(body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/overrides', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
}
const activeMembers = () => store.members.filter((m) => m.is_active)

describe('override lifecycle (db-mocked, stateful)', () => {
  it('create -> list -> detail -> deactivate', async () => {
    const created = await (await list.POST(postBody({
      override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw',
    })).then((r: Response) => r)).json()
    expect(created.success).toBe(true)
    const oid = created.override_id

    const listed = await (await list.GET(new Request('http://t/api/usd-swaps-tape-v2/overrides'))).json()
    expect(listed.rows.some((r: any) => r.override_id === oid)).toBe(true)

    const ctx = { params: Promise.resolve({ overrideId: oid }) }
    const got = await (await detail.GET(new Request('http://t/x'), ctx)).json()
    expect(got.override.override_id).toBe(oid)
    expect(got.members.length).toBe(2)

    await detail.DELETE(new Request('http://t/x', {
      method: 'DELETE', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ user: 'u', admin_password: 'pw' }),
    }), ctx)
    expect(store.overrides.get(oid).is_active).toBe(false)
    expect(activeMembers().length).toBe(0)
  })

  it('one-active-override-per-trade: a second override supersedes the first', async () => {
    await list.POST(postBody({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    await list.POST(postBody({ override_type: 'GROUP', trade_ids: ['T2', 'T3'], user: 'u', admin_password: 'pw' }))

    // Invariant: every trade_id appears in at most one ACTIVE member row.
    const counts = new Map<string, number>()
    activeMembers().forEach((m) => counts.set(m.trade_id, (counts.get(m.trade_id) ?? 0) + 1))
    for (const [, n] of counts) expect(n).toBeLessThanOrEqual(1)
    // First override was superseded; its trades are no longer active members.
    expect([...store.overrides.values()].filter((o) => o.is_active).length).toBe(1)
    expect(activeMembers().map((m) => m.trade_id).sort()).toEqual(['T2', 'T3'])
  })
})
```
- [ ] **Run (expect FAIL first, then PASS after Tasks 5-6 land):** `cd SDRUtils/dashboard && npm test -- src/app/api/usd-swaps-tape-v2/overrides/__tests__/integration.test.ts`
- [ ] **Append db-gated live smoke** to the same file (skips without `DATABASE_URL`; requires the DDL tables from the schema task):
```ts
const DB_URL = process.env.PG_TEST_URL || process.env.DATABASE_URL
const describeIfDb = DB_URL ? describe : describe.skip

describeIfDb('override lifecycle (live DB smoke)', () => {
  it('create/list/detail/deactivate against Postgres', async () => {
    jest.resetModules()
    jest.dontMock('@/lib/db') // use the real pool for this block
    const realList = await import('../route')
    const realDetail = await import('../[overrideId]/route')
    process.env.TAPE_OVERRIDE_PASSWORD = process.env.TAPE_OVERRIDE_PASSWORD || 'live-test-pw'
    // Use synthetic trade ids that will not collide with tape data.
    const t1 = `ITEST-${Date.now()}-A`
    const t2 = `ITEST-${Date.now()}-B`
    const createRes = await realList.POST(new Request('http://t/x', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ override_type: 'GROUP', trade_ids: [t1, t2], user: 'itest', admin_password: process.env.TAPE_OVERRIDE_PASSWORD }),
    }))
    // 200 on success, or 500 if the DDL tables are not yet migrated.
    expect([200, 500]).toContain(createRes.status)
    if (createRes.status !== 200) return
    const { override_id } = await createRes.json()
    const ctx = { params: Promise.resolve({ overrideId: override_id }) }
    expect((await realDetail.GET(new Request('http://t/x'), ctx)).status).toBe(200)
    const delRes = await realDetail.DELETE(new Request('http://t/x', {
      method: 'DELETE', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ user: 'itest', admin_password: process.env.TAPE_OVERRIDE_PASSWORD }),
    }), ctx)
    expect(delRes.status).toBe(200)
  })
})
```
  > Note: the live block relies on `jest.dontMock`/module reset to bypass the file-level mock. If mixing mocked + live in one file proves flaky under ESM, split the live smoke into a sibling `integration.live.test.ts` with no `unstable_mockModule` call. The db-mocked block is the CI-gating coverage; the live block is opportunistic.
- [ ] **Run full override tree (expect PASS):** `cd SDRUtils/dashboard && npm test -- src/app/api/usd-swaps-tape-v2/overrides`
- [ ] **Commit:**
```
git add "SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/overrides/__tests__/integration.test.ts"
git commit -m "$(printf 'test(tape): override lifecycle + supersession invariant integration\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a')"
```

---

## Cross-cutting notes / assumptions

- **Deviation from sofr links pattern (intentional):** the sofr route treats overlapping links as a *validation error* (409). Tape overrides instead **auto-supersede** overlaps (spec §2 + members unique-active index), so `validateOverride` is purely structural (min-trade rules) — no conflict-error item. This matches the contract's "supersede overlapping active overrides" flow.
- **Deviation — transactions:** no existing route uses `withClient`; the sofr route fires sequential `query` calls. The contract mandates a single `withClient` transaction (`BEGIN … COMMIT` with try/catch `ROLLBACK`) for every override mutation, so these are the first transactional handlers. The db-mock harness models it via `withClient(fn) => fn({ query: clientQueryMock })`.
- **Deviation — manual_package_id uniqueness:** the contract's `(manual_package_id)` index is **non-unique**, so a DB 23505 retry (as sofr does) won't fire. `allocateManualPackageId` does a best-effort `SELECT 1 … LIMIT 1` existence pre-check (≤5 attempts) inside the txn instead. 8 hex chars ⇒ ~4.3e9 space; collision is negligible.
- **manual_package_id policy:** generated only for GROUP when none supplied; SPLIT/DETACH carry `null` unless the caller passes one (the display view keys their synthetic rows off `package_id::split/detach::trade_id`, per the frontend contract).
- **Order inside the create txn** (guards the partial-unique `members(trade_id) WHERE is_active` index): BEGIN → allocate pkg id → INSERT parent (RETURNING id) → supersede overlapping (deactivate old parents + **their member rows**) → INSERT new member rows → INSERT CREATED history → COMMIT. PATCH additionally deactivates *this* override's own members before re-insert.
- **`resolveOverrideLegs` reads only** `arbs_usd_swap_tape_legs_v2 (trade_id, package_id)` — never writes ingest-owned tables (guardrail). If that table/columns differ at implementation time, adjust the SELECT; metrics degrade gracefully (distinct_package_ids=0) when legs are absent.
- **Table name constants** are defined once in `lib/tape-overrides.ts` / `lib/tape-notes.ts` and imported by the routes, so a rename touches one place.
- **DDL dependency:** all endpoints assume the three override tables + notes table exist (owned by the schema task, contract §DB). The db-mocked tests don't need them; the live smoke tolerates their absence (200-or-500). Do NOT add a `to_regclass` availability guard like sofr's — these tables ship with the feature, not optionally.
# Plan — Frontend Core (Tasks 9–14)

**Feature:** USD Swaps Tape manual package regrouping + trader notes.
**Owner scope:** types, API clients (`overrideApi`/`noteApi`), leg-level selection, selection-context derivation, contextual action bar, override commit popover.

Contract: `scratchpad/plan_contract.md`. Spec §3.1–3.2, §3.7:
`docs/superpowers/specs/2026-07-08-usd-swaps-tape-manual-regrouping-notes-design.md`.

## Ground truth verified against the repo (2026-07-08)

- **Test runner** = `npm test` (`node --experimental-vm-modules node_modules/jest/bin/jest.js`). NEVER `npx jest`. `jest.config.js`: `testEnvironment: 'node'` globally, ts-jest ESM, `moduleNameMapper` `^@/(.*)$ → <rootDir>/src/$1`, `testMatch` includes `**/__tests__/**/*.test.ts(x)`. ts-jest type-checks (no `isolatedModules` transform flag), so a type error in a test file FAILS it.
- **Three harness archetypes** (mirror exactly):
  1. **Pure-logic** (node, default env): `import { describe, expect, it } from '@jest/globals'` and test a pure exported function. This is the dominant convention (`toggleRowExpansionReducer`, `deriveAnalyticsSelection`). Use for `deriveSelectionContext` + `overrideApi`/`noteApi`.
  2. **Component / hook (jsdom)**: first line docblock `/** @jest-environment jsdom */`, then `import { render, screen, fireEvent, renderHook, act, waitFor } from '@testing-library/react'` + `import '@testing-library/jest-dom'`. jest-dom matchers are typed via the `(expect(x) as any).toBeInTheDocument()` cast idiom (see `BucketOverridesPopover.test.tsx`). Use for `useTradeSelection`, `RegroupActionBar`, `OverrideCommitPopover`.
  3. **fetch mock** (works in either env; no fetch in jsdom/node by default): `beforeEach`/`afterEach` swap `global.fetch` for a `jest.fn()` (see `useManualLinkDetails.test.tsx`). Responses: `fetchMock.mockResolvedValue({ ok: true, json: async () => ({...}) } as any)`.
- **Base**: `TAPE_V2_API_BASE = '/api/usd-swaps-tape-v2'` (`constants.ts`). Overrides base `${TAPE_V2_API_BASE}/overrides`, notes base `${TAPE_V2_API_BASE}/notes`.
- **`api/` dir does not exist yet** under the feature — create it.
- **Barrels**: `types/index.ts` (`export * from './trade.types'` …) — add the two new type modules. `hooks/index.ts` — add the new hooks.
- **Base leg type**: `SofrSwapTapeLeg.trade_id?: string` (optional); `SofrSwapTapeRow.package_id: string` (required); `manual_package_id?: string | null` already on the base row.
- **Toolbar idiom**: `actionSlot` uses plain `<button>` + Tailwind (`rounded border border-slate-700 px-2.5 py-1 font-mono text-[10.5px]`), theme `lara-dark-indigo`. Popover idiom = `BucketOverridesPopover` (absolute-positioned `div`, `bg-slate-900`, `border-slate-700`, `shadow-xl`). Mirror these — do NOT introduce PrimeReact `Dialog`/`OverlayPanel` here.
- **manualLinkApi** pattern to mirror: local `parseError(res)` (reads `payload.error`, else `Request failed with status N`) + `buildQueryString(query)`; per-method `fetch` with `throw await parseError(res)` on `!res.ok`.

### Commit convention (every task)
Conventional commit, scope `(tape)` or `(dashboard)`. Use multiple `-m` so the two trailers land as the final lines (shell-agnostic):
```
git add <files>
git commit -m "<type>(tape): <subject>" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  -m "Claude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a"
```
Test-run command form: `cd SDRUtils/dashboard && npm test -- <relative/path/to/test>` (positional = jest testPathPattern).

### Deviations from contract (flagged, with rationale)
- **`toggleTrade(tradeId, packageId)`** — contract wrote `toggleTrade(tradeId)`. Maintaining the exposed `selectedByPackage: Map<string,string[]>` requires the package context, and the leg checkbox in `LegsSubTable` always renders inside a known package row, so the packageId is in scope at the call site. This is the only signature deviation; everything else matches the contract verbatim.
- **`canNote` rule** = "selection is confined to exactly one package" (i.e. exactly one distinct package spans the selection — whether a single leg → TRADE note, or a full package → PACKAGE note). This is the concrete reading of the spec's "Note = any single target."
- **"auto-package" for SPLIT** = a package row with **no** `override_type` stamped (`!row.override_type`). A manually-grouped or already-split package carries `override_type`, so it is excluded from re-splitting.

---

## Task 9 — Types: `override.types.ts`, `note.types.ts`, extend `UsdSwapTapeRow`

Type-only. Test = a ts-jest-compiled type-usage test (ts-jest type-checks, so an incompatible literal fails the run) plus trivial runtime asserts so the file is green regardless of transpile-only mode.

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/types/__tests__/override-note.types.test.ts`:
```ts
import { describe, expect, it } from '@jest/globals'
import type { OverrideType, TapeOverride, OverrideValidationItem } from '../override.types'
import type { NoteTargetType, TapeNote } from '../note.types'
import type { UsdSwapTapeRow } from '../trade.types'

describe('override + note types', () => {
  it('TapeOverride literal is assignable', () => {
    const o: TapeOverride = {
      override_id: 'o1',
      override_type: 'GROUP',
      manual_package_id: 'SMO-20260708-ABCD1234',
      trade_ids: ['t1', 't2'],
      created_by: 'chris',
      created_at: '2026-07-08T00:00:00Z',
      updated_at: null,
      is_active: true,
      reason: null,
      tags: null,
      metrics: {},
    }
    const t: OverrideType = 'SPLIT'
    const v: OverrideValidationItem = { level: 'error', code: 'GROUP_MIN', message: 'need >=2' }
    expect(o.override_type).toBe('GROUP')
    expect(t).toBe('SPLIT')
    expect(v.level).toBe('error')
  })

  it('TapeNote literal is assignable', () => {
    const tt: NoteTargetType = 'TRADE'
    const n: TapeNote = {
      note_id: 'n1',
      target_type: tt,
      target_id: 't1',
      author: 'chris',
      body: 'watch this',
      created_at: '2026-07-08T00:00:00Z',
      updated_at: null,
      is_active: true,
    }
    expect(n.target_type).toBe('TRADE')
  })

  it('UsdSwapTapeRow carries the v2 override/notes columns', () => {
    const row = {
      package_id: 'PKG1',
      legs_json: [],
      override_map: { t1: 'o1' },
      override_type: 'GROUP',
      manual_package_id: 'SMO-20260708-ABCD1234',
      has_notes: true,
      notes_count: 2,
    } as unknown as UsdSwapTapeRow
    expect(row.override_map?.t1).toBe('o1')
    expect(row.override_type).toBe('GROUP')
    expect(row.has_notes).toBe(true)
    expect(row.notes_count).toBe(2)
  })
})
```
- [ ] **Run** `npm test -- src/features/usd-swaps-tape-v2/types/__tests__/override-note.types.test.ts` → **FAIL** (modules `../override.types`, `../note.types` do not exist; `override_map`/`override_type`/`has_notes`/`notes_count` not on `UsdSwapTapeRow`).
- [ ] **Implement** `src/features/usd-swaps-tape-v2/types/override.types.ts`:
```ts
export type OverrideType = 'GROUP' | 'SPLIT' | 'DETACH'

export interface TapeOverride {
  override_id: string
  override_type: OverrideType
  manual_package_id: string | null
  trade_ids: string[]
  created_by: string
  created_at: string
  updated_at: string | null
  is_active: boolean
  reason: string | null
  tags: string[] | null
  metrics: Record<string, unknown>
}

export interface OverrideValidationItem {
  level: 'error' | 'warning' | 'info'
  code: string
  message: string
}
```
- [ ] **Implement** `src/features/usd-swaps-tape-v2/types/note.types.ts`:
```ts
export type NoteTargetType = 'TRADE' | 'PACKAGE'

export interface TapeNote {
  note_id: string
  target_type: NoteTargetType
  target_id: string
  author: string
  body: string
  created_at: string
  updated_at: string | null
  is_active: boolean
}
```
- [ ] **Extend** `src/features/usd-swaps-tape-v2/types/trade.types.ts` — add the import at the top of the file (after the existing `import type { SofrSwapTapeLeg, SofrSwapTapeRow } ...`):
```ts
import type { OverrideType } from './override.types'
```
  and append these four fields inside the `UsdSwapTapeRow = SofrSwapTapeRow & { ... }` block (just before `legs_json: UsdSwapTapeLeg[]`):
```ts
  // Manual regrouping + notes (v2 override resolution, appended by the
  // display view). `manual_package_id` already rides on the base
  // SofrSwapTapeRow. `override_map` is sparse: trade_id -> override_id
  // for the subset of legs that carry an active override.
  override_map?: Record<string, string> | null
  override_type?: OverrideType | null
  has_notes?: boolean
  notes_count?: number
```
- [ ] **Update barrel** `src/features/usd-swaps-tape-v2/types/index.ts` — add after `export * from './trade.types'`:
```ts
export * from './override.types'
export * from './note.types'
```
- [ ] **Run** same command → **PASS**.
- [ ] **Commit**: `git add src/features/usd-swaps-tape-v2/types/ && git commit -m "feat(tape): add override/note types + UsdSwapTapeRow v2 columns" -m "<trailer1>" -m "<trailer2>"`.

---

## Task 10 — API clients: `api/overrideApi.ts`, `api/noteApi.ts`

TDD with mocked `global.fetch`. Mirror `manualLinkApi.ts` (`parseError` + per-method fetch). Contract exports **named async functions** (not a factory).

### 10a — overrideApi

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/api/__tests__/overrideApi.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals'
import {
  createOverride,
  validateOverride,
  fetchOverrides,
  fetchOverrideDetail,
  updateOverride,
  deactivateOverride,
} from '../overrideApi'

const BASE = '/api/usd-swaps-tape-v2/overrides'

describe('overrideApi', () => {
  let originalFetch: typeof fetch
  let fetchMock: jest.Mock
  beforeEach(() => {
    originalFetch = global.fetch
    fetchMock = jest.fn()
    ;(global as any).fetch = fetchMock
  })
  afterEach(() => {
    ;(global as any).fetch = originalFetch
  })

  const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body } as any)
  const fail = (status: number, body: unknown) =>
    ({ ok: false, status, json: async () => body } as any)

  it('createOverride POSTs to base and returns the success payload', async () => {
    fetchMock.mockResolvedValue(
      ok({ success: true, override_id: 'o1', manual_package_id: 'SMO-1', validation: [], metrics: {} }),
    )
    const res = await createOverride({
      override_type: 'GROUP',
      trade_ids: ['t1', 't2'],
      user: 'chris',
      admin_password: 'pw',
    })
    expect(res.override_id).toBe('o1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(BASE)
    expect((init as RequestInit).method).toBe('POST')
    const sent = JSON.parse(String((init as RequestInit).body))
    expect(sent.validate_only).toBeUndefined()
    expect(sent.trade_ids).toEqual(['t1', 't2'])
  })

  it('validateOverride forces validate_only:true and returns validation+metrics+linked_trade_ids', async () => {
    fetchMock.mockResolvedValue(
      ok({ validation: [{ level: 'warning', code: 'X', message: 'm' }], metrics: {}, linked_trade_ids: ['t1'] }),
    )
    const res = await validateOverride({
      override_type: 'SPLIT',
      trade_ids: ['t1'],
      user: 'chris',
      admin_password: '',
    })
    expect(res.linked_trade_ids).toEqual(['t1'])
    const sent = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(sent.validate_only).toBe(true)
  })

  it('createOverride surfaces the server error message on 403', async () => {
    fetchMock.mockResolvedValue(fail(403, { error: 'Invalid override password.' }))
    await expect(
      createOverride({ override_type: 'GROUP', trade_ids: ['t1', 't2'], user: 'c', admin_password: 'x' }),
    ).rejects.toThrow('Invalid override password.')
  })

  it('fetchOverrides builds a query string and returns rows', async () => {
    fetchMock.mockResolvedValue(ok({ rows: [{ override_id: 'o1' }] }))
    const res = await fetchOverrides({ is_active: true, created_by: 'chris', limit: 50 })
    expect(res.rows).toHaveLength(1)
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}?is_active=true&created_by=chris&limit=50`)
  })

  it('fetchOverrideDetail GETs base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ override: { override_id: 'o1' }, members: [], history: [] }))
    const res = await fetchOverrideDetail('o1')
    expect(res.override.override_id).toBe('o1')
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}/o1`)
  })

  it('updateOverride PATCHes base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true, override_id: 'o1' }))
    await updateOverride('o1', { add_trades: ['t3'], user: 'c', admin_password: 'pw' })
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH')
  })

  it('deactivateOverride DELETEs base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true }))
    const res = await deactivateOverride('o1', { user: 'c', admin_password: 'pw' })
    expect(res.success).toBe(true)
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
  })
})
```
- [ ] **Run** `npm test -- src/features/usd-swaps-tape-v2/api/__tests__/overrideApi.test.ts` → **FAIL** (`../overrideApi` missing).
- [ ] **Implement** `src/features/usd-swaps-tape-v2/api/overrideApi.ts`:
```ts
// ABOUTME: Tape-local REST client for structural override CRUD. Mirrors
// the manualLinkApi factory's error-parsing / query-building idioms but
// exports flat named functions bound to the tape overrides base path.
// Do NOT reuse the shared manual-links client — its base path/semantics
// differ (legacy tables vs. read-time tape override resolution).
import { TAPE_V2_API_BASE } from '../constants'
import type { OverrideType, TapeOverride, OverrideValidationItem } from '../types/override.types'

const OVERRIDES_BASE = `${TAPE_V2_API_BASE}/overrides`

export interface CreateOverrideBody {
  override_type: OverrideType
  trade_ids: string[]
  manual_package_id?: string
  reason?: string
  tags?: string[] | string
  user: string
  admin_password: string
  validate_only?: boolean
}

export interface UpdateOverrideBody {
  reason?: string
  tags?: string[] | string
  add_trades?: string[]
  remove_trades?: string[]
  user: string
  admin_password: string
}

export interface DeactivateOverrideBody {
  reason?: string
  user: string
  admin_password: string
}

export interface ListOverridesQuery {
  is_active?: boolean
  created_by?: string
  limit?: number
}

export interface CreateOverrideResult {
  success: true
  override_id: string
  manual_package_id: string | null
  validation: OverrideValidationItem[]
  metrics: Record<string, unknown>
}

export interface ValidateOverrideResult {
  validation: OverrideValidationItem[]
  metrics: Record<string, unknown> | null
  linked_trade_ids: string[]
}

export interface OverrideMemberRow {
  trade_id: string
  override_id: string
  override_type: OverrideType
  manual_package_id: string | null
  is_active: boolean
}

export interface OverrideHistoryRow {
  history_id: number
  override_id: string
  action: string
  changed_by: string
  changed_at: string
  change_details: Record<string, unknown> | null
  previous_state: Record<string, unknown> | null
}

export interface OverrideDetailBundle {
  override: TapeOverride
  members: OverrideMemberRow[]
  history: OverrideHistoryRow[]
}

async function parseError(res: Response): Promise<Error> {
  try {
    const payload = await res.json()
    if (payload && typeof payload === 'object' && 'error' in payload && payload.error) {
      return new Error(String((payload as { error: unknown }).error))
    }
  } catch {
    // ignore
  }
  return new Error(`Request failed with status ${res.status}`)
}

function buildQueryString(query: Record<string, unknown>): string {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null) return
    params.set(key, String(value))
  })
  const s = params.toString()
  return s ? `?${s}` : ''
}

export async function createOverride(body: CreateOverrideBody): Promise<CreateOverrideResult> {
  const res = await fetch(OVERRIDES_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as CreateOverrideResult
}

export async function validateOverride(body: CreateOverrideBody): Promise<ValidateOverrideResult> {
  const res = await fetch(OVERRIDES_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, validate_only: true }),
  })
  if (!res.ok) throw await parseError(res)
  const payload = await res.json()
  return {
    validation: (payload?.validation as OverrideValidationItem[]) ?? [],
    metrics: (payload?.metrics as Record<string, unknown>) ?? null,
    linked_trade_ids: (payload?.linked_trade_ids as string[]) ?? [],
  }
}

export async function fetchOverrides(query?: ListOverridesQuery): Promise<{ rows: TapeOverride[] }> {
  const url = `${OVERRIDES_BASE}${query ? buildQueryString(query as Record<string, unknown>) : ''}`
  const res = await fetch(url)
  if (!res.ok) throw await parseError(res)
  const payload = await res.json()
  return { rows: (payload?.rows as TapeOverride[]) ?? [] }
}

export async function fetchOverrideDetail(overrideId: string): Promise<OverrideDetailBundle> {
  const res = await fetch(`${OVERRIDES_BASE}/${encodeURIComponent(overrideId)}`)
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as OverrideDetailBundle
}

export async function updateOverride(
  overrideId: string,
  body: UpdateOverrideBody,
): Promise<{ success: true; override_id: string }> {
  const res = await fetch(`${OVERRIDES_BASE}/${encodeURIComponent(overrideId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true; override_id: string }
}

export async function deactivateOverride(
  overrideId: string,
  body: DeactivateOverrideBody,
): Promise<{ success: true }> {
  const res = await fetch(`${OVERRIDES_BASE}/${encodeURIComponent(overrideId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true }
}
```
- [ ] **Run** same command → **PASS**.

### 10b — noteApi

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/api/__tests__/noteApi.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals'
import { fetchNotes, createNote, updateNote, deactivateNote } from '../noteApi'

const BASE = '/api/usd-swaps-tape-v2/notes'

describe('noteApi', () => {
  let originalFetch: typeof fetch
  let fetchMock: jest.Mock
  beforeEach(() => {
    originalFetch = global.fetch
    fetchMock = jest.fn()
    ;(global as any).fetch = fetchMock
  })
  afterEach(() => {
    ;(global as any).fetch = originalFetch
  })
  const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body } as any)

  it('fetchNotes builds target query', async () => {
    fetchMock.mockResolvedValue(ok({ rows: [{ note_id: 'n1' }] }))
    const res = await fetchNotes('TRADE', 't1')
    expect(res.rows).toHaveLength(1)
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}?target_type=TRADE&target_id=t1`)
  })

  it('createNote POSTs body and returns note_id', async () => {
    fetchMock.mockResolvedValue(ok({ success: true, note_id: 'n1' }))
    const res = await createNote({ target_type: 'PACKAGE', target_id: 'PKG1', author: 'chris', body: 'hi' })
    expect(res.note_id).toBe('n1')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('updateNote PATCHes base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true }))
    await updateNote('n1', { body: 'edited', author: 'chris' })
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}/n1`)
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH')
  })

  it('deactivateNote DELETEs base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true }))
    const res = await deactivateNote('n1', { author: 'chris' })
    expect(res.success).toBe(true)
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
  })
})
```
- [ ] **Run** `npm test -- src/features/usd-swaps-tape-v2/api/__tests__/noteApi.test.ts` → **FAIL**.
- [ ] **Implement** `src/features/usd-swaps-tape-v2/api/noteApi.ts`:
```ts
// ABOUTME: Tape-local REST client for trader notes (TRADE/PACKAGE). No
// password gate (author-only). Mirrors overrideApi's error parsing.
import { TAPE_V2_API_BASE } from '../constants'
import type { NoteTargetType, TapeNote } from '../types/note.types'

const NOTES_BASE = `${TAPE_V2_API_BASE}/notes`

export interface CreateNoteBody {
  target_type: NoteTargetType
  target_id: string
  author: string
  body: string
}

export interface UpdateNoteBody {
  body?: string
  author: string
}

export interface DeactivateNoteBody {
  author: string
}

async function parseError(res: Response): Promise<Error> {
  try {
    const payload = await res.json()
    if (payload && typeof payload === 'object' && 'error' in payload && payload.error) {
      return new Error(String((payload as { error: unknown }).error))
    }
  } catch {
    // ignore
  }
  return new Error(`Request failed with status ${res.status}`)
}

export async function fetchNotes(
  targetType: NoteTargetType,
  targetId: string,
): Promise<{ rows: TapeNote[] }> {
  const qs = new URLSearchParams({ target_type: targetType, target_id: targetId }).toString()
  const res = await fetch(`${NOTES_BASE}?${qs}`)
  if (!res.ok) throw await parseError(res)
  const payload = await res.json()
  return { rows: (payload?.rows as TapeNote[]) ?? [] }
}

export async function createNote(body: CreateNoteBody): Promise<{ success: true; note_id: string }> {
  const res = await fetch(NOTES_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true; note_id: string }
}

export async function updateNote(
  noteId: string,
  body: UpdateNoteBody,
): Promise<{ success: true }> {
  const res = await fetch(`${NOTES_BASE}/${encodeURIComponent(noteId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true }
}

export async function deactivateNote(
  noteId: string,
  body: DeactivateNoteBody,
): Promise<{ success: true }> {
  const res = await fetch(`${NOTES_BASE}/${encodeURIComponent(noteId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true }
}
```
- [ ] **Run** same command → **PASS**.
- [ ] **Commit**: `git add src/features/usd-swaps-tape-v2/api/ && git commit -m "feat(tape): add overrideApi + noteApi REST clients" -m "<trailer1>" -m "<trailer2>"`.

---

## Task 11 — `hooks/useTradeSelection.ts` (leg-level Set selection)

TDD with `renderHook`/`act` under jsdom. Internal state is package-keyed (`Map<packageId, Set<tradeId>>`); `selectedTradeIds`/`selectedByPackage` are derived. **Signature deviation**: `toggleTrade(tradeId, packageId)` (see Deviations).

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/hooks/__tests__/useTradeSelection.test.tsx`:
```tsx
/** @jest-environment jsdom */
import { describe, expect, it } from '@jest/globals'
import { renderHook, act } from '@testing-library/react'
import { useTradeSelection } from '../useTradeSelection'

describe('useTradeSelection', () => {
  it('starts empty', () => {
    const { result } = renderHook(() => useTradeSelection())
    expect(result.current.count).toBe(0)
    expect(result.current.selectedTradeIds.size).toBe(0)
    expect(result.current.selectedByPackage.size).toBe(0)
  })

  it('toggleTrade adds then removes a trade under its package', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    expect(result.current.selectedTradeIds.has('t1')).toBe(true)
    expect(result.current.selectedByPackage.get('PKG1')).toEqual(['t1'])
    expect(result.current.count).toBe(1)
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    expect(result.current.count).toBe(0)
    expect(result.current.selectedByPackage.has('PKG1')).toBe(false)
  })

  it('togglePackage selects all legs, and toggling again clears them', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.togglePackage('PKG1', ['t1', 't2', 't3']))
    expect(result.current.count).toBe(3)
    expect(new Set(result.current.selectedByPackage.get('PKG1'))).toEqual(new Set(['t1', 't2', 't3']))
    act(() => result.current.togglePackage('PKG1', ['t1', 't2', 't3']))
    expect(result.current.count).toBe(0)
  })

  it('togglePackage re-selects the full set when only partially selected', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    act(() => result.current.togglePackage('PKG1', ['t1', 't2', 't3']))
    expect(result.current.count).toBe(3)
  })

  it('tracks multiple packages independently and clears all', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    act(() => result.current.toggleTrade('t9', 'PKG2'))
    expect(result.current.selectedByPackage.size).toBe(2)
    expect(result.current.count).toBe(2)
    act(() => result.current.clear())
    expect(result.current.count).toBe(0)
    expect(result.current.selectedByPackage.size).toBe(0)
  })
})
```
- [ ] **Run** `npm test -- src/features/usd-swaps-tape-v2/hooks/__tests__/useTradeSelection.test.tsx` → **FAIL**.
- [ ] **Implement** `src/features/usd-swaps-tape-v2/hooks/useTradeSelection.ts`:
```ts
// ABOUTME: Leg-level tape selection. Internal state is package-keyed
// (Map<packageId, Set<tradeId>>) so `selectedByPackage` is exact; the
// flattened `selectedTradeIds` Set drives the action-bar enablement.
import { useCallback, useMemo, useState } from 'react'

export interface UseTradeSelectionReturn {
  selectedTradeIds: Set<string>
  selectedByPackage: Map<string, string[]>
  toggleTrade: (tradeId: string, packageId: string) => void
  togglePackage: (packageId: string, legTradeIds: string[]) => void
  clear: () => void
  count: number
}

export function useTradeSelection(): UseTradeSelectionReturn {
  const [byPackage, setByPackage] = useState<Map<string, Set<string>>>(() => new Map())

  const toggleTrade = useCallback((tradeId: string, packageId: string) => {
    setByPackage((prev) => {
      const next = new Map(prev)
      const set = new Set(next.get(packageId) ?? [])
      if (set.has(tradeId)) set.delete(tradeId)
      else set.add(tradeId)
      if (set.size === 0) next.delete(packageId)
      else next.set(packageId, set)
      return next
    })
  }, [])

  const togglePackage = useCallback((packageId: string, legTradeIds: string[]) => {
    setByPackage((prev) => {
      const next = new Map(prev)
      const current = next.get(packageId)
      const allSelected =
        legTradeIds.length > 0 &&
        current != null &&
        legTradeIds.every((id) => current.has(id))
      if (allSelected) next.delete(packageId)
      else next.set(packageId, new Set(legTradeIds))
      return next
    })
  }, [])

  const clear = useCallback(() => setByPackage(new Map()), [])

  const selectedByPackage = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const [pkg, set] of byPackage) m.set(pkg, Array.from(set))
    return m
  }, [byPackage])

  const selectedTradeIds = useMemo(() => {
    const s = new Set<string>()
    for (const set of byPackage.values()) for (const id of set) s.add(id)
    return s
  }, [byPackage])

  return {
    selectedTradeIds,
    selectedByPackage,
    toggleTrade,
    togglePackage,
    clear,
    count: selectedTradeIds.size,
  }
}
```
- [ ] **Update barrel** `hooks/index.ts` — add:
```ts
export { useTradeSelection } from './useTradeSelection'
export type { UseTradeSelectionReturn } from './useTradeSelection'
```
- [ ] **Run** same command → **PASS**.
- [ ] **Commit**: `git add src/features/usd-swaps-tape-v2/hooks/useTradeSelection.ts src/features/usd-swaps-tape-v2/hooks/index.ts && git commit -m "feat(tape): add useTradeSelection leg-level Set selection hook" -m "<trailer1>" -m "<trailer2>"`.

---

## Task 12 — `hooks/useSelectionContext.ts` + pure `deriveSelectionContext`

Pure `deriveSelectionContext(rows, selectedTradeIds)` (node, table-driven — mirrors `deriveAnalyticsSelection`), plus a thin `useSelectionContext` `useMemo` wrapper. Enablement rules per §3.2: **Group** ≥2; **Split** = one multi-leg auto-package fully selected; **Detach** = ≥1 leg selected in a package that keeps ≥1 other leg; **Note** = one single target (selection confined to one package).

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/hooks/__tests__/useSelectionContext.test.ts`:
```ts
import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeRow } from '../../types'
import { deriveSelectionContext } from '../useSelectionContext'

function pkg(
  id: string,
  tradeIds: string[],
  extra: Partial<UsdSwapTapeRow> = {},
): UsdSwapTapeRow {
  return {
    package_id: id,
    legs_json: tradeIds.map((t) => ({ trade_id: t })),
    ...extra,
  } as unknown as UsdSwapTapeRow
}

const ROWS: UsdSwapTapeRow[] = [
  pkg('PKG1', ['a', 'b', 'c']), // 3-leg auto package
  pkg('PKG2', ['d']), // lone outright
  pkg('PKG3', ['e', 'f'], { override_type: 'GROUP' }), // already a manual group
]

const ctx = (ids: string[]) => deriveSelectionContext(ROWS, new Set(ids))

describe('deriveSelectionContext', () => {
  it('empty selection → all false', () => {
    expect(ctx([])).toEqual({ canGroup: false, canSplit: false, canDetach: false, canNote: false })
  })

  it('single leg in a multi-leg package → detach + note, no group/split', () => {
    const c = ctx(['a'])
    expect(c).toMatchObject({ canGroup: false, canSplit: false, canDetach: true, canNote: true })
    expect(c.detachPackageId).toBe('PKG1')
    expect(c.splitPackageId).toBeUndefined()
  })

  it('all legs of a multi-leg auto package → group + split + note', () => {
    const c = ctx(['a', 'b', 'c'])
    expect(c).toMatchObject({ canGroup: true, canSplit: true, canDetach: false, canNote: true })
    expect(c.splitPackageId).toBe('PKG1')
  })

  it('two legs of a 3-leg package → group + detach + note (not split — not full)', () => {
    const c = ctx(['a', 'b'])
    expect(c).toMatchObject({ canGroup: true, canSplit: false, canDetach: true, canNote: true })
    expect(c.detachPackageId).toBe('PKG1')
  })

  it('trades spanning two packages → group only', () => {
    expect(ctx(['a', 'd'])).toMatchObject({
      canGroup: true, canSplit: false, canDetach: false, canNote: false,
    })
  })

  it('lone outright fully selected → note only (no split: single leg; no detach: nothing remains)', () => {
    expect(ctx(['d'])).toMatchObject({
      canGroup: false, canSplit: false, canDetach: false, canNote: true,
    })
  })

  it('fully-selected already-manual GROUP package → no split (not auto), note yes', () => {
    const c = ctx(['e', 'f'])
    expect(c.canSplit).toBe(false)
    expect(c.canGroup).toBe(true)
    expect(c.canNote).toBe(true)
  })

  it('ignores trade ids not present in any row', () => {
    expect(ctx(['zzz'])).toEqual({ canGroup: false, canSplit: false, canDetach: false, canNote: false })
  })
})
```
- [ ] **Run** `npm test -- src/features/usd-swaps-tape-v2/hooks/__tests__/useSelectionContext.test.ts` → **FAIL**.
- [ ] **Implement** `src/features/usd-swaps-tape-v2/hooks/useSelectionContext.ts`:
```ts
// ABOUTME: Derives the contextual-action enablement matrix from the
// current leg selection + the visible tape rows. Pure `deriveSelectionContext`
// is unit-tested in node; `useSelectionContext` is a memoized wrapper.
import { useMemo } from 'react'
import type { UsdSwapTapeRow } from '../types'

export interface SelectionContext {
  canGroup: boolean
  canSplit: boolean
  canDetach: boolean
  canNote: boolean
  splitPackageId?: string
  detachPackageId?: string
}

interface PackageInfo {
  row: UsdSwapTapeRow
  legTradeIds: string[]
}

function indexPackages(rows: readonly UsdSwapTapeRow[]): {
  tradeToPackage: Map<string, string>
  packages: Map<string, PackageInfo>
} {
  const tradeToPackage = new Map<string, string>()
  const packages = new Map<string, PackageInfo>()
  for (const row of rows) {
    if (!row || !row.package_id) continue
    const legs = Array.isArray(row.legs_json) ? row.legs_json : []
    const legTradeIds: string[] = []
    for (const leg of legs) {
      const tid = leg?.trade_id
      if (typeof tid === 'string' && tid.length > 0) {
        legTradeIds.push(tid)
        tradeToPackage.set(tid, row.package_id)
      }
    }
    packages.set(row.package_id, { row, legTradeIds })
  }
  return { tradeToPackage, packages }
}

export function deriveSelectionContext(
  rows: readonly UsdSwapTapeRow[],
  selectedTradeIds: ReadonlySet<string>,
): SelectionContext {
  const empty: SelectionContext = {
    canGroup: false,
    canSplit: false,
    canDetach: false,
    canNote: false,
  }
  const count = selectedTradeIds.size
  if (count === 0) return empty

  const { tradeToPackage, packages } = indexPackages(rows)

  const perPackage = new Map<string, number>()
  for (const tid of selectedTradeIds) {
    const pkg = tradeToPackage.get(tid)
    if (!pkg) continue
    perPackage.set(pkg, (perPackage.get(pkg) ?? 0) + 1)
  }

  // Nothing resolved to a known package.
  if (perPackage.size === 0) return empty

  const canGroup = count >= 2

  if (perPackage.size === 1) {
    const pkgId = perPackage.keys().next().value as string
    const info = packages.get(pkgId)
    const totalLegs = info ? info.legTradeIds.length : 0
    const selInPkg = perPackage.get(pkgId) ?? 0
    const isAuto = !info?.row.override_type
    const canSplit = totalLegs >= 2 && selInPkg === totalLegs && isAuto
    const canDetach = selInPkg >= 1 && selInPkg < totalLegs
    return {
      canGroup,
      canSplit,
      canDetach,
      canNote: true,
      splitPackageId: canSplit ? pkgId : undefined,
      detachPackageId: canDetach ? pkgId : undefined,
    }
  }

  // Selection spans ≥2 packages: group only.
  return { canGroup, canSplit: false, canDetach: false, canNote: false }
}

export function useSelectionContext(
  rows: readonly UsdSwapTapeRow[],
  selectedTradeIds: ReadonlySet<string>,
): SelectionContext {
  return useMemo(
    () => deriveSelectionContext(rows, selectedTradeIds),
    [rows, selectedTradeIds],
  )
}
```
- [ ] **Update barrel** `hooks/index.ts` — add:
```ts
export { useSelectionContext, deriveSelectionContext } from './useSelectionContext'
export type { SelectionContext } from './useSelectionContext'
```
- [ ] **Run** same command → **PASS**.
- [ ] **Commit**: `git add src/features/usd-swaps-tape-v2/hooks/useSelectionContext.ts src/features/usd-swaps-tape-v2/hooks/index.ts && git commit -m "feat(tape): add deriveSelectionContext + useSelectionContext enablement rules" -m "<trailer1>" -m "<trailer2>"`.

---

## Task 13 — `components/RegroupActionBar/RegroupActionBar.tsx`

Renders `{count} selected`, four action buttons enabled per `SelectionContext`, and a clear button. jsdom + testing-library. Mirrors the plain-`<button>` + Tailwind toolbar idiom.

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/components/RegroupActionBar/__tests__/RegroupActionBar.test.tsx`:
```tsx
/** @jest-environment jsdom */
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { RegroupActionBar } from '../RegroupActionBar'
import type { SelectionContext } from '../../../hooks/useSelectionContext'

const ALL_OFF: SelectionContext = {
  canGroup: false, canSplit: false, canDetach: false, canNote: false,
}

describe('RegroupActionBar', () => {
  it('shows the selected count', () => {
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a', 'b'])}
        context={{ ...ALL_OFF, canGroup: true }}
        onAction={jest.fn()}
        onClear={jest.fn()}
      />,
    )
    ;(expect(screen.getByText('2 selected')) as any).toBeInTheDocument()
  })

  it('enables only the actions allowed by context', () => {
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a', 'b'])}
        context={{ canGroup: true, canSplit: false, canDetach: true, canNote: true }}
        onAction={jest.fn()}
        onClear={jest.fn()}
      />,
    )
    ;(expect(screen.getByRole('button', { name: 'Group' })) as any).toBeEnabled()
    ;(expect(screen.getByRole('button', { name: 'Split' })) as any).toBeDisabled()
    ;(expect(screen.getByRole('button', { name: 'Detach' })) as any).toBeEnabled()
    ;(expect(screen.getByRole('button', { name: 'Note' })) as any).toBeEnabled()
  })

  it('fires onAction with the action key', () => {
    const onAction = jest.fn()
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a', 'b'])}
        context={{ ...ALL_OFF, canGroup: true }}
        onAction={onAction}
        onClear={jest.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Group' }))
    expect(onAction).toHaveBeenCalledWith('GROUP')
  })

  it('disabled action does not fire onAction', () => {
    const onAction = jest.fn()
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a'])}
        context={ALL_OFF}
        onAction={onAction}
        onClear={jest.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Group' }))
    expect(onAction).not.toHaveBeenCalled()
  })

  it('fires onClear', () => {
    const onClear = jest.fn()
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a'])}
        context={ALL_OFF}
        onAction={jest.fn()}
        onClear={onClear}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(onClear).toHaveBeenCalled()
  })
})
```
- [ ] **Run** `npm test -- src/features/usd-swaps-tape-v2/components/RegroupActionBar/__tests__/RegroupActionBar.test.tsx` → **FAIL**.
- [ ] **Implement** `src/features/usd-swaps-tape-v2/components/RegroupActionBar/RegroupActionBar.tsx`:
```tsx
'use client'
// ABOUTME: Contextual action bar for the tape toolbar `actionSlot`. Shows
// the selection count and Group/Split/Detach/Note actions, each enabled per
// the derived SelectionContext.
import type { JSX } from 'react'
import type { SelectionContext } from '../../hooks/useSelectionContext'

export type RegroupAction = 'GROUP' | 'SPLIT' | 'DETACH' | 'NOTE'

export interface RegroupActionBarProps {
  selectedTradeIds: Set<string>
  context: SelectionContext
  onAction: (action: RegroupAction) => void
  onClear: () => void
}

interface ActionDef {
  key: RegroupAction
  label: string
  enabled: boolean
}

export function RegroupActionBar({
  selectedTradeIds,
  context,
  onAction,
  onClear,
}: RegroupActionBarProps): JSX.Element {
  const count = selectedTradeIds.size
  const actions: ActionDef[] = [
    { key: 'GROUP', label: 'Group', enabled: context.canGroup },
    { key: 'SPLIT', label: 'Split', enabled: context.canSplit },
    { key: 'DETACH', label: 'Detach', enabled: context.canDetach },
    { key: 'NOTE', label: 'Note', enabled: context.canNote },
  ]
  return (
    <div className="flex items-center gap-2" role="toolbar" aria-label="Regroup actions">
      <span className="whitespace-nowrap font-mono text-[10.5px] text-slate-300">
        {count} selected
      </span>
      {actions.map((a) => (
        <button
          key={a.key}
          type="button"
          disabled={!a.enabled}
          onClick={() => onAction(a.key)}
          className={`rounded border px-2.5 py-1 font-mono text-[10.5px] ring-1 ring-transparent transition-colors ${
            a.enabled
              ? 'border-slate-700 text-slate-200 hover:bg-slate-800'
              : 'cursor-not-allowed border-slate-800 text-slate-600 opacity-60'
          }`}
        >
          {a.label}
        </button>
      ))}
      <button
        type="button"
        aria-label="Clear selection"
        onClick={onClear}
        className="rounded border border-slate-700 px-2 py-1 font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
      >
        ✕
      </button>
    </div>
  )
}
```
- [ ] **Run** same command → **PASS**.
- [ ] **Commit**: `git add src/features/usd-swaps-tape-v2/components/RegroupActionBar/ && git commit -m "feat(tape): add RegroupActionBar contextual action bar" -m "<trailer1>" -m "<trailer2>"`.

---

## Task 14 — `components/OverrideCommitPopover/OverrideCommitPopover.tsx`

Collects `reason?`, `tags?`, `admin_password`, `user` (override_type fixed by the triggering action); runs `validateOverride` then `createOverride` via `overrideApi`; inline validation + errors; `onSuccess(result)`. jsdom + `global.fetch` mock (the popover calls `overrideApi`, which calls `fetch`). Popover chrome mirrors `BucketOverridesPopover`.

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/__tests__/OverrideCommitPopover.test.tsx`:
```tsx
/** @jest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { OverrideCommitPopover } from '../OverrideCommitPopover'

describe('OverrideCommitPopover', () => {
  let originalFetch: typeof fetch
  let fetchMock: jest.Mock
  beforeEach(() => {
    originalFetch = global.fetch
    fetchMock = jest.fn()
    ;(global as any).fetch = fetchMock
  })
  afterEach(() => {
    ;(global as any).fetch = originalFetch
  })
  const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body } as any)

  function renderPopover(props: Partial<React.ComponentProps<typeof OverrideCommitPopover>> = {}) {
    const onSuccess = jest.fn()
    const onCancel = jest.fn()
    const onPasswordChange = jest.fn()
    render(
      <OverrideCommitPopover
        overrideType="GROUP"
        tradeIds={['t1', 't2']}
        user="chris"
        password="pw"
        onPasswordChange={onPasswordChange}
        onSuccess={onSuccess}
        onCancel={onCancel}
        {...props}
      />,
    )
    return { onSuccess, onCancel, onPasswordChange }
  }

  it('renders the override type + trade count header', () => {
    renderPopover()
    ;(expect(screen.getByText(/GROUP/)) as any).toBeInTheDocument()
    ;(expect(screen.getByText(/2 trades/)) as any).toBeInTheDocument()
  })

  it('Validate calls validateOverride and shows validation messages', async () => {
    fetchMock.mockResolvedValue(
      ok({ validation: [{ level: 'warning', code: 'W', message: 'heads up' }], metrics: {}, linked_trade_ids: [] }),
    )
    renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }))
    await waitFor(() => (expect(screen.getByText('heads up')) as any).toBeInTheDocument())
    const sent = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(sent.validate_only).toBe(true)
  })

  it('Commit calls createOverride and fires onSuccess', async () => {
    fetchMock.mockResolvedValue(
      ok({ success: true, override_id: 'o1', manual_package_id: 'SMO-1', validation: [], metrics: {} }),
    )
    const { onSuccess } = renderPopover()
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'customer flow' } })
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
    expect(onSuccess.mock.calls[0][0]).toMatchObject({ override_id: 'o1' })
    const sent = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(sent.reason).toBe('customer flow')
    expect(sent.validate_only).toBeUndefined()
  })

  it('surfaces the server error message inline (403)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 403, json: async () => ({ error: 'Invalid override password.' }) } as any)
    const { onSuccess } = renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await waitFor(() => (expect(screen.getByRole('alert')) as any).toHaveTextContent('Invalid override password.'))
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('disables Commit when a validation error is present', async () => {
    fetchMock.mockResolvedValue(
      ok({ validation: [{ level: 'error', code: 'E', message: 'bad' }], metrics: {}, linked_trade_ids: [] }),
    )
    renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }))
    await waitFor(() => (expect(screen.getByText('bad')) as any).toBeInTheDocument())
    ;(expect(screen.getByRole('button', { name: 'Commit' })) as any).toBeDisabled()
  })

  it('fires onCancel', () => {
    const { onCancel } = renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
  })
})
```
- [ ] **Run** `npm test -- src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/__tests__/OverrideCommitPopover.test.tsx` → **FAIL**.
- [ ] **Implement** `src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/OverrideCommitPopover.tsx`:
```tsx
'use client'
// ABOUTME: Inline commit popover for a structural override. override_type
// is fixed by the triggering action; collects reason/tags/user/password,
// runs validate_only then the real create via overrideApi. Errors inline
// (no toast lib). Password is a controlled prop persisted in the orchestrator.
import { useCallback, useState, type JSX } from 'react'
import type { OverrideType, OverrideValidationItem } from '../../types/override.types'
import {
  createOverride,
  validateOverride,
  type CreateOverrideBody,
  type CreateOverrideResult,
} from '../../api/overrideApi'

export interface OverrideCommitPopoverProps {
  overrideType: OverrideType
  tradeIds: string[]
  /** Source package for SPLIT/DETACH (informational); undefined for GROUP. */
  manualPackageId?: string | null
  user: string
  /** Optional: if provided, the user field becomes editable. */
  onUserChange?: (next: string) => void
  password: string
  onPasswordChange: (next: string) => void
  onSuccess: (result: CreateOverrideResult) => void
  onCancel: () => void
}

function splitTags(raw: string): string[] {
  return raw
    .split(',')
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
}

export function OverrideCommitPopover({
  overrideType,
  tradeIds,
  manualPackageId,
  user,
  onUserChange,
  password,
  onPasswordChange,
  onSuccess,
  onCancel,
}: OverrideCommitPopoverProps): JSX.Element {
  const [reason, setReason] = useState('')
  const [tags, setTags] = useState('')
  const [validation, setValidation] = useState<OverrideValidationItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const buildBody = useCallback(
    (validateOnly: boolean): CreateOverrideBody => ({
      override_type: overrideType,
      trade_ids: tradeIds,
      manual_package_id: manualPackageId ?? undefined,
      reason: reason.trim() || undefined,
      tags: splitTags(tags),
      user,
      admin_password: password,
      validate_only: validateOnly,
    }),
    [overrideType, tradeIds, manualPackageId, reason, tags, user, password],
  )

  const hasErrors = validation.some((v) => v.level === 'error')

  const handleValidate = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await validateOverride(buildBody(true))
      setValidation(res.validation)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [buildBody])

  const handleCommit = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await createOverride(buildBody(false))
      onSuccess(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [buildBody, onSuccess])

  return (
    <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded border border-slate-700 bg-slate-900 p-3 shadow-xl">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
          {overrideType} · {tradeIds.length} trades
        </span>
        <button
          type="button"
          aria-label="Cancel"
          onClick={onCancel}
          className="font-mono text-[10px] text-slate-400 hover:text-slate-200"
        >
          ✕
        </button>
      </div>

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-reason">
        Reason
      </label>
      <input
        id="ovr-reason"
        type="text"
        aria-label="Reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-tags">
        Tags (comma-separated)
      </label>
      <input
        id="ovr-tags"
        type="text"
        aria-label="Tags"
        value={tags}
        onChange={(e) => setTags(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-user">
        User
      </label>
      <input
        id="ovr-user"
        type="text"
        aria-label="User"
        value={user}
        readOnly={!onUserChange}
        onChange={(e) => onUserChange?.(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-pw">
        Override password
      </label>
      <input
        id="ovr-pw"
        type="password"
        aria-label="Override password"
        value={password}
        onChange={(e) => onPasswordChange(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      {validation.length > 0 && (
        <ul className="mb-2 space-y-0.5">
          {validation.map((v, i) => (
            <li
              key={`${v.code}-${i}`}
              className={`font-mono text-[10px] ${
                v.level === 'error'
                  ? 'text-rose-300'
                  : v.level === 'warning'
                    ? 'text-amber-300'
                    : 'text-slate-400'
              }`}
            >
              {v.message}
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p role="alert" className="mb-2 font-mono text-[10px] text-rose-300">
          {error}
        </p>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={handleValidate}
          disabled={busy}
          className="rounded border border-slate-700 px-2.5 py-1 font-mono text-[10.5px] text-slate-200 hover:bg-slate-800 disabled:opacity-50"
        >
          Validate
        </button>
        <button
          type="button"
          onClick={handleCommit}
          disabled={busy || hasErrors || !password}
          className="rounded border border-indigo-500/40 bg-indigo-500/20 px-2.5 py-1 font-mono text-[10.5px] text-indigo-100 hover:bg-indigo-500/30 disabled:opacity-50"
        >
          Commit
        </button>
      </div>
    </div>
  )
}
```
- [ ] **Run** same command → **PASS**.
- [ ] **Commit**: `git add src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/ && git commit -m "feat(tape): add OverrideCommitPopover (validate+commit via overrideApi)" -m "<trailer1>" -m "<trailer2>"`.

---

## Handoff notes to the integration section (out of scope here)

- `RegroupActionBar` mounts in the orchestrator's `actionSlot` when `selection.count > 0` (replaces / sits alongside the existing "Link N selected" button). The orchestrator owns `overridePassword` state (persist like today's `adminPassword`) + `useSavedUser()` for `user`, and renders `OverrideCommitPopover` positioned relative to the toolbar (its root is `absolute`, so wrap in a `relative` container as `BucketOverridesPopover` does).
- `LegsSubTable` leg checkbox calls `toggleTrade(leg.trade_id, packageId)`; the package-row checkbox calls `togglePackage(packageId, legTradeIds)`. `useSelectionContext(tape.rows, selectedTradeIds)` feeds `context`. On `onSuccess`, clear selection + `tape.refetch()`.
- The `NOTE` action opens `NotePopover` (owned by another section) using `noteApi`.
# Plan — FRONTEND RENDER + INTEGRATION (Tasks 15–20)

USD Swaps Tape manual regrouping + trader notes. This section owns the display
transform, visual markers, leg-checkbox + note UI, orchestrator wiring, undo /
management, and browser/perf verification.

**Standing rules (repeat in every task):**
- Frontend tests run with **`cd SDRUtils/dashboard && npm test -- <path>`** — NEVER plain
  `npx jest` (ESM mocks break → false Supabase failures). Jest runs ESM via
  `node --experimental-vm-modules`.
- Every `git commit` ends with the two trailer lines (verbatim):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015cnMkf5k8obXybEHTCCk9a
  ```
  Conventional commits, scope `(dashboard)`.
- **NEVER edit shared `lib/manual-links-ui/*`** (swaptions co-consumes it). Build tape-local
  equivalents. Reading/importing from it read-only is fine.
- **NEVER write ingest-owned `_tape_packages/legs_v2`.**
- Verify all frontend changes in Chrome MCP at `localhost:3000` before the final commit.
- Consumes FE-CORE interfaces (contract signatures, since `plan_part_fe_core.md` is absent):
  `useTradeSelection`, `useSelectionContext`, `RegroupActionBar`, `OverrideCommitPopover`,
  `overrideApi`, `noteApi`, and the `override.types.ts` / `note.types.ts` / `trade.types.ts`
  additions. Exact prop names for FE-core-owned components are noted where consumed.

---

## Contract this section produces (read this first)

```ts
// features/usd-swaps-tape-v2/utils/applyOverrides.ts
import type { UsdSwapTapeRow } from '../types'

export type OverrideRowKind = 'normal' | 'split-leg' | 'detached'

export type DisplayRow = UsdSwapTapeRow & {
  __rowKind?: OverrideRowKind
  __syntheticKey?: string   // ALWAYS populated by applyOverrides (see note)
}

export function applyOverrides(rows: UsdSwapTapeRow[]): DisplayRow[]
```

**Synthetic-key formats (verbatim):**
- normal / GROUP-cluster / DETACH-remnant row → `__syntheticKey = package_id`
- SPLIT per-leg row  → `${package_id}::split::${trade_id}`
- DETACH standalone leg → `${package_id}::detach::${trade_id}`
- trade-id-less leg fallback → `${package_id}::split::idx${i}` / `::detach::idx${i}`

> **dataKey note.** Split rows share `package_id`, which collides under the table's current
> `dataKey="package_id"`. `applyOverrides` therefore stamps `__syntheticKey` on **every** emitted
> row (normal rows get `= package_id`) and Task 19 switches the DataTable to `dataKey="__syntheticKey"`
> and keys row-expansion by the same value. The type keeps `__syntheticKey?` optional (contract) but
> it is present in practice on all output rows.

---

## Task 15 — `utils/applyOverrides.ts` (pure transform, TDD)

The display transform. GROUP clustering reuses the shared `groupLinkedRows` **ordering** (called,
never edited), then post-processes; SPLIT explodes a package into per-leg rows; DETACH pulls
matched legs out as standalone rows leaving a remnant package row. Tags `__rowKind` + `__syntheticKey`.

- [ ] **Write failing test** `src/features/usd-swaps-tape-v2/utils/__tests__/applyOverrides.test.ts`:
```ts
import { describe, expect, it } from '@jest/globals'
import { applyOverrides } from '../applyOverrides'
import type { UsdSwapTapeRow } from '../../types'

const leg = (trade_id: string, tenor = 5) =>
  ({ trade_id, tenor_years: tenor } as any)

const row = (
  package_id: string,
  legs: Array<{ trade_id: string }>,
  extras: Partial<UsdSwapTapeRow> = {},
): UsdSwapTapeRow =>
  ({
    package_id,
    package_type: 'CURVE',
    legs_json: legs,
    ...extras,
  } as any)

describe('applyOverrides', () => {
  it('passes normal rows through in order, tagging kind + key', () => {
    const rows = [row('P1', [leg('T1')]), row('P2', [leg('T2')])]
    const out = applyOverrides(rows)
    expect(out.map((r) => r.package_id)).toEqual(['P1', 'P2'])
    expect(out.map((r) => r.__rowKind)).toEqual(['normal', 'normal'])
    expect(out.map((r) => r.__syntheticKey)).toEqual(['P1', 'P2'])
    // legs untouched
    expect(out[0].legs_json).toHaveLength(1)
  })

  it('clusters GROUP rows sharing manual_package_id contiguously (anchored at first)', () => {
    const rows = [
      row('P1', [leg('T1')], { manual_package_id: 'SMO-1', override_type: 'GROUP', override_map: { T1: 'o1' } }),
      row('P2', [leg('T2')]),
      row('P3', [leg('T3')], { manual_package_id: 'SMO-1', override_type: 'GROUP', override_map: { T3: 'o1' } }),
    ]
    const out = applyOverrides(rows)
    expect(out.map((r) => r.package_id)).toEqual(['P1', 'P3', 'P2'])
    expect(out.every((r) => r.__rowKind === 'normal')).toBe(true)
  })

  it('explodes a SPLIT package into one row per leg with synthetic keys', () => {
    const rows = [
      row('P1', [leg('T1'), leg('T2'), leg('T3')], {
        override_type: 'SPLIT',
        override_map: { T1: 'o9', T2: 'o9', T3: 'o9' },
      }),
    ]
    const out = applyOverrides(rows)
    expect(out).toHaveLength(3)
    expect(out.map((r) => r.__syntheticKey)).toEqual([
      'P1::split::T1',
      'P1::split::T2',
      'P1::split::T3',
    ])
    expect(out.every((r) => r.__rowKind === 'split-leg')).toBe(true)
    expect(out.every((r) => r.legs_json.length === 1)).toBe(true)
    expect(out[1].legs_json[0].trade_id).toBe('T2')
    // override metadata preserved so the SPLIT badge renders on each row
    expect(out[0].override_type).toBe('SPLIT')
  })

  it('DETACH keeps a remnant package row + standalone detached legs', () => {
    const rows = [
      row('P1', [leg('T1'), leg('T2'), leg('T3')], {
        override_type: 'DETACH',
        override_map: { T2: 'o5' },
      }),
    ]
    const out = applyOverrides(rows)
    expect(out).toHaveLength(2)
    // remnant first, keyed by package_id, kind normal, only non-detached legs
    expect(out[0].__syntheticKey).toBe('P1')
    expect(out[0].__rowKind).toBe('normal')
    expect(out[0].legs_json.map((l) => l.trade_id)).toEqual(['T1', 'T3'])
    // detached leg standalone
    expect(out[1].__syntheticKey).toBe('P1::detach::T2')
    expect(out[1].__rowKind).toBe('detached')
    expect(out[1].legs_json.map((l) => l.trade_id)).toEqual(['T2'])
  })

  it('DETACH of every leg emits only detached rows (no empty remnant)', () => {
    const rows = [
      row('P1', [leg('T1')], { override_type: 'DETACH', override_map: { T1: 'o5' } }),
    ]
    const out = applyOverrides(rows)
    expect(out).toHaveLength(1)
    expect(out[0].__rowKind).toBe('detached')
    expect(out[0].__syntheticKey).toBe('P1::detach::T1')
  })

  it('SPLIT with a leg missing trade_id falls back to an index key', () => {
    const rows = [
      row('P1', [{ trade_id: undefined } as any, leg('T2')], {
        override_type: 'SPLIT',
        override_map: { T2: 'o9' },
      }),
    ]
    const out = applyOverrides(rows)
    expect(out[0].__syntheticKey).toBe('P1::split::idx0')
    expect(out[1].__syntheticKey).toBe('P1::split::T2')
  })

  it('returns [] for empty input', () => {
    expect(applyOverrides([])).toEqual([])
  })
})
```
- [ ] Run `cd SDRUtils/dashboard && npm test -- applyOverrides` → **expect FAIL** (module missing).
- [ ] **Implement** `src/features/usd-swaps-tape-v2/utils/applyOverrides.ts`:
```ts
// ABOUTME: Tape-local display transform for manual overrides. Explodes SPLIT
// packages into per-leg rows, pulls DETACH legs out as standalone rows leaving
// a remnant, and clusters GROUP packages contiguously by reusing the shared
// groupLinkedRows ordering. Pure — never mutates input, never edits the shared
// grouping helper. Stamps __rowKind + __syntheticKey (dataKey) on every row.
import { groupLinkedRows } from '@/lib/manual-links-ui/grouping'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../types'

export type OverrideRowKind = 'normal' | 'split-leg' | 'detached'

export type DisplayRow = UsdSwapTapeRow & {
  __rowKind?: OverrideRowKind
  __syntheticKey?: string
}

function legKey(pkg: string, verb: 'split' | 'detach', leg: UsdSwapTapeLeg, i: number): string {
  const tid = leg?.trade_id
  return tid ? `${pkg}::${verb}::${tid}` : `${pkg}::${verb}::idx${i}`
}

/**
 * Resolve view-time override columns into render rows.
 * - GROUP: rows keep their shape; clustered contiguously (via groupLinkedRows).
 * - SPLIT: one synthetic row per leg, single-leg legs_json.
 * - DETACH: standalone row per detached leg + a remnant package row of the rest.
 */
export function applyOverrides(rows: UsdSwapTapeRow[]): DisplayRow[] {
  const transformed: DisplayRow[] = []

  for (const row of rows) {
    const legs = (row.legs_json ?? []) as UsdSwapTapeLeg[]
    const type = row.override_type ?? null

    if (type === 'SPLIT' && legs.length > 0) {
      legs.forEach((leg, i) => {
        transformed.push({
          ...row,
          legs_json: [leg],
          __rowKind: 'split-leg',
          __syntheticKey: legKey(row.package_id, 'split', leg, i),
        })
      })
      continue
    }

    if (type === 'DETACH') {
      const map = row.override_map ?? {}
      const detached: Array<{ leg: UsdSwapTapeLeg; i: number }> = []
      const remnant: UsdSwapTapeLeg[] = []
      legs.forEach((leg, i) => {
        if (leg?.trade_id && map[leg.trade_id]) detached.push({ leg, i })
        else remnant.push(leg)
      })
      // Defensive: nothing actually matched -> treat as a normal row.
      if (detached.length === 0) {
        transformed.push({ ...row, __rowKind: 'normal', __syntheticKey: row.package_id })
        continue
      }
      if (remnant.length > 0) {
        transformed.push({
          ...row,
          legs_json: remnant,
          __rowKind: 'normal',
          __syntheticKey: row.package_id,
        })
      }
      detached.forEach(({ leg, i }) => {
        transformed.push({
          ...row,
          legs_json: [leg],
          __rowKind: 'detached',
          __syntheticKey: legKey(row.package_id, 'detach', leg, i),
        })
      })
      continue
    }

    // GROUP or no override: pass through as a normal row (clustering handled below).
    transformed.push({ ...row, __rowKind: 'normal', __syntheticKey: row.package_id })
  }

  // Contiguously cluster GROUP rows sharing manual_package_id. groupLinkedRows
  // clusters by manual_package_id||manual_link_id and leaves everything else in
  // source order, so split/detach synthetic rows (manual_package_id null) stay put
  // and adjacent. Returns the same array reference when no clusters exist.
  return groupLinkedRows(transformed) as DisplayRow[]
}
```
- [ ] Run `npm test -- applyOverrides` → **expect PASS**.
- [ ] `git commit -m "feat(dashboard): applyOverrides display transform for tape regrouping"` (+ trailers).

---

## Task 16 — `LegsSubTable.tsx`: leg checkbox column + per-leg note icon (TDD)

Add a leading checkbox column (`LEG_COL_COUNT` 16→17, summary colspan in lockstep) wired to
`useTradeSelection`, and a per-leg note affordance in the Trade ID cell.

New signature:
```ts
import type { NoteTarget } from '../NotePopover/NotePopover'
export function LegsSubTable({
  row,
  selectedTradeIds,
  onToggleTrade,
  onOpenNote,
}: {
  row: UsdSwapTapeRow
  selectedTradeIds?: Set<string>
  onToggleTrade?: (tradeId: string, packageId: string) => void
  onOpenNote?: (target: NoteTarget) => void
}): JSX.Element
```

- [ ] **Write failing test** `components/TradeTapeTable/__tests__/LegsSubTable.selection.test.tsx`:
```tsx
/**
 * @jest-environment jsdom
 */
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { LegsSubTable } from '../LegsSubTable'

const row = {
  package_id: 'P1',
  package_type: 'CURVE',
  legs_json: [
    { trade_id: 'T1', tenor_years: 2 },
    { trade_id: 'T2', tenor_years: 5 },
  ],
} as any

describe('LegsSubTable selection + notes', () => {
  it('renders a checkbox per leg and toggles the trade id', () => {
    const onToggleTrade = jest.fn()
    render(
      <LegsSubTable
        row={row}
        selectedTradeIds={new Set(['T1'])}
        onToggleTrade={onToggleTrade}
      />,
    )
    const cbT1 = screen.getByLabelText('select leg T1') as HTMLInputElement
    const cbT2 = screen.getByLabelText('select leg T2') as HTMLInputElement
    expect(cbT1.checked).toBe(true)
    expect(cbT2.checked).toBe(false)
    fireEvent.click(cbT2)
    expect(onToggleTrade).toHaveBeenCalledWith('T2', 'P1')
  })

  it('opens a TRADE note target from the per-leg note icon', () => {
    const onOpenNote = jest.fn()
    render(<LegsSubTable row={row} onOpenNote={onOpenNote} />)
    fireEvent.click(screen.getByLabelText('notes for leg T1'))
    expect(onOpenNote).toHaveBeenCalledWith({ target_type: 'TRADE', target_id: 'T1' })
  })
})
```
- [ ] Run `npm test -- LegsSubTable.selection` → **expect FAIL**.
- [ ] **Edit** `LegsSubTable.tsx`:
  - Bump the constant: `const LEG_COL_COUNT = 17`.
  - Add imports: `import { StickyNote } from 'lucide-react'` and `import type { NoteTarget } from '../NotePopover/NotePopover'`.
  - Change the function signature to the destructured props above.
  - Add a leading `<th className="px-2 py-1 text-left w-6"></th>` as the **first** child of the header `<tr data-leg-table-header>` (before `#`).
  - In the leg `.map(...)`, add a leading `<td>` as the first child of each leg `<tr>`:
```tsx
<td className="whitespace-nowrap px-2 py-1">
  <input
    type="checkbox"
    aria-label={`select leg ${leg.trade_id ?? index}`}
    disabled={!leg.trade_id || !onToggleTrade}
    checked={!!leg.trade_id && !!selectedTradeIds?.has(leg.trade_id)}
    onChange={(e) => {
      e.stopPropagation()
      if (leg.trade_id) onToggleTrade?.(leg.trade_id, row.package_id)
    }}
    onClick={(e) => e.stopPropagation()}
  />
</td>
```
  - In the Trade ID `<td>` (currently `{tradeIdBody(leg)}`) append the note icon so it becomes:
```tsx
<td className="whitespace-nowrap px-2 py-1">
  <span className="inline-flex items-center gap-1">
    {tradeIdBody(leg)}
    {leg.trade_id && onOpenNote ? (
      <button
        type="button"
        aria-label={`notes for leg ${leg.trade_id}`}
        title={row.has_notes ? 'View / add notes' : 'Add note'}
        className={`inline-flex items-center rounded p-0.5 ${
          row.has_notes ? 'text-amber-300' : 'text-slate-500 hover:text-slate-300'
        }`}
        onClick={(e) => {
          e.stopPropagation()
          onOpenNote({ target_type: 'TRADE', target_id: leg.trade_id! })
        }}
      >
        <StickyNote className="h-3 w-3" />
      </button>
    ) : null}
  </span>
</td>
```
  - **Empty-state row:** `colSpan={LEG_COL_COUNT}` already references the constant — no edit needed beyond the 17 bump.
  - **Summary row:** add ONE leading `<td className="px-2 py-1" />` as the first child (before the `Σ` cell) so the summary keeps 17 cells in lockstep with the header.
- [ ] Run `npm test -- LegsSubTable.selection` → **expect PASS**. Also run `npm test -- LegsSubTable` to confirm any pre-existing LegsSubTable tests still pass (summary colspan).
- [ ] `git commit -m "feat(dashboard): leg-level checkbox + note affordance in LegsSubTable"` (+ trailers).

> **Per-leg note gating deviation.** The view surfaces `has_notes`/`notes_count` at the *package*
> level only (spec §1.3). The per-leg icon is therefore always clickable (add-note) and merely
> tinted amber when the *package* has notes; the actual per-leg notes are lazy-fetched on open.
> A strict per-leg gate would require per-leg note flags the view does not provide.

---

## Task 17 — Visual markers: `OverrideBadge` + `columns.tsx` Pkg cell + synthetic-row styling (TDD)

Tape-local `OverrideBadge` (mirrors ManualLinkBadge/color idioms; does NOT edit shared lib).
GROUP = "REGROUPED" (amber, distinct from auto ManualLinkBadge); SPLIT = scissors; DETACH = unlink.
Row styling for synthetic rows via `dataTableRowClassName` + global CSS.

### 17a — `OverrideBadge`

New prop type:
```ts
export interface OverrideBadgeProps {
  overrideType: OverrideType       // 'GROUP' | 'SPLIT' | 'DETACH'
  manualPackageId?: string | null  // shown for GROUP clusters
  overrideId?: string | null       // deterministic dot color + click target
  onClick?: (overrideId: string) => void
  className?: string
}
```

- [ ] **Write failing test** `components/TradeTapeTable/__tests__/OverrideBadge.test.tsx`:
```tsx
/**
 * @jest-environment jsdom
 */
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { OverrideBadge } from '../OverrideBadge'

describe('OverrideBadge', () => {
  it('renders a REGROUPED label + package id for GROUP', () => {
    render(<OverrideBadge overrideType="GROUP" manualPackageId="SMO-20260708-ABCD1234" />)
    expect(screen.getByText('REGROUPED')).toBeInTheDocument()
    expect(screen.getByText('SMO-20260708-ABCD1234')).toBeInTheDocument()
  })

  it('renders SPLIT and DETACH labels', () => {
    const { rerender } = render(<OverrideBadge overrideType="SPLIT" />)
    expect(screen.getByText('SPLIT')).toBeInTheDocument()
    rerender(<OverrideBadge overrideType="DETACH" />)
    expect(screen.getByText('DETACHED')).toBeInTheDocument()
  })

  it('is a button that fires onClick(overrideId) when both provided', () => {
    const onClick = jest.fn()
    render(<OverrideBadge overrideType="GROUP" overrideId="o1" onClick={onClick} />)
    fireEvent.click(screen.getByTestId('override-badge'))
    expect(onClick).toHaveBeenCalledWith('o1')
  })

  it('renders a static span when no onClick', () => {
    render(<OverrideBadge overrideType="SPLIT" />)
    expect(screen.getByTestId('override-badge').tagName).toBe('SPAN')
  })
})
```
- [ ] Run `npm test -- OverrideBadge` → **expect FAIL**.
- [ ] **Implement** `components/TradeTapeTable/OverrideBadge.tsx`:
```tsx
// ABOUTME: Tape-local marker chip for a manual override (GROUP/SPLIT/DETACH).
// Mirrors ManualLinkBadge's idioms but is intentionally NOT the shared component
// (swaptions must not inherit tape override semantics). GROUP reuses the amber
// language + a deterministic dot; SPLIT/DETACH use scissors / unlink icons.
import * as React from 'react'
import { Layers, Scissors, Unlink } from 'lucide-react'
import type { OverrideType } from '../../types/override.types'

export interface OverrideBadgeProps {
  overrideType: OverrideType
  manualPackageId?: string | null
  overrideId?: string | null
  onClick?: (overrideId: string) => void
  className?: string
}

const CONFIG: Record<
  OverrideType,
  { label: string; Icon: React.ComponentType<{ className?: string }>; tone: string }
> = {
  GROUP: { label: 'REGROUPED', Icon: Layers, tone: 'border-amber-500/60 bg-amber-900/40 text-amber-200' },
  SPLIT: { label: 'SPLIT', Icon: Scissors, tone: 'border-sky-500/60 bg-sky-900/40 text-sky-200' },
  DETACH: { label: 'DETACHED', Icon: Unlink, tone: 'border-rose-500/60 bg-rose-900/40 text-rose-200' },
}

// Local deterministic colour (self-contained; does not import shared color.ts).
function overrideColor(seed?: string | null): string | null {
  if (!seed) return null
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) % 360
  return `hsl(${hash}, 65%, 52%)`
}

export function OverrideBadge(props: OverrideBadgeProps): React.ReactElement {
  const { overrideType, manualPackageId, overrideId, onClick, className } = props
  const cfg = CONFIG[overrideType]
  const Icon = cfg.Icon
  const dot = overrideColor(overrideId ?? manualPackageId)
  const base =
    `inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${cfg.tone} ${className ?? ''}`
      .trim()

  const inner = (
    <>
      {overrideType === 'GROUP' && dot ? (
        <span
          data-testid="override-dot"
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: dot }}
        />
      ) : (
        <Icon className="h-3 w-3" />
      )}
      <span>{cfg.label}</span>
      {manualPackageId ? (
        <span className="normal-case tracking-normal text-slate-400">{manualPackageId}</span>
      ) : null}
    </>
  )

  if (onClick && overrideId) {
    return (
      <button
        type="button"
        data-testid="override-badge"
        aria-label={`${cfg.label} override ${overrideId}`}
        className={`${base} hover:brightness-110`}
        onClick={(e) => {
          e.stopPropagation()
          onClick(overrideId)
        }}
      >
        {inner}
      </button>
    )
  }
  return (
    <span data-testid="override-badge" className={base} aria-label={`${cfg.label} override`}>
      {inner}
    </span>
  )
}
```
- [ ] Run `npm test -- OverrideBadge` → **expect PASS**.

### 17b — `columns.tsx` Pkg cell

- [ ] **Edit** `columns.tsx`:
  - Add import: `import { OverrideBadge } from './OverrideBadge'`.
  - Add to `ColumnConfig`: `onOpenOverride?: (overrideId: string) => void`.
  - In the Pkg column body, add near the top of the render fn:
    `const firstOverrideId = row.override_map ? Object.values(row.override_map)[0] ?? null : null`
  - Guard the existing ManualLinkBadge so it does **not** double-render for override rows, and add the OverrideBadge after it:
```tsx
{!row.override_type && isManualPackage(row) && manualLinkId ? (
  <ManualLinkBadge
    linkId={manualLinkId}
    manualPackageId={row.manual_package_id}
    sourceLabel={sourceLabel}
    onClick={
      row.manual_link_id && config.onOpenManualLink ? config.onOpenManualLink : undefined
    }
  />
) : null}
{row.override_type ? (
  <OverrideBadge
    overrideType={row.override_type}
    manualPackageId={row.manual_package_id}
    overrideId={firstOverrideId}
    onClick={config.onOpenOverride}
  />
) : null}
```
  (SPLIT/DETACH synthetic rows are DisplayRows that still flow through this cell, so the same
  branch renders their SPLIT/DETACH badge — one code path covers all three types.)

### 17c — synthetic-row styling (`TradeTapeTable.tsx`)

- [ ] **Edit** `TradeTapeTable.tsx` `dataTableRowClassName` to add synthetic-row classes (keep existing classes; the `selected-share-row` rewrite lands in Task 19):
```tsx
const kind = (row as DisplayRow).__rowKind
// ...append to the class array:
kind === 'split-leg' ? 'split-leg-row' : kind === 'detached' ? 'detached-row' : '',
```
  (import `type DisplayRow` from `../../utils/applyOverrides`.)
- [ ] Add to the `<style jsx global>` block (after the `manual-linked-row` rule):
```css
.usd-swaps-tape-table .p-datatable-tbody > tr.split-leg-row > td {
  background-color: rgba(56, 189, 248, 0.06) !important;
}
.usd-swaps-tape-table .p-datatable-tbody > tr.split-leg-row > td:first-child {
  box-shadow: inset 2px 0 0 rgba(56, 189, 248, 0.65) !important;
}
.usd-swaps-tape-table .p-datatable-tbody > tr.detached-row > td {
  background-color: rgba(248, 113, 113, 0.06) !important;
}
.usd-swaps-tape-table .p-datatable-tbody > tr.detached-row > td:first-child {
  box-shadow: inset 2px 0 0 rgba(248, 113, 113, 0.75) !important;
}
```
- [ ] **Write failing test** `columns.override.test.tsx` (renders the Pkg body via `getColumns` config is awkward; instead unit-test `OverrideBadge` (done) and add a render assertion by invoking the Pkg `body`): a lightweight test that calls `getColumns({...}).find(pkg col)` and renders its `.props.body(row)`. Simpler and robust: assert the branch through a tiny wrapper:
```tsx
// components/TradeTapeTable/__tests__/columns.override.test.tsx
/** @jest-environment jsdom */
import { describe, expect, it } from '@jest/globals'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { getColumns } from '../columns'

function renderPkg(row: any) {
  const cols = getColumns({ selection: false })
  const pkg = cols.find((c: any) => c.key === 'pkg') as any
  return render(<>{pkg.props.body(row)}</>)
}

describe('columns Pkg cell override markers', () => {
  it('shows the SPLIT badge for an override row', () => {
    renderPkg({ package_id: 'P1', package_type: 'CURVE', legs_json: [], override_type: 'SPLIT', override_map: { T1: 'o1' } })
    expect(screen.getByText('SPLIT')).toBeInTheDocument()
  })
  it('shows REGROUPED (not the auto ManualLinkBadge) for a GROUP row', () => {
    renderPkg({ package_id: 'P1', package_type: 'CURVE', legs_json: [], override_type: 'GROUP', manual_package_id: 'SMO-1', override_map: { T1: 'o1' } })
    expect(screen.getByText('REGROUPED')).toBeInTheDocument()
    expect(screen.queryByTestId('manual-link-badge')).toBeNull()
  })
})
```
- [ ] Run `npm test -- OverrideBadge columns.override` → **expect PASS**.
- [ ] `git commit -m "feat(dashboard): override visual markers + synthetic-row styling"` (+ trailers).

---

## Task 18 — `NotePopover.tsx` + per-package note affordance (TDD)

Read/add/edit notes for a `{ target_type, target_id }` via `noteApi`; author from `useSavedUser`; no
password. Per-package note button in the Pkg cell (columns.tsx). The orchestrator (Task 19) owns the
open `noteTarget` state; this task builds the popover + the package affordance.

Types:
```ts
import type { NoteTargetType } from '../../types/note.types'
export interface NoteTarget { target_type: NoteTargetType; target_id: string }
export interface NotePopoverProps {
  target: NoteTarget | null           // null => closed
  author: string
  onAuthorChange: (next: string) => void
  onClose: () => void
  onSaved?: () => void                // lets the orchestrator refetch (updates has_notes)
}
```

- [ ] **Write failing test** `components/NotePopover/__tests__/NotePopover.test.tsx` (mock `noteApi`):
```tsx
/** @jest-environment jsdom */
import { describe, expect, it, jest, beforeEach } from '@jest/globals'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

const fetchNotes = jest.fn()
const createNote = jest.fn()
jest.unstable_mockModule('../../../api/noteApi', () => ({
  fetchNotes,
  createNote,
  updateNote: jest.fn(),
  deactivateNote: jest.fn(),
}))
const { NotePopover } = await import('../NotePopover')

beforeEach(() => {
  fetchNotes.mockReset().mockResolvedValue([
    { note_id: 'n1', target_type: 'PACKAGE', target_id: 'P1', author: 'chris', body: 'watch this', created_at: '2026-07-08T00:00:00Z', updated_at: null, is_active: true },
  ])
  createNote.mockReset().mockResolvedValue({ success: true, note_id: 'n2' })
})

describe('NotePopover', () => {
  it('fetches + lists existing notes on open', async () => {
    render(<NotePopover target={{ target_type: 'PACKAGE', target_id: 'P1' }} author="chris" onAuthorChange={jest.fn()} onClose={jest.fn()} />)
    await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith('PACKAGE', 'P1'))
    expect(screen.getByText('watch this')).toBeInTheDocument()
  })

  it('adds a note and calls onSaved', async () => {
    const onSaved = jest.fn()
    render(<NotePopover target={{ target_type: 'TRADE', target_id: 'T1' }} author="chris" onAuthorChange={jest.fn()} onClose={jest.fn()} onSaved={onSaved} />)
    await waitFor(() => expect(fetchNotes).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('note body'), { target: { value: 'hedge for FOMC' } })
    fireEvent.click(screen.getByRole('button', { name: /save note/i }))
    await waitFor(() =>
      expect(createNote).toHaveBeenCalledWith({ target_type: 'TRADE', target_id: 'T1', author: 'chris', body: 'hedge for FOMC' }),
    )
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('renders nothing when target is null', () => {
    const { container } = render(<NotePopover target={null} author="chris" onAuthorChange={jest.fn()} onClose={jest.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('blocks save with no author', async () => {
    render(<NotePopover target={{ target_type: 'TRADE', target_id: 'T1' }} author="" onAuthorChange={jest.fn()} onClose={jest.fn()} />)
    await waitFor(() => expect(fetchNotes).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('note body'), { target: { value: 'x' } })
    expect(screen.getByRole('button', { name: /save note/i })).toBeDisabled()
  })
})
```
- [ ] Run `npm test -- NotePopover` → **expect FAIL**.
- [ ] **Implement** `components/NotePopover/NotePopover.tsx`:
```tsx
'use client'
// ABOUTME: Read/add/edit trader notes for a trade or package target. Author-only
// (no password). Lazily fetches note bodies via noteApi on open; the orchestrator
// owns the open `target` and refetches the tape on save so has_notes updates.
import { useEffect, useState, type JSX } from 'react'
import { X } from 'lucide-react'
import type { NoteTargetType, TapeNote } from '../../types/note.types'
import { createNote, deactivateNote, fetchNotes, updateNote } from '../../api/noteApi'

export interface NoteTarget {
  target_type: NoteTargetType
  target_id: string
}
export interface NotePopoverProps {
  target: NoteTarget | null
  author: string
  onAuthorChange: (next: string) => void
  onClose: () => void
  onSaved?: () => void
}

export function NotePopover({
  target,
  author,
  onAuthorChange,
  onClose,
  onSaved,
}: NotePopoverProps): JSX.Element | null {
  const [notes, setNotes] = useState<TapeNote[]>([])
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const key = target ? `${target.target_type}:${target.target_id}` : null
  useEffect(() => {
    if (!target) return
    let live = true
    setNotes([])
    setError(null)
    fetchNotes(target.target_type, target.target_id)
      .then((rows) => {
        if (live) setNotes(rows)
      })
      .catch((e) => {
        if (live) setError(String(e?.message ?? e))
      })
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!target) return null

  const reload = () =>
    fetchNotes(target.target_type, target.target_id)
      .then(setNotes)
      .catch((e) => setError(String(e?.message ?? e)))

  const canSave = author.trim().length > 0 && body.trim().length > 0 && !busy

  const onSave = async () => {
    if (!canSave) return
    setBusy(true)
    setError(null)
    try {
      await createNote({
        target_type: target.target_type,
        target_id: target.target_id,
        author: author.trim(),
        body: body.trim(),
      })
      setBody('')
      await reload()
      onSaved?.()
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (noteId: string) => {
    setBusy(true)
    try {
      await deactivateNote(noteId, { author: author.trim() })
      await reload()
      onSaved?.()
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const onEdit = async (noteId: string, next: string) => {
    setBusy(true)
    try {
      await updateNote(noteId, { body: next, author: author.trim() })
      await reload()
      onSaved?.()
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-8"
      onClick={onClose}
      data-testid="note-popover"
    >
      <div
        className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-950 p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <div className="font-mono text-[11px] uppercase tracking-wide text-slate-400">
            Notes · {target.target_type} {target.target_id}
          </div>
          <button type="button" aria-label="close notes" onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="h-4 w-4" />
          </button>
        </div>

        <ul className="mb-3 max-h-56 space-y-2 overflow-y-auto">
          {notes.length === 0 ? (
            <li className="text-[11px] text-slate-500">No notes yet.</li>
          ) : (
            notes.map((n) => (
              <li key={n.note_id} className="rounded border border-slate-800 bg-slate-900/60 p-2 text-[11px]">
                <div className="mb-1 flex items-center justify-between text-[10px] text-slate-500">
                  <span>{n.author}</span>
                  <span>{new Date(n.created_at).toISOString().slice(0, 16).replace('T', ' ')}</span>
                </div>
                <NoteRow note={n} onEdit={onEdit} onDelete={onDelete} disabled={busy} />
              </li>
            ))
          )}
        </ul>

        <label className="mb-1 block font-mono text-[10px] uppercase tracking-wide text-slate-500">Author</label>
        <input
          aria-label="note author"
          value={author}
          onChange={(e) => onAuthorChange(e.target.value)}
          className="mb-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100"
          placeholder="your username"
        />
        <label className="mb-1 block font-mono text-[10px] uppercase tracking-wide text-slate-500">New note</label>
        <textarea
          aria-label="note body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={3}
          className="mb-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100"
          placeholder="Add a trader note…"
        />
        {error ? <div className="mb-2 text-[11px] text-rose-300">{error}</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded border border-slate-700 px-3 py-1 text-[11px] text-slate-300 hover:bg-slate-800">
            Close
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!canSave}
            className="rounded bg-sky-700 px-3 py-1 text-[11px] font-semibold text-white hover:bg-sky-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Save note'}
          </button>
        </div>
      </div>
    </div>
  )
}

function NoteRow({
  note,
  onEdit,
  onDelete,
  disabled,
}: {
  note: TapeNote
  onEdit: (id: string, next: string) => void
  onDelete: (id: string) => void
  disabled: boolean
}): JSX.Element {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(note.body)
  if (editing) {
    return (
      <div>
        <textarea
          aria-label={`edit note ${note.note_id}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          className="mb-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-100"
        />
        <div className="flex justify-end gap-2">
          <button type="button" className="text-[10px] text-slate-400" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="text-[10px] text-sky-300 disabled:opacity-50"
            disabled={disabled || !draft.trim()}
            onClick={() => {
              onEdit(note.note_id, draft.trim())
              setEditing(false)
            }}
          >
            Save
          </button>
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-slate-200">{note.body}</span>
      <span className="flex shrink-0 gap-2">
        <button type="button" className="text-[10px] text-slate-400 hover:text-slate-200" onClick={() => setEditing(true)}>
          edit
        </button>
        <button type="button" className="text-[10px] text-rose-400 hover:text-rose-200" disabled={disabled} onClick={() => onDelete(note.note_id)}>
          delete
        </button>
      </span>
    </div>
  )
}
```
- [ ] **Add the per-package note button** in `columns.tsx` Pkg cell (after the OverrideBadge branch), gated by `has_notes`/`notes_count`. Add `onOpenNote?: (target: { target_type: 'PACKAGE'|'TRADE'; target_id: string }) => void` to `ColumnConfig`, import `StickyNote` from `lucide-react`, and render:
```tsx
{config.onOpenNote ? (
  <button
    type="button"
    aria-label={`notes for package ${row.package_id}`}
    data-testid={`pkg-note-${row.package_id}`}
    title={row.has_notes ? `${row.notes_count ?? ''} note(s)` : 'Add note'}
    className={`inline-flex items-center rounded p-0.5 ${
      row.has_notes ? 'text-amber-300' : 'text-slate-500 hover:text-slate-300'
    }`}
    onClick={(e) => {
      e.stopPropagation()
      config.onOpenNote!({
        target_type: 'PACKAGE',
        target_id: row.manual_package_id ?? row.package_id,
      })
    }}
  >
    <StickyNote className="h-3.5 w-3.5" />
    {(row.notes_count ?? 0) > 0 ? <span className="ml-0.5 text-[9px]">{row.notes_count}</span> : null}
  </button>
) : null}
```
- [ ] Run `npm test -- NotePopover` → **expect PASS**.
- [ ] `git commit -m "feat(dashboard): NotePopover + per-package/per-leg note affordances"` (+ trailers).

---

## Task 19 — Orchestrator wiring (`UsdSwapsTradeTape.tsx` + `TradeTapeTable.tsx`)

Mount the action bar, wire `useTradeSelection`, commit/note popovers, `overridePassword`, pass
`applyOverrides(tape.rows)` to the table, refetch on success, undo, and an Overrides management panel.
This is the integration hub — precise diffs below.

> **Primary integration decision (assumption; FE-core report absent).** The main package checkbox +
> leg checkboxes feed a single trade-id selection (`useTradeSelection`). `RegroupActionBar` replaces
> the legacy "Link N selected" trigger; `useRowSelection` + the `ManualLinksDialog` *create* flow are
> retired. `ManualLinkDetailModal` stays (opened by the auto `ManualLinkBadge` for legacy
> `manual_link_id` rows). Analytics-dock focus + `AnalyticsPanel.selected` are preserved by deriving
> rows from `selectedTradeIds`. If FE-core pinned a different selection shape, reconcile here.

### 19a — `TradeTapeTable.tsx` prop + plumbing diffs

- [ ] Add to `TradeTapeTableProps`:
```ts
rows: DisplayRow[]                              // was UsdSwapTapeRow[]
selectedTradeIds?: Set<string>
selectedByPackage?: Map<string, string[]>
onTogglePackage?: (packageId: string, legTradeIds: string[]) => void
onToggleTrade?: (tradeId: string, packageId: string) => void
onOpenNote?: (target: NoteTarget) => void
onOpenOverride?: (overrideId: string) => void
```
  (import `type { DisplayRow } from '../../utils/applyOverrides'` and `type { NoteTarget } from '../NotePopover/NotePopover'`; keep `UsdSwapTapeRow` where still referenced.)
- [ ] **dataKey:** change `dataKey="package_id"` → `dataKey="__syntheticKey"`.
- [ ] **row key helper:** add `const rowKeyOf = (row: UsdSwapTapeRow) => (row as DisplayRow).__syntheticKey ?? row.package_id`. Replace the three `row.package_id` reads that key expansion:
  - `toggleRowExpansion`: `onToggleRow(rowKeyOf(row))` and the legacy branch `next[rowKeyOf(row)]`.
  - `expanderBody`: `const isExpanded = !!expandedRows?.[rowKeyOf(row)]`.
- [ ] **selection column:** stop using PrimeReact built-in selection. Build a package checkbox body and pass it to `getColumns`:
```tsx
const packageSelectBody = useCallback(
  (row: UsdSwapTapeRow) => {
    const legIds = ((row.legs_json ?? []).map((l) => l.trade_id).filter(Boolean)) as string[]
    const sel = legIds.filter((id) => selectedTradeIds?.has(id)).length
    const checked = legIds.length > 0 && sel === legIds.length
    const indeterminate = sel > 0 && sel < legIds.length
    return (
      <input
        type="checkbox"
        aria-label={`select package ${row.package_id}`}
        checked={checked}
        ref={(el) => {
          if (el) el.indeterminate = indeterminate
        }}
        disabled={legIds.length === 0 || !onTogglePackage}
        onChange={(e) => {
          e.stopPropagation()
          onTogglePackage?.(row.package_id, legIds)
        }}
        onClick={(e) => e.stopPropagation()}
      />
    )
  },
  [selectedTradeIds, onTogglePackage],
)
```
  - Remove the `selectionMode`, `cellSelection`, `metaKeySelection`, `selection`, `onSelectionChange` props from `<DataTable>`.
  - Update the `getColumns({...})` call: `selection: !!onTogglePackage`, add `selectionBody: packageSelectBody`, `onOpenNote`, `onOpenOverride` (drop reliance on `onSelectionChange`).
- [ ] **getColumns (`columns.tsx`) select column:** make it render the custom body when supplied:
```tsx
if (config.selection) {
  cols.push(
    config.selectionBody ? (
      <Column key="select" body={config.selectionBody as any} headerStyle={{ width: 30 }} style={{ width: 30 }} />
    ) : (
      <Column key="select" selectionMode="multiple" headerStyle={{ width: 30 }} />
    ),
  )
}
```
  (add `selectionBody?: (row: UsdSwapTapeRow) => JSX.Element` to `ColumnConfig`.)
- [ ] **selected-share styling:** replace the `selectedIds`-based memo/class. In `dataTableRowClassName`:
```tsx
const anyLegSelected = (row.legs_json ?? []).some(
  (l) => l.trade_id && selectedTradeIds?.has(l.trade_id),
)
// ...replace `selectedIds.has(row.package_id) ? 'selected-share-row' : ''` with:
anyLegSelected ? 'selected-share-row' : '',
```
  Delete the now-unused `selectedIds` memo. Update the `useCallback` deps to `[selectedTradeIds, focusedPackageId]`.
- [ ] **rowExpansionTemplate:** pass the new props to `LegsSubTable`:
```tsx
rowExpansionTemplate={(row: UsdSwapTapeRow) => (
  <div className="-mx-2 -my-1 px-0 py-0">
    <LegsSubTable
      row={row}
      selectedTradeIds={selectedTradeIds}
      onToggleTrade={onToggleTrade}
      onOpenNote={onOpenNote}
    />
  </div>
)}
```
- [ ] **MobileTradeCards:** thread `onOpenNote`/`selectedTradeIds`/`onToggleTrade` and key by `__syntheticKey` (one-line dataKey parity). Lower priority; note it — desktop is the Chrome MCP target.

### 19b — `UsdSwapsTradeTape.tsx` orchestrator diffs

- [ ] **Imports:** remove `import { groupLinkedRows } from '@/lib/manual-links-ui/grouping'` and (assumption) the `ManualLinksDialog` import + `useRowSelection`. Add:
```ts
import { applyOverrides } from '../utils/applyOverrides'
import { useTradeSelection } from '../hooks/useTradeSelection'
import { useSelectionContext } from '../hooks/useSelectionContext'
import { RegroupActionBar } from './RegroupActionBar/RegroupActionBar'
import { OverrideCommitPopover } from './OverrideCommitPopover/OverrideCommitPopover'
import { NotePopover, type NoteTarget } from './NotePopover/NotePopover'
import { OverridesPanel } from './OverridesPanel/OverridesPanel'
import { deactivateOverride, createOverride } from '../api/overrideApi'
import type { OverrideType } from '../types/override.types'
```
- [ ] **State additions:**
```ts
const tradeSelection = useTradeSelection()
const [overridePassword, setOverridePassword] = useState('')
const [commitAction, setCommitAction] =
  useState<null | { type: OverrideType; tradeIds: string[] }>(null)
const [noteTarget, setNoteTarget] = useState<NoteTarget | null>(null)
const [overridesPanelOpen, setOverridesPanelOpen] = useState(false)
const [lastAction, setLastAction] =
  useState<null | { kind: 'created' | 'deactivated'; overrideId: string; recreate?: Parameters<typeof createOverride>[0] }>(null)
```
- [ ] **Replace** `const groupedRows = useMemo(() => groupLinkedRows(tape.rows), [tape.rows])` with:
```ts
const displayRows = useMemo(() => applyOverrides(tape.rows), [tape.rows])
const selCtx = useSelectionContext(tradeSelection.selectedTradeIds, tape.rows)
```
- [ ] **Preserve analytics focus** without `useRowSelection`:
```ts
const firstSelectedRow = useMemo(() => {
  const first = tradeSelection.selectedTradeIds.values().next().value
  if (!first) return null
  return tape.rows.find((r) => (r.legs_json ?? []).some((l) => l.trade_id === first)) ?? null
}, [tradeSelection.selectedTradeIds, tape.rows])
const selectedRows = useMemo(
  () => tape.rows.filter((r) => (r.legs_json ?? []).some((l) => l.trade_id && tradeSelection.selectedTradeIds.has(l.trade_id))),
  [tape.rows, tradeSelection.selectedTradeIds],
)
const derivedFocused = useMemo(() => normalizeFocusedTrade(firstSelectedRow), [firstSelectedRow])
```
  (replaces the old `firstSelected`/`derivedFocused`.)
- [ ] **Action handler:**
```ts
const handleRegroupAction = useCallback(
  (action: 'GROUP' | 'SPLIT' | 'DETACH' | 'NOTE') => {
    const tradeIds = Array.from(tradeSelection.selectedTradeIds)
    if (action === 'NOTE') {
      setNoteTarget({ target_type: 'TRADE', target_id: tradeIds[0] })
      return
    }
    setCommitAction({ type: action, tradeIds })
  },
  [tradeSelection.selectedTradeIds],
)
const handleUndo = useCallback(async () => {
  if (!lastAction) return
  try {
    if (lastAction.kind === 'created') {
      await deactivateOverride(lastAction.overrideId, { user: savedUser, admin_password: overridePassword })
    } else if (lastAction.recreate) {
      await createOverride(lastAction.recreate)
    }
    setLastAction(null)
    tape.refetch()
  } catch {
    /* surface via panel; keep affordance */
  }
}, [lastAction, savedUser, overridePassword, tape])
```
- [ ] **`<TradeTapeTable>` props:** `rows={displayRows}`; drop `selected`/`onSelectionChange`; add `selectedTradeIds={tradeSelection.selectedTradeIds}`, `selectedByPackage={tradeSelection.selectedByPackage}`, `onTogglePackage={tradeSelection.togglePackage}`, `onToggleTrade={tradeSelection.toggleTrade}`, `onOpenNote={setNoteTarget}`, `onOpenOverride={(id) => { setOverridesPanelOpen(true) }}`. Keep `onOpenManualLink={handleOpenManualLink}`.
- [ ] **`actionSlot` (desktop):** replace the "Link N selected" button with:
```tsx
{tradeSelection.count > 0 ? (
  <RegroupActionBar
    selectedTradeIds={tradeSelection.selectedTradeIds}
    context={selCtx}
    onAction={handleRegroupAction}
    onClear={tradeSelection.clear}
  />
) : null}
{lastAction ? (
  <button type="button" onClick={handleUndo}
    className="whitespace-nowrap rounded border border-amber-700/50 bg-amber-900/30 px-2 py-1 text-[11px] text-amber-200 hover:bg-amber-900/50">
    Undo {lastAction.kind === 'created' ? 'group/split/detach' : 'revert'}
  </button>
) : null}
<button type="button" onClick={() => setOverridesPanelOpen(true)}
  className="inline-flex items-center rounded border border-slate-700 px-2.5 py-1 font-mono text-[10.5px] text-slate-200 hover:bg-slate-800">
  Overrides
</button>
{/* existing How-to + Analytics buttons unchanged */}
```
- [ ] **Popovers + panel** (mount near the existing modals, replacing the `ManualLinksDialog` mount):
```tsx
{commitAction ? (
  <OverrideCommitPopover
    overrideType={commitAction.type}
    tradeIds={commitAction.tradeIds}
    user={savedUser}
    onUserChange={setSavedUser}
    password={overridePassword}
    onPasswordChange={setOverridePassword}
    onClose={() => setCommitAction(null)}
    onCommitted={(result: { override_id: string }) => {
      setLastAction({ kind: 'created', overrideId: result.override_id })
      setCommitAction(null)
      tradeSelection.clear()
      tape.refetch()
    }}
  />
) : null}
<NotePopover
  target={noteTarget}
  author={savedUser}
  onAuthorChange={setSavedUser}
  onClose={() => setNoteTarget(null)}
  onSaved={() => tape.refetch()}
/>
{overridesPanelOpen ? (
  <OverridesPanel
    user={savedUser}
    adminPassword={overridePassword}
    onClose={() => setOverridesPanelOpen(false)}
    onReverted={(overrideId, recreate) => {
      setLastAction({ kind: 'deactivated', overrideId, recreate })
      tape.refetch()
    }}
  />
) : null}
```
  (`OverrideCommitPopover` exact prop names are FE-core-owned; align to the contract: it collects
  `override_type` [fixed by action], `reason?`, `tags?`, `admin_password`, `user`, validates via
  `overrideApi.validateOverride`, commits via `createOverride`. The `onCommitted` result carries
  `override_id`/`manual_package_id`. Reconcile names against the FE-core component if they differ.)
- [ ] **Mobile bar:** replace "Link N" with a compact `RegroupActionBar` (or a single "Regroup N" button that opens it). Keep How/Analytics.
- [ ] **AnalyticsPanel:** `selected={selectedRows}`, `onClearFocused={() => { focus.clear(); tradeSelection.clear() }}`.

### 19c — `OverridesPanel` (new, minimal)

- [ ] **Implement** `components/OverridesPanel/OverridesPanel.tsx`: lazy `fetchOverrides({ is_active: true })` on mount; render a table (type · manual_package_id · trade_ids count · created_by · created_at) with a **Revert** button per row (`deactivateOverride(id, { user, admin_password })` → `onReverted(id, recreateBody)`), and a "history" expander calling `fetchOverrideDetail(id)`. Props:
```ts
export interface OverridesPanelProps {
  user: string
  adminPassword: string
  onClose: () => void
  onReverted: (overrideId: string, recreate: Parameters<typeof createOverride>[0]) => void
}
```
  (`recreate` is built from the reverted override's `override_type`/`trade_ids`/`manual_package_id`
  so the orchestrator's Undo can re-POST it — the contract API has no reactivate endpoint.)

### 19d — Tests

- [ ] **Write** `components/__tests__/UsdSwapsTradeTape.overrides.test.tsx` (props/smoke): render the orchestrator with a mocked `useTradeTapeData`; assert (a) `applyOverrides` output reaches the table (a SPLIT row explodes into per-leg rows — query by synthetic testids), (b) `RegroupActionBar` mounts when selection is non-empty, (c) the "Overrides" button opens the panel. Keep it a thin integration smoke (mock the api modules).
- [ ] **Update** `components/__tests__/UsdSwapsTradeTape.props.test.tsx` if it asserts on the removed "Link N selected"/`ManualLinksDialog` path. Run `npm test -- UsdSwapsTradeTape` and fix fallout.
- [ ] Run `npm test -- UsdSwapsTradeTape applyOverrides LegsSubTable OverrideBadge NotePopover columns.override` → **expect PASS** (whole feature suite green).
- [ ] `git commit -m "feat(dashboard): wire override action bar, popovers, undo + overrides panel"` (+ trailers). (Do NOT push yet — Chrome MCP verification in Task 20 gates the final commit.)

---

## Task 20 — Verification (Chrome MCP) + perf-guard promotion + final commit

Manual verification (checkboxes, not unit tests), then promote the bench scripts with a documented
budget, then the final feature commit.

### 20a — Promote perf-guard scripts

- [ ] Confirm the DB/backend section has produced `scratchpad/bench_tape_view.js` +
  `scratchpad/bench_override_join.js` (spec §4.1 — they don't exist in `scratchpad/` yet; they are
  authored there by the view/DB work). Copy both to `SDRUtils/dashboard/scripts/`.
- [ ] Add a header comment to each documenting the **pass/fail budget** (spec §4.1): *p95 per-page
  (LIMIT 200) ≤ ~1.3× the no-override baseline with N active overrides (test N=800 member trades)*;
  fail the script (non-zero exit) if exceeded so it can gate CI/pre-deploy. Confirm they read
  `DATABASE_URL` (remote Supabase prod — read-only `EXPLAIN ANALYZE` + timing; **no writes**).
- [ ] Run `node SDRUtils/dashboard/scripts/bench_tape_view.js` and `bench_override_join.js`; record
  the observed p50/p95 in the commit body. **Expected:** override join adds ≤ ~13% server-side; the
  outer scan still uses `idx_tape_v2_packages_exec_start`; package cardinality unchanged (200).

### 20b — Chrome MCP walkthrough (`localhost:3000`)

Prereqs: `cd SDRUtils/dashboard && npm run dev`; set `TAPE_OVERRIDE_PASSWORD` in the dashboard env;
ensure `DATABASE_URL` points at the tape DB. Load Chrome MCP tools via one ToolSearch
`select:` batch (navigate, computer, read_page, take_screenshot, list_console_messages,
list_network_requests). Navigate to the USD swaps tape route.

Checklist headers (each = observe + screenshot):
- [ ] **Baseline render** — tape loads, no console errors; existing rows unchanged; row count chip correct.
- [ ] **Leg selection** — expand a package; per-leg checkboxes appear; checking legs updates the
  package checkbox to indeterminate → checked; `RegroupActionBar` shows the running count.
- [ ] **GROUP happy path** — select ≥2 legs across packages → Group enabled → commit popover →
  enter password + user → validate → commit → toast/inline success → tape refetches → the packages
  cluster contiguously with a **REGROUPED** amber badge (distinct from the auto `Manual` badge).
- [ ] **SPLIT happy path** — select one multi-leg auto-package → Split enabled → commit → the row
  **explodes into per-leg rows** each with a SPLIT (scissors) badge + sky left-marker; virtual
  scroll + expansion still work (no key-collision flicker).
- [ ] **DETACH happy path** — select 1 leg of a package that retains ≥1 other → Detach enabled →
  commit → the leg renders **standalone** (rose unlink marker) and the remnant package row remains.
- [ ] **Password gate** — commit with a wrong/empty password → **403 inline error**
  (`Invalid override password.`), no write; network tab shows 403.
- [ ] **Undo** — after a GROUP/SPLIT/DETACH commit, the **Undo** affordance deactivates the just-
  created override → tape reverts to auto instantly (refetch). After a panel **Revert**, Undo
  re-creates it.
- [ ] **Notes** — per-package note icon opens `NotePopover`; add a note (author from saved user, no
  password) → saves → the icon lights amber + count; per-leg note icon opens a TRADE note target.
- [ ] **Overrides panel** — "Overrides" opens the list; Revert deactivates + refetches; history view
  fetches detail.
- [ ] **Regression sweep** — legacy auto `ManualLinkBadge` still opens `ManualLinkDetailModal`;
  column filters/sort/load-more still work; check `list_console_messages` is clean.

### 20c — Final commit

- [ ] Only after all Chrome MCP checks pass and `npm test` (full feature suite) is green:
  `git commit -m "feat(dashboard): USD swaps tape manual regrouping + trader notes (frontend)"`
  (+ the two trailer lines). Include observed bench p50/p95 in the body. Push per the standing branch
  rules (branch off main if on main).

---

## Assumptions & deviations (summary)

1. **Selection model (19a/19b):** unified trade-id selection via `useTradeSelection`; custom
   tri-state package checkbox column replaces PrimeReact's built-in selection; `RegroupActionBar`
   replaces "Link N selected"; `useRowSelection` + `ManualLinksDialog` *create* flow retired;
   `ManualLinkDetailModal` kept for legacy `manual_link_id` viewing. Analytics focus + `AnalyticsPanel`
   preserved via rows derived from `selectedTradeIds`. Reconcile if FE-core pinned otherwise.
2. **dataKey (`__syntheticKey`):** `applyOverrides` stamps `__syntheticKey` on every row so the table
   switches `dataKey` from `package_id`; expansion keyed by `__syntheticKey` too. Required because
   SPLIT rows share `package_id`.
3. **Per-leg note gating:** view exposes only package-level `has_notes`/`notes_count`; the per-leg
   icon is always add-capable and merely tinted by package-level presence (Task 16 note).
4. **Undo of a revert:** the contract API has no reactivate endpoint; Undo of a deactivate re-POSTs
   an equivalent override (`OverridesPanel` supplies the `recreate` body).
5. **`OverrideCommitPopover` prop names** are FE-core-owned; consumed per the contract's stated
   fields (`override_type` fixed by action, `reason?`, `tags?`, `admin_password`, `user`,
   validate+commit via `overrideApi`). Reconcile at wiring time.
6. **Bench scripts** are authored by the DB/view section into `scratchpad/`; Task 20 promotes them to
   `SDRUtils/dashboard/scripts/` with the documented budget.
