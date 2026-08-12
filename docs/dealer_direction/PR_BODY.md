# Dealer direction inference on the USD swap SDR tape

Per-trade direction with a calibrated probability, a signed key-rate DV01
profile, and the aggregated dealer risk ladder. Plus the two things that turned
out to matter more than the feature: a measurement that invalidates the labels
every prior conclusion in this programme rested on, and a pre-registered test
that closed the intraday premise.

**Not for merge.** Opened for review.

---

## Read this first, even if you read nothing else

**The existing short-end classifier's labels are ~78% one-directional because of
a curve error, not because of flow.**

The Barchart `Q12xM12STIRT` mid it prices against runs about **0.5 bp high** with
roughly **7x the dispersion** of the Citi minute curve. Four independent controls
inside its own output identify the instrument rather than the market:

| control | Barchart | Citi minute |
|---|---|---|
| % of prints above mid | **21.70%** | 55.5% |
| median deviation | **−0.4836 bp** | +0.021 bp |
| within ±0.1 bp | **5.43%** | 40.5% |

- the bias grows **monotonically with tenor** — 3M −0.136 to 3Y −1.237 bp, the
  shape of uncorrected futures→forward convexity on a STIR-futures-built curve;
- **`FLY_VS_MID` cancels it exactly**: median 0.0000 bp, 198 PAID / 194 RECEIVED,
  while `RATE_VS_MID` sits at −0.484 and 78% PAID;
- **`TICK_RULE` — the only method that never touches a curve — is balanced
  53/47**, while every curve-using method is 69–78% PAID;
- IMM buckets are broken outright: `IMM_2Y` median **−6.84 bp**.

A classifier that one-sided cannot produce a meaningful inventory series; the
integral is a drift term plus noise. **So the dealer-ladder programme's "no
signal" verdict is uninformative, not null.** It was never really tested. That
finding is independent of anything else here and is the single most important
line in this PR.

The new pipeline prices against the Citi minute curve, where the same statistic
is clean: median +0.021 bp, bootstrap 95% CI **[−0.0015, +0.0463]** (includes
zero), no tenor gradient, and a 7-days-earlier placebo giving **48.8x** the
dispersion.

---

## What is built

`SDRUtils/dealer_direction/` — 17 modules, **~1,090 tests**. Each was built
against pinned interfaces, then adversarially reviewed by a second agent that
mutation-tested it, then fixed, then independently verified.

| module | what it does |
|---|---|
| `conventions` | the sign convention, base orientations, quote weights |
| `types` | the data contract: `Clocks`, `Unit`, `UnitPricing`, `DirectionCall`, `Provenance` |
| `snapshot` | the pricing clock and the session-branched snapshot policy |
| `universe` / `sanity` | unit construction, filters, venue, the risk-plausibility gate |
| `midprice` | repricing against the Citi minute curve, two-pricer session branch |
| `probability` | the mixture fit, `tau`, `p`, the dead zone |
| `upfront` | the edge-capture rule, made probabilistic |
| `package_price` | orienting a `PKG-N` from its own package price |
| `krd` | signed key-rate DV01 via rateslib's own delta ladder |
| `ladder` / `indicator` | aggregation and the daily positioning series |
| `provenance` / `health` | per-row audit trail and the monitors |
| `imputation` | capped-notional tail model |
| `lineage` | the unwind sidecar from raw DTCC slices |

### The convention, pinned

```
customer pays fixed -> dealer RECEIVED fixed -> dealer long duration -> delta_dv01 > 0
p = p(customer paid fixed);  ladder weight = signed_weight(p) = 2p - 1
```

Inherited unchanged from `stir_flow` so the tie-out means something. **The first
draft of `dealer_received_signs` inverted every leg of every structure at once**
— going from the base party to the dealer is one negation and going from
pay-polarity to received-polarity is a second, and two negations are the
identity. It produced a completely plausible result and was caught only by the
frozen-predecessor test. That is why that test exists.

---

## The design, and what was rejected

Full reasoning in `docs/dealer_direction/DESIGN.md`. The decisions that changed
the brief:

### `tau` is `s²/(2h)`, not the half-spread

The brief specifies `p = sigma((rate − mid)/tau)` with `tau ≈ the half-spread`.
The functional form is right; the identification is not. Modelling
`x | paid ~ N(b0 + h, s²)` and `x | received ~ N(b0 − h, s²)` gives exactly a
logistic with **`tau = s²/(2h)`** — the mid-measurement variance over twice the
half-spread. Two consequences the half-spread reading inverts: a **wide**-spread
bucket is *more* decidable, not less; and mid quality enters **quadratically**,
which is why the curve work was the blocker and why a per-bucket bias term must
be fitted rather than assumed away.

