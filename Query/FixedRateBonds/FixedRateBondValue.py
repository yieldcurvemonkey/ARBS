from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondPricableSpec
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds._FixedRateBondGenericPricable import _FixedRateBondGenericPricable
from Query.FixedRateBonds.carry_roll import (
    compute_carry_roll_frame,
    expand_pricer_universe_for_carry_roll,
    frame_supports_roll,
    normalize_horizon_spec,
    safe_float,
)
from Query.FixedRateBonds.spline_values import (
    MATURITY_BUCKETS,
    compute_spline_for_date,
    expand_pricer_universe_for_spline,
    parse_bucket,
)


class FixedRateBondValue(Enum):
    YTM = auto()
    CLEAN_PRICE = auto()
    DIRTY_PRICE = auto()
    NPV = auto()
    PV01 = auto()
    DV01 = auto()
    MOD_DURATION = auto()
    CONVEXITY = auto()
    CARRY_BPS_RUNNING = auto()
    ROLL_BPS_RUNNING = auto()
    CARRY_AND_ROLL_BPS_RUNNING = auto()

    # Spline-derived metrics
    SPLINE_SPREAD = auto()        # Per-CUSIP yield error vs fitted spline (bp)
    SPLINE_Z_SCORE = auto()       # Per-CUSIP z-score of yield error
    SPLINE_RMSE = auto()          # Whole-curve RMSE (bp) — date-level aggregate
    SPLINE_RMSE_BUCKET = auto()   # Maturity-bucket RMSE (bp) — pass bucket via value_kwargs

    # ------------------------------------------------------------------
    # QUOTE-ONLY values: the vendor's own published number, in bp.
    #
    # These are NOT computed here and have no local fallback. Each one needs
    # something this repo does not carry — OAS needs a term-structure model and
    # a call schedule, SPREAD_TSY needs the vendor's own benchmark choice — and
    # a locally computed "OAS" that was really a Z-spread would be worse than
    # no number at all. They are served today by the Citi Velocity bond source
    # ("USTS_CITIVELO-QL" / "USTS_CITIVELO-RL"); a pricer from any other source
    # RAISES rather than returning NaN or 0.0, because 0.0 is a perfectly
    # plausible spread and would be indistinguishable from a real one.
    # ------------------------------------------------------------------
    SPREAD_TSY = auto()           # Spread to the Treasury benchmark (bp)
    OAS = auto()                  # Option-adjusted spread (bp)
    ASW_SPREAD = auto()           # Asset-swap spread (bp); pass asw_currency="USD"
    CAS = auto()                  # Vendor's published CAS (bp)

    # ------------------------------------------------------------------
    # The REST of the vendor's per-bond vocabulary, one member per published
    # value. MEASURED 2026-08-08 by probing Citi's own 118-field dictionary
    # against the RATES.BOND tag path across ten country/asset-type universes:
    # 46 values serve, and a single US Treasury serves 44 of them. The bracketed
    # count is how many of the ten universes served it.
    #
    # An earlier answer of EIGHT came from a probe that used a ONE-WEEK window
    # against one bond, so "no rows in a week" was recorded as "does not exist".
    # That is how the whole carry/roll family, the OIS-spread family, the
    # yield-yield-spread family and every RFR variant went missing.
    #
    # ``CITI_`` marks the four this repo ALSO computes locally. Both are kept and
    # both are reachable: FRB_CITI_DURATION is Citi's published modified
    # duration, FRB_MOD_DURATION is the one solved here from Citi's PRICE. They
    # agree to 1.9e-05 years, and they are still different numbers with different
    # provenance - conflating them is how a silent source swap survives.
    #
    # All quote-only, like the four above: a pricer from a non-Velocity source
    # RAISES rather than returning 0.0.
    # ------------------------------------------------------------------
    ASSNP_RFR = auto()                   # ASSNP vs RFR  [10/10]
    ASW_RFR = auto()                     # ASW vs RFR  [10/10]
    CARRY_1M = auto()                    # Carry 1M  [10/10]
    CARRY_1Y = auto()                    # Carry 1Y  [10/10]
    CARRY_3M = auto()                    # Carry 3M  [10/10]
    CARRY_6M = auto()                    # Carry 6M  [10/10]
    CITI_DURATION = auto()               # Modified Duration  [10/10]
    CITI_DV01 = auto()                   # DV01  [10/10]
    CITI_PRICE = auto()                  # Price  [10/10]
    PRICING_ACCRUED = auto()             # Accrued Interest  [10/10]
    PRICING_CV01 = auto()                # CV01  [10/10]
    CITI_YIELD = auto()                  # Yield  [10/10]
    CAS_RFR = auto()                     # Coupon Adjusted Spread vs RFR  [9/10]
    OISSMM_RFR = auto()                  # OISSMM vs RFR  [9/10]
    OISS_RFR = auto()                    # OISS vs RFR  [9/10]
    YYS = auto()                         # YYS  [9/10]
    YYS_RFR = auto()                     # YYS vs RFR  [9/10]
    ZSPREAD = auto()                     # Z-Spread to Worst  [9/10]
    ASW = auto()                         # ASW  [8/10]
    ASWNP = auto()                       # ASWNP  [8/10]
    OAS_RFR = auto()                     # OAS vs RFR  [8/10]
    OISS = auto()                        # OISS  [8/10]
    OISSMM = auto()                      # OISSMM  [8/10]
    ROLL_1M = auto()                     # Roll 1M  [8/10]
    ROLL_1Y = auto()                     # Roll 1Y  [8/10]
    ROLL_3M = auto()                     # Roll 3M  [8/10]
    ROLL_6M = auto()                     # Roll 6M  [8/10]
    ROLLCARRY_1M = auto()                # Roll and Carry 1M  [7/10]
    ROLLCARRY_1Y = auto()                # Roll and Carry 1Y  [7/10]
    ROLLCARRY_3M = auto()                # Roll and Carry 3M  [7/10]
    ROLLCARRY_6M = auto()                # Roll and Carry 6M  [7/10]
    ASW_4_CHF = auto()                   # Asset Swap Spread, CHF, Quarterly  [6/10]
    ASW_4_EUR = auto()                   # Asset Swap Spread, EUR, Quarterly  [6/10]
    ASW_4_GBP = auto()                   # Asset Swap Spread, GBP, Quarterly  [6/10]
    ASW_4_USD = auto()                   # Asset Swap Spread, USD, Quarterly  [6/10]
    ASW_4_AUD = auto()                   # Asset Swap Spread, AUD, Quarterly  [5/10]
    ASW_4_JPY = auto()                   # Asset Swap Spread, JPY, Quarterly  [5/10]
    OISS_SOFR = auto()                   # OISS vs SOFR  [2/10]
    ASS_SOFR = auto()                    # Asset Swap Spread vs SOFR  [1/10]
    CAS_SOFR = auto()                    # Coupon Adjusted Spread vs SOFR  [1/10]
    SIMPLEYIELD = auto()                 # Simple Yield  [1/10]
    YIELD_WORST = auto()                 # Yield to Worst  [1/10]
    YYS_SOFR = auto()                    # Yield Yield Spread vs SOFR  [1/10]


