# SFR "Fade the Kink" v2 — Findings

**Date:** 2026-07-30
**Branch:** `feat/sfr-kink-fade-v2`
**Design:** `2026-07-30-sfr-kink-fade-v2-design.md`
**Notebooks:** `notebooks/backtests/sfr_kink_fade_backtest.ipynb` (executed;
40 code cells, 133 outputs, 15 figures, 0 unrun, 0 errors; 264s) and the
follow-up `sfr_kink_fade_curvefit.ipynb` (14 code cells, 127 outputs, 8 figures,
0 unrun, 0 errors; 151s)
**Outputs:** `notebooks/data/sfr_kink_fade/`

## The question

> Does removing the FOMC meeting structure turn the kink into a real signal, or
> was the prior RED verdict right for a deeper reason?

## The answer

**No, and the prior RED verdict was right — but for none of the reasons anyone
had, including this lab's own hypothesis.**

The meeting-calendar story is correct arithmetic and empirically negligible.
What the meeting fit *actually* does is remove a **smooth** component from the
butterfly, and that genuinely helps — the residual mean-reverts where the raw
fly does not (cross-sectional IC −0.18 against +0.01 at 21 days). But a calendar
with the **wrong dates** does it just as well, an **evenly spaced** pseudo-calendar
that cannot carry calendar information at all does it *better*, and a plain
**cubic spline in slot index** beats every meeting basis on the whole sweep
distribution. The improvement is smoothing. It is not meetings.

Four independent tests were run against the hypothesis and **it failed all
four**: the size (§1 — 1–6% of the fly's variance), the mechanism (§1 — a
cross-sectional r² of 1.1% and sign agreement on 46.5% of dates, a coin flip),
the placebos (§2), and the calendar-symmetry conditioning (§4b), which looked
like the one win until the move sizes on each side of the split were measured
and turned out to explain the entire gap.

And it is still not enough. **0 of 28 league rows are ALIVE and 0 of 28 have a
positive grid median.**

| | |
|---|---:|
| league rows | 28 |
| **ALIVE** | **0** |
| SELECTION-ARTIFACT | 8 |
| MARGINAL-maker-only | 11 |
| DEAD | 8 |
| DEAD (too few trades) | 1 |
| rows net positive **gross** | 20 / 28 |
| rows net positive at taker (**2.0bp per contract**) | 9 / 28 |
| rows with a positive **grid median** | **0 / 28** |
| median DSR probability | **0.0000** (threshold 0.5) |

The follow-up notebook `sfr_kink_fade_curvefit.ipynb` (§8b) writes 14 more rows
into the same table. Combined: **42 rows, 0 ALIVE, 0 with a positive grid
median**, 30 net positive gross and 14 net positive at taker.

The least-dead row, for the record:

| framework | n | avg net | gross | net @2.0bp | grid median | DSR | non-overlap SR | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| K1L. meeting residual (6m, front8, 2019+) | 119 | +2.04bp | +480.5 | **+242.5** | −351.6 | 0.000 | −0.12 | SELECTION-ARTIFACT |

Positive at taker over 119 trades with a 47% hit rate — and the best corner of a
sweep whose median config loses 351bp, with a deflated-Sharpe probability of
zero and a *negative* non-overlapping Sharpe. That is what a selection artifact
looks like.

---

## 1. The calendar hypothesis, measured

SR3 settles on the day-weighted compounded average of overnight SOFR over its
IMM quarter, so a butterfly on three consecutive contracts inherits curvature
from wherever the FOMC happens to meet inside those quarters. Define
`phi_sum = 2·M_belly − M_front − M_back`, with `M` the day-weighted *cumulative*
meeting count at each leg — so `phi_sum` is the butterfly a path of exactly
**1bp per meeting** would print. It is pure arithmetic, known years ahead, and
contains no market data. (`M`'s absolute level depends on where the meeting list
starts and is meaningless on its own; only differences of it are used, and the
common prefix cancels in every one.)

The butterfly the calendar actually creates is `phi_sum × pace`. Both factors are
small:

| regime | fly sd (bp) | median \|pace\| (bp/mtg) | calendar fly sd (bp) | **share of fly variance** |
|---|---:|---:|---:|---:|
| ZIRP | 4.71 | 2.08 | 0.77 | **2.7%** |
| HIKING | 10.39 | 3.53 | 1.05 | **1.0%** |
| PLATEAU | 5.06 | 2.12 | 1.20 | **5.6%** |
| CUTTING | 3.40 | 2.12 | 0.45 | **1.7%** |

