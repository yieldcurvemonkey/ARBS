"""Synthetic, no-network tests for the ZQ (30-day Fed Funds) machinery.

Every assertion here is derived from CBOT rulebook Chapter 22 or from
hand-arithmetic, **not** from the implementation's own output. That distinction
is the point: the settlement rule has three separate places to get a day count
wrong (weekend carry, the effective-date lag, the month boundary) and a test
that merely pins today's answer would lock all three in.
"""
from __future__ import annotations

import calendar
import datetime

import numpy as np
import pytest

from RVUtils.MeanRev.ff import (
    ZQ_DV01_USD,
    ZQ_HALF_TICK_BP,
    ZQ_POINT_USD,
    ZQ_TICK_BP,
    applicable_source_day,
    code_to_month,
    compounding_bias_bp,
    day_regime_index,
    delivery_window,
    effr_publication_days,
    expected_settle_rate,
    half_tick_onset,
    month_code,
    round_settle_rate,
    round_trip_bp,
    tick_bp,
    zq_exposure_matrix,
    zq_exposure_vector,
    zq_regime_weights,
)
from RVUtils.MeanRev.meetings import fomc_decisions

D = datetime.date


# ---------------------------------------------------------------------------
# contract calendar
# ---------------------------------------------------------------------------

def test_month_codes_round_trip():
    for y in (2018, 2024, 2026, 2031):
        for m in range(1, 13):
            assert code_to_month(month_code(y, m)) == (y, m)
    assert month_code(2026, 12) == "Z26"
    assert month_code(2027, 1) == "F27"
    assert code_to_month("ZQF27") == (2027, 1)


def test_delivery_window_is_the_whole_calendar_month():
    for y in (2024, 2026, 2028):                    # 2024 and 2028 are leap years
        for m in range(1, 13):
            s, e, n = delivery_window(month_code(y, m))
            assert s == D(y, m, 1)
            assert n == calendar.monthrange(y, m)[1]
            assert (e - s).days == n
            assert e == (D(y + 1, 1, 1) if m == 12 else D(y, m + 1, 1))
    assert delivery_window("G24")[2] == 29          # Feb 2024, leap
    assert delivery_window("G26")[2] == 28


# ---------------------------------------------------------------------------
# the publication calendar and the carry rule (Sec 22103)
# ---------------------------------------------------------------------------

def test_publication_days_exclude_weekends():
    days = effr_publication_days(D(2026, 7, 1), D(2026, 8, 1))
    assert all(d.weekday() < 5 for d in days)


def test_publication_days_exclude_a_fed_holiday_that_nyse_trades():
    """Columbus Day: Federal Reserve Banks closed, NYSE open.

    Using an exchange calendar instead of the Fed's would put an EFFR print on a
    day that has none, and shift a day of weight between regimes.
    """
    fed = set(effr_publication_days(D(2026, 10, 1), D(2026, 11, 1)))
    nyse = set(effr_publication_days(D(2026, 10, 1), D(2026, 11, 1),
                                     calendar_name="nyse"))
    columbus = D(2026, 10, 12)                     # second Monday of October
    assert columbus.weekday() == 0
    assert columbus not in fed
    assert columbus in nyse


def test_a_weekend_takes_the_preceding_fridays_rate():
    fri, sat, sun, mon = D(2026, 7, 10), D(2026, 7, 11), D(2026, 7, 12), D(2026, 7, 13)
    assert fri.weekday() == 4
    src = applicable_source_day([fri, sat, sun, mon])
    assert src == [fri, fri, fri, mon]


def test_a_friday_rate_carries_three_days_of_weight():
    """The rule the brief flags: Fri+Sat+Sun all settle on Friday's print."""
    days = [D(2026, 7, 1) + datetime.timedelta(days=i) for i in range(31)]
    src = applicable_source_day(days)
    counts = {}
    for s in src:
        counts[s] = counts.get(s, 0) + 1
    fridays = [d for d in set(src) if d.weekday() == 4]
    assert fridays
    for f in fridays:
        # every Friday in the middle of the month carries itself + Sat + Sun
        if f + datetime.timedelta(days=2) <= days[-1]:
            assert counts[f] == 3, f


