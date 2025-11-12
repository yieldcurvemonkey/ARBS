import pandas as pd  # Required for gs_quant Dataset API compatibility and pl.from_pandas conversion
import polars as pl
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
        }
    }
}
# fmt: on


def build_rl_basic_gsquant_curve(curve: str, as_of: datetime.date):
    assert curve in RATESLIB_CURVE_DEFINITIONS, f"{curve} not defined in 'RATESLIB_CURVE_DEFINITIONS'"

    if curve == "USD-FEDFUNDS":
        curve = "USD-OIS"
    assert curve in GSQUANT_CURVE_MAP, f"{curve} not defined in 'GSQUANT_CURVE_MAP'"

    curve_id = f"{as_of}-GSQUANT-rl_basic_{curve}"
    gs_client_id = "2eb2f48872304c1d94fa1642fa691afe"
    gs_secret_key = "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4"
    GsSession.use(client_id=gs_client_id, client_secret=gs_secret_key, scopes=GsSession.Scopes.get_default())

    gs_ds = "IR_SWAP_RATES_V1_STANDARD"
    gs_ds_coverage = pl.read_excel(rf"C:\Users\chris\clee\ARBS\MDP\IRSwaps\GSQUANT\COVERAGE\{gs_ds}_COVERAGE.xlsx")

    # Filter coverage for base tenors
    filtered_asset_ids = gs_ds_coverage.filter(
        pl.col("name").is_in(GSQUANT_CURVE_MAP[curve]["rl_basic"]["base_tenors"])
    )["assetId"].to_list()

    # Get data from GS Quant (returns pandas DataFrame, convert to polars)
    df_gs = Dataset(gs_ds).get_data(
        start=as_of, end=as_of, assetId=filtered_asset_ids
    )
    df = pl.from_pandas(df_gs)

    # Create tenor mapping
    tenor_map = dict(zip(gs_ds_coverage["assetId"], gs_ds_coverage["name"]))
    df = df.with_columns(
        pl.col("assetId").replace(tenor_map).alias("tenor")
    )

    # Set tenor as join key and reindex to base_tenors order
    base_tenors_df = pl.DataFrame({"tenor": GSQUANT_CURVE_MAP[curve]["rl_basic"]["base_tenors"]})
    df = base_tenors_df.join(df, on="tenor", how="left")

    # Convert date columns to datetime (handle both string and datetime types)
    # If already datetime from pandas, cast to polars datetime; if string, parse it
    df = df.with_columns([
        pl.col("effectiveDate").cast(pl.Datetime).alias("effectiveDate"),
        pl.col("terminationDate").cast(pl.Datetime).alias("terminationDate"),
        (pl.col("rate") * 100).alias("rate")
    ])

    # Create instruments using list comprehension (polars doesn't have apply)
    instruments = []
    for row in df.iter_rows(named=True):
        instruments.append(
            rl.IRS(
                effective=row["effectiveDate"],
                termination=row["terminationDate"],
                fixed_rate=row["rate"],
                curves=curve_id,
                spec=RATESLIB_CURVE_DEFINITIONS[curve]["ReferenceRate"],
            )
        )
    df = df.with_columns(pl.Series("instruments", instruments))

    # Build nodes dict using datetime objects instead of pd.Timestamp
    nodes = {datetime.datetime.combine(as_of, datetime.time()): 1.0}
    termination_dates = df["terminationDate"].to_list()
    nodes.update(dict(zip(termination_dates, [1.0] * len(termination_dates))))
    nodes = dict(sorted(nodes.items()))

    # Get knots by filtering df for specific tenor names (maintain order)
    knot_tenors = GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"].copy()[1:-1]
    knots = []
    for tenor in knot_tenors:
        knot_date = df.filter(pl.col("tenor") == tenor)["terminationDate"][0]
        knots.append(knot_date)

    # Get extrapolated date
    last_knot_tenor = GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"][-1]
    last_knot_date = df.filter(pl.col("tenor") == last_knot_tenor)["terminationDate"][0]
    extrapolated = last_knot_date + GSQUANT_CURVE_MAP[curve]["rl_basic"]["extrapolation"]

    # Get first knot date for t parameter
    first_knot_tenor = GSQUANT_CURVE_MAP[curve]["rl_basic"]["knots"][0]
    first_knot_date = df.filter(pl.col("tenor") == first_knot_tenor)["terminationDate"][0]

    rl_curve = rl.Curve(
        nodes=nodes,
        id=curve_id,
        convention=RATESLIB_CURVE_DEFINITIONS[curve]["DayCounter"],
        calendar=RATESLIB_CURVE_DEFINITIONS[curve]["Calendar"],
        modifier=RATESLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
        interpolation="log_linear",
        # fmt: off
        t=[
            first_knot_date,
            first_knot_date,
            first_knot_date,
            first_knot_date,
        ]
        + knots
        + [
            extrapolated, extrapolated, extrapolated, extrapolated
        ],
        # fmt: on
        endpoints=("natural", "natural"),
    )

    rl_solver = rl.Solver(
        curves=[rl_curve],
        instruments=df["instruments"].to_list(),
        s=df["rate"].to_list(),
        id=curve_id,
        func_tol=1e-8,
        conv_tol=1e-8,
        weights=[1] * len(df),
    )

    return curve_id, rl_curve, df["pricingLocation"][-1]
