# Trade Tape Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `TradeTape(SDRAnalyzer)` -- a single enriched DataFrame where every row is a classified SDR trade with all signals a market maker needs, plus a demo notebook.

**Architecture:** Layered private methods inside `TradeTape`. `compute()` calls 7 enrichment layers in sequence, each adding columns via existing analytics functions. Trade label enriched with prefix tags mirroring swaption `_backfill_swaption_fields` pattern.

**Tech Stack:** pandas, numpy, existing SDRUtils.analytics.* modules, SDRUtils.core.tenors.build_trade_label

**Env:** `conda activate stir` for all test/run commands.

---

### Task 1: Create `trade_tape.py` with class skeleton and prerequisites layer

**Files:**
- Create: `SDRUtils/analytics/trade_tape.py`

**Step 1: Write the module with class skeleton and `_ensure_prerequisites`**

```python
"""
Trade Tape: single enriched DataFrame with all signals a market maker needs.

Composes existing analytics modules into a unified per-trade enrichment
pipeline.  Each row in the output is a classified SDR trade with ~35 new
columns spanning classification, lifecycle, quality, package structure,
market context, relative value, and an enriched trade label.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ._base import SDRAnalyzer
from .compression import detect_compression_signals
from .filters import (
    add_dv01_columns,
    add_execution_date,
    add_volume_buckets,
    daily_vwap,
)
from .flow import assign_trade_type, bucket_forward_start, classify_venue, infer_ccp
from .fomc import (
    assign_fomc_meeting,
    classify_meeting_proximity,
    classify_rate_index,
    load_fomc_schedule,
)
from .intraday import trade_clustering
from .seasonality import add_event_classifications
from .trade_quality import TradeQualityFlag, flag_outliers

# ---------------------------------------------------------------------------
# Execution session boundaries (Eastern Time hours)
# ---------------------------------------------------------------------------

_SESSION_BREAKS: List[tuple[int, int, str]] = [
    (2, 8, "London"),
    (8, 12, "NY_AM"),
    (12, 16, "NY_PM"),
    (16, 18, "Late"),
    # 18-02 wraps midnight -> handled as default
]


def _hour_to_session(hour: int) -> str:
    """Map an Eastern-Time hour (0-23) to a trading session label."""
    for lo, hi, label in _SESSION_BREAKS:
        if lo <= hour < hi:
            return label
    return "Asia"  # 18-23 and 0-1


# ---------------------------------------------------------------------------
# Rate-index abbreviation for trade labels
# ---------------------------------------------------------------------------

_INDEX_PREFIX = {
    "SOFR": "SOFR",
    "FED_FUNDS": "FF",
}


class TradeTape(SDRAnalyzer):
    """Unified trade enrichment pipeline.

    Takes a classified DataFrame (from ``load_classified_trades`` or
    ``build_classification_dataframe``) and produces a fully enriched
    tape with ~35 new columns across 7 layers.

    Args:
        df: Classified SDR trade DataFrame.
        cluster_gap_seconds: Max seconds between trades in the same
            temporal cluster (default 120).
        off_market_threshold_bp: Basis-point threshold for flagging
            off-market rates (default 10.0).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        *,
        cluster_gap_seconds: int = 120,
        off_market_threshold_bp: float = 10.0,
    ) -> None:
        super().__init__(df)
        self._cluster_gap_seconds = cluster_gap_seconds
        self._off_market_threshold_bp = off_market_threshold_bp

    # -- prerequisites -----------------------------------------------------

    def _ensure_prerequisites(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add execution_date, dv01, and tenor_bucket if missing."""
        if "execution_date" not in df.columns:
            df = add_execution_date(df)
        if "dv01" not in df.columns:
            df = add_dv01_columns(df)
        if "tenor_bucket" not in df.columns:
            df = add_volume_buckets(df)
        return df

    # -- placeholder layers (Tasks 2-8 fill these in) ----------------------

    def _enrich_classification(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_lifecycle(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_quality(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_packages(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_context(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_rv(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _build_enriched_label(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    # -- public interface --------------------------------------------------

    def compute(self) -> pd.DataFrame:
        """Run all enrichment layers and return the fully enriched tape."""
        if self._result is not None:
            return self._result

        df = self._df.copy()
        df = self._ensure_prerequisites(df)
        df = self._enrich_classification(df)
        df = self._enrich_lifecycle(df)
        df = self._enrich_quality(df)
        df = self._enrich_packages(df)
        df = self._enrich_context(df)
        df = self._enrich_rv(df)
        df = self._build_enriched_label(df)

        self._result = df
        return df

    def summary(self) -> Dict[str, Any]:
        """Key stats for the enriched tape."""
        if self._result is None:
            self.compute()
        df = self._result
        n = len(df)
        return {}  # placeholder -- Task 9

    def clean_tape(self) -> pd.DataFrame:
        """Tape filtered to new-risk only, no UFRO/compression/reset-opt."""
        if self._result is None:
            self.compute()
        df = self._result
        return pd.DataFrame(columns=df.columns)  # placeholder -- Task 9

    def package_summary(self) -> pd.DataFrame:
        """One row per package_id with structure description."""
        if self._result is None:
            self.compute()
        return pd.DataFrame()  # placeholder -- Task 9
```

