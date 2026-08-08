# Citi Velocity RV loop — findings

**VERDICT (session 1, complete): NOTHING ALIVE — every registered hypothesis graded and
killed, three families killed at gate, on validated 20-year multi-currency data with a
measured cost line, and the adversarial checker killed the maker's last positive claim.
H13 grail-conditional (17 arms, 3 currencies): DEAD — median +0.0bp, DSR 0.000 everywhere;
its placebo-certified wording was withdrawn by the rival check (raw spread-z reproduces 137%
of the ex-carry). H16 z-fade: dead at gate. H16b sandwich basis: DEAD — median −1.35bp,
steamroller confirmed. H14-graded (Peter's manufactured package): the "+9.9bp at 1×" headline
was a CARRY DOUBLE-COUNT found by the checker (V-SV-14G-KILL) — corrected, the fly's net
contribution is **−22.2bp full-sample at 1×** (negative at every multiplier), +14.1bp
post-2017; what survives is the belly-received solve, genuine risk-reduction, and the
roll-based gate counterfactuals. F1 and F2: dead at gate. Twelve-of-twelve one more time:
every defect found this session flattered the maker, and the maker≠checker machinery caught
them. The loop continues per L-0029; the machine, the ledger, the measured costs, and one
repo-wide pricing fix are the session's durable output.**

**Predecessors:** `2026-08-08-citivelo-rv-loop-design.md` (+ ledger
`docs/superpowers/ledgers/2026-08-08-citivelo-rv-loop-ledger.jsonl` — the row-level record),
`docs/superpowers/plans/2026-08-04-strikeless-vol.md` (PR #392, continued here).

This skeleton is committed before results per the addendum ordering rule (a findings doc
written before the trial count is final publishes a count later work invalidates). Sections
fill in grading order; the DSR trial count is quoted only in the final revision.

## What went right

- **The gates killed cheaply.** Four families/expressions died before any backtest could
  flatter them: H16 z-fade (oracle 0.5–1.8× a *measured* boat), F1 surface residual (tradeable
  cells a coin flip; the "winners" live in the dealer-extrapolated corner — a marking-model
  mirage caught at gate, not post-hoc), F2 gamma IV/RV (no conditioning signal; unconditional
  premium mean-zero with −95-vol-bp tails), JPY grail arms (0–1.1% occupancy over 20 years).
- **The checker discipline worked twice on the maker's own claims.** A calibration run killed
  a fabricated memo on the planted defect *and* on arithmetic it found unprompted (L-0025);
  then the rival check (L-0030) withdrew the maker's strongest surviving claim — the "grail
  state times convexity harvest" wording — by showing occupancy-matched raw-spread-z states
  reproduce a median 137% of the ex-carry at 0–52% day overlap. Every defect that mattered
  favoured the hypothesis, again; adversarial specificity found them, again.
- **A measured cost line replaced an assumed one** (CM-1: 643 days of SDR swaption prints vs
  the cube mid; ATM half-spread 0.17–0.71 annual bp by expiry, upper bound; two SDR
  convention discoveries: forward premiums, UPI package-total duplication).
- **A live repo-wide pricing bug fixed**: the QDB direction-blind signed-bpv seam (buy ≡ sell
  since at least 2026-07-30), root-caused to one line, pinned by tests, mirror verified.
- **The 20-year multi-currency data spine validated**: 2019/2023 published-table tie-outs
  (spreads to ~1bp; Γ matches Citi's, roll convention ~2× open), GS-overlap basis stable, the
  holiday-ghost defect found and filtered before grading.
- **The PM's construction measured, then corrected by the checker**: the roll-based gate
  numbers stand (occupancy 18.6%→39.9%, 82% median-bleed coverage, belly received on 948/950
  days, risk-reducing) — but the graded "+9.9bp net at 1×" was a carry double-count
  (V-SV-14G-KILL); corrected, the fly is net −22.2bp full-sample and +14.1bp post-2017, the
  gamma-retention figure is retracted as uncommitted, and the maintenance line was itself
  understated by a dedup nondeterminism. The strongest surviving statement is direction-only:
  the fly's post-2017 carry contribution is real and roughly half what the maker first
  published.

## Machine (built 2026-08-08, session 1)

- Worktree `ARBS-rv`, branch `feat/citivelo-rv-loop` off main 33fe6981; baseline fast gate
  4159/0 (pure main); sv merge Task 29 complete, sv suite 544/0.
- Ledger, checker charter, reference corpus committed; three reading fan-outs (10 agents)
  distilled the cost line + framework corpus.
- **Repo fix shipped:** the QDB direction-blind signed-bpv seam (kink-v2 §6) — root-caused to
  `resolve_pricable` double-signing signed rateslib notionals; fixed, pinned, mirror verified
  live. See ledger L-0012.
- Data: banked par grids 2005+ × 5 ccy to 50Y; EOD curve warms extended (USD full 2005–2026;
  JPY 2006+; GBP by concurrent session; EUR/CAD in flight); cube 2,699 days (ATM 2015-10+,
  full smile 2020-01-24+).

## Gates (run FIRST, before any graded number)

| gate | spec | outcome |
|---|---|---|
| (a) 2019-05-08 Figure-7 tie-out | L-0009/L-0017 | **PASS** — spreads to −0.8bp median, Spearman BE 0.958, carry sign 7/8 |
| (b) 2023-06-08 steepener-carry tie-out | L-0009/L-0017/L-0020 | **FAIL on tolerance → root-caused** — spread exact (−51.5); Γ validated; roll convention ~2× (unresolved, sign-invariant internally) |
| (c) GS-vs-Citi basis stability 2017–2026 | L-0009/L-0017 | **PASS** — spread basis median −0.2bp, rolling-median range 4.4bp |
| Data integrity | L-0018 | holiday-ghost curves found (990 dup rows) → filter in all engines, panels rebuilt |
| H15 aging | L-0013 | **NOT falsified** — pure-aging Γ retention 1.01–1.06× to 5y (curve-held-fixed) |
| H14 carry-engine gate | L-0024→V-SV-14/V-SV-14G-KILL | gate numbers stand; graded headline KILLED (carry double-count) — corrected fly net −22.2bp at 1× full-sample, +14.1bp post-2017 |
| H13 occupancy | L-0016 (JPY), USD detector | USD pond exists (10–50% by pair); **JPY pure-flattener arm DEAD at gate (0–1.1%)** |
| H16 z-fade basis pond | L-0019 | **THIN** (0.8–1.8× boat) — expected DEAD at grading |
| H16b sandwich pond | L-0023→V-SV-16B | gate OPEN → graded **DEAD** (the wedge proxy did not translate) |
| CM-1 measured swaption cost line | L-0022 | **DONE** — 0.17–0.71 annual bp ATM half-spread by expiry (upper bound), checker 3/3 |
| F1 surface residual | L-0028 | **DEAD AT GATE** — tradeable cells coin-flip; "winners" are the extrapolated corner |
| F2 gamma IV/RV | L-0032 | **DEAD AT GATE** — no conditioning signal; unconditional mean-zero with −95bp tails |
| H14G mechanism columns | V-SV-14G-KILL | **KILLED by the checker** — carry double-count; corrected −22.2bp at 1×; Γ-retention figure retracted (uncommitted); belly-received + risk-reduction survive |
| H13 rival check | L-0030 | spread-z reproduces 137% of grail ex-carry → mechanism wording withdrawn |
| Checker calibration | L-0025 | **PASSED** — planted defect + unprompted fabrication both killed |
| Merged-tree fast gate | L-0033 | **4,766 / 0 failed** (baseline 4,159/0) |

## Graded hypotheses (pre-registered in the ledger before their numbers)

- **H-SV-13** grail-conditional entries — **DEAD** (V-SV-13F: 17/17 arms, median +0.0bp,
  DSR 0.000; mechanism wording withdrawn per L-0030)
- **H-SV-14 / H-SV-14G** manufactured package — **DEAD; graded headline KILLED by the
  checker** (V-SV-14G-KILL: the fly ledger double-counted carry; corrected net −22.2bp at 1×
  full-sample, +14.1bp post-2017; maintenance understated by a dedup nondeterminism;
  Γ-retention retracted as uncommitted; both registrations closed with terminal rows, the
  dropped 2-7-29/5:1 reports stated in V-SV-14)
- **H-SV-16** z-fade — **DEAD AT GATE** (V-SV-16, clean panel, measured boat; never backtested)
- **H-SV-16B** sandwich basis — **DEAD** (V-SV-16B: median −1.35bp, steamroller −$0.7–1.2M)
- **F-ING** EUR forward-strip residual screen — built + gated (L-0015); graded run BLOCKED on
  the fair-value-construction fidelity gap (our PC1 residual ≠ ING's; their 2020-01-15 example
  does not reproduce) — parked, not silently rescoped

## Deaths

- **H13 grail-conditional entries (V-SV-13, 17 pre-registered arms).** DEAD at the registered
  spec. The number that killed it: **DSR 0.000 at n_trials = 3,905** on every arm, median
  across arms ≈ 0. Best arm USD 15y5y/20y10y: +106.7bp net@1× over 116 episodes (+0.92/trade,
  NW t 1.23). GBP arms −816/−517bp: the state chatters at the carry-zero boundary (~3-day
  episodes), so in-state carry ≈ 0 *by construction* while entry/exit churn burns 1.5bp per
  crossing. JPY arms gate-dead (occupancy 0–1.1% over 20 years). What survives: the state
  genuinely times convexity harvest (ex-carry placebo p ≤ 0.014 on 7 USD arms; no post-exit
  steamroller), and always-on flattener profits are first-half (2005–2016) concentrated —
  which *reconciles* the +157…+296bp 21-year controls with the sv-on-GS all-DEAD verdict on
  its 2017+ sample. Regime, not contradiction.
- **H16b sandwich basis trade (V-SV-16B, 4 pre-registered combos).** DEAD. The number:
  **median −1.35bp across combos**, best +23.1bp/19 trades at placebo p 0.075, and worst
  episodes −$0.7–1.2M on ~$30k-vega books. The gate's 15–35× wedge pond was a state-margin
  proxy; premium-marked collection is a fraction of it, and the sandwich exits *with* the vol
  spike (63-day realized lags), hitting the short straddle first — the famb insurance lesson,
  reproduced in swaption space.
- **H16 z-fade (L-0019).** Killed at its oracle gate: pond/boat 0.8–1.8× with harvest
  historically 10–30% of oracle. Never backtested — the gate said stop.

## DSR accounting

Convention: each verdict was graded at the family count current at its grading time
(V-SV-13 at 3,905; V-SV-16B at 3,909; V-SV-14G at 3,910); the final session-1 count is
**N_sv 3,888 + 22 loop trials = 3,910**. Recomputing H13 at the final count changes nothing
(DSR 0.000 either way). Gate-killed families consumed no trials (no selection occurred); the
H16 registration's 4 budgeted trials were released unconsumed.

## The structural finding (L-0029)

At N ≈ 3,900 inherited trials, DSR > 0.5 is out of reach for any carry-class book — Citi's own
published Sharpes for this family are 0.05–0.35, our best measured 0.28. The bar is the bar;
what it implies is family selection: the loop's remaining realistic ALIVE candidates need many
independent periods with high per-period Sharpe (intraday minute-curve constructions,
cross-sectional many-bet books, event windows), not more EOD carry variants.

## Current state worth knowing (2026-08-07/08 close)

- EUR 15y5y/20y10y: grail occupancy **76.9%** over 21y; today BE/RV **0.61** at carry
  −0.7bp/y — the closest live analogue anywhere to Citi's 2019 USD entry (BE/RV 0.42).
- USD: all pairs carry-negative today; BE/RV 0.96–1.72; 20s30s spot inverted.
- JPY 10y10y/20y10y at −3.7bp, flattest in a year — the PM's Japan-flattener thesis is a
  multi-year expectations-wash argument, not a current BE/RV entry state (both recorded).
