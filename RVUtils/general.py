# ABOUTME: General utility functions for relative value analysis
# ABOUTME: Common helpers and calculations used across RV strategies
import pandas as pd

import gs_quant.timeseries.econometrics as gsqtse


def realized_bpvol(x: pd.Series, w=20):
    return gsqtse.volatility(x=x, w=w, returns_type=gsqtse.Returns.ABSOLUTE)