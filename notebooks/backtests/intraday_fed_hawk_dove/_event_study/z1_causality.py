"""SKEPTIC CHECK 1: global causality / lookahead assertion on BOTH parquets,
plus the timezone-of-the-event-stamp evidence, plus the required headline recompute.

Nothing here touches the raw bar cache - it is a pure re-derivation from the
published panel, so it is independent of the build script's own helpers.
"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np, pandas as pd
from pathlib import Path

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OUT = {}


def sec(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


# ---------------------------------------------------------------- 1. causality
sec("1. GLOBAL CAUSALITY ASSERTION  (every priced row must use a bar that had "
    "already CLOSED by its own target instant)")
for name in ["event_paths.parquet", "placebo_paths.parquet"]:
    df = pd.read_parquet(HERE / name)
    tgt = df["speech_ts"] + pd.to_timedelta(df["offset_min"], unit="m")
    priced = df["price"].notna()
    n = int(priced.sum())

    # (a) seconds on the event stamp: a non-zero second makes stale = d/60-1 < 0
    sec_nonzero = int((df["speech_ts"].dt.second != 0).sum())
    # (b) bar label must be STRICTLY before target
    lab = df["bar_label_ts"]
    lab_ok = (lab[priced] < tgt[priced])
    # (c) the bar's CLOSE is stamped label+1min; that must be <= target
    close_ts = lab + pd.Timedelta(minutes=1)
    close_ok = (close_ts[priced] <= tgt[priced])
    # (d) staleness must be >= 0 and <= cap, and must equal the recomputed value
    st = df.loc[priced, "stale_min"]
    st_recalc = ((tgt[priced] - lab[priced]).dt.total_seconds() / 60.0) - 1.0
    st_match = np.isclose(st.to_numpy(float), st_recalc.to_numpy(float), atol=1e-9)

    print(f"\n--- {name}: {len(df):,} rows, {n:,} priced")
    print(f"  speech_ts with non-zero SECONDS      : {sec_nonzero}")
    print(f"  rows where bar_label >= target       : {int((~lab_ok).sum())}   "
          f"[LOOKAHEAD if > 0]")
    print(f"  rows where bar CLOSE (label+1) > tgt : {int((~close_ok).sum())}   "
          f"[LOOKAHEAD if > 0]")
    print(f"  stale_min < 0                        : {int((st < 0).sum())}")
    print(f"  stale_min > 15 (the stated cap)      : {int((st > 15.0).sum())}")
    print(f"  stale_min disagrees with recompute   : {int((~st_match).sum())}")
    print(f"  stale_min  min/med/mean/max          : {st.min():.2f} / "
          f"{st.median():.2f} / {st.mean():.3f} / {st.max():.2f}")
    # worst-case: how far back in time is the offset-0 price actually from?
    z = df[priced & (df["offset_min"] == 0)]
    print(f"  at offset 0: stale_min mean {z['stale_min'].mean():.3f}, "
          f"share stale>1min {(z['stale_min'] > 1).mean():.3%}, "
          f"share stale>5min {(z['stale_min'] > 5).mean():.3%}")
    OUT[name] = dict(rows=len(df), priced=n, sec_nonzero=sec_nonzero,
                     lookahead_label=int((~lab_ok).sum()),
                     lookahead_close=int((~close_ok).sum()),
                     stale_neg=int((st < 0).sum()), stale_over_cap=int((st > 15).sum()),
                     stale_mismatch=int((~st_match).sum()),
                     stale_mean=float(st.mean()), stale_max=float(st.max()))

    if name == "event_paths.parquet":
        ev = df

# -------------------------------------------------- 1b. is the baseline stale?
sec("1b. IS THE -60 BASELINE ITSELF CONTAMINATED?  (a baseline filled from a "
    "LATER bar would open the fan by construction)")
b = ev[(ev["offset_min"] == -60) & ev["price"].notna()]
print(f"  baseline rows priced: {len(b):,}")
print(f"  baseline bar_label >= speech_ts-60min : "
      f"{int((b['bar_label_ts'] >= (b['speech_ts'] - pd.Timedelta(minutes=60))).sum())}")
print(f"  baseline stale_min mean {b['stale_min'].mean():.3f}, max {b['stale_min'].max():.2f}")
# does baseline_price actually equal the price at offset -60?
chk = ev.merge(b[["event_id", "contract_rank", "price"]],
               on=["event_id", "contract_rank"], suffixes=("", "_at_m60"))
bad = int((~np.isclose(chk["baseline_price"], chk["price_at_m60"], atol=1e-12)).sum())
print(f"  rows where baseline_price != price at offset -60 : {bad}")
# does the SAME bar ever serve both -60 and 0?  (would force d=0 -> attenuation)
p0 = ev[ev["offset_min"] == 0][["event_id", "contract_rank", "bar_label_ts"]]
same = b[["event_id", "contract_rank", "bar_label_ts"]].merge(
    p0, on=["event_id", "contract_rank"], suffixes=("_m60", "_0"))
print(f"  (event,rank) where the -60 bar IS the offset-0 bar : "
      f"{int((same['bar_label_ts_m60'] == same['bar_label_ts_0']).sum())} of {len(same)}"
      f"  [attenuation, not lookahead]")
OUT["baseline"] = dict(n=len(b), baseline_price_mismatch=bad,
                       same_bar_m60_and_0=int((same['bar_label_ts_m60'] == same['bar_label_ts_0']).sum()),
                       n_pairs=len(same))

# ------------------------------------------------------ 2. event-stamp clock tz
sec("2. EVENT-STAMP TIMEZONE: the clock distribution and named anchors")
e = pd.read_parquet(HERE / "events.parquet")
print(f"  events.parquet speech_ts dtype: {e['speech_ts'].dtype}")
hr = e["speech_ts"].dt.hour.value_counts().sort_index()
print("  hour-of-day histogram (America/New_York):")
for h, c in hr.items():
    print(f"    {h:02d}:00  {c:5d}  {'#' * int(c / 4)}")
print("\n  clock value counts (top 25):")
print(e["clock"].value_counts().head(25).to_string())
OUT["hour_hist"] = {int(k): int(v) for k, v in hr.items()}

print("\n  --- named anchors (external knowledge): Powell testimony / Jackson Hole ---")
pw = e[e["title"].str.contains("Powell", case=False, na=False)]
print(f"  Powell rows: {len(pw)}")
print(pw[["speech_ts", "clock", "title"]].head(40).to_string())
OUT["powell_clocks"] = pw["clock"].value_counts().to_dict()

# --------------------------------------------------------- 3. required recompute
sec("3. REQUIRED INDEPENDENT RECOMPUTE - headline book, rank 3")


def cluster_t(x, g):
    """CR1 day-clustered t for a mean (OLS on a constant)."""
    x = np.asarray(x, float)
    n = len(x)
    m = x.mean()
    e = x - m
    s = pd.Series(e).groupby(np.asarray(g)).sum().to_numpy()
    G = len(s)
    c = (G / (G - 1.0)) * ((n - 1.0) / (n - 1.0))          # k = 1
    var = c * (s ** 2).sum() / n ** 2
    return m, np.sqrt(var), m / np.sqrt(var), n, G


r3 = ev[(ev["contract_rank"] == 3)].copy()
head = r3[(~r3["is_overlapping"]) & (r3["stance_sign"] != 0)].copy()
print(f"  headline book events: {head['event_id'].nunique()} "
      f"(hawk {head[head['stance_sign'] > 0]['event_id'].nunique()}, "
      f"dove {head[head['stance_sign'] < 0]['event_id'].nunique()}), "
      f"days {head['date'].nunique()}")

for off in [0, 30, 240, 300]:
    s = head[(head["offset_min"] == off) & head["signed_d_bp"].notna()]
    m, se, t, n, G = cluster_t(s["signed_d_bp"], s["date"])
    print(f"  signed_d_bp @ +{off:>3}: mean {m:+.4f} bp  SE {se:.4f}  t {t:+.3f}  "
          f"n {n}  days {G}")
    OUT[f"signed_{off}"] = dict(mean=float(m), se=float(se), t=float(t), n=int(n), days=int(G))

# hawk - dove gap at +240 (on d_rate_bp_from_baseline, unsigned)
s = head[(head["offset_min"] == 240) & head["d_rate_bp_from_baseline"].notna()]
hk = s[s["stance_sign"] > 0]["d_rate_bp_from_baseline"]
dv = s[s["stance_sign"] < 0]["d_rate_bp_from_baseline"]
gap = hk.mean() - dv.mean()
# day-clustered two-sample via a dummy regression
y = s["d_rate_bp_from_baseline"].to_numpy(float)
X = np.column_stack([np.ones(len(s)), (s["stance_sign"] > 0).to_numpy(float)])
bhat = np.linalg.lstsq(X, y, rcond=None)[0]
res = y - X @ bhat
XtXi = np.linalg.inv(X.T @ X)
meat = np.zeros((2, 2))
for _, idx in pd.Series(range(len(s))).groupby(s["date"].to_numpy()):
    ii = idx.to_numpy()
    u = X[ii].T @ res[ii]
    meat += np.outer(u, u)
G = s["date"].nunique()
V = XtXi @ meat @ XtXi * (G / (G - 1.0)) * ((len(s) - 1.0) / (len(s) - 2.0))
print(f"\n  hawk-dove gap @ +240: {gap:+.4f} bp  (regression coef {bhat[1]:+.4f}, "
      f"t {bhat[1] / np.sqrt(V[1, 1]):+.3f})  n {len(s)} "
      f"(hawk {len(hk)}, dove {len(dv)})  days {G}")
OUT["gap_240"] = dict(gap=float(gap), coef=float(bhat[1]),
                      t=float(bhat[1] / np.sqrt(V[1, 1])), n=int(len(s)),
                      n_hawk=int(len(hk)), n_dove=int(len(dv)))

# ---------------------------------------------------- 4. pre-event slope (hazard 3)
sec("4. PRE-EVENT SLOPE  (hazard 3: a late event stamp shows up as pre-drift "
    "in the direction of the eventual move)")
pre = head[head["offset_min"].isin([-120, -90, -45, -30, -20, -15, -10, -5])
           & head["signed_d_bp"].notna()]
x = pre["offset_min"].to_numpy(float) / 60.0
y = pre["signed_d_bp"].to_numpy(float)
X = np.column_stack([np.ones(len(x)), x])
bhat = np.linalg.lstsq(X, y, rcond=None)[0]
res = y - X @ bhat
XtXi = np.linalg.inv(X.T @ X)
meat = np.zeros((2, 2))
for _, idx in pd.Series(range(len(pre))).groupby(pre["date"].to_numpy()):
    ii = idx.to_numpy()
    u = X[ii].T @ res[ii]
    meat += np.outer(u, u)
G = pre["date"].nunique()
V = XtXi @ meat @ XtXi * (G / (G - 1.0)) * ((len(pre) - 1.0) / (len(pre) - 2.0))
print(f"  pre-event slope (excl. the mechanically-zero -60 anchor): "
      f"{bhat[1]:+.4f} bp/hour, day-clustered t {bhat[1] / np.sqrt(V[1, 1]):+.3f}, "
      f"n {len(pre)} rows / {G} days")
OUT["pre_slope"] = dict(slope=float(bhat[1]), t=float(bhat[1] / np.sqrt(V[1, 1])),
                        n=int(len(pre)), days=int(G))

# per-offset pre-event means, to see whether drift accumulates toward 0
print("\n  per-offset mean signed_d_bp BEFORE the speech:")
for off in [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0, 5]:
    s = head[(head["offset_min"] == off) & head["signed_d_bp"].notna()]
    if len(s):
        m, se, t, n, G = cluster_t(s["signed_d_bp"], s["date"])
        print(f"    {off:>5}: {m:+.4f} bp  t {t:+.2f}  n {n}")
        OUT[f"preoff_{off}"] = dict(mean=float(m), t=float(t), n=int(n))

# ------------------------------------- 5. attenuation attack: fresh bars only
sec("5. ATTENUATION ATTACK - re-run the -5 -> +5 jump on FRESH bars only "
    "(stale_min <= 2 at -5, 0 and +5). The build's rule can only UNDERSTATE; "
    "this bounds by how much.")
piv = head.pivot_table(index="event_id", columns="offset_min",
                       values=["rate_bp", "stale_min"], aggfunc="first")
sgn = head.groupby("event_id")["stance_sign"].first()
day = head.groupby("event_id")["date"].first()
for cap in [15.0, 5.0, 2.0, 1.0, 0.0]:
    ok = (piv[("stale_min", -5)] <= cap) & (piv[("stale_min", 5)] <= cap)
    d = (piv[("rate_bp", 5)] - piv[("rate_bp", -5)]) * sgn
    m_ = ok & d.notna()
    if m_.sum() < 5:
        print(f"  cap {cap:>4}: n={int(m_.sum())} - too few")
        continue
    mm, se, t, n, G = cluster_t(d[m_], day[m_])
    print(f"  stale<= {cap:>4} min: jump(-5->+5) {mm:+.4f} bp  t {t:+.3f}  "
          f"n {n} events / {G} days")
    OUT[f"jump_cap{cap}"] = dict(mean=float(mm), t=float(t), n=int(n))

# same for the 0 -> +30 window
print("\n  and the 0 -> +30 window:")
for cap in [15.0, 2.0, 1.0, 0.0]:
    ok = (piv[("stale_min", 0)] <= cap) & (piv[("stale_min", 30)] <= cap)
    d = (piv[("rate_bp", 30)] - piv[("rate_bp", 0)]) * sgn
    m_ = ok & d.notna()
    if m_.sum() < 5:
        continue
    mm, se, t, n, G = cluster_t(d[m_], day[m_])
    print(f"  stale<= {cap:>4} min: {mm:+.4f} bp  t {t:+.3f}  n {n} / {G} days")
    OUT[f"j030_cap{cap}"] = dict(mean=float(mm), t=float(t), n=int(n))

(HERE / "z1_causality.json").write_text(json.dumps(OUT, indent=1, default=str))
print("\nWROTE z1_causality.json")
