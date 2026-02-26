"""
Delta-hedge detection for swaption packages.

Links unpackaged USD SOFR swaptions to SOFR swap hedges using:
- execution timestamp proximity
- tenor alignment
- implied delta notional ratio
- optional soft DV01 consistency checks
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from SDRUtils.core.utils import (
    _ensure_int64_epoch_seconds,
    calculate_tenor_years,
    parse_notional,
)
from SDRUtils.packages.swaption.utils import (
    build_package_reason,
    compute_package_id,
    ensure_package_columns,
    safe_float,
)

if TYPE_CHECKING:
    from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve


DELTA_HEDGE_PACKAGE_TYPE = "DELTA_HEDGE"
DEFAULT_TIMESTAMP_WINDOWS: Tuple[int, ...] = (1, 5, 60)


def _pick_first_column(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return bool(value)
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "t", "1", "y", "yes"}


def _parse_rate(value: object) -> float:
    if value is None or pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return np.nan
    try:
        return float(text)
    except Exception:
        return np.nan


def _rate_to_decimal(rate: float) -> float:
    if not np.isfinite(rate):
        return np.nan
    if abs(rate) > 1.0:
        return rate / 100.0
    return rate


def _rate_to_percent(rate: float) -> float:
    if not np.isfinite(rate):
        return np.nan
    if abs(rate) <= 1.0:
        return rate * 100.0
    return rate


def _norm_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().upper()


def _is_sofr_text(value: object) -> bool:
    text = _norm_text(value)
    if not text:
        return False
    if "CMS" in text or "YCSO" in text:
        return False
    return "SOFR" in text


def _is_swaption_candidate_sofr(underlier: object, trade_label: object) -> bool:
    underlier_ok = _is_sofr_text(underlier)
    label_ok = _is_sofr_text(trade_label)
    return underlier_ok or label_ok


def _underlier_compatible(swaption_underlier: object, swap_underlier: object) -> bool:
    return _is_sofr_text(swaption_underlier) and _is_sofr_text(swap_underlier)


def _coerce_datetime(value: object) -> pd.Timestamp:
    return pd.to_datetime(value, errors="coerce", utc=True)


def _prepare_swap_candidates(
    swaps_df: pd.DataFrame,
    *,
    require_swap_package_indicator: bool,
) -> pd.DataFrame:
    if swaps_df is None or swaps_df.empty:
        return pd.DataFrame()

    trade_id_col = _pick_first_column(
        swaps_df,
        ["Dissemination Identifier", "dissemination_identifier", "trade_id"],
    )
    exec_col = _pick_first_column(swaps_df, ["Event timestamp", "event_timestamp"])
    effective_col = _pick_first_column(swaps_df, ["Effective Date", "effective_date"])
    maturity_col = _pick_first_column(
        swaps_df,
        ["Maturity date of the underlier", "maturity_date_of_the_underlier", "underlying_expiration_date"],
    )
    notional_leg1_col = _pick_first_column(swaps_df, ["Notional amount-Leg 1", "notional_amount_leg_1"])
    notional_leg2_col = _pick_first_column(swaps_df, ["Notional amount-Leg 2", "notional_amount_leg_2"])
    fixed_leg1_col = _pick_first_column(swaps_df, ["Fixed rate-Leg 1", "fixed_rate_leg_1"])
    fixed_leg2_col = _pick_first_column(swaps_df, ["Fixed rate-Leg 2", "fixed_rate_leg_2"])
    platform_col = _pick_first_column(swaps_df, ["Platform identifier", "platform_identifier"])
    package_indicator_col = _pick_first_column(swaps_df, ["Package indicator", "package_indicator"])
    underlier_col = _pick_first_column(swaps_df, ["UPI Underlier Name", "upi_underlier_name"])

    if trade_id_col is None or exec_col is None:
        return pd.DataFrame()
    if notional_leg1_col is None and notional_leg2_col is None:
        return pd.DataFrame()

    swap_rows: List[Dict[str, object]] = []
    for _, raw_row in swaps_df.iterrows():
        trade_id = str(raw_row.get(trade_id_col, "")).strip()
        if not trade_id:
            continue

        package_indicator = _as_bool(raw_row.get(package_indicator_col)) if package_indicator_col else False
        if require_swap_package_indicator and not package_indicator:
            continue

        underlier_name = raw_row.get(underlier_col) if underlier_col else ""
        if not _is_sofr_text(underlier_name):
            continue

        execution_ts = _coerce_datetime(raw_row.get(exec_col))
        if pd.isna(execution_ts):
            continue

        effective_date = pd.to_datetime(raw_row.get(effective_col), errors="coerce") if effective_col else pd.NaT
        maturity_date = pd.to_datetime(raw_row.get(maturity_col), errors="coerce") if maturity_col else pd.NaT
        if pd.isna(effective_date) or pd.isna(maturity_date):
            continue

        tenor_years = calculate_tenor_years(effective_date, maturity_date)
        if not np.isfinite(tenor_years) or tenor_years <= 0:
            continue

        notional_leg1 = np.nan
        notional_leg2 = np.nan
        if notional_leg1_col is not None:
            notional_leg1 = abs(float(parse_notional(raw_row.get(notional_leg1_col))[0]))
        if notional_leg2_col is not None:
            notional_leg2 = abs(float(parse_notional(raw_row.get(notional_leg2_col))[0]))
        swap_notional = np.nanmax([notional_leg1, notional_leg2])
        if not np.isfinite(swap_notional) or swap_notional <= 0:
            continue

        fixed_rate_1 = _parse_rate(raw_row.get(fixed_leg1_col)) if fixed_leg1_col else np.nan
        fixed_rate_2 = _parse_rate(raw_row.get(fixed_leg2_col)) if fixed_leg2_col else np.nan
        swap_fixed_rate = fixed_rate_1 if np.isfinite(fixed_rate_1) else fixed_rate_2
        if not np.isfinite(swap_fixed_rate):
            swap_fixed_rate = np.nan

        swap_rows.append(
            {
                "_swap_trade_id": trade_id,
                "_swap_exec_ts": execution_ts,
                "_swap_effective_date": effective_date,
                "_swap_maturity_date": maturity_date,
                "_swap_tenor_years": float(tenor_years),
                "_swap_notional": float(swap_notional),
                "_swap_fixed_rate": float(swap_fixed_rate) if np.isfinite(swap_fixed_rate) else np.nan,
                "_swap_platform": _norm_text(raw_row.get(platform_col)) if platform_col else "",
                "_swap_underlier": _norm_text(underlier_name),
            }
        )

    if not swap_rows:
        return pd.DataFrame()

    out = pd.DataFrame(swap_rows)
    out["_swap_exec_sec"] = _ensure_int64_epoch_seconds(out["_swap_exec_ts"])
    out = out.sort_values("_swap_exec_sec", kind="mergesort").reset_index(drop=True)
    return out


def _infer_swaption_leg_direction(
    row: pd.Series,
    *,
    product_col: str,
    trade_label_col: str,
) -> Optional[str]:
    product_text = _norm_text(row.get(product_col))
    label_text = _norm_text(row.get(trade_label_col))
    merged_text = f"{product_text} {label_text}"
    if "PAYER" in merged_text or "CALL" in merged_text:
        return "payer"
    if "RECEIVER" in merged_text or "PUT" in merged_text:
        return "receiver"
    return None


def _compute_swaption_dv01(
    row: pd.Series,
    *,
    pricer: "QLIRSwapCurve",
    product_col: str,
    trade_label_col: str,
    strike_col: str,
    notional_col: str,
    premium_col: str,
    expiration_col: str,
    underlying_expiration_col: str,
) -> float:
    # Local import to avoid triggering SDRUtils.products package import at module load.
    from SDRUtils.products._swaptions.pricer import _compute_swaption_leg_greeks

    leg_direction = _infer_swaption_leg_direction(row, product_col=product_col, trade_label_col=trade_label_col)
    if leg_direction is None:
        return np.nan

    strike_raw = safe_float(row.get(strike_col))
    strike = _rate_to_decimal(strike_raw)
    notional = abs(safe_float(row.get(notional_col)))
    premium = safe_float(row.get(premium_col))
    expiration_date = pd.to_datetime(row.get(expiration_col), errors="coerce")
    underlying_expiration_date = pd.to_datetime(row.get(underlying_expiration_col), errors="coerce")

    if not np.isfinite(strike) or strike <= 0:
        return np.nan
    if not np.isfinite(notional) or notional <= 0:
        return np.nan
    if not np.isfinite(premium) or premium <= 0:
        return np.nan
    if pd.isna(expiration_date) or pd.isna(underlying_expiration_date):
        return np.nan

    try:
        greeks = _compute_swaption_leg_greeks(
            pricer=pricer,
            expiration_date=expiration_date.date(),
            underlying_expiration_date=underlying_expiration_date.date(),
            strike=strike,
            notional=notional,
            fwd_prem=float(premium),
            leg=leg_direction,
        )
        return abs(float(greeks.dv01))
    except Exception:
        return np.nan


def _compute_swap_dv01(
    swap_row: pd.Series,
    *,
    pricer: "QLIRSwapCurve",
) -> float:
    # Local imports avoid circular-import path through SDRUtils.products.
    import Query.IRSwaps.adapter  # noqa: F401
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery

    effective_date = pd.to_datetime(swap_row.get("_swap_effective_date"), errors="coerce")
    maturity_date = pd.to_datetime(swap_row.get("_swap_maturity_date"), errors="coerce")
    swap_notional = safe_float(swap_row.get("_swap_notional"))
    swap_fixed_rate = safe_float(swap_row.get("_swap_fixed_rate"))

    if pd.isna(effective_date) or pd.isna(maturity_date):
        return np.nan
    if not np.isfinite(swap_notional) or swap_notional <= 0:
        return np.nan

    structure_kwargs: Dict[str, float] = {"notional": float(abs(swap_notional))}
    if np.isfinite(swap_fixed_rate):
        structure_kwargs["fixed_rate"] = _rate_to_percent(float(swap_fixed_rate))

    try:
        query = IRSwapQuery(
            curve="USD-SOFR-1D",
            effective_date=effective_date.date(),
            maturity_date=maturity_date.date(),
            structure_kwargs=structure_kwargs,
        )
        package, _ = query.resolve_package(pricer_or_curve=pricer)
        if not package:
            return np.nan
        return abs(float(pricer.pv01(package[0])))
    except Exception:
        return np.nan


def _confidence_time_bonus(time_diff_seconds: float) -> float:
    if time_diff_seconds <= 1:
        return 0.25
    if time_diff_seconds <= 5:
        return 0.15
    if time_diff_seconds <= 60:
        return 0.05
    return 0.0


def _init_delta_columns(out: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "delta_hedge_implied_delta",
        "delta_hedge_swap_fixed_rate",
        "delta_hedge_swap_tenor_years",
        "delta_hedge_swap_notional",
        "delta_hedge_match_window_seconds",
        "delta_hedge_dv01_ratio",
        "delta_hedge_time_diff_seconds",
        "delta_hedge_swap_dv01",
        "delta_hedge_swaption_dv01",
    ]
    string_cols = [
        "delta_hedge_swap_trade_id",
        "delta_hedge_dv01_check",
    ]
    for col in numeric_cols:
        if col not in out.columns:
            out[col] = np.nan
    for col in string_cols:
        if col not in out.columns:
            out[col] = None
    return out


def detect_delta_hedge_packages(
    df: pd.DataFrame,
    swaps_df: Optional[pd.DataFrame],
    *,
    timestamp_windows: Sequence[int] = DEFAULT_TIMESTAMP_WINDOWS,
    tenor_tolerance_years: float = 0.50,
    implied_delta_min: float = 0.20,
    implied_delta_max: float = 0.80,
    strike_proximity_bps: float = 50.0,
    dv01_tolerance: float = 0.20,
    require_swaption_package_indicator: bool = True,
    require_swap_package_indicator: bool = True,
    require_same_platform: bool = False,
    check_dv01: bool = True,
    pricer: Optional["QLIRSwapCurve"] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    trade_id_col: str = "trade_id",
    platform_col: str = "platform_identifier",
    underlier_col: str = "upi_underlier_name",
    package_indicator_col: str = "package_indicator",
    tenor_col: str = "tenor_years",
    notional_col: str = "notional",
    strike_col: str = "strike",
    premium_col: str = "premium",
    trade_label_col: str = "trade_label",
    expiration_col: str = "expiration_date",
    underlying_expiration_col: str = "underlying_expiration_date",
    exercise_style_col: str = "exercise_style",
) -> pd.DataFrame:
    """
    Detect swaption + swap delta-hedge pair packages.

    The detector only annotates swaption rows and leaves swap rows unchanged.
    """
    if df.empty:
        return df

    out = ensure_package_columns(df, package_col=package_col)
    out = _init_delta_columns(out)

    swap_candidates = _prepare_swap_candidates(
        swaps_df if swaps_df is not None else pd.DataFrame(),
        require_swap_package_indicator=require_swap_package_indicator,
    )
    if swap_candidates.empty:
        return out

    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    chooser_mask = (
        out[product_col].astype(str).str.contains("CHOOSER", case=False, na=False)
        | out[trade_label_col].astype(str).str.contains("CHOOSER", case=False, na=False)
        if trade_label_col in out.columns
        else out[product_col].astype(str).str.contains("CHOOSER", case=False, na=False)
    )
    bermudan_mask = out[exercise_style_col].astype(str).str.upper().str.contains("BERMUDAN", na=False) if exercise_style_col in out.columns else False

    underlier_series = out[underlier_col] if underlier_col in out.columns else pd.Series(index=out.index, dtype=object)
    trade_label_series = out[trade_label_col] if trade_label_col in out.columns else pd.Series(index=out.index, dtype=object)
    sofr_swaption_mask = pd.Series(
        [
            _is_swaption_candidate_sofr(underlier_series.get(idx), trade_label_series.get(idx))
            for idx in out.index
        ],
        index=out.index,
    )

    candidate_mask = is_swaption & not_packaged & ~chooser_mask & ~bermudan_mask & sofr_swaption_mask

    if require_swaption_package_indicator:
        if package_indicator_col not in out.columns:
            return out
        candidate_mask &= out[package_indicator_col].apply(_as_bool)

    if not candidate_mask.any():
        return out

    swaptions = out.loc[candidate_mask].copy()
    swaptions["_swpt_exec_ts"] = pd.to_datetime(swaptions[exec_col], errors="coerce", utc=True)
    swaptions = swaptions[swaptions["_swpt_exec_ts"].notna()].copy()
    if swaptions.empty:
        return out
    swaptions["_swpt_exec_sec"] = _ensure_int64_epoch_seconds(swaptions["_swpt_exec_ts"])
    swaptions.sort_values("_swpt_exec_sec", inplace=True, kind="mergesort")

    swap_exec_sec = swap_candidates["_swap_exec_sec"].to_numpy(dtype=np.int64)
    used_swap_positions: set[int] = set()
    sorted_windows = sorted({int(w) for w in timestamp_windows if int(w) > 0})
    if not sorted_windows:
        sorted_windows = list(DEFAULT_TIMESTAMP_WINDOWS)

    for swpt_idx in swaptions.index.tolist():
        swpt_row = swaptions.loc[swpt_idx]
        swpt_trade_id = str(swpt_row.get(trade_id_col, "")).strip()
        if not swpt_trade_id:
            continue

        swpt_notional = abs(safe_float(swpt_row.get(notional_col)))
        if not np.isfinite(swpt_notional) or swpt_notional <= 0:
            continue

        swpt_exec_sec = int(swpt_row.get("_swpt_exec_sec"))
        swpt_tenor = safe_float(swpt_row.get(tenor_col))
        if not np.isfinite(swpt_tenor):
            swpt_tenor = np.nan
        swpt_strike = _rate_to_decimal(safe_float(swpt_row.get(strike_col)))
        swpt_underlier_value = swpt_row.get(underlier_col, "")
        if _is_sofr_text(swpt_underlier_value):
            swpt_underlier = swpt_underlier_value
        else:
            # Many swaption rows use generic underlier text (e.g. "USD NA/Swap Fxd Flt USD").
            # Fall back to the richer trade label for SOFR compatibility checks.
            swpt_underlier = swpt_row.get(trade_label_col, swpt_underlier_value)
        swpt_platform = _norm_text(swpt_row.get(platform_col))

        best_match: Optional[Dict[str, object]] = None

        for window_seconds in sorted_windows:
            left = int(np.searchsorted(swap_exec_sec, swpt_exec_sec - window_seconds, side="left"))
            right = int(np.searchsorted(swap_exec_sec, swpt_exec_sec + window_seconds, side="right"))
            if left >= right:
                continue

            window_candidates: List[Dict[str, object]] = []
            for swap_pos in range(left, right):
                if swap_pos in used_swap_positions:
                    continue

                swap_row = swap_candidates.iloc[swap_pos]
                swap_trade_id = str(swap_row.get("_swap_trade_id", "")).strip()
                if not swap_trade_id:
                    continue

                if not _underlier_compatible(swpt_underlier, swap_row.get("_swap_underlier")):
                    continue

                swap_tenor = safe_float(swap_row.get("_swap_tenor_years"))
                if not np.isfinite(swap_tenor):
                    continue
                tenor_diff = abs(float(swpt_tenor) - float(swap_tenor)) if np.isfinite(swpt_tenor) else np.nan
                if np.isfinite(tenor_diff) and tenor_diff > tenor_tolerance_years:
                    continue
                if not np.isfinite(tenor_diff):
                    continue

                swap_notional = abs(safe_float(swap_row.get("_swap_notional")))
                if not np.isfinite(swap_notional) or swap_notional <= 0:
                    continue

                implied_delta = abs(swap_notional / swpt_notional)
                if not np.isfinite(implied_delta):
                    continue
                if implied_delta < implied_delta_min or implied_delta > implied_delta_max:
                    continue

                swap_platform = _norm_text(swap_row.get("_swap_platform"))
                same_platform = bool(swpt_platform and swap_platform and swpt_platform == swap_platform)
                if require_same_platform and not same_platform:
                    continue

                time_diff_seconds = abs(swpt_exec_sec - int(swap_row.get("_swap_exec_sec")))
                strike_signal = False
                strike_fixed_diff_bps = np.nan
                swap_fixed_rate = safe_float(swap_row.get("_swap_fixed_rate"))
                swap_fixed_rate_decimal = _rate_to_decimal(swap_fixed_rate)
                if np.isfinite(swpt_strike) and np.isfinite(swap_fixed_rate_decimal):
                    strike_fixed_diff_bps = abs(swpt_strike - swap_fixed_rate_decimal) * 10_000.0
                    strike_signal = strike_fixed_diff_bps <= strike_proximity_bps

                confidence = 0.40
                confidence += _confidence_time_bonus(float(time_diff_seconds))
                if 0.20 <= implied_delta <= 0.80:
                    confidence += 0.10
                if same_platform:
                    confidence += 0.05
                if strike_signal:
                    confidence += 0.10

                window_candidates.append(
                    {
                        "swap_pos": swap_pos,
                        "swap_trade_id": swap_trade_id,
                        "time_diff_seconds": float(time_diff_seconds),
                        "tenor_diff_years": float(tenor_diff),
                        "implied_delta": float(implied_delta),
                        "score": float(confidence),
                        "window_seconds": int(window_seconds),
                        "same_platform": same_platform,
                        "strike_signal": strike_signal,
                        "strike_fixed_diff_bps": float(strike_fixed_diff_bps) if np.isfinite(strike_fixed_diff_bps) else np.nan,
                    }
                )

            if window_candidates:
                window_candidates.sort(
                    key=lambda item: (
                        -float(item["score"]),
                        float(item["time_diff_seconds"]),
                        float(item["tenor_diff_years"]),
                    )
                )
                best_match = window_candidates[0]
                break

        if best_match is None:
            continue

        swap_row = swap_candidates.iloc[int(best_match["swap_pos"])]
        implied_delta = float(best_match["implied_delta"])
        confidence = float(best_match["score"])
        dv01_ratio = np.nan
        swap_dv01 = np.nan
        swaption_dv01 = np.nan
        dv01_check = "SKIP"

        if check_dv01 and pricer is not None:
            swaption_dv01 = _compute_swaption_dv01(
                swpt_row,
                pricer=pricer,
                product_col=product_col,
                trade_label_col=trade_label_col,
                strike_col=strike_col,
                notional_col=notional_col,
                premium_col=premium_col,
                expiration_col=expiration_col,
                underlying_expiration_col=underlying_expiration_col,
            )
            swap_dv01 = _compute_swap_dv01(swap_row, pricer=pricer)
            if np.isfinite(swaption_dv01) and swaption_dv01 != 0 and np.isfinite(swap_dv01):
                dv01_ratio = abs(float(swap_dv01) / float(swaption_dv01))
                if abs(dv01_ratio - implied_delta) <= dv01_tolerance:
                    dv01_check = "PASS"
                    confidence += 0.10
                else:
                    dv01_check = "FAIL"
                    confidence -= 0.15

        confidence = float(np.clip(confidence, 0.0, 1.0))

        swap_trade_id = str(best_match["swap_trade_id"])
        platform_for_reason = swpt_platform or _norm_text(swap_row.get("_swap_platform")) or "UNKNOWN"
        package_id = compute_package_id(
            [swpt_trade_id, swap_trade_id],
            platform_for_reason,
            int(swpt_exec_sec // 30),
            DELTA_HEDGE_PACKAGE_TYPE,
        )
        reason = build_package_reason(
            platform=platform_for_reason,
            time_delta_max_seconds=float(best_match["time_diff_seconds"]),
            vega_cluster_spread_pct=None,
            premium_mode=DELTA_HEDGE_PACKAGE_TYPE,
            num_legs=2,
            identical_timestamps=float(best_match["time_diff_seconds"]) <= 1.0,
            extra_info=(
                f"implied_delta={implied_delta:.3f}; "
                f"tenor_diff={float(best_match['tenor_diff_years']):.3f}Y; "
                f"window={int(best_match['window_seconds'])}s; "
                f"dv01_check={dv01_check}"
            ),
        )

        idx_mask = out.index == swpt_idx
        out.loc[idx_mask, package_col] = DELTA_HEDGE_PACKAGE_TYPE
        out.loc[idx_mask, "package_id"] = package_id
        out.loc[idx_mask, "package_legs"] = pd.Series(
            [[swpt_trade_id, swap_trade_id]] * int(idx_mask.sum()),
            index=out.index[idx_mask],
        )
        out.loc[idx_mask, "package_confidence"] = confidence
        out.loc[idx_mask, "package_reason"] = reason
        out.loc[idx_mask, "package_legs_count"] = 2

        out.loc[idx_mask, "delta_hedge_implied_delta"] = implied_delta
        out.loc[idx_mask, "delta_hedge_swap_trade_id"] = swap_trade_id
        out.loc[idx_mask, "delta_hedge_swap_fixed_rate"] = safe_float(swap_row.get("_swap_fixed_rate"))
        out.loc[idx_mask, "delta_hedge_swap_tenor_years"] = safe_float(swap_row.get("_swap_tenor_years"))
        out.loc[idx_mask, "delta_hedge_swap_notional"] = safe_float(swap_row.get("_swap_notional"))
        out.loc[idx_mask, "delta_hedge_match_window_seconds"] = int(best_match["window_seconds"])
        out.loc[idx_mask, "delta_hedge_dv01_ratio"] = dv01_ratio
        out.loc[idx_mask, "delta_hedge_time_diff_seconds"] = float(best_match["time_diff_seconds"])
        out.loc[idx_mask, "delta_hedge_swap_dv01"] = swap_dv01
        out.loc[idx_mask, "delta_hedge_swaption_dv01"] = swaption_dv01
        out.loc[idx_mask, "delta_hedge_dv01_check"] = dv01_check

        used_swap_positions.add(int(best_match["swap_pos"]))

    return out
