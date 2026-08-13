# S1 — does signed swap-spread flow predict the swap spread?

`docs/dealer_direction/signals/S_PREREG.md` S1, design sample only.
Produced by `BT/dd_signals/s1_spread_flow.py`; per-cell numbers in
`BT/dd_signals/out/s1_results.csv`.

**Sample: 2024-03-01 .. 2025-08-31 only.** The hold-out (2025-09-01 ..
2026-08-07) was not opened — not for a fit, not for a coverage count. This
module issues **no database read at all**: it consumes the print cache
`measure_costs.py s1` already built and an MI01 series bounded by `DESIGN_END`,
so a forward change that would need a September close has no target and drops.
The truncation is structural, not a filter that could be relaxed.

---

## SPEC — frozen before the regression ran

Written first, and left unedited afterwards, because `S_PREREG` §5 allows one
specification per hypothesis and this repo's memory records twelve post-hoc
defects that all happened to flatter the hypothesis. Every choice below is in
the module's constants block with the reasoning attached.

| | choice | why, decided in advance |
|---|---|---|
| **population** | `SPREADOVER` only | `S_PREREG` §4's reconciliation clause **fired** for `MATCHED_MATURITY` and `INVOICE` in `COSTS.md` §3.6 — PTS on 6.5%/8.2% of legs, and on that subset `b0` to +16.7 bp and `s` to 17.9 bp against MI01, because an invoice spread is quoted to a futures CTD forward, not MI01's spot axis. Signing those off an MI01 deviation would be signing off a 17 bp measurement error. Spreadover reconciles to ±0.05 bp at every tenor. |
| **venue** | primary **D2C**; **D2D** one labelled diagnostic; never pooled | S1 is about *customer* flow. D2D is the dealer laying risk off. |
| **orientation** | `d_i = sign(deviation_i − b0_bucket)` | `tau = s²/(2h)` needs `h`, and `COSTS.md` §3.2 records the mixture fit **could not resolve `h`** here (all 14 buckets at separation 0.025–0.050 against a gate of 1.0). `sign(x − b0)` is invariant to `tau`; a probability weighting is not. |
| **`b0`** | per bucket from `out/costs.csv` | measured before any signal was estimated. \|b0\| ≤ 0.028 bp everywhere, so it is a small correction — but taking it from the pre-measured file keeps the de-biasing out of the signal's own hands. |
| **trim** | 6-MAD per bucket, **before** signing | the same trim the cost fit used, so the same population `b0` was fitted on. The sign of a wrong-bond print or a misprint (the p99 tail of 1–22 bp, `COSTS.md` §3.3) is noise about direction. |
| **regressor** | `F = Σ nᵢdᵢ / Σ nᵢ ∈ [−1, +1]`, notional-weighted net signed fraction | the plain reading of "net signed flow in a tenor bucket"; bounded and scale-free across buckets. The kill-rule quantity — edge per trade — depends only on `sign(F)`, so it is invariant to this normalisation. |
| **flow window** | `[D−1 15:00 ET, D 15:00 ET)`, half-open | ends **at** the target's own base instant, so no print in the flow can post-date the change it predicts. 82.1% of prints are before 15:00 ET on their own calendar day; the window assigns the London and 19:00–22:59 ET sessions to the next close rather than dropping them. |
| **day index** | MI01's **observed** close calendar | `as_of_date` on the tape is a UTC date — 4.4% of prints fall on a different New York date than their `as_of_date`, so it could not be used. Horizons step the observed calendar, so a holiday cannot shift one. |
| **target** | `ΔS_k = close(t+k) − close(t)`, close = last MI01 print in `(14:30, 15:00]` ET | 15:00 NY is the Treasury cash close, the instant a swap spread is marked at. MI01 prints ~1,300 of its 1,320 session minutes, so the staleness guard only rejects a broken day. |
| **horizons** | k = 1..5 | `S_PREREG` S1, "the following 1–5 business days". |
| **direction** | **β < 0** | fixed in advance by `S_PREREG` S1: customer **pays** → prints above the mid → `deviation > 0` → `F > 0`; the dealer is left receiving, long the spread, its pending trade is **selling**, so the spread **falls**. MI01 publishes swap − Treasury (−46 bp at 10Y) and the printed spread reconciles to it in level and sign, so "falls" is unambiguously "more negative". A significant **positive** β is a different phenomenon, not a pass. |
| **standard errors** | Newey–West, Bartlett, **lag = k** | `S_PREREG` §4 says cluster by day and `N_eff` is trading days. Aggregating prints to bucket-days satisfies that; day-clustering can do nothing more *within* a bucket, where a day cluster has one member. The overlapping k-day forward change makes the residual MA(k−1), and NW at lag k is what handles it. The panel is kept **gapless** — `F = 0` on a no-print day rather than a dropped row — because the kernel is positional. |
| **edge per trade** | `mean(−sign(F)·ΔS_k)` over days with a position, in **bp of spread** | this is the quantity `S_PREREG` §1's kill rule is stated against. Computed as the NW mean of a gapless daily P&L series carrying 0 on no-position days, then rescaled by `n_days / n_trades`. |
| **MDE** | `(z₀.₉₈₇₅ + z₀.₈)·SE = 3.083·SE` | 80% power, two-sided at `ALPHA = 0.025`. |
| **significance** | p < 0.025, two-sided | `S_PREREG` §3, Bonferroni over the two hypotheses. |
| **placebo** | one, `prev_session_same_minute_mid` | re-sign every print against MI01 at the **same clock minute one close-day earlier**. Trade, notional, window and tenor untouched; only the mid moves back a session, which removes the half-spread information and any same-day mid-error link at once. Its edge must be ≈ 0 or the pipeline leaks. |

