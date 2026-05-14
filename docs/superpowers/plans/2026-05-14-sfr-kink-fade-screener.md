# SFR Kink-Fade Live Screener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live screener module + notebook that surfaces actionable BF_6M kink-fading signals using the 0.83 Sharpe production config.

**Architecture:** Thin wrapper over existing `sfr_kink_fade.py` analytics pipeline, packaged into the codebase's standard `build_snapshot()` screener pattern. Config dataclass → `build_snapshot()` → snapshot dataclass with `.to_dataframe()/.to_dict()`. Notebook calls `build_snapshot()` and renders formatted tables + charts.

**Tech Stack:** Python dataclasses, pandas, matplotlib, existing `sfr_kink_fade.py` + `sfr_cal_spread_rv.py` modules.

---

### File Map

| File | Responsibility |
|---|---|
| `RVUtils/SFRKinkFadeScreener/__init__.py` | Package init, re-exports public API |
| `RVUtils/SFRKinkFadeScreener/screener.py` | Config, FlyResult, Snapshot dataclasses + `build_snapshot()` |
| `RVUtils/SFRKinkFadeScreener/_display.py` | Notebook rendering: styled table, strip chart, z-score chart |
| `notebooks/rv/sfr_kink_fade_screener.ipynb` | Interactive screener notebook |

---

### Task 1: Screener Core (`screener.py`)

**Files:**
- Create: `RVUtils/SFRKinkFadeScreener/screener.py`

- [ ] **Step 1: Create the screener module with dataclasses and build_snapshot**

