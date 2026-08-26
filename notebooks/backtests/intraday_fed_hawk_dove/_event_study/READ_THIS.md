# Does Fedspeak drive the front end? The intraday read.

**Deck:** `fig1_event_fan.png`, `fig1b_event_fan_all.png`, `fig2_strip_response.png`,
`fig3_speaker_scatter.png`, `fig4_window_decay.png`.
**Panel:** SR3 1-minute bars, 985 signed Fed speeches (767 hawk / 218 dove) on 438 days,
2023-01 → 2026-08, against 2,931 time-of-day- and calendar-matched no-speech pseudo-events.
**Numbers:** the corrected statistics come from `c5_fixes.json` (built by `c5_fixes.py`, which runs
its own known-answer tests and mutations before it emits anything); the window-sweep numbers come
from `fig4_window_decay.json`, and the speaker-level numbers from `c3_results.pkl`. The
**load-bearing** figures — the `days_to_fomc` terciles, the argmax test, and the fig4 window sweep —
are re-derived and **asserted** by `c6_verify_readthis.py`, which fails loudly on mismatch; the
`c5_fixes.json` values are cross-read and printed by the same script but not independently re-derived
there (they carry `c5_fixes.py`'s own mutation-tested estimators instead).

---

## VERDICT

The PM's line contains two claims. They can come apart, so they are graded separately.
**Both fail, and one fails much harder than the other.**

| # | Claim | Grade | The number that decides it |
|---|-------|-------|----------------------------|
| **(a)** | Fed speeches **MOVE** the front end intraday (a *driver* claim — unsigned, direction-agnostic) | **UNSUPPORTED** | The share of speeches whose largest one-minute move lands **exactly at the speech minute** is **3.50%**, against **2.71%** on matched quiet days (z = 1.14, n.s.). **44.4%** of speeches move SR3 **exactly zero ticks** in the following 5 minutes. |
| **(b)** | The direction is **PREDICTABLE ex ante and not fully priced** (a *tradeable* claim) | **UNSUPPORTED — and decisively so** | Release-free signed composite at +240 min, all 985 signed events: **+0.07 bp (t = 0.53, n = 540)**. Hawk−dove gap vs matched placebo, release-free: **+0.34 bp (t = 1.13)** all-events, **−0.09 bp (t = −0.15)** on the 224-event clean book. Cross-speaker slope: **+0.0005 bp per score point (t = 0.05, R² = 0.0001)** against an MDE of 1.57 bp end-to-end. |

**Why (b) fails harder.** Claim (b) is the one this design is built to test, and the design is
powered: the 5-minute window resolves **0.074 bp** — one seventh of a single 0.5 bp SR3 tick — and a
mutation test confirms that injecting a genuine +0.5 bp per-event reaction prints **t = 14.2**. So
(b) is a **measured negative**, not an underpowered silence. Claim (a) is graded on weaker evidence:
the panel's unsigned tests are indirect, and "no detectable *average* effect" is not "no speech ever
moved the market".

**The single most important correction from review.** The deck's only positive numbers —
a +0.20 to +0.35 bp signed composite, the three DiD cells whose CIs excluded zero, the one t = 2.80 —
**live entirely in windows that contain a scheduled US macro release.** The panel shipped *day*
flags (`is_cpi_day`, `is_nfp_day`) covering 4–5% of events where *window* flags were needed: **28.1%
of −60 → +240 windows contain a high- or medium-impact US release.** Split on that flag:

| rank | full book | release-free | release-contaminated |
|------|-----------|--------------|----------------------|
| 1Q | +0.202 bp (t = 2.51, n = 775) | **+0.037 bp (t = 0.64, n = 508)** | +0.514 bp (t = 2.67, n = 267) |
| 3Q | +0.245 bp (t = 1.44, n = 802) | **+0.071 bp (t = 0.53, n = 540)** | +0.603 bp (t = 1.41, n = 262) |

Remove the release windows from **both** books and the excess over placebo goes **negative** at every
rank (−0.02 bp at 1Q to −0.18 bp at 5Q). Comparing hawks against doves **on the same day** (93
identifying days) gives a stance slope of **−0.06 bp (t = −0.31)** at rank 3.

Two further cuts point the same way and are worth having ready, because they do not depend on the
release calendar at all:

- **Drop the pre-speech leg entirely.** Measuring from offset 0 instead of −60 — so nothing banked
  before the speaker opens their mouth can count — gives **+0.26 bp (t = 0.74)** on the headline book
  and **+0.17 bp (t = 1.24)** on the all-events book over [0 → +240]. Same null. This matters because
  the [−60 → 0] leg, which cannot be a response, is **31%** of the all-events +240 composite.
- **Compare the event window against a matched control window on the same day.** A length-matched,
  same-day, no-speech window [−360, −60] carries **+0.48 bp (t = 2.71)** against the release-clean
  event window's **+0.07 bp (t = 0.48)**; the paired difference is **−0.42 bp (t = −1.93)**. The
  label predicts the part of the day the speech is *not* in. A speech cannot cause that.

**The mechanism is not "releases inflate any signed book"** — that is refuted by the placebo, whose
contaminated windows are *negative* (**−0.144 bp at 1Q, −0.082 bp at 3Q**, against **+0.057** and
**+0.112** on its own clean windows). The defensible statement is narrower: the trailing-5-average
stance score is a **lagged proxy for the data-surprise regime**, so on speech days the label predicts
the direction of the release-driven move inside the window. A conditional "speeches matter more when
data is in play" channel cannot be separated from that on this panel — see *the next test*.

---

## THE FOUR FIGURES

### fig1 / fig1b — the event-time fan
- **Shows:** hawk and dove paths against their own matched no-speech days, from −120 to +300 min.
  The two arms start together, do not separate at the speech, and end together.
- **The number:** headline book (224 clean single-speaker events) hawk−dove at +240 =
  **+0.58 bp (t = 0.83, n = 184)**; against the matched placebo **+0.71 bp (t = 0.88)**; on
  release-free windows **−0.09 bp (t = −0.15)**. The all-events book (985 events) is the same
  answer with tighter bars, and carries the study's one borderline number: gap vs placebo
  **+0.71 bp, t = 1.92 (p ≈ 0.055)**, which halves to **+0.34 bp (t = 1.13)** release-free and is
  **−0.06 bp (t = −0.31)** under day fixed effects.
- **A skeptic will say:** *"the mean is three events."* Correct, and it is on the figure. The three
  largest of 184 events sum to **103%** of the entire summed signed move; the other 181 sum to
  **−2.0 bp**. Dropping the top 1% of days — **2025-04-09** (the 90-day tariff pause) and
  **2024-08-05** (the yen-carry unwind), neither flagged by any calendar column — takes the composite
  from +0.36 bp (t = 0.99) to **+0.01 bp (t = 0.03)**. They will also say the pre-event gap reaches
  **+0.66 bp at −90 min**, 1.12× the +240 gap the title is about, before anyone has spoken. Also on
  the figure.

### fig2 — the response across the SR3 strip
- **Shows:** the signed response by contract rank (1Q–5Q), raw against placebo (panel A), the
  arm-balanced excess (panel B), and the unsigned drift gap that explains why panel A misleads (C).
- **The number:** the strip is **flat**. 1Q−5Q is **−0.06 bp (CI [−0.38, +0.25])**; the 3Q tilt is
  **+0.113 bp (CI [+0.002, +0.228])**, about 1/30th of per-event noise. On release-free windows the
  excess is **−0.02 to −0.18 bp** at every rank.
- **A skeptic will say:** *"you're quoting p = 0.046 as a finding."* We are not. That cell is **1 of
  ~90 contrasts** computed for this figure and it **fails in 3 of 5 cuts**. The belly hump a
  structural story needs is **not in the data**, and the flatness is reported as the finding. The
  honest reading of panel B is that its positive level was a release artifact, which is now drawn on
  the panel as a third series.

### fig3 — speaker stance vs. what the market did
- **Shows:** one dot per FOMC official — mean ex-ante hawk/dove score against the mean **RAW**
  (not sign-flipped, so not circular) SR3 move at +240 min. 21 speakers, 827 scored speeches.
- **The number:** slope **+0.0005 bp per score point (t = 0.05, p = 0.96, R² = 0.0001)**. The design
  could have detected a **1.57 bp** end-to-end hawk−dove spread at 80% power; it measured
  **+0.03 bp (95% CI −1.09 to +1.14)**. All 21 leave-one-out refits stay inside
  [−0.0062, +0.0057] and **none** reaches p < 0.05.
- **A skeptic will say:** *"the x-axis is one-sided and Barr is the dove half-plane."* True — 18 of
  21 speakers have a hawkish mean score, and Barr alone supplies **44%** of the x-variance (leverage
  h = 0.49). But his Cook's D is ~0.004: he anchors the axis without tilting the line, and dropping
  him moves the slope to +0.0014. They will also point at the voter row (t = 1.57) — which is why
  the figure now carries an explicit **†** caveat that all three dove-mean speakers are Governors, so
  the voter and non-voter slopes are fitted on non-comparable x-support and the contrast is **not**
  evidence for a voter effect.

### fig4 — does window width hide the effect?
- **Shows:** the signed response measured over windows from 5 minutes to 1 week, with the
  minimum detectable effect at each width. This is the figure that tests the "the daily study just
  used too wide a window" defence.
- **The number:** **no window crosses |t| = 2 intraday** — max |t| = 1.39 at 4h. Effect-to-noise is
  **0.010–0.157, flat across a 1,440× range of window widths**: there is no decay in either
  direction. The one nominal crossing (1 week, t = 2.90) does not survive overlap-robust inference
  (block-bootstrap t = 1.85, p = 0.061; Newey-West t = 1.68) and is carried entirely by 2024.
- **A skeptic will say:** *"prepared remarks leak early, so the reaction is in your pre-window."*
  Checked: the 30-minute **pre**-speech window (+0.12 bp, t = 1.36) is **no larger** than the
  post-speech one (+0.06 bp, t = 0.90). The dilution story is dead too — the 5-minute std is already
  1.9 ticks, a microstructure floor.

---

## RECONCILING WITH THE DAILY NULL

The daily study (`_driver_analysis/FINDINGS.md`) found speech days move the SOFR IMM 3x4 forward
**1.012×** as much as non-speech days, rotation **p = 0.911**, with 1 of 72 pre-registered cells
below p < 0.05 against 3.6 expected by chance.

**These two results are not in tension. They agree, and the agreement is the finding.**

That matters because the daily study explicitly left one lane open: *"the one lane where a real
effect could still hide is intraday: a speech moves the strip in a 30-minute window, and a
close-to-close daily change divides that by a whole day of other news."* **This deck closed that
lane.** Figure 4 is the direct test, and it does **not** show a decay that explains the daily null —
it shows there is **nothing to decay**. The signed response is statistically absent at 5 minutes,
15 minutes, 30 minutes, 1 hour, 2h, 4h, 5h, 1 day and (robustly) 1 week alike.

Two supporting ties:

- **The instrument reproduces.** Day-level correlation between the intraday event-window move and
  the close-to-close daily move is **0.2949 Pearson (R² = 0.087, n = 527 days)** against the daily
  study's published **0.296 (R² = 0.10, n = 311)**, on a different book. The daily move is a weak
  instrument for the event window — but that is true in both studies, and it does not rescue either.
- **The target series is the same.** `contract_rank 3` = SR3 IMM_3xIMM_4, the daily study's exact
  series (level correlation 0.9985, median absolute difference 1.28 bp over 1,167 shared days).

**What the PM must not say in public:** "the daily regression missed it because it used the wrong
frequency." That defence is now measured and false. The correct line is that **two methodologically
independent designs at two frequencies both return null**, which is a stronger position than either
alone. The daily study's own reverse-Granger caveat (rate leads sentiment at lag 1, p = 0.038,
plausibly a score-vintage artifact) still stands and is still unresolved.

