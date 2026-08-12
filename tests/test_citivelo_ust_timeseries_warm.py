r"""The ten-year UST timeseries warm: the four things that would fail silently.

``scripts/citivelo_ust_timeseries_warm.py`` warms the COMPUTED store - 28
constant-maturity aliases and 349 specific issues over ten years - and the whole
job rests on four mechanisms that are each one line and each invisible when
broken.

**The alias grid.** 4 ranks x 7 tenors = 28. Drop a rank and the run reports
success over three quarters of the curve.

**The resume key.** ``_key(start, end, values)`` is the entire definition of
"already done", and it is built from the unit's EFFECTIVE window rather than the
requested one. Drop the window and a ``--years 10`` run after a ``--years 5`` one
reads the manifest, sees every unit at the right key and does nothing - reporting
a ten-year warm with five years of it missing. Drop the values and the same
silence follows an added ``--values``. Use the REQUESTED window instead of the
effective one and the four 20-year ranks, which cannot exist before 2020-06-02,
are re-priced every night forever and never marked.

**The memory gate.** Excel wedged at 5,249 MB on 2026-08-07 and was measured at
13,884 MB the next day; it sat at 9,651 MB while this was written. The gate must
refuse BEFORE anything connects, stop mid-run at the ceiling, and FAIL CLOSED
when the probe cannot be read - "could not tell" and "nothing running" are
different facts and a wedged 13 GB add-in is what the second one hides.

**The fetch/build split.** Fetch is the only phase that may touch Excel. Build is
forced ``offline`` at the MDP, so a cache miss is an empty column and never a
workbook. If that ever inverted, the nightly job would open Excel unattended -
which is the exact failure ``utils.warm_jobs`` exists to prevent, arriving by a
different door.

Hermetic by construction
------------------------
Nothing here connects to Excel, and that is not incidental: ``EXCEL.EXE`` on this
machine is far above its ceiling and only a human restart shrinks it. The REAL
``CitiVeloBondFetcher`` is used - its ``plan`` and ``prefetch`` are what decide
which tags exist and how they are requested - but wrapped around a fake reader,
so ``quotes()`` returns the fake and ``client()`` is never reached. The reference
table is a small synthetic frame built from REAL CUSIPs (so the ISIN arithmetic
and the catalog lookups are real) with hand-chosen dates (so the expected ranking
is computable by hand rather than read back off the thing under test). The tag
cache is redirected through ``CITIVELO_EXCEL_CACHE_DIR`` and the manifest to
``tmp_path``, so no test can read or write the committed ones.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import pathlib
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from MDP.CitiVelocityExcel import memory_guard as MG
from MDP.CitiVelocityExcel.bonds import fetcher as BF
from MDP.CitiVelocityExcel.bonds import historic as H
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "citivelo_ust_timeseries_warm.py"


def _script():
    """Import the script by path, once. It is not in a package."""
    name = "_citivelo_ust_timeseries_warm_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


WARM = _script()


# ══════════════════════════════════════════════════════════════════════════
# A synthetic reference table with a KNOWN answer
# ══════════════════════════════════════════════════════════════════════════
#
# Real CUSIPs, so cusip_to_isin produces real ISINs and the catalog lookups in
# historic_universe are genuine. Invented issue/maturity dates, so the ranking
# this exercises is one whose answer is written down here rather than read back
# out of _filter_and_rank_ref_df.
#
# US912810EX29 is deliberately one Citi still LISTS (it matures 2026-08-15), and
# the others are deliberately ones it does not. That contrast is what several
# tests below turn on.

_D = datetime.date

_REF_ROWS = [
    # 2-Year: two issues, and the second lands INSIDE the window, so CT2 turns
    # over on 2025-01-16 and is a different bond either side of it.
    ("912828SC5", "T 2Y Jan 26", "2-Year", _D(2024, 1, 10), _D(2024, 1, 15), _D(2026, 1, 15), 4.25),
    ("912828MK3", "T 2Y Jan 27", "2-Year", _D(2025, 1, 10), _D(2025, 1, 15), _D(2027, 1, 15), 4.5),
    # 5-Year: three issues, all still outstanding through the window, so ranks
    # 0/1/2 exist together and rank 3 does not. Ranking is over bonds ALIVE at
    # the as-of date - a redeemed note is not "the old 5-year" - so the three
    # have to overlap for this to be a test of the ranks rather than of that.
    ("912828A91", "T 5Y Jan 26", "5-Year", _D(2021, 1, 10), _D(2021, 1, 15), _D(2026, 1, 15), 0.75),
    ("912828SD3", "T 5Y Jan 27", "5-Year", _D(2022, 1, 10), _D(2022, 1, 15), _D(2027, 1, 15), 1.5),
    ("912828B33", "T 5Y Jan 28", "5-Year", _D(2023, 1, 10), _D(2023, 1, 15), _D(2028, 1, 15), 4.0),
    # 30-Year: one issue, and it is one Citi still lists.
    ("912810EX2", "T 30Y Aug 26", "30-Year", _D(1996, 8, 8), _D(1996, 8, 15), _D(2026, 8, 15), 6.75),
    # 20-Year: FIRST ISSUED PART-WAY THROUGH the window, which is the real
    # 20-year's shape - Treasury reintroduced it in May 2020, so CT20 does not
    # resolve before 2020-06-02 and OOO20 not before 2021-03-02.
    ("912828H78", "T 20Y Jun 45", "20-Year", _D(2025, 6, 10), _D(2025, 6, 15), _D(2045, 6, 15), 5.0),
]


def _ref_frame():
    return pd.DataFrame(
        [
            {
                "record_date": issue,
                "label": label,
                "cusip": cusip,
                "oi": oi,
                "auction_date": auction,
                "issue_date": issue,
                "maturity_date": maturity,
                "cpn": cpn,
            }
            for cusip, label, oi, auction, issue, maturity, cpn in _REF_ROWS
        ]
    )


#: The window the synthetic table is designed around: CT2 turns over twice inside
#: it and the 20-year appears part-way through.
WINDOW = (_D(2024, 6, 3), _D(2025, 12, 31))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect the cache, the manifest, the probe and the reference table.

    ``reference_table`` is stubbed rather than left real for two reasons: the
    committed fiscaldata cache would otherwise be consulted (and refreshed over
    the NETWORK on a day it does not cover), and 1,785 real rows have no
    hand-computable answer. ``excel_memory_mb`` is stubbed because the real probe
    shells out to PowerShell against the live process, which is the thing under
    test rather than a dependency of it.
    """
    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(WARM, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(WARM, "reference_table", lambda force_refresh=False: _ref_frame())
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 100.0)
    return SimpleNamespace(tmp=tmp_path, manifest=tmp_path / "manifest.json")


