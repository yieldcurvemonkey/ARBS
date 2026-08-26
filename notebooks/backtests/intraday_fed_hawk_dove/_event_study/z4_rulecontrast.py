"""SKEPTIC CHECK 4: rebuild the headline book from RAW BARS under three
competing bar-indexing rules and show which way the hazard points.

  A  BUILD RULE   price(T) = Close of the LAST bar labelled STRICTLY < T
                  -> a print that had already happened by T.  Strictly causal.
  B  NAIVE        price(T) = Close of the LAST bar labelled <= T
                  -> when a bar is labelled exactly T its close is a print from
                     T+1.  This is the documented hazard: it leaks the first
                     post-event minute into offset 0 (and into the -60 baseline).
  C  BRIEF'S      price(T) = Open of the LAST bar labelled <= T
                  -> the brief suggested "use the bar's OPEN".  The open of the
                     bar labelled T is the FIRST print in [T, T+1), i.e. at or
                     AFTER T - so it is still a (smaller) leak.  A is stricter.

Everything else - baseline -60, staleness cap, sign - is held identical.
"""
import sys, io, json, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np, pandas as pd
from pathlib import Path
import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OFFS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0, 5, 10, 15, 20, 30, 45, 60,
        90, 120, 180, 240, 300]
CAP = 15.0
OUT = {}
G.load_bar_cache(str(HERE / "bars_event_study.pkl"))
CACHE = G._BAR_CACHE

ev = pd.read_parquet(HERE / "event_paths.parquet")
head = ev[(ev["contract_rank"] == 3) & (~ev["is_overlapping"]) & (ev["stance_sign"] != 0)]
meta = head[["event_id", "speech_ts", "symbol", "stance_sign", "date"]].drop_duplicates("event_id")
print(f"headline book: {len(meta)} events")

rows = {"A": [], "B": [], "C": []}
for _, r in meta.iterrows():
    ts = pd.Timestamp(r["speech_ts"])
    frames = []
    for k in (-1, 0, 1):
        b = CACHE.get((r["symbol"], (ts + pd.Timedelta(days=k)).date()))
        if b is not None and len(b) and b["Close"].nunique() >= 2:
            frames.append(b[["Open", "Close"]])
    if not frames:
        continue
    f = pd.concat(frames).sort_index()
    ix = f.index
    for off in OFFS:
        T = ts + pd.Timedelta(minutes=off)
        # A: label strictly < T, use Close
        pre = ix[ix < T]
        a = np.nan
        if len(pre) and (T - pre[-1]).total_seconds() / 60.0 - 1.0 <= CAP:
            a = float(f["Close"].loc[pre[-1]])
        # B / C: label <= T
        le = ix[ix <= T]
        b_ = c_ = np.nan
        if len(le) and (T - le[-1]).total_seconds() / 60.0 <= CAP:
            b_ = float(f["Close"].loc[le[-1]])
            c_ = float(f["Open"].loc[le[-1]])
        for tag, v in (("A", a), ("B", b_), ("C", c_)):
            rows[tag].append((int(r["event_id"]), off, v, int(r["stance_sign"]),
                              str(r["date"])))


def cl_t(x, g):
    x = np.asarray(x, float); n = len(x); m = x.mean(); e = x - m
    s = pd.Series(e).groupby(np.asarray(g)).sum().to_numpy(); Gn = len(s)
    var = (Gn / (Gn - 1.0)) * (s ** 2).sum() / n ** 2
    return m, (m / np.sqrt(var) if var > 0 else np.nan), n


