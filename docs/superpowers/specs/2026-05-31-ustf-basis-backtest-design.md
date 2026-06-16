# UST Futures Basis Backtest Suite — Design Spec

**Date:** 2026-05-31
**Status:** Approved (design), implementation pending
**Owner:** chris

## Goal

Query-driven backtest of common US Treasury futures **basis** trade strategies over the
past 2 years, producing **daily mark-to-market PnL** graphs with correct PnL and
repo/UST financing. Build a new reusable `USTFutureBasis` Query object following the
existing Query/MDP pattern, plus one config-driven notebook per strategy.

Data sources (fixed):
- Cash leg: `FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")` — QuantLib pricers
  (working `npv()` + `cashflows_between()` for coupons/redemption).
- Futures + deliverable basket / CTD / CF / gross+net basis / IRR:
  `USTFuturesMDP(source="BARCHART_USTF-RL")` — RL basket internally.

Clean separation: the RL basket only identifies CTD / conversion factor / gross-net
basis / implied repo; the QL bond pricer prices the cash leg for MTM, financing and
coupon realization.

## Decisions (from brainstorming)

- **Strategies:** all four, one notebook each — (1) systematic long+short CTD basis,
  (2) net-basis / BNOC RV signal, (3) calendar/roll spread, (4) CTD-switch / optionality.
- **Tenors:** TU / FV / TY / US (2/5/10/30Y).
- **Trade structure:** continuous, rolled quarterly (unbroken daily MTM curve; we exit
  before first notice, so no delivery/tail mechanics).
- **Financing:** SOFR GC proxy (`load_us_treasury_gc_fixing_pct`, SOFR→FedFunds,
  prev-day fixing) − configurable CTD specialness bps, ACT/360, on the cash leg's daily
  dirty market value × (1−haircut). Long bond pays (sign −1), short earns (+1).

## Architecture (3 layers)

```
Query/USTFutureBasis/          NEW Query product ("USTFutureBasis object")
BT/signals/ustf_basis.py       NEW backtest runner + helpers (roll calendar, panel cache, plots)
notebooks/backtests/ustf_basis/  4 config-driven notebooks -> daily MTM PnL graphs
```

### Layer 1 — `Query/USTFutureBasis/` (mirrors the 8-file `Query/USTFutures/` pattern)

```
USTFutureBasisQuery.py        product="USTFUTUREBASIS"; symbol, bond_cusip(None=CTD),
                              repo_rate/specialness; forces market_request["include_basket"]=True
USTFutureBasisStructure.py    enum {BASIS, CALENDAR}; CF/DV01-neutral leg sizing
USTFutureBasisValue.py        enum {GROSS_BASIS, NET_BASIS(=BNOC), IMPLIED_REPO, CARRY_BPS,
                              DV01_HEDGE_RATIO, FUTURE_DV01, BOND_DV01, NPV}
_USTFutureBasisGenericPricable.py / _USTFutureBasisGenericPricer.py
adapter.py                    register_product("USTFUTUREBASIS") + register_handler
position_handler.py           USTFutureBasisHandler (PnL core)
backends/rateslib/RLUSTFutureBasis{Pricable,Pricer}.py
```

The Pricer wraps `RLUSTFuturePricer` (already embeds the basket) + selects the CTD (or an
explicit cusip) and **delegates** gross/net-basis/BNOC/IRR/CF to it — no re-implementing
basis math. Adds DV01-hedge-ratio (for the CTD, CF-weight = DV01-weight) and financed
carry (reuses `Query/FixedRateBonds/carry_roll.py`).

### Layer 2 — `BT/signals/ustf_basis.py`

Reusable runner(s) + helpers, idiomatic with existing `BT/signals/*` runners:
- roll calendar: front quarterly contract per tenor; roll `roll_days_before_first_notice`
  bd before first notice (uses MDP `resolve_delivery_contract` + delivery-window helpers).
- daily basis panel cache (per tenor → parquet) for fast notebook re-runs.
- `run_ustf_basis_backtest(config)` drives `QueryDrivenBacktest` with `USTFutureBasisHandler`
  (systematic + BNOC-signal differ only in config-driven entry/exit).
