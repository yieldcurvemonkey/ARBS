"""Backtest engine for the curve-vs-vol pair basis (premium-native by default).

Honesty rules baked in (see docs/superpowers/specs/2026-07-28 spec + backtest
runner): execution is lagged (default 1 day) relative to the signal bar, the
default marks are LISTED wing premiums at strikes fixed at entry (basis
'premium'; 'skew' = BL model marks, kept for comparison only), and quality
gates apply at entry. Costs are charged once per completed trade.

Package for basis='premium' (dir=+1 = long basis): long back-leg risk reversal
(long hike wing P / short cut wing C) vs short front-leg risk reversal, all
four legs at the listed strikes nearest forward +/- wing_offset on the
execution date; theta largely cancels within each RR.
"""
from __future__ import annotations

import dataclasses
import itertools
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.FlyVsVol.pairs import build_pair_history

__all__ = [
    "PairBacktestConfig",
    "PairBacktestResult",
    "prepare_data",
    "run_pair_backtest",
    "grid_search",
]


@dataclasses.dataclass(frozen=True)
class PairBacktestConfig:
    basis: str = "premium"              # 'premium' (listed marks) | 'skew' (model marks)
    ma: int = 5
    zscore_window: int = 120
    zscore_min_periods: int = 40
    entry_min_zscore: float = 2.0
    exit_style: str = "z0"              # 'z0' | 'half' | 't10'
    exit_max_holding_days: int = 20
    stop_loss_bp: Optional[float] = None
    lag: int = 1
    round_trip_cost_bp: float = 2.5
    wing_offset: float = 0.375
    strike_tol: float = 0.13
    quality_gate: bool = True
    pairs: Optional[Tuple[str, ...]] = None   # labels 'FRONT-BACK'; None = all

    def label(self) -> str:
        return (f"{self.basis}|ma{self.ma}|w{self.zscore_window}"
                f"|z{self.entry_min_zscore}|{self.exit_style}|lag{self.lag}")


@dataclasses.dataclass
class PairBacktestResult:
    config: PairBacktestConfig
    trades: pd.DataFrame
    daily_pnl: pd.Series          # net of costs (charged on exit date), bp
    metrics: Dict[str, float]


# ---------------------------------------------------------------------------
def prepare_data(
    wing_panel: pd.DataFrame,
    contracts: pd.DataFrame,
    *,
    wing_offset: float = 0.375,
    strike_tol: float = 0.13,
    max_abs_fwd_resid_bp: float = 2.5,
) -> Dict[str, object]:
    """Precompute both basis series and the premium lookup table.

    Returns {'premium': DataFrame, 'skew': DataFrame, 'lut': Series}. The
    premium basis frame carries the chosen wing strike/premium per leg so an
    entry can fix its strikes without re-searching.
    """
    contracts = contracts.copy()
    contracts["as_of"] = pd.to_datetime(contracts["as_of"])
    wing_panel = wing_panel.copy()
    wing_panel["as_of"] = pd.to_datetime(wing_panel["as_of"])

    fwd = contracts.set_index(["symbol", "as_of"])["forward_rate"]
    ok_leg = (contracts.set_index(["symbol", "as_of"])["fwd_resid_bp"].abs()
              <= max_abs_fwd_resid_bp)

    # per (symbol, as_of): pick hike wing (P at fwd+offset) and cut wing (C at fwd-offset)
    legs = []
    for (sym, ts), grp in wing_panel.groupby(["symbol", "as_of"]):
        f = fwd.get((sym, ts))
        if f is None or np.isnan(f):
            continue
        row = {"symbol": sym, "as_of": ts}
        good = True
        for tag, right, target in (("hk", "P", f + wing_offset),
                                   ("ct", "C", f - wing_offset)):
            g = grp[grp["right"] == right]
            if g.empty:
                good = False
                break
            k = (g["strike_rate"] - target).abs().idxmin()
            if abs(g.loc[k, "strike_rate"] - target) > strike_tol:
                good = False
                break
            row[f"{tag}_K"] = g.loc[k, "strike_price"]
            row[f"{tag}_prem"] = g.loc[k, "premium_bp"]
        if good:
            row["rr_bp"] = row["hk_prem"] - row["ct_prem"]
            legs.append(row)
    leg_df = pd.DataFrame(legs).set_index(["symbol", "as_of"]).sort_index()

    skew = build_pair_history(contracts, max_abs_fwd_resid_bp=max_abs_fwd_resid_bp)

    prem_rows = []
    for label in skew["label"].unique():
        front, back = label.split("-")
        try:
            f_leg = leg_df.xs(front, level="symbol")
            b_leg = leg_df.xs(back, level="symbol")
        except KeyError:
            continue
        j = f_leg.join(b_leg, how="inner", lsuffix="_f", rsuffix="_b")
        if j.empty:
            continue
        out = pd.DataFrame(index=j.index)
        out["label"], out["front"], out["back"] = label, front, back
        out["prem_basis_bp"] = j["rr_bp_b"] - j["rr_bp_f"]
        for col in ("hk_K_f", "hk_prem_f", "ct_K_f", "ct_prem_f",
                    "hk_K_b", "hk_prem_b", "ct_K_b", "ct_prem_b"):
            out[col] = j[col]
        oks = ok_leg.xs(front, level="symbol").reindex(j.index).fillna(False)
        okb = ok_leg.xs(back, level="symbol").reindex(j.index).fillna(False)
        out["quality_ok"] = (oks & okb).to_numpy()
        prem_rows.append(out.reset_index().rename(columns={"index": "as_of"}))
    prem = (pd.concat(prem_rows, ignore_index=True)
            .sort_values(["label", "as_of"]).reset_index(drop=True))

    lut = (wing_panel.set_index(["symbol", "right", "strike_price", "as_of"])
           ["premium_bp"].sort_index())
    return {"premium": prem, "skew": skew, "lut": lut}


