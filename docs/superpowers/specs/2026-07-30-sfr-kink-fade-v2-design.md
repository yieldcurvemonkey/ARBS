# SFR "Fade the Kink" v2 — what a kink actually is

**Date:** 2026-07-30
**Branch:** `feat/sfr-kink-fade-v2`
**Outcome:** `2026-07-30-sfr-kink-fade-v2-findings.md` — **the hypothesis below is
wrong, and the notebook measures by how much.** This document is left as written
so the record of what was believed going in survives. Two of its estimates did
not hold: the "±15bp butterfly in the hiking cycle" in the next section is out by
an order of magnitude (a fly sees the *second difference* along the strip, so the
relevant pace is ~3.5bp per meeting, not ~50), and the fitted level-neutral wing
split of 0.463/0.537 turns out **not** to be the calendar.
**Supersedes:** `notebooks/backtests/sfr_kink_fade_backtest.ipynb` (verdict **RED**,
`notebooks/backtests/SFR_screeners/FINDINGS_kink_fade.md`)
**Ground truth, not background reading:**
`2026-07-29-sfr-fly-meanrev-findings.md` (structural results, bug log, the §5a
retraction), `2026-07-29-sfr-fly-meanrev-design.md` (sign conventions, honesty
rules), `notebooks/backtests/SFR_screeners/kink_fade_backtest.py`
(`ls_fade` / `fama_macbeth` / `nw_t`).

## The problem with the old definition

The incumbent notebook defines a kink as a **6m butterfly whose own 60-day
z-score is extreme**, and fades it. That treats every unit of curvature in the
SR3 strip as a dislocation. It is not, and the reason is mechanical:

> **SR3 settles on the day-weighted compounded average of overnight SOFR across
> its IMM reference quarter.** A contract whose quarter contains two policy
> meetings is legitimately priced differently from one containing one, and a
> meeting late in the quarter moves the contract by only a fraction of its jump.

The FOMC meets eight times a year; the IMM grid divides the year into four
quarters whose boundaries are the third Wednesday of March, June, September and
December. Those two calendars do not commute. Measured on the built panel
(2018-05-04 → 2026-07-29, 29,028 3m-fly observations), the butterfly a path of
**1bp per meeting** would print — call it `phi_sum` — has

| | |
|---|---|
| mean, every CM slot | ≈ **0.000** |
| standard deviation | **0.127 – 0.145** |
| range | **−0.341 … +0.297** |
| share of days with an equal integer meeting count in both gaps | **35 – 45%** |

So on more than half of all sessions the two halves of a butterfly do not span
the same number of meetings, and the resulting curvature is worth **`phi_sum ×
(bp per meeting)`**. In the 2022-23 hiking cycle, at ~50bp per meeting, that is
a **±15bp** butterfly with no information in it at all. `SFR123`'s whole daily
standard deviation in that regime was 3.73bp.

**Fading that is fading the calendar.** It is also, note, a *predictable* thing
to fade: `phi_sum` is known years in advance and mean-reverts on a one-year
cycle, so a trailing z-score of the raw fly will happily report a two-sigma
dislocation that is pure arithmetic.

This is the hypothesis the lab tests. It is not assumed.

## What we are *not* re-deriving

From the prior lab, treated as settled:

* **The binding constraint is move size, not sign.** Fade beats momentum in 17
  of 23 frameworks and the whole lab still loses. The gross edge is ~0.39bp per
  trade against a **2.0bp** per-contract round trip. An oracle with perfect
  direction captures ~2.4bp/trade — barely above cost.
* **Costs are per contract.** A `1/-2/1` fly is **4 contracts**; each SR3
  contract is $25/bp; round trip = `4 × 2 × 0.25 = 2.0bp`. The 1.5bp per-*leg*
  figure in the prior lab is ~25% optimistic.
* **`net_fade + net_momentum = −2 × total_cost`.** Flipping the sign flips gross,
  never cost.
* **Re-weighting cannot improve cost per sigma** for identical-DV01 futures
  (measured invariance 1.000). `1/-2/1` is the cheapest level-neutral 3-leg
  package that exists.