#: The ONE bond these tests treat as "listed by Citi". A fixed base universe
#: rather than the committed catalog, because the catalog is an accumulating
#: union and a moving target - it went from 349 to 877 USA.USD.GOVT ISINs in a
#: single afternoon while this file was being written, which silently inverted
#: three tests that had pinned "this bond is not in it". A test of the mechanism
#: must not depend on today's snapshot of the data.
LISTED = "US912810EX29"


def _base_universe():
    from MDP.CitiVelocityExcel.bonds.universe import BondUniverse

    full = BondUniverse.from_catalog(country="USA", asset_type="GOVT")
    row = full.lookup(LISTED)
    assert row is not None, f"{LISTED} left the catalog; pick another listed bond"
    return BondUniverse([row], catalog=full._catalog)


def _plan(*, aliases=("CT2", "CT20"), cusips=(), values=("PRICE", "YIELD"), window=WINDOW):
    start, end = window
    return WARM.WarmPlan(
        start=start, end=end, aliases=aliases, cusips=cusips, values=values,
        base_universe=_base_universe(),
    )


def _book(path, phase):
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get(phase, {})


# ══════════════════════════════════════════════════════════════════════════
# 1. THE ALIAS GRID
# ══════════════════════════════════════════════════════════════════════════


def test_the_alias_grid_is_twenty_eight_and_is_exactly_these():
    """4 ranks x 7 tenors. Pinned as a SET, not as a count.

    A count alone passes if a rank is duplicated and a tenor lost, which is the
    shape of the mistake worth catching - the run would then report success while
    silently covering three quarters of the curve.
    """
    aliases = H.constant_maturity_aliases()
    assert len(aliases) == 28
    assert len(set(aliases)) == 28
    expected = {
        f"{prefix}{tenor}"
        for prefix in ("CT", "O", "OO", "OOO")
        for tenor in (2, 3, 5, 7, 10, 20, 30)
    }
    assert set(aliases) == expected
    assert WARM.default_aliases() == aliases


def test_the_grid_is_rank_major():
    """A --limit run should get a whole curve at one rank, not one tenor at four."""
    aliases = H.constant_maturity_aliases()
    assert aliases[:7] == ("CT2", "CT3", "CT5", "CT7", "CT10", "CT20", "CT30")
    assert aliases[7] == "O2"


@pytest.mark.parametrize(
    "alias,rank,tenor",
    [("CT2", 0, 2), ("CT30", 0, 30), ("O5", 1, 5), ("OO10", 2, 10), ("OOO20", 3, 20)],
)
def test_rank_and_tenor_match_the_resolver(alias, rank, tenor):
    """These have to agree with ``FixedRateBondsMDP._resolve_aliases_bulk``.

    The warm pre-computes which alias was which bond on which day; the build asks
    the MDP the same question at read time. If the two parsers disagreed the warm
    would fetch one set of bonds and the build would ask for another, and the
    result would be an empty series that raised nothing.
    """
    assert H.alias_rank_and_tenor(alias) == (rank, tenor)


@pytest.mark.parametrize("junk", ["", "CT", "912828A91", "X10", "CTX", "OOOO2"])
def test_a_non_alias_is_refused_rather_than_guessed(junk):
    """A CUSIP that fell into the alias list must raise, not resolve to something."""
    with pytest.raises(ValueError):
        H.alias_rank_and_tenor(junk)


# ══════════════════════════════════════════════════════════════════════════
# 2. WHICH BOND AN ALIAS WAS, ON WHICH DAY
# ══════════════════════════════════════════════════════════════════════════


def test_an_alias_is_a_different_bond_on_different_days():
    """The premise of the whole job, on a table whose answer is written above.

    ``912828SC5`` is the 2-year issued 2024-01-15 and ``912828MK3`` the one issued
    2025-01-15, so CT2 is the first for the first half of the window and the
    second afterwards. If this ever returned one bond, a ten-year CT2 series
    would be one note's life padded with nothing.
    """
    ref = _ref_frame()
    days = WARM.business_days(*WINDOW)
    track = H.resolve_alias_history(ref, ["CT2"], days)["CT2"]

    assert track.by_date[_D(2024, 7, 1)] == "912828SC5"
    assert track.by_date[_D(2025, 7, 1)] == "912828MK3"
    assert set(track.cusips) == {"912828SC5", "912828MK3"}
    assert track.first_resolvable == days[0]
    assert track.unresolved == ()


def test_the_old_and_the_double_old_are_the_ranks_below():
    """O5 and OO5 must be the previous issues, not the same bond three times."""
    ref = _ref_frame()
    days = WARM.business_days(*WINDOW)
    tracks = H.resolve_alias_history(ref, ["CT5", "O5", "OO5", "OOO5"], days)

    day = _D(2025, 7, 1)
    assert tracks["CT5"].by_date[day] == "912828B33"
    assert tracks["O5"].by_date[day] == "912828SD3"
    assert tracks["OO5"].by_date[day] == "912828A91"
    # Only three 5-year issues exist, so rank 3 has nothing to be.
    assert day not in tracks["OOO5"].by_date
    assert day in tracks["OOO5"].unresolved


