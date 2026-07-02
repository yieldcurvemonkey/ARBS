# PTP-Based Package Detection & OPA Sign Solver — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group SDR legs sharing the same PTP/exec-time into super-packages, solve for OPA pay/receive direction, and surface the tieout + dealer spread on the dashboard.

**Architecture:** Hybrid pipeline — PTP pre-grouper pulls `package_indicator=True` legs into scoped groups before existing detectors run on the remainder. OPA sign solver runs post-merge on all PTP groups. New columns flow through tape enrichment → DB → dashboard.

**Tech Stack:** Python 3.11+ / pandas / numpy (backend), TypeScript / React / TanStack Table (frontend), PostgreSQL (Supabase)

## Global Constraints

- All tests run under `conda run -n stir pytest ...`
- Snake-case column names at detection time (conversion happens at line 1643 in `usd_swaps.py`)
- Existing fly/curve/basis tests MUST NOT regress
- Package columns: `package_type`, `package_id`, `package_legs` are the interface contract with `_enrich_packages()` in `trade_tape.py`
- DB upsert is conflict-on-PK (`package_id` for packages, `trade_id` for legs)
- Dashboard reads from `arbs_usd_swap_tape_display_v2` view via `TAPE_DISPLAY_VIEW` constant

---

### Task 1: PTP Pre-Grouper

**Files:**
- Create: `SDRUtils/packages/ptp_grouper.py`
- Test: `tests/test_ptp_grouper.py`

**Interfaces:**
- Consumes: Classified DataFrame with columns `execution_timestamp`, `package_transaction_price`, `package_indicator`, `unique_product_identifier`, `platform_identifier`, `trade_id`
- Produces: `group_by_ptp(df, *, time_tolerance_seconds=5) → tuple[pd.DataFrame, pd.DataFrame]` — (ptp_groups with `ptp_group_id`/`ptp_group_size` columns, non_ptp remainder)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ptp_grouper.py
"""Tests for PTP-based package pre-grouper."""
import pandas as pd
import pytest

from SDRUtils.packages.ptp_grouper import group_by_ptp


def _make_legs(overrides_list: list[dict]) -> pd.DataFrame:
    """Build a test DataFrame from per-leg overrides."""
    base = {
        "trade_id": "T000",
        "execution_timestamp": pd.Timestamp("2026-06-25 14:30:59", tz="UTC"),
        "package_transaction_price": 88100.0,
        "package_indicator": True,
        "unique_product_identifier": "UPI_SOFR_OIS",
        "platform_identifier": "BBSF",
        "estimated_pv01": 10000.0,
        "tenor_years": 5.0,
        "fixed_rate": 0.04,
        "other_payment_amount": 1000.0,
        "product_type": "OIS_SWAP",
        "package_type": "OUTRIGHT",
    }
    rows = []
    for i, ov in enumerate(overrides_list):
        row = {**base, "trade_id": f"T{i:03d}", **ov}
        rows.append(row)
    return pd.DataFrame(rows)


