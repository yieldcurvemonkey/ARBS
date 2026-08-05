# Strikeless Vol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and backtest a two-sided systematic system that trades ultra-long forward swap curve slopes as long-dated volatility instruments, with greeks derived only from repriced curves and P&L attributed across four ledgers.

**Architecture:** A new `RVUtils/StrikelessVol/` package layered strictly bottom-up — conventions → universe → panels → greeks → replication → factors → strategy → backtest → report. Greeks come from bumping and repricing rateslib curves (the rateslib backend's own `dv01`/`gamma` raise `NotImplementedError`, so the package does its own shift/translate repricing). The replication simulator talks to a `PricingContext` protocol so it is fully testable against a synthetic pricer with no market data.

**Tech Stack:** Python 3.11 under conda env `stir`, rateslib 2.1.1, pandas, numpy, statsmodels, pytest. Data via existing `MDP.IRSwaps.IRSwapsMDP` (source `GSQUANT-RL`), `gs_quant` Datasets, and `BT/signals/tfp_swap_spread.py`.

**Spec:** `docs/superpowers/specs/2026-08-04-strikeless-vol-design.md`

## Global Constraints

- **Worktree:** all work happens in `C:\Users\chris\clee\ARBS-sv` on branch `feat/strikeless-vol`. Every git command names the tree: `git -C C:\Users\chris\clee\ARBS-sv ...`. Never `cd`.
- **Python:** every invocation is `conda run -n stir python ...`. `conda run` rejects multiline `-c` strings — write a script file instead.
- **Supabase:** set `ARBS_SUPABASE_ENABLED=0` in the environment before importing anything under `Caching/` or `MDP/`, or imports attempt a live connection.
- **Test markers** (from `pytest.ini`): `slow` (>60s), `network` (external services), `db`, `integration`, `live`. Fast gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.
- **Sign conventions** (verbatim from spec, pinned in `conventions.py`, asserted in tests):
  - `ASW = UST yield − matched swap rate` (tool convention).
  - `curve = longer forward − shorter forward`; **negative = inverted**.
  - Flattener = receive longer, pay shorter = the long-convexity side = `sign = +1`.
  - Under tool convention: drag hypothesis ⇒ **negative** slope-on-UMEP coefficient; common-factor ⇒ **positive**.
- **Units:** rates are decimals inside the package (`0.0342`), spreads and vols are basis points, vol is **bp/day** internally and converted to annual normals (`× √252`) only at display boundaries. Every vol crossing a module boundary is a `VolQuote` carrying its label.
- **Data cache:** `notebooks/data/strikeless_vol/*.parquet`. Never write to `data/ts` directly.
- **No new third-party dependencies.**
- **Universe is set by measured provider coverage:** USD and JPY stop at a 30y observed point; EUR and GBP reach 50y. USD `10y10y/25y10y` does not exist and must never be built from extrapolation.

## File Structure

| File | Responsibility |
|---|---|
| `RVUtils/StrikelessVol/__init__.py` | package exports |
| `RVUtils/StrikelessVol/conventions.py` | units, `VolQuote`, sign constants, slope helper |
| `RVUtils/StrikelessVol/universe.py` | `ForwardLeg`, `ForwardPair`, market registries, coverage filter, placebo pairs |
| `RVUtils/StrikelessVol/panels.py` | forward-rate panel, vol panel, UMEP panel, caching |
| `RVUtils/StrikelessVol/greeks.py` | leg construction, DV01, Γ, carry, breakeven — all by repricing |
| `RVUtils/StrikelessVol/vol_metrics.py` | realized vol, implied lookup, BE/realized, BE/implied |
| `RVUtils/StrikelessVol/costs.py` | `CostSchedule` |
| `RVUtils/StrikelessVol/replication.py` | `PricingContext`, path simulator, four ledgers + cross plug |
| `RVUtils/StrikelessVol/factors.py` | changes/levels regressions, frequency ladder, residual z, drift |
| `RVUtils/StrikelessVol/strategy.py` | two-sided conditional rule |
| `RVUtils/StrikelessVol/backtest.py` | static-long control, conditional book, grid, portfolio |
| `RVUtils/StrikelessVol/report.py` | league tables, ledger attribution, distribution diagnostics |
| `MDP/IRSwaps/GSQUANT/rl_basic/build.py` | **modify** — EUR 35/40/50y knots, new `GBP-SONIA` build definition (the rateslib curve definition already exists) |
| `definitions/IRSwaptions.py` | **modify** — EUR/GBP/JPY swaption asset maps |
| `BT/signals/strikeless_vol.py` | daily state runner |
| `tests/test_strikeless_vol_*.py` | one test module per package module |

---

### Task 1: Conventions and units

**Files:**
- Create: `RVUtils/StrikelessVol/__init__.py`
- Create: `RVUtils/StrikelessVol/conventions.py`
- Test: `tests/test_strikeless_vol_conventions.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TRADING_DAYS: float`, `VolQuote` (frozen dataclass with fields `value_bp_day: float`, `measure: str`, `underlying: str`, `window: str`, property `annual_normals -> float`), `annual_normals_to_bp_day(v: float) -> float`, `bp_day_to_annual_normals(v: float) -> float`, `slope_bp(*, short_rate: float, long_rate: float) -> float`, `FLATTENER: int = 1`, `STEEPENER: int = -1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_conventions.py
import math

import pytest

from RVUtils.StrikelessVol.conventions import (
    FLATTENER,
    STEEPENER,
    TRADING_DAYS,
    VolQuote,
    annual_normals_to_bp_day,
    bp_day_to_annual_normals,
    slope_bp,
)


def test_trading_days_is_252():
    assert TRADING_DAYS == 252.0


def test_gs_daily_vol_matches_published_annual_normals():
    # GS IR_SWAPTION_VOLS_V1_STANDARD publishes impliedNormalVolatility as a
    # DAILY bp vol. USD 2y10y on 2026-08-03 was 5.329, quoted on the desk as
    # 84.6 normals.
    assert bp_day_to_annual_normals(5.329) == pytest.approx(84.6, abs=0.05)
    assert annual_normals_to_bp_day(84.6) == pytest.approx(84.6 / math.sqrt(252.0))


def test_conversions_round_trip():
    assert annual_normals_to_bp_day(bp_day_to_annual_normals(4.2)) == pytest.approx(4.2)


def test_vol_quote_requires_full_label():
    with pytest.raises(TypeError):
        VolQuote(5.0)  # measure / underlying / window are mandatory


def test_vol_quote_annual_normals():
    q = VolQuote(
        value_bp_day=5.329,
        measure="implied",
        underlying="USD 2y10y ATM swaption",
        window="atm",
    )
    assert q.annual_normals == pytest.approx(84.6, abs=0.05)


def test_vol_quote_is_frozen():
    q = VolQuote(value_bp_day=1.0, measure="realized", underlying="x", window="63d")
    with pytest.raises(Exception):
        q.value_bp_day = 2.0


def test_slope_is_long_minus_short_and_inverted_is_negative():
    # 10y10y = 4.00%, 20y10y = 3.42% -> inverted -> -58bp
    assert slope_bp(short_rate=0.0400, long_rate=0.0342) == pytest.approx(-58.0)
    assert slope_bp(short_rate=0.0342, long_rate=0.0400) == pytest.approx(58.0)


def test_direction_constants():
    assert FLATTENER == 1
    assert STEEPENER == -1
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_conventions.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'RVUtils.StrikelessVol'`.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/conventions.py
"""Units, sign conventions and the labelled vol type.

Load-bearing conventions for the whole package:

* ``ASW = UST yield - matched swap rate`` (tool convention; the desk convention
  is its negative).
* ``curve = longer forward - shorter forward``; **negative means inverted**.
* A flattener receives the longer forward and pays the shorter. It is the
  long-convexity side and carries ``sign = FLATTENER = +1``.
* Rates are decimals, spreads are basis points, vols are **bp/day** internally.
  Annual normals appear only at display boundaries.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TRADING_DAYS: float = 252.0

FLATTENER: int = 1
STEEPENER: int = -1

__all__ = [
    "TRADING_DAYS",
    "FLATTENER",
    "STEEPENER",
    "VolQuote",
    "annual_normals_to_bp_day",
    "bp_day_to_annual_normals",
    "slope_bp",
]


def annual_normals_to_bp_day(annual_normals: float) -> float:
    """Annualised normal vol (bp/yr) -> daily bp vol."""
    return float(annual_normals) / math.sqrt(TRADING_DAYS)


def bp_day_to_annual_normals(bp_day: float) -> float:
    """Daily bp vol -> annualised normal vol (bp/yr)."""
    return float(bp_day) * math.sqrt(TRADING_DAYS)


def slope_bp(*, short_rate: float, long_rate: float) -> float:
    """Forward slope in bp: (longer forward - shorter forward), both decimals.

    Negative = inverted = the normal state of the ultra-long forward curve.
    """
    return (float(long_rate) - float(short_rate)) * 10_000.0


@dataclass(frozen=True)
class VolQuote:
    """A vol that states what it is computed on.

    Unlabelled floats do not cross module boundaries in this package: a vol is
    only interpretable alongside its measure, underlying and window.
    """

    value_bp_day: float
    measure: str  # "realized" | "implied" | "breakeven"
    underlying: str  # e.g. "USD 20y10y forward par rate"
    window: str  # e.g. "63d" | "atm 2y10y" | "h=25bp"

    @property
    def annual_normals(self) -> float:
        return bp_day_to_annual_normals(self.value_bp_day)
```

```python
# RVUtils/StrikelessVol/__init__.py
"""Strikeless vol: the ultra-long forward slope traded as a vol instrument."""
from RVUtils.StrikelessVol.conventions import (
    FLATTENER,
    STEEPENER,
    TRADING_DAYS,
    VolQuote,
    annual_normals_to_bp_day,
    bp_day_to_annual_normals,
    slope_bp,
)

__all__ = [
    "FLATTENER",
    "STEEPENER",
    "TRADING_DAYS",
    "VolQuote",
    "annual_normals_to_bp_day",
    "bp_day_to_annual_normals",
    "slope_bp",
]
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_conventions.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol tests/test_strikeless_vol_conventions.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): conventions - units, labelled VolQuote, slope sign"
```

---

### Task 2: Universe of forward pairs

**Files:**
- Create: `RVUtils/StrikelessVol/universe.py`
- Test: `tests/test_strikeless_vol_universe.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent).
- Produces:
  - `ForwardLeg(fwd: str, tail: str)` frozen dataclass; properties `label -> str` (`"10Y10Y"`), `fwd_years -> float`, `tail_years -> float`, `end_years -> float`.
  - `ForwardPair(market: str, curve_name: str, short: ForwardLeg, long: ForwardLeg)` frozen dataclass; properties `name -> str` (`"USD 10Y10Y/20Y10Y"`), `required_point_years -> float`.
  - `MARKET_MAX_POINT_YEARS: dict[str, float]` — measured provider coverage.
  - `ALL_PAIRS: tuple[ForwardPair, ...]`, `PLACEBO_PAIRS: tuple[ForwardPair, ...]`.
  - `supported_pairs(pairs, max_point_years) -> list[ForwardPair]`.
  - `tenor_years(label: str) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_universe.py
import pytest

from RVUtils.StrikelessVol.universe import (
    ALL_PAIRS,
    MARKET_MAX_POINT_YEARS,
    PLACEBO_PAIRS,
    ForwardLeg,
    ForwardPair,
    supported_pairs,
    tenor_years,
)


def test_tenor_years():
    assert tenor_years("10Y") == 10.0
    assert tenor_years("6M") == pytest.approx(0.5)
    with pytest.raises(ValueError):
        tenor_years("10X")


def test_leg_geometry():
    leg = ForwardLeg("20Y", "10Y")
    assert leg.label == "20Y10Y"
    assert leg.fwd_years == 20.0
    assert leg.tail_years == 10.0
    assert leg.end_years == 30.0


def test_pair_required_point_is_the_longest_end():
    p = ForwardPair(
        market="USD",
        curve_name="USD-OIS",
        short=ForwardLeg("10Y", "10Y"),
        long=ForwardLeg("20Y", "10Y"),
    )
    assert p.name == "USD 10Y10Y/20Y10Y"
    assert p.required_point_years == 30.0


def test_measured_provider_coverage():
    # From MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx
    assert MARKET_MAX_POINT_YEARS["USD"] == 30.0
    assert MARKET_MAX_POINT_YEARS["JPY"] == 30.0
    assert MARKET_MAX_POINT_YEARS["EUR"] == 50.0
    assert MARKET_MAX_POINT_YEARS["GBP"] == 50.0


def test_usd_25y10y_is_not_in_the_universe():
    # The 35y USD point is not published at any GS tenor. It must never appear.
    usd_ends = {
        p.required_point_years for p in ALL_PAIRS if p.market == "USD"
    }
    assert max(usd_ends) == 30.0


def test_supported_pairs_filters_on_observed_coverage():
    pairs = [
        ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")),
        ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("25Y", "10Y")),
    ]
    kept = supported_pairs(pairs, MARKET_MAX_POINT_YEARS)
    assert len(kept) == 1
    assert kept[0].long.label == "20Y10Y"


def test_every_registered_pair_is_supported_by_its_market():
    for p in ALL_PAIRS:
        assert p.required_point_years <= MARKET_MAX_POINT_YEARS[p.market]


def test_placebo_pairs_are_short_dated_and_disjoint_from_the_universe():
    assert PLACEBO_PAIRS
    for p in PLACEBO_PAIRS:
        assert p.required_point_years <= 10.0
    assert not (set(PLACEBO_PAIRS) & set(ALL_PAIRS))
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_universe.py -v
```
Expected: FAIL — `ImportError: cannot import name 'ForwardLeg'`.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/universe.py
"""The tradeable universe, bounded by measured provider coverage.

Coverage was read from the GS instrument sheet
``MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx``
(33,111 rows, local, no network):

===========  ==================  ==============
market       longest observed    history starts
===========  ==================  ==============
USD (OIS)    30y                 2010-01-04
USD (SOFR)   30y                 2018-04-27
EUR (ESTR)   50y                 ~2019
JPY (TONA)   30y                 2010-01-04
GBP (OIS)    50y                 2010-01-04
===========  ==================  ==============

USD ``10y10y/25y10y`` needs a 35y point that no GS tenor publishes, so it is
absent here by construction rather than filtered later. Nothing in this package
prices a leg whose end point is beyond its market's observed coverage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

_TENOR_RE = re.compile(r"^(\d+)([DWMY])$", re.IGNORECASE)

_UNIT_YEARS = {"D": 1.0 / 365.0, "W": 7.0 / 365.0, "M": 1.0 / 12.0, "Y": 1.0}

MARKET_MAX_POINT_YEARS: Dict[str, float] = {
    "USD": 30.0,
    "EUR": 50.0,
    "JPY": 30.0,
    "GBP": 50.0,
}

MARKET_CURVES: Dict[str, str] = {
    "USD": "USD-OIS",
    "EUR": "EUR-ESTR",
    "JPY": "JPY-TONAR",
    # GBP-SONIA already exists in Query/IRSwaps/backends/rateslib/
    # rl_curve_definitions_map.py; only the GSQUANT build definition is missing.
    "GBP": "GBP-SONIA",
}


def tenor_years(label: str) -> float:
    """'10Y' -> 10.0, '6M' -> 0.5. Raises on anything else."""
    m = _TENOR_RE.match(str(label).strip())
    if not m:
        raise ValueError(f"Unsupported tenor label: {label!r}")
    return float(m.group(1)) * _UNIT_YEARS[m.group(2).upper()]


@dataclass(frozen=True)
class ForwardLeg:
    """A forward-starting par swap: ``fwd`` forward into a ``tail`` swap."""

    fwd: str
    tail: str

    @property
    def label(self) -> str:
        return f"{self.fwd}{self.tail}".upper()

    @property
    def fwd_years(self) -> float:
        return tenor_years(self.fwd)

    @property
    def tail_years(self) -> float:
        return tenor_years(self.tail)

    @property
    def end_years(self) -> float:
        return self.fwd_years + self.tail_years


@dataclass(frozen=True)
class ForwardPair:
    """A slope: receive ``long``, pay ``short``, DV01-neutral (the flattener)."""

    market: str
    curve_name: str
    short: ForwardLeg
    long: ForwardLeg

    @property
    def name(self) -> str:
        return f"{self.market} {self.short.label}/{self.long.label}"

    @property
    def required_point_years(self) -> float:
        return max(self.short.end_years, self.long.end_years)


def _pair(market: str, s_fwd: str, s_tail: str, l_fwd: str, l_tail: str) -> ForwardPair:
    return ForwardPair(
        market=market,
        curve_name=MARKET_CURVES[market],
        short=ForwardLeg(s_fwd, s_tail),
        long=ForwardLeg(l_fwd, l_tail),
    )


USD_PAIRS = (
    _pair("USD", "10Y", "10Y", "20Y", "10Y"),
    _pair("USD", "15Y", "5Y", "20Y", "10Y"),
    _pair("USD", "5Y", "10Y", "15Y", "10Y"),
)

EUR_PAIRS = (
    _pair("EUR", "10Y", "10Y", "20Y", "10Y"),
    _pair("EUR", "15Y", "5Y", "20Y", "10Y"),
    _pair("EUR", "10Y", "10Y", "25Y", "10Y"),
)

JPY_PAIRS = (
    _pair("JPY", "10Y", "10Y", "20Y", "10Y"),
    _pair("JPY", "15Y", "5Y", "20Y", "10Y"),
)

GBP_PAIRS = (
    _pair("GBP", "15Y", "10Y", "25Y", "10Y"),
    _pair("GBP", "10Y", "10Y", "20Y", "10Y"),
)

ALL_PAIRS = USD_PAIRS + EUR_PAIRS + JPY_PAIRS + GBP_PAIRS

# Short-dated slopes where the convexity story should NOT hold. The identical
# rulebook is run on these; a "signal" that survives here is a calendar or
# curve-shape artifact, not convexity.
PLACEBO_PAIRS = (
    _pair("USD", "1Y", "5Y", "2Y", "5Y"),
    _pair("USD", "2Y", "2Y", "3Y", "2Y"),
)


def supported_pairs(
    pairs: Iterable[ForwardPair],
    max_point_years: Dict[str, float] | None = None,
) -> List[ForwardPair]:
    """Drop any pair whose longest point is not an observed instrument."""
    caps = MARKET_MAX_POINT_YEARS if max_point_years is None else max_point_years
    return [p for p in pairs if p.required_point_years <= caps[p.market]]
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_universe.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/universe.py tests/test_strikeless_vol_universe.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): universe bounded by measured GS instrument coverage"
```

---

### Task 3: Curve definitions — EUR long-end knots and the GBP build definition

**Files:**
- Modify: `MDP/IRSwaps/GSQUANT/rl_basic/build.py` (the `EUR-ESTR` entry's `base_tenors`/`knots`; add a new `GBP-SONIA` entry alongside it)
- Create: `tests/test_strikeless_vol_curve_defs.py`

**Interfaces:**
- Consumes: `RVUtils.StrikelessVol.universe.MARKET_CURVES`, `MARKET_MAX_POINT_YEARS`.
- Produces: buildable curves named `EUR-ESTR` (knots to 50y) and `GBP-SONIA` (knots to 50y) via `MDP.IRSwaps.IRSwapsMDP.IRSwapsMDP(source="GSQUANT-RL").get_pricer({"curve_name": ..., "timestamp": date})`.

**Context the implementer needs:**
- Curve instruments are matched by *name* against a local spreadsheet:
  `MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx`
  (columns `assetId`, `name`, `historyStartDate`). No network needed to check a name exists.
- Verified naming: `EUR Swap EuroSTR 1y ATM 0b to {N}y LCH Cleared` exists for N in 1–30, 35, 40, 45, 50. `GBP Swap OIS 1y ATM 0b to {N}y LCH Cleared` exists for N in 1–30, 35, 40, 45, 50, with `historyStartDate = 2010-01-04` at every one of those points.
- `GBP-SONIA` already exists in `Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py` (`ReferenceRate: "gbp_irs"`, `Calendar: "ldn"`, `DayCounter: "act365f"`, `SettlementDays: 0`), so the new build entry's `reference_key` is `"GBP-SONIA"` and no rateslib definition work is required.
- The existing `EUR-ESTR` build entry lives at roughly `build.py:217-255`; copy its shape exactly (`base_tenors`, `knots`, `extrapolation`, `reference_key`).

- [ ] **Step 1: Write the discovery script and record what exists**

```python
# scripts/sv_check_curve_coverage.py
"""Print the GS instrument names available for each strikeless-vol curve."""
import re
from pathlib import Path

import pandas as pd

COVERAGE = (
    Path(__file__).resolve().parents[1]
    / "MDP" / "IRSwaps" / "GSQUANT" / "COVERAGE"
    / "IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx"
)

PATTERNS = {
    "USD-OIS": r"^USD Swap OIS 1y ATM 0b to (\d+)y LCH Cleared$",
    "EUR-ESTR": r"^EUR Swap EuroSTR 1y ATM 0b to (\d+)y LCH Cleared$",
    "JPY-TONAR": r"^JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to (\d+)y LCH Cleared$",
    "GBP-SONIA": r"^GBP Swap OIS 1y ATM 0b to (\d+)y LCH Cleared$",
}


def main() -> None:
    df = pd.read_excel(COVERAGE)
    df["name"] = df["name"].astype(str)
    for curve, pat in PATTERNS.items():
        sub = df[df["name"].str.match(pat)].copy()
        yrs = sorted(int(re.match(pat, n).group(1)) for n in sub["name"])
        starts = sub["historyStartDate"].astype(str)
        print(f"{curve:10s} n={len(yrs):3d} max={max(yrs) if yrs else 0:3d}y "
              f"earliest_start={starts.min() if len(starts) else 'n/a'}")
        print(f"   tenors: {yrs}")
    # Front-end (meeting-dated) instruments, if any, for GBP.
    gbp_front = [n for n in df["name"] if n.startswith("GBP Swap OIS ATM ")]
    print(f"\nGBP meeting-dated front-end candidates: {gbp_front[:10]}")


if __name__ == "__main__":
    main()
```

Run: `conda run -n stir python scripts/sv_check_curve_coverage.py`
Record the output in the commit message. If GBP meeting-dated front-end names exist, include the first six in `base_tenors`; if they do not, use the annual `0b to 1y..2y` points for the front and say so in a comment — the pairs traded here all start ≥5y forward, so front-end meeting precision does not affect them.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_strikeless_vol_curve_defs.py
import datetime as dt
import re
from pathlib import Path

import pandas as pd
import pytest

from RVUtils.StrikelessVol.universe import MARKET_CURVES, MARKET_MAX_POINT_YEARS

COVERAGE = (
    Path(__file__).resolve().parents[1]
    / "MDP" / "IRSwaps" / "GSQUANT" / "COVERAGE"
    / "IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx"
)


def _definition(curve: str) -> dict:
    from MDP.IRSwaps.GSQUANT.rl_basic.build import GSQUANT_CURVE_MAP

    return GSQUANT_CURVE_MAP[curve]["rl_basic"]


def _knot_years(curve: str) -> list[int]:
    pat = re.compile(r"0b to (\d+)y")
    out = []
    for name in _definition(curve)["knots"]:
        m = pat.search(name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


@pytest.mark.parametrize("market", ["EUR", "GBP"])
def test_long_end_knots_reach_the_market_cap(market):
    curve = MARKET_CURVES[market]
    assert max(_knot_years(curve)) == MARKET_MAX_POINT_YEARS[market]


@pytest.mark.parametrize("market", ["EUR", "GBP", "USD", "JPY"])
def test_every_declared_instrument_exists_in_gs_coverage(market):
    df = pd.read_excel(COVERAGE)
    known = set(df["name"].astype(str))
    d = _definition(MARKET_CURVES[market])
    missing = [n for n in d["base_tenors"] if n not in known]
    assert missing == [], f"{market}: instruments not in GS coverage: {missing}"


def test_gbp_definition_points_at_the_existing_rateslib_definition():
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
        RATESLIB_CURVE_DEFINITIONS,
    )

    ref = _definition("GBP-SONIA")["reference_key"]
    assert ref == "GBP-SONIA"
    assert RATESLIB_CURVE_DEFINITIONS[ref]["Calendar"] == "ldn"


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.parametrize("market,as_of", [("GBP", dt.date(2026, 7, 31)),
                                          ("EUR", dt.date(2026, 7, 31))])
def test_built_curve_reprices_its_own_calibrating_instruments(market, as_of):
    """A curve that cannot reprice its own inputs is not calibrated."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    curve = mdp.get_pricer({"curve_name": MARKET_CURVES[market], "timestamp": as_of})

    rates = {}
    for years in (10, 20, 30, int(MARKET_MAX_POINT_YEARS[market])):
        swap = curve.build_irswap(fwd="0D", tenor=f"{years}Y")
        rates[years] = float(curve.fair_rate(swap))
        assert 0.0 < rates[years] < 0.15, f"{market} {years}Y rate {rates[years]}"

    # The long knots must actually be calibrated, not flat extrapolation off
    # the 30y point: if 50y prices identically to 30y, the instruments did not
    # load and the curve is inventing the ultra-long sector.
    longest = int(MARKET_MAX_POINT_YEARS[market])
    if longest > 30:
        assert abs(rates[longest] - rates[30]) > 1e-6

    # And the curve's last node must reach the market cap, so nothing in the
    # traded universe is priced off the extrapolation stub.
    last_node = max(curve.nodes())
    assert (last_node - as_of).days / 365.0 >= longest - 1.0
```

