r"""When Citi Velocity publishes an intraday curve at all.

Why this is separate from ``density``
------------------------------------
``DayDensity.covers`` answers "does the **stored** day reach this instant". That
cannot distinguish the two reasons an answer is missing:

* Citi never published that minute - no fetch will ever produce it; and
* Citi published it and we did not fetch it - a re-fetch recovers it.

For dealer-direction work those are completely different findings. The first is
a hard limit on which prints can be classified at all; the second is a backlog.
Conflating them is what made an earlier version of the fidelity report claim
that fixing the fetch would remove most of the hour-00 contamination. It would
remove **12.6 %** of it: see the measurement below.

The USD session, measured
-------------------------
Measured 2026-08-10 over 815 stored days of ``USD-SOFR-1D-CITIVELOEXCELMIN`` and
794 of ``USD-FEDFUNDS-1D-CITIVELOEXCELMIN`` (2024 onward, the one-minute era),
split by DST regime so the anchoring of each boundary is established rather than
assumed:

===================  =====================  =====================  ===========
boundary             EDT (Jun-Aug)          EST (Dec-Feb)          anchored in
===================  =====================  =====================  ===========
first row, Mon-Thu   01:00 ET = 05:00 UTC   01:00 ET = 06:00 UTC   **ET**
last row, Mon-Thu    22:59 ET = 02:59 UTC   22:59 ET = 03:59 UTC   **ET**
last row, Friday     17:59 ET = 21:59 UTC   16:59 ET = 21:59 UTC   **UTC**
first row, Sunday    17:00 ET = 21:00 UTC   16:00 ET = 21:00 UTC   **UTC**
===================  =====================  =====================  ===========

138/144 and 138/140 Mon-Thu days respectively start at exactly 01:00 ET; 33/36
and 34/34 Fridays end at exactly 21:59 UTC; 36/36 and 32/33 Sundays start at
exactly 21:00 UTC. So the **week** runs on a UTC clock and the **day** runs on a
New York clock, and neither is a guess.

That gives a continuous Sunday-to-Friday session with a two-hour hole every
night:

* opens **Sunday 21:00 UTC**, closes **Friday 22:00 UTC** (last row 21:59);
* **no rows between 23:00 and 00:59 ET**, any night;
* nothing at all on Saturday.

The daily window changed once, and the model carries both
---------------------------------------------------------
Everything above is the session **from 2022-06-06**. Before that Citi published
a full 24 hours on a weekday: 00:00 to 23:58 ET, 1,439 rows, no nightly hole.
Measured on 810 Mon-Thu fetched days spanning 2021-06 .. 2023-06 - **no month
mixes the two shapes**; the last 24-hour day is 2022-06-03 (Fri) and the first
narrowed one 2022-06-06 (Mon), with only a weekend between.

The **weekly** frame is identical either side of that change - Sunday 21:00 UTC
open, Friday 22:00 UTC close, no Saturday - which is why one dataclass with two
daily settings covers it rather than two unrelated models.

This matters more than a historical footnote: 241 of the 459 truncated Fed Funds
days are pre-2022, and against a 24-hour session they are missing four to five
hours rather than three. A model fixed at 01:00-22:59 reports those days as
*more complete than they are*, which is the direction that hides work.

``publishes`` and ``expected_minutes`` resolve the era from the date. Anything
before **2017-12-05**, the earliest day ever fetched, raises rather than
guessing.

**US holidays publish normally.** Checked on eighteen of them - 2024-12-25,
2025-01-01, 2025-12-25 and 2026-01-01 all hold full 1,318-1,320 row days running
01:00-22:59 ET, indistinguishable from the controls. There is no holiday
calendar in this model because the data does not have one.

What is *not* claimed here
--------------------------
Only the two USD curves were measured this way. The other minute assets show a
clean 08:00-19:59 in their **own** local zone (GBP-SONIA 105/105 days, and the
same for EUR-ESTR, JPY-TONAR, CAD-CORRA on a 40-day sample), which is a
different and much shorter session - but their weekend edges, holidays and DST
transitions were not examined. :func:`publishes` therefore refuses any curve it
has not been shown to model, rather than extrapolating the USD anatomy onto a
curve whose anatomy is known to differ.

Distinguishing a truncated day from a short one
-----------------------------------------------
Roughly 19 % of Mon-Thu days in the store end at 23:59 UTC (19:59 ET on EDT,
18:59 ET on EST) instead of 22:59 ET. That is **our** boundary, not Citi's: the
count is 27/144 and 27/140 across the two DST regimes - identical in a UTC clock
and impossible for a market event - and on 190 dates one USD curve stops early
while the other, fetched in a separate run, runs to 22:59. :func:`is_truncated`
detects it.

Note this is exactly where a short day and a truncated day are confusable:
Friday genuinely ends at 21:59 UTC, and a Sunday genuinely starts at 21:00 UTC.
Judging "complete" by a row count, or by treating 19:59 as a normal weekday
close, marks the truncated days complete and the honest short days broken.
"""
from __future__ import annotations

