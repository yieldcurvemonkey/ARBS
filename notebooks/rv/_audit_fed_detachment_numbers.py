"""Every figure asserted in the findings block must be produced by a cell.

The notebook's own header rule is "if the cells and this summary ever disagree,
the cells are what ran". That rule is worth nothing unless something checks it,
because the summary is written by hand and the cells are not. On the study this
was copied from, the null sizes moved twice and a p-value once over the work's
life, each time silently orphaning a number in the prose.

So this parses the findings markdown, pulls out every figure, and requires each
to appear verbatim in some executed cell's text output. It runs as part of
``run_fed_detachment.py`` and fails the build alongside the zero-errors and
zero-unrun checks.

**Three documented limits**, worth knowing before trusting a pass. Matching is by
SUBSTRING, so ``0.19`` is satisfied by an output containing ``0.1903``; a whitelist
entry shadows any figure it is a substring of, so a whitelisted ``0.25`` also
excuses ``0.259``; and **a number written as a WORD is not a figure**, so "one
episode of four trades" passes whatever the cells say. That third one is not
hypothetical -- it is exactly what slipped through on this notebook's first
executed pass, where the largest episode is one trade and the prose said four.
Write quantities as digits in the findings block. All three make the audit
permissive, never strict: it cannot pass a figure that appears nowhere.

Usage::

    python notebooks/rv/_audit_fed_detachment_numbers.py [notebook.ipynb]
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

# the findings block carries typographic dashes; on a cp1252 console printing
# them raises, and an audit that dies while REPORTING a failure is worse than
# one that never ran
try:  # pragma: no cover - console dependent
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_NB = HERE / "fed_detachment_rv.ipynb"

#: Figures the findings block quotes but does not recompute, each with its source.
WHITELIST = {
    # the two studies already on main, cited rather than re-run here
    "0.12": "prior studies: the 21-year correlation at the surviving lead",
    "2.65": "prior study: mean |revision| in sentiment points",
    "3.73": "t-statistic of the FedLock SR3 winner, quoted to 2dp from 3.733808",
    # the intraday Fed-speaker suite, cited for comparison
    "0.219": "intraday FED leg, bp per trade",
    "1056": "intraday FED leg, trials",
    "0.95": "the DSR threshold that suite cleared on none of them",
    # process constants and structural integers
    "0.97": "AR(0.97) -- the null-calibration process parameter",
    "1.71": "measured on the PRE-FIX pass of the grid, before best_of_both; "
            "pinned by test_best_of_both_does_not_pick_the_reading_the_flip_made_worse "
            "so it cannot recur, and by construction no cell can reproduce it now",
    "0.29": "the other half of that same pre-fix comparison",
    "0.05": "the nominal test size",
    # Structural integers: grid dimensions, calendar years, and counts that
    # describe the DESIGN rather than a measurement. Everything a cell computes
    # is deliberately NOT here -- the tie-out cell at the foot of the notebook
    # prints each of those, so the audit checks them rather than excusing them.
    **{t: "structural" for t in (
        "2048", "2026", "2023", "2018", "1985", "256", "121", "100",
        "11", "13", "20", "1.0", "0.5", "0.0",
    )},
}


def executed_output_text(nb: dict) -> str:
    chunks = []
    for c in nb["cells"]:
        if c["cell_type"] != "code":
            continue
        for o in c.get("outputs", []):
            if o.get("output_type") == "stream":
                chunks.append("".join(o.get("text", [])))
            data = o.get("data") or {}
            if "text/plain" in data and "application/vnd.plotly.v1+json" not in data:
                chunks.append("".join(data["text/plain"]))
    return "\n".join(chunks)


def findings_markdown(nb: dict) -> str:
    for c in nb["cells"]:
        if c["cell_type"] == "markdown":
            src = "".join(c["source"])
            if "What was measured" in src:
                return src
    raise AssertionError("no findings cell -- the summary block is missing")


def figures(text: str) -> set[str]:
    out: set[str] = set()
    out |= {m.group(1) for m in re.finditer(r"(?<![\w.])(\d+\.\d+)(?![\w])", text)}
    out |= {m.group(1) + "%" for m in re.finditer(r"(\d+\.\d)%", text)}
    out |= {m.group(1) for m in re.finditer(r"(?<![\w.])(\d{2,})(?![\w.%])", text)}
    return out


def audit(path: pathlib.Path) -> int:
    nb = json.loads(path.read_text(encoding="utf-8"))
    out = executed_output_text(nb)
    if not out.strip():
        print(f"FAIL {path.name}: the notebook has no cell output -- run it first")
        return 1
    found = findings_markdown(nb)
    checked = [t for t in figures(found) if t not in WHITELIST]
    missing = sorted(t for t in checked if t not in out)
    print(f"{path.name}: {len(checked)} figures in the findings block, "
          f"{len(checked) - len(missing)} produced by a cell, "
          f"{len(WHITELIST)} whitelisted as cited from elsewhere")
    if missing:
        print("FAIL -- these appear in the prose but in no cell output:")
        for t in missing:
            line = next((l.strip() for l in found.splitlines() if t in l), "")
            print(f"    {t:14s} {line[:130]}")
        return 1
    print("OK -- every figure in the findings block is produced by a cell")
    return 0


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_NB
    raise SystemExit(audit(target))
