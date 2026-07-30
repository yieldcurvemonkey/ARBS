# Does dealer positioning inferred from public SDR prints predict SR3 / ZQ?

**Status:** PRE-REGISTRATION LOCKED — results pending
**Pre-registration written:** 2026-07-29, before any G4 statistic was computed
**Plan:** `docs/superpowers/plans/2026-07-14-dealer-ladder-infrastructure.md` (Task 10, gates G0–G5)
**Audit that set the gates:** `docs/superpowers/audits/2026-07-15-sdr-dealer-positioning-feasibility-audit.md`
**Running journal:** `docs/superpowers/plans/2026-07-29-dealer-ladder-research-journal.md`

> **Verdict:** _pending — will be written here, first, once G0–G5 have run._
>
> Per spec §9c the verdict is exactly one of: **(i)** mechanism supported *and* priced edge
> survives OOS and costs → Phase 5 planning; **(ii)** a price effect exists but the mechanism is
> unsupported or costs kill it → relabel as basis / flow continuation and park; **(iii)** no
> robust effect → negative result, and the ladder remains a positioning observable.
> A rigorously established negative is a fully successful outcome of this study.

---

## 0. What is being tested, and what is *not*

The observable is a **model-labelled D2C flow proxy**, never "dealer inventory". Direction is
inferred by comparing a print to a decision-time curve mid (on-market) or a repriced NPV to the
reported upfront (off-market). It is not an observed counterparty field, and it is **uncertified**
against external truth labels: no desk tickets or confirmations were available, so no accuracy
number is claimed. Everything below inherits that.

Three consequences are carried through every gate:

1. **Attenuation.** With independent sign accuracy `a`, signed exposure scales by `(2a − 1)`.
   Every headline number is reported at `a ∈ {0.6, 0.7, 0.8}` (retaining 20% / 40% / 60%).
2. **Off-market prints are a separate stratum.** The `NPV_VS_UPFRONT` rule *constructs* a
   non-negative dealer edge by choosing the side, so a positive edge cannot validate it. Excluded
   from the primary universe; reported separately with full reversal and omission sensitivity.
3. **`TICK_RULE` prints are excluded** from the primary universe entirely — they infer direction
   from a preceding reported swap rate, not from a quote.

---

## 1. Pre-registered PRIMARY specification (locked — exactly one test)

Locked before computing any G4 statistic. One horizon, one bucket space, one basket, one arrival
convention, one cost model, one exposure rule, one threshold.

| Element | Locked choice |
|---|---|
| **Signal space** | `FUTURES` (SR3 contract buckets) |
| **Signal** | `ladder_at(space="FUTURES", half_lives={default:90, block:240}, weighting="expected", include_suspect=False)`, per contract |
| **Standardisation** | z-score of the signal against **its own trailing 10-trading-day** distribution sampled on the same intraday grid; trailing only, no centring on future data |
| **Universe** | `dealer_direction ∈ {PAID, RECEIVED}`, whitelisted D2C platform, `curve_suspect_trade = FALSE`, on-market methods only (`RATE_VS_MID` / `SPREAD_VS_MID` / `FLY_VS_MID`); `TICK_RULE` and `NPV_VS_UPFRONT` excluded |
| **Decision grid** | every 5 minutes, 08:00–16:00 ET, US business days |
| **Arrival** | `visibility_timestamp` = 17 CFR Part 43 Appendix C legal delay class per print (Task A1); actual-arrival replay |
| **Target** | change in the **implied rate** (bp) of the *same* SR3 contract over the next **60 minutes** |
| **Basket** | SR3 front 6 contracts |
| **Direction of the hypothesis** | `delta_dv01 > 0` ⟺ dealer long futures-equivalent ⟺ dealer must **sell** futures to hedge ⟹ predicted **rate rises**. So the predicted sign of Δrate is `+sign(ladder)`. |
| **Trigger** | `|z| ≥ 1.0` |
| **Exposure** | fixed: 1 unit of contract DV01 per triggered (contract, time); a new trigger while that contract's position is open is **ignored** (non-overlapping per contract) |
| **Costs** | conservative round trip per §5: SR3 0.5 bp / \$12.50 deferred, 0.25 bp / \$6.25 only within the final four months before last trading day |
| **Primary statistic** | mean **net** P&L per trade in bp |
| **Standard error** | day-blocked (cluster by ET calendar date) |
| **Pass condition** | mean net > 0 **and** raw t ≥ 3 |

**Why `FUTURES` and not `MEETING` for the signal.** The plan's Task 10 draft named a MEETING-space
z-score; the later bench ordering makes SR3-in-`FUTURES` the primary bench. Using `FUTURES` for the
signal aligns signal and target contract-by-contract and removes an arbitrary meeting→contract
mapping layer, so it is both the more powerful and the less arbitrary test. The MEETING-space
variant is retained in the secondary grid, so nothing is discarded. **`MEETING` is never a test
target** — it has no traded instrument, so a ladder-vs-MEETING test would be model-internal and
circular by construction. `SERFF_BASIS` is conditioning only, never a target.

---

## 2. Secondary grid, and how it is judged

The secondary family is the cross product:

- horizons: 5m, 15m, 30m, 1h, 4h, 1d
- signal spaces: `FUTURES`, `FED_FUNDS`, `MEETING`
- half-lives (min): 30, 90, 240, 1440
- weightings: `expected` (`1 − 2·p_flip`), `unweighted`
- targets: SR3 front-6 (primary bench), ZQ front-6 (cross-check)

Judged by **day-blocked bootstrap max-t / Romano–Wolf stepdown**, family-wise `p < 0.05`,
resampling whole ET dates so cross-contract and cross-horizon correlation is preserved. Every
variant is published, including the ones that fail. A **trial ledger** records every configuration
evaluated, in order, including manual one-off explorations — no cherry-picking.

### SR3 vs ZQ is a mechanism discriminator, not a robustness check

- ladder leads **SR3 but not ZQ** ⟹ liquidity-routed hedging (hedge goes where depth is);
- ladder leads **ZQ specifically** ⟹ meeting-targeted hedging;
- ladder leads **neither** ⟹ no hedge channel at these horizons.

---

## 3. Temporal split and the burn rule

Realized window (probed 2026-07-29 — both ladder curves and the independent Citi mid exist
throughout, so no shrinkage was needed):

| Segment | Dates | Trading days |
|---|---|---|
| In-sample / development | 2026-01-12 → 2026-06-09 | 104 |
| **One-shot lockout** | **2026-06-10 → 2026-07-29** | **34 (6.8 weeks)** |

Holidays excluded: 01-19, 02-16, 05-25, 06-19, 07-03.

**Burn rule, decided in advance.** The lockout is evaluated **once**. If the primary spec fails it —
wrong sign, or mean net ≤ 0, or t < 3 — the configuration is **burned**: no re-optimisation on the
holdout, no second lockout evaluation, no "adjusted" primary. The verdict then cannot be (i); it is
(ii) or (iii) on the in-sample evidence alone. Every fitted parameter (z-score moments, any
calibrated half-life, any threshold) is fitted walk-forward on trailing data only.

**The burn rule is enforced in code, not by my discipline.** A promise not to look twice is the
weakest kind of no-lookahead control, so `BT/dealer_ladder/lockout.py` makes it mechanical.
Reaching the holdout — the only path is `run_primary(in_sample=False)` — writes
`BT/results/dealer_ladder/LOCKOUT_USED.json` recording a fingerprint of the **whole** configuration
plus the code vintage, git SHA and wall clock. Re-running the *same* fingerprint is allowed and
idempotent (same spec over the same data is the same number — a re-render, not a second shot);
claiming under a *different* fingerprint raises `LockoutAlreadyBurned`. The fingerprint covers the
window, universe, signal, cost model, primary block and statistics config, because widening the
universe or softening the cost model changes the test exactly as much as moving the horizon does,
and sliding the lockout boundary would otherwise be a free re-registration. An unreadable ledger
counts as **claimed**, since "cannot parse" must never be the one path back to a second shot. A
`force=True` override exists for a deliberate, documented re-registration and stamps
`overrode_prior` into the ledger, so no override is ever invisible. The ledger is committed
alongside these findings; deleting it is a visible act in the git history rather than an invisible
one in a notebook.

Also fixed as part of this: G2 and G3 originally ran over the **whole** window including the
holdout. Since a G3 failure is precisely the verdict that prompts re-specifying the controls, that
would have burned the holdout silently before the primary ever reached it. Both are now in-sample
by default (`gates.run_g2`, `gates.run_g3`, commit `45a6d797`).

---

## 4. Placebos, all pre-specified

| Placebo | Expected behaviour if the effect is real | Interpretation if it fires |
|---|---|---|
| **Sign shuffle within day** | destroyed (mean ≈ 0) | the result is print *intensity*, not signed direction |
| **Pre-arrival window** — same statistic over the 60 min *before* `visibility_timestamp` | ≈ 0 | leakage, or the market already knew: not a post-disclosure edge |
| **Arrival shifted one grid step later** (+5 min) | largely preserved | effect is knife-edge in timing, i.e. not economically usable |
| **Unrelated contract** — signal for contract *i* against returns of a far-deferred contract | ≈ 0 | generic curve continuation, not bucket-specific |
| **All-+15 min live parity** — floor every visibility at exec + 15 min | attenuated but same sign | production's 15-minute delay removes the edge |

A **label-free** cell is reported alongside: print **intensity and dispersion** (unsigned), which is
immune to classification accuracy. If only the unsigned cell works, the finding is a flow-activity
effect and the direction model is not carrying it.

---

## 5. Cost model (locked)

From `BT/serff/config.py` conventions:

| Contract | DV01 / contract | Minimum increment | Applies |
|---|---|---|---|
| SR3 | \$25.00 / bp | 0.25 bp = \$6.25 | **only** within the final four months before last trading day |
| SR3 (deferred) | \$25.00 / bp | 0.50 bp = \$12.50 | all other quarterlies |
| ZQ / SR1 | \$41.67 / bp | 0.50 bp ≈ \$20.84 | all |

Round trip is charged at the full quoted increment for the contract's own tenor bucket — the
optimistic one-tick convention, treated as a **lower bound** on cost, not an estimate. An eight-leg
deferred SR3 strip therefore carries ≈ 0.45–0.50 bp round-trip in portfolio-DV01 terms before
slippage, queue loss, legging and impact.

---

## 6. Honest power accounting

Independent observations are set by the signal's integration window, not by the number of minute
bars. At a 90-minute half-life the integration window is ≈ 260 minutes, so 104 in-sample trading
days of an 8-hour session give **≈ 150 independent score epochs**, not ~50,000 minutes; at a
240-minute half-life it is ≈ 56. Correlated contracts are not independent replications.

At ~125 independent observations, the 80%-power minimum detectable standardised effect is ≈ **0.25**
for a single test and ≈ **0.35** under a 20-variant Bonferroni illustration. This study can
decisively reject a large, obvious effect. It **cannot** establish that a small effect is durable,
causal, or capacity-bearing, and no claim of that kind will be made from it.

---

## 7. Gate outcomes

Every gate reports its outcome whether it passes or fails. A failure is a result, not a blocker to
route around.

Each subsection states **what the outcome will mean, written before the numbers exist**. That is
the same discipline as the pre-registered specification, applied to interpretation rather than to the
statistic: deciding after the fact what a failed G2 implies is how a mechanism gate becomes a
formality, because whichever reading is convenient at that moment becomes the reading. Only the
values are outstanding.

### G0 — Labels and provenance

*What is being established:* who is in the signed universe, what each exclusion costs, and how far
our direction label sits from an independent one.

*How to read it.* G0 has no pass/fail — it is a measurement of the input, and the number it produces
bounds every claim downstream. A **flip rate near 50%** would mean the label carries essentially no
information and the whole signed study collapses to the label-free cell. A **flip rate near 0%**
would mean our mid and the independent mid agree and the direction label can be taken at close to
face value. Anything between bounds the attenuation: accuracy ≤ 1 − f/2, and the `(2a−1)` grid must
be read against that ceiling. The **`false_negative` column of the mechanism table** decides
whether the disagreement is curve gap (a closed form) or something else (which would be a different
and more troubling finding).

*Preliminary, on Jan+Feb:* 34.9% on 1,155 comparisons, ceiling 79.6%, zero false negatives. See
§8.1.

### G1 — Arrival integrity

*What is being established:* that no feature at decision time `t` uses a print that was not yet
public at `t`.

*How to read it.* This one is binary and non-negotiable. **Any** audit failing invalidates
everything after it, and the run stops being a study and becomes a bug report. The subtler failure
is a **vacuous pass** — an audit that reports clean because it was never given anything to detect —
which is why `max_future_prints` is reported beside the verdict and a zero there is itself a
failure. That is not hypothetical: the first version of this battery passed on a builder leaking
five hours of future flow (see the journal, 2026-07-30 review).

### G2 — Mechanism ordering (runs before any price test)

*What is being established:* whether a signed ladder innovation PRECEDES signed futures flow, in
the direction the forced-hedge story requires.

*How to read it.* Three distinguishable outcomes, and they lead to different papers.

1. **Timing lead with negative peak rho** — the forced-hedge channel is supported, and a subsequent
   price result may be attributed to it.
2. **Timing lead with positive peak rho** — the ladder leads futures in the ANTI-hedging direction.
   This *refutes* the channel rather than supporting it, and no price result may be attributed to
   hedging. LLS alone cannot see this, being built from squared correlations, which is why the
   signed peak correlation is reported separately.
3. **No timing lead** — the channel is unsupported. A price result would then have to be relabelled
   basis or flow continuation, which is verdict (ii), and G4 becomes a description of a correlation
   rather than evidence of a mechanism.

The **SR3-vs-ZQ comparison** then splits outcome 1: leading SR3 but not ZQ reads as
liquidity-routed hedging, leading ZQ specifically reads as meeting-targeted, leading **both** is
undiscriminating and must not be quoted as though it discriminated, and leading neither is no
evidence at all.

### G3 — Circularity battery

*What is being established:* whether the ladder's coefficient survives the swap-futures basis, and
then whether it survives a basis our own curve did not produce.

*How to read it.* The coefficient must survive **both** races, and with the **sign the hypothesis
predicts** — `|t| ≥ 2` alone would admit a coefficient pointing the wrong way, which is a refutation
wearing the costume of a pass. Collapse against our own basis means the effect *is* the basis.
Survival against ours but collapse against the independent one means it was curve-fit error, which
is the single most likely benign explanation given §8.1. Before reading any of it, check
`rank_deficient` and the point-in-time drop rate: a survival claim over a degenerate design, or over
controls thinned by the point-in-time filter, is not a claim.

### G4 — Pre-registered price prediction

*What is being established:* the one locked test — SR3 front six, 1h horizon, `|z| ≥ 1`, net of
costs, day-blocked, **pass requires mean > 0 and raw t ≥ 3**.

*How to read it.* Two things must be checked before the t-statistic means anything.

**`share_long`.** The rule is ~80% one-sided (§8.4), so it must be read against the
constant-position benchmark. **If it does not beat the better constant, the ladder contributes
nothing beyond direction**, whatever the t. That check comes first.

**The placebos.** Sign shuffle surviving means the result is print *intensity*, not direction — but
with the `share_long` caveat, since the shuffle also removes the PAID skew. Pre-arrival firing means
leakage or anticipation. Rotated buckets surviving means generic curve continuation. Live-parity
collapse means production's 15-minute delay removes the edge, which is fatal to usability even if
the effect is real.

The **secondary grid** is judged by day-blocked Romano-Wolf at FWER < 0.05 over the whole declared
family, with the skipped-variant ledger read alongside so untested is never mistaken for weak. Rows
differing only in `weighting` are duplicates, not robustness (§8.3).

### G5 — Economics and capacity

*What is being established:* whether anything survives costs and attenuation, and how much size the
traded volume could have supported.

*How to read it.* The pass criterion is `(2a−1)·gross − cost > 0` at the **worst** grid accuracy —
attenuating the net figure instead would discount the cost along with the edge and the gate could
never fail. Given §8.1, `a = 0.8` is at or above the measured ceiling, so the honest reading sits at
`a = 0.6–0.7`. Capacity is a **traded-volume sensitivity, not measured depth**: this repo has no
historical depth data, so it is an upper bound on what depth would allow and must never be quoted
as a size the strategy could carry.

### The outcomes

Run 2026-07-30, code vintage `468474ca6f84`, in-sample segment only. Every reading below is the
one written above **before** the numbers existed.

| gate | outcome | |
|---|---|---|
| G0 | flip rate **0.398**, 84,201 units → **28,704 signed**, PAID share 0.771 | measurement |
| G1 | all arrival audits pass, poison audit exercised on **343,116** future prints | **PASS** |
| G2 SR3 | LLS mean −4.769 (t = −2.45), peak ρ −0.035, 104 sessions | **FAIL** |
| G2 ZQ | LLS mean −19.88 (t = −1.78), peak ρ −0.005 | **FAIL** |
| G2 cross-check | leads **neither** | no evidence |
| G3 SR3 | signal t **alone = 0.14**; vs our controls 0.50; vs independent basis 0.84 | **FAIL** |
| G3 ZQ | t alone −1.47; coefficient **−0.01176, opposite to the hypothesis** | **FAIL** |
| G4 primary | net **−0.5458 bp/trade**, t = −9.44, n = 1,639 over 99 sessions, share_long 0.277 | **FAIL** |
| G5 | **gross −0.0458 bp, t = −0.79 (no stars)**; cost 0.500; at a = 0.6 → −0.5092 | **FAIL** |

**The single number that matters is G5's gross: −0.0458 bp/trade at t = −0.79.** The gross edge
is statistically indistinguishable from zero. Everything else follows from that.

**The `t = −9.44***` on the primary is not evidence of anything.** It is what you get when a
near-constant 0.5 bp round-trip cost is subtracted from a zero-mean quantity and the difference is
tested against zero across 1,639 trades. The same arithmetic produces the Romano-Wolf table, where
every one of the 96 variants lands within a whisker of −0.50 with |t| between 79 and 311 and
standard errors as small as 0.0016 — those t-statistics measure the *cost constant*, not a
prediction. Read as a signal result they would be a spectacular finding in the wrong direction;
read correctly they say the strategy reliably pays the spread and reliably earns nothing.

**The placebos only became legible once reported gross.** Net-of-cost, all six arms sit between
−0.448 and −0.546 and every one reads as "survives", including the two whose pre-written
expectation was "~0". That was the cost swamping the comparison, not a finding, and the suite now
reports both (commit `fix(dealer-ladder): report placebos on GROSS`).

On gross the six span **−0.046 to +0.052 — every arm is zero.** Sign-shuffle, bucket-rotation and
pre-arrival all produce the same nothing as the reference, which is the signature of no
bucket-specific, no direction-specific and no timing-specific content whatever.

| placebo | net (measured) | gross | pre-written expectation |
|---|---|---|---|
| none (reference) | −0.546 | **−0.046** | the effect, if any |
| sign shuffle within session | −0.448 | **+0.052** | destroyed; survival ⇒ intensity not direction |
| arrival +1 grid step later | −0.537 | **−0.037** | largely preserved; loss ⇒ knife-edge timing |
| live parity (exec+15m floor) | −0.540 | **−0.040** | attenuated, same sign |
| rotated buckets | −0.520 | **−0.020** | ~0; survival ⇒ generic curve continuation |
| pre-arrival window | −0.458 | **+0.042** | ~0; a result ⇒ leakage or anticipation |

> The gross column here is **derived** as net + the measured round-trip cost of 0.500 bp, not
> independently estimated: the placebo fix was committed after this run had already loaded its
> code, so both arms of the run predate it. The derivation is exact to ~0.001 bp because every
> variant trades the same SR3 front-six bucket set under one cost model, but it carries no
> standard error of its own, so the `gross_t` for each arm is **not** claimed here. It is
> re-measured directly in the follow-up run recorded in §9.

**The label-free cell rules out the obvious excuse.** Unsigned print intensity — no direction label
involved, so immune to every §8.1 concern about the classifier — returns net −0.6402 bp
(t = −9.03, n = 1,838), which is the cost again. The negative result is not an artifact of
uncertified direction labels; there is nothing there to mislabel.

**G2 failed in the most informative way available.** The lead-lag statistic is *negative* in both
spaces (−4.769 in SR3, −19.88 in ZQ): futures move **before** the ladder innovation, not after.
By the time a print is public the futures move has already happened. That is not a weak signal, it
is the wrong causal order for the trade to exist, and the SR3-vs-ZQ cross-check confirms it leads
neither.

---

## 7b. Verdict

**Verdict (iii): no evidence of a predictive signal.** Not (ii) — (ii) would require a real
correlation to relabel as basis or flow continuation, and there is no correlation to relabel. The
ladder's coefficient has a univariate t of **0.14** before any control is applied.

Stated as strongly as the evidence permits, and no more strongly:

- **Dealer positioning estimated from public SDR prints does not predict subsequent SR3 or ZQ
  returns at the pre-registered one-hour horizon**, at a gross magnitude this design could detect.
- The mechanism the hypothesis rests on — dealers forced to hedge inherited risk into futures — is
  **unsupported by the ordering evidence, in both spaces**, and the ordering runs the wrong way.
- The result is **not cost-marginal**. A frequent misreading of a −0.55 bp net is "the edge exists
  but costs eat it". The gross edge is −0.046 bp with t = −0.79; there is no edge for costs to eat.
  Halving the cost model would not change the verdict, and neither would a perfect direction label:
  at the measured accuracy ceiling of 0.801 the attenuated gross is still zero.

**What this does NOT establish.** Per §6, this design can decisively reject a large, obvious effect
and cannot establish that a small one is absent. The minimum detectable gross edge is ~0.8 bp at a
one-hour horizon in SR3; an effect materially below that is invisible here. The honest claim is
**"no detectable effect at this size and horizon"**, not "no effect".

### The lockout was NOT opened, and why

