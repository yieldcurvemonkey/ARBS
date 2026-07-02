"""Walk-forward SERFF backtest: SR3 vs covering-ZQ-strip, ledger-driven.

Runner conventions follow BT/signals (config dataclass in, result dataclass
out, matplotlib helper).  Marks are actual exchange EOD settles at contract
multipliers; final settlements are recomputed from fixings and reconciled
against the exchange tail (required data-quality gate).

Structure (explicit, per the design spec): per unit, ``sr3_contracts_per_unit``
SR3 against 1 ZQ per fully covered calendar month with edge stubs weighted
(window days in month)/(days in month) -- aggregate-DV01-neutral ~5 SR3 : 3 ZQ.
The ZQ strip wears the policy path; the tradable signal is the SR3 leg's
basis+turn residual from the ledger.  Sign: residual > 0 means the market
prices remaining SOFR-FF below the model -> SR3 settles higher than priced ->
SR3 price rich -> SHORT SR3 / LONG the ZQ strip.

Daily P&L attribution is an exact telescoping decomposition of each leg's
settle-rate change (order documented, cross-terms explicit):

    realization   -- newly published fixings vs yesterday's expected path,
                     split ``turn`` / ``basis`` by yesterday's day tag
                     (ZQ legs' realization lands in ``policy``: EFFR vs path)
    policy        -- strip-implied EFFR path repricing on remaining days
    spread        -- market flat SOFR-FF add-on repricing (SR3 legs only;
                     one price cannot split this into basis-vs-turn, so it
                     is reported as its own bucket rather than guessed)
    residual      -- exact remainder (compounding cross-terms, stale prices)

A strategy earning only the ``policy`` bucket is a levered strip position,
not a basis trade -- the report makes that visible rather than flattering it.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.serff.config import SerffBacktestConfig
from BT.serff.data import build_panel
from BT.serff.ledger import SerffLedger, build_ledger
from BT.serff.mechanics import (
    SOFR_CAL,
    ContractWindow,
    carry_weights,
    contract_window,
    covering_zq_months,
    fomc_decision_dates,
    implied_remainder,
    prev_business_day_on_or_before,
    settlement_rate,
    zq_monthly_symbols,
)
from BT.serff.walkforward import WalkForwardFits, walk_forward_fits

logger = logging.getLogger(__name__)

_PNL_BUCKETS = ("realized_basis", "realized_turn", "policy", "spread_reprice", "residual", "costs")


# --------------------------------------------------------------------------
# result containers
# --------------------------------------------------------------------------
@dataclass
class SerffBacktestResult:
    config: SerffBacktestConfig
    daily: pd.DataFrame               # date x [pnl, buckets..., position, signal_bp, ...]
    trades: pd.DataFrame              # one row per round trip
    ledgers: Dict[pd.Timestamp, SerffLedger]
    turn_events: pd.DataFrame         # month-end calibration table
    reconciliation: pd.DataFrame      # settle recompute vs exchange tail
    walkforward: WalkForwardFits
    per_regime: pd.DataFrame
    summary: Dict[str, object] = field(default_factory=dict)

    @property
    def cum_pnl(self) -> pd.Series:
        return self.daily["pnl_net"].cumsum()


# --------------------------------------------------------------------------
# leg state for exact attribution
# --------------------------------------------------------------------------
@dataclass
class _LegState:
    symbol: str
    window: ContractWindow
    weights: pd.Series                # carry weights
    contracts: float                  # signed
    point_value: float
    is_sr3: bool
    # yesterday's decomposition inputs
    prev_price: float
    prev_effr_path: pd.Series         # expected EFFR (%) on then-remaining days
    prev_addon: float                 # market flat add-on (%), 0 for missing
    prev_last_pub: datetime.date
    prev_turn_tags: pd.Series         # bool per fixing date (SR3 only)


def _leg_rate(
    fixings: pd.Series,
    w: pd.Series,
    last_pub: datetime.date,
    effr_path: pd.Series,
    addon: float,
    is_sr3: bool,
) -> float:
    """Settle rate (%) for a fixings/path/addon combination (exact convention)."""
    realized_mask = w.index.date <= last_pub
    r = pd.Series(index=w.index, dtype=float)
    r[realized_mask] = fixings.reindex(w.index[realized_mask])
    fwd_idx = w.index[~realized_mask]
    if len(fwd_idx):
        r[~realized_mask] = effr_path.reindex(fwd_idx) + addon
    if r.isna().any():
        raise ValueError("incomplete path in _leg_rate")
    if is_sr3:
        growth = float((1.0 + (r / 100.0) * w / 360.0).prod())
        return (growth - 1.0) * 360.0 / float(w.sum()) * 100.0
    return float((r * w).sum() / float(w.sum()))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _tick_value(root: str, symbol: str, on: datetime.date, trade_cfg) -> float:
    """$ per tick: front-month tick while inside the contract's accrual window."""
    w = contract_window(symbol)
    front = w.start <= on < w.end
    tick = trade_cfg.tick_front[root] if front else trade_cfg.tick_back[root]
    return tick * trade_cfg.point_value[root]


