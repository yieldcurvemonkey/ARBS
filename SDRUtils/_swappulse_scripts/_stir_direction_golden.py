"""Bit-identical correctness harness for the direction-backfill optimization.

`capture_golden` runs the (unchanged) classifier for a date and returns a
canonical frame of every stored column. `diff_against_golden` returns the rows
that differ field-by-field (empty == byte-for-byte identical). Used as the merge
gate for every optimization phase. Dev-only; not imported by production code.
"""
from __future__ import annotations

import math

import pandas as pd

from SDRUtils._swappulse_scripts.backfill_stir_direction import (
    DIRECTION_COLUMNS, run_classification,
)


def _canonical(rows) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    for c in DIRECTION_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[DIRECTION_COLUMNS].copy()
    # quality_flags is a list -> make it hashable/comparable as a tuple
    df["quality_flags"] = df["quality_flags"].apply(
        lambda v: tuple(v) if isinstance(v, (list, tuple)) else v)
    return df.sort_values("unit_key").reset_index(drop=True)


def capture_golden(conn, date, stats=None) -> pd.DataFrame:
    """Run the classifier (dry-run, no DB write) and return the canonical frame.

    `stats` defaults to an empty frame so calibration is skipped and the result
    depends only on the classification/pricing path we are optimizing.
    """
    if stats is None:
        stats = pd.DataFrame()
    rows = run_classification(conn, date, stats, dry_run=True)
    return _canonical(rows)


def _cell_equal(a, b) -> bool:
    # exact equality; NaN==NaN treated equal (bit-identical mandate: floats must
    # match exactly, but two None/NaN cells are considered the same).
    a_nan = isinstance(a, float) and math.isnan(a)
    b_nan = isinstance(b, float) and math.isnan(b)
    if a_nan or b_nan:
        return a_nan and b_nan
    if a is None or b is None:
        return a is None and b is None
    return a == b


def diff_against_golden(golden: pd.DataFrame, rows) -> pd.DataFrame:
    """Return rows/columns where `rows` differ from `golden`. Empty == identical."""
    cur = _canonical(rows)
    g = golden.reset_index(drop=True)
    out = []
    if list(g["unit_key"]) != list(cur["unit_key"]):
        gset, cset = set(g["unit_key"]), set(cur["unit_key"])
        for uk in sorted(gset - cset):
            out.append((-1, uk, "__unit_key__", "present", "MISSING"))
        for uk in sorted(cset - gset):
            out.append((-1, uk, "__unit_key__", "MISSING", "present"))
        # still field-diff the intersection on aligned frames
        g = g[g["unit_key"].isin(cset)].sort_values("unit_key").reset_index(drop=True)
        cur = cur[cur["unit_key"].isin(gset)].sort_values("unit_key").reset_index(drop=True)
    for col in DIRECTION_COLUMNS:
        ga, ca = g[col], cur[col]
        for i in range(len(g)):
            if not _cell_equal(ga.iat[i], ca.iat[i]):
                out.append((i, g["unit_key"].iat[i], col, ga.iat[i], ca.iat[i]))
    return pd.DataFrame(out, columns=["row", "unit_key", "col", "golden", "current"])
