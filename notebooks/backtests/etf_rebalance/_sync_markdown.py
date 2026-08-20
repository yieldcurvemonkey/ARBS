"""Refresh the executed notebook's PROSE from the generator, keeping its outputs.

Why this exists
---------------
`_make_notebook.py` is the source of truth for the notebook, but regenerating it discards
every cell output and forces a 30-minute re-execution. When only the markdown has changed
-- a corrected figure in the commentary, a rewritten explanation -- that re-execution buys
nothing, and skipping it leaves the prose disagreeing with the numbers printed directly
below it, which is exactly the inconsistency a reader notices first.

So: regenerate to a temporary notebook, then copy the markdown cells across by position
into the executed one. It **refuses** if the code cells differ by so much as a character,
because at that point the outputs really are stale and a re-run is the only honest answer.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
NB = HERE / "etf_rebalance_configurable_backtest.ipynb"
GEN = HERE / "_make_notebook.py"


def cells_of(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))["cells"]


def main() -> int:
    if not NB.exists():
        print(f"no executed notebook at {NB}")
        return 1

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / NB.name
        # The generator writes to a fixed path, so run it and take a copy, then put the
        # executed notebook back before touching anything.
        executed = NB.read_text(encoding="utf-8")
        subprocess.run([sys.executable, str(GEN)], check=True, capture_output=True)
        tmp.write_text(NB.read_text(encoding="utf-8"), encoding="utf-8")
        NB.write_text(executed, encoding="utf-8")

        fresh = cells_of(tmp)

    nb = json.loads(NB.read_text(encoding="utf-8"))
    old = nb["cells"]

    if len(old) != len(fresh):
        print(f"REFUSED: cell count differs ({len(old)} executed vs {len(fresh)} generated). "
              f"Re-execute rather than patching.")
        return 1

    diffs = []
    for i, (a, b) in enumerate(zip(old, fresh)):
        if a["cell_type"] != b["cell_type"]:
            diffs.append((i, "type"))
        elif a["cell_type"] == "code" and "".join(a["source"]) != "".join(b["source"]):
            diffs.append((i, "code"))
    if diffs:
        print(f"REFUSED: {len(diffs)} code/type cells differ -- the outputs are stale.")
        for i, why in diffs[:8]:
            print(f"  cell {i}: {why}")
        print("Re-execute the notebook instead.")
        return 1

    n = 0
    for a, b in zip(old, fresh):
        if a["cell_type"] == "markdown" and "".join(a["source"]) != "".join(b["source"]):
            a["source"] = b["source"]
            n += 1

    NB.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"synced {n} markdown cells; all {sum(1 for c in old if c['cell_type'] == 'code')} "
          f"code cells identical, outputs preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