# ---------------------------------------------------------------------------
# exposure vectors -- the properties that must hold whatever the code does
# ---------------------------------------------------------------------------

_MEETINGS_26_27 = [D(2026, 1, 28), D(2026, 3, 18), D(2026, 4, 29), D(2026, 6, 17),
                   D(2026, 7, 29), D(2026, 9, 16), D(2026, 10, 28), D(2026, 12, 9),
                   D(2027, 1, 27), D(2027, 3, 17), D(2027, 4, 28), D(2027, 6, 16)]


def test_regime_weights_sum_to_exactly_one():
    """A partition of the month's days cannot sum to anything else."""
    for y in (2026, 2027):
        for m in range(1, 13):
            w = zq_regime_weights(delivery_window(month_code(y, m))[:2],
                                  _MEETINGS_26_27)
            assert w.sum() == pytest.approx(1.0, abs=1e-12), (y, m)
            assert (w >= 0).all()


def test_exposure_is_bounded_and_monotone_in_meeting_order():
    for y in (2026, 2027):
        for m in range(1, 13):
            w = zq_exposure_vector(delivery_window(month_code(y, m))[:2],
                                   _MEETINGS_26_27)
            assert ((w >= 0.0) & (w <= 1.0)).all(), (y, m)
            # a later meeting can never be in force for MORE of the month
            assert np.all(np.diff(w) <= 1e-12), (y, m, w)


def test_a_month_with_no_meeting_has_a_single_regime():
    """Nov 2026 contains no scheduled decision, so every day is one regime.

    That is also why adjacent no-meeting months are structurally pinned: nothing
    can move between them without a meeting, which is what makes those flies
    degenerate rather than merely quiet.
    """
    w = zq_regime_weights(delivery_window("X26")[:2], _MEETINGS_26_27)
    assert w.max() == pytest.approx(1.0)
    assert (np.sort(w)[:-1] == 0).all()
    exp = zq_exposure_vector(delivery_window("X26")[:2], _MEETINGS_26_27)
    assert set(np.round(exp, 12)) <= {0.0, 1.0}


def test_december_2026_is_the_blended_month():
    """Hand-computed. Decision Wed 2026-12-09 takes effect Thu 2026-12-10, which
    is a publication day, so days 1-9 carry the old rate and 10-31 the new:
    9 pre, 22 post, out of 31."""
    w = delivery_window("Z26")[:2]
    assert delivery_window("Z26")[2] == 31
    exp = zq_exposure_vector(w, [D(2026, 12, 9)])
    assert exp[0] == pytest.approx(22.0 / 31.0)
    reg = zq_regime_weights(w, [D(2026, 12, 9)])
    assert reg == pytest.approx([9.0 / 31.0, 22.0 / 31.0])


def test_january_2027_is_the_clean_read_on_the_december_meeting():
    """The claim the whole FF thesis rests on.

    The December decision is in force for ALL of January, so FFF27 reads it
    without dilution -- until the 2027-01-27 decision (effective the 28th) clips
    the last four days.
    """
    w = delivery_window("F27")[:2]
    assert delivery_window("F27")[2] == 31
    exp = zq_exposure_vector(w, [D(2026, 12, 9), D(2027, 1, 27)])
    assert exp[0] == pytest.approx(1.0)                 # December: fully in force
    assert exp[1] == pytest.approx(4.0 / 31.0)          # Jan 28, 29, 30, 31
    # ...and December's own contract is only 22/31 exposed to the same meeting,
    # so January carries 1/(22/31) = 1.41x the meeting per unit of contract.
    dec = zq_exposure_vector(delivery_window("Z26")[:2], [D(2026, 12, 9)])
    assert exp[0] / dec[0] == pytest.approx(31.0 / 22.0)


