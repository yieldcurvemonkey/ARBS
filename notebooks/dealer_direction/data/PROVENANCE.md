# `notebooks/dealer_direction/data/` — provenance

Every artefact the dealer-direction notebook loads rather than computes, with
enough of its history that a reader can tell **which is which**.

The notebook presents computed and loaded results side by side. The rule this
file exists to enforce:

> **A number the notebook prints is either recomputed in front of you, or it was
> loaded from a file listed below — and where a cell computes *on* a file listed
> below, its banner names that file. There is no fourth case.** Every loaded
> file has a `STATUS` line here. Cite this file next to the figure.

Three of those files are **not in this directory** — the s2 calibration pickle,
the notebook's stage cache and the tape's legs cache. They are large, they are
machine-local, and they are inputs all the same: **§7**. §7.1 in particular sets
`tau`, `b0` and the dead zone, and therefore `p` and every weight the notebook
prints.

Assembled 2026-08-12. Nothing in this directory was re-run; every file is a
byte-exact copy of an artefact produced earlier, or (one file, flagged
`DERIVED`) a mechanical parse of a committed markdown table.

---

## 0. Read this before comparing any two numbers

**There are three different sample windows in this directory.** They are not
interchangeable and several headline numbers differ only because of which one
they sit on.

| window | span | days | what runs on it |
|---|---|---|---|
| **U** universe / package | 2024-03-01 .. 2026-08-07 | 610 tape days | universe retention, exclusions, package-price recovery |
| **S** signal in-sample | 2024-03-01 .. 2025-08-31 | (hold-out 2025-09-01..2026-08-07 **not opened**) | S1, S2, `costs.csv` |
| **R** lead-lag intraday | X 2026-05-01 .. 2026-08-07 (68 UTC days); Y 2026-05-07 .. 2026-08-06 | **67** CME session dates (44 for `SFR_FF`) | R0, R0b |

Window **R** is ~3 months of minute data. It is *not* a subset of the 610-day
universe study in any usable sense, and "610 days" must never be attached to an
R0/R0b number.

### Status legend

| tag | meaning |
|---|---|
| `COPIED` | byte-exact copy of a file from another branch; the notebook **displays** it |
| `IN-TREE` | already committed on `feat/dealer-direction`; referenced **in place**, not duplicated here |
| `DERIVED` | produced here by parsing a committed document; the parse is validated, the numbers are not re-measured |
| `RETRACTED` / `SUPERSEDED` | the file contains at least one number that no longer stands — see §5 |

### Integrity of the copies

All 17 files in §1 were extracted with
`git show r0-leadlag:r0_leadlag/out/<f>` and verified with
`git hash-object --no-filters`, which reproduced the branch's blob SHA for
**17 of 17**. No re-encoding, no filters, no edits. The two files in §2 were
copied from untracked scratch and verified by `sha256sum`.

---

## 1. R0 / R0b lead-lag — `COPIED` from branch `r0-leadlag`

**Source branch** `r0-leadlag`, tip **`c97205bd`**
("r0b: FAIL — and R0's pre-print trough was an artifact of its own mid rule",
2026-08-11 18:43:37 -0400). The worktree was removed; the branch lives in the
shared object store of `C:\Users\chris\clee\ARBS-dd`.

**Run date: 2026-08-11. Both studies were run once, one specification each.**

**Producers** — `r0_leadlag/run_r0.py` (R0), `r0_leadlag/run_r0b.py` (R0b, which
*imports* R0's estimator functions rather than copying them, so the estimator
cannot drift), `r0_leadlag/run_d1.py` (the attenuation/downgrade measurement),
`r0_leadlag/run_r0b_attenuation.py`. X builders: `build_x_tape.py` (R0),
`build_x_r0b.py` (R0b). Y builder: `build_y_mbo.py`. Write-ups on the same
branch: `R0_RESULT.md`, `R0B_RESULT.md`, `ATTENUATION.md`, `IMPLICATIONS.md`,
`r0_prereg.md`, `r0_prereg_addendum_1.md`, `r0b_prereg.md`, `r0_deviations.md`,
`r0b_deviations.md`, `SHARED_BUGS.md`.

**What R0 and R0b differ by, and only by:** X's direction sign. R0 signs a print
against a *trailing median* mid; R0b signs it against a *real-time Citi
USD-SOFR-1D minute curve* par rate at the print's snapped execution minute. The
branch gates this: `build_x_r0b.py` re-derives R0's own X from the same frame and
reports `unmatched cells 0`, `max |d signed_dv01| = 0.000e+00`. Y, the grid, the
binning and the estimator are identical. **Any difference between `r0_*` and
`r0b_*` here is the mid rule and nothing else.**

### 1a. Verdicts

| file | bytes | contents | STATUS |
|---|---|---|---|
| `r0_verdict.txt` | 5 | `FAIL` | `COPIED` — displayed |
| `r0_d1_downgrade.txt` | 14 | `UNINFORMATIVE` | `COPIED` — displayed |
| `r0b_verdict.txt` | 5 | `FAIL` | `COPIED` — displayed |

