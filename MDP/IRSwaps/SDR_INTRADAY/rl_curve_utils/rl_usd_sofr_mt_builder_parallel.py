import datetime
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Literal, Optional, Tuple

import polars as pl
import pytz
import QuantLib as ql
import rateslib as rl
from tqdm import tqdm
import time
import random
from urllib.parse import quote
import requests
import itertools

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.BarchartFetcher import BarchartFetcher
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.SDRDataBuilder import SDRDataBuilder
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import (
    build_rl_fomc_turn_flies,
    build_rl_stirf,
    get_fomc_meetings_list,
    get_short_end_curve_tickers,
)

from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_datetime


NORDVPN_HOSTS = [
    # "amsterdam.nl.socks.nordhold.net",
    "atlanta.us.socks.nordhold.net",  # good
    "chicago.us.socks.nordhold.net",  # good
    "dallas.us.socks.nordhold.net",  # good
    "los-angeles.us.socks.nordhold.net",
    "new-york.us.socks.nordhold.net",
    "phoenix.us.socks.nordhold.net",
    "san-francisco.us.socks.nordhold.net",  # good
    # "stockholm.se.socks.nordhold.net", # good
    # "nl.socks.nordhold.net",
    # "se.socks.nordhold.net", # good
    "us.socks.nordhold.net",  # good
    None,
]
random.shuffle(NORDVPN_HOSTS)
proxy_cycler = itertools.cycle(NORDVPN_HOSTS)


NY = pytz.timezone("America/New_York")

# --- Worker-global variables ---
_SDR_VWAP_DF: Optional[pl.DataFrame] = None
_STIR_DAY_DF: Optional[pl.DataFrame] = None


def _safe_fixed_rate(f):
    try:
        # Handle polars Series
        if isinstance(f._fixed_rate, pl.Series):
            return f._fixed_rate[-1]
        # Handle list/array-like
        return f._fixed_rate[-1]
    except (TypeError, IndexError):
        # Scalar value
        return f._fixed_rate


def _ql_date_to_datetime(ql_date: ql.Date) -> datetime.datetime:
    return datetime.datetime(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())


def _datetime_to_ql_date(dt: datetime.datetime) -> ql.Date:
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


