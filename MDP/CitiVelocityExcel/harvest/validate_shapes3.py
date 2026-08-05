r"""Validate shapes2.json with a PATH-CONSISTENT generator.

validate_shapes2 stored the vocabulary at each level but lost which path those
levels belonged to, so sampling could pick OTM_RFR at level 0 with BLACK/DAILY at
levels 1-2 - a combination that only exists under ATM. VOL scored 17%; XCCY scored
100% only because it is homogeneous.

Correct rule, applied recursively from each recorded node N:

    tags(N) = for each option O of N:
                 if N/O was recorded  -> seg(O) + "." + tags(N/O)
                 else                 -> seg(O) + "." + tags(first recorded child)

i.e. siblings that were not expanded inherit the shape of the sibling that was.
That is the working assumption at depths below the fan-out, and it keeps every
generated tag on a real path.
"""

import json
import pathlib
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
SAMPLES_PER_NODE = 3
CONTROLS = ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y"]

tree = json.loads((SCRATCH / "shapes2.json").read_text())
kids = defaultdict(list)
for k in tree:
    parts = k.split(" / ")
    if len(parts) > 1:
        kids[" / ".join(parts[:-1])].append(k)


def seg(full, parent):
    return full[len(parent) + 1:] if full.startswith(parent + ".") else full


def suffixes(key, rnd, budget=4):
    """Random well-formed suffixes below `key`, following real paths."""
    node = tree.get(key)
    if node is None or node.get("leaf"):
        return [""]
    opts = node.get("options")
    if not opts:
        return [""]
    parent = key.split(" / ")[-1]
    recorded = {c.split(" / ")[-1]: c for c in kids.get(key, [])}
    if not recorded:
        return [seg(o, parent) for o in rnd.sample(opts, min(budget, len(opts)))]
    fallback = next(iter(recorded.values()))
    out = []
    for o in rnd.sample(opts, min(budget, len(opts))):
        child_key = recorded.get(o, fallback)
        for s in suffixes(child_key, rnd, budget=1):
            out.append(seg(o, parent) + ("." + s if s else ""))
    return out


def main():
    rnd = random.Random(20260804)
    roots = [k for k in tree if " / ".join(k.split(" / ")[:-1]) not in tree]
    sample = set()
    for r in roots:
        base = r.split(" / ")[-1]
        for s in suffixes(r, rnd, budget=6):
            sample.add(base + "." + s)
    # also sample from every mid-level node so each convention is represented
    for k in tree:
        if tree[k].get("leaf"):
            continue
        base = k.split(" / ")[-1]
        for s in suffixes(k, rnd, budget=SAMPLES_PER_NODE):
            if s:
                sample.add(base + "." + s)

    sample = sorted(sample)
    print(f"generated {len(sample):,} path-consistent tags", flush=True)

    p = Prober(SCRATCH / "shape3_validation.json", batch=15)
    try:
        ctl = p.probe_tshist(CONTROLS)
        bad = [t for t in CONTROLS if ctl[t]["status"] != "valid"]
        if bad:
            print("CONTROLS FAILED:", [(t, ctl[t]) for t in bad]); return 1
        print("controls pass\n", flush=True)
        res = p.probe_tshist(sample)
    finally:
        p.close()

    fam = defaultdict(Counter)
    for t in sample:
        fam[t.split(".")[1]][res.get(t, {}).get("status")] += 1
    print(f'{"FAMILY":<18}{"valid":>7}{"empty":>7}{"failed":>8}   shape-ok')
    for f, c in sorted(fam.items()):
        tot = sum(c.values()); ok = c["valid"] + c["empty"]
        print(f"  {f:<16}{c['valid']:>7}{c['empty']:>7}{c['failed']:>8}   {ok/tot*100:5.0f}%")

    vm = defaultdict(Counter)
    for t in sample:
        p_ = t.split(".")
        if p_[1] == "VOL" and len(p_) > 3:
            vm[p_[3]][res.get(t, {}).get("status")] += 1
    if vm:
        print("\nVOL by measure:")
        for m, c in sorted(vm.items()):
            tot = sum(c.values()); ok = c["valid"] + c["empty"]
            print(f"  {m:<16} valid={c['valid']:<4} empty={c['empty']:<4} "
                  f"failed={c['failed']:<4} shape-ok {ok/tot*100:3.0f}%")

    good = sorted(t for t in sample if res.get(t, {}).get("status") in ("valid", "empty"))
    (SCRATCH / "shape3_results.json").write_text(json.dumps(
        {"sampled": len(sample), "shape_ok": len(good), "tags": good}, indent=1))
    print(f"\nshape-correct: {len(good):,}/{len(sample):,} = {len(good)/len(sample)*100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
