import datetime
import pandas as pd
from typing import Optional, Tuple, Dict, List

import rateslib as rl

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_sofr_mt_builder import rl_usd_sofr_mt_builder
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_sofr_mt_builder_parallel import rl_usd_sofr_mt_builder_parallel
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache, _make_key

_N_SER_CONTRACTS = 0
_N_SFR_CONTRACTS = 12
_N_PLUS_FOMC_YRS = 3


def rl_usd_sofr_mt_curve(
    curve_id: str,
    snap: datetime.datetime,
    sofr_fixings: pd.Series,
    cache: _RLCurveCache,
    force_refresh: Optional[bool] = False,
) -> Tuple[datetime.datetime, rl.Curve]:
    if cache is not None:
        return snap, rl.from_json(
            cache.get_rl_usd_sofr_mt(
                curve_id=curve_id,
                snap=snap,
                sofr_fixings=sofr_fixings,
                n_ser=_N_SER_CONTRACTS,
                n_sfr=_N_SFR_CONTRACTS,
                n_plus_fomc_years=_N_PLUS_FOMC_YRS,
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
    )
    return rlcurveobj.timestamp, rlcurveobj.rl_pricing_curve


def rl_usd_sofr_mt_curve_bulk(
    base_curve_id: str,
    snaps: List[datetime.datetime],
    sofr_fixings: pd.Series,
    cache: _RLCurveCache,
    max_workers: int,
    force_refresh: Optional[bool] = False,
) -> Dict[datetime.datetime, rl.Curve]:
    if cache is None:
        return rl_usd_sofr_mt_builder_parallel(
            curve_id=curve_id,
            snaps=snaps,
            sofr_fixings=sofr_fixings,
            n_ser_contracts=_N_SER_CONTRACTS,
            n_sfr_contracts=_N_SFR_CONTRACTS,
            n_plus_fomc_years=_N_PLUS_FOMC_YRS,
            max_workers=max_workers,
        )

    cached_curves: Dict[datetime.datetime, rl.Curve] = {}
    snaps_to_build: List[datetime.datetime] = []

    mapping = getattr(cache, cache._cache_attr)

    for snap in snaps:
        key = _make_key(f"{snap}-SDR_INTRADAY-RL_USD_SOFR_MT_Q12", snap, sofr_fixings, _N_SER_CONTRACTS, _N_SFR_CONTRACTS, _N_PLUS_FOMC_YRS)
        if not force_refresh and key in mapping:
            cached_curves[snap] = rl.from_json(mapping[key])
        else:
            snaps_to_build.append(snap)

    if snaps_to_build:
        newly_built_curves = rl_usd_sofr_mt_builder_parallel(
            base_curve_id=base_curve_id,
            snaps=snaps_to_build,
            sofr_fixings=sofr_fixings,
            n_ser_contracts=_N_SER_CONTRACTS,
            n_sfr_contracts=_N_SFR_CONTRACTS,
            n_plus_fomc_years=_N_PLUS_FOMC_YRS,
            max_workers=max_workers,
            use_globex=False,
        )

        with cache.batched():
            for snap, curve in newly_built_curves.items():
                key = _make_key(f"{snap}-SDR_INTRADAY-RL_USD_SOFR_MT_Q12", snap, sofr_fixings, _N_SER_CONTRACTS, _N_SFR_CONTRACTS, _N_PLUS_FOMC_YRS)
                mapping[key] = curve.to_json()

        cached_curves.update(newly_built_curves)

    return cached_curves
