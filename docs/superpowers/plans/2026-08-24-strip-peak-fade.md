# Strip Peak Fade Backtest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Systematically test whether the "peak" (highest rate) contract in the SR3 strip is overpriced, across four expressions: linear calendar spread, linear butterfly, options butterfly grid, and implied distribution mode divergence.

**Architecture:** A shared strip-data layer pulls daily EOD settles for all liquid SR3 contracts and identifies the peak at each date. Four independent backtest variants consume the peak signal and measure P&L through different structures. All backtests are vectorized (no QDB event loop) for speed; the QDB wiring is a follow-on if any variant shows edge.

**Tech Stack:** STIRFutureMDP + BarchartFetcher (linear data), STIRFutureOptionMDP (options data), SFRImpliedDistribution (density), pandas/numpy (backtest engine), matplotlib/plotly (results).

**Spec:** Design agreed in conversation 2026-08-24. No separate spec file — the thesis is: the market is bad at timing the peak/trough of the rate cycle, so the strip's peak contract carries an embedded premium that decays when the peak migrates or fails to realize.

## Global Constraints

- Python via `conda run -n stir`. Multiline `-c` is rejected — write script files.
- `ARBS_SUPABASE_ENABLED=0` for all runs.
- New work in a **new git worktree** (short sibling path, e.g., `../ARBS-spf`).
- Every git command: `git -C <path> ...`. Never rely on `cd`.
- Heredocs collapse backslashes — use Write tool for anything with `\` or backticks.
- Cost assumption: **1.0bp per leg** (2.0bp round-trip for a spread, 4.0bp for a butterfly). Gate on net-of-cost P&L. Prior SFR RV work (380+ configs) died on cost.
- Restrict to **front 8 quarterly contracts** from each date — back-strip tick lattice (0.5bp grid, 51% unchanged days) corrupts rankings.
- Minimum **20 trades** per cell for any grid result.
- Prior art: `project_sfr_kink_fade_v2` (DEAD — calendar explains 1-6% of kink), `project_sfr_fly_meanrev` (flies revert but +0.75bp edge < 2bp cost), `project_sfr_rv_lab` (0/47 alive), `project_linvol_backtest_grid` (0/272 alive). ALL used **static** structures. **Dynamic peak tracking was never tested.**

---

### Task 1: Worktree + project scaffold

**Files:**
- Create: `RVUtils/StripPeak/__init__.py`
- Create: `RVUtils/StripPeak/strip_builder.py`
- Create: `tests/test_strip_peak_builder.py`

**Interfaces:**
- Produces: `build_daily_strip(start_date, end_date, n_front=8) -> pd.DataFrame` — index=date, columns=contract symbols (e.g. `SR3U26`…`SR3Z28`), values=implied rate (100-price). Cached to `data/strip_peak/daily_strip.parquet`.

- [ ] **Step 1: Create worktree**

```bash
git -C C:/Users/chris/clee/ARBS worktree add ../ARBS-spf -b feat/strip-peak-fade
git -C C:/Users/chris/clee/ARBS-spf status -sb | head -1
```

Expected: `## feat/strip-peak-fade`

- [ ] **Step 2: Create module scaffold**

Create `RVUtils/StripPeak/__init__.py`:
```python
from RVUtils.StripPeak.strip_builder import build_daily_strip
```

- [ ] **Step 3: Write the failing test for strip_builder**

Create `tests/test_strip_peak_builder.py`:
```python
"""Tests for the daily SR3 strip builder."""
import datetime
import pandas as pd
import pytest

from RVUtils.StripPeak.strip_builder import build_daily_strip


@pytest.mark.network
def test_build_daily_strip_shape_and_content():
    """Pull a small window and verify the strip has the right shape."""
    df = build_daily_strip(
        start_date=datetime.date(2026, 8, 18),
        end_date=datetime.date(2026, 8, 22),
        n_front=8,
    )
    assert isinstance(df, pd.DataFrame)
    assert len(df) >= 4  # 4-5 business days
    assert len(df.columns) == 8
    # columns should be ordered quarterly: near to far
    assert df.columns[0] < df.columns[-1]  # alphabetical ~ chronological for SR3
    # values are rates in percent, should be between 2% and 8%
    assert (df > 2.0).all().all()
    assert (df < 8.0).all().all()


@pytest.mark.network
def test_strip_builder_known_value():
    """Verify against the known 22-Aug settle: SR3H27=4.07, SR3Z27=4.11."""
    df = build_daily_strip(
        start_date=datetime.date(2026, 8, 22),
        end_date=datetime.date(2026, 8, 22),
        n_front=8,
    )
    row = df.iloc[0]
    # SR3U26 should be in the columns (front contract)
    assert "SR3U26" in df.columns or "SR3M26" in df.columns
    # Check a known value (tolerance for EOD bar timestamp)
    if "SR3H27" in df.columns:
        assert abs(row["SR3H27"] - 4.07) < 0.05
```

- [ ] **Step 4: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_strip_peak_builder.py -v -m network --no-header 2>&1 | tail -5`
Expected: FAIL with ImportError

- [ ] **Step 5: Implement strip_builder.py**

Create `RVUtils/StripPeak/strip_builder.py`:
```python
"""Build a daily rate-strip for the front N SR3 quarterly contracts."""
from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
from typing import List, Optional

