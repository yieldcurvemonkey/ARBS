# USD Swaps Tape v2 — Manual Linking Revamp + Shared Extraction — Design

**Date.** 2026-05-04
**Companion plan.** [docs/plans/2026-05-04-manual-links-revamp-implementation.md](2026-05-04-manual-links-revamp-implementation.md) (forthcoming)
**Routes affected.** `/usd-swaps` and `/swaptions` (the swaptions-tape consumer).
**Feature modules.** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/` and `SDRUtils/dashboard/src/features/swaptions-tape/`.
**New shared module.** `SDRUtils/dashboard/src/lib/manual-links-ui/`.
**Stack.** Same as WS1 / WS2. No new runtime dependencies.

---

## 0. Why this plan

`usd-swaps-tape-v2` ships a minimal manual-linking flow today:

- `useManualLinks` is a thin CRUD wrapper around `/api/usd-swaps-tape-v2/links`
  (POST / PATCH / DELETE) at [useManualLinks.ts:1-82](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useManualLinks.ts).
- `ManualLinksDialog` is a 6-field create-only form at [ManualLinksDialog.tsx](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/ManualLinksDialog.tsx).
- Tape rows carry `manual_link_id` and `manual_package_id` fields (via the shared
  sofr-swaps-tape parent type) but **no row-level visual indication** that a row
  is linked. Linked rows look identical to unlinked rows.
- No detail modal. No edit. No deactivate. No history. No validation feedback.

`swaptions-tape` ships a full ecosystem on the same shared API:

- Hash-based row chips coloured consistently per `link_id` so a linked group is
  visually identifiable across the tape.
- `groupLinkedRows` clusters rows by link.
- A detail modal shows the full link record + linked trades + history audit
  trail; supports edit (admin-password gated) and deactivate (soft-delete,
  `is_active = FALSE`).
- A richer `useManualLinks` state machine: validate-only POSTs, auto-validate on
  dialog open, validation items + computed metrics surfaced in the form.

Both consumers talk to the same `arbs_usd_swap_manual_links_v2` table (the v2
routes re-export the sofr handlers). The API surface for swaptions parity already
exists at the route layer; the gap is overwhelmingly UI + hook state-machine.

The user has chosen the **full parity + extraction** tier: bring v2 to
swaptions-grade, and extract the duplicated UI primitives into a shared module so
both features import from one place.

---

## 1. Approach

Three moves, in order:

1. **Extract** swaptions-tape's manual-link UI primitives into a new shared module
   `lib/manual-links-ui/`. Refactor swaptions to import from the new module;
   verify zero behavior change.
2. **Adopt** the shared module into v2: row badges, detail modal, state-machine
   hook, edit / deactivate flows.
3. **Verify** v2 tape API hydrates `manual_link_id` / `manual_package_id` on every
   row (LEFT JOIN on `arbs_usd_swap_manual_links_v2`) so badges actually render.

The detail modal is a single read+edit component (current swaptions style; user
direction). Admin password is required for PATCH/DELETE; POST stays open. Tape
JOIN includes manual link metadata on every row.

### 1.1 Shared module: `lib/manual-links-ui/`

Module surface:

```
lib/manual-links-ui/
  ├── color.ts                      // manualLinkColor(linkId): string (HSL)
  ├── predicates.ts                 // isManualPackage(row): boolean
  ├── grouping.ts                   // groupLinkedRows(rows): GroupedRow[]
  ├── components/
  │   ├── ManualLinkBadge.tsx       // chip (color + label + linkId)
  │   ├── ManualLinkDetailModal.tsx // single read+edit component
  │   ├── ManualLinkValidationList.tsx
  │   ├── ManualLinkMetricsTable.tsx
  │   └── ManualLinkHistoryTable.tsx
  ├── hooks/
  │   ├── useManualLinkDetails.ts   // GET /links/:id (link + trades + history)
  │   └── useManualLinkForm.ts      // state machine: validate-only, auto-validate, validation items, metrics
  ├── api/
  │   └── manualLinkApi.ts          // typed wrappers around fetch
  ├── types.ts                      // shared type definitions
  └── index.ts