def test_ranking_is_over_bonds_still_ALIVE_at_the_as_of_date():
    """A note that has redeemed is not "the old 5-year", and that is correct.

    ``912828A91`` matures 2026-01-15, so it is rank 2 through 2025 and gone in
    2026 - at which point ``OO5`` has nothing to be. Worth pinning because it is
    the one place where "which bond was this alias" and "which bonds existed" are
    different questions, and getting it backwards would silently splice a matured
    note into the middle of a live series.
    """
    ref = _ref_frame()
    tracks = H.resolve_alias_history(
        ref, ["OO5"], WARM.business_days(_D(2025, 12, 1), _D(2026, 3, 31))
    )
    track = tracks["OO5"]
    assert track.by_date[_D(2025, 12, 1)] == "912828A91"
    assert _D(2026, 3, 2) not in track.by_date
    assert _D(2026, 3, 2) in track.unresolved


def test_an_alias_that_did_not_exist_yet_reports_its_own_floor():
    """The 20-year shape: reintroduced part-way through, so it has a start date.

    Measured on the real table, ``CT20`` first resolves 2020-06-02 and ``OOO20``
    2021-03-02 - 996 and 1,191 unresolvable business days inside a ten-year
    window. Reporting that as a gap rather than as an error is what lets the
    resume key treat those ranks as finishable.
    """
    ref = _ref_frame()
    days = WARM.business_days(*WINDOW)
    track = H.resolve_alias_history(ref, ["CT20"], days)["CT20"]

    assert track.first_resolvable is not None
    assert track.first_resolvable > WINDOW[0], "the 20-year existed before it was issued"
    assert track.first_resolvable > _D(2025, 6, 15)
    assert len(track.unresolved) > 200
    assert all(d < track.first_resolvable for d in track.unresolved)


# ══════════════════════════════════════════════════════════════════════════
# 3. THE UNIVERSE THAT ADMITS MATURED BONDS
# ══════════════════════════════════════════════════════════════════════════


def test_the_committed_catalog_alone_cannot_name_the_matured_constituents():
    """The gap this job exists to close, demonstrated rather than asserted.

    ``resolve_bonds`` against the committed catalog is what the ordinary read path
    does, and it drops a bond that has redeemed - Citi's universe listing is
    today's set and there is no historical one. Over ten years that is 290 of the
    597 bonds the 28 aliases pass through.
    """
    from MDP.CitiVelocityExcel.bonds.resolution import resolve_bonds

    resolved, failures = resolve_bonds(
        [LISTED, "US912828A917"], universe=_base_universe(), strict=False
    )
    assert LISTED in resolved, "the listed bond should resolve"
    assert "US912828A917" in failures, (
        "a bond outside the universe resolved anyway - then this whole module is "
        "solving a problem that does not exist"
    )


def test_the_historic_universe_admits_them_and_keeps_the_listed_ones_intact():
    """Additive, never subtractive.

    A listed bond must keep its CATALOG descriptor, including the validated
    ``available_values`` that stop the fetcher spending Excel budget on tags
    already known unserved. Only the ones the catalog cannot name get a
    synthesised entry.
    """
    ref = _ref_frame()
    uni = H.historic_universe([LISTED, "US912828A917"], ref, base=_base_universe())

    listed = uni.lookup(LISTED)
    matured = uni.lookup("US912828A917")
    assert listed is not None and listed.source == "catalog"
    assert matured is not None and matured.source == "ust-reference"
    assert uni.available_values(LISTED), "the listed bond lost its coverage harvest"


def test_a_synthesised_descriptor_is_priceable_and_carries_treasurys_own_numbers():
    """Coupon in PERCENT and Treasury's own maturity - better than a parse, not worse.

    ``priceable`` gates ``build_rl_bond``: a descriptor without both a coupon and
    a maturity is refused there rather than substituted, so a synthesised entry
    that lost either would produce a bond that resolves and then cannot be priced.
    """
    ref = _ref_frame()
    uni = H.historic_universe(["US912828A917"], ref, base=_base_universe())
    d = uni.lookup("US912828A917")
    assert d.coupon == pytest.approx(0.75)
    assert d.maturity == _D(2026, 1, 15)
    assert d.priceable


def test_a_synthesised_descriptor_carries_no_coverage_claim():
    """A bond the coverage sweep never saw must not carry one.

    ``available_values`` is read from the committed validation harvest, and a
    synthesised descriptor is by definition outside it. Asserted on
    ``historic_universe``'s own output rather than through the catalog, because
    the catalog's coverage set is a moving target - the same afternoon this was
    written, the matured bonds acquired validated tags.
    """
    ref = _ref_frame()
    uni = H.historic_universe(["US912828A917"], ref, base=_base_universe())
    assert uni.lookup("US912828A917").source == "ust-reference"


def test_an_unvalidated_bond_is_asked_in_full_rather_than_skipped():
    """Empty ``available_values`` must read as "never validated", not "serves nothing".

    ``plan()`` treats an empty coverage list as unvalidated and asks the wire for
    the full value set. If it read it as a coverage FACT, every bond outside the
    harvest would be reported as serving nothing, the warm would fetch none of
    them, and it would look like a success.

    The resolution is built HERE rather than resolved out of a universe, because
    the property under test is ``plan``'s reading of an empty list - and routing
    through a catalog whose coverage set changes underneath makes the test pass or
    fail for reasons that have nothing to do with it.
    """
    from MDP.CitiVelocityExcel.bonds.resolution import BondResolution

    resolution = BondResolution(
        token="US912828A917", isin="US912828A917", cusip="912828A91", route="isin",
        descriptor=H.historic_universe(
            ["US912828A917"], _ref_frame(), base=_base_universe()
        ).lookup("US912828A917"),
        available_values=(),
    )

    built = BF.CitiVeloBondFetcher(offline=True).plan(
        [resolution], values=("PRICE", "YIELD")
    )["US912828A917"]

    assert built["validated"] is False
    assert sorted(built["tags"].values()) == [
        "RATES.BOND.US912828A917.PRICE",
        "RATES.BOND.US912828A917.YIELD",
    ]
    assert built["unavailable"] == ()


def test_an_isin_nothing_knows_about_raises_rather_than_disappearing():
    """Silently dropping it would leave a hole exactly where the history matters."""
    with pytest.raises(KeyError, match="neither"):
        H.historic_universe(["US0000000000"], _ref_frame(), base=_base_universe())


# ══════════════════════════════════════════════════════════════════════════
# 4. THE RESUME KEY
# ══════════════════════════════════════════════════════════════════════════


