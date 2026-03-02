import datetime
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
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer

from MDP.STIRFutures.QuikStrikeSDK.core.QuikStrikeFetcher import QuikStrikeFetcher  
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID  
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolQuery import QuikVolQuery  
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolValueType import QuikVolValueType  
from MDP.STIRFutures.QuikStrikeSDK.core.utils.auth import walk_quikstrike_auth_flow  


DateLike = Union[datetime.date, datetime.datetime, str, Literal["live"]]
InstrumentLike = QLSTIRFutureOptionPricer

_NY_TZ = pytz.timezone("America/New_York")
_CHI_TZ = pytz.timezone("America/Chicago")
_UTC_TZ = pytz.UTC

_BBG_TO_BARCHART = {
    "SER": "SL",
    "FF": "QZ",
    "SFR": "SQ",
    "0Q": "MMA",
    "2Q": "MMB",
    "3Q": "MMC",
    "4Q": "MMD",
    "5Q": "MME",
    "UHOA": "MNA",
    "UMOA": "MNB",
    "UUOA": "MNC",
    "UZOA": "MND",
    "VHTA": "MNE",
    "VMTA": "MNF",
    "VUTA": "MNG",
    "VZTA": "MNH",
    "S01": "MMI",
    "S02": "MMJ",
    "S03": "MMK",
    "S04": "MML",
    "S05": "",
    "S21": "MMN",
    "S22": "MMO",
    "S23": "MMP",
    "S24": "MMQ",
    "S25": "",
    "S31": "MMS",
    "S32": "MMT",
    "S33": "MMU",
    "S34": "MMV",
    "S35": "",
}

_ROOT_ALIAS_MAP = {
    # SOFR 3M aliases
    "SFR": "SFR",
    "SR3": "SFR",
    "SQ": "SFR",
    # 1M SOFR aliases
    "SER": "SER",
    "SR1": "SER",
    "SL": "SER",
    # Fed Funds aliases
    "FF": "FF",
    "ZQ": "FF",
    "QZ": "FF",
    # Mid-curves (canonical BBG roots)
    "0Q": "0Q",
    "2Q": "2Q",
    "3Q": "3Q",
    "4Q": "4Q",
    "5Q": "5Q",
    # QuikStrike-like aliases for mid-curves
    "S0": "0Q",
    "S2": "2Q",
    "S3": "3Q",
    "S4": "4Q",
    "S5": "5Q",
    # 1Y serials
    "UHOA": "UHOA",
    "UMOA": "UMOA",
    "UUOA": "UUOA",
    "UZOA": "UZOA",
    # 2Y serials
    "VHTA": "VHTA",
    "VMTA": "VMTA",
    "VUTA": "VUTA",
    "VZTA": "VZTA",
    # Friday mid-curves
    "S01": "S01",
    "S02": "S02",
    "S03": "S03",
    "S04": "S04",
    "S05": "S05",
    "S21": "S21",
    "S22": "S22",
    "S23": "S23",
    "S24": "S24",
    "S25": "S25",
    "S31": "S31",
    "S32": "S32",
    "S33": "S33",
    "S34": "S34",
    "S35": "S35",
}
for _bbg_root, _bc_root in _BBG_TO_BARCHART.items():
    if _bc_root:
        _ROOT_ALIAS_MAP[_bc_root] = _bbg_root

_ROOT_TO_BARCHART = dict(_BBG_TO_BARCHART)

_UNDERLYING_RULES: Dict[str, Tuple[int, Optional[str]]] = {
    "SFR": (0, None),
    "0Q": (1, None),
    "2Q": (2, None),
    "3Q": (3, None),
    "4Q": (4, None),
    "5Q": (5, None),
    "UHOA": (1, "H"),
    "UMOA": (1, "M"),
    "UUOA": (1, "U"),
    "UZOA": (1, "Z"),
    "VHTA": (2, "H"),
    "VMTA": (2, "M"),
    "VUTA": (2, "U"),
    "VZTA": (2, "Z"),
    "S01": (1, None),
    "S02": (1, None),
    "S03": (1, None),
    "S04": (1, None),
    "S05": (1, None),
    "S21": (2, None),
    "S22": (2, None),
    "S23": (2, None),
    "S24": (2, None),
    "S25": (2, None),
    "S31": (3, None),
    "S32": (3, None),
    "S33": (3, None),
    "S34": (3, None),
    "S35": (3, None),
}
_SFR_UNDERLYING_ROOTS = set(_UNDERLYING_RULES.keys())
_MONTH_CODE_TO_NUM = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
_NUM_TO_MONTH_CODE = {v: k for k, v in _MONTH_CODE_TO_NUM.items()}
_QUARTERLY_MONTHS = (3, 6, 9, 12)

_ROOT_TOKEN_PATTERN = "|".join(sorted([re.escape(r) for r in _ROOT_ALIAS_MAP.keys()], key=len, reverse=True))
_OPTION_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{2}})\|(?P<strike>\d{{3,5}})(?P<right>[CPS])$",
    re.IGNORECASE,
)
_OPTION_ATM_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{2}})\|ATM(?P<right>[CPS])$",
    re.IGNORECASE,
)
_OPTION_DELTA_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{2}})\|(?P<delta>\d{{1,2}}(?:\.\d+)?)D?(?P<right>[CP])$",
    re.IGNORECASE,
)
_OPTION_ATM_NATURAL_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{2}})\s+ATM\s+(?P<right>STRADDLE|CALL|PUT)$",
    re.IGNORECASE,
)
_OPTION_DELTA_NATURAL_RE = re.compile(
    rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{2}})\s+(?P<delta>\d{{1,2}}(?:\.\d+)?)\s*D(?:ELTA)?\s+(?P<right>STRADDLE|CALL|PUT)$",
    re.IGNORECASE,
)
_FUTURE_RE = re.compile(rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{2}})$", re.IGNORECASE)
_CM_RE = re.compile(rf"^(?P<root>{_ROOT_TOKEN_PATTERN})?CM(?P<rank>\d+)$", re.IGNORECASE)

