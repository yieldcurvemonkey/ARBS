# Convexity relative value — design notes

Three strategies from three research notes, sharing one measurement kernel.
Everything stated here as a number was measured on this machine, not quoted
from a docstring; where a fact came from a research note it is quoted verbatim
and attributed.

---

## 0. The thesis, in one paragraph

A PVBP-weighted curve trade has an options-like payoff. JPM:

> "as rates rise, receive-fixed positions in the longer tenor (which is losing
> money) will lose dollar duration more quickly than the pay-fixed position in
> the shorter leg (which is making money), resulting in a positive P/L—and vice
> versa in a rally. In this way, flattening exposures on the curve have a
> positively convex payoff under large enough moves in rates."

So a flattener is long gamma. It is only *worth* being long gamma if the carry
you pay for it is small relative to the volatility you expect to harvest — which
is why the long end matters, and why the interesting structures are forward
flatteners rather than spot ones. Citi puts the same point as an analogy:

> "the risk profile of this trade is similar to that of long swaption straddles.
> In that analogy, the spread between 10y10y and 20y10y rates is akin to implied
> volatility, i.e. the vega exposure of the trade."

**Measured, on 2022-09-13, $100k DV01, P&L in bp of package DV01:**

| shift (bp)      | −250 | −200 |  −150 | −100 | −50 | −25 |   0 |  25 |  50 | 100 |  150 |  200 |  250 |
|-----------------|-----:|-----:|------:|-----:|----:|----:|----:|----:|----:|----:|-----:|-----:|-----:|
| 20Yx5Y/25Yx5Y   | 60.0 | 33.7 |  16.5 |  6.4 | 1.3 | 0.3 | 0.0 | 0.4 | 1.2 | 4.2 |  8.2 | 12.8 | 17.5 |
| 30Y/50Y         |137.9 | 82.1 |  44.7 | 20.9 | 6.9 | 2.7 | 0.0 |−1.4 |−1.8 |−0.1 |  3.9 |  9.5 | 15.9 |
| 10Yx10Y/20Yx10Y |104.9 | 60.0 |  29.9 | 11.6 | 2.3 | 0.4 | 0.0 | 0.9 | 2.9 | 9.5 | 18.7 | 29.7 | 41.7 |
| 5Y/30Y          |101.9 | 62.6 |  34.3 | 15.3 | 4.3 | 1.4 | 0.0 | 0.1 | 1.4 | 7.7 | 18.0 | 31.8 | 48.3 |

Clean U-shapes with the minimum at zero: flatteners are long gamma. This table
is used as a regression check in the notebooks.

And the carry, 1-year horizon, same date, same sign convention:

| pair            | carry+roll (bp/yr) |
|-----------------|-------------------:|
| 20Yx5Y/25Yx5Y   |             +0.006 |
| 30Y/50Y         |             +0.363 |
| 10Yx10Y/20Yx10Y |             −2.840 |
| 5Y/30Y          |            −20.670 |

Which is JPM's headline claim reproduced on our own data: the long-end forward
flattener is long gamma for approximately nothing, while the same exposure in
5s30s costs 20bp a year.

---

## 1. Conventions

Established **empirically against the engine**, not read off the risk-weight
code, because this is the class of thing that silently inverts every number
downstream.

| convention | meaning | how it was verified |
|---|---|---|
| `OUTRIGHT bpv > 0` | **payer** | +$2.30M on $100k DV01 across the 23bp Sept-2022 selloff; ±bpv mirrored exactly |
| `CURVE bpv < 0` | **flattener** (receive back leg) = long convexity | 20Yx5Y/25Yx5Y made +$672k over the Jan–Mar 2021 reflation, when that forward curve inverted further |
| `CURVE bpv > 0` | **steepener** = short convexity | 5Y/30Y made +$1.82M over the same window, which steepened 19bp |
| `CURVE RATE` | `back − front` when `bpv>0`; `front − back` when `bpv<0` | matches the outright rate difference to 1e-6 |

Every notebook re-runs a sign probe at execution time and asserts, following
`notebooks/backtests/citivelo_rv/sv_h13_qdb.py`.

---

## 2. Measuring convexity: reprice, don't differentiate

`IRSwapValue.GAMMA_01` and `DV01` are **not available** — the rateslib backend
raises `NotImplementedError` for both, because a true DV01 needs a calibrated
`rl.Solver` that the curve does not carry. `PV01` (analytic delta) is available
and returns ~0 for a DV01-neutral package, as it should.

