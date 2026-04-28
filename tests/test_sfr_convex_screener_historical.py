import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener import Leg
from RVUtils.SFRConvexScreener._historical import (
    HistoricalAsymmetry,
    historical_asymmetry_summary,
    rolling_structure_payoffs_bp,
)


def test_rolling_structure_payoffs_simple_pair():
    """Front price ↑ (rate ↓), back price ↓ (rate ↑). For long-rate calendar
    weights (+1, -1), structure rate change = Δr_front - Δr_back =
    -0.158% - (+0.158%) = -0.316% over 63 days → -31.6 bp."""
    dates = pd.bdate_range("2025-01-01", periods=200)
    df = pd.DataFrame(
        {
            "SFRZ26": np.linspace(96.0, 96.5, 200),
            "SFRH27": np.linspace(96.5, 96.0, 200),
        },
        index=dates,
    )
    legs = (Leg("SFRZ26", 1, 96.0, 25), Leg("SFRH27", -1, 96.0, 25))
    series = rolling_structure_payoffs_bp(df, legs=legs, horizon_days=63)
    assert isinstance(series, pd.Series)
    assert -40 < series.dropna().mean() < -25


def test_historical_asymmetry_summary_basic():
    samples = pd.Series([1.0, 2.0, -0.5, 3.0, -1.0, 4.0, 5.0])
    summary = historical_asymmetry_summary(samples, current_rn_asymmetry=2.0)
    assert isinstance(summary, HistoricalAsymmetry)
    assert summary.n_observations == 7
