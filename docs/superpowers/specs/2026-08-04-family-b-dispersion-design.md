# Family B — the Dispersion Premium, Properly Harnessed

**Date:** 2026-08-04
**Branch:** `feat/family-b-dispersion` (stacked on `feat/linvol-backtest-grid`)
**Question:** the grid showed the 16pp flatness premium doesn't harvest as
episodic fly trades — but that harness gave a quarterly-resolving premium
1–3 trades per config. Rebuilt as a carry study with event attribution,
extended into the hiking cycle, with structure variants and the
intra-quarter mean-reversion question answered explicitly.

## Deliverables

**B1 — the carry harness.** Rank-based rolled books (Q1/Q2/Q3 = first,
second, third non-expired quarterly; roll at expiry−3d; strikes fixed
within each holding, re-struck at roll):
- `FLY25` / `FLY50` — 1/−2/1 butterflies at the tree-modal bucket center
  (25bp and 50bp wings): long = short dispersion.
- `STRG50` / `STRG75` — short strangle at ATM±2 / ±3 buckets: the
  off-lattice tail sale.
- `DFLY` — double butterfly (+1/−3/+3/−1 across four 25bp strikes): trades
  the SKEW of the count distribution (hike-side vs cut-side reallocation),
  the path-scenario extension the fly can't see.
- `CAL` — the frontier-slope calendar: long Q3 fly, short Q1 fly (B4) —
  harvests the +28bp→0 premium compression measured in the triangle.

Daily marks from listed premiums only; forwards from serff SR3 settles;
roll costs charged per leg per side (0.125bp half-ticks) at 0/1/2×.
Attribution per book: ordinary-day carry vs decision-window days (±1 of
FOMC) vs expiry-settlement events (final payout vs last premium), plus a
Δforward regression beta (the hedgeable drift component). NW t-stats on
the daily series (autocorrelation-robust), both signs of every book.

**B2 — history extension.** Probe verified barchart serves expired chains
to 2022. `famb_backfill_quotes.py` (running) pulls quotes-only panels for
SFRH22–SFRZ24 (12 symbols incl. the SFRU24/SFRZ24 gap the lab's rolling
strip skipped). Books extend into the hiking cycle — the regime where
50/75bp meetings delivered genuinely off-lattice outcomes. ZQ ladders for
the tree side come from the serff ZQ history (2018+) — no refits needed.

**B3 — the Sep-2024 autopsy.** The 50bp cut: was it on-support in the ZQ
lattice on the eve (mantissa between −25 and −50 ⇒ support (−2,−1) ⇒
ON-lattice coin flip, not an insurance event)? What did the modal fly and
the tails actually pay through the event, in SFRH25 (in-panel) and SFRZ24
(post-backfill)? Calibrates what "the insurance pays out" even means.

**Mean-reversion question (new).** Daily richness series per (book,
contract): `rich_bp = market premium − tree-fair premium` with the
tree-fair leg priced by `RVUtils.MeetingProb.pricer.price_option` under
the strict smeared tree (verified: SFRZ26 modal fly fair +8.55bp on
07-28). OU/AR(1) half-life per contract-rank and regime; variance-ratio;
then an intra-quarter rule (enter |rich| > thr, exit at thr/2 or h
sessions, NEVER holding to expiry) vs the hold-to-resolution book. If the
half-life is sessions rather than the whole quarter, the premium is
tradeable as mean reversion; if not, it is terminal-only.

## Discipline

Same rules as the grid: listed marks, lag-1, per-contract costs, both
directions, NW t-stats (overlapping daily series), config counts reported
for DSR, verdict taxonomy. The books are few and pre-declared (6 books ×
3 ranks × 2 signs + one small mean-rev grid) — this is a measurement-first
study, not a search.

## Kill criteria (pre-declared)

- "Fairly-priced insurance": |carry| ≈ event payouts across BOTH cycles →
  question closed, no strategy.
- Carry Sharpe < 0.3 after 1× costs on every book and rank → closed.
- Mean-reversion half-life ≥ ~40 sessions → intra-quarter trading dead;
  terminal-only confirmed.
- CAL: if compression carry is inseparable from outright fly PnL (beta to
  Q1 fly > 0.8), the calendar adds nothing.