**Step 2: Verify import works**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "from SDRUtils.analytics.trade_tape import TradeTape; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): add TradeTape skeleton with prerequisites layer"
```

---

### Task 2: Implement classification layer (`_enrich_classification`)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace `_enrich_classification` placeholder**

```python
def _enrich_classification(self, df: pd.DataFrame) -> pd.DataFrame:
    """Layer 1: trade type, forward bucket, rate index, venue, CCP."""
    df["trade_type"] = df.apply(assign_trade_type, axis=1)
    df["forward_bucket"] = df["forward_label"].map(bucket_forward_start)
    df["rate_index_clean"] = (
        df["upi_underlier_name"]
        .fillna("")
        .map(classify_rate_index)
    )
    df["venue"] = df["platform_identifier"].map(
        lambda x: classify_venue(x)
    )
    df["ccp"] = df.apply(infer_ccp, axis=1)
    return df
```

**Step 2: Verify with a quick smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
df = pd.DataFrame({
    'execution_timestamp': pd.to_datetime(['2025-04-01 10:00:00']),
    'effective_date': pd.to_datetime(['2025-04-03']),
    'expiration_date': pd.to_datetime(['2035-04-03']),
    'estimated_pv01': [0.0009],
    'notional': [100_000_000],
    'tenor_years': [10.0],
    'tenor_label': ['10Y'],
    'forward_label': ['spot'],
    'is_forward': [False],
    'trade_label': ['spot 10Y'],
    'fixed_rate': [0.04],
    'package_type': [None],
    'is_spreadover': [False],
    'special_tenor_type': ['STANDARD'],
    'upi_underlier_name': ['USD-SOFR-OIS Compound'],
    'platform_identifier': ['BGCD'],
    'event_action': ['NEWT'],
})
tape = TradeTape(df)
result = tape.compute()
assert result['trade_type'].iloc[0] == 'OUTRIGHT'
assert result['forward_bucket'].iloc[0] == 'spot'
assert result['rate_index_clean'].iloc[0] == 'SOFR'
assert result['venue'].iloc[0] == 'D2D'
assert result['ccp'].iloc[0] == 'LCH'
print('Classification layer OK')
"
```
Expected: `Classification layer OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape classification layer"
```

---

### Task 3: Implement lifecycle layer (`_enrich_lifecycle`)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace `_enrich_lifecycle` placeholder**

```python
def _enrich_lifecycle(self, df: pd.DataFrame) -> pd.DataFrame:
    """Layer 2: lifecycle type, new-risk, compression, reset-opt flags."""
    action = df["event_action"].astype(str).str.upper()

    # Extract first token (e.g. "NEWT-TRAD" -> "NEWT", "NEWT" -> "NEWT")
    action_prefix = action.str.split(r"[-\s]", n=1).str[0]

    lifecycle_map = {
        "NEWT": "NEW_TRADE",
        "TERM": "TERMINATION",
        "CORR": "CORRECTION",
        "MODI": "MODIFICATION",
    }
    df["lifecycle_type"] = action_prefix.map(lifecycle_map).fillna("OTHER")
    df["is_new_risk"] = action_prefix == "NEWT"

    # Reuse compression signals for consistency
    signals = detect_compression_signals(df)
    df["is_compression"] = signals["is_lifecycle"].values
    df["is_reset_optimization"] = signals["is_reset_opt"].values

    return df
```

**Step 2: Smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
df = pd.DataFrame({
    'execution_timestamp': pd.to_datetime(['2025-04-01']*4),
    'effective_date': pd.to_datetime(['2025-04-03']*4),
    'expiration_date': pd.to_datetime(['2035-04-03']*4),
    'estimated_pv01': [0.0009]*4,
    'notional': [100e6]*4,
    'tenor_years': [10.0, 10.0, 10.0, 0.25],
    'tenor_label': ['10Y']*4,
    'forward_label': ['spot']*4,
    'is_forward': [False]*4,
    'trade_label': ['spot 10Y']*4,
    'fixed_rate': [0.04]*4,
    'package_type': [None]*4,
    'is_spreadover': [False]*4,
    'special_tenor_type': ['STANDARD']*4,
    'upi_underlier_name': ['USD-SOFR-OIS Compound']*4,
    'platform_identifier': ['BGCD']*4,
    'event_action': ['NEWT', 'TERM', 'CORR', 'NEWT'],
})
result = TradeTape(df).compute()
assert list(result['lifecycle_type']) == ['NEW_TRADE','TERMINATION','CORRECTION','NEW_TRADE']
assert list(result['is_new_risk']) == [True, False, False, True]
assert list(result['is_compression']) == [False, True, True, False]
assert result['is_reset_optimization'].iloc[3] == True
print('Lifecycle layer OK')
"
```
Expected: `Lifecycle layer OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape lifecycle layer"
```

---

### Task 4: Implement quality layer (`_enrich_quality`)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace `_enrich_quality` placeholder**

```python
def _enrich_quality(self, df: pd.DataFrame) -> pd.DataFrame:
    """Layer 3: UFRO, off-market, capped, block, quality flags."""
    df = flag_outliers(df, threshold_bp=self._off_market_threshold_bp)

    # Block trade flag
    col = "block_trade_election_indicator"
    if col in df.columns:
        df["is_block"] = df[col].astype(str).str.upper().isin({"TRUE", "1"})
    else:
        df["is_block"] = False

    # Add COMPRESSION to quality_flags for lifecycle events
    if "is_compression" in df.columns and "quality_flags" in df.columns:
        comp_mask = df["is_compression"]
        df.loc[comp_mask, "quality_flags"] = df.loc[comp_mask, "quality_flags"].apply(
            lambda flags: flags + [TradeQualityFlag.COMPRESSION.value]
            if TradeQualityFlag.COMPRESSION.value not in flags
            else flags
        )

    return df
