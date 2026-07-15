"""Ladder sign/visibility/bucket conventions (ladder spec sections 4, 6, 8).

Persisted convention: delta_dv01 > 0  <=>  dealer long futures-equivalent
<=> dealer RECEIVED fixed. Off-market (NPV_VS_UPFRONT) directions are the
net-fixed frame from the classifier, so ALL legs carry the same sign; the
on-market spread/fly methods are true opposite-leg structures.
"""
from __future__ import annotations

import pandas as pd

VISIBILITY_BLOCK_DELAY_MIN = 15
VISIBILITY_DEFAULT_DELAY_MIN = 1
PROVISIONAL_HALF_LIVES_MIN = {"default": 90.0, "block": 240.0}  # Phase 4 recalibrates
EPS_HALF_LIVES = 3.0


def visibility_timestamp(execution_ts, is_block: bool) -> pd.Timestamp:
    delay = VISIBILITY_BLOCK_DELAY_MIN if is_block else VISIBILITY_DEFAULT_DELAY_MIN
    return pd.Timestamp(execution_ts) + pd.Timedelta(minutes=delay)


def dealer_leg_signs(kind: str, method: str, direction: str, n_legs: int) -> list:
    if direction not in ("PAID", "RECEIVED"):
        raise ValueError(f"cannot sign direction {direction!r}")
    recv = 1 if direction == "RECEIVED" else -1
    if method == "NPV_VS_UPFRONT":
        return [recv] * n_legs                       # net-fixed frame: same sign
    if kind == "OUTRIGHT":
        return [recv]
    if kind == "CURVE" and n_legs == 2:
        return [-recv, recv]                         # RECEIVED spread = recv back, pay front
    if kind == "FLY" and n_legs == 3:
        return [-recv, recv, -recv]                  # RECEIVED fly = recv belly, pay wings
    raise ValueError(f"unsupported structure {kind}/{method} with {n_legs} legs")


def meeting_bucket_key(effective_date) -> str:
    return pd.Timestamp(effective_date).date().isoformat()


def contract_month_key(effective_date) -> str:
    d = pd.Timestamp(effective_date)
    return f"{d.year:04d}-{d.month:02d}"
