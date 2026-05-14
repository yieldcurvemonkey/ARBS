# SFR Kink-Fade Live Screener — Design Spec

**Date:** 2026-05-14
**Status:** Draft

## Purpose

A live screener that surfaces actionable BF_6M kink-fading signals using the same logic, filters, and thresholds that produced the 0.83 Sharpe backtest config. Consumed via a Python module + Jupyter notebook.

## Production Config (from backtest)

```
Structure:         BF_6M (6-month gap butterfly)
Direction:         buy_kink only (belly rate too high, fade it down)
Strip region:      Reds (SFR5–8 bellies) as primary, greens/whites as context
Signal:            z-score, 60-day window, entry at |z| > 2.0
Exit:              Mean-reversion (z→0), 2sd stop, 22d max hold
Filters:           FOMC 5d blackout, HL gating (3–120d), IMM roll 3d blackout
Max concurrent:    3 positions
```

## Architecture

### Module: `RVUtils/SFRKinkFadeScreener/`

```
RVUtils/SFRKinkFadeScreener/
├── __init__.py
├── screener.py          # build_snapshot() entry point
└── _display.py          # notebook rendering helpers (tables, charts)
```

Follows the existing screener pattern (`SFRConvexScreener`, `STIRAsymmetricScreener`): config dataclass → `build_snapshot(config)` → snapshot dataclass with `.to_dataframe()` / `.to_dict()`.

### Data Flow

```
load_rate_panel()          ← existing, cached in Barchart STIR pipeline
    ↓
compute_kink_curves()      ← existing, from sfr_kink_fade.py
compute_zscore_ts()        ← existing
compute_rolling_halflife() ← existing
    ↓
build_snapshot()           ← NEW: packages analytics into screener snapshot
    ↓
KinkFadeScreenerSnapshot   ← NEW: dataclass with per-fly results + global context
    ↓
Notebook display           ← NEW: formatted tables + charts
```

No new computation logic. The screener is a thin wrapper over the existing `sfr_kink_fade.py` analytics pipeline.

## Data Model

### `KinkFadeScreenerConfig`

```python
@dataclass
class KinkFadeScreenerConfig:
    source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    n_contracts: int = 12
    zscore_window: int = 60
    vol_window: int = 20
    halflife_window: int = 120
    lookback_days: int = 180       # how much history to load for z-score warmup
    entry_zscore: float = 2.0
    fomc_blackout_days: int = 5
    roll_blackout_days: int = 3
    hl_min: float = 3.0
    hl_max: float = 120.0
```

### `FlyResult` (per-structure row)

```python
@dataclass
class FlyResult:
    structure_id: str              # "SFR5/SFR7/SFR9"
    belly_rank: int                # 7 (the belly contract rank)
    region: str                    # "reds" | "whites" | "greens"

    # Signal
    level_bp: float                # current BF level
    zscore: float                  # 60d z-score
    percentile: float              # time-series percentile [0,1]
    xsection_rank: float           # cross-sectional rank [0,1]
    direction: str                 # "buy_kink" | "sell_kink"

    # Mean-reversion
    half_life_days: float          # rolling OU half-life
    vol_ann: float                 # annualized realized vol
    roll_bp: float                 # carry/roll

    # Filter status
    entry_eligible: bool           # passes ALL filters for production config
    filters: Dict[str, bool]       # per-filter pass/fail breakdown:
                                   #   z_threshold, direction, region,
                                   #   fomc_blackout, roll_blackout, hl_gating

    # Context
    days_since_last_entry: Optional[int]  # None if never entered
    zscore_1d_change: float        # z-score momentum (today vs yesterday)
    level_1d_change: float         # level change in bp
```

### `KinkFadeScreenerSnapshot`

