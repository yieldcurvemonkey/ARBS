import datetime
import os
import re
from typing import Dict, List, Literal, Optional, Tuple, Union

import polars as pl
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
    sofr_fixings,  # Accepts dict-like or series-like (pandas/polars) - passed to rateslib
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
            # Handle both scalar and array-like _fixed_rate
            fixed_rate = f._fixed_rate
            if hasattr(fixed_rate, 'iloc'):  # pandas Series
                return fixed_rate.iloc[-1]
            elif hasattr(fixed_rate, '__getitem__') and hasattr(fixed_rate, '__len__'):  # polars or list-like
                return fixed_rate[-1]
            else:
                return fixed_rate
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
        fixings,  # Accepts dict-like or series-like (pandas/polars) - passed to rateslib
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
            # sdr_df is polars DataFrame from SDRDataBuilder
            intraday_df = (
                sdr_df.clone()
                .sort("Execution Timestamp")
                .with_columns([
                    pl.col("Fixed rate-Leg 1").cast(pl.Float64, strict=False)
                ])
                .filter(
                    pl.col("Unique Product Identifier").is_in(usd_sofr_ois_upis)
                    & (pl.col("Effective Date").dt.date() == spot_datetime.date())
                    & (pl.col("Action type") == "NEWT")
                    & (pl.col("Event type") == "TRAD")
                    & (pl.col("Fixed rate-Leg 1") > 0)
                    & (pl.col("Platform identifier") != "XOFF")
                    & pl.col("Large notional off-facility swap election indicator").is_null()
                    & (pl.col("Other payment type") != "UFRO")
                )
                .sort("Execution Timestamp")
            )
            # Convert timezone and filter
            intraday_df = intraday_df.with_columns([
                pl.col("Execution Timestamp").dt.convert_time_zone(str(snap_dt.tzinfo))
            ]).filter(
                pl.col("Execution Timestamp") <= snap_dt
            ).with_columns([
                pl.col("Execution Timestamp").dt.convert_time_zone("America/New_York")
            ])

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
                # Filter for matching maturity
                intraday_subset = intraday_df.filter(
                    pl.col("Expiration Date").dt.date() == maturity_datetime.date()
                )

                # Calculate weights from notional amounts (remove non-numeric characters)
                intraday_subset = intraday_subset.with_columns([
                    pl.col("Notional amount-Leg 1")
                    .str.replace_all(r"[^\d.]", "")
                    .cast(pl.Float64, strict=False)
                    .alias("w"),
                ]).with_columns([
                    (pl.col("Fixed rate-Leg 1") * pl.col("w")).alias("wx")
                ])

                # Group by minute and calculate VWAP
                minute_vwap = (
                    intraday_subset
                    .group_by_dynamic("Execution Timestamp", every="1m")
                    .agg([
                        pl.col("wx").sum().alias("wx"),
                        pl.col("w").sum().alias("w"),
                    ])
                    .with_columns([
                        (pl.col("wx") / pl.col("w")).alias("Fixed rate-Leg 1")
                    ])
                    .select(["Execution Timestamp", "Fixed rate-Leg 1"])
                    .sort("Execution Timestamp")
                )

                # Create full minute range and forward fill
                if len(minute_vwap) > 0:
                    # Get time range
                    min_time = intraday_subset["Execution Timestamp"].min()
                    max_time = intraday_subset["Execution Timestamp"].max()

                    # Create minute range from min to snap_dt
                    # Polars doesn't have date_range with timezone, so we create it manually
                    start_minute = min_time.replace(second=0, microsecond=0)
                    end_minute = snap_dt.replace(second=0, microsecond=0)

                    # Create timestamp range
                    minutes_count = int((end_minute - start_minute).total_seconds() / 60) + 1
                    minute_range = [start_minute + datetime.timedelta(minutes=i) for i in range(minutes_count)]

                    # Create full range dataframe
                    full_range_df = pl.DataFrame({
                        "Execution Timestamp": minute_range
                    })

                    # Join and forward fill
                    minute_ffill = (
                        full_range_df
                        .join(minute_vwap, on="Execution Timestamp", how="left")
                        .with_columns([
                            pl.col("Fixed rate-Leg 1").forward_fill()
                        ])
                    )

                    # Get value at snap_dt (find closest minute)
                    snap_minute = snap_dt.replace(second=0, microsecond=0)
                    rate_at_snap = minute_ffill.filter(
                        pl.col("Execution Timestamp") == snap_minute
                    )["Fixed rate-Leg 1"][0]

                    rl_irs[tenor] = rl.IRS(
                        effective=spot_datetime,
                        termination=maturity_datetime,
                        fixed_rate=rate_at_snap * 100,
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

    mt_nodes = sorted(s.__dict__["kwargs"]["termination"] for s in rl_irss.values())
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
