from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from typing import Optional, Dict

from Query.Base._GenericPricable import _GenericPricable

@dataclass
class Order:
    timestamp: dt.datetime
    instrument: _GenericPricable
    meta: Optional[Dict] = None  # e.g., tags, strategy, trigger id
