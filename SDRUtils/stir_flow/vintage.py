"""Code vintage stamping for the STIR flow / ladder tables.

Every row the classifier and the ladder write is a function of the code that
wrote it, and the tables are upserted in place. Without a vintage stamp a table
silently becomes a mixture: `arbs_stir_direction_v1` held 07/02 classified under
one code revision, 07/09-07/13 under another, and 07/14 under a third (post
dual-timestamp), which is how 07/14 came out at 974 units against ~560-690 for
comparable days. Mixed vintages make coverage, skew and UNKNOWN rates
non-comparable across days, and any research stratified by date inherits that.

WHY A MODULE HASH AND NOT THE GIT SHA
-------------------------------------
The stamp has one job: decide whether two rows were produced by the same logic.
The repo HEAD is a bad proxy for that. A ~6-month backfill runs for many hours,
and committing anything at all in the meantime — a research module, a doc — would
change HEAD and split the window into artificial vintages, while a dirty working
tree would tar every row with "+dirty" regardless of whether the dirt was in this
pipeline. So the stamp is a hash over the CONTENTS of the modules that actually
determine the output, which changes exactly when the pipeline changes and never
otherwise. The git SHA is still recorded, but in logs, as provenance.

Files whose edits must bump the vintage are listed in ``VINTAGE_SOURCES``. Add to
it when a new module starts influencing what gets written.
"""
from __future__ import annotations

import functools
import hashlib
import pathlib
import subprocess

UNKNOWN_VINTAGE = "unknown"
_REPO = pathlib.Path(__file__).resolve().parents[2]

# Output-determining modules. `vintage.py` and `daylog.py` are deliberately
# EXCLUDED: the former is this hasher (editing its prose must not invalidate a
# backfill) and the latter only redirects stdout.
VINTAGE_SOURCES = (
    "SDRUtils/stir_flow/classifier.py",
    "SDRUtils/stir_flow/confidence.py",
    "SDRUtils/stir_flow/config.py",
    "SDRUtils/stir_flow/curve_warm.py",
    "SDRUtils/stir_flow/ladder.py",
    "SDRUtils/stir_flow/ladder_conventions.py",
    "SDRUtils/stir_flow/ladder_state.py",
    "SDRUtils/stir_flow/book.py",
    "SDRUtils/stir_flow/pricing.py",
    "SDRUtils/stir_flow/tick_size.py",
    "SDRUtils/stir_flow/trade_selection.py",
    "SDRUtils/stir_flow/unwinds.py",
    "SDRUtils/_swappulse_scripts/_stir_flow_schema_v1.py",
    "SDRUtils/_swappulse_scripts/_stir_ladder_schema_v1.py",
    "SDRUtils/_swappulse_scripts/backfill_stir_direction.py",
    "SDRUtils/_swappulse_scripts/backfill_stir_direction_range.py",
    "SDRUtils/_swappulse_scripts/backfill_stir_ladder.py",
    "MDP/IRSwaps/BARCHART_STIRF/risk.py",
    "Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py",
)


@functools.lru_cache(maxsize=1)
def code_vintage() -> str:
    """12-hex digest of the output-determining pipeline modules.

    Returns ``"unknown"`` if the sources cannot be read — a stamp must never be
    able to fail a backfill. Missing files are hashed as an explicit ``<missing>``
    marker rather than skipped, so a deleted module still changes the vintage.
    """
    h = hashlib.sha256()
    try:
        for rel in VINTAGE_SOURCES:                 # tuple order is the hash order
            h.update(rel.encode("utf-8"))
            path = _REPO / rel
            try:
                # normalise line endings: a CRLF/LF checkout difference is not a
                # logic change, and this repo warns about exactly that conversion
                h.update(path.read_bytes().replace(b"\r\n", b"\n"))
            except OSError:
                h.update(b"<missing>")
    except Exception:
        return UNKNOWN_VINTAGE
    return h.hexdigest()[:12]


@functools.lru_cache(maxsize=1)
def git_sha() -> str:
    """Short repo HEAD, ``+dirty`` when the tree is modified. Provenance for logs only."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(_REPO), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        if not sha:
            return UNKNOWN_VINTAGE
        dirty = subprocess.run(
            ["git", "-C", str(_REPO), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
        return f"{sha}+dirty" if dirty else sha
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_VINTAGE
