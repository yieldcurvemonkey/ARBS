"""R0 / Y-side probe 9: repeat the book-reconstruction aggressor test on SR3 and ZQ,
where side='N' is ~10% of outright volume (vs 0.55% in ub).

Also classifies where the side='N' prints sit relative to the standing touch.
"""
import zipfile, glob, sys
from collections import defaultdict
import numpy as np
import databento as db

CASES = [("sr3", "glbx-mdp3-20260707.mbo.dbn.zst", "SR3Z6"),
         ("zq", "glbx-mdp3-20260707.mbo.dbn.zst", "ZQQ6"),
         ("zn", "glbx-mdp3-20260715.mbo.dbn.zst", "ZNU6")]

for root, member, sym in CASES:
    zp = next(c for c in sorted(glob.glob(f"D:/{root}_mbo/*.zip"))
              if member in zipfile.ZipFile(c).namelist())
    with zipfile.ZipFile(zp) as z:
        store = db.DBNStore.from_bytes(z.read(member))
    iid = next(int(e["symbol"]) for s, ents in store.metadata.mappings.items()
               if s == sym for e in ents)
    parts = []
    for arr in store.to_ndarray(count=4_000_000):
        m = arr["instrument_id"] == iid
        if m.any():
            parts.append(arr[m])
    sub = np.concatenate(parts)
    sub = sub[np.argsort(sub["ts_recv"], kind="stable")]

    bidsz, asksz, book = defaultdict(int), defaultdict(int), {}

    def _rm(o):
        v = book.pop(o, None)
        if v is None:
            return
        s, p, z_ = v
        d = bidsz if s == b"B" else asksz
        d[p] -= z_
        if d[p] <= 0:
            d.pop(p, None)

    def _add(o, s, p, z_):
        if z_ <= 0 or s not in (b"B", b"A"):
            return
        book[o] = (s, p, z_)
        (bidsz if s == b"B" else asksz)[p] += z_

    res = defaultdict(lambda: defaultdict(int))
    resv = defaultdict(lambda: defaultdict(int))
    i, N = 0, len(sub)
    while i < N:
        ev = sub["ts_event"][i]
        j = i
        while j + 1 < N and sub["ts_event"][j + 1] == ev:
            j += 1
        blk = sub[i:j + 1]
        if (blk["action"] == b"T").any():
            bb = max(bidsz) if bidsz else None
            ba = min(asksz) if asksz else None
            for r in blk[blk["action"] == b"T"]:
                p, sd, v = int(r["price"]), r["side"].decode(), int(r["size"])
                if bb is None or ba is None or bb >= ba:
                    k = "nobook"
                elif p == ba:
                    k = "at_ask"
                elif p == bb:
                    k = "at_bid"
                elif bb < p < ba:
                    k = "inside"
                else:
                    k = "outside"
                res[k][sd] += 1
                resv[k][sd] += v
        for r in blk:
            a, o = r["action"], int(r["order_id"])
            if a == b"R":
                book.clear(); bidsz.clear(); asksz.clear()
            elif a == b"A":
                _add(o, r["side"], int(r["price"]), int(r["size"]))
            elif a in (b"C", b"F"):
                v = book.get(o)
                if v is not None:
                    s, p, z_ = v
                    _rm(o)
                    _add(o, s, p, z_ - int(r["size"]))
            elif a == b"M":
                _rm(o)
                _add(o, r["side"], int(r["price"]), int(r["size"]))
        i = j + 1

    tot = sum(sum(d.values()) for d in res.values())
    print(f"\n### {sym} {member}: {tot:,} T records classified")
    for k in ("at_ask", "at_bid", "inside", "outside", "nobook"):
        if res[k]:
            print(f"   {k:8s} " + "  ".join(f"side={s}:{c:,}" for s, c in sorted(res[k].items())))
    ask_B = res["at_ask"].get("B", 0); ask_A = res["at_ask"].get("A", 0)
    bid_A = res["at_bid"].get("A", 0); bid_B = res["at_bid"].get("B", 0)
    tot_touch = ask_B + ask_A + bid_A + bid_B
    if tot_touch:
        print(f"   aggressor convention holds on {(ask_B+bid_A)/tot_touch:.6f} of "
              f"{tot_touch:,} signed at-touch prints "
              f"(counterexamples: at_ask&side=A {ask_A}, at_bid&side=B {bid_B})")
    nN = sum(d.get("N", 0) for d in res.values())
    print(f"   side='N' prints: {nN:,} -> " +
          ", ".join(f"{k}:{res[k].get('N',0)}" for k in
                    ("at_ask", "at_bid", "inside", "outside", "nobook") if res[k].get("N", 0)))
