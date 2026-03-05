from __future__ import annotations

import datetime
import re
from typing import Dict, Iterable, List, Optional, Tuple


MONTH_CODE_TO_NUM: Dict[str, int] = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}
NUM_TO_MONTH_CODE: Dict[int, str] = {v: k for k, v in MONTH_CODE_TO_NUM.items()}
QUARTERLY_MONTHS: Tuple[int, ...] = (3, 6, 9, 12)


MONTHLY_ROOT_ALIAS_TO_CANON: Dict[str, str] = {
    "ZT": "ZT",
    "ZF": "ZF",
    "ZN": "ZN",
    "ZB": "ZB",
    "TU": "ZT",
    "FV": "ZF",
    "TY": "ZN",
    "US": "ZB",
}

MONTHLY_CANON_ROOTS: Tuple[str, ...] = ("ZT", "ZF", "ZN", "ZB")

OPTION_POINT_VALUE_BY_BASE_ROOT: Dict[str, float] = {
    "ZT": 2000.0,
    "ZF": 1000.0,
    "ZN": 1000.0,
    "ZB": 1000.0,
}


def _range_tokens(prefix: str, lo: str, hi: str) -> List[str]:
    if lo.isdigit() and hi.isdigit():
        return [f"{prefix}{i}" for i in range(int(lo), int(hi) + 1)]
    out: List[str] = []
    for c in range(ord(lo), ord(hi) + 1):
        out.append(f"{prefix}{chr(c)}")
    return out


# Deterministic weekly extrapolation map from base monthly root.
WEEKLY_ROOTS_BY_BASE_ROOT: Dict[str, Dict[str, List[str]]] = {
    "ZN": {
        "friday": _range_tokens("BN", "1", "5"),
        "monday": ["BG6", "BG7", "BG8", "BG9", "BG0"],
        "tuesday": _range_tokens("BN", "A", "E"),
        "wednesday": ["BN6", "BN7", "BN8", "BN9", "BN0"],
        "thursday": _range_tokens("BN", "F", "J"),
    },
    "ZT": {
        "friday": _range_tokens("BT", "1", "5"),
        "monday": _range_tokens("BD", "1", "5"),
        "tuesday": _range_tokens("BT", "A", "E"),
        "wednesday": ["BT6", "BT7", "BT8", "BT9", "BT0"],
        "thursday": _range_tokens("BT", "F", "J"),
    },
    "ZF": {
        "friday": _range_tokens("BF", "1", "5"),
        "monday": ["BD6", "BD7", "BD8", "BD9", "BD0"],
        "tuesday": _range_tokens("BF", "A", "E"),
        "wednesday": ["BF6", "BF7", "BF8", "BF9", "BF0"],
        "thursday": _range_tokens("BF", "F", "J"),
    },
    "ZB": {
        "friday": _range_tokens("BB", "1", "5"),
        "monday": _range_tokens("BG", "A", "E"),
        "tuesday": _range_tokens("BB", "A", "E"),
        "wednesday": ["BB6", "BB7", "BB8", "BB9", "BB0"],
        "thursday": _range_tokens("BB", "F", "J"),
    },
}

WEEKLY_ROOT_TO_BASE_ROOT: Dict[str, str] = {}
WEEKLY_ROOT_META: Dict[str, Tuple[int, int]] = {}

_WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
}

for _base_root, _by_day in WEEKLY_ROOTS_BY_BASE_ROOT.items():
    for _weekday_name, _roots in _by_day.items():
        _weekday = _WEEKDAY_INDEX[_weekday_name]
        for _idx, _root in enumerate(_roots, start=1):
            WEEKLY_ROOT_TO_BASE_ROOT[_root] = _base_root
            WEEKLY_ROOT_META[_root] = (_weekday, _idx)


ALL_OPTION_ROOTS: Tuple[str, ...] = tuple(
    sorted(
        set(MONTHLY_ROOT_ALIAS_TO_CANON.keys()).union(set(WEEKLY_ROOT_TO_BASE_ROOT.keys())),
        key=lambda x: (len(x), x),
        reverse=True,
    )
)

OPTION_ROOT_TOKEN_PATTERN = "|".join(re.escape(r) for r in ALL_OPTION_ROOTS)

