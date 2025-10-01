# BT/event.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Type

@dataclass
class TriggerInfo:
    triggered: bool
    info: Dict[Type, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.triggered
