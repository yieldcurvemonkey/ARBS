r"""Tests for the harvested Citi Velocity catalog and the tag builders on top of it.

These run against the COMMITTED artefacts in ``MDP/CitiVelocityExcel/catalog/`` -
real harvested data from the add-in's Function Builder, not fixtures. That is the
point: the catalog exists because guessing tag spellings provably does not work,
so the tests assert against what was actually observed.

The most valuable test in the module is
:func:`test_the_real_ois_index_tokens_are_present_and_the_guessed_ones_are_not`.
Generate-and-test over plausible spellings found 14 OIS currencies but got the two
biggest ones wrong (``EUR_ESTR`` for ``EUR_EUROSTR``, ``USD_FEDFUNDS`` for
``USD_FEDFUND``) and missed six curves outright. A builder that silently emits
wrong tags is worse than no builder.
"""

from __future__ import annotations

import warnings

import pytest

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.catalog import (
    DEPRECATED_VOL_BRANCHES,
    RFR_VOL_BRANCHES,
    CitiVeloCatalog,
    sort_tenors,
    tenor_years,
)
from MDP.CitiVelocityExcel.errors import CatalogError, FrequencyError, UnknownTagError
from MDP.CitiVelocityExcel.frequencies import normalise_frequency


@pytest.fixture(scope="module")
def cat() -> CitiVeloCatalog:
    return CitiVeloCatalog.default()


# ------------------------------------------------------------------ #
#                          the harvested tree                        #
# ------------------------------------------------------------------ #


def test_rates_has_the_thirty_three_harvested_families(cat: CitiVeloCatalog):
    families = cat.families()
    assert len(families) == 33
    for expected in (
        "OIS",
        "VOL",
        "BOND",
        "XCCY_OIS_SWAP",
        "INFLATION",
        "SWAP_LIBOR",
        "SPREAD_OPTIONS",
        "MIDCURVES",
        "TSY",
        "FUTURES",
        "BASIS_SWAPS",
    ):
        assert expected in families


def test_the_real_ois_index_tokens_are_present_and_the_guessed_ones_are_not(cat: CitiVeloCatalog):
    """The catalog exists because these two columns disagree.

    ==============================  ======================
    guessed                         actual
    ==============================  ======================
    ``EUR_ESTR`` / ``EUR_ESTER``    ``EUR_EUROSTR``
    ``USD_FEDFUNDS`` / ``USD_FF``   ``USD_FEDFUND``
    --                              ``JPY_TONAR_JSCC`` / ``JPY_TONAR_LCH``
    --                              ``DKK_TNDKK``, ``MXN_T_FONDEO``
    ==============================  ======================
    """
    options = set(cat.options("RATES.OIS"))
    for real in (
        "EUR_EUROSTR",
        "USD_FEDFUND",
        "USD_SOFR",
        "JPY_TONAR_JSCC",
        "JPY_TONAR_LCH",
        "DKK_TNDKK",
        "MXN_T_FONDEO",
        "ZAR_ZARONIA",
    ):
        assert real in options, f"{real} is a real Citi OIS index and must be in the catalog"
    for guessed in ("EUR_ESTR", "EUR_ESTER", "USD_FEDFUNDS", "USD_FF", "JPY_TONA", "GBP_SONIA_LCH"):
        assert guessed not in options, f"{guessed} was a guess, and it is wrong"

    with pytest.raises(UnknownTagError) as excinfo:
        T.ois_par("EUR_ESTR", "10Y")
    assert "EUR_EUROSTR" in str(excinfo.value), "the error should point at the right token"


def test_ois_sub_types_include_the_three_the_guesser_missed(cat: CitiVeloCatalog):
    """``ROLL_CARRY``, ``BFLY`` and ``CURVES`` sit beside PAR / FWD / SWAP_SPREAD."""
    assert set(cat.options("RATES.OIS.USD_SOFR")) == {
        "PAR",
        "FWD",
        "SWAP_SPREAD",
        "ROLL_CARRY",
        "BFLY",
        "CURVES",
    }


def test_par_axis_is_forty_four_tenors_in_maturity_order(cat: CitiVeloCatalog):
    tenors = cat.tenors("RATES.OIS.USD_SOFR.PAR")
    assert len(tenors) == 44
    assert tenors[0] == "1D" and tenors[-1] == "50Y"
    assert tenors == sort_tenors(tenors)
    assert tenor_years("18M") == pytest.approx(tenor_years("1Y") * 1.5, rel=0.02)


