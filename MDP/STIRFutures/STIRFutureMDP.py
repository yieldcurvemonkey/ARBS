import datetime
import re
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, Union

import pandas as pd
import pytz
import rateslib as rl

from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts, cme_code_effective_date, first_business_day_next_month
from MDP.MarketDataProvider import MarketDataProvider

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]


def _as_datetime(ts: DateLike) -> datetime.datetime:
    if ts == "live":
        return datetime.datetime.now(pytz.UTC)
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            return pytz.timezone("America/New_York").localize(ts)
        return ts
    if isinstance(ts, datetime.date):
        return pytz.timezone("America/New_York").localize(datetime.datetime.combine(ts, datetime.time(hour=12)))
    raise TypeError("timestamp must be date, datetime, or 'live'")


def _as_date(ts: DateLike) -> datetime.date:
    if ts == "live":
        return datetime.date.today()
    if isinstance(ts, datetime.datetime):
        return ts.date()
    if isinstance(ts, datetime.date):
        return ts
    raise TypeError("timestamp must be date, datetime, or 'live'")


def _normalize_symbol(sym: str) -> Optional[str]:
    s = (sym or "").strip().upper().replace("/", "")
    if not s:
        return None

    # If bare month code like "H26", assume SR3 root (3M SOFR)
    if re.fullmatch(r"[FGHJKMNQUVXZ]\d{2}", s):
        return f"SR3{s}"

    m = re.match(r"^(SR[13]|SFR|SER|FF|ZQ)([FGHJKMNQUVXZ]\d{2})$", s)
    if m:
        root, code = m.groups()
        root = root.replace("SFR", "SR3").replace("SER", "SR1").replace("FF", "ZQ")
        return f"{root}{code}"

    return WebullFintechFetcher._normalize_future_symbol(s)


def _package_contracts(color: str, as_of: datetime.date) -> List[str]:
    color_order = ["whites", "reds", "greens", "blues", "golds", "silvers", "platinums"]
    offset = color_order.index(color) * 4
    count = offset + 4
    contracts = _next_contracts(
        as_of, prefix="SR3", count=count, valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff
    )
    return contracts[offset:count]


def _resolve_aliases(symbols: Iterable[str], timestamp: DateLike) -> "OrderedDict[str, List[str]]":
    aliases: "OrderedDict[str, List[str]]" = OrderedDict()
    as_of = _as_date(timestamp)

    for raw in symbols:
        alias = (raw or "").strip()
        lower = alias.lower()

        # Package colors: whites/reds/greens/... map to consecutive IMM months
        if lower in {"whites", "reds", "greens", "blues", "golds", "silvers", "platinums"}:
            aliases[alias] = _package_contracts(lower, as_of)
            continue

        # Constant maturity rank: CM1 = front, CM2 = 2nd, etc.
        m_cm = re.match(r"^cm(?P<rank>\d+)$", lower)
        if m_cm:
            rank = int(m_cm.group("rank"))
            needed = max(rank, 1)
            contracts = _next_contracts(
                as_of, prefix="SR3", count=needed, valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff
            )
            aliases[alias] = [contracts[rank - 1]]
            continue

        norm = _normalize_symbol(alias)
        if norm:
            aliases[alias] = [norm]

    return aliases


def _clean_symbols(symbols: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for s in symbols:
        token = (s or "").strip()
        if not token:
            continue
        if "x" in token:
            cleaned.extend([p for p in token.split("x") if p])
        elif "/" in token:
            cleaned.extend([p for p in token.split("/") if p])
        else:
            cleaned.append(token)
    return cleaned


def _stir_future_from_symbol(sym: str, price: float) -> Tuple[str, rl.STIRFuture]:
    norm = _normalize_symbol(sym)
    if not norm:
        raise ValueError(f"Invalid STIR future symbol: {sym}")

    m = re.match(r"^(?P<root>[A-Z0-9]+)(?P<code>[FGHJKMNQUVXZ]\d{2})$", norm)
    if not m:
        raise ValueError(f"Could not parse STIR future symbol: {sym}")

    root = m.group("root")
    code = m.group("code")

    if root.startswith("SR1") or root.startswith("ZQ"):
        effective = cme_code_effective_date(code)
        termination = first_business_day_next_month(pd.Timestamp(effective))
        stir = rl.STIRFuture(
            effective=effective,
            termination=termination,
            spec="usd_stir1",
            roll="som",
            price=price,
        )
        return norm, stir

    effective = rl.scheduling.get_imm(code=code)
    termination = rl.scheduling.next_imm(effective)
    stir = rl.STIRFuture(
        effective=effective,
        termination=termination,
        spec="usd_stir",
        price=price,
    )
    return norm, stir


class STIRFutureMDP(MarketDataProvider[rl.STIRFuture]):
    def __init__(self, source: str = "WEBULL_STIRF-RL", **kwargs: Any):
        super().__init__(source, **kwargs)

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[rl.STIRFuture]]:
        return self.get_data(request)

    def get_data(self, request: Dict[str, Any]) -> Dict[str, List[rl.STIRFuture]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamp: DateLike = request.get("timestamp", "live")

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")

        ts_dt = _as_datetime(timestamp)
        alias_map = _resolve_aliases(symbols, timestamp)
        if not alias_map:
            raise ValueError("No valid symbols resolved from request.")

        all_tickers = sorted({t for tickers in alias_map.values() for t in tickers})
        wb = WebullFintechFetcher(debug_verbose=False, error_verbose=True)
        price_df = wb.intraday_by_tickers(
            tickers=all_tickers,
            start=ts_dt,
            end=ts_dt,
            show_tqdm=False,
        )

        if price_df.empty:
            raise RuntimeError("Webull returned no data for requested STIR futures.")

        last_prices = price_df.ffill().bfill().iloc[-1]

        out: Dict[str, List[rl.STIRFuture]] = {}
        for alias, tickers in alias_map.items():
            futs: List[rl.STIRFuture] = []
            for t in tickers:
                if t not in last_prices:
                    continue
                _, stir = _stir_future_from_symbol(t, float(last_prices[t]))
                futs.append(stir)
            out[alias] = futs

        return out
