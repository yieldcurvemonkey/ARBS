# Fed Funds (ZQ) kink-fade — Findings

**Date:** 2026-07-30
**Branch:** `feat/sfr-kink-fade-v2`
**Design:** `2026-07-30-zq-kink-fade-design.md`
**Notebook:** `notebooks/backtests/zq_kink_fade_backtest.ipynb` (executed; 24 code
cells, 53 outputs, 4 figures, 0 unrun, 0 errors; 53s)
**Outputs:** `notebooks/data/zq_kink_fade/`

## The question

> Does the FF complex — with its cleaner meeting capture — pay the kink-fade
> where SR3 didn't, or does the coarser tick lattice kill it first?

## The answer

**Neither. It does not pay, and the tick lattice is not what stops it.**

**VERDICT: DEAD.** 0 of 6 league rows ALIVE, 0 with a positive grid median,
median DSR 0.0000.

The **oracle ceiling** is the whole story and it says stop before any signal work:

| structure | round trip | best oracle net, h=21, **across the entire penalty sweep** |
|---|---:|---:|
| M1-M2 calendar spread | 1.0bp | **+0.093bp** |
| 3-month butterfly | 2.0bp | **−0.778bp** |

With **perfect foresight of the direction**, at the most favourable smoothing
available, the FF kink earns nine hundredths of a basis point per trade on the
cheapest structure it has and loses on everything else. The sweep spans every
definition of the kink between "fit every meeting jump exactly" and "the Fed is
a metronome", so this is not a statement about one parameterisation.

For comparison, SR3's oracle was 2.378bp against a 2.0bp round trip — marginal,
and it still failed. FF's is not marginal.

## Why — and it is the opposite of the expected reason

The brief's premise was that ZQ is the natural habitat for this thesis because
its settlement is exactly computable. That premise is **correct**, and it is
exactly why there is nothing to trade.

ZQ settles on the arithmetic average of daily EFFR over one calendar month, so a
day-weighted blend of policy regimes is not an *approximation* of the contract —
it **is** the contract. Solving the strip for per-meeting jumps and then forcing
the policy path onto a straight line in meeting index (the least flattering
setting available) still leaves:

| | raw sd | residual sd | model explains |
|---|---:|---:|---:|
| M1-M2 spread | 9.03bp | 2.69bp | **91%** |
| 3-month fly | 5.12bp | 3.45bp | 55% |

against round trips of 1.0bp and 2.0bp.

**The kink is real, it reverts, and the room is not there.** Median fitted
half-life of the per-contract residual is **13 days** — *faster* than the 28–53
days the SR3 lab fitted on its tradeable slots. The FF kink does exactly what the
thesis says it should. It simply does it inside a band narrower than the
bid-ask: at `lam=100` the residual spread's sd is **2.61bp**, its mean 21-day
move **1.06bp**, and only **33%** of entries move further than the 1.0bp it costs
to take them.

> SR3's compounded quarterly window is a **messy** read on policy, and that mess
> is where a butterfly's dispersion comes from. ZQ's monthly arithmetic average
> is a **clean** read, so almost nothing is left over. Cleanliness and
> opportunity turn out to be the same axis, pointing opposite ways — which is
> also why the SR3 companion notebook's best pond was the **12m** fly, the
> messiest structure it could build.

---

## 1. The penalty sweep, in full

Read the two ends. At `lam=0` the fit is free (12 contracts against 8–9
identifiable meetings plus an intercept, so 2–4 degrees of freedom) and the
residual is 0.38 ticks — small because the fit is loose, which is a statement
about the model and not the market. At the stiff end the policy path is a
straight line and the residual is everything a perfectly regular Fed cannot
express. **The oracle is below cost at every point in between.**

