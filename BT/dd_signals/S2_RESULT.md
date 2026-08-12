# S2 — does daily dealer positioning predict multi-day reversal?

`docs/dealer_direction/signals/S_PREREG.md` S2, design sample only.
Produced by `BT/dd_signals/s2_positioning.py`; per-cell numbers in
`BT/dd_signals/out/s2_results.csv`, the panel itself in
`BT/dd_signals/out/s2_panel.parquet`.

**Sample: 2024-03-01 .. 2025-08-31 only.** The hold-out (2025-09-01 ..
2026-08-07) was not opened — not for a fit, not for a coverage count.

**The forward window is the hold-out's back door, and it is shut structurally.**
A signal stamped 2025-08-29 needs a September mark to close its `t+5` return,
and reading that mark *is* opening the hold-out. So the last signal day is
`LAST_SIGNAL_DAY = 2025-08-22` — five sessions before `DESIGN_END` — and the
mark series stops at `DESIGN_END`. Both are module constants with no CLI
override, and `stage_test` asserts on both bounds after the fact.

---

## SPEC — frozen before the regression ran

Written first and left unedited afterwards. `S_PREREG` §5 allows one
specification per hypothesis, and this repo's memory records twelve post-hoc
defects that all happened to flatter the hypothesis. Every choice is a constant
in the module with its reasoning attached.

| item | choice | why, decided in advance |
|---|---|---|
| **population** | SOFR, non-lifecycle (FLOW), every unit the ladder can orient: `RATE_VS_MID` for at-market OUTRIGHT/CURVE/FLY, `NPV_VS_UPFRONT` where an other-payment is present (which is what keeps PKG-N in) | the ladder's own retained population, through the ladder's own exclusion vocabulary. FED_FUNDS is dropped — the target is a SOFR par rate and the no-bias curve result was measured on SOFR (`WHAT_THE_LADDER_SUPPORTS` §3); it is ~3% of universe DV01. LIFECYCLE is a separate series by the ladder's own design (D8). |
| **risk** | rateslib delta ladder, 28 pillars, 60-min session blocks, rolled up by `indicator.PILLAR_BUCKET` | `LEDGER` D9 and the per-day-solver correction. Not a maturity-point allocation: "a signed KRD vector rather than a scalar" is one of the three things `S_PREREG` says is different this time, so it is not the thing to economise on. |
| **weight** | `conventions.signed_weight(p) = 2p−1`, never `p` | the task's instruction and `ladder.py`'s contract. Re-derived from `p` and asserted at 1e-12 in the signal stage, the same check `ladder._assert_weight_agrees_with_side` makes. |
| **calibration** | `probability.Calibration` on a **trailing 60-calendar-day** window ending the day before the classification date, refit every 5 sessions | a full-sample fit puts future deviations into day-`t` weights through `b0`. `rolling_calibrations`' own defaults for window and gap; `step_days=5` is the cost amortisation that function documents. |
| **flow window** | `(D−1 15:00 ET, D 15:00 ET]` on the **visibility** clock | `S_PREREG`: stamp on availability, never execution. Ending the window *at* the entry mark is what makes the position takeable — no print in the signal can post-date the mark it is traded at. Same clock as S1, so the two tests are comparable. |
| **buckets** | `indicator.TENOR_BUCKETS` minus **1-2Y** | `S_PREREG` S2 excludes 1-2Y (exclusion rate drifts +5.07 pp/yr, t = +3.21). |
| **regressor** | `z` = own-history standardisation of the bucket's D2C FLOW net `delta_dv01`, trailing 250 obs, min 60, zero-filled on no-print sessions | the indicator's one cross-bucket-safe view (`INDICATOR.md` §1: a constant retention factor cancels exactly in `z`, so `z` may be pooled where a level may not). `Z_WINDOW_OBS`/`Z_MIN_OBS` are the indicator's constants, and the formula is `indicator._own_history`'s, including the current observation in its own window. |
| **target** | `dR = R(t+5) − R(t)`, `R` = par SOFR rate in bp at the bucket's **right-edge** tenor, from the same Citi minute curve at 15:00 ET | same curve family as the mid the direction was inferred against, so both sides of the test share one measurement. Right edge fixed by rule; `30Y+ → 40Y` because its own right edge collides with 20-30Y's, `0-1Y → 1Y`. |
| **horizon** | 5 sessions | `S_PREREG` S2: "over days t+1..t+5". |
| **direction** | **β > 0** | `S_PREREG` S2, fixed in advance: dealer receives fixed → long duration → must sell → the rate should **rise**. A significant negative β is a different phenomenon, not a pass. |
| **primary test** | pooled panel over the nine tested buckets, `dR = a + b·z + e` | `S_PREREG` S2 is one hypothesis about one mechanism, not nine. Per-bucket coefficients are diagnostics, not extra hypotheses. |
| **standard errors** | **Driscoll–Kraay** = day-clustered + Bartlett lag 5; prereg-literal day-clustered (lag 0) reported beside it, and where they disagree the **larger** governs | `S_PREREG` §4 requires day clustering with `N_eff` = trading days. The overlapping 5-day return additionally makes the residual MA(4) *across* days, which day-clustering cannot see. Measured in §1 below: under this test's own dependence structure the day-clustered estimator rejects a true null 21.8% of the time at a nominal 5%. |
| **secondary test** | one interaction, `dR = a + b·z + c·(z·q) + d·q`, `q` = own-history z of `log((|D2D| + 1)/(|D2C| + 1))` in the same bucket-day | `S_PREREG` S2 declares exactly one conditioner — the D2D/D2C volume ratio as a forced-dealer proxy — and says the unconditional test is primary. `log` because it is a ratio; `+1` USD/bp guards a zero side; standardised so `b` keeps its unconditional meaning at the mean. |
| **edge per trade** | `mean(sign(z)·dR)` over bucket-days with a defined `z`, bp of rate | the quantity `S_PREREG` §1's kill rule is stated against. Every bucket-day is one trade; there is no `|z|` threshold, because a threshold is a search. |
| **MDE** | `(z₀.₉₈₇₅ + z₀.₈)·SE = 3.083·SE` | 80% power, two-sided at `ALPHA = 0.025`. Same formula as S1. |
| **significance** | p < 0.025, two-sided | `S_PREREG` §3, Bonferroni over the two hypotheses. |
| **placebo** | one: the flow shifted **forward** five sessions, so the signal "predicts" a return that already happened | leakage detector. Its edge must be ≈ 0 or the pipeline is reading the future. |