- [ ] **Step 3: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_curve_defs.py -v -m "not network"
```
Expected: FAIL — `KeyError: 'GBP-SONIA'` from `GSQUANT_CURVE_MAP`, and EUR max knot is 30, not 50.

- [ ] **Step 4: Extend the EUR entry and add the GBP entry**

In `MDP/IRSwaps/GSQUANT/rl_basic/build.py`, append to the `EUR-ESTR` entry's `base_tenors` **and** `knots` lists:

```python
                "EUR Swap EuroSTR 1y ATM 0b to 35y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 40y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 45y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 50y LCH Cleared",
```

Then add a new top-level entry, mirroring the `EUR-ESTR` shape:

```python
    # GBP OIS (SONIA). Instruments verified against
    # COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx: 1-30y plus 35/40/45/50y,
    # every one with historyStartDate 2010-01-04. No meeting-dated front-end
    # instruments are used - every pair traded off this curve starts >=10y
    # forward, so front-end meeting precision cannot reach them.
    "GBP-SONIA": {
        "rl_basic": {
            "base_tenors": [
                f"GBP Swap OIS 1y ATM 0b to {n}y LCH Cleared"
                for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50]
            ],
            "knots": [
                f"GBP Swap OIS 1y ATM 0b to {n}y LCH Cleared"
                for n in [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50]
            ],
            "extrapolation": datetime.timedelta(days=365 * 5),
            "reference_key": "GBP-SONIA",
        }
    },
```

Note the deliberately short `extrapolation` (5y, not 20y): with a 50y last knot there is nothing legitimate to extrapolate toward, and a long extrapolation window is how an unobservable point silently becomes a number.

- [ ] **Step 5: Run the fast tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_curve_defs.py -v -m "not network"
```
Expected: PASS (4 tests; the network test deselected).

- [ ] **Step 6: Run the network test once**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_curve_defs.py -v -m network
```
Expected: PASS. If GS returns nothing for GBP on that date, try the previous business day before assuming the definition is wrong; if it still fails, print `_fetch_rl_basic_gsquant_dataset("GBP-SONIA", [as_of])` and check which names came back empty.

- [ ] **Step 7: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add MDP/IRSwaps/GSQUANT/rl_basic/build.py scripts/sv_check_curve_coverage.py tests/test_strikeless_vol_curve_defs.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): EUR knots to 50y, GBP-SONIA GSQUANT build definition"
```

---

### Task 4: Forward par-rate panels

**Files:**
- Create: `RVUtils/StrikelessVol/panels.py`
- Test: `tests/test_strikeless_vol_panels.py`

**Interfaces:**
- Consumes: `universe.ForwardLeg`, `universe.MARKET_CURVES`.
- Produces:
  - `forward_rate_panel(curve_name, dates, legs, *, source="GSQUANT-RL", mdp=None, cache_path=None, show_progress=False) -> pd.DataFrame` — index `DatetimeIndex` of dates, columns `ForwardLeg.label` (`"10Y10Y"`), values **decimal** par rates. Missing dates dropped, never forward-filled.
  - `spread_panel(rates: pd.DataFrame, pair) -> pd.Series` — bp slope, `long − short`.
  - `PANEL_DIR: Path` = `notebooks/data/strikeless_vol`.

**Context the implementer needs:**
- `IRSwapsMDP(source="GSQUANT-RL")` exposes `get_pricer({"curve_name": str, "timestamp": datetime.date})` → an `RLIRSwapCurve`, and `bulk_get_data({"curve_name": str, "timestamps": [dates]})` → `dict[date, RLIRSwapCurve]`. Bulk is the fast path; it fans out the GS fetch.
- `RLIRSwapCurve.build_irswap(fwd="10Y", tenor="10Y")` returns a par forward-starting `rl.IRS`; `curve.fair_rate(swap)` returns a **decimal** rate.
- Do not forward-fill. A market holiday in one currency is a missing observation, and filling it manufactures a zero-change day that biases every realized-vol and regression estimate downward.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_panels.py
import datetime as dt

import pandas as pd
import pytest

from RVUtils.StrikelessVol.panels import forward_rate_panel, spread_panel
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair


class _FakeSwap:
    def __init__(self, key):
        self.key = key


class _FakeCurve:
    """Returns a rate that encodes the leg, so column mapping is verifiable."""

    RATES = {"10Y10Y": 0.0400, "20Y10Y": 0.0342}

    def build_irswap(self, fwd=None, tenor=None, **kwargs):
        return _FakeSwap(f"{fwd}{tenor}")

    def fair_rate(self, swap):
        return self.RATES[swap.key]


class _FakeMDP:
    def __init__(self):
        self.bulk_calls = 0

    def bulk_get_data(self, request):
        self.bulk_calls += 1
        return {ts: _FakeCurve() for ts in request["timestamps"]}


def test_panel_has_one_column_per_leg_and_decimal_rates():
    dates = [dt.date(2026, 7, 30), dt.date(2026, 7, 31)]
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    mdp = _FakeMDP()

    panel = forward_rate_panel("USD-OIS", dates, legs, mdp=mdp)

    assert list(panel.columns) == ["10Y10Y", "20Y10Y"]
    assert isinstance(panel.index, pd.DatetimeIndex)
    assert panel.loc["2026-07-30", "10Y10Y"] == pytest.approx(0.0400)
    assert panel.loc["2026-07-31", "20Y10Y"] == pytest.approx(0.0342)


def test_panel_uses_one_bulk_call_not_one_per_date():
    dates = [dt.date(2026, 7, d) for d in (27, 28, 29, 30, 31)]
    mdp = _FakeMDP()
    forward_rate_panel("USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=mdp)
    assert mdp.bulk_calls == 1


def test_missing_dates_are_dropped_not_filled():
    class _GappyMDP(_FakeMDP):
        def bulk_get_data(self, request):
            out = super().bulk_get_data(request)
            out.pop(request["timestamps"][1], None)
            return out

    dates = [dt.date(2026, 7, 29), dt.date(2026, 7, 30), dt.date(2026, 7, 31)]
    panel = forward_rate_panel(
        "USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=_GappyMDP()
    )
    assert len(panel) == 2
    assert pd.Timestamp("2026-07-30") not in panel.index


def test_spread_panel_is_long_minus_short_in_bp():
    panel = pd.DataFrame(
        {"10Y10Y": [0.0400], "20Y10Y": [0.0342]},
        index=pd.DatetimeIndex(["2026-08-03"]),
    )
    pair = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))
    s = spread_panel(panel, pair)
    assert s.iloc[0] == pytest.approx(-58.0)


@pytest.mark.network
@pytest.mark.slow
def test_real_usd_panel_matches_desk_levels():
    """The 2026-08-03 USD 10y10y/20y10y slope is deeply inverted (~-58bp)."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    dates = [dt.date(2026, 7, 31), dt.date(2026, 8, 3)]
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    panel = forward_rate_panel(
        "USD-OIS", dates, legs, mdp=IRSwapsMDP(source="GSQUANT-RL")
    )
    assert len(panel) >= 1
    pair = ForwardPair("USD", "USD-OIS", *legs)
    slope = spread_panel(panel, pair)
    assert slope.iloc[-1] < 0.0            # inverted
    assert -120.0 < slope.iloc[-1] < -10.0  # and in the right neighbourhood
```

- [ ] **Step 2: Run the fast tests to verify they fail**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_panels.py -v -m "not network"
```
Expected: FAIL — `ModuleNotFoundError` / `cannot import name 'forward_rate_panel'`.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/panels.py
"""Daily panels: forward par rates, implied vols, and the funding factor.

Panels are constant-maturity by construction (today's 10Y10Y is priced fresh
every day). Positions age; panels do not. Never join one to the other without
going through ``replication``, which owns the aging.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from RVUtils.StrikelessVol.conventions import slope_bp
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

logger = logging.getLogger(__name__)

PANEL_DIR = Path(__file__).resolve().parents[2] / "notebooks" / "data" / "strikeless_vol"

__all__ = ["PANEL_DIR", "forward_rate_panel", "spread_panel"]


def forward_rate_panel(
    curve_name: str,
    dates: Sequence[dt.date],
    legs: Iterable[ForwardLeg],
    *,
    source: str = "GSQUANT-RL",
    mdp=None,
    cache_path: Optional[str | Path] = None,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Constant-maturity forward par rates (decimals), one column per leg.

    Dates the provider cannot serve are dropped. They are never forward-filled:
    a filled day is a manufactured zero-change observation, and every realized
    vol and every changes-regression in this package would inherit the bias.
    """
    legs = list(legs)
    if cache_path and Path(cache_path).exists():
        cached = pd.read_parquet(cache_path)
        cached.index = pd.to_datetime(cached.index)
        wanted = pd.to_datetime(pd.Index(list(dates)))
        if wanted.isin(cached.index).all():
            return cached.loc[cached.index.isin(wanted), [l.label for l in legs]]

    if mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source=source)

    curve_map = mdp.bulk_get_data(
        {"curve_name": curve_name, "timestamps": list(dates)}
    )

    rows: List[dict] = []
    for ts, curve in curve_map.items():
        if curve is None:
            continue
        rec: dict = {}
        try:
            for leg in legs:
                swap = curve.build_irswap(fwd=leg.fwd, tenor=leg.tail)
                rec[leg.label] = float(curve.fair_rate(swap))
        except Exception:  # a curve that cannot price a leg contributes nothing
            logger.warning("skipping %s on %s", curve_name, ts, exc_info=True)
            continue
        rec["date"] = ts.date() if hasattr(ts, "date") else ts
        rows.append(rec)

    if not rows:
        return pd.DataFrame(columns=[l.label for l in legs])

    panel = pd.DataFrame(rows).set_index("date").sort_index()
    panel.index = pd.to_datetime(panel.index)
    panel = panel[[l.label for l in legs]]

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(cache_path)
    return panel


def spread_panel(rates: pd.DataFrame, pair: ForwardPair) -> pd.Series:
    """The pair's slope in bp: longer forward minus shorter forward."""
    s = rates[pair.short.label].astype(float)
    l = rates[pair.long.label].astype(float)
    out = (l - s) * 10_000.0
    out.name = pair.name
    return out
```

- [ ] **Step 4: Run the fast tests to verify they pass**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_panels.py -v -m "not network"
```
Expected: 4 passed.

- [ ] **Step 5: Run the network test**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_panels.py -v -m network
```
Expected: PASS, with the USD slope landing between −120bp and −10bp. If it lands positive, stop: either `spread_panel` has the sign backwards or the legs are swapped, and every downstream sign in the package depends on this.

- [ ] **Step 6: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/panels.py tests/test_strikeless_vol_panels.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): constant-maturity forward par-rate panels"
```

---

### Task 5: Swaption vol panel and the cross-market asset map

**Files:**
- Modify: `definitions/IRSwaptions.py` (add `EUR-ESTR`, `GBP-SONIA`, `JPY-TONAR` entries to `ASSET_IDS_MAP`)
- Create: `scripts/sv_build_swaption_asset_map.py`
- Modify: `RVUtils/StrikelessVol/panels.py` (add `vol_panel`)
- Test: `tests/test_strikeless_vol_vol_panel.py`

**Interfaces:**
- Consumes: `conventions.VolQuote`.
- Produces: `vol_panel(curve_key, structures, start, end, *, cache_path=None) -> pd.DataFrame` — index dates, columns `"2y10y"`-style structure labels, values **daily bp** normal vol; and `implied_quote(panel, structure, date) -> VolQuote`.

**Context the implementer needs:**
- Dataset `IR_SWAPTION_VOLS_V1_STANDARD`, field `impliedNormalVolatility`, is a **daily bp** vol (USD 2y10y = 5.329 on 2026-08-03 = 84.6 annual normals). Do not multiply by √252 inside the panel; the panel is bp/day.
- `Dataset(...).get_coverage()` returns 240 rows with columns `assetId`, `name`, names shaped `"Swaption USD-3m Payer 3m 2y ATM Physically Settled"`. Currencies present: USD, EUR, GBP, JPY, AUD.
- USD history starts **2017-01-03**; verify and record the start date per currency in the script output.
- `_ensure_gs_session()` in `MDP/IRSwaptions/GSQUANT/ql/grid.py` shows the auth pattern (env `GS_CLIENT_ID` / `GS_CLIENT_SECRET` with defaults).

- [ ] **Step 1: Write the asset-map generator**

```python
# scripts/sv_build_swaption_asset_map.py
"""Print ASSET_IDS_MAP entries for EUR/GBP/JPY from the GS swaption coverage.

Run this, paste the printed dict literals into definitions/IRSwaptions.py.
Generated rather than hand-typed: 240 assetIds are not worth transcribing.
"""
import os
import re
from collections import defaultdict

from gs_quant.data import Dataset
from gs_quant.session import GsSession

CURVE_BY_CCY = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR",
    "GBP": "GBP-SONIA",
    "JPY": "JPY-TONAR",
}

NAME_RE = re.compile(
    r"^Swaption (?P<ccy>[A-Z]{3})-\S+ Payer (?P<expiry>\S+) (?P<tail>\S+) ATM"
)


def main() -> None:
    GsSession.use(
        client_id=os.environ["GS_CLIENT_ID"],
        client_secret=os.environ["GS_CLIENT_SECRET"],
        scopes=GsSession.Scopes.get_default(),
    )
    cov = Dataset("IR_SWAPTION_VOLS_V1_STANDARD").get_coverage()
    out = defaultdict(dict)
    for _, row in cov.iterrows():
        m = NAME_RE.match(str(row["name"]))
        if not m:
            continue
        curve = CURVE_BY_CCY.get(m.group("ccy"))
        if curve is None:
            continue
        out[curve][row["assetId"]] = f"{m.group('expiry')} {m.group('tail')}"

    for curve, mapping in sorted(out.items()):
        print(f'    "{curve}": {{')
        for aid, struct in sorted(mapping.items(), key=lambda kv: kv[1]):
            print(f'        "{aid}": "{struct}",')
        print("    },")
        print(f"    # {curve}: {len(mapping)} structures", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
```

Run: `conda run -n stir python scripts/sv_build_swaption_asset_map.py > C:\Users\chris\AppData\Local\Temp\sv_asset_map.txt`
Paste the EUR/GBP/JPY blocks into `ASSET_IDS_MAP` in `definitions/IRSwaptions.py`, leaving the existing USD block untouched. Update the module comment that currently says "v1 ships with USD-SOFR-1D coverage only".

- [ ] **Step 2: Write the failing test**

```python
# tests/test_strikeless_vol_vol_panel.py
import datetime as dt

import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import VolQuote
from RVUtils.StrikelessVol.panels import implied_quote, vol_panel


def test_asset_map_covers_all_four_markets():
    from definitions.IRSwaptions import ASSET_IDS_MAP

    for curve in ("USD-SOFR-1D", "EUR-ESTR", "GBP-SONIA", "JPY-TONAR"):
        assert curve in ASSET_IDS_MAP, f"missing swaption coverage for {curve}"
        assert "2y 10y" in set(ASSET_IDS_MAP[curve].values())
        assert "10y 10y" in set(ASSET_IDS_MAP[curve].values())


def test_implied_quote_is_labelled_and_in_bp_per_day():
    panel = pd.DataFrame(
        {"2y10y": [5.329]}, index=pd.DatetimeIndex(["2026-08-03"])
    )
    q = implied_quote(panel, "2y10y", pd.Timestamp("2026-08-03"), market="USD")
    assert isinstance(q, VolQuote)
    assert q.measure == "implied"
    assert "USD" in q.underlying and "2y10y" in q.underlying
    assert q.value_bp_day == pytest.approx(5.329)
    assert q.annual_normals == pytest.approx(84.6, abs=0.05)


@pytest.mark.network
@pytest.mark.slow
def test_usd_vol_panel_history_starts_2017_and_matches_the_desk_level():
    panel = vol_panel(
        "USD-SOFR-1D",
        ["2y 10y", "10y 10y"],
        dt.date(2016, 1, 1),
        dt.date(2026, 8, 3),
    )
    assert panel.index.min() >= pd.Timestamp("2017-01-01")
    assert panel.index.min() <= pd.Timestamp("2017-01-31")
    assert panel.loc["2026-08-03", "2y10y"] == pytest.approx(5.329, abs=0.05)
    assert len(panel) > 2000
```

- [ ] **Step 3: Run the fast tests to verify they fail**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_vol_panel.py -v -m "not network"
```
Expected: FAIL — `cannot import name 'vol_panel'`.

- [ ] **Step 4: Implement `vol_panel` and `implied_quote` in `panels.py`**

```python
def vol_panel(
    curve_key: str,
    structures: Sequence[str],
    start: dt.date,
    end: dt.date,
    *,
    cache_path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """ATM normal vols in **bp/day**, one column per structure ("2y10y").

    ``structures`` are given in the ASSET_IDS_MAP form ("2y 10y"); columns come
    back whitespace-stripped ("2y10y"). GS publishes impliedNormalVolatility as
    a daily bp vol -- it is stored here exactly as published, and converted to
    annual normals only at display boundaries.
    """
    if cache_path and Path(cache_path).exists():
        cached = pd.read_parquet(cache_path)
        cached.index = pd.to_datetime(cached.index)
        if cached.index.max() >= pd.Timestamp(end):
            return cached.loc[str(start):str(end)]

    import os

    from gs_quant.data import Dataset
    from gs_quant.session import GsSession

    from definitions.IRSwaptions import ASSET_IDS_MAP

    GsSession.use(
        client_id=os.environ["GS_CLIENT_ID"],
        client_secret=os.environ["GS_CLIENT_SECRET"],
        scopes=GsSession.Scopes.get_default(),
    )

    asset_map = ASSET_IDS_MAP[curve_key]
    wanted = {a: s for a, s in asset_map.items() if s in set(structures)}
    if not wanted:
        raise KeyError(f"No assets for {structures} on {curve_key}")

    raw = Dataset("IR_SWAPTION_VOLS_V1_STANDARD").get_data(
        start=start, end=end, assetId=list(wanted)
    )
    if raw is None or raw.empty:
        raise ValueError(f"GS returned no swaption vols for {curve_key} {start}..{end}")

    df = raw.copy()
    df["structure"] = df["assetId"].map(wanted).str.replace(" ", "", regex=False)
    df["bp_day"] = pd.to_numeric(df["impliedNormalVolatility"], errors="coerce")
    df = df.dropna(subset=["structure", "bp_day"])
    panel = (
        df.reset_index()
        .pivot_table(index="date", columns="structure", values="bp_day", aggfunc="last")
        .sort_index()
    )
    panel.index = pd.to_datetime(panel.index)

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(cache_path)
    return panel


def implied_quote(
    panel: pd.DataFrame, structure: str, date, *, market: str
) -> "VolQuote":
    """One labelled implied vol from the panel."""
    from RVUtils.StrikelessVol.conventions import VolQuote

    return VolQuote(
        value_bp_day=float(panel.loc[date, structure]),
        measure="implied",
        underlying=f"{market} {structure} ATM swaption (normal)",
        window="atm",
    )
```

Add `"vol_panel"` and `"implied_quote"` to `__all__`. The `raw.reset_index()` call assumes gs_quant returns a `DatetimeIndex` named `date` — if the column is already present, `reset_index` still works; if the index is unnamed, rename it to `date` before pivoting.

- [ ] **Step 5: Run the fast tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_vol_panel.py -v -m "not network"
```
Expected: 2 passed.

- [ ] **Step 6: Run the network test and record the per-market history starts**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_vol_panel.py -v -m network
```
Expected: PASS. Then run the same `vol_panel` call for EUR/GBP/JPY over 2010–2026 and record each market's first date in the commit message — those dates bound every vol-conditioned claim in this study.

- [ ] **Step 7: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add definitions/IRSwaptions.py scripts/sv_build_swaption_asset_map.py RVUtils/StrikelessVol/panels.py tests/test_strikeless_vol_vol_panel.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): cross-market swaption asset map and bp/day vol panel"
```

---

### Task 6: UMEP (funding factor) panel

**Files:**
- Modify: `RVUtils/StrikelessVol/panels.py` (add `umep_panel`)
- Test: `tests/test_strikeless_vol_umep.py`

**Interfaces:**
- Consumes: `BT.signals.tfp_swap_spread.build_tfp_history`, `compute_tfp_regression`.
- Produces: `umep_panel(start, end, *, cache_path=None, **kwargs) -> pd.DataFrame` with columns `umep_bp_per_year`, `zds_bp`, `r_squared`, plus the passthrough `mmss_*`/`dev_*` columns.

**Context the implementer needs:**
- `BT/signals/tfp_swap_spread.py` already implements the Dallas Fed / JPM cross-sectional regression: `swap_spread_m = slope · mod_dur_m + intercept`, with `TFP = −slope` and `ZDS = intercept`, over tenors `["2Y","3Y","5Y","7Y","10Y","30Y"]`. It is USD-only (it needs a UST curve).
- `build_tfp_history(start_date, end_date, curve_mdp=None, usts_mdp=None, cache_path=None, ...)` defaults to `IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")` and `FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")` and returns a date-indexed frame with `tfp`, `zds`, `slope`, `r_squared`, `mmss_*`, `dur_*`, `baseline_*`, `dev_*`.
- **The sign must be established, not assumed.** The spec's hypothesis test (H2) depends on which direction UMEP points under the tool convention. Task 6 does not decide it — it *records* it, by asserting the observed relationship between `tfp` and the raw `mmss_30Y` level on real data and writing the observed sign into the module docstring.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_umep.py
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.panels import umep_panel


def test_umep_panel_wraps_the_existing_tfp_history(monkeypatch):
    fake = pd.DataFrame(
        {
            "tfp": [2.0, 4.3],
            "zds": [-10.0, -12.0],
            "slope": [-2.0, -4.3],
            "r_squared": [0.9, 0.95],
            "mmss_30Y": [60.0, 74.6],
        },
        index=pd.DatetimeIndex(["2024-02-01", "2026-02-01"]),
    )
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: fake)

    out = umep_panel(dt.date(2024, 1, 1), dt.date(2026, 2, 1))

    assert "umep_bp_per_year" in out.columns
    assert out["umep_bp_per_year"].tolist() == [2.0, 4.3]
    assert out["zds_bp"].tolist() == [-10.0, -12.0]


def test_umep_panel_is_empty_safe(monkeypatch):
    import RVUtils.StrikelessVol.panels as panels

    monkeypatch.setattr(panels, "_build_tfp_history", lambda *a, **k: pd.DataFrame())
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2024, 2, 1))
    assert out.empty


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.db
def test_real_umep_rises_over_the_2024_2026_window_and_sign_is_recorded():
    """Dallas Fed WP 2613: the funding premium roughly doubled by Feb 2026."""
    out = umep_panel(dt.date(2024, 1, 1), dt.date(2026, 8, 3))
    assert len(out) > 300
    early = out["umep_bp_per_year"].head(60).mean()
    late = out["umep_bp_per_year"].tail(60).mean()
    assert np.isfinite(early) and np.isfinite(late)
    # record the observed direction; the assertion is that it is measurable and
    # monotone in the published direction, not that it hits a target value
    assert late > early