def _remaining_unrealized_bd(window: ContractWindow, decision: datetime.date) -> int:
    from BT.serff.mechanics import is_business_day

    start = max(decision, window.start)
    d, n = start, 0
    while d < window.end:
        n += is_business_day(d)
        d += datetime.timedelta(days=1)
    return n


def _active_sr3(decision: datetime.date, trade_cfg) -> str:
    """Nearest SR3 quarterly still holdable under the roll rule."""
    from BT.serff.mechanics import make_symbol, sr3_quarterly_symbols

    horizon = decision + datetime.timedelta(days=400)
    for sym in sr3_quarterly_symbols(decision, horizon):
        window = contract_window(sym)
        if window.end <= decision:
            continue
        if _remaining_unrealized_bd(window, decision) >= trade_cfg.min_unrealized_bd_to_hold:
            return sym
    raise RuntimeError(f"no active SR3 found for {decision}")


def _wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (center - half, center + half)


# --------------------------------------------------------------------------
# main runner
# --------------------------------------------------------------------------
def run_serff_backtest(
    config: Optional[SerffBacktestConfig] = None,
    *,
    panel: Optional[pd.DataFrame] = None,
    settles: Optional[pd.DataFrame] = None,
    sofr_fixings: Optional[pd.Series] = None,
    effr_fixings: Optional[pd.Series] = None,
    wf: Optional[WalkForwardFits] = None,
    show_progress: bool = True,
) -> SerffBacktestResult:
    """Run the walk-forward ledger backtest.

    All heavy inputs are injectable for tests; by default the panel is built
    in ``published`` alignment, fixings come from the repo cache and settles
    from the Barchart backfill cache.
    """
    from dataclasses import replace

    config = config or SerffBacktestConfig()
    data_cfg = config.data if config.data.alignment == "published" else replace(config.data, alignment="published")
    model_cfg, wf_cfg, trade_cfg = config.model, config.walkforward, config.trade

    if sofr_fixings is None:
        from BT.serff.data import load_fixings

        sofr_fixings = load_fixings("USD-SOFR-1D")
    if effr_fixings is None:
        from BT.serff.data import load_fixings

        effr_fixings = load_fixings("USD-FEDFUNDS")
    if panel is None:
        panel = build_panel(data_cfg, model_cfg, sofr=sofr_fixings, effr=effr_fixings)
    if settles is None:
        from BT.serff.futures_data import backfill_settles, settle_panel

        hist = backfill_settles(data_cfg.start, data_cfg.end or datetime.date.today(), show_progress=show_progress)
        settles = settle_panel(hist)
    if wf is None:
        wf = walk_forward_fits(panel, model_cfg, wf_cfg, show_progress=show_progress)

    # reconciliation gate (expired contracts)
    from BT.serff.futures_data import reconcile_settlements

    recon = reconcile_settlements(
        settles, sofr_fixings, effr_fixings, tolerance_bp=trade_cfg.settle_recon_tolerance_bp
    )
    if len(recon):
        n_bad = int((~recon["ok"]).sum())
        if n_bad:
            logger.warning("Settlement reconciliation: %d/%d contracts outside %.2fbp", n_bad, len(recon), trade_cfg.settle_recon_tolerance_bp)

    meetings = fomc_decision_dates(datetime.date(2015, 1, 1), datetime.date(2035, 1, 1))

    decision_dates = sorted(
        d for d in set(settles.index) if d >= panel.index.min() and wf.as_of(d) is not None
    )

    daily_rows: List[Dict[str, object]] = []
    trades: List[Dict[str, object]] = []
    ledgers: Dict[pd.Timestamp, SerffLedger] = {}

    legs: Dict[str, _LegState] = {}
    position_units = 0
    position_dir = 0
    position_sr3: Optional[str] = None
    entry_info: Dict[str, object] = {}

    iterator = decision_dates
    if show_progress:
        try:
            from tqdm import tqdm

            iterator = tqdm(decision_dates, desc="SERFF backtest")
        except Exception:
            pass

    for ts in iterator:
        t = ts.date() if hasattr(ts, "date") else ts
        row_bkts = {b: 0.0 for b in _PNL_BUCKETS}
        pnl_gross = 0.0

        last_pub = prev_business_day_on_or_before(t - datetime.timedelta(days=1), SOFR_CAL)
        sofr_t = sofr_fixings[sofr_fixings.index.date <= last_pub]
        effr_t = effr_fixings[effr_fixings.index.date <= last_pub]

        fit = wf.as_of(ts)
        # covariates as of decision: latest published panel row
        pub_rows = panel[panel["published_at"] <= pd.Timestamp(t) + pd.Timedelta(hours=16)]
        if pub_rows.empty or fit is None:
            continue
        cov = {"ln_liq": float(pub_rows["ln_liq"].iloc[-1]), "tga_gdp": float(pub_rows["tga_gdp"].iloc[-1])}

        # ---- mark & attribute existing position -----------------------------
        if position_units and legs:
            row_prices = settles.loc[ts] if ts in settles.index else pd.Series(dtype=float)
            strip_syms = set(list(legs) + zq_monthly_symbols(t, contract_window(position_sr3).end))
            zq_prices_today = {
                s: float(row_prices[s])
                for s in strip_syms
                if s.startswith("ZQ") and s in row_prices.index and pd.notna(row_prices[s])
            }
            from BT.serff.mechanics import bootstrap_policy_path

            try:
                path_t = bootstrap_policy_path(t, zq_prices_today, effr_t, meetings) if zq_prices_today else None
            except Exception:
                path_t = None

            for sym, st in list(legs.items()):
                if sym not in settles.columns or ts not in settles.index or pd.isna(settles.at[ts, sym]):
                    continue
                price_t = float(settles.at[ts, sym])
                leg_dollar = st.contracts * st.point_value

                fixings_leg = sofr_t if st.is_sr3 else effr_t
                fwd_idx_prev = st.weights.index[st.weights.index.date > st.prev_last_pub]
                effr_prev = st.prev_effr_path

                try:
                    r_base = _leg_rate(fixings_leg, st.weights, st.prev_last_pub, effr_prev, st.prev_addon, st.is_sr3)
                    # 1) realization: advance last_pub with yesterday's path/addon
                    r_realized = _leg_rate(fixings_leg, st.weights, last_pub, effr_prev, st.prev_addon, st.is_sr3)
                    # 2) policy: swap in today's strip path
                    effr_today = path_t.daily(st.weights.index[st.weights.index.date > last_pub]) if path_t is not None else effr_prev
                    r_policy = _leg_rate(fixings_leg, st.weights, last_pub, effr_today, st.prev_addon, st.is_sr3)
                    # 3) spread: today's actual price defines today's addon
                    ir = implied_remainder(sym, price_t, fixings_leg, last_published=last_pub, shape=effr_today if len(st.weights.index[st.weights.index.date > last_pub]) else None)
                    addon_t = ir.flat_addon if ir.flat_addon is not None else 0.0
                    r_spread = _leg_rate(fixings_leg, st.weights, last_pub, effr_today, addon_t, st.is_sr3) if ir.remaining_days else (100.0 - price_t)

                    d_realize = r_realized - r_base
                    d_policy = r_policy - r_realized
                    d_spread = r_spread - r_policy
                    d_resid = (100.0 - price_t) - r_spread
                except ValueError:
                    # missing fixings tail etc.: everything to residual bucket
                    d_realize = d_policy = d_spread = 0.0
                    d_resid = (100.0 - price_t) - (100.0 - st.prev_price)
                    effr_today, addon_t = st.prev_effr_path, st.prev_addon

                # $ = -delta_rate (points) * point_value * contracts  (price = 100 - rate)
                to_dollar = lambda drate: -drate * leg_dollar
                if st.is_sr3:
                    # split realization into turn/basis by yesterday's tags
                    new_days = st.weights.index[(st.weights.index.date > st.prev_last_pub) & (st.weights.index.date <= last_pub)]
                    turn_w = float(st.weights.reindex(new_days)[st.prev_turn_tags.reindex(new_days).fillna(False)].sum()) if len(new_days) else 0.0
                    tot_w = float(st.weights.reindex(new_days).sum()) if len(new_days) else 0.0
                    frac_turn = (turn_w / tot_w) if tot_w > 0 else 0.0
                    row_bkts["realized_turn"] += to_dollar(d_realize) * frac_turn
                    row_bkts["realized_basis"] += to_dollar(d_realize) * (1 - frac_turn)
                    row_bkts["spread_reprice"] += to_dollar(d_spread)
                else:
                    row_bkts["policy"] += to_dollar(d_realize)  # EFFR realization = policy carry
                    row_bkts["spread_reprice"] += to_dollar(d_spread)
                row_bkts["policy"] += to_dollar(d_policy)
                row_bkts["residual"] += to_dollar(d_resid)
                pnl_gross += (price_t - st.prev_price) * leg_dollar

                st.prev_price = price_t
                st.prev_last_pub = last_pub
                st.prev_effr_path = effr_today if path_t is not None else st.prev_effr_path
                st.prev_addon = addon_t

        # ---- ledger / signal -------------------------------------------------
        sr3_sym = _active_sr3(t, trade_cfg)
        window = contract_window(sr3_sym)
        need_syms = [sr3_sym] + [s for s, _ in covering_zq_months(window)] + zq_monthly_symbols(t, window.end)
        prices = {}
        for s in dict.fromkeys(need_syms):
            if s in settles.columns and ts in settles.index and pd.notna(settles.at[ts, s]):
                prices[s] = float(settles.at[ts, s])

        signal_bp = np.nan
        ledger = None
        if sr3_sym in prices and any(s.startswith("ZQ") for s in prices):
            try:
                ledger = build_ledger(
                    t,
                    sr3_symbol=sr3_sym,
                    prices=prices,
                    sofr_fixings=sofr_t,
                    effr_fixings=effr_t,
                    fit=fit,
                    covariates=cov,
                    meeting_decisions=meetings,
                    cfg=model_cfg,
                    last_published=last_pub,
                )
                ledgers[ts] = ledger
                signal_bp = ledger.structure_residual_bp
                # refresh the SR3 leg's turn-day tags from today's ledger so
                # realization attribution follows the current expected turns
                if position_units and position_sr3 == sr3_sym and position_sr3 in legs:
                    tags = ledger.sr3.daily["source"] == "turn"
                    st = legs[position_sr3]
                    st.prev_turn_tags = tags.reindex(st.weights.index).fillna(False) | st.prev_turn_tags
            except Exception as exc:
                logger.debug("ledger failed %s %s: %s", t, sr3_sym, exc)

        # ---- position management --------------------------------------------
        must_roll = position_sr3 is not None and (position_sr3 != sr3_sym)
        want_exit = position_units and (
            must_roll or (np.isfinite(signal_bp) and abs(signal_bp) <= trade_cfg.exit_threshold_bp)
        )
        if position_units and want_exit:
            cost = 0.0
            for sym, st in legs.items():
                cost += abs(st.contracts) * trade_cfg.cost_ticks_per_leg_per_side * _tick_value(
                    "SR3" if st.is_sr3 else "ZQ", sym, t, trade_cfg
                )
            row_bkts["costs"] -= cost
            trades.append(
                {
                    **entry_info,
                    "exit_date": t,
                    "exit_signal_bp": signal_bp,
                    "exit_reason": "roll" if must_roll else "signal",
                    "exit_cost": cost,
                }
            )
            legs.clear()
            position_units = 0
            position_dir = 0
            position_sr3 = None
            entry_info = {}

        can_enter = (
            not position_units
            and ledger is not None
            and np.isfinite(signal_bp)
            and abs(signal_bp) >= trade_cfg.entry_threshold_bp
        )
        if can_enter:
            position_dir = -int(np.sign(signal_bp))  # residual>0 -> SR3 rich -> short SR3
            position_units = trade_cfg.max_units
            position_sr3 = sr3_sym
            stub = ledger.zq_stub_weights

            new_legs: Dict[str, _LegState] = {}
            sr3_contracts = position_dir * trade_cfg.sr3_contracts_per_unit * position_units
            leg_specs = [(sr3_sym, sr3_contracts, True)]
            for zq_sym, w_stub in stub.items():
                if zq_sym not in prices:
                    continue
                n = -position_dir * position_units * w_stub * (trade_cfg.sr3_contracts_per_unit / 5.0)
                if trade_cfg.round_hedge_contracts:
                    n = float(round(n))
                leg_specs.append((zq_sym, n, False))

            cost = 0.0
            ok = True
            for sym, n, is_sr3 in leg_specs:
                if sym not in prices or n == 0:
                    continue
                w = carry_weights(contract_window(sym), SOFR_CAL)
                fixings_leg = sofr_t if is_sr3 else effr_t
                try:
                    ir = implied_remainder(sym, prices[sym], fixings_leg, last_published=last_pub, shape=ledger.policy_path.daily(w.index[w.index.date > last_pub]) if len(w.index[w.index.date > last_pub]) else None)
                except ValueError:
                    ok = False
                    break
                addon0 = ir.flat_addon if ir.flat_addon is not None else 0.0
                turn_tags = pd.Series(False, index=w.index)
                if is_sr3 and ledger is not None:
                    tags = ledger.sr3.daily["source"] == "turn"
                    turn_tags = tags.reindex(w.index).fillna(False)
                root = "SR3" if is_sr3 else "ZQ"
                new_legs[sym] = _LegState(
                    symbol=sym,
                    window=contract_window(sym),
                    weights=w,
                    contracts=n,
                    point_value=config.trade.point_value[root],
                    is_sr3=is_sr3,
                    prev_price=prices[sym],
                    prev_effr_path=ledger.policy_path.daily(w.index[w.index.date > last_pub]),
                    prev_addon=addon0,
                    prev_last_pub=last_pub,
                    prev_turn_tags=turn_tags,
                )
                cost += abs(n) * trade_cfg.cost_ticks_per_leg_per_side * _tick_value(root, sym, t, trade_cfg)
            if ok and any(s.startswith("ZQ") for s in new_legs) and sr3_sym in new_legs:
                legs = new_legs
                row_bkts["costs"] -= cost
                entry_info = {
                    "entry_date": t,
                    "sr3_symbol": sr3_sym,
                    "direction": position_dir,
                    "units": position_units,
                    "entry_signal_bp": signal_bp,
                    "entry_residual_basis_bp": ledger.sr3.residual_basis_bp,
                    "entry_residual_turn_bp": ledger.sr3.residual_turn_bp,
                    "entry_cost": cost,
                    "sr3_contracts": legs[sr3_sym].contracts,
                    "zq_contracts": {s: st.contracts for s, st in legs.items() if not st.is_sr3},
                }
            else:
                legs = {}
                position_units = 0
                position_dir = 0
                position_sr3 = None

        pnl_net = pnl_gross + row_bkts["costs"]
        attributed = sum(row_bkts[b] for b in _PNL_BUCKETS if b != "costs")
        row_bkts["residual"] += pnl_gross - attributed  # keep buckets exactly summing
        daily_rows.append(
            {
                "date": ts,
                "pnl_gross": pnl_gross,
                "pnl_net": pnl_net,
                **row_bkts,
                "position": position_dir * position_units,
                "sr3_symbol": position_sr3 or sr3_sym,
                "signal_bp": signal_bp,
            }
        )

    if position_units and entry_info:
        trades.append({**entry_info, "exit_date": None, "exit_signal_bp": np.nan, "exit_reason": "open", "exit_cost": 0.0})

    daily = pd.DataFrame(daily_rows).set_index("date") if daily_rows else pd.DataFrame()
    trades_df = pd.DataFrame(trades)

    turn_events = _turn_event_table(panel, wf, model_cfg)
    per_regime = _per_regime_table(daily, panel)
    summary = _summarize(daily, trades_df, turn_events)

    return SerffBacktestResult(
        config=config,
        daily=daily,
        trades=trades_df,
        ledgers=ledgers,
        turn_events=turn_events,
        reconciliation=recon,
        walkforward=wf,
        per_regime=per_regime,
        summary=summary,
    )


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def _turn_event_table(panel: pd.DataFrame, wf: WalkForwardFits, model_cfg) -> pd.DataFrame:
    """Out-of-sample month-end calibration: modeled P(spike) vs realized."""
    rows = []
    me = panel[panel["is_me"] & panel["local_base"].notna()]
    for ts, row in me.iterrows():
        fit = wf.as_of(ts - pd.Timedelta(days=1))
        if fit is None or fit.turn is None:
            continue
        pred = fit.turn.predict(ln_liq=row["ln_liq"], is_qe=bool(row["is_qe"]))
        rows.append(
            {
                "date": ts,
                "is_qe": bool(row["is_qe"]),
                "regime": row["regime"],
                "p_hit_model": pred["p_hit"],
                "q50_model": pred.get("q50", np.nan),
                "spike_realized": row["spike"],
                "hit_realized": row["spike"] > model_cfg.spike_threshold_bp,
            }
        )
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def _per_regime_table(daily: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    regime = panel["regime"].reindex(daily.index).ffill()
    df = daily.copy()
    df["regime"] = regime
    agg = df.groupby("regime").agg(
        pnl_net=("pnl_net", "sum"),
        realized_basis=("realized_basis", "sum"),
        realized_turn=("realized_turn", "sum"),
        policy=("policy", "sum"),
        spread_reprice=("spread_reprice", "sum"),
        costs=("costs", "sum"),
        days=("pnl_net", "size"),
        days_in_position=("position", lambda s: int((s != 0).sum())),
    )
    return agg


def _summarize(daily: pd.DataFrame, trades: pd.DataFrame, turn_events: pd.DataFrame) -> Dict[str, object]:
    if daily.empty:
        return {}
    pnl = daily["pnl_net"]
    monthly = pnl.resample("ME").sum()
    sharpe = float(np.sqrt(252) * pnl.mean() / pnl.std()) if pnl.std() > 0 else np.nan

    # block bootstrap (3-month blocks) on monthly P&L -- small-sample honesty
    rng = np.random.default_rng(0)
    boots = []
    m = monthly.values
    if len(m) >= 6:
        n_blocks = int(np.ceil(len(m) / 3))
        for _ in range(2000):
            starts = rng.integers(0, max(len(m) - 3, 1), size=n_blocks)
            sample = np.concatenate([m[s : s + 3] for s in starts])[: len(m)]
            boots.append(sample.mean())
    boot_ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (np.nan, np.nan)

    out: Dict[str, object] = {
        "total_pnl": float(pnl.sum()),
        "sharpe": sharpe,
        "monthly_mean": float(monthly.mean()) if len(monthly) else np.nan,
        "monthly_mean_ci95_block_bootstrap": boot_ci,
        "n_trades": int(len(trades)),
        "bucket_totals": {b: float(daily[b].sum()) for b in _PNL_BUCKETS},
    }
    if not turn_events.empty:
        n = len(turn_events)
        k = int(turn_events["hit_realized"].sum())
        out["turn_events"] = {
            "n_month_ends": n,
            "realized_hit_rate": k / n,
            "mean_model_p": float(turn_events["p_hit_model"].mean()),
            "hit_rate_wilson95": _wilson(k, n),
            "brier": float(((turn_events["p_hit_model"] - turn_events["hit_realized"].astype(float)) ** 2).mean()),
        }
    return out


def plot_pnl(result: SerffBacktestResult):
    """Cumulative net P&L with source attribution (matplotlib)."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True, height_ratios=[2, 1])
    d = result.daily
    axes[0].plot(d.index, d["pnl_net"].cumsum(), label="net", lw=1.6, color="k")
    for b, c in zip(("realized_basis", "realized_turn", "policy", "spread_reprice"), ("tab:blue", "tab:red", "tab:gray", "tab:green")):
        axes[0].plot(d.index, d[b].cumsum(), label=b, lw=1.0, color=c, alpha=0.8)
    axes[0].legend(loc="upper left", fontsize=8)
    axes[0].set_title("SERFF ledger backtest: cumulative P&L by source ($/unit)")
    axes[1].bar(d.index, d["pnl_net"], width=1.0, color="tab:blue", alpha=0.6)
    axes[1].set_title("daily net P&L")
    fig.tight_layout()
    return fig