### The verdict ladder, fixed before the run

Evaluated in this order, per cell, against that cell's own `costs.csv` row:

1. usable bucket-days < 200 → **UNINFORMATIVE_COVERAGE** (`S_PREREG` §4)
2. sign wrong **and** p < 0.025 → **WRONG_SIGN** (a different phenomenon)
3. edge ≥ `kill_threshold` **and** p < 0.025 → **PASS**, hold-out may open
4. MDE > `kill_threshold` → **UNINFORMATIVE_POWER**
5. otherwise → **UNINFORMATIVE_COST**

**There is no DEAD band for S2, and that is not a softening.** `COSTS.md`
reports S2's round trip as *unmeasured*: there is no quote lattice for a
negotiated par rate, so the only bound available is the ceiling
`2·sqrt(m2_trimmed)`, which is set by **our own curve error** (`s` = 0.26–0.68
bp) rather than by any observed bid-offer. S1 can say DEAD because it has a
measured 0.125 bp lattice floor to say it against; S2 has no floor at all. The
S2 kill rule is therefore one-sided by construction: an edge **above** the
ceiling hurdle clears under any reading of the cost, and an edge **below** it is
`UNINFORMATIVE_COST`, **not "no signal"**. Reporting S2 dead against a
1.06–2.79 bp hurdle would report a curve-error artefact as a market fact.

### Hurdles this is judged against (from `out/costs.csv`, unmodified)

`round_trip_used_bps` for `S2_OUTRIGHT_SOFR`, venue D2C, mapped from the cost
file's tenor bands to the TENOR10 buckets. `0-1Y` spans four sub-year bands in
the cost file and takes the **widest** of them, which is the conservative side
of a one-sided rule.

