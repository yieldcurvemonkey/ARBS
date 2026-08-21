r"""The Citi Velocity query object.

Follows the repo's product pattern exactly: a frozen dataclass over
:class:`~Query.Base.BaseQuery.BaseQuery` that syncs the base fields in
``__post_init__``, fans a list-valued ``value`` out through ``return_query()``, and
names its own column through ``col_name``/``eval_expression``.

What is Velocity-specific is the leg spec. A Velocity query names *what to look
at* - a family, a curve, a tenor, an expiry, a strike offset, an ISIN - and the
pricer resolves that into a tag. A caller who already knows the tag can pass it
straight through with ``tag=``; anything ``RATES.*`` is accepted unchanged, so a
tag newer than the committed catalog is never blocked.

Naming a tag you can find
-------------------------
``tag=`` also takes a member of the generated enums in
:mod:`Query.CitiVelocity.tag_enums` - every one of the 67,425 tags the committed
catalog can name, arranged as a tree a language server can complete through::

    CitiVeloQuery(tag=CitiVeloQuery.Tags.OIS.USD_SOFR.PAR_10Y)
    CitiVeloQuery(tag=CitiVeloQuery.Tags.VOL.USD.ATM_RFR.BLACK_1Y_10Y)

Depth varies - a node splits only once it holds more than 1,024 tags - so
``ATM_RFR`` is a flat enum with 765 members while its ``OTM_RFR`` sibling splits
one level further into ``NORMALABSOLUTE`` and friends. You do not have to know
that: type the dot. ``CitiVeloQuery.Tags.find("RATES...")`` resolves any tag
string whatever its depth.

That is the same string either way - members are ``StrEnum``, and
``__post_init__`` normalises them to a plain ``str`` so nothing downstream can
tell which spelling was used. The raw-string path is unchanged and unblocked:
the enum is a discovery surface, never a gate. See
:mod:`Query.CitiVelocity.tag_enums._base` for what the enum covers, what it
deliberately does not, and the measurements behind both.

>>> q = CitiVeloQuery(citi_index="USD_SOFR", tenor="10Y")
>>> q.product
'CITIVELO'
>>> q.col_name()
'USD_SOFR 10Y OUTRIGHT QUOTE'
>>> fly = CitiVeloQuery(citi_index="USD_SOFR", structure=CitiVeloStructure.FLY,
...                     structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y",
...                                       "back_tenor": "10Y"})
>>> fly.col_name()
'USD_SOFR 2Y-5Y-10Y FLY QUOTE'
"""

from __future__ import annotations

import datetime
import enum
import re
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple, Type, Union

from Query.Base.BaseQuery import BaseQuery
from Query.CitiVelocity import adapter as _citivelo_adapter  # noqa: F401  (registers the product)
from Query.CitiVelocity.CitiVeloStructure import CitiVeloStructure
from Query.CitiVelocity.CitiVeloValue import CitiVeloValue
from Query.CitiVelocity.tag_enums import CitiVeloTag, CitiVeloTags

__all__ = ["CitiVeloQuery", "CitiVeloQueryWrapper"]

#: What a ``tag=`` argument may be. A :class:`CitiVeloTag` member *is* a ``str``,
#: so this widening costs nothing at run time; it exists so a type checker will
#: offer the enum, and so the docstring can say the enum is supported.
TagLike = Union[str, CitiVeloTag]


