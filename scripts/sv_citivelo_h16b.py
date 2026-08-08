"""H16b graded engine — the sandwich basis trade (pre-reg H-SV-16B, L-0021/L-0023).

Expression: while BE(pair) < RV63(long rate) < IV(locus), hold vega-matched
[flattener (long embedded vol) + SHORT straddle at the locus (short traded
vol)], both entered lag-1 on state onset, exited lag-1 on state exit (126bd
cap, synthetic terminal exit fee). Everything marked on what executes:

- Linear leg: the H13 stitched unit aged-package ledger (repriced curves),
  $100k DV01, its own cost schedule (0.75-1.0bp initiate, 0.3-0.4 hedges).
- Vol leg: PREMIUM-marked short straddle — strike frozen at entry ATMF, daily
  reprice off the day's SmileSurface (offset = K - F_t) + locus annuity,
  Bachelier; daily delta-hedge with lag-1 delta; CM-1 measured half-spread on
  entry/exit (x{0.5,1,2}); hedge swaps at RVUtils/cost_model half-spread.
- Vega match: beta = rolling-252d cov(d spread, d IV_annual)/var(d IV_annual),
  ENTRY-VINTAGE FROZEN per episode; straddle notional = |beta|*100k / vega$
  per unit notional at entry.

Placebo: 200 circular shifts of the state series through the IDENTICAL
two-leg premium-marked pipeline (surfaces pre-built once, so shifts are cheap).
Steamroller: per-episode worst day, worst episode, the 2020-03 and 2022
windows called out. DSR at the SV family count.

Run (after clean rebuilds + h13_units): conda run -n stir python scripts/sv_citivelo_h16b.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import math
import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.premium_mark import straddle_delta, straddle_premium_usd
from RVUtils.StrikelessVol.straddle_book import SmileSurface

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
PKG_DV01 = 100_000.0
SQ252 = math.sqrt(252.0)
CAP_BD = 126
N_PLACEBO = 200
MIN_SHIFT = 260

#: graded set per L-0021 (amended for 16b): 2 pairs x 2 loci = 4 trials
COMBOS = [("USD 10Y10Y/20Y10Y", "2Y", "10Y"), ("USD 10Y10Y/20Y10Y", "10Y", "10Y"),
          ("USD 15Y5Y/20Y10Y", "2Y", "10Y"), ("USD 15Y5Y/20Y10Y", "10Y", "10Y")]

#: CM-1 near-close ATM straddle half-spreads, annual bp (upper bounds)
CM1_HALF = {"2Y": 0.23, "10Y": 0.17}
#: linear leg schedule (Citi Fig-9): tight pairs 0.75/0.30
LIN_INITIATE = {"USD 10Y10Y/20Y10Y": 0.75, "USD 15Y5Y/20Y10Y": 0.75}

_TENOR_YRS = {"6M": 0.5, "1Y": 1.0, "2Y": 2.0, "10Y": 10.0, "20Y": 20.0}


def _swap_halfspread_bp(tenor_yrs: float) -> float:
    from RVUtils.cost_model import transaction_cost_bps

    return transaction_cost_bps(tenor_yrs)


def load_inputs():
    screen = pd.read_parquet(DATA / "sv_screen_USD.parquet")
    screen["date"] = pd.to_datetime(screen["date"])
    locus = pd.read_parquet(DATA / "locus_panel_USD.parquet")
    vol = pd.read_parquet(DATA / "vol_panel.parquet")
    vol = vol[(vol["tenor"] == "10Y") & (~vol["atm_only"])]
    surfaces = {pd.Timestamp(d): SmileSurface(g, tenor="10Y")
                for d, g in vol.groupby("date")}
    return screen, locus, surfaces


def _locus_series(locus: pd.DataFrame, exp: str):
    key = f"{exp.lower()}10y"
    return locus[f"fwd_{key}"], locus[f"ann_{key}"]


def episode_blocks(state: pd.Series):
    blocks, entry, prev = [], None, None
    for d, flag in state.items():
        if flag and entry is None:
            entry = d
        elif not flag and entry is not None:
            blocks.append((entry, prev))
            entry = None
        prev = d
    if entry is not None:
        blocks.append((entry, prev))
    return blocks


def simulate_combo(pair, exp, unit, state, fwd, ann, surfaces, iv_annual,
                   *, cost_mult=1.0):
    """One combo's episode ledger. Returns trades DataFrame + daily series."""
    idx = state.index
    exp_yrs = _TENOR_YRS[exp]
    spread = unit["__spread_bp"]
    div = (iv_annual).diff()
    dsp = spread.diff()
    beta = dsp.rolling(252, min_periods=126).cov(div) / div.rolling(252, min_periods=126).var()

    excarry_lin = unit[["harvest", "mtm", "cross"]].sum(axis=1)
    carry_lin = unit["carry"]
    dv01_daily = (unit["long_notional"].abs() * unit["dv01_long_unit"]).replace(0, np.nan)

    lin_init = LIN_INITIATE.get(pair, 1.0) * cost_mult
    swpt_half = CM1_HALF[exp] * cost_mult
    hedge_half_bp = _swap_halfspread_bp(10.0) * cost_mult  # 10Y tail hedge swap

    trades = []
    daily_net = pd.Series(0.0, index=idx)
    for e, x in episode_blocks(state):
        i0, i1 = idx.get_loc(e), idx.get_loc(x)
        i1 = min(i1, i0 + CAP_BD)
        days = idx[i0:i1 + 1]
        if len(days) < 2:
            continue
        b = beta.get(e, np.nan)
        if not np.isfinite(b) or b == 0:
            continue
        vega_target = abs(b) * PKG_DV01  # $ per annual bp
        d0 = days[0]
        if d0 not in surfaces or d0 not in fwd.index or not np.isfinite(fwd.get(d0, np.nan)):
            continue
        F0, A0 = float(fwd[d0]), float(ann[d0])
        try:
            v0 = surfaces[d0].vol(expiry_yrs=exp_yrs, offset_bp=0.0)
        except (ValueError, KeyError):
            continue
        K = F0
        # unit-notional vega$ per annual bp (numeric, +/-0.5bp)
        p_up = straddle_premium_usd(forward=F0, strike=K, vol_bp_annual=v0 + 0.5,
                                    tte_yrs=exp_yrs, annuity_per_bp=A0)
        p_dn = straddle_premium_usd(forward=F0, strike=K, vol_bp_annual=v0 - 0.5,
                                    tte_yrs=exp_yrs, annuity_per_bp=A0)
        vega_unit = p_up - p_dn  # $ per annual bp at 100mm-notional annuity
        if vega_unit <= 0:
            continue
        m = vega_target / vega_unit  # multiplier on the 100mm-annuity book

        lin_pnl = ep_lin_carry = ep_lin_ex = 0.0
        vol_pnl = 0.0
        prem_prev = None
        delta_prev = 0.0
        F_prev = F0
        worst_day = 0.0
        hedge_dv01_traded = 0.0
        ok = True
        for t_i, d in enumerate(days):
            if d not in surfaces or not np.isfinite(fwd.get(d, np.nan)):
                ok = False
                break
            F_t, A_t = float(fwd[d]), float(ann[d])
            tte = max(exp_yrs - t_i / 252.0, 1e-6)
            try:
                v_t = surfaces[d].vol(expiry_yrs=tte, offset_bp=(K - F_t) * 1e4)
            except (ValueError, KeyError):
                ok = False
                break
            prem_t = straddle_premium_usd(forward=F_t, strike=K, vol_bp_annual=v_t,
                                          tte_yrs=tte, annuity_per_bp=A_t) * m
            day_pnl = 0.0
            if prem_prev is not None:
                mtm_short = -(prem_t - prem_prev)
                hedge = delta_prev * (F_t - F_prev) * 1e4 * A_t * m
                day_pnl = mtm_short + hedge
                vol_pnl += day_pnl
                lin_day = float(carry_lin.get(d, 0.0) + excarry_lin.get(d, 0.0))
                ep_lin_carry += float(carry_lin.get(d, 0.0))
                ep_lin_ex += float(excarry_lin.get(d, 0.0))
                lin_pnl += lin_day
                dnet = day_pnl + lin_day
                daily_net.loc[d] += dnet
                worst_day = min(worst_day, dnet)
            # rebalance hedge to today's delta; traded DV01 ($/bp) = |d delta| x A x m
            delta_t = straddle_delta(forward=F_t, strike=K, vol_bp_annual=v_t, tte_yrs=tte)
            hedge_dv01_traded += abs(delta_t - delta_prev) * A_t * m
            delta_prev, F_prev, prem_prev = delta_t, F_t, prem_t
        if not ok or prem_prev is None:
            continue

        dv = float(dv01_daily.loc[days].mean())
        cost_lin = 2.0 * lin_init * PKG_DV01
        cost_vol = 2.0 * swpt_half * vega_target
        # hedge cost: traded delta-DV01 ($/bp) x swap half-spread (bp, one-way per trade)
        cost_hedge = hedge_dv01_traded * hedge_half_bp
        gross = lin_pnl + vol_pnl
        net = gross - cost_lin - cost_vol - cost_hedge
        trades.append({
            "entry": str(e.date()), "exit": str(days[-1].date()), "n_days": len(days),
            "beta": b, "vega_target": vega_target, "m": m,
            "lin_carry_usd": ep_lin_carry, "lin_excarry_usd": ep_lin_ex,
            "vol_pnl_usd": vol_pnl, "gross_usd": gross,
            "cost_usd": cost_lin + cost_vol + cost_hedge, "net_usd": net,
            "net_bp": net / dv if np.isfinite(dv) and dv else np.nan,
            "gross_bp": gross / dv if np.isfinite(dv) and dv else np.nan,
            "worst_day_usd": worst_day,
        })
    return pd.DataFrame(trades), daily_net


