# US Treasury Futures Basis — Backtest Suite

Query-driven backtests of common UST-futures **basis** trades over the past 2 years,
with correct daily mark-to-market PnL and repo/UST financing. Built on a new
`USTFutureBasis` Query object + `USTFutureBasisHandler`, driven by the existing
`QueryDrivenBacktest` engine via `BT/signals/ustf_basis.py`.

## Notebooks

| Notebook | Strategy |
|---|---|
| `01_systematic_ctd_basis.ipynb` | Continuous, quarterly-rolled **long & short CTD basis** (cash-and-carry) across TU/FV/TY/US. |
| `02_net_basis_bnoc_signal.ipynb` | **Net-basis / BNOC** mean-reversion: buy the basis when the delivery option is cheap, sell when rich. |
| `03_calendar_roll_spread.ipynb` | Front-vs-back futures **calendar (roll) spread** (futures-only, no financing). |
| `04_ctd_switch_optionality.ipynb` | **CTD-switch / delivery optionality** harvest (long cheap optionality when a switch is near + vol is high). |

Each notebook is config-driven (top cell). Default: 2024-06-01 → 2026-05-31, $100mm cash
face/tenor, CF-weighted futures, SOFR-GC − CTD specialness financing (ACT/360), 0.5/32 roll cost.

## Architecture

```
Query/USTFutureBasis/        new Query product (analytics) + USTFutureBasisHandler (PnL)
  RLUSTFutureBasisPricer     wraps RLUSTFuturePricer; delegates gross/net basis, BNOC, IRR, CF;
                             picks the CTD (or an explicit cusip) as the cash leg
  position_handler.py        futures tick PnL + cash QL-NPV MTM + repo financing + coupons
BT/signals/ustf_basis.py     roll calendar, config, runners, daily basis panel cache, plots
```

**Data:** futures + deliverable basket/CTD/CF/gross-net-basis/IRR from
`USTFuturesMDP("BARCHART_USTF-RL")`; the cash leg (the specific bond bought, which can later
leave the basket) is priced by cusip with QuantLib via `FixedRateBondsMDP("...-QL")` (FedInvest),
so it is always available.

## PnL & financing (long basis = buy CTD cash / sell CF-weighted futures, direction=+1)

```
daily_pnl =  cash_leg_MTM       direction * (QL dirty NPV_t − NPV_entry)
          +  futures_leg_VM      −direction * (F_t − F_entry)/tick * tickval * n_contracts
          +  coupon_realized     direction * coupons in (last, now]
          −  repo_financing      direction>=0 pays GC−specialness, ACT/360, on cash dirty value
```
CF-weighting (`n = round(face/100k · CF_CTD)`) is **DV01-neutral for the CTD** (verified:
cash DV01 = futures DV01). Short basis flips every sign. Components are split into
`financing` / `coupons` (realized) and price/convergence (open) for decomposition.

## Validation

`tests/test_ustf_basis_pricer.py` — basis analytics match `USTFuturesMDP.get_basis_report` exactly.
`tests/test_ustf_basis_handler.py` — financing/leg sign conventions + an end-to-end engine run.
`tests/test_ustf_basis_runner.py` — quarterly roll calendar + a no-gap end-to-end MTM check.
Run: `conda run -n stir pytest tests/test_ustf_basis_*.py -q`.

## Notes / caveats

- **Held bond can leave the CTD basket** mid-contract; we keep holding the bought bond (correct),
  so its "basis" becomes a cash-vs-futures spread with real residual risk through CTD changes.
- The continuous roll exits before first notice, so **no delivery/tail mechanics** are modelled.
- **Serialize Barchart backfills** — running two basket-fetching processes at once causes
  "No data returned" flakiness (proxy contention). First run is a cold backfill; re-runs are cached.
- The calendar (NB3) enters ~5 bd before the roll (when the deferred contract is liquid) and uses
  futures-only quotes (`include_basket=False`).
