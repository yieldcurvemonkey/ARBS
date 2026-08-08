# Citi Velocity swap-curve / swaption RV loop — design

**Predecessors:** `2026-07-29-sfr-fly-meanrev-findings.md`, `2026-07-29-sfr-rv-lab-findings.md`,
`2026-07-30-sfr-kink-fade-v2-findings.md`, `2026-07-30-zq-kink-fade-findings.md`,
`2026-08-03-linvol-backtest-grid-findings.md`, `2026-08-04-outcome-map-rv-findings.md`,
`2026-08-04-volvol-calendar-hedge-findings.md`, `2026-08-04-family-b-dispersion-findings.md`,
`2026-08-07-sr3-mbo-explorer-findings.md` — nine graded programs, ~1,700 configs, **0 ALIVE**,
all on listed STIR futures/options where the cost line is a 0.5 bp tick lattice.

**Mandate** (spec `~/.claude/specs/2026-08-08-citivelo-rv-loop-prompt.md`): run a hypothesis
loop over the newly warmed Citi Velocity data — `SwaptionCubeStore` asset
`USD-SWAPTIONVOL-CITIVELOEXCEL` and the `<curve>-CITIVELOEXCEL` CurveStore assets — until a
candidate passes the house bar *and* an independent adversarial checker. The bar never moves;
the search space expands. A fabricated ALIVE is the only unrecoverable failure.

## The bar (unchanged from the spec, §5)

ALIVE requires **all** of: (1) oracle/pond gate run FIRST and passed; (2) positive net at taker
on a written-down, sourced cost model; (3) DSR probability > 0.5 at the **program-wide** trial
count; (4) non-negative median config; (5) ≥10 trades, not one episode; (6) scale-matched
placebo battery; (7) sign test both directions; (8) linear-shadow test; (9) NW t +
non-overlapping Sharpe alongside any headline; (10) no t-stats on net series with near-constant
cost; (11) hedge ratios at the trade horizon; (12) marked on what executes, lag-1 fills;
(13) checker verified against a planted defect; (14) cold reproduction from committed code.
Verdict function: `RVUtils/SFRRVLab/stats.py::verdict`.

## The ledger

`docs/superpowers/ledgers/2026-08-08-citivelo-rv-loop-ledger.jsonl` — append-only JSONL,
git-tracked, one JSON object per line. Never rewritten; corrections are new rows with
`"supersedes": "<row id>"`. Row kinds: `hypothesis` (pre-registered spec, BEFORE any backtest
number exists), `gate` (oracle/pond result), `verdict` (measured numbers + status), `note`,
`parked`. Every row carries `trials_delta` and cumulative `trials_total`.

**Trial-counting rule.** One program-wide counter `N`, never reset, shared across all families
in this loop. Every configuration evaluated anywhere in the loop increments it — including
manual probes and oracle-gate variants where a parameter choice could have influenced what was
pursued. Pure data description (coverage counts, unit checks) does not. The nine dead programs'
~1,700 trials are prior programs and do NOT seed `N` (kink-v2 precedent: each program counts
its own sweep), but this loop counts everything it itself touches. DSR is always computed at
the ledger's current `trials_total`, via `BT/signals/deflated_sharpe.py` (per-period Sharpes,
never annualised inside).

## Marking policy (fixed now, before any result exists)

- **Screening** may mark in vol-points × vega (model mark) or par-rate bp × bpv.
- **Certification** must be premium-marked: straddle/structure premiums recomputed from the
  stored cube + same-day stored curve, **lag-1 fills** (signal on day t, execute at day t+1
  marks), and the headline number must come from `QueryDrivenBacktest` or a panel validated
  against a QDB replay with stated tolerance (SERFF pattern, corr ≥ 0.97).
- Fly-vs-vol died exactly on the model-vs-executable line (54 executable configs, max +0.000).
  No exceptions.

## Cost model policy

There is no bid/ask in the data (cube carries mid `vol_bp` only — verified 2026-08-08).
The cost line must therefore be **sourced and written down** before any verdict:
1. Shelf: BofA US Vol Primer + 2025-10-08 USD Skew RV desk ticket (bid/offer conventions in
   normal vol bp), Huggins & Schaller on execution.
2. SDR tape if it classifies swaption prints (measured cost line, MBO-style) — local sources
   first.
3. Swap legs: `RVUtils/cost_model.py` (0.25 + 0.05·min(tenor,30) + 0.04·min(fwd_start,10) bp
   half-spread; structure = Σ|w|·leg).
Every verdict carries the house `cost_curve` (break-even cost) and a pre-registered sensitivity
band of **0.5×–2.0×** the assumed line. A verdict that flips inside the band is not ALIVE.

## Data, measured 2026-08-08

