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


@dataclasses.dataclass(frozen=True)
class CitiUsdSession:
    """The measured USD publication schedule. See the module docstring."""

    #: Weekly open, on a UTC clock.
    open_weekday_utc: int = 6            # Sunday
    open_minute_utc: int = 21 * 60       # 21:00 UTC

    #: Weekly close, on a UTC clock. The last row seen is 21:59 UTC.
    close_weekday_utc: int = 4           # Friday
    close_minute_utc: int = 22 * 60      # exclusive

    #: Nightly gap, on a NEW YORK clock: no rows at or after 23:00 ET, none
    #: before 01:00 ET. Expressed in wall-clock ET so it is DST-correct by
    #: construction rather than by a UTC offset that would drift twice a year.
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

    def bounds_for_local_date(
        self, day: datetime.date
    ) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
        """First and last publishable minute of one ET calendar date, or ``None``.

        ``None`` for a date with no session at all (Saturday, and the part of
        Sunday before the weekly open is handled by the later open time).
        """
        first = pd.Timestamp(
            datetime.datetime.combine(day, datetime.time(1, 0)), tz=ET
        )
        last = pd.Timestamp(
            datetime.datetime.combine(day, datetime.time(22, 59)), tz=ET
        )
        # Walk in from each end rather than reasoning about which rule bit: the
        # weekly bounds are UTC-anchored and the daily ones ET-anchored, so the
        # first publishable minute of a Sunday is not a fixed ET wall clock.
        cur = first
        while cur <= last and not self.publishes(cur):
            cur += pd.Timedelta(minutes=1)
        if cur > last:
            return None
        end = last
        while end >= cur and not self.publishes(end):
            end -= pd.Timedelta(minutes=1)
        return cur, end

    def expected_minutes(self, day: datetime.date) -> int:
        """How many minutes Citi should publish on this ET calendar date."""
        b = self.bounds_for_local_date(day)
        if b is None:
            return 0
        first, last = b
        return sum(
            1
            for t in pd.date_range(first, last, freq="1min")
            if self.publishes(t)
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


def publishes(curve_name: str, instant: Any) -> bool:
    """Could Citi have published ``curve_name`` at ``instant``?

    A ``False`` here means no fetch will ever supply that minute. Contrast
    ``density.DayDensity.covers``, which reports only what the store holds.
    """
    return _require_usd(curve_name).publishes(instant)


def expected_minutes(curve_name: str, day: datetime.date) -> int:
    """Publishable minutes on one ET calendar date - the denominator for coverage."""
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
    b = session.bounds_for_local_date(day)
    if b is None:
        return False
    ts = pd.Timestamp(last_stored)
    if ts.tzinfo is None:
        raise ValueError("is_truncated() needs a tz-aware last_stored")
    return (b[1] - ts.tz_convert("UTC")) > tolerance
