"""Ladder sign/visibility/bucket conventions (ladder spec sections 4, 6, 8).

Persisted convention: delta_dv01 > 0  <=>  dealer long futures-equivalent
<=> dealer RECEIVED fixed. Off-market (NPV_VS_UPFRONT) directions are the
net-fixed frame from the classifier, so ALL legs carry the same sign; the
on-market spread/fly methods are true opposite-leg structures.

Visibility timestamp (audit-revised, ladder spec section 6): an external
audit invalidated the original two-bucket rule (+1min non-block / +15min
block) as an oversimplification of 17 CFR Part 43 Appendix C. The tape has
no ``dissemination_timestamp`` column (confirmed by the Task 5 lineage probe
and re-confirmed here), so visibility is still a *legal delay estimate*
applied to execution_timestamp, but now via the richer Appendix C classes
in ``visibility_class``/``VISIBILITY_DELAYS_MIN`` below rather than the
old two-bucket rule.
"""
from __future__ import annotations

import pandas as pd

# --- legacy two-bucket constants (pre-audit) -------------------------------
# Superseded by VISIBILITY_DELAYS_MIN / visibility_class below. Kept only so
# any external readers of these names don't break; do not use in new code.
VISIBILITY_BLOCK_DELAY_MIN = 15
VISIBILITY_DEFAULT_DELAY_MIN = 1

# SEF/DCM platform_identifier codes on the tape that indicate an on-facility
# execution (vs. bilateral D2C off-facility). Anything else non-null is a
# definite off-facility platform code; null/missing is indeterminate.
SEF_PLATFORM_CODES = {"TWSF", "BBSF", "BGCD", "DWSF", "IGDL", "ISWV", "TPSE", "TSEF"}

# 17 CFR Part 43 Appendix C legal delay classes -> minutes until public
# dissemination is presumed. INDETERMINATE is the conservative (longest)
# fallback for any input that can't be classified with confidence.
VISIBILITY_DELAYS_MIN = {
    "ON_FACILITY_NON_BLOCK": 1,
    "SEF_BLOCK": 15,
    "CLEARED_OFF_FACILITY_CAPPED": 15,
    "UNCLEARED_OFF_FACILITY": 30,
    "INDETERMINATE": 60,
}

PROVISIONAL_HALF_LIVES_MIN = {"default": 90.0, "block": 240.0}  # Phase 4 recalibrates
EPS_HALF_LIVES = 3.0


def visibility_class(*, is_block, cleared, on_facility, is_capped) -> str:
    """Return the Part 43 Appendix C delay class name for a print.

    Rules (first match wins; all comparisons use ``is True``/``is False``,
    never truthiness, so a None input can never satisfy a branch):
      - on_facility=True,  is_block=False               -> ON_FACILITY_NON_BLOCK (+1min)
      - on_facility=True,  is_block=True                -> SEF_BLOCK (+15min)
      - on_facility=False, cleared=True, is_capped=True -> CLEARED_OFF_FACILITY_CAPPED (+15min)
      - on_facility=False, cleared=False                -> UNCLEARED_OFF_FACILITY (+30min)
      - anything else (any field None/indeterminate, OR a combination not
        enumerated above -- e.g. off-facility + cleared + NOT capped, which
        is observed on the tape and has no dedicated class) -> INDETERMINATE
        (+60min), the conservative fallback.
    """
    if on_facility is True and is_block is False:
        return "ON_FACILITY_NON_BLOCK"
    if on_facility is True and is_block is True:
        return "SEF_BLOCK"
    if on_facility is False and cleared is True and is_capped is True:
        return "CLEARED_OFF_FACILITY_CAPPED"
    if on_facility is False and cleared is False:
        return "UNCLEARED_OFF_FACILITY"
    return "INDETERMINATE"


def visibility_timestamp(execution_ts, *, is_block=False, cleared=None,
                         on_facility=None, is_capped=False) -> pd.Timestamp:
    """Legal-delay-adjusted visibility timestamp (17 CFR Part 43 Appendix C).

    Keyword-only except execution_ts, so the pre-audit call pattern
    ``visibility_timestamp(ts, is_block=True)`` still works: is_block is
    honored, and cleared/on_facility default to None (indeterminate) ->
    +60min. That's MORE conservative than the old +15min/+1min two-bucket
    rule the audit invalidated, which is the correct direction to err.
    """
    cls = visibility_class(is_block=is_block, cleared=cleared,
                           on_facility=on_facility, is_capped=is_capped)
    delay = VISIBILITY_DELAYS_MIN[cls]
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
