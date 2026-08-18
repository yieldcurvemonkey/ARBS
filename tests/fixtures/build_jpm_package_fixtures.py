"""Build the JPM-package parser fixtures from the local PDF archive.

The fixtures are *page extracts*: each output PDF holds the cover page (so the
date logic has something to read) plus the two or three report pages the test
exercises.  They are a few hundred kB rather than the 76-page originals, and
they are gitignored -- rebuild them with::

    python tests/fixtures/build_jpm_package_fixtures.py

Pages are located by title, not index, so this script keeps working if the
archive is re-downloaded and the page numbers shift.

The four extracts between them cover every layout the parser has to survive:

===========  =========  ==================================================
extract      vintage    what it pins down
===========  =========  ==================================================
2019-08-27   legacy     a *populated* Eurodollar MidCurve page (the ones
                        in 2023 are entirely dashed)
2023-06-09   legacy     Treasury + Eurodollar summaries, the OTC/CBOT
                        ratio page, the maturity-structure page, the skew
                        page, and a fully-dashed MidCurve page
2024-12-12   v2025      the first issue of the new generation: glued
                        "Jan25" column headers, "Change(5d)" without a
                        space, and "Implied (bp) per day" section labels
2025-06-12   v2025      a swaption page with an intact layout and every
                        cell blank -- the JpmEmptyPage case
2026-08-13   v2025      the mature new layout: "Closes as Of" header, a
                        second page mis-titled "Treasury Volatility
                        Summary" that actually carries SOFR 3M, glued
                        "$167.35$167.35" cells, and the VOLATLITY typo
===========  =========  ==================================================
"""

from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ARCHIVE = Path(r"C:/Users/chris/clee/project-oasis/private/jpm_research/"
               r"us_futures_packages")
OUT = Path(__file__).resolve().parent / "jpm_packages"

#: which report pages to lift out of which issue
WANTED: dict[str, tuple[str, ...]] = {
    "2019-08-27": ("Eurodollar MidCurve Volatility Summary",
                   "Short-Dated Swaption Volatility Report"),
    "2023-06-09": ("Treasury Volatility Summary",
                   "Eurodollar Volatility Summary",
                   "Eurodollar MidCurve Volatility Summary",
                   "U.S. Treasuries Volatility Skew Report",
                   "Maturity Structure of Treasury Volatility",
                   "Treasury OTC and Exchange Volatility",
                   "Short-Dated SOFR Swaption Volatility Report"),
    "2024-12-12": ("Treasury Volatility Summary",),
    # a swaption page whose layout is intact but whose every cell is blank --
    # a legitimate state that must raise JpmEmptyPage rather than emit zeros
    "2025-06-12": ("Short-Dated SOFR Swaption Volatility Report",),
    "2026-08-13": ("Treasury Volatility Summary",
                   "Maturity Structure of Treasury Volatility",
                   "Short-Dated SOFR Swaption Volatility Report"),
}


def build() -> dict:
    import fitz
    from RVUtils.ConvexityRV import jpm_package as jp

    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict = {}
    for tag, titles in WANTED.items():
        hits = glob.glob(str(ARCHIVE / f"{tag}_*.pdf"))
        if not hits:
            raise SystemExit(f"archive has no issue for {tag} under {ARCHIVE}")
        src = fitz.open(hits[0])
        loc = jp.locate_reports(src)
        pages = [0]                      # always keep the cover
        for t in titles:
            for p in loc.get(t, [])[:2]:  # at most 2 pages per report
                if p - 1 not in pages:
                    pages.append(p - 1)
        pages.sort()
        dst = fitz.open()
        for p in pages:
            dst.insert_pdf(src, from_page=p, to_page=p)
        name = f"jpm_{tag}.pdf"
        dst.save(str(OUT / name), garbage=4, deflate=True)
        dst.close()
        manifest[name] = {
            "source": os.path.basename(hits[0]),
            "source_pages_1based": [p + 1 for p in pages],
            "titles": list(titles),
            "bytes": (OUT / name).stat().st_size,
        }
        src.close()
        print(f"[fix] {name}: pages {[p + 1 for p in pages]} "
              f"({manifest[name]['bytes'] / 1024:.0f} kB)")
    with open(OUT / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest


if __name__ == "__main__":
    build()
