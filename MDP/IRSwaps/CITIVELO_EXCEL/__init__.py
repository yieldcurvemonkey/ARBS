r"""Citi Velocity swap curves as an ``IRSwapsMDP`` source, for all 20 currencies.

Source token: **``CITIVELO_EXCEL``** (``-RL`` / ``-QL`` select the backend). It is
deliberately NOT ``CITIVELO`` / ``CITI_VELO`` / ``CITIVELOCITY``: those name the
older workbook-based USD-SOFR-only source, which ~930 warmed CurveStore partitions
and the dealer-ladder study depend on, and which this package does not touch.

Three time modes, one primitive::

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL-RL")
    mdp.get_data({"curve_name": "GBP-SONIA-1D", "timestamp": "live"})
    mdp.get_data({"curve_name": "GBP-SONIA-1D", "timestamp": date(2026, 8, 5)})
    mdp.get_data({"curve_name": "GBP-SONIA-1D",
                  "timestamp": datetime(2026, 8, 6, 10, 30,
                                        tzinfo=ZoneInfo("America/New_York"))})

Read :mod:`~MDP.IRSwaps.CITIVELO_EXCEL.timestamps` before using the intraday mode:
Citi's stamps are America/New_York wall clock, that was measured rather than
assumed, and a naive datetime is localised (with a warning) rather than rejected.
"""

from __future__ import annotations

from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import (
    CITIVELO_EXCEL_CURVES,
    CITI_INDEX_BY_CURVE_NAME,
    CURVE_NAME_BY_CITI_INDEX,
    CurveNameEntry,
    citi_index_for_curve_name,
    curve_name_for_index,
    entry_for_curve_name,
    is_citivelo_excel_curve,
    supported_curve_names,
)
from MDP.IRSwaps.CITIVELO_EXCEL.curve_definitions import register
from MDP.IRSwaps.CITIVELO_EXCEL.fetcher import (
    CitiVeloExcelCurveFetcher,
    CurveSnapshot,
    SparseCurveError,
    StaleCurveError,
)
from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import (
    MAX_SPOT_START_LAG,
    SpotStartRequiredError,
    SwapSpreadQuote,
    SwapSpreadUnavailableError,
    fetch_swap_spread,
    fetch_swap_spreads,
    indices_with_swap_spread,
    swap_spread_for_curve,
    swap_spread_history,
    swap_spread_tag,
    swap_spread_tenors,
)
from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import (
    DEFAULT_WIRE_TZ,
    NaiveTimestampError,
    ResolvedRequest,
    from_wire_naive,
    resolve_request,
    to_wire_naive,
    wire_timezone,
)

#: Source tokens ``IRSwapsMDP`` accepts for this source. The bare token defaults
#: to the rateslib backend, matching every other ``-RL``/``-QL`` pair in the repo.
SOURCE_TOKENS_RL = ("CITIVELO_EXCEL", "CITIVELO-EXCEL", "CITIVELO_EXCEL-RL", "CITIVELO_EXCEL_RL")
SOURCE_TOKENS_QL = ("CITIVELO_EXCEL-QL", "CITIVELO_EXCEL_QL")
SOURCE_TOKENS = SOURCE_TOKENS_RL + SOURCE_TOKENS_QL

__all__ = [
    "CITIVELO_EXCEL_CURVES",
    "CITI_INDEX_BY_CURVE_NAME",
    "CURVE_NAME_BY_CITI_INDEX",
    "CitiVeloExcelCurveFetcher",
    "CurveNameEntry",
    "CurveSnapshot",
    "DEFAULT_WIRE_TZ",
    "MAX_SPOT_START_LAG",
    "NaiveTimestampError",
    "ResolvedRequest",
    "SOURCE_TOKENS",
    "SOURCE_TOKENS_QL",
    "SOURCE_TOKENS_RL",
    "SparseCurveError",
    "SpotStartRequiredError",
    "StaleCurveError",
    "SwapSpreadQuote",
    "SwapSpreadUnavailableError",
    "citi_index_for_curve_name",
    "curve_name_for_index",
    "entry_for_curve_name",
    "fetch_swap_spread",
    "fetch_swap_spreads",
    "from_wire_naive",
    "indices_with_swap_spread",
    "is_citivelo_excel_curve",
    "register",
    "resolve_request",
    "supported_curve_names",
    "swap_spread_for_curve",
    "swap_spread_history",
    "swap_spread_tag",
    "swap_spread_tenors",
    "to_wire_naive",
    "wire_timezone",
]