```

**Step 2: Smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
df = pd.DataFrame({
    'execution_timestamp': pd.to_datetime(['2025-04-01']*3),
    'effective_date': pd.to_datetime(['2025-04-03']*3),
    'expiration_date': pd.to_datetime(['2035-04-03']*3),
    'estimated_pv01': [0.0009]*3,
    'notional': [100e6]*3,
    'tenor_years': [10.0]*3,
    'tenor_label': ['10Y']*3,
    'forward_label': ['spot']*3,
    'is_forward': [False]*3,
    'trade_label': ['spot 10Y']*3,
    'fixed_rate': [0.04, 0.04, 0.09],
    'package_type': [None]*3,
    'is_spreadover': [False]*3,
    'special_tenor_type': ['STANDARD']*3,
    'upi_underlier_name': ['USD-SOFR-OIS Compound']*3,
    'platform_identifier': ['BGCD']*3,
    'event_action': ['NEWT']*3,
    'other_payment_type': ['UFRO', '', ''],
    'other_payment_amount': [500000, 0, 0],
    'is_notional_capped': [False, False, True],
    'block_trade_election_indicator': [False, True, False],
})
result = TradeTape(df).compute()
assert result['is_ufro'].iloc[0] == True
assert result['is_block'].iloc[1] == True
assert result['is_capped'].iloc[2] == True
assert result['is_off_market'].iloc[2] == True  # 9% rate vs 4% median
print('Quality layer OK')
"
```
Expected: `Quality layer OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape quality layer"
```

---

### Task 5: Implement packages layer (`_enrich_packages`)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace `_enrich_packages` placeholder**

```python
def _enrich_packages(self, df: pd.DataFrame) -> pd.DataFrame:
    """Layer 4: package detection, structure derivation, leg count."""
    pkg = df["package_type"].fillna("").astype(str).str.upper()
    df["is_package"] = ~pkg.isin({"", "OUTRIGHT", "NAN", "NONE"})

    # Package transaction spread
    spread_col = "package_transaction_spread"
    if spread_col in df.columns:
        spread_val = pd.to_numeric(df[spread_col], errors="coerce")
        df["has_spread"] = spread_val.notna() & (spread_val != 0)
    else:
        df["has_spread"] = False

    # Package leg count and structure
    df["n_package_legs"] = 1
    df["package_structure"] = ""

    pkg_id_col = "package_id"
    if pkg_id_col in df.columns and df["is_package"].any():
        pkg_groups = (
            df[df["is_package"]]
            .groupby(pkg_id_col)
            .agg(
                n_legs=("tenor_label", "size"),
                tenors=("tenor_label", lambda x: "/".join(
                    x.dropna().astype(str).tolist()
                )),
                pkg_type=("trade_type", "first"),
            )
        )
        # Map back to df
        for pkg_id, row in pkg_groups.iterrows():
            mask = df[pkg_id_col] == pkg_id
            df.loc[mask, "n_package_legs"] = row["n_legs"]
            structure = f"{row['tenors']} {row['pkg_type'].title()}"
            df.loc[mask, "package_structure"] = structure.strip()

    # Non-package outrights get a simple structure
    outright_mask = ~df["is_package"]
    if outright_mask.any():
        df.loc[outright_mask, "package_structure"] = (
            df.loc[outright_mask, "tenor_label"].astype(str) + " Outright"
        )

    return df
```

