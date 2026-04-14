# Phase C Checkpoint — USD Swap Tape v2

Tasks 18–25 complete.

Hooks shipped:
- useTradeTapeData (cursor + poll + upsert + flag-filter serialization)
- useColumnFilters, useFlagFilters (URL-synced)
- useRowExpansion, useRowSelection, useSavedUser
- useManualLinks (wraps /links POST/PATCH/DELETE)
- useTimeseriesData, useSidecarFetch
- useRiskConcentration, usePackageBrowser, useFomcClusters, useTemporalClusters

Types: trade / filter / chart / link / sidecar. Constants: palette,
column defs, poll interval.

Formatters: notional, DV01, rate, rate-range, tenor, time,
cluster-suffix — with 16 unit tests.

`cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`
→ 55 tests pass, 4 skipped (DB integration).
