# CvxSuite — design and interface contracts

Production join layer for the convexity-RV framework: the kink ledger screen,
the cross-wrapper breakeven board, and QDB reference strategies. Everything
stated here as a number was measured on this machine or is quoted with
attribution. Framework sources: `docs/convexityrv/kink_ledger.md` (the
combined PCA × kink × convexity framework), the Convexity Ledger artifact
(Part IV "operationalized", Part VI "what to build"), `docs/convexityrv/DESIGN.md`
(strat 1/2/3), `docs/curvefly/DESIGN.md` (screener conventions).

## 0. Scope and stance

**Build the join, reuse the kernels.** Verified kernels are imported, never
re-derived: `ConvexityRV.curve_ops` (payoff_profile; translate-ageing raises),
`ConvexityRV.holee` (CA forms — `convention=` passed explicitly at every call
site), `ConvexityRV.strat3_strikeless_vol` (leg_metrics repriced roll, screens,
ledgers, hedge_schedule), `ConvexityRV.strat2_sofr_convexity` (ca_snapshot,
matched Q/Q swap), `CurveFlyScreener` (aged-rate carry identity, rac_net),
`INGCurve.xsec` (pinned registration — NOT edited), `mean_reversion` (OU/AR1/
FPT canonical home), `StatisticalFinance` (DSR/permutation/sign-flip),
`Caching.swaption_cube_store`.

**Wrapper → production home map** (how "all sub strategies" are covered):

| Wrapper | Screen | Backtest home | Status |
|---|---|---|---|
| W1 long-end fwd curve (strikeless vol) | `strat3.screen_frame` → board | `BT/signals/cvx_strikeless.py` (QDB, from `strat3.hedge_schedule`) | **new QDB wiring** |
| W2 SR3 CA | `strat2.ca_snapshot` + holee → board | `strat2_sofr_convexity.run_backtest` (exists) | reuse; board row new |
| W3 flies / kinks | `kink_screen` (new) | `BT/signals/cvx_fly_dislocation.py` + `cvx_kink_harvest.py` | **new** |
| W4 UST basis | USTFutureBasis stack (exists) | `BT/signals/ustf_basis.py` (exists) | mapped, not rebuilt |
| W5 options | cube ATM vs realized → board | short-gamma benchmark (Citi 0.84) quoted, not run | board row new |

**No aliveness claims.** The QDB strategies ship as engine-certified reference
implementations with the frozen configs in §6. Incumbent nulls to beat, named:
F3 xsec fade (median 63d reversion +0.81…+1.14bp vs ≥1.0bp RT — pond equals
boat), W4 rac harvest (gross 0.397 < null 0.446, duration in disguise), strat1
grid null (E[max SR | 5,040 cells] = 1.599). Verdicts belong to the RV-loop
ledger only if a family is registered there; nothing here registers one.

## 1. Conventions (binding)

- **Units:** bp/day everywhere at the ledger boundary; bp/yr internal to vol
  sources with explicit `_bp_year`/`_bp_day` suffixes; `sqrt(252)` crossings
  only inside named converters. Median-plausibility guard 0.5–40 bp/day on any
  SOFR-complex daily-vol series (the w3 pattern).
- **Carry:** repriced (aged-rate identity or `handle.roll`) — never
  `IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` for cross-sectional ranking
  (corr −0.136 vs published; repriced +0.991).
- **Gamma:** reprice on `handle().shift(bp)`; `Curve.translate` ageing is
  banned (`horizon_handle` raises); `GAMMA_01`/`DV01` raise on the RL backend.
- **Sign probes over labels:** every QDB runner re-derives direction from the
  engine (±bpv mirror probe) before trusting any sign; `bpv<0` = flattener =
  long convexity per the measured convention table in docs/convexityrv/DESIGN.md §1.