def _as_tag_str(value: Any) -> Any:
    """Plain ``str`` for a tag; raise for a foreign enum; everything else untouched.

    A :class:`CitiVeloTag` member already compares and hashes as its own value, so
    nothing *breaks* without the normalisation. What it prevents is subtler: the
    member carries a repr and a type through to places that display it. A
    ``DataFrame`` column labelled with one renders as
    ``<PAR_10Y: 'RATES.OIS...'>``, a parquet path derived from it reads back as a
    plain string it no longer equals by ``type``, and any ``type(x) is str`` check
    downstream silently takes the other branch. Normalising once, here, is cheaper
    than auditing every consumer - and it makes
    ``CitiVeloQuery(tag=OIS.USD_SOFR.PAR_10Y) == CitiVeloQuery(tag="RATES.OIS...")``
    true by construction rather than by luck.

    Any *other* enum raises. The pricer's resolver does an unconditional
    ``classify_tag(str(explicit))``, and ``str()`` of a foreign ``(str, Enum)``
    member is ``'ClassName.MEMBER'`` - which ``classify_tag`` accepts as a ``RAW``
    tag without complaint, sends to the add-in, and gets nothing back for. The
    error then points at Citi rather than at the argument. Refusing here turns a
    misleading empty series into a message naming the type.
    """
    if isinstance(value, CitiVeloTag):
        return str(value)
    if isinstance(value, enum.Enum):
        raise TypeError(
            f"tag={value!r} is a {type(value).__name__}, not a Citi Velocity tag. Only "
            "Query.CitiVelocity.tag_enums members are understood; str() of any other enum "
            f"is {str(value)!r}, which the tag classifier would accept as a RAW tag and "
            "then fail to serve, blaming the add-in. Pass the plain string, or look it up "
            "with CitiVeloQuery.Tags.find(<tag>)."
        )
    return value

#: Structure kwargs that describe a leg rather than the structure's geometry.
_LEG_FIELDS = (
    "tag",
    "family",
    "citi_index",
    "currency",
    "counter_currency",
    "tenor",
    "forward",
    "expiry",
    "offset_bp",
    "isin",
    "measure",
)