`phi_sum` has a standard deviation of **0.11–0.14 meetings** across every
constant-maturity slot, and the pace *between a 3m fly's own two wings* — which
are only two quarters apart — has a median absolute value of **1.99bp per
meeting**. The product is a few tenths of a basis point against a fly whose daily
standard deviation is several basis points.

This is where the a-priori reasoning went wrong, and it is worth being precise
about why. In the 2022-23 hiking cycle the Fed moved 50–75bp per *meeting*, so
"the calendar is worth ±0.2 meetings × 60bp = ±12bp" looks compelling. But a
butterfly does not see the level of the policy path — it sees the **second
difference along the strip**, and the relevant `pace` is the average jump between
two contracts two quarters apart, which is the *slope of the strip* divided by
the number of meetings in it. Even in the hiking cycle that measures 3.5bp per
meeting, not 60. The calendar effect is real and it is about one part in fifty.

### The direct test

Theory says `fly_k = Σ_m δ_m · Φ_{k,m}`, so under a locally uniform path the
cross-section of flies on a date should be proportional to the cross-section of
`phi_sum`, with slope equal to the pace. Regressing one on the other, once per
date over 1,149 sessions:

| | |
|---|---:|
| median cross-sectional r² of `phi` alone | **1.1%** |
| corr(fitted slope, independently measured pace) | **+0.099** |
| share of dates the two agree in **sign** | **46.5%** |
| median \|fitted slope\| | 2.88 bp/meeting |
| median \|measured pace\| | 1.99 bp/meeting |

The fitted slope agrees in sign with the measured pace on a coin flip. **The
market does not price butterflies as (pace × calendar curvature).**

### The calendar is validated, even though the hypothesis is not

Worth separating, because the calendar itself is now a reusable asset:

* 32 of 32 decision dates over 2023-01 → 2026-12 match
  `Query/IRSwaps/_CENTRAL_BANK_DATES` exactly — an independently maintained
  in-repo copy.
* The lab's own regime boundaries land on meetings (2022-03-17 after liftoff,
  2023-07-27 after the last hike, 2024-09-18 the first cut).
* For 2018-2022, where **no in-repo source exists**, the empirical check holds
  **pooled and only pooled**: front SR3 rates move **1.41×** as much on decision
  days (and the day after, when the range takes effect) as on other sessions,
  Welch **t = 2.97**. Per year: 2019 1.58× (t 1.48), 2021 1.82× (t 1.71), 2022
  1.36× (t 1.93) — **not one year clears t = 2**. 2018 is a flat policy year and
  2020's realised moves came from the **unscheduled** March cuts, which are
  deliberately not in the schedule because nobody could price them; both read
  below 1.0.

  **The first version of this check was wrong, and wrong in the flattering
  direction.** It pivoted rates by constant-maturity *slot* and differenced, so
  slot 1 became a different contract at every IMM roll — a splice worth tens of
  basis points. SR3 rolls on the third Wednesday of March, June, September and
  December, and so, very often, does the FOMC: **22 of the 33 IMM rolls in this
  sample are themselves FOMC decision dates**, and six of the twelve largest
  "daily moves" in the panel were pure roll splices (54.5, 51.9, 49.6, 46.3,
  44.3, 34.1bp against a typical 2–5bp). That version printed 2.12× at t = 4.13.
  Differencing each **contract** against its own prior settle — which cannot
  cross a roll, and discards no genuine FOMC day — gives the numbers above.
  Roughly half the original effect was the roll, not the Fed.

---

## 2. The placebo controls — the section that decides it

The meeting fit is a flexible basis, and *any* flexible smoother leaves a
residual that mean-reverts better than the raw level. So the real schedule was
run against decoys with the same number of knots, each with its penalty `lam`
tuned so **its residual has the same standard deviation** (5.661bp on the 6m
fly). Note that with the scale matched, `1 − var(resid)/var(fly)` is identical
*by construction* and carries no information — the discriminating statistics are
the residual's forward-predictive IC and its backtest.

**Per-date cross-sectional IC vs the forward move (6m flies, 2022+):**

| basis | resid sd | IC h=5 | IC h=10 | **IC h=21** |
|---|---:|---:|---:|---:|
| **real FOMC calendar** | 5.661 | −0.127 | −0.141 | **−0.175** |
| calendar shifted +21d | 5.661 | −0.129 | −0.146 | −0.181 |
| calendar shifted +45d | 5.661 | −0.133 | −0.150 | **−0.186** |
| evenly spaced 8/yr | 5.661 | −0.127 | −0.145 | −0.177 |
| cubic spline in slot index | 4.459 | −0.124 | −0.144 | −0.174 |
| **raw fly, z-scored (the K0 definition)** | 19.998 | −0.042 | −0.028 | **+0.008** |
| raw fly, scale-only (handicapped control) | 19.998 | −0.029 | −0.029 | −0.027 |