**Step 2: Smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
df = pd.DataFrame({
    'execution_timestamp': pd.to_datetime(['2025-04-01']*3),
    'effective_date': pd.to_datetime(['2025-04-03']*3),
    'expiration_date': pd.to_datetime(['2035-04-03', '2030-04-03', '2035-04-03']),
    'estimated_pv01': [0.0009]*3,
    'notional': [100e6]*3,
    'tenor_years': [10.0, 5.0, 10.0],
    'tenor_label': ['10Y', '5Y', '10Y'],
    'forward_label': ['spot']*3,
    'is_forward': [False]*3,
    'trade_label': ['spot 10Y', 'spot 5Y', 'spot 10Y'],
    'fixed_rate': [0.04]*3,
    'package_type': ['CURVE', 'CURVE', None],
    'package_id': ['PKG1', 'PKG1', None],
    'is_spreadover': [False]*3,
    'special_tenor_type': ['STANDARD']*3,
    'upi_underlier_name': ['USD-SOFR-OIS Compound']*3,
    'platform_identifier': ['BGCD']*3,
    'event_action': ['NEWT']*3,
})
result = TradeTape(df).compute()
assert result['is_package'].iloc[0] == True
assert result['is_package'].iloc[2] == False
assert result['n_package_legs'].iloc[0] == 2
assert '10Y' in result['package_structure'].iloc[0]
assert '5Y' in result['package_structure'].iloc[0]
assert 'Outright' in result['package_structure'].iloc[2]
print('Packages layer OK')
"
```
Expected: `Packages layer OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape packages layer"
```

---

### Task 6: Implement market context layer (`_enrich_context`)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace `_enrich_context` placeholder**

```python
def _enrich_context(self, df: pd.DataFrame) -> pd.DataFrame:
    """Layer 5: event windows, FOMC meeting label/proximity, session."""
    # Event classifications (FOMC, month-end, quarter-end)
    df = add_event_classifications(
        df,
        date_col="execution_timestamp",
        include_me=True,
        include_qe=True,
        include_fomc=True,
    )

    # FOMC meeting label and proximity for FOMC-dated trades
    df["fomc_meeting_label"] = ""
    df["fomc_proximity"] = ""

    fomc_mask = df["special_tenor_type"].astype(str).str.upper() == "FOMC"
    if fomc_mask.any():
        try:
            schedule = load_fomc_schedule()
            if not schedule.empty:
                mat_to_label = dict(
                    zip(
                        schedule["maturity_date"].dt.date,
                        schedule["meeting_label"],
                    )
                )
                eff_to_label = dict(
                    zip(
                        schedule["effective_date"].dt.date,
                        schedule["meeting_label"],
                    )
                )

                def _assign_meeting(row):
                    exp = pd.to_datetime(row.get("expiration_date"))
                    eff = pd.to_datetime(row.get("effective_date"))
                    if pd.notna(exp):
                        d = exp.date() if hasattr(exp, "date") else exp
                        lbl = mat_to_label.get(d)
                        if lbl:
                            return lbl
                    if pd.notna(eff):
                        d = eff.date() if hasattr(eff, "date") else eff
                        lbl = eff_to_label.get(d)
                        if lbl:
                            return lbl
                    return ""

                df.loc[fomc_mask, "fomc_meeting_label"] = (
                    df[fomc_mask].apply(_assign_meeting, axis=1)
                )

                # Proximity requires meeting_eff column
                meeting_eff_map = dict(
                    zip(
                        schedule["meeting_label"],
                        schedule["effective_date"],
                    )
                )
                labelled = df["fomc_meeting_label"] != ""
                if labelled.any():
                    df.loc[labelled, "fomc_proximity"] = df[labelled].apply(
                        lambda r: classify_meeting_proximity(
                            pd.Series({
                                "execution_timestamp": r["execution_timestamp"],
                                "meeting_eff": meeting_eff_map.get(
                                    r["fomc_meeting_label"]
                                ),
                            }),
                            schedule,
                        ),
                        axis=1,
                    )
        except Exception:
            pass  # schedule not available

    # Execution session (Eastern Time)
    ts = pd.to_datetime(df["execution_timestamp"], errors="coerce")
    try:
        ts_et = ts.dt.tz_convert("America/New_York")
    except TypeError:
        try:
            ts_et = ts.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
        except Exception:
            ts_et = ts

    df["execution_hour_et"] = ts_et.dt.hour
    df["execution_session"] = df["execution_hour_et"].map(_hour_to_session)

    return df
```

**Step 2: Smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape, _hour_to_session
# Test session mapping
assert _hour_to_session(3) == 'London'
assert _hour_to_session(9) == 'NY_AM'
assert _hour_to_session(14) == 'NY_PM'
assert _hour_to_session(17) == 'Late'
assert _hour_to_session(20) == 'Asia'
assert _hour_to_session(1) == 'Asia'
print('Context layer sessions OK')
"
```
Expected: `Context layer sessions OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape market context layer"
```

---

### Task 7: Implement relative value layer (`_enrich_rv`)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace `_enrich_rv` placeholder**

```python
def _enrich_rv(self, df: pd.DataFrame) -> pd.DataFrame:
    """Layer 6: temporal clusters, daily VWAP, rate vs VWAP."""
    # Trade clustering
    clustered = trade_clustering(
        df,
        ts_col="execution_timestamp",
        gap_seconds=self._cluster_gap_seconds,
    )
    df["cluster_id"] = clustered["cluster_id"].values
    df["cluster_size"] = df.groupby("cluster_id")["cluster_id"].transform("size")

    # Multi-meeting cluster detection (FOMC trades spanning multiple meetings)
    df["is_multi_meeting_cluster"] = False
    if "fomc_meeting_label" in df.columns:
        fomc_in_cluster = (
            df[df["fomc_meeting_label"] != ""]
            .groupby("cluster_id")["fomc_meeting_label"]
            .nunique()
        )
        multi_ids = fomc_in_cluster[fomc_in_cluster > 1].index
        df.loc[df["cluster_id"].isin(multi_ids), "is_multi_meeting_cluster"] = True

    # Daily tenor VWAP
    df["daily_tenor_vwap"] = np.nan
    df["rate_vs_vwap_bp"] = np.nan

    rate = pd.to_numeric(df.get("fixed_rate"), errors="coerce")
    has_rate = rate.notna()
    if has_rate.any() and "tenor_label" in df.columns and "execution_date" in df.columns:
        vwap_df = daily_vwap(
            df[has_rate],
            group_col="tenor_label",
            rate_col="fixed_rate",
            weight_col="dv01",
            date_col="execution_date",
        )
        if not vwap_df.empty:
            vwap_map = vwap_df.set_index(["execution_date", "tenor_label"])["vwap"]
            keys = list(zip(df["execution_date"], df["tenor_label"]))
            df["daily_tenor_vwap"] = [vwap_map.get(k, np.nan) for k in keys]
            df["rate_vs_vwap_bp"] = (rate - df["daily_tenor_vwap"]) * 10_000

    return df
```

