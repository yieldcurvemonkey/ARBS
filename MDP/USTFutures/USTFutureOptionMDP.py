import datetime
import calendar
import hashlib
import importlib.util
import itertools
import json
import logging
import math
import os
import random
import re
import threading
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import pandas as pd
import pytz
import QuantLib as ql
import rateslib as rl
import requests

from Caching.DiskCacheMixin import DiskCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher
from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from Query.USTFutureOptions.backends.quantlib.QLUSTFutureOptionPricer import QLUSTFutureOptionPricer
from definitions.USTFutures import UST_FUTURE_BARCHART_TO_INTERNAL
from definitions.USTFutureOptions import (
    ALL_OPTION_ROOTS,
    MONTH_CODE_TO_NUM as _MONTH_CODE_TO_NUM,
    decode_strike_token,
    encode_strike_token,
    is_weekly_root,
    normalize_contract_code,
    normalize_option_contract,
    normalize_option_root,
    normalize_strike_token,
    option_expiry_date,
    option_root_base_root,
    parse_option_contract,
    strike_step_for_contract as _strike_step_for_contract_def,
    underlying_contract_for_option,
)


DateLike = Union[datetime.date, datetime.datetime, str, Literal["live"]]
InstrumentLike = QLUSTFutureOptionPricer

_NY_TZ = pytz.timezone("America/New_York")
_CHI_TZ = pytz.timezone("America/Chicago")
_UTC_TZ = pytz.UTC

_ROOT_TOKEN_PATTERN = "|".join(re.escape(r) for r in ALL_OPTION_ROOTS)
_OPTION_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{1,2}})\|(?P<strike>\d{{3,5}})(?P<right>[CPS])$",
    re.IGNORECASE,
)
_OPTION_ATM_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{1,2}})\|ATM(?P<right>[CPS])$",
    re.IGNORECASE,
)
_OPTION_DELTA_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{1,2}})\|(?P<delta>\d{{1,2}}(?:\.\d+)?)D?(?P<right>[CP])$",
    re.IGNORECASE,
)
_OPTION_ATM_NATURAL_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{1,2}})\s+ATM\s+(?P<right>STRADDLE|CALL|PUT)$",
    re.IGNORECASE,
)
_OPTION_DELTA_NATURAL_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{1,2}})\s+(?P<delta>\d{{1,2}}(?:\.\d+)?)\s*D(?:ELTA)?\s+(?P<right>STRADDLE|CALL|PUT)$",
    re.IGNORECASE,
)
_FUTURE_RE = re.compile(rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{1,2}})$", re.IGNORECASE)
_USTF_CONTRACT_RE = re.compile(r"^(?P<root>[A-Z]{2,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", re.IGNORECASE)

_DEFAULT_CURVE_NAME = "USD-SOFR-1D-Q12xM12STIRT"

_FV01_FALLBACK_BY_INTERNAL_ROOT: Dict[str, float] = {
    # Approximate futures price DV01 (price points per 1bp yield move), by complex.
    "TU": 0.020,
    "FV": 0.040,
    "TY": 0.080,
    "US": 0.160,
    "WN": 0.160,
    "UXY": 0.080,
}


def _socksio_available() -> bool:
    return importlib.util.find_spec("socksio") is not None


def _build_socks5h(host: str) -> dict:
    user = os.getenv("NORDVPN_USER", "3G5mmfKXWfCGFGT4yDL34Tzn")
    pwd = os.getenv("NORDVPN_PASS", "VN33uViQZp6pXVzdgsGskhNg")
    if not user or not pwd:
        raise ValueError("Missing NORDVPN_USER/NORDVPN_PASS in environment.")
    url = f"socks5h://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:1080"
    return {"http": url, "https": url}


def _preflight_proxy(proxies: dict | None, timeout: int = 6) -> bool:
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
            title_map = {k.title(): v for k, v in hdrs.items()}
            if "Connection" not in title_map:
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


def _as_datetime(ts: DateLike) -> datetime.datetime:
    if isinstance(ts, str):
        token = ts.strip()
        if token.lower() == "live":
            return datetime.datetime.now(_UTC_TZ)
        parsed = pd.Timestamp(token)
        if parsed.tzinfo is None:
            return _NY_TZ.localize(parsed.to_pydatetime())
        return parsed.to_pydatetime()

    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            return _NY_TZ.localize(ts)
        return ts

    if isinstance(ts, datetime.date):
        return _NY_TZ.localize(datetime.datetime.combine(ts, datetime.time(hour=17, minute=0)))

    raise TypeError("timestamp must be date, datetime, iso-string, or 'live'")


def _as_date(ts: DateLike) -> datetime.date:
    if isinstance(ts, str):
        token = ts.strip()
        if token.lower() == "live":
            return datetime.datetime.now(_NY_TZ).date()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
            return datetime.date.fromisoformat(token)
        return _as_datetime(token).astimezone(_NY_TZ).date()

    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = _NY_TZ.localize(ts)
        return ts.astimezone(_NY_TZ).date()

    if isinstance(ts, datetime.date):
        return ts

    raise TypeError("timestamp must be date, datetime, iso-string, or 'live'")


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


def _to_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
        if math.isnan(out):
            return None
        return out
    except Exception:
        return None


def _right_word_to_token(right_word: str) -> str:
    token = str(right_word or "").strip().upper()
    if token in {"C", "CALL"}:
        return "C"
    if token in {"P", "PUT"}:
        return "P"
    if token in {"S", "STRADDLE"}:
        return "S"
    raise ValueError(f"Unsupported option right token: {right_word}")


def _format_strike4(strike: float, contract: Optional[str] = None) -> str:
    if contract:
        return encode_strike_token(contract_or_root=contract, strike=float(strike))
    # Backward-compatible fallback.
    return str(int(round(float(strike) * 100.0))).zfill(4)


def _atm_strike_from_forward(forward: float, step: float = 0.25) -> float:
    if not math.isfinite(forward) or forward <= 0.0:
        raise ValueError(f"Invalid forward for ATM strike resolution: {forward}")
    if step <= 0.0:
        step = 0.25
    return round(forward / step) * step


def _strike_step_for_contract(contract: str) -> float:
    try:
        return float(_strike_step_for_contract_def(contract))
    except Exception:
        return 0.25


def _strike_ladder(center: float, step: float, half_width_steps: int) -> List[float]:
    base = round(center / step) * step
    return [base + i * step for i in range(-half_width_steps, half_width_steps + 1)]


def _estimate_bachelier_strike_for_target_delta(
    *,
    right: str,
    target_delta_abs: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float = 1.0,
) -> float:
    # Closed-form seed from normal model delta, then small local refinement via BachelierCalculator.
    stddev = max(vol_normal, 0.0) * math.sqrt(max(tte, 1e-12))
    icn = ql.InverseCumulativeNormal()
    target = float(target_delta_abs) / 100.0
    if str(right).upper() == "C":
        z = float(icn(target))
    else:
        # Put deltaForward = N(d) - 1
        z = float(icn(1.0 - target))
    seed = float(forward) - stddev * z

    # Refine around the seed using calculator delta.
    step = max(stddev * 0.1, 0.01)
    best_k = seed
    best_err = float("inf")
    for j in range(-6, 7):
        k = seed + j * step
        d = _bachelier_delta_from_calculator(
            right=right,
            strike=k,
            forward=forward,
            vol_normal=vol_normal,
            tte=tte,
            discount=discount,
        )
        if not math.isfinite(d):
            continue
        if str(right).upper() == "C":
            err = abs(d - target)
        else:
            err = abs(d + target)
        if err < best_err:
            best_err = err
            best_k = k
    return float(best_k)


def _normalize_vendor_delta(value: Any) -> Optional[float]:
    d = _to_float(value)
    if d is None:
        return None
    if abs(d) > 1.5:
        d = d / 100.0
    return d


def _contract_to_barchart_contract(contract: str) -> str:
    return normalize_option_contract(contract)


def _parse_contract_token(token: str) -> Dict[str, Any]:
    t = str(token or "").strip().upper().replace("/", "")
    if _FUTURE_RE.fullmatch(t):
        return {
            "contract_selector": "explicit",
            "contract": normalize_option_contract(t),
            "cm_root": None,
            "cm_rank": None,
        }
    raise ValueError(f"Invalid UST option contract token: {token}")


def _resolve_cm_contract(*, cm_root: str, cm_rank: int, as_of: datetime.date) -> str:
    _ = cm_root, cm_rank, as_of
    raise NotImplementedError("UST future options do not support CM aliases.")


def _resolve_contract_from_spec(spec: Dict[str, Any], as_of: datetime.date) -> str:
    selector = str(spec.get("contract_selector", "explicit"))
    if selector == "explicit":
        c = spec.get("contract")
        if not c:
            raise ValueError(f"Missing explicit contract in spec: {spec}")
        return normalize_option_contract(str(c), as_of=as_of)
    if selector == "cm":
        root = str(spec.get("cm_root") or "ZN")
        rank = int(spec.get("cm_rank") or 1)
        return _resolve_cm_contract(cm_root=root, cm_rank=rank, as_of=as_of)
    raise ValueError(f"Unsupported contract selector: {selector}")


def _next_quarterly_code(month_code: str, year_2digit: int) -> Tuple[str, int]:
    _ = month_code, year_2digit
    raise NotImplementedError("UST option underlying mapping is handled by definitions.USTFutureOptions.")


def _option_contract_to_underlying_contract(contract: str) -> str:
    return underlying_contract_for_option(contract)


def _parse_option_request_symbol(symbol: str, *, as_of: Optional[datetime.date] = None) -> Dict[str, Any]:
    token = str(symbol or "").strip().upper().replace("/", "")

    def _build(
        *,
        contract_spec: Dict[str, Any],
        selector: str,
        right: str,
        strike4: Optional[str],
        delta: Optional[float],
    ) -> Dict[str, Any]:
        if contract_spec["contract_selector"] == "explicit":
            contract_ref = str(contract_spec["contract"])
        else:
            contract_ref = f"{contract_spec['cm_root']}CM{int(contract_spec['cm_rank'])}"

        if selector == "strike":
            canonical = f"{contract_ref}|{strike4}{right}"
        elif selector == "atm":
            canonical = f"{contract_ref}|ATM{right}"
        else:
            canonical = f"{contract_ref}|{float(delta):g}D{right}"

        return {
            "selector": selector,
            "right": right,
            "contract": contract_spec.get("contract"),
            "contract_selector": contract_spec["contract_selector"],
            "cm_root": contract_spec.get("cm_root"),
            "cm_rank": contract_spec.get("cm_rank"),
            "canonical": canonical,
            "strike4": strike4,
            "delta": delta,
        }

    if "|" in token:
        contract_part, leg_part = token.split("|", 1)
        contract_spec = _parse_contract_token(contract_part)
        if contract_spec["contract_selector"] == "explicit":
            contract_spec["contract"] = normalize_option_contract(contract_spec["contract"], as_of=as_of)

        m = re.fullmatch(r"(?P<strike>\d{3,5})(?P<right>[CPS])", leg_part)
        if m:
            strike4 = normalize_strike_token(
                contract_or_root=str(contract_spec["contract"]),
                strike_token=m.group("strike"),
            )
            right = m.group("right").upper()
            return _build(contract_spec=contract_spec, selector="strike", right=right, strike4=strike4, delta=None)

        m = re.fullmatch(r"ATM(?P<right>[CPS])", leg_part)
        if m:
            right = m.group("right").upper()
            return _build(contract_spec=contract_spec, selector="atm", right=right, strike4=None, delta=None)

        m = re.fullmatch(r"(?P<delta>\d{1,2}(?:\.\d+)?)D?(?P<right>[CP])", leg_part)
        if m:
            right = m.group("right").upper()
            delta = float(m.group("delta"))
            if delta <= 0.0 or delta >= 100.0:
                raise ValueError(f"Delta alias must be in (0,100): {symbol}")
            return _build(contract_spec=contract_spec, selector="delta", right=right, strike4=None, delta=delta)

    m = re.fullmatch(
        rf"(?P<contract>(?:{_ROOT_TOKEN_PATTERN})[FGHJKMNQUVXZ]\d{{1,2}})\s+ATM\s+(?P<right>STRADDLE|CALL|PUT)",
        token,
    )
    if m:
        contract_spec = _parse_contract_token(m.group("contract"))
        contract_spec["contract"] = normalize_option_contract(contract_spec["contract"], as_of=as_of)
        right = _right_word_to_token(m.group("right"))
        return _build(contract_spec=contract_spec, selector="atm", right=right, strike4=None, delta=None)

    m = re.fullmatch(
        rf"(?P<contract>(?:{_ROOT_TOKEN_PATTERN})[FGHJKMNQUVXZ]\d{{1,2}})\s+(?P<delta>\d{{1,2}}(?:\.\d+)?)\s*D(?:ELTA)?\s+(?P<right>STRADDLE|CALL|PUT)",
        token,
    )
    if m:
        contract_spec = _parse_contract_token(m.group("contract"))
        contract_spec["contract"] = normalize_option_contract(contract_spec["contract"], as_of=as_of)
        right = _right_word_to_token(m.group("right"))
        if right == "S":
            raise ValueError("Delta straddle alias is not supported; use explicit strikes or 25DC/25DP legs.")
        delta = float(m.group("delta"))
        if delta <= 0.0 or delta >= 100.0:
            raise ValueError(f"Delta alias must be in (0,100): {symbol}")
        return _build(contract_spec=contract_spec, selector="delta", right=right, strike4=None, delta=delta)

    raise ValueError(f"Invalid UST option symbol token: {symbol}")


