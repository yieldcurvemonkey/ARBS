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

_CONTRACT_MAP = {
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
) -> pd.DataFrame:
    """Build weekly positioning panel (date × tenor) from CFTC data.

    metric: 'lev_net' (leveraged money net), 'am_net' (asset manager net),
            'total_net' (lev + asset manager combined)
    """
    if raw is None:
        raw = fetch_cftc_financial_futures(cache_path=cache_path)
    if raw.empty:
        return pd.DataFrame()

    if tenors is None:
        tenors = ["2Y", "5Y", "10Y", "30Y"]

    col = "Market_and_Exchange_Names"
    series: Dict[str, pd.Series] = {}

    for tenor in tenors:
        names = _CONTRACT_MAP.get(tenor, [])
        sub = raw[raw[col].isin(names)].copy()
        if sub.empty:
            continue

        sub["date"] = pd.to_datetime(sub["Report_Date_as_YYYY-MM-DD"])
        sub["lev_net"] = (
            sub["Lev_Money_Positions_Long_All"] - sub["Lev_Money_Positions_Short_All"]
        )
        sub["am_net"] = (
            sub["Asset_Mgr_Positions_Long_All"] - sub["Asset_Mgr_Positions_Short_All"]
        )
        sub["total_net"] = sub["lev_net"] + sub["am_net"]

        agg = sub.groupby("date")[metric].sum().sort_index()
        series[tenor] = agg

    if not series:
        return pd.DataFrame()

    panel = pd.DataFrame(series).sort_index()
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
