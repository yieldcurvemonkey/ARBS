"""R0 / Y-side probe 4: SR3 and ZQ structure.

  - spread/combo share of traded volume
  - side=N share on OUTRIGHT trade records
  - T volume vs F volume (double-count anatomy holds?)
  - the outright universe and its resolved expiry ordering
"""
import zipfile, time, re, sys
import numpy as np
import pandas as pd
import databento as db

MONTH = {"F":1,"G":2,"H":3,"J":4,"K":5,"M":6,"N":7,"Q":8,"U":9,"V":10,"X":11,"Z":12}


def resolve_year(digit: int, ref_year: int) -> int:
    """Single-digit CME year -> nearest year >= ref_year with that last digit."""
    base = ref_year - (ref_year % 10) + digit
    if base < ref_year:
        base += 10
    return base


def parse_outright(sym: str, ref_year: int):
    m = re.fullmatch(r"([A-Z0-9]{2,3})([FGHJKMNQUVXZ])(\d)", sym)
    if not m:
        return None
    root, mc, yd = m.group(1), m.group(2), int(m.group(3))
    return root, resolve_year(yd, ref_year), MONTH[mc]


CASES = [
    ("D:/sr3_mbo/GLBX-20260807-HF783HNWSU.zip", "glbx-mdp3-20260707.mbo.dbn.zst", "SR3"),
    ("D:/zq_mbo/GLBX-20260810-6NH9MMQX3E.zip", "glbx-mdp3-20260707.mbo.dbn.zst", "ZQ"),
]

for ZIP, MEMBER, ROOT in CASES:
    t0 = time.time()
    z = zipfile.ZipFile(ZIP)
    raw = z.read(MEMBER)
    print(f"\n########## {ROOT} {MEMBER} compressed={len(raw)/1e9:.2f} GB read {time.time()-t0:.0f}s")
    store = db.DBNStore.from_bytes(raw)
    id2sym = {}
    for sym, ents in store.metadata.mappings.items():
        for e in ents:
            id2sym[int(e["symbol"])] = sym

    t0 = time.time()
    n = 0
    tid, tsz, tsd = [], [], []
    fvol = 0
    tvol = 0
    for arr in store.to_ndarray(count=4_000_000):
        n += len(arr)
        mT = arr["action"] == b"T"
        mF = arr["action"] == b"F"
        fvol += int(arr["size"][mF].sum())
        tvol += int(arr["size"][mT].sum())
        t = arr[mT]
        tid.append(t["instrument_id"].copy())
        tsz.append(t["size"].astype("int64"))
        tsd.append(t["side"].copy())
    tid = np.concatenate(tid); tsz = np.concatenate(tsz); tsd = np.concatenate(tsd)
    print(f"  records={n:,} in {time.time()-t0:.0f}s  T_vol={tvol:,} F_vol={fvol:,} F/T={fvol/max(tvol,1):.4f}")

    df = pd.DataFrame({"iid": tid, "sz": tsz, "side": [s.decode() for s in tsd]})
    df["sym"] = df["iid"].map(id2sym).fillna("?")
    df["is_combo"] = df["sym"].str.contains(r"[-:]", regex=True)
    print("  combo volume share: %.4f  (combo=%s outright=%s)" % (
        df.loc[df.is_combo, "sz"].sum() / df["sz"].sum(),
        f"{df.loc[df.is_combo,'sz'].sum():,}", f"{df.loc[~df.is_combo,'sz'].sum():,}"))
    out = df[~df.is_combo]
    print("  OUTRIGHT side mix by volume:")
    print(out.groupby("side")["sz"].agg(["sum", "size"]).assign(
        share=lambda d: d["sum"] / out["sz"].sum()).to_string())

    # outright universe with resolved expiry
    vol = out.groupby("sym")["sz"].sum().sort_values(ascending=False)
    rows = []
    for s, v in vol.items():
        p = parse_outright(s, 2026)
        rows.append((s, p[1] if p else None, p[2] if p else None, int(v)))
    u = pd.DataFrame(rows, columns=["sym", "yr", "mo", "vol"])
    u["quarterly"] = u["mo"].isin([3, 6, 9, 12])
    u = u.sort_values(["yr", "mo"])
    print(f"  outright contracts traded: {len(u)}  quarterly={int(u.quarterly.sum())}")
    print(u.head(30).to_string(index=False))
    if ROOT == "SR3":
        q = u[u.quarterly].sort_values(["yr", "mo"]).head(14)
        print("  first 14 quarterlies by expiry order:")
        print(q.to_string(index=False))
        print("  serial-month outright volume:", int(u.loc[~u.quarterly, "vol"].sum()),
              "of", int(u["vol"].sum()))