```python
# RVUtils/SFRKinkFadeScreener/screener.py
"""SFR Kink-Fade Live Screener.

Surfaces actionable BF_6M kink-fading signals using the production config
(buy_kink, reds, z>2.0, FOMC+HL+roll blackout). Wraps the existing
sfr_kink_fade.py analytics pipeline into the standard build_snapshot() pattern.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.signals.sfr_cal_spread_rv import (
    SFRCalSpreadRVConfig,
    load_rate_panel,
    compute_fly_curve,
    resolve_cm_to_specific,
)
from BT.signals.sfr_kink_fade import (
    KinkStructure,
    compute_zscore_ts,
    compute_percentile_rank,
    compute_cross_sectional_rank,
    compute_rolling_halflife,
    compute_roll,
    days_to_next_fomc,
    days_to_next_imm_roll,
)

logger = logging.getLogger(__name__)


@dataclass
class KinkFadeScreenerConfig:
    source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    n_contracts: int = 12
    zscore_window: int = 60
    vol_window: int = 20
    halflife_window: int = 120
    lookback_days: int = 180
    entry_zscore: float = 2.0
    fomc_blackout_days: int = 5
    roll_blackout_days: int = 3
    hl_min: float = 3.0
    hl_max: float = 120.0


@dataclass
class FlyResult:
    structure_id: str
    belly_rank: int
    region: str

    level_bp: float
    zscore: float
    percentile: float
    xsection_rank: float
    direction: str

    half_life_days: float
    vol_ann: float
    roll_bp: float

    entry_eligible: bool
    filters: Dict[str, bool]

    zscore_1d_change: float
    level_1d_change: float


@dataclass
class KinkFadeScreenerSnapshot:
    as_of: datetime.date
    results: List[FlyResult]

    strip_rates: Dict[str, float]
    days_to_fomc: int
    days_to_imm_roll: int
    fomc_blackout_active: bool
    roll_blackout_active: bool

    n_actionable: int
    actionable_ids: List[str]

    cm_resolution: Dict[str, str]
    config: KinkFadeScreenerConfig
    run_warnings: List[str] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for r in self.results:
            rows.append({
                "Structure": r.structure_id,
                "Belly": f"SFR{r.belly_rank}",
                "Region": r.region,
                "Level (bp)": round(r.level_bp, 2),
                "Z-Score": round(r.zscore, 2),
                "Pctile": round(r.percentile, 2),
                "XS Rank": round(r.xsection_rank, 2),
                "Direction": r.direction,
                "HL (d)": round(r.half_life_days, 1) if not np.isnan(r.half_life_days) else None,
                "Vol (ann)": round(r.vol_ann, 2) if not np.isnan(r.vol_ann) else None,
                "Roll (bp)": round(r.roll_bp, 2) if not np.isnan(r.roll_bp) else None,
                "Eligible": r.entry_eligible,
                "Z 1d Chg": round(r.zscore_1d_change, 2),
                "Lvl 1d Chg": round(r.level_1d_change, 2),
            })
        return pd.DataFrame(rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "days_to_fomc": self.days_to_fomc,
            "days_to_imm_roll": self.days_to_imm_roll,
            "fomc_blackout_active": self.fomc_blackout_active,
            "roll_blackout_active": self.roll_blackout_active,
            "n_actionable": self.n_actionable,
            "actionable_ids": self.actionable_ids,
            "strip_rates": self.strip_rates,
            "cm_resolution": self.cm_resolution,
            "results": [
                {
                    "structure_id": r.structure_id,
                    "belly_rank": r.belly_rank,
                    "region": r.region,
                    "level_bp": r.level_bp,
                    "zscore": r.zscore,
                    "direction": r.direction,
                    "half_life_days": r.half_life_days,
                    "entry_eligible": r.entry_eligible,
                    "filters": r.filters,
                }
                for r in self.results
            ],
            "run_warnings": self.run_warnings,
        }


def _belly_rank(structure_id: str) -> int:
    parts = structure_id.split("/")
    if len(parts) == 3:
        try:
            return int(parts[1].replace("SFR", ""))
        except ValueError:
            pass
    return 0


def _region(rank: int) -> str:
    if rank <= 4:
        return "whites"
    if rank <= 8:
        return "reds"
    return "greens"


def build_snapshot(
    config: Optional[KinkFadeScreenerConfig] = None,
    *,
    rates_panel: Optional[pd.DataFrame] = None,
    curve_mdp=None,
    ts_builder=None,
) -> KinkFadeScreenerSnapshot:
    """Build a live screener snapshot for the kink-fading strategy."""
    if config is None:
        config = KinkFadeScreenerConfig()

    warnings_list: List[str] = []
    as_of = datetime.date.today()

    # ── Load rates ──
    if rates_panel is None:
        import pytz
        NYC = pytz.timezone("America/New_York")
        rv_config = SFRCalSpreadRVConfig(
            source=config.source, curve=config.curve,
            n_contracts=config.n_contracts, zscore_window=config.zscore_window,
            vol_window=config.vol_window, constant_maturity=True,
        )
        lookback = config.lookback_days + config.zscore_window + 30
        start = NYC.localize(datetime.datetime.combine(
            as_of - datetime.timedelta(days=int(lookback * 1.6)),
            datetime.time(18, 0),
        ))
        try:
            rates_panel = load_rate_panel(
                rv_config, start=start, end="live",
                curve_mdp=curve_mdp, ts_builder=ts_builder,
            )
        except Exception:
            end_dt = NYC.localize(datetime.datetime.combine(as_of, datetime.time(18, 0)))
            rates_panel = load_rate_panel(
                rv_config, start=start, end=end_dt,
                curve_mdp=curve_mdp, ts_builder=ts_builder,
            )
            warnings_list.append("live data unavailable, using latest cached date")

    if rates_panel.empty:
        return KinkFadeScreenerSnapshot(
            as_of=as_of, results=[], strip_rates={},
            days_to_fomc=999, days_to_imm_roll=999,
            fomc_blackout_active=False, roll_blackout_active=False,
            n_actionable=0, actionable_ids=[], cm_resolution={},
            config=config, run_warnings=["no rate data available"],
        )

    actual_as_of = rates_panel.index[-1]

    # ── Strip rates ──
    strip_rates = {col: round(float(rates_panel[col].iloc[-1]), 4)
                   for col in rates_panel.columns}

    # ── CM resolution ──
    cm_res = resolve_cm_to_specific(as_of, n_contracts=config.n_contracts)

    # ── BF_6M curves + analytics ──
    bf6m = compute_fly_curve(rates_panel, gap=2)
    zscore_ts = compute_zscore_ts(bf6m, config.zscore_window)
    pctile_ts = compute_percentile_rank(bf6m, config.zscore_window)
    xsection_ts = compute_cross_sectional_rank(bf6m)
    vol_ts = bf6m.diff().rolling(
        config.vol_window, min_periods=max(10, config.vol_window // 2)
    ).std() * np.sqrt(252)
    roll_vals = compute_roll(bf6m, horizon=1)
    hl_ts = compute_rolling_halflife(bf6m, config.halflife_window)

    # ── Global context ──
    d_fomc = days_to_next_fomc(actual_as_of)
    d_roll = days_to_next_imm_roll(actual_as_of)
    fomc_active = d_fomc <= config.fomc_blackout_days
    roll_active = d_roll <= config.roll_blackout_days

    # ── Build per-fly results ──
    results: List[FlyResult] = []
    for col in bf6m.columns:
        level = float(bf6m[col].iloc[-1]) if not np.isnan(bf6m[col].iloc[-1]) else np.nan
        z = float(zscore_ts[col].iloc[-1]) if col in zscore_ts.columns and not np.isnan(zscore_ts[col].iloc[-1]) else np.nan
        pct = float(pctile_ts[col].iloc[-1]) if col in pctile_ts.columns and not np.isnan(pctile_ts[col].iloc[-1]) else np.nan
        xsr = float(xsection_ts[col].iloc[-1]) if col in xsection_ts.columns and not np.isnan(xsection_ts[col].iloc[-1]) else np.nan
        vol = float(vol_ts[col].iloc[-1]) if col in vol_ts.columns and not np.isnan(vol_ts[col].iloc[-1]) else np.nan
        roll = float(roll_vals[col]) if col in roll_vals.index and not np.isnan(roll_vals[col]) else np.nan
        hl = float(hl_ts[col].iloc[-1]) if col in hl_ts.columns and not np.isnan(hl_ts[col].iloc[-1]) else np.nan

        if np.isnan(level) or np.isnan(z):
            continue

        belly = _belly_rank(col)
        reg = _region(belly)
        direction = "buy_kink" if z < 0 else "sell_kink"

        # 1d changes
        z_prev = float(zscore_ts[col].iloc[-2]) if len(zscore_ts) >= 2 and not np.isnan(zscore_ts[col].iloc[-2]) else z
        lvl_prev = float(bf6m[col].iloc[-2]) if len(bf6m) >= 2 and not np.isnan(bf6m[col].iloc[-2]) else level

        # Filter checks
        f_z = abs(z) >= config.entry_zscore
        f_dir = direction == "buy_kink"
        f_reg = reg == "reds"
        f_fomc = not fomc_active
        f_roll = not roll_active
        f_hl = (not np.isnan(hl)) and config.hl_min <= hl <= config.hl_max

        filters = {
            "z_threshold": f_z,
            "direction": f_dir,
            "region": f_reg,
            "fomc_blackout": f_fomc,
            "roll_blackout": f_roll,
            "hl_gating": f_hl,
        }
        eligible = all(filters.values())

        results.append(FlyResult(
            structure_id=col,
            belly_rank=belly,
            region=reg,
            level_bp=level,
            zscore=z,
            percentile=pct if not np.isnan(pct) else 0.5,
            xsection_rank=xsr if not np.isnan(xsr) else 0.5,
            direction=direction,
            half_life_days=hl,
            vol_ann=vol,
            roll_bp=roll,
            entry_eligible=eligible,
            filters=filters,
            zscore_1d_change=z - z_prev,
            level_1d_change=level - lvl_prev,
        ))

    results.sort(key=lambda r: abs(r.zscore), reverse=True)
    actionable = [r.structure_id for r in results if r.entry_eligible]

    return KinkFadeScreenerSnapshot(
        as_of=as_of,
        results=results,
        strip_rates=strip_rates,
        days_to_fomc=d_fomc,
        days_to_imm_roll=d_roll,
        fomc_blackout_active=fomc_active,
        roll_blackout_active=roll_active,
        n_actionable=len(actionable),
        actionable_ids=actionable,
        cm_resolution=cm_res,
        config=config,
        run_warnings=warnings_list,
    )
```