The one-shot holdout (2026-06-10 → 07-29) is **unburned**. `BT/results/dealer_ladder/LOCKOUT_USED.json`
does not exist, and that is deliberate.

In §8.7 — written before any G4 statistic was read — I committed to opening it once despite the
data-regime confound, on the grounds that declining *after* finding a reason it might fail would be
indistinguishable from avoiding a bad answer. **The protocol did not reach it.** The holdout exists
to test whether an in-sample pass generalises; the in-sample primary failed, so there is no finding
to confirm. Evaluating a holdout after an in-sample failure tests nothing, and hoping it returns a
pass that in-sample already refused is precisely the second shot the burn rule exists to forbid.

I am stating plainly that this decision was made **after** seeing the in-sample failure, because
that is when the protocol terminated. Two reasons, neither of which depends on which way the
holdout would have gone:

1. **There is nothing to confirm.** A holdout result cannot upgrade a failed primary to verdict (i)
   — the burn rule already says so.
2. **The holdout is confounded anyway** (§8.7). Thirteen of its 34 sessions fail the data-quality
   gate, so its number would not have been interpretable even if there had been something to test.

And one reason to actively preserve it: an unburned holdout is a **real asset** for a future,
better-specified study on repaired data. Spending it here to produce an uninterpretable number
about a hypothesis that already failed would destroy that for nothing.


---

## 8. Limitations, stated before the results

Every item here was established by measurement during construction, not inferred afterwards, and
each one bounds what the verdict can say. They are listed now so they cannot be mistaken for
excuses added after seeing a number.

> **Read §8.7 first.** An adversarial audit of the dataset found that the data-generating process
> changes mid-window and that **the entire lockout sits inside the changed regime**. That bounds
> the verdict more tightly than anything else here: it removes verdict (i) from the reachable set
> regardless of what the statistics say.

### 8.1 The direction label is uncertified, and curve disagreement is the same size as the signal

No truth labels exist — no desk tickets or confirmations were available — so **no accuracy number
is claimed anywhere**. The G0 pseudo-label study is the substitute: the *identical* classifier
re-run against an independent Citi Velocity intraday SOFR mid, so a flip isolates curve
disagreement rather than a difference of rule.

The scale of the problem, **measured on two months and replicated across them**. These are
preliminary runs of the same `labels.flip_study` the gate uses, reported here because they are
limitations established by measurement; the full-window version is the real G0. Both months are
complete through all three backfill phases, and the coverage report exits clean on the window.

| | January | February | **Combined** |
|---|---|---|---|
| sessions | 14 | 19 | **33** |
| sampled → compared (coverage) | 560 → 488 (87.1%) | 600 → 524 (87.3%) | **1,320 → 1,155 (87.5%)** |
| **flip rate** | 33.4% | 40.3% | **34.9%** |
| PAID share, our mid | 86.7% | 81.7% | **84.4%** |
| **PAID share, independent mid** | 60.7% | 48.7% | **55.4%** |
| mean / median mid offset (bp) | −0.469 / −0.278 | −0.499 / −0.320 | **−0.475 / −0.331** |
| share \|offset\| > 0.25bp | 63.9% | 67.2% | **67.5%** |
| mechanism agreement | 98.4% | 96.9% | **97.8%** |
| **flips the curve gap does NOT explain** | **0** | **0** | **0** |

The dataset behind the combined column was verified first: 33 sessions, 18,029 classified, 0.22%
UNKNOWN, 99.8% projected, 100% marked per unit, a single code vintage and zero anomalies.

**Overall flip rate 34.9% on 1,155 comparisons**, and three things follow.

*Most of the PAID skew is a mid artefact.* On the same 1,155 prints our mid gives **84.4%** PAID
and the independent mid gives **55.4%** — twenty-nine points of the skew is which curve you ask.
February on its own leaves a coin flip (48.7%); January leaves 60.7%, so some skew does survive an
independent mid and this is not uniformly the whole story. But the headline "dealers are
overwhelmingly paying" is mostly our curve talking.

*The gap is bigger than the edge being read, and it is a stable property of our curve.* Mean
offset −**0.475 bp**, median −**0.331**, stable to within 0.03 bp across the two months, with
**67.5% of prints showing a gap wider than a quarter of a basis point** — roughly the half-spread the direction rule is trying
to resolve. Negative means our curve sits **above** Citi's, in both months, which is the direction
that mechanically makes trades look like they printed below mid, i.e. dealer PAID.

*And the flips are entirely that gap.* Predicting a flip from `|mid offset| > |distance to mid|`
alone reproduces the observed outcome with **97.8% agreement and zero false negatives** across all
1,155 comparisons (403 flips predicted and observed, 727 agreements predicted and observed, 25
false positives). Zero false negatives in **every** `|s2m|` stratum, in each month separately and
combined: there is no flip that the curve gap fails to account for.
Consistently, the flip rate collapses to **10.4%** in the top quintile of `|spread-to-mid|`
(median 3.67 bp) — a trade that printed nearly four basis points from mid is unambiguous whichever
curve you hold. So this is not label noise to be averaged away; it is a mechanism with a closed form,
and it bites hardest exactly where the trade printed closest to mid.

Two further readings, both of which would be easy to get backwards.

`direction_confidence` is mildly **anti**-informative, and it would be a natural mistake to use it
to select a cleaner stratum. Combined: HIGH 40.0% (n=588), MEDIUM 47.9% (n=117), LOW **24.9%**
(n=450) — Spearman(tier rank, flipped) = **+0.141**, so the *higher* the stated confidence the
*more* often the independent mid disagrees. Part of that is the distance mechanism rather than the
label: MEDIUM sits closest to mid (median \|s2m\| 0.16 bp) and flips most, LOW sits furthest
(1.10 bp) and flips least, exactly as a fixed-size curve gap predicts. But the ordering does not
recover when distance is held roughly constant — inside the 0.2–0.8 bp band HIGH still flips 41.9%
against LOW's 29.8% at almost the same median distance. So the tier is not a quality filter for
this failure, however much it looks like one. And CURVE_SUSPECT prints flip **half as often** as CURVE_CLEAN ones
(**20.5%** against **40.8%**, n = 337 and 818) — not an inversion of the gate's quality, but an
artefact of what it selects on: suspect prints sit far from mid (median `|s2m|` 1.57 bp against
0.36 bp, mean 108 bp against 0.90) and a print that far out survives a half-bp disagreement. Note
the direction this cuts: the stratum the study actually trades, CURVE_CLEAN, is the one with the
**worse** flip rate.

That is the audit's first kill risk, and it is live and quantified rather than argued.

Every signed result therefore carries the `(2a − 1)` attenuation grid, and G0's flip rate is
reported as what it is: a **lower bound on disagreement-driven error, not an accuracy**. Both
curves can be wrong together, and a flip does not say which one was right.

With a 34.9% disagreement rate overall — 40.8% on the curve-clean stratum the study actually
trades — and no truth label, if each mid is right half the time where they disagree then direction
accuracy is bounded above by **79.6%** and the signed exposure retains at most **~0.59**. The
pre-registered grid {0.6, 0.7, 0.8} spans that range with its top point sitting essentially *on*
the ceiling. The grid does **not** move — it was fixed before any of this was measured, and moving
it after seeing G0 is precisely the re-specification the lockout rule exists to prevent — but its
rows now have to be read against a known ceiling rather than as three equally live scenarios.

**And the mechanism meant to absorb this uncertainty does not work.** The ladder's `expected`
weighting is `1 − 2·p_flip`, so a print believed likely to be mislabelled is carried smaller. That
is only an improvement on `unweighted` if `p_flip` tracks disagreement, and it does not. On the 750
compared units carrying one, **mean `p_flip` = 0.041 against an observed flip rate of 0.416** — off
by a factor of ten — and prints the model calls essentially certain (`p_flip` ≈ 2×10⁻¹¹) disagree
with an independent mid **36%** of the time. Rank order is weakly right (Spearman +0.129), so the
failure is in LEVEL rather than ordering, which decides what the quantity can be used for: it can
rank prints, it cannot correct them.

The practical consequence is for reading the secondary grid. `expected` applies a mean weight of
0.919 and separates prints that agree (0.927) from prints that flip (0.907) by **0.02**. It is a
near-uniform 8% haircut. So `expected` and `unweighted` are not two competing treatments of
classification uncertainty — they are the same trade scaled by ~0.92, and **neither addresses the
35–41% disagreement**. A grid row that differs only in `weighting` should be read as a duplicate,
not as a robustness check. (`p_flip` may of course be modelling a different event — the classifier's
rule misfiring rather than our mid being on the wrong side of an independent one. The defensible
claim is the narrow one: it is not calibrated against independent-mid disagreement, which is the
dominant label-error channel that can be measured at all.)

**Read the a = 0.8 row as UNREACHABLE, not as a scenario.** The measured disagreement puts accuracy
at *most* **0.796** on the curve-clean stratum, so that row sits marginally *above* what the data
admits and must not be read as an optimistic-but-plausible case. The honest centre of the grid is a = 0.6–0.7.
The a = 0.5 point — trading noise, and paying the full round trip — is drawn on the attenuation
figure as the dashed reference at −cost, because a curve that passes through zero there is
plotting the wrong quantity.

### 8.2 Structural limits of the data

| limit | consequence |
|---|---|
| **No dissemination timestamp exists** anywhere in the tape (re-probed). `visibility_timestamp` is a *modelled* Part 43 legal-delay estimate on top of `execution_timestamp`. | Arrival integrity is verified against the model, not against observed public-tape time. The all-+15min live-parity variant is the hedge. |
| The `is_capped` field feeding the `CLEARED_OFF_FACILITY_CAPPED` delay branch is a **notional**-cap marker, not a Part 43 capped-price flag. | The delay for that class cannot be cited as strictly regulatory. |
| **No trade-level data.** The only sub-bar feed is quote updates; there are no trade prints. | G2's "signed aggressive flow" is a **bar-direction** proxy, not Lee-Ready. ~39% of SR3 bars close unchanged and contribute zero signed volume, biasing the measured lead-lag toward zero — conservative, but a genuine weakening of the mechanism test. |
| **Ladder netting is a no-op.** No lineage column (`original_dissemination_identifier` / `prior_uti` / `prior_usi`) exists, so `extract_unwind_events` returns empty. | Positions decay out via the EWMA cutoff only; genuine lifecycle terminations are invisible. |
| Contracts do not print every minute — 409–493 of 639 for the SR3 front six, **99–197 for ZQ**. | Horizons are evaluated against the last KNOWN price on a forward-filled grid under a staleness cap. 60-minute coverage is 90% (SR3) and 85% (ZQ); staleness is retained and reportable rather than hidden. |
| Both independent mids are **SOFR** curves. | FED_FUNDS prints have **no** independent cross-check at all. The flip study covers the SOFR universe only. |
| The Citi source runs Mon 00:01 → Fri 11:59 and its reader **silently returns its last snapshot** past that. | Staleness-checked; a stale curve counts as no coverage. Friday afternoons are largely uncovered. |
| No historical depth or top-of-book data. | G5's capacity is a traded-**volume** sensitivity, labelled as such in its own output. It is an upper bound on what depth would allow, never a capacity claim. |

### 8.3 The `expected` weighting is close to inert

`disp_jns` is NULL on 100% of `arbs_stir_tick_size_v1` because ticks-only calibration feeds
`s2m_bps = NaN`. So `sigma_mid` always collapses to its fallback `futures_tick_bps / 2` (0.125 bp
SR3, 0.25 bp FF), and a print a normal half-spread from mid scores `p_flip ≈ 0.023`, weight
≈ 0.95. The `expected`-vs-`unweighted` arm of the secondary grid therefore measures the
**calibration**, not the signal, and must not be presented as a robustness result.

**Since confirmed by measurement, and it is worse than inert.** That paragraph was an inference
from the code path; G0 now measures the consequence directly on 750 compared units. Mean `p_flip`
is **0.041** — the same order as the 0.023 predicted above — against an observed flip rate of
**0.416**. Prints the model calls essentially certain (`p_flip` ≈ 2×10⁻¹¹) disagree with an
independent mid **36%** of the time. Rank order is weakly right (Spearman **+0.129**), so the
failure is in LEVEL rather than ordering, and that distinction decides what the quantity can be
used for: it can rank prints, it cannot correct them.

The resulting weight separates prints that agree (0.927) from prints that flip (0.907) by **0.02**
against a mean of 0.919. So `expected` and `unweighted` are not two treatments of classification
uncertainty — they are the same trade scaled by ~0.92, and **a grid row differing only in
`weighting` is a duplicate, not a robustness check**. (`p_flip` may of course be modelling a
different event, the classifier's rule misfiring rather than our mid being on the wrong side of an
independent one. The defensible claim is the narrow one: it is not calibrated against
independent-mid disagreement, which is the dominant label-error channel that can be measured.)

### 8.4 The pre-registered rule is 80% one-sided

The spec triggers on `|z| >= 1` but signs the position from the ladder **level**, because the
hypothesis is about the level: a dealer long futures-equivalent must sell, so a positive ladder
predicts a rate rise. With 84% of prints PAID and PAID meaning *negative* `delta_dv01`, that has a
consequence worth measuring rather than assuming.

Measured on the signed universe over Jan+Feb — 33 sessions, 3,168 decision minutes, 12 SR3
buckets, 32,256 finite cells:

- **94.6%** of all (minute, bucket) cells carry a **negative** ladder level;
- **25.0%** of cells trigger at `|z| >= 1.0`;
- **80.2% of triggers have level < 0**, so four trades in five take the short-rates side;
- `sign(level) != sign(z)` on **20.0%** of triggers, and entirely one-directional —
  `level < 0, z > 0` occurs 1,610 times and `level > 0, z < 0` occurs **zero** times, because a
  positive level is rare enough to always sit far above the (negative) trailing mean.

The imbalance rises steeply with maturity: SFRH26 54.1%, SFRM26 66.5%, SFRU26 82.2%, SFRZ27 93.2%,
**SFRZ28 97.3%**. The front of the strip is near-balanced; the back is a constant short-rates bet.

**What this does to the reading of G4.** A rule that is four-fifths one-sided earns much of its
return from the window's rate drift, and neither the mean nor the t distinguishes that from a
forecast. Day-blocked clustering handles the dependence correctly — the effective sample is
sessions, not trades — but it does not answer the attribution question. So every primary result is
reported with `share_long` beside it and against a **constant-position benchmark** that re-prices
the identical entries, exits and costs at +1 and −1. **If the rule does not beat the better
constant, the ladder is contributing nothing beyond direction**, whatever its t.

None of this changes the pre-registration: level-signing is what the hypothesis states, and the
threshold and horizon stay locked. The benchmark is a diagnostic set beside the test, and it
rescues nothing — if G4 passes only because rates fell over the window, the benchmark says so.


### 8.5 Scope reductions taken deliberately

- **`SERFF_BASIS` is not projected.** Measured at 13.81 s of the 14.6 s per-snapshot risk-model
  cost — 94% — because it is the one space still needing ~60 vendor pricer fetches per snapshot.
  Including it meant 74–109 min/day against 4–8, i.e. an infeasible backfill. The plan designates
  it conditioning-only and bars it from being a test target, and `controls.basis_bp` (curve-implied
  contract rate minus futures market rate, per contract, on the **decision** grid) is a better
  conditioner than a basis DV01 split at scattered print times.
- **The primary signal space is `FUTURES`, not `MEETING`** as the plan's Task 10 draft named it.
  The later bench ordering makes SR3-in-`FUTURES` the primary bench, and using it aligns signal and
  target contract-by-contract instead of inventing a meeting→contract mapping. `MEETING` remains
  in the secondary grid, and is barred from ever being a test *target* — it has no traded
  instrument, so such a test would be circular by construction.

### 8.6 Power

Independent observations are set by the signal's integration window, not the number of minute
bars. More precisely: the inference is **clustered by session** — `cluster_mean_t` and
`day_blocked_ci` both use the day-cluster count — so that count is the effective sample size.
Decisions within a session sharpen the daily mean; they do not add independent observations.

Counted from the trading calendar rather than estimated:

| segment | sessions | mean/sd needed for **t ≥ 3** | for t ≥ 2 | 80%-power MDE |
|---|---|---|---|---|
| in-sample (2026-01-12 → 06-09) | **104** | 0.294 | 0.196 | 0.275 |
| **lockout** (2026-06-10 → 07-29) | **34** | **0.514** | 0.343 | 0.480 |
| whole window | 138 | 0.255 | 0.170 | 0.238 |

All in units of a **daily** standard deviation. In basis points, if the daily mean net result has a
spread of about 1 bp, passing `t ≥ 3` in-sample needs a mean of **+0.29 bp per trade after costs** —
on top of a round trip that is 0.25 bp for a near contract and 0.50 bp for a deferred one. The
gross edge would have to be roughly 0.8 bp at a one-hour horizon in SR3.

**The lockout is much weaker than the in-sample segment, and this has to be said before it is
opened.** Thirty-four sessions give a minimum detectable effect **1.75× larger** than the 104
in-sample ones. So a lockout failure is consistent with *two* different worlds: no effect, or a real
but modest effect the holdout cannot resolve. The burn rule still applies — the configuration is
burned either way, and no re-specification follows — but the **interpretation** of that failure must
not be overstated into "the effect is absent". It licenses verdict (ii) or (iii), never a positive
claim about absence.

Conversely, a lockout *pass* at this cluster count is meaningful precisely because the bar is high.

**This study can decisively reject a large, obvious effect. It cannot establish that a small one is
durable, causal, or capacity-bearing**, and no claim of that kind will be made from it.

### 8.7 The data regime changes mid-window, and the lockout sits entirely inside the change

Found by an adversarial audit of the dataset (six agents, independent attack surfaces), then
verified independently with my own queries rather than taken on the auditors' word.

**The classification mid is intermittently displaced from 2026-05-07.** For 2Y on-market
OUTRIGHTs — the most liquid, best-priced bucket in the book — the median **signed** spread-to-mid:

| month | n | median signed | median abs | curve-suspect |
|---|---|---|---|---|
| 2026-01 | 801 | −0.322 bp | 0.357 | 16.5% |
| 2026-02 | 1,303 | −0.350 | 0.388 | 17.7% |
| 2026-03 | 2,050 | −0.321 | 0.363 | 14.0% |
| 2026-04 | 1,301 | −0.357 | 0.388 | 12.6% |
| **2026-05** | 1,301 | **−5.857** | 5.926 | **79.7%** |
| **2026-06** | 1,388 | **−8.153** | 8.587 | **79.5%** |
| 2026-07 | 1,562 | −0.719 | 0.766 | 43.4% |

The **signed** median is the diagnostic. A genuine widening of dealer spreads moves the *absolute*
value and leaves the signed median near zero; a one-sided −6 to −8 bp median means the mid itself
has moved. A 6–8 bp median dealer spread in 2Y SOFR is not a market state. Daily resolution shows
the fault is **intermittent, not a step**: 05-07 −1.01, 05-08 −4.61, 05-11 −0.22, 05-12 +0.04,
05-14 −5.25 — which is why no monthly average or single break test would have caught it.

**The universe filter does not rescue this; it converts it into a selection effect.** Curve-suspect
prints are excluded by default, so most displaced prints never enter the study. But the exclusion
rate is not constant:

| | Jan–Apr | May–Jun |
|---|---|---|
| curve-suspect share of all units | 20–31% | 48–51% |
| signed share of all units | 40.3% | **27.1%** |
| signed units per session | 225 | **167 (−26%)** |

So the surviving sample in the back half is *selected on agreement with a curve that is
intermittently wrong*, and the selection rate tracks the calendar.

**Why this is the binding limitation.** The pre-registered lockout is **2026-06-10 → 2026-07-29**,
and **all 34 of its sessions sit inside the degraded regime**, while the in-sample segment is 74%
clean-regime. Three further audit findings also land inside the holdout:

- **2026-07-21**: tape package grouping collapses — maximum legs per package falls from 109/55/30 to
  3, and zero eligible legs sit in a >4-leg package. Multi-leg structures are torn into standalone
  OUTRIGHTs, each then classified from its own spread-to-mid, which is exactly what the package
  logic exists to prevent. This covers the last **7 lockout sessions (21% of the holdout)**.
- **2026-07-24**: the entire US cash session is missing from the source tape. Hours 07:00–19:59 ET
  contain zero legs; 294 units survive against a 1,018–1,125 neighbourhood. The day passes every
  presence check and reads as complete.
- **2026-07-29**: 8 package units are orphaned because the tape re-grouped after classification, so
  the ladder holds a grouping that can no longer be tied to any tape row.

**Consequence for the verdict, decided before any G4 statistic was read.** A lockout failure here is
**uninterpretable**: it cannot be distinguished from "the holdout is drawn from a different
data-generating process". The burn rule does not contemplate a confounded holdout.

Therefore:

1. The primary runs on the **full window, unchanged** — it is the locked specification.
2. This limitation was written down **before the lockout was opened**.
3. The lockout **is still opened, once, as pre-registered**. Declining after finding a reason it
   might fail would be indistinguishable from avoiding a bad answer.
4. A **data-regime split at 2026-05-07** is a mandatory reported dimension, and the clean-regime
   subset (2026-01-12 → 2026-05-06, ~77 sessions) is reported beside the full-window primary.
5. **Verdict (i) is unreachable from this dataset.** A holdout that is not drawn from the same
   regime cannot certify out-of-sample generalisation, however the numbers land. The reachable
   verdicts are (ii) and (iii).

**Honest accounting of the audit itself.** 17 of its 25 agents died on a session limit, so five of
six surfaces never had their findings adversarially refuted and the completeness critic never ran.
What is reported above are auditor claims **I verified personally**, not claims that survived
independent refutation. The one finding that did complete verification — that `VINTAGE_SOURCES`
omits 13 value-determining modules — was **confirmed on the facts and downgraded on severity**, its
verifier establishing that only a single logging-only commit touched those modules inside the
stamped window and that no session straddles it, so no reported number is numerically affected. It
remains a provenance-detection gap, recorded in §8.8.

