# SR3 Futures-vs-Options RV Lab — Findings

**Date:** 2026-07-29
**Branch:** `feat/sfr-rv-lab`
**Design:** `2026-07-29-sfr-rv-lab-design.md`
**Executed notebooks:** `notebooks/backtests/sfr_rv_lab_*.ipynb`
**League table:** `notebooks/data/sfr_rv_lab/league_table.csv` (+ `_sorted.csv`)

## Summary

Nine frameworks were implemented and backtested on ~2 years of daily listed SR3
data (2024-07-01 → 2026-07-28, rolling front-8 strip). Every framework is marked
on listed settle premiums at strikes fixed on the execution bar, filled lag-1,
charged per completed trade, swept over a grid, sign-tested in both directions,
and graded by a uniform verdict that charges the search through a deflated
Sharpe.

## The league table in one line

**Nothing is ALIVE.** 47 rows across 20 framework variants: 0 ALIVE,
5 SELECTION-ARTIFACT, 21 MARGINAL-maker-only, 21 DEAD. The median deflated-Sharpe
probability across the whole table is **0.0000** against a 0.5 threshold, and
**0 of 47 rows has a positive median config**. Every positive number in the table
is the best corner of a sweep whose middle is negative.

| framework (best config) | n | net bp @taker | Sharpe | DSR p | grid median | verdict |
|---|---:|---:|---:|---:|---:|---|
| 2c. Digital-calendar shape fly | 168 | +326.0 | 0.62 | 0.015 | −435.5 | SELECTION-ARTIFACT |
| 6a. Fly vs belly straddle | 61 | +290.8 | 0.39 | 0.050 | −228.3 | SELECTION-ARTIFACT |
| 9a. Mid-curve forward vol | 6 | +271.9 | 4.98 | 0.031 | −18.1 | DEAD (too few trades) |
| 9c. Mid-curve skew term structure | 8 | +116.9 | 2.63 | 0.001 | −28.3 | DEAD (too few trades) |
| 3. Gamma/theta (IV−RV) | 47 | +64.6 | 0.46 | 0.015 | −201.4 | SELECTION-ARTIFACT |
| 1. Skew basis (RR spread) | 20 | +29.5 | 0.68 | 0.000 | −181.0 | SELECTION-ARTIFACT |
| 4c. Strangle (wing level) | 100 | +26.4 | 0.11 | 0.000 | −368.9 | SELECTION-ARTIFACT |
| 3b. Vol-return momentum | 28 | −31.9 | −0.29 | 0.024 | −266.8 | MARGINAL-maker-only |
| 3c. Cross-sectional vol carry | 40 | −46.8 | −0.64 | 0.000 | −277.1 | MARGINAL-maker-only |
| 4a. Wing harvest (naked, hedged) | 52 | −92.3 | −1.62 | 0.000 | −345.0 | MARGINAL-maker-only |
| 2. Digital calendar (delta-hedged) | 70 | −114.8 | −0.68 | 0.000 | −549.0 | MARGINAL-maker-only |
| 4b. Wing vertical (disaster buyback) | 51 | −120.8 | −4.67 | 0.000 | −303.5 | MARGINAL-maker-only |
| 6b. Vol butterfly (smile curvature) | 81 | −201.6 | −5.31 | 0.000 | −441.1 | MARGINAL-maker-only |
| 6c. Skew term structure (vol space) | 113 | −291.0 | −6.47 | 0.000 | −757.0 | DEAD |
| 5. Meeting lattice (vs FedWatch null) | 174 | −380.5 | −1.38 | 0.000 | −751.6 | MARGINAL-maker-only |
| 1b. Skew basis (delta-hedged) | 9 | −22.2 | −4.60 | 0.000 | −279.1 | DEAD (too few trades) |
| 7. FOMC event rule | 7 | −12.5 | −3.12 | 0.000 | −281.5 | DEAD (too few trades) |
| 9b. Mid-curve coupling digitals | 1 | −1.6 | −2.70 | 0.001 | −8.8 | DEAD (too few trades) |

Dollars assume **100 packages** with the package's own contract count printed in
each notebook's header (a 4-leg risk reversal is 4 contracts; a digital scaled to
one unit of probability is 24–32). At $25/contract/bp, the top row's +326bp is
+$815k on that sizing — and it is still a selection artifact.

Two diagnostics deserve their own mention because they are the reason to
disbelieve the top rows:

- **Framework 2 is the cleanest kill in the lab.** Across 108 configs, the
  unhedged options, the futures-only benchmark on the same signal, and the
  daily-delta-hedged options were **all 0% net-positive**. The options do not
  beat their own futures shadow, and hedging the deltas does not rescue them.