```

Both v2 and swaptions import from `lib/manual-links-ui/`. Each consumer wires the
shared components into its own column / dialog opening logic.

### 1.2 Swaptions refactor (zero behaviour change)

Phase A is purely structural: copy the existing swaptions implementations of
`manualLinkColor`, `isManualPackage`, `groupLinkedRows`, the badge component,
detail modal, and form hook into `lib/manual-links-ui/`; update swaptions imports;
delete the now-unused source files. Tests must remain green throughout.

This is the riskiest phase — swaptions is in production and any subtle regression
here is bad. Mitigation: phase A ships in three commits (extract pure functions;
extract components; extract hooks) with full test runs between commits, and the
swaptions test suite must pass byte-for-byte.

### 1.3 v2 adoption

After extraction, v2 imports from the shared module:

- **Row badges** in v2 columns: `<ManualLinkBadge>` rendered in the Pkg column when
  `isManualPackage(row)` is true. Click opens detail modal.
- **Row grouping**: `groupLinkedRows()` applied in the table render path so linked
  rows cluster visually.
- **Detail modal**: `<ManualLinkDetailModal>` mounted at the panel level; opened via
  badge click. Read + edit + history + deactivate in one surface (single
  read+edit component per user direction).
- **State-machine hook**: replace minimal `useManualLinks` with the shared
  `useManualLinkForm`; auto-validate on dialog open; surface validation items +
  metrics.
- **Edit + deactivate**: PATCH and DELETE flows wired through `useManualLinkForm`.
  Admin password gate matches swaptions.

### 1.4 API surface

The v2 routes at `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/links/` already
re-export the shared sofr handler. Audit (Phase F) confirms each endpoint is
reachable from v2:

- `POST /links?validate_only=true` — validation only
- `POST /links` — create
- `GET /links?...` — list
- `GET /links/:linkId` — detail (link + linked trades + history)
- `PATCH /links/:linkId` — edit metadata + add/remove trades (admin-password gated)
- `DELETE /links/:linkId` — deactivate (admin-password gated)

If any are missing, add re-export. No new routes expected.

### 1.5 Tape JOIN

User direction: include manual link metadata on every tape row (current swaptions
behavior). Phase F audits and (if needed) extends `route.logic.ts` `buildTapeQuery`
to LEFT JOIN `arbs_usd_swap_manual_links_v2` and project `manual_link_id`,
`manual_package_id`, `link_created_by`, `link_created_at`, `user_comment`,
`link_reason`, `tags` onto each row.

If the JOIN is already present (verify), this phase reduces to a test pinning the
projection.

### 1.6 Out of swaptions scope

Swaptions-tape's `forcedPackageIds` / `assumed_incomplete_straddle` machinery is
straddle-specific (manually flag a single-leg row as "this is half of an
incomplete straddle"). Not relevant to USD swaps; stays inside swaptions-tape —
not extracted, not adopted in v2.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  lib/manual-links-ui/                                            │
│    color · predicates · grouping                                 │
│    components: Badge · DetailModal · Validation · Metrics · Hist │
│    hooks: useManualLinkDetails · useManualLinkForm               │
│    api: manualLinkApi                                            │
│    types: ManualLinkDetail · ManualLinkTrade · ManualLinkHistory │
└──────────────┬─────────────────────────────────────┬─────────────┘
               │                                     │
       ┌───────┴───────┐                  ┌──────────┴───────────┐
       │  swaptions-   │                  │  usd-swaps-tape-v2   │
       │  tape         │                  │                      │
       │  (refactored, │                  │  (adopts shared mod) │
       │   no behavior │                  │                      │
       │   change)     │                  │                      │
       └───────────────┘                  └──────────────────────┘
                              │
                              ▼
                   /api/{...}/links/* (sofr re-exports)
                              │
                              ▼
                arbs_usd_swap_manual_links_v2
                arbs_manual_link_history_v1
```

### 2.1 New / modified files (preview)

**New (shared module).**
- All files under `SDRUtils/dashboard/src/lib/manual-links-ui/`