```

- [ ] **Step 2: Run the fast tests to verify they fail**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_umep.py -v -m "not network"
```
Expected: FAIL — `cannot import name 'umep_panel'`.

- [ ] **Step 3: Implement `umep_panel`**

```python
def _build_tfp_history(*args, **kwargs):
    """Indirection so tests can substitute the (slow, networked) builder."""
    from BT.signals.tfp_swap_spread import build_tfp_history

    return build_tfp_history(*args, **kwargs)


def umep_panel(
    start: dt.date,
    end: dt.date,
    *,
    cache_path: Optional[str | Path] = None,
    **kwargs,
) -> pd.DataFrame:
    """USD term funding premium: the ASW-vs-modified-duration slope, bp/year.

    Thin wrapper over ``BT.signals.tfp_swap_spread.build_tfp_history`` (the
    Dallas Fed WP 2613 / JPM construction), renaming to this package's vocabulary
    and keeping the raw columns for diagnostics.

    USD only: the construction needs a Treasury curve, and no equivalent ASW
    infrastructure exists for EUR/JPY/GBP in this repo. Cross-market signals run
    on valuation and drift alone -- see the spec's stated limits.
    """
    raw = _build_tfp_history(start, end, cache_path=str(cache_path) if cache_path else None, **kwargs)
    if raw is None or raw.empty:
        return pd.DataFrame()
    out = raw.rename(columns={"tfp": "umep_bp_per_year", "zds": "zds_bp"})
    return out
```

- [ ] **Step 4: Run the fast tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_umep.py -v -m "not network"
```
Expected: 2 passed.

- [ ] **Step 5: Run the real one and write the observed sign into the docstring**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_umep.py -v -m "network and db"
```
Then append to the `umep_panel` docstring one sentence recording, from that run, the observed sign of `mmss_30Y` (is the repo's maturity-matched swap spread positive or negative at 30y?) and therefore whether `umep_bp_per_year` is positive under the tool convention. H2's whole test reads off this sign, so it is written down once, here, from data.

- [ ] **Step 6: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/panels.py tests/test_strikeless_vol_umep.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): UMEP panel wrapping the existing TFP construction"
```

---

### Task 7: Package legs and the direction convention

**Files:**
- Create: `RVUtils/StrikelessVol/greeks.py`
- Test: `tests/test_strikeless_vol_greeks.py`

**Interfaces:**
- Consumes: `universe.ForwardPair`, `conventions.FLATTENER`.
- Produces:
  - `PAYER_NOTIONAL_SIGN: int` — module constant recording rateslib's notional convention.
  - `build_leg(curve, leg, *, dv01_usd, direction) -> rl.IRS` where `direction` is `+1` to pay fixed, `−1` to receive fixed.
  - `build_package(curve, pair, *, package_dv01_usd=100_000.0, sign=FLATTENER) -> Package` where `Package` is a frozen dataclass with `short: rl.IRS`, `long: rl.IRS`, `short_dv01: float`, `long_dv01: float`, `sign: int`.
  - `package_npv(curve_handle, package) -> float`.
  - `test_curve()` helper is **not** shipped in the package — tests build their own `rl.Curve` (see below).

**Context the implementer needs:**
- The rateslib backend deliberately raises on `dv01`, `gamma` and `dollar_carry` (see `Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py:99-119`) because a true DV01 needs a calibrated `rl.Solver`. This package therefore does its own bump-and-reprice and must **never** call those three methods.
- `curve.pv01(swap)` is `analytic_delta` — dollars per bp for that swap's notional. That is the sizing tool.
- `curve.build_irswap(fwd="10Y", tenor="10Y", notional=N)` returns a **par-struck** forward-starting `rl.IRS` (the default `fixed_rate=-0` triggers a fair-rate solve), so each leg's PV is ~0 at inception and the package PV starts at ~0.
- Tests must not need market data. Build an `rl.Curve` directly:
  ```python
  import rateslib as rl
  curve = rl.Curve(
      nodes={rl.dt(2026, 8, 3): 1.0, **{rl.dt(2026 + y, 8, 3): 1.0 / (1.04 ** y) for y in range(1, 41)}},
      convention="act365f",
      calendar="nyc",
      id="flat4",
  )
  ```
  and wrap it: `RLIRSwapCurve(rl_curve_id="USD-OIS", rl_curve_handle=curve, fixings=pd.Series(dtype=float), meta_data={"reference_curve_name": "USD-OIS"})`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_greeks.py
import pandas as pd
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER
from RVUtils.StrikelessVol.greeks import build_leg, build_package, package_npv
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 8, 3)


@pytest.fixture(scope="module")
def curve():
    nodes = {REF: 1.0}
    nodes.update({rl.dt(2026 + y, 8, 3): 1.0 / (1.04 ** y) for y in range(1, 41)})
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="flat4")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=pd.Series(dtype=float),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


@pytest.fixture(scope="module")
def pair():
    return ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))


def test_payer_gains_when_rates_rise(curve):
    """Pins rateslib's notional sign convention. Everything downstream uses it."""
    payer = build_leg(curve, ForwardLeg("10Y", "10Y"), dv01_usd=100_000.0, direction=+1)
    base = payer.npv(curves=curve.handle()).real
    up = payer.npv(curves=curve.handle().shift(25)).real
    assert up > base


def test_leg_is_sized_to_the_requested_dv01(curve):
    leg = build_leg(curve, ForwardLeg("10Y", "10Y"), dv01_usd=100_000.0, direction=+1)
    assert abs(curve.pv01(leg)) == pytest.approx(100_000.0, rel=1e-6)


def test_flattener_receives_the_longer_leg_and_pays_the_shorter(curve, pair):
    pkg = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    # receiving the longer leg: its PV falls when rates rise
    up = pkg.long.npv(curves=curve.handle().shift(25)).real
    assert up < pkg.long.npv(curves=curve.handle()).real
    # paying the shorter leg: its PV rises when rates rise
    up_s = pkg.short.npv(curves=curve.handle().shift(25)).real
    assert up_s > pkg.short.npv(curves=curve.handle()).real


def test_package_is_dv01_neutral_at_inception(curve, pair):
    pkg = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    net = abs(pkg.short_dv01) - abs(pkg.long_dv01)
    assert net == pytest.approx(0.0, abs=1.0)  # $1 on a $100k DV01 package


def test_package_starts_at_zero_pv(curve, pair):
    pkg = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    assert package_npv(curve.handle(), pkg) == pytest.approx(0.0, abs=1.0)


def test_steepener_is_the_mirror_of_the_flattener(curve, pair):
    flat = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    steep = build_package(curve, pair, package_dv01_usd=100_000.0, sign=STEEPENER)
    shifted = curve.handle().shift(25)
    assert package_npv(shifted, flat) == pytest.approx(
        -package_npv(shifted, steep), rel=1e-9
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_greeks.py -v
```
Expected: FAIL — `cannot import name 'build_leg'`.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/greeks.py
"""Greeks by repricing. No assumed convexity constants, no quadratic toy.

The rateslib backend raises on ``dv01``/``gamma``/``dollar_carry`` because a
true DV01 needs a calibrated ``rl.Solver`` it does not carry. So this module
bumps the curve itself (``rl.Curve.shift``, in **bp**) and reprices, and takes
theta from ``rl.Curve.translate`` (advance the valuation date, hold the curve).
Nothing here calls the three raising methods.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

# rateslib's leg1 (fixed) notional sign for a PAYER swap. Pinned by
# test_payer_gains_when_rates_rise; flip this constant if that test fails,
# and nothing else in the package needs to change.
PAYER_NOTIONAL_SIGN: int = 1

__all__ = ["PAYER_NOTIONAL_SIGN", "Package", "build_leg", "build_package", "package_npv"]


@dataclass(frozen=True)
class Package:
    """A DV01-neutral two-leg forward slope position."""

    pair: ForwardPair
    short: Any  # rl.IRS, paid when sign == FLATTENER
    long: Any  # rl.IRS, received when sign == FLATTENER
    short_dv01: float
    long_dv01: float
    sign: int


def build_leg(curve, leg: ForwardLeg, *, dv01_usd: float, direction: int):
    """A forward-starting par swap sized to ``dv01_usd`` dollars per bp.

    ``direction`` is +1 to pay fixed, -1 to receive fixed.
    """
    unit = curve.build_irswap(fwd=leg.fwd, tenor=leg.tail, notional=1.0)
    dv01_per_unit = float(curve.pv01(unit))
    if dv01_per_unit == 0.0:
        raise ValueError(f"zero analytic delta for {leg.label}")
    notional = direction * PAYER_NOTIONAL_SIGN * float(dv01_usd) / dv01_per_unit
    return curve.build_irswap(fwd=leg.fwd, tenor=leg.tail, notional=notional)


def build_package(
    curve,
    pair: ForwardPair,
    *,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
) -> Package:
    """DV01-neutral slope package. ``sign=+1`` is the flattener (long convexity)."""
    short = build_leg(curve, pair.short, dv01_usd=package_dv01_usd, direction=+sign)
    long_ = build_leg(curve, pair.long, dv01_usd=package_dv01_usd, direction=-sign)
    return Package(
        pair=pair,
        short=short,
        long=long_,
        short_dv01=float(curve.pv01(short)),
        long_dv01=float(curve.pv01(long_)),
        sign=int(sign),
    )


def package_npv(curve_handle, package: Package) -> float:
    """Package PV on an arbitrary curve handle (base, shifted or translated)."""
    return float(
        package.short.npv(curves=curve_handle).real
        + package.long.npv(curves=curve_handle).real
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_greeks.py -v
```
Expected: 6 passed. If `test_payer_gains_when_rates_rise` fails, flip `PAYER_NOTIONAL_SIGN` to `-1` and re-run — that is the knob it exists for. If `test_leg_is_sized_to_the_requested_dv01` fails, check whether `curve.pv01` returned a signed value and take `abs()` in the sizing only, never in the package.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/greeks.py tests/test_strikeless_vol_greeks.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): DV01-neutral package construction with a pinned direction convention"
```

---

### Task 8: DV01, net convexity, and the analytic control

**Files:**
- Modify: `RVUtils/StrikelessVol/greeks.py`
- Test: `tests/test_strikeless_vol_greeks_control.py`

**Interfaces:**
- Consumes: Task 7's `Package`, `package_npv`.
- Produces:
  - `package_dv01(curve, package, *, h_bp=1.0) -> float` — dollars per bp, central difference.
  - `package_gamma(curve, package, *, h_bp=25.0) -> float` — dollars per bp², second difference.
  - `gamma_by_h(curve, package, *, h_bps=(10.0, 25.0, 50.0)) -> dict[float, float]`.
  - `analytic_leg_gamma(curve, swap) -> float` — the independent closed form used as the control.

**Why this control is the one that matters:** a previous attempt at this strategy plugged guessed constants into a quadratic and "verified" the toy rather than the mechanic. The control below never calls the bump code: it takes discount factors and fixed-leg accruals straight off the curve and differentiates the replication formula by hand. For a single-curve OIS swap, PV per unit notional is

`PV(Δ) = D(T₀)e^(−Δt₀) − D(T_N)e^(−Δt_N) − k·Σᵢ τᵢ D(Tᵢ)e^(−Δtᵢ)`

so `∂²PV/∂Δ² = t₀²D(T₀) − t_N²D(T_N) − k·Σᵢ τᵢ tᵢ² D(Tᵢ)`, and in bp² units that value is multiplied by 1e−8. Agreement to ~2% is expected; the residual is payment lag and compounding detail that the replication formula smooths over.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_greeks_control.py
import pandas as pd
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.greeks import (
    analytic_leg_gamma,
    build_package,
    gamma_by_h,
    package_dv01,
    package_gamma,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 8, 3)


@pytest.fixture(scope="module")
def curve():
    nodes = {REF: 1.0}
    nodes.update({rl.dt(2026 + y, 8, 3): 1.0 / (1.04 ** y) for y in range(1, 41)})
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="flat4")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=pd.Series(dtype=float),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


@pytest.fixture(scope="module")
def pkg(curve):
    pair = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))
    return build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)


def test_package_dv01_is_neutral_at_inception(curve, pkg):
    assert package_dv01(curve, pkg) == pytest.approx(0.0, abs=50.0)


def test_bumped_gamma_matches_the_analytic_replication_formula(curve, pkg):
    """The control: an independent closed form, not the bump code."""
    analytic = analytic_leg_gamma(curve, pkg.short) + analytic_leg_gamma(curve, pkg.long)
    bumped = package_gamma(curve, pkg, h_bp=25.0)
    assert analytic != 0.0
    assert bumped == pytest.approx(analytic, rel=0.02)


def test_flattener_convexity_is_positive(curve, pkg):
    """Receiving the longer forward against the shorter is long convexity."""
    assert package_gamma(curve, pkg, h_bp=25.0) > 0.0


def test_gamma_is_reported_per_h_not_averaged(curve, pkg):
    g = gamma_by_h(curve, pkg, h_bps=(10.0, 25.0, 50.0))
    assert set(g) == {10.0, 25.0, 50.0}
    assert all(v > 0 for v in g.values())
    # h-dependence is a property of the instrument, so it must be visible
    spread = (max(g.values()) - min(g.values())) / max(g.values())
    assert spread >= 0.0


def test_control_bites_when_the_bump_unit_is_wrong(curve, pkg, monkeypatch):
    """Mutation check: if h were passed as a decimal instead of bp, this fails.

    A checking tool that is itself wrong reports success. This asserts the
    control can tell the difference.
    """
    import RVUtils.StrikelessVol.greeks as g

    real_shift = rl.Curve.shift
    monkeypatch.setattr(
        rl.Curve, "shift", lambda self, spread, **kw: real_shift(self, spread * 1e4, **kw)
    )
    analytic = analytic_leg_gamma(curve, pkg.short) + analytic_leg_gamma(curve, pkg.long)
    bumped = g.package_gamma(curve, pkg, h_bp=25.0)
    assert bumped != pytest.approx(analytic, rel=0.02)
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_greeks_control.py -v
```
Expected: FAIL — `cannot import name 'package_dv01'`.

- [ ] **Step 3: Write the implementation (append to `greeks.py`)**

```python
def package_dv01(curve, package: Package, *, h_bp: float = 1.0) -> float:
    """Dollars per bp, central difference on a parallel reprice."""
    handle = curve.handle()
    up = package_npv(handle.shift(h_bp), package)
    dn = package_npv(handle.shift(-h_bp), package)
    return (up - dn) / (2.0 * h_bp)


def package_gamma(curve, package: Package, *, h_bp: float = 25.0) -> float:
    """Dollars per bp squared, second difference on parallel reprices."""
    handle = curve.handle()
    base = package_npv(handle, package)
    up = package_npv(handle.shift(h_bp), package)
    dn = package_npv(handle.shift(-h_bp), package)
    return (up + dn - 2.0 * base) / (h_bp ** 2)


def gamma_by_h(curve, package: Package, *, h_bps=(10.0, 25.0, 50.0)) -> dict:
    """Convexity at several move sizes. Reported, never averaged away."""
    return {float(h): package_gamma(curve, package, h_bp=float(h)) for h in h_bps}


def analytic_leg_gamma(curve, swap) -> float:
    """Closed-form d2PV/dShift2 for one leg, in dollars per bp squared.

    Independent of the bump code: takes discount factors and fixed-leg accruals
    straight off the curve and differentiates the single-curve replication

        PV(D) = N * [ D(T0) e^{-D t0} - D(TN) e^{-D tN}
                      - k * sum_i tau_i D(Ti) e^{-D ti} ]

    so d2PV/dD2 = N * [ t0^2 D(T0) - tN^2 D(TN) - k * sum_i tau_i ti^2 D(Ti) ],
    scaled by 1e-8 to convert per-decimal into per-bp-squared.
    """
    handle = curve.handle()
    ref = curve.reference_date()
    notional = float(curve.notional(swap))
    k = float(curve.fixed_rate(swap))  # decimal

    cf = swap.leg1.cashflows(handle)
    t0 = (pd.Timestamp(curve.effective_date(swap)) - pd.Timestamp(ref)).days / 365.0
    tN = (pd.Timestamp(curve.maturity_date(swap)) - pd.Timestamp(ref)).days / 365.0
    d0 = float(handle[curve.effective_date(swap)])
    dN = float(handle[curve.maturity_date(swap)])

    annuity_term = 0.0
    for _, row in cf.iterrows():
        pay = pd.Timestamp(row["Payment"])
        tau = float(row["DCF"])
        ti = (pay - pd.Timestamp(ref)).days / 365.0
        di = float(handle[pay.to_pydatetime()])
        annuity_term += tau * ti * ti * di

    second_derivative = notional * (t0 * t0 * d0 - tN * tN * dN - k * annuity_term)
    return second_derivative * 1e-8
```

Add `import pandas as pd` at the top of `greeks.py` and extend `__all__` with the four new names.

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_greeks_control.py -v
```
Expected: 5 passed. If the analytic/bumped comparison misses by more than 2% but less than ~10%, print both and check: (a) `PAYER_NOTIONAL_SIGN` consistency, (b) whether `leg1` is the fixed leg for this spec, (c) whether `row["DCF"]` is the accrual fraction rather than a day count. Do **not** widen the tolerance to make it pass — the tolerance is the control.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/greeks.py tests/test_strikeless_vol_greeks_control.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): repriced DV01/convexity with an independent analytic control"
```

---

### Task 9: Carry, breakeven, and the greeks panel

**Files:**
- Modify: `RVUtils/StrikelessVol/greeks.py`
- Test: `tests/test_strikeless_vol_breakeven.py`

**Interfaces:**
- Consumes: Tasks 7–8.
- Produces:
  - `daily_roll_usd(curve, package, *, next_date) -> float` — one-business-day theta, dollars (negative = bleed).
  - `breakeven_bp_day(daily_roll_usd, gamma) -> float` — `sqrt(2·|roll| / Γ)`.
  - `PackageGreeks` frozen dataclass: `date`, `pair_name`, `short_rate`, `long_rate`, `spread_bp`, `short_dv01`, `long_dv01`, `package_dv01`, `gamma_by_h: dict`, `daily_roll_usd`, `breakeven_by_h: dict`.
  - `compute_greeks(curve, pair, *, next_date, package_dv01_usd=100_000.0, sign=FLATTENER, h_bps=(10.,25.,50.)) -> PackageGreeks`.
  - `greeks_panel(curve_map, pair, **kwargs) -> pd.DataFrame` — one row per date, `breakeven_h25` etc. as columns.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_breakeven.py
import math

import pandas as pd
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.greeks import (
    breakeven_bp_day,
    compute_greeks,
    daily_roll_usd,
    greeks_panel,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 8, 3)


def _curve(ref=REF, slope=0.0):
    """Flat-4% curve, optionally with an inverted ultra-long section."""
    nodes = {ref: 1.0}
    for y in range(1, 41):
        r = 0.04 + slope * max(0.0, y - 10) / 100.0
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / ((1.0 + r) ** y)
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="c")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=pd.Series(dtype=float),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


PAIR = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))


def test_breakeven_formula():
    # 2 * |roll| / gamma, square-rooted
    assert breakeven_bp_day(-800.0, 100.0) == pytest.approx(math.sqrt(16.0))


def test_breakeven_is_nan_when_convexity_is_non_positive():
    assert math.isnan(breakeven_bp_day(-800.0, 0.0))
    assert math.isnan(breakeven_bp_day(-800.0, -5.0))


def test_daily_roll_is_a_one_day_translate_not_a_maturity_shortening():
    curve = _curve(slope=-0.5)  # inverted ultra-long -> flattener should bleed
    from RVUtils.StrikelessVol.greeks import build_package

    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    roll = daily_roll_usd(curve, pkg, next_date=rl.dt(2026, 8, 4))
    assert roll != 0.0
    assert abs(roll) < 100_000.0  # one day of carry cannot be a bp of DV01


def test_inverted_curve_makes_the_flattener_bleed(): 
    curve = _curve(slope=-0.5)
    from RVUtils.StrikelessVol.greeks import build_package

    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    assert daily_roll_usd(curve, pkg, next_date=rl.dt(2026, 8, 4)) < 0.0


def test_compute_greeks_returns_a_full_labelled_record():
    curve = _curve(slope=-0.5)
    g = compute_greeks(curve, PAIR, next_date=rl.dt(2026, 8, 4))
    assert g.pair_name == "USD 10Y10Y/20Y10Y"
    assert g.spread_bp < 0.0  # inverted
    assert set(g.gamma_by_h) == {10.0, 25.0, 50.0}
    assert set(g.breakeven_by_h) == {10.0, 25.0, 50.0}
    assert g.breakeven_by_h[25.0] > 0.0
    assert abs(g.package_dv01) < 50.0


def test_greeks_panel_is_one_row_per_date():
    curve_map = {
        pd.Timestamp("2026-08-03"): _curve(slope=-0.5),
        pd.Timestamp("2026-08-04"): _curve(ref=rl.dt(2026, 8, 4), slope=-0.5),
    }
    panel = greeks_panel(curve_map, PAIR)
    assert len(panel) == 2
    assert "breakeven_h25" in panel.columns
    assert "gamma_h25" in panel.columns
    assert "daily_roll_usd" in panel.columns
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_breakeven.py -v
```
Expected: FAIL — `cannot import name 'breakeven_bp_day'`.

- [ ] **Step 3: Write the implementation (append to `greeks.py`)**

```python
import math

import pandas as pd


def daily_roll_usd(curve, package: Package, *, next_date) -> float:
    """One business day of carry+roll, in dollars, curve held fixed.

    ``rl.Curve.translate`` advances the valuation date while holding the forward
    curve, which is exactly "nothing happened, a day passed". Negative means the
    position bleeds -- the normal state of a flattener on an inverted ultra-long
    curve.
    """
    handle = curve.handle()
    base = package_npv(handle, package)
    rolled = package_npv(handle.translate(next_date), package)
    return rolled - base


def breakeven_bp_day(daily_roll: float, gamma: float) -> float:
    """The parallel move whose convexity gain pays one day of roll, in bp.

    ``sqrt(2 * |roll| / gamma)``. Undefined (NaN) when convexity is not positive:
    a non-convex package has no breakeven, and returning 0.0 there would read as
    "infinitely cheap".
    """
    if gamma is None or gamma <= 0.0:
        return float("nan")
    return math.sqrt(2.0 * abs(float(daily_roll)) / float(gamma))


@dataclass(frozen=True)
class PackageGreeks:
    date: Any
    pair_name: str
    short_rate: float
    long_rate: float
    spread_bp: float
    short_dv01: float
    long_dv01: float
    package_dv01: float
    gamma_by_h: dict
    daily_roll_usd: float
    breakeven_by_h: dict


def compute_greeks(
    curve,
    pair: ForwardPair,
    *,
    next_date=None,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
    h_bps=(10.0, 25.0, 50.0),
) -> PackageGreeks:
    """Everything for one pair on one date, all of it repriced."""
    from RVUtils.StrikelessVol.conventions import slope_bp

    pkg = build_package(curve, pair, package_dv01_usd=package_dv01_usd, sign=sign)
    short_rate = float(curve.fair_rate(curve.build_irswap(fwd=pair.short.fwd, tenor=pair.short.tail)))
    long_rate = float(curve.fair_rate(curve.build_irswap(fwd=pair.long.fwd, tenor=pair.long.tail)))

    if next_date is None:
        next_date = curve.calendar_advance(curve.reference_date(), "1b")

    gammas = gamma_by_h(curve, pkg, h_bps=h_bps)
    roll = daily_roll_usd(curve, pkg, next_date=next_date)
    return PackageGreeks(
        date=curve.reference_date(),
        pair_name=pair.name,
        short_rate=short_rate,
        long_rate=long_rate,
        spread_bp=slope_bp(short_rate=short_rate, long_rate=long_rate),
        short_dv01=pkg.short_dv01,
        long_dv01=pkg.long_dv01,
        package_dv01=package_dv01(curve, pkg),
        gamma_by_h=gammas,
        daily_roll_usd=roll,
        breakeven_by_h={h: breakeven_bp_day(roll, g) for h, g in gammas.items()},
    )


def greeks_panel(curve_map: dict, pair: ForwardPair, **kwargs) -> pd.DataFrame:
    """One row per date. Dates whose curve cannot price the pair are dropped."""
    rows = []
    for ts in sorted(curve_map):
        curve = curve_map[ts]
        if curve is None:
            continue
        try:
            g = compute_greeks(curve, pair, **kwargs)
        except Exception:
            continue
        rec = {
            "date": pd.Timestamp(ts),
            "pair": g.pair_name,
            "short_rate": g.short_rate,
            "long_rate": g.long_rate,
            "spread_bp": g.spread_bp,
            "package_dv01": g.package_dv01,
            "daily_roll_usd": g.daily_roll_usd,
        }
        for h, val in g.gamma_by_h.items():
            rec[f"gamma_h{int(h)}"] = val
        for h, val in g.breakeven_by_h.items():
            rec[f"breakeven_h{int(h)}"] = val
        rows.append(rec)
    return pd.DataFrame(rows).set_index("date").sort_index()
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_breakeven.py -v
conda run -n stir python -m pytest tests/test_strikeless_vol_greeks.py tests/test_strikeless_vol_greeks_control.py -v
```
Expected: all pass. The earlier greeks tests must still pass — `compute_greeks` must not have changed `build_package`.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/greeks.py tests/test_strikeless_vol_breakeven.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): theta by curve translate, breakeven in bp/day, greeks panel"
```

---

### Task 10: Vol metrics — realized, implied, and the valuation ratio

**Files:**
- Create: `RVUtils/StrikelessVol/vol_metrics.py`
- Test: `tests/test_strikeless_vol_vol_metrics.py`

**Interfaces:**
- Consumes: `conventions.VolQuote`, panels from Tasks 4–5.
- Produces:
  - `realized_vol_bp_day(rates: pd.Series, window: int = 63) -> pd.Series` — rolling std of daily changes, in bp/day, on a **decimal** rate series.
  - `spread_vol_bp_day(spread_bp: pd.Series, window: int = 63) -> pd.Series` — the sizing base.
  - `realized_quote(rates, window, *, underlying) -> VolQuote` (latest value, labelled).
  - `be_over_realized(be_bp_day: pd.Series, rv_bp_day: pd.Series) -> pd.Series`.
  - `be_over_implied(be_bp_day: pd.Series, iv_bp_day: pd.Series) -> pd.Series`.

**Note on which underlying:** the spec requires every vol to state what it is computed on. Realized vol for the valuation ratio is computed on the **longer leg's forward par rate** (the rate the rebalance trigger watches), and `spread_vol_bp_day` on the **package spread** (the sizing base). These are different numbers with different uses and must never be swapped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_vol_metrics.py
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import VolQuote
from RVUtils.StrikelessVol.vol_metrics import (
    be_over_implied,
    be_over_realized,
    realized_quote,
    realized_vol_bp_day,
    spread_vol_bp_day,
)


def test_realized_vol_of_a_known_series():
    # daily changes of exactly 5bp, alternating sign -> std of |5bp| series
    idx = pd.date_range("2026-01-01", periods=101, freq="B")
    steps = np.where(np.arange(100) % 2 == 0, 5e-4, -5e-4)
    rates = pd.Series(np.concatenate([[0.04], 0.04 + np.cumsum(steps)]), index=idx)
    rv = realized_vol_bp_day(rates, window=100)
    assert rv.iloc[-1] == pytest.approx(5.0, rel=0.02)


def test_spread_vol_is_computed_on_bp_input_without_rescaling():
    idx = pd.date_range("2026-01-01", periods=101, freq="B")
    spread = pd.Series(np.arange(101, dtype=float) * 1.65, index=idx)
    sv = spread_vol_bp_day(spread, window=100)
    assert sv.iloc[-1] == pytest.approx(0.0, abs=1e-9)  # constant increments


def test_realized_quote_is_labelled():
    idx = pd.date_range("2026-01-01", periods=70, freq="B")
    rates = pd.Series(np.linspace(0.04, 0.045, 70), index=idx)
    q = realized_quote(rates, 63, underlying="USD 20Y10Y forward par rate")
    assert isinstance(q, VolQuote)
    assert q.measure == "realized"
    assert q.window == "63d"
    assert "20Y10Y" in q.underlying


def test_ratios_below_one_mean_embedded_vol_is_cheap():
    be = pd.Series([1.3, 4.0])
    rv = pd.Series([3.0, 4.0])
    r = be_over_realized(be, rv)
    assert r.iloc[0] == pytest.approx(0.4333, abs=1e-3)  # the May-2019 15y5y/20y10y case
    assert r.iloc[1] == pytest.approx(1.0)


def test_ratio_is_nan_when_the_denominator_is_zero():
    r = be_over_implied(pd.Series([2.0]), pd.Series([0.0]))
    assert np.isnan(r.iloc[0])
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_vol_metrics.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/vol_metrics.py
"""Realized vol, implied vol and the valuation ratio, all in bp/day.

