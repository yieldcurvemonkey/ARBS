r"""Deep-walk the priority RATES families to their true leaves.

The depth-3 walk was structurally complete but stopped one level short for the
deeper families: RATES.BASIS_SWAPS.3S1S_BASIS.AUD.3M looks like a leaf but still
needs a maturity. This continues downward, for the desk's priority list only:

    VOL, BOND, INFLATION, INVOICESPREAD, OIS_INVOICESPREAD, MIDCURVES,
    OIS_MEETING, SPREAD_OPTIONS, XCCY_OIS_SWAP, REPO

OIS and TSY are already complete and verified, so they are not re-walked.

Leaf detection samples up to 3 children (first/middle/last) rather than expanding
all of them: a 44-tenor list would otherwise cost 44 selections to learn nothing.
Cross-product sub-types (CURVES/BFLY/FWD/ROLL_CARRY) are recorded but not expanded.

Read-only wrt the workbook. Checkpointed after every node; resumable.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fb_harvest2 import HWND, Browser, items, nm  # noqa: E402

TARGETS = [
    "RATES.VOL", "RATES.BOND", "RATES.INFLATION", "RATES.INVOICESPREAD",
    "RATES.OIS_INVOICESPREAD", "RATES.MIDCURVES", "RATES.OIS_MEETING",
    "RATES.SPREAD_OPTIONS", "RATES.XCCY_OIS_SWAP", "RATES.REPO",
]
NO_EXPAND = ("BFLY", "CURVES", "ROLL_CARRY", "FWD")
MAX_DEPTH = 7

# dag_rates_deep.json is a strict superset of dag_rates.json (2,517 nodes vs 2,101,
# zero missing, zero differing children), so only the deep file is committed.
# fb_harvest2.py still writes dag_rates.json when the structural walk is re-run.
_HERE = pathlib.Path(__file__).parent
SRC = next((p for p in (_HERE / "dag_rates_deep.json", _HERE / "dag_rates.json")
            if p.exists()), _HERE / "dag_rates.json")
OUT = pathlib.Path(__file__).parent / "dag_rates_deep.json"

doc = json.loads(SRC.read_text())
tree: dict[str, dict] = dict(doc["tree"])
if OUT.exists():
    try:
        tree.update(json.loads(OUT.read_text())["tree"])
    except Exception:
        pass
stats = {"selects": 0, "nodes": 0, "leaves": 0}


def save():
    OUT.write_text(json.dumps({"tree": tree, "stats": stats}, indent=1))


def sample_idx(n, k=3):
    return list(range(n)) if n <= k else sorted({0, n // 2, n - 1})


def main():
    br = Browser(HWND)
    t0 = time.time()

    q = collections.deque()
    for fam in TARGETS:
        q.append((["RATES", fam], 1))

    while q:
        path, depth = q.pop()          # DFS: preserves selection prefix
        key = " / ".join(path)
        node = tree.get(key)

        if node and "children" in node and node.get("deep_done"):
            kids = node["children"]
        elif node and "children" in node and node.get("leaf_level"):
            continue
        else:
            kids = br.select_path(path)
            stats["nodes"] += 1
            if kids is None or isinstance(kids, dict):
                tree[key] = {"depth": depth, "error": "unreachable_or_stale"}
                save()
                continue
            tree[key] = {"depth": depth, "n": len(kids), "children": kids}
            if not kids:
                tree[key]["leaf"] = True
                stats["leaves"] += 1
                save()
                continue
            # is this level already the leaf level?
            leaf_level = True
            if depth < MAX_DEPTH and not any(path[-1].endswith(s) for s in NO_EXPAND):
                for i in sample_idx(len(kids)):
                    probe = br.select_path(path + [kids[i]], tries=3)
                    if probe and not isinstance(probe, dict):
                        leaf_level = False
                        break
            tree[key]["leaf_level"] = leaf_level
            tree[key]["deep_done"] = True
            save()
            if stats["nodes"] % 10 == 0 or depth <= 2:
                print(f"{'  '*depth}{path[-1]}  n={len(kids)} leaf={leaf_level} "
                      f"[{stats['nodes']} nodes {time.time()-t0:.0f}s]", flush=True)
            if leaf_level:
                stats["leaves"] += len(kids)
                continue

        if depth >= MAX_DEPTH or any(path[-1].endswith(s) for s in NO_EXPAND):
            continue
        for c in reversed(kids):   # reversed so DFS still visits in natural order
            q.append((path + [c], depth + 1))

    save()
    print(f"\nDONE {time.time()-t0:.0f}s nodes={stats['nodes']} leaves={stats['leaves']}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