- **Offline discipline:** `os.environ.setdefault("ARBS_SUPABASE_ENABLED","0")`
  before repo imports; curve requests carry `"offline": True`; SR3/option MDP
  calls wrapped in `listed_cache_guard.cache_only()`; leg warms install the
  Excel tripwire (the TB layer cannot pass `offline`). `ARBS_CACHE_DIR` is
  never set by scripts (unset resolves to the platformdirs cache where the
  2,711-day cube lives).
- **QDB:** plain `QueryStrategy(name=..., triggers=[...])` instances (repo
  practice — zero subclasses exist); `DateTriggerRequirements` dates are
  `datetime.date` (a pd.Timestamp is a silent no-op); fees only at
  `UnwindPositionsAction(fee=...)`; explicit effective/maturity resolved at
  entry (relative tenors re-resolve to NPV≈0); per-segment tags; lag-1 fills
  strategy-side; the assertion battery (non-zero marks, closed-position count,
  no grid holes) after every run.

## 2. Data sources

- **Swap curve / cube (Citi Velocity Excel add-in, Query/MDP):**
  `IRSwapsMDP(source="CITIVELO_EXCEL")` per-date pricers (store-backed,
  measured 2.5s cold; `from_curve_store=True` asserted); leg histories via
  `TimeseriesBuilder` + `IRSwapsTB` warm-once-compose (lowercase tenor labels;
  holiday-ghost filter lives in the TB); `SwaptionCubeStore.default()` ATM
  vols (USD-SWAPTIONVOL-CITIVELOEXCEL, 2,711 days 2015-10-08..2026-08-24;
  smile from 2020-01-24; expiry axis has NO 25Y — clamped interior
  interpolation only, support-gated).
- **Listed futures / options (Barchart, Query/MDP):**
  `STIRFutureMDP(source="BARCHART_STIRF-RL")` (class default is WEBULL —
  always pass the source) EOD settles from the machine-global diskcache
  (2018-05-04..~2026-08-13 at recon); `cache_only()` by default; `--date live`
  screeners may `--refresh` through the guarded throttled fetcher only.
  Options via the STIRFO rawEOD full-history cache and the measured unit laws
  in `ConvexityRV/listed_vol.py` (delta_abs is PERCENT).

## 3. Package layout and API contracts (C1 modules)

C1 modules import kernels only — never each other. Signatures are contracts;
implementers may add keyword-only extras with defaults but not change these.

### grids.py
```python
KinkPoint = NamedTuple("KinkPoint", [("fwd", float), ("tenor", float)])  # years
KINK_GRID: tuple[KinkPoint, ...]   # spot 1y; 1y1y..9y1y; 10y2y; 12y3y; 15y5y; 20y5y; 25y5y; 30y10y; 40y10y
def leg_label(p: KinkPoint) -> str                  # "7y1y" — CurveFlyScreener convention (lowercase)
def k_coord(p: KinkPoint) -> float                  # fit abscissa: fwd + tenor/2 (segment midpoint, years)
def t1_t2(p: KinkPoint) -> tuple[float, float]      # (fwd, fwd+tenor) for the Ho-Lee forward-segment CA
def classify_point(p: KinkPoint, *, meeting_max_fwd: float = 2.0,
                   convexity_min_fwd: float = 20.0) -> str
    # "meeting" (fwd < meeting_max_fwd), "convexity" (fwd >= convexity_min_fwd), else "clean".
    # No "delivery" tag in v1 (swap-derived grid).
CURVEFLY_UNION_LEGS: tuple[KinkPoint, ...]  # KINK_GRID ∪ CurveFlyScreener.leg_universe(), for the warm
```

### carry.py
```python
def carry_roll_bp(pricer, structure, horizon_y: float = 1.0, cache=None) -> float
    # Delegates to RVUtils.CurveFlyScreener.screener.carry_roll_bp (aged-rate identity).
def leg_roll_bp(pricer, label: str, horizon: str = "1Y") -> float
    # handle.roll path via ConvexityRV.strat3_strikeless_vol.leg_metrics; bp of rate.
def carry_ccy(pricer, structure, dv01_usd: float, horizon_y: float = 1.0) -> float
    # carry_roll_bp × dv01, USD — the payoff_profile carry_ccy input.
# Test: the two paths agree within tolerance on forward pairs (G1-style tie-out).
```