**What they mean.** R0's *pre-registered decision rule* returns FAIL. The
addendum's downgrade rule (written before any beta was estimated, and able only
to soften a FAIL, never to create a PASS) then fired because the measured
attenuation of R0's direction proxy is `rho = 0.405`, below its 0.50 threshold,
in **all five** decision buckets — so R0 as reported is **UNINFORMATIVE**: the
premise is untested, not dead. R0b returns FAIL under the same rule and, unlike
R0, is *not* rescued by the power gate — it fails the informativeness gate for a
different reason, recorded in `r0b_gate.csv`.

**What they do not mean.** Neither `FAIL` is evidence that dealers do not hedge.
FAIL is defined as "mass concentrated at `k < 0`, **or** post-print mass
indistinguishable from zero" — an absence of measurable post-print response on
*this* proxy, on *this* 67-session window.

### 1b. Coefficient profiles (what the notebook re-plots)

| file | rows | grain | STATUS |
|---|---|---|---|
| `r0_betas.csv` | 732 | `clock, bucket, k, beta, se_cluster, se_nw` | `COPIED` — **plot from this, not the PNG** |
| `r0b_betas.csv` | 732 | same | `COPIED` — **plot from this, not the PNG** |

`k` runs −30..+30 minutes around the print; two clocks (`exec`, `diss`); six
scopes (`POOLED` + 5 buckets).

**Meaning.** `beta_k` is the coefficient on signed tape DV01 in bucket-minute
`t+k` of a regression whose left side is futures aggressor volume. Positive `k`
is *after* the print (the hedge channel the study was built to detect);
negative `k` is *before* it.

**What it does not mean.** These are **not** a hedge ratio, a P&L, or a tradable
edge. Nothing in R0/R0b was traded or costed.

> **`r0_betas.csv` carries a known artifact and is retained to show it.**
> R0's pre-print trough (`sum(beta_k, k<=-1) = -0.1075`, `t = -5.90`) was R0's
> only significant finding. R0b, changing only the mid rule, turns it into
> `+0.0159`, `t = +1.955` — *opposite sign, and insignificant under the
> governing day-clustered inference*. The two mid rules produce
> opposite-signed pre-print mass, so **the trough is an artifact of R0's own
> mid rule**. Plot `r0_betas.csv` only alongside `r0b_betas.csv`, and never as
> a standalone finding. (`r0b_sign_decomp.csv` decomposes which part of the
> mid rule does it.)

| file | bytes | STATUS |
|---|---|---|
| `r0_betas.png` | 339,176 | `COPIED` — **tie-out only, not for display** |
| `r0b_betas.png` | 413,764 | `COPIED` — **tie-out only, not for display** |

The original figures exactly as produced on the branch. They are kept so a
reader can check the notebook's re-plot against the artefact of record. The
notebook should **re-plot from the betas CSVs** — a re-plotted chart can be
inspected, re-scaled and re-coloured; an embedded PNG cannot.

### 1c. Summary tables

| file | rows | STATUS |
|---|---|---|
| `r0_table.csv` | 60 | `COPIED` — displayed |
| `r0b_table.csv` | 60 | `COPIED` — displayed |

Grain `clock × split × scope × bucket`. Carries `sum_beta_kneg`,
`sum_beta_kpos`, their day-clustered and Newey-West SEs and t's, the
`pos − neg` difference, `beta_k0`, `abs_ratio_pos_over_neg`,
`post_print_share`. `r0b_table.csv` adds `abs_beta_mass` /
`abs_beta_mass_null` (88% of R0b's whole `|beta_k|` profile is what pure noise
would produce).

**The decision row is `clock=diss, split=all, scope=pooled`** — the
pre-registration names the dissemination clock as governing. `exec` rows are
diagnostics. A reader who reads the `exec` row as the verdict will get R0b's
pre-print sum at `t = +2.56` rather than the governing `+1.955`.

**Day-clustered governs, not Newey-West.** R0b's pre-print sum is `t = +1.955`
day-clustered (below 1.96, *not* significant) and `+2.38` Newey-West. The
prereg fixed day-clustering in advance. Consoles that print "+1.96" are
rounding.

### 1d. Power, attenuation and the informativeness gate

| file | rows | STATUS |
|---|---|---|
| `attenuation.csv` | 6 | `COPIED` — displayed |
| `r0_d1_rho.csv` | 5 | `COPIED` — displayed |
| `r0b_dense_rho.csv` | 24 | `COPIED` — displayed |
| `r0b_gate.csv` | 6 | `COPIED` — displayed |
| `r0b_coverage.csv` | 6 | `COPIED` — displayed |
| `r0b_xcorr.csv` | 12 | `COPIED` — displayed |
| `r0b_sign_decomp.csv` | 3 | `COPIED` — displayed |
| `r0b_variance_decomp.csv` | 2 | `COPIED` — displayed |