class TestGroupByPtp:
    def test_exact_match_groups_two_legs(self):
        df = _make_legs([
            {"tenor_years": 2.0},
            {"tenor_years": 10.0},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 2
        assert len(non_ptp_df) == 0
        assert ptp_df["ptp_group_id"].nunique() == 1
        assert ptp_df["ptp_group_size"].iloc[0] == 2

    def test_different_ptp_splits_groups(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_transaction_price": 88100.0},
            {"tenor_years": 10.0, "package_transaction_price": 88100.0},
            {"tenor_years": 5.0, "package_transaction_price": 50000.0},
            {"tenor_years": 7.0, "package_transaction_price": 50000.0},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 4
        assert ptp_df["ptp_group_id"].nunique() == 2

    def test_single_leg_stays_in_global_pool(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_transaction_price": 88100.0},
            {"tenor_years": 10.0, "package_transaction_price": 99999.0},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 2

    def test_null_ptp_stays_in_global_pool(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_transaction_price": None},
            {"tenor_years": 10.0, "package_transaction_price": None},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 2

    def test_pkg_indicator_false_stays_in_global_pool(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_indicator": False},
            {"tenor_years": 10.0, "package_indicator": False},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 2

    def test_time_window_merge(self):
        """Legs 3s apart should group; legs 10s apart should not."""
        t0 = pd.Timestamp("2026-06-25 14:30:59", tz="UTC")
        df = _make_legs([
            {"execution_timestamp": t0},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=3)},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=30)},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=32)},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)
        assert ptp_df["ptp_group_id"].nunique() == 2
        assert len(ptp_df) == 4

    def test_different_upi_splits_groups(self):
        df = _make_legs([
            {"tenor_years": 2.0, "unique_product_identifier": "UPI_A"},
            {"tenor_years": 10.0, "unique_product_identifier": "UPI_B"},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0  # each UPI has only 1 leg → min group 2

    def test_different_platform_splits_groups(self):
        df = _make_legs([
            {"tenor_years": 2.0, "platform_identifier": "BBSF"},
            {"tenor_years": 10.0, "platform_identifier": "TPSF"},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0

    def test_group_id_uses_min_trade_id(self):
        df = _make_legs([
            {"trade_id": "Z999", "tenor_years": 2.0},
            {"trade_id": "A001", "tenor_years": 10.0},
        ])
        ptp_df, _ = group_by_ptp(df)
        assert ptp_df["ptp_group_id"].iloc[0] == "PTP_A001"

    def test_empty_dataframe(self):
        df = _make_legs([])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 0

    def test_twelve_leg_fly_groups_together(self):
        """Real-world: 12 legs, same PTP, same exec_ts → one group."""
        df = _make_legs([{"tenor_years": t, "trade_id": f"T{i:03d}"}
                         for i, t in enumerate([2, 5, 10] * 4)])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 12
        assert ptp_df["ptp_group_id"].nunique() == 1
        assert ptp_df["ptp_group_size"].iloc[0] == 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir pytest tests/test_ptp_grouper.py -v`
Expected: `ModuleNotFoundError: No module named 'SDRUtils.packages.ptp_grouper'`

- [ ] **Step 3: Implement `group_by_ptp`**

```python
# SDRUtils/packages/ptp_grouper.py
"""PTP-based package pre-grouper and structure classifier.

Groups SDR legs sharing the same (exec_ts, PTP, UPI, platform,
package_indicator=True) into PTP super-packages before DV01-based
detectors run. Prevents split-package and mis-classification errors.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def group_by_ptp(
    df: pd.DataFrame,
    *,
    time_tolerance_seconds: int = 5,
    exec_col: str = "execution_timestamp",
    ptp_col: str = "package_transaction_price",
    pkg_ind_col: str = "package_indicator",
    upi_col: str = "unique_product_identifier",
    platform_col: str = "platform_identifier",
    trade_id_col: str = "trade_id",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition legs into PTP groups and non-PTP remainder.

    Returns (ptp_groups_df, non_ptp_df).  PTP groups have
    ``ptp_group_id`` and ``ptp_group_size`` columns added.
    """
    if df.empty:
        empty = df.copy()
        empty["ptp_group_id"] = None
        empty["ptp_group_size"] = 0
        return empty.iloc[:0], empty.iloc[:0]

    ptp_vals = pd.to_numeric(df.get(ptp_col), errors="coerce")
    pkg_ind = df.get(pkg_ind_col)
    if pkg_ind is None:
        pkg_ind = pd.Series(False, index=df.index)
    pkg_ind_bool = pkg_ind.astype(str).str.lower().isin({"true", "t", "1", "yes"})

    candidate_mask = pkg_ind_bool & ptp_vals.notna() & (ptp_vals > 0)
    if not candidate_mask.any():
        out = df.copy()
        out["ptp_group_id"] = None
        out["ptp_group_size"] = 0
        return out.iloc[:0], out

    candidates = df.loc[candidate_mask].copy()
    remainder = df.loc[~candidate_mask].copy()

    ts = pd.to_datetime(candidates[exec_col], errors="coerce", utc=True)
    candidates["_ts_epoch"] = ts.astype("int64") // 10**9
    candidates = candidates.sort_values("_ts_epoch", kind="mergesort")

    epoch = candidates["_ts_epoch"].values
    cluster_ids = np.zeros(len(candidates), dtype=np.int64)
    cid = 0
    for i in range(1, len(candidates)):
        if epoch[i] - epoch[i - 1] > time_tolerance_seconds:
            cid += 1
        cluster_ids[i] = cid
    candidates["_time_cluster"] = cluster_ids

    ptp_rounded = pd.to_numeric(candidates[ptp_col], errors="coerce")
    upi = candidates[upi_col].fillna("_NONE_").astype(str) if upi_col in candidates.columns else "_NONE_"
    plat = candidates[platform_col].fillna("_NONE_").astype(str) if platform_col in candidates.columns else "_NONE_"

    candidates["_group_key"] = (
        candidates["_time_cluster"].astype(str) + "|"
        + ptp_rounded.astype(str) + "|"
        + upi + "|"
        + plat
    )

    group_sizes = candidates.groupby("_group_key")[trade_id_col].transform("count")
    in_group = group_sizes >= 2
    grouped = candidates.loc[in_group].copy()
    ungrouped = candidates.loc[~in_group].copy()

    if grouped.empty:
        remainder = pd.concat([remainder, ungrouped], ignore_index=True)
        remainder["ptp_group_id"] = None
        remainder["ptp_group_size"] = 0
        grouped["ptp_group_id"] = None
        grouped["ptp_group_size"] = 0
        return grouped, remainder

    min_tid = grouped.groupby("_group_key")[trade_id_col].transform("min")
    grouped["ptp_group_id"] = "PTP_" + min_tid.astype(str)
    grouped["ptp_group_size"] = grouped.groupby("ptp_group_id")[trade_id_col].transform("count").astype(int)

    grouped.drop(columns=["_ts_epoch", "_time_cluster", "_group_key"], inplace=True)
    ungrouped.drop(columns=["_ts_epoch", "_time_cluster", "_group_key"], inplace=True, errors="ignore")
    remainder = pd.concat([remainder, ungrouped], ignore_index=True)
    remainder["ptp_group_id"] = None
    remainder["ptp_group_size"] = 0

    return grouped, remainder
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir pytest tests/test_ptp_grouper.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/packages/ptp_grouper.py tests/test_ptp_grouper.py
git commit -m "feat(packages): PTP pre-grouper — group legs by exec_ts/PTP/UPI/platform"
```

---

### Task 2: Scoped Structure Classifier

**Files:**
- Modify: `SDRUtils/packages/ptp_grouper.py`
- Test: `tests/test_ptp_grouper.py` (append)

**Interfaces:**
- Consumes: PTP-grouped DataFrame with `ptp_group_id`, `estimated_pv01`, `tenor_years`, `trade_id`, `fixed_rate`
- Produces: `classify_ptp_groups(df) → pd.DataFrame` — sets `package_type`, `package_id`, `package_legs`, `ptp_sub_structures` on each row

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ptp_grouper.py`:

```python
from SDRUtils.packages.ptp_grouper import classify_ptp_groups


def _grouped_legs(overrides_list, ptp_group_id="PTP_T000"):
    """Build a PTP-grouped test DataFrame."""
    df = _make_legs(overrides_list)
    df["ptp_group_id"] = ptp_group_id
    df["ptp_group_size"] = len(df)
    return df


class TestClassifyPtpGroups:
    def test_two_leg_curve(self):
        df = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 10000.0},
            {"tenor_years": 10.0, "estimated_pv01": 10000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "CURVE").all()
        assert out["package_id"].iloc[0] == "PTP_T000"
        assert len(out["package_legs"].iloc[0]) == 2

    def test_three_leg_fly(self):
        df = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 5000.0},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "FLY").all()

    def test_three_leg_unbalanced_is_pkg3(self):
        df = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 5000.0},
            {"tenor_years": 5.0, "estimated_pv01": 5000.0},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-3").all()

    def test_eight_leg_ladder_is_pkg8(self):
        tenors = [2, 3, 5, 7, 10, 15, 20, 30]
        df = _grouped_legs([
            {"tenor_years": float(t), "estimated_pv01": 1000.0 * t}
            for t in tenors
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-8").all()
        assert out["package_id"].iloc[0] == "PTP_T000"
        assert len(out["package_legs"].iloc[0]) == 8
        assert out["ptp_sub_structures"].iloc[0] == []

    def test_twelve_leg_multi_fly_has_sub_annotations(self):
        legs = []
        for risk_scale in [1.0, 1.8]:
            for rate_offset in [0.0, 0.001]:
                legs.extend([
                    {"tenor_years": 2.0, "estimated_pv01": 5000 * risk_scale,
                     "fixed_rate": 0.0397 + rate_offset},
                    {"tenor_years": 5.0, "estimated_pv01": 10000 * risk_scale,
                     "fixed_rate": 0.0387 + rate_offset},
                    {"tenor_years": 10.0, "estimated_pv01": 5000 * risk_scale,
                     "fixed_rate": 0.0398 + rate_offset},
                ])
        df = _grouped_legs(legs)
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-12").all()
        subs = out["ptp_sub_structures"].iloc[0]
        assert isinstance(subs, list)
        assert len(subs) == 4
        assert all(s["type"] == "FLY" for s in subs)

    def test_multiple_groups_classified_independently(self):
        g1 = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 5000.0},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0},
        ], ptp_group_id="PTP_A")
        g2 = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 1000.0, "package_transaction_price": 50000},
            {"tenor_years": 30.0, "estimated_pv01": 1000.0, "package_transaction_price": 50000},
        ], ptp_group_id="PTP_B")
        df = pd.concat([g1, g2], ignore_index=True)
        out = classify_ptp_groups(df)
        types = out.groupby("ptp_group_id")["package_type"].first()
        assert types["PTP_A"] == "FLY"
        assert types["PTP_B"] == "CURVE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir pytest tests/test_ptp_grouper.py::TestClassifyPtpGroups -v`
Expected: `ImportError: cannot import name 'classify_ptp_groups'`

- [ ] **Step 3: Implement `classify_ptp_groups`**

Append to `SDRUtils/packages/ptp_grouper.py`:

```python
def _is_dv01_balanced(values: list[float], tolerance: float = 0.15) -> bool:
    if len(values) < 2:
        return False
    avg = sum(values) / len(values)
    if avg <= 0:
        return False
    return all(abs(v - avg) / avg <= tolerance for v in values)


def _detect_sub_flies(
    group_df: pd.DataFrame,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_tol: float = 0.15,
) -> list[dict]:
    """Detect DV01-balanced fly triplets within a large group.

    Returns list of sub-structure annotations. Non-greedy: only
    reports sub-flies if ALL legs are consumed by complete triplets.
    """
    tenors = pd.to_numeric(group_df[tenor_years_col], errors="coerce")
    pv01 = pd.to_numeric(group_df[pv01_col], errors="coerce").fillna(0)
    tids = group_df[trade_id_col].astype(str)

    distinct_tenors = sorted(tenors.dropna().unique())
    if len(distinct_tenors) != 3:
        return []

    by_tenor = {}
    for idx, (t, p, tid) in enumerate(zip(tenors, pv01, tids)):
        bucket = round(t, 1)
        by_tenor.setdefault(bucket, []).append({"pv01": p, "tid": tid})

    tenor_keys = sorted(by_tenor.keys())
    if len(tenor_keys) != 3:
        return []

    short_legs = by_tenor[tenor_keys[0]]
    belly_legs = by_tenor[tenor_keys[1]]
    long_legs = by_tenor[tenor_keys[2]]

    if not (len(short_legs) == len(belly_legs) == len(long_legs)):
        return []

    short_sorted = sorted(short_legs, key=lambda x: x["pv01"])
    belly_sorted = sorted(belly_legs, key=lambda x: x["pv01"])
    long_sorted = sorted(long_legs, key=lambda x: x["pv01"])

    subs = []
    for s, b, l in zip(short_sorted, belly_sorted, long_sorted):
        wing_avg = (s["pv01"] + l["pv01"]) / 2.0
        expected_belly = 2.0 * wing_avg
        if wing_avg <= 0:
            return []
        belly_rel = abs(b["pv01"] - expected_belly) / max(expected_belly, 1e-12)
        wings_rel = abs(s["pv01"] - l["pv01"]) / max(wing_avg, 1e-12)
        if belly_rel > belly_tol or wings_rel > belly_tol:
            return []
        subs.append({
            "type": "FLY",
            "legs": [s["tid"], b["tid"], l["tid"]],
            "belly_dv01": round(b["pv01"], 2),
        })
    return subs


def _classify_single_group(
    group_df: pd.DataFrame,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_tol: float = 0.15,
) -> tuple[str, list[dict]]:
    """Classify one PTP group. Returns (package_type, sub_structures)."""
    n = len(group_df)
    pv01 = pd.to_numeric(group_df[pv01_col], errors="coerce").fillna(0).values

    if n == 2:
        if _is_dv01_balanced(list(pv01), tolerance=belly_tol):
            return "CURVE", []
        return "PKG-2", []

    if n == 3:
        sorted_idx = pd.to_numeric(
            group_df[tenor_years_col], errors="coerce"
        ).fillna(0).argsort()
        sorted_pv01 = pv01[sorted_idx]
        wing_avg = (sorted_pv01[0] + sorted_pv01[2]) / 2.0
        expected_belly = 2.0 * wing_avg
        if wing_avg > 0:
            belly_rel = abs(sorted_pv01[1] - expected_belly) / max(expected_belly, 1e-12)
            wings_rel = abs(sorted_pv01[0] - sorted_pv01[2]) / max(wing_avg, 1e-12)
            if belly_rel <= belly_tol and wings_rel <= belly_tol:
                return "FLY", []
        return "PKG-3", []

    sub_flies = _detect_sub_flies(
        group_df, pv01_col=pv01_col, tenor_years_col=tenor_years_col,
        trade_id_col=trade_id_col, belly_tol=belly_tol,
    )
    return f"PKG-{n}", sub_flies


def classify_ptp_groups(
    df: pd.DataFrame,
    *,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_ratio_tolerance: float = 0.15,
) -> pd.DataFrame:
    """Classify each PTP group holistically. Sets package_type,
    package_id, package_legs, and ptp_sub_structures."""
    if df.empty or "ptp_group_id" not in df.columns:
        return df

    out = df.copy()
    if "package_type" not in out.columns:
        out["package_type"] = "OUTRIGHT"
    if "package_id" not in out.columns:
        out["package_id"] = None
    if "package_legs" not in out.columns:
        out["package_legs"] = None
    out["ptp_sub_structures"] = None

    for gid, grp in out.groupby("ptp_group_id"):
        if pd.isna(gid):
            continue
        all_tids = sorted(grp[trade_id_col].astype(str).tolist())
        pkg_type, sub_structs = _classify_single_group(
            grp, pv01_col=pv01_col, tenor_years_col=tenor_years_col,
            trade_id_col=trade_id_col, belly_tol=belly_ratio_tolerance,
        )
        mask = out["ptp_group_id"] == gid
        out.loc[mask, "package_type"] = pkg_type
        out.loc[mask, "package_id"] = gid
        out.loc[mask, "package_legs"] = [all_tids] * mask.sum()
        out.loc[mask, "ptp_sub_structures"] = [sub_structs] * mask.sum()

    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir pytest tests/test_ptp_grouper.py -v`
Expected: All 17 tests PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/packages/ptp_grouper.py tests/test_ptp_grouper.py
git commit -m "feat(packages): PTP structure classifier — FLY/CURVE/PKG-N with sub-fly annotations"
```

---

### Task 3: OPA Sign Solver

**Files:**
- Create: `SDRUtils/packages/opa_sign_solver.py`
- Test: `tests/test_opa_sign_solver.py`

**Interfaces:**
- Consumes: Lists of OPA values, PTP value, optional rate/tenor group indices
- Produces: `solve_opa_signs(opa_values, ptp_value, *, rate_tenor_groups=None) → dict` with keys `signs`, `net`, `residual`, `confidence`, `constrained_signs`, `constrained_net`, `constrained_residual`
- Also: `solve_all_opa_signs(df) → pd.DataFrame` — batch wrapper adding `opa_sign`, `opa_signed_amount` per-leg columns and per-group summary columns

- [ ] **Step 1: Write failing tests**

```python
# tests/test_opa_sign_solver.py
"""Tests for OPA sign solver — brute-force + constrained + greedy."""
import pytest

from SDRUtils.packages.opa_sign_solver import (
    solve_opa_signs,
    confidence_tier,
)


class TestConfidenceTier:
    def test_exact(self):
        assert confidence_tier(50.0) == "EXACT"

    def test_tight(self):
        assert confidence_tier(500.0) == "TIGHT"

    def test_loose(self):
        assert confidence_tier(10000.0) == "LOOSE"

    def test_unresolved(self):
        assert confidence_tier(100000.0) == "UNRESOLVED"

    def test_boundary_exact(self):
        assert confidence_tier(99.99) == "EXACT"
        assert confidence_tier(100.01) == "TIGHT"


class TestSolveOpaSigns:
    def test_two_legs_exact_match(self):
        """Two legs whose diff equals PTP exactly."""
        result = solve_opa_signs([600.0, 500.0], ptp_value=100.0)
        assert result["residual"] < 1.0
        assert result["confidence"] == "EXACT"
        assert len(result["signs"]) == 2
        net = sum(s * v for s, v in zip(result["signs"], [600.0, 500.0]))
        assert abs(abs(net) - 100.0) < 1.0

    def test_twelve_leg_fly_case(self):
        """Real-world 12-leg fly OPA values from the June 25 trade."""
        opas = [
            13267.67310, 677255.44976, 314119.12370,
            23741.62083, 1227520.75738, 563983.19706,
            583940.98780, 46229.79335, 35390.43816,
            326319.60400, 25505.69450, 19963.57680,
        ]
        result = solve_opa_signs(opas, ptp_value=88100.0)
        assert result["residual"] < 300  # known: ~216
        assert result["confidence"] == "TIGHT"

    def test_eight_leg_mac_ladder(self):
        """Real-world 8-leg MAC ladder from July 1."""
        opas = [
            78379.0, 222414.96410, 658253.55059,
            847927.27494, 77767.0, 329324.49648,
            74086.48145, 75285.14512,
        ]
        result = solve_opa_signs(opas, ptp_value=1537032.0)
        assert result["residual"] < 15000  # known: ~11K
        assert result["confidence"] == "LOOSE"

    def test_constrained_solve(self):
        """Legs in the same rate/tenor group must share signs."""
        opas = [100.0, 200.0, 100.0, 200.0]
        groups = [0, 1, 0, 1]  # legs 0,2 same group; legs 1,3 same group
        result = solve_opa_signs(opas, ptp_value=200.0, rate_tenor_groups=groups)
        assert result["constrained_signs"] is not None
        assert result["constrained_signs"][0] == result["constrained_signs"][2]
        assert result["constrained_signs"][1] == result["constrained_signs"][3]

    def test_empty_opas(self):
        result = solve_opa_signs([], ptp_value=100.0)
        assert result["signs"] == []
        assert result["confidence"] == "UNRESOLVED"

    def test_single_leg(self):
        result = solve_opa_signs([100.0], ptp_value=100.0)
        assert result["residual"] < 1.0
        assert result["signs"] == [1]

    def test_greedy_fallback_large_n(self):
        """N=26 should use greedy fallback without timeout."""
        import random
        random.seed(42)
        opas = [random.uniform(1000, 100000) for _ in range(26)]
        ptp = sum(opas) * 0.1
        result = solve_opa_signs(opas, ptp_value=ptp)
        assert result["signs"] is not None
        assert len(result["signs"]) == 26
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir pytest tests/test_opa_sign_solver.py -v`
Expected: `ModuleNotFoundError: No module named 'SDRUtils.packages.opa_sign_solver'`

- [ ] **Step 3: Implement the solver**

```python
# SDRUtils/packages/opa_sign_solver.py
"""OPA sign solver — infer pay/receive direction for package legs.

Brute-force 2^N for N ≤ 24, greedy heuristic above. Also supports
economically-constrained solving where legs sharing the same
(rate, tenor) must have the same sign.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


_TIER_THRESHOLDS = [
    (100.0, "EXACT"),
    (1_000.0, "TIGHT"),
    (50_000.0, "LOOSE"),
]


def confidence_tier(residual: float) -> str:
    for threshold, label in _TIER_THRESHOLDS:
        if residual < threshold:
            return label
    return "UNRESOLVED"


def _solve_brute(opa: list[float], ptp: float) -> tuple[list[int], float, float]:
    n = len(opa)
    best_mask = 0
    best_residual = float("inf")
    best_net = 0.0
    for mask in range(1 << n):
        net = 0.0
        for i in range(n):
            net += opa[i] if (mask & (1 << i)) else -opa[i]
        residual = min(abs(net - ptp), abs(net + ptp))
        if residual < best_residual:
            best_residual = residual
            best_mask = mask
            best_net = net
    signs = [1 if (best_mask & (1 << i)) else -1 for i in range(n)]
    return signs, best_net, best_residual


def _solve_greedy(opa: list[float], ptp: float) -> tuple[list[int], float, float]:
    indexed = sorted(enumerate(opa), key=lambda x: -x[1])
    signs = [0] * len(opa)
    running = 0.0
    for idx, val in indexed:
        plus_d = min(abs(running + val - ptp), abs(running + val + ptp))
        minus_d = min(abs(running - val - ptp), abs(running - val + ptp))
        if plus_d <= minus_d:
            signs[idx] = 1
            running += val
        else:
            signs[idx] = -1
            running -= val
    residual = min(abs(running - ptp), abs(running + ptp))
    return signs, running, residual


def _solve_constrained(
    opa: list[float],
    ptp: float,
    groups: list[int],
) -> tuple[list[int], float, float]:
    unique_groups = sorted(set(groups))
    k = len(unique_groups)
    group_map = {g: i for i, g in enumerate(unique_groups)}
    group_indices: list[list[int]] = [[] for _ in range(k)]
    for i, g in enumerate(groups):
        group_indices[group_map[g]].append(i)

    group_sums = [sum(opa[i] for i in idxs) for idxs in group_indices]

    if k <= 24:
        g_signs, g_net, g_residual = _solve_brute(group_sums, ptp)
    else:
        g_signs, g_net, g_residual = _solve_greedy(group_sums, ptp)

    signs = [0] * len(opa)
    for gi, idxs in enumerate(group_indices):
        for i in idxs:
            signs[i] = g_signs[gi]
    return signs, g_net, g_residual


_MAX_BRUTE_N = 24


def solve_opa_signs(
    opa_values: list[float],
    ptp_value: float,
    *,
    rate_tenor_groups: Optional[list[int]] = None,
) -> dict:
    """Solve for the sign assignment minimizing |Σ(s·OPA) - PTP|.

    Returns dict with keys: signs, net, residual, confidence,
    constrained_signs, constrained_net, constrained_residual.
    """
    n = len(opa_values)
    if n == 0:
        return {
            "signs": [],
            "net": 0.0,
            "residual": abs(ptp_value),
            "confidence": "UNRESOLVED",
            "constrained_signs": None,
            "constrained_net": None,
            "constrained_residual": None,
        }

    if not math.isfinite(ptp_value) or ptp_value == 0:
        return {
            "signs": [1] * n,
            "net": sum(opa_values),
            "residual": abs(sum(opa_values)),
            "confidence": "UNRESOLVED",
            "constrained_signs": None,
            "constrained_net": None,
            "constrained_residual": None,
        }

    if n <= _MAX_BRUTE_N:
        signs, net, residual = _solve_brute(opa_values, ptp_value)
    else:
        signs, net, residual = _solve_greedy(opa_values, ptp_value)

    result = {
        "signs": signs,
        "net": net,
        "residual": residual,
        "confidence": confidence_tier(residual),
        "constrained_signs": None,
        "constrained_net": None,
        "constrained_residual": None,
    }

    if rate_tenor_groups is not None and len(rate_tenor_groups) == n:
        c_signs, c_net, c_residual = _solve_constrained(
            opa_values, ptp_value, rate_tenor_groups,
        )
        result["constrained_signs"] = c_signs
        result["constrained_net"] = c_net
        result["constrained_residual"] = c_residual

    return result


def _rate_tenor_group_index(
    fixed_rates: list[float],
    tenor_years: list[float],
) -> list[int]:
    """Assign a group index to each leg by (rate rounded to 0.01bp, tenor rounded to 0.1Y)."""
    keys = []
    for r, t in zip(fixed_rates, tenor_years):
        rr = round(r, 6) if r is not None and math.isfinite(r) else None
        tr = round(t, 1) if t is not None and math.isfinite(t) else None
        keys.append((rr, tr))
    unique = sorted(set(keys))
    key_to_idx = {k: i for i, k in enumerate(unique)}
    return [key_to_idx[k] for k in keys]


def solve_all_opa_signs(
    df: pd.DataFrame,
    *,
    ptp_group_col: str = "ptp_group_id",
    opa_col: str = "other_payment_amount",
    ptp_col: str = "package_transaction_price",
    rate_col: str = "fixed_rate",
    tenor_col: str = "tenor_years",
    pv01_col: str = "estimated_pv01",
) -> pd.DataFrame:
    """Batch OPA sign solver across all PTP groups in the DataFrame.

    Adds per-leg columns: opa_sign, opa_signed_amount.
    Adds per-group columns: opa_signed_net, opa_ptp_residual,
    opa_sign_confidence, opa_constrained_net, opa_constrained_residual,
    dealer_spread_est, dealer_spread_bps.
    """
    out = df.copy()
    for col in ["opa_sign", "opa_signed_amount", "opa_signed_net",
                "opa_ptp_residual", "opa_sign_confidence",
                "opa_constrained_net", "opa_constrained_residual",
                "dealer_spread_est", "dealer_spread_bps"]:
        out[col] = None

    if ptp_group_col not in out.columns:
        return out

    for gid, grp in out.groupby(ptp_group_col):
        if pd.isna(gid):
            continue

        opas = pd.to_numeric(grp[opa_col], errors="coerce").fillna(0).tolist()
        ptp_vals = pd.to_numeric(grp[ptp_col], errors="coerce")
        ptp_val = ptp_vals.dropna().iloc[0] if ptp_vals.notna().any() else 0.0

        rates = pd.to_numeric(grp[rate_col], errors="coerce").fillna(0).tolist()
        tenors = pd.to_numeric(grp[tenor_col], errors="coerce").fillna(0).tolist()
        rt_groups = _rate_tenor_group_index(rates, tenors)

        result = solve_opa_signs(opas, ptp_val, rate_tenor_groups=rt_groups)

        mask = out[ptp_group_col] == gid
        idx_list = out.loc[mask].index.tolist()

        for i, ix in enumerate(idx_list):
            out.at[ix, "opa_sign"] = result["signs"][i]
            out.at[ix, "opa_signed_amount"] = result["signs"][i] * opas[i]

        total_dv01 = pd.to_numeric(grp[pv01_col], errors="coerce").fillna(0).sum()
        spread_bps = (
            (result["residual"] / total_dv01 * 100)
            if total_dv01 > 0 else None
        )

        out.loc[mask, "opa_signed_net"] = result["net"]
        out.loc[mask, "opa_ptp_residual"] = result["residual"]
        out.loc[mask, "opa_sign_confidence"] = result["confidence"]
        out.loc[mask, "opa_constrained_net"] = result.get("constrained_net")
        out.loc[mask, "opa_constrained_residual"] = result.get("constrained_residual")
        out.loc[mask, "dealer_spread_est"] = result["residual"]
        out.loc[mask, "dealer_spread_bps"] = spread_bps

    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir pytest tests/test_opa_sign_solver.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/packages/opa_sign_solver.py tests/test_opa_sign_solver.py
git commit -m "feat(packages): OPA sign solver — brute-force + constrained + greedy fallback"
```

---

### Task 4: Pipeline Integration

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py` (the `_run_all_detectors` inner function)
- Test: `tests/test_ptp_pipeline_integration.py`

**Interfaces:**
- Consumes: `group_by_ptp`, `classify_ptp_groups`, `solve_all_opa_signs` from Tasks 1-3
- Produces: Modified `_run_all_detectors` that splits PTP legs, classifies them separately, and runs OPA sign solver post-merge

- [ ] **Step 1: Write integration test**

```python
# tests/test_ptp_pipeline_integration.py
"""Integration test: PTP legs bypass global detectors, non-PTP legs unchanged."""
import pandas as pd
import pytest

from SDRUtils.packages.ptp_grouper import group_by_ptp, classify_ptp_groups
from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs


def _pipeline_sim(df):
    """Simulate the new _run_all_detectors flow without importing usd_swaps."""
    ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)

    if not ptp_df.empty:
        ptp_df = classify_ptp_groups(ptp_df)

    if not non_ptp_df.empty:
        if "package_type" not in non_ptp_df.columns:
            non_ptp_df["package_type"] = "OUTRIGHT"
        if "package_id" not in non_ptp_df.columns:
            non_ptp_df["package_id"] = None
        if "package_legs" not in non_ptp_df.columns:
            non_ptp_df["package_legs"] = None

    merged = pd.concat([ptp_df, non_ptp_df], ignore_index=True)
    merged = solve_all_opa_signs(merged)
    return merged


def test_ptp_legs_get_classified_non_ptp_stay_outright():
    ts = pd.Timestamp("2026-06-25 14:30:59", tz="UTC")
    rows = [
        # PTP group: 3-leg fly
        {"trade_id": "P1", "execution_timestamp": ts,
         "package_transaction_price": 88100.0, "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 5000.0, "tenor_years": 2.0, "fixed_rate": 0.04,
         "other_payment_amount": 1000.0, "product_type": "OIS_SWAP"},
        {"trade_id": "P2", "execution_timestamp": ts,
         "package_transaction_price": 88100.0, "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 10000.0, "tenor_years": 5.0, "fixed_rate": 0.04,
         "other_payment_amount": 5000.0, "product_type": "OIS_SWAP"},
        {"trade_id": "P3", "execution_timestamp": ts,
         "package_transaction_price": 88100.0, "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 5000.0, "tenor_years": 10.0, "fixed_rate": 0.04,
         "other_payment_amount": 2000.0, "product_type": "OIS_SWAP"},
        # Non-PTP outright
        {"trade_id": "O1", "execution_timestamp": ts,
         "package_transaction_price": None, "package_indicator": False,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 8000.0, "tenor_years": 5.0, "fixed_rate": 0.04,
         "other_payment_amount": 0.0, "product_type": "OIS_SWAP"},
    ]
    df = pd.DataFrame(rows)
    result = _pipeline_sim(df)

    ptp_rows = result[result["ptp_group_id"].notna()]
    non_ptp_rows = result[result["ptp_group_id"].isna()]

    assert len(ptp_rows) == 3
    assert (ptp_rows["package_type"] == "FLY").all()
    assert ptp_rows["opa_sign"].notna().all()
    assert ptp_rows["opa_sign_confidence"].iloc[0] is not None

    assert len(non_ptp_rows) == 1
    assert non_ptp_rows["package_type"].iloc[0] == "OUTRIGHT"
    assert non_ptp_rows["opa_sign"].iloc[0] is None
```

- [ ] **Step 2: Run test to verify it passes** (this tests the module composition, not the usd_swaps.py wiring)

Run: `conda run -n stir pytest tests/test_ptp_pipeline_integration.py -v`
Expected: PASS

- [ ] **Step 3: Modify `_run_all_detectors` in `usd_swaps.py`**

Find the `_run_all_detectors` inner function (around line 1652). Add the PTP pre-grouping at the top and OPA solver at the bottom. The key change:

```python
# At the top of _run_all_detectors, BEFORE existing detectors:
from SDRUtils.packages.ptp_grouper import group_by_ptp, classify_ptp_groups
from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)

if not ptp_df.empty:
    ptp_df = classify_ptp_groups(ptp_df)

# Replace df with non_ptp_df for all existing detector calls:
df = non_ptp_df

# ... existing detector chain runs on df (non-PTP legs only) ...

# After all existing detectors, merge back and run solver:
df = pd.concat([ptp_df, df], ignore_index=True)
df = solve_all_opa_signs(df)
```

The exact edit depends on the function structure. Read `SDRUtils/products/usd/usd_swaps.py` at lines 1640-1680 to find the precise insertion points. Ensure the `_snake_detector_cols` kwargs are still passed to existing detectors on `non_ptp_df`.

- [ ] **Step 4: Run existing regression tests**

Run: `conda run -n stir pytest tests/test_fly_detector_arrival_order.py tests/test_gap_fly_detection.py tests/test_gap_curve_detection.py tests/test_v2_package_detection.py tests/test_basis_packages.py -v`
Expected: All PASS (existing detectors unaffected — they now run on non-PTP legs only, which is the same population as before for trades without `package_indicator=True`)

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py tests/test_ptp_pipeline_integration.py
git commit -m "feat(pipeline): wire PTP pre-grouper + OPA solver into _run_all_detectors"
```

---

### Task 5: Schema + Tape Write

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` (add columns to table definitions)
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` (add columns to LEG_COLUMNS and PACKAGE_COLUMNS lists, update build_package_rows)
- Modify: `SDRUtils/analytics/trade_tape.py` (`_enrich_packages` — pass through new columns)
- Test: Manual — run `conda run -n stir python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline backfill --date 2026-06-25 --skip-classification` and verify new columns appear in DB

**Interfaces:**
- Consumes: DataFrame with `ptp_group_id`, `ptp_group_size`, `opa_sign`, `opa_signed_amount`, `ptp_sub_structures`, `opa_signed_net`, `opa_ptp_residual`, `opa_sign_confidence`, `opa_constrained_net`, `opa_constrained_residual`, `dealer_spread_est`, `dealer_spread_bps` from Task 3/4
- Produces: These columns persisted to `arbs_usd_swap_tape_legs_v2` and `arbs_usd_swap_tape_packages_v2`, exposed via display view

- [ ] **Step 1: Add columns to schema definitions**

In `SDRUtils/_swappulse_scripts/_tape_schema_v2.py`, find the legs table column list and add after the existing `package_transaction_price` column:

```python
# In LEGS table definition, after package_transaction_price:
Column("ptp_group_id", Text, nullable=True),
Column("opa_sign", SmallInteger, nullable=True),
Column("opa_signed_amount", Numeric, nullable=True),
```

In the PACKAGES table definition, add after `package_transaction_price_currency`:

```python
Column("ptp_group_id", Text, nullable=True),
Column("ptp_group_size", Integer, nullable=True),
Column("opa_signed_net", Numeric, nullable=True),
Column("opa_ptp_residual", Numeric, nullable=True),
Column("opa_sign_confidence", Text, nullable=True),
Column("opa_constrained_net", Numeric, nullable=True),
Column("opa_constrained_residual", Numeric, nullable=True),
Column("dealer_spread_est", Numeric, nullable=True),
Column("dealer_spread_bps", Numeric, nullable=True),
Column("ptp_sub_structures", JSONB, nullable=True),
```

- [ ] **Step 2: Add columns to upsert column lists**

In `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`, find `LEG_COLUMNS` (around line 49-173) and add:

```python
"ptp_group_id",
"opa_sign",
"opa_signed_amount",
```

Find `PACKAGE_COLUMNS` (around line 176-245) and add:

```python
"ptp_group_id",
"ptp_group_size",
"opa_signed_net",
"opa_ptp_residual",
"opa_sign_confidence",
"opa_constrained_net",
"opa_constrained_residual",
"dealer_spread_est",
"dealer_spread_bps",
"ptp_sub_structures",
```

Add `"ptp_sub_structures"` to `JSON_PKG_COLS` (the list of JSONB columns that get special serialization).

- [ ] **Step 3: Update `build_package_rows` to aggregate new columns**

In `ingest_usdswaps_tape.py`, find `build_package_rows()`. Add aggregation for new package-level columns. These are already set per-leg by `solve_all_opa_signs` with the same value for all legs in a group, so use `"first"`:

```python
# In the groupby().agg() call, add:
ptp_group_id=("ptp_group_id", "first"),
ptp_group_size=("ptp_group_size", "first"),
opa_signed_net=("opa_signed_net", "first"),
opa_ptp_residual=("opa_ptp_residual", "first"),
opa_sign_confidence=("opa_sign_confidence", "first"),
opa_constrained_net=("opa_constrained_net", "first"),
opa_constrained_residual=("opa_constrained_residual", "first"),
dealer_spread_est=("dealer_spread_est", "first"),
dealer_spread_bps=("dealer_spread_bps", "first"),
ptp_sub_structures=("ptp_sub_structures", "first"),
```

- [ ] **Step 4: Pass through columns in `_enrich_packages`**

In `SDRUtils/analytics/trade_tape.py`, `_enrich_packages()` — no modification needed if the columns are already present on the DataFrame from the detection step. They flow through as-is. Verify by checking that `_enrich_packages` doesn't drop unknown columns (it doesn't — it only adds columns).

- [ ] **Step 5: Update display view**

In `_tape_schema_v2.py`, find the `DISPLAY_VIEW_V2` SQL definition. Add new columns to the SELECT list from the packages table join:

```sql
p.ptp_group_id,
p.ptp_group_size,
p.opa_signed_net,
p.opa_ptp_residual,
p.opa_sign_confidence,
p.dealer_spread_est,
p.dealer_spread_bps,
p.ptp_sub_structures,
```

- [ ] **Step 6: Run schema migration on Supabase**

Execute the ALTER TABLE statements from the spec against the live database. Use `ensure_schema()` which auto-creates missing columns, or run manually:

```sql
ALTER TABLE arbs_usd_swap_tape_legs_v2
  ADD COLUMN IF NOT EXISTS ptp_group_id text,
  ADD COLUMN IF NOT EXISTS opa_sign smallint,
  ADD COLUMN IF NOT EXISTS opa_signed_amount numeric;

ALTER TABLE arbs_usd_swap_tape_packages_v2
  ADD COLUMN IF NOT EXISTS ptp_group_id text,
  ADD COLUMN IF NOT EXISTS ptp_group_size integer,
  ADD COLUMN IF NOT EXISTS opa_signed_net numeric,
  ADD COLUMN IF NOT EXISTS opa_ptp_residual numeric,
  ADD COLUMN IF NOT EXISTS opa_sign_confidence text,
  ADD COLUMN IF NOT EXISTS opa_constrained_net numeric,
  ADD COLUMN IF NOT EXISTS opa_constrained_residual numeric,
  ADD COLUMN IF NOT EXISTS dealer_spread_est numeric,
  ADD COLUMN IF NOT EXISTS dealer_spread_bps numeric,
  ADD COLUMN IF NOT EXISTS ptp_sub_structures jsonb;
```

Then recreate the display view with the updated definition.

- [ ] **Step 7: Backfill test — run pipeline on June 25 data**

Run: `conda run -n stir python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline backfill --date 2026-06-25`

Verify in DB:
```sql
SELECT trade_id, ptp_group_id, opa_sign, opa_signed_amount
FROM arbs_usd_swap_tape_legs_v2
WHERE ptp_group_id IS NOT NULL
ORDER BY ptp_group_id, tenor_years
LIMIT 20;
```

Expected: 12 rows for the IMM_U2026 fly with `ptp_group_id = 'PTP_3865630341000001201'`, each with `opa_sign` ∈ {-1, +1} and `opa_signed_amount` populated.

- [ ] **Step 8: Commit**

```bash
git add SDRUtils/_swappulse_scripts/_tape_schema_v2.py SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py SDRUtils/analytics/trade_tape.py
git commit -m "feat(schema): add PTP/OPA columns to legs+packages tables and display view"
```

---

### Task 6: Dashboard — Types, API, and Frontend

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/trade.types.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/LegsSubTable.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/LegsSubTable.helpers.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/filter-utils.ts`
- Test: Visual verification in Chrome MCP at localhost:3000

**Interfaces:**
- Consumes: New columns from display view (`ptp_group_id`, `ptp_group_size`, `opa_signed_net`, `opa_ptp_residual`, `opa_sign_confidence`, `dealer_spread_est`, `dealer_spread_bps`, `ptp_sub_structures`) and per-leg columns via `legs_json` (`opa_sign`, `opa_signed_amount`)
- Produces: OPA tieout display, sign badges, confidence filter, dealer spread column

- [ ] **Step 1: Add TypeScript types**

In `trade.types.ts`, add to `UsdSwapTapeRow`:

```typescript
ptp_group_id?: string | null
ptp_group_size?: number | null
opa_signed_net?: number | null
opa_ptp_residual?: number | null
opa_sign_confidence?: 'EXACT' | 'TIGHT' | 'LOOSE' | 'UNRESOLVED' | string | null
dealer_spread_est?: number | null
dealer_spread_bps?: number | null
ptp_sub_structures?: Array<{ type: string; legs: string[]; belly_dv01?: number }> | null
```

Add to `UsdSwapTapeLeg`:

```typescript
opa_sign?: number | null        // +1 or -1
opa_signed_amount?: number | null
```

- [ ] **Step 2: Add sign badges to LegsSubTable**

In `LegsSubTable.tsx`, find the OPA column cell renderer. Update it to show direction:

```typescript
// In the OPA cell, check for opa_sign on the leg:
const sign = leg.opa_sign
const opa = leg.other_payment_amount
if (sign != null && opa != null) {
  const signed = sign * opa
  const color = sign > 0 ? 'text-emerald-400' : 'text-red-400'
  const prefix = sign > 0 ? '+' : '−'
  return <span className={color}>{prefix}{formatDollar(Math.abs(signed))}</span>
}
```

- [ ] **Step 3: Add OPA tieout + dealer spread to package header row**

In `columns.tsx`, find the package summary column or the "OTHER LVL" / "REPORTED LVL" column area. Add a new cell that shows the OPA tieout when `ptp_group_id` is present:

```typescript
// Confidence badge colors
const CONFIDENCE_COLORS: Record<string, string> = {
  EXACT: 'bg-emerald-500/20 text-emerald-400',
  TIGHT: 'bg-emerald-500/10 text-emerald-300',
  LOOSE: 'bg-amber-500/20 text-amber-400',
  UNRESOLVED: 'bg-zinc-500/20 text-zinc-400',
}
```

Render on the package header row:
```typescript
{row.opa_sign_confidence && (
  <div className="flex items-center gap-1 text-xs">
    <span className={`px-1.5 py-0.5 rounded ${CONFIDENCE_COLORS[row.opa_sign_confidence] ?? ''}`}>
      {row.opa_sign_confidence}
    </span>
    {row.dealer_spread_bps != null && (
      <span className="text-zinc-500">
        Spread: {row.dealer_spread_bps.toFixed(2)}bp
      </span>
    )}
  </div>
)}
```

- [ ] **Step 4: Add confidence filter**

In `filter-utils.ts`, add a new filter for `opa_sign_confidence`:

```typescript
// Add to the filter options list:
{
  id: 'opa_sign_confidence',
  label: 'OPA Confidence',
  options: ['EXACT', 'TIGHT', 'LOOSE', 'UNRESOLVED'],
  type: 'multiSelect',
}
```

Wire it into the WHERE clause builder in `route.logic.ts`'s `buildTapeQuery` — add a `columnFilters` case for `opa_sign_confidence`.

- [ ] **Step 5: Add sort by dealer spread**

In `columns.tsx`, add `dealer_spread_bps` as a sortable column. The TanStack Table column definition:

```typescript
{
  accessorKey: 'dealer_spread_bps',
  header: 'Spread (bp)',
  cell: ({ getValue }) => {
    const v = getValue<number | null>()
    return v != null ? `${v.toFixed(2)}bp` : '—'
  },
  sortingFn: 'basic',
  size: 80,
}
```

- [ ] **Step 6: Verify in browser**

Run: `cd SDRUtils/dashboard && npm run dev`

Open Chrome, navigate to localhost:3000, go to USD Swaps Tape v2. Find PTP-grouped packages (filter by `opa_sign_confidence` ≠ null). Verify:
- Sign badges (+/−) appear on expanded leg rows
- Confidence badge (EXACT/TIGHT/LOOSE) on package header
- Dealer spread in bps shown
- Confidence filter dropdown works
- Sort by dealer spread works

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/dashboard/src/
git commit -m "feat(dashboard): OPA tieout column, sign badges, confidence filter, dealer spread"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-07-01-ptp-package-detection.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?