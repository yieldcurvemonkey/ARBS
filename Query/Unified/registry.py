from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

from Query.Base.BaseQuery import BaseQuery
from Query.EventContracts.EventContractQuery import EventContractQuery
from Query.EventContracts.EventContractStructure import EventContractStructure
from Query.EventContracts.EventContractValue import EventContractValue
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FXForwards.FXForwardQuery import FXForwardQuery
from Query.FXForwards.FXForwardStructure import FXForwardStructure
from Query.FXForwards.FXForwardValue import FXForwardValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
from Query.Spreads.SpreadQuery import SpreadQuery
from Query.Spreads.SpreadStructure import SpreadStructure
from Query.Spreads.SpreadValue import SpreadValue
from Query.STIRCapFloors.STIRCapFloorQuery import STIRCapFloorQuery
from Query.STIRCapFloors.STIRCapFloorStructure import STIRCapFloorStructure
from Query.STIRCapFloors.STIRCapFloorValue import STIRCapFloorValue
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.USTFutureOptions.USTFutureOptionQuery import USTFutureOptionQuery
from Query.USTFutureOptions.USTFutureOptionStructure import USTFutureOptionStructure
from Query.USTFutureOptions.USTFutureOptionValue import USTFutureOptionValue
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureStructure import USTFutureStructure
from Query.USTFutures.USTFutureValue import USTFutureValue