def _norm_option_symbol(symbol: str) -> str:
    parsed = _parse_option_request_symbol(symbol)
    if parsed["selector"] != "strike":
        raise ValueError(f"Symbol does not contain explicit strike: {symbol}")
    if parsed.get("contract_selector") != "explicit":
        raise ValueError(f"Symbol does not contain explicit contract code: {symbol}")
    return str(parsed["canonical"])


def _resolve_option_contract_aliases_for_date(
    requested_specs: "OrderedDict[str, Dict[str, Any]]",
    as_of: datetime.date,
) -> "OrderedDict[str, Dict[str, Any]]":
    out: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for raw, spec in requested_specs.items():
        resolved_contract = _resolve_contract_from_spec(spec, as_of=as_of)
        selector = str(spec["selector"])
        right = str(spec["right"]).upper()
        delta = _to_float(spec.get("delta"))
        strike4 = spec.get("strike4")
        if selector == "strike":
            canonical = f"{resolved_contract}|{strike4}{right}"
        elif selector == "atm":
            canonical = f"{resolved_contract}|ATM{right}"
        elif selector == "delta":
            canonical = f"{resolved_contract}|{float(delta):g}D{right}"
        else:
            raise ValueError(f"Unsupported selector in option spec: {selector}")

        next_spec = dict(spec)
        next_spec["contract_selector"] = "explicit"
        next_spec["contract"] = resolved_contract
        next_spec["canonical"] = canonical
        out[raw] = next_spec
    return out


def _expand_straddle_symbol(symbol: str) -> List[str]:
    canonical = _norm_option_symbol(symbol)
    if canonical.endswith("S"):
        return [f"{canonical[:-1]}C", f"{canonical[:-1]}P"]
    return [canonical]


def _canonical_to_barchart_contract(symbol: str) -> str:
    token = _norm_option_symbol(symbol)
    fut = token.split("|", 1)[0]
    return fut


def _canonical_to_barchart_option(symbol: str) -> str:
    token = _norm_option_symbol(symbol)
    return token


def _canonical_contract(symbol: str) -> str:
    return _norm_option_symbol(symbol).split("|", 1)[0]


def _canonical_underlying(symbol: str) -> str:
    return _option_contract_to_underlying_contract(_canonical_contract(symbol))


def _strike_from_symbol(symbol: str) -> float:
    token = _norm_option_symbol(symbol)
    contract, strike_right = token.split("|", 1)
    strike_token = strike_right[:-1]
    return float(decode_strike_token(contract_or_root=contract, strike_token=strike_token))


def _right_from_symbol(symbol: str) -> str:
    return _norm_option_symbol(symbol)[-1]


def _contract_code_from_symbol(symbol: str) -> str:
    return parse_option_contract(_canonical_contract(symbol))[1]


def _ql_date_to_pydate(d: ql.Date) -> datetime.date:
    serial = d.serialNumber()
    dt = datetime.datetime.fromordinal(serial + 693594)
    return dt.date()


def _contract_expiry_date(code2: str) -> datetime.date:
    norm = normalize_contract_code(code2)
    month = _MONTH_CODE_TO_NUM[norm[0]]
    year = 2000 + int(norm[1:])
    # Monthly fallback when root context is unavailable.
    return datetime.date(year, month, 1)


def _time_to_expiry(val_date: datetime.date, exp_date: datetime.date) -> float:
    dt_days = (exp_date - val_date).days
    return max(dt_days / 365.0, 1e-6)


def _ql_option_type(right: str) -> int:
    r = str(right).upper()
    if r == "C":
        return ql.Option.Call
    if r == "P":
        return ql.Option.Put
    raise ValueError(f"Unsupported option right for QuantLib Bachelier: {right}")


def _bachelier_price(right: str, strike: float, forward: float, vol_normal: float, tte: float, discount: float) -> float:
    stddev = max(vol_normal, 0.0) * math.sqrt(max(tte, 1e-12))
    return float(ql.bachelierBlackFormula(_ql_option_type(right), float(strike), float(forward), float(stddev), float(discount)))


def _implied_normal_vol(right: str, strike: float, forward: float, tte: float, price: float, discount: float) -> float:
    if tte <= 0.0 or price <= 0.0:
        return float("nan")
    try:
        return float(
            ql.bachelierBlackFormulaImpliedVolChoi(
                _ql_option_type(right),
                float(strike),
                float(forward),
                float(tte),
                float(price),
                float(discount),
            )
        )
    except Exception:
        return float("nan")


def _bachelier_delta_from_calculator(
    *,
    right: str,
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float,
) -> float:
    if tte <= 0.0 or not math.isfinite(vol_normal) or vol_normal <= 0.0:
        return float("nan")
    try:
        payoff = ql.PlainVanillaPayoff(_ql_option_type(right), float(strike))
        stddev = max(vol_normal, 0.0) * math.sqrt(max(tte, 1e-12))
        calc = ql.BachelierCalculator(payoff, float(forward), float(stddev), float(discount))
        return float(calc.deltaForward())
    except Exception:
        return float("nan")


def _to_internal_ustf_contract(contract: str, *, as_of: Optional[datetime.date] = None) -> str:
    token = str(contract or "").strip().upper().replace("/", "")
    m = _USTF_CONTRACT_RE.fullmatch(token)
    if m is None:
        return token
    root = m.group("root")
    code = normalize_contract_code(m.group("code"), as_of=as_of)
    internal_root = UST_FUTURE_BARCHART_TO_INTERNAL.get(root, root)
    return f"{internal_root}{code}"


def _fv01_fallback_for_contract(contract: str) -> float:
    token = str(contract or "").strip().upper().replace("/", "")
    m = _USTF_CONTRACT_RE.fullmatch(token)
    root = m.group("root") if m is not None else token[:-3]
    internal_root = UST_FUTURE_BARCHART_TO_INTERNAL.get(root, root)
    return float(_FV01_FALLBACK_BY_INTERNAL_ROOT.get(internal_root, 0.050))


def _bachelier_greeks_fd(
    *,
    right: str,
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float,
    use_ql_calculator: bool = True,
) -> Tuple[float, float, float, float]:
    if tte <= 0.0 or not math.isfinite(vol_normal) or vol_normal <= 0.0:
        return float("nan"), float("nan"), float("nan"), float("nan")

    if use_ql_calculator:
        try:
            payoff = ql.PlainVanillaPayoff(_ql_option_type(right), float(strike))
            stddev = max(vol_normal, 0.0) * math.sqrt(max(tte, 1e-12))
            calc = ql.BachelierCalculator(
                payoff,
                float(forward),
                float(stddev),
                float(discount),
            )
            delta = float(calc.deltaForward())
            gamma = float(calc.gammaForward())
            vega = float(calc.vega(float(tte)))
            theta = float(calc.theta(float(forward), float(tte)))
            return delta, gamma, vega, theta
        except Exception as e:
            print(f"ql pricing failed... fallback: {e}")
            # Fall back to finite differences if calculator path fails.
            pass

    h_f = 0.01
    h_v = max(1e-4, vol_normal * 0.01)
    dt = 1.0 / 365.0

    p0 = _bachelier_price(right, strike, forward, vol_normal, tte, discount)
    p_up = _bachelier_price(right, strike, forward + h_f, vol_normal, tte, discount)
    p_dn = _bachelier_price(right, strike, forward - h_f, vol_normal, tte, discount)
    delta = (p_up - p_dn) / (2.0 * h_f)
    gamma = (p_up - 2.0 * p0 + p_dn) / (h_f * h_f)

    pv_up = _bachelier_price(right, strike, forward, vol_normal + h_v, tte, discount)
    pv_dn = _bachelier_price(right, strike, forward, max(vol_normal - h_v, 1e-8), tte, discount)
    vega = (pv_up - pv_dn) / (2.0 * h_v)

    t_up = tte + dt
    t_dn = max(tte - dt, 1e-6)
    pt_up = _bachelier_price(right, strike, forward, vol_normal, t_up, discount)
    pt_dn = _bachelier_price(right, strike, forward, vol_normal, t_dn, discount)
    theta = (pt_up - pt_dn) / (2.0 * dt)

    return float(delta), float(gamma), float(vega), float(theta)


def _extract_row_price(row: Dict[str, Any], price_mode: str = "mid_then_fallback") -> Optional[float]:
    if price_mode != "mid_then_fallback":
        raise ValueError(f"Unsupported price_mode: {price_mode}")

    bid = _to_float(row.get("bidPrice", row.get("BidPrice")))
    ask = _to_float(row.get("askPrice", row.get("OfferPrice")))
    if bid is not None and ask is not None and bid > 0.0 and ask > 0.0:
        return 0.5 * (bid + ask)

    for key in ("lastPrice", "Close", "close", "Open", "open"):
        v = _to_float(row.get(key))
        if v is not None and v > 0.0:
            return v
    return None


def _nearest_index_position(index: pd.Index, target: pd.Timestamp) -> Optional[int]:
    if len(index) == 0:
        return None
    if not isinstance(index, pd.DatetimeIndex):
        return len(index) - 1
    idx = index
    t = target
    if idx.tz is None:
        if t.tzinfo is not None:
            t = t.tz_convert(_UTC_TZ).tz_localize(None)
    else:
        if t.tzinfo is None:
            t = t.tz_localize(idx.tz)
        else:
            t = t.tz_convert(idx.tz)
    loc = idx.get_indexer([t], method="nearest")
    if loc.size == 0 or loc[0] == -1:
        return None
    return int(loc[0])