- [ ] **Step 2: Verify module imports**

Run: `conda run -n stir python -c "from RVUtils.SFRKinkFadeScreener.screener import build_snapshot, KinkFadeScreenerConfig, KinkFadeScreenerSnapshot, FlyResult; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add RVUtils/SFRKinkFadeScreener/screener.py
git commit -m "feat: add SFR kink-fade screener core module"
```

---

### Task 2: Package Init (`__init__.py`)

**Files:**
- Create: `RVUtils/SFRKinkFadeScreener/__init__.py`

- [ ] **Step 1: Create the package init with re-exports**

```python
# RVUtils/SFRKinkFadeScreener/__init__.py
"""SFR Kink-Fade Live Screener.

Surfaces actionable BF_6M kink-fading signals using the production config
(buy_kink, reds SFR5-8, z>2.0, FOMC+HL+roll blackout).
"""
from RVUtils.SFRKinkFadeScreener.screener import (
    FlyResult,
    KinkFadeScreenerConfig,
    KinkFadeScreenerSnapshot,
    build_snapshot,
)

__all__ = [
    "FlyResult",
    "KinkFadeScreenerConfig",
    "KinkFadeScreenerSnapshot",
    "build_snapshot",
]
```

- [ ] **Step 2: Verify package import**

Run: `conda run -n stir python -c "from RVUtils.SFRKinkFadeScreener import build_snapshot, KinkFadeScreenerConfig; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add RVUtils/SFRKinkFadeScreener/__init__.py
git commit -m "feat: add SFR kink-fade screener package init"
```

