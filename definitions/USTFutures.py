from __future__ import annotations

import datetime
from typing import Dict, List, Sequence, Tuple

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import CME_MONTH_CODE, _imm_cutoff, _next_contracts

UST_FUTURE_ROOTS: Dict[str, str] = {
    "2Y": "TU",
    "5Y": "FV",
    "10Y": "TY",
    "30Y": "US",
    "ULTRA": "WN",
    "ULTRA10Y": "UXY",
}

UST_FUTURE_BARCHART_ROOTS: Dict[str, str] = {
    "TU": "ZT",
    "FV": "ZF",
    "TY": "ZN",
    "US": "ZB",
    "WN": "UB",
    "UXY": "TN",
}

UST_FUTURE_VALID_MONTHS: Sequence[int] = (3, 6, 9, 12)

# Tick specifications: (tick_size, tick_value_usd) per contract root.
# tick_size  = minimum price increment (fraction of a point)
# tick_value = dollar value of one tick move per contract
UST_FUTURE_TICK_SPECS: Dict[str, Tuple[float, float]] = {
    "TU": (1.0 / 256.0, 7.8125),
    "Z3N": (1.0 / 256.0, 7.8125),
    "FV": (1.0 / 128.0, 7.8125),
    "TY": (1.0 / 64.0, 15.625),
    "UXY": (1.0 / 64.0, 15.625),
    "US": (1.0 / 32.0, 31.25),
    "WN": (1.0 / 32.0, 31.25),
    "TWE": (1.0 / 32.0, 31.25),
}

# Reverse mapping: BarChart vendor root → internal root
UST_FUTURE_BARCHART_TO_INTERNAL: Dict[str, str] = {
    "ZT": "TU",
    "ZF": "FV",
    "ZN": "TY",
    "ZB": "US",
    "UB": "WN",
    "TN": "UXY",
}


def normalize_root(root: str) -> str:
    key = (root or "").strip().upper()
    if key in UST_FUTURE_ROOTS:
        return UST_FUTURE_ROOTS[key]
    if key in UST_FUTURE_BARCHART_ROOTS:
        return key
    raise KeyError(f"Unsupported UST future root: {root}")


def to_barchart_root(root: str) -> str:
    norm = normalize_root(root)
    return UST_FUTURE_BARCHART_ROOTS.get(norm, norm)


def build_contract_symbol(root: str, month_code: str) -> str:
    return f"{normalize_root(root)}{month_code}"


def front_month(as_of: datetime.date, root: str) -> str:
    norm = normalize_root(root)
    contracts = _next_contracts(
        start_date=as_of,
        prefix=norm,
        count=1,
        valid_months=UST_FUTURE_VALID_MONTHS,
        cutoff_fn=_imm_cutoff,
    )
    return contracts[0]


def back_months(as_of: datetime.date, root: str, count: int) -> List[str]:
    if count < 0:
        raise ValueError("count must be non-negative")
    norm = normalize_root(root)
    contracts = _next_contracts(
        start_date=as_of,
        prefix=norm,
        count=count + 1,
        valid_months=UST_FUTURE_VALID_MONTHS,
        cutoff_fn=_imm_cutoff,
    )
    return contracts[1 : count + 1]


def month_code_to_month(month_code: str) -> int:
    code = (month_code or "").strip().upper()
    if code not in CME_MONTH_CODE:
        raise KeyError(f"Unknown CME month code: {month_code}")
    return CME_MONTH_CODE[code]
