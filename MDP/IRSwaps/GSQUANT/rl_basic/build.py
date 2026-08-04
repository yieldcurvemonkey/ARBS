import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import pandas as pd
import rateslib as rl

from gs_quant.data import Dataset
from gs_quant.session import GsSession

from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS


# fmt: off
GSQUANT_CURVE_MAP = {
    "USD-SOFR-1D": {
        "rl_basic": {
            "base_tenors": [
                "USD Swap SOFR ATM frb1 to frb2 LCH Cleared",
                "USD Swap SOFR ATM frb2 to frb3 LCH Cleared",
                "USD Swap SOFR ATM frb3 to frb4 LCH Cleared",
                "USD Swap SOFR ATM frb4 to frb5 LCH Cleared",
                "USD Swap SOFR ATM frb5 to frb6 LCH Cleared",
                "USD Swap SOFR ATM frb6 to frb7 LCH Cleared",
                
                "USD Swap SOFR 3m ATM imm1 to 3m LCH Cleared",
                "USD Swap SOFR 3m ATM imm2 to 3m LCH Cleared",
                "USD Swap SOFR 3m ATM imm3 to 3m LCH Cleared",
                "USD Swap SOFR 3m ATM imm4 to 3m LCH Cleared",

                "USD Swap SOFR 6m ATM imm1 to 6m LCH Cleared",
                "USD Swap SOFR 6m ATM imm2 to 6m LCH Cleared",
                "USD Swap SOFR 6m ATM imm3 to 6m LCH Cleared",
                "USD Swap SOFR 6m ATM imm4 to 6m LCH Cleared",
                
                "USD Swap SOFR 1y ATM 0b to 2y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 3y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 4y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 5y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 6y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 7y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 8y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 9y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 10y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 12y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 15y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 20y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 25y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 30y LCH Cleared",
            ],
            "knots": [
                "USD Swap SOFR 1y ATM 0b to 2y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 3y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 4y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 5y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 6y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 7y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 8y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 9y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 10y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 12y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 15y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 20y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 25y LCH Cleared",
                "USD Swap SOFR 1y ATM 0b to 30y LCH Cleared",
            ],
            "extrapolation": datetime.timedelta(days=365 * 20),
            "reference_key": "USD-SOFR-1D",
        }
    },
    "USD-OIS": {
        "rl_basic": {
            "base_tenors": [
                "USD Swap OIS ATM frb1 to frb2 LCH Cleared",
                "USD Swap OIS ATM frb2 to frb3 LCH Cleared",
                "USD Swap OIS ATM frb3 to frb4 LCH Cleared",
                "USD Swap OIS ATM frb4 to frb5 LCH Cleared",
                "USD Swap OIS ATM frb5 to frb6 LCH Cleared",
                "USD Swap OIS ATM frb6 to frb7 LCH Cleared",
                
                # "USD Swap OIS 3m ATM imm1 to 3m LCH Cleared",
                # "USD Swap OIS 3m ATM imm2 to 3m LCH Cleared",
                # "USD Swap OIS 3m ATM imm3 to 3m LCH Cleared",
                # "USD Swap OIS 3m ATM imm4 to 3m LCH Cleared",

                # "USD Swap OIS 6m ATM imm1 to 6m LCH Cleared",
                # "USD Swap OIS 6m ATM imm2 to 6m LCH Cleared",
                # "USD Swap OIS 6m ATM imm3 to 6m LCH Cleared",
                # "USD Swap OIS 6m ATM imm4 to 6m LCH Cleared",
                
                "USD Swap OIS 1y ATM 0b to 1y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 2y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 3y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 4y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 5y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 6y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 7y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 8y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 9y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 10y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 12y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 15y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 20y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 25y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 30y LCH Cleared",
            ],
            "knots": [
                "USD Swap OIS 1y ATM 0b to 2y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 3y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 4y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 5y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 6y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 7y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 8y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 9y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 10y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 12y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 15y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 20y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 25y LCH Cleared",
                "USD Swap OIS 1y ATM 0b to 30y LCH Cleared",
            ],
            "extrapolation": datetime.timedelta(days=365 * 20),
            "reference_key": "USD-OIS",
        }
    },
    "USD-OIS-STIR-LCH": {
        "rl_basic": {
            "base_tenors": [
                "USD Swap OIS ATM frb1 to frb2 LCH Cleared",
                "USD Swap OIS ATM frb2 to frb3 LCH Cleared",
                "USD Swap OIS ATM frb3 to frb4 LCH Cleared",
                "USD Swap OIS ATM frb4 to frb5 LCH Cleared",
                "USD Swap OIS ATM frb5 to frb6 LCH Cleared",
                "USD Swap OIS ATM frb6 to frb7 LCH Cleared",
                
                "USD Swap OIS 3m ATM imm1 to 3m LCH Cleared",
                "USD Swap OIS 3m ATM imm2 to 3m LCH Cleared",
                "USD Swap OIS 3m ATM imm3 to 3m LCH Cleared",
                "USD Swap OIS 3m ATM imm4 to 3m LCH Cleared",

                "USD Swap OIS 6m ATM imm1 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm2 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm3 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm4 to 6m LCH Cleared",
                
                # "USD Swap OIS 1y ATM 0b to 1y LCH Cleared",
                "USD Swap OIS 1y ATM 1y to 1y LCH Cleared",
                "USD Swap OIS 1y ATM 2y to 1y LCH Cleared",
                "USD Swap OIS 1y ATM 3y to 1y LCH Cleared",
            ],
            "knots": [
                # "USD Swap OIS 6m ATM imm2 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm3 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm4 to 6m LCH Cleared",
                
                # "USD Swap OIS 1y ATM 0b to 1y LCH Cleared",
                "USD Swap OIS 1y ATM 1y to 1y LCH Cleared",
                "USD Swap OIS 1y ATM 2y to 1y LCH Cleared",
                "USD Swap OIS 1y ATM 3y to 1y LCH Cleared",
            ],
            "extrapolation": datetime.timedelta(days=360 * 1.25),
            "reference_key": "USD-OIS-STIR"
        }
    },
    "USD-SOFR-1D-STIR-CME": {
        "rl_basic": {
            "base_tenors": [
                "USD Swap SOFR 1m ATM 0b to 1m CME Cleared",
                "USD Swap SOFR 2m ATM 0b to 2m CME Cleared",
                "USD Swap SOFR 3m ATM 0b to 3m CME Cleared",
                "USD Swap SOFR 6m ATM 0b to 6m CME Cleared",
                "USD Swap SOFR 9m ATM 0b to 9m CME Cleared",

                "USD Swap SOFR ATM frb1 to frb2 CME Cleared",
                "USD Swap SOFR ATM frb2 to frb3 CME Cleared",
                "USD Swap SOFR ATM frb3 to frb4 CME Cleared",
                "USD Swap SOFR ATM frb4 to frb5 CME Cleared",
                "USD Swap SOFR ATM frb5 to frb6 CME Cleared",
                "USD Swap SOFR ATM frb6 to frb7 CME Cleared",

                "USD Swap SOFR 3m ATM imm1 to 3m CME Cleared",
                "USD Swap SOFR 3m ATM imm2 to 3m CME Cleared",
                "USD Swap SOFR 3m ATM imm3 to 3m CME Cleared",
                "USD Swap SOFR 3m ATM imm4 to 3m CME Cleared",

                "USD Swap SOFR 6m ATM imm1 to 6m CME Cleared",
                "USD Swap SOFR 6m ATM imm2 to 6m CME Cleared",
                "USD Swap SOFR 6m ATM imm3 to 6m CME Cleared",
                "USD Swap SOFR 6m ATM imm4 to 6m CME Cleared",
                
                "USD Swap SOFR 1y ATM 0b to 1y CME Cleared",
                "USD Swap SOFR 1y ATM 0b to 2y CME Cleared",
                "USD Swap SOFR 1y ATM 0b to 3y CME Cleared",

                "USD Swap SOFR 1y ATM imm1 to 1y CME Cleared",
                "USD Swap SOFR 1y ATM imm1 to 2y CME Cleared",
                
                "USD Swap SOFR 1y ATM imm2 to 1y CME Cleared",
                "USD Swap SOFR 1y ATM imm2 to 2y CME Cleared",
                
                "USD Swap SOFR 1y ATM imm3 to 1y CME Cleared",
                "USD Swap SOFR 1y ATM imm3 to 2y CME Cleared",
                
                "USD Swap SOFR 1y ATM imm4 to 1y CME Cleared",
                "USD Swap SOFR 1y ATM imm4 to 2y CME Cleared",
                
                "USD Swap SOFR 1y ATM 1y to 1y CME Cleared",
                "USD Swap SOFR 1y ATM 2y to 1y CME Cleared",
                "USD Swap SOFR 1y ATM 1y to 2y CME Cleared",
            ],
            "reference_key": "USD-SOFR-1D",
        }
    }, 
    "EUR-ESTR": {
        "rl_basic": {
            "base_tenors": [
                "EUR Swap EuroSTR ATM ecb1 to ecb2 LCH Cleared",
                "EUR Swap EuroSTR ATM ecb2 to ecb3 LCH Cleared",
                "EUR Swap EuroSTR ATM ecb3 to ecb4 LCH Cleared",
                "EUR Swap EuroSTR ATM ecb4 to ecb5 LCH Cleared",
                "EUR Swap EuroSTR ATM ecb5 to ecb6 LCH Cleared",
                "EUR Swap EuroSTR ATM ecb6 to ecb7 LCH Cleared",
                
                "EUR Swap EuroSTR 3m ATM imm1 to 3m LCH Cleared",
                "EUR Swap EuroSTR 3m ATM imm2 to 3m LCH Cleared",
                "EUR Swap EuroSTR 3m ATM imm3 to 3m LCH Cleared",
                "EUR Swap EuroSTR 3m ATM imm4 to 3m LCH Cleared",

                "EUR Swap EuroSTR 6m ATM imm1 to 6m LCH Cleared",
                "EUR Swap EuroSTR 6m ATM imm2 to 6m LCH Cleared",
                "EUR Swap EuroSTR 6m ATM imm3 to 6m LCH Cleared",
                "EUR Swap EuroSTR 6m ATM imm4 to 6m LCH Cleared",
                
                "EUR Swap EuroSTR 1y ATM 0b to 2y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 3y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 5y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 10y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 30y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 35y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 40y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 45y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 50y LCH Cleared",
            ],
            "knots": [
                "EUR Swap EuroSTR 1y ATM 0b to 2y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 3y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 5y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 10y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 30y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 35y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 40y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 45y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 50y LCH Cleared",
            ],
            "extrapolation": datetime.timedelta(days=365 * 20),
            "reference_key": "EUR-ESTR"
        }
    },
    "JPY-TONAR": {
        "rl_basic": {
            "base_tenors": [
                "JPY Swap JPY-TONA-OIS-COMPOUND 3m ATM imm1 to 3m LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 3m ATM imm2 to 3m LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 3m ATM imm3 to 3m LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 3m ATM imm4 to 3m LCH Cleared",

                "JPY Swap JPY-TONA-OIS-COMPOUND 6m ATM imm1 to 6m LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 6m ATM imm2 to 6m LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 6m ATM imm3 to 6m LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 6m ATM imm4 to 6m LCH Cleared",
                
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 2y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 3y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 5y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 10y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 30y LCH Cleared",
            ],
            "knots": [
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 2y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 3y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 5y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 10y LCH Cleared",
                "JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to 30y LCH Cleared",
            ],
            "extrapolation": datetime.timedelta(days=365 * 10),
            "reference_key": "JPY-TONAR"
        }
    },
    # GBP OIS (SONIA). Instruments verified against
    # COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx: 1-30y plus 35/40/45/50y,
    # every one with historyStartDate 2010-01-04. Meeting-dated MPC front-end
    # instruments (mpc1..mpc7) also exist in that sheet and are included in
    # base_tenors, mirroring EUR-ESTR/USD-OIS's ecb1-7/frb1-7 blocks - but every
    # pair traded off this curve starts >=10y forward, so front-end meeting
    # precision cannot reach them either way, and none of the six MPC segments
    # are curve knots.
    "GBP-SONIA": {
        "rl_basic": {
            "base_tenors": [
                "GBP Swap OIS ATM mpc1 to mpc2 LCH Cleared",
                "GBP Swap OIS ATM mpc2 to mpc3 LCH Cleared",
                "GBP Swap OIS ATM mpc3 to mpc4 LCH Cleared",
                "GBP Swap OIS ATM mpc4 to mpc5 LCH Cleared",
                "GBP Swap OIS ATM mpc5 to mpc6 LCH Cleared",
                "GBP Swap OIS ATM mpc6 to mpc7 LCH Cleared",

                "GBP Swap OIS 1y ATM 0b to 1y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 2y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 3y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 4y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 5y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 6y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 7y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 8y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 9y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 10y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 12y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 15y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 20y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 25y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 30y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 35y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 40y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 45y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 50y LCH Cleared",
            ],
            "knots": [
                "GBP Swap OIS 1y ATM 0b to 2y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 3y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 4y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 5y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 6y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 7y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 8y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 9y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 10y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 12y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 15y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 20y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 25y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 30y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 35y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 40y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 45y LCH Cleared",
                "GBP Swap OIS 1y ATM 0b to 50y LCH Cleared",
            ],
            "extrapolation": datetime.timedelta(days=365 * 20),
            "reference_key": "GBP-SONIA",
        }
    },
}
# fmt: on