### vols.py
```python
ASSET = "USD-SWAPTIONVOL-CITIVELOEXCEL"
def cube_atm_bp_year(expiry_y: float, tail_y: float, date: datetime.date, *,
                     store=None, clamp: bool = True) -> float
    # ATM normal vol bp/yr from the stored grid; bilinear interp INSIDE the quoted axes
    # (clamped at edges, never extrapolated); NaN when the day is absent. KeyError axes
    # come from the cube's own expiries()/tenors() — that IS the support gate.
def cube_atm_panel(points: Sequence[tuple[float, float]], dates) -> pd.DataFrame
    # date × point panel of the above, reading each day once.
def realized_vol_bp_day(levels_bp: pd.Series, *, window: int = 252,
                        min_periods: int = 100, ex_dates=None) -> pd.Series
    # trailing std of daily diffs, roll/ex dates masked (citi_screen.realized_vol_bp pattern).
def bp_year_to_day(v): ...
def bp_day_to_year(v): ...
def units_median_guard(series_bp_day, lo: float = 0.5, hi: float = 40.0) -> None
    # raises ValueError naming the offending median (the w3 pattern).
```

### ou.py
```python
# Re-exports (unchanged): calibrate_ou, ou_mle, half_life, rolling_ar1,
# rolling_half_life, ou_conditional, ou_ex_ante_sharpe, expected_passage_time
# from RVUtils.mean_reversion.
def fpt_sample(x0, target, params, *, sims=2000, steps=504, dt=1.0,
               rng: np.random.Generator) -> np.ndarray
    # per-path hitting times (censored at `steps` -> np.inf), explicit Generator —
    # NEW implementation (mean_reversion.first_passage_time discards paths and reads
    # the global RNG; that function is left untouched).
def fpt_stats(hits: np.ndarray) -> dict   # {e_fpt (censored->steps), p_hit, q25, q50, q75, frac_censored}
def carry_over_horizon(carry_bp_day: float, horizon_days: float) -> float
def p_fpt_exceeds(hits: np.ndarray, days: float) -> float
    # H-S fn 24: P(reversion takes longer than the carry breakeven horizon).
```

### residuals.py
```python
def hat_matrix(ks: Sequence[float], variant: str = "spline", *, degree: int = 3,
               knots: Sequence[float] = (1.0, 3.0, 7.0, 15.0, 27.0)) -> np.ndarray
    # NEW float-k generalization of INGCurve.xsec.fit_matrix (which is pinned to
    # integer ks and its own registered knots — not edited). Same guards: >=8
    # strictly-increasing ks, Schoenberg-Whitney assert, clamped boundary knots.
def fit_diagnostics(ks, variant, **kw) -> dict     # model_dof=trace(H), leverage per k
def xsec_residuals(levels_bp: pd.DataFrame, ks: Sequence[float], variant: str) -> pd.DataFrame
    # per-day (I-H)@row; bp in, bp out; any-NaN day -> all-NaN row.
def walk_forward_pca_residuals(levels_bp: pd.DataFrame, *, n_pcs: int = 2,
        window: int = 756, min_window: int = 504, refit: str = "M")
        -> tuple[pd.DataFrame, dict]
    # monthly-frozen loadings fit strictly before month start (screen.rolling_pc1_residuals
    # pattern generalized to n_pcs via df_based_pca_risk_model); returns (residuals_bp,
    # info) where info[month] = {"loadings", "mean", "explained", "cos_prev"} —
    # cos_prev = per-PC |cos| vs previous refit after greedy matching (gates.eigenvector
    # feed).
def sign_agreement(a_bp: pd.DataFrame, b_bp: pd.DataFrame, *, min_abs_bp: float = 0.5) -> pd.DataFrame
    # +1 both cheap, -1 both rich, 0 disagree/small.
def convexity_adjustment_bp(sigma_bp_year: float, t1: float, t2: float) -> float
    # Ho-Lee forward-segment bias via ConvexityRV.holee.ho_lee_ca_bp(convention="citi"
    # is a PACK convention; here the plain two-time form ho_lee_ca_bp(sigma, t1, t2) is
    # the documented model choice for a t1->t2 forward). Positive number = amount the
    # quoted forward is DEPRESSED; adjusted forward = quoted + CA.
def adjusted_levels(levels_bp: pd.DataFrame, ca_bp: pd.DataFrame | pd.Series) -> pd.DataFrame
```

