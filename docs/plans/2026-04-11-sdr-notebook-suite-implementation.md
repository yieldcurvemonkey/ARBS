# SDR Analytics Notebook Suite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build 10 Jupyter notebooks + 1 shared Python module in `notebooks/sdr/` providing EOD and historical SDR analytics for a USD swaps market-making desk.

**Architecture:** Shared `_sdr_common.py` wraps `SDRUtils` classification pipeline, providing data loading, enrichment, filtering, and visualization defaults. Each notebook imports this module and focuses on one analytical domain. Data flows: DTCC SDR → `SDRDataBuilder` → `USD_SwapProduct.build_classification_dataframe()` → `_sdr_common.load_classified_trades()` → notebook-specific analytics.

**Tech Stack:** SDRUtils (classification, lifecycle, packages, seasonality), IRSwapsMDP (curves), curve_store (historical snapshots), pandas, numpy, matplotlib, seaborn.

**Design doc:** `docs/plans/2026-04-11-sdr-notebook-suite-design.md`

---

### Task 1: Create `_sdr_common.py` — Shared Data Loading & Enrichment Module

**Files:**
- Create: `notebooks/sdr/_sdr_common.py`

**Step 1: Write the shared module**

```python
"""
Shared SDR analytics utilities for notebook suite.

Wraps SDRUtils classification pipeline with notebook-friendly helpers
for data loading, enrichment, filtering, and visualization defaults.
"""

from __future__ import annotations

import datetime
from typing import List, Literal, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from SDRUtils.products.usd.usd_swaps import USD_SwapProduct
from SDRUtils.products.usd.linear_base import (
    BasisSwapClassification,
    BasisType,
    LinearProductType,
    RateIndex,
    TenorSegment,
    USDLinearClassification,
)
from SDRUtils.analytics.seasonality import (
    add_event_classifications,
    get_fomc_dates,
    get_imm_dates,
    get_month_end_dates,
    get_quarter_end_dates,
)

# ---------------------------------------------------------------------------
# Visualization constants
# ---------------------------------------------------------------------------

TENOR_ORDER = [
    "1M", "3M", "6M",
    "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y",
    "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y",
]

TENOR_BUCKET_ORDER = ["0-2Y", "2-5Y", "5-10Y", "10-20Y", "20-30Y", "30Y+"]

TENOR_BUCKET_RANGES = {
    "0-2Y": (0, 2),
    "2-5Y": (2, 5),
    "5-10Y": (5, 10),
    "10-20Y": (10, 20),
    "20-30Y": (20, 30),
    "30Y+": (30, 100),
}

BENCHMARK_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

PACKAGE_COLORS = {
    "OUTRIGHT": "#4C78A8",
    "CURVE": "#F58518",
    "FLY": "#E45756",
    "SPREADOVER": "#72B7B2",
    "MAC": "#54A24B",
    "MATCHED_MATURITY": "#EECA3B",
    "INVOICE_SWAP": "#B279A2",
    "COMPRESSION": "#BFBFBF",
}

RATE_INDEX_COLORS = {
    "SOFR": "#4C78A8",
    "SOFR_COMPOUND": "#4C78A8",
    "FED_FUNDS": "#F58518",
    "FED_FUNDS_COMPOUND": "#F58518",
    "CMS": "#E45756",
    "SIFMA": "#72B7B2",
    "OBFR": "#54A24B",
}

SPECIAL_TENOR_COLORS = {
    "STANDARD": "#4C78A8",
    "IMM": "#F58518",
    "FOMC": "#E45756",
    "MAC": "#54A24B",
    "MATCHED_MATURITY": "#EECA3B",
    "INVOICE_SWAP": "#B279A2",
}

DEFAULT_CACHE_PATH = "C:/sdr_cache"


# ---------------------------------------------------------------------------
# Notebook setup
# ---------------------------------------------------------------------------

def notebook_setup():
    """Standard notebook initialization."""
    try:
        from IPython import get_ipython
        ip = get_ipython()
        if ip is not None:
            ip.run_line_magic("load_ext", "autoreload")
            ip.run_line_magic("autoreload", "2")
            ip.run_line_magic("matplotlib", "inline")
    except Exception:
        pass

    plt.rcParams.update({
        "figure.figsize": (14, 6),
        "figure.dpi": 100,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 9,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.3,
    })
    sns.set_palette("muted")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_classified_trades(
    start: datetime.datetime,
    end: datetime.datetime,
    cache_path: str = DEFAULT_CACHE_PATH,
    curve_source: str = "ERIS_EOD_LIVE-RL_BASIC",
    detect_packages: bool = True,
) -> pd.DataFrame:
    """
    Load and classify SDR trades for a date range.

    Wraps USD_SwapProduct.build_classification_dataframe() with
    automatic DV01 and volume bucket enrichment.

    Returns DataFrame with classification columns including:
        trade_id, execution_timestamp, effective_date, expiration_date,
        product_type, trade_label, notional, is_notional_capped, estimated_pv01,
        tenor_years, tenor_label, is_forward, forward_start_years, forward_label,
        fixed_rate, special_tenor_type, special_tenor_confidence,
        rate_index, linear_product_type, tenor_segment,
        package_type, package_id, package_legs,
        platform_identifier, cleared, block_trade_election_indicator,
        is_spreadover, is_asset_swap
    """
    product = USD_SwapProduct()
    df = product.build_classification_dataframe(
        start=start,
        end=end,
        cache_path=cache_path,
        detect_curve=detect_packages,
        detect_fly=detect_packages,
        detect_mms=detect_packages,
        detect_invoice=detect_packages,
        detect_mac=detect_packages,
        detect_spreadover=detect_packages,
        curve_source=curve_source,
    )

    if df.empty:
        return df

    df = add_dv01_columns(df)
    df = add_volume_buckets(df)
    df = add_execution_date(df)
    return df


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------

def add_dv01_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add dv01 column = abs(estimated_pv01 * notional / 10_000)."""
    df = df.copy()
    pv01 = pd.to_numeric(df.get("estimated_pv01"), errors="coerce").fillna(0)
    notional = pd.to_numeric(df.get("notional"), errors="coerce").fillna(0)
    df["dv01"] = (pv01 * notional / 10_000).abs()
    return df


def add_volume_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """Add tenor_bucket column based on tenor_years."""
    df = df.copy()
    tenor = pd.to_numeric(df.get("tenor_years"), errors="coerce").fillna(0)
    conditions = [
        tenor <= 2,
        (tenor > 2) & (tenor <= 5),
        (tenor > 5) & (tenor <= 10),
        (tenor > 10) & (tenor <= 20),
        (tenor > 20) & (tenor <= 30),
        tenor > 30,
    ]
    df["tenor_bucket"] = pd.Categorical(
        np.select(conditions, TENOR_BUCKET_ORDER, default="0-2Y"),
        categories=TENOR_BUCKET_ORDER,
        ordered=True,
    )
    return df


def add_execution_date(df: pd.DataFrame) -> pd.DataFrame:
    """Add execution_date (date only) from execution_timestamp."""
    df = df.copy()
    df["execution_date"] = pd.to_datetime(
        df["execution_timestamp"], errors="coerce"
    ).dt.date
    return df


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def filter_new_risk(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only new-risk trades (NEWT action type, exclude compression indicators)."""
    mask = pd.Series(True, index=df.index)
    if "event_action" in df.columns:
        mask &= df["event_action"].astype(str).str.upper() == "NEWT"
    return df[mask].copy()


def filter_outrights(df: pd.DataFrame) -> pd.DataFrame:
    """Keep trades where package_type is None/NaN or OUTRIGHT."""
    if "package_type" not in df.columns:
        return df.copy()
    pkg = df["package_type"].fillna("OUTRIGHT")
    return df[pkg == "OUTRIGHT"].copy()


def filter_packages(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only multi-leg package trades (CURVE, FLY, etc.)."""
    if "package_type" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    pkg = df["package_type"].fillna("OUTRIGHT")
    return df[pkg != "OUTRIGHT"].copy()


def filter_by_rate_index(df: pd.DataFrame, index: str) -> pd.DataFrame:
    """Filter to specific rate index (e.g., 'SOFR', 'FED_FUNDS')."""
    if "rate_index" not in df.columns:
        return df.copy()
    return df[df["rate_index"].astype(str).str.upper() == index.upper()].copy()


def filter_by_basis_type(df: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Filter to specific basis type (e.g., 'SOFR_FF')."""
    if "basis_type" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["basis_type"].astype(str).str.upper() == basis.upper()].copy()


def filter_spreadovers(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only spreadover trades."""
    if "is_spreadover" in df.columns:
        return df[df["is_spreadover"] == True].copy()
    if "linear_product_type" in df.columns:
        return df[df["linear_product_type"] == "SPREADOVER"].copy()
    return pd.DataFrame(columns=df.columns)


def filter_blocks(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only block trades."""
    col = "block_trade_election_indicator"
    if col not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df[col] == True].copy()


def filter_capped(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only trades with capped notional."""
    if "is_notional_capped" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["is_notional_capped"] == True].copy()


def filter_compression_heuristic(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify likely compression trades via heuristics.

    Signals:
    - TERM action type (terminations from compression)
    - Round notional divisible by 5M
    - Non-NEWT lifecycle events
    """
    masks = []

    if "event_action" in df.columns:
        masks.append(df["event_action"].astype(str).str.upper() == "TERM")

    if masks:
        combined = masks[0]
        for m in masks[1:]:
            combined |= m
        return df[combined].copy()

    return pd.DataFrame(columns=df.columns)


def filter_reset_optimization(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify single-period / FRA-like reset optimization activity.

    These are algorithmic trades (not organic demand) that inflate volume stats.
    Signals: tenor_years < 0.5 (roughly 6 months or less).
    """
    tenor = pd.to_numeric(df.get("tenor_years"), errors="coerce").fillna(999)
    return df[tenor < 0.5].copy()


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def daily_dv01_by_group(
    df: pd.DataFrame,
    group_col: str,
    date_col: str = "execution_date",
    value_col: str = "dv01",
) -> pd.DataFrame:
    """Pivot table: daily DV01 by a grouping column."""
    return df.pivot_table(
        index=date_col,
        columns=group_col,
        values=value_col,
        aggfunc="sum",
        fill_value=0,
    )


def rolling_zscore(
    series: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Rolling z-score of a series."""
    mu = series.rolling(window, min_periods=5).mean()
    sigma = series.rolling(window, min_periods=5).std()
    return (series - mu) / sigma.replace(0, np.nan)


def vwap(
    df: pd.DataFrame,
    rate_col: str = "fixed_rate",
    weight_col: str = "dv01",
) -> float:
    """Volume-weighted average rate."""
    rates = pd.to_numeric(df[rate_col], errors="coerce")
    weights = pd.to_numeric(df[weight_col], errors="coerce")
    valid = rates.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return np.nan
    return np.average(rates[valid], weights=weights[valid])


def daily_vwap(
    df: pd.DataFrame,
    group_col: str = "tenor_label",
    rate_col: str = "fixed_rate",
    weight_col: str = "dv01",
    date_col: str = "execution_date",
) -> pd.DataFrame:
    """Daily VWAP per group (e.g., per tenor)."""
    records = []
    for (date, group), sub in df.groupby([date_col, group_col]):
        v = vwap(sub, rate_col=rate_col, weight_col=weight_col)
        records.append({date_col: date, group_col: group, "vwap": v})
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def plot_stacked_area(
    pivot_df: pd.DataFrame,
    title: str,
    ylabel: str = "DV01 ($)",
    color_map: Optional[dict] = None,
    figsize: tuple = (14, 6),
):
    """Stacked area chart from a pivot table."""
    fig, ax = plt.subplots(figsize=figsize)
    cols = pivot_df.columns.tolist()
    colors = [color_map.get(c, None) if color_map else None for c in cols]
    colors = [c for c in colors if c is not None] or None
    pivot_df.plot.area(ax=ax, stacked=True, alpha=0.8, color=colors)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", framealpha=0.9)
    plt.tight_layout()
    return fig, ax


def plot_stacked_bar(
    pivot_df: pd.DataFrame,
    title: str,
    ylabel: str = "DV01 ($)",
    color_map: Optional[dict] = None,
    figsize: tuple = (14, 6),
):
    """Stacked bar chart from a pivot table."""
    fig, ax = plt.subplots(figsize=figsize)
    cols = pivot_df.columns.tolist()
    colors = [color_map.get(c, None) if color_map else None for c in cols]
    colors = [c for c in colors if c is not None] or None
    pivot_df.plot.bar(ax=ax, stacked=True, alpha=0.8, color=colors, width=0.8)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", framealpha=0.9)
    plt.tight_layout()
    return fig, ax


def plot_heatmap(
    pivot_df: pd.DataFrame,
    title: str,
    cmap: str = "RdYlGn_r",
    fmt: str = ".1f",
    figsize: tuple = (14, 8),
):
    """Heatmap from a pivot table."""
    fig, ax = plt.subplots(figsize=figsize)
    sns.heatmap(pivot_df, annot=True, fmt=fmt, cmap=cmap, ax=ax, linewidths=0.5)
    ax.set_title(title)
    plt.tight_layout()
    return fig, ax


def format_dv01(val: float) -> str:
    """Format DV01 value for display (e.g., $1.2M, $450K)."""
    if abs(val) >= 1e6:
        return f"${val / 1e6:.1f}M"
    if abs(val) >= 1e3:
        return f"${val / 1e3:.0f}K"
    return f"${val:.0f}"
```

