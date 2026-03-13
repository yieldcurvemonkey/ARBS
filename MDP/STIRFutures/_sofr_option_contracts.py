from __future__ import annotations

import datetime
import math
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import QuantLib as ql

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts

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
    "SFR": "SFR",
    "SR3": "SFR",
    "SQ": "SFR",
    "SER": "SER",
    "SR1": "SER",
    "SL": "SER",
    "FF": "FF",
    "ZQ": "FF",
    "QZ": "FF",
    "0Q": "0Q",
    "2Q": "2Q",
    "3Q": "3Q",
    "4Q": "4Q",
    "5Q": "5Q",
    "S0": "0Q",
    "S2": "2Q",
    "S3": "3Q",
    "S4": "4Q",
    "S5": "5Q",
    "UHOA": "UHOA",
    "UMOA": "UMOA",
    "UUOA": "UUOA",
    "UZOA": "UZOA",
    "VHTA": "VHTA",
    "VMTA": "VMTA",
    "VUTA": "VUTA",
    "VZTA": "VZTA",
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
_ROOT_TOKEN_PATTERN = "|".join(sorted([re.escape(r) for r in _ROOT_ALIAS_MAP.keys()], key=len, reverse=True))
_FUTURE_RE = re.compile(rf"^(?P<root>{_ROOT_TOKEN_PATTERN})(?P<code>[FGHJKMNQUVXZ]\d{{2}})$", re.IGNORECASE)
_CM_RE = re.compile(rf"^(?P<root>{_ROOT_TOKEN_PATTERN})?CM(?P<rank>\d+)$", re.IGNORECASE)


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


def _contract_month_distance(contract: str, as_of: datetime.date) -> Optional[int]:
    m = _FUTURE_RE.fullmatch((contract or "").strip().upper())
    if m is None:
        return None
    code = str(m.group("code")).upper()
    month = _MONTH_CODE_TO_NUM[code[0]]
    year = 2000 + int(code[1:])
    return (year - as_of.year) * 12 + (month - as_of.month)


def _front_sfr_option_contracts(as_of: datetime.date) -> List[str]:
    serial_months = [m for m in range(1, 13) if m not in _QUARTERLY_MONTHS]
    serials = _next_contracts(
        start_date=as_of,
        prefix="SFR",
        count=4,
        valid_months=serial_months,
    )
    quarterlies = _next_contracts(
        start_date=as_of,
        prefix="SFR",
        count=4,
        valid_months=_QUARTERLY_MONTHS,
        cutoff_fn=_imm_cutoff,
    )
    return list(dict.fromkeys([*serials, *quarterlies]))


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
        fine_step = 0.0625 if str(contract).strip().upper() in set(_front_sfr_option_contracts(as_of)) else 0.125
    else:
        fine_step = 0.125

    return {
        "fine_step": float(fine_step),
        "coarse_step": 0.25,
        "fine_range": 1.5,
        "coarse_range": 5.5,
    }