Each basis is scored on **the signal it actually trades**, i.e. after its own
standardisation. That distinction is load-bearing and getting it wrong was one
of this lab's own bugs (§7b.2): a residual's zero is a fitted fair value, so it
keeps it; the raw fly's zero is not, so it gets a full trailing z-score. Both
raw-fly versions are shown.

**Backtest, identical grid / engine / 2.0bp cost:**

| basis | grid median | % positive | best net | best avg/trade | best Sharpe |
|---|---:|---:|---:|---:|---:|
| **real FOMC calendar** | −631.6 | 4.2% | **+187.3** | +0.84 | +0.31 |
| calendar shifted +21d | −623.1 | 2.8% | +99.0 | +0.64 | +0.20 |
| calendar shifted +45d | −671.0 | 2.8% | +143.8 | +0.91 | +0.29 |
| evenly spaced 8/yr | −624.5 | 2.8% | +55.3 | +0.35 | +0.11 |
| **cubic spline in slot** | **−459.1** | **8.3%** | +155.3 | **+0.98** | **+0.54** |
| **raw fly, z-scored (K0)** | −474.8 | 0.0% | −43.5 | −0.27 | −0.13 |
| raw fly, scale-only (handicapped) | −694.6 | 0.0% | −167.8 | −1.12 | −0.23 |

Read those two tables together, **and be precise about which column**, because
they do not agree:

1. **Smoothing produces the mean reversion.** The raw 6m fly has essentially no
   cross-sectional mean reversion (IC **+0.008** at h=21, i.e. the wrong sign);
   every smoothed basis is at **−0.17 to −0.19**. That is a real and useful
   finding — it just is not the finding this lab set out to make.
2. **On best config, smoothing wins; on the distribution, it does not.** Every
   smoothed basis beats the raw fly's best corner (−43.5bp), but the meeting
   bases have a **worse grid median** than the raw fly does (−623 to −671 against
   −474.8). A better best corner with a worse median is a **wider sweep, not a
   better signal** — the signature of a noisier input. Only the spline improves
   both.
3. **The meeting structure contributes nothing identifiable.** The real calendar
   is inside the decoy range on grid median, and it is *not the best decoy* on
   the IC — the +45-day shift and the evenly-spaced pseudo-calendar both beat it
   at every horizon. The evenly-spaced calendar carries **zero** calendar
   information by construction.
4. **A cubic spline in slot index is the better tool.** It wins on grid median,
   share of positive configs, best average bp per trade and Sharpe, with a
   smaller residual and no meeting machinery at all.
5. **Nothing has a positive grid median.**

---

## 3. The pond — why none of it pays

The prior lab established that the binding constraint is move size, not sign.
This lab measures it directly: on the days each signal fires, what is
`E[|level[t+h] − level[t]|]` — what a trader with perfect foresight of the
*direction* would capture, before any signal skill is required?

**3m flies** (round trip 2.0bp):

| signal | h | mean \|move\| | selectivity | **oracle net** | P(move > cost) |
|---|---:|---:|---:|---:|---:|
| unconditional | 21 | 1.77 | 1.00 | −0.23 | 0.24 |
| K0 raw z | 21 | 2.45 | 1.38 | **+0.45** | 0.34 |
| K1 meeting residual | 21 | 2.47 | 1.39 | **+0.47** | 0.35 |
| K1z residual, re-centred | 21 | 2.82 | 1.59 | **+0.82** | 0.38 |

**6m flies:**

| signal | h | mean \|move\| | selectivity | **oracle net** | P(move > cost) |
|---|---:|---:|---:|---:|---:|
| unconditional | 21 | 5.10 | 1.00 | +3.10 | 0.52 |
| K0 raw z | 21 | 6.31 | 1.24 | **+4.31** | 0.62 |
| K1 meeting residual | 21 | 5.93 | 1.16 | **+3.93** | 0.56 |

Three things follow.

* **Every kink signal does select bigger moves** — selectivity 1.16–1.59. That
  part of the thesis survives.
* **The 3m butterfly cannot pay.** With *perfect direction-calling* it clears the
  round trip by half a basis point at the best horizon and loses at every shorter
  one. No definition of a kink can fix that; the pond is smaller than the boat.
* **The 6m butterfly can.** It carries **2.91×** the dispersion of the 3m fly
  (pooled sd 20.0bp vs 6.87bp) for the *identical* four-contract, 2.0bp cost, and
  its oracle clears the round trip by ~4bp. Every league row that is positive at
  taker is a 6m row. **If anything here is ever tradeable it is a 6m fly held
  about a month**, and that is the single most useful redirection in this lab.

---

