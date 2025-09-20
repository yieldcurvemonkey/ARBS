import datetime
import itertools
import os
import random
import re
from dataclasses import dataclass, field
from io import StringIO
from typing import Dict, List, Literal, Optional, Set, Union

import pandas as pd
import pytz
import QuantLib as ql
import rateslib as rl
import requests
from bs4 import BeautifulSoup

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.BarchartFetcher import BarchartFetcher
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import cme_code_effective_date, first_business_day_next_month, get_short_end_curve_tickers


@dataclass
class RLCurveBase:
    timestamp: Union[datetime.date, datetime.datetime]
    rl_pricing_curve: rl.Curve
    rl_pricing_curve_solver: rl.Solver
    rl_pricing_curve_instruments: Dict[str, Union[rl.IRS, rl.STIRFuture]]

    rl_risk_curve: rl.Curve
    rl_risk_curve_solver: rl.Solver
    rl_risk_curve_instruments: Dict[str, Union[rl.IRS, rl.STIRFuture]]


@dataclass
class RLCurveSTIR(RLCurveBase):
    basis: Dict[str, float] = field(default_factory=dict)


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


def fetch_historical_usd_stir_curve_instruments_snapshot_barchart(
    snap: Union[datetime.date, datetime.datetime],
    tickers: Optional[List[str]] = None,
    first_n_sr1: Optional[int] = None,
    first_n_sr3: Optional[int] = None,
    use_globex: Optional[bool] = True,
):
    import time
    import random
    from urllib.parse import quote
    import requests

    # ---------- helpers ----------
    assert tickers is not None or (first_n_sr1 is not None and first_n_sr3 is not None), "Must pass in instrument args"
    assert snap.tzinfo is not None, "Must pass in tz-aware `snap`"
    snap = snap.astimezone(pytz.timezone("US/Central"))

    def to_barchart_symbol(x: str):
        if use_globex:
            return x.replace("/SR1", "SL").replace("/SR3", "SQ").replace("/ZQ", "ZQ")
        return x.replace("SER", "SL").replace("SFR", "SQ").replace("FF", "ZQ")

    def from_barchart_symbol(x: str):
        if use_globex:
            return x.replace("SL", "/SR1").replace("SQ", "/SR3").replace("ZQ", "/ZQ")
        return x.replace("SL", "SER").replace("SQ", "SFR").replace("ZQ", "FF")

    if tickers:
        usd_stir_barchart_symbol = [to_barchart_symbol(x) for x in tickers]
    else:
        usd_stir_barchart_symbol = [
            to_barchart_symbol(x) for x in get_short_end_curve_tickers(as_of=snap, first_n_sr1=first_n_sr1, first_n_sr3=first_n_sr3, use_globex=use_globex)
        ]

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
    if not hasattr(fetch_historical_usd_stir_curve_instruments_snapshot_barchart, "_state"):
        fetch_historical_usd_stir_curve_instruments_snapshot_barchart._state = {
            "proxies": None,  # dict | None
            "host": None,  # str | None
            "chosen_at": 0.0,  # epoch seconds
            "ttl": 60,  # reuse same POP for 1 minutes
            "fetcher": None,  # BarchartFetcher bound to proxies
        }
    _S = fetch_historical_usd_stir_curve_instruments_snapshot_barchart._state  # type: ignore[attr-defined]

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

    # ---------- data fetch (bulk, with connection reuse & throttling) ----------
    # Keep concurrency modest to avoid POP handshake churn.
    max_conc = min(len(usd_stir_barchart_symbol), 36)

    # Ask BarchartFetcher to keep sockets alive behind the scenes.
    df = bcf.barchart_timeseries_api(
        barchart_symbols=usd_stir_barchart_symbol,
        start_date=snap - datetime.timedelta(minutes=11),  # Barchart ~10m delay
        end_date=snap + datetime.timedelta(minutes=1),
        interval=1,
        one_df=True,
        max_concurrent_tasks=max_conc + 3,
        max_keepalive_connections=max(36, max_conc) + 3,
    )

    # ---------- postprocess ----------
    df.columns = [from_barchart_symbol(x) for x in df.columns]
    df = df.bfill().ffill()
    return df[df.index <= snap].tail(1)


