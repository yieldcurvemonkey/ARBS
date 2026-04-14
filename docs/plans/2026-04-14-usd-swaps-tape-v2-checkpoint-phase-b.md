# Phase B Checkpoint — USD Swap Tape v2

**Scope:** Tasks 7–16 complete. Eight API routes under
`/api/usd-swaps-tape-v2/` plus the shared lib resolver.

## Routes shipped

| Route | Shape |
|---|---|
| `GET /api/usd-swaps-tape-v2` | cursor-paginated enriched rows |
| `GET /api/usd-swaps-tape-v2/risk-concentration` | `{ groups: [...] }` |
| `GET /api/usd-swaps-tape-v2/packages` | `{ packages: [...] }` |
| `GET /api/usd-swaps-tape-v2/fomc-clusters` | `{ meetings: [...] }` |
| `GET /api/usd-swaps-tape-v2/clusters` | `{ clusters: [...] }` |
| `GET /api/usd-swaps-tape-v2/flow-history` | `{ days, meta }` |
| `GET /api/usd-swaps-tape-v2/timeseries` | `{ rows, points, count, truncated }` |
| `{GET,POST} /api/usd-swaps-tape-v2/links` + `/[linkId]` | re-export of `/api/usd-swap/links` |

## Automated tests

`cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`

- 31 Jest tests passing.
- 4 DB-backed integration tests skip when PG_TEST_URL / DATABASE_URL
  is unset.

## Manual curl smoke (deferred)

The plan's Phase B checkpoint runs `curl` against each endpoint on a
running `npm run dev` server. That requires DATABASE_URL + a running
dashboard. Will be executed by the maintainer in their dev
environment before PR review.

## Next

Proceed to Phase C (Frontend types + hooks).
