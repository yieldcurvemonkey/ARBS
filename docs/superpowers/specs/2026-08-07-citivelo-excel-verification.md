# Citi Velocity Excel source — verification results and adversarial review

**Branch** `feat/citivelo-irswaps-source` · **written** 2026-08-07 · design note:
[`2026-08-07-citivelo-excel-irswaps-source.md`](2026-08-07-citivelo-excel-irswaps-source.md)

Reproduce with:

```bash
conda run -n stir python MDP/IRSwaps/CITIVELO_EXCEL/verify_matrix.py --offline
```

Raw output in `MDP/IRSwaps/CITIVELO_EXCEL/verification/` (`mode_matrix.csv`,
`tie_out_rows.csv`, `tie_out_summary.csv`, `forward_stability.csv`,
`verdict.json`). Live harvest evidence in
`MDP/CitiVelocityExcel/harvest/live_curve_modes/`.

---

## 1. The per-currency mode matrix

All 20 curves, all three modes, EOD 2026-08-06 / intraday 2026-08-06 10:30 ET /
live. Cell = tenors served.

| curve | eod | intraday | live | live lag |
|---|---|---|---|---|
| USD-SOFR-1D | 44 | 44 | 44 | 0.7 min |
| USD-FEDFUNDS-1D | 44 | 44 | 44 | 0.8 min |
| EUR-ESTR-1D | 44 | 44 | 44 | 0.8 min |
| **EUR-EONIA-1D** | **—** | **—** | **—** | discontinued 2025-08-15 |
| GBP-SONIA-1D | 44 | 44 | 44 | 0.9 min |
| JPY-TONAR-1D | 44 | 44 | 44 | 232 min (Tokyo closed) |
| **JPY-TONAR-1D-JSCC** | 44 | **—** | **—** | EOD only |
| JPY-TONAR-1D-LCH | 44 | 44 | 44 | 232 min |
| CHF-SARON-1D | 44 | 44 | 44 | 0.8 min |
| CAD-CORRA-1D | 44 | 44 | 44 | 0.8 min |
| AUD-AONIA-1D | 44 | 44 | 44 | 292 min (Sydney closed) |
| NZD-NZIONA-1D | 44 | 44 | 44 | 412 min |
| NOK-NOWA-1D | 44 | 44 | 44 | 1.0 min |
| SEK-STINA-1D | 44 | 44 | 44 | 1.0 min |
| DKK-TNDKK-1D | 44 | 44 | 44 | 0.8 min |
| ILS-SHIR-1D | 44 | 44 | 44 | 0.9 min |
| MXN-FONDEO-1D | 44 | 44 | 44 | 0.9 min |
| SGD-SORA-1D | 44 | 44 | 44 | 172 min |
| THB-THOR-1D | 44 | 44 | 44 | 112 min |
| ZAR-ZARONIA-1D | 44 | 44 | 44 | 1.1 min |

**55 of 60 combinations serve a complete 44-tenor grid.** The five that do not
fail with a named reason, not an empty frame:

* `EUR-EONIA-1D` × 3 — the curve is discontinued; the daily series stops
  2025-08-15 and there is no one-minute history at all.
* `JPY-TONAR-1D-JSCC` × intraday, live — EOD only.

The non-zero live lags are **correct and reported**: JPY, AUD, NZD, SGD and THB
were outside their own trading sessions at 11:00 ET. Serving them silently as
"live" is exactly the failure the lag exists to prevent.

---

## 2. The tie-out

Four checks plus an end-to-end NPV check, all through
`IRSwapsMDP → IRSwapQuery → IRSwapStructure`.

### 2.1 NPV at the curve's own fair rate — 0.0000 everywhere

| | eod | intraday | live |
|---|---|---|---|
| worst \|NPV\| over 20 curves × 4 tenors, both backends | 0.0000 | 0.0000 | 0.0000 |

The check a successful build does not give you. A float leg that silently lost
its fixings, or an instrument whose schedule does not match the curve it was
calibrated against, still *builds* — it just prices wrong. This exercises the
fixed leg, the float leg, the discounting and the schedule together and there is
one right answer.

### 2.2 Par rates through `IRSwapQuery` vs `RATES.OIS.<idx>.PAR.<tenor>`

Worst \|error\| in bp over all 44 tenors:

| backend | eod | intraday | live |
|---|---|---|---|
| rateslib | **0.0017** | 0.0015 | 0.0016 |
| QuantLib | 0.4217 | 0.3478 | 0.4126 |

