# Citi's published convexity trade, backtested in its own framework — DEAD

Block 5 of the convexity RV programme. Backtests **Citi's actual published
trade** — the screen across the strip, the fitted hedge, the five-condition
entry conjunction, the dollar target and stop, short only, held through the
quarterly rolls on dated instruments — as a faithful, pre-registered,
engine-certified rule.

Sources: Citi Research, *NA Rates Trade Idea*, 09 Feb 2017, Bikbov & Williams,
*"Sell Blues convexity adjustments, hedged"* (`print (12).pdf`), and its origin,
*US Rates Weekly*, 13 Jan 2017 (`print (15/18).pdf`).

---

## Verdict

**A small-sample gross edge on the trades it selects, which loses money on the
engine after its own declared costs, on a book too sparse to run.** The two
clocks the pre-registration required say different things and both are true:

| clock | gross | net of 1× costs |
|---|---:|---:|
| **annualised** (`E[max SR \| null]` = 0.9066 at 23 trials, 4.682 y) | 0 of 23 | 0 of 23 |
| **per-hold** (each cell at its own `n_eff`) | **8 of 23** | **0 of 23** |

And on the **engine**, which prices the real dated instruments net of the same
declared costs, **all nine certified books lose money** — the least bad at
−$148,275, the best engine Sharpe −0.0093.

Best per-hold Sharpe **+1.3346 gross / +0.6362 net** against a bar of 0.9808 —
on **four trades**. Best shared-sign-flip p on net per-episode P&L anywhere in
the block: **0.161**. The headline — the note's own trade at the note's own
thresholds — opens **twice in 4.7 years** for a panel net of **−$1,189,942** and
an engine net of **−$1,168,738**.

## The finding that generalises

**Citi's five-way entry conjunction is satisfied on 2 of 1,409 dates**, and the
reason is inside the rule rather than in the data. The pairwise lift on BLUES:

* `wide_to_model × implied_rich` = **0.34** — a CA that is wide to the Ho-Lee
  model occurs when *realised* vol has been high, so implied/realised is low at
  exactly the moment the model calls the adjustment rich;
* `wide_to_model × positioning_stretched` = **0.43** — the note's own causal
  chain runs the other way on SOFR (`corr(CA-vs-model, dealer 1Y z) = −0.187`),
  even though the dealer-takes-the-other-side identity holds at −0.985;
* `wide_to_model × wide_to_fly` = **2.59** — better than independence, but the
  two "wideness" measures the note treats as one signal pass 2.3% of days each
  and **0.14% jointly**.

A conjunction reads in prose as one signal with several confirmations. Measured,
it was three signals that rarely agree.

## What is new in the tree