def get_fomc_meetings_list(as_of: Optional[Union[datetime.date, datetime.datetime]] = None, n_plus_years: Optional[int] = 0):
    # assert n_plus_years < 3 and n_plus_years >= 0, "FOMC meeeting past 3 years unavailable"

    def _get_live_fomc_meeting_live(as_of: Optional[Union[datetime.date, datetime.datetime]] = None) -> List[Union[datetime.date, datetime.datetime]]:

        def most_recent_business_day_ql(ql_calendar: ql.Calendar, tz: Optional[str] = "UTC", to_pydate: Optional[bool] = False):
            from zoneinfo import ZoneInfo

            current_ts = pd.Timestamp.now(ZoneInfo(tz)).normalize()
            current_pydate = current_ts.to_pydatetime().date()
            current_ql = ql.Date(current_pydate.day, current_pydate.month, current_pydate.year)

            while not ql_calendar.isBusinessDay(current_ql):
                current_ql = current_ql - 1

            if to_pydate:
                return datetime(current_ql.year(), current_ql.month(), current_ql.dayOfMonth())
            else:
                return current_ql

        if as_of is None:
            ql_date = most_recent_business_day_ql(ql_calendar=ql.UnitedStates(ql.UnitedStates.FederalReserve))
            as_of = datetime.date(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())

        curr_sch_fomc_meeting_dates = [
            rl.dt(as_of.year, as_of.month, as_of.day),
            rl.dt(2025, 10, 29),
            rl.dt(2025, 12, 10),
            rl.dt(2026, 1, 28),
            rl.dt(2026, 3, 18),
            rl.dt(2026, 4, 29),
            rl.dt(2026, 6, 17),
            rl.dt(2026, 7, 29),
            rl.dt(2026, 9, 16),
            rl.dt(2026, 10, 28),
            rl.dt(2026, 12, 9),
        ]

        # guesses
        np1_fomc_meeting_dates = [
            rl.dt(2027, 1, 27),
            rl.dt(2027, 3, 17),
            rl.dt(2027, 4, 28),
            rl.dt(2027, 6, 9),
            rl.dt(2027, 7, 28),
            rl.dt(2027, 9, 15),
            rl.dt(2027, 10, 27),
            rl.dt(2027, 12, 8),
        ]
        np2_fomc_meeting_dates = [
            rl.dt(2028, 1, 26),
            rl.dt(2028, 3, 15),
            rl.dt(2028, 4, 26),
            rl.dt(2028, 6, 21),
            rl.dt(2028, 7, 26),
            rl.dt(2028, 9, 20),
            rl.dt(2028, 10, 25),
            rl.dt(2028, 12, 13),
        ]
        np3_fomc_meeting_dates = [
            rl.dt(2029, 1, 26),
            rl.dt(2029, 3, 15),
            rl.dt(2029, 4, 26),
            rl.dt(2029, 6, 14),
            rl.dt(2029, 7, 26),
            rl.dt(2029, 9, 13),
            rl.dt(2029, 10, 25),
            rl.dt(2029, 12, 13),
        ]

        if n_plus_years == 0:
            return curr_sch_fomc_meeting_dates
        elif n_plus_years == 1:
            return curr_sch_fomc_meeting_dates + np1_fomc_meeting_dates
        elif n_plus_years == 2:
            return curr_sch_fomc_meeting_dates + np1_fomc_meeting_dates + np2_fomc_meeting_dates
        else:
            return curr_sch_fomc_meeting_dates + np1_fomc_meeting_dates + np2_fomc_meeting_dates + np3_fomc_meeting_dates

    if as_of is None or as_of == "live":
        return _get_live_fomc_meeting_live()

    as_of = rl.dt(as_of.year, as_of.month, as_of.day)
    if as_of.date() == rl.dt.today().date():
        return _get_live_fomc_meeting_live()

    historical_meeting_dates: pd.Series[Union[datetime.date, datetime.datetime]] = fetch_fomc_rate_history_table()["Date"]
    live_fomc_dates = _get_live_fomc_meeting_live(as_of=as_of)
    if as_of > max(historical_meeting_dates):
        return live_fomc_dates

    last_avaliable_fomc_tradable = rl.dt(as_of.year + n_plus_years, 12, 31)
    historical_meeting_dates = pd.concat([historical_meeting_dates, pd.Series(live_fomc_dates)], ignore_index=True)
    historical_meeting_dates = historical_meeting_dates[
        (historical_meeting_dates >= as_of) & ((historical_meeting_dates < last_avaliable_fomc_tradable))
    ].sort_values()
    return historical_meeting_dates.to_list()


