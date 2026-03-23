from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

import numpy as np
import pandas as pd
import QuantLib as ql

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from MDP.MarketDataProvider import MarketDataProvider
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.Base.query_resolution import resolve_query
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve

_CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
_Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")
_SPREAD_ADJUSTMENT_HORIZON_TENOR = "3M"
_SPREAD_ADJUSTMENT_HORIZON_YEARS = 3.0 / 12.0


def _irs_value_set(*names: str) -> set[IRSwapValue]:
    return {
        value
        for value in (getattr(IRSwapValue, name, None) for name in names)
        if value is not None
    }


_SPREADOVER_VALUES = {
    IRSwapValue.SPREADOVER,
} | _irs_value_set(
    "SPREADOVER_CARRY_ADJUSTED",
    "SPREADOVER_ROLL_ADJUSTED",
    "SPREADOVER_CR_ADJUSTED",
)
_MMSS_VALUES = {IRSwapValue.MMSS} | _irs_value_set(
    "MMSS_CARRY_ADJUSTED",
    "MMSS_ROLL_ADJUSTED",
    "MMSS_CR_ADJUSTED",
)
_BENCHMARK_SPREAD_VALUES = _SPREADOVER_VALUES | _MMSS_VALUES
_CARRY_ADJUSTED_VALUES = _irs_value_set(
    "SPREADOVER_CARRY_ADJUSTED",
    "MMSS_CARRY_ADJUSTED",
)
_ROLL_ADJUSTED_VALUES = _irs_value_set(
    "SPREADOVER_ROLL_ADJUSTED",
    "MMSS_ROLL_ADJUSTED",
)
_CR_ADJUSTED_VALUES = _irs_value_set(
    "SPREADOVER_CR_ADJUSTED",
    "MMSS_CR_ADJUSTED",
)
_ASW_VALUES = {
    IRSwapValue.PAR_PAR_ASW,
    IRSwapValue.TRUE_ASW,
    IRSwapValue.PROCEEDS_ASW,
    IRSwapValue.MARKET_ASW,
}


def _ct_alias_to_y(tenor: str) -> str:
    return _CT_RE.sub(r"\1Y", str(tenor))


def _y_alias_to_ct(tenor: str) -> str:
    return _Y_RE.sub(r"CT\1", str(tenor))


def _normalize_value(value: Any) -> IRSwapValue:
    if isinstance(value, IRSwapValue):
        return value
    if isinstance(value, str):
        return IRSwapValue[value.upper()]
    raise TypeError(f"Unsupported IR swap spread value: {value!r}")


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not np.isfinite(out):
        return None
    return out