_GS_DATASET_NAME = "IR_SWAP_RATES_V1_STANDARD"
_GS_CLIENT_ID = "2eb2f48872304c1d94fa1642fa691afe"
_GS_SECRET_KEY = "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4"
_GS_MAX_FETCH_SPAN_DAYS = 90


def _normalize_gsquant_curve_name(curve: str) -> str:
    return "USD-OIS" if curve == "USD-FEDFUNDS" else curve


def _resolve_gsquant_curve_config(curve: str) -> Tuple[str, Dict[str, Any]]:
    normalized_curve = _normalize_gsquant_curve_name(curve)
    assert normalized_curve in GSQUANT_CURVE_MAP, f"{curve} not defined in 'GSQUANT_CURVE_MAP'"
    curve_cfg = GSQUANT_CURVE_MAP[normalized_curve]["rl_basic"]
    reference_curve_name = curve_cfg["reference_key"]
    assert reference_curve_name in RATESLIB_CURVE_DEFINITIONS, f"{curve} not defined in 'RATESLIB_CURVE_DEFINITIONS'"
    return normalized_curve, curve_cfg


@lru_cache(maxsize=1)
def _ensure_gsquant_session() -> bool:
    GsSession.use(
        client_id=_GS_CLIENT_ID,
        client_secret=_GS_SECRET_KEY,
        scopes=GsSession.Scopes.get_default(),
    )
    return True


