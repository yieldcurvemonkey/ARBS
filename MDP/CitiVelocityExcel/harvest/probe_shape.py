r"""Learn a family's per-BRANCH shape cheaply.

Pooling vocabulary per level across a whole family is wrong: RATES.VOL's level-4
vocabulary mixes expiries (1M, 3M) with vol conventions (NORMAL, BLACK), because
each measure has its own shape. Generating from the pooled vocabulary produced
2,163 tags of which zero were valid.

So: descend ONE representative path per branch, recording the FULL child list at
each level. That yields the branch's segment count and per-level vocabulary for
~6 selections per branch instead of walking the whole subtree.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fb_harvest2 import HWND, Browser  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
OUT = SCRATCH / "shapes.json"

# (family, representative level-2 node) -> branch out at level 3
JOBS = [
    ("RATES.VOL", "RATES.VOL.USD"),
    ("RATES.MIDCURVES", "RATES.MIDCURVES.USD_SOFR"),
    ("RATES.SPREAD_OPTIONS", None),
    ("RATES.INVOICESPREAD", None),
]
MAX_DEPTH = 9


def descend(br: Browser, path: list[str]) -> list[dict]:
    """Follow first-child links, recording the full option list at each level."""
    levels = []
    cur = list(path)
    for _ in range(MAX_DEPTH):
        kids = br.select_path(cur)
        if kids is None or isinstance(kids, dict) or not kids:
            break
        levels.append({"depth": len(cur), "parent": cur[-1],
                       "n": len(kids), "options": kids})
        cur = cur + [kids[0]]
    return levels


def main():
    br = Browser(HWND)
    out = {}
    if OUT.exists():
        try:
            out = json.loads(OUT.read_text())
        except Exception:
            pass

    for fam, rep in JOBS:
        base = ["RATES", fam]
        kids = br.select_path(base)
        if not kids or isinstance(kids, dict):
            print(f"{fam}: unreachable"); continue
        # branch on every level-3 child of the representative node (or of the family)
        parent = rep if rep in kids else None
        branch_roots = [rep] if parent else kids
        print(f"\n=== {fam}  branching over {len(branch_roots)} node(s) ===", flush=True)
        for root in branch_roots:
            sub = br.select_path(base + [root])
            if not sub or isinstance(sub, dict):
                continue
            for measure in sub:
                path = base + [root, measure]
                levels = descend(br, path)
                key = measure
                out[key] = {"path": path, "levels": levels,
                            "segments": len(path[-1].split(".")) + len(levels)}
                shape = " -> ".join(f"{l['n']}" for l in levels)
                print(f"  {measure:<42} depth+{len(levels)}  [{shape}]", flush=True)
                for l in levels:
                    print(f"      L{l['depth']}: {l['options'][:6]}"
                          f"{' …' if l['n'] > 6 else ''}", flush=True)
                OUT.write_text(json.dumps(out, indent=1))
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
