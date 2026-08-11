"""R0 / Y-side probe 6: does outright-book T volume + spread-LEG volume
reconcile to the exchange-published contract volume?

Fixes probe 5's combo matcher (it matched the outright itself).
Also enumerates the SR3 / ZQ combo symbol families.
"""
import zipfile, glob, sys, re
from datetime import timedelta
import numpy as np
import pandas as pd
import databento as db

sys.path.insert(0, "C:/Users/chris/clee/ARBS-r0/r0_leadlag")
from scratch_y_barchart import eod

ZIPS = {r: sorted(glob.glob(f"D:/{r}_mbo/*.zip")) for r in
        ["sr3", "zq", "zt", "zf", "zn", "tn", "zb", "ub"]}
CT_OFFSET_H = 5


def member_path(root, d):
    name = f"glbx-mdp3-{d:%Y%m%d}.mbo.dbn.zst"
    for zp in ZIPS[root]:
        with zipfile.ZipFile(zp) as z:
            if name in z.namelist():
                return zp, name
    return None, None


def load(root, d):
    zp, name = member_path(root, d)
    if zp is None:
        return None, {}
    with zipfile.ZipFile(zp) as z:
        store = db.DBNStore.from_bytes(z.read(name))
    id2sym = {}
    for sym, ents in store.metadata.mappings.items():
        for e in ents:
            id2sym[int(e["symbol"])] = sym
    parts = []
    for arr in store.to_ndarray(count=4_000_000):
        m = arr["action"] == b"T"
        if m.any():
            a = arr[m]
            parts.append(pd.DataFrame({"iid": a["instrument_id"],
                                       "ts": a["ts_event"].astype("int64"),
                                       "sz": a["size"].astype("int64")}))
    return (pd.concat(parts, ignore_index=True) if parts else None), id2sym


def legs_of(sym):
    """Leg symbols of a dash-delimited CME combo (Treasury / ZQ calendar style)."""
    if ":" in sym:
        return []          # SR3 pack/bundle/condor families: legs are not literal
    return sym.split("-") if "-" in sym else []


CASES = [
    ("2026-05-29", "zn", "ZNM6", "ZNM26"),
    ("2026-05-29", "zn", "ZNU6", "ZNU26"),
    ("2026-06-02", "zn", "ZNU6", "ZNU26"),
    ("2026-06-02", "zq", "ZQM6", "ZQM26"),
    ("2026-07-07", "zq", "ZQQ6", "ZQQ26"),
]
loaded, bc = {}, {}
rows = []
for sess, root, sym, bsym in CASES:
    D = pd.Timestamp(sess).date(); Dm1 = D - timedelta(days=1)
    s_ns = int(pd.Timestamp(f"{Dm1} 17:00").tz_localize("UTC").value) + CT_OFFSET_H * 3600 * 10**9
    e_ns = int(pd.Timestamp(f"{D} 16:00").tz_localize("UTC").value) + CT_OFFSET_H * 3600 * 10**9
    out_v = leg_v = 0
    for dd in (Dm1, D):
        if (root, dd) not in loaded:
            loaded[(root, dd)] = load(root, dd)
        df, id2sym = loaded[(root, dd)]
        if df is None:
            continue
        w = df[(df["ts"] >= s_ns) & (df["ts"] < e_ns)]
        g = w.groupby("iid")["sz"].sum()
        for iid, v in g.items():
            s = id2sym.get(int(iid), "?")
            if s == sym:
                out_v += int(v)
            elif sym in legs_of(s):
                leg_v += int(v)
    if bsym not in bc:
        bc[bsym] = eod(bsym, "20260501", "20260810").set_index("Date")["Volume"].to_dict()
    pub = bc[bsym].get(sess)
    rows.append({"session": sess, "sym": sym, "published": pub, "outright_T": out_v,
                 "spread_leg_T": leg_v, "sum": out_v + leg_v,
                 "outright/pub": out_v / pub if pub else None,
                 "sum/pub": (out_v + leg_v) / pub if pub else None})
    print(rows[-1])

print()
print(pd.DataFrame(rows).to_string(index=False))

# ---- SR3 / ZQ combo family census (one day) ----
for root, dd in [("sr3", pd.Timestamp("2026-07-07").date()), ("zq", pd.Timestamp("2026-07-07").date())]:
    df, id2sym = loaded.get((root, dd), (None, {}))
    if df is None:
        df, id2sym = load(root, dd)
    g = df.groupby("iid")["sz"].sum()
    fam = {}
    for iid, v in g.items():
        s = id2sym.get(int(iid), "?")
        if ":" in s:
            f = s.split()[0]
        elif "-" in s:
            f = "CALENDAR/INTER"
        else:
            f = "OUTRIGHT"
        fam[f] = fam.get(f, 0) + int(v)
    tot = sum(fam.values())
    print(f"\n{root.upper()} combo family census {dd} (UTC-day T volume, total {tot:,}):")
    for f, v in sorted(fam.items(), key=lambda x: -x[1]):
        print(f"   {f:<18} {v:>12,}  {v/tot:6.2%}")
