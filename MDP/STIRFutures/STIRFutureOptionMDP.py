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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import numpy as np
import pandas as pd
import pytz
import QuantLib as ql
import rateslib as rl
import requests
from scipy.optimize import minimize
from scipy.stats import norm

from Caching.DiskCacheMixin import DiskCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher
from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue

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
_QS_STIR_ROOT_ALIAS_TO_GLOBEX: Dict[str, str] = {
    "SR3": "SR3",
    "SFR": "SR3",
    "SQ": "SR3",
}
_QS_PRICE_VALUE_TYPES = {
    "ATMPRICE",
    "CALLPRICE",
    "PUTPRICE",
    "CALLRATIOPRICE",
    "PUTRATIOPRICE",
    "CALLSKEWPRICE",
    "PUTSKEWPRICE",
    "RISKREVERSALPRICE",
    "BUTTERFLYPRICE",
    "PRICEBYSTRIKE",
}


@dataclass(frozen=True)
class STIRFutureOptionSABRParams:
    alpha: float
    beta: float
    rho: float
    nu: float
    forward_price: float
    forward_rate: float
    time_to_expiry: float
    expiry_date: datetime.date
    as_of: datetime.date

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alpha": float(self.alpha),
            "beta": float(self.beta),
            "rho": float(self.rho),
            "nu": float(self.nu),
            "forward_price": float(self.forward_price),
            "forward_rate": float(self.forward_rate),
            "time_to_expiry": float(self.time_to_expiry),
            "expiry_date": self.expiry_date.isoformat(),
            "as_of": self.as_of.isoformat(),
        }

    @classmethod
    def from_dict(cls, row: Dict[str, Any]) -> "STIRFutureOptionSABRParams":
        return cls(
            alpha=float(row["alpha"]),
            beta=float(row["beta"]),
            rho=float(row["rho"]),
            nu=float(row["nu"]),
            forward_price=float(row["forward_price"]),
            forward_rate=float(row["forward_rate"]),
            time_to_expiry=float(row["time_to_expiry"]),
            expiry_date=datetime.date.fromisoformat(str(row["expiry_date"])),
            as_of=datetime.date.fromisoformat(str(row["as_of"])),
        )


@dataclass(frozen=True)
class STIRFutureOptionSmilePoint:
    label: str
    right: str
    delta_abs: float
    strike_price: float
    strike_rate: float
    iv_normal_price: float
    iv_normal_bps: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": str(self.label),
            "right": str(self.right),
            "delta_abs": float(self.delta_abs),
            "strike_price": float(self.strike_price),
            "strike_rate": float(self.strike_rate),
            "iv_normal_price": float(self.iv_normal_price),
            "iv_normal_bps": float(self.iv_normal_bps),
        }

    @classmethod
    def from_dict(cls, row: Dict[str, Any]) -> "STIRFutureOptionSmilePoint":
        return cls(
            label=str(row["label"]),
            right=str(row["right"]),
            delta_abs=float(row["delta_abs"]),
            strike_price=float(row["strike_price"]),
            strike_rate=float(row["strike_rate"]),
            iv_normal_price=float(row["iv_normal_price"]),
            iv_normal_bps=float(row["iv_normal_bps"]),
        )


def _as_float_array(values: Union[float, Sequence[float], np.ndarray]) -> Tuple[np.ndarray, bool]:
    scalar = np.isscalar(values)
    if scalar:
        arr = np.asarray([values], dtype=float)
    else:
        arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    return arr, bool(scalar)


@dataclass(frozen=True)
class STIRFutureOptionSABRSmile:
    source: str
    symbol: str
    underlying_contract: str
    quote_timestamp: datetime.datetime
    params: STIRFutureOptionSABRParams
    points: Tuple[STIRFutureOptionSmilePoint, ...]

    def to_dict(self) -> Dict[str, Any]:
        quote_ts = self.quote_timestamp
        if isinstance(quote_ts, pd.Timestamp):
            quote_ts = quote_ts.to_pydatetime()
        return {
            "source": str(self.source),
            "symbol": str(self.symbol),
            "underlying_contract": str(self.underlying_contract),
            "quote_timestamp": quote_ts.isoformat(),
            "params": self.params.to_dict(),
            "points": [pt.to_dict() for pt in self.points],
        }

    @classmethod
    def from_dict(cls, row: Dict[str, Any]) -> "STIRFutureOptionSABRSmile":
        quote_ts = row.get("quote_timestamp")
        if isinstance(quote_ts, pd.Timestamp):
            quote_ts = quote_ts.to_pydatetime()
        elif isinstance(quote_ts, str):
            quote_ts = pd.Timestamp(quote_ts).to_pydatetime()
        if not isinstance(quote_ts, datetime.datetime):
            raise ValueError(f"Invalid quote_timestamp for SABR smile: {quote_ts!r}")
        return cls(
            source=str(row["source"]),
            symbol=str(row["symbol"]),
            underlying_contract=str(row["underlying_contract"]),
            quote_timestamp=quote_ts,
            params=STIRFutureOptionSABRParams.from_dict(dict(row["params"])),
            points=tuple(STIRFutureOptionSmilePoint.from_dict(dict(pt)) for pt in row.get("points", [])),
        )

    @staticmethod
    def _normalize_delta_inputs(
        deltas: Union[float, Sequence[float], np.ndarray],
        right: Union[str, Sequence[str]],
    ) -> Tuple[np.ndarray, List[str], bool]:
        delta_arr, scalar = _as_float_array(deltas)
        abs_delta = np.abs(np.asarray(delta_arr, dtype=float))
        if abs_delta.size == 0:
            raise ValueError("deltas must not be empty")
        abs_delta = np.where(abs_delta > 1.0, abs_delta / 100.0, abs_delta)
        if np.any(~np.isfinite(abs_delta)) or np.any(abs_delta <= 0.0) or np.any(abs_delta >= 1.0):
            raise ValueError(f"delta inputs must be in (0,1) or (0,100): {deltas!r}")

        if isinstance(right, str):
            rights = [str(right).strip().upper()] * len(abs_delta)
        else:
            rights = [str(r).strip().upper() for r in list(right)]
            if len(rights) != len(abs_delta):
                raise ValueError("right sequence must match deltas length")

        if any(r not in {"C", "P"} for r in rights):
            raise ValueError(f"right must be 'C', 'P', or matching sequence, got {right!r}")
        return abs_delta, rights, scalar

    def price_to_rate(self, strikes: Union[float, Sequence[float], np.ndarray]) -> Union[float, np.ndarray]:
        values, scalar = _as_float_array(strikes)
        rates = 100.0 - values
        return float(rates[0]) if scalar else rates

    def rate_to_price(self, strikes: Union[float, Sequence[float], np.ndarray]) -> Union[float, np.ndarray]:
        values, scalar = _as_float_array(strikes)
        prices = 100.0 - values
        return float(prices[0]) if scalar else prices

    def normal_vol(
        self,
        strikes: Union[float, Sequence[float], np.ndarray],
        strike_space: str = "price",
        vol_units: str = "price",
    ) -> Union[float, np.ndarray]:
        strike_token = str(strike_space or "price").strip().lower()
        if strike_token not in {"price", "rate"}:
            raise ValueError(f"Unsupported strike_space: {strike_space}")

        unit_token = str(vol_units or "price").strip().lower()
        if unit_token not in {"price", "bps"}:
            raise ValueError(f"Unsupported vol_units: {vol_units}")

        raw, scalar = _as_float_array(strikes)
        model_strikes = np.asarray(self.rate_to_price(raw), dtype=float) if strike_token == "rate" else raw
        vols = np.array(
            [
                _sabr_normal_vol(
                    strike=float(k),
                    forward=float(self.params.forward_price),
                    time_to_expiry=float(self.params.time_to_expiry),
                    alpha=float(self.params.alpha),
                    beta=float(self.params.beta),
                    rho=float(self.params.rho),
                    nu=float(self.params.nu),
                )
                for k in model_strikes
            ],
            dtype=float,
        )
        if unit_token == "bps":
            vols = vols * 100.0
        return float(vols[0]) if scalar else vols

    def delta_to_strike(
        self,
        deltas: Union[float, Sequence[float], np.ndarray],
        right: Union[str, Sequence[str]],
        strike_space: str = "price",
    ) -> Union[float, np.ndarray]:
        strike_token = str(strike_space or "price").strip().lower()
        if strike_token not in {"price", "rate"}:
            raise ValueError(f"Unsupported strike_space: {strike_space}")

        abs_delta, rights, scalar = self._normalize_delta_inputs(deltas, right)
        atm_vol = _sabr_normal_vol(
            strike=float(self.params.forward_price),
            forward=float(self.params.forward_price),
            time_to_expiry=float(self.params.time_to_expiry),
            alpha=float(self.params.alpha),
            beta=float(self.params.beta),
            rho=float(self.params.rho),
            nu=float(self.params.nu),
        )
        if not math.isfinite(atm_vol) or atm_vol <= 0.0:
            raise ValueError(f"Invalid ATM normal vol for SABR delta inversion: {atm_vol}")

        out: List[float] = []
        for d_abs, rgt in zip(abs_delta, rights):
            sigma = float(atm_vol)
            strike = float(self.params.forward_price)
            for _ in range(32):
                strike_next = _normal_delta_to_strike(
                    delta_abs=float(d_abs),
                    vol_normal=float(sigma),
                    forward=float(self.params.forward_price),
                    time_to_expiry=float(self.params.time_to_expiry),
                    right=rgt,
                )
                sigma_next = _sabr_normal_vol(
                    strike=float(strike_next),
                    forward=float(self.params.forward_price),
                    time_to_expiry=float(self.params.time_to_expiry),
                    alpha=float(self.params.alpha),
                    beta=float(self.params.beta),
                    rho=float(self.params.rho),
                    nu=float(self.params.nu),
                )
                strike = float(strike_next)
                if not math.isfinite(sigma_next) or sigma_next <= 0.0:
                    break
                if abs(float(sigma_next) - float(sigma)) <= 1e-12 * max(1.0, abs(float(sigma))):
                    sigma = float(sigma_next)
                    break
                sigma = float(sigma_next)
            strike = _normal_delta_to_strike(
                delta_abs=float(d_abs),
                vol_normal=float(sigma),
                forward=float(self.params.forward_price),
                time_to_expiry=float(self.params.time_to_expiry),
                right=rgt,
            )
            out.append(float(strike))

        strikes_arr = np.asarray(out, dtype=float)
        if strike_token == "rate":
            strikes_arr = np.asarray(self.price_to_rate(strikes_arr), dtype=float)
        return float(strikes_arr[0]) if scalar else strikes_arr

    def normal_vol_for_deltas(
        self,
        deltas: Union[float, Sequence[float], np.ndarray],
        right: Union[str, Sequence[str]],
        strike_space_out: str = "price",
        vol_units: str = "price",
    ) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
        strikes = self.delta_to_strike(deltas=deltas, right=right, strike_space=strike_space_out)
        vols = self.normal_vol(strikes, strike_space=strike_space_out, vol_units=vol_units)
        return strikes, vols


