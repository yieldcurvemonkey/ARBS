"""Lifecycle-linked unwind extraction for ladder netting (ladder spec section 3b/6).

Netting applies ONLY to unwind events whose lineage resolves to an
already-classified print. Generic opposite-direction prints are new flow.
Findings from the lineage probe (Task 5 Step 1): No lineage columns (original_dissemination_identifier, prior_uti, prior_usi) found in the tape legs table as of 2026-07-14. Zero ECONOMIC_UNWIND rows on 07/10. extract_unwind_events returns empty frame; netting is a no-op.
If no lineage column exists in the tape, extract_unwind_events returns an
empty frame and netting is a documented no-op pending a tape lineage column.
"""
from __future__ import annotations

import pandas as pd

from SDRUtils.stir_flow import ladder_conventions as conv
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

LINEAGE_CANDIDATES = ("original_dissemination_identifier", "prior_uti", "prior_usi")
_EMPTY = pd.DataFrame(columns=["unit_key", "unwind_visibility_ts"])


def _match_unwinds_frame(unwind_rows: pd.DataFrame, classified: set, *, lineage_col: str) -> pd.DataFrame:
    if unwind_rows.empty:
        return _EMPTY.copy()
    hits = unwind_rows[unwind_rows[lineage_col].isin(classified)]
    if hits.empty:
        return _EMPTY.copy()
    return pd.DataFrame({
        "unit_key": hits[lineage_col].values,
        # No on_facility/cleared/is_capped data available at this call site
        # (unwind rows only carry is_block) -> always resolves INDETERMINATE
        # (+60min) under the Part 43 Appendix C classes. That's the honest,
        # conservative answer given what's known here -- see
        # ladder_conventions.visibility_class.
        "unwind_visibility_ts": [
            conv.visibility_timestamp(ts, is_block=bool(b))
            for ts, b in zip(hits["execution_timestamp"], hits["is_block"].fillna(False))
        ],
    })


def extract_unwind_events(conn, start_date, end_date, classified_unit_keys: set) -> pd.DataFrame:
    cols = pd.read_sql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %(t)s", conn, params={"t": LEGS_TABLE},
    )["column_name"].tolist()
    lineage_col = next((c for c in LINEAGE_CANDIDATES if c in cols), None)
    if lineage_col is None:
        return _EMPTY.copy()
    rows = pd.read_sql(
        f"SELECT trade_id, {lineage_col}, execution_timestamp, is_block "
        f"FROM {LEGS_TABLE} "
        "WHERE economic_class = 'ECONOMIC_UNWIND' AND as_of_date BETWEEN %(s)s AND %(e)s",
        conn, params={"s": start_date, "e": end_date},
    )
    return _match_unwinds_frame(rows, classified_unit_keys, lineage_col=lineage_col)
