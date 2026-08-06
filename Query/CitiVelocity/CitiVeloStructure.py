r"""Structures over Citi Velocity legs: outright, curve, fly, spread, condor.

Every builder returns ``(package: list[CitiVeloLeg], risk_weights: list[float])``,
the contract :class:`~Query.Base.BaseStructure.BaseStructureFunctionMap` imposes.

Two deliberate departures from the sibling products:

* **Risk-weight defaults are tuples, not lists.** ``Query/FixedRateBonds`` has a
  recorded mutable-default bug: its builders sign-flip the default list in place,
  so an unweighted query permanently poisons the next one. Tuples are copied on
  use here, which makes that class of bug impossible rather than merely absent.
* **The sign convention is applied once, at build time.** ``Query/IRSwaps``
  re-derives the structure from ``len(package)`` inside the value layer, which
  means a three-leg package is always treated as a fly. Here the weights that come
  out of the builder are the weights the value layer uses, so a caller can build a
  three-leg structure that is not a fly and get what they asked for.
"""

from __future__ import annotations

import logging
from enum import Enum, auto, unique
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.CitiVelocity._CitiVeloLeg import CitiVeloKind, CitiVeloLeg

__all__ = [
    "CitiVeloStructure",
    "CitiVeloStructureFunctionMap",
    "DEFAULT_CURVE_WEIGHTS",
    "DEFAULT_FLY_WEIGHTS",
    "DEFAULT_CONDOR_WEIGHTS",
]

_logger = logging.getLogger(__name__)

#: Front short, back long: a steepener is positive.
DEFAULT_CURVE_WEIGHTS: Tuple[float, ...] = (-1.0, 1.0)
#: Wings short, belly long: ``2*belly - front - back``, the repo-wide fly sign.
DEFAULT_FLY_WEIGHTS: Tuple[float, ...] = (-1.0, 2.0, -1.0)
#: Two spreads against each other.
DEFAULT_CONDOR_WEIGHTS: Tuple[float, ...] = (-1.0, 1.0, 1.0, -1.0)


@unique
class CitiVeloStructure(Enum):
    OUTRIGHT = auto()
    CURVE = auto()
    FLY = auto()
    SPREAD = auto()
    CONDOR = auto()