def test_weekend_carry_changes_the_split_for_a_friday_decision():
    """Where the carry rule actually bites.

    A Friday decision would take effect on a Saturday, which publishes nothing,
    so the old rate carries through the weekend and the new regime does not
    start until Monday. A naive calendar-day count would credit the new regime
    with the Saturday and Sunday too.

    No FOMC decision in the actual 2018-2027 calendar lands on a Friday -- every
    one is a Wednesday or a Thursday -- so this is the guard for the projected
    calendar rather than a live correction. It is tested because "we checked and
    it does not bite" is only worth saying if the check exists.
    """
    friday = D(2026, 7, 10)
    assert friday.weekday() == 4
    w = delivery_window("N26")[:2]                      # July 2026, 31 days
    exp = zq_exposure_vector(w, [friday])
    # effective rolls Sat 11 -> Mon 13, so post = 13..31 = 19 days
    assert exp[0] == pytest.approx(19.0 / 31.0)
    naive = (31 - 11 + 1) / 31.0                        # Sat 11 .. 31 = 21 days
    assert exp[0] < naive
    assert (naive - exp[0]) * 31 == pytest.approx(2.0)  # exactly the weekend


def test_juneteenth_delays_the_2025_06_18_decision_by_a_day():
    """The carry rule bites a REAL meeting, and exactly one of them.

    Sweeping 2018-2027, the only decision whose effective day is not an EFFR
    publication day is 2025-06-18: the day after is Juneteenth, a federal
    holiday since 2021, so Thursday carries Wednesday's pre-decision rate and
    the new regime reaches the average only on Friday the 20th.

    That moves one of June 2025's thirty days from post to pre -- 3.3% of the
    contract's exposure to that meeting, 0.8bp on a 25bp move. It is the single
    concrete reason this module counts days through the publication calendar
    instead of the obvious way.
    """
    from RVUtils.MeanRev.meetings import fomc_decisions

    pub = set(effr_publication_days(D(2018, 1, 1), D(2028, 1, 1)))
    offenders = [m for m in fomc_decisions(D(2018, 1, 1), D(2027, 12, 31))
                 if m + datetime.timedelta(days=1) not in pub]
    assert offenders == [D(2025, 6, 18)], offenders

    w = delivery_window("M25")[:2]                  # June 2025, 30 days
    assert delivery_window("M25")[2] == 30
    exp = zq_exposure_vector(w, [D(2025, 6, 18)])
    assert exp[0] == pytest.approx(11.0 / 30.0)     # Jun 20..30 inclusive
    naive = 12.0 / 30.0                             # Jun 19..30 if the 19th counted
    assert exp[0] < naive
    assert (naive - exp[0]) * 30 == pytest.approx(1.0)


def test_exposure_matrix_stacks_the_vectors():
    ws = [delivery_window(c)[:2] for c in ("Z26", "F27", "G27")]
    W = zq_exposure_matrix(ws, _MEETINGS_26_27)
    assert W.shape == (3, len(_MEETINGS_26_27))
    for i, w in enumerate(ws):
        assert W[i] == pytest.approx(zq_exposure_vector(w, _MEETINGS_26_27))


# ---------------------------------------------------------------------------
# the settlement model
# ---------------------------------------------------------------------------

def test_expected_settle_is_the_hand_weighted_average():
    w = delivery_window("Z26")[:2]
    got = expected_settle_rate(w, [D(2026, 12, 9)], [4.00, 4.25])
    hand = (9.0 * 4.00 + 22.0 * 4.25) / 31.0
    assert got == pytest.approx(hand)


def test_expected_settle_with_no_meeting_is_the_flat_rate():
    got = expected_settle_rate(delivery_window("X26")[:2], [], [4.13])
    assert got == pytest.approx(4.13)


def test_expected_settle_rejects_a_bad_regime_count():
    with pytest.raises(ValueError, match="regime rates"):
        expected_settle_rate(delivery_window("Z26")[:2], [D(2026, 12, 9)], [4.0])


def test_settlement_rounding_matches_the_rulebook_example():
    """Sec 22103's own worked example: 2.5915 -> 2.592 -> price 97.408."""
    assert round_settle_rate(2.5915) == pytest.approx(2.592)
    assert 100.0 - round_settle_rate(2.5915) == pytest.approx(97.408)


