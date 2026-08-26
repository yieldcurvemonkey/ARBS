# ABOUTME: Emits FINDINGS.md, the final report for the Fedspeak-driver study.
# ABOUTME: Content is fixed prose; every number in it comes from the three results JSONs.
"""Writes FINDINGS.md next to this script.

Run:  C:\\Users\\chris\\anaconda3\\envs\\stir\\python.exe d1_write_findings.py
"""

import os

OUT = os.path.dirname(os.path.abspath(__file__))

DOC = r"""# Is Fed speak a driver of the US front end -- and more so under Warsh?

**Target:** USD SOFR IMM 3x4 forward (`USD-SOFR-1D IMM_3xIMM_4 OUTRIGHT RATE`), daily bp.
**Span:** 2019-01-02 -> 2026-08-24, 1,912 business days. 862 speech days, 1,050 non-speech.
**Calendar:** ForexFactory `FED_SPEAKERS`, 2,410 engagements from 2015-01-05, 36 named officials.
**Nulls:** circular rotation of `(is_speech_day, n_speakers)` jointly, exhaustive over all 1,871
offsets, masks held fixed. Seed 20260825. An i.i.d. null on this panel inflates significance by
~17x and is never used for a headline.

---

## VERDICT BOX

The PM's line has two halves. They grade differently, and neither survives as written.

| # | Claim | Grade | The number that decides it |
|---|-------|-------|----------------------------|
| **(i)** | "Fed speak remains a key driver for the front end" | **UNSUPPORTED** | Speech days move the 3x4 forward **1.012x** as much as non-speech days (mean abs move), rotation **p = 0.911**. Across 6 control rungs x 3 variants x 4 statistics -- 72 pre-registered tests -- exactly **1 clears p<0.05, against 3.6 expected by chance**. |
| **(ii)** | "and arguably more so now [under Warsh]" | **UNDETERMINED -- and permanently so by this design** | Warsh arm = **56 clean days, 22 speech days**. Ratio-of-ratios **1.174**, 95% CI **[0.818, 1.659]**, achieved power **0.145**, MDE at 80% power **1.69**. Worse: with Powell's tenure closed, SE(log rho) is floored at 0.0768, so the **MDE floor is 1.240 -- permanently above the observed 1.174 -- and maximum achievable power is 0.550.** More calendar time cannot settle it. |

**What IS supported, and is worth saying:** Fed speak is a **bigger calendar presence than ever** --
**+21.0 events/yr over 2015-2025** (R2 0.63, p 0.003), a record **409 events in 2025**, with a
stated coverage confound. That is a statement about the *calendar*, not about the *price*.

**Be blunt about the shape of the negative.** The honest verdict on (i) is *"no detectable effect,
with three of four point estimates at or below their null centres"* -- **not** *"proven absent"*,
and **not** *"it fails in the direction opposite to the hypothesis"*. This design detects a median
tilt of **27% or more**; the observed tilt is **23%** and sits just inside the null.

---

## THE EVIDENCE, IN THE ORDER A SKEPTIC WILL DEMAND IT

### 1. The control ladder -- the effect is never there to lose

Rung (c) is the headline sample: ex-FOMC, ex-CPI, ex-NFP. n = 1,672 (775 speech / 897 non-speech).

| Rung | n | var ratio | mean abs ratio | median abs ratio |
|------|---|-----------|----------------|------------------|
| (a) all days | 1,911 | 0.602 | 0.963 | 1.214 |
| (b) ex-FOMC | 1,850 | 0.608 | 0.992 | 1.242 |
| **(c) ex-FOMC/CPI/NFP** | **1,672** | **0.586** | **1.012** | **1.229** |
| (d) (c) ex-blackout | 1,116 | 0.740 | 1.049 | 1.208 |
| (e) (d) matched on FOMC proximity | -- | 1.175 *(null 1.51)* | 1.089 *(null 1.03)* | 1.301 *(null 1.07)* |
| (e2) (d) matched on yesterday's vol | -- | 1.399 *(null 1.26)* | 1.086 *(null 1.03)* | 1.032 *(null 1.04)* |

Rung-(c) rotation p: var 0.276 - mean abs **0.911** - median abs 0.091 - concentration 0.279.

**Read the matched rungs against their null median, never against 1.0.** Rungs (e)/(e2) aggregate a
ratio of noisy per-stratum estimates and are Jensen-biased upward by construction. Every one of
those six numbers sits **below** its own null centre -- i.e. speech days are, if anything, quieter.
Quoting rung (e)'s 1.175 bare would invert the sign of the finding. The figure now prints the null
reference next to each of those numbers and greys them, so the misread is closed.

**The rise from (c) -> (d) -> (e) is confound removal, not signal appearing.** Two of the stated
rationales for the ladder are false for this calendar:

- `n_press_conf` is **identically zero** (the FED_SPEAKERS theme serves no press-conference rows)
  and only 2 of 61 FOMC days carry any speech. So rung (b) does not remove "the Powell presser as a
  speaker event" -- it strips volatile days from the *non-speech* arm and mechanically raises the
  ratio.
- Blackout days are **more** volatile than non-blackout (mean abs 4.23 vs 3.61 bp) and speeches
  avoid them, so blackout *depresses* the ratio at rungs (a)-(c). Removing it at (d) removes an
  **anti-thesis** confound.

### 2. Dose-response -- corrected, and the correction matters

The first pass called this "the strongest disconfirmation" and ran it on the as-specified sample
with **IMM rolls left in**. The 0-speaker bucket holds 25 roll days; roll days carry mean abs ~11bp
against ~4bp for ordinary days. Both specific claims drawn from it **reverse** on the roll- and
defect-cleaned sample:

| speakers | 0 | 1 | 2 | 3 | 4+ |
|---|---|---|---|---|---|
| as-specified, bp | 3.80 | 3.90 | 3.70 | 4.45 | 3.36 |
| **clean (ex-roll, ex-defect), bp** | **3.39** | **3.72** | **3.74** | **3.78** | **3.40** |
| n (as-spec / clean) | 897 / 869 | 350 / 345 | 217 / 214 | 102 / 100 | 106 / 104 |

On the clean sample **0->3 is monotone increasing** and 4+ sits **at** baseline (+0.02 bp), not
below it. So *"non-monotone"* and *"the 4+ bucket is lower than the no-speech baseline"* are both
dead -- **do not repeat them.**

What survives is the boring disconfirmation, which is the one that matters: the effect is
economically nil. The **whole spread is 0.39 bp on a 3.39 bp base**. Spearman rho = **+0.068**
(rotation p 0.186) on `n_speakers`; **+0.070** (p 0.157) on `n_distinct_speakers`, which the first
pass never ran; on speech days only, rho = +0.030 (p 0.853). A genuine driver shows more movement
with more speakers. This shows 0.4bp.

*(Control-first check: the same machinery reproduces the published as-specified rho = +0.056059 and
rotation p = 0.37607 to the last digit, so the clean-sample numbers are trustworthy.)*

### 3. The null, and what it can and cannot see

- **1 of 72** rotation cells below p<0.05 (against 3.6 expected); **9 of 72** below p<0.10 (against
  7.2 expected). The single hit is rung (e), V4_clean, median abs ratio, p = 0.031 -- the most-cut
  variant on the most-favourable statistic.
- **Reverse causality is absent.** `n_speakers` on lagged abs move (lags 1-5, HAC(10)): R2 = 0.0008,
  every |t| < 0.8. Incremental R2 of lagged vol over calendar controls = **0.00032**. What *does*
  predict `n_speakers` is the speaking calendar itself: blackout t = -2.84, days-to-FOMC t = +3.03,
  calendar-only R2 = 0.059.
- **Rank tests, which the first pass omitted and fat tails require.** Kurtosis of the daily change
  on rung (c) is **62.6**; Welch on abs move (p 0.875) and Brown-Forsythe (p 0.877) are exactly the
  tests that disables, and they were the only two reported. Mann-Whitney i.i.d. p = 0.025,
  KS 0.0097, Mood median 0.0033 -- all nominally significant, and **all three die under the rotation
  null** (0.295 / 0.210 / 0.083). That door is now closed from the inside rather than left open for
  a hostile reader.
- **Day-of-week fixed effect** (never tested in the first pass): OLS abs-move on a speech dummy,
  HAC(10), gives **+0.045 bp** (t 0.12) with no FE, **+0.083 bp** (t 0.24, p 0.81) with DOW FE,
  +0.085 bp adding sqrt(elapsed days). Adding the fixed effect does not rescue an effect.

### 4. Why the variance number must be quoted with its trajectory

The rung-(c) concentration of 0.725 is the sentence a reader is most likely to repeat, and it is the
least robust number in the study. **One day is 15.7% of rung-(c) sum of squared changes.**

| cut | concentration | var ratio |
|---|---|---|
| untrimmed | **0.725** | 0.586 |
| ex top 1 day | 0.859 | 0.767 |
| ex top 5 days | **1.016** | 1.030 |
| ex top 10 days | 1.048 | 1.094 |
| ex top 1% (16 days) | 1.087 | 1.176 |

The sign flips after **five days are removed** -- and after eight (a 0.5% trim: concentration 1.045).
The single largest day is **2023-03-13 (SVB, -114.73 bp)**, a **blackout** day on which Fed
officials structurally cannot speak; **13 of the top 20 rung-(c) days are blackout days**. So the
below-1 reading partly restates the blackout calendar rather than measuring Fedspeak. The two next
largest, 2019-07-01 (+73.24 bp) and 2019-07-08 (-74.05 bp), are a confirmed curve-build defect.

**Disclosed forking path.** Sweeping the trim depth, the 4-6% window clears p<0.03 on all four
statistics (at 5%: concentration 1.136 p 0.013, var 1.304 p 0.006, mean 1.163 p 0.014, median 1.284
p 0.018). It is a forking path -- found after seeing the 1% result, bump-shaped p-curve, effect size
peaking rather than plateauing -- and the **pre-registered rungs kill it**: at rung (d) the same 5%
trim gives p 0.11-0.25, and at rung (e2) p **0.44-0.59** (concentration 1.041 against a null median
of 1.003). It is recorded so nobody has to rediscover it and mistake it for a finding.

### 5. The one surviving statistic, and what actually buries it

The median abs ratio is persistently above 1 (1.21-1.30 at rungs (a) through (e); the five smallest
p-values in the whole 72-cell grid are all median abs). Two things dispose of it.

**(a) Rung (e2).** Within non-blackout days, matching on yesterday's abs move decile collapses it:

| rung | median abs ratio | rotation p | null median |
|---|---|---|---|
| (c) | 1.229 | 0.091 | 1.023 |
| (d) ex-blackout | 1.208 | 0.215 | 1.022 |
| **(e2) matched on yesterday's vol** | **1.032** | **0.973** | 1.036 |

**(b) The curve placebo** -- the most informative test available, and it needed no new data (2y/5y
were already on disk, unused). On identical clean days (n = 1,632):

| series | mean abs ratio | median abs ratio | concentration |
|---|---|---|---|
| IMM 3x4 (target) | 1.089 | 1.272 *(rot p 0.043)* | 0.822 |
| 2y SOFR | 1.095 | 1.167 *(rot p 0.370)* | 0.969 |
| 5y SOFR | 1.073 | 1.150 *(rot p 0.066)* | 1.059 |

The elevation is **the same across the curve**. A 5y SOFR rate has no Fedspeak channel to a 3-month
forward, so a tilt that shows up there too is ambient news flow on ordinary busy mid-week business
days -- not a front-end response.

*Honest disclosure: the target's median tilt on this cleaned sample carries rotation p = 0.043, a
nominally significant cell that is NOT in the 72-cell grid (this variant was never a null variant
there). It is reported rather than buried. It does not rescue the thesis -- the 5y shows the same
tilt on the same days, and the tilt collapses to its null centre at rung (e2).*

Read the residual as **"speech days are busy but bounded"**: non-speech days own the tails, speech
days own a slightly fatter middle, and the middle is not front-end specific.

### 6. The regime comparison -- underpowered, and now provably un-fixable by waiting

| | Powell | Warsh |
|---|---|---|
| clean days | 1,616 | **56** |
| speech days | 753 | **22** |
| mean abs speech / non-speech, bp | 3.847 / 3.824 | 3.722 / 3.153 |
| **excess ratio** | **1.006** [0.87, 1.17] | **1.181** [0.86, 1.61] |

Ratio-of-ratios **rho = 1.174**, CI **[0.818, 1.659]** (spans 1), studentized z 0.88, bootstrap
p 0.383. Median-based rho 1.070. Across seven robustness arms rho spans 0.851-1.269 -- every one
below the MDE.

Six things say do not lean on this:

1. **Power.** MDE at 80% = 1.69 simulated / 1.66 analytic. Achieved power at the observed effect =
   **0.145**. An underpowered null is not evidence of no effect; an underpowered positive is not
   evidence of one.
2. **The Warsh regime contains zero Warsh speeches.** Warsh has 0 events in this calendar, and no
   Chair-titled Fed event of *any* name appears after 2026-03-30. The 56 days measure
   committee-member Fedspeak under a *silent chair* -- arguably a fair proxy for "forward guidance
   is gone", but **not** a measurement of Warsh's own communication.
3. **The lift predates the handover.** Splitting 2026 at the transition: Powell-2026 **1.327**
   (85 days) -> Warsh **1.181** (56 days). It moved **down** across the handover. Powell's last
   6 months (1.387) and last 12 months (1.161) bracket the Warsh value. Under the regime story the
   ratio should have stepped UP on 2026-05-22. It did not.
4. **No single year separates from 1.0.** Every per-year excess ratio 2019-2026 has a 95%
   day-bootstrap CI spanning 1.0 (widths 0.53-1.36). The 0.74-to-1.33 by-year excursion is **one
   noise band wide**. The figure now draws those CIs rather than a connected line.
5. **Season-matched placebo.** The Warsh window is only 22 May - 24 Aug. In the same window of each
   Powell year: 0.65 / 1.05 / 1.15 / 1.21 / 1.37 / 1.19 / 1.29. **4 of 7 were at least as high**
   (one-sided rank p 0.625). A summer excess ratio near 1.2 is ordinary.
6. **Boundary-shift placebo (newly run).** Re-labelling the regimes at TRANSITION +/- k months:

   | shift | date | post n / speech | post ratio | rho | rho CI95 | verdict |
   |---|---|---|---|---|---|---|
   | -3m | 2026-02-22 | 112 / 53 | 1.288 | 1.296 | [0.955, 1.735] | undetermined |
   | **-2m** | **2026-03-22** | 95 / 48 | 1.488 | **1.503** | **[1.098, 2.039] -- EXCLUDES 1** | undetermined |
   | -1m | 2026-04-22 | 75 / 32 | 1.193 | 1.188 | [0.863, 1.614] | undetermined |
   | **0** | **2026-05-22** | **56 / 22** | **1.181** | **1.174** | [0.819, 1.658] | undetermined |
   | +1m | 2026-06-22 | 40 / 15 | 1.438 | 1.434 | [0.999, 2.016] | undetermined |
   | +2m | 2026-07-22 | 21 / 6 | 1.701 | 1.693 | [0.972, 2.707] | undetermined |
   | +3m | 2026-08-22 | 1 / 0 | -- | -- | -- | degenerate |

   A split **two months before the handover, entirely inside Powell's tenure**, produces a CI that
   **excludes 1.0**. That is a textbook boundary-signal placebo firing, and it is the strongest
   available evidence that the 2026 lift is a **window** property, not a **chair** property. The
   verdict is boundary-invariant; the **point estimate emphatically is not** -- the post-arm ratio
   spans **1.181-1.701** over +/-2 months, and the actual transition date happens to be the
   *minimum* of the grid.

**The remediation everyone reaches for is arithmetically wrong.** "Wait 4-6 more quarters" cannot
work: Powell's tenure is over, so SE(log excess ratio | Powell) is **frozen at 0.0768** and floors
SE(log rho) no matter how long the Warsh arm runs.

| quarters added | 0 | 2 | 4 | 6 | 12 | infinite |
|---|---|---|---|---|---|---|
| MDE (80% power) | 1.663 | 1.408 | 1.347 | 1.319 | 1.284 | **1.240** |
| power at rho = 1.174 | 0.143 | 0.259 | 0.325 | 0.368 | 0.434 | **0.550** |

The MDE **never** reaches the observed effect. What *would* settle it: (a) re-run the intraday event
book so a post-2026-05-22 per-trade log exists on disk, replacing close-to-close with a 30-minute
event window; or (b) benchmark the post-transition window against the **season-matched placebo
distribution** (7 Powell summers, mean 1.13) rather than against the whole Powell sample.

**Claim 2 ("fewer, higher-signal events") fails on its own terms:** events per calendar day
0.959 -> 0.893 (a 7% drop inside a one-quarter sample) and events per **speech day** 2.058 -> 2.273
(**up**). The within-regime marginal abs move per extra speaker is +0.016 bp/event under Powell
(t +0.15) and -0.100 under Warsh (t -0.50) -- neither distinguishable from zero.

### 7. Frequency and seasonality -- the half of the story that is real

- **Rising, not falling:** +21.0 events/yr over 2015-2025, R2 0.63, t 3.95, p 0.003. 2025 set a
  record 409, +103 above trend. *Caveat:* fitted on 2015-2023 alone the drift is +8.0/yr -- treat
  the headline slope as descriptive of a two-year level shift, not a stable secular rate.
- **2026 YTD is 195 to 24 Aug: -22.3% vs 2025, -0.5% vs 2024.** Annualised it lands at 329.5
  (seasonal method) against a fitted 327.1 -- **on** the rising trend line, not below it. The naive
  pro-rata method says 301.6 and would put it below; the annualisation method decides the sign, so
  "on trend" is the honest reading.
- **The decline began before the handover:** 1 Jan - 22 May was -15.0% vs 2025; 23 May - 24 Aug was
  -35.2%. It steepens after the chair change but does not start there.
- **Seasonality is strong and bimodal:** Oct index 1.69 vs Dec 0.48 (3.5x). Thursday is the modal
  speaking day (547 events); weekend Fedspeak is real but rare (66 events, 2.7%).
- **The data-quality check passes:** the intra-cycle blackout trough is present and deep -- 0.08
  events/business day at days 0-9 to the decision, **6.9% of the 1.20/day far-field rate** (a
  calendar-side re-derivation that keeps off-spine events says 9.0%). The calendar/FOMC join is
  sound.
- **Coverage confound, unresolvable here:** the 2024-25 level shift coincides with the vendor's
  covered roster broadening from 10 distinct names in 2019 to 21 in 2025. Events **per covered
  speaker** is far more stable (11.9-20.0 across all complete years), so a large part of the rise is
  roster *breadth*. Whether that breadth is genuine Fed behaviour or ForexFactory coverage cannot be
  settled from this data.

**Frequency is not the same thing as being a driver of the price.** The study never conflates them.
The PM's line does.

---

## RECONCILING WITH THE DAILY REGRESSION YOU ALREADY HAVE

The daily sentiment-index regression on the same subject reports: **levels R2 = 0.89 but DW = 0.12,
no cointegration (p = 0.21), no Granger causality from sentiment to rate, and reverse Granger
significant at lag 1 (p = 0.038).**

**First, the framing correction: these two results do not conflict -- they agree.** The premise
behind "why can an event study show an effect the regression misses" does not apply here, because
the event study *also* found nothing at daily frequency. Two methodologically independent approaches
-- a levels/Granger time-series regression, and a day-type variance decomposition with a rotation
null -- both return null at the same frequency on the same question. That is corroboration, not
tension, and it is a stronger position than either result alone.

**Second, what each piece of the regression actually says:**

- **R2 = 0.89 with DW = 0.12 is not evidence of anything.** Two trending, highly persistent series
  regressed in levels produce a high R2 almost mechanically. DW = 0.12 says the residuals are close
  to a random walk. Combined with **no cointegration (p = 0.21)**, this is the textbook signature of
  a **spurious regression**. Do not quote the 0.89 -- it is the number most likely to end the
  conversation badly if repeated.
- **No Granger from sentiment to rate** is the same finding as the variance ratio, reached by a
  different route: past Fedspeak sentiment does not help forecast the front end.

**Third -- and this is the genuine problem for the thesis, so look straight at it:** **reverse
Granger is significant at lag 1 (p = 0.038).** The rate leads the sentiment index, not the other way
round. Two readings, and you should carry both:

1. **The mechanical reading, which is well-evidenced here.** ~**60% of the JPM score rows were
   published AFTER the speech they score** -- a documented vintage hazard in this data. A score
   stamped to a speech date but written a day or more later can absorb the market's post-speech
   move. A sentiment index built that way will mechanically appear to *follow* the rate. Reverse
   Granger at lag 1 is exactly the signature this defect produces. On that reading the finding is
   about the *index construction*, not about causation -- and it is a reason to distrust the index,
   not a result about the Fed.
2. **The uncomfortable reading, which cannot be ruled out.** If it is not purely vintage, then the
   causal arrow genuinely runs market -> Fed communication at daily horizon: officials' tone
   responds to where rates already are. That is a coherent world, and it is the opposite of the PM's
   line. The day-count evidence *weakens* the strong version: speakers do **not** turn up after
   volatile days (lagged-vol R2 0.0008, all |t| < 0.8; incremental R2 over calendar controls
   0.00032). But that tests **occurrence**, not **tone**. The reverse-Granger result is about tone,
   and nothing on disk tests tone-versus-rate cleanly, because the vintage hazard contaminates every
   forward-looking use of the scores. **This is unresolved, and the PM should not be surprised by it
   in the room.**

**Fourth, be honest that the daily result may simply be the true one.** There is no event-study
result here being rescued. The one lane where a real effect could still hide is **intraday**: a
speech moves the strip in a 30-minute window, and a close-to-close daily change divides that by a
whole day of other news. The per-trade log on disk confirms the daily abs move is a **weak
instrument** for event information -- day-level correlation with the intraday 3h event-window abs
move is **0.296 Pearson / 0.343 Spearman, R2 = 0.10 over 311 overlapping days**. (The 0.827
correlation quoted elsewhere is a *year-level* ambient-vol correlation on 4 points -- honest for the
normalization argument, but not validation of the daily metric as an event instrument.) That
attenuation means the true MDE on an underlying intraday effect is materially **wider** than the
stated 1.69 -- this study is *more* underpowered than its own headline says.

**That lane is an open question, not a rescue.** It is untestable post-handover: the only per-trade
logs on disk (`nav_closed.csv`, `sig_closed.csv`) end **2026-03-27**, before the 2026-05-22
transition -- **zero** post-transition intraday observations. Nothing was manufactured from the
straddling year-level aggregates that do exist.

**Net:** at daily frequency, both methods say no. The reverse-Granger result is a real problem for
the thesis and most likely a vintage artefact of the sentiment index -- but "most likely" is not
"shown". Whether Fedspeak moves the front end in the 30 minutes around a speech is **not answered by
anything here**, and the measurement that would answer it does not exist on disk yet.

---

## LIMITATIONS AND UNRESOLVED DEFECTS

**Data layer**

1. **2019 curve-build defect in the target series.** 2019-07-01 (+73.24 bp) and 2019-07-08
   (-74.05 bp) move against a 2y that moved +5.00 / -1.06 bp. These are the #2 and #3 largest daily
   changes in the panel and carry ~5% of total sum of squares. Both boundary days are **non-speech**,
   so the defect biased the headline **against** the thesis. Excluded from variant V1 onward in the
   ladder, and now excluded in the regime split too -- which previously kept them, an inconsistency
   between the two analyses that has been fixed (Powell 1.006 -> 1.050, rho 1.174 -> 1.124).
2. **The overnight SOFR leg is unusable in 2019** (median absolute difference from published SOFR
   29.8 bp, max 275 bp). Not used in any headline.
3. **2019 target is provisional.** The whole curve is flat on 124 consecutive days
   (2019-01-02..06-28). Variants V3/V4 cut 2019 entirely; the verdict is unchanged.
4. **`n_press_conf` is identically zero.** The FED_SPEAKERS theme serves no press-conference rows.
   Zero does **not** mean no press conference happened. Warsh's press-conference doctrine is
   therefore **untestable from this data** -- a different calendar theme would be needed.
5. **`is_blackout` opens ~3 days early. NOT FIXED.** The panel flag is 10 *business* days before the
   decision (~14 calendar days); the Fed's rule starts the second Saturday before (~11 calendar
   days). Days 12-14 are flagged blackout yet run at 1.53 events/day against a 1.20/day far-field
   rate -- near normal. Anything conditioning on `is_blackout`, including rungs (d)/(e)/(e2) here,
   includes ~3 near-normal speaking days. Fixing it requires rebuilding the panel flag.
6. **Off-spine events.** 444 calendar days / 638 events sit off the business-day spine; 52 fall
   inside the rate span (weekend and holiday Fedspeak). Preserved in `fed_calendar_raw.parquet`,
   absent from the panel.
7. **`TimestampNYC` in `fed_calendar_raw.parquet` is stored as UTC.** The instant is correct; the
   column name is misleading. Any event-time work must `tz_convert("America/New_York")` first.

**Method**

8. **Multiplicity framing is generous to itself.** "1 of 72, 3.6 expected" treats nested rungs,
   nested variants and correlated statistics as independent Bernoulli trials. They are near
   duplicates. The p-value pattern is not scattered: 8 of the 18 median-abs cells sit below 0.10,
   all in the same direction. The framing survives a 10%-level check (9 observed vs 7.2 expected),
   so it is a quibble rather than an error -- but the grid looks cleaner than the structure of the
   hits actually is.
9. **`n_speakers` counts calendar ENGAGEMENTS, not distinct people.** On multi-engagement days it
   exceeds `n_distinct_speakers`. The dose-response has now been run on **both** (rho +0.068 vs
   +0.070); neither is significant.
10. **The daily speech flag is not intraday.** This tests whether a speech *day* is more volatile
    close-to-close. It cannot test the minutes around a speech, and the daily proxy is weak
    (R2 = 0.10 against the intraday event window).
11. **JPM sentiment scores were used for coverage only.** ~60% of score rows were published after
    the speech they score, so no forward-looking feature is clean. All Fedspeak analysis here is
    calendar-only (occurrence and count), the vintage-safe subset. The JPM feed also stops
    **2026-08-06**, 18 days before the calendar cutoff: 6 2026 engagements can never be scored
    (31.9% vs 33.0% on the scoreable window -- 1.1pp, minor, now recorded in the JSON and the
    figure).
12. **The regime point estimate is boundary-sensitive** (post-arm ratio 1.181-1.701 over +/-2
    months). The verdict is not.
13. **The chair transition date is repo-derived** (`fomc_extras.CHAIRS`,
    `FED_SPEAKER_QUARTERLY_LABELS.md`), corroborated by a data-derived interval
    (2026-03-30, 2026-05-31] whose right edge rests on a **single** Powell calendar row.
14. **Aggregator choice moves the regime point estimate more than the headline reports.** Across
    seven aggregators rho spans 1.047 (10% trimmed) to 1.537 (RMS); only mean (1.174) and median
    (1.070) are published. The RMS figure is high because *Powell's* ratio falls to 0.759 on his fat
    non-speech tail, not because Warsh rises. Pre-register the aggregator before any re-run.
15. **Speakers are pooled equally. NOT RUN.** Powell (203 events) and Williams (236) sit in the same
    bucket as 34 other names. A principal-versus-rest split is a ~20-line rung on data already on
    disk. If "Fed speak" is the wrong unit, a Chair/Vice-Chair/NY effect diluted ~4x by pooling would
    look exactly like this null. This is the single most valuable untried cut.
16. **Signed direction was never tested here.** Everything is an absolute move. Whether *content*
    (hawkish versus dovish), rather than the calendar slot, carries the move is untested -- and
    untestable forward-looking under the vintage hazard. Descriptive, contemporaneous use of the 463
    scored engagements is the only clean option.
17. **PCE / ISM / retail sales / Treasury refunding were not added to the exclusion set.** Expected
    to be immaterial once the day-of-week fixed effect is in, but it is the one control lane still
    untested.
18. **The "fixed-roster control" is not one.** Speakers present in >=10 of 11 complete years
    resolves to a **single name** (Powell). Renamed to `persistent_speakers_*` with a warning in the
    JSON; the coverage confound above is **not** controlled by it.
19. **Directional statistics answer a different question.** The intraday book's Sharpe decay
    (1st half 1.25 / hit 0.508 -> 2nd half 0.55 / hit 0.431; 2026 pooled SR -1.68, hit 0.362)
    measures whether the *sign* is predictable. Bigger moves in both directions is fully compatible
    with a falling hit rate, so the decaying Sharpe is neither evidence for nor against the
    information-content claim. These figures are now parsed programmatically from
    `_final_report.txt` with a known-answer check rather than hand-transcribed.

---

## WHAT TO SAY, AND WHAT TO DROP

### The defensible sentence

> "Fed speak is a bigger calendar presence than ever -- the event count is up 21 a year through 2025
> and 2025 set a record at 409, though part of that is the vendor covering more names. But at daily
> frequency it is **not** a measurable driver of the 3x4 IMM forward: speech days move it 1.01x as
> much as non-speech days, and 1 of 72 pre-registered tests clears 5% against 3.6 expected by
> chance. And the Warsh window -- 56 days, 22 speech days, zero Warsh speeches in the calendar --
> cannot say whether that has changed. It is not just underpowered now; with Powell's sample closed
> it can never reach 80% power on an effect this size. Re-running the intraday event book past
> 22 May is the test that would settle it."

### Drop these

| Claim | Why |
|---|---|
| **"Fed speak remains a key driver for the front end"** | 1.012x, rotation p 0.911, dose spread 0.4bp. Nothing supports it at daily frequency. |
| **"and arguably more so now"** | Cannot be said in either direction. 14% power, MDE 1.69 vs observed 1.17, and the lift *predates* the handover (1.33 -> 1.18). |
| "Warsh is speaking less" | 2026 is on the trend line, not below it. Events per **speech day** are UP (2.06 -> 2.27). And Warsh has **zero** events in this calendar, so his own frequency is unmeasured. |
| "Warsh only holds a presser when there is real news" | `n_press_conf` is identically zero in this calendar. The claim is not tested here in either direction. |
| "The variance sits on non-speech days" / "it fails in the opposite direction" | Dies on a 0.5% trim. The largest day is SVB -- a blackout day -- carrying 15.7% of the sum of squares. |
| "The dose-response is non-monotone and 4+ is below baseline" | Both reverse on the roll-cleaned sample. Say "economically nil -- 0.4bp of spread on a 3.4bp base" instead. |
| Rung (e)'s "1.18x" or (e2)'s "1.40x" quoted bare | Their no-effect point is the null median (1.51 / 1.26). Both sit **below** it. Quoting against 1.0 inverts the sign. |
| The levels regression's **R2 = 0.89** | DW 0.12 and no cointegration (p 0.21) -- a spurious regression. |
| "Fed speak is dead as a driver" (the over-correction) | This design detects a median tilt of 27%+; the observed 23% sits just inside the null, and the daily metric has R2 0.10 against the intraday event window. Say **"no detectable effect at daily frequency"**, not "proven absent". |

### The one honest concession to make in the room

There is a persistent ~20-30% **central-tendency** tilt: the typical speech day moves a bit more
than the typical non-speech day (median abs ratio 1.21-1.30 at rungs (a) through (e), rotation p
0.05-0.22). It never clears its null, it does not scale with speaker count (speech-only rho +0.03,
p 0.85), it
collapses at rung (e2) (1.032 against a null median of 1.036, p 0.973), and **it appears identically
on the 2y and 5y**, where no Fedspeak channel to a 3-month forward exists. Read it as: *speech days
are ordinary busy mid-week business days.* Say that before someone else says it as a rebuttal.

---

## DELIVERABLES

| file | what it is |
|---|---|
| `fig_variance_ratio.png` | Control ladder (with null-median references on the matched rungs) + dose-response, as-specified versus roll/defect-cleaned |
| `fig_regime_split.png` | Powell versus Warsh with bootstrap CIs, per-year uncertainty, power curve, season-matched placebo |
| `fig_fed_speak_frequency.png` | 7-panel frequency/seasonality deck, partial year flagged in every panel |
| `variance_ratio_results.json` | Full ladder, nulls, dose, reverse causality, tail sensitivity, and the `review_addendum` block (trim sweep, rank tests, day-of-week, curve placebo, MDE) |
| `regime_split_results.json` | Regime arms, power, robustness arms, `ex_defect_arm`, `boundary_shift_sensitivity`, `power_ceiling` |
| `frequency_seasonality_results.json` | Counts, trend, seasonality, speaker composition, JPM coverage, intra-cycle profile |
| `panel_daily.parquet` / `.csv` | The 1,912-day panel everything is computed from |
| `FINDINGS.md` | This document |

Reproduce with `C:\Users\chris\anaconda3\envs\stir\python.exe variance_ratio.py` (likewise
`regime_split.py`, `frequency_seasonality.py`, then `d1_write_findings.py`). Verifiers:
`a1_selftest.py`, `a3_verify.py`, `frequency_seasonality_verify.py` -- all pass, and
`a1_selftest.py` includes a mutation test proving the p-value path is load-bearing.
"""

path = os.path.join(OUT, "FINDINGS.md")
with open(path, "w", encoding="utf-8") as fh:
    fh.write(DOC)
print("wrote", path, len(DOC), "chars")
