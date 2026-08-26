"""Shared helpers for the point-in-time label build.

Quarter helpers are lifted verbatim from _event_study/zz_manual_label_lag.py so the
flattened (speaker, quarter) -> stance map is byte-identical to the one the existing
lag test uses; r2_build.py asserts that reconciliation.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import re

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# quarter helpers  (from zz_manual_label_lag.py)
# --------------------------------------------------------------------------- #


def qseq(a, b):
    """every 'YYYYQn' from a to b inclusive"""
    y, n = int(a[:4]), int(a[-1])
    Y, N = int(b[:4]), int(b[-1])
    out = []
    while (y, n) <= (Y, N):
        out.append(f"{y}Q{n}")
        n += 1
        if n == 5:
            y, n = y + 1, 1
    return out


def qkey(ts):
    ts = pd.Timestamp(ts)
    return f"{ts.year}Q{(ts.month - 1)//3 + 1}"


def qprev(q):
    y, n = int(q[:4]), int(q[-1])
    return f"{y-1}Q4" if n == 1 else f"{y}Q{n-1}"


def qshift(q, k):
    """q shifted back by k quarters (k>0 = earlier)."""
    for _ in range(k):
        q = qprev(q)
    return q


def qstart(q) -> _dt.date:
    """first calendar day of quarter 'YYYYQn'"""
    y, n = int(q[:4]), int(q[-1])
    return _dt.date(y, 3 * (n - 1) + 1, 1)


def to_num(v):
    """stance -> float, tolerating the markdown glyphs"""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    return {"HH": 2.0, "H": 1.0, "·": 0.0, ".": 0.0, "": np.nan,
            "D": -1.0, "DD": -2.0}.get(s, np.nan)


# --------------------------------------------------------------------------- #
# evidence-date parser  (L1)
# --------------------------------------------------------------------------- #
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"


def _mnum(tok: str) -> int:
    return _MONTHS[tok[:3].lower()]


def _month_end(y: int, m: int) -> _dt.date:
    return _dt.date(y, m, calendar.monthrange(y, m)[1])


# Patterns are consumed IN ORDER; each match is blanked out before the next runs,
# so "14 Dec 2022" is read once as a day-precision date and not again as "Dec 2022".
_PATTERNS = [
    # 1. day precision: "14 Dec 2022", "2 Aug 2021", "19 Mar 2025"
    ("day", re.compile(rf"\b(\d{{1,2}})\s+({MON})\s+((?:19|20)\d{{2}})\b")),
    # 2. US day precision: "January 14, 2022"   (zero found in this corpus, kept for safety)
    ("day_us", re.compile(rf"\b({MON})\s+(\d{{1,2}}),\s*((?:19|20)\d{{2}})\b")),
    # 3. multi-month: "Sep/Oct/Dec 2025"
    ("multi", re.compile(rf"\b({MON}(?:\s*/\s*{MON})+)[\s-]((?:19|20)\d{{2}})\b")),
    # 4. month precision: "Aug-2022", "Aug 2022", "April 2024"
    ("month", re.compile(rf"\b({MON})[-\s]((?:19|20)\d{{2}})\b")),
]

#: month names still present after the four patterns above are consumed - a token
#: whose YEAR is only implied by prose ("27 Jul", "the September dots").  Counted,
#: never resolved: see the leakage argument in the report.
_LEFTOVER_MON = re.compile(rf"\b{MON}\b")


def parse_evidence_dates(why: str):
    """-> (dates, n_unresolved_month_tokens)

    ``dates`` is a sorted list of datetime.date.  AMBIGUITY IS ALWAYS RESOLVED
    AGAINST AVAILABILITY: a month-precision token becomes the LAST day of that
    month, so it can never manufacture availability at a quarter boundary that a
    day-precision reading would deny.  Bare years ("2022") and grid self-references
    ("2026Q2") are excluded entirely - adding a token to a min() can only create
    availability, so exclusion is the conservative side.
    """
    if not why:
        return [], 0
    txt = str(why)
    out = []

    for kind, rx in _PATTERNS:
        def _sub(m):
            if kind == "day":
                d, mon, y = int(m.group(1)), _mnum(m.group(2)), int(m.group(3))
                try:
                    out.append(_dt.date(y, mon, d))
                except ValueError:            # impossible day -> month end, conservative
                    out.append(_month_end(y, mon))
            elif kind == "day_us":
                mon, d, y = _mnum(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    out.append(_dt.date(y, mon, d))
                except ValueError:
                    out.append(_month_end(y, mon))
            elif kind == "multi":
                y = int(m.group(2))
                for tok in re.split(r"\s*/\s*", m.group(1)):
                    out.append(_month_end(y, _mnum(tok)))
            else:                              # month precision
                out.append(_month_end(int(m.group(2)), _mnum(m.group(1))))
            return " " * len(m.group(0))
        txt = rx.sub(_sub, txt)

    # strip the grid self-references so they are not miscounted as month tokens
    txt = re.sub(r"\b20\d{2}Q[1-4]\b", " ", txt)
    n_unresolved = len(_LEFTOVER_MON.findall(txt))
    return sorted(out), n_unresolved


def qend_date(q) -> _dt.date:
    """last calendar day of quarter 'YYYYQn'"""
    y, n = int(q[:4]), int(q[-1])
    m = 3 * n
    return _month_end(y, m)
