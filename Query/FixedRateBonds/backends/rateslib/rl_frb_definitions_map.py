# ABOUTME: Maps bond identifiers to rateslib-specific market conventions and parameters
# ABOUTME: Defines instrument specifications for fixed rate bond pricing with rateslib backend
from typing import Dict

from definitions.FixedRateBonds import FRB_DEFINITIONS

RATESLIB_FRB_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "USTS": {
        "spec": "us_gb_tsy"
    } 
}


for k in RATESLIB_FRB_DEFINITIONS.keys():
    assert k in FRB_DEFINITIONS, f"key {k} in 'RATESLIB_FRB_DEFINITIONS' must exist in global 'FRB_DEFINITIONS'"