| bucket | cost band(s) | round trip | **kill = 2×** |
|---|---|---:|---:|
| 0-1Y | 0-1M / 1M-3M / 3M-6M / 6M-1Y | 1.397 | **2.794** |
| 2-3Y | 2Y-3Y | 1.360 | **2.719** |
| 3-5Y | 3Y-5Y | 1.363 | **2.726** |
| 5-7Y | 5Y-7Y | 0.876 | **1.753** |
| 7-10Y | 7Y-10Y | 0.800 | **1.601** |
| 10-15Y | 10Y-15Y | 0.809 | **1.617** |
| 15-20Y | 15Y-20Y | 1.135 | **2.271** |
| 20-30Y | 20Y-30Y | 0.968 | **1.936** |
| 30Y+ | 30Y+ | 0.984 | **1.969** |

(1-2Y is excluded by `S_PREREG` and is not tested.)

---

<!-- RESULTS BELOW THIS LINE WERE WRITTEN AFTER THE SINGLE PASS RAN -->

## 0. The answer

**No. There is no measurable multi-day reversal after dealer positioning, and
for once the test had the power to say so at the pooled level.**

| | |
|---|---|
| pooled `beta` (bp of rate per 1σ of flow) | **+0.024**, DK SE 0.665, **t = +0.04**, **p = 0.97** |
| pooled gross edge per trade | **−0.32 bp**, DK SE 0.599, p = 0.60 |
| pooled MDE (edge) | **1.85 bp** against a count-weighted kill threshold of **2.15 bp** |
| pre-registered verdict, pooled | **UNINFORMATIVE_COST** |
| pre-registered verdict, per bucket | 8 of 9 **UNINFORMATIVE_POWER**, 1 (`0-1Y`) UNINFORMATIVE_COST |
| **hold-out** | **not opened, and stays shut** |

The sign is the pre-registered one and the magnitude is nothing: 0.024 bp per
standard deviation of a bucket's own flow, against a five-day rate change whose
standard deviation is 11.9 bp. The edge per trade is **negative**, so the
one-sided cost caveat is not what is binding here — an edge of −0.32 bp does
not clear a cost of any size. The 98.75% one-sided upper bound on the pooled
gross edge is **+1.03 bp**, below twice even the *cheapest* per-bucket round
trip in `costs.csv` (2 × 0.800 = 1.60 bp at 7-10Y).

**Why the pooled verdict reads UNINFORMATIVE_COST rather than "dead".** The
ladder's band 5 is the S2-specific one-sided rule: `COSTS.md` could not measure
S2's round trip, so the hurdle is a ceiling set by our own curve error, and
this file is not entitled to convert "below that ceiling" into a market fact.
What *can* be said without the cost at all is the stronger and simpler
statement above: **the coefficient is a precisely estimated zero.**

---

## 1. Was the test able to see anything? Yes — measured three ways

`S_PREREG` §4 exists so that a null gets downgraded when it has no power. Two
of the three power questions come out in this test's favour and one does not.

**(a) The pooled cell is not power-limited against its own hurdle.**
MDE(edge) = 3.083 × 0.599 = **1.85 bp** < the count-weighted kill threshold of
**2.15 bp**. This is the first cell in this programme with the power to have
seen a hurdle-sized effect. It saw nothing.

**(b) The per-bucket cells ARE power-limited, and that is the honest limit.**
Eight of nine have MDE(edge) of 2.31–3.33 bp against hurdles of 1.60–2.79 bp,
so a single bucket could not have resolved a cost-clearing edge. Only `0-1Y`
(MDE 2.45 vs hurdle 2.79) clears, and its edge — the largest positive in the
table, +1.14 ± 0.79 bp — is well under its own hurdle. **Do not read the pooled
result as nine independent nulls.** It is one null with nine noisy pieces.

**(c) The machinery detects a real relation in this very panel.** The placebo —
the same flow series shifted **forward** five sessions — comes back at
**β = −4.30, t = −5.19, p = 3.8e-07** (edge −3.64 bp, p = 3.1e-10). Whatever
else is true, a panel and an estimator that resolve a 4.3 bp/σ relation at
p < 1e-6 are not too blunt to have found a 2 bp one. See §4 for what that
placebo actually means, because it is not a leak.

