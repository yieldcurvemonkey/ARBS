from __future__ import annotations

import datetime as dt
import math
import re
from typing import Optional

import QuantLib as ql
from scipy.optimize import brentq, newton
from scipy.stats import norm


_TENOR_RE = re.compile(r"^\s*(\d+)\s*([DWMYdwm y])\s*$")
_MIDCURVE_RE = re.compile(r"^\s*(\d+\s*[DWMYdwm y])\s*[xX]\s*(\d+\s*[DWMYdwm y])\s*$")
_ATM_RE = re.compile(r"^\s*(ATMF|ATMS)\s*(?:([+-])\s*(\d+(?:\.\d+)?)\s*B?P?S?)?\s*$", re.IGNORECASE)
_DELTA_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*D\s*$", re.IGNORECASE)
_SHORTHANDLE_TOKEN_RE = re.compile(r"\d+[DWMYdwm y]")


def to_date(value: dt.date | dt.datetime | str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "live":
            return dt.date.today()
        return dt.date.fromisoformat(value)
    raise TypeError(f"Unsupported date value type: {type(value)}")


def parse_tenor_to_period(tenor: str) -> ql.Period:
    token = str(tenor or "").replace(" ", "").upper()
    m = _TENOR_RE.match(token)
    if not m:
        raise ValueError(f"Invalid tenor: {tenor}")
    n = int(m.group(1))
    u = m.group(2).upper()
    if u == "D":
        return ql.Period(n, ql.Days)
    if u == "W":
        return ql.Period(n, ql.Weeks)
    if u == "M":
        return ql.Period(n, ql.Months)
    if u == "Y":
        return ql.Period(n, ql.Years)
    raise ValueError(f"Invalid tenor unit in {tenor}")


def normalize_tenor(tenor: str) -> str:
    p = parse_tenor_to_period(tenor)
    unit = {ql.Days: "D", ql.Weeks: "W", ql.Months: "M", ql.Years: "Y"}[p.units()]
    return f"{int(p.length())}{unit}"


def parse_midcurve_tail(tail: str) -> tuple[Optional[str], str]:
    token = str(tail or "").strip().upper().replace(" ", "")
    m = _MIDCURVE_RE.match(token)
    if not m:
        return None, normalize_tenor(token)
    fwd = normalize_tenor(m.group(1))
    tenor = normalize_tenor(m.group(2))
    return fwd, tenor


def parse_expiry_tail_shorthandle(shorthandle: str) -> tuple[str, str]:
    token = str(shorthandle or "").strip().upper().replace(" ", "")
    if not token:
        raise ValueError("Invalid shorthandle: empty input")

    parts = [m.group(0).upper() for m in _SHORTHANDLE_TOKEN_RE.finditer(token)]
    leftover = _SHORTHANDLE_TOKEN_RE.sub("", token)
    if leftover and any(ch != "X" for ch in leftover):
        raise ValueError(f"Invalid shorthandle: {shorthandle}")

    if len(parts) == 2:
        return normalize_tenor(parts[0]), normalize_tenor(parts[1])
    if len(parts) == 3:
        return normalize_tenor(parts[0]), f"{normalize_tenor(parts[1])}x{normalize_tenor(parts[2])}"
    raise ValueError(
        f"Invalid shorthandle '{shorthandle}'. Expected forms like '5Yx5Y', '5Y5Y', or '1Yx1Yx10Y'."
    )


def parse_side(side: str | None) -> int:
    token = str(side or "buy").strip().lower()
    if token in {"buy", "b", "long", "l"}:
        return 1
    if token in {"sell", "s", "short"}:
        return -1
    raise ValueError(f"Invalid side '{side}'. Expected 'buy' or 'sell'.")


def option_type_to_ql(option_type: str) -> int:
    token = str(option_type).strip().lower()
    if token in {"payer", "call", "c"}:
        return ql.Option.Call
    if token in {"receiver", "put", "p"}:
        return ql.Option.Put
    raise ValueError(f"Invalid option type '{option_type}'. Expected payer/receiver.")


def strike_value_to_decimal(value: float | int | str) -> float:
    if isinstance(value, str):
        num = float(value.strip())
    else:
        num = float(value)
    if abs(num) > 200.0:
        return num / 10_000.0
    if abs(num) > 2.0:
        return num / 100.0
    return num


def bachelier_price(
    *,
    option_type: str,
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float = 1.0,
) -> float:
    stddev = max(float(vol_normal), 0.0) * math.sqrt(max(float(tte), 1e-12))
    return float(
        ql.bachelierBlackFormula(
            option_type_to_ql(option_type),
            float(strike),
            float(forward),
            float(stddev),
            float(discount),
        )
    )


def bachelier_vega(
    *,
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float = 1.0,
) -> float:
    sigma = max(float(vol_normal), 1e-12)
    t = max(float(tte), 1e-12)
    d = (float(forward) - float(strike)) / (sigma * math.sqrt(t))
    return float(discount) * math.sqrt(t) * float(norm.pdf(d))


def _normal_delta(
    *,
    option_type: str,
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
) -> float:
    sigma = max(float(vol_normal), 1e-12)
    t = max(float(tte), 1e-12)
    d = (float(forward) - float(strike)) / (sigma * math.sqrt(t))
    call_delta = float(norm.cdf(d))
    token = str(option_type).strip().lower()
    if token in {"payer", "call", "c"}:
        return call_delta
    if token in {"receiver", "put", "p"}:
        return call_delta - 1.0
    raise ValueError(f"Invalid option type '{option_type}'.")


def solve_strike_for_target_delta(
    *,
    target_delta_abs: float,
    option_type: str,
    forward: float,
    vol_normal: float,
    tte: float,
    lower_bound: Optional[float] = None,
    upper_bound: Optional[float] = None,
) -> float:
    target = float(target_delta_abs) / 100.0
    if target <= 0.0 or target >= 1.0:
        raise ValueError(f"target_delta_abs must be in (0,100), got {target_delta_abs}")

    sign_target = target if str(option_type).strip().lower() in {"payer", "call", "c"} else -target

    def f(k: float) -> float:
        return _normal_delta(
            option_type=option_type,
            strike=k,
            forward=forward,
            vol_normal=vol_normal,
            tte=tte,
        ) - sign_target

    stddev = max(float(vol_normal), 1e-8) * math.sqrt(max(float(tte), 1e-10))
    width = max(6.0 * stddev, 0.02)
    lo = float(lower_bound) if lower_bound is not None else float(forward) - width
    hi = float(upper_bound) if upper_bound is not None else float(forward) + width

    for _ in range(8):
        try:
            flo = f(lo)
            fhi = f(hi)
            if flo == 0.0:
                return lo
            if fhi == 0.0:
                return hi
            if flo * fhi < 0.0:
                return float(brentq(f, lo, hi, maxiter=200))
        except Exception:
            pass
        lo -= width
        hi += width
        width *= 1.5

    guess = float(forward)
    try:
        root = float(newton(f, x0=guess, maxiter=100))
        if lower_bound is not None:
            root = max(root, float(lower_bound))
        if upper_bound is not None:
            root = min(root, float(upper_bound))
        return root
    except Exception as exc:
        raise ValueError(
            f"Delta strike solve failed for target={target_delta_abs}D, option_type={option_type}, "
            f"forward={forward}, vol={vol_normal}, tte={tte}, guess={guess}"
        ) from exc


def resolve_strike_spec(
    strike_spec: float | int | str | None,
    *,
    atmf: float,
    atms: Optional[float],
    option_type: str,
    vol_normal: Optional[float],
    tte: Optional[float],
    forward: Optional[float] = None,
) -> float:
    if strike_spec is None:
        return float(atmf)
    if isinstance(strike_spec, (int, float)):
        return strike_value_to_decimal(strike_spec)

    token = str(strike_spec).strip().upper().replace(" ", "")
    if not token:
        return float(atmf)

    m_atm = _ATM_RE.match(token)
    if m_atm:
        base_name = m_atm.group(1).upper()
        sign = m_atm.group(2)
        bump = float(m_atm.group(3)) if m_atm.group(3) is not None else 0.0
        base = float(atmf if base_name == "ATMF" else (atms if atms is not None else atmf))
        if sign == "+":
            return base + bump / 10_000.0
        if sign == "-":
            return base - bump / 10_000.0
        return base

    m_delta = _DELTA_RE.match(token)
    if m_delta:
        if vol_normal is None or tte is None:
            raise ValueError(f"Delta strike '{strike_spec}' requires vol_normal and tte inputs.")
        return solve_strike_for_target_delta(
            target_delta_abs=float(m_delta.group(1)),
            option_type=option_type,
            forward=float(forward if forward is not None else atmf),
            vol_normal=float(vol_normal),
            tte=float(tte),
        )

    return strike_value_to_decimal(token)