### 8.8 `VINTAGE_SOURCES` does not cover every value-determining module

The one audit finding that completed independent verification. **Confirmed on the facts and
downgraded on severity** by its own verifier, and recorded here rather than quietly dropped.

`code_vintage` is a hash over the contents of the modules in
`SDRUtils/stir_flow/vintage.py:VINTAGE_SOURCES`, so that the stamp changes exactly when the
pipeline changes. The list is **incomplete**: 13 further modules can influence what gets
written and are not hashed, so an edit to one of them would leave the vintage unchanged and a
mixed-vintage dataset would read as uniform.

**No number in this report is affected, and that was established rather than assumed.** The
verifier checked every commit touching those modules inside the stamped window and found a
single one, logging-only, with no session straddling it. The entire dataset carries one vintage
(`468474ca6f84`, confirmed by the G0 census: *1 code vintage*).

It is left unfixed **deliberately**. Adding modules to `VINTAGE_SOURCES` changes the hash, which
would re-stamp a concluded six-month dataset as stale and make every row look like it needed
re-running. The correct moment to widen the list is the next backfill, not after the study that
depends on the current stamp. Recorded as an owner ticket, not silently deferred.

Note that `BT/dealer_ladder/session_quality.py` correctly does **not** belong in this list.
`VINTAGE_SOURCES` covers the modules that determine what is *written* to the direction and
ladder tables; the session-quality gate filters at read time and changes no stored row.

### 8.9 Open data defects that need fixing OUTSIDE this study

Three defects survived verification. None is caused by this study's code, all three are live in
production, and **the first is a production bug in the tape that has nothing to do with this
research and should be fixed regardless of what happens to the dealer-ladder hypothesis.**

**1. PTP package grouping has been silently dead since 2026-07-21.** `ptp_group_id` is NULL for
every tape leg from that date — 1,485/1,620/1,800 groups a day through 07-20, then
0, 75, 0, 0, 0, 0, 0. The **source fields are intact throughout**: `package_transaction_price` is
populated on 1,550–2,006 legs a day after the break, *more* than the 1,056–1,320 before it. So the
CFTC feed is fine and the grouper is not seeing it.

The consequence is that large multi-leg structures are torn into standalone prints. Maximum legs
per package falls from 90/73/109/55/28/30 to a flat **3**, packages with >4 legs falls from 36–64 a
day to **0**, and `package_id` values change shape from `PTP_4290830669000000301` (30 legs) to
`FLY_101_4315159479000000701` (3 legs) — i.e. only the structure detectors are still firing and
the PTP pre-grouper contributes nothing.

*Most likely mechanism, stated as a hypothesis and not as a finding.* `group_by_ptp` gates every
candidate on

```python
candidate_mask = pkg_ind_bool & (ptp_usable | pts_usable) & ts_all.notna()
if not candidate_mask.any():   # -> everything returned ungrouped
```

`ptp_usable` is confirmed true for thousands of rows a day, so the failure is `pkg_ind_bool` or
`ts_all`. Both are reachable from the same change: `DETECTION_CACHE_VERSION` is
`"ptp16-exec-vs-event-timestamps"`, and `169cb1a9 feat(sdr): Phase 1 — read Event timestamp +
de-conflate execution/event` landed 2026-07-17, four days before the break — consistent with a
cache-version bump that only takes effect on newly ingested days. Note also that the column
normaliser at `usd_swaps.py:1971` lowercases *before* applying its CamelCase split regex, so the
regex can never match and the "snake_case" conversion only replaces spaces; a source column that
changed from `Package Indicator` to `PackageIndicator` would silently stop mapping.

**The decisive next step** is to run `group_by_ptp` on a raw 07-21 frame and print which of the
three conditions is empty. That is a ten-minute check for whoever owns the tape, and this study
should not be the thing that fixes it.

**2. 2026-07-24 is missing its entire US cash session, at the tape level.** 799 legs, of which
**zero** fall in ET hours 08–16; the feed runs 20:02 (prior day) to 06:57 and stops. Neighbours
carry 4,097–4,586 legs with 3,162–3,587 in the cash session. This is **not** recoverable by
re-running classification — the rows are not in `arbs_usd_swap_tape_legs_v2` — so it needs an SDR
re-ingest, which is outside this work's write scope.

**3. The classification mid is intermittently displaced on 12 sessions** (§8.7). Unlike 1 and 2
this one is *inside* the study's own curve stack, but diagnosing it means going into the curve
build rather than the ladder, and it is scoped as its own investigation.

**A gap in my own coverage tool, worth recording.** `dealer_ladder_coverage.py --strict` passed
2026-07-24. It counts rows, checks vintages and joins marks — it never asked whether a session is
*shaped* like a trading day, so a day present but missing its cash session reads as complete. The
generalisation is now `BT/dealer_ladder/session_quality.py`, which found exactly two shape
anomalies in 138 sessions and correctly exempted the third candidate (Good Friday) as a scheduled
early close.

---

## 9. Completeness pass

Which modality, stratum or diagnostic did **not** run, and why. Generated by
`scripts/dealer_ladder_completeness.py` rather than written from memory: the inventory comes from
the declarations in code — the 288-variant grid cross-product, the control lists, the conditioning
splits, the six pre-specified placebos, the audit battery, and every protocol stage paired with the
artifact that proves it ran — so a gap nobody thought of still appears here. A reason is only
accepted from `g4_skipped_variants.csv`, written by the runner at the moment it skipped something;
anything else is flagged **UNEXPLAINED** and needs a reason written by hand beneath the table.

<!-- BEGIN GENERATED COMPLETENESS -->

<!-- GENERATED by scripts/dealer_ladder_completeness.py. The inventory is derived from the DECLARATIONS in code, not from recollection, so a gap nobody thought of still appears. -->

- **47/50 protocol stages produced their artifacts.**
- **196 declared items did not run**, of which **3 have no recorded reason**.

### Not run, and NOT explained

A reason is only accepted from `g4_skipped_variants.csv`, written by the runner at the moment it skipped something. Everything here needs a reason written into the findings doc by hand, or the omission is not accounted for.

| kind   | item                                    | detail      |
|:-------|:----------------------------------------|:------------|
| stage  | G3b horse race vs independent basis, ZQ | no artifact |
| stage  | G4 directional benchmark, LOCKOUT       | no artifact |
| stage  | One-shot lockout                        | no artifact |

### Not run, with a recorded reason

| reason                                                |   items |
|:------------------------------------------------------|--------:|
| no shared bucket keys between signal and target space |      96 |
| panel not built for this space                        |       1 |
| signal space MEETING not built for this window        |      96 |

<details><summary>every item</summary>

| kind               | item                                       | reason                                                |
|:-------------------|:-------------------------------------------|:------------------------------------------------------|
| grid variant       | FED_FUNDS->FUTURES|hl30|expected|h5        | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|expected|h15       | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|expected|h30       | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|expected|h60       | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|expected|h240      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|expected|h1440     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|unweighted|h5      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|unweighted|h15     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|unweighted|h30     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|unweighted|h60     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|unweighted|h240    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl30|unweighted|h1440   | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|expected|h5        | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|expected|h15       | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|expected|h30       | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|expected|h60       | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|expected|h240      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|expected|h1440     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|unweighted|h5      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|unweighted|h15     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|unweighted|h30     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|unweighted|h60     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|unweighted|h240    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl90|unweighted|h1440   | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|expected|h5       | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|expected|h15      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|expected|h30      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|expected|h60      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|expected|h240     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|expected|h1440    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|unweighted|h5     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|unweighted|h15    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|unweighted|h30    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|unweighted|h60    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|unweighted|h240   | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl240|unweighted|h1440  | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|expected|h5      | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|expected|h15     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|expected|h30     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|expected|h60     | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|expected|h240    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|expected|h1440   | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|unweighted|h5    | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|unweighted|h15   | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|unweighted|h30   | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|unweighted|h60   | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|unweighted|h240  | no shared bucket keys between signal and target space |
| grid variant       | FED_FUNDS->FUTURES|hl1440|unweighted|h1440 | no shared bucket keys between signal and target space |
| grid variant       | MEETING->FUTURES|hl30|expected|h5          | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|expected|h15         | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|expected|h30         | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|expected|h60         | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|expected|h240        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|expected|h1440       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|unweighted|h5        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|unweighted|h15       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|unweighted|h30       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|unweighted|h60       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|unweighted|h240      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl30|unweighted|h1440     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|expected|h5          | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|expected|h15         | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|expected|h30         | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|expected|h60         | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|expected|h240        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|expected|h1440       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|unweighted|h5        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|unweighted|h15       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|unweighted|h30       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|unweighted|h60       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|unweighted|h240      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl90|unweighted|h1440     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|expected|h5         | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|expected|h15        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|expected|h30        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|expected|h60        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|expected|h240       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|expected|h1440      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|unweighted|h5       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|unweighted|h15      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|unweighted|h30      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|unweighted|h60      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|unweighted|h240     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl240|unweighted|h1440    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|expected|h5        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|expected|h15       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|expected|h30       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|expected|h60       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|expected|h240      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|expected|h1440     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|unweighted|h5      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|unweighted|h15     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|unweighted|h30     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|unweighted|h60     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|unweighted|h240    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FUTURES|hl1440|unweighted|h1440   | signal space MEETING not built for this window        |
| grid variant       | FUTURES->FED_FUNDS|hl30|expected|h5        | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|expected|h15       | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|expected|h30       | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|expected|h60       | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|expected|h240      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|expected|h1440     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|unweighted|h5      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|unweighted|h15     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|unweighted|h30     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|unweighted|h60     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|unweighted|h240    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl30|unweighted|h1440   | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|expected|h5        | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|expected|h15       | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|expected|h30       | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|expected|h60       | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|expected|h240      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|expected|h1440     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|unweighted|h5      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|unweighted|h15     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|unweighted|h30     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|unweighted|h60     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|unweighted|h240    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl90|unweighted|h1440   | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|expected|h5       | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|expected|h15      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|expected|h30      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|expected|h60      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|expected|h240     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|expected|h1440    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|unweighted|h5     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|unweighted|h15    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|unweighted|h30    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|unweighted|h60    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|unweighted|h240   | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl240|unweighted|h1440  | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|expected|h5      | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|expected|h15     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|expected|h30     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|expected|h60     | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|expected|h240    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|expected|h1440   | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|unweighted|h5    | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|unweighted|h15   | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|unweighted|h30   | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|unweighted|h60   | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|unweighted|h240  | no shared bucket keys between signal and target space |
| grid variant       | FUTURES->FED_FUNDS|hl1440|unweighted|h1440 | no shared bucket keys between signal and target space |
| grid variant       | MEETING->FED_FUNDS|hl30|expected|h5        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|expected|h15       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|expected|h30       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|expected|h60       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|expected|h240      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|expected|h1440     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|unweighted|h5      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|unweighted|h15     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|unweighted|h30     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|unweighted|h60     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|unweighted|h240    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl30|unweighted|h1440   | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|expected|h5        | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|expected|h15       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|expected|h30       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|expected|h60       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|expected|h240      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|expected|h1440     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|unweighted|h5      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|unweighted|h15     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|unweighted|h30     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|unweighted|h60     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|unweighted|h240    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl90|unweighted|h1440   | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|expected|h5       | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|expected|h15      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|expected|h30      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|expected|h60      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|expected|h240     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|expected|h1440    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|unweighted|h5     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|unweighted|h15    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|unweighted|h30    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|unweighted|h60    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|unweighted|h240   | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl240|unweighted|h1440  | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|expected|h5      | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|expected|h15     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|expected|h30     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|expected|h60     | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|expected|h240    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|expected|h1440   | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|unweighted|h5    | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|unweighted|h15   | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|unweighted|h30   | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|unweighted|h60   | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|unweighted|h240  | signal space MEETING not built for this window        |
| grid variant       | MEETING->FED_FUNDS|hl1440|unweighted|h1440 | signal space MEETING not built for this window        |
| conditioning split | sofr_effr_bp                               | panel not built for this space                        |

</details>

### Ran

| kind   | item                                             | detail        |
|:-------|:-------------------------------------------------|:--------------|
| stage  | G0 labels and provenance                         | 2/2 artifacts |
| stage  | G0 independent-mid flip study                    | 2/2 artifacts |
| stage  | G0 flip by confidence tier                       | 1/1 artifacts |
| stage  | G0 flip by curve bucket                          | 1/1 artifacts |
| stage  | G0 flip by trade type                            | 1/1 artifacts |
| stage  | G0 flip by execution hour                        | 1/1 artifacts |
| stage  | G0 PAID share by stratum                         | 1/1 artifacts |
| stage  | G0 direction-skew adjudication                   | 1/1 artifacts |
| stage  | G0 direction skew by hour                        | 1/1 artifacts |
| stage  | G0 flip mechanism (curve gap vs distance to mid) | 1/1 artifacts |
| stage  | G0 p_flip calibration                            | 1/1 artifacts |
| stage  | G0 implied accuracy bounds                       | 1/1 artifacts |
| stage  | G1 arrival integrity                             | 1/1 artifacts |
| stage  | G2 lead-lag, SR3                                 | 1/1 artifacts |
| stage  | G2 lead-lag, ZQ cross-check                      | 1/1 artifacts |
| stage  | G2 signed peak correlation, SR3                  | 1/1 artifacts |
| stage  | G2 signed peak correlation, ZQ                   | 1/1 artifacts |
| stage  | G2 SR3-vs-ZQ cross-check comparison              | 1/1 artifacts |
| stage  | G3 horse race, ZQ cross-check                    | 1/1 artifacts |
| stage  | G2 flow-response event study, SR3                | 1/1 artifacts |
| stage  | G2 flow-response event study, ZQ                 | 1/1 artifacts |
| stage  | G2 lead-lag by lag, SR3                          | 1/1 artifacts |
| stage  | G2 lead-lag by lag, ZQ                           | 1/1 artifacts |
| stage  | G2 flow-response events, SR3                     | 1/1 artifacts |
| stage  | G2 flow-response events, ZQ                      | 1/1 artifacts |
| stage  | G3 horse race vs our basis                       | 1/1 artifacts |
| stage  | G3b horse race vs independent basis              | 1/1 artifacts |
| stage  | G3 point-in-time verification                    | 1/1 artifacts |
| stage  | G3 leave-one-bucket-out                          | 1/1 artifacts |
| stage  | G3 residualised signal                           | 1/1 artifacts |
| stage  | G3 point-in-time verification, ZQ                | 1/1 artifacts |
| stage  | G3 leave-one-bucket-out, ZQ                      | 1/1 artifacts |
| stage  | G3 residualised signal, ZQ                       | 1/1 artifacts |
| stage  | G4 primary (in-sample)                           | 1/1 artifacts |
| stage  | G4 directional benchmark (constant position)     | 1/1 artifacts |
| stage  | G4 staleness sensitivity                         | 1/1 artifacts |
| stage  | G4 secondary grid                                | 1/1 artifacts |
| stage  | G4 variants that could not run                   | 1/1 artifacts |
| stage  | G4 Romano-Wolf family-wise                       | 1/1 artifacts |
| stage  | G4 best-vs-median anti-selection                 | 1/1 artifacts |
| stage  | G4 placebos                                      | 1/1 artifacts |
| stage  | G4 label-free cell                               | 1/1 artifacts |
| stage  | G4 conditioning splits                           | 1/1 artifacts |
| stage  | G4 conditioners that could not be split          | 1/1 artifacts |
| stage  | G5 economics                                     | 1/1 artifacts |
| stage  | G5 capacity                                      | 1/1 artifacts |
| stage  | Trial ledger                                     | 1/1 artifacts |

_Audited against `BT/results/dealer_ladder`._

<!-- END GENERATED COMPLETENESS -->

### 9b. The three unexplained omissions, accounted for by hand

The generated table above flags anything absent without a machine-recorded reason. Three
remain, and the section's own rule is that an omission without a written reason is not
accounted for. All three are here.

**1. G3b horse race vs independent basis, ZQ — impossible by construction, not skipped.**
G3b re-runs the horse race against a basis *our own curve did not produce*. Both independent
sources available to this repo (Citi Velocity, and the ERIS live curve) are USD **SOFR** curves,
so there is an independent SR3 basis to build and **no independent ZQ/Fed-Funds basis exists at
all**. The SR3 arm ran with 86.8% coverage and is reported. This is a permanent property of the
data surface, not a stage that failed, and it is why the G3-ZQ headline reads
`vs independent basis=nan` rather than a number.

The cost is real and worth stating plainly: **the ZQ result rests on our own controls only.**
Its coefficient runs opposite to the hypothesis (−0.01176), so the conclusion does not turn on
this, but a ZQ result that *had* survived our controls could not have been checked against an
independent basis and would have carried much weaker weight than the equivalent SR3 claim.

**2 and 3. G4 directional benchmark (LOCKOUT) and the one-shot lockout — deliberately not
opened.** See §7b. The protocol terminates at a failed in-sample G4; a holdout confirms an
in-sample pass and there was none. `LOCKOUT_USED.json` is absent by design, and its absence is
the evidence that the holdout is unburned and still spendable by a future study.

These two rows will keep appearing in every completeness run over this results directory. That
is correct behaviour and should not be "fixed": a tool that stopped reporting the unopened
holdout would make an unspent holdout indistinguishable from a spent one.

**Two defects in the completeness checker itself, found by reading its own output.** It
originally reported five unexplained items; two of those were its own bugs.

- It writes skipped-conditioner reasons to `g4_conditioning_skipped.csv` and read reasons only
  from `g4_skipped_variants.csv`, so `sofr_effr_bp` was reported UNEXPLAINED while the reason —
  *"panel not built for this space"* — sat in a file the checker had itself written.
- `DECLARED_AUDITS` listed `not_yet_visible_poison`, which is not an audit.
  `poison_not_yet_visible` is the **helper** that corrupts prints to build the poisoned input
  for `audit_future_poison`; it emits no verdict. The check ran, under the name it actually
  uses, exercised on 343,116 future prints. The checker was reporting a permanently missing
  audit for a test that runs every time.

Both are fixed. They are the seventh and eighth instances in this engagement of a **checking
tool that was itself the defect**, and like the other six they were found by running the check
against an input whose answer was already known.

---

## 10. Every artifact, verbatim

Generated by `scripts/render_findings_tables.py` from the CSVs the gates wrote, with a source
filename under each table. Nothing here is transcribed: a hand-copied number cannot be checked
against the run that produced it, and a transcription slip is indistinguishable from a result. A
gate that produced no artifact says so loudly, because an absent table must never read as a passing
gate.

<!-- BEGIN GENERATED TABLES -->

<!-- GENERATED by scripts/render_findings_tables.py — do not edit by hand. Re-run it instead, so every number here traces to the artifact that produced it. -->

### Every gate verdict

| gate                  |   pass | headline                                                                                                                                                                                                        |
|:----------------------|-------:|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| G0                    |    nan | signed universe 28704 units; 1 code vintage(s); flip rate 0.398                                                                                                                                                 |
| G1                    |      1 | all arrival audits pass, poison audit exercised on 343116 future prints                                                                                                                                         |
| G2                    |      0 | LLS mean=-4.769 t=-2.45*, mean peak rho=-0.035 (hedging needs < 0), 104 sessions — no timing lead; forced-hedge channel UNSUPPORTED, so any price result must be relabelled flow/basis continuation             |
| G3                    |      0 | signal t alone=0.14, vs our controls=0.50 (coef +0.01323), vs independent basis=0.84 — effect does not survive; relabel as basis/RV, not a dealer-inventory mechanism                                           |
| G2                    |      0 | LLS mean=-19.88 t=-1.78., mean peak rho=-0.005 (hedging needs < 0), 104 sessions — no timing lead; forced-hedge channel UNSUPPORTED, so any price result must be relabelled flow/basis continuation             |
| G3                    |      0 | signal t alone=-1.47, vs our controls=-1.19 (coef -0.01176), vs independent basis=nan — coefficient is -0.01176, the OPPOSITE direction to the pre-registered hypothesis: this is a negative result, not a pass |
| G2-cross-check        |    nan | leads NEITHER -> no mechanism evidence from the ordering test                                                                                                                                                   |
| G4-primary(in-sample) |      0 | net -0.5458bp/trade, t=-9.44***, n=1639 trades over 99 sessions, 28% long-rates (pass needs mean>0 and t>=3.0)                                                                                                  |
| label-free            |    nan | unsigned intensity: net -0.6402bp, t=-9.03***, n=1838                                                                                                                                                           |
| conditioning          |    nan | 6/6 conditioners sign-consistent across terciles (1 of 7 could not be split)                                                                                                                                    |
| G5                    |      0 | gross -0.0458 - cost 0.5000 = net -0.5458bp/trade; at accuracy a=0.60 -> (2a-1)*gross - cost = -0.5092bp                                                                                                        |

_Source: `verdicts.csv` (11 rows)._

### G0 — the signed universe

|   n_units_all |   n_units_signed |   paid_share_signed |   p_flip_coverage_signed |   n_code_vintages |
|--------------:|-----------------:|--------------------:|-------------------------:|------------------:|
|         84201 |            28704 |               0.771 |                    0.926 |                 1 |

_Source: `g0_universe_summary.csv` (1 rows)._

### G0 — exclusion ladder

| step                              |   units |   removed |
|:----------------------------------|--------:|----------:|
| start: all projected prints       |   84201 |         0 |
| direction in PAID/RECEIVED        |   84201 |         0 |
| classification method in universe |   53543 |     30658 |
| TICK_RULE excluded                |   53543 |         0 |
| curve-clean only                  |   32719 |     20824 |
| whitelisted D2C venue only        |   28704 |      4015 |
| single code vintage               |   28704 |         0 |

