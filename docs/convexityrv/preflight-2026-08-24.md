# CA-vs-fly block — preflight, 2026-08-24

Fresh-session preflight for the third block of convexity RV work: a comprehensive
backtest of the 3M SOFR futures convexity adjustment (outrights, packs, bundles)
against USD SOFR butterflies (spot and forward-starting), plus a live screener.
Every number below was measured on this machine today unless marked otherwise.

Worktree: `C:/Users/chris/clee/ARBS-cvx3`, branch `feat/convexity-rv3`, based on
`origin/main` at `e1eac8e8`. (`ARBS-cvx2` still exists and is parked on
`fix/swaption-nvol-test-seam`; `feat/convexity-rv2` and its deliverables are
already merged to main — PRs #476/#477/#478/#479/#482 — so this block starts
from a main that carries the repaired CA infrastructure.)

## 1. Green board

| check | result |
|---|---|
| convexity suite | **923 passed, 73 skipped, 0 failed**, 166.7s (`pytest tests -k convexity_rv`) |
| skip reasons | all 73 are "panel not built" — gitignored artifacts absent in a fresh worktree |
| CA kernel live | `IRSwapsTB.sfr_cvx_adj` 5 colours, 2026-07-01..08-14: 32/32 dates, **0 failures**, median CA monotone in rank (Whites 0.38 → Golds 9.01 bp) |
| outrights + bundles | `SFR8` and `BUNDLE2` labels price through the same path |
| flies, spot + forward | `2Y/5Y/10Y`, `1Yx2Y/1Yx5Y/1Yx10Y`, `1Y/2Y/3Y` all price via `tb.get_timeseries` (spot 2s5s10s −14.0bp, 1y-fwd −14.4bp on 2026-08-14) |
| intraday CA | `sfr_cvx_adj_intraday` reaches WHITES..GOLDS on warmed sessions with provenance columns; SILVERS correctly refused (needs depth 24) |

## 2. The full CA panel is built, and coverage is no longer the story

`notebooks/backtests/convexity_rv/_cavf_backfill_ca.py` priced **27 labels —
WHITES/REDS/GREENS/BLUES/GOLDS, SFR1..SFR20, BUNDLE1/BUNDLE2 — over
2021-01-04..2026-08-21 through the repaired TB path in 229s: 1,409 dates,
zero failures, zero missing cells.** The 2021–2023 deep-strip hole the
2026-08-20 preflight was still repairing is closed; the deferred-settle warm
plus the Barchart per-symbol history cache serve everything.

Artifact: `notebooks/data/convexity_rv/cavf_ca_panel.parquet` (gitignored,
regenerable; failure ledger `cavf_ca_failures.json` is empty).

Note the repo's `BUNDLE{b}` vocabulary is a 16-quarter window starting at rank
`1+4(b−1)` — **not** the CME bundle (front-anchored 8/12/16/20 contracts).
`BUNDLE{N}Y` labels (ranks 1..4N) will be added to the shared vocabulary with a
test before the backtest quotes anything called a bundle.

## 3. Signal-input data board

| series | verdict | measured window / note |
|---|---|---|
| CA daily, all structures | **GREEN** | §2 |
| fly legs, spot + fwd starts 0/1/2/3/**4**/5y | **building** | `_cavf_backfill_legs.py`, same 1,409 dates; 4y start added so a fly's forward start can sit at the Golds expiry (~4.25y) |
| CME-LCH CCP basis (USD SOFR, LCH−CME) | **GREEN, offline** | `ccp_basis_cache.basis_panel`: **2018-04-27..2026-08-14, 2,023 dates × 11 tenors, 100% non-null**; sign reference pinned (10y −2.0bp on 2026-08-10) |
| CFTC TFF positioning | **GREEN, refreshed today** | 20,190 rows, max report date **2026-08-18** (was 2026-05-12; +98 days); `dealer_net`/`lev_net`/`am_net` for SOFR3M via `build_positioning_panel`, release-lagged 3 bdays |
| whole-strip open interest | GREEN (weekly) | CFTC `Open_Interest_All`; per-contract OI remains survivorship-shaped — unusable pre-2025 |
| swap curve USD-SOFR-1D | GREEN | CurveStore EOD 2005-01..2026-08 (99.7% of bdays 2021-2026, per 08-20 preflight) |

**Curve MDP convention (user preference, 2026-08-24):** the main curve MDP for
timeseries, signal building, marking and backtesting is
`IRSwapsMDP(source="citivelo_excel_rl")`. Measured: bit-identical to the
`"CITIVELO_EXCEL"` spelling on the CA path (max |diff| 0.0 bp over a 3-date ×
2-colour probe — both spellings are members of `CITIVELO_EXCEL_RL_TOKENS`), so
panels built before the convention was pinned remain valid; all new code uses
the `citivelo_excel_rl` token. CME-LCH basis comes from gs_quant
(`ccp_basis_cache.basis_panel`, offline).
| **empirical CA (`CVX_ADJ_EMPIRICAL`, ERIS leg)** | **EXCLUDED** | `IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS")` fails to build a curve on 6/6 probe dates (2022..2026) — no usable history on this machine. The model CA (`CVX_ADJ`) is the only CA series in this block. |

