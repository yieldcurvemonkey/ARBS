"""Probe: can the warmed intraday TS store serve 1-min IRS par rates over the R0 window?"""
import os, time
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
os.environ.setdefault("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")
import pandas as pd

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Utils.timeseries import ComputedTimeseriesStore  # noqa
import importlib

# discover the read entry point the warm script itself documents
warm = importlib.import_module("scripts.citivelo_intraday_ts_warm")
print("SOURCE", warm.SOURCE, "CURVE", warm.CURVE, "MINUTE_ASSET", warm.MINUTE_ASSET)
print("n spot tenors", len(warm.SPOT_TENORS))