---

### Task 3: Display Helpers (`_display.py`)

**Files:**
- Create: `RVUtils/SFRKinkFadeScreener/_display.py`

- [ ] **Step 1: Create the display module**

```python
# RVUtils/SFRKinkFadeScreener/_display.py
"""Notebook rendering helpers for the kink-fade screener."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from RVUtils.SFRKinkFadeScreener.screener import KinkFadeScreenerSnapshot


def render_dashboard_table(snapshot: KinkFadeScreenerSnapshot) -> pd.DataFrame:
    """Styled DataFrame for notebook display with color coding.

    Green rows = entry eligible, yellow = approaching (|z|>1.5 buy_kink reds),
    gray = inactive. Reds bold, whites/greens dimmed.
    """
    df = snapshot.to_dataframe()
    if df.empty:
        return df

    def _row_style(row):
        r = snapshot.results[row.name] if row.name < len(snapshot.results) else None
        if r is None:
            return [""] * len(row)

        if r.entry_eligible:
            bg = "background-color: #c8e6c9"
        elif (r.direction == "buy_kink" and r.region == "reds"
              and abs(r.zscore) >= 1.5):
            bg = "background-color: #fff9c4"
        else:
            bg = "background-color: #f5f5f5; color: #999"

        return [bg] * len(row)

    return df.style.apply(_row_style, axis=1).format({
        "Level (bp)": "{:+.2f}",
        "Z-Score": "{:+.2f}",
        "Pctile": "{:.2f}",
        "XS Rank": "{:.2f}",
        "Z 1d Chg": "{:+.2f}",
        "Lvl 1d Chg": "{:+.2f}",
    })


def render_strip_chart(snapshot: KinkFadeScreenerSnapshot, ax=None):
    """Strip rates with BF_6M kink markers."""
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(figsize=(16, 5))

    ranks = sorted(snapshot.strip_rates.keys(), key=lambda k: int(k.replace("SFR", "")))
    x = [int(k.replace("SFR", "")) for k in ranks]
    y = [snapshot.strip_rates[k] for k in ranks]

    ax.plot(x, y, "o-", color="steelblue", linewidth=2, markersize=8, label="Strip Rate")

    for r in snapshot.results:
        parts = r.structure_id.split("/")
        if len(parts) != 3:
            continue
        belly_x = r.belly_rank
        belly_y = snapshot.strip_rates.get(f"SFR{belly_x}", None)
        if belly_y is None:
            continue

        if r.entry_eligible:
            color, marker, size = "green", "^", 14
        elif r.direction == "buy_kink" and r.region == "reds" and abs(r.zscore) >= 1.5:
            color, marker, size = "#FFC107", "^", 12
        elif r.region == "reds":
            color, marker, size = "gray", "o", 6
        else:
            continue

        ax.plot(belly_x, belly_y, marker=marker, color=color, markersize=size,
                zorder=5, markeredgecolor="black", markeredgewidth=0.5)

    ax.axvspan(4.5, 8.5, alpha=0.08, color="blue", label="Reds (SFR5-8)")
    ax.set_xticks(x)
    ax.set_xticklabels(ranks, fontsize=9)
    ax.set_ylabel("Rate (%)")
    ax.set_title(f"SOFR Strip with BF_6M Kink Signals ({snapshot.as_of})", fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    return ax


def render_zscore_chart(
    snapshot: KinkFadeScreenerSnapshot,
    zscore_history: pd.DataFrame,
    ax=None,
    n_days: int = 120,
):
    """Trailing z-score time series for reds flies with threshold bands."""
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(figsize=(16, 6))

    reds_cols = [r.structure_id for r in snapshot.results if r.region == "reds"]
    tail = zscore_history[reds_cols].tail(n_days) if reds_cols else pd.DataFrame()

    if tail.empty:
        ax.text(0.5, 0.5, "No reds data", ha="center", va="center", transform=ax.transAxes)
        return ax

    for col in tail.columns:
        ax.plot(tail.index, tail[col], linewidth=1.2, label=col, alpha=0.8)

    ax.axhline(-2.0, color="green", linestyle="--", linewidth=1, alpha=0.5, label="Entry threshold (−2.0)")
    ax.axhline(-1.5, color="#FFC107", linestyle=":", linewidth=1, alpha=0.5, label="Approaching (−1.5)")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.axhline(1.5, color="#FFC107", linestyle=":", linewidth=1, alpha=0.5)
    ax.axhline(2.0, color="red", linestyle="--", linewidth=1, alpha=0.5, label="sell_kink zone (+2.0)")

    ax.set_title(f"Reds BF_6M Z-Scores (trailing {n_days}d)", fontweight="bold")
    ax.set_ylabel("Z-Score")
    ax.legend(fontsize=8, loc="upper left", ncol=2)
    ax.grid(True, alpha=0.3)
    return ax


def render_filter_panel(snapshot: KinkFadeScreenerSnapshot):
    """Print compact filter status."""
    print(f"Date: {snapshot.as_of}")
    fomc_status = f"BLOCKED ({snapshot.days_to_fomc}d)" if snapshot.fomc_blackout_active else f"CLEAR ({snapshot.days_to_fomc}d to next)"
    roll_status = f"BLOCKED ({snapshot.days_to_imm_roll}d)" if snapshot.roll_blackout_active else f"CLEAR ({snapshot.days_to_imm_roll}d to next)"
    print(f"FOMC:     {fomc_status}")
    print(f"IMM Roll: {roll_status}")
    print(f"Actionable: {snapshot.n_actionable} signals")
    if snapshot.run_warnings:
        for w in snapshot.run_warnings:
            print(f"WARNING: {w}")

    cm = snapshot.cm_resolution
    if cm:
        mapping = ", ".join(f"{k}={v}" for k, v in sorted(cm.items(), key=lambda x: int(x[0].replace("SFR", "")))[:12])
        print(f"Contracts: {mapping}")
```

