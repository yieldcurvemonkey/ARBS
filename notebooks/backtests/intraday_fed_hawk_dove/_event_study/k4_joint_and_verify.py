"""Joint specification + independent recompute.

k1/k2/k3 each removed one confound.  This asks whether anything survives them
TOGETHER, and then recomputes the load-bearing numbers by a second, independent
route so the verdict does not rest on one code path.

Specifications, rank 1 and rank 3, y = d_rate from the -60 baseline:
  A  raw arm-balanced composite                (= the number the findings quote)
  B  release-clean windows only
  C  release-clean + month fixed effects
  D  release-clean + day fixed effects
  E  release-clean, paired against the length-matched no-speech control window
     on the same day  ([-360,-60] vs [-60,+240], both 300 minutes)
  F  the 08-09 ET bucket split clean/contaminated -- separates 'the effect is at
     a particular clock time' from 'the effect is a data release'
"""
from __future__ import annotations

import io
import json
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(str(HERE))

from c_common import cluster_mean_se, cluster_ols  # noqa: E402
from k1_release_window import load_calendar, flag_windows  # noqa: E402
from k2_trend_confound import fe_slope  # noqa: E402
from k3_calendar_regime import matched_pre_window, load  # noqa: E402

pd.set_option("display.width", 250)


def show(tag, v, sgn, clus, extra=""):
    r = cluster_mean_se(np.asarray(v) * np.asarray(sgn), clus)
    print(f"    {tag:<52s} n={r['n']:>4d} days={r['n_clusters']:>4d}  "
          f"mean={r['mean']:+.4f} bp  t={r['t']:+.2f} {extra}")
    return r