## 4. What the new definition earns — and what did not survive

One result is real and matters more for how one builds the next thing than for
this strategy's P&L. The second looked real until it was controlled.

### 4a. It stops the butterfly being a directional trade in disguise

The prior lab's most damaging diagnostic was that the outright belly on the
identical signal beats the fly in 16 of 24 frameworks — "a fly z-score contains a
directional rates signal, and the butterfly packaging spends three legs of spread
to express what one leg expresses better."

Split by definition:

| | belly beats the fly |
|---|---:|
| **raw-fly** frameworks (K0, K2, K4, K4b, K3) | **7 of 8** |
| **meeting-residual** frameworks (K1, K1z, K1f, K1L, K3r) | **2 of 6** |
| all | 9 of 14 |

Removing the smooth component removes most of the rates-direction leak. On the
headline row the fly makes **+187.2bp** while its own outright belly makes
**−87.5bp**, and on the least-dead row (K1L) **+242.5bp** against **+109.5bp** —
the first frameworks in either lab where the butterfly is clearly the right
instrument. It does not make the fly pay; it makes it an honest fly.

The contrast is stark on the other side too: on `K0L` (raw z-score, 6m,
front8) the fly makes +237.8bp while the **outright belly makes +1430.5bp** on
the identical signal. That is a rates-direction trade wearing three legs, and it
is what a raw fly z-score has been all along.

**Costing correction.** `RVUtils/MeanRev/shadow.py::shadow_table` charged every
instrument its **leg** count, so the butterfly paid 1.5bp round trip while every
shadow's leg count and contract count coincide — handing the fly a **0.5bp per
trade advantage in exactly the comparison the shadow test exists to make**. Fixed
with a `cost_mode='per_contract'` switch (default unchanged, so the prior lab's
published shadow numbers stay reproducible) which the kink lab sets. It moved the
headline framework from +299.2bp to +187.2bp and the overall count from 8 of 14
to **9 of 14**. The direction of the correction is the honest one: the fly looks
worse, not better.

### 4b. Conditioning looked like it worked — until the pond was measured

The one test whose result *supports* the calendar story. If part of the raw fly's
curvature is calendar, fading it should work less badly when the two halves span
the same integer number of meetings.

**It is a static partition of keys, not a day-by-day gate.** A key's legs are
three fixed contracts, so the meeting count between their IMM start dates never
changes over the key's life and `asym` is constant per key by construction. K4
and K4b therefore split the *universe* into two disjoint sets of butterflies,
and any difference between them is confounded with everything else that differs
about those contracts — including how far they move. The notebook prints the
pond for each side so that confound is visible; this was not obvious when the
test was designed and it materially weakens the reading:

| | `asym == 0` (symmetric) | `asym != 0` (asymmetric) |
|---|---:|---:|
| keys | 14 | 16 |
| fade, median of the sweep | **−153.1bp** | **−308.0bp** |
| momentum, median of the sweep | −296.4bp | −242.8bp |
| **is fade the winning sign?** | **yes** | **no** |
| loss per trade | −1.47bp | −2.57bp |
| **mean \|21d move\|** | **6.48bp** | **3.88bp** |

The first five rows look like a **1.1bp per trade** conditioning effect with the
sign of the right trade flipping — the correct order of magnitude for a
mechanism worth 1–6% of variance, visible in conditioning and invisible in the
level. That is how it was written up before the last row was computed.

**The last row removes it.** The symmetric keys move **1.67×** further over 21
days than the asymmetric ones, and the loss-per-trade ratio is **1.75×**. A
fixed 2.0bp round trip is a smaller fraction of a bigger move, so a bucket that
moves 1.67× further loses about 1.7× less per trade for reasons that have
nothing to do with the Fed. The two ratios agree to within 0.08.

So the symmetry split is a **move-size effect wearing a calendar label**, and
this lab has *no* surviving evidence for the meeting hypothesis — not the size
(§1, 1–6% of variance), not the mechanism (§1, r² = 1.1%, sign agreement 46.5%),
not the placebos (§2), and not this.

### 4c. And one place it is fragile

The projection rule for 2028+ was expected to be a footnote. It is not, for the
back of the strip. Shifting the projected meetings by **one week** in either
direction:

| shift | residual sd | median key corr | **worst projected key corr** |
|---:|---:|---:|---:|
| −1 week | 5.730 | 1.000 | **−0.320** |
| 0 | 5.661 | 1.000 | 1.000 |
| +1 week | 5.676 | 1.000 | **+0.268** |

The median correlation is 1.000 at every shift and is **uninformative by
construction** — the median key never spans a projected meeting. The binding
number is the worst of the **11 of 30** keys that do, and one week of projection
error effectively destroys the signal on it.

