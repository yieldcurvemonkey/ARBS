import re
from typing import Any, Optional

from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID


class QuikVolTimeseriesQueryBuilder:

    @staticmethod
    def _product_root(globex_symbol: str) -> str:
        sym = str(globex_symbol or "").strip().upper()
        if not sym:
            raise KeyError(globex_symbol)
        if "_" in sym:
            return sym.split("_", 1)[0]
        m_cm = re.fullmatch(r"(?P<root>[A-Z0-9]+)CM\d+", sym)
        if m_cm is not None:
            return str(m_cm.group("root"))
        m_listed = re.fullmatch(r"(?P<root>[A-Z0-9]+)[FGHJKMNQUVXZ]\d{1,2}", sym)
        if m_listed is not None:
            return str(m_listed.group("root"))
        return sym[:-3] if len(sym) > 3 else sym

    @staticmethod
    def build_elements_dict(globex_symbol: str, qv_value_type: Any, delta: Optional[int] = 0, strike: Optional[float] = 0):
        value_type_num, value_type_keys = qv_value_type.value
        vt_name = str(getattr(qv_value_type, "name", qv_value_type)).upper()
        zero_param_ok = {
            "ATM",
            "ATMPRICE",
            "ABPV",
            "DBPV",
            "SHIFT",
            "SLIDE",
            "FUTURE",
            "RETURN",
        }
        assert (delta or strike) or vt_name in zero_param_ok, "BAD ELEMENT PARAMS - MUST SPECIFICY DELTA OR STRIKE, or BE AN ATM QUERY"

        curr_element = {
            "Quantity": 1,
            "Symbol": globex_symbol,
            "ProductId": QuikVolProductID[QuikVolTimeseriesQueryBuilder._product_root(globex_symbol)].value.underlying_pid,
            "ValueType": value_type_num,
            "Delta": delta,
            "Strike": strike,
            "StrikeFormat": "{0:0.####;;0}" if vt_name == "VOLBYSTRIKE" else "{0:N4}",
        }
        for k in value_type_keys:
            curr_element[k] = True

        return {"Elements": [curr_element]}
