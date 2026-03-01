"""
Delta-hedge detection for swaption packages.

Links unpackaged USD swaptions to USD swap hedges using:
- execution timestamp proximity
- tenor alignment (single-leg) or barbell decomposition (multi-leg)
- implied delta notional ratio / DV01 consistency
- probabilistic scoring with configurable feature weights

Barbell decomposition:
  Dealers hedge forward-starting swaption deltas by decomposing the forward swap
  into spot-starting barbell legs. For example, a 10y10y forward swap decomposes
  into approximately receive-10Y + pay-20Y (or pay-30Y depending on curve build).
  The decomposition is curve-build dependent — different risk models produce
  different barbell leg combinations. This module searches multiple common desk
  configurations and picks the best-scoring match.
"""

from __future__ import annotations

import datetime
import logging
import math
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

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

logger = logging.getLogger(__name__)

DELTA_HEDGE_PACKAGE_TYPE = "DELTA_HEDGE"
DEFAULT_TIMESTAMP_WINDOWS: Tuple[int, ...] = (1, 5, 60)

# ---------------------------------------------------------------------------
# Common dealer desk risk model configurations for barbell decomposition.
# Each model specifies which spot swap tenors appear as risk instruments
# alongside short-end SOFR futures. Different desks use different builds,
# leading to different barbell decompositions for the same forward swap.
# ---------------------------------------------------------------------------
COMMON_RISK_MODELS: Dict[str, Dict[str, Any]] = {
    "desk_a": {
        "mt_tenors": ["5Y", "10Y", "30Y"],
    },
    "desk_b": {
        "mt_tenors": ["5Y", "7Y", "10Y", "20Y", "30Y"],
    },
}

_IMM_MONTH_TO_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}


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


def _normalize_underlier_family(value: object) -> str:
    text = _norm_text(value)
    if not text:
        return ""
    if text.startswith("USD_"):
        return text
    if "CMS" in text or "YCSO" in text:
        return ""

    compact = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = compact.split()

    if "SOFR" in tokens:
        if "TERM" in tokens or "CME" in tokens:
            return "USD_TERM_SOFR"
        if "ICE" in tokens:
            return "USD_ICE_SOFR"
        return "USD_SOFR"
    if "BSBY" in tokens:
        return "USD_BSBY"
    if "LIBOR" in tokens:
        return "USD_LIBOR"
    if "FEDFUNDS" in tokens or ("FED" in tokens and "FUNDS" in tokens):
        return "USD_FEDFUNDS"
    if "FEDERAL" in tokens and "FUNDS" in tokens:
        return "USD_FEDFUNDS"

    if text.startswith("USD-"):
        parts = re.split(r"[-/ ]+", text)
        if len(parts) >= 2 and parts[1]:
            return f"USD_{parts[1]}"
    return ""


def _is_swaption_candidate_usd_family(underlier: object, trade_label: object) -> bool:
    underlier_ok = bool(_normalize_underlier_family(underlier))
    label_ok = bool(_normalize_underlier_family(trade_label))
    return underlier_ok or label_ok


def _underlier_compatible(swaption_underlier: object, swap_underlier: object) -> bool:
    swaption_family = _normalize_underlier_family(swaption_underlier)
    swap_family = _normalize_underlier_family(swap_underlier)
    return bool(swaption_family) and swaption_family == swap_family


def _is_sofr_family(value: object) -> bool:
    return _normalize_underlier_family(value) == "USD_SOFR"


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
        underlier_family = _normalize_underlier_family(underlier_name)
        if not underlier_family:
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
                "_swap_underlier_family": underlier_family,
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


# ---------------------------------------------------------------------------
# Barbell decomposition infrastructure
# ---------------------------------------------------------------------------


