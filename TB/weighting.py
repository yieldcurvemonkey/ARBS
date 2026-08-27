"""Data-driven leg weightings for package queries, applied by ``TimeseriesBuilder``.

A query carrying ``weighting=`` is not priced as a package. It is replaced,
before anything is routed, by its individual legs as outright queries; those are
fetched down the ordinary cached path; and the package is rebuilt afterwards as
``multiplier * sum_i w_i(t) * leg_i(t)`` with the weights fitted by
:mod:`RVUtils.fly`.

It has to work that way round. A PCA or regression weighting is a function of
the legs' joint history, so it cannot be known at the moment a single reference
date is priced - the pricer sees one curve, not a panel. Rebuilding from leg
series is not an approximation of the package price: ``IRSwapValue.RATE`` is
exactly ``sum_i w_i * curve.fair_rate(leg_i)``, linear in the leg rates, and the
same leg tenor builds the same swap whether it arrives inside a fly or on its
own (``Query/IRSwaps/IRSwapStructure._leg`` is reached identically from both).
``tests/test_timeseries_builder_weighting.py`` pins that: the identity schema
``RVUtils.fly.base`` reproduces the natively-priced fly column to 1e-9.

Units. An outright leg comes back in PERCENT (``_swap_structure_legs_mapper``
multiplies one leg by 100, and ``FixedRateBondValue`` by 1 onto an already-percent
yield) while a curve or fly comes back in BASIS POINTS (multiplier 10,000 for IRS,
100 for FRB onto percent). One factor of 100 closes the gap for both products;
:data:`PACKAGE_MULTIPLIER` is that factor.

    KNOWN DEFECT, NOT IN THIS MODULE: an FRB ``YTM`` curve or fly served by the
    leg-cache assembly in ``TB/FixedRateBondsTB.py`` (the ``composite_val =
    sum(w * v ...)`` line, around 444) never applies that 100, while the same
    column priced normally does. Measured on 2026-08-14 with identical legs,
    ``CT2/CT10 CURVE YTM`` came back 51.30 (bp) and ``CT2/CT5 CURVE YTM``,
    ``CT5/CT10 CURVE YTM`` and ``CT2/CT5/CT10 FLY YTM`` came back 0.190, 0.323
    and -0.133 (percent) - a silent 100x, decided by which cache tier answered,
    and written back into the row cache. The weighted columns this module builds
    follow the PRICER (bp, matching ``_frb_structure_legs_mapper``), so a
    weighted FRB package will disagree by 100x with a native column that came
    from that path. That is the native column being wrong.

Signs. The recombination here does NOT route through
``_swap_structure_sign_mapper``, which force-flips a fly's wings negative
whatever it is handed. That map is right for a hand-specified package and wrong
for a fitted one - a level hedge on a steep curve can genuinely want a wing on
the belly's side, and flipping it would invert the hedge. The base weights below
are the *signed* vectors that map produces for the default risk weights, and the
fitted weights are used exactly as solved.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import (
    FixedRateBondStructure,
    FixedRateBondStructureFunctionMap,
)
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, normalize_tenor_token
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.Unified.UnifiedQuery import UnifiedQuery
from RVUtils.fly.estimators import combine, solve_weights
from RVUtils.fly.schema import WeightingSchema, coerce

__all__ = [
    "PACKAGE_MULTIPLIER",
    "AttrBook",
    "WeightedPackagePlan",
    "plan_weighted_queries",
    "apply_weighted_plans",
]


class AttrBook(dict):
    """A ``dict`` for ``DataFrame.attrs`` that compares by identity.

    ``pandas`` propagates ``attrs`` through ``__finalize__``, and on a
    ``concat`` that runs ``all(obj.attrs == attrs for obj in ...)``. A plain
    dict holding DataFrames turns that into an elementwise DataFrame comparison
    and the whole concat dies with *"The truth value of a DataFrame is
    ambiguous"* - so simply putting the weight frames in ``attrs`` would break
    ``pd.concat`` on any column taken out of the result, which is the first
    thing anybody does with one. Identity comparison keeps ``attrs`` inert:
    frames sharing the same book keep it, frames that do not lose it, and
    neither raises.

    Everything else is an ordinary dict.
    """

    __slots__ = ()

    def __eq__(self, other: Any) -> bool:
        return self is other

    def __ne__(self, other: Any) -> bool:
        return self is not other

    __hash__ = object.__hash__  # type: ignore[assignment]

#: Leg values are quoted in percent, package values in basis points.
PACKAGE_MULTIPLIER = 100.0

#: The signed weights the pricer applies to a default two- and three-leg package.
#: IRS: ``_swap_structure_sign_mapper[FLY]`` forces ``(-|w0|, +|w1|, -|w2|)`` onto
#: the ``[1, 2, 1]`` default, and ``_build_curve``'s ``copysign`` block turns the
#: ``[1, 1]`` default into ``(-1, +1)`` under the ``bpv=1`` that ``resolve_query``
#: sets. FRB reaches the same two vectors through its own ``copysign`` blocks and
#: an identity sign map, with ``bpv=1.0`` from ``FixedRateBondQuery.resolve_query``.
BASE_WEIGHTS: Dict[int, Tuple[float, ...]] = {
    2: (-1.0, 1.0),
    3: (-1.0, 2.0, -1.0),
}

_ELIGIBLE_VALUES = {
    "IRS": IRSwapValue.RATE,
    "FRB": FixedRateBondValue.YTM,
}


@dataclass(frozen=True)
class WeightedPackagePlan:
    """One weighted package: what to fetch, and how to put it back together."""

    schema: WeightingSchema
    column: str
    product: str
    leg_columns: Tuple[str, ...]
    leg_queries: Tuple[BaseQuery, ...]
    base_weights: Tuple[float, ...]
    multiplier: float = PACKAGE_MULTIPLIER
    #: Legs the caller did not ask for by name and which are dropped afterwards.
    private_leg_columns: Tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# expansion
# --------------------------------------------------------------------------- #


def _legacy(query: Any) -> BaseQuery:
    return query.to_legacy() if isinstance(query, UnifiedQuery) else query


def _check_value(query: BaseQuery) -> None:
    product = str(getattr(query, "product", "") or "")
    expected = _ELIGIBLE_VALUES.get(product)
    value = getattr(query, "value", None)
    if expected is None:
        raise NotImplementedError(
            f"weighting= is implemented for IRS and FRB packages; got product {product!r}. "
            "Every other product's package value is not a plain risk-weighted sum of its legs, "
            "so recombining leg series would not reproduce it."
        )
    if isinstance(value, list):
        raise NotImplementedError(
            "weighting= needs a single value; pass one query per value rather than value=[...]"
        )
    if value is not expected:
        raise NotImplementedError(
            f"weighting= supports {product} {expected.name} only, got {getattr(value, 'name', value)!r}. "
            f"Only {expected.name} is a linear risk-weighted sum of the same value on each leg."
        )


def _irs_legs(query: IRSwapQuery) -> List[IRSwapQuery]:
    tenor = str(getattr(query, "tenor", "") or getattr(query, "structure_kwargs", {}).get("tenor", "") or "")
    tokens = [tok.strip() for tok in tenor.split("/") if tok.strip()]
    if len(tokens) < 2:
        raise ValueError(
            f"weighting= needs a multi-leg package; tenor {tenor!r} has {len(tokens)} leg(s). "
            "Write it as 'front/belly/back' (fly) or 'front/back' (curve)."
        )
    market_request = {k: v for k, v in dict(query.market_request or {}).items() if k != query.mdp_time_key}
    return [
        IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            # The same normalisation ``resolve_query`` applies to a package's leg
            # tokens, so the outright builds the identical swap. Skipping it is
            # what makes a fly leg spelled "1y5y" price and the outright fail.
            tenor=normalize_tenor_token(token),
            curve=query.curve,
            market_request=dict(market_request),
            mdp_time_key=query.mdp_time_key,
        )
        for token in tokens
    ]


def _frb_legs(query: FixedRateBondQuery) -> List[FixedRateBondQuery]:
    raw = getattr(query, "cusip", None) or dict(getattr(query, "structure_kwargs", {}) or {}).get("cusip")
    # The builder's own splitter, so the leg ORDER here is the leg order the
    # package would have used.
    tokens = FixedRateBondStructureFunctionMap._split_package_cusips(raw)
    if not tokens or len(tokens) < 2:
        raise ValueError(
            f"weighting= could not split {raw!r} into legs. Bond packages split on '/' or 'x'; "
            "a two-leg package of raw CUSIPs beginning with four digits is not recognised as one "
            "(Query/FixedRateBonds/FixedRateBondStructure._split_package_cusips) - name the legs "
            "explicitly or use the on-the-run aliases."
        )
    market_request = {k: v for k, v in dict(query.market_request or {}).items() if k != query.mdp_time_key}
    return [
        FixedRateBondQuery(
            structure=FixedRateBondStructure.OUTRIGHT,
            value=FixedRateBondValue.YTM,
            cusip=token,
            curve=query.curve,
            market_request=dict(market_request),
            mdp_time_key=query.mdp_time_key,
        )
        for token in tokens
    ]


def expand_package(query: Any) -> Tuple[List[BaseQuery], Tuple[float, ...]]:
    """The single-leg queries behind a package, and the package's signed weights."""
    legacy = _legacy(query)
    _check_value(legacy)
    if isinstance(legacy, IRSwapQuery):
        legs: List[BaseQuery] = list(_irs_legs(legacy))
    elif isinstance(legacy, FixedRateBondQuery):
        legs = list(_frb_legs(legacy))
    else:  # pragma: no cover - _check_value already rejects everything else
        raise NotImplementedError(f"weighting= cannot expand {type(legacy).__name__}")

    base = BASE_WEIGHTS.get(len(legs))
    if base is None:
        raise NotImplementedError(
            f"weighting= handles two- and three-leg packages; got {len(legs)} legs. "
            "The pricer itself only maps 1, 2 and 3 legs to a structure."
        )
    return legs, base


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #


def _iter_queries(queries: Iterable[Any]) -> Iterable[Any]:
    for item in queries:
        if isinstance(item, list):
            yield from item
        else:
            yield item


def _column_of(query: Any) -> str:
    try:
        return str(query.col_name())
    except Exception:  # pragma: no cover - mirrors TimeseriesBuilder._safe_col_name
        return f"col_{id(query)}"


def plan_weighted_queries(queries: Sequence[Any]) -> Tuple[List[Any], List[WeightedPackagePlan]]:
    """Split ``queries`` into what to fetch and what to rebuild afterwards.

    Returns the query list to hand to the ordinary pipeline - every weighted
    package replaced by its legs, everything else untouched and in its original
    order - together with one :class:`WeightedPackagePlan` per weighted package.

    A query without ``weighting=`` is passed through by identity, so a request
    that uses none of this is byte-identical to what it was before.
    """
    flat = list(_iter_queries(queries))
    if not any(getattr(query, "weighting", None) is not None for query in flat):
        # The overwhelmingly common case, and the one that must stay free:
        # ``get_timeseries`` re-enters itself on the live and Barchart-bulk
        # paths, so this runs on every nested call too. Do not build column
        # names here.
        return list(queries), []

    plans: List[WeightedPackagePlan] = []
    rewritten: List[Any] = []
    seen_leg_columns: Dict[str, Any] = {}
    requested_columns: set[str] = set()

    for query in flat:
        if coerce(getattr(query, "weighting", None)) is None:
            requested_columns.add(_column_of(query))

    for query in flat:
        schema = coerce(getattr(query, "weighting", None))
        if schema is None:
            rewritten.append(query)
            continue

        legs, base = expand_package(query)
        leg_columns = tuple(_column_of(leg) for leg in legs)
        private = tuple(dict.fromkeys(col for col in leg_columns if col not in requested_columns))

        for leg, column in zip(legs, leg_columns):
            if column not in seen_leg_columns:
                seen_leg_columns[column] = leg
                rewritten.append(leg)

        legacy = _legacy(query)
        column = f"{_column_of(legacy)} [{schema.label}]"
        plans.append(
            WeightedPackagePlan(
                schema=schema,
                column=column,
                product=str(getattr(legacy, "product", "") or ""),
                leg_columns=leg_columns,
                leg_queries=tuple(legs),
                base_weights=tuple(float(w) for w in base),
                private_leg_columns=() if schema.keep_legs else private,
            )
        )

    return rewritten, plans