### The ladder weights `2p − 1`, not `p`

At `p = 0.5`, a `p`-weighted contribution is **half a long position**, not a coin
flip. `E[side] = 2p − 1` is zero at 0.5, which is what "contributes
proportionally rather than as a coin flip" has to mean to be true.

### The upfront rule as briefed is not decidable, and naive edge-capture is not identified

`#58 Other payment amount` is disseminated as "any value >= 0"; **`#61 payer` and
`#62 receiver` are not disseminated at all**. And with the fee sign free, *both*
direction hypotheses can always be made to imply non-negative dealer edge. What
closes it is that **the fee flows from the party receiving value**, which ties
the fee sign to the hypothesis — and that reproduces exactly what
`stir_flow/classifier.py:75-82` already implements. The brief asked for a second
solver; the right answer was that the existing hard rule is correct and needed
only a probability.

### One inferred bit per unit, not a direction per leg

A package has one price. Each unit gets a base orientation and quote weights
chosen so `P` is the price the base party pays; then `P_traded > P_mid` means the
base party overpaid and is therefore the customer, and **the whole signed
key-rate vector follows from that single bit**. There is no direction to name for
a 17-leg package.

### Options rejected

| option | why |
|---|---|
| `tau` = the half-spread, as briefed | derivation gives `s²/(2h)`; the brief's reading inverts the comparative static in `h` |
| a hard dead zone as the only marginal-call handling | `(2p−1)` sends a coin flip to zero automatically |
| a second other-payment sign solver | `opa_sign` is **direction-blind by symmetry** (a sign vector and its complement score identically) and `dealer_spread_est` is a dollar residual, always non-negative, carrying no directional information |
| adding a lineage column to the tape | 610 prod days delete-and-rewrite, for a flip that measurement showed is mostly not needed |
| `event_timestamp` as the availability clock, as briefed | measured p90 lag = **0**; it is not a bound |
| routing on `is_off_market` | it is a rate-outlier heuristic that disagrees with upfront presence on **524k legs** |
| a hand-rolled analytic KRD | instructed against; rateslib's delta is risk to the calibrating instruments, so the bucket set *is* the instrument set |
| PCA to reduce the ladder | unstable out of sample, and a PC bucket is not hedgeable with one instrument |
| leg-by-leg classification with a vote | confident nonsense on curves and flies |

---

## What the tape actually said, against the brief

Every one of these was assumed in the brief and measured otherwise.

- **`#96` is frozen on a lifecycle print.** Appendix F Example 3 shows a
  `TERM-ETRM` row carrying event timestamp 2019-12-12 against execution
  timestamp 2018-04-01 — **twenty months stale**. Confirmed on live data: for the
  613 raw terminations that resolve, the termination's own execution timestamp
  equals the *original's* to under a second in **95.3%** of cases. So rows that
  mint a new UTI price on `#96` and everything else prices on `#30`.
- **A lookahead guard caught 167 of 4,329 legs (3.9%)** being priced on a curve
  up to an hour *after* their own print — arriving through a **sort key**.
- **The 36,763 `ECONOMIC_UNWIND` rows are `lifecycle_type = NEW_TRADE`**, all
  past-effective: the unwind-as-offsetting-trade signature. 97% land in
  2024-03..07, after which the detector stops and `TERMINATION` starts — an
  ingest regime change, not a market one. **Pre-2024-07 tape has no termination
  events at all.**
- **IMM is not a standard coupon** (upfront present *less* often than outrights,
  37.7% vs 40.9%); **MAC is the cleanest upfront-rule population on the tape**
  (98.85% carry a fee) and was re-included.
- **`NEWT-EXER` / `NEWT-NOVA` cannot be excluded**: the flags are literally
  `false` on all 2,326,781 rows. **~3.1% unremovable contamination.** The gate is
  wired and pinned by a synthetic test so it starts working the day the
  enrichment does.
- **Term SOFR was leaking**: 32,842 flow legs carry the CME Term label while
  `rate_index_clean` reads SOFR, so `USD-SOFR-1D` would have priced them.
- **The "corrupt" rows are the spec's own sentinel** — `notional = 1e20` is
  field #31's documented "value not available", not corruption.
- **My own multi-hop lineage claim did not reproduce**: "43 TERM→TERM pointers"
  was **193 self-pointers of 197**, `max_hops = 1`, and the transitive walk
  resolves zero rows a single hop would miss.

---

## What it can and cannot support

