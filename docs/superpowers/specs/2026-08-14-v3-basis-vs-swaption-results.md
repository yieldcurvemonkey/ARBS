# V3 — the basis as an option vs a matched swaption · results

**Date** 2026-08-14 · **Branch** `feat/bvv-v3-basis-swaption` · **Sample** 2019-01-02 → 2026-08-11,
daily · **Pre-registration**
[`2026-08-14-v3-basis-vs-swaption-preregistration.md`](2026-08-14-v3-basis-vs-swaption-preregistration.md),
committed before any result here existed.

Source: **Citi Research, *US Rates Weekly — Summer lull*, 17 July 2015.**

---

## The answer

**Best-Sharpe cell of the 216-cell grid** (198 produced trades, 162 cleared the 10-trade floor):

| | |
|---|---|
| **key** | **`UB/B/e1.1/x1/h10/tp4`** |
| root / arm | **UB** (Ultra Bond) / **B** — long basis + short gamma-matched ATMF receiver |
| entry richness | **1.10** |
| max hold / take profit | 10 days / 4.0 ticks |
| **Sharpe** | **−0.230** |
| trades | 15, hit rate 53.3%, total **−10.76/32** |

| | value | bar | |
|---|---|---|---|
| trials | 162 | | |
| **E[max Sharpe \| null]** | **0.638** | | best is **−0.230** |
| **deflated Sharpe** | **0.0040** | > 0.95 | ✗ |
| sign-flip permutation | 0.2335 | > 0.95 | ✗ |
| break-even cost | 0.0× | > 2.0× | ✗ |
| **grid median Sharpe** | **−0.721** | | |
| **cells with positive Sharpe** | **0 of 198** | | |
| **alive** | **false** | | |

**Not a single configuration in the grid is profitable.** This is a cleaner death than V1's: V1 at
least produced a positive winner that failed on deflation. V3 does not produce a positive cell at
all, on any root, in either arm, at any of the twelve knob settings.

## What the ablation says — the question V3 existed to answer

