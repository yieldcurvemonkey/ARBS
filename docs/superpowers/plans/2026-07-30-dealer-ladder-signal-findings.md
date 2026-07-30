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

### G0 — Labels and provenance
_pending_

### G1 — Arrival integrity
_pending_

### G2 — Mechanism ordering (runs before any price test)
_pending_

### G3 — Circularity battery
_pending_

### G4 — Pre-registered price prediction
_pending_

### G5 — Economics and capacity
_pending_

---

## 8. Limitations, stated before the results

Every item here was established by measurement during construction, not inferred afterwards, and
each one bounds what the verdict can say. They are listed now so they cannot be mistaken for
excuses added after seeing a number.

### 8.1 The direction label is uncertified, and curve disagreement is the same size as the signal

No truth labels exist — no desk tickets or confirmations were available — so **no accuracy number
is claimed anywhere**. The G0 pseudo-label study is the substitute: the *identical* classifier
re-run against an independent Citi Velocity intraday SOFR mid, so a flip isolates curve
disagreement rather than a difference of rule.

The scale of the problem, **measured on two months and replicated across them**. These are
preliminary runs of the same `labels.flip_study` the gate uses, reported here because they are
limitations established by measurement; the full-window version is the real G0. February is
*provisional* — the projection phase was still running, so 15 of its sessions were available.

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
Consistently, the flip rate collapses to **12.2%** in the top quintile of `|spread-to-mid|`
(median 3.88 bp) — a trade that printed four basis points from mid is unambiguous whichever curve
you hold. So this is not label noise to be averaged away; it is a mechanism with a closed form,
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
this failure, however much it looks like one. And CURVE_SUSPECT prints flip **less** than CURVE_CLEAN ones
(28.2% vs 35.7%) — not an inversion of the gate's quality, but an artefact of what it selects on:
suspect prints sit far from mid (mean `|s2m|` 4.73 bp against 0.49 bp) and far-from-mid prints
survive a half-bp disagreement.

That is the audit's first kill risk, and it is live and quantified rather than argued.

Every signed result therefore carries the `(2a − 1)` attenuation grid, and G0's flip rate is
reported as what it is: a **lower bound on disagreement-driven error, not an accuracy**. Both
curves can be wrong together, and a flip does not say which one was right.

With a 34.9% disagreement rate overall — 40.8% on the curve-clean stratum the study actually
trades — and no truth label, if each mid is right half the time where they disagree then direction
accuracy is bounded above by **79.6%** and the signed exposure retains at most **~0.59**. The pre-registered grid {0.6, 0.7, 0.8} brackets that. That is luck
rather than foresight — the grid was fixed before this was measured — but it means the grid does
not move, which is the only thing that matters now that the lockout rule is in force.

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

### 8.4 Scope reductions taken deliberately

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

### 8.5 Power

Independent observations are set by the signal's integration window, not the number of minute
bars: ≈150 independent score epochs in-sample at a 90-minute half-life, ≈56 at 240. At that scale
the 80%-power minimum detectable standardised effect is ≈0.25 for a single test. **This study can
decisively reject a large, obvious effect. It cannot establish that a small one is durable,
causal, or capacity-bearing**, and no claim of that kind will be made from it.

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

_pending — run the gates, then `scripts/dealer_ladder_completeness.py --inject <this file>`._

<!-- END GENERATED COMPLETENESS -->

---

## 10. Every artifact, verbatim

Generated by `scripts/render_findings_tables.py` from the CSVs the gates wrote, with a source
filename under each table. Nothing here is transcribed: a hand-copied number cannot be checked
against the run that produced it, and a transcription slip is indistinguishable from a result. A
gate that produced no artifact says so loudly, because an absent table must never read as a passing
gate.

<!-- BEGIN GENERATED TABLES -->

_pending — run the gates, then `scripts/render_findings_tables.py --inject <this file>`._

<!-- END GENERATED TABLES -->
