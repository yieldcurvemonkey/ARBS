from __future__ import annotations

import math
from enum import Enum, auto
from typing import Any, Callable, Dict, List

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMarketContext
from Query.Base.BaseValue import BaseValueFunctionMap
from Query.IRSwaptions.pricer import (
    IRSwaptionPricable,
    build_underlying_swap,
    leg_cube_vol,
    leg_forward_rate,
    leg_metrics,
    leg_model_vol,
    leg_swap_length_years,
    leg_tte_years,
)


class IRSwaptionValue(Enum):
    NVOL = auto()
    SPREAD_NVOL = auto()
    FWD_NVOL = auto()
    MIDCURVE_FAIR_NVOL = auto()
    DAILY_BREAKEVEN_NVOL = auto()
    ANNUAL_BREAKEVEN_NVOL = auto()
    SPOT_NPV = auto()
    FWD_NPV = auto()
    SPOT_PREM = auto()
    FWD_PREM = auto()
    DV01 = auto()
    DELTA = auto()
    GAMMA = auto()
    GAMMA_01 = auto()
    VEGA_01 = auto()
    THETA_1D = auto()
    CHARM = auto()
    VETA = auto()
    SABR_NVOL = auto()
    SABR_PARAMS = auto()


class IRSwaptionValueFunctionMap(BaseValueFunctionMap[IRSwaptionValue, float]):
    def __init__(
        self,
        *,
        context: IRSwaptionMarketContext,
        package: List[IRSwaptionPricable],
        risk_weights: List[float],
    ):
        super().__init__(IRSwaptionValue, context=context, package=package, risk_weights=risk_weights)

    def _create_map(self) -> Dict[IRSwaptionValue, Callable[..., float]]:
        return {
            IRSwaptionValue.NVOL: self._nvol,
            IRSwaptionValue.SPREAD_NVOL: self._spread_nvol,
            IRSwaptionValue.FWD_NVOL: self._fwd_nvol,
            IRSwaptionValue.MIDCURVE_FAIR_NVOL: self._midcurve_fair_nvol,
            IRSwaptionValue.DAILY_BREAKEVEN_NVOL: self._daily_be_nv,
            IRSwaptionValue.ANNUAL_BREAKEVEN_NVOL: self._annual_be_nv,
            IRSwaptionValue.SPOT_NPV: self._spot_npv,
            IRSwaptionValue.FWD_NPV: self._fwd_npv,
            IRSwaptionValue.SPOT_PREM: self._spot_prem,
            IRSwaptionValue.FWD_PREM: self._fwd_prem,
            IRSwaptionValue.DV01: self._dv01,
            IRSwaptionValue.DELTA: self._delta,
            IRSwaptionValue.GAMMA: self._gamma,
            IRSwaptionValue.GAMMA_01: self._gamma_01,
            IRSwaptionValue.VEGA_01: self._vega_01,
            IRSwaptionValue.THETA_1D: self._theta_1d,
            IRSwaptionValue.CHARM: self._charm,
            IRSwaptionValue.VETA: self._veta,
            IRSwaptionValue.SABR_NVOL: self._sabr_nvol,
            IRSwaptionValue.SABR_PARAMS: self._sabr_params,
        }

    @staticmethod
    def _metrics(kwargs: dict[str, Any]) -> list[dict[str, float]]:
        context = kwargs["context"]
        package = kwargs["package"]
        return [leg_metrics(context, leg) for leg in package]

    @staticmethod
    def _weighted(metrics: list[dict[str, float]], rws: list[float], key: str) -> float:
        return float(sum(float(rw) * float(m[key]) for rw, m in zip(rws, metrics)))

    @staticmethod
    def _sigma_from_nvol_bps(nvol_bps: float) -> float:
        return float(nvol_bps) / 10_000.0

    @staticmethod
    def _nvol_bps_from_sigma(sigma: float) -> float:
        return float(sigma) * 10_000.0

    @staticmethod
    def _safe_sqrt_variance(var: float, *, label: str) -> float:
        v = float(var)
        if v < -1e-12:
            raise ValueError(f"{label} variance is negative ({v}). Check inputs and correlation assumptions.")
        return math.sqrt(max(v, 0.0))

    @staticmethod
    def _is_midcurve_leg(leg: IRSwaptionPricable) -> bool:
        return bool(leg.underlying_effective_date and leg.exercise_date and leg.underlying_effective_date > leg.exercise_date)

    @staticmethod
    def _derive_midcurve_legs(leg: IRSwaptionPricable) -> tuple[IRSwaptionPricable, IRSwaptionPricable, IRSwaptionPricable]:
        ex = leg.exercise_date
        eff = leg.underlying_effective_date
        mat = leg.underlying_maturity_date
        if not (ex and eff and mat):
            raise ValueError("Midcurve decomposition requires explicit exercise/effective/maturity dates.")
        if eff <= ex:
            raise ValueError("Leg is not a midcurve option: underlying_effective_date must be after exercise_date.")
        if mat <= eff:
            raise ValueError("Invalid leg dates: underlying_maturity_date must be after underlying_effective_date.")

        short_leg = IRSwaptionPricable(
            option_type=leg.option_type,
            exercise_date=ex,
            underlying_effective_date=ex,
            underlying_maturity_date=eff,
            strike=leg.strike,
            notional=leg.notional,
            label=f"{leg.label or 'LEG'}_MC_SHORT",
        )
        long_leg = IRSwaptionPricable(
            option_type=leg.option_type,
            exercise_date=ex,
            underlying_effective_date=ex,
            underlying_maturity_date=mat,
            strike=leg.strike,
            notional=leg.notional,
            label=f"{leg.label or 'LEG'}_MC_LONG",
        )
        long_expiry_leg = IRSwaptionPricable(
            option_type=leg.option_type,
            exercise_date=eff,
            underlying_effective_date=eff,
            underlying_maturity_date=mat,
            strike=leg.strike,
            notional=leg.notional,
            label=f"{leg.label or 'LEG'}_LONG_EXPIRY",
        )
        return short_leg, long_leg, long_expiry_leg

    @staticmethod
    def _atm_model_sigma(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
        atmf = float(leg_forward_rate(context, leg))
        return max(float(leg_model_vol(context, leg, strike=atmf)), 0.0)

    @staticmethod
    def _midcurve_weights_from_pvbp(
        context: IRSwaptionMarketContext,
        short_leg: IRSwaptionPricable,
        long_leg: IRSwaptionPricable,
        *,
        wa_override: float | None = None,
        wb_override: float | None = None,
    ) -> tuple[float, float]:
        if wa_override is not None and wb_override is not None:
            return float(wa_override), float(wb_override)

        short_swap = build_underlying_swap(context, short_leg.with_notional(1.0))
        long_swap = build_underlying_swap(context, long_leg.with_notional(1.0))
        pvbp_short = abs(float(short_swap.fixedLegBPS()))
        pvbp_long = abs(float(long_swap.fixedLegBPS()))
        denom = pvbp_long - pvbp_short
        if denom <= 1e-12:
            raise ValueError(
                f"Invalid PVBP weights for midcurve fair value: pvbp_short={pvbp_short}, pvbp_long={pvbp_long}."
            )
        wa = pvbp_short / denom
        wb = pvbp_long / denom
        return float(wa), float(wb)

    def _midcurve_fair_sigma(
        self,
        *,
        context: IRSwaptionMarketContext,
        midcurve_leg: IRSwaptionPricable,
        rho: float,
        wa: float | None = None,
        wb: float | None = None,
    ) -> float:
        short_leg, long_leg, _ = self._derive_midcurve_legs(midcurve_leg)
        sigma_short = self._atm_model_sigma(context, short_leg)
        sigma_long = self._atm_model_sigma(context, long_leg)
        w_a, w_b = self._midcurve_weights_from_pvbp(context, short_leg, long_leg, wa_override=wa, wb_override=wb)
        rho_f = float(rho)
        var_mid = (
            (w_a * w_a * sigma_short * sigma_short)
            + (w_b * w_b * sigma_long * sigma_long)
            - (2.0 * w_a * w_b * rho_f * sigma_short * sigma_long)
        )
        return self._safe_sqrt_variance(var_mid, label="Midcurve fair")

    def _fwd_sigma_from_midcurve(
        self,
        *,
        context: IRSwaptionMarketContext,
        midcurve_leg: IRSwaptionPricable,
        midcurve_sigma: float,
    ) -> float:
        _, _, long_expiry_leg = self._derive_midcurve_legs(midcurve_leg)
        t_short = float(leg_tte_years(context, midcurve_leg))
        t_long = float(leg_tte_years(context, long_expiry_leg))
        if t_long <= t_short:
            raise ValueError(f"Invalid times for forward vol: t_long={t_long}, t_short={t_short}")

        sigma_long = self._atm_model_sigma(context, long_expiry_leg)
        var_fwd = ((t_long * sigma_long * sigma_long) - (t_short * midcurve_sigma * midcurve_sigma)) / (t_long - t_short)
        return self._safe_sqrt_variance(var_fwd, label="Forward vol")

    def _nvol(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        rws = kwargs["risk_weights"]
        if len(mets) == 1:
            return float(mets[0]["NVOL"])
        denom = sum(abs(float(rw)) for rw in rws) or 1.0
        return float(sum(abs(float(rw)) * float(m["NVOL"]) for rw, m in zip(rws, mets)) / denom)

    def _spread_nvol(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        package = kwargs["package"]
        rws = [float(x) for x in kwargs["risk_weights"]]

        if len(package) == 1:
            return float(mets[0]["NVOL"])

        if len(package) == 2:
            t0 = str(package[0].option_type).lower()
            t1 = str(package[1].option_type).lower()
            if t0 == t1:
                return float(rws[0] * mets[0]["NVOL"] + rws[1] * mets[1]["NVOL"])

            # Strangle/straddle (payer+receiver both long/short): average by abs weights.
            if (rws[0] * rws[1]) > 0:
                denom = abs(rws[0]) + abs(rws[1]) or 1.0
                return float((abs(rws[0]) * mets[0]["NVOL"] + abs(rws[1]) * mets[1]["NVOL"]) / denom)

            # Risk reversal style payer-receiver spread.
            return float(rws[0] * mets[0]["NVOL"] + rws[1] * mets[1]["NVOL"])

        if len(package) == 3:
            return float(rws[0] * mets[0]["NVOL"] + rws[1] * mets[1]["NVOL"] + rws[2] * mets[2]["NVOL"])

        raise NotImplementedError(
            "SPREAD_NVOL for packages with more than 3 legs is ambiguous without additional structure metadata."
        )

    def _fwd_nvol(self, **kwargs: Any) -> float:
        context = kwargs["context"]
        package = kwargs["package"]
        mets = self._metrics(kwargs)

        # Midcurve single-leg mode:
        #   use midcurve vol (market or fair) + longer-expiry vanilla to infer forward vol.
        if len(package) == 1:
            leg = package[0]
            if not self._is_midcurve_leg(leg):
                raise ValueError("FWD_NVOL single-leg mode requires a midcurve leg (tail like 'fwdxtenor').")

            use_fair_midcurve = bool(kwargs.get("use_fair_midcurve", False))
            rho = float(kwargs.get("rho", 1.0))
            wa = kwargs.get("wa")
            wb = kwargs.get("wb")
            if use_fair_midcurve:
                sigma_mid = self._midcurve_fair_sigma(context=context, midcurve_leg=leg, rho=rho, wa=wa, wb=wb)
            else:
                sigma_mid = self._sigma_from_nvol_bps(float(mets[0]["NVOL"]))
            sigma_fwd = self._fwd_sigma_from_midcurve(context=context, midcurve_leg=leg, midcurve_sigma=sigma_mid)
            return self._nvol_bps_from_sigma(sigma_fwd)

        # Generic two-leg mode:
        #   infer forward vol from a short-expiry and long-expiry normal vol pair.
        if len(package) == 2:
            t0 = float(leg_tte_years(context, package[0]))
            t1 = float(leg_tte_years(context, package[1]))
            if abs(t0 - t1) < 1e-12:
                raise ValueError("FWD_NVOL two-leg mode requires distinct expiries.")
            long_idx = 0 if t0 > t1 else 1
            short_idx = 1 - long_idx

            t_long = t0 if long_idx == 0 else t1
            t_short = t1 if long_idx == 0 else t0
            sigma_long = self._sigma_from_nvol_bps(float(mets[long_idx]["NVOL"]))
            sigma_short = self._sigma_from_nvol_bps(float(mets[short_idx]["NVOL"]))
            var_fwd = ((t_long * sigma_long * sigma_long) - (t_short * sigma_short * sigma_short)) / (t_long - t_short)
            return self._nvol_bps_from_sigma(self._safe_sqrt_variance(var_fwd, label="Forward vol"))

        raise NotImplementedError("FWD_NVOL currently supports either 1 midcurve leg or 2-leg long/short expiry packages.")

    def _midcurve_fair_nvol(self, **kwargs: Any) -> float:
        context = kwargs["context"]
        package = kwargs["package"]
        if len(package) != 1:
            raise NotImplementedError("MIDCURVE_FAIR_NVOL expects a single midcurve leg.")
        leg = package[0]
        if not self._is_midcurve_leg(leg):
            raise ValueError("MIDCURVE_FAIR_NVOL requires a midcurve leg (tail like 'fwdxtenor').")

        rho = float(kwargs.get("rho", 1.0))
        wa = kwargs.get("wa")
        wb = kwargs.get("wb")
        sigma = self._midcurve_fair_sigma(context=context, midcurve_leg=leg, rho=rho, wa=wa, wb=wb)
        return self._nvol_bps_from_sigma(sigma)

    def _daily_be_nv(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "DAILY_BREAKEVEN_NVOL")

    def _annual_be_nv(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "ANNUAL_BREAKEVEN_NVOL")

    def _spot_npv(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "SPOT_NPV")

    def _fwd_npv(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "FWD_NPV")

    def _spot_prem(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "SPOT_PREM") * 10_000

    def _fwd_prem(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "FWD_PREM") * 100

    def _dv01(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "DV01")

    def _delta(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "DELTA")

    def _gamma(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "GAMMA")

    def _gamma_01(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "GAMMA_01")

    def _vega_01(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "VEGA_01")

    def _theta_1d(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "THETA_1D")

    def _charm(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "CHARM")

    def _veta(self, **kwargs: Any) -> float:
        mets = self._metrics(kwargs)
        return self._weighted(mets, kwargs["risk_weights"], "VETA")

    def _sabr_nvol(self, **kwargs: Any) -> float:
        """Normal vol from SABR cube at exact strike. Requires vol_cube in context metadata."""
        context = kwargs["context"]
        package = kwargs["package"]
        rws = kwargs["risk_weights"]

        cube = (context.metadata or {}).get("vol_cube")
        if cube is None:
            raise ValueError(
                "SABR_NVOL requires a vol cube in market context metadata. "
                "Use source='MONKEYCUBE-QL' to enable the SABR cube."
            )

        vols: list[float] = []
        for leg in package:
            cv = leg_cube_vol(context, leg)
            vols.append(float(cv) * 10_000.0 if cv is not None else 0.0)

        if len(vols) == 1:
            return vols[0]
        denom = sum(abs(float(rw)) for rw in rws) or 1.0
        return float(sum(abs(float(rw)) * v for rw, v in zip(rws, vols)) / denom)

    def _sabr_params(self, **kwargs: Any) -> float:
        """Return interpolated SABR params at the first leg's (expiry, tenor) point.

        Returns alpha as the float value; full params dict is stored in context metadata
        under 'last_sabr_params' for downstream access.
        """
        context = kwargs["context"]
        package = kwargs["package"]

        cube = (context.metadata or {}).get("vol_cube")
        if cube is None:
            raise ValueError(
                "SABR_PARAMS requires a vol cube in market context metadata. "
                "Use source='MONKEYCUBE-QL' to enable the SABR cube."
            )

        leg = package[0]
        option_time = leg_tte_years(context, leg)
        swap_years = leg_swap_length_years(context, leg)

        import numpy as np

        pt = np.array([[option_time, swap_years]])
        a, b, nu, rho, fwd = cube._interpolate_params(pt)
        params = {
            "alpha": a,
            "beta": b,
            "nu": nu,
            "rho": rho,
            "atmf_rate": fwd,
            "expiry_time": option_time,
            "swap_years": swap_years,
        }
        context.metadata["last_sabr_params"] = params
        return a
