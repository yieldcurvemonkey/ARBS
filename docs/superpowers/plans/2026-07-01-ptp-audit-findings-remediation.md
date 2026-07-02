# PTP Audit Findings Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out every open finding from `docs/superpowers/audits/2026-07-01-ptp-package-detection-audit.md` — PTP feature polish (Phase A) and repo-wide test-suite health to a green gate (Phase B).

**Architecture:** Phase A hardens the shipped PTP feature: true-bp spread units, price-notation persistence + UI tag, null-OPA sign hygiene, sub-fly annotation polish, incremental-hood group integrity, and two structural preventions in the dashboard data path (auto-projection, global NUMERIC parsing). It ends with a cache-version bump, re-backfill, and row-level + browser verification. Phase B independently takes `pytest tests/` from "7 collection errors + 111 failures + 1.5h" to a green, marker-partitioned suite, and clears the dashboard jest/tsc debt.

**Tech Stack:** Python 3.11 / pandas / numpy / SQLAlchemy / psycopg2 (backend), TypeScript / Next.js / PrimeReact / jest (dashboard), PostgreSQL (Supabase).

## Global Constraints

- All Python/pytest commands run as `conda run -n stir python -m pytest …` from the repo root (per repo memory + CLAUDE.md).
- The tape DB is **remote Supabase prod**. `run_usdswaps_pipeline backfill --date D` deletes and rewrites that date. Only Task 9 runs backfills, deliberately.
- Any change to detector *output* (columns or values) must bump all three cache knobs together: classification `cache_flags` suffix, warm pickle filename, `TRADE_TAPE_CACHE_VERSION` (Task 9 does this once for all of Phase A).
- Dashboard changes must be verified in Chrome (MCP) against `npm run dev` on localhost:3000 **before** committing (user rule).
- Dashboard reads only `arbs_usd_swap_tape_display_v2` via `resolveDisplayView`; never point anything at `_v1` objects.
- Package-detection interface contract: `package_type`, `package_id`, `package_legs` columns feed `_enrich_packages()`; do not rename them.
- Commit after every task; conventional-commit subjects; end commit messages with the Claude Code trailer used throughout this repo's recent history.
- pandas is 2.3.1; `df.get(col)` returns **None** (not an empty Series) when `col` is absent — every fix in this plan that touches `df.get` must pass an explicit Series default.

## Findings coverage map

| Audit finding | Disposition | Task |
|---|---|---|
| `dealer_spread_bps` is bp×100 | Fix to true bp (user decision) | 1 |
| Price-notation mega-groups (PKG-107 blobs) | Keep grouping; persist notation + UI tag (user decision) | 4 |
| Null-OPA legs get `opa_sign` ±1 / signed 0 | Leave sign NULL where OPA is null | 5 |
| `_detect_sub_flies` raw-vs-rounded distinct-tenor check | Use rounded buckets consistently | 6 |
| Sub-fly pairing can cross-pair rates on DV01 ties | Stable (pv01, rate) sort | 6 |
| Incremental hood can split a straddling PTP group | Key-aware hood expansion | 7 |
| `resolveDisplayView` hard-coded COLUMNS caused C1 | Invert to exclusion-list auto-projection | 2 |
| pg NUMERIC-as-string caused C2 + lexicographic sort | Global NUMERIC type parser in db client | 3 |
| Three hand-maintained cache knobs (C4 class) | Single `DETECTION_CACHE_VERSION` constant + CLAUDE.md rule | 8, 9 |
| Spec drift (notation gating, comma parsing, units) | Update design spec + CLAUDE.md; track spec/plan docs in git | 8 |
| PTP groups bypass invoice/MMS/MAC/spreadover | **Accepted** — spec intent; documented in spec (Task 8), no code change |
| Row order / index reset out of `_run_all_detectors` | **Accepted** — nothing downstream is positional; no action |
| `ensure_schema` deadlock retries | **Accepted** — worked as designed during audit; no action |
| 7 orphaned test files break `pytest tests/` collection | Delete | 10 |
| `df.get(None)` scalar crashes (spreadover/MMS/tape/quality, ~25 tests) | Guard with Series defaults | 11 |
| NOVA-IN/NOVA-OUT/EXER/CLRG + lifecycle label asserts stale (tape_tags refactor) | Update tests to tags convention | 12 |
| Swaption cluster (34): renamed kwargs, removed class, fixture cols | Update tests to current API | 13 |
| Barchart/MDP/mocks (~20): `bulk_get_data` mock drift, read-only arrays, token cache | Diagnose→fix per cluster | 14 |
| Misc (~15): `15y_10y` grid, SABR fixture, live-atmf, supabase sync, date asserts | Diagnose→fix per file | 15 |
| Suite 1.5h, unregistered `slow` marker | Register markers, mark offenders, document fast gate | 16 |
| Jest: rowClassName palette, TapeLabelCell UFRO, VolumeGrid, route.cache live-DB | Fix expectations / mock DB | 17 |
| tsc: 52 error lines in test files | Fix fixtures/types to `tsc --noEmit` clean | 18 |
| Full-suite green gate | Final verification run | 19 |

---

# Phase A — PTP feature polish

### Task 1: `dealer_spread_bps` → true basis points

**Files:**
- Modify: `SDRUtils/packages/opa_sign_solver.py` (in `solve_all_opa_signs`, the `spread_bps` expression)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx` (`spreadBpsDisplay`)
- Test: `tests/test_opa_sign_solver.py`

**Interfaces:**
- Consumes: existing `solve_all_opa_signs(df, ...)` batch API (unchanged signature).
- Produces: `dealer_spread_bps` column now equals `residual / total_dv01` (true bp). Task 9's verification numbers depend on this: 12-leg fly ≈ 0.000269 bp, 8-leg MAC ≈ 0.2012 bp.

- [ ] **Step 1: Write the failing test**

Append to `TestSolveOpaSigns` in `tests/test_opa_sign_solver.py`:

```python
    def test_dealer_spread_bps_is_true_basis_points(self):
        """residual($) / total_dv01($/bp) is already bp — no ×100.
        Audit finding: shipped value was bp×100 (a % of DV01)."""
        import pandas as pd

        from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

        df = pd.DataFrame({
            "trade_id": ["A", "B"],
            "ptp_group_id": ["G", "G"],
            "other_payment_amount": [600.0, 500.0],
            "package_transaction_price": [90.0, 90.0],
            "package_transaction_price_notation": [1.0, 1.0],
            "fixed_rate": [0.04, 0.04],
            "tenor_years": [2.0, 10.0],
            "estimated_pv01": [40.0, 60.0],
        })
        out = solve_all_opa_signs(df)
        # best net = ±100, residual = 10; total_dv01 = 100 → 0.1 bp
        assert abs(out["dealer_spread_bps"].iloc[0] - 0.1) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_opa_sign_solver.py::TestSolveOpaSigns::test_dealer_spread_bps_is_true_basis_points -v`
Expected: FAIL with `assert abs(10.0 - 0.1) < 1e-9` (current value is 10.0 = 0.1 × 100).

- [ ] **Step 3: Fix the solver**

In `SDRUtils/packages/opa_sign_solver.py`, `solve_all_opa_signs`, replace:

```python
        spread_bps = (
            (result["residual"] / total_dv01 * 100)
            if total_dv01 > 0 else None
        )
```

with:

```python
        # residual is $, total_dv01 is $/bp — the ratio is already basis
        # points. The spec's original ×100 made this a % of DV01 while
        # labeling it bp (2026-07-01 audit finding, PM decided: true bp).
        spread_bps = (
            (result["residual"] / total_dv01)
            if total_dv01 > 0 else None
        )