Which underlying each vol is computed on is load-bearing:

* ``realized_vol_bp_day`` runs on the **longer leg's forward par rate** -- the
  rate the rebalance trigger watches, and the one the breakeven is compared to.
* ``spread_vol_bp_day`` runs on the **package spread** -- the sizing base
  (~1.65bp/day for USD 10y10y/20y10y in the 2026 sample).

They are different numbers. Swapping them silently changes what the system is
sized off, which the spec forbids.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import VolQuote

__all__ = [
    "realized_vol_bp_day",
    "spread_vol_bp_day",
    "realized_quote",
    "be_over_realized",
    "be_over_implied",
]


def realized_vol_bp_day(rates: pd.Series, window: int = 63) -> pd.Series:
    """Rolling std of daily changes of a DECIMAL rate series, in bp/day."""
    changes_bp = pd.Series(rates).astype(float).diff() * 10_000.0
    return changes_bp.rolling(int(window), min_periods=int(window)).std(ddof=1)


def spread_vol_bp_day(spread_bp: pd.Series, window: int = 63) -> pd.Series:
    """Rolling std of daily changes of a BP spread series, in bp/day."""
    return (
        pd.Series(spread_bp)
        .astype(float)
        .diff()
        .rolling(int(window), min_periods=int(window))
        .std(ddof=1)
    )


def realized_quote(rates: pd.Series, window: int, *, underlying: str) -> VolQuote:
    """The latest realized vol, labelled."""
    series = realized_vol_bp_day(rates, window=window).dropna()
    if series.empty:
        raise ValueError("not enough observations for the requested window")
    return VolQuote(
        value_bp_day=float(series.iloc[-1]),
        measure="realized",
        underlying=underlying,
        window=f"{int(window)}d",
    )


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    n = pd.Series(num).astype(float)
    d = pd.Series(den).astype(float)
    return n / d.where(d > 0.0, np.nan)


def be_over_realized(be_bp_day: pd.Series, rv_bp_day: pd.Series) -> pd.Series:
    """<1 means the embedded vol is cheap versus what the market actually does."""
    return _ratio(be_bp_day, rv_bp_day)


def be_over_implied(be_bp_day: pd.Series, iv_bp_day: pd.Series) -> pd.Series:
    """<1 means the embedded vol is cheap versus the swaption surface."""
    return _ratio(be_bp_day, iv_bp_day)
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_vol_metrics.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/vol_metrics.py tests/test_strikeless_vol_vol_metrics.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): realized/implied vol metrics and the BE valuation ratio"
```

---

### Task 11: Cost schedule

**Files:**
- Create: `RVUtils/StrikelessVol/costs.py`
- Test: `tests/test_strikeless_vol_costs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CostSchedule` frozen dataclass with fields `initiate_bp=0.875`, `hedge_bp=0.35`, `roll_bp=0.35`, `clip_dv01_usd=100_000.0`, `clip_exponent=0.0`, `multiplier=1.0`; method `cost_usd(kind: str, dv01_traded_usd: float) -> float`; and `TAKER`, `MAKER`, `FREE` module-level presets.

**Priors being encoded (from the spec, stressed not trusted):** at $100k DV01 clips, 0.75–1.0bp to initiate and 0.3–0.4bp per hedge or roll, one way. The midpoints are the defaults. `clip_exponent` models the cost of size: cost per bp scales as `(dv01 / clip_dv01)**clip_exponent`, so `0.0` is size-blind (the prior) and e.g. `0.3` makes a 10× clip cost ~2× per unit.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_costs.py
import pytest

from RVUtils.StrikelessVol.costs import FREE, MAKER, TAKER, CostSchedule


def test_initiation_cost_at_the_reference_clip():
    s = CostSchedule()
    # 0.875bp on a $100k DV01 package = $87,500
    assert s.cost_usd("initiate", 100_000.0) == pytest.approx(87_500.0)


def test_hedge_and_roll_are_charged_separately():
    s = CostSchedule()
    assert s.cost_usd("hedge", 20_000.0) == pytest.approx(0.35 * 20_000.0)
    assert s.cost_usd("roll", 100_000.0) == pytest.approx(0.35 * 100_000.0)


def test_unknown_cost_kind_raises():
    with pytest.raises(KeyError):
        CostSchedule().cost_usd("vibes", 1.0)


def test_multiplier_scales_everything():
    assert CostSchedule(multiplier=2.0).cost_usd("hedge", 100_000.0) == pytest.approx(
        2.0 * CostSchedule().cost_usd("hedge", 100_000.0)
    )
    assert FREE.cost_usd("initiate", 100_000.0) == 0.0


def test_clip_exponent_makes_size_expensive():
    size_blind = CostSchedule(clip_exponent=0.0)
    size_aware = CostSchedule(clip_exponent=0.3)
    big = 1_000_000.0
    assert size_aware.cost_usd("hedge", big) > size_blind.cost_usd("hedge", big)
    # and is neutral at the reference clip
    assert size_aware.cost_usd("hedge", 100_000.0) == pytest.approx(
        size_blind.cost_usd("hedge", 100_000.0)
    )


def test_presets_bracket_the_prior():
    assert MAKER.initiate_bp < TAKER.initiate_bp
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_costs.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/costs.py
"""Transaction costs for forward-slope packages.

Priors from the research brief, at $100k DV01 clips: 0.75-1.0bp to initiate,
0.3-0.4bp per hedge or roll, one way. Defaults are the midpoints. Every result
in this study is reported at multiplier 0, 1 and 2 -- capacity is a first-order
constraint here, so the conclusion is stated in clips, not in ratios.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CostSchedule", "FREE", "MAKER", "TAKER"]


@dataclass(frozen=True)
class CostSchedule:
    initiate_bp: float = 0.875
    hedge_bp: float = 0.35
    roll_bp: float = 0.35
    clip_dv01_usd: float = 100_000.0
    clip_exponent: float = 0.0
    multiplier: float = 1.0

    def cost_usd(self, kind: str, dv01_traded_usd: float) -> float:
        """Dollars charged for trading ``dv01_traded_usd`` of risk."""
        rate_bp = {
            "initiate": self.initiate_bp,
            "hedge": self.hedge_bp,
            "roll": self.roll_bp,
        }[kind]
        dv01 = abs(float(dv01_traded_usd))
        if dv01 == 0.0:
            return 0.0
        size_factor = (
            (dv01 / self.clip_dv01_usd) ** self.clip_exponent
            if self.clip_exponent
            else 1.0
        )
        return self.multiplier * rate_bp * dv01 * size_factor


FREE = CostSchedule(multiplier=0.0)
MAKER = CostSchedule(initiate_bp=0.75, hedge_bp=0.30, roll_bp=0.30)
TAKER = CostSchedule(initiate_bp=1.00, hedge_bp=0.40, roll_bp=0.40)
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_costs.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/costs.py tests/test_strikeless_vol_costs.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): clip-aware cost schedule with maker/taker presets"
```

---

### Task 12: Replication simulator and the four ledgers

**Files:**
- Create: `RVUtils/StrikelessVol/replication.py`
- Test: `tests/test_strikeless_vol_replication.py`

**Interfaces:**
- Consumes: `costs.CostSchedule`, `conventions.FLATTENER`.
- Produces:
  - `PricingContext` protocol: `pv(date, notional_long, notional_short) -> float`, `dv01(date, leg: str) -> float` (dollars per bp per unit notional), `rate(date, leg: str) -> float` (decimal, `leg in {"short","long"}`).
  - `ReplicationConfig(trigger_bp=25.0, roll_months=12, package_dv01_usd=100_000.0, sign=FLATTENER, hedge_instrument="long_leg")`.
  - `simulate(ctx, dates, cfg, costs) -> pd.DataFrame` — one row per date with columns `carry`, `harvest`, `mtm`, `cost`, `cross`, `total`, `n_hedges`, `long_notional`, `short_notional`, `position_age_years`.
  - `reconcile(ledger: pd.DataFrame) -> dict` with `max_abs_cross_frac`, `cross_trend_t`, `ok: bool`.

**The ledger definitions (verbatim from the spec, because getting these wrong is how H10 fakes itself):**
1. **carry** — theta: PV change from a day passing on an unchanged curve.
2. **harvest** — the P&L of the *incremental* legs added at each resize, each marked from the rate at which that increment was traded: `Σ_k Δn_k · (r_t − r_k) · dv01_unit`. It is **not** "total minus the other three".
3. **mtm** — PV change from curve moves on the notionals held at the start of the day, excluding those increments.
4. **cost** — initiation, each hedge, each roll.
5. **cross** — the plug. Not expected to be zero; required to be small (<1% of |total|) and trendless. A plug quietly absorbing the harvest is exactly the failure mode this bucket exists to expose.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_replication.py
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.costs import FREE, CostSchedule
from RVUtils.StrikelessVol.replication import (
    ReplicationConfig,
    reconcile,
    simulate,
)


BASE_DV01 = 100_000.0


class SyntheticCtx:
    """A closed-form world: quadratic PV in the rate, linear time decay.

    With ``k = gamma / 1e4`` and ``dr`` the long rate's move in bp since inception:

        PV   = n_long*(dr + 0.5*k*dr^2) - n_short*dr
               + theta_per_day * days_elapsed * (n_long / BASE_DV01)
        dv01 = 1 + k*dr   (long leg)          # exactly d(PV)/d(dr) per unit
        theta= theta_per_day * n_long / BASE_DV01

    ``dv01`` drifts with the rate, which is what makes the resize rule bite:
    holding DV01 constant means selling delta as rates rise and buying it back
    as they fall. That is the gamma-scalping mechanic the whole strategy rests
    on, so the synthetic world has to contain it or the ledger tests prove
    nothing.
    """

    def __init__(self, path_bp, *, theta_per_day=-500.0, gamma=40.0):
        self.dates = pd.date_range("2026-01-01", periods=len(path_bp), freq="B")
        self.path = dict(zip(self.dates, np.asarray(path_bp, dtype=float)))
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.theta_per_day = theta_per_day
        self.k = gamma / 1e4

    def rate(self, date, leg):
        base = 0.04 if leg == "long" else 0.045
        return base + self.path[date] * 1e-4

    def dv01(self, date, leg):
        if leg == "long":
            return 1.0 + self.k * self.path[date]
        return 1.0

    def theta(self, date, notional_long, notional_short):
        return self.theta_per_day * (notional_long / BASE_DV01)

    def pv(self, date, notional_long, notional_short):
        dr = self.path[date]
        i = self.day_index[date]
        convex = (
            notional_long * (dr + 0.5 * self.k * dr * dr)
            - notional_short * dr
        )
        return convex + self.theta_per_day * i * (notional_long / BASE_DV01)


def test_flat_path_produces_only_carry():
    ctx = SyntheticCtx([0.0] * 20)
    led = simulate(ctx, ctx.dates, ReplicationConfig(), FREE)
    assert led["mtm"].abs().sum() == pytest.approx(0.0, abs=1e-6)
    assert led["harvest"].abs().sum() == pytest.approx(0.0, abs=1e-6)
    assert led["cost"].sum() == pytest.approx(0.0)


def test_no_rebalance_below_the_trigger():
    ctx = SyntheticCtx(list(np.linspace(0.0, 20.0, 30)))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    assert led["n_hedges"].sum() == 0


def test_rebalances_once_per_trigger_crossing():
    ctx = SyntheticCtx(list(np.linspace(0.0, 100.0, 101)))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    assert led["n_hedges"].sum() == 4  # 25, 50, 75, 100


def test_harvest_is_positive_for_a_round_trip_on_the_long_convexity_side():
    """Out 50bp and back: the resizes are bought low and sold high."""
    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    assert led["harvest"].sum() > 0.0


def test_costs_are_charged_on_initiation_and_each_hedge():
    ctx = SyntheticCtx(list(np.linspace(0.0, 100.0, 101)))
    sched = CostSchedule()
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), sched)
    assert led["cost"].iloc[0] == pytest.approx(
        -sched.cost_usd("initiate", 100_000.0)
    )
    assert (led["cost"] < 0).sum() == 1 + 4  # initiation plus four hedges


def test_ledgers_reconcile_with_a_small_trendless_plug():
    rng = np.random.default_rng(0)
    path = np.cumsum(rng.normal(0.0, 5.0, 250))
    ctx = SyntheticCtx(list(path))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    rec = reconcile(led)
    assert rec["ok"] is True
    assert rec["max_abs_cross_frac"] < 0.01


def test_position_ages_and_rolls():
    ctx = SyntheticCtx([0.0] * 400)
    led = simulate(ctx, ctx.dates, ReplicationConfig(roll_months=12), FREE)
    # a 12-month roll inside ~400 business days means at least one roll charge
    assert led["position_age_years"].max() < 1.05
    assert led["position_age_years"].iloc[-1] < led["position_age_years"].max()