> **One line of this SPEC did not survive its own validation stage, and the
> original text above is left standing rather than edited.** The two rows
> marked *standard errors* and *MDE* declare Newey–West at lag = k judged
> against a normal critical value. `validate` — run before the real pass,
> which is what the SPEC put it there for — measured that combination
> rejecting a true null at 5–7% instead of 2.5%. The critical value is
> therefore simulated per cell rather than taken from the normal, and the MDE
> uses that simulated multiplier. **§2 below has the measurement, and the
> correction moves every number against the hypothesis.** Nothing else in the
> SPEC changed.

### The verdict ladder, fixed before the run

Evaluated in this order, per (tenor, venue, k) cell, against that cell's own
`costs.csv` row — `COSTS.md` §5.3 measured cost varying 2.0× across S1 D2C
tenors, so a single hurdle would mislead.

1. usable bucket-days < 200 → **UNINFORMATIVE_COVERAGE** (`S_PREREG` §4)
2. sign wrong **and** p < 0.025 → **WRONG_SIGN** (a different phenomenon)
3. edge ≥ `kill_threshold_used_bps` **and** p < 0.025 → **PASS**, hold-out may open
4. edge + 2.2414·SE < 2 × lattice floor → **DEAD**
5. MDE > `kill_threshold_used_bps` → **UNINFORMATIVE_POWER**
6. otherwise → **AMBIGUOUS**, hold-out stays shut

Band 4 sits before band 5 deliberately: **DEAD** is claimed only when the whole
one-sided 98.75% range of the edge lies below even the *cheapest* reading of the
cost bracket, which is a statement that does not need power against the ceiling.
The floor is 2 × the D2D lattice increment for the tenor; D2C has no detectable
grid of its own and inherits the same-tenor D2D increment, which is exactly what
`COSTS.md` §5.2 instructs. Anything failing band 4 with an MDE above the ceiling
is UNINFORMATIVE, as R0's downgrade worked.

### Hurdles this is judged against (from `out/costs.csv`, unmodified)

| venue | tenor | round trip (ceiling) | **kill = 2×** | lattice floor | 2 × floor |
|---|---|---:|---:|---:|---:|
| D2C | 5Y | 0.325 | **0.651** | 0.125 | 0.250 |
| D2C | 10Y | 0.330 | **0.659** | 0.125 | 0.250 |
| D2C | 30Y | 0.474 | **0.948** | 0.125 | 0.250 |
| D2D | 5Y | 0.272 | 0.543 | 0.125 | 0.250 |
| D2D | 10Y | 0.279 | 0.558 | 0.125 | 0.250 |
| D2D | 30Y | 0.278 | 0.555 | 0.125 | 0.250 |

---

<!-- RESULTS BELOW THIS LINE WERE WRITTEN AFTER THE SINGLE PASS RAN -->

## 0. The answer

**S1 is DEAD. The hold-out is not opened.**

Signed customer swap-spread flow does not predict the swap spread at 1–5 business
days. Across the 35 primary D2C cells (7 tenors × 5 horizons):

* **no cell passes** — zero PASS, and the best gross edge anywhere is
  **0.174 bp per trade** against a hurdle of **0.651–1.332 bp**;
* **nothing is significant in either direction** — zero significant β, zero
  significant edge, largest \|t\| anywhere is **1.66** against a size-corrected
  critical value of 2.51–2.63. There is no WRONG_SIGN cell either;
