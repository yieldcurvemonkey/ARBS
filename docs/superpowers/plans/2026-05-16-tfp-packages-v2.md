# TFP Swap Spread Packages V2 — OU Exits, PCA Weighting, Full Universe

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the TFP swap spread packages backtest to trade all C(6,2)=15 curves and C(6,3)=20 flies across the regression tenor universe (2Y,3Y,5Y,7Y,10Y,30Y), with OU-calibrated mean-reversion exits and optional PCA-weighted position sizing.

**Architecture:** Three layers: (1) a signal module addition (`tfp_packages.py`) that generates the full universe of deviation-differential signals with OU exit calibration, (2) a PCA weighting module that runs Ledoit-Wolf shrunk covariance on deviation-change returns and solves for inverse-vol or MSR weights, (3) a notebook that ties it together — vectorized preview over all 35 packages, PCA weight overlay, then QueryDrivenBacktest on the top-N. The notebook replaces `tfp_swap_spread_packages_backtest.ipynb`.

**Tech Stack:** numpy, pandas, sklearn (LedoitWolf, PCA), QuantLib (calendar), existing BT framework (QueryDrivenBacktest, TimeGrid, DateTrigger), existing RVUtils (mean_reversion.py OU calibration, df_based_pca_risk_model.py CurvePCAModel)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `BT/signals/tfp_packages.py` | **Create** | Package universe generation, OU-exit signal engine, PCA weight computation |
| `notebooks/backtests/tfp_swap_spread_packages_backtest.ipynb` | **Rewrite** | Full notebook: config, signals, preview, QDB backtest, tearsheet |

The signal module is pure-Python (no MDP dependencies) — it takes the TFP `history` DataFrame as input and produces signals + events. The notebook handles data loading, backtest orchestration, and visualization.

---

### Task 1: Create `BT/signals/tfp_packages.py` — Universe + Signal Engine

**Files:**
- Create: `BT/signals/tfp_packages.py`

- [ ] **Step 1: Define package universe generator**

```python
# BT/signals/tfp_packages.py
"""
TFP swap spread package universe: all curves and flies from the
regression tenor set, with OU-calibrated exits and optional PCA weighting.
"""
from __future__ import annotations
import datetime, itertools, logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.signals.tfp_swap_spread import REGRESSION_TENORS, CT_MAP

logger = logging.getLogger(__name__)

CURVE_TENORS = REGRESSION_TENORS  # ['2Y','3Y','5Y','7Y','10Y','30Y']

@dataclass(frozen=True)
class Package:
    name: str
    legs: Tuple[str, ...]
    weights: Tuple[int, ...]   # signal weights: curves [-1,+1], flies [+1,-2,+1]
    kind: str                  # 'curve' or 'fly'

def generate_universe(tenors: Optional[List[str]] = None) -> List[Package]:
    """Generate all C(n,2) curves and C(n,3) flies from *tenors*."""
    if tenors is None:
        tenors = list(CURVE_TENORS)
    pkgs: List[Package] = []
    # Curves: all pairs
    for front, back in itertools.combinations(tenors, 2):
        f_n = front.replace("Y", "")
        b_n = back.replace("Y", "")
        pkgs.append(Package(
            name=f"{f_n}s{b_n}s",
            legs=(front, back),
            weights=(-1, +1),
            kind="curve",
        ))
    # Flies: all triples
    for front, belly, back in itertools.combinations(tenors, 3):
        f_n = front.replace("Y", "")
        m_n = belly.replace("Y", "")
        b_n = back.replace("Y", "")
        pkgs.append(Package(
            name=f"{f_n}s{m_n}s{b_n}s",
            legs=(front, belly, back),
            weights=(+1, -2, +1),
            kind="fly",
        ))
    return pkgs
```

- [ ] **Step 2: Add OU-calibrated signal function**

Append to the same file:

