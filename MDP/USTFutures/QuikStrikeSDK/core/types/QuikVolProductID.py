from enum import Enum
from dataclasses import dataclass

from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolCalulatorEventTarget import QuikVolCalulatorAssetClassEventTarget, QuikVolCalulatorContractEventTarget
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolTermStructureEventTarget import QuikVolTermStructureEventTarget


@dataclass
class _QuikVolProductIDValue:
    underlying_pid: int
    calculator_asset_class_event_target: str
    calculator_underlying_contract_event_target: str
    latest_atm_term_structure_event_target: str


class QuikVolProductID(Enum):
    # SOFR Complex
    # TODO add term midcurves
    SR3 = _QuikVolProductIDValue(
        underlying_pid=362,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.SR3.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.SR3.value,
    )  #  3-Month SOFR Futures, Standard Quarterly/Serial Options
    S0 = _QuikVolProductIDValue(
        underlying_pid=362,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.SR3.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.S0.value,
    )  # 1Y Mid-Curve Options
    S2 = _QuikVolProductIDValue(
        underlying_pid=362,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.SR3.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.S2.value,
    )  # 2Y Mid-Curve Options
    S3 = _QuikVolProductIDValue(
        underlying_pid=362,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.SR3.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.S3.value,
    )  # 3Y Mid-Curve Options
    S4 = _QuikVolProductIDValue(
        underlying_pid=362,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.SR3.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.S5.value,
    )  # 4Y Mid-Curve Options
    S5 = _QuikVolProductIDValue(
        underlying_pid=362,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.SR3.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.S5.value,
    )  # 5Y Mid-Curve Options

    # USTs
    TU = _QuikVolProductIDValue(
        underlying_pid=5,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.TU.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.TU.value,
    )  # 2‑Year U.S. Treasury Note Futures
    FV = _QuikVolProductIDValue(
        underlying_pid=4,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.FV.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.FV.value,
    )  # 5‑Year U.S. Treasury Note Futures
    TY = _QuikVolProductIDValue(
        underlying_pid=3,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.TY.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.TY.value,
    )  # 10‑Year U.S. Treasury Note Futures
    US = _QuikVolProductIDValue(
        underlying_pid=2,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=QuikVolCalulatorContractEventTarget.US.value,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.US.value,
    )  # U.S. Treasury Bond Futures
    UL = _QuikVolProductIDValue(
        underlying_pid=16,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=None,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.UL.value,
    )  # Ultra 30-Year U.S. Treasury Bond Futures
    OTN = _QuikVolProductIDValue(
        underlying_pid=401,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Rates.value,
        calculator_underlying_contract_event_target=None,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.TN.value,
    )  # Ultra 10-Year U.S. Treasury Note Futures
    TN = OTN
    TNO = OTN

    # Energy
    CL = _QuikVolProductIDValue(
        underlying_pid=5,
        calculator_asset_class_event_target=QuikVolCalulatorAssetClassEventTarget.Energy.value,
        calculator_underlying_contract_event_target=None,
        latest_atm_term_structure_event_target=QuikVolTermStructureEventTarget.TU.value,
    ) # WTI 

    # SR1 = 361  # 1‑Month SOFR Futures
    # ZQ = 6  # Federal Funds Futures
    # US = 2  # 30‑Year U.S. Treasury Bond Futures
    # UL = 16  # Ultra 30‑Year U.S. Treasury Bond Futures
    # TY = 3  # 10‑Year U.S. Treasury Note Futures
    # FV = 4  # 5‑Year U.S. Treasury Note Futures
    # TN = 401  # Ultra 10 U.S. Treasury Note Futures