# _frb_structure_sign_mapper = {
#     FixedRateBondStructure.OUTRIGHT: lambda rws: [abs(rws[0])],
#     FixedRateBondStructure.CURVE: lambda rws: [-1 * abs(rws[0]), abs(rws[1])],
#     FixedRateBondStructure.FLY: lambda rws: [-1 * abs(rws[0]), abs(rws[1]), -1 * abs(rws[2])],
# }
_frb_structure_sign_mapper = {
    FixedRateBondStructure.OUTRIGHT: lambda rws: rws,
    FixedRateBondStructure.CURVE: lambda rws: rws,
    FixedRateBondStructure.FLY: lambda rws: rws,
}
_frb_structure_legs_mapper = {
    1: (FixedRateBondStructure.OUTRIGHT, 1),
    2: (FixedRateBondStructure.CURVE, 100),
    3: (FixedRateBondStructure.FLY, 100),
}


def calc_spread_rate(
    pricer: Dict[str, _FixedRateBondGenericPricer],
    package: List[FixedRateBondPricableSpec],
    risk_weights: List[float],
) -> float:
    risk_weights = _frb_structure_sign_mapper[_frb_structure_legs_mapper[len(package)][0]](risk_weights)
    return sum(risk_weights[i] * abs(_rebuild_pricer(_resolve_leg_pricer(pricer, leg), leg).ytm()) for i, leg in enumerate(package))