* **The back of the strip is a tick lattice.** `SFR-14-15-16` has σ = 0.52bp =
  one tick. Ranking flies by fitted half-life puts the least tradeable slots on
  top. σ is always reported in grid steps.
* **Regime dominates**: +476bp hiking vs −905bp cutting, summed across
  frameworks.
* **Q16STIRT is degenerate on recent dates.** Everything marks on **raw SR3
  settles**.

## Sign conventions (one place)

| Object | Definition | Units |
|---|---|---|
| contract rate | `100 − settle` | percent |
| **fly** | **`2·belly − front − back`** | **bp** |
| internal weight `w` | positive = paid | — |
| desk notation `1/-2/1` | negative = paid | — |

Verified on the built panel: `structures_3m.value == (2·leg1 − leg0 − leg2)·100`
exactly on all 29,028 rows (and `+ (…)·100` is off by up to 134.5, so the sign is
not ambiguous).

⚠ `BT/signals/sfr_cal_spread_rv.py::compute_fly_curve` uses the **opposite**
convention (`front − 2·belly + back`, "positive = wings expensive"), and the
incumbent kink-fade stack is built on it. Nothing in this lab imports it. The
prior pandas study `kink_fade_backtest.py` works in *price* space
(`bf_bps = (P_n − 2P_m + P_f)·10000 = −(rate fly)`), which is a third convention;
`ls_fade` happens to be invariant to it because negating both the signal and the
target swaps the long and short books and negates the P&L.

## The candidate kink definitions

Each is a `signal_fn(levels, **params) -> DataFrame` on the same level panel, so
they go through one engine, one grid, one sign test, one shadow decomposition and
one verdict function.

### K0 — raw z-score (the incumbent, reproduced honestly)

`zscore_signal(levels, window, ma)`. The control. Its job is to reproduce the
prior RED under per-contract costs so every other row has something to beat.

### K1 — meeting residual (**the bet**)

On each date, fit per-meeting jumps `delta` to the whole 16-contract strip
through the day-weight matrix `W`, penalising the **second difference** of the
jump sequence:

```
min over (base, delta)   || base + W·delta − r ||²  +  lam · || D²·delta ||²
```

then take `resid = r − fitted` per contract and combine the residuals into
butterflies with the same `1/-2/1` weights the level uses.

The penalty is the entire design. `lam → 0` fits every jump and the residual
vanishes; `lam → ∞` forces the jump path onto a straight line in meeting index —
a Fed that accelerates perfectly smoothly — and the fitted strip is then the
**lumpiest curve a perfectly regular Fed could produce**. The residual is what
the calendar cannot explain. A linear-in-meeting-index path sits in the null
space of the penalty and is fitted for free at any `lam`, which is the property
under test in `tests/test_meanrev_meetings.py`.

Note what this is *not*: `RVUtils/SFRRVLab/lattice.py::solve_meeting_jumps`
ridges the jumps themselves, shrinking toward "the Fed does nothing". Right prior
for a FedWatch lattice, wrong one here.

Measured, 2022+, `lam=10`: per-contract residual σ falls from **0.98bp at slot 1**
to **0.07bp at slot 16** against strip rates of 3-5%.

`lam` is swept. So is the standardisation: `scale` (divide by a trailing σ but
**keep the model's zero**) versus `z` (full trailing z-score, which throws the
model's zero away and re-centres on a trailing mean) versus `raw` (a threshold
in bp).

### K2 — the calendar-tilted fly (one degree of freedom, no fitting)

Using only the structure's own two wings:

```
pace   = (r_back − r_front) / (M_back − M_front)        bp per effective meeting
fly_adj = fly − phi_sum · pace
        = 2·r_belly − (1 − phi/dM)·r_front − (1 + phi/dM)·r_back
```

Still exactly level-neutral, so it is still a butterfly — just a **calendar-tilted
one**, with wing shares `(1 ∓ phi/dM)/2`. With `sd(phi) ≈ 0.135` and `dM ≈ 4`,
the tilt moves the wing split by about **±0.034 around 0.5**, i.e. **0.466 /
0.534**.

