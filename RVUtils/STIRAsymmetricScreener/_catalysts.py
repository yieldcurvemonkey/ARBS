"""Catalyst calendar for the STIR Options Asymmetric Screener.

Spec §6: each option expiry tagged with high-impact catalysts inside its
window. Sources:
    - FOMC / ECB meetings: ``Query/IRSwaps/_CENTRAL_BANK_DATES``
    - NFP / CPI / PCE / ISM: opt-in via ForexFactory feed (Phase 5 v1
      defaults to FOMC + ECB only — econ-data feed integration is
      flagged as a TODO and surfaces a structured warning).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Catalyst:
    """A single calendar event with impact classification."""

    kind: str          # "fomc", "ecb", "boe", "nfp", "cpi", "ppi", "pce", "ism", "umich", "refunding", "turn"
    date: datetime.date
    impact: str        # "high", "medium", "low"
    label: str = ""    # human-readable, e.g. "Jun26 FOMC"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "date": self.date.isoformat(),
            "impact": self.impact,
            "label": self.label,
        }


def _load_central_bank_meetings(curve_id: str, *, kind: str) -> List[Catalyst]:
    """Load central-bank meeting starts as ``Catalyst`` records."""
    try:
        from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
    except Exception as exc:  # noqa: BLE001
        logger.warning("central_bank_dates_unavailable", extra={"error": str(exc)})
        return []

    sched = _CENTRAL_BANK_DATES.get(curve_id, {}) or {}
    out: List[Catalyst] = []
    for label, value in sched.items():
        if not isinstance(value, tuple) or len(value) < 2:
            continue
        eff = value[0]
        if not isinstance(eff, datetime.date):
            continue
        out.append(
            Catalyst(
                kind=kind,
                date=eff,
                impact="high",
                label=f"{label} {kind.upper()}",
            )
        )
    return out


def load_catalyst_calendar(
    *,
    as_of: datetime.date,
    lookahead_days: int = 750,
    include_fomc: bool = True,
    include_ecb: bool = False,
    extra_catalysts: Optional[Iterable[Catalyst]] = None,
) -> Tuple[Catalyst, ...]:
    """Aggregate calendar events from the configured sources.

    NFP / CPI / PCE / ISM econ-data integration is deferred to a follow-up:
    the ForexFactory feed (``RVUtils/forex_factory_calendar.py``) lives in
    a separate module that requires network access at scrape time. Callers
    can pass ``extra_catalysts`` directly.
    """
    cutoff = as_of + datetime.timedelta(days=lookahead_days)
    out: List[Catalyst] = []

    if include_fomc:
        out.extend(_load_central_bank_meetings("USD-SOFR-1D", kind="fomc"))
    if include_ecb:
        out.extend(_load_central_bank_meetings("EUR-ESTR", kind="ecb"))
    if extra_catalysts:
        out.extend(list(extra_catalysts))

    # TODO(blocker): wire NFP / CPI / PCE / ISM via ForexFactoryCalendarFetcher.
    # For now surface a structured warning so callers know data is incomplete.
    logger.info(
        "catalyst_calendar_partial_sources",
        extra={
            "fomc_loaded": include_fomc,
            "ecb_loaded": include_ecb,
            "econ_data_loaded": False,
        },
    )

    # Filter to as_of <= date <= cutoff
    out = [c for c in out if as_of <= c.date <= cutoff]
    out.sort(key=lambda c: c.date)
    return tuple(out)


def catalysts_inside_window(
    *,
    as_of: datetime.date,
    expiry: datetime.date,
    catalysts: Tuple[Catalyst, ...],
    impact: str = "high",
) -> Tuple[Catalyst, ...]:
    """Return catalysts whose date falls inside ``(as_of, expiry]``.

    ``impact`` filters by impact level. Use ``"any"`` to include every
    impact.
    """
    if impact == "any":
        keep = lambda c: True  # noqa: E731
    else:
        keep = lambda c: c.impact == impact  # noqa: E731

    out: List[Catalyst] = []
    for c in catalysts:
        if c.date <= as_of:
            continue
        if c.date > expiry:
            continue
        if not keep(c):
            continue
        out.append(c)
    out.sort(key=lambda c: c.date)
    return tuple(out)