- [ ] **Step 2: Verify import**

Run: `conda run -n stir python -c "from RVUtils.SFRKinkFadeScreener._display import render_dashboard_table, render_strip_chart, render_zscore_chart, render_filter_panel; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add RVUtils/SFRKinkFadeScreener/_display.py
git commit -m "feat: add kink-fade screener display helpers"
```

---

### Task 4: Screener Notebook

**Files:**
- Create: `notebooks/rv/sfr_kink_fade_screener.ipynb`

- [ ] **Step 1: Create the notebook**

Notebook cells in order:

**Cell 1 (code) — Setup:**
```python
%load_ext autoreload
%autoreload 2

import matplotlib.pyplot as plt
import matplotlib.pylab as pylab
plt.style.use('ggplot')
pylab.rcParams.update({'figure.figsize': (18, 8), 'axes.titlesize': 'large'})

import pandas as pd
import numpy as np
import datetime
import warnings
warnings.filterwarnings('ignore')

import sys
sys.path.append('../../')
```

**Cell 2 (markdown):**
```markdown
# SFR Kink-Fade Live Screener

BF_6M kink-fading signals using the 0.83 Sharpe production config:
- **Direction:** buy_kink only (belly rate too high, fade it down)
- **Region:** Reds (SFR5–8) primary, full strip for context
- **Entry:** |z| > 2.0 on 60d window
- **Filters:** FOMC 5d blackout, HL gating (3–120d), IMM roll 3d blackout

---
## 1. Run Screener
```

