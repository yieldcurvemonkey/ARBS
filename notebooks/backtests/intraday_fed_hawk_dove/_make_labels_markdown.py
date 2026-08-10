"""Turn fed_quarterly_labels.json into a readable per-speaker markdown document."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
SRC = HERE / "fed_quarterly_labels.json"
OUT = HERE / "FED_SPEAKER_QUARTERLY_LABELS.md"

QUARTERS = [f"{y}Q{q}" for y in range(2019, 2027) for q in (1, 2, 3, 4)][:31]  # 2019Q1..2026Q3
LABEL = {2: "**HAWK+**", 1: "hawk", 0: "neutral", -1: "dove", -2: "**DOVE+**"}
GLYPH = {2: "HH", 1: "H", 0: "·", -1: "D", -2: "DD", None: " "}


def qi(q: str) -> int:
    y, n = q.upper().split("Q")
    return int(y) * 4 + int(n) - 1


def expand(periods) -> dict:
    """period ranges -> {quarter: (stance, why, confidence)}"""
    out = {}
    for p in periods or []:
        try:
            lo, hi = qi(p["start_q"]), qi(p["end_q"])
        except Exception:  # noqa: BLE001
            continue
        for q in QUARTERS:
            if lo <= qi(q) <= hi:
                out[q] = (int(p.get("stance", 0)), p.get("why", ""),
                          p.get("confidence", ""))
    return out


def main() -> None:
    blob = json.load(open(SRC, encoding="utf-8"))
    speakers = blob.get("speakers", blob)
    notes = blob.get("notes", [])

    grids = {sp: expand(v.get("periods") if isinstance(v, dict) else v)
             for sp, v in speakers.items()}
    # order by first quarter present, then name
    order = sorted(grids, key=lambda s: (min((qi(q) for q in grids[s]), default=9999), s))

    L: list[str] = []
    L.append("# FOMC Speakers — Quarterly Hawk/Dove Labels, 2019Q1 – 2026Q3")
    L.append("")
    L.append("Hand-assigned stance for every FOMC speaker, **rebalanced each quarter**, from "
             "published consensus: recorded dissents, dot-plot positions, and hawk/dove "
             "scorecards from Reuters, Bloomberg Economics, LSEG and the sell side.")
    L.append("")
    L.append("## How to read the scale")
    L.append("")
    L.append("The stance is **relative to the FOMC at that moment**, not absolute. In 2022 nearly "
             "every member sounded hawkish; only some were hawkish *versus their peers*, and only "
             "that difference can move a price that already embeds the consensus.")
    L.append("")
    L.append("| value | meaning |")
    L.append("|---|---|")
    L.append("| **+2** | among the most hawkish members of the committee that quarter |")
    L.append("| +1 | leaning hawkish versus peers |")
    L.append("| 0 | at the committee median, or nothing separates them |")
    L.append("| −1 | leaning dovish versus peers |")
    L.append("| **−2** | among the most dovish members |")
    L.append("")
    L.append("> **These labels are not point-in-time.** They were assigned in 2026 from "
             "commentary covering the whole period, so a quarter's stance can encode what was "
             "only understood later. Any backtest using them is an *upper bound* on what a "
             "correct, quarterly-refreshed read of the committee would have been worth — not a "
             "tradeable strategy.")
    L.append("")

    # ---- the grid
    L.append("## The grid")
    L.append("")
    L.append("`HH` = +2 · `H` = +1 · `·` = 0 · `D` = −1 · `DD` = −2 · blank = not on the committee")
    L.append("")
    yrs = sorted({q[:4] for q in QUARTERS})
    head = "| speaker | " + " | ".join(q[2:] for q in QUARTERS) + " |"
    L.append(head)
    L.append("|" + "---|" * (len(QUARTERS) + 1))
    for sp in order:
        g = grids[sp]
        row = [GLYPH.get(g[q][0]) if q in g else " " for q in QUARTERS]
        L.append(f"| **{sp}** | " + " | ".join(row) + " |")
    L.append("")

    # ---- who moved
    movers = []
    for sp in order:
        vals = [grids[sp][q][0] for q in QUARTERS if q in grids[sp]]
        if vals and (max(vals) - min(vals)) >= 2:
            movers.append((sp, min(vals), max(vals)))
    if movers:
        L.append("## Speakers who genuinely changed side")
        L.append("")
        L.append("The reason to rebalance quarterly rather than fix a label per person.")
        L.append("")
        L.append("| speaker | range | path |")
        L.append("|---|---|---|")
        for sp, lo, hi in sorted(movers, key=lambda x: x[1] - x[2]):
            g = grids[sp]
            path, last = [], None
            for q in QUARTERS:
                if q in g and g[q][0] != last:
                    path.append(f"{q}:{g[q][0]:+d}")
                    last = g[q][0]
            L.append(f"| **{sp}** | {lo:+d} → {hi:+d} | {' → '.join(path)} |")
        L.append("")

    # ---- per speaker
    L.append("## By speaker")
    L.append("")
    for sp in order:
        v = speakers[sp]
        meta = v if isinstance(v, dict) else {}
        L.append(f"### {sp}")
        L.append("")
        bits = [x for x in (meta.get("full_name"), meta.get("role")) if x]
        if bits:
            L.append(" · ".join(bits))
            L.append("")
        L.append("| quarters | stance | confidence | why |")
        L.append("|---|---|---|---|")
        for p in (meta.get("periods") or []):
            st = int(p.get("stance", 0))
            rng = (p.get("start_q", "") if p.get("start_q") == p.get("end_q")
                   else f"{p.get('start_q','')}–{p.get('end_q','')}")
            why = (p.get("why", "") or "").replace("|", "/").replace("\n", " ")
            L.append(f"| {rng} | {LABEL.get(st, st)} ({st:+d}) | "
                     f"{p.get('confidence','')} | {why} |")
        L.append("")
        srcs = meta.get("sources") or []
        if srcs:
            L.append("<sub>Sources: " + "; ".join(str(x) for x in srcs[:6]) + "</sub>")
            L.append("")

    if notes:
        L.append("## Notes from the labelling process")
        L.append("")
        for n in notes:
            L.append(f"- {n}")
        L.append("")

    OUT.write_text("\n".join(L), encoding="utf-8")
    n_cells = sum(len(g) for g in grids.values())
    print(f"wrote {OUT}")
    print(f"  {len(order)} speakers, {n_cells} labelled speaker-quarters, {len(movers)} movers")


if __name__ == "__main__":
    main()
