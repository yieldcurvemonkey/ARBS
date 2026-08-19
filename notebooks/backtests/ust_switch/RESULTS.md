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

**The financing assumption IS the result.** The same baseline under the three modes:

| financing | n | price | carry (special) | cost | net/trade | Sharpe | NW-t | hit |
|---|---|---|---|---|---|---|---|---|
| none (flat GC — ARBS' native carry) | 65 | +1.117 | 0.000 | 0.675 | **+0.441** | +0.34 | **+2.05** | 0.66 |
| modelled (JPM + tenor/rank/age model) | 65 | +1.117 | −0.462 (−0.516) | 0.675 | −0.021 | −0.02 | −0.10 | 0.48 |
| actual (measured only, 2016-08–2025-08) | 36 | +0.970 | −0.619 (−0.629) | 0.676 | **−0.325** | −0.23 | −1.07 | 0.42 |

A flat-financing backtest would have called this trade alive at t=+2.05. Per-issue
specialness is the entire distance between that and dead — and the measured-only window
is *worse* than the modelled full sample, because 2016–25 contains the high-specialness
hiking cycle.

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

## QueryDrivenBacktest: per-tenor every-cycle equity curves

The same trade run END TO END through the repo's own engine — one QDB pass per tenor,
every auction cycle, pinned per-cycle CUSIPs, $1/bp legs (equity natively bp), SR1170
fees at unwind, grid restricted to days both legs actually price (without that
restriction one bad 20y mark on 2023-12-04, ~50bp rich and inside the 100bp gate, baked
+15.3bp into a book whose true annual P&L is ~2bp):

| tenor | trades | QDB zero-financing (bp) | net of per-issue financing (bp) | net/trade | vectorised net/trade |
|---|---|---|---|---|---|
| 2Y | 187 | −46.99 | −195.61 | −1.046 | −1.004 |
| 3Y | 197 | −141.64 | −183.90 | −0.934 | −0.921 |
| 5Y | 189 | −102.39 | −155.16 | −0.821 | −0.814 |
| 7Y | 197 | −176.37 | −186.01 | −0.944 | −0.940 |
| 10Y | 65 | **+40.40** | −1.36 | −0.021 | −0.021 |
| 20Y | 22 | −9.00 | −18.56 | −0.844 | −0.482 |
| 30Y | 65 | −37.88 | −39.26 | −0.604 | −0.596 |

Six of seven tenors agree with the vectorised engine to ≤0.05bp/trade; the 20Y differs
by 0.36 (22 trades, 13–15y durations where the yield-space carry identity is roughest —
the engines bracket it, and both say dead). The 10Y is the only tenor where the
zero-financing book is even positive — +40bp over 16 years — and per-issue financing
takes all of it. Splitting the same books into odd/even cycles halves each tenor's loss
almost exactly: the losses are cost-driven and scale with trade count, not with any
particular subset of cycles. Figures 13–15; artefacts in `_out/qdb/`.

## The QDB all-pairs grid, and the matched-maturity swap box

Second grid, run entirely on QueryDrivenBacktest marks: all 42 (tenor, rank-pair) books
through QDB in parity-split passes (per-cycle daily marks, exactly attributed), then
**8,716 configurations** recombining those marks -- direction x entry offset {0,1,3,5,10}
x exit {next-roll, 10/21/42d} x z-filter x instrument {bond switch, MMS box} x swap cost
{0, 0.5bp}. The MMS box hedges each leg with a matched-maturity USD-SOFR swap (Citi
curves; the window starts 2018-04 because SOFR does).

**0 of 8,716 ALIVE** (8,474 dead, 242 selection-artifacts). The whole top-25 is one
overfit corner: z-filtered FADES (long the current) entering roll+10 holding 10 days,
8-27 trades, hit rates 7-44% -- a few monster wins carrying rare books. Best
effective-trials DSR 0.024. Best cells by Sharpe: bond 10Y CTvOOO 1.54, MMS 30Y CTvOO
1.49 -- both artifacts.

**The matched-maturity hedge does not help: it hurts.** Across 2,816 cells matched on
(tenor, pair, direction, entry, exit, filter), the MMS box improves the bond switch in
only **23.5%**, mean dSharpe **-0.22**. The mechanism is the one the study already
measured from the other side: the curve-slope contamination in the raw spread is a
LEVEL effect that is nearly static over a one-cycle hold (both bonds age together), so
the swap legs hedge a term that produces little P&L while adding a real 0.5bp round
trip and, at the front end, doubling the cost line. Where the hedge does help most
often (3Y 47%, 2Y 35%) is exactly where the curve is steepest and choppiest; at 5Y-7Y
it improves 1-4% of cells. Figures 16-18; artefacts in `_out/qdb_grid/` and
`_out/qdb_allpairs/`, swap rates in `_out/mms_rates/`.

## Dealer auction concession: what the literature says and what this study measured

**Mechanism** (Boyarchenko-Lucca-Veldkamp, NBER w22461; practitioner framing in the MND
"What's an Auction Concession?" note): ~22 primary dealers absorb ~40% of every auction
under minimum-bidding obligations -- underwriting under a shadow cost. The market "makes
room" by cheapening the sector into the auction (the concession), and dealers aggregate
client order flow ("market color"), which the paper estimates is worth ~$5bn/yr of
auction revenue versus a Chinese-wall regime. The compensation for absorbing supply
shows up as **post-auction appreciation**: on 494 auctions the interest-rate-hedged new
issue gains **~3bp of value between auction date and issue date**, more when the
competitive (informed) share is higher (t=3.5), and the distribution is positively
skewed -- badly-concessed auctions produce outsized rebounds, which the paper attributes
to bad news being shared through dealers (their "financial accelerator").

**This study measured the same object from the switch's side, three ways:**

1. *Daily, bond-specific*: the pooled auction-cycle profile -- days 0-7 after the roll
   cost the long-old switch −0.25 to −0.8bp/day, which IS the new issue's post-auction
   appreciation seen from the short-the-new leg. Every surviving grid cell delays entry
   to roll+10, i.e. past the concession release.
2. *Placebo direction*: entering 7bd BEFORE the roll (inside the concession build-up)
   destroys the trade (Sharpe −0.88); after, it merely decays -- the asymmetry the
   mechanism predicts.
3. *Intraday, sector-level* (Citi minute SOFR curve, backward-only snapshots): rates
   cheapen into the 13:00 ET result and richen after -- see the event-study figures and
   the per-tenor 13:00→13:30 result-jump table. (Bond-specific intraday prices for
   individual off-the-runs do not exist in this stack; the intraday evidence is the
   sector rate level, stated as such.)

**Trading implication for the switch**: the classic long-old/short-current switch is
structurally short the concession-release. The short-current leg should be established
only after the ~3bp hedged appreciation has run (roll+10 by the daily evidence), and
intraday at or after the post-result richening -- not into the 13:00 print, where the
concession is at its widest and the new issue at its cheapest.

## Best intraday timestamps (measured, 124 auctions, Citi minute SOFR curve 2022-09..2026-08)

Backward-only snapshots (asof, 12-min tolerance, no future serves -- the store's default
nearest-snapshot policy DID serve future curves on the first run and was rejected).
Sector rate level, + = cheaper; anchored to D-1 15:00 ET; auction result 13:00 ET.

| tenor group | concession peak (cheapest) | release (richest in window) | 13:00->13:30 jump |
|---|---|---|---|
| 2Y (47 ev) | auction day 12:00-15:00 (+0.9 to +1.1bp) | **D+1 09:00 -> D+2 16:00** (-1.9 to -2.7bp) | -0.07bp (t=-0.6) |
| 5Y (47 ev) | auction day 12:00-15:00 (+1.2 to +1.6bp) | D+1 09:00 -> D+2 16:00 (-1.6 to -2.2bp) | +0.04bp (t=+0.4) |
| 10Y (15 ev) | D+2 09:00-10:30 (+2.5 to +3.0bp, refunding wave) | **D-1 13:15** (-0.6bp, post-3Y-result) | -0.20bp (t=-0.6) |
| 30Y (15 ev) | D+2 09:00 (+2.7bp) | D-1 13:15 (-0.4bp) | -0.10bp (t=-0.4) |

Three usable conclusions:

1. **There is no 13:00 scalp.** The average result-window move is 0-0.2bp with t < 0.7
   everywhere. The concession does not release at the print; at the front end it
   releases OVERNIGHT into D+1 morning (a ~3bp swing from D 15:00 cheap to D+1 09:00
   rich at 2Y), which is where the LYZ/w22461 appreciation lives intraday.
2. **Front end**: establish the LONG (old) leg on auction day 12:00-15:00 ET at the
   concession peak; establish the SHORT (new) leg no earlier than D+1 09:00, after the
   overnight release -- and the daily bond-specific evidence pushes it to roll+10.
3. **Long end (refunding week)**: the auctions stack (3Y -> 10Y -> 30Y), so the sector
   keeps CHEAPENING through D+2; the richest moment in the window is D-1 13:15, right
   after the preceding leg's result. A 10Y/30Y switch entered before the refunding wave
   completes fights supply; enter D+2 or later (daily evidence: roll+10).

Caveat, stated: these are SECTOR rate paths. Individual off-the-run intraday prices do
not exist in this stack, so the bond-specific intraday component (the new issue vs the
sector) is inferred from the daily cycle profile, not measured intraday.

## The catalyst loop, and the Month-End Switch Harvest

A directed search over structural catalysts (auction release, concession momentum,
issue-date/index-inclusion exits, specialness gating, month-end, quarter-end) on the QDB
marks. Trail: the auction-release trade is UNTRADEABLE in this data (the roll is
issue+1bd, so the w22461 auction->issue window closes before the new bond has a price
here -- WI prices do not exist in FedInvest); concession-momentum and specialness gates
produce no rescuing uplift (specialness terciles ARE monotone in subsequent LO pnl,
pooled -0.20/+0.06/+0.45 gross, but the gated books stay net-negative); quarter-end is
flat.

**The discovery: the old richens against the current on month-end day.** Pooled across
7 tenors on 26,855 QDB day-marks: month-end day +0.137bp (t=3.96), day before +0.043
(t=2.12), every other day of the cycle ~0. Positive in BOTH halves (2010-18 t=2.2,
2018-26 t=3.9), at 6 of 7 tenors (10Y t=4.1, 3Y t=3.6, 5Y t=3.4; only 7Y flat), and in
**16 of 17 calendar years**. It does not fully reverse in the next month's first days
(-0.10bp day-0, t=-1.6, ~30% of the gain) -- repricing around index duration-extension /
new-issue-settlement flow, not a month-end mark artifact.

**The strategy** (no fitted parameters -- the window is where the diagnostic located the
effect): hold LO CTvO, $1/bp per tenor, over the LAST THREE BUSINESS DAYS of each month.
199 month-ends, 2010-2026:

| cost assumption | net/event | monthly hit | event t | bp/yr | ann. Sharpe |
|---|---|---|---|---|---|
| gross (mid execution) | +1.175bp | 61.3% | +5.70 | +14.1 | 1.40 |
| 0.10x SR1170 | +0.551 | 47.2% | +2.67 | +6.6 | 0.66 |
| **0.19x SR1170** | **0 (break-even)** | | | | |
| full SR1170 taker | -5.070 | 5.0% | -24.6 | -60.8 | -6.03 |

Per-tenor break-even multiples: 3Y 0.54x, 2Y 0.22x, 5Y 0.15x, 20Y 0.13x, 10Y 0.12x,
30Y 0.06x, 7Y 0.02x. Figures 22-24.

**Verdict, stated plainly**: this is the highest-conviction structural regularity the
whole program has found (event t=5.7, 16/17 years, mechanism-first window), and it has
the respectable-Sharpe/high-hit-rate character asked for -- at mid execution. It clears
costs only below ~0.2x institutional effective spreads (0.5x at the 3Y alone), i.e. it
is a desk overlay for internalised flow, not a taker strategy. At full SR1170 costs the
session's cumulative verdict stands: ~14,000 configurations, zero alive.

## Validation chain (all pass)

| check | result |
|---|---|
| specialness vs JPM published `3m Repo Special` | corr 0.9997, mae 0.037bp, per-tenor 0.986–1.000 |
| carry formula vs JPM published `3m Carry` | corr 0.962, R² 0.926, median abs err 0.48bp |
| hand-reconciled trade vs engine | exact (0.00e+00); direction-flip and specialness-removal mutations both break it |
| QueryDrivenBacktest cross-check (price leg, pinned CUSIPs) | corr 0.98 over 6 cycles; offset **verified** as cross-leg carry: predicted (y_L/D_L − y_S/D_S)·Δt matches at corr 0.97, residual ≤ 0.05bp |
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
* One known surviving mark artifact: **2023-02-10**, both 10y legs repriced ~5.5 points
  (≈70bp of yield) in a single FedInvest snapshot and recovered over two days — a
  common-mode bad-price day the cross-rank gate structurally cannot see. It telescopes
  to +0.25bp within the trade that spans it and inflates daily vol, i.e. it deflates
  the reported Sharpe (conservative direction).

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
