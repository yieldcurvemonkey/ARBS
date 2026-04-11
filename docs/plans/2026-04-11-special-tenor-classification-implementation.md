# Special Tenor Classification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add unified `special_tenor_type` / `special_tenor_confidence` / `special_tenor_tags` fields to `SwapTradeClassification` with two-phase detection (intrinsic IMM/FOMC during classification, enrichment MMS/invoice/MAC post-classification), priority hierarchy, and round-notional confidence filter.

**Architecture:** Phase 1 (intrinsic) runs inside `classify_usd_swap_trade()` using only the trade's own dates. Phase 2 (enrichment) runs as existing batch detectors on the DataFrame. A final `_resolve_special_tenor_priority()` merges all results into the unified fields with `INVOICE_SWAP > MATCHED_MATURITY > MAC > FOMC > IMM > STANDARD` priority.

**Tech Stack:** Python 3.13, pandas, QuantLib, pytest

---

### Task 1: Add Type Literals and Priority Constant to Config

**Files:**
- Modify: `SDRUtils/core/classification.py:29-40` (add new Literal types after existing ProductType)
- Modify: `SDRUtils/config.py:285` (add priority constant after PACKAGE_TYPES)

**Step 1: Add SpecialTenorType and SpecialTenorConfidence literals to classification.py**

In `SDRUtils/core/classification.py`, after line 40 (after the `ProductType` literal), add:

```python
SpecialTenorType = Literal[
    "STANDARD",
    "IMM",
    "FOMC",
    "MATCHED_MATURITY",
    "INVOICE_SWAP",
    "MAC",
]

SpecialTenorConfidence = Literal["high", "medium", "low"]
```

**Step 2: Add SPECIAL_TENOR_PRIORITY to config.py**

In `SDRUtils/config.py`, after line 285 (after `PACKAGE_TYPES = PackageTypeMapping()`), add:

```python
# Priority order for special tenor resolution (lowest to highest).
# When multiple types match, the highest-priority type wins as primary.
SPECIAL_TENOR_PRIORITY: list[str] = [
    "STANDARD",
    "IMM",
    "FOMC",
    "MAC",
    "MATCHED_MATURITY",
    "INVOICE_SWAP",
]
```

**Step 3: Verify imports work**

Run: `python -c "from SDRUtils.core.classification import SpecialTenorType, SpecialTenorConfidence; from SDRUtils.config import SPECIAL_TENOR_PRIORITY; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add SDRUtils/core/classification.py SDRUtils/config.py
git commit -m "feat(sdr): add SpecialTenorType/SpecialTenorConfidence literals and priority constant"
```

---

### Task 2: Add Fields to SwapTradeClassification

**Files:**
- Modify: `SDRUtils/core/classification.py:78-93` (SwapTradeClassification dataclass)

**Step 1: Write the failing test**

Create `tests/test_special_tenor_classification.py`:

```python
"""Tests for unified special tenor classification."""

import pandas as pd
import pytest
from dataclasses import fields as dc_fields

from SDRUtils.core.classification import (
    SwapTradeClassification,
    SpecialTenorType,
    SpecialTenorConfidence,
)


class TestSwapTradeClassificationFields:
    """Verify new special_tenor fields exist on the dataclass."""

    def _make_classification(self, **overrides):
        defaults = dict(
            event_action="NEWT-TRAD",
            trade_id=1,
            execution_timestamp=pd.Timestamp("2026-01-07 21:00:00"),
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2036-01-09"),
            product_type="OIS_SWAP",
            trade_label="spot 10Y",
            notional=100_000_000.0,
            notional_currency="USD",
            is_notional_capped=False,
            tenor_years=10.0,
            tenor_label="10Y",
            is_forward=False,
            forward_start_years=0.0,
            forward_label="spot",
            fixed_rate=0.04,
        )
        defaults.update(overrides)
        return SwapTradeClassification(**defaults)

    def test_default_special_tenor_type_is_standard(self):
        c = self._make_classification()
        assert c.special_tenor_type == "STANDARD"

    def test_default_special_tenor_confidence_is_high(self):
        c = self._make_classification()
        assert c.special_tenor_confidence == "high"

    def test_default_special_tenor_tags_is_empty(self):
        c = self._make_classification()
        assert c.special_tenor_tags == []

    def test_can_set_imm_type(self):
        c = self._make_classification(
            special_tenor_type="IMM",
            special_tenor_tags=["IMM"],
        )
        assert c.special_tenor_type == "IMM"

    def test_can_set_multiple_tags(self):
        c = self._make_classification(
            special_tenor_type="INVOICE_SWAP",
            special_tenor_tags=["MATCHED_MATURITY", "INVOICE_SWAP"],
        )
        assert "MATCHED_MATURITY" in c.special_tenor_tags
        assert "INVOICE_SWAP" in c.special_tenor_tags

    def test_matched_ust_cusip_default_none(self):
        c = self._make_classification()
        assert c.matched_ust_cusip is None

    def test_invoice_swap_ticker_default_none(self):
        c = self._make_classification()
        assert c.invoice_swap_ticker is None

    def test_is_mac_default_false(self):
        c = self._make_classification()
        assert c.is_mac is False
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py -v`
Expected: FAIL — `SwapTradeClassification` missing `special_tenor_type` field