def fetch_fomc_rate_history_table() -> pd.DataFrame:
    import warnings

    warnings.filterwarnings("ignore", category=FutureWarning)

    resp = requests.get(
        "https://en.wikipedia.org/wiki/History_of_Federal_Open_Market_Committee_actions",
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/123.0.0.0 Safari/537.36"},
        timeout=30,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Find the wikitable with caption containing the desired text
    target_table_tag = None
    for tbl in soup.select("table.wikitable"):
        cap = tbl.find("caption")
        if not cap:
            continue
        caption_text = " ".join(cap.get_text(strip=True).split())
        if re.search(r"FOMC\s+Federal\s+Funds\s+Rate\s+History", caption_text, re.IGNORECASE):
            target_table_tag = tbl
            break

    if target_table_tag is None:
        raise RuntimeError("Could not find the 'FOMC Federal Funds Rate History' table on the page.")

    # Parse the single table HTML to DataFrame
    df = pd.read_html(StringIO(str(target_table_tag)), flavor="lxml")[0]

    # Basic clean-up: normalize column names
    df.columns = (
        df.columns.map(lambda c: " ".join(str(c).split()))
        .str.replace(r"\[\d+\]", "", regex=True)  # drop footnote markers like [22]
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    # Strip footnote markers inside cells
    df = df.applymap(lambda x: re.sub(r"\[\d+\]", "", str(x)).strip() if pd.notna(x) else x)

    # Try to coerce any percentage/range columns to numeric when possible
    def to_numeric_series(s: pd.Series) -> pd.Series:
        # If many cells look like percents or numbers, attempt conversion
        text = " ".join(s.dropna().astype(str).head(20).tolist())
        looks_numeric = bool(re.search(r"(\d|%|\.\d|\d\.\d|\d+\s*–\s*\d+)", text))
        if not looks_numeric:
            return s
        # Convert percentages like '5.25%' -> 5.25, and ranges '5.25–5.50' -> two cols
        # First, handle en-dash or hyphen ranges
        if s.astype(str).str.contains(r"\d\s*[–-]\s*\d").mean() > 0.5:
            # Split into lower/upper
            lower = s.astype(str).str.replace("%", "", regex=False).str.split(r"[–-]", expand=True)[0]
            upper = s.astype(str).str.replace("%", "", regex=False).str.split(r"[–-]", expand=True)[1]
            out = pd.DataFrame(
                {
                    s.name + " (Lower)": pd.to_numeric(lower.str.strip(), errors="coerce"),
                    s.name + " (Upper)": pd.to_numeric(upper.str.strip(), errors="coerce"),
                }
            )
            return out
        # Otherwise try single numeric
        single = pd.to_numeric(
            s.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False),
            errors="ignore",
        )
        return single

    # Apply conversion cautiously; if a column turns into a DataFrame (range split), collect it
    new_cols = {}
    drop_cols = []
    for col in list(df.columns):
        converted = to_numeric_series(df[col])
        if isinstance(converted, pd.DataFrame):
            new_cols.update({c: converted[c] for c in converted.columns})
            drop_cols.append(col)
        else:
            df[col] = converted

    if new_cols:
        df = pd.concat([df.drop(columns=drop_cols), pd.DataFrame(new_cols)], axis=1)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Target Mid"] = (
        df["Fed. Funds Rate"]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.split(r"[–-]", expand=True)  # handles en-dash or hyphen
        .astype(float)
        .mean(axis=1)  # midpoint of lower/upper
    )
    df["Move"] = df["Target Mid"].diff().mul(100) * -1
    df["Move"] = df["Move"].fillna(0).astype(int)
    return df


