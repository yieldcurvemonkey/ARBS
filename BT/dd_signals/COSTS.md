# Round-trip transaction cost for the two instruments S_PREREG trades

Measured **before any signal was estimated**, because `S_PREREG.md` §1 states its
kill rule against this number and §1 says the test that cannot clear it is not
run. Produced by `BT/dd_signals/measure_costs.py`; per-bucket numbers in
`BT/dd_signals/out/costs.csv`.

**Sample: 2024-03-01 .. 2025-08-31 only.** The hold-out (2025-09-01 .. 2026-08-07)
was not opened — not for a fit, not for a coverage count. The window is a module
constant with no CLI override. Every SQL statement is bounded by it directly,
except S2's per-day pricing query, which selects `as_of_date = <day>` from a day
list produced by a query that is so bounded.

> **One rule changed mid-run, and it changed every affected number upward.** The
> first `fit` pass let Roll set `round_trip_used_bps` where Roll happened to be the
> largest surviving point estimate. §2.3 and §4 then established that Roll is
> contaminated in both directions on this population, so it was demoted to a
> diagnostic and the used number became the top of the `[floor, ceiling]` bracket.
> Everything the correction moved, it moved **against** the researcher: 3Y D2C
> 0.230 → 0.495 bp, S2 D2D 1M–3M 0.058 → 1.084 bp. Recorded because this repo has
> a documented run of post-hoc defects that flattered the thesis, and the one
> mid-run change here did the opposite.

---

## 0. The answer, in one table

| | instrument | unit | round trip | **kill threshold (2×)** |
|---|---|---|---|---|
| **S1** | swap spread, spreadover, **client (D2C)** 5Y / 10Y | bp of spread | **0.325 / 0.330** | **0.651 / 0.659** |
| | same, 30Y | bp of spread | 0.474 | 0.948 |
| | same, 2Y / 3Y / 7Y / 20Y | bp of spread | 0.505 / 0.495 / 0.562 / 0.666 | 1.010 / 0.990 / 1.124 / 1.332 |
| | swap spread, spreadover, **interdealer (D2D)** 5Y/10Y/30Y | bp of spread | 0.272 – 0.279 | 0.543 – 0.558 |
| | swap spread, **matched-maturity / invoice** | bp of spread | *does not reconcile — unmeasured* | — |
| **S2** | outright SOFR swap, client (D2C), by tenor band | bp of rate | **0.529 – 1.397**, *unresolved* | **1.059 – 2.794** |

Every number is the **top of a measured bracket**, not a point estimate. §3
explains why the point estimator this task pointed at could not resolve one, and
§5 says what that does to each hypothesis.

**S1 is a real measurement.** The bracket is tight (`[0.125, 0.28]` bp at 10Y
interdealer) and the two ends come from independent evidence.

**S2 is not.** Its bracket has no floor and its ceiling is set by our own curve
error rather than by any bid-offer, so the hurdle in the table is far above the
true cost. §5.2 says what verdict language that forces.

---

## 1. What was measured, and against what

For a print with deviation `x = P_traded - P_mid`, `docs/dealer_direction/DESIGN.md`
§1.1 models `x | customer paid ~ N(b0 + h, s²)` and `x | customer received ~
N(b0 - h, s²)`, so **`h` is the dealer-to-client half-spread**, `s` is our mid
error, and the round trip is `2h`. `SDRUtils/dealer_direction/probability.fit_mixture`
fits `(b0, h, s)` with the weight pinned at 0.5. That fit was reused unchanged —
it is the validated instrument, and reimplementing it would have replaced it with
an unvalidated one.