**Step 2: Smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
ts = pd.to_datetime(['2025-04-01 10:00:00', '2025-04-01 10:01:00', '2025-04-01 14:00:00'])
df = pd.DataFrame({
    'execution_timestamp': ts,
    'effective_date': pd.to_datetime(['2025-04-03']*3),
    'expiration_date': pd.to_datetime(['2035-04-03']*3),
    'estimated_pv01': [0.0009]*3,
    'notional': [100e6]*3,
    'tenor_years': [10.0]*3,
    'tenor_label': ['10Y']*3,
    'forward_label': ['spot']*3,
    'is_forward': [False]*3,
    'trade_label': ['spot 10Y']*3,
    'fixed_rate': [0.04, 0.041, 0.039],
    'package_type': [None]*3,
    'is_spreadover': [False]*3,
    'special_tenor_type': ['STANDARD']*3,
    'upi_underlier_name': ['USD-SOFR-OIS Compound']*3,
    'platform_identifier': ['BGCD']*3,
    'event_action': ['NEWT']*3,
})
result = TradeTape(df, cluster_gap_seconds=120).compute()
# First two trades within 60s -> same cluster
assert result['cluster_id'].iloc[0] == result['cluster_id'].iloc[1]
# Third trade 4 hours later -> different cluster
assert result['cluster_id'].iloc[2] != result['cluster_id'].iloc[0]
assert result['cluster_size'].iloc[0] == 2
assert result['daily_tenor_vwap'].notna().all()
assert result['rate_vs_vwap_bp'].notna().all()
print('RV layer OK')
"
```
Expected: `RV layer OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape relative value layer"
```

---

### Task 8: Implement enriched trade label (`_build_enriched_label`)

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace `_build_enriched_label` placeholder**

This mirrors `_backfill_swaption_fields` -- multi-stage prefix construction.

```python
def _build_enriched_label(self, df: pd.DataFrame) -> pd.DataFrame:
    """Layer 7: enrich trade_label with prefix tags.

    Mirrors the swaption ``_backfill_swaption_fields`` pattern:
    prefix tokens are prepended to the base label.

    Token order: [INDEX] [LIFECYCLE] [QUALITY] [STRUCTURE] base_label
    Examples: SOFR spot 10Y, SOFR UFRO spot 5Y, FF CURVE 2Y/5Y
    """
    from SDRUtils.core.tenors import build_trade_label

    # Stage 1: ensure base label exists
    missing_label = (
        df["trade_label"].isna()
        | (df["trade_label"].astype(str).str.strip() == "")
    )
    if missing_label.any():
        df.loc[missing_label, "trade_label"] = df[missing_label].apply(
            lambda r: build_trade_label(
                str(r.get("forward_label", "spot")),
                str(r.get("tenor_label", "UNK")),
                bool(r.get("is_forward", False)),
            ),
            axis=1,
        )

    # Stage 2: for packages, replace base label with slash-joined tenors
    if "package_structure" in df.columns:
        pkg_mask = df["is_package"] & df["package_structure"].astype(str).str.contains("/")
        if pkg_mask.any():
            # Extract tenor part from package_structure ("10Y/5Y Curve" -> "10Y/5Y")
            df.loc[pkg_mask, "trade_label"] = (
                df.loc[pkg_mask, "package_structure"]
                .str.rsplit(" ", n=1)
                .str[0]
            )

    # Stage 3: build prefix tokens
    tokens = pd.Series("", index=df.index, dtype=str)

    # (a) Rate index prefix
    idx_prefix = df["rate_index_clean"].map(_INDEX_PREFIX).fillna("")
    tokens = idx_prefix

    # (b) Lifecycle prefix (non-NEWT only)
    lifecycle_prefix = df["lifecycle_type"].map({
        "TERMINATION": "TERM",
        "CORRECTION": "CORR",
        "MODIFICATION": "MODI",
    }).fillna("")
    has_lifecycle = lifecycle_prefix != ""
    tokens = tokens.where(~has_lifecycle, tokens + " " + lifecycle_prefix)

    # (c) Quality prefix: UFRO or BLOCK (pick the most important one)
    quality_prefix = pd.Series("", index=df.index, dtype=str)
    if "is_ufro" in df.columns:
        quality_prefix = quality_prefix.where(~df["is_ufro"], "UFRO")
    if "is_block" in df.columns:
        # BLOCK only if not already UFRO
        block_only = df.get("is_block", False) & (quality_prefix == "")
        quality_prefix = quality_prefix.where(~block_only, "BLOCK")
    has_quality = quality_prefix != ""
    tokens = tokens.where(~has_quality, tokens + " " + quality_prefix)

    # (d) Structure prefix (CURVE/FLY for packages)
    structure_prefix = pd.Series("", index=df.index, dtype=str)
    if "trade_type" in df.columns:
        pkg_type = df["trade_type"].where(
            df["trade_type"].isin({"CURVE", "FLY"}), ""
        )
        structure_prefix = pkg_type
    has_structure = structure_prefix != ""
    tokens = tokens.where(~has_structure, tokens + " " + structure_prefix)

    # Stage 4: prepend tokens to trade_label
    tokens = tokens.str.strip()
    has_prefix = tokens != ""
    df.loc[has_prefix, "trade_label"] = (
        tokens[has_prefix] + " " + df.loc[has_prefix, "trade_label"].astype(str)
    ).str.strip()

    # Clean up any double spaces
    df["trade_label"] = df["trade_label"].str.replace(r"\s+", " ", regex=True).str.strip()

    return df
