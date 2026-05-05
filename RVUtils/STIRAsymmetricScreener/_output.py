"""Output / serialization helpers (spec §7)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from RVUtils.STIRAsymmetricScreener._types import ScreenerSnapshot


def snapshot_to_dataframe(snapshot: ScreenerSnapshot) -> pd.DataFrame:
    return snapshot.to_dataframe()


def write_snapshot(
    snapshot: ScreenerSnapshot,
    *,
    root: str = "data/screener_results/stir_asymmetric_screener",
    fmt: str = "parquet",
) -> Path:
    """Persist the snapshot under ``root/<as_of>/snapshot.<fmt>``.

    Returns the path to the written file. JSON sidecar with config / warnings
    written alongside.
    """
    out_dir = Path(root) / snapshot.as_of.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    df = snapshot_to_dataframe(snapshot)
    if fmt == "parquet":
        path = out_dir / "snapshot.parquet"
        # Convert non-numpy-native columns (lists/dicts) to JSON strings to
        # avoid pyarrow nested-type issues with parquet.
        df = df.copy()
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].apply(
                    lambda v: json.dumps(v, default=str) if isinstance(v, (list, dict)) else v
                )
        df.to_parquet(path, index=False)
    elif fmt == "csv":
        path = out_dir / "snapshot.csv"
        df.to_csv(path, index=False)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    sidecar = out_dir / "snapshot.meta.json"
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "as_of": snapshot.as_of.isoformat(),
                "n_results": len(snapshot.results),
                "config_summary": snapshot.config_summary,
                "run_warnings": list(snapshot.run_warnings),
            },
            fh,
            indent=2,
            default=str,
        )

    return path