def _coerce_date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, ql.Date):
        return datetime.date(value.year(), value.month(), value.dayOfMonth())
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _to_ql_date(value: datetime.date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _normalize_coupon_pct(cpn_raw: float | None) -> float | None:
    if cpn_raw is None or not np.isfinite(cpn_raw):
        return None
    cpn = float(cpn_raw)
    if abs(cpn) <= 1.0:
        cpn *= 100.0
    return cpn


def _coupon_accrual_price_per_100(
    *,
    issue_date: datetime.date | None,
    maturity_date: datetime.date | None,
    coupon_pct: float | None,
    start_date: datetime.date,
    end_date: datetime.date,
) -> float | None:
    if end_date <= start_date:
        return 0.0

    cpn = _normalize_coupon_pct(coupon_pct)
    if issue_date is not None and maturity_date is not None and cpn is not None:
        try:
            cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
            sched = ql.Schedule(
                _to_ql_date(issue_date),
                _to_ql_date(maturity_date),
                ql.Period(6, ql.Months),
                cal,
                ql.ModifiedFollowing,
                ql.ModifiedFollowing,
                ql.DateGeneration.Backward,
                False,
            )
            qs = _to_ql_date(start_date)
            qe = _to_ql_date(end_date)
            total = 0.0
            cpn_per_period = cpn / 2.0

            for idx in range(len(sched) - 1):
                a0 = sched[idx]
                a1 = sched[idx + 1]
                if a1 <= qs or a0 >= qe:
                    continue
                ov_start = a0 if a0 > qs else qs
                ov_end = a1 if a1 < qe else qe
                ov_days = int(ov_end - ov_start)
                period_days = int(a1 - a0)
                if ov_days <= 0 or period_days <= 0:
                    continue
                total += cpn_per_period * (ov_days / period_days)

            if total > 0.0:
                return float(total)
        except Exception:
            pass

    if cpn is None:
        return None
    days = max((end_date - start_date).days, 0)
    return float(cpn) * (days / 365.0)


def _advance_horizon_date(
    *,
    as_of_date: datetime.date,
    pricer: Any = None,
    horizon_tenor: str = _SPREAD_ADJUSTMENT_HORIZON_TENOR,
) -> datetime.date:
    if pricer is not None:
        try:
            advanced = pricer.calendar_advance(as_of_date, horizon_tenor)
            advanced_date = _coerce_date(advanced)
            if advanced_date is not None:
                return advanced_date
        except Exception:
            pass

    try:
        cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        qd = _to_ql_date(as_of_date)
        advanced = cal.advance(qd, ql.Period(horizon_tenor), ql.ModifiedFollowing)
        return datetime.date(advanced.year(), advanced.month(), advanced.dayOfMonth())
    except Exception:
        return as_of_date + datetime.timedelta(days=91)


def _load_sofr_fixing_pct(as_of_date: datetime.date) -> float | None:
    from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

    try:
        fixings = _fetch_fixings(as_of_date=as_of_date, curve_name="USD-SOFR-1D")
    except Exception:
        return None
    if fixings is None:
        return None

    try:
        series = pd.Series(fixings).copy()
    except Exception:
        return None
    if series.empty:
        return None

    idx = pd.to_datetime(series.index, errors="coerce")
    vals = pd.to_numeric(series, errors="coerce")
    tmp = pd.DataFrame({"fixing": vals}, index=idx)
    tmp = tmp[~tmp.index.isna()]
    tmp = tmp.dropna(subset=["fixing"])
    tmp = tmp[tmp.index.date < as_of_date].sort_index()
    if tmp.empty:
        return None

    sofr_pct = float(tmp["fixing"].iloc[-1])
    if not np.isfinite(sofr_pct):
        return None
    if abs(sofr_pct) <= 1.0:
        sofr_pct *= 100.0
    return sofr_pct


def _fit_roll_spline(ttm: np.ndarray, ytm: np.ndarray):
    from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator

    if ttm.size == 0 or ytm.size == 0:
        return None

    df = pd.DataFrame({"ttm": ttm, "ytm": ytm})
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["ttm", "ytm"])
    if df.empty:
        return None

    dedup = df.groupby("ttm", as_index=False)["ytm"].mean().sort_values(by="ttm")
    if len(dedup) < 4:
        return None

    x = dedup["ttm"].to_numpy(dtype=float)
    y = dedup["ytm"].to_numpy(dtype=float)
    degree = max(1, min(3, len(x) - 1))
    try:
        interp = GeneralCurveInterpolator(x=x, y=y)
        return interp.b_spline1_interpolation(k=degree, return_func=True)
    except Exception:
        return None


def _curve_name_from_pricer(curve: _IRSwapGenericCurve, fallback: Optional[str] = None) -> str:
    for key in ("requested_curve_name", "curve_name", "reference_key"):
        try:
            meta = curve.meta()
            if isinstance(meta, Mapping):
                candidate = meta.get(key)
                if candidate:
                    return str(candidate)
        except Exception:
            continue
    if fallback:
        return str(fallback)
    raise KeyError("Could not determine QuantLib curve definition key for asset swap pricing.")


