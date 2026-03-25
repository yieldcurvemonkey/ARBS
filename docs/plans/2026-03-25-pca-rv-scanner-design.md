# Two-Stage PCA Relative Value Scanner and Backtester

**Date:** 2026-03-25
**References:**
- Standard Chartered "Introducing a relative-value tool for swaps" (Lee, Davies, Fernandez — Aug 2013)
- ASM Quant Macro "Principal Component Analysis ~ Part II" (bquanttrading — Jun 2015)

## Objective

Build a research + backtest system implementing the Standard Chartered two-stage PCA methodology for identifying and structuring RV butterfly trades on the USD SOFR swap curve. The key differentiator is the two-stage PCA: Stage 1 scans the full forward surface for rich/cheap points, Stage 2 runs a separate PCA on the 3 selected trade tenors to derive level-and-slope-neutral weights.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Forward surface | Full scan (spot + forward starts) | Matches SC Figure 12 methodology |
| Architecture | Hybrid: standalone research module + event-driven backtest | Research exploration + realistic curve-based MTM |
| Trade structures | Butterflies only | Core of both reference papers; curve trades deferred |
| Data access | TimeseriesBuilder + IRSwapQuery (CORE cached) | Leverages existing ERIS_EOD_LIVE-RL_BASIC cached data |
| Tenor grid | Fully configurable with SC paper defaults | Flexible for future currencies/curves |
| OU estimation | arbitragelab library | OrnsteinUhlenbeck class with half_life(), ADF via OUModelJurek |
| PCA | sklearn.decomposition.PCA | Direct eigenvector access needed for weight derivation |
| Approach | Monolithic signal module (Approach A) | Self-contained, follows pca_rv_engine.py pattern |

## New Files

| File | Purpose |
|---|---|
| `BT/signals/pca_rv_scanner.py` | Full pipeline: config, surface scan, trade weighting, OU analytics, carry/roll |
| `BT/signals/pca_rv_triggers.py` | Trigger adapter wiring scanner output into QueryDrivenBacktest |
| `notebooks/backtests/pca_rv_butterfly_backtest.ipynb` | Research views + event-driven backtest notebook |

## Modified Files

| File | Change |
|---|---|
| `BT/signals/__init__.py` | Export new modules |
| `requirements.txt` | Add arbitragelab dependency |

---

## Configuration

```python
@dataclass
class PCARVScannerConfig:
    # Curve
    curve: str = "USD-SOFR-1D"
    source: str = "ERIS_EOD_LIVE-RL_BASIC"

    # Tenor grid
    tenors: list[str]  # default: ["1Y","2Y","3Y","4Y","5Y","7Y","8Y","9Y","10Y","15Y","20Y","25Y","30Y"]

    # Forward starts (None = spot)
    forward_starts: list[str | None]  # default: [None,"1M","3M","6M","1Y","2Y","5Y","7Y","10Y"]

    # PCA
    pca_window_days: int = 520       # ~2Y business days
    n_components: int = 3
    use_correlation: bool = False    # SC uses covariance on levels
    pca_input: str = "levels"

    # Z-score
    zscore_lookback_days: int = 520

    # OU (via arbitragelab)
    ou_window_days: int = 520
    investment_horizon_pct: float = 0.875  # 87.5% = ln(8)/mu

    # Carry
    carry_horizon: str = "1M"

    # Trade filtering
    min_zscore_entry: float = 1.5
    min_profit_cost_ratio: float = 2.0
    round_trip_cost_bps: float = 0.5

    # Butterfly categories
    fly_tenor_categories: dict  # e.g., {"front_end": [("2Y","3Y","5Y"), ...], ...}
```

---

## Pipeline Stages

### Stage 1: Full-Curve PCA Scan — `scan_forward_surface()`

**Input:** `dict[str | None, DataFrame[date x tenor]]` (one DataFrame per forward curve)

**Per forward curve:**
1. Rolling PCA: on each date T, fit PCA on covariance matrix of trailing pca_window_days (T-520..T-1). Retain 3 PCs.
2. Reconstruct fair value: `reconstructed[T] = loadings[:,:3] @ (loadings[:,:3].T @ rates[T])`
3. Residual: `actual[T] - reconstructed[T]`
4. Z-score: standardize each tenor's residuals over zscore_lookback_days window.

**Output:** `SurfaceScanResult`
- `zscore_surface: dict[str | None, DataFrame]` — Z-scores per forward curve
- `residuals: dict[str | None, DataFrame]` — raw residuals
- `variance_explained: dict[str | None, DataFrame]` — rolling PC variance shares
- `loadings: dict[str | None, dict[date, ndarray]]` — eigenvectors per date

**Helper:** `zscore_snapshot(result, date) -> DataFrame` — pivots into SC Figure 12 table (rows=tenors, cols=forward starts).

### Stage 2: Trade-Specific PCA Weighting — `compute_fly_weights()`

**Input:** 3 tenors + their historical rates (trailing pca_window_days).