def _init_worker_env_and_data(sdr_vwap_df: pl.DataFrame, stir_df: pl.DataFrame, blas_threads: int = 1) -> None:
    """Initializes each worker by setting BLAS threads and storing daily dataframes."""
    os.environ["OMP_NUM_THREADS"] = str(blas_threads)
    os.environ["MKL_NUM_THREADS"] = str(blas_threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(blas_threads)
    os.environ["NUMEXPR_NUM_THREADS"] = str(blas_threads)

    global _SDR_VWAP_DF, _STIR_DAY_DF
    _SDR_VWAP_DF = sdr_vwap_df
    _STIR_DAY_DF = stir_df


def _calculate_daily_sdr_vwap_timeseries(day_sdr_df: pl.DataFrame, as_of_day: datetime.date, medium_term_tenors) -> pl.DataFrame:
    spot_datetime = ql_date_to_datetime(
        ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
            datetime_to_ql_date(datetime.datetime(as_of_day.year, as_of_day.month, as_of_day.day)), ql.Period("2D"), ql.ModifiedFollowing
        )
    )
    usd_sofr_ois_upis = ["QZXQ4R16245X", "QZPB5VSBGRCD"]

    # Convert Fixed rate-Leg 1 to numeric
    intraday_df = day_sdr_df.clone().with_columns(
        pl.col("Fixed rate-Leg 1").cast(pl.Float64, strict=False)
    ).sort("Execution Timestamp")

    # Filter based on conditions
    intraday_df = intraday_df.filter(
        pl.col("Unique Product Identifier").is_in(usd_sofr_ois_upis)
        & (pl.col("Effective Date").dt.date() == spot_datetime.date())
        & (pl.col("Action type") == "NEWT")
        & (pl.col("Event type") == "TRAD")
        & (pl.col("Fixed rate-Leg 1") > 0)
        & (pl.col("Platform identifier") != "XOFF")
        & pl.col("Large notional off-facility swap election indicator").is_null()
        & (pl.col("Other payment type") != "UFRO")
    ).sort("Execution Timestamp")

    # Convert timestamp to NY timezone
    intraday_df = intraday_df.with_columns(
        pl.col("Execution Timestamp").dt.convert_time_zone("America/New_York").alias("Execution Timestamp")
    )

    vwap_series_dict = {}
    for tenor in medium_term_tenors:
        maturity_datetime = ql_date_to_datetime(
            ql.NullCalendar().advance(
                ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                    datetime_to_ql_date(datetime.datetime(as_of_day.year, as_of_day.month, as_of_day.day)),
                    ql.Period("2D"),
                    ql.ModifiedFollowing,
                ),
                ql.Period(tenor),
            )
        )

        # Filter for specific maturity
        intraday_subset = intraday_df.filter(
            pl.col("Expiration Date").dt.date() == maturity_datetime.date()
        )

        if intraday_subset.height == 0:
            continue

        # Extract weights from notional (remove non-numeric characters)
        intraday_subset = intraday_subset.with_columns([
            pl.col("Notional amount-Leg 1").str.replace_all(r"[^\d.]", "").cast(pl.Float64).alias("w")
        ]).with_columns([
            (pl.col("Fixed rate-Leg 1") * pl.col("w")).alias("wx")
        ])

        # Group by minute and calculate VWAP
        minute_vwap = intraday_subset.group_by_dynamic(
            "Execution Timestamp",
            every="1m",
            period="1m",
        ).agg([
            pl.col("wx").sum(),
            pl.col("w").sum(),
        ]).with_columns([
            (pl.col("wx") / pl.col("w")).alias("Fixed rate-Leg 1")
        ]).select(["Execution Timestamp", "Fixed rate-Leg 1"])

        # Get time range (min/max return datetime objects, not Series)
        min_ts = intraday_subset["Execution Timestamp"].min()
        max_ts = intraday_subset["Execution Timestamp"].max()

        # Truncate to minute boundaries
        min_ts_truncated = min_ts.replace(second=0, microsecond=0)
        max_ts_truncated = max_ts.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)

        # Create complete minute grid
        minute_grid = pl.datetime_range(
            min_ts_truncated,
            max_ts_truncated,
            interval="1m",
            time_zone="America/New_York",
            eager=True
        ).to_frame("Execution Timestamp")

        # Join and forward fill
        minute_vwap_filled = minute_grid.join(
            minute_vwap, on="Execution Timestamp", how="left"
        ).with_columns([
            pl.col("Fixed rate-Leg 1").forward_fill()
        ])

        # Extend to full day
        last_ts = minute_vwap_filled["Execution Timestamp"].max()
        # Truncate to day boundary and add time
        sod = last_ts.replace(hour=0, minute=1, second=0, microsecond=0)
        eod = last_ts.replace(hour=23, minute=59, second=0, microsecond=0)

        target_grid = pl.datetime_range(
            sod,
            eod,
            interval="1m",
            time_zone="America/New_York",
            eager=True
        ).to_frame("Execution Timestamp")

        minute_ffill_eod = target_grid.join(
            minute_vwap_filled, on="Execution Timestamp", how="left"
        ).with_columns([
            pl.col("Fixed rate-Leg 1").forward_fill().backward_fill()
        ])

        # Store both timestamp and VWAP value
        if "Execution Timestamp" not in vwap_series_dict:
            vwap_series_dict["Execution Timestamp"] = minute_ffill_eod["Execution Timestamp"]
        vwap_series_dict[f"{tenor}_VWAP"] = minute_ffill_eod["Fixed rate-Leg 1"]

    # Create DataFrame from dict - Execution Timestamp should be first
    if vwap_series_dict:
        # Get the timestamp column
        ts_col = vwap_series_dict.pop("Execution Timestamp", None)
        result = pl.DataFrame(vwap_series_dict)
        if ts_col is not None:
            result = result.insert_column(0, ts_col.alias("Execution Timestamp"))
        return result
    else:
        # Return empty dataframe with at least Execution Timestamp column
        return pl.DataFrame({"Execution Timestamp": []})


