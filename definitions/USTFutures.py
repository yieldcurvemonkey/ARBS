from __future__ import annotations

import datetime
import logging
import math
from typing import Dict, List, Sequence, Tuple

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import CME_MONTH_CODE, _imm_cutoff, _next_contracts

_LOGGER = logging.getLogger(__name__)

UST_FUTURE_ROOTS: Dict[str, str] = {
    "2Y": "TU",
    "5Y": "FV",
    "10Y": "TY",
    "30Y": "US",
    "ULTRA": "WN",
    "ULTRA10Y": "UXY",
}

# BarChart vendor root per internal root.
#
# NOTE ON "WN" -> "UD": BarChart's root for the CBOT Ultra U.S. Treasury Bond is **UD**
# (https://www.barchart.com/futures/quotes/UD*0 -> "Ultra 30-Year Treasury-Bond", CBOT).
# BarChart's "UB" is the CME **Euro/Krone (EUR/NOK) FX future**
# (https://www.barchart.com/futures/quotes/UBU26 -> "Euro/Krone Sep '26", EUR 125,000).
# This map previously said "UB", so every Ultra Bond price this repo has ever served was an
# FX rate. Measured 2026-08-14 over 2018/2020/2024/2026 windows:
#     UDU18 155.1-160.1 (vol 11,992) vs UBU18 9.46-9.54 (vol 4);  ZBU18 142.1-145.4
#     UDZ20 212.8-222.7 (vol 18,350) vs UBZ20 10.85-11.08 (vol 2)
#     UDM24 118.8-127.3 (vol 43,087) vs UBM24 11.59-11.85 (vol 6)
#     UDU26 109.8-111.7 (vol 54,285) vs UBU26 10.94-11.04 (vol 6); Yahoo UB=F 110.41
# UD lands 100% on the contract's 1/32 tick grid; UB lands on it ~5% of the time (i.e. by chance).
UST_FUTURE_BARCHART_ROOTS: Dict[str, str] = {
    "TU": "ZT",
    "FV": "ZF",
    "TY": "ZN",
    "US": "ZB",
    "WN": "UD",
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
    "UD": "WN",
    "TN": "UXY",
}

# Exchange / vendor spellings that callers reasonably type, mapped to the internal root.
# "UB" is the CME **Globex** code for the Ultra Bond, so callers do type it even though it is
# also BarChart's EUR/NOK root -- accept it on the way in, but never emit it on the way out.
UST_FUTURE_ROOT_ALIASES: Dict[str, str] = {
    "UB": "WN",
    "UD": "WN",
    "WN": "WN",
    "ZB": "US",
    "ZN": "TY",
    "ZF": "FV",
    "ZT": "TU",
    "TN": "UXY",
}

# A UST future price is quoted in points of par. Anything outside this band is not a Treasury
# futures price at all -- it is a different instrument, a rate, or a unit error. The band is
# deliberately wide (the Ultra Bond reached ~223 at the 2020 yield lows and the 2y sits ~102):
# it exists to catch a WRONG-INSTRUMENT feed, not to police normal market moves.
UST_FUTURE_PLAUSIBLE_PRICE_BAND: Tuple[float, float] = (50.0, 300.0)


def normalize_root(root: str) -> str:
    key = (root or "").strip().upper()
    if key in UST_FUTURE_ROOTS:
        return UST_FUTURE_ROOTS[key]
    if key in UST_FUTURE_BARCHART_ROOTS:
        return key
    if key in UST_FUTURE_ROOT_ALIASES:
        return UST_FUTURE_ROOT_ALIASES[key]
    raise KeyError(f"Unsupported UST future root: {root}")


def to_barchart_root(root: str) -> str:
    norm = normalize_root(root)
    return UST_FUTURE_BARCHART_ROOTS.get(norm, norm)


def is_plausible_ust_future_price(price: float) -> bool:
    """Could this number be a US Treasury futures price at all?

    This is a wrong-instrument detector, not a market-move filter. See
    ``UST_FUTURE_PLAUSIBLE_PRICE_BAND``.
    """
    value = float(price)
    lo, hi = UST_FUTURE_PLAUSIBLE_PRICE_BAND
    return math.isfinite(value) and lo <= value <= hi


def normalize_barchart_ust_future_price(symbol: str, price: float) -> float:
    """Validate a vendor-supplied UST futures price; return NaN if it cannot be one.

    BarChart serves UST futures as plain decimal points of par (e.g. ZBU26 -> 109.46875), so
    there is nothing to decode. What there IS to do is refuse a number that cannot be a Treasury
    futures price, because the failure this guards against is a *symbol* pointing at a different
    instrument entirely.

    History: this function used to reinterpret any sub-100 "UB" quote as a compact
    handle-and-32nds quote (``100 + whole + frac*100/32``). That rule was written to explain
    values around 11 coming back for the Ultra Bond. Those values were real -- they were the
    EUR/NOK exchange rate, because the vendor root map pointed "WN" at BarChart's "UB" (Euro/Krone)
    instead of "UD" (Ultra 30-Year Treasury-Bond). The decoder turned an obviously-wrong number
    (11.13) into a plausible-looking one (111.40625) and so hid the mapping bug for months.
    Returning NaN keeps a bad feed *absent* rather than *plausible*.
    """
    value = float(price)
    if is_plausible_ust_future_price(value):
        return value
    _LOGGER.warning(
        "Rejected implausible UST future price for %s: %r is outside %s -- this usually means the "
        "vendor symbol resolves to a different instrument.",
        symbol,
        value,
        UST_FUTURE_PLAUSIBLE_PRICE_BAND,
    )
    return float("nan")


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
