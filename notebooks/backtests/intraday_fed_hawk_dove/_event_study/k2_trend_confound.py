"""CHECK 3 -- is 'hawk -> rate up' a SPEECH RESPONSE or a TREND?

The stance label is not randomly assigned.  Hawkish officials speak more when
the committee is hiking and the front end is selling off anyway; dovish ones
speak more when it is cutting.  Under that confound the signed composite is
positive for BOTH arms with no speech channel at all, because each arm's label
lines up with the direction its own months happened to move.

Three tests, ordered by how much of the confound they remove:

  (1) MONTH FIXED EFFECTS.  y ~ const + stance_sign + month dummies.  With
      stance_sign in {-1,+1}, the OLS slope on stance_sign IS the arm-balanced
      signed composite ((mean_hawk - mean_dove)/2), so the uncontrolled and
      controlled numbers are directly comparable.  Adding month FE identifies
      only from hawk-vs-dove differences WITHIN the same month.

  (2) DAY FIXED EFFECTS.  The same thing within a single calendar day -- the
      strictest control available, identified only off days carrying both a
      hawk-labelled and a dove-labelled speech.

  (3) OUTSIDE-WINDOW FALSIFICATION.  The same-day move that is NOT in the event
      window (day total minus window), from the 1-minute bar cache.  A speech
      cannot move the part of the day it is not in.  If stance_sign 'predicts'
      the outside-window move too, the signed composite is measuring the cycle.

Every restriction is counted and printed.
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

pd.set_option("display.width", 250)
BARS = HERE / "bars_event_study.pkl"


# ------------------------------------------------------------------ helpers
def fe_slope(y, sign, groups, clusters, label):
    """OLS slope on stance_sign with `groups` absorbed as dummies, day-clustered."""
    ok = np.isfinite(y) & np.isfinite(sign)
    y, sign, groups, clusters = y[ok], sign[ok], np.asarray(groups)[ok], np.asarray(clusters)[ok]
    if groups is None or len(np.unique(groups)) <= 1:
        X = np.column_stack([np.ones(len(y)), sign])
        names = ["const", "stance_sign"]
    else:
        d = pd.get_dummies(pd.Series(groups), drop_first=True).to_numpy(dtype=float)
        X = np.column_stack([np.ones(len(y)), sign, d])
        names = ["const", "stance_sign"] + [f"g{i}" for i in range(d.shape[1])]
    fit = cluster_ols(y, X, clusters, names=names)
    b = fit["stance_sign"]
    print(f"    {label:<50s} b={b['coef']:+.4f} bp  se={b['se']:.4f}  t={b['t']:+.2f}   "
          f"n={fit['n']}  clusters={fit['n_clusters']}")
    return dict(label=label, coef=b["coef"], se=b["se"], t=b["t"], n=fit["n"], n_clusters=fit["n_clusters"])


def identifying_groups(groups, sign):
    """How many FE groups actually carry both arms (the ones that identify b)."""
    df = pd.DataFrame({"g": groups, "s": sign})
    n = df.groupby("g")["s"].nunique()
    return int((n > 1).sum()), int(len(n))


def selftest():
    """A checking tool that is itself wrong hides the thing it was built to find.

    Build a panel with ZERO speech effect and a pure month trend that the stance
    label tracks.  The uncontrolled slope must be large and the month-FE slope
    must be ~0.  Then mutate: inject a real within-month effect and confirm the
    month-FE slope recovers it.
    """
    print("SELF-TEST of the FE estimator")
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("  OK   " if c else "  FAIL ") + m)
        ok = ok and bool(c)

    rng = np.random.default_rng(11)
    n = 1200
    month = rng.integers(0, 30, size=n)
    trend = rng.normal(0, 3.0, size=30)            # each month has its own drift
    # stance is ASSIGNED BY THE TREND: hawks speak in selling-off months
    p_hawk = 1.0 / (1.0 + np.exp(-trend[month]))
    sign = np.where(rng.random(n) < p_hawk, 1.0, -1.0)
    y_pure_trend = trend[month] + rng.normal(0, 1.0, size=n)   # no speech effect at all
    day = month * 100 + rng.integers(0, 8, size=n)

    a = fe_slope(y_pure_trend, sign, np.zeros(n), day, "confounded panel, NO controls")
    b = fe_slope(y_pure_trend, sign, month, day, "confounded panel, MONTH FE")
    chk(a["t"] > 4, f"uncontrolled slope is spuriously large (b={a['coef']:+.3f}, t={a['t']:+.1f})")
    chk(abs(b["coef"]) < 0.25 and abs(b["t"]) < 2.5,
        f"month FE removes the spurious slope (b={b['coef']:+.3f}, t={b['t']:+.1f})")

    y_real = y_pure_trend + 0.8 * sign          # inject a genuine within-month effect
    c = fe_slope(y_real, sign, month, day, "MUTATION: +0.8 bp real effect injected, MONTH FE")
    chk(abs(c["coef"] - 0.8) < 0.15 and c["t"] > 5,
        f"month FE RECOVERS an injected +0.80 bp effect (b={c['coef']:+.3f}, t={c['t']:+.1f}) "
        f"-- the control is not simply eating everything")
    print("  SELFTEST:", "PASS" if ok else "FAIL")
    return ok


# ------------------------------------------------------------------ load
def load(rank):
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    ev = ev[ev["contract_rank"] == rank]
    meta = ev.drop_duplicates("event_id").set_index("event_id").copy()
    y = {}
    for o in (30, 240):
        y[o] = ev[ev["offset_min"] == o].set_index("event_id")["d_rate_bp_from_baseline"].reindex(meta.index)
    meta["month"] = meta["speech_ts"].dt.strftime("%Y-%m")
    return meta, y


def outside_window(meta, y240, bars):
    """Same-day move that is NOT inside [speech-60, speech+240], in rate bp.

    day_move_bp = (first_close - last_close) * 100     [price down = rate up]
    outside     = day_move_bp - window_move_bp
    Restricted to events whose whole [-60,+240] interval sits inside one NY
    calendar day and whose day frame has >= 2 distinct closes (the repo's
    synthetic-flat-day guard).
    """
    keep, out_bp, day_bp = [], [], []
    n_no_frame = n_crosses_day = n_flat = n_no_window = n_short = 0
    for eid, row in meta.iterrows():
        w = y240.get(eid, np.nan)
        if not np.isfinite(w):
            n_no_window += 1
            continue
        t = row["speech_ts"]
        lo, hi = t - pd.Timedelta(minutes=60), t + pd.Timedelta(minutes=240)
        if lo.date() != t.date() or hi.date() != t.date():
            n_crosses_day += 1
            continue
        key = (row["symbol"], t.date())
        b = bars.get(key)
        if b is None or len(b) < 2:
            n_no_frame += 1
            continue
        if b["Close"].nunique() < 2:
            n_flat += 1
            continue
        # the day frame must actually bracket the window, else 'outside' is empty
        if b.index[0] > lo or b.index[-1] < hi:
            n_short += 1
            continue
        d_bp = (float(b["Close"].iloc[0]) - float(b["Close"].iloc[-1])) * 100.0
        keep.append(eid)
        day_bp.append(d_bp)
        out_bp.append(d_bp - float(w))
    print(f"    outside-window sample: kept {len(keep)}  |  dropped: no +240 price {n_no_window}, "
          f"window crosses midnight {n_crosses_day}, no bar frame {n_no_frame}, "
          f"flat/synthetic day {n_flat}, day frame does not bracket the window {n_short}")
    return pd.Series(out_bp, index=keep), pd.Series(day_bp, index=keep)


def main():
    print("=" * 100)
    print("CHECK 3 -- TREND / CYCLE CONFOUND")
    print("=" * 100)
    if not selftest():
        print("STOPPING: estimator self-test failed")
        return 1

    print("\nloading 1-minute bar cache ...")
    bars = pickle.load(open(BARS, "rb"))
    print(f"  {len(bars)} (symbol, date) frames")

    results = {}
    for rank in (1, 3):
        meta, y = load(rank)
        print("\n" + "=" * 100)
        print(f"RANK {rank}")
        print("=" * 100)

        sg = meta["stance_sign"] != 0
        books = {
            "ALL SIGNED": sg.to_numpy(),
            "NON-OVERLAPPING SIGNED (headline)": (sg & ~meta["is_overlapping"]).to_numpy(),
        }

        # ---- how big is the confound?  measure it, do not assume its sign.
        m = meta[sg]
        mm = m.groupby("month").apply(
            lambda d: pd.Series(dict(mean_y=y[240].loc[d.index].mean(),
                                     hawk_share=(d["stance_sign"] == 1).mean(),
                                     n=len(d))), include_groups=False)
        mm = mm.dropna()
        r = np.corrcoef(mm["hawk_share"], mm["mean_y"])[0, 1]
        print(f"\n  CONFOUND SIZE: across {len(mm)} months, corr(hawk share of speeches, "
              f"that month's mean +240 rate move) = {r:+.3f}")
        ev_r = np.corrcoef(m["stance_sign"].to_numpy(),
                           mm["mean_y"].reindex(m["month"]).to_numpy())[0, 1]
        print(f"                 event-level corr(stance_sign, own-month mean move) = {ev_r:+.3f}")
        results[f"r{rank}_confound_corr_month"] = float(r)
        results[f"r{rank}_confound_corr_event"] = float(ev_r)

        for off in (240, 30):
            print(f"\n  --- y = d_rate at +{off} min (bp from the -60 baseline) ---")
            for bname, bmask in books.items():
                mb = meta[bmask]
                yy = y[off][bmask].to_numpy()
                sgn = mb["stance_sign"].to_numpy().astype(float)
                clus = mb["date"].to_numpy()
                nm, tm = identifying_groups(mb["month"].to_numpy(), sgn)
                nd, td = identifying_groups(mb["date"].to_numpy(), sgn)
                print(f"   {bname}  (months carrying both arms: {nm}/{tm}; "
                      f"days carrying both arms: {nd}/{td})")
                a = fe_slope(yy, sgn, np.zeros(len(yy)), clus, "no controls (= arm-balanced composite)")
                b = fe_slope(yy, sgn, mb["month"].to_numpy(), clus, "+ MONTH fixed effects")
                c = fe_slope(yy, sgn, mb["date"].to_numpy(), clus, "+ DAY fixed effects")
                yr = mb["speech_ts"].dt.year.astype(str).to_numpy()
                d = fe_slope(yy, sgn, yr, clus, "+ YEAR fixed effects")
                results[f"r{rank}_o{off}_{bname}"] = dict(none=a, month=b, day=c, year=d,
                                                          id_months=nm, id_days=nd)

        # ---- outside-window falsification (rank-level, +240 window)
        print(f"\n  --- OUTSIDE-WINDOW FALSIFICATION (rank {rank}) ---")
        for bname, bmask in books.items():
            mb = meta[bmask]
            outs, days = outside_window(mb, y[240][bmask], bars)
            if len(outs) < 20:
                print(f"    {bname}: only {len(outs)} usable events -- not reported")
                continue
            sub = mb.loc[outs.index]
            sgn = sub["stance_sign"].to_numpy().astype(float)
            clus = sub["date"].to_numpy()
            r_in = cluster_mean_se(y[240].loc[outs.index].to_numpy() * sgn, clus)
            r_out = cluster_mean_se(outs.to_numpy() * sgn, clus)
            r_day = cluster_mean_se(days.to_numpy() * sgn, clus)
            print(f"    {bname}  (n={r_in['n']}, days={r_in['n_clusters']})")
            print(f"      signed move INSIDE  the window [-60,+240] : {r_in['mean']:+.4f} bp  t={r_in['t']:+.2f}")
            print(f"      signed move OUTSIDE the window, same day  : {r_out['mean']:+.4f} bp  t={r_out['t']:+.2f}"
                  "   <- a speech cannot cause this")
            print(f"      signed move over the WHOLE day            : {r_day['mean']:+.4f} bp  t={r_day['t']:+.2f}")
            # net of the day's own drift, pro-rated by time
            results[f"r{rank}_outside_{bname}"] = dict(inside=r_in, outside=r_out, whole_day=r_day)

    with open(HERE / "k2_trend_confound.json", "w") as fh:
        json.dump(results, fh, indent=1, default=float)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
