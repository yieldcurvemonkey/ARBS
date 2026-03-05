import datetime
import numpy as np
import QuantLib as ql
import pandas as pd
from scipy.interpolate import griddata
from gs_quant.data import Dataset
from gs_quant.session import GsSession

from typing import List
from tqdm import tqdm

# Ordered grid axes
EXPIRY_LABELS = ["1m", "3m", "6m", "1y", "2y", "3y", "5y", "10y"]
TAIL_LABELS = ["1y", "2y", "5y", "10y", "20y", "30y"]

ASSET_IDS_MAP = {
    "USD-SOFR-1D": {
        "MA0940P64670DMBN": "3m 2y",
        "MA1FNC36DEFHVN2C": "1y 30y",
        "MA2NTGZAVD2MJP7H": "6m 1y",
        "MA3YAP9YTBN0HAM4": "1y 10y",
        "MA445SXEHARX50R9": "10y 1y",
        "MA49ECK032PJTC8J": "3m 10y",
        "MA4ENNPH4E0Y1SSM": "1y 20y",
        "MA58YBVZARCPHEZA": "3y 10y",
        "MA5XPSACC0MJYCVF": "2y 30y",
        "MA6S945RQJGNN9N6": "3y 30y",
        "MA86TN5S1MCAYV43": "5y 2y",
        "MA93T6K8G03JTG3Z": "6m 2y",
        "MA955FBZD7B0P4J3": "3y 5y",
        "MA95VH73S1NCG53X": "2y 1y",
        "MA9QTHX2YEJYXW1F": "2y 5y",
        "MA9SMXP1VBEY5Q3X": "2y 2y",
        "MAB9NBVXX9P4REE8": "1m 1y",
        "MAC4P6MFTTSS0AMC": "5y 10y",
        "MAD3S4WCWZ9QY1CV": "10y 20y",
        "MADBWWZQJ41SV6KN": "1m 10y",
        "MAEGWWZD5Y56JDB4": "5y 5y",
        "MAEY83EK3S0C8S9J": "1y 2y",
        "MAF5ZTP4B6V0Y1FV": "10y 30y",
        "MAFTGRYQ76G5Z30N": "1m 20y",
        "MAFWD8SAF0AAJS3M": "3m 5y",
        "MAH06A6NF31G9RK8": "6m 10y",
        "MAH1GBR0EJV7B1H7": "3m 30y",
        "MAM29DEGNCFFFMGH": "1m 30y",
        "MAME8C0CR5348J9H": "1m 5y",
        "MAMFQNGQMCV5AXEY": "2y 20y",
        "MAMG0AVEH23DQKY8": "3m 20y",
        "MAMXHY0DRCYAJPQM": "3y 20y",
        "MAN2M6FKDSKMM3DK": "1y 1y",
        "MAN736YYV00W3S9W": "3m 1y",
        "MAN86DZD69G4XYR0": "5y 30y",
        "MAPH3C6ANDKXS3KB": "10y 10y",
        "MAPXN9T73JW9REBY": "10y 5y",
        "MASBTVCRWKN3X0E9": "1m 2y",
        "MASJFF197P5KZ9MZ": "3y 2y",
        "MATJX9AX10WZQ88J": "10y 2y",
        "MATK1QVZQ26CV1K1": "3y 1y",
        "MATNZV1K28V2G452": "5y 20y",
        "MAW77GWPT9HN67QM": "5y 1y",
        "MAW8NHDM5GHN4CMN": "6m 20y",
        "MAWJCBSN5NF4HTHJ": "1y 5y",
        "MAWTFMFSHNRGHSG7": "6m 30y",
        "MAYKPCJKVA8ACJZN": "2y 10y",
        "MAZECH8T2R0KD91B": "6m 5y",
    },
    "EUR-ESTR": {
        "MA0E96K3BGQWGEN7": "1m 20y",
        "MA0VJDYW04D7X1J0": "5y 5y",
        "MA1CP1093C77VVKG": "2y 5y",
        "MA21JQV3YFR7BKV6": "1m 10y",
        "MA2TGA22KDQMF8Q9": "2y 2y",
        "MA2YT3P6WDT0P203": "3y 5y",
        "MA42DWGHH8Y928YS": "3m 1y",
        "MA43TG9ZF12V1N3V": "10y 1y",
        "MA4A5J9SE7KW6G20": "3y 1y",
        "MA4BRNS9WAP32980": "6m 20y",
        "MA5BXBM27SGSMNFJ": "1m 1y",
        "MA76SZEEGRZFZNY0": "3m 5y",
        "MA7SJFBB7ES2BQVJ": "3y 10y",
        "MA8A26GW6PHYK46S": "3m 10y",
        "MA8B7ZDDJGWXR9J6": "1y 1y",
        "MA9ST4QPPQZQFPBR": "1y 2y",
        "MA9T57HSE109V0HX": "10y 2y",
        "MAATX57TDWFDD4FN": "6m 10y",
        "MAB1W53HYTMQCX1B": "2y 20y",
        "MAB7CW79KPXSG6ZK": "3y 2y",
        "MACQ358V832EB16N": "5y 30y",
        "MAEHG3NY4TEZYCWY": "10y 10y",
        "MAFF8P44FY2XNE1P": "1y 20y",
        "MAGCT18DY49XNA0D": "6m 1y",
        "MAH7XEQ0XM4CDMJ5": "5y 1y",
        "MAHSEQ2RCNQRGCH5": "3y 20y",
        "MAJB753CHSE3PZ45": "3m 20y",
        "MAJC07KWWS9KP3ND": "5y 10y",
        "MAJFC5E6TVQ9T6TH": "2y 1y",
        "MAK0D7XPCKJX3NW6": "1m 30y",
        "MAKH6WDTKSAMRKPC": "6m 30y",
        "MAKSHA494VKG43PT": "1y 5y",
        "MAMHEZN7GTE27AG5": "3y 30y",
        "MAN9SZR5E325830M": "1y 10y",
        "MANAX5SMV6M1C93F": "3m 30y",
        "MAP5QQ2Y9PDG919M": "10y 30y",
        "MAPN1ZG028DDPBE3": "1m 2y",
        "MASJQE1PRT2NN01A": "10y 5y",
        "MATZJBSQTGBGFN9S": "6m 5y",
        "MAV154H7GDETQ5Z0": "5y 2y",
        "MAWPFN427WWJP8DE": "2y 30y",
        "MAXGWZ7MV2M17KWY": "1m 5y",
        "MAXT9DD3NV3JK6MP": "6m 2y",
        "MAXZHTJSN83YHW85": "2y 10y",
        "MAYC7DHG6XHH7PXS": "5y 20y",
        "MAYZ2NA6WA3ZP5Z9": "10y 20y",
        "MAZ816T7ESTFCXHA": "3m 2y",
        "MAZPZNQ74E7B1HNJ": "1y 30y",
    },
    "JPY-TONAR": {
        "MA1AS4MMFN5VW00Z": "5y 1y",
        "MA2H5C88QGDF0CQD": "5y 5y",
        "MA36GFB37HY2CHA0": "2y 2y",
        "MA39BYTMND29YRW2": "2y 1y",
        "MA3ABFA0V6YFRQ3Z": "10y 30y",
        "MA3AEJ56NPE72721": "10y 2y",
        "MA6B74QPQFV3E14Y": "6m 10y",
        "MA6DYJS6B7CD2XZ1": "1y 10y",
        "MA7GA1XHCYCAWPJ9": "2y 30y",
        "MA7WVJH3GT1CX45S": "10y 10y",
        "MA8KFTEGZ5KXPTA5": "5y 20y",
        "MA9JNG61D9A27PFQ": "5y 10y",
        "MA9V2XM5B8CP17HT": "5y 30y",
        "MA9WBSA12QNEJ9B2": "6m 2y",
        "MA9Z8015DNSFW6M8": "1y 5y",
        "MA9ZXHG21G3MQ8X2": "10y 1y",
        "MAAM45XC89WNWWHA": "10y 5y",
        "MACFH8Y405VJX7K7": "6m 5y",
        "MADP20RBXPZ115AP": "6m 30y",
        "MADXKB825P140JMK": "1m 30y",
        "MAE552QEZTYXV4V9": "3m 20y",
        "MAF4JGP1BT4JGEN9": "1m 20y",
        "MAFFGZJGF3K727RC": "3y 10y",
        "MAHKFPSS8KYMQMMS": "3y 2y",
        "MAKCMXCAT43F4ZE9": "3y 5y",
        "MAM8VWWZ41TMK8HV": "3y 20y",
        "MAMAY04432VRJY3A": "3m 30y",
        "MAN5Q0AY838PRJSD": "6m 20y",
        "MANT1B1MQY2Z0RHS": "1y 1y",
        "MAP5ZPPEQJ2996XY": "2y 5y",
        "MAP8K9G8SB80C1WB": "10y 20y",
        "MAQ20884QXM2NXM6": "3y 1y",
        "MAQ58JZHHKJBACJE": "1m 10y",
        "MAQGFD57MX47KAB2": "3m 10y",
        "MARFRW59WMHSFBGQ": "1m 1y",
        "MARZ8A4P6AK473GN": "2y 20y",
        "MAS9ATY2C2NZSHWF": "5y 2y",
        "MASCSXB490AMV7RK": "1y 30y",
        "MASQFA5H3JH6GNHD": "3m 5y",
        "MASS3A7CGP2DNRH3": "3m 1y",
        "MASTKAXEAB4KTNVT": "1y 20y",
        "MASX5GG4XCQCCJPY": "3y 30y",
        "MATWVFQ4HVTDYQXK": "1m 5y",
        "MAWEME6RCH2S7670": "2y 10y",
        "MAXK5HJEJ5CG82CY": "6m 1y",
        "MAXQ3CTFSJ815H0B": "1m 2y",
        "MAYB6KWA7YQFH3JV": "3m 2y",
        "MAYE9XX2B741N67G": "1y 2y",
    },
    "GBP-SONIA": {
        "MA0PV0WFJDANQSQV": "1m 10y",
        "MA0TCNCP4Q92GYC0": "3y 30y",
        "MA1EZY4GS2ZRNQJV": "3m 20y",
        "MA1TV1FYFZBKK3FH": "2y 1y",
        "MA2GVZWN3TJHR0WA": "3y 1y",
        "MA365QTYFC5RMXVS": "1y 20y",
        "MA39SJPWVFXY3F0N": "1m 5y",
        "MA3DD570BZH1Y9D6": "10y 10y",
        "MA3FGZADKB47TDBM": "2y 30y",
        "MA3Q24EK793BDPHM": "6m 20y",
        "MA5M1HGSS50X05RC": "6m 1y",
        "MA6EE9AENS1D6AET": "3m 2y",
        "MA8GPCTEBG7EG63S": "2y 5y",
        "MAAA4Y70SP207PTK": "10y 5y",
        "MAASX7DA0VKAV893": "3y 5y",
        "MAATH0KSC5CJSDG3": "5y 10y",
        "MAAV1GG1SWAZJRJN": "1y 2y",
        "MAAYR19TK9NDYKEW": "3y 20y",
        "MAC5HKV2V5VG230F": "6m 30y",
        "MAD0GCKJKTEQ88DZ": "6m 10y",
        "MAEDHH32ZBX12XC7": "2y 10y",
        "MAEFTFRJ6ZWW1MTT": "1m 30y",
        "MAENRQC4RV57R76R": "2y 2y",
        "MAFQQ9VZM115W6E8": "6m 2y",
        "MAG0EGGE6FCXZKET": "6m 5y",
        "MAJDCWER394T30C3": "5y 2y",
        "MAJEMBF5B08DRN2H": "1y 30y",
        "MAJJA1A88B903YSJ": "1m 20y",
        "MAJM7K6099MH47E8": "10y 2y",
        "MAJNHFE3F656BMM8": "3m 30y",
        "MAKFPBPWV0SPEQM8": "10y 30y",
        "MAKJN8S6XRP0WT14": "1m 1y",
        "MAN7JM8D90R2C6R4": "1m 2y",
        "MANC7G1DCQ16806B": "5y 20y",
        "MANKJS2FMMZJDTK0": "10y 1y",
        "MANM809DFKR2CNMD": "1y 1y",
        "MAP6GFYQ0WKJB9CB": "3m 5y",
        "MAPKNQ9R27ANEVFA": "3y 2y",
        "MAQ793RWRTP7R21Z": "1y 10y",
        "MARM8345ZB5AW8M7": "5y 1y",
        "MASBHEMR376M9B3J": "5y 5y",
        "MAVGGY0FQQ31ERP7": "3y 10y",
        "MAW9MXYAE4BYFAGJ": "5y 30y",
        "MAX9D33GCQ7QG97G": "3m 10y",
        "MAXEFG5A1MG4NTZY": "10y 20y",
        "MAYH697M0GS07F0E": "2y 20y",
        "MAZCD13ES08PAFKF": "1y 5y",
        "MAZJDCFCZN6NXHMJ": "3m 1y",
    },
}