_DEFAULT_CURVE_NAME = "USD-SOFR-1D-Q12xM12STIRT"


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


def _format_strike4(strike: float) -> str:
    return str(int(round(float(strike) * 100.0))).zfill(4)


def _atm_strike_from_forward(forward: float, step: float = 0.25) -> float:
    if not math.isfinite(forward) or forward <= 0.0:
        raise ValueError(f"Invalid forward for ATM strike resolution: {forward}")
    if step <= 0.0:
        step = 0.25
    return round(forward / step) * step


def _strike_step_for_contract(contract: str) -> float:
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        return 0.125
    root = _ROOT_ALIAS_MAP[m.group("root").upper()]
    if root in _SFR_UNDERLYING_ROOTS or root in {"SFR"}:
        return 0.125
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
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        raise ValueError(f"Invalid STIR future contract token: {contract}")
    root = _ROOT_ALIAS_MAP[m.group("root").upper()]
    barchart_root = _ROOT_TO_BARCHART.get(root, "")
    if not barchart_root:
        raise ValueError(f"Unsupported/disabled Barchart root mapping for {root}")
    return f"{barchart_root}{m.group('code').upper()}"


def _parse_contract_token(token: str) -> Dict[str, Any]:
    t = (token or "").strip().upper()
    m = _FUTURE_RE.fullmatch(t)
    if m:
        root = _ROOT_ALIAS_MAP[m.group("root").upper()]
        code = m.group("code").upper()
        return {
            "contract_selector": "explicit",
            "contract": f"{root}{code}",
            "cm_root": None,
            "cm_rank": None,
        }

    m = _CM_RE.fullmatch(t)
    if m:
        raw_root = m.group("root")
        root = _ROOT_ALIAS_MAP[(raw_root or "SFR").upper()]
        rank = int(m.group("rank"))
        if rank <= 0:
            raise ValueError(f"CM rank must be >= 1: {token}")
        return {
            "contract_selector": "cm",
            "contract": None,
            "cm_root": root,
            "cm_rank": rank,
        }

    raise ValueError(f"Invalid option contract token: {token}")


def _resolve_cm_contract(*, cm_root: str, cm_rank: int, as_of: datetime.date) -> str:
    root = _ROOT_ALIAS_MAP[(cm_root or "SFR").upper()]
    rank = int(cm_rank)
    if rank <= 0:
        raise ValueError(f"CM rank must be >= 1, got {cm_rank}")

    # SOFR/midcurves use quarterly ladder with IMM cutoff. Monthly roots stay monthly.
    use_imm = root in (_SFR_UNDERLYING_ROOTS | {"SFR"})
    valid_months = [3, 6, 9, 12] if use_imm else list(range(1, 13))
    cutoff = _imm_cutoff if use_imm else None
    contracts = _next_contracts(
        start_date=as_of,
        prefix=root,
        count=max(rank, 1),
        valid_months=valid_months,
        cutoff_fn=cutoff,
    )
    if len(contracts) < rank:
        raise ValueError(f"Unable to resolve {root}CM{rank} at {as_of.isoformat()}")
    return contracts[rank - 1]


def _resolve_contract_from_spec(spec: Dict[str, Any], as_of: datetime.date) -> str:
    selector = str(spec.get("contract_selector", "explicit"))
    if selector == "explicit":
        c = spec.get("contract")
        if not c:
            raise ValueError(f"Missing explicit contract in spec: {spec}")
        return str(c)
    if selector == "cm":
        root = str(spec.get("cm_root") or "SFR")
        rank = int(spec.get("cm_rank") or 1)
        return _resolve_cm_contract(cm_root=root, cm_rank=rank, as_of=as_of)
    raise ValueError(f"Unsupported contract selector: {selector}")


def _next_quarterly_code(month_code: str, year_2digit: int) -> Tuple[str, int]:
    month_num = _MONTH_CODE_TO_NUM.get(month_code.upper(), 0)
    next_q = next((m for m in _QUARTERLY_MONTHS if m >= month_num), None)
    if next_q is None:
        return "H", year_2digit + 1
    if month_num in _QUARTERLY_MONTHS:
        return month_code.upper(), year_2digit
    return _NUM_TO_MONTH_CODE[next_q], year_2digit


def _option_contract_to_underlying_contract(contract: str) -> str:
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        raise ValueError(f"Invalid STIR option contract token: {contract}")

    root = _ROOT_ALIAS_MAP[m.group("root").upper()]
    code = m.group("code").upper()
    opt_month = code[0]
    opt_year = int(code[1:])

    if root in _SFR_UNDERLYING_ROOTS:
        rule = _UNDERLYING_RULES.get(root, (0, None))
        year_offset, fixed_month = rule
        if fixed_month:
            ul_month = fixed_month
            ul_year = opt_year + year_offset
        else:
            base_month, base_year = _next_quarterly_code(opt_month, opt_year)
            ul_month = base_month
            ul_year = base_year + year_offset
        return f"SFR{ul_month}{ul_year % 100:02d}"

    # Non-SOFR-underlying products default to same-root underlying contract.
    return f"{root}{code}"


