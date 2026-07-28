# Fly-vs-Vol RV Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `RVUtils/FlyVsVol` (data-agnostic fly-vs-implied-distribution metrics), fast synthetic tests, an EOD screener runner, and a narrative notebook; then run the screener as of 2026-07-27 over all six live adjacent SFR fly triples with daily history z-scores.

**Architecture:** Marginal RNDs (from `RVUtils.ImpliedDistribution` BL results, duck-typed) are coupled into path models (comonotone quantile grid; Gaussian copula on historical correlations). A coupling-agnostic `path_metrics` computes the fly settlement distribution `φ`, move-count tables, and tail slopes; `build_fly_snapshot` assembles Tier-1 marginal metrics + Tier-2/3 path metrics + quality gates; `screener.py` fans that across triples and dates and z-scores the gap series. Data plumbing (Barchart smile fetch, BL extraction) lives only in `notebooks/rv/run_fly_vs_vol_screener.py` and the notebook.

**Tech Stack:** numpy, pandas, scipy.stats.norm, matplotlib; repo infra: `MDP.STIRFutures.STIRFutureOptionMDP`, `RVUtils.ImpliedDistribution`.

## Global Constraints

- Fly sign convention everywhere: `fly_bp = (2*f_belly - f_front - f_back) * 100 = Δ1 − Δ2`; weights on rates `(-1, +2, -1)`.
- Rates in percent inside the module; every `*_bp` output in basis points.
- Tests must run under `conda run -n stir python -m pytest` with no network/db and be fast (no `slow` marker needed).
- Module core must not import MDP or ImpliedDistribution (duck-typed adapter only).
- Quality gates (config defaults): `|forward_residual_bp| ≤ 2.5`, `pre_normalization_mass ≤ 1.02`, `ghost_mass_fraction ≤ 0.02`.
- Reference date for the live run: 2026-07-27; history window start 2025-06-02; strip = `resolve_strip_symbols("2y", as_of)` → SFRU26..SFRM28; six adjacent triples.

---

### Task 1: Package skeleton + `_types.py`

**Files:**
- Create: `RVUtils/FlyVsVol/__init__.py`, `RVUtils/FlyVsVol/_types.py`
- Test: `tests/test_fly_vs_vol_types.py`

**Interfaces (Produces):**
```python
@dataclass(frozen=True)
class ContractMarginal:
    symbol: str
    grid_rate: np.ndarray          # ascending, percent
    cdf: np.ndarray                # nondecreasing, ends ~1
    forward_rate: float            # percent
    as_of: Optional[datetime.date] = None
    forward_residual_bp: float = 0.0
    pre_normalization_mass: float = 1.0
    ghost_mass_fraction: float = 0.0
    warnings: Tuple[str, ...] = ()
    @classmethod
    def from_bl_result(cls, symbol, bl, *, as_of=None) -> "ContractMarginal"
        # bl duck-typed: .strike_grid_rate .rnd_cumulative .input.forward_rate
        # .forward_residual_bp .pre_normalization_mass .ghost_mass_fraction .warnings
    def quantile(self, u) -> np.ndarray        # np.interp(u, cdf, grid_rate)
    def cdf_at(self, k) -> np.ndarray          # np.interp(k, grid_rate, cdf)
    def percentile(self, p: float) -> float    # p in 0..100
    mean: float      # property: trapz of quantile(u) over u=midpoint grid n=4001
    median: float    # percentile(50)
    mode: float      # grid midpoint of max finite-difference density

@dataclass(frozen=True)
class FlyDefinition:
    front: str; belly: str; back: str
    label: str                      # property "SFRU26-SFRZ26-SFRH27"
    symbols: Tuple[str, str, str]   # property

@dataclass(frozen=True)
class FlyVsVolConfig:
    move_size_bp: float = 25.0
    n_quantiles: int = 20001
    n_copula_sims: int = 200_000
    copula_seed: int = 7
    tail_lo: float = 0.15
    tail_hi: float = 0.85
    max_abs_forward_residual_bp: float = 2.5
    max_pre_normalization_mass: float = 1.02
    max_ghost_mass_fraction: float = 0.02
    zscore_window: int = 120
    zscore_min_periods: int = 40
```