---

## LIMITATIONS

1. **2022 is entirely absent from the signed sample.** All 160 of that year's events are unscored —
   the point-in-time lookup returns nothing that early — so every number here is **2023–2026**. The
   fastest tightening cycle in 40 years, plausibly the period where Fedspeak mattered most, is not in
   this picture. No claim here is an "SR3 era" claim.
2. **The SVB week (2023-03-06 → 17) also carries zero signed events.** Four calendar events fall in
   it and none has an ex-ante score. The panel structurally cannot speak to the highest-volatility
   Fedspeak week in its own sample.
3. **Non-scheduled macro is still unflagged.** The window-level release flag catches scheduled
   high/medium-impact US releases. Tariff headlines, refundings, geopolitics and ECB/BoE spillover
   sit inside these windows unlabelled. 2025-04-09 and 2024-08-05 are the two named cases; others
   are not ruled out.
4. **The placebo is not the defence it was claimed to be, and it is biased.** It cannot difference
   out release contamination — its own contaminated windows are *negative*. Separately, **48%** of
   placebo days sit within 10 days of an FOMC decision against **2%** of real speech days, so the
   null is drawn from quieter days and **every excess-over-placebo number is biased upward**. The
   within-real-event tests are the defence instead: day FE (−0.06 bp, t = −0.31), the same-day
   matched control window (paired difference −0.42 bp, t = −1.93) and the release split (+0.07 bp,
   t = 0.53). None of the three needs the placebo, and all three return null.
