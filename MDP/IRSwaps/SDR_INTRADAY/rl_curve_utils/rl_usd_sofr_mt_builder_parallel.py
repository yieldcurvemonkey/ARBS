import datetime
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Literal, Optional, Tuple

import pandas as pd
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
from utils.rl_compat import instrument_kwarg


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
_SDR_VWAP_DF: Optional[pd.DataFrame] = None
_STIR_DAY_DF: Optional[pd.DataFrame] = None


def _safe_fixed_rate(f):
    try:
        return f._fixed_rate.iloc[-1]
    except Exception:
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


def _init_worker_env_and_data(sdr_vwap_df: pd.DataFrame, stir_df: pd.DataFrame, blas_threads: int = 1) -> None:
    """Initializes each worker by setting BLAS threads and storing daily dataframes."""
    os.environ["OMP_NUM_THREADS"] = str(blas_threads)
    os.environ["MKL_NUM_THREADS"] = str(blas_threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(blas_threads)
    os.environ["NUMEXPR_NUM_THREADS"] = str(blas_threads)

    global _SDR_VWAP_DF, _STIR_DAY_DF
    _SDR_VWAP_DF = sdr_vwap_df
    _STIR_DAY_DF = stir_df


def _calculate_daily_sdr_vwap_timeseries(day_sdr_df: pd.DataFrame, as_of_day: datetime.date, medium_term_tenors) -> pd.DataFrame:
    spot_datetime = ql_date_to_datetime(
        ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
            datetime_to_ql_date(datetime.datetime(as_of_day.year, as_of_day.month, as_of_day.day)), ql.Period("2D"), ql.ModifiedFollowing
        )
    )
    usd_sofr_ois_upis = ["QZXQ4R16245X", "QZPB5VSBGRCD"]
    intraday_df = day_sdr_df.copy().sort_values(by="Execution Timestamp")
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
    intraday_df.index = intraday_df.index.tz_convert(NY)

    # sod_ny = NY.localize(datetime.datetime(as_of_day.year, as_of_day.month, as_of_day.day, 0, 0))
    # eod_ny = NY.localize(datetime.datetime(as_of_day.year, as_of_day.month, as_of_day.day, 23, 59))
    # minute_grid = pd.date_range(start=sod_ny, end=eod_ny, freq="T", tz=NY)

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
        intraday_subset = intraday_df[intraday_df["Expiration Date"].dt.date == maturity_datetime.date()]
        w = intraday_subset["Notional amount-Leg 1"].replace(r"[^\d.]", "", regex=True).astype(float)
        minute_vwap = intraday_subset.assign(w=w, wx=intraday_subset["Fixed rate-Leg 1"] * w).resample("T").agg({"wx": "sum", "w": "sum"})
        minute_vwap["Fixed rate-Leg 1"] = minute_vwap["wx"] / minute_vwap["w"]
        minute_vwap = minute_vwap[["Fixed rate-Leg 1"]]
        idx = pd.date_range(intraday_subset.index.min().floor("T"), intraday_subset.index.max().ceil("T"), freq="T", tz=intraday_subset.index.tz)
        minute_vwap = minute_vwap.reindex(idx)

        minute_ffill = minute_vwap.ffill()
        sod = minute_ffill.index[-1].normalize() + pd.Timedelta(hours=0, minutes=1)
        eod = minute_ffill.index[-1].normalize() + pd.Timedelta(hours=23, minutes=59)
        target_idx = pd.date_range(start=sod, end=eod, freq="T", tz=minute_ffill.index.tz)
        minute_ffill_eod = minute_ffill.reindex(target_idx).ffill().bfill()
        vwap_series_dict[f"{tenor}_VWAP"] = minute_ffill_eod["Fixed rate-Leg 1"]

        # sub = intraday_df[intraday_df["Expiration Date"].dt.date == maturity_datetime.date()].copy()
        # if sub.empty:
        #     # still output a series (NaNs); you can ffill at consumption-time if desired
        #     vwap_series_dict[f"{tenor}_VWAP"] = pd.Series(index=minute_grid, dtype=float)
        #     continue

        # # minute aggregation (sum of weights and weighted price *within* each minute)
        # sub["w"] = sub["Notional amount-Leg 1"].replace(r"[^\d.]", "", regex=True).astype(float)
        # sub["wx"] = sub["w"] * sub["Fixed rate-Leg 1"]
        # per_min = sub.resample("T").agg({"wx": "sum", "w": "sum"}).reindex(minute_grid).ffill().bfill()

        # # ---- CAUSAL VWAP: expanding sums up to each minute ----
        # cwx = per_min["wx"].cumsum()
        # cw = per_min["w"].cumsum()

        # # avoid divide-by-zero; where cw==0 keep NaN (will be ffilled by consumer)
        # vwap_causal = cwx.where(cw == 0, cwx / cw)
        # vwap_series_dict[f"{tenor}_VWAP"] = vwap_causal

    return pd.DataFrame(*[vwap_series_dict])
    # return pd.DataFrame(vwap_series_dict)


