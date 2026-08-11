# What this ladder can and cannot support

For the consumer. The point of this note is where **not** to trust the output,
which matters more than where to.

Numbers marked `[pilot]` are filled from the pilot run; everything else is
measured during the build and cited in `LEDGER.md`.

---

## 0. Read this first, even if you read nothing else

**The existing short-end classifier's labels are ~78% one-directional because
of a curve error, not because of flow.** The Barchart `Q12xM12STIRT` mid it
prices against runs about **0.5 bp high** with roughly **7× the dispersion** of
the Citi minute curve. On its own output:

- 21.70% of prints land above mid on Barchart, against 55.5% on Citi;
- the bias grows monotonically with tenor — 3M −0.136 bp to 3Y −1.237 bp — which
  is the shape of uncorrected futures→forward convexity on a STIR-futures-built
  curve;
- `FLY_VS_MID` (a second difference) cancels it exactly: median 0.0000 bp,
  198 PAID / 194 RECEIVED;
- `TICK_RULE` — the only method that never touches a curve — is balanced 53/47,
  while **every** curve-using method is 69–78% PAID;
- IMM buckets are broken outright: `IMM_2Y` median −6.84 bp.

Anything previously concluded from `arbs_stir_direction_v1` inherits that. In
particular the dealer-ladder programme's "no signal" verdict was reached on
labels with a half-basis-point one-way bias. That does not make the verdict
wrong, but it does mean it was never really tested.

This note describes the **new** ladder, which prices against the Citi minute
curve. On that curve the same statistic is clean: median (printed − mid)
= +0.021 bp, bootstrap 95% CI [−0.0015, +0.0463] — including zero — with no
tenor gradient, and a 7-days-earlier placebo giving 48.8× the dispersion.

---

## 0b. The intraday use has been tested and retired

A pre-registered lead-lag test (**R0**, branch `r0-leadlag`) asked whether
customer swap flow predicts signed futures aggressor volume *after* the print
becomes public. Post-print mass was indistinguishable from zero on both clocks —
pooled `Σβ_k(k≥1)` = +0.0076, day-clustered **t = +0.59** — while the mass sat
*before* dissemination, where the measured ~4.7 min publication lag predicts.
Five of five buckets agreed.

An attenuation diagnostic then **downgraded that FAIL to UNINFORMATIVE**: the
crude proxy the test was required to use had `rho = 0.405`, so the null did not
have the power to be a null. One authorized re-run with a curve-based input is
in flight. `rho` is a *lower* bound on the attenuation, which cuts toward the
FAIL standing, so the re-run is expected to confirm rather than overturn it.

**Either way the consequence is the same and has been applied:** the intraday
hedge-trigger and max-pain components are **dropped**, and this output is a
**daily** street-positioning indicator. Full result: `r0_leadlag/R0_RESULT.md`.

## 1. What it is

A **flow** series: model-labelled customer-to-dealer risk transfer, per
key-rate bucket, **daily**, stamped on the clock at which each print became
public.

## 2. What it is not

**It is not an inventory.** Compression and allocation are never publicly
reported, so positions that were netted away leave no offsetting print. A
running sum of this series accumulates a monotone, unbounded error. If you want
inventory, you need a decay term or an external reconciliation.

**It is not cross-sectionally comparable.** This is the sharpest limit and it is
new. DV01 retention varies from **0.761 at 0–1Y to 0.495 at 15–20Y** — a
**1.54× cross-bucket scaling distortion** — because the packages the classifier
cannot orient are not a random sample. So:

> **You may read "the 5y bucket against its own history."**
> **You may not read "dealers are longer 5y than 10y."**

The second is exactly what a positioning read wants to say, and it is not
available at 57% retention. The recovery route below is what buys it back.

**The 1–2Y bucket's level is contaminated.** Its exclusion rate drifts at
**+5.07 pp/yr (t = +3.21)**, which moves the level for measurement reasons that
look exactly like information. It is detrended or carries a loud caveat — and it
is the meeting-dated front-end bucket, so this matters more than its share
suggests.

**It is not counterparty-observed.** Direction is inferred from price against a
repriced mid. It is uncertified against any external truth label — there are no
desk tickets behind it.

**It is not a signal.** Two candidate signals are separately pre-registered
(`docs/dealer_direction/signals/S_PREREG.md`) with a hold-out and a cost hurdle
fixed before testing. Nothing here is a backtest.

---

## 3. Where confidence is low

| condition | why | `[pilot]` share |
|---|---|---|
| near mid | the deviation is inside the mid's own measurement error; `2p−1` sends these to ≈0 automatically | |
| beyond the tick lattice (>3y) | no consecutive-print tick to validate the fitted half-spread against; the mixture fit is the only estimator | |
| out-of-session prints (00:xx ET) | Citi publishes nothing 23:00–00:59 ET, so these are served from a curve up to 2 h stale | |
| Fed Funds | the no-bias result was measured on SOFR; FF is where the old curve failed per-meeting | |
| lifecycle prints | the sign is right but is driven by seasoned P&L, not bid-offer, so the confidence model does not transfer | |
| capped notional | the size is imputed, not read | |

---

## 4. Which package types are excluded, and why

**Headline number**: exclusions cost **43.04% of DV01**, of which
`UNORIENTABLE_PKG` alone is **39.97%** (`PKG-4+` 22.6%). That is the single most
expensive line in the design — larger than the entire asset-swap family — and
the reason the recovery route below is the top open item.

