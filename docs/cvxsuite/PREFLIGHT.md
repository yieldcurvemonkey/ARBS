# CvxSuite pre-flight — handover prompt for a new session

You are picking up the convexity-RV production suite ("CvxSuite") in the ARBS
repo. Read this file end to end before touching anything; every claim in it
was measured in the building session (2026-08-26/27) or is quoted with its
source. The genre rule of this codebase: numbers are measured, not assumed;
bank claims are attributed; ARBS verdicts are marked; nothing is called
ALIVE without a deflated-Sharpe verdict at a declared trial count.

## 0. Where things are, and what you must not touch

- **The work lives in worktree `C:/Users/chris/clee/ARBS-cvxsuite`, branch
  `feat/cvx-rv-suite`, shipped as PR #508** (8 commits, `2e3f42a4..88f53f7e`;
  body at `docs/cvxsuite/PR_BODY.md` — read it, it is the results record).
- **The primary checkout `C:/Users/chris/clee/ARBS` carries someone's
  in-flight, uncommitted fly-weighting work** (`RVUtils/fly/`,
  `TB/weighting.py`, modified `IRSwapQuery/UnifiedQuery/TimeseriesBuilder` +
  notebooks). It is NOT part of this suite and NOT yours. Never write, stage,
  or "clean up" anything in the primary. Start any new work in a NEW
  worktree (`git -C <repo> worktree add ../ARBS-<short> -b <branch>`), and
  prefix every git command with `git -C <path>`.
- Framework docs: `docs/cvxsuite/DESIGN.md` (the binding design; **§6a is
  the dated correction record from the adversarial review — read it before
  trusting any older number**), `docs/convexityrv/kink_ledger.md` (the
  theory synthesis this suite implements; committed on the branch),
  `docs/convexityrv/DESIGN.md` (the strat1/2/3 measurement layer),
  `docs/curvefly/DESIGN.md` (screener conventions). Artifacts from the
  research sessions: "The Convexity Ledger", "Vol Without Vega", "The Kink
  Ledger" (`/artifacts` lists them).
- Memory files that matter: `project_cvx_suite`, `project_kink_ledger`,
  `project-curve-fly-screener`, `citivelo-rv-loop` (the dead-family ledger),
  `reference_excel_supervisor_test_hazard`.

## 1. The theory, compressed (what the suite implements)

**One identity unifies the framework** (Salomon *Understanding the Yield
Curve* Part 6): `E[R] = yield income + rolldown + ½·Cx·σ² + duration·view +
local rich/cheap`. Forwards decompose as expectations + bond risk premium −
convexity bias (`CB = −½·Cx·Vol(Δy)²`, vol in ABSOLUTE bp; zero-coupon
Cx ≈ duration²/100). The PCA-on-1y-forwards machinery (CS *PCA Unleashed*,
ING *Deconstructing the EUR yield curve*) measures the **last** term — a
"kink" is the factor/cross-sectional residual of local curvature. The
convexity ledger measures the **middle** terms — the rent, normalized as
`σ_BE = √(2·θ_daily/Γ)` in bp/day against realized vol.

