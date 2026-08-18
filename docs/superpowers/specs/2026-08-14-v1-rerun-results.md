# V1 re-run on the repaired data layer — results

**Date** 2026-08-14 · **Branch** `feat/basis-vs-vol-v1-qdb` = `fix/ustf-data-layer` (PR #455) +
`feat/basis-vs-vol` (PR #454) · **Pre-registration**
[`2026-08-14-v1-rerun-preregistration.md`](2026-08-14-v1-rerun-preregistration.md), committed
before any result here was read.

---

## The answer

**Best-Sharpe cell of the 324-cell grid:**

| | |
|---|---|
| **key** | **`UB/w126/e2.5/x0.5/h10/sv90`** |
| root | **UB** — Ultra Bond |
| z_window | **126** |
| entry_z / exit_z | **2.5 / 0.5** |
| max_hold_days | **10** |
| switch_vol_bp | **90** |
| **Sharpe** | **0.320** |
| trades | 52, hit rate 51.9%, mean +4.02/32 per trade |

**And the number that says what that means:**

| | value | bar | |
|---|---|---|---|
| trials | 324 | | |
| **E[max Sharpe \| null] at 324 trials** | **0.503** | | winner scores **below chance** |
| **deflated Sharpe** | **0.297** | > 0.95 | ✗ |
| t (Newey–West) | 1.331 | | |
| bootstrap 95% CI | **[−0.224, 0.651]** | | straddles zero |
| top-3 trade share | **1.104** | < 0.60 | ✗ |
| sign-flip permutation | 0.9095 | > 0.95 | ✗ |
| break-even cost | 3.0× | > 2.0× | ✓ |
| ablation: model vs raw BNOC | 0.320 vs 0.285 | model must add | ✗ |
| **alive** | **false** | | |

**V1 is still dead — but now for real reasons rather than data reasons.** That distinction is the
point of the exercise, and it could not be made before.

### Why the winner is not a strategy

Two numbers finish it independently of any deflation argument:

- **One year is the whole P&L.** 2020 contributes **+238.70/32** of a **+209.03/32** total. Every
  other year sums to **−29.67**, and five of the nine are negative.
- **Three trades are 110% of the P&L.** Top-3 = 230.78/32; the other 49 trades sum to **−21.75**.

| year | 2018 | 2019 | **2020** | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| P&L (32nds) | −3.6 | −14.3 | **+238.7** | −10.0 | +8.3 | −5.5 | +10.2 | +0.7 | −15.5 |
| Sharpe | −0.26 | −0.41 | **+1.13** | −0.34 | +0.22 | −0.21 | +0.37 | +0.01 | −1.08 |

Costs are **not** the binding constraint (break-even 3.0×, and it is still +0.24 at 3× cost). The
constraint is that there is nothing there outside one dislocation.

### The delivery-option model earns nothing

The pre-registration made this a kill condition in its own right, and it fires:

| model | Sharpe | trades |
|---|---|---|
| switch + wildcard (full V1) | 0.320 | 52 |
| switch only | 0.322 | 57 |
| wildcard only | 0.288 | 54 |
| **no model (raw BNOC z-score)** | **0.285** | 59 |

The entire intellectual content of V1 — modelling the switch and wildcard options and trading the
residual — buys **0.035 of Sharpe** over simply fading the net basis. By its own pre-registered
standard, "the delivery-option machinery is decoration and the honest name for the strategy is
*fade the net basis*."

---

## Against the prior verdict

| | prior run (corrupt data) | this run (repaired data) |
|---|---|---|
| best cell | `ZN/w252/e1.5/x0.5/h10/sv90` | `UB/w126/e2.5/x0.5/h10/sv90` |
| Sharpe | 0.381 | 0.320 |
| trials | 216 | **324** |
| E[max \| null] | 0.478 | 0.503 |
| deflated Sharpe | 0.435 | **0.297** |
| grid median Sharpe | −0.144 | −0.090 |
| positive cells | 25% | 33% |
| **alive** | false | **false** |

Both runs share the same structural failure: **the winner of the entire search scores below what
chance produces at that trial count.**

### The reproduction check, which makes the comparison mean something

Running the prior winning cell on the **original** panel with the **current** code returns
**Sharpe 0.3809** against the published 0.381 — 21 trades, 42.9% hit rate, matching the published
table exactly. The merged tree reproduces the old result bit-for-bit, so every difference below is
attributable to the data and not to code drift.

### Same cell, before and after — the number immune to selection

`ZN/w252/e1.5/x0.5/h10/sv90`, the prior winner, re-evaluated:

| | original panel | repaired panel |
|---|---|---|
| usable rows (after gate) | **662** | **2,043** |
| Sharpe | **0.381** | **0.181** |
| trades | 21 | 175 |
| hit rate | 42.9% | 52.0% |
| top-3 share | 1.273 | 0.918 |

The cell that won the old search loses **half its Sharpe** when its input becomes a real net basis,
while trading eight times as often on a three-times-larger sample. Its old 0.381 was drawn from 662
days that had survived a gate which rejected 65% of the root — and, underneath that, from a series
where the CTD was a bond that could not be delivered.

*(An earlier interim figure of 0.125 for this cell was measured on a pre-resume panel of 2,016 rows;
0.181 on the final 2,043-row panel is the number that stands.)*

---

## Per-root, and the one genuinely interesting result

| root | cells | best | E[max \| null] | **grid median** | **positive cells** |
|---|---|---|---|---|---|
| UB | 108 | 0.320 | 0.246 | −0.083 | 18% |
| ZB | 108 | 0.242 | 0.300 | −0.165 | 9% |
| **ZN** | 108 | 0.314 | 0.505 | **+0.157** | **72%** |

One number in that table deserves naming rather than leaving for a reader to find: **UB's best
(0.320) exceeds UB's own per-root E[max | null] (0.246)**, where ZN's does not. It changes nothing,
for three reasons. Choosing UB *because it won* is precisely the selection the 324-trial null
(0.503) exists to price, so the per-root figure is computed on a subgrid picked after the fact. The
cell fails top-3 share, the permutation test and the ablation independently of any null. And all of
its P&L is in one year. A per-root null is the right comparison only for a root chosen in advance —
which UB was not.

**ZN's whole surface lifted.** Prior ZN: grid median −0.144, 25% of cells positive. Now: median
**+0.157**, **72%** positive, inter-quartile range [−0.055, +0.236]. A fluke lifts one cell; a
*level* shift across 108 configurations is what a weak-but-real effect looks like.

I am deliberately **not** claiming that as a finding. Reasons to distrust it, stated rather than
buried:

- ZN's best cell (0.314) is still **below its own** E[max | null] (0.505), so nothing in the grid
  clears the pre-registered bar.
- The 108 cells are heavily overlapping — same panel, adjacent parameters — so "72% positive" is
  nothing like 108 independent successes.
- The effect is small in absolute terms: ZN's best cell earns **0.86/32 per trade**, against a
  round-trip cost assumption of 0.5/32. That is a thin margin.

What it does justify is a **narrow, separately pre-registered** follow-up on ZN alone — not a claim,
and not a reason to keep searching this grid.

### ZB behaved exactly as a control should

ZB's panel is numerically identical to the original (max abs difference **0.000000** across all ten
columns; CTD bond unchanged on every day checked). Its grid is the weakest of the three — median
−0.165, 9% positive. The classic bond basis, measured correctly all along, has no edge here.

---

## The QueryDrivenBacktest requirement

V1 already ran through QDB (`Query/BasisPair` → `BT/signals/basis_pair.py::run_v1_qdb`); the
reference engine emits the trade schedule and QDB prices and marks it. **The winning cell was run
through it:**

```
UB/w126/e2.5/x0.5/h10/sv90
  QDB final 6,532,181.82 | reference final 6,532,181.82 | agree: True
  QDB closed positions 52 | reference trades 52
```

The prior claim of "exact agreement" turned out to be weaker than it sounds — the test behind it
compares the **final total and the trade count, with costs switched off**. On real panels the totals
do agree to the cent and trade counts agree exactly (ZN 175/175, ZB 134/134, UB 167/167), but the
daily **paths** differ, and Sharpe is a property of the path:

(on the committed panels; an earlier version of this table was measured on pre-resume panels and
its numbers will not reproduce)

| cell | ref final | QDB final | ref Sharpe | QDB Sharpe | trades |
|---|---|---|---|---|---|
| `ZN/w252/e1.5/x0.5/h10/sv90` | 1,088,198.01 | 1,088,198.01 | 0.1814 | 0.1968 | 175/175 |
| `ZB/w126/e1.5/x0.5/h21/sv70` | −3,406,378.88 | −3,406,378.88 | −0.2120 | −0.2462 | 134/134 |
| `UB/w126/e1.5/x0.5/h21/sv70` | −1,794,432.15 | −1,794,432.15 | −0.0775 | −0.0887 | 167/167 |

That is a convention, not a disagreement, and it is now characterised and pinned by test:

```
qdb_equity[t] == reference.equity[t]        on exit days
qdb_equity[t] == reference.equity[t - 1]    on every other day
```

QDB marks an open position at the previous close and settles in full at unwind, and the round-trip
fee lands at unwind because the framework has no entry-side hook. On the real ZN panel **all 160
divergent days are exit days and none is a roll day**, so nothing about this touches the roll guard.
Reported Sharpes are the reference engine's, which is what the grid uses.

---

## What was fixed in the harness before the run

Two defects in `build_basis_panel.py` would each have silently corrupted the sample:

1. **The gate now raises by default**, and the builder wraps every day in `except Exception:
   continue` — so every gate-failing day would have vanished from the panel as though it were a
   market holiday. Now passes `on_bad_data="warn"`.
2. **`data_ok` was still the bespoke `abs(min_gross32) < 32` gross-basis rule**, which
   `run_v1_results.py` genuinely reads via `filter_data_ok`. Gross basis contains carry, so that
   rule rejected 58% of healthy ZB in 2021 and passed nothing that would have caught the Ultra Bond
   serving an FX rate. It now uses the shared carry-adjusted gate.

Panel quality, rebuilt daily 2018-06-01 → 2026-08-13 with term financing:

| root | rows | gate pass | prior rows | prior gate pass |
|---|---|---|---|---|
| ZB | 2,052 | 96.7% | 1,905 | 85.4% |
| ZN | 2,049 | 99.7% | 1,886 | **35.1%** |
| UB | 2,031 | 99.8% | 1,669 | **1.9%** |

UB entering the grid at all is what moved the trial count 216 → 324, and it entered on the
**pre-existing** rule: `ROOTS` already listed it, and the loader's `min_rows = 200` floor had been
dropping it.

---

## Prediction scorecard

From the pre-registration, written before any output:

| prediction | outcome |
|---|---|
| "ZB will barely move" | ✓ panel numerically identical; weakest grid of the three |
| "ZN will change a lot but I do not expect it to become alive" | ✓ transformed, still not alive |
| "UB is the genuine unknown" | ✓ it produced the winner — and the winner is one year and three trades |
| "Most likely: still dead, for real reasons rather than data reasons" | ✓ |

---

## Bottom line

The literal answer to "find the best params optimising for Sharpe" is
**`UB/w126/e2.5/x0.5/h10/sv90` at Sharpe 0.320**. It is not tradeable: it is below the null for its
own search, three trades are 110% of its P&L, one year is all of it, and the delivery-option model
that justifies the strategy's existence adds 0.035 of Sharpe over a raw net-basis z-score.

The one result worth carrying forward is not the maximum but the **level**: ZN's grid median moved
from −0.144 to +0.157 and its positive-cell share from 25% to 72% once its basket stopped containing
bonds that were not deliverable. That is a change in the data, correctly measured — and it is the
kind of thing that only becomes visible after someone fixes the feed.