| | S1 — swap spread | S2 — outright SOFR swap |
|---|---|---|
| traded price | `package_transaction_spread`, converted to bp | printed `fixed_rate`, in bp |
| mid | Citi **MI01** swap spread, same tenor, T−1min | par mid from `midprice.UnitRepricer` on the Citi minute SOFR curve, T−1min |
| population | `SPREADOVER`, `ECONOMIC_FLOW`, tenor on MI01's axis | `OUTRIGHT`, `ECONOMIC_FLOW`, SOFR, **spot-start, standard tenor, no upfront** |
| curve involved | none — both sides are already spreads | yes |
| n | 61,476 packages, 375 days | 93,714 legs, 125 days |

The S2 filter is the instrument S2's signal would actually put on: a par swap in a
liquid tenor. A swap carrying an upfront prints a rate that is not a quote, and a
forward-start or IMM-dated swap is a different instrument with its own spread;
including either would measure something S2 does not trade.

### Sampling, fixed before any pricing ran

S1 uses every design-window day. S2 reprices **every 3rd trading day** — 125 of the
376 — because the full pass is 3.6 h at the measured 18.6 ms/leg while a third of
it is 1.2 h, and even the thinnest D2C band still lands 2,050 prints against the
`MIN_BUCKET_N = 800` the fit asks for. The stride is a module constant, chosen from
that arithmetic and not revisited.

---

## 2. The tools were checked against known answers first

`measure_costs.py validate`. Every number below is from that stage, not asserted.

**1. `fit_mixture` recovers a known `h` — but only above its own separation gate.**
36 `(h, s, n)` cells, 40 draws each:

| the fit's own reported `h/s` | cells | bias in `h` | p90 abs error |
|---|---|---|---|
| ≥ 1 | 23 / 36 | −2.4% .. +0.5% | ≤ 10.4% |
| < 1 | 13 / 36 | **−80.1% .. −0.1%** | up to 168% |

The failure is **downward** — it argues the cost too low, the one direction a kill
rule may not be wrong in. The fit's own reported separation detects it: at a true
`h/s` of 0.5 it reports 0.05. **Reported separation ≥ 1 is therefore the gate**, and
below it the fitted `h` is a floor artefact, not a measurement.

**2. With no spread at all (`h = 0`), the fit returns `h` ≈ 0.005 bp** (median over
60 draws, p90 0.005, max 0.056) carrying `SEPARATION_BELOW_FLOOR`. Anything at that
scale is noise.

**3. The repo's incumbent mid-free estimator is degenerate on a two-sided book.**
`probability._independent_half_spread` takes `median tick / 2`. On simulated
streams with a known `h` and no drift, `|Δp|` is `0` or `2h` with equal
probability, so its median is a coin flip: at `h = 0.25` the estimator returned
0.000, 0.016, 0.119, 0.132, 0.176 and 0.216 across cells. **Roll (1984),
`sqrt(-Cov(Δp_t, Δp_{t-1}))`, is unbiased instead** — ratio 0.974 to 1.004 against
a moving mid — and is biased **up** (×1.02 to ×1.42) by i.i.d. instrument
heterogeneity. Roll replaced the incumbent as the mid-free reading; §3 and §4 then
show Roll is itself contaminated on this population, so both end up diagnostics.
*(Worth surfacing to the module owner, scoped to this population: 5–83% of
consecutive differences here are exactly zero because a block prints as several
clips at one price. On a futures lattice with a genuinely moving mid the incumbent
may behave.)*

**4. The lattice detector returns the coarsest grid ≥99% of prints land on.** Across
16 cells with a known increment and 0–10% off-grid contamination it was correct or
honestly `NaN` in 100%, and never returned a grid *coarser* than the truth — which
is the error that would overstate a floor.

**5. The dispersion ceiling really is a ceiling.** `sqrt(m2_trimmed) < h_true` in
**0 / 200** random `(b0, h, s)` draws.

**6. Units, against answers already in the ledger.** The S2 median deviation is
**+0.008 bp** against the ladder programme's independently measured **+0.021 bp**
"no measured convention bias" (`S_PREREG` §0.1). The S1 median deviation is
**+0.001 bp** across all tenors. Neither was tuned to.

---

## 3. S1 — the swap spread