`N_eff`: the edge's DK standard error of 0.599 bp against a 11.9 bp dispersion
implies **~396 independent observations behind 2,763 bucket-days** — a variance
inflation of 7.0× from the five-day overlap and a mean cross-bucket `z`
correlation of 0.277. That factor is the whole reason the per-bucket cells
cannot clear their hurdles.

---

## 2. The primary test

`dR(t→t+5) = a + b·z(t) + e`, pooled over the nine tested buckets, 2,763
bucket-days on 307 sessions, 2024-06-03 .. 2025-08-22.

| | Driscoll–Kraay (governing) | day-clustered (prereg-literal) |
|---|---:|---:|
| `beta` (bp per 1σ) | +0.0240 | +0.0240 |
| SE | 0.665 | 0.452 |
| t | +0.036 | +0.053 |
| p | 0.971 | 0.958 |
| edge per trade | −0.316 bp | −0.316 bp |
| edge SE | 0.599 | 0.396 |
| edge p | 0.598 | 0.425 |

The two estimators agree on the verdict, so the "larger governs" rule never had
to arbitrate. It would have mattered if anything had been close: the validation
(§5) measures the day-clustered estimator rejecting a **true null 21.8% of the
time** at a nominal 5% under this test's own dependence structure, against 7.8%
for Driscoll–Kraay.

### Per bucket (diagnostics, not nine hypotheses)

| bucket | `beta` | t (DK) | edge bp | edge SE | MDE edge | kill | verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| 0-1Y | +1.129 | +1.29 | **+1.135** | 0.794 | 2.45 | 2.79 | UNINFORMATIVE_COST |
| 2-3Y | −0.389 | −0.33 | −0.834 | 0.989 | 3.05 | 2.72 | UNINFORMATIVE_POWER |
| 3-5Y | −0.314 | −0.30 | −0.991 | 1.063 | 3.28 | 2.73 | UNINFORMATIVE_POWER |
| 5-7Y | −0.662 | −0.62 | −0.529 | 0.946 | 2.92 | 1.75 | UNINFORMATIVE_POWER |
| 7-10Y | +0.458 | +0.45 | −0.548 | 1.079 | 3.33 | 1.60 | UNINFORMATIVE_POWER |
| 10-15Y | −0.346 | −0.33 | −0.272 | 0.908 | 2.80 | 1.62 | UNINFORMATIVE_POWER |
| 15-20Y | −0.139 | −0.17 | −0.888 | 0.752 | 2.32 | 2.27 | UNINFORMATIVE_POWER |
| 20-30Y | +0.205 | +0.20 | −1.101 | 0.895 | 2.76 | 1.94 | UNINFORMATIVE_POWER |
| 30Y+ | +0.333 | +0.56 | +1.178 | 0.750 | 2.31 | 1.97 | UNINFORMATIVE_POWER |

Four positive, five negative, none within a factor of two of significance. The
scatter across buckets (−0.66 to +1.13) is the sampling noise the pooled SE
already accounts for.

---

## 3. The secondary (conditional) test — and it points the wrong way

The one declared conditioner, the D2D/D2C ratio as a forced-dealer proxy:

`dR = a + b·z + c·(z·q) + d·q`, with `q` the own-history z of
`log((|D2D|+1)/(|D2C|+1))`. Every bucket-day has non-zero D2D flow, so the `+1`
guard never binds.

| term | coefficient | t (DK) | p (DK) | t (day-cl) | p (day-cl) |
|---|---:|---:|---:|---:|---:|
| `z` | +0.128 | +0.20 | 0.841 | +0.28 | 0.777 |
| **`z·q`** | **−1.096** | **−2.00** | **0.046** | −2.47 | 0.014 |
| `q` | −0.389 | −0.80 | 0.424 | | |

MDE on the interaction, as `S_PREREG` §4 requires for both hypotheses:
`3.083 × 0.548 = 1.69 bp` per 1σ of `z` per 1σ of `q`.

Two things have to be said about this, in this order.

1. **It does not clear the pre-registered bar.** p = 0.046 on the governing
   (larger) standard error, against ALPHA = 0.025 Bonferroni. Not significant.
