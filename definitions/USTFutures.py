from __future__ import annotations

import datetime
import logging
import math
from typing import Dict, List, Sequence, Tuple

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
    sunday_to_monday,
)
from pandas.tseries.offsets import CustomBusinessDay

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import CME_MONTH_CODE, _monthly_cutoff, _next_contracts

_LOGGER = logging.getLogger(__name__)

UST_FUTURE_ROOTS: Dict[str, str] = {
    "2Y": "TU",
    "3Y": "Z3N",
    "20Y": "TWE",
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
#
# Z3N -> "ZE" and TWE -> "ZZ" are the second and third instances of the same namespace split, and
# were verified the same way rather than guessed. Measured 2026-08-15 over 2020-2026 EOD history:
#     ZEM22 106.52-115.53 (max vol 31,176), ZEU26 104.06-107.13 (9,690) -- 100% in the 50-300 band
#                                                                       and 100% on the 1/256 grid
#     ZZM22 136.34-175.63 (1,896), ZZU26 constant 125.50 (max vol 0)    -- 100% in band, 100% on 1/32
#     UBU26 10.81-12.45 (398)      -- 0% in band, 2.8% on tick: the EUR/NOK future, as recorded
#     TBU26 96.03-97.19 (4,921)    -- 100% IN BAND but 4.3% on tick, i.e. a candidate the price band
#                                     alone would have admitted. The tick grid is the discriminator.
# ZZ's 20-Year contract is listed but effectively untraded from 2024: ZZU26 prints a flat 125.50
# with zero volume. The root is correct; a TWE panel is not buildable from it.
UST_FUTURE_BARCHART_ROOTS: Dict[str, str] = {
    "TU": "ZT",
    "FV": "ZF",
    "TY": "ZN",
    "US": "ZB",
    "WN": "UD",
    "UXY": "TN",
    "Z3N": "ZE",
    "TWE": "ZZ",
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
    "ZE": "Z3N",
    "ZZ": "TWE",
}

# CME **Globex** root per internal root. This is a DIFFERENT namespace from the BarChart map
# above, and the two agree for every root except the Ultra Bond: Globex calls it UB, BarChart calls
# it UD (BarChart's UB is Euro/Krone). Broker feeds that speak Globex -- Schwab / thinkorswim, which
# quote /ZN, /ZB, /UB -- must use THIS map. Conflating the two namespaces is what produced the
# Ultra Bond defect in the first place, so they are kept separate rather than merged.
UST_FUTURE_GLOBEX_ROOTS: Dict[str, str] = {
    "TU": "ZT",
    "FV": "ZF",
    "TY": "ZN",
    "US": "ZB",
    "WN": "UB",
    "UXY": "TN",
    # Globex keeps its own spellings for these two; BarChart calls them ZE and ZZ.
    "Z3N": "Z3N",
    "TWE": "TWE",
}

# Exchange / vendor spellings that callers reasonably type, mapped to the internal root.
# "UB" is the CME **Globex** code for the Ultra Bond, so callers do type it even though it is
# also BarChart's EUR/NOK root -- accept it on the way in, but never emit it on the way out.
UST_FUTURE_ROOT_ALIASES: Dict[str, str] = {
    "ZE": "Z3N",
    "Z3N": "Z3N",
    "ZZ": "TWE",
    "TWE": "TWE",
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


def to_globex_root(root: str) -> str:
    """CME Globex root -- for broker feeds, NOT for BarChart. See UST_FUTURE_GLOBEX_ROOTS."""
    norm = normalize_root(root)
    return UST_FUTURE_GLOBEX_ROOTS.get(norm, norm)


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


class CMEInterestRateCalendar(AbstractHolidayCalendar):
    """CBOT/CME interest-rate trading holidays.

    Not the federal calendar, and the difference is not cosmetic. CME closes on **Good Friday**,
    which the federal calendar has no rule for, and CME **trades** on Columbus Day and Veterans Day,
    which the federal calendar closes. New Year is ``sunday_to_monday``, not ``nearest_workday``:
    when 1 January falls on a Saturday the exchange trades 31 December (it did in 2021).

    Verified against the last bar BarChart holds for every expired contract, 6 roots x 2018-2025:
    **192/192 exact**. The same code on ``pandas.USFederalHolidayCalendar`` scores **174/192** -- so
    the check discriminates, and these three rules are exactly the 18 contracts it gets wrong
    (``ZNH18``/``ZBH18``/``UDH18``/``TNH18`` and the ``ZTH18``/``ZFH18`` pair on Good Friday 2018;
    ``*Z21`` on the 2021 New Year; ``*H24`` on Good Friday 2024).

    Known limitation, not currently load-bearing: CME has opened on Good Friday when it collided
    with the payrolls release (2023-04-07, 2026-04-03). Neither lands in a last-trading-day window.
    """

    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date=pd.Timestamp("2022-06-19"), observance=nearest_workday),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


_CME_BD = CustomBusinessDay(calendar=CMEInterestRateCalendar())

# Business days between the last trading day and the last business day of the delivery month.
# The short end trades through the whole delivery month; the long end stops seven business days
# early so the short has time to declare intention.
UST_FUTURE_LAST_TRADE_BD_BEFORE_MONTH_END: Dict[str, int] = {
    "TU": 0,
    "Z3N": 0,
    "FV": 0,
    "TY": 7,
    "UXY": 7,
    "US": 7,
    "WN": 7,
    "TWE": 7,
}

#: First position (intention) day: two business days before the first business day of the delivery
#: month. This is the roll the market uses -- see ``ust_front_month``.
_UST_POSITION_DAY_BD_BEFORE_MONTH_START = 2


def _last_business_day_of_month(year: int, month: int) -> datetime.date:
    stamp = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    if not _CME_BD.is_on_offset(stamp):
        stamp = stamp - _CME_BD
    return stamp.date()


def _first_business_day_of_month(year: int, month: int) -> datetime.date:
    stamp = pd.Timestamp(year=year, month=month, day=1)
    if not _CME_BD.is_on_offset(stamp):
        stamp = stamp + _CME_BD
    return stamp.date()


def ust_last_trading_day(root: str, year: int, month: int) -> datetime.date:
    """Last trading day of the ``root`` contract delivering in ``year``/``month``.

    TU/Z3N/FV trade to the last business day of the delivery month; TY/UXY/US/WN/TWE stop seven
    business days before it. Validated against observed final bars, 192/192 (see
    :class:`CMEInterestRateCalendar`).
    """
    key = (root or "").strip().upper()
    offset = UST_FUTURE_LAST_TRADE_BD_BEFORE_MONTH_END.get(key)
    if offset is None:
        offset = UST_FUTURE_LAST_TRADE_BD_BEFORE_MONTH_END[normalize_root(key)]
    last_bd = pd.Timestamp(_last_business_day_of_month(year, month))
    return (last_bd - offset * _CME_BD).date() if offset else last_bd.date()


def ust_first_position_day(year: int, month: int) -> datetime.date:
    """First position (intention) day: two business days before the delivery month's first bd."""
    first_bd = pd.Timestamp(_first_business_day_of_month(year, month))
    return (first_bd - _UST_POSITION_DAY_BD_BEFORE_MONTH_START * _CME_BD).date()


def _ust_position_day_cutoff(year: int, month: int) -> datetime.date:
    if month in UST_FUTURE_VALID_MONTHS:
        return ust_first_position_day(year, month)
    return _monthly_cutoff(year, month)


def _ust_last_trade_cutoff_for(root: str):
    def _cutoff(year: int, month: int) -> datetime.date:
        if month in UST_FUTURE_VALID_MONTHS:
            # `_next_contracts` skips a month when as_of >= cutoff, so the cutoff is the first day
            # the contract is no longer tradeable: the day after its last trading day.
            return ust_last_trading_day(root, year, month) + datetime.timedelta(days=1)
        return _monthly_cutoff(year, month)

    return _cutoff


def build_contract_symbol(root: str, month_code: str) -> str:
    return f"{normalize_root(root)}{month_code}"


def front_month(as_of: datetime.date, root: str) -> str:
    """The contract the MARKET is trading -- rolled on the first position day.

    This used to roll on the IMM date (third Wednesday), which is a Eurodollar/SOFR convention with
    no meaning for a Treasury future. The handover's suspicion was that it therefore named expired
    contracts; measured over 2,168 CME business days and 2018-2026, it **never** does -- the IMM
    date always falls before the last trading day. The real defect is the opposite one: it holds
    the expiring contract a median **16 business days** past the liquidity roll.

    Measured against the contract actually carrying the most open interest, 2018-2026:

    ==========================  ==========  ==========  ==========
    rule                        TY          TU          WN
    ==========================  ==========  ==========  ==========
    IMM (previous)              25.3% wrong 25.4% wrong 26.9% wrong
    last trading day            28.8% wrong 39.9% wrong 29.4% wrong
    **first position day**      **3.7%**    **3.8%**    **4.4%**
    ==========================  ==========  ==========  ==========

    On the days the IMM rule was wrong, the contract it named held a **median 0.8-1.2%** of the
    liquid contract's open interest, and was under 10% of it on 88% of them -- roughly 56-60 days a
    year, per root, of quoting a contract nobody trades. The price was never garbage, which is
    exactly why this was invisible.

    Rolling at the last trading day -- the obvious "fix" -- is measurably WORSE than the status quo
    for quoting, most of all for TU (100.5 days a year wrong vs 9.5). Delivery-side callers do not
    need it: they all pass an explicit contract symbol. Use :func:`ust_deliverable_contract` when
    the question really is "what can still be delivered".
    """
    norm = normalize_root(root)
    contracts = _next_contracts(
        start_date=as_of,
        prefix=norm,
        count=1,
        valid_months=UST_FUTURE_VALID_MONTHS,
        cutoff_fn=_ust_position_day_cutoff,
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
        cutoff_fn=_ust_position_day_cutoff,
    )
    return contracts[1 : count + 1]


def ust_deliverable_contract(as_of: datetime.date, root: str) -> str:
    """The nearest contract still TRADEABLE on ``as_of`` -- rolled after its last trading day.

    Deliberately separate from :func:`front_month`. The two answer different questions and the
    answers differ on 3.6% (TY) to 14.5% (TU) of days; collapsing them into one function is how the
    IMM rule ended up serving both. Nothing calls this today; it exists so the next person asking
    "is this contract still alive" does not reach for ``front_month``.
    """
    norm = normalize_root(root)
    contracts = _next_contracts(
        start_date=as_of,
        prefix=norm,
        count=1,
        valid_months=UST_FUTURE_VALID_MONTHS,
        cutoff_fn=_ust_last_trade_cutoff_for(norm),
    )
    return contracts[0]


def month_code_to_month(month_code: str) -> int:
    code = (month_code or "").strip().upper()
    if code not in CME_MONTH_CODE:
        raise KeyError(f"Unknown CME month code: {month_code}")
    return CME_MONTH_CODE[code]