### 3.1 The reconciliation gate (`S_PREREG` §4) — PASS for spreadover

`S_PREREG` §4 makes "the S1 units failing to reconcile against MI01 on the overlap
population" a reason to call the test uninformative. They reconcile:

| tenor | venue | n | median printed (bp) | median MI01 (bp) | median dev | dev IQR |
|---|---|---:|---:|---:|---:|---|
| 10Y | D2D | 20,275 | −46.250 | −46.263 | **−0.002** | −0.077 .. +0.076 |
| 10Y | D2C | 4,205 | −46.750 | −46.740 | −0.001 | −0.087 .. +0.087 |
| 5Y | D2D | 16,578 | −30.375 | −30.231 | +0.004 | −0.070 .. +0.081 |
| 30Y | D2D | 9,143 | −81.375 | −81.365 | −0.005 | −0.075 .. +0.065 |
| 30Y | D2C | 3,217 | −81.950 | −81.943 | −0.004 | −0.118 .. +0.121 |
| 2Y | D2C | 884 | −20.625 | −20.482 | +0.024 | −0.121 .. +0.155 |
| 20Y | D2C | 373 | −75.620 | −76.199 | +0.022 | −0.118 .. +0.170 |

Every tenor and venue agrees on **level, sign and scale**, with a median residual
inside 0.05 bp. Overall median +0.001 bp on 61,476 packages.

**Units had to be established first, and the field is a mess.** The CFTC
`package_transaction_spread` carries no notation flag and the tape passes it
through raw, so three notations coexist on this population — decimal (`-0.00463` =
−46.3 bp, 92.2%), percent (`-0.463`, 6.5%) and basis points (`-46.3`, 0.3%). Each
print is assigned the one multiplier of {1e4, 1e2, 1} that lands it inside 2–200 bp;
the three are 100× apart so the assignment is unique except at |raw| ∈ {0.02, 2.0},
and it classifies a *decade* while the quantity being measured is a tenth of a bp,
so it cannot distort the answer. **663 legs (1.04%) fit none of the three and were
refused, not guessed** — 98.5% of them would land in range under a fourth, 1e6
multiplier, which is recorded as an observation and deliberately not acted on.

### 3.2 The fit reports that it cannot resolve `h` — everywhere

All 14 spreadover buckets return `separation h/s` of **0.025 – 0.050** against the
gate of 1.0, and all 14 carry both `SEPARATION_BELOW_FLOOR` and
`LEPTOKURTIC_MOMENT_CHECK_FAILED` — a separated 50/50 mixture is *platykurtic*, and
the trimmed 10Y D2D deviations have excess kurtosis **+2.86**. The returned `h` of
0.004–0.009 bp is `MIN_SEPARATION × s`, the floor, and §2.2 shows that is what a
half-spread of *zero* also returns.

This is not a surprise once the numbers are in front of you. The 10Y D2D deviation
has a trimmed sd of 0.139 bp. If the true `h` is one half-tick, 0.0625 bp, then
`s = sqrt(0.139² − 0.0625²) = 0.125` and `h/s = 0.50` — **exactly the regime §2.1
measured as an 80% downward collapse to the floor.** The instrument is inside its
own documented blind spot, and it says so.

### 3.3 What resolves it: the market quotes on a 1/8 bp grid

This is the task's own cross-check clause — *the observed bid-offer in the tape's
own D2D prints* — promoted to load-bearing because the primary instrument declared
itself unresolved. Three facts, none of which uses a mid:

| tenor (D2D) | prints | grid detected | on-grid | Δ=0 on consecutive prints | p90 abs Δ | p99 abs Δ |
|---|---:|---:|---:|---:|---:|---:|
| 2Y | 345 | 0.1250 | 100.00% | 60.5% | 0.1250 | 0.525 |
| 3Y | 924 | 0.0625 | 100.00% | 72.7% | 0.1250 | 8.777 |
| 5Y | 16,578 | 0.1250 | 99.73% | 67.3% | 0.1250 | 21.875 |
| 7Y | 498 | 0.0625 | 100.00% | 65.1% | 0.1250 | 0.390 |
| 10Y | 20,275 | **0.1250** | **99.98%** | 64.6% | **0.1250** | 1.000 |
| 20Y | 110 | 0.1250 | 100.00% | 47.6% | 0.2500 | 0.250 |
| 30Y | 9,143 | 0.1250 | 99.99% | 54.1% | 0.2500 | 0.750 |

*(The p99 column is the fat tail the 6-MAD trim removes — misprints and wrong-bond
prints, not quoting behaviour. It is the reason a raw Roll estimate on this stream
returns 0.06 – 1.05 bp with no stable relation to the grid, and why Roll is carried
as a diagnostic only.)*

Essentially every interdealer spreadover spread prints on a **0.125 bp** grid, and
the 90th percentile of consecutive-print moves is **exactly one grid step**. Bid and
offer are at least one increment apart, so **one increment is a hard floor on the
round trip: 0.125 bp**.

D2C prints have **no** detectable grid — at 10Y only 69% land on the 0.125 grid —
which is itself informative: the client-executed level is not constrained to the
interdealer increment. So D2C has no floor, only the ceiling.

### 3.4 And the ceiling

`m2 = h² + s²` with both terms non-negative, so `2 sqrt(m2)` bounds the round trip
above whatever the split is, with no identification at all. Trimmed at the same
6 MAD the fit trims at (untrimmed, one −158 bp misprint sets the answer; the trim
removes 1.6% of the 10Y D2D sample).

### 3.5 S1 result

| venue | tenor | n | days | floor (lattice) | **ceiling = round trip used** | **kill threshold** |
|---|---|---:|---:|---:|---:|---:|
| **D2C** | 2Y | 884 | 302 | — | 0.505 | **1.010** |
| | 3Y | 1,058 | 294 | — | 0.495 | **0.990** |
| | 5Y | 3,235 | 373 | — | **0.325** | **0.651** |
| | 7Y | 631 | 236 | — | 0.562 | **1.124** |
| | 10Y | 4,205 | 375 | — | **0.330** | **0.659** |
| | 20Y | 373 | 169 | — | 0.666 | **1.332** |
| | 30Y | 3,217 | 367 | — | 0.474 | **0.948** |
| **D2D** | 2Y | 345 | 166 | 0.125 | 0.342 | 0.684 |
| | 3Y | 924 | 233 | 0.063 | 0.319 | 0.638 |
| | 5Y | 16,578 | 375 | 0.125 | 0.272 | 0.543 |
| | 7Y | 498 | 177 | 0.063 | 0.286 | 0.572 |
| | 10Y | 20,275 | 375 | 0.125 | **0.279** | 0.558 |
| | 20Y | 110 | 64 | 0.125 | 0.404 | 0.808 |
| | 30Y | 9,143 | 374 | 0.125 | 0.278 | 0.555 |

*All in bp of spread, per round trip. `bracket_ok` is true in every row — no ceiling
falls below its floor.*

**Which venue applies.** A research strategy transacts as a client, so **the D2C
row is the cost** and D2D is the floor a dealer would face. Note the D2C venue label
is a platform heuristic — the tape returns `D2D` only for six known IDB platform
codes and `D2C` for everything else including unknowns — so the D2C population is
contaminated with interdealer prints, which biases its measured dispersion *down*.
Using the ceiling covers that.

### 3.6 Matched-maturity and invoice do not reconcile — their cost is unmeasured

