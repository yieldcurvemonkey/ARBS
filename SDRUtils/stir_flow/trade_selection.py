"""Trade eligibility + classification-unit construction (spec section 2)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd

from SDRUtils.stir_flow import config

_LEG_COLS = """
    l.trade_id, l.package_id, l.as_of_date,
    l.execution_timestamp, l.original_execution_timestamp,
    l.trade_type, l.rate_index_clean, l.venue,
    l.special_tenor_type, l.fomc_meeting_label,
    l.tenor_label, l.forward_label, l.forward_start_years,
    l.effective_date, l.expiration_date,
    l.notional, l.risk, l.fixed_rate,
    l.other_payment_ufro, l.is_capped, l.is_block, l.is_off_date,
    l.leg_tape_label, l.execution_session, l.platform_identifier, l.cleared,
    p.package_structure, p.n_package_legs,
    p.package_transaction_price AS pkg_ptp,
    p.package_transaction_spread AS pkg_pts
"""

ELIGIBLE_LEGS_SQL = f"""
SELECT {_LEG_COLS}
FROM arbs_usd_swap_tape_legs_v2 l
LEFT JOIN arbs_usd_swap_tape_packages_v2 p USING (package_id)
WHERE l.as_of_date BETWEEN %(start)s AND %(end)s
  AND l.economic_class = 'ECONOMIC_FLOW'
  AND l.contributes_to_flow = true
  AND l.venue = 'D2C'
  AND l.rate_index_clean IN ('SOFR', 'FED_FUNDS')
  AND l.fixed_rate IS NOT NULL
ORDER BY l.execution_timestamp
"""

ALL_PKG_LEGS_SQL = f"""
SELECT {_LEG_COLS}
FROM arbs_usd_swap_tape_legs_v2 l
LEFT JOIN arbs_usd_swap_tape_packages_v2 p USING (package_id)
WHERE l.package_id = ANY(%(package_ids)s)
ORDER BY l.package_id, l.expiration_date
"""


@dataclasses.dataclass
class Unit:
    unit_key: str
    kind: str                    # OUTRIGHT | CURVE | FLY | PKG
    legs: pd.DataFrame           # all legs, sorted by expiration_date
    package_id: str | None
    is_off_market: bool


def _horizon(as_of: datetime.date) -> datetime.date:
    return as_of + datetime.timedelta(days=config.SUB3Y_HORIZON_DAYS)


def is_excluded_unit(legs: pd.DataFrame) -> str | None:
    labels = legs["leg_tape_label"].fillna("")
    if labels.str.contains("|".join(config.EXCLUDED_LABEL_TOKENS)).any():
        return "EXCLUDED_UNDERLIER"
    if legs["trade_type"].isin(config.EXCLUDED_TRADE_TYPES).any():
        return "EXCLUDED_TRADE_TYPE"
    if legs["fixed_rate"].isna().any():
        return "MISSING_FIXED_RATE"
    as_of = pd.Timestamp(legs.iloc[0]["as_of_date"]).date()
    mats = pd.to_datetime(legs["expiration_date"]).dt.date
    if (mats > _horizon(as_of)).any():
        return "LEG_BEYOND_3Y"
    return None


def venue_status(platform_identifier: str) -> str:
    """Return 'D2C_WHITELISTED', 'D2D', or 'VENUE_UNKNOWN'.

    NOT called from ``is_excluded_unit`` -- venue is not a classification/
    projection-time exclusion. Units keep flowing through classification and
    the ladder regardless of venue_status; this is a read-time filter for
    the *signed research* aggregation (audit follow-up, Task A2), which must
    be whitelist-based rather than relying on the D2C-by-default heuristic
    in ``SDRUtils.analytics.flow.classify_venue``.
    """
    from SDRUtils.analytics.filters import D2D_PLATFORMS
    pid = str(platform_identifier).upper().strip() if pd.notna(platform_identifier) else ""
    if pid in D2D_PLATFORMS:
        return "D2D"
    if pid in config.D2C_PLATFORM_WHITELIST:
        return "D2C_WHITELISTED"
    return "VENUE_UNKNOWN"


def resolve_upfront(pkg_ptp, leg_ufros) -> tuple:
    ufro_sum = float(sum(u for u in leg_ufros if u)) if leg_ufros is not None else 0.0
    ptp_usd = None
    if pkg_ptp is not None and pkg_ptp == pkg_ptp and abs(float(pkg_ptp)) > config.PTP_USD_FLOOR:
        ptp_usd = abs(float(pkg_ptp))
    disagree = False
    if ptp_usd is not None and ufro_sum > 0:
        hi, lo = max(ptp_usd, ufro_sum), min(ptp_usd, ufro_sum)
        disagree = lo > 0 and (hi / lo) > config.PTP_UFRO_DISAGREE_RATIO
    if ptp_usd is not None:
        return ptp_usd, "PTP", disagree
    if ufro_sum > 0:
        return ufro_sum, "UFRO_SUM", False
    return None, None, False


def _kind(n_legs: int) -> str:
    return {1: "OUTRIGHT", 2: "CURVE", 3: "FLY"}.get(n_legs, "PKG")


def build_units(eligible: pd.DataFrame, all_legs: pd.DataFrame) -> list:
    units: list[Unit] = []
    seen: set[str] = set()
    for _, row in eligible.iterrows():
        pkg_id = row["package_id"]
        n = int(row["n_package_legs"] or 1)
        if n <= 1:
            key = row["trade_id"]
            if key in seen:
                continue
            seen.add(key)
            legs = eligible[eligible["trade_id"] == key].head(1).copy()
            upfront, _, _ = resolve_upfront(row.get("pkg_ptp"), [row.get("other_payment_ufro") or 0.0])
            units.append(Unit(key, "OUTRIGHT", legs, None, upfront is not None))
        else:
            if pkg_id in seen:
                continue
            seen.add(pkg_id)
            legs = all_legs[all_legs["package_id"] == pkg_id].copy()
            legs = legs.sort_values("expiration_date").reset_index(drop=True)
            upfront, _, _ = resolve_upfront(
                legs.iloc[0].get("pkg_ptp"),
                list(legs["other_payment_ufro"].fillna(0.0)),
            )
            units.append(Unit(pkg_id, _kind(len(legs)), legs, pkg_id, upfront is not None))
    return units
