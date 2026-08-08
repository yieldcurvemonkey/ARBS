r"""Getting from what a caller typed to the bond Citi is actually quoting.

The repo keys UST bonds by CUSIP and offers on-the-run aliases (``CT10``, ``OO5``,
``Ox230``, ``0832``). Citi Velocity keys bonds by ISIN and by nothing else. So a
query has to cross a gap, and crossing it has two halves that fail differently:

**Arithmetic** - ``US`` + CUSIP + ISO 6166 check digit. Mechanical, and verified
in :mod:`utils.identifiers` against 2,162 real Citi ISINs. This half is either
right or it raises.

**Existence** - Citi has to actually quote that ISIN. The arithmetic cannot tell
you this, and it fails *quietly*: a well-formed ISIN for a bond outside Citi's
universe looks exactly like one inside it. Of the 349 US Treasuries Citi carries,
none is the whole UST universe - a query for an off-the-run bond, a TIPS, a bill,
or a just-auctioned issue resolves arithmetically and then serves nothing.

So resolution here always ends by consulting the harvested universe, and reports
which of the two halves failed. :class:`BondResolution` records the route taken
so a surprising answer can be traced back rather than re-derived.

What this module does NOT do
----------------------------
Alias-to-CUSIP. That already exists three times over (``FixedRateBondsMDP.
_resolve_aliases_bulk``, ``FixedRateBondQuery._resolve_on_the_run_token``, and
``Query.IRSwaps.adapter._resolve_cusip_or_alias``), all keyed off the UST
reference table, and a fourth implementation would be a fourth thing to keep in
step. The Velocity bond source is wired *inside* ``FixedRateBondsMDP``
specifically so that the existing resolver runs first and this module only ever
sees a CUSIP.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from MDP.CitiVelocityExcel.bonds.universe import BondDescriptor, BondUniverse
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from utils.identifiers import (
    InvalidIdentifierError,
    cusip_to_isin,
    is_valid_isin,
    isin_to_cusip,
    normalise_cusip,
    validate_isin,
)

__all__ = [
    "BondNotQuotedError",
    "BondResolution",
    "resolve_bond",
    "resolve_bonds",
]


class BondNotQuotedError(CitiVelocityError):
    """The identifier is well formed but Citi does not quote that bond."""


@dataclasses.dataclass(frozen=True)
class BondResolution:
    """How one caller token became one Citi ISIN.

    Attributes
    ----------
    token
        Exactly what the caller passed, untouched.
    isin
        The resolved ISIN, present in Citi's universe.
    cusip
        The 9-character CUSIP when one exists (US and CA securities), else
        ``None``. For a bond reached by ISIN directly this is filled in only when
        the NSIN validates as a CUSIP.
    route
        ``"isin"`` when the token was already an ISIN, ``"cusip"`` when it was
        completed arithmetically. The route is recorded rather than inferred
        because the two have different failure modes and a support question
        usually starts with "which one did it take".
    descriptor
        Citi's own record for the bond: description, ticker, coupon, maturity.
        ``None`` only when resolution ran with ``require_quoted=False`` and the
        bond is outside Citi's universe.
    available_values
        The Citi value tokens validated for this ISIN, e.g.
        ``['PRICE', 'YIELD', 'SPREAD_TSY', ...]``. Coverage is per-bond and
        uneven - ``ASW_4_USD`` exists for half the universe, ``DURATION`` for
        nearly all of it - so this is consulted rather than assumed.
    """

    token: str
    isin: str
    cusip: Optional[str]
    route: str
    descriptor: Optional[BondDescriptor]
    available_values: Tuple[str, ...]

    @property
    def quoted(self) -> bool:
        """Whether Citi carries this bond at all."""
        return self.descriptor is not None

    @property
    def priceable(self) -> bool:
        """Whether Citi's description yielded both a coupon and a maturity."""
        return self.descriptor is not None and self.descriptor.priceable

    def serves(self, value: str) -> bool:
        """Whether Citi serves ``value`` for this particular bond."""
        return str(value).strip().upper() in self.available_values

    def describe(self) -> str:
        if self.descriptor is None:
            return f"{self.token} -> {self.isin} via {self.route}, NOT quoted by Citi"
        return (
            f"{self.token} -> {self.isin} ({self.descriptor.description}) "
            f"via {self.route}, {len(self.available_values)} values"
        )


def _universe(universe: Optional[BondUniverse]) -> BondUniverse:
    return universe if universe is not None else BondUniverse.from_catalog()