### frontiers.py
```python
def daily_xfit(y_bp: pd.DataFrame, x_bp: pd.DataFrame, *, min_n: int = 6)
        -> pd.DataFrame       # per-day OLS slope/intercept/r2/n (generic form of
                              # INGCurve.screen.daily_frontier; NaN-guarded)
def off_frontier(y_bp: pd.DataFrame, x_bp: pd.DataFrame, fit: pd.DataFrame) -> pd.DataFrame
    # y - (a + b·x) per day — the tradeable 2-D residual.
# value–carry frontier: y = residual, x = rolldown; carry–vol frontier: y = rolldown,
# x = atm vol (ING Fig 3/4 orientations documented in the module docstring).
```

### gates.py
```python
def degeneracy_gate(realized_bp_day: pd.Series | float, floor: float = 0.25) -> bool | pd.Series
def support_gate(expiry_y, tail_y, *, expiries, tenors) -> bool   # inside quoted axes
def compose_price_gate(composed_bp: float, priced_bp: float, tol_bp: float = 3.0) -> bool
def eigenvector_gap_gate(cos_prev: Mapping[str, float], *, min_cos: float = 0.90) -> dict
    # NEW gate: per-PC pass/fail + overall; feeds from walk_forward_pca_residuals info.
def cloud_diagnostic(structure_bp: pd.Series, pc1_scores: pd.Series, *,
                     window: int = 126, max_abs_corr: float = 0.45) -> dict
    # H-S pre-entry test: trailing corr of structure changes vs PC1 changes;
    # {"corr", "pass"}.
```

### rent.py
```python
@dataclass(frozen=True)
class RentRow:
    gamma_usd_per_bp2: float; theta_usd_day: float; carry_bp_day: float
    sigma_be_bp_day: float; status: str        # root|always_cheap|never_cheap|undefined
def package_gamma_usd(pricer, package, *, shifts=(-100,-50,-25,-10,10,25,50,100)) -> float
    # quadratic fit through ConvexityRV.curve_ops.payoff_profile (currency).
def sigma_be_bp_day(theta_usd_day: float, gamma_usd_per_bp2: float) -> tuple[float, str]
    # sqrt(2|θ|/Γ) with the strat1 status taxonomy (sign of θ decides which side).
def rent_row(pricer, package, *, dv01_usd, carry_bp_yr) -> RentRow
```

### books.py
```python
@dataclass(frozen=True)
class BookGates:  # frozen reference config in §6
    harvest_min_be_over_rv: float; harvest_max_z: float; harvest_min_rac_net: float
    disl_min_abs_z: float; disl_min_edge_bp: float
def classify_books(df: pd.DataFrame, gates: BookGates) -> pd.Series
    # "harvest" | "dislocation" | "none" per kink-screen row, per
    # docs/convexityrv/kink_ledger.md §4.6. Pure pandas; column names documented.
```

## 4. C2 composition