_Source: `g0_exclusion_ladder.csv` (7 rows)._

### G0 — PAID share by stratum (our labels)

| venue_bucket    | curve_bucket   | market_bucket   |     n |   paid_share |   p_flip_share |
|:----------------|:---------------|:----------------|------:|-------------:|---------------:|
| D2C_WHITELISTED | CURVE_CLEAN    | OFF_MARKET      |  8449 |        0.749 |          1     |
| D2C_WHITELISTED | CURVE_CLEAN    | ON_MARKET       | 38497 |        0.695 |          0.69  |
| D2C_WHITELISTED | CURVE_SUSPECT  | OFF_MARKET      | 10187 |        0.65  |          0     |
| D2C_WHITELISTED | CURVE_SUSPECT  | ON_MARKET       | 18166 |        0.792 |          0     |
| VENUE_UNKNOWN   | CURVE_CLEAN    | OFF_MARKET      |   325 |        0.72  |          1     |
| VENUE_UNKNOWN   | CURVE_CLEAN    | ON_MARKET       |  5398 |        0.695 |          0.695 |
| VENUE_UNKNOWN   | CURVE_SUSPECT  | OFF_MARKET      |   521 |        0.559 |          0     |
| VENUE_UNKNOWN   | CURVE_SUSPECT  | ON_MARKET       |  2658 |        0.713 |          0     |

_Source: `g0_skew_by_stratum.csv` (8 rows)._

### G0 — our mid vs the independent mid (bp)

| stratum       |    n |   mean_our_s2m_bps |   mean_ind_s2m_bps |   mean_offset_bps |   median_offset_bps |   share_offset_gt_quarter_bp |
|:--------------|-----:|-------------------:|-------------------:|------------------:|--------------------:|-----------------------------:|
| ALL           | 4723 |             27.602 |             29.552 |            -1.95  |              -0.356 |                        0.7   |
| CURVE_CLEAN   | 2982 |             -0.759 |             -0.156 |            -0.603 |              -0.262 |                        0.621 |
| CURVE_SUSPECT | 1741 |             76.179 |             80.436 |            -4.257 |              -1.128 |                        0.835 |

_Source: `g0_mid_offset_bps.csv` (3 rows)._

### G0 — flip rate by our confidence tier

| our_confidence   |   n_units |   n_compared |   flip_rate |   n_no_coverage |
|:-----------------|----------:|-------------:|------------:|----------------:|
| HIGH             |      2398 |         2049 |       0.386 |             349 |
| LOW              |      2547 |         2191 |       0.334 |             356 |
| MEDIUM           |       575 |          483 |       0.451 |              92 |

_Source: `g0_flip_by_confidence.csv` (3 rows)._

### G0 — flip rate by curve bucket

| curve_bucket   |   n_units |   n_compared |   flip_rate |   n_no_coverage |
|:---------------|----------:|-------------:|------------:|----------------:|
| CURVE_CLEAN    |      3506 |         2982 |       0.398 |             524 |
| CURVE_SUSPECT  |      2014 |         1741 |       0.319 |             273 |

_Source: `g0_flip_by_curve_bucket.csv` (2 rows)._

### G0 — flip rate by trade type

| trade_type   |   n_units |   n_compared |   flip_rate |   n_no_coverage |
|:-------------|----------:|-------------:|------------:|----------------:|
| CURVE        |       277 |          227 |       0.379 |              50 |
| FLY          |        54 |           38 |       0.342 |              16 |
| OUTRIGHT     |      5189 |         4458 |       0.368 |             731 |

_Source: `g0_flip_by_trade_type.csv` (3 rows)._

### G0 — flip rate by execution hour (ET)

|   hour |   n_units |   n_compared |   flip_rate |   n_no_coverage |
|-------:|----------:|-------------:|------------:|----------------:|
|      0 |       167 |            0 |             |             167 |
|      1 |       187 |          181 |       0.448 |               6 |
|      2 |       233 |          228 |       0.417 |               5 |
|      3 |       240 |          234 |       0.372 |               6 |
|      4 |       239 |          232 |       0.418 |               7 |
|      5 |       222 |          215 |       0.447 |               7 |
|      6 |       211 |          208 |       0.447 |               3 |
|      7 |       256 |          251 |       0.402 |               5 |
|      8 |       346 |          337 |       0.374 |               9 |
|      9 |       383 |          373 |       0.402 |              10 |
|     10 |       373 |          366 |       0.328 |               7 |
|     11 |       364 |          357 |       0.249 |               7 |
|     12 |       334 |          273 |       0.311 |              61 |
|     13 |       284 |          229 |       0.306 |              55 |
|     14 |       287 |          224 |       0.339 |              63 |
|     15 |       271 |          222 |       0.365 |              49 |
|     16 |       231 |          194 |       0.351 |              37 |
|     17 |        61 |           51 |       0.137 |              10 |
|     18 |        10 |           10 |       0.3   |               0 |
|     19 |        50 |           44 |       0.295 |               6 |
|     20 |       180 |          147 |       0.442 |              33 |
|     21 |       201 |          164 |       0.372 |              37 |
|     22 |       215 |          168 |       0.423 |              47 |
|     23 |       175 |           15 |       0.4   |             160 |

_Source: `g0_flip_by_hour.csv` (24 rows)._

### G0 — PAID/RECEIVED skew, ours vs independent

| index   |    n |   our_paid_share |   ind_paid_share |   flip_rate |
|:--------|-----:|-----------------:|-----------------:|------------:|
| ALL     | 4723 |            0.798 |            0.566 |       0.369 |

_Source: `g0_skew_vs_independent.csv` (1 rows)._

### G0 — PAID/RECEIVED skew by execution hour

|   hour |   n |   our_paid_share |   ind_paid_share |   flip_rate |
|-------:|----:|-----------------:|-----------------:|------------:|
|      1 | 181 |            0.757 |            0.508 |       0.448 |
|      2 | 228 |            0.833 |            0.539 |       0.417 |
|      3 | 234 |            0.842 |            0.573 |       0.372 |
|      4 | 232 |            0.828 |            0.547 |       0.418 |
|      5 | 215 |            0.851 |            0.516 |       0.447 |
|      6 | 208 |            0.798 |            0.495 |       0.447 |
|      7 | 251 |            0.761 |            0.582 |       0.402 |
|      8 | 337 |            0.825 |            0.605 |       0.374 |
|      9 | 373 |            0.783 |            0.536 |       0.402 |
|     10 | 366 |            0.803 |            0.568 |       0.328 |
|     11 | 357 |            0.776 |            0.65  |       0.249 |
|     12 | 273 |            0.762 |            0.604 |       0.311 |
|     13 | 229 |            0.769 |            0.594 |       0.306 |
|     14 | 224 |            0.817 |            0.585 |       0.339 |
|     15 | 222 |            0.838 |            0.572 |       0.365 |
|     16 | 194 |            0.804 |            0.567 |       0.351 |
|     17 |  51 |            0.667 |            0.529 |       0.137 |
|     18 |  10 |            0.7   |            0.4   |       0.3   |
|     19 |  44 |            0.818 |            0.523 |       0.295 |
|     20 | 147 |            0.769 |            0.517 |       0.442 |
|     21 | 164 |            0.756 |            0.53  |       0.372 |
|     22 | 168 |            0.798 |            0.601 |       0.423 |
|     23 |  15 |            0.933 |            0.533 |       0.4   |

_Source: `g0_skew_vs_independent_by_hour.csv` (23 rows)._

### G0 — is a flip explained by the curve gap alone?

| stratum                  |    n |   flip_rate |   predicted_rate |   agreement |   true_positive |   false_positive |   false_negative |   true_negative |   median_abs_s2m_bps |   median_offset_bps |
|:-------------------------|-----:|------------:|-----------------:|------------:|----------------:|-----------------:|-----------------:|----------------:|---------------------:|--------------------:|
| ALL                      | 4723 |       0.369 |            0.403 |       0.965 |            1741 |              163 |                0 |            2819 |                0.637 |              -0.356 |
| |s2m| (-0.001, 0.221]    |  945 |       0.422 |            0.549 |       0.873 |             399 |              120 |                0 |             426 |                0.129 |              -0.046 |
| |s2m| (0.221, 0.435]     |  944 |       0.411 |            0.442 |       0.969 |             388 |               29 |                0 |             527 |                0.318 |              -0.242 |
| |s2m| (0.435, 1.016]     |  945 |       0.363 |            0.377 |       0.986 |             343 |               13 |                0 |             589 |                0.637 |              -0.458 |
| |s2m| (1.016, 5.762]     |  944 |       0.305 |            0.306 |       0.999 |             288 |                1 |                0 |             655 |                1.532 |              -1.106 |
| |s2m| (5.762, 39597.669] |  945 |       0.342 |            0.342 |       1     |             323 |                0 |                0 |             622 |               12.958 |              -7.782 |

_Source: `g0_flip_mechanism.csv` (6 rows)._

### G0 — is p_flip calibrated against an independent mid?

| stratum                     |    n |   mean_p_flip |   observed_flip |   calibration_gap |   spearman_rank |   mean_weight |   mean_weight_agreeing |   mean_weight_flipped |
|:----------------------------|-----:|--------------:|----------------:|------------------:|----------------:|--------------:|-----------------------:|----------------------:|
| ALL                         | 2732 |         0.045 |           0.4   |             0.355 |           0.063 |         0.909 |                  0.917 |                 0.898 |
| p_flip (-0.001, 3.17e-13]   |  547 |         0     |           0.369 |             0.369 |                 |         1     |                        |                       |
| p_flip (3.17e-13, 0.000158] |  546 |         0     |           0.357 |             0.357 |                 |         1     |                        |                       |
| p_flip (0.000158, 0.00896]  |  546 |         0.002 |           0.405 |             0.402 |                 |         0.995 |                        |                       |
| p_flip (0.00896, 0.0812]    |  546 |         0.035 |           0.418 |             0.383 |                 |         0.931 |                        |                       |
| p_flip (0.0812, 0.452]      |  547 |         0.189 |           0.453 |             0.264 |                 |         0.621 |                        |                       |

_Source: `g0_pflip_calibration.csv` (6 rows)._

### G0 — implied bounds on direction accuracy

|   flip_rate |   accuracy_ceiling |   attenuation_at_ceiling |
|------------:|-------------------:|-------------------------:|
|       0.398 |              0.801 |                    0.602 |

_Source: `g0_implied_accuracy.csv` (1 rows)._

### G1 — arrival integrity (differential poison audits)

| audit             | pass   |      n | mode           | observed_delays         | illegal_delays   |   n_shorter_than_minimum |   n_timestamps |   n_leaking |   min_future_prints |   max_future_prints | leaks   |   split_at |   max_abs_dev_in_head |
|:------------------|:-------|-------:|:---------------|:------------------------|:-----------------|-------------------------:|---------------:|------------:|--------------------:|--------------------:|:--------|-----------:|----------------------:|
| visibility_delays | True   | 344448 | delay-set-only | [1.0, 15.0, 30.0, 60.0] | []               |                        0 |                |             |                     |                     | nan     |            |                       |
| future_poison     | True   |        | nan            | nan                     | nan              |                          |            200 |           0 |                 876 |              343116 | []      |            |                       |
| trailing_moments  | True   |  13248 | nan            | nan                     | nan              |                          |                |             |                     |                     | nan     |       6624 |                     0 |

_Source: `g1_audits.csv` (3 rows)._

### G2 — lead-lag summary, SR3

|    mean |     se |       t |   n |   n_blocks | stars   |   share_agreeing |   p_sign |
|--------:|-------:|--------:|----:|-----------:|:--------|-----------------:|---------:|
| -4.7689 | 1.9497 | -2.4459 | 624 |        104 | *       |            0.673 |    0.001 |

_Source: `g2_lead_lag_summary_FUTURES.csv` (1 rows)._

### G2 — flow response event study, SR3

|   horizon_min |      mean |      se |       t |    n |   n_blocks | stars   |   expected_sign |
|--------------:|----------:|--------:|--------:|-----:|-----------:|:--------|----------------:|
|             5 |    9.3867 |  85.15  |  0.1102 | 5893 |        104 | nan     |              -1 |
|            15 | -167.301  | 116.882 | -1.4314 | 5893 |        104 | nan     |              -1 |
|            30 | -266.658  | 149.526 | -1.7834 | 5893 |        104 | .       |              -1 |
|            60 | -234.118  | 226.059 | -1.0356 | 5893 |        104 | nan     |              -1 |

_Source: `g2_flow_response_FUTURES.csv` (4 rows)._

### G2 — signed peak correlation, SR3

|    mean |     se |       t |   n |   n_blocks | stars   |
|--------:|-------:|--------:|----:|-----------:|:--------|
| -0.0347 | 0.0128 | -2.7079 | 624 |        104 | **      |

_Source: `g2_peak_rho_summary_FUTURES.csv` (1 rows)._

### G2 — lead-lag by lag, SR3

|   day | bucket   |       lls |   peak_lag_min |   peak_rho |   n_x |   n_y |
|------:|:---------|----------:|---------------:|-----------:|------:|------:|
|     0 | SFRH26   |  -17.6348 |            -15 |    -0.2134 |    96 |    95 |
|     0 | SFRM26   |   -0.527  |            -15 |     0.1804 |    96 |    95 |
|     0 | SFRU26   |   -2.029  |             -1 |     0.2122 |    96 |    95 |
|     0 | SFRZ26   |    2.684  |            240 |    -0.164  |    96 |    95 |
|     0 | SFRH27   |   -2.0849 |            -15 |     0.3515 |    96 |    95 |
|     0 | SFRM27   |   -6.3876 |            -15 |     0.355  |    96 |    95 |
|     1 | SFRH26   |   -0.8195 |            -60 |    -0.223  |    96 |    96 |
|     1 | SFRM26   |   -2.7499 |            -60 |    -0.2628 |    96 |    96 |
|     1 | SFRU26   |   -0.4    |            -60 |    -0.0813 |    96 |    96 |
|     1 | SFRZ26   |   -3.5558 |             -1 |     0.3025 |    96 |    96 |
|     1 | SFRH27   |   -1.5707 |             -1 |     0.3445 |    96 |    96 |
|     1 | SFRM27   |   -6.5232 |             -1 |     0.3874 |    96 |    96 |
|     2 | SFRH26   |   -2.4676 |              1 |    -0.336  |    96 |    96 |
|     2 | SFRM26   |    1.2977 |             60 |    -0.1883 |    96 |    96 |
|     2 | SFRU26   |   -4.3105 |             -1 |     0.2377 |    96 |    96 |
|     2 | SFRZ26   | -316.654  |            -30 |    -0.3662 |    96 |    96 |
|     2 | SFRH27   |   -1.0575 |            -15 |     0.1505 |    96 |    96 |
|     2 | SFRM27   |    0.058  |           -240 |     0.178  |    96 |    96 |
|     3 | SFRH26   |   -3.6023 |             -5 |    -0.2067 |    96 |    96 |
|     3 | SFRM26   |   -0.1487 |            -15 |    -0.0985 |    96 |    96 |
|     3 | SFRU26   |    2.2725 |             30 |     0.3589 |    96 |    96 |
|     3 | SFRZ26   |   -3.427  |            -30 |     0.301  |    96 |    96 |
|     3 | SFRH27   |    0.1844 |              0 |     0.2212 |    96 |    96 |
|     3 | SFRM27   |   -0.5803 |              1 |     0.207  |    96 |    96 |
|     4 | SFRH26   |   -9.1167 |             -1 |    -0.325  |    96 |    96 |
|     4 | SFRM26   |   -3.9123 |            -30 |    -0.3374 |    96 |    96 |
|     4 | SFRU26   |    0.0756 |             30 |     0.3378 |    96 |    96 |
|     4 | SFRZ26   |   -0.2151 |            -60 |     0.2156 |    96 |    96 |
|     4 | SFRH27   |    0.0511 |              5 |     0.1594 |    96 |    96 |
|     4 | SFRM27   |    0.3005 |              5 |     0.14   |    96 |    96 |
|     5 | SFRH26   |   -1.7893 |            -60 |     0.2454 |    96 |    96 |
|     5 | SFRM26   |    3.9164 |              5 |     0.2685 |    96 |    96 |
|     5 | SFRU26   |    0.0806 |            -60 |    -0.3116 |    96 |    96 |
|     5 | SFRZ26   |    1.4826 |             60 |     0.1734 |    96 |    96 |
|     5 | SFRH27   |   -0.8843 |            -60 |    -0.264  |    96 |    96 |
|     5 | SFRM27   |  -56.0492 |            -60 |    -0.4668 |    96 |    96 |
|     6 | SFRH26   |    0.0763 |            120 |    -0.2711 |    96 |    96 |
|     6 | SFRM26   |   -3.6538 |           -120 |    -0.3324 |    96 |    96 |
|     6 | SFRU26   |    1.067  |             60 |     0.2885 |    96 |    96 |
|     6 | SFRZ26   |   -0.4267 |              0 |    -0.1642 |    96 |    96 |
|     6 | SFRH27   |   -0.7392 |           -240 |     0.1555 |    96 |    96 |
|     6 | SFRM27   |   -1.2015 |            -60 |     0.2271 |    96 |    96 |
|     7 | SFRH26   |   -0.2318 |            -60 |    -0.1306 |    96 |    96 |
|     7 | SFRM26   |   -3.3387 |           -240 |    -0.24   |    96 |    96 |
|     7 | SFRU26   |  -27.9055 |             -5 |     0.4425 |    96 |    96 |
|     7 | SFRZ26   | -164.318  |             -5 |     0.4435 |    96 |    96 |
|     7 | SFRH27   |   -8.6634 |           -240 |    -0.4052 |    96 |    96 |
|     7 | SFRM27   |    0.3825 |              1 |    -0.1845 |    96 |    96 |
|     8 | SFRH26   |   -0.5237 |             -1 |     0.1022 |    96 |    96 |
|     8 | SFRM26   |    5.281  |             30 |     0.3209 |    96 |    96 |
|     8 | SFRU26   |   -0.0235 |             -5 |    -0.1717 |    96 |    96 |
|     8 | SFRZ26   |   -0.1094 |             30 |    -0.1949 |    96 |    96 |
|     8 | SFRH27   |   -1.9037 |            -15 |     0.1233 |    96 |    96 |
|     8 | SFRM27   |   -0.3207 |           -120 |    -0.0937 |    96 |    96 |
|     9 | SFRH26   |    0.6066 |              1 |     0.1019 |    96 |    96 |
|     9 | SFRM26   |   -0.421  |             -1 |    -0.1721 |    96 |    96 |
|     9 | SFRU26   |    1.8712 |             30 |     0.2326 |    96 |    96 |
|     9 | SFRZ26   |   -2.4638 |             -1 |    -0.1902 |    96 |    96 |
|     9 | SFRH27   |   -9.6409 |           -240 |    -0.3814 |    96 |    96 |
|     9 | SFRM27   |   94.8675 |              5 |     0.4739 |    96 |    96 |
|    10 | SFRH26   |    0.1216 |            -30 |     0.1588 |    96 |    96 |
|    10 | SFRM26   |    8.1356 |             15 |     0.3936 |    96 |    96 |
|    10 | SFRU26   | -906.29   |             -1 |    -0.6451 |    96 |    96 |
|    10 | SFRZ26   |  -20.1392 |             -1 |    -0.4204 |    96 |    96 |
|    10 | SFRH27   |  -72.7488 |             -1 |    -0.6832 |    96 |    96 |
|    10 | SFRM27   |  -29.9295 |             -1 |    -0.474  |    96 |    96 |
|    11 | SFRH26   |   -3.222  |           -120 |     0.2021 |    96 |    96 |
|    11 | SFRM26   |    0.2318 |              1 |     0.108  |    96 |    96 |
|    11 | SFRU26   |   -0.2401 |           -120 |     0.1009 |    96 |    96 |
|    11 | SFRZ26   |    0.388  |             30 |    -0.1827 |    96 |    96 |
|    11 | SFRH27   |   -2.4473 |            -60 |    -0.2623 |    96 |    96 |
|    11 | SFRM27   |   -7.7876 |            -60 |    -0.331  |    96 |    96 |
|    12 | SFRH26   |    0.8011 |              5 |     0.2697 |    96 |    96 |
|    12 | SFRM26   |    4.2263 |              1 |    -0.4921 |    96 |    96 |
|    12 | SFRU26   |   -3.9189 |           -240 |    -0.2182 |    96 |    96 |
|    12 | SFRZ26   |    1.7169 |             30 |     0.2299 |    96 |    96 |
|    12 | SFRH27   |   -7.2853 |            -60 |     0.2403 |    96 |    96 |
|    12 | SFRM27   |   -6.0418 |            -15 |     0.2304 |    96 |    96 |
|    13 | SFRH26   |    0.0318 |            -15 |    -0.1002 |    96 |    96 |
|    13 | SFRM26   |    0.1737 |              1 |     0.2439 |    96 |    96 |

_Source: `g2_lead_lag_FUTURES.csv` (80 rows shown, 544 more in the CSV — truncated for length only)._

### G2 — flow-response events, SR3

