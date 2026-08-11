# Bugs found in shared code while building R0.

Logged, not fixed. Fixing shared code mid-flight on this branch would couple
R0 to the ladder work, which is exactly what the isolation rule forbids.

---

## `arbs_usd_swap_tape_legs_v3.forward_bucket` is a catch-all, not a bucket

Found while choosing a forward-start key for the R0 tape-internal mid.
**Measured** over the R0 filter set (2026-05-01..2026-08-07, `ECONOMIC_FLOW`,
`contributes_to_flow`, SOFR/FED_FUNDS, non-null fixed rate), grouping
`forward_bucket` against the `forward_start_years` it is supposed to summarise:

| forward_bucket | n | min fwd_start_years | max | median |
|---|---|---|---|---|
| spot | 175,732 | 0.000000 | 0.019178 | 0.000000 |
| **3Y+** | **106,013** | **0.021918** | **35.032877** | **0.224658** |
| 2M | 2,261 | 0.153425 | 0.178082 | 0.167123 |
| 1M | 2,180 | 0.076712 | 0.095890 | 0.093151 |
| 3M | 1,690 | 0.238356 | 0.263014 | 0.254795 |
| 1Y | 1,277 | 0.986301 | 1.041096 | 1.005479 |
| 2W | 912 | 0.035616 | 0.043836 | 0.038356 |
| 2Y | 869 | 1.958904 | 2.041096 | 2.010959 |
| 6M | 598 | 0.487671 | 0.512329 | 0.506849 |
| 1W | 583 | 0.021918 | 0.024658 | 0.021918 |
| 9M | 413 | 0.736986 | 0.761644 | 0.753425 |

Every narrow label is tight and correct. `3Y+` is not: it spans
**0.0219 to 35.03 years with a median of 0.2247 years (~3 months)**, and absorbs
**36% of all rows**. It is evidently the default arm of the classifier catching
anything that does not match one of the exact labels, rather than "forward start of
3 years or more".

Consequences for anyone using it:
* `forward_bucket = '3Y+'` does **not** select long-forward trades. The typical
  member starts in about three months.
* Any aggregation keyed on `forward_bucket` silently pools spot-adjacent
  1-week-forward trades with 35-year-forward trades.
* Cross-check: `forward_start_years > 1` matches only 22,526 rows, while
  `forward_bucket = '3Y+'` matches 106,013 — a 4.7x disagreement on the same rows.

R0 does not use the column; it derives its forward key from `forward_start_years`
directly (see `r0_deviations.md` §3c).