- [ ] Step 1: failing tests — synthetic Normal marginal helper (module-level in test file):
```python
def normal_marginal(sym, mu, sigma, n=6001, span=6.0):
    grid = np.linspace(mu - span * sigma, mu + span * sigma, n)
    return ContractMarginal(symbol=sym, grid_rate=grid, cdf=norm.cdf(grid, mu, sigma),
                            forward_rate=mu)

def test_quantile_roundtrip():   # m.cdf_at(m.quantile(u)) ≈ u for u in (0.05..0.95)
def test_moments_normal():       # mean≈mu ±1e-3, median≈mu, mode≈mu ±2*grid_step
def test_from_bl_result_stub():  # SimpleNamespace stub carries all diagnostics through
def test_percentile_bounds():    # percentile(0)=grid[0], percentile(100)=grid[-1]
```
- [ ] Step 2: run, verify FAIL (import error)
- [ ] Step 3: implement `_types.py` + `__init__` exports
- [ ] Step 4: run, verify PASS
- [ ] Step 5: commit `feat(rv): FlyVsVol types + BL adapter`

### Task 2: `coupling.py`

**Files:** Create `RVUtils/FlyVsVol/coupling.py`; Test `tests/test_fly_vs_vol_coupling.py`

**Interfaces (Produces):**
```python
def comonotone_grid(marginals: Sequence[ContractMarginal], n: int = 20001) -> np.ndarray
    # (n, k); row i = [m.quantile(u_i) for m], u midpoint grid (i+0.5)/n
def gaussian_copula_sample(marginals, corr: np.ndarray, n_sim: int = 200_000,
                           rng: Optional[np.random.Generator] = None) -> np.ndarray
    # eigh-clipped Cholesky, z -> norm.cdf -> per-marginal quantile; (n_sim, k)
def historical_corr(panel: pd.DataFrame, *, min_overlap: int = 60) -> pd.DataFrame
    # Pearson corr of panel.diff(); columns with < min_overlap overlap -> NaN
```

- [ ] Step 1: failing tests:
```python
def test_comonotone_normals_closed_form():
    # mus (3.99,4.145,4.225), sigmas (.30,.45,.82): phi = fly + (2s2-s1-s3)z
    # -> mean(phi)≈fly ±0.05bp, P(phi>0)≈Phi(fly/|2s2-s1-s3|) ±0.005
def test_copula_rho1_matches_comonotone():   # quantiles of phi agree ±0.5bp
def test_copula_rho0_wider():                # std(phi_rho0) > std(phi_comonotone)
def test_historical_corr_min_overlap():      # short column -> NaN row/col
```
- [ ] Steps 2-5: red → implement → green → commit `feat(rv): FlyVsVol couplings`

### Task 3: `metrics.py` (path metrics + snapshot builder)

**Files:** Create `RVUtils/FlyVsVol/metrics.py`; Test `tests/test_fly_vs_vol_metrics.py`

