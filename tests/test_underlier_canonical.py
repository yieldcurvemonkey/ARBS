"""Tests for SDRUtils.core.underlier_canonical.canonical_underlier_key.

The SDR tape ships the same economic underlier under several display
strings depending on which submitter wrote the row. The canonical key
collapses every observed variation that is the same swap-economically
into a single stable token. Tests below pin the canonical output for
every variation pair the trader called out plus regression cases for
case / whitespace / hyphen / parenthetical noise.
"""
from __future__ import annotations

from typing import Iterable

import pytest

from SDRUtils.core.underlier_canonical import canonical_underlier_key


# ---------------------------------------------------------------------------
# SOFR family — daily-compounded OIS
# ---------------------------------------------------------------------------


SOFR_OIS_VARIANTS: list[str] = [
    "USD-SOFR-COMPOUND",
    "USD-SOFR-OIS",
    "USD-SOFR-OIS Compound",
    "USD-SOFR-COMPOUND 1D Constant",
    "USD-SOFR-OIS Compound 1D Constant",
    "USD-SOFR Compound",
    "usd-sofr-compound",
    "  USD-SOFR-COMPOUND  ",
    "USD-SOFR-OIS-COMPOUND",
    "USD-SOFR",
    "USD SOFR",
    "USD-SOFR ",
]


def test_sofr_variants_collapse_to_single_key() -> None:
    keys = {canonical_underlier_key(v) for v in SOFR_OIS_VARIANTS}
    assert keys == {"USD/SOFR-OIS/COMPOUND"}, (
        f"Expected every SOFR-OIS variation to collapse to one canonical "
        f"key, got {sorted(keys)} for inputs {SOFR_OIS_VARIANTS}"
    )


def test_sofr_term_is_distinct_from_oss_compound() -> None:
    # CME Term SOFR is a forward-looking term rate, NOT the daily
    # compounded OIS. The canonical key must keep them distinct so
    # rarity / extremes queries don't average them.
    assert canonical_underlier_key("USD-SOFR CME Term") == "USD/SOFR-TERM"
    assert canonical_underlier_key("USD-SOFR-CME-Term") == "USD/SOFR-TERM"
    assert canonical_underlier_key("USD-SOFR-CME-TERM") == "USD/SOFR-TERM"
    assert canonical_underlier_key("USD-SOFR Term") == "USD/SOFR-TERM"
    assert canonical_underlier_key("USD-SOFR-OIS Compound") != canonical_underlier_key(
        "USD-SOFR CME Term"
    )


# ---------------------------------------------------------------------------
# Federal Funds family
# ---------------------------------------------------------------------------


FED_FUNDS_VARIANTS: list[str] = [
    "USD-Federal Funds-H.15-OIS-COMPOUND",
    "USD-Federal Funds-H.15",
    "USD-Federal Funds",
    "USD-FEDERAL FUNDS-H.15-OIS-COMPOUND",
    "USD-Federal Funds H.15 Compound",
    "USD-Federal Funds-OIS-COMPOUND",
    "USD-FED-FUNDS-OIS",
    "usd-federal funds-h.15-ois-compound",
]


def test_fed_funds_variants_collapse_to_single_key() -> None:
    keys = {canonical_underlier_key(v) for v in FED_FUNDS_VARIANTS}
    assert keys == {"USD/FED-FUNDS-OIS/COMPOUND"}, (
        f"Expected every Fed Funds variation to collapse to one canonical "
        f"key, got {sorted(keys)} for inputs {FED_FUNDS_VARIANTS}"
    )


# ---------------------------------------------------------------------------
# OBFR — Overnight Bank Funding Rate (NY Fed)
# ---------------------------------------------------------------------------


def test_obfr_variants_collapse() -> None:
    variants = [
        "USD-Overnight Bank Funding-OIS-COMPOUND",
        "USD-OBFR-OIS-COMPOUND",
        "USD-OBFR",
        "usd-overnight bank funding rate",
        "USD-OBFR-OIS Compound",
    ]
    keys = {canonical_underlier_key(v) for v in variants}
    assert keys == {"USD/OBFR-OIS/COMPOUND"}, (
        f"Expected every OBFR variation to collapse to one canonical "
        f"key, got {sorted(keys)} for inputs {variants}"
    )


# ---------------------------------------------------------------------------
# Legacy BSBY
# ---------------------------------------------------------------------------


def test_bsby_legacy_canonical() -> None:
    variants = [
        "USD-BSBY",
        "USD-BSBY 1M",
        "USD-BSBY-1M",
        "usd-bsby",
        "USD BSBY",
    ]
    # BSBY tenor is captured separately on the leg (upi_reset_freq);
    # the canonical key only carries the underlier identity.
    keys = {canonical_underlier_key(v) for v in variants}
    assert keys == {"USD/BSBY/IBOR"}, (
        f"Expected every BSBY variation to collapse, got {sorted(keys)} "
        f"for inputs {variants}"
    )


