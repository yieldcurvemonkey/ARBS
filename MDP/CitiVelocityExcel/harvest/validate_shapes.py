r"""Validate the per-BRANCH shapes learned by probe_shape.py.

Exhaustive enumeration is NOT the goal and is not affordable: VOL alone is
~23,000 tags for USD and ~250,000 across 11 currencies, which at 15 tags per
~2s call is ~9 hours. The grammar is the deliverable; a notebook generates the
one tag it wants and CVTSHIST answers immediately.

So this samples each branch's cross product to prove the shape is right.
"""

import itertools
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
PER_BRANCH = 8
CONTROLS = ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y"]


def last_seg(full, parent):
    return full[len(parent) + 1:] if full.startswith(parent + ".") else full


def main():
    shapes = json.loads((SCRATCH / "shapes.json").read_text())
    rnd = random.Random(20260804)

    sample, sizes = [], {}
    for branch, info in shapes.items():
        levels = info["levels"]
        if not levels:
            continue
        # vocabulary of each level, as bare segments
        vocabs = []
        for lv in levels:
            parent = lv["parent"]
            vocabs.append([last_seg(o, parent) for o in lv["options"]])
        sizes[branch] = 1
        for v in vocabs:
            sizes[branch] *= len(v)
        picks = set()
        for _ in range(PER_BRANCH * 3):
            if len(picks) >= PER_BRANCH:
                break
            picks.add(branch + "." + ".".join(rnd.choice(v) for v in vocabs))
        sample += sorted(picks)

    sample = sorted(set(sample))
    print(f"{len(shapes)} branches, cross products total {sum(sizes.values()):,}")
    print(f"sampling {len(sample)} tags ({PER_BRANCH} per branch)\n")

    p = Prober(SCRATCH / "shape_validation.json", batch=15)
    try:
        ctl = p.probe_tshist(CONTROLS)
        bad = [t for t in CONTROLS if ctl[t]["status"] != "valid"]
        if bad:
            print("CONTROLS FAILED:", [(t, ctl[t]) for t in bad])
            return 1
        print("controls pass\n")
        res = p.probe_tshist(sample)
    finally:
        p.close()

    print(f"{'BRANCH':<44}{'ok':>4}{'/':^3}{'n':<5}{'cross product':>15}")
    good_branches = 0
    for branch in sorted(shapes):
        mine = [t for t in sample if t.startswith(branch + ".")]
        if not mine:
            continue
        ok = [t for t in mine if res.get(t, {}).get("status") == "valid"]
        if ok:
            good_branches += 1
        flag = "" if ok else "   <-- shape wrong"
        print(f"{branch.replace('RATES.',''):<44}{len(ok):>4}{'/':^3}"
              f"{len(mine):<5}{sizes.get(branch,0):>15,}{flag}")
    print(f"\nbranches with a working shape: {good_branches}/{len(shapes)}")
    tot_ok = sum(1 for t in sample if res.get(t, {}).get("status") == "valid")
    print(f"sampled tags valid: {tot_ok}/{len(sample)} = {tot_ok/len(sample)*100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