```python
@dataclass
class KinkFadeScreenerSnapshot:
    as_of: datetime.date
    results: List[FlyResult]       # all BF_6M flies, ranked by |z|

    # Global context
    strip_rates: Dict[str, float]  # SFR1..SFR12 rates
    days_to_fomc: int
    days_to_imm_roll: int
    fomc_blackout_active: bool
    roll_blackout_active: bool

    # Summary
    n_actionable: int              # flies passing all filters
    actionable_ids: List[str]      # structure_ids of actionable flies

    config: KinkFadeScreenerConfig

    def to_dataframe(self) -> pd.DataFrame: ...
    def to_dict(self) -> Dict[str, Any]: ...
```

## Notebook: `notebooks/rv/sfr_kink_fade_screener.ipynb`

### Cell Structure

1. **Setup** — imports, autoreload
2. **Config** — editable `KinkFadeScreenerConfig` cell
3. **Run Screener** — `snapshot = build_snapshot(config)`
4. **Signal Dashboard** — primary output table:
   - Color-coded rows: green = entry eligible, yellow = approaching (z > 1.5), gray = inactive
   - Columns: structure, region, z-score, level, direction, HL, filters, eligibility
   - Sorted by |z| descending
   - Reds highlighted, whites/greens dimmed
5. **Strip Visualization** — strip rate line chart with BF_6M kink locations overlaid as colored markers
6. **Z-Score Time Series** — line chart of z-scores for reds flies over trailing 120 days, with ±1.5 and ±2.0 threshold bands
7. **Filter Status Panel** — compact view: FOMC (N days, active/clear), IMM roll (N days, active/clear), HL range for each fly
8. **Historical Context** — last 10 entries from backtest signal table (when did the strategy last fire on each fly?)

### Display Helpers (`_display.py`)

```python
def render_dashboard_table(snapshot: KinkFadeScreenerSnapshot) -> pd.DataFrame:
    """Styled DataFrame for notebook display with color coding."""

def render_strip_chart(snapshot: KinkFadeScreenerSnapshot, ax=None):
    """Strip rates with BF_6M kink markers."""

def render_zscore_chart(snapshot: KinkFadeScreenerSnapshot, ax=None):
    """Trailing z-score time series for reds flies."""

def render_filter_panel(snapshot: KinkFadeScreenerSnapshot):
    """Compact filter status display."""
```

## Implementation Notes

- `build_snapshot()` calls `load_rate_panel()` with `end="live"` to get the latest available data. If live data is unavailable, falls back to the most recent cached date and flags the staleness in `snapshot.run_warnings`.
- Z-score requires `lookback_days` of history before the as_of date. Default 180 days provides 120 days of z-score warmup after the 60-day rolling window stabilizes.
- The screener computes ALL BF_6M flies across the strip (8 structures for 12 contracts), not just reds. Reds are highlighted as primary; whites/greens provide context for cross-sectional interpretation.
- `entry_eligible` is True only when ALL of: direction == buy_kink, region == reds, |z| >= 2.0, FOMC clear, roll clear, HL in range. The `filters` dict shows exactly which filter(s) block entry for non-eligible flies.
- No position state tracking — the screener is stateless. It shows what's actionable NOW. Position management remains in the backtest/execution layer.

## Files to Create

| File | Purpose |
|---|---|
| `RVUtils/SFRKinkFadeScreener/__init__.py` | Package init, re-exports |
| `RVUtils/SFRKinkFadeScreener/screener.py` | `build_snapshot()`, config, snapshot, FlyResult dataclasses |
| `RVUtils/SFRKinkFadeScreener/_display.py` | Notebook rendering: styled tables, strip chart, z-score chart, filter panel |
| `notebooks/rv/sfr_kink_fade_screener.ipynb` | Interactive screener notebook |

## Files to Modify

None. The screener imports from existing modules (`sfr_kink_fade.py`, `sfr_cal_spread_rv.py`, `IRSwapsMDP`) but doesn't modify them.

## Dependencies

All existing:
- `BT/signals/sfr_kink_fade.py` — analytics pipeline
- `BT/signals/sfr_cal_spread_rv.py` — `load_rate_panel()`, `compute_fly_curve()`
- `MDP/IRSwaps/IRSwapsMDP.py` — market data provider
- `TB/TimeseriesBuilder.py` — timeseries cache