```

- [ ] **Step 4: Run the solver test file**

Run: `conda run -n stir python -m pytest tests/test_opa_sign_solver.py -v`
Expected: all PASS (no other test asserts spread scale).

- [ ] **Step 5: Fix the display precision for sub-0.01bp values**

In `columns.tsx`, replace the `spreadBpsDisplay` helper body:

```tsx
// pg returns NUMERIC columns as strings; coerce like the format helpers do
// instead of trusting the row type's `number | null`. True-bp values can be
// tiny (a near-exact tieout is ~0.0003bp) — show 4 decimals below 0.01bp.
function spreadBpsDisplay(v: number | string | null | undefined): string | null {
  if (v == null) return null
  const n = Number(v)
  if (!Number.isFinite(n)) return null
  const digits = Math.abs(n) >= 0.01 ? 2 : 4
  return `${n.toFixed(digits)}bp`
}
```

- [ ] **Step 6: Verify in Chrome (values still ×100 in DB until Task 9 — check formatting only)**

Run `npm run dev` in `SDRUtils/dashboard` if not running; open
`http://localhost:3000/usd-swaps`, confirm Spread column renders without
errors. (Semantics verified after Task 9's re-backfill.)

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/packages/opa_sign_solver.py tests/test_opa_sign_solver.py SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx
git commit -m "fix(packages): dealer_spread_bps is true basis points, not bp*100"
```

---

### Task 2: Dashboard column auto-projection (prevention for audit C1)

**Files:**
- Modify: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts`
- Test: `SDRUtils/dashboard/src/lib/__tests__/usd-swaps-tape-v2.test.ts` (create)

**Interfaces:**
- Consumes: `query()` from `@/lib/db`, `TAPE_DISPLAY_VIEW`.
- Produces: `resolveDisplayView(): Promise<{view, columns}>` (same signature) — but new view columns are now **included by default**; only names in the exported `EXCLUDED_VIEW_COLUMNS` set are dropped. Task 4 relies on this (its new column needs no registration).

- [ ] **Step 1: Enumerate the current implicit exclusions**

Run against the live view (this seeds the exclusion set — the goal is a
no-op payload change today):

```bash
conda run -n stir python - <<'EOF'
import os
for line in open("SDRUtils/dashboard/.env"):
    if line.startswith("DATABASE_URL="):
        os.environ.setdefault("DATABASE_URL", line.strip().split("=",1)[1])
from sqlalchemy import text
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import create_engine, resolve_pg_url
eng = create_engine(resolve_pg_url(None))
with eng.connect() as c:
    cols = [r[0] for r in c.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='arbs_usd_swap_tape_display_v2' AND table_schema=current_schema()"))]
print(sorted(cols))
EOF
```

Diff that list against the `COLUMNS` array in `usd-swaps-tape-v2.ts`. As of
the audit the difference is: `is_off_market_any`, `confidence_score`,
`confidence_total`, `confidence_tone`, `confidence_signals`, `summary_rate`,
`summary_risk`, `summary_opa`, `is_ccp_switch`, `ccp_switch_from`,
`ccp_switch_to`, `package_adjusted_dv01`, `normalized_tape_label`,
`tape_tags` — confirm against the live output and use whatever the diff
actually is.

- [ ] **Step 2: Write the failing test**

Create `SDRUtils/dashboard/src/lib/__tests__/usd-swaps-tape-v2.test.ts`:

```ts
import { EXCLUDED_VIEW_COLUMNS, __projectColumns } from '../usd-swaps-tape-v2'

describe('display view projection', () => {
  it('includes unknown new columns by default (audit C1 prevention)', () => {
    const viewCols = ['package_id', 'brand_new_column', 'confidence_score']
    const projected = __projectColumns(viewCols)
    expect(projected).toContain('d.brand_new_column')
    expect(projected).toContain('d.package_id')
  })

  it('drops only explicitly excluded columns', () => {
    const projected = __projectColumns(['package_id', 'confidence_score'])
    expect(projected).not.toContain('d.confidence_score')
    expect(EXCLUDED_VIEW_COLUMNS.has('confidence_score')).toBe(true)
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `SDRUtils/dashboard`):
`node --experimental-vm-modules node_modules/jest/bin/jest.js --testPathPatterns="lib/__tests__/usd-swaps-tape-v2"`
Expected: FAIL — `__projectColumns` is not exported.

- [ ] **Step 4: Implement exclusion-list projection**

In `usd-swaps-tape-v2.ts`, replace the `COLUMNS` allowlist + `projected`
computation with:

```ts
// Audit C1 prevention: the old hard-coded COLUMNS allowlist silently
// dropped every new view column (the whole PTP feature shipped invisible).
// Project ALL view columns except explicit exclusions, so the failure mode
// of forgetting registration becomes harmless over-inclusion. Excluded
// columns are ones the client derives itself or never reads.
export const EXCLUDED_VIEW_COLUMNS = new Set<string>([
  // seed from Step 1's live diff — keep this comment-annotated:
  'is_off_market_any',
  'confidence_score',
  'confidence_total',
  'confidence_tone',
  'confidence_signals',
  'summary_rate',
  'summary_risk',
  'summary_opa',
  'is_ccp_switch',
  'ccp_switch_from',
  'ccp_switch_to',
  'package_adjusted_dv01',
  'normalized_tape_label',
  'tape_tags',
])

/** Test-only pure helper. */
export function __projectColumns(viewColumns: string[]): string[] {
  return viewColumns
    .filter((c) => !EXCLUDED_VIEW_COLUMNS.has(c))
    .map((c) => `d.${c}`)
}
```

and inside `resolveDisplayView()` replace the `COLUMNS.filter(...)` block
with:

```ts
  const projected = __projectColumns(present.rows.map((r) => r.column_name))
```

Delete the now-unused `COLUMNS` constant.

- [ ] **Step 5: Run tests**

Run: `node --experimental-vm-modules node_modules/jest/bin/jest.js --testPathPatterns="lib/__tests__/usd-swaps-tape-v2"`
Expected: new tests PASS.

- [ ] **Step 6: Verify in Chrome**

With `npm run dev` running, hard-reload `http://localhost:3000/usd-swaps`,
confirm: tape renders, PTP badges still show, no console errors, and the
network response for `/api/usd-swaps-tape-v2` has the same fields as before
plus none of the excluded ones.

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts SDRUtils/dashboard/src/lib/__tests__/usd-swaps-tape-v2.test.ts
git commit -m "refactor(dashboard): auto-project display view columns minus exclusion list (audit C1 prevention)"
```

---

### Task 3: Global pg NUMERIC parser (prevention for audit C2 / sort bug)

**Files:**
- Modify: `SDRUtils/dashboard/src/lib/db.ts` (locate with `grep -n "Pool\|pg" SDRUtils/dashboard/src/lib/db.ts`)
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts` (remove the local coercion loop added by audit commit `9d0053b6`)
- Test: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/` (existing suites must stay green)

**Interfaces:**
- Consumes: `pg` module in `lib/db.ts`.
- Produces: every `query()` result returns NUMERIC (OID 1700), INT8 (OID 20) as JS numbers repo-wide. `route.ts` no longer needs field-by-field coercion.

- [ ] **Step 1: Risk sweep — find consumers that rely on numeric-strings**

```bash
grep -rn "Number(" SDRUtils/dashboard/src/app/api --include=*.ts | wc -l
grep -rn "parseFloat\|parseInt" SDRUtils/dashboard/src/app/api --include=*.ts | head -20
```

`Number()`/`parseFloat` on an already-number value is a no-op — those are
safe. Manually check any hit that does **string ops** on a numeric field
(`.replace`, `.split`, template keys). Expected from the audit: none, but
record findings in the commit message.

- [ ] **Step 2: Add the type parsers**

In `SDRUtils/dashboard/src/lib/db.ts`, immediately after the `pg` import:

```ts
import pg from 'pg'

// pg returns NUMERIC (1700) and BIGINT (20) as strings by default. Every
// consumer in this app treats them as numbers (formatters wrap Number(),
// the tape table sorts on them — audit 2026-07-01 found lexicographic
// spread sorting). Values are money/risk quantities well inside 2^53.
pg.types.setTypeParser(1700, (v: string) => (v === null ? null : parseFloat(v)))
pg.types.setTypeParser(20, (v: string) => (v === null ? null : parseInt(v, 10)))
```

(Adapt import style to what `db.ts` actually uses — `import { Pool, types }
from 'pg'` → `types.setTypeParser(...)`.)

- [ ] **Step 3: Remove the route-local coercion**

In `route.ts`, delete the `for (const r of rows …) { for (const k of
['ptp_group_size', …]) … }` block added by audit commit `9d0053b6` and its
comment (the global parser now covers it).

- [ ] **Step 4: Run the dashboard test suites for the tape API**

Run: `node --experimental-vm-modules node_modules/jest/bin/jest.js --testPathPatterns="usd-swaps-tape-v2"`
Expected: no NEW failures vs the Task-17 baseline (pre-existing failures are
fixed in Phase B; compare failure lists).

- [ ] **Step 5: Verify in Chrome**

Reload the tape: Spread column sorts numerically (sort URL:
`?sort_field=dealer_spread_bps&sort_order=-1` with a `6/25` date filter),
Reported LvL / Risk / notional columns unchanged, volume grid unchanged, no
console errors.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/lib/db.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts
git commit -m "fix(dashboard): parse pg NUMERIC/BIGINT as numbers globally (audit C2 prevention)"
```

---

### Task 4: Persist PTP price notation + tag mega-groups in the UI

**Files:**
- Modify: `SDRUtils/packages/opa_sign_solver.py` (`solve_all_opa_signs` — set `ptp_price_notation` per group)
- Modify: `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` (packages ALTER + display view SELECT)
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` (`PACKAGE_COLUMNS`, `build_package_rows`, `_LATEST_MIGRATION_COLS`)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/trade.types.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx` (OPA Conf column body)
- Test: `tests/test_opa_sign_solver.py`

**Interfaces:**
- Consumes: `numeric_like` from `SDRUtils.packages.ptp_grouper`; Task 2's auto-projection (no dashboard column registration needed).
- Produces: `ptp_price_notation` SMALLINT on `arbs_usd_swap_tape_packages_v2` + display view; `UsdSwapTapeRow.ptp_price_notation?: number | null`. Value: Part 43 notation of the group's PTP (1 = monetary, 3 = decimal price), NULL for non-PTP packages.

- [ ] **Step 1: Write the failing test**

Append to `TestSolveOpaSigns`:

```python
    def test_ptp_price_notation_persisted_per_group(self):
        import pandas as pd

        from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

        df = pd.DataFrame({
            "trade_id": ["A", "B", "C"],
            "ptp_group_id": ["G", "G", None],
            "other_payment_amount": [None, None, None],
            "package_transaction_price": ["9.9999999999", "9.9999999999", None],
            "package_transaction_price_notation": [3.0, 3.0, None],
            "fixed_rate": [0.04, 0.04, 0.04],
            "tenor_years": [2.0, 10.0, 5.0],
            "estimated_pv01": [100.0, 100.0, 100.0],
        })
        out = solve_all_opa_signs(df)
        grp = out[out["ptp_group_id"] == "G"]
        assert (grp["ptp_price_notation"] == 3).all()
        assert out[out["ptp_group_id"].isna()]["ptp_price_notation"].isna().all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_opa_sign_solver.py::TestSolveOpaSigns::test_ptp_price_notation_persisted_per_group -v`
Expected: FAIL with `KeyError: 'ptp_price_notation'`.

- [ ] **Step 3: Implement in the solver**

In `solve_all_opa_signs`: add `"ptp_price_notation"` to the init loop's
column list (`out[col] = None`), and restructure the notation gate so the
value persists for every PTP group (monetary or not):

```python
        notation_val = None
        if ptp_notation_col in grp.columns:
            notation = numeric_like(grp[ptp_notation_col])
            if notation.notna().any():
                notation_val = int(notation.dropna().iloc[0])
        mask = out[ptp_group_col] == gid
        out.loc[mask, "ptp_price_notation"] = notation_val
        if notation_val is not None and notation_val != 1:
            # Non-monetary PTP: no meaningful dollar tieout.
            out.loc[mask, "opa_sign_confidence"] = "UNRESOLVED"
            continue
```

(This replaces the existing gate block, which computes `mask` later — move
the `mask` computation up and reuse it; do not compute it twice.)

- [ ] **Step 4: Run solver tests**

Run: `conda run -n stir python -m pytest tests/test_opa_sign_solver.py -v`
Expected: all PASS, including the notation-UNRESOLVED regression test.

- [ ] **Step 5: Schema + ingest wiring**

`_tape_schema_v2.py` — in the PTP/OPA packages ALTER block add:

```sql
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS ptp_price_notation SMALLINT;
```

and add `p.ptp_price_notation,` to the display-view SELECT next to
`p.ptp_group_size`.

`ingest_usdswaps_tape.py`:
- add `"ptp_price_notation",` to `PACKAGE_COLUMNS` (next to `ptp_group_size`)
- in `build_package_rows`, next to the other PTP aggregations:

```python
            "ptp_price_notation": _int_or_none(
                g["ptp_price_notation"].iloc[0] if "ptp_price_notation" in g.columns else None
            ),
```

- update the migration marker:

```python
_LATEST_MIGRATION_COLS = [
    ("arbs_usd_swap_tape_packages_v2", "ptp_price_notation"),
    ("arbs_usd_swap_tape_legs_v2", "opa_signed_amount"),
]
```

- [ ] **Step 6: Dashboard type + tag chip**

`trade.types.ts` — add to `UsdSwapTapeRow` next to the other PTP fields:

```ts
  ptp_price_notation?: number | null
```

`columns.tsx` — in the `opa_conf` Column body, render a PX chip beside the
badge when the group's PTP is non-monetary:

```tsx
      body={(row: UsdSwapTapeRow) => {
        const px =
          row.ptp_price_notation != null && Number(row.ptp_price_notation) !== 1
        if (!row.opa_sign_confidence && !px)
          return <span className="text-slate-600 text-[10px]">·</span>
        return (
          <span className="inline-flex items-center gap-1">
            {row.opa_sign_confidence && (
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${CONFIDENCE_COLORS[row.opa_sign_confidence] ?? 'bg-zinc-500/20 text-zinc-400'}`}
              >
                {row.opa_sign_confidence}
              </span>
            )}
            {px && (
              <span
                className="px-1 py-0.5 rounded text-[10px] font-semibold bg-zinc-500/20 text-zinc-400"
                title="Package transaction price is a decimal price (Part 43 notation != 1) — no dollar OPA tieout"
              >
                PX
              </span>
            )}
          </span>
        )
      }}
