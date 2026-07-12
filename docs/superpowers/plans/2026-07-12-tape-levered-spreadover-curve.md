# LEVERED tag + SPREADOVER_CURVE/FLY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `LEVERED` tape-tag for forward-levered swaps, and surface spreadover curves/flies as `SPREADOVER_CURVE`/`SPREADOVER_FLY` (new differential detection + remove the lossy frontend type-override).

**Architecture:** Enh 1 is one clause in the per-leg tag builder plus a frontend badge tone. Enh 2b makes the *package-PTS-vs-standalone-spreadover-level differential* the authoritative spreadover-curve signal: Phase-1 of the existing sub-package detector keeps only DISTINCT-per-leg-spread upgrades, a new `spreadover_curve.py` detector upgrades plain CURVE/FLY whose package PTS ties out to the level differential, the composite type renders in the label, and the frontend/server `inferBaseTypeOverride` downgrade is removed so the stored type is trusted.

**Tech Stack:** Python 3 / pandas (`conda run -n stir`); Next.js 15 / React 19 / TypeScript; Jest 30 (`npm test`).

## Global Constraints

- Python runs under `conda run -n stir`. Fast gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.
- Frontend tests run via `npm test` ONLY (never `npx jest` — it bypasses the ESM mocks). Typecheck: `npx tsc --noEmit`.
- Branch: `feat/tape-levered-spreadover-curve` (already cut off the PR #346 tip; `core/pts_scale.py` and frontend `utils/ptsScale.ts` already exist there).
- Detector-output changes MUST bump `DETECTION_CACHE_VERSION` (`SDRUtils/products/usd/usd_swaps.py`); enrichment/label changes MUST bump `TRADE_TAPE_CACHE_VERSION` (`SDRUtils/analytics/trade_tape.py`).
- Parse SDR numerics with `pd.to_numeric(errors="coerce")` / `numeric_like`, never bare int/float casts on raw columns.
- All new scale/bp work reuses `SDRUtils/core/pts_scale.py` (mirrors the frontend `utils/ptsScale.ts`); keep the two ports in sync.
- Worktree dashboard needs a real `npm install --legacy-peer-deps` (a node_modules junction breaks `next dev --turbopack`); the dev server reads the prod DB via the hardcoded `SWAPPULSE_DB_*` defaults.

---

## Task 1: Enh 1 — `LEVERED` tape-tag (Python)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py` (`_tags_for_row`, ~line 1654-1688; `TRADE_TAPE_CACHE_VERSION`, line 67)
- Test: `tests/test_tape_levered_tag.py` (create)

**Interfaces:**
- Produces: rows gain `"LEVERED"` in the comma-joined `tape_tags` string when `forward_start_years - tenor_years > 0.05`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tape_levered_tag.py
"""A LEVERED tape-tag marks forward-levered swaps (fwd-start > tenor)."""
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape


def _tags(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    out = tape._build_enriched_label(out)
    return out["tape_tags"].tolist()


def _leg(**over):
    row = {
        "trade_id": "T1", "execution_timestamp": pd.Timestamp("2026-07-06 14:30:00", tz="UTC"),
        "product_type": "OIS_SWAP", "upi_underlier_name": "USD-SOFR-COMPOUND 1D",
        "upi_reset_freq": "1D", "upi_notional_schedule": "Constant", "upi_delivery_type": "PHYS",
        "trade_type": "OUTRIGHT", "package_type": "OUTRIGHT", "forward_label": "10Y",
        "forward_start_years": 10.0, "tenor_label": "1Y", "tenor_display": "1Y", "tenor_years": 1.0,
        "package_tenors": "1Y", "cleared": "Y", "special_tenor_type": "STANDARD",
        "effective_date": pd.Timestamp("2036-07-08"), "expiration_date": pd.Timestamp("2037-07-08"),
        "is_unwind": False, "is_mac": False, "is_ufro": False, "is_block": False,
    }
    row.update(over)
    return row


def test_10y1y_outright_is_levered():
    assert "LEVERED" in _tags([_leg()])[0]


def test_5y5y_is_not_levered():
    tags = _tags([_leg(forward_label="5Y", forward_start_years=5.0,
                       tenor_label="5Y", tenor_years=5.0)])[0]
    assert "LEVERED" not in tags


def test_spot_10y_is_not_levered():
    tags = _tags([_leg(forward_label="spot", forward_start_years=0.0,
                       tenor_label="10Y", tenor_years=10.0)])[0]
    assert "LEVERED" not in tags


def test_missing_forward_does_not_error():
    tags = _tags([_leg(forward_start_years=None)])[0]
    assert "LEVERED" not in tags
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `conda run -n stir python -m pytest tests/test_tape_levered_tag.py -q`
Expected: FAIL (`test_10y1y_outright_is_levered` — LEVERED not in tags).

- [ ] **Step 3: Add the LEVERED clause to `_tags_for_row`**

In `SDRUtils/analytics/trade_tape.py`, inside `_tags_for_row`, immediately before `return ",".join(tags) if tags else ""`:

```python
            _fwd_y = row.get("forward_start_years")
            _ten_y = row.get("tenor_years")
            try:
                if (
                    pd.notna(_fwd_y) and pd.notna(_ten_y)
                    and float(_fwd_y) - float(_ten_y) > 0.05
                ):
                    tags.append("LEVERED")
            except (TypeError, ValueError):
                pass
```

- [ ] **Step 4: Bump the cache version**

`SDRUtils/analytics/trade_tape.py` line 67:
```python
TRADE_TAPE_CACHE_VERSION = "v18-levered-spreadover-curve"
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `conda run -n stir python -m pytest tests/test_tape_levered_tag.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py tests/test_tape_levered_tag.py
git commit -m "feat(tape): LEVERED tag for forward-levered swaps (fwd-start > tenor)"
```

---

## Task 2: Enh 1 — `LEVERED` badge (frontend)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts` (`TAPE_TAG_TONES`)
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/RowBadges.helpers.test.ts` (create if absent; else append)

**Interfaces:**
- Consumes: Task 1's `tape_tags` string.
- Produces: `tapeTagBadgesFor(row)` returns a `{ key: 'LEVERED', className, label: 'LEVERED' }` badge.

- [ ] **Step 1: Write the failing test**

```typescript
// __tests__/RowBadges.helpers.test.ts (append if the file exists)
import { tapeTagBadgesFor } from '../RowBadges.helpers'

describe('tapeTagBadgesFor — LEVERED', () => {
  it('renders a LEVERED badge from tape_tags', () => {
    const badges = tapeTagBadgesFor({ tape_tags: 'LEVERED', legs_json: [] } as any)
    const lev = badges.find((b) => b.key === 'LEVERED')
    expect(lev).toBeTruthy()
    expect(lev!.label).toBe('LEVERED')
    expect(lev!.className).not.toBe('bg-zinc-700/50 text-zinc-300') // not the default tone
  })
})
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns="RowBadges.helpers"`
Expected: FAIL — className equals the default tone (no `LEVERED` entry in `TAPE_TAG_TONES`).

- [ ] **Step 3: Add the tone**

In `constants.ts`, add a `LEVERED` entry to the existing `TAPE_TAG_TONES` object (match the surrounding entries' `'bg-… text-… ring-1 ring-…'` shape):

```typescript
  LEVERED: 'bg-indigo-900/40 text-indigo-200 ring-1 ring-indigo-400/40',
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns="RowBadges.helpers"`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

```bash
cd SDRUtils/dashboard && npx tsc --noEmit && cd ../..
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/RowBadges.helpers.test.ts
git commit -m "feat(tape-ui): LEVERED badge tone"
```

---

## Task 3: Enh 2b — `spread_to_bp` helper (core)

**Files:**
- Modify: `SDRUtils/core/pts_scale.py`
- Test: `tests/test_pts_scale.py` (create)

**Interfaces:**
- Produces: `spread_to_bp(value) -> float | None` — normalizes a single raw spreadover value to bp via a magnitude band (decimal ≤0.01 → ×10000; percent 0.10–1.0 → ×100). Returns None for the ambiguous middle `(0.01, 0.10)` and for `|value| > 1.0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pts_scale.py
from SDRUtils.core.pts_scale import spread_to_bp


def test_decimal_spreadover_to_bp():
    assert abs(spread_to_bp(-0.004239) - (-42.39)) < 0.01


def test_percent_spreadover_to_bp():
    assert abs(spread_to_bp(-0.422) - (-42.2)) < 0.01


def test_ambiguous_mid_returns_none():
    assert spread_to_bp(0.05) is None


def test_huge_returns_none():
    assert spread_to_bp(-50.0) is None


def test_zero_and_missing():
    assert spread_to_bp(0.0) == 0.0
    assert spread_to_bp(None) is None
    assert spread_to_bp(float("nan")) is None
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `conda run -n stir python -m pytest tests/test_pts_scale.py -q`
Expected: FAIL (`ImportError: cannot import name 'spread_to_bp'`).

- [ ] **Step 3: Implement `spread_to_bp`**

Append to `SDRUtils/core/pts_scale.py`:

```python
def spread_to_bp(value: object) -> Optional[float]:
    """Normalize a single reported spreadover value to basis points via a
    magnitude band (no counter-leg to tie against). Mirrors the accept-bands in
    ``detect_spreadovers``: decimal (|v|<=0.01 -> x10000) or percent
    (0.10<=|v|<=1.0 -> x100). The ambiguous middle (0.01, 0.10) and clearly
    erroneous magnitudes (>1.0) return None."""
    if not _finite(value):
        return None
    v = float(value)
    a = abs(v)
    if a == 0:
        return 0.0
    if a <= 0.01:
        return v * 10_000.0
    if 0.10 <= a <= 1.0:
        return v * 100.0
    return None
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `conda run -n stir python -m pytest tests/test_pts_scale.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/core/pts_scale.py tests/test_pts_scale.py
git commit -m "feat(core): spread_to_bp magnitude-band normalizer"
```

---

## Task 4: Enh 2b — spreadover-curve differential detector

**Files:**
- Create: `SDRUtils/packages/spreadover_curve.py`
- Test: `tests/test_spreadover_curve.py` (create)

**Interfaces:**
- Consumes: `spread_to_bp`, `find_scale_match` from `core/pts_scale.py`.
- Produces:
  - `build_spreadover_level_index(df, *, tol_y=0.1) -> dict[float, float]` — `{benchmark_tenor: latest_standalone_spreadover_bp}`.
  - `detect_spreadover_curves_df(df, *, tol_bp=5.0, level_index=None) -> pd.DataFrame` — upgrades plain `CURVE`/`FLY` package_ids to `SPREADOVER_CURVE`/`SPREADOVER_FLY` when the package PTS ties out to the level differential.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spreadover_curve.py
import pandas as pd
from SDRUtils.packages.spreadover_curve import (
    build_spreadover_level_index, detect_spreadover_curves_df,
)


def _so(tid, tenor, pts, ts="2026-07-10 20:00:00"):
    return dict(trade_id=tid, package_type="SPREADOVER", is_spreadover=True,
               tenor_years=tenor, package_transaction_spread=pts, forward_label="spot",
               execution_timestamp=pd.Timestamp(ts, tz="UTC"))


def _curve_leg(tid, pkg_id, tenor, pkg_pts, ptype="CURVE", ts="2026-07-10 21:00:32"):
    return dict(trade_id=tid, package_id=pkg_id, package_type=ptype,
                package_legs=[f"{pkg_id}_1", f"{pkg_id}_2"], tenor_years=tenor,
                package_transaction_spread=pkg_pts, forward_label="spot",
                execution_timestamp=pd.Timestamp(ts, tz="UTC"), is_spreadover=False)


def test_index_keeps_latest_per_tenor():
    df = pd.DataFrame([
        _so("A", 10.0, -0.004239, ts="2026-07-10 19:00:00"),
        _so("B", 30.0, -0.007475, ts="2026-07-10 19:30:00"),
        _so("C", 10.0, -0.004000, ts="2026-07-10 20:00:00"),  # newer 10Y
    ])
    idx = build_spreadover_level_index(df)
    assert abs(idx[10.0] - (-40.0)) < 0.01   # latest 10Y, -0.004 -> -40bp
    assert abs(idx[30.0] - (-74.75)) < 0.01


def test_curve_upgrades_when_differential_ties_out():
    # standalone 10Y=-42.39bp, 30Y=-74.75bp -> differential -32.36bp;
    # package PTS -0.00325 (decimal) ties -32.5bp at 10000x, within 5bp.
    df = pd.DataFrame([
        _so("SA", 10.0, -0.004239),
        _so("SB", 30.0, -0.007475),
        _curve_leg("C1", "P1", 10.0, -0.00325),
        _curve_leg("C2", "P1", 30.0, -0.00325),
    ])
    out = detect_spreadover_curves_df(df)
    got = out.loc[out["package_id"] == "P1", "package_type"].unique().tolist()
    assert got == ["SPREADOVER_CURVE"]


def test_curve_stays_plain_when_differential_off():
    df = pd.DataFrame([
        _so("SA", 10.0, -0.004239),
        _so("SB", 30.0, -0.007475),
        _curve_leg("C1", "P1", 10.0, -0.05),   # 500bp, nowhere near -32bp
        _curve_leg("C2", "P1", 30.0, -0.05),
    ])
    out = detect_spreadover_curves_df(df)
    assert (out.loc[out["package_id"] == "P1", "package_type"] == "CURVE").all()


def test_curve_stays_plain_when_level_missing():
    df = pd.DataFrame([
        _so("SA", 10.0, -0.004239),            # only 10Y level, no 30Y
        _curve_leg("C1", "P1", 10.0, -0.00325),
        _curve_leg("C2", "P1", 30.0, -0.00325),
    ])
    out = detect_spreadover_curves_df(df)
    assert (out.loc[out["package_id"] == "P1", "package_type"] == "CURVE").all()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `conda run -n stir python -m pytest tests/test_spreadover_curve.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the detector**

```python
# SDRUtils/packages/spreadover_curve.py
"""Differential-based SPREADOVER_CURVE / SPREADOVER_FLY detection.

A curve/fly of spreadovers has a package PTS that equals the DIFFERENTIAL of its
legs' standalone swap-vs-UST spread levels (CURVE: back-front; FLY: 2*belly-wings).
We index the most-recent standalone SPREADOVER print per benchmark tenor from the
same frame and upgrade a plain CURVE/FLY whose package PTS ties out to that
differential within a bp tolerance. Complements detect_sub_package_curve_fly,
which handles legs that each carry their own distinct broker spread.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.core.pts_scale import find_scale_match, spread_to_bp

_BENCHMARKS = (2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0)


def _nearest_benchmark(tenor: object, tol_y: float = 0.1):
    try:
        t = float(tenor)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(t):
        return None
    best = min(_BENCHMARKS, key=lambda b: abs(b - t))
    return best if abs(best - t) <= tol_y else None


def build_spreadover_level_index(df: pd.DataFrame, *, tol_y: float = 0.1) -> dict:
    """{benchmark_tenor -> latest standalone spreadover level in bp}."""
    if df.empty:
        return {}
    base = df.get("package_type", pd.Series(index=df.index, dtype=object)).astype(str).str.upper()
    is_so = base.eq("SPREADOVER")
    if "is_spreadover" in df.columns:
        is_so = is_so | df["is_spreadover"].fillna(False).astype(bool)
    so = df.loc[is_so].copy()
    if so.empty:
        return {}
    so["_ts"] = pd.to_datetime(so.get("execution_timestamp"), errors="coerce", utc=True)
    so = so.sort_values("_ts", kind="mergesort")  # ascending -> latest overwrites
    index: dict = {}
    for _, r in so.iterrows():
        bench = _nearest_benchmark(r.get("tenor_years"), tol_y)
        if bench is None:
            continue
        lvl = spread_to_bp(pd.to_numeric(r.get("package_transaction_spread"), errors="coerce"))
        if lvl is None:
            continue
        index[bench] = lvl
    return index


def _differential_bp(levels_bp: list, structure: str):
    if structure == "CURVE" and len(levels_bp) == 2:
        return levels_bp[1] - levels_bp[0]
    if structure == "FLY" and len(levels_bp) == 3:
        return 2.0 * levels_bp[1] - levels_bp[0] - levels_bp[2]
    return None


def detect_spreadover_curves_df(
    df: pd.DataFrame, *, tol_bp: float = 5.0, level_index: dict | None = None,
) -> pd.DataFrame:
    if df.empty or "package_type" not in df.columns or "package_id" not in df.columns:
        return df
    out = df.copy()
    if level_index is None:
        level_index = build_spreadover_level_index(out)
    if not level_index:
        return out

    base = out["package_type"].astype(str).str.upper()
    cand = base.isin({"CURVE", "FLY"}) & out["package_id"].notna()
    if not cand.any():
        return out

    for pkg_id, gidx in out.loc[cand].groupby("package_id").groups.items():
        gidx = list(gidx)
        g = out.loc[gidx]
        structure = str(g["package_type"].iloc[0]).upper()
        n = len(gidx)
        if (structure == "CURVE" and n != 2) or (structure == "FLY" and n != 3):
            continue
        if "forward_label" in g.columns and not (
            g["forward_label"].astype(str).str.lower() == "spot"
        ).all():
            continue
        g = g.assign(_t=pd.to_numeric(g["tenor_years"], errors="coerce")).sort_values("_t")
        if g["_t"].isna().any():
            continue
        levels = [level_index.get(_nearest_benchmark(t)) for t in g["_t"]]
        if any(l is None for l in levels):
            continue
        diff = _differential_bp(list(levels), structure)
        if diff is None:
            continue
        pkg_pts = pd.to_numeric(g["package_transaction_spread"], errors="coerce").dropna()
        if pkg_pts.empty:
            continue
        m = find_scale_match(abs(diff), abs(float(pkg_pts.iloc[0])), tol_bp)
        if m is None:
            continue
        pkg_bp = abs(float(pkg_pts.iloc[0])) * m["factor"]
        if abs(pkg_bp - abs(diff)) > tol_bp:
            continue
        new_type = "SPREADOVER_CURVE" if structure == "CURVE" else "SPREADOVER_FLY"
        out.loc[gidx, "package_type"] = new_type
        if "trade_type" in out.columns:
            out.loc[gidx, "trade_type"] = new_type
    return out
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `conda run -n stir python -m pytest tests/test_spreadover_curve.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/packages/spreadover_curve.py tests/test_spreadover_curve.py
git commit -m "feat(detect): differential-based SPREADOVER_CURVE/FLY detector"
```

---

## Task 5: Enh 2b — wire detector + tighten Phase-1; reconcile

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py` (`detect_sub_package_curve_fly` Phase-1, ~806-817; `_run_all_detectors`, ~1958-1965; `DETECTION_CACHE_VERSION`, line 195)
- Test: `tests/test_sub_package_detection.py` (reconcile), plus a new wiring assertion in `tests/test_spreadover_curve.py`

**Interfaces:**
- Consumes: `detect_spreadover_curves_df` (Task 4).
- Produces: `_run_all_detectors` emits `SPREADOVER_CURVE/FLY` for differential-confirmed plain curves/flies; Phase-1 only upgrades DISTINCT-per-leg-spread curves/flies.

- [ ] **Step 1: Tighten Phase-1 to distinct-spread only**

In `detect_sub_package_curve_fly`, replace the `all_spreadover` upgrade decision (currently lines ~806-813):

```python
            all_mms = bool(leg_mms.loc[idx].all())
            all_spreadover = bool(leg_spreadover.loc[idx].all())

            # Uniform per-leg spread = a broadcast package spread, not distinct
            # individual spreadover levels. Only DISTINCT per-leg spreads are an
            # unambiguous spreadover structure here; the uniform / no-spread case
            # is confirmed separately by detect_spreadover_curves_df (differential
            # vs standalone spreadover levels).
            _leg_spreads = pd.to_numeric(
                out.loc[idx, "package_transaction_spread"], errors="coerce"
            ).round(10)
            _distinct_spreads = _leg_spreads.nunique(dropna=True) >= 2

            if all_spreadover and _distinct_spreads:
                new_type = f"SPREADOVER_{base_type}"
            elif all_mms:
                new_type = f"MATCHED_MATURITY_{base_type}"
            else:
                continue
```

- [ ] **Step 2: Wire the new detector into `_run_all_detectors`**

In `_run_all_detectors`, immediately after the non-PTP `detect_sub_package_curve_fly` call (line ~1958-1961), add:

```python
                    from SDRUtils.packages.spreadover_curve import (
                        detect_spreadover_curves_df,
                    )
                    df = detect_spreadover_curves_df(df)
```

And in the PTP branch, after its `detect_sub_package_curve_fly` (line ~1931-1933), add the same two lines operating on `ptp_df`:

```python
                        from SDRUtils.packages.spreadover_curve import (
                            detect_spreadover_curves_df,
                        )
                        ptp_df = detect_spreadover_curves_df(ptp_df)
```

- [ ] **Step 3: Bump the detection cache version**

`SDRUtils/products/usd/usd_swaps.py` line 195:
```python
DETECTION_CACHE_VERSION = "ptp11-spreadover-curve-diff"
```

- [ ] **Step 4: Add a wiring assertion**

Append to `tests/test_spreadover_curve.py`:

```python
def test_distinct_leg_spreads_still_upgrade_in_phase1_path():
    # This case (distinct per-leg spreads) is handled by Phase-1, NOT the
    # differential detector — assert the differential detector leaves it alone
    # so the two paths don't double-fire.
    df = pd.DataFrame([
        _curve_leg("C1", "P1", 10.0, -0.004239),
        _curve_leg("C2", "P1", 30.0, -0.007475),
    ])
    # no standalone levels -> differential detector no-ops
    out = detect_spreadover_curves_df(df)
    assert (out.loc[out["package_id"] == "P1", "package_type"] == "CURVE").all()
```

- [ ] **Step 5: Run the affected Python suites; reconcile sub-package tests**

Run: `conda run -n stir python -m pytest tests/test_spreadover_curve.py tests/test_sub_package_detection.py tests/test_ptp_pipeline_integration.py -q`

If any `test_sub_package_detection.py` case fails because its fixture used a UNIFORM per-leg spread and expected `SPREADOVER_CURVE/FLY`: that case now belongs to the differential path. Fix it by giving the legs DISTINCT per-leg spreads (the genuine Phase-1 case), e.g. change a shared `package_transaction_spread=-0.004437` on both legs to `-0.004239` / `-0.007475`. Do NOT weaken the assertion. Re-run until green.

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py tests/test_spreadover_curve.py tests/test_sub_package_detection.py
git commit -m "feat(detect): wire spreadover-curve differential; Phase-1 distinct-spread only"
```

---

## Task 6: Enh 2b — composite label rendering

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py` (`_build_enriched_label` structure step, ~1552-1557)
- Test: `tests/test_tape_spreadover_curve_label.py` (create)

**Interfaces:**
- Consumes: a package row with `package_type` / `trade_type` = `SPREADOVER_CURVE` / `SPREADOVER_FLY`.
- Produces: the package-scope `tape_label` structure token reads `SPREADOVER_CURVE` / `SPREADOVER_FLY` (leg-scope stays `Outright`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tape_spreadover_curve_label.py
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape


def _labels(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    return tape._build_enriched_label(out)


def _leg(tid, tenor, ty):
    return {
        "trade_id": tid, "execution_timestamp": pd.Timestamp("2026-07-10 21:00:32", tz="UTC"),
        "product_type": "OIS_SWAP", "upi_underlier_name": "USD-SOFR-OIS Compound",
        "upi_reset_freq": "1D", "upi_notional_schedule": "Constant", "upi_delivery_type": "PHYS",
        "trade_type": "SPREADOVER_CURVE", "package_type": "SPREADOVER_CURVE",
        "package_legs": ["S1", "S2"], "forward_label": "spot", "forward_start_years": 0.0,
        "tenor_label": tenor, "tenor_display": tenor, "tenor_years": ty,
        "package_tenors": "10Y/30Y", "cleared": "Y", "special_tenor_type": "STANDARD",
        "effective_date": pd.Timestamp("2026-07-14"),
        "expiration_date": pd.Timestamp(f"20{36 if ty==10 else 56}-07-14"),
        "is_unwind": False, "is_mac": False,
    }


def test_spreadover_curve_label():
    out = _labels([_leg("S1", "10Y", 10.0), _leg("S2", "30Y", 30.0)])
    lbl = out.loc[0, "tape_label"]
    assert "SPREADOVER_CURVE" in lbl
    assert "10Y/30Y SPREADOVER_CURVE" in lbl
    # leg scope stays Outright
    assert "Outright" in out.loc[0, "leg_tape_label"]
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `conda run -n stir python -m pytest tests/test_tape_spreadover_curve_label.py -q`
Expected: FAIL — label contains `CURVE`, not `SPREADOVER_CURVE`.

- [ ] **Step 3: Render the composite structure token**

In `_build_enriched_label`, step 5 (structure), replace the curvey/flyey arms (currently `parts.append("CURVE")` / `parts.append("FLY")`) so a composite type renders its full name while a bare type is unchanged. `trade_type` is already the composite (e.g. `"SPREADOVER_CURVE"`) because `assign_trade_type` passes `_CURVE`/`_FLY` suffixes through:

```python
            elif _is_curvey(trade_type):
                _tt = trade_type.upper()
                parts.append(_tt if _tt.endswith("_CURVE") else "CURVE")
            elif _is_flyey(trade_type):
                _tt = trade_type.upper()
                parts.append(_tt if _tt.endswith("_FLY") else "FLY")
```

This yields `SPREADOVER_CURVE` / `MATCHED_MATURITY_CURVE` for composites and `CURVE` / `FLY` for base types.

- [ ] **Step 4: Run tests to confirm they pass**

Run: `conda run -n stir python -m pytest tests/test_tape_spreadover_curve_label.py tests/test_tape_bug_batch_0706.py tests/test_trade_tape_mms_package_label.py -q`
Expected: PASS. (If a `test_tape_bug_batch_0706` gap-fly/curve case asserted a bare `CURVE`/`FLY` on a `MATCHED_MATURITY_*` type, update it to the composite name — that is now the intended label.)

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py tests/test_tape_spreadover_curve_label.py
git commit -m "feat(tape): render SPREADOVER_CURVE/FLY (and MATCHED_MATURITY_*) in the label"
```

---

## Task 7: Enh 2b — remove the frontend type-override

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts` (`inferBaseTypeOverride` 377-425; usage 667-687)
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts` (update)

**Interfaces:**
- Produces: `computePackageConfidence(row).inferredType` is always `null`; the displayed badge (`inferredType ?? package_type` in `columns.tsx` / `LegsSubTable.tsx` / `MobileTradeCards.tsx` / `useFocusedTrade.ts`) always equals the stored `package_type`.

- [ ] **Step 1: Update the failing test**

In `packageConfidence.test.ts`, find the block(s) asserting the override (search `inferredType`, `inferred_base_type`, "Inferred type") and rewrite the SPREADOVER_CURVE-with-uniform-per-leg case to expect NO downgrade:

```typescript
  it('does NOT downgrade SPREADOVER_CURVE to CURVE (override removed)', () => {
    const row = {
      package_type: 'SPREADOVER_CURVE', package_indicator: true, n_package_legs: 2,
      package_transaction_spread: -0.00325,
      legs_json: [
        { tenor_years: 10, risk: 40000, fixed_rate: 0.04139, package_transaction_spread: -0.00325 },
        { tenor_years: 30, risk: 40000, fixed_rate: 0.04313, package_transaction_spread: -0.00325 },
      ],
    } as any
    const conf = computePackageConfidence(row)
    expect(conf.inferredType).toBeNull()
    expect(conf.signals.find((s) => s.name === 'inferred_base_type')).toBeUndefined()
  })
```

Delete or update any prior test that asserted `inferredType === 'CURVE'` / `'FLY'`.

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns="packageConfidence"`
Expected: FAIL — `inferredType` is currently `'CURVE'`.

- [ ] **Step 3: Remove the override**

In `packageConfidence.ts`: delete the `inferBaseTypeOverride` function (377-425), and replace the usage (667-687) with:

```typescript
  return {
    score,
    total,
    tone,
    signals,
    resolvedType,
    inferredType: null,
    inferredTypeReason: null,
  }
```

Remove any now-unused imports flagged by the typecheck.

- [ ] **Step 4: Run tests + typecheck to confirm they pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns="packageConfidence|columns|LegsSubTable" && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts
git commit -m "feat(tape-ui): trust stored package_type; drop SPREADOVER_* downgrade"
```

---

## Task 8: Enh 2b — remove the server-side type-override (port)

**Files:**
- Modify: `SDRUtils/analytics/package_confidence.py` (`_infer_base_type_override` 576-632; usage 727-746)
- Test: `tests/test_package_confidence.py` (update if it asserts the override; else add)

**Interfaces:**
- Produces: `compute_package_confidence(...)["inferred_type"]` is always `None` — mirrors Task 7 so the server port and the browser stay in sync.

- [ ] **Step 1: Add/adjust the failing test**

```python
# tests/test_package_confidence.py (add)
from SDRUtils.analytics.package_confidence import compute_package_confidence


def test_spreadover_curve_not_downgraded():
    conf = compute_package_confidence(
        package_type="SPREADOVER_CURVE", package_indicator=True, n_package_legs=2,
        package_transaction_spread=-0.00325, has_spread=True,
        legs=[
            {"tenor_years": 10, "risk": 40000, "fixed_rate": 0.04139,
             "package_transaction_spread": -0.00325},
            {"tenor_years": 30, "risk": 40000, "fixed_rate": 0.04313,
             "package_transaction_spread": -0.00325},
        ],
    )
    assert conf["inferred_type"] is None
    assert not any(s["name"] == "inferred_base_type" for s in conf["signals"])
```

(If `tests/test_package_confidence.py` already asserts `inferred_type == "CURVE"`, delete/rewrite that assertion.)

- [ ] **Step 2: Run it and confirm it fails**

Run: `conda run -n stir python -m pytest tests/test_package_confidence.py::test_spreadover_curve_not_downgraded -q`
Expected: FAIL — `inferred_type` is `"CURVE"`.

- [ ] **Step 3: Remove the override**

In `package_confidence.py`: delete `_infer_base_type_override` (576-632). Replace the usage (727-746) with:

```python
    return {
        "score": score,
        "total": total,
        "tone": tone,
        "signals": signals,
        "resolved_type": resolved_type,
        "inferred_type": None,
        "inferred_type_reason": None,
    }
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `conda run -n stir python -m pytest tests/test_package_confidence.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/analytics/package_confidence.py tests/test_package_confidence.py
git commit -m "feat(detect): drop server-side SPREADOVER_* type-override (port of UI change)"
```

---

## Final verification (after all tasks)

- [ ] Python fast gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q` → all pass.
- [ ] Frontend: `cd SDRUtils/dashboard && npm test` → all pass; `npx tsc --noEmit` → clean.
- [ ] Chrome MCP against the dev server (`PORT=3055 npm run dev`, reads prod DB): once data is re-enriched, confirm the `LEVERED` badge on a 10y1y and `SPREADOVER_CURVE` on the Spot 10Y/30Y. NOTE: classification/label changes only surface after re-enrichment — do NOT run the destructive prod backfill.
- [ ] Push branch; open PR referencing the spec and PR #346.

---

## Spec-coverage self-check

| Spec item | Task |
|---|---|
| LEVERED rule (fwd-start > tenor + margin) in `_tags_for_row` | 1 |
| LEVERED badge in frontend tag catalog | 2 |
| Level index from tape's own standalone SPREADOVER prints (bp-normalized) | 3 (`spread_to_bp`), 4 (`build_spreadover_level_index`) |
| Differential match `|pkg_PTS − differential| ≤ 5bp` → SPREADOVER_CURVE/FLY | 4, 5 |
| Placement after `detect_sub_package_curve_fly` (PTP + non-PTP) | 5 |
| Phase-1 precision (distinct per-leg spreads only) | 5 |
| Composite type in the tape label | 6 |
| Remove frontend `inferBaseTypeOverride` | 7 |
| Mirror removal in server `package_confidence.py` | 8 |
| Cache-version bumps (detection + trade-tape) | 1, 5 |
| Known limitation: no levels for IMM/non-benchmark tenors (fly stays plain) | documented in spec; covered by `test_curve_stays_plain_when_level_missing` (Task 4) |
