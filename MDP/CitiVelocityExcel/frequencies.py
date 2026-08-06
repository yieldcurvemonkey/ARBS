r"""Frequency, period and price-point handling for ``CVTSHIST``.

Two things this module is careful about.

**The frequency vocabulary is closed and small.** ``MI01 MI10 HOURLY DAILY
WEEKLY MONTHLY`` and nothing else - see :mod:`MDP.CitiVelocityExcel.excel_constants`.
In particular ``SE10`` describes the streaming feed, not historical retrieval, and
``CVTSHIST`` rejects it outright. One minute is the finest historical granularity
for every family, so there is no sub-minute code path anywhere in this package.

**Intraday capability is per-family and the desk's map is incomplete.**
``Velocity_Charting_Intraday_Tags.xlsx`` maps a tag regex to intraday capability,
but ``RATES.BOND`` is absent from it and *is* intraday-capable (measured
2026-08-05: 1,564 one-minute rows over two days against a 2,291-row
known-intraday control, and 65 hourly rows against 70; the shortfall is liquidity,
not capability). So :func:`intraday_capability` returns ``None`` - "unknown" -
for a tag the map does not cover, and callers must not read that as "no".
"""

from __future__ import annotations

import datetime
import re
from typing import Iterable, Optional, Sequence, Union

from MDP.CitiVelocityExcel.errors import FrequencyError
from MDP.CitiVelocityExcel.excel_constants import (
    FREQUENCIES,
    INTRADAY_FREQUENCIES,
    PRICE_POINTS,
)

__all__ = [
    "normalise_frequency",
    "normalise_price_point",
    "is_intraday",
    "format_bound",
    "normalise_period",
    "intraday_capability",
    "supports_ohlc",
    "DateLike",
]

DateLike = Union[datetime.date, datetime.datetime, str]

_PERIOD_RE = re.compile(r"^\d+[DWMY]$", re.IGNORECASE)


def normalise_frequency(freq: str) -> str:
    """Upper-case and validate a ``CVTSHIST`` frequency.

    Raises
    ------
    FrequencyError
        With the exact accepted set, and with a specific hint for ``SE10`` -
        the one wrong answer a reader of the desk's intraday workbook will
        reach for.
    """
    token = str(freq or "").strip().upper()
    if token in FREQUENCIES:
        return token
    hint = ""
    if token in {"SE10", "S10", "SECONDLY", "TEN_SECONDLY"}:
        hint = (
            " SE10 is the STREAMING granularity (CVSTREAM), not a CVTSHIST frequency; "
            "one minute (MI01) is the finest historical granularity for every family."
        )
    raise FrequencyError(
        f"Unsupported CVTSHIST frequency {freq!r}. Must be one of {', '.join(FREQUENCIES)}.{hint}"
    )


def normalise_price_point(price_point: str) -> str:
    """Upper-case and validate a ``PricePoint``."""
    token = str(price_point or "").strip().upper()
    if token in PRICE_POINTS:
        return token
    raise FrequencyError(
        f"Unsupported PricePoint {price_point!r}. Must be one of {', '.join(PRICE_POINTS)}."
    )


def is_intraday(freq: str) -> bool:
    """True when ``freq`` yields more than one observation per day."""
    return normalise_frequency(freq) in INTRADAY_FREQUENCIES


def format_bound(when: Optional[DateLike], *, freq: str) -> str:
    """Format a start/end bound the way the add-in's date parameters expect.

    Intraday frequencies get ``yyyyMMddHHmm`` (the form the add-in's own saved
    functions and ``CVSNAP`` use, e.g. ``202608010900``); daily and coarser get
    ``yyyyMMdd``. An empty bound formats to ``""`` so it can be spliced into the
    formula as an omitted argument.

    .. note::
       **Confirmed live 2026-08-05.** ``start=2026-07-22, end=2026-08-05`` on
       ``RATES.OIS.USD_SOFR.PAR.10Y`` returned exactly 11 daily rows spanning
       2026-07-22..2026-08-05, i.e. ``CVTSHIST`` honours the ``yyyyMMdd`` form on
       its ``StartDate``/``EndDate`` parameters. The intraday
       ``yyyyMMddHHmm`` form is still inferred from the add-in's own saved
       functions and from ``CVSNAP`` rather than measured.
    """
    if when is None:
        return ""
    if isinstance(when, str):
        text = when.strip()
        if not text:
            return ""
        if text.isdigit() and len(text) in (8, 12):
            return text
        when = datetime.datetime.fromisoformat(text)
    if isinstance(when, datetime.datetime):
        return when.strftime("%Y%m%d%H%M") if is_intraday(freq) else when.strftime("%Y%m%d")
    if isinstance(when, datetime.date):
        return when.strftime("%Y%m%d0000") if is_intraday(freq) else when.strftime("%Y%m%d")
    raise TypeError(f"Unsupported bound type for CVTSHIST: {type(when)!r}")