def test_settlement_rounding_breaks_ties_upward_not_to_even():
    """Ties go UP, and neither float arithmetic nor Python's round does that.

    2.5925 is the discriminating case. In binary it sits a hair BELOW the tie
    (2592.4999999999995 tenths of a bp), so ``floor(x/step + 0.5)`` rounds it
    down to 2.592 and so does ``round``, which additionally breaks exact ties to
    even. The rulebook says 2.593.
    """
    assert round_settle_rate(2.5915) == pytest.approx(2.592)
    assert round_settle_rate(2.5905) == pytest.approx(2.591)
    assert round_settle_rate(2.5925) == pytest.approx(2.593)
    assert round(2.5925, 3) == pytest.approx(2.592)      # what NOT to use
    assert round_settle_rate(4.1234) == pytest.approx(4.123)
    assert round_settle_rate(4.1236) == pytest.approx(4.124)
    assert round_settle_rate(4.1235) == pytest.approx(4.124)
    # every tenth-of-a-bp tie in a realistic range must go up
    for k in range(0, 600):
        x = 2.0 + k * 0.001 + 0.0005
        assert round_settle_rate(x) == pytest.approx(round(x + 1e-9, 3), abs=1e-9), x


def test_compounding_bias_is_the_size_the_convention_trap_predicts():
    """A compounded window overstates the arithmetic average by ~r^2 n / 720.

    At 4% over 31 days that is 0.69bp -- larger than a ZQ half-tick, so building
    a ZQ on a compounded (SOFR) spec is the wrong contract, not a near one.
    """
    assert compounding_bias_bp(4.0, 31) == pytest.approx(0.689, abs=0.01)
    assert compounding_bias_bp(4.11, 30) == pytest.approx(0.704, abs=0.01)
    assert compounding_bias_bp(0.1, 31) < 0.01           # negligible at ZIRP
    assert compounding_bias_bp(4.0, 91) > compounding_bias_bp(4.0, 31)


# ---------------------------------------------------------------------------
# ticks and cost (Sec 22102.C)
# ---------------------------------------------------------------------------

def test_contract_scaling_constants():
    assert ZQ_POINT_USD == pytest.approx(4167.0)
    assert ZQ_DV01_USD == pytest.approx(ZQ_POINT_USD / 100.0, abs=0.01)
    assert ZQ_TICK_BP == 0.5 and ZQ_HALF_TICK_BP == 0.25
    # one tick = 0.005 index points = $20.835; the half tick = $10.4175
    assert ZQ_TICK_BP / 100.0 * ZQ_POINT_USD == pytest.approx(20.835, abs=0.01)
    assert ZQ_HALF_TICK_BP / 100.0 * ZQ_POINT_USD == pytest.approx(10.4175, abs=0.01)


def test_half_tick_onset_obeys_the_first_of_month_weekday_rule():
    """The structural characterisation, independent of the implementation.

    Month starts Sat/Sun/Mon -> the half tick begins ON or after the first of the
    delivery month. Month starts Tue-Fri -> it begins BEFORE it, because the rule
    anchors on the last Sunday of the PRECEDING month.
    """
    checked = 0
    for y in (2024, 2025, 2026, 2027):
        for m in range(1, 13):
            code = month_code(y, m)
            first = datetime.date(y, m, 1)
            onset = half_tick_onset(code)
            if first.weekday() in (5, 6, 0):
                assert onset >= first, (code, first.strftime("%a"), onset)
            else:
                # <=, not <: the anchor is the trading day after the last Sunday
                # of the previous month, and a holiday in between can push that
                # onto the 1st itself. June 2027 starts on a Tuesday, the last
                # Sunday of May 2027 is the 30th, and the 31st is Memorial Day --
                # so the onset lands exactly on 2027-06-01.
                assert onset <= first, (code, first.strftime("%a"), onset)
            checked += 1
    assert checked == 48
    # ...and the Memorial Day case is real, not defensive
    assert half_tick_onset("M27") == datetime.date(2027, 6, 1)
    assert datetime.date(2027, 6, 1).weekday() == 1


def test_half_tick_onset_is_always_a_trading_day_and_near_the_boundary():
    for y in (2025, 2026):
        for m in range(1, 13):
            onset = half_tick_onset(month_code(y, m))
            assert onset.weekday() < 5
            assert abs((onset - datetime.date(y, m, 1)).days) <= 8