**Step 3: Add fields to SwapTradeClassification**

In `SDRUtils/core/classification.py`, modify the `SwapTradeClassification` dataclass (lines 78-93). After the existing `fixed_rate` field (line 93), add:

```python
@dataclass
class SwapTradeClassification(TradeClassification):
    """Swap-specific classification details."""

    # Tenor information
    tenor_years: float
    tenor_label: str  # e.g., "2Y", "5Y", "10Y"

    # Forward start info (for forward swaps)
    is_forward: bool
    forward_start_years: float
    forward_label: str  # e.g., "spot", "1Y", "5Y"

    # Rates
    fixed_rate: Optional[float]

    # Unified special tenor classification
    special_tenor_type: SpecialTenorType = field(default="STANDARD", kw_only=True)
    special_tenor_confidence: SpecialTenorConfidence = field(default="high", kw_only=True)
    special_tenor_tags: List[str] = field(default_factory=list, kw_only=True)

    # Reference data enrichment (populated by Phase 2 detectors)
    matched_ust_cusip: Optional[str] = field(default=None, kw_only=True)
    invoice_swap_ticker: Optional[str] = field(default=None, kw_only=True)
    is_mac: bool = field(default=False, kw_only=True)
```

**Step 4: Run test to verify it passes**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add SDRUtils/core/classification.py tests/test_special_tenor_classification.py
git commit -m "feat(sdr): add special_tenor fields to SwapTradeClassification"
```

---

### Task 3: Implement Phase 1 Intrinsic Classification

**Files:**
- Modify: `SDRUtils/core/tenors.py` (add `classify_intrinsic_special_tenor` function)
- Modify: `tests/test_special_tenor_classification.py` (add Phase 1 tests)

**Step 1: Write the failing tests**

Append to `tests/test_special_tenor_classification.py`:

```python
from SDRUtils.core.tenors import classify_intrinsic_special_tenor


class TestIntrinsicSpecialTenor:
    """Tests for Phase 1 intrinsic special tenor classification."""

    def test_standard_tenor_returns_standard(self):
        """A normal 10Y swap should be STANDARD."""
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2036-01-09"),
            tenor_label="10Y",
            forward_label="spot",
            is_forward=False,
        )
        assert typ == "STANDARD"
        assert conf == "high"
        assert tags == []

    def test_imm_maturity_detected(self):
        """Swap maturing on IMM date (3rd Wed of Jun 2026) should tag IMM."""
        # 3rd Wednesday of June 2026 = June 17, 2026
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2026-06-17"),
            tenor_label="IMM_M2026",
            forward_label="spot",
            is_forward=False,
        )
        assert typ == "IMM"
        assert "IMM" in tags

    def test_imm_forward_detected(self):
        """Forward-starting on IMM date should tag IMM."""
        # 3rd Wednesday of March 2026 = March 18, 2026
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2026-03-18"),
            expiration_date=pd.Timestamp("2028-03-18"),
            tenor_label="2Y",
            forward_label="IMM_H2026",
            is_forward=True,
        )
        assert typ == "IMM"
        assert "IMM" in tags

    def test_fomc_maturity_detected(self):
        """Swap maturing on FOMC date should tag FOMC."""
        # FOMC meeting Jan 29, 2025
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2025-01-02"),
            expiration_date=pd.Timestamp("2025-01-29"),
            tenor_label="FOMC_20250129",
            forward_label="spot",
            is_forward=False,
        )
        assert typ == "FOMC"
        assert "FOMC" in tags

    def test_fomc_takes_priority_over_imm_when_both_match(self):
        """If both FOMC and IMM labels present, FOMC wins (higher priority)."""
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2025-01-29"),
            expiration_date=pd.Timestamp("2025-06-18"),
            tenor_label="IMM_M2025",
            forward_label="FOMC_20250129",
            is_forward=True,
        )
        assert typ == "FOMC"
        assert "IMM" in tags
        assert "FOMC" in tags

    def test_labels_checked_not_just_dates(self):
        """Even if date doesn't match QL IMM, label prefix is enough."""
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2026-12-16"),
            tenor_label="IMM_Z2026",
            forward_label="spot",
            is_forward=False,
        )
        assert "IMM" in tags