So convexity is measured the way the note measures it: reprice the whole package
on `handle.shift(bp)`. That is exact rather than a second-order approximation.
`RVUtils/ConvexityRV/curve_ops.py::payoff_profile` is the kernel.

### 2.1 Ageing is NOT done with `Curve.translate` — a measured rejection

The intuitive approach is to age a position by pricing it on
`handle.translate(horizon)`. It runs without complaint and returns numbers that
are simply wrong:

| package | aged 1y at zero shift | independent check (carry+roll) |
|---|---:|---:|
| 20Yx5Y/25Yx5Y | −0.000 bp | +0.006 bp |
| 10Yx10Y/20Yx10Y | 0.000 bp | −2.840 bp |
| 30Y/50Y | **−147.739 bp** | +0.363 bp |
| 30Y outright payer | **−531.94 bp** | — |

`translate` renormalises discount factors onto a new initial node. For a
DV01-neutral forward package that cancels and no carry is captured at all; once
a swap's effective date precedes the translated curve's initial node, the
intervening fixings are absent and the result is meaningless. A $100k DV01 payer
cannot lose 532bp to one year of ageing with rates unchanged.

30s/50s is in strat 1's universe, so this would have corrupted precisely the
spot-versus-forward comparison the JPM note turns on — and in the direction that
makes the forwards look better.

`horizon_handle(..., horizon_date=...)` now raises `HorizonAgeingUnsupported`.
Carry enters as `payoff_profile(carry_ccy=...)`: **convexity is the shape of the
profile, carry is its level**, which is exactly how the note describes it —
"the payoff profile of an aged flattener at fixed coupon, primarily to
incorporate carry costs". JPM's own Exhibit 3 footnote confirms the construction
is note-faithful: *"Net P/L for a **spot** 30s/50s flattener under parallel
shifts in rate, **with coupons equal to the 1-year forward rates**"*.

### 2.2 …and `CARRY_AND_ROLL_BPS_RUNNING` is not Citi's carry either

The obvious source for that level term is the query field. Measured against
Citi's published Figure 7 (close 5/8/2019, eight pairs with printed "1y carry"):

| carry source | correlation vs Citi | MAE |
|---|---:|---:|
| `IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` @1Y | **−0.136** | 1.28 bp |
| repriced 1y `rl.Curve.roll` of the aged package / DV01 | **+0.991** | 0.354 bp |

The query field gets the *rank order across pairs wrong*, which is fatal for a
screen that ranks pairs. Strat 3 uses the repriced roll as primary and reports
the query value alongside as `carry_query_bp`. Strat 1's profile level still
uses the query field; its pinned carry values are internally consistent and its
signal is a within-structure time series rather than a cross-sectional rank, but
the discrepancy is recorded here rather than smoothed over.

---

## 3. Data coverage — measured, and it shapes the design

| series | source | window | coverage in 2019-01..2026-08 |
|---|---|---|---|
| swap curve `USD-SOFR-1D` | Citi Velocity Excel add-in cache | 2019-01-02 .. 2026-08-12 | complete for all long-end forwards |
| swaption **ATMF** vol | Citi Velocity cube store | from 2015-10-08 | **97.8%** (1859/1900 days) |
| swaption **OTM smile** | same | from **2020-03-25** | **83.9%** (1594/1900) |
| SR3 futures settles | Barchart | 2018-05-04 .. 2026-08-13 | full Q12 |

The cube carries normal vols in bp at strike offsets
−200/−100/−75/−50/−25/−10/0/+10/+25/+50/+75/+100/+200 around ATMF.

**Consequence for strat 1.** The JPM note gives two signals and they need
different data:

* *expected payoff* — integrate the payoff profile against the swaption-implied
  terminal distribution. Needs the **OTM smile**, so it cannot run before
  2020-03-25.
* *breakeven ("curve-implied") vol* — solve for the normal vol that zeroes the
  expected payoff, and compare to the ATMF swaption vol. Needs **ATMF only**, so
  it runs from Jan-2019.

The note presents them as two readings of one comparison — *"Both measures can
be interpreted as a relative value signal for curve convexity trades versus
swaptions"* — so `signal_mode` is a config knob and **breakeven_vol is the
default**, on coverage grounds. This was decided by measuring the store, not by
preference.

---

## 4. Ho-Lee: Citi's convention is `T1²`, not Hull's `T1·T2`

Citi never prints the formula, only *"the Ho-Lee model calibrated to cap/floor
vols"*. Solving for σ against the printed "Implied Vol" column of eight
published screens discriminates the two candidates cleanly:

| form | ratio σ_fit/σ_published across the 12-Jan-2017 table |
|---|---|
| `½σ²·mean(T1²)` (**citi**, default) | flat at 1.000 |
| `½σ²·mean(T1·T2)`, T2=T1+0.25 (**hull**) | drifts 0.933 → 0.975 |

Both are implemented. Hull's form is retained because it is the textbook result
and Hull's worked example (σ=1.2%, T1=8, T2=8.25 → 47.52bp) pins the arithmetic —
and it serves as a **negative control** that must fail against Citi's tables.

**Known-answer tie-out.** All 13 rows of Citi's SOFR screen (Rates Vol Lab,
12-Jun-2023, Fig 58, close 6/9/2023) reproduce to better than 1%, median ratio
0.9973, no maturity drift.

---

## 5. The matched-maturity swap must be quarterly

Citi specifies it verbatim — *"both fixed and floating legs of this swap have a
quarterly payment frequency"* — while the `usd_irs` rateslib spec carried by
`USD-SOFR-1D` quotes **annual** fixed (`spec frequency: 'a'`). At a ~3.2% rate
the compounding difference is ≈`3q²/8` ≈ 3.8bp: the same order as the convexity
adjustment being measured, so getting it wrong does not perturb the answer, it
*is* the answer.

Computing `CA = pack_rate − matched_swap_rate` against Citi's published 13-pack
SOFR screen:

| matched swap | mean error vs Citi | median error |
|---|---:|---:|
| spec default (annual fixed) | −3.89 bp | −4.31 bp |
| **quarterly / quarterly** | **−0.11 bp** | **−0.58 bp** |

`matched_forward_swap_rate()` defaults to Q/Q; the annual variant is kept as a
test negative control. The residual is within Citi's own rounding and snapshot
timing.

*(An earlier hypothesis attributed the offset to CME-vs-LCH clearing basis. The
measurement above rules that out: SOFR CCP basis is sub-bp, and the offset scales
with the rate level exactly as compounding predicts.)*

Re-running strat 2's own tie-out through its own code path after the fix:
median error **−4.31bp → +0.77bp** on the same packs. The backtest P&L is
unchanged, because P&L comes from the traded instruments rather than from the
measured adjustment; what improves is the screen's fidelity.

---

## 5a. Results at a glance

Measured, not projected. Full detail in `docs/convexityrv/results/`.

| | strat 1 (best structure) | strat 2 | strat 3 (objective-matching cell) |
|---|---|---|---|
| structure | 20Yx5Y/25Yx5Y | short SOFR pack CA, unhedged | 15Yx5Y/20Yx5Y @15bp |
| window | 2019-01..2026-08 (7.61y) | 2020-02..2023-09 (3.63y) | 2019-01..2026-08 |
| total | +468.3 bp net | +$3,209,018 | +$4,362,913 |
| annualised Sharpe | 2.95 (overlapping cohorts) | 0.191 | 0.335 |
| Sharpe ex-direction | — | — | **0.186** |
| hit rate | 84.2% gross | 74.3% per trade | — |
| mean carry | +0.000 bp/yr | — | **+0.087 bp/yr** |

The honest caveats attached to each of these are in §8 and are not optional
reading.

---

## 8. What the results do *not* show

* **Strat 1's signal is degenerate on the long end.** The curve breakeven vol is
  below 1Yx30Y ATMF on *every* day a vol exists (97.3%), so for the three
  long-end structures the rule never says "rich" and the book is a permanently-on
  flattener, not a timing strategy. 5Y/30Y is the two-sided control and does
  switch (45 flattener / 43 steepener cohorts). The 2.95 Sharpe is also an
  overlapping-cohort number — 76 one-year holds a month apart contain ~7.6
  independent years.
* **Strat 1 does not reproduce JPM's carry claim.** On 2019–2026 SOFR, 30s/50s
  carried *positively* (+1.36 bp/yr mean); JPM's −100.6 bp belongs to 2009–2017
  LIBOR. The forward structure's carry advantage here exists only against spot
  5Y/30Y (−5.44 bp/yr). Hit rate and dispersion do reproduce the ordering.
* **Strat 2 does not survive costs.** At 1bp round-trip per $100k DV01 both books
  go negative. The fly hedge *reduced* return (Sharpe 0.191 → 0.070) because on
  the near-dated packs the data can reach, the hedge regression is unstable
  (R² 0.2–0.6, β sign-flipping) — Citi fitted Blues, 3–4y out, which are not in
  daily reach offline. Two 2020 epochs nearly cancel (−$3.10M then +$2.85M).
