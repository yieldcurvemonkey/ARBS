import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener._ivrv import (
    IVRVDiagnostic,
    iv_rv_diagnostic,
    realized_vol_bp,
)


def test_realized_vol_bp_matches_simple_std():
    rng = np.random.default_rng(0)
    daily_changes_bp = rng.standard_normal(63)
    rv = realized_vol_bp(pd.Series(daily_changes_bp))
    assert 14.0 < rv < 18.0


def test_iv_rv_diagnostic_returns_ratio():
    iv_bp = 80.0
    rv_bp = 65.0
    diag = iv_rv_diagnostic("SFRZ26", iv_bp=iv_bp, rv_bp=rv_bp)
    assert diag.contract == "SFRZ26"
    assert abs(diag.iv_rv_ratio - (iv_bp / rv_bp)) < 1e-9