@dataclass(frozen=True)
class CitiVeloQuery(BaseQuery):
    """One Citi Velocity structure and the metric to compute over it."""

    # -- what to compute ------------------------------------------------
    structure: CitiVeloStructure = CitiVeloStructure.OUTRIGHT
    value: Union[CitiVeloValue, List[CitiVeloValue]] = CitiVeloValue.QUOTE

    # -- what to look at ------------------------------------------------
    family: Optional[str] = None
    citi_index: Optional[str] = None
    currency: Optional[str] = None
    counter_currency: Optional[str] = None
    tenor: Optional[str] = None
    forward: Optional[str] = None
    expiry: Optional[str] = None
    offset_bp: Optional[float] = None
    isin: Optional[str] = None
    measure: Optional[str] = None
    #: A raw ``RATES.*`` string, or a member of the generated tag enums. Both are
    #: normalised to a plain ``str`` in ``__post_init__``; see :func:`_as_tag_str`.
    tag: Optional[TagLike] = None

    # -- how to fetch it ------------------------------------------------
    freq: str = "DAILY"
    price_point: str = "CLOSE"
    method: str = "asof"

    # -- the repo-wide product trio -------------------------------------
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="CITIVELO")
    structure_id: Any = field(init=False, default=None)

    #: The whole generated tag tree, reachable from the class a caller already
    #: imported::
    #:
    #:     CitiVeloQuery(tag=CitiVeloQuery.Tags.OIS.USD_SOFR.PAR_10Y)
    #:
    #: ``ClassVar`` is load-bearing, not decoration: without it ``dataclass``
    #: would read this as a field with a mutable class default and every query
    #: would gain a ``Tags`` constructor argument.
    Tags: ClassVar[Type[CitiVeloTags]] = CitiVeloTags

    # -- construction ---------------------------------------------------

    def __post_init__(self) -> None:
        object.__setattr__(self, "product", "CITIVELO")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "tag", _as_tag_str(self.tag))

        skw = dict(self.structure_kwargs or {})
        # Legs carry their own tags, and a SPREAD's legs are the one place a
        # caller reaches for the enum most - a cross-curve spread is exactly what
        # you build by picking two members. Normalise them on the way in; a copy
        # per leg because mutating the caller's dict in place would be a
        # side effect on an argument they still hold.
        if skw.get("legs"):
            skw["legs"] = [
                {k: _as_tag_str(v) if k == "tag" else v for k, v in dict(spec).items()}
                if isinstance(spec, dict)
                else spec
                for spec in skw["legs"]
            ]
        if "tag" in skw:
            skw["tag"] = _as_tag_str(skw["tag"])
        for name in _LEG_FIELDS:
            supplied = getattr(self, name, None)
            if supplied is not None and name not in skw:
                skw[name] = supplied
        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        mr.setdefault("freq", self.freq)
        mr.setdefault("price_point", self.price_point)
        mr.setdefault("method", self.method)
        if self.citi_index is not None:
            mr.setdefault("citi_index", self.citi_index)
        if self.currency is not None:
            mr.setdefault("currency", self.currency)
        mr.setdefault("tags", tuple(self.leg_tag_hints()))
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    # -- required BaseQuery hooks ---------------------------------------

    def return_query(self) -> List["CitiVeloQuery"]:
        """Fan a list-valued ``value`` out into one query per value."""
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        """The DataFrame column label for this query."""
        if self.name:
            return str(self.name)
        subject = cube_name or self._subject()
        geometry = self._geometry()
        value = self.value.name if not isinstance(self.value, list) else "MULTI"
        parts = [p for p in (subject, geometry, self.structure.name, value) if p]
        return re.sub(r"\s\s+", " ", " ".join(parts)).strip()

    def eval_expression(self, cube_name: Optional[str] = None, ignore_risk_weight: bool = False) -> str:
        """The ``df.eval`` string that references this query's column."""
        col = self.col_name(cube_name=cube_name)
        if (self.risk_weight is not None) and (not ignore_risk_weight):
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    # -- helpers --------------------------------------------------------

    def _subject(self) -> str:
        if self.tag:
            return self.tag
        for candidate in (self.citi_index, self.isin, self.currency):
            if candidate:
                if self.counter_currency:
                    return f"{candidate}{self.counter_currency}"
                return str(candidate)
        return self.family or "CITIVELO"

    def _geometry(self) -> str:
        skw = self.structure_kwargs or {}
        if self.structure is CitiVeloStructure.CURVE:
            return f"{skw.get('front_tenor')}-{skw.get('back_tenor')}"
        if self.structure is CitiVeloStructure.FLY:
            return f"{skw.get('front_tenor')}-{skw.get('belly_tenor')}-{skw.get('back_tenor')}"
        if self.structure is CitiVeloStructure.CONDOR:
            return (
                f"{skw.get('front_tenor')}-{skw.get('front_belly_tenor')}"
                f"-{skw.get('back_belly_tenor')}-{skw.get('back_tenor')}"
            )
        if self.structure is CitiVeloStructure.SPREAD:
            legs = skw.get("legs") or []
            return "/".join(str(spec.get("tenor") or spec.get("citi_index") or "?") for spec in legs)
        bits = [b for b in (self.expiry, self.tenor) if b]
        if self.offset_bp:
            bits.append(f"{self.offset_bp:+.0f}bp")
        return "x".join(bits) if bits else ""

    def leg_tag_hints(self) -> Tuple[str, ...]:
        """Tags this query is known to need, before the pricer resolves it.

        Only populated when the caller gave explicit tags; the resolver fills the
        rest. Used by the timeseries builder to pre-batch a fetch.
        """
        skw = self.structure_kwargs or {}
        out: List[str] = []
        if skw.get("tag"):
            out.append(str(skw["tag"]))
        for spec in skw.get("legs") or []:
            if isinstance(spec, dict) and spec.get("tag"):
                out.append(str(spec["tag"]))
        return tuple(dict.fromkeys(out))

    @property
    def is_quote_only(self) -> bool:
        """True when every requested value is a published quote.

        This is the predicate the timeseries fast path routes on.
        """
        values = self.value if isinstance(self.value, list) else [self.value]
        return all(isinstance(v, CitiVeloValue) and v.is_quote for v in values)


@dataclass(frozen=True)
class CitiVeloQueryWrapper:
    """A linear combination of Citi Velocity queries, evaluated after assembly.

    Mirrors ``IRSwapQueryWrapper``: the component queries are priced normally and
    the wrapper's expression is evaluated over the resulting frame.
    """

    queries: Tuple[CitiVeloQuery, ...] = tuple()
    name: Optional[str] = None

    def return_query(self) -> List[CitiVeloQuery]:
        out: List[CitiVeloQuery] = []
        for q in self.queries:
            out.extend(q.return_query())
        return out

    def col_name(self, cube_name: Optional[str] = None) -> str:
        if self.name:
            return str(self.name)
        return " + ".join(q.col_name(cube_name) for q in self.queries)

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        return " + ".join(q.eval_expression(cube_name) for q in self.queries)
