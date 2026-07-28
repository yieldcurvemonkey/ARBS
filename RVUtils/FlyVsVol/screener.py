"""Fan the fly-vs-vol snapshot across triples and dates; z-score the gap series."""
from __future__ import annotations

import datetime
import logging
from typing import List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.FlyVsVol._types import (
    ContractMarginal,
    FlyDefinition,
    FlySnapshot,
    FlyVsVolConfig,
)
from RVUtils.FlyVsVol.metrics import build_fly_snapshot

logger = logging.getLogger(__name__)

__all__ = ["adjacent_triples", "run_fly_screener", "screener_table", "history_zscores"]


def adjacent_triples(symbols: Sequence[str]) -> List[FlyDefinition]:
    """All adjacent three-contract flies, preserving input order."""
    symbols = list(symbols)
    return [
        FlyDefinition(symbols[i], symbols[i + 1], symbols[i + 2])
        for i in range(len(symbols) - 2)
    ]


def run_fly_screener(
    marginals_by_symbol: Mapping[str, ContractMarginal],
    triples: Optional[Sequence[FlyDefinition]] = None,
    *,
    config: FlyVsVolConfig = FlyVsVolConfig(),
    corr: Optional[pd.DataFrame] = None,
    as_of: Optional[datetime.date] = None,
) -> List[FlySnapshot]:
    """Build a snapshot per triple; triples with a missing leg are skipped (logged).

    ``corr`` (symbol-indexed DataFrame) enables the Gaussian-copula overlay; a
    triple whose 3x3 slice has NaNs falls back to comonotone-only.
    """
    if triples is None:
        triples = adjacent_triples(list(marginals_by_symbol.keys()))
    snaps: List[FlySnapshot] = []
    for fly in triples:
        missing = [s for s in fly.symbols if s not in marginals_by_symbol]
        if missing:
            logger.info("skipping %s: missing marginals for %s", fly.label, missing)
            continue
        sub = None
        if corr is not None:
            try:
                sub = corr.reindex(index=fly.symbols, columns=fly.symbols).to_numpy(
                    dtype=float
                )
            except Exception:  # pragma: no cover - defensive
                sub = None
            if sub is not None and not np.all(np.isfinite(sub)):
                sub = None
        legs = [marginals_by_symbol[s] for s in fly.symbols]
        snaps.append(
            build_fly_snapshot(*legs, config=config, corr=sub, as_of=as_of)
        )
    return snaps


def screener_table(snapshots: Sequence[FlySnapshot]) -> pd.DataFrame:
    """One row per triple (index = label), sorted by |tail_rent_bp| descending."""
    if not snapshots:
        return pd.DataFrame()
    df = pd.DataFrame([s.to_row() for s in snapshots]).set_index("label")
    return df.reindex(df["tail_rent_bp"].abs().sort_values(ascending=False).index)


def history_zscores(
    history: pd.DataFrame,
    cols: Sequence[str],
    *,
    window: int = 120,
    min_periods: int = 40,
) -> pd.DataFrame:
    """Per-label rolling and full-sample z-scores for the given metric columns.

    ``history`` needs ``as_of`` and ``label`` columns; returns a sorted copy with
    ``{col}_z`` (rolling ``window``) and ``{col}_z_full`` added. Zero-variance
    windows yield NaN.
    """
    out = history.sort_values(["label", "as_of"]).reset_index(drop=True).copy()
    for col in cols:
        grp = out.groupby("label")[col]
        mean = grp.transform(
            lambda s: s.rolling(window, min_periods=min_periods).mean()
        )
        std = grp.transform(
            lambda s: s.rolling(window, min_periods=min_periods).std(ddof=0)
        )
        std = std.where(std > 1e-12)
        out[f"{col}_z"] = (out[col] - mean) / std
        fmean = grp.transform("mean")
        fstd = grp.transform(lambda s: s.std(ddof=0)).where(lambda s: s > 1e-12)
        out[f"{col}_z_full"] = (out[col] - fmean) / fstd
    return out
