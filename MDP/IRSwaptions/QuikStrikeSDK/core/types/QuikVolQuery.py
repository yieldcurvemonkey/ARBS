from dataclasses import dataclass
from typing import Optional, Literal

from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolValueType import QuikVolValueType


@dataclass
class QuikVolQuery:
    globex_symbol: str
    qv_value_type: Optional[QuikVolValueType] = QuikVolValueType.ABPV # NVOL
    delta: Optional[int] = 0
    strike: Optional[float] = 0
    option_type: Optional[Literal["Call", "Put", "Straddle"]] = "Straddle"