def _generate_imm_codes(reference_date: datetime.date, n_quarters: int = 12) -> List[str]:
    """Generate the next *n_quarters* quarterly IMM codes from *reference_date*."""
    imm_months = [3, 6, 9, 12]
    year = reference_date.year
    month = reference_date.month

    # Find first IMM quarter at or after current month.
    start_idx = 0
    start_year = year
    found = False
    for i, m in enumerate(imm_months):
        if m >= month:
            start_idx = i
            start_year = year
            found = True
            break
    if not found:
        # Past December → start from March next year
        start_idx = 0
        start_year = year + 1

    codes: List[str] = []
    for offset in range(n_quarters):
        idx = (start_idx + offset) % 4
        q_year = start_year + (start_idx + offset) // 4
        code = f"{_IMM_MONTH_TO_CODE[imm_months[idx]]}{q_year % 100:02d}"
        codes.append(code)
    return codes


def _tenor_label_to_years(tenor: str) -> float:
    """Convert a tenor label to approximate years.  ``'10Y'`` → ``10.0``."""
    t = tenor.strip().upper()
    if t.endswith("Y"):
        return float(t[:-1])
    if t.endswith("M"):
        return float(t[:-1]) / 12.0
    return float(t)


def _build_rl_risk_model(
    curve_name: str,
    timestamp: datetime.date,
    mt_tenors: List[str],
    source: str = "ERIS_EOD_LIVE-RL_BASIC",
    n_imm_quarters: int = 12,
) -> Optional[Tuple]:
    """Build a rateslib curve handle and solver for barbell decomposition.

    Returns ``(curve_handle, solver, mt_tenors_available)`` or ``None`` on failure.
    """
    try:
        import rateslib as rl
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
        import Query.IRSwaps.adapter  # noqa: F401
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapStructure
    except ImportError:
        logger.warning("rateslib or MDP imports unavailable; barbell decomposition disabled")
        return None

    try:
        curve_mdp = IRSwapsMDP(source=source)
        curve_handle = curve_mdp._get_curve(curve_name=curve_name, timestamp=timestamp)
    except Exception:
        logger.debug("Failed to build RL curve for %s @ %s", curve_name, timestamp)
        return None

    # Build SFR futures for the short end.
    imm_codes = _generate_imm_codes(timestamp, n_imm_quarters)
    sfrs: Dict[str, Any] = {}
    for code in imm_codes:
        try:
            eff = rl.get_imm(code=code)
            term = rl.next_imm(eff)
            sfrs[code] = rl.STIRFuture(
                effective=eff,
                termination=term,
                spec="usd_stir",
                curves=curve_handle.handle(),
            )
        except Exception:
            continue

    # Build spot swaps for medium-term tenors.
    mt_irs: Dict[str, Any] = {}
    for t in mt_tenors:
        try:
            q = IRSwapQuery(
                curve=curve_name,
                tenor=t,
                structure=IRSwapStructure.OUTRIGHT,
                structure_kwargs={"bpv": 1},
            )
            pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
            if pkg:
                mt_irs[t] = pkg[0]
        except Exception:
            continue

    instruments = sfrs | mt_irs
    if len(instruments) < 3:
        logger.debug("Insufficient instruments for solver: %d", len(instruments))
        return None

    try:
        solver = rl.Solver(
            curves=[curve_handle.handle()],
            instruments=list(instruments.values()),
            instrument_labels=list(instruments.keys()),
            s=[r.rate().real for r in instruments.values()],
            id=curve_handle.id(),
            func_tol=1e-8,
            conv_tol=1e-10,
        )
    except Exception:
        logger.debug("RL solver construction failed for %s", curve_name)
        return None

    return curve_handle, solver, list(mt_irs.keys())