class CitiVeloStructureFunctionMap(BaseStructureFunctionMap[CitiVeloStructure, CitiVeloLeg]):
    """Turns a query's ``structure_kwargs`` into a package of tagged legs.

    The bound ``pricer`` resolves each leg spec into a concrete tag: it is the
    only thing that knows the catalog, so a structure builder never spells a tag
    itself.
    """

    def __init__(self, pricer: Any):
        super().__init__(CitiVeloStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(self) -> Dict[CitiVeloStructure, Callable[..., Tuple[List[CitiVeloLeg], List[float]]]]:
        return {
            CitiVeloStructure.OUTRIGHT: partial(self._build_outright),
            CitiVeloStructure.CURVE: partial(self._build_curve),
            CitiVeloStructure.FLY: partial(self._build_fly),
            CitiVeloStructure.SPREAD: partial(self._build_spread),
            CitiVeloStructure.CONDOR: partial(self._build_condor),
        }

    # -- leg resolution -------------------------------------------------

    @staticmethod
    def _leg(pricer: Any, **spec: Any) -> CitiVeloLeg:
        """Resolve one leg through the pricer's tag resolver."""
        return pricer.resolve_leg(**{k: v for k, v in spec.items() if v is not None})

    @staticmethod
    def _weights(supplied: Optional[Sequence[float]], default: Tuple[float, ...], n: int) -> List[float]:
        if supplied is None:
            return list(default)
        weights = [float(w) for w in supplied]
        if len(weights) != n:
            raise ValueError(
                f"Expected {n} risk_weights for this structure, got {len(weights)}: {supplied!r}."
            )
        return weights

    # -- builders -------------------------------------------------------

    def _build_outright(
        self,
        *,
        pricer: Any,
        tag: Optional[str] = None,
        family: Optional[str] = None,
        citi_index: Optional[str] = None,
        currency: Optional[str] = None,
        counter_currency: Optional[str] = None,
        tenor: Optional[str] = None,
        forward: Optional[str] = None,
        expiry: Optional[str] = None,
        offset_bp: Optional[float] = None,
        isin: Optional[str] = None,
        measure: Optional[str] = None,
        notional: Optional[float] = None,
        risk_weight: Optional[float] = None,
        **_: Any,
    ) -> Tuple[List[CitiVeloLeg], List[float]]:
        """One leg.

        Returns
        -------
        (package, risk_weights)
            A single-element package. ``risk_weight`` defaults to 1.0.
        """
        leg = self._leg(
            pricer,
            tag=tag,
            family=family,
            citi_index=citi_index,
            currency=currency,
            counter_currency=counter_currency,
            tenor=tenor,
            forward=forward,
            expiry=expiry,
            offset_bp=offset_bp,
            isin=isin,
            measure=measure,
            notional=notional,
        )
        return [leg], [1.0 if risk_weight is None else float(risk_weight)]

    def _build_curve(
        self,
        *,
        pricer: Any,
        front_tenor: Optional[str] = None,
        back_tenor: Optional[str] = None,
        risk_weights: Optional[Sequence[float]] = None,
        **common: Any,
    ) -> Tuple[List[CitiVeloLeg], List[float]]:
        """Two legs: front and back, weighted ``(-1, +1)`` unless told otherwise."""
        if front_tenor is None or back_tenor is None:
            raise ValueError("CURVE requires front_tenor and back_tenor.")
        weights = self._weights(risk_weights, DEFAULT_CURVE_WEIGHTS, 2)
        legs = [
            self._leg(pricer, tenor=t, **_leg_common(common))
            for t in (front_tenor, back_tenor)
        ]
        _assert_homogeneous(legs)
        return legs, weights

    def _build_fly(
        self,
        *,
        pricer: Any,
        front_tenor: Optional[str] = None,
        belly_tenor: Optional[str] = None,
        back_tenor: Optional[str] = None,
        risk_weights: Optional[Sequence[float]] = None,
        **common: Any,
    ) -> Tuple[List[CitiVeloLeg], List[float]]:
        """Three legs: ``2*belly - front - back``."""
        if front_tenor is None or belly_tenor is None or back_tenor is None:
            raise ValueError("FLY requires front_tenor, belly_tenor and back_tenor.")
        weights = self._weights(risk_weights, DEFAULT_FLY_WEIGHTS, 3)
        legs = [
            self._leg(pricer, tenor=t, **_leg_common(common))
            for t in (front_tenor, belly_tenor, back_tenor)
        ]
        _assert_homogeneous(legs)
        return legs, weights

    def _build_spread(
        self,
        *,
        pricer: Any,
        legs: Optional[Sequence[Dict[str, Any]]] = None,
        risk_weights: Optional[Sequence[float]] = None,
        **common: Any,
    ) -> Tuple[List[CitiVeloLeg], List[float]]:
        """An explicit N-leg spread across ANY two or more tags.

        This is how heterogeneous structures are expressed - SOFR vs Fed Funds,
        USD 10y vol against EUR 10y vol, a bond against its matched swap. Each
        entry of ``legs`` is a leg spec dict; keys absent from an entry fall back
        to the shared ``structure_kwargs``.

        Unlike CURVE and FLY this does NOT assert the legs are homogeneous,
        because heterogeneity is the point. It DOES assert they share a unit, so
        a percent leg and a basis-point leg can never be silently netted.
        """
        if not legs:
            raise ValueError(
                "SPREAD requires structure_kwargs['legs'], a sequence of leg spec dicts, "
                "e.g. [{'citi_index': 'USD_SOFR', 'tenor': '10Y'}, "
                "{'citi_index': 'USD_FEDFUND', 'tenor': '10Y'}]."
            )
        shared = _leg_common(common)
        built = [self._leg(pricer, **{**shared, **dict(spec)}) for spec in legs]
        weights = self._weights(
            risk_weights,
            tuple([-1.0] + [1.0] * (len(built) - 1)),
            len(built),
        )
        _assert_same_unit(built)
        return built, weights

    def _build_condor(
        self,
        *,
        pricer: Any,
        front_tenor: Optional[str] = None,
        front_belly_tenor: Optional[str] = None,
        back_belly_tenor: Optional[str] = None,
        back_tenor: Optional[str] = None,
        risk_weights: Optional[Sequence[float]] = None,
        **common: Any,
    ) -> Tuple[List[CitiVeloLeg], List[float]]:
        """Four legs: two spreads against each other."""
        tenors = (front_tenor, front_belly_tenor, back_belly_tenor, back_tenor)
        if any(t is None for t in tenors):
            raise ValueError(
                "CONDOR requires front_tenor, front_belly_tenor, back_belly_tenor and back_tenor."
            )
        weights = self._weights(risk_weights, DEFAULT_CONDOR_WEIGHTS, 4)
        legs = [self._leg(pricer, tenor=t, **_leg_common(common)) for t in tenors]
        _assert_homogeneous(legs)
        return legs, weights


# ------------------------------------------------------------------ #
#                              helpers                               #
# ------------------------------------------------------------------ #

_LEG_SPEC_KEYS = (
    "tag",
    "family",
    "citi_index",
    "currency",
    "counter_currency",
    "forward",
    "expiry",
    "offset_bp",
    "isin",
    "measure",
    "notional",
)


def _leg_common(common: Dict[str, Any]) -> Dict[str, Any]:
    """The subset of shared structure_kwargs that describes a leg."""
    return {k: v for k, v in common.items() if k in _LEG_SPEC_KEYS and v is not None}


def _assert_homogeneous(legs: Sequence[CitiVeloLeg]) -> None:
    """Every leg of a curve/fly/condor must be the same kind on the same curve.

    A curve built from a SOFR par rate and a Fed Funds par rate is a basis, not a
    curve, and netting them under a CURVE label produces a number nobody asked
    for. Use SPREAD with explicit leg specs for that.
    """
    kinds = {leg.kind for leg in legs}
    if len(kinds) > 1:
        raise ValueError(
            f"CURVE/FLY/CONDOR legs must share a kind, got {sorted(k.value for k in kinds)}. "
            "Use structure=SPREAD with explicit leg specs for a heterogeneous structure."
        )
    indices = {leg.citi_index for leg in legs if leg.citi_index is not None}
    if len(indices) > 1:
        raise ValueError(
            f"CURVE/FLY/CONDOR legs must share a curve, got {sorted(indices)}. "
            "Use structure=SPREAD for a cross-curve structure."
        )


def _assert_same_unit(legs: Sequence[CitiVeloLeg]) -> None:
    units = {leg.unit for leg in legs}
    if len(units) > 1:
        raise ValueError(
            f"Cannot net legs quoted in different units: {sorted(u.value for u in units)}. "
            "Citi serves par rates in percent, spreads and bases in basis points, and normal "
            "vols in basis points of vol - netting across them is a 100x error that still prices."
        )
