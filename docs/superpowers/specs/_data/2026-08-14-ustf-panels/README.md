# Rebuilt UST futures basis panels — evidence for the 2026-08-14 data-layer repair

These are the panels behind the pass-rate tables in
`docs/superpowers/specs/2026-08-14-ustf-data-layer-report.md`. They are committed (168 KB total)
so the report's numbers can be audited without rerunning a multi-hour rebuild.

Produced by:

```
python -m MDP.USTFutures.rebuild_basis_panels \
    --roots US TY WN --start 2018-06-01 --end 2026-08-13 \
    --out-dir <dir> --sample-every 5
```

* Roots are INTERNAL: `US` = classic bond (ZB), `TY` = 10-year note (ZN), `WN` = Ultra Bond (UB).
* `--sample-every 5` → every 5th business day, ~50 rows per root per year.
* `repo_pct` is the overnight SOFR fixing **at the reference date** (the defect-4 fix), not a term
  financing rate. The original panels used a term rate from a module that lives only on the PR #454
  branch, so the two are not identical inputs; the report says so.
* `data_ok` / `data_quality_reason` come from the shared gate in
  `MDP/USTFutures/basis_report_quality.py` — net basis and implied repo, never gross basis.

To regenerate the comparison table:

```
python -m MDP.USTFutures.rebuild_basis_panels --table-only --roots US TY WN --out-dir <this dir>
```

The "before" side of the report's tables is the ORIGINAL panels at
`ARBS-bvv/notebooks/backtests/basis_vs_vol/_data/basis_panel_{ZB,ZN,UB}.parquet` (branch
`feat/basis-vs-vol`, gitignored there), whose `data_ok` used the old gross-basis rule
`abs(min_gross32) < 32`. Those are not copied here — they belong to that branch.