This is near-circular on the *curve* but not on the *definitions*: `IRSwapQuery`
builds its swaps from `RATESLIB_CURVE_DEFINITIONS`, a different table read by a
different code path. A registered definition that disagreed with
`conventions.py` about the calendar, the frequency, the settlement lag or the
day count would move this, and it is what caught the CHF sign bug (F8 in §6).

The QuantLib residual is concentrated in the sub-year tenors (worst 0.34 bp at
2M on USD) and is the two libraries' different treatment of a stub period, not a
source defect — the two backends agree to 0.11 bp everywhere they overlap (§2.4).

### 2.3 Forward rates vs Citi's published `RATES.OIS.<idx>.FWD.<e>.<t>` — the ±1bp check

**204 comparisons across 17 curves** (three publish no `FWD` tags at all:
`EUR-EONIA-1D`, `JPY-TONAR-1D-JSCC`, `JPY-TONAR-1D-LCH`).

Worst \|error\| per curve, in bp, rateslib (QuantLib is identical to 3 dp):

| curve | worst bp | | curve | worst bp |
|---|---|---|---|---|
| SGD-SORA-1D | 0.0011 | | JPY-TONAR-1D | 0.3817 |
| NOK-NOWA-1D | 0.0259 | | CAD-CORRA-1D | 0.4217 |
| ILS-SHIR-1D | 0.0486 | | SEK-STINA-1D | 0.7498 |
| CHF-SARON-1D | 0.0530 | | **ZAR-ZARONIA-1D** | **1.6376** |
| GBP-SONIA-1D | 0.0909 | | **AUD-AONIA-1D** | **2.1649** |
| EUR-ESTR-1D | 0.1517 | | **MXN-FONDEO-1D** | **3.2126** |
| USD-SOFR-1D | 0.1800 | | **THB-THOR-1D** | **4.2251** |
| USD-FEDFUNDS-1D | 0.2060 | | **DKK-TNDKK-1D** | **6.0922** |
| NZD-NZIONA-1D | 0.3664 | | | |

**12 of 17 curves are inside ±1 bp on every one of the six forward points.**
Five are not, on 14 of the 204 comparisons.

### 2.4 rateslib vs QuantLib on the same trade

Worst \|difference\| over 2Y/5Y/10Y/30Y: **0.1113 bp** (JPY-TONAR-1D-LCH, live);
median across curves ~0.013 bp. This is the check that catches schedule, day-count
and annuity divergence, because the two libraries agree on nothing by accident.

### 2.5 Interpolation (drop one interior node, then price it)

Worst **5.26 bp** (MXN at 3Y); typical 1.3–4.5 bp, mostly at 25Y between the
20Y and 30Y nodes. This is a **property of log-linear interpolation across a wide
node gap**, not a source defect — the curve is calibrated to every tenor Citi
serves, so this gap only matters to someone asking for a tenor Citi does not
quote. It bounds what an off-node quote is worth on these curves, which is the
useful thing to know.

---

## 3. Is a forward residual a bias or noise?

A single day cannot tell those apart and they mean opposite things: a bias whose
mean dwarfs its standard deviation is a convention difference and will not average
away; noise around zero is a timing artefact. Measured over **44 business days**
to 2026-08-06 (`forward_stability.csv`).

> **This measurement changed a conclusion.** A first pass over 39 days had DKK's
> 1Yx1Y at mean +6.17 / sd 1.30 and it was written up as a bias. Over the wider
> window it is mean +3.16 / **sd 8.61**, range −22.3 to +12.8 — the single noisiest
> point in the entire set. The wider window is the one to believe, and the earlier
> reading was the flattering-looking answer arrived at from too little data.

**Residuals that survive averaging — real, and they will not average away:**

| curve | point | n | mean bp | sd bp | bias/noise |
|---|---|---|---|---|---|
| THB-THOR-1D | 10Yx10Y | 44 | **+4.304** | 0.386 | 11.2 |
| ZAR-ZARONIA-1D | 10Yx10Y | 44 | **+1.696** | 0.157 | 10.8 |
| MXN-FONDEO-1D | 10Yx10Y | 44 | **−2.879** | 0.272 | 10.6 |
| THB-THOR-1D | 5Yx10Y | 44 | **+1.437** | 0.158 | 9.1 |
| MXN-FONDEO-1D | 5Yx10Y | 44 | **−1.040** | 0.127 | 8.2 |

**Residuals that average away — every one of them at the 1Yx1Y point:**

