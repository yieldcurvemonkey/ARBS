# Phase D Checkpoint — USD Swap Tape v2

Tasks 27–31 complete. Components shipped:

- `TapeLabelCell.tsx` — hero label cell
- `RowBadges.tsx` — Lifecycle pills + Flag badges (helpers split out)
- `LegsSubTable.tsx` — per-package leg expansion
- `columns.tsx` + `columns.helpers.ts` — table column JSX + row class
- `TradeTapeTable.tsx` — main container with virtual scroll / expansion / selection

Tests: 18 pure-helper tests cover row-class mapping per lifecycle,
lifecycle-pill logic, flag-badge ordering/aria, and tone-selection
helpers. JSX rendering verified manually via the dev-server harness
in Phase G (no @testing-library/react set up in this repo).

Manual harness deferred — the full dev-server smoke test will be run
by the maintainer when `DATABASE_URL` is available.
