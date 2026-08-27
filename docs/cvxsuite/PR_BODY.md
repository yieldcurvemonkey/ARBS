# CvxSuite: the convexity-RV production layer — screens live, three QDB books engine-certified, review-corrected before any result existed

**The verdict up front.** The suite the convexity-RV programme asked for
(Convexity Ledger Part VI; `docs/convexityrv/kink_ledger.md` §7) now exists as
one package: the kink ledger screen and the cross-wrapper breakeven board run
daily offline from the Citi Velocity stores (Query/MDP), and three
QueryDrivenBacktest reference books run on Barchart + Citi data with sign
probes, assertion batteries, and fees that tie to the dollar. A five-refuter
adversarial review ran BEFORE any full-history P&L existed on the final
semantics; it found and forced five corrections (one of which — a duration
z masquerading as a kink z — is the exact failure that killed W4), and the
dated record of every correction is in `docs/cvxsuite/DESIGN.md` §6a. No
aliveness is claimed anywhere: reference numbers ship with their incumbent
nulls attached.

## What shipped

| Component | What it is | Status |
|---|---|---|
| `RVUtils/CvxSuite/` (12 modules) | grids, carry, vols, ou, residuals, frontiers, gates, rent, books, panels + kink_screen, board | new; 209 kernel tests + composition tests |
| `scripts/kink_ledger_screen.py` | daily 17-point kink screen (dual residuals, CA-adjusted, rent rows, two-book labels) | runs 2026-08-21 in ~25s offline |
| `scripts/breakeven_board.py` | W1/W2/W3/W5 σ_BE/σ_rlzd + σ_impl/σ_rlzd, one bp/day axis | prices all four wrappers on 2026-08-21 |
| `BT/signals/cvx_strikeless.py` | strat3 hedge-tape replay through QDB + certification | corr 0.999719 / 0.999402 vs the unit ledger, 7.6y, hedges 50/50 rolls 7/7 exact |
| `BT/signals/cvx_kink_harvest.py` | same-tenor forward-pair harvest, panel-driven, lag-1 | 2 episodes; net −13.0bp at the frozen 0.30bp/leg costs |
| `BT/signals/cvx_fly_dislocation.py` | PCA-neutral micro-fly fades, 63bd book | 38 episodes; gross +96.3bp, net@1× +52.6bp |
| `scripts/cvxsuite_warm_legs.py` / `cvxsuite_build_panels.py` | 80-leg warm (Excel tripwire) + repriced leg/harvest/dislocation panels | 1,912×80 legs; 5,628-row leg panel, 0 failures |
| 4 executed notebook pairs | `notebooks/backtests/cvx_suite/` | `_check_notebook` 0 errors / 0 never-executed on all |
| Fix: `Query/STIRFutures/STIRFutureStructure.py` | FLY/BASIS builders NameError (`**_` vs `kwargs`) — every call raised | fixed + mutation-checked regression tests |

Wrapper coverage map (how "all sub strategies" are covered without rebuilding
verified work): W1 strikeless = new QDB wiring over strat3; W2 SR3 CA = board
row over the existing strat2 screen/backtest; W3 kinks/flies = new; W4 basis
= mapped to the existing `BT/signals/ustf_basis.py`, not rebuilt; W5 options
= board rows off the cube; the CMS feed and conditioning dashboard remain
data acquisitions, not code.

## The adversarial review, and what it changed

Five refuters (signs / causality / units / engine / stats) with executed
probes. **Causality: CLEAN** — planted-future mutations left every prior
panel row bit-identical; entries verified lag-1 by construction probes.
**Engine: clean** with receipts (explicit dates, tag sets, gross-vs-gross
certification, real negative controls). Five corrections were forced, all
fixed before any full-history P&L existed on the final semantics (§6a):

1. **Duration in kink clothing** (found by the orchestrator's own read, fixed
   pre-review): per-point z ran on adjusted outright levels — 15/17 points at
   z≈+2 together with +23bp fake "edges". All reversion statistics now run on
   the composed micro-fly level (2b−f−k), and the artifact is gone.
2. **One fly ruler.** The panel/strategy charged the single measured
   2.0–2.6bp cost band on a belly=+1 level while the screen used belly=+2 —
   a 2× double-charge (fee $115k → $57.5k). Anti-flattering, still wrong.
3. **The edge gate runs on the book's clock**: p_hit and carry at
   min(E[FPT], 63bd) — the review measured 86/265 gate rows priced on a hold
   the frozen book cannot run.
4. **Frozen costs restored** (harvest 0.30bp/leg; the shipped 0.25 was a
   post-freeze understatement) and **entries must agree with the fade**
   (sign_agree == sign(zs); 2/23 episodes had traded against both residual
   models).
5. **books.py point-row harvest gate re-signed for the receive-belly side**
   (the pair-shape gate had been transplanted onto flies, where the
   level-to-convexity mapping inverts). The review's planted rows are pinned
   as tests verbatim.