```

**Step 2: Smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
df = pd.DataFrame({
    'execution_timestamp': pd.to_datetime(['2025-04-01']*5),
    'effective_date': pd.to_datetime(['2025-04-03']*5),
    'expiration_date': pd.to_datetime(['2035-04-03']*5),
    'estimated_pv01': [0.0009]*5,
    'notional': [100e6]*5,
    'tenor_years': [10.0, 5.0, 10.0, 10.0, 10.0],
    'tenor_label': ['10Y', '5Y', '10Y', '10Y', '10Y'],
    'forward_label': ['spot']*5,
    'is_forward': [False]*5,
    'trade_label': ['spot 10Y', 'spot 5Y', 'spot 10Y', 'spot 10Y', 'spot 10Y'],
    'fixed_rate': [0.04]*5,
    'package_type': [None, None, None, 'CURVE', 'CURVE'],
    'package_id': [None, None, None, 'P1', 'P1'],
    'is_spreadover': [False]*5,
    'special_tenor_type': ['STANDARD']*5,
    'upi_underlier_name': ['USD-SOFR-OIS Compound']*5,
    'platform_identifier': ['BGCD']*5,
    'event_action': ['NEWT', 'TERM', 'NEWT', 'NEWT', 'NEWT'],
    'other_payment_type': ['', '', 'UFRO', '', ''],
    'other_payment_amount': [0, 0, 100000, 0, 0],
    'block_trade_election_indicator': [False]*5,
})
result = TradeTape(df).compute()
labels = list(result['trade_label'])
print(labels)
assert labels[0].startswith('SOFR'), f'Expected SOFR prefix, got {labels[0]}'
assert 'TERM' in labels[1], f'Expected TERM in label, got {labels[1]}'
assert 'UFRO' in labels[2], f'Expected UFRO in label, got {labels[2]}'
assert 'CURVE' in labels[3], f'Expected CURVE in label, got {labels[3]}'
print('Label layer OK')
"
```
Expected: `Label layer OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape enriched trade label"
```

---

### Task 9: Implement `summary()`, `clean_tape()`, `package_summary()`

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py`

**Step 1: Replace the placeholder public methods**

```python
def summary(self) -> Dict[str, Any]:
    """Key stats for the enriched tape."""
    if self._result is None:
        self.compute()
    df = self._result
    n = len(df)
    n_new = int(df["is_new_risk"].sum()) if "is_new_risk" in df.columns else 0
    n_comp = int(df["is_compression"].sum()) if "is_compression" in df.columns else 0

    return {
        "n_trades": n,
        "n_new_risk": n_new,
        "pct_new_risk": round(n_new / max(n, 1) * 100, 1),
        "pct_compression": round(n_comp / max(n, 1) * 100, 1),
        "pct_ufro": round(
            df["is_ufro"].sum() / max(n, 1) * 100, 1
        ) if "is_ufro" in df.columns else 0,
        "pct_block": round(
            df["is_block"].sum() / max(n, 1) * 100, 1
        ) if "is_block" in df.columns else 0,
        "pct_capped": round(
            df["is_capped"].sum() / max(n, 1) * 100, 1
        ) if "is_capped" in df.columns else 0,
        "top_trade_types": (
            df["trade_type"].value_counts().head(5).to_dict()
            if "trade_type" in df.columns else {}
        ),
        "venue_split": (
            df["venue"].value_counts().to_dict()
            if "venue" in df.columns else {}
        ),
        "ccp_split": (
            df["ccp"].value_counts().to_dict()
            if "ccp" in df.columns else {}
        ),
    }


def clean_tape(self) -> pd.DataFrame:
    """Tape filtered to new-risk only, no UFRO/compression/reset-opt.

    Returns the 'real' organic flow: NEWT trades with tenor >= 0.5Y,
    excluding off-market-coupon (UFRO) trades.
    """
    if self._result is None:
        self.compute()
    df = self._result

    mask = pd.Series(True, index=df.index)
    if "is_new_risk" in df.columns:
        mask &= df["is_new_risk"]
    if "is_ufro" in df.columns:
        mask &= ~df["is_ufro"]
    if "is_compression" in df.columns:
        mask &= ~df["is_compression"]
    if "is_reset_optimization" in df.columns:
        mask &= ~df["is_reset_optimization"]

    return df[mask].copy()


