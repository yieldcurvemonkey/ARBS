r"""Security identifier arithmetic: CUSIP, ISIN, and the bridge between them.

Citi Velocity's only bond identifier is the ISIN. Everything else in this repo
keys UST bonds by CUSIP: the reference table from ``fiscaldata`` has a ``cusip``
column and no ``isin`` column, ``FixedRateBondQuery`` takes ``cusip=``, and the
CT/O/OO/OOO on-the-run aliases resolve to a CUSIP. So reaching a Velocity bond
from a repo query means crossing that gap, and for a US security the crossing is
mechanical: ``US`` + the 9-character CUSIP + an ISO 6166 check digit.

Why this module exists rather than a one-line helper
----------------------------------------------------
The arithmetic was already in the tree, at
``MDP.FixedRateBonds.WSJ.WSJFetcher.get_isin_from_cusip``, and it is **correct** -
measured here, it reproduces **2,162 / 2,162** of the ISINs Citi actually serves
across all 29 country/currency/asset-type universes. It is kept as the shared
core rather than reimplemented.

What it does not do is *refuse* bad input, and every one of those silent
successes resolves to the wrong bond rather than raising:

===============================  ==========================  =====================
input                            existing behaviour           why it matters
===============================  ==========================  =====================
``"03783310"`` (8-char CUSIP)    ``"US037833108"`` (11 chars)  Not an ISIN at all.
                                                              The 8-char base has
                                                              no CUSIP check digit,
                                                              so the ISIN digit is
                                                              computed over the
                                                              wrong body.
``country_code="us"``            ``"us0378331005"``            Lower case never
                                                              matches the catalog,
                                                              which is upper case.
``"00790C*10"`` (``*`` = 36)     ``ValueError`` from ``int``   Right outcome, wrong
                                                              reason - the message
                                                              names ``'-'``.
``""``                           ``"US8"``                     A three-character
                                                              "ISIN".
===============================  ==========================  =====================

A check digit that is arithmetically right can still name a bond nobody quotes,
and a CUSIP with one mistyped character usually has a *valid* check digit for
some other security. So the functions here validate first and raise on anything
they cannot resolve unambiguously.

Establishing the identity is only half of it; confirming Citi quotes that exact
bond is the other half, and that needs the catalog rather than arithmetic - see
``MDP.CitiVelocityExcel.bonds.resolution``.

Verification
------------
Both algorithms are checked against published control identifiers, against a
deliberately corrupted identifier (the checker must be *able* to fail), and
against the 2,162 real Citi-served ISINs - see ``tests/test_identifiers.py``.
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "CUSIP_ALPHABET",
    "InvalidIdentifierError",
    "cusip_check_digit",
    "cusip_to_isin",
    "is_valid_cusip",
    "is_valid_isin",
    "isin_check_digit",
    "isin_to_cusip",
    "normalise_cusip",
    "validate_isin",
]


class InvalidIdentifierError(ValueError):
    """A CUSIP or ISIN that cannot be resolved to exactly one security."""


#: The CUSIP character set. Digits are their own value, letters run ``A``=10 to
#: ``Z``=35, and the three legacy symbols carry the values ISO 6166 assigns them
#: (they appear in pre-1980 issues and in some private placements).
CUSIP_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*@#"

_CUSIP_VALUE = {ch: i for i, ch in enumerate(CUSIP_ALPHABET)}


def _char_value(ch: str) -> int:
    try:
        return _CUSIP_VALUE[ch]
    except KeyError:
        raise InvalidIdentifierError(
            f"{ch!r} is not a CUSIP character. Accepted: 0-9, A-Z, and * @ #."
        ) from None


def _luhn_sum(values: list[int], *, double_from_right_odd: bool) -> int:
    """Modulus-10 double-add-double over already-expanded single digits.

    ``double_from_right_odd`` selects the ISIN convention (double positions
    1, 3, 5 ... counting from the RIGHT). CUSIP doubles every second character
    counting from the LEFT, which is handled by its own caller.
    """
    total = 0
    for i, d in enumerate(reversed(values) if double_from_right_odd else values):
        if (i % 2 == 0) if double_from_right_odd else (i % 2 == 1):
            d *= 2
        total += d // 10 + d % 10
    return total


def cusip_check_digit(base: str) -> str:
    """The 9th character of a CUSIP, from its 8-character base.

    Doubles every second character counting from the left (0-indexed: positions
    1, 3, 5, 7), sums the digits of each product, and takes the 10's complement.

    Raises
    ------
    InvalidIdentifierError
        When ``base`` is not exactly 8 characters, or holds a character outside
        :data:`CUSIP_ALPHABET`.
    """
    base = str(base).strip().upper()
    if len(base) != 8:
        raise InvalidIdentifierError(
            f"A CUSIP base is 8 characters; got {len(base)} ({base!r}). "
            "Pass the first 8 characters of a 9-character CUSIP, not the whole thing."
        )
    values = [_char_value(ch) for ch in base]
    total = _luhn_sum(values, double_from_right_odd=False)
    return str((10 - total % 10) % 10)


def isin_check_digit(body: str) -> str:
    """The 12th character of an ISIN, from its 11-character body.

    ``body`` is the 2-letter country prefix followed by the 9-character NSIN.
    Letters expand to two digits (``A``=10 ... ``Z``=35) *before* the Luhn pass,
    which is why the expanded string is not 11 digits long.

    Raises
    ------
    InvalidIdentifierError
        When ``body`` is not exactly 11 characters, or holds a character outside
        the alphanumeric range.
    """
    body = str(body).strip().upper()
    if len(body) != 11:
        raise InvalidIdentifierError(
            f"An ISIN body is 11 characters (2-letter country + 9-character NSIN); "
            f"got {len(body)} ({body!r})."
        )
    digits: list[int] = []
    for ch in body:
        if ch.isdigit():
            digits.append(int(ch))
        elif "A" <= ch <= "Z":
            v = ord(ch) - ord("A") + 10
            digits.append(v // 10)
            digits.append(v % 10)
        else:
            raise InvalidIdentifierError(
                f"{ch!r} is not valid in an ISIN body; expected 0-9 or A-Z."
            )
    total = _luhn_sum(digits, double_from_right_odd=True)
    return str((10 - total % 10) % 10)


def is_valid_isin(isin: str) -> bool:
    """``True`` when ``isin`` is 12 characters with a country prefix and a good check digit."""
    try:
        validate_isin(isin)
    except InvalidIdentifierError:
        return False
    return True


def validate_isin(isin: str) -> str:
    """Return the upper-cased ISIN, or raise explaining which rule it broke.

    Raises
    ------
    InvalidIdentifierError
        Wrong length, a non-alphabetic country prefix, or a check digit that does
        not match the body. The check-digit message reports both digits, because
        a one-character typo in the NSIN is the usual cause and it otherwise
        looks like a lookup miss further downstream.
    """
    text = str(isin).strip().upper()
    if len(text) != 12:
        raise InvalidIdentifierError(f"An ISIN is 12 characters; got {len(text)} ({text!r}).")
    if not text[:2].isalpha():
        raise InvalidIdentifierError(
            f"An ISIN starts with a 2-letter country code; got {text[:2]!r} in {text!r}."
        )
    want = isin_check_digit(text[:11])
    if text[11] != want:
        raise InvalidIdentifierError(
            f"{text!r} has check digit {text[11]!r} but its body implies {want!r}. "
            "One mistyped character in the NSIN usually still yields a valid-looking "
            "identifier for a different security, so this is rejected rather than repaired."
        )
    return text


def is_valid_cusip(cusip: str) -> bool:
    """``True`` when ``cusip`` is 9 characters with a matching check digit."""
    text = str(cusip).strip().upper()
    if len(text) != 9:
        return False
    try:
        return cusip_check_digit(text[:8]) == text[8]
    except InvalidIdentifierError:
        return False


def normalise_cusip(cusip: str, *, verify_check_digit: bool = True) -> str:
    """Upper-cased 9-character CUSIP, appending the check digit to an 8-character base.

    Parameters
    ----------
    cusip
        8 or 9 characters. An 8-character base gets its check digit computed;
        a 9-character CUSIP has its existing one verified.
    verify_check_digit
        Set ``False`` to accept a 9-character CUSIP whose check digit is wrong.
        Off by default: a bad check digit means the identifier is not the one the
        caller thinks it is, and silently continuing resolves to another bond.

    Raises
    ------
    InvalidIdentifierError
        On any length other than 8 or 9, an out-of-alphabet character, or (unless
        ``verify_check_digit=False``) a check digit that does not match.
    """
    text = str(cusip).strip().upper()
    if len(text) == 8:
        return text + cusip_check_digit(text)
    if len(text) != 9:
        raise InvalidIdentifierError(
            f"A CUSIP is 8 characters (base) or 9 (with check digit); got {len(text)} ({text!r})."
        )
    want = cusip_check_digit(text[:8])
    if verify_check_digit and text[8] != want:
        raise InvalidIdentifierError(
            f"{text!r} has check digit {text[8]!r} but its base implies {want!r}."
        )
    return text


def cusip_to_isin(cusip: str, country: str = "US") -> str:
    """``US`` + CUSIP + ISO 6166 check digit.

    Accepts an 8-character base (the check digit is computed) or a full
    9-character CUSIP (its check digit is verified). Both guards matter: an
    8-character base fed to naive concatenation produces an 11-character string
    that is not an ISIN, and a CUSIP with a bad check digit produces a
    well-formed ISIN for the wrong security.

    Parameters
    ----------
    cusip
        8 or 9 characters.
    country
        ISO 3166 alpha-2. Defaults to ``US``; ``CA`` is the other common one, as
        Canadian securities also carry CUSIPs.

    Returns
    -------
    str
        A 12-character ISIN.

    Raises
    ------
    InvalidIdentifierError
        On a malformed CUSIP or a country code that is not two letters.

    Examples
    --------
    >>> cusip_to_isin("037833100")
    'US0378331005'
    >>> cusip_to_isin("03783310")          # 8-char base, check digit computed
    'US0378331005'
    """
    ctry = str(country).strip().upper()
    if len(ctry) != 2 or not ctry.isalpha():
        raise InvalidIdentifierError(
            f"A country code is 2 letters; got {country!r}."
        )
    nsin = normalise_cusip(cusip)
    bad = sorted({ch for ch in nsin if not ch.isalnum()})
    if bad:
        raise InvalidIdentifierError(
            f"{nsin!r} contains {', '.join(repr(c) for c in bad)}, which is valid in a "
            "CUSIP but not in an ISIN: ISO 6166 NSINs are alphanumeric only, so "
            "'*', '@' and '#' have no ISIN representation. This security cannot be "
            "reached by identifier arithmetic; look it up in the Velocity universe "
            "by description instead."
        )
    body = ctry + nsin
    return body + isin_check_digit(body)


def isin_to_cusip(isin: str, *, expect_country: Optional[str] = None) -> str:
    """The 9-character NSIN of an ISIN, validated as a CUSIP.

    Only meaningful where the NSIN *is* a CUSIP - US and CA. For any other
    country the NSIN is a national number in some other scheme, so pass
    ``expect_country`` to make the assumption explicit and fail loudly when it
    does not hold.

    Raises
    ------
    InvalidIdentifierError
        When the ISIN is malformed, its check digit is wrong, or its country
        prefix is not ``expect_country``.
    """
    text = validate_isin(isin)
    if expect_country is not None:
        want = str(expect_country).strip().upper()
        if text[:2] != want:
            raise InvalidIdentifierError(
                f"{text!r} is a {text[:2]} security; expected {want}. "
                "Outside US/CA the NSIN is not a CUSIP."
            )
    return text[2:11]