def _compute_barbell_decomposition(
    expiration_date: datetime.date,
    underlying_expiration_date: datetime.date,
    curve_name: str,
    curve_handle,
    solver,
    mt_tenors: List[str],
    min_bpv_fraction: float = 0.02,
) -> Optional[Dict]:
    """Compute expected spot barbell legs for a forward swap.

    Builds the forward swap (effective=expiry, maturity=underlying_mat) at
    unit BPV and decomposes its risk across the solver's instrument basis.

    Returns a dict with ``"legs"`` (list of dicts with ``tenor_label``,
    ``expected_bpv_weight``, ``tenor_years``, ``direction``, ``fraction``)
    and ``"total_mt_bpv"``, or ``None`` on failure.
    """
    try:
        import rateslib as rl  # noqa: F811
        import Query.IRSwaps.adapter  # noqa: F401
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from RVUtils.rl_swap_risk_ladder_utils import ladder_from_pkg
    except ImportError:
        return None

    try:
        q = IRSwapQuery(
            curve=curve_name,
            effective_date=expiration_date,
            maturity_date=underlying_expiration_date,
            structure_kwargs={"bpv": 1},
        )
        pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
        if not pkg:
            return None

        delta = ladder_from_pkg(pkg, solver=solver)
    except Exception:
        return None

    # ``ladder_from_pkg`` may return a MultiIndex Series — flatten to label level.
    if isinstance(delta.index, pd.MultiIndex):
        delta.index = delta.index.get_level_values(-1)

    # Extract medium-term tenor weights.
    total_abs = 0.0
    raw_legs: List[Tuple[str, float, float]] = []
    for tenor in mt_tenors:
        if tenor in delta.index:
            weight = float(delta[tenor])
            abs_weight = abs(weight)
            total_abs += abs_weight
            raw_legs.append((tenor, weight, abs_weight))

    if total_abs < 1e-6:
        return None

    legs: List[Dict[str, Any]] = []
    for tenor, weight, abs_weight in raw_legs:
        if abs_weight / total_abs >= min_bpv_fraction:
            legs.append(
                {
                    "tenor_label": tenor,
                    "expected_bpv_weight": weight,
                    "tenor_years": _tenor_label_to_years(tenor),
                    "direction": "pay" if weight > 0 else "receive",
                    "fraction": abs_weight / total_abs,
                }
            )

    if not legs:
        return None

    # Sort by absolute weight descending.
    legs.sort(key=lambda x: abs(x["expected_bpv_weight"]), reverse=True)

    return {"legs": legs, "total_mt_bpv": total_abs}


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _time_proximity_score(seconds: float, half_life: float = 30.0) -> float:
    """Continuous time-proximity score with exponential decay."""
    if seconds <= 0:
        return 1.0
    return math.exp(-math.log(2) * seconds / half_life)


# ---------------------------------------------------------------------------
# Barbell pair matching
# ---------------------------------------------------------------------------


