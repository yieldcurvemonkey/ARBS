"""Nominal GDP (SAAR, $bn) from BEA NIPA table 1.1.5 via DBnomics.

Publication timing: the advance estimate for a quarter is released roughly
one month after quarter end (then revised).  ``publication_date`` stamps each
quarter-end observation with reference date + ``publication_lag_days``.

Vintage caveat (documented in the SERFF spec): DBnomics serves the latest
revised values, not the as-published vintages, so publication-lag alignment
removes the timing look-ahead but not the revision look-ahead.
"""

from __future__ import annotations

import datetime
from typing import Optional

import pandas as pd

from MDP.USMoneyMarkets.dbnomics_fetcher import fetch_dbnomics_series

_BEA_PROVIDER = "BEA"
_BEA_DATASET = "NIPA-T10105"
_BEA_CODE = "A191RC-Q"

DEFAULT_GDP_PUBLICATION_LAG_DAYS = 30


def fetch_nominal_gdp(
    *,
    force_refresh: bool = False,
    publication_lag_days: int = DEFAULT_GDP_PUBLICATION_LAG_DAYS,
    start: Optional[datetime.date] = None,
) -> pd.DataFrame:
    """Quarterly nominal GDP in $bn with approximate publication dates.

    Returns a DataFrame indexed by quarter-end reference date with columns
    ``gdp`` ($bn SAAR) and ``published`` (reference + lag).
    """
    raw = fetch_dbnomics_series(_BEA_PROVIDER, _BEA_DATASET, _BEA_CODE, quarterly=True, force_refresh=force_refresh)
    gdp = (raw / 1000.0).rename("gdp")  # $mn -> $bn
    if start is not None:
        gdp = gdp.loc[pd.Timestamp(start) :]
    published = pd.Series(gdp.index + pd.Timedelta(days=publication_lag_days), index=gdp.index, name="published")
    return pd.DataFrame({"gdp": gdp, "published": published})
