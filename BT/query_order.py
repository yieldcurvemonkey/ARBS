# BT/query_order.py
from __future__ import annotations
import datetime
from dataclasses import dataclass
from typing import Optional, Dict

from Query.Base.BaseQuery import BaseQuery


@dataclass
class QueryOrder:
    timestamp: datetime.datetime
    query: BaseQuery
    meta: Optional[Dict] = None  # tags, strategy, trigger id, etc.