| lam | residual sd | ticks | spread oracle h21 | fly oracle h21 | spread P(beat cost) |
|---:|---:|---:|---:|---:|---:|
| 0 | 0.189 | 0.38 | −0.794 | −1.597 | 0.014 |
| 0.1 | 0.800 | 1.60 | −0.460 | −1.146 | 0.150 |
| 1 | 1.106 | 2.21 | −0.285 | −0.976 | 0.222 |
| 10 | 1.750 | 3.50 | −0.100 | −0.871 | 0.280 |
| 100 | 2.294 | 4.59 | **+0.059** | −0.795 | 0.328 |
| 1e3 | 2.389 | 4.78 | **+0.089** | −0.780 | 0.337 |
| 1e5 | 2.400 | 4.80 | **+0.093** | −0.778 | 0.338 |

The saturation trap is worth naming because the SR3 lab fell into a version of
it: an unpenalised residual is small *by construction* and reporting it as "the
market prices policy almost perfectly" would be circular. The λ sweep is what
makes the number mean anything.

## 2. What the raw structures can do

The kink is dead, but the **raw** spread is not — and the split is instructive.

| structure | differential exposure | keys | sd (ticks) | oracle net h21 | P(beat cost) |
|---|---|---:|---:|---:|---:|
| M1-M2 spread | (0, 0.2] | 1 | 2.4 | −0.392 | 0.22 |
| M1-M2 spread | (0.2, 0.5] | 38 | 13.3 | +0.615 | 0.50 |
| **M1-M2 spread** | **(0.5, 1.0]** | **74** | **20.1** | **+1.548** | **0.59** |
| 3-month fly | (0, 0.2] | 21 | 4.3 | −1.294 | 0.07 |
| 3-month fly | (0.2, 0.5] | 17 | 8.4 | −0.860 | 0.15 |
| 3-month fly | (0.5, 1.0] | 74 | 11.5 | −0.182 | 0.28 |

The spread's headroom scales with how much of a policy decision it carries,
which is the point: **that is a directional meeting trade, not a kink fade.** The
FF butterfly's oracle is negative in every bucket at every horizon shorter than
a month.

Run through the full house treatment anyway, the high-exposure spread delivers
**+0.305bp per trade over 204 trades** against an oracle of ~1.5bp — it harvests
20% of what is available — with a grid median of **−245.5bp** and DSR 0.000.
`SELECTION-ARTIFACT`.

## 3. Two premises in the brief that the data contradicted

**"Adjacent no-meeting months are structurally pinned."** They are not. The first
pass of this work used exactly that criterion and the data said so: the "no
meeting between the delivery-month starts" spreads moved *further* than the
others (sd 9.5bp against 8.8bp). November/December has no decision between the
1st of November and the 1st of December, yet the December contract is 22/31
exposed to the December meeting *inside its own month* while November is not
exposed at all — the spread carries most of a decision.

The right criterion is **differential exposure**, `max_m |Σ_j w_j·W[leg_j,m]|`,
which is zero only when every meeting loads identically on every leg. Measured:
**not one** of the 113 adjacent pairs or 112 three-month flies is pinned. The
range is 0.13 to 1.00 of a decision for spreads and 0.03 to 1.00 for flies.

**"The tick lattice is worse here."** It is not the binding constraint. The
high-exposure M1-M2 spread runs **20.5 ticks** of dispersion (10.26bp) and is
unchanged on 42.9% of days — comparable to SR3's *tradeable* front slots, not to its degenerate
back end (`SFR-14-15-16` was 1.0 tick). The lattice is fine; the residual is what
is small.

## 4. The convention trap, resolved by measurement

A compounded window overstates the arithmetic average by `r²·n/720` — **0.69bp
on a 31-day month at 4%**, nearly three ZQ half-ticks, i.e. the size of the
signal being tested.

**No analytical correction is needed.** rateslib's `usd_stir1` spec is already
the monthly averaged contract (`frequency: m`, `roll: som`,
`leg2_fixing_method: rfr_payment_delay_avg`, `bp_value: 41.67`), while
`usd_stir` is quarterly IMM and compounded at $25/bp. Measured directly on a
curve, the two are **0.658bp** apart on identical dates — matching the formula.

