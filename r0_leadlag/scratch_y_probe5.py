"""R0 / Y-side probe 5: DAILY VOLUME RECONCILIATION against Barchart (external).

Aggregates MBO trades over the real CME Globex session window
(D-1 17:00 CT -> D 16:00 CT, i.e. D-1 22:00 UTC -> D 21:00 UTC in CDT), which
spans TWO Databento UTC-day files, and compares three candidate volume
definitions against the exchange-reported volume Barchart publishes:

    T_only      sum(size) over action=='T' on the outright instrument
    T_plus_F    sum(size) over action in ('T','F')      <- the double-count trap
    T_all       T_only + spread/combo-instrument T volume
"""
import json, zipfile, glob, sys
from datetime import date, timedelta
import numpy as np
import pandas as pd
import databento as db

sys.path.insert(0, "C:/Users/chris/clee/ARBS-r0/r0_leadlag")
from scratch_y_barchart import eod

ZIPS = {r: sorted(glob.glob(f"D:/{r}_mbo/*.zip")) for r in
        ["sr3", "zq", "zt", "zf", "zn", "tn", "zb", "ub"]}

# session date -> (root, dbn symbol, barchart symbol)
CASES = [
    ("2026-06-02", "zn", "ZNU6", "ZNU26"),
    ("2026-06-02", "zt", "ZTU6", "ZTU26"),
    ("2026-06-02", "zf", "ZFU6", "ZFU26"),
    ("2026-06-02", "zb", "ZBU6", "ZBU26"),
    ("2026-06-02", "tn", "TNU6", "TNU26"),
    ("2026-06-02", "zq", "ZQM6", "ZQM26"),
    ("2026-07-07", "zn", "ZNU6", "ZNU26"),
    ("2026-07-07", "zq", "ZQQ6", "ZQQ26"),
    ("2026-07-07", "sr3", "SR3M6", "SQM26"),
    ("2026-07-07", "sr3", "SR3U6", "SQU26"),
    ("2026-07-07", "sr3", "SR3Z6", "SQZ26"),
    # roll-period day: Sep/Dec Treasury roll runs late Aug; use a mid-roll Jun day
    ("2026-05-29", "zn", "ZNM6", "ZNM26"),
    ("2026-05-29", "zn", "ZNU6", "ZNU26"),
]


def member_path(root, d: date):
    name = f"glbx-mdp3-{d:%Y%m%d}.mbo.dbn.zst"
    for zp in ZIPS[root]:
        with zipfile.ZipFile(zp) as z:
            if name in z.namelist():
                return zp, name
    return None, None


def load_trades(root, d: date):
    """Return DataFrame of T and F records for a UTC day file, + id->sym map."""
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
        m = (arr["action"] == b"T") | (arr["action"] == b"F")
        if m.any():
            a = arr[m]
            parts.append(pd.DataFrame({
                "iid": a["instrument_id"],
                "ts": a["ts_event"].astype("int64"),
                "sz": a["size"].astype("int64"),
                "side": a["side"],
                "act": a["action"],
            }))
    if not parts:
        return None, id2sym
    return pd.concat(parts, ignore_index=True), id2sym


CT_OFFSET_H = 5  # CDT = UTC-5 for the whole sample (2026-05-07..2026-08-06)
rows = []
bc_cache = {}
loaded = {}
for sess_str, root, dbn_sym, bc_sym in CASES:
    D = pd.Timestamp(sess_str).date()
    Dm1 = D - timedelta(days=1)
    if root == "zn" and Dm1.weekday() == 6:
        pass
    start_ns = int(pd.Timestamp(f"{Dm1} 17:00", tz=None).tz_localize("UTC").value) + CT_OFFSET_H * 3600 * 10**9
    end_ns = int(pd.Timestamp(f"{D} 16:00", tz=None).tz_localize("UTC").value) + CT_OFFSET_H * 3600 * 10**9

    tot = {"T_only": 0, "T_plus_F": 0, "T_all": 0, "T_combo": 0, "utcday_T_only": 0}
    for dd in (Dm1, D):
        key = (root, dd)
        if key not in loaded:
            loaded[key] = load_trades(root, dd)
        df, id2sym = loaded[key]
        if df is None:
            continue
        ids = [i for i, s in id2sym.items() if s == dbn_sym]
        if not ids:
            continue
        sub = df[df["iid"].isin(ids)]
        insess = sub[(sub["ts"] >= start_ns) & (sub["ts"] < end_ns)]
        tot["T_only"] += int(insess.loc[insess["act"] == b"T", "sz"].sum())
        tot["T_plus_F"] += int(insess["sz"].sum())
        if dd == D:
            tot["utcday_T_only"] += int(sub.loc[sub["act"] == b"T", "sz"].sum())
        # combos that name this contract
        cids = [i for i, s in id2sym.items()
                if dbn_sym in s.replace(":", " ").split() or (dbn_sym in s and s != dbn_sym)]
        csub = df[df["iid"].isin(cids)]
        cin = csub[(csub["ts"] >= start_ns) & (csub["ts"] < end_ns)]
        tot["T_combo"] += int(cin.loc[cin["act"] == b"T", "sz"].sum())
    tot["T_all"] = tot["T_only"] + tot["T_combo"]

    if bc_sym not in bc_cache:
        try:
            bc_cache[bc_sym] = eod(bc_sym, "20260501", "20260810").set_index("Date")["Volume"].to_dict()
        except Exception as e:
            print("barchart err", bc_sym, repr(e)[:120]); bc_cache[bc_sym] = {}
    pub = bc_cache[bc_sym].get(sess_str)
    rows.append({"session": sess_str, "root": root, "sym": dbn_sym, "barchart": bc_sym,
                 "published": pub, **tot,
                 "T_only/pub": (tot["T_only"] / pub) if pub else None,
                 "T_all/pub": (tot["T_all"] / pub) if pub else None,
                 "T+F/pub": (tot["T_plus_F"] / pub) if pub else None})
    print(rows[-1])

out = pd.DataFrame(rows)
out.to_csv("C:/Users/chris/clee/ARBS-r0/r0_leadlag/cache/recon_volume.csv", index=False)
print()
print(out.to_string(index=False))
