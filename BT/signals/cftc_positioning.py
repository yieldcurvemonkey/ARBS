"""
CFTC Traders in Financial Futures — treasury positioning data.

Fetches from CFTC bulk downloads, extracts leveraged-money and
asset-manager net positioning for 2Y, 5Y, 10Y, 30Y treasury futures.
Computes rolling z-scores for use as positioning filters.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

#: Business days from the Tuesday a TFF report MEASURES to the Friday it is
#: PUBLISHED (15:30 ET). Measured on the local cache: 329 of 332 report dates are
#: Tuesdays and the modal gap is exactly 7 days, but **no column carries a
#: release stamp** -- so nothing in the data itself stops a reader from treating
#: Tuesday's position as known on Tuesday. Indexing on the report date and
#: forward-filling, which is what this module used to do, is three business days
#: of look-ahead inside the signal, before any backtest code runs.
RELEASE_LAG_BUSINESS_DAYS = 3

#: The metrics that can be built from the TFF category columns.
_METRICS = {
    "lev_net": ("Lev_Money_Positions_Long_All", "Lev_Money_Positions_Short_All"),
    "am_net": ("Asset_Mgr_Positions_Long_All", "Asset_Mgr_Positions_Short_All"),
    "dealer_net": ("Dealer_Positions_Long_All", "Dealer_Positions_Short_All"),
}

_CONTRACT_MAP = {
    #: STIR. The convexity work needs these and the map did not carry them, so a
    #: pack-convexity strategy could not read positioning at all. Both vintages
    #: of each name are listed: CFTC renamed the markets in Feb-2022 and a map
    #: carrying only the new name starts the series at the rename.
    "SOFR3M": [
        "SOFR-3M - CHICAGO MERCANTILE EXCHANGE",
        "3-MONTH SOFR - CHICAGO MERCANTILE EXCHANGE",
    ],
    "SOFR1M": [
        "SOFR-1M - CHICAGO MERCANTILE EXCHANGE",
        "1-MONTH SOFR - CHICAGO MERCANTILE EXCHANGE",
    ],
    "FF": [
        "FED FUNDS - CHICAGO BOARD OF TRADE",
        "30-DAY FED FUNDS - CHICAGO BOARD OF TRADE",
    ],
    "ED": [
        "EURODOLLARS-3M - CHICAGO MERCANTILE EXCHANGE",
        "3-MONTH EURODOLLARS - CHICAGO MERCANTILE EXCHANGE",
    ],
    "2Y": [
        "2-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
        "UST 2Y NOTE - CHICAGO BOARD OF TRADE",
    ],
    "5Y": [
        "5-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
        "UST 5Y NOTE - CHICAGO BOARD OF TRADE",
    ],
    "10Y": [
        "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
        "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
        "ULTRA 10-YEAR U.S. T-NOTES - CHICAGO BOARD OF TRADE",
        "ULTRA UST 10Y - CHICAGO BOARD OF TRADE",
    ],
    "30Y": [
        "U.S. TREASURY BONDS - CHICAGO BOARD OF TRADE",
        "UST BOND - CHICAGO BOARD OF TRADE",
        "ULTRA U.S. TREASURY BONDS - CHICAGO BOARD OF TRADE",
        "ULTRA UST BOND - CHICAGO BOARD OF TRADE",
    ],
}


def fetch_cftc_financial_futures(
    years: Optional[List[int]] = None,
    cache_path: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch CFTC Traders in Financial Futures bulk data."""
    if cache_path and Path(cache_path).exists():
        return pd.read_parquet(cache_path)

    if years is None:
        years = list(range(2020, 2027))

    frames: list[pd.DataFrame] = []
    for y in years:
        url = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{y}.zip"
        try:
            r = requests.get(url, timeout=60)
            if r.status_code != 200:
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            with z.open(z.namelist()[0]) as f:
                df = pd.read_csv(f, low_memory=False)
            frames.append(df)
        except Exception as exc:
            logger.warning("CFTC %d: %s", y, exc)

    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(cache_path)

    return raw


def build_positioning_panel(
    raw: Optional[pd.DataFrame] = None,
    cache_path: Optional[str] = None,
    tenors: Optional[List[str]] = None,
    metric: str = "lev_net",
    release_lag_bdays: int = RELEASE_LAG_BUSINESS_DAYS,
) -> pd.DataFrame:
    """Daily positioning panel (date x tenor), indexed by RELEASE date.

    ``metric``
        ``lev_net`` (leveraged money), ``am_net`` (asset managers),
        ``dealer_net`` (**dealers/intermediaries**), or ``total_net``
        (leveraged + asset manager). An unrecognised name raises rather than
        returning an empty frame, because an empty frame is how a typo becomes
        "the signal had no effect".

    ``release_lag_bdays``
        Business days added to each report date before the panel is
        forward-filled. **This is not a smoothing parameter.** The TFF report
        measures positions as of Tuesday and is published Friday 15:30 ET; the
        raw file carries no release stamp, so indexing on the report date and
        forward-filling makes Friday's number readable on Tuesday. Defaults to
        :data:`RELEASE_LAG_BUSINESS_DAYS`. Pass ``0`` to reproduce the previous
        behaviour deliberately.

    The dealer category is the one the convexity research is about -- *"Dealers,
    who are on the other side of the shorts established by hedge funds and asset
    managers, have ended up with significant long ED positions. Convexity
    adjustments have therefore widened to compensate dealers for this
    concentration risk."* -- and it was absent, although its columns are fully
    populated.
    """
    if raw is None:
        raw = fetch_cftc_financial_futures(cache_path=cache_path)
    if raw.empty:
        return pd.DataFrame()

    if tenors is None:
        tenors = ["2Y", "5Y", "10Y", "30Y"]

    if metric not in _METRICS and metric != "total_net":
        raise KeyError(
            f"unknown metric {metric!r}; expected one of "
            f"{sorted(list(_METRICS) + ['total_net'])}")

    col = "Market_and_Exchange_Names"
    series: Dict[str, pd.Series] = {}

    for tenor in tenors:
        names = _CONTRACT_MAP.get(tenor, [])
        sub = raw[raw[col].isin(names)].copy()
        if sub.empty:
            continue

        sub["date"] = pd.to_datetime(sub["Report_Date_as_YYYY-MM-DD"])
        for name, (lng, sht) in _METRICS.items():
            sub[name] = sub[lng] - sub[sht]
        sub["total_net"] = sub["lev_net"] + sub["am_net"]

        agg = sub.groupby("date")[metric].sum().sort_index()
        series[tenor] = agg

    if not series:
        return pd.DataFrame()

    panel = pd.DataFrame(series).sort_index()
    if release_lag_bdays:
        panel.index = panel.index + pd.tseries.offsets.BDay(release_lag_bdays)
    panel = panel.resample("B").ffill()
    return panel


def positioning_zscore(
    panel: pd.DataFrame,
    window: int = 52,
) -> pd.DataFrame:
    """Rolling z-score of positioning level (weekly data ffilled to daily)."""
    mu = panel.rolling(window * 5, min_periods=window * 2).mean()
    sigma = panel.rolling(window * 5, min_periods=window * 2).std()
    return (panel - mu) / sigma.replace(0, np.nan)
