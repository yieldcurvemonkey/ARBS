# Basis vs Swaption — adversarial review, implementation, and V2 backtest results

**Date:** 2026-08-13 · **Branch:** `feat/basis-vs-vol` (worktree `ARBS-bvv`)

Covers: adversarial review of the design doc and its implementation plan, the fixes that review
forced, the code that was built, and the backtest results.

---

## 1. What the adversarial review changed

Three independent adversarial passes were run against the design, the plan, and the backtest
*before* it was built. Fourteen findings were material. The ones that changed the work:

| # | finding | what it forced |
|---|---|---|
| **D1** | `ingest_ustf_vs_swaption_vol.py:419` divides by 10,000 against an `fv01` already in per-bp units, so every stored strike-offset bucket sits ~1/100 of the requested distance from the forward — a "100bp OTM" vol is 0.01bp from ATM | fixed the ingest; **rebuilt the futures smile from `smile_points`** for all historical work |
| **D2** | the swaption leg does *not* share that bug | differencing the two as-stored would have produced a large, stable, entirely artificial skew spread. Avoided. |
| **D3** | `atm_nvol_bps` is the SABR **model** value; `market_vol_bps` is stored separately, and the gap is +0.4 to +1.0bp, product-dependent, against a 4–13bp signal | measured and reported; a market-to-market comparison is impossible because the swaption leg stores no market vol |
| **D5** | `updated_at` on both tables spans only **2026-03-12 → 2026-03-17** for an `as_of_date` history running 2022-12 → 2026-03 | **the whole "history" is one retrospective vintage.** All results are labelled in-sample model output |
| **D8** | coverage gaps are non-random — they cluster at the quarterly roll | gap guard; missingness reported rather than dropped silently |
| **D11** | the futures leg is a constant-maturity splice across 14 underlying contracts | roll flags; a roll is never booked as a return |
| **D14/D12** | 1M/2M/3M are constant-maturity synthetics, not listed instruments | confirmed independently: `forward_price` and `fv01` are **identical across all three slots on all 665 days** |
| **D16** | snapshot-time alignment between legs is unverifiable from stored data | **tested and passed** — lead-lag cross-correlation peaks at lag 0 (0.70/0.84/0.75) with neighbours ~0 |
| **T1** | σ_basis is a 1:1 pass-through of term-repo error: NB moves 0.08/32 per bp of repo, so ZB Sep26's entire 4/32 option is 50bp of term repo | V1 is not attempted on ARBS's repo input (an overnight *unsecured* SOFR fixing) |
| **T3** | `V1 + V2` telescopes only if σ_exchange is the same object in both — it is a *price* vol on a futures price that already embeds the delivery option | see §5, limitation 3 |
| **T11/C5** | one TY tick ≈ **1.05bp of nvol**; a realistic round trip is **3–5bp** | the assumed 2.5bp round trip is the optimistic end; results are read off the **break-even multiple** |
| **C1** | execution lag is decisive: same-day fills give Sharpe 2.80, t+1 gives 1.28, t+2 gives 0.86 | `exec_lag_days=1` is the default and the harness is mutation-tested for lookahead sensitivity |

Two further defects were found by me, not the reviewers, and two by the engines checking each other
(§4).

---

## 2. Design changes made

1. **Split the signal and run the cheap leg first.** `V_spread = V1 + V2` with
   `V1 = σ_basis − σ_exchange` (needs a basket model, a term repo, WI handling) and
   `V2 = σ_swaption − σ_exchange` (needs none of it). V2 was built and tested; V1's *core* was built
   and validated against a vendor sheet but not backtested, because ARBS has no term repo.
2. **A hard support gate.** Positions may not be priced below the shortest quoted expiry node. This
   is the single most consequential change — see §6.
3. **G7, the map-validity gate.** A single-swaption, parallel-shift map is only defensible when the
   live deliverable set is tight. Implemented in `switch.map_is_valid`.
4. **Controls fixed.** ZF and TN are the `p_CTD > 0.99` twins; ZT is a *live-switch, zero-value*
   control (three deliverables all maturing the same month at 56.8/34.4/8.8%).
5. **UL excluded as corrupt**, not for performance.

---

## 3. What was built

