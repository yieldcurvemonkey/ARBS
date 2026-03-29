from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

import QuantLib as ql

from BT.flow_alpha.models import EventSource, KnownDemandEvent
from BT.flow_alpha.window_rules import default_rates_calendar


@dataclass
class BusinessPeriodEventSource(EventSource):
    family: str
    period: str
    asset_class: str = "RATES"
    source_name: str = "CALENDAR"
    direction_hint: Optional[str] = None
    instrument_scope: Optional[str] = None
    calendar: ql.Calendar = field(default_factory=default_rates_calendar)
    payload_factory: Optional[Callable[[dt.date], dict[str, Any]]] = None

    def _business_period_ends(self, start: dt.date, end: dt.date) -> list[dt.date]:
        current = dt.date(start.year, start.month, 1)
        out: list[dt.date] = []
        while current <= end:
            qd = ql.Date(1, current.month, current.year)
            eom = self.calendar.endOfMonth(qd)
            anchor = dt.date(eom.year(), int(eom.month()), eom.dayOfMonth())
            if self.period == "month":
                if start <= anchor <= end:
                    out.append(anchor)
            elif self.period == "quarter":
                if current.month in (3, 6, 9, 12) and start <= anchor <= end:
                    out.append(anchor)
            elif self.period == "year":
                if current.month == 12 and start <= anchor <= end:
                    out.append(anchor)
            else:
                raise ValueError(f"Unsupported period: {self.period!r}")
            if current.month == 12:
                current = dt.date(current.year + 1, 1, 1)
            else:
                current = dt.date(current.year, current.month + 1, 1)
        return out

    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        payload_factory = kwargs.get("payload_factory") or self.payload_factory
        out: list[KnownDemandEvent] = []
        for anchor in self._business_period_ends(start, end):
            payload = payload_factory(anchor) if payload_factory else {}
            out.append(
                KnownDemandEvent(
                    event_id=f"{self.family}-{anchor.isoformat()}",
                    family=self.family,
                    asset_class=self.asset_class,
                    anchor_date=anchor,
                    direction_hint=self.direction_hint,
                    instrument_scope=self.instrument_scope,
                    source=self.source_name,
                    payload=payload,
                )
            )
        return out


@dataclass
class DateListEventSource(EventSource):
    family: str
    dates_fn: Callable[[dt.date, dt.date], Iterable[dt.date]]
    asset_class: str = "RATES"
    source_name: str = "CALENDAR"
    direction_hint: Optional[str] = None
    instrument_scope: Optional[str] = None
    payload_factory: Optional[Callable[[dt.date], dict[str, Any]]] = None

    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        payload_factory = kwargs.get("payload_factory") or self.payload_factory
        out: list[KnownDemandEvent] = []
        for anchor in self.dates_fn(start, end):
            payload = payload_factory(anchor) if payload_factory else {}
            out.append(
                KnownDemandEvent(
                    event_id=f"{self.family}-{anchor.isoformat()}",
                    family=self.family,
                    asset_class=self.asset_class,
                    anchor_date=anchor,
                    direction_hint=self.direction_hint,
                    instrument_scope=self.instrument_scope,
                    source=self.source_name,
                    payload=payload,
                )
            )
        return out
