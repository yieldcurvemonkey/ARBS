"""CHECK 1 -- what ELSE is in the window.

The panel carries is_cpi_day / is_nfp_day, which are DAY flags.  A speech at
10:00 ET measured from a -60 baseline to +240 spans 09:00 -> 14:00 and swallows
the 10:00 ISM/UoM/JOLTS print, the 13:00 auction stop, and on a Thursday the
08:30 claims sit just outside.  A day flag cannot tell those apart.

This script rebuilds the release flag at WINDOW resolution from the timestamped
USD ForexFactory calendar already cached in the repo
(notebooks/backtests/econ_release_fade/_cache/events_raw.pkl, 2,870 release
minutes 2019-01 -> 2026-08-07) and re-estimates the headline signed composite on
the clean subset and, separately, on the contaminated subset.

Sample-kill is not effect-kill: the discriminating statistic is whether the
effect CONCENTRATES in the contaminated windows, not merely whether the clean
subset loses significance from a smaller n.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

if __name__ == "__main__":
    # only when run directly -- re-wrapping on import would close the caller's
    # own wrapper around the same buffer.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import pickle

sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
sys.path.append(str(HERE))

from c_common import cluster_mean_se, cluster_ols  # noqa: E402

CAL = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\econ_release_fade\_cache\events_raw.pkl")

pd.set_option("display.width", 250)


# ---------------------------------------------------------------- calendar
def load_calendar():
    df = pickle.load(open(CAL, "rb"))
    assert set(["release_ts_ny", "any_release", "impact", "lead_title"]).issubset(df.columns)
    df = df[df["currency"] == "USD"].copy()
    rel = df[df["any_release"]].copy()          # drops CB-speech-only minutes
    rel["ts"] = rel["release_ts_ny"]
    return df, rel


def selftest_calendar(rel):
    """Known-answer: the calendar must place CPI and NFP where they belong."""
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("  OK   " if c else "  FAIL ") + m)
        ok = ok and bool(c)

    cpi = rel[rel["titles"].apply(lambda t: any("CPI" in x for x in t))]
    chk(len(cpi) > 30, f"CPI minutes found: {len(cpi)}")
    chk((cpi["ts"].dt.strftime("%H:%M") == "08:30").mean() > 0.95,
        f"CPI lands 08:30 ET on {(cpi['ts'].dt.strftime('%H:%M') == '08:30').mean():.1%} of minutes")
    ism = rel[rel["lead_title"].str.contains("ISM", na=False)]
    chk((ism["ts"].dt.strftime("%H:%M") == "10:00").mean() > 0.95,
        f"ISM lands 10:00 ET on {(ism['ts'].dt.strftime('%H:%M') == '10:00').mean():.1%} of minutes")
    # mutation: a 5-minute window around a random NON-release minute must be clean
    return ok


def _utc64(s):
    """tz-aware Series -> numpy datetime64[ns] on a single UTC clock.

    .to_numpy() on a tz-aware Series returns dtype=object, which will not take a
    timedelta64.  Converting to UTC first makes every comparison unambiguous
    across the DST boundary as well.
    """
    return pd.to_datetime(pd.Series(s).dt.tz_convert("UTC").dt.tz_localize(None)).to_numpy()


def flag_windows(events, rel_ts, lo_min, hi_min):
    """True if ANY release minute lies in [speech + lo, speech + hi] (inclusive)."""
    t = _utc64(events["speech_ts"])
    lo = t + np.timedelta64(lo_min, "m")
    hi = t + np.timedelta64(hi_min, "m")
    r = np.sort(_utc64(rel_ts))
    i_lo = np.searchsorted(r, lo, side="left")
    i_hi = np.searchsorted(r, hi, side="right")
    return (i_hi - i_lo) > 0, (i_hi - i_lo)


def selftest_flagger(rel):
    """Pin flag_windows against a hand-built case, then mutate it."""
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("  OK   " if c else "  FAIL ") + m)
        ok = ok and bool(c)

    ts = pd.Series(pd.to_datetime([
        "2024-01-10 09:00", "2024-01-10 12:00", "2024-01-10 20:00"
    ]).tz_localize("America/New_York"))
    ev = pd.DataFrame({"speech_ts": pd.to_datetime([
        "2024-01-10 10:00",   # -60 -> 09:00 catches the 09:00; +240 -> 14:00 catches 12:00
        "2024-01-10 16:00",   # 15:00 -> 20:00 catches the 20:00
        "2024-01-10 03:00",   # 02:00 -> 07:00 catches nothing
    ]).tz_localize("America/New_York")})
    f, n = flag_windows(ev, ts, -60, 240)
    chk(list(f) == [True, True, False], f"hand case [-60,+240] -> {list(f)} (want [T,T,F])")
    chk(list(n) == [2, 1, 0], f"hand case counts -> {list(n)} (want [2,1,0])")
    # boundary: exactly at the edge counts (inclusive)
    ev2 = pd.DataFrame({"speech_ts": pd.to_datetime(["2024-01-10 10:00"]).tz_localize("America/New_York")})
    f2, _ = flag_windows(ev2, ts, -60, -60)
    chk(bool(f2[0]), "inclusive boundary: a release exactly at the baseline minute is flagged")
    f3, _ = flag_windows(ev2, ts, -59, -1)
    chk(not bool(f3[0]), "mutation: shifting the window off the release minute clears the flag")
    return ok


# ---------------------------------------------------------------- panel
def load_panel(rank):
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    ev = ev[ev["contract_rank"] == rank]
    meta = ev.drop_duplicates("event_id").set_index("event_id")
    vals = {}
    for o in (0, 5, 30, 60, 240, 300):
        s = ev[ev["offset_min"] == o].set_index("event_id")["d_rate_bp_from_baseline"]
        vals[o] = s.reindex(meta.index)
    return meta, vals


def report(tag, meta, y, mask):
    sub = meta[mask]
    yy = y[mask]
    sgn = sub["stance_sign"].to_numpy()
    r = cluster_mean_se(yy.to_numpy() * sgn, sub["date"].to_numpy())
    nh = int((sub["stance_sign"] == 1).sum())
    nd = int((sub["stance_sign"] == -1).sum())
    print(f"  {tag:<44s} n={r['n']:>4d} days={r['n_clusters']:>4d} "
          f"h/d={nh:>3d}/{nd:>3d}  mean={r['mean']:+.4f} bp  se={r['se']:.4f}  t={r['t']:+.2f}")
    return dict(tag=tag, n_hawk=nh, n_dove=nd, **{k: (float(v) if isinstance(v, float) else v) for k, v in r.items()})


def main():
    print("=" * 100)
    print("CHECK 1 -- WINDOW-LEVEL MACRO RELEASE CONTAMINATION")
    print("=" * 100)

    cal_all, rel = load_calendar()
    print(f"\ncalendar: {len(cal_all)} USD minutes {cal_all['release_ts_ny'].min()} -> "
          f"{cal_all['release_ts_ny'].max()}")
    print(f"          {len(rel)} carry an actual DATA release (any_release=True); "
          f"{len(cal_all) - len(rel)} are CB-speech / other minutes")
    CAL_END = cal_all["release_ts_ny"].max()

    print("\nCALENDAR SELF-TEST")
    ok1 = selftest_calendar(rel)
    print("\nFLAGGER SELF-TEST")
    ok2 = selftest_flagger(rel["ts"])
    if not (ok1 and ok2):
        print("SELFTEST FAILED -- stopping")
        return 1

    rel_high = rel[rel["impact"] == "high"]["ts"]
    rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]
    print(f"\nrelease minutes: high={len(rel_high)}  high+medium={len(rel_hm)}")

    out = {}
    for rank in (1, 3):
        meta, vals = load_panel(rank)
        print("\n" + "=" * 100)
        print(f"RANK {rank}")
        print("=" * 100)

        signed = meta["stance_sign"] != 0
        # calendar coverage: events after the calendar's last minute cannot be
        # judged and are EXCLUDED from both arms rather than defaulting to clean.
        covered = meta["speech_ts"] <= CAL_END
        n_uncov = int((signed & ~covered).sum())
        print(f"signed events: {int(signed.sum())};  outside calendar coverage "
              f"(speech after {CAL_END}): {n_uncov} -> EXCLUDED from both arms")

        for lo, hi, wname in ((-60, 240, "[-60,+240] measurement interval"),
                              (-120, 300, "[-120,+300] full panel window"),
                              (0, 240, "[0,+240] post-speech only")):
            for rts, iname in ((rel_high, "high"), (rel_hm, "high+medium")):
                f, cnt = flag_windows(meta, rts, lo, hi)
                meta[f"contam_{lo}_{hi}_{iname}"] = f
                if wname.startswith("[-60"):
                    print(f"  {wname} x {iname:<12s}: contaminated "
                          f"{int(f[signed.to_numpy() & covered.to_numpy()].sum())}/"
                          f"{int((signed & covered).sum())} signed "
                          f"({f[signed.to_numpy() & covered.to_numpy()].mean():.1%})")

        base_all = (signed & covered).to_numpy()
        base_no = (signed & covered & ~meta["is_overlapping"]).to_numpy()

        for offset in (240, 30):
            y = vals[240] if offset == 240 else vals[30]
            print(f"\n-- signed composite at +{offset} min, rank {rank} --")
            for bname, bmask in (("ALL SIGNED", base_all), ("NON-OVERLAPPING SIGNED (headline)", base_no)):
                print(f" {bname}")
                report("  full book", meta, y, bmask)
                for key, label in (
                    ("contam_-60_240_high", "high-impact in [-60,+240]"),
                    ("contam_-60_240_high+medium", "high+med in [-60,+240]"),
                    ("contam_-120_300_high", "high-impact in [-120,+300]"),
                ):
                    c = meta[key].to_numpy()
                    a = report(f"  CLEAN   ({label})", meta, y, bmask & ~c)
                    b = report(f"  CONTAM  ({label})", meta, y, bmask & c)
                    out[f"r{rank}_o{offset}_{bname}_{key}"] = dict(clean=a, contam=b)
                    # difference of the two means, day-clustered, via OLS on the indicator
                    sub = meta[bmask]
                    yy = y[bmask].to_numpy() * sub["stance_sign"].to_numpy()
                    d = sub[key].to_numpy().astype(float)
                    X = np.column_stack([np.ones(len(d)), d])
                    fit = cluster_ols(yy, X, sub["date"].to_numpy(), names=["clean_mean", "contam_minus_clean"])
                    print(f"    -> contam - clean = {fit['contam_minus_clean']['coef']:+.4f} bp "
                          f"(t={fit['contam_minus_clean']['t']:+.2f})")
                    out[f"r{rank}_o{offset}_{bname}_{key}_diff"] = fit["contam_minus_clean"]

        # which releases are doing the swallowing
        if rank == 3:
            print("\n-- what is actually in the contaminated windows (all-signed, high+med, [-60,+240]) --")
            rows = []
            rr = rel[rel["impact"].isin(["high", "medium"])]
            rts = _utc64(rr["ts"])
            order = np.argsort(rts)
            rts_s, rr_s = rts[order], rr.iloc[order]
            t = _utc64(meta.loc[base_all, "speech_ts"])
            lo = t + np.timedelta64(-60, "m")
            hi = t + np.timedelta64(240, "m")
            i_lo = np.searchsorted(rts_s, lo, "left")
            i_hi = np.searchsorted(rts_s, hi, "right")
            for a, b in zip(i_lo, i_hi):
                for j in range(a, b):
                    rows.append(rr_s.iloc[j]["lead_title"])
            print(pd.Series(rows).value_counts().head(20).to_string())

    print("\nDONE")
    import json
    with open(HERE / "k1_release_window.json", "w") as fh:
        json.dump({k: v for k, v in out.items()}, fh, indent=1, default=float)
    return 0


if __name__ == "__main__":
    sys.exit(main())
