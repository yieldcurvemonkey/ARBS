# Phase G Checkpoint — USD Swap Tape v2

Tasks 44–48 complete. All 48 tasks shipped.

## Components shipped in Phase G

- `UsdSwapsMethodologyModal.tsx` — tape methodology dialog.
- `Sidecars/SidecarDrawer.tsx` — tabbed host for the three drawer sidecars.
- `UsdSwapsTradeTape.tsx` — main orchestrator (226 lines, well under the
  plan's 900-line cap) wiring the header, filters, table, sidecars, and
  modals together.
- `app/usd-swaps-v2/page.tsx` — parallel route during the soak window,
  now a redirect shim after cutover.
- `app/usd-swaps/page.tsx` — cutover to v2 import + legacy banner
  removed in favour of the new tape.
- `__tests__/e2e/usd-swaps-v2.e2e.ts` — Puppeteer suite gated on
  `E2E_BASE_URL`.

## Final test run

**Python** — `pytest tests/test_ingest_usdswaps_tape_schema.py tests/test_ingest_usdswaps_tape_writepath.py tests/test_trade_tape_on_fixture.py -v`

- 11 passing, 7 skipped (DB-gated).

**Dashboard** — `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`

- 82 passing, 4 skipped (DB-gated integration + E2E).

**Manual QA** remaining for the maintainer (needs DATABASE_URL):

- `python -m SDRUtils._swappulse_scripts.ingest_usdswaps_tape --start-date YYYY-MM-DD --end-date YYYY-MM-DD`
- `cd SDRUtils/dashboard && npm run dev` and walk through the UAT
  checklist in design doc §12.4.
- `E2E_BASE_URL=http://localhost:3000 npm test -- --testPathPatterns=e2e`.

## Cleanup (separate PR)

Per plan §10 / task 48 explicitly excludes:
- deleting `features/sofr-swaps-tape/`
- deleting `features/usd-swaps-tape/`
- deleting `/api/sofr-swaps-tape/`
- deleting `/api/usd-swaps-tape/`

These remain untouched in this PR and will be landed as a follow-up.