```python
def _ou_params(series: pd.Series) -> dict:
    """Calibrate OU process: dX = theta(mu - X)dt + sigma dW.
    Returns dict with mu, theta, sigma, half_life, or NaN on failure."""
    y = series.dropna().astype(float)
    if len(y) < 20:
        return {"mu": np.nan, "theta": np.nan, "sigma": np.nan, "half_life": np.nan}
    y0 = y.shift(1).dropna()
    y1 = y.loc[y0.index]
    X = np.column_stack([np.ones(len(y0)), y0.values])
    try:
        a, b = np.linalg.lstsq(X, y1.values, rcond=None)[0]
    except Exception:
        return {"mu": np.nan, "theta": np.nan, "sigma": np.nan, "half_life": np.nan}
    if not (0 < b < 1) or not np.isfinite(b):
        return {"mu": np.nan, "theta": np.nan, "sigma": np.nan, "half_life": np.nan}
    mu = a / (1 - b)
    theta = -np.log(b)
    eps = y1.values - (a + b * y0.values)
    sigma = np.sqrt(np.var(eps, ddof=1) * 2 * theta / (1 - b**2))
    half_life = np.log(2) / theta
    return {"mu": float(mu), "theta": float(theta), "sigma": float(sigma), "half_life": float(half_life)}


def compute_package_signals(
    history: pd.DataFrame,
    packages: List[Package],
    *,
    z_window: int = 60,
    z_entry: float = 1.5,
    ou_exit: bool = True,
    ou_window: int = 252,
    fixed_z_exit: float = 0.5,
    max_hold: int = 60,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute deviation diffs, z-scores, and signals for all packages.

    OU exit: on each day a position is held, recalibrate OU on the trailing
    dev_diff series.  Exit when the current level crosses the OU-implied
    long-run mean (mu).  Fallback to fixed_z_exit if OU calibration fails.

    Returns (dev_diffs, zscores, signals) DataFrames with package names as columns.
    """
    dev_diffs = pd.DataFrame(index=history.index)
    zscores = pd.DataFrame(index=history.index)
    signals = pd.DataFrame(index=history.index)

    for pkg in packages:
        col_ok = all(f"dev_{leg}" in history.columns for leg in pkg.legs)
        if not col_ok:
            continue

        dd = sum(w * history[f"dev_{leg}"] for w, leg in zip(pkg.weights, pkg.legs))
        dev_diffs[pkg.name] = dd

        mu = dd.rolling(z_window, min_periods=z_window // 2).mean()
        sigma = dd.rolling(z_window, min_periods=z_window // 2).std()
        z = (dd - mu) / sigma.replace(0, np.nan)
        zscores[pkg.name] = z

        # Signal generation with OU exit
        sig = np.zeros(len(z), dtype=np.int8)
        pos = 0
        hold_count = 0

        for i in range(len(z)):
            v = z.iloc[i]
            if np.isnan(v):
                sig[i] = 0; pos = 0; hold_count = 0; continue

            if pos == 0:
                if v > z_entry:
                    pos = -1; hold_count = 0
                elif v < -z_entry:
                    pos = +1; hold_count = 0
            else:
                hold_count += 1
                should_exit = False

                # Max holding period stop
                if hold_count >= max_hold:
                    should_exit = True

                # OU exit: check if dev_diff crossed OU long-run mean
                elif ou_exit and i >= ou_window:
                    ou = _ou_params(dd.iloc[max(0, i - ou_window):i + 1])
                    if np.isfinite(ou["mu"]):
                        current = dd.iloc[i]
                        if pos == +1 and current >= ou["mu"]:
                            should_exit = True
                        elif pos == -1 and current <= ou["mu"]:
                            should_exit = True

                # Fallback: fixed z-score exit
                if not should_exit and not ou_exit:
                    if pos == -1 and v <= fixed_z_exit:
                        should_exit = True
                    elif pos == +1 and v >= -fixed_z_exit:
                        should_exit = True

                if should_exit:
                    pos = 0; hold_count = 0

            sig[i] = pos

        signals[pkg.name] = sig

    return dev_diffs, zscores, signals
```

- [ ] **Step 3: Add PCA weighting function**

Append to the same file:

