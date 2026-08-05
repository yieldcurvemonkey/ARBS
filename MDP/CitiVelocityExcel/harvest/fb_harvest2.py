r"""Harvest the Citi Velocity RATES tag DAG from the Function Builder DATA BROWSER.

Breadth-first with a depth cap, priority-ordered so the linear-rates families land
first. DFS was abandoned because RATES.MBS is combinatorially explosive (BFLY over
coupon x coupon x coupon) and starved everything else.

Cross-product subtrees (BFLY / CURVES / ROLL_CARRY) are recorded one level deep but
not expanded: their legs are drawn from the same tenor set as PAR, so they are
generated, not enumerated.

Read-only wrt the workbook - only the browser selection changes, Insert is never
pressed. Checkpointed after every node, so it can be killed and resumed.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo

HWND = int(sys.argv[1]) if len(sys.argv) > 1 else 3609176
MAX_DEPTH = int(sys.argv[2]) if len(sys.argv) > 2 else 4
SETTLE = 0.3
SETTLE_TRIES = 10
PROBE_TRIES = 3

OUT = pathlib.Path(__file__).parent / "dag_rates.json"

# expanded first - the linear/vol rates complex the work actually needs
PRIORITY = [
    "RATES.OIS", "RATES.SWAP_LIBOR", "RATES.TSY", "RATES.SOV", "RATES.VOL",
    "RATES.FUTURES", "RATES.OIS_MEETING", "RATES.INVOICESPREAD",
    "RATES.OIS_INVOICESPREAD", "RATES.BASIS_SWAPS", "RATES.XCCY_SWAP",
    "RATES.XCCY_OIS_SWAP", "RATES.FRA", "RATES.FRA_OIS", "RATES.INFLATION",
    "RATES.MONEY_MARKETS", "RATES.MIDCURVES", "RATES.REPO", "RATES.BENCH_RATES",
    "RATES.SPREAD_OPTIONS", "RATES.BOND", "RATES.SSA", "RATES.SSA_CS",
    "RATES.FORECAST", "RATES.LIQUIDITY_IDX", "RATES.FLOWS",
]
# recorded but not expanded: pure cross products of a tenor/coupon axis
NO_EXPAND = ("BFLY", "CURVES", "ROLL_CARRY")

tree: dict[str, dict] = {}
stats = {"selects": 0, "nodes": 0}
stale_tries: dict[str, int] = {}


def ct(c):
    try:
        return c.element_info.control_type
    except Exception:
        return "?"


def nm(c):
    try:
        return (c.element_info.name or "").replace("\n", " ")
    except Exception:
        return ""


def find_lists(w, depth=0, out=None):
    if out is None:
        out = []
    if depth > 12:
        return out
    try:
        if ct(w) == "List":
            out.append(w)
        kids = w.children()
    except Exception:
        return out
    for k in kids:
        find_lists(k, depth + 1, out)
    return out


def items(lst):
    try:
        return [x for x in lst.children() if ct(x) == "ListItem"]
    except Exception:
        return []


def save():
    OUT.write_text(json.dumps({"tree": tree, "stats": stats}, indent=1))


class Browser:
    def __init__(self, hwnd):
        self.w = UIAWrapper(UIAElementInfo(hwnd))
        self.current: list[str] = []

    def lists(self):
        return find_lists(self.w)

    def select_path(self, path, tries=SETTLE_TRIES):
        common = 0
        for a, b in zip(self.current, path):
            if a != b:
                break
            common += 1
        for level, want in enumerate(path):
            if level < common:
                continue
            ls = self.lists()
            if level >= len(ls):
                self.current = path[:level]
                return None
            tgt = next((o for o in items(ls[level]) if nm(o) == want), None)
            if tgt is None:
                self.current = path[:level]
                return None
            try:
                tgt.select()
                stats["selects"] += 1
            except Exception:
                self.current = path[:level]
                return None
            # Wait for the child list to actually REFRESH, not merely exist.
            # Without this the previous node's children are read back (observed:
            # RATES.SPREAD_OPTIONS returning RATES.REPO.* ). Children are always
            # named "<parent>.<something>", which is a strong staleness check.
            for _ in range(tries):
                time.sleep(SETTLE)
                ls_now = self.lists()
                if len(ls_now) <= level + 1:
                    continue
                names = [nm(x) for x in items(ls_now[level + 1])]
                if names and all(n.startswith(want + ".") for n in names):
                    break
        self.current = list(path)
        ls = self.lists()
        if len(ls) <= len(path):
            return []
        kids = [nm(x) for x in items(ls[len(path)])]
        parent = path[-1]
        if kids and not all(k.startswith(parent + ".") for k in kids):
            # settled on something that is not this node's children
            return {"__stale__": kids}
        return kids


def main():
    if OUT.exists():
        try:
            tree.update(json.loads(OUT.read_text())["tree"])
            print(f"resumed {len(tree)} nodes", flush=True)
        except Exception:
            pass

    br = Browser(HWND)
    t0 = time.time()

    root = br.select_path(["RATES"])
    if not root:
        print("could not open RATES")
        return 1
    tree["RATES"] = {"depth": 0, "n": len(root), "children": root}
    save()
    print(f"RATES: {len(root)} families", flush=True)

    order = [f for f in PRIORITY if f in root] + [f for f in root if f not in PRIORITY]
    q = collections.deque([(["RATES", f], 1) for f in order])

    while q:
        path, depth = q.popleft()
        key = " / ".join(path)
        if key in tree and "children" in tree[key]:
            kids = tree[key]["children"]
        else:
            kids = br.select_path(path)
            stats["nodes"] += 1
            if kids is None:
                tree[key] = {"depth": depth, "error": "unreachable"}
                save()
                continue
            if isinstance(kids, dict):
                n = stale_tries[key] = stale_tries.get(key, 0) + 1
                if n <= 3:
                    # force a full re-descent: current == path would otherwise
                    # short-circuit the re-selection and re-read the same stale list
                    br.current = []
                    q.append((path, depth))
                    print(f"{'  '*depth}{path[-1]}  STALE retry {n}", flush=True)
                    continue
                tree[key] = {"depth": depth, "error": "stale_read",
                             "saw": kids["__stale__"][:6]}
                save()
                print(f"{'  '*depth}{path[-1]}  STALE giving up", flush=True)
                continue
            tree[key] = {"depth": depth, "n": len(kids), "children": kids}
            save()
            print(f"{'  '*depth}{path[-1]}  n={len(kids)}  "
                  f"[{stats['nodes']} nodes, {time.time()-t0:.0f}s]", flush=True)
        if depth >= MAX_DEPTH or not kids:
            continue
        if any(path[-1].endswith(s) for s in NO_EXPAND):
            continue
        for c in kids:
            q.append((path + [c], depth + 1))

    save()
    print(f"\nDONE {time.time()-t0:.0f}s nodes={stats['nodes']} -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