# ------------------------------------------------------------------ #
#                    per-branch shape, not per level                 #
# ------------------------------------------------------------------ #


def test_vol_depth_varies_between_conventions_of_one_measure(cat: CitiVeloCatalog):
    """``ATM.NORMAL`` carries a basis level; ``ATM.BLACK`` goes straight to expiry.

    Depth varies WITHIN a family and even between conventions of one measure, so a
    generator must read the shape per branch. This is the fact that makes a
    level-pooled generator produce tags on no real path.
    """
    assert cat.options("RATES.VOL.USD.ATM_RFR.NORMAL") == ["ANNUAL"]
    black_children = cat.options("RATES.VOL.USD.ATM_RFR.BLACK")
    assert "ANNUAL" not in black_children
    assert "10Y" in black_children  # straight to expiry

    assert T.vol_atm("USD", "1Y", "10Y") == "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y"
    assert (
        T.vol_atm("USD", "1Y", "10Y", measure="BLACK") == "RATES.VOL.USD.ATM_RFR.BLACK.1Y.10Y"
    )


def test_pooled_level_vocabulary_produces_tags_on_no_real_path(cat: CitiVeloCatalog):
    """MUTATION CHECK for the path-consistency rule.

    Pooling ``RATES.VOL``'s level-4 vocabulary gives
    ``[1M, 1Y, 3M, 6M, BLACK, FWDPREMIUM, NORMAL, NORMALABSOLUTE, NORMALSKEW,
    PREMIUM, RISK_REVERSAL]`` - expiries and vol conventions mixed together,
    because each measure has its own shape. Sampling one entry per level from that
    pool produced 2,163 VOL tags of which ZERO were valid.
    """
    pooled = cat.family_vocabulary("VOL", 4)
    assert {"NORMAL", "BLACK", "NORMALABSOLUTE", "RISK_REVERSAL"} <= set(pooled)
    assert {"1M", "3M", "6M", "1Y"} <= set(pooled), "expiries and measures are mixed in the pool"

    # A pooled generator would happily put a measure that only exists under ATM
    # underneath OTM_RFR. Path-consistent expansion does not.
    real = set(cat.expand("RATES.VOL.USD.OTM_RFR"))
    for impossible in (
        "RATES.VOL.USD.OTM_RFR.BLACK.ANNUAL.1Y.10Y",
        "RATES.VOL.USD.OTM_RFR.NORMAL.DAILY.1Y.10Y",
    ):
        assert impossible not in real


def test_expansion_contains_the_tags_that_were_verified_live(cat: CitiVeloCatalog):
    """Three tags confirmed against the live add-in on 2026-08-04."""
    assert "RATES.OIS.USD_SOFR.PAR.10Y" in cat.expand("RATES.OIS.USD_SOFR.PAR")
    assert "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y" in cat.expand("RATES.VOL.USD.ATM_RFR")
    xccy = cat.expand("RATES.XCCY_OIS_SWAP.USD.EUR")
    assert any(t.endswith(".SPREAD_LEG.BASIS_SPREAD") for t in xccy)

    # ccy1 . ccy2 . fwd . tenor . leg . BASIS_SPREAD below RATES.XCCY_OIS_SWAP,
    # i.e. seven dots. Two of the 840 stop one level short at the leg, because the
    # walk recorded those two nodes as leaves and the generator will not invent a
    # segment below a recorded leaf. That is a gap in the HARVEST, not in the
    # generator, and it is asserted here so a future re-harvest that closes it is
    # noticed rather than absorbed.
    short = sorted(t for t in xccy if t.count(".") != 7)
    assert len(short) == 2, f"expected exactly 2 truncated paths, got {len(short)}: {short[:5]}"
    assert all(t.endswith(("_LEG",)) for t in short)
    assert all(t.count(".") == 7 for t in xccy if t not in short)


def test_expansion_raises_over_the_cap_rather_than_truncating(cat: CitiVeloCatalog):
    """A silently-capped enumeration reads as 'that is all there is'."""
    n = cat.count_expansion("RATES.VOL.USD.OTM_RFR")
    assert n > 1000
    with pytest.raises(CatalogError) as excinfo:
        cat.expand("RATES.VOL.USD.OTM_RFR", max_tags=10)
    assert "max_tags" in str(excinfo.value)
    assert len(cat.expand("RATES.VOL.USD.OTM_RFR", max_tags=n + 1)) == n


