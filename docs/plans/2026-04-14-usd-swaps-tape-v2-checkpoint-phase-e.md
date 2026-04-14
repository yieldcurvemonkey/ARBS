# Phase E Checkpoint — USD Swap Tape v2

Tasks 33–35 complete. Components shipped:
- `CleanTapeToggle.tsx`, `FlagChips.tsx`
- `TradeTapeHeader.tsx` + `TradeTapeHeader.helpers.ts`
- `FilterChips.tsx`, `TradeTapeFilters.tsx`

URL round-trip is tested indirectly through the hook tests (Phase C —
useFlagFilters exercises parseCsvSet/csvFromSet and the lifecycle ↔
query-string mapping). The manual round-trip walkthrough from the
plan requires a running dev server + DB and will be performed by
the maintainer.