### kink_screen.py
`build_kink_screen(asof, *, leg_hist_bp, pricer, cube_store=None, cfg) ->
pd.DataFrame` — one row per KINK_GRID point with the §6 schema of
kink_ledger.md: residual_xsec / residual_pca / sign_agree / z / pctl (on the
CONVEXITY-ADJUSTED levels), OU stats + FPT, θ (repriced), Γ + σ_BE (as-of only
— repriced profiles are not run over history), σ_impl (cube, support-gated),
σ_rlzd (ex-roll), frontier residuals (off value–carry, off carry–vol),
rac_net@FPT, tags, book. Micro-fly packages for Γ/θ built on adjacent grid
points with DV01-neutral belly=+2 weights (`CurveFlyScreener.neutral_weights`)
— PCA-neutral weights are the *strategy* sizing, the screen prints both.
CLI `scripts/kink_ledger_screen.py --date live|YYYY-MM-DD [--json]`, famb
conventions, gates printed as `=== GATE ... ===` lines, exit 2 when nothing
priced.

### board.py
`build_breakeven_board(asof, *, cfg) -> pd.DataFrame` — rows across wrappers
(W1 pairs via `strat3.screen_frame`; W2 packs via `strat2.ca_snapshot` +
`holee.implied_vol_from_ca_bp` + realized pack vol, SR3 settles under
`cache_only()`; W3 named flies from the kink screen; W5 cube ATM vs realized
swap-rate vol at matched points). Columns: structure, wrapper, θ_bp_yr,
Γ_usd_bp2, σ_BE, σ_impl, σ_rlzd, be_over_rv, impl_over_rv, z, tag. All bp/day.
Citi's published thresholds (0.8 / 1.17–1.38) printed as reference lines and
labeled "curve-pair anchors — not validated on micro-flies". CLI
`scripts/breakeven_board.py`.

## 5. QDB reference strategies (C3)

All follow `BT/signals/ustf_basis.py` shape: frozen config dataclass →
trigger builders → one `QueryDrivenBacktest` per unit → result dataclass;
`IRSwapsMDP(source="CITIVELO_EXCEL")` with `"offline": True`; entries resolved
to explicit effective/maturity; per-segment tags; unwind fees; ±bpv sign probe
+ assert_ran battery; executed notebook pair under `notebooks/backtests/cvx_suite/`.

- **cvx_strikeless.py** — replay `strat3.hedge_schedule(curve_map, cfg)` (the
  exact trade tape: initiate/hedge/roll/unwind) through QDB as dated triggers;
  certify the QDB equity against the strat3 ledger (`certify` function,
  corr ≥ 0.99 + terminal-gap statement — the panel-is-not-P&L rule).
- **cvx_kink_harvest.py** — harvest book: same-tenor forward pairs from the
  screen, entry when rac_net@FPT > 0 AND z ≤ harvest_max_z AND be_over_rv ≥
  threshold at t−1, monthly reform, 3–6m holds.
- **cvx_fly_dislocation.py** — |z| ≥ disl_min_abs_z on sign-agreeing kink
  residuals outside meeting/convexity zones, PCA-neutral weights (frozen at
  entry), enter only when `E[reversion]·P(hit) − |carry|·E[FPT]/252 − cost >
  disl_min_edge_bp`; exits zero-cross / +2SD / max-hold.

## 6. Pre-registered reference configs (frozen BEFORE any backtest ran)

Few, closely related (L-0064); these are the ONLY configs the reference runs
execute; anything else is exploration and says so.

- **Strikeless (W1):** `Strat3Config` defaults with pairs {15Yx5Y/20Yx10Y,
  10Yx10Y/20Yx10Y}, hedge 25bp, roll 12m, entry_rule="always", 2019-01-02..
  latest; costs FIG9 at 1×. Certification target: strat3 ledger corr ≥ 0.99.
- **Kink harvest:** pairs = forward-tenor family members present in KINK_GRID
  {10y10y/15y10y, 10y10y/20y10y, 15y5y/20y10y}; gates harvest_min_be_over_rv
  = 1.17, harvest_max_z = +0.5, harvest_min_rac_net = 0.0 at the measured
  half-life horizon; monthly reform; lag-1; costs 0.3bp/leg one-way ×{0,0.5,1,2}.
- **Dislocation:** disl_min_abs_z = 2.0, sign_agree required, tags == "clean",
  disl_min_edge_bp = 1.0 after 1× cost (3-leg package 2.0–2.6bp RT band),
  max_hold = 63bd, exits zero-cross/+2SD. ONE config.