def _parse_option_request_symbol(symbol: str) -> Dict[str, Any]:
    token = (symbol or "").strip().upper().replace("/", "")

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

        m = re.fullmatch(r"(?P<strike>\d{3,5})(?P<right>[CPS])", leg_part)
        if m:
            strike4 = str(int(m.group("strike"))).zfill(4)
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
        rf"(?P<contract>(?:{_ROOT_TOKEN_PATTERN})?(?:CM\d+)|(?:{_ROOT_TOKEN_PATTERN})[FGHJKMNQUVXZ]\d{{2}})\s+ATM\s+(?P<right>STRADDLE|CALL|PUT)",
        token,
    )
    if m:
        contract_spec = _parse_contract_token(m.group("contract"))
        right = _right_word_to_token(m.group("right"))
        return _build(contract_spec=contract_spec, selector="atm", right=right, strike4=None, delta=None)

    m = re.fullmatch(
        rf"(?P<contract>(?:{_ROOT_TOKEN_PATTERN})?(?:CM\d+)|(?:{_ROOT_TOKEN_PATTERN})[FGHJKMNQUVXZ]\d{{2}})\s+(?P<delta>\d{{1,2}}(?:\.\d+)?)\s*D(?:ELTA)?\s+(?P<right>STRADDLE|CALL|PUT)",
        token,
    )
    if m:
        contract_spec = _parse_contract_token(m.group("contract"))
        right = _right_word_to_token(m.group("right"))
        if right == "S":
            raise ValueError("Delta straddle alias is not supported; use explicit strikes or 25DC/25DP legs.")
        delta = float(m.group("delta"))
        if delta <= 0.0 or delta >= 100.0:
            raise ValueError(f"Delta alias must be in (0,100): {symbol}")
        return _build(contract_spec=contract_spec, selector="delta", right=right, strike4=None, delta=delta)

    raise ValueError(f"Invalid STIR option symbol token: {symbol}")


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
    return _contract_to_barchart_contract(fut)


def _canonical_to_barchart_option(symbol: str) -> str:
    token = _norm_option_symbol(symbol)
    _ = token.split("|", 1)[0]
    bcontract = _canonical_to_barchart_contract(token)
    return f"{bcontract}|{token.split('|', 1)[1]}"


def _canonical_contract(symbol: str) -> str:
    return _norm_option_symbol(symbol).split("|", 1)[0]


def _canonical_underlying(symbol: str) -> str:
    return _option_contract_to_underlying_contract(_canonical_contract(symbol))


def _strike_from_symbol(symbol: str) -> float:
    token = _norm_option_symbol(symbol)
    strike4 = token.split("|", 1)[1][:-1]
    return float(int(strike4)) / 100.0


def _right_from_symbol(symbol: str) -> str:
    return _norm_option_symbol(symbol)[-1]


def _contract_code_from_symbol(symbol: str) -> str:
    return _canonical_contract(symbol)[-3:]


def _ql_date_to_pydate(d: ql.Date) -> datetime.date:
    serial = d.serialNumber()
    dt = datetime.datetime.fromordinal(serial + 693594)
    return dt.date()


def _contract_expiry_date(code2: str) -> datetime.date:
    m = re.fullmatch(r"([FGHJKMNQUVXZ])(\d{2})", (code2 or "").upper())
    if m is None:
        raise ValueError(f"Invalid SR3 contract code: {code2}")
    month_code = m.group(1)
    yy = int(m.group(2))
    year = 2000 + yy
    imm_code = f"{month_code}{yy % 10}"
    qd = ql.IMM.date(imm_code, ql.Date(1, 1, year))
    return _ql_date_to_pydate(qd)


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

