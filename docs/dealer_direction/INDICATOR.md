# The daily street-positioning indicator

`SDRUtils/dealer_direction/indicator.py`

One number per **(tenor bucket, availability date, venue class, series)**: the
signed DV01 of model-labelled customer risk transfer that became public that
day, read against that cell's **own history**.

This is the retarget the pre-registered branch called for. The intraday
hedge-trigger and max-pain components are **gone** — not deferred, not stubbed.
What is kept is the tape reconstruction, the direction inference and the change
of basis.

> **The important half of this note is §3, "What it cannot say."** A positioning
> indicator built on 57% of the tape's DV01, where the surviving share is a
> fixed function of the curve region, can support one reading and not the other.
> The API enforces the difference; this note explains it.

---

## 0. The one-minute read

| | |
|---|---|
| **grain** | (tenor bucket, availability date, venue class, series), daily |
| **buckets** | the skew document's ten: `0-1Y … 30Y+`, rolled up from the 28 KRD pillars, right edge inclusive (a 10Y point is `7-10Y`) |
| **clock** | `Clocks.visibility`, New York date. Never execution. |
| **series** | D2C / D2D / `VENUE_UNKNOWN` × FLOW / LIFECYCLE — six, never merged |
| **weight** | `conventions.signed_weight(p) = 2p − 1`, never `p` |
| **sign** | `+` = dealer received fixed = dealer long duration |
| **sample floor** | 2024-07-01 (the ingest break), refused earlier unless asked |
| **you may read** | "the 5y bucket against its own history" |
| **you may not read** | "dealers are longer 5y than 10y", or any running total |

```python
from SDRUtils.dealer_direction import indicator as ind, ladder, types as T

obj = ind.build(unit_rows,                 # ladder.unit_ladder_rows()[0]
                coverage=coverage_frame,   # required, no default
                session_dates=sessions)    # so a gap is a zero, not an absence

obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
obj.standardised()      # every bucket, z / percentile, NO level
obj.properties()        # autocorrelation, stationarity, coverage moves
obj.drift               # is this bucket's coverage holding still?
```

---

## 1. Why the API is shaped the way it is

Everything below follows from one measurement,
`2026-08-11-package-exclusion-skew.md`: **the retained population is a biased
sample, and the bias is a fixed function of the curve region.**

| bucket | 0-1Y | 1-2Y | 2-3Y | 3-5Y | 5-7Y | 7-10Y | 10-15Y | 15-20Y | 20-30Y | 30Y+ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **DV01 retention** | **0.761** | 0.522 | 0.602 | 0.554 | 0.524 | 0.537 | 0.601 | **0.495** | 0.512 | 0.612 |

A reader comparing the 0-1Y level to the 15-20Y level is comparing 76% of one
bucket's tape DV01 against 50% of the other's — a **1.54× cross-bucket scaling
distortion**. Within a bucket the factor is persistent (the cross-bucket spread
of the means is 5.5× the median within-bucket monthly sd), so a **within-bucket
time series is defensible and a cross-sectional shape is not**.

### The z-score is the one cross-bucket-safe view, and this is arithmetic

Write the observed level as `r_b · L` for a retention factor `r_b`. Then

```
z = (r_b·L − r_b·μ) / (r_b·σ) = (L − μ) / σ
```

