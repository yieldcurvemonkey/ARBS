"""Single source of truth for the ARBS-owned tape table generation.

The USD-swaps tape has two writers. ``arbs_usd_swap_tape_*_v2`` is owned by
the ``run_swaptape`` cron job on the host ``sky`` (``/home/peter/SwapPulse``),
which serves a different front end and must keep running. ARBS owns ``_v3``.

Every table, view, and index name the ARBS pipeline writes derives from
``TAPE_GENERATION`` here, so moving to a future generation is a one-line
change and no literal suffix is left stranded in a query.
"""
from __future__ import annotations

import os

TAPE_GENERATION = "v3"

# Index and constraint names are schema-global in Postgres, so they must
# carry the generation too. `CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_exec
# ON <a v3 table>` matches the *existing v2 index name*, skips, and reports
# success -- leaving the new generation silently unindexed on millions of
# rows with nothing raised.
IDX_INFIX = TAPE_GENERATION


def _t(base: str) -> str:
    return f"arbs_usd_swap_{base}_{TAPE_GENERATION}"


PACKAGES_TABLE = _t("tape_packages")
LEGS_TABLE = _t("tape_legs")
RUNS_TABLE = _t("tape_ingestion_runs")
DISPLAY_VIEW = _t("tape_display")
OVERRIDES_TABLE = _t("tape_overrides")
OVERRIDE_MEMBERS_TABLE = _t("tape_override_members")
OVERRIDE_HISTORY_TABLE = _t("tape_override_history")
NOTES_TABLE = _t("tape_notes")
VWAP_TABLE = _t("vwap_daily")
SIGNAL_TABLE = _t("tape_signal")
QUALITY_VIEW = _t("tape_quality_daily")

# Deliberately NOT versioned: keyed by its own UUID and shared with the
# classification stage (``ingest_usdswaps.py``), which stays on v2.
MANUAL_LINKS_TABLE = "arbs_usd_swap_manual_links_v2"


def assert_writable_generation() -> None:
    """Refuse to write a tape generation ARBS does not own.

    Called from every write path. The failure this prevents is not
    hypothetical: ARBS and the ``sky`` job both delete-and-rewrite a whole
    ``as_of`` day, so a misconfigured run destroys the other front end's
    data for that day rather than merely duplicating it.
    """
    if TAPE_GENERATION == "v2" and os.getenv("ARBS_ALLOW_V2_WRITES") != "1":
        raise RuntimeError(
            "Refusing to write the _v2 tape: it is owned by the `sky` "
            "run_swaptape job and serves a different front end. "
            "Set ARBS_ALLOW_V2_WRITES=1 to override."
        )
