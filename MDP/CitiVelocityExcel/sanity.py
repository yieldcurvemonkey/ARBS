r"""Per-family plausibility bands for Citi Velocity tag values.

Why this exists, and why it is a band per FAMILY rather than one global rule
---------------------------------------------------------------------------
The tag cache served swaption normal volatility under the OIS par-rate tags for
years: ``RATES.OIS.USD_SOFR.PAR.2Y`` returned ~102 on a day the 2y SOFR OIS was
4.24%. The values were interleaved with good ones, so the series still PLOTTED as
a plausible line and only ever failed a value check - never a shape check.

A single global band cannot express that, because 76.5 is impossible for a par
rate in percent and completely ordinary for a normal vol in basis points. The
unit is a property of the tag family, so the band has to be too.

What a band is for, and what it is not
--------------------------------------
This is the day-one net, not the fix. The fix is that a block parse cannot read a
foreign block's rows (:func:`~MDP.CitiVelocityExcel.block_parser.parse_tshist_block`)
and that a fetcher cannot bank a tag it was not asked for
(:meth:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache.get`). A value check only
catches the cases where the wrong number happens to be far away, which is why it
is the last line rather than the first.

Bands are therefore deliberately WIDE - roughly twice the widest value the family
has ever legitimately printed - so the guard fires on a units error and never on
a market. An unknown family gets ``None`` and no opinion at all: a guard that
guessed a band would block real data, which is a worse failure than the one it
would prevent.

Escape hatch
------------
``ARBS_CITIVELO_SANITY=off`` disables the gate for a process. It exists for a
repair run that has to write a series the gate would refuse, and for nothing
else; it is read at CALL time so a test can set and unset it.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional, Tuple

import pandas as pd

_logger = logging.getLogger(__name__)

__all__ = [
    "TagSanityError",
    "band_for_tag",
    "implausible_rows",
    "assert_plausible",
    "sanity_enabled",
]


class TagSanityError(ValueError):
    """A series holds values its tag family cannot take."""


#: ``(compiled pattern, (low, high), what the numbers mean)``, first match wins.
#:
#: ``RATES.OIS.<index>.PAR.<tenor>`` and its LIBOR sibling are quoted in PERCENT.
#: The widest legitimate print across the 20 curves the catalog carries is MXN
#: T_FONDEO and ZAR ZARONIA in the low teens; JPY and CHF go negative. ±2x that
#: is (-5, 25), which still excludes every USD normal vol ever quoted (the
#: poisoned values ran 37 to 165).
#:
#: ``RATES.VOL.*`` NORMAL branches are quoted in BASIS POINTS - the one number
#: that made the poison legible in the first place - so their band is the bp one.
_BANDS: Tuple[Tuple[re.Pattern, Tuple[float, float], str], ...] = (
    (
        re.compile(r"^RATES\.(OIS|SWAP_LIBOR|SWAP_RFR)\.[^.]+\.PAR\.", re.I),
        (-5.0, 25.0),
        "an OIS/swap par rate in percent",
    ),
    (
        re.compile(r"^RATES\.OIS_MEETING\.", re.I),
        (-5.0, 25.0),
        "a meeting-priced OIS rate in percent",
    ),
    (
        re.compile(r"^RATES\.VOL\.[^.]+\.[^.]*(ATM|OTM)[^.]*\.NORMAL", re.I),
        (-500.0, 2000.0),
        "a normal volatility in basis points",
    ),
    # A government-bond yield in percent. Same band as a par rate and for the
    # same reason: the widest legitimate print across the currencies this cache
    # carries is low double digits, and the poisoned values ran 25 to 690.
    (
        re.compile(r"^RATES\.BOND\.[^.]+\.(YIELD|YTM)$", re.I),
        (-5.0, 25.0),
        "a bond yield in percent",
    ),
)

#: Families whose unit is unambiguous but whose RANGE overlaps the poison, so a
#: band cannot separate them. Listed rather than banded on purpose: a bond price
#: of 89.9 is perfectly ordinary AND is exactly what a normal vol of 89.9bp looks
#: like once it lands in the wrong column. Only an exact match to the donor
#: series settles those, which is what the repair tool's tier 2 does.
UNBANDABLE_BUT_POISONABLE = (
    re.compile(r"^RATES\.BOND\.[^.]+\.(PRICE|DIRTY_PRICE)$", re.I),
)


def sanity_enabled() -> bool:
    """False when ``ARBS_CITIVELO_SANITY`` is set to ``off``/``0``/``false``."""
    raw = str(os.environ.get("ARBS_CITIVELO_SANITY", "")).strip().lower()
    return raw not in {"off", "0", "false", "no"}


def band_for_tag(tag: str) -> Optional[Tuple[float, float]]:
    """``(low, high)`` the family may take, or ``None`` when we have no opinion."""
    text = str(tag).strip()
    for pattern, band, _what in _BANDS:
        if pattern.match(text):
            return band
    return None


def _describe(tag: str) -> str:
    text = str(tag).strip()
    for pattern, _band, what in _BANDS:
        if pattern.match(text):
            return what
    return "this tag"


def implausible_rows(tag: str, series: pd.Series) -> pd.Series:
    """The rows of ``series`` outside the tag family's band.

    An empty series comes back for a family with no band, so a caller can treat
    "nothing to say" and "nothing wrong" the same way.
    """
    band = band_for_tag(tag)
    if band is None or series is None or len(series) == 0:
        return pd.Series(dtype="float64")
    values = pd.to_numeric(series, errors="coerce")
    lo, hi = band
    mask = (values < lo) | (values > hi)
    return series[mask.fillna(False)]


#: How much of a series must be out of band before the write is refused.
#:
#: MEASURED, and the two populations do not overlap. A poisoned series is a
#: DIFFERENT series: the smallest poison event in this cache was 2,687 of 41,415
#: MI01 bond rows (6.5%) and the largest was 100%. A bad vendor tick is one row:
#: the worst observed was 1 of 1,252 (0.08%). 1% sits two orders of magnitude
#: from the ticks and six times below the smallest poison.
#:
#: Why this matters, learned the hard way: Citi really does serve
#: ``RATES.BOND.US9128284X55.YIELD`` as -6.5211 on 2023-08-30. That row was
#: deleted by the repair and came back BIT-IDENTICAL on the next fetch, which
#: proves it is a vendor print and not an artefact. A gate that raised on it
#: would refuse the whole 1,252-row series for ever, and one bad tick would cost
#: a tag its entire history. Refusing a wrong SERIES is the job; refusing a wrong
#: ROW is a denial of service against the good rows around it.
MIN_BAD_FRACTION = 0.01

#: ...but never fewer than this many rows, so a short series cannot be condemned
#: by a single tick that happens to exceed 1% of three rows.
MIN_BAD_ROWS = 3


def assert_plausible(tag: str, series: pd.Series) -> None:
    """Raise :class:`TagSanityError` when ``series`` cannot belong to ``tag``.

    Refuses only when enough of the series is out of band to mean it is a
    DIFFERENT series (see :data:`MIN_BAD_FRACTION`). A handful of impossible rows
    in an otherwise sane series is a bad vendor print: it is logged, loudly and
    by date, and the write proceeds. The repair tool removes those separately,
    where a human can see what was dropped.

    The message names the family, the band, how many rows broke it and the first
    few offending dates, because the cause is always "these values came from a
    different series" and the dates are what identifies which one.
    """
    if not sanity_enabled():
        return
    bad = implausible_rows(tag, series)
    if bad.empty:
        return
    lo, hi = band_for_tag(tag)  # type: ignore[misc]
    if len(bad) < max(MIN_BAD_ROWS, MIN_BAD_FRACTION * len(series)):
        _logger.warning(
            "%s: %d of %d row(s) lie outside [%s, %s] - %s. Too few to mean the "
            "whole series is foreign, so it is being banked; these look like bad "
            "vendor prints. scripts/citivelo_tagcache_repair.py removes them.",
            tag, len(bad), len(series), lo, hi,
            ", ".join(f"{getattr(ts, 'date', lambda: ts)()}={float(v):.6g}"
                      for ts, v in list(bad.items())[:5]),
        )
        return
    head = ", ".join(
        f"{ts.date() if hasattr(ts, 'date') else ts}={float(v):.6g}"
        for ts, v in list(bad.items())[:5]
    )
    raise TagSanityError(
        f"{tag} is {_describe(tag)}, which lies in [{lo}, {hi}]; "
        f"{len(bad)} of {len(series)} row(s) do not, spanning "
        f"{bad.index.min()} .. {bad.index.max()} ({head}). "
        "This is what a series from ANOTHER tag looks like - see "
        "docs/2026-08-24-citivelo-tagcache-poison.md. Set ARBS_CITIVELO_SANITY=off "
        "only if you are deliberately repairing this file."
    )
