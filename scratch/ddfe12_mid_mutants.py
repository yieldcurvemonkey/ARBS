"""Do the continuous-mid tests actually bite?

A test suite that passes is evidence of nothing until you have watched it fail.
Each mutation below is a plausible edit -- the kind that gets made while
"tidying" -- and each one changes what the chart CLAIMS rather than whether it
renders. That is the whole hazard class: every one of these produces a chart
that draws perfectly and means something else.

Run: python scratch/ddfe12_mid_mutants.py
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "SDRUtils", "dashboard")
NPM = r"C:\Program Files (x86)\Nodist\bin\npm.cmd"

SRC = os.path.join(DASH, "src")
LOGIC = os.path.join(SRC, "app", "api", "usd-swaps-tape-v2", "direction", "prints.logic.ts")
HELP = os.path.join(
    SRC, "features", "usd-swaps-tape-v2", "components", "AnalyticsPanel",
    "IntradayPrintsPanel.helpers.ts")

# (name, file, find, replace, what it would silently do)
MUTANTS = [
    ("gap-too-tight", HELP,
     "export const MID_GRID_GAP_MINUTES = 10",
     "export const MID_GRID_GAP_MINUTES = 3",
     "breaks the line inside a live session -- invents holes that are not there"),
    ("gap-too-loose", HELP,
     "export const MID_GRID_GAP_MINUTES = 10",
     "export const MID_GRID_GAP_MINUTES = 200",
     "bridges the 2h overnight hole -- draws a mid where no curve exists"),
    ("residual-on-execution-clock", HELP,
     "    const t = tsMillis(r.curve_timestamp)\n"
     "    if (t == null) continue\n"
     "    const g = byMinute.get(Math.floor(t / 60_000))",
     "    const t = tsMillis(r.execution_timestamp)\n"
     "    if (t == null) continue\n"
     "    const g = byMinute.get(Math.floor(t / 60_000))",
     "compares each mark to the WRONG minute's mid -- reports a disagreement "
     "it manufactured itself"),
    ("residual-admits-off-market", HELP,
     "    if (r.mid_pct == null || r.is_off_market === true) continue",
     "    if (r.mid_pct == null) continue",
     "lets a fee-bearing print into the mark-vs-line statistic"),
    ("thin-grid-wins", HELP,
     "  if (grid?.available && grid.points.length >= MIN_MID_POINTS) {",
     "  if (grid?.available) {",
     "draws a 'curve' through 3 points"),
    ("residual-max-unsigned", HELP,
     "    maxBps: abs[abs.length - 1]!,",
     "    maxBps: sorted[sorted.length - 1]!,",
     "prints max 0.000 on a day whose worst mark is 5bp BELOW the line"),
    ("ydomain-drops-the-line", HELP,
     "  for (const m of mid) {\n"
     "    if (m.mid != null && Number.isFinite(m.mid)) vals.push(m.mid)\n"
     "  }",
     "  // for (const m of mid) {}",
     "clips the line at the frame edge -- reads as the market going flat"),
    ("window-unpadded", LOGIC,
     "export const MID_PAD_MINUTES = 15",
     "export const MID_PAD_MINUTES = 0",
     "the line stops dead on the first and last mark"),
    ("grid-by-band-label", LOGIC,
     "      AND g.tenor_label = $2",
     "      AND g.tenor_display = $2",
     "looks the grid up by the +/-6-month band column"),
    ("availability-scoped-to-window", LOGIC,
     "            SELECT 1 FROM ${DD_CURVE_MID} WHERE rate_index = $1 AND tenor_label = $2",
     "            SELECT 1 FROM ${DD_CURVE_MID} WHERE rate_index = $1 AND tenor_label = $2 AND ts > now()",
     "cannot tell 'this tenor has no grid' from 'this window is a hole'"),
    ("line-sold-as-a-quote", LOGIC,
     "'not a quoted mid and not a tradable level. It is built by the same '",
     "'a live mid. It is built by the same '",
     "a MODELLED curve presented as a quote"),
    ("fallback-goes-silent", LOGIC,
     "      `NO CONTINUOUS MID IS AVAILABLE for ${d.rateIndex} ${d.tenor}` +",
     "      `` +",
     "Fed Funds 7Y/20Y/30Y shows a polyline through 8 prints with no warning"),
]

TEST_ARGS = ["test", "--", "--silent", "IntradayPrintsPanel", "prints.logic"]


def run_tests() -> tuple[bool, str]:
    p = subprocess.run([NPM, *TEST_ARGS], cwd=DASH, capture_output=True, text=True,
                       shell=False)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0, out


def main() -> int:
    print("baseline ...", end=" ", flush=True)
    ok, out = run_tests()
    if not ok:
        print("BASELINE IS RED -- fix that before mutating\n")
        print(out[-3000:])
        return 2
    tail = [l for l in out.splitlines() if l.startswith("Tests:")]
    print(f"green ({tail[0] if tail else '?'})\n")

    survived = []
    for name, path, find, repl, harm in MUTANTS:
        orig = io.open(path, encoding="utf-8").read()
        if find not in orig:
            print(f"  [SKIP] {name}: anchor not found -- the code moved")
            survived.append((name, "anchor not found"))
            continue
        io.open(path, "w", encoding="utf-8").write(orig.replace(find, repl, 1))
        try:
            ok, out = run_tests()
        finally:
            io.open(path, "w", encoding="utf-8").write(orig)
        if ok:
            print(f"  [SURVIVED] {name}")
            print(f"             would: {harm}")
            survived.append((name, harm))
        else:
            failed = [l.strip() for l in out.splitlines()
                      if l.strip().startswith(("\u00d7", "x ", "\u2715"))][:2]
            print(f"  [killed]   {name:<28} {failed[0][:70] if failed else ''}")

    print()
    if survived:
        print(f"{len(survived)} of {len(MUTANTS)} SURVIVED -- those behaviours are untested:")
        for n, h in survived:
            print(f"  - {n}: {h}")
        return 1
    print(f"all {len(MUTANTS)} mutants killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
