"""SKEPTIC CHECK 3: is the CALENDAR STAMP itself at the right minute?

A sign-free, baseline-free test that does not depend on the panel at all: for
every event, take the raw minute bars of the rank-3 contract in [-60, +60] and
ask WHICH MINUTE carries the largest |dClose|. If the ForexFactory stamp is
accurate AND a speech moves the front end, that argmax must pile up at 0/+1. If
headlines cross early (prepared remarks released ahead of the slot) it piles up
BEFORE 0. If nothing happens, it is flat - and the placebo gives the flat
reference directly.

Also re-runs the per-offset means on the ALL-EVENTS and PLACEBO books to see
whether the -90/-45 wiggle in the headline book is a real pre-event feature or a
mechanical artefact of anchoring at -60.
"""
import sys, io, json, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np, pandas as pd
from pathlib import Path
import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OUT = {}
G.load_bar_cache(str(HERE / "bars_event_study.pkl"))
CACHE = G._BAR_CACHE


def argmax_hist(ev, label, W=60):
    """distribution of the argmax-|dClose| minute relative to the stamp"""
    rel, nrows = [], 0
    for _, r in ev.iterrows():
        ts = pd.Timestamp(r["speech_ts"])
        rows = []
        for k in (-1, 0, 1):
            b = CACHE.get((r["symbol"], (ts + pd.Timedelta(days=k)).date()))
            if b is not None and len(b) and b["Close"].nunique() >= 2:
                rows.append(b["Close"])
        if not rows:
            continue
        s = pd.concat(rows).sort_index()
        w = s[(s.index >= ts - pd.Timedelta(minutes=W)) & (s.index <= ts + pd.Timedelta(minutes=W))]
        if len(w) < 40:
            continue
        dc = w.diff().abs()
        if dc.notna().sum() < 20 or not np.isfinite(dc.max()) or dc.max() == 0:
            continue
        m = int(round((dc.idxmax() - ts).total_seconds() / 60.0))
        rel.append(m)
        nrows += 1
    a = np.array(rel)
    print(f"\n  {label}: {nrows} usable events, window +-{W} min")
    if not len(a):
        return None
    for lo, hi, nm in [(-60, -31, "[-60,-31]"), (-30, -11, "[-30,-11]"),
                       (-10, -1, "[-10,-1]"), (0, 0, "   {0}   "),
                       (1, 1, "   {+1}  "), (2, 10, "  [2,10]"),
                       (11, 30, " [11,30]"), (31, 60, " [31,60]")]:
        c = int(((a >= lo) & (a <= hi)).sum())
        width = hi - lo + 1
        print(f"    {nm:>10}: {c:5d}  ({c / nrows:6.2%})  per-minute rate "
              f"{c / width / nrows:.4%}")
    top = pd.Series(a).value_counts().head(8)
    print(f"    single most common minutes: {top.to_dict()}")
    print(f"    share at exactly 0 : {(a == 0).mean():.3%}   "
          f"(uniform expectation {1/(2*W+1):.3%})")
    return dict(n=nrows, share_0=float((a == 0).mean()),
                share_01=float(((a >= 0) & (a <= 1)).mean()),
                share_pre=float((a < 0).mean()), top=top.to_dict())


print("=" * 78)
print("3a. WHICH MINUTE CARRIES THE BIGGEST MOVE, RELATIVE TO THE STAMP?")
print("=" * 78)
ev = pd.read_parquet(HERE / "event_paths.parquet")
pl = pd.read_parquet(HERE / "placebo_paths.parquet")
e3 = ev[(ev["contract_rank"] == 3) & (ev["offset_min"] == 0)].drop_duplicates("event_id")
p3 = pl[(pl["contract_rank"] == 3) & (pl["offset_min"] == 0)].drop_duplicates("event_id")
OUT["real_all"] = argmax_hist(e3, "REAL  all events")
OUT["real_signed_nonoverlap"] = argmax_hist(
    e3[(~e3["is_overlapping"]) & (e3["stance_sign"] != 0)], "REAL  headline book")
OUT["placebo"] = argmax_hist(p3.sample(n=min(1500, len(p3)), random_state=3),
                             "PLACEBO (1500 draw)")

print("\n" + "=" * 78)
print("3b. IS THE -90/-45 PRE-EVENT WIGGLE REAL, OR AN ARTEFACT OF THE -60 ANCHOR?")
print("=" * 78)


def cl_t(x, g):
    x = np.asarray(x, float); n = len(x); m = x.mean(); e = x - m
    s = pd.Series(e).groupby(np.asarray(g)).sum().to_numpy(); Gn = len(s)
    var = (Gn / (Gn - 1.0)) * (s ** 2).sum() / n ** 2
    return m, m / np.sqrt(var) if var > 0 else np.nan, n


books = {
    "REAL headline (non-ovl, signed)": ev[(ev["contract_rank"] == 3) & (~ev["is_overlapping"])
                                          & (ev["stance_sign"] != 0)],
    "REAL all signed": ev[(ev["contract_rank"] == 3) & (ev["stance_sign"] != 0)],
    "PLACEBO all signed": pl[(pl["contract_rank"] == 3) & (pl["stance_sign"] != 0)],
}
offs = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0, 5, 10, 15, 20, 30, 45, 60, 240]
print(f"  {'offset':>7} " + " ".join(f"{k[:22]:>24}" for k in books))
tab = {}
for off in offs:
    line = f"  {off:>7} "
    for k, df in books.items():
        s = df[(df["offset_min"] == off) & df["signed_d_bp"].notna()]
        if len(s) < 5:
            line += f"{'-':>24} "; continue
        m, t, n = cl_t(s["signed_d_bp"], s["date"])
        line += f"{m:+8.4f} t{t:+6.2f} n{n:>5} "
        tab.setdefault(k, {})[off] = dict(mean=float(m), t=float(t) if t == t else None, n=int(n))
    print(line)
OUT["per_offset"] = tab

print("\n" + "=" * 78)
print("3c. WHERE DOES THE (tiny) MOVE SIT RELATIVE TO THE STAMP?  A LATE stamp")
print("    would put the bulk of it BEFORE 0.")
print("=" * 78)
h = ev[(ev["contract_rank"] == 3) & (~ev["is_overlapping"]) & (ev["stance_sign"] != 0)]
piv = h.pivot_table(index="event_id", columns="offset_min", values="rate_bp", aggfunc="first")
sgn = h.groupby("event_id")["stance_sign"].first()
day = h.groupby("event_id")["date"].first()
for a, b in [(-120, -60), (-60, -5), (-30, -5), (-5, 5), (5, 30), (5, 60), (5, 240),
             (60, 240)]:
    d = (piv[b] - piv[a]) * sgn
    ok = d.notna()
    m, t, n = cl_t(d[ok], day[ok])
    print(f"  signed move [{a:>5} -> {b:>4}] : {m:+.4f} bp   t {t:+.3f}   n {n}")
    OUT[f"seg_{a}_{b}"] = dict(mean=float(m), t=float(t), n=int(n))

(HERE / "z3_stampcheck.json").write_text(json.dumps(OUT, indent=1, default=str))
print("\nWROTE z3_stampcheck.json")