That is worth stating loudly, because the prior lab's §5a found a fitted
level-neutral wing split of **0.463 / 0.537** and could not explain it. This lab
tests directly whether the fitted tilt is the calendar. If K1 (a jump per
meeting) does not beat K2 (one number per structure per day, no estimation), the
extra machinery is not earning its keep.

### K3 — cross-sectional fade on the residual

The prior work's one genuinely positive result was the naive within-bucket
`ls_fade` (IR ≈ +1.35 gross, non-overlapping Sharpe ≈ +1.97) — gross of costs,
one regime, one year. Reproduced with per-contract costs, on both the raw fly and
the meeting residual, using `xsection_signal` through the same engine so the cost
model is the engine's and not `ls_fade`'s flat per-date charge.

### K4 — calendar gating

K0 restricted to structures whose meeting counts are symmetric (`asym == 0`) or
whose `|phi_sum|` is small. Answers the brief's question directly: *is the fade
only real when the calendar is not creating the kink?* Gates apply at entry only.

### K5 — curve-fit residual in meeting time

`curvefit_residual_signal` fits smoothness against **slot index**, i.e. it assumes
the strip should be smooth in calendar time. The meeting-space analogue uses the
cumulative effective meeting count as the abscissa. Cheap, and it isolates
"smooth per meeting" from "smooth per quarter".

## The diagnostic that decides it: the pond test

A better signal can only help in two ways — call the sign more often, or **select
days on which the fly moves further**. The prior lab established that the second
is binding, and it is measurable before any backtest. So every candidate reports,
at fixed horizons 5 / 10 / 21:

| | |
|---|---|
| `oracle_bp` | `E[ \|level[t+h] − level[t]\| ]` on the days the signal fires — what perfect direction-calling captures. An upper bound. |
| `selectivity` | that expectation over its unconditional counterpart. **1.0 means the signal is picking days at random with respect to move size**, and every bp of edge must then come from the sign call alone. |
| `p_beat_cost` | `P(\|move\| > 2.0bp)` on the selected days. |

`RVUtils/MeanRev/diagnostics.py`, tested synthetically. This is the block that
can kill a definition without running a grid, and it is placed before the grids
for that reason.

## Data

Reuses the built panel — `notebooks/data/sfr_fly_meanrev/{contracts,
structures_3m, structures_6m, slot_panel}.parquet`, 2018-05-04 → 2026-07-29,
2,074 sessions, 55 contracts, 66,227 contract-days. Marks are raw settles;
`rate_pct = 100 − settle` verified exact on every row. `imm_start` / `imm_end`
are the contract's true accrual quarter (third Wednesday to third Wednesday;
91 days on 51 of 55 contracts, four 84/98-day exceptions from the five-week
quarter roll) — which is what makes the day-weight matrix exact rather than
approximate.

**One date is dropped: 2025-07-04.** It is a US market holiday that nonetheless
carries a panel row built from **8 contracts — H29 … Z30, all with zero open
interest**. The strip builder slotted those deep back months into slots 1–8, so
`slot 1` is a four-year-forward contract, the front slot prints a −57bp jump in
and +58bp out, and every structure on that date is mislabelled (`H29-M29-U29`
tagged `SFR123`). It is the only session in the file with fewer than 16
contracts. Verified in `notebooks/rv/_probe_kink_bad_dates.py`.

Windows are the prior lab's, chosen from measured liquidity:

* **`liquid16`** — 2022-01-03 onward, all 16 slots; the only honest full
  cross-section.
* **`front8`** — 2019-01-02 onward, back leg inside slot 8; the regime-rich
  window, and the only one containing ZIRP and the hiking cycle.

### The FOMC calendar

New: `RVUtils/MeanRev/meetings.py` carries the scheduled decision dates
(the second day of each two-day meeting; the new target range is effective the
next day, hence `effective_lag_days=1`).

* **2018–2026 actual, 2027 published, 2028+ projected** and flagged as such in a
  `source` column. Any result leaning on projected rows has to say so.
* Validated three ways: 32 of 32 dates match
  `Query/IRSwaps/_CENTRAL_BANK_DATES._FALLBACK_DATES['USD-SOFR-1D']` over
  2023-01 → 2026-12 exactly; the lab's own regime boundaries (2022-03-17,
  2023-07-27, 2024-09-18) land on meetings; and the notebook runs an **empirical**
  check — the mean absolute daily move of front SR3 rates on decision days versus
  every other day, over 2018-2022, where no in-repo source exists.
