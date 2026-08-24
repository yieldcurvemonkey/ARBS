"""Render the screen CSV into the committed markdown result doc."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

d = pd.read_csv(REPO / "docs" / "curvefly" / "screen_full_2026-08-21.csv")
ok = d[d.rac.notna()]
out = []
A = out.append

A("# Curve-fly screen — 2026-08-21 (USD SOFR)\n")
A("1,075 structures from 71 legs; 1,019 survive the degeneracy gate. Carry-and-roll")
A("is static-curve, one year. `rac = carry / (realised daily vol x sqrt(252))`;")
A("`rac_net` charges the position for full reversion to its 2-year mean. See")
A("`../DESIGN.md`, especially section 6 — **the two columns disagree and the")
A("disagreement is the point**.\n")

A("## By family\n")
g = ok.groupby("kind").agg(n=("rac", "size"), mean_cr=("cr_bp", "mean"),
                           pct_carry_pos=("cr_bp", lambda x: (x > 0).mean()),
                           mean_rac=("rac", "mean"), mean_rac_net=("rac_net", "mean"),
                           mean_vol=("rlzd_vol_bp", "mean")).round(3)
A(g.to_markdown() + "\n")
A("The forward curve of a fixed tenor (`f1 x t / f2 x t`) is the carry family and")
A("the short-convexity one. Forward flies are where convexity is sold to you: only")
A("30% carry positively, averaging -2.55bp/yr. That is the linear long-vol vehicle")
A("and that is its price.\n")

A("## The structures the desk names\n")
named = ["10y10y/20y10y", "10y10y/15y10y", "5y10y/10y10y", "15y5y/20y5y",
         "2s10s", "5s30s", "2s7s20s", "5s10s30s"]
cols = ["label", "kind", "level_bp", "cr_bp", "rlzd_vol_bp", "zs", "rac",
        "rev_drag_bp", "cr_net_rev", "rac_net"]
A(d[d.label.isin(named)][cols].round(2).to_markdown(index=False) + "\n")
A("Every carry structure goes negative once charged for reversion; `5s10s30s`, the")
A("worst on `rac`, is the only one positive on `rac_net` — because it is the only")
A("one that is cheap. Its negative carry is what a value position costs.\n")

A("## Carry vs reversion at the horizon\n")
A("Fraction reverted over horizon `h` with AR(1) half-life `L` is `1 - 2^(-h/L)`.")
A("bp of structure.\n")
A("| structure | half-life | 3m | 4.5m | 6m | 12m |")
A("|---|---|---|---|---|---|")
for name, cr, drag, L in [("10y10y/20y10y", 9.13, -10.79, 3.1),
                          ("10y10y/15y10y", 6.63, -7.75, 6.9),
                          ("5y10y/10y10y", 6.59, -7.29, 4.5),
                          ("5s10s30s", -5.80, 7.40, 4.4)]:
    cells = []
    for h in (3.0, 4.5, 6.0, 12.0):
        cells.append(f"{cr*h/12 + drag*(1 - 2 ** (-h / L)):+.2f}")
    A(f"| `{name}` | {L:.1f}m | " + " | ".join(cells) + " |")
A("")
A("At a 3-6 month horizon every steepener is net negative and `5s10s30s` is the")
A("only positive. `10y10y/20y10y` has a 3.1-month half-life, so most of the")
A("reversion lands inside the trade.\n")

for k, title in [("curve_fwd_tenor", "Forward curve, same tenor"),
                 ("curve_fwd_start", "Forward curve, same start"),
                 ("curve_spot", "Spot curve"),
                 ("fly_spot", "Spot fly"),
                 ("fly_fwd", "Forward fly")]:
    s = ok[ok.kind == k]
    if s.empty:
        continue
    A(f"## {title} — top 5 by `rac_net`\n")
    A(s.sort_values("rac_net", ascending=False).head(5)
      [["label", "level_bp", "cr_bp", "rlzd_vol_bp", "zs", "rac", "rac_net"]]
      .round(2).to_markdown(index=False) + "\n")

A("## Caveats\n")
A("* The screen ranks carry per unit of realised vol. It knows nothing about")
A("  bid-offer: the top raw-`rac` name is `10y1y/20y1y` (33.8bp of carry) and a")
A("  1y tail 10-20 years forward is nothing like as liquid as a 10y tail.")
A("* Half-lives are estimated in-sample over two years; mean-reversion parameters")
A("  are the least stable quantity here. Direction solid, magnitudes indicative.")
A("* `rac_net` assumes the 2-year mean is the attractor. If the forward curve is")
A("  structurally repricing rather than mean-reverting, `rac` is the better guide.")
A("  That is a view, not a screen output — but the trade requires one.")
A("* 47 structures were excluded for realising under 0.25bp/day: their legs sit")
A("  between the same curve nodes, so the level is near-constant by construction.")
A("  Before that gate they were the top AND bottom of the ranking.\n")

p = REPO / "docs" / "curvefly" / "results" / "screen-2026-08-21.md"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text("\n".join(out), encoding="utf-8")
print(f"wrote {p} ({len(out)} lines)")