def test_the_same_request_produces_the_same_key():
    """Without this the manifest never matches and every run redoes everything."""
    a = WARM._key(_D(2016, 8, 8), _D(2026, 8, 8), ("PRICE", "YIELD"))
    b = WARM._key(_D(2016, 8, 8), _D(2026, 8, 8), ("PRICE", "YIELD"))
    assert a == b


@pytest.mark.parametrize(
    "label,start,end,values",
    [
        ("--years 10 after --years 5", _D(2016, 8, 8), _D(2026, 8, 8), ("PRICE", "YIELD")),
        ("one more day", _D(2021, 8, 8), _D(2026, 8, 9), ("PRICE", "YIELD")),
        ("an added value", _D(2021, 8, 8), _D(2026, 8, 8), ("PRICE", "YIELD", "DV01")),
        ("a removed value", _D(2021, 8, 8), _D(2026, 8, 8), ("PRICE",)),
    ],
)
def test_a_different_window_or_value_set_is_a_different_key(label, start, end, values):
    """Each of these is a request the manifest has NOT answered.

    A key that collapses any of them makes a resumed run skip work it never did:
    the widened window comes back reporting every unit warm with the extra years
    missing from the store and no record that they are.
    """
    base = WARM._key(_D(2021, 8, 8), _D(2026, 8, 8), ("PRICE", "YIELD"))
    assert WARM._key(start, end, values) != base, label


def test_value_order_does_not_change_the_key():
    """``--values YIELD PRICE`` is the same request as ``--values PRICE YIELD``.

    An order-sensitive key would re-price the whole ten years because someone
    typed the same set in a different order - measured at 372 s per six business
    days across 377 symbols, so about twenty hours.
    """
    start, end = _D(2016, 8, 8), _D(2026, 8, 8)
    assert WARM._key(start, end, ("PRICE", "YIELD", "DV01")) == WARM._key(
        start, end, ("DV01", "YIELD", "PRICE")
    )
    assert WARM._key(start, end, ("PRICE", "YIELD", "DV01")) != WARM._key(
        start, end, ("PRICE", "YIELD")
    )


def test_the_key_survives_a_json_round_trip():
    """It lives in the manifest, so it has to come back out as itself."""
    key = WARM._key(_D(2016, 8, 8), _D(2026, 8, 8), ("PRICE", "YIELD"))
    assert json.loads(json.dumps({"key": key}))["key"] == key


def test_a_unit_is_keyed_on_its_EFFECTIVE_window_not_the_requested_one(env):
    """The 20-year ranks, which is where a requested-window key goes wrong.

    ``CT20`` cannot exist before its first issue, so widening ``--years`` must not
    change its key - otherwise the four 20-year ranks are re-priced on every
    deepening run and never counted as done, forever. ``CT2`` spans the whole
    window and MUST change, or the widening would be skipped.
    """
    narrow = _plan(window=(_D(2025, 1, 1), _D(2025, 12, 31)))
    wide = _plan(window=(_D(2024, 6, 3), _D(2025, 12, 31)))

    def key_for(plan, symbol, year):
        for y, lo, hi in plan.slices(symbol):
            if y == year:
                return WARM._key(lo, hi, plan.values)
        return None

    # (a) The 20-year has NO slice before it was issued, in either window. A key
    #     built from the requested window instead of the alias's own floor gives
    #     it a 2024 slice - a whole year of a bond that did not exist, priced
    #     every run and never satisfiable.
    floor = wide.history["CT20"].first_resolvable
    assert floor is not None and floor > _D(2025, 6, 15)
    assert [year for year, _, _ in wide.slices("CT20")] == [2025], (
        "the 20-year was given slices for years before its first issue"
    )
    assert wide.slices("CT20")[0][1] == floor, (
        "the 20-year's first slice starts at the REQUESTED window rather than at "
        "its own first issue; that slice can never be filled, so the rank is "
        "re-priced on every run and never marked done"
    )

    # (b) ... and widening the request past that floor does not move its key.
    assert key_for(narrow, "CT20", 2025) == key_for(wide, "CT20", 2025)

    # (c) The opposite direction, so this is not just "everything is stable":
    #     CT2 spans both windows, so its interior year matches and the widening
    #     genuinely adds a 2024 slice that the narrow run never did.
    assert key_for(narrow, "CT2", 2025) == key_for(wide, "CT2", 2025)
    assert key_for(wide, "CT2", 2024) is not None
    assert key_for(narrow, "CT2", 2024) is None, "the narrow run has no 2024 slice to do"


def test_a_specific_issue_is_not_priced_outside_its_own_life(env):
    """Most of the saving, and a correctness point too.

    A bond has no data before it is issued or after it redeems, so a slice outside
    its life is pure CPU spent producing nothing. Over ten years the 349 listed
    USTs have a median life inside the window of about four years, so pricing all
    of them across the full span would be mostly empty days.
    """
    plan = _plan(aliases=(), cusips=("912828A91", "912828H78"),
                 window=(_D(2024, 6, 3), _D(2026, 6, 30)))

    # 912828A91 matures 2026-01-15, so 2026 stops there and 2027 never starts.
    matures = plan.slices("912828A91")
    assert [year for year, _, _ in matures] == [2024, 2025, 2026]
    assert matures[-1][2] == _D(2026, 1, 15), "priced past its own maturity"
    assert matures[0][1] == _D(2024, 6, 3), "priced before the window opened"

    # 912828H78 is ISSUED 2025-06-15, so the years before it do not exist.
    issued_late = plan.slices("912828H78")
    assert [year for year, _, _ in issued_late] == [2025, 2026]
    assert issued_late[0][1] == _D(2025, 6, 15), "priced before it was issued"


# ══════════════════════════════════════════════════════════════════════════
# 5. THE FETCH PHASE, AND THE MEMORY GATE ON IT
# ══════════════════════════════════════════════════════════════════════════


