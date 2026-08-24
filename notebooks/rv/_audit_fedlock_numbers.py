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

# the findings block contains typographic dashes and a Unicode minus; on a
# cp1252 console printing them raises, and an audit that dies while REPORTING
# a failure is worse than one that never ran
try:  # pragma: no cover - console dependent
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_NB = HERE / "fedlock_sentiment_lead.ipynb"

#: Figures the findings block quotes but does not compute, each with its source.
WHITELIST = {
    # the FIRST study's published results, quoted here for comparison and
    # recomputed there, not here
    "0.737": "study 1, JPM levels r",
    "0.096": "study 1, JPM levels p",
    "0.153": "study 1, JPM changes r",
    "0.568": "study 1, JPM changes p",
    "0.005": "study 1, as-published p floor",
    "2.65": "study 1, JPM mean revision in points",
    "147": "study 1, sample weeks",
    "189": "study 1, rotation count",
    # FedLock's own published figures, quoted from its methodology page
    "0.82": "FedLock published rho between V2 and V3",
    "3.3": "Llama 3.3 70B -- a model name, not a measurement",
    "2.0": "Gemini 2.0 Flash -- a model name, not a measurement",
    "78": "FedLock published Powell Jackson Hole score (V2 era)",
    # dates, lag counts and other structural integers
    **{t: "structural" for t in (
        "1985", "2004", "2005", "2009", "2013", "2016", "2017", "2019", "2021",
        "2022", "2023", "2024", "2025", "2026", "2027", "2010", "2020",
        "13", "11", "12", "27", "18", "10", "5", "2.52", "3.28", "21", "70",
        "1.5", "1.6",
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
