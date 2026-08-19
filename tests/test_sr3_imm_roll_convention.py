"""The SR3 quarterly ladder on the IMM date itself -- one convention, everywhere.

Two comparison sites in this repo used to disagree on exactly ~4 days a year,
the quarterly IMM dates, and only on those days:

* ``packs.quarterly_imm_sequence(..., include_current=True)`` **keeps** the
  contract whose reference quarter begins today.
* ``tos._imm_cutoff`` + ``tos._next_contracts`` (strict ``<``) **dropped** it.

The repo now keeps it at both. The whole rationale -- CME's text does not
adjudicate a zero-day-elapsed accrual, the vendor "corroboration" was circular,
and the settlement grid says the starting contract is the live one -- is written
up in ``tos._imm_cutoff``'s docstring; this file is the executable half.

Every test here is pure date arithmetic. No market data, no I/O, no skips: the
convention is a calendar rule and it should be checkable on a machine with an
empty cache.

**Verifying the checker.** Each test below was run against the pre-fix
implementation (``_imm_cutoff`` returning the IMM date itself, and
``strat2_q20.instrument_count`` subtracting one on roll dates) and observed to
FAIL, with the harness compiling the mutated source first so that a syntax error
could not be scored as a kill. What each one catches:

``test_imm_cutoff_is_the_day_after_the_imm_date``
    the primitive itself.  [pre-fix: 2023-06-21 vs 2023-06-22]
``test_the_ladder_keeps_the_contract_whose_quarter_starts_today``
    the behaviour that primitive buys.  [pre-fix: front is SR3U23 on 2023-06-21]
``test_the_ladder_still_rolls_the_day_after_the_imm_date``
    the OTHER direction, so "keep it forever" cannot pass. This is the U25
    regression the strict cutoff was originally introduced for (``tos.py``:
    "SR3 rolls on IMM -- this fixes the U25 issue after 2025-09-17").
``test_the_two_ladders_agree_on_every_day_around_every_imm_date``
    the cross-site invariant. This is the test that would have caught the
    original drift, and the one that has to stay green if a future change moves
    either side.
``test_colour_packs_start_at_the_contract_whose_quarter_starts_today``
    the consumer that named the bug: ``Whites`` on an IMM date.
``test_sfrcm_rank_k_is_the_k_th_contract_of_the_pack_sequence``
    the alias layer, which is what ``strat2_q20`` calibrates its curve to.
"""
from __future__ import annotations

import datetime

import pytest

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import (
    _imm_cutoff,
    _monthly_cutoff,
    _next_contracts,
)
from MDP.STIRFutures.STIRFutureMDP import _package_contracts, _resolve_aliases_bulk
from MDP.STIRFutures._sofr_option_contracts import resolve_quarterly_contracts
from RVUtils.ConvexityRV.packs import imm_date, quarterly_imm_sequence
from RVUtils.ConvexityRV.strat2_sofr_convexity import futures_symbol

#: Quarterly IMM dates spanning the cached panel, plus one ahead of it.
_IMM_DATES = [imm_date(y, m)
              for y in range(2018, 2028)
              for m in (3, 6, 9, 12)]

#: 2023-06-21 is the worked example the two independent investigations both
#: landed on, so it is spelled out rather than generated.
_D = datetime.date(2023, 6, 21)


def _sr3_ladder(as_of: datetime.date, n: int) -> list:
    """The MDP-side ladder: what ``_next_contracts`` calls the front *n*."""
    return _next_contracts(as_of, prefix="SR3", count=n,
                           valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff)


def _packs_ladder(as_of: datetime.date, n: int) -> list:
    """The packs-side ladder, in the same symbol space."""
    return [futures_symbol(y, m, "SR3")
            for y, m in quarterly_imm_sequence(as_of, n)]


# ===========================================================================
# The primitive
# ===========================================================================
def test_imm_cutoff_is_the_day_after_the_imm_date():
    """``_next_contracts`` drops a month once ``as_of >= cutoff``, so the cutoff
    is the first date the contract is no longer forward-starting -- the day
    AFTER its IMM date, because on the IMM date zero days of its reference
    quarter have been observed."""
    assert imm_date(2023, 6) == datetime.date(2023, 6, 21)
    assert _imm_cutoff(2023, 6) == datetime.date(2023, 6, 22)
    for d in _IMM_DATES:
        assert _imm_cutoff(d.year, d.month) == d + datetime.timedelta(days=1)


def test_imm_cutoff_is_unchanged_for_non_quarterly_months():
    """Serial (SR1/ZQ) months keep the monthly cutoff. The +1 day is a statement
    about an IMM accrual, not about month ends."""
    for m in (1, 2, 4, 5, 7, 8, 10, 11):
        assert _imm_cutoff(2023, m) == _monthly_cutoff(2023, m)


# ===========================================================================
# The behaviour it buys
# ===========================================================================
def test_the_ladder_keeps_the_contract_whose_quarter_starts_today():
    """SR3M23 references 2023-06-21 -> 2023-09-20. On 2023-06-21 it is day 0 of
    91, it trades all session on the 0.0025 grid, and it is the largest open
    interest on the board. It is the front contract."""
    assert _sr3_ladder(_D, 4) == ["SR3M23", "SR3U23", "SR3Z23", "SR3H24"]