def normalise_period(period: Optional[str]) -> str:
    """Validate a relative period such as ``'1W'``, ``'6M'``, ``'5Y'``."""
    if period is None:
        return ""
    token = str(period).strip().upper()
    if not token:
        return ""
    if not _PERIOD_RE.match(token):
        raise FrequencyError(
            f"Unsupported CVTSHIST period {period!r}; expected <n><D|W|M|Y>, e.g. '1W', '6M', '5Y'."
        )
    return token


# ------------------------------------------------------------------ #
#           per-family intraday capability (the desk's map)           #
# ------------------------------------------------------------------ #

#: ``(regex, intraday_ok, intraday_ohlc, eod_ohlc, streaming)`` transcribed from
#: ``Velocity_Charting_Intraday_Tags.xlsx``. The workbook's "finest" column
#: (``SE10`` for OIS and TSY.OTR) is deliberately NOT represented: it describes
#: ``CVSTREAM``, and ``CVTSHIST`` rejects ``SE10``.
_INTRADAY_MAP: Sequence[tuple[re.Pattern[str], bool, bool, bool, bool]] = (
    (re.compile(r"^RATES\.FUTURES\."), True, True, True, True),
    (re.compile(r"^RATES\.OIS\."), True, False, False, True),
    (re.compile(r"^RATES\.TSY\.TSY\.OTR\."), True, False, False, True),
    (re.compile(r"^RATES\.SOV\..*\.OTR"), True, False, False, True),
    (re.compile(r"^RATES\.(SWAP_LIBOR|SWAP_INTERNAL)\..*\.(PAR|FWD)\."), True, False, False, True),
    (
        re.compile(r"^RATES\.(SWAP_LIBOR|SWAP_INTERNAL)\..*\.(SWAP_SPREAD|CURVES|BFLY)\."),
        True,
        False,
        False,
        False,
    ),
    (re.compile(r"^RATES\.SOV\..*\.(CURVES|BFLY)"), True, False, False, False),
    (re.compile(r"^RATES\.VOL\..*\.ANNUAL\."), True, False, False, True),
    (re.compile(r"^RATES\.VOL\..*\.DAILY\."), True, False, False, False),
    # Absent from the desk's workbook, but measured intraday-capable on
    # 2026-08-05 against a known-intraday control in the same window.
    (re.compile(r"^RATES\.BOND\."), True, False, False, False),
)


def intraday_capability(tag: str) -> Optional[bool]:
    """Whether ``tag``'s family serves intraday history.

    Returns ``True``/``False`` when the desk's map (or our own measurement)
    covers the tag, and ``None`` when it does not. **``None`` means unknown, not
    "no"** - ``RATES.BOND`` was absent from the map and turned out to be fully
    intraday-capable. Callers should attempt the request and let the add-in
    answer rather than pre-emptively refusing.
    """
    text = str(tag or "").strip()
    for pattern, intraday_ok, _iohlc, _eohlc, _stream in _INTRADAY_MAP:
        if pattern.search(text):
            return intraday_ok
    return None


def supports_ohlc(tag: str) -> Optional[bool]:
    """Whether ``PricePoint='OHLC'`` is meaningful for ``tag``.

    In the rates complex only ``RATES.FUTURES`` carries OHLC. ``None`` means the
    map does not cover the tag.
    """
    text = str(tag or "").strip()
    for pattern, _intraday_ok, intraday_ohlc, eod_ohlc, _stream in _INTRADAY_MAP:
        if pattern.search(text):
            return bool(intraday_ohlc or eod_ohlc)
    return None


def unknown_intraday_tags(tags: Iterable[str]) -> list[str]:
    """Tags whose intraday capability the desk's map does not cover."""
    return [t for t in tags if intraday_capability(t) is None]