def _find_barbell_pair(
    swpt_exec_sec: int,
    swap_candidates: pd.DataFrame,
    swap_exec_sec: np.ndarray,
    used_swap_positions: set,
    decomposition: Dict,
    *,
    sorted_windows: List[int],
    barbell_tenor_tolerance: float,
    swpt_platform: str,
    swpt_underlier: str,
    time_half_life: float,
) -> Optional[Dict]:
    """Find a pair of swaps matching the top-2 barbell decomposition legs.

    Searches time windows progressively and returns the best-scoring pair,
    or ``None`` if no valid pair is found.
    """
    legs = decomposition["legs"]
    if len(legs) < 2:
        return None

    leg_a = legs[0]  # largest by absolute BPV
    leg_b = legs[1]  # second largest

    leg_a_years = leg_a["tenor_years"]
    leg_b_years = leg_b["tenor_years"]
    expected_bpv_ratio = (
        abs(leg_a["expected_bpv_weight"] / leg_b["expected_bpv_weight"])
        if abs(leg_b["expected_bpv_weight"]) > 1e-6
        else np.nan
    )

    for window_seconds in sorted_windows:
        left = int(np.searchsorted(swap_exec_sec, swpt_exec_sec - window_seconds, side="left"))
        right = int(np.searchsorted(swap_exec_sec, swpt_exec_sec + window_seconds, side="right"))
        if left >= right:
            continue

        # Classify available swaps by which barbell leg they could match.
        leg_a_cands: List[int] = []
        leg_b_cands: List[int] = []

        for pos in range(left, right):
            if pos in used_swap_positions:
                continue

            swap_row = swap_candidates.iloc[pos]
            if not _underlier_compatible(swpt_underlier, swap_row.get("_swap_underlier")):
                continue

            swap_tenor = safe_float(swap_row.get("_swap_tenor_years"))
            if not np.isfinite(swap_tenor):
                continue

            if abs(swap_tenor - leg_a_years) <= barbell_tenor_tolerance:
                leg_a_cands.append(pos)
            if abs(swap_tenor - leg_b_years) <= barbell_tenor_tolerance:
                leg_b_cands.append(pos)

        if not leg_a_cands or not leg_b_cands:
            continue

        # Score all valid pairs.
        best_pair: Optional[Dict] = None
        best_score = -1.0

        for pos_a in leg_a_cands:
            for pos_b in leg_b_cands:
                if pos_a == pos_b:
                    continue

                row_a = swap_candidates.iloc[pos_a]
                row_b = swap_candidates.iloc[pos_b]

                not_a = abs(safe_float(row_a.get("_swap_notional")))
                not_b = abs(safe_float(row_b.get("_swap_notional")))
                if not (np.isfinite(not_a) and not_a > 0 and np.isfinite(not_b) and not_b > 0):
                    continue

                # --- feature: tenor alignment (0–1) ---
                swap_tenor_a = safe_float(row_a.get("_swap_tenor_years"))
                swap_tenor_b = safe_float(row_b.get("_swap_tenor_years"))
                tenor_score_a = max(0.0, 1.0 - abs(swap_tenor_a - leg_a_years) / barbell_tenor_tolerance)
                tenor_score_b = max(0.0, 1.0 - abs(swap_tenor_b - leg_b_years) / barbell_tenor_tolerance)
                tenor_alignment = (tenor_score_a + tenor_score_b) / 2.0

                # --- feature: temporal proximity (0–1) ---
                time_a = abs(swpt_exec_sec - int(row_a.get("_swap_exec_sec")))
                time_b = abs(swpt_exec_sec - int(row_b.get("_swap_exec_sec")))
                max_time = max(time_a, time_b)
                temporal_proximity = _time_proximity_score(max_time, time_half_life)

                # --- feature: platform match (0 or 1) ---
                plat_a = _norm_text(row_a.get("_swap_platform"))
                plat_b = _norm_text(row_b.get("_swap_platform"))
                platform_match = 1.0 if (swpt_platform and plat_a == swpt_platform and plat_b == swpt_platform) else 0.0

                # --- feature: notional ratio plausibility (0–1) ---
                # BPV weight ratio ≠ notional ratio, but they are correlated.
                observed_notional_ratio = not_a / not_b
                ratio_plausibility = 0.5  # neutral default
                if np.isfinite(expected_bpv_ratio) and expected_bpv_ratio > 0:
                    ratio_diff = abs(
                        math.log(observed_notional_ratio + 1e-6) - math.log(expected_bpv_ratio + 1e-6)
                    )
                    ratio_plausibility = max(0.0, 1.0 - ratio_diff / 2.0)

                # --- composite ---
                score = (
                    0.30 * tenor_alignment
                    + 0.30 * temporal_proximity
                    + 0.20 * ratio_plausibility
                    + 0.10 * platform_match
                    + 0.10  # base credit for a structurally valid barbell pair
                )

                if score > best_score:
                    best_score = score
                    best_pair = {
                        "pos_a": pos_a,
                        "pos_b": pos_b,
                        "score": float(score),
                        "window_seconds": window_seconds,
                        "time_diff_a": float(time_a),
                        "time_diff_b": float(time_b),
                        "max_time_diff": float(max_time),
                        "tenor_alignment": float(tenor_alignment),
                        "temporal_proximity": float(temporal_proximity),
                        "ratio_plausibility": float(ratio_plausibility),
                        "platform_match": float(platform_match),
                        "observed_notional_ratio": float(observed_notional_ratio),
                        "expected_bpv_ratio": float(expected_bpv_ratio) if np.isfinite(expected_bpv_ratio) else np.nan,
                        "leg_a_tenor_label": leg_a["tenor_label"],
                        "leg_b_tenor_label": leg_b["tenor_label"],
                    }

        if best_pair is not None:
            return best_pair

    return None