def main():
    cal_all, rel = load_calendar()
    CAL_END = cal_all["release_ts_ny"].max()
    rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]
    rel_h = rel[rel["impact"] == "high"]["ts"]
    bars = pickle.load(open(HERE / "bars_event_study.pkl", "rb"))

    res = {}
    for rank in (1, 3):
        meta, y = load(rank)
        base = ((meta["stance_sign"] != 0) & (meta["speech_ts"] <= CAL_END)).to_numpy()
        mb = meta[base]
        sgn = mb["stance_sign"].to_numpy().astype(float)
        clus = mb["date"].to_numpy()
        print("\n" + "=" * 100)
        print(f"RANK {rank}  --  JOINT SPECIFICATION (all-signed, calendar-covered: "
              f"n={len(mb)}, {mb['date'].nunique()} days)")
        print("=" * 100)

        ctrl = matched_pre_window(mb, bars)

        for off in (240, 30):
            v = y[off][base].to_numpy()
            f_hm, _ = flag_windows(mb, rel_hm, -60, off)
            f_h, _ = flag_windows(mb, rel_h, -60, off)
            clean = ~f_hm
            print(f"\n  y = d_rate at +{off} min")
            A = show("A  raw arm-balanced composite", v, sgn, clus)
            B = show("B  release-clean (no high/med release in window)", v[clean], sgn[clean], clus[clean])
            C = fe_slope(v[clean] * 1.0, sgn[clean], mb["month"].to_numpy()[clean] if "month" in mb
                         else mb["speech_ts"].dt.strftime("%Y-%m").to_numpy()[clean],
                         clus[clean], "C  release-clean + MONTH fixed effects")
            D = fe_slope(v[clean] * 1.0, sgn[clean], mb["date"].to_numpy()[clean], clus[clean],
                         "D  release-clean + DAY fixed effects")
            res[f"r{rank}_o{off}"] = dict(A=A, B=B, C=C, D=D)

            if off == 240:
                pos = mb.index.get_indexer(ctrl.index)
                have = np.zeros(len(mb), bool)
                have[pos] = True
                cv = np.full(len(mb), np.nan)
                cv[pos] = ctrl.to_numpy()
                m = clean & have & np.isfinite(v) & np.isfinite(cv)
                print(f"    E  release-clean, paired vs the same-day control window "
                      f"([-360,-60], 300 min, no speech)")
                e1 = show("     event window   [-60,+240]", v[m], sgn[m], clus[m])
                e2 = show("     control window [-360,-60]", cv[m], sgn[m], clus[m])
                e3 = show("     EVENT minus CONTROL (paired)", v[m] - cv[m], sgn[m], clus[m])
                res[f"r{rank}_o{off}_E"] = dict(event=e1, control=e2, diff=e3)

                hh = mb["speech_ts"].dt.hour.to_numpy()
                b89 = (hh >= 8) & (hh < 10)
                print("    F  the 08-09 ET bucket -- clock artefact or data artefact?")
                f1 = show("     08-09 ET, all", v[b89], sgn[b89], clus[b89])
                f2 = show("     08-09 ET, release-CLEAN", v[b89 & clean], sgn[b89 & clean], clus[b89 & clean])
                f3 = show("     08-09 ET, release-CONTAMINATED", v[b89 & ~clean], sgn[b89 & ~clean],
                          clus[b89 & ~clean])
                f4 = show("     NOT 08-09 ET, release-CONTAMINATED", v[~b89 & ~clean], sgn[~b89 & ~clean],
                          clus[~b89 & ~clean])
                res[f"r{rank}_F"] = dict(all=f1, clean=f2, contam=f3, other_contam=f4)
                print(f"       (08-09 ET is {clean[b89].mean():.0%} clean vs "
                      f"{clean[~b89].mean():.0%} elsewhere -- the bucket IS the contamination)")

    # ------------------------------------------------------------------
    # INDEPENDENT RECOMPUTE of the load-bearing numbers, long-panel route,
    # unclustered iid t as a second opinion on magnitude (not on inference).
    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("INDEPENDENT RECOMPUTE (long panel, no pivot, no helper module)")
    print("=" * 100)
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    cal = pickle.load(open(Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\econ_release_fade"
                                r"\_cache\events_raw.pkl"), "rb"))
    cal = cal[(cal["currency"] == "USD") & cal["any_release"] &
              cal["impact"].isin(["high", "medium"])]
    rts = cal["release_ts_ny"].sort_values().reset_index(drop=True)

    for rank in (1, 3):
        d = ev[(ev["contract_rank"] == rank) & (ev["offset_min"] == 240) &
               (ev["stance_sign"] != 0) & (ev["speech_ts"] <= CAL_END)].copy()
        d = d[d["d_rate_bp_from_baseline"].notna()]
        # brute-force contamination flag: a python loop, no searchsorted
        flags = []
        for t in d["speech_ts"]:
            lo, hi = t - pd.Timedelta(minutes=60), t + pd.Timedelta(minutes=240)
            flags.append(bool(((rts >= lo) & (rts <= hi)).any()))
        d["contam"] = flags
        d["sd"] = d["d_rate_bp_from_baseline"] * d["stance_sign"]
        # cross-check against the panel's own precomputed signed column
        agree = np.allclose(d["sd"], d["signed_d_bp"], equal_nan=True)
        print(f"\nrank {rank}: signed column reproduced from d_rate*sign: {agree}")
        for nm, s in (("full", d), ("clean", d[~d["contam"]]), ("contam", d[d["contam"]])):
            m = s["sd"].mean()
            se_iid = s["sd"].std(ddof=1) / np.sqrt(len(s))
            g = s.groupby("date")["sd"]
            cm = g.mean()
            se_day = cm.std(ddof=1) / np.sqrt(len(cm))
            print(f"  {nm:<7s} n={len(s):>4d} days={len(cm):>4d}  mean={m:+.4f} bp   "
                  f"iid t={m / se_iid:+.2f}   day-mean t={cm.mean() / se_day:+.2f} "
                  f"(day-mean mean {cm.mean():+.4f})")
            res[f"verify_r{rank}_{nm}"] = dict(n=len(s), mean=float(m), t_iid=float(m / se_iid),
                                               t_daymean=float(cm.mean() / se_day))

    with open(HERE / "k4_joint_and_verify.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