* **the deepest buckets go the wrong way**. At 5Y and 30Y — 372 and 371 usable
  bucket-days — the estimated β is **positive** at every horizon and the realised
  edge is **negative** (5Y −0.015 to −0.060, 30Y −0.042 to −0.174 bp per trade).
  The hypothesis predicts β < 0;
* **hit rates are 43–51%**, i.e. a coin.

And critically, **this is a powered negative, not an uninformative one**: the MDE
is below the cell's own cost hurdle in **35 of 35** D2C cells. The test could have
seen an effect large enough to matter, and did not.

| primary D2C, deep buckets | k=1 | k=2 | k=3 | k=4 | k=5 |
|---|---:|---:|---:|---:|---:|
| **5Y** β (t) | +0.04 (0.6) | +0.02 (0.2) | +0.07 (0.6) | +0.14 (0.9) | +0.22 (1.3) |
| edge bp/trade | −0.018 | −0.015 | −0.032 | −0.024 | −0.060 |
| MDE / hurdle 0.651 | 0.133 | 0.199 | 0.231 | 0.254 | 0.277 |
| verdict | DEAD | DEAD | DEAD | DEAD | DEAD |
| **10Y** β (t) | +0.02 (0.3) | −0.07 (−0.4) | −0.25 (−1.2) | −0.16 (−0.6) | −0.35 (−1.1) |
| edge bp/trade | 0.000 | 0.031 | **0.117** | 0.045 | 0.084 |
| MDE / hurdle 0.659 | 0.159 | 0.240 | 0.313 | 0.395 | 0.441 |
| verdict | DEAD | DEAD | AMBIG | AMBIG | AMBIG |
| **30Y** β (t) | +0.01 (0.1) | +0.03 (0.2) | +0.04 (0.2) | +0.01 (0.1) | +0.13 (0.5) |
| edge bp/trade | −0.042 | −0.120 | −0.059 | −0.056 | −0.174 |
| MDE / hurdle 0.948 | 0.189 | 0.298 | 0.335 | 0.362 | 0.447 |
| verdict | DEAD | DEAD | DEAD | DEAD | DEAD |

Full grid, both venues, both specs: `out/s1_results.csv` (140 rows).
Verdict counts, primary: **D2C** 23 DEAD / 7 AMBIGUOUS / 5 UNINFORMATIVE_COVERAGE
(20Y only); **D2D** 11 / 9 / 15.

The seven AMBIGUOUS D2C cells are AMBIGUOUS only in the frozen ladder's narrow
sense — their edge is far below the *ceiling* hurdle but the one-sided 98.75%
upper bound does not quite clear the *floor* hurdle of 0.25 bp. None is
significant; none is close to the kill threshold.

## 1. Population, and the sub-family the pre-registration excluded itself

61,476 spreadover packages carry both a printed spread and an MI01 mid. The
6-MAD trim removes 1,787 (2.9%), leaving **59,689 signed prints over 384 close
days**. No print signed to exactly zero. The unconditional pay/receive split is
**0.4996–0.5008** in every bucket — the classifier is balanced, so nothing here
is a drift term.

`MATCHED_MATURITY` and `INVOICE` are **not tested**. `S_PREREG` §4's
reconciliation clause fired for them in `COSTS.md` §3.6, before any signal was
estimated: they carry a PTS on 6.5%/8.2% of legs and on that subset the deviation
against MI01 has `b0` to +16.7 bp and `s` to 17.9 bp, because an invoice spread is
quoted to a futures CTD forward rather than MI01's spot axis. Their cost is
unmeasured and their rows carry `reconciles_to_mid = False`. Signing them off an
MI01 deviation would be signing off a 17 bp measurement error. **S1 therefore
tests roughly a third of the 198k legs the hypothesis names** — the third whose
units reconcile. That is the pre-registration's own escape hatch operating, not a
choice made after seeing a result, but it is a real narrowing and is the first
thing to hold against this verdict.

## 2. The machinery was checked against planted answers first — and failed once

`out/s1_validate.txt`, run before the real pass.

The mixture fit recovers a planted β to within 1.3% with 96–98% interval coverage,
and the edge estimator recovers a planted 0.5 bp edge to within 0.011 bp. But
test (4) caught a real defect in what the SPEC had declared. **Newey–West at
lag = k judged against a normal critical value rejects a true null at 5–7%, not
2.5%, once the regressor is persistent and the horizon overlaps** — plain OLS
reaches **29%**. Widening the bandwidth does not fix it (k=5 stays at 5.4–7.4% for
every lag from k to 4k) and neither does a circular block bootstrap at L=10/20/30.
This is the known finite-sample over-rejection of overlapping long-horizon tests.