## Reference numbers (never verdicts)

- **Strikeless (W1)**, 2019-01-02..2026-08-22, both frozen pairs:
  certification corr 0.999719 / 0.999402, hedge and roll counts exact
  (50/50, 7/7), terminal gaps **+3.14bp / +2.98bp stated, not smoothed**
  (the known sizing-convention drift). Net +61.2bp / +35.5bp, Sharpe
  0.40 / 0.24 — far under the strat3 grid null E[max SR | 5,040] = 1.599,
  consistent with the incumbent verdict that this is a structural allocation,
  not a timing edge.
- **Kink harvest**, frozen gates, 2 episodes: net −13.0bp at 1×
  (−15.4bp at 2×). The +0.61 carry-richness confound doing exactly what the
  framework says it does; the gates refused everything else.
- **Fly dislocation**, corrected semantics, 38 episodes (25 receive-belly /
  13 pay-belly; exits 19 horizon / 18 target / 1 stop): gross +96.3bp,
  net@1× +52.6bp, net Sharpe 0.55 (NW t 0.99), DSR prob 0.845 — **which is
  an undeflated single-cell PSR** (one frozen config; deflation inactive and
  said so in the notebook). Incumbent null to beat remains F3's "pond equals
  boat" (median 63d reversion +0.81…+1.14bp vs the round trip), and
  L-0088's constraint stands: a registered family here needs a NON-FLOW
  persistent state (supply/LDI/index calendars), which is a data
  acquisition, not code. This book is machinery plus a reference run —
  registering it as a family is explicitly out of scope of this PR.

## For a human, not for an unattended agent

- **The fast gate wedges on this machine when Excel is open, and the culprit
  is now identified with a stack**:
  `tests/test_citivelo_fixings_offline.py::test_the_old_bounded_request_is_what_went_to_excel`
  blocks forever in `MDP/CitiVelocityExcel/supervisor.py:656 wait_for_addin`
  via `quotes._launch_and_wait` — a seam the conftest `_no_live_excel` rail
  does not fence (the rail patches `CitiVelocityExcelClient.connect` and
  `press_addin_login`, but this path waits on the add-in directly). With
  "Book4 - Excel" open and the add-in signed out it waits with zero CPU and
  no pytest output (three wedged runs this session; faulthandler dump in the
  session log). Pre-existing: the file is untouched by this branch
  (`git diff main` empty). This PR's gate number was produced with that one
  test `--deselect`ed; the real fix is fencing `wait_for_addin` in the
  conftest rail or marking the test `live_excel`.
- **Strikeless terminal gap**: +3.1bp/7.6y is ~5% of gross but dominates on
  near-zero windows (the 2-year certification saw +1.14bp on +4.6bp net).
  Recommend pinning an accepted band next to the corr bar after one
  event-day-vs-carry-day decomposition.
- The `docs/cvxsuite/*.parquet` artifacts are regenerable and gitignored;
  `notebooks/backtests/cvx_suite/*.ipynb` are committed EXECUTED per house
  convention (the strikeless one is 2.6MB).

## Testing

- New-suite tests: **368 green in one combined run across the 16 new test
  files** (`-m "not slow"`, 62s), plus the slow 2-year strikeless
  certification test which passed separately in 97s — 369 total; integration
  tests executed against the real offline stores (curve store, cube, SR3
  settle cache), self-skip proven against an empty cache dir.
- Full fast gate (`-m "not slow and not network and not db"`, the house
  set): **10,856 passed, 9 failed, 122 skipped in 2h29m**, with the one
  Excel-wait test deselected (below). All 9 failures are in files untouched
  by this branch (`tests/test_citivelo_fixings_offline.py` ×5 — the
  "signed_out_excel" family, `test_citivelo_bond_fetcher.py` ×1,
  `test_citivelo_read_path_perf.py` ×2,
  `test_computed_query_timeseries_cache.py::…default_base_dir_is_repo_root_relative`
  ×1) and are environmental on this machine's current state: a real Excel
  open with the Citi add-in signed out, plus `ARBS_DATA_ROOT` set (which
  relocates the computed-TS default base dir). An isolation re-run of the
  nine wedged on the same machine state, which is the same evidence. Node
  ids above; none share a module with anything this PR changed.
- **Mutation discipline**: 80+ planted mutations killed across the session's
  harnesses (9/9, 11/11, 13/13, 12/12, 19/19, 8/8, 5/5, 2/2, 3/3 per
  module-family, each with compile-check + byte-restore verification); two
  harness self-guards fired and were fixed (an anchor matching two sites; a
  mutant masked by an incidental TypeError).
- Engine probes: ±bpv mirror sign probes pass on real curves in all three
  books; scrambled-ledger certification negative control fails as designed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01UAZKBWnixtNvsGW6ghP3Qj
