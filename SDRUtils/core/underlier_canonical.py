"""Canonical underlier-name resolver for the USD swap tape.

Different SDR submitters render the same economic underlier as
different display strings ("USD-SOFR-COMPOUND 1D Constant" vs
"USD-SOFR-OIS Compound 1D Constant" vs "USD-SOFR" — all the same
daily-compounded SOFR OIS). The dashboard's rarity / extremes /
package-analytics queries previously did `GROUP BY upi_underlier_name`,
which split a single economic distribution across three buckets.

The function below collapses every observed variation that is the same
swap-economically into a single canonical token. Persisted on
``arbs_usd_swap_tape_legs_v2`` as ``canonical_underlier_key`` and read
by the dashboard's ``groupBy=canonical`` query option.

The canonical form is a slash-separated, all-uppercase string with a
stable token order. Single-leg products use
``USD/<index-family>/<calc-method>``; basis products use
``USD/BASIS/<legA>+<legB>`` with leg keys sorted alphabetically so the
two SDR-feed orderings of the same pair collapse together.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Tokens — every recognized canonical key the resolver can emit
# ---------------------------------------------------------------------------

UNKNOWN = "UNKNOWN"
SOFR_OIS = "USD/SOFR-OIS/COMPOUND"
SOFR_TERM = "USD/SOFR-TERM"
FED_FUNDS_OIS = "USD/FED-FUNDS-OIS/COMPOUND"
OBFR_OIS = "USD/OBFR-OIS/COMPOUND"
BSBY = "USD/BSBY/IBOR"
LIBOR = "USD/LIBOR/IBOR"
ISDA_CMS = "USD/ISDA-CMS"
SIFMA = "USD/SIFMA-MUNI"


# ---------------------------------------------------------------------------
# Pattern matchers — order matters: more specific patterns first.
# ---------------------------------------------------------------------------

# CME Term SOFR is a forward-looking term rate, NOT the daily-compounded
# OIS. We MUST detect this before the generic SOFR pattern, otherwise
# every USD-SOFR row would absorb the term-SOFR rows into the OIS
# bucket and silently average two distinct distributions.
_TERM_SOFR_RE = re.compile(
    r"USD[-\s]+SOFR[-\s]+(CME[-\s]+)?TERM",
    re.IGNORECASE,
)

# Generic SOFR catches USD-SOFR, USD-SOFR-COMPOUND, USD-SOFR-OIS,
# USD-SOFR-OIS Compound, USD-SOFR Compound — all daily-compounded.
_SOFR_OIS_RE = re.compile(r"USD[-\s]+SOFR\b", re.IGNORECASE)

# Federal Funds: with or without H.15 / OIS / COMPOUND modifiers, with
# Federal Funds spelled out or hyphenated. The SDR feed uses both
# "USD-Federal Funds-H.15-OIS-COMPOUND" and the older "USD-FED-FUNDS-OIS".
_FED_FUNDS_RE = re.compile(
    r"USD[-\s]+(?:Federal[-\s]+Funds|FED[-\s]+FUNDS|FF)\b",
    re.IGNORECASE,
)

# OBFR — Overnight Bank Funding Rate (NY Fed). Both the explicit
# "USD-Overnight Bank Funding" full string and the "USD-OBFR" abbrev.
_OBFR_RE = re.compile(
    r"USD[-\s]+(?:Overnight[-\s]+Bank[-\s]+Funding|OBFR)\b",
    re.IGNORECASE,
)

_BSBY_RE = re.compile(r"USD[-\s]+BSBY\b", re.IGNORECASE)
_LIBOR_RE = re.compile(r"USD[-\s]+LIBOR\b", re.IGNORECASE)
_ISDA_CMS_RE = re.compile(r"USD[-\s]+(?:ISDA[-\s]+Swap[-\s]+Rate|CMS)\b", re.IGNORECASE)
_SIFMA_RE = re.compile(r"USD[-\s]+(?:SIFMA|BMA)\b", re.IGNORECASE)

# Basis separator — the SDR feed renders float-vs-float legs as
# "<leg1> vs <leg2>". Canonical form sorts legs and joins with '+'.
_BASIS_SPLIT_RE = re.compile(r"\s+vs\s+", re.IGNORECASE)

# Already-canonical detector. If a caller hands us a value that's
# already a canonical key (e.g. round-tripped from the DB), short-circuit
# rather than re-walk the pattern table.
_CANONICAL_RE = re.compile(
    r"^USD/(?:[A-Z][A-Z0-9+\-/]*)$",
)


def _is_nullish(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in {"", "nan", "none", "null"}:
            return True
    return False


def _resolve_single_leg(token: str) -> str:
    """Resolve a single-leg underlier (no `vs`)."""
    # Term SOFR before generic SOFR — order matters.
    if _TERM_SOFR_RE.search(token):
        return SOFR_TERM
    if _SOFR_OIS_RE.search(token):
        return SOFR_OIS
    if _FED_FUNDS_RE.search(token):
        return FED_FUNDS_OIS
    if _OBFR_RE.search(token):
        return OBFR_OIS
    if _BSBY_RE.search(token):
        return BSBY
    if _LIBOR_RE.search(token):
        return LIBOR
    if _ISDA_CMS_RE.search(token):
        return ISDA_CMS
    if _SIFMA_RE.search(token):
        return SIFMA

    # Unrecognised — slug-ify. Strip everything past the underlier root
    # (tenor / reset modifiers like "1M", "3M", "Compound", "Constant"
    # belong on the leg's other columns, not the underlier key itself).
    # Conservative slug: uppercase, replace whitespace with hyphens,
    # collapse multi-hyphens, drop trailing hyphens.
    slug = re.sub(r"\s+", "-", token.strip()).upper()
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    # If the slug already starts with USD-, drop the "USD-" prefix and
    # re-add as "USD/" so the namespace shape stays consistent.
    if slug.upper().startswith("USD-"):
        return f"USD/{slug[4:]}"
    return f"USD/{slug}"


def _basis_leg_key(token: str) -> str:
    """Reduce a basis leg to the index-family suffix only.

    For ``USD/SOFR-OIS/COMPOUND`` the basis representation is just
    ``SOFR-OIS`` — the calc method is implicit when the canonical full
    key is ``USD/SOFR-OIS/COMPOUND``. This keeps basis canonical keys
    short while still uniquely identifying the leg.
    """
    canon = _resolve_single_leg(token)
    # Strip "USD/" prefix
    if canon.startswith("USD/"):
        canon = canon[4:]
    # For OIS-compound legs, drop the trailing "/COMPOUND" so the basis
    # representation is "SOFR-OIS" not "SOFR-OIS/COMPOUND". Term /
    # IBOR / CMS / MUNI legs keep their full suffix.
    if canon.endswith("/COMPOUND"):
        canon = canon[: -len("/COMPOUND")]
    return canon


def canonical_underlier_key(upi_underlier_name: Optional[str]) -> str:
    """Collapse an SDR ``upi_underlier_name`` into a canonical key.

    The canonical form is a stable, all-uppercase, slash-separated
    string designed to be safe to GROUP BY in SQL and to be appended to
    URL query parameters without escaping headaches.

    Returns ``"UNKNOWN"`` when the input is null, empty, or one of the
    common SDR null-string sentinels (``"nan"``, ``"None"``, ``"NULL"``).
    Unrecognised but non-null inputs are slug-ified and returned under
    the ``USD/`` namespace so DB rows always have a non-null value.
    """
    if _is_nullish(upi_underlier_name):
        return UNKNOWN
    text = str(upi_underlier_name).strip()
    if not text:
        return UNKNOWN

    # Already canonical? Return as-is.
    if _CANONICAL_RE.match(text):
        return text

    # Basis swaps: "<leg1> vs <leg2>" — canonical form sorts legs.
    parts = _BASIS_SPLIT_RE.split(text)
    if len(parts) == 2:
        left = _basis_leg_key(parts[0].strip())
        right = _basis_leg_key(parts[1].strip())
        legs = sorted([left, right])
        return f"USD/BASIS/{legs[0]}+{legs[1]}"

    return _resolve_single_leg(text)


__all__ = [
    "canonical_underlier_key",
    "UNKNOWN",
    "SOFR_OIS",
    "SOFR_TERM",
    "FED_FUNDS_OIS",
    "OBFR_OIS",
    "BSBY",
    "LIBOR",
    "ISDA_CMS",
    "SIFMA",
]