def test_the_ladder_is_unchanged_on_the_days_either_side():
    """The change is confined to the IMM date itself -- the boundary is a whole
    number of days, so no other date can move."""
    assert _sr3_ladder(_D - datetime.timedelta(days=1), 4) == \
        ["SR3M23", "SR3U23", "SR3Z23", "SR3H24"]
    assert _sr3_ladder(_D + datetime.timedelta(days=1), 4) == \
        ["SR3U23", "SR3Z23", "SR3H24", "SR3M24"]


def test_the_ladder_still_rolls_the_day_after_the_imm_date():
    """The strict cutoff existed for a reason -- ``tos.py`` records it as "this
    fixes the U25 issue after 2025-09-17". Keeping the contract ON the IMM date
    must not become keeping it after, or that fix is undone."""
    u25 = imm_date(2025, 9)
    assert u25 == datetime.date(2025, 9, 17)
    assert _sr3_ladder(u25, 1) == ["SR3U25"]
    assert _sr3_ladder(u25 + datetime.timedelta(days=1), 1) == ["SR3Z25"]
    # and it never holds a contract whose quarter has started
    for d in _IMM_DATES:
        for k in (1, 2, 7, 30):
            after = d + datetime.timedelta(days=k)
            front = _sr3_ladder(after, 1)[0]
            assert front != f"SR3{'HMUZ'[(d.month // 3) - 1]}{d.year % 100:02d}", \
                f"{after}: still holding the contract that started {d}"


# ===========================================================================
# The cross-site invariant -- the one that would have caught the drift
# ===========================================================================
@pytest.mark.parametrize("d", _IMM_DATES)
def test_the_two_ladders_agree_on_every_day_around_every_imm_date(d):
    """``packs`` and the MDP name the same twenty contracts, on every day.

    The two are reached by completely separate code -- one is a generator over
    ``(year, month)`` pairs, the other walks a month table against a cutoff
    function -- so this is a genuine cross-check and not a tautology. It is
    stated over the IMM boundary because that is the only place they could
    differ.
    """
    for k in (-2, -1, 0, 1, 2):
        as_of = d + datetime.timedelta(days=k)
        assert _sr3_ladder(as_of, 20) == _packs_ladder(as_of, 20), \
            f"ladders disagree on {as_of} (IMM {d})"


def test_the_two_ladders_agree_on_a_long_run_of_ordinary_days():
    """A wider net than the boundary test, cheap enough to run in full: every
    day of 2023 and 2025."""
    for year in (2023, 2025):
        d = datetime.date(year, 1, 1)
        while d.year == year:
            assert _sr3_ladder(d, 8) == _packs_ladder(d, 8), f"{d}"
            d += datetime.timedelta(days=1)


# ===========================================================================
# The consumers
# ===========================================================================
def test_colour_packs_start_at_the_contract_whose_quarter_starts_today():
    """``Whites`` is CME's "nearest four forward-starting quarterly months", and
    on the IMM date the contract starting today is still one of them."""
    assert _package_contracts("whites", _D) == \
        ["SR3M23", "SR3U23", "SR3Z23", "SR3H24"]
    assert _package_contracts("reds", _D) == \
        ["SR3M24", "SR3U24", "SR3Z24", "SR3H25"]
    # the colour ladder is a partition of the same sequence
    seq = _packs_ladder(_D, 20)
    for i, colour in enumerate(("whites", "reds", "greens", "blues", "golds")):
        assert _package_contracts(colour, _D) == seq[4 * i:4 * i + 4]


def test_sfrcm_rank_k_is_the_k_th_contract_of_the_pack_sequence():
    """``SFRCM{k}`` is the calibration instrument ``strat2_q20`` builds the Q20
    curve out of. It has to index the same ladder the pack universe counts, or
    a strip of depth *d* supplies *d-1* instruments and the shortfall is only
    visible as a cache miss."""
    seq = _packs_ladder(_D, 20)
    aliases = _resolve_aliases_bulk([f"SFRCM{k}" for k in range(1, 21)], _D)
    assert [aliases[f"SFRCM{k}"][0] for k in range(1, 21)] == seq
    assert aliases["SFRCM1"] == ["SR3M23"]


def test_the_option_underlying_ladder_uses_the_same_convention():
    """Cap/floor and listed-option strips resolve their underlying quarterly
    ladder through ``resolve_quarterly_contracts``. A different answer there is
    what refused 26 cap/floor cells, every one of them on an IMM date."""
    assert resolve_quarterly_contracts(_D, start_index=0, count=4, root="SFR") == \
        ["SFRM23", "SFRU23", "SFRZ23", "SFRH24"]
    for d in _IMM_DATES:
        got = resolve_quarterly_contracts(d, start_index=0, count=4, root="SFR")
        want = [futures_symbol(y, m, "SFR")
                for y, m in quarterly_imm_sequence(d, 4)]
        assert got == want, f"{d}"
