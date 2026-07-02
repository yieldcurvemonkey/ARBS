"""The three SERFF model layers.

Layer 0 (mechanical) lives in ``mechanics.bootstrap_policy_path`` -- the
policy path is read off the ZQ strip, never regressed.  This module fits:

Layer 1 -- level model on NON-TURN days:
    spread_bp ~ C(regime) + C(regime):ln_liq + tga_gdp + is_mid,  HAC(cfg.hac_lags)
    (log liquidity/GDP linearizes the convex reserve-demand curve; pooled R^2
    is uninformative across regimes -- per-regime fits are the diagnostic)

Layer 2 -- turn model on month-end observations (hurdle):
    occurrence:  Logit( spike > threshold ~ const + ln_liq + is_qe )
    magnitude:   QuantReg( spike ~ ln_liq + is_qe ) at cfg.quantiles

Defaults reproduce the standalone prototype; every knob comes from
SerffModelConfig.
"""

from __future__ import annotations

import datetime
import warnings
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from BT.serff.config import SerffModelConfig

LEVEL_FORMULA = "spread ~ C(regime) + C(regime):ln_liq + tga_gdp + is_mid"
TURN_FORMULA = "spike ~ ln_liq + is_qe"


@dataclass
class LevelFit:
    """Layer 1: pooled regime-interaction model + per-regime simple fits."""

    model: object                       # statsmodels results (HAC errors)
    per_regime: pd.DataFrame            # regime -> slope/R2/n of simple fit
    n_obs: int
    train_end: pd.Timestamp

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Expected non-turn spread (bp) for rows with regime/ln_liq/tga_gdp/is_mid."""
        return np.asarray(self.model.predict(rows), dtype=float).ravel()

    def regime_slopes(self) -> pd.Series:
        params = self.model.params
        slopes = params[[p for p in params.index if ":ln_liq" in p]]
        slopes.index = [p.split("[")[-1].split("]")[0] for p in slopes.index]
        return slopes


@dataclass
class TurnFit:
    """Layer 2: hurdle (logit occurrence + quantile magnitudes)."""

    logit: object
    quantiles: Dict[float, object]
    logit_cols: Tuple[str, ...]
    n_month_ends: int
    n_quarter_ends: int
    n_hits: int
    train_end: pd.Timestamp

    def predict(self, ln_liq: float, is_qe: bool) -> Dict[str, float]:
        row = pd.DataFrame({"const": [1.0], "ln_liq": [float(ln_liq)], "is_qe": [float(is_qe)]})
        p_hit = float(np.asarray(self.logit.predict(row[list(self.logit_cols)])).ravel()[0])
        out = {"p_hit": p_hit}
        qrow = pd.DataFrame({"ln_liq": [float(ln_liq)], "is_qe": [float(is_qe)]})
        for q, m in self.quantiles.items():
            out[f"q{int(round(q * 100)):02d}"] = float(np.asarray(m.predict(qrow)).ravel()[0])
        return out


@dataclass
class SerffFit:
    """A point-in-time fit of both statistical layers."""

    level: LevelFit
    turn: Optional[TurnFit]
    config: SerffModelConfig
    train_end: pd.Timestamp
    meta: Dict[str, object] = field(default_factory=dict)


# --------------------------------------------------------------------------
# fitting
# --------------------------------------------------------------------------
def fit_level(panel: pd.DataFrame, cfg: SerffModelConfig, train_end: Optional[pd.Timestamp] = None) -> LevelFit:
    lvl = panel[~panel["turn_window"]].copy()
    lvl["is_mid"] = lvl["is_mid"].astype(float)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = smf.ols(LEVEL_FORMULA, data=lvl).fit(cov_type="HAC", cov_kwds={"maxlags": cfg.hac_lags})

    rows = []
    for rg, g in lvl.groupby("regime", observed=True):
        if len(g) < 10 or g["ln_liq"].std() == 0:
            rows.append({"regime": rg, "slope": np.nan, "r2": np.nan, "n": len(g)})
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f = smf.ols("spread ~ ln_liq", data=g).fit()
        rows.append({"regime": rg, "slope": float(f.params["ln_liq"]), "r2": float(f.rsquared), "n": int(f.nobs)})
    per_regime = pd.DataFrame(rows).set_index("regime")

    return LevelFit(
        model=model,
        per_regime=per_regime,
        n_obs=int(model.nobs),
        train_end=train_end if train_end is not None else lvl.index.max(),
    )


def fit_turn(panel: pd.DataFrame, cfg: SerffModelConfig, train_end: Optional[pd.Timestamp] = None) -> Optional[TurnFit]:
    turns = panel[panel["is_me"]].dropna(subset=["local_base"]).copy()
    if turns.empty:
        return None
    turns["hit"] = (turns["spike"] > cfg.spike_threshold_bp).astype(int)
    if turns["hit"].nunique() < 2:
        return None

    X = sm.add_constant(turns[["ln_liq", "is_qe"]].astype(float))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            logit = sm.Logit(turns["hit"], X).fit(disp=0)
        except Exception:
            logit = sm.GLM(turns["hit"], X, family=sm.families.Binomial()).fit()

        quants: Dict[float, object] = {}
        qdata = turns.copy()
        qdata["is_qe"] = qdata["is_qe"].astype(float)
        for q in cfg.quantiles:
            quants[q] = smf.quantreg(TURN_FORMULA, qdata).fit(q=q)

    return TurnFit(
        logit=logit,
        quantiles=quants,
        logit_cols=tuple(X.columns),
        n_month_ends=len(turns),
        n_quarter_ends=int(turns["is_qe"].sum()),
        n_hits=int(turns["hit"].sum()),
        train_end=train_end if train_end is not None else turns.index.max(),
    )


def fit_layers(
    panel: pd.DataFrame,
    cfg: Optional[SerffModelConfig] = None,
    *,
    train_end: Optional[pd.Timestamp | datetime.date] = None,
) -> SerffFit:
    """Fit both statistical layers on (optionally truncated) panel rows."""
    cfg = cfg or SerffModelConfig()
    if train_end is not None:
        train_end = pd.Timestamp(train_end)
        panel = panel.loc[:train_end]
    else:
        train_end = panel.index.max()

    level = fit_level(panel, cfg, train_end)
    turn = fit_turn(panel, cfg, train_end)
    return SerffFit(level=level, turn=turn, config=cfg, train_end=train_end)


# --------------------------------------------------------------------------
# prediction helpers used by the ledger
# --------------------------------------------------------------------------
def baseline_row(
    date: pd.Timestamp,
    *,
    regime: str,
    ln_liq: float,
    tga_gdp: float,
    mid_month_days: Tuple[int, ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "regime": [regime],
            "ln_liq": [float(ln_liq)],
            "tga_gdp": [float(tga_gdp)],
            "is_mid": [1.0 if date.day in mid_month_days else 0.0],
        },
        index=[date],
    )
