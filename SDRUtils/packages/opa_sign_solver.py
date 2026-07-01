# SDRUtils/packages/opa_sign_solver.py
"""OPA sign solver — infer pay/receive direction for package legs.

Brute-force 2^N for N <= 24, greedy heuristic above. Also supports
economically-constrained solving where legs sharing the same
(rate, tenor) must have the same sign.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


_TIER_THRESHOLDS = [
    (100.0, "EXACT"),
    (1_000.0, "TIGHT"),
    (50_000.0, "LOOSE"),
]


def confidence_tier(residual: float) -> str:
    for threshold, label in _TIER_THRESHOLDS:
        if residual < threshold:
            return label
    return "UNRESOLVED"


def _solve_brute(opa: list[float], ptp: float) -> tuple[list[int], float, float]:
    n = len(opa)
    best_mask = 0
    best_residual = float("inf")
    best_direct_dist = float("inf")  # tiebreaker: prefer net closer to +ptp
    best_net = 0.0
    for mask in range(1 << n):
        net = 0.0
        for i in range(n):
            net += opa[i] if (mask & (1 << i)) else -opa[i]
        residual = min(abs(net - ptp), abs(net + ptp))
        direct_dist = abs(net - ptp)
        if residual < best_residual or (
            abs(residual - best_residual) < 1e-9 and direct_dist < best_direct_dist
        ):
            best_residual = residual
            best_direct_dist = direct_dist
            best_mask = mask
            best_net = net
    signs = [1 if (best_mask & (1 << i)) else -1 for i in range(n)]
    return signs, best_net, best_residual


def _solve_greedy(opa: list[float], ptp: float) -> tuple[list[int], float, float]:
    indexed = sorted(enumerate(opa), key=lambda x: -x[1])
    signs = [0] * len(opa)
    running = 0.0
    for idx, val in indexed:
        plus_d = min(abs(running + val - ptp), abs(running + val + ptp))
        minus_d = min(abs(running - val - ptp), abs(running - val + ptp))
        if plus_d <= minus_d:
            signs[idx] = 1
            running += val
        else:
            signs[idx] = -1
            running -= val
    residual = min(abs(running - ptp), abs(running + ptp))
    return signs, running, residual


def _solve_constrained(
    opa: list[float],
    ptp: float,
    groups: list[int],
) -> tuple[list[int], float, float]:
    unique_groups = sorted(set(groups))
    k = len(unique_groups)
    group_map = {g: i for i, g in enumerate(unique_groups)}
    group_indices: list[list[int]] = [[] for _ in range(k)]
    for i, g in enumerate(groups):
        group_indices[group_map[g]].append(i)

    group_sums = [sum(opa[i] for i in idxs) for idxs in group_indices]

    if k <= 24:
        g_signs, g_net, g_residual = _solve_brute(group_sums, ptp)
    else:
        g_signs, g_net, g_residual = _solve_greedy(group_sums, ptp)

    signs = [0] * len(opa)
    for gi, idxs in enumerate(group_indices):
        for i in idxs:
            signs[i] = g_signs[gi]
    return signs, g_net, g_residual


_MAX_BRUTE_N = 24


def solve_opa_signs(
    opa_values: list[float],
    ptp_value: float,
    *,
    rate_tenor_groups: Optional[list[int]] = None,
) -> dict:
    """Solve for the sign assignment minimizing |Sigma(s*OPA) - PTP|.

    Returns dict with keys: signs, net, residual, confidence,
    constrained_signs, constrained_net, constrained_residual.
    """
    n = len(opa_values)
    if n == 0:
        return {
            "signs": [],
            "net": 0.0,
            "residual": abs(ptp_value),
            "confidence": "UNRESOLVED",
            "constrained_signs": None,
            "constrained_net": None,
            "constrained_residual": None,
        }

    if not math.isfinite(ptp_value) or ptp_value == 0:
        return {
            "signs": [1] * n,
            "net": sum(opa_values),
            "residual": abs(sum(opa_values)),
            "confidence": "UNRESOLVED",
            "constrained_signs": None,
            "constrained_net": None,
            "constrained_residual": None,
        }

    if n <= _MAX_BRUTE_N:
        signs, net, residual = _solve_brute(opa_values, ptp_value)
    else:
        signs, net, residual = _solve_greedy(opa_values, ptp_value)

    result = {
        "signs": signs,
        "net": net,
        "residual": residual,
        "confidence": confidence_tier(residual),
        "constrained_signs": None,
        "constrained_net": None,
        "constrained_residual": None,
    }

    if rate_tenor_groups is not None and len(rate_tenor_groups) == n:
        c_signs, c_net, c_residual = _solve_constrained(
            opa_values, ptp_value, rate_tenor_groups,
        )
        result["constrained_signs"] = c_signs
        result["constrained_net"] = c_net
        result["constrained_residual"] = c_residual

    return result


def _rate_tenor_group_index(
    fixed_rates: list[float],
    tenor_years: list[float],
) -> list[int]:
    """Assign a group index to each leg by (rate rounded to 0.01bp, tenor rounded to 0.1Y)."""
    keys = []
    for r, t in zip(fixed_rates, tenor_years):
        rr = round(r, 6) if r is not None and math.isfinite(r) else None
        tr = round(t, 1) if t is not None and math.isfinite(t) else None
        keys.append((rr, tr))
    unique = sorted(set(keys))
    key_to_idx = {k: i for i, k in enumerate(unique)}
    return [key_to_idx[k] for k in keys]


def solve_all_opa_signs(
    df: pd.DataFrame,
    *,
    ptp_group_col: str = "ptp_group_id",
    opa_col: str = "other_payment_amount",
    ptp_col: str = "package_transaction_price",
    rate_col: str = "fixed_rate",
    tenor_col: str = "tenor_years",
    pv01_col: str = "estimated_pv01",
) -> pd.DataFrame:
    """Batch OPA sign solver across all PTP groups in the DataFrame.

    Adds per-leg columns: opa_sign, opa_signed_amount.
    Adds per-group columns: opa_signed_net, opa_ptp_residual,
    opa_sign_confidence, opa_constrained_net, opa_constrained_residual,
    dealer_spread_est, dealer_spread_bps.
    """
    out = df.copy()
    for col in ["opa_sign", "opa_signed_amount", "opa_signed_net",
                "opa_ptp_residual", "opa_sign_confidence",
                "opa_constrained_net", "opa_constrained_residual",
                "dealer_spread_est", "dealer_spread_bps"]:
        out[col] = None

    if ptp_group_col not in out.columns:
        return out

    for gid, grp in out.groupby(ptp_group_col):
        if pd.isna(gid):
            continue

        opas = pd.to_numeric(grp[opa_col], errors="coerce").fillna(0).tolist()
        ptp_vals = pd.to_numeric(grp[ptp_col], errors="coerce")
        ptp_val = ptp_vals.dropna().iloc[0] if ptp_vals.notna().any() else 0.0

        rates = pd.to_numeric(grp[rate_col], errors="coerce").fillna(0).tolist()
        tenors = pd.to_numeric(grp[tenor_col], errors="coerce").fillna(0).tolist()
        rt_groups = _rate_tenor_group_index(rates, tenors)

        result = solve_opa_signs(opas, ptp_val, rate_tenor_groups=rt_groups)

        mask = out[ptp_group_col] == gid
        idx_list = out.loc[mask].index.tolist()

        for i, ix in enumerate(idx_list):
            out.at[ix, "opa_sign"] = result["signs"][i]
            out.at[ix, "opa_signed_amount"] = result["signs"][i] * opas[i]

        total_dv01 = pd.to_numeric(grp[pv01_col], errors="coerce").fillna(0).sum()
        spread_bps = (
            (result["residual"] / total_dv01 * 100)
            if total_dv01 > 0 else None
        )

        out.loc[mask, "opa_signed_net"] = result["net"]
        out.loc[mask, "opa_ptp_residual"] = result["residual"]
        out.loc[mask, "opa_sign_confidence"] = result["confidence"]
        out.loc[mask, "opa_constrained_net"] = result.get("constrained_net")
        out.loc[mask, "opa_constrained_residual"] = result.get("constrained_residual")
        out.loc[mask, "dealer_spread_est"] = result["residual"]
        out.loc[mask, "dealer_spread_bps"] = spread_bps

    return out
