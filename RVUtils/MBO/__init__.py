"""SR3 market-by-order exploration: the full CME order book, not settles.

Every SR3 relative-value study in this repo prices structures off settles and
charges a per-contract cost taken on faith.  A GLBX MDP3 MBO file carries the
quoted book itself, including the book of the exchange-listed butterflies --
where a fly is one instrument with one bid and one ask rather than three
outrights crossed separately.  That makes the cost assumption measurable.

See ``docs/superpowers/specs/2026-08-07-sr3-mbo-explorer-design.md``.

Modules
-------
``symbols``  CME SR3 symbology -> kind, legs, exchange leg weights.
``source``   DBN file -> activity catalogue and a per-instrument parquet cache.
``book``     JIT L3 replay -> top-of-book stream and depth ladders.
``metrics``  quoted / effective / realised spread, depth, imbalance, cost.
``implied``  leg-implied structure book vs the listed instrument's own book.
``plots``    charts, on the validated palette.
"""
from RVUtils.MBO.book import (
    F_LAST,
    F_SNAPSHOT,
    PRICE_SCALE,
    PriceGrid,
    ReplayResult,
    build_price_grid,
    replay_book,
)
from RVUtils.MBO.implied import ImpliedComparison, compare_listed_vs_implied, implied_structure_book
from RVUtils.MBO.metrics import (
    IMM_TICK_VALUE_USD,
    cost_summary,
    depth_profile,
    effective_spread,
    intraday_profile,
    order_flow_imbalance,
    quoted_spread_summary,
    resample_tob,
    trade_ohlcv,
)
from RVUtils.MBO.source import (
    MboSource,
    activity_catalogue,
    instrument_records,
    scan_activity,
)
from RVUtils.MBO.symbols import (
    KINDS_QUOTED_IN_BP,
    USD_PER_BP_PER_CONTRACT,
    ParsedSymbol,
    bp_per_price_unit,
    parse_symbol,
    parse_symbols,
)

__all__ = [
    "F_LAST", "F_SNAPSHOT", "IMM_TICK_VALUE_USD", "KINDS_QUOTED_IN_BP",
    "PRICE_SCALE", "USD_PER_BP_PER_CONTRACT",
    "ImpliedComparison", "MboSource", "ParsedSymbol", "PriceGrid", "ReplayResult",
    "activity_catalogue", "bp_per_price_unit", "build_price_grid",
    "compare_listed_vs_implied", "cost_summary", "depth_profile",
    "effective_spread", "implied_structure_book", "instrument_records",
    "intraday_profile", "order_flow_imbalance", "parse_symbol", "parse_symbols",
    "quoted_spread_summary", "replay_book", "resample_tob", "scan_activity",
    "trade_ohlcv",
]