- **Framework 1's edge was direction, not skew.** The unhedged risk-reversal
  spread's best config makes +29.5bp; killing both contracts' deltas daily takes
  it to −22.2bp.

What follows are the results that do not depend on any strategy choice — the
constraints, the bugs, and the coverage limits — because those are the parts that
stay true regardless of how the grids come out.

## Structural results (measured, not assumed)

### 1. There is no mean-level RV, and the data proves it

Put-call parity holds on SR3 settles **to within a quarter-tick**: across all
two-sided strike-days in the panel, `|C − P − (F − K)|` has a median of 0.00bp
and a maximum of 0.25bp. The settlement process enforces it. Two consequences:

- Every surface's risk-neutral mean is pinned to its own futures settle, so any
  "options-implied fair value of a futures structure" is the traded structure.
- The synthetic-futures / conversion-reversal basis is **degenerate** — there is
  nothing to mine there, and a parity gate never binds.

### 2. The digital-calendar *level* is pinned by the linear market

For a non-negative rate, `E[f] = ∫ P(f ≥ K) dK`, so
`∫ [P_back(≥K) − P_front(≥K)] dK` is exactly the futures calendar spread.
Measured on real data across 147 pair-day checks: **correlation 0.9955** between
the integrated listed digital-calendar profile and the futures calendar spread,
median absolute gap 0.50bp — the residual being mass outside the quoted strike
ladder (median span 4.5% of rate), not tradeable slack.

So a digital calendar at a single strike is not a free object at the level — only
the **shape across strikes** is. This is why the framework trades the strike
butterfly of calendars and why the unhedged version had to be decomposed against
a futures-only benchmark.

### 3. Options price far more tail than the curve-only lattice

Solving per-meeting jumps from the futures strip with the exact day-weight matrix
and coupling FedWatch two-point lattices independently gives a curve-only
`P(rate ≥ K)`. Against the listed vertical:

| strike | listed `P(≥K)` | lattice null | gap | n |
|---|---|---|---|---|
| forward − 25bp | 0.687 | 0.856 | **−0.169** | 3,698 |
| forward | 0.540 | 0.541 | **−0.0002** | 3,673 |
| forward + 25bp | 0.360 | 0.148 | **+0.213** | 3,739 |

Two things to read here. First, **the at-the-money gap is exactly zero** — an
independent confirmation that the curve-only null and the listed surface share
the same mean, because both are pinned to the same futures settle. That is result
(1) arriving by a completely different route.

Second, the *tails* diverge hugely and persistently: the options price ~21
percentage points more probability above forward+25bp and ~17pp less below
forward−25bp than a two-point lattice coupled independently. That is the price of
everything the null discards — fat tails, non-25bp outcomes, intermeeting risk,
coupling. It is a **risk premium, not an arbitrage**, and where the null is
near-degenerate the "gap" signal is simply the listed digital under another name.

### 4. The listed quarterlies are too long-dated for a gamma harvest

In the rolling front-8 strip, contracts spend most of their life more than a year
from option expiry. A 5–20 day delta-hedged straddle on a 1y+ option is dominated
by **vega**, not by the gamma/theta exchange. Implied exceeds trailing realized
about 70% of the time with a median of +10.7bp, yet that premium does not
mechanically convert into delta-hedged P&L at daily-EOD hedging — the two are
different claims.

SR3 also settles on a **compounding quarterly average**, so once the reference
quarter starts accruing, front-contract implied vol decays for a purely
mechanical reason. Any vol-level ranking that ignores this finds enormous fake
alpha in the front contract; the notebook gates on time-to-expiry and shows the
decay directly.

The sharpest demonstration is the unconditional short-gamma benchmark. On a
partial panel holding only far-dated contracts it printed +347bp net of taker
costs at Sharpe 2.3 with an 84% hit rate. Adding the front contracts — the ones
with actual gamma — turned it into **−242bp at taker, Sharpe −0.73** over 152
trades. The apparent variance premium was an artifact of selling optionality on
contracts too far out to have any.

## Mid-curve extension: data-blocked, not disproven