`docs/dealer_direction/WHAT_THE_LADDER_SUPPORTS.md` is the consumer note. The two
limits that decide how it can be read:

**Cross-sectional levels are not available.** DV01 retention runs **0.761 at
0–1Y to 0.495 at 15–20Y**, a **1.54x distortion**, because the packages the
classifier cannot orient are not a random sample — they are **97.9% D2C** against
82.1% retained, with **28.7% of their DV01 in blocks** against 11.1%. So *"the 5y
bucket against its own history"* is supportable and *"dealers are longer 5y than
10y"* is not. **Enforced in the API, not a docstring** — the level column is
bucket-suffixed, the all-bucket frame carries no level, and the cross-section
accessors raise.

**What is available cross-bucket is `z`**, because **`z` is exactly invariant to
a constant retention factor**. That is the spine of the retarget.

**The recovery route was tried and mostly failed.** Orienting a `PKG-N` against
its own package price recovers **0.93 pp** — retention **56.96% → 57.89%**, not
the 79.12% I projected. **64.2% of PKG-4+ DV01 is genuinely unidentifiable**:
several mutually inconsistent sign vectors reconcile the fees inside the same
tolerance. The discriminating statistic is the **margin to the next distinct sign
class**, and the control that proves it is the right one is that match rate rises
**45% → 99%** across margin bands while being **flat** across tie-out bands — and
the tie-out is what the module originally gated on. Ambiguity is structural:
**61.45% at four legs, 97.25% at eight or more.**

---

## R0 — the intraday premise, closed

Separate branch **`r0-leadlag`** (deliberately isolated: it must not depend on
the thing it evaluates), 8 commits, its own PR.

Pre-registered before any data was touched, with the decision rule, the sign of
the prediction, and the conditions that would make it *uninformative rather than
negative* all fixed in advance. Commit order is checkable: prereg → addendum →
result → correction.

- **R0**: post-print mass indistinguishable from zero on both clocks
  (`t = +0.59`); mass sits *before* dissemination where the measured 4.70 min
  publication lag predicts. Five of five buckets agree.
- **D1** then downgraded that FAIL to **UNINFORMATIVE** — `rho = 0.405`, so the
  null did not have the power to be a null.
- **R0b**, the one authorized re-run with a curve-based input: **FAIL**, with the
  post-print 95% interval **(−0.0188, +0.0165)** — the hedge channel R0 could not
  exclude is now excluded, at 2.4–13.6x the power.
- **R0's pre-print trough was an artifact of its own mid rule.** The clincher:
  R0b's execution clock carries significant **positive** pre-print mass where
  R0's was negative. **Each mid rule manufactures pre-print mass with the sign
  its own staleness direction implies.**

Consequence, applied here: the intraday hedge-trigger and max-pain components are
**dropped**; the output is a **daily** street-positioning indicator.

---

## Signal search — both hypotheses fail

`docs/dealer_direction/signals/` — pre-registered with the cost hurdle measured
**first** and a kill rule (in-sample edge below 2x cost means the hold-out is
never opened). It never was.

- **S1** (swap-spread flow → swap spread): **DEAD.** Zero significant cells,
  largest |t| **1.66**; best edge anywhere **0.174 bp at 20Y k=5 against its own
  1.332 bp hurdle, 7.7x short**.
- **S2** (positioning → reversal): **UNINFORMATIVE.** Pooled `t = +0.04`, edge
  **−0.32 bp**.
- **`S_DEVIATIONS.md` records a sign error in my own pre-registration** (S1's
  predicted direction is inverted) and withdraws S2's "powered null" claim on
  three independent grounds.

**What stopped a false positive**: the mixture fit *refused* to resolve `h` on
**all 21** spreadover buckets (separation 0.013–0.050; the 14 quoted earlier are
the non-`ALL` subset), and validation showed it is biased **−80% downward**
below its own separation gate. Without that gate, `2h` would have argued the cost
**down by 5–20x** and both hypotheses would have "cleared". The gate was written
first.

---

## Unfinished, stated plainly

- **`PKG_OPA_MISSING` — 4.38 pp of tape DV01, 81,124 legs** with no fee to
  reconcile. Their `|f|` still belongs in the package value, so they cannot
  simply be dropped. The largest remaining prize.
- **`PKG_TIEOUT_FAIL` — 1.25 pp, genuinely unreconcilable**: 11.3% of PKG-4+ have
  `|PTP| > sum|OPA|`, which no signed sum of the fees can reach.
