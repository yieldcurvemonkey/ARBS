# Trade Tape Design

## Overview

A single enriched DataFrame where every row is a classified SDR trade with all signals a market maker needs. Implemented as `TradeTape(SDRAnalyzer)` in `SDRUtils/analytics/trade_tape.py`.

**Input**: Classified DataFrame from `load_classified_trades()` or `build_classification_dataframe()`.
**Output**: Same DataFrame with ~35 new columns across 7 enrichment layers + enriched `trade_label`.

## Architecture

Layered private methods inside `TradeTape`, each responsible for one signal domain. `compute()` calls them in sequence. Follows `FOMCAnalyzer` pattern.

```
TradeTape(SDRAnalyzer)
  __init__(df, *, cluster_gap_seconds=120, off_market_threshold_bp=10.0)
  compute() -> pd.DataFrame          # full enriched tape
  summary() -> dict                   # key stats
  clean_tape() -> pd.DataFrame        # new-risk only, no UFRO/compression
  package_summary() -> pd.DataFrame   # one row per package_id

  _ensure_prerequisites()             # execution_date, dv01, tenor_bucket
  _enrich_classification()            # Layer 1: trade_type, venue, ccp, etc.
  _enrich_lifecycle()                 # Layer 2: lifecycle_type, is_new_risk, etc.
  _enrich_quality()                   # Layer 3: UFRO, off-market, capped, flags
  _enrich_packages()                  # Layer 4: package structure derivation
  _enrich_context()                   # Layer 5: FOMC/event windows, session
  _enrich_rv()                        # Layer 6: clustering, VWAP, relative value
  _build_enriched_label()             # Layer 7: prefix-tag trade label
```

## Enrichment Layers

### Layer 1: Classification (`_enrich_classification`)
Reuses: `assign_trade_type`, `bucket_forward_start`, `classify_rate_index`, `classify_venue`, `infer_ccp`

| Column | Source | Values |
|--------|--------|--------|
| `trade_type` | `assign_trade_type(row)` | OUTRIGHT/CURVE/FLY/SPREADOVER/MAC/IMM/FOMC/MATCHED_MATURITY/INVOICE_SWAP |
| `forward_bucket` | `bucket_forward_start(forward_label)` | spot/1W/2W/1M/.../3Y+ |
| `rate_index_clean` | `classify_rate_index(upi_underlier_name)` | SOFR/FED_FUNDS/OTHER |
| `venue` | `classify_venue(platform_identifier)` | D2D/D2C |
| `ccp` | `infer_ccp(row)` | CME/LCH |

### Layer 2: Lifecycle (`_enrich_lifecycle`)
Reuses: `detect_compression_signals` for `is_newt`/`is_lifecycle`/`is_reset_opt`

| Column | Logic |
|--------|-------|
| `lifecycle_type` | Parse `event_action` prefix: NEWT->NEW_TRADE, TERM->TERMINATION, CORR->CORRECTION, MODI->MODIFICATION, else OTHER |
| `is_new_risk` | `event_action` starts with "NEWT" |
| `is_compression` | `is_lifecycle` from `detect_compression_signals` (TERM/CORR/MODI events) |
| `is_reset_optimization` | `tenor_years < 0.5` |

### Layer 3: Quality (`_enrich_quality`)
Reuses: `flag_outliers` (composite of `flag_upfront_payments`, `flag_off_market_trades`, `flag_capped_notional`)

| Column | Source |
|--------|--------|
| `is_ufro` | `flag_upfront_payments` |
| `ufro_amount` | `flag_upfront_payments` |
| `is_off_market` | `flag_off_market_trades` (threshold from `self._off_market_threshold_bp`) |
| `rate_deviation_bp` | `flag_off_market_trades` |
| `is_capped` | `flag_capped_notional` |
| `is_block` | `block_trade_election_indicator == True` |
| `quality_flags` | `flag_outliers` composite list |

### Layer 4: Packages (`_enrich_packages`)
New logic, no existing function to reuse.

| Column | Logic |
|--------|-------|
| `is_package` | `package_type` not in (None, NaN, "", "OUTRIGHT") |
| `package_structure` | Derive from groupby `package_id`: join tenor_labels with "/" separator, append trade_type. E.g., "2Y/5Y Curve", "2Y/5Y/10Y Fly", "10Y Outright" |
| `n_package_legs` | Count of rows sharing same `package_id` |
| `has_spread` | `package_transaction_spread` is not null/NaN/0 |

**Package structure derivation**: Group by `package_id`, collect `tenor_label` from all legs sorted by `tenor_years`, join with "/", append `trade_type`. If package_id is null, derive from single row. For CURVE: "2Y/5Y Curve". For FLY: "2Y/5Y/10Y Fly". For OUTRIGHT: "10Y Outright".

### Layer 5: Market Context (`_enrich_context`)
Reuses: `add_event_classifications` (with include_fomc/include_me/include_qe all True)

| Column | Source |
|--------|--------|
| `is_fomc_window` | `add_event_classifications` |
| `is_month_end_window` | `add_event_classifications` |
| `is_quarter_end_window` | `add_event_classifications` |
| `fomc_meeting_label` | If `special_tenor_type=="FOMC"`, use `assign_fomc_meeting` with schedule |
| `fomc_proximity` | `classify_meeting_proximity` for FOMC trades |
| `execution_hour_et` | Extract hour from `execution_timestamp` in America/New_York |
| `execution_session` | Map hour: Asia(18-02), London(02-08), NY_AM(08-12), NY_PM(12-16), Late(16-18) |