| curve | point | n | mean bp | sd bp | min | max |
|---|---|---|---|---|---|---|
| DKK-TNDKK-1D | 1Yx1Y | 44 | +3.159 | **8.608** | −22.26 | +12.81 |
| AUD-AONIA-1D | 1Yx1Y | 44 | −0.880 | 1.827 | −6.69 | +3.08 |
| SEK-STINA-1D | 1Yx1Y | 44 | +1.377 | 0.756 | +0.31 | +3.77 |
| USD-FEDFUNDS-1D | 1Yx1Y | 44 | −0.435 | 1.059 | −5.70 | +1.47 |
| NZD-NZIONA-1D | 1Yx1Y | 44 | +0.076 | 1.385 | −2.99 | +3.48 |
| USD-SOFR-1D | 1Yx1Y | 44 | −0.214 | 1.109 | −5.67 | +1.89 |
| JPY-TONAR-1D | 1Yx1Y | 43 | −0.312 | 0.993 | −4.12 | +1.40 |
| CAD-CORRA-1D | 1Yx1Y | 44 | −0.063 | 0.792 | −1.91 | +3.11 |
| NOK-NOWA-1D | 1Yx1Y | 44 | −0.251 | 0.668 | −1.92 | +1.05 |
| DKK-TNDKK-1D | 1Yx10Y | 44 | +0.359 | 0.973 | −2.51 | +1.44 |

Two conclusions, and they need different words:

**The 1Yx1Y point is noisy for every currency, USD included.** It is the most
timing-sensitive point on the grid, and Citi's daily `PAR` row and daily `FWD` row
for the same date are evidently not stamped at the same instant — USD's own
1Yx1Y ranges over 7.5 bp across 44 days while its 10Yx10Y has an sd of 0.008 bp.
DKK's is extreme (±22 bp), which says its published front forward is unreliable in
Citi's own data, not that our curve is wrong. **The single-day AUD (−2.16 bp) and
DKK (+6.09 bp) failures in §2.3 are draws from this distribution, not defects.**

**THB, MXN and ZAR carry genuine long-end biases** of 1.0–4.3 bp at 5Yx10Y and
10Yx10Y, with the mean 8–11× the standard deviation. All three are approximate-
convention curves: `THB` and `ZAR` carry `provenance="market_standard"` (rateslib
ships no spec, so `curves/conventions.py` encodes market convention), and MXN's
28-day Fondeo roll is the fourth approximation in the table. **The tie-out has
localised the residual uncertainty onto precisely the curves whose provenance was
already flagged as approximate**, which is the most useful thing it could have
done.

Two hypotheses were tested and **rejected**:

* *Interpolation.* Rebuilding with a log-cubic spline from 1Y or 2Y moves these
  residuals by **less than 0.03 bp**. The Citi tenor axis is dense (44 points,
  including 15M/18M/21M and every year to 20Y), so there is little to interpolate.
* *Forward start convention.* Pricing the forward off the curve's reference date
  instead of spot (the `IRSwapQuery` `"5Yx10Y"` shorthand) moves them by ≤0.5 bp
  — reported per row as `fwd_shorthand_bp`.

**Do not price a THB, MXN or ZAR long forward off this source and expect it to
match Citi's screen to a basis point.** The par grid, which is what Citi actually
publishes for those curves, ties out to 0.002 bp on all three.

---

## 4. Verdict against the ±1bp target

| claim | status |
|---|---|
| all 20 curves fetchable in EOD / intraday / live with tz-aware timestamps | **yes**, 55/60 combinations; the 5 gaps are two genuinely dead/EOD-only curves and are reported, not hidden |
| swaps price through MDP → Query → Structure | **yes**, both backends, all three modes |
| NPV at the curve's own fair rate is zero | **yes**, 0.0000 on every curve, backend and mode |
| par rates tie out to Citi's quotes | **yes**, ≤0.0017 bp (rateslib) / ≤0.42 bp (QuantLib) |
| the two backends agree | **yes**, ≤0.11 bp |
| **forwards tie out to Citi's published forwards within ±1 bp** | **12 of 17 curves on all six points; 5 fail on 14 of 204 comparisons.** Of those, DKK and AUD are draws from a noisy 1Yx1Y point (§3) and only **THB, MXN and ZAR** carry a real bias — at 5Yx10Y and 10Yx10Y, 1.0–4.3 bp |
| the tie-out is mutation-verified | **yes** — §5 |

The honest one-line summary: **the source is correct on everything it can be
checked against independently, except that three currencies whose conventions were
already flagged approximate — THB, MXN and ZAR — disagree with Citi's own long-end
forwards by 1.0–4.3 bp, and that disagreement is stable rather than random.** The
other two single-day failures (DKK, AUD) are at the 1Yx1Y point, which is noisy
for every currency including USD.

