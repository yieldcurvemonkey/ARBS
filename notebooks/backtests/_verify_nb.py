"""Verify an executed notebook: zero cell errors, and report what it produced.

Reads the .ipynb rather than trusting the exit code — nbconvert can complete
while individual cells carry error outputs if the run was configured to allow
them, and a notebook whose cells never ran is not a deliverable either.

Usage::

    python notebooks/backtests/_verify_nb.py sfr_rv_lab_*.ipynb
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def verify(path: Path) -> tuple[bool, str]:
    nb = json.loads(path.read_text(encoding="utf-8"))
    cells = nb.get("cells", [])
    code = [c for c in cells if c.get("cell_type") == "code"]
    errors, unrun, n_out, n_img = [], 0, 0, 0
    for i, c in enumerate(code):
        if c.get("execution_count") is None:
            unrun += 1
        for o in c.get("outputs", []):
            n_out += 1
            if o.get("output_type") == "error":
                errors.append(f"cell {i}: {o.get('ename')}: "
                              f"{str(o.get('evalue'))[:120]}")
            if "image/png" in (o.get("data") or {}):
                n_img += 1
    ok = not errors and unrun == 0
    msg = (f"{path.name}: {len(code)} code cells, {n_out} outputs, {n_img} figures, "
           f"{unrun} unrun, {len(errors)} errors")
    if errors:
        msg += "\n    " + "\n    ".join(errors[:10])
    return ok, msg


def main(argv: list[str]) -> int:
    bad = 0
    for a in argv:
        for p in sorted(Path().glob(a)) or [Path(a)]:
            if not p.exists():
                print(f"MISSING {p}")
                bad += 1
                continue
            ok, msg = verify(p)
            print(("OK   " if ok else "FAIL ") + msg)
            bad += 0 if ok else 1
    print(f"\n{bad} notebook(s) failed verification")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
