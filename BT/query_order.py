# ABOUTME: Query order dataclass for query-based backtesting
# ABOUTME: Represents trade orders using BaseQuery instead of priceable instruments
# BT/query_order.py
from __future__ import annotations
import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Callable, Any

from Query.Base.BaseQuery import BaseQuery


@dataclass
class QueryOrder:
    timestamp: datetime.datetime
    query: BaseQuery
    meta: Optional[Dict] = None  # tags, strategy, trigger id, etc.


@dataclass
class UnwindOrder:
    timestamp: datetime.datetime
    selector: Callable[[Any], bool]  # predicate: ResolvedQueryPosition -> bool
    meta: Optional[Dict] = None  # e.g., {"action":"unwind", "fee": 0.0}