**On the ±1bp target as stated:** it is met for 12 of the 17 curves Citi publishes
forwards for, and not met for 3 (plus 2 that are within their own noise). It
cannot be evaluated at all for `EUR-EONIA-1D`, `JPY-TONAR-1D-JSCC` and
`JPY-TONAR-1D-LCH`, because Citi publishes no forward tags for them — for those
three the only available evidence is that they reprice their own par grid
(≤0.002 bp) and that the two backends agree (≤0.11 bp), which is weaker and is
labelled as such rather than counted as a pass.

---

## 5. The tie-out was mutation-verified

A check that cannot fail reports success and hides what it was built to find.
Each of these was run and confirmed to fail:

| mutation | expected | observed |
|---|---|---|
| shift the timestamp by **+1 hour** | the curve must change | 10Y went 4.23287 → 4.24648; `test_an_hour_later_is_a_different_snapshot` |
| express the same instant in **UTC instead of ET** | the curve must be **identical** | identical to the digit; `test_the_same_instant_in_two_zones_asks_for_the_same_window` |
| remove the write-spacing discipline from the COM probe | the fake must raise `AccessViolation` | raised; `mutate_check` (a no-op `_advance_past` collides at row 10) |
| restore `abs()` in `calc_spread_rate` | the negative-rate tests must fail | 2 of 3 failed |
| tighten `max_reprice_error_bp` to 1e-15 | the builder must refuse | refused with the reprice message; `test_the_reprice_guard_fires_and_is_not_merely_decorative` |
| put a hole in one tenor of a grid | complete-row count must drop | dropped; `test_grid_report_counts_complete_rows_not_just_rows` |
| mark one tag bad in a batch | it must be reported, not dropped | reported; `test_a_tag_that_serves_nothing_is_reported_not_dropped` |

---

## 6. Adversarial review — findings

Reviewed as a hostile reader, hunting specifically for silent fallbacks, naive/aware
confusion, thin tenor grids, stale-served-as-live, and `None` becoming a plausible
number. **Thirteen defects found, all fixed.** Eight were in code this work added;
five were pre-existing and this source is simply the first thing to reach them.

### Found in this work

**F1 — EOD staleness was measured against 23:59:59, so every EOD request tripped
the 12-hour guard.** Daily rows are stamped at midnight, making every EOD snapshot
look 24 h stale. All 20 curves failed. *Fix:* a separate `max_eod_gap` measured in
days (default 7), and the lag measured from the start of the requested day.

**F2 — `pandas.Timestamp` is a `datetime` subclass, so the midnight-means-EOD rule
was unreachable.** `pd.Timestamp("2026-08-06")` silently became an *intraday*
request at midnight, which resolves to the previous evening's last print. *Fix:*
dispatch on bare `date` first, then on exact-midnight, then intraday; pinned by
`test_pandas_timestamp_is_not_swallowed_by_the_datetime_branch`.

**F3 — `from_wire_naive` raised on both DST edges.** `Timestamp.tz_localize`
raises `AmbiguousTimeError` on the repeated fall-back hour and
`NonExistentTimeError` on the spring-forward gap — one snapshot a year would have
been an unhandled crash inside a curve build. The docstring claimed `fold=0`
handled it; that is true of `datetime.replace`, not of pandas. *Fix:*
`ambiguous=True`, `nonexistent="shift_forward"`, both documented and tested.

**F4 — `IRSwapValue.RATE` returns percent for an outright and basis points for a
two- or three-leg package.** The first tie-out scaled by 100 and reported 44,566 bp
"errors". A units slip that landed inside a plausible range would not have been
obvious. *Fix:* no scaling, the reason spelled out, and `query_par_rate` now
raises if handed anything but a single-leg package.

**F5 — the intraday probe's fixed NY-morning window reported "no intraday
history" for every Asian curve.** It was the middle of their night. *Fix:* two
probe windows (10:00 and 02:00 ET); coverage went from 12/20 to 18/20 at one
month and 15/20 to 19/20 at one year.

**F6 — `CVTSHIST` at `HOURLY` with a relative `period=` returns no block at all**
(instantly, not a timeout), while `HOURLY` with explicit bounds works. The
session-fingerprint stage relied on it and produced a confident "no intraday data
for all 20 curves". *Fix:* stage removed; the same information is derived from the
`MI01` data already banked. Recorded as a wire fact.

