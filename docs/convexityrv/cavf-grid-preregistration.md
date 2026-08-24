# CA-vs-fly — pre-registered grid (frozen 2026-08-24, BEFORE any scoring)

This file freezes the search space for the fresh CA-vs-fly backtest. Anything
scored later that is not declared here expands the trial count and must be
added to this file with a dated note — the null bar moves with it. Corpus-2
synthesis findings arriving after this freeze may only ADD declared cells the
same way.

## Window and panels

* Window **2021-01-04 .. 2026-08-21** (1,409 panel dates). Signals need a 252-day
  warm-up, so first entries land ~2022-01; the flat warm-up year is reported,
  not dropped.
* CA panel: `cavf_ca_panel.parquet` — TB path (`sfr_cvx_adj`), Q/Q matched swap,
  27 labels, zero failures.
* Fly legs: `cavf_fly_legs.parquet` — par rates + 3M carry for spot tenors
  {1,2,3,5,7,10,20,30}y at forward starts {0,1,2,3,4,5}y.
* Enrichment: CFTC TFF (release-lagged 3bd), CCP basis (lagged 1bd),
  whole-strip OI (lagged with TFF). All signals use **t−1 information; trades
  execute on t marks**.

**Execution-convention amendment (2026-08-24, after the first grid pass and
before any verdict):** the first pass filled at the SAME settle the signal was
computed from, and its results carried the signature of mark-noise harvesting —
100% hit rates on 38–72 episodes, 3–5-day holds, per-episode P&L an order of
magnitude above the CA level itself. The CA mark is a composite of a
17:00-nearest-bar futures mark and a separately-timed swap curve (measured
timing noise 0.89–2.55bp/pack-day) plus occasional stale deferred settles; a
z-rule that enters at that mark buys the noise and is filled at a price nobody
can trade. The primary convention is therefore **fill at t+1's mark on a
signal observed at t** (entry, exit and cost all at t+1); the same-day-fill
variant is retained ONLY as a reported diagnostic whose gap to the t+1 numbers
measures the mark-noise harvest. This amendment changes no declared cell.

**Roll-splice amendment (2026-08-24, same session, before any verdict):** every
CA structure label is a CONSTANT-RANK series — at each quarterly IMM roll the
label switches contracts, so a day-over-day difference across the roll is a
contract-switching jump, not P&L (22 of 33 SR3 rolls are FOMC decision dates,
so the jump is also systematically signed). The second grid pass entered
positions ON those jumps and booked them as reversion. Both the signal and the
panel P&L therefore use the **roll-spliced** series: the level change on a
front-IMM roll date is removed and the level backward-adjusted, exactly the
continuous-futures convention; the raw CM level remains the screener's display
quantity. Panel-side rolls execute at zero cost (flagged as optimistic — an
engine-certified finalist holds real contracts across the roll and prices it).
This amendment changes no declared cell.

## Structure universe (CA side) — 14 tradeable

| group | labels | T1_mean (yrs) | matched fwd start |
|---|---|---|---|
| packs | WHITES, REDS, GREENS, BLUES, GOLDS | 0.75 / 1.75 / 2.75 / 3.75 / 4.75 | 1 / 2 / 3 / 4 / 5 |
| bundles (CME, front-anchored) | BUNDLE2Y, BUNDLE3Y, BUNDLE4Y, BUNDLE5Y | 1.25 / 1.75 / 2.25 / 2.75 | 1 / 2 / 2 / 3 |
| outrights | SFR4, SFR8, SFR12, SFR16, SFR20 | 1 / 2 / 3 / 4 / 5 | 1 / 2 / 3 / 4 / 5 |

`T1_mean` = average years to IMM expiry of member contracts ≈ (rank+2)·0.25 for
packs, k·0.25 for outright rank k. The remaining outright ranks and the repo's
16-quarter `BUNDLE1/2` windows stay in the screener but are not scored cells.

## Fly universe (hedge/pair side)

Shapes (belly-weighted [w_front, 1, w_back] = 50/50 DV01-neutral wings unless a
regression weighting is named): **1s2s3s, 2s3s5s, 2s5s10s**. Starts per
structure: **spot (0)** and the **matched forward start** from the table above.
So 6 flies per structure. Rationale: 1s2s3s carried the only broad R² plateau
(0.42–0.55, ranks 2–8) in the superseded grid; 2s5s10s is Citi's published
hedge; 2s3s5s is the shape nearest pack expiries. The other six shapes from
`strat2_fly_universe.FLY_SHAPES` remain available to the screener only.

## Signal families and scored cells