class FakeQuotes:
    """A ``CitiVeloQuotes``-shaped reader that never opens anything.

    ``offline = True`` is load-bearing: ``CitiVeloBondFetcher`` reconciles the flag
    against an injected reader and raises on a contradiction.

    ``writes`` is the point of the fake. ``False`` reproduces the defect the
    sibling warm was caught by - a fetch that returns cleanly and persists
    nothing - and ``True`` reproduces a working transport through the REAL
    ``CitiVeloTagCache``, so a passing test also proves the cache layout and
    ``cached_tags`` still agree about where a warmed tag lives.
    """

    offline = True

    def __init__(self, *, writes=True, raise_on=None):
        self.writes = writes
        self.raise_on = raise_on
        self.calls = []
        self.closed = False

    def frame(self, tags, freq="DAILY", **kwargs):
        self.calls.append(
            SimpleNamespace(tags=list(tags), freq=freq,
                            start=kwargs.get("start"), end=kwargs.get("end"))
        )
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise RuntimeError("Excel went away mid-batch")
        index = pd.date_range("2025-01-02", periods=2, freq="D")
        if self.writes:
            cache = CitiVeloTagCache(base_dir=default_cache_dir())
            for tag in tags:
                cache.write(tag, freq, pd.Series([1.0, 2.0], index=index))
            return pd.DataFrame({t: [1.0, 2.0] for t in tags}, index=index)
        return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))

    def close(self):
        self.closed = True


#: Captured at IMPORT, before anything can patch it. Reading
#: ``BF.CitiVeloBondFetcher`` inside the installer instead makes a second install
#: in the same test wrap the FIRST factory - so the second fake never receives a
#: call and every "it did not re-fetch" assertion passes for free. That bug was
#: live in this file and hid two real failures; see
#: test_bonds_already_at_this_key_are_not_refetched, which is the test it flattered.
_REAL_FETCHER = BF.CitiVeloBondFetcher


def _install_fetcher(monkeypatch, quotes):
    """The REAL fetcher, wrapped around ``quotes``, where ``fetch()`` looks.

    ``plan`` and ``prefetch`` are kept real: they decide which tags exist and how
    the request is windowed, which is most of what is worth testing here. Only the
    transport is faked, and ``close()`` on a fetcher with an injected reader is a
    no-op by design, so nothing can close a live client that was never opened.
    """
    made = []

    def _factory(*args, **kwargs):
        kwargs.pop("quotes", None)
        f = _REAL_FETCHER(*args, quotes=quotes, **kwargs)
        made.append(f)
        return f

    monkeypatch.setattr(BF, "CitiVeloBondFetcher", _factory)
    return made


def _isins_requested(quotes):
    out = set()
    for call in quotes.calls:
        for tag in call.tags:
            parts = str(tag).split(".")
            if len(parts) >= 3:
                out.add(parts[2])
    return out


def test_a_fetch_that_works_warms_the_tags_and_records_them(env, monkeypatch):
    """The positive control, end to end through the real cache."""
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    plan = _plan(aliases=("CT2",), cusips=("912810EX2",))

    out = WARM.fetch(plan, batch=2)

    assert out["stopped"] is False
    assert out["done"] == len(plan.isins) > 0
    assert out["tags"] == out["done"] * 2
    book = _book(env.manifest, "fetch")
    assert set(book) == set(plan.isins)
    assert all(e["tags"] == 2 for e in book.values())
    # It really is on disk, at DAILY, where cached_tags looks.
    assert WARM.cached_tags("DAILY", [f"RATES.BOND.{i}.PRICE" for i in plan.isins]) == len(plan.isins)


def test_the_fetch_covers_the_matured_constituents_not_only_the_listed_ones(env, monkeypatch):
    """The whole reason this script exists rather than reusing the sibling.

    A fetch that quietly warmed only the bonds Citi still lists would succeed, be
    fast, and leave the alias series empty on exactly the dates the backfill was
    for.
    """
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    plan = _plan(aliases=("CT2",))

    WARM.fetch(plan, batch=8)

    listed = {d.isin for d in _base_universe()}
    requested = _isins_requested(quotes)
    assert requested == set(plan.isins)
    assert requested - listed, (
        "every bond requested is one the universe already listed, so the bonds "
        "outside it were dropped - which is the bug this module removes"
    )


def test_a_fetch_that_caches_nothing_stops_and_records_nothing(env, monkeypatch):
    """The 134-second lie, pinned again on a second transport.

    The sibling warm's first version fetched 349 bonds without an error, left ZERO
    parquets on disk and wrote 349/349 done to its manifest. Everything downstream
    then believed the cache was warm, so the next unattended job went to live
    Excel. A warm is the file on disk, not the call returning.
    """
    quotes = FakeQuotes(writes=False)
    _install_fetcher(monkeypatch, quotes)

    out = WARM.fetch(_plan(aliases=("CT2",)), batch=4)

    assert quotes.calls, "nothing was fetched; this is not exercising the guard"
    assert out["stopped"] is True
    assert "cach" in out["reason"].lower(), out["reason"]
    assert out["done"] == 0
    assert _book(env.manifest, "fetch") == {}


def test_bonds_already_at_this_key_are_not_refetched(env, monkeypatch):
    """A lost session must cost time, not data."""
    plan = _plan(aliases=("CT2",))
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    WARM.fetch(plan, batch=4)
    first = _isins_requested(quotes)
    assert first

    again = FakeQuotes()
    _install_fetcher(monkeypatch, again)
    out = WARM.fetch(plan, batch=4)

    assert not again.calls, f"{sorted(_isins_requested(again))} were already warm and went out again"
    assert out["done"] == 0 and out["stopped"] is False


@pytest.mark.parametrize(
    "label,kwargs",
    [
        ("a deeper history", {"window": (_D(2024, 1, 2), _D(2025, 12, 31))}),
        ("an added value", {"values": ("PRICE", "YIELD", "DV01")}),
    ],
)
def test_a_widened_request_refetches_what_the_manifest_holds(env, monkeypatch, label, kwargs):
    """The resume key at the level the resume actually happens.

    A manifest entry written for one request says nothing about a wider one, in
    either direction. If it did, the run would report every bond warm with rows
    that were never fetched and no record that they are missing.
    """
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    WARM.fetch(_plan(aliases=("CT2",)), batch=4)

    again = FakeQuotes()
    _install_fetcher(monkeypatch, again)
    WARM.fetch(_plan(aliases=("CT2",), **kwargs), batch=4)

    assert _isins_requested(again), (
        f"{label}: a widened request was served from a manifest entry written for "
        f"a different one"
    )


