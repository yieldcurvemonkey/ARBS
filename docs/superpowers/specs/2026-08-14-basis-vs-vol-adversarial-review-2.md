# Adversarial review #2 — basis vs swaption, against the dealer literature

**Date:** 2026-08-14 · **Branch:** `feat/basis-vs-vol` · **Supersedes parts of**
`2026-08-13-basis-vs-vol-v2-results.md`

Sources: J.P. Morgan *Special delivery* (4 Dec 2019), *Good things come to those who wait*
(18 May 2018), *Revisiting cheap gamma in Treasury/futures basis* (15 May 2020), *Why we should all
care about Treasury futures basis* (12 Mar 2020); BofA *US Rates Alpha: Buy futures basis = cheap
options* (10 Apr 2025); CFTC MRAC *The Treasury Cash-Futures Basis Trade and Effective Risk
Management Practices* (Dec 2024). Plus the `usd_repo_timeseries_history.xlsx` Velocity export.

---

## 0. Verdict

The V2 conclusion is unchanged and unaffected: **that leg is dead** on its own evidence, and none of
this literature bears on it.

What the literature does is falsify a claim I made about the **V1** side, and identify that the
framework prices the wrong option.

1. **The design ranks the delivery options backwards.** §2.4 calls the switch "dominant for ZB/UB"
   and the wildcard "small in the electronic era". Two dealers say the reverse for the modern
   regime. The correct statement is conditional, and the condition is measurable.
2. **My §4 delivery-option validation is retracted.** It was two omissions cancelling, against a
   vendor number printed to a resolution that could not have discriminated anyway.
3. **The repo workbook does not contain a term repo curve.** It contains something useful, but not
   the thing V1 was blocked on, and consuming it as though it did would have recreated the defect
   it was meant to fix.

Implemented in response: `RVUtils/BasisVsVol/wildcard.py` (the missing option, validated against
published values) and `MDP/CitiVelocityExcel/repo/store.py` (the repo pipeline, with the
degeneracy as an executable guard). 72 tests.

---

## 1. The framework prices the sub-dominant option

> "Pre-crisis, when yields were closer to the 6% level from which CTD conversion factors are
> derived, the switch option was the most important of these delivery options… **While the CTD bond
> still switches on occasion in multiple contracts, the switch is essentially valueless.** Yields
> today are much lower than the 6% reference rate, which causes the shortest duration bonds in the
> eligible delivery basket to always become CTD… **Delivery optionality — in today's yield curve
> environment, most notably the wildcard option — can comprise the majority of the net basis.**"
> — JPM, *Special delivery*, Dec 2019

> "TY and UXY offer different option focus, with TY more exposed to switches in the basket but also
> having a wild card (after futures close) delivery option, **while UXY has only wild card option**."
> — BofA, Apr 2025

The design doc's §2.4 table has this exactly inverted. The framework I built implements the switch
and treats the wildcard as an adjustment "with explicit error bars" that was never written.

**But the ranking is regime-conditional, and 2026 is not 2019.** The switch dies when yields sit far
below the 6% notional coupon, because the shortest-duration deliverable always wins. In Dec 2019 the
long end was near 2%. In Aug 2026 it is 5.24–5.31%, ~75bp below the notional coupon, and the vendor
sheet shows ZB Sep26 with a CTD delivery probability of 32–41% and **seven** deliverables above 1%.
That is a live switch. So the honest statement is:

| regime | switch | wildcard |
|---|---|---|
| yields far below 6% (2019–21) | ~dead | dominant |
| yields near 6% (2026) | **live** | suppressed by positive carry (§3) |

Both must be priced. Neither is "the" delivery option.

---

## 2. Retraction: the delivery-option tie-out was not evidence

`2026-08-13-…-results.md` §4 reported the two-bond switch model giving **1.05/32** for Ultra Bond
Sep26 against a printed **0-01**, and treated that as validating the delivery-option core.

Adding the wildcard — the component the literature says dominates — gives:

| contract | switch | wildcard | sum | JPM printed |
|---|---|---|---|---|
| Ultra Bond Sep26 | 1.05 | **1.57** | **2.62** | 1.00 |
| Bond Sep26 | 1.39 | 0.25 | 1.64 | 4.00 |

So the model that "tied out" overshoots by 2.6× once it is made more complete. The apparent
agreement was **two omissions cancelling**: a switch model missing the wildcard, matched against a
contract whose wildcard is large.

There is a second, independent reason the tie-out was never evidence: **the sheet prints delivery
option values to the half-tick** (`0-01`, `0-04`, `0-14+`). A printed 1-tick number is consistent
with anything in [0.75, 1.25]. At option values of 1–4 ticks, that resolution **cannot discriminate
between a switch-only and a switch-plus-wildcard model.** I read a wide bucket as a precise match.