def package_summary(self) -> pd.DataFrame:
    """One row per package_id with structure description.

    Returns:
        DataFrame with columns: package_id, package_structure,
        n_legs, trade_type, total_dv01, total_notional, has_spread,
        rate_index_clean.
    """
    if self._result is None:
        self.compute()
    df = self._result

    pkg = df[df.get("is_package", pd.Series(False, index=df.index))].copy()
    if pkg.empty or "package_id" not in pkg.columns:
        return pd.DataFrame()

    return (
        pkg.groupby("package_id")
        .agg(
            package_structure=("package_structure", "first"),
            n_legs=("package_id", "size"),
            trade_type=("trade_type", "first"),
            total_dv01=("dv01", "sum"),
            total_notional=("notional", "sum"),
            has_spread=("has_spread", "first"),
            rate_index_clean=("rate_index_clean", "first"),
        )
        .sort_values("total_dv01", ascending=False)
        .reset_index()
    )
```

**Step 2: Smoke test**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape
df = pd.DataFrame({
    'execution_timestamp': pd.to_datetime(['2025-04-01']*4),
    'effective_date': pd.to_datetime(['2025-04-03']*4),
    'expiration_date': pd.to_datetime(['2035-04-03']*4),
    'estimated_pv01': [0.0009]*4,
    'notional': [100e6]*4,
    'tenor_years': [10.0, 10.0, 10.0, 0.25],
    'tenor_label': ['10Y']*4,
    'forward_label': ['spot']*4,
    'is_forward': [False]*4,
    'trade_label': ['spot 10Y']*4,
    'fixed_rate': [0.04]*4,
    'package_type': [None]*4,
    'is_spreadover': [False]*4,
    'special_tenor_type': ['STANDARD']*4,
    'upi_underlier_name': ['USD-SOFR-OIS Compound']*4,
    'platform_identifier': ['BGCD']*4,
    'event_action': ['NEWT', 'TERM', 'NEWT', 'NEWT'],
    'other_payment_type': ['UFRO', '', '', ''],
    'other_payment_amount': [500000, 0, 0, 0],
})
tape = TradeTape(df)
s = tape.summary()
assert s['n_trades'] == 4
assert s['n_new_risk'] == 3

clean = tape.clean_tape()
# Should exclude: TERM (not new risk), UFRO, reset-opt (tenor 0.25)
assert len(clean) == 1  # only the one clean NEWT with tenor 10Y
print(f'Summary OK: {s[\"n_trades\"]} trades, {s[\"n_new_risk\"]} new risk')
print(f'Clean tape: {len(clean)} trades')
"
```
Expected: Summary and clean tape counts correct.

**Step 3: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "feat(sdr): implement TradeTape summary, clean_tape, package_summary"
```

---

### Task 10: Update `__init__.py` exports

**Files:**
- Modify: `SDRUtils/analytics/__init__.py:78-128`

**Step 1: Add TradeTape import and export**

Add after the FOMC imports block (line 77):

```python
from SDRUtils.analytics.trade_tape import TradeTape
```

Add to `__all__` list (before the closing bracket):

```python
    # Trade Tape
    "TradeTape",
```

**Step 2: Verify import**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "from SDRUtils.analytics import TradeTape; print('Export OK')"`
Expected: `Export OK`

**Step 3: Commit**

```bash
git add SDRUtils/analytics/__init__.py
git commit -m "feat(sdr): export TradeTape from analytics package"
```

---

### Task 11: Integration test with real classified data

**Files:**
- (no new files, uses existing infrastructure)

**Step 1: Run against real data**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir python -c "
from notebooks.sdr._sdr_common import load_classified_trades
from SDRUtils.analytics.trade_tape import TradeTape
import datetime

# Load a small window of real data
df = load_classified_trades(
    datetime.datetime(2025, 4, 1),
    datetime.datetime(2025, 4, 3),
)
print(f'Loaded {len(df)} classified trades')
print(f'Columns: {len(df.columns)}')

tape = TradeTape(df)
result = tape.compute()
print(f'Enriched tape: {len(result)} rows, {len(result.columns)} columns')

s = tape.summary()
for k, v in s.items():
    print(f'  {k}: {v}')

clean = tape.clean_tape()
print(f'Clean tape: {len(clean)} rows ({len(clean)/max(len(result),1)*100:.0f}%)')

pkg = tape.package_summary()
print(f'Packages: {len(pkg)} unique package_ids')

# Verify label enrichment
print()
print('Sample enriched labels:')
for label in result['trade_label'].value_counts().head(10).index:
    print(f'  {label}')
"
```

Expected: Successfully enriches real data, prints summary stats and sample labels.

**Step 2: Fix any issues found**

If columns are missing or type errors occur, fix in the appropriate layer method.

**Step 3: Commit any fixes**

```bash
git add SDRUtils/analytics/trade_tape.py
git commit -m "fix(sdr): address integration issues in TradeTape"
```

---

### Task 12: Create demo notebook `13_trade_tape.ipynb`

**Files:**
- Create: `notebooks/sdr/13_trade_tape.ipynb`

**Step 1: Create notebook with 8 analysis cells**

Cell 1 (markdown): Title
```
# 13. Trade Tape -- Unified SDR Enrichment
```

Cell 2 (code): Load and compute
```python
import datetime
import pandas as pd
from notebooks.sdr._sdr_common import load_classified_trades
from SDRUtils.analytics.trade_tape import TradeTape

