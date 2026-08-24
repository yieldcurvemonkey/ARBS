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

**Four documented limits**, worth knowing before trusting a pass. Matching is by
SUBSTRING, so ``0.19`` is satisfied by an output containing ``0.1903``; a whitelist
entry shadows any figure it is a substring of, so a whitelisted ``0.25`` also
excuses ``0.259``; and **a number written as a WORD is not a figure**, so "one
episode of four trades" passes whatever the cells say. That third one is not
hypothetical -- it is exactly what slipped through on this notebook's first
executed pass, where the largest episode is one trade and the prose said four.
Write quantities as digits in the findings block. And a figure is extracted
without its UNIT, so ``0.50bp`` is checked as ``0.50`` and would be satisfied by
an unrelated ``0.50`` elsewhere in the output -- which is why the tie-out cell
prints each figure in the exact form the prose quotes it, unit included, rather
than relying on the match. All four make the audit permissive, never strict: it
cannot pass a figure that appears nowhere.

Usage::

    python notebooks/backtests/intraday_fed_hawk_dove/_audit_macro_state_overlay_numbers.py [notebook.ipynb]
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
DEFAULT_NB = HERE / "usd_fed_macro_state_overlay.ipynb"

#: Figures the findings block quotes but does not recompute, each with its source.
WHITELIST = {
    # ---- cited from studies already on `main`, not recomputed here ----
    "0.219": "project_global_cb_hawk_dove: the intraday FED leg, bp per trade",
    "0.25": "the listed one-way cost per contract, bp of rate",
    "41.5": "project_fomc_nonvoter_fade: the displaced voter trades, cited",
    "155": "project_fomc_nonvoter_fade: the flipped subset size, cited",
    "504": "project_fomc_nonvoter_fade: its combined book size, cited",
    "0.02": "project_fomc_nonvoter_fade: the demeaned partition p, cited",
    "99.9": "project_fomc_nonvoter_fade: the partition percentile, cited",
    # ---- structural ----
    **{t: "structural" for t in (
        "2026", "2023", "2022", "2019", "0.50", "0.0", "0.5", "1.0", "24", "72",
        "10", "11",
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


#: Unit suffixes a figure may carry in the prose. A number written ``1.891bp``
#: must still be extracted as ``1.891``; the first version of this file used a
#: ``(?![\w])`` lookahead, which silently skipped EVERY figure with a unit --
#: including the pre-registered result, the noise scale the whole "not a cost
#: problem" argument rests on, and the engine tie-out tolerance. Seven headline
#: figures could never have failed the audit.
_UNIT = r"(?:bp|w|%|x|e-?\d+)?"


def figures(text: str) -> set[str]:
    out: set[str] = set()
    out |= {m.group(1) for m in
            re.finditer(rf"(?<![\w.])(\d+\.\d+){_UNIT}(?![\w.])", text)}
    out |= {m.group(1) + "%" for m in re.finditer(r"(\d+\.\d)%", text)}
    out |= {m.group(1) for m in
            re.finditer(rf"(?<![\w.])(\d{{2,}}){_UNIT}(?![\w.])", text)}
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
