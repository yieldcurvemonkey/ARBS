"""Where does the fast engine's mark differ from the QDB's, leg by leg, day by day?

The two curves agree in level (0.4bp over 74 days) and their DAILY changes correlate only
0.46. That is the signature of a difference that averages out rather than accumulates,
and it has to be identified rather than described. This walks one package's legs through
both pipelines on the same dates and attributes the gap.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from BT.signals import etf_rebalance as QDB  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402

pd.set_option("display.width", 240)


def main() -> int:
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build(["TLT"], panel=panel)
    cfg = EN.merge_config({"fund": "TLT", "universe": {"start": "2023-01-01"},
                           "price_basis": "eod",
                           "timing": {"hold_days": 10, "entry_every": 21}})
    uni, funnel = EN.prepare_universe(cfg, joined=joined, panel=panel)
    res = EN.run_config(cfg, universe=uni, prepared_funnel=funnel, keep_segments=True)

    one = res.closed.sort_values("opened_at").iloc[[0]]
    legs = res.legs[res.legs.trade_id.isin(one.trade_id)]
    d0, d1 = one["opened_at"].iloc[0], one["closed_at"].iloc[0]
    dates = res.daily.loc[res.daily["date"].between(d0, d1), "date"]
    print(f"ONE package: {one['belly'].iloc[0]} side {one['side'].iloc[0]:+.0f}  "
          f"{d0.date()} -> {d1.date()}  ({len(dates)} marks)")
    print(legs[["role", "cusip", "w"]].to_string(index=False))

    out = QDB.run_qdb(one, legs, dates=dates, charge_fee=False, show_progress=False,
                      name="probe")
    q = out["daily"].set_index("date")["mtm_bp"]

    # The panel's own view of the same legs.
    p = uni[uni["cusip"].isin(legs["cusip"]) & uni["date"].between(d0, d1)]
    ypiv = p.pivot_table(index="date", columns="cusip", values="ytm")
    dpiv = p.pivot_table(index="date", columns="cusip", values="mod_dur")
    ppiv = p.pivot_table(index="date", columns="cusip", values="clean_price")
    w = legs.set_index("cusip")["w"].reindex(ypiv.columns).to_numpy(float)
    side = float(one["side"].iloc[0])

    R = (ypiv.to_numpy(float) * w).sum(axis=1) * 100.0
    fast_lin = pd.Series(-side * (R - R[0]), index=ypiv.index)

    # What the QDB is really doing: notional_i = bpv_i / dv01_per_unit_i, fixed at entry,
    # then dirty NPV repriced. Reproduce that in closed form from the panel and see which
    # of the two it matches.
    dv01_unit = dpiv.iloc[0].to_numpy(float) * ppiv.iloc[0].to_numpy(float) / 100.0 * 1e-4
    face = side * w / dv01_unit                       # $ face per unit belly DV01
    npv = (ppiv.to_numpy(float) / 100.0) * face       # CLEAN value of the fixed package
    fast_full = pd.Series(npv.sum(axis=1) - npv.sum(axis=1)[0], index=ypiv.index)

    j = pd.concat([fast_lin.rename("fast_linear_bp"),
                   fast_full.rename("clean_repriced_bp"),
                   q.rename("qdb_bp")], axis=1).dropna()
    j["lin_vs_qdb"] = j["qdb_bp"] - j["fast_linear_bp"]
    j["reprice_vs_qdb"] = j["qdb_bp"] - j["clean_repriced_bp"]
    print("\ncumulative, bp per unit belly DV01:")
    print(j.round(4).to_string())

    dd = j.diff().dropna()
    print("\ndaily-change correlations against the QDB:")
    print(f"  linear yield-space (-dR)          : {dd['fast_linear_bp'].corr(dd['qdb_bp']):.4f}")
    print(f"  full reprice of the FIXED package : {dd['clean_repriced_bp'].corr(dd['qdb_bp']):.4f}")
    print("\nIf the second is near 1 and the first is not, the gap is the linearisation:")
    print("a DV01-weighted YIELD sum is not the same object as the value of a package of")
    print("fixed notionals, because each leg's own DV01 moves as its yield moves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