def get_fixings(rate: Literal["sofr", "effr"], n: Optional[int] = 90) -> pd.Series:
    if rate == "sofr":
        url = f"https://markets.newyorkfed.org/api/rates/secured/sofr/last/{n}.json"
    else:
        url = f"https://markets.newyorkfed.org/api/rates/unsecured/effr/last/{n}.json"
    res = requests.get(url, headers={"accept": "application/json"})
    res.raise_for_status()
    data = res.json().get("refRates", [])

    df = pd.DataFrame(data)
    if df.empty:
        raise ValueError(f"No {rate} data returned from NY Fed API.")

    df["effectiveDate"] = pd.to_datetime(df["effectiveDate"]).dt.date
    df["percentRate"] = pd.to_numeric(df["percentRate"], errors="coerce")
    df = df.dropna(subset=["percentRate"]).set_index("effectiveDate").sort_index()

    tz = pytz.timezone("America/Chicago")
    yday = datetime.datetime.now(tz).date() - datetime.timedelta(days=1)
    cal = ql.UnitedStates(ql.UnitedStates.FederalReserve)
    y_qld = ql.Date(yday.day, yday.month, yday.year)

    if cal.isBusinessDay(y_qld) and (yday not in df.index):
        last_val = float(df["percentRate"].iloc[-1])
        df.loc[yday] = last_val
        df = df.sort_index()

    df.index = pd.to_datetime(df.index)
    return df["percentRate"]


def get_turn_dates(instrument_dates: List[Union[datetime.date, datetime.datetime]]) -> List[Union[datetime.date, datetime.datetime]]:
    turn_dates: Set[Union[datetime.date, datetime.datetime]] = set()

    for dt in instrument_dates:
        first_day_of_current_month = dt.replace(day=1)
        first_day_of_next_month = (first_day_of_current_month + datetime.timedelta(days=32)).replace(day=1)
        last_day_of_current_month = first_day_of_next_month - datetime.timedelta(days=1)
        turn_dates.add(last_day_of_current_month)
        turn_dates.add(first_day_of_next_month)

    return sorted(list(turn_dates))


def get_turn_dates_bday_adj(
    instrument_dates: List[Union[datetime.date, datetime.datetime]],
    calendar: Optional[ql.Calendar] = ql.UnitedStates(ql.UnitedStates.FederalReserve),
    include_eomtm1: Optional[bool] = False,
) -> List[Union[datetime.date, datetime.datetime]]:
    turn_dates: Set[Union[datetime.date, datetime.datetime]] = set()

    for dt in instrument_dates:
        if hasattr(dt, "date"):
            dt = dt.date()

        first_day_of_current_month = dt.replace(day=1)
        first_day_of_next_month = (first_day_of_current_month + datetime.timedelta(days=32)).replace(day=1)
        last_day_of_current_month = first_day_of_next_month - datetime.timedelta(days=1)

        ql_eom_date = ql.Date(last_day_of_current_month.day, last_day_of_current_month.month, last_day_of_current_month.year)
        ql_som_date = ql.Date(first_day_of_next_month.day, first_day_of_next_month.month, first_day_of_next_month.year)

        adjusted_ql_eom = calendar.adjust(ql_eom_date, ql.Preceding)
        adjusted_ql_eomtm1 = calendar.adjust(adjusted_ql_eom - 1, ql.Preceding)
        adjusted_ql_som = calendar.adjust(ql_som_date, ql.Following)

        py_eomtm1_date = datetime.datetime(adjusted_ql_eomtm1.year(), adjusted_ql_eomtm1.month(), adjusted_ql_eomtm1.dayOfMonth())
        py_eom_date = datetime.datetime(adjusted_ql_eom.year(), adjusted_ql_eom.month(), adjusted_ql_eom.dayOfMonth())
        py_som_date = datetime.datetime(adjusted_ql_som.year(), adjusted_ql_som.month(), adjusted_ql_som.dayOfMonth())

        if include_eomtm1:
            turn_dates.add(py_eomtm1_date)
        turn_dates.add(py_eom_date)
        turn_dates.add(py_som_date)

    return sorted(list(turn_dates))


