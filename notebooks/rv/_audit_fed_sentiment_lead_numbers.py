"""Every figure asserted in the findings block must be produced by a cell.

The notebook's own header rule is "if the cells and this summary ever disagree,
the cells are what ran". That rule is worth nothing unless something checks it,
because the summary is written by hand and the cells are not: over this study's
life the null sizes moved twice and the prewhitened p-value moved once, each
time silently orphaning a number in the prose.

So this parses the findings markdown, pulls out every figure, and requires each
to appear verbatim in some executed cell's text output. It runs as part of
``run_fed_sentiment_lead.py`` and fails the build, alongside the zero-errors and
zero-unrun checks.

Figures that legitimately come from elsewhere are whitelisted with a reason --
JWS's own numbers, quoted from the note under test, and the existing intraday
speaker backtest's economics, which this notebook cites but does not recompute.

Usage::

    python notebooks/rv/_audit_fed_sentiment_lead_numbers.py [notebook.ipynb]
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_NB = HERE / "fed_sentiment_lead.ipynb"

#: Figures the findings block quotes but does not compute, each with its source.
WHITELIST = {
    # JWS Macro #8's own description of his chart, quoted in the introduction
    "0.85": "JWS's stated July level",
    "0.1": "JWS's stated current level",
    # the existing point-in-time-gated speaker backtest, cited not recomputed
    "0.219": "intraday FED leg, bp per trade",
    "0.146": "intraday FED leg, break-even bp",
    "0.25": "listed SR3 round-trip cost, bp",
    "473": "intraday FED leg, trades",
    "103.5": "intraday FED leg, total bp",
    "0.69": "intraday FED leg, Sharpe",
    "1.24": "intraday FED leg, t",
    # dates, lag counts and other structural integers
    **{t: "structural" for t in (
        "2026", "2023", "2024", "2025", "2022", "1998", "2005",
        "16", "27", "13", "12", "11", "14", "26", "10", "5", "4.33",
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
            print(f"    {t:12s} {line[:130]}")
        return 1
    print("OK -- every figure in the findings block is produced by a cell")
    return 0


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_NB
    raise SystemExit(audit(target))
