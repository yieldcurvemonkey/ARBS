"""Batch-parse the *Short-Dated [SOFR] Swaption Volatility Report* page.

Companion to :mod:`scripts.parse_jpm_packages`, kept separate so re-running it
cannot disturb the seven parquets that script already produced.

Why this page matters
---------------------
It is the **only** page in the J.P. Morgan package that prints the OTC
swaption grid as numbers rather than as a chart, and it prints it in the same
unit as the exchange pages: a *daily* basis-point normal yield vol.  That
makes the listed-vs-OTC basis -- our headline claim -- checkable against a
single outside vendor whose two legs were struck at the same 3:00 pm mark.

The *Treasury OTC and Exchange Volatility* page looks like the natural test
and is not: its ``Implied`` ratios are ``N/A`` on 100% of dates (only the
model ``FV`` and the realised ``Historical`` cells carry data), and what it
quotes is a **price**-vol ratio, not a bp yield-vol ratio.

Run::

    python scripts/parse_jpm_swaptions.py                # full archive
    python scripts/parse_jpm_swaptions.py --limit 40     # smoke test

Output (``notebooks/data/convexity_rv/``)::

    jpm_pkg_swaption_vol.parquet       one row per (as_of, tenor, maturity)
    jpm_pkg_swaption_coverage.json     files seen / page present / parsed / failed

Every row carries BOTH dates (``as_of`` = the 3:00 pm NY close the numbers
describe = the join key; ``business_date`` = the "For Business" date).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")


@dataclass
class Config:
    """Every knob, documented inline."""

    #: the read-only daily archive (1,716 PDFs, 2019-08-27 .. 2026-08-13)
    archive: Path = Path(r"C:/Users/chris/clee/project-oasis/private/"
                         r"jpm_research/us_futures_packages")

    #: output directory (gitignored, regenerable)
    out_dir: Path = REPO / "notebooks" / "data" / "convexity_rv"

    #: worker processes; each opens its own fitz.Document (paths, never handles)
    workers: int = 12

    #: files per task handed to a worker
    chunksize: int = 8

    #: both spellings of the page title.  The LIBOR-era name lost the "SOFR"
    #: qualifier when the underlying switched (first SOFR-titled issue
    #: 2023-03-09 as_of); neither string is a substring of the other, so
    #: locate_reports keeps them apart.
    titles: tuple[str, ...] = (
        "Short-Dated SOFR Swaption Volatility Report",
        "Short-Dated Swaption Volatility Report",
    )

    limit: int | None = None
    since: str | None = None
    until: str | None = None


CFG = Config()


def parse_one(path: str) -> dict[str, Any]:
    """Parse one PDF's swaption page.  Returns rows + status; never raises."""
    import fitz
    from RVUtils.ConvexityRV import jpm_package as jp

    base = os.path.basename(path)
    res: dict[str, Any] = {"file": base, "rows": [], "status": "absent",
                           "failures": [], "as_of": None, "generation": None}
    try:
        doc = fitz.open(path)
    except Exception as exc:  # corrupt / unreadable
        res["status"] = "fail"
        res["failures"].append({"page": None, "reason": f"open failed: {exc!r}"})
        return res
    try:
        dd = jp.document_dates(doc)
        res["as_of"] = dd.as_of.isoformat() if dd.as_of else None
        res["generation"] = dd.generation
        loc = jp.locate_reports(doc, CFG.titles)
        pages = [(t, p) for t, ps in loc.items() for p in ps]
        if not pages:
            return res
        n_ok = n_fail = 0
        for title, pno in pages:
            page = doc[pno - 1]
            pd_ = jp.page_dates(page, dd)
            try:
                recs = jp.parse_swaption_report(page, source=base)
            except jp.JpmParseError as exc:
                n_fail += 1
                res["failures"].append({"page": pno, "reason": exc.reason})
                continue
            except Exception as exc:  # noqa: BLE001 - want the reason, not a crash
                n_fail += 1
                res["failures"].append({
                    "page": pno,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=1).strip()[-200:]})
                continue
            for r in recs:
                r.update({
                    "as_of": pd_.as_of.isoformat() if pd_.as_of else None,
                    "business_date": (pd_.business_date.isoformat()
                                      if pd_.business_date else None),
                    "generation": dd.generation,
                    "report": title,
                    "source_file": base,
                    "page": pno,
                })
            res["rows"].extend(recs)
            n_ok += 1
        res["status"] = "fail" if n_fail else "ok" if n_ok else "absent"
    finally:
        doc.close()
    return res


