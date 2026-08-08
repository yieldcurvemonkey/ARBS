r"""The hardened blob path, pointed at the curve day-block table.

``arbs_curve_intraday_blocks_v1`` is already written by
:meth:`Caching.supabase_curve_sync.SupabaseCurveSync.push_day` and read by
``CurveStore.read_raw_day``'s L2 fallback. This adds a *second writer* for the
same table rather than changing that one, because the live curve path depends on
it and a bulk backfill wants four things it does not have:

* **content-based resume.** ``backfill_local_curve_store_to_supabase`` resumes on
  "is this date present remotely", so a day whose local parquet has been rebuilt
  since it was pushed is never noticed. Comparing shas costs the same query.
* **a multi-file refusal.** ``_local_parquet_bytes`` returns ``pq_files[0]``
  while ``read_raw_day`` concatenates every file in the partition. Pushing one of
  several silently publishes fewer rows than the local store serves.
* **``SET LOCAL statement_timeout = 0``.** The server default is 120 s
  (measured); a 385 KB minute-day blob is nowhere near that, but a batch that
  ever grows past it dies mid-backfill with no other symptom.
* **a labelled transaction**, so a multi-hour backfill is identifiable and
  cancellable in ``pg_stat_activity`` instead of anonymous behind Supavisor.

It writes the same columns with the same ``ON CONFLICT`` semantics, so
``pull_day`` and ``prefetch_range`` on the existing sync read what this writes.

What it deliberately does not do is write ``arbs_curve_snapshots_v1``. The row
tier is a separate concern with a separate failure mode (``_push_tagged_snapshots``
skips untagged rows, silently), so it is a separate, explicit step in
``scripts/citivelo_l2_sync.py`` rather than a side effect of a blob push.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine

from Caching.supabase_blob_blocks import BlobBlockSync, BlobBlockTable

__all__ = ["CURVE_INTRADAY_BLOCKS_TABLE", "CURVE_ANALYTICS_BLOCKS_TABLE", "CurveBlobSync"]

CURVE_INTRADAY_BLOCKS_TABLE = "arbs_curve_intraday_blocks_v1"
CURVE_ANALYTICS_BLOCKS_TABLE = "arbs_curve_analytics_blocks_v1"

#: The exact rule ``Caching.supabase_curve_sync`` and ``Caching.curve_store`` use
#: for the on-disk name. Reproduced rather than imported so this module does not
#: drag in the curve sync.
_SLUG_RX = re.compile(r"[^\w.\-]")


def _sanitize(name: str) -> str:
    return _SLUG_RX.sub("_", name)


class CurveBlobSync(BlobBlockSync):
    """``raw`` or ``analytics`` day blobs for one CurveStore base directory."""

    def __init__(
        self,
        *,
        base_dir: Path,
        engine: Optional[Engine],
        kind: str = "raw",
    ) -> None:
        if kind not in ("raw", "analytics"):
            raise ValueError(f"kind must be 'raw' or 'analytics', not {kind!r}")
        table = (
            CURVE_INTRADAY_BLOCKS_TABLE if kind == "raw" else CURVE_ANALYTICS_BLOCKS_TABLE
        )
        super().__init__(
            table=BlobBlockTable(name=table, key_column="curve_name"),
            base_dir=base_dir,
            engine=engine,
            label_component=f"curve_l2_{kind}",
        )
        self.kind = kind

    def asset_root(self, key: str) -> Path:
        return self.base_dir / self.kind / f"asset={_sanitize(key)}"

    def partition_dir(self, key: str, trading_date: datetime.date) -> Path:
        return self.asset_root(key) / f"date={trading_date.isoformat()}"
