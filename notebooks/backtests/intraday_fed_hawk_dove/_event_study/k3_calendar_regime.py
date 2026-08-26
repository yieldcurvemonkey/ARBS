"""CHECKS 1 (refined), 2 and 4, plus the length-matched control window.

k1 flagged contamination on the [-60,+240] interval for every statistic, which
is the right interval for the +240 number but far too wide for the +30 one.
Here each statistic gets its OWN measurement interval flagged.

Also:
  * PRE/POST DECOMPOSITION.  d_rate at offset 0 is the move from the -60
    baseline to the speech minute -- it cannot be a speech response.  Splitting
    the composite into [-60,0] and [0,+off] says how much of it is already
    banked before the speaker opens his mouth.
  * LENGTH-MATCHED CONTROL WINDOW.  The 300 minutes ending at speech-60, on the
    same day and the same contract, from the 1-minute bar cache.  Same length,
    same day, no speech.  This is the fair version of k2's outside-window test,
    which compared a 300-minute window against the ~1,140-minute remainder.
  * CHECK 2: clock buckets (does the window contain 08:30 / 10:00 / 13:00) and
    days_to_fomc terciles.
  * CHECK 4: year splits.
"""
from __future__ import annotations

import io
import json
import pickle
import sys
from pathlib import Path

if __name__ == "__main__":
    # guarded: re-wrapping on import closes the caller's wrapper over the same buffer.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(str(HERE))

from c_common import cluster_mean_se, cluster_ols  # noqa: E402
from k1_release_window import load_calendar, flag_windows, _utc64  # noqa: E402

pd.set_option("display.width", 250)
BARS = HERE / "bars_event_study.pkl"


def line(tag, vals, sgn, clus, extra=""):
    r = cluster_mean_se(np.asarray(vals) * np.asarray(sgn), clus)
    print(f"    {tag:<46s} n={r['n']:>4d} days={r['n_clusters']:>4d}  "
          f"mean={r['mean']:+.4f} bp  t={r['t']:+.2f} {extra}")
    return r


def load(rank):
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    ev = ev[ev["contract_rank"] == rank]
    meta = ev.drop_duplicates("event_id").set_index("event_id").copy()
    y = {}
    for o in (0, 5, 15, 30, 60, 120, 240, 300):
        y[o] = ev[ev["offset_min"] == o].set_index("event_id")["d_rate_bp_from_baseline"].reindex(meta.index)
    return meta, y


def matched_pre_window(meta, bars, length=300, gap=60):
    """Signed rate move over the `length` minutes ending at speech - gap.

    Same day, same contract, same length as the [-60,+240] event window, and it
    contains no speech.  Uses the panel's own bar rule: the price at T is the
    close of the LAST bar labelled strictly before T.
    """
    keep, mv = [], []
    n_short = n_noframe = n_flat = n_crossday = 0
    for eid, row in meta.iterrows():
        t = row["speech_ts"]
        hi = t - pd.Timedelta(minutes=gap)          # = the -60 baseline stamp
        lo = hi - pd.Timedelta(minutes=length)
        if lo.date() != t.date():
            n_crossday += 1
            continue
        b = bars.get((row["symbol"], t.date()))
        if b is None or len(b) < 2:
            n_noframe += 1
            continue
        if b["Close"].nunique() < 2:
            n_flat += 1
            continue
        i_lo = b.index.searchsorted(lo, side="left") - 1
        i_hi = b.index.searchsorted(hi, side="left") - 1
        if i_lo < 0 or i_hi < 0 or i_hi <= i_lo:
            n_short += 1
            continue
        mv.append((float(b["Close"].iloc[i_lo]) - float(b["Close"].iloc[i_hi])) * 100.0)
        keep.append(eid)
    print(f"      matched control window [-360,-60]: kept {len(keep)}  |  dropped: "
          f"crosses midnight {n_crossday}, no frame {n_noframe}, flat day {n_flat}, "
          f"not enough bars before the speech {n_short}")
    return pd.Series(mv, index=keep)