**Interfaces (Produces):**
```python
@dataclass(frozen=True)
class PathDistribution:
    e_phi_bp: float; phi_median_bp: float; p_phi_gt0: float
    phi_quantiles_bp: Dict[int, float]          # {1,5,25,50,75,95,99}
    e_d1_bp: float; e_d2_bp: float
    e_n1: float; e_n2: float
    prob_delta: float; p_dn_pos: float; p_dn_neg: float; p_dn_zero: float
    dn_table: Dict[int, float]                  # P(N1-N2=j)
    e_phi_given_dn_bp: Dict[int, float]         # only j with P>=0.005
    tail_slope_upper: float; tail_slope_lower: float   # bp phi per bp back-leg

def path_metrics(rates: np.ndarray, *, move_size_bp=25.0,
                 tail_lo=0.15, tail_hi=0.85) -> PathDistribution
    # rates (n,3); phi=(2c1-c0-c2)*100; N=np.round(d*100/move); tails cut on
    # back-leg empirical quantiles; slopes via lstsq of phi on back rate /100

def build_fly_snapshot(front: ContractMarginal, belly: ContractMarginal,
                       back: ContractMarginal, *, config=FlyVsVolConfig(),
                       corr: Optional[np.ndarray] = None,
                       rng=None, as_of=None) -> FlySnapshot
    # FlySnapshot fields: fly, as_of, forwards, spread1_bp, spread2_bp, fly_bp,
    # fly_mean_bp, fly_median_path_bp, fly_mode_path_bp, tail_rent_bp,
    # heuristic_prob, comonotone: PathDistribution,
    # copula: Optional[PathDistribution] (None unless corr given),
    # quality_ok: bool, quality_flags: Tuple[str, ...], legs: Tuple[...x3]
    # FlySnapshot.to_row() -> flat Dict for DataFrames (no legs/tables;
    # keys: label, as_of, fly_bp, spread1_bp, spread2_bp, fly_mean_bp,
    # fly_median_path_bp, tail_rent_bp, heuristic_prob, prob_delta,
    # heuristic_gap, p_dn_zero, p_dn_pos, phi_p05, phi_p95, phi_iqr_bp,
    # p_phi_gt0, tail_slope_upper, tail_slope_lower, quality_ok, n_flags)
```
`FlySnapshot` lives in `_types.py` (imported by metrics) to keep types together; `heuristic_gap = heuristic_prob - prob_delta`.

- [ ] Step 1: failing tests:
```python
def test_tie_out_mean():          # E[phi] == fly from marginal means ±0.05bp
def test_dn_table_sums_to_1()
def test_dn_mean_consistency():   # sum(j*P(j)) == mean(n1-n2) ±1e-9
def test_symmetric_no_tail_rent():# equal-sigma Normals -> tail_rent ≈ 0 ±0.1bp
def test_tail_slope_normals():    # slope == (2s2-s1-s3)/s3 ±5%
def test_equal_sigmas_degenerate()# phi std < 0.2bp; P(phi>0) in {0,1} per fly sign
def test_quality_gate_flags():    # bad forward_residual -> quality_ok False + flag text
def test_to_row_keys()
```
- [ ] Steps 2-5: red → implement → green → commit `feat(rv): FlyVsVol path metrics + snapshot`

### Task 4: `screener.py`

**Files:** Create `RVUtils/FlyVsVol/screener.py`; Test `tests/test_fly_vs_vol_screener.py`

**Interfaces (Produces):**
```python
def adjacent_triples(symbols: Sequence[str]) -> List[FlyDefinition]   # len = n-2, order kept
def run_fly_screener(marginals_by_symbol: Mapping[str, ContractMarginal],
                     triples: Optional[Sequence[FlyDefinition]] = None, *,
                     config=FlyVsVolConfig(), corr: Optional[pd.DataFrame] = None,
                     as_of=None) -> List[FlySnapshot]
    # triples default: adjacent_triples(sorted-by-input-order keys); missing leg -> skip
    # corr: DataFrame indexed by symbol; per-triple 3x3 slice; NaN -> comonotone only
def screener_table(snapshots: Sequence[FlySnapshot]) -> pd.DataFrame
    # rows = to_row(), index = label, sorted by |tail_rent_bp| desc
def history_zscores(history: pd.DataFrame, cols: Sequence[str], *,
                    window=120, min_periods=40) -> pd.DataFrame
    # history: columns ['as_of','label',*cols]; per-label rolling z ({col}_z)
    # and full-sample z ({col}_z_full); returns copy with added columns
```

