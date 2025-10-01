# BT/data_handler.py
from __future__ import annotations
import datetime
from typing import Iterable, Iterator


class TimeGrid:
    """Simple iterator over a schedule of datetimes."""
    def __init__(self, states: Iterable[datetime.datetime]):
        self._states = list(states)

    def __iter__(self) -> Iterator[datetime.datetime]:
        return iter(self._states)