def _quote_kwargs(pr: _FixedRateBondGenericPricer) -> Dict[str, Any]:
    clean_price = getattr(pr, "_clean_price", None)
    ytm = getattr(pr, "_ytm", None)
    if clean_price is not None:
        return {"clean_price": clean_price}
    if ytm is not None:
        return {"ytm": ytm}
    return {"clean_price": pr.clean_price()}


def _rebuild_pricer(pr: _FixedRateBondGenericPricer, leg: FixedRateBondPricableSpec) -> _FixedRateBondGenericPricer:
    init_kwargs = {
        "reference_date": pr.reference_date(),
        "issue_date": leg.issue_date,
        "maturity_date": leg.maturity_date,
        "cpn": leg.cpn,
        "notional": leg.notional,
        "meta_data": pr.meta(),
        **_quote_kwargs(pr),
    }
    if hasattr(pr, "_ql_frb_id"):
        init_kwargs["ql_frb_id"] = pr.id()
    else:
        init_kwargs["rl_frb_id"] = pr.id()
    return type(pr)(**init_kwargs)


def _resolve_leg_pricer(
    pricers: Dict[str, _FixedRateBondGenericPricer],
    leg: FixedRateBondPricableSpec,
) -> _FixedRateBondGenericPricer:
    leg_key = str(leg.cusip)
    pr = pricers.get(leg_key)
    if pr is not None:
        return pr

    for key, candidate in pricers.items():
        try:
            meta = candidate.meta() or {}
        except Exception:
            meta = {}
        if str(meta.get("cusip") or key) == leg_key:
            return candidate

    raise KeyError(f"Missing FRB pricer for leg cusip={leg_key!r}. available={list(pricers.keys())}")