| ts                        | bucket   |   horizon_min |   innovation |   flow_signed_by_innovation |   expected_sign |
|:--------------------------|:---------|--------------:|-------------:|----------------------------:|----------------:|
| 2026-01-12 08:15:00-05:00 | SFRH26   |             5 |     -17378.2 |                         550 |              -1 |
| 2026-01-12 08:15:00-05:00 | SFRH26   |            15 |     -17378.2 |                         159 |              -1 |
| 2026-01-12 08:15:00-05:00 | SFRH26   |            30 |     -17378.2 |                         159 |              -1 |
| 2026-01-12 08:15:00-05:00 | SFRH26   |            60 |     -17378.2 |                      -11577 |              -1 |
| 2026-01-12 09:05:00-05:00 | SFRH26   |             5 |     -68869   |                        -854 |              -1 |
| 2026-01-12 09:05:00-05:00 | SFRH26   |            15 |     -68869   |                        -839 |              -1 |
| 2026-01-12 09:05:00-05:00 | SFRH26   |            30 |     -68869   |                        -839 |              -1 |
| 2026-01-12 09:05:00-05:00 | SFRH26   |            60 |     -68869   |                        -839 |              -1 |
| 2026-01-12 09:10:00-05:00 | SFRH26   |             5 |     -27367.8 |                          -0 |              -1 |
| 2026-01-12 09:10:00-05:00 | SFRH26   |            15 |     -27367.8 |                          15 |              -1 |
| 2026-01-12 09:10:00-05:00 | SFRH26   |            30 |     -27367.8 |                          15 |              -1 |
| 2026-01-12 09:10:00-05:00 | SFRH26   |            60 |     -27367.8 |                          15 |              -1 |
| 2026-01-12 09:20:00-05:00 | SFRH26   |             5 |     -63539.3 |                          -0 |              -1 |
| 2026-01-12 09:20:00-05:00 | SFRH26   |            15 |     -63539.3 |                          -0 |              -1 |
| 2026-01-12 09:20:00-05:00 | SFRH26   |            30 |     -63539.3 |                          -0 |              -1 |
| 2026-01-12 09:20:00-05:00 | SFRH26   |            60 |     -63539.3 |                          -0 |              -1 |
| 2026-01-12 09:35:00-05:00 | SFRH26   |             5 |      66758.9 |                           0 |              -1 |
| 2026-01-12 09:35:00-05:00 | SFRH26   |            15 |      66758.9 |                           0 |              -1 |
| 2026-01-12 09:35:00-05:00 | SFRH26   |            30 |      66758.9 |                           0 |              -1 |
| 2026-01-12 09:35:00-05:00 | SFRH26   |            60 |      66758.9 |                           0 |              -1 |
| 2026-01-12 10:05:00-05:00 | SFRH26   |             5 |      59420.8 |                           0 |              -1 |
| 2026-01-12 10:05:00-05:00 | SFRH26   |            15 |      59420.8 |                           0 |              -1 |
| 2026-01-12 10:05:00-05:00 | SFRH26   |            30 |      59420.8 |                           0 |              -1 |
| 2026-01-12 10:05:00-05:00 | SFRH26   |            60 |      59420.8 |                           0 |              -1 |
| 2026-01-12 10:10:00-05:00 | SFRH26   |             5 |     201307   |                           0 |              -1 |
| 2026-01-12 10:10:00-05:00 | SFRH26   |            15 |     201307   |                           0 |              -1 |
| 2026-01-12 10:10:00-05:00 | SFRH26   |            30 |     201307   |                           0 |              -1 |
| 2026-01-12 10:10:00-05:00 | SFRH26   |            60 |     201307   |                           0 |              -1 |
| 2026-01-12 10:15:00-05:00 | SFRH26   |             5 |     -71978.6 |                          -0 |              -1 |
| 2026-01-12 10:15:00-05:00 | SFRH26   |            15 |     -71978.6 |                          -0 |              -1 |
| 2026-01-12 10:15:00-05:00 | SFRH26   |            30 |     -71978.6 |                          -0 |              -1 |
| 2026-01-12 10:15:00-05:00 | SFRH26   |            60 |     -71978.6 |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | SFRH26   |             5 |    -194877   |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | SFRH26   |            15 |    -194877   |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | SFRH26   |            30 |    -194877   |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | SFRH26   |            60 |    -194877   |                         278 |              -1 |
| 2026-01-12 11:45:00-05:00 | SFRH26   |             5 |      80666.1 |                           0 |              -1 |
| 2026-01-12 11:45:00-05:00 | SFRH26   |            15 |      80666.1 |                           0 |              -1 |
| 2026-01-12 11:45:00-05:00 | SFRH26   |            30 |      80666.1 |                           0 |              -1 |
| 2026-01-12 11:45:00-05:00 | SFRH26   |            60 |      80666.1 |                           0 |              -1 |

_Source: `g2_flow_events_FUTURES.csv` (40 rows shown, 23532 more in the CSV — truncated for length only)._

### G2 — lead-lag summary, ZQ (cross-check)

|     mean |      se |       t |   n |   n_blocks | stars   |   share_agreeing |   p_sign |
|---------:|--------:|--------:|----:|-----------:|:--------|-----------------:|---------:|
| -19.8752 | 11.1761 | -1.7784 | 624 |        104 | .       |            0.663 |    0.001 |

_Source: `g2_lead_lag_summary_FED_FUNDS.csv` (1 rows)._

### G2 — signed peak correlation, ZQ

|    mean |     se |       t |   n |   n_blocks | stars   |
|--------:|-------:|--------:|----:|-----------:|:--------|
| -0.0048 | 0.0129 | -0.3722 | 624 |        104 |         |

_Source: `g2_peak_rho_summary_FED_FUNDS.csv` (1 rows)._

### G2 — lead-lag by lag, ZQ

|   day | bucket   |       lls |   peak_lag_min |   peak_rho |   n_x |   n_y |
|------:|:---------|----------:|---------------:|-----------:|------:|------:|
|     0 | FFF26    |    0.1634 |            240 |    -0.0465 |    96 |    50 |
|     0 | FFG26    |   23.767  |             30 |     0.3925 |    96 |    92 |
|     0 | FFH26    |    7.8586 |            240 |    -0.1463 |    96 |    95 |
|     0 | FFJ26    |   52.4571 |             30 |    -0.4354 |    96 |    95 |
|     0 | FFK26    |    0.0595 |              1 |    -0.0266 |    96 |    95 |
|     0 | FFM26    | 1999.05   |              5 |     0.8573 |    96 |    81 |
|     1 | FFF26    |    0.1336 |              1 |    -0.1319 |    96 |    67 |
|     1 | FFG26    |   -0.6591 |            -30 |     0.4583 |    96 |    89 |
|     1 | FFH26    |    5.9382 |             15 |    -0.3749 |    96 |    92 |
|     1 | FFJ26    |   -0.5874 |            -30 |    -0.1882 |    96 |    96 |
|     1 | FFK26    |   -1.7761 |           -120 |    -0.2636 |    96 |    94 |
|     1 | FFM26    |  -67.8629 |           -120 |    -0.6445 |    96 |    85 |
|     2 | FFF26    |    0.7175 |            120 |     0.1302 |    96 |    80 |
|     2 | FFG26    |    0.137  |            120 |     0.0434 |    96 |    93 |
|     2 | FFH26    |    0.5459 |              1 |    -0.1061 |    96 |    93 |
|     2 | FFJ26    |   -3.319  |            -60 |     0.3056 |    96 |    96 |
|     2 | FFK26    |    0.0296 |           -240 |    -0.1085 |    96 |    96 |
|     2 | FFM26    |    2.8286 |             15 |    -0.1736 |    96 |    69 |
|     3 | FFF26    |    6.729  |             60 |     0.2796 |    96 |    84 |
|     3 | FFG26    |  -13.9949 |           -120 |     0.3596 |    96 |    82 |
|     3 | FFH26    | -303.041  |           -120 |     0.2562 |    96 |    96 |
|     3 | FFJ26    |    0.0365 |             30 |    -0.0606 |    96 |    96 |
|     3 | FFK26    |    0.016  |             30 |    -0.1352 |    96 |    94 |
|     3 | FFM26    |   -0.3713 |           -120 |     0.0775 |    96 |    85 |
|     4 | FFF26    |    0.7523 |             60 |     0.0268 |    96 |    72 |
|     4 | FFG26    |   -0.0271 |             -1 |     0.1002 |    96 |    69 |
|     4 | FFH26    |    0.6999 |            -60 |    -0.44   |    96 |    96 |
|     4 | FFJ26    |  -19.4871 |            -60 |    -0.4348 |    96 |    93 |
|     4 | FFK26    |    1.6357 |              1 |     0.5362 |    96 |    96 |
|     4 | FFM26    |    2.1131 |              1 |     0.3388 |    96 |    79 |
|     5 | FFF26    |    1.9849 |              5 |    -0.2281 |    96 |    96 |
|     5 | FFG26    |  116.172  |            240 |     0.5288 |    96 |    87 |
|     5 | FFH26    |    0.3691 |             15 |    -0.1349 |    96 |    89 |
|     5 | FFJ26    |    1.0923 |              1 |     0.1388 |    96 |    90 |
|     5 | FFK26    |   -9.0918 |             -1 |    -0.3204 |    96 |    94 |
|     5 | FFM26    |   -2.8165 |            -60 |     0.4642 |    96 |    80 |
|     6 | FFF26    |    0.4905 |             15 |    -0.191  |    96 |    80 |
|     6 | FFG26    |    0.206  |              5 |     0.1613 |    96 |    84 |
|     6 | FFH26    |   -0.0443 |             -5 |     0.0501 |    96 |    70 |
|     6 | FFJ26    |  -80.5141 |            -30 |     0.4329 |    96 |    90 |
|     6 | FFK26    |  118.902  |            120 |    -0.5337 |    96 |    69 |
|     6 | FFM26    | -120.194  |           -240 |    -0.6973 |    96 |    93 |
|     7 | FFF26    |   24.2091 |            120 |     0.306  |    96 |    69 |
|     7 | FFG26    |    5.0572 |             30 |     0.3742 |    96 |    96 |
|     7 | FFH26    |   -4.3336 |           -120 |    -0.4866 |    96 |    93 |
|     7 | FFJ26    |  -21.977  |            -60 |     0.3206 |    96 |    96 |
|     7 | FFK26    |   -0.3247 |             -1 |     0.1044 |    96 |    88 |
|     7 | FFM26    |  -10.0011 |           -120 |     0.2414 |    96 |    84 |
|     8 | FFF26    |    0      |          -1440 |     0      |    96 |    26 |
|     8 | FFG26    |   -3.3905 |            -15 |     0.202  |    96 |    96 |
|     8 | FFH26    |    0.0638 |             30 |    -0.0926 |    96 |    83 |
|     8 | FFJ26    |    3.2218 |              1 |     0.5712 |    96 |    83 |
|     8 | FFK26    |   -1.3452 |            -15 |    -0.1281 |    96 |    93 |
|     8 | FFM26    |    0.1752 |              1 |     0.2563 |    96 |    80 |
|     9 | FFF26    |    0.0025 |             -1 |     0.0269 |    96 |    39 |
|     9 | FFG26    |   -0.9392 |           -240 |     0.1459 |    96 |    89 |
|     9 | FFH26    |   -5.8311 |            -15 |    -0.3158 |    96 |    81 |
|     9 | FFJ26    |   -0.079  |            -15 |    -0.0812 |    96 |    96 |
|     9 | FFK26    |   -0.0241 |           -120 |     0.0537 |    96 |    81 |
|     9 | FFM26    |   -8.1164 |            -15 |    -0.5574 |    96 |    67 |
|    10 | FFF26    |    0.0432 |              1 |    -0.0355 |    96 |    60 |
|    10 | FFG26    |  349.121  |              5 |    -0.8931 |    96 |    94 |
|    10 | FFH26    |    0.0108 |              1 |     0.0297 |    96 |    96 |
|    10 | FFJ26    |   -1.2819 |            -30 |     0.198  |    96 |    89 |
|    10 | FFK26    |  -11.9354 |            -30 |     0.631  |    96 |    93 |
|    10 | FFM26    |  -10.3249 |             -1 |    -0.1388 |    96 |    91 |
|    11 | FFF26    |    0.1104 |              1 |    -0.0857 |    96 |    76 |
|    11 | FFG26    |   -0.6551 |           -120 |     0.3054 |    96 |    96 |
|    11 | FFH26    |   -3.1664 |            -15 |    -0.2579 |    96 |    88 |
|    11 | FFJ26    |   -1.8312 |            -15 |    -0.0847 |    96 |    96 |
|    11 | FFK26    |   -1.3826 |             -1 |    -0.0996 |    96 |    92 |
|    11 | FFM26    |    0.6115 |            120 |     0.2027 |    96 |    89 |
|    12 | FFF26    |  -22.067  |           -240 |     0.0276 |    96 |    40 |
|    12 | FFG26    |   -0.5644 |            -60 |     0.0919 |    96 |    91 |
|    12 | FFH26    |   -0.0051 |              0 |     0.0404 |    96 |    77 |
|    12 | FFJ26    |  -51.1732 |            -60 |    -0.3135 |    96 |    80 |
|    12 | FFK26    |   -0.3162 |             -1 |    -0.13   |    96 |    93 |
|    12 | FFM26    |   17.3467 |              1 |    -0.3533 |    96 |    77 |
|    13 | FFF26    |    0      |          -1440 |     0      |    96 |    26 |
|    13 | FFG26    |    0.0389 |            240 |    -0.0475 |    96 |    89 |

_Source: `g2_lead_lag_FED_FUNDS.csv` (80 rows shown, 544 more in the CSV — truncated for length only)._

### G2 — flow response event study, ZQ

|   horizon_min |     mean |      se |       t |    n |   n_blocks | stars   |   expected_sign |
|--------------:|---------:|--------:|--------:|-----:|-----------:|:--------|----------------:|
|             5 |  19.4205 | 31.7692 |  0.6113 | 5910 |        104 | nan     |              -1 |
|            15 | -44.2651 | 21.8686 | -2.0241 | 5910 |        104 | *       |              -1 |
|            30 | -59.542  | 41.1872 | -1.4456 | 5910 |        104 | nan     |              -1 |
|            60 | -37.6343 | 52.7986 | -0.7128 | 5910 |        104 | nan     |              -1 |

_Source: `g2_flow_response_FED_FUNDS.csv` (4 rows)._

### G2 — flow-response events, ZQ

| ts                        | bucket   |   horizon_min |   innovation |   flow_signed_by_innovation |   expected_sign |
|:--------------------------|:---------|--------------:|-------------:|----------------------------:|----------------:|
| 2026-01-12 08:15:00-05:00 | FFF26    |             5 |    -11932.4  |                          -0 |              -1 |
| 2026-01-12 08:15:00-05:00 | FFF26    |            15 |    -11932.4  |                          -0 |              -1 |
| 2026-01-12 08:15:00-05:00 | FFF26    |            30 |    -11932.4  |                          -0 |              -1 |
| 2026-01-12 08:15:00-05:00 | FFF26    |            60 |    -11932.4  |                          -0 |              -1 |
| 2026-01-12 09:05:00-05:00 | FFF26    |             5 |     -9938.72 |                          -0 |              -1 |
| 2026-01-12 09:05:00-05:00 | FFF26    |            15 |     -9938.72 |                          -0 |              -1 |
| 2026-01-12 09:05:00-05:00 | FFF26    |            30 |     -9938.72 |                          -0 |              -1 |
| 2026-01-12 09:05:00-05:00 | FFF26    |            60 |     -9938.72 |                          -0 |              -1 |
| 2026-01-12 09:20:00-05:00 | FFF26    |             5 |     -9214.8  |                          -0 |              -1 |
| 2026-01-12 09:20:00-05:00 | FFF26    |            15 |     -9214.8  |                          -0 |              -1 |
| 2026-01-12 09:20:00-05:00 | FFF26    |            30 |     -9214.8  |                          -0 |              -1 |
| 2026-01-12 09:20:00-05:00 | FFF26    |            60 |     -9214.8  |                          -0 |              -1 |
| 2026-01-12 10:15:00-05:00 | FFF26    |             5 |    -94770.6  |                          -0 |              -1 |
| 2026-01-12 10:15:00-05:00 | FFF26    |            15 |    -94770.6  |                          -0 |              -1 |
| 2026-01-12 10:15:00-05:00 | FFF26    |            30 |    -94770.6  |                          -0 |              -1 |
| 2026-01-12 10:15:00-05:00 | FFF26    |            60 |    -94770.6  |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | FFF26    |             5 |   -240984    |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | FFF26    |            15 |   -240984    |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | FFF26    |            30 |   -240984    |                          -0 |              -1 |
| 2026-01-12 10:40:00-05:00 | FFF26    |            60 |   -240984    |                         159 |              -1 |
| 2026-01-12 10:45:00-05:00 | FFF26    |             5 |     13390.2  |                           0 |              -1 |
| 2026-01-12 10:45:00-05:00 | FFF26    |            15 |     13390.2  |                           0 |              -1 |
| 2026-01-12 10:45:00-05:00 | FFF26    |            30 |     13390.2  |                           0 |              -1 |
| 2026-01-12 10:45:00-05:00 | FFF26    |            60 |     13390.2  |                        -159 |              -1 |
| 2026-01-12 10:50:00-05:00 | FFF26    |             5 |     10258.6  |                           0 |              -1 |
| 2026-01-12 10:50:00-05:00 | FFF26    |            15 |     10258.6  |                           0 |              -1 |
| 2026-01-12 10:50:00-05:00 | FFF26    |            30 |     10258.6  |                           0 |              -1 |
| 2026-01-12 10:50:00-05:00 | FFF26    |            60 |     10258.6  |                        -159 |              -1 |
| 2026-01-12 10:55:00-05:00 | FFF26    |             5 |     12172.1  |                           0 |              -1 |
| 2026-01-12 10:55:00-05:00 | FFF26    |            15 |     12172.1  |                           0 |              -1 |
| 2026-01-12 10:55:00-05:00 | FFF26    |            30 |     12172.1  |                           0 |              -1 |
| 2026-01-12 10:55:00-05:00 | FFF26    |            60 |     12172.1  |                        -159 |              -1 |
| 2026-01-12 11:00:00-05:00 | FFF26    |             5 |     11771.2  |                           0 |              -1 |
| 2026-01-12 11:00:00-05:00 | FFF26    |            15 |     11771.2  |                           0 |              -1 |
| 2026-01-12 11:00:00-05:00 | FFF26    |            30 |     11771.2  |                        -159 |              -1 |
| 2026-01-12 11:00:00-05:00 | FFF26    |            60 |     11771.2  |                        -159 |              -1 |
| 2026-01-12 11:05:00-05:00 | FFF26    |             5 |     11592.4  |                           0 |              -1 |
| 2026-01-12 11:05:00-05:00 | FFF26    |            15 |     11592.4  |                           0 |              -1 |
| 2026-01-12 11:05:00-05:00 | FFF26    |            30 |     11592.4  |                        -159 |              -1 |
| 2026-01-12 11:05:00-05:00 | FFF26    |            60 |     11592.4  |                        -159 |              -1 |

_Source: `g2_flow_events_FED_FUNDS.csv` (40 rows shown, 23600 more in the CSV — truncated for length only)._

### G2 — SR3 vs ZQ: which contract does the ladder lead?

| space     | root   |   lls_mean |   lls_t |   peak_rho_mean |   peak_rho_t | timing_lead   | direction_ok   | leads   | reading                                                       |
|:----------|:-------|-----------:|--------:|----------------:|-------------:|:--------------|:---------------|:--------|:--------------------------------------------------------------|
| FUTURES   | SR3    |     -4.769 |  -2.446 |          -0.035 |       -2.708 | False         | True           | False   | leads NEITHER -> no mechanism evidence from the ordering test |
| FED_FUNDS | ZQ     |    -19.875 |  -1.778 |          -0.005 |       -0.372 | False         | True           | False   | leads NEITHER -> no mechanism evidence from the ordering test |

_Source: `g2_cross_check.csv` (2 rows)._

### G3 — horse race against our own basis

| spec              | term              |    coef |      se |        t |     n |   n_blocks |   design_rank |   design_cols |   design_cond | rank_deficient   |
|:------------------|:------------------|--------:|--------:|---------:|------:|-----------:|--------------:|--------------:|--------------:|:-----------------|
| signal only       | const             |  0.0095 |  0.0443 |   0.2136 | 42426 |         99 |             2 |             2 |   1.344       | False            |
| signal only       | signal            |  0.0035 |  0.0247 |   0.14   | 42426 |         99 |             2 |             2 |   1.344       | False            |
| signal + controls | const             | 22.4472 | 16.0969 |   1.3945 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | signal            |  0.0132 |  0.0263 |   0.5031 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | basis_bp          |  0.0474 |  0.0234 |   2.0213 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | abs_basis_bp      | -0.0328 |  0.021  |  -1.5609 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | signed_basis_dv01 |  0      |  0      |   1.7088 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | level_bp          | -0.0602 |  0.0439 |  -1.3705 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | slope_bp          |  0.032  |  0.023  |   1.3896 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | curvature_bp      |  0.0253 |  0.0173 |   1.4639 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | trailing_60m_bp   | -0.0506 |  0.0281 |  -1.8035 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | realized_vol_bp   | -0.1723 |  0.2528 |  -0.6818 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | amihud            | 33.5876 |  0.0864 | 388.813  | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | tod_min           | -0.0003 |  0.0005 |  -0.6151 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | days_to_expiry    |  0.0001 |  0.0002 |   0.5542 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |
| signal + controls | days_to_fomc      | -0.0065 |  0.0048 |  -1.3677 | 42426 |         99 |            14 |            14 |   2.80051e+08 | False            |

_Source: `g3_horse_race_FUTURES.csv` (16 rows)._

### G3b — horse race against the INDEPENDENT (Citi) basis

