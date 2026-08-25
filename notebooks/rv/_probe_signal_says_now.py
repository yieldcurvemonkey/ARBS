"""What does the signal say RIGHT NOW at a 2-3 month horizon, and is that
horizon worth anything?

Two separate questions and they have different answers:
  (a) which way is the rule currently pointing?
  (b) does the rule have a measured edge at that holding period?
"""
from __future__ import annotations

import dataclasses
import io
import pathlib
import pickle
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fed_expected_sentiment as E  # noqa: E402

pd.set_option("display.width", 210)


def line(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76, flush=True)


zc, _ = E.load_composite()
zc = zc.dropna()
line("A. WHICH WAY IS THE RULE POINTING TODAY?")
print(f"composite last {zc.index[-1].date()}  z = {zc.iloc[-1]:+.4f}")
print(f"  8 weeks ago {zc.index[-9].date()}  z = {zc.iloc[-9]:+.4f}")
print(f" 13 weeks ago {zc.index[-14].date()} z = {zc.iloc[-14]:+.4f}\n")

rows = []
for reading in ("level", "chg"):
    for lead in E.LEADS_W:
        for h in (4, 8, 13):          # 1, 2 and 3 months
            cfg = dataclasses.replace(E.PRIMARY, reading=reading, lead_w=lead,
                                      horizon_w=h)
            s = E.build_signal(zc, cfg)
            if s.empty:
                continue
            v = float(s.iloc[-1])
            near, far = cfg.lags()
            # FOLLOW (the frozen direction): hot data -> PAY.  side = -sign(s)
            side = 0 if v == 0 else (-1 if v > 0 else +1)
            rows.append({"reading": reading, "lead_L": lead, "horizon_w": h,
                         "lags": f"{near},{far}", "signal_now": v,
                         "follow_says": "RECEIVE" if side > 0 else "PAY"})
NOW = pd.DataFrame(rows)
print(NOW.to_string(index=False))
n_rec = int((NOW["follow_says"] == "RECEIVE").sum())
print(f"\n  {n_rec} of {len(NOW)} cells currently say RECEIVE "
      f"({100*n_rec/len(NOW):.0f}%).")

line("B. IS THE 2-3 MONTH HORIZON WORTH ANYTHING? (measured in PR #501)")
pk = pathlib.Path(r"C:/Users/chris/clee/ARBS-fdx/notebooks/rv/"
                  r"fed_expected_sentiment_results.pkl")
if not pk.exists():
    print(f"  {pk} not found -- run fed_expected_sentiment_grids.py")
else:
    R = pickle.load(open(pk, "rb"))
    for name in ("SR3", "OIS21"):
        r = R.get(name)
        if not r:
            continue
        lg = r["league"]
        nm = r["null_summary"]
        print(f"\n{name}: null median {nm['median']:.4f}, q95 {nm['q95']:.4f} "
              f"(exhaustive {nm['draws']} rotations)")
        g = (lg.dropna(subset=["sharpe"]).groupby("horizon_w")
               .agg(cells=("sharpe", "size"), median_sharpe_wk=("sharpe", "median"),
                    best_sharpe_wk=("sharpe", "max"),
                    median_avg_bp=("avg_bp", "median"),
                    follow_share=("sign", lambda s: float((s == "follow").mean()))))
        g["best_beats_null_median"] = g["best_sharpe_wk"] > nm["median"]
        g["median_beats_null_median"] = g["median_sharpe_wk"] > nm["median"]
        print("   " + g.to_string().replace("\n", "\n   "))

        h8 = lg[(lg["horizon_w"] == 8) & lg["sharpe"].notna()]
        if len(h8):
            print(f"\n   the 8-week (2-month) slice alone: {len(h8)} cells, "
                  f"best {h8['sharpe'].max():.4f} vs null median "
                  f"{nm['median']:.4f} -> "
                  f"{'ABOVE' if h8['sharpe'].max() > nm['median'] else 'BELOW'}")
            rec = h8[h8["sign"] == "follow"]
            print(f"   of those, {len(rec)} prefer FOLLOW "
                  f"({100*len(rec)/len(h8):.0f}%), median avg "
                  f"{h8['avg_bp'].median():+.3f}bp per trade")

line("C. THE PRE-REGISTERED CELL, EXTENDED TO A 2-3 MONTH HOLD")
try:
    import fed_detachment_prices as PX

    PX.seed_local_cache()
    syms = PX.sr3_universe(pd.Timestamp("2018-05-07").date(),
                           pd.Timestamp("2026-08-24").date(), max_rank=4)
    panel = PX.settle_panel(syms)
    sess = np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")
    out = []
    for h in (4, 8, 13):
        cfg = dataclasses.replace(E.PRIMARY, horizon_w=h)
        s = E.build_signal(zc, cfg)
        s = s[s.index >= pd.Timestamp("2018-05-11")]
        tr = E.schedule_trades(s, cfg, sess)
        bk, _r = E.price_trades(tr, panel, cfg)
        st = E.score_trades(bk, weeks_per_trade=float(h))
        ep = E.episodes(bk)
        out.append({"horizon_w": h, **{k: st[k] for k in
                    ("trades", "avg_bp", "total_bp", "hit", "sharpe_ann", "t_stat")},
                    "episodes": int(ep["episode"].nunique()) if len(ep) else 0})
    print(pd.DataFrame(out).to_string(index=False))
    print("\n  the frozen cell is chg / L0 / threshold 0 / out3 / FOLLOW, i.e.")
    print("  exactly 'receive when the data has softened over the holding period'.")
except Exception as exc:  # noqa: BLE001
    print(f"  failed: {type(exc).__name__}: {exc}")

print("\nDONE", flush=True)