# --------------------------------------------------------------------------- #
# recombination
# --------------------------------------------------------------------------- #


def _resolve_column(frame: pd.DataFrame, name: str) -> Any:
    """Find ``name`` whether or not the frame still carries the product level."""
    if isinstance(frame.columns, pd.MultiIndex):
        matches = [col for col in frame.columns if str(col[-1]) == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError(f"{name!r} is ambiguous across products: {matches}")
        return None
    return name if name in frame.columns else None


def _insert(frame: pd.DataFrame, name: str, product: str, series: pd.Series) -> None:
    key: Any = (product or "WEIGHTED", name) if isinstance(frame.columns, pd.MultiIndex) else name
    frame[key] = series


def apply_weighted_plans(
    frame: pd.DataFrame,
    plans: Sequence[WeightedPackagePlan],
) -> pd.DataFrame:
    """Rebuild every planned package from its leg columns, in place on a copy.

    The fitted weights land in ``frame.attrs["fly_weights"][column]`` as a
    ``T x n`` frame columned by leg, whatever ``emit_weights`` says - so a P&L
    that needs ``w[t-1] . dy[t]`` can always get at them - alongside the schema
    in ``["fly_schemas"]`` and the leg panel in ``["fly_legs"]``.
    """
    if not plans:
        return frame
    if frame is None or frame.empty:
        raise ValueError(
            "weighting= was requested but the fetch returned no rows, so there is nothing to fit on."
        )

    out = frame.copy()
    weights_by_column = AttrBook(out.attrs.get("fly_weights", {}))
    schemas_by_column = AttrBook(out.attrs.get("fly_schemas", {}))
    legs_by_column = AttrBook(out.attrs.get("fly_legs", {}))
    droppable: set[Any] = set()
    protected: set[Any] = set()
    done: set[str] = set()

    for plan in plans:
        keys = []
        for leg_column in plan.leg_columns:
            key = _resolve_column(out, leg_column)
            if key is None:
                raise KeyError(
                    f"weighted package {plan.column!r} needs leg column {leg_column!r}, which the fetch "
                    f"did not produce. Columns returned: {sorted(str(c) for c in out.columns)}"
                )
            keys.append(key)

        # A leg any schema wants kept is kept for all of them; a leg only the
        # weighting itself pulled in goes away again.
        for leg_column, key in zip(plan.leg_columns, keys):
            if plan.schema.keep_legs:
                protected.add(key)
            elif leg_column in plan.private_leg_columns:
                droppable.add(key)

        if plan.column in done:
            continue
        done.add(plan.column)

        legs = out.loc[:, keys].copy()
        legs.columns = list(plan.leg_columns)
        weight_frame = solve_weights(legs, plan.base_weights, plan.schema)
        series = combine(
            legs,
            weight_frame,
            multiplier=plan.multiplier,
            mode=plan.schema.resolved_combine_mode,
        )
        series.name = plan.column
        _insert(out, plan.column, plan.product, series)

        weights_by_column[plan.column] = weight_frame
        schemas_by_column[plan.column] = plan.schema
        legs_by_column[plan.column] = legs

        if plan.schema.emit_weights:
            for i, leg_column in enumerate(plan.leg_columns):
                _insert(
                    out,
                    f"{plan.column} W{i + 1}",
                    plan.product,
                    weight_frame.iloc[:, i].rename(f"{plan.column} W{i + 1}"),
                )

    to_drop = [key for key in droppable if key not in protected]
    if to_drop:
        out = out.drop(columns=to_drop)

    out.attrs["fly_weights"] = weights_by_column
    out.attrs["fly_schemas"] = schemas_by_column
    out.attrs["fly_legs"] = legs_by_column
    return out