res = {}
for tag in "ABC":
    d = pd.DataFrame(rows[tag], columns=["event_id", "off", "px", "sgn", "date"])
    piv = d.pivot_table(index="event_id", columns="off", values="px", aggfunc="first")
    sgn = d.groupby("event_id")["sgn"].first()
    day = d.groupby("event_id")["date"].first()
    rate = (100.0 - piv) * 100.0
    base = rate[-60]
    sd = rate.sub(base, axis=0).mul(sgn, axis=0)
    r = {}
    for off in [0, 5, 30, 60, 240]:
        s = sd[off].dropna()
        m, t, n = cl_t(s, day[s.index])
        r[f"signed_{off}"] = dict(mean=round(float(m), 4), t=round(float(t), 3), n=int(n))
    j = ((rate[5] - rate[-5]) * sgn).dropna()
    m, t, n = cl_t(j, day[j.index])
    r["jump_m5_p5"] = dict(mean=round(float(m), 4), t=round(float(t), 3), n=int(n))
    # hawk - dove gap at +240 on the unsigned path
    u = rate.sub(base, axis=0)[240].dropna()
    hk = u[sgn[u.index] > 0]; dv = u[sgn[u.index] < 0]
    r["gap_240"] = dict(gap=round(float(hk.mean() - dv.mean()), 4),
                        n_hawk=int(len(hk)), n_dove=int(len(dv)))
    # how often does the rule differ from A at offset 0?
    res[tag] = r

pa = pd.DataFrame(rows["A"], columns=["event_id", "off", "px", "sgn", "date"])
pb = pd.DataFrame(rows["B"], columns=["event_id", "off", "px", "sgn", "date"])
pc = pd.DataFrame(rows["C"], columns=["event_id", "off", "px", "sgn", "date"])
m0 = pa[pa["off"] == 0].merge(pb[pb["off"] == 0], on="event_id", suffixes=("_a", "_b")) \
       .merge(pc[pc["off"] == 0][["event_id", "px"]].rename(columns={"px": "px_c"}), on="event_id")
ok = m0["px_a"].notna() & m0["px_b"].notna()
diff_b = (m0.loc[ok, "px_b"] - m0.loc[ok, "px_a"])
okc = m0["px_a"].notna() & m0["px_c"].notna()
diff_c = (m0.loc[okc, "px_c"] - m0.loc[okc, "px_a"])
print(f"\nAT OFFSET 0, rule B (naive close) differs from the build rule on "
      f"{(diff_b != 0).mean():.1%} of events; mean price diff {diff_b.mean():+.5f} "
      f"(= {-diff_b.mean()*100:+.4f} bp of rate), max |diff| {diff_b.abs().max():.4f}")
print(f"AT OFFSET 0, rule C (bar OPEN)     differs on {(diff_c != 0).mean():.1%}; "
      f"mean {diff_c.mean():+.5f}, max |diff| {diff_c.abs().max():.4f}")
OUT["offset0_diff"] = dict(share_B=float((diff_b != 0).mean()),
                           mean_B=float(diff_b.mean()), max_B=float(diff_b.abs().max()),
                           share_C=float((diff_c != 0).mean()),
                           mean_C=float(diff_c.mean()), max_C=float(diff_c.abs().max()))

print("\n" + "=" * 78)
print("HEADLINE NUMBERS UNDER EACH RULE (bp, day-clustered t)")
print("=" * 78)
lab = {"A": "A build (close of bar < T)  CAUSAL",
       "B": "B naive (close of bar <= T) LEAKY",
       "C": "C open  (open  of bar <= T) brief"}
keys = ["jump_m5_p5", "signed_0", "signed_5", "signed_30", "signed_60", "signed_240"]
print(f"{'':38}" + "".join(f"{k:>20}" for k in keys))
for tag in "ABC":
    line = f"{lab[tag]:38}"
    for k in keys:
        v = res[tag][k]
        line += f"{v['mean']:+8.4f} t{v['t']:+5.2f}  "
    print(line)
for tag in "ABC":
    print(f"  {lab[tag]:38} gap@240 {res[tag]['gap_240']}")
OUT["rules"] = res

(HERE / "z4_rulecontrast.json").write_text(json.dumps(OUT, indent=1, default=str))
print("\nWROTE z4_rulecontrast.json")
