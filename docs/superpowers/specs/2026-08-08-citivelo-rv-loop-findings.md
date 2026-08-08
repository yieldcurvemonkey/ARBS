# Citi Velocity RV loop — findings

**VERDICT: _pending_ — no graded family has completed its gauntlet yet. Nothing here is a
result until the verdict line above changes and quotes its number.**

**Predecessors:** `2026-08-08-citivelo-rv-loop-design.md` (+ ledger
`docs/superpowers/ledgers/2026-08-08-citivelo-rv-loop-ledger.jsonl` — the row-level record),
`docs/superpowers/plans/2026-08-04-strikeless-vol.md` (PR #392, continued here).

This skeleton is committed before results per the addendum ordering rule (a findings doc
written before the trial count is final publishes a count later work invalidates). Sections
fill in grading order; the DSR trial count is quoted only in the final revision.

## What went right

_pending_

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
| H14 carry-engine gate | L-0024 | **OPEN** — occupancy 18.6%→39.9% (2.1×) with the fly; covers 82% of median bleed; PCA-metric risk 0.19 residual |
| H13 occupancy | L-0016 (JPY), USD detector | USD pond exists (10–50% by pair); **JPY pure-flattener arm DEAD at gate (0–1.1%)** |
| H16 z-fade basis pond | L-0019 | **THIN** (0.8–1.8× boat) — expected DEAD at grading |
| H16b sandwich pond | L-0023 | **OPEN** — state 42–75% of days at liquid loci, wedge×episode ≫ boat (proxy) |
| CM-1 measured swaption cost line | L-0022 | **DONE** — 0.17–0.71 annual bp ATM half-spread by expiry (upper bound), checker 3/3 |

## Graded hypotheses (pre-registered in the ledger before their numbers)

- **H-SV-13** grail-conditional entries — _pending_
- **H-SV-14** manufactured package (four ledgers, per-leg costs) — _pending_
- **H-SV-16** strike-ful basis trade — _pending_
- **F-ING** EUR forward-strip residual screen — _pending_

## Deaths

_none recorded yet — a death gets its number and its ledger row here_

## DSR accounting

Quoted only in the final revision. SV family inherits N_sv = 3,888 (PR #392); loop-wide N per
ledger `trials_total`.