| family | treatment | reason |
|---|---|---|
| `PKG-N`, N ≥ 4 | **excluded — recovery in flight** | no market quote convention fixes the base orientation, so forcing one manufactures a confident direction from nothing. But **100% of its DV01 carries a package price or spread**, and orienting the *package* rather than its legs takes retention **56.96% → 79.12%** with the cross-bucket distortion halved (spread 26.65 → 16.73 pp). This is what converts a caveated indicator into a clean one. |
| MAC / IMM standard coupons | | off-market *by construction* rather than by negotiation, so they pollute the off-market population |
| `NEWT-EXER` | | prints at the **strike**, arbitrarily far from mid, with no upfront — so an upfront-presence test calls it on-market and the rate rule returns a large, confident, meaningless deviation (~374/week) |
| `NEWT-NOVA` | | a dealer-to-dealer transfer that would otherwise count as customer flow (~435/week) |
| spreadover / matched-maturity / invoice | | the direction *question* is different, not merely harder: a spreadover's direction is about the **spread**, not the swap rate |
| BASIS / OTHER index | | no curve mapping |
| risk/notional sentinels | | 55 legs carry the spec's own "value not available" placeholder (`notional = 1e20`, `fixed_rate = 9.9`) |

Every excluded unit carries exactly one reason code and its DV01 share is
reported, so the coverage accounting sums.

---

## 5. How much DV01 is imputed rather than observed

Blocks print at the §43.4 cap, so the largest and most informative prints are
exactly the ones whose size cannot be read. 68,946 of 2,289,646 flow legs
(3.01%) are capped.

- Cap schedule: **nine tenor bands, two vintages**, switching **2024-10-07**
  (the CFTC's recalibrated post-initial block-and-cap sizes, matched to the day
  from the data alone).
- Imputation: censored MLE, lognormal, threshold `u = C/4`, which reproduces the
  observed capped count to ±19% in every cell. A truncation-only MLE is off by
  −72% to +2400%.
- `[pilot]` **imputed share of DV01**, per bucket and overall.
- The quoted sensitivity band is **within-lognormal-family only**. Absolute KS
  is 0.07–0.28 for both candidate families, so neither fits well and family risk
  sits outside the band.
- Capped legs are ~5× more likely to have a NULL fixed rate, so the DV01 needing
  imputation sits disproportionately on legs that cannot be direction-classified
  at all.

---

## 6. Known holes that cannot be closed from public data

- **The other-payment payer and receiver are not disseminated.** Field #58 is
  "any value ≥ 0"; #61 and #62 are not published. Direction on an off-market
  print therefore comes from an edge-capture argument, not from reading who
  paid.
- **For rates, the other-payment block is optional.** An absent fee does not
  mean an at-market trade.
- **Remedy-1 unwinds are invisible.** When a client unwinds by executing an
  offsetting trade and the dealer nets it via bilateral compression, the tape
  shows only an ordinary new trade. Lineage coverage is coverage of ISDA
  Remedy 2 only.
- **Prime-brokerage double-counting is unbounded.** The PB indicator (#99) is
  not required when `Cleared = Y`, and most of the tape is cleared — so the
  de-duplication tool is absent exactly where it is needed.
- **~7.3% of prints are later corrected or cancelled** (CORR + EROR in one raw
  week, against NEWT), and the v3 tape applies neither. `EROR` means the trade
  legally never existed.
- **The tape has no dissemination timestamp.** Availability is either the
  Part 43 Appendix C legal-delay estimate or, where the lineage sidecar covers
  the window, the measured slice publication time (median 5.23 min, p95
  11.3 min). The tape's own `report_lag_seconds` is event minus execution and is
  **0 at p90** — it is not a publication delay at all.
- **Pre-2024-07 tape carries no termination events whatsoever** — an ingest
  regime change, not a market one.
- **The excluded packages are the most customer-facing prints on the tape**, not
  the least. `PKG-4+` is **97.9% D2C** against 82.1% for what is retained, with
  **28.7% of its DV01 in block legs** against 11.1%. The exclusion strips the
  largest, most informative customer trades. (Asset swaps run the other way at
  44.1% D2D, so only ~9.7 of their 17.4 pp was ever customer flow.)
- **A caution inherited from R0 that applies to any futures-side validation of
  this ladder**: aggressor-signed futures volume is *not* a clean read on dealer
  hedging, because a passively worked hedge enters with the **opposite** sign —
  a dealer resting offers is lifted by a buyer. Any attempt to validate this
  ladder against futures flow inherits that, and MBO carries no counterparty, so
  it cannot be separated.

---

## 7. Tie-out against the frozen short-end classifier

Two measurements, each varying one thing:

| | holds constant | varies | result |
|---|---|---|---|
| logic | the curve | old code → new code | `[pilot]` — a disagreement here is a **bug** |
| curve | the code | Barchart → Citi | `[pilot]` — a **finding**, not a failure |

A single blended agreement number would be meaningless: moving from a 78% PAID
label set to a balanced one is a ≥34 pp shift on the `RATE_VS_MID` population
alone, so any gate tight enough to be interesting could only be passed by
reproducing the bias.

The join is **unit-level and valid only for outrights**. The frozen system
assigns one direction per unit; a per-leg model gives the two legs of a curve
trade opposite signs, which is economically correct and leaves nothing to
compare.

---

## 8. Unfinished

`[pilot]` — stated plainly, including anything left out and why.