def _label_to_years(label: str) -> float:
    if label.endswith("m"):
        return int(label[:-1]) / 12.0
    return float(label[:-1])


def _label_to_ql_period(label: str) -> ql.Period:
    if label.endswith("m"):
        return ql.Period(int(label[:-1]), ql.Months)
    return ql.Period(int(label[:-1]), ql.Years)


def _interpolate_missing(vol_matrix: np.ndarray) -> np.ndarray:
    """Fill NaN cells via cubic interpolation on log-tenor axes,
    with linear fallback at boundaries."""
    if not np.isnan(vol_matrix).any():
        return vol_matrix

    expiry_years = np.array([_label_to_years(e) for e in EXPIRY_LABELS])
    tail_years = np.array([_label_to_years(t) for t in TAIL_LABELS])
    log_exp = np.log(expiry_years)
    log_tail = np.log(tail_years)

    known_mask = ~np.isnan(vol_matrix)
    known_pts = np.array([(log_exp[i], log_tail[j]) for i in range(len(EXPIRY_LABELS)) for j in range(len(TAIL_LABELS)) if known_mask[i, j]])
    known_vals = vol_matrix[known_mask]

    grid_exp, grid_tail = np.meshgrid(log_exp, log_tail, indexing="ij")
    filled = griddata(known_pts, known_vals, (grid_exp, grid_tail), method="cubic")
    linear = griddata(known_pts, known_vals, (grid_exp, grid_tail), method="linear")
    filled = np.where(np.isnan(filled), linear, filled)

    return np.where(np.isnan(vol_matrix), filled, vol_matrix)