```

- [ ] **Step 7: Run migration against live DB**

```bash
conda run -n stir python - <<'EOF'
import os
for line in open("SDRUtils/dashboard/.env"):
    if line.startswith("DATABASE_URL="):
        os.environ.setdefault("DATABASE_URL", line.strip().split("=",1)[1])
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import create_engine, ensure_schema, resolve_pg_url
ensure_schema(create_engine(resolve_pg_url(None)))
print("migrated")
EOF
```

Expected: `migrated` (deadlock retries are normal). Verify:
`SELECT column_name FROM information_schema.columns WHERE table_name='arbs_usd_swap_tape_packages_v2' AND column_name='ptp_price_notation';` returns 1 row.

- [ ] **Step 8: Verify in Chrome** — column data arrives after Task 9's
re-backfill; for now confirm the tape renders with no console errors and the
OPA Conf column still shows badges.

- [ ] **Step 9: Commit**

```bash
git add SDRUtils/packages/opa_sign_solver.py tests/test_opa_sign_solver.py SDRUtils/_swappulse_scripts/_tape_schema_v2.py SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/trade.types.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx
git commit -m "feat(packages): persist PTP price notation; tag non-monetary groups PX in UI"
```

---

### Task 5: Null-OPA legs keep NULL `opa_sign`

**Files:**
- Modify: `SDRUtils/packages/opa_sign_solver.py` (`solve_all_opa_signs` per-leg assignment loop)
- Test: `tests/test_opa_sign_solver.py`

**Interfaces:**
- Consumes: `numeric_like`.
- Produces: legs whose raw `other_payment_amount` is null get `opa_sign = None`, `opa_signed_amount = None` (previously ±1 / 0.0). Group-level columns unchanged.

- [ ] **Step 1: Write the failing test**

```python
    def test_null_opa_leg_gets_null_sign(self):
        """A leg with no OPA has no pay/receive direction — the solver
        internally treats it as 0 but must not persist a sign for it."""
        import pandas as pd

        from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

        df = pd.DataFrame({
            "trade_id": ["A", "B", "C"],
            "ptp_group_id": ["G", "G", "G"],
            "other_payment_amount": [600.0, 500.0, None],
            "package_transaction_price": [100.0, 100.0, 100.0],
            "package_transaction_price_notation": [1.0, 1.0, 1.0],
            "fixed_rate": [0.04, 0.041, 0.042],
            "tenor_years": [2.0, 5.0, 10.0],
            "estimated_pv01": [100.0, 100.0, 100.0],
        })
        out = solve_all_opa_signs(df)
        c = out[out["trade_id"] == "C"].iloc[0]
        assert pd.isna(c["opa_sign"]) and pd.isna(c["opa_signed_amount"])
        ab = out[out["trade_id"].isin(["A", "B"])]
        assert ab["opa_sign"].notna().all()
        # group summary still populated for all legs
        assert out["opa_ptp_residual"].notna().all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_opa_sign_solver.py::TestSolveOpaSigns::test_null_opa_leg_gets_null_sign -v`
Expected: FAIL — `c["opa_sign"]` is ±1.

- [ ] **Step 3: Implement**

In `solve_all_opa_signs`, capture nullness before the fillna and skip the
per-leg write:

```python
        opa_raw = numeric_like(grp[opa_col]) if opa_col in grp.columns else pd.Series(index=grp.index, dtype=float)
        opas = opa_raw.fillna(0).tolist()
        opa_is_null = opa_raw.isna().tolist()
