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

## V1 — option-adjusted basis · COMPLETE · **DEAD**

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

### Result

Panels built 2018-06 → 2026-08. **216 pre-registered configurations** (the grid was fixed before
the first run and not touched after seeing results), 2 roots × 4 entry_z × 3 max_hold × 3 z_window
× 3 switch_vol.

| | |
|---|---|
| best cell | `ZN/w252/e1.5/x0.5/h10/sv90` |
| Sharpe | 0.381 |
| **E[max Sharpe \| null] at 216 trials** | **0.478** |
| **deflated Sharpe** | **0.435** (needs > 0.95) |
| t(Newey–West) | 0.981 |
| bootstrap 95% CI | [−0.24, 0.84] |
| hit rate | 42.9% (21 trades) |
| top-3 trade share | 1.27 (needs < 0.60) |
| sign-flip permutation | 0.811 (needs > 0.95) |
| grid median Sharpe | −0.144 (25% of cells positive) |
| **alive** | **false** |

As with V2, the winner of the whole search scores **below what chance produces at that trial
count**, and it fails every other kill condition independently.

**The decisive number is not in that table.** Split the grid by root:

| root | usable days | cells | median Sharpe | % positive | best |
|---|---|---|---|---|---|
| **ZB** — the only root whose data is coherent | 1,627 | 108 | **−0.217** | **0%** | **−0.000** |
| ZN — 35% intact, effectively 2024→ | 662 | 108 | −0.002 | 49% | +0.381 |

**On ZB, not one configuration of 108 made money.** Every positive cell in the pooled grid comes
from ZN, the root whose panel is two-thirds rejected and whose futures-vs-basket relationship is
systematically biased (below). The strategy is dead, and on the clean root it is dead without
ambiguity.

The ablation is moot at these levels but points the same way: switch-only (0.469) beats
switch+wildcard (0.381), so the **wildcard subtracts**; no-model raw BNOC is 0.094. Every arm is
below E[max|null].

### The gate was written and never read

`build_basis_panel` computed `data_ok` per row — the internal-consistency check that the cheapest
CF-adjusted forward in the basket must sit at the futures price — and **nothing ever read it**. The
first V1 grid therefore ran over rows where the cash and futures feeds disagree about the same day,
including a UB panel that is 98% rejected. It reported "dead" too, but that was not a measurement.

Fixed by `filter_data_ok()`, applied at the **load boundary** (runner, notebook, QDB path) rather
than inside `run_v1`: the engine also runs on synthetic test panels that carry no `data_ok` column,
so an engine-internal `if "data_ok" in p` would silently no-op on exactly the inputs the tests use.
The helper also **re-derives `is_roll`**, which the builder computed before any filtering — drop
rows and a contract change can land on a row flagged `False`, and the entry gate tests `not roll[i]`
directly. Both failure modes are pinned by tests, each confirmed to fail under mutation.

### What the gate found: two roots are not usable

| root | gate passes | verdict |
|---|---|---|
| ZB | 85% | usable, 1,627 days |
| ZN | 35% | usable ~2024 → only |
| UB | 2% | **unmeasurable, dropped below the 200-row floor** |

**UB's price series is not the Ultra Bond's price.** It sits in 110.0–114.1 for all nine years while
ZB ranges 107.9–185.6; a 25y+ future with ~19y duration cannot move 4 points through a cycle that
moved the classic bond 78. It also lands on no tick grid (25.7% on 1/64, vs ZB 88% on 1/32 and ZN
100% on 1/64 — both correct for their contracts), and its basket is frozen at exactly 19
deliverables every year from 2018 to 2026. On 2024-04-15 the served price is 112.86 while every
CF-adjusted forward in its own basket sits at 120.7–124.6; the cash leg is verifiably right
(T 2¼ Aug '49 at 62.47 is what that bond prices to at those yields), so the futures leg is broken.

**ZN's price series is fine** — correct range, perfect 1/64 conformity — but `min(gross basis)`
across its basket is systematically negative and decays monotonically, −149/32 (2020) → −16/32
(2026). That is a bias on the cash/basket side, not the price.

Both are defects in the shared `USTFuturesMDP` basis-report path, not in this branch. They are
recorded here rather than fixed: the fix is a basket/symbol-map change in shared infrastructure plus
a multi-hour rebuild, and it cannot rescue V1 — ZB is already clean, already eight years long, and
already 0-for-108.

### The regime the gate cannot vouch for

ZB's rejected rows are not the same animal as ZN's and UB's. They cluster in 2020 (62% pass) and
2021 (42%) at a median 8/32 — plausibly the **real** COVID basis dislocation rather than a feed
break, and the gate cannot tell the two apart. So V1 is untested in precisely the regime where
basis risk is largest, and the ZB result above should be read as "dead in normal markets", with
the 2020–21 stress period excluded rather than survived.

---

## Bugs fixed to make any of this run

| | |
|---|---|
| `RLUSTFuturePricer.net_basis/bnoc/implied_repo` | defaulted the repo leg to `ActAct`. rateslib 2.7 refuses the bare form so **the entire RL basis path raised on every call**; it is also financially wrong, USD repo accrues **Act/360**. Fixed. |
| `RLFixedRateBondPricer.time_to_maturity` | fed rateslib's own spec convention back into `rl.dcf`, rejected for the same reason. Disambiguated to `ActActISDA` (schedule-free). |
| `build_basis_panel.front_symbol` | iterated months-outer/years-inner, so it returned next March before this June and silently picked a contract a year away. |
| `v1.add_model_option` | with both option components disabled, `dov32` was NaN not 0, so the **no-model ablation arm** — the one that asks whether the delivery-option machinery earns its place — silently produced nothing. |
| CTD selection | was max implied repo; now min net basis, which is the standard definition and the more robust of the two on imperfect data. |
| `data_ok` | the build-time consistency gate was **written by the builder and read by nothing**, so the first V1 grid ran over feed-break rows including a 98%-rejected UB panel. Now applied at the load boundary by `filter_data_ok()`, which also re-derives `is_roll` (stale after any row drop). |

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
