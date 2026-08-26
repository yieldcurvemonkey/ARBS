"""SKEPTIC CHECK 2: go back to the RAW minute bars.

  (a) hand-check the worked example at three offsets and the baseline
  (b) known-answer test for START-STAMPING and for the BAR timezone: on an
      08:30 ET macro release the biggest one-minute move must sit in the bar
      LABELLED 08:30 if bars are start-stamped and stamped in ET.  If it sits at
      08:31 the bars are end-stamped; if it sits at 08:30+k hours the tz is off.
  (c) CME maintenance halt fingerprint (17:00-18:00 ET) - a second tz witness
  (d) fully independent re-index of a random sample of (event, rank) cells
"""
import sys, io, json, datetime, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np, pandas as pd
from pathlib import Path
import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OUT = {}

n = G.load_bar_cache(str(HERE / "bars_event_study.pkl"))
print(f"bar cache: {n} symbol-days")
CACHE = G._BAR_CACHE
keys = list(CACHE.keys())
print("sample keys:", keys[:3])

# what tz do the bar indices carry?
k0 = keys[0]
b0 = CACHE[k0]
print(f"\nframe {k0}: {len(b0)} bars, index tz = {getattr(b0.index, 'tz', None)}, "
      f"cols {list(b0.columns)}")
print(f"  first 3 labels: {list(b0.index[:3])}")
print(f"  last  3 labels: {list(b0.index[-3:])}")
OUT["bar_index_tz"] = str(getattr(b0.index, "tz", None))

# ---------------------------------------------------------------- (a) worked ex
print("\n" + "=" * 78)
print("(a) WORKED EXAMPLE - Barkin 2025-04-09 11:00 ET, SR3Z25")
print("=" * 78)
day = datetime.date(2025, 4, 9)
bars = CACHE.get(("SR3Z25", day))
if bars is None:
    print("  MISSING from cache - trying alternate key spellings")
    print([k for k in keys if k[1] == day][:10])
else:
    w = bars.loc["2025-04-09 10:50":"2025-04-09 11:06"]
    print(w[["Open", "High", "Low", "Close"]].to_string())
    ts = pd.Timestamp("2025-04-09 11:00", tz="America/New_York")
    print("\n  hand-applied rule  price(T) = Close of the LAST bar labelled < T")
    for off in [-60, -5, -1, 0, 1, 5]:
        T = ts + pd.Timedelta(minutes=off)
        sub = bars.index[bars.index < T]
        if len(sub) == 0:
            print(f"    offset {off:>4}: no bar")
            continue
        L = sub[-1]
        stale = (T - L).total_seconds() / 60.0 - 1.0
        naive_ix = bars.index[bars.index <= T]
        naive = bars["Close"].loc[naive_ix[-1]] if len(naive_ix) else np.nan
        print(f"    offset {off:>4}: T={T.strftime('%H:%M')}  bar {L.strftime('%H:%M')}"
              f"  close {bars['Close'].loc[L]:.4f}  stale {stale:.1f}min"
              f"   | NAIVE(close of bar<=T) = {naive:.4f}")
        OUT[f"barkin_off{off}"] = dict(bar=L.strftime("%H:%M"),
                                       close=float(bars["Close"].loc[L]),
                                       naive=float(naive))

    # cross-check against the published panel
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    z = ev[(ev["date"].astype(str) == "2025-04-09") & (ev["symbol"] == "SR3Z25")
           & (ev["speaker"].str.contains("Barkin", na=False))]
    print("\n  panel rows for that (event, rank):")
    print(z[["offset_min", "price", "stale_min", "bar_label_ts", "rate_bp",
             "d_rate_bp_from_baseline", "signed_d_bp"]].to_string(index=False))

# ------------------------------------------ (b) start-stamp + tz known-answer
print("\n" + "=" * 78)
print("(b) KNOWN-ANSWER: 08:30 ET macro releases (CPI / NFP).  A start-stamped")
print("    ET-indexed frame must put the biggest 1-min |dClose| in the bar")
print("    LABELLED 08:30.")
print("=" * 78)
ev = pd.read_parquet(HERE / "event_paths.parquet")
macro = ev[(ev["is_cpi_day"] | ev["is_nfp_day"])][["date", "symbol"]].drop_duplicates()
print(f"  candidate (day, symbol) on CPI/NFP days in the cache: {len(macro)}")
hits = []
for _, r in macro.iterrows():
    d = r["date"] if isinstance(r["date"], datetime.date) else pd.Timestamp(r["date"]).date()
    b = CACHE.get((r["symbol"], d))
    if b is None or len(b) < 300 or b["Close"].nunique() < 2:
        continue
    w = b.loc[f"{d} 08:00":f"{d} 09:00"]
    if len(w) < 30:
        continue
    dc = w["Close"].diff().abs()
    if dc.notna().sum() < 10 or dc.max() == 0:
        continue
    hits.append((str(d), r["symbol"], dc.idxmax().strftime("%H:%M"), float(dc.max())))
