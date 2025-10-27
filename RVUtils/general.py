import pandas as pd

import gs_quant.timeseries.econometrics as gsqtse


def realized_bpvol(x: pd.Series, w=20):
    return gsqtse.volatility(x=x, w=w, returns_type=gsqtse.Returns.ABSOLUTE)