def _select(cfg: Config) -> list[str]:
    files = sorted(str(p) for p in cfg.archive.glob("*.pdf"))
    if cfg.since:
        files = [f for f in files if os.path.basename(f)[:10] >= cfg.since]
    if cfg.until:
        files = [f for f in files if os.path.basename(f)[:10] <= cfg.until]
    if cfg.limit:
        files = files[:cfg.limit]
    return files


def main(cfg: Config = CFG) -> int:
    import pandas as pd

    files = _select(cfg)
    if not files:
        raise SystemExit(f"no PDFs under {cfg.archive}")
    print(f"[swpn] {len(files)} files, {cfg.workers} workers", flush=True)

    rows: list[dict[str, Any]] = []
    per_year: dict[str, dict[str, int]] = defaultdict(
        lambda: {"files_seen": 0, "page_present": 0, "parsed_ok": 0,
                 "failed": 0, "rows": 0})
    failures: list[dict[str, Any]] = []
    absent: list[str] = []

    done = 0
    with ProcessPoolExecutor(max_workers=cfg.workers) as ex:
        for r in ex.map(parse_one, files, chunksize=cfg.chunksize):
            done += 1
            if done % 250 == 0:
                print(f"[swpn]   {done}/{len(files)}", flush=True)
            rows.extend(r["rows"])
            year = (r["as_of"] or r["file"])[:4]
            cell = per_year[year]
            cell["files_seen"] += 1
            if r["status"] == "absent":
                absent.append(r["as_of"] or r["file"][:10])
            else:
                cell["page_present"] += 1
            if r["status"] == "ok":
                cell["parsed_ok"] += 1
            elif r["status"] == "fail":
                cell["failed"] += 1
            cell["rows"] += len(r["rows"])
            for f in r["failures"]:
                failures.append({"file": r["file"], **f})

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise SystemExit("[swpn] no rows parsed")

    df = pd.DataFrame(rows)
    for c in ("as_of", "business_date"):
        df[c] = pd.to_datetime(df[c])
    df = df.sort_values(["as_of", "tenor_years", "maturity_months", "source_file"])
    df = df.reset_index(drop=True)
    out = cfg.out_dir / "jpm_pkg_swaption_vol.parquet"
    df.to_parquet(out, index=False)
    print(f"[swpn] {out.name}: {len(df):,} rows x {df.shape[1]} cols", flush=True)

    cov = {
        "archive": str(cfg.archive),
        "files_parsed": len(files),
        "rows": int(len(df)),
        "as_of_range": [str(df["as_of"].min().date()), str(df["as_of"].max().date())],
        "as_of_dates": int(df["as_of"].nunique()),
        "per_year": {k: dict(v) for k, v in sorted(per_year.items())},
        "page_absent_dates": sorted(absent),
        "failures": failures[:200],
        "failure_count": len(failures),
    }
    (cfg.out_dir / "jpm_pkg_swaption_coverage.json").write_text(
        json.dumps(cov, indent=2), encoding="utf-8")
    print(f"[swpn] absent on {len(absent)} files, {len(failures)} failures",
          flush=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--since", type=str, default=None)
    ap.add_argument("--until", type=str, default=None)
    ap.add_argument("--workers", type=int, default=CFG.workers)
    a = ap.parse_args()
    CFG.limit, CFG.since, CFG.until, CFG.workers = a.limit, a.since, a.until, a.workers
    raise SystemExit(main(CFG))