`MATCHED_MATURITY` and `INVOICE` carry a PTS on only 6.5% and 8.2% of their legs,
and on that selected subset the deviation against MI01 has `b0` up to **+16.7 bp**
and `s` up to **17.9 bp** (2Y, n=41). That is not a wide market, it is a different
instrument: an invoice spread is quoted against a futures CTD forward, not against
the spot swap-spread axis MI01 publishes. **`S_PREREG` §4's reconciliation clause
fires for this sub-family** and its cost is not measured here. Those rows carry
`reconciles_to_mid = False` in `costs.csv` and their `round_trip_used_bps` and
`kill_threshold_used_bps` are deliberately blank, so a consumer joining on tenor
cannot pick up a number this file disavows. Spreadover is the same-risk proxy;
treat an S1 signal built on the MM/invoice families as carrying an unmeasured cost.

---

## 4. S2 — the outright SOFR swap

The pass priced **93,714 of 95,073** filtered legs (98.57%) over 125 days; the
1,289 `NO_CURVE` and 70 `RISK_IMPLAUSIBLE` refusals are the whole of the loss.
Median snapshot lag 0 s, mean 58 s. D2C 89,067 / D2D 4,647. Block share 2.2%.

**Same verdict from the fit, for the same reason, only worse.** All 26 buckets
report separation 0.016 – 0.050, all `SEPARATION_BELOW_FLOOR`, `h` on the floor
(23 of 26 also leptokurtic).
The trimmed deviation sd is 0.26 – 0.68 bp for D2C, several times any plausible
outright half-spread, so `h/s` here is well below the 0.5 that already collapsed S1.

**And there is no floor.** `tick_bps` is `NaN` for every S2 bucket: an outright par
swap rate is a negotiated level, not a quote on a grid, so the lattice that rescued
S1 does not exist. The bracket is one-sided.

**The mid-free readings are unusable here, and it is worth saying why rather than
quietly dropping them.** Roll returns 0.8 – 90 bp and same-minute `mean|Δ|` returns
0.2 – 21 bp on D2C bands. Both estimators require consecutive prints to be *the same
instrument*, and on this tape no two outright swaps are: within `tenor_label = '10Y'`
the actual tenors run 9.55 – 10.25 years, so a "consecutive-print tick" is mostly the
curve between two different swaps. The precondition cannot be met for outrights.
They are in `costs.csv` as diagnostics and set nothing.

| venue | band | n | days | trimmed sd | **round trip used (= ceiling)** | **kill threshold** |
|---|---|---:|---:|---:|---:|---:|
| **D2C** | 0–1M | 762 | 107 | 0.699 | 1.397 | 2.794 |
| | 1M–3M | 2,488 | 125 | 0.529 | 1.057 | 2.115 |
| | 3M–6M | 2,850 | 125 | 0.355 | 0.710 | 1.421 |
| | 6M–1Y | 9,134 | 125 | 0.265 | **0.529** | **1.059** |
| | 1Y–2Y | 10,362 | 125 | 0.392 | 0.785 | 1.569 |
| | 2Y–3Y | 4,787 | 125 | 0.680 | 1.360 | 2.719 |
| | 3Y–5Y | 7,836 | 124 | 0.681 | **1.363** | **2.726** |
| | 5Y–7Y | 15,071 | 125 | 0.438 | 0.876 | 1.753 |
| | 7Y–10Y | 6,202 | 125 | 0.400 | 0.800 | 1.601 |
| | 10Y–15Y | 16,891 | 125 | 0.404 | 0.809 | 1.617 |
| | 15Y–20Y | 2,050 | 122 | 0.567 | 1.135 | 2.271 |
| | 20Y–30Y | 3,372 | 125 | 0.484 | 0.968 | 1.936 |
| | 30Y+ | 7,262 | 125 | 0.492 | 0.985 | 1.969 |
| **D2D** | 5Y–7Y | 649 | 93 | 0.305 | 0.610 | 1.221 |
| | 7Y–10Y | 783 | 84 | 0.187 | 0.373 | 0.747 |
| | 10Y–15Y | 996 | 112 | 0.262 | 0.524 | 1.047 |
| | 20Y–30Y | 522 | 79 | 0.142 | 0.284 | 0.568 |
| | 30Y+ | 508 | 86 | 0.207 | 0.414 | 0.828 |
| | *(the eight thinner D2D bands, n = 55 – 234, are in `costs.csv`)* | | | | | |

