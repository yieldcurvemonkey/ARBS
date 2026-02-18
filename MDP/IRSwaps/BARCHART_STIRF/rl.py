import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

import pandas as pd
import pytz
import rateslib as rl
from pandas.tseries.offsets import DateOffset
from itertools import islice

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer


def _flatten_pricers(pricers: Dict[str, List["RLSTIRFuturePricer"]]) -> List["RLSTIRFuturePricer"]:
    # Each key maps to a list (often length 1). Keep all, preserve order.
    out: List["RLSTIRFuturePricer"] = []
    for lst in pricers.values():
        if lst:
            out.extend(lst)
    return out


def _sort_pricers_for_solver(
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
) -> List["RLSTIRFuturePricer"]:
    """
    Deterministic ordering for solver:
      1) by effective date
      2) then by maturity date
      3) then by rl_stirf_id (or symbol) as a stable tie-breaker
    """
    flat = _flatten_pricers(pricers)
    return sorted(
        flat,
        key=lambda p: (
            getattr(p, "_effective_date", None),
            getattr(p, "_maturity_date", None),
            getattr(p, "_rl_stirf_id", None) or getattr(p, "_meta_data", {}).get("symbol", ""),
        ),
    )


def _sort_nodes(nodes: Dict) -> Dict:
    # nodes keys are rateslib dt (datetime-like); dict insertion order matters
    return dict(sorted(nodes.items(), key=lambda kv: kv[0]))


def _as_node_ts(d: datetime.date, *, base_ts: pd.Timestamp) -> pd.Timestamp:
    """
    Create a timezone-aware pd.Timestamp for date `d` using the SAME time-of-day + tz as `base_ts`.
    """
    tod = base_ts.to_pydatetime().timetz()
    naive = rl.dt(d.year, d.month, d.day, tod.hour, tod.minute, tod.second, tod.microsecond)
    return naive
    # ts = pd.Timestamp(naive)
    # # localize to base tz (works for pytz/dateutil tz and tz strings)
    # if ts.tzinfo is None:
    #     return ts.tz_localize(base_ts.tz)
    # return ts.tz_convert(base_ts.tz)


def _build_stirf_nodes(
    *,
    timestamp: datetime.datetime,
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
    central_bank_dates: Dict[str, Dict[str, Tuple[datetime.date, datetime.date]]],
    reference_key: str,
    max_tenor_from_timestamp_months: int,
) -> Dict[pd.Timestamp, float]:
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
    nodes: Dict[pd.Timestamp, float] = {_as_node_ts(base_ts, base_ts=base_ts): 1.0}
    for d in node_dates:
        nodes[_as_node_ts(d, base_ts=base_ts)] = 1.0

    return nodes


def build_rl_stirf_turn_flies(
    turn_nodes: List[Union[datetime.date, datetime.datetime]], curve_id: str, spec: str, one_step: Optional[bool] = False
) -> Dict[str, rl.Fly]:
    args = {"termination": "1d", "spec": spec, "curves": curve_id}

    rl_irs = [rl.IRS(effective=node, **args) for node in turn_nodes]
    flies = {}
    if len(rl_irs) < 3:
        return flies

    if one_step:
        for i in range(0, len(rl_irs) - 2):
            fly = rl.Fly(rl_irs[i], rl_irs[i + 1], rl_irs[i + 2])
            flies[f"{i}/{i+1}/{i+2}"] = fly
    else:
        for i in range(3, len(rl_irs) - 2, 2):
            fly = rl.Fly(rl_irs[i], rl_irs[i + 1], rl_irs[i + 2])
            flies[f"{i}/{i+1}/{i+2}"] = fly

    return flies


class BARCHART_STIRF_CURVE:

    def __init__(self):
        self.stirf_mdp = STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")

        self._STIRF_CURVE_CONFIGS = {
            "USD-SOFR-1D-Q8": {
                "fetch_pricers_func": self._usd_sofr_1d_q8,
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "usd_irs_lt_2y",
            },
            "USD-SOFR-1D-Q12x3": {
                "fetch_pricers_func": self._usd_sofr_1d_q12x3,
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "usd_irs_lt_2y",
            },
        }

    def _usd_sofr_1d_q8(self, timestamp: datetime.datetime, kwargs={}):
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

    def _usd_sofr_1d_q12x3(self, timestamp: datetime.datetime, kwargs={}):
        pricers: Dict[str, List[RLSTIRFuturePricer]] = self.stirf_mdp.get_data(
            {
                "symbols": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",

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
        if type(timestamp) == str and timestamp.lower() == "live":
            timestamp = datetime.datetime.now(tz=pytz.timezone("America/New_York"))
        else:
            assert type(timestamp) == datetime.datetime, "timestamp must be am actually timestamp with defined hour, minute"
            assert timestamp.tzinfo is not None and timestamp.tzinfo.utcoffset(timestamp) is not None, "timestamp must be timezone aware"
            assert timestamp.astimezone(pytz.utc) < datetime.datetime.now(tz=pytz.utc), "in the future"

        assert curve_name in self._STIRF_CURVE_CONFIGS, f"{curve_name} not defined in configs"

        pricers: Dict[str, List[RLSTIRFuturePricer]] = self._STIRF_CURVE_CONFIGS[curve_name]["fetch_pricers_func"](timestamp=timestamp, kwargs=kwargs)
        cfg = self._STIRF_CURVE_CONFIGS[curve_name]

        pricers: Dict[str, List[RLSTIRFuturePricer]] = cfg["fetch_pricers_func"](timestamp=timestamp, kwargs=kwargs)

        nodes = _build_stirf_nodes(
            timestamp=timestamp,
            pricers=pricers,
            central_bank_dates=_CENTRAL_BANK_DATES,
            reference_key=cfg["reference_key"],
            max_tenor_from_timestamp_months=cfg["max_tenor_from_timestamp_months"],
        )
        nodes = _sort_nodes(nodes)

        rl_curve = rl.Curve(
            nodes=nodes,
            id=cfg["reference_key"],
            convention=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["DayCounter"],
            calendar=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["Calendar"],
            modifier=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["BusinessConvention"],
            interpolation="log_linear",
        )

        sorted_pricers = _sort_pricers_for_solver(pricers)
        instruments = [p.build_pricable() for p in sorted_pricers]
        s = [p._rate for p in sorted_pricers]
        weights = [1.0] * len(sorted_pricers)

        def one_day_irs(eff_date):
            return rl.IRS(
                effective=eff_date,
                termination="1b",
                spec=cfg["rl_irs_spec"],
                curves=cfg["reference_key"],
            )

        def butterfly(d0, d1, d2):
            return rl.Spread(
                rl.Spread(one_day_irs(d0), one_day_irs(d1)),
                rl.Spread(one_day_irs(d1), one_day_irs(d2)),
            )

        meeting_dates = sorted(k for k in nodes.keys())
        bflies = [butterfly(meeting_dates[i - 1], meeting_dates[i], meeting_dates[i + 1]) for i in range(1, len(meeting_dates) - 1)]
        pseudo_targets = [0.0] * len(bflies)

        instruments = instruments + bflies
        s = s + pseudo_targets
        weights = [1.0] * len(pricers) + [1e-8] * len(bflies)

        rl_solver = rl.Solver(
            curves=[rl_curve],
            instruments=instruments,
            s=s,
            id=curve_name,
            weights=weights,
            func_tol=1e-5,
            conv_tol=1e-5,
        )

        return rl_curve, rl_solver