**A kink is a fly, and a fly is signed convexity.** The tradeable expression
of a kink is a micro-fly on adjacent grid points; receiving an upward kink
(belly rate high vs wings = belly CHEAP) = the bullet side = **short local
convexity = you collect rent while positioned for reversion** — the only
configuration that literally "earns theta while fading kinks". Paying a rich
belly = long convexity = you pay rent, and the mispricing must beat the bill
(Citi 2010's arithmetic: target = mispricing − rent).

**The scarcity fact that shapes everything**: `corr(carry, level z) = +0.61`
(measured, 1,075 structures). A static kink harvested by roll and a
reverting kink harvested by reversion are the SAME P&L on two clocks — never
add carry and expected reversion, net them (`rac_net`; formally
Huggins–Schaller Ch3 fn 24: charge carry over the OU expected-first-passage
horizon, report P(FPT > carry-breakeven)). "Earning theta while fading" is
the RARE decoupled cell: carry > 0 with z at-or-cheap-of fair, carry above
the carry-vs-vol frontier, or a maturity-anchored kink whose roll-off pays
without any reversion.

**Three frontiers price every candidate** (deviation from the surface, not
any one axis): (1) value–carry — ING: residual = −1.27·rolldown + 16.4,
R² 0.93, slope DOUBLES under PC1-neutral weighting (the +0.61 in regression
form; fade only the off-frontier component); (2) carry–vol — ING: nvol =
5.62·rolldown − 25.9, R² 0.97 (rolldown IS priced vol; the ledger's
σ_BE/σ_rlzd is this frontier in breakeven units; Citi's two-sided anchors
0.8 long / 1.17–1.38 short are CURVE-PAIR anchors, never validated on
micro-flies); (3) reversion–horizon (OU/FPT, target at half-distance,
Sharpe declines with horizon).

**Five layers of a kink — subtract before fading**: expectations curvature
(meetings; a meeting-step model explained 91% of the ZQ "kink" — that family
is dead), risk-premium curvature, convexity bias (dominant ≳20y forward
start — CS's own PC1 loadings flip negative there; ING's frontiers break
there; fit residuals on the CONVEXITY-ADJUSTED curve, `f̃ = f + ½σ²·T₁·T₂`
from the swaption cube, or the long end reads as a permanent fake kink),
local/technical (supply, LDI, CTD-delivery cusps for futures-derived
curves), and the residual — the only fade candidate. Zones on the grid:
`meeting` (fwd < 2y), `convexity` (fwd ≥ 20y), else `clean`.

**Vol prices the rent; it is NEVER the hedge pair.** Salomon Part 7 (1996):
curvature is ~0.8-correlated with curve-reshaping expectations, ~0.1 with
implied vol; "arbitraging" curvature vs option vol cannot neutralize the
curve exposure. ARBS re-measured it: a fly's partial R² to vol after
level/slope controls is 0.000–0.044. The cube feeds fair-value rent
(σ_impl), never a vega hedge.

**Polarity, pinned once (the sign chain that was once backwards)**: the fly
level is `L = 2b − f − k` in RATE bp (belly=+2 — the ONE ruler suite-wide,
DESIGN §6a.1). `zs = z(L)` over trailing 756d, windows trailing-INCLUSIVE.
`zs > 0` = L above its mean = belly CHEAP = fade **receives** the belly
(direction = −sign(zs) in the dislocation book). Gate shapes INVERT between
pairs and flies: for a forward PAIR the level-long steepener IS the
short-convexity harvest side; for a FLY the harvest side is SHORT the level
— transplanting a pair gate onto point rows is exactly the side-inversion
the review caught in `books.py` (§6a.5). If you ever "fix" a sign here,
re-derive from the engine probe, not from a docstring.

**The dead ledger is a constraint set, not history**: F3 xsec fade (median
63d reversion +0.81–1.14bp vs ≥1.0bp RT — pond equals boat), F-ING (21–29Y
construction sawtooth), ZQ/SFR/intraday kink fades, W4 ultra-long carry
(gross 0.397 < null 0.446 — DURATION in disguise; the reason rac_net and
factor gates exist), CA-vs-fly and every fly-as-vega idea, basis-vs-vol V1/
V2. Program result L-0088: on daily marks at measured costs, knowing what
traded does not help you fade what moved — a registered dislocation family
needs a NON-FLOW persistent state (supply/LDI/index/CTD calendars), which is
a data acquisition, not code. The suite therefore ships as: a harvest
selection layer (no reversion needed), a dislocation MACHINE awaiting state
data, and measurement everywhere.

## 2. The code map (all under the worktree)

`RVUtils/CvxSuite/` — C1 kernels import repo kernels only, never each other:
- `grids.py` — `KINK_GRID` (17 CS-style points, spot 1y → 40y10y),
  `leg_label` ("7y1y", LOWERCASE — case forks the IRSwapsTB cache symbol),
  `k_coord` (fit abscissa), `classify_point` (meeting/convexity/clean),
  `CURVEFLY_UNION_LEGS` (80 legs — warm from THIS, not `leg_universe()`).
- `carry.py` — repriced carry only: `carry_roll_bp` (aged-rate identity),
  `leg_roll_bp` (`handle.roll`), tie-out ≤1.0bp on forwards. NEVER
  `IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` for ranking (corr −0.136 vs
  published; repriced +0.991). Spot legs do NOT tie out cross-path;
  age-past-zero RAISES (spot-1y at 1y horizon).
- `vols.py` — `cube_atm_bp_year` (bilinear INSIDE the day's quoted axes,
  clamped, never extrapolated; NaN when absent), `quoted_axes(date)`
  (**axes vary by day** — 136 vs 153 nodes measured; support-gate from this,
  never a hardcoded grid), `realized_vol_bp_day` (bp/DAY, ex-dates masked),
  `units_median_guard` (0.5–40 bp/day). Cube expiry axis has NO 25Y node
  (25y5y interpolates 20Y–30Y) and tops at 30Y (40y10y σ_impl NaN by
  design; spot-1y too).
- `ou.py` — re-exports `mean_reversion` canon + `fpt_sample` (explicit
  `np.random.Generator`, per-path hits, censored = inf; `fpt_stats`
  REQUIRES `steps=`; hits are step indices = business days at dt=1),
  `p_fpt_exceeds`.
- `residuals.py` — float-k hat-matrix xsec fit (spline knots (1,3,7,15,27);
  k=35/45 sit on the cubic extension — leverage is PRINTED),
  `walk_forward_pca_residuals` (monthly-frozen, fit strictly before month
  start, per-refit |cos| continuity), `sign_agreement` (NaN-refusing),
  `convexity_adjustment_bp` (Ho-Lee two-time form via
  `holee.ho_lee_ca_bp` — always pass `convention=` explicitly at pack call
  sites), bp-scale guard (median |level| ≥ 20bp or raise).
- `frontiers.py` — per-day OLS `daily_xfit` + `off_frontier` (orientations
  documented; NOT a hedge regression).
- `gates.py` — degeneracy (0.25bp/day floor), support, compose-vs-price
  (3bp), eigenvector-gap (per-step |cos| ≥ 0.90 — NOTE: overlapping windows
  smear a real rotation across steps; a cumulative first-vs-last check is
  the sharp detector, currently a documented recommendation), cloud
  diagnostic (H-S pre-entry corr vs PC1). All gates fail CLOSED on NaN.
- `rent.py` — `package_gamma_usd` (quadratic fit incl. linear term over
  `payoff_profile`; packages via `pricer.build_irswap(bpv=±…)` handed
  STRAIGHT to the profile — `resolve_pricable` would double-apply
  direction), `sigma_be_bp_day` (uses |Γ| so the short-gamma root is
  representable; status taxonomy root/always_cheap/never_cheap/undefined —
  a NaN would hide opposite states).
- `books.py` — two-book classifier; `REQUIRED_COLUMNS = (be_over_rv, zs,
  rac_net, sign_agree, tag, edge_bp)` exported; harvest gate is RE-SIGNED
  for the receive-belly side (§6a.5): `zs ≥ −0.5` and `−rac_net > 0`;
  dislocation `|zs| ≥ 2 & agree & clean & edge > 1`; NaN refuses; both-pass
  → dislocation.
- `panels.py` — historical strategy inputs: harvest panel `("date","pair")`
  on RAW pair levels (stated approximation), dislocation panel
  `("date","point")` on the belly=+2 ruler with the shared edge formula;
  panel carry is the ING strip-interpolation APPROXIMATION (panel-only —
  the as-of screen repriced); leg panel keyed "10Yx10Y" strat3-form.
- `kink_screen.py` / `board.py` — the compositions. Screen: dual residuals
  on CA-adjusted levels, ALL reversion stats on the fly level L (the §6a
  duration fix), rent row per point, `df.attrs` diagnostics (read
  immediately — attrs don't survive pandas ops). Board: W1 via
  `strat3.screen_frame`, W2 via `strat2.ca_snapshot` + Ho-Lee (σ_BE ≡
  σ_impl on W2 by identity), W3 micro-flies (be_over_rv NOT comparable to
  W1 — near-zero-Γ flies explode the ratio), W5 cube vs realized.

**The shared edge formula (screen ∧ panel, byte-consistent in spirit)**:
`h = max_hold_bd = 63`; `edge_bp = e_rev·p_hit_h − |carry_bp_day|·min(e_fpt,
h) − cost_rt_bp`, all on the belly=+2 L; screen p_hit from the MC hits
array, panel p_hit = 1 − exp(−h/e_fpt); cost 2.3bp RT (≈0.2875bp/leg
one-way × 4 units of leg DV01).

`BT/signals/cvx_{strikeless,kink_harvest,fly_dislocation}.py` — import by
full path (the package `__init__` does not re-export them; `ustf_basis`
precedent). All are plain `QueryStrategy(name, triggers=[…])` instances —
the repo has ZERO QueryStrategy subclasses; logic lives in trigger closures.
Fees: strikeless per the strat3 FIG9 schedule at unwinds; harvest
$120,000/RT (2×2×0.30bp×$100k — the §6-frozen cost); dislocation
$57,500/RT (2.3bp × dv01/2 — the package pays dv01/2 USD per bp of L).
`CurveMapMDP` (in cvx_strikeless) serves QDB marks from a pre-fetched
{date: pricer} map with NO fetch path — the strongest offline form; the
TimeGrid must equal the map's days.

Scripts (famb conventions: docstring command, env setdefault BEFORE
imports, `--date live`, gate lines `=== GATE … ===`, exit 2 when nothing
priced): `kink_ledger_screen.py`, `breakeven_board.py`,
`cvxsuite_warm_legs.py` (Excel tripwire — the TB layer cannot pass
`offline`), `cvxsuite_build_panels.py`. Regenerable parquets are gitignored
under `docs/cvxsuite/` (leg_history 1,912×80 2019-01-02..2026-08-24;
leg_panel 5,628 rows repriced; harvest/dislocation panels).

Notebooks: 4 executed pairs under `notebooks/backtests/cvx_suite/` (build
with `scripts/s3_build_notebook.py <src.py>`, verify with
`scripts/_check_notebook.py`; jupytext is NOT installed). Tests: 16 files
`tests/test_cvx_suite_*.py` + `tests/test_bt_cvx_*.py` +
`test_stirfuture_structure_fly_basis.py` — 368 green in one 62s run
(`-m "not slow"`) + the slow 2y certification (97s). Mutation discipline is
the norm: compile-check + named-test-kill + byte-restore, ledgered in test
docstrings.

## 3. Data-layer rules (each one bit somebody)

- `os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")` BEFORE any repo
  import, in every script/notebook. Never SET `ARBS_CACHE_DIR` (unset
  resolves to the platformdirs cache where the 2,711-day cube lives).
  `ARBS_DATA_ROOT=D:\ARBS_DATA\repo` anchors `data/ts` (without it a
  worktree run silently forks the computed-TS store).
- Curve pricer, offline: `IRSwapsMDP(source="CITIVELO_EXCEL").get_data(
  {"curve_name": "USD-SOFR-1D", "timestamp": <date>, "offline": True})`
  then **assert `p.meta().get("from_curve_store") is True`** — a non-stored
  day silently BUILDS a rateslib curve from quotes (observed on a
  Saturday) instead of returning None. Drop reference-date mismatches (the
  store serves holiday rows stamped with the prior session).
  `bulk_get_data` COERCES today to "live" — refuse today.
- Python: `C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8`, never
  `conda run` for anything parallel (temp-file collision → EMPTY output).
- SR3 futures: `STIRFutureMDP(source="BARCHART_STIRF-RL")` — the CLASS
  DEFAULT IS WEBULL, always pass the source — under
  `RVUtils.ConvexityRV.listed_cache_guard.cache_only()` (no offline switch
  exists; a miss is a proxied Barchart fetch). Settle cache extends past
  stale coverage notes — re-measure, don't trust them. Negative `contracts`
  silently goes LONG (direction on risk_weights); pack aliases mismark in
  QDB (4 OUTRIGHT legs instead).
- Label namespaces: curve legs "10y10y" (lowercase, cache form), strat3
  legs "10Yx10Y", swaption points "5yx10y" — three namespaces, do not mix.
- Fast gate: `conda run -n stir python -m pytest tests -m "not slow and not
  network and not db"` — BUT SEE §5 before running it on this machine.

## 4. QDB rules (the engine bites silently)

`DateTriggerRequirements` dates must be `datetime.date` — a pd.Timestamp is
a silent no-op (every mark exactly 0.0, run "completes"). `run()` swallows
every per-step exception (`except: print`) — always assert: grid coverage
of `mtm_history`, non-zero-mark count, closed-position count (2×/3× the
episode count — a ghost unwind's fee is DROPPED silently and the rac
battery alone cannot see it). Resolve legs to EXPLICIT effective/maturity
at entry (relative tenors re-resolve at every mark → NPV≈0 forever). Fees
only via `UnwindPositionsAction(fee=…)` on tags that MATCH. Per-episode
tags (same-day roll = adds fill BEFORE unwinds; distinct tags). Lag-1 is
strategy-side (no t+1 in the engine). Run the ±bpv mirror sign probe before
trusting any direction (the L-0012 seam re-signs `abs(notional)` at every
mark). `mtm_history` is CUMULATIVE TOTAL P&L, not equity-vs-capital;
tearsheet via `BT.query_tearsheet.QueryBacktestTearSheet.from_backtest`.

## 5. Machine hazard: the fast gate wedges with Excel open

With a real Excel open and the Citi add-in signed out,
`tests/test_citivelo_fixings_offline.py::test_the_old_bounded_request_is_what_went_to_excel`
blocks FOREVER in `MDP/CitiVelocityExcel/supervisor.py:656 wait_for_addin`
(via `quotes._launch_and_wait`) — a seam the conftest `_no_live_excel` rail
does NOT fence (it patches `connect`/`press_addin_login` only). Zero CPU,
no pytest output, no summary. Diagnose any future wedge with
`-v -o faulthandler_timeout=180` redirected to a log (NOT
`--faulthandler-timeout` — unrecognized). Workaround: sign the add-in in or
close Excel, or `--deselect` that node id. The 2026-08-27 gate:
**10,856 passed / 9 failed / 122 skipped in 2h29m** with that test
deselected; the 9 failures are environmental (the signed-out-Excel test
family ×5, bond fetcher ×1, read-path perf ×2, computed-TS base-dir ×1 —
`ARBS_DATA_ROOT` relocates it), all in files untouched by the branch.
Durable fix (open item): fence `wait_for_addin` in the conftest rail or
mark the test `live_excel`.

## 6. State, reference numbers, and the honesty rules around them

Reference numbers (engine-run, frozen §6 configs — NEVER quote without the
qualifiers): strikeless certified vs the strat3 ledger 7.6y on both pairs
(corr 0.999719/0.999402, hedges 50/50 rolls 7/7 exact, terminal gaps
+3.14/+2.98bp STATED — sizing-convention drift, do not smooth; net
+61.2/+35.5bp, Sharpe 0.40/0.24 vs the strat3-grid null E[max|5,040] =
1.599); kink harvest 2 episodes net −13.0bp (the +0.61 confound behaving
as documented); fly dislocation 38 episodes (25 receive / 13 pay), gross
+96.3bp, net@1× +52.6bp, DSR 0.845 = an UNDEFLATED single-cell PSR, gross
concentrated in 18 target exits — machinery plus a reference run, not a
verdict. The §6a amendment record is the provenance for why any older
number (23 episodes, $115k fees, +23bp "edges") is superseded and
unquotable.

Open items, in order of value: (1) merge review of PR #508; (2) the
conftest `wait_for_addin` fence; (3) strikeless terminal-gap decomposition
(event-day vs carry-day) then pin an accepted band next to the corr bar;
(4) the NON-FLOW state calendar (issuance/LDI/index/CTD events) — the one
genuinely new data acquisition, prerequisite to registering the dislocation
family per L-0088; (5) harvest-panel adjusted-level (ca_bp) plumbing;
(6) W4 basis board row needs term repo (JPM package per-issue repo is the
stopgap); (7) cumulative eigenvector-rotation gate (the per-step |cos|
smears under 97% window overlap).

Working rules, non-negotiable: pre-register configs before backtests (few,
closely related — L-0064); name incumbent nulls (F3, W4, 1.599); research
bugs flatter the hypothesis (12/12 precedent — adversarially review your
own results, with executed probes, before believing them); costs per leg at
0×/0.5×/1×/2×; negative controls that must fail; everything in bp/day at
the ledger boundary with the 0.5–40 guard; a negative result is a result.