def fair_asset_swap_spread_bps(
    swap_curve: _IRSwapGenericCurve,
    frb_pricer: _FixedRateBondGenericPricer,
    *,
    curve_name: Optional[str] = None,
    par_par_asw: bool = True,
) -> float:
    from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_discount_curve_from_nodes
    from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
    from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

    ql.Settings.instance().evaluationDate = datetime_to_ql_date(swap_curve.reference_date())

    ql_bond = frb_pricer.build_fixed_rate_bond(
        issue_date=frb_pricer.issue_date(),
        maturity_date=frb_pricer.maturity_date(),
        coupon=frb_pricer.coupon(),
        notional=100,
    )

    ql_curve_handle = ql.YieldTermStructureHandle(
        build_discount_curve_from_nodes(
            swap_curve.nodes(),
            ql_dc=ql.Actual360(),
            ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            interpolation_algo="df_log_linear",
        )
    )
    definition_key = _curve_name_from_pricer(swap_curve, fallback=curve_name)
    ql_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[definition_key]["ReferenceRate"](ql_curve_handle)

    index_fixings = swap_curve.index()
    if hasattr(index_fixings, "to_dict"):
        fixings_dict = index_fixings.to_dict()
    elif isinstance(index_fixings, Mapping):
        fixings_dict = dict(index_fixings)
    else:
        fixings_dict = {}

    for d, f in fixings_dict.items():
        try:
            ql_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
        except Exception:
            continue

    swap = ql.AssetSwap(
        True,
        ql_bond,
        frb_pricer.clean_price(),
        ql_index,
        0.0,
        ql.Schedule(
            datetime_to_ql_date(frb_pricer.issue_date()),
            datetime_to_ql_date(frb_pricer.maturity_date()),
            ql.Period(6, ql.Months),
            ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            ql.ModifiedFollowing,
            ql.ModifiedFollowing,
            ql.DateGeneration.Forward,
            False,
        ),
        ql_index.dayCounter(),
        par_par_asw,
    )
    swap.setPricingEngine(ql.DiscountingSwapEngine(ql_curve_handle))
    return float(swap.fairSpread()) * 10_000


@dataclass
class IRSwapSpreadPricer:
    swap_curve: _IRSwapGenericCurve
    bond_pricer: _FixedRateBondGenericPricer
    value: IRSwapValue
    swap_query: Optional[IRSwapQuery] = None
    requested_curve_name: Optional[str] = None
    adjustment_bps: Dict[str, float] = field(default_factory=dict)
    meta_data: Dict[str, Any] = field(default_factory=dict)

    def _resolve_swap_query(self) -> IRSwapQuery:
        if self.swap_query is None:
            raise ValueError("Swap spread pricing requires an IRSwapQuery for the swap leg.")
        return resolve_query(
            self.swap_query,
            timestamp=self.swap_curve.reference_date(),
            pricer_or_curve=self.swap_curve,
        )

    def swap_rate_percent(self) -> float:
        q_eff = self._resolve_swap_query()
        if getattr(q_eff, "structure", None) is not None and str(q_eff.structure.name) != "OUTRIGHT":
            raise NotImplementedError("IRSwapSpreadsMDP currently supports outright IRS-vs-bond spreads only.")

        package, risk_weights = q_eff.resolve_package(
            pricer_or_curve=self.swap_curve,
            is_for_timeseries=True,
        )
        value_map = q_eff.build_value_map(
            pricer_or_curve=self.swap_curve,
            package=package,
            risk_weights=risk_weights,
        )
        return float(value_map.apply(value=q_eff.value, **(q_eff.value_kwargs or {})))

    def cash_yield_percent(self) -> float:
        return float(self.bond_pricer.ytm())

    def spread_bps(self) -> float:
        return (self.swap_rate_percent() - self.cash_yield_percent()) * 100.0

    def asset_swap_spread_bps(self) -> float:
        return fair_asset_swap_spread_bps(
            self.swap_curve,
            self.bond_pricer,
            curve_name=self.requested_curve_name,
            par_par_asw=self.value == IRSwapValue.PAR_PAR_ASW,
        )

    def value_bps(self) -> float:
        if self.value in _BENCHMARK_SPREAD_VALUES:
            spread_bps = self.spread_bps()
            if self.value in _CARRY_ADJUSTED_VALUES:
                return spread_bps + float(self.adjustment_bps.get("carry", np.nan))
            if self.value in _ROLL_ADJUSTED_VALUES:
                return spread_bps + float(self.adjustment_bps.get("roll", np.nan))
            if self.value in _CR_ADJUSTED_VALUES:
                return spread_bps + float(self.adjustment_bps.get("carry_and_roll", np.nan))
            return spread_bps
        if self.value in _ASW_VALUES:
            return self.asset_swap_spread_bps()
        raise NotImplementedError(f"Unsupported IRSwap spread metric: {self.value}")


