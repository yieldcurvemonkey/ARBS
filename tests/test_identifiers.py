r"""CUSIP/ISIN arithmetic, checked against identifiers nobody in this repo invented.

Three layers, deliberately:

1. **Published controls** - ISINs whose check digit is documented outside this
   repo, so the algorithm is pinned to the standard rather than to itself.
2. **Negative controls** - a corrupted identifier must be *rejected*. A checker
   that cannot fail reports success and hides the thing it was built to find,
   which is the failure mode this repo has been bitten by before.
3. **The real corpus** - all 2,162 ISINs Citi actually serves, from the committed
   ``bond_isins.json`` harvest. This is the test that would catch a subtly wrong
   doubling rule: the published controls are few enough that an off-by-one in
   the Luhn pass can pass them by luck, but not 2,162 of them.

The guard tests are written so that *removing the guard* makes them fail - each
one names the wrong value the unguarded code produced.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from utils.identifiers import (
    InvalidIdentifierError,
    cusip_check_digit,
    cusip_to_isin,
    is_valid_cusip,
    is_valid_isin,
    isin_check_digit,
    isin_to_cusip,
    normalise_cusip,
    validate_isin,
)

_CATALOG = (
    pathlib.Path(__file__).resolve().parents[1]
    / "MDP" / "CitiVelocityExcel" / "catalog" / "bond_isins.json"
)

# ISINs with a published check digit, from outside this repository.
PUBLISHED_ISINS = [
    "US0378331005",   # Apple
    "US5949181045",   # Microsoft
    "GB0002634946",   # BAE Systems
    "AU0000XVGZA3",   # Treasury Corp Victoria
    "US38259P5089",   # Google
    "CA0679011084",   # Barrick Gold
]

# CUSIPs with a published check digit.
PUBLISHED_CUSIPS = [
    ("037833100", "Apple"),
    ("594918104", "Microsoft"),
    ("38259P508", "Google"),
    ("912810EZ7", "T 6.625 02/15/2027"),
]


def _corpus():
    data = json.loads(_CATALOG.read_text())
    out = []
    for key, rows in data.items():
        for r in rows:
            isin = str(r["isin"])
            if len(isin) == 12 and isin[:2].isalpha():
                out.append((key, isin))
    return out


CORPUS = _corpus()


# ── layer 1: published controls ──────────────────────────────────────────

@pytest.mark.parametrize("isin", PUBLISHED_ISINS)
def test_isin_check_digit_matches_published(isin):
    assert isin_check_digit(isin[:11]) == isin[11]
    assert is_valid_isin(isin)


@pytest.mark.parametrize("cusip,name", PUBLISHED_CUSIPS)
def test_cusip_check_digit_matches_published(cusip, name):
    assert cusip_check_digit(cusip[:8]) == cusip[8], name
    assert is_valid_cusip(cusip), name


# ── layer 2: negative controls — the checker must be able to fail ────────

@pytest.mark.parametrize("isin", PUBLISHED_ISINS)
def test_corrupted_check_digit_is_rejected(isin):
    """Bump the check digit by one. Every one of these must be refused."""
    wrong = isin[:11] + str((int(isin[11]) + 1) % 10)
    assert not is_valid_isin(wrong)
    with pytest.raises(InvalidIdentifierError, match="check digit"):
        validate_isin(wrong)


@pytest.mark.parametrize("isin", PUBLISHED_ISINS)
def test_single_character_body_typo_is_rejected(isin):
    """A one-character NSIN typo must not silently keep a valid check digit.

    This is the case that resolves to a *different real bond* rather than to
    nothing, so it is the one worth pinning.
    """
    body = list(isin[:11])
    pos = 5
    body[pos] = "0" if body[pos] != "0" else "1"
    typo = "".join(body) + isin[11]
    assert not is_valid_isin(typo), f"{typo} should not validate"


def test_transposition_is_caught():
    """Luhn catches adjacent transpositions; if it did not, the doubling is wrong."""
    isin = "US0378331005"
    swapped = isin[:4] + isin[5] + isin[4] + isin[6:]
    assert swapped != isin
    assert not is_valid_isin(swapped)


# ── layer 3: the real corpus ─────────────────────────────────────────────

def test_corpus_is_present_and_large():
    """Guards the guard: if the catalog moved, the corpus tests would vacuously pass."""
    assert len(CORPUS) == 2162, f"expected the 2,162-ISIN harvest, got {len(CORPUS)}"


def test_every_citi_isin_validates():
    bad = [(k, i) for k, i in CORPUS if not is_valid_isin(i)]
    assert not bad, f"{len(bad)} of {len(CORPUS)} Citi ISINs failed: {bad[:5]}"


def test_us_cusip_to_isin_round_trips_on_every_us_bond():
    us = [i for k, i in CORPUS if i.startswith("US")]
    assert len(us) > 300, f"only {len(us)} US ISINs — corpus changed?"
    bad = []
    for isin in us:
        cusip = isin_to_cusip(isin, expect_country="US")
        if cusip_to_isin(cusip) != isin:
            bad.append((isin, cusip, cusip_to_isin(cusip)))
    assert not bad, f"{len(bad)} round trips failed: {bad[:5]}"


def test_us_cusip_check_digit_is_rederivable_from_the_base():
    """The 9th CUSIP character must fall out of the first 8 for every real bond."""
    us = [i for k, i in CORPUS if i.startswith("US")]
    bad = []
    for isin in us:
        cusip = isin_to_cusip(isin)
        if cusip_check_digit(cusip[:8]) != cusip[8]:
            bad.append((isin, cusip, cusip_check_digit(cusip[:8])))
    assert not bad, f"{len(bad)} CUSIP check digits failed: {bad[:5]}"


def test_agrees_with_the_existing_wsj_implementation_where_the_nsin_is_a_cusip():
    """The pre-existing helper is correct; this module must not change any answer.

    Scoped to US and CA, the two countries whose NSIN *is* a CUSIP. Pinning the
    agreement means a future edit here cannot silently diverge from the
    identifiers the rest of the repo already produces.
    """
    from MDP.FixedRateBonds.WSJ.WSJFetcher import get_isin_from_cusip

    n = 0
    for key, isin in CORPUS:
        if isin[:2] not in ("US", "CA"):
            continue
        cusip, ctry = isin[2:11], isin[:2]
        assert cusip_to_isin(cusip, ctry) == get_isin_from_cusip(cusip, ctry) == isin
        n += 1
    assert n > 300, f"only {n} US/CA ISINs compared — corpus changed?"


def test_deliberately_stricter_than_wsj_on_a_non_cusip_nsin():
    """A GB NSIN is not a CUSIP, so completing it as one is refused.

    ``get_isin_from_cusip`` happily round-trips these because it validates
    nothing; that is fine for its own call sites, which already hold a real ISIN.
    It is not fine as a general CUSIP bridge, because it would accept a
    9-character string from anywhere and hand back a well-formed ISIN.
    """
    from MDP.FixedRateBonds.WSJ.WSJFetcher import get_isin_from_cusip

    gb = next(i for k, i in CORPUS if i.startswith("GB") and not is_valid_cusip(i[2:11]))
    assert get_isin_from_cusip(gb[2:11], "GB") == gb          # unvalidated: accepts it
    with pytest.raises(InvalidIdentifierError, match="check digit"):
        cusip_to_isin(gb[2:11], "GB")                          # validated: refuses it


# ── the guards: each names the wrong value the unguarded code produced ───

def test_eight_char_cusip_is_completed_not_concatenated():
    """Naive concatenation gave 'US037833108' — 11 characters, not an ISIN."""
    assert cusip_to_isin("03783310") == "US0378331005"
    assert len(cusip_to_isin("03783310")) == 12


def test_lower_case_country_is_normalised_not_propagated():
    """Naive concatenation gave 'us0378331005', which never matches the catalog.

    Upper-casing removes the hazard outright, so the input is repaired rather
    than refused — unlike a bad check digit, there is no ambiguity about which
    security the caller meant.
    """
    assert cusip_to_isin("037833100", "us") == "US0378331005"
    assert cusip_to_isin("037833100", "Us") == "US0378331005"


@pytest.mark.parametrize("bad", ["U", "USA", "1S", ""])
def test_country_code_that_is_not_two_letters_is_rejected(bad):
    with pytest.raises(InvalidIdentifierError, match="2 letters"):
        cusip_to_isin("037833100", bad)


def test_empty_cusip_is_rejected():
    """Naive concatenation gave 'US8'."""
    with pytest.raises(InvalidIdentifierError):
        cusip_to_isin("")


@pytest.mark.parametrize("bad", ["1234567", "1234567890", "12345678901"])
def test_wrong_length_cusip_is_rejected(bad):
    with pytest.raises(InvalidIdentifierError, match="8 characters|9"):
        cusip_to_isin(bad)


def test_cusip_with_bad_check_digit_is_rejected():
    """A mistyped CUSIP otherwise yields a well-formed ISIN for another security."""
    good = "037833100"
    bad = good[:8] + str((int(good[8]) + 1) % 10)
    with pytest.raises(InvalidIdentifierError, match="check digit"):
        cusip_to_isin(bad)
    # ...but the caller can opt out knowingly
    assert normalise_cusip(bad, verify_check_digit=False) == bad


def test_legacy_cusip_symbols_are_accepted():
    """'*', '@' and '#' are real CUSIP characters; int() used to blow up on them.

    Fed the 8-character base so the check digit is computed rather than asserted
    against a value invented for the test.
    """
    for base in ("00790C*1", "00790C@1", "00790C#1"):
        full = normalise_cusip(base)
        assert len(full) == 9 and is_valid_cusip(full)


@pytest.mark.parametrize("base", ["00790C*1", "00790C@1", "00790C#1"])
def test_legacy_cusip_symbols_have_no_isin_and_say_so(base):
    """'*', '@' and '#' are legal in a CUSIP but not in an ISIN.

    ISO 6166 NSINs are alphanumeric, so these securities are unreachable by
    identifier arithmetic. Worth an explicit message: the natural failure is a
    confusing "ISIN body is 11 characters" from two frames deeper.
    """
    with pytest.raises(InvalidIdentifierError, match="valid in a CUSIP but not in an ISIN"):
        cusip_to_isin(base)


def test_non_cusip_character_is_rejected_with_a_useful_message():
    with pytest.raises(InvalidIdentifierError, match="not a CUSIP character"):
        cusip_check_digit("0378331-")


@pytest.mark.parametrize("bad", ["US037833100", "US03783310055", ""])
def test_wrong_length_isin_is_rejected(bad):
    with pytest.raises(InvalidIdentifierError, match="12 characters"):
        validate_isin(bad)


def test_numeric_country_prefix_is_rejected():
    with pytest.raises(InvalidIdentifierError, match="country code"):
        validate_isin("120378331005")


def test_isin_to_cusip_refuses_a_non_us_security_when_told_to_expect_one():
    """Outside US/CA the NSIN is not a CUSIP, so the assumption must be stated."""
    gb = next(i for k, i in CORPUS if i.startswith("GB"))
    with pytest.raises(InvalidIdentifierError, match="expected US"):
        isin_to_cusip(gb, expect_country="US")
    # without the assertion it still returns the raw NSIN
    assert len(isin_to_cusip(gb)) == 9


def test_whitespace_and_case_are_normalised():
    assert cusip_to_isin("  037833100  ") == "US0378331005"
    assert cusip_to_isin("037833100", "us ".strip().upper()) == "US0378331005"
    assert validate_isin(" us0378331005 ") == "US0378331005"
