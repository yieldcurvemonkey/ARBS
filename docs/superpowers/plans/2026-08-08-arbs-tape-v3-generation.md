# ARBS tape `_v3` generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an ARBS-owned `_v3` tape generation, backfill it over 611 days with current logic, and point the ARBS dashboard at it — leaving `_v2` entirely to the `sky` cron job that serves a different front end.

**Architecture:** A single `TAPE_GENERATION` constant drives every table, view, and index name the ARBS pipeline writes. A writer guard refuses to target `_v2` unless explicitly overridden. The existing v2 DDL is parameterised in place (three name families: tables, indexes, VWAP) rather than copied a third time. The backfill runs day-by-day, newest-first, resumable via a ledger.

**Tech Stack:** Python 3 / pandas / SQLAlchemy / psycopg2 against prod Supabase Postgres; Next.js + TypeScript dashboard; pytest; jest.

**Spec:** `docs/superpowers/specs/2026-08-08-arbs-tape-v3-generation-design.md`

## Global Constraints

- **Worktree:** `C:\Users\chris\clee\ARBS-v3`, branch `feat/tape-v3-generation`. Every git command must name its tree: `git -C C:/Users/chris/clee/ARBS-v3 ...`. Never rely on `cd` having stuck.
- **Python interpreter:** `C:\Users\chris\anaconda3\envs\stir\python.exe`, invoked **directly**. Do NOT use `conda run` — parallel `conda run` invocations collide on a temp file and return empty output with exit code 0, which reads as a passing test run.
- **Set `ARBS_SUPABASE_ENABLED=0`** in the environment before any script that imports `Caching`.
- **Backfill cache path is mandatory:** `--cache-path C:\Users\chris\clee\ARBS\sdr_cache`. The default resolves `./sdr_cache` relative to CWD; from this worktree that is an empty directory and all 611 days silently re-download from DTCC.
- **Dashboard tests:** `npm test` only. Plain `npx jest` bypasses the ESM mocks and produces false Supabase failures.
- **`TAPE_GENERATION` is `"v3"`** in Python and `'v3'` in TypeScript — two independent constants, deliberately not a shared env var.
- **Never write `_v2`.** It is owned by `run_swaptape` on host `sky`.

---

### Task 1: Generation seam and writer guard

**Files:**
- Create: `SDRUtils/_swappulse_scripts/_tape_tables.py`
- Test: `tests/test_tape_generation_seam.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: module `SDRUtils._swappulse_scripts._tape_tables` exporting `TAPE_GENERATION: str`, `IDX_INFIX: str`, `MANUAL_LINKS_TABLE: str`, `assert_writable_generation() -> None`, and the table-name constants `PACKAGES_TABLE`, `LEGS_TABLE`, `RUNS_TABLE`, `DISPLAY_VIEW`, `OVERRIDES_TABLE`, `OVERRIDE_MEMBERS_TABLE`, `OVERRIDE_HISTORY_TABLE`, `NOTES_TABLE`, `VWAP_TABLE`, `SIGNAL_TABLE`, `QUALITY_VIEW` — all `str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tape_generation_seam.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_tape_generation_seam.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'SDRUtils._swappulse_scripts._tape_tables'`

- [ ] **Step 3: Write the implementation**

Create `SDRUtils/_swappulse_scripts/_tape_tables.py`:

```python
"""Single source of truth for the ARBS-owned tape table generation.

The USD-swaps tape has two writers. ``arbs_usd_swap_tape_*_v2`` is owned by
the ``run_swaptape`` cron job on the host ``sky`` (``/home/peter/SwapPulse``),
which serves a different front end and must keep running. ARBS owns ``_v3``.

Every table, view, and index name the ARBS pipeline writes derives from
``TAPE_GENERATION`` here, so moving to a future generation is a one-line
change and no literal suffix is left stranded in a query.
"""
from __future__ import annotations

import os

TAPE_GENERATION = "v3"

# Index and constraint names are schema-global in Postgres, so they must
# carry the generation too. `CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_exec
# ON <a v3 table>` matches the *existing v2 index name*, skips, and reports
# success -- leaving the new generation silently unindexed on millions of
# rows with nothing raised.
IDX_INFIX = TAPE_GENERATION


def _t(base: str) -> str:
    return f"arbs_usd_swap_{base}_{TAPE_GENERATION}"


PACKAGES_TABLE = _t("tape_packages")
LEGS_TABLE = _t("tape_legs")
RUNS_TABLE = _t("tape_ingestion_runs")
DISPLAY_VIEW = _t("tape_display")
OVERRIDES_TABLE = _t("tape_overrides")
OVERRIDE_MEMBERS_TABLE = _t("tape_override_members")
OVERRIDE_HISTORY_TABLE = _t("tape_override_history")
NOTES_TABLE = _t("tape_notes")
VWAP_TABLE = _t("vwap_daily")
SIGNAL_TABLE = _t("tape_signal")
QUALITY_VIEW = _t("tape_quality_daily")

# Deliberately NOT versioned: keyed by its own UUID and shared with the
# classification stage (``ingest_usdswaps.py``), which stays on v2.
MANUAL_LINKS_TABLE = "arbs_usd_swap_manual_links_v2"


