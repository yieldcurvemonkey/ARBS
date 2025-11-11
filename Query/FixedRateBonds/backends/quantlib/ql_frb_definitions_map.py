# ABOUTME: Maps bond identifiers to QuantLib-specific market conventions and parameters
# ABOUTME: Defines calendars, day counters, frequencies for fixed rate bond pricing with QuantLib backend
from typing import Dict
import QuantLib as ql

from definitions.FixedRateBonds import FRB_DEFINITIONS

QUANTLIB_FRB_DEFINITIONS: Dict[str, Dict[str, ql.SwapIndex | bool | ql.DayCounter | ql.Calendar | int | int | ql.Period | ql.Currency | int | int]] = {
    "USTS": {
        "NotionalCurrency": ql.USDCurrency(),
        "DayCounter": ql.ActualActual(ql.ActualActual.ISMA),
        "Calendar": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        "BusinessConvention": ql.ModifiedFollowing,
        "Frequency": ql.Semiannual,
        "FrequencyPeriod": ql.Period(6, ql.Months),
        "SettlementDays": 1,
        "Redemption": 100,
        "Compounded": ql.Compounded
    } 
}


for k in QUANTLIB_FRB_DEFINITIONS.keys():
    assert k in FRB_DEFINITIONS, f"key {k} in 'QUANTLIB_FRB_DEFINITIONS' must exist in global 'FRB_DEFINITIONS'"