import dataclasses
import datetime
import zoneinfo
from typing import Any, Optional

import pandas as pd

__all__ = [
    "CITI_USD_SESSION",
    "CitiUsdSession",
    "publishes",
    "expected_minutes",
    "is_truncated",
    "UnknownSessionError",
]

ET = zoneinfo.ZoneInfo("America/New_York")

#: Curves whose session anatomy has actually been measured here.
MODELLED_CURVES = ("USD-SOFR-1D", "USD-FEDFUNDS-1D")


class UnknownSessionError(LookupError):
    """No measured session model for this curve.

    Deliberately an error rather than a default. The USD session is 22 hours a
    day across a UTC-anchored week; every other Citi curve measured is 12 hours
    a day in its own local zone. Extrapolating one onto the other would produce
    a confident wrong answer about which minutes are missing - which is the
    exact mistake this module exists to prevent.
    """


#: The day Citi narrowed the USD session. Before it, the feed ran a full
#: 24 hours on a weekday; from it, 01:00-22:59 ET with a two-hour nightly hole.
#: Measured on 810 Mon-Thu fetched days spanning 2021-06 .. 2023-06: **no month
#: mixes the two shapes**. The last 24-hour day observed is 2022-06-03 (Fri) and
#: the first narrowed one is 2022-06-06 (Mon), with only a weekend between.
SESSION_NARROWED_ON = datetime.date(2022, 6, 6)

#: Earliest date any of this was measured against - the first fetched day in the
#: work directory. Asking about anything earlier gets an error, not a guess.
MEASURED_FROM = datetime.date(2017, 12, 5)



def _et_wall_clock(day: datetime.date, minute_of_day: int) -> pd.Timestamp:
    """``day`` at ``minute_of_day`` ET, as a wall clock rather than an offset.

    ``nonexistent="shift_forward"`` and ``ambiguous=True`` are here for the two
    hours a year that do not exist or exist twice. Neither currently falls
    inside a session bound - the transitions are at 02:00 ET and the bounds are
    00:00, 01:00, 22:59 and 23:59 - but a bound that raises once a year inside a
    coverage report is not a failure anyone would enjoy diagnosing.
    """
    naive = datetime.datetime.combine(day, datetime.time(0, 0)) + datetime.timedelta(
        minutes=int(minute_of_day)
    )
    return pd.Timestamp(naive).tz_localize(ET, ambiguous=True, nonexistent="shift_forward")


@dataclasses.dataclass(frozen=True)
class CitiUsdSession:
    """The measured USD publication schedule. See the module docstring.

    The **weekly** frame is identical in both eras - Sunday 21:00 UTC open,
    Friday 22:00 UTC close, no Saturday - and only the **daily** window moved.
    That is worth stating because it is what makes one dataclass with two daily
    settings sufficient, rather than two unrelated models.
    """

    #: Weekly open, on a UTC clock.
    open_weekday_utc: int = 6            # Sunday
    open_minute_utc: int = 21 * 60       # 21:00 UTC

    #: Weekly close, on a UTC clock. The last row seen is 21:59 UTC.
    close_weekday_utc: int = 4           # Friday
    close_minute_utc: int = 22 * 60      # exclusive

    #: Daily window, on a NEW YORK clock. Expressed in wall-clock ET so it is
    #: DST-correct by construction rather than by a UTC offset that would drift
    #: twice a year. The defaults are the CURRENT era; see :func:`session_for`.
    day_open_minute_et: int = 60         # 01:00 ET, inclusive
    day_close_minute_et: int = 22 * 60 + 59   # 22:59 ET, inclusive

    def publishes(self, instant: Any) -> bool:
        """Could Citi have published a USD curve at this instant?

        Inclusive at both edges: 01:00 ET and 22:59 ET are published minutes, so
        the nightly hole is [23:00, 00:59] ET inclusive.
        """
        ts = pd.Timestamp(instant)
        if ts.tzinfo is None:
            raise ValueError(
                "publishes() needs a tz-aware instant. A naive one has no defined "
                "position relative to a session anchored in two different zones."
            )
        utc = ts.tz_convert("UTC")
        wd = utc.weekday()
        hm_utc = utc.hour * 60 + utc.minute
        if wd == 5:                                             # Saturday UTC
            return False
        if wd == self.open_weekday_utc and hm_utc < self.open_minute_utc:
            return False
        if wd == self.close_weekday_utc and hm_utc >= self.close_minute_utc:
            return False

        et = ts.tz_convert(ET)
        hm_et = et.hour * 60 + et.minute
        return self.day_open_minute_et <= hm_et <= self.day_close_minute_et

    def for_date(self, day: datetime.date) -> "CitiUsdSession":
        """This session's daily window as it stood on ``day``.

        The weekly frame is shared, so only the two daily bounds move.
        """
        if day >= SESSION_NARROWED_ON:
            return self
        return dataclasses.replace(
            self, day_open_minute_et=0, day_close_minute_et=23 * 60 + 59
        )

    def bounds_for_local_date(
        self, day: datetime.date
    ) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
        """First and last publishable minute of one ET calendar date, or ``None``.

        ``None`` for a date with no session at all (Saturday, and the part of
        Sunday before the weekly open is handled by the later open time).
        """
        era = self.for_date(day)
        # Built as WALL CLOCK times, not as midnight-plus-N-minutes. On a
        # fall-back Sunday the ET day is 25 hours long, so adding 1,439 minutes
        # to midnight lands on 22:59, not 23:59 - which silently shortened the
        # expected count by exactly the repeated hour. Caught by validating
        # expected_minutes against 2,498 fetched days: every DST-transition
        # Sunday came out 60 short.
        first = _et_wall_clock(day, era.day_open_minute_et)
        last = _et_wall_clock(day, era.day_close_minute_et)
        # Walk in from each end rather than reasoning about which rule bit: the
        # weekly bounds are UTC-anchored and the daily ones ET-anchored, so the
        # first publishable minute of a Sunday is not a fixed ET wall clock.
        cur = first
        while cur <= last and not era.publishes(cur):
            cur += pd.Timedelta(minutes=1)
        if cur > last:
            return None
        end = last
        while end >= cur and not era.publishes(end):
            end -= pd.Timedelta(minutes=1)
        return cur, end

    def expected_minutes(self, day: datetime.date) -> int:
        """How many minutes Citi should publish on this ET calendar date."""
        b = self.bounds_for_local_date(day)
        if b is None:
            return 0
        era = self.for_date(day)
        first, last = b
        return sum(
            1
            for t in pd.date_range(first, last, freq="1min")
            if era.publishes(t)
        )