def selftest_matched(bars):
    """Pin matched_pre_window against a hand-computed value from the raw frame."""
    print("SELF-TEST of the matched control window")
    ok = True
    key = None
    for k, v in bars.items():
        if len(v) > 900 and v["Close"].nunique() > 5:
            key = k
            break
    b = bars[key]
    sym, dt = key
    t = pd.Timestamp(f"{dt} 14:00", tz="America/New_York")
    meta = pd.DataFrame({"speech_ts": [t], "symbol": [sym]}, index=[999])
    got = matched_pre_window(meta, bars).iloc[0]
    lo = t - pd.Timedelta(minutes=360)
    hi = t - pd.Timedelta(minutes=60)
    pl = b.loc[b.index < lo, "Close"].iloc[-1]
    ph = b.loc[b.index < hi, "Close"].iloc[-1]
    want = (pl - ph) * 100.0
    print(("  OK   " if np.isclose(got, want) else "  FAIL ") +
          f"{sym} {dt}: {got:+.4f} vs hand {want:+.4f} bp")
    ok = ok and np.isclose(got, want)
    # mutation: a window shifted by 3 hours must give a different number
    meta2 = pd.DataFrame({"speech_ts": [t + pd.Timedelta(hours=3)], "symbol": [sym]}, index=[999])
    got2 = matched_pre_window(meta2, bars).iloc[0]
    print(("  OK   " if not np.isclose(got, got2) else "  FAIL ") +
          f"mutation: shifting the window 3h gives {got2:+.4f} != {got:+.4f}")
    return ok and not np.isclose(got, got2)