def _build_one_mt_curve_worker(
    *,
    base_curve_id: str,
    snap_iso: str,
    sofr_fixings: Dict,
    n_ser_contracts: int,
    n_sfr_contracts: int,
    n_plus_fomc_years: int,
    use_globex: bool,
    medium_term_tenors=["5Y", "10Y", "30Y"],
    max_tenor="30Y",
    extrapolation_yrs=20,
) -> Tuple[datetime.datetime, rl.Curve]:
    """Worker function that builds one curve using pre-fetched daily data."""
    global _SDR_VWAP_DF, _STIR_DAY_DF
    assert _SDR_VWAP_DF is not None and _STIR_DAY_DF is not None, "Worker dataframes not initialized"
    day_sdr_vwap_df = _SDR_VWAP_DF
    day_stir_df = _STIR_DAY_DF

    # Parse timestamp
    snap = datetime.datetime.fromisoformat(snap_iso)
    curve_id = f"{snap}-{base_curve_id}"
    snap = snap.astimezone(NY) if snap.tzinfo is not None else NY.localize(snap)

    # Filter STIR data up to snap time (assuming day_stir_df has timestamp index or column)
    stir_df_snap = day_stir_df.filter(
        pl.col("timestamp") <= snap
    ).tail(1)
    if stir_df_snap.height == 0:
        raise ValueError(f"No STIR data available for snapshot {snap}")

    rl_stirfs: Dict[str, rl.STIRFuture] = {}
    # Iterate over columns (tickers) in stir_df_snap
    for ticker in stir_df_snap.columns:
        if ticker == "timestamp":  # Skip timestamp column
            continue
        if ("/ZQ" if use_globex else "FF") in ticker:
            continue
        price = stir_df_snap[ticker][0]
        obj_t, obj_stirf = build_rl_stirf(ticker=ticker, curve_id=curve_id, price=price, fixings=sofr_fixings, use_globex=use_globex)
        rl_stirfs[obj_t] = obj_stirf

    # 2) Look up swap rates from pre-calculated daily VWAP timeseries
    spot_dt = _ql_date_to_datetime(
        ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
            _datetime_to_ql_date(datetime.datetime(snap.year, snap.month, snap.day)),
            ql.Period("2D"),
            ql.ModifiedFollowing,
        )
    )

    rl_irss: Dict[str, rl.IRS] = {}
    for tenor in medium_term_tenors:
        maturity_dt = _ql_date_to_datetime(ql.NullCalendar().advance(datetime_to_ql_date(spot_dt), ql.Period(tenor)))
        vwap_col = f"{tenor}_VWAP"

        rate_at_snap = 0.0
        if vwap_col in day_sdr_vwap_df.columns:
            # Filter up to snap time and forward fill, then get last value
            filtered = day_sdr_vwap_df.filter(
                pl.col("Execution Timestamp") <= snap
            ).with_columns([
                pl.col(vwap_col).forward_fill()
            ])
            if filtered.height > 0:
                val = filtered[vwap_col][-1]
                rate_at_snap = float(val) if val is not None else 0.0

        assert rate_at_snap != 0.0, "should not be zero!"

        rl_irss[tenor] = rl.IRS(
            effective=spot_dt,
            termination=maturity_dt,
            fixed_rate=rate_at_snap * 100,
            curves=curve_id,
            spec="usd_irs",
        )

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

    tail = max(rl_irss[max_tenor].leg1.cashflows()["Payment"]) + datetime.timedelta(days=365 * extrapolation_yrs)

    rl_sofr_pricing_curve = rl.Curve(
        nodes=dict(zip(curve_nodes, [1] * len(curve_nodes))),
        id=curve_id,
        convention="act360",
        calendar="nyc",
        modifier="MF",
        interpolation="log_linear",
        t=[st_nodes[-1], st_nodes[-1], st_nodes[-1], st_nodes[-1]] + mt_nodes[:-1] + [tail, tail, tail, tail] 
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

    return snap, rl_sofr_pricing_curve


def rl_usd_sofr_mt_builder_parallel(
    *,
    base_curve_id: str,
    snaps: List[datetime.datetime],
    sofr_fixings: Dict,
    n_ser_contracts: int,
    n_sfr_contracts: int,
    n_plus_fomc_years: int,
    max_workers: int,
    use_globex: Optional[bool] = False,
    medium_term_tenors=["5Y", "10Y", "30Y"],
    max_tenor="30Y",
    extrapolation_yrs=20,
) -> Dict[datetime.datetime, rl.Curve]:
    """Main parallel builder that fetches and prepares data before dispatching jobs."""
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)

    # Normalize snapshots to NY timezone
    norm_snaps = sorted([
        s.tz_localize(NY) if s.tzinfo is None else s.astimezone(NY)
        for s in snaps
    ])
    by_day = {}
    for s in norm_snaps:
        by_day.setdefault(s.date(), []).append(s)

    cache_path = os.getenv("SDR_CACHE_DIR", r"C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache")
    sdr_builder = SDRDataBuilder(cache_path=cache_path, show_tqdm=False)
    bcf = BarchartFetcher(proxies=None, debug_verbose=False)
    bcf._fetch_session_tokens()

    sdr_vwap_by_day: Dict[datetime.date, pl.DataFrame] = {}
    stir_by_day: Dict[datetime.date, pl.DataFrame] = {}

    for day in tqdm(by_day.keys(), desc="Prefetching and preparing daily data"):
        # start_ts = NY.localize(datetime.datetime.combine(day, datetime.time.min))
        # end_ts = NY.localize(datetime.datetime.combine(day, datetime.time.max))
        start_ts = NY.localize(datetime.datetime(day.year, day.month, day.day, 0, 0))
        end_ts = NY.localize(datetime.datetime(day.year, day.month, day.day, 23, 59))

        sdr_df = sdr_builder.grab_sdr_trades(start_timestamp=start_ts, end_timestamp=end_ts, agency="CFTC", asset_class="RATES")

        # Convert to polars if pandas (SDRDataBuilder returns pandas)
        if not isinstance(sdr_df, pl.DataFrame):
            import pandas as pd
            sdr_df = pl.from_pandas(sdr_df)

        sdr_vwap_by_day[day] = _calculate_daily_sdr_vwap_timeseries(sdr_df, day, medium_term_tenors)

        tickers = get_short_end_curve_tickers(as_of=day, first_n_sr1=n_ser_contracts, first_n_sr3=n_sfr_contracts, use_globex=use_globex)
        barchart_tickers = [
            t.replace("/SR1", "SL").replace("/SR3", "SQ").replace("/ZQ", "ZQ") if use_globex else t.replace("SER", "SL").replace("SFR", "SQ").replace("FF", "ZQ")
            for t in tickers
        ]

        def from_barchart_symbol(x: str):
            if use_globex:
                return x.replace("SL", "/SR1").replace("SQ", "/SR3").replace("ZQ", "/ZQ")
            return x.replace("SL", "SER").replace("SQ", "SFR").replace("ZQ", "FF")

        def _build_socks5h(host: str) -> dict:
            user = os.getenv("NORDVPN_USER") or ""
            pwd = os.getenv("NORDVPN_PASS") or ""
            # MUST be Nord service credentials; URL-encode both
            url = f"socks5h://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:1080"
            return {"http": url, "https": url}

        def _preflight_proxy(proxies: dict | None, timeout=6) -> bool:
            try:
                r = requests.get(
                    "https://api.ipify.org?format=json",
                    proxies=proxies,
                    timeout=timeout,
                    headers={"Connection": "close"},
                )
                r.raise_for_status()
                return True
            except Exception:
                return False

        class _ProxyGuard:
            """Force chosen proxies + Connection: close for token fetches (reduce WAF flakiness)."""

            def __init__(self, proxies: dict | None):
                self.proxies = proxies

            def __enter__(self):
                self._orig_get = requests.get

                def _patched_get(url, *args, **kwargs):
                    hdrs = kwargs.pop("headers", {}) or {}
                    if "Connection" not in {k.title(): v for k, v in hdrs.items()}:
                        hdrs["Connection"] = "close"
                    kwargs["headers"] = hdrs
                    if self.proxies is not None:
                        kwargs["proxies"] = self.proxies
                    else:
                        kwargs.pop("proxies", None)
                    return self._orig_get(url, *args, **kwargs)

                requests.get = _patched_get
                return self

            def __exit__(self, exc_type, exc, tb):
                requests.get = self._orig_get

        # ---------- persistent, cross-call cache ----------
        # We store a “sticky” proxy choice & a fetcher instance so we can reuse connections.
        if not hasattr(rl_usd_sofr_mt_builder_parallel, "_state"):
            rl_usd_sofr_mt_builder_parallel._state = {
                "proxies": None,  # dict | None
                "host": None,  # str | None
                "chosen_at": 0.0,  # epoch seconds
                "ttl": 60,  # reuse same POP for 1 minutes
                "fetcher": None,  # BarchartFetcher bound to proxies
            }
        _S = rl_usd_sofr_mt_builder_parallel._state  # type: ignore[attr-defined]

        # Build candidate list (shuffled once per process start by your code)
        hosts_cycle = proxy_cycler

        # If cached POP is fresh, keep using it
        def _get_cached_proxies() -> tuple[dict | None, str | None]:
            nonlocal _S
            if time.time() - _S["chosen_at"] < _S["ttl"]:
                return _S["proxies"], _S["host"]
            return None, None

        def _choose_proxies() -> tuple[dict | None, str | None]:
            """Rotate through Nord POPs, preflight, allow direct if None."""
            for _ in range(len(NORDVPN_HOSTS)):
                host = next(hosts_cycle)
                if host is None:
                    return None, None
                proxies = _build_socks5h(host)
                if _preflight_proxy(proxies):
                    return proxies, host
            # If no POP worked, go direct
            return None, None

        proxies, host = _get_cached_proxies()
        if proxies is None and host is None:
            proxies, host = _choose_proxies()
            _S["proxies"], _S["host"], _S["chosen_at"] = proxies, host, time.time()
            # Discard old fetcher if proxies changed
            _S["fetcher"] = None

        # Make/Reuse the Barchart fetcher bound to this proxy
        bcf = _S["fetcher"]
        if bcf is None:
            bcf = BarchartFetcher(proxies=proxies, debug_verbose=False)  # reuse same POP across calls
            _S["fetcher"] = bcf

        # ---------- session token seeding (once per batch) ----------
        # Do token fetch through ProxyGuard to force Connection: close.
        try:
            with _ProxyGuard(proxies):
                # One token fetch per batch; bcf should reuse cookies/session for the subsequent API calls
                bcf._fetch_session_tokens(dummy_symbol="BTC")
        except Exception:
            # Proxy likely died; rotate once and retry token fetch
            proxies, host = _choose_proxies()
            _S["proxies"], _S["host"], _S["chosen_at"] = proxies, host, time.time()
            _S["fetcher"] = BarchartFetcher(proxies=proxies, debug_verbose=False)
            bcf = _S["fetcher"]
            with _ProxyGuard(proxies):
                bcf._fetch_session_tokens(dummy_symbol="BTC")

        max_conc = min(len(barchart_tickers), 36)
        stir_df = bcf.barchart_timeseries_api(
            barchart_symbols=barchart_tickers,
            start_date=start_ts,
            end_date=end_ts,
            interval=1,
            one_df=True,
            max_concurrent_tasks=max_conc + 3,
            max_keepalive_connections=max(36, max_conc) + 3,
        )

        # Convert to polars if pandas (BarchartFetcher returns pandas)
        if hasattr(stir_df, 'to_polars'):
            # pandas DataFrame
            import pandas as pd
            stir_df = pl.from_pandas(stir_df.reset_index())
        elif not isinstance(stir_df, pl.DataFrame):
            # Just in case it's something else
            import pandas as pd
            stir_df = pl.from_pandas(pd.DataFrame(stir_df).reset_index())

        # Rename columns
        stir_df = stir_df.rename({col: from_barchart_symbol(col) for col in stir_df.columns if col != 'index'})

        # Backward fill then forward fill all columns
        fill_cols = [col for col in stir_df.columns if col != 'index']
        stir_df = stir_df.with_columns([
            pl.col(col).backward_fill().forward_fill() for col in fill_cols
        ])

        # Rename index column to timestamp if it exists
        if 'index' in stir_df.columns:
            stir_df = stir_df.rename({'index': 'timestamp'})

        stir_by_day[day] = stir_df

        # tickers = get_short_end_curve_tickers(as_of=day, first_n_sr1=n_ser_contracts, first_n_sr3=n_sfr_contracts, use_globex=use_globex)
        # barchart_tickers = [t.replace("/SR1", "SL").replace("/SR3", "SQ").replace("/ZQ", "ZQ") if use_globex else t.replace("SER", "SL").replace("SFR", "SQ").replace("FF", "ZQ") for t in tickers]
        # stir_df = bcf.barchart_timeseries_api(barchart_symbols=barchart_tickers, start_date=start_ts, end_date=end_ts, interval=1, one_df=True, show_tqdm=False)
        # stir_df.columns = [c.replace("SL", "/SR1" if use_globex else "SER").replace("SQ", "/SR3" if use_globex else "SFR") for c in stir_df.columns]
        # stir_by_day[day] = stir_df.bfill().ffill()

    mp_ctx = multiprocessing.get_context("spawn")
    out: Dict[datetime.datetime, rl.Curve] = {}

    for day, day_snaps in by_day.items():
        with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=mp_ctx,
            initializer=_init_worker_env_and_data,
            initargs=(sdr_vwap_by_day.get(day, pl.DataFrame()), stir_by_day.get(day, pl.DataFrame()), 1),
        ) as ex:
            futures = [
                ex.submit(
                    _build_one_mt_curve_worker,
                    base_curve_id=base_curve_id,
                    snap_iso=s.isoformat(),
                    sofr_fixings=sofr_fixings,
                    n_ser_contracts=n_ser_contracts,
                    n_sfr_contracts=n_sfr_contracts,
                    n_plus_fomc_years=n_plus_fomc_years,
                    medium_term_tenors=medium_term_tenors,
                    max_tenor=max_tenor,
                    extrapolation_yrs=extrapolation_yrs,
                    use_globex=bool(use_globex),
                )
                for s in day_snaps
            ]
            for fut in tqdm(as_completed(futures), total=len(futures), desc=f"Calibrating {base_curve_id} curves for {day}"):
                snap, result = fut.result()
                out[snap] = result

    return dict(sorted(out.items(), key=lambda kv: norm_snaps.index(kv[0])))