The hypothesised symbol-resolution bug **does not exist**. The repo already maps
`0Q→MMA, 2Q→MMB, 3Q→MMC, 4Q→MMD, 5Q→MME` in `_BBG_TO_BARCHART`, `_UNDERLYING_RULES`
carries the +1..+5-year underlying offsets, and quarterly mid-curve roots are
inside `_PRE_IMM_FRIDAY_OPTION_ROOTS`, so `sofr_option_last_trade_date` returns
real dates for them. Only **weekly** mid-curves (`S01..S35`) return `None`, which
is deliberate and documented (rulebook 460A01.J.2 is not a function of the
contract code alone). Verified live: `0QZ26 → SFRZ27` last trade 2026-12-11,
`2QZ26 → SFRZ28`, `3QZ26 → SFRZ29`, all fetching smiles. Strike decoding is
correct too (`0QZ26|9450P` → price 94.50 against a 95.87 forward).

What blocks the mid-curve frameworks is the **chains themselves**:

- **Moneyness.** A listed mid-curve strike sits within 50bp of the forward on
  **0.5%** of pair-days, and within 100bp on **1.1%**. An ATM straddle cannot be
  constructed on 99% of days, so listed forward vol is not observable.
- **Open interest.** Median OI is **zero**; only 6.3% of mid-curve quotes carry
  500 lots or more. The marks are settle prices with no demonstrated liquidity.
- **History.** Useful overlap with a quarterly on the same underlying is 70 days
  (`0QZ26`/`SFRZ27`) and 112 days (`2QZ26`/`SFRZ28`). The 0Q cycles before Z26
  have essentially no history in this feed (`0QU26`: one day, six quotes).

The three frameworks were rebuilt to use strikes that exist — matched-strike
straddles, digitals drawn from the mid-curve's own ladder, widest-available wing
pairs — and they do produce panels, but every variant lands under the ten-trade
floor. **Verdict: data-blocked.** Mid-curves remain the right instrument for the
coupling dimension; this feed cannot support the test.

## Bugs found and fixed (each one had produced a fake result first)

1. **`delta_abs` is quoted in percent, not as a decimal** (ATM ≈ 46). Every daily
   futures hedge was 100× oversized, producing hundreds of bp per trade on
   one-contract packages. Detected and normalised in `MarkBook`.
2. **Hedge costs were credited to short positions.** `hedged_path` folded
   cumulative re-hedge cost into the package value, which the engine then
   multiplied by the trade direction. The tell was the unconditional gamma
   benchmark showing long *and* short both gross profitable.
3. **The call-side vertical implies `P(rate < K)`, not `P(rate ≥ K)`.** With
   automatic OTM side-selection this silently mixed conventions across strikes.
4. **Fixed-horizon exits were lagged twice.** A deterministic exit date is known
   at entry; only signal-driven exits cost a lag day.
5. **"Always short" benchmarks were not always short.** Driving an unconditional
   program through the z-score path with a dummy signal flips the side every bar.
   Added `entry_rule='always'`.
6. **ITM legs were being frozen.** The vendor panel is OTM-only, so a strike that
   crosses the money stops printing and was forward-filled — 40–50% of marks in
   the wing frameworks. `complete_by_parity` reconstructs the missing side
   exactly (parity holds to a quarter-tick), cutting mean staleness from 5.4% to
   1.0% and worst-case from 48% to 14%.
7. **A back-fill look-ahead** in the hedge path pulled deltas and futures prices
   backwards into leading gaps.

Every one of these inflated results before it was found. The digital-calendar
framework read as +1,058bp (and +12,593bp hedged) before fixes 1 and 2; after
them, 0–1% of its configs are net positive.

## What I would test next

1. **Shorter-dated listed options.** The gamma finding is horizon-limited, not
   disproven. SR3 weekly and serial options sit where the gamma/theta exchange
   actually dominates; they are the natural next panel.
2. **A liquidity-screened mid-curve feed.** The coupling dimension is still the
   most interesting untested basis. It needs a source with near-the-money
   mid-curve strikes and real OI — CME direct rather than this vendor path.
3. **Intraday.** Every basis here has a sub-1-day half-life in the prior work's
   measurement. Daily EOD may simply be the wrong frequency for the shape bases,
   and the repo already has intraday SOFR curve infrastructure.
4. **The sample-composition lesson, applied to whatever comes next.** On a
   partial panel containing only far-dated contracts, the unconditional
   short-gamma program looked like the one survivor: +347bp net of taker costs,
   Sharpe 2.3, 84% hit rate. Completing the strip with the front contracts
   reversed it to **−242bp at taker, Sharpe −0.73** over 152 trades. Short gamma
   made money precisely where there was no gamma to be short of, and lost it
   where there was. Any future result on this panel should be re-run against the
   full maturity cross-section before it is believed — the composition of the
   sample was worth more than any parameter in the grid.