**Cell 3 (code) — Config + Run:**
```python
from RVUtils.SFRKinkFadeScreener import build_snapshot, KinkFadeScreenerConfig
from RVUtils.SFRKinkFadeScreener._display import (
    render_dashboard_table, render_strip_chart,
    render_zscore_chart, render_filter_panel,
)

config = KinkFadeScreenerConfig(
    entry_zscore=2.0,
    fomc_blackout_days=5,
    roll_blackout_days=3,
    hl_min=3.0,
    hl_max=120.0,
)

snapshot = build_snapshot(config)
print(f'Snapshot as of: {snapshot.as_of}')
print(f'Actionable signals: {snapshot.n_actionable}')
```

**Cell 4 (markdown):**
```markdown
---
## 2. Filter Status
```

**Cell 5 (code) — Filter Panel:**
```python
render_filter_panel(snapshot)
```

**Cell 6 (markdown):**
```markdown
---
## 3. Signal Dashboard
```

**Cell 7 (code) — Dashboard Table:**
```python
render_dashboard_table(snapshot)
```

**Cell 8 (markdown):**
```markdown
---
## 4. Strip Visualization
```

**Cell 9 (code) — Strip Chart:**
```python
fig, ax = plt.subplots(figsize=(16, 5))
render_strip_chart(snapshot, ax=ax)
plt.tight_layout()
plt.show()
```

**Cell 10 (markdown):**
```markdown
---
## 5. Z-Score History (Reds)
```

**Cell 11 (code) — Z-Score Chart:**
```python
# Compute z-score history for the chart
from BT.signals.sfr_cal_spread_rv import load_rate_panel, SFRCalSpreadRVConfig, compute_fly_curve
from BT.signals.sfr_kink_fade import compute_zscore_ts
import pytz

NYC = pytz.timezone('America/New_York')
rv_config = SFRCalSpreadRVConfig(
    source=config.source, curve=config.curve,
    n_contracts=config.n_contracts, constant_maturity=True,
    zscore_window=config.zscore_window, vol_window=config.vol_window,
)
start = NYC.localize(datetime.datetime.combine(
    snapshot.as_of - datetime.timedelta(days=400), datetime.time(18, 0)))
try:
    rates = load_rate_panel(rv_config, start=start, end='live')
except Exception:
    end_dt = NYC.localize(datetime.datetime.combine(snapshot.as_of, datetime.time(18, 0)))
    rates = load_rate_panel(rv_config, start=start, end=end_dt)

bf6m = compute_fly_curve(rates, gap=2)
zscore_history = compute_zscore_ts(bf6m, config.zscore_window)

fig, ax = plt.subplots(figsize=(16, 6))
render_zscore_chart(snapshot, zscore_history, ax=ax, n_days=120)
plt.tight_layout()
plt.show()
```

