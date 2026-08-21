"""The most recent signal trigger and the exact butterfly it produced, as a ticket.

Prints three things:

1. the last package the baseline config actually entered, with its legs, weights,
   notionals for a stated belly DV01, entry/exit levels and realised P&L;
2. why it fired -- the ladder context on the as-of date the signal was read from; and
3. the live reading on the last date in the panel, i.e. what the same rule says now.

The strategy this comes from does not work (see RESULTS.md). The ticket is the concrete
shape of the trade, not a recommendation.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 240)


def _fmt_bond(row) -> str:
    mat = pd.Timestamp(row["maturity_date"]).strftime("%b-%Y")
    return f"{row['cpn']:.3f}% {mat}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund", default="TLT")
    ap.add_argument("--belly-dv01", type=float, default=100_000.0,
                    help="$ per bp of belly risk to size the ticket on")
    a = ap.parse_args()

    sp = spec(a.fund)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([a.fund], panel=panel)
    cfg = EN.merge_config({"fund": a.fund, "universe": {"start": "2016-01-01"}})
    uni, fn = EN.prepare_universe(cfg, joined=joined, panel=panel)
    res = EN.run_config(cfg, universe=uni, prepared_funnel=fn)

    c = res.closed.sort_values("opened_at")
    last = c.iloc[-1]
    legs = res.legs[res.legs["trade_id"] == last["trade_id"]].copy()
    tdate = pd.Timestamp(last["opened_at"])
    asof = sorted([d for d in uni["date"].unique() if d < tdate])[-1]

    print("=" * 96)
    print(f"MOST RECENT TRIGGER -- {a.fund} constant-maturity ladder, baseline config")
    print("=" * 96)
    print(f"  holdings file read (as-of)  : {pd.Timestamp(asof).date()}")
    print(f"  first tradeable close       : {tdate.date()}   (exec_lag = "
          f"{cfg['timing']['exec_lag']} business day)")
    print(f"  exit                        : {pd.Timestamp(last['closed_at']).date()}  "
          f"({int(last['hold_days'])} business days)")
    print(f"  direction                   : "
          f"{'LONG the belly' if last['side'] > 0 else 'SHORT the belly'}   "
          f"(signal z = {last['score']:+.2f})")

    # ---- the legs -------------------------------------------------------------
    day = uni[uni["date"] == tdate].set_index("cusip")
    rows = []
    for lg in legs.itertuples():
        r = day.loc[lg.cusip]
        w_signed = float(last["side"]) * float(lg.w)
        dv01_leg = w_signed * a.belly_dv01                      # $ per bp
        face = dv01_leg / (float(r["dv01_per_mm"]) / 1e6)       # $ face
        rows.append({
            "role": lg.role, "cusip": lg.cusip, "bond": _fmt_bond(r),
            "ttm_y": round(float(r["ttm"]), 2),
            "dv01_wt": round(float(lg.w), 4),
            "side": "BUY" if w_signed > 0 else "SELL",
            "face_$mm": round(abs(face) / 1e6, 2),
            "dv01_$per_bp": round(abs(dv01_leg), 0),
            "px": round(float(r["clean_price"]), 4),
            "ytm_%": round(float(r["ytm"]), 4),
            "quoted_spread_px_bp": round(float(r["spread_price_bp"]), 2),
        })
    tk = pd.DataFrame(rows)
    print(f"\n  THE STRUCTURE  (DV01-neutral butterfly, sized at "
          f"${a.belly_dv01:,.0f}/bp of belly risk)\n")
    print("  " + tk.to_string(index=False).replace("\n", "\n  "))
    print(f"\n  net DV01 : ${tk.apply(lambda r: r['dv01_$per_bp'] * (1 if r['side'] == 'BUY' else -1), axis=1).sum():,.0f}/bp"
          f"   (0 = neutral)")
    print(f"  net face : ${tk.apply(lambda r: r['face_$mm'] * (1 if r['side'] == 'BUY' else -1), axis=1).sum():,.2f}mm")

    # ---- levels and P&L --------------------------------------------------------
    print(f"\n  LEVELS")
    print(f"    fly rate at entry : {last['R_entry_bp']:+.3f} bp   "
          f"(y_belly - {last['a']:.3f}*y_front - {1 - last['a']:.3f}*y_back)")
    print(f"    fly rate at exit  : {last['R_exit_bp']:+.3f} bp   "
          f"move {last['R_exit_bp'] - last['R_entry_bp']:+.3f} bp")
    print(f"\n  P&L, per unit of belly DV01 (bp), and in $ at this size")
    for k, lbl in (("price_bp", "price"), ("carry_bp", "carry"),
                   ("gross_bp", "GROSS"), ("cost_bp", "cost (full round trip, 3 legs)"),
                   ("pnl_bp", "NET")):
        v = float(last[k])
        sign = -1.0 if k == "cost_bp" else 1.0
        print(f"    {lbl:34s} {v:+8.4f} bp   ${sign * v * a.belly_dv01:+12,.0f}")

    # ---- why it fired ----------------------------------------------------------
    print("\n" + "=" * 96)
    print("WHY IT FIRED -- the ladder around the belly on the as-of date")
    print("=" * 96)
    ctx = uni[uni["date"] == asof].copy()
    ctx["bucket"] = HP.bucket_index(ctx["ttm"], sp, width_y=0.25)
    ctx["z_active"] = SIG.cross_sectional_z(
        SIG.sig_active_w(ctx), ctx["date"], robust=True).clip(-5, 5)
    belly_ttm = float(day.loc[last["belly"], "ttm"])
    near = ctx[(ctx["ttm"] - belly_ttm).abs() <= 1.0].sort_values("ttm")
    show = near[["cusip", "ttm", "cpn", "w_f", "w_i", "active_w", "z_active",
                 "ownership", "resid_bp"]].copy()
    show["w_f_pct"] = (show.pop("w_f") * 100).round(3)
    show["w_i_pct"] = (show.pop("w_i") * 100).round(3)
    show["active_bp"] = (show.pop("active_w") * 1e4).round(2)
    show["own_pct"] = (show.pop("ownership") * 100).round(2)
    show = show.round({"ttm": 2, "cpn": 3, "z_active": 2, "resid_bp": 3})
    show["<<"] = np.where(show["cusip"] == last["belly"], "BELLY", "")
    print("  " + show.to_string(index=False).replace("\n", "\n  "))
    print("\n  active_bp = fund DV01 weight minus index DV01 weight, in bp of the book.")
    print("  Negative = underweight = the fund has buying to do there = the signal buys it.")

    # ---- what it says today ----------------------------------------------------
    print("\n" + "=" * 96)
    print("THE SAME RULE ON THE LAST DATE IN THE PANEL")
    print("=" * 96)
    live_date = uni["date"].max()
    live = uni[uni["date"] == live_date].copy()
    live["z_active"] = SIG.cross_sectional_z(
        SIG.sig_active_w(live), live["date"], robust=True).clip(-5, 5)
    live = live.sort_values("z_active", ascending=False)
    cols = ["cusip", "ttm", "cpn", "z_active", "resid_bp", "ownership", "spread_price_bp"]
    print(f"  as of {pd.Timestamp(live_date).date()}  ({len(live)} eligible bonds)\n")
    print("  most UNDERWEIGHT (the signal would buy the belly here):")
    print("  " + live.head(3)[cols].round(3).to_string(index=False).replace("\n", "\n  "))
    print("\n  most OVERWEIGHT (the signal would sell the belly here):")
    print("  " + live.tail(3)[cols].round(3).to_string(index=False).replace("\n", "\n  "))

    print("\n" + "=" * 96)
    print(f"CONTEXT: this book is {len(c)} trades, gross "
          f"{c['gross_bp'].mean():+.4f} bp/trade against {c['cost_bp'].mean():.3f} bp of")
    print("cost. The structure below is real; the edge behind it is not. See RESULTS.md.")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