def test_steepener_mirrors_the_flattener_ledgers():
    from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER

    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    flat = simulate(ctx, ctx.dates, ReplicationConfig(sign=FLATTENER), FREE)
    steep = simulate(ctx, ctx.dates, ReplicationConfig(sign=STEEPENER), FREE)
    assert flat["harvest"].sum() == pytest.approx(-steep["harvest"].sum(), rel=1e-9)
    assert flat["carry"].sum() == pytest.approx(-steep["carry"].sum(), rel=1e-9)
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_replication.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/replication.py
"""Path-wise replication of the delta-hedged straddle.

The rebalancing rule IS the option replication: unhedged, a forward flattener is
a curve position with a story. Resizing the longer leg back to DV01 neutral at
fixed move triggers is grid gamma-scalping, and it applies on both sides -- a
steepener runs the short-straddle ledger (carry collected, convexity paid).

The simulator talks to a ``PricingContext``, so it is fully testable against a
closed-form synthetic world with no market data anywhere near it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.costs import CostSchedule

__all__ = ["PricingContext", "ReplicationConfig", "simulate", "reconcile"]


class PricingContext(Protocol):
    def rate(self, date, leg: str) -> float: ...
    def dv01(self, date, leg: str) -> float: ...
    def pv(self, date, notional_long: float, notional_short: float) -> float: ...
    def theta(self, date, notional_long: float, notional_short: float) -> float: ...


@dataclass(frozen=True)
class ReplicationConfig:
    trigger_bp: float = 25.0
    roll_months: int = 12
    package_dv01_usd: float = 100_000.0
    sign: int = FLATTENER
    hedge_instrument: str = "long_leg"  # or "spot_atm"


def simulate(
    ctx: PricingContext,
    dates: Sequence,
    cfg: ReplicationConfig,
    costs: CostSchedule,
) -> pd.DataFrame:
    """Run the rule down a path and keep the five ledgers separately."""
    dates = list(dates)
    if not dates:
        return pd.DataFrame()

    d0 = dates[0]
    dv01_long_unit = ctx.dv01(d0, "long")
    dv01_short_unit = ctx.dv01(d0, "short")

    n_long = cfg.sign * cfg.package_dv01_usd / dv01_long_unit
    n_short = -cfg.sign * cfg.package_dv01_usd / dv01_short_unit

    increments: list[tuple[float, float]] = []  # (delta_notional, rate_at_trade)
    last_hedge_rate_bp = ctx.rate(d0, "long") * 1e4
    inception = pd.Timestamp(d0)
    roll_days = int(round(cfg.roll_months * 21))

    n_long_base = n_long  # notional before any resize increments
    prev_pv = ctx.pv(d0, n_long, n_short)
    prev_base_pv = prev_pv
    prev_long_rate_bp = last_hedge_rate_bp
    rows = [
        {
            "date": pd.Timestamp(d0),
            "carry": 0.0,
            "harvest": 0.0,
            "mtm": 0.0,
            "cross": 0.0,
            "cost": -costs.cost_usd("initiate", abs(cfg.package_dv01_usd)),
            "n_hedges": 0,
            "long_notional": n_long,
            "short_notional": n_short,
            "position_age_years": 0.0,
        }
    ]

    days_held = 0
    for d in dates[1:]:
        days_held += 1
        long_rate_bp = ctx.rate(d, "long") * 1e4

        # what actually happened, on everything held
        total_pv_change = ctx.pv(d, n_long, n_short) - prev_pv

        # 1. carry: a day passing with the curve unchanged
        carry = float(ctx.theta(d, n_long, n_short))

        # 2. mtm: the curve move on the BASE notionals only, net of their carry
        base_pv = ctx.pv(d, n_long_base, n_short)
        base_carry = float(ctx.theta(d, n_long_base, n_short))
        mtm = (base_pv - prev_base_pv) - base_carry

        # 3. harvest: each increment marked from the rate it was traded at
        harvest = sum(
            dn * (long_rate_bp - prev_long_rate_bp) * dv01_long_unit
            for dn, _ in increments
        )

        # 4. cross: the plug. Second-order terms the three buckets above cannot
        #    hold -- chiefly the increments' own convexity within the day. It is
        #    computed, never assumed zero: defining mtm as the residual would
        #    force this to zero by construction and make reconciliation vacuous.
        cross = total_pv_change - (carry + mtm + harvest)

        cost = 0.0
        n_hedges = 0

        if abs(long_rate_bp - last_hedge_rate_bp) >= cfg.trigger_bp:
            target_long = cfg.sign * cfg.package_dv01_usd / ctx.dv01(d, "long")
            delta_n = target_long - n_long
            if delta_n != 0.0:
                increments.append((delta_n, long_rate_bp))
                n_long = target_long
                cost -= costs.cost_usd("hedge", abs(delta_n) * ctx.dv01(d, "long"))
                n_hedges = 1
            last_hedge_rate_bp = long_rate_bp

        if days_held >= roll_days:
            cost -= costs.cost_usd("roll", abs(cfg.package_dv01_usd))
            days_held = 0
            inception = pd.Timestamp(d)
            increments.clear()
            n_long = cfg.sign * cfg.package_dv01_usd / ctx.dv01(d, "long")
            n_short = -cfg.sign * cfg.package_dv01_usd / ctx.dv01(d, "short")
            n_long_base = n_long
            last_hedge_rate_bp = long_rate_bp

        rows.append(
            {
                "date": pd.Timestamp(d),
                "carry": carry,
                "harvest": harvest,
                "mtm": mtm,
                "cross": cross,
                "cost": cost,
                "n_hedges": n_hedges,
                "long_notional": n_long,
                "short_notional": n_short,
                "position_age_years": (pd.Timestamp(d) - inception).days / 365.0,
            }
        )
        prev_pv = ctx.pv(d, n_long, n_short)
        prev_base_pv = ctx.pv(d, n_long_base, n_short)
        prev_long_rate_bp = long_rate_bp

    led = pd.DataFrame(rows).set_index("date")
    led["total"] = led[["carry", "harvest", "mtm", "cross", "cost"]].sum(axis=1)
    return led


def reconcile(ledger: pd.DataFrame) -> dict:
    """The plug must be small and trendless, not zero.

    Theta, base-notional MTM and increment MTM leave second-order cross terms.
    A growing plug means the attribution is wrong; a plug that quietly absorbs
    the harvest is how H10 would fake itself.
    """
    if ledger.empty:
        return {"max_abs_cross_frac": 0.0, "cross_trend_t": 0.0, "ok": True}
    total = ledger["total"].abs().sum()
    cross = ledger["cross"].abs().sum()
    frac = float(cross / total) if total else 0.0
    cum = ledger["cross"].cumsum().to_numpy()
    x = np.arange(len(cum), dtype=float)
    if len(cum) > 2 and np.std(cum) > 0:
        slope, intercept = np.polyfit(x, cum, 1)
        resid = cum - (slope * x + intercept)
        se = np.std(resid, ddof=2) / (np.std(x) * np.sqrt(len(x))) if np.std(x) else np.nan
        t = float(slope / se) if se and np.isfinite(se) else 0.0
    else:
        t = 0.0
    return {
        "max_abs_cross_frac": frac,
        "cross_trend_t": t,
        "ok": bool(frac < 0.01 and abs(t) < 3.0),
    }
```

**Implementer's note on `carry`:** the simulator gets theta from the context's `theta` hook, because the synthetic world has no curve to translate. The real `CurvePricer` (Task 13) implements `theta(date)` by calling `greeks.daily_roll_usd`, which *is* a curve translate — so the ledger's carry is repriced in production and closed-form in tests, with one code path.

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_replication.py -v
```
Expected: 8 passed. `test_harvest_is_positive_for_a_round_trip_on_the_long_convexity_side` is the one that proves the scalping mechanic; if it fails, check the sign of `delta_n` and that increments are marked from `long_rate_bp` at trade time, not from inception.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/replication.py tests/test_strikeless_vol_replication.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): path-wise replication with four ledgers and a reconciliation plug"
```

---

### Task 13: `CurvePricer` and the Citi static-long positive control — **GATE (SUPERSEDED — see banner below)**

**Files:**
- Modify: `RVUtils/StrikelessVol/replication.py` (add `CurvePricer`)
- Create: `RVUtils/StrikelessVol/report.py`
- Create: `scripts/sv_static_long_control.py`
- Test: `tests/test_strikeless_vol_control.py`

**Interfaces:**
- Consumes: `greeks.build_package`, `greeks.package_npv`, `greeks.daily_roll_usd`, `panels.forward_rate_panel`, `replication.simulate`.
- Produces:
  - `CurvePricer(curve_map, pair, *, package_dv01_usd)` implementing `PricingContext` plus `theta(date)`; positions **age** (a package built on day 0 keeps its dates and is repriced on later curves) while panels stay constant-maturity.
  - `report.distribution_stats(daily_pnl: pd.Series) -> dict` with `sharpe_annualised`, `skew`, `kurtosis`, `max_drawdown`, `daily_pnl_vol`.
  - `report.vol_beta(monthly_pnl: pd.Series, vol_changes: pd.Series) -> dict` with `corr`, `beta`, `n`.

> **SUPERSEDED — READ THIS FIRST.** The gate described in this task was **run, and its criteria were measured non-discriminating.** A DV01-matched **zero-convexity twin** (constant-maturity flattener, no aging, no gamma, zero harvest) clears skew, Sharpe *and* vol-correlation with **better** numbers than the real package (skew +0.288 vs +0.087; vol-corr +0.613 vs +0.635; Sharpe +0.228 vs +0.046, inside the published band the real book misses), and the short-convexity **steepener** passes the skew criterion too (−0.0815). The instrument carries an unhedged first-order slope exposure holding ~95.6% of its daily variance, so its distribution *is* the slope's distribution, and `corr(−Δspread, Δvol)` reproduces the twin's vol correlation to four decimals. The twin is committed as a runnable null model. The criteria below are retained as the historical record of what was tried; **do not reinstate them, and do not record `harvest_to_mtm`** (renamed `harvest_flow_ratio` / `harvest_pnl_share` — see Task 18). Downstream work proceeds on the mechanism evidence listed in the design spec's superseded-positive-control section, not on this signature.

**This task was written as a gate.** The spec originally required that a faithful static-long reproduction recover the published distributional signature: Sharpe roughly 0.05–0.35 by pair, daily P&L skew ≈ 0 (versus ≈ −3 for a short 1m10y straddle), monthly P&L correlation to Δ1y10y vol ≈ +26%, with "the distribution, not the Sharpe" as the test. See the banner above for why that framing did not survive contact with the instrument.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_control.py
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.report import distribution_stats, vol_beta


def test_distribution_stats_on_a_known_series():
    r = pd.Series([1.0, -1.0] * 126)
    s = distribution_stats(r)
    assert s["skew"] == pytest.approx(0.0, abs=1e-9)
    assert s["daily_pnl_vol"] == pytest.approx(1.0, rel=0.01)
    assert s["sharpe_annualised"] == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_is_negative_and_measured_on_the_cumulative_path():
    r = pd.Series([1.0, 1.0, -5.0, 1.0])
    assert distribution_stats(r)["max_drawdown"] == pytest.approx(-5.0)


def test_vol_beta_recovers_a_planted_relationship():
    rng = np.random.default_rng(1)
    dvol = pd.Series(rng.normal(0, 1, 60))
    pnl = 0.4 * dvol + rng.normal(0, 0.1, 60)
    out = vol_beta(pnl, dvol)
    assert out["beta"] == pytest.approx(0.4, rel=0.15)
    assert out["corr"] > 0.9


@pytest.mark.network
@pytest.mark.slow
def test_static_long_flattener_has_the_long_vol_signature():
    """HISTORICAL. These assertions were measured non-discriminating — the
    zero-convexity twin passes all of them with better numbers. Retained only
    as the record of what was tried; see the SUPERSEDED banner above."""
    from scripts.sv_static_long_control import run_control

    res = run_control(
        market="USD",
        start=dt.date(2017, 1, 3),
        end=dt.date(2026, 8, 3),
    )
    daily = res["daily_pnl"]
    stats = distribution_stats(daily)

    assert len(daily) > 1500
    # skew near zero (the brief's ~0 vs ~-3 for a short 1m10y straddle)
    assert stats["skew"] > -1.0
    # positive correlation of monthly P&L to changes in implied vol
    assert res["vol_corr"] > 0.0
    # and a Sharpe in the published neighbourhood rather than a fantasy
    assert -0.5 < stats["sharpe_annualised"] < 1.5
```

- [ ] **Step 2: Run the fast tests to verify they fail**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_control.py -v -m "not network"
```
Expected: FAIL — `No module named 'RVUtils.StrikelessVol.report'`.

- [ ] **Step 3: Write `report.py`**

```python
# RVUtils/StrikelessVol/report.py
"""Distribution diagnostics. The distribution is the result, not the Sharpe."""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import TRADING_DAYS

__all__ = ["distribution_stats", "vol_beta"]


def distribution_stats(daily_pnl: pd.Series) -> dict:
    r = pd.Series(daily_pnl).astype(float).dropna()
    if r.empty:
        return {k: float("nan") for k in
                ("sharpe_annualised", "skew", "kurtosis", "max_drawdown", "daily_pnl_vol")}
    sd = float(r.std(ddof=1))
    cum = r.cumsum()
    dd = float((cum - cum.cummax()).min())
    return {
        "sharpe_annualised": float(r.mean() / sd * np.sqrt(TRADING_DAYS)) if sd else float("nan"),
        "skew": float(r.skew()),
        "kurtosis": float(r.kurtosis()),
        "max_drawdown": dd,
        "daily_pnl_vol": sd,
        "n": int(len(r)),
    }


def vol_beta(pnl: pd.Series, vol_changes: pd.Series) -> dict:
    """Regression of P&L on changes in implied vol -- the long-vol fingerprint."""
    df = pd.concat(
        [pd.Series(pnl).astype(float).rename("p"),
         pd.Series(vol_changes).astype(float).rename("v")],
        axis=1,
    ).dropna()
    if len(df) < 5:
        return {"corr": float("nan"), "beta": float("nan"), "n": len(df)}
    beta = float(np.polyfit(df["v"], df["p"], 1)[0])
    return {"corr": float(df["p"].corr(df["v"])), "beta": beta, "n": int(len(df))}
```

- [ ] **Step 4: Write `CurvePricer` in `replication.py`**

```python
class CurvePricer:
    """A ``PricingContext`` backed by real repriced curves.

    Holds ONE aged package: the legs are built on the inception curve and keep
    their dates, so a 10y10y bought today is priced as a 9y10y a year later.
    Panels elsewhere in this package are constant-maturity; mixing the two is
    the vintage trap, so the aging lives here and only here.
    """

    def __init__(self, curve_map: dict, pair, *, package_dv01_usd: float = 100_000.0,
                 sign: int = FLATTENER):
        from RVUtils.StrikelessVol.greeks import build_package

        self._curves = {pd.Timestamp(k): v for k, v in curve_map.items() if v is not None}
        self._dates = sorted(self._curves)
        self._pair = pair
        self._sign = sign
        self._package_dv01_usd = package_dv01_usd
        inception = self._curves[self._dates[0]]
        self._pkg = build_package(
            inception, pair, package_dv01_usd=package_dv01_usd, sign=sign
        )
        self._unit_dv01 = {
            "long": abs(self._pkg.long_dv01) / abs(self._pkg.long.__dict__["kwargs"]["notional"]),
            "short": abs(self._pkg.short_dv01) / abs(self._pkg.short.__dict__["kwargs"]["notional"]),
        }

    def _curve(self, date):
        return self._curves[pd.Timestamp(date)]

    def rate(self, date, leg: str) -> float:
        curve = self._curve(date)
        spec = self._pair.long if leg == "long" else self._pair.short
        return float(curve.fair_rate(curve.build_irswap(fwd=spec.fwd, tenor=spec.tail)))

    def dv01(self, date, leg: str) -> float:
        return self._unit_dv01[leg]

    def pv(self, date, notional_long: float, notional_short: float) -> float:
        """Reprice the AGED legs on ``date``'s curve at the requested notionals."""
        from RVUtils.StrikelessVol.greeks import package_npv

        curve = self._curve(date)
        scale_l = notional_long / self._pkg.long.__dict__["kwargs"]["notional"]
        scale_s = notional_short / self._pkg.short.__dict__["kwargs"]["notional"]
        return (
            scale_l * float(self._pkg.long.npv(curves=curve.handle()).real)
            + scale_s * float(self._pkg.short.npv(curves=curve.handle()).real)
        )

    def theta(self, date, notional_long: float, notional_short: float) -> float:
        """One day of repriced carry, scaled to the notionals actually held."""
        from RVUtils.StrikelessVol.greeks import daily_roll_usd

        curve = self._curve(date)
        nxt = curve.calendar_advance(curve.reference_date(), "1b")
        unit_roll = float(daily_roll_usd(curve, self._pkg, next_date=nxt))
        scale = abs(notional_long) / abs(curve.notional(self._pkg.long))
        return unit_roll * scale
```

If `rl.IRS` does not expose `__dict__["kwargs"]["notional"]` in rateslib 2.1.1, use `curve.notional(swap)` — the wrapper method exists for exactly this and is the safer call. Prefer it.

- [ ] **Step 5: Write the control runner**

```python
# scripts/sv_static_long_control.py
"""The Citi-style static-long reproduction. This is the gate on the greeks.

Buys the flattener, rebalances at the trigger, rolls annually, holds throughout.
Reports the DISTRIBUTION -- skew, correlation of monthly P&L to changes in
implied vol -- because that, not the Sharpe, is what a long-vol position must
look like.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from RVUtils.StrikelessVol.costs import CostSchedule
from RVUtils.StrikelessVol.panels import vol_panel
from RVUtils.StrikelessVol.replication import (
    CurvePricer,
    ReplicationConfig,
    reconcile,
    simulate,
)
from RVUtils.StrikelessVol.report import distribution_stats, vol_beta
from RVUtils.StrikelessVol.universe import ALL_PAIRS, MARKET_CURVES


def run_control(*, market: str = "USD", start: dt.date, end: dt.date,
                trigger_bp: float = 25.0, costs: CostSchedule | None = None) -> dict:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    pair = next(p for p in ALL_PAIRS if p.market == market
                and p.short.label == "10Y10Y" and p.long.label == "20Y10Y")
    dates = pd.bdate_range(start, end).date.tolist()
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    curve_map = mdp.bulk_get_data(
        {"curve_name": MARKET_CURVES[market], "timestamps": dates}
    )
    curve_map = {k: v for k, v in curve_map.items() if v is not None}

    ctx = CurvePricer(curve_map, pair, package_dv01_usd=100_000.0)
    led = simulate(ctx, sorted(curve_map), ReplicationConfig(trigger_bp=trigger_bp),
                   costs or CostSchedule())

    vols = vol_panel(
        {"USD": "USD-SOFR-1D", "EUR": "EUR-ESTR",
         "JPY": "JPY-TONAR", "GBP": "GBP-SONIA"}[market],
        ["1y 10y"], start, end,
    )
    monthly_pnl = led["total"].resample("ME").sum()
    monthly_dvol = vols["1y10y"].resample("ME").last().diff()
    vb = vol_beta(monthly_pnl, monthly_dvol)

    return {
        "pair": pair.name,
        "daily_pnl": led["total"],
        "ledger": led,
        "stats": distribution_stats(led["total"]),
        "vol_corr": vb["corr"],
        "vol_beta": vb["beta"],
        "reconciliation": reconcile(led),
        "harvest_to_mtm": float(
            led["harvest"].abs().sum() / max(led["mtm"].abs().sum(), 1e-9)
        ),
    }


if __name__ == "__main__":
    res = run_control(market="USD", start=dt.date(2017, 1, 3), end=dt.date(2026, 8, 3))
    print(res["pair"])
    print(pd.Series(res["stats"]))
    print("monthly P&L corr to d(1y10y vol):", round(res["vol_corr"], 3))
    print("harvest / |mtm|:", round(res["harvest_to_mtm"], 4))
    print("reconciliation:", res["reconciliation"])
```

- [ ] **Step 6: Run the fast tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_control.py -v -m "not network"
```
Expected: 3 passed.

- [ ] **Step 7: Run the gate**

```
conda run -n stir python scripts/sv_static_long_control.py
conda run -n stir python -m pytest tests/test_strikeless_vol_control.py -v -m network
```

Record in the commit message: Sharpe, skew, kurtosis, max drawdown, `vol_corr`, `harvest_flow_ratio`, `harvest_pnl_share`, and the reconciliation dict — **and the same statistics for the zero-convexity twin beside them**, since the twin clearing the published anchors more comfortably than the real package is the finding, not a footnote.

**SUPERSEDED — this stop condition was measured to have no discriminating power.** It was retained through implementation and then falsified: the zero-convexity twin clears skew and `vol_corr` more comfortably than the real package, and the steepener passes the skew bound at −0.0815. Do **not** stop or proceed on these numbers. The debugging order below remains useful for its own sake, since each item is a genuine failure mode — particularly (4), which is how a rebuilt-daily package produces a zero-gamma result: (1) `reconcile` — is the plug at float scale? (2) the sign of `daily_roll_usd` on an inverted curve — a flattener must bleed; (3) `PAYER_NOTIONAL_SIGN`; (4) whether `CurvePricer.pv` reprices the *aged* legs rather than rebuilding constant-maturity ones each day.

- [ ] **Step 8: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/replication.py RVUtils/StrikelessVol/report.py scripts/sv_static_long_control.py tests/test_strikeless_vol_control.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): CurvePricer and the static-long positive control"
```

---

### Task 14: The factor model — changes, levels, and the frequency ladder

**Files:**
- Create: `RVUtils/StrikelessVol/factors.py`
- Test: `tests/test_strikeless_vol_factors.py`

**Interfaces:**
- Consumes: panels from Tasks 4–6.
- Produces:
  - `RegressionResult` frozen dataclass: `betas: dict[str, float]`, `tstats: dict[str, float]`, `r_squared`, `durbin_watson`, `n`, `kind` (`"changes"`/`"levels"`), `anchor_only: bool`, `residuals: pd.Series`.
  - `changes_regression(spread_bp, drivers: dict[str, pd.Series], *, horizon_days=1, hac_lags=None) -> RegressionResult`.
  - `levels_regression(spread_bp, drivers) -> RegressionResult` — always returns `anchor_only=True`.
  - `frequency_ladder(spread_bp, drivers, horizons=(1,5,21)) -> pd.DataFrame`.
  - `durbin_watson(resid) -> float`.

**Discipline encoded here (H1, and the spec's honesty rules):** inference runs on changes with HAC (Newey–West) standard errors; levels regressions are RV anchors and carry `anchor_only=True` so no consumer can quietly treat their t-stats as inference. The 2026 sample's levels DW ≈ 0.2 is the reason.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_factors.py
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.factors import (
    changes_regression,
    durbin_watson,
    frequency_ladder,
    levels_regression,
)


@pytest.fixture
def planted():
    """A world where d(spread) = -0.78 * d(vol) + noise, by construction."""
    rng = np.random.default_rng(7)
    n = 1500
    idx = pd.bdate_range("2020-01-01", periods=n)
    dvol = rng.normal(0.0, 0.05, n)
    vol = pd.Series(80.0 + np.cumsum(dvol), index=idx)
    dspread = -0.78 * dvol + rng.normal(0.0, 0.5, n)
    spread = pd.Series(-50.0 + np.cumsum(dspread), index=idx)
    return spread, vol


def test_changes_regression_recovers_the_planted_beta(planted):
    spread, vol = planted
    res = changes_regression(spread, {"vol": vol})
    assert res.kind == "changes"
    assert res.anchor_only is False
    assert res.betas["vol"] == pytest.approx(-0.78, rel=0.15)
    assert abs(res.tstats["vol"]) > 2.0


def test_changes_regression_residuals_are_not_autocorrelated(planted):
    spread, vol = planted
    res = changes_regression(spread, {"vol": vol})
    assert 1.7 < res.durbin_watson < 2.3


def test_levels_regression_is_flagged_anchor_only(planted):
    spread, vol = planted
    res = levels_regression(spread, {"vol": vol})
    assert res.anchor_only is True
    assert res.kind == "levels"
    # trending data -> DW near zero, which is exactly why it is anchor-only
    assert res.durbin_watson < 0.6


def test_durbin_watson_of_white_noise_is_two():
    rng = np.random.default_rng(3)
    assert durbin_watson(pd.Series(rng.normal(0, 1, 5000))) == pytest.approx(2.0, abs=0.1)


def test_durbin_watson_of_a_random_walk_is_near_zero():
    rng = np.random.default_rng(3)
    assert durbin_watson(pd.Series(np.cumsum(rng.normal(0, 1, 5000)))) < 0.3


def test_frequency_ladder_reports_every_horizon(planted):
    spread, vol = planted
    lad = frequency_ladder(spread, {"vol": vol}, horizons=(1, 5, 21))
    assert list(lad["horizon_days"]) == [1, 5, 21]
    assert {"beta_vol", "t_vol", "r_squared", "n"} <= set(lad.columns)


def test_two_factor_regression_returns_both_betas(planted):
    spread, vol = planted
    rng = np.random.default_rng(11)
    umep = pd.Series(
        2.0 + np.cumsum(rng.normal(0.0, 0.01, len(spread))), index=spread.index
    )
    res = changes_regression(spread, {"vol": vol, "umep": umep})
    assert set(res.betas) == {"vol", "umep"}
    assert set(res.tstats) == {"vol", "umep"}
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_factors.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/factors.py
"""The factor model: what moves the ultra-long forward slope.

Inference runs on CHANGES with HAC (Newey-West) standard errors. Levels
regressions are computed too, because they are the RV anchor the residual
z-score is built on, but they are returned with ``anchor_only=True``: in the
2026 sample the levels Durbin-Watson is ~0.2, so their t-statistics are not
evidence of anything and no consumer may treat them as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm

__all__ = [
    "RegressionResult",
    "changes_regression",
    "levels_regression",
    "frequency_ladder",
    "durbin_watson",
]


@dataclass(frozen=True)
class RegressionResult:
    betas: Dict[str, float]
    tstats: Dict[str, float]
    r_squared: float
    durbin_watson: float
    n: int
    kind: str
    anchor_only: bool
    residuals: pd.Series = field(repr=False)


def durbin_watson(resid) -> float:
    e = pd.Series(resid).astype(float).dropna().to_numpy()
    if e.size < 3:
        return float("nan")
    de = np.diff(e)
    return float((de @ de) / (e @ e))


def _fit(y: pd.Series, X: pd.DataFrame, *, kind: str, anchor_only: bool,
         hac_lags: Optional[int]) -> RegressionResult:
    data = pd.concat([y.rename("_y_"), X], axis=1).dropna()
    if len(data) < 10:
        raise ValueError(f"only {len(data)} aligned observations")
    cols = [c for c in data.columns if c != "_y_"]
    Xm = sm.add_constant(data[cols])
    model = sm.OLS(data["_y_"], Xm).fit()
    lags = hac_lags if hac_lags is not None else max(1, int(round(len(data) ** 0.25)))
    robust = model.get_robustcov_results(cov_type="HAC", maxlags=lags)
    return RegressionResult(
        betas={c: float(model.params[c]) for c in cols},
        tstats={c: float(robust.tvalues[list(Xm.columns).index(c)]) for c in cols},
        r_squared=float(model.rsquared),
        durbin_watson=durbin_watson(model.resid),
        n=int(len(data)),
        kind=kind,
        anchor_only=anchor_only,
        residuals=model.resid,
    )


def changes_regression(
    spread_bp: pd.Series,
    drivers: Dict[str, pd.Series],
    *,
    horizon_days: int = 1,
    hac_lags: Optional[int] = None,
) -> RegressionResult:
    """d(spread) on d(drivers) at ``horizon_days``. This is where inference lives."""
    y = pd.Series(spread_bp).astype(float).diff(horizon_days)
    X = pd.DataFrame(
        {k: pd.Series(v).astype(float).diff(horizon_days) for k, v in drivers.items()}
    )
    return _fit(y, X, kind="changes", anchor_only=False, hac_lags=hac_lags)


def levels_regression(
    spread_bp: pd.Series, drivers: Dict[str, pd.Series],
    *, hac_lags: Optional[int] = None,
) -> RegressionResult:
    """Levels fit. RV anchor only -- never inference. See the module docstring."""
    y = pd.Series(spread_bp).astype(float)
    X = pd.DataFrame({k: pd.Series(v).astype(float) for k, v in drivers.items()})
    return _fit(y, X, kind="levels", anchor_only=True, hac_lags=hac_lags)