### Layer 6: Relative Value (`_enrich_rv`)
Reuses: `trade_clustering`, `daily_vwap`

| Column | Source |
|--------|--------|
| `cluster_id` | `trade_clustering(df, gap_seconds=self._cluster_gap_seconds)` |
| `cluster_size` | `groupby('cluster_id').transform('size')` |
| `is_multi_meeting_cluster` | For FOMC trades: cluster spans >1 distinct `fomc_meeting_label` |
| `daily_tenor_vwap` | `daily_vwap(df, group_col='tenor_label')` merged back |
| `rate_vs_vwap_bp` | `(fixed_rate - daily_tenor_vwap) * 10_000` |

### Layer 7: Enriched Trade Label (`_build_enriched_label`)
Mirrors `_backfill_swaption_fields` pattern. Multi-stage prefix construction.

**Prefix tokens** (in order, space-separated):
1. **Rate index**: `SOFR` | `FF` | (omit if OTHER)
2. **Lifecycle flag** (non-NEWT only): `TERM` | `CORR` | `MODI`
3. **Quality flag** (if applicable): `UFRO` | `BLOCK`
4. **Trade structure** (packages only): `CURVE` | `FLY`

**Base label**: existing `trade_label` (e.g., "spot 10Y", "1Y 5Y", "FOMC_20250618 3M")

**Package base**: For CURVE/FLY packages, replace base with slash-joined tenor labels from legs: "2Y/5Y", "2Y/5Y/10Y"

**Examples**:
- `SOFR spot 10Y` (vanilla SOFR outright, NEWT)
- `SOFR UFRO spot 5Y` (off-market coupon SOFR swap)
- `FF FOMC_20250618 3M` (fed funds FOMC-dated)
- `SOFR CURVE 2Y/5Y` (SOFR curve trade)
- `SOFR FLY 2Y/5Y/10Y` (SOFR butterfly)
- `SOFR BLOCK spot 30Y` (block trade)
- `SOFR TERM spot 10Y` (termination)
- `SOFR MODI spot 7Y` (modification)

**Fallback**: If trade_label is empty/NaN, use `build_trade_label(forward_label, tenor_label, is_forward)`.

## Public Interface

```python
class TradeTape(SDRAnalyzer):
    def __init__(
        self,
        df: pd.DataFrame,
        *,
        cluster_gap_seconds: int = 120,
        off_market_threshold_bp: float = 10.0,
    ) -> None: ...

    def compute(self) -> pd.DataFrame:
        """Run all enrichment layers, return fully enriched tape."""

    def summary(self) -> dict:
        """Key stats: n_trades, n_new_risk, pct_compression, pct_ufro,
        pct_block, pct_capped, top_trade_types, venue_split, ccp_split."""

    def clean_tape(self) -> pd.DataFrame:
        """Filtered to is_new_risk==True, is_ufro==False, is_compression==False,
        is_reset_optimization==False. The 'real' organic flow."""

    def package_summary(self) -> pd.DataFrame:
        """One row per package_id: package_structure, n_legs, trade_type,
        total_dv01, total_notional, has_spread, rate_index_clean."""
```

## Notebook: `notebooks/sdr/13_trade_tape.ipynb`

8 cells demonstrating:
1. Load data via `load_classified_trades()`, create `TradeTape(df).compute()`
2. Distribution of `trade_type`, `lifecycle_type`, `venue`
3. `clean_tape()` -- volume comparison (raw vs clean)
4. `quality_flags` distribution -- UFRO, off-market, capped fractions
5. `package_summary()` -- most common structures
6. `execution_session` distribution
7. Cluster analysis -- multi-leg cluster stats
8. Cross-tab: `trade_type` x `venue` x `rate_index_clean`

## Dependencies

All reused from existing modules -- no new external dependencies:
- `SDRUtils.analytics.filters`: `add_dv01_columns`, `add_volume_buckets`, `add_execution_date`, `daily_vwap`
- `SDRUtils.analytics.flow`: `assign_trade_type`, `bucket_forward_start`, `classify_venue`, `infer_ccp`
- `SDRUtils.analytics.fomc`: `classify_rate_index`, `assign_fomc_meeting`, `classify_meeting_proximity`, `load_fomc_schedule`
- `SDRUtils.analytics.trade_quality`: `flag_outliers`, `TradeQualityFlag`
- `SDRUtils.analytics.compression`: `detect_compression_signals`
- `SDRUtils.analytics.intraday`: `trade_clustering`
- `SDRUtils.analytics.seasonality`: `add_event_classifications`
- `SDRUtils.core.tenors`: `build_trade_label`

## Files to Create/Modify

| File | Action |
|------|--------|
| `SDRUtils/analytics/trade_tape.py` | CREATE -- TradeTape class |
| `SDRUtils/analytics/__init__.py` | MODIFY -- add TradeTape to exports |
| `notebooks/sdr/13_trade_tape.ipynb` | CREATE -- demo notebook |
