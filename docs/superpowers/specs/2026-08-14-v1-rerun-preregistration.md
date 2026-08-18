# V1 re-run on the repaired data layer — pre-registration

**Written and committed before any result of this run was read.** Branch
`feat/basis-vs-vol-v1-qdb` = `fix/ustf-data-layer` (PR #455) + `feat/basis-vs-vol` (PR #454).

---

## Why re-run something already concluded dead

V1 was concluded **dead** on 2026-08-14 (`2026-08-14-v1-v2-backtest-results.md`): 216
configurations, best cell `ZN/w252/e1.5/x0.5/h10/sv90` at Sharpe 0.381 against an E[max | null] of
0.478, deflated Sharpe 0.435. That verdict was rendered on data that has since been **proved
corrupt** (PR #455):

| root | what the old panel contained |
|---|---|
| **ZN** | the deliverable basket admitted old 30-year bonds; on a 2020-10 sample the CTD is a different bond on **9 of 9 days**, `ctd_bnoc32` is **−190.5/32** where the repaired data says **+0.48/32**, and implied repo is **+24.02%** against 0.08% funding |
| **UB** | the futures price was the **EUR/NOK exchange rate**; `ctd_bnoc32` **1724.7/32** vs a repaired **4.17/32** |
| **ZB** | **unaffected** — numerically identical on all ten panel columns, max abs diff 0.000000 |

V1's P&L is exactly `d(net basis)`. Its entire input is that column. **The winning cell of the
prior search was a ZN cell**, so the prior verdict was rendered on a series that was not a net
basis. This is a different experiment on different inputs, not a second look at the same numbers.

This is also the point on which the handover said "do not re-run its grids looking for a surviving
configuration". That instruction was written before the data defects were known and is superseded
by the user's explicit instruction to run it. It is recorded here rather than argued.

## What is NOT changing

The grid is **exactly** what `run_v1_results.py` already contains, unedited:

```python
ROOTS = ("ZB", "ZN", "UB")
AXES  = dict(entry_z=[1.0, 1.5, 2.0, 2.5], max_hold_days=[10, 21, 42],
             z_window=[63, 126, 252], switch_vol_bp=[50.0, 70.0, 90.0])
ALIVE = dict(min_dsr=0.95, max_top3=0.60, cost_mult=2.0, perm_pct=0.95)
```

108 cells per root. **`UB` was already in `ROOTS`**; it never entered the prior grid because the
loader's `min_rows = 200` floor dropped it — its gate pass rate was 1.9%. It now passes 99.7%, so
it enters on the *same pre-registered rule*. **The trial count therefore moves 216 → 324 with no
post-hoc grid expansion**, which is the only reason that change is legitimate.

Direction remains fixed in code: `z < 0` means the market pays less than the delivery option is
worth, so the position is long basis. Not chosen after the fact.

## Kill conditions — carried over verbatim

"Alive" requires **all** of:

1. deflated Sharpe > **0.95** against the full trial count;
2. survives **2×** costs;
3. sign-flip permutation percentile > **0.95**;
4. top-3 trade share < **0.60**;
5. the **ablation**: if the no-model arm (raw net-basis z-score) matches the full model, the
   delivery-option machinery is decoration and the honest name for the strategy is "fade the net
   basis".

## What will be reported, decided now

1. **The best-Sharpe cell and its parameters** — the literal ask.
2. Immediately beside it: **E[max Sharpe | null] at the realised trial count**, the **deflated
   Sharpe**, and the full kill battery. A maximum drawn from a grid without its null is not a
   result, and every prior lab in this repo reports it this way.
3. The **216-cell ZB+ZN subset**, for a like-for-like comparison with the prior verdict.
4. **The prior winning cell `ZN/w252/e1.5/x0.5/h10/sv90` re-evaluated on repaired data.** This is
   the single most informative number in the run: same cell, before and after, immune to selection
   effects.
5. Grid median Sharpe and the fraction of positive cells — a real edge lifts the whole grid, a
   fluke lifts one cell.
6. Per-root results, since ZB is a control that should barely move.

## Predictions, so the result can embarrass me

Recorded before seeing any output:

- **ZB will barely move.** Its panel is numerically identical; only `data_ok` changes, which admits
  the 2020–21 rows the old gross-basis gate wrongly rejected. Its cells should shift slightly, not
  transform.
- **ZN will change a lot but I do not expect it to become alive.** The old ZN signal was noise from
  a broken basket; replacing noise with signal does not by itself create an edge.
- **UB is the genuine unknown.** It has never been tested on real data.
- **Most likely overall outcome: still dead, for real reasons rather than data reasons.** That is a
  worthwhile finding and will be reported as plainly as the alternative.