What survives: the **crossover** tie-out (24.6bp computed vs 28.3bp printed, with the residual
attributable to JPM's beta-adjusted yields and convexity). Geometry validated; option value not.

Corrected in `switch.py`'s docstring and in the §4 table of the earlier report.

---

## 3. The wildcard, implemented and validated

`RVUtils/BasisVsVol/wildcard.py`, following the backward induction in JPM's *Good things come to
those who wait*.

**Mechanism.** The invoice is frozen at the futures settle but notice of delivery is due hours
later, and the cash bond keeps trading. A duration-hedged short holds `1/CF` face per contract and
delivers 1, so a post-close rally can be monetised on the `k = 1/CF − 1` **tail**; a sell-off costs
nothing because the short simply waits. Exercise on day *i* iff the tail payoff beats the
continuation value plus one more day of carry:

```
W_i = V_{i+1} + g          a_i = W_i / k
V_i = k·σ·φ(a_i/σ) + Φ(a_i/σ)·W_i          σ = σ_yield_bp × DV01
```

**Validation against published values** (`tests/test_bvv_wildcard_repo.py`):

| case | model | JPM published |
|---|---|---|
| FVM8, 1bp/2hr, FOMC ×2 | 0.65 ticks | 0.5–1.0 |
| TUM8, same, **with the negative gross basis the paper describes** | 0.69 ticks | ~0.75 |
| TUM8 at zero carry | 0.11 ticks | — |
| CF sweep 0.60 → 0.95 | 3.64 → 0.09 ticks | monotone, matches their Exhibit 6 |

The TU case is the one worth noting: the model only reaches JPM's number once the *negative* gross
basis that was the subject of their note is supplied. Getting it right at zero carry would have
meant being right for the wrong reason.

**A finding the literature states unconditionally and I can condition.** JPM: *"FOMC meetings timed
towards the end of the delivery month can likewise boost its value substantially."* Measured, the
sign of the late-vs-early effect **flips with carry**:

| daily carry (pts) | FOMC day 2 | FOMC day 14 | late − early | first exercise threshold |
|---|---|---|---|---|
| 0.000 | 3.095 | 2.833 | **−0.262** | 1.5bp |
| 0.006 | 1.778 | 1.936 | +0.158 | 2.5bp |
| 0.020 | 0.702 | 1.210 | **+0.508** | 5.8bp |

Carry sets the exercise threshold. With little carry the threshold is low, the option is exercised
in the first few days, and a late meeting is never reached. Their claim holds in the positive-carry
regime they were writing about — which is also the 2026 regime.

---

## 4. Carry is the governor, and it explains why 2026 flatters a switch-only model

> "With higher coupons now CTDs (vs repo financing rates ~ SOFR), **the cash carry of holding a long
> basis through delivery month is close to flat — making delivery options nearly flat cost for the
> entire delivery month.** This marks a difference from recent cycles where carry had typically
> become prohibitively negative going into the delivery month." — BofA, Apr 2025

Positive carry raises the wildcard's exercise threshold and suppresses it. In Aug 2026 term repo is
3.69% against a CTD coupon of 5.00%, carry is strongly positive, and the vendor sheet marks nearly
every deliverable `LD` (last delivery) — i.e. the model itself says nobody exercises early.

So the regime in which I happened to validate is the one in which ignoring the wildcard is least
wrong. That is luck, not design, and it does not generalise backwards: a historical V1 study
spanning 2019–2021 would sit in the opposite regime.

**This also connects the two workstreams.** The design's premise — basis is a cheap option — is
enabled by the coupon-versus-repo relationship, not by anything about vol. Which is precisely what
the repo data governs.

---

## 5. The repo workbook: what it is, and what it is not

`usd_repo_timeseries_history.xlsx` — 7,220 rows, 1998→2026, 63 tags. Now seeded into a proper store
at `MDP/CitiVelocityExcel/repo/store.py` with an incremental `--refresh` through the Excel add-in,
replacing the hand-saved workbook `BT/gss_fly/costs.py` reads.

**It contains no term repo curve.** `RATES.REPO.USD.<collateral>.SPOT.<tenor>` is quoted for 14
tenors from ON to 10Y and, measured across the whole history:

| collateral | days | max spread across all 14 tenors | days with any dispersion |
|---|---|---|---|
| USTREASGC | 1,255 | **0.0000 bp** | **0%** |
| USD5YOTR | 1,202 | 0.0000 bp | 0% |
| USD10YOTR | 1,953 | 0.0000 bp | 0% |
| USD30YOTR | 1,202 | 0.0000 bp | 0% |

ON equals 10Y **exactly**, on every day, for every collateral. Citi serves one number and replicates
it down the tenor axis. Treating that as a term repo curve would have reproduced — with a better
label — exactly the defect it was meant to fix. The check is an executable guard
(`assert_tenor_axis_is_degenerate`), so if Citi ever starts serving a real curve the test fails
rather than the docstring quietly going stale.

**What it does contain, and what each is good for:**

| series | coverage | use |
|---|---|---|
| GC overnight (secured) | 1,255 days from 2020-10 | **Replaces the overnight *unsecured* SOFR fixing** the basis path uses as its term repo today. Ties out: Citi 3.69188% on 2026-08-12 vs the 3.69% JPM used for Sep26. |
| OTR specialness (5y/10y/30y) | ~1,200 days | Sizing a sensitivity band only — see below. |
| **Term SOFR 1M/3M/6M/1Y** | 1,890 days from 2019 | **The only genuine term structure here**, and a defensible term-financing proxy: on 2026-08-12 it runs 3.6444 / 3.7558 / 3.8754 / 4.0330, and JPM's own Sep→Dec term repo (3.69 → 3.84) tracks its 1M→6M slope. |

**Specialness is real, large in the tail, and about the wrong bonds.** The 10y OTR is more than 1bp
special on 31% of days and more than 10bp special on 16%, with a 1st percentile of −50bp. Against
the design's §6.3 sensitivity (0.08/32 per bp of repo over a quarter), a 25bp special is 2/32 —
half the entire ZB Sep26 delivery option. But a future's CTD is **off-the-run** (ZB Sep26's is the
5% May 2045). The OTR series describe the most special corner of the market and are therefore an
**upper bound** on plausible CTD specialness, not an estimate of it. The store's docstring says so
and the accessor is named to make misuse awkward.

