# Family B — Findings

**Date:** 2026-08-04
**Branch:** `feat/family-b-dispersion` (stacked on `feat/linvol-backtest-grid`)
**Design:** `2026-08-04-family-b-dispersion-design.md`
**Executed notebooks:** `famb_carry.ipynb`, `famb_meanrev.ipynb`
**Engine:** `famb_common.py` + 11 synthetic tests

## The harness defect that made the grid's family B meaningless

The lab quotes are OTM-only. Any structure straddling the money silently
lost legs, so the grid's episodic flys entered 1–3 times per config —
starvation by construction, not by market. The parity-completed surface
(`C = P + DF·(F−K)`, ~0.03bp on settle forwards) un-starves every modal
package; the strangle is built put-low/call-high because an all-call
synthesis would smuggle a forward leg into the "tail" book.

## B1 — the carry books (2024-07 → 2026-07, ranks Q1–Q3, daily marks)

| book (long) | best rank net@1x | worst | read |
|---|---:|---:|---|
| FLY25 | −8.8 | −10.7 | modal fly priced FAIR — neither side clears costs |
| FLY50 | +8.5 | −3.8 | slight long edge, NW t ≤ 0.3 — noise |
| DFLY | −12.7 | −17.0 | count-skew fairly priced; 8-contract costs dominate |
| STRG50 short | **+25.0 / +37.9 / +11.6** | — | NW |t| up to 2.36 |
| STRG75 short | +15.5 / +18.5 / +14.5 | — | same shape, smaller |

**Selling the off-lattice tails cleared 1× costs in every one of six
strangle cells** — the first consistently-signed, cost-cleared result in
this family. Attribution: shorts collect ordinary-day carry (+26/+48/+25
by rank for STRG50) and give a fraction back in decision windows; forward
betas ≤ 0.14bp/bp (books are clean of drift).

**The regime caveat is absolute**: every strangle in the terminal ledger
settled at exactly 0.00 against ~0.5bp final marks. The insurance was
never once tested in this sample.

## B3 — Sep-2024: the "wild" meeting was not an insurance event

Eve-of-decision lattice: jump −44.6bp, support (−2,−1), P(−50) ≈ 0.78.
The 50bp cut was ON the two-point support — a priced coin flip. The modern
sample therefore contains ZERO off-lattice terminal outcomes, which is
exactly why tail-selling looks clean. What tests the short is the 2022
regime: fast repricings (June-2022 style) can move settles beyond strikes
fixed at an earlier roll even when the eve-of-decision support has caught
up. The backfill (below) is the referee.

## B4 — the calendar is dead on arrival

Long Q3 fly / short Q1 fly: +7.7bp over 408 days, NW t 0.46, **beta to the
outright Q1 fly −0.93** — the pre-declared kill criterion (|β| > 0.8)
fires. The frontier-slope "compression carry" is the outright fly in
disguise; nothing distinct to trade.

## The mean-reversion answer: this is a TRADE, not a position

Richness (market − tree-fair, strict smeared ZQ tree via the MeetingProb
pricer), pooled AR(1) within holdings:

| book | rank | mean rich bp | half-life (sessions) |
|---|---:|---:|---:|
| STRG50 | 1 | +1.9 | 7.3 |
| STRG50 | 2 | +9.1 | 17.9 |
| STRG50 | 3 | +19.2 | 18.4 |
| FLY25 | 1–3 | −0.5…−2.4 | 11–14 |
| DFLY | 1–3 | ~0 | 9–11 |

Every half-life is far under the 40-session kill: **terminal-only is
refuted**. The richness LEVEL by rank reproduces the feasibility frontier
in premium bp (the standing tail premium compresses toward expiry); the
fly's slight cheapness confirms the mode-deficit; the skew (DFLY) is fair.

