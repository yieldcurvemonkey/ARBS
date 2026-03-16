"""Priority snapshot tagging for CurveStore -> Supabase curve_snapshots."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Tolerance: event tag applies if session_minute is within +/- this many minutes
_EVENT_MINUTE_TOLERANCE = 2


def get_tags(
    *,
    session_minute: int,
    trading_date: datetime.date,
    is_last_of_day: bool,
    event_calendar: dict[datetime.date, dict[str, Any]],
) -> list[str]:
    """Return priority tags for a curve snapshot."""
    tags: list[str] = []
    if session_minute == 0:
        tags.append("OPEN")
    if is_last_of_day:
        tags.append("EOD")
    event = event_calendar.get(trading_date)
    if event is not None:
        event_minute = event.get("session_minute")
        if event_minute is not None and abs(session_minute - event_minute) <= _EVENT_MINUTE_TOLERANCE:
            tags.append(event["tag"])
    return tags


def load_event_calendar(path: Path) -> dict[datetime.date, dict[str, Any]]:
    """Load event calendar from YAML file. Returns empty dict if file missing."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        import yaml

        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        # Convert string keys to date objects if needed
        cal = {}
        for k, v in raw.items():
            if isinstance(k, str):
                k = datetime.date.fromisoformat(k)
            cal[k] = v
        return cal
    except Exception:
        logger.warning("Failed to load event calendar from %s", path, exc_info=True)
        return {}