def _normalize_product_token(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _as_selector(selector: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(selector or {})


def _selector_has_any(selector: Mapping[str, Any], *keys: str) -> bool:
    return any(selector.get(key) is not None for key in keys)


_CME_CODE_RE = r"[FGHJKMNQUVXZ]\d{1,2}"
_UST_FUTURE_ROOTS = ("TU", "FV", "TY", "US", "WN", "UXY", "ZT", "ZF", "ZN", "ZB", "UB", "TN")
_STIR_FUTURE_ROOTS = ("SR3", "SR1", "SFR", "SER", "FF", "ZQ", "SQ", "SL", "RA", "EB", "IJ", "RG", "IM", "TV", "J8", "JU", "T0", "IT", "J2")
_OPTION_SYMBOL_KEYS = ("symbol", "long_symbol", "short_symbol", "call_symbol", "put_symbol")
_STIR_OPTION_SIZE_KEYS = ("contracts", "dv01", "gamma_01", "vega_01")
_SWAPTION_HINT_KEYS = (
    "exercise_date",
    "underlying_effective_date",
    "underlying_maturity_date",
    "strike",
    "side",
    "trade_date",
)


def _symbol_candidates(selector: Mapping[str, Any], extra_keys: Iterable[str] = ()) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in (*_OPTION_SYMBOL_KEYS, "front_symbol", "back_symbol", "belly_symbol", "symbols", "tickers", "tenor", *extra_keys):
        raw = selector.get(key)
        if raw is None:
            continue
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        for value in values:
            token = str(value).strip().upper()
            if token and token not in seen:
                seen.add(token)
                out.append(token)
    return out


def _looks_like_fx_forward_symbol(token: str) -> bool:
    return ":" in str(token or "")


def _looks_like_ust_option_symbol(token: str) -> bool:
    sym = str(token or "").strip().upper()
    if "|" not in sym:
        return False
    left = sym.split("|", 1)[0]
    return any(left.startswith(root) or left.startswith(f"{root}_") for root in _UST_FUTURE_ROOTS)


def _looks_like_stir_option_symbol(token: str) -> bool:
    sym = str(token or "").strip().upper()
    if "|" not in sym:
        return False
    left = sym.split("|", 1)[0]
    return any(left.startswith(root) or left.startswith(f"{root}_") for root in _STIR_FUTURE_ROOTS)


def _looks_like_ust_future_symbol(token: str) -> bool:
    sym = str(token or "").strip().upper().replace("/", "")
    if "|" in sym:
        return False
    if any(re.fullmatch(rf"{root}{_CME_CODE_RE}", sym) for root in _UST_FUTURE_ROOTS):
        return True
    return any(sym.startswith(f"{root}_") for root in _UST_FUTURE_ROOTS)


def _looks_like_stir_future_symbol(token: str) -> bool:
    sym = str(token or "").strip().upper().replace("/", "")
    if "|" in sym:
        return False
    if re.fullmatch(_CME_CODE_RE, sym):
        return True
    return any(re.fullmatch(rf"{root}{_CME_CODE_RE}", sym) for root in _STIR_FUTURE_ROOTS)


def _looks_like_swap_tenor(token: str) -> bool:
    sym = str(token or "").strip().upper()
    if not sym or "|" in sym:
        return False
    if sym.startswith("IMM_"):
        return True
    if re.fullmatch(r"(\d+[DWMY])x(\d+[DWMY])", sym):
        return True
    if re.fullmatch(r"\d+[DWMY]", sym):
        return True
    if "/" in sym and any(part.endswith(("D", "W", "M", "Y")) or part.startswith("IMM_") for part in sym.split("/")):
        return True
    return bool(re.fullmatch(r"(CT\d+|O{1,3}\d+|OX\d+\d+|\d{4}(?:-\d{1,2})?)", sym))


def _classify_event(selector: Mapping[str, Any]) -> bool:
    return _selector_has_any(selector, "ticker", "market_id")


def _classify_fx_forward(selector: Mapping[str, Any]) -> bool:
    if selector.get("pair") is not None:
        return True
    return any(_looks_like_fx_forward_symbol(token) for token in _symbol_candidates(selector))


def _classify_fixed_rate_bond(selector: Mapping[str, Any]) -> bool:
    return _selector_has_any(selector, "cusip", "front_cusip", "back_cusip", "belly_cusip")


def _classify_spread(selector: Mapping[str, Any]) -> bool:
    return _selector_has_any(selector, "curve_a", "curve_b", "source_a", "source_b")


def _classify_swaption(selector: Mapping[str, Any]) -> bool:
    if _selector_has_any(selector, *_SWAPTION_HINT_KEYS):
        return True
    if _selector_has_any(selector, "swap_start", "swap_end"):
        return False
    return False


def _classify_stir_capfloor(selector: Mapping[str, Any]) -> bool:
    return _selector_has_any(selector, "swap_start", "swap_end")


def _classify_stir_future_option(selector: Mapping[str, Any]) -> bool:
    if _selector_has_any(selector, *_STIR_OPTION_SIZE_KEYS):
        return True
    return any(_looks_like_stir_option_symbol(token) for token in _symbol_candidates(selector))


def _classify_ust_future_option(selector: Mapping[str, Any]) -> bool:
    return any(_looks_like_ust_option_symbol(token) for token in _symbol_candidates(selector))


def _classify_stir_future(selector: Mapping[str, Any]) -> bool:
    if selector.get("is_ser") is not None:
        return True
    if _selector_has_any(selector, "front_curve", "back_curve"):
        return True
    if any(_looks_like_stir_future_symbol(token) for token in _symbol_candidates(selector)):
        return True
    tenor = selector.get("tenor")
    return bool(tenor is not None and _looks_like_stir_future_symbol(str(tenor)))


def _classify_ust_future(selector: Mapping[str, Any]) -> bool:
    if selector.get("contract") is not None:
        return True
    return any(_looks_like_ust_future_symbol(token) for token in _symbol_candidates(selector))


def _classify_ir_swap(selector: Mapping[str, Any]) -> bool:
    if selector.get("contract") is not None:
        return False
    tenor = selector.get("tenor")
    if tenor is not None and _looks_like_swap_tenor(str(tenor)):
        return True
    return _selector_has_any(selector, "front_tenor", "back_tenor", "belly_tenor")


def _spread_aliases() -> dict[str, str]:
    aliases = {
        "IRSPREAD": "IRSPREAD",
        "SPREAD": "IRSPREAD",
        "SPREADS": "IRSPREAD",
        "IRBASIS": "IRBASIS",
        "IRCHBASIS": "IRCHBASIS",
        "STIRCVX": "STIRCVX",
        "BASIS": "IRBASIS",
    }
    return {_normalize_product_token(k): v for k, v in aliases.items()}


def _alias_map(*aliases: str, query_product: str) -> dict[str, str]:
    out = {_normalize_product_token(query_product): query_product}
    for alias in aliases:
        out[_normalize_product_token(alias)] = query_product
    return out


@dataclass(frozen=True)
class _DescriptorSpec:
    canonical_product: str
    query_cls: type[BaseQuery]
    structure_enum_cls: type[Enum]
    value_enum_cls: type[Enum]
    classifier: Callable[[Mapping[str, Any]], bool]
    aliases: dict[str, str]
    ctor_selector_keys: tuple[str, ...]
    structure_selector_keys: tuple[str, ...]
    query_product_field: str | None = None


_DESCRIPTOR_SPECS: tuple[_DescriptorSpec, ...] = (
    _DescriptorSpec(
        canonical_product="IRS",
        query_cls=IRSwapQuery,
        structure_enum_cls=IRSwapStructure,
        value_enum_cls=IRSwapValue,
        classifier=_classify_ir_swap,
        aliases=_alias_map("IRSWAP", "IRSWAPS", "SWAP", "SWAPS", query_product="IRS"),
        ctor_selector_keys=("tenor", "effective_date", "maturity_date", "is_mms", "curve"),
        structure_selector_keys=(
            "front_tenor",
            "back_tenor",
            "belly_tenor",
            "front_effective_date",
            "back_effective_date",
            "belly_effective_date",
            "front_maturity_date",
            "back_maturity_date",
            "belly_maturity_date",
        ),
    ),
    _DescriptorSpec(
        canonical_product="IRSWAPTION",
        query_cls=IRSwaptionQuery,
        structure_enum_cls=IRSwaptionStructure,
        value_enum_cls=IRSwaptionValue,
        classifier=_classify_swaption,
        aliases=_alias_map("IRSWAPTIONS", "SWAPTION", "SWAPTIONS", query_product="IRSWAPTION"),
        ctor_selector_keys=(
            "curve",
            "shorthand",
            "expiry",
            "tail",
            "exercise_date",
            "underlying_effective_date",
            "underlying_maturity_date",
            "strike",
            "side",
            "trade_date",
        ),
        structure_selector_keys=tuple(),
    ),
    _DescriptorSpec(
        canonical_product="IRSPREAD",
        query_cls=SpreadQuery,
        structure_enum_cls=SpreadStructure,
        value_enum_cls=SpreadValue,
        classifier=_classify_spread,
        aliases=_spread_aliases(),
        ctor_selector_keys=("tenor", "curve_a", "curve_b", "source_a", "source_b"),
        structure_selector_keys=("front_tenor", "back_tenor", "belly_tenor"),
        query_product_field="product_key",
    ),
    _DescriptorSpec(
        canonical_product="STIRCAPFLOOR",
        query_cls=STIRCapFloorQuery,
        structure_enum_cls=STIRCapFloorStructure,
        value_enum_cls=STIRCapFloorValue,
        classifier=_classify_stir_capfloor,
        aliases=_alias_map("STIRCAPFLOORS", "CAPFLOOR", "CAPFLOORS", query_product="STIRCAPFLOOR"),
        ctor_selector_keys=("curve", "shorthand", "expiry", "tail", "swap_start", "swap_end"),
        structure_selector_keys=tuple(),
    ),
    _DescriptorSpec(
        canonical_product="STIRFUTURE",
        query_cls=STIRFutureQuery,
        structure_enum_cls=STIRFutureStructure,
        value_enum_cls=STIRFutureValue,
        classifier=_classify_stir_future,
        aliases=_alias_map("STIRFUTURES", "STIR", "STIRF", query_product="STIRFUTURE"),
        ctor_selector_keys=("tenor", "symbol", "effective_date", "maturity_date", "is_ser", "curve"),
        structure_selector_keys=(
            "front_symbol",
            "back_symbol",
            "belly_symbol",
            "symbols",
            "front_effective_date",
            "back_effective_date",
            "belly_effective_date",
            "front_maturity_date",
            "back_maturity_date",
            "belly_maturity_date",
            "front_curve",
            "back_curve",
        ),
    ),
    _DescriptorSpec(
        canonical_product="STIRFUTUREOPTION",
        query_cls=STIRFutureOptionQuery,
        structure_enum_cls=STIRFutureOptionStructure,
        value_enum_cls=STIRFutureOptionValue,
        classifier=_classify_stir_future_option,
        aliases=_alias_map("STIRFUTUREOPTIONS", "STIRFO", "STIROPTION", "STIROPTIONS", query_product="STIRFUTUREOPTION"),
        ctor_selector_keys=("symbol", "contracts", "dv01", "gamma_01", "vega_01"),
        structure_selector_keys=("long_symbol", "short_symbol", "call_symbol", "put_symbol", "symbols"),
    ),
    _DescriptorSpec(
        canonical_product="USTFUTURE",
        query_cls=USTFutureQuery,
        structure_enum_cls=USTFutureStructure,
        value_enum_cls=USTFutureValue,
        classifier=_classify_ust_future,
        aliases=_alias_map("USTFUTURES", "TREASURYFUTURE", "TREASURYFUTURES", "UST", query_product="USTFUTURE"),
        ctor_selector_keys=("tenor", "contract", "symbol", "curve"),
        structure_selector_keys=("front_symbol", "back_symbol", "belly_symbol", "symbols"),
    ),
    _DescriptorSpec(
        canonical_product="USTFUTUREOPTION",
        query_cls=USTFutureOptionQuery,
        structure_enum_cls=USTFutureOptionStructure,
        value_enum_cls=USTFutureOptionValue,
        classifier=_classify_ust_future_option,
        aliases=_alias_map("USTFUTUREOPTIONS", "USTFO", "TREASURYOPTION", "TREASURYOPTIONS", query_product="USTFUTUREOPTION"),
        ctor_selector_keys=("symbol",),
        structure_selector_keys=("long_symbol", "short_symbol", "call_symbol", "put_symbol", "symbols"),
    ),
    _DescriptorSpec(
        canonical_product="FRB",
        query_cls=FixedRateBondQuery,
        structure_enum_cls=FixedRateBondStructure,
        value_enum_cls=FixedRateBondValue,
        classifier=_classify_fixed_rate_bond,
        aliases=_alias_map("FIXEDRATEBOND", "FIXEDRATEBONDS", "BOND", "BONDS", query_product="FRB"),
        ctor_selector_keys=("cusip", "curve"),
        structure_selector_keys=("front_cusip", "back_cusip", "belly_cusip"),
    ),
    _DescriptorSpec(
        canonical_product="FXFORWARD",
        query_cls=FXForwardQuery,
        structure_enum_cls=FXForwardStructure,
        value_enum_cls=FXForwardValue,
        classifier=_classify_fx_forward,
        aliases=_alias_map("FXFORWARDS", "FXFWD", query_product="FXFORWARD"),
        ctor_selector_keys=("pair", "tenor", "symbol"),
        structure_selector_keys=tuple(),
    ),
    _DescriptorSpec(
        canonical_product="EVENT",
        query_cls=EventContractQuery,
        structure_enum_cls=EventContractStructure,
        value_enum_cls=EventContractValue,
        classifier=_classify_event,
        aliases=_alias_map("EVENTCONTRACT", "EVENTCONTRACTS", query_product="EVENT"),
        ctor_selector_keys=("ticker", "market_id"),
        structure_selector_keys=tuple(),
    ),
)


def _build_unified_enum(name: str, *, attr_name: str) -> type[Enum]:
    members: dict[str, str] = {}
    for spec in _DESCRIPTOR_SPECS:
        enum_cls = getattr(spec, attr_name)
        for member in enum_cls:
            unified_name = f"{spec.canonical_product}_{member.name}"
            members[unified_name] = unified_name
    return Enum(name, members)


UnifiedStructure = _build_unified_enum("UnifiedStructure", attr_name="structure_enum_cls")
UnifiedValue = _build_unified_enum("UnifiedValue", attr_name="value_enum_cls")


@dataclass(frozen=True)
class ProductDescriptor:
    canonical_product: str
    query_cls: type[BaseQuery]
    structure_enum_cls: type[Enum]
    value_enum_cls: type[Enum]
    classifier: Callable[[Mapping[str, Any]], bool]
    aliases: Mapping[str, str]
    ctor_selector_keys: tuple[str, ...]
    structure_selector_keys: tuple[str, ...]
    unified_structures: Mapping[UnifiedStructure, Enum]
    unified_values: Mapping[UnifiedValue, Enum]
    local_to_unified_structure: Mapping[Enum, UnifiedStructure]
    local_to_unified_value: Mapping[Enum, UnifiedValue]
    query_product_field: str | None = None

    @property
    def default_query_product(self) -> str:
        return self.aliases[_normalize_product_token(self.canonical_product)]

    def query_product_for_alias(self, product: str | None) -> str:
        if product is None:
            return self.default_query_product
        normalized = _normalize_product_token(product)
        try:
            return self.aliases[normalized]
        except KeyError as exc:
            raise KeyError(f"Unsupported product alias '{product}' for {self.canonical_product}.") from exc

    def classify(self, selector: Mapping[str, Any]) -> bool:
        return bool(self.classifier(selector))

    def to_local_structure(self, value: UnifiedStructure | None) -> Enum | None:
        if value is None:
            return None
        try:
            return self.unified_structures[value]
        except KeyError as exc:
            raise KeyError(f"{value.name} does not belong to {self.canonical_product}.") from exc

    def to_local_value(self, value: UnifiedValue | None) -> Enum | None:
        if value is None:
            return None
        try:
            return self.unified_values[value]
        except KeyError as exc:
            raise KeyError(f"{value.name} does not belong to {self.canonical_product}.") from exc

    def to_unified_structure(self, value: Enum) -> UnifiedStructure:
        try:
            return self.local_to_unified_structure[value]
        except KeyError as exc:
            raise KeyError(f"{value!r} is not registered under {self.canonical_product}.") from exc

    def to_unified_value(self, value: Enum) -> UnifiedValue:
        try:
            return self.local_to_unified_value[value]
        except KeyError as exc:
            raise KeyError(f"{value!r} is not registered under {self.canonical_product}.") from exc

    def translate_query(
        self,
        *,
        structure: UnifiedStructure | None,
        value: UnifiedValue | Sequence[UnifiedValue] | None,
        selector: Mapping[str, Any] | None,
        structure_kwargs: Mapping[str, Any] | None,
        market_request: Mapping[str, Any] | None,
        value_kwargs: Mapping[str, Any] | None,
        name: str | None,
        tags: Sequence[str] | None,
        meta: Mapping[str, Any] | None,
        risk_weight: float | None,
        product: str | None,
    ) -> BaseQuery:
        selector_dict = _as_selector(selector)
        structure_dict = copy.deepcopy(dict(structure_kwargs or {}))
        consumed_keys = set(self.ctor_selector_keys) | set(self.structure_selector_keys)
        unknown_selector_keys = sorted(
            key for key, value in selector_dict.items() if value is not None and key not in consumed_keys
        )
        if unknown_selector_keys:
            raise ValueError(
                f"Selector keys not supported for {self.canonical_product}: {', '.join(unknown_selector_keys)}"
            )

        for key in self.structure_selector_keys:
            value_from_selector = selector_dict.get(key)
            if value_from_selector is not None and key not in structure_dict:
                structure_dict[key] = copy.deepcopy(value_from_selector)

        init_fields = {
            field_name
            for field_name, field_def in self.query_cls.__dataclass_fields__.items()
            if field_def.init
        }

        kwargs: dict[str, Any] = {
            "structure_kwargs": structure_dict,
            "market_request": copy.deepcopy(dict(market_request or {})),
            "name": name,
            "tags": tuple(tags or ()),
            "meta": copy.deepcopy(dict(meta or {})),
            "risk_weight": risk_weight,
        }

        if "value_kwargs" in init_fields:
            kwargs["value_kwargs"] = copy.deepcopy(dict(value_kwargs or {}))

        local_structure = self.to_local_structure(structure)
        if local_structure is not None:
            kwargs["structure"] = local_structure

        if value is not None:
            if isinstance(value, (list, tuple)):
                kwargs["value"] = [self.to_local_value(item) for item in value]
            else:
                kwargs["value"] = self.to_local_value(value)

        for key in self.ctor_selector_keys:
            value_from_selector = selector_dict.get(key)
            if value_from_selector is not None:
                kwargs[key] = copy.deepcopy(value_from_selector)

        if self.query_product_field is not None:
            kwargs[self.query_product_field] = self.query_product_for_alias(product)

        filtered_kwargs = {key: value for key, value in kwargs.items() if key in init_fields and value is not None}
        return self.query_cls(**filtered_kwargs)


def _build_descriptors() -> tuple[ProductDescriptor, ...]:
    descriptors: list[ProductDescriptor] = []
    for spec in _DESCRIPTOR_SPECS:
        unified_structures = {
            getattr(UnifiedStructure, f"{spec.canonical_product}_{member.name}"): member
            for member in spec.structure_enum_cls
        }
        unified_values = {
            getattr(UnifiedValue, f"{spec.canonical_product}_{member.name}"): member
            for member in spec.value_enum_cls
        }
        descriptors.append(
            ProductDescriptor(
                canonical_product=spec.canonical_product,
                query_cls=spec.query_cls,
                structure_enum_cls=spec.structure_enum_cls,
                value_enum_cls=spec.value_enum_cls,
                classifier=spec.classifier,
                aliases=dict(spec.aliases),
                ctor_selector_keys=spec.ctor_selector_keys,
                structure_selector_keys=spec.structure_selector_keys,
                unified_structures=unified_structures,
                unified_values=unified_values,
                local_to_unified_structure={local: unified for unified, local in unified_structures.items()},
                local_to_unified_value={local: unified for unified, local in unified_values.items()},
                query_product_field=spec.query_product_field,
            )
        )
    return tuple(descriptors)


class DescriptorRegistry:
    def __init__(self, descriptors: Sequence[ProductDescriptor]):
        self._descriptors = tuple(descriptors)
        self._by_alias: dict[str, ProductDescriptor] = {}
        self._alias_query_products: dict[tuple[str, str], str] = {}
        self._structure_owners: dict[UnifiedStructure, list[ProductDescriptor]] = {}
        self._value_owners: dict[UnifiedValue, list[ProductDescriptor]] = {}
        self._local_structure_to_unified: dict[Enum, UnifiedStructure] = {}
        self._local_value_to_unified: dict[Enum, UnifiedValue] = {}

        for descriptor in self._descriptors:
            for alias_key, query_product in descriptor.aliases.items():
                self._by_alias[alias_key] = descriptor
                self._alias_query_products[(descriptor.canonical_product, alias_key)] = query_product
            for unified, local in descriptor.unified_structures.items():
                self._structure_owners.setdefault(unified, []).append(descriptor)
                self._local_structure_to_unified[local] = unified
            for unified, local in descriptor.unified_values.items():
                self._value_owners.setdefault(unified, []).append(descriptor)
                self._local_value_to_unified[local] = unified

    @property
    def descriptors(self) -> tuple[ProductDescriptor, ...]:
        return self._descriptors

    def descriptor_for_product(self, product: str) -> tuple[ProductDescriptor, str]:
        normalized = _normalize_product_token(product)
        descriptor = self._by_alias[normalized]
        query_product = self._alias_query_products[(descriptor.canonical_product, normalized)]
        return descriptor, query_product

    def descriptor_for_legacy_query(self, query: BaseQuery) -> ProductDescriptor:
        descriptor, _ = self.descriptor_for_product(query.product)
        return descriptor

    def _coerce_enum_string(
        self,
        *,
        value: str,
        enum_cls: type[Enum],
        product: str | None,
        label: str,
    ) -> Enum:
        token = value.strip().upper()
        if token in enum_cls.__members__:
            return enum_cls[token]

        exact_candidates = [member for member in enum_cls if member.name.split("_", 1)[1] == token]
        if product:
            descriptor, _ = self.descriptor_for_product(product)
            expected_name = f"{descriptor.canonical_product}_{token}"
            if expected_name in enum_cls.__members__:
                return enum_cls[expected_name]
            exact_candidates = [member for member in exact_candidates if member.name.startswith(f"{descriptor.canonical_product}_")]

        if len(exact_candidates) == 1:
            return exact_candidates[0]
        if len(exact_candidates) > 1:
            names = ", ".join(member.name for member in exact_candidates)
            raise ValueError(f"Ambiguous {label} '{value}'. Candidates: {names}.")

        suffix = f"_{token}"
        candidates = [member for member in enum_cls if member.name.endswith(suffix)]
        if product:
            descriptor, _ = self.descriptor_for_product(product)
            candidates = [member for member in candidates if member.name.startswith(f"{descriptor.canonical_product}_")]

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(member.name for member in candidates)
            raise ValueError(f"Ambiguous {label} '{value}'. Candidates: {names}.")
        raise KeyError(f"Unknown {label} '{value}'.")

    def coerce_structure(self, value: Any, *, product: str | None = None) -> UnifiedStructure | None:
        if value is None:
            return None
        if isinstance(value, UnifiedStructure):
            return value
        if isinstance(value, str):
            coerced = self._coerce_enum_string(value=value, enum_cls=UnifiedStructure, product=product, label="structure")
            return coerced
        if isinstance(value, Enum):
            try:
                return self._local_structure_to_unified[value]
            except KeyError as exc:
                raise KeyError(f"Unrecognized structure enum {value!r}.") from exc
        raise TypeError(f"Unsupported structure type: {type(value)}")

    def coerce_value(self, value: Any, *, product: str | None = None) -> UnifiedValue | None:
        if value is None:
            return None
        if isinstance(value, UnifiedValue):
            return value
        if isinstance(value, str):
            coerced = self._coerce_enum_string(value=value, enum_cls=UnifiedValue, product=product, label="value")
            return coerced
        if isinstance(value, Enum):
            try:
                return self._local_value_to_unified[value]
            except KeyError as exc:
                raise KeyError(f"Unrecognized value enum {value!r}.") from exc
        raise TypeError(f"Unsupported value type: {type(value)}")

    def coerce_values(self, value: Any, *, product: str | None = None) -> UnifiedValue | list[UnifiedValue] | None:
        if isinstance(value, (list, tuple)):
            return [self.coerce_value(item, product=product) for item in value]
        return self.coerce_value(value, product=product)

    def descriptor_for_structure(self, structure: UnifiedStructure) -> list[ProductDescriptor]:
        return list(self._structure_owners.get(structure, ()))

    def descriptor_for_value(self, value: UnifiedValue) -> list[ProductDescriptor]:
        return list(self._value_owners.get(value, ()))

    def infer_query_product(
        self,
        *,
        product: str | None,
        structure: UnifiedStructure | None,
        value: UnifiedValue | Sequence[UnifiedValue] | None,
        selector: Mapping[str, Any] | None,
    ) -> str | None:
        selector_dict = _as_selector(selector)
        candidates = list(self._descriptors)
        query_product: str | None = None

        if product:
            descriptor, query_product = self.descriptor_for_product(product)
            candidates = [descriptor]

        if structure is not None:
            owners = self.descriptor_for_structure(structure)
            candidates = [descriptor for descriptor in candidates if descriptor in owners]

        value_items = list(value) if isinstance(value, (list, tuple)) else [value] if value is not None else []
        for item in value_items:
            owners = self.descriptor_for_value(item)
            candidates = [descriptor for descriptor in candidates if descriptor in owners]

        if len(candidates) == 1:
            return query_product or candidates[0].default_query_product

        classified = [descriptor for descriptor in candidates if descriptor.classify(selector_dict)]
        if len(classified) == 1:
            return query_product or classified[0].default_query_product

        return query_product

    def resolve(
        self,
        *,
        product: str | None,
        structure: UnifiedStructure | None,
        value: UnifiedValue | Sequence[UnifiedValue] | None,
        selector: Mapping[str, Any] | None,
        structure_kwargs: Mapping[str, Any] | None,
        market_request: Mapping[str, Any] | None,
        value_kwargs: Mapping[str, Any] | None,
        name: str | None,
        tags: Sequence[str] | None,
        meta: Mapping[str, Any] | None,
        risk_weight: float | None,
    ) -> tuple[ProductDescriptor, BaseQuery]:
        selector_dict = _as_selector(selector)
        candidates = list(self._descriptors)
        explicit_query_product: str | None = None

        if product:
            descriptor, explicit_query_product = self.descriptor_for_product(product)
            candidates = [descriptor]

        if structure is not None:
            owners = self.descriptor_for_structure(structure)
            candidates = [descriptor for descriptor in candidates if descriptor in owners]

        value_items = list(value) if isinstance(value, (list, tuple)) else [value] if value is not None else []
        for item in value_items:
            owners = self.descriptor_for_value(item)
            candidates = [descriptor for descriptor in candidates if descriptor in owners]

        if not candidates:
            raise ValueError("UnifiedQuery product/structure/value combination did not match any registered product.")

        classified = [descriptor for descriptor in candidates if descriptor.classify(selector_dict)]
        if classified:
            candidates = classified

        translated: list[tuple[ProductDescriptor, BaseQuery]] = []
        failures: dict[str, str] = {}
        for descriptor in candidates:
            query_product = explicit_query_product or descriptor.default_query_product
            try:
                legacy = descriptor.translate_query(
                    structure=structure,
                    value=value,
                    selector=selector_dict,
                    structure_kwargs=structure_kwargs,
                    market_request=market_request,
                    value_kwargs=value_kwargs,
                    name=name,
                    tags=tags,
                    meta=meta,
                    risk_weight=risk_weight,
                    product=query_product,
                )
            except Exception as exc:
                failures[descriptor.canonical_product] = str(exc)
                continue
            translated.append((descriptor, legacy))

        if len(translated) == 1:
            return translated[0]

        if len(translated) > 1:
            products = ", ".join(descriptor.canonical_product for descriptor, _ in translated)
            raise ValueError(
                f"UnifiedQuery is ambiguous across products: {products}. "
                "Add an explicit product= or use namespaced UnifiedStructure/UnifiedValue."
            )

        details = "; ".join(f"{product_name}: {reason}" for product_name, reason in sorted(failures.items()))
        raise ValueError(
            "Unable to translate UnifiedQuery to a legacy query. "
            f"Candidates checked: {', '.join(descriptor.canonical_product for descriptor in candidates)}. "
            f"Failures: {details}"
        )

    def binding_records(self, *, kind: str) -> list[tuple[str, str, str]]:
        if kind not in {"structure", "value"}:
            raise ValueError("kind must be 'structure' or 'value'")
        rows: list[tuple[str, str, str]] = []
        for descriptor in self._descriptors:
            if kind == "structure":
                for local, unified in descriptor.local_to_unified_structure.items():
                    rows.append((descriptor.canonical_product, local.name, unified.name))
            else:
                for local, unified in descriptor.local_to_unified_value.items():
                    rows.append((descriptor.canonical_product, local.name, unified.name))
        return sorted(rows)


DESCRIPTOR_REGISTRY = DescriptorRegistry(_build_descriptors())