| spec              | term               |    coef |      se |       t |     n |   n_blocks |   design_rank |   design_cols |   design_cond | rank_deficient   |
|:------------------|:-------------------|--------:|--------:|--------:|------:|-----------:|--------------:|--------------:|--------------:|:-----------------|
| signal only       | const              |  0.0182 |  0.0489 |  0.3725 | 38436 |         99 |             2 |             2 |   1.335       | False            |
| signal only       | signal             |  0.0133 |  0.0265 |  0.5012 | 38436 |         99 |             2 |             2 |   1.335       | False            |
| signal + controls | const              | 23.0489 | 17.4756 |  1.3189 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | signal             |  0.0233 |  0.0279 |  0.8368 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | basis_bp           |  0.0195 |  0.0276 |  0.7075 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | abs_basis_bp       |  0.0015 |  0.0264 |  0.0566 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | signed_basis_dv01  |  0      |  0      |  0.9036 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | level_bp           | -0.0621 |  0.0477 | -1.303  | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | slope_bp           |  0.0327 |  0.025  |  1.3078 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | curvature_bp       |  0.027  |  0.0187 |  1.4484 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | trailing_60m_bp    | -0.039  |  0.0324 | -1.2039 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | realized_vol_bp    | -0.2019 |  0.267  | -0.7559 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | amihud             |  2.9753 |  0.0878 | 33.8725 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | tod_min            | -0.0002 |  0.0005 | -0.4299 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | days_to_expiry     |  0.0002 |  0.0002 |  1.0847 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | days_to_fomc       | -0.0065 |  0.0052 | -1.2381 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | indep_basis_bp     |  0.1962 |  0.0432 |  4.5413 | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |
| signal + controls | abs_indep_basis_bp |  0.1326 |  0.0577 |  2.299  | 38436 |         99 |            16 |            16 |   2.91403e+08 | False            |

_Source: `g3_horse_race_independent_FUTURES.csv` (18 rows)._

### G3 — point-in-time verification of the controls

| curve             |   rows_dropped_future_stamp |   drop_rate |   rows_unverifiable_stamp |   unverifiable_rate |
|:------------------|----------------------------:|------------:|--------------------------:|--------------------:|
| decision_curve    |                           0 |           0 |                         0 |                   0 |
| independent_curve |                           0 |           0 |                         0 |                   0 |

_Source: `g3_point_in_time_FUTURES.csv` (2 rows)._

### G3 — leave-one-bucket-out

| held_out   |   mean_bp |      t |     n |
|:-----------|----------:|-------:|------:|
| SFRH26     |    0.0358 | 1.052  | 46194 |
| SFRH27     |    0.0301 | 1.0697 | 41295 |
| SFRM26     |    0.0387 | 1.0601 | 41295 |
| SFRM27     |    0.0324 | 1.0704 | 41295 |
| SFRU26     |    0.0335 | 0.9954 | 41295 |
| SFRU27     |    0.0284 | 0.9061 | 44655 |
| SFRZ26     |    0.0315 | 1.0175 | 41295 |
| <none>     |    0.0329 | 1.0371 | 49554 |

_Source: `g3_leave_one_out_FUTURES.csv` (8 rows)._

### G3 — residualised signal

| spec              | term   |   coef |     se |      t |     n |   n_blocks |   design_rank |   design_cols |   design_cond | rank_deficient   |
|:------------------|:-------|-------:|-------:|-------:|------:|-----------:|--------------:|--------------:|--------------:|:-----------------|
| signal only       | const  | 0.0089 | 0.0439 | 0.2038 | 42426 |         99 |             2 |             2 |         1.269 | False            |
| signal only       | signal | 0.0132 | 0.0265 | 0.5002 | 42426 |         99 |             2 |             2 |         1.269 | False            |
| signal + controls | const  | 0.0089 | 0.0439 | 0.2038 | 42426 |         99 |             2 |             2 |         1.269 | False            |
| signal + controls | signal | 0.0132 | 0.0265 | 0.5002 | 42426 |         99 |             2 |             2 |         1.269 | False            |

_Source: `g3_residual_race_FUTURES.csv` (4 rows)._

### G3 — horse race, ZQ (cross-check)

| spec              | term              |    coef |     se |         t |     n |   n_blocks |   design_rank |   design_cols |   design_cond | rank_deficient   |
|:------------------|:------------------|--------:|-------:|----------:|------:|-----------:|--------------:|--------------:|--------------:|:-----------------|
| signal only       | const             |  0.0212 | 0.0204 |    1.0403 | 16090 |         99 |             2 |             2 |   1.436       | False            |
| signal only       | signal            | -0.0122 | 0.0083 |   -1.4748 | 16090 |         99 |             2 |             2 |   1.436       | False            |
| signal + controls | const             |  6.3988 | 0.0037 | 1716.65   | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | signal            | -0.0118 | 0.0099 |   -1.1874 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | basis_bp          |  0.0133 | 0.0162 |    0.8217 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | abs_basis_bp      | -0.0217 | 0.0206 |   -1.0531 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | signed_basis_dv01 |  0      | 0      |    0.6458 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | level_bp          | -0.0174 | 0.0004 |  -39.7116 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | slope_bp          |  0.0014 | 0.0072 |    0.1931 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | curvature_bp      | -0.0083 | 0.01   |   -0.8321 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | trailing_60m_bp   | -0.1134 | 0.0299 |   -3.7957 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | realized_vol_bp   | -0.3556 | 0.2539 |   -1.4007 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | amihud            |  1.4425 | 1.6374 |    0.881  | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | tod_min           |  0      | 0.0002 |    0.0734 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | days_to_expiry    |  0.0006 | 0.0004 |    1.6717 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |
| signal + controls | days_to_fomc      | -0.0032 | 0.0024 |   -1.3387 | 16090 |         99 |            14 |            14 |   3.23296e+07 | False            |

_Source: `g3_horse_race_FED_FUNDS.csv` (16 rows)._

### G3b — horse race vs the independent basis, ZQ

_Not produced in this run — `g3_horse_race_independent_FED_FUNDS.csv` is absent. Optional, so this may be a stage that legitimately had nothing to report (e.g. a cross-check space with no data); it is NOT a result._

### G3 — point-in-time verification of the controls, ZQ

| curve          |   rows_dropped_future_stamp |   drop_rate |   rows_unverifiable_stamp |   unverifiable_rate |
|:---------------|----------------------------:|------------:|--------------------------:|--------------------:|
| decision_curve |                           0 |           0 |                         0 |                   0 |

_Source: `g3_point_in_time_FED_FUNDS.csv` (1 rows)._

### G3 — leave-one-bucket-out, ZQ

| held_out   |   mean_bp |       t |     n |
|:-----------|----------:|--------:|------:|
| FFF26      |   -0.0091 | -1.0495 | 41258 |
| FFG26      |   -0.0093 | -1.037  | 40047 |
| FFH26      |   -0.0097 | -1.0465 | 38486 |
| FFJ26      |   -0.0114 | -1.1861 | 36809 |
| FFK26      |   -0.0113 | -1.1082 | 35335 |
| FFM26      |   -0.0116 | -1.2361 | 34759 |
| FFN26      |   -0.0046 | -0.5019 | 34749 |
| FFQ26      |   -0.0062 | -0.8359 | 36057 |
| FFU26      |   -0.0076 | -1.0164 | 37986 |
| FFV26      |   -0.0093 | -1.0871 | 39502 |
| FFX26      |   -0.0088 | -1.016  | 41042 |
| <none>     |   -0.009  | -1.0425 | 41603 |

_Source: `g3_leave_one_out_FED_FUNDS.csv` (12 rows)._

### G3 — residualised signal, ZQ

| spec              | term   |    coef |     se |       t |     n |   n_blocks |   design_rank |   design_cols |   design_cond | rank_deficient   |
|:------------------|:-------|--------:|-------:|--------:|------:|-----------:|--------------:|--------------:|--------------:|:-----------------|
| signal only       | const  |  0.0214 | 0.0204 |  1.0497 | 16090 |         99 |             2 |             2 |         1.283 | False            |
| signal only       | signal | -0.0118 | 0.0099 | -1.19   | 16090 |         99 |             2 |             2 |         1.283 | False            |
| signal + controls | const  |  0.0214 | 0.0204 |  1.0497 | 16090 |         99 |             2 |             2 |         1.283 | False            |
| signal + controls | signal | -0.0118 | 0.0099 | -1.19   | 16090 |         99 |             2 |             2 |         1.283 | False            |

_Source: `g3_residual_race_FED_FUNDS.csv` (4 rows)._

### G4 — the rule against a CONSTANT position

| variant                 |   mean_bp |       t | stars   |    n |   n_blocks |   share_long |
|:------------------------|----------:|--------:|:--------|-----:|-----------:|-------------:|
| as traded               |   -0.5458 | -9.4433 | ***     | 1639 |         99 |        0.277 |
| always long rates (+1)  |   -0.4643 | -6.3687 | ***     | 1639 |         99 |        1     |
| always short rates (-1) |   -0.5357 | -7.3478 | ***     | 1639 |         99 |        0     |

_Source: `g4_directional_benchmark_is.csv` (3 rows)._

### G4 — the rule against a constant position, LOCKOUT

_Not produced in this run — `g4_directional_benchmark_lockout.csv` is absent. Optional, so this may be a stage that legitimately had nothing to report (e.g. a cross-check space with no data); it is NOT a result._

### G4 — staleness sensitivity of the primary

| max_stale_min   |   n_trades |   n_sessions |   gross_bp |   net_bp |       t | stars   |   mean_realised_horizon_min |   share_of_uncapped_trades |
|:----------------|-----------:|-------------:|-----------:|---------:|--------:|:--------|----------------------------:|---------------------------:|
| none            |       1639 |           99 |    -0.0458 |  -0.5458 | -9.4433 | ***     |                      59.568 |                      1     |
| 30              |       1639 |           99 |    -0.0458 |  -0.5458 | -9.4433 | ***     |                      59.568 |                      1     |
| 15              |       1639 |           99 |    -0.0458 |  -0.5458 | -9.4433 | ***     |                      59.568 |                      1     |
| 10              |       1639 |           99 |    -0.0461 |  -0.5461 | -9.4524 | ***     |                      59.575 |                      1     |
| 5               |       1639 |           99 |    -0.0451 |  -0.5451 | -9.4354 | ***     |                      59.622 |                      1     |
| 2               |       1633 |           99 |    -0.0484 |  -0.5484 | -9.4361 | ***     |                      59.737 |                      0.996 |
| 0               |       1578 |           98 |    -0.0596 |  -0.5596 | -9.3513 | ***     |                      60     |                      0.963 |

_Source: `g4_staleness_sensitivity.csv` (7 rows)._

### G4 — best vs median configuration

| role          | variant                                |    mean |     se |        t |    n |   n_blocks |      lo |      hi |   n_boot | stars   |   hit_rate |   share_long |   share_agreeing |   p_sign |
|:--------------|:---------------------------------------|--------:|-------:|---------:|-----:|-----------:|--------:|--------:|---------:|:--------|-----------:|-------------:|-----------------:|---------:|
| best-config   | FUTURES->FUTURES|hl1440|expected|h1440 | -0.6102 | 0.5535 |  -1.1024 |  304 |         74 | -1.6386 |  0.5388 |      200 | nan     |      0.457 |        0.062 |            0.527 |    0.728 |
| median-config | FUTURES->FUTURES|hl30|expected|h15     | -0.4822 | 0.0184 | -26.1631 | 4586 |         99 | -0.5232 | -0.4472 |      200 | ***     |      0.159 |        0.344 |            0.949 |    0     |

_Source: `g4_best_and_median.csv` (2 rows)._

### G4 — the full secondary grid