class FixedRateBondValueFunctionMap(BaseValueFunctionMap[FixedRateBondValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _FixedRateBondGenericPricer],
        package: List[FixedRateBondPricableSpec],
        risk_weights: List[float],
    ):
        super().__init__(FixedRateBondValue, package=package, risk_weights=risk_weights, pricer=pricer)
        self._carry_roll_lookup_cache: Optional[pd.DataFrame] = None
        self._spline_cache: Optional[Any] = None  # CashSpline, cached per value-map instance

    def _create_map(self) -> Dict[FixedRateBondValue, Callable[..., float]]:
        return {
            FixedRateBondValue.YTM: self._ytm,
            FixedRateBondValue.CLEAN_PRICE: self._clean_price,
            FixedRateBondValue.DIRTY_PRICE: self._dirty_price,
            FixedRateBondValue.NPV: self._npv,
            FixedRateBondValue.PV01: self._pv01,
            FixedRateBondValue.DV01: self._dv01,
            FixedRateBondValue.MOD_DURATION: self._mod_duration,
            FixedRateBondValue.CARRY_BPS_RUNNING: self._carry_bps_running,
            FixedRateBondValue.ROLL_BPS_RUNNING: self._roll_bps_running,
            FixedRateBondValue.CARRY_AND_ROLL_BPS_RUNNING: self._carry_and_roll_bps_running,
            # FixedRateBondValue.CONVEXITY: self._convexity,
            FixedRateBondValue.SPLINE_SPREAD: self._spline_spread,
            FixedRateBondValue.SPLINE_Z_SCORE: self._spline_z_score,
            FixedRateBondValue.SPLINE_RMSE: self._spline_rmse,
            FixedRateBondValue.SPLINE_RMSE_BUCKET: self._spline_rmse_bucket,
            FixedRateBondValue.SPREAD_TSY: self._spread_tsy,
            FixedRateBondValue.OAS: self._oas,
            FixedRateBondValue.ASW_SPREAD: self._asw_spread,
            FixedRateBondValue.CAS: self._cas,
            FixedRateBondValue.ASSNP_RFR: self._quote_reader("ASSNP_RFR"),
            FixedRateBondValue.ASW_RFR: self._quote_reader("ASW_RFR"),
            FixedRateBondValue.CARRY_1M: self._quote_reader("CARRY.1M"),
            FixedRateBondValue.CARRY_1Y: self._quote_reader("CARRY.1Y"),
            FixedRateBondValue.CARRY_3M: self._quote_reader("CARRY.3M"),
            FixedRateBondValue.CARRY_6M: self._quote_reader("CARRY.6M"),
            FixedRateBondValue.CITI_DURATION: self._quote_reader("DURATION"),
            FixedRateBondValue.CITI_DV01: self._quote_reader("DV01"),
            FixedRateBondValue.CITI_PRICE: self._quote_reader("PRICE"),
            FixedRateBondValue.PRICING_ACCRUED: self._quote_reader("PRICING_ACCRUED"),
            FixedRateBondValue.PRICING_CV01: self._quote_reader("PRICING_CV01"),
            FixedRateBondValue.CITI_YIELD: self._quote_reader("YIELD"),
            FixedRateBondValue.CAS_RFR: self._quote_reader("CAS_RFR"),
            FixedRateBondValue.OISSMM_RFR: self._quote_reader("OISSMM_RFR"),
            FixedRateBondValue.OISS_RFR: self._quote_reader("OISS_RFR"),
            FixedRateBondValue.YYS: self._quote_reader("YYS"),
            FixedRateBondValue.YYS_RFR: self._quote_reader("YYS_RFR"),
            FixedRateBondValue.ZSPREAD: self._quote_reader("ZSPREAD"),
            FixedRateBondValue.ASW: self._quote_reader("ASW"),
            FixedRateBondValue.ASWNP: self._quote_reader("ASWNP"),
            FixedRateBondValue.OAS_RFR: self._quote_reader("OAS_RFR"),
            FixedRateBondValue.OISS: self._quote_reader("OISS"),
            FixedRateBondValue.OISSMM: self._quote_reader("OISSMM"),
            FixedRateBondValue.ROLL_1M: self._quote_reader("ROLL.1M"),
            FixedRateBondValue.ROLL_1Y: self._quote_reader("ROLL.1Y"),
            FixedRateBondValue.ROLL_3M: self._quote_reader("ROLL.3M"),
            FixedRateBondValue.ROLL_6M: self._quote_reader("ROLL.6M"),
            FixedRateBondValue.ROLLCARRY_1M: self._quote_reader("ROLLCARRY.1M"),
            FixedRateBondValue.ROLLCARRY_1Y: self._quote_reader("ROLLCARRY.1Y"),
            FixedRateBondValue.ROLLCARRY_3M: self._quote_reader("ROLLCARRY.3M"),
            FixedRateBondValue.ROLLCARRY_6M: self._quote_reader("ROLLCARRY.6M"),
            FixedRateBondValue.ASW_4_CHF: self._quote_reader("ASW_4_CHF"),
            FixedRateBondValue.ASW_4_EUR: self._quote_reader("ASW_4_EUR"),
            FixedRateBondValue.ASW_4_GBP: self._quote_reader("ASW_4_GBP"),
            FixedRateBondValue.ASW_4_USD: self._quote_reader("ASW_4_USD"),
            FixedRateBondValue.ASW_4_AUD: self._quote_reader("ASW_4_AUD"),
            FixedRateBondValue.ASW_4_JPY: self._quote_reader("ASW_4_JPY"),
            FixedRateBondValue.OISS_SOFR: self._quote_reader("OISS_SOFR"),
            FixedRateBondValue.ASS_SOFR: self._quote_reader("ASS_SOFR"),
            FixedRateBondValue.CAS_SOFR: self._quote_reader("CAS_SOFR"),
            FixedRateBondValue.SIMPLEYIELD: self._quote_reader("SIMPLEYIELD"),
            FixedRateBondValue.YIELD_WORST: self._quote_reader("YIELD_WORST"),
            FixedRateBondValue.YYS_SOFR: self._quote_reader("YYS_SOFR"),
        }

    def _frame_covers_package(self, frame: pd.DataFrame) -> bool:
        if frame.empty or "cusip" not in frame.columns:
            return False
        available = set(frame["cusip"].astype(str))
        for leg in self.common_kwargs["package"]:
            candidate_keys = {str(leg.cusip)}
            try:
                leg_pricer = _resolve_leg_pricer(self.common_kwargs["pricer"], leg)
                meta = leg_pricer.meta() or {}
            except Exception:
                meta = {}
            candidate_keys.add(str(meta.get("cusip") or leg.cusip))
            if available.isdisjoint(candidate_keys):
                return False
        return True

    def _carry_roll_lookup(self) -> pd.DataFrame:
        if self._carry_roll_lookup_cache is None:
            pricers = self.common_kwargs["pricer"]
            if not pricers:
                self._carry_roll_lookup_cache = pd.DataFrame()
            else:
                first_pricer = next(iter(pricers.values()))
                as_of_date = first_pricer.reference_date()
                frame = compute_carry_roll_frame(pricers=pricers, as_of_date=as_of_date)
                if not self._frame_covers_package(frame) or not frame_supports_roll(frame, as_of_date=as_of_date):
                    expanded_pricers = expand_pricer_universe_for_carry_roll(
                        pricers=pricers,
                        as_of_date=as_of_date,
                        min_ttm=1.0,
                    )
                    frame = compute_carry_roll_frame(pricers=expanded_pricers, as_of_date=as_of_date)
                if frame.empty or "cusip" not in frame.columns:
                    self._carry_roll_lookup_cache = pd.DataFrame()
                else:
                    self._carry_roll_lookup_cache = frame.drop_duplicates(subset=["cusip"], keep="last").set_index("cusip", drop=False)
        return self._carry_roll_lookup_cache

    def _metric_for_leg(self, *, leg: FixedRateBondPricableSpec, column: str) -> float:
        lookup = self._carry_roll_lookup()
        if lookup.empty or column not in lookup.columns:
            return float("nan")

        leg_key = str(leg.cusip)
        if leg_key not in lookup.index:
            pr = self.common_kwargs["pricer"].get(leg_key)
            if pr is not None:
                try:
                    meta = pr.meta() or {}
                except Exception:
                    meta = {}
                leg_key = str(meta.get("cusip") or leg_key)

        if leg_key not in lookup.index:
            return float("nan")

        val = safe_float(lookup.at[leg_key, column])
        return float("nan") if val is None else float(val)

    def _carry_roll_metric(self, *, column: str, **kwargs: Any) -> float:
        total = 0.0
        for i, leg in enumerate(kwargs["package"]):
            val = self._metric_for_leg(leg=leg, column=column)
            if pd.isna(val):
                return float("nan")
            total += kwargs["risk_weights"][i] * float(val)
        return float(total)

    def _ytm(self, **kwargs: Any) -> float:
        return calc_spread_rate(kwargs["pricer"], kwargs["package"], kwargs["risk_weights"]) * _frb_structure_legs_mapper[len(kwargs["package"])][1]

    def _clean_price(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).clean_price() for leg in kwargs["package"])

    def _dirty_price(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).dirty_price(notional=leg.notional) for leg in kwargs["package"])

    def _npv(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).npv(notional=leg.notional) for leg in kwargs["package"])

    def _pv01(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).pv01(notional=leg.notional) for leg in kwargs["package"])

    def _dv01(self, **kwargs: Any) -> float:
        return self._pv01(**kwargs)

    def _mod_duration(self, **kwargs: Any) -> float:
        return sum(
            kwargs["risk_weights"][i] * abs(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).mod_duration())
            for i, leg in enumerate(kwargs["package"])
        )

    def _carry_bps_running(self, **kwargs: Any) -> float:
        label, _, _ = normalize_horizon_spec(kwargs.get("horizon"))
        return self._carry_roll_metric(column=f"carry_{label}_bps", **kwargs)

    def _roll_bps_running(self, **kwargs: Any) -> float:
        label, _, _ = normalize_horizon_spec(kwargs.get("horizon"))
        return self._carry_roll_metric(column=f"roll_{label}_bps", **kwargs)

    def _carry_and_roll_bps_running(self, **kwargs: Any) -> float:
        label, _, _ = normalize_horizon_spec(kwargs.get("horizon"))
        return self._carry_roll_metric(column=f"carry_and_roll_{label}_bps", **kwargs)

    def _convexity(self, **kwargs: Any) -> float:
        return sum(
            kwargs["risk_weights"][i] * abs(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).convexity())
            for i, leg in enumerate(kwargs["package"])
        )

    # ------------------------------------------------------------------
    # Spline-derived values
    # ------------------------------------------------------------------
    def _get_spline(self, **kwargs: Any) -> Optional[Any]:
        """Lazily build / cache a CashSpline for the current date.

        Mirrors ``_carry_roll_lookup()`` — builds once per value-map
        instance, expands the pricer universe if the initial set is
        insufficient for a cross-sectional fit.
        """
        if self._spline_cache is not None:
            return self._spline_cache

        pricers = kwargs["pricer"]
        if not pricers:
            return None

        first_pricer = next(iter(pricers.values()))
        as_of_date = first_pricer.reference_date()
        config = kwargs.get("spline_config")  # from value_kwargs

        spline = compute_spline_for_date(pricers, as_of_date, config)

        # If the fit failed or didn't cover the package, expand
        if spline is None or (spline.fit_cusips is not None and len(spline.fit_cusips) < 10):
            expanded = expand_pricer_universe_for_spline(
                pricers=pricers, as_of_date=as_of_date,
            )
            spline = compute_spline_for_date(expanded, as_of_date, config)

        self._spline_cache = spline
        return spline

    def _spline_spread(self, **kwargs: Any) -> float:
        """Weighted sum of per-leg spline spreads (bp).

        For OUTRIGHT: the yield error of the single bond.
        For CURVE: difference of yield errors (spread of spreads).
        For FLY: weighted combination of yield errors.
        """
        spline = self._get_spline(**kwargs)
        if spline is None:
            return float("nan")
        total = 0.0
        for i, leg in enumerate(kwargs["package"]):
            spread_bp = spline.spread_for_cusip(str(leg.cusip))
            if pd.isna(spread_bp):
                return float("nan")
            total += kwargs["risk_weights"][i] * float(spread_bp)
        return float(total)

    def _spline_z_score(self, **kwargs: Any) -> float:
        """Weighted sum of per-leg z-scores of spline yield errors."""
        spline = self._get_spline(**kwargs)
        if spline is None:
            return float("nan")
        total = 0.0
        for i, leg in enumerate(kwargs["package"]):
            z = spline.z_score_for_cusip(str(leg.cusip))
            if pd.isna(z):
                return float("nan")
            total += kwargs["risk_weights"][i] * float(z)
        return float(total)

    def _spline_rmse(self, **kwargs: Any) -> float:
        """Date-level aggregate: RMSE of the entire fitted curve (bp)."""
        spline = self._get_spline(**kwargs)
        if spline is None:
            return float("nan")
        return float(spline.rmse) if spline.rmse is not None else float("nan")

    def _spline_rmse_bucket(self, **kwargs: Any) -> float:
        """Maturity-bucket RMSE (bp).

        Pass ``bucket="7-10Y"`` via ``value_kwargs``.  Valid buckets:
        ``0-2Y``, ``2-3Y``, ``3-5Y``, ``5-7Y``, ``7-10Y``, ``10-15Y``,
        ``15-20Y``, ``20-30Y``, or ``ALL``.
        """
        spline = self._get_spline(**kwargs)
        if spline is None:
            return float("nan")
        bucket_name = kwargs.get("bucket", "ALL")
        lo, hi = parse_bucket(str(bucket_name))
        return spline.rmse_bucket(lo, hi)

    # ------------------------------------------------------------------
    # Quote-only values
    # ------------------------------------------------------------------
    def _quote_reader(self, citi_value: str):
        """A value function that returns the vendor's published ``citi_value``.

        One factory rather than 43 near-identical methods. Each returned callable
        accepts ``**kwargs`` because ``BaseValueFunctionMap.apply`` splats the
        merged common and extra kwargs at it, and a fixed signature would
        TypeError on the extra keys.
        """
        def _read(**kwargs: Any) -> float:
            return self._vendor_quote(citi_value, **kwargs)

        _read.__name__ = f"_quote_{citi_value.replace('.', '_').lower()}"
        return _read

    def _vendor_quote(self, citi_value: str, **kwargs: Any) -> float:
        """Risk-weighted sum of the vendor's published number over the legs.

        Two conventions, both deliberate and both different from ``_ytm``:

        * **No ×100.** ``_ytm`` multiplies a curve/fly by 100 because a yield is
          quoted in percent and a spread of percents has to become basis points.
          These values are *already* basis points, so applying the same factor
          would inflate every curve and fly by 100×. Percent-vs-bp is the trap
          this repo has been bitten by more than once, and the two scalings live
          three functions apart, so it is called out here rather than inferred.
        * **No ``abs()``.** ``calc_spread_rate`` takes ``abs()`` of each leg's
          yield; a spread to Treasuries is *signed* (a cheap bond trades wide,
          a rich one trades through) and folding the sign away would make a
          -8 bp spread read as +8.

        Raises
        ------
        QuoteNotServedError
            When any leg's pricer did not come from the Velocity source, or the
            bond does not serve this value, or the fetch for it failed, or it
            served nothing in the window that was fetched. Which one is named in
            the message, because they have different fixes.

        Notes
        -----
        ``pricer.meta()`` is called WITHOUT a ``try``. Wrapping it in
        ``except Exception: meta = {}`` made any failure - a lazy-deserialisation
        bug, a corrupted DiskCache entry, an AttributeError from a refactor -
        impersonate the first of those causes: "this pricer did not come from the
        Velocity source, build it with FixedRateBondsMDP(source=...)", i.e. telling
        the user to do exactly what they already did while destroying the
        traceback that said why. This whole function exists to keep the causes
        apart; a fourth cause wearing the first one's message defeats it.
        """
        from MDP.CitiVelocityExcel.bonds.values import require_quoted

        total = 0.0
        for i, leg in enumerate(kwargs["package"]):
            pricer = _resolve_leg_pricer(kwargs["pricer"], leg)
            meta = pricer.meta() or {}
            quote = require_quoted(meta, citi_value, subject=f"{citi_value} for {leg.cusip}")
            total += kwargs["risk_weights"][i] * float(quote)
        return float(total)

    def _spread_tsy(self, **kwargs: Any) -> float:
        """Citi's published spread to the Treasury benchmark, in bp.

        Quote-only: reproducing it would mean reproducing Citi's benchmark
        choice (interpolated on the curve, or the nearest on-the-run), which is
        unmeasured and matters most for an off-the-run bond sitting between two
        benchmark points — exactly where the number is interesting.
        """
        return self._vendor_quote("SPREAD_TSY", **kwargs)

    def _oas(self, **kwargs: Any) -> float:
        """Citi's published option-adjusted spread, in bp.

        Served for 1,401 of the 2,162 ISINs in Citi's universe (304 of the 349 US
        Treasuries), and window-dependent: measured empty over a one-week window
        and full over five years. An empty OAS therefore raises with "widen the
        window", not with "this bond has no OAS".

        Because of that window dependence OAS is **not** in
        ``fetcher.DEFAULT_BOND_VALUES`` - the default 21-day EOD lookback cannot
        answer it, and fetching a column per bond that comes back empty is the
        cost that source exists to avoid. On a default-built pricer this raises
        "not requested, although Citi does serve it"; build the pricer with
        ``citivelo_values=[..., "OAS"]`` and a wide ``eod_lookback``.
        """
        return self._vendor_quote("OAS", **kwargs)

    def _asw_spread(self, **kwargs: Any) -> float:
        """Citi's published asset-swap spread into ``asw_currency`` (default USD), in bp.

        ``ASW_4_<CCY>`` is a sparse cross-currency MATRIX, not one value per
        bond: a bund carries USD/GBP/CHF/AUD but not EUR, a gilt carries
        EUR/GBP/AUD. Where the leg currency differs from the bond's own currency
        this is a cross-currency asset swap and is not the bond's own spread at
        all, so the currency is an explicit argument rather than a default the
        caller never sees.

        The default stays USD on a US Treasury because that is the bond's own
        currency, even though the AUD leg is the better covered one: measured over
        the 349 US Treasuries in the harvest, ASW_4_AUD serves 348 and ASW_4_USD
        253. Both are in ``fetcher.DEFAULT_BOND_VALUES``, so ``asw_currency="AUD"``
        needs no refetch - but it answers a different question.
        """
        from MDP.CitiVelocityExcel.bonds.values import asw_value_for_currency

        return self._vendor_quote(
            asw_value_for_currency(kwargs.get("asw_currency", "USD")), **kwargs
        )

    def _cas(self, **kwargs: Any) -> float:
        """Citi's published CAS, in bp.

        Served for 381 of the 2,162 ISINs (measured ``CND1000113G9`` = 43.4983,
        ``KR10350172C8`` = 44.2101) and for **no US Treasury** - exactly one US
        ISIN in the universe carries it, ``US3133EPSW68``, an FFCB agency. So on a
        Treasury this is expected to raise "Citi does not serve CAS" rather than to
        return anything.
        """
        return self._vendor_quote("CAS", **kwargs)