def build_rl_stirf(ticker: str, curve_id: str, price: float, fixings: pd.Series = None, use_globex=True):
    ser_key = "/SR1" if use_globex else "SER"
    sfr_key = "/SR3" if use_globex else "SFR"

    def build_rl_ser(month: str, curve_id: str, price: float):
        return f"{ser_key}{month}", rl.STIRFuture(
            effective=cme_code_effective_date(month),
            termination=first_business_day_next_month(pd.Timestamp(cme_code_effective_date(month))),
            spec="usd_stir1",
            roll="som",
            curves=curve_id,
            price=price,
            leg2_fixings=fixings,
        )

    def build_rl_sfr(month: str, curve_id: str, price: float):
        return f"{sfr_key}{month}", rl.STIRFuture(
            effective=rl.scheduling.get_imm(code=month),
            termination=rl.scheduling.next_imm(rl.scheduling.get_imm(code=month)),
            spec="usd_stir",
            curves=curve_id,
            price=price,
            # leg2_fixings=fixings
        )

    if ser_key in ticker:
        return build_rl_ser(month=ticker.replace(ser_key, ""), curve_id=curve_id, price=price)
    elif sfr_key in ticker:
        return build_rl_sfr(month=ticker.replace(sfr_key, ""), curve_id=curve_id, price=price)

    raise ValueError("Bad Ticker passed in")


def build_rl_turn_spreads(turn_curve_nodes: List[Union[datetime.date, datetime.datetime]], curve_id: str) -> List[rl.Spread]:
    spreads = []
    args = {"termination": "1d", "spec": "usd_irs_lt_2y", "curves": curve_id}

    for i in range(1, len(turn_curve_nodes), 3):
        if i + 1 < len(turn_curve_nodes):
            eom_date_tm1 = turn_curve_nodes[i - 1]
            eom_date = turn_curve_nodes[i]
            som_date = turn_curve_nodes[i + 1]

            # print(eom_date_tm1.date(), eom_date.date(), som_date.date())
            spreads.append(rl.Spread(rl.IRS(effective=eom_date_tm1, **args), rl.IRS(effective=eom_date, **args)))
            spreads.append(rl.Spread(rl.IRS(effective=eom_date, **args), rl.IRS(effective=som_date, **args)))

    return spreads


def build_rl_fomc_turn_flies(fomc_nodes: List[Union[datetime.date, datetime.datetime]], curve_id: str, one_step: Optional[bool] = False) -> Dict[str, rl.Fly]:
    args = {"termination": "1d", "spec": "usd_irs_lt_2y", "curves": curve_id}

    fomc_irs = [rl.IRS(effective=node, **args) for node in fomc_nodes]
    flies = {}
    if len(fomc_irs) < 3:
        return flies

    if one_step:
        for i in range(0, len(fomc_irs) - 2):
            fly = rl.Fly(fomc_irs[i], fomc_irs[i + 1], fomc_irs[i + 2])
            flies[f"{i}/{i+2}/{i+2}"] = fly
    else:
        for i in range(3, len(fomc_irs) - 2, 2):
            fly = rl.Fly(fomc_irs[i], fomc_irs[i + 1], fomc_irs[i + 2])
            flies[f"{i}/{i+2}/{i+2}"] = fly

    return flies
