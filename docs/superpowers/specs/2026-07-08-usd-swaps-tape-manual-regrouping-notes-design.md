# USD Swaps Tape — Manual Package Regrouping & Trader Notes

**Date:** 2026-07-08
**Status:** Design / spec for implementation (approved in brainstorming; feature is greenfield)
**Area:** `SDRUtils/dashboard` (frontend + API) + `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` (DDL/view)

## 0. Context for the implementer

Traders need to manually correct the auto-detected package groupings on the USD Swaps Tape and annotate trades/packages with free-text notes. Three capabilities: **GROUP** (merge legs/outrights into a manual package), **SPLIT** (break an auto-package into its individual legs), **DETACH** (pull specific legs out of a package). Plus **trader notes** and a **password gate** on structural edits.

### Terrain that shaped this design (verified against the codebase, 2026-07-08)

- **Two table families + a shared links table.** The dashboard reads the **tape** family (`arbs_usd_swap_tape_{packages,legs,display}_v2`, defined in `_tape_schema_v2.py`). A separate **legacy** family (`arbs_usd_swap_{packages,legs}_v2`) + the shared `arbs_usd_swap_manual_links_v2` / `arbs_usd_swap_link_history_v2` are defined in `ingest_usdswaps.py`. The existing manual-link write API mutates the **legacy** tables; the **tape** tables only pick links up via `attach_manual_links` on the **next ingest cycle** — a latency trap this design avoids.
- **The tape display view is a live (non-materialized) SQL view.** It does a `LEFT JOIN LATERAL` leg aggregation (`jsonb_agg(to_jsonb(l))`) per package per read, plus `LEFT JOIN arbs_usd_swap_manual_links_v2 ml ON ml.link_id = p.manual_link_id AND ml.is_active`.
- **Auth reality:** there is **no** password gate on the USD-swaps path today (create/edit/delete require only a `user` string). A hardcoded `SIMPLE_ADMIN_PASSWORD='admin'` (401 on fail) exists **only** in the swaption tree (`lib/utils.ts`). We are *adding* a gate.
- **`superseded_by` exists but is dead** in the current manual-links code (supersession is really `is_active=false`). This design *activates* a real version chain.
- **Frontend:** the create dialog is feature-local, but the detail modal / form hook / API client / badge / `groupLinkedRows` live in **shared `lib/manual-links-ui/`** co-consumed by the swaptions tape. **Do not entangle the shared lib** with tape-specific override semantics. No drag-drop / context-menu / inline-edit infra exists. `user_comment` rides on every tape row but is **never rendered** — that is the notes gap. Row selection (`useRowSelection`) returns **full `UsdSwapTapeRow` objects**; expansion (`useRowExpansion`) is keyed by `package_id`. The API operates on **trade_ids**, flattened from `selected[].legs_json[].trade_id`.
- **Guardrail:** *never write to the ingest-owned `_tape_packages/legs_v2` tables from the dashboard.* All overrides go through new tables; the view resolves them at read time.

### Performance findings (measured on prod, 2026-07-08)

Prod volume: **1.30M packages, 1.65M legs, 1.26 legs/pkg**, Nov 2024→Jul 2026 (~2.1k pkgs/day). `manual_links` has **1 row, 0 active** → greenfield.