class STIRFutureOptionMDP(MarketDataProvider[InstrumentLike], DiskCacheMixin):
    _STIR_OPTION_CACHE = "_stir_option_pricer_cache"
    _BARCHART_STATE: Dict[str, Any] = {}
    _CURVE_STATE: Dict[str, Any] = {}
    _QS_STATE: Dict[str, Any] = {}

    def __init__(self, source: str = "STIRFO_DUAL-QL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        DiskCacheMixin.__init__(self)

        self.cache_full_intraday_fetch = bool(kwargs.get("cache_full_intraday_fetch", False))
        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False

        self._barchart_fetcher: Optional[BarchartFetcher] = None
        self._barchart_lock = threading.RLock()
        self._barchart_proxies_static = kwargs.get("barchart_proxies")
        self._curve_name_default = kwargs.get("curve_name_default", _DEFAULT_CURVE_NAME)
        self._socksio_enabled = _socksio_available()

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

        if not STIRFutureOptionMDP._BARCHART_STATE:
            STIRFutureOptionMDP._BARCHART_STATE = {
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
                "ttl": self._barchart_proxy_ttl,
                "fetcher": None,
                "cycler": itertools.cycle(self._barchart_proxy_hosts),
                "lock": threading.RLock(),
            }

        if not STIRFutureOptionMDP._CURVE_STATE:
            STIRFutureOptionMDP._CURVE_STATE = {
                "builder": None,
                "lock": threading.RLock(),
            }
        if not STIRFutureOptionMDP._QS_STATE:
            STIRFutureOptionMDP._QS_STATE = {
                "insid": None,
                "qsid": None,
                "lock": threading.RLock(),
            }

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._STIR_OPTION_CACHE):
            return
        cache_path = DiskCacheMixin.default_cache_path("STIRFutureOptionPricer_Cache")
        self.open_cache(cache_attr=self._STIR_OPTION_CACHE, path=cache_path, encode=None, decode=None)
        self._cache_ready = True

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._STIR_OPTION_CACHE)
            cache[key] = value

    def _threadsafe_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._STIR_OPTION_CACHE)
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

    def _build_get_data_cache_key(self, endpoint: str, request: Dict[str, Any]) -> Optional[str]:
        ep = str(endpoint or "").strip().lower()
        if ep not in {"option_snapshot", "option_timeseries"}:
            return None

        cache_req = dict(request)
        cache_req.pop("show_tqdm", None)
        cache_req.pop("force_refresh", None)

        if ep == "option_snapshot":
            ts = cache_req.get("timestamp", "live")
            if isinstance(ts, str) and ts.strip().lower() == "live":
                # Avoid stale caches for live snapshots unless explicitly opted in.
                if not self.cache_full_intraday_fetch:
                    return None
                live_bucket = datetime.datetime.now(_NY_TZ).replace(second=0, microsecond=0)
                cache_req["timestamp"] = live_bucket
            else:
                cache_req["timestamp"] = _as_date(ts)

        if ep == "option_timeseries":
            if "start" in cache_req:
                cache_req["start"] = _as_date(cache_req["start"])
            if "end" in cache_req:
                cache_req["end"] = _as_date(cache_req["end"])

        payload = {
            "schema": 1,
            "cache_version": "stirfo_get_data_v1",
            "source": str(self.source).upper(),
            "endpoint": ep,
            "request": self._cache_primitive(cache_req),
        }
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(payload_str.encode("utf-8")).hexdigest()
        return f"STIRFO_GET_DATA::{ep}::{digest}"

    def _serialize_pricer(self, pr: QLSTIRFutureOptionPricer) -> Dict[str, Any]:
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
            "meta_data": pr.meta(),
        }

    def _deserialize_pricer(self, row: Dict[str, Any]) -> QLSTIRFutureOptionPricer:
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

        return QLSTIRFutureOptionPricer(
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
            meta_data=row.get("meta_data") or {},
        )

    def _serialize_get_data_result(self, endpoint: str, result: Dict[str, List[QLSTIRFutureOptionPricer]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for k, plist in result.items():
            payload[str(k)] = [self._serialize_pricer(p) for p in plist]
        return {"schema": 1, "endpoint": endpoint, "result": payload}

    def _deserialize_get_data_result(self, cached: Dict[str, Any]) -> Optional[Dict[str, List[QLSTIRFutureOptionPricer]]]:
        if not isinstance(cached, dict):
            return None
        if int(cached.get("schema", 0)) != 1:
            return None
        result_raw = cached.get("result")
        if not isinstance(result_raw, dict):
            return None
        out: Dict[str, List[QLSTIRFutureOptionPricer]] = {}
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
        if src == "STIRFO_DUAL-QL":
            return
        if src == "BARCHART_STIRFO-QL" and ep in {"option_snapshot", "option_timeseries"}:
            return
        if src == "QUIKSTRIKE_STIRFO-QL" and ep in {"qs_atm_term_structure", "qs_timeseries"}:
            return
        raise NotImplementedError(f"Endpoint '{endpoint}' is not available for source '{self.source}'")

    def _get_cached_barchart_proxy(self) -> Tuple[Optional[dict], Optional[str]]:
        S = STIRFutureOptionMDP._BARCHART_STATE
        if time.time() - float(S["chosen_at"]) < float(S["ttl"]):
            return S["proxies"], S["host"]
        return None, None

    def _choose_barchart_proxy(self) -> Tuple[Optional[dict], Optional[str]]:
        S = STIRFutureOptionMDP._BARCHART_STATE
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

    def _get_barchart_fetcher(self) -> BarchartFetcher:
        # Explicit static proxy path (caller-provided).
        if self._barchart_proxies_static is not None:
            with self._barchart_lock:
                if self._barchart_fetcher is None:
                    self._barchart_fetcher = BarchartFetcher(
                        proxies=self._barchart_proxies_static,
                        debug_verbose=False,
                        error_verbose=True,
                    )
                try:
                    with _ProxyGuard(self._barchart_proxies_static):
                        self._barchart_fetcher._fetch_session_tokens(dummy_symbol="BTC")
                except Exception:
                    pass
                return self._barchart_fetcher

        # Rotating sticky proxy path (same pattern as STIRFutureMDP).
        S = STIRFutureOptionMDP._BARCHART_STATE
        with S["lock"]:
            proxies, host = self._get_cached_barchart_proxy()
            if proxies is None and host is None:
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                S["fetcher"] = None

            bcf = S["fetcher"]
            if bcf is None:
                bcf = BarchartFetcher(proxies=proxies, debug_verbose=False, error_verbose=True)
                S["fetcher"] = bcf

            try:
                with _ProxyGuard(proxies):
                    bcf._fetch_session_tokens(dummy_symbol="BTC")
            except Exception:
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                bcf = BarchartFetcher(proxies=proxies, debug_verbose=False, error_verbose=True)
                S["fetcher"] = bcf
                with _ProxyGuard(proxies):
                    bcf._fetch_session_tokens(dummy_symbol="BTC")

            return bcf

    def _get_curve_builder(self) -> BARCHART_STIRF_CURVE:
        S = STIRFutureOptionMDP._CURVE_STATE
        with S["lock"]:
            if S["builder"] is None:
                S["builder"] = BARCHART_STIRF_CURVE()
            return S["builder"]

    def _curve_timestamp_for_request(self, ts_like: DateLike) -> datetime.datetime:
        d = _as_date(ts_like)
        return _NY_TZ.localize(datetime.datetime.combine(d, datetime.time(hour=17, minute=0)))

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

    def _quikstrike_credentials(self, *, force_refresh: bool = False) -> Tuple[int, str]:
        S = STIRFutureOptionMDP._QS_STATE
        with S["lock"]:
            if force_refresh or S["insid"] is None or S["qsid"] is None:
                insid, qsid = walk_quikstrike_auth_flow()
                S["insid"] = int(insid)
                S["qsid"] = str(qsid)
            return int(S["insid"]), str(S["qsid"])

    def _quikstrike_client(self, *, force_refresh: bool = False) -> QuikStrikeFetcher:
        insid, qsid = self._quikstrike_credentials(force_refresh=force_refresh)
        return QuikStrikeFetcher(
            cme_insid=insid,
            cme_qsid=qsid,
            run_selenium=False,
            log_level=logging.ERROR,
        )

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
        bcf = self._get_barchart_fetcher()
        start_dt = datetime.datetime.combine(start, datetime.time(0, 0))
        end_dt = datetime.datetime.combine(end, datetime.time(23, 59))
        mc = int(max_concurrent_tasks or min(max(len(symbols), 1), 32))
        mk = int(max_keepalive_connections or min(max(len(symbols), 1), 32))
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
        bcf = self._get_barchart_fetcher()
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
            max_concurrent_tasks=min(max(len(contracts), 1), 24),
            max_keepalive_connections=min(max(len(contracts), 1), 24),
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
    ) -> Optional[QLSTIRFutureOptionPricer]:
        right = _right_from_symbol(canonical_symbol)
        if right not in {"C", "P"}:
            return None

        strike = _strike_from_symbol(canonical_symbol)
        contract_code = _contract_code_from_symbol(canonical_symbol)
        expiry = _contract_expiry_date(contract_code)
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

        return QLSTIRFutureOptionPricer(
            symbol=canonical_symbol,
            right=right,
            underlying_symbol=_canonical_underlying(canonical_symbol),
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
            meta_data=metadata,
        )

    def _synthesize_straddle(
        self,
        *,
        straddle_symbol: str,
        call_pricer: QLSTIRFutureOptionPricer,
        put_pricer: QLSTIRFutureOptionPricer,
    ) -> QLSTIRFutureOptionPricer:
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

        return QLSTIRFutureOptionPricer(
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
            meta_data=metadata,
        )

    def _extract_live_option_row(
        self,
        *,
        chain: Dict[str, pd.DataFrame],
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
            target = int(round(strike * 100))
            pat = re.compile(rf"\|{target}(C|P)$", re.IGNORECASE)
            rows = df_work[df_work["symbol"].astype(str).str.contains(pat, regex=True, na=False)]
            if not rows.empty:
                return dict(rows.iloc[0].to_dict())

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

    def _strike_token_from_barchart_option_symbol(self, option_symbol: str) -> Optional[str]:
        m = re.search(r"\|(?P<strike>\d{3,5})(?P<right>[CP])$", str(option_symbol or "").strip().upper())
        if m is None:
            return None
        return str(int(m.group("strike"))).zfill(4)

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
                resolved[raw] = f"{contract}|{_format_strike4(strike)}{right}"
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
                resolved[raw] = f"{contract}|{_format_strike4(strike)}{right}"
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
        delta_resolution_cache: Dict[Tuple[str, str, float, datetime.date], str] = {}

        for raw, spec in requested_specs.items():
            selector = str(spec["selector"])
            contract = str(spec["contract"])
            right = str(spec["right"]).upper()
            if selector == "strike":
                resolved[raw] = str(spec["canonical"])
                continue

            if selector == "delta":
                if right not in {"C", "P"}:
                    raise ValueError(f"Historical delta alias supports call/put only: {raw!r}")
                delta = _to_float(spec.get("delta"))
                if delta is None:
                    raise ValueError(f"Missing delta in historical alias spec: {raw!r}")
                cache_key = (contract, right, float(delta), target_date)
                if cache_key not in delta_resolution_cache:
                    underlying_contract = _option_contract_to_underlying_contract(contract)
                    bcontract = _contract_to_barchart_contract(underlying_contract)
                    fut_df = underlying_data.get(bcontract)
                    if fut_df is None or fut_df.empty:
                        raise ValueError(f"Could not resolve delta alias {raw!r}: missing underlying history for {contract}.")
                    strike_token = self._resolve_historical_delta_strike(
                        option_contract=contract,
                        right=right,
                        target_delta=float(delta),
                        target_date=target_date,
                        underlying_df=fut_df,
                        price_mode=price_mode,
                        show_tqdm=show_tqdm,
                    )
                    delta_resolution_cache[cache_key] = strike_token

                strike_token = delta_resolution_cache[cache_key]
                resolved[raw] = f"{contract}|{strike_token}{right}"
                continue

            if selector != "atm":
                raise ValueError(f"Unsupported alias selector {selector!r} for symbol {raw!r}")

            underlying_contract = _option_contract_to_underlying_contract(contract)
            bcontract = _contract_to_barchart_contract(underlying_contract)
            fut_df = underlying_data.get(bcontract)
            if fut_df is None or fut_df.empty:
                raise ValueError(f"Could not resolve ATM alias {raw!r}: missing underlying history for {contract}.")

            pos = _nearest_index_position(fut_df.index, target_ts)
            if pos is None:
                raise ValueError(f"Could not resolve ATM alias {raw!r}: no underlying row near {target_date}.")
            forward = _extract_row_price(fut_df.iloc[pos].to_dict(), price_mode=price_mode)
            if forward is None or forward <= 0.0:
                raise ValueError(f"Could not resolve ATM alias {raw!r}: invalid underlying forward.")

            atm_strike = _atm_strike_from_forward(float(forward), step=atm_strike_step)
            resolved[raw] = f"{contract}|{_format_strike4(atm_strike)}{right}"

        return resolved

    def _resolve_historical_delta_strike(
        self,
        *,
        option_contract: str,
        right: str,
        target_delta: float,
        target_date: datetime.date,
        underlying_df: pd.DataFrame,
        price_mode: str,
        show_tqdm: bool,
    ) -> str:
        start = target_date - datetime.timedelta(days=7)
        end = target_date + datetime.timedelta(days=7)

        target_ts = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(target_date, datetime.time(17, 0))))
        pos_under = _nearest_index_position(underlying_df.index, target_ts)
        if pos_under is None:
            raise ValueError(f"Could not resolve historical delta: no underlying row near {target_date} for {option_contract}")
        forward = _extract_row_price(underlying_df.iloc[pos_under].to_dict(), price_mode=price_mode)
        if forward is None or forward <= 0.0:
            raise ValueError(f"Could not resolve historical delta: invalid forward near {target_date} for {option_contract}")

        expiry = _contract_expiry_date(option_contract[-3:])
        tte = _time_to_expiry(target_date, expiry)
        if tte <= 0.0:
            raise ValueError(f"Could not resolve historical delta: non-positive TTE for {option_contract}")

        right = str(right).upper()
        side = "call" if right == "C" else "put"
        option_bcontract = _contract_to_barchart_contract(option_contract)

        # Get current listed strikes once, then only query historical EOD for those exact listed symbols.
        bcf = self._get_barchart_fetcher()
        chains = bcf.get_option_quotes(
            symbols=[option_bcontract],
            max_concurrent_tasks=1,
            max_keepalive_connections=1,
            show_tqdm=show_tqdm,
        )
        chain = chains.get(option_bcontract) if isinstance(chains, dict) else None
        if chain is None:
            raise ValueError(f"Could not resolve historical delta: missing live chain for {option_contract}")

        listed_pairs = self._live_chain_listed_symbols(chain=chain, side=side)
        if not listed_pairs:
            # Fallback when chain rows do not include explicit symbol column.
            side_df = chain.get(side) if isinstance(chain, dict) else None
            if isinstance(side_df, pd.DataFrame) and not side_df.empty and "strikePrice" in side_df.columns:
                strikes = pd.to_numeric(side_df["strikePrice"], errors="coerce").dropna()
                seen = set()
                listed_pairs = []
                for strike in sorted(float(x) for x in strikes.unique()):
                    token = _format_strike4(strike)
                    bc_sym = f"{option_bcontract}|{token}{right}"
                    if bc_sym in seen:
                        continue
                    seen.add(bc_sym)
                    listed_pairs.append((strike, bc_sym))

        if not listed_pairs:
            raise ValueError(f"Could not resolve historical delta: no listed {side} strikes for {option_contract}")

        # Phase 1: infer a local normal vol proxy from nearest listed strikes to forward.
        iv_probe_pairs = sorted(listed_pairs, key=lambda p: abs(float(p[0]) - float(forward)))[:5]
        iv_probe_symbols = [sym for _, sym in iv_probe_pairs]
        iv_data = self._fetch_barchart_eod_series(
            symbols=iv_probe_symbols,
            start=start,
            end=end,
            show_tqdm=show_tqdm,
            max_concurrent_tasks=min(max(len(iv_probe_symbols), 1), 3),
            max_keepalive_connections=min(max(len(iv_probe_symbols), 1), 3),
        )
        iv_proxy = float("nan")
        for strike, bc_sym in iv_probe_pairs:
            df = iv_data.get(bc_sym)
            if df is None or df.empty:
                continue
            pos = _nearest_index_position(df.index, target_ts)
            if pos is None:
                continue
            row = dict(df.iloc[pos].to_dict())
            price = _extract_row_price(row, price_mode=price_mode)
            if price is None or price <= 0.0:
                continue
            iv = _implied_normal_vol(right, float(strike), float(forward), tte, float(price), 1.0)
            if math.isfinite(iv) and iv > 0.0:
                iv_proxy = float(iv)
                break
            vendor_iv = _to_float(row.get("optImpliedVolatility", row.get("impliedVolatility", row.get("impliedVolatilitySkew"))))
            if vendor_iv is not None and vendor_iv > 0.0:
                iv_proxy = float(vendor_iv)
                break

        if not math.isfinite(iv_proxy) or iv_proxy <= 0.0:
            iv_proxy = 0.80

        # Phase 2: estimate strike via Bachelier delta and only fetch a small local subset of listed strikes.
        est_strike = _estimate_bachelier_strike_for_target_delta(
            right=right,
            target_delta_abs=float(target_delta),
            forward=float(forward),
            vol_normal=float(iv_proxy),
            tte=tte,
            discount=1.0,
        )

        listed_pairs_sorted = sorted(listed_pairs, key=lambda p: float(p[0]))
        est_idx = min(range(len(listed_pairs_sorted)), key=lambda i: abs(float(listed_pairs_sorted[i][0]) - float(est_strike)))
        lo = max(est_idx - 6, 0)
        hi = min(est_idx + 7, len(listed_pairs_sorted))
        candidate_pairs = listed_pairs_sorted[lo:hi]
        if not candidate_pairs:
            candidate_pairs = [listed_pairs_sorted[est_idx]]

        candidate_bc_symbols = [sym for _, sym in candidate_pairs]
        data = self._fetch_barchart_eod_series(
            symbols=candidate_bc_symbols,
            start=start,
            end=end,
            show_tqdm=show_tqdm,
            max_concurrent_tasks=min(max(len(candidate_bc_symbols), 1), 4),
            max_keepalive_connections=min(max(len(candidate_bc_symbols), 1), 4),
        )

        target = float(target_delta) / 100.0
        best: Optional[Tuple[float, float, float, str]] = None  # (error, distance_to_est, strike, bc_symbol)

        for strike, bc_sym in candidate_pairs:
            df = data.get(bc_sym)
            if df is None or df.empty:
                continue
            pos = _nearest_index_position(df.index, target_ts)
            if pos is None:
                continue
            row = dict(df.iloc[pos].to_dict())

            delta_val = _normalize_vendor_delta(row.get("delta", row.get("Delta")))
            if delta_val is None:
                price = _extract_row_price(row, price_mode=price_mode)
                if price is None or price <= 0.0:
                    continue
                iv = _implied_normal_vol(right, strike, float(forward), tte, float(price), 1.0)
                if (not math.isfinite(iv)) or iv <= 0.0:
                    vendor_iv = _to_float(
                        row.get("optImpliedVolatility", row.get("impliedVolatility", row.get("impliedVolatilitySkew")))
                    )
                    if vendor_iv is not None and vendor_iv > 0.0:
                        iv = float(vendor_iv)
                if not math.isfinite(iv) or iv <= 0.0:
                    continue
                delta_val = _bachelier_delta_from_calculator(
                    right=right,
                    strike=strike,
                    forward=float(forward),
                    vol_normal=iv,
                    tte=tte,
                    discount=1.0,
                )
                if not math.isfinite(delta_val):
                    continue

            if right == "C":
                err = abs(float(delta_val) - target)
            else:
                err = min(abs(float(delta_val) + target), abs(abs(float(delta_val)) - target))
            dist = abs(float(strike) - float(est_strike))
            if best is None or err < best[0] or (
                abs(err - best[0]) < 1e-12 and dist < best[1]
            ):
                best = (err, dist, float(strike), bc_sym)

        if best is None:
            # Fallback: nearest listed strike to model estimate (no synthetic strikes).
            fallback_strike, fallback_sym = min(listed_pairs_sorted, key=lambda p: abs(float(p[0]) - float(est_strike)))
            token = self._strike_token_from_barchart_option_symbol(fallback_sym)
            return token if token is not None else _format_strike4(float(fallback_strike))

        token = self._strike_token_from_barchart_option_symbol(best[3])
        if token is None:
            token = _format_strike4(best[2])
        return token

    def _resolve_underlying_forward_for_eod_row(
        self,
        *,
        underlying_df: pd.DataFrame,
        row_dt: pd.Timestamp,
        price_mode: str,
    ) -> Optional[float]:
        if underlying_df is None or underlying_df.empty:
            return None
        pos = _nearest_index_position(underlying_df.index, row_dt)
        if pos is None:
            return None
        return _extract_row_price(underlying_df.iloc[pos].to_dict(), price_mode=price_mode)

    def _option_snapshot(self, request: Dict[str, Any]) -> Dict[str, List[QLSTIRFutureOptionPricer]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        if not symbols:
            raise ValueError("option_snapshot requires symbols")

        ts = request.get("timestamp", "live")
        show_tqdm = bool(request.get("show_tqdm", False))
        price_mode = str(request.get("price_mode", "mid_then_fallback"))
        use_ql_calculator = bool(request.get("use_ql_calculator", False))
        window_minutes = int(request.get("window_minutes", 2))
        atm_strike_step = float(request.get("atm_strike_step", 0.25))
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})

        requested_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for raw in symbols:
            requested_specs[raw] = _parse_option_request_symbol(raw)
        requested_specs = _resolve_option_contract_aliases_for_date(requested_specs, as_of=_as_date(ts))

        requested: "OrderedDict[str, str]"
        cp_pricers: Dict[str, QLSTIRFutureOptionPricer] = {}

        if str(ts).strip().lower() == "live":
            ts_dt = _as_datetime("live")
            option_contracts = sorted({_contract_to_barchart_contract(str(spec["contract"])) for spec in requested_specs.values()})
            underlying_contracts = sorted(
                {_contract_to_barchart_contract(_option_contract_to_underlying_contract(str(spec["contract"]))) for spec in requested_specs.values()}
            )
            bcf = self._get_barchart_fetcher()
            chains = bcf.get_option_quotes(
                symbols=option_contracts,
                max_concurrent_tasks=min(max(len(option_contracts), 1), 32),
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
                strike = _strike_from_symbol(leg_symbol)
                right = _right_from_symbol(leg_symbol)
                row = self._extract_live_option_row(chain=chain, strike=strike, right=right)
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
            start = target_date - datetime.timedelta(days=7)
            end = target_date + datetime.timedelta(days=7)

            contract_symbols_bc = sorted(
                {_contract_to_barchart_contract(_option_contract_to_underlying_contract(str(spec["contract"]))) for spec in requested_specs.values()}
            )
            underlying_data = self._fetch_barchart_eod_series(
                symbols=contract_symbols_bc,
                start=start,
                end=end,
                show_tqdm=show_tqdm,
            )
            requested = self._resolve_snapshot_requested_symbols_historical(
                requested_specs=requested_specs,
                target_date=target_date,
                underlying_data=underlying_data,
                price_mode=price_mode,
                atm_strike_step=atm_strike_step,
                show_tqdm=show_tqdm,
            )

            expanded_needed: "OrderedDict[str, str]" = OrderedDict()
            for norm in requested.values():
                for leg in _expand_straddle_symbol(norm):
                    expanded_needed[leg] = leg

            option_symbols_bc = sorted({_canonical_to_barchart_option(sym) for sym in expanded_needed})
            contracts = sorted({_contract_to_barchart_contract(_canonical_underlying(sym)) for sym in expanded_needed})
            all_syms = option_symbols_bc + contracts
            data = self._fetch_barchart_eod_series(
                symbols=all_syms,
                start=start,
                end=end,
                show_tqdm=show_tqdm,
            )
            curve_memo = {}
            target_ts = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(target_date, datetime.time(17, 0))))

            for leg_symbol in expanded_needed:
                opt_bc = _canonical_to_barchart_option(leg_symbol)
                fut_bc = _contract_to_barchart_contract(_canonical_underlying(leg_symbol))
                opt_df = data.get(opt_bc)
                fut_df = data.get(fut_bc)
                if opt_df is None or opt_df.empty or fut_df is None or fut_df.empty:
                    continue

                opt_pos = _nearest_index_position(opt_df.index, target_ts)
                if opt_pos is None:
                    continue
                row_dt = pd.Timestamp(opt_df.index[opt_pos])
                row = dict(opt_df.iloc[opt_pos].to_dict())
                forward = self._resolve_underlying_forward_for_eod_row(underlying_df=fut_df, row_dt=row_dt, price_mode=price_mode)
                if forward is None or forward <= 0.0:
                    continue
                val_ts = _NY_TZ.localize(datetime.datetime.combine(row_dt.date(), datetime.time(17, 0)))
                pr = self._build_pricer_from_row(
                    canonical_symbol=leg_symbol,
                    row=row,
                    valuation_ts=val_ts,
                    forward=forward,
                    curve_name=curve_name,
                    curve_kwargs=curve_kwargs,
                    curve_memo=curve_memo,
                    price_mode=price_mode,
                    source="BARCHART_EOD_SNAPSHOT",
                    use_ql_calculator=use_ql_calculator,
                )
                if pr is not None:
                    cp_pricers[leg_symbol] = pr

        result: Dict[str, List[QLSTIRFutureOptionPricer]] = {}
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

    def _option_timeseries(self, request: Dict[str, Any]) -> Dict[str, List[QLSTIRFutureOptionPricer]]:
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
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})

        requested_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for raw in symbols:
            parsed = _parse_option_request_symbol(raw)
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

        option_symbols_bc = sorted({_canonical_to_barchart_option(sym) for sym in expanded_needed})
        contracts = sorted({_contract_to_barchart_contract(_canonical_underlying(sym)) for sym in expanded_needed})
        all_syms = option_symbols_bc + contracts
        data = self._fetch_barchart_eod_series(
            symbols=all_syms,
            start=start_date,
            end=end_date,
            show_tqdm=show_tqdm,
        )

        curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]] = {}
        cp_by_symbol_date: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]] = defaultdict(dict)

        for leg_symbol in expanded_needed:
            opt_bc = _canonical_to_barchart_option(leg_symbol)
            fut_bc = _contract_to_barchart_contract(_canonical_underlying(leg_symbol))
            opt_df = data.get(opt_bc)
            fut_df = data.get(fut_bc)
            if opt_df is None or opt_df.empty or fut_df is None or fut_df.empty:
                continue

            for row_dt, row_series in opt_df.iterrows():
                row_day = pd.Timestamp(row_dt).date()
                if row_day < start_date or row_day > end_date:
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
                    source="BARCHART_EOD_TIMESERIES",
                    use_ql_calculator=use_ql_calculator,
                )
                if pr is not None:
                    cp_by_symbol_date[leg_symbol][row_day] = pr

        result: Dict[str, List[QLSTIRFutureOptionPricer]] = {}
        for raw, norm in requested.items():
            if norm.endswith("S"):
                c_key = f"{norm[:-1]}C"
                p_key = f"{norm[:-1]}P"
                c_map = cp_by_symbol_date.get(c_key, {})
                p_map = cp_by_symbol_date.get(p_key, {})
                dates = sorted(set(c_map.keys()).intersection(p_map.keys()))
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
                result[raw] = [pr_map[d] for d in sorted(pr_map.keys())]

        return result

    def _qs_atm_term_structure(self, request: Dict[str, Any]) -> Dict[str, List[Any]]:
        force_refresh = bool(request.get("force_refresh", False))
        for attempt in (0, 1):
            try:
                qsf = self._quikstrike_client(force_refresh=force_refresh or attempt == 1)
                out = qsf.fetch_latest_atm_term_structures([QuikVolProductID.SR3])
                return {"qs_atm_term_structure": [out]}
            except Exception:
                if attempt == 1:
                    raise
        raise RuntimeError("QuikStrike ATM term structure fetch failed")

    def _qs_timeseries(self, request: Dict[str, Any]) -> Dict[str, List[Any]]:
        if "start" not in request or "end" not in request:
            raise ValueError("qs_timeseries requires start and end")
        if "queries" not in request:
            raise ValueError("qs_timeseries requires queries")
        force_refresh = bool(request.get("force_refresh", False))

        start_dt = _as_datetime(request["start"]).replace(tzinfo=None)
        end_dt = _as_datetime(request["end"]).replace(tzinfo=None)

        qlist: List[QuikVolQuery] = []
        for q in request.get("queries", []):
            if not isinstance(q, dict):
                raise ValueError("qs_timeseries queries must be dictionaries")
            raw_symbol = str(q.get("globex_symbol", "")).strip().upper()
            m = re.fullmatch(r"^(SR3|SFR|SQ)([FGHJKMNQUVXZ]\d{2})$", raw_symbol)
            if not m:
                raise ValueError(f"qs_timeseries supports SR3-only symbols; got {raw_symbol!r}")
            globex_symbol = f"SR3{m.group(2)}"
            vt_name = str(q.get("qv_value_type", "")).strip()
            if not vt_name:
                raise ValueError("qv_value_type is required for each qs_timeseries query")
            try:
                vt = QuikVolValueType[vt_name]
            except KeyError as exc:
                raise ValueError(f"Unknown QuikVolValueType: {vt_name}") from exc

            qlist.append(
                QuikVolQuery(
                    globex_symbol=globex_symbol,
                    qv_value_type=vt,
                    delta=int(q.get("delta", 0) or 0),
                    strike=float(q.get("strike", 0.0) or 0.0),
                    option_type=q.get("option_type", "Straddle"),
                )
            )

        for attempt in (0, 1):
            try:
                qsf = self._quikstrike_client(force_refresh=force_refresh or attempt == 1)
                df = qsf.fetch_quikvol_timeseries(
                    start_date=start_dt,
                    end_date=end_dt,
                    queries=qlist,
                )
                return {"qs_timeseries": [df]}
            except Exception:
                if attempt == 1:
                    raise
        raise RuntimeError("QuikStrike timeseries fetch failed")

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
            elif endpoint == "qs_atm_term_structure":
                out = self._qs_atm_term_structure(request)
            elif endpoint == "qs_timeseries":
                out = self._qs_timeseries(request)
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
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="stirfo-mdp") as pool:
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