def test_unknown_node_is_refused_but_a_raw_tag_is_never_blocked(cat: CitiVeloCatalog):
    with pytest.raises(CatalogError):
        cat.expand("RATES.NOT_A_FAMILY")
    # Pass-through is the client's contract, not the catalog's: a tag newer than
    # the committed catalog must still be fetchable.
    assert cat.verification("RATES.SOMETHING.BRAND.NEW") == "unverified"


# ------------------------------------------------------------------ #
#                     the per-measure OTM spelling                   #
# ------------------------------------------------------------------ #


def test_negative_strike_offsets_are_spelled_differently_per_measure(cat: CitiVeloCatalog):
    """``NORMALABSOLUTE`` uses ``OTM_M25``; ``PREMIUM`` uses ``OTM_N25``.

    A builder that hardcodes either spelling is wrong for the other branch. The
    offsets are read from the catalog per branch instead.
    """
    absolute = cat.options("RATES.VOL.USD.OTM_RFR.NORMALABSOLUTE.ANNUAL")
    premium = cat.options("RATES.VOL.USD.OTM_RFR.PREMIUM")
    assert "OTM_M25" in absolute and "OTM_N25" not in absolute
    assert "OTM_N25" in premium and "OTM_M25" not in premium

    assert T.vol_otm("USD", "1Y", "10Y", -25).endswith("OTM_M25.1Y.10Y")
    assert T.vol_otm("USD", "1Y", "10Y", -25, measure="PREMIUM").endswith("OTM_N25.1Y.10Y")
    assert T.vol_otm("USD", "1Y", "10Y", 25).endswith("OTM_25.1Y.10Y")


def test_rfr_branches_are_the_default_and_the_legacy_twins_warn(cat: CitiVeloCatalog):
    """Every legacy non-RFR branch is dead; all four ``_RFR`` twins are clean.

    The legacy branches account for 100% of the harvest's VOL shape failures and
    return no data, so they are opt-in and noisy.
    """
    usd = set(cat.options("RATES.VOL.USD"))
    assert set(RFR_VOL_BRANCHES) <= usd
    assert set(DEPRECATED_VOL_BRANCHES) <= usd
    assert "ATM_RFR" in T.vol_atm("USD", "1Y", "10Y")

    with pytest.warns(UserWarning, match="deprecated"):
        legacy = T.vol_atm("USD", "1Y", "10Y", rfr=False)
    assert ".ATM." in legacy and "_RFR" not in legacy


# ------------------------------------------------------------------ #
#                        honest unverified flags                     #
# ------------------------------------------------------------------ #


def test_swap_libor_coverage_is_per_currency():
    """46 currencies; the grammar is confirmed and coverage varies by currency.

    Measured live on 2026-08-05 at ``PAR.10Y``: EUR, AUD and INR served data
    while GBP and JPY came back EMPTY - which is what an IBOR family looks like
    after those two currencies migrated to RFR, not a shape failure. So the
    warning is about coverage, not about the grammar, and ``describe()`` says so.

    Note the family still has no local repricing path: its legs are IBOR-indexed,
    so the OIS conventions in ``curves/conventions.py`` would be the wrong ones.
    """
    with pytest.warns(UserWarning, match=r"(?i)per currency"):
        tag = T.swap_libor("EUR", "PAR", "10Y")
    assert tag == "RATES.SWAP_LIBOR.EUR.PAR.10Y"
    info = T.describe(tag)
    assert info.family == "SWAP_LIBOR"
    assert "IBOR" in info.note
    assert "2026-08-05" in info.note


def test_documented_only_families_say_so():
    """SPREAD_OPTIONS and MIDCURVES were harvested only to the measure level."""
    with pytest.warns(UserWarning, match="unverified"):
        spread = T.spread_option("USD", "1Y", "2Y5Y")
    assert spread == "RATES.SPREAD_OPTIONS.USD.OPT_CAP.VOL.1Y.2Y5Y"
    assert "documented shape" in T.describe(spread).note

    with pytest.warns(UserWarning, match="unverified"):
        mid = T.midcurve("USD_SOFR", "1Y", "1Y1Y")
    assert mid == "RATES.MIDCURVES.USD_SOFR.OPT_STR.VOL.1Y.1Y1Y"