```
RVUtils/BasisVsVol/
  bachelier.py   normal-option primitives; the inverter returns nan -- not 0.0 -- wherever the
                 time value cannot identify a vol
  voldata.py     parquet loader, sanitizer, roll + liveness flags, smile expansion,
                 variance-linear term-structure interpolation, data-quality report
  surfaces.py    per-day surface queryable at arbitrary (remaining tte, strike offset)
  switch.py      crossover solver, CF-adjusted DV01 gap, two-bond Bachelier delivery option,
                 implied switch vol, G7 map-validity gate
  strategy.py    vega-matched, delta-hedged pair; support / gap / roll guards
  analytics.py   Newey-West t, PSR, deflated Sharpe, block bootstrap, concentration
  grid.py        pooled grid search + shuffled-signal and mismatched-pair placebos + cost ladder
  run_grid_search.py

Query/BasisVsVol/     BASISVSVOL product: query, inert adapter, position handler
MDP/BasisVsVol/       offline snapshot MDP (returns absence, never the nearest neighbour)
BT/signals/basis_vs_vol.py   QueryDrivenBacktest runner
notebooks/backtests/basis_vs_vol/   generated configurable notebook + builder + README
tests/test_bvv_{bachelier,switch,backtest}.py   67 tests (incl. the ingest regression)
```

---

## 4. Validation

**The delivery-option core reproduces a vendor model it does not share.** Against the J.P. Morgan
*U.S. Futures and Options Package* of 2026-08-12:

| contract | two-bond DOV | JPM printed | crossover | JPM `Baseline Yld Shft` |
|---|---|---|---|---|
| Ultra Bond Sep26 | **1.05/32** | 0-01 | 24.6bp | 28.3bp |
| Bond Sep26 | **1.39/32** | 0-04 | 14.6bp | 10.9bp |

UB ties out to within a tick. ZB captures **35%** — as it must, because ZB has seven deliverables
above 1% delivery probability spanning 33 months and a two-bond model can see only one switch. That
is the diffuse-basket conclusion of the earlier design review, reached by a completely independent
route.

**Two independent engines agree exactly.** The QueryDrivenBacktest path (framework MDP, query,
adapter, handler, triggers) and the standalone vectorised engine produce identical P&L —
`0.0000` difference across US/3M, TY/2M, FV/3M, TN/3M, TU/2M. They share only the Bachelier
primitives and the surfaces.

That cross-check paid for itself immediately: it found that **the reference engine was booking the
contract-roll forward gap as P&L**, and an unbounded index in the entry path. Neither would have
been visible from a single implementation.

### Test status

The repo's own `audit_test_results.txt` records **222 pre-existing failures**, so the CLAUDE.md fast
gate (`pytest tests -m "not slow and not network and not db"`) does not pass on this checkout and
was never going to. It also cannot complete here: it **hangs at ~10%** in the Citi Velocity Excel
tests, having burned 379s of CPU across 71 minutes of wall clock — a pre-existing COM/environment
issue, not a slow test.

The meaningful bar is therefore *adds no failure*, and that is established directly:

| suite | result |
|---|---|
| `test_bvv_{bachelier,switch,backtest}.py` | 67 passed |
| `test_ingest_ustf_vs_swaption_vol.py` (the file I modified) | 9 passed |
| `tests/test_[a-b]*.py` (in order) | 150 passed |
| `test_citivelo_excel_{integration,source,client}.py` | 81 passed, 9 skipped |
| `test_backtest_simple.py`, `test_portfolio.py` | included in 77 passed |

The only global side effect of this work is `register_product("BASISVSVOL")` /
`register_handler(...)`, which fires solely when `Query.BasisVsVol` is imported. No test anywhere
depends on the registry's contents or size — every use in `tests/` is `get_adapter("<name>")` for a
specific name — so the registration cannot affect another test. Everything else added is new files.

**The harness is mutation-tested for lookahead.** Feeding the signal one day of future knowledge
must change results; a test asserts it does. A backtest that cannot detect lookahead cannot be
trusted when it reports none.

---

## 5. Data defects found

