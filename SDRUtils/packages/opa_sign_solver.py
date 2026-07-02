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

from SDRUtils.packages.ptp_grouper import numeric_like


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


# Above this leg count, exact enumeration switches from a vectorized
# full 2^N sweep to meet-in-the-middle (2 x 2^(N/2) half-enumerations +
# binary search). Both are exact; MITM turns the N=24 worst case from
# ~3s of full sweep into single-digit milliseconds.
_MITM_MIN_N = 16


def _half_nets(vals: np.ndarray) -> np.ndarray:
    """Nets of all +/-1 assignments over ``vals``; index = mask (bit i set = +1)."""
    nets = np.array([-vals.sum()], dtype=np.float64)
    for v in vals:
        nets = np.concatenate([nets, nets + 2.0 * v])
    return nets


def _select_best(
    residual: np.ndarray,
    direct: np.ndarray,
    masks: np.ndarray,
    nets: np.ndarray,
    tol: float,
) -> tuple[float, float, int, float]:
    """Pick by (min residual, then min net-to-+ptp distance, then lowest mask).

    ``tol`` must scale with the input magnitudes: a sign vector and its
    complement have *mathematically equal* residuals, but float summation
    noise on $1M-scale OPAs is ~1e-8 — far above a fixed 1e-9 window — so
    a too-tight window lets rounding luck, not the +PTP preference, decide
    which direction of the package wins.
    """
    r_min = float(residual.min())
    cand = np.flatnonzero(residual <= r_min + tol)
    d = direct[cand]
    d_min = float(d.min())
    cand = cand[d <= d_min + tol]
    local = cand[np.argmin(masks[cand])]
    return (
        float(residual[local]),
        float(direct[local]),
        int(masks[local]),
        float(nets[local]),
    )


def _solve_brute(opa: list[float], ptp: float) -> tuple[list[int], float, float]:
    """Exact 2^N enumeration.

    Selection order: minimal residual; among residuals tied within 1e-9,
    prefer the net closer to +ptp; then the lowest mask (bit i set = +1
    on leg i). The original pure-python loop was ~1.7s at N=20 and ~27s
    at N=24, which stalled the live service loop.
    """
    n = len(opa)
    opa_arr = np.asarray(opa, dtype=np.float64)
    tie_tol = 1e-9 + 1e-13 * (float(np.abs(opa_arr).sum()) + abs(ptp))

    if n <= _MITM_MIN_N:
        # Full vectorized sweep — cheap up to 2^16 masks.
        masks = np.arange(1 << n, dtype=np.uint32)
        plus = np.zeros(masks.shape[0], dtype=np.float64)
        for i in range(n):
            plus += opa_arr[i] * ((masks >> np.uint32(i)) & np.uint32(1))
        nets = 2.0 * plus - float(opa_arr.sum())
        direct = np.abs(nets - ptp)
        residual = np.minimum(direct, np.abs(nets + ptp))
        best_residual, _, best_mask, best_net = _select_best(
            residual, direct, masks, nets, tie_tol,
        )
    else:
        # Meet-in-the-middle: any optimal (a, b) pair has netsA[a] adjacent
        # to (target - netsB[b]) in the sorted half-A nets, so scanning the
        # two sorted neighbors per b per target covers every optimum.
        h = n // 2
        nets_a = _half_nets(opa_arr[:h])
        nets_b = _half_nets(opa_arr[h:])
        order_a = np.argsort(nets_a, kind="stable")
        sorted_a = nets_a[order_a]
        masks_b = np.arange(nets_b.shape[0], dtype=np.int64)

        cand_masks = []
        cand_nets = []
        for target in (ptp, -ptp):
            want = target - nets_b
            pos = np.searchsorted(sorted_a, want)
            for off in (-1, 0):
                idx = np.clip(pos + off, 0, sorted_a.shape[0] - 1)
                a_mask = order_a[idx]
                cand_masks.append(a_mask | (masks_b << h))
                cand_nets.append(sorted_a[idx] + nets_b)
        masks = np.concatenate(cand_masks)
        nets = np.concatenate(cand_nets)
        direct = np.abs(nets - ptp)
        residual = np.minimum(direct, np.abs(nets + ptp))
        best_residual, _, best_mask, best_net = _select_best(
            residual, direct, masks, nets, tie_tol,
        )

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
    ptp_notation_col: str = "package_transaction_price_notation",
    rate_col: str = "fixed_rate",
    tenor_col: str = "tenor_years",
    pv01_col: str = "estimated_pv01",
) -> pd.DataFrame:
    """Batch OPA sign solver across all PTP groups in the DataFrame.

    Adds per-leg columns: opa_sign, opa_signed_amount.
    Adds per-group columns: opa_signed_net, opa_ptp_residual,
    opa_sign_confidence, opa_constrained_net, opa_constrained_residual,
    dealer_spread_est, dealer_spread_bps.

    The Sigma(signed OPA) = PTP tieout only makes sense when the PTP is a
    monetary amount (Part 43 price notation 1). Price/decimal-notation
    PTPs (e.g. ``9.9999999999`` with notation 3) still group upstream,
    but solving against them would produce fake EXACT confidences, so
    those groups are reported UNRESOLVED with no per-leg signs.
    """
    out = df.copy()
    for col in ["opa_sign", "opa_signed_amount", "opa_signed_net",
                "opa_ptp_residual", "opa_sign_confidence",
                "opa_constrained_net", "opa_constrained_residual",
                "dealer_spread_est", "dealer_spread_bps",
                "ptp_price_notation"]:
        out[col] = None

    if ptp_group_col not in out.columns:
        return out

    for gid, grp in out.groupby(ptp_group_col):
        if pd.isna(gid):
            continue

        opas = numeric_like(grp[opa_col]).fillna(0).tolist() if opa_col in grp.columns else [0.0] * len(grp)
        ptp_vals = numeric_like(grp[ptp_col]) if ptp_col in grp.columns else pd.Series(dtype=float)
        ptp_val = ptp_vals.dropna().iloc[0] if ptp_vals.notna().any() else 0.0

        notation_val = None
        if ptp_notation_col in grp.columns:
            notation = numeric_like(grp[ptp_notation_col])
            if notation.notna().any():
                notation_val = int(notation.dropna().iloc[0])
        mask = out[ptp_group_col] == gid
        out.loc[mask, "ptp_price_notation"] = notation_val
        if notation_val is not None and notation_val != 1:
            # Non-monetary PTP: no meaningful dollar tieout.
            out.loc[mask, "opa_sign_confidence"] = "UNRESOLVED"
            continue

        rates = numeric_like(grp[rate_col]).fillna(0).tolist() if rate_col in grp.columns else [0.0] * len(grp)
        tenors = numeric_like(grp[tenor_col]).fillna(0).tolist() if tenor_col in grp.columns else [0.0] * len(grp)
        rt_groups = _rate_tenor_group_index(rates, tenors)

        result = solve_opa_signs(opas, ptp_val, rate_tenor_groups=rt_groups)

        idx_list = out.loc[mask].index.tolist()

        for i, ix in enumerate(idx_list):
            out.at[ix, "opa_sign"] = result["signs"][i]
            out.at[ix, "opa_signed_amount"] = result["signs"][i] * opas[i]

        total_dv01 = numeric_like(grp[pv01_col]).fillna(0).sum() if pv01_col in grp.columns else 0.0
        # residual is $, total_dv01 is $/bp — the ratio is already basis
        # points. The spec's original ×100 made this a % of DV01 while
        # labeling it bp (2026-07-01 audit finding, PM decided: true bp).
        spread_bps = (
            (result["residual"] / total_dv01)
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
