# Rebuilt UST futures basis panels — evidence for the 2026-08-15 repair (round 2)

The panels behind the pass-rate tables in
`docs/superpowers/specs/2026-08-15-ustf-data-layer-round-2.md`. Committed so the report's numbers
can be audited without rerunning a multi-hour build.

**Six roots, not three.** TU, FV and UXY had never been panel-tested at all — UXY had never had a
single basis report in the store — and US, TY and WN are rebuilt because the delivery-date fix
changes every one of their rows.

Produced by:

```
python -m MDP.USTFutures.rebuild_basis_panels \
    --roots TU FV UXY US TY WN --start 2018-06-01 --end 2026-08-13 \
    --out-dir <dir> --sample-every 5 --fresh
```

* Roots are INTERNAL: `TU` 2-year (ZT), `FV` 5-year (ZF), `TY` 10-year (ZN), `UXY` Ultra 10-year
  (TN), `US` classic bond (ZB), `WN` Ultra Bond (UD — **not** BarChart's UB, which is EUR/NOK).
* `--sample-every 5` → every 5th business day, ~50 rows per root per year.
* `--fresh` is not optional here: resuming onto a panel built by the previous code would carry rows
  computed against the IMM-date delivery into a "rebuilt" one.

## What differs from `2026-08-14-ustf-panels/`

Those three panels are kept alongside these, because the comparison is part of the evidence.

1. **The delivery date.** `RLUSTFuturePricer._resolve_delivery` fell back to the contract's IMM date
   — the third Wednesday — where a Treasury future delivers across the business days of the delivery
   month. `_build_basis_report_frame` calls that fallback directly, so every row was carried to the
   wrong day. Measured on US over all 410 overlapping rows: min net basis moves a **median
   −1.23/32** (mean −1.93, range −6.51 … +1.53), while the deliverable count is **unchanged on all
   410 rows** and the futures price is **identical on 100%** — only the carry moved, which is the
   check that the change is what it claims to be.
2. **Good Friday.** The SOFR series carries an explicit NaN on non-publication days, and
   `_resolve_repo_rate` took `.iloc[-1]` of a slice ending there — so every Good Friday, on every
   root, had a NaN repo rate and therefore a NaN net basis, and failed the gate. Five dates per root
   across the sample.
3. **The TU/FV deliverable grade** now implements CBOT's re-opening clause, so a 7-year note
   reopened as a 5-year is deliverable (validated against CME's published conversion-factor file:
   `ZTH25` 11/11, `ZFH25` 10/10, factors to 4dp).

`_BASIS_REPORT_SCHEMA_VERSION` went 3 → 4 and `contract_specs_fingerprint()` changed, so nothing
built by the older code can be served and this rebuild started from a cold store for every row.

## Reading the columns

* `repo_pct` is the overnight SOFR fixing **at the reference date**, not a term financing rate — the
  same deviation the 2026-08-14 README records, and still the likeliest source of the residual
  `USH22` flags (a CTD on special is funded far below the overnight fixing).
* `data_ok` / `data_quality_reason` come from the shared gate in
  `MDP/USTFutures/basis_report_quality.py` — net basis and implied repo, never gross basis.
* `n_deliverable` of 2–3 for UXY is **correct**, not a truncated basket: the Ultra 10-year grade is a
  seven-month window (9y5m–10y remaining), and CME's own prose describes the contract as "the three
  most recently issued 10-Year notes".

To regenerate the table:

```
python -m MDP.USTFutures.rebuild_basis_panels --table-only --roots TU FV UXY US TY WN --out-dir <this dir>
```
