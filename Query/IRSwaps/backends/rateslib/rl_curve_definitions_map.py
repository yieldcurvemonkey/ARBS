from typing import Dict
import rateslib as rl

from definitions.IRSwaps import CURVE_DEFINITIONS

RATESLIB_CURVE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "USD-SOFR-1D": {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": "usd_irs",
        "ReferenceRate2": "usd_stir",
        "ReferenceRate3": "usd_stir1",
        "NotionalCurrency": "usd",
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": "days",
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": "act360",
        "Calendar": "nyc",
        "BusinessConvention": "mf",
        "PaymentFrequency": "1y",
        "PaymentLag": 2,
        "SettlementDays": 2,
        "SDR_UPIs": ["QZXQ4R16245X", "QZPB5VSBGRCD"],
    },
}

for k in RATESLIB_CURVE_DEFINITIONS.keys():
    assert k in CURVE_DEFINITIONS, f"key {k} in 'RATESLIB_CURVE_DEFINITIONS' must exist in global 'CURVE_DEFINITIONS'"