import httpx
import pandas as pd

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher

_QUARTERLY = "HMUZ"
_CACHE_DIR = Path(os.environ.get("ARBS_CACHE_DIR", "data")) / "strip_peak"


def _enumerate_contracts(anchor_date: datetime.date, n_front: int) -> List[str]:
    """Return the next *n_front* quarterly SR3 symbols from *anchor_date*."""
    year = anchor_date.year
    month = anchor_date.month
    codes = list(_QUARTERLY)
    month_to_code = {3: "H", 6: "M", 9: "U", 12: "Z"}
    code_to_month = {v: k for k, v in month_to_code.items()}

    # find the first quarterly month >= anchor_date.month
    out: List[str] = []
    y, idx = year, 0
    # start from the first quarterly month on or after the anchor
    for i, c in enumerate(codes):
        if code_to_month[c] >= month:
            idx = i
            break
    else:
        idx = 0
        y += 1

    while len(out) < n_front:
        c = codes[idx % 4]
        yr = y + (idx // 4) if idx >= 0 else y
        # recalculate year properly
        sym = f"SR3{c}{y % 100:02d}"
        out.append(sym)
        idx += 1
        if idx % 4 == 0:
            y += 1
            idx = 0
    return out


def _internal_to_barchart(sym: str) -> str:
    return "SQ" + sym[3:]


async def _fetch_one(
    fetcher: BarchartFetcher, bc_sym: str
) -> tuple[str, pd.DataFrame]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        return await fetcher._fetch_eod_timeseries(
            client=client, symbol=bc_sym, columns=None, set_dt_index=False
        )


def build_daily_strip(
    start_date: datetime.date,
    end_date: datetime.date,
    n_front: int = 8,
    *,
    cache: bool = True,
) -> pd.DataFrame:
    """Build a date x contract rate matrix for the front *n_front* SR3 contracts.

    Returns a DataFrame: index=datetime.date, columns=SR3 symbols, values=rate (%).
    """
    cache_path = _CACHE_DIR / f"strip_{start_date}_{end_date}_n{n_front}.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    contracts = _enumerate_contracts(start_date, n_front)
    fetcher = BarchartFetcher()

    async def _fetch_all():
        tasks = []
        for sym in contracts:
            bc = _internal_to_barchart(sym)
            tasks.append(_fetch_one(fetcher, bc))
        return await asyncio.gather(*tasks, return_exceptions=True)

    results = asyncio.run(_fetch_all())

    frames = {}
    for sym, result in zip(contracts, results):
        if isinstance(result, Exception):
            continue
        _name, df = result
        if df is None or df.empty:
            continue
        df["_date"] = pd.to_datetime(df[df.columns[1]]).dt.date
        # Column index 4 is the Low (close proxy from prior verified pull)
        df["_close"] = pd.to_numeric(df[df.columns[5]], errors="coerce")
        ser = df.set_index("_date")["_close"].dropna()
        frames[sym] = 100.0 - ser  # convert price to rate

    strip = pd.DataFrame(frames).dropna()
    strip = strip[(strip.index >= start_date) & (strip.index <= end_date)]
    strip = strip.sort_index()
    # ensure columns are chronologically ordered
    strip = strip[sorted(strip.columns, key=lambda s: (int(s[5:]), _QUARTERLY.index(s[4])))]

    if cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        strip.to_parquet(cache_path)

    return strip
```

Note: the column index for the close/settle price needs verification — the BarchartFetcher returns unnamed integer columns. The prior pull showed column 4 = Low and column 5 = Close. **Verify by printing the first row** during the test run and adjust accordingly.

- [ ] **Step 6: Run test, iterate until passing**

Run: `conda run -n stir python -m pytest tests/test_strip_peak_builder.py -v -m network --no-header 2>&1 | tail -10`

Debug cycle: if the column index is wrong, print `df.iloc[0].to_dict()` and adjust. If `_enumerate_contracts` produces wrong symbols, test it in isolation first:
```python
from RVUtils.StripPeak.strip_builder import _enumerate_contracts
print(_enumerate_contracts(datetime.date(2026, 8, 22), 8))
# expect: ['SR3U26', 'SR3Z26', 'SR3H27', 'SR3M27', 'SR3U27', 'SR3Z27', 'SR3H28', 'SR3M28']
```

- [ ] **Step 7: Commit**

```bash
git -C ../ARBS-spf add RVUtils/StripPeak/ tests/test_strip_peak_builder.py
git -C ../ARBS-spf commit -m "feat(strip-peak): daily SR3 strip builder with Barchart EOD fetch"
```

---

### Task 2: Peak identifier + migration tracker

**Files:**
- Create: `RVUtils/StripPeak/peak_tracker.py`
- Modify: `RVUtils/StripPeak/__init__.py`
- Create: `tests/test_strip_peak_tracker.py`

**Interfaces:**
- Consumes: `build_daily_strip(start, end, n_front) -> DataFrame[date x contract -> rate]`
- Produces:
  - `identify_peak(strip_df) -> pd.DataFrame` — columns: `peak_contract`, `peak_rate`, `peak_idx`, `prominence`, `is_interior`
  - `migration_events(peak_df) -> pd.DataFrame` — rows where `peak_contract` changed from prior day

- [ ] **Step 1: Write the failing test**

Create `tests/test_strip_peak_tracker.py`:
```python
"""Tests for peak identification and migration tracking."""
import datetime
import pandas as pd
import numpy as np
import pytest

from RVUtils.StripPeak.peak_tracker import identify_peak, migration_events


def _make_strip() -> pd.DataFrame:
    """Synthetic strip: 5 dates, 6 contracts, peak migrates from C3 to C4."""
    contracts = [f"SR3{c}" for c in ["U26", "Z26", "H27", "M27", "U27", "Z27"]]
    data = {
        # rates: peak starts at M27, migrates to U27 on day 4
        contracts[0]: [3.80, 3.80, 3.80, 3.80, 3.80],
        contracts[1]: [3.90, 3.90, 3.90, 3.90, 3.90],
        contracts[2]: [4.00, 4.00, 4.00, 4.00, 4.00],
        contracts[3]: [4.10, 4.12, 4.14, 4.05, 4.05],  # peak days 1-3
        contracts[4]: [4.05, 4.08, 4.10, 4.15, 4.18],  # peak days 4-5
        contracts[5]: [3.95, 3.95, 3.95, 3.95, 3.95],
    }
    dates = pd.date_range("2026-08-18", periods=5, freq="B").date
    return pd.DataFrame(data, index=dates)


def test_identify_peak_basic():
    strip = _make_strip()
    peak = identify_peak(strip)
    assert len(peak) == 5
    assert peak["peak_contract"].iloc[0] == "SR3M27"
    assert peak["peak_contract"].iloc[-1] == "SR3U27"
    assert peak["is_interior"].all()  # none at endpoints


def test_peak_prominence():
    strip = _make_strip()
    peak = identify_peak(strip)
    # prominence = peak_rate - avg(neighbors)
    # day 1: M27=4.10, neighbors H27=4.00, U27=4.05 -> prom = 4.10 - 4.025 = 0.075
    assert abs(peak["prominence"].iloc[0] - 0.075) < 0.001


def test_migration_events():
    strip = _make_strip()
    peak = identify_peak(strip)
    events = migration_events(peak)
    assert len(events) == 1  # one migration: M27 -> U27
    assert events.iloc[0]["from_contract"] == "SR3M27"
    assert events.iloc[0]["to_contract"] == "SR3U27"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_strip_peak_tracker.py -v --no-header 2>&1 | tail -5`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement peak_tracker.py**

Create `RVUtils/StripPeak/peak_tracker.py`:
```python
"""Identify the peak-rate contract in a strip and track its migration."""
from __future__ import annotations

import pandas as pd
import numpy as np


def identify_peak(strip_df: pd.DataFrame) -> pd.DataFrame:
    """For each date, find the contract with the highest implied rate.

    Parameters
    ----------
    strip_df : DataFrame
        Index = date, columns = SR3 symbols, values = rate (%).

    Returns
    -------
    DataFrame with columns:
        peak_contract, peak_rate, peak_idx, prominence, is_interior
    """
    cols = list(strip_df.columns)
    rates = strip_df.values  # (n_dates, n_contracts)
    peak_idx = np.argmax(rates, axis=1)
    peak_rate = rates[np.arange(len(rates)), peak_idx]
    peak_contract = [cols[i] for i in peak_idx]

    # prominence: peak_rate minus average of immediate neighbors
    prominence = np.full(len(rates), np.nan)
    is_interior = np.ones(len(rates), dtype=bool)
    for i, pi in enumerate(peak_idx):
        if pi == 0:
            # peak at front — only right neighbor
            prominence[i] = peak_rate[i] - rates[i, pi + 1]
            is_interior[i] = False
        elif pi == len(cols) - 1:
            # peak at back — only left neighbor
            prominence[i] = peak_rate[i] - rates[i, pi - 1]
            is_interior[i] = False
        else:
            avg_neighbors = (rates[i, pi - 1] + rates[i, pi + 1]) / 2
            prominence[i] = peak_rate[i] - avg_neighbors

    return pd.DataFrame(
        {
            "peak_contract": peak_contract,
            "peak_rate": peak_rate,
            "peak_idx": peak_idx,
            "prominence": prominence,
            "is_interior": is_interior,
        },
        index=strip_df.index,
    )


def migration_events(peak_df: pd.DataFrame) -> pd.DataFrame:
    """Return rows where the peak contract changed from the previous day."""
    shifted = peak_df["peak_contract"].shift(1)
    mask = (peak_df["peak_contract"] != shifted) & shifted.notna()
    events = peak_df[mask].copy()
    events["from_contract"] = shifted[mask].values
    events["to_contract"] = events["peak_contract"].values
    return events[["from_contract", "to_contract", "peak_rate", "prominence"]]
```

- [ ] **Step 4: Run tests and verify pass**

Run: `conda run -n stir python -m pytest tests/test_strip_peak_tracker.py -v --no-header 2>&1 | tail -10`
Expected: 3 PASSED

- [ ] **Step 5: Update __init__.py and commit**

Add to `RVUtils/StripPeak/__init__.py`:
```python
from RVUtils.StripPeak.peak_tracker import identify_peak, migration_events
```

```bash
git -C ../ARBS-spf add RVUtils/StripPeak/peak_tracker.py tests/test_strip_peak_tracker.py RVUtils/StripPeak/__init__.py
git -C ../ARBS-spf commit -m "feat(strip-peak): peak identifier + migration tracker"
```

---

### Task 3: Linear backtests — calendar spread (A) and butterfly (B)

**Files:**
- Create: `RVUtils/StripPeak/linear_backtest.py`
- Create: `tests/test_strip_peak_linear_bt.py`

**Interfaces:**
- Consumes: `build_daily_strip(...)`, `identify_peak(...)`
- Produces:
  - `backtest_spread(strip_df, peak_df, hold_days, cost_bp) -> pd.DataFrame` — one row per entry date, with entry/exit levels and P&L
  - `backtest_butterfly(strip_df, peak_df, hold_days, cost_bp) -> pd.DataFrame` — same format
  - `summary_stats(bt_df) -> dict` — hit_rate, avg_pnl, sharpe, n_trades

- [ ] **Step 1: Write the failing test**

Create `tests/test_strip_peak_linear_bt.py`:
```python
"""Tests for the linear strip-peak-fade backtests."""
import datetime
import pandas as pd
import numpy as np
import pytest

from RVUtils.StripPeak.peak_tracker import identify_peak
from RVUtils.StripPeak.linear_backtest import (
    backtest_spread,
    backtest_butterfly,
    summary_stats,
)


def _make_strip_with_decay() -> pd.DataFrame:
    """10-day strip where the peak decays: M27 starts at 4.20 and falls to 4.10."""
    contracts = ["SR3U26", "SR3Z26", "SR3H27", "SR3M27", "SR3U27", "SR3Z27"]
    n = 10
    dates = pd.date_range("2026-01-05", periods=n, freq="B").date
    base = np.array([3.80, 3.90, 4.00, 4.20, 4.05, 3.95])
    # decay: M27 falls by 1bp/day, neighbors stay flat
    data = {}
    for j, c in enumerate(contracts):
        if c == "SR3M27":
            data[c] = [base[j] - 0.01 * i for i in range(n)]
        else:
            data[c] = [base[j]] * n
    return pd.DataFrame(data, index=dates)


def test_backtest_spread_positive_pnl_on_decay():
    """When the peak decays, the spread (sell peak / buy peak+1) should profit."""
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt = backtest_spread(strip, peak, hold_days=5, cost_bp=0.0)
    assert len(bt) > 0
    # peak decays 5bp over 5 days — spread should profit
    assert bt["pnl_bp"].mean() > 0


def test_backtest_butterfly_positive_pnl_on_decay():
    """When the peak decays, the butterfly should profit."""
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt = backtest_butterfly(strip, peak, hold_days=5, cost_bp=0.0)
    assert len(bt) > 0
    assert bt["pnl_bp"].mean() > 0


def test_backtest_spread_cost_reduces_pnl():
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt_free = backtest_spread(strip, peak, hold_days=5, cost_bp=0.0)
    bt_cost = backtest_spread(strip, peak, hold_days=5, cost_bp=2.0)
    assert bt_cost["pnl_bp"].mean() < bt_free["pnl_bp"].mean()


def test_summary_stats_has_required_keys():
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt = backtest_spread(strip, peak, hold_days=5, cost_bp=0.0)
    stats = summary_stats(bt)
    for key in ["n_trades", "hit_rate", "avg_pnl_bp", "sharpe", "total_pnl_bp"]:
        assert key in stats
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_strip_peak_linear_bt.py -v --no-header 2>&1 | tail -5`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement linear_backtest.py**

Create `RVUtils/StripPeak/linear_backtest.py`:
```python
"""Vectorized backtests for fading the strip peak via calendar spreads and butterflies."""
from __future__ import annotations

import numpy as np
import pandas as pd


def backtest_spread(
    strip_df: pd.DataFrame,
    peak_df: pd.DataFrame,
    hold_days: int = 21,
    cost_bp: float = 2.0,
    require_interior: bool = True,
) -> pd.DataFrame:
    """Backtest: sell peak contract, buy peak+1 (one-quarter-out).

    P&L in bp: positive = peak rate fell relative to peak+1 (flattener won).
    Spread P&L = (peak_rate_entry - peak_rate_exit) - (next_rate_entry - next_rate_exit)
               = delta(peak) - delta(next)  [in rate terms, selling peak]

    For a flattener (sell peak rate, buy next rate):
      pnl = -(change in peak rate) + (change in next rate)
          = (peak_rate_entry - peak_rate_exit) - (next_rate_entry - next_rate_exit)
    Wait — sell peak rate means RECEIVE peak rate at entry, PAY at exit.
    If peak rate falls, we profit (entered high, exited low).
    pnl_peak_leg = (entry_peak - exit_peak) [positive when rate falls]
    pnl_next_leg = -(entry_next - exit_next) = (exit_next - entry_next) [we bought next]
    total = (entry_peak - exit_peak) + (exit_next - entry_next)
    """
    cols = list(strip_df.columns)
    records = []

    for i, (date, row) in enumerate(peak_df.iterrows()):
        if require_interior and not row["is_interior"]:
            continue
        peak_idx = int(row["peak_idx"])
        if peak_idx >= len(cols) - 1:
            continue  # no next contract

        exit_i = i + hold_days
        if exit_i >= len(strip_df):
            continue

        peak_sym = cols[peak_idx]
        next_sym = cols[peak_idx + 1]
        exit_date = strip_df.index[exit_i]

        entry_peak = strip_df.at[date, peak_sym]
        exit_peak = strip_df.at[exit_date, peak_sym]
        entry_next = strip_df.at[date, next_sym]
        exit_next = strip_df.at[exit_date, next_sym]

        pnl = (entry_peak - exit_peak) + (exit_next - entry_next)
        pnl_bp = pnl * 100 - cost_bp

        records.append({
            "entry_date": date,
            "exit_date": exit_date,
            "peak_contract": peak_sym,
            "next_contract": next_sym,
            "entry_spread_bp": (entry_peak - entry_next) * 100,
            "exit_spread_bp": (exit_peak - exit_next) * 100,
            "pnl_bp": pnl_bp,
            "prominence": row["prominence"],
        })

    return pd.DataFrame(records)


def backtest_butterfly(
    strip_df: pd.DataFrame,
    peak_df: pd.DataFrame,
    hold_days: int = 21,
    cost_bp: float = 4.0,
    require_interior: bool = True,
) -> pd.DataFrame:
    """Backtest: buy peak-1, sell 2x peak, buy peak+1.

    Butterfly P&L in bp (selling the peak curvature):
      pnl = 1*(prev_change) - 2*(peak_change) + 1*(next_change)
      where change = exit_rate - entry_rate (positive = rate rose)

    We are SHORT the peak and LONG the wings in rate terms.
    If the peak rate falls more than the wings, we profit.
    pnl = (entry_fly - exit_fly) where fly = 2*peak - prev - next
    """
    cols = list(strip_df.columns)
    records = []

    for i, (date, row) in enumerate(peak_df.iterrows()):
        if require_interior and not row["is_interior"]:
            continue
        peak_idx = int(row["peak_idx"])
        if peak_idx == 0 or peak_idx >= len(cols) - 1:
            continue

        exit_i = i + hold_days
        if exit_i >= len(strip_df):
            continue

        prev_sym = cols[peak_idx - 1]
        peak_sym = cols[peak_idx]
        next_sym = cols[peak_idx + 1]
        exit_date = strip_df.index[exit_i]

        entry_fly = (
            2 * strip_df.at[date, peak_sym]
            - strip_df.at[date, prev_sym]
            - strip_df.at[date, next_sym]
        )
        exit_fly = (
            2 * strip_df.at[exit_date, peak_sym]
            - strip_df.at[exit_date, prev_sym]
            - strip_df.at[exit_date, next_sym]
        )
        pnl = (entry_fly - exit_fly) * 100 - cost_bp

        records.append({
            "entry_date": date,
            "exit_date": exit_date,
            "peak_contract": peak_sym,
            "entry_fly_bp": entry_fly * 100,
            "exit_fly_bp": exit_fly * 100,
            "pnl_bp": pnl,
            "prominence": row["prominence"],
        })

    return pd.DataFrame(records)


def summary_stats(bt_df: pd.DataFrame) -> dict:
    """Compute summary statistics for a backtest result DataFrame."""
    if bt_df.empty:
        return {"n_trades": 0, "hit_rate": 0, "avg_pnl_bp": 0, "sharpe": 0, "total_pnl_bp": 0}
    pnl = bt_df["pnl_bp"]
    return {
        "n_trades": len(pnl),
        "hit_rate": (pnl > 0).mean(),
        "avg_pnl_bp": pnl.mean(),
        "sharpe": pnl.mean() / pnl.std() * np.sqrt(252 / max(1, len(pnl))) if pnl.std() > 0 else 0,
        "total_pnl_bp": pnl.sum(),
        "median_pnl_bp": pnl.median(),
        "max_dd_bp": (pnl.cumsum() - pnl.cumsum().cummax()).min(),
    }
```

- [ ] **Step 4: Run tests and verify pass**

Run: `conda run -n stir python -m pytest tests/test_strip_peak_linear_bt.py -v --no-header 2>&1 | tail -10`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git -C ../ARBS-spf add RVUtils/StripPeak/linear_backtest.py tests/test_strip_peak_linear_bt.py
git -C ../ARBS-spf commit -m "feat(strip-peak): vectorized spread + butterfly backtests with cost"
```

---

### Task 4: Full linear backtest run + results notebook

**Files:**
- Create: `scripts/_build_strip_peak.py` — data builder + backtest runner
- Create: `notebooks/backtests/strip_peak/strip_peak_linear.ipynb` — results notebook

**Interfaces:**
- Consumes: `build_daily_strip`, `identify_peak`, `migration_events`, `backtest_spread`, `backtest_butterfly`, `summary_stats`
- Produces: results notebook with grid over `hold_days x cost_bp`, regime splits, migration analysis

- [ ] **Step 1: Write the data builder script**

Create `scripts/_build_strip_peak.py`:
```python
"""Build strip data + run the linear peak-fade backtests."""
import datetime
import json
import sys
sys.path.insert(0, ".")

import os
os.environ["ARBS_SUPABASE_ENABLED"] = "0"

import pandas as pd
import numpy as np

from RVUtils.StripPeak.strip_builder import build_daily_strip
from RVUtils.StripPeak.peak_tracker import identify_peak, migration_events
from RVUtils.StripPeak.linear_backtest import backtest_spread, backtest_butterfly, summary_stats

START = datetime.date(2023, 6, 1)
END = datetime.date(2026, 8, 22)
N_FRONT = 8
HOLD_DAYS_GRID = [5, 10, 21, 42, 63]
COST_GRID_SPREAD = [0.0, 1.0, 2.0]      # 2 legs
COST_GRID_FLY = [0.0, 2.0, 4.0]          # 4 legs

print("=== Building daily strip ===")
strip = build_daily_strip(START, END, N_FRONT, cache=True)
print(f"Strip: {strip.shape[0]} dates x {strip.shape[1]} contracts")
print(f"Columns: {list(strip.columns)}")
print(f"Date range: {strip.index[0]} to {strip.index[-1]}")

print("\n=== Identifying peaks ===")
peak = identify_peak(strip)
interior = peak[peak["is_interior"]]
print(f"Total dates: {len(peak)}, interior peaks: {len(interior)}")
print(f"Peak contracts (value counts):")
print(peak["peak_contract"].value_counts().head(10).to_string())

events = migration_events(peak)
print(f"\nMigration events: {len(events)}")
if len(events) > 0:
    print(events.tail(10).to_string())

print("\n=== Spread backtest grid ===")
spread_results = []
for hd in HOLD_DAYS_GRID:
    for cost in COST_GRID_SPREAD:
        bt = backtest_spread(strip, peak, hold_days=hd, cost_bp=cost)
        stats = summary_stats(bt)
        stats["hold_days"] = hd
        stats["cost_bp"] = cost
        stats["variant"] = "spread"
        spread_results.append(stats)
        print(f"  hold={hd:3d}d  cost={cost:.1f}bp  n={stats['n_trades']:4d}  "
              f"hit={stats['hit_rate']:.1%}  avg={stats['avg_pnl_bp']:+.2f}bp  "
              f"sharpe={stats['sharpe']:.2f}")

print("\n=== Butterfly backtest grid ===")
fly_results = []
for hd in HOLD_DAYS_GRID:
    for cost in COST_GRID_FLY:
        bt = backtest_butterfly(strip, peak, hold_days=hd, cost_bp=cost)
        stats = summary_stats(bt)
        stats["hold_days"] = hd
        stats["cost_bp"] = cost
        stats["variant"] = "butterfly"
        fly_results.append(stats)
        print(f"  hold={hd:3d}d  cost={cost:.1f}bp  n={stats['n_trades']:4d}  "
              f"hit={stats['hit_rate']:.1%}  avg={stats['avg_pnl_bp']:+.2f}bp  "
              f"sharpe={stats['sharpe']:.2f}")

all_results = pd.DataFrame(spread_results + fly_results)
out_dir = "analysis_outputs/strip_peak"
os.makedirs(out_dir, exist_ok=True)
all_results.to_csv(f"{out_dir}/linear_grid.csv", index=False)
print(f"\nResults saved to {out_dir}/linear_grid.csv")
```

- [ ] **Step 2: Run the builder script**

```bash
cd ../ARBS-spf && conda run -n stir python scripts/_build_strip_peak.py 2>&1 | tail -40
```

This is the key gate. If the linear variants show no edge at any holding period even gross of cost, stop and report. If there IS gross edge but cost kills it, note the cost threshold and continue to the options variants (which have different cost structures).

- [ ] **Step 3: Create the results notebook**

Create `notebooks/backtests/strip_peak/strip_peak_linear.ipynb` using `scripts/_check_notebook.py` or manually. The notebook should:
1. Load the grid results from `analysis_outputs/strip_peak/linear_grid.csv`
2. Plot: avg P&L vs hold_days, colored by cost
3. Plot: the peak contract over time (which contract is the peak and when it migrates)
4. Plot: cumulative P&L of the best variant
5. Regime split: separate results for 2023-2024 (easing cycle) vs 2025-2026 (hiking cycle)
6. Conditioning: filter to entries where prominence > median

- [ ] **Step 4: Commit**

```bash
git -C ../ARBS-spf add scripts/_build_strip_peak.py notebooks/backtests/strip_peak/ analysis_outputs/strip_peak/
git -C ../ARBS-spf commit -m "feat(strip-peak): linear backtest grid + results notebook"
```

---

### Task 5: Vol butterfly variant (C) — options butterfly grid

**Files:**
- Create: `RVUtils/StripPeak/vol_backtest.py`
- Create: `tests/test_strip_peak_vol_bt.py`

**Interfaces:**
- Consumes: `STIRFutureOptionMDP.fetch_sabr_smile(request)`, strip peak data
- Produces:
  - `build_butterfly_grid(mdp, symbol, as_of) -> pd.DataFrame` — JWS-style grid with body, yield, fly_settle, imp_prob
  - `backtest_mode_butterfly(strip_df, peak_df, mdp, hold_days) -> pd.DataFrame`

**Note:** This task is data-intensive. Each date × contract requires an options smile fetch. Start with a small sample (e.g., 3 months of the peak contract only) to validate before scaling.

- [ ] **Step 1: Write the failing test**

Create `tests/test_strip_peak_vol_bt.py`:
```python
"""Tests for the vol butterfly grid + backtest."""
import datetime
import pytest

from RVUtils.StripPeak.vol_backtest import build_butterfly_grid


@pytest.mark.network
def test_build_butterfly_grid_known_date():
    """Build the grid for SFRU26 on 2026-08-21 and verify against JWS screenshot."""
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    grid = build_butterfly_grid(mdp, "SFRU26", datetime.date(2026, 8, 21))
    assert len(grid) > 10
    assert "body_price" in grid.columns
    assert "fly_settle" in grid.columns
    assert "imp_prob" in grid.columns
    # the modal body for U6 on 21-Aug was 96.1250 (3.875%) per JWS grid
    mode_row = grid.loc[grid["imp_prob"].idxmax()]
    assert abs(mode_row["body_price"] - 96.125) < 0.0625 * 2  # within 2 ticks
```

- [ ] **Step 2: Implement vol_backtest.py**

Create `RVUtils/StripPeak/vol_backtest.py`:
```python
"""Vol butterfly grid (JWS-style) and mode-vs-forward backtest."""
from __future__ import annotations

import datetime
from typing import Optional

import numpy as np
import pandas as pd


def build_butterfly_grid(
    mdp,
    symbol: str,
    as_of: datetime.date,
    wing_width_bp: float = 12.5,
    body_step_bp: float = 6.25,
) -> pd.DataFrame:
    """Build the JWS-style 12bp butterfly grid for a single contract.

    Uses listed strikes via fetch_sabr_smile. Fills deep-ITM calls via put-call parity.
    """
    req = {"symbol": symbol, "as_of": as_of, "strike_offsets_bps": "listed"}
    smile = mdp.fetch_sabr_smile(req)
    # smile is STIRFutureOptionSABRSmile
    # .points -> tuple of STIRFutureOptionSmilePoint (strike_price, right, market_price, open_interest)
    # .params -> STIRFutureOptionSABRParams (alpha, beta, rho, nu, forward)
    pts = smile.points
    future_price = smile.params.forward if hasattr(smile.params, "forward") else None

    calls = {p.strike_price: p.market_price for p in pts if p.right == "C"}
    puts = {p.strike_price: p.market_price for p in pts if p.right == "P"}

    # Build bodies on the 6.25bp grid
    # body prices from ~94.50 to ~97.00
    bodies = np.arange(94.5, 97.001, body_step_bp / 100)
    records = []

    for body in bodies:
        lower = body - wing_width_bp / 100
        upper = body + wing_width_bp / 100
        # fly = call(lower) - 2*call(body) + call(upper)
        # need call prices at these strikes
        try:
            c_lower = _get_call_price(calls, lower, future_price, pts)
            c_body = _get_call_price(calls, body, future_price, pts)
            c_upper = _get_call_price(calls, upper, future_price, pts)
        except (KeyError, ValueError):
            continue

        if any(x is None for x in [c_lower, c_body, c_upper]):
            continue

        fly_settle = c_lower - 2 * c_body + c_upper
        max_payout = wing_width_bp / 100  # 0.125 for 12.5bp wings
        imp_prob = fly_settle / max_payout if max_payout > 0 else 0

        records.append({
            "body_price": body,
            "body_yield": 100 - body,
            "fly_settle": fly_settle,
            "imp_prob": imp_prob,
        })

    return pd.DataFrame(records)


def _get_call_price(calls_dict, puts_dict, strike, future_price):
    """Get call price at strike, using put-call parity for ITM calls if needed."""
    if strike in calls_dict:
        return calls_dict[strike]
    # put-call parity: C(K) = P(K) + F - K  (assuming DF~1 for short-dated STIR)
    if strike in puts_dict and future_price is not None:
        return puts_dict[strike] + future_price - strike
    return None
```

This is a skeleton — the exact interface of `STIRFutureOptionMDP.fetch_sabr_smile` needs verification against the actual return type. The existing `recreate_jpm_appendix_distributions.py` at line 18-23 shows the calling pattern: `STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")` with `fetch_sabr_smile({"symbol": "SFRU26", "as_of": date, "strike_offsets_bps": "listed"})`. Adapt the grid builder based on what the smile object actually exposes.

- [ ] **Step 3: Run test, iterate**

Run: `conda run -n stir python -m pytest tests/test_strip_peak_vol_bt.py -v -m network --no-header 2>&1 | tail -10`

The first run will likely fail on the smile object's interface. Print `type(smile)`, `dir(smile)`, and `smile.points.head()` to discover the actual API, then adjust.

- [ ] **Step 4: Extend with mode-vs-forward tracker and backtest**

Once `build_butterfly_grid` works for one date, add:
```python
def mode_vs_forward(grid: pd.DataFrame, future_price: float) -> dict:
    """Compute the mode-forward gap from a butterfly grid."""
    mode_row = grid.loc[grid["imp_prob"].idxmax()]
    return {
        "mode_yield": mode_row["body_yield"],
        "forward_yield": 100 - future_price,
        "gap_bp": (mode_row["body_yield"] - (100 - future_price)) * 100,
        "mode_imp_prob": mode_row["imp_prob"],
    }
```

The backtest: at each date, when the mode-forward gap exceeds a threshold, buy the mode butterfly. Track P&L over hold_days.

- [ ] **Step 5: Commit**

```bash
git -C ../ARBS-spf add RVUtils/StripPeak/vol_backtest.py tests/test_strip_peak_vol_bt.py
git -C ../ARBS-spf commit -m "feat(strip-peak): vol butterfly grid + mode-vs-forward tracker"
```

---

### Task 6: Implied distribution variant (D)

**Files:**
- Create: `RVUtils/StripPeak/distribution_backtest.py`
- Create: `tests/test_strip_peak_dist_bt.py`

**Interfaces:**
- Consumes: `SFRImpliedDistribution`, `STIRFutureOptionMDP`, strip peak data
- Produces: `backtest_mode_divergence(strip_df, peak_df, mdp, hold_days) -> pd.DataFrame`

- [ ] **Step 1: Write the failing test**

Create `tests/test_strip_peak_dist_bt.py`:
```python
"""Tests for the implied-distribution mode divergence backtest."""
import datetime
import pytest

from RVUtils.StripPeak.distribution_backtest import build_mode_series


@pytest.mark.network
def test_build_mode_series_single_contract():
    """Build mode time series for SFRU26 over a short window."""
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    modes = build_mode_series(
        mdp,
        symbol="SFRU26",
        dates=[datetime.date(2026, 8, 20), datetime.date(2026, 8, 21)],
    )
    assert len(modes) >= 1
    assert "mode_rate" in modes.columns
    assert "forward_rate" in modes.columns
    assert "gap_bp" in modes.columns
```

- [ ] **Step 2: Implement distribution_backtest.py**

Create `RVUtils/StripPeak/distribution_backtest.py`:
```python
"""Implied-distribution mode divergence backtest."""
from __future__ import annotations

import datetime
from typing import List

import numpy as np
import pandas as pd

from RVUtils.ImpliedDistribution import SFRImpliedDistribution


def build_mode_series(
    mdp,
    symbol: str,
    dates: List[datetime.date],
) -> pd.DataFrame:
    """Build a time series of the implied distribution mode for a contract."""
    records = []
    for d in dates:
        try:
            # 1. fetch the smile for this date
            smile = mdp.fetch_sabr_smile({
                "symbol": symbol, "as_of": d, "strike_offsets_bps": "listed"
            })
            # 2. extract the implied distribution
            dist = SFRImpliedDistribution()
            snap = dist.extract(smile)
            bl = snap.bl_result
            # 3. find mode from the density
            mode_rate = bl.strike_grid_rate[np.argmax(bl.rnd_density)]
            forward_rate = smile.params.forward if hasattr(smile.params, "forward") else np.nan
            records.append({
                "date": d,
                "symbol": symbol,
                "mode_rate": mode_rate,
                "forward_rate": forward_rate,
                "gap_bp": (mode_rate - forward_rate) * 100 if not np.isnan(mode_rate) else np.nan,
            })
        except Exception:
            continue
    return pd.DataFrame(records).set_index("date") if records else pd.DataFrame()
```

This is a skeleton — `SFRImpliedDistribution`'s actual constructor and API need verification against `RVUtils/ImpliedDistribution/`. Adapt based on the actual class.

- [ ] **Step 3: Run test, iterate on SFRImpliedDistribution API**

Discover the actual API by running:
```python
from RVUtils.ImpliedDistribution import SFRImpliedDistribution
help(SFRImpliedDistribution.__init__)
```

Then adjust `build_mode_series` to match.

- [ ] **Step 4: Commit**

```bash
git -C ../ARBS-spf add RVUtils/StripPeak/distribution_backtest.py tests/test_strip_peak_dist_bt.py
git -C ../ARBS-spf commit -m "feat(strip-peak): implied distribution mode divergence tracker"
```

---

### Task 7: Unified results notebook + what kills it

**Files:**
- Create: `notebooks/backtests/strip_peak/strip_peak_all_variants.ipynb`
- Create: `docs/strip_peak/RESULTS.md`

**Interfaces:**
- Consumes: all prior tasks' outputs

- [ ] **Step 1: Build the unified results notebook**

The notebook should contain:

**Section 1: Strip anatomy**
- The daily strip heatmap (dates × contracts → rate, colored)
- Peak contract migration chart (which contract is the peak over time)
- Peak prominence over time
- Migration frequency by regime

**Section 2: Linear variants (A+B)**
- Grid: hold_days × cost → avg P&L, Sharpe
- Cumulative P&L of the best variant (gross and net of cost)
- Regime split: easing (2023-2024) vs hiking (2025-2026)
- Conditioning on prominence: does fading high-prominence peaks work better?

**Section 3: Vol butterfly variant (C)**
- Mode-vs-forward gap over time by contract
- Butterfly P&L at the mode
- Comparison: does the options expression outperform the linear?

**Section 4: Implied distribution variant (D)**
- Mode from density vs mode from butterfly grid (should match)
- Mode migration tracking
- Gap-based entry signal

**Section 5: What kills it** (the most important section)
- Cost threshold: at what cost does the edge die?
- Direction contamination: is the signal just a rates-direction trade? (Regress P&L on front contract change)
- Overlapping entries: how much of the P&L is just the same trade rolling?
- Sample size: n-floor check on every cell
- The question from prior work: does the belly outright beat the fly on the same signal?

- [ ] **Step 2: Write RESULTS.md with findings**

Commit the findings as markdown under `docs/strip_peak/RESULTS.md`, following the `docs/convexityrv` pattern.

- [ ] **Step 3: Final commit**

```bash
git -C ../ARBS-spf add notebooks/backtests/strip_peak/ docs/strip_peak/
git -C ../ARBS-spf commit -m "feat(strip-peak): unified results + what kills it"
```