- **Recovered packages have a sign but no `p`**, so they cannot be
  probability-weighted into the ladder until a package `tau` is fitted. **57.89%
  is universe retention, not ladder coverage.**
- **Asset swaps (17.41 pp) were not attempted** — the bond is identified
  (`ust_cusip` on 48%) but not priced on this tape.
- **`build_universe` is ~30 min for the full tape** and annotates twice.
- **The coverage adjustment uses a full-sample mean**, so the adjusted level
  restates as history extends. That is lookahead in a published series; it is
  documented rather than fixed, and I would make it trailing.
- **The tape's own `lc_*` cross-day enrichment is empty** across all 2.33M rows —
  a v3 defect reported here, not fixed.
- **No backtest.** Deliberately.

---

## The research notebook

`notebooks/dealer_direction/dealer_direction_showcase.ipynb` — **78 cells,
executed, outputs stored, 0 errors, 14 inline figures.** Reads the tape
read-only and writes its own artefacts. It traces one real print end to end
(snapped instant → curve → mid → deviation → `tau` → `p` → `signed_weight` →
dealer side → per-leg signs → the 28-pillar KRD), then the universe, the three
rules, the risk buckets, the positioning series, and the regression studies.

Underneath it, `dd_nb.py` is a tested pipeline — 45/45 self-test, and validated
against `s2_positioning.py`'s own cached build of the same three days: 4,806
shared units with `deviation_bps` / `npv_pay` / `structure_dv01` / `gross_pv01`
**bit-identical at max |diff| 0.000e+00**.

**The review of it is worth reading as much as the notebook.** It confirmed the
notebook ran clean and its numbers were right — and that it was **lying about
which of them it had computed**. Three stages were served from a content-keyed
stage cache, and the calibration setting `tau` on every one of 4,938 calls was
unpickled from outside the repo, while every banner said `COMPUTED`. It also
caught two display defects that taught an **inverted sign**: the centrepiece
printed a raw decimal with a `%` appended (`fixed 0.037880%` for a 3.788% swap,
so forming the deviation off the displayed line gave −362 bp and *dealer PAID*
against the +13.096 bp and *dealer RECEIVED* four lines below), and a canned
sentence asserted `delta_dv01 > 0` for a package whose net the same cell
computed as **−5,243.5 USD/bp**.

All fixed, with runtime asserts that fail in both directions. The fixes are
labelling only: all 14 figures are byte-identical afterwards and no headline
number moved.

**It also corrected three numbers in these documents** — the best S1 edge, the
spreadover bucket count, and the "convention-dependent for 11 of 35 cells"
claim, which is **0 of 35**.

---

## The tie-out — passes exactly

`docs/dealer_direction/2026-08-12-tieout.md`. D11's two measurements, each
varying one thing.

**Logic tie-out** (same curve, same instants, old code → new): **100.0000%**
agreement on old-HIGH decisive rows, **100.0000%** on all decisive rows,
**κ = 1.000000**, and **zero unexplained residue**. All 2,675 disagreements are
`OLD_TICK_RULE` — a rule the new package does not implement, agreeing at 51.7%,
a coin flip, exactly as the curve finding predicts for the one curve-blind
method. Every stratum was measured, not just the decisive one:
`CURVE_SUSPECT` (12,728), `KNIFE_EDGE` (4,089) and `NEW_ABSTAIN` (11,238) are
each 100.0000% at κ = 1.000.

The convincing number is not the agreement rate. It is **max
|s2m_old − dev_new| = 8.9e-14 bp** over 29,812 rate-rule rows and **exactly
0.000 USD** on 8,021 upfront NPVs — the residual is `(a−b)*100` against
`a*100−b*100`, not a pricing difference.

**Curve effect** (same code, Barchart → Citi): **74.65% → 55.80% PAID, a 33.92%
label shift, κ = 0.28** — the curve finding quantified, and the reason a single
blended gate would have been meaningless.

Sample 64 of 131 days on a deterministic 2-in-3 stride, stopped by disk rather
than time, and stated as such.

---

## Provenance and discipline

Every substantive claim in `LEDGER.md` carries the measurement behind it. Where a
number was retracted — the 79.12% and 71.92% recovery projections, S2's powered
null, the S1 sign error, my multi-hop lineage claim — **the retraction is in the
tree next to the original**, not a silent edit.

Mutation testing throughout: the recovery module ends at **0 survivors of 38**,
the seams 0 of 26, the indicator **47 of 49** with the two remaining proved
equivalent. Two harnesses were themselves found wrong mid-flight (a stale `.pyc`
serving the previous mutant; a test floor written relative to the constant it
pins) and both are disclosed.