def _normal_delta_to_strike(
    *,
    delta_abs: float,
    vol_normal: float,
    forward: float,
    time_to_expiry: float,
    right: str,
) -> float:
    right_token = str(right or "").strip().upper()
    if right_token not in {"C", "P"}:
        raise ValueError(f"Unsupported option right for delta inversion: {right}")
    target = float(delta_abs)
    if target <= 0.0 or target >= 1.0:
        raise ValueError(f"delta_abs must be in (0,1): {delta_abs}")
    scale = float(vol_normal) * math.sqrt(max(float(time_to_expiry), 1e-12))
    call_delta = target if right_token == "C" else (1.0 - target)
    return float(forward) - scale * float(norm.ppf(call_delta))


def _sabr_normal_vol(
    *,
    strike: float,
    forward: float,
    time_to_expiry: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> float:
    eps = 1e-12
    f = float(forward)
    k = float(strike)
    t = max(float(time_to_expiry), 0.0)
    a = float(alpha)
    b = float(beta)
    r = float(rho)
    n = float(nu)

    if abs(f - k) < eps:
        correction = (
            ((b - 1.0) * (b - 2.0) * a * a) / (24.0 * (f ** (2.0 - 2.0 * b)))
            + (r * b * n * a) / (4.0 * (f ** (1.0 - b)))
            + ((2.0 - 3.0 * r * r) * n * n) / 24.0
        )
        return a * (f ** b) * (1.0 + correction * t)

    log_fk = math.log(f / k)
    f_mid = math.sqrt(f * k)

    if abs(b - 1.0) < eps:
        zeta = (n / a) * log_fk
    else:
        zeta = (n / a) * ((f ** (1.0 - b) - k ** (1.0 - b)) / (1.0 - b))

    disc = math.sqrt(max(1.0 - 2.0 * r * zeta + zeta * zeta, 1e-18))
    x_zeta = math.log((disc + zeta - r) / (1.0 - r))
    zeta_over_x = 1.0 if abs(x_zeta) < eps else zeta / x_zeta

    if abs(b) < eps:
        prefactor = a
    elif abs(b - 1.0) < eps:
        prefactor = a * (f - k) / log_fk
    else:
        prefactor = a * (1.0 - b) * (f - k) / (f ** (1.0 - b) - k ** (1.0 - b))

    correction = (
        ((b - 1.0) * (b - 2.0) * a * a) / (24.0 * (f_mid ** (2.0 - 2.0 * b)))
        + (r * b * n * a) / (4.0 * (f_mid ** (1.0 - b)))
        + ((2.0 - 3.0 * r * r) * n * n) / 24.0
    )
    return prefactor * zeta_over_x * (1.0 + correction * t)


def _collapse_duplicate_strikes(
    strikes: np.ndarray,
    vols: np.ndarray,
    *,
    tol: float = 1e-10,
) -> Tuple[np.ndarray, np.ndarray]:
    if strikes.size == 0:
        return strikes, vols
    order = np.argsort(strikes)
    srt_strikes = strikes[order]
    srt_vols = vols[order]
    out_strikes: List[float] = []
    out_vols: List[float] = []
    bucket: List[float] = [float(srt_vols[0])]
    anchor = float(srt_strikes[0])
    for strike, vol in zip(srt_strikes[1:], srt_vols[1:]):
        if abs(float(strike) - anchor) <= tol:
            bucket.append(float(vol))
            continue
        out_strikes.append(anchor)
        out_vols.append(float(sum(bucket) / len(bucket)))
        anchor = float(strike)
        bucket = [float(vol)]
    out_strikes.append(anchor)
    out_vols.append(float(sum(bucket) / len(bucket)))
    return np.asarray(out_strikes, dtype=float), np.asarray(out_vols, dtype=float)


def _calibrate_sabr_normal_from_delta_points(
    *,
    forward: float,
    time_to_expiry: float,
    market_points: Sequence[Tuple[float, float, str]],
    beta: float = 0.5,
) -> STIRFutureOptionSABRParams:
    if not math.isfinite(forward) or forward <= 0.0:
        raise ValueError(f"Invalid forward for SABR calibration: {forward}")
    if not math.isfinite(time_to_expiry) or time_to_expiry <= 0.0:
        raise ValueError(f"Invalid time_to_expiry for SABR calibration: {time_to_expiry}")
    if len(market_points) < 6:
        raise ValueError("SABR calibration requires at least 6 valid points.")

    call_count = sum(1 for _, _, right in market_points if str(right).upper() == "C")
    put_count = sum(1 for _, _, right in market_points if str(right).upper() == "P")
    if call_count < 2 or put_count < 2:
        raise ValueError("SABR calibration requires at least 2 call points and 2 put points.")

    strikes: List[float] = []
    vols: List[float] = []
    for delta_abs, vol_normal, right in market_points:
        if not math.isfinite(vol_normal) or vol_normal <= 0.0:
            continue
        strike = _normal_delta_to_strike(
            delta_abs=float(delta_abs),
            vol_normal=float(vol_normal),
            forward=float(forward),
            time_to_expiry=float(time_to_expiry),
            right=str(right),
        )
        if not math.isfinite(strike) or strike <= 0.0:
            continue
        strikes.append(float(strike))
        vols.append(float(vol_normal))

    if len(strikes) < 6:
        raise ValueError("SABR calibration requires at least 6 strike-vol points after delta inversion.")

    strikes_arr = np.asarray(strikes, dtype=float)
    vols_arr = np.asarray(vols, dtype=float)
    order = np.argsort(strikes_arr)
    strikes_arr = strikes_arr[order]
    vols_arr = vols_arr[order]

    collapsed_strikes, collapsed_vols = _collapse_duplicate_strikes(strikes_arr, vols_arr)
    if collapsed_strikes.size == 0:
        raise ValueError("No SABR calibration points remain after collapsing duplicate strikes.")

    atm_idx = int(np.argmin(np.abs(collapsed_strikes - float(forward))))
    atm_vol = float(collapsed_vols[atm_idx])
    if not math.isfinite(atm_vol) or atm_vol <= 0.0:
        raise ValueError(f"Invalid ATM normal vol seed for SABR calibration: {atm_vol}")

    near_forward_width = 2.0 * atm_vol * math.sqrt(float(time_to_expiry))
    weights = np.ones_like(vols_arr, dtype=float)
    weights[np.abs(strikes_arr - float(forward)) <= near_forward_width] *= 2.0

    def _objective(x: np.ndarray) -> float:
        alpha, rho, nu = (float(x[0]), float(x[1]), float(x[2]))
        if alpha <= 0.0 or nu <= 0.0 or abs(rho) >= 1.0:
            return 1e12
        try:
            model = np.array(
                [
                    _sabr_normal_vol(
                        strike=float(k),
                        forward=float(forward),
                        time_to_expiry=float(time_to_expiry),
                        alpha=alpha,
                        beta=float(beta),
                        rho=rho,
                        nu=nu,
                    )
                    for k in strikes_arr
                ],
                dtype=float,
            )
        except Exception:
            return 1e12
        if not np.all(np.isfinite(model)):
            return 1e12
        err = model - vols_arr
        return float(np.sum(weights * err * err))

    alpha0 = float(atm_vol / (float(forward) ** float(beta)))
    result = minimize(
        _objective,
        x0=np.asarray([alpha0, -0.1, 0.3], dtype=float),
        method="Nelder-Mead",
        options={"maxiter": 10000, "xatol": 1e-10, "fatol": 1e-12},
    )

    alpha_cal, rho_cal, nu_cal = (float(result.x[0]), float(result.x[1]), float(result.x[2]))
    if alpha_cal <= 0.0 or nu_cal <= 0.0 or abs(rho_cal) >= 1.0:
        raise ValueError(f"SABR calibration returned invalid params: {result.x!r}")

    return STIRFutureOptionSABRParams(
        alpha=alpha_cal,
        beta=float(beta),
        rho=rho_cal,
        nu=nu_cal,
        forward_price=float(forward),
        forward_rate=100.0 - float(forward),
        time_to_expiry=float(time_to_expiry),
        expiry_date=datetime.date.today(),
        as_of=datetime.date.today(),
    )


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


def _contract_root(contract: str) -> Optional[str]:
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        return None
    return _ROOT_ALIAS_MAP[m.group("root").upper()]


def _is_sofr_style_option_contract(contract: Optional[str]) -> bool:
    root = _contract_root(str(contract or ""))
    return root in (_SFR_UNDERLYING_ROOTS | {"SFR"})


def _decode_sofr_style_strike_token(strike4: str) -> float:
    token_int = int(str(strike4).strip())
    raw = float(token_int) / 100.0
    lo = int(math.floor((raw - 0.25) * 16.0))
    hi = int(math.ceil((raw + 0.25) * 16.0))
    best: Optional[Tuple[float, float]] = None

    for n in range(lo, hi + 1):
        candidate = float(n) / 16.0
        if int(math.floor(candidate * 100.0 + 1e-9)) != token_int:
            continue
        dist = abs(candidate - raw)
        if best is None or dist < best[0]:
            best = (dist, candidate)

    if best is not None:
        return float(best[1])
    return raw


def _format_strike4(strike: float, *, contract: Optional[str] = None) -> str:
    strike_val = float(strike)
    if _is_sofr_style_option_contract(contract):
        scaled = int(math.floor(strike_val * 100.0 + 1e-9))
    else:
        scaled = int(round(strike_val * 100.0))
    return str(scaled).zfill(4)


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


def _contract_month_distance(contract: str, as_of: datetime.date) -> Optional[int]:
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        return None
    code = str(m.group("code")).upper()
    month = _MONTH_CODE_TO_NUM[code[0]]
    year = 2000 + int(code[1:])
    return (year - as_of.year) * 12 + (month - as_of.month)


def _cme_listed_strikes_for_contract_forward(
    *,
    contract: str,
    forward: float,
    as_of: datetime.date,
) -> Optional[List[float]]:
    if not _is_sofr_style_option_contract(contract):
        return None

    month_distance = _contract_month_distance(contract, as_of=as_of)
    if month_distance is None:
        return None

    is_front_eight = month_distance <= 7
    fine_step = 0.0625 if is_front_eight else 0.125
    fine_half_width_steps = int(round(1.5 / fine_step))
    coarse_step = 0.25
    coarse_half_width_steps = int(round(5.5 / coarse_step))

    fine_atm = _atm_strike_from_forward(float(forward), step=float(fine_step))
    coarse_atm = _atm_strike_from_forward(float(forward), step=float(coarse_step))
    ladders = list(_strike_ladder(center=float(fine_atm), step=float(fine_step), half_width_steps=int(fine_half_width_steps)))
    ladders.extend(_strike_ladder(center=float(coarse_atm), step=float(coarse_step), half_width_steps=int(coarse_half_width_steps)))

    out: List[float] = []
    seen = set()
    for strike in sorted(float(x) for x in ladders):
        key = round(float(strike), 8)
        if key in seen:
            continue
        seen.add(key)
        out.append(float(strike))
    return out


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


def _normalize_qs_stir_globex_symbol(token: str) -> str:
    t = str(token or "").strip().upper().replace("/", "")
    roots = "|".join(sorted([re.escape(r) for r in _QS_STIR_ROOT_ALIAS_TO_GLOBEX.keys()], key=len, reverse=True))
    m_listed = re.fullmatch(rf"^(?P<root>{roots})(?P<code>[FGHJKMNQUVXZ]\d{{2}})$", t)
    if m_listed is not None:
        root = _QS_STIR_ROOT_ALIAS_TO_GLOBEX[m_listed.group("root")]
        code = m_listed.group("code").upper()
        return f"{root}{code}"

    m_cm = re.fullmatch(rf"^(?P<root>{roots})_(?P<days>\d{{1,3}})$", t)
    if m_cm is not None:
        root = _QS_STIR_ROOT_ALIAS_TO_GLOBEX[m_cm.group("root")]
        days = int(m_cm.group("days"))
        if days <= 0:
            raise ValueError(f"Invalid constant-maturity tenor in symbol {token!r}: days must be > 0")
        return f"{root}_{days}"

    raise ValueError(
        "qs_timeseries supports SR3 listed contracts (e.g. SR3Z26/SFRZ26/SQZ26) "
        "and SR3 constant maturity aliases (e.g. SR3_60); "
        f"got {token!r}"
    )


def _parse_qs_stir_globex_symbol(token: str, *, as_of: Optional[datetime.date] = None) -> Dict[str, Any]:
    sym = _normalize_qs_stir_globex_symbol(token)
    roots = "|".join(sorted([re.escape(r) for r in set(_QS_STIR_ROOT_ALIAS_TO_GLOBEX.values())], key=len, reverse=True))

    m_listed = re.fullmatch(rf"^(?P<root>{roots})(?P<code>[FGHJKMNQUVXZ]\d{{2}})$", sym)
    if m_listed is not None:
        root_globex = m_listed.group("root")
        code = m_listed.group("code").upper()
        canonical_contract = f"{_ROOT_ALIAS_MAP[root_globex]}{code}"
        underlying_contract = _option_contract_to_underlying_contract(canonical_contract)
        barchart_contract = _contract_to_barchart_contract(underlying_contract)
        return {
            "kind": "listed",
            "globex_symbol": sym,
            "root_globex": root_globex,
            "cm_days": None,
            "contract_code": code,
            "canonical_contract": canonical_contract,
            "underlying_contract": underlying_contract,
            "barchart_contract": barchart_contract,
        }

    m_cm = re.fullmatch(rf"^(?P<root>{roots})_(?P<days>\d{{1,3}})$", sym)
    if m_cm is not None:
        return {
            "kind": "cm",
            "globex_symbol": sym,
            "root_globex": m_cm.group("root"),
            "cm_days": int(m_cm.group("days")),
            "contract_code": None,
            "canonical_contract": None,
            "underlying_contract": None,
            "barchart_contract": None,
        }

    raise ValueError(f"Unsupported qs_timeseries STIR symbol: {token!r}")


def _qs_front_barchart_contract_for_date(*, root_globex: str, as_of: datetime.date) -> str:
    root_token = str(root_globex or "").strip().upper()
    if not root_token:
        raise ValueError("Missing STIR root for constant maturity symbol.")
    if root_token not in _ROOT_ALIAS_MAP:
        raise ValueError(f"Unsupported STIR root for constant maturity symbol: {root_globex!r}")
    cm_root = _ROOT_ALIAS_MAP[root_token]
    front_contract = _resolve_cm_contract(cm_root=cm_root, cm_rank=1, as_of=as_of)
    return _contract_to_barchart_contract(front_contract)


def _qs_stir_normal_vol_from_value(value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        return float("nan")
    # QuikStrike STIR vol values are typically in bps-vol units.
    return v / 100.0 if abs(v) > 5.0 else v


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
    contract = token.split("|", 1)[0]
    strike4 = token.split("|", 1)[1][:-1]
    if _is_sofr_style_option_contract(contract):
        return _decode_sofr_style_strike_token(strike4)
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
                spec = _parse_option_request_symbol(raw)
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
            "cache_version": "stirfo_barchart_pricer_window_v1",
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
        return f"STIRFO_BC_WINDOW::{digest}"

    def _serialize_pricer_window(
        self,
        pricers_by_symbol_date: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for symbol, by_day in sorted(pricers_by_symbol_date.items(), key=lambda kv: str(kv[0])):
            plist = [self._serialize_pricer(pr) for _, pr in sorted(by_day.items(), key=lambda kv: kv[0])]
            payload[str(symbol)] = plist
        return {"schema": 1, "result": payload}

    def _deserialize_pricer_window(
        self,
        cached: Any,
    ) -> Optional[Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]]]:
        if not isinstance(cached, dict):
            return None
        if int(cached.get("schema", 0)) != 1:
            return None
        raw = cached.get("result")
        if not isinstance(raw, dict):
            return None
        out: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]] = defaultdict(dict)
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

    @staticmethod
    def _normalize_sabr_smile_deltas(raw: Any) -> List[int]:
        if raw is None:
            raw = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
        if isinstance(raw, (int, float)):
            values = [raw]
        else:
            values = list(raw)
        out: List[int] = []
        for value in values:
            delta = int(round(float(value)))
            if delta <= 0 or delta >= 100:
                raise ValueError(f"SABR smile deltas must be in (0,100): {value!r}")
            out.append(delta)
        return sorted(set(out))

    def _validate_sabr_smile_request(
        self,
        request: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], datetime.date, List[int], str, Dict[str, Any], bool, bool]:
        if "as_of" not in request:
            raise ValueError("sabr_smile requires 'as_of'")
        if "beta" in request:
            raise ValueError("sabr_smile fixes beta=0.5; request must not include 'beta'")

        as_of = _as_date(request["as_of"])
        src = str(self.source).upper()

        if src == "STIRFO_DUAL-QL":
            if "globex_symbol" not in request:
                raise ValueError("sabr_smile requires 'globex_symbol' for STIRFO_DUAL-QL")
            symbol_info = _parse_qs_stir_globex_symbol(str(request.get("globex_symbol", "")).strip().upper(), as_of=as_of)
            raw_symbol = str(symbol_info["globex_symbol"])
        elif src == "BARCHART_STIRFO-QL":
            raw_contract = request.get("symbol", request.get("contract", request.get("globex_symbol")))
            if raw_contract is None:
                raise ValueError("sabr_smile requires 'symbol' or 'contract' for BARCHART_STIRFO-QL")
            token = str(raw_contract).strip().upper().replace("/", "")
            if "|" in token:
                token = token.split("|", 1)[0]
            if not token:
                raise ValueError("sabr_smile requires a non-empty listed or CM option contract for BARCHART_STIRFO-QL")
            try:
                contract_spec = _parse_contract_token(token)
            except Exception as exc:
                raise ValueError(
                    "sabr_smile for BARCHART_STIRFO-QL requires a listed or CM option contract such as SR3Z30, SFRCM1, or S0CM1"
                ) from exc
            if str(contract_spec.get("contract_selector")) == "explicit":
                request_symbol = token
                symbol_info = {
                    "kind": "listed",
                    "request_symbol": request_symbol,
                    "contract": str(contract_spec["contract"]),
                    "underlying_contract": _option_contract_to_underlying_contract(str(contract_spec["contract"])),
                }
            else:
                request_symbol = f"{str(contract_spec['cm_root']).upper()}CM{int(contract_spec['cm_rank'])}"
                symbol_info = {
                    "kind": "cm",
                    "request_symbol": request_symbol,
                    "contract_selector": "cm",
                    "cm_root": str(contract_spec["cm_root"]).upper(),
                    "cm_rank": int(contract_spec["cm_rank"]),
                }
            raw_symbol = request_symbol
        else:
            raise NotImplementedError(
                f"SABR smile fetcher is only available for sources 'STIRFO_DUAL-QL' and 'BARCHART_STIRFO-QL', got {self.source!r}"
            )

        deltas = self._normalize_sabr_smile_deltas(request.get("deltas"))
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})
        force_refresh = bool(request.get("force_refresh", False))
        show_tqdm = bool(request.get("show_tqdm", False))
        return raw_symbol, symbol_info, as_of, deltas, curve_name, curve_kwargs, force_refresh, show_tqdm

    def _build_sabr_smile_qs_request(
        self,
        *,
        globex_symbol: str,
        as_of: datetime.date,
        deltas: Sequence[int],
        curve_name: str,
        curve_kwargs: Dict[str, Any],
        force_refresh: bool,
        show_tqdm: bool,
    ) -> Dict[str, Any]:
        queries: List[Dict[str, Any]] = []
        for delta in deltas:
            queries.append(
                {
                    "globex_symbol": globex_symbol,
                    "qv_value_type": "Call",
                    "delta": int(delta),
                    "option_type": "Call",
                }
            )
        for delta in deltas:
            queries.append(
                {
                    "globex_symbol": globex_symbol,
                    "qv_value_type": "Put",
                    "delta": int(delta),
                    "option_type": "Put",
                }
            )
        return {
            "endpoint": "qs_timeseries",
            "start": as_of,
            "end": as_of,
            "queries": queries,
            "options": True,
            "curve_name": curve_name,
            "curve_kwargs": dict(curve_kwargs or {}),
            "force_refresh": force_refresh,
            "show_tqdm": show_tqdm,
        }

    def _build_sabr_smile_snapshot_request(
        self,
        *,
        request_symbol: str,
        as_of: datetime.date,
        deltas: Sequence[int],
        curve_name: str,
        curve_kwargs: Dict[str, Any],
        force_refresh: bool,
        show_tqdm: bool,
    ) -> Dict[str, Any]:
        symbols: List[str] = []
        for delta in deltas:
            symbols.append(f"{request_symbol}|{int(delta)}DC")
        for delta in deltas:
            symbols.append(f"{request_symbol}|{int(delta)}DP")
        return {
            "endpoint": "option_snapshot",
            "symbols": symbols,
            "timestamp": as_of,
            "curve_name": curve_name,
            "curve_kwargs": dict(curve_kwargs or {}),
            "use_ql_calculator": True,
            "force_refresh": force_refresh,
            "show_tqdm": show_tqdm,
        }

    def _select_sabr_smile_pricers(
        self,
        *,
        pricers_by_series: Dict[str, List[QLSTIRFutureOptionPricer]],
        as_of: datetime.date,
        deltas: Sequence[int],
    ) -> Dict[Tuple[str, int], QLSTIRFutureOptionPricer]:
        selected: Dict[Tuple[str, int], QLSTIRFutureOptionPricer] = {}
        available_dates: set[datetime.date] = set()

        for series_name, plist in pricers_by_series.items():
            series_label = str(series_name)
            series_right = self._qs_right_from_label_and_query(label=series_label, query={})
            series_delta = self._qs_delta_abs_from_label_and_query(label=series_label, query={})
            for pr in plist:
                quote_day = pr.quote_timestamp().astimezone(_NY_TZ).date()
                available_dates.add(quote_day)
                if quote_day != as_of:
                    continue
                meta = pr.meta() if callable(getattr(pr, "meta", None)) else {}
                qs_query = dict((meta or {}).get("qs_query") or {})
                label = str((meta or {}).get("qs_series_label", series_label))
                delta_raw = series_delta if series_delta is not None else self._qs_delta_abs_from_label_and_query(label=label, query=qs_query)
                right = series_right if series_right in {"C", "P"} else self._qs_right_from_label_and_query(label=label, query=qs_query)
                if delta_raw is None:
                    delta_raw = _to_float(qs_query.get("delta"))
                if delta_raw is None or right not in {"C", "P"}:
                    continue
                key = (right, int(round(float(delta_raw))))
                current = selected.get(key)
                if current is None or pr.quote_timestamp() > current.quote_timestamp():
                    selected[key] = pr

        missing: List[str] = []
        for delta in deltas:
            if ("C", int(delta)) not in selected:
                missing.append(f"{int(delta)}D Call")
            if ("P", int(delta)) not in selected:
                missing.append(f"{int(delta)}D Put")
        if missing:
            av = ", ".join(sorted(d.isoformat() for d in available_dates)) or "none"
            raise ValueError(f"Missing SABR smile legs for {as_of.isoformat()}: {missing}. Available quote dates: {av}.")
        return selected

    def _select_sabr_smile_snapshot_pricers(
        self,
        *,
        pricers_by_symbol: Dict[str, List[QLSTIRFutureOptionPricer]],
        as_of: datetime.date,
        deltas: Sequence[int],
    ) -> Tuple[Dict[Tuple[str, int], QLSTIRFutureOptionPricer], Dict[Tuple[str, int], str]]:
        selected: Dict[Tuple[str, int], QLSTIRFutureOptionPricer] = {}
        labels_by_key: Dict[Tuple[str, int], str] = {}
        available_dates: set[datetime.date] = set()

        for raw_symbol, plist in pricers_by_symbol.items():
            try:
                spec = _parse_option_request_symbol(str(raw_symbol))
            except Exception:
                continue
            if str(spec.get("selector")) != "delta":
                continue
            right = str(spec.get("right", "")).upper()
            delta_raw = _to_float(spec.get("delta"))
            if right not in {"C", "P"} or delta_raw is None:
                continue
            key = (right, int(round(float(delta_raw))))
            for pr in plist:
                quote_day = pr.quote_timestamp().astimezone(_NY_TZ).date()
                available_dates.add(quote_day)
                if quote_day != as_of:
                    continue
                current = selected.get(key)
                if current is None or pr.quote_timestamp() > current.quote_timestamp():
                    selected[key] = pr
                    labels_by_key[key] = str(raw_symbol)

        missing: List[str] = []
        for delta in deltas:
            if ("C", int(delta)) not in selected:
                missing.append(f"{int(delta)}D Call")
            if ("P", int(delta)) not in selected:
                missing.append(f"{int(delta)}D Put")
        if missing:
            av = ", ".join(sorted(d.isoformat() for d in available_dates)) or "none"
            raise ValueError(f"Missing SABR smile legs for {as_of.isoformat()}: {missing}. Available quote dates: {av}.")
        return selected, labels_by_key

    @staticmethod
    def _coerce_sabr_leg_market_points(
        selected_pricers: Dict[Tuple[str, int], QLSTIRFutureOptionPricer],
    ) -> Tuple[List[Tuple[float, float, str]], List[Tuple[str, int, QLSTIRFutureOptionPricer]]]:
        market_points: List[Tuple[float, float, str]] = []
        ordered: List[Tuple[str, int, QLSTIRFutureOptionPricer]] = []
        for key in sorted(selected_pricers.keys(), key=lambda item: (item[0], item[1])):
            right, delta = key
            pr = selected_pricers[key]
            iv_normal = float(pr.iv_normal())
            if not math.isfinite(iv_normal) or iv_normal <= 0.0:
                raise ValueError(f"Invalid normal vol for SABR smile leg {delta}D{right}: {iv_normal}")
            market_points.append((float(delta) / 100.0, iv_normal, str(right)))
            ordered.append((str(right), int(delta), pr))
        return market_points, ordered

    @staticmethod
    def _ensure_sabr_smile_pricer_consistency(
        selected_pricers: Dict[Tuple[str, int], QLSTIRFutureOptionPricer],
    ) -> Tuple[str, float, datetime.date]:
        pricers = list(selected_pricers.values())
        if not pricers:
            raise ValueError("No option pricers available for SABR smile calibration.")
        ref_underlying = str(pricers[0].underlying_symbol()).upper()
        ref_forward = float(pricers[0].forward())
        ref_expiry = pricers[0].expiry_date()
        for pr in pricers[1:]:
            if str(pr.underlying_symbol()).upper() != ref_underlying:
                raise ValueError("SABR smile legs do not agree on underlying contract.")
            if pr.expiry_date() != ref_expiry:
                raise ValueError("SABR smile legs do not agree on expiry date.")
            if not math.isclose(float(pr.forward()), ref_forward, rel_tol=0.0, abs_tol=1e-8):
                raise ValueError("SABR smile legs do not agree on forward price.")
        return ref_underlying, ref_forward, ref_expiry

    def _assemble_sabr_smile_result(
        self,
        *,
        raw_symbol: str,
        as_of: datetime.date,
        selected: Dict[Tuple[str, int], QLSTIRFutureOptionPricer],
        labels_by_key: Optional[Dict[Tuple[str, int], str]],
    ) -> STIRFutureOptionSABRSmile:
        underlying_contract, forward_price, expiry_date = self._ensure_sabr_smile_pricer_consistency(selected)
        time_to_expiry = (expiry_date - as_of).days / 365.0
        if time_to_expiry <= 0.0:
            raise ValueError(f"SABR smile requires positive time to expiry, got {time_to_expiry} for {expiry_date.isoformat()}")

        market_points, ordered_legs = self._coerce_sabr_leg_market_points(selected)
        params_seed = _calibrate_sabr_normal_from_delta_points(
            forward=float(forward_price),
            time_to_expiry=float(time_to_expiry),
            market_points=market_points,
            beta=0.5,
        )
        params = STIRFutureOptionSABRParams(
            alpha=float(params_seed.alpha),
            beta=0.5,
            rho=float(params_seed.rho),
            nu=float(params_seed.nu),
            forward_price=float(forward_price),
            forward_rate=100.0 - float(forward_price),
            time_to_expiry=float(time_to_expiry),
            expiry_date=expiry_date,
            as_of=as_of,
        )

        points: List[STIRFutureOptionSmilePoint] = []
        latest_quote = max(pr.quote_timestamp() for pr in selected.values())
        labels_by_key = dict(labels_by_key or {})
        for right, delta, pr in ordered_legs:
            strike_price = _normal_delta_to_strike(
                delta_abs=float(delta) / 100.0,
                vol_normal=float(pr.iv_normal()),
                forward=float(forward_price),
                time_to_expiry=float(time_to_expiry),
                right=str(right),
            )
            strike_rate = 100.0 - float(strike_price)
            iv_normal_bps = float(pr.iv_normal_bps()) if math.isfinite(float(pr.iv_normal_bps())) else float(pr.iv_normal()) * 100.0
            label = labels_by_key.get((str(right), int(delta)))
            if not label:
                label = str((pr.meta() or {}).get("qs_series_label", pr.symbol()))
            points.append(
                STIRFutureOptionSmilePoint(
                    label=label,
                    right=str(right),
                    delta_abs=float(delta),
                    strike_price=float(strike_price),
                    strike_rate=float(strike_rate),
                    iv_normal_price=float(pr.iv_normal()),
                    iv_normal_bps=float(iv_normal_bps),
                )
            )

        points = sorted(points, key=lambda pt: pt.strike_price)
        return STIRFutureOptionSABRSmile(
            source=str(self.source),
            symbol=raw_symbol,
            underlying_contract=underlying_contract,
            quote_timestamp=latest_quote,
            params=params,
            points=tuple(points),
        )

    def _seed_option_snapshot_alias_cache(
        self,
        *,
        request: Dict[str, Any],
        result: Dict[str, List[QLSTIRFutureOptionPricer]],
        source_request: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not isinstance(result, dict) or not result:
            return

        source_request = dict(source_request or {})
        base_request: Dict[str, Any] = {
            "endpoint": "option_snapshot",
            "timestamp": request.get("timestamp", "live"),
            "use_ql_calculator": bool(request.get("use_ql_calculator", False)),
        }
        passthrough_fields = [
            "price_mode",
            "window_minutes",
            "window_start",
            "window_end",
            "bulk_timeseries",
            "atm_strike_step",
            "delta_candidate_half_width",
            "delta_vendor_candidate_half_width",
        ]
        for field in passthrough_fields:
            if field in source_request:
                base_request[field] = source_request[field]
        if "curve_name" in source_request:
            base_request["curve_name"] = request["curve_name"]
        if "curve_kwargs" in source_request:
            base_request["curve_kwargs"] = request["curve_kwargs"]

        for raw_symbol, plist in result.items():
            if not isinstance(plist, list) or not plist:
                continue
            single_request = dict(base_request)
            single_request["symbols"] = [str(raw_symbol)]
            cache_key = self._build_get_data_cache_key("option_snapshot", single_request)
            if not cache_key:
                continue
            payload = self._serialize_get_data_result("option_snapshot", {str(raw_symbol): list(plist)})
            self._threadsafe_cache_put(cache_key, payload)

    def _build_sabr_smile_result(self, request: Dict[str, Any]) -> STIRFutureOptionSABRSmile:
        raw_symbol, symbol_info, as_of, deltas, curve_name, curve_kwargs, force_refresh, show_tqdm = self._validate_sabr_smile_request(request)
        labels_by_key: Dict[Tuple[str, int], str]
        if str(self.source).upper() == "STIRFO_DUAL-QL":
            qs_request = self._build_sabr_smile_qs_request(
                globex_symbol=str(symbol_info["globex_symbol"]),
                as_of=as_of,
                deltas=deltas,
                curve_name=curve_name,
                curve_kwargs=curve_kwargs,
                force_refresh=force_refresh,
                show_tqdm=show_tqdm,
            )
            pricers_by_series = self._qs_timeseries(qs_request)
            selected = self._select_sabr_smile_pricers(pricers_by_series=pricers_by_series, as_of=as_of, deltas=deltas)
            labels_by_key = {key: str((pr.meta() or {}).get("qs_series_label", pr.symbol())) for key, pr in selected.items()}
        else:
            snapshot_request = self._build_sabr_smile_snapshot_request(
                request_symbol=str(symbol_info["request_symbol"]),
                as_of=as_of,
                deltas=deltas,
                curve_name=curve_name,
                curve_kwargs=curve_kwargs,
                force_refresh=force_refresh,
                show_tqdm=show_tqdm,
            )
            snapshot = self.get_data(snapshot_request)
            self._seed_option_snapshot_alias_cache(request=snapshot_request, result=snapshot, source_request=request)
            selected, labels_by_key = self._select_sabr_smile_snapshot_pricers(
                pricers_by_symbol=snapshot,
                as_of=as_of,
                deltas=deltas,
            )

        return self._assemble_sabr_smile_result(
            raw_symbol=raw_symbol,
            as_of=as_of,
            selected=selected,
            labels_by_key=labels_by_key,
        )

    def _serialize_sabr_smile(self, smile: STIRFutureOptionSABRSmile) -> Dict[str, Any]:
        return smile.to_dict()

    def _deserialize_sabr_smile(self, row: Dict[str, Any]) -> STIRFutureOptionSABRSmile:
        return STIRFutureOptionSABRSmile.from_dict(row)

    def _build_get_data_cache_key(self, endpoint: str, request: Dict[str, Any]) -> Optional[str]:
        ep = str(endpoint or "").strip().lower()
        if ep not in {"option_snapshot", "option_timeseries", "sabr_smile"}:
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

        if ep == "sabr_smile":
            if "as_of" in cache_req:
                cache_req["as_of"] = _as_date(cache_req["as_of"])
            src = str(self.source).upper()
            if src == "STIRFO_DUAL-QL":
                if "globex_symbol" in cache_req:
                    cache_req["globex_symbol"] = str(
                        _parse_qs_stir_globex_symbol(str(cache_req["globex_symbol"]).strip().upper(), as_of=cache_req.get("as_of"))["globex_symbol"]
                    )
            elif src == "BARCHART_STIRFO-QL":
                raw_contract = cache_req.get("symbol", cache_req.get("contract", cache_req.get("globex_symbol")))
                if raw_contract is not None:
                    token = str(raw_contract).strip().upper().replace("/", "")
                    if "|" in token:
                        token = token.split("|", 1)[0]
                    contract_spec = _parse_contract_token(token)
                    if str(contract_spec.get("contract_selector")) == "explicit":
                        cache_req["symbol"] = str(contract_spec["contract"])
                    else:
                        cache_req["symbol"] = f"{str(contract_spec['cm_root']).upper()}CM{int(contract_spec['cm_rank'])}"
                cache_req.pop("contract", None)
                cache_req.pop("globex_symbol", None)
            cache_req["deltas"] = self._normalize_sabr_smile_deltas(cache_req.get("deltas"))

        if symbols_raw:
            cache_req["symbol_specs"] = self._normalize_symbols_for_cache(symbols=symbols_raw, as_of=as_of_for_symbols)
        cache_req.pop("symbols", None)
        cache_req.pop("tickers", None)

        payload = {
            "schema": 1,
            "cache_version": "stirfo_get_data_v5",
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

    def _serialize_get_data_result(self, endpoint: str, result: Dict[str, List[Any]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for k, plist in result.items():
            if endpoint == "sabr_smile":
                payload[str(k)] = [self._serialize_sabr_smile(p) for p in plist]
            else:
                payload[str(k)] = [self._serialize_pricer(p) for p in plist]
        return {"schema": 1, "endpoint": endpoint, "result": payload}

    def _deserialize_get_data_result(self, cached: Dict[str, Any]) -> Optional[Dict[str, List[Any]]]:
        if not isinstance(cached, dict):
            return None
        if int(cached.get("schema", 0)) != 1:
            return None
        endpoint = str(cached.get("endpoint", "")).strip().lower()
        result_raw = cached.get("result")
        if not isinstance(result_raw, dict):
            return None
        out: Dict[str, List[Any]] = {}
        try:
            for k, plist in result_raw.items():
                if not isinstance(plist, list):
                    continue
                if endpoint == "sabr_smile":
                    out[str(k)] = [self._deserialize_sabr_smile(p) for p in plist if isinstance(p, dict)]
                else:
                    out[str(k)] = [self._deserialize_pricer(p) for p in plist if isinstance(p, dict)]
        except Exception:
            return None
        return out

    def _assert_endpoint_allowed(self, endpoint: str) -> None:
        src = self.source.upper()
        ep = endpoint.strip().lower()
        if src == "STIRFO_DUAL-QL":
            return
        if src == "BARCHART_STIRFO-QL" and ep in {"option_snapshot", "option_timeseries", "sabr_smile"}:
            return
        if src == "QUIKSTRIKE_STIRFO-QL" and ep in {"qs_atm_term_structure", "qs_timeseries"}:
            return
        raise NotImplementedError(f"Endpoint '{endpoint}' is not available for source '{self.source}'")

    def _bounded_session_token_pool_size(self, concurrency: Optional[int]) -> int:
        if concurrency is None:
            target = 1
        else:
            target = max(1, int(concurrency))
        return min(target, int(self._barchart_session_token_pool_size_cap))

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
        S = STIRFutureOptionMDP._BARCHART_STATE
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
    ) -> Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]]:
        curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]] = {}
        out: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]] = defaultdict(dict)

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
    ) -> Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]]:
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
        by_day: Dict[datetime.date, QLSTIRFutureOptionPricer],
        target_date: datetime.date,
    ) -> Optional[QLSTIRFutureOptionPricer]:
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
        contract: Optional[str],
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
            target = _format_strike4(strike, contract=contract)
            pat = re.compile(rf"\|{re.escape(target)}(C|P)$", re.IGNORECASE)
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
        pricers_window: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]],
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

            atm_strike = _atm_strike_from_forward(float(forward), step=atm_strike_step)
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

        if selector != "cm":
            raise ValueError(f"Unsupported contract selector for historical window fetch: {selector}")

        # Resolve CM aliases across the full requested window so one fetch can price all dates.
        days = pd.bdate_range(window_start, window_end).date.tolist()
        if not days:
            days = [window_start]
        resolved = [_resolve_contract_from_spec(spec, as_of=d) for d in days]
        return self._dedupe_preserve_order(resolved)

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
            atm_strike = _atm_strike_from_forward(float(forward), step=atm_strike_step)
            out.append(f"{contract}|{_format_strike4(atm_strike, contract=contract)}{right}")

        return self._dedupe_preserve_order(out)

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
        bulk_timeseries = bool(request.get("bulk_timeseries", False))
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})

        parsed_requested_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for raw in symbols:
            parsed_requested_specs[raw] = _parse_option_request_symbol(raw)
        requested_specs = _resolve_option_contract_aliases_for_date(parsed_requested_specs, as_of=_as_date(ts))

        requested: "OrderedDict[str, str]"
        cp_pricers: Dict[str, QLSTIRFutureOptionPricer] = {}

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
            delta_vendor_candidate_half_width = max(0, int(request.get("delta_vendor_candidate_half_width", 1)))

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
                chains: Optional[Dict[str, Dict[str, pd.DataFrame]]] = None

                def _ensure_delta_chains() -> Dict[str, Dict[str, pd.DataFrame]]:
                    nonlocal chains
                    if chains is not None:
                        return chains

                    option_contracts = sorted(
                        {
                            _contract_to_barchart_contract(contract)
                            for raw in delta_specs.keys()
                            for contract in contracts_by_raw.get(raw, [])
                        }
                    )
                    if not option_contracts:
                        chains = {}
                        return chains

                    chain_concurrency = min(max(len(option_contracts), 1), 16)
                    bcf = self._get_barchart_fetcher(required_concurrency=chain_concurrency)
                    fetched = bcf.get_option_quotes(
                        symbols=option_contracts,
                        max_concurrent_tasks=chain_concurrency,
                        max_keepalive_connections=min(max(len(option_contracts), 1), 16),
                        show_tqdm=show_tqdm,
                    )
                    chains = fetched if isinstance(fetched, dict) else {}
                    return chains

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
                        underlying_contract = _option_contract_to_underlying_contract(contract)
                        underlying_bcontract = _contract_to_barchart_contract(underlying_contract)
                        fut_df = underlying_data.get(underlying_bcontract)
                        if fut_df is None or fut_df.empty:
                            if bulk_timeseries:
                                continue
                            raise ValueError(
                                f"Could not resolve delta alias {raw!r}: missing underlying history for {contract}."
                            )

                        generated_from_rules = False
                        if not bulk_timeseries:
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

                            strike_subset = _cme_listed_strikes_for_contract_forward(
                                contract=contract,
                                forward=float(forward),
                                as_of=target_date,
                            )
                            if strike_subset:
                                option_bcontract = _contract_to_barchart_contract(contract)
                                chain = _ensure_delta_chains().get(option_bcontract)
                                if chain is not None:
                                    vendor_center_strike = self._resolve_live_delta_strike(
                                        chain=chain,
                                        target_delta=float(target_delta),
                                        right=right,
                                    )
                                    if vendor_center_strike is not None:
                                        vendor_slice = self._pick_centered_strike_slice(
                                            strike_subset,
                                            center=float(vendor_center_strike),
                                            half_width=delta_vendor_candidate_half_width,
                                        )
                                        forward_slice = self._pick_centered_strike_slice(
                                            strike_subset,
                                            center=float(forward),
                                            half_width=min(delta_candidate_half_width, 2),
                                        )
                                        narrowed: List[float] = []
                                        seen_strikes = set()
                                        for strike_val in list(vendor_slice) + list(forward_slice):
                                            key = round(float(strike_val), 8)
                                            if key in seen_strikes:
                                                continue
                                            seen_strikes.add(key)
                                            narrowed.append(float(strike_val))
                                        if narrowed:
                                            strike_subset = narrowed
                                candidate_symbols.extend(
                                    [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_subset]
                                )
                                generated_from_rules = True

                        if bulk_timeseries and not generated_from_rules:
                            for row_dt, row in fut_df.iterrows():
                                row_day = pd.Timestamp(row_dt).date()
                                if row_day < req_window_start or row_day > req_window_end:
                                    continue
                                forward = _extract_row_price(row.to_dict(), price_mode=price_mode)
                                if forward is None or forward <= 0.0:
                                    continue
                                strike_subset = _cme_listed_strikes_for_contract_forward(
                                    contract=contract,
                                    forward=float(forward),
                                    as_of=row_day,
                                )
                                if strike_subset:
                                    candidate_symbols.extend(
                                        [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_subset]
                                    )
                                    generated_from_rules = True

                        if generated_from_rules:
                            continue

                        option_bcontract = _contract_to_barchart_contract(contract)
                        chain = _ensure_delta_chains().get(option_bcontract)
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

                        if not bulk_timeseries:
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

                            strike_subset = []
                            vendor_center_strike = self._resolve_live_delta_strike(
                                chain=chain,
                                target_delta=float(target_delta),
                                right=right,
                            )
                            if vendor_center_strike is not None:
                                vendor_slice = self._pick_centered_strike_slice(
                                    listed_strikes,
                                    center=float(vendor_center_strike),
                                    half_width=delta_vendor_candidate_half_width,
                                )
                                forward_slice = self._pick_centered_strike_slice(
                                    listed_strikes,
                                    center=float(forward),
                                    half_width=min(delta_candidate_half_width, 2),
                                )
                                seen_strikes = set()
                                for strike_val in list(vendor_slice) + list(forward_slice):
                                    key = round(float(strike_val), 8)
                                    if key in seen_strikes:
                                        continue
                                    seen_strikes.add(key)
                                    strike_subset.append(float(strike_val))
                            else:
                                strike_subset = self._pick_centered_strike_slice(
                                    listed_strikes,
                                    center=float(forward),
                                    half_width=delta_candidate_half_width,
                                )

                            candidate_symbols.extend(
                                [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_subset]
                            )
                            continue

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
        )

        result: Dict[str, List[QLSTIRFutureOptionPricer]] = {}
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

    @staticmethod
    def _coerce_stirfo_value(value: Any) -> Optional[STIRFutureOptionValue]:
        if value is None:
            return None
        if isinstance(value, STIRFutureOptionValue):
            return value
        token = str(value).strip()
        if not token:
            return None
        try:
            return STIRFutureOptionValue[token.upper()]
        except KeyError as exc:
            valid = ", ".join(v.name for v in STIRFutureOptionValue)
            raise ValueError(f"Unknown STIRFutureOptionValue {value!r}; expected one of: {valid}, or 'options'.") from exc

    @staticmethod
    def _qs_right_from_label_and_query(*, label: str, query: Dict[str, Any]) -> str:
        lbl = str(label or "").strip().upper()
        vt = str(query.get("qv_value_type", "")).strip().upper()
        opt_type = str(query.get("option_type", "")).strip().upper()

        if " PUT" in f" {lbl}" or vt.startswith("PUT") or opt_type == "PUT":
            return "P"
        if " CALL" in f" {lbl}" or vt.startswith("CALL") or opt_type == "CALL":
            return "C"
        if "STRADDLE" in lbl or opt_type == "STRADDLE":
            return "S"
        return "S"

    @staticmethod
    def _qs_delta_abs_from_label_and_query(*, label: str, query: Dict[str, Any]) -> Optional[float]:
        lbl = str(label or "").strip().upper()
        m = re.search(r"(?P<delta>\d+(?:\.\d+)?)\s*D\b", lbl)
        if m:
            return _to_float(m.group("delta"))
        return _to_float(query.get("delta"))

    @staticmethod
    def _qs_delta_from_label_and_query(*, label: str, query: Dict[str, Any], right: str) -> float:
        delta_abs = STIRFutureOptionMDP._qs_delta_abs_from_label_and_query(label=label, query=query)
        if delta_abs is None or not math.isfinite(float(delta_abs)):
            return 0.0
        d = abs(float(delta_abs)) / 100.0
        if right == "P":
            return -d
        if right == "C":
            return d
        return 0.0

    def _qs_timeseries_to_pricers(
        self,
        *,
        df: pd.DataFrame,
        query_meta: List[Dict[str, Any]],
        underlying_data: Dict[str, pd.DataFrame],
        curve_name: str,
        curve_kwargs: Optional[Dict[str, Any]],
        use_ql_calculator: bool,
    ) -> Dict[str, List[QLSTIRFutureOptionPricer]]:
        if not isinstance(df, pd.DataFrame):
            return {}

        curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]] = {}
        out: "OrderedDict[str, List[QLSTIRFutureOptionPricer]]" = OrderedDict()
        for idx, col in enumerate(df.columns):
            col_name = str(col)
            qmeta = query_meta[idx] if idx < len(query_meta) else {}
            vt_name = str(qmeta.get("qv_value_type", "")).strip().upper()
            right = self._qs_right_from_label_and_query(label=col_name, query=qmeta)
            if right not in {"C", "P", "S"}:
                right = "S"

            globex_symbol = str(qmeta.get("globex_symbol", "")).strip().upper()
            if not globex_symbol:
                head = str(col_name).strip().upper().split(" ", 1)[0]
                try:
                    globex_symbol = _normalize_qs_stir_globex_symbol(head)
                except Exception:
                    globex_symbol = head

            symbol_kind = str(qmeta.get("kind", "listed")).strip().lower()
            root_globex = str(qmeta.get("root_globex", "")).strip().upper()
            cm_days_raw = qmeta.get("cm_days")
            cm_days = int(cm_days_raw) if cm_days_raw is not None else None
            contract_code = str(qmeta.get("contract_code", "")).strip().upper()

            listed_underlying_contract = str(qmeta.get("barchart_contract", "")).strip().upper()
            if symbol_kind == "listed" and not listed_underlying_contract:
                try:
                    parsed = _parse_qs_stir_globex_symbol(globex_symbol)
                    listed_underlying_contract = str(parsed.get("barchart_contract", "")).strip().upper()
                    if not contract_code:
                        contract_code = str(parsed.get("contract_code", "")).strip().upper()
                except Exception:
                    listed_underlying_contract = ""

            explicit_strike = _to_float(qmeta.get("strike"))
            delta_abs = self._qs_delta_abs_from_label_and_query(label=col_name, query=qmeta)

            series = df[col].dropna()
            if not series.empty:
                series = series.sort_index()

            pricers: List[QLSTIRFutureOptionPricer] = []
            for ts_raw, val_raw in series.items():
                y = _to_float(val_raw)
                if y is None:
                    continue

                ts = pd.Timestamp(ts_raw)
                if ts.tzinfo is None:
                    quote_dt = _NY_TZ.localize(ts.to_pydatetime())
                else:
                    quote_dt = ts.tz_convert(_NY_TZ).to_pydatetime()
                quote_day = quote_dt.astimezone(_NY_TZ).date()

                if symbol_kind == "cm":
                    if not root_globex:
                        m_root = re.fullmatch(r"^(?P<root>[A-Z0-9]+)_(?P<days>\d{1,3})$", globex_symbol)
                        root_globex = m_root.group("root") if m_root else ""
                    if not root_globex:
                        continue
                    try:
                        underlying_contract = _qs_front_barchart_contract_for_date(root_globex=root_globex, as_of=quote_day)
                    except Exception:
                        continue
                else:
                    underlying_contract = listed_underlying_contract
                if not underlying_contract:
                    continue

                fut_df = underlying_data.get(underlying_contract)
                forward = float("nan")
                if fut_df is not None and not fut_df.empty:
                    pos = _asof_index_position(fut_df.index, pd.Timestamp(quote_dt))
                    if pos is not None:
                        forward_row = fut_df.iloc[pos].to_dict()
                        forward_val = _extract_row_price(forward_row, price_mode="mid_then_fallback")
                        if forward_val is not None and forward_val > 0.0:
                            forward = float(forward_val)
                if not math.isfinite(forward) or forward <= 0.0:
                    continue

                if symbol_kind == "cm" and cm_days is not None and cm_days > 0:
                    expiry = quote_day + datetime.timedelta(days=int(cm_days))
                else:
                    code2 = contract_code
                    if not code2:
                        m_code = re.fullmatch(r"^[A-Z0-9]+(?P<code>[FGHJKMNQUVXZ]\d{2})$", globex_symbol)
                        code2 = m_code.group("code") if m_code else ""
                    if not code2:
                        continue
                    expiry = _contract_expiry_date(code2)
                tte = _time_to_expiry(quote_day, expiry)
                discount, curve_error = self._discount_factor(
                    valuation_ts=quote_dt,
                    expiry_date=expiry,
                    curve_name=curve_name,
                    curve_kwargs=curve_kwargs,
                    memo=curve_memo,
                )

                strike = float(explicit_strike) if explicit_strike is not None and explicit_strike > 0.0 else float("nan")
                iv_from_qs = float(y) if vt_name not in _QS_PRICE_VALUE_TYPES else float("nan")
                iv_normal = _qs_stir_normal_vol_from_value(iv_from_qs) if vt_name not in _QS_PRICE_VALUE_TYPES else float("nan")
                iv_scale = 0.01 if (vt_name not in _QS_PRICE_VALUE_TYPES and math.isfinite(iv_from_qs) and abs(iv_from_qs) > 5.0) else 1.0
                if not math.isfinite(strike) or strike <= 0.0:
                    if right in {"C", "P"} and delta_abs is not None and float(delta_abs) > 0.0 and math.isfinite(iv_normal) and iv_normal > 0.0:
                        strike = _estimate_bachelier_strike_for_target_delta(
                            right=right,
                            target_delta_abs=float(delta_abs),
                            forward=float(forward),
                            vol_normal=float(iv_normal),
                            tte=float(tte),
                            discount=float(discount),
                        )
                    else:
                        strike = float(forward)

                signed_delta = 0.0
                if delta_abs is not None and right in {"C", "P"}:
                    signed_delta = abs(float(delta_abs)) / 100.0
                    if right == "P":
                        signed_delta = -signed_delta

                market_price = float("nan")
                model_price = float("nan")
                gamma = vega = theta = float("nan")
                if right in {"C", "P"} and math.isfinite(strike) and strike > 0.0 and tte > 0.0:
                    if vt_name in _QS_PRICE_VALUE_TYPES:
                        market_price = float(y)
                        iv_normal = _implied_normal_vol(
                            right=right,
                            strike=float(strike),
                            forward=float(forward),
                            tte=float(tte),
                            price=float(market_price),
                            discount=float(discount),
                        )
                    elif math.isfinite(iv_normal) and iv_normal > 0.0:
                        market_price = _bachelier_price(
                            right=right,
                            strike=float(strike),
                            forward=float(forward),
                            vol_normal=float(iv_normal),
                            tte=float(tte),
                            discount=float(discount),
                        )

                    if math.isfinite(iv_normal) and iv_normal > 0.0:
                        model_price = _bachelier_price(
                            right=right,
                            strike=float(strike),
                            forward=float(forward),
                            vol_normal=float(iv_normal),
                            tte=float(tte),
                            discount=float(discount),
                        )
                        d_calc, gamma, vega, theta = _bachelier_greeks_fd(
                            right=right,
                            strike=float(strike),
                            forward=float(forward),
                            vol_normal=float(iv_normal),
                            tte=float(tte),
                            discount=float(discount),
                            use_ql_calculator=use_ql_calculator,
                        )
                        if math.isfinite(d_calc):
                            signed_delta = float(d_calc)

                if not math.isfinite(market_price):
                    market_price = float(y)
                if not math.isfinite(model_price):
                    model_price = market_price

                if math.isfinite(strike) and strike > 0.0:
                    selector = _format_strike4(strike, contract=underlying_contract)
                elif delta_abs is not None and float(delta_abs) > 0.0:
                    selector = f"{float(delta_abs):g}D"
                else:
                    selector = "ATM"
                symbol = f"{underlying_contract}|{selector}{right}"

                meta_data = {
                    "schema": 1,
                    "source": "QUIKSTRIKE_TIMESERIES",
                    "qs_series_label": col_name,
                    "qs_query": dict(qmeta),
                    "curve_name": curve_name,
                    "curve_error": curve_error,
                    "discount": float(discount),
                    "underlying_contract": underlying_contract,
                    "vol_input_type": "normal_vol" if vt_name not in _QS_PRICE_VALUE_TYPES else "premium",
                    "iv_normal_input_raw": float(iv_from_qs) if math.isfinite(iv_from_qs) else float("nan"),
                    "iv_normal_input_scale": float(iv_scale),
                    "iv_normal": float(iv_normal) if math.isfinite(iv_normal) else float("nan"),
                }

                pricers.append(
                    QLSTIRFutureOptionPricer(
                        symbol=symbol,
                        right=right,
                        underlying_symbol=underlying_contract,
                        strike=float(strike),
                        quote_timestamp=quote_dt,
                        expiry_date=expiry,
                        market_price=float(market_price),
                        model_price=float(model_price) if math.isfinite(model_price) else float("nan"),
                        iv_normal=float(iv_normal) if math.isfinite(iv_normal) else float("nan"),
                        delta=float(signed_delta),
                        gamma=float(gamma) if math.isfinite(gamma) else float("nan"),
                        vega=float(vega) if math.isfinite(vega) else float("nan"),
                        theta=float(theta) if math.isfinite(theta) else float("nan"),
                        forward=float(forward),
                        discount=float(discount),
                        meta_data=meta_data,
                    )
                )

            out[col_name] = pricers

        return dict(out)

    @staticmethod
    def _qs_value_from_pricer(*, pricer: QLSTIRFutureOptionPricer, value: STIRFutureOptionValue) -> float:
        if value == STIRFutureOptionValue.PRICE:
            return float(pricer.price())
        if value == STIRFutureOptionValue.NPV:
            return float(pricer.npv(pricer.build_pricable(quantity=1.0)))
        if value == STIRFutureOptionValue.DELTA:
            return float(pricer.delta())
        if value == STIRFutureOptionValue.GAMMA:
            return float(pricer.gamma())
        if value == STIRFutureOptionValue.VEGA:
            return float(pricer.vega())
        if value == STIRFutureOptionValue.THETA:
            return float(pricer.theta())
        if value == STIRFutureOptionValue.IV_NORMAL_BPS:
            return float(pricer.iv_normal_bps())
        raise KeyError(f"Unsupported STIRFutureOptionValue: {value}")

    def _qs_pricers_to_value_df(
        self,
        *,
        pricers_by_series: Dict[str, List[QLSTIRFutureOptionPricer]],
        value: STIRFutureOptionValue,
    ) -> pd.DataFrame:
        if not pricers_by_series:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        ordered_cols = list(pricers_by_series.keys())
        for series_name, plist in pricers_by_series.items():
            for pr in plist:
                rows.append(
                    {
                        "Date": pd.Timestamp(pr.quote_timestamp()),
                        "series": str(series_name),
                        "value": self._qs_value_from_pricer(pricer=pr, value=value),
                    }
                )

        if not rows:
            empty = pd.DataFrame(columns=ordered_cols)
            empty.index.name = "Date"
            return empty

        work = pd.DataFrame(rows)
        out = work.pivot_table(index="Date", columns="series", values="value", aggfunc="first").sort_index()
        out = out.reindex(columns=ordered_cols)
        out.index = pd.to_datetime(out.index)
        out.index.name = "Date"
        return out

    def _qs_timeseries(self, request: Dict[str, Any]) -> Dict[str, List[Any]]:
        if "start" not in request or "end" not in request:
            raise ValueError("qs_timeseries requires start and end")
        if "queries" not in request:
            raise ValueError("qs_timeseries requires queries")

        force_refresh = bool(request.get("force_refresh", False))
        show_tqdm = bool(request.get("show_tqdm", False))
        use_ql_calculator = bool(request.get("use_ql_calculator", False))
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})

        value_arg = request.get("value")
        return_options = bool(request.get("options", False))
        if isinstance(value_arg, str) and value_arg.strip().upper() == "OPTIONS":
            return_options = True
            value_arg = None
        value_enum = self._coerce_stirfo_value(value_arg)

        start_dt = _as_datetime(request["start"]).replace(tzinfo=None)
        end_dt = _as_datetime(request["end"]).replace(tzinfo=None)
        start_date = _as_date(request["start"])
        end_date = _as_date(request["end"])

        qlist: List[QuikVolQuery] = []
        query_meta: List[Dict[str, Any]] = []
        underlying_symbols_set: set[str] = set()
        business_days = pd.bdate_range(start_date, end_date).date.tolist()
        if not business_days:
            business_days = [start_date]

        for q in request.get("queries", []):
            if not isinstance(q, dict):
                raise ValueError("qs_timeseries queries must be dictionaries")

            raw_symbol = str(q.get("globex_symbol", "")).strip().upper()
            symbol_info = _parse_qs_stir_globex_symbol(raw_symbol, as_of=start_date)
            globex_symbol = str(symbol_info["globex_symbol"])

            vt_name = str(q.get("qv_value_type", "")).strip()
            if not vt_name:
                raise ValueError("qv_value_type is required for each qs_timeseries query")
            try:
                vt = QuikVolValueType[vt_name]
            except KeyError as exc:
                raise ValueError(f"Unknown QuikVolValueType: {vt_name}") from exc
            delta = int(q.get("delta", 0) or 0)
            strike = float(q.get("strike", 0.0) or 0.0)
            option_type = str(q.get("option_type", "Straddle"))
            barchart_contract = symbol_info.get("barchart_contract")
            if symbol_info.get("kind") == "listed":
                if barchart_contract:
                    underlying_symbols_set.add(str(barchart_contract))
            else:
                root_globex = str(symbol_info.get("root_globex", "")).strip().upper()
                for day in business_days:
                    underlying_symbols_set.add(_qs_front_barchart_contract_for_date(root_globex=root_globex, as_of=day))

            qlist.append(
                QuikVolQuery(
                    globex_symbol=globex_symbol,
                    qv_value_type=vt,
                    delta=delta,
                    strike=strike,
                    option_type=option_type,
                )
            )
            query_meta.append(
                {
                    "globex_symbol": globex_symbol,
                    "barchart_contract": barchart_contract,
                    "kind": symbol_info.get("kind"),
                    "root_globex": symbol_info.get("root_globex"),
                    "cm_days": symbol_info.get("cm_days"),
                    "contract_code": symbol_info.get("contract_code"),
                    "qv_value_type": vt.name,
                    "delta": delta,
                    "strike": strike,
                    "option_type": option_type,
                }
            )

        underlying_symbols = sorted({str(s).strip().upper() for s in underlying_symbols_set if str(s).strip()})
        if underlying_symbols:
            underlying_data = self._fetch_barchart_eod_series(
                symbols=underlying_symbols,
                start=start_date,
                end=end_date,
                show_tqdm=show_tqdm,
            )
        else:
            underlying_data = {}

        for attempt in (0, 1):
            try:
                qsf = self._quikstrike_client(force_refresh=force_refresh or attempt == 1)
                df = qsf.fetch_quikvol_timeseries(
                    start_date=start_dt,
                    end_date=end_dt,
                    queries=qlist,
                )
                pricers_by_series = self._qs_timeseries_to_pricers(
                    df=df,
                    query_meta=query_meta,
                    underlying_data=underlying_data,
                    curve_name=curve_name,
                    curve_kwargs=curve_kwargs,
                    use_ql_calculator=use_ql_calculator,
                )
                if return_options:
                    return pricers_by_series
                if value_enum is not None:
                    return {"qs_timeseries": [self._qs_pricers_to_value_df(pricers_by_series=pricers_by_series, value=value_enum)]}
                return {"qs_timeseries": [df]}
            except Exception:
                if attempt == 1:
                    raise
        raise RuntimeError("QuikStrike timeseries fetch failed")

    def fetch_sabr_smile(self, request: Dict[str, Any]) -> STIRFutureOptionSABRSmile:
        req = dict(request)
        req["endpoint"] = "sabr_smile"
        out = self.get_data(req)
        smiles = out.get("sabr_smile") or []
        if not smiles:
            raise ValueError("sabr_smile returned no calibrated smile.")
        return smiles[0]

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
            elif endpoint == "sabr_smile":
                out = {"sabr_smile": [self._build_sabr_smile_result(request)]}
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