def _init_delta_columns(out: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        # Existing single-leg columns
        "delta_hedge_implied_delta",
        "delta_hedge_swap_fixed_rate",
        "delta_hedge_swap_tenor_years",
        "delta_hedge_swap_notional",
        "delta_hedge_match_window_seconds",
        "delta_hedge_dv01_ratio",
        "delta_hedge_time_diff_seconds",
        "delta_hedge_swap_dv01",
        "delta_hedge_swaption_dv01",
        # Barbell columns
        "delta_hedge_long_leg_notional",
        "delta_hedge_long_leg_dv01",
        "delta_hedge_short_leg_notional",
        "delta_hedge_short_leg_dv01",
        "delta_hedge_expected_ratio",
        "delta_hedge_observed_ratio",
    ]
    string_cols = [
        # Existing
        "delta_hedge_swap_trade_id",
        "delta_hedge_dv01_check",
        # Barbell columns
        "delta_hedge_match_type",
        "delta_hedge_curve_build",
        "delta_hedge_long_leg_trade_id",
        "delta_hedge_long_leg_tenor",
        "delta_hedge_short_leg_trade_id",
        "delta_hedge_short_leg_tenor",
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
    # --- barbell decomposition parameters ---
    enable_barbell: bool = True,
    barbell_risk_models: Optional[Dict[str, Dict[str, Any]]] = None,
    barbell_tenor_tolerance: float = 1.0,
    barbell_time_half_life: float = 30.0,
    barbell_curve_name: str = "USD-SOFR-1D",
    barbell_source: str = "ERIS_EOD_LIVE-RL_BASIC",
    barbell_min_bpv_fraction: float = 0.02,
    # --- capped notional ---
    notional_capped_col: str = "is_notional_capped",
    capped_implied_delta_max: float = 4.0,
) -> pd.DataFrame:
    """Detect swaption + swap delta-hedge pair packages.

    Enhanced with barbell decomposition: for each swaption, the detector first
    attempts to find a **pair** of spot swaps matching the expected barbell legs
    of the forward swap hedge (under multiple desk risk-model configurations).
    If no barbell pair is found, it falls back to single-leg matching (the
    original algorithm).

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

    # ----- candidate filtering (unchanged) -----
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
    usd_family_swaption_mask = pd.Series(
        [
            _is_swaption_candidate_usd_family(underlier_series.get(idx), trade_label_series.get(idx))
            for idx in out.index
        ],
        index=out.index,
    )

    candidate_mask = is_swaption & not_packaged & ~chooser_mask & ~bermudan_mask & usd_family_swaption_mask

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

    # ----- build barbell risk models (once per execution date) -----
    risk_model_cache: Dict[str, Tuple] = {}
    if enable_barbell:
        models = barbell_risk_models or COMMON_RISK_MODELS
        exec_dates = swaptions[exec_col].apply(lambda x: pd.to_datetime(x, errors="coerce"))
        exec_dates = exec_dates.dropna()
        if not exec_dates.empty:
            exec_date = exec_dates.dt.date.mode().iloc[0] if not exec_dates.dt.date.mode().empty else exec_dates.dt.date.iloc[0]
            for model_name, model_config in models.items():
                result = _build_rl_risk_model(
                    curve_name=barbell_curve_name,
                    timestamp=exec_date,
                    mt_tenors=model_config["mt_tenors"],
                    source=barbell_source,
                )
                if result is not None:
                    risk_model_cache[model_name] = result

        if risk_model_cache:
            logger.info(
                "Barbell decomposition enabled with %d risk models: %s",
                len(risk_model_cache),
                list(risk_model_cache.keys()),
            )

    # ===================================================================
    # Main matching loop
    # ===================================================================
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
        swpt_underlier = swpt_underlier_value
        if not _normalize_underlier_family(swpt_underlier_value):
            swpt_underlier = swpt_row.get(trade_label_col, swpt_underlier_value)
        swpt_underlier_family = _normalize_underlier_family(swpt_underlier)
        if not swpt_underlier_family:
            continue
        swpt_platform = _norm_text(swpt_row.get(platform_col))

        # Capped notional: widen implied-delta range.
        is_capped = False
        if notional_capped_col in swaptions.columns:
            is_capped = _as_bool(swpt_row.get(notional_capped_col))
        effective_implied_delta_max = capped_implied_delta_max if is_capped else implied_delta_max

        # ---------------------------------------------------------------
        # A) Try barbell pair matching across risk models
        # ---------------------------------------------------------------
        best_barbell: Optional[Dict] = None
        best_barbell_model: Optional[str] = None

        if risk_model_cache and _is_sofr_family(swpt_underlier):
            swpt_expiry = pd.to_datetime(swpt_row.get(expiration_col), errors="coerce")
            swpt_underlying_mat = pd.to_datetime(swpt_row.get(underlying_expiration_col), errors="coerce")

            if not pd.isna(swpt_expiry) and not pd.isna(swpt_underlying_mat):
                for model_name, (curve_handle, solver, mt_tenors_avail) in risk_model_cache.items():
                    decomposition = _compute_barbell_decomposition(
                        expiration_date=swpt_expiry.date(),
                        underlying_expiration_date=swpt_underlying_mat.date(),
                        curve_name=barbell_curve_name,
                        curve_handle=curve_handle,
                        solver=solver,
                        mt_tenors=mt_tenors_avail,
                        min_bpv_fraction=barbell_min_bpv_fraction,
                    )
                    if decomposition is None:
                        continue

                    pair = _find_barbell_pair(
                        swpt_exec_sec=swpt_exec_sec,
                        swap_candidates=swap_candidates,
                        swap_exec_sec=swap_exec_sec,
                        used_swap_positions=used_swap_positions,
                        decomposition=decomposition,
                        sorted_windows=sorted_windows,
                        barbell_tenor_tolerance=barbell_tenor_tolerance,
                        swpt_platform=swpt_platform,
                        swpt_underlier=swpt_underlier,
                        time_half_life=barbell_time_half_life,
                    )

                    if pair is not None and (best_barbell is None or pair["score"] > best_barbell["score"]):
                        best_barbell = pair
                        best_barbell_model = model_name
                        best_barbell["decomposition"] = decomposition

        # ---------------------------------------------------------------
        # B) Try single-leg matching (original algorithm)
        # ---------------------------------------------------------------
        best_single: Optional[Dict[str, object]] = None

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
                if implied_delta < implied_delta_min or implied_delta > effective_implied_delta_max:
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
                best_single = window_candidates[0]
                break

        # ---------------------------------------------------------------
        # C) Choose barbell or single-leg, annotate
        # ---------------------------------------------------------------
        use_barbell = (
            best_barbell is not None
            and (best_single is None or best_barbell["score"] >= best_single.get("score", 0))
        )

        if use_barbell:
            # ---------- annotate BARBELL match ----------
            row_a = swap_candidates.iloc[int(best_barbell["pos_a"])]
            row_b = swap_candidates.iloc[int(best_barbell["pos_b"])]
            trade_id_a = str(row_a.get("_swap_trade_id", "")).strip()
            trade_id_b = str(row_b.get("_swap_trade_id", "")).strip()

            # DV01 check for barbell legs (soft)
            confidence = float(best_barbell["score"])
            dv01_check = "SKIP"
            swap_dv01_a = np.nan
            swap_dv01_b = np.nan
            swaption_dv01 = np.nan

            if check_dv01 and pricer is not None and _is_sofr_family(swpt_underlier):
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
                swap_dv01_a = _compute_swap_dv01(row_a, pricer=pricer)
                swap_dv01_b = _compute_swap_dv01(row_b, pricer=pricer)
                if np.isfinite(swap_dv01_a) and np.isfinite(swap_dv01_b) and swap_dv01_b > 0:
                    observed_dv01_ratio = abs(swap_dv01_a / swap_dv01_b)
                    expected_ratio = best_barbell.get("expected_bpv_ratio", np.nan)
                    if np.isfinite(expected_ratio) and expected_ratio > 0:
                        ratio_err = abs(observed_dv01_ratio - expected_ratio) / expected_ratio
                        if ratio_err <= dv01_tolerance:
                            dv01_check = "PASS"
                            confidence += 0.05
                        else:
                            dv01_check = "FAIL"
                            confidence -= 0.10

            confidence = float(np.clip(confidence, 0.0, 1.0))

            # Determine long vs short leg by tenor.
            tenor_a = safe_float(row_a.get("_swap_tenor_years"))
            tenor_b = safe_float(row_b.get("_swap_tenor_years"))
            if np.isfinite(tenor_a) and np.isfinite(tenor_b) and tenor_a >= tenor_b:
                long_row, short_row = row_a, row_b
                long_tid, short_tid = trade_id_a, trade_id_b
                long_dv01, short_dv01 = swap_dv01_a, swap_dv01_b
            else:
                long_row, short_row = row_b, row_a
                long_tid, short_tid = trade_id_b, trade_id_a
                long_dv01, short_dv01 = swap_dv01_b, swap_dv01_a

            platform_for_reason = swpt_platform or _norm_text(row_a.get("_swap_platform")) or "UNKNOWN"
            package_id = compute_package_id(
                [swpt_trade_id, trade_id_a, trade_id_b],
                platform_for_reason,
                int(swpt_exec_sec // 30),
                DELTA_HEDGE_PACKAGE_TYPE,
            )
            reason = build_package_reason(
                platform=platform_for_reason,
                time_delta_max_seconds=float(best_barbell["max_time_diff"]),
                vega_cluster_spread_pct=None,
                premium_mode=DELTA_HEDGE_PACKAGE_TYPE,
                num_legs=3,
                identical_timestamps=float(best_barbell["max_time_diff"]) <= 1.0,
                extra_info=(
                    f"match=BARBELL; "
                    f"model={best_barbell_model}; "
                    f"legs={best_barbell.get('leg_a_tenor_label', '?')}/{best_barbell.get('leg_b_tenor_label', '?')}; "
                    f"window={int(best_barbell['window_seconds'])}s; "
                    f"dv01_check={dv01_check}"
                ),
            )

            idx_mask = out.index == swpt_idx
            out.loc[idx_mask, package_col] = DELTA_HEDGE_PACKAGE_TYPE
            out.loc[idx_mask, "package_id"] = package_id
            out.loc[idx_mask, "package_legs"] = pd.Series(
                [[swpt_trade_id, long_tid, short_tid]] * int(idx_mask.sum()),
                index=out.index[idx_mask],
            )
            out.loc[idx_mask, "package_confidence"] = confidence
            out.loc[idx_mask, "package_reason"] = reason
            out.loc[idx_mask, "package_legs_count"] = 3

            out.loc[idx_mask, "delta_hedge_match_type"] = "BARBELL"
            out.loc[idx_mask, "delta_hedge_curve_build"] = best_barbell_model
            out.loc[idx_mask, "delta_hedge_match_window_seconds"] = int(best_barbell["window_seconds"])
            out.loc[idx_mask, "delta_hedge_time_diff_seconds"] = float(best_barbell["max_time_diff"])
            out.loc[idx_mask, "delta_hedge_swaption_dv01"] = swaption_dv01
            out.loc[idx_mask, "delta_hedge_dv01_check"] = dv01_check
            out.loc[idx_mask, "delta_hedge_expected_ratio"] = (
                float(best_barbell["expected_bpv_ratio"]) if np.isfinite(best_barbell.get("expected_bpv_ratio", np.nan)) else np.nan
            )
            out.loc[idx_mask, "delta_hedge_observed_ratio"] = float(best_barbell.get("observed_notional_ratio", np.nan))

            # Long leg
            out.loc[idx_mask, "delta_hedge_long_leg_trade_id"] = long_tid
            out.loc[idx_mask, "delta_hedge_long_leg_tenor"] = str(safe_float(long_row.get("_swap_tenor_years")))
            out.loc[idx_mask, "delta_hedge_long_leg_notional"] = safe_float(long_row.get("_swap_notional"))
            out.loc[idx_mask, "delta_hedge_long_leg_dv01"] = long_dv01
            # Short leg
            out.loc[idx_mask, "delta_hedge_short_leg_trade_id"] = short_tid
            out.loc[idx_mask, "delta_hedge_short_leg_tenor"] = str(safe_float(short_row.get("_swap_tenor_years")))
            out.loc[idx_mask, "delta_hedge_short_leg_notional"] = safe_float(short_row.get("_swap_notional"))
            out.loc[idx_mask, "delta_hedge_short_leg_dv01"] = short_dv01

            used_swap_positions.add(int(best_barbell["pos_a"]))
            used_swap_positions.add(int(best_barbell["pos_b"]))

        elif best_single is not None:
            # ---------- annotate SINGLE-LEG match (original logic) ----------
            swap_row = swap_candidates.iloc[int(best_single["swap_pos"])]
            implied_delta = float(best_single["implied_delta"])
            confidence = float(best_single["score"])
            dv01_ratio = np.nan
            swap_dv01 = np.nan
            swaption_dv01 = np.nan
            dv01_check = "SKIP"

            if check_dv01 and pricer is not None and _is_sofr_family(swpt_underlier):
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

            swap_trade_id = str(best_single["swap_trade_id"])
            platform_for_reason = swpt_platform or _norm_text(swap_row.get("_swap_platform")) or "UNKNOWN"
            package_id = compute_package_id(
                [swpt_trade_id, swap_trade_id],
                platform_for_reason,
                int(swpt_exec_sec // 30),
                DELTA_HEDGE_PACKAGE_TYPE,
            )
            reason = build_package_reason(
                platform=platform_for_reason,
                time_delta_max_seconds=float(best_single["time_diff_seconds"]),
                vega_cluster_spread_pct=None,
                premium_mode=DELTA_HEDGE_PACKAGE_TYPE,
                num_legs=2,
                identical_timestamps=float(best_single["time_diff_seconds"]) <= 1.0,
                extra_info=(
                    f"match=SINGLE; "
                    f"implied_delta={implied_delta:.3f}; "
                    f"tenor_diff={float(best_single['tenor_diff_years']):.3f}Y; "
                    f"window={int(best_single['window_seconds'])}s; "
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

            out.loc[idx_mask, "delta_hedge_match_type"] = "SINGLE"
            out.loc[idx_mask, "delta_hedge_implied_delta"] = implied_delta
            out.loc[idx_mask, "delta_hedge_swap_trade_id"] = swap_trade_id
            out.loc[idx_mask, "delta_hedge_swap_fixed_rate"] = safe_float(swap_row.get("_swap_fixed_rate"))
            out.loc[idx_mask, "delta_hedge_swap_tenor_years"] = safe_float(swap_row.get("_swap_tenor_years"))
            out.loc[idx_mask, "delta_hedge_swap_notional"] = safe_float(swap_row.get("_swap_notional"))
            out.loc[idx_mask, "delta_hedge_match_window_seconds"] = int(best_single["window_seconds"])
            out.loc[idx_mask, "delta_hedge_dv01_ratio"] = dv01_ratio
            out.loc[idx_mask, "delta_hedge_time_diff_seconds"] = float(best_single["time_diff_seconds"])
            out.loc[idx_mask, "delta_hedge_swap_dv01"] = swap_dv01
            out.loc[idx_mask, "delta_hedge_swaption_dv01"] = swaption_dv01
            out.loc[idx_mask, "delta_hedge_dv01_check"] = dv01_check

            used_swap_positions.add(int(best_single["swap_pos"]))

    return out