- **`attenuation.csv`** — per-bucket `rho_print`, `rho_minute`, `rho_daily`,
  `sign_agreement`, `se_cluster_kpos`, `mde`, plus the pinned thresholds
  (`downgrade_threshold_rho = 0.5`, `downgrade_threshold_signagree = 0.6`) and
  the reference curve identity (`USD-SOFR-1D`, `citivelo_excel_rl`). Produced by
  `run_d1.py` / `run_r0b_attenuation.py`. Six rows: the five decision buckets
  (`scope = bucket`) plus a DV01-weighted `POOLED` row. **This is the file that
  fires the downgrade**: `rho_minute` is **0.317 (US) – 0.490 (TY_UXY)** across
  the five buckets, all below 0.50; the `POOLED` row is 0.4047, agreeing with
  `r0b_dense_rho.csv` to 2e-5. `rho` here is a **lower bound** on the proxy's
  correlation with the true direction; it does **not** say the tape direction is
  40% accurate in any everyday sense.
- **`r0_d1_rho.csv`** — the same measurement on D1's 12-tenor grid, the
  per-bucket detail behind the downgrade.
- **`r0b_dense_rho.csv`** — `rho` on three grids (D1's 12 tenors, R0b's 28
  tenors, the full regression grid). **The headline `rho = 0.405` is the
  `POOLED / rho_minute` cell on D1's 12-tenor grid** (0.404717). Different
  grids give 0.406 (28-tenor) and 0.883/0.481 (full grid, exec/diss); quoting
  the wrong row will silently change the story.
- **`r0b_gate.csv`** — `informative` is `False` in all six scopes. **This file
  carries R0b's headline exclusion interval.** Pooled:
  `sum_beta_kpos = -0.0011427`, `se_cluster_kpos = 0.0090139`,
  `mde = 0.0176672` (= 1.96·SE). The 95% interval on the post-print sum is
  therefore **(−0.01881, +0.01652)** — recompute it from this file rather than
  copying the number, so the reader sees it formed.
- **`r0b_coverage.csv`** — the signed-share collapse from R0's median rule to
  R0b's curve rule (`ALL`: 91.7% → 57.7% of DV01 signed). R0b signs *fewer*
  prints; that is the cost of the real-time mid, not a bug.
- **`r0b_xcorr.csv`** — cross-correlation of the two X series by clock/scope.
- **`r0b_sign_decomp.csv`** — attributes the sign difference to staleness vs
  cell bias. This is the mechanical account of *why* R0's trough was an
  artifact.
- **`r0b_variance_decomp.csv`** — predicted vs measured sign agreement
  (0.822 predicted, 0.676 measured). The gap is a model shortfall, not a
  measurement of the market.

---

## 2. Universe and package recovery — `COPIED` from untracked scratch

These two files were **untracked** (not committed anywhere). They are copied in
so the notebook has a durable, citable source for numbers that otherwise exist
only in prose.

### `universe_exclusions_610d.txt` — `COPIED`

- **Source**: `scratch/_rep_full.txt` (untracked, mtime 2026-08-11 12:25),
  sha256[0:16] `5e356c1ef4c1d701`.
- **Producer**: the report path of `SDRUtils/dealer_direction/universe.py`
  (`__main__`, `--report --start 2024-03-01 --end 2026-08-07`).
- **Window**: **U** — 2024-03-01 .. 2026-08-07, 610 tape days.
- **Carries**: units **1,437,838**; kept **1,082,393 (75.28%)**; DV01 proxy
  total 80,660,906,449, kept **45,941,783,080 (56.96%)**; the exclusion table by
  pinned constant, in which **`UNORIENTABLE_PKG` is 39.973637% of universe
  DV01** (of which `PKG-4+` 22.567462%, `SPREADOVER` 6.040688%,
  `MATCHED_MATURITY` 3.915588%, `INVOICE` 3.062897%).
- **Means**: how much of the tape the pinned convention can orient at all.
- **Does not mean**: a data-quality score. Most of the excluded DV01 is not bad
  data — it is flow whose direction is genuinely not identified by the tape
  (see §5).
- **Note**: the file's first seven lines are a rateslib licence notice on
  stderr, captured into the same stream. Skip them when parsing.

### `pkg_recovery_seam_SUPERSEDED.txt` — `COPIED`, **`SUPERSEDED`**

- **Source**: `scratch/_ddseam_coverage_out.txt` (untracked, mtime 2026-08-11
  19:39), sha256[0:16] `0f9ad952c9eda275`.
- **Producer**: `scratch/ddseam_coverage.py` — attribution confirmed by matching
  its literal `print` strings (`"retained, post-recovery"` at line 97,
  `"ladder-weightable"` at 113, `"the CRUDE gate"` at 89), not inferred from the
  filename. **Window**: **U**.
- **Carries the retracted 71.92%.** See §5.2. Retained *only* so the projection
  can be shown next to the measurement that replaced it. **Do not plot the
  71.92% as a current number.** The file itself already labels its own gate
  "the CRUDE gate … and an upper bound only: it asks whether a PTP exists, not
  whether it reconciles."
- It also carries a result that still stands and is worth keeping: even under
  the optimistic projection, **ladder-weightable DV01 goes 56.96% → 56.96%,
  +0.00 pp**, because `package_price` produces no `p`, so a recovered package
  never reaches the ladder at all.

### `bucket_retention_DERIVED.csv` — `DERIVED`

