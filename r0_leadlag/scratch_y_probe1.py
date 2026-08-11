"""R0 / Y-side probe 1: DBN MBO structure, action mix, T-vs-F volume.

Runs on one SMALL day member so it is fast. No writes outside r0_leadlag/.
"""
import sys, time, zipfile
import numpy as np
import databento as db

ZIP = "D:/ub_mbo/GLBX-20260808-PF3KREYS4D.zip"
MEMBER = sys.argv[1] if len(sys.argv) > 1 else "glbx-mdp3-20260511.mbo.dbn.zst"

t0 = time.time()
z = zipfile.ZipFile(ZIP)
raw = z.read(MEMBER)
print(f"member bytes (compressed) = {len(raw):,}  read in {time.time()-t0:.1f}s")

store = db.DBNStore.from_bytes(raw)
print("dbn version", store.metadata.version, "schema", store.metadata.schema)

t0 = time.time()
n = 0
act_counts = {}
side_counts = {}
# per-action volume
act_vol = {}
batches = 0
arrs = []
for arr in store.to_ndarray(count=2_000_000):
    batches += 1
    n += len(arr)
    a = arr["action"]
    s = arr["side"]
    sz = arr["size"].astype(np.int64)
    for code in np.unique(a):
        m = a == code
        c = code.decode() if isinstance(code, bytes) else chr(code)
        act_counts[c] = act_counts.get(c, 0) + int(m.sum())
        act_vol[c] = act_vol.get(c, 0) + int(sz[m].sum())
    for code in np.unique(s):
        c = code.decode() if isinstance(code, bytes) else chr(code)
        side_counts[c] = side_counts.get(c, 0) + int((s == code).sum())
    arrs.append(arr)
dt = time.time() - t0
print(f"records = {n:,} in {dt:.1f}s -> {n/max(dt,1e-9):,.0f} rec/s, batches={batches}")
print("dtype fields:", arrs[0].dtype.names)
print("action counts:", act_counts)
print("action volume:", act_vol)
print("side counts:", side_counts)

full = np.concatenate(arrs)
del arrs

# cross-tab action x side  (trades only)
for act in ("T", "F"):
    m = full["action"] == act.encode()
    if not m.any():
        continue
    sub = full[m]
    print(f"--- action {act}: n={len(sub):,} vol={int(sub['size'].sum()):,}")
    for code in np.unique(sub["side"]):
        mm = sub["side"] == code
        print(f"      side={code.decode() if isinstance(code,bytes) else chr(code)} n={int(mm.sum()):,} vol={int(sub['size'][mm].sum()):,}")
    print("      order_id==0 frac:", float((sub["order_id"] == 0).mean()))
    print("      flags sample:", np.unique(sub["flags"])[:20])

# instrument ids seen in trades
mT = full["action"] == b"T"
ids, cnts = np.unique(full["instrument_id"][mT], return_counts=True)
print("distinct instrument ids in T:", len(ids))
mp = store.metadata.mappings
id2sym = {}
for sym, ents in mp.items():
    for e in ents:
        id2sym[int(e["symbol"])] = sym
for i, c in sorted(zip(ids.tolist(), cnts.tolist()), key=lambda x: -x[1]):
    vol = int(full["size"][mT & (full["instrument_id"] == i)].sum())
    print(f"   {i} {id2sym.get(i,'?'):<20} n={c:,} vol={vol:,}")
