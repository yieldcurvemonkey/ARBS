"""Citi Velocity intraday USD SOFR OIS par-curve → rateslib discount curve.

This package turns the Citi Velocity ``CVTSHIST`` intraday export
(``RATES.OIS.USD_SOFR.PAR.<tenor>`` par swap rates sampled at 1-minute
granularity) into fully-calibrated rateslib :class:`~rateslib.curves.Curve`
discount curves, following the IRSwaps RL (rateslib) curve-building patterns
used elsewhere in the repo (see
``MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/rl_usd_sofr_mt_builder.py`` and
``ErisFuturesFetcher.fetch_intraday_discount_curve``).

Public surface
--------------
- :func:`~MDP.IRSwaps.CITI_VELOCITY_INTRADAY.citi_velocity_loader.load_intraday_par_rates`
- :class:`~MDP.IRSwaps.CITI_VELOCITY_INTRADAY.citi_velocity_loader.CitiVelocityWorkbook`
- :func:`~MDP.IRSwaps.CITI_VELOCITY_INTRADAY.rl_usd_sofr_intraday_builder.build_rl_usd_sofr_intraday_curve`
- :class:`~MDP.IRSwaps.CITI_VELOCITY_INTRADAY.CitiVelocityIntradayFetcher.CitiVelocityIntradayFetcher`
"""

from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.citi_velocity_loader import (
    CitiVelocityWorkbook,
    CURVE_TENOR_ORDER,
    load_intraday_par_rates,
    parse_period_from_sheet_name,
    parse_tenor_from_header,
)
from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.rl_usd_sofr_intraday_builder import (
    build_rl_usd_sofr_intraday_curve,
)
from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.CitiVelocityIntradayFetcher import (
    CitiVelocityIntradayFetcher,
    DEFAULT_DB_PATH,
)

__all__ = [
    "CitiVelocityWorkbook",
    "CURVE_TENOR_ORDER",
    "load_intraday_par_rates",
    "parse_period_from_sheet_name",
    "parse_tenor_from_header",
    "build_rl_usd_sofr_intraday_curve",
    "CitiVelocityIntradayFetcher",
    "DEFAULT_DB_PATH",
]