_CONTRACT_RE = re.compile(
    rf"^(?P<root>{OPTION_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{1,2}})$",
    re.IGNORECASE,
)


def normalize_monthly_root(root: str) -> str:
    tok = str(root or "").strip().upper()
    if tok not in MONTHLY_ROOT_ALIAS_TO_CANON:
        raise ValueError(f"Unsupported UST monthly option root: {root}")
    return MONTHLY_ROOT_ALIAS_TO_CANON[tok]


def normalize_option_root(root: str) -> str:
    tok = str(root or "").strip().upper()
    if tok in WEEKLY_ROOT_TO_BASE_ROOT:
        return tok
    return normalize_monthly_root(tok)


def option_root_base_root(root: str) -> str:
    tok = normalize_option_root(root)
    return WEEKLY_ROOT_TO_BASE_ROOT.get(tok, tok)


def is_weekly_root(root: str) -> bool:
    tok = normalize_option_root(root)
    return tok in WEEKLY_ROOT_TO_BASE_ROOT


def _nearest_yy_for_one_digit(digit: int, *, as_of: datetime.date) -> int:
    year = int(as_of.year)
    base_decade = (year // 10) * 10
    candidates = [base_decade + digit, base_decade - 10 + digit, base_decade + 10 + digit]
    candidates = [c for c in candidates if 2000 <= c <= 2099]
    candidates.sort(key=lambda y: (abs(y - year), 0 if y >= year else 1))
    return candidates[0]


def normalize_contract_code(code: str, *, as_of: Optional[datetime.date] = None) -> str:
    tok = str(code or "").strip().upper()
    m = re.fullmatch(r"([FGHJKMNQUVXZ])(\d{1,2})", tok)
    if m is None:
        raise ValueError(f"Invalid contract code: {code}")
    month_code = m.group(1)
    yraw = m.group(2)
    if len(yraw) == 2:
        yy = int(yraw)
        return f"{month_code}{yy:02d}"
    as_of_date = as_of or datetime.date.today()
    abs_year = _nearest_yy_for_one_digit(int(yraw), as_of=as_of_date)
    return f"{month_code}{abs_year % 100:02d}"


def normalize_option_contract(contract: str, *, as_of: Optional[datetime.date] = None) -> str:
    tok = str(contract or "").strip().upper().replace("/", "")
    m = _CONTRACT_RE.fullmatch(tok)
    if m is None:
        raise ValueError(f"Invalid UST option contract token: {contract}")
    root = normalize_option_root(m.group("root"))
    code = normalize_contract_code(m.group("code"), as_of=as_of)
    return f"{root}{code}"


def parse_option_contract(contract: str, *, as_of: Optional[datetime.date] = None) -> Tuple[str, str]:
    norm = normalize_option_contract(contract, as_of=as_of)
    return norm[:-3], norm[-3:]


def weekly_root_meta(root: str) -> Tuple[int, int]:
    tok = normalize_option_root(root)
    if tok not in WEEKLY_ROOT_META:
        raise ValueError(f"Root is not weekly: {root}")
    return WEEKLY_ROOT_META[tok]


def _next_quarter_month(month: int, year: int, *, strict: bool) -> Tuple[int, int]:
    if strict:
        cand = [m for m in QUARTERLY_MONTHS if m > month]
    else:
        cand = [m for m in QUARTERLY_MONTHS if m >= month]
    if cand:
        return cand[0], year
    return QUARTERLY_MONTHS[0], year + 1


def underlying_contract_for_option(option_contract: str) -> str:
    root, code = parse_option_contract(option_contract)
    base_root = option_root_base_root(root)
    month_code = code[0]
    yy = int(code[1:])
    year = 2000 + yy
    month = MONTH_CODE_TO_NUM[month_code]

    if is_weekly_root(root):
        ul_month, ul_year = _next_quarter_month(month, year, strict=True)
    else:
        if month in QUARTERLY_MONTHS:
            ul_month, ul_year = month, year
        else:
            ul_month, ul_year = _next_quarter_month(month, year, strict=False)

    return f"{base_root}{NUM_TO_MONTH_CODE[ul_month]}{ul_year % 100:02d}"


def strike_step_for_contract(contract_or_root: str) -> float:
    tok = str(contract_or_root or "").strip().upper().replace("/", "")
    if _CONTRACT_RE.fullmatch(tok):
        root = tok[:-3]
    else:
        root = normalize_option_root(tok)
    base = option_root_base_root(root)
    if is_weekly_root(root):
        if base == "ZT":
            return 0.125
        if base in {"ZF", "ZN"}:
            return 0.25
        return 0.5
    if base == "ZT":
        return 0.125
    if base == "ZF":
        return 0.25
    return 0.5


def option_point_value_for_contract(contract_or_root: str) -> float:
    tok = str(contract_or_root or "").strip().upper().replace("/", "")
    if _CONTRACT_RE.fullmatch(tok):
        root = tok[:-3]
    else:
        root = tok
    base = option_root_base_root(root)
    return float(OPTION_POINT_VALUE_BY_BASE_ROOT[base])


def _split_int_frac(strike: float) -> Tuple[int, float]:
    k = float(strike)
    whole = int(k)
    frac = round(k - whole, 6)
    if frac < 0:
        raise ValueError(f"Invalid negative strike fraction: {strike}")
    if frac >= 1.0:
        whole += int(frac)
        frac = round(frac - int(frac), 6)
    return whole, frac


def _closest_key(frac: float, mapping: Dict[str, float], *, tol: float = 1e-6) -> str:
    best_key = min(mapping.keys(), key=lambda k: abs(mapping[k] - frac))
    if abs(mapping[best_key] - frac) > tol:
        raise ValueError(f"Unsupported strike fractional part {frac:.6f} for mapping {mapping}")
    return best_key


_ZT_MONTHLY_FRAC_MAP = {
    "0": 0.0,
    "1": 0.125,
    "2": 0.25,
    "3": 0.375,
    "5": 0.5,
    "6": 0.625,
    "7": 0.75,
    "8": 0.875,
}
_ZF_MONTHLY_FRAC_MAP = {"0": 0.0, "2": 0.25, "5": 0.5, "7": 0.75}
_ZN_MONTHLY_FRAC_MAP = {"0": 0.0, "5": 0.5}
_HALF_FRAC_2D_MAP = {"00": 0.0, "50": 0.5}
_QUARTER_FRAC_2D_MAP = {"00": 0.0, "20": 0.25, "50": 0.5, "70": 0.75}
_EIGHTH_FRAC_2D_MAP = {
    "00": 0.0,
    "10": 0.125,
    "20": 0.25,
    "30": 0.375,
    "50": 0.5,
    "60": 0.625,
    "70": 0.75,
    "80": 0.875,
}


def decode_strike_token(*, contract_or_root: str, strike_token: str) -> float:
    root_raw = str(contract_or_root or "").strip().upper().replace("/", "")
    if _CONTRACT_RE.fullmatch(root_raw):
        root = root_raw[:-3]
    else:
        root = normalize_option_root(root_raw)
    base = option_root_base_root(root)
    weekly = is_weekly_root(root)
    tok = str(strike_token or "").strip()
    if not re.fullmatch(r"\d{3,5}", tok):
        raise ValueError(f"Invalid strike token: {strike_token}")

    if weekly:
        if len(tok) < 4:
            raise ValueError(f"Weekly strike token must be at least 4 digits: {strike_token}")
        whole = int(tok[:-2])
        suffix = tok[-2:]
        if base == "ZT":
            mapping = _EIGHTH_FRAC_2D_MAP
        elif base in {"ZF", "ZN"}:
            mapping = _QUARTER_FRAC_2D_MAP
        else:
            mapping = _HALF_FRAC_2D_MAP
        if suffix not in mapping:
            raise ValueError(f"Invalid weekly strike suffix {suffix} for base root {base}")
        return whole + mapping[suffix]

    if base == "ZB":
        if len(tok) < 4:
            raise ValueError(f"Monthly ZB strike token must be at least 4 digits: {strike_token}")
        whole = int(tok[:-2])
        suffix = tok[-2:]
        if suffix not in _HALF_FRAC_2D_MAP:
            raise ValueError(f"Invalid monthly ZB strike suffix {suffix}")
        return whole + _HALF_FRAC_2D_MAP[suffix]

    whole = int(tok[:-1])
    suffix1 = tok[-1]
    if base == "ZT":
        mapping = _ZT_MONTHLY_FRAC_MAP
    elif base == "ZF":
        mapping = _ZF_MONTHLY_FRAC_MAP
    else:
        mapping = _ZN_MONTHLY_FRAC_MAP
    if suffix1 not in mapping:
        raise ValueError(f"Invalid monthly strike suffix {suffix1} for base root {base}")
    return whole + mapping[suffix1]


def encode_strike_token(*, contract_or_root: str, strike: float) -> str:
    root_raw = str(contract_or_root or "").strip().upper().replace("/", "")
    if _CONTRACT_RE.fullmatch(root_raw):
        root = root_raw[:-3]
    else:
        root = normalize_option_root(root_raw)
    base = option_root_base_root(root)
    weekly = is_weekly_root(root)
    whole, frac = _split_int_frac(strike)

    if weekly:
        if base == "ZT":
            key = _closest_key(frac, _EIGHTH_FRAC_2D_MAP)
        elif base in {"ZF", "ZN"}:
            key = _closest_key(frac, _QUARTER_FRAC_2D_MAP)
        else:
            key = _closest_key(frac, _HALF_FRAC_2D_MAP)
        return f"{whole}{key}"

    if base == "ZB":
        key = _closest_key(frac, _HALF_FRAC_2D_MAP)
        return f"{whole}{key}"
    if base == "ZT":
        key = _closest_key(frac, _ZT_MONTHLY_FRAC_MAP)
    elif base == "ZF":
        key = _closest_key(frac, _ZF_MONTHLY_FRAC_MAP)
    else:
        key = _closest_key(frac, _ZN_MONTHLY_FRAC_MAP)
    return f"{whole}{key}"


def normalize_strike_token(*, contract_or_root: str, strike_token: str) -> str:
    strike = decode_strike_token(contract_or_root=contract_or_root, strike_token=strike_token)
    return encode_strike_token(contract_or_root=contract_or_root, strike=strike)


def month_from_code(code: str) -> int:
    tok = str(code or "").strip().upper()
    if len(tok) < 1 or tok[0] not in MONTH_CODE_TO_NUM:
        raise ValueError(f"Invalid month code: {code}")
    return MONTH_CODE_TO_NUM[tok[0]]


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime.date:
    if n <= 0:
        raise ValueError("n must be >= 1")
    first = datetime.date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    candidate = first + datetime.timedelta(days=shift + 7 * (n - 1))
    if candidate.month == month:
        return candidate
    # Fallback to last such weekday in month if nth does not exist.
    last = datetime.date(year, month, 28)
    while True:
        nxt = last + datetime.timedelta(days=1)
        if nxt.month != month:
            break
        last = nxt
    delta = (last.weekday() - weekday) % 7
    return last - datetime.timedelta(days=delta)


def monthly_option_expiry_from_code(code: str) -> datetime.date:
    norm = normalize_contract_code(code)
    month = MONTH_CODE_TO_NUM[norm[0]]
    year = 2000 + int(norm[1:])
    # "Month preceding option month"
    if month == 1:
        prev_month, prev_year = 12, year - 1
    else:
        prev_month, prev_year = month - 1, year
    # Last business day (Mon-Fri) of prev month.
    day = datetime.date(prev_year, prev_month, 28)
    while True:
        nxt = day + datetime.timedelta(days=1)
        if nxt.month != prev_month:
            break
        day = nxt
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    # At least two business days before last business day.
    cutoff = day
    moved = 0
    while moved < 2:
        cutoff -= datetime.timedelta(days=1)
        if cutoff.weekday() < 5:
            moved += 1
    # Last Friday on/before cutoff.
    while cutoff.weekday() != 4:
        cutoff -= datetime.timedelta(days=1)
    return cutoff


def option_expiry_date(option_contract: str) -> datetime.date:
    root, code = parse_option_contract(option_contract)
    month = MONTH_CODE_TO_NUM[code[0]]
    year = 2000 + int(code[1:])
    if is_weekly_root(root):
        weekday, idx = weekly_root_meta(root)
        return nth_weekday_of_month(year, month, weekday, idx)
    return monthly_option_expiry_from_code(code)


def iter_all_weekly_roots() -> Iterable[str]:
    return tuple(sorted(WEEKLY_ROOT_TO_BASE_ROOT.keys()))