5. **The release cut and the tail trim are not independent.** 2025-04-09 is itself
   release-contaminated. Applied jointly (release-free, then trim the top 1% of days) the composite
   is **+0.19 bp (t = 0.91)** on the headline book and **+0.08 bp (t = 0.60)** on the all-events
   book — both null, but the two checks overlap and should not be counted as two.
6. **Overlap attribution.** 916 of 1,256 events overlap another Fed calendar entry. Of 271
   (day, symbol) groups holding more than one event, **20 book an identical +240 move to every event
   in the group**, and one group carries 10 events. Day clustering fixes the inference, not the
   attribution: the effective sample is smaller than 985.
7. **A `days_to_fomc` gradient runs backwards from any information story.** Splitting rank 3 at +240
   into terciles of |days to the next FOMC|: near (1–21d) **−0.01 bp (t = −0.03, n = 289)**,
   mid (22–30d) **+0.11 bp (t = 0.36)**, far (31–50d) **+0.61 bp (t = 2.13, n = 263)**. Release
   contamination is flat across the three (33.9% / 32.0% / 31.2%), so this is a *second, independent*
   calendar artifact rather than the release effect in disguise. Speeches nearer a decision should
   matter *more*, not less. Unexplained. (A reviewer reported +0.76 bp / t = 2.53 for the far
   tercile from a slightly different cut; the recomputed figures above are the ones to quote —
   see `c6_verify_readthis.py`.)