- **Not a measurement made here.** A mechanical parse of two committed markdown
  tables in `docs/dealer_direction/2026-08-11-package-exclusion-skew.md`
  (line 88 for columns 2–9; lines 108 and 109 for `retention_factor` and
  `vs_best_bucket`). The `source_md_line` column records this per row.
- **Producer of the parse**: `scratch/nbdata_work/extract_bucket_retention.py`
  (2026-08-12). Underlying measurement: `scratch/pkgskew_analyse.py` on
  window **U**.
- **Shape** 10 × 12, one row per tenor bucket.
- **The parse is validated against three relations it does not impose**:
  `retention_factor == 1 − excl_rate/100` (max deviation 0.00050, within the
  doc's 3 d.p. rounding); `vs_best_bucket == retention/0.761` (max deviation
  0.0043); and `retained_share == renormalised tape_share × retention` (max
  deviation 0.0142 pp). A mis-aligned column or a dropped bucket fails these.
- **Means**: what a ladder *level* in each bucket is multiplied by, relative to
  the tape. **0.761 at 0–1Y against 0.495 at 15–20Y — a 1.54× distortion.**
- **Does not mean**: that the ladder is wrong everywhere. **`z` is exactly
  invariant to a constant retention factor**, so `z` may be compared across
  buckets and **levels may not**. A notebook chart that puts two buckets' levels
  on one axis is making the error this table exists to forbid.

---

## 3. In-tree artefacts — `IN-TREE`, referenced in place, **not** duplicated

All committed on `feat/dealer-direction`. Load them from their real paths so
there is exactly one copy and no chance of a stale duplicate.

### `scratch/ppfix_results.txt` — commit `dba6d234` (2026-08-11)

- **Producers**: `scratch/ppfix_measure.py` (the 610-day report) and
  `scratch/ppfix_known_answer.py` (the CURVE/FLY known-answer test).
  Run 2026-08-11. **Window U.**
- **The standing package-recovery numbers live here.** Gating on identification
  takes retention to **57.89%**; **64.22%** of `PKG-4+` DV01 is
  `PKG_SIGNS_AMBIGUOUS`; ambiguity rises **61.45% → 97.25%** from four legs to
  eight-or-more; match rate rises **45.45% → 99.17%** across identification-margin
  bands and is **flat** across tie-out bands (95.65 / 88.54 / 97.75 / 96.92 /
  98.02) — which is the whole argument for gating on the margin rather than the
  tie-out.
- **Means**: how much tape DV01 can be *oriented with a defensible sign*.
- **Does not mean**: that the remaining 42% is unusable data. "Unidentifiable"
  here is a precise claim — several mutually inconsistent sign vectors fit
  inside the same tolerance — not a claim about noise.
- Also carries the **72.40%** "retention if ambiguity is ignored" figure. That
  is not the standing number and is not the same computation as the 71.92% in
  §2. See §5.2.

### `BT/dd_signals/out/` — all commit `c0b7d0f0` (2026-08-11), window **S**

| path | producer | STATUS |
|---|---|---|
| `s1_results.csv` (140 rows) | `BT/dd_signals/s1_spread_flow.py` | `IN-TREE` — **`RETRACTED` columns, see §5.3** |
| `s1_population.csv` (14) | same | `IN-TREE` |
| `s1_oracle_ceiling.csv` (70) | same | `IN-TREE` |
| `s1_plumbing.txt` | same | `IN-TREE` |
| `s1_validate.txt` | same | `IN-TREE` |
| `s2_results.csv` (13) | `BT/dd_signals/s2_positioning.py` | `IN-TREE` — **`RETRACTED` claim, see §5.4** |
| `s2_panel.parquet` (206 KB) | same | `IN-TREE` — the notebook **may recompute** from this |
| `s2_panel_description.csv` (10) | same | `IN-TREE` |
| `s2_z_cross_correlation.csv` (10) | same | `IN-TREE` |
| `s2_validate.txt` | same | `IN-TREE` |
| `costs.csv` (47) | `BT/dd_signals/measure_costs.py` | `IN-TREE` |

**`s1_results.csv`.** Grain `spec × tenor × venue × k`; `spec ∈ {primary,
placebo}`. **The S1 headline is the 35 `primary × D2C` cells (7 tenors × 5
horizons).** In those: zero significant cells on either β or edge; largest
`|beta_t|` **1.6551** against size-corrected criticals **2.5124–2.6309**; the
realised edge is below the cell's own cost hurdle in **35 of 35**. The quoted
"0.117 bp/trade against 0.659, 5.6× short" is the **10Y D2C** cell at `k=3`
(edges by `k`: 0.000, 0.031, 0.117, 0.045, 0.084; hurdle
`kill_ceiling_bps = 0.6594`). *It is not the maximum over all 35 cells* — that
is 0.174 bp at 20Y `k=5` against its own 1.332 bp hurdle, 7.7× short. Either
reading gives DEAD; do not present 0.117 as the best cell anywhere.
**Column trap**: `mde_bps` is the MDE in bp and `mde_over_ceiling` is that
divided by the hurdle. `S1_RESULT.md`'s row headed "MDE / hurdle 0.659" is
`mde_bps`, not the ratio.

