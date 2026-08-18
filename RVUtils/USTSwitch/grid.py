"""Grid search over switch configurations.

Scope of the search is stated explicitly because the deflation depends on it: every
configuration evaluated counts as a trial, including the ones that were only run as
controls. Quietly excluding the losers from the trial count is the cheapest way to
manufacture a surviving row, and ``RVUtils/SFRRVLab/stats.deflated_for_grid`` raises
rather than let it happen.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.USTSwitch.analytics import summarize_switch
from RVUtils.USTSwitch.costs import CostModel
from RVUtils.USTSwitch.data import select_financing
from RVUtils.USTSwitch.engine import SwitchConfig, run_switch

TENORS = (2, 3, 5, 7, 10, 20, 30)
#: (rank_young, rank_old). All six pairs among CT/O/OO/OOO -- "double olds vs current",
#: "triple olds vs olds" and the rest of the combinations the study asked for.
PAIRS: Tuple[Tuple[int, int], ...] = tuple(itertools.combinations(range(4), 2))


def default_axes() -> Dict[str, Sequence]:
    return {
        "direction": (1, -1),
        "entry_offset": (0, 1, 3, 5, 10),
        "exit_rule": ("next_roll", "fixed"),
        "exit_offset": (1,),
        "hold_days": (10, 21, 42),
        "z_window": (None, 250),
        "z_entry": (None, 1.0),
    }


def expand(
    tenors: Sequence[int] = TENORS,
    pairs: Sequence[Tuple[int, int]] = PAIRS,
    axes: Optional[Dict[str, Sequence]] = None,
    *,
    financing_mode: str = "modelled",
    cost_multiplier: float = 1.0,
) -> List[SwitchConfig]:
    ax = axes or default_axes()
    cfgs: List[SwitchConfig] = []
    for tenor, (ry, ro) in itertools.product(tenors, pairs):
        for direction, e_off, exit_rule, x_off, hold, zw, ze in itertools.product(
            ax["direction"], ax["entry_offset"], ax["exit_rule"], ax["exit_offset"],
            ax["hold_days"], ax["z_window"], ax["z_entry"],
        ):
            # collapse redundant cells: hold_days is meaningless for next_roll and
            # exit_offset is meaningless for fixed; z_window and z_entry must agree.
            if exit_rule == "next_roll" and hold != ax["hold_days"][0]:
                continue
            if exit_rule == "fixed" and x_off != ax["exit_offset"][0]:
                continue
            if (zw is None) != (ze is None):
                continue
            cfgs.append(
                SwitchConfig(
                    tenor=tenor, rank_young=ry, rank_old=ro, direction=direction,
                    entry_offset=e_off, exit_rule=exit_rule, exit_offset=x_off,
                    hold_days=hold, z_window=zw, z_entry=ze,
                    financing_mode=financing_mode, cost_multiplier=cost_multiplier,
                )
            )
    return cfgs


def run_grid(
    panel: pd.DataFrame,
    amap: pd.DataFrame,
    configs: Sequence[SwitchConfig],
    *,
    progress: bool = True,
    keep_daily: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, pd.Series], Dict[str, object]]:
    """Returns (league frame, {name: daily pnl series}, {name: SwitchResult})."""
    # Financing selection is per-mode, so prepare each mode once instead of per config.
    modes = sorted({c.financing_mode for c in configs})
    panels = {m: select_financing(panel, m) for m in modes}

    rows: List[Dict] = []
    daily: Dict[str, pd.Series] = {}
    results: Dict[str, object] = {}

    it = configs
    if progress:
        try:
            from tqdm import tqdm

            it = tqdm(configs, desc="GRID")
        except ImportError:
            pass

    for cfg in it:
        try:
            res = run_switch(
                panels[cfg.financing_mode], amap, cfg,
                cost_model=CostModel(multiplier=cfg.cost_multiplier),
            )
            row = summarize_switch(res)
            row["error"] = ""
            rows.append(row)
            if keep_daily and not res.daily.empty:
                d = res.daily
                daily[cfg.name] = d.loc[d["in_position"] > 0, "pnl_bp"]
                results[cfg.name] = res
        except Exception as exc:  # a broken cell is a fact, and must not look like a zero
            rows.append({"name": cfg.name, "tenor": cfg.tenor, "pair": cfg.pair_label,
                         "n_trades": 0, "error": f"{type(exc).__name__}: {exc}"})
    return pd.DataFrame(rows), daily, results


def placebo_grid(configs: Sequence[SwitchConfig], shifts: Sequence[int] = (7, 14, -7)) -> List[SwitchConfig]:
    """The same configs, entered off the auction clock.

    If the edge is the auction mechanism, shifting entry away from the roll must degrade
    it. If the shifted book performs as well, whatever is being measured is not the
    on-the-run premium and the auction story is decoration.
    """
    return [replace(c, placebo_shift=s) for c in configs for s in shifts]


def cost_curve(
    panel: pd.DataFrame, amap: pd.DataFrame, cfg: SwitchConfig,
    multipliers: Sequence[float] = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0),
) -> pd.DataFrame:
    """Net P&L as a function of the assumed execution cost.

    Reported because every prior lab in this repo died on the cost line, and the useful
    number is not "does it work at my cost assumption" but "at what fraction of my cost
    assumption does it stop working".
    """
    p = select_financing(panel, cfg.financing_mode)
    rows = []
    for m in multipliers:
        c = replace(cfg, cost_multiplier=m)
        res = run_switch(p, amap, c, cost_model=CostModel(multiplier=m))
        s = summarize_switch(res)
        rows.append({"cost_multiplier": m, **{k: s.get(k) for k in
                     ("n_trades", "net_bp", "net_bp_per_trade", "sharpe", "t_stat_nw", "hit_rate")}})
    return pd.DataFrame(rows)