* **Strat 3's headline Sharpes are mostly direction.** The mtm share of net
  averages 1.29 across the 15 pairs and is ≥0.88 for every one: the ultra-long
  forward curve inverted ~40bp over the sample, so a DV01-neutral flattener was
  long the biggest move in the window. Only **8 of 15 pairs** are profitable
  ex-direction. The whole `10Yx10Y/*` family's gamma harvest covers only
  0.48–0.63× its carry bill.
* **The grid winner fails multiple-testing.** `10Yx10Y/25Yx10Y` @40bp scores
  Sharpe 0.765, but expected max Sharpe under the null across 5,040 cells is
  **1.599**, and its deflated Sharpe gives p(true SR>0) = **0.011**. It is also
  short theta (−4.17 bp/yr, positive-carry on 2.0% of days). Flagged, not
  crowned.

---

## 6. What each strategy is

### Strat 1 — curve as gamma, versus swaptions
JPM, *An option by any other name* (03-Feb-2017), with the 2019 follow-up
*For cheap gamma, look to the long end*.

Signal: is the curve or the swaption the cheaper source of long gamma? Trade:
when the curve is cheap, put on the flattener and **sell** 1Yx30Y ATMF straddles
sized so the premium intake equals the carry over the horizon; when rich, reverse
both. Universe centres on `25Y/20Yx5Y` versus `30s/50s`, which is the note's own
comparison.

JPM's Exhibit 5 (trades initiated daily, post-2009, 1y horizon) is the reference
point, not a target — different sample, SOFR not LIBOR:

| | 30s/50s | 25Y/20Yx5Y |
|---|---:|---:|
| % cheap curve gamma | 70% | 100% |
| hit rate | 56% | 86% |
| avg P&L (bp of notional) | 10.4 | 11.4 |
| carry (bp) | −100.6 | +1.1 |

### Strat 2 — SOFR pack convexity versus a 2s5s10s butterfly
Citi's STIR screen, ported ED → SFR. Citi restated it for SOFR itself on
12-Jun-2023, so the port has a native target.

"Short convexity" = buy the futures pack + pay fixed on the matched 1y swap,
DV01-neutral. Hedged by paying the belly of a 2s5s10s swap fly sized to the
**regression beta** (`belly_DV01 = CA_DV01 · β/100`), not to the CA DV01 —
because the fly is a beta hedge for the vol exposure, and *"selling the 2s5s10s
fly as a hedge has the advantage of positive carry, unlike buying volatility."*

### Strat 3 — strikeless vol: long convexity that pays theta
Citi, *US Rates Vol Lab: Trading long-dated convexity* (09-May-2019), plus the
practitioner framing from the PM chat.

> "we enter $100K DV01 of flatteners, rolled every year. We delta-hedge by
> adjusting the notional on the longer end of the trade at each 25bp move in the
> longer rate (at market close)."

> "You just recalc the delta on the trades you do every 25 bp and then resize the
> notionals back to be dv01 neutral. Everytime you will be 'taking profit'. …
> That's how you delta hedge and treat 10y10y 20y10y as a vol trade - I think of
> it as strikeless vol."

The resize *is* the P&L: the flattener drifts long duration in a rally (the
received long leg gains DV01 faster), and re-flattening back to neutral books the
gamma. The objective is explicitly **long convexity with positive carry**, so the
grid search reports carry alongside Sharpe rather than optimising Sharpe blind.

Citi's own Fig 4 backtest (2013-12-31..2019-05-07, $100K DV01, 25bp hedging, net
of their costs) is the reference: Sharpes 0.05–0.35, best `10y10y/25y10y` at 0.35.

---

## 7. Test inventory

| file | what it pins |
|---|---|
| `test_convexity_rv_holee.py` | Hull's worked example; all 13 rows of Citi's SOFR screen; the citi-vs-hull distinction; Hull as a failing negative control |
| `test_convexity_rv_payoff.py` | flat smile ⇒ exactly Gaussian density; analytic quadratic expectation and breakeven; NaN rather than a guess on ATM-only days |
| `test_convexity_rv_matched_swap.py` | quarterly matched swap ties to Citi; annual is the failing negative control |

Every suite was mutation-checked: changing `0.5` → `0.55` in `ho_lee_ca` fails 3
tests, so the suites bite.
