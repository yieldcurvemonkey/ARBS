"""H13 — grail-conditional entries vs unconditional, on Citi curves (pre-reg H-SV-13).

Engine design:

* Per (market, pair, roll segment): ``CurvePricer`` + ``simulate`` build a
  UNIT aged-package ledger at zero cost (fees come from the scaling layer,
  where the signal decides what was actually traded). Segments follow
  ``sv_static_long_control.roll_segments`` (annual, shared boundary date).
* The conditional book scales the stitched unit flows by the LAG-1 grail state
  (repriced flattener carry >= 0 AND gamma_25 > 0, from the detector parquet —
  the state is a market property, priced fresh constant-maturity daily; the
  position P&L is the aged package. That asymmetry is intended.)
* Fees, separable by construction (traded-DV01 columns are kept apart from
  charges): entry/exit at state flips charged as ``initiate``; intra-hold
  hedges at ``hedge``; annual rolls charged ONLY when the state is on at a
  boundary, reported under BOTH the ``roll`` and ``initiate`` conventions
  (the control script's 67.5%-of-headline lesson).
* Placebo: 500 circular shifts (>=260d) of the state series through the
  IDENTICAL scaling machinery — preserves on-fraction and episode-length
  distribution exactly, destroys alignment with the curves.
* Control: state ≡ 1 (the sv static-long book, now on Citi data).

No fitted parameters exist in this rule (the state is a repriced sign), so the
z-signal binding requirements (expanding betas / entry-vintage hedge /
rolling-sigma z) are structurally N/A — stated here, auditable by the checker,
not silently waved through.

Run:  conda run -n stir python scripts/sv_citivelo_h13.py USD [workers]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
PKG_DV01 = 100_000.0
TRIGGER_BP = 25.0
NEVER_ROLL_MONTHS = 1200  # see sv_static_long_control's nanosecond-overflow note
N_PLACEBO = 500
MIN_SHIFT = 260
FLOWS = ["carry", "harvest", "mtm", "cross"]

# Citi 2019 Fig-9 per-pair schedule (one-way, bp of rate, $100k DV01):
# initiation 0.75 on the four tighter pairs, 1.0 on the longer-ended four;
# delta-hedge/roll 0.3 vs 0.4 on the same split. Non-USD and the extra sv pair
# default to the CONSERVATIVE end (1.0/0.40) — recorded as an assumption
# (ledger L-0010): the schedule is a USD 2019 measurement applied cross-market.
_TIGHT = {"USD 10Y5Y/15Y15Y", "USD 10Y10Y/15Y15Y", "USD 10Y10Y/20Y10Y", "USD 15Y5Y/20Y10Y"}
INITIATE_BP_BY_PAIR = {p: 0.75 for p in _TIGHT}
HEDGE_BP_BY_PAIR = {p: 0.30 for p in _TIGHT}


def _segment_unit_ledgers(market: str, seg_days: list) -> dict:
    """One segment: curves once, then a unit simulate per pair. Worker-safe."""
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.StrikelessVol.citivelo import CITIVELO_MARKET_CURVES, CITIVELO_SOURCE, citivelo_pairs
    from RVUtils.StrikelessVol.costs import CostSchedule
    from RVUtils.StrikelessVol.replication import CurvePricer, ReplicationConfig, simulate

    free = CostSchedule(multiplier=0.0)
    mdp = IRSwapsMDP(source=CITIVELO_SOURCE)
    curve_map = mdp.bulk_get_data(
        {"curve_name": CITIVELO_MARKET_CURVES[market], "timestamps": seg_days, "offline": True}
    )
    out = {}
    for pair in citivelo_pairs([market]):
        try:
            ctx = CurvePricer(curve_map, pair, package_dv01_usd=PKG_DV01)
            dates = ctx.dates()
            cfg = ReplicationConfig(trigger_bp=TRIGGER_BP, roll_months=NEVER_ROLL_MONTHS,
                                    package_dv01_usd=PKG_DV01)
            led = simulate(ctx, dates, cfg, free)
            led["dv01_long_unit"] = [abs(float(ctx.dv01(d, "long"))) for d in led.index]
            out[pair.name] = led.reset_index().to_dict("list")
        except Exception as exc:  # noqa: BLE001 - a pair failing a segment is recorded
            out[pair.name] = {"__error__": f"{type(exc).__name__}: {exc}"}
    return out


def _stitch_units(per_seg: list) -> dict:
    """pair -> stitched unit ledger (flows summed on shared boundary dates)."""
    by_pair: dict = {}
    for seg in per_seg:
        for pair_name, payload in seg.items():
            if "__error__" in payload:
                continue
            df = pd.DataFrame(payload).set_index("date")
            df.index = pd.to_datetime(df.index)
            by_pair.setdefault(pair_name, []).append(df)
    stitched = {}
    for pair_name, frames in by_pair.items():
        stacked = pd.concat(frames)
        flows = stacked.groupby(level=0)[FLOWS + ["hedge_dv01_usd", "n_hedges"]].sum()
        state_cols = stacked.groupby(level=0)[["long_notional", "dv01_long_unit",
                                               "position_age_years"]].last()
        stitched[pair_name] = flows.join(state_cols).sort_index()
    return stitched


def _boundary_dates(days: list, segs: list) -> set:
    return {pd.Timestamp(days[j]) for (_, j) in segs[:-1]}


def _book(unit: pd.DataFrame, state: pd.Series, boundaries: set, *,
          initiate_bp: float, hedge_bp: float, roll_bp: float, mult: float,
          roll_kind: str) -> dict:
    """Scale the unit ledger by a {0,1} state and charge what was traded."""
    s = state.reindex(unit.index).fillna(0.0).astype(float)
    gross = unit[FLOWS].mul(s, axis=0).sum(axis=1)
    flips = s.diff().fillna(s.iloc[0])
    opens = (flips > 0).astype(float)
    closes = (flips < 0).astype(float)
    # CostSchedule convention (costs.py): dollars = rate_bp x dv01_traded_usd,
    # so 0.75bp on a $100k/bp package = $75,000 per initiation, matching the
    # 2019 note's Fig-9 units ("one-way mid-to-bid, bp of rate, $100K DV01").
    fee = (opens + closes) * (initiate_bp * mult * PKG_DV01)
    hedge_fee = unit["hedge_dv01_usd"].mul(s, axis=0) * (hedge_bp * mult)
    roll_dates = pd.Series(0.0, index=unit.index)
    for b in boundaries:
        if b in roll_dates.index and s.get(b, 0.0) > 0:
            roll_dates.loc[b] = 1.0
    roll_bp_eff = (roll_bp if roll_kind == "roll" else initiate_bp) * mult
    roll_fee = roll_dates * (roll_bp_eff * PKG_DV01)
    total_cost = fee + hedge_fee + roll_fee
    net = gross - total_cost
    realised_dv01 = (unit["long_notional"].abs() * unit["dv01_long_unit"] * s)
    held = realised_dv01[s > 0]
    denom = float(held.mean()) if len(held) else np.nan

    # episodes
    blocks = []
    on = s > 0
    entry = None
    prev = None
    for d, flag in on.items():
        if flag and entry is None:
            entry = d
        elif not flag and entry is not None:
            blocks.append((entry, prev))
            entry = None
        prev = d
    if entry is not None:
        blocks.append((entry, prev))

    trades = []
    for e, x in blocks:
        seg_net = float(net.loc[e:x].sum())
        seg_gross = float(gross.loc[e:x].sum())
        seg_dv01 = float(realised_dv01.loc[e:x][realised_dv01.loc[e:x] > 0].mean())
        # exit fee lands on the first off day; attribute to the episode
        xi = net.index.get_loc(x)
        if xi + 1 < len(net.index):
            nd = net.index[xi + 1]
            seg_net -= float(total_cost.loc[nd]) * float(closes.loc[nd])
        d = seg_dv01 if np.isfinite(seg_dv01) and seg_dv01 else np.nan
        trades.append({"entry": str(e.date()), "exit": str(x.date()),
                       "n_days": int(on.loc[e:x].sum()),
                       "gross_bp": seg_gross / d, "net_bp": seg_net / d})
    tr = pd.DataFrame(trades)
    daily_net_bp = net / denom if np.isfinite(denom) and denom else net * np.nan
    out = {
        "n_trades": int(len(tr)),
        "n_days_held": int(on.sum()),
        "occupancy": float(on.mean()),
        "gross_bp_total": float(tr["gross_bp"].sum()) if len(tr) else 0.0,
        "net_bp_total": float(tr["net_bp"].sum()) if len(tr) else 0.0,
        "net_bp_per_trade": float(tr["net_bp"].mean()) if len(tr) else np.nan,
        "hit": float((tr["net_bp"] > 0).mean()) if len(tr) else np.nan,
        "median_days": float(tr["n_days"].median()) if len(tr) else np.nan,
        "daily_sharpe": float(daily_net_bp[on].mean() / daily_net_bp[on].std())
        if on.sum() > 2 and daily_net_bp[on].std() > 0 else np.nan,
        "realised_dv01_mean": denom,
    }
    return {"stats": out, "trades": tr, "daily_net_bp": daily_net_bp}


def main() -> None:
    from RVUtils.StrikelessVol.citivelo import stored_dates
    sys.path.insert(0, str(_REPO / "scripts"))
    from sv_static_long_control import roll_segments

    market = (sys.argv[1] if len(sys.argv) > 1 else "USD").upper()
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    det = pd.read_parquet(DATA / f"sv_detector_{market}.parquet")
    det["date"] = pd.to_datetime(det["date"])

    days = stored_dates(market)
    segs = roll_segments(days, 12)
    boundaries = _boundary_dates(days, segs)
    seg_days = [days[i:j + 1] for (i, j) in segs]
    print(f"{market}: {len(days)} days, {len(segs)} roll segments, {workers} workers", flush=True)

    t0 = time.time()
    per_seg = [None] * len(seg_days)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_segment_unit_ledgers, market, sd): k for k, sd in enumerate(seg_days)}
        done = 0
        for fut in as_completed(futs):
            per_seg[futs[fut]] = fut.result()
            done += 1
            print(f"  seg {done}/{len(seg_days)} ({time.time() - t0:.0f}s)", flush=True)
    units = _stitch_units([s for s in per_seg if s])

    results = {}
    rng = np.random.default_rng(20260808)
    for pair_name, unit in units.items():
        d = det[det["pair"] == pair_name].set_index("date").sort_index()
        state = d["grail_flattener"].astype(float).shift(1).fillna(0.0)  # LAG-1
        args = dict(initiate_bp=INITIATE_BP_BY_PAIR.get(pair_name, 1.0),
                    hedge_bp=HEDGE_BP_BY_PAIR.get(pair_name, 0.40),
                    roll_bp=HEDGE_BP_BY_PAIR.get(pair_name, 0.40),
                    mult=1.0, roll_kind="roll")
        cond = _book(unit, state, boundaries, **args)
        ctrl = _book(unit, pd.Series(1.0, index=unit.index), boundaries, **args)

        # placebo: circular shifts through the identical machinery
        placebo_net = []
        s_vals = state.reindex(unit.index).fillna(0.0).to_numpy()
        n = len(s_vals)
        for _ in range(N_PLACEBO):
            k = int(rng.integers(MIN_SHIFT, n - MIN_SHIFT))
            shifted = pd.Series(np.roll(s_vals, k), index=unit.index)
            pb = _book(unit, shifted, boundaries, **args)
            placebo_net.append(pb["stats"]["net_bp_total"])
        placebo_net = np.array(placebo_net)
        real = cond["stats"]["net_bp_total"]
        p_val = float((placebo_net >= real).mean())

        results[pair_name] = {
            "conditional": cond["stats"],
            "control": ctrl["stats"],
            "placebo": {"n": N_PLACEBO, "mean": float(placebo_net.mean()),
                        "p95": float(np.quantile(placebo_net, 0.95)),
                        "p_value_net_ge_real": p_val},
        }
        cond["trades"].to_parquet(DATA / f"h13_trades_{market}_{pair_name.replace(' ', '_').replace('/', '-')}.parquet")
        print(f"  {pair_name}: occ {cond['stats']['occupancy']:.1%}, "
              f"{cond['stats']['n_trades']} trades, net {real:+.1f}bp "
              f"(ctrl {ctrl['stats']['net_bp_total']:+.1f}bp), placebo p={p_val:.3f}", flush=True)

    with open(DATA / f"h13_results_{market}.json", "w") as f:
        json.dump(results, f, indent=1, default=str)
    pd.concat({k: v for k, v in units.items()}, names=["pair"]).to_parquet(
        DATA / f"h13_units_{market}.parquet")
    print(f"done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
