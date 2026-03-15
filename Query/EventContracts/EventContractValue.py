from enum import Enum, auto

class EventContractValue(Enum):
    PRICE = auto()
    PROBABILITY = auto()
    VOLUME = auto()
    OPEN_INTEREST = auto()
    MARKET_IMPACT_AVG_PRICE = auto()
    MARKET_IMPACT_SLIPPAGE = auto()
    MARKET_IMPACT_TOTAL_COST = auto()
