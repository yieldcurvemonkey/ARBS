# USD Swap Tape v2 — FOMC/IMM Labeling + Package UPI Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix flakey FOMC/IMM labeling and package false-positives in `usd-swap-tape-v2` by introducing a 3-tier special-tenor priority and a hard `Unique Product Identifier` gate on package detection.

**Architecture:** Two orthogonal fixes in the existing pipeline:
1. Rewrite `detect_special_tenor` (`SDRUtils/core/tenors.py`) and the meeting-label emitter in `_enrich_context` (`SDRUtils/analytics/trade_tape.py`) to follow a strict 3-tier priority: consecutive-FOMC > quarterly-IMM > FOMC-other.
2. Add `require_same_upi` parameter to `curve.py`, `fly.py`, `basis.py` so legs with differing UPIs never get bundled; add a safety-net UPI validator in `_enrich_packages` that un-packages heterogeneous-UPI multi-leg groups surviving via SDR-native `Package indicator`.

**Tech Stack:** Python 3.11, pandas, numpy, pytest. Run everything under `conda run -n stir`.

---

## Context primer for the implementing engineer

- The tape pipeline is: raw SDR → `ingest_usdswaps` classifier → `TradeTape.compute()` (pandas enrichment) → `ingest_usdswaps_tape` writes leg + package rows to Postgres.
- `ingest_usdswaps_tape.py` itself is a thin wrapper; the labeling bug and package-grouping bug live **upstream** in the classifier + TradeTape.
- `_CENTRAL_BANK_DATES["USD-SOFR-1D"]` in `Query.IRSwaps._CENTRAL_BANK_DATES` maps meeting-label keys (e.g. `"APR26"`) → `(effective_date, maturity_date)` tuples. `load_fomc_schedule()` in [SDRUtils/analytics/fomc.py:23](SDRUtils/analytics/fomc.py:23) returns the schedule sorted by `effective_date`; **consecutive** = adjacent rows.
- Raw SDR column names: `"Unique Product Identifier"` (the 12-char DSB code), `"UPI Underlier Name"` (human-readable — e.g. `"USD-SOFR-COMPOUND 1D"`). These are **different**. The classifier keeps raw column names on the df until tape ingestion.
- The snake_case alias `unique_product_identifier` is also present after pandas normalization (see [ingest_usdswaps.py:38](SDRUtils/_swappulse_scripts/ingest_usdswaps.py:38)). Detectors operate on pre-classification raw columns, so use `"Unique Product Identifier"`.
- Label-shape examples from the user (target outputs):
  - Tier 1 consecutive-FOMC: `FOMC APR26`
  - Tier 2 IMM quarterly + constant tenor: `USD-SOFR-COMPOUND 1D Constant IMM_Z2026 10Y Outright PHYS`
  - Tier 3 FOMC + constant tenor: `USD-SOFR-COMPOUND 1D Constant FOMC APR26 10Y Outright PHYS`
  - Tier 3 FOMC + non-consec FOMC: `USD-SOFR-COMPOUND 1D Constant FOMC APR26 DEC26 Outright PHYS`
- All `pytest` invocations MUST run under `conda run -n stir pytest ...` per repo-level memory.

---

## Task 1: `consecutive_meeting_pair` helper in `fomc.py`

**Files:**
- Modify: [SDRUtils/analytics/fomc.py](SDRUtils/analytics/fomc.py) — add a new standalone helper alongside `load_fomc_schedule`.
- Test: `tests/test_fomc_consecutive_pair.py` (new)

**Step 1: Write the failing test**

Create `tests/test_fomc_consecutive_pair.py`:

```python
"""Tests for consecutive_meeting_pair helper.

Verifies that a pair of dates is classified as consecutive FOMC meetings
iff the dates exactly match adjacent rows in the schedule (sorted by
effective_date).
"""
import pandas as pd
import pytest

from SDRUtils.analytics.fomc import (
    consecutive_meeting_pair,
    load_fomc_schedule,
)


@pytest.fixture
def schedule():
    sched = load_fomc_schedule()
    if sched.empty:
        pytest.skip("FOMC schedule unavailable in this env")
    return sched


def test_adjacent_meetings_are_consecutive(schedule):
    row0 = schedule.iloc[0]
    row1 = schedule.iloc[1]
    assert consecutive_meeting_pair(
        row0["effective_date"], row1["effective_date"], schedule
    ) is True


def test_skip_one_meeting_not_consecutive(schedule):
    row0 = schedule.iloc[0]
    row2 = schedule.iloc[2]
    assert consecutive_meeting_pair(
        row0["effective_date"], row2["effective_date"], schedule
    ) is False


def test_non_fomc_eff_returns_false(schedule):
    fake_eff = pd.Timestamp("2026-01-01")
    fake_mat = pd.Timestamp("2026-03-18")
    assert consecutive_meeting_pair(fake_eff, fake_mat, schedule) is False


def test_mat_equals_next_maturity_date_also_counts(schedule):
    """Effective-to-effective is the primary signal, but SDR may report
    maturity as the next meeting's maturity_date rather than its
    effective_date. Both should resolve to consecutive=True."""
    row0 = schedule.iloc[0]
    row1 = schedule.iloc[1]
    assert consecutive_meeting_pair(
        row0["effective_date"], row1["maturity_date"], schedule
    ) is True


def test_reversed_order_returns_false(schedule):
    row0 = schedule.iloc[0]
    row1 = schedule.iloc[1]
    assert consecutive_meeting_pair(
        row1["effective_date"], row0["effective_date"], schedule
    ) is False
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_fomc_consecutive_pair.py -v`
Expected: FAIL with `ImportError` / `AttributeError: module ... has no attribute 'consecutive_meeting_pair'`.

**Step 3: Implement `consecutive_meeting_pair`**