```

**Step 2: Run tests to verify they fail**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py::TestIntrinsicSpecialTenor -v`
Expected: FAIL — `classify_intrinsic_special_tenor` does not exist

**Step 3: Implement classify_intrinsic_special_tenor**

In `SDRUtils/core/tenors.py`, add before the backward-compatibility aliases section (before line 288):

```python
def classify_intrinsic_special_tenor(
    effective_date: Optional[pd.Timestamp],
    expiration_date: Optional[pd.Timestamp],
    tenor_label: str,
    forward_label: str,
    is_forward: bool,
) -> tuple[str, str, list[str]]:
    """
    Classify special tenor using only the trade's own dates and labels.

    This is Phase 1 of special tenor detection — no external reference data needed.
    Detects: STANDARD, IMM, FOMC.

    Returns:
        (special_tenor_type, special_tenor_confidence, special_tenor_tags)
    """
    tags: list[str] = []

    # Check labels for IMM/FOMC (already computed by tenor_to_label / forward_to_label)
    if tenor_label.startswith("IMM_") or forward_label.startswith("IMM_"):
        tags.append("IMM")
    if tenor_label.startswith("FOMC_") or forward_label.startswith("FOMC_"):
        tags.append("FOMC")

    # Check expiration date directly against IMM/FOMC calendars
    if expiration_date is not None and "IMM" not in tags:
        if get_imm_label(expiration_date) is not None:
            tags.append("IMM")

    if expiration_date is not None and "FOMC" not in tags:
        if get_fomc_label(expiration_date) is not None:
            tags.append("FOMC")

    # Check effective date for forward-starting trades
    if is_forward and effective_date is not None:
        if "IMM" not in tags and get_imm_label(effective_date) is not None:
            tags.append("IMM")
        if "FOMC" not in tags and get_fomc_label(effective_date) is not None:
            tags.append("FOMC")

    if not tags:
        return "STANDARD", "high", []

    # FOMC is higher priority than IMM in intrinsic phase
    primary = "FOMC" if "FOMC" in tags else "IMM"
    return primary, "high", tags
```

**Step 4: Run tests to verify they pass**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add SDRUtils/core/tenors.py tests/test_special_tenor_classification.py
git commit -m "feat(sdr): implement Phase 1 intrinsic special tenor classification"
```

---

### Task 4: Wire Phase 1 into classify_usd_swap_trade

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py:48-145` (classify_usd_swap_trade function)

**Step 1: Write the failing test**

Append to `tests/test_special_tenor_classification.py`:

```python
from SDRUtils.products.usd.usd_swaps import classify_usd_swap_trade


class TestClassifyUsdSwapTradeSpecialTenor:
    """Verify Phase 1 is wired into classify_usd_swap_trade."""

    def _make_row(self, **overrides):
        defaults = {
            "Action type": "NEWT",
            "Event type": "TRAD",
            "Execution Timestamp": "2026-01-07 21:00:00+00:00",
            "Effective Date": "2026-01-09",
            "Expiration Date": "2036-01-09",
            "UPI FISN": "NA/T Swap Fxd Flt OIS USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "Notional amount-Leg 1": "100,000,000",
            "Notional currency-Leg 1": "USD",
            "Fixed rate-Leg 1": 0.04,
        }
        defaults.update(overrides)
        return pd.Series(defaults)

    def test_standard_swap_has_standard_type(self):
        row = self._make_row()
        c = classify_usd_swap_trade(row, trade_id=1, curve=None)
        assert c.special_tenor_type == "STANDARD"
        assert c.special_tenor_tags == []

    def test_imm_maturity_swap_has_imm_type(self):
        # 3rd Wednesday of June 2026 = June 17
        row = self._make_row(**{"Expiration Date": "2026-06-17"})
        c = classify_usd_swap_trade(row, trade_id=2, curve=None)
        assert c.special_tenor_type == "IMM"
        assert "IMM" in c.special_tenor_tags
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py::TestClassifyUsdSwapTradeSpecialTenor -v`
Expected: FAIL — `classify_usd_swap_trade` doesn't set `special_tenor_type`