```

and in the assignment loop:

```python
        for i, ix in enumerate(idx_list):
            if opa_is_null[i]:
                continue  # no OPA — a sign has no economic meaning
            out.at[ix, "opa_sign"] = result["signs"][i]
            out.at[ix, "opa_signed_amount"] = result["signs"][i] * opas[i]
```

- [ ] **Step 4: Run the solver + integration tests**

Run: `conda run -n stir python -m pytest tests/test_opa_sign_solver.py tests/test_ptp_pipeline_integration.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/packages/opa_sign_solver.py tests/test_opa_sign_solver.py
git commit -m "fix(packages): leave opa_sign NULL for legs with no other_payment_amount"
```

---

### Task 6: Sub-fly annotation polish

**Files:**
- Modify: `SDRUtils/packages/ptp_grouper.py` (`_detect_sub_flies`)
- Test: `tests/test_ptp_grouper.py`

**Interfaces:**
- Consumes/Produces: `_detect_sub_flies(group_df, ...) -> list[dict]` (same signature); annotations unchanged in shape (`{"type","legs","belly_dv01"}`).

- [ ] **Step 1: Write the failing tests**

Append to `TestClassifyPtpGroups`:

```python
    def test_sub_flies_use_rounded_tenor_buckets(self):
        """Raw tenors 2.01/2.04 bucket to the same 2.0 — the distinct-tenor
        check must agree with the bucketing (audit observation)."""
        legs = [
            {"tenor_years": 2.01, "estimated_pv01": 5000.0, "trade_id": "T000"},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0, "trade_id": "T001"},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0, "trade_id": "T002"},
            {"tenor_years": 2.04, "estimated_pv01": 5000.0, "trade_id": "T003"},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0, "trade_id": "T004"},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0, "trade_id": "T005"},
        ]
        df = _grouped_legs(legs)
        out = classify_ptp_groups(df)
        subs = out["ptp_sub_structures"].iloc[0]
        assert len(subs) == 2  # was [] because raw-distinct saw 4 tenors

    def test_sub_fly_pairing_keeps_rates_together(self):
        """Two equal-DV01 sub-flies at different rates must not cross-pair
        legs in the annotation."""
        legs = []
        for rate in (0.040, 0.041):
            legs.extend([
                {"tenor_years": 2.0, "estimated_pv01": 5000.0, "fixed_rate": rate},
                {"tenor_years": 5.0, "estimated_pv01": 10000.0, "fixed_rate": rate},
                {"tenor_years": 10.0, "estimated_pv01": 5000.0, "fixed_rate": rate},
            ])
        df = _grouped_legs(legs)
        rates = dict(zip(df["trade_id"], df["fixed_rate"]))
        out = classify_ptp_groups(df)
        for sub in out["ptp_sub_structures"].iloc[0]:
            leg_rates = {round(rates[tid], 6) for tid in sub["legs"]}
            assert len(leg_rates) == 1, f"cross-paired rates: {sub}"
```

- [ ] **Step 2: Run to verify failures**

Run: `conda run -n stir python -m pytest "tests/test_ptp_grouper.py::TestClassifyPtpGroups::test_sub_flies_use_rounded_tenor_buckets" "tests/test_ptp_grouper.py::TestClassifyPtpGroups::test_sub_fly_pairing_keeps_rates_together" -v`
Expected: first FAILS (subs == []); second may pass by luck of stable sort —
keep it regardless as a pin.

- [ ] **Step 3: Implement**

In `_detect_sub_flies`:

1. Replace the raw distinct check:

```python
    distinct_tenors = sorted(tenors.round(1).dropna().unique())
    if len(distinct_tenors) != 3:
        return []
```

2. Give the function a rate-aware sort. Change the signature to accept
`rate_col: str = "fixed_rate"`, read
`rates = numeric_like(group_df[rate_col]) if rate_col in group_df.columns else pd.Series(0.0, index=group_df.index)`,
carry the rate into each bucket entry
(`{"pv01": p, "tid": tid, "rate": r}` in the `by_tenor` loop — zip `rates`
alongside), and sort each bucket with:

```python
    short_sorted = sorted(short_legs, key=lambda x: (x["pv01"], x["rate"]))
    belly_sorted = sorted(belly_legs, key=lambda x: (x["pv01"], x["rate"]))
    long_sorted = sorted(long_legs, key=lambda x: (x["pv01"], x["rate"]))
```

Pass `rate_col` through from `_classify_single_group` (add the parameter
with the same default; `classify_ptp_groups` needs no change).

- [ ] **Step 4: Run the grouper test file**

Run: `conda run -n stir python -m pytest tests/test_ptp_grouper.py -v`
Expected: all PASS (the shipped 12-leg annotation test included).

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/packages/ptp_grouper.py tests/test_ptp_grouper.py
git commit -m "fix(packages): sub-fly annotations — rounded tenor buckets, rate-stable pairing"
```

---

### Task 7: Incremental-hood PTP group integrity

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py` (new module-level helper + one call in the neighborhood block, currently `~1699-1750`)
- Test: `tests/test_ptp_pipeline_integration.py`

**Interfaces:**
- Consumes: `numeric_like` from `SDRUtils.packages.ptp_grouper`.
- Produces: `_expand_hood_for_ptp_keys(df, hood_mask, *, tolerance_seconds=5) -> pd.Series` — a boolean mask ⊇ `hood_mask` that additionally includes out-of-hood PTP-candidate rows sharing a (PTP, UPI, platform) key with an in-hood candidate. Called from the incremental branch right after `_hood_mask` is computed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ptp_pipeline_integration.py`:

```python
def test_hood_expansion_pulls_in_straddling_ptp_legs():
    """A PTP group straddling the neighborhood boundary must be re-detected
    as a whole, not split between hood and cache (audit observation)."""
    import pandas as pd

    from SDRUtils.products.usd.usd_swaps import _expand_hood_for_ptp_keys

    t0 = pd.Timestamp("2026-06-25 14:30:59", tz="UTC")
    df = pd.DataFrame([
        # in-hood leg of the group
        {"trade_id": "P1", "execution_timestamp": t0,
         "package_transaction_price": "88,100", "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF"},
        # out-of-hood mate, 2s later, same key
        {"trade_id": "P2", "execution_timestamp": t0 + pd.Timedelta(seconds=2),
         "package_transaction_price": "88,100", "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF"},
        # unrelated out-of-hood trade
        {"trade_id": "O1", "execution_timestamp": t0 + pd.Timedelta(seconds=2),
         "package_transaction_price": None, "package_indicator": False,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF"},
    ])
    hood = pd.Series([True, False, False], index=df.index)
    out = _expand_hood_for_ptp_keys(df, hood, tolerance_seconds=5)
    assert bool(out.iloc[0]) and bool(out.iloc[1])
    assert not bool(out.iloc[2])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_ptp_pipeline_integration.py::test_hood_expansion_pulls_in_straddling_ptp_legs -v`
Expected: FAIL with ImportError (`_expand_hood_for_ptp_keys` undefined).

- [ ] **Step 3: Implement the helper**

Add at module level in `usd_swaps.py` (near `_resolve_special_tenor_priority`):