2. **Its sign is the opposite of the mechanism it was declared to test.** The
   forced-dealer story says that when the dealer is recycling more risk
   interdealer — at a limit, forced — the reversal should be **stronger**, i.e.
   `c > 0`. The estimate is `c = −1.10`: the relation is *more negative* when the
   D2D/D2C ratio is high. Under `S_PREREG`'s own rule that a coefficient of the
   right size and the wrong sign is a different phenomenon, this is not partial
   support for the hypothesis; it is a marginal, wrong-signed coefficient in a
   secondary test that the primary already found nothing in. Reported, not
   pursued. Chasing it would be the search the pre-registration exists to stop.

---

## 4. The placebo fires hard, and it is not a leak

The flow shifted **forward** five sessions predicts the return that has already
happened: β = −4.30 (t = −5.19, p = 3.8e-07), edge −3.64 bp (p = 3.1e-10).

**What it means.** `z(t+5)` is measured *after* the return window closes, so
this is the tape saying that **customer flow responds to the move that just
happened**: over 2024-06 .. 2025-08, after rates fell, customers paid fixed
(the ladder goes positive — dealer received); after rates rose, they received.
That is a real property of the series, and the direction is contrarian.

**Why it is not evidence of a pipeline leak.** A leak would put future prints
inside `z(t)`, and future prints carry exactly this −4.3 bp/σ relation — so a
contaminated `z(t)` would show a *negative* primary coefficient. The primary is
**+0.024**. Leakage is also shut structurally rather than statistically: the
flow window closes **at** the 15:00 ET entry mark, and `flow_day_map` is pinned
by a seven-case known-answer test including the right-closed boundary, the
20:30 ET print that rolls to the next session, and the Friday-evening print
that rolls to Monday.

**What it costs the reader.** The SPEC's line — "its edge must be ≈ 0 or the
pipeline is reading the future" — was written before the run and has **not**
been edited; this paragraph is the disclosure that it over-claims, not a
retrospective softening of the spec. As written it is a leak detector *and* a
flow-reaction measurement, and on this data it is
dominated by the second. It is a weak leak bound (a contamination share would
have to exceed ~35% of the series to be detectable at this precision), which is
why the structural argument above is the one doing the work.

---

## 5. Everything that had to be true for the numbers above to mean anything

Each of these is a known-answer check, run before the result was read.

| check | answer | known answer it was checked against |
|---|---|---|
| the mid is unbiased on **this** population | D2C median (printed − mid) **+0.0030 bp**, 50.6% above mid, no tenor gradient (all \|median\| ≤ 0.09 bp over 13 bands, 361,259 units) | `WHAT_THE_LADDER_SUPPORTS` §0: +0.021 bp, CI includes zero. The premise of the whole re-test. |
| my repricing vs an independently written one | **max \|diff\| = 0.000e+00 bp** on 1,423 overlapping outrights over three days | `measure_costs.py`'s S2 cache, written by a different pass for a different purpose |
| my vectorised weighting vs the ladder's own loop | **max \|diff\| = 0.000e+00** on 200 units / 5,572 ladder rows | `ladder.unit_ladder_rows` |
| coverage vs the published skew factors | 0.741 / 0.544 / 0.666 / 0.574 / 0.567 / 0.564 / 0.661 / 0.540 / 0.552 / 0.690 by bucket | published 0.761 / 0.522 / 0.602 / 0.554 / 0.524 / 0.537 / 0.601 / 0.495 / 0.512 / 0.612 — same shape, 2–6 pp higher on a shorter window |
| the flow-day clock | 7 of 7 cases correct, incl. right-closed 15:00:00, 20:30 ET → next session, Friday 16:00 → Monday | hand-computed |
| the SE estimator under a true null | iid OLS **52.8%**, day-clustered **21.8%**, Driscoll–Kraay **7.8%** rejection at nominal 5% | 5%. The first simulation I wrote used an iid regressor, reported every estimator as fine, and **checked nothing** — an iid `x` makes OLS SEs approximately right however dependent `y` is. Replaced with a persistent, cross-sectionally correlated regressor, which is what `z` actually is. |
| the SE estimator with an effect present | recovers a planted β = +0.5 inside its own CI **94.0%** of the time | 95% |
| the target series | 2Y 339.5 / 5Y 333.7 / 10Y 369.0 / 30Y 407.6 bp on 2025-08-29; daily σ 4.7–6.0 bp; **zero** stale marks | quoted USD SOFR swap levels for that date |