1. Fit PCA on covariance matrix of the 3-tenor subset (independent from Stage 1).
2. Extract PC3 eigenvector loadings: `[eig(1,3), eig(2,3), eig(3,3)]`
3. Normalize to belly: `w_left = eig(1,3)/eig(2,3)`, `w_belly = 1.0`, `w_right = eig(3,3)/eig(2,3)`
4. Verify neutrality:
   - PC1: `eig(1,1)*w_left + eig(2,1) + eig(3,1)*w_right ≈ 0`
   - PC2: `eig(1,2)*w_left + eig(2,2) + eig(3,2)*w_right ≈ 0`

### Candidate Identification — `identify_candidates()`

For each forward curve x fly category:
1. Check Z-score pattern: belly cheap + wings rich (receive fly) or belly rich + wings cheap (pay fly).
2. Filter by `min_zscore_entry` on belly.
3. Compute PCA weights via `compute_fly_weights()`.

**Output:** `list[FlyCandidate]` with tenors, weights, direction, Z-scores, neutrality check.

### Stage 3: OU Analytics — `analyze_candidates()`

**Uses arbitragelab:**
```python
from arbitragelab.optimal_mean_reversion.ou_model import OrnsteinUhlenbeck

ou = OrnsteinUhlenbeck()
ou.fit(fly_series, data_frequency="D")
theta, mu, sigma_sq, _ = ou.optimal_coefficients(fly_series)
half_life = ou.half_life()
```

For each candidate:
1. Build PCA-weighted fly series: `w_left*rate(left) + 1.0*rate(belly) + w_right*rate(right)`
2. Fit OU via arbitragelab → θ (mean), μ (speed), σ, half-life
3. Investment horizon: `ln(8) / μ` (87.5% life = 3 half-lives)
4. Target = θ, stop-loss = current ± 0.5 × |current - θ| in adverse direction
5. Lifetime Z-score: `(current - θ) / (σ / sqrt(2μ))`
6. ADF test via `OUModelJurek.fit(adf_test=True)`

### Stage 4: Carry/Roll-Down

Per candidate:
```
fly_carry = w_left*carry(left) + 1.0*carry(belly) + w_right*carry(right)
fly_roll  = w_left*roll(left)  + 1.0*roll(belly)  + w_right*roll(right)
```

Filter: reject if `expected_profit < min_profit_cost_ratio × round_trip_cost × 3`

**Output:** `list[AnalyzedTrade]` with full analytics per trade.

---

## Trigger Adapter — `BT/signals/pca_rv_triggers.py`

### Pre-computation pattern

Scanner runs over the full historical period **before** the backtest, producing a signal table: `dict[date, list[AnalyzedTrade]]`. Triggers do simple date-based lookups at runtime.

### PCARVEntryTrigger

Fires when a candidate on date T passes all filters:
- `passes_filter = True`
- `|lifetime_zscore| >= min_zscore_entry`
- ADF p-value < 0.05
- No duplicate fly in portfolio

Generates:
```python
IRSwapQuery(
    structure=IRSwapStructure.FLY,
    curve="USD-SOFR-1D",
    tenor=f"{left}/{belly}/{right}",
    structure_kwargs={"weights": (w_left, 1.0, w_right), "bpv": 100_000},
)
```

### PCARVExitTrigger

Fires when open position hits:
- Mean reversion: fly level crosses θ
- Stop-loss: fly level breaches stop-loss
- Max holding period: days held > investment_horizon_days

Generates: `UnwindPositionsAction(match_tag=fly_tag)`

---

## Notebook Structure

`notebooks/backtests/pca_rv_butterfly_backtest.ipynb`

| Section | Content |
|---|---|
| 1. Config & Data | PCARVScannerConfig, load rates + carry/roll via TimeseriesBuilder |
| 2. Stage 1: Surface Scan | Z-score snapshot table (Fig 12), PCA vs actual curve, residual distributions, variance explained |
| 3. Stage 2: Candidates | Candidate table with PCA weights, neutrality verification |
| 4. Stage 3: OU Analytics | Trade summary table (Fig 19/21), fly series with OU bands (Fig 23), fly vs level scatter (Fig 3/16) |
| 5. Backtest | QueryDrivenBacktest, cumulative MTM P&L, trade log, Sharpe/hit rate/drawdown |
| 6. Sensitivity | Vary pca_window, zscore_entry, OU horizon → impact on Sharpe/hit rate |

---

## Data Flow

```
TimeseriesBuilder + IRSwapQuery (CORE cached)
    ↓
rates_panel: dict[fwd_start, DataFrame[date x tenor]]
carry_roll_panel: dict[fwd_start, DataFrame[date x tenor]]
    ↓
Stage 1: scan_forward_surface() → SurfaceScanResult (Z-scores, residuals, loadings)
    ↓
Stage 2: identify_candidates() → list[FlyCandidate] (PCA weights, direction)
    ↓
Stage 3: analyze_candidates() [arbitragelab OU] → list[AnalyzedTrade] (OU params, carry, filter)
    ↓
build_signal_table() → dict[date, list[AnalyzedTrade]]
    ↓
PCARVEntryTrigger + PCARVExitTrigger
    ↓
QueryDrivenBacktest (IRSwapsMDP, EOD curve MTM)
    ↓
mtm_history, realized_pnl, trade_log
```
