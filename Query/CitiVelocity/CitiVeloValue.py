r"""Values over a Citi Velocity package: the published quote, or a local reprice.

Every value falls into one of two families, and the split is the whole point of
this product:

``QUOTE``-family
    Read the number Citi publishes. One ``CVTSHIST`` column, no model.

``RL_*`` / ``QL_*`` family
    Rebuild the object locally from Citi quotes - strip the curve, build the cube,
    construct the bond - and compute the metric from it. Velocity's own pricers
    (``CVDSWAP``, ``CVDSWAPTION``, ``CVCALCDERIVATIVES``, ...) are **not entitled**,
    so there is no third option: anything beyond a published quote is our model.

Having both on the same query is what makes the timeseries fast path auditable:
``QUOTE`` and ``RL_RATE`` on the same outright must agree to solver tolerance,
because the curve was calibrated to that very quote. A test asserts it. Without
that, a "fast path" is just an unverified shortcut.

Units
-----
Single-leg values come back in the family's native unit (par rates in percent,
spreads and bases in basis points, normal vols in basis points of vol). Multi-leg
structures come back in **basis points**: a percent-quoted structure is scaled by
100, a bp-quoted structure is not. This mirrors ``Query/IRSwaps``, where an
outright RATE is percent and a CURVE or FLY is bp.
"""

from __future__ import annotations

import logging
from enum import Enum, auto, unique
from typing import Any, Callable, Dict, List, Sequence

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.CitiVelocity._CitiVeloLeg import CitiVeloKind, CitiVeloLeg, CitiVeloUnit

__all__ = ["CitiVeloValue", "CitiVeloValueFunctionMap", "structure_scale"]

_logger = logging.getLogger(__name__)


@unique
class CitiVeloValue(Enum):
    # -- published quotes -------------------------------------------
    QUOTE = auto()

    # -- rateslib reprices ------------------------------------------
    RL_RATE = auto()
    RL_FWD_RATE = auto()
    RL_NPV = auto()
    RL_PV01 = auto()
    RL_DV01 = auto()
    RL_ZERO_RATE = auto()
    RL_DISCOUNT = auto()
    RL_VOL = auto()
    RL_OPTION_PREMIUM = auto()
    RL_BOND_YIELD = auto()
    RL_BOND_PRICE = auto()
    RL_BOND_DURATION = auto()
    RL_XCCY_BASIS = auto()
    RL_BREAKEVEN = auto()

    # -- QuantLib reprices ------------------------------------------
    QL_RATE = auto()
    QL_FWD_RATE = auto()
    QL_ZERO_RATE = auto()
    QL_DISCOUNT = auto()
    QL_VOL = auto()
    QL_OPTION_PREMIUM = auto()
    QL_BOND_YIELD = auto()
    QL_BOND_PRICE = auto()
    QL_BOND_DURATION = auto()
    QL_BOND_DV01 = auto()
    QL_BOND_ASW = auto()
    QL_XCCY_BASIS = auto()
    QL_BREAKEVEN = auto()

    @property
    def is_quote(self) -> bool:
        """True when this value is served directly by a tag - the fast path."""
        return self is CitiVeloValue.QUOTE

    @property
    def backend(self) -> str:
        if self.is_quote:
            return "citi"
        return "rateslib" if self.name.startswith("RL_") else "quantlib"


def structure_scale(package: Sequence[CitiVeloLeg]) -> float:
    """Multiplier taking a package's native unit to its reporting unit.

    One leg reports in its own unit; two or more report in basis points. A
    package whose legs disagree on unit never reaches here - the structure layer
    refuses to build it.
    """
    if not package:
        return 1.0
    if len(package) == 1:
        return 1.0
    return package[0].unit.scale_to_bp