@lru_cache(maxsize=1)
def _load_gsquant_coverage() -> pd.DataFrame:
    coverage_path = Path(__file__).resolve().parents[1] / "COVERAGE" / f"{_GS_DATASET_NAME}_COVERAGE.xlsx"
    return pd.read_excel(coverage_path)


def _extract_gsquant_as_of_dates(df: pd.DataFrame) -> pd.Series:
    for col in ("date", "pricingDate", "pricing_date", "as_of", "time", "index"):
        if col in df.columns:
            return pd.to_datetime(df[col], errors="coerce").dt.date
    raise KeyError("Could not infer GSQUANT pricing date column from dataset response.")


def _request_rl_basic_gsquant_dataset(
    *,
    start: datetime.date,
    end: datetime.date,
    asset_ids: Sequence[Any],
) -> pd.DataFrame:
    raw = Dataset(_GS_DATASET_NAME).get_data(
        start=start,
        end=end,
        assetId=list(asset_ids),
    )
    if raw is None:
        return pd.DataFrame()
    return raw.reset_index()


def _fetch_rl_basic_gsquant_dataset_chunked(
    *,
    requested_dates: Sequence[datetime.date],
    asset_ids: Sequence[Any],
) -> pd.DataFrame:
    if not requested_dates:
        return pd.DataFrame()

    chunks = []
    start_idx = 0
    while start_idx < len(requested_dates):
        start_date = requested_dates[start_idx]
        end_idx = start_idx
        while (
            end_idx + 1 < len(requested_dates)
            and (requested_dates[end_idx + 1] - start_date).days <= _GS_MAX_FETCH_SPAN_DAYS
        ):
            end_idx += 1

        chunk_start = start_date
        chunk_end = requested_dates[end_idx]
        chunk_df = _request_rl_basic_gsquant_dataset(
            start=chunk_start,
            end=chunk_end,
            asset_ids=asset_ids,
        )
        if not chunk_df.empty:
            chunks.append(chunk_df)
        start_idx = end_idx + 1

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def _fetch_rl_basic_gsquant_dataset(curve: str, as_of_dates: Sequence[datetime.date]) -> pd.DataFrame:
    requested_dates = sorted({d for d in as_of_dates if isinstance(d, datetime.date)})
    if not requested_dates:
        return pd.DataFrame()

    _, curve_cfg = _resolve_gsquant_curve_config(curve)
    coverage = _load_gsquant_coverage()
    requested_names = set(curve_cfg["base_tenors"])
    coverage_slice = coverage.loc[coverage["name"].isin(requested_names), ["assetId", "name"]].dropna()
    asset_id_to_name = dict(zip(coverage_slice["assetId"], coverage_slice["name"]))

    _ensure_gsquant_session()
    df = _fetch_rl_basic_gsquant_dataset_chunked(
        requested_dates=requested_dates,
        asset_ids=coverage_slice["assetId"].tolist(),
    )
    if df.empty:
        return df

    df["assetId"] = df["assetId"]
    df["tenor"] = df["assetId"].map(asset_id_to_name)
    df["as_of"] = _extract_gsquant_as_of_dates(df)
    df = df[df["as_of"].isin(requested_dates) & df["tenor"].notna()].copy()
    if df.empty:
        return df

    df["effectiveDate"] = pd.to_datetime(df["effectiveDate"], errors="coerce")
    df["terminationDate"] = pd.to_datetime(df["terminationDate"], errors="coerce")
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce") * 100.0
    return df