Net effect on V1: the term-repo blocker is **partially** cleared. A secured GC rate and a term SOFR
proxy are available; per-CUSIP CTD specialness still is not.

---

## 6. What the literature says the trade is actually worth

> "It is difficult to value precisely the options within the contract, but as options they are worth
> more than 0 ticks, and **probably somewhere around 1 tick fair value for TYM5**. Our futures model
> has the fair value of TYM5 at 1.5 ticks under parallel shift and curve twist assumptions **which
> we think may overstate the switch option by a modest amount.**" — BofA, Apr 2025

Two things follow.

**The prize is ~1 tick.** BofA enters at 0 to −0.5 ticks, targets +1 tick, and stops at −4. A 1:4
target-to-stop is not a mispriced-option trade; it is a high-hit-rate carry trade with a fat left
tail. This corroborates the earlier review's cost finding from an independent direction.

**A dealer says a parallel-shift switch model overstates.** That is exactly the assumption class of
`switch.py`. Combined with §2, the switch module should be treated as an upper bound on the switch
component, not a fair value.

---

## 7. The tail the backtest cannot see

> "In normal and even reasonably stressed times, these positions exhibit very low MTM volatility and
> have near-arbitrage terminal payoffs… **Near-arbitrage terminal payoffs do not, of course, ensure
> low MTM volatility.**" — JPM, 12 Mar 2020

> "The return in the basis trade is small, so **leverage is used to increase returns.** Stress on
> these trades therefore could present a potential financial stability risk if unwound rapidly and
> in large scale." — CFTC MRAC, Dec 2024

In March 2020 TY implied repo traded a **0%–3% intraday range in a single session**, against gross
levered-fund shorts JPM sized at up to $600–650bn, concentrated in TU, US and WN.

Consequences the design does not currently carry:

1. **The P&L is left-skewed with a rare, violent tail**, and the trade is only economic *with*
   leverage — which is what makes the tail lethal rather than merely unpleasant. §9's residual-risk
   list has swap spread, specialness, curve, roll and delivery risk. It does not have funding
   withdrawal or forced deleveraging, which is the one that has actually happened.
2. **Any backtest window without a dislocation measures the wrong distribution.** The V2 sample
   (2023-12 → 2026-03) contains none. A V1 study would need to span March 2020 to see the tail at
   all — and the vol-snapshot vintage cannot reach back that far.
3. **The structural wedge has a named cause.** The basis is held partly as balance-sheet
   maintenance under "use it or lose it" dealer allocation, not purely as RV. That is direct
   external support for the design's §2.9 item 1 and for the conclusion to trade the deviation, never
   the level.

---

## 8. Corrections and additions made

| | |
|---|---|
| `RVUtils/BasisVsVol/wildcard.py` | new — the missing option, backward induction, validated against JPM's published TU/FV/CF-sweep values |
| `MDP/CitiVelocityExcel/repo/store.py` | new — repo history via the add-in, incremental refresh, degeneracy guard, GC / specialness / term-SOFR accessors |
| `switch.py` docstring | tie-out retracted; crossover validation retained |
| `2026-08-13-…-results.md` §4 | retraction notice added |
| `tests/test_bvv_wildcard_repo.py` | new — 13 tests |

## 9. What is still wrong

* **The switch and wildcard are priced separately and added.** They are not additive: both are
  exercised into the same delivery decision, and a proper treatment values the maximum over a joint
  policy. Adding them overstates. This is why §2's 2.62 vs 1.00 is an upper bound on the discrepancy,
  not a measurement of it.
* **The end-of-month option is still not implemented**, and after the last trading day it is the
  only one left.
* **No per-CUSIP CTD specialness exists**, so V1's repo input remains a band, not a number.
* **The wildcard's post-close σ is assumed, not measured.** JPM fit it from price impact; ARBS has
  BrokerTec-style microstructure data nowhere. 1bp/2hr is a borrowed constant.
