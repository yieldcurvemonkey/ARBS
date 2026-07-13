# ABOUTME: Pure-function scorer that grades package-detection confidence
# for USD swap tape rows by cross-checking package_indicator, leg-level
# risk balance, and the derived spread vs the reported PTS.
# Faithful Python port of:
#   SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts
from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Default tolerances (mirrors PACKAGE_CONFIDENCE_TOLERANCES in constants.ts)
# ---------------------------------------------------------------------------
DEFAULT_TOLERANCES: dict[str, float] = {
    # +/- bp window for derived-spread vs reported PTS match.
    "pts_match_bp": 0.5,
    # Relative tolerance for risk-balance checks (10% = 0.10).
    "risk_balance_rel": 0.10,
}

# Scale factors for unit-mismatch detection (decimal/percent/bps).
# Order matters: 1 is checked first so an exact match wins.
PTS_SCALE_FACTORS: tuple[float, ...] = (
    1, 10, 0.1, 100, 0.01, 1000, 0.001, 10_000, 0.0001,
)

# Relative tolerance for non-1x scale matches.
SCALE_REL_TOL: float = 0.05


# ---------------------------------------------------------------------------
# Numeric / None helpers
# ---------------------------------------------------------------------------

def _is_finite(v: Any) -> bool:
    """Return True if *v* is a finite number (not None, NaN, inf)."""
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _num_or_none(v: Any) -> float | None:
    """Coerce to float if finite, else None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# Type normalization
# ---------------------------------------------------------------------------

def _normalize_type(value: Any) -> str:
    """Normalize package_type to uppercase; map empty/NaN/None to OUTRIGHT."""
    if value is None:
        return "OUTRIGHT"
    s = str(value).strip().upper()
    if not s or s == "NAN" or s == "NONE":
        return "OUTRIGHT"
    return s


# ---------------------------------------------------------------------------
# Tone
# ---------------------------------------------------------------------------

def _pick_tone(score: int, total: int, is_info: bool) -> str:
    if is_info:
        return "info"
    if score == total:
        return "high"
    if score >= total - 1:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _format_bp(value: float) -> str:
    """Render a PTS / derived-spread number with enough precision that
    sub-bp values don't collapse to '0.00bp' in the UI."""
    if not math.isfinite(value):
        return str(value)
    a = abs(value)
    if a == 0:
        return "0"
    if a < 1e-3:
        return f"{value:.3e}"
    if a < 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{value:.3f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Leg helpers
# ---------------------------------------------------------------------------

def _leg_number_or(leg: dict, key: str) -> float | None:
    """Extract a finite number from a leg dict, or None."""
    v = leg.get(key)
    return _num_or_none(v)


def _sort_legs_tenor_asc(legs: list[dict]) -> list[dict]:
    """Return a copy of legs sorted ascending by tenor_years."""
    def _key(leg: dict) -> float:
        t = leg.get("tenor_years")
        if _is_finite(t):
            return float(t)
        return float("inf")
    return sorted(legs, key=_key)


def _is_ascending_by_tenor(legs: list[dict]) -> bool:
    """True if legs are already monotonically non-decreasing by tenor_years."""
    for i in range(1, len(legs)):
        prev = legs[i - 1].get("tenor_years")
        curr = legs[i].get("tenor_years")
        pv = float(prev) if _is_finite(prev) else float("inf")
        cv = float(curr) if _is_finite(curr) else float("inf")
        if pv > cv:
            return False
    return True


# ---------------------------------------------------------------------------
# Scale-match logic
# ---------------------------------------------------------------------------

def _find_scale_match(
    a: float,
    b: float,
    tol: float,
    scales: tuple[float, ...] = PTS_SCALE_FACTORS,
) -> dict[str, float] | None:
    """Try to express *a* as *b * factor* for any factor in *scales*.
    Returns {"factor": f, "residual": r} for the best match, or None."""
    if not math.isfinite(a) or not math.isfinite(b):
        return None
    if b == 0:
        return {"factor": 1, "residual": abs(a)} if abs(a) <= tol else None
    best: dict[str, float] | None = None
    for f in scales:
        scaled = b * f
        residual = abs(a - scaled)
        fits = False
        if f == 1:
            fits = residual <= tol
        else:
            denom = max(abs(a), abs(scaled))
            if denom < 1e-12:
                fits = residual <= tol
            else:
                fits = (residual / denom) <= SCALE_REL_TOL
        if fits:
            if best is None or residual < best["residual"]:
                best = {"factor": f, "residual": residual}
    return best


# ---------------------------------------------------------------------------
# Fixed-rate spread to bp conversion
# ---------------------------------------------------------------------------

def _fixed_rate_spread_to_bp(
    spread: float,
    rates: list[float | None],
) -> float:
    """Convert a derived fixed-rate spread to bp, auto-detecting
    whether rates are decimal (0.0384) or percentage (3.84)."""
    finite_rates = [r for r in rates if r is not None and math.isfinite(r)]
    if not finite_rates:
        return spread * 100
    max_abs_rate = max(abs(r) for r in finite_rates)
    return spread * (10_000 if max_abs_rate < 1 else 100)


# ---------------------------------------------------------------------------
# Signal constructors
# ---------------------------------------------------------------------------

def _outright_signals(
    package_indicator: bool,
    n_package_legs: int,
) -> list[dict]:
    indicator_on = bool(package_indicator)
    legs = n_package_legs
    return [
        {
            "name": "package_indicator_off",
            "passed": not indicator_on,
            "detail": (
                "reported as packaged but classified outright"
                if indicator_on
                else "not flagged as a package"
            ),
        },
        {
            "name": "leg_count",
            "passed": legs == 1,
            "detail": f"expected 1, got {legs}",
        },
    ]


def _risk_balance_signal(
    legs: list[dict],
    weights: list[float],
    label: str,
    tol: dict[str, float],
) -> dict:
    """Pass when all legs have similar absolute DV01 (risk) values."""
    rel_tol = tol["risk_balance_rel"]
    risks = [_leg_number_or(l, "risk") for l in legs]
    if any(r is None for r in risks):
        return {
            "name": "risk_balance",
            "passed": False,
            "detail": "leg risk missing",
        }
    abs_risks = [abs(r) for r in risks]  # type: ignore[arg-type]
    avg = sum(abs_risks) / len(abs_risks)
    if avg <= 0:
        return {
            "name": "risk_balance",
            "passed": False,
            "detail": "zero risk",
        }
    max_delta = max(abs(r - avg) for r in abs_risks)
    rel = max_delta / avg
    return {
        "name": "risk_balance",
        "passed": rel <= rel_tol,
        "detail": f"Δ {rel * 100:.1f}% (tol {rel_tol * 100:.0f}%)",
    }


def _fly_risk_balance_signal(
    legs: list[dict],
    tol: dict[str, float],
) -> dict:
    """Butterfly risk balance: wings similar, belly ~ 2x average wing."""
    rel_tol = tol["risk_balance_rel"]
    risks = [_leg_number_or(l, "risk") for l in legs[:3]]
    if len(risks) < 3 or any(r is None for r in risks):
        return {
            "name": "risk_balance",
            "passed": False,
            "detail": "leg risk missing",
        }
    front_abs = abs(risks[0])  # type: ignore[arg-type]
    belly_abs = abs(risks[1])  # type: ignore[arg-type]
    back_abs = abs(risks[2])  # type: ignore[arg-type]
    wing_denom = max(front_abs, back_abs, 1e-9)
    wing_rel = abs(front_abs - back_abs) / wing_denom
    wing_avg = (front_abs + back_abs) / 2
    expected_belly = 2 * wing_avg
    belly_denom = max(belly_abs, expected_belly, 1e-9)
    belly_rel = abs(belly_abs - expected_belly) / belly_denom
    return {
        "name": "risk_balance",
        "passed": wing_rel <= rel_tol and belly_rel <= rel_tol,
        "detail": (
            f"wings delta {wing_rel * 100:.1f}%, "
            f"belly delta {belly_rel * 100:.1f}% "
            f"(tol {rel_tol * 100:.0f}%)"
        ),
    }


def _pts_match_signal(
    derived_bp: float | None,
    reported_pts: float | None,
    tol: dict[str, float],
) -> dict:
    """Pass when derived spread (bp) is within pts_match_bp of reported PTS,
    directly or up to a clean order-of-magnitude scale factor."""
    bp_tol = tol["pts_match_bp"]
    if derived_bp is None or reported_pts is None:
        return {
            "name": "pts_match",
            "passed": False,
            "detail": (
                "leg fixed_rate missing"
                if derived_bp is None
                else "PTS not reported"
            ),
        }
    reported = float(reported_pts)
    if not math.isfinite(reported):
        return {
            "name": "pts_match",
            "passed": False,
            "detail": "PTS not reported",
        }
    direct_delta = abs(derived_bp - reported)
    scale = _find_scale_match(derived_bp, reported, bp_tol)

    # Priority: non-1x scale with smaller residual than direct
    if scale and scale["factor"] != 1 and scale["residual"] < direct_delta:
        return {
            "name": "pts_match",
            "passed": True,
            "detail": (
                f"derived {_format_bp(derived_bp)}bp vs reported "
                f"{_format_bp(reported)}bp matches at {scale['factor']}× "
                f"scale (Δ {_format_bp(scale['residual'])}, tol "
                f"±{bp_tol}); likely unit mismatch "
                f"(decimal/percent/bps)"
            ),
        }
    # Direct match
    if direct_delta <= bp_tol:
        return {
            "name": "pts_match",
            "passed": True,
            "detail": (
                f"derived {_format_bp(derived_bp)}bp vs reported "
                f"{_format_bp(reported)}bp (Δ "
                f"{_format_bp(direct_delta)}, tol ±{bp_tol})"
            ),
        }
    # Fallback: non-1x scale match (even if residual >= direct_delta)
    if scale and scale["factor"] != 1:
        return {
            "name": "pts_match",
            "passed": True,
            "detail": (
                f"derived {_format_bp(derived_bp)}bp vs reported "
                f"{_format_bp(reported)}bp matches at {scale['factor']}× "
                f"scale (Δ {_format_bp(scale['residual'])}, tol "
                f"±{bp_tol}); likely unit mismatch "
                f"(decimal/percent/bps)"
            ),
        }
    # No match
    return {
        "name": "pts_match",
        "passed": False,
        "detail": (
            f"derived {_format_bp(derived_bp)}bp vs reported "
            f"{_format_bp(reported)}bp (Δ "
            f"{_format_bp(direct_delta)}, tol ±{bp_tol})"
        ),
    }


def _per_leg_pts_signal(legs: list[dict]) -> dict:
    """Check that every leg has a finite per-leg PTS."""
    present = all(_is_finite(l.get("package_transaction_spread")) for l in legs)
    if present and len(legs) > 0:
        detail = ", ".join(
            f"{l.get('tenor_years', '?')}Y="
            f"{_format_bp(float(l['package_transaction_spread']))}"
            for l in legs
        )
    else:
        detail = "one or more legs missing per-leg PTS"
    return {
        "name": "per_leg_pts_present",
        "passed": present and len(legs) > 0,
        "detail": detail,
    }


def _per_leg_matched_maturity_signal(legs: list[dict]) -> dict:
    """Check all legs have a maturity date populated."""
    all_have = all(
        bool(l.get("swap_maturity_date") or l.get("expiration_date"))
        for l in legs
    )
    if all_have and len(legs) > 0:
        detail = ", ".join(
            l.get("swap_maturity_date") or l.get("expiration_date") or "—"
            for l in legs
        )
    else:
        detail = "one or more legs missing maturity date"
    return {
        "name": "per_leg_matched_maturity",
        "passed": all_have and len(legs) > 0,
        "detail": detail,
    }


def _spread_over_signals(
    package_indicator: bool,
    has_spread: bool,
    package_transaction_spread: float | None,
) -> list[dict]:
    indicator_on = bool(package_indicator)
    pts = package_transaction_spread
    pts_numeric = _num_or_none(pts)
    has_pts_number = pts_numeric is not None and pts_numeric != 0
    return [
        {
            "name": "package_indicator_on",
            "passed": indicator_on,
            "detail": "true" if indicator_on else "broker did not flag as a package",
        },
        {
            "name": "has_spread",
            "passed": bool(has_spread),
            "detail": "has_spread true" if has_spread else "has_spread not set",
        },
        {
            "name": "pts_present",
            "passed": has_pts_number,
            "detail": (
                f"PTS = {pts_numeric}" if has_pts_number else "PTS missing or zero"
            ),
        },
    ]


def _matched_maturity_signals(
    package_indicator: bool,
    legs: list[dict],
) -> list[dict]:
    indicator_on = bool(package_indicator)
    maturities = [
        l.get("swap_maturity_date") or l.get("expiration_date")
        for l in legs
    ]
    maturities = [m for m in maturities if m]
    same_maturity = (
        len(maturities) >= 2 and all(m == maturities[0] for m in maturities)
    )
    indices = set()
    for l in legs:
        idx = l.get("rate_index_clean")
        if idx:
            indices.add(idx)
    indices_distinct = len(legs) >= 2 and len(indices) >= 2
    return [
        {
            "name": "package_indicator_on",
            "passed": indicator_on,
            "detail": "true" if indicator_on else "broker did not flag as a package",
        },
        {
            "name": "same_maturity",
            "passed": same_maturity,
            "detail": (
                f"all legs mature {maturities[0]}"
                if same_maturity
                else f"mismatched maturities: {', '.join(maturities) or '—'}"
            ),
        },
        {
            "name": "distinct_indices",
            "passed": indices_distinct,
            "detail": (
                f"indices: {', '.join(sorted(indices))}"
                if indices_distinct
                else f"only one rate index: {', '.join(sorted(indices)) or '—'}"
            ),
        },
    ]


def _curve_signals(
    package_indicator: bool,
    n_package_legs: int,
    package_transaction_spread: float | None,
    legs: list[dict],
    tol: dict[str, float],
) -> list[dict]:
    legs_raw = legs
    legs_sorted = _sort_legs_tenor_asc(legs_raw)
    indicator_on = bool(package_indicator)
    n = n_package_legs
    front = legs_sorted[0] if len(legs_sorted) > 0 else {}
    back = legs_sorted[1] if len(legs_sorted) > 1 else {}
    r1 = _leg_number_or(front, "fixed_rate")
    r2 = _leg_number_or(back, "fixed_rate")
    derived_bp: float | None = None
    if r1 is not None and r2 is not None:
        derived_bp = _fixed_rate_spread_to_bp(r2 - r1, [r1, r2])

    return [
        {
            "name": "package_indicator_on",
            "passed": indicator_on,
            "detail": "true" if indicator_on else "broker did not flag as a package",
        },
        _risk_balance_signal(
            legs_sorted[:2], [1, 1], "Risk balance (DV01-neutral)", tol,
        ),
        _pts_match_signal(derived_bp, package_transaction_spread, tol),
        {
            "name": "tenor_monotonic",
            "passed": _is_ascending_by_tenor(legs_raw),
            "detail": " → ".join(
                f"{l.get('tenor_years')}Y" if _is_finite(l.get("tenor_years")) else "?"
                for l in legs_raw
            ),
        },
        {
            "name": "leg_count",
            "passed": n == 2,
            "detail": f"expected 2, got {n}",
        },
    ]


def _fly_signals(
    package_indicator: bool,
    n_package_legs: int,
    package_transaction_spread: float | None,
    legs: list[dict],
    tol: dict[str, float],
) -> list[dict]:
    legs_raw = legs
    legs_sorted = _sort_legs_tenor_asc(legs_raw)
    indicator_on = bool(package_indicator)
    n = n_package_legs
    front = legs_sorted[0] if len(legs_sorted) > 0 else {}
    belly = legs_sorted[1] if len(legs_sorted) > 1 else {}
    back = legs_sorted[2] if len(legs_sorted) > 2 else {}
    r_f = _leg_number_or(front, "fixed_rate")
    r_b = _leg_number_or(belly, "fixed_rate")
    r_k = _leg_number_or(back, "fixed_rate")
    derived_bp: float | None = None
    if r_f is not None and r_b is not None and r_k is not None:
        derived_bp = _fixed_rate_spread_to_bp(
            2 * r_b - r_f - r_k, [r_f, r_b, r_k],
        )

    return [
        {
            "name": "package_indicator_on",
            "passed": indicator_on,
            "detail": "true" if indicator_on else "broker did not flag as a package",
        },
        _fly_risk_balance_signal(legs_sorted, tol),
        _pts_match_signal(derived_bp, package_transaction_spread, tol),
        {
            "name": "tenor_monotonic",
            "passed": _is_ascending_by_tenor(legs_raw),
            "detail": " → ".join(
                f"{l.get('tenor_years')}Y" if _is_finite(l.get("tenor_years")) else "?"
                for l in legs_raw
            ),
        },
        {
            "name": "leg_count",
            "passed": n == 3,
            "detail": f"expected 3, got {n}",
        },
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_package_confidence(
    package_type: str,
    package_indicator: bool,
    n_package_legs: int,
    package_transaction_spread: float | None,
    has_spread: bool,
    legs: list[dict],
    *,
    tolerance_overrides: dict[str, float] | None = None,
) -> dict:
    """Score package-detection confidence for a single USD swap tape row.

    Parameters
    ----------
    package_type : str
        Raw package_type from the SDR feed.
    package_indicator : bool
        Whether the broker flagged the trade as a package.
    n_package_legs : int
        Number of legs in the package.
    package_transaction_spread : float | None
        The reported package transaction spread (PTS).
    has_spread : bool
        Whether has_spread is set on the row.
    legs : list[dict]
        Per-leg dicts. Expected keys: tenor_years, risk, fixed_rate,
        package_transaction_spread, swap_maturity_date, expiration_date,
        rate_index_clean.
    tolerance_overrides : dict | None
        Optional overrides for DEFAULT_TOLERANCES keys.

    Returns
    -------
    dict
        {score, total, tone, signals, resolved_type,
         inferred_type, inferred_type_reason}
        where each signal is {name, passed, detail}.
    """
    tol = {**DEFAULT_TOLERANCES, **(tolerance_overrides or {})}
    resolved_type = _normalize_type(package_type)
    signals: list[dict]
    is_info = False

    if resolved_type == "CURVE":
        signals = _curve_signals(
            package_indicator, n_package_legs,
            package_transaction_spread, legs, tol,
        )
    elif resolved_type == "FLY":
        signals = _fly_signals(
            package_indicator, n_package_legs,
            package_transaction_spread, legs, tol,
        )
    elif resolved_type == "SPREADOVER":
        signals = _spread_over_signals(
            package_indicator, has_spread, package_transaction_spread,
        )
    elif resolved_type == "MATCHED_MATURITY":
        signals = _matched_maturity_signals(package_indicator, legs)
    elif resolved_type == "SPREADOVER_CURVE":
        signals = _curve_signals(
            package_indicator, n_package_legs,
            package_transaction_spread, legs, tol,
        ) + [_per_leg_pts_signal(legs)]
    elif resolved_type == "SPREADOVER_FLY":
        signals = _fly_signals(
            package_indicator, n_package_legs,
            package_transaction_spread, legs, tol,
        ) + [_per_leg_pts_signal(legs)]
    elif resolved_type == "MATCHED_MATURITY_CURVE":
        signals = _curve_signals(
            package_indicator, n_package_legs,
            package_transaction_spread, legs, tol,
        ) + [_per_leg_matched_maturity_signal(legs)]
    elif resolved_type == "MATCHED_MATURITY_FLY":
        signals = _fly_signals(
            package_indicator, n_package_legs,
            package_transaction_spread, legs, tol,
        ) + [_per_leg_matched_maturity_signal(legs)]
    else:
        # MAC, IMM, FOMC, OUTRIGHT, and anything else
        signals = _outright_signals(package_indicator, n_package_legs)
        is_info = True

    score = sum(1 for s in signals if s["passed"])
    total = len(signals)
    tone = _pick_tone(score, total, is_info)

    return {
        "score": score,
        "total": total,
        "tone": tone,
        "signals": signals,
        "resolved_type": resolved_type,
        "inferred_type": None,
        "inferred_type_reason": None,
    }


# ---------------------------------------------------------------------------
# Pandas convenience wrapper
# ---------------------------------------------------------------------------

def _bool_coerce(v: Any) -> bool:
    """Coerce a value to bool, handling pandas NA / None / strings."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "t", "1", "yes", "y")
    try:
        return bool(v)
    except (TypeError, ValueError):
        return False


def compute_confidence_for_group(
    g: pd.DataFrame,
    package_type: str,
    *,
    tolerance_overrides: dict[str, float] | None = None,
) -> dict:
    """Extract the fields needed from a pandas group and call
    :func:`compute_package_confidence`.

    Parameters
    ----------
    g : pd.DataFrame
        A group of rows sharing the same package_id, sorted by
        execution_timestamp.
    package_type : str
        The package_type for this group (may be 'OUTRIGHT', 'CURVE', etc.).
    tolerance_overrides : dict | None
        Optional overrides for DEFAULT_TOLERANCES keys.

    Returns
    -------
    dict
        Same as :func:`compute_package_confidence`.
    """
    # --- scalar fields ---
    package_indicator = False
    if "package_indicator" in g.columns:
        # _any() style: True if any leg has it
        pi_series = g["package_indicator"].map(_bool_coerce)
        package_indicator = bool(pi_series.any())

    n_package_legs = len(g)

    pkg_spread: float | None = None
    if "package_transaction_spread" in g.columns:
        raw = g["package_transaction_spread"].iloc[0]
        pkg_spread = _num_or_none(raw)

    has_spread_val = False
    if "has_spread" in g.columns:
        has_spread_val = bool(
            g["has_spread"].fillna(False).astype(bool).any()
        )

    # --- build leg dicts ---
    leg_fields = [
        "tenor_years", "risk", "fixed_rate", "package_transaction_spread",
        "swap_maturity_date", "expiration_date", "rate_index_clean",
    ]
    legs: list[dict] = []
    for _, row in g.iterrows():
        leg: dict[str, Any] = {}
        for f in leg_fields:
            if f in g.columns:
                v = row[f]
                # Convert pandas NA / NaT to None
                if pd.isna(v) if not isinstance(v, str) else False:
                    leg[f] = None
                else:
                    leg[f] = v
            else:
                leg[f] = None
        legs.append(leg)

    return compute_package_confidence(
        package_type=package_type,
        package_indicator=package_indicator,
        n_package_legs=n_package_legs,
        package_transaction_spread=pkg_spread,
        has_spread=has_spread_val,
        legs=legs,
        tolerance_overrides=tolerance_overrides,
    )
