"""FOMC-specific structure the global study has no room for.

Three things are true of the Fed and of no other committee here, and each gives a
cut the pooled notebook cannot make:

* the committee is large enough that "relative to peers" is a real cross-section
  rather than a rounding error - 26 speakers in this corpus against the BoJ's 12
  and the SNB's 4;
* only some regional presidents vote in a given year, on a fixed rotation, so the
  same speech carries different institutional weight depending on the calendar;
* the meeting calendar is published years ahead, so distance-to-meeting is known
  at trade time and can be tested without any lookahead.
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
#: Board of Governors. Governors vote at EVERY meeting; regional presidents do not.
GOVERNORS = {
    "Powell", "Waller", "Bowman", "Jefferson", "Kugler", "Cook", "Barr",
    "Brainard", "Quarles", "Miran", "Warsh", "Clarida",
}

#: Regional president -> Reserve Bank district.
DISTRICT = {
    "Williams": "New York",
    "Logan": "Dallas", "Kaplan": "Dallas",
    "Collins": "Boston", "Rosengren": "Boston",
    "Harker": "Philadelphia", "Paulson": "Philadelphia",
    "Barkin": "Richmond",
    "Mester": "Cleveland", "Hammack": "Cleveland",
    "Goolsbee": "Chicago", "Evans": "Chicago",
    "Bostic": "Atlanta",
    "Bullard": "St. Louis", "Musalem": "St. Louis",
    "Kashkari": "Minneapolis",
    "George": "Kansas City", "Schmid": "Kansas City",
    "Daly": "San Francisco",
}

#: Chair tenure - the Chair is the committee's median by construction, so it is
#: worth being able to separate them from the rest.
CHAIRS = [("Powell", datetime.date(2018, 2, 5), datetime.date(2026, 5, 21)),
          ("Warsh", datetime.date(2026, 5, 22), datetime.date(2100, 1, 1))]


def role_of(speaker: str, as_of: Optional[datetime.date] = None) -> str:
    if as_of is not None:
        for name, s, e in CHAIRS:
            if speaker == name and s <= as_of <= e:
                return "Chair"
    if speaker in GOVERNORS:
        return "Governor"
    if speaker in DISTRICT:
        return "President (NY)" if DISTRICT[speaker] == "New York" else "President"
    return "Other"


# ---------------------------------------------------------------------------
# Voting rotation
# ---------------------------------------------------------------------------
#: New York votes every year. The other eleven districts rotate in four groups:
#: (Boston, Philadelphia, Richmond), (Cleveland, Chicago),
#: (Atlanta, St. Louis, Dallas), (Minneapolis, Kansas City, San Francisco).
#: This is the published rotation, not an inference.
#:
#: 2019-2020 are included because the hand-labelled book starts in 2019, and an
#: unmapped year returns None from ``is_voter`` — which a voters-only filter reads
#: as "not a voter" and silently drops. They are not extrapolated from the
#: six-year periodicity alone; both check against the actual rosters:
#: 2019 voted Evans (Chicago), Rosengren (Boston), Bullard (St. Louis),
#: George (Kansas City); 2020 voted Mester (Cleveland), Harker (Philadelphia),
#: Kaplan (Dallas), Kashkari (Minneapolis).
VOTING_DISTRICTS: Dict[int, tuple] = {
    2019: ("Chicago", "Boston", "St. Louis", "Kansas City"),
    2020: ("Cleveland", "Philadelphia", "Dallas", "Minneapolis"),
    2021: ("Chicago", "Richmond", "Atlanta", "San Francisco"),
    2022: ("Cleveland", "Boston", "St. Louis", "Kansas City"),
    2023: ("Chicago", "Philadelphia", "Dallas", "Minneapolis"),
    2024: ("Cleveland", "Richmond", "Atlanta", "San Francisco"),
    2025: ("Chicago", "Boston", "St. Louis", "Kansas City"),
    2026: ("Cleveland", "Philadelphia", "Dallas", "Minneapolis"),
}


def is_voter(speaker: str, as_of: datetime.date) -> Optional[bool]:
    """Does this speaker hold a vote in the year of ``as_of``?

    None where we cannot say - an unmapped speaker, or a year outside the
    published rotation - so that 'unknown' never masquerades as 'non-voter'.
    """
    if speaker in GOVERNORS:
        return True
    d = DISTRICT.get(speaker)
    if d is None:
        return None
    if d == "New York":
        return True
    yr = VOTING_DISTRICTS.get(as_of.year)
    if yr is None:
        return None
    return d in yr


# ---------------------------------------------------------------------------
# Meeting calendar
# ---------------------------------------------------------------------------
def fomc_decision_dates(curve_id: str = "USD-FEDFUNDS") -> List[datetime.date]:
    from Query.IRSwaps._CENTRAL_BANK_DATES import central_bank_date_map
    out = set()
    for eff, _mat in central_bank_date_map(curve_id).values():
        out.add(eff.date() if isinstance(eff, datetime.datetime) else eff)
    return sorted(out)


def days_to_next_meeting(as_of: datetime.date, meetings: List[datetime.date]) -> Optional[int]:
    nxt = [m for m in meetings if m >= as_of]
    return (nxt[0] - as_of).days if nxt else None


def days_since_last_meeting(as_of: datetime.date, meetings: List[datetime.date]) -> Optional[int]:
    prev = [m for m in meetings if m <= as_of]
    return (as_of - prev[-1]).days if prev else None


def annotate(df: pd.DataFrame, speaker_col: str = "speaker",
             date_col: str = "opened_at") -> pd.DataFrame:
    """Attach role / voter / meeting-distance columns to a trade log."""
    meetings = fomc_decision_dates()
    out = df.copy()
    d = pd.to_datetime(out[date_col]).dt.date
    out["role"] = [role_of(s, dt) for s, dt in zip(out[speaker_col], d)]
    out["district"] = out[speaker_col].map(DISTRICT).fillna("-")
    out["is_voter"] = [is_voter(s, dt) for s, dt in zip(out[speaker_col], d)]
    out["days_to_fomc"] = [days_to_next_meeting(dt, meetings) for dt in d]
    out["days_since_fomc"] = [days_since_last_meeting(dt, meetings) for dt in d]
    # the inter-meeting cycle is ~45 days; thirds of it are a natural split
    out["cycle_phase"] = pd.cut(
        out["days_since_fomc"], bins=[-1, 14, 30, 999],
        labels=["0-14d after", "15-30d after", "30d+ / pre-meeting"])
    return out
