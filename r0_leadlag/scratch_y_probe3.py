"""R0 / Y-side probe 3.

(1) INDEPENDENT CHECK: sign(signed aggressor volume) vs contemporaneous
    1-minute price change.  Buyers lift offers -> price up.
(2) per-instrument T volume vs F volume (double-count evidence).
(3) daily total volume per contract, for external reconciliation.
"""
import zipfile, sys
import numpy as np
import pandas as pd
import databento as db

CASES = [
    ("D:/ub_mbo/GLBX-20260808-PF3KREYS4D.zip", "glbx-mdp3-20260602.mbo.dbn.zst", "UB"),
    ("D:/zn_mbo/GLBX-20260808-5ELX5DQDJ9.zip", "glbx-mdp3-20260602.mbo.dbn.zst", "ZN"),
]

for ZIP, MEMBER, ROOT in CASES:
    z = zipfile.ZipFile(ZIP)
    store = db.DBNStore.from_bytes(z.read(MEMBER))
    mp = store.metadata.mappings
    id2sym = {}
    for sym, ents in mp.items():
        for e in ents:
            id2sym[int(e["symbol"])] = sym
    full = np.concatenate([a for a in store.to_ndarray(count=8_000_000)])
    print(f"\n########## {ROOT} {MEMBER}  records={len(full):,}")

    mT = full["action"] == b"T"
    mF = full["action"] == b"F"
    tv = pd.Series(full["size"][mT].astype("int64")).groupby(
        pd.Series(full["instrument_id"][mT])).sum()
    fv = pd.Series(full["size"][mF].astype("int64")).groupby(
        pd.Series(full["instrument_id"][mF])).sum()
    tab = pd.DataFrame({"T_vol": tv, "F_vol": fv}).fillna(0).astype("int64")
    tab["sym"] = [id2sym.get(i, "?") for i in tab.index]
    tab["is_spread"] = tab["sym"].str.contains("-") | tab["sym"].str.contains(":")
    tab = tab.sort_values("T_vol", ascending=False)
    print(tab.head(12).to_string())
    print("  outright T_vol total:", int(tab.loc[~tab.is_spread, "T_vol"].sum()),
          " spread T_vol total:", int(tab.loc[tab.is_spread, "T_vol"].sum()))

    # ---- price-change check on the single most active outright ----
    top = tab[~tab.is_spread].index[0]
    sym = id2sym[top]
    t = full[mT & (full["instrument_id"] == top)]
    ts = pd.to_datetime(t["ts_recv"], utc=True)
    px = t["price"].astype("float64") / 1e9
    sz = t["size"].astype("int64")
    sd = np.where(t["side"] == b"B", 1, np.where(t["side"] == b"A", -1, 0))
    df = pd.DataFrame({"ts": ts, "px": px, "sz": sz, "sd": sd})
    df["minute"] = df["ts"].dt.floor("min")
    g = df.groupby("minute").agg(
        signed=("sd", lambda s: 0),  # placeholder replaced below
        last=("px", "last"),
        first=("px", "first"),
        n=("px", "size"),
    )
    g["signed"] = df.assign(sv=df.sd * df.sz).groupby("minute")["sv"].sum()
    g["gross"] = df.groupby("minute")["sz"].sum()
    g = g.sort_index()
    g["dpx_close2close"] = g["last"].diff()
    g["dpx_within"] = g["last"] - g["first"]
    sub = g.dropna()
    c1 = np.corrcoef(sub["signed"], sub["dpx_close2close"])[0, 1]
    c2 = np.corrcoef(g["signed"], g["dpx_within"])[0, 1]
    # sign-agreement rate on nonzero moves
    nz = sub[(sub["dpx_close2close"] != 0) & (sub["signed"] != 0)]
    agree = float((np.sign(nz["signed"]) == np.sign(nz["dpx_close2close"])).mean())
    print(f"  price-change check on {sym}: bins={len(g)}")
    print(f"    corr(signed_vol, minute close-to-close dP) = {c1:+.4f}")
    print(f"    corr(signed_vol, within-minute first->last dP) = {c2:+.4f}")
    print(f"    sign-agreement rate on {len(nz)} nonzero bins = {agree:.4f}")
    tot_signed = int(df.assign(sv=df.sd * df.sz)["sv"].sum())
    print(f"    day signed = {tot_signed:,} of gross {int(df['sz'].sum()):,};"
          f" day dP = {px[-1]-px[0]:+.6f}")
