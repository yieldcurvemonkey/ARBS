import datetime
import pandas as pd  # Keep for compatibility
import polars as pl
from typing import Optional, Tuple

import rateslib as rl

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_sofr_mt_builder import rl_usd_sofr_mt_builder
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

_N_SER_CONTRACTS = 11
_N_SFR_CONTRACTS = 12
_N_PLUS_FOMC_YRS = 1
# _MT_TENORS = ["5Y", "10Y", "30Y"]
_MT_TENORS = ["5Y", "7Y", "10Y", "20Y", "30Y"]
_MT_TENOR_MAX = f"{max([int(t[:-1]) for t in _MT_TENORS])}Y"
_EXTRAPOLATION_YRS = 30


def rl_usd_sofr_mt_curve(
    curve_id: str,
    snap: datetime.datetime,
    sofr_fixings: pd.Series,
    cache: _RLCurveCache,
    force_refresh: Optional[bool] = False,
) -> Tuple[datetime.datetime, rl.Curve]:
    print("_N_SER_CONTRACTS: ", _N_SER_CONTRACTS)
    print("_N_SFR_CONTRACTS: ", _N_SFR_CONTRACTS)
    print("_N_PLUS_FOMC_YRS: ", _N_PLUS_FOMC_YRS)
    print("_MT_TENORS: ", _MT_TENORS)
    print("_MT_TENOR_MAX: ", _MT_TENOR_MAX)
    print("_EXTRAPOLATION_YRS: ", _EXTRAPOLATION_YRS)

    if cache is not None:
        return snap, rl.from_json(
            cache.get_rl_usd_sofr_mt(
                curve_id=curve_id,
                snap=snap,
                sofr_fixings=sofr_fixings,
                n_ser=_N_SER_CONTRACTS,
                n_sfr=_N_SFR_CONTRACTS,
                n_plus_fomc_years=_N_PLUS_FOMC_YRS,
                medium_term_tenors=_MT_TENORS,
                max_tenor=_MT_TENOR_MAX,
                extrapolation_yrs=_EXTRAPOLATION_YRS,
                force_refresh=force_refresh,
            )
        )

    rlcurveobj = rl_usd_sofr_mt_builder(
        curve_id=curve_id,
        snap=snap,
        sofr_fixings=sofr_fixings,
        n_ser_contracts=_N_SER_CONTRACTS,
        n_sfr_contracts=_N_SFR_CONTRACTS,
        n_plus_fomc_years=_N_PLUS_FOMC_YRS,
        medium_term_tenors=_MT_TENORS,
        max_tenor=_MT_TENOR_MAX,
        extrapolation_yrs=_EXTRAPOLATION_YRS,
    )
    return rlcurveobj.timestamp, rlcurveobj.rl_pricing_curve
