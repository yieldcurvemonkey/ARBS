import datetime
import pandas as pd  # Keep for compatibility
import polars as pl
from typing import Optional, Tuple

import rateslib as rl

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_curve_stir_builder import rl_usd_sofr_stir_builder 
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache 

_N_SER_CONTRACTS = 12
_N_SFR_CONTRACTS = 12
_N_PLUS_FOMC_YRS = 2


def rl_usd_sofr_stir_curve(
    curve_id: str,
    snap: datetime.datetime,
    sofr_fixings: pd.Series,
    cache: _RLCurveCache,
    force_refresh: Optional[bool] = False,
) -> Tuple[datetime.datetime, rl.Curve]:
    if cache is not None:
        return snap, rl.from_json(
            cache.get_rl_usd_sofr_stir(
                curve_id=curve_id,
                snap=snap,
                sofr_fixings=sofr_fixings,
                n_ser=_N_SER_CONTRACTS,
                n_sfr=_N_SFR_CONTRACTS,
                n_plus_fomc_years=_N_PLUS_FOMC_YRS,
                force_refresh=force_refresh,
            )
        )

    rlcurveobj = rl_usd_sofr_stir_builder(
        curve_id=curve_id,
        snap=snap,
        sofr_fixings=sofr_fixings,
        n_ser_contracts=_N_SER_CONTRACTS,
        n_sfr_contracts=_N_SFR_CONTRACTS,
        n_plus_fomc_years=_N_PLUS_FOMC_YRS,
    )
    return rlcurveobj.timestamp, rlcurveobj.rl_pricing_curve
