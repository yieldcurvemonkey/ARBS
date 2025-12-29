import datetime
import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple, Union
from tqdm import tqdm
from collections import defaultdict, deque

import numpy as np
import pandas as pd
import QuantLib as ql
import pytz


SOFR_OIS_UPIS = ["QZXQ4R16245X", "QZPB5VSBGRCD"]

SOFR_UPI_PATTERNS = [
    "USD-SOFR",
    "SOFR",
]

SWAPTION_FISN_PATTERNS = [
    "O Call",  # Call swaption
    "O Put",  # Put swaption
    "Cap",  # Cap
    "Floor",  # Floor
    "Straddle",
    "Strangle",
]


def filter_new_sofr_ois_trades(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    upi = df["Unique Product Identifier"].fillna("").astype(str)
    mask = upi.isin(SOFR_OIS_UPIS)
    if "Action type" in df.columns:
        mask &= df["Action type"].eq("NEWT")

    return df.loc[mask].copy()
