"""
Risk reversal detection for swaption packages.

Detects risk reversals: 4-leg structures with wings + delta hedge (3 strikes, 2 notionals).
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.swaption.utils import (
    compute_package_id,
    build_package_reason,
    ensure_package_columns,
)


def detect_risk_reversals_packages(
    df: pd.DataFrame,
    *,
    # Time window parameters
    time_window_seconds: int = 60,
    # Matching tolerances
    strike_tolerance: float = 0.0001,
    notional_tolerance_pct: float = 0.05,
    middle_notional_max_ratio: float = 0.5,
    # Structural requirements
    require_same_expiration: bool = True,
    require_same_tenor: bool = True,
    require_same_forward: bool = True,
    require_directional_structure: bool = True,
    require_same_event_action: bool = False,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    underlier_col: str = "upi_underlier_name",
    trade_label_col: str = "trade_label",
    trade_id_col: str = "trade_id",
    strike_col: str = "strike",
    expiration_col: str = "expiration_date",
    tenor_col: str = "tenor_years",
    forward_col: str = "forward_start_years",
    notional_col: str = "notional",
    upi_col: str = "unique_product_identifier",
    event_action_col: str = "event_action",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    require_same_underlier: bool = False,
    require_same_index: bool = True,
    # Platform filters
    platform_allowlist: Optional[List[str]] = None,
    platform_blocklist: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Detect swaption risk reversals with delta-hedge legs.

    Pattern (inter-dealer):
      - 4 trades
      - 3 distinct strikes (middle strike appears twice)
      - 2 distinct notionals (middle strike notional is smaller)
      - 2 distinct unique_product_identifiers
      - Same event_action across all legs (optional, not required by default)

    Args:
        df: Classifications dataframe with swaption trades
        time_window_seconds: Max time gap between legs
        strike_tolerance: Absolute strike tolerance for grouping
        notional_tolerance_pct: Relative notional tolerance for grouping
        middle_notional_max_ratio: Max ratio of middle notional to wing notional
        require_same_expiration: Require same expiration_date across legs
        require_same_tenor: Require same tenor_years across legs
        require_same_forward: Require same forward_start_years across legs
        require_directional_structure: Require payer/receiver direction alignment
        require_same_event_action: Require same event_action across all legs (default False)
        product_col: Column name for product type
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        underlier_col: Column name for underlier
        trade_label_col: Column name for trade label
        trade_id_col: Column name for trade ID
        strike_col: Column name for strike
        expiration_col: Column name for expiration date
        tenor_col: Column name for tenor years
        forward_col: Column name for forward start years
        notional_col: Column name for notional
        upi_col: Column name for unique product identifier
        event_action_col: Column name for event action
        require_same_platform: Require same platform for matching
        require_same_currency: Require same currency for matching
        require_same_underlier: Require same underlier for matching
        require_same_index: Require the same swaption index for matching
        platform_allowlist: If set, only these platforms are considered
        platform_blocklist: If set, these platforms are excluded

    Returns:
        DataFrame with risk reversal annotations:
        - package_type: "RISK_REVERSAL"
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the package
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation string
        - package_legs_count: Always 4 for risk reversals
    """
    if df.empty:
        return df

    out = ensure_package_columns(df, package_col=package_col)

    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

    if platform_allowlist:
        candidate_mask &= out[platform_col].isin(platform_allowlist)
    if platform_blocklist:
        candidate_mask &= ~out[platform_col].isin(platform_blocklist)

    cand = out.loc[candidate_mask].copy()
    if cand.empty:
        return out

    cand["_t"] = _ensure_int64_epoch_seconds(cand[exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    strike_vals = pd.to_numeric(cand[strike_col], errors="coerce").to_numpy(dtype=np.float64)
    notional_vals = pd.to_numeric(cand[notional_col], errors="coerce").to_numpy(dtype=np.float64)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    trade_ids = cand[trade_id_col].astype(str).to_numpy()
    platforms = cand[platform_col].astype("string").to_numpy() if platform_col in cand.columns else None
    currencies = cand[currency_col].astype("string").to_numpy() if currency_col in cand.columns else None
    underliers = cand[underlier_col].astype("string").to_numpy() if underlier_col in cand.columns else None
    trade_labels = cand[trade_label_col].astype("string").to_numpy() if trade_label_col in cand.columns else None
    expirations = cand[expiration_col].astype("string").to_numpy() if expiration_col in cand.columns else None
    tenors = pd.to_numeric(cand[tenor_col], errors="coerce").to_numpy(dtype=np.float64) if tenor_col in cand.columns else None
    forwards = pd.to_numeric(cand[forward_col], errors="coerce").to_numpy(dtype=np.float64) if forward_col in cand.columns else None
    product_labels = cand[product_col].astype(str).to_numpy()
    upis = cand[upi_col].astype("string").to_numpy() if upi_col in cand.columns else None
    event_actions = cand[event_action_col].astype("string").to_numpy() if event_action_col in cand.columns else None

    matched = np.zeros(len(cand), dtype=bool)
    pkg_ids = np.full(len(cand), "", dtype=object)
    pkg_type = np.full(len(cand), "", dtype=object)
    pkg_legs = np.full(len(cand), None, dtype=object)
    pkg_conf = np.full(len(cand), 0.0, dtype=np.float64)
    pkg_reason = np.full(len(cand), "", dtype=object)
    pkg_legs_count = np.full(len(cand), 0, dtype=np.int32)

    def _cluster_values(values: np.ndarray, tol: float) -> List[List[int]]:
        clusters: List[List[int]] = []
        for idx, val in enumerate(values):
            placed = False
            for cluster in clusters:
                cvals = values[cluster]
                avg = float(np.nanmean(cvals))
                if avg <= 0:
                    continue
                if abs(val - avg) / avg <= tol:
                    cluster.append(idx)
                    placed = True
                    break
            if not placed:
                clusters.append([idx])
        return clusters

    def _strike_groups(strikes: np.ndarray) -> List[List[int]]:
        if strike_tolerance <= 0:
            groups: Dict[float, List[int]] = {}
            for idx, val in enumerate(strikes):
                groups.setdefault(val, []).append(idx)
            return list(groups.values())
        buckets: Dict[int, List[int]] = {}
        for idx, val in enumerate(strikes):
            bucket = int(np.round(val / strike_tolerance))
            buckets.setdefault(bucket, []).append(idx)
        return list(buckets.values())

    def _direction(label: str) -> int:
        upper = label.upper()
        if "PAYER" in upper or "CALL" in upper:
            return 1
        if "RECEIVER" in upper or "PUT" in upper:
            return -1
        return 0

    def _directional_ok(indices: List[int], ordered_groups: List[Tuple[float, List[int]]]) -> bool:
        if not require_directional_structure:
            return True

        # Relaxed check: Simply ensure Low and High wings are opposite types.
        # This supports both (Low=Rec, High=Pay) AND (Low=Pay, High=Rec)

        low_group = ordered_groups[0][1]
        high_group = ordered_groups[2][1]

        # Directions of the wings
        low_dir = _direction(product_labels[indices[low_group[0]]])
        high_dir = _direction(product_labels[indices[high_group[0]]])

        # Must have valid directions (not unknown)
        if low_dir == 0 or high_dir == 0:
            return False

        # Wings must be opposite (one Payer, one Receiver)
        if low_dir == high_dir:
            return False

        return True

    def _extract_index_name(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if "CONSTANT" in text:
            text = text.split("CONSTANT", 1)[0].strip()
        return text

    def _same_index_ok(indices: List[int]) -> bool:
        if not require_same_index:
            return True
        if trade_labels is None:
            # Allow detection when trade_label data is missing
            return True
        raw_labels = [str(trade_labels[i]) for i in indices]
        has_libor = any("LIBOR" in name.upper() for name in raw_labels)
        has_sofr = any("SOFR" in name.upper() for name in raw_labels)
        # Mixed LIBOR/SOFR is not allowed
        if has_libor and has_sofr:
            return False
        if underliers is None:
            # Allow detection when underlier data is missing
            return True
        index_names = {_extract_index_name(str(underliers[i])) for i in indices}
        index_names.discard("")
        # If no valid index names found, treat as acceptable (data missing/incomplete)
        if len(index_names) == 0:
            return True
        # Otherwise require exactly 1 unique index name
        return len(index_names) == 1

    def _unique_upi_count_ok(indices: List[int]) -> bool:
        """Check that exactly 2 unique UPIs exist across the 4 legs."""
        if upis is None:
            # Allow detection when UPI data is missing
            return True
        unique_upis = set()
        for i in indices:
            val = str(upis[i])
            if val and val not in ("", "nan", "<NA>", "None"):
                unique_upis.add(val)
        # If no valid UPIs found, treat as acceptable (data missing/incomplete)
        if len(unique_upis) == 0:
            return True
        # Otherwise require exactly 2 unique UPIs
        return len(unique_upis) == 2

    def _same_event_action_ok(indices: List[int]) -> bool:
        """Check that all legs have the same event_action value."""
        if not require_same_event_action:
            return True
        if event_actions is None:
            # Allow detection when event_action data is missing
            return True
        actions = set()
        for i in indices:
            val = str(event_actions[i])
            if val and val not in ("", "nan", "<NA>", "None"):
                actions.add(val)
        # If no valid event_actions found, treat as acceptable (data missing/incomplete)
        if len(actions) == 0:
            return True
        # Otherwise require all legs to have the same event_action
        return len(actions) == 1

    def _is_risk_reversal(indices: List[int]) -> bool:
        strikes = strike_vals[indices]
        notionals = np.abs(notional_vals[indices])

        if np.any(np.isnan(strikes)) or np.any(np.isnan(notionals)):
            return False

        if not _same_index_ok(indices):
            return False

        # Require exactly 2 unique UPIs
        if not _unique_upi_count_ok(indices):
            return False

        # Require same event_action across all legs
        if not _same_event_action_ok(indices):
            return False

        payer_count = 0
        receiver_count = 0
        for idx in indices:
            direction = _direction(product_labels[idx])
            if direction == 1:
                payer_count += 1
            elif direction == -1:
                receiver_count += 1

        if payer_count != 2 or receiver_count != 2:
            return False

        strike_groups_list = _strike_groups(strikes)
        # Classic 3-strike only for now (reference logic flow)
        if len(strike_groups_list) != 3:
            return False

        strike_counts = sorted(len(g) for g in strike_groups_list)
        if strike_counts != [1, 1, 2]:
            return False

        strike_levels = [float(np.nanmean(strikes[group])) for group in strike_groups_list]
        ordered = sorted(zip(strike_levels, strike_groups_list), key=lambda x: x[0])
        middle_group = ordered[1][1]

        # ATM must have 2 legs
        if len(middle_group) != 2:
            return False

        if not _directional_ok(indices, ordered):
            return False

        notional_groups = _cluster_values(notionals, notional_tolerance_pct)
        if len(notional_groups) != 2:
            return False

        group_means = [float(np.nanmean(notionals[group])) for group in notional_groups]
        low_idx = int(np.argmin(group_means))  # Small notional group index
        high_idx = int(np.argmax(group_means))  # Large notional group index
        low_mean = group_means[low_idx]
        high_mean = group_means[high_idx]

        if low_mean <= 0 or high_mean <= 0:
            return False

        # Relaxed notional ratio check.
        # Reference script implies ATM < Wing is sufficient.
        # Enforcing <= 0.5 ratio kills valid trades like 80M ATM / 100M Wing.
        # We assume 0.95 to ensure they are distinct and smaller.
        if low_mean > high_mean * 0.95:
            return False

        low_group_indices = set(notional_groups[low_idx])
        middle_indices = {indices[idx] for idx in middle_group}

        # The Middle Strike trades MUST be the ones with the Smaller Notional
        if not middle_indices.issubset({indices[idx] for idx in low_group_indices}):
            return False

        notional_counts = sorted(len(g) for g in notional_groups)
        if notional_counts != [2, 2]:
            return False

        return True

    def _econ_key(i: int) -> Tuple[Any, ...]:
        parts: List[Any] = []
        if require_same_platform and platforms is not None:
            parts.append(platforms[i])
        if require_same_currency and currencies is not None:
            parts.append(currencies[i])
        if require_same_underlier and underliers is not None:
            parts.append(underliers[i])
        if require_same_expiration and expirations is not None:
            parts.append(expirations[i])
        if require_same_tenor and tenors is not None:
            parts.append(tenors[i])
        if require_same_forward and forwards is not None:
            parts.append(forwards[i])
        return tuple(parts)

    group_indices: Dict[Tuple[Any, ...], List[int]] = {}
    for i in range(len(cand)):
        key = _econ_key(i)
        group_indices.setdefault(key, []).append(i)

    for key, indices in group_indices.items():
        window: List[int] = []
        left = 0

        for idx in indices:
            while left < len(window) and (tsec[idx] - tsec[window[left]] > time_window_seconds):
                left += 1
            window = window[left:] + [idx]
            left = 0

            if len(window) < 4:
                continue

            for combo in itertools.combinations(window, 4):
                if any(matched[i] for i in combo):
                    continue
                if not _is_risk_reversal(list(combo)):
                    continue

                combo_list = list(combo)
                time_delta_max = float(np.max(tsec[combo_list]) - np.min(tsec[combo_list]))

                platform = key[0] if key else "UNKNOWN"
                pid = compute_package_id(
                    [trade_ids[i] for i in combo_list],
                    str(platform),
                    int(tsec[combo_list[0]] // 30),
                    "RISK_REVERSAL",
                )

                confidence = 0.8
                if time_delta_max <= 5:
                    confidence += 0.1
                confidence = min(confidence, 1.0)

                strike_values = sorted({strike_vals[i] for i in combo_list})
                notional_values = sorted({abs(notional_vals[i]) for i in combo_list})
                reason = build_package_reason(
                    platform=str(platform),
                    time_delta_max_seconds=time_delta_max,
                    vega_cluster_spread_pct=None,
                    premium_mode="RISK_REVERSAL",
                    num_legs=4,
                    identical_timestamps=(time_delta_max < 1),
                    extra_info=f"strikes={strike_values}; notionals={notional_values}",
                )

                legs_list = [str(trade_ids[i]) for i in combo_list]
                for i in combo_list:
                    matched[i] = True
                    pkg_ids[i] = pid
                    pkg_type[i] = "RISK_REVERSAL"
                    pkg_legs[i] = legs_list
                    pkg_conf[i] = confidence
                    pkg_reason[i] = reason
                    pkg_legs_count[i] = 4

                break

    res = pd.DataFrame(
        {
            trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
            "_pkg_conf": pkg_conf,
            "_pkg_reason": pkg_reason,
            "_pkg_legs_count": pkg_legs_count,
        }
    )

    out[trade_id_col] = out[trade_id_col].astype(str)
    out = out.merge(
        res[[trade_id_col, "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]],
        on=trade_id_col,
        how="left",
    )

    detected_mask = out["_pkg_id"].notna() & (out["_pkg_id"] != "")
    out.loc[detected_mask, package_col] = out.loc[detected_mask, "_pkg_type"]
    out.loc[detected_mask, "package_id"] = out.loc[detected_mask, "_pkg_id"]
    out.loc[detected_mask, "package_legs"] = out.loc[detected_mask, "_pkg_legs"]
    out.loc[detected_mask, "package_confidence"] = out.loc[detected_mask, "_pkg_conf"]
    out.loc[detected_mask, "package_reason"] = out.loc[detected_mask, "_pkg_reason"]
    out.loc[detected_mask, "package_legs_count"] = out.loc[detected_mask, "_pkg_legs_count"]

    temp_cols = ["_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]
    out.drop(columns=[c for c in temp_cols if c in out.columns], inplace=True, errors="ignore")

    return out
