r"""Learn shapes per CONVENTION, not just per measure.

probe_shape.py descended first-child links only, so it learned
RATES.VOL.USD.OTM_RFR.PREMIUM's shape and wrongly applied it to NORMALABSOLUTE -
which has an extra ANNUAL level. Result: OTM/OTM_RFR generated 0/8 valid.

This descends EVERY child at the convention level (one level deeper than before)
before falling back to first-child, so heterogeneous branches are captured.

Targets the families still unverified: VOL, INFLATION, XCCY_OIS_SWAP.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fb_harvest2 import HWND, Browser  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
OUT = SCRATCH / "shapes2.json"
MAX_DEPTH = 9

# (family, level-2 node, how many levels to fan out fully before first-child)
JOBS = [
    ("RATES.VOL", "RATES.VOL.USD", 2),
    ("RATES.INFLATION", None, 2),
    ("RATES.XCCY_OIS_SWAP", "RATES.XCCY_OIS_SWAP.USD", 2),
]


def descend(br, path, fanout, out, depth=0):
    """Record the option list at each level. Fan out fully for `fanout` levels,
    then follow first-child to the bottom."""
    kids = br.select_path(path)
    if kids is None or isinstance(kids, dict) or not kids:
        out[" / ".join(path)] = {"leaf": True, "depth": len(path)}
        return
    out[" / ".join(path)] = {"depth": len(path), "n": len(kids), "options": kids}
    OUT.write_text(json.dumps(out, indent=1))
    if len(path) >= MAX_DEPTH:
        return
    nxt = kids if depth < fanout else kids[:1]
    for k in nxt:
        descend(br, path + [k], fanout, out, depth + 1)


def main():
    br = Browser(HWND)
    out = {}
    if OUT.exists():
        try:
            out = json.loads(OUT.read_text())
        except Exception:
            pass
    for fam, rep, fanout in JOBS:
        base = ["RATES", fam] if rep is None else ["RATES", fam, rep]
        print(f"\n=== {fam} (fanout={fanout}) ===", flush=True)
        descend(br, base, fanout, out)
        for k, v in sorted(out.items()):
            if k.startswith(f"RATES / {fam}") and "options" in v:
                seg = k.split(" / ")[-1]
                print(f"  {seg:<58} n={v['n']}", flush=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"\n-> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