**`s1_oracle_ceiling.csv`** is a *ceiling*, not a result: what a perfect-foresight
signal would earn. It shows the panel can express a large β, so S1's null is not
a plumbing failure.

**`s2_results.csv`.** Grain: one row per cell. **The pooled cell is
`POOLED_UNCONDITIONAL`**: `beta_z = +0.0240`, `t_z_dk = +0.0361`,
`edge_bps = −0.3165`, `n_obs = 2763`, `n_days = 307`, verdict
`UNINFORMATIVE_COST`. The nine pre-registered per-bucket cells are **8 of 9
`UNINFORMATIVE_POWER`** (the ninth, 0–1Y, is `UNINFORMATIVE_COST`).
`PLACEBO_FLOW_LEADS_RETURN` comes back at `t = −5.19` — **this is not a leak**:
flow shifted *forward* five sessions predicts a return that already happened, so
it measures customer flow responding to a move, and it demonstrates the
estimator can resolve a real relation in this very panel.
`DIAGNOSTIC` rows are not verdicts.

**A bucket is missing on purpose, and the two S2 files disagree about it.**
`s2_panel_description.csv` and `s2_z_cross_correlation.csv` carry **10** tenor
buckets; `s2_results.csv` carries **9** `BUCKET::` cells. **1-2Y is absent from
the results, and that is pre-registered, not a scope reduction**:
`S_PREREG.md` excludes 1-2Y from S2 because its exclusion rate drifts
**+5.07 pp/yr (t = +3.21)** (`BT/dd_signals/s2_positioning.py:144`,
`EXCLUDED_BUCKET = "1-2Y"`; `S2_RESULT.md:34` and `:87`). It is *not* covered by
`S_DEVIATIONS.md` §D4. A notebook that joins the panel description to the
results on `bucket` will silently drop or NaN that row — say which of the two
counts a figure is on.

**`s2_panel.parquet`** is the daily bucket panel behind those regressions and is
the one file here the notebook can legitimately **recompute** from. If it does,
say so at the figure.

**`costs.csv`.** The hurdles every S1/S2 verdict is read against. For S1 the
round trip is model-free (99.7–100% of interdealer spreadover spreads print on a
0.125 bp lattice). **For S2 there is no lattice**, and its column is "not a
bid-offer; it is mostly the T−1min curve's own error" — which is why S2's kill
rule is one-sided (an edge below the hurdle is `UNINFORMATIVE_COST`, never
DEAD). Do not plot the S2 cost column as a bid-offer.

### Documents the notebook should cite, not restate

`docs/dealer_direction/LEDGER.md`, `DESIGN.md`, `INDICATOR.md`,
`WHAT_THE_LADDER_SUPPORTS.md`, `2026-08-11-package-exclusion-skew.md`,
`signals/S_PREREG.md` (committed at `5ec6a7dd`, **never edited**),
`signals/S_DEVIATIONS.md`; and on `r0-leadlag`, the R0/R0b write-ups listed
in §1.

---

## 4. What is *not* here, deliberately

> **Not here is not the same as not used.** Three inputs are read by the
> notebook from outside this directory and are too large to copy into it — the
> s2 calibration pickle, the stage cache and the tape connection. They are
> **§7**, and §7.1 in particular is the most consequential single input in the
> notebook. The rule at the top of this file is satisfied by listing them, not
> by their size.

- No tape parquet, no minute-curve cache, no `x_signed_dv01.parquet` /
  `y_*.parquet` panels, no MBO extracts, no `D:\ddnb_cache` content. This
  directory is ~1.0 MB and is meant to stay that way.
- No copy of `BT/dd_signals/out/*` or `scratch/ppfix_results.txt`. They are
  committed; duplicating them would create a second copy that can go stale.
- The R0/R0b **run logs** (`out/r0_run.log`, `out/r0b_run.log`,
  `out/r0b_x_build.log`) are referenced in the write-ups but were not committed
  to `r0-leadlag`; they are not recoverable and no number here depends on them.

---

## 5. Retraction register

Numbers that appear in files in or referenced by this directory and **no longer
stand**. A stale figure must not be re-plotted as though it did.

### 5.1 — `79.12%` package recovery — **RETRACTED**

- **Carried by**: `docs/dealer_direction/signals/S_PREREG.md:129`;
  `docs/dealer_direction/INDICATOR.md:528`;
  `docs/dealer_direction/2026-08-11-package-exclusion-skew.md:24` and `:415`.
  (INDICATOR.md and the skew doc carry a `SUPERSEDED 2026-08-11` block
  immediately after; `S_PREREG.md` does **not**, and must not be edited — it is
  the pre-registration.)
- **The claim**: orienting `PKG-4+` packages from their package price would take
  DV01 retention from 56.96% to 79.12% and halve the cross-bucket distortion.
- **Why it fails**: it assumed every price-bearing `PKG-4+` package can be
  oriented from its price. It cannot.
- **Stands in its place**: **57.89%** (`scratch/ppfix_results.txt`). The recovery
  is **0.93 pp**, not 22 pp. **64.22% of `PKG-4+` DV01 is genuinely
  unidentifiable.** The cross-bucket distortion is **not** halved.

### 5.2 — `71.92%` package recovery — **SUPERSEDED**