| | |
|---|---|
| `RVUtils/ConvexityRV/citi_fv.py` | Citi's Figure-6 fair value: three fits (free / fly-constrained / Citi's published weights), refit at every quarterly IMM roll on a window ending strictly before it. **Promoted out of the reproduction notebook** so a backtest can import it; the notebook now imports it back, and `_p4_tieout_repro.py` pins the module against the reproduction's own recorded path — the mid-2023 sign reversal of `b`, the residual table (2.232 / 2.149 sd, 1.674 / 1.892 mae) and the fly-start ranking. All reproduce to the third decimal. |
| `RVUtils/ConvexityRV/citi_screen.py` | Figure 20 as a per-date panel. `CA − Model − VsModel = 0` exactly; the roll column is the analytic `−θ/4` because colour packs are one YEAR apart, and `roll_identity()` measures it against the term-structure form rather than asserting an equality the granularity cannot support. |
| `RVUtils/ConvexityRV/citi_rule.py` | The conjunction, the screen selection, the dollar target/stop state machine, the 23 declared cells, the stats and null bars. |
| `RVUtils/ConvexityRV/citi_engine.py` | `QueryDrivenBacktest` wiring for a **fitted-weight** fly (`bpv` is **1×**, not `gv_engine`'s 2×, because a `[w2, 1, w10]` package earns exactly `bpv` per bp of `r5 − w2·r2 − w10·r10`) and **per-segment tags**, so the hedge can be re-struck at each quarterly refit without unwinding the futures pack. |
| `docs/convexityrv/citi-framework-preregistration.md` | 23 cells, frozen and committed **before any P&L was computed**. |
| `docs/convexityrv/results/citi-framework-backtest.md` | the full write-up. |
| `notebooks/backtests/convexity_rv/citi_framework_backtest.{py,ipynb}` | executed through the gate at 0 unrun / 0 errors. |
| 4 test files + a 40-mutant harness | every mutant killed. |

## Three things measured that changed the design, before the freeze

1. **The roll splice belongs in the P&L and NOT in the signal.** The roll jump
   IS the CA's theta being paid back (1.024× the quarter-theta on BLUES), so a
   constant-rank CA is stationary *because* of it and the spliced series carries
   the whole undone decay as a ~20 bp drift — its 252-day rolling z sits at a
   median of −1.15 to −1.31 instead of −0.20 to −0.53.
2. **The conjunction fires twice**, so the pre-registration declares a
   **two-rung threshold ladder** (the note's 2.0σ and a widened 1.0σ) and prints
   the rungs it does not walk (1.5, 0.5, 0.0 → 2, 30, 51 days).
3. **A single multi-year `IRSwapsTB` span request returns different par rates
   for the same dates than the year-chunked request does** — up to 1.21 bp on
   the 10y. The carried leg panel is exact on 1,409 of 1,409 dates under the
   request shape it was built with.

## Controls, all declared in advance

* **same-day fills** are worth **$1.88m–$17.76m more** on every cell — the
  mark-noise harvest, and the reason `exec_lag_bd = 1` is the convention;
* the **placebo ladder** kills every cell that makes money unlagged by 40 bd;
* the **always-short control** is profitable on 15 of 16 (cell, structure)
  pairs with the signal off — what the trade IS, when it works, is
  short-convexity carry;
* **β = 0**, like-for-like (same contexts, same episodes, fly leg removed): the
  fly adds Sharpe on 3 of 5 cells and removes it on 2, and **Citi's own
  published 0.705/−1/0.465 weights are the worst**, at −0.32 of Sharpe and
  −$1.01m against the same five episodes with the hedge simply removed;
* the **convexity signature** as a point prediction, in the 2-parameter
  linear-in-variance form the identity actually gives: the clean unhedged row
  fits −64.12 against a predicted −128.87 — right sign, half the magnitude, on
  four points.

## The adversarial review, and what it changed

A six-lens fan-out over the FINISHED work — look-ahead, signs/units,
pre-registration fidelity, statistics, data/API misuse, test quality and
doc-vs-artifact — with **every finding sent to a separate skeptic instructed to
refute it**. 22 raised, 12 survived, reducing to **7 distinct defects, all 7
fixed and every number re-run**. Two were material:

* **the engine never charged the fees it computed** (`fee_by_tag` built and
  never passed), so every "engine net" in the certification table was a GROSS
  number. Charged, all nine books are net negative and the block's best cell
  goes +$3.36m → −$190,110. This is the one defect that flattered *alive*, and
  fixing it makes the verdict stronger;
* **the fair-value stability table was fitted on the roll-spliced CA**, a series
  the rule never fits. On BLUES the spliced path reported `b` median **+12.42**,
  **4** sign flips and a residual sd of **4.537 bp** where the traded raw path
  gives **−5.45** (opposite sign), **1** and **2.766 bp** — and it produced a
  sentence, *"adding 2021 doubles the residual and doubles the flips"*, that is
  false on the fitted series (flips stay at one, residual ×1.24).

The other five were clock and specification errors (three Sharpe denominators in
one comparison; a β=0 control that compared two strategies; a convexity
signature missing the trade's own side; a count that read backwards on negative
P&L). **Six of the seven pushed the same way**, five of them flattering the
"dead" conclusion the author already held — the pattern this package recorded
once before and now has twice.

## Recorded, not promoted

One cell reads p = 0.024 one-sided on the GROSS sign-flip null: the *secondary*
`screen_best_all5 × citi_2017`. It is 16 of 22 WHITES episodes on marks whose
daily-change AC1 is −0.540 — at or past the pure-noise bound — its net
sign-flip p is 0.161, and on the engine it loses $190,110 against $3.55m of its
own declared fees.

## Standing caveat

This is the fifth pass over the same CA panel (block 1 `strat2`, block 3
`cavf`/#492, block 4 `gv`/#496, the reproduction/#499, now this). The 23-trial
bar is the honest one for the cells scored here, but the *structure* being
tested was chosen after four prior searches over the same data, and no
single-rule null bar undoes that. Block 4's verdict — CA-vs-fly is dead as a
systematic strategy — stands; this block adds the reason the published version
of it does not rescue the idea.

## Testing

```
pytest tests -m "not slow and not network and not db"        # 10,156 passed
pytest tests -k "convexity_rv or ccp_basis"                  # scoped
python notebooks/backtests/convexity_rv/_p4_mutate_citi.py   # 40 mutants
```

Note: run the gate **without** `ARBS_COMPUTED_TS_DIR` exported. That variable is
needed for a panel build and breaks two tests that assert the computed-TS
store's default location.