df = load_classified_trades(
    datetime.datetime(2025, 4, 1),
    datetime.datetime(2025, 4, 11),
)
tape = TradeTape(df)
enriched = tape.compute()
print(f"Raw: {len(df):,} trades | Enriched: {len(enriched.columns)} columns")
tape.summary()
```

Cell 3 (code): Distribution of trade_type, lifecycle_type, venue
```python
from collections import Counter

for col in ["trade_type", "lifecycle_type", "venue", "ccp", "rate_index_clean"]:
    print(f"\n--- {col} ---")
    print(enriched[col].value_counts().to_string())
```

Cell 4 (code): Clean tape comparison
```python
clean = tape.clean_tape()
raw_dv01 = enriched["dv01"].sum()
clean_dv01 = clean["dv01"].sum()

print(f"Total DV01:  ${raw_dv01/1e9:.1f}B")
print(f"Clean DV01:  ${clean_dv01/1e9:.1f}B")
print(f"Noise:       ${(raw_dv01-clean_dv01)/1e9:.1f}B ({(1-clean_dv01/raw_dv01)*100:.0f}%)")
print(f"\nClean trades: {len(clean):,} / {len(enriched):,} ({len(clean)/len(enriched)*100:.0f}%)")
```

Cell 5 (code): Quality flags distribution
```python
from collections import Counter

all_flags = [f for flags in enriched["quality_flags"] for f in flags]
flag_counts = Counter(all_flags)
n = len(enriched)

print("Quality Flag Distribution:")
for flag, count in flag_counts.most_common():
    print(f"  {flag}: {count:,} ({count/n*100:.1f}%)")

print(f"\nUFRO: {enriched['is_ufro'].sum():,} ({enriched['is_ufro'].mean()*100:.1f}%)")
print(f"Block: {enriched['is_block'].sum():,} ({enriched['is_block'].mean()*100:.1f}%)")
print(f"Capped: {enriched['is_capped'].sum():,} ({enriched['is_capped'].mean()*100:.1f}%)")
print(f"Off-market: {enriched['is_off_market'].sum():,} ({enriched['is_off_market'].mean()*100:.1f}%)")
```

Cell 6 (code): Package summary
```python
pkg = tape.package_summary()
print(f"Unique packages: {len(pkg):,}")
print(f"\nTop 15 package structures:")
print(pkg.groupby("package_structure")["total_dv01"].agg(["count","sum"]).sort_values("sum", ascending=False).head(15).to_string())
```

Cell 7 (code): Execution session distribution
```python
session_stats = enriched.groupby("execution_session").agg(
    trades=("dv01", "size"),
    total_dv01=("dv01", "sum"),
).sort_values("total_dv01", ascending=False)
session_stats["pct"] = (session_stats["total_dv01"] / session_stats["total_dv01"].sum() * 100).round(1)
print(session_stats.to_string())
```

Cell 8 (code): Cluster analysis
```python
print(f"Total clusters: {enriched['cluster_id'].nunique():,}")
print(f"Multi-trade clusters: {(enriched['cluster_size'] > 1).sum():,} trades in clusters of 2+")

cluster_sizes = enriched.groupby("cluster_id").size()
print(f"\nCluster size distribution:")
print(cluster_sizes.value_counts().sort_index().head(10).to_string())

if enriched['is_multi_meeting_cluster'].any():
    n_multi = enriched['is_multi_meeting_cluster'].sum()
    print(f"\nMulti-FOMC-meeting clusters: {n_multi} trades")
```

Cell 9 (code): Cross-tab
```python
cross = pd.crosstab(
    [enriched["trade_type"], enriched["rate_index_clean"]],
    enriched["venue"],
    values=enriched["dv01"],
    aggfunc="sum",
).fillna(0)
cross = cross / 1e6  # millions
print("DV01 Cross-tab (trade_type x rate_index x venue, $M):")
print(cross.round(0).to_string())
```

Cell 10 (code): Sample enriched labels
```python
print("Top 20 enriched trade labels by DV01:")
label_dv01 = enriched.groupby("trade_label")["dv01"].sum().sort_values(ascending=False)
for label, dv01 in label_dv01.head(20).items():
    print(f"  ${dv01/1e6:>8.0f}M  {label}")
```

**Step 2: Run the notebook**

Run: `cd C:/Users/chris/clee/ARBS && conda run -n stir jupyter nbconvert --to notebook --execute notebooks/sdr/13_trade_tape.ipynb --output 13_trade_tape.ipynb --ExecutePreprocessor.timeout=300`

**Step 3: Fix any runtime errors and re-run**

**Step 4: Commit**

```bash
git add notebooks/sdr/13_trade_tape.ipynb
git commit -m "feat(sdr): add trade tape demo notebook (13_trade_tape)"
```

---

### Task 13: Final review and cleanup

**Files:**
- Review: `SDRUtils/analytics/trade_tape.py`

**Step 1: Run the simplify skill to check for code quality issues**

Use `superpowers:requesting-code-review` skill.

**Step 2: Fix any issues found**

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore(sdr): trade tape final cleanup"
```