**Modified.**
- `SDRUtils/dashboard/src/features/swaptions-tape/components/SwaptionTradeTape.tsx` — import shared module; delete duplicates.
- `SDRUtils/dashboard/src/features/swaptions-tape/hooks/useManualLinks.ts` — re-export from shared module (or delete + re-import at call sites).
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useManualLinks.ts` — replace with shared `useManualLinkForm`.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/ManualLinksDialog.tsx` — replace shell with shared modal.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx` — wire `<ManualLinkBadge>` into Pkg column.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx` — apply `groupLinkedRows`.
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts` — verify / extend tape JOIN.

**Deleted.**
- Swaptions-internal duplicates of `manualLinkColor`, `isManualPackage`, `groupLinkedRows`, badge component, detail modal, manual-link form hook (after extraction + import wiring).

---

## 3. Constraints satisfied

| Constraint | How |
|---|---|
| Swaptions UX unchanged | Phase A is pure structural extraction; tests pin behavior. |
| v2 single-row UX preserved | All v2 changes are additive (badges, modal, richer hook). The "click row → analytics dock opens" flow is untouched. |
| Existing tests stay green | Swaptions test suite must remain green throughout extraction. v2 tests for the current minimal flow are extended (not replaced) to cover new badge / modal / state-machine behavior. |
| API stable | No new routes; existing re-exports verified; tape JOIN verified or extended. |
| Forced-straddle code stays in swaptions | Not extracted, not touched by v2. |
| Manual-link metadata on every row | Tape JOIN audit (Phase F) ensures consumer features see the metadata as-of every row fetch. |

---

## 4. Test plan

User direction: "be very comprehensive in front end testing".

### 4.1 Unit / integration

**Shared module (new).**
- `color.test.ts` — same input → same colour across runs; uniform distribution across N=1000 sample link IDs.
- `predicates.test.ts` — `isManualPackage` true/false for fixtures with / without `manual_link_id`, `manual_package_id`, `package_source`.
- `grouping.test.ts` — clusters rows by `manual_package_id` then `manual_link_id`; preserves source order within group; ungrouped rows pass through.
- `ManualLinkBadge.test.tsx` — renders dot + label + linkId; click handler fires; colour matches `manualLinkColor(linkId)`; connector lines render when between rows.
- `ManualLinkDetailModal.test.tsx` — read mode shows link + trades + history; edit mode shows form; edit submit fires PATCH; deactivate fires DELETE; admin-password gate works; auto-validation on open.
- `ManualLinkValidationList.test.tsx` — renders validation items; warning / info / error styling.
- `ManualLinkMetricsTable.test.tsx` — renders computed metrics rows.
- `ManualLinkHistoryTable.test.tsx` — renders history rows in chronological order; previous-state diff if available.
- `useManualLinkDetails.test.ts` — fetches link; resolves link + trades + history; loading + error states.
- `useManualLinkForm.test.ts` — auto-validate on open; validate-only POST; create POST; PATCH; DELETE; tag add / remove; reset on close; admin-password reset between operations.
- `manualLinkApi.test.ts` — request shapes, header construction, error parsing.

**Swaptions refactor (regression-only).**
- Existing swaptions test suite — must pass byte-for-byte after extraction. No new tests required, but every test that touched the moved files is verified green at each phase commit.

**v2 adoption.**
- `columns.test.tsx` — Pkg column renders `<ManualLinkBadge>` when `isManualPackage(row)` is true.
- `UsdSwapsTradeTape.test.tsx` — `groupLinkedRows` applied; linked rows cluster; manual link metadata reaches the row.
- `useManualLinks.test.ts` (v2) — replaced surface re-exports `useManualLinkForm` correctly.
- `ManualLinksDialog.test.tsx` (v2) — opens with auto-validation; renders validation items + metrics; create / edit / deactivate paths; admin-password prompt for PATCH/DELETE only.
- `route.logic.test.ts` — tape JOIN projects manual link fields onto each row.

### 4.2 Comprehensive E2E (dev server)

`PORT=3001 npx next dev`:

1. Navigate `/usd-swaps`. No row badges yet (no manual links in test data).
2. Open ManualLinksDialog (toolbar button), select 2 rows. Auto-validate fires on open. Validation items + metrics render.
3. Submit create → success. Both rows now show `<ManualLinkBadge>` with the same colour.
4. `groupLinkedRows` clusters them visually.
5. Click badge → detail modal opens (read mode). Shows link record, linked trades, empty history.
6. Switch to edit mode → admin password prompt → enter → form editable.
7. Edit comment → submit PATCH → modal updates → history table now has 1 entry.
8. Add a third trade via edit → PATCH → modal updates → history table 2 entries.
9. Remove that third trade via edit → PATCH → modal updates → history 3 entries.
10. Click deactivate → admin password → DELETE fires → modal closes → row badges disappear.
11. Refresh → confirm DB state via re-open: link is `is_active=FALSE`.
12. Refresh page → previously-created link no longer renders badges (deactivated).

### 4.3 Regression

**Swaptions.** Walk the swaptions tape: row badges, group clustering, detail modal,
edit, deactivate, validation, force-straddle (out of scope but must still work).
Snapshot diff vs pre-change. Manual smoke test of every modal action.

**v2.** Walk every existing v2 feature: package-confidence detail panel, analytics
dock single-row mode (post-WS2 multi-mode if landed), four PR-#286 cards (post-WS2
if mounted), pagination + filters, polling, manual-link create-only path (still
works as pre-revamp lower bound).

---

## 5. Build sequence

One PR; phases sequence within.

- **Phase A — Shared-module skeleton + pure-function extraction.**
  - A1. `lib/manual-links-ui/color.ts` extracted from swaptions; tests; swaptions imports.
  - A2. `lib/manual-links-ui/predicates.ts` + `grouping.ts` extracted; tests; swaptions imports.
  - A3. `lib/manual-links-ui/types.ts` consolidated from swaptions / sofr; types unified.
  - **Gate.** Full swaptions test suite green.
- **Phase B — Component extraction.**
  - B1. `<ManualLinkBadge>` extracted; swaptions imports; render tests.
  - B2. `<ManualLinkValidationList>`, `<ManualLinkMetricsTable>`, `<ManualLinkHistoryTable>` sub-components extracted.
  - B3. `<ManualLinkDetailModal>` shell extracted; swaptions imports; tests.
  - **Gate.** Full swaptions test suite green.
- **Phase C — Hook extraction.**
  - C1. `manualLinkApi` typed wrapper.
  - C2. `useManualLinkDetails` extracted; swaptions imports; tests.
  - C3. `useManualLinkForm` extracted; swaptions imports; tests.
  - **Gate.** Full swaptions test suite green; manual smoke test of swaptions modal flow.
- **Phase D — v2 adoption (UI primitives).**
  - D1. v2 `columns.tsx` wires `<ManualLinkBadge>`.
  - D2. v2 row grouping via `groupLinkedRows`.
- **Phase E — v2 adoption (modal + state machine).**
  - E1. v2 `useManualLinks` replaced with `useManualLinkForm`.
  - E2. v2 `ManualLinksDialog` replaced with `<ManualLinkDetailModal>` + create flow.
  - E3. Edit + deactivate flows wired.
- **Phase F — API + tape JOIN audit.**
  - F1. Verify all six endpoints reachable from v2 paths; add re-exports if missing.
  - F2. Verify `route.logic.ts` LEFT JOINs manual links table; extend if missing; pin in `route.logic.test.ts`.
- **Verification — full E2E** (§4.2) + regression (§4.3).
- **Open PR.**

---

## 6. Out of scope

- **Real-time WebSocket updates** when a link is created / edited elsewhere. Not currently implemented; not added by this revamp.
- **Forced-straddle / `assumed_incomplete_straddle`** — swaptions-specific, stays in swaptions.
- **Schema changes.** No DB migrations expected; the existing `arbs_usd_swap_manual_links_v2` + `arbs_manual_link_history_v1` tables already host all needed fields.
- **Sofr-tape adoption.** The legacy sofr-swaps-tape consumer is out of scope for this revamp; it can adopt the shared module in a follow-up if desired.
- **Admin-password UX upgrade.** Current single-prompt pattern preserved; richer auth (session-cached, OAuth) is its own workstream.
- **Conflict-detection policy change.** The API's existing conflict detection (preventing the same trade from belonging to multiple active links) is preserved as-is.

---

## 7. Risks

1. **Swaptions extraction regression.** The riskiest phase. Mitigation: phase A is broken into 3 sub-commits; full swaptions test suite must pass between each; manual smoke before phase D begins.
2. **Detail modal divergence over time.** With one component used by two features, future feature requests in one consumer might bloat the shared component. Mitigation: keep the modal feature-flag- and option-prop-driven so per-consumer customisation is local; document the contract in `lib/manual-links-ui/components/ManualLinkDetailModal.tsx` ABOUTME.
3. **Tape JOIN performance.** Adding LEFT JOIN to the v2 tape query may add latency. Mitigation: index on `arbs_usd_swap_manual_links_v2.linked_trade_ids` (likely already exists per swaptions usage); benchmark before merge.
4. **Admin-password gate UX.** Trader UX may dislike re-entering the password for every PATCH. Mitigation: matches existing swaptions behavior (consistency); session-cached password is a separate UX workstream.
5. **Colour collision at scale.** Hash-based colours will collide for ~1 in 256 link IDs visually. Mitigation: matches existing swaptions behavior; acceptable; visual disambiguation comes from the link-ID label and package-ID alongside the dot.
6. **Type unification across swaptions / sofr / v2.** Shared module types must accept all three consumers' field expectations. Mitigation: types built up from intersection of consumer needs in `types.ts`; consumer-specific extensions live in consumer modules.

---

## 8. Rollback

Phase commits are individually revertible:

- Phase F: tape JOIN revert restores pre-existing JOIN state (which may be no JOIN — fine, badges then don't render in v2 but swaptions remains green).
- Phase E: v2 reverts to current minimal `useManualLinks` + `ManualLinksDialog`.
- Phase D: v2 columns lose badges; `<ManualLinkBadge>` still exists in shared module, unused by v2.
- Phase C: hooks reverted; swaptions reverts to internal hooks.
- Phase B: component extraction reverted; swaptions reverts to internal components.
- Phase A: pure-function extraction reverted; swaptions reverts to internal functions.

A full revert leaves swaptions and v2 in their pre-PR state. The shared module is
deleted entirely.