def frequency_ladder(
    spread_bp: pd.Series,
    drivers: Dict[str, pd.Series],
    horizons: Sequence[int] = (1, 5, 21),
) -> pd.DataFrame:
    """H1: is the funding factor a weekly/monthly effect invisible daily?"""
    rows = []
    for h in horizons:
        res = changes_regression(spread_bp, drivers, horizon_days=int(h))
        rec = {"horizon_days": int(h), "r_squared": res.r_squared, "n": res.n,
               "durbin_watson": res.durbin_watson}
        for k in drivers:
            rec[f"beta_{k}"] = res.betas[k]
            rec[f"t_{k}"] = res.tstats[k]
        rows.append(rec)
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_factors.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/factors.py tests/test_strikeless_vol_factors.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): changes/levels regressions with HAC errors and a frequency ladder"
```

---

### Task 15: Residual dynamics, drift, and reproducing the 2026 numbers

**Files:**
- Modify: `RVUtils/StrikelessVol/factors.py`
- Create: `scripts/sv_reproduce_2026.py`
- Test: `tests/test_strikeless_vol_residuals.py`

**Interfaces:**
- Consumes: Task 14's `RegressionResult`, `RVUtils.regression.residual_diagnostics`.
- Produces:
  - `ar1_phi(resid) -> float`, `ar1_half_life_days(resid) -> float`.
  - `residual_z(resid, *, window=252, min_periods=126) -> pd.Series` — rolling z on the residual's own dispersion.
  - `drift(changes_resid, *, window=63) -> pd.DataFrame` with columns `mean_bp_per_day`, `t_stat` (Newey–West via `RVUtils.SFRRVLab.stats.nw_tstat`).
  - `positive_residual_clustering(resid, *, window=21) -> pd.Series` — share of positive residuals in the window, the regime tell.

**The band discipline (H6):** entry bands come from the residual's **own AR-adjusted dispersion**, not from the OLS standard error. The OLS SE is `σ/√n` and shrinks with sample size, so bands built on it tighten as history accumulates and would fire constantly. `residual_z` therefore divides by a rolling standard deviation of the residual itself.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_residuals.py
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.factors import (
    ar1_half_life_days,
    ar1_phi,
    drift,
    positive_residual_clustering,
    residual_z,
)


def _ar1(phi, n=4000, sigma=1.0, seed=0):
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sigma, n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return pd.Series(x, index=pd.bdate_range("2015-01-01", periods=n))


def test_ar1_phi_recovers_a_planted_persistence():
    assert ar1_phi(_ar1(0.87)) == pytest.approx(0.87, abs=0.03)


def test_half_life_of_phi_087_is_about_a_week():
    hl = ar1_half_life_days(_ar1(0.87))
    assert 4.0 < hl < 7.0  # ln(0.5)/ln(0.87) = 4.98 business days


def test_half_life_is_infinite_for_a_random_walk():
    rng = np.random.default_rng(1)
    rw = pd.Series(np.cumsum(rng.normal(0, 1, 3000)))
    assert not np.isfinite(ar1_half_life_days(rw)) or ar1_half_life_days(rw) > 100


def test_residual_z_uses_the_residuals_own_dispersion_not_the_ols_se():
    s = _ar1(0.5, n=1000, sigma=2.0)
    z = residual_z(s, window=252, min_periods=126).dropna()
    # a z built on sigma/sqrt(n) would be sqrt(252) times too large
    assert z.abs().max() < 6.0
    assert z.std() == pytest.approx(1.0, abs=0.25)


def test_drift_detects_a_planted_positive_mean():
    rng = np.random.default_rng(2)
    x = pd.Series(0.2 + rng.normal(0, 1.0, 500),
                  index=pd.bdate_range("2024-01-01", periods=500))
    out = drift(x, window=250)
    assert out["mean_bp_per_day"].iloc[-1] == pytest.approx(0.2, abs=0.15)
    assert out["t_stat"].iloc[-1] > 1.5


def test_drift_is_flat_for_zero_mean_noise():
    rng = np.random.default_rng(3)
    x = pd.Series(rng.normal(0, 1.0, 500),
                  index=pd.bdate_range("2024-01-01", periods=500))
    out = drift(x, window=250)
    assert abs(out["t_stat"].iloc[-1]) < 2.0


def test_clustering_is_one_when_every_residual_is_positive():
    x = pd.Series(np.ones(50), index=pd.bdate_range("2026-01-01", periods=50))
    assert positive_residual_clustering(x, window=21).iloc[-1] == pytest.approx(1.0)
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_residuals.py -v
```
Expected: FAIL — `cannot import name 'ar1_phi'`.

- [ ] **Step 3: Write the implementation (append to `factors.py`)**

```python
def ar1_phi(resid) -> float:
    """OLS AR(1) coefficient of a residual series."""
    e = pd.Series(resid).astype(float).dropna()
    if len(e) < 20:
        return float("nan")
    x, y = e.shift(1).dropna(), e.iloc[1:]
    return float(np.polyfit(x.to_numpy(), y.to_numpy(), 1)[0])


def ar1_half_life_days(resid) -> float:
    """Business days to halve. Infinite for a unit root."""
    phi = ar1_phi(resid)
    if not np.isfinite(phi) or phi <= 0.0 or phi >= 1.0:
        return float("inf")
    return float(np.log(0.5) / np.log(phi))


def residual_z(resid, *, window: int = 252, min_periods: int = 126) -> pd.Series:
    """Rolling z on the residual's OWN dispersion.

    Not the OLS standard error: that is sigma/sqrt(n), it shrinks with sample
    size, and bands built on it tighten as history accumulates until the rule
    fires constantly.
    """
    e = pd.Series(resid).astype(float)
    roll = e.rolling(int(window), min_periods=int(min_periods))
    return (e - roll.mean()) / roll.std(ddof=1)


def drift(changes_resid, *, window: int = 63) -> pd.DataFrame:
    """Signal 2: the vol-orthogonal structural drift, and its significance."""
    from RVUtils.SFRRVLab.stats import nw_tstat

    e = pd.Series(changes_resid).astype(float)
    mean = e.rolling(int(window), min_periods=int(window)).mean()
    t = e.rolling(int(window), min_periods=int(window)).apply(
        lambda w: nw_tstat(w, lags=5), raw=False
    )
    return pd.DataFrame({"mean_bp_per_day": mean, "t_stat": t})


def positive_residual_clustering(resid, *, window: int = 21) -> pd.Series:
    """Share of positive residuals in the window -- the regime tell (H4)."""
    e = pd.Series(resid).astype(float)
    return (e > 0).rolling(int(window), min_periods=int(window)).mean()
```

Extend `__all__` with the five new names.

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_residuals.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Write the reproduction script**

```python
# scripts/sv_reproduce_2026.py
"""Reproduce the brief's 2026 USD numbers from raw data before extending.

Targets (2026 YTD, ~147 daily observations, USD 10y10y/20y10y):
  changes, 1 factor : beta ~ -0.78, R2 ~ 0.34, DW ~ 2.54
  changes, 2 factor : vol ~ -0.67 (significant), ASW ~ -0.17 (t ~ -1.2), R2 ~ 0.345
  levels,  2 factor : y = 5.66 - 1.18*vol + 0.443*ASW, R2 ~ 0.455, DW ~ 0.2-0.26
  levels residual   : AR(1) ~ 0.87 -> about a one-week half-life
  spread daily vol  : ~1.65 bp/day
Anything that misses badly is a data or convention problem, not a discovery.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from RVUtils.StrikelessVol.factors import (
    ar1_half_life_days,
    ar1_phi,
    changes_regression,
    frequency_ladder,
    levels_regression,
)
from RVUtils.StrikelessVol.panels import forward_rate_panel, spread_panel, umep_panel, vol_panel
from RVUtils.StrikelessVol.universe import ALL_PAIRS
from RVUtils.StrikelessVol.vol_metrics import spread_vol_bp_day


def build(start=dt.date(2026, 1, 2), end=dt.date(2026, 8, 3)) -> dict:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    pair = next(p for p in ALL_PAIRS if p.name == "USD 10Y10Y/20Y10Y")
    dates = pd.bdate_range(start, end).date.tolist()
    rates = forward_rate_panel(
        "USD-OIS", dates, [pair.short, pair.long], mdp=IRSwapsMDP(source="GSQUANT-RL")
    )
    spread = spread_panel(rates, pair)
    vols = vol_panel("USD-SOFR-1D", ["2y 10y", "10y 10y"], start, end)
    vol_ann = vols["2y10y"] * (252 ** 0.5)  # the brief quotes annual normals
    umep = umep_panel(start, end)
    return {"pair": pair, "spread": spread, "vol_ann": vol_ann,
            "umep": umep.get("umep_bp_per_year"), "mmss_30y": umep.get("mmss_30Y")}


def main() -> None:
    d = build()
    spread, vol = d["spread"], d["vol_ann"]

    one = changes_regression(spread, {"vol": vol})
    print(f"changes 1F: beta={one.betas['vol']:+.3f} t={one.tstats['vol']:+.2f} "
          f"R2={one.r_squared:.3f} DW={one.durbin_watson:.2f} n={one.n}")

    if d["mmss_30y"] is not None:
        two = changes_regression(spread, {"vol": vol, "asw30": d["mmss_30y"]})
        print(f"changes 2F: vol={two.betas['vol']:+.3f} (t={two.tstats['vol']:+.2f}) "
              f"asw={two.betas['asw30']:+.3f} (t={two.tstats['asw30']:+.2f}) "
              f"R2={two.r_squared:.3f}")

        lev = levels_regression(spread, {"vol": vol, "asw30": d["mmss_30y"]})
        print(f"levels  2F: vol={lev.betas['vol']:+.3f} asw={lev.betas['asw30']:+.3f} "
              f"R2={lev.r_squared:.3f} DW={lev.durbin_watson:.2f} [ANCHOR ONLY]")
        print(f"levels residual: phi={ar1_phi(lev.residuals):.3f} "
              f"half_life={ar1_half_life_days(lev.residuals):.1f}d "
              f"latest={lev.residuals.iloc[-1]:+.2f}bp")

    print(f"spread daily vol: {spread_vol_bp_day(spread, window=63).iloc[-1]:.2f} bp/day")
    print(frequency_ladder(spread, {"vol": vol}).to_string(index=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run it and record the comparison**

```
conda run -n stir python scripts/sv_reproduce_2026.py
```

Write the printed table into the commit message next to the targets above. Judge each line: a changes beta of −0.78 ± 0.25 and R² of 0.34 ± 0.12 counts as reproduced; a beta of the wrong **sign** does not, and means the slope or the vol series is inverted somewhere. Do not tune anything to hit the targets — record the gap and move on, noting it in the findings.

- [ ] **Step 7: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/factors.py scripts/sv_reproduce_2026.py tests/test_strikeless_vol_residuals.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): residual dynamics, drift, and the 2026 reproduction script"
```

---

### Task 16: H2 (drag vs common factor) and H3 (beta scales with vol)

**Files:**
- Create: `RVUtils/StrikelessVol/treasury_forwards.py`
- Modify: `RVUtils/StrikelessVol/factors.py` (add `beta_vs_vol_level`)
- Create: `scripts/sv_h2_h3.py`
- Test: `tests/test_strikeless_vol_treasury_forwards.py`

**Interfaces:**
- Consumes: `MDP.FixedRateBonds`, `MDP.FixedRateBonds.cash_spline.CashSpline` (`yield_at(ttm)` returns the fitted **par** yield), Task 14's regressions.
- Produces:
  - `par_to_discount(ttms: np.ndarray, par_yields: np.ndarray, *, freq: int = 2) -> np.ndarray` — bootstrap par curve to discount factors on the same grid.
  - `forward_par_rate(ttms, dfs, *, fwd_years, tail_years, freq=2) -> float`.
  - `treasury_forward_panel(spline_by_date: dict, legs) -> pd.DataFrame` — same shape as `panels.forward_rate_panel`, so every downstream regression accepts it unchanged.
  - `factors.beta_vs_vol_level(spread_bp, vol_ann, *, window=126) -> pd.DataFrame` with `beta`, `vol_level`, and the fitted slope of beta on vol.

**What each hypothesis needs:**
- **H2**: regress the *swap* forward slope and the *Treasury-built* forward slope on the same UMEP series. The drag channel (rising funding premium mechanically pulls long swaps down relative to bonds) exists only in the swap curve, so it must **vanish** on Treasury forwards. Under the tool convention, drag ⇒ negative coefficient, common-factor ⇒ positive. Report the pair of coefficients; the discriminator is the *difference*, not either one alone.
- **H3**: convexity ∝ σ², so ∂spread/∂σ ∝ σ. Rolling changes-betas regressed on the contemporaneous vol level should show a negative slope of `|beta|` growth in σ. Citi's −0.5 at ~65–70 normals scales to ≈ −0.63 at 84.6; measured values were −0.67/−0.78.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_treasury_forwards.py
import numpy as np
import pytest

from RVUtils.StrikelessVol.treasury_forwards import (
    forward_par_rate,
    par_to_discount,
)


def _analytic_curve(rate, ttms, freq=2):
    """Discount factors and par yields of a flat continuously-quoted curve."""
    dfs = 1.0 / (1.0 + rate / freq) ** (ttms * freq)
    return dfs


def test_bootstrap_round_trips_a_flat_par_curve():
    ttms = np.arange(0.5, 40.5, 0.5)
    par = np.full_like(ttms, 0.04)
    dfs = par_to_discount(ttms, par, freq=2)
    expected = _analytic_curve(0.04, ttms)
    assert np.allclose(dfs, expected, atol=1e-10)


def test_forward_par_rate_of_a_flat_curve_is_the_flat_rate():
    ttms = np.arange(0.5, 40.5, 0.5)
    dfs = par_to_discount(ttms, np.full_like(ttms, 0.04), freq=2)
    fwd = forward_par_rate(ttms, dfs, fwd_years=10, tail_years=10)
    assert fwd == pytest.approx(0.04, abs=1e-8)


def test_forward_of_an_upward_sloping_curve_exceeds_the_spot_rate():
    ttms = np.arange(0.5, 40.5, 0.5)
    par = 0.03 + 0.0005 * ttms
    dfs = par_to_discount(ttms, par, freq=2)
    fwd = forward_par_rate(ttms, dfs, fwd_years=10, tail_years=10)
    spot20 = float(np.interp(20.0, ttms, par))
    assert fwd > spot20


def test_discount_factors_are_monotone_decreasing():
    ttms = np.arange(0.5, 40.5, 0.5)
    dfs = par_to_discount(ttms, 0.03 + 0.0005 * ttms, freq=2)
    assert np.all(np.diff(dfs) < 0)


def test_bootstrap_rejects_an_unsorted_grid():
    with pytest.raises(ValueError):
        par_to_discount(np.array([2.0, 1.0]), np.array([0.04, 0.04]))
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_treasury_forwards.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/treasury_forwards.py
"""Forward par rates built off the Treasury curve.

H2's discriminator. If the ultra-long forward slope inverts because a rising
term funding premium drags long SWAP rates down relative to bonds, then the
same slope built from TREASURY forwards should not show the effect: there is no
swap leg to drag. If instead a single balance-sheet regime cheapens bonds versus
swaps AND removes the receiving bid, both curves move together.

The Treasury curve arrives as a fitted PAR curve (``CashSpline.yield_at``), so
it is bootstrapped to discount factors before any forward is taken.
"""
from __future__ import annotations

from typing import Dict, Iterable

import numpy as np
import pandas as pd

__all__ = ["par_to_discount", "forward_par_rate", "treasury_forward_panel"]


def par_to_discount(ttms, par_yields, *, freq: int = 2) -> np.ndarray:
    """Bootstrap a par curve to discount factors on the same (sorted) grid.

    ``ttms`` must be sorted ascending and evenly spaced at ``1/freq`` years -- a
    par bond's coupon dates have to land on grid points for the bootstrap to be
    exact rather than interpolated.
    """
    t = np.asarray(ttms, dtype=float)
    c = np.asarray(par_yields, dtype=float)
    if t.ndim != 1 or np.any(np.diff(t) <= 0):
        raise ValueError("ttms must be strictly increasing")
    if c.shape != t.shape:
        raise ValueError("par_yields must match ttms")

    dfs = np.empty_like(t)
    annuity = 0.0
    for i, (ti, ci) in enumerate(zip(t, c)):
        coupon = ci / freq
        dfs[i] = (1.0 - coupon * annuity) / (1.0 + coupon)
        annuity += dfs[i]
    return dfs


def forward_par_rate(ttms, dfs, *, fwd_years: float, tail_years: float,
                     freq: int = 2) -> float:
    """Par rate of a swap starting in ``fwd_years`` running ``tail_years``."""
    t = np.asarray(ttms, dtype=float)
    d = np.asarray(dfs, dtype=float)
    start, end = float(fwd_years), float(fwd_years + tail_years)
    grid = np.arange(start + 1.0 / freq, end + 1e-9, 1.0 / freq)
    d_start = float(np.interp(start, t, d))
    d_end = float(np.interp(end, t, d))
    annuity = float(np.sum(np.interp(grid, t, d)) / freq)
    if annuity <= 0.0:
        return float("nan")
    return (d_start - d_end) / annuity


def treasury_forward_panel(spline_by_date: Dict, legs: Iterable) -> pd.DataFrame:
    """Same shape as ``panels.forward_rate_panel`` so regressions are unchanged."""
    legs = list(legs)
    grid = np.arange(0.5, 40.5, 0.5)
    rows = []
    for ts in sorted(spline_by_date):
        spline = spline_by_date[ts]
        if spline is None:
            continue
        try:
            par = np.asarray([float(spline.yield_at(x)) for x in grid], dtype=float)
            if np.nanmax(par) > 1.0:  # spline may quote percent
                par = par / 100.0
            dfs = par_to_discount(grid, par)
            rec = {
                leg.label: forward_par_rate(
                    grid, dfs, fwd_years=leg.fwd_years, tail_years=leg.tail_years
                )
                for leg in legs
            }
        except Exception:
            continue
        rec["date"] = pd.Timestamp(ts)
        rows.append(rec)
    if not rows:
        return pd.DataFrame(columns=[l.label for l in legs])
    return pd.DataFrame(rows).set_index("date").sort_index()
```

Append to `factors.py`:

```python
def beta_vs_vol_level(spread_bp, vol_ann, *, window: int = 126) -> pd.DataFrame:
    """H3: convexity is proportional to sigma^2, so the beta should scale in sigma."""
    from RVUtils.regression import rolling_beta_stability

    dy = pd.Series(spread_bp).astype(float).diff()
    dx = pd.Series(vol_ann).astype(float).diff()
    tbl = rolling_beta_stability(dy, dx.rename("vol"), window_beta=int(window))
    out = pd.DataFrame(
        {"beta": tbl["beta_vol"], "vol_level": pd.Series(vol_ann).astype(float)}
    ).dropna()
    if len(out) > 10:
        slope, intercept = np.polyfit(out["vol_level"], out["beta"], 1)
        out.attrs["beta_on_vol_slope"] = float(slope)
        out.attrs["beta_on_vol_intercept"] = float(intercept)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_treasury_forwards.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Write and run the H2/H3 script**

```python
# scripts/sv_h2_h3.py
"""H2: drag vs common factor. H3: does the vol beta scale with the vol level?"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from RVUtils.StrikelessVol.factors import beta_vs_vol_level, changes_regression
from RVUtils.StrikelessVol.panels import forward_rate_panel, spread_panel, umep_panel, vol_panel
from RVUtils.StrikelessVol.treasury_forwards import treasury_forward_panel
from RVUtils.StrikelessVol.universe import ALL_PAIRS


def main(start=dt.date(2017, 1, 3), end=dt.date(2026, 8, 3)) -> None:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    pair = next(p for p in ALL_PAIRS if p.name == "USD 10Y10Y/20Y10Y")
    dates = pd.bdate_range(start, end).date.tolist()

    swap_rates = forward_rate_panel(
        "USD-OIS", dates, [pair.short, pair.long], mdp=IRSwapsMDP(source="GSQUANT-RL")
    )
    swap_slope = spread_panel(swap_rates, pair)

    # Treasury-built forwards over the same dates. Build the spline map first;
    # see Query/FixedRateBonds/spline_values.compute_spline_for_date and
    # expand_pricer_universe_for_spline for the pricer-universe plumbing.
    from scripts.sv_treasury_splines import spline_map  # written in this task

    ust_rates = treasury_forward_panel(spline_map(dates), [pair.short, pair.long])
    ust_slope = spread_panel(ust_rates, pair)

    vols = vol_panel("USD-SOFR-1D", ["2y 10y", "10y 10y"], start, end)
    vol_ann = vols["2y10y"] * (252 ** 0.5)
    umep = umep_panel(start, end)["umep_bp_per_year"]

    for label, slope in (("swap", swap_slope), ("treasury", ust_slope)):
        for h in (1, 5, 21):
            r = changes_regression(slope, {"vol": vol_ann, "umep": umep}, horizon_days=h)
            print(f"{label:8s} h={h:2d}d  vol={r.betas['vol']:+.3f} (t={r.tstats['vol']:+.2f})  "
                  f"umep={r.betas['umep']:+.3f} (t={r.tstats['umep']:+.2f})  R2={r.r_squared:.3f}")

    tbl = beta_vs_vol_level(swap_slope, vol_ann)
    print("\nH3 beta-on-vol slope:", tbl.attrs.get("beta_on_vol_slope"))
    print(tbl.tail())


if __name__ == "__main__":
    main()
```

Also write `scripts/sv_treasury_splines.py` exposing `spline_map(dates) -> dict[date, CashSpline]`, built from `FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")` pricers via `expand_pricer_universe_for_spline` and `compute_spline_for_date`. Cache it to `notebooks/data/strikeless_vol/ust_splines.pkl` — refitting a decade of splines twice is wasted hours.

Run: `conda run -n stir python scripts/sv_h2_h3.py`

Record in the commit message: the UMEP coefficient sign and significance on swap-built versus Treasury-built forwards at each horizon, and the H3 slope. State the verdict explicitly — drag, common-factor, or unresolved — and say which of the two would have to be wrong for the other reading to hold.