def assert_writable_generation() -> None:
    """Refuse to write a tape generation ARBS does not own.

    Called from every write path. The failure this prevents is not
    hypothetical: ARBS and the ``sky`` job both delete-and-rewrite a whole
    ``as_of`` day, so a misconfigured run destroys the other front end's
    data for that day rather than merely duplicating it.
    """
    if TAPE_GENERATION == "v2" and os.getenv("ARBS_ALLOW_V2_WRITES") != "1":
        raise RuntimeError(
            "Refusing to write the _v2 tape: it is owned by the `sky` "
            "run_swaptape job and serves a different front end. "
            "Set ARBS_ALLOW_V2_WRITES=1 to override."
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_tape_generation_seam.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-v3 add SDRUtils/_swappulse_scripts/_tape_tables.py tests/test_tape_generation_seam.py
git -C C:/Users/chris/clee/ARBS-v3 commit -m "feat(tape): add the generation seam and writer guard

Every ARBS-written tape object name now derives from a single
TAPE_GENERATION constant, and a guard refuses to target _v2, which is
owned by the run_swaptape job on sky. Both writers delete-and-rewrite a
whole as_of day, so a misconfigured run destroys the other front end's
data rather than duplicating it -- the guard makes that impossible by
default rather than by discipline."
```

---

### Task 2: Parameterise the v2 DDL

The DDL interpolates table names but hardcodes **37 index and constraint names** containing `v2` as literal text, and hardcodes the VWAP table name at two lines. Because `CREATE INDEX IF NOT EXISTS` matches on the *index name* and index names are schema-global, leaving these would create v3 with **zero indexes** and raise nothing.

**Files:**
- Rename: `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` → `SDRUtils/_swappulse_scripts/_tape_schema_current.py`
- Modify: the renamed file's constants block, 37 index names, and VWAP block
- Test: `tests/test_tape_schema_generation.py`

**Interfaces:**
- Consumes: `_tape_tables` constants from Task 1.
- Produces: module `SDRUtils._swappulse_scripts._tape_schema_current` exporting `TAPE_SCHEMA_SQL_CURRENT: str`, `SIGNAL_TABLE_DDL: str`, `SIGNAL_REALTIME_DDL: str`, and the untouched `FREEZE_V1_SQL: str`. All previously-exported `*_V2` name constants are removed; consumers import names from `_tape_tables` instead.

**Note on the VWAP block:** there is no separate VWAP DDL constant. The VWAP `CREATE TABLE` (line 633) and its index (line 643) sit *inside* `TAPE_SCHEMA_SQL_V2`, which spans lines 32-645. Because that is already an f-string, replacing the literal `arbs_usd_swap_vwap_daily_v2` with `{VWAP_TABLE}` interpolates correctly with no new constant. `FREEZE_V1_SQL` (line 680) is a plain non-f string of v1 runbook DDL — leave it entirely alone.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tape_schema_generation.py`:

```python
from __future__ import annotations

import re

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts._tape_schema_current import (
    SIGNAL_TABLE_DDL,
    TAPE_SCHEMA_SQL_CURRENT,
)

# The VWAP DDL is inside TAPE_SCHEMA_SQL_CURRENT, not a separate constant.
ALL_DDL = TAPE_SCHEMA_SQL_CURRENT + SIGNAL_TABLE_DDL

# Index names are schema-global. An index name still pinned to v2 makes
# `CREATE INDEX IF NOT EXISTS` match the existing v2 index, skip, and
# report success -- leaving v3 unindexed on millions of rows.
INDEX_NAME_RE = re.compile(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS\s+(\w+)")


def test_no_index_name_is_pinned_to_v2():
    stray = sorted({n for n in INDEX_NAME_RE.findall(ALL_DDL) if "v2" in n})
    assert stray == [], f"index names still pinned to v2: {stray}"


def test_every_index_name_carries_the_generation():
    names = sorted(set(INDEX_NAME_RE.findall(ALL_DDL)))
    assert len(names) >= 36, f"expected >=36 index names, found {len(names)}"
    missing = [n for n in names if f"_{tt.IDX_INFIX}_" not in n]
    assert missing == [], f"index names missing the generation infix: {missing}"


def test_ddl_targets_v3_tables():
    assert tt.LEGS_TABLE in TAPE_SCHEMA_SQL_CURRENT
    assert tt.PACKAGES_TABLE in TAPE_SCHEMA_SQL_CURRENT
    assert tt.DISPLAY_VIEW in TAPE_SCHEMA_SQL_CURRENT
    assert "arbs_usd_swap_tape_legs_v2" not in ALL_DDL
    assert "arbs_usd_swap_tape_packages_v2" not in ALL_DDL


def test_vwap_block_is_parameterised():
    # The VWAP block sits inside TAPE_SCHEMA_SQL and hardcoded its table
    # name, with VWAP_TABLE_V2 defined *after* the DDL that should have
    # used it.
    assert tt.VWAP_TABLE in TAPE_SCHEMA_SQL_CURRENT
    assert "arbs_usd_swap_vwap_daily_v2" not in TAPE_SCHEMA_SQL_CURRENT


def test_manual_links_reference_is_still_v2():
    # The display view joins the shared, unversioned manual-links table.
    assert tt.MANUAL_LINKS_TABLE in TAPE_SCHEMA_SQL_CURRENT
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_tape_schema_generation.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'SDRUtils._swappulse_scripts._tape_schema_current'`

- [ ] **Step 3: Rename the module**

```bash
git -C C:/Users/chris/clee/ARBS-v3 mv \
  SDRUtils/_swappulse_scripts/_tape_schema_v2.py \
  SDRUtils/_swappulse_scripts/_tape_schema_current.py
```

- [ ] **Step 4: Apply the mechanical rewrite**

37 hand-edits invite error, so do it deterministically. Create `scripts/_rewrite_tape_ddl.py` (a one-shot migration helper; delete it in Step 8):

```python
"""One-shot: parameterise the tape DDL onto the generation seam."""
from __future__ import annotations

import re
from pathlib import Path

FP = Path("SDRUtils/_swappulse_scripts/_tape_schema_current.py")
src = FP.read_text(encoding="utf-8")

# 1. Index and constraint names: idx_tape_v2_* / uq_tape_v2_* / idx_vwap_v2_*
src = re.sub(r"\b(idx|uq)_(tape|vwap)_v2_", r"\1_\2_{IDX_INFIX}_", src)

# 2. VWAP block: the only hardcoded table literal in the DDL text.
src = src.replace("arbs_usd_swap_vwap_daily_v2", "{VWAP_TABLE}")

# 3. Drop the old constants block; import the names from the seam instead.
old_consts = re.compile(
    r"^PACKAGES_TABLE_V2 = .*?^NOTES_TABLE_V2 = .*?$", re.S | re.M
)
src = old_consts.sub("", src, count=1)
src = src.replace(
    "from __future__ import annotations\n",
    "from __future__ import annotations\n\n"
    "from ._tape_tables import (\n"
    "    DISPLAY_VIEW,\n"
    "    IDX_INFIX,\n"
    "    LEGS_TABLE,\n"
    "    MANUAL_LINKS_TABLE,\n"
    "    NOTES_TABLE,\n"
    "    OVERRIDE_HISTORY_TABLE,\n"
    "    OVERRIDE_MEMBERS_TABLE,\n"
    "    OVERRIDES_TABLE,\n"
    "    PACKAGES_TABLE,\n"
    "    RUNS_TABLE,\n"
    "    SIGNAL_TABLE,\n"
    "    VWAP_TABLE,\n"
    ")\n",
    1,
)

# 4. Repoint every remaining {NAME_V2} placeholder at the seam constant.
for old, new in [
    ("{PACKAGES_TABLE_V2}", "{PACKAGES_TABLE}"),
    ("{LEGS_TABLE_V2}", "{LEGS_TABLE}"),
    ("{RUNS_TABLE_V2}", "{RUNS_TABLE}"),
    ("{DISPLAY_VIEW_V2}", "{DISPLAY_VIEW}"),
    ("{OVERRIDES_TABLE_V2}", "{OVERRIDES_TABLE}"),
    ("{OVERRIDE_MEMBERS_TABLE_V2}", "{OVERRIDE_MEMBERS_TABLE}"),
    ("{OVERRIDE_HISTORY_TABLE_V2}", "{OVERRIDE_HISTORY_TABLE}"),
    ("{NOTES_TABLE_V2}", "{NOTES_TABLE}"),
    ("{SIGNAL_TABLE_V2}", "{SIGNAL_TABLE}"),
]:
    src = src.replace(old, new)

# 5. Rename the exported DDL constants.
src = src.replace("TAPE_SCHEMA_SQL_V2", "TAPE_SCHEMA_SQL_CURRENT")
src = re.sub(r"^VWAP_TABLE_V2 = .*$", "", src, flags=re.M)
src = re.sub(r"^SIGNAL_TABLE_V2 = .*$", "", src, flags=re.M)

FP.write_text(src, encoding="utf-8")
print("rewritten")
```

Run it, then **read the file** and fix by hand anything the regex missed. Two things to confirm specifically: that `TAPE_SCHEMA_SQL_CURRENT` is still declared `f"""` (the `{...}` placeholders only interpolate in an f-string), and that `FREEZE_V1_SQL` at the bottom is untouched — it is a plain non-f string of v1 runbook DDL and must stay that way.

```bash
cd C:/Users/chris/clee/ARBS-v3 && C:/Users/chris/anaconda3/envs/stir/python.exe scripts/_rewrite_tape_ddl.py
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_tape_schema_generation.py -v
```

Expected: PASS, 5 tests. If `test_every_index_name_carries_the_generation` reports missing names, those are indexes the regex did not match — fix them by hand and re-run.

- [ ] **Step 6: Delete the one-shot helper and commit**

```bash
rm C:/Users/chris/clee/ARBS-v3/scripts/_rewrite_tape_ddl.py
git -C C:/Users/chris/clee/ARBS-v3 add -A SDRUtils/_swappulse_scripts/ tests/test_tape_schema_generation.py
git -C C:/Users/chris/clee/ARBS-v3 commit -m "feat(tape): parameterise the tape DDL onto the generation seam

Table names were already interpolated, but 37 index and constraint names
carried v2 as literal text and the VWAP block hardcoded its table name.
Index names are schema-global, so CREATE INDEX IF NOT EXISTS would have
matched the existing v2 index, skipped, and reported success -- creating
v3 with zero indexes on 2.3M legs and raising nothing. Tests assert no
index name is pinned to v2 and that all 36+ carry the generation infix."
```

---

### Task 3: Route the remaining Python literals through the seam

`_LATEST_MIGRATION_COLS` is a **hard blocker**, not a cosmetic literal: it feeds `_schema_already_current()`, which short-circuits `ensure_schema()` when the named columns exist. It names `_v2` tables, and sky's v2 tables carry every one of those columns, so `ensure_schema()` would skip all DDL and the v3 tables would never be created. It runs on every ingest (`ingest_usdswaps_tape.py:2175`).

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py:31-41` (import block), `:545-562` (`_LATEST_MIGRATION_COLS`)
- Modify: `SDRUtils/_swappulse_scripts/_tape_monitoring_v2.py:18,50`
- Modify: `SDRUtils/stir_flow/trade_selection.py:34-35,47-48`
- Modify: `SDRUtils/stir_flow/unwinds.py:42,49`
- Test: `tests/test_tape_generation_seam.py` (extend)

**Interfaces:**
- Consumes: `_tape_tables` (Task 1), `_tape_schema_current` (Task 2).
- Produces: no new public API. `ingest_usdswaps_tape` continues to expose `LEGS_TABLE`, `PACKAGES_TABLE`, `RUNS_TABLE` at module level (now sourced from `_tape_tables`), which Task 4's parity script imports.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tape_generation_seam.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_tape_generation_seam.py -v
```

Expected: FAIL — `test_migration_cols_target_the_current_generation` reports v2 table names; `test_no_v2_tape_literals_remain_in_python` lists `_tape_monitoring_v2.py`, `stir_flow/trade_selection.py`, `stir_flow/unwinds.py`.

- [ ] **Step 3: Rewrite the import block**

In `ingest_usdswaps_tape.py`, replace lines 31-41 with:

```python
from ._tape_schema_current import (
    SIGNAL_REALTIME_DDL,
    SIGNAL_TABLE_DDL,
    TAPE_SCHEMA_SQL_CURRENT,
)
from ._tape_tables import (
    DISPLAY_VIEW,
    LEGS_TABLE,
    MANUAL_LINKS_TABLE,
    PACKAGES_TABLE,
    RUNS_TABLE,
    SIGNAL_TABLE,
    VWAP_TABLE,
    assert_writable_generation,
)
```

Then fix every downstream reference: `DISPLAY_VIEW_V2` → `DISPLAY_VIEW`, `SIGNAL_TABLE_V2` → `SIGNAL_TABLE`, `TAPE_SCHEMA_SQL_V2` → `TAPE_SCHEMA_SQL_CURRENT`, and the local import at line ~2055 (`from ..._tape_schema_v2 import VWAP_TABLE_V2`) → `from ._tape_tables import VWAP_TABLE`.

- [ ] **Step 4: Rewrite `_LATEST_MIGRATION_COLS`**

Replace `ingest_usdswaps_tape.py:545-562` with:

```python
# Migration markers for _schema_already_current(). These MUST name the
# current generation's tables: the check is by column name against the
# named table, so pointing it at another generation that happens to have
# those columns makes ensure_schema() skip all DDL and silently never
# create this generation's tables at all.
_LATEST_MIGRATION_COLS = [
    (PACKAGES_TABLE, "ptp_price_notation"),
    (LEGS_TABLE, "opa_signed_amount"),
    (OVERRIDES_TABLE, "override_id"),
    (DISPLAY_VIEW, "override_map"),
    # Matched-maturity (MMS) migration markers.
    (PACKAGES_TABLE, "is_matched_maturity_all"),
    (LEGS_TABLE, "matched_ust_maturity"),
    # MMS bond-reference marker (CUSIP details in expanded row).
    (LEGS_TABLE, "ust_coupon"),
    # Execution-vs-event timestamp integration (2026-07-17).
    (LEGS_TABLE, "event_timestamp"),
    (PACKAGES_TABLE, "event_start"),
]
```

Add `OVERRIDES_TABLE` to the `._tape_tables` import list from Step 3.

- [ ] **Step 5: Wire the guard into `ensure_schema`**

In `ingest_usdswaps_tape.py`, insert as the first statement of `ensure_schema()` (currently line 600, `key = str(engine.url)`):

```python
    assert_writable_generation()
```

- [ ] **Step 6: Repoint the monitoring view and the two stir_flow readers**

`_tape_monitoring_v2.py` — make `MONITORING_SQL_V2` an f-string and import from the seam:

```python
from ._tape_tables import LEGS_TABLE, QUALITY_VIEW
```

then `CREATE OR REPLACE VIEW arbs_usd_swap_tape_quality_daily_v2 AS` → `CREATE OR REPLACE VIEW {QUALITY_VIEW} AS`, and `FROM arbs_usd_swap_tape_legs_v2 l` → `FROM {LEGS_TABLE} l`.

`stir_flow/trade_selection.py` and `stir_flow/unwinds.py` are **readers**. Move them to v3 — v3 is the corrected data, and the missing `ptp_group_id` is exactly what distorts dealer-flow analysis. Import `LEGS_TABLE` / `PACKAGES_TABLE` from `SDRUtils._swappulse_scripts._tape_tables` and interpolate them into the SQL strings.

- [ ] **Step 7: Run the tests**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest \
  tests/test_tape_generation_seam.py tests/test_tape_schema_generation.py \
  tests/test_ddl_bundle.py tests/test_ingest_usdswaps_tape_schema.py -v
```

Expected: PASS. Then the fast gate:

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests \
  -m "not slow and not network and not db" -q
```

Expected: no new failures against the baseline on `main`. Record the counts.

- [ ] **Step 8: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-v3 add -A SDRUtils/ tests/
git -C C:/Users/chris/clee/ARBS-v3 commit -m "feat(tape): route the remaining Python literals through the seam

_LATEST_MIGRATION_COLS was the blocker: it feeds _schema_already_current(),
which short-circuits ensure_schema() when the named columns exist. It named
_v2 tables, and sky's v2 tables carry all those columns, so ensure_schema
would have skipped every CREATE and the v3 tables would never have been
created -- on the hot path, on day one of the backfill.

Also repoints the monitoring quality view and the two stir_flow readers,
and wires assert_writable_generation() into ensure_schema. A regression
test now fails on any hardcoded _v2 tape literal in SDRUtils."
```

---

### Task 4: Create the v3 objects and verify parity

**Files:**
- Create: `scripts/tape_v3_parity_check.py`
- Test: manual run against prod (this task's deliverable is a verified schema, not a unit test)

**Interfaces:**
- Consumes: `ingest_usdswaps_tape.ensure_schema`, `_tape_tables` constants, `ingest_usdswaps.get_db_connection_string`.
- Produces: `scripts/tape_v3_parity_check.py`, runnable as `python scripts/tape_v3_parity_check.py`, exit 0 on parity and 1 on any mismatch. Task 8 re-runs it.

- [ ] **Step 1: Write the parity checker**

Create `scripts/tape_v3_parity_check.py`:

```python
"""Verify the v3 tape schema matches what the pipeline writes.

Three column sets must agree:
  1. v3's actual columns (information_schema)
  2. live v2's columns, minus `producer` (added by the sky writer)
  3. the column list the ingest's INSERT statements build

A column in (2) or (3) missing from (1) is silent data loss -- a column
never inserted looks exactly like a column always NULL.

Index parity is checked alongside, because a v3 with zero indexes passes
every column check while being unusable.

The check validates itself against a known answer: `producer` MUST appear
in (2) and in neither (1) nor (3). A run that does not report that is
broken, and its "pass" means nothing.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import LEG_COLUMNS, PACKAGE_COLUMNS

V2_LEGS = "arbs_usd_swap_tape_legs_v2"
V2_PACKAGES = "arbs_usd_swap_tape_packages_v2"


def _columns(conn, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t"
            ),
            {"t": table},
        )
    }


def _index_count(conn, table: str) -> int:
    return conn.execute(
        text("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND tablename=:t"),
        {"t": table},
    ).scalar_one()


def main() -> int:
    engine = create_engine(get_db_connection_string())
    failures: list[str] = []

    with engine.connect() as conn:
        pairs = [
            ("legs", tt.LEGS_TABLE, V2_LEGS, set(LEG_COLUMNS)),
            ("packages", tt.PACKAGES_TABLE, V2_PACKAGES, set(PACKAGE_COLUMNS)),
        ]
        for label, v3_table, v2_table, insert_cols in pairs:
            v3_cols = _columns(conn, v3_table)
            v2_cols = _columns(conn, v2_table)

            if not v3_cols:
                failures.append(f"{label}: {v3_table} does not exist")
                continue

            # --- self-validation against a known answer -------------------
            if "producer" not in v2_cols:
                failures.append(
                    f"{label}: SELF-CHECK FAILED -- `producer` absent from live "
                    f"{v2_table}. The check cannot be trusted; investigate before "
                    "reading any result below."
                )
            if "producer" in v3_cols:
                failures.append(f"{label}: v3 unexpectedly carries `producer`")

            expected = (v2_cols - {"producer"}) | insert_cols
            missing = sorted(expected - v3_cols)
            if missing:
                failures.append(f"{label}: v3 missing {len(missing)} columns: {missing}")

            not_written = sorted(v3_cols - insert_cols - {"created_at", "updated_at"})
            if not_written:
                print(f"  [note] {label}: in v3 but not in INSERT list: {not_written}")

            v3_idx, v2_idx = _index_count(conn, v3_table), _index_count(conn, v2_table)
            print(f"  {label}: v3 cols={len(v3_cols)} v2 cols={len(v2_cols)} "
                  f"v3 idx={v3_idx} v2 idx={v2_idx}")
            if v3_idx < v2_idx:
                failures.append(
                    f"{label}: v3 has {v3_idx} indexes vs v2's {v2_idx}. Index names "
                    "are schema-global -- CREATE INDEX IF NOT EXISTS silently skipped."
                )

    if failures:
        print("\nPARITY FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPARITY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Both column tuples are verified to exist: `LEG_COLUMNS` at `ingest_usdswaps_tape.py:49` and `PACKAGE_COLUMNS` at `:199`.

- [ ] **Step 2: Create the v3 objects**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -c "from sqlalchemy import create_engine; from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string; from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import ensure_schema; ensure_schema(create_engine(get_db_connection_string())); print('schema ensured')"
```

Expected: `schema ensured`, no exception.

- [ ] **Step 3: Run the parity check**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe scripts/tape_v3_parity_check.py
```

Expected: `PARITY OK`, exit 0, with `v3 idx` **greater than zero and >= `v2 idx`**. If `v3 idx` is 0, Task 2's index parameterisation did not take — go back and fix it; do not proceed.

- [ ] **Step 4: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-v3 add scripts/tape_v3_parity_check.py
git -C C:/Users/chris/clee/ARBS-v3 commit -m "feat(tape): add the v3 schema parity check

Compares v3's columns against live v2 minus producer and against the
ingest's INSERT column list, and asserts index-count parity -- a v3 with
zero indexes passes every column and row-count check while being
unusable. The check validates itself against a known answer: producer
must appear in v2 and in neither v3 nor the INSERT list, so a run that
fails to report that is broken and its pass means nothing."
```

---

### Task 5: Pilot three days

Before committing to a run of ~10 h or more, prove the pipeline works at both ends of the range. The 2024 date is the real test: it exercises whether ERIS EOD curves reach back that far. Risk pricing depends on them and their absence is the most likely cause of a failed 2024 tail.

**Files:**
- Create: `docs/superpowers/plans/2026-08-08-tape-v3-backfill-ledger.md` (running record)

**Interfaces:**
- Consumes: the verified v3 schema from Task 4.
- Produces: a measured per-day wall-clock figure that Task 8's go/no-go decision uses, and a recorded frozen SHA.

- [ ] **Step 1: Freeze and record the code SHA**

```bash
git -C C:/Users/chris/clee/ARBS-v3 log --oneline -1
git -C C:/Users/chris/clee/ARBS-v3 status --porcelain
```

The working tree must be clean. Record the SHA in the ledger file — editing pipeline code mid-backfill splits the output into two logic vintages with nothing to distinguish them.

- [ ] **Step 2: Snapshot the v2 non-interference baseline**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -c "
from sqlalchemy import create_engine, text
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string
import datetime
e = create_engine(get_db_connection_string())
with e.connect() as c:
    print('backfill_start (UTC):', datetime.datetime.now(datetime.timezone.utc).isoformat())
    for t in ('arbs_usd_swap_tape_legs_v2','arbs_usd_swap_tape_packages_v2'):
        print(t, c.execute(text(f'SELECT count(*), max(created_at) FROM {t}')).fetchone())
"
```

Record `backfill_start` in the ledger. Task 8 asserts against it.

- [ ] **Step 3: Run the three pilot days, timing each**

```bash
cd C:/Users/chris/clee/ARBS-v3
for d in 2026-08-06 2025-06-02 2024-03-04; do
  echo "=== $d ==="
  ARBS_SUPABASE_ENABLED=0 /usr/bin/time -f "%e s" \
    C:/Users/chris/anaconda3/envs/stir/python.exe -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline \
    backfill --date "$d" --cache-path C:/Users/chris/clee/ARBS/sdr_cache
done
```

(On PowerShell use `Measure-Command` instead of `/usr/bin/time`.)

Expected: three successful runs. Record wall-clock per day in the ledger.

- [ ] **Step 4: Verify the pilot days landed correctly**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -c "
from sqlalchemy import create_engine, text
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string
from SDRUtils._swappulse_scripts import _tape_tables as tt
e = create_engine(get_db_connection_string())
q = text(f'''
SELECT as_of_date::text d, count(*) legs,
       round(100.0*count(ptp_group_id)/nullif(count(*),0),1)         ptp,
       round(100.0*count(special_tenor_type)/nullif(count(*),0),1)   spec,
       round(100.0*count(event_timestamp)/nullif(count(*),0),1)      evt,
       round(100.0*count(matched_ust_maturity)/nullif(count(*),0),1) ust,
       round(100.0*count(risk)/nullif(count(*),0),1)                 risk
FROM {tt.LEGS_TABLE} GROUP BY 1 ORDER BY 1''')
with e.connect() as c:
    for r in c.execute(q):
        print(r)
")
```

Expected, for all three days: `spec`, `evt`, `ust` at ~100%; `ptp` materially above 0; `risk` at ~100%.

**Decision gate.** If 2024-03-04 shows NULL risk or fails on a missing curve, the ERIS curve history does not reach 2024-03. Do **not** work around it by publishing NULL risk. Determine the earliest date with curve coverage, shorten the backfill range to that date, record the shortened range and the reason in the ledger, and report it before continuing.

- [ ] **Step 5: Extrapolate and record the go/no-go**

Multiply the median pilot day by 611 and record the projection. Write the ledger entry and commit.

```bash
git -C C:/Users/chris/clee/ARBS-v3 add docs/superpowers/plans/2026-08-08-tape-v3-backfill-ledger.md
git -C C:/Users/chris/clee/ARBS-v3 commit -m "docs(tape): record the v3 backfill pilot and frozen SHA"
```

---

### Task 6: Resumable backfill runner

**Files:**
- Create: `scripts/tape_v3_backfill.py`
- Test: `tests/test_tape_v3_backfill_runner.py`

**Interfaces:**
- Consumes: `run_usdswaps_pipeline` as a subprocess.
- Produces: `scripts/tape_v3_backfill.py` with `trading_days(start: date, end: date) -> list[date]` (descending) and `load_ledger(path: Path) -> dict[str, str]` mapping `"YYYY-MM-DD"` → status string. CLI: `--start`, `--end`, `--ledger`, `--cache-path`, `--retry-failed`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tape_v3_backfill_runner.py`:

```python
from __future__ import annotations

import datetime as dt
import json

from scripts.tape_v3_backfill import load_ledger, trading_days


def test_trading_days_are_descending_and_exclude_weekends():
    days = trading_days(dt.date(2026, 8, 3), dt.date(2026, 8, 7))
    assert days == [
        dt.date(2026, 8, 7), dt.date(2026, 8, 6), dt.date(2026, 8, 5),
        dt.date(2026, 8, 4), dt.date(2026, 8, 3),
    ]


def test_trading_days_skips_a_weekend():
    days = trading_days(dt.date(2026, 8, 7), dt.date(2026, 8, 10))
    assert dt.date(2026, 8, 8) not in days   # Saturday
    assert dt.date(2026, 8, 9) not in days   # Sunday


def test_load_ledger_returns_empty_for_missing_file(tmp_path):
    assert load_ledger(tmp_path / "nope.jsonl") == {}


def test_load_ledger_keeps_the_last_status_per_day(tmp_path):
    fp = tmp_path / "ledger.jsonl"
    fp.write_text(
        json.dumps({"date": "2026-08-07", "status": "failed"}) + "\n"
        + json.dumps({"date": "2026-08-07", "status": "ok"}) + "\n",
        encoding="utf-8",
    )
    assert load_ledger(fp) == {"2026-08-07": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_tape_v3_backfill_runner.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.tape_v3_backfill'`

- [ ] **Step 3: Write the runner**

Create `scripts/tape_v3_backfill.py`:

```python
"""Resumable, ledger-first backfill of the ARBS v3 tape.

Runs newest-first so the front end becomes correct within the first hour
rather than the last. Safe to order descending: cross-day enrichment
resolves from raw DTCC data fetched one day *forward*, never from earlier
tape days in the database, so no day depends on one not yet written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

PYTHON = r"C:\Users\chris\anaconda3\envs\stir\python.exe"
DEFAULT_CACHE = r"C:\Users\chris\clee\ARBS\sdr_cache"


def trading_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """US business days in [start, end], newest first."""
    idx = pd.date_range(
        start=start, end=end,
        freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()),
    )
    return sorted((d.date() for d in idx), reverse=True)