All z-scores: rolling 252-day mean/sd computed through t−1, applied at t.
β conventions (clarified 2026-08-24, before any scoring — without this the two
families collapse into one statistic): **family A (pairs)** estimates β from
rolling 252-day OLS of ΔCA on Δfly (daily changes — hedge-ratio semantics) and
z-scores the frozen-β spread `CA − β·fly` against its own rolling mean/sd;
**family B (fair value)** fits CA on fly in LEVELS with an intercept and
z-scores the regression residual against its rolling sd. Both β's are gated to
0.01 ≤ |β| ≤ 1.0 bp-per-bp (≡ 1..100 in Citi's bp-per-percent units); a day
outside the gate cannot open a position (recorded).
Two-sided entries (long AND short the spread), unlike Citi's short-only book —
declared here because it doubles the opportunity set.

| family | signal | entry / exit | cells |
|---|---|---|---|
| **A. pairs MR** | z of (CA − β·fly) residual | primary z_in 2.0 / z_out 0.5, max hold 63bd; sensitivity z_in 1.5 | 14×6×2 = **168** |
| A-control CA-only | z of CA level | same two threshold sets | 14×2 = **28** |
| A-control fly-only | z of fly level | same | 18 distinct flies ×2 = **36** |
| **B. fair-value residual** | z of (CA − α̂ − β̂·fly), rolling fit | z_in 2.0 & 1.5 / z_out 0.5 | 14×6×2 = **168** |
| B-pinned Citi-Blues | fixed α=10.2, β=21.4, weights −0.70/1/−0.46 (2017 print), BLUES vs spot 2s5s10s, residual z | z_in 2.0 / z_out 0.5 | **1** |
| **C. positioning overlay** | family-A/B primary books on the 5 packs × spot 2s5s10s, entry additionally requires dealer_net z ≥ +1 for short-CA (mechanism side) and ≤ −1 for long-CA | — | 10 |
| **D. CCP-basis overlay** | same books, entry requires |Δ20d basis_5y| ≥ 0.25bp aligned with trade sign | — | 10 |
| **E. carry/RAC overlay** | same books, short-CA entries additionally require 3m roll > 0 (the screen's own carry column) | — | 10 |
| **B-jpm** (added 2026-08-24, after the corpus synthesis landed and BEFORE any scoring) | JPM's Apr-2021 beta-stability recipe adapted to the pair: family-B levels fit, entry requires rolling R² ≥ 0.60 AND |z| ≥ 1.5; exit when the residual crosses zero (not a z band), stop at |z| ≥ 3.5, max hold 21bd | 14×6 = **84** |
| **total declared** | | | **515** |

Overlay families C–E are conditioning overlays on declared base books, never
standalone signals; pre-registered expectation is weak (positioning reproduces
in Blues only; the basis mechanism is IM non-nettability, not the level).

**Headline measurement (not a scored cell):** the forward-start-matched-fly
hypothesis — hedge R² by (structure T1 × fly forward start) — re-measured at
Blues/Golds depth for the first time. Prior rejection (slope −0.018 vs +1.0)
covered ranks ≤10 / T1 ≤ 2.5y only.

## Sizing and costs

* CA leg $100k DV01 (packs/bundles: equal contracts per leg; matched Q/Q swap
  opposite); fly belly DV01 = β·CA_DV01/100 for β-sized books (Citi's rule),
  CA_DV01 for the 50/50 controls with declared weighting.
* Costs **per leg, round trip, on leg DV01**, charged at unwind: futures legs
  0.25bp, swap leg 0.5bp, each fly leg 0.5bp; swept ×{0, 0.5, 1, 2}; break-even
  quoted on gross DV01 traded. (Anchors: CME 0.5bp two-way 2y IMM swap quote,
  0.25bp bundle tick, 0.1875bp bundle give-up; the incumbent w2b convention —
  one fee per epoch — is reported alongside for comparability.)

## Statistics, controls, certification

* n_eff per cell from span × 252 / mean hold; **E[max SR | null] at 431 trials
  on both clocks** (per-hold and annualised), deflated Sharpe for any winner.
* Placebos: signal lagged +20bd must kill the edge; sign-flip resampling (not
  row permutation) for Sharpe p-values.
* Negative controls that must fail: annual-frequency matched swap vs Fig 58;
  reversed roll identity.
* Finalists (top ≤3 by DSR, plus the pinned Citi-Blues book) run end-to-end
  through `QueryDrivenBacktest` — 4 futures legs + matched swap + fly as
  separate queries, `assert_ran`, CA-leg daily-change corr ≥ 0.99 against the
  panel and full-package agreement reported honestly.