| arm | what it trades | trades | Sharpe |
|---|---|---|---|
| **A** | long basis, entered on richness (the note's literal trade) | 15 | −0.246 |
| **B** | long basis + short gamma-matched receiver (the RV structure) | 15 | **−0.230** |
| **C** | cheap net basis alone, no vol leg (the ablation) | 119 | **−0.395** |

The swaption comparison **does** add information: B and A both beat C by a wide margin
(−0.23 / −0.25 against −0.40), and the hedge in B improves on the outright in A. **The note's core
claim — that comparing the basis to a swaption is a better way to decide than looking at the basis
alone — survives.** It simply does not survive into profit. The richness filter turns 119 losing
trades into 15 smaller losing trades.

That distinction matters, because it is the opposite of V1's outcome, where the delivery-option
model added 0.035 of Sharpe over a raw z-score and was declared decoration.

---

## Why it fails, and it is not the trade's fault

**The premise does not hold in this sample.** The note's trade works when the CTD switch is close —
its own setup has the forward yield 30bp from a switch. Measured over 2019–2026:

| | ZB | ZN | UB |
|---|---|---|---|
| median \|crossover\| | 131bp | 140bp | 89bp |
| \|crossover\| < 25bp | 29.1% | 30.4% | 29.9% |
| richness > 1 (basis cheaper) | 8.4% | 16.8% | 4.1% |

The distribution is **bimodal** — p10 ≈ 5bp, median ≈ 130bp — so the switch is either right on top
of you or nowhere near. And with the crossover typically 130bp away, the delivery option is nearly
worthless while the market net basis is a median 1.8/32. **The net basis in this period is mostly
not switch optionality**; it is carry, financing, the wildcard and the rest of the basket.

That is the finding. The trade is a bet on CTD-switch convexity being cheap, and for most of
2019–2026 there was very little CTD-switch convexity to buy at any price.

### A rejected implementation, recorded because it was more elegant and wrong

The first version inverted the market net basis for an implied switch vol, which makes richness
collapse to the beautiful `(σ_swaption / σ_switch)²`. It is degenerate: forcing a two-bond model
sitting 130bp out of the money to explain a 1.8/32 net basis returns implied vols of **400–1000bp**
against a swaption vol of ~81bp. The note itself mixes a **model** gamma with a **market** cost, and
the shipped implementation does the same.

---

## Faithfulness to the note

The known-answer gate in the notebook asserts the note's own arithmetic from its own stated inputs:

```
4.2 ticks on $100mm            -> $131,250      (note: "$130K")
swaption/basis cost ratio      -> 1.438         (note: "approximately 1.4 times")
basis cost per unit gamma      -> 309.5
swaption cost per unit gamma   -> 445.2
richness = 445.2 / 309.5       -> 1.438
```

and the closed form the whole comparison rests on, verified numerically against the repo's own
`bachelier.py` rather than only algebraically:

```
cost/gamma of an ATMF normal swaption = sigma^2 * T     (4050.0 == 4050.0 bp^2)
```

The note is from **July 2015** and the vol cube starts **2015-10-08**, so reproducing its market
numbers is impossible; that was declared in the pre-registration rather than attempted.

**The annuity cancels** out of the swaption's cost-per-gamma. That is load-bearing: the entry signal
needs no curve, no notional convention and no swap-spread assumption. A forward rate is required
only to *mark* an already-open short receiver, so every curve assumption is contained strictly
downstream of the decision to trade.

---

## Prediction scorecard

| pre-registered prediction | outcome |
|---|---|
| "Arm C will be hard to beat" | **WRONG** — A and B both beat C clearly (−0.23/−0.25 vs −0.40) |
| "richness will spend most of its time > 1" | **WRONG, and badly** — it is > 1 on only 4–17% of days |
| "most likely outcome: dead" | right |
| "if there is an edge it shows as a level shift, not one cell" | vacuous — there is no positive cell |

Two of four predictions were wrong in the same direction: I expected the basis to look cheap most of
the time and the vol comparison to be redundant. The data says the basis usually looks *expensive*
per unit of gamma, and the vol comparison is the most useful part of the signal.

---

## Deliverables

| | |
|---|---|
| strategy | `RVUtils/BasisVsVol/v3.py` |
| panel assembly | `RVUtils/BasisVsVol/v3_panel.py` (1,884–1,905 rows/root, 99.6% with a richness, 100% with a forward) |
| grid runner | `RVUtils/BasisVsVol/run_v3_grid.py` |
| QDB runner | `BT/signals/basis_swaption.py` |
| configurable notebook | `notebooks/backtests/basis_vs_vol/basis_v3_configurable_backtest.ipynb` — 12 code cells, executed, 0 errors |
| grid notebook | `notebooks/backtests/basis_vs_vol/basis_v3_grid_search.ipynb` — 7 code cells, executed, 0 errors |

**QueryDrivenBacktest agreement.** Arm A reproduces the reference engine **exactly** on all three
roots (UB −344,187.34, ZB −1,446,945.45, ZN −528,986.27; trade counts 15/15, 34/34, 49/49). Arm B
agrees to within **$2.40 on $1.5m** because its swaption leg is booked at unwind rather than marked
as a second product — a stated limitation, not a silent one.

## Limitations, declared

1. **Sticky-ATM marking** of an open short receiver: the cube is ATM-only before 2020-01-24.
2. **2020-01-24 → 2020-03-24** carries no expiry under 4Y in the cube — 40 days, exactly COVID, and
   exactly the short-expiry vol this trade most wants. Those days are **dropped, not bridged**;
   bridging a vol spike is how a backtest invents a trade that never existed.
3. **Static gamma matching** at entry; no re-hedging.
4. **Arm B's QDB path** marks the basis leg only.
5. **Small trade counts.** The winning cell has 15 trades. Nothing here would be significant even if
   the sign were positive, which it is not.
