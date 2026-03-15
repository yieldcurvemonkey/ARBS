import pandas as pd
import datetime
import rateslib as rl

from gs_quant.data import Dataset
from gs_quant.session import GsSession

from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache


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
                
                "USD Swap OIS 3m ATM imm1 to 3m LCH Cleared",
                "USD Swap OIS 3m ATM imm2 to 3m LCH Cleared",
                "USD Swap OIS 3m ATM imm3 to 3m LCH Cleared",
                "USD Swap OIS 3m ATM imm4 to 3m LCH Cleared",

                "USD Swap OIS 6m ATM imm1 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm2 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm3 to 6m LCH Cleared",
                "USD Swap OIS 6m ATM imm4 to 6m LCH Cleared",
                
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
                "EUR Swap EuroSTR 1y ATM 0b to 50y LCH Cleared",
            ],
            "knots": [
                "EUR Swap EuroSTR 1y ATM 0b to 2y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 3y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 5y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 10y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 30y LCH Cleared",
                "EUR Swap EuroSTR 1y ATM 0b to 50y LCH Cleared",
            ],
            "extrapolation": datetime.timedelta(days=30),
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
    }
}
# fmt: on


def build_rl_basic_gsquant_curve(curve: str, as_of: datetime.date):
    assert GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"] in RATESLIB_CURVE_DEFINITIONS, f"{curve} not defined in 'RATESLIB_CURVE_DEFINITIONS'"

    if curve == "USD-FEDFUNDS":
        curve = "USD-OIS"
    assert curve in GSQUANT_CURVE_MAP, f"{curve} not defined in 'GSQUANT_CURVE_MAP'"

    curve_id = f"{as_of}-GSQUANT-rl_basic_{curve}"
    gs_client_id = "2eb2f48872304c1d94fa1642fa691afe"
    gs_secret_key = "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4"
    GsSession.use(client_id=gs_client_id, client_secret=gs_secret_key, scopes=GsSession.Scopes.get_default())

    gs_ds = "IR_SWAP_RATES_V1_STANDARD"
    gs_ds_coverage = pd.read_excel(rf"C:\Users\chris\clee\ARBS\MDP\IRSwaps\GSQUANT\COVERAGE\{gs_ds}_COVERAGE.xlsx")
    df = Dataset(gs_ds).get_data(
        start=as_of, end=as_of, assetId=gs_ds_coverage[gs_ds_coverage["name"].isin(GSQUANT_CURVE_MAP[curve]["rl_basic"]["base_tenors"])]["assetId"]
    )
    df["tenor"] = df["assetId"].map(dict(zip(gs_ds_coverage["assetId"], gs_ds_coverage["name"])))
    df = df.reset_index(drop=True).set_index("tenor").reindex(GSQUANT_CURVE_MAP[curve]["rl_basic"]["base_tenors"])
    df["effectiveDate"] = pd.to_datetime(df["effectiveDate"], errors="coerce")
    df["terminationDate"] = pd.to_datetime(df["terminationDate"], errors="coerce")
    df["rate"] = df["rate"] * 100

    def make_swap(row):
        return rl.IRS(
            effective=row["effectiveDate"],
            termination=row["terminationDate"],
            fixed_rate=row["rate"],
            curves=curve_id,
            spec=RATESLIB_CURVE_DEFINITIONS[GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]]["ReferenceRate"],
        )

    df["instruments"] = df.apply(make_swap, axis=1)

    nodes = {pd.Timestamp(as_of): 1.0}
    nodes.update(dict(zip(df["terminationDate"], [1.0] * len(df))))
    nodes = dict(sorted(nodes.items()))

    if "extrapolation" in GSQUANT_CURVE_MAP[curve]["rl_basic"] and GSQUANT_CURVE_MAP[curve]["rl_basic"]["extrapolation"]:
        knots = [df.loc[i]["terminationDate"] for i in GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"].copy()[1:-1]]
        extrapolated = df.loc[GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"][-2]]["terminationDate"] + GSQUANT_CURVE_MAP[curve]["rl_basic"]["extrapolation"]
        rl_curve = rl.Curve(
            nodes=nodes,
            id=curve_id,
            convention=RATESLIB_CURVE_DEFINITIONS[GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]]["DayCounter"],
            calendar=RATESLIB_CURVE_DEFINITIONS[GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]]["Calendar"],
            modifier=RATESLIB_CURVE_DEFINITIONS[GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]]["BusinessConvention"],
            interpolation="log_linear",
            # fmt: off
            t=[
                df.loc[GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"][0]]["terminationDate"],
                df.loc[GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"][0]]["terminationDate"],
                df.loc[GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"][0]]["terminationDate"],
                df.loc[GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"][0]]["terminationDate"],
            ]
            + knots
            + [
                extrapolated, extrapolated, extrapolated, extrapolated
            ],
            # fmt: on
            endpoints=("natural", "natural"),
        )
    else:
        rl_curve = rl.Curve(
            nodes=nodes,
            id=curve_id,
            convention=RATESLIB_CURVE_DEFINITIONS[GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]]["DayCounter"],
            calendar=RATESLIB_CURVE_DEFINITIONS[GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]]["Calendar"],
            modifier=RATESLIB_CURVE_DEFINITIONS[GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]]["BusinessConvention"],
        )

    print(df["rate"])

    rl_solver = rl.Solver(
        curves=[rl_curve],
        instruments=df["instruments"],
        s=df["rate"],
        id=curve_id,
        func_tol=1e-9,
        conv_tol=1e-9,
        max_iter=100,
        weights=[1] * len(df["instruments"]),
    )

    return curve_id, rl_curve, df["pricingLocation"].iloc[-1]
