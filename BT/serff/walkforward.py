"""Walk-forward (point-in-time) estimation for the SERFF layers.

Every fit at a refit date consumes only panel rows *published* by that date
(`published_at <= refit timestamp`), so coefficients at each decision date
reflect information actually available then.  Refit cadence, window style
and activation thresholds come from SerffWalkForwardConfig.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from BT.serff.config import SerffModelConfig, SerffWalkForwardConfig
from BT.serff.layers import SerffFit, fit_layers


@dataclass
class WalkForwardFits:
    fits: Dict[pd.Timestamp, SerffFit]
    coefficient_history: pd.DataFrame     # refit date x coefficient
    regime_slope_history: pd.DataFrame    # refit date x regime simple-fit slope
    config: SerffWalkForwardConfig

    def as_of(self, decision_ts: pd.Timestamp | datetime.date) -> Optional[SerffFit]:
        """Latest fit whose refit date is <= the decision timestamp."""
        ts = pd.Timestamp(decision_ts)
        keys = [k for k in self.fits if k <= ts]
        if not keys:
            return None
        return self.fits[max(keys)]


def refit_dates(panel: pd.DataFrame, wf: SerffWalkForwardConfig) -> List[pd.Timestamp]:
    idx = panel.index
    if len(idx) == 0:
        return []
    first_allowed = idx[min(wf.min_train_days, len(idx) - 1)]
    schedule = pd.date_range(first_allowed, idx.max(), freq=wf.refit_frequency)
    # snap each schedule date to the last panel date <= it
    out: List[pd.Timestamp] = []
    for d in schedule:
        loc = idx.searchsorted(d, side="right") - 1
        if loc >= 0:
            snapped = idx[loc]
            if not out or snapped > out[-1]:
                out.append(snapped)
    return out


def walk_forward_fits(
    panel: pd.DataFrame,
    model_cfg: Optional[SerffModelConfig] = None,
    wf_cfg: Optional[SerffWalkForwardConfig] = None,
    *,
    show_progress: bool = False,
) -> WalkForwardFits:
    """Fit the layers at each refit date on point-in-time data."""
    model_cfg = model_cfg or SerffModelConfig()
    wf_cfg = wf_cfg or SerffWalkForwardConfig()

    dates = refit_dates(panel, wf_cfg)
    iterator = dates
    if show_progress:
        try:
            from tqdm import tqdm

            iterator = tqdm(dates, desc="SERFF walk-forward fits")
        except Exception:
            pass

    has_pub = "published_at" in panel.columns
    fits: Dict[pd.Timestamp, SerffFit] = {}
    coef_rows: List[pd.Series] = []
    slope_rows: List[pd.Series] = []

    for refit_ts in iterator:
        cutoff = refit_ts + pd.Timedelta(hours=23, minutes=59)
        train = panel[panel["published_at"] <= cutoff] if has_pub else panel.loc[:refit_ts]
        if wf_cfg.min_train_days and len(train) < wf_cfg.min_train_days:
            continue
        if not wf_cfg.expanding and wf_cfg.rolling_window_days:
            train = train.iloc[-wf_cfg.rolling_window_days :]

        fit = fit_layers(train, model_cfg, train_end=refit_ts)
        if fit.turn is not None and fit.turn.n_month_ends < wf_cfg.min_turn_events:
            fit = SerffFit(level=fit.level, turn=None, config=model_cfg, train_end=fit.train_end)
        fits[refit_ts] = fit

        coef_rows.append(pd.Series(fit.level.model.params, name=refit_ts))
        slope_rows.append(fit.level.per_regime["slope"].rename(refit_ts))

    coef_hist = pd.DataFrame(coef_rows) if coef_rows else pd.DataFrame()
    slope_hist = pd.DataFrame(slope_rows) if slope_rows else pd.DataFrame()
    return WalkForwardFits(fits=fits, coefficient_history=coef_hist, regime_slope_history=slope_hist, config=wf_cfg)
