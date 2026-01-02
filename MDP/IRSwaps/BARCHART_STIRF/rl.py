import datetime
import pandas as pd
from typing import Dict, List

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES


import datetime
import pandas as pd
from pandas.tseries.offsets import DateOffset
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


def _flatten_pricers(pricers: Dict[str, List["RLSTIRFuturePricer"]]) -> List["RLSTIRFuturePricer"]:
    # Each key maps to a list (often length 1). Keep all, preserve order.
    out: List["RLSTIRFuturePricer"] = []
    for lst in pricers.values():
        if lst:
            out.extend(lst)
    return out


def _as_node_ts(d: datetime.date, *, base_ts: pd.Timestamp) -> pd.Timestamp:
    """
    Create a timezone-aware pd.Timestamp for date `d` using the SAME time-of-day + tz as `base_ts`.
    """
    tod = base_ts.to_pydatetime().timetz()
    naive = datetime.datetime(d.year, d.month, d.day, tod.hour, tod.minute, tod.second, tod.microsecond)
    ts = pd.Timestamp(naive)
    # localize to base tz (works for pytz/dateutil tz and tz strings)
    if ts.tzinfo is None:
        return ts.tz_localize(base_ts.tz)
    return ts.tz_convert(base_ts.tz)


def _build_stirf_nodes(
    *,
    timestamp: datetime.datetime,
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
    central_bank_dates: Dict[str, Dict[str, Tuple[datetime.date, datetime.date]]],
    reference_key: str,
    max_tenor_from_timestamp_months: int,
) -> Dict[pd.Timestamp, float]:
    """
    Nodes rule (as per your comments):
      1) nodes anchored at timestamp
      2) nodes should be from _CENTRAL_BANK_DATES up to horizon
         - if CB schedule extends beyond horizon, STOP at max CB date <= horizon
      3) if CB schedule does NOT extend beyond horizon (i.e. all CB dates < horizon),
         then append pricer maturity dates to extend nodes (up to horizon).
    """
    assert isinstance(timestamp, datetime.datetime)
    assert timestamp.tzinfo is not None and timestamp.tzinfo.utcoffset(timestamp) is not None

    base_ts = pd.Timestamp(timestamp)
    base_date = timestamp.date()
    horizon_date = (base_ts + DateOffset(months=max_tenor_from_timestamp_months)).date()

    # --- central bank end dates (period boundaries) ---
    cb_map = central_bank_dates.get(reference_key, {})
    all_cb_ends: List[datetime.date] = sorted({end for (_start, end) in cb_map.values()})

    cb_extends_beyond_horizon = bool(all_cb_ends) and (max(all_cb_ends) > horizon_date)

    # take CB ends in (base_date, horizon_date]
    cb_ends_in_range = [d for d in all_cb_ends if (d > base_date and d <= horizon_date)]

    # if horizon is before the next CB end (rare, but handle), include the next end after base_date
    if not cb_ends_in_range:
        next_end = min((d for d in all_cb_ends if d > base_date), default=None)
        if next_end is not None:
            cb_ends_in_range = [next_end]

    node_dates: List[datetime.date] = list(cb_ends_in_range)
    last_cb_date: Optional[datetime.date] = max(node_dates) if node_dates else None

    # --- extend with pricer maturities only if CB schedule does NOT cover the horizon ---
    if (not cb_extends_beyond_horizon) and pricers:
        flat = _flatten_pricers(pricers)
        pricer_mats = sorted({p._maturity_date for p in flat if getattr(p, "_maturity_date", None) is not None})

        cutoff = last_cb_date or base_date
        extra = [d for d in pricer_mats if (d > cutoff and d <= horizon_date)]
        node_dates.extend(extra)

    # de-dupe + sort
    node_dates = sorted(set(node_dates))

    # build nodes dict (values are placeholders / initial guesses)
    nodes: Dict[pd.Timestamp, float] = {base_ts: 1.0}
    for d in node_dates:
        nodes[_as_node_ts(d, base_ts=base_ts)] = 1.0

    return nodes


class BARCHART_STIRF_CURVE:

    def __init__(self):
        self.stirf_mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")

        self._STIRF_CURVE_CONFIGS = {
            "USD-SOFR-1D-Q12": {
                "fetch_pricers_func": self._usd_sofr_1d_q12,
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 360,
            },
        }

    def _usd_sofr_1d_q12(self, timestamp: datetime.datetime, kwargs={}):
        pricers: Dict[str, List[RLSTIRFuturePricer]] = self.stirf_mdp.get_data(
            {
                "symbols": [
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "timestamp": timestamp,
            }
            | kwargs
        )
        return pricers

    def build_curve(self, curve_name: str, timestamp: datetime.datetime, kwargs={}):
        assert type(timestamp) == datetime.datetime, "timestamp must be am actually timestamp with defined hour, minute"
        assert timestamp.tzinfo is not None and timestamp.tzinfo.utcoffset(timestamp) is not None, "timestamp must be timezone aware"
        assert curve_name in self._STIRF_CURVE_CONFIGS, f"{curve_name} not defined in configs"

        pricers: Dict[str, List[RLSTIRFuturePricer]] = self._STIRF_CURVE_CONFIGS[curve_name]["fetch_pricers_func"](timestamp=timestamp, kwargs=kwargs)

        return _build_stirf_nodes(
            timestamp=timestamp,
            pricers=pricers,
            central_bank_dates=_CENTRAL_BANK_DATES,
            reference_key=self._STIRF_CURVE_CONFIGS[curve_name]["reference_key"],
            max_tenor_from_timestamp_months=self._STIRF_CURVE_CONFIGS[curve_name]["max_tenor_from_timestamp_months"],
        )