```python
def _expand_hood_for_ptp_keys(
    df: pd.DataFrame,
    hood_mask: pd.Series,
    *,
    tolerance_seconds: int = 5,
) -> pd.Series:
    """Widen a neighborhood mask so PTP groups are never split.

    Incremental cycles re-detect only trades near new prints; a PTP group
    straddling the window edge would otherwise be re-grouped from a subset
    of its legs while the cached remainder keeps the old package_id. Any
    out-of-window PTP candidate sharing the exact (PTP, UPI, platform) key
    with an in-window candidate, within the group time tolerance of the
    window, is pulled in.
    """
    from SDRUtils.packages.ptp_grouper import numeric_like

    ptp = numeric_like(df.get("package_transaction_price",
                              pd.Series(index=df.index, dtype=object)))
    ind = (
        df.get("package_indicator", pd.Series(False, index=df.index))
        .astype(str).str.lower().isin({"true", "t", "1", "1.0", "yes"})
    )
    ts = pd.to_datetime(
        df.get("execution_timestamp", pd.Series(pd.NaT, index=df.index)),
        errors="coerce", utc=True,
    )
    cand = ind & ptp.notna() & (ptp > 0) & ts.notna()
    hood_cand = hood_mask & cand
    if not hood_cand.any():
        return hood_mask

    upi = df.get("unique_product_identifier", pd.Series("", index=df.index)).astype(str)
    plat = df.get("platform_identifier", pd.Series("", index=df.index)).astype(str)
    key = ptp.astype(str) + "|" + upi + "|" + plat

    in_keys = set(key[hood_cand])
    lo = ts[hood_cand].min() - pd.Timedelta(seconds=tolerance_seconds)
    hi = ts[hood_cand].max() + pd.Timedelta(seconds=tolerance_seconds)
    pulled = cand & key.isin(in_keys) & ts.between(lo, hi)
    return hood_mask | pulled
```

Then in the incremental branch, immediately after `_hood_mask` is assigned
(both the computed and the all-True fallback paths converge before
`_hood_df = package_df[_hood_mask].copy()`), insert:

```python
                    _hood_mask = _expand_hood_for_ptp_keys(
                        package_df, _hood_mask, tolerance_seconds=5
                    )
```

- [ ] **Step 4: Run tests**

Run: `conda run -n stir python -m pytest tests/test_ptp_pipeline_integration.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py tests/test_ptp_pipeline_integration.py
git commit -m "fix(pipeline): expand incremental hood so straddling PTP groups re-detect whole"
```

---

### Task 8: Docs — spec update, CLAUDE.md rules, track the design docs

**Files:**
- Modify: `docs/superpowers/specs/2026-07-01-ptp-package-detection-design.md`
- Modify: `SDRUtils/CLAUDE.md`
- Track: `docs/superpowers/plans/2026-07-01-ptp-package-detection.md` (currently untracked), this plan file

**Interfaces:** none (documentation).

- [ ] **Step 1: Update the spec** — edit these sections to match shipped
reality (audit fixes + Tasks 1–7):

- Module 1 grouping table: parsing is comma/notation-tolerant
  (`numeric_like`); NaT timestamps excluded; time clustering is per
  (PTP, UPI, platform) partition.
- Module 2: CURVE requires 2 distinct tenor buckets, FLY 3 (rounded 0.1Y).
- Module 3: `dealer_spread_bps = residual / total_dv01` (true bp — replace
  the ×100 formula and re-derive the two worked examples: 12-leg fly →
  0.0003bp, 8-leg MAC → 0.20bp); solver is exact via vectorized sweep
  (N≤16) / meet-in-the-middle (N≤24), greedy above; the dollar tieout is
  gated on PTP notation 1, other notations report UNRESOLVED and persist
  `ptp_price_notation`; legs with null OPA keep null `opa_sign`.
- Schema section: add `ptp_price_notation SMALLINT` to the packages DDL and
  display view list.
- "Not in scope" → add an "Accepted behaviors" note: PTP groups bypass
  invoice/MMS/MAC/spreadover detection by design (holistic classification).

- [ ] **Step 2: Add the prevention rules to `SDRUtils/CLAUDE.md`** — append
to the "What NOT to do" list:

```markdown
- Don't parse raw SDR numerics (`Package transaction price`, `Other
  payment amount`, …) with bare `pd.to_numeric` — they arrive as strings
  with thousands separators and `;` multi-values. Use `numeric_like`
  ([`SDRUtils/packages/ptp_grouper.py`](packages/ptp_grouper.py)) or
  `_coerce_numeric_like`.
- Don't call `df.get(col)` and treat the result as a Series — pandas
  returns `None` for missing columns. Always pass a Series default:
  `df.get(col, pd.Series(index=df.index, dtype=...))`.
- Don't change detector *output* (columns or values) without bumping the
  detection cache version (see `DETECTION_CACHE_VERSION` in
  [`SDRUtils/products/usd/usd_swaps.py`](products/usd/usd_swaps.py)) AND
  `TRADE_TAPE_CACHE_VERSION`.
```

(The `DETECTION_CACHE_VERSION` constant is introduced in Task 9 — write the
doc as above; Task 9 lands before this text is ever stale because both are
in this plan. If executing out of order, land Task 9 first.)

- [ ] **Step 3: Commit (including the previously untracked design docs)**

```bash
git add docs/superpowers/specs/2026-07-01-ptp-package-detection-design.md docs/superpowers/plans/2026-07-01-ptp-package-detection.md docs/superpowers/plans/2026-07-01-ptp-audit-findings-remediation.md SDRUtils/CLAUDE.md
git commit -m "docs: sync PTP spec with audited implementation; add SDR parsing + cache-version rules"
```

---

### Task 9: Cache version unification + re-backfill + end-to-end verification

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py` (introduce `DETECTION_CACHE_VERSION`, use in `cache_flags` and warm-cache filenames)
- Modify: `SDRUtils/analytics/trade_tape.py` (`TRADE_TAPE_CACHE_VERSION`)
- Test: live DB verification queries (below)

**Interfaces:**
- Consumes: all Phase A output changes (Tasks 1, 4, 5, 6).
- Produces: `DETECTION_CACHE_VERSION = "ptp2"` module constant; caches keyed on it; both test dates re-backfilled with Phase A semantics.

- [ ] **Step 1: Introduce the single detection version constant**

In `usd_swaps.py`, near `_SERVICE_CACHE_DIR_NAME`:

```python
# Bump on ANY change to detector output (new columns, changed values).
# Keys both the classification parquet day-cache directory and the
# packaged-day warm-start pickle, so stale-schema frames can never be
# served after a deploy (2026-07-01 audit, finding C4).
DETECTION_CACHE_VERSION = "ptp2"
```

Replace the literal suffix in `cache_flags`:

```python
        cache_flags = f"curve{int(detect_curve)}_fly{int(detect_fly)}_mms{int(detect_mms)}_invoice{int(detect_invoice)}_mac{int(detect_mac)}_spreadover{int(detect_spreadover)}_basis{int(detect_basis)}_{DETECTION_CACHE_VERSION}"
```

and both warm-cache tuples:

```python
        (f"packaged_day_{DETECTION_CACHE_VERSION}.pkl", _PACKAGED_DAY_CACHE),
```

In `trade_tape.py`: `TRADE_TAPE_CACHE_VERSION = "v10-ptp-truebp-notation"`.

- [ ] **Step 2: Run the PTP + detector regression subset**

Run: `conda run -n stir python -m pytest tests/test_ptp_grouper.py tests/test_opa_sign_solver.py tests/test_ptp_pipeline_integration.py tests/test_fly_detector_arrival_order.py tests/test_gap_fly_detection.py tests/test_gap_curve_detection.py tests/test_v2_package_detection.py tests/test_basis_packages.py tests/test_sub_package_detection.py -q`
Expected: all PASS.

- [ ] **Step 3: Stop the running tape service** (it holds pre-Phase-A code
and rewrites today):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'run_usdswaps_pipeline service' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

- [ ] **Step 4: Re-backfill both audit test dates** (sequential; ~15 min each):

```bash
conda run -n stir python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline backfill --date 2026-06-25
conda run -n stir python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline backfill --date 2026-07-01
```

- [ ] **Step 5: Row-level verification** (adapt the audit's
`verify_backfill.py` queries):

```sql
SELECT package_id, package_type, ptp_group_size, opa_ptp_residual,
       opa_sign_confidence, dealer_spread_bps, ptp_price_notation
FROM arbs_usd_swap_tape_packages_v2
WHERE package_id IN ('PTP_3865630341000001201', 'PTP_3969258311000000201');
```

Expected:
- fly: PKG-12, residual ≈ 216.29, TIGHT, `dealer_spread_bps ≈ 0.000269`
  (true bp — was 0.0269), `ptp_price_notation = 1`
- MAC: PKG-8, residual ≈ 10 999, LOOSE, `dealer_spread_bps ≈ 0.2012`
  (was 20.115), `ptp_price_notation = 1`
- a PKG-24+ blob on 2026-06-25 has `ptp_price_notation = 3` and confidence
  UNRESOLVED
- legs with `other_payment_amount IS NULL` now have `opa_sign IS NULL`:

```sql
SELECT count(*) FROM arbs_usd_swap_tape_legs_v2
WHERE as_of_date='2026-06-25' AND ptp_group_id IS NOT NULL
  AND other_payment_amount IS NULL AND opa_sign IS NOT NULL;  -- expect 0
