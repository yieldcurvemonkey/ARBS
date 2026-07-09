# Task 14 Report — `OverrideCommitPopover`

## STATUS: DONE

## Commit
`812cadaa` — `feat(tape): add OverrideCommitPopover (validate+commit via overrideApi)`
(branch `feat/usd-swaps-tape-manual-regrouping`)

Files added:
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/OverrideCommitPopover.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/__tests__/OverrideCommitPopover.test.tsx`

## What was done

Followed TDD per the brief: wrote the verbatim test file first, confirmed it FAILed
(`Cannot find module '../OverrideCommitPopover'`), then wrote the verbatim implementation
from `task-14-brief.md`, re-ran, fixed two issues (see Deviations below), and reached green.

`OverrideCommitPopover` renders a `BucketOverridesPopover`-style chrome panel (`absolute
right-0 top-full` positioned, `border-slate-700 bg-slate-900`, mono `text-[10px]`/`[10.5px]`
labels/buttons). Props match the spec exactly:
`{ overrideType, tradeIds, manualPackageId?, user, onUserChange?, password, onPasswordChange,
onSuccess, onCancel }`. `password`/`user` are controlled (persisted by the orchestrator per the
handoff notes). Fields: Reason (text input, `aria-label="Reason"`), Tags (comma-separated,
split/trimmed/filtered on build), User (read-only unless `onUserChange` supplied), Override
password (`type="password"`). "Validate" button calls `overrideApi.validateOverride` with
`validate_only: true` and renders returned `OverrideValidationItem[]` color-coded by level
(error=rose, warning=amber, info=slate). "Commit" calls `overrideApi.createOverride` and on
success invokes `onSuccess(result)`; disabled while busy, while any validation item has
`level === 'error'`, or while `password` is empty. Both actions catch and render errors inline
via `role="alert"` (no toast lib). "Cancel" (✕, `aria-label="Cancel"`) invokes `onCancel`.

## Deviations from the brief's verbatim snippets (both required to reach green; documented per
"full authority to resolve ambiguity")

1. **Implementation bug fix**: the brief's verbatim `buildBody` set `validate_only: validateOnly`
   unconditionally, so a commit body serialized `"validate_only":false`. The brief's own verbatim
   test (`Commit calls createOverride and fires onSuccess`) asserts
   `expect(sent.validate_only).toBeUndefined()` after JSON round-trip — which requires the key to
   be *omitted*, not `false`. Changed to `validate_only: validateOnly ? true : undefined` (matches
   `overrideApi.validateOverride`'s own convention of only ever setting the flag `true`). This is
   the only substantive line changed from the brief's given implementation.
2. **Test typing fix (type-annotation only)**: the brief's verbatim test declares
   `let fetchMock: jest.Mock` / `fetchMock = jest.fn()`, which fails `tsc --noEmit` with
   `TS2345: Argument of type 'any' is not assignable to parameter of type 'never'` at each
   `fetchMock.mockResolvedValue(...)` call site (untyped `jest.fn()` infers a `never`-parameter
   mock under this repo's jest/ts-jest ESM config). Found the exact established fix already used
   in this repo's own `api/__tests__/overrideApi.test.ts`: `let fetchMock: jest.Mock<any>` and
   `fetchMock = jest.fn() as jest.Mock<any>`. Applied the identical pattern — zero behavioral
   change, matches sibling test file precedent exactly.

No other deviations. Styling, prop shape, button labels/roles, and validation/error rendering all
match the brief verbatim.

## Verification

- `npm test -- src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/__tests__/OverrideCommitPopover.test.tsx`
  → **6/6 PASS** (renders header; Validate hits `validateOverride` with `validate_only:true` and
  shows messages; Commit hits `createOverride`, fires `onSuccess` with `override_id`, and omits
  `validate_only` from the sent body; 403 API error renders inline via `role="alert"` and does NOT
  fire `onSuccess`; a validation-level `error` disables Commit; Cancel fires `onCancel`).
- `cd SDRUtils/dashboard && npx tsc --noEmit` → **0 errors**.
- Confirmed via `git status --short SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/OverrideCommitPopover/`
  that only the two new files existed before staging (isolated `git add` by explicit path — no
  `-A`/`.`; unrelated WIP in `package.json`/lock/other tape files left untouched).
- `git show --stat HEAD` confirms the commit contains exactly the two new files; trailers present
  verbatim.

## Concerns

- None blocking. The `validate_only` fix is a small, well-justified deviation from the brief's
  literal implementation snippet, required by the brief's own literal test snippet — flagging for
  awareness in case task 15+ integration assumed the original (buggy) shape.
- This component's `NOTE` action is explicitly out of scope (owned by another section per the
  brief's handoff notes) — not implemented here, as expected.
- Not yet wired into `RegroupActionBar`/orchestrator (that's Tasks 15–20 per the handoff notes in
  the brief) — this task delivers the standalone component + tests only, as scoped.
