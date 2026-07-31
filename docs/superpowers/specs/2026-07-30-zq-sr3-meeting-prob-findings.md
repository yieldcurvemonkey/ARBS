# ZQ-vs-SR3 Meeting-Probability RV — Findings

**Date:** 2026-07-30
**Branch:** `feat/zq-sr3-meeting-prob` (worktree)
**Design:** `2026-07-30-zq-sr3-meeting-prob-design.md`
**Executed notebooks:** `notebooks/backtests/meeting_prob_*.ipynb`
**Panels:** `notebooks/data/meeting_prob/` (monitor / boundaries / tieout)

## What was tested

The one framework in this research line with a second price: ZQ prices each
meeting's move probability P through its means (the FedWatch ladder); SR3
options price P(1−P) through variance and the node CDF through verticals.
Parity pins the option mean to the SR3 future — the dead channel the options
lab measured to a quarter-tick — so the whole comparison is shape, factored
into a convergence channel (per-meeting reallocation, two prices) and a
harvest channel (everything the lattice cannot represent, one price).

## Structural results (independent of any backtest outcome)

### 1. Quarterly SR3 surfaces cannot attribute probability to meetings

For a quarterly option, every resolved-by-expiry meeting shifts the whole
reference quarter, so all day weights are 1 and the meetings are
**exchangeable**: the atom distribution depends on the q-vector only through
symmetric functions. The surface identifies the distribution of the TOTAL move
count N — never which meeting carries which probability. Found by a failing
test (the refit recovered the planted q's swapped), then proven as an
invariance of the object itself and pinned by a test. Consequence: the
design conversation's "N_meetings tradeable dimensions" (A7) overstates the
rank — per-meeting attribution must come from ZQ (we regularize toward it,
attribution-by-parsimony), and the honest channel-1 signal is the N-space CDF,
i.e. the boundary digitals. Serial/mid-curve expiries would break the
degeneracy; the vendor feed has no usable near-money chains for them (measured
in the SR3 options lab).

### 2. Replication lives in the frame-frozen representation

When the market reprices a meeting, the forward moves with the expected path,
so the mean-pinned atoms sit at CONSTANT absolute rates (base + n·25bp) and a
digital at a fixed strike is an exactly **multilinear** function of the
per-meeting probabilities. Holding the forward fixed while drifting q — the
naive first implementation — breaks multilinearity through atom migration and
is an inconsistent joint dynamic. With frame-frozen hedge ratios, the planted-
path test recovers the entry probability gap **on every outcome branch** (all
four parametrizations): the meeting is the delivery date, not the bet. The
residual risks are exactly as the design conversation stated: off-lattice
outcomes (>25bp, intermeeting), support migration, and the cross term from
hedging at stale ratios between rebalances.

### 3. The lattice has a variance ceiling, and the surface lives above it at long horizon

Bernoulli variance maxes at P = 1/2: a meeting can contribute at most 12.5·w bp
of standard deviation. On 2026-07-27, SFRZ26 (137 days to expiry, three
resolved meetings): lattice ceiling ≈ 21bp of event std, plus ~5bp of
unresolved-meeting smear — against a listed surface pricing ~45bp of total
width. The refit saturates even at a 30bp smear cap; the two-digital
classifier reads **channel 2** (both tails rich vs the strict ZQ-null tree:
+17pp at forward+43bp, +12pp at forward+68bp, +8pp below). This is the SR3
options lab's "+21pp more tail than the FedWatch lattice" arriving through an
entirely different machine — the standing, one-sided, off-lattice premium
(A6's feasibility ceiling: *"above it, the option market is paying for
lattice-infeasible outcomes — measurable, one-sided information, not the
convergence trade"*).

### 4. The CME fixture ties end to end

The committed FedWatch tree builder reproduces the CME Sep-2022 worked example
from planted ZQ prices through this module's ladder (72.5bp → 10/90; Nov
81.4/18.6), and the 2026-07-27 ladder read P(Sep16 hike) = 68% off live cached
settles with the day-after-the-hold repricing visible.

## Empirical results (from the 2024-07 → 2026-07 panel)

<!-- FILLED AFTER THE EXECUTED NOTEBOOKS -->

- Tie-out gate: …
- Feasibility frontier in days-to-expiry: …
- Identification (half-tick bootstrap) in the feasible region: …
- Channel mix and episode structure: …
- Channel-1 backtest grid, sign test, cost scenarios, verdict: …

### 5. The ladder must keep the current month's meeting — and doing so is noisy

The first implementation started the FedWatch range at the month after
``as_of``, silently dropping each meeting for the ~three weeks before its
decision — the event window. Fixed and fixture-pinned (mid-September 2022
vantage reproduces the CME worked example). The residual limit: intra-month
jump extraction divides by the post-meeting day count, amplifying ZQ price
noise late in the month — the 2024-09-17 read is P(50bp) = 78% against
official FedWatch's ~64% (both on the right side of the coin flip; the realized
outcome was 50). A realized-EFFR-anchored current-month treatment is the
upgrade path.

## Honest limits

- Daily EOD marks; the design conversation itself predicted the cross-market
  lag is "real for hours, not weeks" — episodic, event-window, intraday. A
  clean EOD null here does not disprove the intraday version.
- The ZQ hedge is marked through the ladder (a fixed-weight ZQ basket), not
  through individually simulated ZQ fills; costs are per contract per side
  with the DV01 conversion stated, support-migration rebalances understated by
  design and disclosed.
- One rate cycle, ~17 meetings. Per-meeting resolution keeps trades
  near-independent, but regime coverage is thin and the 2024-07 start
  excludes the hiking cycle entirely.