Add after `load_fomc_schedule` in [SDRUtils/analytics/fomc.py](SDRUtils/analytics/fomc.py):

```python
def consecutive_meeting_pair(
    effective_date: pd.Timestamp,
    maturity_date: pd.Timestamp,
    schedule_df: pd.DataFrame,
) -> bool:
    """Return True iff ``effective_date`` and ``maturity_date`` line up
    with two adjacent rows of the FOMC schedule.

    The schedule is assumed to be sorted by ``effective_date`` (as produced
    by :func:`load_fomc_schedule`). A pair is consecutive iff:

    - ``effective_date`` matches some row ``i``'s ``effective_date``, AND
    - ``maturity_date`` matches row ``i+1``'s ``effective_date`` OR row
      ``i``'s ``maturity_date`` (SDR trades report either).
    """
    if schedule_df is None or schedule_df.empty:
        return False
    eff = pd.to_datetime(effective_date, errors="coerce")
    mat = pd.to_datetime(maturity_date, errors="coerce")
    if pd.isna(eff) or pd.isna(mat):
        return False
    if mat <= eff:
        return False

    eff_dates = schedule_df["effective_date"].dt.normalize()
    mat_dates = schedule_df["maturity_date"].dt.normalize()
    eff_n = eff.normalize()
    mat_n = mat.normalize()

    match = eff_dates == eff_n
    if not match.any():
        return False
    i = match.idxmax()
    pos = schedule_df.index.get_loc(i)
    if pos + 1 >= len(schedule_df):
        return False
    next_eff = eff_dates.iloc[pos + 1]
    this_mat = mat_dates.iloc[pos]
    return bool(mat_n == next_eff or mat_n == this_mat)
```

**Step 4: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_fomc_consecutive_pair.py -v`
Expected: all five tests PASS (or SKIPPED if schedule is unavailable — that's acceptable in a sandbox env).

**Step 5: Commit**

```bash
git add SDRUtils/analytics/fomc.py tests/test_fomc_consecutive_pair.py
git commit -m "feat(analytics): add consecutive_meeting_pair helper for FOMC schedule"
```

---

## Task 2: `short_meeting_label` helper

**Files:**
- Modify: [SDRUtils/analytics/fomc.py](SDRUtils/analytics/fomc.py)
- Test: `tests/test_fomc_short_label.py` (new)

Context: `_CENTRAL_BANK_DATES` keys are already short forms like `"APR26"` (verified by [check_cb_dates.py](SDRUtils/dashboard/scripts/check_cb_dates.py)). But some upstream code mutates them to `"FOMC_APR2026"`. Centralize conversion.

**Step 1: Write the failing test**

Create `tests/test_fomc_short_label.py`:

```python
import pytest
from SDRUtils.analytics.fomc import short_meeting_label


@pytest.mark.parametrize("raw,expected", [
    ("APR26", "APR26"),
    ("FOMC_APR2026", "APR26"),
    ("FOMC APR2026", "APR26"),
    ("FOMC_20260428", "APR26"),   # date-based fallback
    ("", ""),
    (None, ""),
])
def test_short_meeting_label_formats(raw, expected):
    assert short_meeting_label(raw) == expected
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_fomc_short_label.py -v`
Expected: FAIL with ImportError.

**Step 3: Implement `short_meeting_label`**

Add to [SDRUtils/analytics/fomc.py](SDRUtils/analytics/fomc.py):

```python
import re
from datetime import datetime


_MONTH_ABBR = ("JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC")


def short_meeting_label(raw: str | None) -> str:
    """Normalize an FOMC meeting label to the compact 'MMMYY' form.

    Accepts 'APR26', 'FOMC_APR2026', 'FOMC APR2026', 'FOMC_20260428'.
    Returns '' for None/empty.
    """
    if not raw:
        return ""
    s = str(raw).strip().upper()
    if not s:
        return ""
    s = s.replace("FOMC_", "").replace("FOMC ", "").strip()

    # Already short form: MMMYY
    if re.fullmatch(r"[A-Z]{3}\d{2}", s):
        return s

    # MMMYYYY
    m = re.fullmatch(r"([A-Z]{3})(\d{4})", s)
    if m:
        return f"{m.group(1)}{m.group(2)[2:]}"

    # YYYYMMDD
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return f"{_MONTH_ABBR[dt.month-1]}{dt.year % 100:02d}"
        except ValueError:
            return ""

    return ""
```

**Step 4: Run tests**

Run: `conda run -n stir pytest tests/test_fomc_short_label.py -v`
Expected: all parametrized tests PASS.

**Step 5: Commit**

```bash
git add SDRUtils/analytics/fomc.py tests/test_fomc_short_label.py
git commit -m "feat(analytics): add short_meeting_label normalizer"
```

---

## Task 3: Rewrite `detect_special_tenor` with 3-tier priority

**Files:**
- Modify: [SDRUtils/core/tenors.py:337-378](SDRUtils/core/tenors.py:337)
- Test: `tests/test_detect_special_tenor_priority.py` (new)

**Step 1: Write the failing test**

Create `tests/test_detect_special_tenor_priority.py`:

```python
"""Priority tests for detect_special_tenor.

Priority order (highest first):
  1. Consecutive FOMC meetings on both eff and mat => FOMC
  2. Quarterly IMM effective + constant-maturity tenor => IMM
  3. FOMC effective + (non-consecutive FOMC OR constant-tenor) mat => FOMC
  else => STANDARD

Especially critical: when eff is both an IMM quarterly AND an FOMC meeting
(dates coincide), and mat is constant tenor, tier 2 wins => IMM.
"""
import pandas as pd
import pytest

from SDRUtils.core.tenors import detect_special_tenor


