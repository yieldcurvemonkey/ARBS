import datetime
import calendar
import hashlib
import importlib.util
import itertools
import json
import logging
import math
import os
import queue
import random
import re
import threading
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import numpy as np
import pandas as pd
import pytz
import QuantLib as ql
import rateslib as rl
import requests

from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from MDP.sabr_calibration import (
    _collapse_duplicate_strikes,
    _normal_delta_to_strike,
    _sabr_normal_vol,
    calibrate_sabr_normal,
)
from MDP.STIRFutures import _sofr_option_contracts as _shared_sofr_option_contracts
from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher
from MDP.STIRFutures.SCHWAB.schwab_simple import get_quotes as schwab_get_quotes
from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutureOptions._risk import dollar_dv01, dollar_gamma_01, dollar_vega_01

from MDP.STIRFutures.QuikStrikeSDK.core.QuikStrikeFetcher import QuikStrikeFetcher  
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID  
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolQuery import QuikVolQuery  
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolValueType import QuikVolValueType  
from MDP.STIRFutures.QuikStrikeSDK.core.utils.auth import walk_quikstrike_auth_flow  
from Query.Base.bachelier import (
    bachelier_greeks_fd as _shared_bachelier_greeks_fd,
    bachelier_price as _shared_bachelier_price,
    implied_normal_vol as _shared_implied_normal_vol,
    ql_option_type as _shared_ql_option_type,
)


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
_MIDCURVE_1Y2Y_ROOTS = {
    "0Q",
    "2Q",
    "UHOA",
    "UMOA",
    "UUOA",
    "UZOA",
    "VHTA",
    "VMTA",
    "VUTA",
    "VZTA",
}
_MIDCURVE_WEEKLY_ROOTS = {
    "S01",
    "S02",
    "S03",
    "S04",
    "S05",
    "S21",
    "S22",
    "S23",
    "S24",
    "S25",
    "S31",
    "S32",
    "S33",
    "S34",
    "S35",
}
_MIDCURVE_BACK_STYLE_ROOTS = {"3Q", "4Q", "5Q"}
_MONTH_CODE_TO_NUM = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
_NUM_TO_MONTH_CODE = {v: k for k, v in _MONTH_CODE_TO_NUM.items()}
_QUARTERLY_MONTHS = (3, 6, 9, 12)
_SCHWAB_ROOT_MAP = {
    "SFR": "SR3",
    "SER": "SR1",
    "FF": "ZQ",
}

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
_SABR_SMILE_LISTED_OFFSET_CAP_BPS = 250.0
# A smile must be a snapshot of one trading session.  EOD windows are prefetched +/- a
# calendar month around the request, so without this bound a leg whose chain stopped
# printing weeks ago is silently carried forward into an as-of it never traded on.
_SABR_SMILE_MAX_QUOTE_STALENESS_DAYS = 5
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
    calibration_rmse: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
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
        if self.calibration_rmse is not None:
            payload["calibration_rmse"] = float(self.calibration_rmse)
        return payload

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
            calibration_rmse=float(row["calibration_rmse"]) if row.get("calibration_rmse") is not None else None,
        )


@dataclass(frozen=True)
class STIRFutureOptionSmilePoint:
    label: str
    right: str
    delta_abs: float
    atm_offset_bps: float
    strike_price: float
    strike_rate: float
    iv_normal_price: float
    iv_normal_bps: float
    market_price: Optional[float] = None
    discount_factor: Optional[float] = None
    open_interest: Optional[float] = None
    volume: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "label": str(self.label),
            "right": str(self.right),
            "delta_abs": float(self.delta_abs),
            "atm_offset_bps": float(self.atm_offset_bps),
            "strike_price": float(self.strike_price),
            "strike_rate": float(self.strike_rate),
            "iv_normal_price": float(self.iv_normal_price),
            "iv_normal_bps": float(self.iv_normal_bps),
        }
        if self.market_price is not None:
            payload["market_price"] = float(self.market_price)
        if self.discount_factor is not None:
            payload["discount_factor"] = float(self.discount_factor)
        if self.open_interest is not None:
            payload["open_interest"] = float(self.open_interest)
        if self.volume is not None:
            payload["volume"] = float(self.volume)
        return payload

    @classmethod
    def from_dict(cls, row: Dict[str, Any]) -> "STIRFutureOptionSmilePoint":
        return cls(
            label=str(row["label"]),
            right=str(row["right"]),
            delta_abs=float(row["delta_abs"]),
            atm_offset_bps=float(row.get("atm_offset_bps", float("nan"))),
            strike_price=float(row["strike_price"]),
            strike_rate=float(row["strike_rate"]),
            iv_normal_price=float(row["iv_normal_price"]),
            iv_normal_bps=float(row["iv_normal_bps"]),
            market_price=float(row["market_price"]) if row.get("market_price") is not None else None,
            discount_factor=float(row["discount_factor"]) if row.get("discount_factor") is not None else None,
            open_interest=float(row["open_interest"]) if row.get("open_interest") is not None else None,
            volume=float(row["volume"]) if row.get("volume") is not None else None,
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


def _calibrate_sabr_normal_from_delta_points(
    *,
    forward: float,
    time_to_expiry: float,
    market_points: Sequence[Tuple[float, float, str]],
    beta: float = 0.5,
    calibration_method: str = "nelder-mead",
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

    alpha_cal, rho_cal, nu_cal, rmse = calibrate_sabr_normal(
        forward=float(forward),
        time_to_expiry=float(time_to_expiry),
        strikes_arr=strikes,
        vols_arr=vols,
        beta=float(beta),
        method=calibration_method,
    )

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
        calibration_rmse=rmse,
    )


def _calibrate_sabr_normal_from_strike_points(
    *,
    forward: float,
    time_to_expiry: float,
    market_points: Sequence[Tuple[float, float]],
    beta: float = 0.5,
    calibration_method: str = "nelder-mead",
) -> STIRFutureOptionSABRParams:
    if not math.isfinite(forward) or forward <= 0.0:
        raise ValueError(f"Invalid forward for SABR calibration: {forward}")
    if not math.isfinite(time_to_expiry) or time_to_expiry <= 0.0:
        raise ValueError(f"Invalid time_to_expiry for SABR calibration: {time_to_expiry}")
    if len(market_points) < 6:
        raise ValueError("SABR calibration requires at least 6 valid strike-vol points.")

    strikes: List[float] = []
    vols: List[float] = []
    for strike, vol_normal in market_points:
        strike_val = float(strike)
        vol_val = float(vol_normal)
        if not math.isfinite(strike_val) or strike_val <= 0.0:
            continue
        if not math.isfinite(vol_val) or vol_val <= 0.0:
            continue
        strikes.append(strike_val)
        vols.append(vol_val)

    if len(strikes) < 6:
        raise ValueError("SABR calibration requires at least 6 strike-vol points after filtering.")

    alpha_cal, rho_cal, nu_cal, rmse = calibrate_sabr_normal(
        forward=float(forward),
        time_to_expiry=float(time_to_expiry),
        strikes_arr=strikes,
        vols_arr=vols,
        beta=float(beta),
        method=calibration_method,
    )

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
        calibration_rmse=rmse,
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


def _contract_code(contract: str) -> str:
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        raise ValueError(f"Invalid STIR contract token: {contract}")
    return m.group("code").upper()


def _format_schwab_strike(strike: float) -> str:
    return f"{float(strike):.4f}".rstrip("0").rstrip(".")


def _contract_to_schwab_future_symbol(contract: str) -> str:
    root = _contract_root(contract)
    if root is None:
        raise ValueError(f"Invalid STIR future contract token: {contract}")
    code = _contract_code(contract)
    return f"/{_SCHWAB_ROOT_MAP.get(root, root)}{code}"


def _canonical_to_schwab_option_symbol(symbol: str) -> str:
    token = _norm_option_symbol(symbol)
    contract = _canonical_contract(token)
    right = _right_from_symbol(token)
    if right not in {"C", "P"}:
        raise ValueError(f"Schwab option quotes require an explicit call/put leg, got {symbol!r}")

    root = _contract_root(contract)
    if root is None:
        raise ValueError(f"Invalid STIR option contract token: {contract}")
    code = _contract_code(contract)
    strike = _strike_from_symbol(token)
    return f"./{_SCHWAB_ROOT_MAP.get(root, root)}{code}{right}{_format_schwab_strike(strike)}"


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
    return [round(float(center) + i * float(step), 8) for i in range(-half_width_steps, half_width_steps + 1)]


def _contract_month_distance(contract: str, as_of: datetime.date) -> Optional[int]:
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        return None
    code = str(m.group("code")).upper()
    month = _MONTH_CODE_TO_NUM[code[0]]
    year = 2000 + int(code[1:])
    return (year - as_of.year) * 12 + (month - as_of.month)


def _cme_listed_strike_rule_for_contract(
    *,
    contract: str,
    as_of: datetime.date,
) -> Optional[Dict[str, float]]:
    if not _is_sofr_style_option_contract(contract):
        return None

    root = _contract_root(contract)
    month_distance = _contract_month_distance(contract, as_of=as_of)
    if root is None or month_distance is None:
        return None

    fine_step: float
    if root in _MIDCURVE_WEEKLY_ROOTS:
        fine_step = 0.0625
    elif root in _MIDCURVE_1Y2Y_ROOTS:
        fine_step = 0.0625 if month_distance <= 5 else 0.125
    elif root in _MIDCURVE_BACK_STYLE_ROOTS:
        fine_step = 0.125
    elif root == "SFR":
        fine_step = 0.0625 if month_distance <= 7 else 0.125
    else:
        fine_step = 0.125

    return {
        "fine_step": float(fine_step),
        "coarse_step": 0.25,
        "fine_range": 1.5,
        "coarse_range": 5.5,
    }


def _cme_listed_strike_grid_for_contract_forward(
    *,
    contract: str,
    forward: float,
    as_of: datetime.date,
) -> Optional[Dict[str, Any]]:
    rule = _cme_listed_strike_rule_for_contract(contract=contract, as_of=as_of)
    if rule is None:
        return None

    fine_step = float(rule["fine_step"])
    coarse_step = float(rule["coarse_step"])
    fine_half_width_steps = int(round(float(rule["fine_range"]) / fine_step))
    coarse_half_width_steps = int(round(float(rule["coarse_range"]) / coarse_step))

    fine_atm = _atm_strike_from_forward(float(forward), step=fine_step)
    ladders = list(_strike_ladder(center=float(fine_atm), step=fine_step, half_width_steps=int(fine_half_width_steps)))
    ladders.extend(_strike_ladder(center=float(fine_atm), step=coarse_step, half_width_steps=int(coarse_half_width_steps)))

    out: List[float] = []
    seen = set()
    for strike in sorted(float(x) for x in ladders):
        key = round(float(strike), 8)
        if key in seen:
            continue
        seen.add(key)
        out.append(float(strike))

    return {
        "atm_strike": float(fine_atm),
        "strikes": out,
        "fine_step": fine_step,
        "coarse_step": coarse_step,
    }


def _cme_listed_strikes_for_contract_forward(
    *,
    contract: str,
    forward: float,
    as_of: datetime.date,
) -> Optional[List[float]]:
    grid = _cme_listed_strike_grid_for_contract_forward(
        contract=contract,
        forward=forward,
        as_of=as_of,
    )
    if grid is None:
        return None
    return list(grid["strikes"])


def _cme_listed_abs_offset_grid_bps_for_contract_forward(
    *,
    contract: str,
    forward: float,
    as_of: datetime.date,
) -> Optional[Tuple[float, List[float], List[float]]]:
    grid = _cme_listed_strike_grid_for_contract_forward(
        contract=contract,
        forward=forward,
        as_of=as_of,
    )
    if grid is None:
        return None

    atm_strike = float(grid["atm_strike"])
    strikes = [float(s) for s in grid["strikes"]]
    signed_offsets = sorted({round((atm_strike - strike) * 100.0, 8) for strike in strikes})
    abs_offsets = sorted({round(abs(offset), 8) for offset in signed_offsets})
    return atm_strike, abs_offsets, signed_offsets


def _snap_to_listed_strike_for_offset(
    *,
    contract: str,
    forward: float,
    as_of: datetime.date,
    right: str,
    offset_bps: float,
) -> Tuple[float, float]:
    grid = _cme_listed_strike_grid_for_contract_forward(
        contract=contract,
        forward=forward,
        as_of=as_of,
    )
    if grid is None:
        raise ValueError(f"No listed strike rule available for offset-based SABR smile on {contract}")

    atm_strike = float(grid["atm_strike"])
    listed_strikes = [float(s) for s in grid["strikes"]]
    right_token = str(right or "").strip().upper()
    if right_token not in {"C", "P"}:
        raise ValueError(f"Unsupported option right for offset strike snapping: {right}")

    target_signed_offset = float(offset_bps)
    if right_token == "C" and target_signed_offset > 0.0:
        target_signed_offset = -abs(target_signed_offset)
    if right_token == "P" and target_signed_offset < 0.0:
        target_signed_offset = abs(target_signed_offset)

    side_candidates = (
        [strike for strike in listed_strikes if strike >= atm_strike - 1e-12]
        if right_token == "C"
        else [strike for strike in listed_strikes if strike <= atm_strike + 1e-12]
    )
    if not side_candidates:
        side_candidates = list(listed_strikes)

    target_strike = atm_strike - target_signed_offset / 100.0
    snapped = min(
        side_candidates,
        key=lambda strike: (
            abs(float(strike) - float(target_strike)),
            abs(float(atm_strike) - float(strike)),
        ),
    )
    actual_offset = round((atm_strike - float(snapped)) * 100.0, 8)
    return float(snapped), float(actual_offset)


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
        atm_offset_bps: Optional[float],
    ) -> Dict[str, Any]:
        if contract_spec["contract_selector"] == "explicit":
            contract_ref = str(contract_spec["contract"])
        else:
            contract_ref = f"{contract_spec['cm_root']}CM{int(contract_spec['cm_rank'])}"

        if selector == "strike":
            canonical = f"{contract_ref}|{strike4}{right}"
        elif selector == "atm":
            canonical = f"{contract_ref}|ATM{right}"
        elif selector == "atmf_offset":
            canonical = f"{contract_ref}|{abs(float(atm_offset_bps)):g}BP{right}"
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
            "atm_offset_bps": atm_offset_bps,
        }

    if "|" in token:
        contract_part, leg_part = token.split("|", 1)
        contract_spec = _parse_contract_token(contract_part)

        m = re.fullmatch(r"(?P<strike>\d{3,5})(?P<right>[CPS])", leg_part)
        if m:
            strike4 = str(int(m.group("strike"))).zfill(4)
            right = m.group("right").upper()
            return _build(contract_spec=contract_spec, selector="strike", right=right, strike4=strike4, delta=None, atm_offset_bps=None)

        m = re.fullmatch(r"ATM(?P<right>[CPS])", leg_part)
        if m:
            right = m.group("right").upper()
            return _build(contract_spec=contract_spec, selector="atm", right=right, strike4=None, delta=None, atm_offset_bps=None)

        m = re.fullmatch(r"(?P<offset>\d{1,4}(?:\.\d+)?)BP(?P<right>[CP])", leg_part)
        if m:
            right = m.group("right").upper()
            offset_bps = abs(float(m.group("offset")))
            if offset_bps <= 0.0:
                raise ValueError(f"ATMF offset alias must be > 0: {symbol}")
            signed_offset = -offset_bps if right == "C" else offset_bps
            return _build(
                contract_spec=contract_spec,
                selector="atmf_offset",
                right=right,
                strike4=None,
                delta=None,
                atm_offset_bps=signed_offset,
            )

        m = re.fullmatch(r"ATMF(?P<sign>[+-])(?P<offset>\d{1,4}(?:\.\d+)?)", leg_part)
        if m:
            price_sign = m.group("sign")
            offset_bps = abs(float(m.group("offset")))
            if offset_bps <= 0.0:
                raise ValueError(f"ATMF offset alias must be > 0: {symbol}")
            right = "C" if price_sign == "+" else "P"
            signed_offset = -offset_bps if right == "C" else offset_bps
            return _build(
                contract_spec=contract_spec,
                selector="atmf_offset",
                right=right,
                strike4=None,
                delta=None,
                atm_offset_bps=signed_offset,
            )

        m = re.fullmatch(r"(?P<delta>\d{1,2}(?:\.\d+)?)D?(?P<right>[CP])", leg_part)
        if m:
            right = m.group("right").upper()
            delta = float(m.group("delta"))
            if delta <= 0.0 or delta >= 100.0:
                raise ValueError(f"Delta alias must be in (0,100): {symbol}")
            return _build(contract_spec=contract_spec, selector="delta", right=right, strike4=None, delta=delta, atm_offset_bps=None)

    m = re.fullmatch(
        rf"(?P<contract>(?:{_ROOT_TOKEN_PATTERN})?(?:CM\d+)|(?:{_ROOT_TOKEN_PATTERN})[FGHJKMNQUVXZ]\d{{2}})\s+ATM\s+(?P<right>STRADDLE|CALL|PUT)",
        token,
    )
    if m:
        contract_spec = _parse_contract_token(m.group("contract"))
        right = _right_word_to_token(m.group("right"))
        return _build(contract_spec=contract_spec, selector="atm", right=right, strike4=None, delta=None, atm_offset_bps=None)

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
        return _build(contract_spec=contract_spec, selector="delta", right=right, strike4=None, delta=delta, atm_offset_bps=None)

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
        atm_offset_bps = _to_float(spec.get("atm_offset_bps"))
        if selector == "strike":
            canonical = f"{resolved_contract}|{strike4}{right}"
        elif selector == "atm":
            canonical = f"{resolved_contract}|ATM{right}"
        elif selector == "atmf_offset":
            canonical = f"{resolved_contract}|{abs(float(atm_offset_bps)):g}BP{right}"
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
    return _shared_ql_option_type(right)


def _bachelier_price(right: str, strike: float, forward: float, vol_normal: float, tte: float, discount: float) -> float:
    return _shared_bachelier_price(right, strike, forward, vol_normal, tte, discount)


def _implied_normal_vol(right: str, strike: float, forward: float, tte: float, price: float, discount: float) -> float:
    return _shared_implied_normal_vol(right, strike, forward, tte, price, discount)


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
    return _shared_bachelier_greeks_fd(
        right=right,
        strike=strike,
        forward=forward,
        vol_normal=vol_normal,
        tte=tte,
        discount=discount,
        use_ql_calculator=use_ql_calculator,
    )


def _extract_row_price(row: Dict[str, Any], price_mode: str = "mid_then_fallback") -> Optional[float]:
    if price_mode != "mid_then_fallback":
        raise ValueError(f"Unsupported price_mode: {price_mode}")

    mid = _to_float(row.get("mid", row.get("Mid")))
    if mid is not None and mid > 0.0:
        return mid

    bid = _to_float(row.get("bidPrice", row.get("BidPrice", row.get("bid", row.get("Bid")))))
    ask = _to_float(row.get("askPrice", row.get("OfferPrice", row.get("ask", row.get("Ask")))))
    if bid is not None and ask is not None and bid > 0.0 and ask > 0.0:
        return 0.5 * (bid + ask)

    for key in ("lastPrice", "last", "mark", "Close", "close", "Open", "open"):
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


# Rebind the contract/strike helpers to the shared helper module so new
# products can depend on one implementation instead of this monolithic MDP.
_to_float = _shared_sofr_option_contracts._to_float
_right_word_to_token = _shared_sofr_option_contracts._right_word_to_token
_is_sofr_style_option_contract = _shared_sofr_option_contracts._is_sofr_style_option_contract
_decode_sofr_style_strike_token = _shared_sofr_option_contracts._decode_sofr_style_strike_token
_format_strike4 = _shared_sofr_option_contracts._format_strike4
_cme_listed_strike_rule_for_contract = _shared_sofr_option_contracts._cme_listed_strike_rule_for_contract
_cme_listed_abs_offset_grid_bps_for_contract_forward = (
    _shared_sofr_option_contracts._cme_listed_abs_offset_grid_bps_for_contract_forward
)
_snap_to_listed_strike_for_offset = _shared_sofr_option_contracts._snap_to_listed_strike_for_offset
_contract_to_barchart_contract = _shared_sofr_option_contracts._contract_to_barchart_contract
_parse_contract_token = _shared_sofr_option_contracts._parse_contract_token
_resolve_cm_contract = _shared_sofr_option_contracts._resolve_cm_contract
_resolve_contract_from_spec = _shared_sofr_option_contracts._resolve_contract_from_spec
_option_contract_to_underlying_contract = _shared_sofr_option_contracts._option_contract_to_underlying_contract
_parse_option_request_symbol = _shared_sofr_option_contracts._parse_option_request_symbol
_norm_option_symbol = _shared_sofr_option_contracts._norm_option_symbol
_resolve_option_contract_aliases_for_date = _shared_sofr_option_contracts._resolve_option_contract_aliases_for_date
_expand_straddle_symbol = _shared_sofr_option_contracts._expand_straddle_symbol
_canonical_to_barchart_contract = _shared_sofr_option_contracts._canonical_to_barchart_contract
_canonical_to_barchart_option = _shared_sofr_option_contracts._canonical_to_barchart_option
_canonical_contract = _shared_sofr_option_contracts._canonical_contract
_canonical_underlying = _shared_sofr_option_contracts._canonical_underlying
_strike_from_symbol = _shared_sofr_option_contracts._strike_from_symbol
_right_from_symbol = _shared_sofr_option_contracts._right_from_symbol
_contract_code_from_symbol = _shared_sofr_option_contracts._contract_code_from_symbol
_contract_expiry_date = _shared_sofr_option_contracts._contract_expiry_date
sofr_option_last_trade_date = _shared_sofr_option_contracts.sofr_option_last_trade_date
_front_sfr_option_contracts = _shared_sofr_option_contracts._front_sfr_option_contracts