- `run_ustf_calendar_roll_backtest(config)` uses existing `USTFuture` SPREAD legs.
- standard PnL plot (per-tenor + combined + decomposition).

### Layer 3 — `notebooks/backtests/ustf_basis/`

| # | Notebook | Engine path | Logic |
|---|---|---|---|
| 1 | `01_systematic_ctd_basis.ipynb` | USTFutureBasis + engine | Continuous rolled long-basis and short-basis sleeves on CTD, per tenor. |
| 2 | `02_net_basis_bnoc_signal.ipynb` | USTFutureBasis + engine | z-score BNOC vs trailing window → long when cheap, short when rich. |
| 3 | `03_calendar_roll_spread.ipynb` | USTFuture SPREAD (front−back) | Futures-only calendar; tail-repo + CTD-yield spread. No cash financing. |
| 4 | `04_ctd_switch_optionality.ipynb` | USTFutureBasis + basis-report panel | CTD vs runner-up net basis + `is_ctd` flips; long basis into switch / high realized vol (documented proxy). |

Each notebook: top config cell → `run_*` → daily MTM graph (per-tenor + combined) +
tearsheet + PnL decomposition.

## PnL accounting (core correctness requirement)

Per **long-basis** position (short = flip signs), daily:
```
daily_pnl =  cash_leg_MTM      (long, QL dirty-NPV change vs entry)
           + futures_leg_VM     (short, -(F_t - F_{t-1}) * $pt * n_f, tick-based)
           + coupon_realized    (cashflows_between on payment dates, gross)
           - repo_financing     (SOFR-GC - specialness, ACT/360, on cash dirty value)
```
Identity to plot: `daily_pnl ≈ (N/100)·Δ(gross_basis = B − cf·F) + (coupon − repo)`.
`n_f = round(N/100k · CF_CTD)` (CF-weighted). Component histories:
`futures_total / bond_total / financing_total / net_total`.

## Defaults (override via config)

- Sizing: $100mm cash face per tenor, CF-weighted futures; PnL in $ and per-DV01.
  Combined book = DV01-equal across the 4 tenors.
- Specialness: 0 bp default (per-tenor knob).
- Tx cost: 0.5/32 per futures side; repo flat.
- Roll: a few bd before first notice (configurable).
- Haircut: 0.

## Validation + tests (`tests/`)

- `USTFutureBasis` basis values **match `USTFuturesMDP.get_basis_report`** on sample dates.
- Financing sign/magnitude matches `FinancedFixedRateBondHandler` conventions
  (see `tests/test_fixed_rate_bond_backtest.py`).
- Tiny end-to-end engine run asserts `mtm_history` covers the full grid (engine swallows
  per-day pricing errors with print+continue — assert no gaps).
- Sanity: long-basis cumulative PnL ≈ entry gross basis monetized + carry.

## Risks / notes

- First run = heavy cached backfill (4 tenors × ~500 bd × basket pulls). Warm caches /
  run in background; re-runs cheap. Always verify `mtm_history` covers the full grid.
- RL (basket/CTD/CF/basis) vs QL (cash-leg MTM/financing/coupons) split is deliberate.
- Repo rate is in **percent** on the future-pricer side, **decimal** in the financing
  handler — normalize at the boundary.

## Implementation plan (phased)

1. **Scaffold + tests-first** `Query/USTFutureBasis/` object (Query/Structure/Value/
   Pricable/Pricer/adapter); unit-test basis values vs `get_basis_report`.
2. **`USTFutureBasisHandler`** (combined futures-tick + cash financing/coupon MTM);
   unit-test financing sign/coupon realization; register product+handler.
3. **`BT/signals/ustf_basis.py`** runner + roll calendar + panel cache + plot; tiny
   end-to-end test (no-gap mtm_history).
4. **Notebook 1** (systematic) end-to-end as the template; run 2y, verify graph.
5. **Notebooks 2–4** (BNOC signal, calendar roll, CTD-switch).
6. Full 2y run across TU/FV/TY/US; verify + report back with graphs.
```