**F7 — an Asian curve's morning session was dated a business day early.** Citi
stamps everything in ET, so Tokyo's morning (19:00–23:59 ET) falls on the
*previous* ET calendar date. Dating a snapshot by `snapshot_at.date()` therefore
put every intraday or live JPY, AUD, NZD, SGD or THB request in that window one
business day back, shifting spot and all 44 maturities by a day. *Measured, not
reasoned:* on JPY_TONAR the session runs 19:00 ET → 06:59 ET next day as one
continuous block (the 23:59 print and the following 00:00 print are the same
number, 2.6425), and it matches Citi's DAILY row for the **later** date — ET 08-06
19:00–23:59 ended at 2.6575 against a DAILY 08-07 of 2.6500, while DAILY 08-06 was
2.6300. *Fix:* a `local_timezone` per curve; intraday and live snapshots are dated
by the curve's own market calendar. **EOD deliberately keeps the ET date** — an
end-of-day row carries the label Citi assigned it, and re-deriving that label
through a local zone would move MXN's backwards (midnight ET is the previous day
in Mexico City). Both directions are pinned by tests.

**F8 — setting QuantLib's global evaluation date inside a getter.** The QL branch
must do it — `QLIRSwapCurve`'s pricer builds instruments outside any pinned block,
so a 2026-08-05 curve would otherwise be priced with today's spot date — but it is
a global side effect of asking for a curve. Not a defect so much as a hazard;
documented at the call site and recorded on `meta_data["ql_evaluation_date"]`.

### Pre-existing, reached first by this source

**F9 — `calc_spread_rate` took `abs()` of every leg's fair rate.** Invisible while
every rate in the book is positive; wrong the moment one is not. CHF SARON's front
is −0.055314% and came back as +0.055314% — an **11.06 bp** error, exactly twice
the rate. A CHF 1s10s curve trade straddling zero was out by a similar amount the
other way. *Fix:* use the signed rate; `tests/test_irswap_value_negative_rates.py`,
mutation-verified.

**F10 — rateslib 2.7.1 rejects both `None` and an empty Series for
`leg2_rate_fixings`.** Measured: omitting the argument prices, `None` raises
`ValueError`, an empty Series raises `IndexError` from `index[-1]`, a non-empty
Series prices. Nineteen of the twenty curves have no fixings source in this repo,
so all nineteen were unusable through `IRSwapQuery`, failing inside rateslib with
a message about fixing containers that says nothing about the cause. *Resolved by*
`utils.rl_compat.rate_fixings_kwargs`, which landed on main mid-session and
returns `{}` for exactly those two cases.

**F11 — the rateslib solver was seeded at 1.0 for every node, which diverges on a
high-rate curve with a long tail.** `MXN_T_FONDEO` (8.47–8.59% to 50Y) and
`ZAR_ZARONIA` (8.26–8.44%) both hit `max_iter` with `f_val: nan`; bisection put the
boundary at the same place for both (the 40-tenor prefix to 30Y converged, adding
35Y did not). Nothing in either grid is degenerate. *Fix:* seed each node at
`exp(-par_t · t)`. The fixed point is unchanged and the reprice guard checks the
result either way; only whether an answer is produced at all changes.

**F12 — `CVLATEST`/`CVSNAP` scalar grids were parsed by compaction, so one dead
curve blanked every live one beside it.** Six tags where one is discontinued
returns six rows, one blank; compacting the blank away made the count disagree and
returned `(None, None)` for **all six**. *Fix:* positional alignment.

**F13 — a price cell was read as a timestamp.** `CVSNAP` publishes no stamp, and
`coerce_excel_datetime(4.23287)` happily returns `1900-01-03 05:35:20`, so the 10Y
rate was reported as the quote's own timestamp. *Fix:* a stamp is only taken from a
cell that is genuinely a datetime, or from a *different* cell whose serial is past
1990.

### Checked and found clean

* **No silent curve substitution.** `JPY-TONAR-1D-JSCC` never falls back to
  `JPY-TONAR-1D`; an unknown curve name raises and lists the twenty.
* **No stale-served-as-live.** Every snapshot carries a lag; past `max_staleness`
  it raises. Verified against a two-day-old grid.
* **No thin-grid curve.** Fewer than `min_tenors` raises rather than solving
  trivially; tenors that did not serve are named on the snapshot.
* **No mixed-instant curve.** Per-tenor as-of makes it possible for one illiquid
  tenor to be hours behind the rest, so the spread is measured, warned at 30 min
  and raised at 6 h.
* **The old `CITIVELO` source is untouched** — different token, different fetcher
  cache, no shared code path.