def _asof_index_position(index: pd.Index, target: pd.Timestamp) -> Optional[int]:
    """Return the last row at or before target (no look-ahead)."""
    if len(index) == 0:
        return None
    if not isinstance(index, pd.DatetimeIndex):
        return len(index) - 1

    idx = index
    t = pd.Timestamp(target)

    if idx.tz is None:
        if t.tzinfo is not None:
            # For tz-aware requests against naive EOD bars, keep the request calendar date.
            t = pd.Timestamp(t.date())
    else:
        if t.tzinfo is None:
            t = t.tz_localize(idx.tz)
        else:
            t = t.tz_convert(idx.tz)

    # EOD series are date buckets; ignore time-of-day when selecting as-of rows.
    if (idx == idx.normalize()).all():
        t = pd.Timestamp(t.date()) if idx.tz is None else t.normalize()

    pos = int(idx.searchsorted(t, side="right") - 1)
    if pos < 0:
        return None
    return pos

class USTFutureOptionMDP(MarketDataProvider[InstrumentLike], DiskCacheMixin):
    _UST_OPTION_CACHE = "_ust_option_pricer_cache"
    _BARCHART_STATE: Dict[str, Any] = {}
    _CURVE_STATE: Dict[str, Any] = {}

    def __init__(self, source: str = "BARCHART_USTFO-QL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        DiskCacheMixin.__init__(self)

        self.cache_full_intraday_fetch = bool(kwargs.get("cache_full_intraday_fetch", False))
        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False

        self._barchart_fetcher: Optional[BarchartFetcher] = None
        self._barchart_lock = threading.RLock()
        self._barchart_proxies_static = kwargs.get("barchart_proxies")
        self._fv01_memo: Dict[str, float] = {}
        self._curve_name_default = kwargs.get("curve_name_default", _DEFAULT_CURVE_NAME)
        self._socksio_enabled = _socksio_available()
        # Historical fetch windows are fixed to one month on either side of the request range.
        self._barchart_prefetch_months = 1

        default_hosts = [
            "atlanta.us.socks.nordhold.net",
            "chicago.us.socks.nordhold.net",
            "dallas.us.socks.nordhold.net",
            "los-angeles.us.socks.nordhold.net",
            "new-york.us.socks.nordhold.net",
            "phoenix.us.socks.nordhold.net",
            "san-francisco.us.socks.nordhold.net",
            "us.socks.nordhold.net",
            None,
        ]
        self._barchart_proxy_hosts: List[Optional[str]] = list(kwargs.get("barchart_proxy_hosts", default_hosts))
        if not self._socksio_enabled:
            self._barchart_proxy_hosts = [None]
        random.shuffle(self._barchart_proxy_hosts)
        self._barchart_proxy_ttl: int = int(kwargs.get("barchart_proxy_ttl", 60))
        self._barchart_session_token_pool_size_cap: int = max(1, int(kwargs.get("barchart_session_token_pool_size_cap", 24)))

        if not USTFutureOptionMDP._BARCHART_STATE:
            USTFutureOptionMDP._BARCHART_STATE = {
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
                "ttl": self._barchart_proxy_ttl,
                "fetcher": None,
                "cycler": itertools.cycle(self._barchart_proxy_hosts),
                "lock": threading.RLock(),
            }

        if not USTFutureOptionMDP._CURVE_STATE:
            USTFutureOptionMDP._CURVE_STATE = {
                "builder": None,
                "lock": threading.RLock(),
            }

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._UST_OPTION_CACHE):
            return
        cache_path = DiskCacheMixin.default_cache_path("USTFutureOptionPricer_Cache")
        self.open_cache(cache_attr=self._UST_OPTION_CACHE, path=cache_path, encode=None, decode=None)
        self._cache_ready = True

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._UST_OPTION_CACHE)
            cache[key] = value

    def _threadsafe_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._UST_OPTION_CACHE)
            return cache.get(key)

    def _cache_primitive(self, value: Any) -> Any:
        if isinstance(value, datetime.datetime):
            if value.tzinfo is None:
                value = _NY_TZ.localize(value)
            return {"__datetime__": value.astimezone(_UTC_TZ).isoformat()}
        if isinstance(value, datetime.date):
            return {"__date__": value.isoformat()}
        if isinstance(value, dict):
            return {str(k): self._cache_primitive(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
        if isinstance(value, (list, tuple, set)):
            return [self._cache_primitive(v) for v in value]
        if isinstance(value, float):
            if math.isnan(value):
                return "NaN"
            if math.isinf(value):
                return "Inf" if value > 0 else "-Inf"
        return value

    def _historical_prefetch_window(
        self,
        *,
        start: datetime.date,
        end: datetime.date,
    ) -> Tuple[datetime.date, datetime.date]:
        # Exact historical window: one calendar month before start and one month after end.
        return self._shift_month(start, -self._barchart_prefetch_months), self._shift_month(end, self._barchart_prefetch_months)

    @staticmethod
    def _shift_month(value: datetime.date, months: int) -> datetime.date:
        month_index = value.month - 1 + int(months)
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return datetime.date(year, month, day)

    def _normalize_symbols_for_cache(
        self,
        *,
        symbols: Iterable[str],
        as_of: Optional[datetime.date] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for raw in _clean_symbols(symbols):
            try:
                spec = _parse_option_request_symbol(raw, as_of=as_of)
                if as_of is not None:
                    resolved = _resolve_option_contract_aliases_for_date(OrderedDict([(raw, spec)]), as_of=as_of)
                    spec = resolved[raw]
                out.append(
                    {
                        "selector": str(spec.get("selector")),
                        "right": str(spec.get("right")),
                        "contract_selector": str(spec.get("contract_selector")),
                        "contract": spec.get("contract"),
                        "cm_root": spec.get("cm_root"),
                        "cm_rank": spec.get("cm_rank"),
                        "strike4": spec.get("strike4"),
                        "delta": _to_float(spec.get("delta")),
                        "canonical": str(spec.get("canonical")),
                    }
                )
            except Exception:
                out.append({"raw": str(raw).strip().upper()})
        return sorted(out, key=lambda item: json.dumps(self._cache_primitive(item), sort_keys=True))

    def _build_barchart_pricer_window_cache_key(
        self,
        *,
        leg_symbols: Iterable[str],
        window_start: datetime.date,
        window_end: datetime.date,
        price_mode: str,
        curve_name: str,
        curve_kwargs: Dict[str, Any],
        use_ql_calculator: bool,
    ) -> str:
        payload = {
            "schema": 1,
            "cache_version": "ustfo_barchart_pricer_window_v2",
            "source": str(self.source).upper(),
            "symbols": sorted({str(s).upper() for s in leg_symbols}),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "price_mode": str(price_mode),
            "curve_name": str(curve_name),
            "curve_kwargs": self._cache_primitive(curve_kwargs or {}),
            "use_ql_calculator": bool(use_ql_calculator),
        }
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(payload_str.encode("utf-8")).hexdigest()
        return f"USTFO_BC_WINDOW::{digest}"

    def _serialize_pricer_window(
        self,
        pricers_by_symbol_date: Dict[str, Dict[datetime.date, QLUSTFutureOptionPricer]],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for symbol, by_day in sorted(pricers_by_symbol_date.items(), key=lambda kv: str(kv[0])):
            plist = [self._serialize_pricer(pr) for _, pr in sorted(by_day.items(), key=lambda kv: kv[0])]
            payload[str(symbol)] = plist
        return {"schema": 1, "result": payload}

    def _deserialize_pricer_window(
        self,
        cached: Any,
    ) -> Optional[Dict[str, Dict[datetime.date, QLUSTFutureOptionPricer]]]:
        if not isinstance(cached, dict):
            return None
        if int(cached.get("schema", 0)) != 1:
            return None
        raw = cached.get("result")
        if not isinstance(raw, dict):
            return None
        out: Dict[str, Dict[datetime.date, QLUSTFutureOptionPricer]] = defaultdict(dict)
        try:
            for symbol, plist in raw.items():
                if not isinstance(plist, list):
                    continue
                for row in plist:
                    if not isinstance(row, dict):
                        continue
                    pr = self._deserialize_pricer(row)
                    day = pr.quote_timestamp().astimezone(_NY_TZ).date()
                    out[str(symbol)][day] = pr
        except Exception:
            return None
        return dict(out)

    def _build_get_data_cache_key(self, endpoint: str, request: Dict[str, Any]) -> Optional[str]:
        ep = str(endpoint or "").strip().lower()
        if ep not in {"option_snapshot", "option_timeseries"}:
            return None

        cache_req = dict(request)
        cache_req.pop("show_tqdm", None)
        cache_req.pop("force_refresh", None)
        symbols_raw = cache_req.get("symbols") or cache_req.get("tickers") or []
        as_of_for_symbols: Optional[datetime.date] = None

        if ep == "option_snapshot":
            ts = cache_req.get("timestamp", "live")
            if isinstance(ts, str) and ts.strip().lower() == "live":
                # Avoid stale caches for live snapshots unless explicitly opted in.
                if not self.cache_full_intraday_fetch:
                    return None
                live_bucket = datetime.datetime.now(_NY_TZ).replace(second=0, microsecond=0)
                cache_req["timestamp"] = live_bucket
            else:
                as_of_for_symbols = _as_date(ts)
                cache_req["timestamp"] = as_of_for_symbols

        if ep == "option_timeseries":
            if "start" in cache_req:
                cache_req["start"] = _as_date(cache_req["start"])
            if "end" in cache_req:
                cache_req["end"] = _as_date(cache_req["end"])
            as_of_for_symbols = cache_req.get("start")

        if symbols_raw:
            cache_req["symbol_specs"] = self._normalize_symbols_for_cache(symbols=symbols_raw, as_of=as_of_for_symbols)
        cache_req.pop("symbols", None)
        cache_req.pop("tickers", None)

        payload = {
            "schema": 1,
            "cache_version": "USTFO_GET_DATA_v3",
            "source": str(self.source).upper(),
            "endpoint": ep,
            "request": self._cache_primitive(cache_req),
        }
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(payload_str.encode("utf-8")).hexdigest()
        return f"USTFO_GET_DATA::{ep}::{digest}"

    def _serialize_pricer(self, pr: QLUSTFutureOptionPricer) -> Dict[str, Any]:
        return {
            "symbol": pr.symbol(),
            "right": pr.right(),
            "underlying_symbol": pr.underlying_symbol(),
            "strike": pr.strike(),
            "quote_timestamp": pr.quote_timestamp(),
            "expiry_date": pr.expiry_date(),
            "market_price": pr.price(),
            "model_price": pr.model_price(),
            "iv_normal": pr.iv_normal(),
            "delta": pr.delta(),
            "gamma": pr.gamma(),
            "vega": pr.vega(),
            "theta": pr.theta(),
            "forward": pr.forward(),
            "discount": pr.discount(),
            "fv01": pr.fv01(),
            "meta_data": pr.meta(),
        }

    def _deserialize_pricer(self, row: Dict[str, Any]) -> QLUSTFutureOptionPricer:
        quote_ts = row.get("quote_timestamp")
        if isinstance(quote_ts, pd.Timestamp):
            quote_ts = quote_ts.to_pydatetime()
        elif isinstance(quote_ts, str):
            quote_ts = pd.Timestamp(quote_ts).to_pydatetime()
        if not isinstance(quote_ts, datetime.datetime):
            raise ValueError(f"Invalid cached quote_timestamp: {quote_ts!r}")

        expiry = row.get("expiry_date")
        if isinstance(expiry, pd.Timestamp):
            expiry = expiry.date()
        elif isinstance(expiry, str):
            expiry = datetime.date.fromisoformat(expiry)
        if not isinstance(expiry, datetime.date):
            raise ValueError(f"Invalid cached expiry_date: {expiry!r}")

        fv01_raw = row.get("fv01")
        fv01 = float(fv01_raw) if fv01_raw is not None else float("nan")

        return QLUSTFutureOptionPricer(
            symbol=str(row["symbol"]),
            right=str(row["right"]),
            underlying_symbol=str(row["underlying_symbol"]),
            strike=float(row["strike"]),
            quote_timestamp=quote_ts,
            expiry_date=expiry,
            market_price=float(row["market_price"]),
            model_price=float(row["model_price"]),
            iv_normal=float(row["iv_normal"]),
            delta=float(row["delta"]),
            gamma=float(row["gamma"]),
            vega=float(row["vega"]),
            theta=float(row["theta"]),
            forward=float(row["forward"]),
            discount=float(row["discount"]),
            fv01=fv01,
            meta_data=row.get("meta_data") or {},
        )

    def _serialize_get_data_result(self, endpoint: str, result: Dict[str, List[QLUSTFutureOptionPricer]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for k, plist in result.items():
            payload[str(k)] = [self._serialize_pricer(p) for p in plist]
        return {"schema": 1, "endpoint": endpoint, "result": payload}

    def _deserialize_get_data_result(self, cached: Dict[str, Any]) -> Optional[Dict[str, List[QLUSTFutureOptionPricer]]]:
        if not isinstance(cached, dict):
            return None
        if int(cached.get("schema", 0)) != 1:
            return None
        result_raw = cached.get("result")
        if not isinstance(result_raw, dict):
            return None
        out: Dict[str, List[QLUSTFutureOptionPricer]] = {}
        try:
            for k, plist in result_raw.items():
                if not isinstance(plist, list):
                    continue
                out[str(k)] = [self._deserialize_pricer(p) for p in plist if isinstance(p, dict)]
        except Exception:
            return None
        return out

    def _assert_endpoint_allowed(self, endpoint: str) -> None:
        src = self.source.upper()
        ep = endpoint.strip().lower()
        if src in {"USTFO_DUAL-QL", "BARCHART_USTFO-QL"} and ep in {"option_snapshot", "option_timeseries"}:
            return
        raise NotImplementedError(f"Endpoint '{endpoint}' is not available for source '{self.source}'")

    def _bounded_session_token_pool_size(self, concurrency: Optional[int]) -> int:
        if concurrency is None:
            target = 1
        else:
            target = max(1, int(concurrency))
        return min(target, int(self._barchart_session_token_pool_size_cap))

    def _get_cached_barchart_proxy(self) -> Tuple[Optional[dict], Optional[str]]:
        S = USTFutureOptionMDP._BARCHART_STATE
        if time.time() - float(S["chosen_at"]) < float(S["ttl"]):
            return S["proxies"], S["host"]
        return None, None

    def _choose_barchart_proxy(self) -> Tuple[Optional[dict], Optional[str]]:
        S = USTFutureOptionMDP._BARCHART_STATE
        cycler = S["cycler"]
        for _ in range(len(self._barchart_proxy_hosts)):
            host = next(cycler)
            if host is None:
                return None, None
            if not self._socksio_enabled:
                continue
            try:
                proxies = _build_socks5h(host)
            except Exception:
                continue
            if _preflight_proxy(proxies):
                return proxies, host
        return None, None

    def _get_barchart_fetcher(self, *, required_concurrency: Optional[int] = None) -> BarchartFetcher:
        desired_pool_size = self._bounded_session_token_pool_size(required_concurrency)

        def _safe_close(fetcher: Optional[BarchartFetcher]) -> None:
            if fetcher is None:
                return
            try:
                fetcher.close()
            except Exception:
                pass

        # Explicit static proxy path (caller-provided).
        if self._barchart_proxies_static is not None:
            with self._barchart_lock:
                if self._barchart_fetcher is None:
                    self._barchart_fetcher = BarchartFetcher(
                        proxies=self._barchart_proxies_static,
                        debug_verbose=False,
                        error_verbose=True,
                        session_token_ttl_seconds=max(1, int(self._barchart_proxy_ttl)),
                        session_token_pool_size=desired_pool_size,
                        session_token_scope=f"{self.__class__.__name__}:static",
                    )
                else:
                    self._barchart_fetcher._session_token_pool_size = desired_pool_size
                try:
                    self._barchart_fetcher._fetch_session_tokens(dummy_symbol="BTC")
                except Exception:
                    pass
                return self._barchart_fetcher

        # Rotating sticky proxy path (same pattern as STIRFutureMDP).
        S = USTFutureOptionMDP._BARCHART_STATE
        with S["lock"]:
            def _build_fetcher(fetcher_proxies: Optional[dict], fetcher_host: Optional[str]) -> BarchartFetcher:
                scope_host = fetcher_host if fetcher_host is not None else "direct"
                return BarchartFetcher(
                    proxies=fetcher_proxies,
                    debug_verbose=False,
                    error_verbose=True,
                    session_token_ttl_seconds=max(1, int(S["ttl"])),
                    session_token_pool_size=desired_pool_size,
                    session_token_scope=f"{self.__class__.__name__}:{scope_host}",
                )

            proxies, host = self._get_cached_barchart_proxy()
            if proxies is None and host is None:
                _safe_close(S.get("fetcher"))
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                S["fetcher"] = None

            bcf = S["fetcher"]
            if bcf is None:
                bcf = _build_fetcher(proxies, host)
                S["fetcher"] = bcf
            else:
                bcf._session_token_pool_size = desired_pool_size

            try:
                bcf._fetch_session_tokens(dummy_symbol="BTC")
            except Exception:
                _safe_close(S.get("fetcher"))
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                bcf = _build_fetcher(proxies, host)
                S["fetcher"] = bcf
                bcf._fetch_session_tokens(dummy_symbol="BTC")

            return bcf

    def _get_curve_builder(self) -> BARCHART_STIRF_CURVE:
        S = USTFutureOptionMDP._CURVE_STATE
        with S["lock"]:
            if S["builder"] is None:
                S["builder"] = BARCHART_STIRF_CURVE()
            return S["builder"]

    def _curve_timestamp_for_request(self, ts_like: DateLike) -> datetime.datetime:
        d = _as_date(ts_like)
        return _NY_TZ.localize(datetime.datetime.combine(d, datetime.time(hour=17, minute=0)))

    def _compute_fv01(
        self,
        underlying_contract: str,
        forward: float,
        as_of: datetime.date,
    ) -> float:
        """Compute the forward DV01 per bp of the underlying futures contract.

        FV01 = DV01_CTD / CF_CTD, i.e. the change in futures price for a 1 bp
        parallel yield shift on the cheapest-to-deliver bond.
        """
        internal_underlying = _to_internal_ustf_contract(underlying_contract, as_of=as_of)
        memo_key = f"{internal_underlying}|{as_of.isoformat()}"
        cached = self._fv01_memo.get(memo_key)
        if cached is not None:
            return cached

        fallback_fv01 = _fv01_fallback_for_contract(internal_underlying)
        fv01 = fallback_fv01

        try:
            ust_mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
            with ust_mdp:
                basket_data = ust_mdp.get_delivery_basket(
                    as_of=as_of,
                    symbol=internal_underlying,
                )

            basket_pricers = basket_data["basket_pricers"]
            cfs = basket_data["conversion_factors"]
            delivery_raw = basket_data["delivery"]
            if isinstance(delivery_raw, tuple) and len(delivery_raw) == 2:
                d0, d1 = delivery_raw
                if isinstance(d0, datetime.date) and not isinstance(d0, datetime.datetime):
                    d0 = datetime.datetime.combine(d0, datetime.time())
                if isinstance(d1, datetime.date) and not isinstance(d1, datetime.datetime):
                    d1 = datetime.datetime.combine(d1, datetime.time())
                delivery = (d0, d1)
            else:
                delivery = delivery_raw

            bf = rl.BondFuture(
                delivery=delivery,
                basket=[pr.build_pricable() for pr in basket_pricers],
                coupon=basket_data["contract_coupon"],
                currency="usd",
                calc_mode=basket_data["calc_mode"],
            )
            prices = [pr.clean_price() for pr in basket_pricers]
            settlement = basket_pricers[0].settlement_date()
            if isinstance(settlement, datetime.date) and not isinstance(settlement, datetime.datetime):
                settlement = datetime.datetime.combine(settlement, datetime.time())
            ctd_idx = int(
                bf.ctd_index(future_price=forward, prices=prices, settlement=settlement)
            )
            ctd = basket_pricers[ctd_idx]
            cf_ctd = float(cfs[ctd_idx])
            if not math.isfinite(cf_ctd) or cf_ctd <= 0.0:
                raise ValueError(f"Invalid CTD conversion factor for {internal_underlying}: {cf_ctd}")

            moddur = float(ctd.mod_duration())
            dirty_px = _to_float(ctd.dirty_price())
            if dirty_px is None or dirty_px <= 0.0:
                dirty_px = _to_float(ctd.clean_price())

            if dirty_px is None or not math.isfinite(moddur) or not math.isfinite(dirty_px):
                raise ValueError(
                    f"Invalid CTD risk inputs for {internal_underlying}: moddur={moddur}, dirty_px={dirty_px}"
                )

            fv01_calc = moddur * dirty_px / 10000.0 / cf_ctd
            if math.isfinite(fv01_calc) and fv01_calc > 0.0:
                fv01 = float(fv01_calc)
        except Exception:
            fv01 = fallback_fv01

        self._fv01_memo[memo_key] = fv01
        return fv01

    def _discount_factor(
        self,
        *,
        valuation_ts: datetime.datetime,
        expiry_date: datetime.date,
        curve_name: str,
        curve_kwargs: Optional[Dict[str, Any]],
        memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]],
    ) -> Tuple[float, Optional[str]]:
        vdate = valuation_ts.astimezone(_NY_TZ).date()
        if expiry_date <= vdate:
            return 1.0, None

        memo_key = (curve_name, vdate)
        curve_obj = None
        curve_err = None
        if memo_key in memo:
            curve_obj, curve_err = memo[memo_key]
        else:
            try:
                builder = self._get_curve_builder()
                ts_curve = self._curve_timestamp_for_request(vdate)
                kwargs = dict(curve_kwargs or {})
                curve_obj = builder.build_curve(
                    curve_name=curve_name,
                    timestamp=ts_curve,
                    kwargs=kwargs,
                    curve_only=True,
                )
            except Exception as exc:
                curve_obj = None
                curve_err = str(exc)
            memo[memo_key] = (curve_obj, curve_err)

        if curve_obj is None:
            return 1.0, curve_err

        try:
            df = float(curve_obj[rl.dt(expiry_date.year, expiry_date.month, expiry_date.day)])
            if not math.isfinite(df) or df <= 0.0:
                return 1.0, "invalid discount factor from curve"
            return df, curve_err
        except Exception as exc:
            return 1.0, str(exc)

    def _fetch_barchart_eod_series(
        self,
        *,
        symbols: List[str],
        start: datetime.date,
        end: datetime.date,
        show_tqdm: bool,
        max_concurrent_tasks: Optional[int] = None,
        max_keepalive_connections: Optional[int] = None,
    ) -> Dict[str, pd.DataFrame]:
        start_dt = datetime.datetime.combine(start, datetime.time(0, 0))
        end_dt = datetime.datetime.combine(end, datetime.time(23, 59))
        mc = int(max_concurrent_tasks or min(max(len(symbols), 1), 32))
        mk = int(max_keepalive_connections or min(max(len(symbols), 1), 32))
        bcf = self._get_barchart_fetcher(required_concurrency=mc)
        out = bcf.barchart_timeseries_api(
            barchart_symbols=symbols,
            start_date=start_dt,
            end_date=end_dt,
            interval=None,
            one_df=False,
            show_tqdm=show_tqdm,
            max_concurrent_tasks=mc,
            max_keepalive_connections=mk,
        )
        return out if isinstance(out, dict) else {}

    def _fetch_barchart_intraday_prices(
        self,
        *,
        contracts: List[str],
        timestamp: datetime.datetime,
        window_minutes: int,
        show_tqdm: bool,
    ) -> Dict[str, float]:
        if not contracts:
            return {}
        mc = min(max(len(contracts), 1), 24)
        bcf = self._get_barchart_fetcher(required_concurrency=mc)
        ts_chi = timestamp.astimezone(_CHI_TZ)
        start = ts_chi - datetime.timedelta(minutes=window_minutes)
        end = ts_chi + datetime.timedelta(minutes=window_minutes)
        out = bcf.barchart_timeseries_api(
            barchart_symbols=contracts,
            start_date=start,
            end_date=end,
            interval=1,
            one_df=False,
            show_tqdm=show_tqdm,
            max_concurrent_tasks=mc,
            max_keepalive_connections=mc,
        )
        if not isinstance(out, dict):
            return {}

        px: Dict[str, float] = {}
        target = pd.Timestamp(timestamp)
        for sym, df in out.items():
            if df is None or df.empty:
                continue
            idx = _nearest_index_position(df.index, target)
            if idx is None:
                continue
            row = df.iloc[idx]
            val = _extract_row_price(row.to_dict(), price_mode="mid_then_fallback")
            if val is not None and val > 0.0:
                px[sym] = float(val)
        return px

    def _build_pricers_from_eod_window(
        self,
        *,
        leg_symbols: List[str],
        data: Dict[str, pd.DataFrame],
        window_start: datetime.date,
        window_end: datetime.date,
        price_mode: str,
        curve_name: str,
        curve_kwargs: Optional[Dict[str, Any]],
        use_ql_calculator: bool,
        source: str,
    ) -> Dict[str, Dict[datetime.date, QLUSTFutureOptionPricer]]:
        curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]] = {}
        out: Dict[str, Dict[datetime.date, QLUSTFutureOptionPricer]] = defaultdict(dict)

        for leg_symbol in leg_symbols:
            opt_bc = _canonical_to_barchart_option(leg_symbol)
            fut_bc = _contract_to_barchart_contract(_canonical_underlying(leg_symbol))
            opt_df = data.get(opt_bc)
            fut_df = data.get(fut_bc)
            if opt_df is None or opt_df.empty or fut_df is None or fut_df.empty:
                continue

            for row_dt, row_series in opt_df.iterrows():
                row_day = pd.Timestamp(row_dt).date()
                if row_day < window_start or row_day > window_end:
                    continue

                forward = self._resolve_underlying_forward_for_eod_row(
                    underlying_df=fut_df,
                    row_dt=pd.Timestamp(row_dt),
                    price_mode=price_mode,
                )
                if forward is None or forward <= 0.0:
                    continue

                val_ts = _NY_TZ.localize(datetime.datetime.combine(row_day, datetime.time(17, 0)))
                pr = self._build_pricer_from_row(
                    canonical_symbol=leg_symbol,
                    row=dict(row_series.to_dict()),
                    valuation_ts=val_ts,
                    forward=forward,
                    curve_name=curve_name,
                    curve_kwargs=curve_kwargs,
                    curve_memo=curve_memo,
                    price_mode=price_mode,
                    source=source,
                    use_ql_calculator=use_ql_calculator,
                )
                if pr is not None:
                    out[leg_symbol][row_day] = pr

        return dict(out)

    def _get_or_build_barchart_pricer_window(
        self,
        *,
        leg_symbols: List[str],
        cache_symbols: Optional[List[str]] = None,
        request_start: datetime.date,
        request_end: datetime.date,
        show_tqdm: bool,
        price_mode: str,
        curve_name: str,
        curve_kwargs: Optional[Dict[str, Any]],
        use_ql_calculator: bool,
        source: str,
        force_refresh: bool = False,
    ) -> Dict[str, Dict[datetime.date, QLUSTFutureOptionPricer]]:
        window_start, window_end = self._historical_prefetch_window(start=request_start, end=request_end)
        key_symbols = list(cache_symbols) if cache_symbols is not None else list(leg_symbols)
        cache_key = self._build_barchart_pricer_window_cache_key(
            leg_symbols=key_symbols,
            window_start=window_start,
            window_end=window_end,
            price_mode=price_mode,
            curve_name=curve_name,
            curve_kwargs=curve_kwargs or {},
            use_ql_calculator=use_ql_calculator,
        )

        if not force_refresh:
            cached = self._threadsafe_cache_get(cache_key)
            hit = self._deserialize_pricer_window(cached)
            if hit is not None:
                return hit

        option_symbols_bc = sorted({_canonical_to_barchart_option(sym) for sym in leg_symbols})
        contracts = sorted({_contract_to_barchart_contract(_canonical_underlying(sym)) for sym in leg_symbols})
        all_syms = option_symbols_bc + contracts
        data = self._fetch_barchart_eod_series(
            symbols=all_syms,
            start=window_start,
            end=window_end,
            show_tqdm=show_tqdm,
        )

        built = self._build_pricers_from_eod_window(
            leg_symbols=leg_symbols,
            data=data,
            window_start=window_start,
            window_end=window_end,
            price_mode=price_mode,
            curve_name=curve_name,
            curve_kwargs=curve_kwargs,
            use_ql_calculator=use_ql_calculator,
            source=source,
        )
        self._threadsafe_cache_put(cache_key, self._serialize_pricer_window(built))
        return built

    @staticmethod
    def _asof_pricer_for_date(
        by_day: Dict[datetime.date, QLUSTFutureOptionPricer],
        target_date: datetime.date,
    ) -> Optional[QLUSTFutureOptionPricer]:
        if not by_day:
            return None
        keys = [d for d in by_day.keys() if d <= target_date]
        if not keys:
            return None
        return by_day[max(keys)]

    def _build_pricer_from_row(
        self,
        *,
        canonical_symbol: str,
        row: Dict[str, Any],
        valuation_ts: datetime.datetime,
        forward: float,
        curve_name: str,
        curve_kwargs: Optional[Dict[str, Any]],
        curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]],
        price_mode: str,
        source: str,
        use_ql_calculator: bool = False,
    ) -> Optional[QLUSTFutureOptionPricer]:
        right = _right_from_symbol(canonical_symbol)
        if right not in {"C", "P"}:
            return None

        strike = _strike_from_symbol(canonical_symbol)
        contract_code = _contract_code_from_symbol(canonical_symbol)
        expiry = option_expiry_date(_canonical_contract(canonical_symbol))
        tte = _time_to_expiry(valuation_ts.astimezone(_NY_TZ).date(), expiry)

        market_price = _extract_row_price(row, price_mode=price_mode)
        if market_price is None or market_price <= 0.0:
            return None

        discount, curve_error = self._discount_factor(
            valuation_ts=valuation_ts,
            expiry_date=expiry,
            curve_name=curve_name,
            curve_kwargs=curve_kwargs,
            memo=curve_memo,
        )

        iv_normal = _implied_normal_vol(right, strike, forward, tte, market_price, discount)
        if math.isnan(iv_normal) or iv_normal <= 0.0:
            model_price = float("nan")
            delta = gamma = vega = theta = float("nan")
        else:
            model_price = _bachelier_price(right, strike, forward, iv_normal, tte, discount)
            delta, gamma, vega, theta = _bachelier_greeks_fd(
                right=right,
                strike=strike,
                forward=forward,
                vol_normal=iv_normal,
                tte=tte,
                discount=discount,
                use_ql_calculator=use_ql_calculator,
            )

        vendor_iv = _to_float(row.get("optImpliedVolatility", row.get("impliedVolatility", row.get("impliedVolatilitySkew"))))
        vendor_delta = _to_float(row.get("delta", row.get("Delta")))
        vendor_gamma = _to_float(row.get("gamma", row.get("Gamma")))
        vendor_vega = _to_float(row.get("vega", row.get("Vega")))
        vendor_theta = _to_float(row.get("theta", row.get("Theta")))

        metadata = {
            "schema": 1,
            "source": source,
            "symbol": canonical_symbol,
            "underlying_symbol": _canonical_underlying(canonical_symbol),
            "contract_code": contract_code,
            "expiry_date": expiry.isoformat(),
            "tte": float(tte),
            "curve_name": curve_name,
            "curve_error": curve_error,
            "discount": float(discount),
            "greeks_method": "ql_bachelier_calculator" if use_ql_calculator else "finite_diff",
            "vendor_iv": vendor_iv,
            "vendor_delta": vendor_delta,
            "vendor_gamma": vendor_gamma,
            "vendor_vega": vendor_vega,
            "vendor_theta": vendor_theta,
            "vendor_row": dict(row),
        }

        underlying = _canonical_underlying(canonical_symbol)
        fv01 = self._compute_fv01(
            underlying, forward, valuation_ts.astimezone(_NY_TZ).date()
        )
        metadata["fv01"] = float(fv01)
        metadata["iv_normal_bps"] = float(iv_normal / fv01) if (math.isfinite(iv_normal) and fv01 > 0.0) else float("nan")

        return QLUSTFutureOptionPricer(
            symbol=canonical_symbol,
            right=right,
            underlying_symbol=underlying,
            strike=strike,
            quote_timestamp=valuation_ts,
            expiry_date=expiry,
            market_price=float(market_price),
            model_price=float(model_price) if model_price == model_price else float("nan"),
            iv_normal=float(iv_normal) if iv_normal == iv_normal else float("nan"),
            delta=float(delta) if delta == delta else float("nan"),
            gamma=float(gamma) if gamma == gamma else float("nan"),
            vega=float(vega) if vega == vega else float("nan"),
            theta=float(theta) if theta == theta else float("nan"),
            forward=float(forward),
            discount=float(discount),
            fv01=float(fv01),
            meta_data=metadata,
        )

    def _synthesize_straddle(
        self,
        *,
        straddle_symbol: str,
        call_pricer: QLUSTFutureOptionPricer,
        put_pricer: QLUSTFutureOptionPricer,
    ) -> QLUSTFutureOptionPricer:
        total_vega = 0.0
        weighted_iv = 0.0
        for pr in (call_pricer, put_pricer):
            if math.isfinite(pr.iv_normal()) and math.isfinite(pr.vega()):
                v = abs(pr.vega())
                total_vega += v
                weighted_iv += v * pr.iv_normal()
        if total_vega > 0.0:
            iv = weighted_iv / total_vega
        else:
            vals = [v for v in [call_pricer.iv_normal(), put_pricer.iv_normal()] if math.isfinite(v)]
            iv = float(sum(vals) / len(vals)) if vals else float("nan")

        metadata = {
            "schema": 1,
            "source": "SYNTH_STRADDLE",
            "symbol": straddle_symbol,
            "underlying_symbol": call_pricer.underlying_symbol(),
            "legs": [call_pricer.id(), put_pricer.id()],
            "curve_name": call_pricer.meta().get("curve_name"),
            "curve_error": call_pricer.meta().get("curve_error") or put_pricer.meta().get("curve_error"),
            "vendor_legs": [call_pricer.meta().get("vendor_row"), put_pricer.meta().get("vendor_row")],
        }

        # Propagate fv01 from the legs (same underlying, so identical).
        fv01 = call_pricer.fv01() if math.isfinite(call_pricer.fv01()) else put_pricer.fv01()

        return QLUSTFutureOptionPricer(
            symbol=straddle_symbol,
            right="S",
            underlying_symbol=call_pricer.underlying_symbol(),
            strike=call_pricer.strike(),
            quote_timestamp=max(call_pricer.quote_timestamp(), put_pricer.quote_timestamp()),
            expiry_date=call_pricer.expiry_date(),
            market_price=call_pricer.price() + put_pricer.price(),
            model_price=call_pricer.model_price() + put_pricer.model_price(),
            iv_normal=iv,
            delta=call_pricer.delta() + put_pricer.delta(),
            gamma=call_pricer.gamma() + put_pricer.gamma(),
            vega=call_pricer.vega() + put_pricer.vega(),
            theta=call_pricer.theta() + put_pricer.theta(),
            forward=call_pricer.forward(),
            discount=min(call_pricer.discount(), put_pricer.discount()),
            fv01=float(fv01),
            meta_data=metadata,
        )

    def _extract_live_option_row(
        self,
        *,
        chain: Dict[str, pd.DataFrame],
        contract: str,
        strike: float,
        right: str,
    ) -> Optional[Dict[str, Any]]:
        side = "call" if right == "C" else "put"
        df = chain.get(side)
        if df is None or df.empty:
            return None

        df_work = df.copy()
        if "strikePrice" in df_work.columns:
            df_work["strikePrice"] = pd.to_numeric(df_work["strikePrice"], errors="coerce")
            mask = (df_work["strikePrice"] - strike).abs() < 1e-9
            if mask.any():
                return dict(df_work.loc[mask].iloc[0].to_dict())

        if "symbol" in df_work.columns:
            right_tok = str(right).upper()
            for _, row in df_work.iterrows():
                raw_symbol = str(row.get("symbol", "")).strip().upper().replace("/", "")
                if "|" not in raw_symbol or not raw_symbol.endswith(right_tok):
                    continue
                try:
                    opt_contract, tail = raw_symbol.split("|", 1)
                    strike_token = tail[:-1]
                    norm_contract = normalize_option_contract(opt_contract)
                    if norm_contract != normalize_option_contract(contract):
                        continue
                    decoded = decode_strike_token(contract_or_root=norm_contract, strike_token=strike_token)
                    if abs(float(decoded) - float(strike)) < 1e-9:
                        return dict(row.to_dict())
                except Exception:
                    continue

        return None

    def _live_chain_strikes(self, chain: Dict[str, pd.DataFrame], side: str) -> List[float]:
        df = chain.get(side)
        if df is None or df.empty or "strikePrice" not in df.columns:
            return []
        vals = pd.to_numeric(df["strikePrice"], errors="coerce").dropna()
        if vals.empty:
            return []
        return sorted(float(x) for x in vals.unique())

    def _live_chain_listed_symbols(
        self,
        chain: Dict[str, pd.DataFrame],
        side: str,
    ) -> List[Tuple[float, str]]:
        df = chain.get(side)
        if df is None or df.empty:
            return []

        work = df.copy()
        if "strikePrice" not in work.columns or "symbol" not in work.columns:
            return []
        work["strikePrice"] = pd.to_numeric(work["strikePrice"], errors="coerce")
        work["symbol"] = work["symbol"].astype(str)
        work = work.dropna(subset=["strikePrice"])
        if work.empty:
            return []

        out: List[Tuple[float, str]] = []
        seen = set()
        for _, row in work.iterrows():
            strike = float(row["strikePrice"])
            symbol = str(row["symbol"]).upper()
            if "|" not in symbol:
                continue
            if symbol in seen:
                continue
            seen.add(symbol)
            out.append((strike, symbol))
        out.sort(key=lambda x: x[0])
        return out

    def _resolve_live_atm_strike(self, *, chain: Dict[str, pd.DataFrame], forward: float, right: str) -> Optional[float]:
        r = str(right).upper()
        if r == "C":
            strikes = self._live_chain_strikes(chain, "call")
        elif r == "P":
            strikes = self._live_chain_strikes(chain, "put")
        elif r == "S":
            c = set(self._live_chain_strikes(chain, "call"))
            p = set(self._live_chain_strikes(chain, "put"))
            strikes = sorted(c.intersection(p))
        else:
            return None

        if not strikes:
            return None
        return min(strikes, key=lambda k: abs(float(k) - float(forward)))

    def _resolve_live_delta_strike(self, *, chain: Dict[str, pd.DataFrame], target_delta: float, right: str) -> Optional[float]:
        r = str(right).upper()
        side = "call" if r == "C" else "put"
        df = chain.get(side)
        if df is None or df.empty:
            return None
        if "delta" not in df.columns or "strikePrice" not in df.columns:
            return None

        work = df.copy()
        work["strikePrice"] = pd.to_numeric(work["strikePrice"], errors="coerce")
        work["delta_norm"] = work["delta"].apply(_normalize_vendor_delta)
        work = work.dropna(subset=["strikePrice", "delta_norm"])
        if work.empty:
            return None

        target = float(target_delta) / 100.0
        if r == "C":
            work["delta_error"] = (work["delta_norm"] - target).abs()
        else:
            work["delta_error"] = work.apply(
                lambda row: min(abs(row["delta_norm"] + target), abs(abs(row["delta_norm"]) - target)),
                axis=1,
            )

        row = work.sort_values(["delta_error", "strikePrice"], ascending=[True, True]).iloc[0]
        return float(row["strikePrice"])

    @staticmethod
    def _pick_centered_strike_slice(strikes: List[float], *, center: float, half_width: int) -> List[float]:
        if not strikes:
            return []
        if len(strikes) <= (2 * half_width + 1):
            return list(strikes)
        center_idx = min(range(len(strikes)), key=lambda i: abs(float(strikes[i]) - float(center)))
        lo = max(0, center_idx - half_width)
        hi = min(len(strikes), center_idx + half_width + 1)
        return list(strikes[lo:hi])

    def _resolve_historical_delta_from_pricers(
        self,
        *,
        candidate_symbols: List[str],
        pricers_window: Dict[str, Dict[datetime.date, QLUSTFutureOptionPricer]],
        target_date: datetime.date,
        target_delta: float,
        right: str,
        forward: float,
    ) -> Optional[str]:
        target = float(target_delta) / 100.0
        best: Optional[Tuple[float, float, str]] = None  # (delta_error, strike_dist, symbol)

        for sym in candidate_symbols:
            by_day = pricers_window.get(sym, {})
            pr = self._asof_pricer_for_date(by_day, target_date)
            if pr is None:
                continue
            delta_val = _to_float(pr.delta())
            if delta_val is None or not math.isfinite(delta_val):
                continue
            strike_val = _strike_from_symbol(sym)
            if right == "C":
                err = abs(float(delta_val) - target)
            else:
                err = min(abs(float(delta_val) + target), abs(abs(float(delta_val)) - target))
            dist = abs(float(strike_val) - float(forward))
            if best is None or err < best[0] or (abs(err - best[0]) < 1e-12 and dist < best[1]):
                best = (err, dist, sym)

        if best is None:
            return None
        return best[2]

    def _resolve_snapshot_requested_symbols_live(
        self,
        *,
        requested_specs: "OrderedDict[str, Dict[str, Any]]",
        chains: Dict[str, Dict[str, pd.DataFrame]],
        forward_map: Dict[str, float],
    ) -> "OrderedDict[str, str]":
        resolved: "OrderedDict[str, str]" = OrderedDict()

        for raw, spec in requested_specs.items():
            selector = str(spec["selector"])
            contract = str(spec["contract"])
            right = str(spec["right"]).upper()
            if selector == "strike":
                resolved[raw] = str(spec["canonical"])
                continue

            option_bcontract = _contract_to_barchart_contract(contract)
            underlying_contract = _option_contract_to_underlying_contract(contract)
            underlying_bcontract = _contract_to_barchart_contract(underlying_contract)
            chain = chains.get(option_bcontract)
            forward = _to_float(forward_map.get(underlying_bcontract))
            if chain is None or forward is None or forward <= 0.0:
                raise ValueError(f"Could not resolve alias {raw!r}: missing live chain/forward for {contract}")

            if selector == "atm":
                strike = self._resolve_live_atm_strike(chain=chain, forward=forward, right=right)
                if strike is None:
                    raise ValueError(f"Could not resolve ATM alias {raw!r}: no valid strikes in live chain.")
                resolved[raw] = f"{contract}|{_format_strike4(strike, contract=contract)}{right}"
                continue

            if selector == "delta":
                if right not in {"C", "P"}:
                    raise ValueError(f"Delta alias supports call/put only: {raw}")
                delta = _to_float(spec.get("delta"))
                if delta is None:
                    raise ValueError(f"Could not resolve delta alias {raw!r}: missing delta")
                strike = self._resolve_live_delta_strike(chain=chain, target_delta=delta, right=right)
                if strike is None:
                    raise ValueError(f"Could not resolve delta alias {raw!r}: no valid delta/strike rows.")
                resolved[raw] = f"{contract}|{_format_strike4(strike, contract=contract)}{right}"
                continue

            raise ValueError(f"Unsupported alias selector {selector!r} for symbol {raw!r}")

        return resolved

    def _resolve_snapshot_requested_symbols_historical(
        self,
        *,
        requested_specs: "OrderedDict[str, Dict[str, Any]]",
        target_date: datetime.date,
        underlying_data: Dict[str, pd.DataFrame],
        price_mode: str,
        atm_strike_step: float,
        show_tqdm: bool,
    ) -> "OrderedDict[str, str]":
        resolved: "OrderedDict[str, str]" = OrderedDict()
        target_ts = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(target_date, datetime.time(17, 0))))

        for raw, spec in requested_specs.items():
            selector = str(spec["selector"])
            contract = str(spec["contract"])
            right = str(spec["right"]).upper()
            if selector == "strike":
                resolved[raw] = str(spec["canonical"])
                continue

            if selector == "delta":
                raise ValueError(
                    f"Historical delta alias {raw!r} must be resolved from a prebuilt pricer window. "
                    "Callers should resolve delta after fetching window pricers."
                )

            if selector != "atm":
                raise ValueError(f"Unsupported alias selector {selector!r} for symbol {raw!r}")

            underlying_contract = _option_contract_to_underlying_contract(contract)
            bcontract = _contract_to_barchart_contract(underlying_contract)
            fut_df = underlying_data.get(bcontract)
            if fut_df is None or fut_df.empty:
                raise ValueError(f"Could not resolve ATM alias {raw!r}: missing underlying history for {contract}.")

            pos = _asof_index_position(fut_df.index, target_ts)
            if pos is None:
                raise ValueError(f"Could not resolve ATM alias {raw!r}: no underlying row near {target_date}.")
            forward = _extract_row_price(fut_df.iloc[pos].to_dict(), price_mode=price_mode)
            if forward is None or forward <= 0.0:
                raise ValueError(f"Could not resolve ATM alias {raw!r}: invalid underlying forward.")

            step = _strike_step_for_contract(contract) if atm_strike_step <= 0.0 else atm_strike_step
            atm_strike = _atm_strike_from_forward(float(forward), step=step)
            resolved[raw] = f"{contract}|{_format_strike4(atm_strike, contract=contract)}{right}"

        return resolved

    def _resolve_underlying_forward_for_eod_row(
        self,
        *,
        underlying_df: pd.DataFrame,
        row_dt: pd.Timestamp,
        price_mode: str,
    ) -> Optional[float]:
        if underlying_df is None or underlying_df.empty:
            return None
        pos = _asof_index_position(underlying_df.index, row_dt)
        if pos is None:
            return None
        return _extract_row_price(underlying_df.iloc[pos].to_dict(), price_mode=price_mode)

    @staticmethod
    def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for item in items:
            tok = str(item or "").strip()
            if not tok or tok in seen:
                continue
            seen.add(tok)
            out.append(tok)
        return out

    def _contracts_for_spec_window(
        self,
        *,
        spec: Dict[str, Any],
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> List[str]:
        selector = str(spec.get("contract_selector", "explicit"))
        if selector == "explicit":
            contract = spec.get("contract")
            if not contract:
                raise ValueError(f"Missing explicit contract in spec: {spec}")
            return [str(contract)]

        raise ValueError(f"Unsupported contract selector for historical window fetch: {selector}")

    def _historical_atm_symbols_for_contract_window(
        self,
        *,
        contract: str,
        right: str,
        underlying_data: Dict[str, pd.DataFrame],
        window_start: datetime.date,
        window_end: datetime.date,
        price_mode: str,
        atm_strike_step: float,
    ) -> List[str]:
        underlying_contract = _option_contract_to_underlying_contract(contract)
        bcontract = _contract_to_barchart_contract(underlying_contract)
        fut_df = underlying_data.get(bcontract)
        if fut_df is None or fut_df.empty:
            return []

        out: List[str] = []
        for row_dt, row in fut_df.iterrows():
            row_day = pd.Timestamp(row_dt).date()
            if row_day < window_start or row_day > window_end:
                continue
            forward = _extract_row_price(row.to_dict(), price_mode=price_mode)
            if forward is None or forward <= 0.0:
                continue
            step = _strike_step_for_contract(contract) if atm_strike_step <= 0.0 else atm_strike_step
            atm_strike = _atm_strike_from_forward(float(forward), step=step)
            out.append(f"{contract}|{_format_strike4(atm_strike, contract=contract)}{right}")

        return self._dedupe_preserve_order(out)

    def _option_snapshot(self, request: Dict[str, Any]) -> Dict[str, List[QLUSTFutureOptionPricer]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        if not symbols:
            raise ValueError("option_snapshot requires symbols")

        ts = request.get("timestamp", "live")
        show_tqdm = bool(request.get("show_tqdm", False))
        price_mode = str(request.get("price_mode", "mid_then_fallback"))
        use_ql_calculator = bool(request.get("use_ql_calculator", False))
        window_minutes = int(request.get("window_minutes", 2))
        atm_strike_step = float(request.get("atm_strike_step", 0.0))
        bulk_timeseries = bool(request.get("bulk_timeseries", False))
        force_refresh = bool(request.get("force_refresh", False))
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})

        parsed_requested_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for raw in symbols:
            parsed_requested_specs[raw] = _parse_option_request_symbol(raw, as_of=_as_date(ts))
        requested_specs = _resolve_option_contract_aliases_for_date(parsed_requested_specs, as_of=_as_date(ts))

        requested: "OrderedDict[str, str]"
        cp_pricers: Dict[str, QLUSTFutureOptionPricer] = {}

        if str(ts).strip().lower() == "live":
            ts_dt = _as_datetime("live")
            option_contracts = sorted({_contract_to_barchart_contract(str(spec["contract"])) for spec in requested_specs.values()})
            underlying_contracts = sorted(
                {_contract_to_barchart_contract(_option_contract_to_underlying_contract(str(spec["contract"]))) for spec in requested_specs.values()}
            )
            chain_concurrency = min(max(len(option_contracts), 1), 32)
            bcf = self._get_barchart_fetcher(required_concurrency=chain_concurrency)
            chains = bcf.get_option_quotes(
                symbols=option_contracts,
                max_concurrent_tasks=chain_concurrency,
                max_keepalive_connections=min(max(len(option_contracts), 1), 16),
                show_tqdm=show_tqdm,
            )
            forward_map = self._fetch_barchart_intraday_prices(
                contracts=underlying_contracts,
                timestamp=ts_dt,
                window_minutes=window_minutes,
                show_tqdm=show_tqdm,
            )

            requested = self._resolve_snapshot_requested_symbols_live(
                requested_specs=requested_specs,
                chains=chains,
                forward_map=forward_map,
            )

            expanded_needed: "OrderedDict[str, str]" = OrderedDict()
            for norm in requested.values():
                for leg in _expand_straddle_symbol(norm):
                    expanded_needed[leg] = leg

            curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]] = {}

            for leg_symbol in expanded_needed:
                option_bcontract = _canonical_to_barchart_contract(leg_symbol)
                underlying_bcontract = _contract_to_barchart_contract(_canonical_underlying(leg_symbol))
                chain = chains.get(option_bcontract)
                if chain is None:
                    continue
                contract = _canonical_contract(leg_symbol)
                strike = _strike_from_symbol(leg_symbol)
                right = _right_from_symbol(leg_symbol)
                row = self._extract_live_option_row(chain=chain, contract=contract, strike=strike, right=right)
                if row is None:
                    continue
                forward = _to_float(forward_map.get(underlying_bcontract))
                if forward is None or forward <= 0.0:
                    continue
                quote_ts = ts_dt
                trade_time = _to_float(row.get("tradeTime"))
                if trade_time is not None and trade_time > 0:
                    try:
                        quote_ts = pd.to_datetime(int(trade_time), unit="s", utc=True).to_pydatetime()
                    except Exception:
                        quote_ts = ts_dt
                pr = self._build_pricer_from_row(
                    canonical_symbol=leg_symbol,
                    row=row,
                    valuation_ts=quote_ts,
                    forward=forward,
                    curve_name=curve_name,
                    curve_kwargs=curve_kwargs,
                    curve_memo=curve_memo,
                    price_mode=price_mode,
                    source="BARCHART_LIVE",
                    use_ql_calculator=use_ql_calculator,
                )
                if pr is not None:
                    cp_pricers[leg_symbol] = pr
        else:
            target_date = _as_date(ts)
            req_window_start_raw = request.get("window_start", target_date)
            req_window_end_raw = request.get("window_end", target_date)
            req_window_start = _as_date(req_window_start_raw)
            req_window_end = _as_date(req_window_end_raw)
            if req_window_end < req_window_start:
                raise ValueError(
                    f"option_snapshot requires window_end >= window_start; "
                    f"got {req_window_start.isoformat()}..{req_window_end.isoformat()}"
                )

            # Use caller-provided request window so timeseries TB can reuse one cached window across many dates.
            start, end = self._historical_prefetch_window(start=req_window_start, end=req_window_end)
            target_ts = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(target_date, datetime.time(17, 0))))
            delta_candidate_half_width = max(2, int(request.get("delta_candidate_half_width", 8)))

            contracts_by_raw: "OrderedDict[str, List[str]]" = OrderedDict()
            for raw, spec in parsed_requested_specs.items():
                if bulk_timeseries:
                    contracts = self._contracts_for_spec_window(
                        spec=spec,
                        window_start=req_window_start,
                        window_end=req_window_end,
                    )
                else:
                    contracts = [str(requested_specs[raw]["contract"])]
                contracts_by_raw[raw] = self._dedupe_preserve_order(contracts)

            underlying_contracts = sorted(
                {
                    _option_contract_to_underlying_contract(contract)
                    for contracts in contracts_by_raw.values()
                    for contract in contracts
                }
            )
            contract_symbols_bc = sorted(
                {_contract_to_barchart_contract(contract) for contract in underlying_contracts}
            )
            underlying_data = self._fetch_barchart_eod_series(
                symbols=contract_symbols_bc,
                start=start,
                end=end,
                show_tqdm=show_tqdm,
            )

            non_delta_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
            delta_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
            for raw, spec in requested_specs.items():
                if str(spec.get("selector")) == "delta":
                    delta_specs[raw] = spec
                else:
                    non_delta_specs[raw] = spec

            resolved_non_delta: "OrderedDict[str, str]" = OrderedDict()
            if non_delta_specs:
                resolved_non_delta = self._resolve_snapshot_requested_symbols_historical(
                    requested_specs=non_delta_specs,
                    target_date=target_date,
                    underlying_data=underlying_data,
                    price_mode=price_mode,
                    atm_strike_step=atm_strike_step,
                    show_tqdm=show_tqdm,
                )

            delta_meta: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
            delta_candidate_symbols: "OrderedDict[str, List[str]]" = OrderedDict()

            if delta_specs:
                option_contracts = sorted(
                    {
                        _contract_to_barchart_contract(contract)
                        for raw in delta_specs.keys()
                        for contract in contracts_by_raw.get(raw, [])
                    }
                )
                if option_contracts:
                    chain_concurrency = min(max(len(option_contracts), 1), 16)
                    bcf = self._get_barchart_fetcher(required_concurrency=chain_concurrency)
                    chains = bcf.get_option_quotes(
                        symbols=option_contracts,
                        max_concurrent_tasks=chain_concurrency,
                        max_keepalive_connections=min(max(len(option_contracts), 1), 16),
                        show_tqdm=show_tqdm,
                    )
                else:
                    chains = {}

                for raw, spec in delta_specs.items():
                    right = str(spec["right"]).upper()
                    if right not in {"C", "P"}:
                        raise ValueError(f"Historical delta alias supports call/put only: {raw!r}")
                    target_delta = _to_float(spec.get("delta"))
                    if target_delta is None:
                        raise ValueError(f"Missing delta in historical alias spec: {raw!r}")

                    target_contract = str(spec["contract"])
                    target_underlying_contract = _option_contract_to_underlying_contract(target_contract)
                    target_underlying_bcontract = _contract_to_barchart_contract(target_underlying_contract)
                    target_fut_df = underlying_data.get(target_underlying_bcontract)
                    if target_fut_df is None or target_fut_df.empty:
                        raise ValueError(
                            f"Could not resolve delta alias {raw!r}: missing underlying history for {target_contract}."
                        )
                    target_pos = _asof_index_position(target_fut_df.index, target_ts)
                    if target_pos is None:
                        raise ValueError(
                            f"Could not resolve delta alias {raw!r}: no underlying row near {target_date}."
                        )
                    target_forward = _extract_row_price(target_fut_df.iloc[target_pos].to_dict(), price_mode=price_mode)
                    if target_forward is None or target_forward <= 0.0:
                        raise ValueError(
                            f"Could not resolve delta alias {raw!r}: invalid underlying forward."
                        )

                    candidate_symbols: List[str] = []
                    per_raw_contracts = contracts_by_raw.get(raw, []) or [target_contract]
                    for contract in per_raw_contracts:
                        option_bcontract = _contract_to_barchart_contract(contract)
                        chain = chains.get(option_bcontract) if isinstance(chains, dict) else None
                        if chain is None:
                            if bulk_timeseries:
                                continue
                            raise ValueError(
                                f"Could not resolve delta alias {raw!r}: missing option chain for {contract}."
                            )
                        side = "call" if right == "C" else "put"
                        listed_strikes = self._live_chain_strikes(chain, side)
                        if not listed_strikes:
                            if bulk_timeseries:
                                continue
                            raise ValueError(
                                f"Could not resolve delta alias {raw!r}: no listed {side} strikes for {contract}."
                            )

                        underlying_contract = _option_contract_to_underlying_contract(contract)
                        underlying_bcontract = _contract_to_barchart_contract(underlying_contract)
                        fut_df = underlying_data.get(underlying_bcontract)
                        if fut_df is None or fut_df.empty:
                            if bulk_timeseries:
                                continue
                            raise ValueError(
                                f"Could not resolve delta alias {raw!r}: missing underlying history for {contract}."
                            )

                        if bulk_timeseries:
                            for row_dt, row in fut_df.iterrows():
                                row_day = pd.Timestamp(row_dt).date()
                                if row_day < req_window_start or row_day > req_window_end:
                                    continue
                                forward = _extract_row_price(row.to_dict(), price_mode=price_mode)
                                if forward is None or forward <= 0.0:
                                    continue
                                strike_subset = self._pick_centered_strike_slice(
                                    listed_strikes,
                                    center=float(forward),
                                    half_width=delta_candidate_half_width,
                                )
                                candidate_symbols.extend(
                                    [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_subset]
                                )
                        else:
                            pos = _asof_index_position(fut_df.index, target_ts)
                            if pos is None:
                                raise ValueError(
                                    f"Could not resolve delta alias {raw!r}: no underlying row near {target_date}."
                                )
                            forward = _extract_row_price(fut_df.iloc[pos].to_dict(), price_mode=price_mode)
                            if forward is None or forward <= 0.0:
                                raise ValueError(
                                    f"Could not resolve delta alias {raw!r}: invalid underlying forward."
                                )
                            strike_subset = self._pick_centered_strike_slice(
                                listed_strikes,
                                center=float(forward),
                                half_width=delta_candidate_half_width,
                            )
                            candidate_symbols.extend(
                                [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_subset]
                            )

                    candidate_symbols = self._dedupe_preserve_order(candidate_symbols)
                    if not candidate_symbols:
                        raise ValueError(
                            f"Could not resolve delta alias {raw!r}: no candidate strikes near forward."
                        )

                    delta_candidate_symbols[raw] = candidate_symbols
                    delta_meta[raw] = {
                        "target_delta": float(target_delta),
                        "right": right,
                        "forward": float(target_forward),
                    }

            expanded_needed: "OrderedDict[str, str]" = OrderedDict()
            if bulk_timeseries:
                for raw, spec in parsed_requested_specs.items():
                    selector = str(spec["selector"])
                    right = str(spec["right"]).upper()
                    contracts = contracts_by_raw.get(raw, [])
                    if selector == "delta":
                        continue
                    if selector == "strike":
                        strike4 = str(spec.get("strike4"))
                        for contract in contracts:
                            norm = f"{contract}|{strike4}{right}"
                            for leg in _expand_straddle_symbol(norm):
                                expanded_needed[leg] = leg
                        continue
                    if selector == "atm":
                        for contract in contracts:
                            atm_symbols = self._historical_atm_symbols_for_contract_window(
                                contract=contract,
                                right=right,
                                underlying_data=underlying_data,
                                window_start=req_window_start,
                                window_end=req_window_end,
                                price_mode=price_mode,
                                atm_strike_step=atm_strike_step,
                            )
                            for norm in atm_symbols:
                                for leg in _expand_straddle_symbol(norm):
                                    expanded_needed[leg] = leg

            for norm in resolved_non_delta.values():
                for leg in _expand_straddle_symbol(norm):
                    expanded_needed[leg] = leg
            for candidate_list in delta_candidate_symbols.values():
                for leg in candidate_list:
                    expanded_needed[leg] = leg

            if bulk_timeseries:
                cache_symbols = ["__BULK_TIMESERIES__"] + self._dedupe_preserve_order(
                    [str(s).strip().upper() for s in symbols]
                )
            else:
                cache_symbols = [str(spec.get("canonical")) for spec in requested_specs.values()]

            if expanded_needed:
                pricers_window = self._get_or_build_barchart_pricer_window(
                    leg_symbols=list(expanded_needed.keys()),
                    cache_symbols=cache_symbols,
                    request_start=req_window_start,
                    request_end=req_window_end,
                    show_tqdm=show_tqdm,
                    price_mode=price_mode,
                    curve_name=curve_name,
                    curve_kwargs=curve_kwargs,
                    use_ql_calculator=use_ql_calculator,
                    source="BARCHART_EOD_WINDOW",
                    force_refresh=force_refresh,
                )
            else:
                pricers_window = {}

            resolved_delta: "OrderedDict[str, str]" = OrderedDict()
            for raw, spec in delta_specs.items():
                meta = delta_meta[raw]
                resolved_leg = self._resolve_historical_delta_from_pricers(
                    candidate_symbols=delta_candidate_symbols[raw],
                    pricers_window=pricers_window,
                    target_date=target_date,
                    target_delta=float(meta["target_delta"]),
                    right=str(meta["right"]),
                    forward=float(meta["forward"]),
                )
                if resolved_leg is None:
                    contract = str(spec["contract"])
                    raise ValueError(f"Could not resolve delta alias {raw!r}: no priced strikes available near {target_date} for {contract}.")
                resolved_delta[raw] = resolved_leg

            requested = OrderedDict()
            for raw in requested_specs.keys():
                if raw in resolved_non_delta:
                    requested[raw] = resolved_non_delta[raw]
                elif raw in resolved_delta:
                    requested[raw] = resolved_delta[raw]

            for norm in requested.values():
                for leg_symbol in _expand_straddle_symbol(norm):
                    pr = self._asof_pricer_for_date(pricers_window.get(leg_symbol, {}), target_date)
                    if pr is not None:
                        cp_pricers[leg_symbol] = pr

        result: Dict[str, List[QLUSTFutureOptionPricer]] = {}
        for raw, norm in requested.items():
            if norm.endswith("S"):
                c_key = f"{norm[:-1]}C"
                p_key = f"{norm[:-1]}P"
                cpr = cp_pricers.get(c_key)
                ppr = cp_pricers.get(p_key)
                if cpr is None or ppr is None:
                    continue
                result[raw] = [self._synthesize_straddle(straddle_symbol=norm, call_pricer=cpr, put_pricer=ppr)]
            else:
                pr = cp_pricers.get(norm)
                if pr is None:
                    continue
                result[raw] = [pr]

        return result

    def _option_timeseries(self, request: Dict[str, Any]) -> Dict[str, List[QLUSTFutureOptionPricer]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        if not symbols:
            raise ValueError("option_timeseries requires symbols")
        if "start" not in request or "end" not in request:
            raise ValueError("option_timeseries requires start and end")

        start_date = _as_date(request["start"])
        end_date = _as_date(request["end"])
        if end_date < start_date:
            raise ValueError("option_timeseries requires end >= start")

        show_tqdm = bool(request.get("show_tqdm", False))
        price_mode = str(request.get("price_mode", "mid_then_fallback"))
        use_ql_calculator = bool(request.get("use_ql_calculator", False))
        force_refresh = bool(request.get("force_refresh", False))
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})

        requested_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for raw in symbols:
            parsed = _parse_option_request_symbol(raw, as_of=start_date)
            if parsed["selector"] != "strike":
                raise ValueError(
                    "option_timeseries currently supports explicit strike symbols only; "
                    f"got alias {raw!r}. Use option_snapshot for ATM/delta aliases."
                )
            requested_specs[raw] = parsed
        requested_specs = _resolve_option_contract_aliases_for_date(requested_specs, as_of=start_date)
        requested: "OrderedDict[str, str]" = OrderedDict((raw, str(spec["canonical"])) for raw, spec in requested_specs.items())

        expanded_needed: "OrderedDict[str, str]" = OrderedDict()
        for norm in requested.values():
            for leg in _expand_straddle_symbol(norm):
                expanded_needed[leg] = leg

        cp_by_symbol_date = self._get_or_build_barchart_pricer_window(
            leg_symbols=list(expanded_needed.keys()),
            cache_symbols=list(requested.values()),
            request_start=start_date,
            request_end=end_date,
            show_tqdm=show_tqdm,
            price_mode=price_mode,
            curve_name=curve_name,
            curve_kwargs=curve_kwargs,
            use_ql_calculator=use_ql_calculator,
            source="BARCHART_EOD_WINDOW",
            force_refresh=force_refresh,
        )

        result: Dict[str, List[QLUSTFutureOptionPricer]] = {}
        for raw, norm in requested.items():
            if norm.endswith("S"):
                c_key = f"{norm[:-1]}C"
                p_key = f"{norm[:-1]}P"
                c_map = cp_by_symbol_date.get(c_key, {})
                p_map = cp_by_symbol_date.get(p_key, {})
                dates = sorted(
                    d
                    for d in set(c_map.keys()).intersection(p_map.keys())
                    if start_date <= d <= end_date
                )
                if not dates:
                    continue
                result[raw] = [
                    self._synthesize_straddle(
                        straddle_symbol=norm,
                        call_pricer=c_map[d],
                        put_pricer=p_map[d],
                    )
                    for d in dates
                ]
            else:
                pr_map = cp_by_symbol_date.get(norm, {})
                if not pr_map:
                    continue
                days = sorted(d for d in pr_map.keys() if start_date <= d <= end_date)
                if not days:
                    continue
                result[raw] = [pr_map[d] for d in days]

        return result

    def get_pricer(self, request: Dict[str, Any]):
        return self.get_data(request)

    def get_data(self, request: Dict[str, Any]):
        endpoint = str(request.get("endpoint", "")).strip().lower()
        if not endpoint:
            raise ValueError("Request must include endpoint")

        self._assert_endpoint_allowed(endpoint)
        force_refresh = bool(request.get("force_refresh", False))
        cache_key = self._build_get_data_cache_key(endpoint, request)
        with self:
            if cache_key and not force_refresh:
                cached = self._threadsafe_cache_get(cache_key)
                hit = self._deserialize_get_data_result(cached)
                if hit is not None:
                    return hit

            if endpoint == "option_snapshot":
                out = self._option_snapshot(request)
            elif endpoint == "option_timeseries":
                out = self._option_timeseries(request)
            else:
                raise NotImplementedError(f"Unsupported endpoint: {endpoint}")

            if cache_key:
                self._threadsafe_cache_put(cache_key, self._serialize_get_data_result(endpoint, out))
            return out

    def get_bulk_pricer(self, request: Dict[str, Any]):
        return self.get_bulk_data(request)

    def get_bulk_data(self, request: Dict[str, Any]):
        timestamps_raw = request.get("timestamps")
        if timestamps_raw is None:
            raise ValueError("get_bulk_data requires timestamps")

        if isinstance(timestamps_raw, (str, datetime.date, datetime.datetime)):
            timestamps: List[DateLike] = [timestamps_raw]
        else:
            timestamps = list(timestamps_raw)
        if not timestamps:
            raise ValueError("timestamps is empty")

        max_workers = int(request.get("max_workers", 8))
        base_req = dict(request)
        base_req.pop("timestamps", None)

        jobs = [(ts, dict(base_req, timestamp=ts)) for ts in timestamps]
        results: List[Tuple[DateLike, Any]] = []

        with self:
            def _process_one(ts_like: DateLike, req: Dict[str, Any]):
                return ts_like, self.get_data(req)

            if max_workers <= 1 or len(jobs) == 1:
                for ts_like, req in jobs:
                    results.append(_process_one(ts_like, req))
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ustfo-mdp") as pool:
                    futs = {pool.submit(_process_one, ts_like, req): ts_like for ts_like, req in jobs}
                    for fut in as_completed(futs):
                        results.append(fut.result())

        out: Dict[DateLike, Any] = defaultdict(dict)
        for ts_like, res in results:
            out[ts_like] = res
        return dict(out)

    def __open__(self):
        with self._open_lock:
            if self._open_count == 0:
                self._ensure_pricer_cache()
            self._open_count += 1
        return self

    def __close__(self, *, commit: bool = True):
        with self._open_lock:
            if self._open_count <= 0:
                return
            self._open_count -= 1
            if self._open_count == 0:
                try:
                    if commit:
                        pass  # auto-committed (DiskCache)
                finally:
                    try:
                        self.close_cache()
                    finally:
                        self._cache_ready = False

    def __enter__(self):
        self.__open__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

