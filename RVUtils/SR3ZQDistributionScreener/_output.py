"""Output / serialization helpers."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from RVUtils.SR3ZQDistributionScreener._types import SignalRecord


@dataclass(frozen=True)
class ScreenerSnapshot:
    as_of: datetime.date
    records: Tuple[SignalRecord, ...]
    config_summary: Dict[str, Any]
    run_warnings: Tuple[str, ...] = ()

    def to_dataframe(self) -> pd.DataFrame:
        if not self.records:
            return pd.DataFrame()
        return pd.DataFrame([r.to_dict() for r in self.records])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "records": [r.to_dict() for r in self.records],
            "config_summary": self.config_summary,
            "run_warnings": list(self.run_warnings),
        }


def snapshot_to_dataframe(snapshot: ScreenerSnapshot) -> pd.DataFrame:
    return snapshot.to_dataframe()


def write_snapshot(
    snapshot: ScreenerSnapshot,
    *,
    root: str = "data/screener_results/sr3_zq_distribution_screener",
    fmt: str = "parquet",
) -> Path:
    out_dir = Path(root) / snapshot.as_of.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    df = snapshot_to_dataframe(snapshot)
    if fmt == "parquet":
        path = out_dir / "snapshot.parquet"
        df = df.copy()
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].apply(
                    lambda v: json.dumps(v, default=str)
                    if isinstance(v, (list, dict))
                    else v
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
                "n_records": len(snapshot.records),
                "config_summary": snapshot.config_summary,
                "run_warnings": list(snapshot.run_warnings),
            },
            fh,
            indent=2,
            default=str,
        )

    return path
