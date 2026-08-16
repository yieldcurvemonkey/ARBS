"""Where ARBS keeps its bytes.

This box has a 950 GB system drive that ran down to 2 GB free and a data drive
with room to spare, so every persistent store belongs off ``C:``. Two different
mechanisms get them there, and the split is deliberate:

**Stores under ``%LOCALAPPDATA%\\ARBS`` are relocated by an NTFS junction**
(``C:\\Users\\chris\\AppData\\Local\\ARBS`` -> ``D:\\ARBS_DATA\\appdata``), not
by this module. Those stores already share a resolution ladder --
``ARBS_CACHE_DIR`` -> ``platformdirs.user_cache_dir`` -> ``LOCALAPPDATA`` -- but
the first rung does **not** agree with the second for four of them:

===========================  ==============================  ===========================
store                        ``$ARBS_CACHE_DIR`` branch      platformdirs branch (live)
===========================  ==============================  ===========================
fixings_cache                ``$E/fixings_cache``            ``ARBS/MDP/IRSwaps/.../Cache``
dbnomics_fetcher             ``$E/dbnomics_cache``           ``ARBS/MDP/USMoneyMarkets/...``
serff futures_data           ``$E/eod_settles``              ``ARBS/BT/serff/.../Cache``
BARCHART_STIRF curve_cache   ``$E/IRSwaps/BARCHART_STIRF``   ``ARBS/Cache/diskcache/dump``
===========================  ==============================  ===========================

Setting ``ARBS_CACHE_DIR`` to move them would therefore point four caches at
directories that have never held data, and each would rebuild cold and silent --
network refetches measured in hours, reported as a successful migration. A
junction has no such failure mode: it is byte-identical by construction, and
every one of the ladders above still resolves through it. See
``docs/storage_layout.md``.

**Repo-relative stores get an explicit env override instead**, resolved here.
They cannot use a junction: they sit inside a git worktree, where
``git clean -xfd`` deletes straight through a reparse point and would take the
real data on the far side with it.

Nothing changes for a caller who sets no environment variable -- every helper
below falls back to the historical repo-relative default. Setting
``ARBS_DATA_ROOT`` moves the whole set at once; the per-store variables exist so
one store can be pinned without disturbing the others.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "DATA_ROOT_ENV",
    "data_root",
    "repo_store",
]

#: The checkout this module was imported from -- ``utils/`` is one level down.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Points the repo-relative stores at a directory outside the checkout.
DATA_ROOT_ENV = "ARBS_DATA_ROOT"


def data_root() -> Path | None:
    """The configured off-checkout data root, or ``None`` when unset.

    ``None`` is the answer that preserves history: every caller falls back to
    its repo-relative default, so an unconfigured machine behaves exactly as it
    did before this module existed. There is deliberately no "guess ``D:`` if it
    exists" branch -- a store that silently changes location because a drive was
    mounted is a store that silently rebuilds cold.
    """
    raw = os.getenv(DATA_ROOT_ENV)
    if not raw or not raw.strip():
        return None
    return Path(raw.strip()).expanduser()


def repo_store(*relative_parts: str, env_var: str | None = None) -> Path:
    """Resolve one repo-relative store, honouring its overrides.

    Precedence, highest first:

    1. ``env_var`` -- the store's own variable, when the caller names one.
    2. ``$ARBS_DATA_ROOT / <relative_parts>`` -- the whole-repo relocation.
    3. ``REPO_ROOT / <relative_parts>`` -- the historical default.

    ``relative_parts`` is the store's path *relative to the checkout root*, so
    the layout under ``$ARBS_DATA_ROOT`` mirrors the layout under the repo. That
    matters more than it looks: it makes a migration a plain directory move, and
    it makes the two locations diffable afterwards.
    """
    if env_var:
        explicit = os.getenv(env_var)
        if explicit and explicit.strip():
            return Path(explicit.strip()).expanduser()

    root = data_root()
    if root is not None:
        return root.joinpath(*relative_parts)

    return REPO_ROOT.joinpath(*relative_parts)
