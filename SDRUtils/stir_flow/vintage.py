"""Code vintage stamping for the STIR flow / ladder tables.

Every row the classifier and the ladder write is a function of the code that
wrote it, and the tables are upserted in place. Without a vintage stamp a table
silently becomes a mixture: `arbs_stir_direction_v1` held 07/02 classified under
one code revision, 07/09-07/13 under another, and 07/14 under a third (post
dual-timestamp), which is how 07/14 came out at 974 units against ~560-690 for
comparable days. Mixed vintages make coverage, skew, and UNKNOWN rates
non-comparable across days, and any research stratified by date inherits that.

So: stamp the writing revision, resolved once per process.
"""
from __future__ import annotations

import functools
import pathlib
import subprocess

UNKNOWN_VINTAGE = "unknown"


@functools.lru_cache(maxsize=1)
def code_vintage() -> str:
    """Short git SHA of the working tree this module was imported from.

    Appends ``+dirty`` when the tree has uncommitted changes, so a row written
    from a modified checkout is never mistaken for one written from the commit.
    Returns ``"unknown"`` if git is unavailable or this is not a repository --
    stamping must never be able to fail a backfill.
    """
    repo = pathlib.Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        if not sha:
            return UNKNOWN_VINTAGE
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
        return f"{sha}+dirty" if dirty else sha
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_VINTAGE