# ---------------------------------------------------------------------------
# Legacy LIBOR — collapses across BBA / ICE Benchmark Administration / tenor
# ---------------------------------------------------------------------------


def test_libor_legacy_canonical() -> None:
    variants = [
        "USD-LIBOR-BBA",
        "USD-LIBOR-ICE",
        "USD-LIBOR",
        "USD-LIBOR 3M",
        "usd-libor-bba 6m",
        "USD-LIBOR-BBA-3M",
    ]
    keys = {canonical_underlier_key(v) for v in variants}
    assert keys == {"USD/LIBOR/IBOR"}, (
        f"Expected every LIBOR variation to collapse, got {sorted(keys)} "
        f"for inputs {variants}"
    )


# ---------------------------------------------------------------------------
# CMS / ISDA-Swap Rate
# ---------------------------------------------------------------------------


def test_isda_swap_rate_canonical() -> None:
    variants = [
        "USD-ISDA-Swap Rate",
        "USD-CMS",
        "USD-CMS-10Y",
        "USD-ISDA Swap Rate",
        "usd-isda-swap rate",
    ]
    keys = {canonical_underlier_key(v) for v in variants}
    assert keys == {"USD/ISDA-CMS"}, (
        f"Expected ISDA / CMS variants to collapse, got {sorted(keys)} "
        f"for inputs {variants}"
    )


# ---------------------------------------------------------------------------
# SIFMA — municipal swap index
# ---------------------------------------------------------------------------


def test_sifma_canonical() -> None:
    variants = [
        "USD-SIFMA-Municipal Swap Index",
        "USD-SIFMA",
        "USD-BMA",
    ]
    keys = {canonical_underlier_key(v) for v in variants}
    assert keys == {"USD/SIFMA-MUNI"}, (
        f"Expected SIFMA variants to collapse, got {sorted(keys)} "
        f"for inputs {variants}"
    )


# ---------------------------------------------------------------------------
# Basis swaps — float vs float
# ---------------------------------------------------------------------------


def test_basis_swap_canonical_sorts_legs() -> None:
    # Basis swaps have two legs. Canonical form sorts the leg keys
    # alphabetically so SOFR-vs-FF and FF-vs-SOFR collapse to the same
    # key — the order of legs in the SDR feed isn't economically
    # meaningful, only the pair is.
    a = canonical_underlier_key("USD-Federal Funds-H.15 vs USD-SOFR")
    b = canonical_underlier_key("USD-SOFR vs USD-Federal Funds-H.15")
    assert a == b, f"Basis legs should be order-invariant: {a} vs {b}"
    assert a == "USD/BASIS/FED-FUNDS-OIS+SOFR-OIS"


def test_basis_obfr_vs_sofr_canonical() -> None:
    a = canonical_underlier_key("USD-OBFR-OIS-COMPOUND vs USD-SOFR-OIS-COMPOUND")
    b = canonical_underlier_key("USD-SOFR-OIS-COMPOUND vs USD-OBFR-OIS-COMPOUND")
    assert a == b
    assert a == "USD/BASIS/OBFR-OIS+SOFR-OIS"


# ---------------------------------------------------------------------------
# Edge cases — null, empty, garbage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "nan",
        "None",
        "NULL",
    ],
)
def test_empty_or_null_returns_unknown(raw: object) -> None:
    assert canonical_underlier_key(raw) == "UNKNOWN"  # type: ignore[arg-type]


def test_unrecognized_passes_through_with_namespace() -> None:
    # An underlier the resolver doesn't classify still gets a canonical
    # key (uppercase, slash-prefixed) so DB rows always have a non-null
    # value. This keeps GROUP BY canonical_underlier_key well-defined
    # for novel rate indices the SDR feed introduces.
    out = canonical_underlier_key("USD-Some-Future-Index")
    assert out == "USD/SOME-FUTURE-INDEX"


def test_idempotent() -> None:
    # Feeding a canonical key back into the resolver should be a no-op.
    cases: Iterable[str] = [
        "USD/SOFR-OIS/COMPOUND",
        "USD/FED-FUNDS-OIS/COMPOUND",
        "USD/LIBOR/IBOR",
        "USD/BASIS/FED-FUNDS-OIS+SOFR-OIS",
    ]
    for c in cases:
        assert canonical_underlier_key(c) == c, (
            f"canonical_underlier_key should be idempotent — {c!r} got "
            f"{canonical_underlier_key(c)!r}"
        )


def test_focused_pair_from_spec() -> None:
    # The two example strings the trader called out in the QA spec.
    a = canonical_underlier_key("USD-SOFR-COMPOUND 1D Constant")
    b = canonical_underlier_key("USD-SOFR-OIS Compound 1D Constant")
    assert a == b == "USD/SOFR-OIS/COMPOUND"