def test_stale_curves_warn_rather_than_being_hidden():
    """``EUR_EONIA`` exists and resolves; it is simply about a year behind."""
    with pytest.warns(UserWarning, match="stale"):
        tag = T.ois_par("EUR_EONIA", "10Y")
    assert tag == "RATES.OIS.EUR_EONIA.PAR.10Y"


# ------------------------------------------------------------------ #
#                             the bonds                              #
# ------------------------------------------------------------------ #


def test_bond_universe_matches_the_harvest(cat: CitiVeloCatalog):
    """Floors, not equalities.

    The catalog is an accumulating union that never removes, so pinning its size
    turns growth into a failure. It grew twice for good reasons: seeding the 525
    matured USTs Citi quotes but ``CVCURVEBOND`` no longer lists took the whole
    file from 2,162 to 2,690 and the US GOVT slice from 349 to 877. Both are the
    feature. A SHRINK is the regression, and that is what these still catch.
    """
    bonds = cat.bonds()
    assert len(bonds) >= 2162, f"catalog shrank below the original harvest: {len(bonds)}"
    assert len({b.country for b in bonds}) >= 18
    assert {b.asset_type for b in bonds} == {"GOVT", "AGENCY", "COVERED"}
    usa_govt = cat.bonds(country="USA", asset_type="GOVT")
    assert len(usa_govt) >= 349, f"US GOVT shrank below the original harvest: {len(usa_govt)}"
    assert cat.bond_isin_lookup("US91282CCS89") is not None


def test_the_two_bond_vocabularies_are_different_surfaces():
    """``CVCURVEBOND`` accepts ``OAS`` but not ``DV01``; ``DV01`` IS a valid value.

    The desk's 43-entry measure catalogue is not the tag vocabulary either: every
    ``REFERENCE_DATA`` field is rejected, and ``DOLLAR_DURATION`` is really
    ``DV01``.
    """
    assert T.bond("US91282CCS89", "DV01").endswith(".DV01")
    with pytest.raises(UnknownTagError, match="CVCURVEBOND"):
        T.bond_curve("USA", "USD", "GOVT", "DV01")
    assert T.bond_curve("USA", "USD", "GOVT", "OAS", "20260805").endswith(".OAS.20260805")

    with pytest.raises(UnknownTagError, match="DV01"):
        T.bond("US91282CCS89", "DOLLAR_DURATION")
    with pytest.raises(UnknownTagError, match="REFERENCE_DATA"):
        T.bond("US91282CCS89", "SEDOL")


def test_empty_bond_asset_types_are_refused():
    """``CORP``, ``MUNI``, ``SUPRA``, ``TIPS`` and friends return nothing."""
    for dead in ("CORP", "MUNI", "SUPRA", "TIPS", "SSA"):
        with pytest.raises(UnknownTagError):
            T.bond_curve("USA", "USD", dead)


# ------------------------------------------------------------------ #
#                        frequency vocabulary                        #
# ------------------------------------------------------------------ #


def test_frequency_vocabulary_is_closed_and_se10_is_explained():
    """``SE10`` is the STREAMING granularity, not a ``CVTSHIST`` frequency.

    The desk's intraday workbook advertises it as the finest for OIS and TSY.OTR,
    which is the one wrong answer a reader of that workbook will reach for.
    """
    for good in ("MI01", "MI10", "HOURLY", "DAILY", "WEEKLY", "MONTHLY"):
        assert normalise_frequency(good.lower()) == good
    with pytest.raises(FrequencyError) as excinfo:
        normalise_frequency("SE10")
    message = str(excinfo.value)
    assert "STREAMING" in message.upper() and "MI01" in message


def test_swap_spread_liquid_tenors_are_recorded():
    """``CVMETADATA`` reports zero valid tenors here; ``CVTSHIST`` serves eleven."""
    assert len(T.SWAP_SPREAD_LIQUID_TENORS) == 11
    assert "10Y" in T.SWAP_SPREAD_LIQUID_TENORS
    assert T.ois_swap_spread("USD_SOFR", "10Y") == "RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y"


def test_unverified_families_are_reported_honestly(cat: CitiVeloCatalog):
    """The catalog records structure for far more than was ever probed."""
    unverified = cat.unverified_families()
    assert "SWAP_LIBOR" in unverified
    assert "OIS" not in unverified  # OIS was probed live
    assert "VOL" not in unverified