def _build_rl_basic_gsquant_curve_from_frame(curve: str, as_of: datetime.date, frame: pd.DataFrame):
    normalized_curve, curve_cfg = _resolve_gsquant_curve_config(curve)
    reference_curve_name = curve_cfg["reference_key"]
    curve_id = f"{as_of}-GSQUANT-rl_basic_{curve}"

    df = frame.copy()
    df = df.set_index("tenor").reindex(curve_cfg["base_tenors"])
    required_cols = ["effectiveDate", "terminationDate", "rate"]
    missing_mask = df[required_cols].isna().any(axis=1)
    if missing_mask.any():
        missing_tenors = list(df.index[missing_mask])
        raise ValueError(f"Missing GSQUANT inputs for curve '{curve}' on {as_of}: {missing_tenors}")

    def make_swap(row: pd.Series):
        return rl.IRS(
            effective=row["effectiveDate"],
            termination=row["terminationDate"],
            fixed_rate=row["rate"],
            curves=curve_id,
            spec=RATESLIB_CURVE_DEFINITIONS[reference_curve_name]["ReferenceRate"],
        )

    df["instruments"] = df.apply(make_swap, axis=1)

    nodes = {pd.Timestamp(as_of): 1.0}
    nodes.update(dict(zip(df["terminationDate"], [1.0] * len(df))))
    nodes = dict(sorted(nodes.items()))

    curve_kwargs: Dict[str, Any] = {
        "nodes": nodes,
        "id": curve_id,
        "convention": RATESLIB_CURVE_DEFINITIONS[reference_curve_name]["DayCounter"],
        "calendar": RATESLIB_CURVE_DEFINITIONS[reference_curve_name]["Calendar"],
        "modifier": RATESLIB_CURVE_DEFINITIONS[reference_curve_name]["BusinessConvention"],
    }

    if curve_cfg.get("extrapolation"):
        # The right spline boundary must be anchored on the true LAST knot, not
        # the second-to-last: the previous form built `extrapolated` from
        # `knot_names[-2]`, which left the spline domain short of the curve's
        # actual longest node (the last knot's own termination) whenever the
        # extrapolation window undershot that gap even slightly - undefined
        # evaluation there, which showed up as an all-NaN Solver failure once a
        # calibrating instrument's cashflow landed past the spline's endpoint.
        #
        # The textbook fix would also promote the last knot itself into the
        # interior control-point list (`knot_names[1:]` instead of
        # `knot_names[1:-1]`), since it now lies strictly inside the domain.
        # That does not solve here: every curve in this map is built so its
        # `knots` list is exactly 1:1 with the curve's in-domain nodes (any
        # meeting-dated/imm front-end instrument always terminates before the
        # first knot, so it never contributes a node inside the spline's
        # domain) - which means rateslib's per-curve exact (non-least-squares)
        # spline fit is already exactly determined: `len(t) - 4` basis
        # functions against exactly that many fit points. Adding one more
        # interior knot without a new underlying node to fit makes the system
        # overdetermined by one and rateslib's `csolve` raises `` `csolve`
        # cannot complete if length of `tau` < n or `allow_lsq` is false ``
        # (verified directly against USD-OIS on 2015-06-30, 2020-06-30 and
        # 2026-07-31, all three failing identically with the textbook form).
        # So only the `extrapolated` anchor moves to the true last knot; the
        # interior control-point list is unchanged, which keeps every curve's
        # spline exactly determined while still fixing the boundary bug: the
        # domain's right edge now clears the true last knot's date by the full
        # extrapolation window, rather than by window-minus-gap-to-the-
        # second-to-last-knot.
        knot_names = list(curve_cfg["knots"])
        knots = [df.loc[name]["terminationDate"] for name in knot_names[1:-1]]
        extrapolated = df.loc[knot_names[-1]]["terminationDate"] + curve_cfg["extrapolation"]
        curve_kwargs.update(
            interpolation="log_linear",
            t=[
                df.loc[knot_names[0]]["terminationDate"],
                df.loc[knot_names[0]]["terminationDate"],
                df.loc[knot_names[0]]["terminationDate"],
                df.loc[knot_names[0]]["terminationDate"],
            ]
            + knots
            + [extrapolated, extrapolated, extrapolated, extrapolated],
            endpoints=("natural", "natural"),
        )

    rl_curve = rl.Curve(**curve_kwargs)
    rl.Solver(
        curves=[rl_curve],
        instruments=df["instruments"],
        s=df["rate"],
        id=curve_id,
        func_tol=1e-9,
        conv_tol=1e-9,
        max_iter=100,
        weights=[1] * len(df["instruments"]),
    )

    pricing_location: Optional[str] = None
    if "pricingLocation" in df.columns:
        pricing_values = df["pricingLocation"].dropna().tolist()
        if pricing_values:
            pricing_location = pricing_values[-1]

    return curve_id, rl_curve, pricing_location


