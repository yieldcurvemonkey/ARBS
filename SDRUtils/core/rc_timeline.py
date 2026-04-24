"""Reporting counterparty (RC) timeline per UTI.

§45.8(g) preserves UTI across novations even though the Reporting
Counterparty may change. Any aggregation keyed on the *current* RC
mislabels pre-novation volume as belonging to the new RC. This module
produces a per-UTI RC history so aggregators can attribute flow to the
correct RC at each point in time.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pandas as pd


def build_rc_timeline(uti_group: pd.DataFrame) -> List[Tuple[pd.Timestamp, str]]:
    """Build per-UTI RC history.

    Args:
        uti_group: DataFrame rows for a single UTI, sorted by event
            timestamp. Columns expected: ``event_timestamp``,
            ``Reporting counterparty ID``.

    Returns:
        List of (timestamp, reporting_counterparty_id) tuples in order.
        Consecutive duplicates are collapsed.
    """
    if uti_group.empty:
        return []

    ts_col = (
        "event_timestamp"
        if "event_timestamp" in uti_group.columns
        else "Event timestamp"
    )
    rc_col = (
        "Reporting counterparty ID"
        if "Reporting counterparty ID" in uti_group.columns
        else "reporting_counterparty_id"
    )
    if rc_col not in uti_group.columns:
        return []

    ordered = uti_group.sort_values(ts_col) if ts_col in uti_group.columns else uti_group

    timeline: List[Tuple[pd.Timestamp, str]] = []
    last_rc: str | None = None
    for _, row in ordered.iterrows():
        rc_raw = row.get(rc_col)
        if rc_raw is None or (isinstance(rc_raw, float) and pd.isna(rc_raw)):
            continue
        rc = str(rc_raw).strip()
        if not rc:
            continue
        if rc == last_rc:
            continue
        ts = row.get(ts_col)
        try:
            ts_parsed = pd.to_datetime(ts, errors="coerce", utc=True)
        except Exception:
            ts_parsed = pd.NaT
        timeline.append((ts_parsed, rc))
        last_rc = rc
    return timeline


def rc_timeline_to_json(timeline: List[Tuple[pd.Timestamp, str]]) -> str:
    """Serialize an RC timeline to a JSON string for column storage."""
    out = []
    for ts, rc in timeline:
        ts_str = ts.isoformat() if ts is not None and not pd.isna(ts) else None
        out.append({"ts": ts_str, "rc": rc})
    return json.dumps(out)


def enrich_rc_timeline_column(
    df: pd.DataFrame,
    *,
    uti_col: str = "trade_id",
) -> pd.DataFrame:
    """Materialize ``rc_timeline_json`` on a DataFrame of SDR rows.

    Groups rows by UTI (default ``trade_id``), builds the RC history per
    group, and broadcasts the JSON string onto every row in the group.
    """
    if uti_col not in df.columns or df.empty:
        df["rc_timeline_json"] = ""
        return df

    timelines: Dict[Any, str] = {}
    for uti, group in df.groupby(uti_col, sort=False):
        timelines[uti] = rc_timeline_to_json(build_rc_timeline(group))
    df["rc_timeline_json"] = df[uti_col].map(timelines).fillna("")
    return df