class CitiVeloValueFunctionMap(BaseValueFunctionMap[CitiVeloValue, float]):
    """Computes a value over ``(pricer, package, risk_weights)``.

    Every function takes ``**kwargs`` and digs its inputs out of the merged
    common/extra dict, matching every other product in this repo, because
    :meth:`BaseValueFunctionMap.apply` splats them together.
    """

    def __init__(self, pricer: Any, package: List[CitiVeloLeg], risk_weights: List[float]):
        super().__init__(
            CitiVeloValue,
            pricer=pricer,
            package=package,
            risk_weights=risk_weights,
        )

    def _create_map(self) -> Dict[CitiVeloValue, Callable[..., float]]:
        return {
            CitiVeloValue.QUOTE: self._quote,
            # rateslib
            CitiVeloValue.RL_RATE: self._rl_rate,
            CitiVeloValue.RL_FWD_RATE: self._rl_fwd_rate,
            CitiVeloValue.RL_NPV: self._rl_npv,
            CitiVeloValue.RL_PV01: self._rl_pv01,
            CitiVeloValue.RL_DV01: self._rl_dv01,
            CitiVeloValue.RL_ZERO_RATE: self._rl_zero_rate,
            CitiVeloValue.RL_DISCOUNT: self._rl_discount,
            CitiVeloValue.RL_VOL: self._rl_vol,
            CitiVeloValue.RL_OPTION_PREMIUM: self._rl_option_premium,
            CitiVeloValue.RL_BOND_YIELD: self._rl_bond_metric("ytm"),
            CitiVeloValue.RL_BOND_PRICE: self._rl_bond_metric("clean_price"),
            CitiVeloValue.RL_BOND_DURATION: self._rl_bond_metric("mod_duration"),
            CitiVeloValue.RL_XCCY_BASIS: self._rl_xccy_basis,
            CitiVeloValue.RL_BREAKEVEN: self._rl_breakeven,
            # QuantLib
            CitiVeloValue.QL_RATE: self._ql_rate,
            CitiVeloValue.QL_FWD_RATE: self._ql_fwd_rate,
            CitiVeloValue.QL_ZERO_RATE: self._ql_zero_rate,
            CitiVeloValue.QL_DISCOUNT: self._ql_discount,
            CitiVeloValue.QL_VOL: self._ql_vol,
            CitiVeloValue.QL_OPTION_PREMIUM: self._ql_option_premium,
            CitiVeloValue.QL_BOND_YIELD: self._ql_bond_metric("ytm"),
            CitiVeloValue.QL_BOND_PRICE: self._ql_bond_metric("clean_price"),
            CitiVeloValue.QL_BOND_DURATION: self._ql_bond_metric("mod_duration"),
            CitiVeloValue.QL_BOND_DV01: self._ql_bond_metric("dv01"),
            CitiVeloValue.QL_BOND_ASW: self._ql_bond_asw,
            CitiVeloValue.QL_XCCY_BASIS: self._ql_xccy_basis,
            CitiVeloValue.QL_BREAKEVEN: self._ql_breakeven,
        }

    # -- plumbing -------------------------------------------------------

    @staticmethod
    def _unpack(kwargs: Dict[str, Any]):
        return kwargs["pricer"], kwargs["package"], kwargs["risk_weights"]

    def _weighted(self, kwargs: Dict[str, Any], per_leg: Callable[[Any, CitiVeloLeg], float]) -> float:
        pricer, package, weights = self._unpack(kwargs)
        scale = structure_scale(package)
        return float(
            sum(float(w) * float(per_leg(pricer, leg)) for w, leg in zip(weights, package)) * scale
        )

    # -- published quote ------------------------------------------------

    def _quote(self, **kwargs: Any) -> float:
        """The number Citi publishes, weighted across the package.

        Raises
        ------
        ValueError
            When a leg has no quote at the pricer's timestamp. It raises rather
            than treating a missing leg as zero: a fly silently priced with one
            missing wing is a plausible number that is wrong.
        """
        return self._weighted(kwargs, lambda p, leg: p.quote(leg.tag))

    # -- rateslib -------------------------------------------------------

    def _rl_rate(self, **kwargs: Any) -> float:
        """Par rate repriced off the locally-stripped rateslib curve, in percent.

        For an ``OIS_PAR`` leg this must reproduce ``QUOTE`` to solver tolerance,
        because the curve is calibrated to that quote. That equivalence is the
        contract the timeseries fast path rests on.
        """
        return self._weighted(kwargs, lambda p, leg: p.rl_par_rate(leg))

    def _rl_fwd_rate(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.rl_forward_rate(leg))

    def _rl_npv(self, **kwargs: Any) -> float:
        pricer, package, weights = self._unpack(kwargs)
        return float(sum(float(w) * pricer.rl_npv(leg, **kwargs) for w, leg in zip(weights, package)))

    def _rl_pv01(self, **kwargs: Any) -> float:
        pricer, package, weights = self._unpack(kwargs)
        return float(sum(float(w) * pricer.rl_pv01(leg) for w, leg in zip(weights, package)))

    def _rl_dv01(self, **kwargs: Any) -> float:
        pricer, package, weights = self._unpack(kwargs)
        return float(sum(float(w) * pricer.rl_dv01(leg) for w, leg in zip(weights, package)))

    def _rl_zero_rate(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.rl_zero_rate(leg))

    def _rl_discount(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.rl_discount(leg))

    def _rl_vol(self, **kwargs: Any) -> float:
        strike = kwargs.get("strike")
        return self._weighted(kwargs, lambda p, leg: p.rl_vol(leg, strike=strike))

    def _rl_option_premium(self, **kwargs: Any) -> float:
        pricer, package, weights = self._unpack(kwargs)
        return float(
            sum(float(w) * pricer.rl_option_premium(leg, **kwargs) for w, leg in zip(weights, package))
        )

    def _rl_bond_metric(self, metric: str) -> Callable[..., float]:
        def fn(**kwargs: Any) -> float:
            return self._weighted(kwargs, lambda p, leg: p.rl_bond_metric(leg, metric))

        return fn

    def _rl_xccy_basis(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.rl_xccy_basis(leg))

    def _rl_breakeven(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.rl_breakeven(leg))

    # -- QuantLib -------------------------------------------------------

    def _ql_rate(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.ql_par_rate(leg))

    def _ql_fwd_rate(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.ql_forward_rate(leg))

    def _ql_zero_rate(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.ql_zero_rate(leg))

    def _ql_discount(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.ql_discount(leg))

    def _ql_vol(self, **kwargs: Any) -> float:
        strike = kwargs.get("strike")
        return self._weighted(kwargs, lambda p, leg: p.ql_vol(leg, strike=strike))

    def _ql_option_premium(self, **kwargs: Any) -> float:
        pricer, package, weights = self._unpack(kwargs)
        return float(
            sum(float(w) * pricer.ql_option_premium(leg, **kwargs) for w, leg in zip(weights, package))
        )

    def _ql_bond_metric(self, metric: str) -> Callable[..., float]:
        def fn(**kwargs: Any) -> float:
            return self._weighted(kwargs, lambda p, leg: p.ql_bond_metric(leg, metric))

        return fn

    def _ql_bond_asw(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.ql_bond_asw(leg))

    def _ql_xccy_basis(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.ql_xccy_basis(leg))

    def _ql_breakeven(self, **kwargs: Any) -> float:
        return self._weighted(kwargs, lambda p, leg: p.ql_breakeven(leg))
