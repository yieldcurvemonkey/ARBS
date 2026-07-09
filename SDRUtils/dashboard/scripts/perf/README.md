# Tape display-view perf guards

Read-only benchmarks for the USD swaps tape display view (`arbs_usd_swap_tape_display_v2`),
used to guard the manual-regrouping feature's read-path against regression. They mirror
`src/lib/db.ts` connection resolution (`DATABASE_URL` → `SWAPPULSE_DB_*` ladder), loading
`.env.local`/`.env` from the dashboard root. **SELECT / EXPLAIN only — no writes.**

Run from anywhere (paths are relative):

```
node SDRUtils/dashboard/scripts/perf/bench_tape_view.js
node SDRUtils/dashboard/scripts/perf/bench_override_join.js
```

## What they measure & the pass/fail budget

**`bench_tape_view.js`** — baseline per-page (LIMIT 200) latency across history percentiles,
plus an `EXPLAIN (ANALYZE)` attributing the LATERAL leg-aggregation cost.
- **Budget:** warm p50 per page should stay ~55–80ms and be **flat across history**
  (deep pages within ~1.3× of recent pages). The outer scan MUST use
  `idx_tape_v2_packages_exec_start`. A deep page materially slower than a recent page, or a
  seq-scan on packages, is a regression.

**`bench_override_join.js`** — simulates N active-override member trades and compares the
baseline page vs. the override-resolving page shape (members index-probe + sparse `override_map`).
- **Budget:** with a generous 800 active-override member trades, the override resolution should
  add **≤ ~15% server-side** (measured +13%) and **preserve** (a) the `idx_tape_v2_packages_exec_start`
  index scan on the outer package scan and (b) package cardinality (no re-carve). Regressions to
  watch (all previously observed and fixed): a correlated per-package CTE (+130%), an unindexed
  override set forcing a merge-join re-scan (+50–78%), or rewriting every leg's `jsonb` (+65–78%).

## Measured baseline (prod, 2026-07-08)

1.30M packages / 1.65M legs / 1.26 legs/pkg, Nov 2024→Jul 2026. Per-page warm p50 ~59ms (server
~30ms), flat across history via the `execution_start DESC NULLS LAST` index. Override resolution
via the indexed `arbs_usd_swap_tape_override_members_v2` probe: **+13% server** at 800 active
members, index + cardinality preserved. Materialization was evaluated and **not** warranted.
