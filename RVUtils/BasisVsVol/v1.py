"""V1: the option-adjusted basis. Model the delivery option, trade the residual.

    OABNOC = BNOC_market - (switch option + wildcard option)

Buy the basis when the market pays you less than the option is worth (OABNOC low), sell when it
pays more. This is the leg the design doc calls V1, and it is the trade the dealer literature
actually recommends -- BofA's "buy futures basis = cheap options" is exactly a long-OABNOC
position.

**P&L is exactly the change in net basis.** Long basis = long the CTD, short CF futures, financed.
Daily P&L per 100 face = d(P_cash) - CF*d(F) + coupon accrual - repo cost = d(gross basis) + one
day's carry = **d(net basis)**. So marking the position daily needs only the net basis series, and
the carry is already inside it. Reported in 32nds per 100 face; one 32nd on $1mm face is $312.50.

**A roll is never a return.** The panel rolls the front contract before first notice; on that day
the net basis jumps to a different contract's, which is not P&L.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .switch import Deliverable, delivery_option_two_bond
from .wildcard import wildcard_value

__all__ = ["V1Config", "add_model_option", "run_v1", "TICK_USD_PER_MM"]

TICK_USD_PER_MM = 312.50  # one 32nd on $1mm face


@dataclass
class V1Config:
    root: str = "ZB"
    # --- delivery-option model ------------------------------------------------
    sigma_yield_bp: float = 1.0        # post-close vol for the wildcard, bp/2hr
    wildcard_days: int = 14            # delivery days on which the wildcard is live
    switch_vol_bp: float = 70.0        # annualised bp vol of the forward yield for the switch
    use_wildcard: bool = True
    use_switch: bool = True
    # --- signal ---------------------------------------------------------------
    z_window: int = 126
    z_min_periods: int = 60
    entry_z: float = 1.5
    exit_z: float = 0.5
    exec_lag_days: int = 1
    max_hold_days: int = 21
    max_gap_days: int = 5
    # --- sizing / costs -------------------------------------------------------
    face_mm: float = 100.0             # $mm of CTD face per unit position
    cost_32nds: float = 0.5            # round-trip, in 32nds of the cash+futures package
    cost_mult: float = 1.0

    def key(self) -> str:
        return (f"{self.root}/w{self.z_window}/e{self.entry_z:g}/x{self.exit_z:g}"
                f"/h{self.max_hold_days}/sv{self.switch_vol_bp:g}/wc{int(self.use_wildcard)}"
                f"/cm{self.cost_mult:g}")


@dataclass
class V1Result:
    config: dict
    daily: pd.DataFrame
    trades: pd.DataFrame
    panel: pd.DataFrame
    diagnostics: dict = field(default_factory=dict)


def add_model_option(panel: pd.DataFrame, cfg: V1Config) -> pd.DataFrame:
    """Attach the modelled delivery option value and the option-adjusted net basis."""
    p = panel.copy().sort_values("date").reset_index(drop=True)
    sw, wc = [], []
    for r in p.itertuples(index=False):
        tte = np.nan
        if getattr(r, "delivery_date", None) is not None and pd.notna(r.delivery_date):
            tte = max((pd.Timestamp(r.delivery_date) - pd.Timestamp(r.date)).days, 1) / 365.0
        s_val = np.nan
        if cfg.use_switch and np.isfinite(tte):
            try:
                ctd = Deliverable("ctd", r.ctd_cf, r.ctd_price, r.ctd_dv01)
                alt = Deliverable("alt", r.alt_cf, r.alt_price, r.alt_dv01)
                s_val = delivery_option_two_bond(ctd, alt, cfg.switch_vol_bp, tte)["value"]
            except Exception:
                s_val = np.nan
        w_val = np.nan
        if cfg.use_wildcard and np.isfinite(r.ctd_cf) and np.isfinite(r.ctd_dv01):
            # one day's carry, in price points: (gross - net) spread over the days to delivery
            days = max((pd.Timestamp(r.delivery_date) - pd.Timestamp(r.date)).days, 1) \
                if pd.notna(getattr(r, "delivery_date", None)) else 60
            carry_pts = (r.ctd_gross32 - r.ctd_bnoc32) / 32.0 / days
            try:
                w_val = wildcard_value(r.ctd_cf, r.ctd_dv01, carry_pts,
                                       cfg.wildcard_days, sigma_yield_bp=cfg.sigma_yield_bp).value_ticks
            except Exception:
                w_val = np.nan
        sw.append(s_val)
        wc.append(w_val)

    p["switch32"] = sw
    p["wildcard32"] = wc
    p["dov32"] = np.nansum(np.vstack([p["switch32"].to_numpy(float),
                                      p["wildcard32"].to_numpy(float)]), axis=0)
    # A component switched OFF by config contributes zero; a component that FAILED to compute is
    # missing. Conflating the two makes the no-model ablation arm -- the one that asks whether the
    # delivery-option machinery earns its place -- silently produce an empty result.
    if cfg.use_switch or cfg.use_wildcard:
        p.loc[p[["switch32", "wildcard32"]].isna().all(axis=1), "dov32"] = np.nan
    p["oabnoc32"] = p["ctd_bnoc32"] - p["dov32"]

    mu = p["oabnoc32"].rolling(cfg.z_window, min_periods=cfg.z_min_periods).mean()
    sd = p["oabnoc32"].rolling(cfg.z_window, min_periods=cfg.z_min_periods).std()
    p["z"] = (p["oabnoc32"] - mu) / sd.replace(0.0, np.nan)
    return p


def run_v1(panel: pd.DataFrame, cfg: V1Config) -> V1Result:
    """Event-driven backtest with daily mark-to-market on the net basis."""
    p = add_model_option(panel, cfg)
    if p.empty or p["z"].notna().sum() == 0:
        return V1Result(asdict(cfg), pd.DataFrame(), pd.DataFrame(), p, {"reason": "no signal"})

    dates = list(p["date"])
    nb = p["ctd_bnoc32"].to_numpy(float)
    zs = p["z"].to_numpy(float)
    roll = p["is_roll"].to_numpy(bool) if "is_roll" in p else np.zeros(len(p), bool)
    sym = p["symbol"].to_numpy()

    pos, daily, trades, n_gap = None, [], [], 0
    entry_cost = lambda: cfg.cost_mult * cfg.cost_32nds * cfg.face_mm * TICK_USD_PER_MM / 2.0

    for i, d in enumerate(dates):
        gap = (d - dates[i - 1]).days if i else 0
        stale = gap > cfg.max_gap_days
        row = {"date": d, "z": zs[i], "oabnoc32": p["oabnoc32"].iloc[i], "nb32": nb[i],
               "pnl": 0.0, "gross_pnl": 0.0, "cost": 0.0, "in_pos": 0, "side": 0}

        if pos is not None:
            if stale or roll[i] or sym[i] != pos["symbol"]:
                # neither a data hole nor a contract change is a return: close at the last mark
                c = entry_cost()
                row["pnl"] -= c
                row["cost"] += c
                pos["cum"] -= c
                trades.append({**{k: pos[k] for k in ("entry_date", "side", "entry_z", "symbol")},
                               "exit_date": d, "held_days": (dates[i - 1] - pos["entry_date"]).days,
                               "reason": "gap" if stale else "roll", "pnl": pos["cum"]})
                pos = None
                n_gap += 1 if stale else 0
            else:
                gross = pos["side"] * (nb[i] - nb[i - 1]) * cfg.face_mm * TICK_USD_PER_MM
                row.update(pnl=gross, gross_pnl=gross, in_pos=1, side=pos["side"])
                pos["cum"] += gross
                held = (d - pos["entry_date"]).days
                reason = None
                if held >= cfg.max_hold_days:
                    reason = "max_hold"
                elif np.isfinite(zs[i]) and abs(zs[i]) <= cfg.exit_z:
                    reason = "z_exit"
                if reason:
                    c = entry_cost()
                    row["pnl"] -= c
                    row["cost"] += c
                    pos["cum"] -= c
                    trades.append({**{k: pos[k] for k in ("entry_date", "side", "entry_z", "symbol")},
                                   "exit_date": d, "held_days": held, "reason": reason,
                                   "pnl": pos["cum"]})
                    pos = None

        if pos is None and not stale and not roll[i]:
            j = i - cfg.exec_lag_days
            if 0 <= j < len(p) and np.isfinite(zs[j]) and abs(zs[j]) >= cfg.entry_z:
                c = entry_cost()
                pos = {"entry_date": d, "side": int(-np.sign(zs[j])), "entry_z": zs[j],
                       "symbol": sym[i], "cum": -c}
                row["pnl"] -= c
                row["cost"] += c
                row["in_pos"] = 1
                row["side"] = pos["side"]
        daily.append(row)

    dly = pd.DataFrame(daily).set_index("date")
    dly["equity"] = dly["pnl"].cumsum()
    dly["pnl_32nds"] = dly["pnl"] / (cfg.face_mm * TICK_USD_PER_MM)
    dly["pnl_volbp"] = dly["pnl_32nds"]  # alias so the shared analytics work unchanged
    trd = pd.DataFrame(trades)
    if len(trd):
        trd["pnl_volbp"] = trd["pnl"] / (cfg.face_mm * TICK_USD_PER_MM)
    diag = {"n_days": len(dly), "n_trades": len(trd), "days_in_pos": int(dly["in_pos"].sum()),
            "gap_exits": n_gap, "median_dov32": float(np.nanmedian(p["dov32"])),
            "median_bnoc32": float(np.nanmedian(p["ctd_bnoc32"]))}
    return V1Result(asdict(cfg), dly, trd, p, diag)