class STIRFutureOptionMDP(MarketDataProvider[InstrumentLike], LayeredCacheMixin):
    _STIR_OPTION_CACHE = "_stir_option_pricer_cache"
    _RAW_EOD_CACHE_STEM = "STIRFutureOptionRawEOD_Cache"
    _BARCHART_STATE: Dict[str, Any] = {}
    _CURVE_STATE: Dict[str, Any] = {}
    _QS_STATE: Dict[str, Any] = {}

    def __init__(self, source: str = "STIRFO_DUAL-QL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        LayeredCacheMixin.__init__(self)

        self.cache_full_intraday_fetch = bool(kwargs.get("cache_full_intraday_fetch", False))
        self._schwab_app_key = kwargs.get("schwab_app_key") or os.getenv("SCHWABDEV_APP_KEY") or os.getenv("SCHWAB_APP_KEY") or "zm3GYiQREbtrpBHACURcNzFJIObUq2aX"
        self._schwab_app_secret = kwargs.get("schwab_app_secret") or os.getenv("SCHWABDEV_APP_SECRET") or os.getenv("SCHWAB_APP_SECRET") or "SznUHXvKPZUnmxG9"
        self._schwab_scope = kwargs.get("schwab_scope", "pystonk")
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

        # Candidate SOCKS hosts; runtime preflight + health-scoring pick the live/healthy
        # ones per call. NordVPN's working US SOCKS pool is small and flaky, so the list is
        # intentionally generous (dead hosts are filtered each run). socks-us2x/4x are the
        # newer nordvpn.com-scheme endpoints validated alongside the nordhold cities.
        default_hosts = [
            "atlanta.us.socks.nordhold.net",
            "chicago.us.socks.nordhold.net",
            "dallas.us.socks.nordhold.net",
            "los-angeles.us.socks.nordhold.net",
            "new-york.us.socks.nordhold.net",
            "phoenix.us.socks.nordhold.net",
            "san-francisco.us.socks.nordhold.net",
            "us.socks.nordhold.net",
            "socks-us29.nordvpn.com",
            "socks-us40.nordvpn.com",
            None,
        ]
        self._barchart_proxy_hosts: List[Optional[str]] = list(kwargs.get("barchart_proxy_hosts", default_hosts))
        if not self._socksio_enabled:
            self._barchart_proxy_hosts = [None]
        random.shuffle(self._barchart_proxy_hosts)
        self._barchart_proxy_ttl: int = int(kwargs.get("barchart_proxy_ttl", 60))
        self._barchart_session_token_pool_size_cap: int = max(1, int(kwargs.get("barchart_session_token_pool_size_cap", 24)))

        # Raw per-symbol EOD frame cache: full-history frames keyed by barchart symbol,
        # sliced locally per window. Historical data is immutable (a window ending before
        # the fetch day is always a hit); windows reaching "today" are TTL-gated so the
        # still-settling current bar stays live. L0 = in-process dict, L1 = local diskcache
        # (no Supabase L2 -- EOD frames must not be written to remote prod KV).
        self._raw_eod_cache_enabled: bool = bool(kwargs.get("raw_eod_cache", True))
        self._raw_eod_ttl_seconds: int = max(0, int(kwargs.get("raw_eod_ttl_seconds", 900)))
        self._raw_eod_mem: Dict[str, Dict[str, Any]] = {}
        self._raw_eod_lock = threading.RLock()
        self._raw_eod_disk_cache: Any = None

        # Multi-proxy fan-out (opt-in): shard a large symbol set across distinct NordVPN
        # SOCKS hosts and fetch the shards concurrently for ~K x throughput while keeping
        # each per-IP request rate modest (ban-safe). Off by default -> no behavior change.
        _fanout_env = os.getenv("STIRFO_BARCHART_FANOUT", "").strip().lower()
        self._barchart_fanout_enabled: bool = bool(
            kwargs.get("barchart_fanout", _fanout_env in {"1", "true", "yes", "on"})
        )
        self._barchart_fanout_max_shards: int = max(1, int(kwargs.get("barchart_fanout_max_shards", 6)))
        self._barchart_fanout_min_symbols_per_shard: int = max(
            1, int(kwargs.get("barchart_fanout_min_symbols_per_shard", 8))
        )
        # Work-stealing pool tuning: small batches keep fast/slow proxies balanced; a batch
        # is retried on another worker up to max_batch_attempts; a worker self-evicts after
        # evict_after consecutive failures (dead proxy).
        self._barchart_fanout_batch_size: int = max(1, int(kwargs.get("barchart_fanout_batch_size", 16)))
        self._barchart_fanout_max_batch_attempts: int = max(1, int(kwargs.get("barchart_fanout_max_batch_attempts", 2)))
        self._barchart_fanout_evict_after: int = max(1, int(kwargs.get("barchart_fanout_evict_after", 2)))
        # Tight per-symbol retry budget for fan-out workers: a degraded proxy fails its batch
        # fast (instead of ~22s of exponential backoff) so work-stealing re-routes it quickly.
        self._barchart_fanout_eod_max_retries: int = max(1, int(kwargs.get("barchart_fanout_eod_max_retries", 2)))
        self._barchart_fanout_eod_backoff: float = max(0.0, float(kwargs.get("barchart_fanout_eod_backoff", 0.5)))
        # A proxy a worker had to evict (passed preflight but failed barchart data requests)
        # is demoted for this cooldown so the next cold runs don't re-pick it.
        self._barchart_fanout_proxy_cooldown: int = max(0, int(kwargs.get("barchart_fanout_proxy_cooldown", 300)))

        if not STIRFutureOptionMDP._BARCHART_STATE:
            STIRFutureOptionMDP._BARCHART_STATE = {
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
                "ttl": self._barchart_proxy_ttl,
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
        cache_path = LayeredCacheMixin.default_cache_path("STIRFutureOptionPricer_Cache")
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
                        "atm_offset_bps": _to_float(spec.get("atm_offset_bps")),
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
            "cache_version": "stirfo_barchart_pricer_window_v2",
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

    @staticmethod
    def _normalize_sabr_smile_strike_offsets_bps(raw: Any) -> Tuple[List[float], bool]:
        if raw is None:
            return [], True
        if isinstance(raw, str):
            token = raw.strip().lower()
            if token in {"", "listed", "full", "auto"}:
                return [], True
            values = [raw]
        elif np.isscalar(raw):
            values = [raw]
        else:
            values = list(raw)

        if len(values) == 0:
            return [], True

        out: List[float] = []
        for value in values:
            offset = abs(float(value))
            if not math.isfinite(offset):
                raise ValueError(f"SABR smile strike offsets must be finite bps values: {value!r}")
            out.append(round(offset, 8))
        return sorted(set(out)), False

    def _normalize_sabr_smile_point_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        has_offsets = "strike_offsets_bps" in request
        has_deltas = "deltas" in request
        if has_offsets and has_deltas:
            raise ValueError("sabr_smile does not allow both 'deltas' and 'strike_offsets_bps'")
        if has_offsets:
            offsets_bps, auto_full = self._normalize_sabr_smile_strike_offsets_bps(request.get("strike_offsets_bps"))
            return {
                "mode": "atm_offset_bps",
                "strike_offsets_bps": list(offsets_bps),
                "auto_full_ladder": bool(auto_full),
            }
        return {
            "mode": "delta",
            "deltas": self._normalize_sabr_smile_deltas(request.get("deltas")),
            "auto_full_ladder": False,
        }

    def _validate_sabr_smile_request(
        self,
        request: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], datetime.date, Dict[str, Any], str, Dict[str, Any], bool, bool, str]:
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

        point_request = self._normalize_sabr_smile_point_request(request)
        curve_name = str(request.get("curve_name", self._curve_name_default))
        curve_kwargs = dict(request.get("curve_kwargs") or {})
        force_refresh = bool(request.get("force_refresh", False))
        show_tqdm = bool(request.get("show_tqdm", False))
        calibration_method = str(request.get("calibration_method", "nelder-mead")).strip().lower().replace("_", "-")
        if calibration_method not in {"nelder-mead", "de-gn"}:
            raise ValueError(f"Unsupported SABR calibration_method: {request.get('calibration_method')!r}")
        return raw_symbol, symbol_info, as_of, point_request, curve_name, curve_kwargs, force_refresh, show_tqdm, calibration_method

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
        as_of: DateLike,
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
            "delta_ignore_deep_itm": True,
            "force_refresh": force_refresh,
            "show_tqdm": show_tqdm,
        }

    @staticmethod
    def _sabr_smile_point_mode(point_request: Dict[str, Any]) -> str:
        return str((point_request or {}).get("mode", "delta")).strip().lower()

    def _resolve_sabr_smile_underlying_forward(
        self,
        *,
        contract: str,
        as_of: datetime.date,
        show_tqdm: bool,
        price_mode: str = "mid_then_fallback",
    ) -> Tuple[str, float]:
        underlying_contract = _option_contract_to_underlying_contract(contract)
        bcontract = _contract_to_barchart_contract(underlying_contract)
        data = self._fetch_barchart_eod_series(
            symbols=[bcontract],
            start=as_of,
            end=as_of,
            show_tqdm=show_tqdm,
        )
        fut_df = data.get(bcontract)
        if fut_df is None or fut_df.empty:
            raise ValueError(f"Could not resolve SABR smile forward: missing underlying history for {contract}")

        target_ts = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(as_of, datetime.time(17, 0))))
        pos = _asof_index_position(fut_df.index, target_ts)
        if pos is None:
            raise ValueError(f"Could not resolve SABR smile forward: no underlying row near {as_of.isoformat()} for {contract}")
        forward = _extract_row_price(fut_df.iloc[pos].to_dict(), price_mode=price_mode)
        if forward is None or forward <= 0.0:
            raise ValueError(f"Could not resolve SABR smile forward: invalid underlying price for {contract}")
        return underlying_contract, float(forward)

    def _resolve_sabr_smile_live_underlying_forward(
        self,
        *,
        contract: str,
        price_mode: str = "mid_then_fallback",
    ) -> Tuple[str, float]:
        underlying_contract = _option_contract_to_underlying_contract(contract)
        forward_map = self._fetch_schwab_live_underlying_forwards(
            contracts=[underlying_contract],
            price_mode=price_mode,
        )
        forward = _to_float(forward_map.get(underlying_contract))
        if forward is None or forward <= 0.0:
            raise ValueError(f"Could not resolve SABR smile live forward: missing Schwab live price for {contract}")
        return underlying_contract, float(forward)

    def _build_sabr_smile_offset_leg_specs(
        self,
        *,
        contract: str,
        forward: float,
        as_of: datetime.date,
        offset_magnitudes_bps: Sequence[float],
        auto_full_ladder: bool,
    ) -> List[Dict[str, Any]]:
        offset_info = _cme_listed_abs_offset_grid_bps_for_contract_forward(
            contract=contract,
            forward=float(forward),
            as_of=as_of,
        )
        if offset_info is None:
            raise ValueError(f"Offset-based SABR smile is not supported for contract {contract}")

        atm_strike, abs_offsets, _ = offset_info
        requested_abs_offsets = (
            [float(offset) for offset in abs_offsets if float(offset) <= _SABR_SMILE_LISTED_OFFSET_CAP_BPS + 1e-9]
            if auto_full_ladder
            else sorted(set([0.0] + [float(x) for x in offset_magnitudes_bps]))
        )
        out: List[Dict[str, Any]] = []
        seen_symbols: set[str] = set()

        for right, signed_offsets in (
            ("C", [0.0] + [float(x) for x in requested_abs_offsets if float(x) > 0.0]),
            ("P", [0.0] + [-float(x) for x in requested_abs_offsets if float(x) > 0.0]),
        ):
            for signed_offset in signed_offsets:
                snapped_strike, actual_offset = _snap_to_listed_strike_for_offset(
                    contract=contract,
                    forward=float(forward),
                    as_of=as_of,
                    right=right,
                    offset_bps=float(signed_offset),
                )
                canonical_symbol = f"{contract}|{_format_strike4(snapped_strike, contract=contract)}{right}"
                if canonical_symbol in seen_symbols:
                    continue
                seen_symbols.add(canonical_symbol)
                out.append(
                    {
                        "right": right,
                        "label": canonical_symbol,
                        "canonical_symbol": canonical_symbol,
                        "requested_atm_offset_bps": float(actual_offset),
                        "requested_delta_abs": None,
                        "atm_strike": float(atm_strike),
                        "strike_price": float(snapped_strike),
                    }
                )
        return out

    @staticmethod
    def _build_sabr_smile_leg_selection(
        *,
        label: str,
        right: str,
        pricer: QLSTIRFutureOptionPricer,
        requested_delta_abs: Optional[float],
        requested_atm_offset_bps: Optional[float],
        canonical_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "label": str(label),
            "right": str(right).upper(),
            "pricer": pricer,
            "requested_delta_abs": None if requested_delta_abs is None else float(requested_delta_abs),
            "requested_atm_offset_bps": None if requested_atm_offset_bps is None else float(requested_atm_offset_bps),
            "canonical_symbol": str(canonical_symbol) if canonical_symbol else None,
        }

    def _selected_sabr_smile_legs_from_delta_map(
        self,
        *,
        selected_pricers: Dict[Tuple[str, int], QLSTIRFutureOptionPricer],
        labels_by_key: Optional[Dict[Tuple[str, int], str]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        labels_by_key = dict(labels_by_key or {})
        for key in sorted(selected_pricers.keys(), key=lambda item: (item[0], item[1])):
            right, delta = key
            pr = selected_pricers[key]
            label = labels_by_key.get(key)
            if not label:
                label = str((pr.meta() or {}).get("qs_series_label", pr.symbol()))
            out.append(
                self._build_sabr_smile_leg_selection(
                    label=label,
                    right=str(right),
                    pricer=pr,
                    requested_delta_abs=float(delta),
                    requested_atm_offset_bps=None,
                )
            )
        return out

    @staticmethod
    def _pricer_delta_abs(pr: QLSTIRFutureOptionPricer, *, fallback: Optional[float] = None) -> float:
        delta_val = _to_float(pr.delta())
        if delta_val is not None and math.isfinite(float(delta_val)):
            out = abs(float(delta_val))
            if out <= 1.0:
                out *= 100.0
            if out > 0.0:
                return float(out)
        if fallback is not None:
            return float(abs(float(fallback)))
        return float("nan")

    def _canonicalize_sabr_smile_leg(
        self,
        *,
        as_of: datetime.date,
        right: str,
        pricer: QLSTIRFutureOptionPricer,
        requested_delta_abs: Optional[float],
        label: str,
        canonical_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            option_contract = _canonical_contract(pricer.symbol())
        except Exception:
            option_contract = str(pricer.underlying_symbol()).upper()
        forward = float(pricer.forward())
        raw_strike = float(pricer.strike())
        strike_price = raw_strike
        atm_strike = _atm_strike_from_forward(float(forward), step=_strike_step_for_contract(option_contract))
        if math.isfinite(raw_strike) and raw_strike > 0.0:
            offset_info = _cme_listed_abs_offset_grid_bps_for_contract_forward(
                contract=option_contract,
                forward=float(forward),
                as_of=as_of,
            )
            if offset_info is not None:
                grid_atm, _, _ = offset_info
                atm_strike = float(grid_atm)
                strike_price, _ = _snap_to_listed_strike_for_offset(
                    contract=option_contract,
                    forward=float(forward),
                    as_of=as_of,
                    right=right,
                    offset_bps=(float(atm_strike) - float(raw_strike)) * 100.0,
                )
        actual_symbol = canonical_symbol or f"{option_contract}|{_format_strike4(strike_price, contract=option_contract)}{str(right).upper()}"
        atm_offset_bps = round((float(atm_strike) - float(strike_price)) * 100.0, 8)
        return {
            "label": str(label),
            "right": str(right).upper(),
            "canonical_symbol": str(actual_symbol),
            "strike_price": float(strike_price),
            "atm_offset_bps": float(atm_offset_bps),
            "delta_abs": self._pricer_delta_abs(pricer, fallback=requested_delta_abs),
            "pricer": pricer,
        }

    def _build_sabr_smile_common_cache_key(
        self,
        *,
        as_of: datetime.date,
        curve_name: str,
        curve_kwargs: Dict[str, Any],
        canonical_legs: Sequence[str],
        calibration_method: str,
    ) -> Optional[str]:
        legs = sorted({str(symbol).upper() for symbol in canonical_legs if str(symbol).strip()})
        if not legs:
            return None
        payload = {
            "schema": 1,
            "cache_version": "stirfo_sabr_smile_common_v3",
            "source": str(self.source).upper(),
            "as_of": as_of.isoformat(),
            "curve_name": str(curve_name),
            "curve_kwargs": self._cache_primitive(curve_kwargs or {}),
            "calibration_method": str(calibration_method).strip().lower(),
            "legs": legs,
        }
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(payload_str.encode("utf-8")).hexdigest()
        return f"STIRFO_SABR_COMMON::{digest}"

    @staticmethod
    def _sabr_smile_with_symbol(
        smile: STIRFutureOptionSABRSmile,
        *,
        symbol: str,
    ) -> STIRFutureOptionSABRSmile:
        if str(smile.symbol) == str(symbol):
            return smile
        return STIRFutureOptionSABRSmile(
            source=str(smile.source),
            symbol=str(symbol),
            underlying_contract=str(smile.underlying_contract),
            quote_timestamp=smile.quote_timestamp,
            params=smile.params,
            points=tuple(smile.points),
        )

    @staticmethod
    def _flip_stir_sabr_smile_point_label(label: str) -> str:
        text = str(label)

        def _swap_word(match: re.Match[str]) -> str:
            word = match.group(0)
            replacement = "Put" if word.lower() == "call" else "Call"
            if word.isupper():
                return replacement.upper()
            if word.islower():
                return replacement.lower()
            return replacement

        swapped, count = re.subn(r"\b(Call|Put)\b", _swap_word, text, count=1, flags=re.IGNORECASE)
        if count:
            return swapped
        if text.endswith("C"):
            return f"{text[:-1]}P"
        if text.endswith("P"):
            return f"{text[:-1]}C"
        return text

    @classmethod
    def _normalize_stir_sabr_smile_convention(
        cls,
        smile: STIRFutureOptionSABRSmile,
    ) -> STIRFutureOptionSABRSmile:
        if not isinstance(smile, STIRFutureOptionSABRSmile):
            return smile

        call_strikes = [
            float(pt.strike_price)
            for pt in smile.points
            if str(pt.right).upper() == "C" and math.isfinite(float(pt.strike_price))
        ]
        put_strikes = [
            float(pt.strike_price)
            for pt in smile.points
            if str(pt.right).upper() == "P" and math.isfinite(float(pt.strike_price))
        ]
        if not call_strikes or not put_strikes:
            return smile

        call_mid = float(np.median(np.asarray(call_strikes, dtype=float)))
        put_mid = float(np.median(np.asarray(put_strikes, dtype=float)))
        if not math.isfinite(call_mid) or not math.isfinite(put_mid) or call_mid >= put_mid - 1e-10:
            return smile

        # STIR smiles should preserve futures-price call/put semantics:
        # calls on the higher-price / lower-rate wing, puts on the lower-price / higher-rate wing.
        flipped_points = []
        for pt in smile.points:
            right = str(pt.right).upper()
            if right not in {"C", "P"}:
                flipped_points.append(pt)
                continue
            flipped_points.append(
                replace(
                    pt,
                    right="P" if right == "C" else "C",
                    label=cls._flip_stir_sabr_smile_point_label(pt.label),
                )
            )

        return replace(smile, points=tuple(sorted(flipped_points, key=lambda pt: pt.strike_price)))

    def _load_sabr_smile_common_cache(
        self,
        *,
        common_key: Optional[str],
    ) -> Optional[STIRFutureOptionSABRSmile]:
        if not common_key:
            return None
        cached = self._threadsafe_cache_get(common_key)
        hit = self._deserialize_get_data_result(cached)
        if hit is None:
            return None
        smiles = hit.get("sabr_smile") or []
        return smiles[0] if smiles else None

    def _store_sabr_smile_common_cache(
        self,
        *,
        common_key: Optional[str],
        smile: STIRFutureOptionSABRSmile,
    ) -> None:
        if not common_key:
            return
        self._threadsafe_cache_put(
            common_key,
            self._serialize_get_data_result("sabr_smile", {"sabr_smile": [smile]}),
        )

    @staticmethod
    def _pricer_meta_number(pricer: QLSTIRFutureOptionPricer, keys: Sequence[str]) -> Optional[float]:
        meta = pricer.meta() if callable(getattr(pricer, "meta", None)) else {}
        if not isinstance(meta, dict):
            return None
        rows: List[Dict[str, Any]] = []
        for row_key in ("vendor_row", "raw_quote", "vendor_quote"):
            row = meta.get(row_key)
            if isinstance(row, dict):
                rows.append(row)
        rows.append(meta)
        for row in rows:
            for key in keys:
                val = _to_float(row.get(key))
                if val is not None and math.isfinite(float(val)):
                    return float(val)
        return None

    @classmethod
    def _pricer_open_interest(cls, pricer: QLSTIRFutureOptionPricer) -> Optional[float]:
        return cls._pricer_meta_number(
            pricer,
            ("Open Interest", "openInterest", "open_interest", "OpenInterest", "openinterest"),
        )

    @classmethod
    def _pricer_volume(cls, pricer: QLSTIRFutureOptionPricer) -> Optional[float]:
        return cls._pricer_meta_number(pricer, ("Volume", "volume"))

    def _resolve_delta_from_sabr_cache(
        self,
        *,
        contract: str,
        as_of: datetime.date,
        target_delta: float,
        right: str,
        forward: float,
    ) -> Optional[QLSTIRFutureOptionPricer]:
        """Resolve a delta-addressed option from a cached SABR smile.

        Returns a synthetic QLSTIRFutureOptionPricer if a calibrated SABR
        smile is available in the cache for this contract/date, or None to
        fall through to the chain-fetching path.
        """
        try:
            smile = None
            # Try the get_data sabr_smile cache first (keyed by contract + as_of)
            smile_key = self._build_get_data_cache_key("sabr_smile", {
                "endpoint": "sabr_smile",
                "symbol": contract,
                "as_of": as_of,
            })
            if smile_key:
                cached = self._threadsafe_cache_get(smile_key)
                hit = self._deserialize_get_data_result(cached)
                if hit is not None:
                    smiles = hit.get("sabr_smile") or []
                    smile = smiles[0] if smiles else None
            if smile is None:
                return None

            p = smile.params
            if p.time_to_expiry <= 0.0:
                return None

            atm_vol = _sabr_normal_vol(
                strike=p.forward_price, forward=p.forward_price,
                time_to_expiry=p.time_to_expiry,
                alpha=p.alpha, beta=p.beta, rho=p.rho, nu=p.nu,
            )
            strike = _normal_delta_to_strike(
                delta_abs=target_delta / 100.0,
                vol_normal=atm_vol,
                forward=p.forward_price,
                time_to_expiry=p.time_to_expiry,
                right=right,
            )
            vol_at_strike = _sabr_normal_vol(
                strike=strike, forward=p.forward_price,
                time_to_expiry=p.time_to_expiry,
                alpha=p.alpha, beta=p.beta, rho=p.rho, nu=p.nu,
            )
            if not math.isfinite(vol_at_strike) or vol_at_strike <= 0.0:
                return None

            price = _bachelier_price(right, strike, p.forward_price, vol_at_strike, p.time_to_expiry, 1.0)
            delta_val, gamma_val, vega_val, theta_val = _shared_bachelier_greeks_fd(
                right=right, strike=strike, forward=p.forward_price,
                vol_normal=vol_at_strike, tte=p.time_to_expiry, discount=1.0,
            )

            underlying = _option_contract_to_underlying_contract(contract)
            strike4 = _format_strike4(strike, contract=contract)
            symbol = f"{contract}|{strike4}{right}"
            quote_ts = _NY_TZ.localize(datetime.datetime.combine(as_of, datetime.time(17, 0)))

            return QLSTIRFutureOptionPricer(
                symbol=symbol, right=right,
                underlying_symbol=underlying,
                strike=strike, quote_timestamp=quote_ts,
                expiry_date=p.expiry_date,
                market_price=price, model_price=price,
                iv_normal=vol_at_strike,
                delta=delta_val, gamma=gamma_val,
                vega=vega_val, theta=theta_val,
                forward=p.forward_price, discount=1.0,
                meta_data={"source": "SABR_CACHE", "sabr_alpha": p.alpha,
                           "sabr_rho": p.rho, "sabr_nu": p.nu},
            )
        except Exception:
            return None

    def _build_sabr_smile_jpm_leg_specs(
        self,
        *,
        contract: str,
        forward: float,
        as_of: datetime.date,
    ) -> List[Dict[str, Any]]:
        grid = _cme_listed_strike_grid_for_contract_forward(
            contract=contract,
            forward=float(forward),
            as_of=as_of,
        )
        if grid is None:
            raise ValueError(f"No listed strike rule available for JPM SABR smile on {contract}")

        atm_strike = float(grid["atm_strike"])
        specs: List[Dict[str, Any]] = []
        for strike in list(grid["strikes"]):
            strike_f = float(strike)
            for right in ("C", "P"):
                canonical_symbol = f"{contract}|{_format_strike4(strike_f, contract=contract)}{right}"
                specs.append(
                    {
                        "label": canonical_symbol,
                        "right": right,
                        "strike_price": strike_f,
                        "canonical_symbol": canonical_symbol,
                        "requested_atm_offset_bps": round((atm_strike - strike_f) * 100.0, 8),
                    }
                )
        return specs

    def _filter_sabr_smile_jpm_legs(
        self,
        selected_legs: Sequence[Dict[str, Any]],
        *,
        open_interest_min: float,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for leg in selected_legs:
            pr = leg.get("pricer")
            if pr is None:
                continue
            right_raw = leg.get("right")
            if right_raw is None:
                pricer_right = getattr(pr, "right", None)
                right_raw = pricer_right() if callable(pricer_right) else None
            right = str(right_raw or "").upper()
            if right not in {"C", "P"}:
                continue
            strike = _to_float(getattr(pr, "strike", lambda: None)())
            forward = _to_float(getattr(pr, "forward", lambda: None)())
            if strike is None or forward is None:
                continue
            is_otm = (right == "C" and strike >= forward - 1e-12) or (right == "P" and strike <= forward + 1e-12)
            if not is_otm:
                continue
            oi = self._pricer_open_interest(pr)
            if oi is None or oi < float(open_interest_min):
                continue
            out.append(dict(leg))
        if len(out) < 6:
            raise ValueError(
                f"JPM SABR smile requires at least 6 OTM legs with open interest >= {open_interest_min:g}; got {len(out)}"
            )
        return out

    def _finalize_sabr_smile_result(
        self,
        *,
        raw_symbol: str,
        as_of: datetime.date,
        selected_legs: Sequence[Dict[str, Any]],
        curve_name: str,
        curve_kwargs: Dict[str, Any],
        force_refresh: bool,
        calibration_method: str,
        enable_common_cache: bool = True,
    ) -> Tuple[STIRFutureOptionSABRSmile, Optional[str]]:
        normalized_legs = self._normalize_sabr_smile_selected_legs(as_of=as_of, selected_legs=selected_legs)
        common_key: Optional[str] = None
        if enable_common_cache:
            common_key = self._build_sabr_smile_common_cache_key(
                as_of=as_of,
                curve_name=curve_name,
                curve_kwargs=curve_kwargs,
                canonical_legs=[str(leg["canonical_symbol"]) for leg in normalized_legs],
                calibration_method=calibration_method,
            )
            if not force_refresh:
                cached_smile = self._load_sabr_smile_common_cache(common_key=common_key)
                if cached_smile is not None:
                    return self._sabr_smile_with_symbol(cached_smile, symbol=raw_symbol), common_key
        return (
            self._assemble_sabr_smile_result(
                raw_symbol=raw_symbol,
                as_of=as_of,
                selected_legs=selected_legs,
                calibration_method=calibration_method,
            ),
            common_key,
        )

    def _resolve_sabr_smile_contract(
        self,
        *,
        symbol_info: Dict[str, Any],
        as_of: datetime.date,
        assert_tradable: bool = True,
    ) -> str:
        contract = self._resolve_sabr_smile_contract_unchecked(symbol_info=symbol_info, as_of=as_of)
        if assert_tradable:
            self._assert_sabr_smile_chain_tradable(contract=contract, as_of=as_of)
        return contract

    def _resolve_sabr_smile_contract_unchecked(
        self,
        *,
        symbol_info: Dict[str, Any],
        as_of: datetime.date,
    ) -> str:
        src = str(self.source).upper()
        kind = str(symbol_info.get("kind", "")).strip().lower()
        if src == "STIRFO_DUAL-QL":
            if kind == "listed":
                return str(symbol_info["canonical_contract"])
            return _resolve_cm_contract(
                cm_root=_ROOT_ALIAS_MAP[str(symbol_info["root_globex"]).upper()],
                cm_rank=1,
                as_of=as_of,
            )
        if src == "BARCHART_STIRFO-QL":
            if kind == "listed":
                return str(symbol_info["contract"])
            return _resolve_cm_contract(
                cm_root=str(symbol_info["cm_root"]),
                cm_rank=int(symbol_info["cm_rank"]),
                as_of=as_of,
            )
        raise NotImplementedError(f"Unsupported SABR smile source for contract resolution: {self.source!r}")

    @staticmethod
    def _live_sofr_option_contracts(as_of: datetime.date, *, limit: int = 3) -> List[str]:
        candidates = list(_front_sfr_option_contracts(as_of))
        live = [c for c in candidates if (sofr_option_last_trade_date(c) or as_of) >= as_of]
        live.sort(key=lambda c: (sofr_option_last_trade_date(c) or datetime.date.max))
        return live[:limit]

    def _assert_sabr_smile_chain_tradable(self, *, contract: str, as_of: datetime.date) -> None:
        """Reject an as_of after the option chain stopped trading.

        The underlying SR3 future keeps trading for another quarter after its options
        terminate, so the forward resolves cleanly and the request would otherwise only
        fail deep inside leg selection with a bare list of "missing" strikes.
        """
        last_trade = sofr_option_last_trade_date(contract)
        if last_trade is None or as_of <= last_trade:
            return
        alternatives = self._live_sofr_option_contracts(as_of)
        suggestion = f" Still listed on that date: {', '.join(alternatives)}." if alternatives else ""
        raise ValueError(
            f"{contract} options terminated trading on {last_trade.isoformat()} (the Friday "
            f"preceding the third Wednesday of the contract month); the requested as_of "
            f"{as_of.isoformat()} is {(as_of - last_trade).days} days later, so the chain has no "
            f"quotes. The underlying future keeps trading until the end of the reference quarter, "
            f"which is why the forward still resolves.{suggestion}"
        )

    def _resolve_sabr_smile_forward_from_underlying_data(
        self,
        *,
        contract: str,
        as_of: datetime.date,
        underlying_data: Dict[str, pd.DataFrame],
        price_mode: str,
    ) -> float:
        underlying_contract = _option_contract_to_underlying_contract(contract)
        bcontract = _contract_to_barchart_contract(underlying_contract)
        fut_df = underlying_data.get(bcontract)
        if fut_df is None or fut_df.empty:
            raise ValueError(f"Could not resolve SABR smile forward: missing underlying history for {contract}")
        target_ts = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(as_of, datetime.time(17, 0))))
        pos = _asof_index_position(fut_df.index, target_ts)
        if pos is None:
            raise ValueError(f"Could not resolve SABR smile forward: no underlying row near {as_of.isoformat()} for {contract}")
        forward = _extract_row_price(fut_df.iloc[pos].to_dict(), price_mode=price_mode)
        if forward is None or forward <= 0.0:
            raise ValueError(f"Could not resolve SABR smile forward: invalid underlying price for {contract}")
        return float(forward)

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

    def _select_sabr_smile_qs_offset_legs(
        self,
        *,
        pricers_by_series: Dict[str, List[QLSTIRFutureOptionPricer]],
        as_of: datetime.date,
        requested_legs: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        selected: Dict[Tuple[str, float], QLSTIRFutureOptionPricer] = {}
        available_dates: set[datetime.date] = set()

        for series_name, plist in pricers_by_series.items():
            for pr in plist:
                quote_day = pr.quote_timestamp().astimezone(_NY_TZ).date()
                available_dates.add(quote_day)
                if quote_day != as_of:
                    continue
                meta = pr.meta() if callable(getattr(pr, "meta", None)) else {}
                qs_query = dict((meta or {}).get("qs_query") or {})
                label = str((meta or {}).get("qs_series_label", series_name))
                right = self._qs_right_from_label_and_query(label=label, query=qs_query)
                strike_raw = _to_float(qs_query.get("strike"))
                if right not in {"C", "P"} or strike_raw is None:
                    continue
                key = (right, round(float(strike_raw), 8))
                current = selected.get(key)
                if current is None or pr.quote_timestamp() > current.quote_timestamp():
                    selected[key] = pr

        out: List[Dict[str, Any]] = []
        missing: List[str] = []
        for spec in requested_legs:
            right = str(spec["right"]).upper()
            strike = round(float(spec["strike_price"]), 8)
            pr = selected.get((right, strike))
            if pr is None:
                missing.append(str(spec["canonical_symbol"]))
                continue
            out.append(
                self._build_sabr_smile_leg_selection(
                    label=str(spec["label"]),
                    right=right,
                    pricer=pr,
                    requested_delta_abs=None,
                    requested_atm_offset_bps=_to_float(spec.get("requested_atm_offset_bps")),
                    canonical_symbol=str(spec["canonical_symbol"]),
                )
            )

        if missing:
            av = ", ".join(sorted(d.isoformat() for d in available_dates)) or "none"
            raise ValueError(f"Missing SABR smile strike legs for {as_of.isoformat()}: {missing}. Available quote dates: {av}.")
        return out

    @staticmethod
    def _resolve_pricer_window_quote_day(
        *,
        requested_legs: Sequence[Dict[str, Any]],
        pricers_window: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]],
        target_date: datetime.date,
    ) -> Optional[datetime.date]:
        """Latest session on or before ``target_date`` that any requested leg printed on.

        The whole smile is then taken from that one session.  Resolving each leg's own
        as-of independently produced cross-session smiles: on 2026-06-16 the SFRM26 ATM
        call came from 2026-06-12 (the chain's last trading day) while every other strike
        came from 2026-06-11.
        """
        days: set[datetime.date] = set()
        for spec in requested_legs:
            for day in pricers_window.get(str(spec["canonical_symbol"]), {}):
                if day <= target_date:
                    days.add(day)
        return max(days) if days else None

    def _resolve_sabr_smile_pricer_window_session(
        self,
        *,
        requested_legs: Sequence[Dict[str, Any]],
        pricers_window: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]],
        target_date: datetime.date,
    ) -> datetime.date:
        quote_day = self._resolve_pricer_window_quote_day(
            requested_legs=requested_legs,
            pricers_window=pricers_window,
            target_date=target_date,
        )
        if quote_day is None:
            raise ValueError(
                f"No quotes on or before {target_date.isoformat()} for any of the "
                f"{len(requested_legs)} requested SABR smile legs"
                f"{self._sabr_smile_expiry_hint(requested_legs=requested_legs, as_of=target_date)}"
            )
        staleness = (target_date - quote_day).days
        if staleness > _SABR_SMILE_MAX_QUOTE_STALENESS_DAYS:
            raise ValueError(
                f"SABR smile quotes for {target_date.isoformat()} are stale: the last session with "
                f"any quoted leg is {quote_day.isoformat()} ({staleness} days earlier, limit "
                f"{_SABR_SMILE_MAX_QUOTE_STALENESS_DAYS})"
                f"{self._sabr_smile_expiry_hint(requested_legs=requested_legs, as_of=target_date)}"
            )
        return quote_day

    @staticmethod
    def _sabr_smile_expiry_hint(
        *,
        requested_legs: Sequence[Dict[str, Any]],
        as_of: datetime.date,
    ) -> str:
        if not requested_legs:
            return "."
        try:
            contract = str(requested_legs[0]["canonical_symbol"]).split("|", 1)[0]
            last_trade = sofr_option_last_trade_date(contract)
        except Exception:
            return "."
        if last_trade is None or as_of <= last_trade:
            return "."
        return (
            f"; {contract} options terminated trading on {last_trade.isoformat()}, "
            f"{(as_of - last_trade).days} days before the requested as_of."
        )

    def _select_sabr_smile_explicit_legs_from_pricer_window(
        self,
        *,
        requested_legs: Sequence[Dict[str, Any]],
        pricers_window: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]],
        target_date: datetime.date,
    ) -> List[Dict[str, Any]]:
        quote_day = self._resolve_sabr_smile_pricer_window_session(
            requested_legs=requested_legs,
            pricers_window=pricers_window,
            target_date=target_date,
        )
        # Derived from the request, not from whichever leg resolved last: legs pinned to
        # an ATM offset were snapped onto a rule lattice that need not be fully listed,
        # so gaps are expected.  Explicitly named strikes must all be present.
        offset_mode = any(
            _to_float(spec.get("requested_atm_offset_bps")) is not None for spec in requested_legs
        )

        out: List[Dict[str, Any]] = []
        missing: List[str] = []
        for spec in requested_legs:
            canonical_symbol = str(spec["canonical_symbol"])
            pr = pricers_window.get(canonical_symbol, {}).get(quote_day)
            if pr is None:
                missing.append(canonical_symbol)
                continue
            out.append(
                self._build_sabr_smile_leg_selection(
                    label=str(spec["label"]),
                    right=str(spec["right"]),
                    pricer=pr,
                    requested_delta_abs=None,
                    requested_atm_offset_bps=_to_float(spec.get("requested_atm_offset_bps")),
                    canonical_symbol=canonical_symbol,
                )
            )

        if missing and not offset_mode:
            raise ValueError(
                f"Missing SABR smile strike legs for {target_date.isoformat()} "
                f"(quote session {quote_day.isoformat()}): {missing}."
                f"{self._sabr_smile_expiry_hint(requested_legs=requested_legs, as_of=target_date)}"
            )
        return out

    def _select_sabr_smile_available_legs_from_pricer_window(
        self,
        *,
        requested_legs: Sequence[Dict[str, Any]],
        pricers_window: Dict[str, Dict[datetime.date, QLSTIRFutureOptionPricer]],
        target_date: datetime.date,
    ) -> List[Dict[str, Any]]:
        quote_day = self._resolve_sabr_smile_pricer_window_session(
            requested_legs=requested_legs,
            pricers_window=pricers_window,
            target_date=target_date,
        )
        out: List[Dict[str, Any]] = []
        for spec in requested_legs:
            canonical_symbol = str(spec["canonical_symbol"])
            pr = pricers_window.get(canonical_symbol, {}).get(quote_day)
            if pr is None:
                continue
            out.append(
                self._build_sabr_smile_leg_selection(
                    label=str(spec["label"]),
                    right=str(spec["right"]),
                    pricer=pr,
                    requested_delta_abs=None,
                    requested_atm_offset_bps=_to_float(spec.get("requested_atm_offset_bps")),
                    canonical_symbol=canonical_symbol,
                )
            )
        return out

    def _select_sabr_smile_explicit_legs_from_snapshot(
        self,
        *,
        requested_legs: Sequence[Dict[str, Any]],
        pricers_by_symbol: Dict[str, List[QLSTIRFutureOptionPricer]],
        target_date: datetime.date,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        missing: List[str] = []
        requested_atm_offset = False
        available_dates: set[datetime.date] = set()

        for spec in requested_legs:
            canonical_symbol = str(spec["canonical_symbol"])
            chosen: Optional[QLSTIRFutureOptionPricer] = None
            for pr in pricers_by_symbol.get(canonical_symbol, []):
                quote_day = pr.quote_timestamp().astimezone(_NY_TZ).date()
                available_dates.add(quote_day)
                if quote_day != target_date:
                    continue
                if chosen is None or pr.quote_timestamp() > chosen.quote_timestamp():
                    chosen = pr
            if chosen is None:
                missing.append(canonical_symbol)
                continue
            out.append(
                self._build_sabr_smile_leg_selection(
                    label=str(spec["label"]),
                    right=str(spec["right"]),
                    pricer=chosen,
                    requested_delta_abs=None,
                    requested_atm_offset_bps=_to_float(spec.get("requested_atm_offset_bps")),
                    canonical_symbol=canonical_symbol,
                )
            )
            requested_atm_offset = requested_atm_offset or _to_float(spec.get("requested_atm_offset_bps")) is not None

        if missing and not requested_atm_offset:
            av = ", ".join(sorted(d.isoformat() for d in available_dates)) or "none"
            raise ValueError(f"Missing SABR smile strike legs for {target_date.isoformat()}: {missing}. Available quote dates: {av}.")
        return out

    def _normalize_sabr_smile_selected_legs(
        self,
        *,
        as_of: datetime.date,
        selected_legs: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for leg in selected_legs:
            out.append(
                self._canonicalize_sabr_smile_leg(
                    as_of=as_of,
                    right=str(leg["right"]),
                    pricer=leg["pricer"],
                    requested_delta_abs=_to_float(leg.get("requested_delta_abs")),
                    label=str(leg["label"]),
                    canonical_symbol=leg.get("canonical_symbol"),
                )
            )
        out.sort(key=lambda row: (float(row["strike_price"]), str(row["right"])))
        return out

    @staticmethod
    def _ensure_sabr_smile_pricer_consistency(
        selected_legs: Sequence[Dict[str, Any]],
    ) -> Tuple[str, float, datetime.date]:
        pricers = [leg["pricer"] for leg in selected_legs]
        if not pricers:
            raise ValueError("No option pricers available for SABR smile calibration.")
        ref_underlying = str(pricers[0].underlying_symbol()).upper()
        ref_forward = float(pricers[0].forward())
        ref_expiry = pricers[0].expiry_date()
        ref_quote_day = pricers[0].quote_timestamp().astimezone(_NY_TZ).date()
        for pr in pricers[1:]:
            if str(pr.underlying_symbol()).upper() != ref_underlying:
                raise ValueError("SABR smile legs do not agree on underlying contract.")
            if pr.expiry_date() != ref_expiry:
                raise ValueError("SABR smile legs do not agree on expiry date.")
            quote_day = pr.quote_timestamp().astimezone(_NY_TZ).date()
            if quote_day != ref_quote_day:
                raise ValueError(
                    "SABR smile legs do not agree on quote session: "
                    f"{ref_quote_day.isoformat()} vs {quote_day.isoformat()}."
                )
            if not math.isclose(float(pr.forward()), ref_forward, rel_tol=0.0, abs_tol=1e-8):
                raise ValueError(
                    "SABR smile legs do not agree on forward price: "
                    f"{ref_forward!r} vs {float(pr.forward())!r}."
                )
        return ref_underlying, ref_forward, ref_expiry

    def _assemble_sabr_smile_result(
        self,
        *,
        raw_symbol: str,
        as_of: datetime.date,
        selected_legs: Sequence[Dict[str, Any]],
        calibration_method: str = "nelder-mead",
    ) -> STIRFutureOptionSABRSmile:
        normalized_legs = self._normalize_sabr_smile_selected_legs(as_of=as_of, selected_legs=selected_legs)
        underlying_contract, forward_price, expiry_date = self._ensure_sabr_smile_pricer_consistency(normalized_legs)
        time_to_expiry = (expiry_date - as_of).days / 365.0
        if time_to_expiry <= 0.0:
            raise ValueError(f"SABR smile requires positive time to expiry, got {time_to_expiry} for {expiry_date.isoformat()}")

        market_points = [
            (float(leg["strike_price"]), float(leg["pricer"].iv_normal()))
            for leg in normalized_legs
            if math.isfinite(float(leg["pricer"].iv_normal())) and float(leg["pricer"].iv_normal()) > 0.0
        ]
        params_seed = _calibrate_sabr_normal_from_strike_points(
            forward=float(forward_price),
            time_to_expiry=float(time_to_expiry),
            market_points=market_points,
            beta=0.5,
            calibration_method=calibration_method,
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
            calibration_rmse=params_seed.calibration_rmse,
        )

        points: List[STIRFutureOptionSmilePoint] = []
        latest_quote = max(leg["pricer"].quote_timestamp() for leg in normalized_legs)
        for leg in normalized_legs:
            pr = leg["pricer"]
            strike_price = float(leg["strike_price"])
            strike_rate = 100.0 - float(strike_price)
            iv_normal_bps = float(pr.iv_normal_bps()) if math.isfinite(float(pr.iv_normal_bps())) else float(pr.iv_normal()) * 100.0
            market_price = _to_float(pr.price())
            discount_factor = _to_float(pr.discount())
            open_interest = self._pricer_open_interest(pr)
            volume = self._pricer_volume(pr)
            points.append(
                STIRFutureOptionSmilePoint(
                    label=str(leg["label"]),
                    right=str(leg["right"]),
                    delta_abs=float(leg["delta_abs"]),
                    atm_offset_bps=float(leg["atm_offset_bps"]),
                    strike_price=float(strike_price),
                    strike_rate=float(strike_rate),
                    iv_normal_price=float(pr.iv_normal()),
                    iv_normal_bps=float(iv_normal_bps),
                    market_price=float(market_price) if market_price is not None else None,
                    discount_factor=float(discount_factor) if discount_factor is not None else None,
                    open_interest=float(open_interest) if open_interest is not None else None,
                    volume=float(volume) if volume is not None else None,
                )
            )

        points = sorted(points, key=lambda pt: pt.strike_price)
        return self._normalize_stir_sabr_smile_convention(STIRFutureOptionSABRSmile(
            source=str(self.source),
            symbol=raw_symbol,
            underlying_contract=underlying_contract,
            quote_timestamp=latest_quote,
            params=params,
            points=tuple(points),
        ))

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

    def _build_sabr_smile_result(self, request: Dict[str, Any]) -> Tuple[STIRFutureOptionSABRSmile, Optional[str]]:
        raw_symbol, symbol_info, as_of, point_request, curve_name, curve_kwargs, force_refresh, show_tqdm, calibration_method = self._validate_sabr_smile_request(request)
        as_of_raw = request.get("as_of")
        as_of_live = isinstance(as_of_raw, str) and as_of_raw.strip().lower() == "live"
        mode = self._sabr_smile_point_mode(point_request)
        jpm_method = bool(request.get("jpm_method", False))
        selected_legs: List[Dict[str, Any]]

        if not as_of_live:
            # Fail fast and legibly on an expired chain, before ~100 EOD fetches produce
            # nothing.  Delta mode never resolves a contract otherwise.
            try:
                resolved_contract = self._resolve_sabr_smile_contract_unchecked(
                    symbol_info=symbol_info, as_of=as_of
                )
            except Exception:
                resolved_contract = ""
            if resolved_contract:
                self._assert_sabr_smile_chain_tradable(contract=resolved_contract, as_of=as_of)

        if str(self.source).upper() == "STIRFO_DUAL-QL":
            if jpm_method:
                raise ValueError("jpm_method SABR smiles require source='BARCHART_STIRFO-QL'")
            if mode == "delta":
                deltas = list(point_request["deltas"])
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
                selected_legs = self._selected_sabr_smile_legs_from_delta_map(
                    selected_pricers=selected,
                    labels_by_key=labels_by_key,
                )
            else:
                contract = self._resolve_sabr_smile_contract(symbol_info=symbol_info, as_of=as_of)
                _, forward = self._resolve_sabr_smile_underlying_forward(contract=contract, as_of=as_of, show_tqdm=show_tqdm)
                requested_legs = self._build_sabr_smile_offset_leg_specs(
                    contract=contract,
                    forward=float(forward),
                    as_of=as_of,
                    offset_magnitudes_bps=list(point_request.get("strike_offsets_bps") or []),
                    auto_full_ladder=bool(point_request.get("auto_full_ladder", False)),
                )
                qs_request = {
                    "endpoint": "qs_timeseries",
                    "start": as_of,
                    "end": as_of,
                    "queries": [
                        {
                            "globex_symbol": str(symbol_info["globex_symbol"]),
                            "qv_value_type": "VolByStrike",
                            "strike": float(spec["strike_price"]),
                            "option_type": "Call" if str(spec["right"]).upper() == "C" else "Put",
                        }
                        for spec in requested_legs
                    ],
                    "options": True,
                    "curve_name": curve_name,
                    "curve_kwargs": dict(curve_kwargs or {}),
                    "force_refresh": force_refresh,
                    "show_tqdm": show_tqdm,
                }
                pricers_by_series = self._qs_timeseries(qs_request)
                selected_legs = self._select_sabr_smile_qs_offset_legs(
                    pricers_by_series=pricers_by_series,
                    as_of=as_of,
                    requested_legs=requested_legs,
                )
        else:
            if mode == "delta" and not jpm_method:
                deltas = list(point_request["deltas"])
                snapshot_request = self._build_sabr_smile_snapshot_request(
                    request_symbol=str(symbol_info["request_symbol"]),
                    as_of="live" if as_of_live else as_of,
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
                selected_legs = self._selected_sabr_smile_legs_from_delta_map(
                    selected_pricers=selected,
                    labels_by_key=labels_by_key,
                )
            else:
                contract = self._resolve_sabr_smile_contract(symbol_info=symbol_info, as_of=as_of)
                price_mode = str(request.get("price_mode", "mid_then_fallback"))
                if jpm_method and as_of_live:
                    raise ValueError("jpm_method SABR smiles require a historical as_of date, not 'live'")
                if as_of_live:
                    _, forward = self._resolve_sabr_smile_live_underlying_forward(
                        contract=contract,
                        price_mode=price_mode,
                    )
                else:
                    _, forward = self._resolve_sabr_smile_underlying_forward(
                        contract=contract,
                        as_of=as_of,
                        show_tqdm=show_tqdm,
                        price_mode=price_mode,
                    )
                if jpm_method:
                    requested_legs = self._build_sabr_smile_jpm_leg_specs(
                        contract=contract,
                        forward=float(forward),
                        as_of=as_of,
                    )
                else:
                    requested_legs = self._build_sabr_smile_offset_leg_specs(
                        contract=contract,
                        forward=float(forward),
                        as_of=as_of,
                        offset_magnitudes_bps=list(point_request.get("strike_offsets_bps") or []),
                        auto_full_ladder=bool(point_request.get("auto_full_ladder", False)),
                    )
                if as_of_live:
                    snapshot_request = {
                        "endpoint": "option_snapshot",
                        "symbols": [str(spec["canonical_symbol"]) for spec in requested_legs],
                        "timestamp": "live",
                        "curve_name": curve_name,
                        "curve_kwargs": dict(curve_kwargs or {}),
                        "price_mode": price_mode,
                        "use_ql_calculator": True,
                        "force_refresh": force_refresh,
                        "show_tqdm": show_tqdm,
                    }
                    snapshot = self.get_data(snapshot_request)
                    selected_legs = self._select_sabr_smile_explicit_legs_from_snapshot(
                        requested_legs=requested_legs,
                        pricers_by_symbol=snapshot,
                        target_date=as_of,
                    )
                else:
                    cache_symbols = (
                        [f"__JPM_FULL__{contract}"]
                        if jpm_method
                        else [str(spec["canonical_symbol"]) for spec in requested_legs]
                    )
                    pricers_window = self._get_or_build_barchart_pricer_window(
                        leg_symbols=[str(spec["canonical_symbol"]) for spec in requested_legs],
                        cache_symbols=cache_symbols,
                        request_start=as_of,
                        request_end=as_of,
                        show_tqdm=show_tqdm,
                        price_mode=price_mode,
                        curve_name=curve_name,
                        curve_kwargs=curve_kwargs,
                        use_ql_calculator=True,
                        source="BARCHART_EOD_WINDOW",
                        force_refresh=force_refresh,
                    )
                    if jpm_method:
                        selected_legs = self._select_sabr_smile_available_legs_from_pricer_window(
                            requested_legs=requested_legs,
                            pricers_window=pricers_window,
                            target_date=as_of,
                        )
                        selected_legs = self._filter_sabr_smile_jpm_legs(
                            selected_legs,
                            open_interest_min=float(request.get("open_interest_min", 100.0)),
                        )
                    else:
                        selected_legs = self._select_sabr_smile_explicit_legs_from_pricer_window(
                            requested_legs=requested_legs,
                            pricers_window=pricers_window,
                            target_date=as_of,
                        )
        return self._finalize_sabr_smile_result(
            raw_symbol=raw_symbol,
            as_of=as_of,
            selected_legs=selected_legs,
            curve_name=curve_name,
            curve_kwargs=curve_kwargs,
            force_refresh=force_refresh,
            calibration_method=calibration_method,
            enable_common_cache=not as_of_live,
        )

    def _normalize_bulk_sabr_smile_request(
        self,
        request: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[datetime.date], Dict[str, Any], str, Dict[str, Any], bool, bool, str]:
        if "timestamps" not in request:
            raise ValueError("fetch_bulk_sabr_smile requires 'timestamps'")
        if "beta" in request:
            raise ValueError("sabr_smile fixes beta=0.5; request must not include 'beta'")

        timestamps_raw = request.get("timestamps")
        if isinstance(timestamps_raw, (str, datetime.date, datetime.datetime)):
            timestamp_items = [timestamps_raw]
        else:
            timestamp_items = list(timestamps_raw or [])
        if not timestamp_items:
            raise ValueError("timestamps is empty")

        dates: List[datetime.date] = []
        seen_dates: set[datetime.date] = set()
        for item in timestamp_items:
            if isinstance(item, str) and item.strip().lower() == "live":
                raise ValueError("fetch_bulk_sabr_smile does not support 'live' timestamps")
            dt = _as_date(item)
            if dt in seen_dates:
                continue
            seen_dates.add(dt)
            dates.append(dt)
        if not dates:
            raise ValueError("timestamps is empty")

        src = str(self.source).upper()
        input_symbols: List[str] = []
        if src == "STIRFO_DUAL-QL":
            if any(key in request for key in ("symbols", "symbol", "contract")):
                raise ValueError("fetch_bulk_sabr_smile for STIRFO_DUAL-QL requires 'globex_symbols' or 'globex_symbol'")
            raw_symbols = request.get("globex_symbols", request.get("globex_symbol"))
        elif src == "BARCHART_STIRFO-QL":
            if "globex_symbols" in request:
                raise ValueError("fetch_bulk_sabr_smile for BARCHART_STIRFO-QL requires 'symbols', 'symbol', or 'contract'")
            raw_symbols = []
            if "symbols" in request:
                symbols_val = request.get("symbols")
                if isinstance(symbols_val, str):
                    raw_symbols.append(symbols_val)
                else:
                    raw_symbols.extend(list(symbols_val or []))
            for key in ("symbol", "contract"):
                if key in request and request.get(key) is not None:
                    raw_symbols.append(request.get(key))
        else:
            raise NotImplementedError(
                f"SABR smile fetcher is only available for sources 'STIRFO_DUAL-QL' and 'BARCHART_STIRFO-QL', got {self.source!r}"
            )

        if isinstance(raw_symbols, str):
            raw_symbols = [raw_symbols]
        for sym in list(raw_symbols or []):
            token = str(sym).strip()
            if token:
                input_symbols.append(token)
        if not input_symbols:
            raise ValueError("fetch_bulk_sabr_smile requires at least one symbol")

        ordered_symbols = self._dedupe_preserve_order([str(sym).strip().upper() for sym in input_symbols if str(sym).strip()])
        if not ordered_symbols:
            raise ValueError("fetch_bulk_sabr_smile requires at least one symbol")

        base_req = dict(request)
        for key in ("timestamps", "globex_symbols", "globex_symbol", "symbols", "symbol", "contract", "endpoint", "max_workers"):
            base_req.pop(key, None)

        symbol_rows: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        point_request = self._normalize_sabr_smile_point_request(request)
        curve_name: Optional[str] = None
        curve_kwargs: Optional[Dict[str, Any]] = None
        force_refresh: Optional[bool] = None
        show_tqdm: Optional[bool] = None
        calibration_method: Optional[str] = None

        symbol_field = "globex_symbol" if src == "STIRFO_DUAL-QL" else "symbol"
        first_date = dates[0]
        for input_symbol in ordered_symbols:
            scalar_req = dict(base_req)
            scalar_req[symbol_field] = input_symbol
            scalar_req["as_of"] = first_date
            raw_symbol, symbol_info, _, deltas_i, curve_name_i, curve_kwargs_i, force_refresh_i, show_tqdm_i, calibration_method_i = self._validate_sabr_smile_request(
                scalar_req
            )

            for as_of in dates[1:]:
                probe_req = dict(base_req)
                probe_req[symbol_field] = input_symbol
                probe_req["as_of"] = as_of
                probe_raw_symbol, _, _, _, _, _, _, _, _ = self._validate_sabr_smile_request(probe_req)
                if probe_raw_symbol != raw_symbol:
                    raise ValueError(
                        f"Bulk SABR symbol normalization is not stable across dates for {input_symbol!r}: "
                        f"{raw_symbol!r} on {first_date.isoformat()} vs {probe_raw_symbol!r} on {as_of.isoformat()}"
                    )

            if curve_name is None:
                point_request = dict(deltas_i)
                curve_name = curve_name_i
                curve_kwargs = dict(curve_kwargs_i)
                force_refresh = bool(force_refresh_i)
                show_tqdm = bool(show_tqdm_i)
                calibration_method = str(calibration_method_i)

            row = symbol_rows.get(raw_symbol)
            if row is None:
                symbol_rows[raw_symbol] = {
                    "raw_symbol": raw_symbol,
                    "symbol_info": dict(symbol_info),
                    "input_symbols": [input_symbol],
                }
            else:
                row["input_symbols"] = self._dedupe_preserve_order(list(row.get("input_symbols") or []) + [input_symbol])

        return (
            list(symbol_rows.values()),
            dates,
            dict(point_request),
            str(curve_name or self._curve_name_default),
            dict(curve_kwargs or {}),
            bool(force_refresh),
            bool(show_tqdm),
            str(calibration_method or "nelder-mead"),
        )

    def _select_bulk_sabr_smile_qs_pricers(
        self,
        *,
        pricers_by_series: Dict[str, List[QLSTIRFutureOptionPricer]],
        misses: Sequence[Dict[str, Any]],
        deltas: Sequence[int],
        strict: bool = True,
    ) -> Tuple[
        Dict[Tuple[str, datetime.date], Dict[Tuple[str, int], QLSTIRFutureOptionPricer]],
        Dict[Tuple[str, datetime.date], Dict[Tuple[str, int], str]],
        List[Dict[str, Any]],
    ]:
        selected_by_request: Dict[Tuple[str, datetime.date], Dict[Tuple[str, int], QLSTIRFutureOptionPricer]] = {}
        labels_by_request: Dict[Tuple[str, datetime.date], Dict[Tuple[str, int], str]] = {}
        pricer_buckets: Dict[Tuple[str, datetime.date, str, int], QLSTIRFutureOptionPricer] = {}
        label_buckets: Dict[Tuple[str, datetime.date, str, int], str] = {}
        available_dates_by_symbol: Dict[str, set[datetime.date]] = defaultdict(set)
        unresolved: List[Dict[str, Any]] = []

        for series_name, plist in pricers_by_series.items():
            series_label = str(series_name)
            series_right = self._qs_right_from_label_and_query(label=series_label, query={})
            series_delta = self._qs_delta_abs_from_label_and_query(label=series_label, query={})
            for pr in plist:
                quote_day = pr.quote_timestamp().astimezone(_NY_TZ).date()
                meta = pr.meta() if callable(getattr(pr, "meta", None)) else {}
                qs_query = dict((meta or {}).get("qs_query") or {})
                label = str((meta or {}).get("qs_series_label", series_label))
                delta_raw = series_delta if series_delta is not None else self._qs_delta_abs_from_label_and_query(label=label, query=qs_query)
                right = series_right if series_right in {"C", "P"} else self._qs_right_from_label_and_query(label=label, query=qs_query)
                if delta_raw is None:
                    delta_raw = _to_float(qs_query.get("delta"))
                if delta_raw is None or right not in {"C", "P"}:
                    continue
                globex_symbol = str(qs_query.get("globex_symbol", "")).strip().upper()
                if not globex_symbol:
                    head = str(label).strip().upper().split(" ", 1)[0]
                    try:
                        globex_symbol = _normalize_qs_stir_globex_symbol(head)
                    except Exception:
                        globex_symbol = head
                if not globex_symbol:
                    continue

                key = (globex_symbol, quote_day, right, int(round(float(delta_raw))))
                available_dates_by_symbol[globex_symbol].add(quote_day)
                current = pricer_buckets.get(key)
                if current is None or pr.quote_timestamp() > current.quote_timestamp():
                    pricer_buckets[key] = pr
                    label_buckets[key] = label

        for miss in misses:
            request_key = (str(miss["raw_symbol"]), miss["as_of"])
            selected: Dict[Tuple[str, int], QLSTIRFutureOptionPricer] = {}
            labels: Dict[Tuple[str, int], str] = {}
            globex_symbol = str(miss["symbol_info"]["globex_symbol"]).strip().upper()
            missing: List[str] = []
            for delta in deltas:
                for right, side_label in (("C", "Call"), ("P", "Put")):
                    bucket_key = (globex_symbol, miss["as_of"], right, int(delta))
                    pr = pricer_buckets.get(bucket_key)
                    if pr is None:
                        missing.append(f"{int(delta)}D {side_label}")
                        continue
                    leg_key = (right, int(delta))
                    selected[leg_key] = pr
                    labels[leg_key] = label_buckets.get(bucket_key, str((pr.meta() or {}).get("qs_series_label", pr.symbol())))
            if missing:
                available_dates = ", ".join(sorted(d.isoformat() for d in available_dates_by_symbol.get(globex_symbol, set()))) or "none"
                if strict:
                    raise ValueError(
                        f"Missing SABR smile legs for {miss['raw_symbol']} on {miss['as_of'].isoformat()}: {missing}. "
                        f"Available quote dates: {available_dates}."
                    )
                unresolved.append(dict(miss, missing=missing, available_dates=available_dates))
                continue
            selected_by_request[request_key] = selected
            labels_by_request[request_key] = labels

        return selected_by_request, labels_by_request, unresolved

    def _select_bulk_sabr_smile_qs_offset_legs(
        self,
        *,
        pricers_by_series: Dict[str, List[QLSTIRFutureOptionPricer]],
        misses: Sequence[Dict[str, Any]],
        requested_legs_by_request: Dict[Tuple[str, datetime.date], List[Dict[str, Any]]],
        strict: bool = True,
    ) -> Tuple[
        Dict[Tuple[str, datetime.date], List[Dict[str, Any]]],
        List[Dict[str, Any]],
    ]:
        selected_by_request: Dict[Tuple[str, datetime.date], List[Dict[str, Any]]] = {}
        pricer_buckets: Dict[Tuple[str, datetime.date, str, float], QLSTIRFutureOptionPricer] = {}
        available_dates_by_symbol: Dict[str, set[datetime.date]] = defaultdict(set)
        unresolved: List[Dict[str, Any]] = []

        for series_name, plist in pricers_by_series.items():
            for pr in plist:
                quote_day = pr.quote_timestamp().astimezone(_NY_TZ).date()
                meta = pr.meta() if callable(getattr(pr, "meta", None)) else {}
                qs_query = dict((meta or {}).get("qs_query") or {})
                label = str((meta or {}).get("qs_series_label", series_name))
                right = self._qs_right_from_label_and_query(label=label, query=qs_query)
                strike_raw = _to_float(qs_query.get("strike"))
                if strike_raw is None or right not in {"C", "P"}:
                    continue
                globex_symbol = str(qs_query.get("globex_symbol", "")).strip().upper()
                if not globex_symbol:
                    head = str(label).strip().upper().split(" ", 1)[0]
                    try:
                        globex_symbol = _normalize_qs_stir_globex_symbol(head)
                    except Exception:
                        globex_symbol = head
                if not globex_symbol:
                    continue

                key = (globex_symbol, quote_day, right, round(float(strike_raw), 8))
                available_dates_by_symbol[globex_symbol].add(quote_day)
                current = pricer_buckets.get(key)
                if current is None or pr.quote_timestamp() > current.quote_timestamp():
                    pricer_buckets[key] = pr

        for miss in misses:
            request_key = (str(miss["raw_symbol"]), miss["as_of"])
            globex_symbol = str(miss["symbol_info"]["globex_symbol"]).strip().upper()
            requested_legs = list(requested_legs_by_request.get(request_key) or [])
            selected_legs: List[Dict[str, Any]] = []
            missing: List[str] = []
            for spec in requested_legs:
                right = str(spec["right"]).upper()
                strike = round(float(spec["strike_price"]), 8)
                pr = pricer_buckets.get((globex_symbol, miss["as_of"], right, strike))
                if pr is None:
                    missing.append(str(spec["canonical_symbol"]))
                    continue
                selected_legs.append(
                    self._build_sabr_smile_leg_selection(
                        label=str(spec["label"]),
                        right=right,
                        pricer=pr,
                        requested_delta_abs=None,
                        requested_atm_offset_bps=_to_float(spec.get("requested_atm_offset_bps")),
                        canonical_symbol=str(spec["canonical_symbol"]),
                    )
                )
            if missing:
                available_dates = ", ".join(sorted(d.isoformat() for d in available_dates_by_symbol.get(globex_symbol, set()))) or "none"
                if strict:
                    raise ValueError(
                        f"Missing SABR smile strike legs for {miss['raw_symbol']} on {miss['as_of'].isoformat()}: {missing}. "
                        f"Available quote dates: {available_dates}."
                    )
                unresolved.append(dict(miss, missing=missing, available_dates=available_dates))
                continue
            selected_by_request[request_key] = selected_legs

        return selected_by_request, unresolved

    def _build_bulk_sabr_smile_snapshot_context(
        self,
        *,
        symbol_rows: Sequence[Dict[str, Any]],
        dates: Sequence[datetime.date],
        point_request: Dict[str, Any],
        request: Dict[str, Any],
        curve_name: str,
        curve_kwargs: Dict[str, Any],
        show_tqdm: bool,
        force_refresh: bool,
    ) -> Dict[str, Any]:
        if not dates:
            raise ValueError("Bulk SABR smile context requires at least one date")
        window_start = min(dates)
        window_end = max(dates)
        start, end = self._historical_prefetch_window(start=window_start, end=window_end)
        price_mode = str(request.get("price_mode", "mid_then_fallback"))
        mode = self._sabr_smile_point_mode(point_request)
        request_symbols = [str(row["raw_symbol"]) for row in symbol_rows]

        if mode == "atm_offset_bps":
            contracts_by_request: Dict[Tuple[str, datetime.date], str] = {}
            underlying_symbols = sorted(
                {
                    _contract_to_barchart_contract(_option_contract_to_underlying_contract(self._resolve_sabr_smile_contract(symbol_info=row["symbol_info"], as_of=as_of)))
                    for row in symbol_rows
                    for as_of in dates
                }
            )
            underlying_data = self._fetch_barchart_eod_series(
                symbols=underlying_symbols,
                start=start,
                end=end,
                show_tqdm=show_tqdm,
            ) if underlying_symbols else {}

            requested_legs_by_request: Dict[Tuple[str, datetime.date], List[Dict[str, Any]]] = {}
            expanded_needed: "OrderedDict[str, str]" = OrderedDict()
            for row in symbol_rows:
                raw_symbol = str(row["raw_symbol"])
                symbol_info = dict(row["symbol_info"])
                for as_of in dates:
                    contract = self._resolve_sabr_smile_contract(symbol_info=symbol_info, as_of=as_of)
                    contracts_by_request[(raw_symbol, as_of)] = contract
                    forward = self._resolve_sabr_smile_forward_from_underlying_data(
                        contract=contract,
                        as_of=as_of,
                        underlying_data=underlying_data,
                        price_mode=price_mode,
                    )
                    requested_legs = self._build_sabr_smile_offset_leg_specs(
                        contract=contract,
                        forward=float(forward),
                        as_of=as_of,
                        offset_magnitudes_bps=list(point_request.get("strike_offsets_bps") or []),
                        auto_full_ladder=bool(point_request.get("auto_full_ladder", False)),
                    )
                    requested_legs_by_request[(raw_symbol, as_of)] = requested_legs
                    for spec in requested_legs:
                        expanded_needed[str(spec["canonical_symbol"])] = str(spec["canonical_symbol"])

            pricers_window = self._get_or_build_barchart_pricer_window(
                leg_symbols=list(expanded_needed.keys()),
                cache_symbols=list(expanded_needed.keys()),
                request_start=window_start,
                request_end=window_end,
                show_tqdm=show_tqdm,
                price_mode=price_mode,
                curve_name=curve_name,
                curve_kwargs=curve_kwargs,
                use_ql_calculator=True,
                source="BARCHART_EOD_WINDOW",
                force_refresh=force_refresh,
            ) if expanded_needed else {}

            return {
                "mode": mode,
                "price_mode": price_mode,
                "contracts_by_request": contracts_by_request,
                "underlying_data": underlying_data,
                "requested_legs_by_request": requested_legs_by_request,
                "pricers_window": pricers_window,
            }

        delta_candidate_half_width = max(2, int(request.get("delta_candidate_half_width", 8)))

        alias_symbols: List[str] = []
        alias_by_symbol: Dict[str, Dict[Tuple[str, int], str]] = {}
        parsed_requested_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for request_symbol in request_symbols:
            per_symbol: Dict[Tuple[str, int], str] = {}
            for delta in point_request["deltas"]:
                for right in ("C", "P"):
                    raw_alias = f"{request_symbol}|{int(delta)}D{right}"
                    alias_symbols.append(raw_alias)
                    per_symbol[(right, int(delta))] = raw_alias
                    parsed_requested_specs[raw_alias] = _parse_option_request_symbol(raw_alias)
            alias_by_symbol[request_symbol] = per_symbol

        contracts_by_raw: "OrderedDict[str, List[str]]" = OrderedDict()
        for raw, spec in parsed_requested_specs.items():
            contracts = self._contracts_for_spec_window(
                spec=spec,
                window_start=window_start,
                window_end=window_end,
            )
            contracts_by_raw[raw] = self._dedupe_preserve_order(contracts)

        underlying_contracts = sorted(
            {
                _option_contract_to_underlying_contract(contract)
                for contracts in contracts_by_raw.values()
                for contract in contracts
            }
        )
        contract_symbols_bc = sorted({_contract_to_barchart_contract(contract) for contract in underlying_contracts})
        underlying_data = self._fetch_barchart_eod_series(
            symbols=contract_symbols_bc,
            start=start,
            end=end,
            show_tqdm=show_tqdm,
        )

        chains: Optional[Dict[str, Dict[str, pd.DataFrame]]] = None

        def _ensure_delta_chains() -> Dict[str, Dict[str, pd.DataFrame]]:
            nonlocal chains
            if chains is not None:
                return chains

            option_contracts = sorted(
                {
                    _contract_to_barchart_contract(contract)
                    for contracts in contracts_by_raw.values()
                    for contract in contracts
                }
            )
            if not option_contracts:
                chains = {}
                return chains

            chain_concurrency = min(max(len(option_contracts), 1), 16)
            bcf = self._get_barchart_fetcher(required_concurrency=chain_concurrency)
            try:
                fetched = bcf.get_option_quotes(
                    symbols=option_contracts,
                    max_concurrent_tasks=chain_concurrency,
                    max_keepalive_connections=min(max(len(option_contracts), 1), 16),
                    show_tqdm=show_tqdm,
                )
            finally:
                try:
                    bcf.close()
                except Exception:
                    pass
            chains = fetched if isinstance(fetched, dict) else {}
            return chains

        delta_alias_meta: Dict[str, Dict[str, Any]] = {}
        expanded_needed: "OrderedDict[str, str]" = OrderedDict()
        for raw, spec in parsed_requested_specs.items():
            right = str(spec["right"]).upper()
            if right not in {"C", "P"}:
                raise ValueError(f"Historical delta alias supports call/put only: {raw!r}")
            target_delta = _to_float(spec.get("delta"))
            if target_delta is None:
                raise ValueError(f"Missing delta in historical alias spec: {raw!r}")

            candidate_symbols: List[str] = []
            for contract in contracts_by_raw.get(raw, []):
                underlying_contract = _option_contract_to_underlying_contract(contract)
                underlying_bcontract = _contract_to_barchart_contract(underlying_contract)
                fut_df = underlying_data.get(underlying_bcontract)
                if fut_df is None or fut_df.empty:
                    continue

                generated_from_rules = False
                for row_dt, row in fut_df.iterrows():
                    row_day = pd.Timestamp(row_dt).date()
                    if row_day < window_start or row_day > window_end:
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
                    continue
                side = "call" if right == "C" else "put"
                listed_strikes = self._live_chain_strikes(chain, side)
                if not listed_strikes:
                    continue

                for row_dt, row in fut_df.iterrows():
                    row_day = pd.Timestamp(row_dt).date()
                    if row_day < window_start or row_day > window_end:
                        continue
                    forward = _extract_row_price(row.to_dict(), price_mode=price_mode)
                    if forward is None or forward <= 0.0:
                        continue
                    strike_subset = self._pick_centered_strike_slice(
                        listed_strikes,
                        center=float(forward),
                        half_width=delta_candidate_half_width,
                    )
                    if strike_subset:
                        candidate_symbols.extend(
                            [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_subset]
                        )

            candidate_symbols = self._dedupe_preserve_order(candidate_symbols)
            if not candidate_symbols:
                raise ValueError(f"Could not resolve delta alias {raw!r}: no candidate strikes near forward.")

            delta_alias_meta[raw] = {
                "target_delta": float(target_delta),
                "right": right,
                "candidate_symbols": candidate_symbols,
            }
            for leg in candidate_symbols:
                expanded_needed[leg] = leg

        pricers_window = self._get_or_build_barchart_pricer_window(
            leg_symbols=list(expanded_needed.keys()),
            cache_symbols=["__BULK_TIMESERIES__"] + self._dedupe_preserve_order(alias_symbols),
            request_start=window_start,
            request_end=window_end,
            show_tqdm=show_tqdm,
            price_mode=price_mode,
            curve_name=curve_name,
            curve_kwargs=curve_kwargs,
            use_ql_calculator=True,
            source="BARCHART_EOD_WINDOW",
            force_refresh=force_refresh,
        ) if expanded_needed else {}

        return {
            "mode": mode,
            "price_mode": price_mode,
            "alias_by_symbol": alias_by_symbol,
            "parsed_requested_specs": parsed_requested_specs,
            "underlying_data": underlying_data,
            "delta_alias_meta": delta_alias_meta,
            "pricers_window": pricers_window,
        }

    def _select_bulk_sabr_smile_snapshot_pricers(
        self,
        *,
        context: Dict[str, Any],
        request_symbol: str,
        as_of: datetime.date,
    ) -> Tuple[
        Dict[Tuple[str, int], QLSTIRFutureOptionPricer],
        Dict[Tuple[str, int], str],
        Dict[str, List[QLSTIRFutureOptionPricer]],
    ]:
        alias_by_symbol = dict(context["alias_by_symbol"])
        parsed_requested_specs = dict(context["parsed_requested_specs"])
        underlying_data = dict(context["underlying_data"])
        delta_alias_meta = dict(context["delta_alias_meta"])
        pricers_window = dict(context["pricers_window"])
        price_mode = str(context["price_mode"])
        target_ts = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(as_of, datetime.time(17, 0))))

        selected: Dict[Tuple[str, int], QLSTIRFutureOptionPricer] = {}
        labels_by_key: Dict[Tuple[str, int], str] = {}
        seed_result: Dict[str, List[QLSTIRFutureOptionPricer]] = {}

        for key, raw_alias in alias_by_symbol.get(request_symbol, {}).items():
            resolved_spec = _resolve_option_contract_aliases_for_date(
                OrderedDict([(raw_alias, parsed_requested_specs[raw_alias])]),
                as_of=as_of,
            )[raw_alias]
            target_contract = str(resolved_spec["contract"])
            target_underlying_contract = _option_contract_to_underlying_contract(target_contract)
            target_underlying_bcontract = _contract_to_barchart_contract(target_underlying_contract)
            fut_df = underlying_data.get(target_underlying_bcontract)
            if fut_df is None or fut_df.empty:
                raise ValueError(
                    f"Could not resolve delta alias {raw_alias!r}: missing underlying history for {target_contract}."
                )
            target_pos = _asof_index_position(fut_df.index, target_ts)
            if target_pos is None:
                raise ValueError(
                    f"Could not resolve delta alias {raw_alias!r}: no underlying row near {as_of}."
                )
            target_forward = _extract_row_price(fut_df.iloc[target_pos].to_dict(), price_mode=price_mode)
            if target_forward is None or target_forward <= 0.0:
                raise ValueError(
                    f"Could not resolve delta alias {raw_alias!r}: invalid underlying forward."
                )

            meta = delta_alias_meta[raw_alias]
            resolved_leg = self._resolve_historical_delta_from_pricers(
                candidate_symbols=meta["candidate_symbols"],
                pricers_window=pricers_window,
                target_date=as_of,
                target_delta=float(meta["target_delta"]),
                right=str(meta["right"]),
                forward=float(target_forward),
            )
            if resolved_leg is None:
                raise ValueError(
                    f"Could not resolve delta alias {raw_alias!r}: no priced strikes available near {as_of} for {target_contract}."
                )
            pr = self._asof_pricer_for_date(pricers_window.get(resolved_leg, {}), as_of)
            if pr is None:
                raise ValueError(
                    f"Could not resolve delta alias {raw_alias!r}: missing pricer for resolved leg {resolved_leg!r} on {as_of}."
                )
            selected[key] = pr
            labels_by_key[key] = raw_alias
            seed_result[raw_alias] = [pr]

        missing: List[str] = []
        for delta in sorted({k[1] for k in alias_by_symbol.get(request_symbol, {}).keys()}):
            if ("C", int(delta)) not in selected:
                missing.append(f"{int(delta)}D Call")
            if ("P", int(delta)) not in selected:
                missing.append(f"{int(delta)}D Put")
        if missing:
            raise ValueError(f"Missing SABR smile legs for {request_symbol} on {as_of.isoformat()}: {missing}.")

        return selected, labels_by_key, seed_result

    def fetch_bulk_sabr_smile(self, request: Dict[str, Any]) -> Dict[str, Dict[datetime.date, STIRFutureOptionSABRSmile]]:
        req = dict(request)
        symbol_rows, dates, point_request, curve_name, curve_kwargs, force_refresh, show_tqdm, calibration_method = self._normalize_bulk_sabr_smile_request(req)
        src = str(self.source).upper()
        mode = self._sabr_smile_point_mode(point_request)
        base_req = dict(req)
        for key in ("timestamps", "globex_symbols", "globex_symbol", "symbols", "symbol", "contract", "endpoint", "max_workers"):
            base_req.pop(key, None)

        symbol_field = "globex_symbol" if src == "STIRFO_DUAL-QL" else "symbol"
        smiles_by_symbol: "OrderedDict[str, OrderedDict[datetime.date, STIRFutureOptionSABRSmile]]" = OrderedDict(
            (str(row["raw_symbol"]), OrderedDict()) for row in symbol_rows
        )
        misses: List[Dict[str, Any]] = []

        with self:
            for row in symbol_rows:
                raw_symbol = str(row["raw_symbol"])
                for as_of in dates:
                    scalar_req = dict(base_req)
                    scalar_req[symbol_field] = row["input_symbols"][0]
                    scalar_req["as_of"] = as_of
                    cache_key = self._build_get_data_cache_key("sabr_smile", scalar_req)
                    if cache_key and not force_refresh:
                        cached = self._threadsafe_cache_get(cache_key)
                        hit = self._deserialize_get_data_result(cached)
                        if hit is not None:
                            smiles = hit.get("sabr_smile") or []
                            if smiles:
                                smiles_by_symbol[raw_symbol][as_of] = smiles[0]
                                continue
                    misses.append(
                        {
                            "raw_symbol": raw_symbol,
                            "symbol_info": dict(row["symbol_info"]),
                            "input_symbols": list(row["input_symbols"]),
                            "as_of": as_of,
                            "scalar_request": scalar_req,
                            "cache_key": cache_key,
                        }
                    )

            if misses:
                selected_legs_by_request: Dict[Tuple[str, datetime.date], List[Dict[str, Any]]] = {}
                seed_results_by_request: Dict[Tuple[str, datetime.date], Dict[str, List[QLSTIRFutureOptionPricer]]] = {}
                if src == "STIRFO_DUAL-QL":
                    if mode == "delta":
                        deltas = list(point_request["deltas"])
                        queries: List[Dict[str, Any]] = []
                        seen_queries: set[Tuple[str, str, int]] = set()
                        for miss in misses:
                            globex_symbol = str(miss["symbol_info"]["globex_symbol"]).strip().upper()
                            for delta in deltas:
                                for qv_type, right in (("Call", "C"), ("Put", "P")):
                                    qkey = (globex_symbol, right, int(delta))
                                    if qkey in seen_queries:
                                        continue
                                    seen_queries.add(qkey)
                                    queries.append(
                                        {
                                            "globex_symbol": globex_symbol,
                                            "qv_value_type": qv_type,
                                            "delta": int(delta),
                                            "option_type": qv_type,
                                        }
                                    )
                        qs_request = {
                            "endpoint": "qs_timeseries",
                            "start": min(miss["as_of"] for miss in misses),
                            "end": max(miss["as_of"] for miss in misses),
                            "queries": queries,
                            "options": True,
                            "fresh_quikstrike_session_per_symbol": True,
                            "curve_name": curve_name,
                            "curve_kwargs": dict(curve_kwargs or {}),
                            "force_refresh": force_refresh,
                            "show_tqdm": show_tqdm,
                        }
                        pricers_by_series = self._qs_timeseries(qs_request)
                        selected_by_request, labels_by_request, unresolved = self._select_bulk_sabr_smile_qs_pricers(
                            pricers_by_series=pricers_by_series,
                            misses=misses,
                            deltas=deltas,
                            strict=(len({miss["as_of"] for miss in misses}) == 1),
                        )
                        if unresolved:
                            unresolved_by_date: "OrderedDict[datetime.date, List[Dict[str, Any]]]" = OrderedDict()
                            for miss in unresolved:
                                unresolved_by_date.setdefault(miss["as_of"], []).append(miss)

                            for fallback_date, fallback_misses in unresolved_by_date.items():
                                fallback_queries: List[Dict[str, Any]] = []
                                fallback_seen_queries: set[Tuple[str, str, int]] = set()
                                for miss in fallback_misses:
                                    globex_symbol = str(miss["symbol_info"]["globex_symbol"]).strip().upper()
                                    for delta in deltas:
                                        for qv_type, right in (("Call", "C"), ("Put", "P")):
                                            qkey = (globex_symbol, right, int(delta))
                                            if qkey in fallback_seen_queries:
                                                continue
                                            fallback_seen_queries.add(qkey)
                                            fallback_queries.append(
                                                {
                                                    "globex_symbol": globex_symbol,
                                                    "qv_value_type": qv_type,
                                                    "delta": int(delta),
                                                    "option_type": qv_type,
                                                }
                                            )

                                fallback_request = {
                                    "endpoint": "qs_timeseries",
                                    "start": fallback_date,
                                    "end": fallback_date,
                                    "queries": fallback_queries,
                                    "options": True,
                                    "fresh_quikstrike_session_per_symbol": True,
                                    "curve_name": curve_name,
                                    "curve_kwargs": dict(curve_kwargs or {}),
                                    "force_refresh": force_refresh,
                                    "show_tqdm": show_tqdm,
                                }
                                fallback_pricers_by_series = self._qs_timeseries(fallback_request)
                                fallback_selected, fallback_labels, _ = self._select_bulk_sabr_smile_qs_pricers(
                                    pricers_by_series=fallback_pricers_by_series,
                                    misses=fallback_misses,
                                    deltas=deltas,
                                    strict=True,
                                )
                                selected_by_request.update(fallback_selected)
                                labels_by_request.update(fallback_labels)

                        for miss in misses:
                            request_key = (str(miss["raw_symbol"]), miss["as_of"])
                            selected_legs_by_request[request_key] = self._selected_sabr_smile_legs_from_delta_map(
                                selected_pricers=selected_by_request[request_key],
                                labels_by_key=labels_by_request[request_key],
                            )
                    else:
                        price_mode = str(req.get("price_mode", "mid_then_fallback"))
                        start, end = self._historical_prefetch_window(
                            start=min(miss["as_of"] for miss in misses),
                            end=max(miss["as_of"] for miss in misses),
                        )
                        underlying_symbols = sorted(
                            {
                                _contract_to_barchart_contract(
                                    _option_contract_to_underlying_contract(
                                        self._resolve_sabr_smile_contract(symbol_info=miss["symbol_info"], as_of=miss["as_of"])
                                    )
                                )
                                for miss in misses
                            }
                        )
                        underlying_data = self._fetch_barchart_eod_series(
                            symbols=underlying_symbols,
                            start=start,
                            end=end,
                            show_tqdm=show_tqdm,
                        ) if underlying_symbols else {}
                        requested_legs_by_request: Dict[Tuple[str, datetime.date], List[Dict[str, Any]]] = {}
                        queries: List[Dict[str, Any]] = []
                        seen_queries: set[Tuple[str, str, float]] = set()
                        for miss in misses:
                            request_key = (str(miss["raw_symbol"]), miss["as_of"])
                            contract = self._resolve_sabr_smile_contract(symbol_info=miss["symbol_info"], as_of=miss["as_of"])
                            forward = self._resolve_sabr_smile_forward_from_underlying_data(
                                contract=contract,
                                as_of=miss["as_of"],
                                underlying_data=underlying_data,
                                price_mode=price_mode,
                            )
                            requested_legs = self._build_sabr_smile_offset_leg_specs(
                                contract=contract,
                                forward=float(forward),
                                as_of=miss["as_of"],
                                offset_magnitudes_bps=list(point_request.get("strike_offsets_bps") or []),
                                auto_full_ladder=bool(point_request.get("auto_full_ladder", False)),
                            )
                            requested_legs_by_request[request_key] = requested_legs
                            globex_symbol = str(miss["symbol_info"]["globex_symbol"]).strip().upper()
                            for spec in requested_legs:
                                qkey = (globex_symbol, str(spec["right"]).upper(), round(float(spec["strike_price"]), 8))
                                if qkey in seen_queries:
                                    continue
                                seen_queries.add(qkey)
                                queries.append(
                                    {
                                        "globex_symbol": globex_symbol,
                                        "qv_value_type": "VolByStrike",
                                        "strike": float(spec["strike_price"]),
                                        "option_type": "Call" if str(spec["right"]).upper() == "C" else "Put",
                                    }
                                )
                        qs_request = {
                            "endpoint": "qs_timeseries",
                            "start": min(miss["as_of"] for miss in misses),
                            "end": max(miss["as_of"] for miss in misses),
                            "queries": queries,
                            "options": True,
                            "fresh_quikstrike_session_per_symbol": True,
                            "curve_name": curve_name,
                            "curve_kwargs": dict(curve_kwargs or {}),
                            "force_refresh": force_refresh,
                            "show_tqdm": show_tqdm,
                        }
                        pricers_by_series = self._qs_timeseries(qs_request)
                        selected_legs_by_request, unresolved = self._select_bulk_sabr_smile_qs_offset_legs(
                            pricers_by_series=pricers_by_series,
                            misses=misses,
                            requested_legs_by_request=requested_legs_by_request,
                            strict=(len({miss["as_of"] for miss in misses}) == 1),
                        )
                        if unresolved:
                            unresolved_by_date: "OrderedDict[datetime.date, List[Dict[str, Any]]]" = OrderedDict()
                            for miss in unresolved:
                                unresolved_by_date.setdefault(miss["as_of"], []).append(miss)

                            for fallback_date, fallback_misses in unresolved_by_date.items():
                                fallback_queries: List[Dict[str, Any]] = []
                                fallback_seen_queries: set[Tuple[str, str, float]] = set()
                                for miss in fallback_misses:
                                    request_key = (str(miss["raw_symbol"]), miss["as_of"])
                                    globex_symbol = str(miss["symbol_info"]["globex_symbol"]).strip().upper()
                                    for spec in requested_legs_by_request[request_key]:
                                        qkey = (globex_symbol, str(spec["right"]).upper(), round(float(spec["strike_price"]), 8))
                                        if qkey in fallback_seen_queries:
                                            continue
                                        fallback_seen_queries.add(qkey)
                                        fallback_queries.append(
                                            {
                                                "globex_symbol": globex_symbol,
                                                "qv_value_type": "VolByStrike",
                                                "strike": float(spec["strike_price"]),
                                                "option_type": "Call" if str(spec["right"]).upper() == "C" else "Put",
                                            }
                                        )

                                fallback_request = {
                                    "endpoint": "qs_timeseries",
                                    "start": fallback_date,
                                    "end": fallback_date,
                                    "queries": fallback_queries,
                                    "options": True,
                                    "fresh_quikstrike_session_per_symbol": True,
                                    "curve_name": curve_name,
                                    "curve_kwargs": dict(curve_kwargs or {}),
                                    "force_refresh": force_refresh,
                                    "show_tqdm": show_tqdm,
                                }
                                fallback_pricers_by_series = self._qs_timeseries(fallback_request)
                                fallback_selected, _ = self._select_bulk_sabr_smile_qs_offset_legs(
                                    pricers_by_series=fallback_pricers_by_series,
                                    misses=fallback_misses,
                                    requested_legs_by_request=requested_legs_by_request,
                                    strict=True,
                                )
                                selected_legs_by_request.update(fallback_selected)
                else:
                    context = self._build_bulk_sabr_smile_snapshot_context(
                        symbol_rows=symbol_rows,
                        dates=dates,
                        point_request=point_request,
                        request=req,
                        curve_name=curve_name,
                        curve_kwargs=curve_kwargs,
                        show_tqdm=show_tqdm,
                        force_refresh=force_refresh,
                    )
                    seed_source_request: Dict[str, Any] = {}
                    if "curve_name" in req:
                        seed_source_request["curve_name"] = curve_name
                    if "curve_kwargs" in req:
                        seed_source_request["curve_kwargs"] = curve_kwargs

                    for miss in misses:
                        request_key = (str(miss["raw_symbol"]), miss["as_of"])
                        if mode == "delta":
                            selected, labels_by_key, seed_result = self._select_bulk_sabr_smile_snapshot_pricers(
                                context=context,
                                request_symbol=str(miss["raw_symbol"]),
                                as_of=miss["as_of"],
                            )
                            selected_legs_by_request[request_key] = self._selected_sabr_smile_legs_from_delta_map(
                                selected_pricers=selected,
                                labels_by_key=labels_by_key,
                            )
                            seed_results_by_request[request_key] = seed_result
                        else:
                            selected_legs_by_request[request_key] = self._select_sabr_smile_explicit_legs_from_pricer_window(
                                requested_legs=context["requested_legs_by_request"][request_key],
                                pricers_window=context["pricers_window"],
                                target_date=miss["as_of"],
                            )

                for miss in misses:
                    request_key = (str(miss["raw_symbol"]), miss["as_of"])
                    if request_key in seed_results_by_request:
                        seed_request: Dict[str, Any] = {
                            "endpoint": "option_snapshot",
                            "timestamp": miss["as_of"],
                            "use_ql_calculator": True,
                        }
                        if "curve_name" in seed_source_request:
                            seed_request["curve_name"] = curve_name
                        if "curve_kwargs" in seed_source_request:
                            seed_request["curve_kwargs"] = curve_kwargs
                        self._seed_option_snapshot_alias_cache(
                            request=seed_request,
                            result=seed_results_by_request[request_key],
                            source_request=seed_source_request,
                        )

                    smile, common_key = self._finalize_sabr_smile_result(
                        raw_symbol=str(miss["raw_symbol"]),
                        as_of=miss["as_of"],
                        selected_legs=selected_legs_by_request[request_key],
                        curve_name=curve_name,
                        curve_kwargs=curve_kwargs,
                        force_refresh=force_refresh,
                        calibration_method=calibration_method,
                    )
                    smiles_by_symbol[str(miss["raw_symbol"])][miss["as_of"]] = smile

                    cache_key = miss.get("cache_key")
                    if cache_key:
                        self._threadsafe_cache_put(
                            cache_key,
                            self._serialize_get_data_result("sabr_smile", {"sabr_smile": [smile]}),
                        )
                    if common_key and (force_refresh or self._threadsafe_cache_get(common_key) is None):
                        self._store_sabr_smile_common_cache(common_key=common_key, smile=smile)

        return {symbol: dict(by_date) for symbol, by_date in smiles_by_symbol.items()}

    def _serialize_sabr_smile(self, smile: STIRFutureOptionSABRSmile) -> Dict[str, Any]:
        return smile.to_dict()

    def _deserialize_sabr_smile(self, row: Dict[str, Any]) -> STIRFutureOptionSABRSmile:
        return self._normalize_stir_sabr_smile_convention(STIRFutureOptionSABRSmile.from_dict(row))

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
                return None
            else:
                as_of_for_symbols = _as_date(ts)
                cache_req["timestamp"] = as_of_for_symbols
            for _drop in ("bulk_timeseries", "use_ql_calculator", "window_start",
                          "window_end", "endpoint", "window_minutes",
                          "delta_candidate_half_width", "delta_vendor_candidate_half_width"):
                cache_req.pop(_drop, None)

        if ep == "option_timeseries":
            if "start" in cache_req:
                cache_req["start"] = _as_date(cache_req["start"])
            if "end" in cache_req:
                cache_req["end"] = _as_date(cache_req["end"])
            as_of_for_symbols = cache_req.get("start")

        if ep == "sabr_smile":
            raw_as_of = cache_req.get("as_of")
            if isinstance(raw_as_of, str) and raw_as_of.strip().lower() == "live":
                return None
            if "as_of" in cache_req:
                cache_req["as_of"] = _as_date(cache_req["as_of"])
            cache_req["calibration_method"] = str(cache_req.get("calibration_method", "nelder-mead")).strip().lower().replace("_", "-")
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
            point_request = self._normalize_sabr_smile_point_request(cache_req)
            cache_req["point_request"] = self._cache_primitive(point_request)
            cache_req.pop("deltas", None)
            cache_req.pop("strike_offsets_bps", None)

        if symbols_raw:
            cache_req["symbol_specs"] = self._normalize_symbols_for_cache(symbols=symbols_raw, as_of=as_of_for_symbols)
        cache_req.pop("symbols", None)
        cache_req.pop("tickers", None)

        payload = {
            "schema": 1,
            "cache_version": "stirfo_get_data_v9",
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
                bcf = BarchartFetcher(
                    proxies=self._barchart_proxies_static,
                    debug_verbose=False,
                    error_verbose=True,
                    session_token_ttl_seconds=max(1, int(self._barchart_proxy_ttl)),
                    session_token_pool_size=desired_pool_size,
                    session_token_scope=f"{self.__class__.__name__}:static",
                )
                try:
                    bcf._fetch_session_tokens(dummy_symbol="BTC")
                except Exception:
                    pass
                return bcf

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
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()

            bcf = _build_fetcher(proxies, host)
            try:
                bcf._fetch_session_tokens(dummy_symbol="BTC")
            except Exception:
                _safe_close(bcf)
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                bcf = _build_fetcher(proxies, host)
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

    def _run_eod_fetch_single(
        self,
        symbols: List[str],
        start_dt: datetime.datetime,
        end_dt: datetime.datetime,
        show_tqdm: bool,
        mc: int,
        mk: int,
        mr: int,
    ) -> Dict[str, pd.DataFrame]:
        """Single-proxy EOD fetch: build a fetcher on the rotating sticky proxy, fetch, close."""
        if not symbols:
            return {}
        bcf = self._get_barchart_fetcher(required_concurrency=mc)
        try:
            out = bcf.barchart_timeseries_api(
                barchart_symbols=symbols,
                start_date=start_dt,
                end_date=end_dt,
                interval=None,
                one_df=False,
                show_tqdm=show_tqdm,
                max_concurrent_tasks=mc,
                max_keepalive_connections=mk,
                max_requests_per_second=mr,
            )
        finally:
            try:
                bcf.close()
            except Exception:
                pass
        return out if isinstance(out, dict) else {}

    def _build_barchart_fetcher_for_host(
        self,
        proxies: Optional[dict],
        host: Optional[str],
        required_concurrency: Optional[int],
        *,
        proxy_auth_retries: int = 1,
        warm: bool = True,
    ) -> BarchartFetcher:
        """Build a fetcher bound to one specific proxy host (own per-host token scope).

        ``proxy_auth_retries=0`` makes a flaky proxy raise instantly instead of sleeping
        60s. With ``warm=True`` a token-warm failure propagates so the caller can drop a
        dead proxy up front (used by the fan-out workers).
        """
        desired_pool_size = self._bounded_session_token_pool_size(required_concurrency)
        scope_host = host if host is not None else "direct"
        bcf = BarchartFetcher(
            proxies=proxies,
            debug_verbose=False,
            error_verbose=True,
            session_token_ttl_seconds=max(1, int(self._barchart_proxy_ttl)),
            session_token_pool_size=desired_pool_size,
            session_token_scope=f"{self.__class__.__name__}:{scope_host}",
            proxy_auth_retries=proxy_auth_retries,
        )
        if warm:
            bcf._fetch_session_tokens(dummy_symbol="BTC")
        return bcf

    def _record_fanout_proxy_failure(self, host: Optional[str]) -> None:
        """Demote a proxy a worker had to evict: a host can pass preflight yet fail barchart
        data requests (degraded), so feed that signal back and drop it from the cached set
        so the next selection skips it for the cooldown window."""
        if host is None:
            return
        S = STIRFutureOptionMDP._BARCHART_STATE
        now = time.time()
        with S["lock"]:
            health = S.get("proxy_health")
            if not isinstance(health, dict):
                health = {}
                S["proxy_health"] = health
            health[host] = now
            cached = S.get("fanout")
            if isinstance(cached, list):
                S["fanout"] = [(p, h) for (p, h) in cached if h != host]

    def _choose_fanout_proxies(self, k: int) -> List[Tuple[Optional[dict], Optional[str]]]:
        """Return up to k distinct, preflighted-live (proxies, host) pairs (TTL-cached).

        Hosts a worker recently evicted are demoted for ``_barchart_fanout_proxy_cooldown``
        seconds (they pass preflight but fail data requests), unless skipping them would
        leave too few candidates."""
        S = STIRFutureOptionMDP._BARCHART_STATE
        now = time.time()
        with S["lock"]:
            cached = S.get("fanout")
            chosen_at = float(S.get("fanout_chosen_at", 0.0) or 0.0)
            if cached and (now - chosen_at) < float(S["ttl"]):
                return list(cached)[:k]
            health = dict(S.get("proxy_health") or {})

        if not self._socksio_enabled:
            return [(None, None)]

        all_hosts = [h for h in self._barchart_proxy_hosts if h is not None]
        cooldown = float(self._barchart_fanout_proxy_cooldown)
        healthy = [h for h in all_hosts if (now - float(health.get(h, 0.0) or 0.0)) >= cooldown]
        # Keep at least a couple of candidates even if most are in cooldown.
        candidate_hosts = healthy if len(healthy) >= 2 else all_hosts

        def _try(host: str) -> Optional[Tuple[dict, str]]:
            try:
                proxies = _build_socks5h(host)
            except Exception:
                return None
            return (proxies, host) if _preflight_proxy(proxies) else None

        live: List[Tuple[Optional[dict], Optional[str]]] = []
        if candidate_hosts:
            with ThreadPoolExecutor(max_workers=min(len(candidate_hosts), 12), thread_name_prefix="stirfo-preflight") as ex:
                for res in ex.map(_try, candidate_hosts):
                    if res is not None:
                        live.append(res)
        if not live:
            live = [(None, None)]

        with S["lock"]:
            S["fanout"] = list(live)
            S["fanout_chosen_at"] = time.time()
        return live[:k]

    def _fanout_should_engage(self, n_symbols: int) -> bool:
        """Fan out only when enabled, proxies are available, and there are enough symbols
        to make at least two worthwhile workers."""
        if not self._barchart_fanout_enabled or not self._socksio_enabled:
            return False
        min_per = max(1, int(self._barchart_fanout_min_symbols_per_shard))
        return n_symbols >= 2 * min_per

    def _run_eod_fetch(
        self,
        symbols: List[str],
        start_dt: datetime.datetime,
        end_dt: datetime.datetime,
        show_tqdm: bool,
        mc: int,
        mk: int,
        mr: int,
    ) -> Dict[str, pd.DataFrame]:
        """EOD network-fetch chokepoint. Uses the hardened work-stealing fan-out when
        enabled and worthwhile, otherwise the single-proxy path. The raw-frame cache
        routes here."""
        if not symbols:
            return {}
        symbols = list(symbols)
        if not self._fanout_should_engage(len(symbols)):
            return self._run_eod_fetch_single(symbols, start_dt, end_dt, show_tqdm, mc, mk, mr)
        return self._run_eod_fetch_fanout(symbols, start_dt, end_dt, mc, mk, mr)

    def _run_eod_fetch_fanout(
        self,
        symbols: List[str],
        start_dt: datetime.datetime,
        end_dt: datetime.datetime,
        mc: int,
        mk: int,
        mr: int,
    ) -> Dict[str, pd.DataFrame]:
        """Work-stealing fan-out: one shared batch queue drained by per-proxy workers.

        Fast proxies pull more batches, slow ones fewer. A flaky proxy fails fast (no 60s
        stall via proxy_auth_retries=0), self-evicts after repeated failures, and its
        in-flight batch is requeued for a healthier worker. A batch that comes back
        empty/erroring is retried on another worker, then handed to the reliable
        single-proxy fallback -- so no symbol is dropped and the slowest proxy can never
        gate the whole job.
        """
        n = len(symbols)
        min_per = max(1, int(self._barchart_fanout_min_symbols_per_shard))
        desired = min(max(1, int(self._barchart_fanout_max_shards)), max(1, n // min_per))
        proxies = [(p, h) for (p, h) in self._choose_fanout_proxies(desired) if h is not None]
        if len(proxies) < 2:
            return self._run_eod_fetch_single(symbols, start_dt, end_dt, False, mc, mk, mr)

        batch_size = max(1, int(self._barchart_fanout_batch_size))
        max_attempts = max(1, int(self._barchart_fanout_max_batch_attempts))
        evict_after = max(1, int(self._barchart_fanout_evict_after))
        log = logging.getLogger(self.__class__.__name__)

        work: "queue.Queue" = queue.Queue()
        for i in range(0, n, batch_size):
            work.put((symbols[i:i + batch_size], 0))

        results: Dict[str, pd.DataFrame] = {}
        results_lock = threading.Lock()

        def _worker(worker_proxies: Optional[dict], worker_host: Optional[str]) -> None:
            try:
                fetcher = self._build_barchart_fetcher_for_host(
                    worker_proxies, worker_host, mc, proxy_auth_retries=0, warm=True
                )
            except Exception as exc:
                # Dead proxy: never starts a worker; its share stays queued for the others.
                log.warning("Barchart fan-out worker %s did not start: %s", worker_host, exc)
                return
            consecutive_failures = 0
            try:
                while True:
                    try:
                        batch, attempt = work.get_nowait()
                    except queue.Empty:
                        break
                    got_data = False
                    try:
                        out = fetcher.barchart_timeseries_api(
                            barchart_symbols=batch,
                            start_date=start_dt,
                            end_date=end_dt,
                            interval=None,
                            one_df=False,
                            show_tqdm=False,
                            max_concurrent_tasks=max(1, min(mc, len(batch))),
                            max_keepalive_connections=mk,
                            max_requests_per_second=mr,
                            eod_max_retries=self._barchart_fanout_eod_max_retries,
                            eod_backoff_factor=self._barchart_fanout_eod_backoff,
                        )
                        if isinstance(out, dict) and any(v is not None for v in out.values()):
                            with results_lock:
                                results.update(out)
                            got_data = True
                    except Exception as exc:
                        log.debug("Barchart fan-out batch error on %s: %s", worker_host, exc)

                    if got_data:
                        consecutive_failures = 0
                        continue
                    # Empty/erroring batch: a flaky proxy surfaces as all-None here (per-symbol
                    # errors are swallowed downstream), so treat it as a failure and requeue.
                    consecutive_failures += 1
                    if attempt + 1 < max_attempts:
                        work.put((batch, attempt + 1))  # let a healthier worker retry
                    # else: drop from the queue -- the missing-symbol sweep below recovers it
                    if consecutive_failures >= evict_after:
                        log.warning("Barchart fan-out evicting flaky proxy %s", worker_host)
                        self._record_fanout_proxy_failure(worker_host)
                        break
            finally:
                try:
                    fetcher.close()
                except Exception:
                    pass

        threads = [
            threading.Thread(target=_worker, args=(p, h), name=f"stirfo-fanout-{h}", daemon=True)
            for (p, h) in proxies
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Completeness backstop: any requested symbol that did NOT come back with data is
        # recovered on the reliable single-proxy path (full retry budget). This covers a
        # failed/dropped batch, a batch left unqueued by an evicted worker, AND a symbol that
        # returned None inside an otherwise-successful batch (a transient per-symbol hiccup).
        # Guarantees fan-out is at least as complete as the single-proxy path.
        with results_lock:
            have_data = {k for k, v in results.items() if v is not None}
        missing = [s for s in symbols if BarchartFetcher._normalize_barchart_symbol(s) not in have_data]
        if missing:
            log.info("Barchart fan-out: recovering %d symbol(s) via reliable single-proxy path", len(missing))
            fallback = self._run_eod_fetch_single(missing, start_dt, end_dt, False, mc, mk, mr)
            with results_lock:
                results.update(fallback)
        return results

    # ---- raw per-symbol EOD frame cache -------------------------------------

    def _raw_eod_disk(self) -> Any:
        cache = self._raw_eod_disk_cache
        if cache is None:
            with self._raw_eod_lock:
                if self._raw_eod_disk_cache is None:
                    path = LayeredCacheMixin.default_cache_path(self._RAW_EOD_CACHE_STEM)
                    # L1 diskcache only (no Supabase L2 wrapper): full-history EOD frames
                    # are large and immutable -- local disk, never remote prod KV.
                    # _acquire_cache is an inherited DiskCacheMixin classmethod and returns a
                    # raw FanoutCache (L2 is only added in open_cache, which we deliberately skip).
                    self._raw_eod_disk_cache = LayeredCacheMixin._acquire_cache(path)
                cache = self._raw_eod_disk_cache
        return cache

    @staticmethod
    def _raw_eod_disk_key(symbol: str) -> str:
        return f"rawEOD::v1::{symbol}"

    def _raw_eod_cache_get(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._raw_eod_lock:
            ent = self._raw_eod_mem.get(symbol)
        if ent is not None:
            return ent
        try:
            ent = self._raw_eod_disk().get(self._raw_eod_disk_key(symbol))
        except Exception:
            ent = None
        if isinstance(ent, dict):
            with self._raw_eod_lock:
                self._raw_eod_mem[symbol] = ent
            return ent
        return None

    def _raw_eod_cache_put(self, symbol: str, frame: Optional[pd.DataFrame], fetched_at: float) -> None:
        max_date = min_date = None
        if frame is not None and len(frame) and isinstance(frame.index, pd.DatetimeIndex):
            max_date = pd.Timestamp(frame.index.max()).date()
            min_date = pd.Timestamp(frame.index.min()).date()
        ent = {"frame": frame, "fetched_at": float(fetched_at), "min_date": min_date, "max_date": max_date}
        with self._raw_eod_lock:
            self._raw_eod_mem[symbol] = ent
        try:
            self._raw_eod_disk()[self._raw_eod_disk_key(symbol)] = ent
        except Exception:
            pass

    def _raw_eod_cache_covers(self, ent: Dict[str, Any], start: datetime.date, end: datetime.date) -> bool:
        fetched_at = float(ent.get("fetched_at", 0.0) or 0.0)
        if fetched_at <= 0.0:
            return False
        fetched_date = datetime.datetime.fromtimestamp(fetched_at, tz=_NY_TZ).date()
        # Window ends strictly before the day we fetched -> historical & immutable: the
        # full-history snapshot we stored already contains everything this window can have.
        if end < fetched_date:
            return True
        # Window reaches the fetch day / today -> only trust a fetch within the TTL so the
        # still-settling current bar stays live.
        return (time.time() - fetched_at) < float(self._raw_eod_ttl_seconds)

    @staticmethod
    def _slice_eod_frame(
        frame: Optional[pd.DataFrame],
        start: datetime.date,
        end: datetime.date,
    ) -> Optional[pd.DataFrame]:
        if frame is None:
            return None
        if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
            return frame
        lo = pd.Timestamp(datetime.datetime.combine(start, datetime.time(0, 0)))
        hi = pd.Timestamp(datetime.datetime.combine(end, datetime.time(23, 59)))
        return frame[(frame.index >= lo) & (frame.index <= hi)]

    def _fetch_barchart_eod_series(
        self,
        *,
        symbols: List[str],
        start: datetime.date,
        end: datetime.date,
        show_tqdm: bool,
        max_concurrent_tasks: Optional[int] = None,
        max_keepalive_connections: Optional[int] = None,
        max_requests_per_second: Optional[int] = None,
        force_refresh: bool = False,
    ) -> Dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        mc = int(max_concurrent_tasks or min(max(len(symbols), 1), 6))
        mk = int(max_keepalive_connections or mc)
        mr = int(max_requests_per_second or min(mc, 4))

        if not self._raw_eod_cache_enabled:
            start_dt = datetime.datetime.combine(start, datetime.time(0, 0))
            end_dt = datetime.datetime.combine(end, datetime.time(23, 59))
            return self._run_eod_fetch(list(symbols), start_dt, end_dt, show_tqdm, mc, mk, mr)

        # Normalize to the keys barchart_timeseries_api would emit, de-duped, order-preserved.
        norm: List[str] = []
        seen: set = set()
        for s in symbols:
            n = BarchartFetcher._normalize_barchart_symbol(s)
            if n not in seen:
                seen.add(n)
                norm.append(n)

        result: Dict[str, pd.DataFrame] = {}
        to_fetch: List[str] = []
        for n in norm:
            ent = None if force_refresh else self._raw_eod_cache_get(n)
            if ent is not None and self._raw_eod_cache_covers(ent, start, end):
                result[n] = self._slice_eod_frame(ent.get("frame"), start, end)
            else:
                to_fetch.append(n)

        if to_fetch:
            # Fetch full history once (wide window -> client-side filter keeps it all), cache
            # it, then slice locally. Every later window for these symbols hits the cache.
            today = datetime.date.today()
            wide_start = datetime.datetime(1990, 1, 1)
            wide_end = datetime.datetime(today.year + 1, 12, 31, 23, 59)
            fetched_full = self._run_eod_fetch(to_fetch, wide_start, wide_end, show_tqdm, mc, mk, mr)
            now = time.time()
            for n in to_fetch:
                # Mirror the raw passthrough: only surface symbols the fetch returned
                # (downstream uses dict.get(), so absent == None either way).
                if n not in fetched_full:
                    continue
                frame = fetched_full.get(n)
                if frame is not None:
                    self._raw_eod_cache_put(n, frame, now)
                result[n] = self._slice_eod_frame(frame, start, end)

        return result

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
        try:
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
        finally:
            try:
                bcf.close()
            except Exception:
                pass
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
        force_refresh: bool = False,
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

        if not force_refresh:
            cached = self._threadsafe_cache_get(cache_key)
            hit = self._deserialize_pricer_window(cached)
            # `if hit` rather than `is not None`: an empty entry left behind by an older
            # build (or a failed fetch) must not short-circuit the refetch.
            if hit:
                return hit

        option_symbols_bc = sorted({_canonical_to_barchart_option(sym) for sym in leg_symbols})
        contracts = sorted({_contract_to_barchart_contract(_canonical_underlying(sym)) for sym in leg_symbols})
        all_syms = option_symbols_bc + contracts
        data = self._fetch_barchart_eod_series(
            symbols=all_syms,
            start=window_start,
            end=window_end,
            show_tqdm=show_tqdm,
            force_refresh=force_refresh,
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
        # Never persist an empty window.  An empty payload deserializes to {} (not None),
        # so caching one turns a transient Barchart outage into a permanent "no data"
        # answer that only force_refresh can clear.
        if built:
            self._threadsafe_cache_put(cache_key, self._serialize_pricer_window(built))
        return built

    @staticmethod
    def _asof_pricer_for_date(
        by_day: Dict[datetime.date, QLSTIRFutureOptionPricer],
        target_date: datetime.date,
        max_staleness_days: Optional[int] = None,
    ) -> Optional[QLSTIRFutureOptionPricer]:
        """Latest pricer on or before ``target_date``.

        EOD windows are prefetched +/- a calendar month around the request, so an
        unbounded lookback happily returns a quote from weeks earlier.  Pass
        ``max_staleness_days`` to reject anything older than that.
        """
        if not by_day:
            return None
        keys = [d for d in by_day.keys() if d <= target_date]
        if not keys:
            return None
        best = max(keys)
        if max_staleness_days is not None and (target_date - best).days > int(max_staleness_days):
            return None
        return by_day[best]

    def _fetch_schwab_quotes(self, *, symbols: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        req_symbols = self._dedupe_preserve_order([str(sym).strip() for sym in symbols if str(sym).strip()])
        if not req_symbols:
            return {}

        quote_kwargs: Dict[str, Any] = {"symbols": req_symbols}
        if self._schwab_app_key and self._schwab_app_secret:
            quote_kwargs["app_key"] = self._schwab_app_key
            quote_kwargs["app_secret"] = self._schwab_app_secret
            quote_kwargs["scope"] = self._schwab_scope

        quotes = schwab_get_quotes(**quote_kwargs)
        return dict(quotes) if isinstance(quotes, dict) else {}

    @staticmethod
    def _lookup_schwab_quote(quotes: Dict[str, Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
        raw = str(symbol or "").strip()
        if not raw:
            return None
        if isinstance(quotes.get(raw), dict):
            return dict(quotes[raw])
        upper = raw.upper()
        if isinstance(quotes.get(upper), dict):
            return dict(quotes[upper])
        return None

    @staticmethod
    def _quote_time_to_dt(quote_time: Any, fallback: datetime.datetime) -> datetime.datetime:
        qt = _to_float(quote_time)
        if qt is None or qt <= 0.0:
            return fallback
        try:
            return pd.to_datetime(int(qt), unit="ms", utc=True).to_pydatetime()
        except Exception:
            return fallback

    @staticmethod
    def _resolve_live_atm_strike_from_grid(
        *,
        contract: str,
        forward: float,
        valuation_date: datetime.date,
    ) -> Optional[float]:
        grid = _cme_listed_strike_grid_for_contract_forward(
            contract=contract,
            forward=float(forward),
            as_of=valuation_date,
        )
        if grid is not None:
            return float(grid["atm_strike"])
        try:
            return float(_atm_strike_from_forward(float(forward), step=_strike_step_for_contract(contract)))
        except Exception:
            return None

    def _fetch_schwab_live_underlying_forwards(
        self,
        *,
        contracts: Sequence[str],
        price_mode: str,
    ) -> Dict[str, float]:
        contract_symbols = {str(contract): _contract_to_schwab_future_symbol(str(contract)) for contract in contracts}
        quotes = self._fetch_schwab_quotes(symbols=list(contract_symbols.values()))
        out: Dict[str, float] = {}
        for contract, schwab_symbol in contract_symbols.items():
            q = self._lookup_schwab_quote(quotes, schwab_symbol)
            if not q:
                continue
            price = _extract_row_price(q, price_mode=price_mode)
            if price is not None and price > 0.0:
                out[contract] = float(price)
        return out

    def _build_schwab_live_option_chains(
        self,
        *,
        canonical_symbols: Sequence[str],
    ) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, Dict[str, Any]]]:
        explicit_symbols: List[str] = []
        quote_symbols: Dict[str, str] = {}
        for sym in canonical_symbols:
            token = _norm_option_symbol(sym)
            if _right_from_symbol(token) not in {"C", "P"}:
                continue
            explicit_symbols.append(token)
            quote_symbols[token] = _canonical_to_schwab_option_symbol(token)

        if not quote_symbols:
            return {}, {}

        quotes = self._fetch_schwab_quotes(symbols=list(quote_symbols.values()))
        rows_by_symbol: Dict[str, Dict[str, Any]] = {}
        rows_by_contract: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for canonical_symbol in self._dedupe_preserve_order(explicit_symbols):
            schwab_symbol = quote_symbols[canonical_symbol]
            q = self._lookup_schwab_quote(quotes, schwab_symbol)
            if not q:
                continue

            contract = _canonical_contract(canonical_symbol)
            right = _right_from_symbol(canonical_symbol)
            side = "call" if right == "C" else "put"
            row = {
                "symbol": canonical_symbol,
                "schwabSymbol": schwab_symbol,
                "strikePrice": float(_strike_from_symbol(canonical_symbol)),
                "bid": _to_float(q.get("bid")),
                "ask": _to_float(q.get("ask")),
                "mid": _to_float(q.get("mid")),
                "last": _to_float(q.get("last")),
                "mark": _to_float(q.get("mark")),
                "bidSize": _to_float(q.get("bidSize")),
                "askSize": _to_float(q.get("askSize")),
                "netChange": _to_float(q.get("netChange")),
                "quoteTime": _to_float(q.get("quoteTime")),
                "rawQuote": dict(q),
            }
            rows_by_symbol[canonical_symbol] = dict(row)
            bucket = rows_by_contract.setdefault(contract, {"call": [], "put": []})
            bucket[side].append(dict(row))

        chains: Dict[str, Dict[str, pd.DataFrame]] = {}
        for contract, side_rows in rows_by_contract.items():
            chains[contract] = {
                "call": pd.DataFrame(side_rows["call"]),
                "put": pd.DataFrame(side_rows["put"]),
            }
        return chains, rows_by_symbol

    def _option_snapshot_live_schwab(
        self,
        *,
        requested_specs: "OrderedDict[str, Dict[str, Any]]",
        valuation_ts: datetime.datetime,
        curve_name: str,
        curve_kwargs: Optional[Dict[str, Any]],
        price_mode: str,
        use_ql_calculator: bool,
        delta_ignore_deep_itm: bool,
    ) -> Tuple["OrderedDict[str, str]", Dict[str, QLSTIRFutureOptionPricer]]:
        valuation_date = valuation_ts.astimezone(_NY_TZ).date()
        curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]] = {}
        cp_pricers: Dict[str, QLSTIRFutureOptionPricer] = {}

        underlying_contracts = sorted(
            {
                _option_contract_to_underlying_contract(str(spec["contract"]))
                for spec in requested_specs.values()
            }
        )
        forward_map = self._fetch_schwab_live_underlying_forwards(
            contracts=underlying_contracts,
            price_mode=price_mode,
        )

        non_delta_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        delta_specs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for raw, spec in requested_specs.items():
            if str(spec.get("selector")) == "delta":
                delta_specs[raw] = spec
            else:
                non_delta_specs[raw] = spec

        resolved_non_delta: "OrderedDict[str, str]" = OrderedDict()
        quote_universe: "OrderedDict[str, str]" = OrderedDict()
        for raw, spec in non_delta_specs.items():
            selector = str(spec["selector"])
            contract = str(spec["contract"])
            right = str(spec["right"]).upper()

            if selector == "strike":
                resolved_symbol = str(spec["canonical"])
            else:
                underlying_contract = _option_contract_to_underlying_contract(contract)
                forward = _to_float(forward_map.get(underlying_contract))
                if forward is None or forward <= 0.0:
                    raise ValueError(f"Could not resolve alias {raw!r}: missing Schwab live forward for {contract}")

                if selector == "atm":
                    strike = self._resolve_live_atm_strike_from_grid(
                        contract=contract,
                        forward=float(forward),
                        valuation_date=valuation_date,
                    )
                    if strike is None:
                        raise ValueError(f"Could not resolve ATM alias {raw!r}: no listed strike rule for {contract}")
                    resolved_symbol = f"{contract}|{_format_strike4(strike, contract=contract)}{right}"
                elif selector == "atmf_offset":
                    offset_bps = _to_float(spec.get("atm_offset_bps"))
                    if offset_bps is None:
                        raise ValueError(f"Could not resolve ATMF offset alias {raw!r}: missing offset")
                    strike, _ = _snap_to_listed_strike_for_offset(
                        contract=contract,
                        forward=float(forward),
                        as_of=valuation_date,
                        right=right,
                        offset_bps=float(offset_bps),
                    )
                    resolved_symbol = f"{contract}|{_format_strike4(strike, contract=contract)}{right}"
                else:
                    raise ValueError(f"Unsupported live alias selector {selector!r} for symbol {raw!r}")

            resolved_non_delta[raw] = resolved_symbol
            for leg_symbol in _expand_straddle_symbol(resolved_symbol):
                quote_universe[leg_symbol] = leg_symbol

        delta_candidate_symbols: Dict[str, List[str]] = {}
        delta_meta: Dict[str, Dict[str, Any]] = {}
        for raw, spec in delta_specs.items():
            contract = str(spec["contract"])
            right = str(spec["right"]).upper()
            if right not in {"C", "P"}:
                raise ValueError(f"Delta alias supports call/put only: {raw!r}")

            target_delta = _to_float(spec.get("delta"))
            if target_delta is None:
                raise ValueError(f"Could not resolve delta alias {raw!r}: missing delta")

            underlying_contract = _option_contract_to_underlying_contract(contract)
            forward = _to_float(forward_map.get(underlying_contract))
            if forward is None or forward <= 0.0:
                raise ValueError(f"Could not resolve delta alias {raw!r}: missing Schwab live forward for {contract}")

            strike_candidates = _cme_listed_strikes_for_contract_forward(
                contract=contract,
                forward=float(forward),
                as_of=valuation_date,
            )
            if not strike_candidates:
                raise ValueError(f"Could not resolve delta alias {raw!r}: no listed strike rule for {contract}")
            strike_candidates = self._pick_otm_strike_slice(
                list(strike_candidates),
                forward=float(forward),
                right=right,
                count=self._delta_otm_candidate_count(target_delta=float(target_delta), base_count=8),
                itm_buffer=self._delta_itm_buffer_count(
                    target_delta=float(target_delta),
                    ignore_deep_itm=bool(delta_ignore_deep_itm),
                ),
            )
            candidate_symbols = self._dedupe_preserve_order(
                [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_candidates]
            )
            if not candidate_symbols:
                raise ValueError(f"Could not resolve delta alias {raw!r}: no candidate listed strikes for {contract}")
            delta_candidate_symbols[raw] = candidate_symbols
            delta_meta[raw] = {
                "contract": contract,
                "right": right,
                "target_delta": float(target_delta),
                "forward": float(forward),
            }
            for sym in candidate_symbols:
                quote_universe[sym] = sym

        chains, rows_by_symbol = self._build_schwab_live_option_chains(
            canonical_symbols=list(quote_universe.keys()),
        )

        resolved_delta: "OrderedDict[str, str]" = OrderedDict()
        for raw, meta in delta_meta.items():
            contract = str(meta["contract"])
            chain = chains.get(contract, {"call": pd.DataFrame(), "put": pd.DataFrame()})
            resolved_live = self._resolve_live_delta_from_chain_pricers(
                contract=contract,
                chain=chain,
                target_delta=float(meta["target_delta"]),
                right=str(meta["right"]),
                forward=float(meta["forward"]),
                valuation_ts=valuation_ts,
                curve_name=curve_name,
                curve_kwargs=curve_kwargs,
                curve_memo=curve_memo,
                price_mode=price_mode,
                use_ql_calculator=use_ql_calculator,
                base_candidate_count=8,
                ignore_deep_itm=delta_ignore_deep_itm,
                source="SCHWAB_LIVE",
            )
            if resolved_live is None:
                raise ValueError(f"Could not resolve delta alias {raw!r}: no priced Schwab live strikes available.")
            resolved_leg, pr = resolved_live
            resolved_delta[raw] = resolved_leg
            cp_pricers[resolved_leg] = pr

        requested: "OrderedDict[str, str]" = OrderedDict()
        for raw in requested_specs.keys():
            if raw in resolved_non_delta:
                requested[raw] = resolved_non_delta[raw]
            elif raw in resolved_delta:
                requested[raw] = resolved_delta[raw]

        expanded_needed: "OrderedDict[str, str]" = OrderedDict()
        for norm in requested.values():
            for leg_symbol in _expand_straddle_symbol(norm):
                expanded_needed[leg_symbol] = leg_symbol

        for leg_symbol in expanded_needed:
            if leg_symbol in cp_pricers:
                continue
            row = rows_by_symbol.get(leg_symbol)
            if row is None:
                continue
            underlying_contract = _canonical_underlying(leg_symbol)
            forward = _to_float(forward_map.get(underlying_contract))
            if forward is None or forward <= 0.0:
                continue
            quote_ts = self._quote_time_to_dt(row.get("quoteTime"), valuation_ts)
            pr = self._build_pricer_from_row(
                canonical_symbol=leg_symbol,
                row=row,
                valuation_ts=quote_ts,
                forward=float(forward),
                curve_name=curve_name,
                curve_kwargs=curve_kwargs,
                curve_memo=curve_memo,
                price_mode=price_mode,
                source="SCHWAB_LIVE",
                use_ql_calculator=use_ql_calculator,
            )
            if pr is not None:
                cp_pricers[leg_symbol] = pr

        return requested, cp_pricers

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

        vendor_row = dict(row)
        raw_quote = vendor_row.pop("rawQuote", None)
        if not isinstance(raw_quote, dict):
            raw_quote = dict(vendor_row)

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
            "vendor_row": vendor_row,
            "raw_quote": dict(raw_quote),
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

        raw_quote_legs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for pr in (call_pricer, put_pricer):
            meta = pr.meta()
            meta_dict = meta if isinstance(meta, dict) else {}
            raw_quote = meta_dict.get("raw_quote", meta_dict.get("vendor_quote", meta_dict.get("vendor_row")))
            if isinstance(raw_quote, dict):
                raw_quote_legs[str(pr.symbol())] = dict(raw_quote)

        metadata = {
            "schema": 1,
            "source": "SYNTH_STRADDLE",
            "symbol": straddle_symbol,
            "underlying_symbol": call_pricer.underlying_symbol(),
            "legs": [call_pricer.id(), put_pricer.id()],
            "curve_name": call_pricer.meta().get("curve_name"),
            "curve_error": call_pricer.meta().get("curve_error") or put_pricer.meta().get("curve_error"),
            "vendor_legs": [call_pricer.meta().get("vendor_row"), put_pricer.meta().get("vendor_row")],
            "raw_quote_legs": dict(raw_quote_legs),
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
            suffix = f"|{_format_strike4(strike, contract=contract)}{str(right).upper()}"
            rows = df_work[df_work["symbol"].astype(str).str.upper().str.endswith(suffix, na=False)]
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

    def _resolve_live_atmf_offset_strike(
        self,
        *,
        chain: Dict[str, pd.DataFrame],
        contract: str,
        forward: float,
        right: str,
        atm_offset_bps: float,
    ) -> Optional[float]:
        r = str(right).upper()
        if r not in {"C", "P"}:
            return None
        atm_strike = self._resolve_live_atm_strike(chain=chain, forward=forward, right="S")
        if atm_strike is None:
            atm_strike = self._resolve_live_atm_strike(chain=chain, forward=forward, right=r)
        if atm_strike is None:
            return None

        side = "call" if r == "C" else "put"
        strikes = self._live_chain_strikes(chain, side)
        if not strikes:
            try:
                strike, _ = _snap_to_listed_strike_for_offset(
                    contract=contract,
                    forward=float(forward),
                    as_of=datetime.datetime.now(_NY_TZ).date(),
                    right=r,
                    offset_bps=float(atm_offset_bps),
                )
                return float(strike)
            except Exception:
                return None

        signed_offset = -abs(float(atm_offset_bps)) if r == "C" else abs(float(atm_offset_bps))
        side_candidates = (
            [strike for strike in strikes if strike >= atm_strike - 1e-12]
            if r == "C"
            else [strike for strike in strikes if strike <= atm_strike + 1e-12]
        )
        if not side_candidates:
            side_candidates = list(strikes)
        target_strike = float(atm_strike) - signed_offset / 100.0
        return min(
            side_candidates,
            key=lambda strike: (
                abs(float(strike) - float(target_strike)),
                abs(float(atm_strike) - float(strike)),
            ),
        )

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

    def _resolve_live_delta_from_chain_pricers(
        self,
        *,
        contract: str,
        chain: Dict[str, pd.DataFrame],
        target_delta: float,
        right: str,
        forward: float,
        valuation_ts: datetime.datetime,
        curve_name: str,
        curve_kwargs: Optional[Dict[str, Any]],
        curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]],
        price_mode: str,
        use_ql_calculator: bool,
        source: str = "BARCHART_LIVE",
        base_candidate_count: int = 8,
        ignore_deep_itm: bool = False,
    ) -> Optional[Tuple[str, QLSTIRFutureOptionPricer]]:
        side = "call" if str(right).upper() == "C" else "put"
        rule_strikes = _cme_listed_strikes_for_contract_forward(
            contract=contract,
            forward=float(forward),
            as_of=valuation_ts.astimezone(_NY_TZ).date(),
        )
        listed_strikes = self._live_chain_strikes(chain, side)
        strike_candidates: List[float] = []
        seen_strikes = set()
        for strike in list(rule_strikes or []) + list(listed_strikes):
            key = round(float(strike), 8)
            if key in seen_strikes:
                continue
            seen_strikes.add(key)
            strike_candidates.append(float(strike))
        strike_candidates.sort()
        strike_candidates = self._pick_otm_strike_slice(
            strike_candidates,
            forward=float(forward),
            right=str(right).upper(),
            count=self._delta_otm_candidate_count(target_delta=float(target_delta), base_count=int(base_candidate_count)),
            itm_buffer=self._delta_itm_buffer_count(target_delta=float(target_delta), ignore_deep_itm=bool(ignore_deep_itm)),
        )
        candidate_symbols = [
            f"{contract}|{_format_strike4(strike, contract=contract)}{str(right).upper()}"
            for strike in strike_candidates
        ]
        candidate_symbols = self._dedupe_preserve_order(candidate_symbols)
        if not candidate_symbols:
            return None

        target = float(target_delta) / 100.0
        best: Optional[Tuple[float, float, str, QLSTIRFutureOptionPricer]] = None

        for sym in candidate_symbols:
            strike = _strike_from_symbol(sym)
            row = self._extract_live_option_row(chain=chain, contract=contract, strike=strike, right=right)
            if row is None:
                continue
            pr = self._build_pricer_from_row(
                canonical_symbol=sym,
                row=row,
                valuation_ts=valuation_ts,
                forward=float(forward),
                curve_name=curve_name,
                curve_kwargs=curve_kwargs,
                curve_memo=curve_memo,
                price_mode=price_mode,
                source=source,
                use_ql_calculator=use_ql_calculator,
            )
            if pr is None:
                continue
            delta_val = _to_float(pr.delta())
            if delta_val is None or not math.isfinite(delta_val):
                continue

            if str(right).upper() == "C":
                err = abs(float(delta_val) - target)
            else:
                err = min(abs(float(delta_val) + target), abs(abs(float(delta_val)) - target))
            dist = abs(float(strike) - float(forward))
            if best is None or err < best[0] or (abs(err - best[0]) < 1e-12 and dist < best[1]):
                best = (err, dist, sym, pr)

        if best is None:
            return None
        return best[2], best[3]

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

    @staticmethod
    def _delta_otm_candidate_count(*, target_delta: float, base_count: int) -> int:
        delta_abs = abs(float(target_delta))
        if not math.isfinite(delta_abs) or delta_abs <= 0.0:
            return max(1, int(base_count))
        return max(int(base_count), int(math.ceil(125.0 / delta_abs)))

    @staticmethod
    def _delta_itm_buffer_count(*, target_delta: float, ignore_deep_itm: bool) -> int:
        if not bool(ignore_deep_itm):
            return 4
        delta_abs = abs(float(target_delta))
        if not math.isfinite(delta_abs) or delta_abs <= 0.0:
            return 0
        if delta_abs <= 10.0:
            return 0
        if delta_abs <= 20.0:
            return 1
        return 2

    @staticmethod
    def _pick_otm_strike_slice(strikes: List[float], *, forward: float, right: str, count: int, itm_buffer: int) -> List[float]:
        if not strikes:
            return []
        ordered = sorted(float(s) for s in strikes)
        n = max(1, int(count))
        fwd = float(forward)
        right_token = str(right).upper()
        buffer_count = max(0, int(itm_buffer))
        if right_token == "C":
            start_idx = next((i for i, strike in enumerate(ordered) if strike >= fwd), len(ordered) - 1)
            lo = max(0, start_idx - buffer_count)
            hi = min(len(ordered), start_idx + n)
            return ordered[lo:hi]
        if right_token == "P":
            end_idx = next((i for i in range(len(ordered) - 1, -1, -1) if ordered[i] <= fwd), 0)
            lo = max(0, end_idx - n + 1)
            hi = min(len(ordered), end_idx + buffer_count + 1)
            return ordered[lo:hi]
        return ordered[:n]

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

            if selector == "atmf_offset":
                offset_bps = _to_float(spec.get("atm_offset_bps"))
                if offset_bps is None:
                    raise ValueError(f"Could not resolve ATMF offset alias {raw!r}: missing offset")
                strike = self._resolve_live_atmf_offset_strike(
                    chain=chain,
                    contract=contract,
                    forward=float(forward),
                    right=right,
                    atm_offset_bps=float(offset_bps),
                )
                if strike is None:
                    raise ValueError(f"Could not resolve ATMF offset alias {raw!r}: no valid listed strikes.")
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

            if selector not in {"atm", "atmf_offset"}:
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

            if selector == "atm":
                atm_strike = _atm_strike_from_forward(float(forward), step=atm_strike_step)
                resolved[raw] = f"{contract}|{_format_strike4(atm_strike, contract=contract)}{right}"
                continue

            offset_bps = _to_float(spec.get("atm_offset_bps"))
            if offset_bps is None:
                raise ValueError(f"Could not resolve ATMF offset alias {raw!r}: missing offset")
            strike, _ = _snap_to_listed_strike_for_offset(
                contract=contract,
                forward=float(forward),
                as_of=target_date,
                right=right,
                offset_bps=float(offset_bps),
            )
            resolved[raw] = f"{contract}|{_format_strike4(strike, contract=contract)}{right}"

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

    def _historical_atmf_offset_symbols_for_contract_window(
        self,
        *,
        contract: str,
        right: str,
        atm_offset_bps: float,
        underlying_data: Dict[str, pd.DataFrame],
        window_start: datetime.date,
        window_end: datetime.date,
        price_mode: str,
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
            try:
                strike, _ = _snap_to_listed_strike_for_offset(
                    contract=contract,
                    forward=float(forward),
                    as_of=row_day,
                    right=right,
                    offset_bps=float(atm_offset_bps),
                )
            except Exception:
                continue
            out.append(f"{contract}|{_format_strike4(strike, contract=contract)}{right}")

        return self._dedupe_preserve_order(out)

    def _option_snapshot(self, request: Dict[str, Any]) -> Dict[str, List[QLSTIRFutureOptionPricer]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        if not symbols:
            raise ValueError("option_snapshot requires symbols")

        ts = request.get("timestamp", "live")
        show_tqdm = bool(request.get("show_tqdm", False))
        price_mode = str(request.get("price_mode", "mid_then_fallback"))
        use_ql_calculator = bool(request.get("use_ql_calculator", False))
        delta_ignore_deep_itm = bool(request.get("delta_ignore_deep_itm", False))
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
            if str(self.source).upper() == "BARCHART_STIRFO-QL":
                requested, cp_pricers = self._option_snapshot_live_schwab(
                    requested_specs=requested_specs,
                    valuation_ts=ts_dt,
                    curve_name=curve_name,
                    curve_kwargs=curve_kwargs,
                    price_mode=price_mode,
                    use_ql_calculator=use_ql_calculator,
                    delta_ignore_deep_itm=delta_ignore_deep_itm,
                )
            else:
                option_contracts = sorted({_contract_to_barchart_contract(str(spec["contract"])) for spec in requested_specs.values()})
                underlying_contracts = sorted(
                    {_contract_to_barchart_contract(_option_contract_to_underlying_contract(str(spec["contract"]))) for spec in requested_specs.values()}
                )
                chain_concurrency = min(max(len(option_contracts), 1), 32)
                bcf = self._get_barchart_fetcher(required_concurrency=chain_concurrency)
                try:
                    chains = bcf.get_option_quotes(
                        symbols=option_contracts,
                        max_concurrent_tasks=chain_concurrency,
                        max_keepalive_connections=min(max(len(option_contracts), 1), 16),
                        show_tqdm=show_tqdm,
                    )
                finally:
                    try:
                        bcf.close()
                    except Exception:
                        pass
                forward_map = self._fetch_barchart_intraday_prices(
                    contracts=underlying_contracts,
                    timestamp=ts_dt,
                    window_minutes=window_minutes,
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
                    resolved_non_delta = self._resolve_snapshot_requested_symbols_live(
                        requested_specs=non_delta_specs,
                        chains=chains,
                        forward_map=forward_map,
                    )

                curve_memo: Dict[Tuple[str, datetime.date], Tuple[Any, Optional[str]]] = {}
                resolved_delta: "OrderedDict[str, str]" = OrderedDict()
                for raw, spec in delta_specs.items():
                    right = str(spec["right"]).upper()
                    if right not in {"C", "P"}:
                        raise ValueError(f"Delta alias supports call/put only: {raw!r}")

                    delta = _to_float(spec.get("delta"))
                    if delta is None:
                        raise ValueError(f"Could not resolve delta alias {raw!r}: missing delta")

                    contract = str(spec["contract"])
                    option_bcontract = _contract_to_barchart_contract(contract)
                    underlying_contract = _option_contract_to_underlying_contract(contract)
                    underlying_bcontract = _contract_to_barchart_contract(underlying_contract)
                    chain = chains.get(option_bcontract)
                    forward = _to_float(forward_map.get(underlying_bcontract))
                    if chain is None or forward is None or forward <= 0.0:
                        raise ValueError(f"Could not resolve delta alias {raw!r}: missing live chain/forward for {contract}")

                    resolved_live = self._resolve_live_delta_from_chain_pricers(
                        contract=contract,
                        chain=chain,
                        target_delta=float(delta),
                        right=right,
                        forward=float(forward),
                        valuation_ts=ts_dt,
                        curve_name=curve_name,
                        curve_kwargs=curve_kwargs,
                        curve_memo=curve_memo,
                        price_mode=price_mode,
                        use_ql_calculator=use_ql_calculator,
                        base_candidate_count=8,
                        ignore_deep_itm=delta_ignore_deep_itm,
                    )
                    if resolved_live is None:
                        raise ValueError(f"Could not resolve delta alias {raw!r}: no priced live strikes available.")
                    resolved_leg, pr = resolved_live
                    resolved_delta[raw] = resolved_leg
                    cp_pricers[resolved_leg] = pr

                requested = OrderedDict()
                for raw in requested_specs.keys():
                    if raw in resolved_non_delta:
                        requested[raw] = resolved_non_delta[raw]
                    elif raw in resolved_delta:
                        requested[raw] = resolved_delta[raw]

                expanded_needed: "OrderedDict[str, str]" = OrderedDict()
                for norm in requested.values():
                    for leg in _expand_straddle_symbol(norm):
                        expanded_needed[leg] = leg

                for leg_symbol in expanded_needed:
                    if leg_symbol in cp_pricers:
                        continue
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

            # SABR fast-path: resolve delta specs from cached SABR smiles.
            # Unresolved delta specs are dropped (NaN) unless force_refresh
            # is set, which explicitly requests a Barchart chain fetch.
            force_refresh = bool(request.get("force_refresh", False))
            resolved_delta_sabr: "OrderedDict[str, str]" = OrderedDict()
            if delta_specs:
                sabr_resolved_raws: List[str] = []
                for raw, spec in delta_specs.items():
                    right = str(spec.get("right", "")).upper()
                    target_delta = _to_float(spec.get("delta"))
                    if right not in {"C", "P"} or target_delta is None:
                        continue
                    contract = str(spec["contract"])
                    underlying_contract = _option_contract_to_underlying_contract(contract)
                    underlying_bcontract = _contract_to_barchart_contract(underlying_contract)
                    fut_df = underlying_data.get(underlying_bcontract)
                    if fut_df is None or fut_df.empty:
                        continue
                    target_ts_local = pd.Timestamp(_NY_TZ.localize(datetime.datetime.combine(target_date, datetime.time(17, 0))))
                    pos = _asof_index_position(fut_df.index, target_ts_local)
                    if pos is None:
                        continue
                    forward = _extract_row_price(fut_df.iloc[pos].to_dict(), price_mode=price_mode)
                    if forward is None or forward <= 0.0:
                        continue
                    pr = self._resolve_delta_from_sabr_cache(
                        contract=contract, as_of=target_date,
                        target_delta=float(target_delta), right=right,
                        forward=float(forward),
                    )
                    if pr is not None:
                        resolved_leg = pr.symbol()
                        resolved_delta_sabr[raw] = resolved_leg
                        cp_pricers[resolved_leg] = pr
                        sabr_resolved_raws.append(raw)
                for raw in sabr_resolved_raws:
                    del delta_specs[raw]
                if not force_refresh:
                    delta_specs.clear()

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
                    try:
                        fetched = bcf.get_option_quotes(
                            symbols=option_contracts,
                            max_concurrent_tasks=chain_concurrency,
                            max_keepalive_connections=min(max(len(option_contracts), 1), 16),
                            show_tqdm=show_tqdm,
                        )
                    finally:
                        try:
                            bcf.close()
                        except Exception:
                            pass
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
                                listed_strikes = self._live_chain_strikes(chain, "call" if right == "C" else "put") if chain is not None else []
                                strike_candidates: List[float] = []
                                seen_strikes = set()
                                for strike in list(strike_subset) + list(listed_strikes):
                                    key = round(float(strike), 8)
                                    if key in seen_strikes:
                                        continue
                                    seen_strikes.add(key)
                                    strike_candidates.append(float(strike))
                                strike_candidates.sort()
                                strike_candidates = self._pick_otm_strike_slice(
                                    strike_candidates,
                                    forward=float(forward),
                                    right=right,
                                    count=self._delta_otm_candidate_count(
                                        target_delta=float(target_delta),
                                        base_count=delta_candidate_half_width,
                                    ),
                                    itm_buffer=self._delta_itm_buffer_count(
                                        target_delta=float(target_delta),
                                        ignore_deep_itm=delta_ignore_deep_itm,
                                    ),
                                )
                                # Union the rule lattice with the actual listed chain so
                                # live fine-grid strikes (e.g. 9818) survive stale rules
                                # without expanding to the entire ladder.
                                candidate_symbols.extend(
                                    [f"{contract}|{_format_strike4(strike, contract=contract)}{right}" for strike in strike_candidates]
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
                        continue
                    if selector == "atmf_offset":
                        offset_bps = _to_float(spec.get("atm_offset_bps"))
                        if offset_bps is None:
                            raise ValueError(f"Missing ATMF offset in historical alias spec: {raw!r}")
                        for contract in contracts:
                            offset_symbols = self._historical_atmf_offset_symbols_for_contract_window(
                                contract=contract,
                                right=right,
                                atm_offset_bps=float(offset_bps),
                                underlying_data=underlying_data,
                                window_start=req_window_start,
                                window_end=req_window_end,
                                price_mode=price_mode,
                            )
                            for norm in offset_symbols:
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
                    force_refresh=bool(request.get("force_refresh", False)),
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
                if raw in resolved_delta_sabr:
                    requested[raw] = resolved_delta_sabr[raw]
                elif raw in resolved_non_delta:
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
                    f"got alias {raw!r}. Use option_snapshot for ATM/delta/ATMF-offset aliases."
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
            force_refresh=bool(request.get("force_refresh", False)),
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
        if value == STIRFutureOptionValue.DV01:
            return float(dollar_dv01(pricer))
        if value == STIRFutureOptionValue.DELTA:
            return float(pricer.delta())
        if value == STIRFutureOptionValue.GAMMA:
            return float(pricer.gamma())
        if value == STIRFutureOptionValue.GAMMA_01:
            return float(dollar_gamma_01(pricer))
        if value == STIRFutureOptionValue.VEGA:
            return float(pricer.vega())
        if value == STIRFutureOptionValue.VEGA_01:
            return float(dollar_vega_01(pricer))
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
        fresh_quikstrike_session_per_symbol = bool(request.get("fresh_quikstrike_session_per_symbol", False))
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

        query_batches: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        if fresh_quikstrike_session_per_symbol:
            for query, meta in zip(qlist, query_meta):
                batch_key = str(meta.get("globex_symbol") or getattr(query, "globex_symbol", "")).strip().upper()
                batch = query_batches.setdefault(batch_key, {"queries": [], "query_meta": []})
                batch["queries"].append(query)
                batch["query_meta"].append(meta)
        else:
            query_batches["__all__"] = {"queries": qlist, "query_meta": query_meta}

        fetched_frames: List[pd.DataFrame] = []
        pricers_by_series: "OrderedDict[str, List[Any]]" = OrderedDict()
        for batch in query_batches.values():
            for attempt in (0, 1):
                try:
                    qsf = self._quikstrike_client(
                        force_refresh=force_refresh or fresh_quikstrike_session_per_symbol or attempt == 1
                    )
                    batch_df = qsf.fetch_quikvol_timeseries(
                        start_date=start_dt,
                        end_date=end_dt,
                        queries=batch["queries"],
                    )
                    fetched_frames.append(batch_df)
                    if return_options or value_enum is not None:
                        batch_pricers_by_series = self._qs_timeseries_to_pricers(
                            df=batch_df,
                            query_meta=batch["query_meta"],
                            underlying_data=underlying_data,
                            curve_name=curve_name,
                            curve_kwargs=curve_kwargs,
                            use_ql_calculator=use_ql_calculator,
                        )
                        for series_label, batch_pricers in batch_pricers_by_series.items():
                            pricers_by_series.setdefault(series_label, []).extend(batch_pricers)
                    break
                except Exception:
                    if attempt == 1:
                        raise

        if return_options:
            return pricers_by_series
        if value_enum is not None:
            return {"qs_timeseries": [self._qs_pricers_to_value_df(pricers_by_series=pricers_by_series, value=value_enum)]}
        if not fetched_frames:
            return {"qs_timeseries": [pd.DataFrame()]}
        if len(fetched_frames) == 1:
            return {"qs_timeseries": [fetched_frames[0]]}
        merged_df = pd.concat(fetched_frames, axis=1).sort_index()
        merged_df.index.name = fetched_frames[0].index.name
        return {"qs_timeseries": [merged_df]}
        raise RuntimeError("QuikStrike timeseries fetch failed")

    def fetch_sabr_smile(self, request: Dict[str, Any]) -> STIRFutureOptionSABRSmile:
        req = dict(request)
        req["endpoint"] = "sabr_smile"
        out = self.get_data(req)
        smiles = out.get("sabr_smile") or []
        if not smiles:
            raise ValueError("sabr_smile returned no calibrated smile.")
        return self._normalize_stir_sabr_smile_convention(smiles[0])

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
                smile, common_key = self._build_sabr_smile_result(request)
                out = {"sabr_smile": [smile]}
            else:
                raise NotImplementedError(f"Unsupported endpoint: {endpoint}")

            if cache_key:
                self._threadsafe_cache_put(cache_key, self._serialize_get_data_result(endpoint, out))
            if endpoint == "sabr_smile" and common_key and (force_refresh or self._threadsafe_cache_get(common_key) is None):
                self._store_sabr_smile_common_cache(common_key=common_key, smile=smile)
            return out

    def get_bulk_pricer(self, request: Dict[str, Any]):
        return self.get_bulk_data(request)

    def get_bulk_data(self, request: Dict[str, Any]):
        endpoint = str(request.get("endpoint", "")).strip().lower()
        if endpoint == "sabr_smile":
            req = dict(request)
            smiles_by_symbol = self.fetch_bulk_sabr_smile(req)
            _, dates, _, _, _, _, _, _ = self._normalize_bulk_sabr_smile_request(req)
            out: "OrderedDict[datetime.date, OrderedDict[str, List[STIRFutureOptionSABRSmile]]]" = OrderedDict(
                (as_of, OrderedDict()) for as_of in dates
            )
            for symbol, by_date in smiles_by_symbol.items():
                for as_of, smile in by_date.items():
                    out.setdefault(as_of, OrderedDict())[symbol] = [smile]
            return {as_of: dict(rows) for as_of, rows in out.items()}

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
