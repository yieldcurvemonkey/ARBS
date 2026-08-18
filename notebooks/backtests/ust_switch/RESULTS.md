# Olds-vs-currents UST switch — results

2026-08-18. Branch `feat/ust-olds-currents-switch`, worktree `ARBS-sw`.
Daily mark-to-market 2010-01-04 → 2026-08-17 (4,148 business days), equity in bp of a
DV01-matched ($1/bp per leg) position. 958 CUSIPs across 2y/3y/5y/7y/10y/20y/30y,
ranks CT/O/OO/OOO, all six rank pairs, both directions.

## Verdict

**0 of 3,084 scored configurations ALIVE** (2,974 dead on negative net, 66
selection-artifacts, 44 too few trades; 3,396 trials counted including placebos).

The on-the-run premium is real and its mechanism is confirmed. It is also priced to
within ~0.02bp of the round-trip cost — the market charges almost exactly what the
convergence pays.

## The baseline in one table

10Y O-vs-CT, long the old / short the current, enter roll+1bd, exit next-roll+1bd,
65 trades over 16.6 years, measured+modelled per-issue financing:

| component | bp/trade |
|---|---|
| price (premium convergence) | **+1.117** |
| carry (of which specialness −0.516) | −0.462 |
| gross | +0.655 |
| execution (SR1170 Table 3) | −0.675 |
| **net** | **−0.021** |

Gross hit rate **72.3%** — the convergence itself is one of the most reliable effects
this program has measured. Net hit rate 47.7%.

## What killed it, by channel

* **Execution.** Full effective spreads by off-the-run rank (NY Fed SR1170 Table 3),
  price-bp → yield-bp via modified duration. Round trip 0.58–2.75bp depending on
  (tenor, pair). The front end is unaffordable outright: 2y/3y/5y/7y every-cycle cells
  run t = −5 to −17 — those tenors have essentially no premium (the raw rank pickup is
  *negative*; curve slope dominates) while paying the same cost.
* **Financing.** Per-issue specialness (JPM panel, tied out at corr 0.9997) costs the
  short-the-current leg −0.5 to −0.8bp/trade at the 10y. ARBS' native flat-GC carry
  would have missed this entirely.
* **Regime.** Baseline net by era: **+15.96bp pre-2018, −6.22bp 2018–21, −11.10bp
  2022–26.** The premium compressed (price leg 4–10bp/yr → 2.4–3.9) while specialness
  rose (carry −0.6 → −4.7bp/yr in 2024). The trade's own edge decayed along the same
  axis SR1170 documents for off-the-run liquidity.

## The best cell, and why it is not claimable

`10Y OOO-vs-CT, enter roll+10bd, exit next-roll+1bd, z(250)≥1 filter`:
+0.95bp/trade net, 26 trades, Sharpe 0.88, NW-t 2.16, break-even at 1.98× assumed cost.

Not claimable: DSR ≈ 0 against the search (raw 3,396 trials; effective-trial count 349
changes nothing — best DSR 7.8e-6), and its PSR vs zero is only 0.88 **before** any
multiple-testing correction. +9.7 of its +24.7 total bp came from 2010 alone.

## Mechanism findings (robust, and the useful output)

1. **The auction clock is real.** Top-12 mean Sharpe +0.584 vs placebo −0.075 when the
   same rules are shifted off the roll date. The degradation is direction-consistent:
   shifting entry −7bd (into the pre-auction window) destroys the trade (Sharpe −0.88);
   +7/+14bd keeps roughly half.
2. **Days 0–7 after the roll are the worst part of the cycle for the long-old trade**
   (pooled −0.25 to −0.8bp/day): the displaced bond keeps cheapening after losing
   benchmark status. Every top cell delays entry to roll+10. Premium is then collected
   mid-cycle at +0.03–0.13bp/day.
3. **The raw rank pickup is only positive at the long end** (20y +0.59/+0.95/+1.14bp by
   rank; 30y +0.25/+0.42/+0.41) — at 2y–10y the older bond *yields less* (slope
   dominates the liquidity premium in level space). The trade at 10y works gross off
   the *change*, not the level.
4. **20y: richest specialness (16.9bp mean when special), only tenor with a clean
   monotone premium, and still dead** — quarterly cycle gives 21 trades, and its cost
   (mapped from SR1170's 30y sector ×1.25 uncertainty haircut) is 1.9bp/trade against
   0.9–1.1bp of gross.
5. **Calendar seasonality is secondary to the auction clock**: July stands out on the
   best cell (t=3.4) and December is negative, but pooled across configs nothing
   survives that isn't better explained by cycle position.

## Validation chain (all pass)

| check | result |
|---|---|
| specialness vs JPM published `3m Repo Special` | corr 0.9997, mae 0.037bp, per-tenor 0.986–1.000 |
| carry formula vs JPM published `3m Carry` | corr 0.962, R² 0.926, median abs err 0.48bp |
| hand-reconciled trade vs engine | exact (0.00e+00); direction-flip and specialness-removal mutations both break it |
| QueryDrivenBacktest cross-check (price leg, pinned CUSIPs) | corr 0.98 over 6 cycles; offset = QDB's total-return marks vs spread-only |
| panel QC: rank-spread lag-1 autocorrelation | 42/42 cells ≥ 0.55 (median ~0.95) |
| placebo (off-auction-clock entries) | degrades as the mechanism predicts |

## Data hygiene that mattered

* 283 QuantLib yield-solver failures (CLEAN_PRICE=0 → YTM up to 8145%) — one such row
  turns a 0.86bp-sd spread into 18.9bp-sd white noise. Gated cross-sectionally + price
  and yield bounds.
* Alias series splice at every roll (measured −1.395 vs −0.358bp on the 2024-02-16
  refunding) — positions pinned to CUSIPs at entry, always.
* JPM tabula noise gated on the repo LEVEL, not the spread, so ZIRP and the March-2020
  fails episode survive.

## Blocked / out of scope

* **Citi Velocity GC tie-out**: harness ready (`tie_out_citi_repo.py`); Excel add-in COM
  transport dead this session (`ExcelDiedError`, re-login fails on this machine). Run
  `-m MDP.CitiVelocityExcel.repo.store --refresh` when signed in, then the script.
* Ranks 4–5 (SR1170 costs exist; alias parser stops at OOO) — needs explicit per-date
  CUSIP resolution and another fetch.
* Financing before 2016-08 is modelled (per tenor/rank/age median, thin cells dropped,
  capped at measured p95); the "actual" financing mode restricts to the JPM window and
  agrees in sign and shape.

## Artefacts

`_out/`: league_raw/league_deflated (3,360 rows), placebo, cost_curve, auction-cycle
and calendar seasonality CSVs, effective_trials.json, qc_panel, baseline trade log +
daily; `_out/figs/`: 12 figures. Reproduce: `build_jpm_repo_panel.py` →
`build_panel_chunks.py` → `run_study.py`.