def get_atmf_grid(curve: str, dates: List[datetime.date]):
    """Fetch GS ATMF normal vol grid and return a ql.SwaptionVolatilityMatrix.

    Returns
    -------
    surface : ql.SwaptionVolatilityMatrix
        Normal (bp) vol surface, annualised.  Query with:
        ``surface.volatility(ql.Period("2Y"), ql.Period("10Y"), 0.0)``
    df : pd.DataFrame
        Raw GS data with swaption_structure and bpvol columns.
    """
    # ── auth + fetch ──────────────────────────────────────────────
    gs_client_id = "2eb2f48872304c1d94fa1642fa691afe"
    gs_secret_key = "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4"
    GsSession.use(
        client_id=gs_client_id,
        client_secret=gs_secret_key,
        scopes=GsSession.Scopes.get_default(),
    )

    df = Dataset("IR_SWAPTION_VOLS_V1_STANDARD").get_data(start=min(dates), end=max(dates), assetId=ASSET_IDS_MAP[curve].keys())
    df["swaption_structure"] = df["assetId"].map(ASSET_IDS_MAP[curve])
    df["bpvol"] = df["impliedNormalVolatility"] * (252**0.5)

    # ── pivot into expiry × tail matrix ───────────────────────────
    df[["expiry", "tail"]] = df["swaption_structure"].str.split(" ", expand=True)

    surfaceses = {}

    for date in tqdm(dates, desc="CONSTRUCTING GS VOL GRIDS..."):
        curr_df = df[df.index == pd.Timestamp(date)]
        vol_matrix = np.full((len(EXPIRY_LABELS), len(TAIL_LABELS)), np.nan)
        for _, row in curr_df.iterrows():
            try:
                i = EXPIRY_LABELS.index(row["expiry"])
                j = TAIL_LABELS.index(row["tail"])
                vol_matrix[i, j] = row["bpvol"]
            except ValueError:
                continue

        vol_matrix = _interpolate_missing(vol_matrix)

        # ── build QuantLib surface ────────────────────────────────────
        ql_eval = ql.Date(date.day, date.month, date.year)
        ql.Settings.instance().evaluationDate = ql_eval

        calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        bdc = ql.ModifiedFollowing
        day_count = ql.Actual365Fixed()

        ql_expiries = ql.PeriodVector()
        for label in EXPIRY_LABELS:
            ql_expiries.append(_label_to_ql_period(label))

        ql_tails = ql.PeriodVector()
        for label in TAIL_LABELS:
            ql_tails.append(_label_to_ql_period(label))

        # bpvol is in bp/yr (e.g. 82.4);  QuantLib Normal expects decimal (0.00824)
        ql_vols = ql.Matrix(len(EXPIRY_LABELS), len(TAIL_LABELS))
        for i in range(len(EXPIRY_LABELS)):
            for j in range(len(TAIL_LABELS)):
                ql_vols[i][j] = vol_matrix[i, j] / 10_000.0

        surface = ql.SwaptionVolatilityStructureHandle(
            ql.SwaptionVolatilityMatrix(
                calendar,
                bdc,
                ql_expiries,
                ql_tails,
                ql_vols,
                day_count,
                False,  # flatExtrapolation
                ql.Normal,  # volatilityType
            )
        )
        surface.enableExtrapolation()
        surfaceses[date] = surface

    return surfaceses