**Step 3: Wire Phase 1 into classify_usd_swap_trade**

In `SDRUtils/products/usd/usd_swaps.py`, add the import at the top (after the existing tenors imports around line 33):

```python
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_from_dates, tenor_to_label, classify_intrinsic_special_tenor
```

Then in the `classify_usd_swap_trade` function, after line 106 (`trade_label = build_trade_label(...)`) and before the notional extraction (line 109), add:

```python
    # Phase 1: intrinsic special tenor classification
    special_tenor_type, special_tenor_confidence, special_tenor_tags = classify_intrinsic_special_tenor(
        effective_date=effective_date,
        expiration_date=expiration_date,
        tenor_label=tenor_label,
        forward_label=forward_label,
        is_forward=is_forward,
    )
```

Then update the return statement (lines 126-145) to include the new fields:

```python
    return SwapTradeClassification(
        event_action=f"{row.get('Action type')}-{row.get('Event type')}",
        trade_id=trade_id,
        execution_timestamp=execution_ts,
        effective_date=effective_date,
        expiration_date=expiration_date,
        product_type=product_type,
        trade_label=trade_label,
        tenor_years=tenor_years,
        tenor_label=tenor_label,
        is_forward=is_forward,
        forward_start_years=forward_years,
        forward_label=forward_label,
        notional=notional,
        notional_currency=row.get("Notional currency-Leg 1", "USD"),
        is_notional_capped=is_notional_capped,
        fixed_rate=fixed_rate if pd.notna(fixed_rate) else None,
        estimated_pv01=pv01,
        package_type="OUTRIGHT",
        special_tenor_type=special_tenor_type,
        special_tenor_confidence=special_tenor_confidence,
        special_tenor_tags=special_tenor_tags,
    )
```

**Step 4: Run tests to verify they pass**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py tests/test_special_tenor_classification.py
git commit -m "feat(sdr): wire Phase 1 intrinsic special tenor into classify_usd_swap_trade"
```

---

### Task 5: Implement Round-Notional Confidence Helper and Priority Resolver

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py` (add `_is_round_notional` and `_resolve_special_tenor_priority`)
- Modify: `tests/test_special_tenor_classification.py` (add tests)

**Step 1: Write the failing tests**

Append to `tests/test_special_tenor_classification.py`:

```python
from SDRUtils.products.usd.usd_swaps import _is_round_notional, _resolve_special_tenor_priority
import numpy as np


class TestIsRoundNotional:
    """Tests for round-notional detection."""

    def test_exact_multiple_of_5m_is_round(self):
        assert _is_round_notional(100_000_000) is True
        assert _is_round_notional(250_000_000) is True
        assert _is_round_notional(5_000_000) is True

    def test_non_multiple_is_not_round(self):
        assert _is_round_notional(147_300_000) is False
        assert _is_round_notional(103_500_000) is False

    def test_nan_is_not_round(self):
        assert _is_round_notional(float("nan")) is False

    def test_zero_is_not_round(self):
        assert _is_round_notional(0) is False

    def test_negative_is_not_round(self):
        assert _is_round_notional(-100_000_000) is False


class TestResolveSpecialTenorPriority:
    """Tests for the final rollup that resolves unified special_tenor fields."""

    def _make_df(self, rows):
        return pd.DataFrame(rows)

    def test_standard_swap_stays_standard(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": False,
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "spot",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "STANDARD"

    def test_mms_upgrades_standard_to_matched_maturity(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 147_300_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MATCHED_MATURITY"
        assert "MATCHED_MATURITY" in result["special_tenor_tags"].iloc[0]

    def test_invoice_swap_wins_over_matched_maturity(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": "TYA",
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 147_300_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "INVOICE_SWAP"
        assert "MATCHED_MATURITY" in result["special_tenor_tags"].iloc[0]
        assert "INVOICE_SWAP" in result["special_tenor_tags"].iloc[0]

    def test_spot_round_notional_mms_gets_low_confidence(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "spot",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MATCHED_MATURITY"
        assert result["special_tenor_confidence"].iloc[0] == "low"

    def test_spot_nonround_notional_mms_gets_medium_confidence(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "spot",
            "notional": 147_300_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MATCHED_MATURITY"
        assert result["special_tenor_confidence"].iloc[0] == "medium"

    def test_forward_mms_gets_high_confidence_regardless_of_notional(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2027-01-09",
            "expiration_date": "2037-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_confidence"].iloc[0] == "high"

    def test_mac_tags_added(self):
        df = self._make_df([{
            "special_tenor_type": "IMM",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "['IMM']",
            "matched_ust_maturity": False,
            "invoice_swap_ticker": None,
            "is_mac": True,
            "forward_label": "spot",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2026-03-18",
            "expiration_date": "2036-03-18",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MAC"
        assert "IMM" in result["special_tenor_tags"].iloc[0]
        assert "MAC" in result["special_tenor_tags"].iloc[0]

    def test_short_tenor_mms_gets_low_confidence(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 147_300_000,
            "tenor_years": 0.5,
            "effective_date": "2026-01-09",
            "expiration_date": "2026-07-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_confidence"].iloc[0] == "low"
```

**Step 2: Run tests to verify they fail**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py::TestIsRoundNotional tests/test_special_tenor_classification.py::TestResolveSpecialTenorPriority -v`
Expected: FAIL — functions don't exist

**Step 3: Implement _is_round_notional**

In `SDRUtils/products/usd/usd_swaps.py`, add after the `_coerce_numeric_like` function (after line 418):

```python
def _is_round_notional(notional: float, threshold: float = 5_000_000) -> bool:
    """True if notional is a 'round' number (divisible by threshold with no remainder)."""
    if pd.isna(notional) or notional <= 0:
        return False
    return (notional % threshold) == 0
```

**Step 4: Implement _resolve_special_tenor_priority**

In `SDRUtils/products/usd/usd_swaps.py`, add after `_is_round_notional`:

```python
def _resolve_special_tenor_priority(df: pd.DataFrame) -> pd.DataFrame:
    """
    After all detectors have run, resolve unified special_tenor fields.

    Reads existing detection columns (matched_ust_maturity, invoice_swap_ticker,
    is_mac) and merges them with Phase 1 intrinsic tags. Applies priority
    hierarchy and round-notional confidence adjustment.

    Priority (lowest to highest):
        STANDARD < IMM < FOMC < MAC < MATCHED_MATURITY < INVOICE_SWAP
    """
    from SDRUtils.config import SPECIAL_TENOR_PRIORITY

    out = df.copy()

    if out.empty:
        return out

    priority_map = {t: i for i, t in enumerate(SPECIAL_TENOR_PRIORITY)}

    def _parse_tags(val) -> list[str]:
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if not inner:
                    return []
                return [t.strip().strip("'\"") for t in inner.split(",")]
            return [val] if val else []
        return []

    def _resolve_row(row):
        tags = list(_parse_tags(row.get("special_tenor_tags", [])))
        intrinsic_type = str(row.get("special_tenor_type", "STANDARD"))

        # Collect Phase 2 detections
        if row.get("matched_ust_maturity") is True or str(row.get("matched_ust_maturity")).lower() == "true":
            if "MATCHED_MATURITY" not in tags:
                tags.append("MATCHED_MATURITY")

        if pd.notna(row.get("invoice_swap_ticker")) and str(row.get("invoice_swap_ticker")).strip():
            if "INVOICE_SWAP" not in tags:
                tags.append("INVOICE_SWAP")

        if row.get("is_mac") is True or str(row.get("is_mac")).lower() == "true":
            if "MAC" not in tags:
                tags.append("MAC")

        # Determine primary type by priority
        if not tags:
            return "STANDARD", "high", []

        primary = max(tags, key=lambda t: priority_map.get(t, -1))

        # Confidence scoring for MATCHED_MATURITY
        conf = "high"
        if primary in ("MATCHED_MATURITY", "INVOICE_SWAP"):
            fwd = str(row.get("forward_label", "spot")).strip().lower()
            is_spot = fwd == "spot"
            notional = pd.to_numeric(row.get("notional"), errors="coerce")
            tenor_y = pd.to_numeric(row.get("tenor_years"), errors="coerce")

            if pd.notna(tenor_y) and tenor_y < 1.0:
                conf = "low"
            elif is_spot:
                if _is_round_notional(notional if pd.notna(notional) else 0):
                    conf = "low"
                else:
                    conf = "medium"
            # Forward-starting or invoice: keep "high"

        return primary, conf, tags

    results = out.apply(_resolve_row, axis=1, result_type="expand")
    results.columns = ["special_tenor_type", "special_tenor_confidence", "special_tenor_tags"]
    out["special_tenor_type"] = results["special_tenor_type"]
    out["special_tenor_confidence"] = results["special_tenor_confidence"]
    out["special_tenor_tags"] = results["special_tenor_tags"]

    return out
