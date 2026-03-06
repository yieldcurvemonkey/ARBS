from enum import Enum


class QuikVolTermStructureEventTarget(Enum):
    SR3 = "a#ctl00_SubNav_PGMenu_lvGroups_ctrl0_lbGroup"
    S0 = "a#ctl00_SubNav_PGMenu_lvGroups_ctrl1_lbGroup" 
    S2 = "a#ctl00_SubNav_PGMenu_lvGroups_ctrl2_lbGroup"
    S3 = "a#ctl00_SubNav_PGMenu_lvGroups_ctrl3_lbGroup"
    S4 = "a#ctl00_SubNav_PGMenu_lvGroups_ctrl4_lbGroup"
    S5 = "a#ctl00_SubNav_PGMenu_lvGroups_ctrl5_lbGroup"
    UL = None
    US = None
    TN = None
    TY = None
    FV = None
    TU = None
    ZQ = None
    