def resolve_bond(
    token: str,
    *,
    universe: Optional[BondUniverse] = None,
    country: str = "US",
    require_quoted: bool = True,
) -> BondResolution:
    """Resolve one CUSIP or ISIN to the bond Citi quotes.

    Parameters
    ----------
    token
        A 12-character ISIN, or an 8- or 9-character CUSIP. On-the-run aliases
        (``CT10`` and friends) are **not** accepted here - resolve those to a
        CUSIP first through the UST reference table; see the module docstring.
    universe
        A :class:`BondUniverse`. Defaults to the full committed catalog, which
        costs one JSON read and no Excel.
    country
        ISO 3166 alpha-2 used when completing a CUSIP. ``US`` unless you are
        deliberately resolving a Canadian security.
    require_quoted
        Leave ``True`` so a bond outside Citi's universe raises instead of
        producing a dead ISIN. Set ``False`` only to ask "what would the ISIN
        be", e.g. when reporting coverage.

    Returns
    -------
    BondResolution

    Raises
    ------
    InvalidIdentifierError
        The token is not a well-formed CUSIP or ISIN. Nothing is looked up:
        arithmetic failure is distinguished from a coverage gap.
    BondNotQuotedError
        Well formed, but absent from Citi's universe. The message reports the
        route taken, so a wrong-bond resolution is visible rather than silent.

    Examples
    --------
    >>> r = resolve_bond("91282CLF6")                    # doctest: +SKIP
    >>> r.isin, r.route                                  # doctest: +SKIP
    ('US91282CLF67', 'cusip')
    """
    raw = str(token).strip().upper()
    if not raw:
        raise InvalidIdentifierError("Empty bond identifier.")

    if len(raw) == 12 and raw[:2].isalpha():
        isin = validate_isin(raw)
        route = "isin"
        try:
            cusip = isin_to_cusip(isin) if isin[:2] in ("US", "CA") else None
            if cusip is not None:
                cusip = normalise_cusip(cusip)
        except InvalidIdentifierError:
            cusip = None
    elif len(raw) in (8, 9):
        cusip = normalise_cusip(raw)
        isin = cusip_to_isin(cusip, country)
        route = "cusip"
    else:
        raise InvalidIdentifierError(
            f"{token!r} is neither a 12-character ISIN nor an 8/9-character CUSIP. "
            "On-the-run aliases such as 'CT10' must be resolved against the UST "
            "reference table before they reach the Velocity bond source."
        )

    uni = _universe(universe)
    descriptor = uni.lookup(isin)
    if descriptor is None:
        if require_quoted:
            hint = ""
            if route == "cusip":
                hint = (
                    " The arithmetic is not in question - it reproduces all 2,162 ISINs "
                    "Citi serves - so this is a coverage gap: Citi carries a liquid subset "
                    "(349 US Treasuries), not every issue. Off-the-runs, bills, TIPS and "
                    "just-auctioned bonds are the usual misses."
                )
            raise BondNotQuotedError(
                f"{token!r} resolves to {isin} via {route}, but Citi does not quote it.{hint}"
            )
        return BondResolution(
            token=str(token), isin=isin, cusip=cusip, route=route,
            descriptor=None, available_values=(),
        )

    values = tuple(uni.available_values(isin))
    return BondResolution(
        token=str(token),
        isin=isin,
        cusip=cusip,
        route=route,
        descriptor=descriptor,
        available_values=values,
    )


def resolve_bonds(
    tokens: Sequence[str],
    *,
    universe: Optional[BondUniverse] = None,
    country: str = "US",
    strict: bool = True,
) -> Tuple[dict, dict]:
    """:func:`resolve_bond` over many tokens, one universe load.

    Parameters
    ----------
    strict
        ``True`` re-raises the first failure. ``False`` collects them, which is
        what a warm wants: one un-quoted bond in a 300-name list should not lose
        the other 299.

    Returns
    -------
    (resolved, failures)
        ``resolved`` maps token -> :class:`BondResolution` in input order;
        ``failures`` maps token -> the exception message.
    """
    uni = _universe(universe)
    resolved: dict = {}
    failures: dict = {}
    for token in tokens:
        try:
            resolved[token] = resolve_bond(token, universe=uni, country=country)
        except (InvalidIdentifierError, BondNotQuotedError) as exc:
            if strict:
                raise
            failures[token] = f"{type(exc).__name__}: {exc}"
    return resolved, failures
