"""Fed H.4.1 weekly Wednesday levels via the DBnomics mirror.

Series (all $mn at source, returned in $bn):
  reserves : RESH4R_N.WW      -- reserve balances with F.R. Banks
  rrp      : RESPPLLRD_N.WW   -- overnight reverse repo (others)
  tga      : RESPPLLDT_N.WW   -- Treasury General Account

Publication timing: the H.4.1 is released Thursday ~16:30 ET covering the
prior Wednesday.  ``publication_date`` stamps each Wednesday observation with
the calendar date on which it became public knowledge; a 16:30 ET release is
treated as usable from the *next* calendar day for an end-of-day decision
process (see BT/serff SerffDataConfig.h41_available_next_day).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from MDP.USMoneyMarkets.dbnomics_fetcher import fetch_dbnomics_series

_H41_PROVIDER = "FED"
_H41_DATASET = "H41"

_H41_CODES: Dict[str, str] = {
    "reserves": "RESH4R_N.WW",
    "rrp": "RESPPLLRD_N.WW",
    "tga": "RESPPLLDT_N.WW",
}


@dataclass(frozen=True)
class H41Series:
    """A weekly H.4.1 series with its publication dates.

    values  : $bn, indexed by Wednesday reference date
    published : reference date -> calendar date the release hit the wire
    """

    name: str
    values: pd.Series
    published: pd.Series

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame({self.name: self.values, "published": self.published})


def _publication_dates(reference_dates: pd.DatetimeIndex, release_lag_days: int = 1) -> pd.Series:
    """H.4.1 release date per Wednesday reference date (Thursday = Wed + 1).

    Federal holidays occasionally shift the release by a day; a 1-day
    approximation is used (the model consumes it through an additional
    next-day availability lag, so a holiday slip is absorbed conservatively
    only when ``release_lag_days`` is raised).
    """
    return pd.Series(
        reference_dates + pd.Timedelta(days=release_lag_days),
        index=reference_dates,
        name="published",
    )


def fetch_h41_series(
    name: str,
    *,
    force_refresh: bool = False,
    release_lag_days: int = 1,
    start: Optional[datetime.date] = None,
) -> H41Series:
    """Fetch one H.4.1 weekly series ('reserves', 'rrp' or 'tga') in $bn."""
    try:
        code = _H41_CODES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown H41 series {name!r}; expected one of {sorted(_H41_CODES)}") from exc

    raw = fetch_dbnomics_series(_H41_PROVIDER, _H41_DATASET, code, force_refresh=force_refresh)
    values = (raw / 1000.0).rename(name)  # $mn -> $bn
    if start is not None:
        values = values.loc[pd.Timestamp(start) :]
    published = _publication_dates(pd.DatetimeIndex(values.index), release_lag_days)
    return H41Series(name=name, values=values, published=published)
