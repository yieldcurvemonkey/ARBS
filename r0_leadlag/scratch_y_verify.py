"""R0 / Y-side final verification of data/y_signed_volume.parquet.

  V1 schema / dtypes / uniqueness / |signed| <= gross / n_trades > 0 where gross > 0
  V2 minute grid is contiguous inside each session block, gaps only between sessions
  V3 END-TO-END known answer: recompute one bucket-minute from the RAW dbn stream
     (both constituent roots, all contracts) and compare
  V4 bucket-level economic check: corr(signed_volume, contemporaneous 1-min price
     change of the bucket's most active contract) must be POSITIVE
"""
import os, sys, glob, zipfile
import numpy as np
import pandas as pd
import databento as db

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_y_mbo import BUCKETS, sr3_quarterly_set, is_combo

P = os.path.join(HERE, "data", "y_signed_volume.parquet")
df = pd.read_parquet(P)
print("=== V1 schema ===")
print(df.dtypes.to_string())
print("rows", len(df), "buckets", sorted(df["bucket"].unique()))
assert list(df.columns) == ["bucket", "minute_utc", "signed_volume", "gross_volume", "n_trades"]
dup = df.duplicated(["bucket", "minute_utc"]).sum()
print("duplicate (bucket, minute) rows:", dup)
bad1 = (df["signed_volume"].abs() > df["gross_volume"]).sum()
bad2 = ((df["gross_volume"] > 0) & (df["n_trades"] == 0)).sum()
bad3 = ((df["gross_volume"] == 0) & (df["n_trades"] > 0)).sum()
bad4 = (df["gross_volume"] < 0).sum() + (df["n_trades"] < 0).sum()
print(f"|signed|>gross: {bad1}   gross>0&n=0: {bad2}   gross=0&n>0: {bad3}   negatives: {bad4}")
print("null minutes:", df["minute_utc"].isna().sum(),
      " tz:", df["minute_utc"].dt.tz,
      " seconds!=0:", int((df['minute_utc'].dt.second != 0).sum()))

print("\n=== V2 grid contiguity ===")
sess = pd.read_csv(os.path.join(HERE, "data", "y_sessions.csv"))
for b, sub in df.groupby("bucket"):
    d = sub.sort_values("minute_utc")["minute_utc"].diff().dropna()
    steps = d.value_counts()
    n1 = int(steps.get(pd.Timedelta("1min"), 0))
    n_gaps = len(d) - n1
    print(f"  {b:<7} 1-min steps {n1:,}  gaps {n_gaps}  "
          f"(sessions {sess[sess.bucket==b].shape[0]}, so {sess[sess.bucket==b].shape[0]-1} expected)")

print("\n=== V3 end-to-end known answer ===")
TARGETS = [("TY_UXY", "2026-06-02 14:00"), ("SFR_FF", "2026-07-07 14:30"), ("US", "2026-07-15 18:00")]
ZIPS = {r: sorted(glob.glob(f"D:/{r}_mbo/*.zip")) for r in
        ["sr3", "zq", "zt", "zf", "zn", "tn", "zb", "ub"]}
fails = 0
for bucket, tstr in TARGETS:
    t = pd.Timestamp(tstr, tz="UTC")
    lo, hi = t.value, t.value + 60_000_000_000
    sd = t.tz_convert("America/Chicago")
    session = (sd + pd.Timedelta(days=1)).date() if sd.hour >= 17 else sd.date()
    tot_s = tot_g = tot_n = 0
    for root in BUCKETS[bucket]:
        name = f"glbx-mdp3-{t.strftime('%Y%m%d')}.mbo.dbn.zst"
        zp = next((c for c in ZIPS[root] if name in zipfile.ZipFile(c).namelist()), None)
        if zp is None:
            print(f"   {root}: member missing"); continue
        with zipfile.ZipFile(zp) as z:
            store = db.DBNStore.from_bytes(z.read(name))
        id2sym = {int(e["symbol"]): s for s, ents in store.metadata.mappings.items() for e in ents}
        allowed = set(sr3_quarterly_set(session)) if root == "sr3" else None
        for arr in store.to_ndarray(count=4_000_000):
            m = (arr["action"] == b"T") & (arr["ts_event"] >= lo) & (arr["ts_event"] < hi)
            if not m.any():
                continue
            a = arr[m]
            for r in a:
                sym = id2sym.get(int(r["instrument_id"]), "?")
                if sym == "?" or is_combo(sym):
                    continue
                if allowed is not None and sym not in allowed:
                    continue
                s = r["side"]
                tot_s += int(r["size"]) * (1 if s == b"B" else (-1 if s == b"A" else 0))
                tot_g += int(r["size"])
                tot_n += 1
    row = df[(df["bucket"] == bucket) & (df["minute_utc"] == t)]
    got = (int(row["signed_volume"].iloc[0]), int(row["gross_volume"].iloc[0]),
           int(row["n_trades"].iloc[0])) if len(row) else None
    ok = got == (tot_s, tot_g, tot_n)
    print(f"  {bucket} {tstr}: raw=({tot_s}, {tot_g}, {tot_n})  file={got}  {'PASS' if ok else 'FAIL'}")
    fails += 0 if ok else 1

print("\n=== V4 bucket-level sign check vs price ===")
PX = [("TY_UXY", "zn", "ZNU6", "20260715"), ("US", "zb", "ZBU6", "20260715"),
      ("SFR_FF", "sr3", "SR3Z6", "20260715"), ("TU", "zt", "ZTU6", "20260715")]
for bucket, root, sym, day in PX:
    name = f"glbx-mdp3-{day}.mbo.dbn.zst"
    zp = next((c for c in ZIPS[root] if name in zipfile.ZipFile(c).namelist()), None)
    with zipfile.ZipFile(zp) as z:
        store = db.DBNStore.from_bytes(z.read(name))
    iid = next(int(e["symbol"]) for s, ents in store.metadata.mappings.items()
               if s == sym for e in ents)
    rows = []
    for arr in store.to_ndarray(count=4_000_000):
        m = (arr["action"] == b"T") & (arr["instrument_id"] == iid)
        if m.any():
            a = arr[m]
            rows.append(pd.DataFrame({"ts": a["ts_event"].astype("int64"),
                                      "px": a["price"].astype("float64") / 1e9}))
    r = pd.concat(rows, ignore_index=True)
    r["minute_utc"] = pd.to_datetime(r["ts"], utc=True).dt.floor("min")
    last = r.groupby("minute_utc")["px"].last()
    bb = df[df["bucket"] == bucket].set_index("minute_utc")["signed_volume"]
    j = pd.concat([bb, last.rename("px")], axis=1, join="inner").sort_index()
    j["dpx"] = j["px"].diff()
    j = j.dropna()
    c = np.corrcoef(j["signed_volume"], j["dpx"])[0, 1]
    nz = j[(j["dpx"] != 0) & (j["signed_volume"] != 0)]
    agree = float((np.sign(nz["signed_volume"]) == np.sign(nz["dpx"])).mean())
    print(f"  {bucket:<7} vs {sym} {day}: n={len(j)}  corr={c:+.4f}  "
          f"sign-agreement={agree:.3f} on {len(nz)} bins  {'PASS' if c > 0 else 'FAIL'}")
    fails += 0 if c > 0 else 1

print("\nVERIFY FAILS:", fails)
sys.exit(1 if fails else 0)