def test_the_fetch_refuses_to_start_above_the_ceiling(env, monkeypatch):
    """Gated BEFORE anything is constructed. A check after ``client()`` is not a check."""
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 3600.0)
    quotes = FakeQuotes()
    made = _install_fetcher(monkeypatch, quotes)

    with pytest.raises(MG.ExcelTooLargeError):
        WARM.fetch(_plan(aliases=("CT2",)), batch=4, ceiling_mb=3500.0)

    assert not made and not quotes.calls


def test_the_fetch_stops_when_memory_reaches_the_ceiling_mid_run(env, monkeypatch):
    """Excel's memory only ever grows; it wedged at 5,249 MB on 2026-08-07.

    Stopping is the correct outcome and not an error to route around -
    ``recycle_workbook()`` was measured returning True while memory went UP 7 MB.
    The batch already done must survive, which is what lets several sessions add
    up to one warm.
    """
    readings = iter([100.0, 3500.0, 3500.0, 3500.0])
    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 100.0)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: next(readings, 3500.0))
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.fetch(_plan(aliases=("CT2",)), batch=1, ceiling_mb=3500.0)

    assert out["stopped"] is True
    assert "ceiling" in out["reason"].lower(), out["reason"]
    assert out["done"] == 1, "the first batch's progress was lost"
    assert len(_book(env.manifest, "fetch")) == 1


def test_an_unreadable_probe_stops_the_fetch_before_it_fetches_anything(env, monkeypatch):
    """FAIL CLOSED. "Could not tell" is not "nothing is running".

    A probe that timed out or was refused says nothing about what is live, and
    what might be live is the 13,884 MB process measured on 2026-08-08.
    """
    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 100.0)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: None)
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.fetch(_plan(aliases=("CT2",)), batch=4, ceiling_mb=3500.0)

    assert out["stopped"] is True
    assert "could not read" in out["reason"].lower(), out["reason"]
    assert out["done"] == 0
    assert not quotes.calls, "it fetched anyway after failing to read Excel's size"


def test_a_probe_that_raises_is_treated_as_unreadable(env, monkeypatch):
    """An exception out of the probe must gate the run, not crash it."""
    def _boom(**k):
        raise OSError("powershell not found")

    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 100.0)
    monkeypatch.setattr(MG, "excel_memory_mb", _boom)
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.fetch(_plan(aliases=("CT2",)), batch=4, ceiling_mb=3500.0)

    assert out["stopped"] is True and not quotes.calls


def test_a_reading_just_under_the_ceiling_still_runs(env, monkeypatch):
    """The gate must not be so eager the job can never make progress."""
    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 3499.0)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 3499.0)
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.fetch(_plan(aliases=("CT2",)), batch=8, ceiling_mb=3500.0)
    assert out["stopped"] is False and out["done"] > 0


def test_a_batch_that_fails_keeps_every_batch_before_it(env, monkeypatch):
    """One bad batch must not lose the rest - that is what makes it resumable."""
    quotes = FakeQuotes(raise_on=2)
    _install_fetcher(monkeypatch, quotes)

    out = WARM.fetch(_plan(aliases=("CT2",), cusips=("912810EX2", "912828MK3")), batch=1)

    assert out["stopped"] is True
    assert "Excel went away" in out["reason"]
    assert out["done"] == 1
    assert len(_book(env.manifest, "fetch")) == 1


# ══════════════════════════════════════════════════════════════════════════
# 6. THE FETCH / BUILD SPLIT
# ══════════════════════════════════════════════════════════════════════════


class _RecordingTB:
    """Stands in for TimeseriesBuilder. Records the windows and the queries."""

    calls = []

    def __init__(self, *a, **k):
        pass

    def get_timeseries(self, *, start, end, queries, **kwargs):
        _RecordingTB.calls.append(
            SimpleNamespace(start=start, end=end, queries=list(queries), kwargs=kwargs)
        )
        return pd.DataFrame(
            [[1.0] * len(queries)],
            index=pd.to_datetime([start]),
            columns=[f"q{i}" for i in range(len(queries))],
        )


@pytest.fixture
def no_pricing(monkeypatch):
    """Replace the pricing stack. The unit under test is the ORCHESTRATION."""
    import TB.FixedRateBondsTB as FTB
    import TB.TimeseriesBuilder as TTB

    _RecordingTB.calls = []
    monkeypatch.setattr(TTB, "TimeseriesBuilder", _RecordingTB)
    monkeypatch.setattr(FTB, "FixedRateBondsTB", lambda *a, **k: object())
    return _RecordingTB


def test_the_build_never_touches_excel_and_never_gates_on_it(env, monkeypatch, no_pricing):
    """The split, stated as the two things that must be true of the build half.

    It must not read Excel's memory (nothing it does can grow it), and it must not
    construct a fetcher that could connect. A lost Excel session therefore costs
    the fetch and nothing else, and the build runs on a laptop with no add-in.
    """
    def _forbidden(*a, **k):
        raise AssertionError("the build phase probed Excel")

    monkeypatch.setattr(MG, "excel_memory_mb", _forbidden)
    monkeypatch.setattr(MG, "assert_safe_to_connect", _forbidden)
    monkeypatch.setattr(
        BF, "CitiVeloBondFetcher",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("the build built a fetcher")),
    )

    out = WARM.build(_plan(aliases=("CT2",)), batch=4)
    assert out["stopped"] is False
    assert out["done"] > 0