CITI_USD_SESSION = CitiUsdSession()


def _require_usd(curve_name: str) -> CitiUsdSession:
    if curve_name not in MODELLED_CURVES:
        raise UnknownSessionError(
            f"No measured Citi session model for {curve_name!r}. Modelled: "
            f"{list(MODELLED_CURVES)}. The non-USD minute assets run a 12-hour "
            "08:00-19:59 session in their OWN local zone, whose weekend and DST "
            "edges were not measured - see MDP/IRSwaps/CITIVELO_EXCEL/citi_session.py."
        )
    return CITI_USD_SESSION


def _require_measured(day: datetime.date) -> None:
    """Refuse a date older than anything this model was measured against.

    The first fetched day in the work directory is 2017-12-05. Answering for
    1998 would be a guess dressed as a measurement, and this module's whole
    purpose is telling "Citi published nothing" apart from "we did not fetch
    it" - an answer that is itself a guess cannot do that.
    """
    if day < MEASURED_FROM:
        raise UnknownSessionError(
            f"{day} predates anything this session model was measured against "
            f"({MEASURED_FROM}). Extend the measurement before asking."
        )


def publishes(curve_name: str, instant: Any) -> bool:
    """Could Citi have published ``curve_name`` at ``instant``?

    A ``False`` here means no fetch will ever supply that minute. Contrast
    ``density.DayDensity.covers``, which reports only what the store holds.

    Era-resolved on the instant's own ET date, because the daily window narrowed
    on 2022-06-06 and a single fixed window answers half the history wrongly.
    """
    session = _require_usd(curve_name)
    ts = pd.Timestamp(instant)
    if ts.tzinfo is None:
        raise ValueError(
            "publishes() needs a tz-aware instant. A naive one has no defined "
            "position relative to a session anchored in two different zones."
        )
    day = ts.tz_convert(ET).date()
    _require_measured(day)
    return session.for_date(day).publishes(ts)


def expected_minutes(curve_name: str, day: datetime.date) -> int:
    """Publishable minutes on one ET calendar date - the denominator for coverage."""
    _require_measured(day)
    return _require_usd(curve_name).expected_minutes(day)


def is_truncated(
    curve_name: str,
    day: datetime.date,
    last_stored: Any,
    *,
    tolerance: datetime.timedelta = datetime.timedelta(minutes=2),
) -> bool:
    """Does this stored day stop materially before Citi stopped publishing?

    The signature to catch is a day ending at **23:59 UTC** - 19:59 ET on
    daylight time, 18:59 ET on standard time - which is a chunk boundary in a
    UTC clock, not a market close. The comparison is against the session's own
    end for that date, so Friday's genuine 21:59 UTC close and Sunday's late
    open do not register.
    """
    session = _require_usd(curve_name)
    _require_measured(day)
    b = session.bounds_for_local_date(day)
    if b is None:
        return False
    ts = pd.Timestamp(last_stored)
    if ts.tzinfo is None:
        raise ValueError("is_truncated() needs a tz-aware last_stored")
    return (b[1] - ts.tz_convert("UTC")) > tolerance