class IRSwapSpreadsMDP(MarketDataProvider[IRSwapSpreadPricer]):
    """
    IRS-vs-UST spread provider backed by an IRSwapsMDP and a FixedRateBondsMDP.

    Supported request shape:
        {
            "curve_name": "USD-SOFR-1D",
            "timestamp": date|datetime|"live",
            "value": IRSwapValue.MMSS | IRSwapValue.SPREADOVER | IRSwapValue.PAR_PAR_ASW | ...,
            "tenor": "CT10" | "10Y" | "<cusip>",
        }

    Optional keys:
        swap_query: explicit IRSwapQuery for the swap leg
        bond_symbol / cusip / symbol: explicit cash-leg identifier
        curve_request: dict of extra kwargs forwarded to IRSwapsMDP.get_pricer()
        bond_request: dict of extra kwargs forwarded to FixedRateBondsMDP.get_pricer()
    """

    def __init__(
        self,
        irs_source: str = "CME_NY_EOD_LIVE-ql_basic",
        frb_source: str = "USTS_FEDINVEST_WSJ_LIVE-QL",
        *,
        source_a: Optional[str] = None,
        source_b: Optional[str] = None,
        _irs_mdp: Optional[IRSwapsMDP] = None,
        _frb_mdp: Optional[FixedRateBondsMDP] = None,
        _mdp_a: Optional[Any] = None,
        _mdp_b: Optional[Any] = None,
        **kwargs: Any,
    ):
        super().__init__(source="IRSWAP_SPREAD", **kwargs)

        if source_a is not None:
            irs_source = source_a
        if source_b is not None:
            frb_source = source_b

        self.irs_mdp = _irs_mdp or _mdp_a or IRSwapsMDP(source=irs_source)
        self.frb_mdp = _frb_mdp or _mdp_b or FixedRateBondsMDP(source=frb_source)
        self._cash_adjustment_cache: Dict[tuple[str, str], Dict[str, Dict[str, float]]] = {}

    @staticmethod
    def _as_of_date(timestamp: Any) -> datetime.date:
        if timestamp == "live":
            return datetime.date.today()
        if isinstance(timestamp, datetime.datetime):
            return timestamp.date()
        if isinstance(timestamp, datetime.date):
            return timestamp
        return pd.Timestamp(timestamp).date()

    @staticmethod
    def _timestamp_cache_key(timestamp: Any) -> str:
        if timestamp == "live":
            return "live"
        if isinstance(timestamp, datetime.datetime):
            return timestamp.isoformat()
        if isinstance(timestamp, datetime.date):
            return timestamp.isoformat()
        return str(timestamp)

    @staticmethod
    def _bond_cusip_from_pricer(
        bond_pricer: _FixedRateBondGenericPricer,
        *,
        fallback_symbol: str,
    ) -> str:
        try:
            meta = bond_pricer.meta() or {}
        except Exception:
            meta = {}
        candidate = meta.get("cusip") if isinstance(meta, Mapping) else None
        return str(candidate or fallback_symbol)

    def _build_cash_adjustment_context(
        self,
        *,
        curve_name: str,
        timestamp: Any,
    ) -> Dict[str, Dict[str, float]]:
        cache_key = (str(curve_name), self._timestamp_cache_key(timestamp))
        cached = self._cash_adjustment_cache.get(cache_key)
        if cached is not None:
            return cached

        from scripts._ust_service_common import resolve_bond_universe

        as_of_date = self._as_of_date(timestamp)
        symbols = resolve_bond_universe(as_of_date=as_of_date, tier="otr-plus-old")
        if not symbols:
            ctx = {"carry": {}, "roll": {}, "carry_and_roll": {}}
            self._cash_adjustment_cache[cache_key] = ctx
            return ctx

        pricers = self.frb_mdp.get_pricer(
            {
                "cusips": list(symbols),
                "timestamp": timestamp,
                "show_tqdm": False,
            }
        )

        rows: list[Dict[str, Any]] = []
        for symbol, pricer in (pricers or {}).items():
            try:
                meta = pricer.meta() or {}
            except Exception:
                meta = {}
            maturity_date = _coerce_date(meta.get("maturity_date")) or _coerce_date(pricer.maturity_date() if hasattr(pricer, "maturity_date") else None)
            issue_date = _coerce_date(meta.get("issue_date")) or _coerce_date(pricer.issue_date() if hasattr(pricer, "issue_date") else None)
            coupon = _safe_float(meta.get("cpn")) if isinstance(meta, Mapping) else None
            if coupon is None and hasattr(pricer, "coupon"):
                coupon = _safe_float(pricer.coupon())
            actual_cusip = str(meta.get("cusip") or symbol)
            rows.append(
                {
                    "cusip": actual_cusip,
                    "ytm": _safe_float(pricer.ytm() if hasattr(pricer, "ytm") else None),
                    "mdur": _safe_float(pricer.mod_duration() if hasattr(pricer, "mod_duration") else None),
                    "dirty_price": _safe_float(pricer.dirty_price() if hasattr(pricer, "dirty_price") else None),
                    "issue_date_eff": issue_date,
                    "maturity_date_eff": maturity_date,
                    "coupon_eff": coupon,
                    "ttm": max((maturity_date - as_of_date).days, 0) / 365.25 if maturity_date is not None else np.nan,
                }
            )

        merged = pd.DataFrame(rows)
        if merged.empty:
            ctx = {"carry": {}, "roll": {}, "carry_and_roll": {}}
            self._cash_adjustment_cache[cache_key] = ctx
            return ctx
        merged = merged.drop_duplicates(subset=["cusip"], keep="first")

        carry_map: Dict[str, float] = {}
        roll_map: Dict[str, float] = {}
        carry_roll_map: Dict[str, float] = {}

        sofr_pct = _load_sofr_fixing_pct(as_of_date=as_of_date)
        horizon_date = _advance_horizon_date(as_of_date=as_of_date, horizon_tenor=_SPREAD_ADJUSTMENT_HORIZON_TENOR)
        if sofr_pct is not None:
            sofr_dec = float(sofr_pct) / 100.0
            for row in merged.itertuples(index=False):
                cusip = str(getattr(row, "cusip"))
                dirty0 = _safe_float(getattr(row, "dirty_price", None))
                mdur = _safe_float(getattr(row, "mdur", None))
                if dirty0 is None or mdur is None or dirty0 <= 0 or mdur <= 0 or horizon_date <= as_of_date:
                    continue
                dv01 = mdur * dirty0 / 10000.0
                if dv01 <= 0 or not np.isfinite(dv01):
                    continue
                coupon_accrual = _coupon_accrual_price_per_100(
                    issue_date=_coerce_date(getattr(row, "issue_date_eff", None)),
                    maturity_date=_coerce_date(getattr(row, "maturity_date_eff", None)),
                    coupon_pct=_safe_float(getattr(row, "coupon_eff", None)),
                    start_date=as_of_date,
                    end_date=horizon_date,
                )
                if coupon_accrual is None:
                    continue
                horizon_days = max((horizon_date - as_of_date).days, 1)
                financing_cost = dirty0 * sofr_dec * (horizon_days / 360.0)
                carry_bps = (coupon_accrual - financing_cost) / dv01
                if np.isfinite(carry_bps):
                    carry_map[cusip] = float(carry_bps)

        roll_func = _fit_roll_spline(
            ttm=merged["ttm"].to_numpy(dtype=float),
            ytm=merged["ytm"].to_numpy(dtype=float),
        )
        if roll_func is not None:
            fit_df = (
                merged[["ttm", "ytm"]]
                .replace([np.inf, -np.inf], np.nan)
                .dropna(subset=["ttm", "ytm"])
                .groupby("ttm", as_index=False)["ytm"]
                .mean()
                .sort_values(by="ttm")
            )
            if not fit_df.empty:
                fit_min = float(fit_df["ttm"].iloc[0])
                fit_max = float(fit_df["ttm"].iloc[-1])
                shifted_ttm = merged["ttm"] - _SPREAD_ADJUSTMENT_HORIZON_YEARS
                valid = (
                    merged["ttm"].notna()
                    & merged["ytm"].notna()
                    & shifted_ttm.notna()
                    & (shifted_ttm >= fit_min)
                    & (shifted_ttm <= fit_max)
                )
                if bool(valid.any()):
                    x_now = merged.loc[valid, "ttm"].to_numpy(dtype=float)
                    x_prev = shifted_ttm.loc[valid].to_numpy(dtype=float)
                    y_now = np.asarray(roll_func(x_now), dtype=float)
                    y_prev = np.asarray(roll_func(x_prev), dtype=float)
                    roll_bps = (y_now - y_prev) * 100.0
                    for cusip, value in zip(merged.loc[valid, "cusip"].astype(str), roll_bps):
                        if np.isfinite(value):
                            roll_map[str(cusip)] = float(value)

        all_cusips = set(carry_map) | set(roll_map) | set(merged["cusip"].astype(str))
        for cusip in all_cusips:
            carry = carry_map.get(cusip)
            roll = roll_map.get(cusip)
            if carry is None and roll is None:
                continue
            carry_roll_map[cusip] = float((carry or 0.0) + (roll or 0.0))

        ctx = {
            "carry": carry_map,
            "roll": roll_map,
            "carry_and_roll": carry_roll_map,
        }
        self._cash_adjustment_cache[cache_key] = ctx
        return ctx

    def _evaluate_swap_adjustment(
        self,
        *,
        swap_curve: _IRSwapGenericCurve,
        swap_query: IRSwapQuery,
        metric_value: IRSwapValue,
    ) -> float:
        structure_kwargs = dict(swap_query.structure_kwargs or {})
        structure_kwargs.pop("notional", None)
        structure_kwargs["bpv"] = -1
        metric_query = IRSwapQuery(
            structure=swap_query.structure,
            value=metric_value,
            tenor=swap_query.tenor,
            effective_date=swap_query.effective_date,
            maturity_date=swap_query.maturity_date,
            is_mms=swap_query.is_mms,
            curve=swap_query.curve,
            structure_kwargs=structure_kwargs,
            value_kwargs={"horizon": _SPREAD_ADJUSTMENT_HORIZON_TENOR},
            risk_weight=swap_query.risk_weight,
            name=swap_query.name,
            tags=swap_query.tags,
            meta=swap_query.meta,
            market_request=swap_query.market_request,
            mdp_time_key=swap_query.mdp_time_key,
        )
        resolved = resolve_query(
            metric_query,
            timestamp=swap_curve.reference_date(),
            pricer_or_curve=swap_curve,
        )
        package, risk_weights = resolved.resolve_package(
            pricer_or_curve=swap_curve,
            is_for_timeseries=True,
        )
        value_map = resolved.build_value_map(
            pricer_or_curve=swap_curve,
            package=package,
            risk_weights=risk_weights,
        )
        return float(value_map.apply(value=resolved.value, **(resolved.value_kwargs or {})))

    def _compute_adjustment_bps(
        self,
        *,
        curve_name: str,
        timestamp: Any,
        bond_symbol: str,
        bond_pricer: _FixedRateBondGenericPricer,
        swap_curve: _IRSwapGenericCurve,
        swap_query: Optional[IRSwapQuery],
    ) -> Dict[str, float]:
        if swap_query is None:
            raise ValueError("Adjusted swap spread values require a swap leg query.")

        cash_ctx = self._build_cash_adjustment_context(curve_name=curve_name, timestamp=timestamp)
        actual_cusip = self._bond_cusip_from_pricer(bond_pricer, fallback_symbol=bond_symbol)
        cash_carry = float(cash_ctx["carry"].get(actual_cusip, np.nan))
        cash_roll = float(cash_ctx["roll"].get(actual_cusip, np.nan))
        cash_carry_roll = float(cash_ctx["carry_and_roll"].get(actual_cusip, np.nan))

        swap_carry = self._evaluate_swap_adjustment(
            swap_curve=swap_curve,
            swap_query=swap_query,
            metric_value=IRSwapValue.CARRY_BPS_RUNNING,
        )
        swap_roll = self._evaluate_swap_adjustment(
            swap_curve=swap_curve,
            swap_query=swap_query,
            metric_value=IRSwapValue.ROLL_BPS_RUNNING,
        )
        swap_carry_roll = swap_carry + swap_roll

        return {
            "carry": cash_carry + swap_carry,
            "roll": cash_roll + swap_roll,
            "carry_and_roll": cash_carry_roll + swap_carry_roll,
        }

    @staticmethod
    def build_request_from_query(q: IRSwapQuery, timestamp: Any) -> Dict[str, Any]:
        request = dict(q.market_request or {})
        if q.curve is not None and "curve_name" not in request:
            request["curve_name"] = q.curve
        request[q.mdp_time_key] = timestamp
        request["value"] = q.value
        if q.tenor is not None:
            request["tenor"] = q.tenor
        return request

    @staticmethod
    def _resolve_bond_symbol(request: Mapping[str, Any], value: IRSwapValue) -> str:
        token = (
            request.get("bond_symbol")
            or request.get("cusip")
            or request.get("symbol")
            or request.get("tenor")
        )
        if token is None:
            raise ValueError("IR swap spread request requires 'tenor', 'bond_symbol', 'cusip', or 'symbol'.")

        token = str(token)
        if value in _SPREADOVER_VALUES and _Y_RE.search(token):
            return _y_alias_to_ct(token)
        return token

    @staticmethod
    def _build_swap_query(
        request: Mapping[str, Any],
        *,
        curve_name: str,
        value: IRSwapValue,
    ) -> Optional[IRSwapQuery]:
        if value not in _BENCHMARK_SPREAD_VALUES:
            return None

        explicit_query = request.get("swap_query")
        if explicit_query is not None:
            if not isinstance(explicit_query, IRSwapQuery):
                raise TypeError("request['swap_query'] must be an IRSwapQuery.")
            if explicit_query.value != IRSwapValue.RATE:
                return IRSwapQuery(
                    structure=explicit_query.structure,
                    value=IRSwapValue.RATE,
                    tenor=explicit_query.tenor,
                    effective_date=explicit_query.effective_date,
                    maturity_date=explicit_query.maturity_date,
                    is_mms=explicit_query.is_mms,
                    curve=explicit_query.curve or curve_name,
                    structure_kwargs=explicit_query.structure_kwargs,
                    value_kwargs=explicit_query.value_kwargs,
                    risk_weight=explicit_query.risk_weight,
                    name=explicit_query.name,
                    tags=explicit_query.tags,
                    meta=explicit_query.meta,
                    market_request=explicit_query.market_request,
                    mdp_time_key=explicit_query.mdp_time_key,
                )
            return explicit_query

        raw_tenor = request.get("swap_tenor") or request.get("tenor")
        if raw_tenor is None:
            raise ValueError("IR swap spread request requires 'tenor' or 'swap_tenor'.")

        tenor = str(raw_tenor)
        if value in _SPREADOVER_VALUES and _CT_RE.search(tenor):
            tenor = _ct_alias_to_y(tenor)

        return IRSwapQuery(
            curve=curve_name,
            tenor=tenor,
            value=IRSwapValue.RATE,
        )

    def get_pricer(self, request: Dict[str, Any]) -> IRSwapSpreadPricer:
        req = dict(request)
        value = _normalize_value(req.pop("value", req.pop("spread_type", IRSwapValue.MMSS)))
        curve_name = req.pop("curve_name", req.pop("curve", None))
        timestamp = req.pop("timestamp", None)

        if not curve_name:
            raise ValueError("IR swap spread request requires 'curve_name'.")
        if timestamp is None:
            raise ValueError("IR swap spread request requires 'timestamp'.")

        swap_query = self._build_swap_query(req, curve_name=str(curve_name), value=value)
        bond_symbol = self._resolve_bond_symbol(req, value)

        curve_request = dict(req.pop("curve_request", {}) or {})
        curve_request["curve_name"] = curve_name
        curve_request["timestamp"] = timestamp
        swap_curve = self.irs_mdp.get_pricer(dict(curve_request))

        bond_request = dict(req.pop("bond_request", {}) or {})
        bond_request["cusips"] = [bond_symbol]
        bond_request["timestamp"] = timestamp
        bond_pricers = self.frb_mdp.get_pricer(dict(bond_request))
        if not bond_pricers:
            raise RuntimeError(f"FixedRateBondsMDP returned no pricer for {bond_symbol!r} at {timestamp!r}.")

        bond_pricer = next(iter(bond_pricers.values()))
        adjustment_bps: Dict[str, float] = {}
        if value in (_CARRY_ADJUSTED_VALUES | _ROLL_ADJUSTED_VALUES | _CR_ADJUSTED_VALUES):
            adjustment_bps = self._compute_adjustment_bps(
                curve_name=str(curve_name),
                timestamp=timestamp,
                bond_symbol=bond_symbol,
                bond_pricer=bond_pricer,
                swap_curve=swap_curve,
                swap_query=swap_query,
            )
        return IRSwapSpreadPricer(
            swap_curve=swap_curve,
            bond_pricer=bond_pricer,
            value=value,
            swap_query=swap_query,
            requested_curve_name=str(curve_name),
            adjustment_bps=adjustment_bps,
            meta_data={
                "curve_name": curve_name,
                "timestamp": timestamp,
                "bond_symbol": bond_symbol,
                "value": value,
            },
        )
