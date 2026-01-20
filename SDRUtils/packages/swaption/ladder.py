"""
Swaption Ladder (Christmas Tree) detection for swaption packages.

Detects ladder structures: 3+ strikes, same option type, asymmetric notionals.

A ladder is a vertical structure with 3+ legs where:
- All legs are same option type (all payers OR all receivers)
- Same underlying tenor (expiry and tail)
- 3+ distinct strikes with minimum spacing
- Asymmetric notionals (at least one strike with different notional)

Common patterns:
- 1x1x2: Long 2 strikes, short 2x at third strike
- 2x1x1: Short 2x at one strike, long at two others
- 1x1x1x2: 4-strike ladder

Direction determination:
- RECEIVER ladder: Higher notional at LOW strike = BEAR; HIGH strike = BULL
- PAYER ladder: Higher notional at HIGH strike = BEAR; LOW strike = BULL
"""

from __future__ import annotations

import itertools
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.swaption.utils import (
    compute_package_id,
    build_package_reason,
    ensure_package_columns,
    is_payer,
    is_receiver,
    check_economic_filters,
)


# =============================================================================
# Configuration
# =============================================================================

# Platform-specific time windows (seconds)
# IDB platforms have tighter execution, customer platforms more latency
PLATFORM_TIME_WINDOWS = {
    "BGCD": 30,
    "ISWV": 25,
    "TPSE": 30,
    "BILT": 15,  # BILT often has identical timestamps for packages
    "XXXX": 120,
    "TWSF": 60,
    "BBSF": 60,
    "XOFF": 60,
}
DEFAULT_TIME_WINDOW_SEC = 120

# IDB platforms for confidence scoring
IDB_PLATFORMS = {"BGCD", "ISWV", "TPSE"}

# Default detection parameters
DEFAULT_MIN_LEGS = 3  # Minimum legs for a ladder (distinguishes from vertical spread)
DEFAULT_MIN_STRIKES = 2  # Minimum distinct strikes
DEFAULT_MIN_STRIKE_WIDTH_BPS = 15  # Minimum strike separation in basis points
DEFAULT_NOTIONAL_RATIO_TOLERANCE = 0.15  # 15% tolerance for notional ratios
DEFAULT_LADDER_ITERATION_TIMEOUT_SEC = 5.0  # Hard timeout per cluster iteration


def _get_platform_time_window(platform: str, override: Optional[int] = None) -> int:
    """Get time window for platform, with optional override."""
    if override is not None:
        return override
    return PLATFORM_TIME_WINDOWS.get(platform, DEFAULT_TIME_WINDOW_SEC)


def _analyze_ladder_structure(
    strikes: List[float],
    notionals: List[float],
    opt_type: str,
) -> Tuple[str, str, List[float]]:
    """
    Analyze strikes and notionals to determine ladder structure.

    Args:
        strikes: Sorted list of strikes in the ladder
        notionals: Notionals corresponding to each strike (aggregated)
        opt_type: "PAYER" or "RECEIVER"

    Returns:
        Tuple of (structure_label, direction, notional_ratios)
        - structure_label: e.g., "1x1x2", "2x1x1"
        - direction: "BULL" or "BEAR"
        - notional_ratios: ratios relative to minimum notional
    """
    if len(strikes) < 2 or len(notionals) < 2:
        return "1x1", "NEUTRAL", [1.0]

    # Sort by strike
    sorted_pairs = sorted(zip(strikes, notionals), key=lambda x: x[0])
    sorted_strikes = [p[0] for p in sorted_pairs]
    sorted_notionals = [p[1] for p in sorted_pairs]

    # Find minimum notional as base unit
    min_notional = min(sorted_notionals)
    if min_notional <= 0:
        min_notional = 1.0

    # Calculate ratios relative to minimum
    ratios = [n / min_notional for n in sorted_notionals]

    # Round ratios to nearest 0.5 for labeling
    rounded_ratios = [round(r * 2) / 2 for r in ratios]

    # Build structure label (e.g., "1x1x2")
    def _format_ratio(r: float) -> str:
        if r == int(r):
            return str(int(r))
        return str(r)

    structure_label = "x".join([_format_ratio(r) for r in rounded_ratios])

    # Determine direction based on where the higher notional sits
    # For RECEIVER ladder:
    #   - Higher notional at LOW strike = BEAR (profits if rates stay high/rise)
    #   - Higher notional at HIGH strike = BULL (profits if rates fall moderately)
    # For PAYER ladder:
    #   - Higher notional at HIGH strike = BEAR
    #   - Higher notional at LOW strike = BULL
    max_notional_idx = sorted_notionals.index(max(sorted_notionals))

    if opt_type == "RECEIVER":
        direction = "BEAR" if max_notional_idx == 0 else "BULL"
    else:  # PAYER
        direction = "BEAR" if max_notional_idx == len(sorted_notionals) - 1 else "BULL"

    return structure_label, direction, ratios


