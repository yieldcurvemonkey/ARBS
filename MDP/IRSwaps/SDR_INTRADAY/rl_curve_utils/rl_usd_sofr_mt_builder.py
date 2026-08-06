import datetime
import os
import re
from typing import Dict, List, Literal, Optional, Tuple, Union

import pandas as pd
import pytz
import QuantLib as ql
import rateslib as rl

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import get_quotes
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.SDRDataBuilder import SDRDataBuilder
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import (
    RLCurveBase,
    build_rl_fomc_turn_flies,
    build_rl_stirf,
    fetch_historical_usd_stir_curve_instruments_snapshot_barchart,
    get_fomc_meetings_list,
    get_short_end_curve_tickers,
)


def rl_usd_sofr_mt_builder(
    *,
    curve_id: str,
    snap: Union[datetime.datetime, datetime.date, List[Union[datetime.datetime, datetime.date]]],
    sofr_fixings: pd.Series,
    n_ser_contracts: int,
    n_sfr_contracts: int,
    n_plus_fomc_years: int,
    live_side: Literal["bid", "mid", "ask"] = "mid",
    medium_term_tenors: List[str] = ["5Y", "10Y", "30Y"],
    max_tenor: Optional[str] = "30Y",
    extrapolation_yrs: Optional[int] = 20,
    use_globex: Optional[bool] = False,
    schwab_app_key: Optional[str] = None,
    schwab_app_secret: Optional[str] = None,
) -> RLCurveBase:
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning)

    def _safe_fixed_rate(f):
        try:
            return f._fixed_rate.iloc[-1]
        except Exception:
            return f._fixed_rate

    def ql_date_to_datetime(ql_date: ql.Date) -> datetime.datetime:
        return datetime.datetime(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())

    def datetime_to_ql_date(dt: datetime.datetime) -> ql.Date:
        ql_month = {
            1: ql.January,
            2: ql.February,
            3: ql.March,
            4: ql.April,
            5: ql.May,
            6: ql.June,
            7: ql.July,
            8: ql.August,
            9: ql.September,
            10: ql.October,
            11: ql.November,
            12: ql.December,
        }[dt.month]
        return ql.Date(dt.day, ql_month, dt.year)

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

    def _fetch_medium_term_market_data(
        curve_id_local: str,
        snap_local: Union[datetime.datetime, datetime.date, List[Union[datetime.datetime, datetime.date]]],
        medium_term_tenors: List[str] = ["5Y", "10Y", "30Y"],
    ) -> Tuple[Union[datetime.datetime, datetime.date], Dict[str, rl.IRS]]:
        NY_tz = pytz.timezone("America/New_York")

        if type(snap_local) == datetime.date:
            raise NotImplementedError("eod medium-term datafetching for 'rl_usd_sofr_mt_q12' not implemented")

        if snap_local == "live":
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.ErisFuturesFetcher import ErisFuturesFetcher

            live_eris_rlcurve, ts = ErisFuturesFetcher().fetch_intraday_discount_curve(
                curve_id=curve_id_local, n_sfr_contracts=n_sfr_contracts, n_ser_contracts=0, medium_term_tenors=medium_term_tenors, n_plus_fomc_years=n_plus_fomc_years
            )
            rl_irs: Dict[str, rl.IRS] = {}

            snap_dt = datetime.datetime.now(tz=NY_tz)
            spot_datetime = ql_date_to_datetime(
                ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                    datetime_to_ql_date(datetime.datetime(snap_dt.year, snap_dt.month, snap_dt.day)), ql.Period("2D"), ql.ModifiedFollowing
                )
            )
            for tenor in medium_term_tenors:
                maturity_datetime = ql_date_to_datetime(
                    ql.NullCalendar().advance(
                        ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                            datetime_to_ql_date(datetime.datetime(snap_dt.year, snap_dt.month, snap_dt.day)),
                            ql.Period("2D"),
                            ql.ModifiedFollowing,
                        ),
                        ql.Period(tenor),
                    )
                )

                temp_rl_irs = rl.IRS(
                    effective=spot_datetime,
                    termination=maturity_datetime,
                    fixed_rate=-0.0,
                    curves=curve_id_local,
                    spec="usd_irs",
                )
                rl_irs[tenor] = rl.IRS(
                    effective=spot_datetime,
                    termination=maturity_datetime,
                    fixed_rate=temp_rl_irs.rate(curves=live_eris_rlcurve),
                    curves=curve_id_local,
                    spec="usd_irs",
                )

            return ts, rl_irs

        else:
            # Treat snap_local as a timezone-aware intraday timestamp (minute VWAP path)
            snap_dt = snap_local if isinstance(snap_local, datetime.datetime) else snap_local[0]
            start_timestamp = NY_tz.localize(datetime.datetime(snap_dt.year, snap_dt.month, snap_dt.day, 0, 0))
            end_timestamp = NY_tz.localize(datetime.datetime(snap_dt.year, snap_dt.month, snap_dt.day, 23, 59))

            cache_path = r"C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache"
            sdr_df = SDRDataBuilder(cache_path=cache_path, show_tqdm=True).grab_sdr_trades(
                start_timestamp=start_timestamp, end_timestamp=end_timestamp, agency="CFTC", asset_class="RATES"
            )

            spot_datetime = ql_date_to_datetime(
                ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                    datetime_to_ql_date(datetime.datetime(snap_dt.year, snap_dt.month, snap_dt.day)), ql.Period("2D"), ql.ModifiedFollowing
                )
            )

            usd_sofr_ois_upis = ["QZXQ4R16245X", "QZPB5VSBGRCD"]
            intraday_df = sdr_df.copy().sort_values(by="Execution Timestamp")
            intraday_df["Fixed rate-Leg 1"] = pd.to_numeric(intraday_df["Fixed rate-Leg 1"], errors="coerce")
            intraday_df = (
                intraday_df[
                    (intraday_df["Unique Product Identifier"].isin(usd_sofr_ois_upis))
                    & (intraday_df["Effective Date"].dt.date == spot_datetime.date())
                    & (intraday_df["Action type"] == "NEWT")
                    & (intraday_df["Event type"] == "TRAD")
                    & (intraday_df["Fixed rate-Leg 1"] > 0)
                    & (intraday_df["Platform identifier"] != "XOFF")
                    & (intraday_df["Large notional off-facility swap election indicator"].isna())
                    & (intraday_df["Other payment type"] != "UFRO")
                ]
                .set_index("Execution Timestamp")
                .sort_index()
            )
            intraday_df.index = intraday_df.index.tz_convert(snap_dt.tzinfo)
            intraday_df = intraday_df[intraday_df.index <= snap_dt]
            intraday_df.index = intraday_df.index.tz_convert(NY_tz)

            rl_irs: Dict[str, rl.IRS] = {}
            for tenor in medium_term_tenors:
                maturity_datetime = ql_date_to_datetime(
                    ql.NullCalendar().advance(
                        ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                            datetime_to_ql_date(datetime.datetime(snap_dt.year, snap_dt.month, snap_dt.day)),
                            ql.Period("2D"),
                            ql.ModifiedFollowing,
                        ),
                        ql.Period(tenor),
                    )
                )
                intraday_subset = intraday_df[intraday_df["Expiration Date"].dt.date == maturity_datetime.date()]
                w = intraday_subset["Notional amount-Leg 1"].replace(r"[^\d.]", "", regex=True).astype(float)
                minute_vwap = intraday_subset.assign(w=w, wx=intraday_subset["Fixed rate-Leg 1"] * w).resample("T").agg({"wx": "sum", "w": "sum"})
                minute_vwap["Fixed rate-Leg 1"] = minute_vwap["wx"] / minute_vwap["w"]
                minute_vwap = minute_vwap[["Fixed rate-Leg 1"]]
                idx = pd.date_range(intraday_subset.index.min().floor("T"), intraday_subset.index.max().ceil("T"), freq="T", tz=intraday_subset.index.tz)
                minute_vwap = minute_vwap.reindex(idx)

                minute_ffill = minute_vwap.ffill()
                target_idx = pd.date_range(start=minute_ffill.index[0], end=snap_dt, freq="T", tz=minute_ffill.index.tz)
                minute_ffill_eod = minute_ffill.reindex(target_idx).ffill()

                rl_irs[tenor] = rl.IRS(
                    effective=spot_datetime,
                    termination=maturity_datetime,
                    fixed_rate=minute_ffill_eod.loc[snap_dt]["Fixed rate-Leg 1"] * 100,
                    curves=curve_id_local,
                    spec="usd_irs",
                )

            return snap_dt, rl_irs

    stir_timestamp, rl_stirfs, _ = _fetch_stir_market_data(
        curve_id_local=curve_id,
        snap_local=snap,
        fixings=sofr_fixings,
        side=live_side,
        include_serff=False,
    )
    _, rl_irss = _fetch_medium_term_market_data(curve_id_local=curve_id, snap_local=snap, medium_term_tenors=medium_term_tenors)

    fomc_curve_nodes = get_fomc_meetings_list(as_of=snap, n_plus_years=n_plus_fomc_years)
    sfr_tickers = get_short_end_curve_tickers(
        as_of=snap if isinstance(snap, datetime.date) or snap == "live" else snap.date(),
        first_n_sr1=0,
        first_n_sr3=n_sfr_contracts,
        use_globex=use_globex,
    )
    imm_nodes = [rl.get_imm(code=sfr.replace("/SR3", "")) if use_globex else rl.get_imm(code=sfr.replace("SFR", "")) for sfr in sfr_tickers]
    st_nodes = list({*fomc_curve_nodes, *[d for d in imm_nodes if (d.year, d.month) not in {(d.year, d.month) for d in fomc_curve_nodes}]})
    st_nodes.sort()

    mt_nodes = sorted(s.leg1.schedule.termination for s in rl_irss.values())
    curve_nodes = sorted(st_nodes + mt_nodes)

    rl_stirfs_s = [_safe_fixed_rate(f) for f in rl_stirfs.values()]
    rl_irss_s = [_safe_fixed_rate(s) for s in rl_irss.values()]

    rl_fomc_turn_flies = build_rl_fomc_turn_flies(fomc_nodes=get_fomc_meetings_list(as_of=snap, n_plus_years=n_plus_fomc_years), curve_id=curve_id, one_step=True)
    rl_fomc_turn_flies_s = [0] * len(rl_fomc_turn_flies)

    rl_stirf_weights = [1] * len(rl_stirfs)
    rl_irss_weights = [1] * len(rl_irss)
    rl_fomc_turn_flies_weights = [1e-9] * len(rl_fomc_turn_flies)

    # TODO use nyc cal
    tail = max(rl_irss[max_tenor].leg1.cashflows()["Payment"]) + datetime.timedelta(days=365 * extrapolation_yrs)

    rl_sofr_pricing_curve = rl.Curve(
        nodes=dict(zip(curve_nodes, [1] * len(curve_nodes))),
        id=curve_id,
        convention="act360",
        calendar="nyc",
        modifier="MF",
        interpolation="log_linear",
        t=[st_nodes[-1], st_nodes[-1], st_nodes[-1], st_nodes[-1]] + mt_nodes[:-1] + [tail, tail, tail, tail],
    )
    rl_sofr_pricing_curve_solver = rl.Solver(
        curves=[rl_sofr_pricing_curve],
        instruments=list(rl_stirfs.values()) + list(rl_irss.values()) + list(rl_fomc_turn_flies.values()),
        s=rl_stirfs_s + rl_irss_s + rl_fomc_turn_flies_s,
        id=curve_id,
        weights=rl_stirf_weights + rl_irss_weights + rl_fomc_turn_flies_weights,
        func_tol=1e-8,
        conv_tol=1e-10,
    )

    return RLCurveBase(
        timestamp=stir_timestamp,
        rl_pricing_curve=rl_sofr_pricing_curve,
        rl_pricing_curve_solver=rl_sofr_pricing_curve_solver,
        rl_pricing_curve_instruments=rl_stirfs | rl_irss | rl_fomc_turn_flies,
        rl_risk_curve=None,
        rl_risk_curve_solver=None,
        rl_risk_curve_instruments=None,
    )