The intra-quarter rule (fade |rich| > thr, exit at half-entry richness or
15 sessions, lag-1, never holding to expiry): **STRG50 Q2 thr 4bp: 30
trades, 63% hit, +48.9bp net@1x, ~13-session holds**; Q3 +18.8, Q1
+6…+16; momentum properly negative; fly/dfly richness fades ≈ nothing (the
action is in the wings, not the body). 54 configs run, overlapping trades
across ranks share dates — inference is optimistic and flagged as such.

## B2 — the history extension (running)

Barchart serves expired chains to 2022 (verified: SFRM23, SFRZ22, SFRZ23
chains with live premiums), but warm per-day fetches cost ~12.6s → ~1h per
symbol. The backfill (`famb_backfill_quotes.py`, 12 symbols, gap-first
order: SFRZ24/SFRU24 → 2022) checkpoints per symbol and `load_quotes`
consumes parts incrementally — re-executing the two notebooks after it
lands extends every table into the hiking cycle without code changes. The
tail-selling verdict is provisional until then.

## The parameter grid and full statistics (second pass, sample now 2023-08→2026-07)

With SFRU24/SFRZ24 backfilled (books extend to 2023-08), full carry-book
statistics @1x, both signs — the best cells:

| book (short) | rank | total bp | Sharpe | NW t | maxDD | worst day | skew |
|---|---:|---:|---:|---:|---:|---:|---:|
| STRG50 | 1 | +35.5 | 1.15 | 2.05 | −13.7 | −10.5 | −1.86 |
| STRG75 | 1 | +22.2 | **1.17** | **2.12** | **−7.8** | −5.5 | −0.19 |
| STRG50 | 2 | +8.7 | 0.11 | 0.18 | −65.0 | −18.0 | −1.49 |
| FLY25 | 1 | +18.0 | 0.63 | 0.97 | −13.2 | −3.5 | +1.01 |

The extended sample concentrates the carry in **rank-1 tail shorts** and
dilutes Q2/Q3 (their worst days −18/−21bp show why). Every long book is
negative. The negative skew on the shorts is the insurance signature,
priced in plain sight.

**The intra-quarter grid** (pre-declared 720 configs: 5 books × 3 ranks ×
thr {2,3,4,6} × exit {0.25,0.5} × hold {5,10,15} × both directions):
every top-12 row is a STRG fade; winner STRG50 Q2 thr4/exit0.25/hold15 —
35 trades, 63% hit, **+37.5bp net@1×, +20.0 @2×**, per-trade t 1.07;
daily-series stats: Sharpe 0.58, NW t 1.02, maxDD −36.4, skew −1.08.
Neighborhood **SUPPORTED** (15/24 positive, median +12.7); halves
consistent (+14.0 / +23.5); fade beats momentum family-wide (−16.8 vs
−41.6 medians). The cleanest single cell: STRG50 Q1 thr3 — 11 trades, 91%
hit, +29.2/+23.8, t 2.57.

**But the house discipline says: SELECTION-ARTIFACT.** DSR = 0.000 at 720
trials and the median config is −26.3bp — a wide search found a
consistent-looking corner, and the taxonomy correctly refuses to certify
it. What separates this from noise-mining is the mechanism evidence
(half-lives, frontier-consistent richness levels, mirrored signs,
neighborhood, halves) — the honest status is: *mechanism-supported,
search-uncertified*. Certification requires out-of-regime confirmation
(the 2022 backfill, still running) or a pre-registered single config run
forward, not more search.

## Verdicts (house taxonomy, this sample)

- Long dispersion (fly, dfly): **DEAD** — fairly priced, costs decide.
- Frontier calendar: **DEAD** (redundant with the outright).
- Short tails as passive carry: cost-cleared, sign-consistent, but
  **untested insurance** — WATCH pending the 2022 extension; not ALIVE.
- Intra-quarter richness fade (STRG): cost-cleared with a measured
  7–18-session reversion mechanism, neighborhood- and halves-supported —
  but **SELECTION-ARTIFACT** at the full 720-trial count (DSR 0.000,
  median config −26.3). Mechanism-supported, search-uncertified: the next
  test is the 2022 regime or a pre-registered forward run, not more grid.