8. **The dove arm is thin** — 51 events in the headline book, 44 priced at +240. Its wide ribbon is
   information, not a rendering artifact.
9. **Multiplicity, stated once for the whole deck.** Several hundred statistics were computed across
   these four figures. Under a global null, ~5% should print |t| > 2. The disclosed positives number
   **fewer than chance expectation**, which argues *for* the nulls — but no individual cell here
   should be promoted, including the ones that favour the thesis.

---

## THE SINGLE NEXT TEST

**Match on the release, vary the speech.** Take every window that contains a scheduled high- or
medium-impact US macro release and split it by whether a scored Fed speaker was talking inside that
same window. Compare the stance-signed response across those two groups, matched on release identity
(same indicator, same clock slot) and on release surprise where the consensus is on disk.

This is the one test that separates the last surviving story — *"speeches matter more when data is in
play"* — from the artifact this deck has already established, namely that the stance label proxies
the data-surprise regime. Nothing in the current panel can do it, because the current design varies
the speech and lets the release float.

Second priority, and a different kind of fix: **score 2022**. It requires an ex-ante score source
predating the JPM FED corpus, and it is the only way any version of this study can speak to a
tightening cycle. No re-analysis of the existing panel gets there — reaching t = 2 on a 0.5 bp effect
would need roughly **580** non-overlapping signed events against the **224** available.

---

## PROVENANCE — how to re-run and what was fixed

| Script | What it does |
|--------|--------------|
| `c5_fixes.py` | **The one source of truth.** Builds the window-level release flags, the gap DiD (raw / parent-matched / release-clean), day fixed effects, post-only legs, the tail trims and the strip restatement → `c5_fixes.json`. Runs 7 known-answer tests **each paired with a mutation** before emitting anything (the DiD must recover a real-arm-only effect *and* return ~0 when the effect is in both arms; day FE must kill a trend-assigns-stance confound *and* retain a genuine within-day effect; the trim must keep a broad effect *and* remove a three-outlier one). |
| `c6_verify_readthis.py` | Re-derives every number in this document that `c5_fixes.py` did not compute, and fails loudly on mismatch. It caught two: the `days_to_fomc` tercile and the zero-move share. Both are corrected above. |
| `c2_figs.py` / `c2_strip.py` / `c3_figure.py` / `c4_fig4.py` | The four figures. All read `c5_fixes.json`, so a figure and this write-up cannot drift apart. |

**Fixed in this pass:** the fig1 annotation box no longer prints the signed composite next to the
hawk−dove gap as if it were that gap's placebo-adjusted version (they differ by 1.9–2.7×); the
placebo band is now the parent-matched book (43% wider on fig1, and honest); the twins share a
y-axis; the pre-event box no longer claims "no leakage, no selection" on the strength of a pooled
slope while the gap itself wanders +0.66 bp; fig2's title no longer asserts an effect its own panels
do not support; the release-window and day-FE checks are promoted from a reviewer's scratch file into
the headline specification; the palette is imported from one place, so red means hawk and blue means
dove on every panel (the forest plot's voter rows are now neutral slate); and every figure states the
window the same way — **−60 → +240 min, five hours, of which four are after the speech**.

**Bar rule, unchanged and worth stating:** price at time T is the close of the last minute bar
labelled **strictly before** T. Barchart bars are start-stamped, so the leaky alternative (last bar
≤ T) reads a print from *after* T; it would inflate the +30 min composite **6.3×** and the +240 gap
from +0.58 to +0.68 bp. The conservative rule is the one used, and it can only understate.