```python
def compute_pca_weights(
    dev_diffs: pd.DataFrame,
    *,
    cov_window: int = 90,
    n_components: int = 3,
    method: str = "inverse_vol",
) -> pd.DataFrame:
    """Compute PCA-informed position weights for active packages.

    Runs rolling Ledoit-Wolf shrunk covariance on daily changes of
    deviation-differentials, then computes weights via one of:
      - 'inverse_vol':  w_i = 1 / sigma_i, normalized to sum to 1
      - 'msr':          w propto Sigma^{-1} mu  (maximum Sharpe ratio)
      - 'gmv':          w propto Sigma^{-1} 1   (global min variance)
      - 'equal':        w_i = 1/N (no PCA, baseline)

    Returns DataFrame of weights indexed by date, columns = package names.
    """
    from sklearn.covariance import LedoitWolf

    changes = dev_diffs.diff().dropna(how="all")
    cols = changes.columns.tolist()
    n = len(cols)
    weight_records = []

    for i in range(cov_window, len(changes)):
        window = changes.iloc[i - cov_window:i][cols].dropna(axis=1, how="any")
        active_cols = window.columns.tolist()
        if len(active_cols) < 2:
            weight_records.append({c: 1.0 / n for c in cols})
            continue

        try:
            lw = LedoitWolf().fit(window.values.astype(float))
            cov = lw.covariance_
        except Exception:
            cov = np.cov(window.values.T)

        if method == "inverse_vol":
            vols = np.sqrt(np.diag(cov))
            vols = np.where(vols > 0, vols, 1e-8)
            raw = 1.0 / vols
        elif method == "gmv":
            try:
                inv_cov = np.linalg.inv(cov)
                raw = inv_cov @ np.ones(len(active_cols))
            except np.linalg.LinAlgError:
                raw = np.ones(len(active_cols))
        elif method == "msr":
            mu = window.mean().values
            try:
                inv_cov = np.linalg.inv(cov)
                raw = inv_cov @ mu
            except np.linalg.LinAlgError:
                raw = mu
        else:
            raw = np.ones(len(active_cols))

        raw = np.abs(raw)
        total = raw.sum()
        if total > 0:
            raw = raw / total
        else:
            raw = np.ones(len(active_cols)) / len(active_cols)

        row = {c: 0.0 for c in cols}
        for j, c in enumerate(active_cols):
            row[c] = float(raw[j])
        weight_records.append(row)

    idx = changes.index[cov_window:]
    return pd.DataFrame(weight_records, index=idx)


def extract_package_events(
    signals: pd.DataFrame,
    pkg: Package,
    bt_start,
    bt_end,
) -> List[dict]:
    """Extract entry/exit events for a single package from the signals DataFrame."""
    col = pkg.name
    if col not in signals.columns:
        return []
    sig = signals[col].loc[bt_start:bt_end]
    dates = [d.date() if hasattr(d, "date") else d for d in sig.index]
    vals = sig.values
    events = []
    prev = 0; entry_date = None; direction = 0

    for i in range(len(vals)):
        cur = int(vals[i])
        if prev == 0 and cur != 0:
            entry_date = dates[i]; direction = cur
        elif prev != 0 and cur == 0:
            events.append(dict(
                entry_date=entry_date, exit_date=dates[i],
                direction=direction, pkg=pkg.name,
                tag=f"tfp-pkg-{pkg.name}-{entry_date}",
                legs=pkg.legs, weights=pkg.weights,
            ))
            entry_date = None; direction = 0
        elif prev != 0 and cur != 0 and cur != prev:
            events.append(dict(
                entry_date=entry_date, exit_date=dates[i],
                direction=direction, pkg=pkg.name,
                tag=f"tfp-pkg-{pkg.name}-{entry_date}",
                legs=pkg.legs, weights=pkg.weights,
            ))
            entry_date = dates[i]; direction = cur
        prev = cur

    if entry_date is not None:
        events.append(dict(
            entry_date=entry_date, exit_date=dates[-1],
            direction=direction, pkg=pkg.name,
            tag=f"tfp-pkg-{pkg.name}-{entry_date}",
            legs=pkg.legs, weights=pkg.weights,
        ))
    return events
```

- [ ] **Step 4: Add vectorized P&L preview function**

Append to the same file:

```python
def vectorized_preview(
    history: pd.DataFrame,
    packages: List[Package],
    signals: pd.DataFrame,
    dev_diffs: pd.DataFrame,
    bt_start,
    bt_end,
    *,
    pca_weights: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Fast vectorized P&L for all packages. Returns summary DataFrame."""
    h_bt = history.loc[bt_start:bt_end]
    results = []

    for pkg in packages:
        if pkg.name not in signals.columns:
            continue
        sig = signals[pkg.name].loc[bt_start:bt_end].reindex(h_bt.index).fillna(0)

        d_mmss = sum(
            w * h_bt[f"mmss_{leg}"].diff()
            for w, leg in zip(pkg.weights, pkg.legs)
            if f"mmss_{leg}" in h_bt.columns
        )
        daily = -sig * d_mmss
        daily = daily.fillna(0)

        # Apply PCA weights if provided
        if pca_weights is not None and pkg.name in pca_weights.columns:
            pw = pca_weights[pkg.name].reindex(h_bt.index).ffill().fillna(1.0)
            daily = daily * pw * len(packages)  # scale up since weights sum to 1

        cum = daily.cumsum()
        sh = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0
        mdd = (cum - cum.cummax()).min()
        n_trades = ((sig != 0) & (sig.shift(1).fillna(0) == 0)).sum()

        # OU stats on dev_diff
        dd = dev_diffs[pkg.name].loc[bt_start:bt_end].dropna()
        ou = _ou_params(dd) if len(dd) > 30 else {"half_life": np.nan, "theta": np.nan}

        results.append(dict(
            Package=pkg.name, Kind=pkg.kind, Legs="/".join(pkg.legs),
            Sharpe=round(sh, 3), Total_bp=round(cum.iloc[-1], 1),
            MaxDD_bp=round(mdd, 1), Trades=int(n_trades),
            OU_HL=round(ou["half_life"], 0) if np.isfinite(ou["half_life"]) else np.nan,
        ))

    return pd.DataFrame(results).sort_values("Sharpe", ascending=False)
```