- [ ] **Step 6: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/treasury_forwards.py RVUtils/StrikelessVol/factors.py scripts/sv_h2_h3.py scripts/sv_treasury_splines.py tests/test_strikeless_vol_treasury_forwards.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): Treasury-built forwards for H2 and the beta-vs-vol-level test for H3"
```

---

### Task 17: The two-sided conditional rule

**Files:**
- Create: `RVUtils/StrikelessVol/strategy.py`
- Test: `tests/test_strikeless_vol_strategy.py`

**Interfaces:**
- Consumes: `conventions.FLATTENER/STEEPENER`, Tasks 10, 15.
- Produces:
  - `SignalConfig(be_cheap=0.8, be_rich=1.2, drift_t_gate=2.0, z_entry=1.5, z_exit=0.0, size_floor=0.0, size_cap=1.0, short_side_enabled=True, iv_spike_gate_z=2.0)`.
  - `signal_state(row: pd.Series, cfg: SignalConfig) -> dict` with keys `sign`, `size`, `reason`.
  - `build_signals(panel: pd.DataFrame, cfg: SignalConfig) -> pd.DataFrame` with columns `sign`, `size`, `reason`, `dv01_usd`.
  - Input panel columns required: `be_over_realized`, `drift_t`, `residual_z`, `spread_vol_bp_day`, `iv_z`.

**The rule, restated as code contract:**
1. **Valuation** sets the sign: `be_over_realized < be_cheap` → flattener; `> be_rich` → steepener; between → flat.
2. **Drift** can veto: a significantly positive vol-orthogonal drift (`drift_t > drift_t_gate`) is a structural cost to flatteners and cancels a *mildly* cheap flattener signal.
3. **Residual z** scales size, not sign; `|z| < z_entry` means no new risk.
4. **Short-convexity side is gated**: an implied-vol spike (`iv_z > iv_spike_gate_z`) forces the steepener flat. A crowded carry steepener unwinds as a flattening squeeze.
5. Size is risk-parity on `spread_vol_bp_day`, capped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_strategy.py
import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER
from RVUtils.StrikelessVol.strategy import SignalConfig, build_signals, signal_state


def _row(**kw):
    base = {"be_over_realized": 1.0, "drift_t": 0.0, "residual_z": 0.0,
            "spread_vol_bp_day": 1.65, "iv_z": 0.0}
    base.update(kw)
    return pd.Series(base)


def test_cheap_breakeven_buys_convexity():
    st = signal_state(_row(be_over_realized=0.45, residual_z=2.0), SignalConfig())
    assert st["sign"] == FLATTENER
    assert st["size"] > 0


def test_rich_breakeven_sells_convexity():
    st = signal_state(_row(be_over_realized=1.6, residual_z=-2.0), SignalConfig())
    assert st["sign"] == STEEPENER


def test_fair_breakeven_is_flat():
    st = signal_state(_row(be_over_realized=1.0, residual_z=3.0), SignalConfig())
    assert st["sign"] == 0
    assert st["size"] == 0.0


def test_positive_drift_vetoes_a_mildly_cheap_flattener():
    cfg = SignalConfig()
    st = signal_state(_row(be_over_realized=0.78, drift_t=3.0, residual_z=2.0), cfg)
    assert st["sign"] == 0
    assert "drift" in st["reason"]


def test_positive_drift_does_not_veto_a_deeply_cheap_flattener():
    st = signal_state(
        _row(be_over_realized=0.35, drift_t=3.0, residual_z=2.0), SignalConfig()
    )
    assert st["sign"] == FLATTENER


def test_small_residual_z_means_no_new_risk():
    st = signal_state(_row(be_over_realized=0.45, residual_z=0.3), SignalConfig())
    assert st["size"] == 0.0


def test_vol_spike_gates_the_short_convexity_side_only():
    cfg = SignalConfig()
    short = signal_state(_row(be_over_realized=1.6, residual_z=-2.0, iv_z=3.0), cfg)
    long_ = signal_state(_row(be_over_realized=0.45, residual_z=2.0, iv_z=3.0), cfg)
    assert short["sign"] == 0
    assert long_["sign"] == FLATTENER


def test_short_side_can_be_disabled_entirely():
    cfg = SignalConfig(short_side_enabled=False)
    st = signal_state(_row(be_over_realized=1.6, residual_z=-2.0), cfg)
    assert st["sign"] == 0


def test_size_is_inverse_to_spread_vol():
    cfg = SignalConfig()
    quiet = signal_state(_row(be_over_realized=0.45, residual_z=2.0,
                              spread_vol_bp_day=1.0), cfg)
    noisy = signal_state(_row(be_over_realized=0.45, residual_z=2.0,
                              spread_vol_bp_day=4.0), cfg)
    assert quiet["size"] > noisy["size"]


def test_build_signals_is_row_wise_and_lagged():
    panel = pd.DataFrame(
        {
            "be_over_realized": [0.45, 0.45],
            "drift_t": [0.0, 0.0],
            "residual_z": [2.0, 2.0],
            "spread_vol_bp_day": [1.65, 1.65],
            "iv_z": [0.0, 0.0],
        },
        index=pd.bdate_range("2026-08-03", periods=2),
    )
    out = build_signals(panel, SignalConfig())
    assert list(out.columns) >= ["sign", "size", "reason", "dv01_usd"]
    # lag-1: the first row cannot act on its own day's information
    assert out["sign"].iloc[0] == 0
    assert out["sign"].iloc[1] == FLATTENER
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_strategy.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# RVUtils/StrikelessVol/strategy.py
"""The conditional two-sided rule: valuation sets the sign, drift can veto it,
the RV residual sets the size, and the short-convexity side is gated.

Nothing here is a constant of nature. Every threshold is a prior from the
research brief, to be re-estimated per pair in the backtest grid.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER

__all__ = ["SignalConfig", "signal_state", "build_signals"]

REQUIRED_COLUMNS = (
    "be_over_realized", "drift_t", "residual_z", "spread_vol_bp_day", "iv_z",
)


@dataclass(frozen=True)
class SignalConfig:
    be_cheap: float = 0.8
    be_rich: float = 1.2
    be_deep_cheap: float = 0.5  # below this, drift cannot veto
    drift_t_gate: float = 2.0
    z_entry: float = 1.5
    z_exit: float = 0.0
    z_size_cap: float = 3.0
    target_vol_bp_day: float = 1.65
    size_cap: float = 1.0
    short_side_enabled: bool = True
    iv_spike_gate_z: float = 2.0
    base_dv01_usd: float = 100_000.0


def signal_state(row: pd.Series, cfg: SignalConfig) -> dict:
    be = float(row["be_over_realized"])
    drift_t = float(row["drift_t"])
    z = float(row["residual_z"])
    sv = float(row["spread_vol_bp_day"])
    iv_z = float(row.get("iv_z", 0.0))

    if not np.isfinite(be):
        return {"sign": 0, "size": 0.0, "reason": "no valuation"}

    if be < cfg.be_cheap:
        sign, reason = FLATTENER, f"BE/RV={be:.2f} cheap"
    elif be > cfg.be_rich:
        sign, reason = STEEPENER, f"BE/RV={be:.2f} rich"
    else:
        return {"sign": 0, "size": 0.0, "reason": f"BE/RV={be:.2f} fair"}

    if sign == FLATTENER and drift_t > cfg.drift_t_gate and be > cfg.be_deep_cheap:
        return {"sign": 0, "size": 0.0,
                "reason": f"{reason}; vetoed by drift t={drift_t:+.1f}"}

    if sign == STEEPENER:
        if not cfg.short_side_enabled:
            return {"sign": 0, "size": 0.0, "reason": f"{reason}; short side disabled"}
        if iv_z > cfg.iv_spike_gate_z:
            return {"sign": 0, "size": 0.0,
                    "reason": f"{reason}; gated by vol spike z={iv_z:+.1f}"}

    if not np.isfinite(z) or abs(z) < cfg.z_entry:
        return {"sign": 0, "size": 0.0, "reason": f"{reason}; |z|={abs(z):.2f} < entry"}

    # size: risk parity on spread vol, scaled by how stretched the residual is
    vol_scale = cfg.target_vol_bp_day / sv if sv > 0 else 0.0
    z_scale = min(abs(z), cfg.z_size_cap) / cfg.z_size_cap
    size = float(min(cfg.size_cap, vol_scale * z_scale))
    return {"sign": sign, "size": size, "reason": f"{reason}; z={z:+.2f}"}


def build_signals(panel: pd.DataFrame, cfg: SignalConfig) -> pd.DataFrame:
    """Lag-1 signals. A row never acts on its own day's information."""
    missing = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing:
        raise KeyError(f"signal panel missing columns: {missing}")

    lagged = panel.shift(1)
    records = []
    for ts, row in lagged.iterrows():
        if row.isna().all():
            records.append({"sign": 0, "size": 0.0, "reason": "warmup", "dv01_usd": 0.0})
            continue
        st = signal_state(row, cfg)
        st["dv01_usd"] = st["sign"] * st["size"] * cfg.base_dv01_usd
        records.append(st)
    return pd.DataFrame(records, index=panel.index)
```

- [ ] **Step 4: Run the test to verify it passes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_strategy.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/strategy.py tests/test_strikeless_vol_strategy.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): two-sided conditional rule with drift veto and short-side gates"
```

---

### Task 18: Backtest engine, the config grid, and the league table

**Files:**
- Create: `RVUtils/StrikelessVol/backtest.py`
- Modify: `RVUtils/StrikelessVol/report.py` (add `league_table`, `ledger_attribution`)
- Test: `tests/test_strikeless_vol_backtest.py`

**Interfaces:**
- Consumes: `replication.simulate`, `replication.CurvePricer`, `strategy.build_signals`, `costs.CostSchedule`, `report.distribution_stats`.
- Produces:
  - `BacktestResult` frozen dataclass: `pair_name`, `config: dict`, `daily_pnl: pd.Series`, `ledger: pd.DataFrame`, `trades: pd.DataFrame`, `stats: dict`.
  - `run_pair(ctx, signals, *, rep_cfg, costs, pair_name) -> BacktestResult`.
  - `run_grid(ctx_by_pair, signal_panel_by_pair, grid: list[dict], *, costs) -> pd.DataFrame`.
  - `report.league_table(results: list[BacktestResult], *, cost_multipliers=(0,1,2)) -> pd.DataFrame` with columns `pair`, `config`, `n_trades`, `hit`, `gross_bp`, `net_1x_bp`, `net_2x_bp`, `t_stat`, `sharpe`, `dsr_prob`, `verdict`.
  - `report.ledger_attribution(results) -> pd.DataFrame` — carry / harvest / mtm / cost / cross totals plus, per pair, `harvest_flow_ratio` (gross daily absolute flows — a measure of the increment book's size, **not** a share of P&L) and `harvest_pnl_share` (the signed contribution share) (H10).

  **Amended after Task 13.** The original name `harvest_to_mtm` was renamed because it was computed from gross daily absolute flows and so measured book size rather than a P&L contribution share. Use the two names above; do not reintroduce `harvest_to_mtm`.

**Grid (the trial count that DSR must be deflated by):** `trigger_bp ∈ {10,15,20,25,30,40}` × `be_cheap ∈ {0.6,0.8,0.9}` × `be_rich ∈ {1.1,1.2,1.5}` × `z_entry ∈ {1.0,1.5,2.0}` × `drift_t_gate ∈ {1.5,2.0,∞}` × `short_side_enabled ∈ {True,False}`. That is 972 configs per pair before markets. `deflated_for_grid` must receive the **full** trial count across all pairs and families, not the per-pair count.

**Verdict:** reuse `RVUtils.SFRRVLab.stats.verdict(net_bp_at_taker, net_bp_at_maker, dsr_prob, median_net_bp, n_trades)` verbatim. The taxonomy is repo-wide and this study does not get its own.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_backtest.py
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.backtest import BacktestResult, run_grid, run_pair
from RVUtils.StrikelessVol.costs import FREE
from RVUtils.StrikelessVol.replication import ReplicationConfig
from RVUtils.StrikelessVol.report import league_table, ledger_attribution


BASE_DV01 = 100_000.0


class SyntheticCtx:
    """Same closed-form world as tests/test_strikeless_vol_replication.py."""

    def __init__(self, path_bp, theta_per_day=-500.0, gamma=40.0):
        self.dates = pd.bdate_range("2026-01-01", periods=len(path_bp))
        self.path = dict(zip(self.dates, np.asarray(path_bp, dtype=float)))
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.theta_per_day = theta_per_day
        self.k = gamma / 1e4

    def rate(self, date, leg):
        return (0.04 if leg == "long" else 0.045) + self.path[date] * 1e-4

    def dv01(self, date, leg):
        return 1.0 + self.k * self.path[date] if leg == "long" else 1.0

    def theta(self, date, nl, ns):
        return self.theta_per_day * (nl / BASE_DV01)

    def pv(self, date, nl, ns):
        dr = self.path[date]
        i = self.day_index[date]
        return (
            nl * (dr + 0.5 * self.k * dr * dr)
            - ns * dr
            + self.theta_per_day * i * (nl / BASE_DV01)
        )


def _signals(dates, sign=1, size=1.0):
    return pd.DataFrame(
        {"sign": sign, "size": size, "dv01_usd": sign * size * 100_000.0,
         "reason": "test"},
        index=dates,
    )


def test_run_pair_returns_a_complete_result():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=FREE, pair_name="TEST")
    assert isinstance(res, BacktestResult)
    assert len(res.daily_pnl) == len(ctx.dates)
    assert {"carry", "harvest", "mtm", "cost", "cross", "total"} <= set(res.ledger.columns)
    assert res.stats["n"] == len(ctx.dates)


def test_zero_signal_produces_zero_pnl_and_no_costs():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates, sign=0, size=0.0),
                   rep_cfg=ReplicationConfig(), costs=FREE, pair_name="TEST")
    assert res.daily_pnl.abs().sum() == pytest.approx(0.0, abs=1e-9)


def test_sign_flip_flips_the_pnl():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    long_ = run_pair(ctx, _signals(ctx.dates, sign=1), rep_cfg=ReplicationConfig(),
                     costs=FREE, pair_name="TEST")
    short = run_pair(ctx, _signals(ctx.dates, sign=-1), rep_cfg=ReplicationConfig(),
                     costs=FREE, pair_name="TEST")
    assert long_.daily_pnl.sum() == pytest.approx(-short.daily_pnl.sum(), rel=1e-9)


def test_run_grid_reports_one_row_per_config():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    grid = [{"trigger_bp": t} for t in (10.0, 25.0, 40.0)]
    out = run_grid({"TEST": ctx}, {"TEST": _signals(ctx.dates)}, grid, costs=FREE)
    assert len(out) == 3
    assert set(out["trigger_bp"]) == {10.0, 25.0, 40.0}


def test_league_table_reports_costs_at_multiple_multipliers():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=FREE, pair_name="TEST")
    tbl = league_table([res])
    assert {"net_1x_bp", "net_2x_bp", "dsr_prob", "verdict"} <= set(tbl.columns)


def test_ledger_attribution_exposes_the_harvest_flow_ratio():
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=FREE, pair_name="TEST")
    att = ledger_attribution([res])
    assert "harvest_flow_ratio" in att.columns
    assert "harvest_pnl_share" in att.columns
    assert att["harvest_flow_ratio"].iloc[0] >= 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_backtest.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write `backtest.py`**

```python
# RVUtils/StrikelessVol/backtest.py
"""Run the rule down real (or synthetic) paths and grid over its parameters.

Every number here is reported at three cost multipliers and deflated by the FULL
trial count across all pairs and families. The top row of a sweep is never the
verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.costs import CostSchedule
from RVUtils.StrikelessVol.replication import ReplicationConfig, reconcile, simulate
from RVUtils.StrikelessVol.report import distribution_stats

__all__ = ["BacktestResult", "run_pair", "run_grid"]


@dataclass(frozen=True)
class BacktestResult:
    pair_name: str
    config: dict
    daily_pnl: pd.Series
    ledger: pd.DataFrame = field(repr=False)
    trades: pd.DataFrame = field(repr=False)
    stats: dict = field(default_factory=dict)


def run_pair(ctx, signals: pd.DataFrame, *, rep_cfg: ReplicationConfig,
             costs: CostSchedule, pair_name: str) -> BacktestResult:
    """Simulate the replication and scale each day by that day's signal.

    The signal is already lag-1 (``strategy.build_signals``). Scaling the
    simulated unit-package P&L is exact for the linear ledgers and correct to
    first order for the harvest; positions are opened and closed at signal
    changes, and the cost of those changes is charged here rather than inside
    ``simulate``, which knows only about hedges and rolls.
    """
    dates = list(signals.index)
    unit = simulate(ctx, dates, rep_cfg, costs)
    scale = (signals["dv01_usd"] / rep_cfg.package_dv01_usd).reindex(unit.index).fillna(0.0)

    LEDGER_COLS = ["carry", "harvest", "mtm", "cross", "cost"]
    ledger = unit.copy()
    for col in LEDGER_COLS:
        ledger[col] = unit[col] * scale.abs() if col == "cost" else unit[col] * scale

    # entry/exit costs on signal changes
    turns = scale.diff().fillna(scale)
    ledger["cost"] = ledger["cost"] - turns.abs() * costs.cost_usd(
        "initiate", rep_cfg.package_dv01_usd
    )
    ledger["total"] = ledger[LEDGER_COLS].sum(axis=1)

    trades = _extract_trades(signals, ledger)
    stats = distribution_stats(ledger["total"])
    stats["reconciliation"] = reconcile(ledger)
    return BacktestResult(
        pair_name=pair_name,
        config={"trigger_bp": rep_cfg.trigger_bp, "sign": rep_cfg.sign,
                "cost_multiplier": costs.multiplier},
        daily_pnl=ledger["total"],
        ledger=ledger,
        trades=trades,
        stats=stats,
    )


def _extract_trades(signals: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    """One row per held episode, so per-trade statistics are well defined."""
    sign = signals["sign"].fillna(0).astype(int)
    blocks, start, cur = [], None, 0
    for ts, s in sign.items():
        if s != cur:
            if cur != 0 and start is not None:
                blocks.append((start, ts, cur))
            start, cur = (ts if s != 0 else None), s
    if cur != 0 and start is not None:
        blocks.append((start, sign.index[-1], cur))
    rows = []
    for entry, exit_, s in blocks:
        seg = ledger.loc[entry:exit_]
        # NOTE (amended after Task 13): these are DOLLARS, not bp. The ledger
        # buckets are dollar P&L, and the divisor a reader would assume ($100k
        # of DV01) is not the realised book size -- Task 13 measured a mean of
        # ~$98.8k with a daily range of $52.7k-$148.9k. Either rename these to
        # *_usd, or divide by the REALISED average DV01 per trade rather than
        # by the design notional. Do not leave dollars wearing a bp name, and
        # do not compare dollar P&L across roll frequencies or trigger widths
        # without normalising -- a regression beta of P&L on the spread is the
        # dspread^2-weighted DV01, not the book's size.
        rows.append({"entry": entry, "exit": exit_, "sign": s,
                     "gross_bp": float(seg[["carry", "harvest", "mtm", "cross"]].sum().sum()),
                     "cost_bp": float(-seg["cost"].sum()),
                     "net_bp": float(seg["total"].sum())})
    return pd.DataFrame(rows)


def run_grid(ctx_by_pair: Dict[str, object], signals_by_pair: Dict[str, pd.DataFrame],
             grid: Sequence[dict], *, costs: CostSchedule) -> pd.DataFrame:
    """One row per (pair, config). Nothing is dropped silently."""
    rows: List[dict] = []
    for pair_name, ctx in ctx_by_pair.items():
        signals = signals_by_pair[pair_name]
        for cfg in grid:
            rep = ReplicationConfig(**{k: v for k, v in cfg.items()
                                       if k in ReplicationConfig.__dataclass_fields__})
            res = run_pair(ctx, signals, rep_cfg=rep, costs=costs, pair_name=pair_name)
            row = {"pair": pair_name, **cfg, **{k: v for k, v in res.stats.items()
                                                if k != "reconciliation"}}
            row["total_net_bp"] = float(res.daily_pnl.sum())
            row["n_trades"] = int(len(res.trades))
            rows.append(row)
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Add `league_table` and `ledger_attribution` to `report.py`**

```python
def league_table(results, *, n_trials: int | None = None,
                 grid: pd.DataFrame | None = None) -> pd.DataFrame:
    """The honesty panel: costs at 0x/1x/2x, DSR on the full trial count, verdict."""
    from RVUtils.SFRRVLab.stats import deflated_for_grid, nw_tstat, verdict

    rows = []
    for res in results:
        trades = res.trades
        gross = float(trades["gross_bp"].sum()) if len(trades) else 0.0
        cost1 = float(trades["cost_bp"].sum()) if len(trades) else 0.0
        dsr = (deflated_for_grid(res.daily_pnl, grid) if grid is not None
               else {"dsr_prob": float("nan")})
        median_net = float(grid["total_net_bp"].median()) if grid is not None else 0.0
        net1, net2 = gross - cost1, gross - 2.0 * cost1
        rows.append({
            "pair": res.pair_name,
            "config": res.config,
            "n_trades": int(len(trades)),
            "hit": float((trades["net_bp"] > 0).mean()) if len(trades) else float("nan"),
            "gross_bp": gross,
            "net_1x_bp": net1,
            "net_2x_bp": net2,
            "t_stat": nw_tstat(res.daily_pnl.dropna(), lags=5),
            "sharpe": res.stats.get("sharpe_annualised"),
            "skew": res.stats.get("skew"),
            "dsr_prob": dsr.get("dsr_prob"),
            "verdict": verdict(
                net_bp_at_taker=net2, net_bp_at_maker=gross - 0.5 * cost1,
                dsr_prob=float(dsr.get("dsr_prob") or 0.0),
                median_net_bp=median_net, n_trades=int(len(trades)),
            ),
        })
    return pd.DataFrame(rows)


def ledger_attribution(results) -> pd.DataFrame:
    """H10: is the harvest near-uniformly positive while total P&L is MTM-driven?"""
    rows = []
    for res in results:
        led = res.ledger
        mtm = float(led["mtm"].abs().sum())
        rows.append({
            "pair": res.pair_name,
            "carry": float(led["carry"].sum()),
            "harvest": float(led["harvest"].sum()),
            "mtm": float(led["mtm"].sum()),
            "cost": float(led["cost"].sum()),
            "cross": float(led["cross"].sum()),
            "harvest_positive_share": float((led["harvest"] > 0).mean()),
            "harvest_flow_ratio": float(led["harvest"].abs().sum() / mtm) if mtm else float("nan"),
            "harvest_pnl_share": float(
                led["harvest"].sum()
                / sum(abs(led[c].sum()) for c in ("carry", "harvest", "mtm"))
            ),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 5: Run the tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_backtest.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/backtest.py RVUtils/StrikelessVol/report.py tests/test_strikeless_vol_backtest.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): backtest engine, config grid, league table and ledger attribution"
```

---

### Task 19: Placebos and confound checks

**Files:**
- Create: `scripts/sv_placebos.py`
- Test: `tests/test_strikeless_vol_placebos.py`

**Interfaces:**
- Consumes: Tasks 17–18, `universe.PLACEBO_PAIRS`.
- Produces: `run_placebos(...) -> pd.DataFrame` and `run_confounds(...) -> pd.DataFrame`.

**What must be run (the spec's requirement, and the repo's hard-won lesson that every post-hoc defect has flattered the hypothesis):**
1. **Short-dated placebo** — the identical rulebook on `PLACEBO_PAIRS` (1y5y/2y5y, 2y2y/3y2y), where the convexity story should not hold. A surviving signal there is a calendar/curve artifact.
2. **Shuffled-vol placebo** — block-bootstrap the vol series (preserving its autocorrelation) and re-run. The valuation switch must degrade.
3. **Sign-mirror** — every config run with the sign reversed. If both directions "work", the P&L is coming from something other than the stated mechanism.

   **Amended after Task 13 — this is arithmetically vacuous for a *static* book and must be scoped to the conditional rule.** `simulate` was measured exactly antisymmetric in `sign`: per-unit DV01 is sign-invariant, notionals flip, PV and theta are linear in notionals, the trigger reads a sign-independent constant-maturity rate, and cost is a magnitude fee. So `P&L_short = −P&L_long_gross + cost` identically, and both directions cannot "work" as a matter of arithmetic rather than of evidence. Run the sign-mirror **only on the Task 17 conditional rule**, where the signal's timing — not the engine — decides direction, and where both sides genuinely can win or lose together.
4. **Confound alternatives** for whatever config wins: duration-only (long the long leg outright, DV01-matched to the package), PC1-only (the slope's projection on the first principal component of the curve), and pure-carry (hold whichever sign has positive roll). If the winner does not beat all three, the vol story is not what is paying.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_placebos.py
import numpy as np
import pandas as pd
import pytest

from scripts.sv_placebos import block_bootstrap, mirror_configs


def test_block_bootstrap_preserves_length_and_roughly_the_vol():
    rng = np.random.default_rng(0)
    s = pd.Series(np.cumsum(rng.normal(0, 1, 1000)),
                  index=pd.bdate_range("2022-01-03", periods=1000))
    out = block_bootstrap(s, block=21, seed=1)
    assert len(out) == len(s)
    assert out.index.equals(s.index)
    assert out.diff().std() == pytest.approx(s.diff().std(), rel=0.25)


def test_block_bootstrap_is_seed_reproducible():
    s = pd.Series(np.arange(100.0), index=pd.bdate_range("2024-01-01", periods=100))
    assert block_bootstrap(s, block=10, seed=7).equals(
        block_bootstrap(s, block=10, seed=7)
    )


def test_block_bootstrap_actually_reorders():
    s = pd.Series(np.arange(200.0), index=pd.bdate_range("2024-01-01", periods=200))
    assert not block_bootstrap(s, block=10, seed=3).equals(s)


def test_mirror_configs_flips_every_sign():
    grid = [{"sign": 1, "trigger_bp": 25.0}, {"sign": -1, "trigger_bp": 25.0}]
    out = mirror_configs(grid)
    assert [c["sign"] for c in out] == [-1, 1]
    assert all(c["trigger_bp"] == 25.0 for c in out)
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_placebos.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the script**

```python
# scripts/sv_placebos.py
"""Placebos and confound checks.

