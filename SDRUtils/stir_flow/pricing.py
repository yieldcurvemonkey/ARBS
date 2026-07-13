"""Curve snapshot rule + IRSwapQuery pricing wrapper (spec sections 3-4)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytz

from SDRUtils.stir_flow import config

NY = pytz.timezone("America/New_York")


def snap_timestamp(orig_ts, exec_ts):
    ts = orig_ts
    if ts is None or (isinstance(ts, float) and ts != ts) or pd.isna(ts):
        ts = exec_ts
    et = pd.Timestamp(ts).tz_convert(NY)
    et = et.replace(second=0, microsecond=0) - pd.Timedelta(minutes=1)
    return NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))


@dataclasses.dataclass
class LegPricing:
    mid_pct: float
    npv_pay: float | None
    pv01: float


class CurvePricer:
    def __init__(self, mdp=None):
        if mdp is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            mdp = IRSwapsMDP(source=config.CURVE_SOURCE)
        self._mdp = mdp
        self._handles: dict = {}

    def handle(self, curve_name: str, ts):
        key = (curve_name, ts)
        if key not in self._handles:
            self._handles[key] = self._mdp._get_curve(curve_name=curve_name, timestamp=ts)
        return self._handles[key]

    def price_leg(self, curve_name, ts, effective_date, maturity_date,
                  notional, fixed_rate=None) -> LegPricing:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        h = self.handle(curve_name, ts)
        skw = {"notional": float(notional)}
        if fixed_rate is not None:
            skw["fixed_rate"] = float(fixed_rate)   # decimal in, decimal through
        q = IRSwapQuery(
            curve=curve_name,
            effective_date=pd.Timestamp(effective_date).date(),
            maturity_date=pd.Timestamp(maturity_date).date(),
            structure_kwargs=skw,
        ).resolve_query(ts, pricer_or_curve=h)
        pkg, rws = q.resolve_package(pricer_or_curve=h)
        vmap = q.build_value_map(pricer_or_curve=h, package=pkg, risk_weights=rws)
        mid = float(vmap.apply(value=IRSwapValue.RATE))
        npv = float(vmap.apply(value=IRSwapValue.NPV)) if fixed_rate is not None else None
        pv01 = float(vmap.apply(value=IRSwapValue.PV01))
        return LegPricing(mid_pct=mid, npv_pay=npv, pv01=pv01)