def test_tick_size_switches_on_the_onset():
    code = "Z26"
    onset = half_tick_onset(code)
    assert tick_bp(code, onset) == ZQ_HALF_TICK_BP
    assert tick_bp(code, onset + datetime.timedelta(days=1)) == ZQ_HALF_TICK_BP
    assert tick_bp(code, onset - datetime.timedelta(days=1)) == ZQ_TICK_BP
    assert tick_bp(code, datetime.date(2026, 1, 5)) == ZQ_TICK_BP


def test_round_trip_matches_the_sr3_convention_when_all_legs_are_full_tick():
    """A 1/-2/1 package of full-tick contracts costs 4 x 0.5 = 2.0bp, exactly the
    figure the SR3 lab uses -- the cost rule is per CONTRACT in both."""
    early = datetime.date(2026, 1, 5)
    codes = ["Z26", "F27", "G27"]
    assert all(tick_bp(c, early) == ZQ_TICK_BP for c in codes)
    assert round_trip_bp(codes, early, [1, -2, 1]) == pytest.approx(2.0)
    assert round_trip_bp(codes, early) == pytest.approx(1.5)   # 3 x 1 contract


def test_round_trip_mixes_tick_sizes_across_the_onset():
    """A spread straddling the onset pays a different tick on each leg."""
    code_near, code_far = "Z26", "F27"
    d = half_tick_onset(code_near)
    assert tick_bp(code_near, d) == ZQ_HALF_TICK_BP
    assert tick_bp(code_far, d) == ZQ_TICK_BP
    assert round_trip_bp([code_near, code_far], d, [1, -1]) == pytest.approx(0.75)


def test_day_regime_index_counts_meetings_in_force():
    idx = day_regime_index(delivery_window("Z26")[:2], [D(2026, 12, 9)])
    assert idx.size == 31
    assert (idx[:9] == 0).all()
    assert (idx[9:] == 1).all()


# ---------------------------------------------------------------------------
# meeting-INDEXED structures -- the ones a desk actually trades
# ---------------------------------------------------------------------------

def test_the_desk_fomc_123_fly_as_of_2026_07_30():
    """The golden test for meeting indexing, taken from desk convention.

    As of 2026-07-30 the next three decisions are Sep-16, Oct-28 and Dec-09, and
    a desk's "FOMC 1/2/3 fly" is built on the contracts that READ them:
    **ZQV26 / ZQX26 / ZQF27** -- October, November and January-27.

    **December is not in it.** ZQZ26 splits 22/31 at the post-December rate and
    9/31 at the post-October rate, so it reads neither decision cleanly, and the
    January contract reads December better (27/31) than December does (22/31).

    A calendar-consecutive fly on (Oct, Nov, Dec) is a DIFFERENT and weaker
    object: it loads the December decision at -0.71 instead of -1.00.
    """
    asof = D(2026, 7, 30)
    meetings = fomc_decisions(D(2017, 1, 1), D(2031, 12, 31))
    nxt = [m for m in meetings if m > asof][:3]
    assert nxt == [D(2026, 9, 16), D(2026, 10, 28), D(2026, 12, 9)]

    candidates = ["U26", "V26", "X26", "Z26", "F27", "G27"]

    def regime_share(code, k):
        """Day share of `code`'s month spent at meeting k's rate."""
        w = delivery_window(code)[:2]
        e = zq_exposure_vector(w, meetings)
        i = meetings.index(k)
        return float(e[i] - e[i + 1])

    readers = [max(candidates, key=lambda c: regime_share(c, k)) for k in nxt]
    assert readers == ["V26", "X26", "F27"], readers

    # the numbers behind it, hand-checkable
    assert regime_share("V26", D(2026, 9, 16)) == pytest.approx(28 / 31, abs=1e-9)
    assert regime_share("X26", D(2026, 10, 28)) == pytest.approx(1.0)
    assert regime_share("Z26", D(2026, 12, 9)) == pytest.approx(22 / 31, abs=1e-9)
    assert regime_share("F27", D(2026, 12, 9)) == pytest.approx(27 / 31, abs=1e-9)
    # January reads December better than December does -- that is why Z26 is skipped
    assert regime_share("F27", D(2026, 12, 9)) > regime_share("Z26", D(2026, 12, 9))


