"""The V2 leg: exchange vol vs OTC vol, as a delta-hedged, vega-matched paired position.

This is the cheap half of the ``V_spread = V1 + V2`` decomposition. It needs no basis model, no
deliverable basket and no repo mark, so it can falsify the cross-product thesis before any of that
is built.

    V2 = sigma_swaption - sigma_ustf_option

Both legs are normal (Bachelier) options on a rate, so the whole position lives in one unit
system: vols in annualised bp, forwards in bp, premia in bp of rate, and money = bp x DV01.

Four modelling commitments, each made because the alternative is wrong rather than merely
different:

* **A position is priced at its own remaining time to expiry**, not at the constant-maturity slot
  it was opened from. Differencing a CM series books the roll-down of the vol term structure as
  P&L.
* **Delta-hedged P&L is right-invariant.** Put-call parity gives ``C - P = F - K`` and
  ``delta_C - delta_P = 1``, so ``dV - delta*dF`` is identical for a call and a put at the same
  strike. Every position is therefore priced as a call on the rate; the choice carries no
  information and pretending otherwise would just be decoration.
* **The signal is computed on data up to and including t, and executed at t + exec_lag_days.**
  There is no path by which a fill uses a price the signal has not already seen.
* **A contract roll is not a return.** The stored ``forward_yield`` belongs to a constant-maturity
  slot whose underlying contract changes; differencing across that change books a non-market gap.
  The default policy closes the position at the roll.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

import numpy as np
import pandas as pd

from .bachelier import normal_delta, normal_price, normal_vega
from .surfaces import DailySurface, SurfaceBook, build_swaption_surfaces, build_ustf_surfaces
from .voldata import PRODUCT_TAIL, VolData

__all__ = ["StrategyConfig", "build_signal_panel", "run_strategy", "BacktestResult"]

# UL is excluded by default: its stored forward_yield moves 20bp across the whole 3.3-year sample
# (US moves 163bp) and a block of its rows carries a forward price with a dropped leading digit.
# Its implied/realized ratio is 3.5 against 0.97-1.13 for every other product.
DEFAULT_UNIVERSE = ("TU", "FV", "TY", "TN", "US")


@dataclass
class StrategyConfig:
    # --- instrument selection -------------------------------------------------
    product: str = "US"
    tail: str | None = None  # None -> PRODUCT_TAIL[product]
    expiry_label: str = "3M"
    swpt_expiry_label: str | None = None  # None -> same label
    offset_bps: float = 0.0  # signed strike offset at inception; + = higher rate

    # --- signal ---------------------------------------------------------------
    z_window: int = 126
    z_min_periods: int = 60
    entry_z: float = 1.5
    exit_z: float = 0.5
    signal_on: Literal["level", "change"] = "level"

    # --- position management --------------------------------------------------
    max_hold_days: int = 21
    min_tte_days: float = 10.0
    exec_lag_days: int = 1
    rehedge_days: int = 1  # 0 disables delta hedging
    roll_policy: Literal["exit", "reanchor"] = "exit"
    stop_loss_vega_mult: float | None = None  # stop at this many x target_vega of loss
    # The futures-option leg has 13 holes longer than a week, one of them 80 days, clustered
    # around the quarterly option expiry. A position marked across such a hole books the entire
    # unobserved move as a single unhedged day -- in the first run that produced one 80-day trade
    # worth 57% of all P&L. Positions are liquidated at the last observed mark instead, and no
    # return is claimed for the gap.
    max_gap_days: int = 5
    # HARD SUPPORT GATE. The vol term structure is quoted at three nodes (30/60/90 days); below the
    # shortest node the surface holds vol flat because there is nothing to interpolate. A position
    # priced there is priced outside the data. This is not academic: opening at the 1M slot puts
    # every position-day in the extrapolated region and produces Sharpe 1.94 (t=3.4, hit 76%),
    # which inverts to Sharpe -0.58 the moment positions are confined to the quoted range. Off
    # support is not a result, it is an absence of measurement.
    require_on_support: bool = True
    support_tol_days: float = 0.0

    # --- sizing ---------------------------------------------------------------
    target_vega_usd: float = 100_000.0

    # --- costs (per side, in bp of vol) ---------------------------------------
    ustf_cost_vol_bp: float = 0.5
    swpt_cost_vol_bp: float = 0.75
    hedge_cost_bp: float = 0.10  # per rehedge, per leg, in bp of the underlying rate
    cost_mult: float = 1.0

    def resolved_tail(self) -> str:
        return self.tail or PRODUCT_TAIL[self.product]

    def resolved_swpt_expiry(self) -> str:
        return self.swpt_expiry_label or self.expiry_label

    def key(self) -> str:
        return (
            f"{self.product}/{self.expiry_label}/{self.resolved_tail()}/off{self.offset_bps:+g}"
            f"/w{self.z_window}/e{self.entry_z:g}/x{self.exit_z:g}/h{self.max_hold_days}"
            f"/rh{self.rehedge_days}/cm{self.cost_mult:g}"
        )


@dataclass
class BacktestResult:
    config: dict
    daily: pd.DataFrame
    trades: pd.DataFrame
    signal: pd.DataFrame
    diagnostics: dict = field(default_factory=dict)


def build_signal_panel(vd: VolData, cfg: StrategyConfig, book: SurfaceBook | None = None) -> pd.DataFrame:
    """Daily observable signal at the constant-maturity slot.

    The signal may legitimately be computed on CM data -- it is a relative-value observation, not a
    P&L. Only the *position* has to be priced at its own remaining maturity.
    """
    tail = cfg.resolved_tail()
    book = book or SurfaceBook(vd)
    u_surf = book.ustf(cfg.product)
    s_surf = book.swpt(tail)

    u_rows = vd.ustf[
        (vd.ustf["product"] == cfg.product) & (vd.ustf["expiry_label"] == cfg.expiry_label)
    ].set_index("as_of_date").sort_index()
    s_rows = vd.swpt[
        (vd.swpt["tail_label"] == tail) & (vd.swpt["expiry_label"] == cfg.resolved_swpt_expiry())
    ].set_index("as_of_date").sort_index()

    dates = sorted(set(u_rows.index) & set(s_rows.index) & set(u_surf) & set(s_surf))
    recs = []
    for d in dates:
        ur, sr = u_rows.loc[d], s_rows.loc[d]
        if isinstance(ur, pd.DataFrame):
            ur = ur.iloc[0]
        if isinstance(sr, pd.DataFrame):
            sr = sr.iloc[0]
        tte = float(ur["time_to_expiry"])
        us, ss = u_surf[d], s_surf[d]
        uv = us.vol(tte, cfg.offset_bps)
        sv = ss.vol(tte, cfg.offset_bps)
        recs.append(
            {
                "as_of_date": d,
                "tte": tte,
                "ustf_vol": uv,
                "swpt_vol": sv,
                "spread": sv - uv,
                "ustf_fwd_bp": us.forward_bp,
                "swpt_fwd_bp": ss.forward_bp,
                "fv01": us.meta["fv01"],
                "underlying_contract": us.meta["underlying_contract"],
                "is_roll": bool(ur.get("is_roll", False)),
            }
        )
    p = pd.DataFrame(recs).set_index("as_of_date").sort_index()
    if p.empty:
        return p

    base = p["spread"] if cfg.signal_on == "level" else p["spread"].diff()
    mu = base.rolling(cfg.z_window, min_periods=cfg.z_min_periods).mean()
    sd = base.rolling(cfg.z_window, min_periods=cfg.z_min_periods).std()
    p["z"] = (base - mu) / sd.replace(0.0, np.nan)
    return p


def _leg_state(surf: DailySurface, K_bp: float, tte: float):
    """(vol, price_bp, delta) for a call on the rate at fixed strike ``K_bp``."""
    F = surf.forward_bp
    sig = surf.vol(tte, K_bp - F)
    if not np.isfinite(sig) or sig <= 0 or tte <= 0:
        return np.nan, np.nan, np.nan
    return (
        sig,
        float(normal_price(F, K_bp, sig, tte, w=1)),
        float(normal_delta(F, K_bp, sig, tte, w=1)),
    )


def run_strategy(vd: VolData, cfg: StrategyConfig, book: SurfaceBook | None = None) -> BacktestResult:
    """Event-driven backtest of the paired vol position."""
    tail = cfg.resolved_tail()
    book = book or SurfaceBook(vd)
    panel = build_signal_panel(vd, cfg, book)
    if panel.empty or panel["z"].notna().sum() == 0:
        return BacktestResult(asdict(cfg), pd.DataFrame(), pd.DataFrame(), panel,
                              {"reason": "no signal"})

    u_surf = book.ustf(cfg.product)
    s_surf = book.swpt(tail)
    dates = list(panel.index)
    pos = None
    daily, trades = [], []
    n_blocked_roll = 0
    n_gap_exits = 0

    for i, d in enumerate(dates):
        row = panel.loc[d]
        us, ss = u_surf.get(d), s_surf.get(d)
        day = {"as_of_date": d, "z": row["z"], "spread": row["spread"], "pnl": 0.0,
               "gross_pnl": 0.0, "cost": 0.0, "in_pos": 0, "side": 0}

        gap_days = (d - dates[i - 1]).days if i > 0 else 0
        stale = gap_days > cfg.max_gap_days

        # ---------------- liquidate across an unobservable stretch ------------
        if pos is not None and stale:
            # Close at the LAST OBSERVED mark. No P&L is booked for the gap: the position could
            # not have been hedged through it, so claiming the move would be inventing a return.
            exit_cost = cfg.cost_mult * cfg.target_vega_usd * (
                cfg.ustf_cost_vol_bp + cfg.swpt_cost_vol_bp
            )
            pos["cum_pnl"] -= exit_cost
            day["pnl"] -= exit_cost
            day["cost"] += exit_cost
            trades.append(
                {**{k: pos[k] for k in ("entry_date", "side", "entry_z", "entry_spread",
                                        "K_u", "K_s", "tte0", "dv01_u", "dv01_s")},
                 "exit_date": d, "exit_z": row["z"], "exit_spread": row["spread"],
                 "held_days": (dates[i - 1] - pos["entry_date"]).days,
                 "reason": "gap", "pnl": pos["cum_pnl"]}
            )
            pos = None
            n_gap_exits += 1

        # ---------------- mark the open position -----------------------------
        if pos is not None and us is not None and ss is not None:
            tte = pos["tte0"] - (d - pos["entry_date"]).days / 365.0
            rolled = bool(row["is_roll"]) or (row["underlying_contract"] != pos["contract"])

            if rolled and cfg.roll_policy == "reanchor":
                # keep the economic position: re-strike to the same moneyness on the new contract
                pos["K_u"] = us.forward_bp + pos["moneyness_u"]
                pos["prev_F_u"] = us.forward_bp
                pos["contract"] = row["underlying_contract"]
                _, pu, du = _leg_state(us, pos["K_u"], tte)
                pos["prev_pu"], pos["prev_du"] = pu, du

            su_v, pu, du = _leg_state(us, pos["K_u"], tte)
            ss_v, ps, ds = _leg_state(ss, pos["K_s"], tte)

            if np.isfinite(pu) and np.isfinite(ps) and tte > 0:
                hedged = cfg.rehedge_days > 0
                dpu = (pu - pos["prev_pu"]) - (pos["prev_du"] * (us.forward_bp - pos["prev_F_u"]) if hedged else 0.0)
                dps = (ps - pos["prev_ps"]) - (pos["prev_ds"] * (ss.forward_bp - pos["prev_F_s"]) if hedged else 0.0)
                if rolled:
                    # A contract change gaps the forward by a non-market amount. Whatever the roll
                    # policy, that jump is not a return: re-anchor the marks and claim nothing.
                    # (Found by cross-checking against the QueryDrivenBacktest handler, which
                    # refused the jump while this engine was booking it.)
                    dpu = dps = 0.0
                gross = pos["side"] * (pos["dv01_s"] * dps - pos["dv01_u"] * dpu)

                cost = 0.0
                if hedged and (i - pos["last_hedge_i"]) >= cfg.rehedge_days:
                    cost += cfg.cost_mult * cfg.hedge_cost_bp * (
                        abs(pos["dv01_u"] * pos["prev_du"]) + abs(pos["dv01_s"] * pos["prev_ds"])
                    ) / 100.0
                    pos["last_hedge_i"] = i

                day.update(pnl=gross - cost, gross_pnl=gross, cost=cost, in_pos=1, side=pos["side"])
                pos["cum_pnl"] += gross - cost
                pos.update(prev_pu=pu, prev_ps=ps, prev_du=du, prev_ds=ds,
                           prev_F_u=us.forward_bp, prev_F_s=ss.forward_bp)

            # ---------------- exit tests -------------------------------------
            held = (d - pos["entry_date"]).days
            support_floor = max(us.min_node_tte, ss.min_node_tte) - cfg.support_tol_days / 365.0
            reason = None
            if cfg.require_on_support and np.isfinite(support_floor) and tte < support_floor:
                reason = "off_support"
            elif rolled and cfg.roll_policy == "exit":
                reason = "roll"
            elif tte * 365.0 <= cfg.min_tte_days:
                reason = "tte_floor"
            elif held >= cfg.max_hold_days:
                reason = "max_hold"
            elif np.isfinite(row["z"]) and abs(row["z"]) <= cfg.exit_z:
                reason = "z_exit"
            elif (cfg.stop_loss_vega_mult is not None
                  and pos["cum_pnl"] < -cfg.stop_loss_vega_mult * cfg.target_vega_usd):
                reason = "stop"
            elif not np.isfinite(pu) or not np.isfinite(ps):
                reason = "no_mark"

            if reason is not None:
                # Charge the exit on the vega actually held, not the vega opened with. Vega decays
                # as sqrt(T); billing the entry notional at exit overstates costs on long holds.
                vu_now = float(normal_vega(us.forward_bp, pos["K_u"], su_v, max(tte, 1e-6)))
                vs_now = float(normal_vega(ss.forward_bp, pos["K_s"], ss_v, max(tte, 1e-6)))
                exit_cost = cfg.cost_mult * (
                    pos["dv01_u"] * (vu_now if np.isfinite(vu_now) else 0.0) * cfg.ustf_cost_vol_bp
                    + pos["dv01_s"] * (vs_now if np.isfinite(vs_now) else 0.0) * cfg.swpt_cost_vol_bp
                )
                day["pnl"] -= exit_cost
                day["cost"] += exit_cost
                pos["cum_pnl"] -= exit_cost
                trades.append(
                    {**{k: pos[k] for k in ("entry_date", "side", "entry_z", "entry_spread",
                                            "K_u", "K_s", "tte0", "dv01_u", "dv01_s")},
                     "exit_date": d, "exit_z": row["z"], "exit_spread": row["spread"],
                     "held_days": held, "reason": reason, "pnl": pos["cum_pnl"]}
                )
                pos = None

        # ---------------- entry ---------------------------------------------
        if pos is None and us is not None and ss is not None:
            j = i - cfg.exec_lag_days
            # A negative lag is the deliberate-lookahead mutation used to prove the harness
            # can see future knowledge at all; it must be bounded, not allowed to run off
            # the end of the panel.
            if 0 <= j < len(panel):
                zs = panel["z"].iloc[j]
                if np.isfinite(zs) and abs(zs) >= cfg.entry_z and not stale:
                    if bool(row["is_roll"]):
                        n_blocked_roll += 1
                    else:
                        tte0 = float(row["tte"])
                        floor0 = max(us.min_node_tte, ss.min_node_tte) - cfg.support_tol_days / 365.0
                        if cfg.require_on_support and np.isfinite(floor0) and tte0 < floor0:
                            daily.append(day)
                            continue
                        K_u = us.forward_bp + cfg.offset_bps
                        K_s = ss.forward_bp + cfg.offset_bps
                        vu, pu, du = _leg_state(us, K_u, tte0)
                        vs, ps, ds = _leg_state(ss, K_s, tte0)
                        veg_u = float(normal_vega(us.forward_bp, K_u, vu, tte0))
                        veg_s = float(normal_vega(ss.forward_bp, K_s, vs, tte0))
                        if all(np.isfinite(x) and x > 0 for x in (pu, ps, veg_u, veg_s)):
                            entry_cost = cfg.cost_mult * cfg.target_vega_usd * (
                                cfg.ustf_cost_vol_bp + cfg.swpt_cost_vol_bp
                            )
                            pos = {
                                "entry_date": d,
                                "side": int(-np.sign(zs)),  # z<0 -> long swaption vol
                                "entry_z": zs,
                                "entry_spread": row["spread"],
                                "K_u": K_u, "K_s": K_s,
                                "moneyness_u": cfg.offset_bps,
                                "tte0": tte0,
                                "dv01_u": cfg.target_vega_usd / veg_u,
                                "dv01_s": cfg.target_vega_usd / veg_s,
                                "prev_pu": pu, "prev_ps": ps, "prev_du": du, "prev_ds": ds,
                                "prev_F_u": us.forward_bp, "prev_F_s": ss.forward_bp,
                                "contract": row["underlying_contract"],
                                "last_hedge_i": i,
                                "cum_pnl": -entry_cost,
                            }
                            day["pnl"] -= entry_cost
                            day["cost"] += entry_cost
                            day["in_pos"] = 1
                            day["side"] = pos["side"]
        daily.append(day)

    dly = pd.DataFrame(daily).set_index("as_of_date")
    dly["equity"] = dly["pnl"].cumsum()
    # scale-free view: P&L expressed in bp of vol on the target vega notional
    dly["pnl_volbp"] = dly["pnl"] / cfg.target_vega_usd
    dly["equity_volbp"] = dly["pnl_volbp"].cumsum()
    trd = pd.DataFrame(trades)
    if len(trd):
        trd["pnl_volbp"] = trd["pnl"] / cfg.target_vega_usd
    diag = {
        "n_days": len(dly),
        "n_trades": len(trd),
        "days_in_pos": int(dly["in_pos"].sum()),
        "entries_blocked_by_roll": n_blocked_roll,
        "gap_exits": n_gap_exits,
        "universe_note": "UL excluded: corrupt forward_yield",
    }
    return BacktestResult(asdict(cfg), dly, trd, panel, diag)