def detect_ladder_packages(
    df: pd.DataFrame,
    *,
    # Time window parameters
    time_window_seconds: Optional[int] = None,  # None = use platform-specific defaults
    # Ladder parameters
    min_legs: int = DEFAULT_MIN_LEGS,
    min_strikes: int = DEFAULT_MIN_STRIKES,
    min_strike_width_bps: float = DEFAULT_MIN_STRIKE_WIDTH_BPS,
    notional_ratio_tolerance: float = DEFAULT_NOTIONAL_RATIO_TOLERANCE,
    ladder_iteration_timeout_seconds: Optional[float] = DEFAULT_LADDER_ITERATION_TIMEOUT_SEC,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    underlier_col: str = "upi_underlier_name",
    trade_id_col: str = "trade_id",
    strike_col: str = "strike",
    expiration_col: str = "expiration_date",
    tenor_col: str = "tenor_years",
    forward_col: str = "forward_start_years",
    notional_col: str = "notional",
    premium_col: str = "premium",
    package_indicator_col: str = "package_indicator",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    require_same_underlier: bool = False,
    # Platform filters
    platform_allowlist: Optional[List[str]] = None,
    platform_blocklist: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Detect ladder (christmas tree) structures in swaption trades.

    A ladder consists of:
    - 3+ legs with same option type (all payers OR all receivers)
    - Same underlying tenor (same expiry and tail)
    - 3+ distinct strikes (minimum spacing enforced)
    - Asymmetric notionals (at least one strike with different notional)

    Direction determination:
    - RECEIVER: long higher strikes, short lower = BULL (rates falling)
    - PAYER: long lower strikes, short higher = BULL (rates rising)

    Args:
        df: Classifications dataframe with swaption trades
        time_window_seconds: Override platform-specific time windows (None = auto)
        min_legs: Minimum legs to qualify as ladder (default 3)
        min_strikes: Minimum distinct strikes (default 2)
        min_strike_width_bps: Minimum strike separation in bps (default 15)
        notional_ratio_tolerance: Tolerance for notional ratio matching (default 0.15)
        ladder_iteration_timeout_seconds: Hard timeout per cluster iteration in seconds (None to disable)
        product_col: Column name for product type
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        underlier_col: Column name for underlier
        trade_id_col: Column name for trade ID
        strike_col: Column name for strike
        expiration_col: Column name for expiration date
        tenor_col: Column name for tenor years
        forward_col: Column name for forward start years
        notional_col: Column name for notional
        premium_col: Column name for premium
        package_indicator_col: Column name for package indicator
        require_same_platform: Require same platform for matching
        require_same_currency: Require same currency for matching
        require_same_underlier: Require same underlier for matching
        platform_allowlist: If set, only these platforms are considered
        platform_blocklist: If set, these platforms are excluded

    Returns:
        DataFrame with ladder annotations:
        - package_type: "RECEIVER_LADDER" or "PAYER_LADDER"
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the ladder
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation with direction
        - package_legs_count: Number of legs (3+)
        - ladder_structure: Structure label (e.g., "1x1x2")
        - ladder_direction: "BULL" or "BEAR"
        - ladder_strikes: List of strikes in the ladder
        - ladder_notionals: List of notionals per strike
    """
    if df.empty:
        return df

    out = ensure_package_columns(df, package_col=package_col)

    # Initialize ladder-specific columns
    for col in ["ladder_structure", "ladder_direction", "ladder_strikes", "ladder_notionals"]:
        if col not in out.columns:
            out[col] = None

    # Filter to swaption candidates not already packaged
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

    if platform_allowlist:
        candidate_mask &= out[platform_col].isin(platform_allowlist)
    if platform_blocklist:
        candidate_mask &= ~out[platform_col].isin(platform_blocklist)

    cand = out.loc[candidate_mask].copy()
    if len(cand) < min_legs:
        return out

    # Prepare data arrays
    cand["_t"] = _ensure_int64_epoch_seconds(cand[exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    n = len(cand)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    strike_vals = pd.to_numeric(cand[strike_col], errors="coerce").to_numpy(dtype=np.float64)
    notional_vals = pd.to_numeric(cand[notional_col], errors="coerce").to_numpy(dtype=np.float64)
    tenor_vals = pd.to_numeric(cand[tenor_col], errors="coerce").to_numpy(dtype=np.float64)
    forward_vals = pd.to_numeric(cand[forward_col], errors="coerce").to_numpy(dtype=np.float64)
    trade_ids = cand[trade_id_col].astype(str).to_numpy()
    product_labels = cand[product_col].astype(str).to_numpy()
    platforms = cand[platform_col].astype("string").to_numpy() if platform_col in cand.columns else None
    currencies = cand[currency_col].astype("string").to_numpy() if currency_col in cand.columns else None
    underliers = cand[underlier_col].astype("string").to_numpy() if underlier_col in cand.columns else None
    expirations = cand[expiration_col].astype("string").to_numpy() if expiration_col in cand.columns else None
    premiums = pd.to_numeric(cand[premium_col], errors="coerce").to_numpy(dtype=np.float64) if premium_col in cand.columns else None
    pkg_ind = cand[package_indicator_col].to_numpy() if package_indicator_col in cand.columns else None

    # Output tracking
    matched = np.zeros(n, dtype=bool)
    pkg_ids = np.full(n, "", dtype=object)
    pkg_type = np.full(n, "", dtype=object)
    pkg_legs = np.full(n, None, dtype=object)
    pkg_conf = np.full(n, 0.0, dtype=np.float64)
    pkg_reason = np.full(n, "", dtype=object)
    pkg_legs_count = np.full(n, 0, dtype=np.int32)
    ladder_structure = np.full(n, None, dtype=object)
    ladder_direction = np.full(n, None, dtype=object)
    ladder_strikes = np.full(n, None, dtype=object)
    ladder_notionals = np.full(n, None, dtype=object)

    def _get_option_type(idx: int) -> Optional[str]:
        """Get option type for trade index."""
        if is_payer(product_labels[idx]):
            return "PAYER"
        elif is_receiver(product_labels[idx]):
            return "RECEIVER"
        return None

    def _same_tenor(i: int, j: int) -> bool:
        """Check if same underlying tenor (same expiry and tail)."""
        # Same expiration date
        if expirations is not None:
            if expirations[i] != expirations[j]:
                return False
        # Same underlying tenor (tail)
        if pd.notna(tenor_vals[i]) and pd.notna(tenor_vals[j]):
            if abs(tenor_vals[i] - tenor_vals[j]) > 0.01:
                return False
        # Same forward start (expiry)
        if pd.notna(forward_vals[i]) and pd.notna(forward_vals[j]):
            if abs(forward_vals[i] - forward_vals[j]) > 0.01:
                return False
        return True

    def _validate_ladder_cluster(indices: List[int], platform: str) -> Optional[Dict]:
        """
        Validate if a cluster of trades forms a valid ladder.

        Returns dict with ladder info if valid, None otherwise.
        """
        if len(indices) < min_legs:
            return None

        # Must all be same option type
        opt_types = set(_get_option_type(i) for i in indices)
        opt_types.discard(None)
        if len(opt_types) != 1:
            return None
        opt_type = opt_types.pop()

        # Must all be same tenor
        ref_idx = indices[0]
        if not all(_same_tenor(ref_idx, i) for i in indices[1:]):
            return None

        # Economic filters
        for i in indices[1:]:
            if not check_economic_filters(
                ref_idx, i,
                platforms=platforms,
                currencies=currencies,
                underliers=underliers,
                require_same_platform=require_same_platform,
                require_same_currency=currencies is not None and require_same_currency,
                require_same_underlier=underliers is not None and require_same_underlier,
            ):
                return None

        # Aggregate notionals by strike
        strike_data: Dict[float, Dict] = {}
        for i in indices:
            strike = round(strike_vals[i], 6)  # Round for grouping
            if strike not in strike_data:
                strike_data[strike] = {"notional": 0, "premium": 0, "indices": []}
            strike_data[strike]["notional"] += abs(notional_vals[i])
            if premiums is not None and pd.notna(premiums[i]):
                strike_data[strike]["premium"] += abs(premiums[i])
            strike_data[strike]["indices"].append(i)

        unique_strikes = sorted(strike_data.keys())

        # Need minimum distinct strikes
        if len(unique_strikes) < min_strikes:
            return None

        # Check strike spacing (minimum width)
        if len(unique_strikes) > 1:
            min_width_bps = min(
                (unique_strikes[i + 1] - unique_strikes[i]) * 10000
                for i in range(len(unique_strikes) - 1)
            )
            if min_width_bps < min_strike_width_bps:
                return None

        # Get notionals per strike
        notionals_per_strike = [strike_data[s]["notional"] for s in unique_strikes]

        # Must have asymmetric notionals (not all equal)
        # Use tolerance for "equal" check
        unique_notionals = set()
        for n_val in notionals_per_strike:
            # Check if this notional is close to any existing
            found_match = False
            for existing in unique_notionals:
                if abs(n_val - existing) / max(n_val, existing, 1) < notional_ratio_tolerance:
                    found_match = True
                    break
            if not found_match:
                unique_notionals.add(n_val)

        if len(unique_notionals) < 2:
            return None  # All notionals effectively equal - not a ladder

        # Analyze structure
        structure_label, direction, ratios = _analyze_ladder_structure(
            unique_strikes, notionals_per_strike, opt_type
        )

        # Calculate time span
        exec_times = [tsec[i] for i in indices]
        time_delta = max(exec_times) - min(exec_times)

        # Calculate total premium
        total_premium = sum(
            strike_data[s]["premium"] for s in unique_strikes
        )

        return {
            "opt_type": opt_type,
            "strikes": unique_strikes,
            "notionals": notionals_per_strike,
            "structure_label": structure_label,
            "direction": direction,
            "ratios": ratios,
            "time_delta": time_delta,
            "total_premium": total_premium,
        }

    # Group by platform, then by economic key (currency, underlier)
    # Process each group to find ladder clusters

    # Build economic grouping key
    def _econ_key(idx: int) -> Tuple:
        """Build economic grouping key for a trade."""
        parts = []
        if platforms is not None:
            parts.append(str(platforms[idx]))
        if currencies is not None and require_same_currency:
            parts.append(str(currencies[idx]))
        if underliers is not None and require_same_underlier:
            parts.append(str(underliers[idx]))
        if expirations is not None:
            parts.append(str(expirations[idx]))
        if pd.notna(tenor_vals[idx]):
            parts.append(f"tenor_{tenor_vals[idx]:.2f}")
        if pd.notna(forward_vals[idx]):
            parts.append(f"fwd_{forward_vals[idx]:.2f}")
        return tuple(parts)

    # Group indices by economic key and option type
    groups: Dict[Tuple, Dict[str, List[int]]] = defaultdict(lambda: {"PAYER": [], "RECEIVER": []})
    for idx in range(n):
        if matched[idx]:
            continue
        opt_type = _get_option_type(idx)
        if opt_type is None:
            continue
        key = _econ_key(idx)
        groups[key][opt_type].append(idx)

    # Process each group
    for econ_key, type_indices in groups.items():
        for opt_type, indices in type_indices.items():
            if len(indices) < min_legs:
                continue

            # Sort by time
            indices = sorted(indices, key=lambda i: tsec[i])

            # Get platform for time window
            platform = str(platforms[indices[0]]) if platforms is not None else "UNKNOWN"
            time_window = _get_platform_time_window(platform, time_window_seconds)

            # Sliding window to find clusters
            i = 0
            while i < len(indices):
                iteration_deadline = None
                if ladder_iteration_timeout_seconds is not None:
                    iteration_deadline = time.monotonic() + ladder_iteration_timeout_seconds

                if matched[indices[i]]:
                    i += 1
                    continue

                # Collect trades within time window
                cluster = [indices[i]]
                j = i + 1

                while j < len(indices):
                    if matched[indices[j]]:
                        j += 1
                        continue

                    time_diff = tsec[indices[j]] - tsec[indices[i]]
                    if time_diff <= time_window:
                        cluster.append(indices[j])
                    elif time_diff > time_window:
                        break
                    j += 1

                # Try to validate as ladder
                if len(cluster) >= min_legs:
                    # Try largest possible cluster first, then smaller subsets
                    timed_out = False
                    for size in range(len(cluster), min_legs - 1, -1):
                        for subset in itertools.combinations(cluster, size):
                            if iteration_deadline is not None and time.monotonic() > iteration_deadline:
                                timed_out = True
                                break
                            subset_list = list(subset)
                            # Skip if any already matched
                            if any(matched[idx] for idx in subset_list):
                                continue

                            ladder_info = _validate_ladder_cluster(subset_list, platform)
                            if ladder_info is not None:
                                # Found a valid ladder
                                opt_type_str = ladder_info["opt_type"]
                                pkg_type_str = f"{opt_type_str}_LADDER"

                                # Calculate confidence
                                exec_times = [tsec[idx] for idx in subset_list]
                                identical_ts = len(set(exec_times)) == 1
                                time_delta = ladder_info["time_delta"]

                                if platform in IDB_PLATFORMS:
                                    confidence = 0.9  # IDB = high confidence
                                elif identical_ts:
                                    confidence = 0.8  # Identical timestamps
                                elif pkg_ind is not None and any(
                                    pkg_ind[idx] == True or pkg_ind[idx] == "Y"
                                    for idx in subset_list
                                ):
                                    confidence = 0.75  # Has package indicator
                                else:
                                    confidence = 0.6  # Customer platform, spread timestamps

                                # Adjust confidence based on time delta
                                if time_delta < 5:
                                    confidence = min(confidence + 0.1, 1.0)

                                # Generate package ID
                                pid = compute_package_id(
                                    [trade_ids[idx] for idx in subset_list],
                                    platform,
                                    int(min(exec_times) // 30),
                                    pkg_type_str,
                                )

                                # Build reason string
                                strikes_str = "/".join([f"{s * 100:.2f}%" for s in ladder_info["strikes"]])
                                notionals_str = "/".join([f"${n / 1e6:.0f}mm" for n in ladder_info["notionals"]])

                                reason = build_package_reason(
                                    platform=platform,
                                    time_delta_max_seconds=float(time_delta),
                                    vega_cluster_spread_pct=None,
                                    premium_mode=f"LADDER_{ladder_info['structure_label']}",
                                    num_legs=len(subset_list),
                                    identical_timestamps=identical_ts,
                                    extra_info=f"strikes={strikes_str}; "
                                              f"notionals={notionals_str}; "
                                              f"structure={ladder_info['structure_label']}; "
                                              f"direction={ladder_info['direction']}",
                                )

                                legs_list = [str(trade_ids[idx]) for idx in subset_list]

                                # Mark trades
                                for idx in subset_list:
                                    matched[idx] = True
                                    pkg_ids[idx] = pid
                                    pkg_type[idx] = pkg_type_str
                                    pkg_legs[idx] = legs_list
                                    pkg_conf[idx] = confidence
                                    pkg_reason[idx] = reason
                                    pkg_legs_count[idx] = len(subset_list)
                                    ladder_structure[idx] = ladder_info["structure_label"]
                                    ladder_direction[idx] = ladder_info["direction"]
                                    ladder_strikes[idx] = ladder_info["strikes"]
                                    ladder_notionals[idx] = ladder_info["notionals"]

                                # Found a ladder in this cluster, break out
                                break

                        if timed_out:
                            break
                        # If we found a match for this size, break
                        if any(matched[idx] for idx in cluster):
                            break

                    if timed_out:
                        i += 1
                        continue

                i += 1

    # Build result and merge back
    res = pd.DataFrame({
        trade_id_col: trade_ids,
        "_pkg_type": pkg_type,
        "_pkg_id": pkg_ids,
        "_pkg_legs": pkg_legs,
        "_pkg_conf": pkg_conf,
        "_pkg_reason": pkg_reason,
        "_pkg_legs_count": pkg_legs_count,
        "_ladder_structure": ladder_structure,
        "_ladder_direction": ladder_direction,
        "_ladder_strikes": ladder_strikes,
        "_ladder_notionals": ladder_notionals,
    })

    out[trade_id_col] = out[trade_id_col].astype(str)
    out = out.merge(
        res,
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
    out.loc[detected_mask, "ladder_structure"] = out.loc[detected_mask, "_ladder_structure"]
    out.loc[detected_mask, "ladder_direction"] = out.loc[detected_mask, "_ladder_direction"]
    out.loc[detected_mask, "ladder_strikes"] = out.loc[detected_mask, "_ladder_strikes"]
    out.loc[detected_mask, "ladder_notionals"] = out.loc[detected_mask, "_ladder_notionals"]

    # Clean up temp columns
    temp_cols = [
        "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count",
        "_ladder_structure", "_ladder_direction", "_ladder_strikes", "_ladder_notionals",
    ]
    out.drop(columns=[c for c in temp_cols if c in out.columns], inplace=True, errors="ignore")

    return out