```

- [ ] **Step 6: Verify in Chrome** — June-25 filter: PKG-12 shows TIGHT +
`0.0003bp`; MAC (July 1) shows LOOSE + `0.20bp`; a notation-3 blob shows the
PX chip; spread sort still numeric; no console errors.

- [ ] **Step 7: Restart the tape service from the fixed tree**

```powershell
Start-Process -FilePath "C:\Users\chris\anaconda3\envs\stir\python.exe" `
  -ArgumentList "-m","SDRUtils._swappulse_scripts.run_usdswaps_pipeline","service","--interval","10" `
  -WorkingDirectory "C:\Users\chris\clee\ARBS" -WindowStyle Hidden `
  -RedirectStandardOutput "C:\Users\chris\clee\ARBS\sdr_cache\service.log" `
  -RedirectStandardError "C:\Users\chris\clee\ARBS\sdr_cache\service.log.err"
```

- [ ] **Step 8: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py SDRUtils/analytics/trade_tape.py
git commit -m "chore(cache): single DETECTION_CACHE_VERSION constant; bump for Phase A output changes"
```

---

# Phase B — test-suite health (independent of Phase A)

### Task 10: Delete the 7 orphaned test files

**Files:**
- Delete: `tests/test_ingest_listed_vs_swaption_vol.py`, `tests/test_listed_vs_swaption_vol_ingest.py`, `tests/test_kalshi_lob.py`, `tests/test_obi_strategy.py`, `tests/test_pca_rv_engine.py`, `tests/test_rv_query_backtest.py`, `tests/test_swap_curve_rv.py`

**Interfaces:** none. These import modules deleted in commits `c006547e`, `71d8baf0`, `e944c2d8` (`SDRUtils._swappulse_scripts.ingest_listed_vs_swaption_vol`, `OBI`, `BT.signals.pca_rv_engine`, `BT.signals.swap_curve_rv`).

- [ ] **Step 1: Confirm each target module is really gone** (guard against
renames):

```bash
ls SDRUtils/_swappulse_scripts/ | grep -i "listed_vs_swaption"; ls OBI 2>/dev/null; ls BT/signals/ | grep -iE "pca_rv|swap_curve_rv"
```

Expected: no output for all three (if any module exists under a new name,
FIX THE IMPORT instead of deleting that test file).

- [ ] **Step 2: Delete and verify collection**

```bash
git rm tests/test_ingest_listed_vs_swaption_vol.py tests/test_listed_vs_swaption_vol_ingest.py tests/test_kalshi_lob.py tests/test_obi_strategy.py tests/test_pca_rv_engine.py tests/test_rv_query_backtest.py tests/test_swap_curve_rv.py
conda run -n stir python -m pytest tests/ --collect-only -q 2>&1 | tail -3
```

Expected: `N tests collected` with **no errors**.

- [ ] **Step 3: Commit**

```bash
git commit -m "test: delete 7 orphaned test files importing deleted modules"
```

---

### Task 11: Guard the `df.get(missing) → None` crashes (~25 tests)

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py` (`detect_spreadovers`, around line 899)
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` (`_gap_aware_sort_key`, around line 510)
- Modify: `SDRUtils/analytics/trade_quality.py` (`flag_off_market_trades`, around line 132)
- Test: existing `tests/test_spreadover_tight_gate.py`, `tests/test_spreadover_package_type.py`, `tests/test_mms_imm_to_imm_exclusion.py`, `tests/test_ingest_usdswaps_tape_writepath.py`, `tests/test_trade_quality.py`

**Interfaces:** behavior on real data unchanged (these columns always exist in the live pipeline); missing-column synthetic frames no longer crash.

- [ ] **Step 1: Reproduce the three fingerprints**

```bash
conda run -n stir python -m pytest tests/test_spreadover_tight_gate.py::test_missing_invoice_swap_column_is_tolerated tests/test_ingest_usdswaps_tape_writepath.py::test_build_rows_relabel_false_positive_sdr_package_as_outright tests/test_trade_quality.py -q --tb=line 2>&1 | tail -8
```

Expected: `'numpy.float64' object has no attribute 'abs'` /
`… has no attribute 'notna'` / `'NoneType' object has no attribute 'dt'`.

- [ ] **Step 2: Fix `detect_spreadovers`**

Replace:

```python
    tenor_y = pd.to_numeric(copy_df.get("tenor_years"), errors="coerce")
```

with:

```python
    tenor_y = pd.to_numeric(
        copy_df.get("tenor_years", pd.Series([None] * len(copy_df), index=copy_df.index)),
        errors="coerce",
    )
```

In the `broker_spreadover_mask` expression a few lines below, replace the
three direct column indexings with defaulted `.get` (same pattern as the
`invoice_swap_ticker` handling directly above them):

```python
    package_legs_col = copy_df.get(
        "package_legs", pd.Series([None] * len(copy_df), index=copy_df.index)
    )
    package_ind_col = copy_df.get(
        "package_indicator", pd.Series([False] * len(copy_df), index=copy_df.index)
    )
    forward_label_col = copy_df.get(
        "forward_label", pd.Series(["spot"] * len(copy_df), index=copy_df.index)
    )
    broker_spreadover_mask = (
        (package_legs_col.isna())
        & (package_ind_col == True)
        & (forward_label_col == "spot")
        & spread_num.notna()
        ...
```

(keep the rest of the conjunction unchanged).

- [ ] **Step 3: Fix `_gap_aware_sort_key`**

```python
    tenor_y = pd.to_numeric(
        group.get("tenor_years", pd.Series(index=group.index, dtype="float64")),
        errors="coerce",
    )
    ...
    fwd_y = pd.to_numeric(
        group.get("forward_start_years", pd.Series(index=group.index, dtype="float64")),
        errors="coerce",
    )
```

- [ ] **Step 4: Fix `flag_off_market_trades`**

```python
    exec_date = pd.to_datetime(
        df.get(date_col, pd.Series(pd.NaT, index=df.index)), errors="coerce"
    ).dt.normalize()
    eff_date = pd.to_datetime(
        df.get("effective_date", pd.Series(pd.NaT, index=df.index)), errors="coerce"
    ).dt.normalize()
```

- [ ] **Step 5: Run the five files; chase any remaining same-fingerprint failures**

```bash
conda run -n stir python -m pytest tests/test_spreadover_tight_gate.py tests/test_spreadover_package_type.py tests/test_mms_imm_to_imm_exclusion.py tests/test_ingest_usdswaps_tape_writepath.py tests/test_trade_quality.py -q --tb=short
```

If any test still fails with a scalar-attribute error or
`KeyError: 'package_indicator'`-style missing column, apply the identical
defaulted-`.get` pattern at the reported line (there may be one or two more
sites inside `detect_mms_trades_df`). Expected end state: all 5 files PASS.

- [ ] **Step 6: Regression check the detector subset** (these functions run
in the live chain):

```bash
conda run -n stir python -m pytest tests/test_v2_package_detection.py tests/test_basis_packages.py tests/test_sub_package_detection.py tests/test_ptp_pipeline_integration.py -q
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py SDRUtils/analytics/trade_quality.py
git commit -m "fix: Series defaults for df.get on optional columns (spreadover/sort-key/off-market)"
```

---

### Task 12: Update stale label/lifecycle test expectations (tape_tags refactor)

**Files:**
- Modify: `tests/test_event_type_enrichment.py` (4 tests in `TestEventTypeLabelIntegration`)
- Modify: `tests/test_lifecycle_cross_day.py` (2 tests in `TestBuildEnrichedLabelCrossDay`)

**Interfaces:** none — tests move from asserting flags in `tape_label` to the `tape_tags` column, matching the 2026-05-11 refactor (`439bbe09` "move execution flags from tape_label to tape_tags column"; tags are appended in `SDRUtils/analytics/trade_tape.py:~1475`, known set at `:~1517`).

- [ ] **Step 1: Confirm the current tags contract**

Read `SDRUtils/analytics/trade_tape.py` lines 1455–1530. Determine: (a) the
output column name (`tape_tags`), (b) its type (comma-joined string vs
list). Then run one failing test with `-vv` to see the actual produced row:

```bash
conda run -n stir python -m pytest tests/test_event_type_enrichment.py::TestEventTypeLabelIntegration::test_nova_in_label -vv --tb=long 2>&1 | tail -20
```

- [ ] **Step 2: Update the six assertions**

Pattern (repeat for NOVA-IN / NOVA-OUT / EXER→`EXER-BORN`-style tag /
CLRG→`CLRG-TERM`-style tag — use the EXACT tag strings found in the
`trade_tape.py` known-tags list, and for the two lifecycle tests the
`XD-TERM` / `PARTIAL-UNWIND` tags):

```python
    def test_nova_in_label(self):
        tape = TradeTape(self._make_tape_df("NEWT-NOVA", "NOVA"))
        df = tape._build_enriched_label(self._make_tape_df("NEWT-NOVA", "NOVA"))
        assert "NOVA-IN" in str(df.iloc[0]["tape_tags"])
```

If a tag genuinely no longer exists for a case (behavior intentionally
removed), delete that assertion's test and note it in the commit message —
do not weaken the assertion to pass vacuously.

- [ ] **Step 3: Run both files**

```bash
conda run -n stir python -m pytest tests/test_event_type_enrichment.py tests/test_lifecycle_cross_day.py -q
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_event_type_enrichment.py tests/test_lifecycle_cross_day.py
git commit -m "test: assert execution flags on tape_tags per 2026-05-11 refactor"
```

---

### Task 13: Swaption package test cluster (34 failures)

**Files:**
- Modify: `tests/test_swaption_packages.py`
- Possibly modify: `SDRUtils/packages/__init__.py` or the swaption detector module (only if Step 1 shows an unintentional API break)

**Interfaces:** current production API (confirm in Step 1): `detect_and_link_swaption_packages_df(..., custy_straddle_timestamp_tolerance=...)`; `detect_conditional_curve_packages(...)` without `tail_maturity_col`; `SwaptionPackageDetector` no longer exported from `SDRUtils.packages`.

- [ ] **Step 1: Establish intent for each of the three fingerprints**

```bash
git log -S "custy_straddle_timestamp_tolerance" --oneline -3 -- SDRUtils
git log -S "SwaptionPackageDetector" --oneline -3 -- SDRUtils
git log -S "tail_maturity_col" --oneline -3 -- SDRUtils
grep -rn "def detect_and_link_swaption_packages_df\|def detect_conditional_curve_packages" SDRUtils --include=*.py
```

Decision rule per fingerprint: if the commit that changed the API says the
rename/removal was deliberate (feature commit), update the TESTS; if it
looks accidental (drive-by rename in an unrelated commit), restore a
backward-compatible alias in code instead. Expected (from the audit): all
three are deliberate May commits → update tests.

- [ ] **Step 2: Fix the kwarg drift** — in `test_swaption_packages.py`
replace every `straddle_timestamp_tolerance=` with
`custy_straddle_timestamp_tolerance=` (or the exact current name found in
Step 1), and every `tail_maturity_col=` with the current parameter (check
the signature; if the concept was removed, drop the kwarg from the call).

- [ ] **Step 3: Fix the removed-class tests** — the `SwaptionPackageDetector`
import tests (`test_detector_interface`, `test_detector_detect`,
`test_detector_custom_config`): if Step 1 shows the class was replaced by
the functional API, rewrite the three tests against
`detect_and_link_swaption_packages_df` asserting the same behaviors
(interface accepts config kwargs; detect returns linked package ids). If the
class merely moved modules, fix the import path.

- [ ] **Step 4: Fix fixture KeyErrors** — the remaining failures are
`KeyError: 'platform_identifier'` (28 across the cluster): locate the
fixture-builder function at the top of `test_swaption_packages.py` and add
the missing columns with sensible defaults:

```python
        "platform_identifier": "TWSF",
        "package_indicator": False,
```

(match existing fixture style; add only columns the detector now requires —
run the file after each addition rather than guessing the full set).

- [ ] **Step 5: Run to green**

```bash
conda run -n stir python -m pytest tests/test_swaption_packages.py tests/test_swaption_label_precedence.py -q --tb=short
```

Expected: all PASS (label-precedence file shares fixtures — fix any residue
with the same patterns).

- [ ] **Step 6: Commit**

```bash
git add tests/test_swaption_packages.py tests/test_swaption_label_precedence.py
git commit -m "test: sync swaption package tests with current detector API and fixtures"
```

---

### Task 14: Barchart / MDP / cache mock cluster (~20 failures)

**Files:**
- Modify: `tests/test_ust_future_backtest.py`, `tests/test_stir_future_backtest.py` (mock drift)
- Modify: `tests/test_barchart_session_token_cache.py`, `tests/test_barchart_stirf_curve_cache.py`, `tests/test_barchart_stirf_curve_configs.py`, `tests/test_stir_future_option_mdp_barchart.py` (14), `tests/test_stir_future_mdp_fixings.py`, `tests/test_stir_convexity_adjustment_mdp.py`, `tests/test_spread_mdp_integration.py`, `tests/test_ir_clearing_house_basis_mdp.py`, `tests/test_ir_swap_central_bank_tenors.py`, `tests/test_layered_cache_mixin.py`, `tests/test_computed_query_timeseries_cache.py`, `tests/test_query_engine_bulk_pricer_cache.py`, `tests/test_timeseries_builder_refactor.py`, `tests/test_ust_future_pricer_rateslib.py`
- Possibly modify: production code only where Step-1 diagnosis shows a real bug (e.g., the `assignment destination is read-only` ValueErrors may be a genuine numpy-view mutation bug)

**Interfaces:** none fixed in advance — this is a diagnose→fix cluster. Known fingerprints from the audit run: `'_MockUSTFutureMDP' object has no attribute 'bulk_get_data'`; `ValueError: assignment destination is read-only` (×4); token-cache reuse assertion; per-file config assertions.

- [ ] **Step 1: Capture per-file first errors**

```bash
conda run -n stir python -m pytest tests/test_ust_future_backtest.py tests/test_stir_future_backtest.py tests/test_barchart_session_token_cache.py tests/test_barchart_stirf_curve_cache.py tests/test_barchart_stirf_curve_configs.py -x -q --tb=short 2>&1 | tail -25
```

(then the remaining files in a second batch). For each distinct error,
apply the decision rule: **test drift** (mock/fixture missing something
production added — e.g., `_MockUSTFutureMDP` needs a `bulk_get_data` that
delegates to its existing `get_data` per symbol) → fix the test; **code
bug** (e.g., mutating a read-only numpy view from a memory-mapped parquet)
→ use the `superpowers:systematic-debugging` skill and fix the code with a
regression test.

Known first fix (mock drift):

```python
class _MockUSTFutureMDP:
    ...
    def bulk_get_data(self, queries):
        return [self.get_data(q) for q in queries]
```

(match the real `bulk_get_data` signature — check
`grep -n "def bulk_get_data" MDP -r` first.)

- [ ] **Step 2: Work file-by-file to green**, committing per coherent chunk:

```bash
conda run -n stir python -m pytest <file> -q --tb=short
```

- [ ] **Step 3: Full-cluster pass**

```bash
conda run -n stir python -m pytest tests/test_ust_future_backtest.py tests/test_stir_future_backtest.py tests/test_barchart_session_token_cache.py tests/test_barchart_stirf_curve_cache.py tests/test_barchart_stirf_curve_configs.py tests/test_stir_future_option_mdp_barchart.py tests/test_stir_future_mdp_fixings.py tests/test_stir_convexity_adjustment_mdp.py tests/test_spread_mdp_integration.py tests/test_ir_clearing_house_basis_mdp.py tests/test_ir_swap_central_bank_tenors.py tests/test_layered_cache_mixin.py tests/test_computed_query_timeseries_cache.py tests/test_query_engine_bulk_pricer_cache.py tests/test_timeseries_builder_refactor.py tests/test_ust_future_pricer_rateslib.py -q
```

Expected: all PASS.

- [ ] **Step 4: Commit** (one commit per root cause is fine; final subject):

```bash
git commit -m "test: sync barchart/MDP/cache mocks and fixtures with current interfaces"
```

---

### Task 15: Misc remainder (~15 failures)

**Files:**
- Modify as diagnosed: `tests/test_live_atmf_grid_ingest.py` (3), `tests/test_supabase_computed_timeseries_sync.py` (1), `tests/test_ingest_listed_option_oi_volume.py` (2), plus any residue from the full-suite list not covered by Tasks 11–14 (`KeyError: '15y_10y'` grid tests, SABR `requires at least 6 valid strike-vol points` fixtures, date-type asserts)