def _strike_ladder(center: float, step: float, half_width_steps: int) -> List[float]:
    return [round(float(center) + i * float(step), 8) for i in range(-half_width_steps, half_width_steps + 1)]


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
        raise ValueError(f"No listed strike rule available for offset-based strike snapping on {contract}")

    atm_strike = float(grid["atm_strike"])
    listed_strikes = [float(s) for s in grid["strikes"]]
    right_token = str(right or "").strip().upper()
    if right_token not in {"C", "P"}:
        raise ValueError(f"Unsupported option right for offset strike snapping: {right}")

    target_signed_offset = float(offset_bps)
    if right_token == "C" and target_signed_offset < 0.0:
        target_signed_offset = abs(target_signed_offset)
    if right_token == "P" and target_signed_offset > 0.0:
        target_signed_offset = -abs(target_signed_offset)

    side_candidates = (
        [strike for strike in listed_strikes if strike <= atm_strike + 1e-12]
        if right_token == "C"
        else [strike for strike in listed_strikes if strike >= atm_strike - 1e-12]
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
        contract = spec.get("contract")
        if not contract:
            raise ValueError(f"Missing explicit contract in spec: {spec}")
        return str(contract)
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
        year_offset, fixed_month = _UNDERLYING_RULES.get(root, (0, None))
        if fixed_month:
            ul_month = fixed_month
            ul_year = opt_year + year_offset
        else:
            base_month, base_year = _next_quarterly_code(opt_month, opt_year)
            ul_month = base_month
            ul_year = base_year + year_offset
        return f"SFR{ul_month}{ul_year % 100:02d}"

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
            signed_offset = offset_bps if right == "C" else -offset_bps
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
            right = "C" if price_sign == "-" else "P"
            signed_offset = offset_bps if right == "C" else -offset_bps
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
    future = token.split("|", 1)[0]
    return _contract_to_barchart_contract(future)


def _canonical_to_barchart_option(symbol: str) -> str:
    token = _norm_option_symbol(symbol)
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
    dt_val = datetime.datetime.fromordinal(serial + 693594)
    return dt_val.date()


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


def quarterly_contract_expiry_date(contract: str) -> datetime.date:
    token = (contract or "").strip().upper()
    m = _FUTURE_RE.fullmatch(token)
    if m is None:
        raise ValueError(f"Invalid futures contract token: {contract}")
    return _contract_expiry_date(m.group("code"))


def next_quarterly_contract(contract: str) -> str:
    token = (contract or "").strip().upper()
    m = _FUTURE_RE.fullmatch(token)
    if m is None:
        raise ValueError(f"Invalid futures contract token: {contract}")
    root = _ROOT_ALIAS_MAP[m.group("root").upper()]
    code = m.group("code").upper()
    month_num = _MONTH_CODE_TO_NUM[code[0]]
    year = 2000 + int(code[1:])
    current_idx = _QUARTERLY_MONTHS.index(month_num)
    next_idx = current_idx + 1
    next_year = year
    if next_idx >= len(_QUARTERLY_MONTHS):
        next_idx = 0
        next_year += 1
    next_month = _QUARTERLY_MONTHS[next_idx]
    return f"{root}{_NUM_TO_MONTH_CODE[next_month]}{next_year % 100:02d}"


def quarterly_reference_window(contract: str) -> Tuple[datetime.date, datetime.date]:
    start = quarterly_contract_expiry_date(contract)
    end = quarterly_contract_expiry_date(next_quarterly_contract(contract))
    return start, end


def resolve_quarterly_contracts(as_of: datetime.date, *, start_index: int, count: int, root: str = "SFR") -> List[str]:
    if start_index < 0:
        raise ValueError(f"start_index must be >= 0, got {start_index}")
    if count < 0:
        raise ValueError(f"count must be >= 0, got {count}")
    contracts = _next_contracts(
        start_date=as_of,
        prefix=_ROOT_ALIAS_MAP[root.upper()],
        count=max(start_index + count, 1),
        valid_months=_QUARTERLY_MONTHS,
        cutoff_fn=_imm_cutoff,
    )
    return list(contracts[start_index:start_index + count])


__all__ = [
    "_canonical_contract",
    "_canonical_to_barchart_contract",
    "_canonical_to_barchart_option",
    "_canonical_underlying",
    "_cme_listed_abs_offset_grid_bps_for_contract_forward",
    "_cme_listed_strike_rule_for_contract",
    "_contract_code_from_symbol",
    "_contract_expiry_date",
    "_contract_to_barchart_contract",
    "_decode_sofr_style_strike_token",
    "_expand_straddle_symbol",
    "_format_strike4",
    "_is_sofr_style_option_contract",
    "_norm_option_symbol",
    "_option_contract_to_underlying_contract",
    "_parse_contract_token",
    "_parse_option_request_symbol",
    "_resolve_cm_contract",
    "_resolve_contract_from_spec",
    "_resolve_option_contract_aliases_for_date",
    "_right_from_symbol",
    "_right_word_to_token",
    "_snap_to_listed_strike_for_offset",
    "_strike_from_symbol",
    "_to_float",
    "next_quarterly_contract",
    "quarterly_contract_expiry_date",
    "quarterly_reference_window",
    "resolve_quarterly_contracts",
]