**Cell 12 (markdown):**
```markdown
---
## 6. Detailed View (per-fly filter breakdown)
```

**Cell 13 (code) — Filter Breakdown:**
```python
print(f'{"Structure":<25s}  {"Z":>6s}  {"Dir":>10s}  {"Reg":>7s}  {"HL":>6s}  z_ok dir  reg  fomc roll hl   ENTRY')
print('-' * 100)
for r in snapshot.results:
    f = r.filters
    hl_str = f'{r.half_life_days:.0f}d' if not np.isnan(r.half_life_days) else 'N/A'
    checks = f'{"Y" if f["z_threshold"] else ".":>3s}  {"Y" if f["direction"] else ".":>3s}  {"Y" if f["region"] else ".":>3s}  {"Y" if f["fomc_blackout"] else "X":>3s}  {"Y" if f["roll_blackout"] else "X":>3s}  {"Y" if f["hl_gating"] else ".":>3s}'
    flag = ' *** ENTRY ***' if r.entry_eligible else ''
    print(f'  {r.structure_id:<23s}  {r.zscore:>+6.2f}  {r.direction:>10s}  {r.region:>7s}  {hl_str:>6s}  {checks}{flag}')
```

- [ ] **Step 2: Verify notebook loads**

Run: `conda run -n stir python -c "import json; nb = json.load(open('notebooks/rv/sfr_kink_fade_screener.ipynb')); print(f'Cells: {len(nb[\"cells\"])}')"`

Expected: `Cells: 13`

- [ ] **Step 3: Commit**

```bash
git add notebooks/rv/sfr_kink_fade_screener.ipynb
git commit -m "feat: add kink-fade screener notebook"
```

---

### Task 5: Smoke Test

- [ ] **Step 1: Run a quick import + snapshot build test**

Run:
```bash
conda run -n stir python -c "
from RVUtils.SFRKinkFadeScreener import build_snapshot, KinkFadeScreenerConfig
import numpy as np, pandas as pd

# Test with synthetic data
dates = pd.bdate_range('2025-01-01', periods=200, freq='B')
np.random.seed(42)
base = np.linspace(4.0, 3.5, 12)
noise = np.cumsum(np.random.randn(200, 12) * 0.01, axis=0)
rates = pd.DataFrame(base + noise, index=dates, columns=[f'SFR{i+1}' for i in range(12)])

config = KinkFadeScreenerConfig()
snapshot = build_snapshot(config, rates_panel=rates)
print(f'as_of: {snapshot.as_of}')
print(f'results: {len(snapshot.results)}')
print(f'actionable: {snapshot.n_actionable}')
print(f'fomc_blackout: {snapshot.fomc_blackout_active}')
print(f'roll_blackout: {snapshot.roll_blackout_active}')
df = snapshot.to_dataframe()
print(f'dataframe shape: {df.shape}')
d = snapshot.to_dict()
print(f'dict keys: {sorted(d.keys())}')
print('ALL OK')
"
```

Expected: output ending with `ALL OK`, 8 results (BF_6M produces 8 flies from 12 contracts), dataframe shape (8, 14).

- [ ] **Step 2: Commit all files together with final message**

```bash
git add -A RVUtils/SFRKinkFadeScreener/ notebooks/rv/sfr_kink_fade_screener.ipynb
git commit -m "feat: SFR kink-fade live screener module + notebook

build_snapshot() surfaces actionable BF_6M kink-fading signals using
the 0.83 Sharpe production config (buy_kink, reds SFR5-8, z>2.0,
FOMC+HL+roll blackout). Notebook renders signal dashboard, strip chart,
z-score history, and per-fly filter breakdown."
```