- **Per-page (LIMIT 200) latency is flat across all history** (~55–76ms warm p50; server ~30ms). Deep historical pages are *not* slower than recent ones, because `idx_tape_v2_packages_exec_start` (`execution_start DESC NULLS LAST`) exactly matches the ORDER BY → every page is an O(200) index walk. **Materialization is not warranted** (it would shave ~30ms server compute but not the ~40% network-transfer share, and forces REFRESH/staleness onto a 3s-polling tape).
- The **read-time override resolution** (indexed override set, hash-joined **once** over the page's legs, `legs_json` unchanged, overrides surfaced as a **sparse `override_map`**) adds **~4ms server-side (+13%)** even at a generous **800 active-override member trades**, and **preserves both the exec_start index scan and package cardinality** (no re-carve). Verified via EXPLAIN ANALYZE. This is the load-bearing assumption; it holds.
- Anti-patterns proven costly and to be avoided in the view: (a) a **correlated per-package CTE** re-evaluates the override set per row (+130%); (b) an **unindexed** override set forces a merge-join re-scan per package (+50–78%); (c) rewriting **every** leg's 130-key `jsonb` via `to_jsonb(l) || jsonb_build_object(...)` (+65–78% client). The correct shape (§1.3) avoids all three.

Benchmark scripts (keep as perf guards): `scratchpad/bench_tape_view.js`, `scratchpad/bench_override_join.js` (to be promoted into the repo under `SDRUtils/dashboard/scripts/` during implementation).

---

## 1. Data model

### 1.1 `arbs_usd_swap_tape_overrides_v2` (new; tape-scoped; NOT written by ingest)

| column | type | notes |
|---|---|---|
| `override_id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `override_type` | `TEXT NOT NULL` | `CHECK (override_type IN ('GROUP','SPLIT','DETACH'))` |
| `manual_package_id` | `TEXT` | for `GROUP` clustering; `UNIQUE` where non-null; generated `SMO-YYYYMMDD-{8hex}` |
| `trade_ids` | `TEXT[] NOT NULL` | member trades |
| `created_by` | `TEXT NOT NULL` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | |
| `updated_by` / `updated_at` | `TEXT` / `TIMESTAMPTZ` | |
| `reason` | `TEXT` | |
| `tags` | `TEXT[]` | |
| `metrics` | `JSONB NOT NULL DEFAULT '{}'` | notional/risk/rate rollup (reuse `computeLinkMetrics` logic) |
| `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | soft-delete = revert to auto |
| `superseded_by` | `UUID REFERENCES arbs_usd_swap_tape_overrides_v2(override_id)` | **real version chain** |

Constraints:
- `CHECK (override_type <> 'GROUP' OR array_length(trade_ids,1) >= 2)` — GROUP needs ≥2; SPLIT/DETACH allow 1.
- **One active override per trade** — the write transaction supersedes any existing active override overlapping the incoming `trade_ids` (`is_active=FALSE, superseded_by=<new>`), and the partial unique index on the members table (§1.1, `arbs_usd_swap_tape_override_members_v2`) is the hard DB backstop.
- Indexes: `GIN (trade_ids)` for overlap detection; partial `(is_active) WHERE is_active`; `(manual_package_id)`; `(created_at)`.

Companion audit table **`arbs_usd_swap_tape_override_history_v2`**: `history_id BIGSERIAL PK · override_id UUID · action TEXT ('CREATED'|'UPDATED'|'DEACTIVATED'|'SUPERSEDED') · changed_by · changed_at · change_details JSONB · previous_state JSONB`.

**`arbs_usd_swap_tape_override_members_v2`** (new; the normalized, view-optimized projection of active membership — see §1.3 for why this exists rather than unnesting the array in the view):

| column | type | notes |
|---|---|---|
| `trade_id` | `TEXT NOT NULL` | |
| `override_id` | `UUID NOT NULL REFERENCES arbs_usd_swap_tape_overrides_v2(override_id)` | |
| `override_type` | `TEXT NOT NULL` | denormalized for the view |
| `manual_package_id` | `TEXT` | denormalized for the view |
| `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | mirrors the parent override |

- **`CREATE UNIQUE INDEX ... ON (trade_id) WHERE is_active`** — DB-enforces the *one-active-override-per-trade* invariant (the write transaction also guarantees it by superseding, but this is the hard backstop).
- Btree on `(trade_id)` (the unique-partial index serves the view's per-leg probe).
- This table is a maintained derivation of the parent override's `trade_ids[]` — the write path rewrites its rows for an override inside the same transaction, so there is no drift. `trade_ids[]` on the parent remains the human-facing record and the GIN-indexed surface for overlap detection.

### 1.2 `arbs_usd_swap_tape_notes_v2` (new)

`note_id UUID PK · target_type TEXT CHECK IN ('TRADE','PACKAGE') · target_id TEXT NOT NULL · author TEXT NOT NULL · body TEXT NOT NULL · created_at · updated_at · is_active BOOLEAN DEFAULT TRUE`.
Index: `(target_type, target_id) WHERE is_active`. A `TRADE` note keys on `trade_id`; a `PACKAGE` note keys on `package_id` (auto packages) **or** `manual_package_id` (manual groups). Notes are independent of the ≥2 grouping rule — a lone outright can be annotated.

### 1.3 View change — `arbs_usd_swap_tape_display_v2` (stays a live view)

Add to the existing `CREATE OR REPLACE VIEW`, **appended at the end of the SELECT list** (rename-safe): `override_map JSONB`, `manual_package_id`, `override_type`, `has_notes BOOLEAN`, `notes_count INT`. **`legs_json` stays byte-identical to today.**

**Why the members table (§1.1) and not an unnest-CTE.** A plain SQL view cannot see the caller's `WHERE/ORDER/LIMIT` (`buildTapeQuery` appends them), so the view is inherently the current **per-package `LEFT JOIN LATERAL`** form — the planner pushes the caller's `LIMIT 200` down so the LATERAL runs for only ~200 packages. Inside that LATERAL, a per-leg lookup against an **unnested-array CTE** is re-scanned per package (measured **+52–67%**) or, if correlated, re-evaluated per row (**+130%**). The fix is to make the per-leg lookup an **index probe**: join legs to `arbs_usd_swap_tape_override_members_v2` on `trade_id` via its partial-unique btree.

Resolution shape (inside the existing per-package LATERAL; `legs_json` unchanged):

```sql
-- ... existing package columns ...
-- inside the LATERAL over legs l WHERE l.package_id = p.package_id:
jsonb_agg(to_jsonb(l) ORDER BY l.leg_order)                       AS legs_json      -- unchanged from today
LEFT JOIN arbs_usd_swap_tape_override_members_v2 m                                   -- index probe per leg
  ON m.trade_id = l.trade_id AND m.is_active
-- surfaced per package:
jsonb_object_agg(l.trade_id, m.override_id)
  FILTER (WHERE m.override_id IS NOT NULL)                         AS override_map   -- sparse, empty for ~99%
max(m.manual_package_id)                                           AS manual_package_id
max(m.override_type)                                              AS override_type
```

Per-leg index probes against a sparse, small active-members table are microseconds each (~255 legs/page); this should be **≤ the +13% hash-join-once figure** measured for the equivalent shape in `bench_override_join.js`. **Acceptance / plan-regression gate (§4.1):** `EXPLAIN (ANALYZE)` on a representative page must show (a) the outer scan still uses `idx_tape_v2_packages_exec_start`, (b) package cardinality unchanged (200 rows, no re-carve), and (c) the members join resolved as an index scan/probe — not a seq-scan or per-package re-scan. If the planner mis-plans, fall back to stamping `override_map` via the same members join in a thin wrapper, but do **not** reintroduce an unnested-array CTE inside the LATERAL.

Note bodies are **NOT** in the view — only `has_notes`/`notes_count` indicators (a cheap correlated `EXISTS`/count against the sparse notes table, or a second small LATERAL). Bodies are lazy-fetched (§2).

---

## 2. Write path & API

New **tape-dedicated** routes under `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/` (these do **not** re-export the shared `sofr-swap` handlers; the shared `manual_links` CRUD stays intact for the swaption/legacy trees):

**Overrides**
- `POST /overrides` — body `{ override_type, trade_ids, manual_package_id?, reason?, tags?, user, admin_password }`. Flow in one `withClient` transaction: validate (types/counts/trades-exist/overlap) → **supersede** overlapping active overrides (flip parent `is_active` + `superseded_by`, and their members' `is_active`) → insert parent override → **insert its member rows** into `arbs_usd_swap_tape_override_members_v2` → history. Supports `validate_only:true` (returns validation+metrics, no write). The members table is always rewritten from the parent's `trade_ids[]` in the same transaction (no drift).
- `PATCH /overrides/[id]` — edit metadata / `add_trades` / `remove_trades`; re-validate, re-supersede, in-place update + **rewrite member rows** + history (one transaction).
- `DELETE /overrides/[id]` — `is_active=FALSE` on the parent **and its member rows** + history `DEACTIVATED` (reverts to auto).
- `GET /overrides` + `GET /overrides/[id]` — list / detail-with-history.

**Notes**
- `POST /notes` `{ target_type, target_id, author, body }`; `PATCH /notes/[id]`; `DELETE /notes/[id]` (soft); `GET /notes?target_type=&target_id=` (lazy body fetch).

**Auth** — new helper `isValidTapeWritePassword(value)` in `dashboard/src/lib/utils.ts`, comparing against **env var `TAPE_OVERRIDE_PASSWORD`** (documented in `.env.example`; **no hardcoded default** — missing env ⇒ all structural writes 403). Gate: override `POST/PATCH/DELETE` → 403 on fail. Notes require a non-empty `author` only (no password).

**Transactions** — override writes use `withClient` with explicit `BEGIN/COMMIT/ROLLBACK`, fixing the non-atomic gap in the existing manual-links path.

**Guardrail** — no writes to `_tape_packages/legs_v2`. Reflection is via the read-time view join → immediate, no re-ingest wait. On success the client calls `tape.refetch()`.

---

## 3. Frontend

Feature root `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`.

### 3.1 Selection (leg-level)
- Add a checkbox column to `LegsSubTable` (16→17 cols; keep `LEG_COL_COUNT`/summary colspan in lockstep).
- New orchestrator state `selectedTradeIds: Set<string>` spanning package rows and individual legs. Package-row checkbox = all its legs; partial leg selection = indeterminate.

### 3.2 Contextual action bar
- Rendered in the existing toolbar `actionSlot` (and mobile bar) when the selection is non-empty. Actions **Group · Split · Detach · Note**, enabled contextually: **Group** ≥2 trades; **Split** = exactly one multi-leg auto-package selected; **Detach** = ≥1 leg selected within a package that retains ≥1 other leg; **Note** = any single target.
- Commit via a lightweight inline popover carrying the password field (persisted in orchestrator like today's `adminPassword`). Errors inline (no toast lib), success → clear selection + `tape.refetch()`.

### 3.3 Visual language (extends existing amber-tint + `ManualLinkBadge`)
- **GROUP** — manual badge + per-override color; a distinct "manually regrouped" marker separating it from auto-detected packages.
- **SPLIT** — the package row **explodes into per-leg rows** in a tape-local display transform (driven by `override_type='SPLIT'` + `override_map`); each split-off leg carries a scissors/dashed marker and a synthetic row key.
- **DETACH** — the detached leg leaves its package cluster and renders standalone with an unlinked marker.
- Exact palette/iconography to be finalized against interactive mockups; must read cleanly in the existing `lara-dark-indigo` theme.

### 3.4 Regroup transform
- A **tape-local** wrapper (new file under `features/usd-swaps-tape-v2/`) around `groupLinkedRows` — **do not modify** shared `lib/manual-links-ui/grouping.ts` (swaptions consumes it). The wrapper honors `override_map`/`override_type` for GROUP clustering, SPLIT explosion, and DETACH removal, then hands rows to the DataTable. Split/detach synthetic rows must interoperate with virtual scroll (`dataKey`, `itemSize`), selection, and expansion.

### 3.5 Notes UI
- Per-leg note icon in `LegsSubTable` and per-package note icon on the row, gated by `has_notes`/`notes_count`. Click → popover reads (lazy `GET /notes`) and adds/edits (author = saved username via `useSavedUser`). No password.

### 3.6 Undo / management
- Deactivating an override reverts to auto instantly. A post-action **undo** affordance (re-activate the just-deactivated override / deactivate the just-created one). A small **"Overrides" panel** (reachable from the toolbar) lists active overrides with revert + history view.

### 3.7 Types & API client
- Extend `types/trade.types.ts`: `UsdSwapTapeRow` gains `override_map?`, `override_type?`, `manual_package_id?` (already present), `has_notes?`, `notes_count?`. New `types/override.types.ts`, `types/note.types.ts`.
- New tape-local API client `api/overrideApi.ts`, `api/noteApi.ts` (mirror `manualLinkApi.ts` patterns; do not reuse the shared client, whose base path/semantics differ).

---

## 4. Testing, migration, rollout

### 4.1 Tests
- **API (unit):** override validation (type/count rules, GROUP≥2, SPLIT/DETACH single-trade OK), overlap→supersede→one-active-per-trade invariant, transaction rollback on mid-write failure, notes CRUD, `isValidTapeWritePassword` 403 paths. Notes gate = author-only.
- **DB plan-regression:** assert the view plan retains the `idx_tape_v2_packages_exec_start` scan and evaluates the override set once (guard against the +130% per-loop regression).
- **Frontend (jest, ESM):** run via `npm test` **only** (plain `npx jest` bypasses ESM mocks → false Supabase failures). Cover selection model, action-bar enablement matrix, the regroup transform (GROUP/SPLIT/DETACH), note popovers.
- **Perf guard:** promote the benchmark scripts to `SDRUtils/dashboard/scripts/`; budget p95 per-page ≤ ~1.3× baseline with N active overrides.
- **Browser verification:** verify all frontend changes in Chrome MCP against `localhost:3000` before committing (standing rule).

### 4.2 Migration (no framework — idempotent DDL)
- Add all four new tables (`arbs_usd_swap_tape_overrides_v2`, `..._override_history_v2`, `..._override_members_v2`, `..._notes_v2`) + their indexes + the five new view columns via idempotent DDL in `_tape_schema_v2.py` (tables: `CREATE TABLE IF NOT EXISTS`; indexes: `CREATE ... IF NOT EXISTS`; view: `CREATE OR REPLACE VIEW` with new columns appended).
- **Update `_LATEST_MIGRATION_COLS`** in `ingest_usdswaps_tape.py` to a new sentinel `(table, column)` referencing one of the new columns/tables — otherwise `ensure_schema()` short-circuits and the DDL never runs on provisioned DBs. (Known trap.)
- Every DDL statement `;`-terminated (the executor splits on `;`).

### 4.3 Rollout
- Tape DB is **remote Supabase prod** — test writes carefully; the override/notes tables are additive and safe. Read path is unchanged in shape (view gains sparse columns).
- No `_v1`/rollback impact; overrides are inert until first written.

---

## 5. Decisions locked (from brainstorming)

1. **Model:** unified stamped override (GROUP/SPLIT/DETACH), resolved read-time cardinality-preserving; **no materialization**.
2. **Interaction:** contextual action bar + leg-level selection (no drag-drop).
3. **Notes:** unified store, trade + package level.
4. **Auth:** env-var password on structural commits; notes need only a username.
5. **Isolation:** tape-dedicated tables/routes/UI; shared `manual-links-ui` lib and other product trees untouched.

## 6. Open items for the plan / mockups
- Final SPLIT/DETACH iconography + palette (interactive mockups).
- Exact `override_map` → frontend synthetic-row keying for virtual scroll.
- Whether the "Overrides" management panel reuses the analytics-dock chrome or is a modal.