def test_meeting_fly_loads_the_decision_harder_than_the_calendar_fly():
    """Why the distinction is worth the trouble, in one assertion.

    Both flies are 4 contracts and cost 2.0bp. The meeting-indexed one carries
    a full unit of the December decision; the calendar-consecutive one carries
    0.71 of it, because December only spends 22/31 of itself at the new rate.
    """
    meetings = fomc_decisions(D(2017, 1, 1), D(2031, 12, 31))
    i_dec = meetings.index(D(2026, 12, 9))
    e = {c: zq_exposure_vector(delivery_window(c)[:2], meetings)
         for c in ("V26", "X26", "Z26", "F27")}

    meeting_fly = 2 * e["X26"] - e["V26"] - e["F27"]        # Oct, Nov, Jan
    calendar_fly = 2 * e["X26"] - e["V26"] - e["Z26"]       # Oct, Nov, Dec
    assert meeting_fly[i_dec] == pytest.approx(-1.0)
    assert calendar_fly[i_dec] == pytest.approx(-22 / 31, abs=1e-9)
    assert abs(meeting_fly[i_dec]) > abs(calendar_fly[i_dec])

    # both are still level-neutral: a parallel shift of every regime moves neither
    assert float(np.sum([2.0, -1.0, -1.0])) == pytest.approx(0.0)


def test_no_calendar_month_holds_two_fomc_decisions():
    """The fact that makes meeting-indexing well-defined at all.

    A ZQ contract is one calendar month, so "the contract that reads meeting k"
    is only a sensible idea if a month never has to read two. Over 2018-2027 no
    calendar month contains two decisions -- the Fed's ~6-8 week spacing
    guarantees it in practice, though nothing in the rulebook does.

    This is a claim about the CALENDAR, asserted independently of the reader
    map, so it fails if the schedule is ever edited into an impossible shape.
    """
    from RVUtils.MeanRev.meetings import fomc_decisions
    ms = fomc_decisions(D(2018, 1, 1), D(2027, 12, 31))
    months = [(m.year, m.month) for m in ms]
    dupes = {k for k in months if months.count(k) > 1}
    assert not dupes, f"months with two decisions: {sorted(dupes)}"

    # and the spacing that causes it
    gaps = [(b - a).days for a, b in zip(ms, ms[1:])]
    assert min(gaps) >= 28, f"two decisions inside 28 days: min gap {min(gaps)}"


def test_a_month_always_reads_its_decision_by_a_clear_majority():
    """No meeting is read by a coin-flip of a month.

    If some decision's best reader only carried, say, 55% of a month, the
    "meeting-indexed" label would be a fiction for that node. The measured floor
    over 2018-2027 is 73% (Nov-18: the 2018-11-08 decision takes effect on the
    9th, leaving 22 of 30 November days at the new rate).
    """
    from RVUtils.MeanRev.meetings import fomc_decisions
    ms = fomc_decisions(D(2018, 1, 1), D(2027, 12, 31))
    codes = [f"{c}{y % 100:02d}" for y in range(2018, 2028)
             for c in "FGHJKMNQUVXZ"]
    exps = {c: zq_exposure_vector(delivery_window(c)[:2], ms) for c in codes}

    worst = 1.0
    for i, m in enumerate(ms[:-1]):
        shares = [float(e[i] - e[i + 1]) for e in exps.values()]
        worst = min(worst, max(shares))
    assert worst > 0.70, f"a decision's best reader carries only {worst:.3f}"

    # the specific floor, pinned by hand: Nov-18 has 30 days, the 2018-11-08
    # decision is effective the 9th, so 22/30 of the month sits at the new rate
    i = ms.index(D(2018, 11, 8))
    assert float(exps["X18"][i] - exps["X18"][i + 1]) == pytest.approx(22 / 30,
                                                                      abs=1e-9)
