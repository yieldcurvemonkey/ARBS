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

## 1. What it is

A **flow** series: model-labelled customer-to-dealer risk transfer, per
key-rate bucket, stamped on the clock at which each print became public.

## 2. What it is not

**It is not an inventory.** Compression and allocation are never publicly
reported, so positions that were netted away leave no offsetting print. A
running sum of this series accumulates a monotone, unbounded error. If you want
inventory, you need a decay term or an external reconciliation, and neither is
supplied here.

**It is not counterparty-observed.** Direction is inferred from price against a
repriced mid. It is uncertified against any external truth label — there are no
desk tickets behind it.

**It is not a signal.** No backtest was run, deliberately.

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

| family | treatment | reason |
|---|---|---|
| `PKG-N`, N ≥ 4 | **excluded** | no market quote convention fixes the base orientation, so forcing one manufactures a confident direction from nothing |
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