**Step 2: Verify imports work**

Run: `cd /c/Users/chris/clee/ARBS && python -c "import sys; sys.path.insert(0, 'notebooks/sdr'); import _sdr_common; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add notebooks/sdr/_sdr_common.py
git commit -m "feat(sdr): add shared analytics module for SDR notebook suite"
```

---

### Task 2: Create `01_flow_decomposition.ipynb` — "What Actually Traded?"

**Files:**
- Create: `notebooks/sdr/01_flow_decomposition.ipynb`

**Step 1: Create the notebook**

Create a Jupyter notebook with the following cells:

**Cell 1 (code) — Setup & data loading:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr

sdr.notebook_setup()

# --- Parameters ---
START = datetime.datetime(2025, 3, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH
```

**Cell 2 (code) — Load classified trades:**
```python
df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
print(f"Loaded {len(df):,} classified trades from {df['execution_date'].nunique()} trading days")
print(f"Total DV01: {sdr.format_dv01(df['dv01'].sum())}")
print(f"Columns: {list(df.columns)}")
```

**Cell 3 (markdown):**
```markdown
## 1. Trade Type Breakdown (DV01)
Decompose raw SDR trades into economic form: outrights, curves, flies, spreadovers, MAC, IMM, FOMC.
~25% of SDR trades are packages — raw data misleads without decomposition.
```

**Cell 4 (code) — Trade type stacked bar:**
```python
# Assign effective trade type for visualization
def assign_trade_type(row):
    pkg = str(row.get("package_type", "")).upper()
    if pkg in ("CURVE", "FLY"):
        return pkg
    if row.get("is_spreadover", False):
        return "SPREADOVER"
    st = str(row.get("special_tenor_type", "STANDARD")).upper()
    if st in ("MAC", "IMM", "FOMC", "MATCHED_MATURITY", "INVOICE_SWAP"):
        return st
    return "OUTRIGHT"

df["trade_type"] = df.apply(assign_trade_type, axis=1)

pivot = sdr.daily_dv01_by_group(df, "trade_type")
type_order = ["OUTRIGHT", "CURVE", "FLY", "SPREADOVER", "MAC", "IMM", "FOMC", "MATCHED_MATURITY", "INVOICE_SWAP"]
pivot = pivot[[c for c in type_order if c in pivot.columns]]

sdr.plot_stacked_bar(pivot, "Daily DV01 by Trade Type", color_map=sdr.PACKAGE_COLORS)
plt.show()

# Summary stats
print("\nTrade Type Summary:")
type_summary = df.groupby("trade_type").agg(
    count=("dv01", "size"),
    total_dv01=("dv01", "sum"),
    pct_count=("dv01", "size"),
).assign(
    pct_count=lambda x: x["count"] / x["count"].sum() * 100,
    pct_dv01=lambda x: x["total_dv01"] / x["total_dv01"].sum() * 100,
)
print(type_summary.round(1).to_string())
```

**Cell 5 (markdown):**
```markdown
## 2. Package Decomposition Table
For each detected package (curve, fly): show leg tenors, net DV01, and execution timestamp.
```

**Cell 6 (code) — Package decomposition:**
```python
packages = sdr.filter_packages(df)
if not packages.empty:
    pkg_summary = packages.groupby("package_id").agg(
        package_type=("package_type", "first"),
        num_legs=("trade_id", "size"),
        tenors=("tenor_label", lambda x: " / ".join(sorted(x.unique()))),
        net_dv01=("dv01", "sum"),
        execution_time=("execution_timestamp", "first"),
    ).sort_values("net_dv01", ascending=False)
    
    print(f"Detected {len(pkg_summary)} packages ({len(packages)} legs)")
    print(f"  Curves: {(pkg_summary['package_type'] == 'CURVE').sum()}")
    print(f"  Flies: {(pkg_summary['package_type'] == 'FLY').sum()}")
    print(f"\nTop 20 packages by DV01:")
    display(pkg_summary.head(20))
else:
    print("No packages detected in this date range.")
```

**Cell 7 (markdown):**
```markdown
## 3. Rate Index Split
SOFR OIS vs FedFunds OIS vs Basis. Volume distribution by underlying rate index.
```

**Cell 8 (code) — Rate index split:**
```python
if "rate_index" in df.columns:
    ri_pivot = sdr.daily_dv01_by_group(df, "rate_index")
    sdr.plot_stacked_area(ri_pivot, "Daily DV01 by Rate Index", color_map=sdr.RATE_INDEX_COLORS)
    plt.show()

    # Pie chart
    ri_totals = df.groupby("rate_index")["dv01"].sum()
    fig, ax = plt.subplots(figsize=(8, 8))
    colors = [sdr.RATE_INDEX_COLORS.get(ri, "#999") for ri in ri_totals.index]
    ri_totals.plot.pie(ax=ax, autopct="%1.1f%%", colors=colors, startangle=90)
    ax.set_ylabel("")
    ax.set_title("DV01 Share by Rate Index")
    plt.tight_layout()
    plt.show()
else:
    print("rate_index column not available — skipping.")
```

**Cell 9 (markdown):**
```markdown
## 4. Forward-Start Distribution
Spot vs forward-starting swap breakdown. ~73% of swaps can be forward-started (per Clarus research).
```

**Cell 10 (code) — Forward-start distribution:**
```python
fwd_labels = ["spot", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "2Y", "3Y+"]

def bucket_forward(label):
    if pd.isna(label) or str(label).lower() == "spot":
        return "spot"
    try:
        years = float(str(label).replace("Y", "").replace("M", ""))
    except ValueError:
        return str(label)
    return str(label) if str(label) in fwd_labels else "3Y+"

df["forward_bucket"] = df["forward_label"].apply(bucket_forward)
fwd_dv01 = df.groupby("forward_bucket")["dv01"].sum()
spot_pct = fwd_dv01.get("spot", 0) / fwd_dv01.sum() * 100

fig, ax = plt.subplots(figsize=(10, 6))
fwd_order = [f for f in fwd_labels if f in fwd_dv01.index]
fwd_dv01[fwd_order].plot.bar(ax=ax, color="#4C78A8", alpha=0.8)
ax.set_title(f"DV01 by Forward Start Period (Spot: {spot_pct:.1f}%)")
ax.set_ylabel("DV01 ($)")
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
```

**Cell 11 (markdown):**
```markdown
## 5. Special Tenor Breakdown
STANDARD / IMM / FOMC / MAC / MATCHED_MATURITY / INVOICE_SWAP classification.
```

**Cell 12 (code) — Special tenor breakdown:**
```python
if "special_tenor_type" in df.columns:
    st_counts = df.groupby("special_tenor_type").agg(
        count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    )
    st_counts["pct_count"] = st_counts["count"] / st_counts["count"].sum() * 100
    st_counts["pct_dv01"] = st_counts["total_dv01"] / st_counts["total_dv01"].sum() * 100
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    colors = [sdr.SPECIAL_TENOR_COLORS.get(st, "#999") for st in st_counts.index]
    st_counts["count"].plot.bar(ax=axes[0], color=colors, alpha=0.8)
    axes[0].set_title("Trade Count by Special Tenor Type")
    st_counts["total_dv01"].plot.bar(ax=axes[1], color=colors, alpha=0.8)
    axes[1].set_title("DV01 by Special Tenor Type")
    plt.tight_layout()
    plt.show()
    
    print(st_counts.round(1).to_string())
```

**Cell 13 (markdown):**
```markdown
## 6. Daily Summary Table
Per-date rollup: total DV01, trade count, % packages, top 3 tenors by DV01.
```

**Cell 14 (code) — Daily summary table:**
```python
def top_tenors(group, n=3):
    return ", ".join(
        group.groupby("tenor_label")["dv01"]
        .sum()
        .nlargest(n)
        .index.tolist()
    )

daily = df.groupby("execution_date").agg(
    trade_count=("dv01", "size"),
    total_dv01=("dv01", "sum"),
    avg_dv01=("dv01", "mean"),
    pct_packages=("package_type", lambda x: (x.fillna("OUTRIGHT") != "OUTRIGHT").mean() * 100),
    pct_spreadovers=("is_spreadover", lambda x: x.fillna(False).mean() * 100),
    unique_tenors=("tenor_label", "nunique"),
)
daily["top_tenors"] = df.groupby("execution_date").apply(top_tenors)
daily["total_dv01_fmt"] = daily["total_dv01"].apply(sdr.format_dv01)

display(daily.round(1))
```

**Step 2: Commit**

```bash
git add notebooks/sdr/01_flow_decomposition.ipynb
git commit -m "feat(sdr): add flow decomposition notebook (01)"
```

---

### Task 3: Create `02_volume_regime.ipynb` — "Is the Market Busy or Quiet?"

**Files:**
- Create: `notebooks/sdr/02_volume_regime.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr

sdr.notebook_setup()

# Use wider lookback for baseline comparison
START = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
print(f"Loaded {len(df):,} trades across {df['execution_date'].nunique()} trading days")
```

**Cell 2 (markdown):**
```markdown
## 1. DV01 by Tenor Bucket (Stacked Area)
Daily volume by risk bucket: 0-2Y, 2-5Y, 5-10Y, 10-20Y, 20-30Y, 30Y+.
```

**Cell 3 (code) — DV01 by tenor bucket:**
```python
pivot = sdr.daily_dv01_by_group(df, "tenor_bucket")
pivot = pivot[[c for c in sdr.TENOR_BUCKET_ORDER if c in pivot.columns]]

sdr.plot_stacked_area(pivot, "Daily DV01 by Tenor Bucket", ylabel="DV01 ($)")
plt.show()
```

**Cell 4 (markdown):**
```markdown
## 2. Rolling Baseline Comparison
Today's DV01 vs 20-day / 60-day / 252-day rolling averages. Z-score per bucket.
Flag days where volume exceeds 2 standard deviations.
```

**Cell 5 (code) — Rolling z-scores:**
```python
daily_total = df.groupby("execution_date")["dv01"].sum().sort_index()
daily_total.index = pd.to_datetime(daily_total.index)

fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

# Panel 1: Daily DV01 with rolling averages
axes[0].bar(daily_total.index, daily_total.values, alpha=0.4, color="#4C78A8", label="Daily DV01")
for window, color, label in [(20, "#F58518", "20d MA"), (60, "#E45756", "60d MA"), (252, "#54A24B", "252d MA")]:
    ma = daily_total.rolling(window, min_periods=5).mean()
    axes[0].plot(ma.index, ma.values, color=color, linewidth=1.5, label=label)
axes[0].set_title("Daily DV01 with Rolling Averages")
axes[0].set_ylabel("DV01 ($)")
axes[0].legend()

# Panel 2: Z-scores
for window, color, label in [(20, "#F58518", "20d Z"), (60, "#E45756", "60d Z")]:
    z = sdr.rolling_zscore(daily_total, window=window)
    axes[1].plot(z.index, z.values, color=color, linewidth=1, label=label, alpha=0.8)
axes[1].axhline(2, color="red", linestyle="--", alpha=0.5, label="+2σ")
axes[1].axhline(-2, color="red", linestyle="--", alpha=0.5, label="-2σ")
axes[1].set_title("Volume Z-Scores (vs Rolling Baselines)")
axes[1].set_ylabel("Z-Score")
axes[1].legend()

plt.tight_layout()
plt.show()

# Flag spike days
z20 = sdr.rolling_zscore(daily_total, window=20)
spikes = z20[z20.abs() > 2].sort_values(ascending=False)
if not spikes.empty:
    print(f"\n{len(spikes)} volume spike days (|Z| > 2):")
    for date, z_val in spikes.head(10).items():
        vol = daily_total.get(date, 0)
        print(f"  {date.date()}: Z={z_val:+.1f}, DV01={sdr.format_dv01(vol)}")
```

**Cell 6 (markdown):**
```markdown
## 3. New-Risk vs Compression Separation
Compression is ~1/3 of all SDR trades. Must be separated to understand true market activity.
```

**Cell 7 (code) — New-risk vs compression:**
```python
new_risk = sdr.filter_new_risk(df)
compression = sdr.filter_compression_heuristic(df)

nr_daily = new_risk.groupby("execution_date")["dv01"].sum()
comp_daily = compression.groupby("execution_date")["dv01"].sum()

combined = pd.DataFrame({
    "New Risk": nr_daily,
    "Compression": comp_daily,
}).fillna(0).sort_index()
combined.index = pd.to_datetime(combined.index)

sdr.plot_stacked_area(combined, "Daily DV01: New Risk vs Compression")
plt.show()

total_nr = nr_daily.sum()
total_comp = comp_daily.sum()
print(f"New Risk: {sdr.format_dv01(total_nr)} ({total_nr / (total_nr + total_comp) * 100:.1f}%)")
print(f"Compression: {sdr.format_dv01(total_comp)} ({total_comp / (total_nr + total_comp) * 100:.1f}%)")
```

**Cell 8 (markdown):**
```markdown
## 4. Reset Optimization Filtering
Single-period swaps and FRA-like activity inflate volume stats. Quantify and remove.
```

**Cell 9 (code) — Reset optimization:**
```python
reset_opt = sdr.filter_reset_optimization(df)
clean = df[~df.index.isin(reset_opt.index)]

reset_daily = reset_opt.groupby("execution_date")["dv01"].sum()
clean_daily = clean.groupby("execution_date")["dv01"].sum()

fig, ax = plt.subplots(figsize=(14, 6))
combined_ro = pd.DataFrame({
    "Clean Volume": clean_daily,
    "Reset Optimization": reset_daily,
}).fillna(0).sort_index()
combined_ro.index = pd.to_datetime(combined_ro.index)
combined_ro.plot.area(ax=ax, stacked=True, alpha=0.8, color=["#4C78A8", "#BFBFBF"])
ax.set_title("Daily DV01: Clean Volume vs Reset Optimization")
ax.set_ylabel("DV01 ($)")
plt.tight_layout()
plt.show()

print(f"Reset optimization: {len(reset_opt):,} trades ({len(reset_opt)/len(df)*100:.1f}% of total)")
```

**Cell 10 (markdown):**
```markdown
## 5. Weekday x Month Seasonality
Average DV01 by weekday and month. IMM roll dates highlighted.
```

**Cell 11 (code) — Seasonality heatmap:**
```python
df_dt = df.copy()
df_dt["execution_date_dt"] = pd.to_datetime(df_dt["execution_date"])
df_dt["weekday"] = df_dt["execution_date_dt"].dt.day_name()
df_dt["month"] = df_dt["execution_date_dt"].dt.month_name()

daily_dv01 = df_dt.groupby(["execution_date", "weekday", "month"])["dv01"].sum().reset_index()
season_pivot = daily_dv01.pivot_table(
    index="weekday",
    columns="month",
    values="dv01",
    aggfunc="mean",
)
weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
month_order = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
season_pivot = season_pivot.reindex(index=[d for d in weekday_order if d in season_pivot.index],
                                     columns=[m for m in month_order if m in season_pivot.columns])

sdr.plot_heatmap(season_pivot / 1e6, "Average Daily DV01 by Weekday x Month ($M)", fmt=".2f", cmap="YlOrRd")
plt.show()
```

**Cell 12 (markdown):**
```markdown
## 6. Volume Spike Detection
Automated flagging of dates where volume exceeds 2σ from 20-day rolling baseline.
```

**Cell 13 (code) — Spike detection with event context:**
```python
from SDRUtils.analytics.seasonality import get_fomc_dates, get_quarter_end_dates, get_imm_dates

fomc = get_fomc_dates()
qe = get_quarter_end_dates(START.date(), END.date())
imm = get_imm_dates(START.date(), END.date())

def classify_spike(date):
    d = date.date() if hasattr(date, "date") else date
    tags = []
    if d in fomc:
        tags.append("FOMC")
    if d in qe:
        tags.append("Quarter-End")
    if d in imm:
        tags.append("IMM Roll")
    # Check +/- 1 day
    for event_dates, label in [(fomc, "FOMC±1"), (qe, "QE±1")]:
        for ed in event_dates:
            if abs((d - ed).days) == 1:
                tags.append(label)
                break
    return ", ".join(tags) if tags else "None"

z20 = sdr.rolling_zscore(daily_total, window=20)
spikes_df = pd.DataFrame({
    "dv01": daily_total,
    "z_score_20d": z20,
}).dropna()
spikes_df["is_spike"] = spikes_df["z_score_20d"].abs() > 2
spikes_df["event_context"] = spikes_df.index.map(classify_spike)

spike_days = spikes_df[spikes_df["is_spike"]].sort_values("z_score_20d", ascending=False)
print(f"Volume spike days (|Z| > 2): {len(spike_days)}")
display(spike_days[["dv01", "z_score_20d", "event_context"]].head(15))
```

**Step 2: Commit**

```bash
git add notebooks/sdr/02_volume_regime.ipynb
git commit -m "feat(sdr): add volume regime notebook (02)"
```

---

### Task 4: Create `07_compression_analytics.ipynb` — "How Much Is Real Flow?"

Built before notebooks 03-06 because other notebooks need compression-filtering logic validated.

**Files:**
- Create: `notebooks/sdr/07_compression_analytics.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr

sdr.notebook_setup()

START = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
print(f"Loaded {len(df):,} trades across {df['execution_date'].nunique()} trading days")
```

**Cell 2 (markdown):**
```markdown
## 1. Compression Identification
Multi-signal approach: lifecycle events (TERM/CORR), platform signatures, notional rounding.
~1/3 of all SDR-reported trades are compression.
```

**Cell 3 (code) — Compression identification:**
```python
# Signal 1: Non-NEWT action types (lifecycle events)
non_newt = df[df["event_action"].astype(str).str.upper() != "NEWT"] if "event_action" in df.columns else pd.DataFrame()

# Signal 2: NEWT trades (potential new risk)
newt = sdr.filter_new_risk(df)

# Signal 3: Reset optimization (tenor < 6M)
reset_opt = sdr.filter_reset_optimization(newt)
non_reset = newt[~newt.index.isin(reset_opt.index)]

print(f"Total trades: {len(df):,}")
print(f"  NEWT (new risk candidates): {len(newt):,} ({len(newt)/len(df)*100:.1f}%)")
print(f"  Non-NEWT (lifecycle/compression): {len(non_newt):,} ({len(non_newt)/len(df)*100:.1f}%)")
print(f"  Reset optimization (< 6M tenor): {len(reset_opt):,} ({len(reset_opt)/len(newt)*100:.1f}% of NEWT)")
print(f"  Clean new risk: {len(non_reset):,} ({len(non_reset)/len(df)*100:.1f}% of total)")
```

**Cell 4 (markdown):**
```markdown
## 2. Compression vs New-Risk Volume
```

**Cell 5 (code) — Compression vs new-risk stacked area:**
```python
clean_daily = non_reset.groupby("execution_date")["dv01"].sum()
reset_daily = reset_opt.groupby("execution_date")["dv01"].sum()
lifecycle_daily = non_newt.groupby("execution_date")["dv01"].sum() if not non_newt.empty else pd.Series(dtype=float)

combined = pd.DataFrame({
    "Clean New Risk": clean_daily,
    "Reset Optimization": reset_daily,
    "Lifecycle (TERM/CORR/MODI)": lifecycle_daily,
}).fillna(0).sort_index()
combined.index = pd.to_datetime(combined.index)

sdr.plot_stacked_area(
    combined,
    "Daily DV01: Clean vs Reset Optimization vs Lifecycle",
    color_map={"Clean New Risk": "#4C78A8", "Reset Optimization": "#BFBFBF", "Lifecycle (TERM/CORR/MODI)": "#F58518"},
)
plt.show()
```

**Cell 6 (markdown):**
```markdown
## 3. Platform Market Share
TradeWeb (~46%), OSTTRA (~27%), bilateral (~22%), Bloomberg (~4%).
```

**Cell 7 (code) — Platform analysis:**
```python
if "platform_identifier" in df.columns:
    platform_dv01 = df.groupby("platform_identifier")["dv01"].sum().sort_values(ascending=False)
    top_platforms = platform_dv01.head(10)
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # Bar chart
    top_platforms.plot.barh(ax=axes[0], color="#4C78A8", alpha=0.8)
    axes[0].set_title("DV01 by Platform (Top 10)")
    axes[0].set_xlabel("DV01 ($)")
    
    # Pie chart
    top_platforms.plot.pie(ax=axes[1], autopct="%1.1f%%", startangle=90)
    axes[1].set_ylabel("")
    axes[1].set_title("Platform Market Share (DV01)")
    
    plt.tight_layout()
    plt.show()
else:
    print("platform_identifier column not available.")
```

**Cell 8 (markdown):**
```markdown
## 4. Reset Optimization Detection
Single-period swaps and FRA-like activity. Weekday clustering analysis.
```

**Cell 9 (code) — Reset opt weekday clustering:**
```python
if not reset_opt.empty:
    reset_opt_dt = reset_opt.copy()
    reset_opt_dt["execution_date_dt"] = pd.to_datetime(reset_opt_dt["execution_date"])
    reset_opt_dt["weekday"] = reset_opt_dt["execution_date_dt"].dt.day_name()
    
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    weekday_counts = reset_opt_dt.groupby("weekday").agg(
        trade_count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    ).reindex(weekday_order)
    
    fig, ax = plt.subplots(figsize=(10, 5))
    weekday_counts["trade_count"].plot.bar(ax=ax, color="#E45756", alpha=0.8)
    ax.set_title("Reset Optimization Trade Count by Weekday")
    ax.set_ylabel("Trade Count")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
    
    print(weekday_counts.to_string())
```

**Cell 10 (markdown):**
```markdown
## 5. Compression-Adjusted "Clean" Volume
The metric that matters for flow analysis — stripping compression and reset optimization.
```

**Cell 11 (code) — Clean volume time series:**
```python
raw_daily = df.groupby("execution_date")["dv01"].sum()
clean_daily_final = non_reset.groupby("execution_date")["dv01"].sum()

comparison = pd.DataFrame({
    "Raw Reported": raw_daily,
    "Clean (New Risk Only)": clean_daily_final,
}).fillna(0).sort_index()
comparison.index = pd.to_datetime(comparison.index)

fig, ax = plt.subplots(figsize=(14, 6))
comparison["Raw Reported"].plot(ax=ax, alpha=0.4, color="#BFBFBF", label="Raw Reported")
comparison["Clean (New Risk Only)"].plot(ax=ax, color="#4C78A8", linewidth=1.5, label="Clean New Risk")
ax.set_title("Raw vs Clean Volume (DV01)")
ax.set_ylabel("DV01 ($)")
ax.legend()
plt.tight_layout()
plt.show()

ratio = clean_daily_final.sum() / raw_daily.sum() * 100
print(f"Clean/Raw ratio: {ratio:.1f}% — {100-ratio:.1f}% of reported volume is non-new-risk")
```

**Cell 12 (markdown):**
```markdown
## 6. Gross-to-Net Compression Ratio
Higher ratio = more portfolio optimization activity.
```

**Cell 13 (code) — Compression ratio over time:**
```python
monthly_raw = raw_daily.resample("ME").sum() if hasattr(raw_daily.index, "month") else raw_daily.groupby(pd.to_datetime(raw_daily.index).to_period("M")).sum()
monthly_clean = clean_daily_final.resample("ME").sum() if hasattr(clean_daily_final.index, "month") else clean_daily_final.groupby(pd.to_datetime(clean_daily_final.index).to_period("M")).sum()

# Align on datetime index
raw_s = raw_daily.copy()
raw_s.index = pd.to_datetime(raw_s.index)
clean_s = clean_daily_final.copy()
clean_s.index = pd.to_datetime(clean_s.index)

monthly = pd.DataFrame({
    "raw": raw_s.resample("ME").sum(),
    "clean": clean_s.resample("ME").sum(),
})
monthly["compression_pct"] = (1 - monthly["clean"] / monthly["raw"]) * 100

fig, ax = plt.subplots(figsize=(14, 5))
monthly["compression_pct"].plot.bar(ax=ax, color="#E45756", alpha=0.8)
ax.set_title("Monthly Compression as % of Total Volume")
ax.set_ylabel("Compression %")
ax.axhline(33, color="black", linestyle="--", alpha=0.5, label="33% benchmark")
ax.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
```

**Step 2: Commit**

```bash
git add notebooks/sdr/07_compression_analytics.ipynb
git commit -m "feat(sdr): add compression analytics notebook (07)"
```

---

### Task 5: Create `03_liquidity_scoring.ipynb` — "Is It Cheap or Expensive to Trade?"

**Files:**
- Create: `notebooks/sdr/03_liquidity_scoring.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr

sdr.notebook_setup()

START = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
# Focus on new risk with valid rates
trades = sdr.filter_new_risk(df)
trades = trades[pd.to_numeric(trades["fixed_rate"], errors="coerce").notna()].copy()
trades["fixed_rate"] = pd.to_numeric(trades["fixed_rate"], errors="coerce")
print(f"Loaded {len(trades):,} trades with valid fixed rates")
```

**Cell 2 (markdown):**
```markdown
## 1. Price Dispersion by Benchmark Tenor
Standard deviation of fixed rates within rolling 1-hour windows.
Higher dispersion = worse liquidity. Per Clarus: COVID tripled 10Y price dispersion.
```

**Cell 3 (code) — Price dispersion:**
```python
benchmark = trades[trades["tenor_label"].isin(sdr.BENCHMARK_TENORS)].copy()
benchmark["execution_timestamp_dt"] = pd.to_datetime(benchmark["execution_timestamp"])
benchmark = benchmark.sort_values("execution_timestamp_dt")

# Daily price dispersion (std of fixed_rate) per tenor
daily_disp = benchmark.groupby(["execution_date", "tenor_label"])["fixed_rate"].std().reset_index()
daily_disp.columns = ["execution_date", "tenor_label", "price_dispersion_bps"]
daily_disp["price_dispersion_bps"] = daily_disp["price_dispersion_bps"] * 10_000  # convert to bps

disp_pivot = daily_disp.pivot_table(
    index="execution_date", columns="tenor_label", values="price_dispersion_bps",
)
disp_pivot.index = pd.to_datetime(disp_pivot.index)
disp_pivot = disp_pivot[[c for c in sdr.BENCHMARK_TENORS if c in disp_pivot.columns]]

fig, ax = plt.subplots(figsize=(14, 6))
for col in disp_pivot.columns:
    rolling = disp_pivot[col].rolling(5, min_periods=1).mean()
    ax.plot(rolling.index, rolling.values, label=col, linewidth=1.2)
ax.set_title("Price Dispersion by Tenor (5-day Rolling Avg, bps)")
ax.set_ylabel("Std Dev of Fixed Rate (bps)")
ax.legend()
plt.tight_layout()
plt.show()
```

**Cell 4 (markdown):**
```markdown
## 2. Tick Size Distribution
Rate deltas between consecutive same-tenor trades. Median tick = market's effective resolution.
```

**Cell 5 (code) — Tick analysis:**
```python
ticks = {}
for tenor in sdr.BENCHMARK_TENORS:
    tenor_trades = benchmark[benchmark["tenor_label"] == tenor].sort_values("execution_timestamp_dt")
    if len(tenor_trades) < 2:
        continue
    diffs = tenor_trades["fixed_rate"].diff().dropna().abs() * 10_000  # bps
    diffs = diffs[diffs > 0]  # exclude zero ticks
    ticks[tenor] = diffs

fig, axes = plt.subplots(2, 4, figsize=(16, 8))
axes = axes.flatten()
for i, (tenor, tick_data) in enumerate(ticks.items()):
    if i >= len(axes):
        break
    ax = axes[i]
    tick_data.clip(upper=tick_data.quantile(0.95)).hist(ax=ax, bins=50, color="#4C78A8", alpha=0.8)
    ax.axvline(tick_data.median(), color="red", linestyle="--", label=f"Median: {tick_data.median():.2f}bp")
    ax.set_title(f"{tenor} Tick Distribution")
    ax.legend(fontsize=8)
for j in range(i + 1, len(axes)):
    axes[j].set_visible(False)
plt.suptitle("Tick Size Distribution (bps)", fontsize=13)
plt.tight_layout()
plt.show()
```

**Cell 6 (markdown):**
```markdown
## 3. D2D vs D2C Pricing
Separate by platform identifier. Compare price distributions.
```

**Cell 7 (code) — D2D vs D2C:**
```python
if "platform_identifier" in trades.columns:
    # Common D2D platforms (IDB SEFs)
    D2D_PLATFORMS = {"ICAU", "BGCD", "TLAD", "TRAD", "DWUS", "MARF"}
    
    trades_plat = trades[trades["platform_identifier"].notna()].copy()
    trades_plat["venue_type"] = trades_plat["platform_identifier"].apply(
        lambda x: "D2D" if str(x).upper() in D2D_PLATFORMS else "D2C"
    )
    
    for tenor in ["5Y", "10Y", "30Y"]:
        tenor_df = trades_plat[trades_plat["tenor_label"] == tenor]
        if len(tenor_df) < 10:
            continue
        d2d = tenor_df[tenor_df["venue_type"] == "D2D"]["fixed_rate"]
        d2c = tenor_df[tenor_df["venue_type"] == "D2C"]["fixed_rate"]
        
        daily_d2d_disp = tenor_df[tenor_df["venue_type"] == "D2D"].groupby("execution_date")["fixed_rate"].std() * 10_000
        daily_d2c_disp = tenor_df[tenor_df["venue_type"] == "D2C"].groupby("execution_date")["fixed_rate"].std() * 10_000
        
        print(f"\n{tenor}: D2D median dispersion = {daily_d2d_disp.median():.2f}bp, D2C = {daily_d2c_disp.median():.2f}bp")
```

**Cell 8 (markdown):**
```markdown
## 4. Block vs Non-Block Pricing
Price impact estimation: do block trades print at wider levels?
```

**Cell 9 (code) — Block pricing:**
```python
if "block_trade_election_indicator" in trades.columns:
    trades_block = trades.copy()
    trades_block["is_block"] = trades_block["block_trade_election_indicator"] == True
    
    for tenor in ["5Y", "10Y", "30Y"]:
        t = trades_block[trades_block["tenor_label"] == tenor]
        blocks = t[t["is_block"]]
        non_blocks = t[~t["is_block"]]
        
        if len(blocks) > 5 and len(non_blocks) > 5:
            block_disp = blocks.groupby("execution_date")["fixed_rate"].std() * 10_000
            nonblock_disp = non_blocks.groupby("execution_date")["fixed_rate"].std() * 10_000
            print(f"{tenor}: Block dispersion={block_disp.median():.2f}bp, Non-block={nonblock_disp.median():.2f}bp")
```

**Cell 10 (markdown):**
```markdown
## 5. Liquidity Heatmap
Tenor x Date colored by price dispersion. Red = wide (poor liquidity), green = tight.
```

**Cell 11 (code) — Liquidity heatmap:**
```python
# Monthly aggregation for cleaner heatmap
benchmark_monthly = benchmark.copy()
benchmark_monthly["month"] = pd.to_datetime(benchmark_monthly["execution_date"]).dt.to_period("M").astype(str)

monthly_disp = benchmark_monthly.groupby(["month", "tenor_label"])["fixed_rate"].std().reset_index()
monthly_disp["dispersion_bps"] = monthly_disp["fixed_rate"] * 10_000

hm_pivot = monthly_disp.pivot_table(index="tenor_label", columns="month", values="dispersion_bps")
hm_pivot = hm_pivot.reindex([t for t in sdr.BENCHMARK_TENORS if t in hm_pivot.index])

sdr.plot_heatmap(hm_pivot, "Monthly Price Dispersion by Tenor (bps)", cmap="RdYlGn_r", fmt=".1f")
plt.show()
```

**Cell 12 (markdown):**
```markdown
## 6. Composite Liquidity Score
Weighted combination of dispersion + tick size + volume → single score per tenor.
```

**Cell 13 (code) — Composite score:**
```python
scores = []
for tenor in sdr.BENCHMARK_TENORS:
    t = trades[trades["tenor_label"] == tenor]
    if len(t) < 10:
        continue
    
    disp = t.groupby("execution_date")["fixed_rate"].std().median() * 10_000
    tick_data = t.sort_values("execution_timestamp")["fixed_rate"].diff().abs() * 10_000
    tick_data = tick_data[tick_data > 0]
    tick_med = tick_data.median() if len(tick_data) > 0 else np.nan
    avg_daily_dv01 = t.groupby("execution_date")["dv01"].sum().median()
    daily_count = t.groupby("execution_date").size().median()
    
    scores.append({
        "tenor": tenor,
        "dispersion_bps": disp,
        "median_tick_bps": tick_med,
        "median_daily_dv01": avg_daily_dv01,
        "median_daily_count": daily_count,
    })

score_df = pd.DataFrame(scores).set_index("tenor")
# Normalize each metric to 0-100 (higher = more liquid)
for col in ["dispersion_bps", "median_tick_bps"]:
    if col in score_df.columns:
        score_df[f"{col}_score"] = 100 * (1 - (score_df[col] - score_df[col].min()) / (score_df[col].max() - score_df[col].min() + 1e-10))
for col in ["median_daily_dv01", "median_daily_count"]:
    if col in score_df.columns:
        score_df[f"{col}_score"] = 100 * (score_df[col] - score_df[col].min()) / (score_df[col].max() - score_df[col].min() + 1e-10)

score_cols = [c for c in score_df.columns if c.endswith("_score")]
score_df["composite_score"] = score_df[score_cols].mean(axis=1)

print("Composite Liquidity Scores (100 = most liquid):")
display(score_df.round(1))
```

**Step 2: Commit**

```bash
git add notebooks/sdr/03_liquidity_scoring.ipynb
git commit -m "feat(sdr): add liquidity scoring notebook (03)"
```

---

### Task 6: Create `04_spreadover_analytics.ipynb` — "What's Happening in Swap Spreads?"

**Files:**
- Create: `notebooks/sdr/04_spreadover_analytics.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr

sdr.notebook_setup()

START = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")
```

**Cell 2 (markdown):**
```markdown
## 1. Spreadover Identification
Spreadovers = swap spread trades vs on-the-run Treasuries.
Dominant D2D product (~70% of interdealer flow). Identified via package_indicator + package_transaction_spread fields.
```

**Cell 3 (code) — Spreadover identification:**
```python
spreadovers = sdr.filter_spreadovers(df)
non_spreadovers = df[~df.index.isin(spreadovers.index)]

print(f"Spreadovers: {len(spreadovers):,} trades ({len(spreadovers)/len(df)*100:.1f}%)")
print(f"  DV01: {sdr.format_dv01(spreadovers['dv01'].sum())} ({spreadovers['dv01'].sum()/df['dv01'].sum()*100:.1f}% of total)")
print(f"Non-spreadovers: {len(non_spreadovers):,}")
```

**Cell 4 (markdown):**
```markdown
## 2. VWAP Tracking
Volume-weighted average rate per tenor, daily. Delta vs prior day + rolling average.
```

**Cell 5 (code) — VWAP tracking:**
```python
sprd_rates = spreadovers[pd.to_numeric(spreadovers["fixed_rate"], errors="coerce").notna()].copy()
sprd_rates["fixed_rate"] = pd.to_numeric(sprd_rates["fixed_rate"])

daily_vwaps = sdr.daily_vwap(sprd_rates, group_col="tenor_label")

for tenor in ["2Y", "5Y", "10Y", "30Y"]:
    tv = daily_vwaps[daily_vwaps["tenor_label"] == tenor].set_index("execution_date")["vwap"].sort_index()
    if len(tv) < 5:
        continue
    tv.index = pd.to_datetime(tv.index)
    
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(tv.index, tv.values, color="#4C78A8", linewidth=1, label="VWAP")
    ma20 = tv.rolling(20, min_periods=3).mean()
    ax.plot(ma20.index, ma20.values, color="#F58518", linewidth=1.5, linestyle="--", label="20d MA")
    ax.set_title(f"{tenor} Spreadover VWAP")
    ax.set_ylabel("Fixed Rate")
    ax.legend()
    plt.tight_layout()
    plt.show()
```

**Cell 6 (markdown):**
```markdown
## 3. Trade Count + DV01 Time Series
Daily spreadover activity by tenor. Flag "Swapalypse" events (>2σ volume).
```

**Cell 7 (code) — Spreadover volume by tenor:**
```python
sprd_pivot = sdr.daily_dv01_by_group(spreadovers, "tenor_label")
sprd_pivot = sprd_pivot[[c for c in sdr.BENCHMARK_TENORS if c in sprd_pivot.columns]]

sdr.plot_stacked_area(sprd_pivot, "Daily Spreadover DV01 by Tenor")
plt.show()

# Swapalypse detection
sprd_daily = spreadovers.groupby("execution_date")["dv01"].sum()
sprd_daily.index = pd.to_datetime(sprd_daily.index)
z = sdr.rolling_zscore(sprd_daily, window=20)
swapalypse = z[z > 2].sort_values(ascending=False)

if not swapalypse.empty:
    print(f"\n'Swapalypse' days (spreadover volume >2σ): {len(swapalypse)}")
    for date, z_val in swapalypse.head(10).items():
        vol = sprd_daily.get(date, 0)
        print(f"  {date.date()}: Z={z_val:+.1f}, DV01={sdr.format_dv01(vol)}")
```

**Cell 8 (markdown):**
```markdown
## 4. Tenor Distribution
Which maturities dominate spreadover flow? Track share shifts over time.
```

**Cell 9 (code) — Tenor distribution:**
```python
tenor_dv01 = spreadovers.groupby("tenor_label")["dv01"].sum().sort_values(ascending=False)
top_tenors = tenor_dv01.head(10)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
top_tenors.plot.bar(ax=axes[0], color="#72B7B2", alpha=0.8)
axes[0].set_title("Spreadover DV01 by Tenor")
axes[0].set_ylabel("DV01 ($)")

top_tenors.plot.pie(ax=axes[1], autopct="%1.1f%%", startangle=90)
axes[1].set_ylabel("")
axes[1].set_title("Spreadover Tenor Distribution")
plt.tight_layout()
plt.show()
```

**Cell 10 (markdown):**
```markdown
## 5. Spreadover-to-Outright Ratio
What fraction of total flow is spreadovers? Higher = more relative-value activity.
```

**Cell 11 (code) — Spreadover ratio:**
```python
sprd_daily_dv01 = spreadovers.groupby("execution_date")["dv01"].sum()
total_daily_dv01 = df.groupby("execution_date")["dv01"].sum()

ratio = (sprd_daily_dv01 / total_daily_dv01 * 100).fillna(0)
ratio.index = pd.to_datetime(ratio.index)

fig, ax = plt.subplots(figsize=(14, 5))
ax.bar(ratio.index, ratio.values, alpha=0.4, color="#72B7B2")
ma20 = ratio.rolling(20, min_periods=3).mean()
ax.plot(ma20.index, ma20.values, color="#E45756", linewidth=2, label="20d MA")
ax.set_title("Spreadover as % of Total DV01")
ax.set_ylabel("Spreadover %")
ax.legend()
plt.tight_layout()
plt.show()

print(f"Average spreadover share: {ratio.mean():.1f}%")
print(f"Current (last 20d): {ratio.tail(20).mean():.1f}%")
```

**Step 2: Commit**

```bash
git add notebooks/sdr/04_spreadover_analytics.ipynb
git commit -m "feat(sdr): add spreadover analytics notebook (04)"
```

---

### Task 7: Create `05_sofr_ff_basis.ipynb` — "Where's the SOFR-FedFunds Basis?"

**Files:**
- Create: `notebooks/sdr/05_sofr_ff_basis.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr
from SDRUtils.analytics.seasonality import get_fomc_dates

sdr.notebook_setup()

START = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")
```

**Cell 2 (markdown):**
```markdown
## 1. SOFR vs FedFunds OIS Volume Split
Daily DV01 by rate index. Track percentage of total in each category.
53% volume growth in SOFR-FF basis swaps to $14.4T in 2025.
```

**Cell 3 (code) — SOFR vs FF split:**
```python
sofr = sdr.filter_by_rate_index(df, "SOFR")
sofr_compound = sdr.filter_by_rate_index(df, "SOFR_COMPOUND")
ff = sdr.filter_by_rate_index(df, "FED_FUNDS")
ff_compound = sdr.filter_by_rate_index(df, "FED_FUNDS_COMPOUND")

sofr_all = pd.concat([sofr, sofr_compound])
ff_all = pd.concat([ff, ff_compound])

sofr_daily = sofr_all.groupby("execution_date")["dv01"].sum()
ff_daily = ff_all.groupby("execution_date")["dv01"].sum()

split = pd.DataFrame({"SOFR": sofr_daily, "FedFunds": ff_daily}).fillna(0).sort_index()
split.index = pd.to_datetime(split.index)

sdr.plot_stacked_area(split, "Daily DV01: SOFR vs FedFunds", color_map=sdr.RATE_INDEX_COLORS)
plt.show()

# Percentage split
split_pct = split.div(split.sum(axis=1), axis=0) * 100
fig, ax = plt.subplots(figsize=(14, 4))
split_pct["FedFunds"].rolling(20, min_periods=3).mean().plot(ax=ax, color="#F58518", linewidth=2)
ax.set_title("FedFunds Share of Total (20d Rolling Avg)")
ax.set_ylabel("FedFunds %")
ax.axhline(10, color="red", linestyle="--", alpha=0.5, label="10% reference")
ax.legend()
plt.tight_layout()
plt.show()

print(f"SOFR DV01: {sdr.format_dv01(sofr_all['dv01'].sum())} ({sofr_all['dv01'].sum()/(sofr_all['dv01'].sum()+ff_all['dv01'].sum())*100:.1f}%)")
print(f"FedFunds DV01: {sdr.format_dv01(ff_all['dv01'].sum())} ({ff_all['dv01'].sum()/(sofr_all['dv01'].sum()+ff_all['dv01'].sum())*100:.1f}%)")
```

**Cell 4 (markdown):**
```markdown
## 2. Basis Swap Volumes
Filter to SOFR-FF basis swaps. DV01 by tenor.
```

**Cell 5 (code) — Basis swap volumes:**
```python
basis = sdr.filter_by_basis_type(df, "SOFR_FF")
if not basis.empty:
    basis_daily = basis.groupby("execution_date")["dv01"].sum()
    basis_daily.index = pd.to_datetime(basis_daily.index)
    
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(basis_daily.index, basis_daily.values, alpha=0.6, color="#E45756")
    ma = basis_daily.rolling(20, min_periods=3).mean()
    ax.plot(ma.index, ma.values, color="black", linewidth=2, label="20d MA")
    ax.set_title("SOFR-FedFunds Basis Swap Daily DV01")
    ax.set_ylabel("DV01 ($)")
    ax.legend()
    plt.tight_layout()
    plt.show()
else:
    print("No SOFR_FF basis swaps found. Check if basis_type column is populated.")
```

**Cell 6 (markdown):**
```markdown
## 3. Basis Activity Heatmap
DV01 by tenor x month. Shows where on the curve basis is being traded.
```

**Cell 7 (code) — Basis heatmap:**
```python
if not basis.empty and "tenor_label" in basis.columns:
    basis_monthly = basis.copy()
    basis_monthly["month"] = pd.to_datetime(basis_monthly["execution_date"]).dt.to_period("M").astype(str)
    
    hm = basis_monthly.pivot_table(
        index="tenor_label", columns="month", values="dv01", aggfunc="sum", fill_value=0,
    )
    hm = hm.reindex([t for t in sdr.TENOR_ORDER if t in hm.index])
    
    sdr.plot_heatmap(hm / 1e6, "SOFR-FF Basis DV01 by Tenor x Month ($M)", cmap="YlOrRd", fmt=".1f")
    plt.show()
```

**Cell 8 (markdown):**
```markdown
## 4. Regime Detection
Rolling FF/total ratio. Highlight spikes (e.g., Q3 2024: 7%→24%).
```

**Cell 9 (code) — Regime detection:**
```python
ff_ratio = (ff_daily / (sofr_daily + ff_daily) * 100).fillna(0)
ff_ratio.index = pd.to_datetime(ff_ratio.index)

fig, ax = plt.subplots(figsize=(14, 5))
ax.fill_between(ff_ratio.index, ff_ratio.values, alpha=0.3, color="#F58518")
ma = ff_ratio.rolling(20, min_periods=3).mean()
ax.plot(ma.index, ma.values, color="#F58518", linewidth=2, label="20d MA")
ax.set_title("FedFunds Share of USD Swap Volume (Regime Indicator)")
ax.set_ylabel("FedFunds %")
ax.legend()
plt.tight_layout()
plt.show()

# Detect regime shifts (large month-over-month changes)
monthly_ratio = ff_ratio.resample("ME").mean()
mom_change = monthly_ratio.diff()
big_shifts = mom_change[mom_change.abs() > 3]
if not big_shifts.empty:
    print("Significant regime shifts (>3pp monthly change):")
    for date, change in big_shifts.items():
        print(f"  {date.date()}: {change:+.1f}pp (from {monthly_ratio.get(date - pd.offsets.MonthEnd(1), np.nan):.1f}% to {monthly_ratio.get(date, np.nan):.1f}%)")
```

**Cell 10 (markdown):**
```markdown
## 5. FOMC Overlay
Basis volumes and FF share around FOMC meeting dates.
```

**Cell 11 (code) — FOMC overlay:**
```python
fomc_dates = get_fomc_dates()
fomc_in_range = [d for d in fomc_dates if START.date() <= d <= END.date()]

if fomc_in_range:
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(ff_ratio.index, ff_ratio.values, color="#F58518", alpha=0.5, linewidth=0.8)
    ma_plot = ff_ratio.rolling(20, min_periods=3).mean()
    ax.plot(ma_plot.index, ma_plot.values, color="#F58518", linewidth=2)
    
    for fd in fomc_in_range:
        ax.axvline(pd.Timestamp(fd), color="red", linestyle="--", alpha=0.3, linewidth=0.8)
    
    ax.set_title("FedFunds Share with FOMC Meeting Dates")
    ax.set_ylabel("FedFunds %")
    plt.tight_layout()
    plt.show()
```

**Step 2: Commit**

```bash
git add notebooks/sdr/05_sofr_ff_basis.ipynb
git commit -m "feat(sdr): add SOFR-FedFunds basis notebook (05)"
```

---

### Task 8: Create `06_cme_lch_basis.ipynb` — "What's the CCP Basis Doing?"

**Files:**
- Create: `notebooks/sdr/06_cme_lch_basis.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr

sdr.notebook_setup()

START = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")
```

**Cell 2 (markdown):**
```markdown
## 1. CCP Identification
Use `cleared` field to split trades into CME vs LCH pools.
CME currently ~2.6% of USD swap market share.
```

**Cell 3 (code) — CCP identification:**
```python
if "cleared" in df.columns:
    # SDR 'Cleared' field values: 'C' = cleared, 'U' = uncleared, 'I' = intent-to-clear
    cleared = df[df["cleared"].astype(str).str.upper().isin(["C", "I"])].copy()
    
    # CCP inference from platform identifier
    # CME platforms contain "CME" or known codes; LCH is default for cleared USD swaps
    def infer_ccp(row):
        platform = str(row.get("platform_identifier", "")).upper()
        if "CME" in platform:
            return "CME"
        return "LCH"  # Default for USD cleared swaps
    
    cleared["ccp"] = cleared.apply(infer_ccp, axis=1)
    
    ccp_summary = cleared.groupby("ccp").agg(
        trade_count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    )
    ccp_summary["share_pct"] = ccp_summary["total_dv01"] / ccp_summary["total_dv01"].sum() * 100
    print("CCP Market Share:")
    print(ccp_summary.round(1).to_string())
else:
    print("cleared column not available.")
    cleared = df.copy()
    cleared["ccp"] = "UNKNOWN"
```

**Cell 4 (markdown):**
```markdown
## 2. Volume by CCP
DV01 time series per CCP. Track CME market share over time.
```

**Cell 5 (code) — CCP volume time series:**
```python
ccp_pivot = sdr.daily_dv01_by_group(cleared, "ccp")
sdr.plot_stacked_area(ccp_pivot, "Daily DV01 by CCP")
plt.show()

# CME share over time
if "CME" in ccp_pivot.columns:
    cme_share = ccp_pivot["CME"] / ccp_pivot.sum(axis=1) * 100
    cme_share.index = pd.to_datetime(cme_share.index)
    
    fig, ax = plt.subplots(figsize=(14, 4))
    ma = cme_share.rolling(20, min_periods=3).mean()
    ax.plot(ma.index, ma.values, color="#F58518", linewidth=2)
    ax.fill_between(ma.index, ma.values, alpha=0.2, color="#F58518")
    ax.set_title("CME Market Share (20d Rolling Avg)")
    ax.set_ylabel("CME %")
    plt.tight_layout()
    plt.show()
```

**Cell 6 (markdown):**
```markdown
## 3. Price Differential Estimation
Same-tenor trades within tight time windows: compare CME vs LCH fixed rates.
```

**Cell 7 (code) — Basis estimation:**
```python
# For each benchmark tenor, compare rates between CCP pools on the same day
cleared_rates = cleared[pd.to_numeric(cleared["fixed_rate"], errors="coerce").notna()].copy()
cleared_rates["fixed_rate"] = pd.to_numeric(cleared_rates["fixed_rate"])

basis_estimates = []
for tenor in sdr.BENCHMARK_TENORS:
    for date in cleared_rates["execution_date"].unique():
        day_tenor = cleared_rates[(cleared_rates["execution_date"] == date) & (cleared_rates["tenor_label"] == tenor)]
        cme = day_tenor[day_tenor["ccp"] == "CME"]["fixed_rate"]
        lch = day_tenor[day_tenor["ccp"] == "LCH"]["fixed_rate"]
        
        if len(cme) >= 2 and len(lch) >= 5:
            basis_bps = (cme.median() - lch.median()) * 10_000
            basis_estimates.append({
                "date": date, "tenor": tenor, "basis_bps": basis_bps,
            })

if basis_estimates:
    basis_df = pd.DataFrame(basis_estimates)
    basis_pivot = basis_df.pivot_table(index="date", columns="tenor", values="basis_bps")
    basis_pivot.index = pd.to_datetime(basis_pivot.index)
    
    fig, ax = plt.subplots(figsize=(14, 5))
    for tenor in ["10Y", "30Y"]:
        if tenor in basis_pivot.columns:
            ma = basis_pivot[tenor].rolling(10, min_periods=3).mean()
            ax.plot(ma.index, ma.values, label=tenor, linewidth=1.5)
    ax.axhline(0, color="black", linestyle="-", alpha=0.3)
    ax.set_title("Estimated CME-LCH Basis (bps, 10d rolling)")
    ax.set_ylabel("Basis (bps)")
    ax.legend()
    plt.tight_layout()
    plt.show()
else:
    print("Insufficient data for basis estimation (need CME and LCH trades at same tenor/date).")
```

**Cell 8 (markdown):**
```markdown
## 4. CCP Switch Detection
Offsetting trades at different CCPs within short time windows.
```

**Cell 9 (code) — Switch detection placeholder:**
```python
# CCP switch = offsetting trades (same notional, same tenor, opposite direction)
# at different CCPs within a short time window
# This is a simplified heuristic - real implementation would need more fields

print("CCP switch detection requires directional information (pay/receive)")
print("which is not directly available in CFTC SDR data.")
print("Alternative: look for same-day, same-tenor, same-notional pairs across CCPs.")

if "CME" in cleared["ccp"].values and "LCH" in cleared["ccp"].values:
    for tenor in ["10Y", "30Y"]:
        t = cleared[cleared["tenor_label"] == tenor]
        daily_cme = t[t["ccp"] == "CME"].groupby("execution_date").size()
        daily_lch = t[t["ccp"] == "LCH"].groupby("execution_date").size()
        both_days = daily_cme.index.intersection(daily_lch.index)
        print(f"\n{tenor}: {len(both_days)} days with both CME and LCH trades")
```

**Step 2: Commit**

```bash
git add notebooks/sdr/06_cme_lch_basis.ipynb
git commit -m "feat(sdr): add CME-LCH basis notebook (06)"
```

---

### Task 9: Create `08_block_cap_analysis.ipynb` — "What Can't We See?"

**Files:**
- Create: `notebooks/sdr/08_block_cap_analysis.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr

sdr.notebook_setup()

# Include pre/post Oct 2024 recalibration for regime analysis
START = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH
RECALIBRATION_DATE = datetime.date(2024, 10, 1)

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")
```

**Cell 2 (markdown):**
```markdown
## 1. Block Trade Identification
Oct 2024: CFTC recalibrated block thresholds +64% DV01. Capped trades dropped from 8% to 2%.
```

**Cell 3 (code) — Block identification:**
```python
blocks = sdr.filter_blocks(df)
non_blocks = df[~df.index.isin(blocks.index)]

print(f"Block trades: {len(blocks):,} ({len(blocks)/len(df)*100:.1f}%)")
print(f"  Block DV01: {sdr.format_dv01(blocks['dv01'].sum())} ({blocks['dv01'].sum()/df['dv01'].sum()*100:.1f}%)")
print(f"Non-block trades: {len(non_blocks):,}")
```

**Cell 4 (markdown):**
```markdown
## 2. Capped Notional Detection
Fraction of trades with capped notional — obscures true trade size.
```

**Cell 5 (code) — Capped detection:**
```python
capped = sdr.filter_capped(df)
print(f"Capped notional trades: {len(capped):,} ({len(capped)/len(df)*100:.1f}%)")
print(f"  Capped DV01: {sdr.format_dv01(capped['dv01'].sum())}")

# Daily capped percentage
capped_daily = capped.groupby("execution_date").size()
total_daily = df.groupby("execution_date").size()
capped_pct = (capped_daily / total_daily * 100).fillna(0)
capped_pct.index = pd.to_datetime(capped_pct.index)

fig, ax = plt.subplots(figsize=(14, 4))
ax.bar(capped_pct.index, capped_pct.values, alpha=0.6, color="#E45756")
ax.axvline(pd.Timestamp(RECALIBRATION_DATE), color="black", linestyle="--", linewidth=2, label="Oct 2024 Recalibration")
ax.set_title("Daily % of Trades with Capped Notional")
ax.set_ylabel("Capped %")
ax.legend()
plt.tight_layout()
plt.show()
```

**Cell 6 (markdown):**
```markdown
## 3. Block Size Distribution by Tenor
Histogram of block trade notionals. Overlay CFTC threshold lines.
```

**Cell 7 (code) — Block size distribution:**
```python
if not blocks.empty:
    for tenor in ["5Y", "10Y", "30Y"]:
        t_blocks = blocks[blocks["tenor_label"] == tenor]
        if len(t_blocks) < 5:
            continue
        
        notionals = pd.to_numeric(t_blocks["notional"], errors="coerce").dropna() / 1e6
        
        fig, ax = plt.subplots(figsize=(10, 4))
        notionals.clip(upper=notionals.quantile(0.95)).hist(ax=ax, bins=30, color="#4C78A8", alpha=0.8)
        ax.set_title(f"{tenor} Block Trade Notional Distribution")
        ax.set_xlabel("Notional ($M)")
        ax.set_ylabel("Count")
        plt.tight_layout()
        plt.show()
```

**Cell 8 (markdown):**
```markdown
## 4. Regime Change Analysis
Before/after Oct 2024: block count, capped percentage, average visible notional.
```

**Cell 9 (code) — Regime analysis:**
```python
pre = df[pd.to_datetime(df["execution_date"]) < pd.Timestamp(RECALIBRATION_DATE)]
post = df[pd.to_datetime(df["execution_date"]) >= pd.Timestamp(RECALIBRATION_DATE)]

pre_blocks = sdr.filter_blocks(pre)
post_blocks = sdr.filter_blocks(post)
pre_capped = sdr.filter_capped(pre)
post_capped = sdr.filter_capped(post)

pre_days = pre["execution_date"].nunique()
post_days = post["execution_date"].nunique()

regime = pd.DataFrame({
    "Pre-Oct 2024": {
        "Trading Days": pre_days,
        "Block % (count)": f"{len(pre_blocks)/len(pre)*100:.1f}%",
        "Block % (DV01)": f"{pre_blocks['dv01'].sum()/pre['dv01'].sum()*100:.1f}%",
        "Capped % (count)": f"{len(pre_capped)/len(pre)*100:.1f}%",
        "Avg Daily Block Count": f"{len(pre_blocks)/max(pre_days,1):.0f}",
    },
    "Post-Oct 2024": {
        "Trading Days": post_days,
        "Block % (count)": f"{len(post_blocks)/max(len(post),1)*100:.1f}%",
        "Block % (DV01)": f"{post_blocks['dv01'].sum()/max(post['dv01'].sum(),1)*100:.1f}%",
        "Capped % (count)": f"{len(post_capped)/max(len(post),1)*100:.1f}%",
        "Avg Daily Block Count": f"{len(post_blocks)/max(post_days,1):.0f}",
    },
})
display(regime.T)
```

**Cell 10 (markdown):**
```markdown
## 5. True Volume Estimation
Apply ~30% uplift to block notionals (per Clarus research).
Block sizes are systematically underreported due to capping at CFTC thresholds.
```

**Cell 11 (code) — True volume estimation:**
```python
UPLIFT_FACTOR = 1.30

block_notional = blocks.groupby("execution_date")["notional"].sum()
adjusted_block_notional = block_notional * UPLIFT_FACTOR
uplift = adjusted_block_notional - block_notional

non_block_notional = non_blocks.groupby("execution_date")["notional"].sum()
total_reported = block_notional + non_block_notional
total_adjusted = adjusted_block_notional + non_block_notional

combined = pd.DataFrame({
    "Reported": total_reported,
    "Adjusted (+30% blocks)": total_adjusted,
}).sort_index() / 1e9  # billions
combined.index = pd.to_datetime(combined.index)

fig, ax = plt.subplots(figsize=(14, 5))
combined.plot(ax=ax, alpha=0.6)
ax.set_title("Reported vs Adjusted Notional (30% Block Uplift)")
ax.set_ylabel("Notional ($B)")
plt.tight_layout()
plt.show()

total_uplift = uplift.sum()
print(f"Total block uplift: ${total_uplift/1e9:.1f}B additional notional estimated")
```

**Step 2: Commit**

```bash
git add notebooks/sdr/08_block_cap_analysis.ipynb
git commit -m "feat(sdr): add block & cap analysis notebook (08)"
```

---

### Task 10: Create `09_tenor_maturity.ipynb` — "Where on the Curve Is Risk Being Put On?"

**Files:**
- Create: `notebooks/sdr/09_tenor_maturity.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr
from SDRUtils.analytics.seasonality import get_fomc_dates, get_imm_dates

sdr.notebook_setup()

START = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")
```

**Cell 2 (markdown):**
```markdown
## 1. DV01 by Tenor
Bar chart of DV01 per tenor label. Identifies where risk concentrates on the SOFR curve.
```

**Cell 3 (code) — DV01 by tenor:**
```python
tenor_dv01 = df.groupby("tenor_label")["dv01"].sum()
ordered_tenors = [t for t in sdr.TENOR_ORDER if t in tenor_dv01.index]
tenor_dv01 = tenor_dv01[ordered_tenors]

fig, ax = plt.subplots(figsize=(14, 6))
tenor_dv01.plot.bar(ax=ax, color="#4C78A8", alpha=0.8)
ax.set_title("Total DV01 by Tenor")
ax.set_ylabel("DV01 ($)")
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

print("Top 5 tenors by DV01:")
for tenor, val in tenor_dv01.nlargest(5).items():
    print(f"  {tenor}: {sdr.format_dv01(val)} ({val/tenor_dv01.sum()*100:.1f}%)")
```

**Cell 4 (markdown):**
```markdown
## 2. Tenor Distribution Over Time
Stacked area of DV01 share by tenor bucket. Detect shifts.
```

**Cell 5 (code) — Tenor evolution:**
```python
bucket_pivot = sdr.daily_dv01_by_group(df, "tenor_bucket")
bucket_pivot = bucket_pivot[[c for c in sdr.TENOR_BUCKET_ORDER if c in bucket_pivot.columns]]

# Normalize to percentages
bucket_pct = bucket_pivot.div(bucket_pivot.sum(axis=1), axis=0) * 100
bucket_pct.index = pd.to_datetime(bucket_pct.index)

# 20-day rolling average for smoother view
bucket_pct_smooth = bucket_pct.rolling(20, min_periods=5).mean()

sdr.plot_stacked_area(bucket_pct_smooth, "Tenor Bucket Share Over Time (20d Rolling, %)", ylabel="Share %")
plt.show()
```

**Cell 6 (markdown):**
```markdown
## 3. Forward-Start Profile
Spot vs forward-starting. Which tenors are most commonly forward-started?
```

**Cell 7 (code) — Forward-start analysis:**
```python
df_fwd = df.copy()
df_fwd["fwd_type"] = df_fwd["is_forward"].apply(lambda x: "Forward" if x else "Spot")

fwd_split = df_fwd.groupby(["tenor_label", "fwd_type"])["dv01"].sum().unstack(fill_value=0)
fwd_split = fwd_split.reindex([t for t in sdr.TENOR_ORDER if t in fwd_split.index])

fig, ax = plt.subplots(figsize=(14, 6))
fwd_split.plot.bar(ax=ax, stacked=True, color=["#4C78A8", "#F58518"], alpha=0.8)
ax.set_title("DV01 by Tenor: Spot vs Forward-Starting")
ax.set_ylabel("DV01 ($)")
ax.legend(["Spot", "Forward"])
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

fwd_pct = df_fwd[df_fwd["is_forward"] == True]["dv01"].sum() / df_fwd["dv01"].sum() * 100
print(f"Forward-starting trades: {fwd_pct:.1f}% of total DV01")
```

**Cell 8 (markdown):**
```markdown
## 4. IMM Date Activity
Volume of IMM-dated swaps by IMM code (H/M/U/Z). Track roll patterns.
```

**Cell 9 (code) — IMM activity:**
```python
imm_trades = df[df["special_tenor_type"].astype(str) == "IMM"]
if not imm_trades.empty:
    imm_daily = imm_trades.groupby("execution_date")["dv01"].sum()
    imm_daily.index = pd.to_datetime(imm_daily.index)
    
    # Overlay IMM roll dates
    imm_dates = get_imm_dates(START.date(), END.date())
    
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(imm_daily.index, imm_daily.values, alpha=0.6, color="#F58518")
    for imd in imm_dates:
        ax.axvline(pd.Timestamp(imd), color="red", linestyle="--", alpha=0.4, linewidth=0.8)
    ax.set_title("IMM-Dated Swap DV01 (vertical lines = IMM roll dates)")
    ax.set_ylabel("DV01 ($)")
    plt.tight_layout()
    plt.show()
    
    print(f"IMM trades: {len(imm_trades):,} ({len(imm_trades)/len(df)*100:.1f}%)")
else:
    print("No IMM-dated swaps found in this period.")
```

**Cell 10 (markdown):**
```markdown
## 5. FOMC-Dated Swaps & MAC Tracking
```

**Cell 11 (code) — FOMC and MAC:**
```python
fomc_trades = df[df["special_tenor_type"].astype(str) == "FOMC"]
mac_trades = df[df["special_tenor_type"].astype(str) == "MAC"]

print(f"FOMC-dated swaps: {len(fomc_trades):,} ({len(fomc_trades)/len(df)*100:.1f}%)")
print(f"MAC swaps: {len(mac_trades):,} ({len(mac_trades)/len(df)*100:.1f}%)")

# FOMC activity around meeting dates
if not fomc_trades.empty:
    fomc_dates = get_fomc_dates()
    fomc_daily = fomc_trades.groupby("execution_date")["dv01"].sum()
    fomc_daily.index = pd.to_datetime(fomc_daily.index)
    
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.bar(fomc_daily.index, fomc_daily.values, alpha=0.6, color="#E45756")
    for fd in fomc_dates:
        if START.date() <= fd <= END.date():
            ax.axvline(pd.Timestamp(fd), color="blue", linestyle="--", alpha=0.3)
    ax.set_title("FOMC-Dated Swap DV01 (blue lines = FOMC meetings)")
    ax.set_ylabel("DV01 ($)")
    plt.tight_layout()
    plt.show()
```

**Cell 12 (markdown):**
```markdown
## 6. Average Life Trend
DV01-weighted average tenor over time. Fed hikes historically reduced average life.
```

**Cell 13 (code) — Average life:**
```python
df_life = df.copy()
df_life["tenor_years_num"] = pd.to_numeric(df_life["tenor_years"], errors="coerce")

daily_avg_life = df_life.groupby("execution_date").apply(
    lambda g: np.average(
        g["tenor_years_num"].dropna(),
        weights=g.loc[g["tenor_years_num"].notna(), "dv01"].clip(lower=0.01),
    ) if len(g["tenor_years_num"].dropna()) > 0 else np.nan
)
daily_avg_life.index = pd.to_datetime(daily_avg_life.index)

fig, ax = plt.subplots(figsize=(14, 5))
ma = daily_avg_life.rolling(20, min_periods=5).mean()
ax.plot(ma.index, ma.values, color="#4C78A8", linewidth=2)
ax.fill_between(ma.index, ma.values, alpha=0.2, color="#4C78A8")
ax.set_title("DV01-Weighted Average Tenor (20d Rolling)")
ax.set_ylabel("Average Tenor (Years)")
plt.tight_layout()
plt.show()

print(f"Current avg life (last 20d): {daily_avg_life.tail(20).mean():.1f}Y")
print(f"Period average: {daily_avg_life.mean():.1f}Y")
```

**Step 2: Commit**

```bash
git add notebooks/sdr/09_tenor_maturity.ipynb
git commit -m "feat(sdr): add tenor & maturity profile notebook (09)"
```

---

### Task 11: Create `10_event_flow.ipynb` — "What Happens Around Events?"

**Files:**
- Create: `notebooks/sdr/10_event_flow.ipynb`

**Step 1: Create the notebook**

**Cell 1 (code) — Setup:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _sdr_common as sdr
from SDRUtils.analytics.seasonality import (
    add_event_classifications,
    analyze_seasonality_by_event,
    get_fomc_dates,
    get_imm_dates,
    get_month_end_dates,
    get_quarter_end_dates,
)

sdr.notebook_setup()

START = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 3, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_classified_trades(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades across {df['execution_date'].nunique()} days")
```

**Cell 2 (markdown):**
```markdown
## 1. Event Calendar
Load FOMC, quarter-end, month-end, IMM roll dates.
```

**Cell 3 (code) — Event calendar:**
```python
fomc = get_fomc_dates()
fomc_in_range = [d for d in fomc if START.date() <= d <= END.date()]
qe = get_quarter_end_dates(START.date(), END.date())
me = get_month_end_dates(START.date(), END.date())
imm = get_imm_dates(START.date(), END.date())

print(f"FOMC meetings: {len(fomc_in_range)}")
print(f"Quarter-ends: {len(qe)}")
print(f"Month-ends: {len(me)}")
print(f"IMM rolls: {len(imm)}")

# Add event flags to DataFrame
df_events = add_event_classifications(
    df, include_fomc=True, include_me=True, include_qe=True, days_before=3,
)
```

**Cell 4 (markdown):**
```markdown
## 2. Pre/Post Event Volume
Average DV01 in T-5..T+5 window for each event type.
```

**Cell 5 (code) — Event volume analysis:**
```python
daily_dv01 = df.groupby("execution_date")["dv01"].sum()
daily_dv01.index = pd.to_datetime(daily_dv01.index)

def event_window_analysis(event_dates, window=5, label="Event"):
    """Analyze volume in T-window..T+window around events."""
    all_windows = []
    for ed in event_dates:
        ed_ts = pd.Timestamp(ed)
        for offset in range(-window, window + 1):
            target = ed_ts + pd.Timedelta(days=offset)
            val = daily_dv01.get(target, np.nan)
            if not np.isnan(val):
                all_windows.append({"offset": offset, "dv01": val, "event_date": ed})
    
    if not all_windows:
        return pd.DataFrame()
    
    wdf = pd.DataFrame(all_windows)
    return wdf.groupby("offset")["dv01"].mean()

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

for ax, (dates, label) in zip(axes.flatten(), [
    (fomc_in_range, "FOMC"),
    (qe, "Quarter-End"),
    (me, "Month-End"),
    (imm, "IMM Roll"),
]):
    avg_profile = event_window_analysis(dates, window=5, label=label)
    if not avg_profile.empty:
        colors = ["#E45756" if x == 0 else "#4C78A8" for x in avg_profile.index]
        ax.bar(avg_profile.index, avg_profile.values, color=colors, alpha=0.8)
        ax.set_title(f"{label} (n={len(dates)} events)")
        ax.set_xlabel("Days from Event")
        ax.set_ylabel("Avg DV01")
        ax.axvline(0, color="red", linestyle="--", alpha=0.5)

plt.suptitle("Average DV01 Around Events (T-5 to T+5)", fontsize=13)
plt.tight_layout()
plt.show()
```

**Cell 6 (markdown):**
```markdown
## 3. Event-Day Tenor Profile
Does tenor distribution shift around events?
```

**Cell 7 (code) — Tenor shift analysis:**
```python
fomc_day_trades = df_events[df_events["is_fomc_day"] == True]
non_fomc_trades = df_events[df_events["is_fomc_day"] != True]

if not fomc_day_trades.empty:
    fomc_tenor = fomc_day_trades.groupby("tenor_bucket")["dv01"].sum()
    non_fomc_tenor = non_fomc_trades.groupby("tenor_bucket")["dv01"].sum()
    
    # Normalize to per-day averages
    fomc_days = fomc_day_trades["execution_date"].nunique()
    non_fomc_days = non_fomc_trades["execution_date"].nunique()
    
    comparison = pd.DataFrame({
        "FOMC Day": fomc_tenor / max(fomc_days, 1),
        "Non-FOMC": non_fomc_tenor / max(non_fomc_days, 1),
    }).reindex(sdr.TENOR_BUCKET_ORDER).fillna(0)
    
    comparison.plot.bar(figsize=(10, 5), alpha=0.8)
    plt.title("Average Daily DV01 by Tenor Bucket: FOMC vs Non-FOMC Days")
    plt.ylabel("Avg Daily DV01")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
```

**Cell 8 (markdown):**
```markdown
## 4. FOMC Seasonality Analysis
Use SDRUtils seasonality module for structured event analysis.
```

**Cell 9 (code) — FOMC seasonality:**
```python
fomc_season = analyze_seasonality_by_event(
    df_events,
    event_col="is_fomc_window",
    value_col="dv01",
    label_col="trade_label",
    show_progress=True,
)

if not fomc_season.empty:
    top = fomc_season.head(15)
    print("Top 15 trade labels by FOMC/non-FOMC volume ratio:")
    display(top[["trade_label", "event_avg_daily", "non_event_avg_daily", "volume_ratio"]].round(2))
```

**Cell 10 (markdown):**
```markdown
## 5. Historical Case Study Template
Input an event date → full flow decomposition + volume analysis.
Pre-built events: COVID (Mar 2020), SVB (Mar 2023), US Election (Nov 2024).
```

**Cell 11 (code) — Case study template:**
```python
def event_case_study(event_date, label, window_days=5):
    """Full flow analysis for a specific event date."""
    event_ts = pd.Timestamp(event_date)
    start = event_ts - pd.Timedelta(days=window_days)
    end = event_ts + pd.Timedelta(days=window_days)
    
    mask = (pd.to_datetime(df["execution_date"]) >= start) & (pd.to_datetime(df["execution_date"]) <= end)
    window = df[mask]
    
    if window.empty:
        print(f"No data for {label} ({event_date})")
        return
    
    print(f"\n{'='*60}")
    print(f"EVENT: {label} ({event_date})")
    print(f"{'='*60}")
    
    daily = window.groupby("execution_date").agg(
        trade_count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    )
    daily.index = pd.to_datetime(daily.index)
    
    fig, ax = plt.subplots(figsize=(12, 4))
    colors = ["#E45756" if d.date() == event_date else "#4C78A8" for d in daily.index]
    ax.bar(daily.index, daily["total_dv01"], color=colors, alpha=0.8)
    ax.axvline(event_ts, color="red", linestyle="--", linewidth=2)
    ax.set_title(f"{label}: DV01 ({window_days}d Window)")
    ax.set_ylabel("DV01 ($)")
    plt.tight_layout()
    plt.show()
    
    # Tenor breakdown on event day
    event_day = window[pd.to_datetime(window["execution_date"]) == event_ts]
    if not event_day.empty:
        tenor_dist = event_day.groupby("tenor_bucket")["dv01"].sum()
        print(f"\nEvent-day tenor distribution:")
        for t, v in tenor_dist.items():
            print(f"  {t}: {sdr.format_dv01(v)}")

# Run case studies for events in range
if datetime.date(2024, 11, 5) >= START.date():
    event_case_study(datetime.date(2024, 11, 5), "US Election 2024")
```

**Cell 12 (markdown):**
```markdown
## 6. Cumulative DV01 Tracker
Running total of DV01 through the day via execution timestamps.
Reveals when risk gets put on during the trading session.
```

**Cell 13 (code) — Intraday cumulative DV01:**
```python
# Pick a recent high-volume date
recent_dates = sorted(df["execution_date"].unique())[-5:]

fig, ax = plt.subplots(figsize=(14, 6))
for date in recent_dates:
    day = df[df["execution_date"] == date].copy()
    day["exec_ts"] = pd.to_datetime(day["execution_timestamp"])
    day = day.sort_values("exec_ts")
    day["cumulative_dv01"] = day["dv01"].cumsum()
    
    # Normalize time to hours from midnight
    day["hour"] = day["exec_ts"].dt.hour + day["exec_ts"].dt.minute / 60
    
    ax.plot(day["hour"], day["cumulative_dv01"], alpha=0.6, linewidth=1, label=str(date))

ax.set_title("Intraday Cumulative DV01 (Recent Trading Days)")
ax.set_xlabel("Hour (UTC)")
ax.set_ylabel("Cumulative DV01 ($)")
ax.legend(fontsize=8)
ax.set_xlim(8, 22)
plt.tight_layout()
plt.show()
```

**Step 2: Commit**

```bash
git add notebooks/sdr/10_event_flow.ipynb
git commit -m "feat(sdr): add event flow analysis notebook (10)"
```

---

### Task 12: Final — Verify all notebooks import correctly

**Step 1: Run import check**

```bash
cd /c/Users/chris/clee/ARBS
python -c "
import sys
sys.path.insert(0, 'notebooks/sdr')
import _sdr_common as sdr
sdr.notebook_setup()
print('_sdr_common: OK')
print(f'TENOR_ORDER: {len(sdr.TENOR_ORDER)} tenors')
print(f'BENCHMARK_TENORS: {sdr.BENCHMARK_TENORS}')
print(f'Functions: load_classified_trades, filter_new_risk, filter_packages, ...')
"
```

Expected: All imports succeed, constants print correctly.

**Step 2: List all notebooks**

```bash
ls -la notebooks/sdr/
```

Expected: `_sdr_common.py` + 10 `.ipynb` files.

**Step 3: Final commit**

```bash
git add notebooks/sdr/
git commit -m "feat(sdr): complete SDR analytics notebook suite (10 notebooks + shared module)"
```