| defect | evidence | handling |
|---|---|---|
| strike-offset buckets corrupt on the futures leg | a "25bp" strike sits 0.25bp from the forward; vol 114.72970 vs ATM 114.72966 | ingest fixed; history rebuilt from `smile_points` |
| `UL` forward yield corrupt | forward price stored as `11.28` for `111.28`; forward yield spans **20bp in 3.3 years** against 163bp for US; implied/realized 3.5 vs 0.97–1.13 | product excluded; 642 rows dropped by the sanitizer |
| 13 gaps > 1 week, one of **80 days** | clustered at the quarterly roll | positions liquidated at the last observed mark; **no return claimed for the gap** |
| single retrospective vintage | `updated_at` 2026-03-12 → 2026-03-17 | all results labelled in-sample |
| CM slots share one forward | `forward_price`/`fv01` identical across 1M/2M/3M on every day of the full sample (665/665) | the series are synthetic, not instruments |
| model-not-market ATM | `market_vol_bps` exceeds the SABR value by +0.4 to +1.0bp, product-dependent | measured and reported |

**Limitation 3 (from the theory review), stated precisely.** The futures leg's bp vol is
`price_vol / fv01`. If `fv01` is the naive `DV01_CTD/CF` rather than the option-adjusted futures
DV01, it is wrong by 5–14% (measured on the JPM sheet: ZB +13.6%, UB +5.2%). A *constant*
multiplicative error is absorbed by the z-score; only its *time variation* matters, and that
variation is driven by how live the CTD switch is. This is second-order for the signal but it is
not zero, and it cannot be checked from this vintage.

---

## 6. The result that decides the V2 leg

*(Measured on the full sample, before the flat-smile seam exclusion of §5 — this is when and how
the problem was found. The clean-sample equivalents are given below the table.)*

The first grid put the strongest cell at the **1M** expiry: pooled Sharpe **1.94**, t(NW) 3.43, hit
rate 76%, top-3 concentration 0.26, costs 26% of gross. 2M and 3M showed nothing.

An edge that lives in one cell and nowhere near it is a warning, not a discovery. The vol term
structure is quoted at three nodes — 30, 60 and 90 days. Below the shortest node the surface holds
vol flat, because there is nothing to interpolate. **A 1M position spends its entire life there.**

Confining positions to the quoted range:

| expiry | on support | n trades | mean vol bp | hit | Sharpe | t(NW) |
|---|---|---|---|---|---|---|
| 1M | no | 45 | +6.24 | 0.76 | **+1.94** | 3.43 |
| 1M | **yes** | 24 | −0.59 | 0.33 | **−0.19** | −0.33 |
| 2M | either | 45 | +1.07 | 0.64 | +0.30 | 0.85 |
| 3M | either | 38 | +1.06 | 0.55 | +0.44 | 0.83 |

The entire result was produced outside the data's support and inverts on contact with it. This is
now a hard gate (`require_on_support=True`) and the 1M slot is inadmissible.

**On the clean post-seam sample the same test is starker.** A 1M position opens at the shortest
quoted node, so it is extrapolated from day one: allowed to run it earns **+5.63 vol bp per trade**
over a 7-day hold; gated, **all 11 trades exit after exactly one day** with reason `off_support`, at
**−0.12 vol bp** each. The 1M slot is not a losing configuration — it is an unmeasurable one.

---

## 7. Grid search results

**1,296 pre-registered configurations**, each pooled across TU/FV/TY/TN/US at equal vega, on the
clean sample (2023-12-12 to 2026-03-13; per product TY 508, US 497, FV 483, TU 460, TN 457 days).

Axes: `expiry_label` {2M, 3M} x `offset_bps` {-25, 0, +25} x `z_window` {63, 126, 252} x `entry_z`
{1.0, 1.5, 2.0, 2.5} x `exit_z` {0.0, 0.5, 1.0} x `max_hold_days` {10, 21, 42} x `rehedge_days`
{1, 5}.

### The grid as a whole

| statistic | value |
|---|---|
| cells | 1,296 |
| median Sharpe | **-0.19** |
| mean Sharpe | -0.44 |
| cells with positive Sharpe | 444 / 1,296 (**34%**) |
| best Sharpe | **0.970** |
| **E[max Sharpe \| null]** at 1,296 trials | **2.73** |

The best cell in the entire search scores **0.97 against the 2.73 that a null grid of this size
produces by chance**. Deflated Sharpe = **6.6e-06**.

### The winning cell

`US/3M/20Y/off-25/w63/e2/x0/h42/rh5` — 3M expiry, -25bp strike offset, 63-day z-window, entry
|z| >= 2.0, exit_z 0.0, 42-day max hold, 5-day rehedge.