Every defect found post-hoc in this repo's research so far has flattered the
hypothesis. So the placebos run BEFORE the winner is believed, not after it is
questioned.
"""
from __future__ import annotations

from typing import Iterable, List

import numpy as np
import pandas as pd


def block_bootstrap(series: pd.Series, *, block: int = 21, seed: int = 0) -> pd.Series:
    """Resample in blocks, preserving short-run autocorrelation.

    A plain shuffle destroys the persistence of a vol series and makes the
    placebo trivially easy to beat, which would be a comforting result rather
    than an informative one.
    """
    s = pd.Series(series).astype(float)
    rng = np.random.default_rng(seed)
    n = len(s)
    values = s.to_numpy()
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, max(n - block, 1), size=n_blocks)
    out = np.concatenate([values[st:st + block] for st in starts])[:n]
    return pd.Series(out, index=s.index, name=s.name)


def mirror_configs(grid: Iterable[dict]) -> List[dict]:
    """Every config with its sign reversed. Both sides must not 'work'."""
    return [{**c, "sign": -int(c.get("sign", 1))} for c in grid]
```

Then extend it with `run_placebos` and `run_confounds` that reuse `backtest.run_grid`: the short-dated placebo simply passes `PLACEBO_PAIRS`' contexts and signal panels through the same call; the shuffled-vol placebo rebuilds the signal panel with `block_bootstrap` applied to the vol column before `strategy.build_signals`; the confound alternatives are three extra "pairs" whose contexts are (a) the long leg alone at matched DV01, (b) the slope's PC1 projection from `RVUtils.pca_rv`, (c) a carry-sign rule with no vol input.

- [ ] **Step 4: Run the tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_placebos.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add scripts/sv_placebos.py tests/test_strikeless_vol_placebos.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): block-bootstrap placebos, sign mirror, confound alternatives"
```

---

### Task 20: Constructions — fly-hedged package and the same-sector pair (H9)

**Files:**
- Create: `RVUtils/StrikelessVol/constructions.py`
- Test: `tests/test_strikeless_vol_constructions.py`

**Interfaces:**
- Consumes: `greeks.build_package`, `RVUtils.rl_swap_risk_ladder_utils.solve_best_n_leg_hedge_pca`, `RVUtils.df_based_pca_risk_model`.
- Produces:
  - `Construction` enum-like constants: `TWO_LEG`, `FLY_HEDGED`, `SAME_SECTOR`.
  - `fly_hedge_weights(curve, package, *, pca_model, fly_tenors=("2Y","7Y","30Y"), fly_fwd="1Y") -> dict` — PCA-neutralising weights for a received 1y-forward 2-7-30 fly.
  - `carry_per_vega(greeks_row, beta) -> float` — `daily_roll_usd / (|beta| · spread_dv01)`.
  - `compare_constructions(curve, pair, *, pca_model, beta) -> pd.DataFrame` — one row per construction with `carry_per_vega`, `residual_pc1`, `residual_pc2`, `n_legs`, `cost_bp_round_trip`.

**What H9 claims:** the fly-hedged package neutralises residual level/slope exposure and flips theta positive, at the price of wing hedges; and 15y5y/20y10y (both legs in the same ultra-long sector, no fly needed) dominates 10y10y/20y10y after costs. The comparison metric is **carry per unit of vega after costs**, with uncompensated factor risk reported beside it — a construction that wins on carry while carrying PC1 is not winning.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_constructions.py
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.constructions import carry_per_vega


def test_carry_per_vega_uses_beta_times_spread_dv01():
    # roll -$500/day, |beta| 0.7, spread DV01 $100k -> -500 / 70,000
    assert carry_per_vega(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=100_000.0) == (
        pytest.approx(-500.0 / 70_000.0)
    )


def test_carry_per_vega_is_nan_when_beta_is_zero():
    assert np.isnan(carry_per_vega(daily_roll_usd=-500.0, beta=0.0, spread_dv01=1e5))


def test_positive_carry_construction_reports_positive_carry_per_vega():
    assert carry_per_vega(daily_roll_usd=+120.0, beta=-0.7, spread_dv01=1e5) > 0
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_constructions.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write `constructions.py`**

Start with `carry_per_vega` (below), then build `fly_hedge_weights` on top of the existing PCA hedge solver — do not write a new solver.

```python
# RVUtils/StrikelessVol/constructions.py
"""Three ways to express the same view, compared on carry per unit of vega.

* TWO_LEG      -- the plain DV01-neutral forward flattener.
* FLY_HEDGED   -- the flattener plus a received 1y-forward 2-7-30 fly at PCA
                  weights, which neutralises residual level/slope exposure and
                  can flip theta positive: long far-dated vega, short near
                  gamma, a calendar built from delta instruments. It needs
                  disciplined wing hedges, and the wings cost money.
* SAME_SECTOR  -- 15y5y/20y10y, both legs inside the ultra-long sector, so no
                  fly leg is needed and the market is tighter.

The metric is carry per unit of vega AFTER costs, reported next to the residual
factor exposure. A construction that wins on carry while still carrying PC1 has
not won; it has changed the question.
"""
from __future__ import annotations

import numpy as np

__all__ = ["TWO_LEG", "FLY_HEDGED", "SAME_SECTOR", "carry_per_vega"]

TWO_LEG = "two_leg"
FLY_HEDGED = "fly_hedged"
SAME_SECTOR = "same_sector"


def carry_per_vega(*, daily_roll_usd: float, beta: float, spread_dv01: float) -> float:
    """Dollars of daily carry per dollar of vega.

    vega$ ~ |beta| * spread DV01, where ``beta`` is the pair's ROLLING
    changes-regression beta on vol -- never a global constant, because every
    coefficient in this study is regime-local.
    """
    vega = abs(float(beta)) * abs(float(spread_dv01))
    if vega == 0.0:
        return float("nan")
    return float(daily_roll_usd) / vega
```

Then add `fly_hedge_weights` and `compare_constructions`, using
`RVUtils.rl_swap_risk_ladder_utils.solve_best_n_leg_hedge_pca` for the weights and
`RVUtils.df_based_pca_risk_model` for the PCA model. Report `residual_pc1`/`residual_pc2`
as the package's post-hedge exposure to the first two components.

- [ ] **Step 4: Run the tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_constructions.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/constructions.py tests/test_strikeless_vol_constructions.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): construction comparison on carry-per-vega with residual factor risk"
```

---

### Task 21: Cross-market book (H8)

**Files:**
- Create: `scripts/sv_cross_market.py`
- Modify: `RVUtils/StrikelessVol/report.py` (add `portfolio`)
- Test: `tests/test_strikeless_vol_portfolio.py`

**Interfaces:**
- Consumes: Task 18's results per market.
- Produces: `report.portfolio(results_by_market: dict[str, pd.Series], *, target_bp_day: float, caps: dict | None = None) -> pd.DataFrame` with columns `pnl`, plus one weight column per market.

**What H8 claims:** one rulebook, expected different signs — JPY entering flatteners at post-lifer-exit levels with a better carry profile, EUR drift-dominated with a datable Wtp calendar (avoid flatteners into tranche windows), USD near-fair valuation against hostile drift. The test is whether the combined book has a better distribution and drawdown than the best single market, not merely a higher Sharpe.

**Amended after Task 13 — do not compare on raw daily-P&L skew.** Task 13 measured that this instrument's raw skew is inherited from `skew(Δspread)` and carries no information about convexity: a DV01-matched **zero-convexity twin** cleared skew, Sharpe and vol-correlation with better numbers than the real package, and the short-convexity steepener passed the skew criterion too. Compare instead on **max drawdown**, the **carry sign**, and `harvest_pnl_share`. Sharpe is actively misleading here: both placebo pairs out-Sharpe every real pair while running the opposite carry sign.

**`resid_skew` and `mirror_split` — narrow domain, established by refutation.** The mirrored paired difference was *tested* on the placebos and **failed**: placebo-2's steepener printed a near-exact reflection rather than the same-signed misfit the cancellation argument requires, so differencing doubled the error (`−0.830`) instead of cancelling it. Decisively, the two placebo pairs have **identical Γ to within 0.2%** (20.31 vs 20.34 $/bp²) and receive **opposite** `resid_skew` signs — at a tenth the study pair's convexity the sign carries no information. Pairing cancels contamination *common* to both books; it does not touch position-odd noise. So `mirror_split` is a **confirmatory statistic in the high-Γ, high-R² regime only** (study pair: Γ ≈ 204, R² ≈ 0.956, split +5.13), and it is the **R² cut that does the work** of excluding the placebos, not the pairing. Never use it to rank, and never read it on a low-Γ configuration.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_portfolio.py
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.report import portfolio


def _series(mu, sd, n=500, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mu, sd, n), index=pd.bdate_range("2024-01-01", periods=n))


def test_portfolio_risk_weights_the_noisier_market_down():
    out = portfolio({"USD": _series(0, 1.0, seed=1), "JPY": _series(0, 4.0, seed=2)},
                    target_bp_day=1.0)
    assert out["w_USD"].iloc[-1] > out["w_JPY"].iloc[-1]


def test_portfolio_pnl_is_the_weighted_sum():
    a, b = _series(0, 1.0, seed=3), _series(0, 1.0, seed=4)
    out = portfolio({"A": a, "B": b}, target_bp_day=1.0)
    expected = out["w_A"] * a + out["w_B"] * b
    assert out["pnl"].dropna().sub(expected.dropna()).abs().max() < 1e-9


def test_caps_are_respected():
    out = portfolio({"USD": _series(0, 0.1, seed=5), "EUR": _series(0, 4.0, seed=6)},
                    target_bp_day=1.0, caps={"USD": 0.5})
    assert out["w_USD"].max() <= 0.5 + 1e-12


def test_diversification_reduces_volatility():
    a, b = _series(0, 1.0, seed=7), _series(0, 1.0, seed=8)
    out = portfolio({"A": a, "B": b}, target_bp_day=1.0)
    assert out["pnl"].std() < max(a.std(), b.std())
```

- [ ] **Step 2: Run the test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_portfolio.py -v
```
Expected: FAIL — `cannot import name 'portfolio'`.

- [ ] **Step 3: Implement `portfolio` in `report.py`**

```python
def portfolio(results_by_market: dict, *, target_bp_day: float,
              caps: dict | None = None, window: int = 63) -> pd.DataFrame:
    """Risk-parity book across markets, weights from trailing P&L vol.

    Weights are lagged one day: today's weight cannot know today's volatility.
    """
    caps = caps or {}
    frame = pd.DataFrame(results_by_market)
    vol = frame.rolling(int(window), min_periods=int(window)).std(ddof=1).shift(1)
    weights = (target_bp_day / vol).replace([np.inf, -np.inf], np.nan)
    for market, cap in caps.items():
        if market in weights:
            weights[market] = weights[market].clip(upper=float(cap))
    out = pd.DataFrame({f"w_{c}": weights[c] for c in frame.columns})
    out["pnl"] = (weights * frame).sum(axis=1, min_count=1)
    return out
```

- [ ] **Step 4: Run the tests**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_portfolio.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Write and run the cross-market script**

`scripts/sv_cross_market.py` builds, for each of USD/EUR/JPY/GBP: the forward panel, vol panel, breakeven panel (`greeks.greeks_panel`), the signal panel, and the backtest; then prints (a) today's signal state per market with its reason, (b) per-market distribution stats, (c) the combined book from `report.portfolio`, and (d) the comparison of combined skew and max drawdown against the best single market. EUR runs start 2019 and JPY/GBP from 2010 — print each market's actual sample so no table implies a common history it does not have.

- [ ] **Step 6: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add RVUtils/StrikelessVol/report.py scripts/sv_cross_market.py tests/test_strikeless_vol_portfolio.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): risk-parity cross-market book and the H8 comparison"
```

---

### Task 22: Daily signal runner

**Files:**
- Create: `BT/signals/strikeless_vol.py`
- Test: `tests/test_strikeless_vol_runner.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `today_state(asof: dt.date | None = None, *, markets=("USD","EUR","JPY","GBP"), cfg: SignalConfig | None = None) -> pd.DataFrame` with one row per pair and columns `pair`, `spread_bp`, `breakeven_h25`, `realized_vol_bp_day`, `implied_bp_day`, `be_over_realized`, `be_over_implied`, `drift_t`, `residual_z`, `sign`, `size`, `dv01_usd`, `reason`, `sample_start`.

Follow the shape of the other runners in `BT/signals/` (e.g. `ustf_basis.py`, `tfp_swap_spread.py`): a module of plain functions, cache-aware, no CLI framework, importable from a notebook.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strikeless_vol_runner.py
import datetime as dt

import pandas as pd
import pytest

from BT.signals.strikeless_vol import REQUIRED_OUTPUT_COLUMNS, today_state


def test_required_columns_are_declared():
    assert "sign" in REQUIRED_OUTPUT_COLUMNS
    assert "be_over_realized" in REQUIRED_OUTPUT_COLUMNS
    assert "reason" in REQUIRED_OUTPUT_COLUMNS
    assert "sample_start" in REQUIRED_OUTPUT_COLUMNS


@pytest.mark.network
@pytest.mark.slow
def test_today_state_returns_one_row_per_supported_pair():
    out = today_state(asof=dt.date(2026, 8, 3), markets=("USD",))
    assert not out.empty
    assert set(REQUIRED_OUTPUT_COLUMNS) <= set(out.columns)
    assert out["sign"].isin([-1, 0, 1]).all()
    # every row must be able to explain itself
    assert out["reason"].astype(str).str.len().min() > 0
    # and must not claim a sample it does not have
    assert (out["sample_start"] >= pd.Timestamp("2010-01-01")).all()
```

- [ ] **Step 2: Run the fast test to verify it fails**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_runner.py -v -m "not network"
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the runner**

```python
# BT/signals/strikeless_vol.py
"""Today's strikeless-vol state, one row per pair.

Composes the package: forward panel -> greeks/breakeven -> vol metrics ->
factor residual and drift -> the conditional rule. Every row carries the reason
the rule reached its sign, and the sample start of the data behind it.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional, Sequence

import pandas as pd

from RVUtils.StrikelessVol.factors import changes_regression, drift, levels_regression, residual_z
from RVUtils.StrikelessVol.greeks import greeks_panel
from RVUtils.StrikelessVol.panels import forward_rate_panel, spread_panel, umep_panel, vol_panel
from RVUtils.StrikelessVol.strategy import SignalConfig, signal_state
from RVUtils.StrikelessVol.universe import ALL_PAIRS, MARKET_CURVES, supported_pairs
from RVUtils.StrikelessVol.vol_metrics import (
    be_over_implied, be_over_realized, realized_vol_bp_day, spread_vol_bp_day,
)

REQUIRED_OUTPUT_COLUMNS = (
    "pair", "spread_bp", "breakeven_h25", "realized_vol_bp_day", "implied_bp_day",
    "be_over_realized", "be_over_implied", "drift_t", "residual_z",
    "sign", "size", "dv01_usd", "reason", "sample_start",
)

VOL_CURVE_BY_MARKET = {
    "USD": "USD-SOFR-1D", "EUR": "EUR-ESTR", "JPY": "JPY-TONAR", "GBP": "GBP-SONIA",
}


def today_state(
    asof: Optional[dt.date] = None,
    *,
    markets: Sequence[str] = ("USD", "EUR", "JPY", "GBP"),
    lookback_days: int = 750,
    cfg: Optional[SignalConfig] = None,
) -> pd.DataFrame:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    cfg = cfg or SignalConfig()
    asof = asof or dt.date.today()
    start = asof - dt.timedelta(days=int(lookback_days * 1.5))
    dates = pd.bdate_range(start, asof).date.tolist()
    mdp = IRSwapsMDP(source="GSQUANT-RL")

    rows = []
    for pair in supported_pairs([p for p in ALL_PAIRS if p.market in markets]):
        rates = forward_rate_panel(
            MARKET_CURVES[pair.market], dates, [pair.short, pair.long], mdp=mdp
        )
        if rates.empty:
            continue
        spread = spread_panel(rates, pair)

        curve_map = mdp.bulk_get_data(
            {"curve_name": MARKET_CURVES[pair.market], "timestamps": list(rates.index.date)}
        )
        gk = greeks_panel(curve_map, pair)
        vols = vol_panel(VOL_CURVE_BY_MARKET[pair.market], ["2y 10y"], start, asof)
        vol_ann = vols["2y10y"] * (252 ** 0.5)

        rv = realized_vol_bp_day(rates[pair.long.label], window=63)
        be = gk["breakeven_h25"]
        ratio_rv = be_over_realized(be, rv)
        ratio_iv = be_over_implied(be, vols["2y10y"])

        drivers = {"vol": vol_ann}
        if pair.market == "USD":
            umep = umep_panel(start, asof)
            if not umep.empty:
                drivers["umep"] = umep["umep_bp_per_year"]

        chg = changes_regression(spread, drivers)
        lev = levels_regression(spread, drivers)
        z = residual_z(lev.residuals)
        dr = drift(chg.residuals)

        row = {
            "pair": pair.name,
            "spread_bp": float(spread.iloc[-1]),
            "breakeven_h25": float(be.iloc[-1]),
            "realized_vol_bp_day": float(rv.iloc[-1]),
            "implied_bp_day": float(vols["2y10y"].iloc[-1]),
            "be_over_realized": float(ratio_rv.iloc[-1]),
            "be_over_implied": float(ratio_iv.iloc[-1]),
            "drift_t": float(dr["t_stat"].iloc[-1]),
            "residual_z": float(z.iloc[-1]),
            "spread_vol_bp_day": float(spread_vol_bp_day(spread, window=63).iloc[-1]),
            "iv_z": float(residual_z(vols["2y10y"]).iloc[-1]),
            "sample_start": spread.index.min(),
        }
        st = signal_state(pd.Series(row), cfg)
        row.update(st)
        row["dv01_usd"] = st["sign"] * st["size"] * cfg.base_dv01_usd
        rows.append(row)

    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run both test modes**

```
conda run -n stir python -m pytest tests/test_strikeless_vol_runner.py -v -m "not network"
conda run -n stir python -m pytest tests/test_strikeless_vol_runner.py -v -m network
```
Expected: the fast test passes; the network test passes and prints a plausible USD row. Sanity-check by eye: `spread_bp` deeply negative, `breakeven_h25` a few bp/day, `be_over_realized` somewhere near 0.4–1.5.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add BT/signals/strikeless_vol.py tests/test_strikeless_vol_runner.py
git -C C:\Users\chris\clee\ARBS-sv commit -m "feat(sv): daily signal runner reporting per-pair state and its reason"
```

---

### Task 23: Notebooks and the findings document

**Files:**
- Create: `notebooks/rv/strikeless_vol_research.ipynb`
- Create: `notebooks/backtests/strikeless_vol/strikeless_vol_backtest.ipynb`
- Create: `docs/superpowers/specs/2026-08-04-strikeless-vol-findings.md`

**The notebooks must compute their conclusions.** No hardcoded numbers in markdown cells that a later data change would silently invalidate — every figure quoted in prose is produced by a cell above it, in the same run.

- [ ] **Step 1: Build the research notebook**

Sections, in order: (1) data coverage per market, printed from the coverage sheet and the actual panels — including what is *excluded* (USD 25y10y) and why; (2) the 2026 reproduction table against the brief's targets; (3) the frequency ladder (H1); (4) swap-built vs Treasury-built UMEP coefficients (H2) with the stated verdict; (5) beta vs vol level (H3); (6) residual half-life, z-bands, positive-residual clustering (H4, H6); (7) breakeven versus realized and implied, per pair, through time.

- [ ] **Step 2: Build the backtest notebook**

Sections: (1) the static-long control, its distribution, **and the zero-convexity twin beside it** — the twin clears the published distributional anchors with better numbers than the real package, so the anchors must be shown as non-discriminating rather than as a pass; (2) ledger attribution, `harvest_flow_ratio` and `harvest_pnl_share` (H10); (3) the trigger plateau (H7); (4) the conditional two-sided book versus static long, compared on drawdown, carry sign and mirrored `resid_skew` — **not** on raw skew or Sharpe (H5); (5) constructions (H9); (6) the cross-market book (H8); (7) league table with DSR and verdicts, cost curve versus clip size, **including the roll-charge convention as its own row** (charging rolls as initiations moves 67.5% of the headline P&L); (8) placebos and confounds — noting that both placebos out-Sharpe every real pair on the opposite carry sign.

- [ ] **Step 3: Run the fast gate and the full package tests**

```
conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q
conda run -n stir python -m pytest tests/test_strikeless_vol_*.py -v -m "not network"
```
Expected: all pass, and the pre-existing suite is unaffected.

- [ ] **Step 4: Write the findings document**

`docs/superpowers/specs/2026-08-04-strikeless-vol-findings.md`, following the house style of `2026-08-03-linvol-backtest-grid-findings.md`. It must state, for each of H1–H10, the measured answer and whether it was confirmed, rejected, or left unresolved; the verdict per pair and per market from the shared taxonomy; what was excluded and why (USD 25y10y, pre-2017 vol, non-USD UMEP); and the honest bottom line, including a plain statement if nothing is ALIVE. A modest Sharpe with the right distribution and a working two-sided switch is the success criterion; a high Sharpe from an untested static long is not.

- [ ] **Step 5: Commit**

```bash
git -C C:\Users\chris\clee\ARBS-sv add notebooks/rv/strikeless_vol_research.ipynb notebooks/backtests/strikeless_vol/strikeless_vol_backtest.ipynb docs/superpowers/specs/2026-08-04-strikeless-vol-findings.md
git -C C:\Users\chris\clee\ARBS-sv commit -m "docs(sv): research and backtest notebooks, findings"
```

---

## Self-Review Notes

Checked against the spec:

- **Spec coverage.** Data facts → Tasks 3–6. Conventions → Task 1. Greeks contract (repricing, `h`-sensitivity, analytic control, mutation check) → Tasks 7–9. Four ledgers plus the cross plug → Task 12. Replication rule, trigger grid, aging, annual roll → Tasks 12–13, 18. Positive control → Task 13 (gate). Factor model, frequency ladder, levels-as-anchor → Task 14. Residual dynamics, drift, 2026 reproduction → Task 15. H2/H3 → Task 16. The rule → Task 17. Backtest, league, DSR, verdict taxonomy → Task 18. Placebos and confounds → Task 19. Constructions (H9) → Task 20. Cross-market (H8) → Task 21. Runner → Task 22. Notebooks and findings → Task 23.
- **Known gaps, deliberate.** `fly_hedge_weights` / `compare_constructions` (Task 20) and `run_placebos` / `run_confounds` (Task 19) are specified by interface and reuse an existing solver rather than shipped as full code — they compose already-tested pieces, and writing their internals blind would invent an API for `solve_best_n_leg_hedge_pca` rather than read it. The implementer reads that function first. Every other task carries complete code.
- **Hedge-instrument comparison** (`hedge_instrument="spot_atm"` versus `"long_leg"`) is carried in `ReplicationConfig` from Task 12 and exercised in the Task 18 grid; the spec flags it as an open implementation question, so it is a config axis rather than a decision.
- **Type consistency.** `ForwardLeg.label` is the panel column name everywhere; `PricingContext.rate/dv01/pv/theta` signatures are identical in `SyntheticCtx` (both test modules), `CurvePricer`, and the backtest tests; `CostSchedule.cost_usd(kind, dv01)` takes the same two arguments at every call site; `RegressionResult.residuals` feeds `residual_z` and `drift` unchanged; `LEDGER_COLS` is the same five buckets in `simulate`, `run_pair` and `ledger_attribution`.
- **One defect found and fixed during this review.** The first draft defined `mtm` as `total_pv_change − harvest − carry`, which forces `cross` to zero by construction and would have made the reconciliation test pass vacuously — the exact failure the spec says the plug exists to catch. `mtm` is now computed independently from the base notionals and `cross` is the genuine residual. The synthetic test context was also given a rate-dependent `dv01`, without which the resize rule never fires and no ledger test proves anything about gamma scalping.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-04-strikeless-vol.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
