"""Best-effort alpha-join: resolve ``original_execution_timestamp`` via lineage.

Part of the execution-vs-event timestamp integration (2026-07-17 spec §6).

For beta/gamma clearing (``NEWT-CLRG``) and novation (``NEWT-NOVA``) rows the
trade's *original* economic execution belongs to a different UTI — the alpha —
linked in public SDR data via ``[#2] Original Dissemination Identifier``. We
reuse the existing :func:`SDRUtils.core.graph_resolver.build_synthetic_uti_mapping`
connected-components clustering to find, per lineage component, the earliest
NEWT execution and attribute it to every member row.

Coverage is intentionally *partial*: Prior UTI / Original Dissemination
Identifier is frequently masked in public dissemination, and the alpha's
original ``NEWT-TRAD`` may not be present in the frame at all (it was executed
days/months earlier). Rows we cannot link keep
``original_execution_timestamp == execution_timestamp`` and are flagged
``original_execution_source='fallback'``. Downstream analytics must consult the
reconciliation report (spec §6, monitoring) before trusting ``alpha_lag_seconds``.

The signed invariant is ``original_execution_timestamp <= execution_timestamp``
so ``alpha_lag_seconds = execution - original >= 0``.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from SDRUtils.core.graph_resolver import (
    _normalize_identifier,
    build_synthetic_uti_mapping,
)

# original_execution_source provenance values
SOURCE_NEWT = "newt"          # row is its own origin (no earlier lineage found)
SOURCE_LINEAGE = "lineage"    # resolved to an earlier alpha via public lineage
SOURCE_FALLBACK = "fallback"  # set upstream (e.g. classify-time missing execution)


def resolve_original_execution(
    df: pd.DataFrame,
    *,
    execution_col: str = "execution_timestamp",
    dissemination_col: str = "trade_id",
    original_col: str = "original_dissemination_id",
    event_action_col: str = "event_action",
    event_ts_col: str = "event_timestamp",
    original_execution_col: str = "original_execution_timestamp",
    source_col: str = "original_execution_source",
    alpha_lag_col: str = "alpha_lag_seconds",
) -> pd.DataFrame:
    """Add ``original_execution_timestamp`` / ``original_execution_source`` /
    ``alpha_lag_seconds`` to ``df`` via best-effort lineage resolution.

    Idempotent and non-destructive: an existing ``original_execution_source``
    of ``'fallback'`` (set at classify time when Execution Timestamp was
    missing) is preserved. Rows without resolvable lineage default to their own
    execution timestamp with source ``'newt'``.
    """
    out = df.copy()
    n = len(out)

    if execution_col not in out.columns or n == 0:
        # Nothing to anchor on — degrade gracefully.
        out[original_execution_col] = out.get(execution_col)
        out[source_col] = out.get(source_col)
        out[alpha_lag_col] = 0.0
        return out

    exec_ts = pd.to_datetime(out[execution_col], utc=True, errors="coerce")

    # Default: each row is its own origin.
    original = exec_ts.copy()
    source = pd.Series([None] * n, index=out.index, dtype="object")

    have_lineage = (
        dissemination_col in out.columns and original_col in out.columns
    )
    if have_lineage:
        work = pd.DataFrame(
            {
                dissemination_col: out[dissemination_col].values,
                original_col: out[original_col].values,
                event_ts_col: pd.to_datetime(
                    out.get(event_ts_col), utc=True, errors="coerce"
                ).values
                if event_ts_col in out.columns
                else pd.NaT,
                # graph_resolver's anchor filter matches action == "NEWT"
                # exactly; the tape carries "NEWT-CLRG"/"NEWT-TRAD" in
                # event_action, so pass the prefix.
                "_action_prefix": out[event_action_col]
                .astype(str)
                .str.split("-")
                .str[0]
                .values
                if event_action_col in out.columns
                else "",
            }
        )

        mapping, members = build_synthetic_uti_mapping(
            work,
            dissemination_col=dissemination_col,
            original_col=original_col,
            action_col="_action_prefix",
            event_timestamp_col=event_ts_col,
        )

        # Anchor (synthetic UTI) -> earliest execution timestamp among its
        # members. The graph anchor is the earliest NEWT by event time; we take
        # its *execution* time as the original execution.
        # Iterate the Series (NOT .values, which drops tz -> naive/aware
        # comparison errors); keep everything tz-aware UTC.
        norm_list = out[dissemination_col].map(_normalize_identifier).tolist()
        exec_list = list(exec_ts)
        id_to_exec: dict[str, pd.Timestamp] = {}
        for did, ets in zip(norm_list, exec_list):
            if did is None or pd.isna(ets):
                continue
            prev = id_to_exec.get(did)
            if prev is None or ets < prev:
                id_to_exec[did] = ets

        anchor_exec: dict[str, pd.Timestamp] = {}
        for anchor, member_ids in members.items():
            candidates = [id_to_exec[m] for m in member_ids if m in id_to_exec]
            anchor_exec[anchor] = min(candidates) if candidates else pd.NaT

        for i, did in enumerate(norm_list):
            if did is None:
                continue
            anchor = mapping.get(did)
            if anchor is None:
                continue
            a_exec = anchor_exec.get(anchor)
            row_exec = exec_list[i]
            if a_exec is not None and not pd.isna(a_exec) and not pd.isna(row_exec):
                if a_exec < row_exec:
                    original.iloc[i] = a_exec
                    source.iloc[i] = SOURCE_LINEAGE

    # Preserve any upstream classify-time fallback flag; fill the rest as NEWT.
    if source_col in out.columns:
        prior = out[source_col]
        source = source.where(source.notna(), prior)
    source = source.where(source.notna(), SOURCE_NEWT)

    alpha_lag = (exec_ts - pd.to_datetime(original, utc=True, errors="coerce"))
    alpha_lag_seconds = alpha_lag.dt.total_seconds().clip(lower=0).fillna(0.0)

    out[original_execution_col] = original
    out[source_col] = source
    out[alpha_lag_col] = alpha_lag_seconds
    return out