def _leg_marks(lut: pd.Series, sym: str, right: str, k: float,
               dates: pd.DatetimeIndex, entry_prem: float) -> np.ndarray:
    try:
        s = lut.loc[(sym, right, k)]
    except KeyError:
        return np.full(len(dates), entry_prem)
    s = s.reindex(dates).ffill()
    return s.fillna(entry_prem).to_numpy()


# ---------------------------------------------------------------------------
def run_pair_backtest(
    config: PairBacktestConfig,
    *,
    data: Dict[str, object],
) -> PairBacktestResult:
    prem, skew, lut = data["premium"], data["skew"], data["lut"]
    base_df = prem if config.basis == "premium" else skew
    sig_col = "prem_basis_bp" if config.basis == "premium" else "pair_rent_skew_bp"

    trades: List[dict] = []
    daily: Dict[pd.Timestamp, float] = {}
    labels = (config.pairs if config.pairs is not None
              else sorted(base_df["label"].unique()))

    for label in labels:
        sub = base_df[base_df["label"] == label].sort_values("as_of").reset_index(drop=True)
        if len(sub) < config.zscore_min_periods + 5:
            continue
        s = sub[sig_col].rolling(config.ma).mean()
        mu = s.rolling(config.zscore_window,
                       min_periods=config.zscore_min_periods).mean()
        sd = s.rolling(config.zscore_window,
                       min_periods=config.zscore_min_periods).std(ddof=0)
        z = ((s - mu) / sd.where(sd > 1e-9)).to_numpy()
        ok = sub["quality_ok"].to_numpy() if config.quality_gate else np.ones(len(sub), bool)
        dates = pd.DatetimeIndex(sub["as_of"])
        front, back = label.split("-")

        pos, sig_i, exec_i, marks = 0, None, None, None
        i = 0
        while i < len(sub):
            if pos == 0:
                if (np.isfinite(z[i]) and abs(z[i]) >= config.entry_min_zscore
                        and ok[i] and i + config.lag < len(sub) - 1):
                    j = i + config.lag
                    d = int(-np.sign(z[i]))
                    if config.basis == "premium":
                        row = sub.iloc[j]
                        span = dates[j:]
                        v = (
                            _leg_marks(lut, back, "P", row["hk_K_b"], span, row["hk_prem_b"])
                            - _leg_marks(lut, back, "C", row["ct_K_b"], span, row["ct_prem_b"])
                            - _leg_marks(lut, front, "P", row["hk_K_f"], span, row["hk_prem_f"])
                            + _leg_marks(lut, front, "C", row["ct_K_f"], span, row["ct_prem_f"])
                        ) * d
                    else:
                        v = (sub[sig_col].to_numpy()[j:]) * d
                    pos, sig_i, exec_i, marks = d, i, j, v
            else:
                days = i - sig_i
                mark_now = marks[min(i + config.lag, len(sub) - 1) - exec_i] - marks[0]
                if config.exit_style == "z0":
                    exit_sig = np.isfinite(z[i]) and (z[i] * (-pos) <= 0)
                elif config.exit_style == "half":
                    exit_sig = np.isfinite(z[i]) and abs(z[i]) <= 0.5
                else:
                    exit_sig = days >= 10
                reason = None
                if exit_sig:
                    reason = ("mean_reversion" if config.exit_style == "z0"
                              else "take_profit" if config.exit_style == "half"
                              else "time")
                elif config.stop_loss_bp is not None and mark_now <= -config.stop_loss_bp:
                    reason = "stop_loss"
                elif days >= config.exit_max_holding_days:
                    reason = "max_hold"
                elif i >= len(sub) - 1 - config.lag:
                    reason = "eod"
                if reason is not None:
                    j1 = min(i + config.lag, len(sub) - 1)
                    gross = marks[j1 - exec_i] - marks[0]
                    net = gross - config.round_trip_cost_bp
                    for k in range(exec_i + 1, j1 + 1):
                        daily[dates[k]] = daily.get(dates[k], 0.0) + (
                            marks[k - exec_i] - marks[k - 1 - exec_i])
                    daily[dates[j1]] = daily.get(dates[j1], 0.0) - config.round_trip_cost_bp
                    trades.append({
                        "label": label, "dir": pos,
                        "signal_date": dates[sig_i], "entry": dates[exec_i],
                        "exit": dates[j1], "days": j1 - exec_i,
                        "z_in": round(float(z[sig_i]), 2),
                        "gross_bp": round(float(gross), 3),
                        "net_bp": round(float(net), 3),
                        "exit_reason": reason,
                    })
                    pos, sig_i, exec_i, marks = 0, None, None, None
            i += 1

    trades_df = pd.DataFrame(trades)
    if daily:
        daily_s = pd.Series(daily).sort_index()
    else:
        daily_s = pd.Series(dtype=float)
    metrics = _metrics(trades_df, daily_s)
    return PairBacktestResult(config=config, trades=trades_df,
                              daily_pnl=daily_s, metrics=metrics)