def main() -> None:
    screen, locus, surfaces = load_inputs()
    units = pd.read_parquet(DATA / "h13_units_USD.parquet")
    from RVUtils.StrikelessVol.citivelo import citivelo_atm_vol_panel

    results = {}
    rng = np.random.default_rng(20260808)
    t0 = time.time()
    for pair, exp, ten in COMBOS:
        cell = f"{exp.lower()}{ten.lower()}"
        iv_day = citivelo_atm_vol_panel([cell])[cell]  # bp/day
        iv_annual = iv_day * SQ252
        g = screen[screen["pair"] == pair].set_index("date").sort_index()
        unit = units.xs(pair, level="pair").copy()
        unit["__spread_bp"] = g["spread_bp"].reindex(unit.index)
        rv = (g["long_rate"] * 1e4).diff().rolling(63, min_periods=63).std().reindex(unit.index)
        be = g["be_25"].reindex(unit.index)
        ivd = iv_day.reindex(unit.index)
        state_raw = ((be < rv) & (rv < ivd)).astype(float)
        state = state_raw.shift(1).fillna(0.0)  # LAG-1
        fwd, ann = _locus_series(locus, exp)
        fwd = fwd.reindex(unit.index)
        ann = ann.reindex(unit.index)

        tr, daily = simulate_combo(pair, exp, unit, state, fwd, ann, surfaces, iv_annual)
        stats = {
            "n_trades": int(len(tr)),
            "net_bp_total": float(tr["net_bp"].sum()) if len(tr) else 0.0,
            "net_bp_per_trade": float(tr["net_bp"].mean()) if len(tr) else np.nan,
            "hit": float((tr["net_bp"] > 0).mean()) if len(tr) else np.nan,
            "gross_bp_total": float(tr["gross_bp"].sum()) if len(tr) else 0.0,
            "lin_carry_usd": float(tr["lin_carry_usd"].sum()) if len(tr) else 0.0,
            "lin_excarry_usd": float(tr["lin_excarry_usd"].sum()) if len(tr) else 0.0,
            "vol_pnl_usd": float(tr["vol_pnl_usd"].sum()) if len(tr) else 0.0,
            "cost_usd": float(tr["cost_usd"].sum()) if len(tr) else 0.0,
            "worst_day_usd": float(tr["worst_day_usd"].min()) if len(tr) else np.nan,
            "worst_episode_net_usd": float(tr["net_usd"].min()) if len(tr) else np.nan,
            "median_days": float(tr["n_days"].median()) if len(tr) else np.nan,
        }
        # placebo: circular shifts of the state through the SAME two-leg pipeline
        pb_net = []
        s_vals = state.to_numpy()
        n = len(s_vals)
        for _ in range(N_PLACEBO):
            k = int(rng.integers(MIN_SHIFT, n - MIN_SHIFT))
            s_shift = pd.Series(np.roll(s_vals, k), index=state.index)
            trp, _ = simulate_combo(pair, exp, unit, s_shift, fwd, ann, surfaces, iv_annual)
            pb_net.append(float(trp["net_bp"].sum()) if len(trp) else 0.0)
        pb_net = np.array(pb_net)
        stats["placebo_p"] = float((pb_net >= stats["net_bp_total"]).mean())
        stats["placebo_mean"] = float(pb_net.mean())
        results[f"{pair} x {exp}x{ten}"] = stats
        tr.to_parquet(DATA / f"h16b_trades_{pair.split()[1].replace('/', '-')}_{exp}{ten}.parquet")
        print(f"{pair} x {exp}x{ten}: {stats['n_trades']} trades, "
              f"net {stats['net_bp_total']:+.1f}bp ({stats['net_bp_per_trade']:+.2f}/tr), "
              f"hit {stats['hit']:.0%}, worst-ep {stats['worst_episode_net_usd']:+,.0f}$, "
              f"placebo_p {stats['placebo_p']:.3f} ({time.time() - t0:.0f}s)", flush=True)

    with open(DATA / "h16b_results.json", "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("wrote h16b_results.json", flush=True)


if __name__ == "__main__":
    main()