def main():
    print("=" * 100)
    print("CHECKS 1 (window-matched), 2 (clock / FOMC clock) and 4 (regime)")
    print("=" * 100)

    cal_all, rel = load_calendar()
    CAL_END = cal_all["release_ts_ny"].max()
    rel_high = rel[rel["impact"] == "high"]["ts"]
    rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]

    print("\nloading bars ...")
    bars = pickle.load(open(BARS, "rb"))
    if not selftest_matched(bars):
        print("STOPPING: matched-window self-test failed")
        return 1

    res = {}
    for rank in (1, 3):
        meta, y = load(rank)
        sg = meta["stance_sign"] != 0
        cov = meta["speech_ts"] <= CAL_END
        base = (sg & cov).to_numpy()
        mb = meta[base]
        sgn = mb["stance_sign"].to_numpy().astype(float)
        clus = mb["date"].to_numpy()
        print("\n" + "=" * 100)
        print(f"RANK {rank}   ALL-SIGNED book, calendar-covered: n={len(mb)} events, "
              f"{mb['date'].nunique()} days")
        print("=" * 100)

        # -------- CHECK 1 REFINED: each statistic flagged on its OWN interval
        print("\n-- CHECK 1 (window-matched release flags) --")
        for off in (30, 240):
            f_h, _ = flag_windows(mb, rel_high, -60, off)
            f_hm, _ = flag_windows(mb, rel_hm, -60, off)
            print(f"  +{off} min  (measurement interval [-60,+{off}])   "
                  f"contaminated: high {f_h.mean():.1%}, high+med {f_hm.mean():.1%}")
            v = y[off][base].to_numpy()
            line(f"  full book", v, sgn, clus)
            for f, nm in ((f_h, "high"), (f_hm, "high+med")):
                a = line(f"  CLEAN  (no {nm} release in window)", v[~f], sgn[~f], clus[~f])
                b = line(f"  CONTAM ({nm} release in window)", v[f], sgn[f], clus[f])
                X = np.column_stack([np.ones(len(v)), f.astype(float)])
                fit = cluster_ols(v * sgn, X, clus, names=["clean", "diff"])
                print(f"      -> contam - clean = {fit['diff']['coef']:+.4f} bp (t={fit['diff']['t']:+.2f})")
                res[f"r{rank}_o{off}_wm_{nm}"] = dict(clean=a, contam=b, diff=fit["diff"])

        # -------- PRE / POST decomposition
        print("\n-- PRE vs POST decomposition (offset 0 is the speech minute) --")
        v0 = y[0][base].to_numpy()
        for off in (30, 240):
            v = y[off][base].to_numpy()
            pre = line(f"  PRE  [-60 -> 0]  (cannot be a response)", v0, sgn, clus)
            post = line(f"  POST [0 -> +{off}]", v - v0, sgn, clus)
            tot = line(f"  TOTAL[-60 -> +{off}] (the reported statistic)", v, sgn, clus)
            share = pre["mean"] / tot["mean"] * 100 if tot["mean"] else np.nan
            print(f"      -> the PRE-speech leg is {share:.0f}% of the reported composite")
            res[f"r{rank}_o{off}_prepost"] = dict(pre=pre, post=post, total=tot, pre_share_pct=float(share))

        # -------- LENGTH-MATCHED control window
        print("\n-- LENGTH-MATCHED same-day control window (300 min, ending at the baseline) --")
        ctrl = matched_pre_window(mb, bars)
        idx = ctrl.index
        pos = mb.index.get_indexer(idx)
        ev_v = y[240][base].to_numpy()[pos]
        ok = np.isfinite(ev_v)
        c_in = line("  EVENT window [-60,+240] (300 min)", ev_v[ok], sgn[pos][ok], clus[pos][ok])
        c_ct = line("  CONTROL window [-360,-60] (300 min, same day)",
                    ctrl.to_numpy()[ok], sgn[pos][ok], clus[pos][ok], "  <- no speech in it")
        d = (ev_v[ok] - ctrl.to_numpy()[ok])
        c_df = line("  EVENT minus CONTROL (paired)", d, sgn[pos][ok], clus[pos][ok])
        res[f"r{rank}_matched"] = dict(event=c_in, control=c_ct, diff=c_df)

        # -------- CHECK 2: clock and FOMC calendar
        print("\n-- CHECK 2: does the effect sit at particular clock times / FOMC distances? --")
        hh = mb["speech_ts"].dt.hour.to_numpy()
        buckets = [("pre-open / overnight (<08 ET)", hh < 8),
                   ("08-09 ET (data hour)", (hh >= 8) & (hh < 10)),
                   ("10-11 ET (10:00 release hour)", (hh >= 10) & (hh < 12)),
                   ("12-14 ET (auction hour)", (hh >= 12) & (hh < 15)),
                   ("15-17 ET (into the close)", (hh >= 15) & (hh < 18)),
                   ("evening (>=18 ET)", hh >= 18)]
        v = y[240][base].to_numpy()
        for nm, m in buckets:
            if m.sum() >= 15:
                line(f"  +240 | {nm}", v[m], sgn[m], clus[m])
            else:
                print(f"    +240 | {nm:<44s} n={int(m.sum())} -- too few, not reported")
        # window contains a specific clock minute
        for hhmm, nm in (("08:30", "08:30 print"), ("10:00", "10:00 print"), ("13:00", "13:00 auction stop")):
            hh_, mm_ = int(hhmm[:2]), int(hhmm[3:])
            t = mb["speech_ts"]
            mark = t.dt.normalize() + pd.Timedelta(hours=hh_, minutes=mm_)
            inwin = ((mark >= t - pd.Timedelta(minutes=60)) & (mark <= t + pd.Timedelta(minutes=240))).to_numpy()
            a = line(f"  +240 | window CONTAINS {nm}", v[inwin], sgn[inwin], clus[inwin])
            b = line(f"  +240 | window does NOT", v[~inwin], sgn[~inwin], clus[~inwin])
            res[f"r{rank}_clock_{hhmm}"] = dict(contains=a, not_contains=b)
        dtf = mb["days_to_fomc"].to_numpy()
        qs = np.quantile(dtf, [1 / 3, 2 / 3])
        for nm, m in (("days_to_fomc low  (<= %.0f)" % qs[0], dtf <= qs[0]),
                      ("days_to_fomc mid", (dtf > qs[0]) & (dtf <= qs[1])),
                      ("days_to_fomc high (> %.0f)" % qs[1], dtf > qs[1])):
            line(f"  +240 | {nm}", v[m], sgn[m], clus[m])
        # slope on days_to_fomc
        X = np.column_stack([np.ones(len(v)), (dtf - dtf.mean())])
        fit = cluster_ols(v * sgn, X, clus, names=["const", "per_day_to_fomc"])
        print(f"      -> signed composite slope on days_to_fomc = "
              f"{fit['per_day_to_fomc']['coef']:+.5f} bp/day (t={fit['per_day_to_fomc']['t']:+.2f})")

        # -------- CHECK 4: regime
        print("\n-- CHECK 4: regime / year split --")
        yr = mb["speech_ts"].dt.year.to_numpy()
        for off in (30, 240):
            vv = y[off][base].to_numpy()
            print(f"   +{off} min")
            for Y in sorted(set(yr)):
                m = yr == Y
                r = line(f"    {Y}", vv[m], sgn[m], clus[m],
                         f" h/d={int((sgn[m] == 1).sum())}/{int((sgn[m] == -1).sum())}")
                res[f"r{rank}_o{off}_year{Y}"] = r
            h1 = mb["speech_ts"] < pd.Timestamp("2025-01-01", tz="America/New_York")
            h1 = h1.to_numpy()
            line("    2023-24 (first half of the signed sample)", vv[h1], sgn[h1], clus[h1])
            line("    2025-26 (second half)", vv[~h1], sgn[~h1], clus[~h1])

    with open(HERE / "k3_calendar_regime.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