def _build_one_mt_curve_worker(
    *,
    base_curve_id: str,
    snap_iso: str,
    sofr_fixings: pd.Series,
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

    snap = pd.to_datetime(snap_iso)
    curve_id = f"{snap}-{base_curve_id}"
    snap = snap.tz_convert(NY) if snap.tzinfo is not None else NY.localize(snap)

    stir_df_snap = day_stir_df[day_stir_df.index <= snap].tail(1)
    if stir_df_snap.empty:
        raise ValueError(f"No STIR data available for snapshot {snap}")

    rl_stirfs: Dict[str, rl.STIRFuture] = {}
    for t, q in stir_df_snap.T.iterrows():
        if ("/ZQ" if use_globex else "FF") in t:
            continue
        obj_t, obj_stirf = build_rl_stirf(ticker=t, curve_id=curve_id, price=q, fixings=sofr_fixings, use_globex=use_globex)
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
            val = day_sdr_vwap_df[vwap_col].loc[:snap].ffill().iloc[-1]
            rate_at_snap = float(val) if pd.notna(val) else 0.0

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

    mt_nodes = sorted(instrument_kwarg(s, "termination") for s in rl_irss.values())
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
    sofr_fixings: pd.Series,
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

    norm_snaps = sorted([pd.to_datetime(s).tz_localize(NY) if s.tzinfo is None else pd.to_datetime(s).astimezone(NY) for s in snaps])
    by_day = {}
    for s in norm_snaps:
        by_day.setdefault(s.date(), []).append(s)

    cache_path = os.getenv("SDR_CACHE_DIR", r"C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache")
    sdr_builder = SDRDataBuilder(cache_path=cache_path, show_tqdm=False)
    bcf = BarchartFetcher(proxies=None, debug_verbose=False)
    bcf._fetch_session_tokens()

    sdr_vwap_by_day: Dict[datetime.date, pd.DataFrame] = {}
    stir_by_day: Dict[datetime.date, pd.DataFrame] = {}

    for day in tqdm(by_day.keys(), desc="Prefetching and preparing daily data"):
        # start_ts = NY.localize(datetime.datetime.combine(day, datetime.time.min))
        # end_ts = NY.localize(datetime.datetime.combine(day, datetime.time.max))
        start_ts = NY.localize(datetime.datetime(day.year, day.month, day.day, 0, 0))
        end_ts = NY.localize(datetime.datetime(day.year, day.month, day.day, 23, 59))

        sdr_df = sdr_builder.grab_sdr_trades(start_timestamp=start_ts, end_timestamp=end_ts, agency="CFTC", asset_class="RATES")
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
        stir_df.columns = [from_barchart_symbol(x) for x in stir_df.columns]
        stir_df = stir_df.bfill().ffill()
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
            initargs=(sdr_vwap_by_day.get(day, pd.DataFrame()), stir_by_day.get(day, pd.DataFrame()), 1),
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