*All in bp of rate, per round trip.*

**These are ceilings on a quantity the ceiling does not isolate.** A round trip of
1.36 bp on a 3–5Y SOFR swap is not a bid-offer; it is mostly the T−1min curve's own
error entering `m2` as `s²`. §5.2 is the consequence.

**One observation, marked INFERRED and not used.** D2D deviation dispersion is
2 – 3× tighter than D2C in the same band (7Y–10Y: 0.187 vs 0.400). If `s` were common
to both venues — same curve, same clock — the excess would be client charge, giving
`h_D2C ≥ sqrt(0.400² − 0.187²) = 0.354` bp and a round trip of 0.71 bp. The premise
is not safe: D2C also carries the odd-size, odd-date and less liquid flow, which
raises `s` as well as `h`. Recorded because it is the shape of the answer, not
because it is one.

---

## 5. What this does to each hypothesis

### 5.1 The arithmetic, spelled out

This repo's founding cost error was a factor of two — the SR3 fly was believed to
cost 1.5 bp per structure and costs 2.0 bp because the charge is per *contract*.
So the chain is written out and carried as separate columns in `costs.csv`:

```
h                      the dealer-to-client HALF-spread
round trip   =  2h     cross the spread going in, cross it coming out
kill threshold = 2 x round trip = 4h      (S_PREREG §1)
```

`kill_threshold_used_bps` in the csv is the number a candidate must beat.

### 5.2 The two hypotheses

**S1 — measured, and the hurdle is usable.** An S1 candidate must show an in-sample
gross edge above **0.651 bp of spread per trade at 5Y and 0.659 at 10Y**, rising to
**0.95 – 1.33 bp** in the less liquid tenors (exact per-bucket values in
`kill_threshold_used_bps`). That hurdle is conservative by construction: the true
5Y/10Y D2C round trip is somewhere in `[0.125, 0.33]` bp and the hurdle uses the top.
If a candidate fails it, check whether it also fails against the floor before
declaring death — an edge between 0.25 and 0.65 bp is genuinely ambiguous and
`S_PREREG` §4's UNINFORMATIVE applies to it.

**S2 — the hurdle exists but is not a cost measurement.** The ceiling-based
threshold of **1.06 – 2.79 bp of rate** is several times any plausible outright
bid-offer, because it is set by our own mid error. That makes it a **sufficient but
not necessary** condition:

* an S2 edge **above** the ceiling hurdle clears under any reading of the cost, and
  the hold-out may be opened;
* an S2 edge **below** it is **UNINFORMATIVE, not "no signal"** — exactly R0's
  downgrade. The measurement cannot distinguish "the edge is smaller than the cost"
  from "the cost measurement is a ceiling four times the cost". Reporting S2 dead on
  this hurdle would be reporting a curve-error artefact as a market fact.

Resolving S2 properly needs a mid whose error is small against a ~0.1 bp
half-spread, i.e. `s` below roughly 0.1 bp against the 0.26 – 0.68 measured here.
That is a curve problem, not a statistics problem, and it is out of scope for this
run.

> **This needs an `S_DEVIATIONS.md` entry, which this file does not write.**
> `S_PREREG` §1 assumes a measurable round-trip cost for both instruments and
> states one kill rule over both. For S2 the cost is not measurable by the route
> the pre-registration names, so the kill rule can only be applied to S2 in the
> one-sided form above. The pre-registration is not edited; whoever owns
> `S_DEVIATIONS.md` should record that asymmetry before S2 is run.

### 5.3 Does cost vary enough across buckets that a single hurdle would mislead?

**Yes, for both — use the per-bucket column.**