| variant                                      |    mean |     se |         t |     n |   n_blocks |      lo |      hi |   n_boot | stars   |   hit_rate |   share_long |   share_agreeing |   p_sign |
|:---------------------------------------------|--------:|-------:|----------:|------:|-----------:|--------:|--------:|---------:|:--------|-----------:|-------------:|-----------------:|---------:|
| FUTURES->FUTURES|hl1440|expected|h1440       | -0.6102 | 0.5535 |   -1.1024 |   304 |         74 | -1.6386 |  0.5388 |      200 | nan     |      0.457 |        0.062 |            0.527 |    0.728 |
| FUTURES->FUTURES|hl30|expected|h1440         | -0.4267 | 0.3741 |   -1.1406 |   375 |         78 | -1.2357 |  0.284  |      200 | nan     |      0.416 |        0.381 |            0.551 |    0.428 |
| FUTURES->FUTURES|hl1440|unweighted|h1440     | -0.6908 | 0.5509 |   -1.2538 |   304 |         76 | -1.6521 |  0.3134 |      200 | nan     |      0.461 |        0.069 |            0.5   |    1     |
| FUTURES->FUTURES|hl30|unweighted|h1440       | -0.5187 | 0.3986 |   -1.3012 |   375 |         78 | -1.302  |  0.2276 |      200 | nan     |      0.427 |        0.363 |            0.564 |    0.308 |
| FUTURES->FUTURES|hl90|unweighted|h1440       | -0.6925 | 0.3533 |   -1.9603 |   361 |         78 | -1.3577 | -0.0005 |      200 | *       |      0.407 |        0.291 |            0.59  |    0.141 |
| FUTURES->FUTURES|hl240|expected|h240         | -0.5219 | 0.2517 |   -2.0736 |   376 |         95 | -1.0369 | -0.1498 |      200 | *       |      0.37  |        0.205 |            0.642 |    0.007 |
| FUTURES->FUTURES|hl240|expected|h1440        | -0.8842 | 0.3751 |   -2.357  |   341 |         77 | -1.6717 | -0.2978 |      200 | *       |      0.411 |        0.194 |            0.597 |    0.11  |
| FUTURES->FUTURES|hl240|unweighted|h1440      | -0.8576 | 0.3604 |   -2.3796 |   344 |         77 | -1.6314 | -0.3312 |      200 | *       |      0.404 |        0.203 |            0.597 |    0.11  |
| FUTURES->FUTURES|hl1440|expected|h240        | -0.6911 | 0.2835 |   -2.4381 |   310 |         85 | -1.218  | -0.1984 |      200 | *       |      0.297 |        0.071 |            0.635 |    0.017 |
| FUTURES->FUTURES|hl90|expected|h1440         | -0.8242 | 0.3365 |   -2.4497 |   357 |         77 | -1.5294 | -0.2569 |      200 | *       |      0.403 |        0.263 |            0.584 |    0.171 |
| FUTURES->FUTURES|hl1440|unweighted|h240      | -0.7761 | 0.2809 |   -2.7632 |   307 |         88 | -1.2555 | -0.2977 |      200 | **      |      0.287 |        0.068 |            0.659 |    0.004 |
| FUTURES->FUTURES|hl30|expected|h240          | -0.5423 | 0.1943 |   -2.7902 |   420 |         95 | -0.9189 | -0.2398 |      200 | **      |      0.34  |        0.429 |            0.716 |    0     |
| FUTURES->FUTURES|hl240|unweighted|h240       | -0.6784 | 0.2327 |   -2.9159 |   384 |         95 | -1.1465 | -0.3058 |      200 | **      |      0.339 |        0.211 |            0.695 |    0     |
| FUTURES->FUTURES|hl90|expected|h240          | -0.6213 | 0.2122 |   -2.9282 |   404 |         95 | -1.0452 | -0.172  |      200 | **      |      0.354 |        0.334 |            0.684 |    0     |
| FUTURES->FUTURES|hl90|unweighted|h240        | -0.6714 | 0.2127 |   -3.156  |   407 |         97 | -1.0434 | -0.3028 |      200 | ***     |      0.339 |        0.329 |            0.67  |    0.001 |
| FUTURES->FUTURES|hl30|unweighted|h240        | -0.6367 | 0.1748 |   -3.6431 |   426 |         97 | -1.012  | -0.3131 |      200 | ***     |      0.326 |        0.418 |            0.711 |    0     |
| FED_FUNDS->FED_FUNDS|hl30|expected|h1440     | -0.3845 | 0.0979 |   -3.9259 |   342 |         76 | -0.5835 | -0.1778 |      200 | ***     |      0.251 |        0.401 |            0.776 |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|expected|h1440   | -0.4256 | 0.1029 |   -4.1376 |   309 |         77 | -0.6075 | -0.2152 |      200 | ***     |      0.223 |        0.243 |            0.753 |    0     |
| FED_FUNDS->FED_FUNDS|hl240|unweighted|h1440  | -0.4633 | 0.1117 |   -4.1483 |   320 |         78 | -0.6667 | -0.1918 |      200 | ***     |      0.228 |        0.359 |            0.795 |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|unweighted|h1440 | -0.4478 | 0.1043 |   -4.294  |   316 |         78 | -0.6315 | -0.2404 |      200 | ***     |      0.218 |        0.247 |            0.769 |    0     |
| FED_FUNDS->FED_FUNDS|hl30|unweighted|h1440   | -0.375  | 0.0831 |   -4.5152 |   342 |         77 | -0.5308 | -0.1808 |      200 | ***     |      0.254 |        0.418 |            0.805 |    0     |
| FED_FUNDS->FED_FUNDS|hl240|expected|h1440    | -0.5376 | 0.0955 |   -5.6309 |   319 |         75 | -0.7017 | -0.3532 |      200 | ***     |      0.21  |        0.345 |            0.813 |    0     |
| FED_FUNDS->FED_FUNDS|hl90|unweighted|h1440   | -0.5582 | 0.0986 |   -5.6624 |   331 |         77 | -0.7493 | -0.3606 |      200 | ***     |      0.218 |        0.411 |            0.818 |    0     |
| FED_FUNDS->FED_FUNDS|hl90|expected|h1440     | -0.5575 | 0.0945 |   -5.8982 |   326 |         76 | -0.7579 | -0.3707 |      200 | ***     |      0.212 |        0.387 |            0.803 |    0     |
| FUTURES->FUTURES|hl30|expected|h60           | -0.5046 | 0.0694 |   -7.2678 |  1520 |         99 | -0.6509 | -0.3695 |      200 | ***     |      0.243 |        0.363 |            0.879 |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|expected|h240    | -0.5737 | 0.0755 |   -7.5973 |   329 |         96 | -0.723  | -0.4196 |      200 | ***     |      0.143 |        0.24  |            0.927 |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|unweighted|h240  | -0.5727 | 0.0753 |   -7.6063 |   330 |         94 | -0.7189 | -0.4049 |      200 | ***     |      0.155 |        0.264 |            0.904 |    0     |
| FED_FUNDS->FED_FUNDS|hl90|unweighted|h240    | -0.5853 | 0.066  |   -8.8662 |   378 |         97 | -0.7352 | -0.4663 |      200 | ***     |      0.161 |        0.458 |            0.907 |    0     |
| FUTURES->FUTURES|hl240|expected|h60          | -0.5262 | 0.0592 |   -8.8885 |  1601 |         98 | -0.6656 | -0.4226 |      200 | ***     |      0.245 |        0.204 |            0.837 |    0     |
| FED_FUNDS->FED_FUNDS|hl30|unweighted|h240    | -0.5504 | 0.0612 |   -8.989  |   392 |         95 | -0.6782 | -0.4347 |      200 | ***     |      0.145 |        0.48  |            0.905 |    0     |
| FUTURES->FUTURES|hl1440|expected|h60         | -0.5758 | 0.0622 |   -9.2567 |  1663 |         94 | -0.7025 | -0.4534 |      200 | ***     |      0.229 |        0.075 |            0.904 |    0     |
| FED_FUNDS->FED_FUNDS|hl30|expected|h240      | -0.5573 | 0.0601 |   -9.2763 |   384 |         95 | -0.6827 | -0.4443 |      200 | ***     |      0.159 |        0.479 |            0.884 |    0     |
| FED_FUNDS->FED_FUNDS|hl90|expected|h240      | -0.5879 | 0.0628 |   -9.3566 |   367 |         95 | -0.7142 | -0.4748 |      200 | ***     |      0.144 |        0.439 |            0.905 |    0     |
| FUTURES->FUTURES|hl90|expected|h60           | -0.5458 | 0.0578 |   -9.4433 |  1639 |         99 | -0.681  | -0.4412 |      200 | ***     |      0.236 |        0.277 |            0.899 |    0     |
| FUTURES->FUTURES|hl30|unweighted|h60         | -0.5517 | 0.0578 |   -9.5458 |  1534 |         99 | -0.6856 | -0.4346 |      200 | ***     |      0.241 |        0.375 |            0.889 |    0     |
| FED_FUNDS->FED_FUNDS|hl240|expected|h240     | -0.6409 | 0.0647 |   -9.9013 |   330 |         94 | -0.7751 | -0.5221 |      200 | ***     |      0.121 |        0.385 |            0.936 |    0     |
| FED_FUNDS->FED_FUNDS|hl240|unweighted|h240   | -0.6224 | 0.0628 |   -9.9077 |   341 |         96 | -0.7736 | -0.4828 |      200 | ***     |      0.147 |        0.402 |            0.927 |    0     |
| FUTURES->FUTURES|hl240|unweighted|h60        | -0.561  | 0.056  |  -10.0211 |  1639 |         98 | -0.6853 | -0.4611 |      200 | ***     |      0.242 |        0.214 |            0.857 |    0     |
| FUTURES->FUTURES|hl1440|unweighted|h60       | -0.5822 | 0.0556 |  -10.4751 |  1649 |         96 | -0.6638 | -0.4878 |      200 | ***     |      0.228 |        0.083 |            0.875 |    0     |
| FUTURES->FUTURES|hl90|unweighted|h60         | -0.6108 | 0.0565 |  -10.8085 |  1656 |         99 | -0.7344 | -0.5127 |      200 | ***     |      0.229 |        0.29  |            0.909 |    0     |
| FUTURES->FUTURES|hl30|unweighted|h30         | -0.4621 | 0.0365 |  -12.6495 |  2601 |         99 | -0.5429 | -0.3846 |      200 | ***     |      0.21  |        0.359 |            0.899 |    0     |
| FUTURES->FUTURES|hl30|expected|h30           | -0.4722 | 0.0372 |  -12.7    |  2591 |         99 | -0.558  | -0.4023 |      200 | ***     |      0.202 |        0.352 |            0.899 |    0     |
| FUTURES->FUTURES|hl90|expected|h30           | -0.5318 | 0.0305 |  -17.4516 |  2991 |         99 | -0.5916 | -0.4769 |      200 | ***     |      0.202 |        0.28  |            0.96  |    0     |
| FUTURES->FUTURES|hl90|unweighted|h30         | -0.5403 | 0.0283 |  -19.0741 |  3024 |         99 | -0.5998 | -0.4966 |      200 | ***     |      0.203 |        0.289 |            0.97  |    0     |
| FUTURES->FUTURES|hl240|expected|h30          | -0.5179 | 0.0271 |  -19.0833 |  3101 |         98 | -0.5809 | -0.4738 |      200 | ***     |      0.199 |        0.21  |            0.939 |    0     |
| FUTURES->FUTURES|hl1440|expected|h30         | -0.5341 | 0.0276 |  -19.3579 |  3412 |         95 | -0.5783 | -0.4841 |      200 | ***     |      0.194 |        0.077 |            0.968 |    0     |
| FUTURES->FUTURES|hl240|unweighted|h30        | -0.5218 | 0.0263 |  -19.8236 |  3147 |         98 | -0.5807 | -0.4778 |      200 | ***     |      0.194 |        0.222 |            0.939 |    0     |
| FUTURES->FUTURES|hl1440|unweighted|h30       | -0.5352 | 0.0259 |  -20.6923 |  3385 |         97 | -0.5772 | -0.4835 |      200 | ***     |      0.192 |        0.086 |            0.969 |    0     |
| FUTURES->FUTURES|hl30|expected|h15           | -0.4822 | 0.0184 |  -26.1631 |  4586 |         99 | -0.5232 | -0.4472 |      200 | ***     |      0.159 |        0.344 |            0.949 |    0     |
| FUTURES->FUTURES|hl30|unweighted|h15         | -0.4811 | 0.0169 |  -28.5058 |  4612 |         99 | -0.5209 | -0.4483 |      200 | ***     |      0.157 |        0.353 |            0.96  |    0     |
| FED_FUNDS->FED_FUNDS|hl240|expected|h60      | -0.5261 | 0.018  |  -29.1859 |  1419 |         98 | -0.5609 | -0.4954 |      200 | ***     |      0.071 |        0.361 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl90|expected|h60       | -0.5309 | 0.0176 |  -30.1952 |  1349 |         98 | -0.5627 | -0.5019 |      200 | ***     |      0.07  |        0.409 |            0.99  |    0     |
| FED_FUNDS->FED_FUNDS|hl30|expected|h60       | -0.517  | 0.0171 |  -30.2625 |  1236 |         99 | -0.551  | -0.4816 |      200 | ***     |      0.078 |        0.428 |            0.99  |    0     |
| FED_FUNDS->FED_FUNDS|hl240|unweighted|h60    | -0.5306 | 0.0173 |  -30.6413 |  1489 |         99 | -0.5676 | -0.4979 |      200 | ***     |      0.083 |        0.376 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl90|unweighted|h60     | -0.514  | 0.0166 |  -31.0549 |  1391 |         99 | -0.5506 | -0.4817 |      200 | ***     |      0.083 |        0.422 |            0.99  |    0     |
| FED_FUNDS->FED_FUNDS|hl30|unweighted|h60     | -0.5076 | 0.016  |  -31.6612 |  1256 |         99 | -0.5387 | -0.4762 |      200 | ***     |      0.084 |        0.439 |            0.98  |    0     |
| FUTURES->FUTURES|hl90|expected|h15           | -0.5135 | 0.0155 |  -33.0672 |  5602 |         99 | -0.5442 | -0.4856 |      200 | ***     |      0.156 |        0.28  |            0.99  |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|expected|h60     | -0.5055 | 0.015  |  -33.7945 |  1768 |         98 | -0.5364 | -0.4768 |      200 | ***     |      0.097 |        0.258 |            0.98  |    0     |
| FUTURES->FUTURES|hl90|unweighted|h15         | -0.5119 | 0.0146 |  -35.1709 |  5670 |         99 | -0.5435 | -0.4876 |      200 | ***     |      0.153 |        0.29  |            0.99  |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|unweighted|h60   | -0.5135 | 0.0142 |  -36.1346 |  1760 |         97 | -0.5429 | -0.4872 |      200 | ***     |      0.093 |        0.273 |            0.979 |    0     |
| FUTURES->FUTURES|hl240|expected|h15          | -0.5103 | 0.0137 |  -37.3333 |  6021 |         98 | -0.5401 | -0.4877 |      200 | ***     |      0.149 |        0.212 |            1     |    0     |
| FUTURES->FUTURES|hl240|unweighted|h15        | -0.5047 | 0.0133 |  -38.0066 |  6093 |         98 | -0.5351 | -0.4849 |      200 | ***     |      0.152 |        0.224 |            1     |    0     |
| FUTURES->FUTURES|hl1440|expected|h15         | -0.5139 | 0.0131 |  -39.31   |  6876 |         95 | -0.5363 | -0.488  |      200 | ***     |      0.154 |        0.079 |            0.968 |    0     |
| FUTURES->FUTURES|hl1440|unweighted|h15       | -0.5135 | 0.0124 |  -41.5112 |  6807 |         97 | -0.534  | -0.4893 |      200 | ***     |      0.152 |        0.088 |            0.979 |    0     |
| FED_FUNDS->FED_FUNDS|hl30|expected|h30       | -0.505  | 0.0109 |  -46.4769 |  2053 |         99 | -0.5282 | -0.4852 |      200 | ***     |      0.07  |        0.429 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl30|unweighted|h30     | -0.4995 | 0.0105 |  -47.5167 |  2068 |         99 | -0.5234 | -0.4772 |      200 | ***     |      0.078 |        0.439 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl90|unweighted|h30     | -0.5064 | 0.0099 |  -51.1986 |  2498 |         99 | -0.5253 | -0.4874 |      200 | ***     |      0.067 |        0.422 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl90|expected|h30       | -0.5135 | 0.0095 |  -54.1611 |  2427 |         98 | -0.531  | -0.4969 |      200 | ***     |      0.06  |        0.414 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl240|unweighted|h30    | -0.5113 | 0.0085 |  -60.2981 |  2818 |         99 | -0.5289 | -0.4941 |      200 | ***     |      0.061 |        0.379 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl240|expected|h30      | -0.5125 | 0.0081 |  -63.5282 |  2678 |         98 | -0.5281 | -0.4975 |      200 | ***     |      0.058 |        0.37  |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|unweighted|h30   | -0.5026 | 0.0074 |  -67.6514 |  3492 |         98 | -0.5161 | -0.4889 |      200 | ***     |      0.071 |        0.276 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|expected|h30     | -0.5032 | 0.0074 |  -68.2774 |  3528 |         98 | -0.5206 | -0.489  |      200 | ***     |      0.07  |        0.26  |            1     |    0     |
| FUTURES->FUTURES|hl30|unweighted|h5          | -0.4953 | 0.0066 |  -74.743  | 12518 |         99 | -0.5092 | -0.4828 |      200 | ***     |      0.105 |        0.349 |            1     |    0     |
| FUTURES->FUTURES|hl30|expected|h5            | -0.4973 | 0.0065 |  -76.8428 | 12411 |         99 | -0.5111 | -0.4853 |      200 | ***     |      0.104 |        0.341 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl30|expected|h15       | -0.5012 | 0.0061 |  -81.6607 |  3600 |         99 | -0.5135 | -0.4894 |      200 | ***     |      0.044 |        0.428 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl30|unweighted|h15     | -0.4988 | 0.0059 |  -84.0354 |  3671 |         99 | -0.5119 | -0.4858 |      200 | ***     |      0.048 |        0.438 |            1     |    0     |
| FUTURES->FUTURES|hl90|expected|h5            | -0.5021 | 0.0053 |  -94.6446 | 15936 |         99 | -0.513  | -0.4927 |      200 | ***     |      0.103 |        0.282 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl90|unweighted|h15     | -0.503  | 0.0051 |  -99.2702 |  4657 |         99 | -0.5119 | -0.4924 |      200 | ***     |      0.046 |        0.427 |            1     |    0     |
| FUTURES->FUTURES|hl90|unweighted|h5          | -0.5011 | 0.005  |  -99.4173 | 16140 |         99 | -0.5118 | -0.4929 |      200 | ***     |      0.103 |        0.293 |            0.99  |    0     |
| FED_FUNDS->FED_FUNDS|hl90|expected|h15       | -0.5052 | 0.005  | -100.668  |  4525 |         98 | -0.5142 | -0.4951 |      200 | ***     |      0.041 |        0.418 |            1     |    0     |
| FUTURES->FUTURES|hl240|expected|h5           | -0.5029 | 0.0046 | -110.495  | 17633 |         98 | -0.5144 | -0.4958 |      200 | ***     |      0.099 |        0.216 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl240|expected|h15      | -0.5049 | 0.0046 | -110.514  |  5167 |         98 | -0.5135 | -0.4955 |      200 | ***     |      0.041 |        0.371 |            1     |    0     |
| FUTURES->FUTURES|hl240|unweighted|h5         | -0.5008 | 0.0045 | -111.634  | 17823 |         98 | -0.5115 | -0.4937 |      200 | ***     |      0.099 |        0.227 |            0.99  |    0     |
| FED_FUNDS->FED_FUNDS|hl240|unweighted|h15    | -0.5028 | 0.0045 | -111.708  |  5405 |         99 | -0.512  | -0.4936 |      200 | ***     |      0.044 |        0.381 |            1     |    0     |
| FUTURES->FUTURES|hl1440|expected|h5          | -0.5048 | 0.0041 | -122.615  | 20712 |         95 | -0.5116 | -0.4971 |      200 | ***     |      0.096 |        0.08  |            1     |    0     |
| FUTURES->FUTURES|hl1440|unweighted|h5        | -0.5038 | 0.0041 | -123.647  | 20482 |         97 | -0.5106 | -0.4957 |      200 | ***     |      0.096 |        0.088 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|expected|h15     | -0.5005 | 0.0038 | -131.391  |  6995 |         98 | -0.509  | -0.4927 |      200 | ***     |      0.048 |        0.265 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|unweighted|h15   | -0.5    | 0.0038 | -132.294  |  6934 |         98 | -0.5069 | -0.4924 |      200 | ***     |      0.048 |        0.278 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl30|expected|h5        | -0.5004 | 0.0023 | -218.867  |  9661 |         99 | -0.5051 | -0.4958 |      200 | ***     |      0.024 |        0.43  |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl30|unweighted|h5      | -0.4994 | 0.0021 | -234.76   |  9911 |         99 | -0.5041 | -0.4947 |      200 | ***     |      0.025 |        0.437 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl90|expected|h5        | -0.5014 | 0.0018 | -272.988  | 12943 |         98 | -0.5046 | -0.4975 |      200 | ***     |      0.021 |        0.421 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl90|unweighted|h5      | -0.5009 | 0.0018 | -273.46   | 13349 |         99 | -0.5041 | -0.4971 |      200 | ***     |      0.023 |        0.431 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl240|expected|h5       | -0.501  | 0.0015 | -323.838  | 15202 |         98 | -0.5039 | -0.4981 |      200 | ***     |      0.02  |        0.372 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl240|unweighted|h5     | -0.5005 | 0.0015 | -325.099  | 15886 |         99 | -0.5035 | -0.4973 |      200 | ***     |      0.021 |        0.383 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|expected|h5      | -0.4999 | 0.0012 | -405.24   | 20936 |         98 | -0.5026 | -0.4975 |      200 | ***     |      0.024 |        0.266 |            1     |    0     |
| FED_FUNDS->FED_FUNDS|hl1440|unweighted|h5    | -0.4999 | 0.0012 | -421.007  | 20811 |         98 | -0.5021 | -0.4976 |      200 | ***     |      0.024 |        0.28  |            1     |    0     |

_Source: `g4_league.csv` (96 rows)._

### G4 — Romano-Wolf family-wise adjusted p

|    mean |     se |        t |   n |   n_blocks |   p_raw |   p_fwer |
|--------:|-------:|---------:|----:|-----------:|--------:|---------:|
| -0.3156 | 0.3537 |  -0.8924 |  99 |         99 |   0.394 |    0.588 |
| -0.3625 | 0.3537 |  -1.025  |  99 |         99 |   0.32  |    0.588 |
| -0.3098 | 0.297  |  -1.0431 |  99 |         99 |   0.281 |    0.588 |
| -0.3078 | 0.2856 |  -1.0776 |  99 |         99 |   0.25  |    0.588 |
| -0.5219 | 0.258  |  -2.0229 |  99 |         99 |   0.039 |    0.137 |
| -0.575  | 0.2724 |  -2.1112 |  99 |         99 |   0.032 |    0.126 |
| -0.6313 | 0.2826 |  -2.234  |  99 |         99 |   0.028 |    0.112 |
| -0.4984 | 0.2148 |  -2.3201 |  99 |         99 |   0.025 |    0.112 |
| -0.5785 | 0.2218 |  -2.608  |  99 |         99 |   0.011 |    0.061 |
| -0.627  | 0.2402 |  -2.61   |  99 |         99 |   0.011 |    0.061 |
| -0.6065 | 0.2273 |  -2.6678 |  99 |         99 |   0.008 |    0.058 |
| -0.6029 | 0.2214 |  -2.7239 |  99 |         99 |   0.003 |    0.053 |
| -0.5743 | 0.209  |  -2.7483 |  99 |         99 |   0.005 |    0.053 |
| -0.5918 | 0.1846 |  -3.2048 |  99 |         99 |   0.001 |    0.015 |
| -0.2888 | 0.0888 |  -3.2535 |  99 |         99 |   0.001 |    0.015 |
| -0.7566 | 0.2142 |  -3.5323 |  99 |         99 |   0.001 |    0.007 |
| -0.623  | 0.1748 |  -3.564  |  99 |         99 |   0.001 |    0.007 |
| -0.3258 | 0.0854 |  -3.8137 |  99 |         99 |   0.001 |    0.005 |
| -0.3003 | 0.076  |  -3.9501 |  99 |         99 |   0     |    0.003 |
| -0.3274 | 0.0825 |  -3.9665 |  99 |         99 |   0.001 |    0.003 |
| -0.3431 | 0.0855 |  -4.0107 |  99 |         99 |   0.001 |    0.003 |
| -0.4181 | 0.0799 |  -5.2331 |  99 |         99 |   0     |    0     |
| -0.4085 | 0.0775 |  -5.2705 |  99 |         99 |   0     |    0     |
| -0.3845 | 0.0723 |  -5.3194 |  99 |         99 |   0     |    0     |
| -0.4688 | 0.0772 |  -6.0699 |  99 |         99 |   0     |    0     |
| -0.4818 | 0.0714 |  -6.7465 |  99 |         99 |   0     |    0     |
| -0.5017 | 0.072  |  -6.9661 |  99 |         99 |   0     |    0     |
| -0.5678 | 0.0657 |  -8.6367 |  99 |         99 |   0     |    0     |
| -0.5184 | 0.0593 |  -8.7359 |  99 |         99 |   0     |    0     |
| -0.5295 | 0.0601 |  -8.8119 |  99 |         99 |   0     |    0     |
| -0.5112 | 0.0579 |  -8.8284 |  99 |         99 |   0     |    0     |
| -0.5488 | 0.0597 |  -9.1953 |  99 |         99 |   0     |    0     |
| -0.5947 | 0.0626 |  -9.5041 |  99 |         99 |   0     |    0     |
| -0.5797 | 0.0586 |  -9.8913 |  99 |         99 |   0     |    0     |
| -0.5357 | 0.0538 |  -9.9524 |  99 |         99 |   0     |    0     |
| -0.5363 | 0.0533 | -10.0703 |  99 |         99 |   0     |    0     |
| -0.5658 | 0.0544 | -10.3919 |  99 |         99 |   0     |    0     |
| -0.5338 | 0.0511 | -10.4439 |  99 |         99 |   0     |    0     |
| -0.5883 | 0.0558 | -10.5387 |  99 |         99 |   0     |    0     |
| -0.5349 | 0.0493 | -10.8595 |  99 |         99 |   0     |    0     |
| -0.5948 | 0.0539 | -11.0267 |  99 |         99 |   0     |    0     |
| -0.5675 | 0.0515 | -11.0287 |  99 |         99 |   0     |    0     |
| -0.4597 | 0.0405 | -11.3433 |  99 |         99 |   0     |    0     |
| -0.4606 | 0.0388 | -11.8782 |  99 |         99 |   0     |    0     |
| -0.4847 | 0.0358 | -13.5263 |  99 |         99 |   0     |    0     |
| -0.5412 | 0.0338 | -16.0176 |  99 |         99 |   0     |    0     |
| -0.5194 | 0.0319 | -16.2622 |  99 |         99 |   0     |    0     |
| -0.5106 | 0.03   | -17.0331 |  99 |         99 |   0     |    0     |
| -0.5092 | 0.0267 | -19.0627 |  99 |         99 |   0     |    0     |
| -0.5402 | 0.0266 | -20.3011 |  99 |         99 |   0     |    0     |
| -0.5213 | 0.0247 | -21.1306 |  99 |         99 |   0     |    0     |
| -0.4787 | 0.0222 | -21.5713 |  99 |         99 |   0     |    0     |
| -0.469  | 0.021  | -22.3821 |  99 |         99 |   0     |    0     |
| -0.5256 | 0.0222 | -23.6417 |  99 |         99 |   0     |    0     |
| -0.5258 | 0.0216 | -24.3648 |  99 |         99 |   0     |    0     |
| -0.4662 | 0.0191 | -24.4262 |  99 |         99 |   0     |    0     |
| -0.5134 | 0.0196 | -26.2549 |  99 |         99 |   0     |    0     |
| -0.5134 | 0.0181 | -28.3845 |  99 |         99 |   0     |    0     |
| -0.5078 | 0.0173 | -29.2852 |  99 |         99 |   0     |    0     |
| -0.5014 | 0.0168 | -29.8731 |  99 |         99 |   0     |    0     |

_Source: `g4_romano_wolf.csv` (60 rows shown, 36 more in the CSV — truncated for length only)._

### G4 — declared variants that could NOT run

| variant                                   | reason                                                |
|:------------------------------------------|:------------------------------------------------------|
| FED_FUNDS->FUTURES|hl30|expected|h5       | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|expected|h15      | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|expected|h30      | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|expected|h60      | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|expected|h240     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|expected|h1440    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|unweighted|h5     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|unweighted|h15    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|unweighted|h30    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|unweighted|h60    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|unweighted|h240   | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl30|unweighted|h1440  | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|expected|h5       | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|expected|h15      | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|expected|h30      | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|expected|h60      | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|expected|h240     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|expected|h1440    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|unweighted|h5     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|unweighted|h15    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|unweighted|h30    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|unweighted|h60    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|unweighted|h240   | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl90|unweighted|h1440  | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|expected|h5      | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|expected|h15     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|expected|h30     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|expected|h60     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|expected|h240    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|expected|h1440   | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|unweighted|h5    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|unweighted|h15   | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|unweighted|h30   | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|unweighted|h60   | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|unweighted|h240  | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl240|unweighted|h1440 | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl1440|expected|h5     | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl1440|expected|h15    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl1440|expected|h30    | no shared bucket keys between signal and target space |
| FED_FUNDS->FUTURES|hl1440|expected|h60    | no shared bucket keys between signal and target space |

_Source: `g4_skipped_variants.csv` (40 rows shown, 152 more in the CSV — truncated for length only)._

### G4 — placebos

| placebo                                      | expect                                            |    mean |     se |        t |    n |   n_blocks |      lo |      hi |   n_boot | stars   |   hit_rate |   share_long |   share_agreeing |   p_sign |
|:---------------------------------------------|:--------------------------------------------------|--------:|-------:|---------:|-----:|-----------:|--------:|--------:|---------:|:--------|-----------:|-------------:|-----------------:|---------:|
| none (reference)                             | the effect, if any                                | -0.5458 | 0.0578 |  -9.4433 | 1639 |         99 | -0.6588 | -0.425  |     2000 | ***     |      0.236 |        0.277 |            0.899 |        0 |
| sign shuffle within session                  | destroyed; survival means intensity not direction | -0.4476 | 0.0399 | -11.2199 | 1636 |         99 | -0.5168 | -0.3701 |      300 | ***     |      0.257 |        0.4   |            0.899 |        0 |
| arrival +1 grid step later                   | largely preserved; loss means knife-edge timing   | -0.5366 | 0.0552 |  -9.7137 | 1640 |         99 | -0.6533 | -0.4314 |      300 | ***     |      0.24  |        0.279 |            0.869 |        0 |
| live parity (visibility floored at exec+15m) | attenuated, same sign                             | -0.5405 | 0.0594 |  -9.0949 | 1636 |         98 | -0.6663 | -0.4279 |      300 | ***     |      0.234 |        0.276 |            0.888 |        0 |
| rotated buckets                              | ~0; survival means generic curve continuation     | -0.52   | 0.0557 |  -9.3347 | 1639 |         99 | -0.6372 | -0.4039 |      300 | ***     |      0.218 |        0.277 |            0.909 |        0 |
| pre-arrival window                           | ~0; a result means leakage or anticipation        | -0.4582 | 0.0735 |  -6.2323 | 1434 |         97 | -0.5799 | -0.3281 |      300 | ***     |      0.25  |        0.273 |            0.825 |        0 |

_Source: `g4_placebos.csv` (6 rows)._

### G4 — the label-free cell (unsigned print intensity)

|    mean |     se |       t |    n |   n_blocks |      lo |      hi |   n_boot | stars   |   hit_rate |   share_long |   share_agreeing |   p_sign | signal                   |
|--------:|-------:|--------:|-----:|-----------:|--------:|--------:|---------:|:--------|-----------:|-------------:|-----------------:|---------:|:-------------------------|
| -0.6402 | 0.0709 | -9.0344 | 1838 |         99 | -0.7785 | -0.5019 |     2000 | ***     |      0.238 |        0.497 |            0.848 |        0 | unsigned print intensity |

_Source: `g4_label_free.csv` (1 rows)._

### G4 — conditioning splits

