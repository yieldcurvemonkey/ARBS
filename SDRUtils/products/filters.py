import pandas as pd


def new_sofr_swap_trades(df: pd.DataFrame, include_misc=False):
    upi_underlier_names = [
        "USD-SOFR-COMPOUND",
        "USD-SOFR-OIS Compound",
    ]
    upi_underlier_names_misc = [
        "USD-SOFR CME Term",
        "USD-SOFR",
        "USD-SOFR ICE Swap Rate",
        "USD-SOFR Average 30D ",
    ]
    if include_misc:
        upi_underlier_names = upi_underlier_names + upi_underlier_names_misc
    upi_fisn = ["NA/Swap OIS USD", "NA/Swap Fxd Flt USD"]

    df = df.copy()
    return df[(df["UPI Underlier Name"].isin(upi_underlier_names)) & (df["UPI FISN"].isin(upi_fisn)) & (df["Action type"] == "NEWT")]
