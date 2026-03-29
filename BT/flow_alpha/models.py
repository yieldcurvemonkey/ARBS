from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Optional

import pandas as pd


def _coerce_date(value: Any) -> Optional[dt.date]:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out


@dataclass(frozen=True)
class KnownDemandEvent:
    event_id: str
    family: str
    asset_class: str
    anchor_date: dt.date
    entry_date: Optional[dt.date] = None
    exit_date: Optional[dt.date] = None
    direction_hint: Optional[str] = None
    instrument_scope: Optional[str] = None
    source: str = ""
    confidence: float = 1.0
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "anchor_date", _coerce_date(self.anchor_date))
        object.__setattr__(self, "entry_date", _coerce_date(self.entry_date))
        object.__setattr__(self, "exit_date", _coerce_date(self.exit_date))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, _coerce_float(self.confidence, default=1.0))))
        object.__setattr__(self, "payload", dict(self.payload or {}))

    def with_window(
        self,
        *,
        entry_date: Optional[dt.date] = None,
        exit_date: Optional[dt.date] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> "KnownDemandEvent":
        merged_payload = dict(self.payload)
        if payload:
            merged_payload.update(dict(payload))
        return replace(
            self,
            entry_date=_coerce_date(entry_date) if entry_date is not None else self.entry_date,
            exit_date=_coerce_date(exit_date) if exit_date is not None else self.exit_date,
            payload=merged_payload,
        )


def normalize_event_records(records: Any) -> list[KnownDemandEvent]:
    if records is None:
        return []
    if isinstance(records, KnownDemandEvent):
        return [records]
    if isinstance(records, pd.DataFrame):
        return [
            KnownDemandEvent(
                event_id=str(row.get("event_id") or row.get("id") or f"{row.get('family', 'event')}-{idx}"),
                family=str(row.get("family") or row.get("event_family") or "flow_alpha"),
                asset_class=str(row.get("asset_class") or row.get("asset") or "RATES"),
                anchor_date=row.get("anchor_date"),
                entry_date=row.get("entry_date"),
                exit_date=row.get("exit_date"),
                direction_hint=row.get("direction_hint"),
                instrument_scope=row.get("instrument_scope"),
                source=str(row.get("source") or ""),
                confidence=row.get("confidence", 1.0),
                payload=row.get("payload")
                if isinstance(row.get("payload"), Mapping)
                else {
                    k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "event_id",
                        "id",
                        "family",
                        "event_family",
                        "asset_class",
                        "asset",
                        "anchor_date",
                        "entry_date",
                        "exit_date",
                        "direction_hint",
                        "instrument_scope",
                        "source",
                        "confidence",
                        "payload",
                    }
                },
            )
            for idx, row in records.iterrows()
        ]
    if isinstance(records, Iterable) and not isinstance(records, (str, bytes, dict)):
        out: list[KnownDemandEvent] = []
        for item in records:
            out.extend(normalize_event_records(item))
        return out
    raise TypeError(f"Unsupported event records type: {type(records)!r}")


class EventSource(ABC):
    @abstractmethod
    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent] | pd.DataFrame:
        raise NotImplementedError

    def materialize(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        return normalize_event_records(self.fetch(start, end, **kwargs))


class StateSignalSource(ABC):
    @abstractmethod
    def signal(self, state: dt.datetime, backtest=None, **kwargs: Any) -> Any:
        raise NotImplementedError

    def exit_signal(self, state: dt.datetime, backtest=None, **kwargs: Any) -> Any:
        return False
