from enum import Enum, auto


class SpreadStructure(Enum):
    OUTRIGHT = auto()
    CURVE = auto()
    FLY = auto()
