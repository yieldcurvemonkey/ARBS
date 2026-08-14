# V1 and V2 backtests — results

**Date:** 2026-08-14 · **Branch:** `feat/basis-vs-vol` · 96 tests

Both legs are built on the QueryDrivenBacktest framework with daily mark-to-market, each with a
configurable notebook and each cross-checked against an independent standalone engine.

---

## V2 — exchange vol vs OTC vol · COMPLETE · **DEAD**

`V2 = σ_swaption − σ_ustf_option`, vega-matched, delta-hedged, both legs Bachelier on a rate.

**1,296 pre-registered configurations**, pooled across TU/FV/TY/TN/US, sample 2023-12-12 → 2026-03-13
(545 days after the flat-smile seam exclusion).

| | |
|---|---|
| best cell | `US/3M/20Y/off-25/w63/e2/x0/h42/rh5` |
| Sharpe | 0.970 |
| **E[max Sharpe \| null] at 1,296 trials** | **2.73** |
| **deflated Sharpe** | **6.6e-06** |
| t(Newey–West) | 1.085 |
| bootstrap 95% CI | [−0.54, 1.76] |
| hit rate | 40.5% |
| shuffled-signal placebo | 0.678 pct (needs > 0.95) |
| grid median Sharpe | −0.19 (34% of cells positive) |
| **alive** | **false** |

The winner of the entire search scores **below what chance produces at that trial count**. It is
noise four independent ways: one product carries it (TY +434.6 of a +414.5 total; the other four sum
to −20.1), five trades carry it (top 5 +477.5, the other 37 −63.0), one year carries it (2024
negative, 2025 all of it), and **it never uses its own signal to exit** — `exit_z = 0.0` never fires,
so 22 of 42 trades close on data gaps, 12 on rolls, 8 on the hold cap, and every dollar of profit is
in those 8. Costs are not the binding constraint: break-even is 3.0× and at zero cost t is still 1.34.

The sample cannot be extended. The vol-snapshot vintage does not exist before 2022-12.

---

## V1 — option-adjusted basis · BUILT AND VALIDATED · results pending the data build

`OABNOC = BNOC_market − (switch + wildcard)`. Long basis when the market pays less than the delivery
option is worth. **P&L is exactly the change in net basis** — `d(P_cash) − CF·d(F) + coupon − repo`
= `d(gross) + a day's carry` = `d(net basis)` — so a daily mark needs only that series and carry is
already inside it.

Stack: `build_basis_panel.py` (daily CTD + challenger panel from the repo's own basket machinery,
financed off the swaps-curve term rate to each contract's delivery date, front contract rolled 7 days
before first notice, checkpointed and resumable) → `v1.py` (delivery-option model, signal, engine) →
`Query/BasisPair/` (BASISPAIR product: query, adapter, handler, panel MDP) → `BT/signals/basis_pair.py`
(QDB runner) → `run_v1_results.py` (grid, ablation, cost ladder, permutation, DSR, verdict).

**Validated**: 11 tests on a synthetic panel pin the P&L identity, the roll guard, the roll
chronology, lookahead sensitivity, and **exact agreement between QueryDrivenBacktest and the
reference engine**.

**Status**: three panels (ZB, ZN, UB) building 2018-06 → 2026-08 at ~12s/day; `run_v1_results.py`
is armed and fires automatically when they settle, writing `_results/v1_verdict.json`,
`v1_grid.csv`, `v1_ablation.csv`, `v1_cost_ladder.csv`, `v1_best_{daily,trades}.csv`.

### The 10-year target is not available, and here is the measurement

The design asked for 10+ years. The feeds do not support it. The futures price is pinned to the
cheapest CF-adjusted forward, so `min(gross basis)` across the basket must be small. Measured:

| era | min gross basis across the basket | gate passes | CTD net basis |
|---|---|---|---|
| 2015 | **+135.9/32** (max +509) | **0%** | −278/32 |
| 2019 | +13.6/32 | 100% | −0.14/32 |
| 2024 | −3.8/32 | 100% | +0.38/32 |

A net basis of −278/32 is not a market; on 2015-01-02 the *smallest* gross basis over every
deliverable was +135/32. The cash and futures feeds disagree about the same day. This is now an
executable gate (`data_ok`), the builds run from 2018-06 so the funnel brackets the transition, and
the usable V1 sample is **roughly 2019 → 2026, about 7 years of daily marks**.

---

## Bugs fixed to make any of this run

| | |
|---|---|
| `RLUSTFuturePricer.net_basis/bnoc/implied_repo` | defaulted the repo leg to `ActAct`. rateslib 2.7 refuses the bare form so **the entire RL basis path raised on every call**; it is also financially wrong, USD repo accrues **Act/360**. Fixed. |
| `RLFixedRateBondPricer.time_to_maturity` | fed rateslib's own spec convention back into `rl.dcf`, rejected for the same reason. Disambiguated to `ActActISDA` (schedule-free). |
| `build_basis_panel.front_symbol` | iterated months-outer/years-inner, so it returned next March before this June and silently picked a contract a year away. |
| `v1.add_model_option` | with both option components disabled, `dov32` was NaN not 0, so the **no-model ablation arm** — the one that asks whether the delivery-option machinery earns its place — silently produced nothing. |
| CTD selection | was max implied repo; now min net basis, which is the standard definition and the more robust of the two on imperfect data. |

---

## Notebooks

| notebook | builder |
|---|---|
| `basis_vs_vol_configurable_backtest.ipynb` (V2) | `_make_bvv_notebook.py` |
| `basis_v1_configurable_backtest.ipynb` (V1) | `_make_v1_notebook.py` |

Both follow the `usd_fomc_nonvoter_fade` pattern: a single CONFIG dict, a known-answer gate, a
data-quality funnel, performance, knob-sweep heatmaps, a cost curve with break-even, permutation and
DSR against the honest trial count, a regime split, and a QDB-vs-reference cross-check.

The V1 notebook adds **§7, a model ablation** — switch+wildcard vs switch only vs wildcard only vs
no model at all. It is a pre-registered kill condition: if the no-model arm matches the full model,
the delivery-option machinery is decoration and the honest name for the strategy is "fade the net
basis".
