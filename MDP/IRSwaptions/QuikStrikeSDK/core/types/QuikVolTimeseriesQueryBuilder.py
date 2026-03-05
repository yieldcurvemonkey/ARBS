from typing import Optional

from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolValueType import QuikVolValueType


class QuikVolTimeseriesQueryBuilder:

    @staticmethod
    def build_elements_dict(globex_symbol: str, qv_value_type: QuikVolValueType, delta: Optional[int] = 0, strike: Optional[float] = 0):
        value_type_num, value_type_keys = qv_value_type.value
        assert (delta or strike) or qv_value_type in [
            QuikVolValueType.ATM,
            QuikVolValueType.ATMPrice,
            QuikVolValueType.ABPV,
            QuikVolValueType.DBPV,
            QuikVolValueType.Shift,
            QuikVolValueType.Slide,
            QuikVolValueType.Future,
            QuikVolValueType.Return,
        ], "BAD ELEMENT PARAMS - MUST SPECIFICY DELTA OR STRIKE, or BE AN ATM QUERY"

        curr_element = {
            "Quantity": 1,
            "Symbol": globex_symbol,
            "ProductId": QuikVolProductID[globex_symbol[:-3]].value.underlying_pid,
            "ValueType": value_type_num,
            "Delta": delta,
            "Strike": strike,
            "StrikeFormat": "{0:0.####;;0}" if qv_value_type in [QuikVolValueType.VolByStrike] else "{0:N4}" ,
        }
        for k in value_type_keys:
            curr_element[k] = True

        return {"Elements": [curr_element]}
