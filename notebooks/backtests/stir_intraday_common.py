"""Shared machinery for the SR3 4-hour intraday lab.

Deliberately thin. The structures are built by ``RVUtils.MeanRev.panel``'s
``add_strip_slots`` / ``enumerate_structures`` -- **the same functions the EOD
lab uses** -- so an intraday number and a daily number describe the same object
and the two labs can be compared without an adapter in between. That is what
made the EOD reconciliation (ratio 1.045 on the common window) a real check
rather than a coincidence.

Three conventions that are load-bearing here and easy to get wrong:

**``cm_slot`` is the BELLY.** ``enumerate_structures`` tags a structure with its
belly slot (``panel.py:118``), so for spacing ``s`` it runs ``1+s .. max_slot-s``.
Filtering ``cm_slot <= 4`` therefore keeps front legs 1-3 at 3m, 1-2 at 6m, only
slot 1 at 9m, and **nothing at all at 12m**. The front leg is
``cm_slot - spacing``; ``front_legs`` below filters on that so the spacings stay
comparable.

**Bar closes are trade prints, not mids.** They alternate between bid and offer,
which is mechanically mean-reverting. Roll's effective spread comes out at
0.94-1.36bp against the 2.0bp round trip charged, so the cost model is honest --
but one-bar "reversion" is pure bounce: VR(2) = 1 + rho(1) reproduces the
measured variance ratio to three decimals. Any short-horizon opportunity has to
be bounce-corrected before it is believed, and the correction is applied as a
scale factor rather than through ``E|X| = 0.798*sd``, because this data is
nowhere near normal (mean|move|/sd is 0.59-0.69, kurtosis 26-136, and 6-15% of
bar moves are exactly zero).

**The panel is a more volatile sample than the EOD one.** Barchart serves 240-min
bars from 2021-01; the EOD panel starts 2018-01. The intraday window is
dominated by the 2022-23 hiking cycle and excludes the quiet 2018-19 and ZIRP
2020 stretches, which is worth 32% on every dispersion statistic. Comparisons
against the daily lab must be run on the common window.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.MeanRev.diagnostics import (  # noqa: F401
    debounced_abs_move, roll_effective_spread, variance_ratio,
)

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "notebooks" / "data" / "stir_intraday"
EOD_DIR = REPO / "notebooks" / "data" / "sfr_fly_meanrev"

FLY_COST_BP = 2.0          # 4 contracts x 0.5bp round trip each
TICK_BP = 0.5
MAX_SLOT = 16
FRONT_LEG_MAX = 4
BARS_PER_DAY = 6
BAR_HOURS = (0, 4, 8, 12, 16, 20)          # Central
SETTLE_BAR_HOUR = 12                       # spans 12:00-16:00 CT, holds the 15:00 ET settle
FOMC_BAR_HOUR = 12                         # ... and the 13:00 CT decision
SPACINGS = ((1, "3m"), (2, "6m"), (3, "9m"), (4, "12m"))
HORIZONS = ((1, "4h"), (2, "8h"), (3, "12h"), (6, "1d"), (12, "2d"),
            (30, "5d"), (60, "10d"), (126, "21d"))

__all__ = [
    "DATA_DIR", "EOD_DIR", "FLY_COST_BP", "TICK_BP", "MAX_SLOT", "FRONT_LEG_MAX",
    "BARS_PER_DAY", "BAR_HOURS", "SETTLE_BAR_HOUR", "FOMC_BAR_HOUR", "SPACINGS",
    "HORIZONS", "load_bars", "structures", "front_legs", "roll_spread",
    "bounce_correction", "pond_table", "daily_slice", "nw_t",
]


def load_bars(*, drop_accruing: bool = True) -> pd.DataFrame:
    """The 4h contract panel, pre-accrual by default."""
    p = pd.read_parquet(DATA_DIR / "contracts.parquet")
    p["as_of"] = pd.to_datetime(p["as_of"])
    return p[~p["accruing"]].copy() if drop_accruing else p


def front_legs(st: pd.DataFrame, spacing: int, *, max_leg: int = FRONT_LEG_MAX):
    """Restrict to structures whose FRONT leg is within ``max_leg``.

    ``cm_slot`` is the belly, so the front leg is ``cm_slot - spacing``. Doing
    this on ``cm_slot`` directly silently selects a different (and at 12m, an
    empty) slice for every spacing.
    """
    return st[st["cm_slot"] - spacing <= max_leg]


def structures(slots: pd.DataFrame, spacing: int, *, front_only: bool = False,
               max_slot: int = MAX_SLOT) -> pd.DataFrame:
    """Wide (bar x key) panel of equally-spaced butterflies, in bp."""
    from RVUtils.MeanRev.panel import enumerate_structures
    st = enumerate_structures(slots, spacing=spacing, max_slot=max_slot)
    if front_only:
        st = front_legs(st, spacing)
    return st.pivot_table(index="as_of", columns="key", values="value",
                          aggfunc="first").sort_index()


def roll_spread(wide: pd.DataFrame) -> float:
    """Roll's effective spread -- see ``RVUtils.MeanRev.diagnostics``."""
    return roll_effective_spread(wide)


def bounce_correction(moves: pd.Series, roll: float) -> float:
    """E|move| net of the bid-ask bounce -- see ``RVUtils.MeanRev.diagnostics``."""
    return debounced_abs_move(moves, roll)


def pond_table(slots: pd.DataFrame, *, front_only: bool,
               cost_bp: float = FLY_COST_BP) -> pd.DataFrame:
    """E|move| and the oracle ceiling by spacing and horizon, bounce-corrected."""
    rows = []
    for sp, tag in SPACINGS:
        w = structures(slots, sp, front_only=front_only)
        if w.shape[1] == 0:
            continue
        roll = roll_spread(w)
        for h, lbl in HORIZONS:
            m = (w.shift(-h) - w).stack(future_stack=True).dropna()
            if len(m) < 200:
                continue
            raw = float(m.abs().mean())
            deb = bounce_correction(m, roll)
            rows.append({"spacing": tag, "spacing_m": 3 * sp, "horizon": lbl,
                         "bars": h, "n": len(m), "roll_bp": roll,
                         "absmove_raw": raw, "absmove_debounced": deb,
                         "oracle_raw": raw - cost_bp,
                         "oracle_debounced": deb - cost_bp,
                         "p_beat_cost": float((m.abs() > cost_bp).mean())})
    return pd.DataFrame(rows)


def daily_slice(panel: pd.DataFrame, hour: int) -> pd.DataFrame:
    """One observation per DAY, taken from the bar closing at ``hour`` Central.

    Used to ask what execution timing is worth: six panels, identical in every
    respect except the time of day the position is opened and closed.
    """
    sub = panel[panel["bar_hour_ct"] == hour].copy()
    sub["as_of"] = sub["as_of"].dt.normalize()
    return sub.drop_duplicates(subset=["as_of", "code"], keep="last")


def nw_t(x, lags: int = 5) -> float:
    """Newey-West t of a mean, so overlapping configurations are not over-trusted."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 5:
        return float("nan")
    e = x - x.mean()
    v = float(e @ e / n)
    for L in range(1, min(lags, n - 1) + 1):
        v += 2.0 * (1.0 - L / (lags + 1.0)) * float(e[L:] @ e[:-L] / n)
    return float(x.mean() / np.sqrt(max(v, 1e-18) / n))