So the critical value is **calibrated by simulation** instead of assumed: for each
cell's own `(n, k, ρ)` the null distribution of \|t\| is simulated under an AR(1)
regressor and MA(k−1) errors and its 98.75th percentile taken. `ρ` is the lag-1
autocorrelation of `F` itself — a property of the regressor, observable without
the target. Corrected, the null rejects at **0.4–2.3%** (test 4b) and power at the
reported MDE is **0.77–0.81** (test 5), as designed.

**This is a departure from the SPEC's declared "NW at lag = k", made before the
real pass, and it moved every number against the hypothesis:** a larger critical
value makes PASS harder, DEAD harder and UNINFORMATIVE easier. Multipliers came
out 2.51–2.78 against the normal's 2.241. Had it not been caught, the SEs would
have been ~20% too small, which would have manufactured *more* DEAD verdicts than
are reported here — R0's downgrade run backwards.

## 3. The alignment was proved end-to-end, not assumed

`out/s1_plumbing.txt`. The obvious check — does `F` correlate with the
contemporaneous close-to-close move — returns **0.03 to 0.08**, which cannot
distinguish "the day index is off by one" from "the flow is noise". It was not
used. Instead each print's direction was replaced by an **oracle**,
`−sign(close(t+1) − close(t))` for its own close-day:

| | β (D2C, k=1) | hit rate | edge bp/trade | mean \|daily move\| |
|---|---:|---:|---:|---:|
| 5Y oracle | −0.525 | 1.000 | 0.526 | 0.530 |
| 10Y oracle | −0.589 | 1.000 | 0.590 | 0.596 |
| 30Y oracle | −0.728 | 1.000 | 0.728 | 0.738 |
| 10Y **one day stale** | −0.082 | 0.551 | 0.083 | — |

The oracle returns the predicted **negative** β, a hit rate of exactly 1.0, and an
edge equal to the mean absolute daily move; one day of staleness collapses it to
0.08. The day index, the flow window, the sign convention and the edge arithmetic
are all confirmed simultaneously. **The zero in §0 is a real zero, not a plumbing
bug.**

## 4. The result that reframes the k=1 horizon

That oracle also bounds what *any* signal could earn. `out/s1_oracle_ceiling.csv`:

| D2C | k=1 | k=2 | k=3 | k=4 | k=5 |
|---|---:|---:|---:|---:|---:|
| 5Y oracle edge / hurdle | **0.81** | 1.14 | 1.35 | 1.58 | 1.75 |
| 10Y oracle edge / hurdle | **0.90** | 1.31 | 1.59 | 1.85 | 2.08 |
| 30Y oracle edge / hurdle | **0.78** | 1.13 | 1.41 | 1.69 | 1.91 |
| 10Y hit rate needed to clear | **105%** | 88% | 82% | 77% | 74% |

**At k=1 a perfect one-day-ahead oracle does not clear the cost hurdle at any
deep tenor.** The required directional accuracy exceeds 100%. So the k=1 DEAD
verdicts are over-determined: they would be DEAD for *any* signal, and they say
something about the instrument rather than about flow. The daily swap-spread move
is simply too small against a 0.33 bp round trip.

At **k ≥ 2 the oracle clears** (1.13–2.08×) and the required hit rate is 74–94%.
Those cells are genuine, powered tests — and they return 47–51%.

## 5. The placebo did not do what it was declared to do

`prev_session_same_minute_mid` was declared as a null whose edge "must be ≈ 0".
It is not a null. Re-signing a print against the *previous session's* mid makes
`sign(pts − mid_{t−1})` essentially the sign of the spread's own day-over-day
move, so the placebo is a **spread-reversal signal**, not an absence of one. It
produces edges of **0.21 bp** (10Y D2C, k=5, t = 2.05) — *larger* than anything
the primary produces.

Reported as a miss rather than quietly dropped. Two things follow, one of them
useful:

* It **fails as a leak test**, and the plumbing evidence in §3 carries that load
  instead — which it does more directly anyway.
* It shows that a **mechanically constructed signal with no flow content
  whatsoever produces edges at least as large as the primary's** at 10Y. That
  strengthens rather than weakens the verdict: the primary's largest positive
  numbers are not distinguishable from a mid-staleness artefact.

The same effect appears independently as the 0.083 bp residual on the one-day-stale
oracle in §3 — there is a mild 1-day reversal in MI01 itself, worth ~0.08–0.2 bp
against round trips of 0.27–0.33 bp. It does not clear either.