> ⚠ **Live trap, reported not fixed.** `is_ser` — the flag selecting
> `ReferenceRate3` (`usd_stir1`) over `ReferenceRate2` (`usd_stir`) — is derived
> from `root in {SR1, SER, SL}` at `RLSTIRFuturePricer.py:276`, `:350` and
> `MDP/IRSwaps/BARCHART_STIRF/rl.py:2521`. **`ZQ` is not in that set.** A ZQ
> routed through those predicates against a curve whose `ReferenceRate2` is
> `usd_stir` silently selects the quarterly compounded contract at $25/bp — the
> wrong instrument, not a close one. Only
> `SDRUtils/stir_flow/ladder.py:37-40` gets it right, by passing `is_ser=True`
> explicitly. On the path exercised here rateslib refuses to build the schedule
> at all, which is luck rather than design.

## 5. The curve golden test — MIX23 recovers ZQ, but not to 0.5bp

Curve-implied ZQ against the actual settle, 12 front pre-accrual contracts on
2026-07-10:

| snapshot | mean gap | median abs gap | max abs gap |
|---|---:|---:|---:|
| 15:40 ET (the brief's timestamp) | −0.866bp | 1.167bp | 2.063bp |
| **17:00 ET (matches the settle)** | **−0.097bp** | **0.851bp** | **1.634bp** |

Three findings:

1. **The timestamp matters.** The 15:40 comparison carries an hour of market
   drift against an EOD settle; matching the snapshot to the settle removes the
   bias entirely (−0.87bp → −0.10bp).
2. **The date convention does not.** Building with the exact calendar month and
   with `contract_grid`'s business-day window gave *identical* rates to 1e-9 —
   the `roll: som` / `mf` spec normalises both to the same schedule. The worry
   was legitimate and the answer is that it does not bite on this path.
3. **MIX23 is EFFR-aware but not calibrated to ZQ.** The bias is nil but the
   dispersion is 0.85bp median absolute — **1.7 ZQ ticks**, which **fails** the
   brief's ≲0.5bp tie-out. For contrast the same machinery on the SOFR curve
   gaps by **+3.2bp** mean, which is the SOFR-FF basis, so the SERFF skew is
   genuinely doing its job. Consistent with the curve's construction: MIX23
   *fetches* FFCM1-12 but pulls the ZQ pricers out of the solver instrument set
   (`rl.py:328-330`) and uses them only to build the SER−FF basis.

**Consequence for the study:** the curve cannot define a kink at 0.5bp
resolution because its own noise is 1.7 ticks. Marks are settles — which the
house rule required anyway — and the curve is a diagnostic with a stated noise
floor.

## 6. Rulebook details that turned out to matter

**The carry rule bites exactly once.** §22103 forward-fills EFFR on
non-publication days, so a Friday's print carries Fri+Sat+Sun. Because every
FOMC decision lands on a Wednesday or Thursday, its effective day is normally a
publication day and the carry rule moves no weight at all. Sweeping 2018–2027
there is **exactly one exception**: **2025-06-18 → 2025-06-19 is Juneteenth**, a
federal holiday since 2021, so the new rate first reaches the average on Friday
the 20th. That moves one of June 2025's thirty days from post to pre — 3.3% of
that contract's exposure to the meeting, ~0.8bp on a 25bp move. Found by a test
that asserted the *opposite*.

**The half-tick is economically irrelevant but precisely encoded.** §22102.C's
two branches are implemented exactly (Sat/Sun/Mon start → first trading day of
the month; Tue–Fri start → the trading day after the last Sunday of the
preceding month, which can be a week early; June 2027 is the edge case where
Memorial Day pushes the anchor onto the 1st itself). Measured across the
tradeable pre-accrual window, the reduced tick applies to **0.6% of live
contract-days**, because the discount only starts once a contract is days from
ceasing to be a forward read. So the cost model is 0.5bp per contract in
practice — but the claim is measured, not assumed.

**Settlement rounding needs decimal arithmetic.** §22103 rounds to the nearest
tenth of a basis point with ties **up**. The obvious `floor(x/step + 0.5)*step`
gets **2.5925** wrong: in binary that is 2592.4999999999995 steps, a hair below
the tie, so it rounds down to 2.592 when the rule says 2.593. Python's `round`
is worse — it breaks exact ties to even. Half a tenth of a basis point is $2.08
a contract. Caught by a test written from the rulebook rather than from the
implementation.

## 7. Data

`notebooks/rv/build_zq_panel.py` — the monthly twin of `build_sfr_fly_panel.py`.
Barchart's root for Fed Funds is already `ZQ`, so only the contract-code
generation changes.

**2018-01-02 → 2026-07-30, 2,159 sessions, 132 contracts, 103,483 contract-days**,
median 47 pre-accrual contracts per session; the study uses ranks 1–12. Per-rank
zero-volume and open-interest tables are printed in the notebook rather than a
depth assumption being made.

## 8. What I would test next

1. **Stop looking for an FF kink; the FF *meeting* trade is the live object.**
   The high-exposure M1-M2 spread has an oracle of +1.55bp against a 1.0bp round
   trip. Nothing in this lab predicts its direction, but the pond is real and
   the structure is the cleanest policy expression in the listed complex. That
   is a *forecasting* problem, not an RV one, and it wants a different lab.
2. **The SR3↔FF cross-market kink** (the SERFF basis kink) was a stretch goal
   conditional on 1–2 surviving. They did not, so it was not run. It is also the
   one FF structure whose residual could plausibly be larger, because the two
   complexes read the same meetings through different windows and the basis has
   its own dynamics — `BT/serff` already models it.
3. **Fix or wrap the `is_ser` root predicate** so `ZQ` selects the averaged spec
   by construction rather than by the caller remembering. A one-line set
   membership, and the current safety is that rateslib happens to raise.
4. **Turn-of-month EFFR.** The residual this lab measures is whatever a
   policy-step path cannot express, and month-end/quarter-end EFFR pressure is a
   known, dateable part of it. Modelling it would shrink the residual further —
   which makes the trade *worse*, not better, and is worth confirming for that
   reason alone.

---

## Appendix — what was built

**`RVUtils/MeanRev/ff.py`** (new): the ZQ contract calendar; the EFFR publication
calendar and §22103's carry rule; `zq_exposure_vector` / `zq_exposure_matrix` /
`zq_regime_weights` (a partition of the month's days, summing to exactly 1);
`expected_settle_rate`; `round_settle_rate` (decimal, ties up);
`compounding_bias_bp`; `half_tick_onset` / `tick_bp` / `round_trip_bp` encoding
§22102.C exactly. **27 synthetic no-network tests**, every assertion derived from
the rulebook or hand-arithmetic rather than from the implementation's own output.

**`notebooks/rv/build_zq_panel.py`** — the ZQ panel builder.

**`notebooks/backtests/zq_kink_fade_common.py`** — re-exports every reporting
block from `sfr_fly_meanrev_common` unchanged so all three labs are graded by
identical code, plus `load_zq`, `zq_structures` (with the differential-exposure
degeneracy measure), `meeting_residual_panel_zq`, `zq_cost_panel` (masked to live
cells), `implied_jump_panel`, `zq_shadow_block` (a spread's shadows are its
outright legs) and `zq_run_family`.

**Probes, all runnable:** `_probe_zq_curve.py` (the golden test),
`_probe_zq_oracle.py` (the first pass, with the wrong degeneracy criterion, kept
because the record of it being wrong is the point), `_probe_zq_oracle2.py`
(the corrected criterion), `_probe_zq_oracle3.py` (the penalty sweep).
