from enum import Enum, auto


class SpreadValue(Enum):
    SPREAD_BPS = auto()
    SPREAD_RATE = auto()
    LEG_A_RATE = auto()
    LEG_B_RATE = auto()
    PV01 = auto()
    NPV = auto()
    CVX_ADJ_EMPIRICAL = auto()
    CVX_ADJ_HW1F = auto()