# Fixture FOMC meeting pair: Apr 2026 and Jun 2026 (typical spacing).
# Real schedule values should come from load_fomc_schedule in integration
# tests; here we monkeypatch for unit isolation.
APR_EFF = pd.Timestamp("2026-04-28")
APR_MAT = pd.Timestamp("2026-06-16")   # next meeting eff
JUN_EFF = pd.Timestamp("2026-06-16")
JUN_MAT = pd.Timestamp("2026-07-28")
DEC_EFF = pd.Timestamp("2026-12-15")

IMM_Z26 = pd.Timestamp("2026-12-16")  # 3rd Wed of Dec 2026 = IMM Z26


def _patch_fomc(monkeypatch, meeting_dates):
    """Force get_fomc_label to return a label for dates in ``meeting_dates``."""
    def _fake(dt):
        if dt is None:
            return None
        ts = pd.to_datetime(dt, errors="coerce")
        if pd.isna(ts):
            return None
        return f"FOMC_{ts.strftime('%Y%m%d')}" if ts.normalize() in meeting_dates else None
    monkeypatch.setattr("SDRUtils.core.tenors.get_fomc_label", _fake)


def test_tier1_consecutive_fomc_both(monkeypatch):
    _patch_fomc(monkeypatch, {APR_EFF.normalize(), APR_MAT.normalize()})
    kind, conf, tags = detect_special_tenor(
        tenor_label="~2M",
        forward_label="spot",
        effective_date=APR_EFF,
        expiration_date=APR_MAT,
        is_forward=False,
    )
    assert kind == "FOMC"
    assert "FOMC" in tags


def test_tier2_imm_quarterly_plus_constant_tenor_wins(monkeypatch):
    # eff is IMM quarterly (Z26). Not an FOMC meeting in this fixture.
    _patch_fomc(monkeypatch, set())
    kind, conf, tags = detect_special_tenor(
        tenor_label="10Y",
        forward_label="IMM_Z2026",
        effective_date=IMM_Z26,
        expiration_date=pd.Timestamp("2036-12-16"),
        is_forward=True,
    )
    assert kind == "IMM"


def test_tier2_wins_over_tier3_when_eff_is_both_imm_and_fomc(monkeypatch):
    # IMM_Z26 happens to coincide with an FOMC meeting; mat is constant 10Y.
    # Must resolve to IMM (tier 2), not FOMC (tier 3).
    _patch_fomc(monkeypatch, {IMM_Z26.normalize()})
    kind, conf, tags = detect_special_tenor(
        tenor_label="10Y",
        forward_label="IMM_Z2026",
        effective_date=IMM_Z26,
        expiration_date=pd.Timestamp("2036-12-16"),
        is_forward=True,
    )
    assert kind == "IMM"


def test_tier3_fomc_eff_constant_tenor_mat(monkeypatch):
    # Apr 2026 FOMC is not a quarterly IMM month.
    _patch_fomc(monkeypatch, {APR_EFF.normalize()})
    kind, conf, tags = detect_special_tenor(
        tenor_label="10Y",
        forward_label="spot",
        effective_date=APR_EFF,
        expiration_date=pd.Timestamp("2036-04-28"),
        is_forward=True,
    )
    assert kind == "FOMC"


def test_tier3_fomc_eff_nonconsecutive_fomc_mat(monkeypatch):
    _patch_fomc(monkeypatch, {APR_EFF.normalize(), DEC_EFF.normalize()})
    # Note: our tier1 check requires consecutive — patching
    # consecutive_meeting_pair to False would be cleaner, but the tier
    # resolver uses get_fomc_label presence only. Full consecutive logic
    # is exercised by the trade_tape-level tests.
    kind, _, tags = detect_special_tenor(
        tenor_label="FOMC_20261215",
        forward_label="spot",
        effective_date=APR_EFF,
        expiration_date=DEC_EFF,
        is_forward=True,
    )
    assert kind == "FOMC"


def test_standard_when_no_rules_match(monkeypatch):
    _patch_fomc(monkeypatch, set())
    kind, _, _ = detect_special_tenor(
        tenor_label="10Y",
        forward_label="spot",
        effective_date=pd.Timestamp("2026-04-15"),
        expiration_date=pd.Timestamp("2036-04-15"),
        is_forward=False,
    )
    assert kind == "STANDARD"
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_detect_special_tenor_priority.py -v`
Expected: FAIL — existing logic gives FOMC priority over IMM even in the tier 2 coincidence case.

**Step 3: Rewrite `detect_special_tenor`**

Replace lines 337-378 in [SDRUtils/core/tenors.py](SDRUtils/core/tenors.py:337) with:

```python
def detect_special_tenor(
    tenor_label: str,
    forward_label: str,
    effective_date: Optional[pd.Timestamp],
    expiration_date: Optional[pd.Timestamp],
    is_forward: bool,
) -> tuple[str, str, list[str]]:
    """Classify special tenor with strict 3-tier priority.

    Priority (highest first):
      1. Both ``effective_date`` AND ``expiration_date`` land on FOMC
         meeting dates  => FOMC (tags=["FOMC"]).
      2. ``effective_date`` is a quarterly IMM date (H/M/U/Z) and the
         maturity side is a constant-maturity tenor (no IMM_/FOMC_
         prefix on tenor_label)  => IMM (tags=["IMM"]).
      3. ``effective_date`` is an FOMC meeting date and the maturity
         side is either constant tenor OR another FOMC meeting date
         (non-consecutive — tier 1 already handled consecutive)
         => FOMC (tags=["FOMC"]).
      else => STANDARD.

    This supersedes the legacy FOMC > IMM tag-priority rule. IMM and FOMC
    dates coincide on quarterly meetings; the old rule flipped quarterly
    IMM trades to FOMC erroneously.
    """
    eff_is_fomc = effective_date is not None and get_fomc_label(effective_date) is not None
    mat_is_fomc = expiration_date is not None and get_fomc_label(expiration_date) is not None
    eff_is_imm_q = effective_date is not None and get_imm_label(effective_date) is not None

    tenor_is_constant = not (
        tenor_label.startswith("IMM_") or tenor_label.startswith("FOMC_")
    )

    # Tier 1 — FOMC-to-FOMC (both dates are meetings).
    if eff_is_fomc and mat_is_fomc:
        return "FOMC", "high", ["FOMC"]

    # Tier 2 — quarterly IMM eff + constant-tenor mat.
    if eff_is_imm_q and tenor_is_constant:
        return "IMM", "high", ["IMM"]

    # Tier 3 — FOMC eff with non-consecutive FOMC mat or constant-tenor mat.
    if eff_is_fomc and (tenor_is_constant or mat_is_fomc):
        return "FOMC", "high", ["FOMC"]

    # Label-based fallback (matches legacy behaviour for edge cases where
    # tenor_to_label already baked in IMM_/FOMC_ but dates don't resolve).
    if tenor_label.startswith("IMM_") or forward_label.startswith("IMM_"):
        return "IMM", "medium", ["IMM"]
    if tenor_label.startswith("FOMC_") or forward_label.startswith("FOMC_"):
        return "FOMC", "medium", ["FOMC"]

    return "STANDARD", "high", []