- **Carried by**: `pkg_recovery_seam_SUPERSEDED.txt` in this directory (the only
  file that carries it).
- **The claim**: a seam-coverage projection that a `tape_gate` recovery of
  12.07 bn DV01 takes retention 56.96% → 71.92%.
- **Why it fails**: the same reason as 79.12% — its gate asks only whether a
  package price exists, not whether the orientation it implies is *identified*.
  The file says so itself ("the CRUDE gate … an upper bound only").
- **Do not conflate 71.92% with ppfix's 72.40%.** They are different
  computations that fail for the same reason: 71.92% is the seam-coverage
  projection; 72.40% is ppfix's measured "retention if ambiguity is ignored".
  Ambiguity cannot be ignored. **The standing number is 57.89%.**

### 5.3 — the S1 pre-registration sign error — **RECORDED, NOT DROPPED**

- **Recorded in**: `docs/dealer_direction/signals/S_DEVIATIONS.md` §D1
  ("THE PRE-REGISTRATION CONTAINS A SIGN ERROR IN S1. Mine.").
- **Carried by**: the `beta_sign_expected` and `sign_ok` columns of
  `BT/dd_signals/out/s1_results.csv`, which were computed under the erroneous
  sign, and therefore the `DEAD` / `AMBIGUOUS` split in its `verdict` column.
- **The error**: `S_PREREG.md:86-90` reasons "customer pays the spread → dealer
  receives → dealer is *long* the spread". Wrong at the third step. Paying a
  swap spread is paying fixed and buying the Treasury; that gains when the
  spread **widens**, so the customer is long and **the dealer is short**. S1's
  predicted sign is **β > 0**, not β < 0.
- **What it changes**: the `DEAD`-vs-`AMBIGUOUS` label is convention-dependent
  for **11 of 35** cells. It also withdraws the characterisation that "the
  deepest buckets go the wrong way" — under the corrected direction those are
  the *expected* sign.
- **What it does not change**: the verdict. Zero cells are significant in
  *either* direction (largest `|t|` 1.66 vs criticals 2.51–2.63), and the best
  edge is 5.6× short of its hurdle. A sign error cannot rescue a result that is
  not significant either way. The results were deliberately **not** re-read
  under the corrected sign to look for a finding.
- **Notebook obligation**: this must appear wherever `s1_results.csv`'s
  `verdict` or `sign_ok` columns are shown. It must not be quietly dropped.

### 5.4 — S2's "powered null" — **WITHDRAWN**

- **Recorded in**: `S_DEVIATIONS.md` §D2.
- **Carried by**: `BT/dd_signals/out/s2_results.csv` — specifically
  `mde_beta` / `mde_beta_dk` / `mde_edge_dk`, which use the **uncorrected normal
  multiplier** (`MDE_Z = 3.083`).
- **The claim**: that the pooled cell was "the first cell in the programme with
  the power to have seen a hurdle-sized effect".
- **Why it fails** — any one of three is sufficient: (1) the hurdle it is
  powered against is not a cost (pooled MDE 1.847 bp vs a 2.154 bp kill
  threshold, and `COSTS.md`'s own ceiling-free estimate is 0.71 bp — under which
  kill < MDE); (2) the size correction S1 applied was not applied to S2, and it
  flips the verdict (the module's own validation measures Driscoll–Kraay
  rejecting a true null at **7.8%** against a nominal 5%; corrected critical
  2.896 gives pooled MDE **2.239 > 2.154** → `UNINFORMATIVE_POWER`); (3) the
  pooled panel is **not the pre-registered unit** — `S_PREREG.md:126-130` says
  within-bucket only, and the pre-registered cells are 8 of 9
  `UNINFORMATIVE_POWER`.
- **Stands in its place**: **S2 is UNINFORMATIVE.** Pooled `β = +0.024`,
  `t = +0.04`, edge **−0.32 bp**. The edge is *negative*, so the cost caveat is
  not what binds — a negative edge clears no cost of any size — but the honest
  label is that this test could not have found a hurdle-sized effect in the unit
  it was registered on.

### 5.5 — R0's pre-print trough — **ARTIFACT** (see §1b)

Not a retraction of a number but of its interpretation: `r0_betas.csv`'s
`sum(beta_k, k<=-1) = -0.1075, t = -5.90` is real as a coefficient and
**meaningless as a finding**, because R0b's mid rule produces the opposite sign
on the same data. R0's own `R0_RESULT.md` caveat 1 hypothesised this before R0b
was run.

### 5.6 — five interpretive claims in R0's write-up

