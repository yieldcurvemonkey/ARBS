# Linear-vs-Vol Backtest Grid — Findings

**Date:** 2026-08-03
**Branch:** `feat/linvol-backtest-grid` (stacked on `feat/impdist-linear-vs-vol`)
**Design:** `2026-08-03-linvol-backtest-grid-design.md`
**Executed notebooks:** `linvol_grid_{league,autopsy,summary}.ipynb`
(0 errors, 0 unrun); league at `notebooks/data/linvol_grid/league.parquet`
(272 real configs + 384 placebo rows), engine tests in
`tests/test_linvol_grid_engine.py` (9) on top of the 59-strong MeetingProb
suite.

## The question and the answer

Of every way to trade the measured gap between the FF/ZQ lattice and the SR3
option surface — which family and config is best, and is anything ALIVE?

**Answer: nothing is ALIVE.** 272 configs across four families, both
directions, per-contract listed-mark costs, 2024-07 → 2026-07:

| family | best (n-floored) | n | gross | net@1x | net@2x | DSR | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| A bucket convergence | mode_flank, 30–60dte, momentum | 5 | +30.5 | −10.9 | −52.2 | 0.00 | **DEAD (too few trades)** |
| B modal 25bp fly | 135–400dte, long-dispersion | 10 | +7.8 | −2.2 | −12.2 | 0.00 | MARGINAL-maker-only* |
| C tail vertical | below, 60–135dte, sell | 5 | +3.5 | +1.0 | −1.5 | 0.00 | **DEAD (too few trades)** |
| E ICS residual | fade, 20d hold | 114–150 | +15.9/+46.2 | −98.1 | −212 | 0.00 | **MARGINAL-maker-only** |

*B's verdict does not survive its own autopsy: neighborhood 12/24 positive
(median +0.4bp) — an island — and the largest single trade is −133% of total
net. Selection, not signal.

## The three real findings

**1. The ICS residual genuinely converges, and costs eat it 3–7×.** Family E
is the only statistically populated row: fade gross +15.9bp over 114 trades
ex-turn (+0.14/trade), +46.2bp over 150 with turn quarters (+0.84/trade on
the turn subset — turn residuals converge hardest), momentum the exact
mirror (−15.9/−46.2), t on gross positive both ways. The 10:6 package round
trip (~1.0 spread-bp at half-ticks) is 3–7× the per-trade edge. This
reproduces the serff fair-value conclusion through a completely independent
pipeline — decomposed residual, listed settles, different code.

**2. The convergence mechanism is real; the strategy is not runnable at
EOD.** The placebo battery on family A: replacing the lattice tree with a
moment-matched Gaussian drops the best config from +49.5bp to +12.2bp;
feeding the tree a WRONG meeting calendar kills it entirely (best −1.2bp).
That is exactly the signature of genuine lattice information. But the
family's sign test fails (median fade −23.4, momentum −16.1 — both
directions lose across configs), its best rows hold 1–5 trades, and its
sole +49.5bp row is one momentum trade in the <30dte band. Same shape as
PR #375's 5-trade result, now established across 192 configs instead of 12:
the event-window edge is real for hours, not for EOD portfolios.

**3. The dispersion premium is not harvestable — in either direction.**
Family B's sign test: short-dispersion median −4.0bp, long-dispersion +0.4bp
— if anything the 16pp "flatness premium" from the triangle notebook is
FAIRLY priced insurance (owning the fly loses roughly its cost; selling the
wings earns nothing after the same cost). Family C agrees from the tail
side: selling the off-lattice tails nets +1bp at 1× and −1.5 at 2× on 5
entries. The static mispricing measured in section D/F of the triangle is
real as a *price* and absent as a *harvest* — the classic insurance-premium
resolution.

## Discipline notes

Every config ran both directions; DSR computed per family winner log with
the family's full trial count (all 0.00 — no family clears multiple
testing); the n≥10 verdict floor stopped a 1-trade +49.5bp "winner" from
headlining; the placebo battery was re-classified inside the placebo world
after an initial wiring bug let the real lattice leak into P1's flags
(caught because P1's best matched the real best bit-for-bit — too good to
be true is a bug signature). A latent AtomEngine NaN on degenerate
zero-jump meetings was found by the P2 run and fixed with a regression
test. The P2 tree recomputation was validated against the frozen panel
(median |Δp_tree| = 0.0000) before the shifted world was trusted.

## Family D (not run, by design)

The cross-expiry conditional signal measured fit_L1 ≈ 0.33–0.41 in the
triangle notebook — a third of the mass outside the model. Running configs
on a signal measured that weak inflates the trial count without adding a
testable thesis.

## Honest limits

EOD panels frozen at 2026-07-28; one rate cycle; family A's engine holds
one open trade per contract (no portfolio overlay); B/C packages unhedged
in delta (drift beta reported, not neutralized); E marks the package at
settle-to-settle spread changes, not intraday fills. None of these limits
flatter the strategies — every one of them, relaxed, adds costs or noise.

## What would change the verdicts

Intraday event-window execution for family A (the mechanism passes both
placebos — it is the only family whose SIGNAL is certified real); maker
fills on the ICS for family E (+0.14–0.84bp/trade gross is real, standing,
and currently un-collectable at taker); a second cycle of data for
everything else.
