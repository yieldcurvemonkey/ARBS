"""IV/RV diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IVRVDiagnostic:
    contract: str
    iv_bp: float
    rv_bp: float
    iv_rv_ratio: float


def realized_vol_bp(daily_rate_changes_bp: pd.Series, *, periods_per_year: int = 252) -> float:
    """Annualize a series of daily rate changes (bp) into bp/yr realized vol."""
    s = daily_rate_changes_bp.dropna()
    if len(s) < 2:
        return float("nan")
    return float(s.std(ddof=1) * np.sqrt(periods_per_year))


def iv_rv_diagnostic(contract: str, *, iv_bp: float, rv_bp: float) -> IVRVDiagnostic:
    ratio = iv_bp / rv_bp if rv_bp > 0 else float("inf")
    return IVRVDiagnostic(contract=contract, iv_bp=iv_bp, rv_bp=rv_bp, iv_rv_ratio=ratio)
