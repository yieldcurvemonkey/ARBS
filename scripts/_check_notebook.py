"""Assert an executed notebook has no error cells, and echo its gate output.

A notebook that renders is not a notebook that ran. nbconvert exits 0 on a
notebook full of tracebacks when --allow-errors is on, and even without it a
silently-empty output reads as success.
"""
from __future__ import annotations

import json
import pathlib
import sys

KEYS = ("GATE", "matched", "mode vs forward", "sums to", "corr(carry",
        "degeneracy", "compose-vs-price", "survive both gates", "priced ")


def main(path: str) -> int:
    nb = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    cells = nb["cells"]
    code = [c for c in cells if c["cell_type"] == "code"]
    errs, unrun = [], 0
    for c in code:
        if c.get("execution_count") is None:
            unrun += 1
        for o in c.get("outputs", []):
            if o.get("output_type") == "error":
                errs.append((o.get("ename"), (o.get("evalue") or "")[:220]))
    print(f"{pathlib.Path(path).name}: {len(code)} code cells, "
          f"{unrun} never executed, {len(errs)} errored")
    for e, v in errs[:5]:
        print(f"  !! {e}: {v}")

    for c in code:
        for o in c.get("outputs", []):
            if o.get("output_type") == "stream":
                txt = "".join(o.get("text", ""))
                for line in txt.splitlines():
                    if any(k in line for k in KEYS):
                        print("   |", line[:150])
    return 1 if (errs or unrun) else 0


if __name__ == "__main__":
    sys.exit(max(main(p) for p in sys.argv[1:]))
