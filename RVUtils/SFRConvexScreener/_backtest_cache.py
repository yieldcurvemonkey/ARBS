"""On-disk snapshot cache for the SFR Convex Screener backtest.

Stores one pickled `SFRConvexScreenerSnapshot` per (as_of, config-hash) pair so
the heavyweight `build_snapshot` runs once per backtest date and reloads
instantly on subsequent runs.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

from RVUtils.SFRConvexScreener._types import SFRConvexScreenerSnapshot

logger = logging.getLogger(__name__)


def snapshot_cache_key(as_of: datetime.date, config_summary: Dict[str, Any]) -> str:
    """Stable hash of (as_of, config) — JSON-encoded config sorted by key."""
    payload = json.dumps(config_summary, sort_keys=True, default=str)
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{as_of.isoformat()}_{h}"


@dataclass
class SnapshotCache:
    root: Union[str, Path]

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, as_of: datetime.date, config_summary: Dict[str, Any]) -> Path:
        key = snapshot_cache_key(as_of, config_summary)
        return Path(self.root) / f"{key}.pkl"

    def get(
        self, as_of: datetime.date, config_summary: Dict[str, Any]
    ) -> Optional[SFRConvexScreenerSnapshot]:
        p = self._path(as_of, config_summary)
        if not p.exists():
            return None
        try:
            with p.open("rb") as fh:
                return pickle.load(fh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache read failed for %s: %s", p, exc)
            return None

    def put(
        self,
        snapshot: SFRConvexScreenerSnapshot,
        config_summary: Dict[str, Any],
    ) -> Path:
        p = self._path(snapshot.as_of, config_summary)
        with p.open("wb") as fh:
            pickle.dump(snapshot, fh)
        return p