```

**Step 5: Export the new functions**

In `SDRUtils/products/usd/usd_swaps.py`, update `__all__` (line 656) to include:

```python
__all__ = [
    "USD_SwapProduct",
    "classify_usd_swap_trade",
    "usd_swap_trades",
    "new_usd_swap_trades",
    "is_usd_swap",
    "detect_invoice_swaps",
    "detect_mac_swaps",
    "detect_spreadovers",
    "_is_round_notional",
    "_resolve_special_tenor_priority",
]
```

**Step 6: Run tests to verify they pass**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py tests/test_special_tenor_classification.py
git commit -m "feat(sdr): implement round-notional filter and special tenor priority resolver"
```

---

### Task 6: Wire Priority Resolver into build_classification_dataframe

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py:616-628` (the detector chain in build_classification_dataframe)

**Step 1: Add _resolve_special_tenor_priority call after all detectors**

In `SDRUtils/products/usd/usd_swaps.py`, in the `build_classification_dataframe` method, after the spreadover detection block (line 628: `package_df = detect_spreadovers(package_df)`), add:

```python
            if detect_spreadover:
                package_df = detect_spreadovers(package_df)

            # Final rollup: resolve unified special_tenor fields from all detectors
            package_df = _resolve_special_tenor_priority(package_df)
```

**Step 2: Verify existing tests still pass**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py
git commit -m "feat(sdr): wire special tenor priority resolver into build_classification_dataframe"
```

---

### Task 7: Run Full Test Suite and Verify No Regressions

**Files:** None (verification only)

**Step 1: Run SDR-related tests**

Run: `cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_special_tenor_classification.py tests/test_sdr_trade_events.py -v`
Expected: All PASS

**Step 2: Verify imports and dataclass serialization**

Run:
```bash
cd /c/Users/chris/clee/ARBS && python -c "
from SDRUtils.core.classification import SwapTradeClassification, classifications_to_dataframe, SpecialTenorType, SpecialTenorConfidence
from SDRUtils.config import SPECIAL_TENOR_PRIORITY
from SDRUtils.core.tenors import classify_intrinsic_special_tenor
from SDRUtils.products.usd.usd_swaps import _is_round_notional, _resolve_special_tenor_priority
import pandas as pd

# Test dataclass -> DataFrame serialization preserves new fields
c = SwapTradeClassification(
    event_action='NEWT-TRAD', trade_id=1,
    execution_timestamp=pd.Timestamp('2026-01-07'),
    effective_date=pd.Timestamp('2026-01-09'),
    expiration_date=pd.Timestamp('2036-01-09'),
    product_type='OIS_SWAP', trade_label='spot 10Y',
    notional=100_000_000.0, notional_currency='USD',
    is_notional_capped=False, tenor_years=10.0, tenor_label='10Y',
    is_forward=False, forward_start_years=0.0, forward_label='spot',
    fixed_rate=0.04, special_tenor_type='IMM', special_tenor_tags=['IMM'],
)
df = classifications_to_dataframe([c])
assert 'special_tenor_type' in df.columns
assert df['special_tenor_type'].iloc[0] == 'IMM'
assert 'special_tenor_tags' in df.columns
print('All integration checks passed')
"
```
Expected: `All integration checks passed`

**Step 3: Final commit for any fixups**

If any fixes were needed, commit them. Otherwise, no action.