def build_rl_basic_gsquant_curves(
    curve: str,
    as_of_dates: Sequence[datetime.date],
    *,
    max_workers: Optional[int] = None,
) -> Dict[datetime.date, Tuple[str, Any, Optional[str]]]:
    requested_dates = sorted({d for d in as_of_dates if isinstance(d, datetime.date)})
    if not requested_dates:
        return {}

    dataset_df = _fetch_rl_basic_gsquant_dataset(curve, requested_dates)
    if dataset_df.empty:
        return {}

    frames_by_date: Dict[datetime.date, pd.DataFrame] = {
        as_of: dataset_df.loc[dataset_df["as_of"] == as_of].copy()
        for as_of in requested_dates
        if as_of in set(dataset_df["as_of"].tolist())
    }
    if not frames_by_date:
        return {}

    def _build_one(as_of: datetime.date):
        return as_of, _build_rl_basic_gsquant_curve_from_frame(curve, as_of, frames_by_date[as_of])

    out: Dict[datetime.date, Tuple[str, Any, Optional[str]]] = {}
    worker_count = int(max_workers or 1)
    if worker_count > 1 and len(frames_by_date) > 1:
        with ThreadPoolExecutor(max_workers=min(worker_count, len(frames_by_date))) as executor:
            futures = {executor.submit(_build_one, as_of): as_of for as_of in frames_by_date}
            for future in as_completed(futures):
                try:
                    as_of, built = future.result()
                except Exception:
                    continue
                out[as_of] = built
        return {as_of: out[as_of] for as_of in requested_dates if as_of in out}

    for as_of in requested_dates:
        frame = frames_by_date.get(as_of)
        if frame is None or frame.empty:
            continue
        try:
            _, built = _build_one(as_of)
        except Exception:
            continue
        out[as_of] = built
    return out


def build_rl_basic_gsquant_curve(curve: str, as_of: datetime.date):
    built = build_rl_basic_gsquant_curves(curve=curve, as_of_dates=[as_of], max_workers=1)
    if as_of not in built:
        raise ValueError(f"Could not build GSQUANT curve '{curve}' for {as_of}.")
    return built[as_of]