- **Board/screen:** KINK_GRID as in grids.py; xsec variant "spline" with knots
  (1,3,7,15,27); PCA n_pcs=2, window 756, monthly refit; z/pctl window 756 on
  adjusted levels; OU on trailing 756; FPT sims 2000, steps 504, seed 20260826.

Incumbent nulls (named in §0) are the bar; results reported as
engine-certified reference numbers with DSR at the declared config count,
never as verdicts.

### §6a. Dated amendment — 2026-08-26, post-adversarial-review, BEFORE any
### full-history reference result was produced

The five-refuter review (signs / causality / units / engine / stats; probe
scripts in the session scratchpad) verified the causality and engine layers
clean and found the following, all fixed before the reference notebooks ran.
Corrections that change frozen values are stated here so the freeze stays
honest:

1. **One fly ruler, suite-wide: belly=+2 (L = 2b − f − k).** The dislocation
   panel and strategy had denominated L, e_rev, carry and the cost band on
   the belly=+1 level while the screen used belly=+2 — the single measured
   2.0–2.6bp RT band was being charged on two rulers 2× apart (strategy fee
   $115k vs ~$57.5k at the suite's own per-leg anchors; anti-flattering but
   wrong). Panels rescale to belly=+2; the QDB fee = cost_rt_bp × (P&L per bp
   of that L) = 2.3bp × dv01/2 with the unchanged (−D/2, +D, −D/2) legs.
2. **The edge gate runs on the book's own clock.** edge_bp had credited
   reversion at the 504bd FPT cap and charged carry over the uncapped E[FPT]
   while the frozen book must exit at 63bd (measured: 86/265 gate rows and
   3/23 episodes fail the hold-consistent gate, zero flip in). p_hit and the
   carry charge are now computed at min(E[FPT], max_hold_bd = 63), in the
   panel and in the screen edge alike.
3. **Harvest cost restored to the frozen 0.3bp/leg one-way** (the shipped
   0.25 was a 16.7% understatement vs this section; test pin updated); the
   {0, 0.5, 1, 2}× ladder is produced in the reference notebook by gross
   recosting.
4. **Dislocation entries now require the residuals to agree with the fade**:
   sign_agree == sign(zs) at entry (2 of 23 episodes had entered against
   both cross-sectional models; "sign-agreeing" now means what it says).
5. **books.py point-row harvest gates re-signed for the receive-belly side**
   (rac_net and the z bound were transplanted from the pair-shape gate where
   level-long IS the harvest side; on a fly, harvest is SHORT the level, so
   the gate reads −rac_net > min and zs ≥ −max_z). Screen label only — no
   backtest traded it.
6. Doc corrections: the W1 null belongs to strat3 (5,040 cells, E[max SR |
   null] = 1.599), not strat1; the harvest panel's zs runs on RAW quoted
   pair levels (stated approximation, mirroring the dislocation builder's
   disclosure) — adjusted-level plumbing is future work; production
   run_backtest in both panel strategies now asserts the closed-position
   count (the rac battery alone cannot see a silently dropped unwind fee).

Consequence of 1–4: the dislocation reference episode set changes from 23 to
the hold-consistent set (~20 before the direction gate, fewer after), and
harvest fees rise ~20%. These are corrections of measurement, not selection:
every change was fixed from first principles before any full-history P&L
existed, and the review that forced them is part of the record.

## 7. What this suite is NOT

- Not a new fade family registered with the RV-loop (L-0088 stands: flow-mark
  fades on this data are pre-dead; the dislocation book is machinery awaiting
  non-flow state data — supply/LDI/index calendars are a data acquisition, not
  a code deliverable).
- Not a rebuild of W4 (ustf_basis exists), the CMS curve-vol feed (no data),
  or the conditioning dashboard (external feeds).
- Not a vega hedge anywhere: vol prices rent; it is never the hedge pair
  (Salomon Part 7; measured partial R² ≤ 0.044).
