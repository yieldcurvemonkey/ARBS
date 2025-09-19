import datetime
import os
import re
from typing import Dict, List, Literal, Optional, Tuple, Union

import pandas as pd
import pytz
import rateslib as rl

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import get_quotes
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import (
    RLCurveSTIR,
    build_rl_fomc_turn_flies,
    build_rl_stirf,
    fetch_historical_usd_stir_curve_instruments_snapshot_barchart,
    get_fomc_meetings_list,
    get_short_end_curve_tickers,
)


def rl_usd_sofr_stir_builder(
    *,
    curve_id: str,
    snap: Union[datetime.datetime, datetime.date, List[Union[datetime.datetime, datetime.date]]],
    sofr_fixings: pd.Series,
    n_ser_contracts: int,
    n_sfr_contracts: int,
    n_plus_fomc_years: int,
    live_side: Literal["bid", "mid", "ask"] = "mid",
    use_globex: Optional[bool] = False,
    schwab_app_key: Optional[str] = None,
    schwab_app_secret: Optional[str] = None,
) -> RLCurveSTIR:
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning)

    def _safe_fixed_rate(f):
        try:
            return f._fixed_rate.iloc[-1]
        except Exception:
            return f._fixed_rate

    def _fetch_stir_market_data(
        curve_id_local: str,
        snap_local: Union[datetime.datetime, datetime.date, List[Union[datetime.datetime, datetime.date]], str],
        fixings: pd.Series,
        side: Literal["bid", "mid", "ask"],
        include_serff: bool,
    ) -> Tuple[Union[datetime.datetime, datetime.date], Dict[str, rl.STIRFuture], Dict[str, float]]:
        ff = "/ZQ" if use_globex else "FF"
        ser = "/SR1" if use_globex else "SER"

        if snap_local == "live":
            symbols = get_short_end_curve_tickers(
                as_of=datetime.date.today(),
                first_n_sr1=n_ser_contracts,
                first_n_sr3=n_sfr_contracts,
                include_serff=include_serff,
                use_globex=True,
            )
            first_sfr = next((s for s in symbols if "SR3" in s), None)

            quotes = get_quotes(
                symbols=symbols,
                app_key=schwab_app_key or os.environ["SCHWABDEV_APP_KEY"],
                app_secret=schwab_app_secret or os.environ["SCHWABDEV_APP_SECRET"],
            )
            curve_timestamp = datetime.datetime.fromtimestamp(quotes[first_sfr]["quoteTime"] / 1000).astimezone(pytz.timezone("US/Central"))

            # rename to non-Globex if requested
            if not use_globex:
                _subs = {"/SR3": "SFR", "/SR1": "SER", "/ZQ": "FF"}
                _pat = re.compile("|".join(map(re.escape, _subs)))

                def rename(sym: str) -> str:
                    return _pat.sub(lambda m: _subs[m.group(0)], sym)

                quotes = {rename(k): v for k, v in quotes.items()}

            rl_stirfs: Dict[str, rl.STIRFuture] = {}
            serff_basis: Dict[str, float] = {}
            for t, q in quotes.items():
                if ff in t:
                    curr_contract = str(t).replace(ff, "")
                    if curr_contract not in serff_basis:
                        serff_basis[curr_contract] = quotes[f"{ser}{curr_contract}"][side] - quotes[f"{ff}{curr_contract}"][side]
                else:
                    obj_t, obj_stirf = build_rl_stirf(ticker=t, curve_id=curve_id_local, price=q[side], fixings=fixings, use_globex=use_globex)
                    rl_stirfs[obj_t] = obj_stirf
        else:
            # historical snapshot(s)
            dt_for = snap_local if isinstance(snap_local, (datetime.datetime, datetime.date)) else snap_local[0]
            stir_df = fetch_historical_usd_stir_curve_instruments_snapshot_barchart(
                snap=dt_for,
                tickers=get_short_end_curve_tickers(
                    as_of=dt_for if isinstance(dt_for, datetime.date) else dt_for.date(),
                    first_n_sr1=n_ser_contracts,
                    first_n_sr3=n_sfr_contracts,
                    include_serff=include_serff,
                    use_globex=use_globex,
                ),
                use_globex=use_globex,
            )
            curve_timestamp = stir_df.index[0]
            rl_stirfs = {}
            serff_basis = {}
            ff = "/ZQ" if use_globex else "FF"
            ser = "/SR1" if use_globex else "SER"
            for t, q in stir_df.T.iterrows():
                if ff in t:
                    curr_contract = str(t).replace(ff, "")
                    if curr_contract not in serff_basis:
                        serff_basis[curr_contract] = stir_df[f"{ser}{curr_contract}"].iloc[-1] - stir_df[f"{ff}{curr_contract}"].iloc[-1]
                else:
                    obj_t, obj_stirf = build_rl_stirf(ticker=t, curve_id=curve_id_local, price=q, fixings=fixings, use_globex=use_globex)
                    rl_stirfs[obj_t] = obj_stirf

        return curve_timestamp, rl_stirfs, serff_basis

    if isinstance(snap, list):
        _as_of = snap[0] if isinstance(snap[0], (datetime.datetime, datetime.date)) else datetime.date.today()
    else:
        _as_of = snap

    # ensure a plain date for “as_of”
    if isinstance(_as_of, datetime.datetime):
        _as_of_date = _as_of.date()
    elif isinstance(_as_of, datetime.date):
        _as_of_date = _as_of
    else:
        raise ValueError("Unsupported snap type")

    curve_timestamp, rl_stirfs, serff_basis = _fetch_stir_market_data(
        curve_id_local=curve_id, snap_local=_as_of, fixings=sofr_fixings, side=live_side, include_serff=True
    )

    fomc_curve_nodes = get_fomc_meetings_list(as_of=_as_of_date, n_plus_years=n_plus_fomc_years)

    imm_nodes = [
        rl.get_imm(code=sfr.replace("/SR3", "")) if use_globex else rl.get_imm(code=sfr.replace("SFR", ""))
        for sfr in get_short_end_curve_tickers(as_of=_as_of_date, first_n_sr1=0, first_n_sr3=n_sfr_contracts, use_globex=use_globex)
    ]

    curve_nodes = list({*fomc_curve_nodes, *[d for d in imm_nodes if (d.year, d.month) not in {(d.year, d.month) for d in fomc_curve_nodes}]})
    curve_nodes.sort()

    rl_sofr_curve = rl.Curve(
        nodes=dict(zip(curve_nodes, [1] * len(curve_nodes))),
        id=curve_id,
        convention="act360",
        calendar="nyc",
        modifier="MF",
        interpolation="log_linear",
    )

    _stirf_items = sorted(rl_stirfs.items(), key=lambda kv: kv[0])  # sort by ticker/tenor key
    rl_fomc_turn_flies = build_rl_fomc_turn_flies(fomc_nodes=get_fomc_meetings_list(as_of=snap, n_plus_years=n_plus_fomc_years), curve_id=curve_id, one_step=True)
    rl_stirf_weights = [1] * len(rl_stirfs)
    rl_fomc_turn_flies_weights = [1e-8] * len(rl_fomc_turn_flies)

    rl_sofr_curve_solver = rl.Solver(
        curves=[rl_sofr_curve],
        instruments=[v for _, v in _stirf_items] + [v for _, v in sorted(rl_fomc_turn_flies.items(), key=lambda kv: kv[0])],
        s=[_safe_fixed_rate(v) for _, v in _stirf_items] + [0] * len(rl_fomc_turn_flies),
        id=curve_id,
        func_tol=1e-5,
        conv_tol=1e-5,
        weights=rl_stirf_weights + rl_fomc_turn_flies_weights,
    )

    return RLCurveSTIR(
        timestamp=curve_timestamp,
        rl_pricing_curve=rl_sofr_curve,
        rl_pricing_curve_solver=rl_sofr_curve_solver,
        rl_pricing_curve_instruments=rl_stirfs,
        basis=serff_basis,
        rl_risk_curve=None,
        rl_risk_curve_solver=None,
        rl_risk_curve_instruments=None,
    )