**Interfaces:** none fixed in advance; same decision rule as Task 14.

- [ ] **Step 1: Regenerate the current failure inventory** (Tasks 10–14 will
have shrunk it):

```bash
conda run -n stir python -m pytest tests/ -q --tb=line 2>&1 | tee scratch_failures.txt | grep -E "^FAILED" | sed 's/::.*//' | sort | uniq -c | sort -rn
```

- [ ] **Step 2: For each remaining file**: reproduce with `--tb=short`,
classify (fixture drift → fix fixture: e.g., SABR tests need ≥6 strike-vol
points in the synthetic smile; `15y_10y` KeyError → the grid key set
changed, update the expected-keys fixture; supabase sync → likely needs a
mocked client, follow the existing mock pattern in the same file), fix,
re-run the file to green. Use `superpowers:systematic-debugging` for
anything that isn't an obvious drift.

- [ ] **Step 3: Delete `scratch_failures.txt`, commit**

```bash
git commit -m "test: fix remaining fixture/assert drift (atmf grid, SABR smile, grid keys, supabase sync)"
```

---

### Task 16: Pytest markers + fast gate

**Files:**
- Modify: `pytest.ini`
- Modify: marked test files (identified in Step 2)
- Modify: `CLAUDE.md` (repo root — test-command documentation)

**Interfaces:**
- Produces: registered markers `slow`, `network`, `db`; documented fast gate `conda run -n stir python -m pytest tests -m "not slow and not network and not db" `.

- [ ] **Step 1: Register markers** — in `pytest.ini` add (preserving existing
content):

```ini
markers =
    slow: takes >60s; excluded from the fast gate
    network: hits external services (DTCC, Barchart, Supabase)
    db: requires a live DATABASE_URL
```

This also kills the existing `PytestUnknownMarkWarning: Unknown
pytest.mark.slow` warnings from `tests/perf/`.

- [ ] **Step 2: Identify offenders empirically**

```bash
conda run -n stir python -m pytest tests/ -q --durations=40 2>&1 | tail -45
```

Mark every test/module >60s with `pytestmark = pytest.mark.slow` (module
level) or per-test decorators; anything that opened a socket to
DTCC/Barchart/Supabase additionally gets `network`/`db`. From the audit run,
expect `tests/perf/*` and several ingest/MDP integration files here.

- [ ] **Step 3: Verify the fast gate**

```bash
conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q 2>&1 | tail -3
```

Expected: PASS in well under 15 minutes (record the actual time).

- [ ] **Step 4: Document** — add to the repo-root `CLAUDE.md` (create a
"Testing" section if absent):

```markdown
## Testing
- Fast gate (pre-commit): `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
- Full suite (~1.5h, needs network + DATABASE_URL): `conda run -n stir python -m pytest tests`
```

- [ ] **Step 5: Commit**

```bash
git add pytest.ini CLAUDE.md tests
git commit -m "test: register slow/network/db markers; document fast gate"
```

---

### Task 17: Dashboard jest debt (29 failures / 7 suites)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/TapeLabelCell.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCard.test.tsx`, `.../VolumeGridCellModal.test.tsx`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/__tests__/route.cache.test.ts`, `.../extremes/__tests__/route.cache.test.ts`, `.../rarity/__tests__/route.cache.test.ts`

**Interfaces:** none — expectations sync + DB mocking. All failures pre-date the PTP feature (palette change `809f1fe6`; UFRO token moved to tags in the 2026-05-11 refactor).

- [ ] **Step 1: rowClassName palette (2 tests)** — in `columns.test.ts`
update the CURVE expectations to the current classes:

```ts
    expect(cls).toContain('!bg-blue-900/50')
```

(both occurrences; keep the `toMatch(/border-sky/)` lines — they already
pass). Before editing, confirm the current classes are intentional:
`grep -n "bg-blue-900" SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.helpers.ts`.

- [ ] **Step 2: TapeLabelCell UFRO** — the label no longer embeds `UFRO`
(moved to tags). Update the expected string in the failing test to the
current label (`USD-SOFR-COMPOUND 1D Constant 5Y11M 1Y Outright PHYS`) and,
if the fixture carries tags, add a companion assertion that `UFRO` appears
in the row's tags path instead.

- [ ] **Step 3: VolumeGrid suites** — run each with `--tb`-equivalent
verbosity:

```bash
node --experimental-vm-modules node_modules/jest/bin/jest.js --testPathPatterns="VolumeGridCard" 2>&1 | grep -A12 "●" | head -40
```

Classify each failure (expected: fixture-shape drift vs the current
`RawVolumeGridRow`, same class as the tsc errors in Task 18 — fix fixtures
to the current type, including `invoice_current`).

- [ ] **Step 4: route.cache suites (65–130s each = live DB attempts)** —
mock the db module at the top of each suite so they run hermetic and fast:

```ts
jest.mock('@/lib/db', () => ({
  query: jest.fn(async () => ({ rows: [] })),
}))
```

then adapt each test's arrange step to seed `query` per-case
(`(query as jest.Mock).mockResolvedValueOnce({ rows: [...] })`) following
the suite's existing cache-behavior assertions. If a suite is genuinely an
integration test, instead gate it:
`const maybe = process.env.DATABASE_URL ? describe : describe.skip` — choose
per suite based on what it asserts (cache-header logic → mock; end-to-end
query shape → gate).

- [ ] **Step 5: Full dashboard jest run**

```bash
node --experimental-vm-modules node_modules/jest/bin/jest.js 2>&1 | tail -6
```

Expected: 0 failed (skipped integration suites OK when no DATABASE_URL).

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src
git commit -m "test(dashboard): sync stale expectations; mock db in route.cache suites"
```

---

### Task 18: Dashboard tsc to clean (52 error lines)

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts` and `.../volume-grid/structure/__tests__/route.logic.test.ts` (fixtures missing `invoice_current`)
- Modify: `__tests__/e2e/usd-swaps-v2.test.ts` (`page.waitForTimeout` no longer exists)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/__tests__/InterTradeGaps.test.tsx` (`pts` type)

**Interfaces:** none — type-level only.

- [ ] **Step 1: Volume-grid fixtures** — every fixture object flagged
`Property 'invoice_current' is missing` gets `invoice_current: 0` added
(match the neighboring `curve_current`/`fly_current` style). If the fixture
builder is a helper, add it once there.

- [ ] **Step 2: e2e `waitForTimeout`** — replace both uses with a local
sleep (puppeteer removed the API):

```ts
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
// ...
await sleep(1000)
```

- [ ] **Step 3: InterTradeGaps `pts`** — the fixture builds
`pts: number | null | undefined` against `FocusedTrade.pts: number | null`;
coalesce at the fixture: `pts: row.pts ?? null` (or type the literal
explicitly).

- [ ] **Step 4: Verify clean**

```bash
cd SDRUtils/dashboard && npx tsc --noEmit; echo "exit=$?"
```

Expected: no output, `exit=0`.

- [ ] **Step 5: Commit**

Run from the repo root:

```bash
git add SDRUtils/dashboard __tests__/e2e/usd-swaps-v2.test.ts
git commit -m "chore(dashboard): tsc --noEmit clean — fixture types, e2e sleep helper"
```

(The e2e file lives at the repo root `__tests__/e2e/` per the tsc output —
confirm with `ls __tests__/e2e/` before staging.)

---

### Task 19: Green-gate verification

**Files:** none (verification only; report update).

- [ ] **Step 1: Full Python suite**

```bash
conda run -n stir python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: `0 failed` (skips OK). Record runtime.

- [ ] **Step 2: Fast gate**

```bash
conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q 2>&1 | tail -3
```

Expected: `0 failed`, runtime recorded.

- [ ] **Step 3: Dashboard**

```bash
cd SDRUtils/dashboard && npx tsc --noEmit && node --experimental-vm-modules node_modules/jest/bin/jest.js 2>&1 | tail -4
```

Expected: tsc silent; jest 0 failed.

- [ ] **Step 4: Append a "Remediation completed" addendum** to
`docs/superpowers/audits/2026-07-01-ptp-package-detection-audit.md` — date,
the two phase outcomes, final suite numbers, and the re-backfill
verification values from Task 9.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/audits/2026-07-01-ptp-package-detection-audit.md
git commit -m "docs(audit): remediation addendum — all findings closed, suites green"
```