## 4. What "do not trust the previous results" means, precisely

`docs/convexityrv/research/corpus2/repo-results-audit.md` classifies all 21
results docs. Only two are outright suspect on the matched-swap convention —
`strat2-sofr-convexity-vs-fly.md` and `strat2-fly-grid-engine.md`, both built on
the **annual-frequency** `strat2_panel.parquet` (the −3.9bp "clearing basis"
offset was the compounding gap; both superseded in-corpus). Everything else is
current with named caveats. The eight inheritance bans in that audit (trim
artifacts, correlation-only tie-outs, coverage-as-finding, unit seams, Golds
rank-17 gate, engine-certification scope, null bars at n_eff on both clocks)
are adopted wholesale for this block.

Baseline facts the fresh work must beat or explain:
* w2b (repaired panel, 2021-2026): gross Sharpe **0.130 < E[max SR|null] 0.177**
  at six trials — DEAD; the 2s5s10s fly removed 0.6% of variance.
* grid (1,890 cells, ranks ≤10, window ended 2023-12): winner deflated-Sharpe
  p 0.924, fails; forward-start-matched-fly hypothesis **rejected on ranks ≤10
  only** — the deep ranks were not reachable then and are now. Re-testing it at
  Blues/Golds depth is a headline question of this block.
* Citi's positioning mechanism reproduces on SOFR **in Blues only**
  (slope +5.28e-07, t 2.59, R² 0.124, monthly, HAC).

## 5. New corpus read (88 unique documents)

Extraction reports committed under `docs/convexityrv/research/corpus2/`
(g01..g11 + repo digests + synthesis). Items that shape this block:

* **Citi fair-value regressions, verbatim**: Blues CA ≈ `10.2 + 21.4·(−0.70·2y +
  5y − 0.46·10y)` (swap 2s5s10s); Greens fair value ≈ `−3.53·ED5 + 4.17·ED9`
  (futures steepener, −1/1.18 DV01). No R² published anywhere — must be
  re-established in-house.
* **Four more Citi tickets** with entry/exit marks (Blues 2017 +$500k net incl.
  costs; Greens 2017 target +$450k/stop −$225k, CA-leg MTM $285k exact; Blues
  2018; Blues 2021 EDM4-H5 at 7.9bp, target 4bp / stop 3bp) and two full 17-row
  ED screens (5/12/17, 1/5/18) as additional known answers.
* **CME 2025 worked chain** (8 SR3 prices → 3.3304% 2y IMM coupon → 779-lot
  hedge ladder → ±10/25/50/100bp convexity P&L table → $46,161 portfolio-margined
  IM): a complete tie-out for any bundle-vs-swap helper; cost anchors 0.5bp
  two-way swap, 0.25bp bundle tick, 0.1875bp bundle give-up.
* **CCP basis**: regime history <0.1bp (2014) → 2bp blow-out (May-2015) → 3.4bp
  30y (2017, fully explained as two-sided MVA) → ~0.85bp and vol-insensitive
  (2025), **sign flip below zero in 2024**; arb threshold ~3.9–4bp (two
  independent sources); structural breaks 2015-05, 2020-10 (SOFR discounting),
  2024-09 (FMX SOFR futures at LCH). Treat as a slow conditioning covariate,
  never a venue correction to the CA (the Fig-58 tie-out already passes at
  ~1bp median without one).
* **Positioning**: JPM measured the CA-richness-vs-dealer-positioning beta
  **peaking at 2–3y forwards (Greens/Blues)**; Citi's mechanism is the same
  trade from the short side. Aikin: no market-level OI→price link — stay with
  TFF dealer nets.
* pm_bbgchat and the long-end vol-lab docs are the previous blocks' material;
  nothing new binds this block.

## 6. Verdict and build order

All five requested variation families are feasible on measured data:

1. **technical** — mean-reversion / pairs on `CA_s − β·fly_f` (and CA-only,
   fly-only controls), all structures × spot & forward flies;
2. **fair-value regression** — Citi's `CA = α + β·fly` residual, rolling,
   t−1-lagged, incl. the exact published Blues spec as a pinned variant;
3. **positioning-conditioned** — TFF dealer/lev/am nets, release-lagged;
4. **CCP-basis-conditioned** — LCH−CME level/changes as gate and covariate;
5. **carry/RAC** — the screen's own `3m roll` + implied/realised columns as a
   risk-adjusted timing overlay.

Order: leg panel → pre-registered grid spec (committed BEFORE scoring) →
enrichment panel → panel-space grid simulation with controls and null bars →
engine certification of finalists through `QueryDrivenBacktest` (per-leg costs)
→ configurable backtest notebook → live screener notebook (intraday CA path) →
tests incl. mutation checks → results doc.
