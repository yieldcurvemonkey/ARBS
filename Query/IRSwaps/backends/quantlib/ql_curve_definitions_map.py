from typing import Dict
import QuantLib as ql

from definitions.IRSwaps import CURVE_DEFINITIONS

QUANTLIB_CURVE_DEFINITIONS: Dict[str, Dict[str, ql.SwapIndex | bool | ql.DayCounter | ql.Calendar | int | int | ql.Period | ql.Currency | int | int]] = {
    "USD-SOFR-1D": {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": ql.Sofr,
        "NotionalCurrency": ql.USDCurrency(),
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": ql.Days,
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": ql.Actual360(),
        "Calendar": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        "BusinessConvention": ql.ModifiedFollowing,
        "PaymentFrequency": ql.Annual,
        "PaymentLag": 2,
        "SettlementDays": 2,
        "SDR_UPIs": ["QZXQ4R16245X", "QZPB5VSBGRCD"],
    },
    "USD-FEDFUNDS": {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": ql.FedFunds,
        "NotionalCurrency": ql.USDCurrency(),
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": ql.Days,
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": ql.Actual360(),
        "Calendar": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        "BusinessConvention": ql.ModifiedFollowing,
        "PaymentFrequency": ql.Annual,
        "PaymentLag": 2,
        "SettlementDays": 2,
        "SDR_UPIs": ["QZFF9TXNNM7X", "QZ7HZS5V2LQS"],
    },
    "USD-OIS": {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": ql.FedFunds,
        "NotionalCurrency": ql.USDCurrency(),
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": ql.Days,
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": ql.Actual360(),
        "Calendar": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        "BusinessConvention": ql.ModifiedFollowing,
        "PaymentFrequency": ql.Annual,
        "PaymentLag": 2,
        "SettlementDays": 2,
        "SDR_UPIs": ["QZFF9TXNNM7X", "QZ7HZS5V2LQS"],
    },
}

for k in QUANTLIB_CURVE_DEFINITIONS.keys():
    assert k in CURVE_DEFINITIONS, f"key {k} in 'QUANTLIB_CURVE_DEFINITIONS' must exist in global 'CURVE_DEFINITIONS'"