def load_ledger(path: Path) -> dict[str, str]:
    """Map date -> last recorded status. Missing file means nothing done."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        out[rec["date"]] = rec["status"]
    return out


def _append(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--ledger", default="tape_v3_backfill_ledger.jsonl")
    ap.add_argument("--cache-path", default=DEFAULT_CACHE)
    ap.add_argument("--retry-failed", action="store_true",
                    help="Second pass: run only the days marked failed.")
    args = ap.parse_args()

    ledger = Path(args.ledger)
    done = load_ledger(ledger)
    days = trading_days(
        dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    )

    if args.retry_failed:
        todo = [d for d in days if done.get(d.isoformat()) == "failed"]
    else:
        todo = [d for d in days if done.get(d.isoformat()) != "ok"]

    print(f"{len(todo)} day(s) to run of {len(days)} in range "
          f"({len(days) - len(todo)} already ok)")

    for i, d in enumerate(todo, 1):
        iso = d.isoformat()
        print(f"[{i}/{len(todo)}] {iso}", flush=True)
        t0 = time.time()
        proc = subprocess.run(
            [PYTHON, "-m", "SDRUtils._swappulse_scripts.run_usdswaps_pipeline",
             "backfill", "--date", iso, "--cache-path", args.cache_path],
            capture_output=True, text=True,
        )
        elapsed = round(time.time() - t0, 1)
        ok = proc.returncode == 0
        _append(ledger, {
            "date": iso,
            "status": "ok" if ok else "failed",
            "seconds": elapsed,
            "returncode": proc.returncode,
            "tail": proc.stderr.strip()[-400:] if not ok else "",
        })
        print(f"    {'ok' if ok else 'FAILED'} in {elapsed}s", flush=True)

    failed = [d for d, s in load_ledger(ledger).items() if s == "failed"]
    if failed:
        print(f"\n{len(failed)} day(s) failed: {sorted(failed)[:20]}")
        return 1
    print("\nall days ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_tape_v3_backfill_runner.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-v3 add scripts/tape_v3_backfill.py tests/test_tape_v3_backfill_runner.py
git -C C:/Users/chris/clee/ARBS-v3 commit -m "feat(tape): add the resumable v3 backfill runner

Ledger-first and newest-first: the front end becomes correct within the
first hour rather than the last. Descending order is safe because
cross-day enrichment resolves from raw DTCC data fetched one day forward,
never from earlier tape days in the DB, so no day depends on one not yet
written. A failed day records its status and does not stop the run."
```

---

### Task 7: Dashboard generation seam

**Files:**
- Create: `SDRUtils/dashboard/src/lib/tape-tables.ts`
- Modify: 43 files containing 92 table-name literals (see spec §2)
- Test: `SDRUtils/dashboard/src/lib/__tests__/tape-tables.test.ts`

**Interfaces:**
- Consumes: nothing from Python — the TS constant is deliberately independent.
- Produces: `src/lib/tape-tables.ts` exporting `TAPE_GENERATION`, `TAPE_LEGS`, `TAPE_PACKAGES`, `TAPE_DISPLAY`, `TAPE_OVERRIDES`, `TAPE_OVERRIDE_MEMBERS`, `TAPE_OVERRIDE_HISTORY`, `TAPE_NOTES`, `TAPE_SIGNAL`, `MANUAL_LINKS` — all `string`.

- [ ] **Step 1: Write the failing test**

Create `SDRUtils/dashboard/src/lib/__tests__/tape-tables.test.ts`:

```typescript
import {
  MANUAL_LINKS,
  TAPE_DISPLAY,
  TAPE_GENERATION,
  TAPE_LEGS,
  TAPE_PACKAGES,
} from '../tape-tables'

describe('tape table generation seam', () => {
  it('is pinned to v3', () => {
    expect(TAPE_GENERATION).toBe('v3')
  })

  it('derives table names from the generation', () => {
    expect(TAPE_LEGS).toBe('arbs_usd_swap_tape_legs_v3')
    expect(TAPE_PACKAGES).toBe('arbs_usd_swap_tape_packages_v3')
    expect(TAPE_DISPLAY).toBe('arbs_usd_swap_tape_display_v3')
  })

  it('leaves manual links unversioned', () => {
    expect(MANUAL_LINKS).toBe('arbs_usd_swap_manual_links_v2')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/chris/clee/ARBS-v3/SDRUtils/dashboard && npm test -- tape-tables
```

Expected: FAIL — cannot resolve `../tape-tables`.

- [ ] **Step 3: Write the seam**

Create `SDRUtils/dashboard/src/lib/tape-tables.ts`:

```typescript
// ABOUTME: Single source of truth for which tape generation the dashboard reads.
// The _v2 tape is written by the `run_swaptape` cron job on the host `sky` and
// serves a different front end. ARBS owns _v3.
//
// This constant is deliberately independent of the Python writer's
// TAPE_GENERATION, and deliberately a constant rather than an env var:
// pointing the reader back at v2 to inspect what sky produces must never
// resurrect ARBS *writes* to v2, and a missing env var must never silently
// select the wrong generation.

export const TAPE_GENERATION = 'v3'

const t = (base: string) => `arbs_usd_swap_${base}_${TAPE_GENERATION}`

export const TAPE_PACKAGES = t('tape_packages')
export const TAPE_LEGS = t('tape_legs')
export const TAPE_DISPLAY = t('tape_display')
export const TAPE_OVERRIDES = t('tape_overrides')
export const TAPE_OVERRIDE_MEMBERS = t('tape_override_members')
export const TAPE_OVERRIDE_HISTORY = t('tape_override_history')
export const TAPE_NOTES = t('tape_notes')
export const TAPE_SIGNAL = t('tape_signal')

// Not versioned: keyed by its own UUID, shared with the classification stage.
export const MANUAL_LINKS = 'arbs_usd_swap_manual_links_v2'
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:/Users/chris/clee/ARBS-v3/SDRUtils/dashboard && npm test -- tape-tables
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Replace the 92 literals**

Enumerate them first:

```bash
cd C:/Users/chris/clee/ARBS-v3/SDRUtils/dashboard
grep -rn "arbs_usd_swap_tape_[a-z_]*_v[12]" src/ | tee /tmp/tape-refs.txt | wc -l
```

Replace each with an import from `@/lib/tape-tables`, **including test files** — a test pinning `_v2` keeps passing while production is broken. In `src/app/api/usd-swaps-tape-v2/route.logic.ts`, keep `TAPE_DISPLAY_VIEW` as a re-export:

```typescript
import { TAPE_DISPLAY } from '@/lib/tape-tables'
export const TAPE_DISPLAY_VIEW = TAPE_DISPLAY
```

**Handle the two `_v1` references deliberately, not mechanically:**
`src/features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts:76` and
`src/app/api/usd-swaps-tape-v2/packages/route.logic.ts:15` both name
`arbs_usd_swap_tape_packages_v1`. A blanket replace changes their behaviour from "read the frozen v1 rollback table" to "read v3". Read each call site, decide on purpose, and note the decision in the commit message. (Most likely both are stale and should move to v3 — but confirm.)

- [ ] **Step 6: Verify no literals remain**

```bash
cd C:/Users/chris/clee/ARBS-v3/SDRUtils/dashboard
grep -rn "arbs_usd_swap_tape_[a-z_]*_v[12]" src/ | grep -v 'lib/tape-tables.ts'
```

Expected: no output.

- [ ] **Step 7: Run the full dashboard suite and typecheck**

```bash
cd C:/Users/chris/clee/ARBS-v3/SDRUtils/dashboard && npm test
cd C:/Users/chris/clee/ARBS-v3/SDRUtils/dashboard && npx tsc --noEmit
```

Expected: both green. Use `npm test` — never `npx jest`.

- [ ] **Step 8: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-v3 add -A SDRUtils/dashboard/src
git -C C:/Users/chris/clee/ARBS-v3 commit -m "feat(dashboard): read the tape generation from a single constant

Replaces 92 hardcoded table names across 43 files, tests included -- a
test pinning _v2 would keep passing while production was broken. The TS
constant is deliberately independent of the Python writer's, so pointing
the reader back at v2 to inspect sky's data cannot resurrect ARBS writes
to it."
```

---

### Task 8: Bulk backfill and acceptance

**Files:**
- Modify: `docs/superpowers/plans/2026-08-08-tape-v3-backfill-ledger.md`
- Create: `scripts/tape_v3_acceptance.py`

**Interfaces:**
- Consumes: everything above; `backfill_start` recorded in Task 5.
- Produces: a populated v3 tape and a passing acceptance report.

- [ ] **Step 1: Launch the bulk backfill in the background**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe scripts/tape_v3_backfill.py \
  --start 2024-03-01 --end 2026-08-07 \
  --ledger docs/superpowers/plans/tape_v3_backfill_ledger.jsonl \
  --cache-path C:/Users/chris/clee/ARBS/sdr_cache
```

Run it in the background. **Check progress by process, not by log tail** — redirected stdout is block-buffered while stderr is not, so a log frozen at a traceback usually means the process is alive with output still in the buffer:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Select-Object ProcessId, @{n='MB';e={[int]($_.WorkingSetSize/1MB)}}, CommandLine
```

Progress is the ledger's line count, not the console.

- [ ] **Step 2: Second pass over failures**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe scripts/tape_v3_backfill.py \
  --start 2024-03-01 --end 2026-08-07 \
  --ledger docs/superpowers/plans/tape_v3_backfill_ledger.jsonl \
  --cache-path C:/Users/chris/clee/ARBS/sdr_cache --retry-failed
```

- [ ] **Step 3: Write the acceptance checker**

Create `scripts/tape_v3_acceptance.py`:

```python
"""Acceptance criteria for the v3 tape backfill (spec section 8)."""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string

CUTOFF = "2026-08-07"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-start", required=True,
                    help="UTC ISO timestamp recorded before the backfill began.")
    args = ap.parse_args()

    engine = create_engine(get_db_connection_string())
    failures: list[str] = []

    with engine.connect() as c:
        # 1. Day-set parity, pinned to the cutoff. v2 is NOT frozen -- sky
        #    keeps writing it, so an unrestricted comparison fails as soon
        #    as sky publishes a day after the backfill started.
        v3_days = {r[0] for r in c.execute(text(
            f"SELECT DISTINCT as_of_date FROM {tt.LEGS_TABLE} WHERE as_of_date <= :cut"
        ), {"cut": CUTOFF})}
        v2_days = {r[0] for r in c.execute(text(
            "SELECT DISTINCT as_of_date FROM arbs_usd_swap_tape_legs_v2 "
            "WHERE as_of_date <= :cut"
        ), {"cut": CUTOFF})}
        print(f"1. days: v3={len(v3_days)} v2={len(v2_days)}")
        if v2_days - v3_days:
            failures.append(f"missing from v3: {sorted(v2_days - v3_days)[:20]}")

        # 2. Enrichment markers.
        overall = c.execute(text(
            f"SELECT round(100.0*count(ptp_group_id)/nullif(count(*),0),2) "
            f"FROM {tt.LEGS_TABLE} WHERE as_of_date <= :cut"
        ), {"cut": CUTOFF}).scalar_one()
        print(f"2a. corpus ptp_group_id fill: {overall}%")
        if overall is None or float(overall) < 50.0:
            failures.append(f"corpus ptp fill {overall}% < 50%")

        bad = c.execute(text(f"""
            SELECT as_of_date::text, count(*) n,
                   round(100.0*count(ptp_group_id)/nullif(count(*),0),1)         ptp,
                   round(100.0*count(special_tenor_type)/nullif(count(*),0),1)   spec,
                   round(100.0*count(event_timestamp)/nullif(count(*),0),1)      evt,
                   round(100.0*count(matched_ust_maturity)/nullif(count(*),0),1) ust
            FROM {tt.LEGS_TABLE} WHERE as_of_date <= :cut
            GROUP BY 1
            HAVING round(100.0*count(ptp_group_id)/nullif(count(*),0),1) = 0
                OR round(100.0*count(special_tenor_type)/nullif(count(*),0),1) < 99
                OR round(100.0*count(event_timestamp)/nullif(count(*),0),1) < 99
                OR round(100.0*count(matched_ust_maturity)/nullif(count(*),0),1) < 99
            ORDER BY 1
        """), {"cut": CUTOFF}).fetchall()
        print(f"2b. days below threshold: {len(bad)}")
        if bad:
            failures.append(f"{len(bad)} day(s) below marker thresholds, e.g. {bad[:5]}")

        # 3. The 2026-07-24 hole sky left ~80% short.
        n0724 = c.execute(text(
            f"SELECT count(*) FROM {tt.LEGS_TABLE} WHERE as_of_date = DATE '2026-07-24'"
        ), ).scalar_one()
        print(f"3. as_of 2026-07-24 legs: {n0724}")
        if n0724 < 2000:
            failures.append(f"2026-07-24 still short: {n0724} legs")

        # 4. v2 non-interference. v2 changes legitimately during the run;
        #    what must hold is that every row written since backfill_start
        #    came from sky.
        for tbl in ("arbs_usd_swap_tape_legs_v2", "arbs_usd_swap_tape_packages_v2"):
            n = c.execute(text(
                f"SELECT count(*) FROM {tbl} WHERE created_at > :t0 "
                "AND producer IS DISTINCT FROM 'swappulse_port'"
            ), {"t0": args.backfill_start}).scalar_one()
            print(f"4. {tbl}: {n} non-sky rows since backfill_start")
            if n:
                failures.append(f"{tbl}: ARBS wrote {n} rows to v2")

    if failures:
        print("\nACCEPTANCE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nACCEPTANCE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run acceptance**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe scripts/tape_v3_acceptance.py \
  --backfill-start "<the UTC timestamp recorded in Task 5 Step 2>"
```

Expected: `ACCEPTANCE OK`, exit 0.

- [ ] **Step 5: Re-run the parity check**

```bash
cd C:/Users/chris/clee/ARBS-v3 && ARBS_SUPABASE_ENABLED=0 \
  C:/Users/chris/anaconda3/envs/stir/python.exe scripts/tape_v3_parity_check.py
```

Expected: `PARITY OK` with non-zero index counts.

- [ ] **Step 6: Verify the dashboard in Chrome**

```bash
cd C:/Users/chris/clee/ARBS-v3/SDRUtils/dashboard && npm install --legacy-peer-deps && npm run dev
```

Open the tape view in Chrome MCP and confirm rows render, package grouping appears (PTP-grouped packages with more than 3 legs, absent from v2 since 2026-07-23), and the report-lag column is populated. Screenshot for the record.

- [ ] **Step 7: Commit and open the PR**

```bash
git -C C:/Users/chris/clee/ARBS-v3 add -A docs/ scripts/
git -C C:/Users/chris/clee/ARBS-v3 commit -m "feat(tape): backfill v3 across 611 days and record acceptance

Acceptance pins the day-set comparison to as_of <= 2026-08-07 because v2
is not frozen -- sky keeps writing it throughout a multi-hour backfill --
and proves non-interference by asserting zero rows written to v2 since
backfill_start carry a producer other than swappulse_port."
git -C C:/Users/chris/clee/ARBS-v3 push -u origin feat/tape-v3-generation
```

---

## Post-merge follow-ups (not in scope)

- Ongoing v3 freshness — a scheduled task or service loop. Until this exists, v3 goes stale the day after the backfill.
- Coordinate with the `sky` owner on whether `run_swaptape` should also adopt the current logic, or whether the two generations diverge permanently by design.
