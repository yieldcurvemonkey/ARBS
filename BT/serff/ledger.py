"""Residual ledger: the SERFF aggregator's output shape.

Per decision date the aggregator emits a dated daily path, not a scalar fair
value.  Both legs settle to realized fixings, so at any decision date the
spread is part-locked and part-forecast:

    SR3 - ZQ = [realized-to-date fixings]      (booked from published fixings)
             + [forward-implied remainder]     (backed out of futures prices)
             + [view remainder]                (model expected - market implied)

Day tagging (source): ``realized`` for booked fixings; ``turn`` for the
expected-spike days at each remaining month-end (Layer 2 prices these);
``basis`` for all other forward days (Layer 1 prices these).  The policy
content of every forward day -- the strip-implied EFFR level -- is carried in
a separate column and is *worn, not traded*: it is taken from the ZQ strip
(Layer 0) as given, and the ledger reports the structure's per-meeting policy
sensitivity so the leakage is visible and separable.

Identifiability note (documented, not hidden): a single SR3 price yields ONE
market-implied flat SOFR-FF add-on over its remaining days.  The market side
cannot be split into basis-vs-turn from one price, so the source split of the
residual is model-sided: ``residual_basis`` = (Layer-1 fair basis - market
flat) accrual-weighted; ``residual_turn`` = the model's turn premium (which
the market's flat add-on may or may not contain).  They sum to the total
residual exactly.  The backtest characterizes the turn side against realized
prints rather than assuming the premium away.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from BT.serff.config import SerffModelConfig
from BT.serff.layers import SerffFit, baseline_row
from BT.serff.mechanics import (
    SOFR_CAL,
    ContractWindow,
    PolicyPath,
    bootstrap_policy_path,
    carry_weights,
    contract_window,
    covering_zq_months,
    fomc_effective_date,
    fomc_window_weight,
    implied_remainder,
)
from BT.serff.data import regime_labels


# --------------------------------------------------------------------------
# output containers
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class LegLedger:
    """Dated ledger for one futures leg."""

    symbol: str
    price: float
    implied_rate: float               # 100 - price (%)
    daily: pd.DataFrame               # index=fixing date; see build_leg_ledger
    accrued_days: float               # carry-weighted days already fixed
    remaining_days: float
    accrued_rate_contrib: float       # % contribution of booked fixings to settle
    market_flat_addon_bp: Optional[float]  # flat SOFR-FF (SR3) / EFFR add-on (ZQ) over strip path
    model_rate: float                 # % settle implied by the model path
    residual_total_bp: float          # model - market, accrual-weighted, bp of settle rate
    residual_basis_bp: float
    residual_turn_bp: float


@dataclass(frozen=True)
class SerffLedger:
    """Per-decision-date residual ledger for the SR3-vs-ZQ-strip structure."""

    decision_date: datetime.date
    sr3: LegLedger
    zq_legs: Dict[str, LegLedger]
    zq_stub_weights: Dict[str, float]
    policy_path: PolicyPath
    policy_exposure: pd.DataFrame     # per remaining meeting: net weight of structure
    structure_residual_bp: float      # tradable signal: basis + turn residual on SR3 leg
    residual_by_source: Dict[str, float]
    meta: Dict[str, object] = field(default_factory=dict)


# --------------------------------------------------------------------------
# leg construction
# --------------------------------------------------------------------------
def _turn_day_addons(
    dates: pd.DatetimeIndex,
    fit: SerffFit,
    *,
    ln_liq: float,
    cfg: SerffModelConfig,
) -> Tuple[pd.Series, pd.Series]:
    """Expected spike add-on (bp) per date and its p_hit, on turn dates only.

    The turn model prices the month-end print; pressure is assumed to span
    ``cfg.effective_spike_days`` business days ending at each month-end
    inside the window (fractional trailing day supported).
    """
    addon = pd.Series(0.0, index=dates)
    p_hit = pd.Series(np.nan, index=dates)
    if fit.turn is None or len(dates) == 0:
        return addon, p_hit

    frame = pd.DataFrame(index=dates)
    frame["ym"] = frame.index.to_period("M")
    last_bd = frame.index.to_series().groupby(frame["ym"]).max()

    for ym, me_date in last_bd.items():
        # only true month-ends (window may truncate a month before its end)
        month_last = (pd.Timestamp(ym.end_time).normalize())
        if me_date + pd.Timedelta(days=7) < month_last:
            continue  # window ends mid-month: no month-end print in window
        is_qe = me_date.month in (3, 6, 9, 12)
        pred = fit.turn.predict(ln_liq=ln_liq, is_qe=is_qe)
        spike = max(pred.get("q50", 0.0), 0.0) * pred["p_hit"]
        if spike <= 0:
            continue
        month_days = frame.index[frame["ym"] == ym]
        k = float(cfg.effective_spike_days)
        full = int(np.floor(k))
        frac = k - full
        eligible = month_days[month_days <= me_date]
        tail = eligible[-full:] if full > 0 else eligible[:0]
        for d in tail:
            addon.loc[d] += spike
            p_hit.loc[d] = pred["p_hit"]
        if frac > 0:
            prior = month_days[month_days <= me_date]
            if len(prior) > full:
                d = prior[-(full + 1)]
                addon.loc[d] += spike * frac
                p_hit.loc[d] = pred["p_hit"]
    return addon, p_hit


def build_leg_ledger(
    symbol: str,
    price: float,
    *,
    fixings: pd.Series,               # leg's own index: SOFR for SR3, EFFR for ZQ (%), published only
    policy_path: PolicyPath,
    fit: SerffFit,
    covariates: Dict[str, float],     # ln_liq, tga_gdp as of decision (held flat)
    cfg: SerffModelConfig,
    last_published: datetime.date,
) -> LegLedger:
    window = contract_window(symbol)
    w = carry_weights(window, SOFR_CAL)
    D = float(w.sum())

    realized_mask = w.index.date <= last_published
    w_real, w_fwd = w[realized_mask], w[~realized_mask]
    fixings_real = fixings.reindex(w_real.index)
    accrued_contrib_arith = float((fixings_real * w_real).sum() / D) if len(w_real) else 0.0

    fwd_dates = w_fwd.index
    effr_exp = policy_path.daily(fwd_dates)

    if window.root == "SR3":
        # expected daily SOFR-FF (bp): Layer-1 baseline + Layer-2 turn add-on
        regimes = regime_labels(fwd_dates, cfg)
        base_rows = pd.concat(
            [
                baseline_row(
                    d,
                    regime=regimes.loc[d],
                    ln_liq=covariates["ln_liq"],
                    tga_gdp=covariates["tga_gdp"],
                    mid_month_days=cfg.mid_month_days,
                )
                for d in fwd_dates
            ]
        ) if len(fwd_dates) else pd.DataFrame()
        baseline_bp = pd.Series(fit.level.predict(base_rows), index=fwd_dates) if len(fwd_dates) else pd.Series(dtype=float)
        turn_bp, turn_p = _turn_day_addons(fwd_dates, fit, ln_liq=covariates["ln_liq"], cfg=cfg)
        spread_bp = baseline_bp + turn_bp
        sofr_exp = effr_exp + spread_bp / 100.0

        ir = implied_remainder(symbol, price, fixings, last_published=last_published, shape=effr_exp)
        market_addon_bp = (ir.flat_addon or 0.0) * 100.0 if ir.flat_addon is not None else None

        source = pd.Series("basis", index=fwd_dates)
        source[turn_bp > 0] = "turn"

        # model settle rate: exact compounding over realized + expected path
        full_path = pd.concat([fixings_real, sofr_exp]) if len(w_real) else sofr_exp
        growth = float((1.0 + (full_path.reindex(w.index) / 100.0) * w / 360.0).prod())
        model_rate = (growth - 1.0) * 360.0 / D * 100.0

        resid_daily_bp = spread_bp - (market_addon_bp if market_addon_bp is not None else np.nan)
        res_total = float((resid_daily_bp * w_fwd).sum() / D) if len(fwd_dates) else 0.0
        res_basis = float(((baseline_bp - market_addon_bp) * w_fwd).sum() / D) if len(fwd_dates) else 0.0
        res_turn = float((turn_bp * w_fwd).sum() / D) if len(fwd_dates) else 0.0

        daily = pd.DataFrame(
            {
                "weight": w,
                "status": np.where(realized_mask, "realized", "forward"),
                "fixing": fixings.reindex(w.index),
                "effr_expected": pd.concat([pd.Series(np.nan, index=w_real.index), effr_exp]) if len(w_real) else effr_exp,
                "spread_expected_bp": spread_bp.reindex(w.index),
                "turn_addon_bp": turn_bp.reindex(w.index),
                "turn_p_hit": turn_p.reindex(w.index),
                "sofr_expected": sofr_exp.reindex(w.index),
                "source": pd.Series("realized", index=w.index).where(pd.Series(realized_mask, index=w.index), source.reindex(w.index)),
                "market_flat_addon_bp": market_addon_bp,
                "residual_bp": resid_daily_bp.reindex(w.index),
            }
        )
    else:  # ZQ / SR1 leg: EFFR path is the policy path; no spread layers
        ir = implied_remainder(symbol, price, fixings, last_published=last_published, shape=effr_exp if len(fwd_dates) else None)
        market_addon_bp = (ir.flat_addon or 0.0) * 100.0 if ir.flat_addon is not None else None
        full_path = pd.concat([fixings_real, effr_exp]) if len(w_real) else effr_exp
        model_rate = float((full_path.reindex(w.index) * w).sum() / D)
        res_total = -(market_addon_bp or 0.0)  # model - market = 0 - addon
        res_basis = 0.0
        res_turn = 0.0
        daily = pd.DataFrame(
            {
                "weight": w,
                "status": np.where(realized_mask, "realized", "forward"),
                "fixing": fixings.reindex(w.index),
                "effr_expected": pd.concat([pd.Series(np.nan, index=w_real.index), effr_exp]) if len(w_real) else effr_exp,
                "source": np.where(realized_mask, "realized", "policy"),
                "market_flat_addon_bp": market_addon_bp,
            }
        )

    return LegLedger(
        symbol=symbol.upper(),
        price=float(price),
        implied_rate=100.0 - float(price),
        daily=daily,
        accrued_days=float(w_real.sum()),
        remaining_days=float(w_fwd.sum()),
        accrued_rate_contrib=accrued_contrib_arith,
        market_flat_addon_bp=market_addon_bp,
        model_rate=model_rate,
        residual_total_bp=res_total,
        residual_basis_bp=res_basis,
        residual_turn_bp=res_turn,
    )


# --------------------------------------------------------------------------
# structure ledger
# --------------------------------------------------------------------------
def build_ledger(
    decision_date: datetime.date,
    *,
    sr3_symbol: str,
    prices: Dict[str, float],          # settles as of decision date (SR3 + covering ZQs + strip ZQs)
    sofr_fixings: pd.Series,           # % -- PUBLISHED as of decision date (caller truncates)
    effr_fixings: pd.Series,           # %
    fit: SerffFit,
    covariates: Dict[str, float],      # ln_liq, tga_gdp as of decision date
    meeting_decisions: Sequence[datetime.date],
    cfg: Optional[SerffModelConfig] = None,
    last_published: Optional[datetime.date] = None,
) -> SerffLedger:
    """Assemble the dated, source-tagged residual ledger for one structure.

    ``prices`` must include the SR3 contract and every ZQ month used for the
    policy-path bootstrap (at minimum the months covering the SR3 window).
    """
    cfg = cfg or SerffModelConfig()
    lp = last_published or min(
        sofr_fixings.index.max().date() if len(sofr_fixings) else decision_date,
        effr_fixings.index.max().date() if len(effr_fixings) else decision_date,
    )

    window = contract_window(sr3_symbol)
    zq_prices = {s: p for s, p in prices.items() if s.upper().startswith("ZQ")}
    if not zq_prices:
        raise ValueError("build_ledger requires ZQ strip prices for the policy path")

    policy_path = bootstrap_policy_path(decision_date, zq_prices, effr_fixings, meeting_decisions)

    sr3 = build_leg_ledger(
        sr3_symbol,
        prices[sr3_symbol],
        fixings=sofr_fixings,
        policy_path=policy_path,
        fit=fit,
        covariates=covariates,
        cfg=cfg,
        last_published=lp,
    )

    stub = dict(covering_zq_months(window))
    zq_legs: Dict[str, LegLedger] = {}
    for zq_sym in stub:
        if zq_sym in prices:
            zq_legs[zq_sym] = build_leg_ledger(
                zq_sym,
                prices[zq_sym],
                fixings=effr_fixings,
                policy_path=policy_path,
                fit=fit,
                covariates=covariates,
                cfg=cfg,
                last_published=lp,
            )

    # per-meeting policy exposure of the DV01-weighted structure:
    # SR3 weight minus stub-weighted ZQ coverage (in window-weight units).
    rows = []
    for dec in meeting_decisions:
        eff = fomc_effective_date(dec)
        if eff < window.start or eff >= window.end:
            continue
        w_sr3 = fomc_window_weight(window, eff)
        # ZQ coverage rescaled by month length vs window length:
        # a full ZQ month is ~30/91 of the SR3 window's accrual.
        w_zq_scaled = 0.0
        for zq_sym, sw in stub.items():
            zw = contract_window(zq_sym)
            w_zq_scaled += sw * fomc_window_weight(zw, eff) * (zw.calendar_days / window.calendar_days)
        rows.append(
            {
                "decision": dec,
                "effective": eff,
                "sr3_weight": w_sr3,
                "zq_strip_weight": w_zq_scaled,
                "net_weight": w_sr3 - w_zq_scaled,
            }
        )
    policy_exposure = pd.DataFrame(rows)

    residual_by_source = {
        "basis": sr3.residual_basis_bp,
        "turn": sr3.residual_turn_bp,
        "policy_zq_strip": float(np.nansum([leg.residual_total_bp for leg in zq_legs.values()])),
    }

    return SerffLedger(
        decision_date=decision_date,
        sr3=sr3,
        zq_legs=zq_legs,
        zq_stub_weights=stub,
        policy_path=policy_path,
        policy_exposure=policy_exposure,
        structure_residual_bp=sr3.residual_basis_bp + sr3.residual_turn_bp,
        residual_by_source=residual_by_source,
        meta={"last_published": lp, "train_end": fit.train_end},
    )