* **S1 D2C spans 2.0×**, 0.325 bp (5Y) to 0.666 bp (20Y), and it tracks liquidity
  rather than noise: the two deepest buckets, 5Y and 10Y, are the two cheapest. A
  single hurdle set at 10Y would understate 20Y by a factor of two and let a 20Y
  candidate through on half the required edge. A single hurdle set at 20Y would kill
  a live 10Y candidate.
* **S1 D2D is much flatter**, 0.272 – 0.404 bp, 1.5× across seven tenors — the
  interdealer market really does charge one tick nearly everywhere.
* **S2 D2C spans 2.6×**, 0.529 bp (6M–1Y) to 1.363 bp (3Y–5Y), and here the variation
  is *not* a liquidity ordering — 5Y–7Y is the second-deepest bucket and sits mid-range
  while 3Y–5Y is the most expensive. That is the signature of curve error rather than
  cost, and another reason not to read the S2 column as a cost.

---

## 6. Caveats, in the order they could bite

1. **MI01's independence is assumed, not proved.** If Citi built its swap-spread
   quote from the SDR tape, the S1 deviation would collapse and the ceiling with it.
   Evidence against: MI01 prints ~1,300 of the 1,320 minutes in its session while
   10Y spreadovers print ~170 times a day, so it cannot be tape-derived at that
   resolution; and its published construction is Citi's own swap curve less a
   Treasury yield. Not verified.
2. **The MI01 mid is matched backward with a 2-minute tolerance** (production's
   in-session rule is 1 minute; MI01 has its own gaps). **97.8%** of prints matched;
   the 2.2% that did not are dropped, and they concentrate in Citi's 23:00–00:59 ET
   publication hole.
3. **The spreadover's bond is not MI01's bond.** A print is a spread to a specific
   Treasury; MI01 indexes a maturity. Where the two differ the residual enters `s`,
   which inflates the ceiling — conservative, but it means the ceiling is not a
   tight bound. 3Y D2D shows this most: 23.9% of its deviations exceed 1 bp against
   1.3% at 10Y D2D.
4. **`D2C` is a platform heuristic**, not observed counterparty identity. It
   contaminates the client population with interdealer prints and biases the D2C
   dispersion down.
5. **S2's 125-day stride** was fixed before pricing; it costs precision, not
   coverage — the thinnest D2C band carries 762 prints and every other carries
   ≥ 2,050. **Thin buckets:** 12 of the 13 S2 D2D bands (n = 55 – 783) and 5 of the
   14 S1 spreadover buckets (2Y/7Y/20Y D2D, 7Y/20Y D2C, n = 110 – 631) fall under
   the `MIN_BUCKET_N = 800` the fit asks for. A ceiling is a bound rather than a
   fit and stays valid, but on those rows it is itself noisy — read them as
   indicative and prefer the deep buckets.
6. **Blocks are included** (2.2% of S2, and spreadover blocks are not separated).
   They are real customer trades; a block-only cost is not measured.
7. **Two processes briefly wrote the S2 cache** before one was killed. The fit stage
   now verifies the readable day set against the target day set before use and
   refuses rather than proceeding on a partial cache; it passed at 125/125.
8. **`C:` fell to 214 MB free mid-run** from other activity on the box. All caches
   for this work are on `D:\dd_signals_cache\`; nothing was lost, but a longer pass
   would be at risk.

---

## 7. Reproducing

```
python BT/dd_signals/measure_costs.py validate   # tools vs known answers, ~5 min
python BT/dd_signals/measure_costs.py s1         # -> D:/dd_signals_cache/s1_dev.parquet
python BT/dd_signals/measure_costs.py s2         # -> D:/dd_signals_cache/s2/<date>.parquet, resumable
python BT/dd_signals/measure_costs.py fit        # -> BT/dd_signals/out/costs.csv
```

Use the env interpreter directly (`C:/Users/chris/anaconda3/envs/stir/python.exe`),
never `conda run` — parallel invocations collide on a temp file and return empty
output with exit code 0. `ARBS_CITIVELO_QUOTES_OFFLINE=1` is set inside the module,
so no stage can open Excel.
