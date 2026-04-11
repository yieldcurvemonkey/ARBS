# Special Tenor Classification for SDR Linear Swap Analytics

**Date:** 2026-04-11
**Status:** Design approved, pending implementation
**Scope:** USD swaps only (other currencies follow same pattern later)

## Problem

The SDR swap analytics pipeline detects special tenor types (IMM, FOMC, matched maturity UST, invoice swaps, MAC swaps) through disconnected post-processing detectors. There is no unified classification field, making it difficult for consumers to answer "what kind of swap is this?" without checking multiple columns. Additionally, false positives occur when a spot-starting swap coincidentally matures on a UST maturity date.

## Design

### Architecture: Layered Classification with Enrichment Pipeline

Two-phase approach:

- **Phase 1 (intrinsic):** During `classify_usd_swap_trade()`, detect types that need only the trade's own dates: `STANDARD`, `IMM`, `FOMC`. Written directly onto `SwapTradeClassification`.
- **Phase 2 (enrichment):** After batch classification, existing detectors (`detect_mms_trades_df`, `detect_invoice_swaps`, `detect_mac_swaps`) run on the DataFrame and write results into the unified fields. A final `_resolve_special_tenor_priority()` applies hierarchy and confidence scoring.

### Type System

```python
SpecialTenorType = Literal[
    "STANDARD",           # Regular benchmark tenor
    "IMM",                # 3rd Wednesday of Mar/Jun/Sep/Dec
    "FOMC",               # Federal Reserve meeting date
    "MATCHED_MATURITY",   # Maturity matches a UST maturity date
    "INVOICE_SWAP",       # Effective = delivery date, maturity = CTD maturity
    "MAC",                # Market Agreed Coupon
]

SpecialTenorConfidence = Literal["high", "medium", "low"]
```

### Priority Hierarchy

When multiple types match (e.g., invoice swap IS a matched maturity swap):

```
INVOICE_SWAP > MATCHED_MATURITY > MAC > FOMC > IMM > STANDARD
```

Most specific wins for `special_tenor_type`. All matching types stored in `special_tenor_tags`.

### Fields on SwapTradeClassification

```python
@dataclass
class SwapTradeClassification(TradeClassification):
    # ... existing fields ...

    # Unified special tenor classification
    special_tenor_type: SpecialTenorType = "STANDARD"
    special_tenor_confidence: SpecialTenorConfidence = "high"
    special_tenor_tags: List[str] = field(default_factory=list)

    # Reference data enrichment (populated by Phase 2)
    matched_ust_cusip: Optional[str] = None
    invoice_swap_ticker: Optional[str] = None
    is_mac: bool = False
```

### Phase 1: Intrinsic Classification

In `classify_usd_swap_trade()`, after computing tenor/forward labels:

```python
def _classify_intrinsic_special_tenor(
    effective_date, expiration_date, tenor_label, forward_label, is_forward
) -> tuple[SpecialTenorType, SpecialTenorConfidence, list[str]]:
    tags = []

    # Check labels for IMM/FOMC (already computed)
    if tenor_label.startswith("IMM_") or forward_label.startswith("IMM_"):
        tags.append("IMM")
    if tenor_label.startswith("FOMC_") or forward_label.startswith("FOMC_"):
        tags.append("FOMC")

    # Check maturity date directly
    if expiration_date is not None:
        if get_imm_label(expiration_date):
            if "IMM" not in tags:
                tags.append("IMM")
        if get_fomc_label(expiration_date):
            if "FOMC" not in tags:
                tags.append("FOMC")

    if not tags:
        return "STANDARD", "high", []

    primary = "FOMC" if "FOMC" in tags else "IMM"
    return primary, "high", tags
```

### Phase 2: Enrichment and Priority Resolution

After all detectors run, `_resolve_special_tenor_priority()`:

1. Collects all detected types into `special_tenor_tags`
2. Applies round-notional confidence filter
3. Picks highest-priority type as `special_tenor_type`
4. Writes backward-compatible columns

### Round-Notional Confidence Filter

Key insight: matched maturity trades from real-money accounts typically have non-round notionals (e.g., $147.3M duration-matched to a specific bond position). Spot-starting swaps tend to be round numbers.

```python
def _is_round_notional(notional: float, threshold: float = 5_000_000) -> bool:
    if pd.isna(notional) or notional <= 0:
        return False
    return (notional % threshold) == 0
```

Confidence matrix for MATCHED_MATURITY:

| Forward? | Notional  | Confidence |
|----------|-----------|------------|
| Yes      | Any       | high       |
| No (spot)| Non-round | medium     |
| No (spot)| Round     | low        |
| No (spot)| Round + same MM-DD as effective | low (likely coincidental) |
| Any      | < 1Y tenor| low        |

### Orchestration

In `build_classification_dataframe`:

```
classify trades (Phase 1: intrinsic special tenor)
  -> detect_fly_trades_df
  -> detect_curve_trades_df
  -> detect_mms_trades_df
  -> detect_invoice_swaps
  -> detect_mac_swaps
  -> detect_spreadovers
  -> _resolve_special_tenor_priority()   # NEW: final rollup
```

### Backward Compatibility

All existing columns preserved:
- `matched_ust_maturity` = `"MATCHED_MATURITY" in special_tenor_tags`
- `matched_ust_maturity_trade_confidence` = `special_tenor_confidence` when MMS matched
- `invoice_swap_ticker` stays as enrichment data (not replaced)
- `is_mac` = `"MAC" in special_tenor_tags`

### Files to Modify

| File | Changes |
|------|---------|
| `SDRUtils/core/classification.py` | Add `SpecialTenorType`, `SpecialTenorConfidence` literals. Add fields to `SwapTradeClassification`. |
| `SDRUtils/core/tenors.py` | Add `_classify_intrinsic_special_tenor()` function. |
| `SDRUtils/products/usd/usd_swaps.py` | Call Phase 1 in `classify_usd_swap_trade()`. Add `_resolve_special_tenor_priority()`. Wire rollup into `build_classification_dataframe`. Add `_is_round_notional()`. |
| `SDRUtils/packages/mms.py` | Update `detect_mms_trades_df` to write into unified columns (additive, not breaking). |
| `SDRUtils/config.py` | Add `SPECIAL_TENOR_PRIORITY` list constant. |

### Non-Goals

- Non-USD currencies (future work, same pattern)
- Changing how `tenor_to_label` / `forward_to_label` work (these stay as-is)
- Removing existing detector modules (they continue to do the heavy lifting)
