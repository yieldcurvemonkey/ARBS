"""V3: the basis as an option, priced against a matched swaption.

Citi Research, *US Rates Weekly -- Summer lull*, 17 July 2015:

    "Since the futures contract is unlikely to trade higher than the forward settlement price of
     the CTD, owning a futures bond net basis is like owning an option and hence, the net basis has
     a floor of 0. ... Since a long basis trade is like owning an option, it is fair to measure its
     relative value by comparing it to a swaption. The gamma of a $100mm May37 basis (Long $100mm
     5% May37s vs short 911 USZ5 contracts) is $420 and costs 4.2 ticks or $130K. For owning the
     same amount of gamma through a 1m25y swaption, it costs $187K, ie. approximately 1.4 times the
     cost of the May37 basis."

THE SIGNAL
----------
For an **at-the-money-forward** normal (Bachelier) swaption with annuity ``A``, normal vol ``sigma``
and expiry ``T``::

    price = A * sigma * sqrt(T / (2*pi))
    gamma = A / (sigma * sqrt(2*pi*T))
    cost per unit gamma = price / gamma = sigma**2 * T

**The annuity cancels.** That is the load-bearing property of this whole construction: the swaption
side of the comparison needs no curve, no notional convention and no swap-spread assumption --
only a vol and a time. Everything that could go wrong with a forward-rate source (see
``mark_short_receiver``) is confined to the *marking* of an already-open position, never to the
signal that opens it.

For the basis, cost is the net basis itself and gamma is the curvature of the delivery option::

    cost per unit gamma = net_basis_usd / gamma_basis
    richness = (sigma**2 * T) / (net_basis_usd / gamma_basis)

``richness > 1`` means the swaption costs more per unit of gamma, i.e. **the basis is the cheaper
option**. The note's worked example sits at 187/130 ~= 1.44.

Both legs must express gamma in the same convention for the ratio to mean anything; the ratio is
otherwise convention-free, which is why :func:`richness` takes cost-per-gamma on both sides rather
than prices and gammas separately.

TWO DEGENERATE DENOMINATORS
---------------------------
Guarded because each *inverts* the signal rather than merely adding noise, and the guards are fixed
constants rather than grid axes -- a guard that is tuned is not a guard. See the pre-registration.

* ``net_basis -> 0`` (or negative): the basis appears infinitely cheap. A negative net basis also
  contradicts the zero floor the whole thesis rests on, so on this repo's evidence it is a
  data-quality tell rather than a market.
* ``gamma_basis -> 0`` (no CTD switch within reach): the basis appears infinitely expensive.
* Time-of-quarter: ``sigma**2 * T`` shrinks mechanically into delivery while wildcard gamma
  concentrates there, so entries are confined to a fixed days-to-delivery window. Without it a grid
  search finds the calendar, not the trade.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Optional

import numpy as np
import pandas as pd

__all__ = [
    "V3Config",
    "TICK_USD_PER_MM",
    "atmf_normal_price",
    "atmf_normal_gamma",
    "swaption_cost_per_gamma",
    "basis_cost_per_gamma",
    "richness",
    "normal_receiver_price",
    "mark_short_receiver",
    "add_v3_signal",
    "run_v3",
]

TICK_USD_PER_MM = 312.50  # one 32nd on $1mm face
_SQRT_2PI = math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------------------------
# swaption side -- closed forms, normal model
# ---------------------------------------------------------------------------------------------

def atmf_normal_price(annuity: float, vol_bp: float, t_years: float) -> float:
    """Bachelier price of an ATMF swaption. ``vol_bp`` is annualised NORMAL vol in basis points."""
    if t_years <= 0 or vol_bp <= 0:
        return 0.0
    sigma = float(vol_bp) / 1e4
    return float(annuity) * sigma * math.sqrt(float(t_years) / (2.0 * math.pi))


def atmf_normal_gamma(annuity_usd_per_bp: float, vol_bp: float, t_years: float) -> float:
    """ATMF swaption gamma in **$ per bp^2**.

    EVERYTHING in V3 is bp-native: vol in bp, the shift in bp, gamma per bp^2. The basis leg's
    gamma arrives as 32nds/bp^2 and is converted with TICK_USD_PER_MM * face_mm, so the two legs
    are matched in one convention. An earlier version mixed decimal-rate and bp conventions here;
    the swaption notional came out ~0 and arms A and B returned P&L identical to ten decimal
    places, which is what exposed it.
    """
    if t_years <= 0 or vol_bp <= 0:
        return float("nan")
    return float(annuity_usd_per_bp) / (float(vol_bp) * math.sqrt(2.0 * math.pi * float(t_years)))


def swaption_cost_per_gamma(vol_bp: float, t_years: float) -> float:
    """``sigma**2 * T`` -- the annuity-free cost of one unit of ATMF swaption gamma.

    Units are rate^2 (decimal), so a 90bp vol for half a year gives 0.0090^2 * 0.5 = 4.05e-05.
    """
    if t_years <= 0 or vol_bp <= 0:
        return float("nan")
    sigma = float(vol_bp) / 1e4
    return sigma * sigma * float(t_years)


def normal_receiver_price(forward_bp: float, strike_bp: float, vol_bp: float, t_years: float,
                          annuity_usd_per_bp: float = 1.0) -> float:
    """Bachelier receiver value in **$**. Rates and vol in bp; annuity in $ per bp.

    ``A * [ (K-F)*Phi(d) + sigma*sqrt(T)*phi(d) ]`` with ``d = (K-F)/(sigma*sqrt(T))``, everything
    in bp, so the bracket is in bp and multiplying by $/bp gives $.
    """
    F, K = float(forward_bp), float(strike_bp)
    if t_years <= 0 or vol_bp <= 0:
        return float(annuity_usd_per_bp) * max(K - F, 0.0)
    sd = float(vol_bp) * math.sqrt(float(t_years))
    d = (K - F) / sd
    cdf = 0.5 * (1.0 + math.erf(d / math.sqrt(2.0)))
    pdf = math.exp(-0.5 * d * d) / _SQRT_2PI
    return float(annuity_usd_per_bp) * ((K - F) * cdf + sd * pdf)


def mark_short_receiver(forward_bp: float, strike_bp: float, vol_bp: float, t_years: float,
                        annuity_usd_per_bp: float = 1.0) -> float:
    """Value of a SHORT receiver (negative of the long price).

    STICKY-ATM APPROXIMATION, declared in the pre-registration: the vol cube is ATM-only for the
    early sample, so a position that has drifted off the money is marked with the *current ATM* vol
    at its *original* strike. That understates the value of a struck-away option whenever the smile
    is not flat. It cannot affect entry decisions -- the signal is ATMF by construction -- only the
    mark-to-market path of an already-open swaption leg.
    """
    return -normal_receiver_price(forward_bp, strike_bp, vol_bp, t_years, annuity_usd_per_bp)


# ---------------------------------------------------------------------------------------------
# basis side, and the comparison
# ---------------------------------------------------------------------------------------------

def basis_cost_per_gamma(net_basis_usd: float, gamma_basis: float) -> float:
    """Cost of one unit of basis gamma. ``gamma_basis`` must use the same rate convention as
    :func:`atmf_normal_gamma` (decimal rate), or the ratio is meaningless."""
    if not np.isfinite(net_basis_usd) or not np.isfinite(gamma_basis) or gamma_basis <= 0:
        return float("nan")
    return float(net_basis_usd) / float(gamma_basis)


def richness(swaption_cpg: float, basis_cpg: float) -> float:
    """``> 1`` means the swaption costs more per unit of gamma, i.e. the basis is the cheaper option."""
    if not np.isfinite(swaption_cpg) or not np.isfinite(basis_cpg) or basis_cpg <= 0:
        return float("nan")
    return float(swaption_cpg) / float(basis_cpg)


# ---------------------------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------------------------

@dataclass
class V3Config:
    root: str = "ZB"

    # A = long basis outright (the note's literal trade, swaption as yardstick)
    # B = long basis + short gamma-matched ATMF receiver (the RV structure)
    # C = ablation: cheap net basis alone, no vol leg -- a kill condition, not a candidate
    arm: str = "A"

    # --- signal (grid axes) ---------------------------------------------------------------
    entry_richness: float = 1.25
    exit_richness: float = 1.00
    max_hold_days: int = 21
    take_profit_ticks: Optional[float] = None

    # Arm C enters on net basis cheapness alone, in ticks, with no reference to vol.
    entry_net_basis_ticks: float = 6.0

    # --- guards: FIXED, never searched ----------------------------------------------------
    min_net_basis_ticks: float = 1.0
    min_gamma: float = 1e-5   # 32nds per bp^2; set from the gamma DISTRIBUTION, before any P&L
    dtd_min: int = 21
    dtd_max: int = 120

    # --- mechanics ------------------------------------------------------------------------
    exec_lag_days: int = 1
    max_gap_days: int = 5
    stop_ticks: Optional[float] = None

    # --- sizing / costs -------------------------------------------------------------------
    face_mm: float = 100.0
    cost_32nds: float = 0.5          # basis round trip
    swaption_cost_vol_bp: float = 0.25  # swaption round trip, in normal bp of vol
    cost_mult: float = 1.0

    def key(self) -> str:
        tp = "na" if self.take_profit_ticks is None else f"{self.take_profit_ticks:g}"
        return (f"{self.root}/{self.arm}/e{self.entry_richness:g}/x{self.exit_richness:g}"
                f"/h{self.max_hold_days}/tp{tp}/cm{self.cost_mult:g}")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class V3Result:
    daily: pd.DataFrame
    trades: pd.DataFrame
    panel: pd.DataFrame
    config: V3Config


# ---------------------------------------------------------------------------------------------
# signal assembly
# ---------------------------------------------------------------------------------------------

def add_v3_signal(panel: pd.DataFrame, cfg: V3Config) -> pd.DataFrame:
    """Attach ``swaption_cpg``, ``basis_cpg``, ``richness`` and the entry eligibility mask.

    Expects the V3 panel: the V1 basis panel plus ``swaption_vol_bp``, ``t_expiry_years``,
    ``gamma_basis`` and ``days_to_delivery``.
    """
    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p.sort_values("date").reset_index(drop=True)

    nb_ticks = p["ctd_bnoc32"].astype(float)
    p["net_basis_usd"] = nb_ticks * TICK_USD_PER_MM * cfg.face_mm

    # v3_panel precomputes these in bp^2 (market cost / model gamma). Recompute only if absent, so
    # the engine and the panel can never disagree about what the signal is.
    if "richness" not in p.columns:
        p["swaption_cpg"] = p["swaption_vol_bp"].astype(float) ** 2 * p["t_expiry_years"].astype(float)
        p["basis_cpg"] = p["ctd_bnoc32"].astype(float) / p["gamma_basis"].astype(float)
        p["richness"] = p["swaption_cpg"] / p["basis_cpg"]

    # the guards -- fixed, and applied to ENTRY eligibility only, never to exits
    dtd = p["days_to_delivery"].astype(float)
    p["eligible"] = (
        (nb_ticks >= cfg.min_net_basis_ticks)
        & (p["gamma_basis"].astype(float) >= cfg.min_gamma)
        & (dtd >= cfg.dtd_min)
        & (dtd <= cfg.dtd_max)
        & np.isfinite(p["richness"].astype(float))
        & (~p["is_roll"].astype(bool) if "is_roll" in p.columns else True)
    )
    return p


def _entry_signal(p: pd.DataFrame, cfg: V3Config) -> np.ndarray:
    """Arms A and B trade the richness ratio; arm C ignores it entirely."""
    if cfg.arm == "C":
        return (p["ctd_bnoc32"].astype(float) >= cfg.entry_net_basis_ticks).to_numpy()
    return (p["richness"].astype(float) >= cfg.entry_richness).to_numpy()


def run_v3(panel: pd.DataFrame, cfg: V3Config) -> V3Result:
    """Long-basis (arms A/C) or long-basis/short-receiver (arm B), on the V3 panel.

    P&L convention follows V1 exactly: the basis leg's daily P&L is ``d(net basis)``, because
    ``d(P_cash) - CF*d(F) + coupon - repo`` collapses to it and carry is already inside. A ROLL IS
    NEVER A RETURN -- on a roll day the net basis jumps to a different contract's, which is not P&L,
    so positions are forced flat and the jump is skipped.

    Arm B adds ``-d(short receiver value)``. The swaption leg is gamma-matched at ENTRY and held
    statically; re-hedging is a different strategy.
    """
    p = add_v3_signal(panel, cfg)
    n = len(p)
    if n == 0:
        empty = pd.DataFrame()
        return V3Result(empty, empty, p, cfg)

    nb = p["ctd_bnoc32"].astype(float).to_numpy()          # ticks
    roll = p["is_roll"].astype(bool).to_numpy() if "is_roll" in p.columns else np.zeros(n, bool)
    elig = p["eligible"].to_numpy()
    sig = _entry_signal(p, cfg)
    rich = p["richness"].astype(float).to_numpy()
    dates = p["date"].to_numpy()
    gaps = np.r_[0, (p["date"].diff().dt.days.to_numpy()[1:])]

    use_swaption = cfg.arm == "B"
    fwd = p.get("forward_rate")
    vol = p.get("swaption_vol_bp")
    tex = p.get("t_expiry_years")
    ann = p.get("swaption_annuity")
    # the panel carries forward_rate in PERCENT; V3 is bp-native throughout
    fwd = (fwd.astype(float).to_numpy() * 100.0) if fwd is not None else np.full(n, np.nan)
    vol = vol.astype(float).to_numpy() if vol is not None else np.full(n, np.nan)
    tex = tex.astype(float).to_numpy() if tex is not None else np.full(n, np.nan)
    ann = ann.astype(float).to_numpy() if ann is not None else np.ones(n)

    pos = 0            # 0 flat, 1 long basis
    entry_i = -1
    entry_nb = np.nan
    strike = np.nan
    swpt_ratio = 0.0   # swaption notional multiplier that gamma-matches the basis at entry
    swpt_entry_val = 0.0

    pnl = np.zeros(n)
    pnl_b = np.zeros(n)   # basis leg only
    pnl_s = np.zeros(n)   # swaption leg only
    cost = np.zeros(n)
    in_pos = np.zeros(n, int)
    trades = []

    lag = max(int(cfg.exec_lag_days), 0)

    for i in range(1, n):
        # ---- mark an open position ------------------------------------------------------
        if pos:
            if roll[i] or gaps[i] > cfg.max_gap_days:
                reason = "roll" if roll[i] else "gap"
                # no P&L across a roll or a data gap
                trades.append(_close(p, entry_i, i, entry_nb, nb, reason, cfg, pnl, pnl_b, pnl_s, cost,
                                     use_swaption, fwd, vol, tex, ann, strike, swpt_ratio,
                                     swpt_entry_val, book_today=False))
                pos = 0
                in_pos[i] = 0
                continue

            leg_b = (nb[i] - nb[i - 1]) * TICK_USD_PER_MM * cfg.face_mm
            leg_s = 0.0
            if use_swaption and np.isfinite(strike):
                v_now = mark_short_receiver(fwd[i], strike, vol[i], tex[i], ann[i]) * swpt_ratio
                v_prev = mark_short_receiver(fwd[i - 1], strike, vol[i - 1], tex[i - 1], ann[i - 1]) * swpt_ratio
                if np.isfinite(v_now) and np.isfinite(v_prev):
                    leg_s = v_now - v_prev
            pnl_b[i] += leg_b
            pnl_s[i] += leg_s
            pnl[i] += leg_b + leg_s
            in_pos[i] = 1

            held = i - entry_i
            gain_ticks = nb[i] - entry_nb
            hit_tp = cfg.take_profit_ticks is not None and gain_ticks >= cfg.take_profit_ticks
            hit_stop = cfg.stop_ticks is not None and gain_ticks <= -abs(cfg.stop_ticks)
            exit_sig = (cfg.arm != "C") and np.isfinite(rich[i]) and rich[i] <= cfg.exit_richness
            if cfg.arm == "C":
                exit_sig = nb[i] <= cfg.min_net_basis_ticks
            if hit_tp or hit_stop or exit_sig or held >= cfg.max_hold_days or i == n - 1:
                reason = ("take_profit" if hit_tp else "stop" if hit_stop else
                          "signal" if exit_sig else "max_hold" if held >= cfg.max_hold_days else "end")
                trades.append(_close(p, entry_i, i, entry_nb, nb, reason, cfg, pnl, pnl_b, pnl_s, cost,
                                     use_swaption, fwd, vol, tex, ann, strike, swpt_ratio,
                                     swpt_entry_val, book_today=True))
                pos = 0
            continue

        # ---- consider an entry, with the execution lag ----------------------------------
        j = i - lag
        if j < 1 or not elig[j] or not sig[j]:
            continue
        if roll[i] or gaps[i] > cfg.max_gap_days:
            continue
        pos = 1
        entry_i = i
        entry_nb = nb[i]
        in_pos[i] = 1
        c = cfg.cost_mult * cfg.cost_32nds * TICK_USD_PER_MM * cfg.face_mm
        if use_swaption:
            # both in $ per bp^2
            g_b = float(p["gamma_basis"].iloc[i]) * TICK_USD_PER_MM * cfg.face_mm
            g_s = atmf_normal_gamma(ann[i], vol[i], tex[i])
            swpt_ratio = (g_b / g_s) if (np.isfinite(g_s) and g_s > 0) else 0.0
            strike = fwd[i]
            swpt_entry_val = mark_short_receiver(fwd[i], strike, vol[i], tex[i], ann[i]) * swpt_ratio
            # Swaption round trip, charged as a vol-bp cost on the matched notional.
            #
            # NO /1e4. This module is bp-native by declaration (see atmf_normal_gamma) and
            # `swaption_annuity` is "$ per bp on $1mm notional" (v3_panel.py:249), so the ATM
            # Bachelier price IS `ann * vol_bp * sqrt(T/2pi)` -- verified against this module's own
            # `normal_receiver_price` at ratio 1.00000000. The extra division was a leftover from a
            # decimal-rate convention and under-charged the swaption leg by a factor of 10,000:
            # UB $0.63 instead of $6,332, ZB $2.39 instead of $23,948, ZN $2.22 instead of $22,203.
            # The pre-registration required "a separate swaption round-trip cost in normal-bp of
            # vol -- an RV trade costed on one leg only flatters itself"; until now it was not met.
            c += cfg.cost_mult * abs(swpt_ratio) * ann[i] * cfg.swaption_cost_vol_bp * math.sqrt(
                max(tex[i], 0.0) / (2.0 * math.pi))
        cost[i] += c
        pnl[i] -= c

    daily = pd.DataFrame(
        {"pnl": pnl, "pnl_basis": pnl_b, "pnl_swaption": pnl_s, "cost": cost, "in_pos": in_pos,
         "richness": rich, "nb32": nb},
        index=pd.DatetimeIndex(dates, name="date"),
    )
    daily["equity"] = daily["pnl"].cumsum()
    daily["pnl_32nds"] = daily["pnl"] / (TICK_USD_PER_MM * cfg.face_mm)
    daily["pnl_volbp"] = daily["pnl_32nds"]  # analytics.summarize's default column
    return V3Result(daily, pd.DataFrame(trades), p, cfg)


def _close(p, entry_i, i, entry_nb, nb, reason, cfg, pnl, pnl_b, pnl_s, cost, use_swaption,
           fwd, vol, tex, ann, strike, swpt_ratio, swpt_entry_val, book_today: bool) -> dict:
    """Book the unwind. ``book_today=False`` is the roll/gap path: flatten without P&L."""
    c = cfg.cost_mult * cfg.cost_32nds * TICK_USD_PER_MM * cfg.face_mm
    if use_swaption:
        # bp-native, no /1e4 -- see the entry leg above.
        c += cfg.cost_mult * abs(swpt_ratio) * ann[i] * cfg.swaption_cost_vol_bp * math.sqrt(
            max(tex[i], 0.0) / (2.0 * math.pi))
    cost[i] += c
    pnl[i] -= c
    return {
        "entry_date": p["date"].iloc[entry_i],
        "exit_date": p["date"].iloc[i],
        "held_days": int(i - entry_i),
        "reason": reason,
        "entry_nb32": float(entry_nb),
        "exit_nb32": float(nb[i]),
        "entry_richness": float(p["richness"].iloc[entry_i]),
        "symbol": p["symbol"].iloc[entry_i] if "symbol" in p.columns else "",
        "pnl": float(np.nansum(pnl[entry_i:i + 1])),
        "pnl_basis": float(np.nansum(pnl_b[entry_i:i + 1])),
        "pnl_swaption": float(np.nansum(pnl_s[entry_i:i + 1])),
        "fees": float(np.nansum(cost[entry_i:i + 1])),
        "pnl_volbp": float(np.nansum(pnl[entry_i:i + 1]) / (TICK_USD_PER_MM * cfg.face_mm)),
    }
