from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import QuantLib as ql

from BT.flow_alpha.models import KnownDemandEvent
from BT.misc import _n_business_days_before, _nth_business_day_of_month


def default_rates_calendar() -> ql.Calendar:
    return ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def _to_ql_date(value: dt.date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _to_py_date(value: ql.Date) -> dt.date:
    return dt.date(value.year(), int(value.month()), value.dayOfMonth())


def advance_business_days(cal: ql.Calendar, value: dt.date, offset: int) -> dt.date:
    if offset == 0:
        return _to_py_date(cal.adjust(_to_ql_date(value), ql.Following))
    if offset < 0:
        return _n_business_days_before(cal, value, abs(offset))
    return _to_py_date(cal.advance(_to_ql_date(value), offset, ql.Days))


def next_period_anchor(anchor: dt.date, *, period: str, cal: ql.Calendar) -> dt.date:
    if period == "month":
        ny, nm = (anchor.year + 1, 1) if anchor.month == 12 else (anchor.year, anchor.month + 1)
        return _nth_business_day_of_month(cal, ny, nm, 1)
    if period == "quarter":
        month = ((anchor.month - 1) // 3) * 3 + 1
        next_month = month + 3
        year = anchor.year
        if next_month > 12:
            next_month -= 12
            year += 1
        return _nth_business_day_of_month(cal, year, next_month, 1)
    if period == "year":
        return _nth_business_day_of_month(cal, anchor.year + 1, 1, 1)
    raise ValueError(f"Unsupported period: {period!r}")


def resolve_event_date(event: KnownDemandEvent, field_name: str) -> dt.date:
    if hasattr(event, field_name):
        value = getattr(event, field_name)
        if value is not None:
            return value
    value = event.payload.get(field_name)
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raise KeyError(f"Event {event.event_id} does not contain date field '{field_name}'")


class WindowRule(ABC):
    @abstractmethod
    def apply(self, event: KnownDemandEvent, *, calendar: Optional[ql.Calendar] = None) -> KnownDemandEvent:
        raise NotImplementedError


@dataclass(frozen=True)
class AnchorDateWindowRule(WindowRule):
    entry_anchor_field: str = "anchor_date"
    exit_anchor_field: str = "anchor_date"
    entry_offset_business_days: int = 0
    exit_offset_business_days: int = 0

    def apply(self, event: KnownDemandEvent, *, calendar: Optional[ql.Calendar] = None) -> KnownDemandEvent:
        cal = calendar or default_rates_calendar()
        entry_anchor = resolve_event_date(event, self.entry_anchor_field)
        exit_anchor = resolve_event_date(event, self.exit_anchor_field)
        return event.with_window(
            entry_date=advance_business_days(cal, entry_anchor, self.entry_offset_business_days),
            exit_date=advance_business_days(cal, exit_anchor, self.exit_offset_business_days),
        )


@dataclass(frozen=True)
class NextPeriodBusinessDayWindowRule(WindowRule):
    entry_anchor_field: str = "anchor_date"
    entry_offset_business_days: int = 0
    next_period: str = "month"
    exit_business_day: int = 1

    def apply(self, event: KnownDemandEvent, *, calendar: Optional[ql.Calendar] = None) -> KnownDemandEvent:
        cal = calendar or default_rates_calendar()
        anchor = resolve_event_date(event, self.entry_anchor_field)
        entry_date = advance_business_days(cal, anchor, self.entry_offset_business_days)
        exit_anchor = next_period_anchor(anchor, period=self.next_period, cal=cal)
        if self.exit_business_day > 1:
            exit_date = _nth_business_day_of_month(cal, exit_anchor.year, exit_anchor.month, self.exit_business_day)
        else:
            exit_date = exit_anchor
        return event.with_window(entry_date=entry_date, exit_date=exit_date)


@dataclass(frozen=True)
class SettlementWindowRule(WindowRule):
    pricing_field: str = "pricing_date"
    settlement_field: str = "settlement_date"
    entry_offset_business_days: int = -1
    exit_offset_business_days: int = 0

    def apply(self, event: KnownDemandEvent, *, calendar: Optional[ql.Calendar] = None) -> KnownDemandEvent:
        cal = calendar or default_rates_calendar()
        pricing_date = resolve_event_date(event, self.pricing_field)
        settlement_date = resolve_event_date(event, self.settlement_field)
        return event.with_window(
            entry_date=advance_business_days(cal, pricing_date, self.entry_offset_business_days),
            exit_date=advance_business_days(cal, settlement_date, self.exit_offset_business_days),
        )


@dataclass(frozen=True)
class RollWindowRule(NextPeriodBusinessDayWindowRule):
    pass
