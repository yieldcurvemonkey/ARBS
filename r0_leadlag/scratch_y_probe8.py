"""R0 / Y-side probe 8: bin-level known-answer check.

Recomputes a handful of (contract, minute) cells straight from the raw DBN stream
with an independent code path (pure pandas, no reuse of build_y_mbo's aggregation)
and compares them to the cached parquet.  Catches binning / sign / floor errors that
day totals cannot see.
"""
import os, sys, zipfile, glob
import numpy as np
import pandas as pd
import databento as db

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache_y_mbo")

CASES = [
    ("zn", "20260602", "ZNU6"),
    ("zt", "20260715", "ZTU6"),
    ("sr3", "20260707", "SR3Z6"),
]

fails = 0
for root, day, sym in CASES:
    zp = None
    name = f"glbx-mdp3-{day}.mbo.dbn.zst"
    for cand in sorted(glob.glob(f"D:/{root}_mbo/*.zip")):
        with zipfile.ZipFile(cand) as z:
            if name in z.namelist():
                zp = cand
                break
    if zp is None:
        print(f"SKIP {root} {day}: member absent"); continue
    with zipfile.ZipFile(zp) as z:
        store = db.DBNStore.from_bytes(z.read(name))
    iid = None
    for s, ents in store.metadata.mappings.items():
        if s == sym:
            iid = int(ents[0]["symbol"])
    if iid is None:
        print(f"SKIP {root} {day} {sym}: not in symbology"); continue

    rows = []
    for arr in store.to_ndarray(count=4_000_000):
        m = (arr["action"] == b"T") & (arr["instrument_id"] == iid)
        if m.any():
            a = arr[m]
            rows.append(pd.DataFrame({"ts": a["ts_event"].astype("int64"),
                                      "sz": a["size"].astype("int64"),
                                      "sd": [x.decode() for x in a["side"]]}))
    raw = pd.concat(rows, ignore_index=True)
    raw["minute_utc"] = pd.to_datetime(raw["ts"], utc=True).dt.floor("min")
    raw["sgn"] = raw["sd"].map({"B": 1, "A": -1}).fillna(0).astype(int)
    ind = (raw.assign(sv=raw["sgn"] * raw["sz"])
              .groupby("minute_utc")
              .agg(signed_volume=("sv", "sum"), gross_volume=("sz", "sum"),
                   n_trades=("sz", "size")))

    cached = pd.read_parquet(os.path.join(CACHE, root, f"{day}.parquet"))
    cached = cached[cached["sym"] == sym].copy()
    cached["minute_utc"] = pd.to_datetime(cached["minute_utc"], utc=True)
    cached = cached.set_index("minute_utc")[["signed_volume", "gross_volume", "n_trades"]]

    j = ind.join(cached, how="outer", lsuffix="_indep", rsuffix="_cache").fillna(-999999)
    bad = j[(j["signed_volume_indep"] != j["signed_volume_cache"]) |
            (j["gross_volume_indep"] != j["gross_volume_cache"]) |
            (j["n_trades_indep"] != j["n_trades_cache"])]
    print(f"{root}/{sym} {day}: {len(ind)} independent bins, {len(cached)} cached bins, "
          f"mismatched bins = {len(bad)}  {'PASS' if len(bad)==0 else 'FAIL'}")
    if len(bad):
        print(bad.head(10).to_string())
        fails += 1
    else:
        k = ind.sort_values("gross_volume", ascending=False).head(3)
        print("   busiest bins:", [(str(i), int(r.signed_volume), int(r.gross_volume),
                                    int(r.n_trades)) for i, r in k.iterrows()])
sys.exit(fails)
