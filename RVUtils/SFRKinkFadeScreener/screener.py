"""SFR Kink-Fade Live Screener.

Surfaces actionable BF_6M kink-fading signals using the production config
(buy_kink, reds, z>2.0, FOMC+HL+roll blackout). Wraps the existing
sfr_kink_fade.py analytics pipeline into the standard build_snapshot() pattern.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.signals.sfr_cal_spread_rv import (
    SFRCalSpreadRVConfig,
    load_rate_panel,
    compute_fly_curve,
    resolve_cm_to_specific,
)
from BT.signals.sfr_kink_fade import (
    KinkStructure,
    compute_zscore_ts,
    compute_percentile_rank,
    compute_cross_sectional_rank,
    compute_rolling_halflife,
    compute_roll,
    days_to_next_fomc,
    days_to_next_imm_roll,
)

logger = logging.getLogger(__name__)


@dataclass
class KinkFadeScreenerConfig:
    source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    n_contracts: int = 12
    zscore_window: int = 60
    vol_window: int = 20
    halflife_window: int = 120
    lookback_days: int = 180
    entry_zscore: float = 2.0
    fomc_blackout_days: int = 5
    roll_blackout_days: int = 3
    hl_min: float = 3.0
    hl_max: float = 120.0


@dataclass
class FlyResult:
    structure_id: str
    belly_rank: int
    region: str

    level_bp: float
    zscore: float
    percentile: float
    xsection_rank: float
    direction: str

    half_life_days: float
    vol_ann: float
    roll_bp: float

    entry_eligible: bool
    filters: Dict[str, bool]

    zscore_1d_change: float
    level_1d_change: float


@dataclass
class KinkFadeScreenerSnapshot:
    as_of: datetime.date
    results: List[FlyResult]

    strip_rates: Dict[str, float]
    days_to_fomc: int
    days_to_imm_roll: int
    fomc_blackout_active: bool
    roll_blackout_active: bool

    n_actionable: int
    actionable_ids: List[str]

    cm_resolution: Dict[str, str]
    config: KinkFadeScreenerConfig
    run_warnings: List[str] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for r in self.results:
            rows.append({
                "Structure": r.structure_id,
                "Belly": f"SFR{r.belly_rank}",
                "Region": r.region,
                "Level (bp)": round(r.level_bp, 2),
                "Z-Score": round(r.zscore, 2),
                "Pctile": round(r.percentile, 2),
                "XS Rank": round(r.xsection_rank, 2),
                "Direction": r.direction,
                "HL (d)": round(r.half_life_days, 1) if not np.isnan(r.half_life_days) else None,
                "Vol (ann)": round(r.vol_ann, 2) if not np.isnan(r.vol_ann) else None,
                "Roll (bp)": round(r.roll_bp, 2) if not np.isnan(r.roll_bp) else None,
                "Eligible": r.entry_eligible,
                "Z 1d Chg": round(r.zscore_1d_change, 2),
                "Lvl 1d Chg": round(r.level_1d_change, 2),
            })
        return pd.DataFrame(rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "days_to_fomc": self.days_to_fomc,
            "days_to_imm_roll": self.days_to_imm_roll,
            "fomc_blackout_active": self.fomc_blackout_active,
            "roll_blackout_active": self.roll_blackout_active,
            "n_actionable": self.n_actionable,
            "actionable_ids": self.actionable_ids,
            "strip_rates": self.strip_rates,
            "cm_resolution": self.cm_resolution,
            "results": [
                {
                    "structure_id": r.structure_id,
                    "belly_rank": r.belly_rank,
                    "region": r.region,
                    "level_bp": r.level_bp,
                    "zscore": r.zscore,
                    "direction": r.direction,
                    "half_life_days": r.half_life_days,
                    "entry_eligible": r.entry_eligible,
                    "filters": r.filters,
                }
                for r in self.results
            ],
            "run_warnings": self.run_warnings,
        }


def _belly_rank(structure_id: str) -> int:
    parts = structure_id.split("/")
    if len(parts) == 3:
        try:
            return int(parts[1].replace("SFR", ""))
        except ValueError:
            pass
    return 0


def _region(rank: int) -> str:
    if rank <= 4:
        return "whites"
    if rank <= 8:
        return "reds"
    return "greens"


def build_snapshot(
    config: Optional[KinkFadeScreenerConfig] = None,
    *,
    rates_panel: Optional[pd.DataFrame] = None,
    curve_mdp=None,
    ts_builder=None,
) -> KinkFadeScreenerSnapshot:
    """Build a live screener snapshot for the kink-fading strategy."""
    if config is None:
        config = KinkFadeScreenerConfig()

    warnings_list: List[str] = []
    as_of = datetime.date.today()

    if rates_panel is None:
        import pytz
        NYC = pytz.timezone("America/New_York")
        rv_config = SFRCalSpreadRVConfig(
            source=config.source, curve=config.curve,
            n_contracts=config.n_contracts, zscore_window=config.zscore_window,
            vol_window=config.vol_window, constant_maturity=True,
        )
        lookback = config.lookback_days + config.zscore_window + 30
        start = NYC.localize(datetime.datetime.combine(
            as_of - datetime.timedelta(days=int(lookback * 1.6)),
            datetime.time(18, 0),
        ))
        try:
            rates_panel = load_rate_panel(
                rv_config, start=start, end="live",
                curve_mdp=curve_mdp, ts_builder=ts_builder,
            )
        except Exception:
            end_dt = NYC.localize(datetime.datetime.combine(as_of, datetime.time(18, 0)))
            rates_panel = load_rate_panel(
                rv_config, start=start, end=end_dt,
                curve_mdp=curve_mdp, ts_builder=ts_builder,
            )
            warnings_list.append("live data unavailable, using latest cached date")

    if rates_panel.empty:
        return KinkFadeScreenerSnapshot(
            as_of=as_of, results=[], strip_rates={},
            days_to_fomc=999, days_to_imm_roll=999,
            fomc_blackout_active=False, roll_blackout_active=False,
            n_actionable=0, actionable_ids=[], cm_resolution={},
            config=config, run_warnings=["no rate data available"],
        )

    actual_as_of = rates_panel.index[-1]

    strip_rates = {col: round(float(rates_panel[col].iloc[-1]), 4)
                   for col in rates_panel.columns}

    cm_res = resolve_cm_to_specific(as_of, n_contracts=config.n_contracts)

    bf6m = compute_fly_curve(rates_panel, gap=2)
    zscore_ts = compute_zscore_ts(bf6m, config.zscore_window)
    pctile_ts = compute_percentile_rank(bf6m, config.zscore_window)
    xsection_ts = compute_cross_sectional_rank(bf6m)
    vol_ts = bf6m.diff().rolling(
        config.vol_window, min_periods=max(10, config.vol_window // 2)
    ).std() * np.sqrt(252)
    roll_vals = compute_roll(bf6m, horizon=1)
    hl_ts = compute_rolling_halflife(bf6m, config.halflife_window)

    d_fomc = days_to_next_fomc(actual_as_of)
    d_roll = days_to_next_imm_roll(actual_as_of)
    fomc_active = d_fomc <= config.fomc_blackout_days
    roll_active = d_roll <= config.roll_blackout_days

    results: List[FlyResult] = []
    for col in bf6m.columns:
        level = float(bf6m[col].iloc[-1]) if not np.isnan(bf6m[col].iloc[-1]) else np.nan
        z = float(zscore_ts[col].iloc[-1]) if col in zscore_ts.columns and not np.isnan(zscore_ts[col].iloc[-1]) else np.nan
        pct = float(pctile_ts[col].iloc[-1]) if col in pctile_ts.columns and not np.isnan(pctile_ts[col].iloc[-1]) else np.nan
        xsr = float(xsection_ts[col].iloc[-1]) if col in xsection_ts.columns and not np.isnan(xsection_ts[col].iloc[-1]) else np.nan
        vol = float(vol_ts[col].iloc[-1]) if col in vol_ts.columns and not np.isnan(vol_ts[col].iloc[-1]) else np.nan
        roll = float(roll_vals[col]) if col in roll_vals.index and not np.isnan(roll_vals[col]) else np.nan
        hl = float(hl_ts[col].iloc[-1]) if col in hl_ts.columns and not np.isnan(hl_ts[col].iloc[-1]) else np.nan

        if np.isnan(level) or np.isnan(z):
            continue

        belly = _belly_rank(col)
        reg = _region(belly)
        direction = "buy_kink" if z < 0 else "sell_kink"

        z_prev = float(zscore_ts[col].iloc[-2]) if len(zscore_ts) >= 2 and not np.isnan(zscore_ts[col].iloc[-2]) else z
        lvl_prev = float(bf6m[col].iloc[-2]) if len(bf6m) >= 2 and not np.isnan(bf6m[col].iloc[-2]) else level

        f_z = abs(z) >= config.entry_zscore
        f_dir = direction == "buy_kink"
        f_reg = reg == "reds"
        f_fomc = not fomc_active
        f_roll = not roll_active
        f_hl = (not np.isnan(hl)) and config.hl_min <= hl <= config.hl_max

        filters = {
            "z_threshold": f_z,
            "direction": f_dir,
            "region": f_reg,
            "fomc_blackout": f_fomc,
            "roll_blackout": f_roll,
            "hl_gating": f_hl,
        }
        eligible = all(filters.values())

        results.append(FlyResult(
            structure_id=col,
            belly_rank=belly,
            region=reg,
            level_bp=level,
            zscore=z,
            percentile=pct if not np.isnan(pct) else 0.5,
            xsection_rank=xsr if not np.isnan(xsr) else 0.5,
            direction=direction,
            half_life_days=hl,
            vol_ann=vol,
            roll_bp=roll,
            entry_eligible=eligible,
            filters=filters,
            zscore_1d_change=z - z_prev,
            level_1d_change=level - lvl_prev,
        ))

    results.sort(key=lambda r: abs(r.zscore), reverse=True)
    actionable = [r.structure_id for r in results if r.entry_eligible]

    return KinkFadeScreenerSnapshot(
        as_of=as_of,
        results=results,
        strip_rates=strip_rates,
        days_to_fomc=d_fomc,
        days_to_imm_roll=d_roll,
        fomc_blackout_active=fomc_active,
        roll_blackout_active=roll_active,
        n_actionable=len(actionable),
        actionable_ids=actionable,
        cm_resolution=cm_res,
        config=config,
        run_warnings=warnings_list,
    )