h = pd.DataFrame(hits, columns=["date", "symbol", "argmax_minute", "abs_move"])
print(f"  usable frames: {len(h)}")
if len(h):
    vc = h["argmax_minute"].value_counts()
    print("  minute carrying the largest |dClose| in the 08:00-09:00 ET window:")
    print(vc.head(12).to_string())
    print(f"\n  share at 08:30 exactly : {(h['argmax_minute'] == '08:30').mean():.1%}")
    print(f"  share at 08:31         : {(h['argmax_minute'] == '08:31').mean():.1%}")
    print(f"  share at 08:29         : {(h['argmax_minute'] == '08:29').mean():.1%}")
    OUT["macro_argmax"] = vc.head(12).to_dict()
    OUT["macro_share_0830"] = float((h["argmax_minute"] == "08:30").mean())
    OUT["macro_share_0831"] = float((h["argmax_minute"] == "08:31").mean())
    OUT["macro_n_frames"] = int(len(h))

# widen: over the WHOLE trading day, where does the biggest minute sit on a CPI day?
print("\n  and over the whole 24h day (tz witness - a 4-5h tz error would move this):")
wide = []
for _, r in macro.iterrows():
    d = r["date"] if isinstance(r["date"], datetime.date) else pd.Timestamp(r["date"]).date()
    b = CACHE.get((r["symbol"], d))
    if b is None or len(b) < 300 or b["Close"].nunique() < 2:
        continue
    dc = b["Close"].diff().abs()
    if dc.notna().sum() < 50 or dc.max() == 0:
        continue
    wide.append(dc.idxmax().strftime("%H:%M"))
if wide:
    vc = pd.Series(wide).value_counts()
    print(vc.head(10).to_string())
    OUT["macro_argmax_24h"] = vc.head(10).to_dict()

# -------------------------------------------------------- (c) CME halt gap
print("\n" + "=" * 78)
print("(c) CME MAINTENANCE HALT: SR3 trades ~23h; the daily break is 17:00-18:00 ET.")
print("    On a start-stamped ET frame the emptiest hour must be 17:00-17:59.")
print("=" * 78)
cnt = np.zeros(24, dtype=float)
nfr = 0
for k in keys[:4000]:
    b = CACHE.get(k)
    if b is None or len(b) < 300 or b["Close"].nunique() < 2:
        continue
    h = pd.Series(b.index.hour).value_counts()
    for hh, c in h.items():
        cnt[hh] += c
    nfr += 1
print(f"  frames scanned: {nfr}")
per = cnt / max(nfr, 1)
for hh in range(24):
    print(f"    {hh:02d}:00  {per[hh]:6.1f} bars/frame  {'#' * int(per[hh] / 1.2)}")
OUT["bars_per_hour"] = {int(i): round(float(per[i]), 2) for i in range(24)}
OUT["emptiest_hour"] = int(np.argmin(per))
print(f"  emptiest hour = {int(np.argmin(per)):02d}:00  (expect 17 on an ET frame)")

# -------------------------------------------- (d) independent re-index sample
print("\n" + "=" * 78)
print("(d) INDEPENDENT RE-INDEX of 400 random (event, rank) cells, own asof code")
print("=" * 78)
OFFS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0, 5, 10, 15, 20, 30, 45, 60,
        90, 120, 180, 240, 300]
cells = ev[["event_id", "speech_ts", "symbol", "contract_rank"]].drop_duplicates(
    ["event_id", "contract_rank"])
rng = random.Random(7)
pick = cells.iloc[rng.sample(range(len(cells)), 400)]
panel_ix = ev.set_index(["event_id", "contract_rank", "offset_min"])
ncmp = nmis = 0
mism = []
for _, r in pick.iterrows():
    ts = pd.Timestamp(r["speech_ts"])
    d0 = (ts - pd.Timedelta(minutes=136)).date()
    d1 = (ts + pd.Timedelta(minutes=300)).date()
    frames = []
    dd = d0
    while dd <= d1:
        b = CACHE.get((r["symbol"], dd))
        if b is not None and len(b) and b["Close"].nunique() >= 2:
            frames.append(b["Close"])
        dd += datetime.timedelta(days=1)
    s = pd.concat(frames).sort_index() if frames else pd.Series(dtype=float)
    for off in OFFS:
        T = ts + pd.Timedelta(minutes=off)
        mine = np.nan
        if len(s):
            sub = s.index[s.index < T]
            if len(sub):
                L = sub[-1]
                if (T - L).total_seconds() / 60.0 - 1.0 <= 15.0:
                    mine = float(s.loc[L])
        try:
            theirs = float(panel_ix.loc[(r["event_id"], r["contract_rank"], off), "price"])
        except KeyError:
            continue
        ncmp += 1
        same = (np.isnan(mine) and np.isnan(theirs)) or np.isclose(mine, theirs, atol=1e-12)
        if not same:
            nmis += 1
            if len(mism) < 12:
                mism.append((int(r["event_id"]), int(r["contract_rank"]), off, mine, theirs))
print(f"  cells compared: {ncmp}   MISMATCHES: {nmis}")
for m in mism:
    print("   ", m)
OUT["reindex"] = dict(compared=ncmp, mismatches=nmis)

(HERE / "z2_bars.json").write_text(json.dumps(OUT, indent=1, default=str))
print("\nWROTE z2_bars.json")