```

**Step 4: Run tests**

Run: `conda run -n stir pytest tests/test_detect_special_tenor_priority.py tests/test_special_tenor_classification.py -v`
Expected: new priority tests PASS; existing tests still PASS.

**Step 5: Commit**

```bash
git add SDRUtils/core/tenors.py tests/test_detect_special_tenor_priority.py
git commit -m "fix(tenors): 3-tier priority for FOMC/IMM special-tenor detection"
```

---

## Task 4: Tier-aware `_assign_meeting` in `_enrich_context`

**Files:**
- Modify: [SDRUtils/analytics/trade_tape.py:704-717](SDRUtils/analytics/trade_tape.py:704)
- Test: `tests/test_trade_tape_fomc_label.py` (new)

This reshapes the `fomc_meeting_label` column so it stores:
- `"APR26"` for tier-1 consecutive (short-hand used downstream by `_build_enriched_label`)
- `""` for tier-2 IMM (so `_build_enriched_label` falls into the forward+tenor branch that prints `IMM_Z2026 10Y`)
- `"APR26"` or `"APR26 DEC26"` for tier 3

**Step 1: Write the failing test**

Create `tests/test_trade_tape_fomc_label.py`:

```python
"""End-to-end labeling tests against the 3-tier priority.

Feeds hand-built DataFrames through TradeTape._enrich_context and
_build_enriched_label and asserts the final ``tape_label`` string.
"""
import pandas as pd
import pytest

from SDRUtils.analytics.trade_tape import TradeTape


@pytest.fixture
def base_row():
    return {
        "trade_id": "T1",
        "execution_timestamp": pd.Timestamp("2026-03-15 14:30:00", tz="UTC"),
        "product_type": "OIS_SWAP",
        "upi_underlier_name": "USD-SOFR-COMPOUND 1D",
        "upi_reset_freq": "1D",
        "upi_notional_schedule": "Constant",
        "upi_delivery_type": "PHYS",
        "trade_type": "OUTRIGHT",
        "package_type": "OUTRIGHT",
        "forward_label": "spot",
        "forward_start_years": 0.0,
        "tenor_label": "10Y",
        "tenor_display": "10Y",
        "package_tenors": "10Y",
        "cleared": "Y",
        "special_tenor_type": "STANDARD",
        "effective_date": pd.Timestamp("2026-03-18"),
        "expiration_date": pd.Timestamp("2036-03-18"),
        "is_unwind": False,
        "is_mac": False,
        "is_ufro": False,
        "is_block": False,
    }


