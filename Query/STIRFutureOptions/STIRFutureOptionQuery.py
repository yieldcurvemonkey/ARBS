from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Union

from Query.Base.BaseQuery import BaseQuery
from Query.STIRFutureOptions import adapter as _stirfo_adapter  # noqa: F401
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue


def _split_two_symbols(symbol: Optional[str]) -> Optional[Tuple[str, str]]:
    if symbol is None:
        return None
    token = symbol.strip()
    if not token:
        return None
    match = re.split(r"\s+v\s+|\s+V\s+|\+", token)
    if len(match) == 2:
        return match[0].strip(), match[1].strip()
    return None


@dataclass(frozen=True)
class STIRFutureOptionQuery(BaseQuery):
    structure: STIRFutureOptionStructure = STIRFutureOptionStructure.OUTRIGHT
    value: Union[STIRFutureOptionValue, List[STIRFutureOptionValue]] = STIRFutureOptionValue.PRICE

    symbol: Optional[str] = None
    contracts: Optional[float] = None
    dv01: Optional[float] = None
    gamma_01: Optional[float] = None
    vega_01: Optional[float] = None
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="STIRFUTUREOPTION")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "STIRFUTUREOPTION")
        object.__setattr__(self, "structure_id", self.structure)

        skw: Dict[str, Any] = dict(self.structure_kwargs or {})
        if skw.get("premium") is None and skw.get("upfront") is not None:
            skw["premium"] = skw["upfront"]
        if skw.get("premiums") is None and skw.get("upfronts") is not None:
            skw["premiums"] = skw["upfronts"]
        if self.symbol is not None and "symbol" not in skw:
            skw["symbol"] = self.symbol
        if self.contracts is not None and "contracts" not in skw:
            skw["contracts"] = self.contracts
        if self.dv01 is not None and "dv01" not in skw:
            skw["dv01"] = self.dv01
        if self.gamma_01 is not None and "gamma_01" not in skw:
            skw["gamma_01"] = self.gamma_01
        if self.vega_01 is not None and "vega_01" not in skw:
            skw["vega_01"] = self.vega_01

        size_targets = [name for name in ("contracts", "dv01", "gamma_01", "vega_01") if skw.get(name) is not None]
        if len(size_targets) > 1:
            raise ValueError(f"Specify only one STIR option size target, got: {', '.join(size_targets)}")

        if self.structure == STIRFutureOptionStructure.OUTRIGHT:
            assert skw.get("symbol") is not None, "OUTRIGHT requires symbol"
        elif self.structure == STIRFutureOptionStructure.VERTICAL:
            symbols = skw.get("symbols")
            if isinstance(symbols, (list, tuple)) and len(symbols) >= 2:
                skw.setdefault("long_symbol", symbols[0])
                skw.setdefault("short_symbol", symbols[1])
            if (skw.get("long_symbol") is None or skw.get("short_symbol") is None) and skw.get("symbol"):
                maybe = _split_two_symbols(skw.get("symbol"))
                if maybe is not None:
                    skw.setdefault("long_symbol", maybe[0])
                    skw.setdefault("short_symbol", maybe[1])
            assert skw.get("long_symbol") is not None and skw.get("short_symbol") is not None, "VERTICAL requires long_symbol and short_symbol"
            skw.setdefault("risk_weights", [1.0, -1.0])
        elif self.structure == STIRFutureOptionStructure.STRADDLE:
            if skw.get("symbol") is not None:
                pass
            else:
                symbols = skw.get("symbols")
                if isinstance(symbols, (list, tuple)) and len(symbols) >= 2:
                    skw.setdefault("call_symbol", symbols[0])
                    skw.setdefault("put_symbol", symbols[1])
                assert skw.get("call_symbol") is not None and skw.get("put_symbol") is not None, "STRADDLE requires symbol or call_symbol+put_symbol"
            skw.setdefault("risk_weights", [1.0, 1.0])

        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        mr.setdefault("endpoint", "option_snapshot")
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["STIRFutureOptionQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        skw = self.structure_kwargs or {}
        val = self.value.name if not isinstance(self.value, list) else "MULTI"
        if self.structure == STIRFutureOptionStructure.OUTRIGHT:
            return f"{skw.get('symbol','')} {self.structure.name} {val}".strip()
        if self.structure == STIRFutureOptionStructure.VERTICAL:
            return f"{skw.get('long_symbol','')}v{skw.get('short_symbol','')} {self.structure.name} {val}".strip()
        if skw.get("symbol"):
            return f"{skw.get('symbol')} {self.structure.name} {val}".strip()
        return f"{skw.get('call_symbol','')}+{skw.get('put_symbol','')} {self.structure.name} {val}".strip()

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return col

    def build_mdp_request(self, now: datetime.datetime = None) -> Dict[str, Any]:
        if now is None:
            assert self.market_request["timestamp"] is not None, "must pass in timestamp in market request"
            now = datetime.date.today() if str(self.market_request["timestamp"]).lower() == "live" else self.market_request["timestamp"] 

        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = now.date()
        elif req[self.mdp_time_key] == "now":
            req[self.mdp_time_key] = now

        skw = self.structure_kwargs or {}
        symbols: List[str] = []
        for key in ("symbol", "long_symbol", "short_symbol", "call_symbol", "put_symbol", "symbols"):
            val = skw.get(key)
            if not val:
                continue
            if isinstance(val, (list, tuple)):
                symbols.extend([str(x) for x in val])
            else:
                symbols.append(str(val))

        if symbols:
            req["symbols"] = symbols

        req.setdefault("endpoint", "option_snapshot")
        return req

    def default_mtm_value_id(self):
        return STIRFutureOptionValue.PRICE
