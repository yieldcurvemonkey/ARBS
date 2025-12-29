import datetime
import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple, Union
from tqdm import tqdm
from collections import defaultdict, deque

import numpy as np
import pandas as pd
import QuantLib as ql
import pytz


NY_tz = pytz.timezone("America/New_York")
UTC_tz = pytz.timezone("UTC")


def _ensure_int64_epoch_seconds(ts: pd.Series) -> np.ndarray:
    # robust for tz-aware / naive
    t = pd.to_datetime(ts, errors="coerce", utc=True)
    # int64 ns -> seconds
    return (t.view("int64") // 1_000_000_000).astype(np.int64)


def _pv01_bucket(pv01: np.ndarray, tol: float) -> np.ndarray:
    # bucket by log scale so "within % tolerance" becomes "nearby buckets"
    # Use log to make constant relative width buckets.
    pv01_pos = np.maximum(pv01, 1e-12)
    return np.floor(np.log(pv01_pos) / np.log(1.0 + tol)).astype(np.int32)

