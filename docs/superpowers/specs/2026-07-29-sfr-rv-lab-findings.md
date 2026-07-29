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

The headline is in the league-table notebook. What follows are the results that
do not depend on any strategy choice — the constraints, the bugs, and the
coverage limits — because those are the parts that stay true regardless of how
the grids come out.

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
Measured on real data across pair-days: **correlation 0.97** between the
integrated listed digital-calendar profile and the futures calendar spread, with
the residual explained by strike-ladder truncation.

So a digital calendar at a single strike is not a free object at the level — only
the **shape across strikes** is. This is why the framework trades the strike
butterfly of calendars and why the unhedged version had to be decomposed against
a futures-only benchmark.

### 3. Options price far more tail than the curve-only lattice

Solving per-meeting jumps from the futures strip with the exact day-weight matrix
and coupling FedWatch two-point lattices independently gives a curve-only
`P(rate ≥ K)`. Against the listed vertical:

| strike | listed `P(≥K)` | lattice null | gap |
|---|---|---|---|
| forward − 25bp | 0.65 | 0.96 | **−0.31** |
| forward | 0.51 | 0.60 | −0.09 |
| forward + 25bp | 0.36 | 0.04 | **+0.32** |

The gap is enormous and persistent (sd ≈ 0.07 at the wings). That is the price of
everything the null discards — tails, non-25bp outcomes, intermeeting risk,
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
4. **The unconditional short-gamma program, properly stress-tested.** It is the
   only thing in the lab that clears taker costs, and it has no fitted parameter
   — which makes it the one result worth attacking with regime splits, tail
   analysis and a longer sample rather than another grid.