## 6. The one cell with the predicted sign — interdealer, and still short

10Y **D2D** is the only place the hypothesis's sign appears with any strength:
β = −0.61 to −0.88 at k = 2–5, t = −1.47 to −1.97, hit rate 55%, edge
**0.107–0.215 bp** per trade. It is reported because it is the one thing that
moved, and it changes nothing:

* not significant — \|t\| = 1.97 against a size-corrected critical value of 2.62.
  **This is the one cell where §2's correction was load-bearing:** the k=3 edge
  carries t = 2.29, which the SPEC's original normal critical value of 2.241
  would have called significant and the simulated 2.667 does not. The verdict is
  AMBIGUOUS either way — the edge is 0.204 bp against a 0.558 bp ceiling — but
  the uncorrected test would have reported a significant result here;
* below the cheapest reading of cost — 0.215 bp against a **0.25 bp** floor
  hurdle, let alone the 0.558 bp ceiling;
* **D2D is not the hypothesis.** S1 is about *customer* flow. D2D is the dealer
  laying risk off, and a dealer-to-dealer print signed off its own deviation is
  as likely to be the hedge as the cause;
* with 70 primary cells reported, one \|t\| ≈ 2 is expected.

## 7. Caveats, in the order they could bite

1. **Only spreadover is tested** (§1). Two thirds of the legs the hypothesis names
   are excluded by the pre-registration's own reconciliation clause. If
   matched-maturity and invoice flow behaves differently, this run says nothing
   about it — and pricing an invoice spread against its CTD forward is the work
   that would be needed to find out.
2. **The direction is inferred, not observed.** Every sign here is
   `sign(deviation − b0)`, and `COSTS.md` §3.2 records that the mixture fit could
   not resolve `h` on this population, so the per-print accuracy is unknown. The
   bracket implies `h/s ≈ 0.3–0.6`, i.e. roughly 62–73% per print. At 9 D2C prints
   a day, the daily `F` is a noisy estimate of the true imbalance, and
   attenuation bias pushes β toward zero. **This is the caveat most able to
   overturn the negative**: a noisier regressor cannot manufacture the wrong sign
   at 5Y/30Y, but it does shrink β. Against that: the MDE is below the hurdle in
   all 35 cells, and the oracle in §3 shows the panel *can* express a strong β
   when a strong signal is present.
3. **The MI01 day-level common error is small but not zero.** The ICC of the
   deviation by day is 0.014–0.034 in the deep buckets, so a positive mechanical
   bias in β is expected and observed — every k=1 β is small positive
   (+0.008 to +0.036). It is negligible at that size, and it biases *against* the
   hypothesis's negative sign, so it cannot have hidden a pass.
4. **`D2C` is a platform heuristic**, not observed counterparty identity
   (`COSTS.md` §4 caveat 4), so the "customer" population is contaminated with
   interdealer prints.
5. **Notional weights come from the package's first leg** and 0.5–6.7% of prints
   are capped. A capped notional understates size.
6. **The hurdle is a ceiling.** `COSTS.md` §5.2 says the true D2C round trip is
   somewhere in [0.125, 0.33] bp at 5Y/10Y and the hurdle uses the top. Against
   the *floor* hurdle of 0.25 bp the 10Y k=3–5 cells become AMBIGUOUS rather than
   DEAD — which is exactly why they are labelled that way and why they are
   reported, not buried. Nothing reaches PASS under either reading.
7. **Multiplicity.** `S_PREREG` §3's Bonferroni is over the two hypotheses, not
   over the 70 cells here. At 2.5% per cell, ~1.75 false positives were expected
   across the grid; **zero** were observed.

## 8. Reproducing

```
python BT/dd_signals/s1_spread_flow.py validate   # machinery vs planted answers
python BT/dd_signals/s1_spread_flow.py mi01       # -> D:/dd_signals_cache/s1_mi01_min.parquet
python BT/dd_signals/s1_spread_flow.py plumbing   # oracle alignment + oracle ceiling
python BT/dd_signals/s1_spread_flow.py run        # -> out/s1_results.csv
```

Use the env interpreter directly (`C:/Users/chris/anaconda3/envs/stir/python.exe`),
never `conda run`. Outputs: `out/s1_results.csv`, `out/s1_population.csv`,
`out/s1_validate.txt`, `out/s1_plumbing.txt`, `out/s1_oracle_ceiling.csv`;
caches `D:/dd_signals_cache/s1_mi01_min.parquet`, `s1_panel.parquet`.