- [ ] Step 1: failing tests:
```python
def test_adjacent_triples_count_order()
def test_run_skips_missing_leg()           # 3 symbols + 1 missing -> 1 snapshot
def test_screener_table_index_and_sort()
def test_history_zscores_synthetic():      # constant series -> z 0/NaN; step jump -> big z
def test_history_zscores_grouped():        # two labels z-scored independently
```
- [ ] Steps 2-5: red → implement → green → commit `feat(rv): FlyVsVol screener + history z-scores`

### Task 5: `plotting.py`

**Files:** Create `RVUtils/FlyVsVol/plotting.py`; Test `tests/test_fly_vs_vol_plotting.py`
(Invoke the `dataviz` skill before writing chart code.)

**Interfaces (Produces):**
```python
def plot_fly_distribution(snapshot, *, entry_bp=None, ax=None) -> plt.Axes
    # phi density (from comonotone grid, KDE-free histogram) + entry line + quantile marks
def plot_move_table(snapshot, *, ax=None) -> plt.Axes
    # bar chart of dn_table with heuristic fly/25 annotation
def plot_history_panel(history: pd.DataFrame, label: str, *,
                       cols=("fly_bp", "fly_median_path_bp", "tail_rent_bp",
                             "heuristic_gap"), figsize=(14, 9)) -> plt.Figure
```
- [ ] Steps 1-4: smoke tests (figures/axes created, non-interactive Agg backend), implement, green
- [ ] Step 5: commit `feat(rv): FlyVsVol plotting`

### Task 6: runner `notebooks/rv/run_fly_vs_vol_screener.py`

**Files:** Create `notebooks/rv/run_fly_vs_vol_screener.py` (argparse: `--as-of`, `--start`, `--out-dir notebooks/data/fly_vs_vol`, `--symbols` optional override)

**Consumes:** `STIRFutureOptionMDP(source="BARCHART_STIRFO-QL").fetch_bulk_sabr_smile`,
`SFRImpliedDistribution(anchor_wings=True).extract`, `resolve_strip_symbols("2y", as_of)`,
everything from Tasks 1-4.

Steps: resolve strip → per symbol bulk-fetch smiles over business days → BL-extract per (symbol, date) → `ContractMarginal.from_bl_result` → forwards panel → `historical_corr` → per-date `run_fly_screener` (copula only at `--as-of`) → history DataFrame → `history_zscores` → write `history.parquet`, `screener_<asof>.csv`, print monitor table. Per-(symbol,date) failures logged and skipped; a date needs all 3 legs for its triples only.

- [ ] Implement; verify with a 5-day smoke window; commit `feat(rv): fly-vs-vol screener runner`

### Task 7: notebook `notebooks/rv/fly_vs_vol_screener.ipynb`

Sections: (1) framework intro md; (2) setup; (3) snapshot monitor @ ref date; (4) U26-Z26-H27 deep dive (distribution + move-table plots, decile conditioning); (5) history z-score panels; (6) copula-vs-comonotone; (7) optional joint-stack cell (`extract_joint`, whites, guarded `%%time`); (8) optional linear cross-check cell (`IRSwapsMDP` fly query, commented); (9) findings.

- [ ] Write notebook JSON (no outputs), execute headless to validate, commit `feat(rv): fly-vs-vol notebook`

### Task 8: full run + verification

- [ ] `conda run -n stir python -m pytest tests/test_fly_vs_vol_*.py -v` all green
- [ ] Fast gate touchpoint: `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -k fly_vs_vol`
- [ ] Full screener run @ 2026-07-27 (history 2025-06-02+), artifacts in `notebooks/data/fly_vs_vol/`
- [ ] Commit any final fixes; PR

## Self-Review

Spec coverage: Tier 1/2/3 → Tasks 2-4; quality gates → Task 3; z-scores → Task 4; runner/notebook → Tasks 6-7; joint stack → Task 7 (notebook-only per spec). Types consistent: `ContractMarginal.quantile/cdf_at`, `PathDistribution` names reused verbatim in Tasks 4-6. No placeholders — test bodies listed by name carry explicit assertions in their docstring lines above; implementer = this session with full context.