**Build.** 371 tape days, 576,772 units, **99.04% priced** (5,538 `NO_CURVE`),
15,986,319 KRD rows. 2024-10-14 is the only day with no orientable SOFR flow — it is
Columbus Day, and its tape DV01 is 0.05% of a normal day. The readable day set
was asserted equal to the target day set before the panel was built.

---

## 6. Caveats, in the order they could matter

1. **Per-bucket, this test is under-powered and says nothing.** Only the pooled
   cell clears its hurdle on MDE. A bucket-level reversal of 2–3 bp per trade
   would not have been detected.
2. **The upfront rule's `tau` is borrowed.** The 171,130 `NPV_VS_UPFRONT` units
   (30% of the population) take `tau` from the same bucket's RATE-rule mixture
   fit rather than from a fit on upfront residuals
   (`upfront.fit_tau_upfront`). That saturates their `|2p−1|` towards 1 — a
   **weight** distortion, not a direction one, since the upfront sign comes
   from the edge-capture logic. Bounded by re-running the primary on the
   RATE-rule population alone: **β = +0.029 (t = +0.10), edge +0.008 bp**, i.e.
   the same null with a *smaller* standard error (MDE 1.06 bp). The borrowed
   `tau` is not holding a result up.
3. **S2's cost is a ceiling, not a measurement.** Per `COSTS.md`: no lattice
   exists for a negotiated par rate, so the hurdle is `2·sqrt(m2)` and is set by
   our own curve error. This is why band 5 is `UNINFORMATIVE_COST`. It does not
   rescue the result — the edge is negative — but it does mean this file cannot
   say "dead" the way S1 can.
4. **The KRD is dense.** rateslib's delta puts a non-zero number on all 28
   pillars for every unit, so `n_units` per bucket-day is the same 1,427 in
   every bucket and is not a liquidity measure. The *level* is still a genuine
   per-bucket key-rate quantity; only the unit count is uninformative.
5. **The 15:00 ET cut moves 13.4% of priced units off their `as_of_date`.**
   That is the London and evening flow being assigned to the next mark, which
   is correct on the availability clock and is the reason the position is
   takeable at all.
6. **Availability is the Appendix C legal estimate for 100% of these prints** —
   the lineage sidecar covers none of this window. A measured publication time
   would move some prints across the 15:00 boundary.
7. **Both sides of the test use the same curve.** The target's own measurement
   error (`s` = 0.26–0.68 bp per `COSTS.md`) is independent across the two ends
   of a five-day window, so it inflates the SE rather than biasing `beta` — but
   it is part of why the per-bucket MDEs are what they are.
8. **Calibration staleness runs to 7 calendar days** (5 sessions across a
   weekend) because the fit is refit every 5th session. 6,184 units in the
   first sessions have no trailing window and carry no `p`.
9. **A numerical guard was installed and it fired 6 times.**
   `upfront.classify` can hand `conventions.signed_weight` a `p` of
   `1.0000000000000002`, which that function rightly refuses; clipping is
   allowed within 1e-9 of the boundary and raises beyond it. Worst overshoot
   observed: **2.2e-16**, on 6 of 571,234 units. Dropping them instead would
   have dropped the most confident off-market calls, which is a biased sample.
   **This is a defect in `upfront.py` worth a line in the module's own ledger.**

---

## 7. What this does and does not settle

**Settles:** the dealer-ladder programme's "no signal" verdict was reached on
labels that were 78% one-directional, and this re-test was authorised because
that made the verdict uninformative rather than null. On unbiased labels, a
signed 28-pillar KRD vector, 371 days and 576,772 units, the answer at the
pooled level is the same — and this time it is a real null rather than an
artefact: **β = +0.024 ± 0.665, with the power to have resolved an effect the
size of the cost hurdle.**

**Does not settle:** anything per-bucket; anything at a horizon other than five
sessions; anything about the excluded 1-2Y bucket; anything cross-sectional
(forbidden until the package-skew recovery route lands); and the marginal,
wrong-signed D2D/D2C interaction, which is left exactly where it fell.

**The hold-out (2025-09-01 .. 2026-08-07) was not opened and must stay shut.**
Nothing cleared `S_PREREG` §1's kill rule.