- [ ] **Step 5: Verify module imports**

```bash
conda run -n stir python -c "from BT.signals.tfp_packages import generate_universe, compute_package_signals, compute_pca_weights, vectorized_preview; u = generate_universe(); print(f'{len(u)} packages: {len([p for p in u if p.kind==\"curve\"])} curves, {len([p for p in u if p.kind==\"fly\"])} flies')"
```

Expected: `35 packages: 15 curves, 20 flies`

---

### Task 2: Rewrite `tfp_swap_spread_packages_backtest.ipynb`

**Files:**
- Rewrite: `notebooks/backtests/tfp_swap_spread_packages_backtest.ipynb`

The notebook structure:

1. **Imports & Config** — `bt_config` dict with `use_pca_weights`, `ou_exit`, `pca_method` flags
2. **Load TFP History** — from cache
3. **Generate Universe** — `generate_universe()` → 15 curves + 20 flies
4. **Compute Signals** — `compute_package_signals()` with OU exit
5. **PCA Weights** (optional) — `compute_pca_weights()` with Ledoit-Wolf
6. **Vectorized Preview** — `vectorized_preview()` over all 35 packages, display top-20
7. **Preview Equity Curves** — plot top-10 with `make_secondary_axis_plot`
8. **OU Diagnostics** — half-life and mean estimates for top packages
9. **QueryDrivenBacktest** — run top-N through full engine with financing
10. **Results** — MTM, Sharpe, max DD, by-package attribution
11. **Tearsheet**

- [ ] **Step 1: Write the notebook cells**

Create the notebook with the cell structure above, using `bt_config` dict:

```python
bt_config = dict(
    signal_start  = datetime.date(2020, 6, 1),
    bt_start      = datetime.date(2021, 6, 1),
    bt_end        = datetime.date(2026, 5, 14),
    z_window      = 60,
    z_entry       = 1.5,
    ou_exit       = True,         # OU mean-reversion exit
    ou_window     = 252,          # OU calibration lookback
    fixed_z_exit  = 0.5,          # fallback if ou_exit=False
    max_hold      = 60,           # max holding period (days)
    use_pca_weights = False,      # PCA-weighted sizing
    pca_method    = 'inverse_vol',# 'inverse_vol', 'gmv', 'msr', 'equal'
    pca_cov_window = 90,          # Ledoit-Wolf covariance window
    top_n         = 5,            # how many packages to run through QDB
    risk_bpv      = 100_000,
    unwind_fee_bps = 0.5,
    specialness_bps = 10.0,
    irs_source    = 'ERIS_EOD_LIVE-RL_BASIC',
    frb_source    = 'USTS_FEDINVEST_WSJ_LIVE-QL',
    curve_name    = 'USD-SOFR-1D',
    cache_path    = '...',
)
```

- [ ] **Step 2: Run the notebook via nbconvert**

```bash
cd notebooks/backtests && conda run -n stir jupyter nbconvert --to notebook --execute tfp_swap_spread_packages_backtest.ipynb --output tfp_swap_spread_packages_v2_executed.ipynb --ExecutePreprocessor.timeout=900
```

Expected: 0 errors, preview table showing 35 packages ranked by Sharpe.

- [ ] **Step 3: Verify OU exits differ from fixed exits**

Run with `ou_exit=True` and `ou_exit=False`, compare trade counts and holding periods. OU exits should produce shorter average hold times (exits when dev_diff crosses OU mu, not fixed z threshold).

---

### Task 3: Run vectorized preview and report results

- [ ] **Step 1: Run a standalone script to get the preview table**

```bash
conda run -n stir python -u _run_preview.py 2>&1 | grep -v "FETCHING\|PRICING\|DuckDB"
```

This produces the top-20 packages ranked by Sharpe, with OU half-life for each.

- [ ] **Step 2: Compare OU exit vs fixed exit**

Show side-by-side metrics for the top 5 packages under both exit regimes.

- [ ] **Step 3: Show PCA weights impact**

Run with `use_pca_weights=True` (inverse_vol method) and compare aggregate Sharpe.