**A constant retention factor cancels exactly.** That, and only that, is why
`standardised()` is allowed to put every bucket in one frame while the level is
not — and it is why the cancellation is pinned by a known-answer test (halve one
bucket's level; z does not move by more than 1e-12).

The cancellation needs `r_b` constant **in time**. §4 is about the bucket where
it is not.

---

## 2. What is published

`obj.bucket(key, venue_class=…, series=…)` returns one cell-series with:

| column | what it is |
|---|---|
| `delta_dv01__<bucket>` | **the level.** Signed, USD per bp, `Σ (2p−1)·dv01_if_received`. Bucket-suffixed — see §3. |
| `delta_dv01_cov_adj__<bucket>` | the same level divided by smoothed coverage (§4) |
| `abs_dv01__<bucket>` | the pond the net was formed from: summed across units of each unit's **net-within-bucket** magnitude. Two units offsetting each other still show their gross, so a net of zero over a $40mm `abs_dv01` is a different day from a net of zero over nothing — but one unit's own offsetting pillars inside a bucket net away before they reach here, so this is not a per-pillar gross. |
| `z_raw`, `z_cov_adj`, `pct_raw` | own-history statistics, **trailing** 250 observations, min 60 |
| `z_n_obs` | how much history is actually behind that z |
| `coverage_frac` | the fraction of this bucket-day's gross tape DV01 that reached the ladder |
| `coverage_smooth` | its trailing 63-observation mean, which the adjusted basis divides by |
| `coverage_drift_flag`, `coverage_trend_pp_per_yr`, `coverage_drift_source` | §4 |
| `n_units`, `mean_abs_signed_weight` | how many prints, and how much of the pond survived the confidence weighting |
| `frac_dv01_block`, `frac_dv01_capped` | how much of the size was imputed rather than read |
| `frac_dv01_dead_zone` | how much sat inside the mid's own measurement error |
| `frac_dv01_visibility_measured` | measured publication time vs the Appendix C legal estimate |
| `code_vintage` | the stamp, or `MIXED:n` if the cell was built by two vintages |
| `observed` | `False` on a calendar day the cell did not print (filled as zero flow) |
| `primary_level_basis` | `RAW`. The basis travels with the number. |

### Two allocations, and they are not the same allocation

The **level** is key-rate risk from rateslib's delta ladder over the 28 KRD
pillars, rolled up. The **coverage fraction** is a maturity-point allocation of
gross `|DV01|`, because an excluded unit has no key-rate profile *by
construction* — that is why it was excluded. Both the numerator and the
denominator of coverage come from the maturity-point grid, so coverage is
internally consistent; but do **not** read `coverage_frac` as "the fraction of
this cell's key-rate risk that survived". Read it as "the fraction of this
bucket-day's gross tape DV01 that reached the ladder at all". The columns are
named `coverage_dv01_kept` / `coverage_dv01_total` for that reason.

---

## 3. What it cannot say

### 3.1 It cannot compare levels across buckets — and the object will not help you

`cross_section(date)` and `pivot_levels()` exist **only to refuse**, with the
measurement in the message. Beyond that the enforcement is structural, because a
pivot is one line of pandas and a docstring is not a control:

- the level column is **named for its bucket** (`delta_dv01__5_7Y`,
  `delta_dv01__15_20Y`), so `pd.concat` of two buckets is a block-diagonal frame
  of NaNs, not a comparison, and `pivot(values="delta_dv01")` has nothing to
  pivot;
- `standardised()` — the one all-bucket frame — carries **no level at all**;
- there is no `to_frame`, `levels`, `frame` or `df` accessor. Deliberately. A
  test asserts they do not exist.

If you genuinely need cross-bucket levels, `rescale_for_cross_section(factors)`
divides by retention factors **you supply** (they are not defaulted from
`MEASURED_RETENTION_FACTORS`; you have to go and read §1). The output column is
`tape_scaled_dv01_ASSUMES_SAME_DIRECTIONAL_MIX`, named so it cannot be quoted
without its assumption: the rescale assumes the excluded flow in a bucket has
the same directional mix as the retained flow, and per skew §8.1 that is
precisely what cannot be verified — the excluded units are excluded *because*
their direction cannot be read.

### 3.2 It will not cumulate

`cumulate()`, `cumsum()`, `position()` and `inventory()` all raise
`CumulationRefused`. Compression and allocation are **never publicly reported**,
so risk leaves a dealer's book with no offsetting print and a running sum
carries an unbounded, *monotone* error — it only ever grows and nothing in the
data pushes back. Prime-brokerage mirror legs cannot be de-duplicated where it
matters, and Remedy-1 unwinds print as ordinary at-market trades.

If you want a stock, name the assumption:
`ladder.decayed_flow(frame, half_life_days=…)`, which has **no default
half-life** for exactly this reason. `half_life_days=float("inf")` is pure
accumulation and is allowed; it is just not the default. No published column
accumulates, and a test scans every returned frame for one.

### 3.3 It under-reports large customer prints

The excluded `PKG-4+` family is **97.9% D2C** against 82.1% retained, and
**28.7% block by DV01** against 11.1% retained. Whatever this indicator says
about the size of customer risk transfer, it is a **low reading**, and it is
lowest in the long end.

### 3.4 It is not counterparty-observed, and it is not a signal

Direction is inferred from price against a repriced mid, uncertified against any
external truth label. No backtest is in this module.

---

## 4. The 1-2Y bucket: the decision, and the measured effect of it

**1-2Y's exclusion rate drifts at +5.07 pp/yr (t = +3.21)** — its retention is
falling through the sample, so its *level* moves for reasons unrelated to
positioning. It is the meeting-dated front end, i.e. the bucket that matters
most here.

**The choice made: the raw level stays primary, and the adjusted one sits beside
it.** Coverage-adjusting by default would silently apply the same
directional-mix assumption that §3.1 makes loud for cross-sections; doing one
silently while refusing the other loudly is incoherent. So both columns are
published, `primary_level_basis` travels with the number, and every row carries
its own drift flag.

**The flag is raised two ways**, because a consumer on a short window cannot
detect a 5 pp/yr slope from the data at all: `MEASURED` from the window's own
monthly coverage when there are ≥ 12 months, and `PINNED` from
`PINNED_DRIFT_BUCKETS` otherwise — which contains 1-2Y and the finding verbatim.

**The adjustment divides by a smoothed coverage, not by the day's own fraction.**
The defect is a slow trend; the daily fraction is mostly print composition (§5.2
measures the median day-over-day relative move at 13–34%), so dividing by it
would inject daily noise to fix an annual drift. A test asserts the adjusted
series' coefficient of variation is at least 5× smaller than per-day division
would give on a constant true level.

### The measured effect of the choice

`adjusted = raw × f`, where `f = mean(coverage) / rolling_mean(coverage, 63)`.
`f` is a pure function of coverage, so **its path bounds the raw-versus-adjusted
divergence for any level path** — no signed level is needed to measure it.
D2C / FLOW, 464 days post-floor:

| bucket | f mean | f sd | f p5 | f p95 | f last / first | f trend /yr | sd log f |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0-1Y | 1.002 | 0.030 | 0.959 | 1.055 | 0.979 | −0.008 | 3.00% |
| **1-2Y** | 1.009 | **0.062** | 0.893 | 1.121 | **1.264** | **+0.077** | 6.18% |
| 2-3Y | 1.009 | 0.041 | 0.950 | 1.080 | 0.992 | −0.039 | 4.05% |
| 3-5Y | 0.999 | 0.073 | 0.882 | 1.102 | 1.022 | −0.074 | 7.43% |
| 5-7Y | 1.002 | 0.037 | 0.943 | 1.068 | 1.115 | +0.037 | 3.64% |
| 7-10Y | 1.006 | 0.048 | 0.928 | 1.087 | 1.060 | +0.040 | 4.76% |
| 10-15Y | 1.002 | **0.018** | 0.973 | 1.035 | 0.967 | −0.007 | 1.82% |
| 15-20Y | 1.005 | 0.074 | 0.912 | 1.164 | 0.840 | −0.033 | 7.12% |
| 20-30Y | 1.014 | 0.074 | 0.898 | 1.168 | 1.047 | +0.097 | 7.16% |
| 30Y+ | 1.006 | 0.034 | 0.949 | 1.056 | 1.009 | +0.004 | 3.37% |

**Read this as: the two bases differ by 1.8% to 7.4% (sd of log f), and for
1-2Y the difference is not noise but a 26% level trend across the sample.** The
raw 1-2Y level ends the sample carrying a **+26.4%** measurement-driven uplift
relative to where it started; the adjusted basis removes it. In the nine other
buckets the choice is a few percent of scatter and changes no conclusion.

Because `z` is invariant to a *constant* factor, `z_raw` and `z_cov_adj` differ
only through the *variation* of `f` inside the 250-observation window — small
everywhere except 1-2Y, 3-5Y, 15-20Y and 20-30Y, where `sd log f` runs 6–7.4%.

**Practical rule: for 1-2Y, read `z_cov_adj`, or read `z_raw` and subtract a
trend you know is there. For the rest, the choice does not matter much and the
raw level is the honest default.**

---

## 5. The series' own properties

Measured on the pinned 610-day tape, restricted to the post-floor window
**2024-07-01 … 2026-08-07 (527 days)**. Two scope caveats, both real:

- the source is the skew document's per-leg extract, which is keyed on the
  tape's **`as_of_date`**, not on the visibility date. The tape's `as_of` day
  runs 20:00 ET the prior evening to 19:59 ET, so this is a day-boundary
  approximation to the published clock — good enough for autocorrelation and
  drift, not a substitute for the real stamping;
- it is the **maturity-point** allocation of *kept* gross DV01, not the KRD
  allocation of the signed level. See §6 for what that leaves unmeasured.

### 5.1 Persistence and stationarity — D2C / FLOW

| bucket | days | gross mean $m/bp | AC(1) | AC(5) | AC(21) | ADF | stationary | coverage mean | coverage sd | coverage AC(1) | coverage stationary |
|---|---:|---:|---:|---:|---:|---:|:--:|---:|---:|---:|:--:|
| 0-1Y | 526 | 4.90 | 0.563 | 0.274 | 0.171 | −2.70 | **no** | 0.773 | 0.127 | 0.104 | yes |
| 1-2Y | 526 | 3.55 | 0.520 | 0.259 | 0.126 | −2.86 | yes | 0.544 | 0.138 | 0.172 | yes |
| 2-3Y | 526 | 4.40 | 0.711 | 0.550 | 0.273 | −2.66 | **no** | 0.611 | 0.121 | 0.246 | yes |
| 3-5Y | 526 | 6.31 | 0.579 | 0.388 | 0.174 | −3.40 | yes | 0.545 | 0.121 | 0.222 | yes |
| 5-7Y | 526 | 11.55 | 0.532 | 0.293 | 0.011 | −3.93 | yes | 0.596 | 0.104 | 0.190 | yes |
| 7-10Y | 526 | 4.91 | 0.435 | 0.233 | 0.094 | −3.83 | yes | 0.522 | 0.141 | 0.175 | yes |
| 10-15Y | 526 | 13.61 | 0.473 | 0.261 | 0.144 | −3.43 | yes | 0.687 | 0.114 | 0.077 | yes |
| 15-20Y | 526 | 1.85 | 0.233 | 0.211 | 0.023 | −4.11 | yes | 0.456 | 0.167 | 0.132 | yes |
| 20-30Y | 527 | 3.01 | 0.401 | 0.194 | −0.078 | −5.59 | yes | 0.463 | 0.153 | 0.205 | yes |
| 30Y+ | 526 | 7.47 | 0.491 | 0.273 | 0.160 | −3.61 | yes | 0.688 | 0.130 | 0.134 | yes |

**What this says.**

- **The gross pond is persistent at the daily grain and decays fast.** AC(1)
  0.23–0.71, AC(5) 0.19–0.55, AC(21) at or below 0.28 everywhere. The market
  memory in this series is roughly a week, not a month.
- **Its level holds still in 8 of 10 buckets.** 0-1Y (−2.70) and 2-3Y (−2.66)
  sit just short of the 5% critical value of −2.86; those two are "not
  distinguishable from a unit root at n = 526", which is a statement about
  power, not a claim that they wander.
- **The coverage fraction is stationary in every D2C bucket and nearly white**
  (AC(1) 0.08–0.25). That is the good news underneath §4: the coverage
  contamination is *noise around a stable mean* in nine buckets and a *slow
  trend* in one.
- **D2D is much less persistent** (AC(1) 0.01–0.49, mostly under 0.3) and
  stationary in 9 of 10. **`VENUE_UNKNOWN` is nearly white** (AC(1) ≤ 0.24) —
  consistent with it being a residue rather than a business.
  (`D:\ddind_cache\ddind_props_d2d.csv`, `ddind_props_unknown.csv`.)

### 5.2 How often the coverage fraction moves enough to matter

"Enough to matter" is defined against the level's own noise, not by eye: a
day-over-day coverage change puts a multiplicative distortion of `|Δc| / c` on
the level, and it matters when that distortion applied to the level's typical
size exceeds `COVERAGE_MOVE_SIGMA = 0.25` standard deviations of the level. An
absolute percentage-point threshold cannot do this — 2 pp is nothing on a bucket
whose level swings 3× a day and is the whole signal on a quiet one.

D2C / FLOW, 525 day-pairs per bucket:

| bucket | median \|Δc/c\| | share > 25% | share > 25%, big days only | median, big days |
|---|---:|---:|---:|---:|
| 0-1Y | 13.1% | 25.1% | 24.1% | 12.7% |
| 1-2Y | 21.7% | 43.2% | 46.8% | 23.8% |
| 2-3Y | 15.1% | 29.5% | 29.8% | 14.0% |
| 3-5Y | 17.9% | 37.7% | 41.8% | 18.8% |
| 5-7Y | 14.4% | 26.3% | 29.8% | 15.7% |
| 7-10Y | 22.4% | 46.1% | 47.5% | 22.8% |
| 10-15Y | 15.2% | 27.4% | 32.7% | 16.4% |
| **15-20Y** | **32.9%** | **61.1%** | **65.4%** | **35.2%** |
| 20-30Y | 27.6% | 53.9% | 54.9% | 31.8% |
| 30Y+ | 15.2% | 30.1% | 31.6% | 14.5% |

**The answer is: very often.** On a quarter to nearly two-thirds of days,
depending on bucket, the coverage behind a cell moves by more than 25% relative
to the day before. **Restricting to the bucket's own high-volume days does not
shrink it** — it grows slightly, so this is not a small-sample artefact of quiet
days; it is genuine day-to-day churn in which packages happened to print.

Consequences, and they are the practical read of this whole note:

1. **A single day's level carries heavy print-composition noise.** Read
   multi-day. AC(5) at 0.19–0.55 says a week's worth of the series is still
   informative about itself; one day against the previous day is mostly
   composition.
2. **This is exactly why the adjusted basis divides by smoothed coverage** and
   why the raw basis is primary — a per-day division would import all of the
   churn in the table above into the level.
3. **Gate on `coverage_frac` per row.** It is published for this reason. 15-20Y
   and 20-30Y are the two buckets where it moves most and where the DV01 base is
   smallest (15-20Y is 4.3% of the tape).

---

## 6. What is NOT measured here, and what it would cost

**The signed level's own autocorrelation and stationarity are unmeasured.**
Everything in §5 is the gross pond and the coverage — the two published columns
that can be computed from the cached extract. The signed level needs the full
direction pass, and no composed pipeline
(universe → midprice → probability → krd → ladder) exists yet.

The cost, measured today rather than estimated:

| stage | measured | source |
|---|---|---|
| repricing | **115 s/day** (4,329 eligible flow legs on 2026-04-01, 26.5 ms/leg, 100% priced) | `scratch/dd18_one_full_day.py`, run 2026-08-11 |
| key-rate change of basis | ~65 s/day, 36 solvers | LEDGER, per-session-block 60 min |
| **610 days, single process** | **≈ 30 h** | |

A window short enough to fit a session is also too short to answer the question:
this module's own Monte Carlo puts the ADF's power at **91.5% at n = 250** and
its size at 2.8%, so a 60-day pilot would return an autocorrelation with a
standard error of 0.13 and a stationarity verdict with almost no power. A
plausible-looking level series from a hastily composed pipeline is worse than a
stated gap, so the gap is stated.

**The gap has a lid.** `obj.properties()` computes exactly these numbers, and
its meters are already validated (§7). The first real backfill produces them
with no new code.

---

## 7. Validation — what was checked before anything here was believed

| gate | result |
|---|---|
| **bucket map** vs the skew extract's own `tenor_bucket` | **2,326,777 / 2,326,777 legs agree (100.000000%)**; the 4 legs with no extract bucket carry 0.00 DV01 |
| **retention factors**, recomputed from the leg cache | reproduce the published table, worst \|diff\| **0.00047** |
| **drift meter**, monthly, complete months 2024-07…2026-07, n = 25 | **1-2Y +5.072 pp/yr, t = +3.205** against the document's independently computed **+5.07, t = +3.21**; 0-1Y **−2.873 / −2.158** against **−2.87 / −2.16** |
| **ADF** vs `statsmodels.tsa.stattools.adfuller` | identical to **2.7e-13** on white noise, AR(1) φ=0.6, AR(1) φ=0.98, a random walk and a random walk with drift |
| **ADF size and power**, 400 replications | RW called stationary 2.8% / 4.5% / 5.0% at n = 250 / 610 / 1500 (nominal 5%); white noise detected 91.5% / 100% / 100% |
| **tests** | 59, all passing |
| **mutation testing** | **15 / 15 killed**, no survivors |

### A defect this found in its own meter

The first ADF implementation was **numerically wrong on DV01-scale inputs** and
the unit-scale statsmodels cross-check could not see it. A design matrix
carrying a column of ones beside a column of 1e7 DV01s has a condition number
near 1e12, and the normal-equations inverse returned a standard error wrong by
orders of magnitude:

- on the real 610-day gross series it reported **−20.98** where the correct
  answer is **−4.23**;
- on 1e7-scaled white noise, **−1086.7** against **−4.96**.

Both are very confident "stationary" verdicts manufactured out of arithmetic —
the exact failure the column exists to catch, self-flattering and silent. `t_ρ`
is exactly invariant to an affine rescaling of the series, so the fix is to
standardise before regressing; the statistic is unchanged and the conditioning
is not. It is pinned by `test_the_stationarity_meter_is_invariant_to_the_scale_of_the_level`,
which failed at −1086.7 vs −4.96 before the fix. For reference, `statsmodels`
itself survives 1e7 but returns −0.011 at 1e11 on the same series.

### The mutations, all killed

weight check accepts `p`-weighting · `venue_class` dropped from the key ·
execution-stamped rows not caught · bucket-map right edge moved · `cross_section`
returns instead of refusing · drift flag never trips · z pooled across venue
classes · sample floor removed · `cumulate` returns instead of refusing · level
column loses its bucket suffix · z uses the whole sample instead of a trailing
window · a missing coverage row tolerated · ADF standardisation removed ·
roll-up stops checking a unit is one print · coverage smoother replaced by the
day's own fraction.

The last two **survived the first pass** and are reported as such: no test built
a unit whose pillar rows disagreed about the venue, and the coverage-adjustment
test used a noiseless linear coverage path that per-day division removed just as
well as the smoother did. Two tests were added for exactly those holes and both
mutants then died.

---

## 8. Notes for whoever wires this into a backfill

- **`indicator.py` is not in `provenance.VINTAGE_SOURCES`, and should not be.**
  It reads the ladder's output, it does not determine it — the same reason
  `health.py` is excluded. A monitoring or presentation edit must not invalidate
  a 30-hour backfill. The vintage that matters travels in the `code_vintage`
  column of every published row.
- **`coverage` is a required argument with no default.** It must carry both
  `dv01_kept` and `dv01_total` per (bucket, day, venue, series) — a ratio alone
  cannot be re-aggregated, and the denominator is the only thing that knows
  about the units that were excluded. A published cell with no coverage row
  raises `CoverageGap` rather than defaulting to 1.0, because reporting full
  coverage on a 57% population is the self-flattering failure a reader would
  believe.
- **Pass `session_dates`.** Without a calendar, an absent day is a missing row,
  and every rolling statistic then treats a fortnight-old print as yesterday's.
  With one, the day is zero flow and `observed=False`.
- **The sample floor is 2024-07-01** and earlier dates raise. The exclusion rate
  steps −3.2 pp across the ingest break and the tape carries **no** termination
  events before it, so the LIFECYCLE series is empty there for a reason that is
  not the market.
- **Read the venue classes apart.** D2D is not customer flow; `VENUE_UNKNOWN` is
  a third series and not a rounding of the other two. Assigning it to D2C
  manufactures customer flow.
- **The recovery route is the thing worth building next.** 100% of `PKG-4+`
  DV01 carries a package price or spread; orienting it against a repriced swap
  package mid would take retention from 56.96% to **79.12%** and halve the
  cross-bucket distortion (spread 26.65 → 16.73 pp). That is the change that
  would make §3.1 shorter.

---

## Reproduction

Python invoked directly from `C:/Users/chris/anaconda3/envs/stir/python.exe`
(never `conda run`); `ARBS_SUPABASE_ENABLED=0`; the tape was read only.
Cache on `D:\ddind_cache` (C: had ~3.7 GB free).

| script | what it does |
|---|---|
| `scratch/ddind_coverage.py` | gates 1 and 2 above, then writes the 610-day coverage frame (27,655 cells) |
| `scratch/ddind_properties.py` | §5 tables and the §4 basis-factor path |
| `scratch/ddind_adf_check.py` | the ADF cross-check against statsmodels |
| `scratch/ddind_mutate.py` | the 15 mutations; restores the source in a `finally` |
| `tests/test_dealer_direction_indicator.py` | 59 tests |