| | |
|---|---|
| Sharpe | 0.970 |
| t(Newey-West) | **1.085** |
| bootstrap 95% CI on Sharpe | **[-0.54, 1.76]** |
| trades | 42 |
| mean per trade | +9.87 vol bp |
| **hit rate** | **40.5%** |
| **top-3 trade share** | **111%** |
| deflated Sharpe | **0.0000066** |
| shuffled-signal placebo percentile | **0.678** (needs > 0.95) |
| break-even cost multiple | 3.0x |
| lagged-exit sensitivity | identical (0.970) |

### Why it is noise, in four independent ways

1. **It is one product.** TY contributes **+434.6** vol bp of a **+414.5** total; the other four
   products sum to **-20.1**. Pooling across five products was supposed to buy breadth and instead
   the "portfolio" is a single duration bucket.
2. **It is five trades.** The top five trades make **+477.5**; the remaining thirty-seven make
   **-63.0**.
3. **It never uses its own signal to exit.** `exit_z = 0.0` means the reversion test
   `|z| <= exit_z` essentially never fires. Of 42 trades, **zero** exit on the signal: 22 are closed
   by data gaps, 12 by contract rolls, 8 by the 42-day cap — and **all the profit is in those 8**
   (+449.9, against -20.3 for gaps and -15.1 for rolls). The winner of a mean-reversion grid search
   is not a mean-reversion strategy; it is "enter when |z| > 2 and hold for six weeks".
4. **It is one year.** 2024 loses (-17.5, Sharpe -0.375); 2025 makes all of it (+444.3); 2026 is 48
   days.

**Costs are not what kills it.** At `cost_mult = 0` the cell still only reaches Sharpe 1.19 with
t = 1.34, and the break-even multiple is 3.0x. For once in this programme the edge is not lost to
the bid/offer — there is no edge to lose.

---

## 8. Verdict

**V2 is dead. `alive = false` on every pre-registered criterion except the cost gate.**

| kill condition | required | actual | pass |
|---|---|---|---|
| deflated Sharpe | > 0.95 | 6.6e-06 | **no** |
| top-3 trade share | < 0.60 | 1.114 | **no** |
| shuffled-signal placebo | > 0.95 pct | 0.678 | **no** |
| survives 2x costs | yes | yes (break-even 3.0x) | yes |

The one positive is that the **matched pairing beats the mismatched one** — US against its 20Y tail
scores 0.227 versus -0.516 against a deliberately wrong 2Y tail, and TY against 7Y scores 0.989
versus -0.143 against 2Y. So the tail map is not arbitrary. But the matched numbers are themselves
insignificant, so this says the construction is sane, not that the trade is there.

**Every bias left open in the harness points in the strategy's favour** — same-day signal-driven
exits (measured: no effect on this cell, because it has none), a cost model with no market impact,
and an in-sample vintage. A dead verdict from this harness is therefore conservative.

### What was deliberately not done, and why

* **V1 (`sigma_basis - sigma_exchange`) was not backtested.** ARBS has no term repo: the basis path
  applies the last *overnight unsecured* SOFR fixing as the term repo to delivery for every bond in
  the basket, with specialness a hand-typed per-root constant defaulting to zero. Net basis moves
  0.08/32 per bp of term repo, so ZB Sep26's entire 4/32 delivery option is 50bp of repo. Inverting
  that to a vol and comparing it to a 4-13bp signal is not a measurement. The *core* was built and
  validated (§4); the backtest waits on a repo curve.
* **The stale ingest was not restarted.** Both upstream producers are dead (the MONKEYCUBE cube
  files stop in 2026-04), and the tables' primary key means a restart UPSERTs over the only copy of
  the vintage. The parquet mirror in `_data/` is that snapshot.
* **The full-basket two-factor Monte Carlo (M3) was not built.** It needs a term repo,
  per-CUSIP specialness, when-issued handling and an end-of-month option, none of which exist, and
  its output is a 4/32 number against a 1/32 tick. The two-bond reduction answers the question the
  Monte Carlo would have answered first: is sigma_basis in the right ballpark? It is, for UB.

### What would change the verdict

A genuine out-of-sample window. Everything here is one retrospective vintage, so the honest next
step is not a better model but a **point-in-time recorder**: run the vendor-package parser and the
vol ingest forward from today, and re-test on data that was not manufactured with hindsight. Until
then no configuration of this signal should be traded, and the framework's value is as a valuation
lens and a set of gates, not as a strategy.