def _compute(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    # Run only the enrichment stages we care about. The public entry point
    # is .compute(), but we want isolated assertions; call the internal
    # layers in order. If signature changes, update here.
    out = tape._enrich_context(df.copy())
    out = tape._build_enriched_label(out)
    return out


def test_tier1_consecutive_fomc_produces_short_label(base_row, monkeypatch):
    """eff=2026-04-28 (Apr26 FOMC), mat=2026-06-16 (next meeting eff=Jun26).
    Expect: 'FOMC APR26' in tape_label, no 10Y suffix."""
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-04-28"),
        "expiration_date": pd.Timestamp("2026-06-16"),
        "tenor_label": "~2M",
        "tenor_display": "~2M",
        "package_tenors": "~2M",
        "special_tenor_type": "FOMC",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == "APR26"
    assert "FOMC APR26" in out.loc[0, "tape_label"]
    # Short-hand: no trailing tenor on consecutive-FOMC trades
    assert "10Y" not in out.loc[0, "tape_label"]


def test_tier2_imm_quarterly_constant_tenor(base_row):
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-12-16"),  # IMM Z26
        "expiration_date": pd.Timestamp("2036-12-16"),
        "forward_label": "IMM_Z2026",
        "forward_start_years": 0.67,
        "special_tenor_type": "IMM",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == ""
    label = out.loc[0, "tape_label"]
    assert "IMM_Z2026" in label
    assert "10Y" in label
    assert "FOMC" not in label


def test_tier3_fomc_eff_constant_tenor(base_row):
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-04-28"),  # Apr26 FOMC, not IMM-Q
        "expiration_date": pd.Timestamp("2036-04-28"),
        "forward_label": "FOMC_APR2026",
        "special_tenor_type": "FOMC",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == "APR26"
    label = out.loc[0, "tape_label"]
    assert "FOMC APR26" in label
    assert "10Y" in label


def test_tier3_fomc_to_fomc_nonconsecutive(base_row):
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-04-28"),
        "expiration_date": pd.Timestamp("2026-12-15"),  # Dec26 FOMC — skip
        "tenor_label": "FOMC_20261215",
        "tenor_display": "FOMC_20261215",
        "package_tenors": "FOMC_20261215",
        "special_tenor_type": "FOMC",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == "APR26 DEC26"
    assert "FOMC APR26 DEC26" in out.loc[0, "tape_label"]
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_trade_tape_fomc_label.py -v`
Expected: most cases FAIL — current `_assign_meeting` returns the full `FOMC_APR2026` for tier-3-style matches and assigns a label to IMM-quarterly trades it shouldn't.

**Step 3: Rewrite `_assign_meeting` and its caller**

Replace lines 704-717 in [SDRUtils/analytics/trade_tape.py](SDRUtils/analytics/trade_tape.py:704) with a tier-aware formatter. Import helpers at top of module:

```python
from SDRUtils.analytics.fomc import (
    load_fomc_schedule,
    consecutive_meeting_pair,
    short_meeting_label,
)
from SDRUtils.core.tenors import get_imm_label
```

Then inside `_enrich_context`, replace the current `_assign_meeting` body (lines 704-717) and the subsequent `df.loc[fomc_mask, "fomc_meeting_label"] = ...` call (lines 719-721):

```python
                    schedule = schedule  # from load_fomc_schedule() above

                    def _assign_meeting(row):
                        eff = pd.to_datetime(row.get("effective_date"))
                        mat = pd.to_datetime(row.get("expiration_date"))
                        if pd.isna(eff) or pd.isna(mat):
                            return ""
                        eff_date = eff.date()
                        mat_date = mat.date()
                        eff_lbl_raw = eff_to_label.get(eff_date)
                        mat_lbl_raw = mat_to_label.get(mat_date)

                        # Tier 1 — consecutive FOMC meetings.
                        if eff_lbl_raw and mat_lbl_raw and consecutive_meeting_pair(
                            eff, mat, schedule
                        ):
                            return short_meeting_label(eff_lbl_raw)

                        # Tier 2 — quarterly IMM eff + constant-tenor mat.
                        # Return empty string; downstream _build_enriched_label
                        # will then print "IMM_Z2026 10Y" via the forward+tenor
                        # branch.
                        if get_imm_label(eff) is not None and not mat_lbl_raw:
                            tenor_label = str(row.get("tenor_label", ""))
                            if not (
                                tenor_label.startswith("IMM_")
                                or tenor_label.startswith("FOMC_")
                            ):
                                return ""

                        # Tier 3a — FOMC eff + FOMC mat but non-consecutive.
                        if eff_lbl_raw and mat_lbl_raw:
                            return (
                                short_meeting_label(eff_lbl_raw)
                                + " "
                                + short_meeting_label(mat_lbl_raw)
                            )

                        # Tier 3b — FOMC eff + constant-tenor mat.
                        if eff_lbl_raw:
                            return short_meeting_label(eff_lbl_raw)

                        # Fallback: mat is FOMC but eff isn't — rare; don't
                        # re-label (keeps prior behaviour for pathological
                        # inputs).
                        return ""

                    # Broaden the mask — tier rules consume eff AND mat, so we
                    # can't rely on the upstream `special_tenor_type == FOMC`
                    # gate alone (it was bugged — see detect_special_tenor).
                    candidate_mask = (
                        df["effective_date"].map(lambda d: eff_to_label.get(
                            pd.to_datetime(d).date() if pd.notna(pd.to_datetime(d)) else None
                        ))
                        .notna()
                    ) | fomc_mask

                    df.loc[candidate_mask, "fomc_meeting_label"] = (
                        df[candidate_mask].apply(_assign_meeting, axis=1)
                    )
```

**Step 4: Run tests**

Run: `conda run -n stir pytest tests/test_trade_tape_fomc_label.py -v`
Expected: all four tests PASS.

Then smoke-test the wider trade-tape suite:

Run: `conda run -n stir pytest tests/test_trade_tape_on_fixture.py -v`
Expected: still passes (no regression).

**Step 5: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py tests/test_trade_tape_fomc_label.py
git commit -m "fix(trade_tape): tier-aware fomc_meeting_label via consecutive/short helpers"
```

---

## Task 5: `require_same_upi` in `curve.py`

**Files:**
- Modify: [SDRUtils/packages/curve.py:10-93](SDRUtils/packages/curve.py:10)
- Test: `tests/test_curve_upi_gate.py` (new)

**Step 1: Write the failing test**

Create `tests/test_curve_upi_gate.py`:

```python
"""Hard UPI gate on curve detection.

Two trades that are otherwise a valid curve pair but carry distinct
``Unique Product Identifier`` strings MUST NOT be grouped.
"""
import pandas as pd
import pytest

from SDRUtils.packages.curve import detect_curve_trades_df


def _mk_pair(upi_a: str, upi_b: str) -> pd.DataFrame:
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    return pd.DataFrame([
        {
            "trade_id": "A",
            "execution_timestamp": base,
            "product_type": "OIS_SWAP",
            "package_type": "OUTRIGHT",
            "estimated_pv01": 45_000.0,
            "tenor_label": "5Y",
            "notional_currency": "USD",
            "effective_date": pd.Timestamp("2026-04-17"),
            "forward_label": "spot",
            "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
            "Platform identifier": "TW",
            "Cleared": "Y",
            "Unique Product Identifier": upi_a,
        },
        {
            "trade_id": "B",
            "execution_timestamp": base + pd.Timedelta(seconds=15),
            "product_type": "OIS_SWAP",
            "package_type": "OUTRIGHT",
            "estimated_pv01": 46_000.0,
            "tenor_label": "10Y",
            "notional_currency": "USD",
            "effective_date": pd.Timestamp("2026-04-17"),
            "forward_label": "spot",
            "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
            "Platform identifier": "TW",
            "Cleared": "Y",
            "Unique Product Identifier": upi_b,
        },
    ])


def test_same_upi_bundles_into_curve():
    df = _mk_pair("QZF08M5TR8H3", "QZF08M5TR8H3")
    out = detect_curve_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "CURVE").all()
    assert out["package_id"].nunique(dropna=True) == 1


def test_distinct_upi_stays_outright():
    df = _mk_pair("QZF08M5TR8H3", "DIFFERENTUPIABC")
    out = detect_curve_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "OUTRIGHT").all()


def test_upi_gate_off_allows_distinct_upi():
    """Back-compat: setting require_same_upi=False restores prior behavior."""
    df = _mk_pair("QZF08M5TR8H3", "DIFFERENTUPIABC")
    out = detect_curve_trades_df(df, require_same_upi=False)
    assert (out["package_type"] == "CURVE").any()
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_curve_upi_gate.py -v`
Expected: `test_distinct_upi_stays_outright` FAILS — current detector bundles them.

**Step 3: Add UPI gate**

Edit [SDRUtils/packages/curve.py:10](SDRUtils/packages/curve.py:10) to add two new parameters to `detect_curve_trades_df` signature:

```python
    require_same_upi: bool = True,
    upi_col: str = "Unique Product Identifier",
```

Then, alongside the existing `require_same_underlier` block (around [line 83-84](SDRUtils/packages/curve.py:83)), add:

```python
    if require_same_upi and upi_col in out.columns:
        cols.append(upi_col)
```

And extend the econ-guard array preparation (around [line 116](SDRUtils/packages/curve.py:116)):

```python
    upi = (
        cand[upi_col].astype("string").to_numpy()
        if (require_same_upi and upi_col in cand.columns)
        else None
    )
```

And in `_econ_ok` (around [line 143-162](SDRUtils/packages/curve.py:143)), add right after the `und` check:

```python
        if upi is not None and upi[i] != upi[j]:
            return False
```

**Step 4: Run tests**

Run: `conda run -n stir pytest tests/test_curve_upi_gate.py -v`
Expected: all three tests PASS.

Regression: run the wider curve test suite.

Run: `conda run -n stir pytest tests/test_swap_curve_rv.py tests/test_curve_tag_config.py -v`
Expected: pass (these test curve *analytics* — should be unaffected).

**Step 5: Commit**

```bash
git add SDRUtils/packages/curve.py tests/test_curve_upi_gate.py
git commit -m "fix(packages): require identical UPI for curve leg pairing"
```

---

## Task 6: `require_same_upi` in `fly.py`

**Files:**
- Modify: [SDRUtils/packages/fly.py:10-97](SDRUtils/packages/fly.py:10) (two locations — `_run_pass` reruns the econ-guard)
- Test: `tests/test_fly_upi_gate.py` (new)

**Step 1: Write the failing test**

Create `tests/test_fly_upi_gate.py`:

```python
"""Hard UPI gate on fly detection."""
import pandas as pd

from SDRUtils.packages.fly import detect_fly_trades_df


def _mk_fly(upi_mid: str):
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    return pd.DataFrame([
        # 5Y wing
        {"trade_id": "A", "execution_timestamp": base, "product_type": "OIS_SWAP",
         "package_type": "OUTRIGHT", "estimated_pv01": 22_500.0,
         "tenor_label": "5Y", "tenor_years": 5.0,
         "notional_currency": "USD", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
         "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": "QZF08M5TR8H3"},
        # 7Y belly
        {"trade_id": "B", "execution_timestamp": base + pd.Timedelta(seconds=10),
         "product_type": "OIS_SWAP", "package_type": "OUTRIGHT",
         "estimated_pv01": 45_000.0,
         "tenor_label": "7Y", "tenor_years": 7.0,
         "notional_currency": "USD", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
         "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi_mid},
        # 10Y wing
        {"trade_id": "C", "execution_timestamp": base + pd.Timedelta(seconds=20),
         "product_type": "OIS_SWAP", "package_type": "OUTRIGHT",
         "estimated_pv01": 22_500.0,
         "tenor_label": "10Y", "tenor_years": 10.0,
         "notional_currency": "USD", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
         "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": "QZF08M5TR8H3"},
    ])


def test_same_upi_fly_is_detected():
    df = _mk_fly("QZF08M5TR8H3")
    out = detect_fly_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "FLY").sum() == 3


def test_belly_different_upi_not_a_fly():
    df = _mk_fly("DIFFERENTUPIABC")
    out = detect_fly_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "FLY").sum() == 0
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_fly_upi_gate.py -v`
Expected: `test_belly_different_upi_not_a_fly` FAILS.

**Step 3: Add UPI gate to fly.py**

Edit [SDRUtils/packages/fly.py:10](SDRUtils/packages/fly.py:10) signature — add before the closing `) -> pd.DataFrame:`:

```python
    require_same_upi: bool = True,
    upi_col: str = "Unique Product Identifier",
```

Inside `_run_pass`, alongside the existing `require_same_underlier` line (around [line 88-89](SDRUtils/packages/fly.py:88)):

```python
        if require_same_upi and upi_col in out.columns:
            cols.append(upi_col)
```

In the array-prep block ([line 117-134](SDRUtils/packages/fly.py:117)):

```python
        upi = cand[upi_col].astype("string").to_numpy() if (require_same_upi and upi_col in cand.columns) else None
```

And in `_econ_ok` ([line 183-202](SDRUtils/packages/fly.py:183)), after the `und` check:

```python
            if upi is not None and upi[i] != upi[j]:
                return False
```

**Step 4: Run tests**

Run: `conda run -n stir pytest tests/test_fly_upi_gate.py -v`
Expected: both tests PASS.

**Step 5: Commit**

```bash
git add SDRUtils/packages/fly.py tests/test_fly_upi_gate.py
git commit -m "fix(packages): require identical UPI for fly leg bundling"
```

---

## Task 7: `require_same_upi` in `basis.py`

**Files:**
- Modify: [SDRUtils/packages/basis.py:28-183](SDRUtils/packages/basis.py:28)
- Test: `tests/test_basis_upi_gate.py` (new)

Note: basis packages group basis swaps across tenors (e.g. 2Y SOFR/FF + 10Y SOFR/FF). The raw SDR UPI is the same when the basis pair is the same, so the gate is valid.

**Step 1: Write the failing test**

Create `tests/test_basis_upi_gate.py`:

```python
"""Hard UPI gate on basis-package detection."""
import pandas as pd

from SDRUtils.packages.basis import detect_basis_packages_df


def _mk_basis_pair(upi_a: str, upi_b: str):
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    return pd.DataFrame([
        {"trade_id": "A", "execution_timestamp": base,
         "package_type": "OUTRIGHT", "basis_type": "SOFR_FF",
         "tenor_label": "2Y", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi_a},
        {"trade_id": "B", "execution_timestamp": base + pd.Timedelta(seconds=20),
         "package_type": "OUTRIGHT", "basis_type": "SOFR_FF",
         "tenor_label": "10Y", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi_b},
    ])


def test_same_upi_bundles_basis_curve():
    df = _mk_basis_pair("BSISSAME001", "BSISSAME001")
    out = detect_basis_packages_df(df, require_same_upi=True)
    assert (out["package_type"] == "BASIS_CURVE").sum() == 2


def test_distinct_upi_leaves_outrights():
    df = _mk_basis_pair("BSISSAME001", "DIFFERENTBASI")
    out = detect_basis_packages_df(df, require_same_upi=True)
    assert (out["package_type"] == "OUTRIGHT").all()
```

**Step 2: Run test**

Run: `conda run -n stir pytest tests/test_basis_upi_gate.py -v`
Expected: `test_distinct_upi_leaves_outrights` FAILS.

**Step 3: Add UPI gate to basis.py**

Edit [SDRUtils/packages/basis.py:28](SDRUtils/packages/basis.py:28) signature — add parameters:

```python
    require_same_upi: bool = True,
    upi_col: str = "Unique Product Identifier",
```

After the array-prep block (around [line 85-91](SDRUtils/packages/basis.py:85)):

```python
    upi = (
        cand[upi_col].astype("string").to_numpy()
        if (require_same_upi and upi_col in cand.columns)
        else None
    )
```

Extend the `_match_ok` function (find it at [line 100-108 of basis.py](SDRUtils/packages/basis.py:100) — it uses `eff`, `fwd`, `plat`, `clr` to gate pairs). Add after the `clr` check:

```python
        if upi is not None and upi[i] != upi[j]:
            return False
```

**Step 4: Run tests**

Run: `conda run -n stir pytest tests/test_basis_upi_gate.py tests/test_basis_packages.py -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add SDRUtils/packages/basis.py tests/test_basis_upi_gate.py
git commit -m "fix(packages): require identical UPI for basis-package bundling"
```

---

## Task 8: UPI safety-net validator in `TradeTape._enrich_packages`

**Files:**
- Modify: [SDRUtils/analytics/trade_tape.py:580-669](SDRUtils/analytics/trade_tape.py:580)
- Test: `tests/test_trade_tape_upi_validator.py` (new)

Rationale: detector-level gate (Tasks 5-7) won't catch packages that arrive already-tagged via the SDR-native `Package indicator` column. This validator runs AFTER leg resolution and un-packages any multi-leg group whose legs don't share a UPI.

**Step 1: Write the failing test**

Create `tests/test_trade_tape_upi_validator.py`:

```python
"""Safety-net UPI validator in TradeTape._enrich_packages.

An SDR-native package (package_indicator=True, package_type set upstream,
package_legs populated) whose legs have heterogeneous UPIs must be
un-packaged back to OUTRIGHT.
"""
import pandas as pd

from SDRUtils.analytics.trade_tape import TradeTape


def _mk_spurious_curve(upi_a: str, upi_b: str) -> pd.DataFrame:
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    rows = [
        {"trade_id": "A", "execution_timestamp": base,
         "product_type": "OIS_SWAP", "package_type": "CURVE",
         "package_id": "SPURIOUS_1", "package_legs": ["A", "B"],
         "package_indicator": True,
         "tenor_label": "5Y", "tenor_years": 5.0, "tenor_display": "5Y",
         "notional_currency": "USD",
         "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "trade_type": "CURVE",
         "Unique Product Identifier": upi_a,
         "unique_product_identifier": upi_a},
        {"trade_id": "B", "execution_timestamp": base + pd.Timedelta(seconds=10),
         "product_type": "OIS_SWAP", "package_type": "CURVE",
         "package_id": "SPURIOUS_1", "package_legs": ["A", "B"],
         "package_indicator": True,
         "tenor_label": "10Y", "tenor_years": 10.0, "tenor_display": "10Y",
         "notional_currency": "USD",
         "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "trade_type": "CURVE",
         "Unique Product Identifier": upi_b,
         "unique_product_identifier": upi_b},
    ]
    return pd.DataFrame(rows)


def test_heterogeneous_upi_gets_unpackaged():
    df = _mk_spurious_curve("QZF08M5TR8H3", "DIFFERENTUPIABC")
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert (out["package_type"].str.upper() == "OUTRIGHT").all()
    assert out["is_package"].eq(False).all()


def test_homogeneous_upi_survives():
    df = _mk_spurious_curve("QZF08M5TR8H3", "QZF08M5TR8H3")
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert (out["package_type"].str.upper() == "CURVE").all()
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_trade_tape_upi_validator.py -v`
Expected: `test_heterogeneous_upi_gets_unpackaged` FAILS — current `_enrich_packages` passes through whatever `package_type` was set upstream.

**Step 3: Add validator in `_enrich_packages`**

Inside `_enrich_packages` ([SDRUtils/analytics/trade_tape.py:580](SDRUtils/analytics/trade_tape.py:580)), after the existing leg-resolution loop (the `for pos in pkg_positions:` block around [lines 626-647](SDRUtils/analytics/trade_tape.py:626)) but BEFORE the `if valid_indices:` write-back, add:

```python
            # --- UPI validator (safety net) -------------------------------
            upi_col_raw = "Unique Product Identifier"
            upi_col_snake = "unique_product_identifier"
            upi_col = (
                upi_col_raw if upi_col_raw in df.columns else
                upi_col_snake if upi_col_snake in df.columns else None
            )
            if upi_col is not None:
                upi_arr = df[upi_col].astype(str).to_numpy()
                to_unpackage: list = []
                for pos in pkg_positions:
                    legs = legs_arr[pos]
                    if legs is None or (isinstance(legs, float) and pd.isna(legs)):
                        continue
                    try:
                        leg_ids = [str(x) for x in legs]
                    except (TypeError, ValueError):
                        continue
                    leg_positions = [tid_to_pos[lid] for lid in leg_ids if lid in tid_to_pos]
                    if len(leg_positions) < 2:
                        continue
                    leg_upis = {upi_arr[p] for p in leg_positions if upi_arr[p] and upi_arr[p] != "nan"}
                    if len(leg_upis) > 1:
                        to_unpackage.extend(df_indices[p] for p in leg_positions)

                if to_unpackage:
                    # Idempotent: set back to OUTRIGHT and clear package refs.
                    df.loc[to_unpackage, "package_type"] = "OUTRIGHT"
                    if "package_id" in df.columns:
                        df.loc[to_unpackage, "package_id"] = None
                    if "package_legs" in df.columns:
                        df.loc[to_unpackage, "package_legs"] = None
                    df.loc[to_unpackage, "is_package"] = False
                    if "trade_type" in df.columns:
                        df.loc[to_unpackage, "trade_type"] = "OUTRIGHT"
                    # Recompute is_package mask so the rest of this method
                    # (tenor join, structure label) respects the un-package.
                    pkg = df["package_type"].astype(str).fillna("").str.upper()
                    df["is_package"] = ~pkg.isin({"", "OUTRIGHT", "NAN", "NONE"})
                    # Mark newly-outright legs out of the pkg_positions set so
                    # the remainder of the method (package_structure build) skips them.
                    pkg_positions = pkg_positions[~np.isin(
                        pkg_positions,
                        np.array([tid_to_pos[str(df.loc[idx, "trade_id"])] for idx in to_unpackage]),
                    )]
```

**Step 4: Run tests**

Run: `conda run -n stir pytest tests/test_trade_tape_upi_validator.py tests/test_trade_tape_on_fixture.py -v`
Expected: new tests PASS; existing fixture tests still PASS.

**Step 5: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py tests/test_trade_tape_upi_validator.py
git commit -m "fix(trade_tape): un-package multi-leg groups with heterogeneous UPIs"
```

---

## Task 9: Full-suite regression

**Files:**
- None (verification only)

**Step 1: Run the relevant test suite**

Run: `conda run -n stir pytest tests/ -k "tape or tenor or fomc or curve or fly or basis or package" -v --maxfail=10`
Expected: all green. If anything new fails, triage before proceeding.

**Step 2: Run type check (if mypy/pyright configured)**

Inspect for a mypy config. If one exists:
Run: `conda run -n stir mypy SDRUtils/core/tenors.py SDRUtils/analytics/trade_tape.py SDRUtils/analytics/fomc.py SDRUtils/packages/curve.py SDRUtils/packages/fly.py SDRUtils/packages/basis.py`
Expected: no new errors. If no config exists, skip.

**Step 3: Sample-data smoke test**

```python
# scripts/smoke_test_fomc_upi.py (temporary, don't commit)
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
from notebooks.sdr._usd_swaps_common import load_usd_swaps
from datetime import datetime, timezone, timedelta

start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
end = start + timedelta(days=1)
classified, raw_df = load_usd_swaps(start=start, end=end, return_raw=True)
tape = TradeTape(df=classified, raw_df=raw_df).compute(use_cache=False)

print("Label-count diff:")
print(tape["fomc_meeting_label"].value_counts(dropna=False).head(20))
print("\nPackage-type distribution:")
print(tape["package_type"].value_counts(dropna=False))
print("\nSample FOMC labels:")
print(tape[tape["fomc_meeting_label"] != ""][["trade_id", "effective_date", "expiration_date", "fomc_meeting_label", "tape_label"]].head(20))
```

Run: `conda run -n stir python scripts/smoke_test_fomc_upi.py` (only if a local SDR cache is available).
Expected: IMM quarterly trades have `fomc_meeting_label == ""`; consecutive-FOMC trades show `APR26`-style labels; no package rows where legs have different UPIs.

**Step 4: Commit if anything tweaked during regression**

Only commit if something needed a touchup during the regression pass.

---

## Summary of files touched

- `SDRUtils/analytics/fomc.py` — +`consecutive_meeting_pair`, +`short_meeting_label`.
- `SDRUtils/core/tenors.py` — rewrote `detect_special_tenor` with 3-tier priority.
- `SDRUtils/analytics/trade_tape.py` — tier-aware `_assign_meeting` in `_enrich_context`; UPI validator in `_enrich_packages`.
- `SDRUtils/packages/curve.py` — `require_same_upi` parameter.
- `SDRUtils/packages/fly.py` — `require_same_upi` parameter.
- `SDRUtils/packages/basis.py` — `require_same_upi` parameter.
- `tests/` — 7 new test files (TDD-driven).

## Rollback

Each task has its own commit; revert commits in reverse order (`git revert <hash>`) to undo selectively. No schema changes → no migration to roll back.