| store | asset | coverage |
|---|---|---|
| SwaptionCubeStore | `USD-SWAPTIONVOL-CITIVELOEXCEL` | 1,746 days 2019-08-07→2026-08-06; 17 expiries × 9 tenors × 13 offsets; 115 ATM-only days pre-2020-01-24 tagged `.../atm_only` (mask, never ffill) |
| CurveStore | `USD-SOFR-1D-CITIVELOEXCEL` | 1,346 days (sparse 2010→2023, dense 2024-01→2026-08); cube∩curve = 649 days |
| CurveStore | EUR/GBP/CAD ESTR/SONIA/CORRA `-CITIVELOEXCEL` | 680 days 2024-01→2026-08 each; JPY 633 |
| CurveStore | `USD-SOFR-1D-CITIVELO` (minute) | 930 days 2023-01→2026-07 |
| banked tag cache | `CitiVeloQuotes(offline=True)` par grids | daily 2005-01-03→, 20 curves, tenor-sparse early (USD: 5,540 rows, 1,835 with all 44 tenors) |

**Warm extension** (running 2026-08-08): USD EOD curves 2019-08→2023-12 via
`MDP/IRSwaps/CITIVELO_EXCEL/warm.py` offline — closes the cube∩curve gap to ~6.5 years and puts
the 2022 hiking regime in-sample. The famb lesson ("modern-sample carry was regime luck") makes
this load-bearing for any carry-flavoured family.

## Family queue (priors, mechanism-first; each opens with its oracle gate)

- **F1 — swaption surface residual mean-reversion.** A-priori factor basis: BofA hierarchical
  PCs (HPC1 level, HPC2 gamma-vs-vega rotation, HPC3 left-vs-right), FIXED basis primary
  (sidesteps eigenvector instability + look-ahead); rolling PCA is a walk-forward robustness
  arm only. Trade node-vs-fit residuals as vega-weighted vol spreads/flies. Placebos
  (pre-registered): scale-matched 2D smoother with no factor structure; node shuffle at matched
  marginals; random orthonormal basis rotation. Shadow: ATM vol level / dominant single leg on
  the same signal.
- **F2 — gamma vs realized carry (IV−RV), conditional.** Short-expiry (1M–3M) sector only
  (Nordea prior-killer bars long-expiry vol carry). Realized vol primary series from **daily
  EOD curves back to 2019** (cube start); minute-curve realized is a refinement arm (632 days,
  2024+, no hiking regime — regime-luck trap). Famb steamroller lesson: tail risk reported with
  skew/maxDD/worst-day always.
- **F3 — curve RV: fitted-curve → PCA → residual selection** (Huggins-Schaller ch8–9), 2005+
  banked par grids, multi-ccy. Mark on **quoted par rates, never the fitted curve** (the curve
  is a model of the quotes; a fitted-curve mark lets the strategy trade its own interpolation
  error). Tenor-sparsity mask written before the panel is cut.
- **F4 — conditional trades / skew RV** (curve×vol joint; swap-desk conditional-trades primer;
  implied vs delivered directionality).
- **PARKED — SR3 listed-butterfly re-costing** (needs butterfly history, not one MBO day) and
  **famb STRG pre-registered forward run** (spec named in famb findings; needs forward window).
  Ledger rows exist so the loop cannot re-discover them.

## The machine

- Worktree `C:\Users\chris\clee\ARBS-rv`, branch `feat/citivelo-rv-loop` off origin/main
  33fe6981. Primary checkout is never written.
- Maker ≠ checker: research runs inline; every candidate verdict is attacked by a separate
  checker agent operating under
  `docs/superpowers/specs/2026-08-08-citivelo-rv-loop-checker-charter.md`. The checker's
  written verdict, not the maker's, decides. Checker is validated once on a planted defect
  before its first real verdict.
- Program code: `notebooks/backtests/citivelo_rv/` (+ `RVUtils/` modules where durable).
  Panels: `notebooks/data/citivelo_rv/` (gitignored; every panel records its rebuild command in
  this doc's appendix).
- Every script starts with `os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")` before any
  `Caching` import. Python is `conda run -n stir`.
- Baseline: fast pytest gate running on fresh main (2026-08-08) before any change.

## Known harness landmines to verify before certification (from spec §6)

1. QDB signed-bpv direction blindness (reported unfixed 2026-07-30) — planted sign test before
   trusting any QDB number: buy vs sell same structure must mirror; a known rate move must
   produce a known P&L sign.
2. `RLIRSwapCurve.py` notional `* -1` sign bug (pre-fix numbers suspect) — verify current state.
3. Unregistered product → base `PositionHandler` returns gross package value silently — read
   `Query/IRSwaptions/position_handler.py` for entry-anchored convention before use.
4. `run()` swallows exceptions per step — wrap and re-raise inside signal fns.
5. Explicit-timestamp queries freeze one pricer for the whole run.
6. `UnwindPositionsAction.fee` is the only cost hook — flat currency at exit.

## Panel rebuild commands (appendix)

- Vol panel: `conda run -n stir python notebooks/backtests/citivelo_rv/build_vol_panel.py`
- Curve panels: `conda run -n stir python notebooks/backtests/citivelo_rv/build_curve_panel.py`