* **2020 is the scheduled calendar, not the realised one.** The 2020-03-15
  emergency cut replaced the scheduled 2020-03-17/18 meeting and 2020-03-03 was
  an intermeeting cut. Neither was in anyone's day-weight matrix the day before,
  and this module models what the strip could price.
* Projection is anchored on the last Wednesday of January with gaps
  `(7,6,7,6,7,6,6)` weeks — which reproduces 2026 exactly and is within 7 days on
  2–3 of 8 meetings for 2023-25. The notebook re-runs with the projection shifted
  ±1 week and reports the signal correlation rather than asking anyone to take
  that on trust.

## Costs

Per **contract**, not per leg. `4 × 2 × 0.25 = 2.0bp` round trip on a `1/-2/1`
fly; the linear shadows pay their own contract counts (outright belly 1 contract
= 0.5bp, a belly-versus-wing spread 2 contracts = 1.0bp). Headline scenarios
**0.0 (maker) / 2.0 (taker) / 2.5 (stress)**, and the full cost curve is printed
for every framework.

## Honesty rules (inherited verbatim — each one earned)

1. Lag-1 fills. A **deterministic** exit (fixed horizon, max hold, stop breached,
   end of sample) is known at entry and is **not** lagged twice.
2. Costs charged once per completed trade, on the exit bar, in the daily series
   too.
3. Grid discipline: the distribution (median config, % net positive), the
   deflated Sharpe with `n_trials` = configs actually run, and one-parameter-at-a-time
   neighbourhood stability. **The top row is never the verdict.**
4. Sign-test both directions, every framework.
5. Beat the linear shadow. `fly = (belly−front) + (belly−back)`; the outright
   belly beat the fly in 16 of 24 frameworks last time.
6. Split by regime.
7. Report non-overlapping Sharpe and Newey-West t alongside the per-trade t.
8. Verify field scales and print units early.
9. Forward-fill only, never `bfill`.
10. Verdict from `RVUtils/SFRRVLab/stats.py::verdict`, unchanged.

## Deliverables

1. This spec, and a findings doc that answers: **does removing the FOMC meeting
   structure turn the kink into a real signal, or was the prior RED verdict right
   for a deeper reason?**
2. `RVUtils/MeanRev/meetings.py` and `RVUtils/MeanRev/diagnostics.py`, plus
   `scale_only_zscore` / `meeting_residual_signal` / `calendar_adjusted_signal`
   in `signals.py` — all with synthetic, no-network tests.
3. `notebooks/backtests/sfr_kink_fade_backtest.ipynb`, executed, zero cell
   errors, zero unrun cells, built from `sfr_kink_fade_backtest.py` via
   `_py2nb.py`, executed with `jupyter nbconvert --execute --inplace`, verified
   with `_verify_nb.py`, driven by `run_sfr_kink_fade.py`.
4. `notebooks/data/sfr_kink_fade/` — league table, sign tests, regime splits,
   shadow tests, calendar table. Kept separate from the fly-meanrev lab's
   outputs so neither overwrites the other.

## Repo issues expected to be reported, not fixed

* **The incumbent kink-fade backtest is direction-blind.**
  `Query/IRSwaps/IRSwapStructure.linear_solve_for_risk_weighted_notionals` gives
  each leg the sign of its risk weight, and
  `RLIRSwapCurve.resolve_pricable(swap, risk_weight)` then multiplies by that
  same sign — so the resolved package is `|notional|` on every leg and
  `bpv = +100k` and `bpv = −100k` resolve to the **identical** all-payer strip.
  Entry NPV and mark both use the resolved package, so the traded direction never
  reaches the P&L. This is a shared Query/BT pricing seam used by other
  strategies; fixing it is a separate change with a large blast radius.
* 2025-07-04 in the built SFR panel (above).
* `RVUtils/SFRKinkFadeScreener` and `RVUtils/STIRRVScreener` import from
  `BT.signals.*` — inverted layering, already noted in the prior findings.