| conditioner     | bucket   |   n |   n_blocks |   mean_net_bp |        t | stars   |   median_value |
|:----------------|:---------|----:|-----------:|--------------:|---------:|:--------|---------------:|
| block_share     | q1       | 546 |         59 |        -0.375 |  -5.488  | ***     |          0     |
| block_share     | q2       | 546 |         68 |        -0.667 |  -9.437  | ***     |          0.025 |
| block_share     | q3       | 547 |         59 |        -0.596 |  -4.6508 | ***     |          0.258 |
| level_prox_bp   | q1       | 546 |         86 |        -0.57  |  -8.0895 | ***     |         -9.056 |
| level_prox_bp   | q2       | 546 |         88 |        -0.6   |  -7.9855 | ***     |         -1.347 |
| level_prox_bp   | q3       | 547 |         88 |        -0.468 |  -5.9062 | ***     |          7.467 |
| realized_vol_bp | q1       | 477 |         88 |        -0.461 | -10.1336 | ***     |          0.257 |
| realized_vol_bp | q2       | 477 |         90 |        -0.589 |  -7.4928 | ***     |          0.396 |
| realized_vol_bp | q3       | 477 |         78 |        -0.415 |  -3.3874 | ***     |          0.634 |
| amihud          | q1       | 477 |         83 |        -0.484 | -10.4162 | ***     |          0     |
| amihud          | q2       | 477 |         92 |        -0.515 |  -5.2217 | ***     |          0     |
| amihud          | q3       | 477 |         87 |        -0.465 |  -4.3217 | ***     |          0     |
| days_to_fomc    | q1       | 570 |         34 |        -0.722 |  -8.339  | ***     |          5     |
| days_to_fomc    | q2       | 542 |         34 |        -0.544 |  -5.7151 | ***     |         15     |
| days_to_fomc    | q3       | 527 |         31 |        -0.357 |  -3.302  | ***     |         29     |
| tod_min         | q1       | 557 |         88 |        -0.636 |  -5.6688 | ***     |        540     |
| tod_min         | q2       | 535 |         91 |        -0.504 |  -6.4703 | ***     |        695     |
| tod_min         | q3       | 547 |         88 |        -0.495 |  -6.8246 | ***     |        820     |

_Source: `g4_conditioning.csv` (18 rows)._

### G4 — conditioners that could NOT be split

| conditioner   | reason                         |
|:--------------|:-------------------------------|
| sofr_effr_bp  | panel not built for this space |

_Source: `g4_conditioning_skipped.csv` (1 rows)._

### G5 — gross, cost, net and the attenuation grid

| measure              |   mean_bp |       t | stars   |    n |
|:---------------------|----------:|--------:|:--------|-----:|
| gross                |   -0.0458 | -0.7918 | nan     | 1639 |
| net of costs         |   -0.5458 | -9.4433 | ***     | 1639 |
| round-trip cost      |   -0.5    |         | nan     | 1639 |
| net, accuracy a=0.60 |   -0.5092 |         | nan     | 1639 |
| net, accuracy a=0.70 |   -0.5183 |         | nan     | 1639 |
| net, accuracy a=0.80 |   -0.5275 |         | nan     | 1639 |

_Source: `g5_net_table.csv` (6 rows)._

### G5 — capacity (participation-based, NOT measured depth)

|   participation |   median_dv01_per_trade |   total_dv01 |   n_trades_priced |   n_trades_dropped | basis                                                            |
|----------------:|------------------------:|-------------:|------------------:|-------------------:|:-----------------------------------------------------------------|
|            0.01 |                  4274.5 |  9.4019e+06  |              1639 |                  0 | traded-volume sensitivity over (entry, exit], NOT measured depth |
|            0.05 |                 21372.5 |  4.70095e+07 |              1639 |                  0 | traded-volume sensitivity over (entry, exit], NOT measured depth |
|            0.1  |                 42745   |  9.4019e+07  |              1639 |                  0 | traded-volume sensitivity over (entry, exit], NOT measured depth |

_Source: `g5_capacity.csv` (3 rows)._

### Trial ledger — every configuration evaluated, in order

|   trial | label                                        |   cfg_horizon |   cfg_threshold |   res_mean |    res_t | note   | cfg_signal   | cfg_signal_space   | cfg_target   |   cfg_half_life | cfg_weighting   |
|--------:|:---------------------------------------------|--------------:|----------------:|-----------:|---------:|:-------|:-------------|:-------------------|:-------------|----------------:|:----------------|
|       1 | PRIMARY (in-sample)                          |            60 |               1 |     -0.546 |   -9.443 |        | nan          | nan                | nan          |                 | nan             |
|       2 | LABEL-FREE (unsigned intensity, FUTURES)     |            60 |               1 |     -0.64  |   -9.034 |        | intensity    | nan                | nan          |                 | nan             |
|       3 | FUTURES->FUTURES|hl30|expected|h5            |             5 |                 |     -0.497 |  -76.843 |        | nan          | FUTURES            | FUTURES      |              30 | expected        |
|       4 | FUTURES->FUTURES|hl30|expected|h15           |            15 |                 |     -0.482 |  -26.163 |        | nan          | FUTURES            | FUTURES      |              30 | expected        |
|       5 | FUTURES->FUTURES|hl30|expected|h30           |            30 |                 |     -0.472 |  -12.7   |        | nan          | FUTURES            | FUTURES      |              30 | expected        |
|       6 | FUTURES->FUTURES|hl30|expected|h60           |            60 |                 |     -0.505 |   -7.268 |        | nan          | FUTURES            | FUTURES      |              30 | expected        |
|       7 | FUTURES->FUTURES|hl30|expected|h240          |           240 |                 |     -0.542 |   -2.79  |        | nan          | FUTURES            | FUTURES      |              30 | expected        |
|       8 | FUTURES->FUTURES|hl30|expected|h1440         |          1440 |                 |     -0.427 |   -1.141 |        | nan          | FUTURES            | FUTURES      |              30 | expected        |
|       9 | FUTURES->FUTURES|hl30|unweighted|h5          |             5 |                 |     -0.495 |  -74.743 |        | nan          | FUTURES            | FUTURES      |              30 | unweighted      |
|      10 | FUTURES->FUTURES|hl30|unweighted|h15         |            15 |                 |     -0.481 |  -28.506 |        | nan          | FUTURES            | FUTURES      |              30 | unweighted      |
|      11 | FUTURES->FUTURES|hl30|unweighted|h30         |            30 |                 |     -0.462 |  -12.649 |        | nan          | FUTURES            | FUTURES      |              30 | unweighted      |
|      12 | FUTURES->FUTURES|hl30|unweighted|h60         |            60 |                 |     -0.552 |   -9.546 |        | nan          | FUTURES            | FUTURES      |              30 | unweighted      |
|      13 | FUTURES->FUTURES|hl30|unweighted|h240        |           240 |                 |     -0.637 |   -3.643 |        | nan          | FUTURES            | FUTURES      |              30 | unweighted      |
|      14 | FUTURES->FUTURES|hl30|unweighted|h1440       |          1440 |                 |     -0.519 |   -1.301 |        | nan          | FUTURES            | FUTURES      |              30 | unweighted      |
|      15 | FUTURES->FUTURES|hl90|expected|h5            |             5 |                 |     -0.502 |  -94.645 |        | nan          | FUTURES            | FUTURES      |              90 | expected        |
|      16 | FUTURES->FUTURES|hl90|expected|h15           |            15 |                 |     -0.514 |  -33.067 |        | nan          | FUTURES            | FUTURES      |              90 | expected        |
|      17 | FUTURES->FUTURES|hl90|expected|h30           |            30 |                 |     -0.532 |  -17.452 |        | nan          | FUTURES            | FUTURES      |              90 | expected        |
|      18 | FUTURES->FUTURES|hl90|expected|h60           |            60 |                 |     -0.546 |   -9.443 |        | nan          | FUTURES            | FUTURES      |              90 | expected        |
|      19 | FUTURES->FUTURES|hl90|expected|h240          |           240 |                 |     -0.621 |   -2.928 |        | nan          | FUTURES            | FUTURES      |              90 | expected        |
|      20 | FUTURES->FUTURES|hl90|expected|h1440         |          1440 |                 |     -0.824 |   -2.45  |        | nan          | FUTURES            | FUTURES      |              90 | expected        |
|      21 | FUTURES->FUTURES|hl90|unweighted|h5          |             5 |                 |     -0.501 |  -99.417 |        | nan          | FUTURES            | FUTURES      |              90 | unweighted      |
|      22 | FUTURES->FUTURES|hl90|unweighted|h15         |            15 |                 |     -0.512 |  -35.171 |        | nan          | FUTURES            | FUTURES      |              90 | unweighted      |
|      23 | FUTURES->FUTURES|hl90|unweighted|h30         |            30 |                 |     -0.54  |  -19.074 |        | nan          | FUTURES            | FUTURES      |              90 | unweighted      |
|      24 | FUTURES->FUTURES|hl90|unweighted|h60         |            60 |                 |     -0.611 |  -10.809 |        | nan          | FUTURES            | FUTURES      |              90 | unweighted      |
|      25 | FUTURES->FUTURES|hl90|unweighted|h240        |           240 |                 |     -0.671 |   -3.156 |        | nan          | FUTURES            | FUTURES      |              90 | unweighted      |
|      26 | FUTURES->FUTURES|hl90|unweighted|h1440       |          1440 |                 |     -0.693 |   -1.96  |        | nan          | FUTURES            | FUTURES      |              90 | unweighted      |
|      27 | FUTURES->FUTURES|hl240|expected|h5           |             5 |                 |     -0.503 | -110.495 |        | nan          | FUTURES            | FUTURES      |             240 | expected        |
|      28 | FUTURES->FUTURES|hl240|expected|h15          |            15 |                 |     -0.51  |  -37.333 |        | nan          | FUTURES            | FUTURES      |             240 | expected        |
|      29 | FUTURES->FUTURES|hl240|expected|h30          |            30 |                 |     -0.518 |  -19.083 |        | nan          | FUTURES            | FUTURES      |             240 | expected        |
|      30 | FUTURES->FUTURES|hl240|expected|h60          |            60 |                 |     -0.526 |   -8.889 |        | nan          | FUTURES            | FUTURES      |             240 | expected        |
|      31 | FUTURES->FUTURES|hl240|expected|h240         |           240 |                 |     -0.522 |   -2.074 |        | nan          | FUTURES            | FUTURES      |             240 | expected        |
|      32 | FUTURES->FUTURES|hl240|expected|h1440        |          1440 |                 |     -0.884 |   -2.357 |        | nan          | FUTURES            | FUTURES      |             240 | expected        |
|      33 | FUTURES->FUTURES|hl240|unweighted|h5         |             5 |                 |     -0.501 | -111.634 |        | nan          | FUTURES            | FUTURES      |             240 | unweighted      |
|      34 | FUTURES->FUTURES|hl240|unweighted|h15        |            15 |                 |     -0.505 |  -38.007 |        | nan          | FUTURES            | FUTURES      |             240 | unweighted      |
|      35 | FUTURES->FUTURES|hl240|unweighted|h30        |            30 |                 |     -0.522 |  -19.824 |        | nan          | FUTURES            | FUTURES      |             240 | unweighted      |
|      36 | FUTURES->FUTURES|hl240|unweighted|h60        |            60 |                 |     -0.561 |  -10.021 |        | nan          | FUTURES            | FUTURES      |             240 | unweighted      |
|      37 | FUTURES->FUTURES|hl240|unweighted|h240       |           240 |                 |     -0.678 |   -2.916 |        | nan          | FUTURES            | FUTURES      |             240 | unweighted      |
|      38 | FUTURES->FUTURES|hl240|unweighted|h1440      |          1440 |                 |     -0.858 |   -2.38  |        | nan          | FUTURES            | FUTURES      |             240 | unweighted      |
|      39 | FUTURES->FUTURES|hl1440|expected|h5          |             5 |                 |     -0.505 | -122.615 |        | nan          | FUTURES            | FUTURES      |            1440 | expected        |
|      40 | FUTURES->FUTURES|hl1440|expected|h15         |            15 |                 |     -0.514 |  -39.31  |        | nan          | FUTURES            | FUTURES      |            1440 | expected        |
|      41 | FUTURES->FUTURES|hl1440|expected|h30         |            30 |                 |     -0.534 |  -19.358 |        | nan          | FUTURES            | FUTURES      |            1440 | expected        |
|      42 | FUTURES->FUTURES|hl1440|expected|h60         |            60 |                 |     -0.576 |   -9.257 |        | nan          | FUTURES            | FUTURES      |            1440 | expected        |
|      43 | FUTURES->FUTURES|hl1440|expected|h240        |           240 |                 |     -0.691 |   -2.438 |        | nan          | FUTURES            | FUTURES      |            1440 | expected        |
|      44 | FUTURES->FUTURES|hl1440|expected|h1440       |          1440 |                 |     -0.61  |   -1.102 |        | nan          | FUTURES            | FUTURES      |            1440 | expected        |
|      45 | FUTURES->FUTURES|hl1440|unweighted|h5        |             5 |                 |     -0.504 | -123.647 |        | nan          | FUTURES            | FUTURES      |            1440 | unweighted      |
|      46 | FUTURES->FUTURES|hl1440|unweighted|h15       |            15 |                 |     -0.514 |  -41.511 |        | nan          | FUTURES            | FUTURES      |            1440 | unweighted      |
|      47 | FUTURES->FUTURES|hl1440|unweighted|h30       |            30 |                 |     -0.535 |  -20.692 |        | nan          | FUTURES            | FUTURES      |            1440 | unweighted      |
|      48 | FUTURES->FUTURES|hl1440|unweighted|h60       |            60 |                 |     -0.582 |  -10.475 |        | nan          | FUTURES            | FUTURES      |            1440 | unweighted      |
|      49 | FUTURES->FUTURES|hl1440|unweighted|h240      |           240 |                 |     -0.776 |   -2.763 |        | nan          | FUTURES            | FUTURES      |            1440 | unweighted      |
|      50 | FUTURES->FUTURES|hl1440|unweighted|h1440     |          1440 |                 |     -0.691 |   -1.254 |        | nan          | FUTURES            | FUTURES      |            1440 | unweighted      |
|      51 | FED_FUNDS->FED_FUNDS|hl30|expected|h5        |             5 |                 |     -0.5   | -218.866 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | expected        |
|      52 | FED_FUNDS->FED_FUNDS|hl30|expected|h15       |            15 |                 |     -0.501 |  -81.661 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | expected        |
|      53 | FED_FUNDS->FED_FUNDS|hl30|expected|h30       |            30 |                 |     -0.505 |  -46.477 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | expected        |
|      54 | FED_FUNDS->FED_FUNDS|hl30|expected|h60       |            60 |                 |     -0.517 |  -30.262 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | expected        |
|      55 | FED_FUNDS->FED_FUNDS|hl30|expected|h240      |           240 |                 |     -0.557 |   -9.276 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | expected        |
|      56 | FED_FUNDS->FED_FUNDS|hl30|expected|h1440     |          1440 |                 |     -0.385 |   -3.926 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | expected        |
|      57 | FED_FUNDS->FED_FUNDS|hl30|unweighted|h5      |             5 |                 |     -0.499 | -234.76  |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | unweighted      |
|      58 | FED_FUNDS->FED_FUNDS|hl30|unweighted|h15     |            15 |                 |     -0.499 |  -84.035 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | unweighted      |
|      59 | FED_FUNDS->FED_FUNDS|hl30|unweighted|h30     |            30 |                 |     -0.5   |  -47.517 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | unweighted      |
|      60 | FED_FUNDS->FED_FUNDS|hl30|unweighted|h60     |            60 |                 |     -0.508 |  -31.661 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | unweighted      |
|      61 | FED_FUNDS->FED_FUNDS|hl30|unweighted|h240    |           240 |                 |     -0.55  |   -8.989 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | unweighted      |
|      62 | FED_FUNDS->FED_FUNDS|hl30|unweighted|h1440   |          1440 |                 |     -0.375 |   -4.515 |        | nan          | FED_FUNDS          | FED_FUNDS    |              30 | unweighted      |
|      63 | FED_FUNDS->FED_FUNDS|hl90|expected|h5        |             5 |                 |     -0.501 | -272.988 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | expected        |
|      64 | FED_FUNDS->FED_FUNDS|hl90|expected|h15       |            15 |                 |     -0.505 | -100.668 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | expected        |
|      65 | FED_FUNDS->FED_FUNDS|hl90|expected|h30       |            30 |                 |     -0.513 |  -54.161 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | expected        |
|      66 | FED_FUNDS->FED_FUNDS|hl90|expected|h60       |            60 |                 |     -0.531 |  -30.195 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | expected        |
|      67 | FED_FUNDS->FED_FUNDS|hl90|expected|h240      |           240 |                 |     -0.588 |   -9.357 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | expected        |
|      68 | FED_FUNDS->FED_FUNDS|hl90|expected|h1440     |          1440 |                 |     -0.558 |   -5.898 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | expected        |
|      69 | FED_FUNDS->FED_FUNDS|hl90|unweighted|h5      |             5 |                 |     -0.501 | -273.46  |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | unweighted      |
|      70 | FED_FUNDS->FED_FUNDS|hl90|unweighted|h15     |            15 |                 |     -0.503 |  -99.27  |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | unweighted      |
|      71 | FED_FUNDS->FED_FUNDS|hl90|unweighted|h30     |            30 |                 |     -0.506 |  -51.199 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | unweighted      |
|      72 | FED_FUNDS->FED_FUNDS|hl90|unweighted|h60     |            60 |                 |     -0.514 |  -31.055 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | unweighted      |
|      73 | FED_FUNDS->FED_FUNDS|hl90|unweighted|h240    |           240 |                 |     -0.585 |   -8.866 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | unweighted      |
|      74 | FED_FUNDS->FED_FUNDS|hl90|unweighted|h1440   |          1440 |                 |     -0.558 |   -5.662 |        | nan          | FED_FUNDS          | FED_FUNDS    |              90 | unweighted      |
|      75 | FED_FUNDS->FED_FUNDS|hl240|expected|h5       |             5 |                 |     -0.501 | -323.838 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | expected        |
|      76 | FED_FUNDS->FED_FUNDS|hl240|expected|h15      |            15 |                 |     -0.505 | -110.514 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | expected        |
|      77 | FED_FUNDS->FED_FUNDS|hl240|expected|h30      |            30 |                 |     -0.513 |  -63.528 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | expected        |
|      78 | FED_FUNDS->FED_FUNDS|hl240|expected|h60      |            60 |                 |     -0.526 |  -29.186 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | expected        |
|      79 | FED_FUNDS->FED_FUNDS|hl240|expected|h240     |           240 |                 |     -0.641 |   -9.901 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | expected        |
|      80 | FED_FUNDS->FED_FUNDS|hl240|expected|h1440    |          1440 |                 |     -0.538 |   -5.631 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | expected        |
|      81 | FED_FUNDS->FED_FUNDS|hl240|unweighted|h5     |             5 |                 |     -0.501 | -325.099 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | unweighted      |
|      82 | FED_FUNDS->FED_FUNDS|hl240|unweighted|h15    |            15 |                 |     -0.503 | -111.708 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | unweighted      |
|      83 | FED_FUNDS->FED_FUNDS|hl240|unweighted|h30    |            30 |                 |     -0.511 |  -60.298 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | unweighted      |
|      84 | FED_FUNDS->FED_FUNDS|hl240|unweighted|h60    |            60 |                 |     -0.531 |  -30.641 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | unweighted      |
|      85 | FED_FUNDS->FED_FUNDS|hl240|unweighted|h240   |           240 |                 |     -0.622 |   -9.908 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | unweighted      |
|      86 | FED_FUNDS->FED_FUNDS|hl240|unweighted|h1440  |          1440 |                 |     -0.463 |   -4.148 |        | nan          | FED_FUNDS          | FED_FUNDS    |             240 | unweighted      |
|      87 | FED_FUNDS->FED_FUNDS|hl1440|expected|h5      |             5 |                 |     -0.5   | -405.24  |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | expected        |
|      88 | FED_FUNDS->FED_FUNDS|hl1440|expected|h15     |            15 |                 |     -0.5   | -131.391 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | expected        |
|      89 | FED_FUNDS->FED_FUNDS|hl1440|expected|h30     |            30 |                 |     -0.503 |  -68.277 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | expected        |
|      90 | FED_FUNDS->FED_FUNDS|hl1440|expected|h60     |            60 |                 |     -0.506 |  -33.795 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | expected        |
|      91 | FED_FUNDS->FED_FUNDS|hl1440|expected|h240    |           240 |                 |     -0.574 |   -7.597 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | expected        |
|      92 | FED_FUNDS->FED_FUNDS|hl1440|expected|h1440   |          1440 |                 |     -0.426 |   -4.138 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | expected        |
|      93 | FED_FUNDS->FED_FUNDS|hl1440|unweighted|h5    |             5 |                 |     -0.5   | -421.007 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | unweighted      |
|      94 | FED_FUNDS->FED_FUNDS|hl1440|unweighted|h15   |            15 |                 |     -0.5   | -132.294 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | unweighted      |
|      95 | FED_FUNDS->FED_FUNDS|hl1440|unweighted|h30   |            30 |                 |     -0.503 |  -67.651 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | unweighted      |
|      96 | FED_FUNDS->FED_FUNDS|hl1440|unweighted|h60   |            60 |                 |     -0.513 |  -36.135 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | unweighted      |
|      97 | FED_FUNDS->FED_FUNDS|hl1440|unweighted|h240  |           240 |                 |     -0.573 |   -7.606 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | unweighted      |
|      98 | FED_FUNDS->FED_FUNDS|hl1440|unweighted|h1440 |          1440 |                 |     -0.448 |   -4.294 |        | nan          | FED_FUNDS          | FED_FUNDS    |            1440 | unweighted      |

_Source: `trial_ledger.csv` (98 rows)._

<!-- END GENERATED TABLES -->
