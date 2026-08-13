# Treasury futures basis vs swaption — V2 backtest

Tests the **exchange-vs-OTC** leg of the design's decomposition:

```
V_spread = V1 + V2
V1 = sigma_basis    - sigma_ustf_option    delivery option vs listed option   (needs a basket model)
V2 = sigma_swaption - sigma_ustf_option    OTC vs exchange                    (needs NO basis model)
```

V2 runs first because it needs no deliverable basket, no term repo and no Monte Carlo, so it can
falsify the cross-product thesis before any of that exists.

## Notebook

| file | what it is |
|---|---|
| `basis_vs_vol_configurable_backtest.ipynb` | **generated — do not edit** |
| `_make_bvv_notebook.py` | the builder. Edit this, then re-run it. |

```
<env>/python.exe notebooks/backtests/basis_vs_vol/_make_bvv_notebook.py
```

## Architecture

```
  parquet mirror (_data/)                    _pull_vol_snapshots.py
        |
        v
  voldata.load()          sanitize -> roll flags -> liveness flags -> smile expansion
        |
        v
  surfaces.SurfaceBook    per date: term structure (linear in total variance)
        |                           + skew as a spread to ATM in bp-offset space
        v
  strategy.run_strategy() signal on the CM slot -> position priced at its OWN remaining maturity
        |                 support gate | gap guard | roll guard | delta hedge | costs
        +---------------------------------------------+
        |                                             |
        v                                             v
  grid.run_pooled_grid()                    BT/signals/basis_vs_vol.py
  analytics (DSR, NW t, bootstrap)          QueryDrivenBacktest + handler + snapshot MDP
        |                                             |
        +----------------- must agree ----------------+
```

## P&L

Both legs are Bachelier options on a rate; everything is in bp and money = bp x DV01.

```
daily leg P&L (bp) = [V(F_t, K, sigma_t, tau_t) - V(F_{t-1}, K, sigma_{t-1}, tau_{t-1})]
                     - delta_{t-1} * (F_t - F_{t-1})
net (USD)          = side * [DV01_s * dps - DV01_u * dpu] - costs
DV01_leg           = target_vega_usd / vega_bp(leg at inception)      (vega-matched)
```

P&L is reported in **vol bp** = USD / `target_vega_usd`, so it is scale-free.

Delta-hedged P&L is right-invariant (put-call parity gives `C-P = F-K` and `d_C - d_P = 1`), so
every position is priced as a call on the rate.

## Validation

| check | test |
|---|---|
| Bachelier primitives vs closed forms + finite differences | `tests/test_bvv_bachelier.py` (32) |
| delivery option vs the JPM package of 2026-08-12 | `tests/test_bvv_switch.py` (12) |
| two engines produce identical P&L | `tests/test_bvv_backtest.py::test_query_driven_backtest_matches_the_reference_engine` |
| harness can detect deliberate lookahead | `test_harness_detects_deliberate_lookahead` |
| gap guard, roll guard, support gate | `test_gap_guard_*`, `test_a_contract_roll_is_never_booked_as_pnl`, `test_support_gate_*` |

```
conda activate stir && python -m pytest tests/test_bvv_*.py tests/test_ingest_ustf_vs_swaption_vol.py -q   # 67 tests
```

## Notes / caveats — read before quoting any P&L

0. **The sample starts 2023-12-12.** Before that the swaption smile is a flat fallback: 248
   contiguous days with a NULL SABR alpha and a 25bp payer-minus-receiver skew whose standard
   deviation is *exactly* 0.0000, plus a 15.3bp step in the ATM level at the seam. Enforced in
   `voldata.load()`, which raises if any NULL-alpha row survives the cut. Usable sample: 545 days
   across the universe (per product: TY 508, US 497, FV 483, TU 460, TN 457 -- see
   `_results/data_quality.csv`).
1. **The source history is a single retrospective vintage.** `updated_at` spans 2026-03-12 to
   2026-03-17 for `as_of_date` 2022-12-09 to 2026-03-13. Results are in-sample model output.
2. **1M/2M/3M are synthetic constant-maturity vols, not instruments.** `forward_price` and `fv01`
   are identical across all three slots on every day — one front-contract forward serves every
   tenor.
3. **`strike_offset_otm_vols` is corrupt on the futures leg** (`/10_000` against an `fv01` already
   in per-bp units): every stored "OTM" bucket sits ~1/100 of the requested distance from the
   forward. Fixed at `SDRUtils/_swappulse_scripts/ingest_ustf_vs_swaption_vol.py:419` for future
   ingests; the stored history is **not** repaired. This code rebuilds the futures smile from
   `smile_points` instead. The swaption leg's offsets are correct — differencing the two as-stored
   yields a large, stable, entirely artificial skew spread.
4. **`atm_nvol_bps` is the SABR model value, not the market quote.** The futures leg's delta
   buckets also carry `market_vol_bps`; the gap is +0.4 to +1.0bp and product-dependent, against a
   signal of 4–13bp. The swaption leg stores no market vol, so a market-to-market comparison is not
   available from this vintage.
5. **`UL` is excluded as corrupt**, not for performance: its forward yield moves 20bp across 3.3
   years (US moves 163bp) and a block of rows has a dropped leading digit in the price.
6. **No liquidity data exists in the source** — no OI, no bid/ask, no volume. Costs are assumed.
   `cost_mult = 1.0` here is a 2.5bp round trip; the defensible band derived from tick sizes
   (one TY tick ~ 1.05bp of nvol; swaption bid/ask 0.5–1.5bp a side) is **3–5bp = cost_mult
   1.2–2.0**. Read the break-even multiple, not the net P&L.
7. **The futures leg has 13 holes longer than a week, one of them 80 days**, clustered at the
   quarterly roll. Positions are liquidated at the last observed mark and no return is claimed for
   the gap. The missingness is not random — it coincides with the roll.

## Known asymmetries, disclosed rather than fixed

* **The two engines are proven identical at zero costs only.** The framework has no entry-side fee
  hook, so QueryDrivenBacktest charges the whole round trip at unwind while the reference charges
  entry and a vega-decayed exit separately. Pricing agrees exactly; cost conventions differ by
  construction.
* **Hedge-cost cadence differs at `rehedge_days > 1`** — the reference counts panel index steps,
  the handler counts calendar days. Identical at the default of 1.
* **Entries are lagged one day; the signal-driven exit fires on the same close.** `lag_exits=True`
  closes it, and is run as a sensitivity rather than as the default so the pre-registered grid is
  not silently re-specified.

**Every bias left open points in the strategy's favour**, so a dead verdict from this harness is
conservative.

## Results

`_results/` — `grid_pooled.csv`, `best_daily.csv`, `best_trades.csv`, `best_cost_ladder.csv`,
`best_placebo.csv`, `best_mismatched_pair.csv`, `best_regime.csv`, `verdict.json`,
`data_quality.csv`.
