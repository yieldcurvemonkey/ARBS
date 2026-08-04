# Linear-vs-Vol Mispricing — the Backtest Grid

**Date:** 2026-08-03
**Branch:** `feat/linvol-backtest-grid` (stacked on `feat/impdist-linear-vs-vol`)
**Question:** of every way to trade the measured gap between the FF/ZQ
lattice and the SR3 option surface, which strategy family and config is
best — and is anything ALIVE after costs and multiple-testing discipline?

## What the measurement passes established (inputs, not hypotheses)

The mispricing has ONE dominant shape at long horizon (the surface flattens
modal count-buckets and pays every non-modal cell — a single dispersion
premium) and an EPISODIC shape near expiry (one-sided single-bucket
dislocations — the convergence channel, feasible <60dte). The linear legs
agree on the path to ~1bp and disagree on attribution by ~4bp. The level
(ICS) is its own listed market, ~75% mechanical.

## Data (already built — this study is joins, not builds)

- `notebooks/data/meeting_prob/boundaries.parquet` — 1,329 contract-days ×
  ~6 listed 6.25bp-vertical digitals vs strict-null tree digitals, with
  strikes, smear, saturation (2024-07-01 → 2026-07-28, 9 quarterlies).
- `notebooks/data/meeting_prob/monitor.parquet` — 1,337 contract-days:
  per-meeting q_opt/q_zq/pgap/tstat, channel, event stds, forward, dte.
- `notebooks/data/meeting_prob/tieout_gate.parquet` — 540 sessions.
- `sfr_rv_lab/quotes.parquet` — 199k listed premiums (as_of, symbol, right,
  strike, premium_bp, oi, volume): marks any fixed-strike package daily.
- ZQ serff settles + fixings cache + `RVUtils/MeetingProb` (ladder,
  swap_ladder, ics, atoms, backtest engine, SFRRVLab.stats).

## Strategy families (the "type" axis)

- **A. Bucket convergence** (generalized channel-1): trade one listed
  6.25bp boundary vertical against its tree digital, ZQ-meeting-basket
  hedged (frame-frozen ratios), exit at meeting resolution / time stop.
  Grid: boundary class {mode-flank, outer, largest-|gap|} × |gap| threshold
  {4, 6, 8, 10pp} × dte band {<30, 30–60, 60–90, all<90} × gates {on, off}
  × exit {resolution, 10d stop} × direction {fade, momentum}.
- **B. Dispersion fly** (the one-premium package): buy the 25bp vertical
  covering the modal bucket, sell the two flanking 25bp verticals (1:1:1
  condor of verticals), fixed strikes at entry, marked daily from quotes,
  unhedged (delta beta reported as diagnostic). Grid: sign {short-disp,
  long-disp} × entry {always-on monthly, mode-deficit >20pp, >25pp} × dte
  band {30–60, 60–90, 90–135, 135+} × hold {to 30dte, 20 sessions}.
- **C. Tail harvest** (off-lattice insurance): the outermost boundary
  vertical (above / below / both), sell or buy, hold to expiry or stop.
  Grid: side × direction × tail-gap threshold {4, 6pp} × dte band.
  Below-tail rows flagged: the spline check halved that tail; only listed
  marks are used here, but quotes are sparse deep OTM — coverage reported.
- **D. Per-meeting divergence calendar** (small): when monitor's
  pgap_<mtg> for the first meeting NOT shared with the front contract
  exceeds a threshold with |tstat| gate, trade the back-contract boundary
  vertical vs the front-contract vertical at the nearest boundary.
  Deliberately few configs (~12) — weak identification is known.
- **E. ICS level** (benchmark): daily decomposed residual (observed blend
  spread − basis − compounding − proxy wedge) per front quarterlies; fade
  at {2, 3bp} thresholds, turn-quarters {in, out}. Futures-only costs.
  Exists to CONTEXT the serff conclusion, not to relitigate it.

## Honesty rules (inherited, binding)

Lag-1 on the global session calendar; listed marks only (quotes panel; no
BL/spline anywhere in PnL); costs per contract per side (SR3 option
0.125bp, SR3/ZQ futures 0.25bp half-ticks) at multipliers {0, 1, 2};
fade AND momentum for every config (sign test must mirror); league reports
n, hit, gross, net@1x, net@2x, t, Sharpe, and **deflated Sharpe with the
FULL trial count across all families**; chronological-half stability and
winner-neighborhood stability; verdict taxonomy per SFRRVLab.

## Placebos and confounds (the kink-fade lesson)

- **P1 Gaussian tree**: replace the lattice tree with a Gaussian matched to
  its mean/std; recompute family A/C signals. Edge that survives is option
  mean-reversion, not lattice information.
- **P2 wrong calendar**: shift ZQ q's by one meeting; a real mechanism dies.
- Winner confound checks: FOMC proximity, IMM-roll windows (22/33 rolls ARE
  decision dates), tie-out regime, saturation regime.

## Deliverables

`notebooks/backtests/linvol_grid_common.py` (panel loads, package engine,
placebo trees) + engine tests; runner → `notebooks/data/linvol_grid/
league.parquet` (checkpointed per family); executed notebooks
`linvol_grid_league` (league, sign tests, splits), `linvol_grid_autopsy`
(winner + placebos + confounds), `linvol_grid_summary`; findings doc;
memory; PR stacked on #376.

## Non-goals

No intraday. No new RND extraction. No re-run of the meeting-prob refit
history (panels are frozen at 2026-07-28 — the sample is 2 years and 3 more
days buy nothing). Family D is a probe, not a thesis.
