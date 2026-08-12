"""R0 / Y-side probe 2 -- AGGRESSOR SIDE CONVENTION.

Three independent internal checks on one liquid outright (UBM6, 2026-05-11):

  CHECK A  match-event anatomy: within one ts_event, is T's side opposite the
           F records' sides?  Is T.order_id a resting order we have seen added?
  CHECK B  book reconstruction from A/C/M/F only.  For each T, compare the
           trade price with the best bid / best ask standing immediately
           before the event.  A trade at the offer is buyer-initiated.
  CHECK C  F.side vs the side the same order_id was ADDED with.  If they agree,
           F.side is the RESTING side, hence T.side (opposite) is the aggressor.
"""
import zipfile, sys
from collections import defaultdict
import numpy as np
import databento as db

ZIP = "D:/ub_mbo/GLBX-20260808-PF3KREYS4D.zip"
MEMBER = "glbx-mdp3-20260511.mbo.dbn.zst"
SYM = "UBM6"

z = zipfile.ZipFile(ZIP)
store = db.DBNStore.from_bytes(z.read(MEMBER))
mp = store.metadata.mappings
iid = int(mp[SYM][0]["symbol"])
print(f"{SYM} instrument_id={iid}")

arrs = [a for a in store.to_ndarray(count=5_000_000)]
full = np.concatenate(arrs)
del arrs
sub = full[full["instrument_id"] == iid]
print("records for", SYM, len(sub))
# DBN guarantees ts_recv order; within an event keep original order
order = np.argsort(sub["ts_recv"], kind="stable")
sub = sub[order]

acts = sub["action"]
sides = sub["side"]

# ---------------- CHECK A : event anatomy ----------------
print("\n===== CHECK A : match-event anatomy =====")
tidx = np.flatnonzero(acts == b"T")
shown = 0
for i in tidx:
    ev = sub["ts_event"][i]
    lo = i
    while lo > 0 and sub["ts_event"][lo - 1] == ev:
        lo -= 1
    hi = i
    while hi + 1 < len(sub) and sub["ts_event"][hi + 1] == ev:
        hi += 1
    blk = sub[lo : hi + 1]
    if (blk["action"] == b"F").sum() < 2:
        continue
    print(f"--- event ts_event={ev} n={len(blk)}")
    for r in blk:
        print(
            f"    seq={r['sequence']} act={r['action'].decode()} side={r['side'].decode()}"
            f" px={r['price']/1e9:.9f} sz={r['size']} oid={r['order_id']} flags={r['flags']}"
        )
    shown += 1
    if shown >= 4:
        break

# ---------------- CHECK C : F.side vs the side of the ADD ----------------
print("\n===== CHECK C : F.side vs the side the order was ADDED with =====")
add_side = {}
agree = disagree = unknown = 0
t_oid_resting = 0
t_oid_unknown = 0
t_oid_zero = 0
for r in sub:
    a = r["action"]
    oid = int(r["order_id"])
    if a == b"A":
        add_side[oid] = r["side"]
    elif a == b"F":
        if oid in add_side:
            if add_side[oid] == r["side"]:
                agree += 1
            else:
                disagree += 1
        else:
            unknown += 1
    elif a == b"M":
        add_side[oid] = r["side"]
    elif a == b"T":
        if oid == 0:
            t_oid_zero += 1
        elif oid in add_side:
            t_oid_resting += 1
        else:
            t_oid_unknown += 1
print(f"  F.side == side-of-Add : agree={agree:,}  disagree={disagree:,}  oid-not-seen={unknown:,}")
print(f"  T.order_id : zero={t_oid_zero:,}  matches-a-resting-order={t_oid_resting:,}  never-added={t_oid_unknown:,}")

# ---------------- CHECK B : book reconstruction ----------------
print("\n===== CHECK B : trade price vs standing best bid/ask =====")
# book: order_id -> (side, price, size); price levels aggregated lazily
bidsz = defaultdict(int)  # price -> total size
asksz = defaultdict(int)
book = {}


def _rm(oid):
    o = book.pop(oid, None)
    if o is None:
        return
    s, p, sz = o
    d = bidsz if s == b"B" else asksz
    d[p] -= sz
    if d[p] <= 0:
        d.pop(p, None)


def _add(oid, s, p, sz):
    if sz <= 0 or s not in (b"B", b"A"):
        return
    book[oid] = (s, p, sz)
    (bidsz if s == b"B" else asksz)[p] += sz


def best():
    bb = max(bidsz) if bidsz else None
    ba = min(asksz) if asksz else None
    return bb, ba


res = {"at_ask": defaultdict(int), "at_bid": defaultdict(int), "inside": defaultdict(int),
       "outside": defaultdict(int), "nobook": defaultdict(int)}
res_vol = {"at_ask": defaultdict(int), "at_bid": defaultdict(int)}
n_seen = 0
i = 0
N = len(sub)
while i < N:
    ev = sub["ts_event"][i]
    j = i
    while j + 1 < N and sub["ts_event"][j + 1] == ev:
        j += 1
    blk = sub[i : j + 1]
    has_T = (blk["action"] == b"T").any()
    if has_T:
        bb, ba = best()
        for r in blk[blk["action"] == b"T"]:
            p = int(r["price"])
            sd = r["side"].decode()
            v = int(r["size"])
            if bb is None or ba is None or bb >= ba:
                res["nobook"][sd] += 1
            elif p == ba:
                res["at_ask"][sd] += 1
                res_vol["at_ask"][sd] += v
            elif p == bb:
                res["at_bid"][sd] += 1
                res_vol["at_bid"][sd] += v
            elif bb < p < ba:
                res["inside"][sd] += 1
            else:
                res["outside"][sd] += 1
            n_seen += 1
    # apply the event to the book
    for r in blk:
        a = r["action"]
        oid = int(r["order_id"])
        if a == b"R":
            book.clear(); bidsz.clear(); asksz.clear()
        elif a == b"A":
            _add(oid, r["side"], int(r["price"]), int(r["size"]))
        elif a == b"C":
            o = book.get(oid)
            if o is not None:
                s, p, sz = o
                _rm(oid)
                _add(oid, s, p, sz - int(r["size"]))
        elif a == b"M":
            _rm(oid)
            _add(oid, r["side"], int(r["price"]), int(r["size"]))
        elif a == b"F":
            o = book.get(oid)
            if o is not None:
                s, p, sz = o
                _rm(oid)
                _add(oid, s, p, sz - int(r["size"]))
    i = j + 1

print(f"  classified {n_seen:,} T records")
for k in ("at_ask", "at_bid", "inside", "outside", "nobook"):
    print(f"   {k:8s} " + "  ".join(f"side={s}:{c:,}" for s, c in sorted(res[k].items())))
print("  volume at_ask by side:", dict(res_vol["at_ask"]))
print("  volume at_bid by side:", dict(res_vol["at_bid"]))