def _metrics(trades: pd.DataFrame, daily: pd.Series) -> Dict[str, float]:
    if trades.empty:
        return {"n_trades": 0, "total_net_bp": 0.0, "hit_rate": np.nan,
                "avg_net_bp": np.nan, "sharpe": np.nan, "max_dd_bp": 0.0,
                "avg_hold_days": np.nan, "worst_bp": np.nan}
    cum = daily.cumsum()
    sd = daily.std(ddof=1)
    return {
        "n_trades": int(len(trades)),
        "total_net_bp": float(trades["net_bp"].sum()),
        "hit_rate": float((trades["net_bp"] > 0).mean()),
        "avg_net_bp": float(trades["net_bp"].mean()),
        "sharpe": float(daily.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan,
        "max_dd_bp": float((cum - cum.cummax()).min()),
        "avg_hold_days": float(trades["days"].mean()),
        "worst_bp": float(trades["net_bp"].min()),
    }


def grid_search(
    param_grid: Dict[str, Sequence],
    *,
    data: Dict[str, object],
    base: Optional[PairBacktestConfig] = None,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Cartesian sweep over config fields; returns one summary row per config."""
    base = base or PairBacktestConfig()
    keys = list(param_grid)
    rows = []
    combos = list(itertools.product(*(param_grid[k] for k in keys)))
    for n, combo in enumerate(combos):
        cfg = dataclasses.replace(base, **dict(zip(keys, combo)))
        res = run_pair_backtest(cfg, data=data)
        rows.append({**{k: v for k, v in zip(keys, combo)},
                     "config": cfg.label(), **res.metrics})
        if show_progress and (n + 1) % 20 == 0:
            print(f"  {n + 1}/{len(combos)} configs", flush=True)
    return pd.DataFrame(rows)
