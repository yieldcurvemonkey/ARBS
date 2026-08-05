r"""Validate the per-CONVENTION shapes from probe_shape2.py.

shapes2.json is a trie: each node records the full option list at its level, with
the first two levels fanned out completely (so heterogeneous conventions are each
captured) and first-child descent below that.

A "branch" is a root->leaf path. Its grammar is the product of the option lists
along it. That is generated and sampled here; exhaustive enumeration is not the
goal (VOL is ~250k tags) - proving each branch's shape is.
"""

import json
import pathlib
import random
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
PER_BRANCH = 6
CONTROLS = ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y"]


def last_seg(full, parent):
    return full[len(parent) + 1:] if full.startswith(parent + ".") else full


def branches(tree):
    """Every root->leaf path as (branch_root, [vocab_per_level_below_it]).

    The root must be carried down explicitly. Using the leaf's parent path element
    as the base double-counts: that element already contains the chosen segments,
    so tags came out as
      RATES.VOL.USD.ATM.NORMAL.DAILY.1M + .ATM.NORMAL.DAILY.1M.3M
    and 0/1673 validated.
    """
    kids = defaultdict(list)
    for key in tree:
        parts = key.split(" / ")
        if len(parts) > 1:
            kids[" / ".join(parts[:-1])].append(key)

    out = []

    def walk(key, root, levels):
        node = tree[key]
        if node.get("leaf"):
            if levels:
                out.append((root, list(levels)))
            return
        opts = node.get("options")
        if not opts:
            return
        parent = key.split(" / ")[-1]
        vocab = [last_seg(o, parent) for o in opts]
        children = kids.get(key, [])
        if not children:
            out.append((root, levels + [vocab]))
            return
        for c in children:
            walk(c, root, levels + [vocab])

    # roots are the shallowest recorded nodes (their parent key is absent)
    roots = [k for k in tree if " / ".join(k.split(" / ")[:-1]) not in tree]
    for r in roots:
        walk(r, r.split(" / ")[-1], [])
    return out


def main():
    tree = json.loads((SCRATCH / "shapes2.json").read_text())
    brs = branches(tree)
    rnd = random.Random(20260804)

    sample, sizes = [], {}
    for base, levels in brs:
        size = 1
        for v in levels:
            size *= len(v)
        sizes[base] = sizes.get(base, 0) + size
        picks = set()
        for _ in range(PER_BRANCH * 4):
            if len(picks) >= PER_BRANCH:
                break
            picks.add(base + "." + ".".join(rnd.choice(v) for v in levels))
        sample += sorted(picks)

    sample = sorted(set(sample))
    print(f"{len(brs)} branches, combined cross product {sum(sizes.values()):,}")
    print(f"sampling {len(sample)} tags\n", flush=True)

    p = Prober(SCRATCH / "shape2_validation.json", batch=15)
    try:
        ctl = p.probe_tshist(CONTROLS)
        bad = [t for t in CONTROLS if ctl[t]["status"] != "valid"]
        if bad:
            print("CONTROLS FAILED:", [(t, ctl[t]) for t in bad]); return 1
        print("controls pass\n", flush=True)
        res = p.probe_tshist(sample)
    finally:
        p.close()

    per_base = defaultdict(lambda: [0, 0])
    for t in sample:
        base = ".".join(t.split(".")[:5])
        ok = res.get(t, {}).get("status") == "valid"
        per_base[base][ok] += 1

    print(f"{'BRANCH':<52}{'ok':>4}{'/':^3}{'n':<5}{'cross':>12}")
    good = bad_n = 0
    for base in sorted(per_base):
        b, o = per_base[base]
        (good := good + 1) if o else (bad_n := bad_n + 1)
        flag = "" if o else "  <-- shape wrong"
        print(f"{base.replace('RATES.',''):<52}{o:>4}{'/':^3}{o+b:<5}"
              f"{sizes.get(base,0):>12,}{flag}")
    tot_ok = sum(1 for t in sample if res.get(t, {}).get("status") == "valid")
    print(f"\nbranches working: {good}/{good+bad_n}")
    print(f"sampled tags valid: {tot_ok}/{len(sample)} = {tot_ok/len(sample)*100:.0f}%")

    (SCRATCH / "shape2_results.json").write_text(json.dumps(
        {"branches": {k: v for k, v in per_base.items()}, "sizes": sizes}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
