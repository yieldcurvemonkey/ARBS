r"""The Supabase L2 tier for :class:`Caching.swaption_cube_store.SwaptionCubeStore`.

``SwaptionCubeStore`` shipped deliberately without one. Its module docstring
records why: ``Caching.supabase_engine.SUPABASE_ENABLED`` defaults to **True**
and ``get_database_url()`` falls back to hard-coded production credentials, so
cloning ``CurveStore``'s always-on push would have had a fresh checkout creating
tables in, and pushing blobs to, the live database the first time anybody built
a cube. ``scripts/citivelo_swaption_vol_warm.py`` does not even set
``ARBS_SUPABASE_ENABLED=0`` the way the four Citi curve scripts do, so ``build``
would have been that first time.

Three things close that, and none of them is "remember to set an env var":

1. **The tier is off unless asked.** :data:`Caching.l2_policy.SWAPTION_CUBE_L2_ENV`
   defaults to ``off`` and is parsed strictly, so ``disabled`` or a typo also
   mean off - where ``_env_enabled`` reads both as *enabled*. It is read at call
   time, so ``--push-l2`` on a CLI can turn it on after import, which is exactly
   what ``citivelo_excel_warm.py --push-l2`` could never do.
2. **Reads are a separate state from writes.** ``ARBS_SUPABASE_ENABLED`` is
   all-or-nothing; this has ``read`` for "pull history, never publish".
3. **Reads run no DDL.** See :mod:`Caching.supabase_blob_blocks`.

The blob mechanics - sha verification on the way in, atomic landing,
manifest-first prefetch, refusing a multi-file partition, restatement symmetry -
all live in :class:`~Caching.supabase_blob_blocks.BlobBlockSync`. This module is
the ~50 lines that are actually specific to cubes.

What is *not* here, on purpose: a row-level tier. ``arbs_curve_snapshots_v1``
exists because a curve snapshot has a natural row shape (node dates and discount
factors) that supports as-of lookup. A vol surface has no such reading - you
want the whole grid or nothing - so a row table would be 500 rows a day to
answer the same question one blob answers.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine

from Caching.l2_policy import L2Mode, swaption_cube_l2_mode
from Caching.supabase_blob_blocks import BlobBlockSync, BlobBlockTable

logger = logging.getLogger(__name__)

__all__ = [
    "SWAPTION_CUBE_BLOCKS_TABLE",
    "SupabaseSwaptionCubeSync",
    "resolve_cube_sync",
]

SWAPTION_CUBE_BLOCKS_TABLE = "arbs_swaption_cube_blocks_v1"

#: The store's own partition root. Kept as a literal rather than imported so this
#: module does not pull in the store (and the store's L2 hook does not import in
#: a cycle).
_RAW_SUBDIR = "vol_raw"


class SupabaseSwaptionCubeSync(BlobBlockSync):
    """Blob-block sync for ``vol_raw/asset=<ASSET>/date=<ISO>/<sha>.parquet``."""

    def __init__(self, *, base_dir: Path, engine: Optional[Engine]) -> None:
        super().__init__(
            table=BlobBlockTable(name=SWAPTION_CUBE_BLOCKS_TABLE, key_column="asset"),
            base_dir=base_dir,
            engine=engine,
            label_component="swaption_cube_l2",
        )

    # The DB key is the RAW asset name; only the path is sanitized. Same split as
    # the curve sync: `_sanitize` exists to survive a Windows path limit, not to
    # rename the asset, and a sanitized key would not join to anything else.
    @staticmethod
    def _path_token(asset: str) -> str:
        from Caching.swaption_cube_store import _sanitize

        return _sanitize(asset)

    def asset_root(self, key: str) -> Path:
        return self.base_dir / _RAW_SUBDIR / f"asset={self._path_token(key)}"

    def partition_dir(self, key: str, trading_date: datetime.date) -> Path:
        return self.asset_root(key) / f"date={trading_date.isoformat()}"

    @classmethod
    def from_defaults(cls, *, engine: Optional[Engine] = None) -> "SupabaseSwaptionCubeSync":
        """Bind to the default store's directory and the shared engine.

        Does **not** consult the L2 mode - it builds a sync object, it does not
        decide policy. Use :func:`resolve_cube_sync` for the gated version.
        """
        from Caching.swaption_cube_store import SwaptionCubeStore

        if engine is None:
            from Caching.supabase_engine import get_engine

            engine = get_engine()
        return cls(base_dir=SwaptionCubeStore.default().base_dir, engine=engine)


def resolve_cube_sync(
    base_dir: Path,
    *,
    mode: Optional[L2Mode] = None,
    engine: Optional[Engine] = None,
    need: str = "read",
) -> Optional[SupabaseSwaptionCubeSync]:
    """A sync object, or ``None`` when policy says this operation must not happen.

    ``need`` is ``"read"`` or ``"write"``. ``mode=None`` means "ask the
    environment now" - deliberately at call time, so the answer tracks a CLI flag
    set after import rather than whatever was true when ``Caching`` first loaded.
    """
    active = swaption_cube_l2_mode() if mode is None else mode
    if need == "write" and not active.writes:
        return None
    if need == "read" and not active.reads:
        return None

    if engine is None:
        from Caching.supabase_engine import get_engine

        engine = get_engine()
    if engine is None:
        logger.debug(
            "swaption cube L2 requested (%s) but no engine is configured; staying local.",
            active.value,
        )
        return None
    return SupabaseSwaptionCubeSync(base_dir=Path(base_dir), engine=engine)