def test_the_build_forces_the_mdp_offline_and_onto_the_historic_universe(env):
    """Both halves of what makes the build safe AND correct.

    ``offline`` is why a cache miss is an empty column instead of a workbook on an
    unattended run. ``citivelo_universe`` is why the matured constituents resolve
    at all - without it the build succeeds and is empty on exactly the dates the
    backfill was for. Both are given to the CONSTRUCTOR because a
    ``TimeseriesBuilder`` run has no way to pass request kwargs.
    """
    plan = _plan(aliases=("CT2",))
    uni = plan.universe()
    mdp = WARM._mdp(uni)

    assert mdp.source == "USTS_CITIVELO-RL"
    assert mdp._citivelo_option("offline", default=False) is True
    assert mdp._citivelo_option("citivelo_universe") is uni
    # ... and the constructor level really does reach the read path's lookup.
    assert mdp._citivelo_option("offline", {}, default=False) is True


def test_an_offline_mdp_does_not_prefetch(env):
    """The one call on the read path that would open a workbook, skipped.

    ``_citivelo_prefetch_range`` drives ``CitiVeloQuotes.frame`` through a LIVE
    reader. Leaving it in place under ``offline=True`` would mean the build's
    first act is the thing the flag exists to forbid.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    mdp = FixedRateBondsMDP(source="USTS_CITIVELO-RL", offline=True)
    out = mdp._citivelo_prefetch_range(
        timestamps=[_D(2025, 6, 2)], symbols=["CT2"],
    )
    assert out.tags == 0 and out.eod_ok is False and out.intraday_ok is False


def test_the_build_asks_for_the_unified_values_the_fetch_asked_citi_for():
    """The two vocabularies have to be derived from one map, not two literals.

    ``PRICE`` is ``FRB_CLEAN_PRICE`` and ``YIELD`` is ``FRB_YTM``, and on this
    source ``YIELD`` and ``YTM`` are DIFFERENT numbers - the pricer is built from
    ``PRICE`` and re-solves its own yield. A hardcoded pair here would drift from
    ``values.frb_value_for`` without anything failing.
    """
    pairs = dict((c, m.name) for c, m in WARM.unified_values(("PRICE", "YIELD", "SPREAD_TSY")))
    assert pairs == {
        "PRICE": "FRB_CLEAN_PRICE",
        "YIELD": "FRB_YTM",
        "SPREAD_TSY": "FRB_SPREAD_TSY",
    }


def test_a_citi_value_with_no_unified_counterpart_is_skipped_not_crashed():
    """It is still worth FETCHING; it is simply not buildable."""
    assert WARM.unified_values(("NOT_A_VALUE",)) == []
    assert [c for c, _ in WARM.unified_values(("PRICE", "NOT_A_VALUE"))] == ["PRICE"]


def test_the_build_prices_a_calendar_year_at_a_time(env, no_pricing):
    """Bounded memory, and a manifest fine-grained enough that a stop costs a year."""
    WARM.build(_plan(aliases=("CT2",), window=(_D(2024, 6, 3), _D(2025, 12, 31))), batch=8)

    windows = {(c.start.year, c.end.year) for c in no_pricing.calls}
    assert windows == {(2024, 2024), (2025, 2025)}
    for call in no_pricing.calls:
        assert call.start.year == call.end.year


def test_a_build_unit_already_done_is_skipped_and_a_widened_one_is_not(env, no_pricing):
    """The resume key, behaviourally, on the phase where re-doing costs twenty hours."""
    narrow = _plan(aliases=("CT2",), window=(_D(2025, 1, 2), _D(2025, 12, 31)))
    WARM.build(narrow, batch=8)
    assert no_pricing.calls

    no_pricing.calls = []
    WARM.build(narrow, batch=8)
    assert not no_pricing.calls, "an identical request re-priced everything"

    no_pricing.calls = []
    WARM.build(_plan(aliases=("CT2",), values=("PRICE", "YIELD", "SPREAD_TSY")), batch=8)
    assert no_pricing.calls, "an added value was served from a manifest entry without it"


def test_force_redoes_units_the_manifest_calls_done(env, no_pricing):
    """The override for a store someone cleared by hand."""
    plan = _plan(aliases=("CT2",))
    WARM.build(plan, batch=8)
    no_pricing.calls = []

    WARM.build(plan, batch=8, force=True)
    assert no_pricing.calls


def test_the_manifest_lives_beside_the_cache_and_not_in_the_repo():
    """The nightly slice runs from the PRIMARY checkout.

    A tracked file in this position leaves the user's working tree dirty every
    morning with a change nobody made and nobody commits - which is exactly the
    state that makes a real edit invisible.
    """
    path = WARM._manifest_path()
    assert path.name.endswith(".json")
    assert _REPO_ROOT not in path.parents, f"{path} is inside the repo"
    assert path.parent == default_cache_dir()


# ══════════════════════════════════════════════════════════════════════════
# 7. THE JOB IS DECLARED, AND DECLARED IN THE RIGHT ORDER
# ══════════════════════════════════════════════════════════════════════════


def test_the_daily_job_declares_the_tag_warm_it_reads():
    """Undeclared, the ordering guard cannot see it.

    The build reads the tag cache OFFLINE, so running before the tag warm does not
    fail - it returns empty columns, which the computed store then holds as days
    Citi served nothing. That is worse than the live-Excel failure the guard was
    written for, because it is silent and it persists.
    """
    from scripts import daily_cache_warmer as DCW

    job = next(j for j in DCW.WARM_JOBS if j.name == "CITIVELO UST timeseries values EOD")
    assert job.kind == "value"
    assert job.provides == ()
    assert DCW._CV_BOND_TAGS in job.requires

    provider = next(j for j in DCW.WARM_JOBS if DCW._CV_BOND_TAGS in j.provides)
    assert DCW.WARM_JOBS.index(provider) < DCW.WARM_JOBS.index(job)


def test_the_whole_registry_still_passes_the_ordering_check():
    """``check`` runs at import; call it again so a failure names this test."""
    from utils.warm_jobs import check

    from scripts import daily_cache_warmer as DCW

    check(DCW.WARM_JOBS)


# ------------------------------------------------------------------ #
#          the BUILD value set is stated, not derived                #
# ------------------------------------------------------------------ #


def test_the_build_set_is_not_derivable_from_the_fetch_set():
    """Why `build_values` has to exist at all.

    `unified_values` maps one Citi token to at most one `UnifiedValue`, so a build
    driven by the fetch set can only ever produce two values. The ten-year backfill
    writes ten. Left derived, the nightly job refreshes two of them and the other
    eight go stale from the day the backfill finishes - invisibly, because a series
    that stops updating looks exactly like one with nothing new to say.
    """
    from scripts.citivelo_ust_timeseries_warm import (
        DEFAULT_BUILD_VALUES,
        DEFAULT_VALUES,
        unified_values,
    )

    derived = {m.name for _, m in unified_values(DEFAULT_VALUES)}
    assert derived == {"FRB_CLEAN_PRICE", "FRB_YTM"}
    assert len(DEFAULT_BUILD_VALUES) == 10
    assert derived < set(DEFAULT_BUILD_VALUES), "the fetch set must be a strict subset"


def test_every_declared_build_value_exists():
    """A typo here is a warm that raises on the first slice, at 3am."""
    from Query.Unified.registry import UnifiedValue
    from scripts.citivelo_ust_timeseries_warm import DEFAULT_BUILD_VALUES

    missing = [v for v in DEFAULT_BUILD_VALUES if getattr(UnifiedValue, v, None) is None]
    assert not missing, f"not UnifiedValue members: {missing}"


def test_the_nightly_job_asks_for_all_ten():
    """The job the cron runs, not the constant it could have used."""
    import datetime as _dt

    import scripts.daily_cache_warmer as dcw
    from scripts.citivelo_ust_timeseries_warm import DEFAULT_BUILD_VALUES

    seen = {}

    class _Plan:
        def __init__(self, **kw):
            seen.update(kw)

        def describe(self):
            return "stub"

    orig_plan = dcw.__dict__.get("WarmPlan")
    import scripts.citivelo_ust_timeseries_warm as tw

    real_plan, real_build = tw.WarmPlan, tw.build
    tw.WarmPlan = _Plan
    tw.build = lambda plan, **kw: {"stopped": False}
    try:
        dcw.warm_citivelo_ust_timeseries(_dt.date(2026, 8, 3), _dt.date(2026, 8, 7))
    finally:
        tw.WarmPlan, tw.build = real_plan, real_build

    assert tuple(seen.get("build_values") or ()) == tuple(DEFAULT_BUILD_VALUES)


def test_widening_the_build_set_invalidates_the_resume_key():
    """The vintage trap, in its own words.

    Widening the built set without touching the key reads the manifest, finds
    every unit already done, does nothing, and reports a ten-value warm holding
    two.

    Drives ``build_unit_key`` - the function ``build`` actually calls. The first
    version of this test compared ``_key`` against two hand-made tuples, which
    only asserts that ``_key`` reads its argument; it passed happily with the
    build values deleted from the caller.
    """
    import datetime as _dt
    from types import SimpleNamespace

    from scripts.citivelo_ust_timeseries_warm import build_unit_key

    lo, hi = _dt.date(2026, 1, 1), _dt.date(2026, 8, 7)
    narrow = SimpleNamespace(values=("PRICE", "YIELD"), build_values=("FRB_YTM",))
    wide = SimpleNamespace(
        values=("PRICE", "YIELD"), build_values=("FRB_YTM", "FRB_DV01")
    )
    unit_a, stamp_a = build_unit_key(narrow, "CT10", 2026, lo, hi)
    unit_b, stamp_b = build_unit_key(wide, "CT10", 2026, lo, hi)

    assert unit_a == unit_b == "CT10@2026"
    assert stamp_a != stamp_b, "the build values never reached the resume key"

    same = build_unit_key(narrow, "CT10", 2026, lo, hi)
    assert same == (unit_a, stamp_a), "the key must be stable for an unchanged plan"


def test_build_computes_the_declared_values_not_the_derived_two():
    """The behaviour the whole change exists for.

    Drives `build_pairs`, which `build` calls. Checked inline, a mutation that
    ignored `plan.build_values` and fell back to the fetch set passed the entire
    suite - the ten-value nightly quietly became a two-value one.
    """
    from types import SimpleNamespace

    from scripts.citivelo_ust_timeseries_warm import DEFAULT_BUILD_VALUES, build_pairs

    declared = SimpleNamespace(values=("PRICE", "YIELD"), build_values=DEFAULT_BUILD_VALUES)
    names = [m.name for _, m in build_pairs(declared)]
    assert names == list(DEFAULT_BUILD_VALUES)
    assert len(names) == 10

    # and without one, the old derived behaviour, unchanged
    derived = SimpleNamespace(values=("PRICE", "YIELD"), build_values=None)
    assert {m.name for _, m in build_pairs(derived)} == {"FRB_CLEAN_PRICE", "FRB_YTM"}


def test_an_unknown_build_value_fails_loudly():
    """At plan time, not at 3am on the first slice."""
    from types import SimpleNamespace

    import pytest as _pytest

    from scripts.citivelo_ust_timeseries_warm import build_pairs

    bad = SimpleNamespace(values=("PRICE",), build_values=("FRB_NOT_A_VALUE",))
    with _pytest.raises(ValueError, match="FRB_NOT_A_VALUE"):
        build_pairs(bad)


def test_build_actually_calls_build_pairs(monkeypatch):
    """That ``build`` USES the helper, not merely that the helper is right.

    A plan with no symbols is the whole trick: ``pairs`` is computed before the
    unit list, and an empty unit list returns immediately - so this reaches the
    value decision and nothing else. No market data provider, no Excel, no store.

    Without it, deleting the ``build_pairs`` call and going back to deriving two
    values from the fetch set passed all sixty-one other tests.
    """
    from types import SimpleNamespace

    import scripts.citivelo_ust_timeseries_warm as tw

    calls = []
    real = tw.build_pairs

    def _spy(plan):
        calls.append(plan)
        return real(plan)

    monkeypatch.setattr(tw, "build_pairs", _spy)

    plan = SimpleNamespace(
        values=("PRICE", "YIELD"),
        build_values=tw.DEFAULT_BUILD_VALUES,
        symbols=lambda: [],
        slices=lambda s: [],
    )
    out = tw.build(plan, n_jobs=1)

    assert out["of"] == 0, "the plan was supposed to have nothing to do"
    assert len(calls) == 1, "build did not go through build_pairs"
