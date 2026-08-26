"""Final: the POST-SPEECH-ONLY leg under every control, and a placebo falsification.

Two things left to settle.

(1) Every statistic in the findings is measured from the -60 baseline, so it
    contains 60 minutes that precede the speech.  k3 showed that leg is 58-61%
    of the +30 composite.  Strip it: y = d_rate(+off) - d_rate(0), which starts
    at the speech minute and can only contain a response.  Then apply the
    release-clean filter and the month / day fixed effects on top.

(2) PLACEBO FALSIFICATION.  The placebo book has no speech in it at all -- the
    stance label is inherited from the parent event.  If the release-contaminated
    placebo windows ALSO show a positive signed composite, the contamination
    effect has nothing to do with Fedspeak, which is the whole point.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(str(HERE))

from c_common import cluster_mean_se, cluster_ols  # noqa: E402
from k1_release_window import load_calendar, flag_windows  # noqa: E402
from k2_trend_confound import fe_slope  # noqa: E402

pd.set_option("display.width", 250)


def show(tag, v, sgn, clus):
    r = cluster_mean_se(np.asarray(v) * np.asarray(sgn), clus)
    print(f"    {tag:<52s} n={r['n']:>4d} days={r['n_clusters']:>4d}  "
          f"mean={r['mean']:+.4f} bp  t={r['t']:+.2f}")
    return r


def main():
    cal_all, rel = load_calendar()
    CAL_END = cal_all["release_ts_ny"].max()
    rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]
    res = {}

    # ================================================================== (1)
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    for rank in (1, 3):
        e = ev[ev["contract_rank"] == rank]
        meta = e.drop_duplicates("event_id").set_index("event_id").copy()
        meta["month"] = meta["speech_ts"].dt.strftime("%Y-%m")
        y = {o: e[e["offset_min"] == o].set_index("event_id")["d_rate_bp_from_baseline"]
             .reindex(meta.index) for o in (0, 5, 15, 30, 60, 240)}
        base = ((meta["stance_sign"] != 0) & (meta["speech_ts"] <= CAL_END)).to_numpy()
        mb = meta[base]
        sgn = mb["stance_sign"].to_numpy().astype(float)
        clus = mb["date"].to_numpy()
        v0 = y[0][base].to_numpy()
        print("\n" + "=" * 100)
        print(f"RANK {rank}  --  POST-SPEECH-ONLY leg  y = d_rate(+off) - d_rate(0)")
        print("=" * 100)
        for off in (5, 15, 30, 60, 240):
            post = y[off][base].to_numpy() - v0
            f, _ = flag_windows(mb, rel_hm, 0, off)      # release AFTER the speech only
            clean = ~f
            print(f"\n  [0 -> +{off}]   ({f.mean():.1%} of windows contain a high/med release)")
            a = show("    raw", post, sgn, clus)
            b = show("    release-clean", post[clean], sgn[clean], clus[clean])
            c = fe_slope(post[clean], sgn[clean], mb["month"].to_numpy()[clean], clus[clean],
                         "    release-clean + MONTH FE")
            d = fe_slope(post[clean], sgn[clean], mb["date"].to_numpy()[clean], clus[clean],
                         "    release-clean + DAY FE")
            res[f"post_r{rank}_{off}"] = dict(raw=a, clean=b, month=c, day=d)

    # ================================================================== (2)
    print("\n" + "=" * 100)
    print("PLACEBO FALSIFICATION -- same release split on pseudo-events with NO speech")
    print("=" * 100)
    pl = pd.read_parquet(HERE / "placebo_paths.parquet")
    for rank in (1, 3):
        p = pl[pl["contract_rank"] == rank]
        pm = p.drop_duplicates("event_id").set_index("event_id").copy()
        py = {o: p[p["offset_min"] == o].set_index("event_id")["d_rate_bp_from_baseline"]
              .reindex(pm.index) for o in (30, 240)}
        base = ((pm["stance_sign"] != 0) & (pm["speech_ts"] <= CAL_END)).to_numpy()
        pb = pm[base]
        sgn = pb["stance_sign"].to_numpy().astype(float)
        clus = pb["date"].to_numpy()
        print(f"\n  RANK {rank}  placebo, signed, calendar-covered: n={len(pb)}, "
              f"{pb['date'].nunique()} days")
        for off in (240, 30):
            v = py[off][base].to_numpy()
            f, _ = flag_windows(pb, rel_hm, -60, off)
            print(f"   +{off} min  ({f.mean():.1%} contaminated)")
            a = show("     full placebo book", v, sgn, clus)
            b = show("     placebo, release-CLEAN", v[~f], sgn[~f], clus[~f])
            c = show("     placebo, release-CONTAMINATED", v[f], sgn[f], clus[f])
            X = np.column_stack([np.ones(len(v)), f.astype(float)])
            fit = cluster_ols(v * sgn, X, clus, names=["clean", "diff"])
            print(f"       -> contam - clean = {fit['diff']['coef']:+.4f} bp (t={fit['diff']['t']:+.2f})"
                  "   <- NO SPEECH IS INVOLVED IN ANY OF THESE")
            res[f"placebo_r{rank}_{off}"] = dict(full=a, clean=b, contam=c, diff=fit["diff"])

    # ================================================================== (3)
    print("\n" + "=" * 100)
    print("days_to_fomc gradient, conditional on release-clean (rank 3, +240)")
    print("=" * 100)
    e = ev[ev["contract_rank"] == 3]
    meta = e.drop_duplicates("event_id").set_index("event_id").copy()
    yv = e[e["offset_min"] == 240].set_index("event_id")["d_rate_bp_from_baseline"].reindex(meta.index)
    base = ((meta["stance_sign"] != 0) & (meta["speech_ts"] <= CAL_END)).to_numpy()
    mb = meta[base]
    sgn = mb["stance_sign"].to_numpy().astype(float)
    clus = mb["date"].to_numpy()
    v = yv[base].to_numpy()
    f, _ = flag_windows(mb, rel_hm, -60, 240)
    dtf = mb["days_to_fomc"].to_numpy()
    qs = np.quantile(dtf, [1 / 3, 2 / 3])
    for nm, m in ((f"<= {qs[0]:.0f} d to FOMC", dtf <= qs[0]),
                  ("mid", (dtf > qs[0]) & (dtf <= qs[1])),
                  (f"> {qs[1]:.0f} d to FOMC", dtf > qs[1])):
        show(f"  ALL         {nm}", v[m], sgn[m], clus[m])
        show(f"  CLEAN only  {nm}", v[m & ~f], sgn[m & ~f], clus[m & ~f])
    print(f"  release contamination rate by tercile: "
          f"{f[dtf <= qs[0]].mean():.0%} / {f[(dtf > qs[0]) & (dtf <= qs[1])].mean():.0%} / "
          f"{f[dtf > qs[1]].mean():.0%}")

    with open(HERE / "k5_postonly_and_placebo.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
