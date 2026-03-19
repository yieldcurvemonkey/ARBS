from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from Query.Base.bachelier import bachelier_price
from Query.IRSwaptions.pricer import leg_forward_rate, leg_model_vol, leg_spot_npv, leg_tte_years
from Simulation.scenarios import MarketState


class MarketStateExtractor(ABC):
    """Bridge between product-specific pricing handles and generic market state."""

    @abstractmethod
    def extract(self, pricer: Any, leg: Any) -> MarketState:
        raise NotImplementedError

    @abstractmethod
    def reprice(self, state: MarketState, leg: Any) -> float:
        raise NotImplementedError


class BachelierExtractor(MarketStateExtractor):
    """Extractor for listed future options priced with normal vol."""

    def extract(self, pricer: Any, leg: Any) -> MarketState:
        tte = max((leg.expiry_date() - pricer.quote_timestamp().date()).days / 365.0, 0.0)
        return MarketState(
            forward=float(pricer.forward()),
            vol_normal=float(pricer.iv_normal()),
            discount=float(pricer.discount()),
            tte=float(tte),
            eval_date=pricer.quote_timestamp().date(),
        )

    def reprice(self, state: MarketState, leg: Any) -> float:
        self._validate_state(state)
        if float(state.tte) <= 0.0:
            return _intrinsic_payoff(
                right=leg.right(),
                strike=float(leg.strike()),
                forward=float(state.forward),
                scale=float(state.discount),
            )
        return float(
            bachelier_price(
                right=leg.right(),
                strike=float(leg.strike()),
                forward=float(state.forward),
                vol_normal=float(state.vol_normal),
                tte=float(state.tte),
                discount=float(state.discount),
            )
        )

    @staticmethod
    def _validate_state(state: MarketState) -> None:
        missing = [
            name
            for name in ("forward", "vol_normal", "discount", "tte")
            if getattr(state, name) is None
        ]
        if missing:
            raise ValueError(f"BachelierExtractor requires MarketState fields: {', '.join(missing)}")


class SwaptionExtractor(MarketStateExtractor):
    """
    Swaption extractor using a constant annuity/scale approximation.

    The inferred scale is stored in MarketState.discount so the common
    Bachelier pricing path can still be reused by the engine.
    """

    def extract(self, pricer: Any, leg: Any) -> MarketState:
        forward = float(leg_forward_rate(pricer, leg))
        vol_normal = float(leg_model_vol(pricer, leg))
        tte = float(leg_tte_years(pricer, leg))
        base_npv = float(leg_spot_npv(pricer, leg))

        unit_price = float(
            bachelier_price(
                right=self._leg_right(leg),
                strike=float(leg.strike),
                forward=forward,
                vol_normal=vol_normal,
                tte=tte,
                discount=1.0,
            )
        )
        scale = base_npv / unit_price if abs(unit_price) > 1e-14 else 0.0

        return MarketState(
            forward=forward,
            vol_normal=vol_normal,
            discount=float(scale),
            tte=tte,
            eval_date=pricer.as_of_date,
        )

    def reprice(self, state: MarketState, leg: Any) -> float:
        BachelierExtractor._validate_state(state)
        if float(state.tte) <= 0.0:
            return _intrinsic_payoff(
                right=self._leg_right(leg),
                strike=float(leg.strike),
                forward=float(state.forward),
                scale=float(state.discount),
            )
        return float(
            bachelier_price(
                right=self._leg_right(leg),
                strike=float(leg.strike),
                forward=float(state.forward),
                vol_normal=max(float(state.vol_normal), 0.0),
                tte=max(float(state.tte), 1e-12),
                discount=float(state.discount),
            )
        )

    @staticmethod
    def _leg_right(leg: Any) -> str:
        token = str(getattr(leg, "option_type", "")).strip().lower()
        if token in {"payer", "call", "c"}:
            return "C"
        if token in {"receiver", "put", "p"}:
            return "P"
        raise ValueError(f"Unsupported swaption option_type '{getattr(leg, 'option_type', None)}'")


_EXTRACTORS: dict[str, type[MarketStateExtractor]] = {}


def register_extractor(product: str, extractor_cls: type[MarketStateExtractor]) -> None:
    if not issubclass(extractor_cls, MarketStateExtractor):
        raise TypeError("extractor_cls must subclass MarketStateExtractor")
    _EXTRACTORS[str(product).upper()] = extractor_cls


def get_extractor(product: str) -> MarketStateExtractor:
    key = str(product).upper()
    try:
        return _EXTRACTORS[key]()
    except KeyError as exc:
        raise KeyError(
            f"No MarketStateExtractor registered for product '{product}'. "
            f"Registered: {sorted(_EXTRACTORS)}"
        ) from exc


register_extractor("STIRFUTUREOPTION", BachelierExtractor)
register_extractor("USTFUTUREOPTION", BachelierExtractor)
register_extractor("IRSWAPTION", SwaptionExtractor)
register_extractor("IRSWAPTIONS", SwaptionExtractor)


def _intrinsic_payoff(
    *,
    right: str,
    strike: float,
    forward: float,
    scale: float,
) -> float:
    token = str(right).upper()
    if token in {"C", "CALL"}:
        intrinsic = max(float(forward) - float(strike), 0.0)
    elif token in {"P", "PUT"}:
        intrinsic = max(float(strike) - float(forward), 0.0)
    else:
        raise ValueError(f"Unsupported option right for intrinsic payoff: {right}")
    return float(scale) * intrinsic
