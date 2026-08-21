"""Dump everything the trigger figure pack needs, once, so the figures are cheap to iterate.

Runs the BASELINE config exactly as RESULTS.md defines it and writes:

    trig_closed.parquet     one row per completed package (the trade log, with trade_id)
    trig_legs.parquet       one row per (trade, leg)
    trig_daily.parquet      date / pnl_bp / mtm_bp / open_positions
    trig_scores.parquet     date, cusip, score  -- the z on EVERY gated bond-day
    trig_lastday.parquet    the full eligible cross-section on the last trade's ENTRY date
    trig_lastpath.parquet   per-day yields of the last trade's three legs, entry -> exit
    trig_meta.json          the config, the summary, and the last trade's identity
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

OUT = _HERE / "_data"
FUND = "TLT"


def main() -> int:
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([FUND], panel=panel)
    cfg = EN.merge_config({"fund": FUND, "universe": {"start": "2016-01-01"}})
    uni, fn = EN.prepare_universe(cfg, joined=joined, panel=panel)
    res = EN.run_config(cfg, universe=uni, prepared_funnel=fn)
    summ = EN.summarize(res)
    print("summary:", {k: (str(v) if isinstance(v, pd.Timestamp) else v)
                       for k, v in summ.items()})

    closed = res.closed.copy()
    closed.to_parquet(OUT / "trig_closed.parquet", index=False)
    res.legs.to_parquet(OUT / "trig_legs.parquet", index=False)
    res.daily.to_parquet(OUT / "trig_daily.parquet", index=False)

    # ---- the two comparison books, run through the SAME machinery -------------------
    # Without these the equity curve has nothing to be judged against. ``resid`` is the
    # bond's own richness against its local curve and reads no ETF file; ``deletion`` is
    # the calendar-only 20-year crossing and reads no ETF file either. Same universe,
    # same wings, same measured cost -- only the score differs.
    for tag, comp in (("control_resid", {"resid": 1.0}),
                      ("null_deletion", {"deletion": 1.0})):
        r2 = EN.run_config({**cfg, "signal": {**cfg["signal"], "components": comp}},
                           universe=uni, prepared_funnel=fn)
        r2.closed.to_parquet(OUT / f"trig_closed_{tag}.parquet", index=False)
        s2 = EN.summarize(r2)
        print(f"{tag}: {s2['trades']} trades  gross {s2['gross_avg_bp']:+.4f}  "
              f"cost {s2['cost_avg_bp']:.4f}  net {s2['avg_bp']:+.4f}")

    # ---- the z on every gated bond-day, exactly as the engine scored it -------------
    sc = cfg["signal"]
    sp = spec(FUND)
    kw = dict(sc.get("kwargs") or {})
    kw.setdefault("deletion", {}).setdefault("band_low", sp.band_low or 0.0)
    kw.setdefault("addition", {}).setdefault("band_high", sp.band_high or np.inf)
    scored = SIG.combine(uni, sc["components"], z_mode=sc["z_mode"],
                         z_lookback=sc["z_lookback"], robust_z=sc["robust_z"],
                         smooth_days=sc["smooth_days"], signal_kwargs=kw)
    scored = HP.apply_exec_lag(scored, exec_lag=int(cfg["timing"]["exec_lag"]))
    # ``is_entry_day`` marks the as-of dates the rule actually looked at. Without it a
    # selection rate is diluted 5x by the 4-in-5 days that entry_every=5 never reads,
    # and the figure reads as "the rule ignores extreme z" when it is simply asleep.
    entry_asof = set(pd.to_datetime(
        scored.loc[scored["trade_date"].isin(set(closed["opened_at"])), "date"].unique()))
    scored["is_entry_day"] = scored["date"].isin(entry_asof)
    scored[["date", "cusip", "ttm", "score", "resid_bp", "active_w", "ownership",
            "is_entry_day"]].to_parquet(OUT / "trig_scores.parquet", index=False)

    # ---- the most recent trigger ----------------------------------------------------
    last = closed.sort_values("opened_at").iloc[-1]
    tdate = pd.Timestamp(last["opened_at"])
    xdate = pd.Timestamp(last["closed_at"])
    legs = res.legs[res.legs["trade_id"] == last["trade_id"]].copy()
    cus = list(legs["cusip"])

    day = uni[uni["date"] == tdate].copy()
    day.to_parquet(OUT / "trig_lastday.parquet", index=False)

    path = uni[(uni["date"].between(tdate, xdate)) & (uni["cusip"].isin(cus))].copy()
    path[["date", "cusip", "ytm", "mod_dur", "clean_price", "resid_bp"]] \
        .to_parquet(OUT / "trig_lastpath.parquet", index=False)

    asof = sorted([d for d in uni["date"].unique() if d < tdate])[-1]
    meta = {
        "config": cfg,
        "summary": {k: (str(v) if isinstance(v, pd.Timestamp) else float(v)
                        if isinstance(v, (int, float, np.floating)) else v)
                    for k, v in summ.items()},
        "funnel": {k: (int(v) if isinstance(v, (int, np.integer)) else v)
                   for k, v in res.funnel.items()},
        "last_trade": {k: (str(v) if isinstance(v, pd.Timestamp) else float(v))
                       for k, v in last.items() if k != "belly"},
        "last_belly": str(last["belly"]),
        "last_asof": str(pd.Timestamp(asof).date()),
        "last_legs": legs.to_dict("records"),
        "n_scored_bond_days": int(scored["score"].notna().sum()),
    }
    (OUT / "trig_meta.json").write_text(json.dumps(meta, indent=2, default=str),
                                        encoding="utf-8")
    print("last trade:", last["belly"], tdate.date(), "->", xdate.date(),
          "side", last["side"], "z", round(float(last["score"]), 3))
    print("legs:\n", legs.to_string(index=False))
    print("wrote to", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