Nothing tradeable rests on those keys (§3 already showed the back of the strip
cannot pay 2.0bp on move size, and both headline rows are front-of-strip), but
the reading is the same as everywhere else in this lab: **the part of the signal
that genuinely depends on the meeting calendar is the part that is least
reliable.**

---

## 5. Regime, and the sign

Unchanged from the prior lab, and worth restating because it is the largest
single driver of everything above. Summed across all 14 frameworks' best configs:

| regime | total net bp | frameworks positive | trades |
|---|---:|---:|---:|
| ZIRP | +151.2 | 3 / 14 | 127 |
| **HIKING** | **+1029.8** | **12 / 14** | 394 |
| PLATEAU | +186.0 | 7 / 14 | 283 |
| **CUTTING** | **−569.8** | 5 / 14 | 608 |

**Fade beats momentum in 10 of 14 frameworks.** Mean reversion is the right
direction; it is the cost and the instrument that fail.

---

## 6. Was the prior RED verdict even testing anything?

**No — and this is the most consequential thing found here.** The incumbent
`sfr_kink_fade_backtest` runs through `QueryDrivenBacktest`, and on that path the
traded direction never reaches the P&L:

* `Query/IRSwaps/IRSwapStructure.linear_solve_for_risk_weighted_notionals`
  returns `notionals = (risk_weights * R) / bpvs` with `R > 0` by construction
  (`np.copysign` forces the constrained leg's contribution to match its risk
  weight's sign), so **every leg's notional carries the sign of its risk weight**;
* `RLIRSwapCurve.resolve_pricable(swap, risk_weight)` then computes
  `sign = -1 if risk_weight < 0 else +1` and returns `notional_real * sign`, i.e.
  **`|notional|` on every leg**;
* `bpv = +100k` and `bpv = −100k` flip every risk weight together, so both
  resolve to the *identical* all-payer package;
* `PositionHandler._resolved_pricables` feeds that resolved package to both the
  entry NPV and the mark.

So a `buy_kink` and a `sell_kink` on the same structure are priced as the same
trade. The RED conclusion survives this lab's own re-test, but the evidence
originally offered for it was invalid. This is a shared Query/BT pricing seam
used by other strategies, so it is reported rather than fixed here — the blast
radius is every `QueryDrivenBacktest` strategy that uses a signed `bpv`.

Nothing in this lab touches that path: everything marks on raw SR3 settlement
prices through `RVUtils/MeanRev/engine.py`, where P&L is
`direction × (level[exit] − level[entry])` and there is no mark model to get
wrong.

---

## 7. Bugs and data defects found

1. **2025-07-04 is a corrupt session in the built SFR panel.** US Independence
   Day, a market holiday, carries a panel row built from **8 contracts — H29 …
   Z30, every one with zero open interest**. The strip builder ranked those deep
   back months into slots 1–8, so `slot 1` is a four-year-forward contract; the
   front slot prints a **−57bp** jump in and **+58bp** out, and every structure
   that day is mislabelled (`H29-M29-U29` tagged `SFR123`). It is the only
   session in the file with fewer than 16 contracts. Now dropped by default in
   `sfr_fly_meanrev_common.BAD_DATES`; reproduce with
   `notebooks/rv/_probe_kink_bad_dates.py`. The 2026-07-29 fly mean-reversion
   findings were written before this was found and include it — one session of
   1,150.
2. **`RVUtils/SFRRVLab/lattice.py::solve_meeting_jumps` shrinks toward the wrong
   prior for this purpose.** Its ridge penalises the jumps themselves, i.e. it
   shrinks toward "the Fed does nothing". That is right for a FedWatch lattice
   null and wrong for a fair-value fit, where the prior should be a *smooth
   path*. `RVUtils/MeanRev/meetings.py::solve_smooth_path` penalises the second
   difference instead, so a linearly accelerating policy path sits in the null
   space and is fitted for free. Not a bug in `lattice.py`; a different tool.
3. **`r² = 1 − var(resid)/var(fly)` is tautological under scale matching.** An
   earlier version of the placebo table compared explained variance across
   calendars whose `lam` had been tuned to a common residual scale, and got
   0.783 for all five — identical by construction. Caught before it reached the
   notebook; the notebook says so explicitly where the number is printed.
4. The prior lab's **birth-slot attribution bug (its bug 11) is easy to
   reintroduce.** A key's CM slot rolls, so grouping panel *columns* by a key's
   first label mis-buckets almost everything — it put 10,498 of 16,086
   observations in `SFR-14-15-16`. `sfr_kink_fade_common.cm_variance_decomposition`
   does the attribution on the long frame per `(date, key)`, and the front-slot
   restriction is applied through the `(date, key)` gate rather than a key filter.

## 7b. Defects found in **this lab's own code**, by adversarial review

Every one of these was caught by a review pass run against the finished
notebook, and four of them changed a number this document reports. They are
listed because the pattern is more useful than the individual fixes: **every
single one flattered the hypothesis being tested.**

1. **The 2018-2022 calendar validation was measuring the IMM roll.** §1. The
   original check reported 2.12× at t = 4.13; the correct one reports 1.41× at
   t = 2.97, and no individual year clears t = 2. Fixed by differencing each
   contract against its own prior settle;
   `sfr_kink_fade_common.imm_roll_fomc_collisions` now prints the collision
   count next to the audit so the hazard is impossible to miss.
2. **The placebo section handicapped its own baseline.** Every panel was
   standardised with `scale_only_zscore`, which keeps the model's zero. That is
   right for a *residual* and wrong for the *raw fly level*, whose zero means
   nothing — a 6m fly parked at −13bp for a year is not a permanent two-sigma
   dislocation. The raw-fly control now gets a full trailing z-score (which is
   also the incumbent K0 definition) and the handicapped version is kept
   alongside it, labelled.
3. **The shadow test charged the butterfly per leg.** 1.5bp instead of the
   2.0bp per-contract figure the rest of the lab is built on, while every
   shadow's leg count and contract count coincide — a 0.5bp per trade subsidy
   in precisely the comparison the shadow test exists to make. Fixed with
   `cost_mode='per_contract'`; it moved the headline framework from +299.2bp to
   +187.2bp.
4. **Prior-lab bug 11 was reintroduced sixty lines above the cell that warns
   about it.** K3/K3r bucketed the cross-section by each key's *birth* pack
   colour, and a key's pack rolls with its slot. Fixed by dropping the bucket
   entirely: `xsection_signal(window=...)` already converts each key to its own
   trailing z-score, which is scale-free across maturities and is what the
   bucketing was there to achieve.
5. **`asym` is constant per key, so K4/K4b is a static partition and not a
   gate.** §4b. The cell now says so and prints the pond on each side.
6. **`project_year(shift_weeks=n)` compounded the shift**, displacing meeting
   *k* by *k·n* weeks — so §12's "shift the projection by a week" was moving
   December by seven. The sensitivity result was therefore *overstated*. Fixed
   to translate the year uniformly.
7. **The projection fidelity table in the docstring was wrong** and untested.
   Real figures now measured against all ten known years and pinned by
   `test_projection_fidelity_against_every_known_year`.
8. **`oracle_table` raised `KeyError` when a signal never fired**, taking down
   the whole pond block — the diagnostic that runs *before* the grids.
9. **`meeting_count_gaps` used `[a, b)` while `calendar_fly_panel` used
   `(a, b]`** for the same quantity, and only the latter matches the day-weight
   convention. Now pinned together by a boundary test.
10. **`mtg_front` / `mtg_belly` / `mtg_back` were documented as in-quarter
    meeting counts.** They are *cumulative* counts from the start of the
    supplied meeting list, so their absolute level is arbitrary. Only
    differences of them are used, and only differences are meaningful;
    documented, and `in_window_meeting_count` added for the quantity people
    will actually reach for.
11. **The conditioning ridge shrank the base rate toward zero**, and
    `solve_smooth_path(fit_base=False)` silently defaulted the base to
    `min(strip)`. Both fixed; the second now raises.
12. **`r² = 1 − var(resid)/var(fly)` is tautological under scale matching.** An
    earlier placebo table compared explained variance across calendars whose
    `lam` had been tuned to a common residual scale and got 0.783 for all five
    — identical by construction. Caught before it reached the notebook, which
    now says so where the number is printed.

## 8. Closed questions

* **Is the prior lab's fitted level-neutral wing split (0.463/0.537) the meeting
  calendar?** **No.** The calendar-implied tilt has almost exactly the same
  *range* — front share 0.4615 to 0.5385 — which is what made the idea worth
  testing, but it is centred on **0.4999** against the fitted **0.4592**, and the
  two are uncorrelated across keys (**+0.042**). The fitted tilt is something
  else.
* **Is the fade only real when `fomc_asym == 0`?** **No.** It is less bad on the
  symmetric keys and the winning sign flips, but `asym` is constant per key, so
  the split is a static partition of the universe rather than a gate, and the
  symmetric bucket simply moves 1.67× further — which accounts for the whole
  difference (§4b). Neither side is profitable.
* **Does a kink defined against a fitted curve beat one defined against its own
  history?** On the *best config* yes, decisively; on the *sweep distribution*
  only the cubic spline in slot index does, and the meeting-space fits are worse
  than the plain z-score (§2). "Fit a curve" is the right instinct; "fit the
  meeting calendar" is not the right curve.
* **Is a butterfly's curvature mostly the FOMC/IMM calendar?** **No** — 1–6% of
  its variance, and a cross-sectional r² of 1.1%. The premise the whole lab was
  built to test is quantitatively wrong, and the reason is that a fly sees the
  *second difference* along the strip: the relevant pace is not 50bp per meeting
  but the strip slope divided by the meetings inside it, which measures ~2bp
  even in a hiking cycle.

## 8b. The three follow-ups, run

The three leads this document ended with were all executed. **Two produced
useful measurements and one falsified its own recommendation.**

### 8b.1 The shadow re-audit at per-contract cost — CONFIRMED, and slightly worse

`notebooks/rv/_reaudit_fly_meanrev_shadows.py`. No re-run was needed: cost enters
net P&L linearly and once per completed trade, so `net(c) = gross - c*n`, and the
stored table carries both. The identity was asserted first and reconciles to the
CSV's 1-decimal rounding on all 96 rows.

| | per LEG (published) | per CONTRACT (correct) |
|---|---:|---:|
| outright belly beats the fly | 16 / 24 | **17 / 24** |
| any shadow beats the fly | 22 / 24 | 22 / 24 |

One framework flipped: *5. Kalman local-level (3m, liquid16)*, whose fly went
from −184.5bp to −270.0bp and fell below its own belly. The prior lab's
conclusion was **understated**, exactly as the arithmetic requires — the fly is
charged 0.5bp/trade more and every shadow is unchanged, so the count can only
rise.

### 8b.2 Wider spacings — the pond scales, and cost stops being the constraint

9m and 12m butterflies were never built by either prior lab. They are now
(`build_sfr_fly_structures.py --spacings 1 2 3 4`), and **all four are the same
four contracts and the same 2.0bp round trip**:

| spacing | pooled sd | round trip in days of typical movement | best signal oracle net, h=21 |
|---|---:|---:|---:|
| 3m | 6.87bp | 2.08 | +0.77bp |
| 6m | 20.00bp | 0.86 | +4.31bp |
| 9m | 34.08bp | 0.58 | +8.42bp |
| **12m** | **46.64bp** | **0.42** | **+11.62bp** |

Widening the spacing is the only lever found in three labs that improves the
cost-to-move ratio for free, and it improves it by a factor of five.

**And it still is not enough.** `notebooks/backtests/sfr_kink_fade_curvefit.ipynb`
runs the full house treatment on all four: **0 of 14 curve-fit rows ALIVE, 0 with
a positive grid median.** The best row is the 12m curve-fit residual at
**+666.2bp net over 156 trades (+4.27bp/trade, 50% hit)** — against a grid median
of **−275.8bp** and DSR 0.002. `SELECTION-ARTIFACT`.

That is the useful reframing. On the 3m fly the binding constraint was **cost**:
the pond was smaller than the boat. At 12m the pond is five times the boat and
the constraint moves to **signal quality** — and the signal is not there. Both
failures are real and they are different failures, which is worth knowing before
anyone widens the spacing again expecting the first problem to be the only one.

### 8b.3 "Keep the model's zero" — MY OWN RECOMMENDATION, FALSIFIED

This document recommended sweeping the pairing of `scale_only_zscore` (divide by
a trailing sd, keep the fitted model's zero) with the `z0` exit ("exit at fitted
fair value"), on the grounds that it produced the winning configs here and had
never been a grid axis. It has now been swept as one:

| standardisation | configs | median net bp | % positive | best net bp |
|---|---:|---:|---:|---:|
| `scale` (keep the model's zero) | 144 | **−289.1** | 20.8% | +666.2 |
| `z` (re-centre on a trailing mean) | 144 | **−266.6** | 27.8% | +491.5 |

`scale` owns the best single corner and `z` owns the distribution — which is the
same "wider sweep, not better signal" pattern §2 identified for the meeting
bases. The best cell of the standardisation × exit grid is **`z` × `t42`**, a
fixed 42-day horizon on a re-centred z-score, **not** `scale` × `z0`.

So the lead was wrong. The winning configs in this lab used `scale`+`z0` because
that corner happened to be the best corner, not because keeping the model's zero
is a better idea — and the honest way to find that out was to make it an axis
rather than a choice, which is what the recommendation got right.

## 9. What I would test next

1. ~~**Stop fitting calendars and fit the strip**, sweeping `scale_only_zscore`
   with the `z0` exit.~~ **RUN — see §8b.3.** The spline is confirmed as the
   better basis, but the standardisation recommendation was **wrong**: on the
   sweep distribution a plain trailing z-score beats keeping the model's zero,
   and the best cell is `z` × `t42`. What remains open is the *exit*: `z0` on a
   `scale` signal and `t42` on a `z` signal are the two corners that work, and
   nothing tested why.
2. ~~**6m flies, and 9m/12m were never tested.**~~ **RUN — see §8b.2.** The 12m
   fly carries 6.8× the 3m fly's dispersion for the identical four-contract
   cost, and its oracle clears the round trip by 11.6bp. It still produces
   nothing ALIVE. The open question is now the one that replaced it: at 12m the
   constraint is **signal quality**, not cost, so the next lab should be about
   prediction and not about packaging.
3. **Maker execution remains the only thing that changes the answer.** 20 of 28
   rows are positive gross and 9 of 28 survive 2.0bp. The whole distance between
   those two numbers is the spread.
4. **The 2020 ablation.** The schedule deliberately excludes the unscheduled
   March 2020 cuts because nobody could price them ex ante. Re-running the
   meeting audit *with* them included would quantify how much of the ZIRP-era
   residual is intermeeting policy that no calendar can capture.
5. **Fix or wrap the direction-blind `bpv` seam** (§6) before any further
   `QueryDrivenBacktest` result is believed. A one-line regression test on
   `resolve_pricable` would have caught it.
6. ~~**Re-audit the fly mean-reversion lab's shadow tests at per-CONTRACT
   cost.**~~ **RUN — see §8b.1.** 16 of 24 becomes 17 of 24; one framework
   flipped.

### A methodological note worth keeping

Every one of the twelve defects in §7b flattered the hypothesis under test.
That is not coincidence and it is not bad luck: a researcher who believes a
mechanism builds the check that would confirm it, and stops looking when it
does. The two that mattered most — the roll-contaminated calendar audit and the
handicapped placebo baseline — both *passed* on first run and produced the
numbers the hypothesis predicted. Neither was found by re-reading the code; both
were found by asking, adversarially and specifically, "what would make this
result appear if the hypothesis were false?" The confound check in §4b exists
only because that question was asked of the one test that had gone the
hypothesis's way, and it is the test that killed it.

---

## Appendix — what was built

**`RVUtils/MeanRev/meetings.py`** (new): the scheduled FOMC decision calendar
2018–2027 with a documented projection rule beyond it and a `source` column
flagging provenance; `meeting_weight_matrix` (delegating to
`SFRRVLab.lattice.day_weight_matrix` so the two labs cannot drift);
`contract_weight_table` (one row per contract, not per contract-day — the IMM
quarter is a property of the contract); `calendar_fly_loading`;
`solve_smooth_path` (second-difference-penalised jump fit);
`meeting_residual_panel`; `calendar_fly_panel`; `calendar_tilted_fly`.

**`RVUtils/MeanRev/diagnostics.py`** (new): the pond test — `forward_move`,
`move_profile`, `oracle_table`, `selectivity_table`, `signal_entry_mask`,
`variance_decomposition`.

**`RVUtils/MeanRev/signals.py`**: `scale_only_zscore` (standardise the scale,
keep the model's zero), `meeting_residual_signal`, `calendar_adjusted_signal`.

**`notebooks/backtests/sfr_kink_fade_common.py`**: re-exports every reporting
block from `sfr_fly_meanrev_common` unchanged so both labs are graded by
identical code, retargeted to `notebooks/data/sfr_kink_fade/` with the correct
per-contract taker cost, plus `load_kink_lab`, `meeting_audit`,
`calendar_summary`, `pond_block`, `cm_variance_decomposition`.

**`sfr_fly_meanrev_common.py`**: gained `set_output_dir` (so a sibling lab can
reuse the blocks without overwriting the CSVs), a configurable `TAKER_BP` and
cost curve, `BAD_DATES`, and a `PANEL_DIR` separate from the results directory.
Defaults are unchanged, so the prior lab's numbers are reproducible.

**`RVUtils/MeanRev/shadow.py`**: `cost_mode='per_contract'` and
`SHADOW_CONTRACTS`, so the shadow test can charge a butterfly the four contracts
it actually trades. Default unchanged.

**Tests: 66 new synthetic, no-network tests** —
`tests/test_meanrev_meetings.py` (38), `tests/test_meanrev_diagnostics.py` (16),
`tests/test_meanrev_kink_signals.py` (12), plus 3 in
`tests/test_meanrev_engine.py` pinning the per-contract shadow costing. The
calendar cross-check against `_CENTRAL_BANK_DATES`, the regime-boundary check,
the projection-fidelity table and the gap/day-weight boundary convention are all
tests rather than notebook cells, so a typo in the schedule fails the gate.