`r0-leadlag` commit `07eeb1f2` ("r0: adversarial review — the FAIL survives,
five interpretive claims do not") withdrew five interpretive claims from
`R0_RESULT.md` while the FAIL survived. The tip `c97205bd` copies here already
reflect that review. If the notebook quotes `R0_RESULT.md` prose, quote the tip.

---

## 6. Verification performed

`scratch/nbdata_work/verify_nbdata.py`, run 2026-08-12 against this directory
(21 files, 0.92 MB). For every file: parsed, shape and columns printed, and at
least one headline number asserted against the corresponding documented claim.

**Result: 154/154 checks passed, exit 0** (log:
`scratch/nbdata_work/verify_out.txt`). The asserted values were hand-verified
against the write-ups *before* the script was written, so the checker is checked
against known answers rather than against itself.

**The checker was also mutation-tested**, because a check that cannot fail is
not a check. Three independent corruptions were injected and each was caught,
with the directory restored and re-verified byte-exact afterwards:

| mutation | caught by |
|---|---|
| `r0b_gate.csv` `sum_beta_kpos` perturbed by 0.008 | the CI bounds moved to (−0.0268, +0.0085) — both assertions failed |
| `bucket_retention_DERIVED.csv` 0.761 → 0.781 | the 0.761 assertion, the 1.54× ratio, **and** the `1 − excl_rate/100` relation |
| one row dropped from `r0_betas.csv` | the 732-row assertion |

Its first run also found three real errors — two regex bugs in the checker and
one factual error in this document (the `rho_minute` span was written as
0.345–0.490; it is 0.317–0.490). All three are fixed.

| claim | asserted against |
|---|---|
| R0 `FAIL`, downgraded `UNINFORMATIVE`; R0b `FAIL` | the three verdict files |
| `rho = 0.405` | `r0b_dense_rho.csv` POOLED/12-tenor `rho_minute` = 0.404717 |
| all five buckets below the 0.50 downgrade threshold | `attenuation.csv` |
| R0b post-print 95% interval **(−0.0188, +0.0165)** | recomputed from `r0b_gate.csv` as `sum ± 1.96·se` |
| R0 trough −0.1075 / t −5.90 flips to +0.0159 / t +1.955 | `r0_table.csv` and `r0b_table.csv`, `clock=diss, scope=pooled` |
| universe 1,437,838 units / 75.28% / 56.96% / `UNORIENTABLE_PKG` 39.97% | `universe_exclusions_610d.txt` |
| package recovery 57.89%, 64.22% ambiguous, match 45.45%→99.17%, flat in tie-out | `scratch/ppfix_results.txt` |
| retention 0.761 vs 0.495, 1.54× | `bucket_retention_DERIVED.csv` |
| S1 0 significant / max \|t\| 1.66 / 0.117 vs 0.659 / 35 of 35 below hurdle | `BT/dd_signals/out/s1_results.csv` |
| S2 pooled +0.024, t +0.04, edge −0.32; 8 of 9 `UNINFORMATIVE_POWER` | `BT/dd_signals/out/s2_results.csv` |
| 17 of 17 R0 copies byte-exact | `git hash-object --no-filters` vs branch blob SHAs |

---

## 7. External inputs — read by the notebook, **too large to live here**

These are not in `data/`, and every one of them is nevertheless an input to a
number the notebook prints. They are listed here because the rule at the top of
this file — *recomputed in front of you, or loaded from a file listed below* —
is a rule about **disclosure**, not about file size. Each carries the banner the
affected cells must show and the command that regenerates it.

| § | input | machine path | what depends on it |
|---|---|---|---|
| 7.1 | s2's rolling calibrations | `D:\dd_signals_cache\s2_pos\calibrations.pkl` | `tau`, `b0`, the dead zone and therefore `p` on **every** call |
| 7.2 | the notebook's own stage cache | `D:\ddnb_cache\stage\<digest>\<window>\{pricing,krd}\*.parquet` | the marks, the deviations and the 28-pillar KRD |
| 7.3 | the tape | `D:\ddnb_cache\legs\*.parquet`, else production Postgres | every row upstream of everything |

### 7.1 `calibrations.pkl` — `EXTERNAL`, **the most consequential input here**

- **Producer**: `BT/dd_signals/s2_positioning.py`, **`signal` stage**
  (`s2_positioning.py:621`), which calls
  `SDRUtils/dealer_direction/probability.py::rolling_calibrations`. It is *not*
  written by the `build` stage; `build` and `target` are its prerequisites
  (`build` fills `D:\dd_signals_cache\s2_pos\units\`, `target` writes
  `rates.parquet`, `signal` then fits and pickles).
- **What it is**: `{donor_date: (window_lo, window_hi, probability.Calibration)}`.
  **74 calibrations**, donor dates **2024-03-08 .. 2025-08-22**, one every
  `CALIB_STEP_DAYS = 5` sessions, each fitted on the trailing
  `CALIB_WINDOW_DAYS = 60` **calendar** days of rate-rule deviations ending
  `CALIB_MIN_GAP_DAYS = 1` day before its donor date. 8,156,282 bytes,
  `sha256 4d5916ea…d14c8f`, written 2026-08-11 21:40:36.
- **Why it is external, and not refitted in the notebook**: the pilot window is
  three days, ~3.4k rate-rule deviations, against `MIN_BUCKET_N = 800`. A fit on
  it would pool almost everything to a coarse parent *and* — decisively — would
  not be **trailing**: the days would enter their own `b0`. Reusing s2's fits is
  the same code (`probability.rolling_calibrations`) on 18 months, and
  `dd_nb.taus` re-asserts per day that the governing window ends **strictly
  before** the day it governs.
- **What comes off it, and is therefore `LOADED` and not `COMPUTED`**: the
  397/409 bucket fits per donor; the `b0` / `h` / `s` / `separation` / `tau` /
  `dead_zone` of the demonstrated bucket; the gate counts (`SEPARATION_BELOW_FLOOR`
  304, `N_BELOW_MINIMUM` 341, …); the pooling ladder; and `tau` — hence `p`,
  hence `2p-1`, hence `delta_dv01` — on **all 4,938 calls**. Everything
  downstream of a weight inherits it.
- **What does *not* come off it**: the marks and deviations (§7.2), the KRD
  geometry (§7.2), the universe accounting, the convention comparison, and all
  of §9's loaded studies.
- **If it is absent** `dd_nb.taus` raises `FileNotFoundError` naming this section
  and the chain below. It must never fall back to an in-window fit: that fit is
  a different claim, and the failure would otherwise surface four cells later
  as a strictly-prior assertion, blaming window ordering for a missing file.
- **Regenerate** (hours; `build` reads the production tape):

  ```
  set ARBS_SUPABASE_ENABLED=0
  C:/Users/chris/anaconda3/envs/stir/python.exe BT/dd_signals/s2_positioning.py build
  C:/Users/chris/anaconda3/envs/stir/python.exe BT/dd_signals/s2_positioning.py target
  C:/Users/chris/anaconda3/envs/stir/python.exe BT/dd_signals/s2_positioning.py signal
  ```

  Or point the notebook at another copy: `dd_nb.config(s2_calibrations=<path>)`.

### 7.2 The stage cache — `EXTERNAL`, **content-keyed, and not stale**

- **Path**: `D:\ddnb_cache\stage\<source_digest>\<window>\{pricing,krd}\<day>.*.parquet`,
  plus `D:\ddnb_cache\legs\legs_<start>_<end>.parquet` for the tape frame.
- **What is cached**: exactly two of the eight pipeline stages — `price_units`
  (per-unit marks, `structure_dv01`, `npv_pay`, `traded`/`mid`/`deviation_bps`,
  and the per-leg frame) and `krd_frame` (the 28-pillar `dv01_if_received`).
  `build_units`, `classify`, `ladder_rows` and `daily` are always recomputed;
  `taus` is always §7.1.
- **What keys it**: `dd_nb.source_digest` — a SHA-256 over the **contents** of
  every `SDRUtils/dealer_direction/*.py` **and the whole text of `dd_nb.py`,
  comments included**, plus `Config.digest_payload()` (`curve_source`,
  `indices`, `include_lifecycle`, `block_minutes`, `dust_frac`). Any edit to any
  of them is a new key and a cold run, so **a cached mark cannot have been
  produced by different code**. The cost of that guarantee is ~180 s after a
  docstring edit; the alternative is a silent wrong mark.
- **Why it is still disclosed**: "cannot be stale" is not "was computed in front
  of you". A cell that banners `COMPUTED` over rows read off parquet is
  mislabelled even when every number in it is right.
- **What checks it anyway**: §3's trace re-prices its unit **live** through the
  same `midprice.UnitRepricer` and reports `deviation_diff`, `npv_pay_diff`,
  `structure_dv01_diff` and `gross_pv01_diff` against the cached mark. That
  recheck is perturbation-sensitive to 1e-6 bp.
- **See it**: `pipe.timings.source` (one word per stage) and `pipe.cache`
  (`dd_nb.cache_report()`, with the paths). Both are printed in §1.
- **Regenerate**: delete `D:\ddnb_cache\stage`, or run with
  `dd_nb.config(use_cache=False)`. ~180 s for three tape days, pricing is 70–80%
  of it.

### 7.3 The tape — `EXTERNAL`, read-only, and normally not read at all

- **Served from** `D:\ddnb_cache\legs\legs_<start>_<end>.parquet` when it exists.
  The legs cache is keyed on the **window alone** — the tape is immutable
  history and does not depend on any config knob.
- **On a miss** `dd_nb.connect()` opens **one** read-only `SELECT`
  (`universe.LEGS_SQL`) against production Supabase via
  `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py::resolve_pg_url()`.
  **Nothing is written**: no `INSERT`, no `UPDATE`, no DDL, no temp tables, and
  the notebook asserts that on the query text.
- **Credentials**, in `resolve_pg_url`'s own precedence order:
  1. `DATABASE_URL`
  2. `PG_URL`
  3. the shared `SWAPPULSE_DB_*` defaults on `ingest_usdswaps`
     (`SWAPPULSE_DB_HOST` / `_PORT` / `_NAME` / `_USER` / `_PASSWORD`), which
     fall back to the repo-default Supabase host.

  So a cold legs cache needs **one of** `DATABASE_URL`, `PG_URL`, or a
  populated `SWAPPULSE_DB_*` set in the environment. With a warm cache none of
  them is read and the notebook runs fully offline.
- **Also required for an offline run**: `ARBS_SUPABASE_ENABLED=0` (set in the
  notebook's first cell, before anything imports `Caching`) and
  `ARBS_CITIVELO_QUOTES_OFFLINE=1` (so no cell can open Excel). Curve reads go
  to the local DuckDB curve store.
