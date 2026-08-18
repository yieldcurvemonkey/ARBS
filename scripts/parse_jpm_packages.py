"""Batch-parse the J.P. Morgan U.S. Futures and Options Package archive.

Reads every ``*.pdf`` in the archive directory, locates the volatility pages
by title, parses them with :mod:`RVUtils.ConvexityRV.jpm_package`, and writes
tidy parquets plus a coverage report.

Run::

    python scripts/parse_jpm_packages.py                 # full archive
    python scripts/parse_jpm_packages.py --limit 20      # smoke test
    python scripts/parse_jpm_packages.py --since 2024-01-01

Outputs (all under ``notebooks/data/convexity_rv/``)::

    jpm_pkg_treasury_vol.parquet        Treasury Bond / Note / 5Y vol summary
    jpm_pkg_stir_vol.parquet            Eurodollar (to 2023) + SOFR 3M (from 2024-12)
    jpm_pkg_midcurve_vol.parquet        Eurodollar 1Yr..5Yr MidCurve vol summary
    jpm_pkg_otc_exchange_ratio.parquet  OTC/CBOT price-vol ratios
    jpm_pkg_maturity_structure.parquet  (Front a)/(Front b) vol ratios
    jpm_pkg_skew.parquet                UST vol-skew strike table
    jpm_pkg_skew_atm.parquet            the skew page's ATM vol / vol-beta captions
    jpm_pkg_coverage.json               per report per year: files, rows, failures

Every row carries BOTH dates:

``as_of``          the 3:00 pm NY close the numbers describe -- **the join key**
``business_date``  the "For Business" date the sheet is filed under (= next
                   business day)

The PDF filename is deliberately *not* used as a date: it disagrees with the
cover's "For Business" line on 273 of the 1,306 legacy files.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
@dataclass
class Config:
    """Every knob for the batch, documented inline."""

    #: where the daily packages live (1,716 PDFs, 2019-08-27 .. 2026-08-13).
    #: Outside the repo and read-only -- nothing here writes to it.
    archive: Path = Path(r"C:/Users/chris/clee/project-oasis/private/"
                         r"jpm_research/us_futures_packages")

    #: output directory (gitignored, regenerable)
    out_dir: Path = REPO / "notebooks" / "data" / "convexity_rv"

    #: worker processes.  Each opens its own fitz.Document; PyMuPDF is not
    #: fork-safe across processes on Windows so we pass paths, never handles.
    workers: int = 12

    #: files per task handed to a worker.  Large enough to amortise process
    #: hand-off, small enough that one slow file does not stall a worker.
    chunksize: int = 8

    #: parse the volatility-skew page too.  It roughly triples wall time and
    #: row count, so it can be turned off for a quick re-run.
    parse_skew: bool = True

    #: optional filters (mostly for smoke tests)
    limit: int | None = None
    since: str | None = None
    until: str | None = None

    #: fail the whole run if the failure rate on the primary report exceeds
    #: this.  A layout change that our hard-fail catches should be *loud*.
    max_failure_rate: float = 0.05


CFG = Config()


# ---------------------------------------------------------------------------
# per-file worker
# ---------------------------------------------------------------------------
#: (title, parser-kind) pairs we attempt on every file
_TARGETS = (
    ("Treasury Volatility Summary", "vol"),
    ("Eurodollar Volatility Summary", "vol"),
    ("Eurodollar MidCurve Volatility Summary", "vol"),
    ("Treasury OTC and Exchange Volatility", "otc"),
    ("Maturity Structure of Treasury Volatility", "mat"),
    ("U.S. Treasuries Volatility Skew Report", "skew"),
)


def parse_one(args: tuple[str, bool]) -> dict[str, Any]:
    """Parse one PDF.  Returns rows + per-report status; never raises."""
    path, do_skew = args
    import fitz
    from RVUtils.ConvexityRV import jpm_package as jp

    base = os.path.basename(path)
    res: dict[str, Any] = {
        "file": base,
        "vol": [], "otc": [], "mat": [], "skew": [], "skew_atm": [],
        "status": {},          # title -> "ok" / "absent" / "empty" / "fail"
        "failures": [],        # {report, page, reason, label}
        "doc_as_of": None, "doc_business": None, "generation": None,
        "pages": None,
    }
    try:
        doc = fitz.open(path)
    except Exception as exc:  # corrupt / unreadable file
        res["failures"].append({"report": "<document>", "page": None,
                                "reason": f"open failed: {exc!r}", "label": ""})
        res["status"]["<document>"] = "fail"
        return res

    try:
        dd = jp.document_dates(doc)
        res["doc_as_of"] = dd.as_of.isoformat() if dd.as_of else None
        res["doc_business"] = dd.business_date.isoformat() if dd.business_date else None
        res["generation"] = dd.generation
        res["pages"] = doc.page_count
        loc = jp.locate_reports(doc)

        for title, kind in _TARGETS:
            if kind == "skew" and not do_skew:
                continue
            pages = loc.get(title, [])
            if not pages:
                res["status"][title] = "absent"
                continue
            n_ok = n_empty = n_fail = 0
            for pno in pages:
                page = doc[pno - 1]
                pd_ = jp.page_dates(page, dd)
                stamp = {
                    "as_of": pd_.as_of.isoformat() if pd_.as_of else None,
                    "business_date": (pd_.business_date.isoformat()
                                      if pd_.business_date else None),
                    "generation": dd.generation,
                    "report": title,
                    "source_file": base,
                    "page": pno,
                }
                try:
                    if kind == "vol":
                        recs = jp.parse_vol_summary(page, as_of=pd_.as_of,
                                                    source=base)
                        for r in recs:
                            r.update(stamp)
                            r["family"] = jp.product_family(r["product"])
                        res["vol"].extend(recs)
                    elif kind == "otc":
                        recs = jp.parse_otc_exchange(page, source=base)
                        for r in recs:
                            r.update(stamp)
                        res["otc"].extend(recs)
                    elif kind == "mat":
                        recs = jp.parse_maturity_structure(page, source=base)
                        for r in recs:
                            r.update(stamp)
                        res["mat"].extend(recs)
                    else:
                        got = jp.parse_skew_report(page, source=base)
                        for r in got["strikes"]:
                            r.update(stamp)
                        for r in got["captions"]:
                            r.update(stamp)
                        res["skew"].extend(got["strikes"])
                        res["skew_atm"].extend(got["captions"])
                    n_ok += 1
                except jp.JpmEmptyPage as exc:
                    n_empty += 1
                    res["failures"].append({"report": title, "page": pno,
                                            "reason": "parsed_empty",
                                            "label": exc.label})
                except jp.JpmParseError as exc:
                    n_fail += 1
                    res["failures"].append({"report": title, "page": pno,
                                            "reason": exc.reason,
                                            "label": exc.label})
                except Exception as exc:  # noqa: BLE001 - want the reason, not a crash
                    n_fail += 1
                    res["failures"].append({
                        "report": title, "page": pno,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "label": traceback.format_exc(limit=1).strip()[-200:]})
            res["status"][title] = ("fail" if n_fail else
                                    "ok" if n_ok else "empty")
    finally:
        doc.close()
    return res


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def _select_files(cfg: Config) -> list[str]:
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

    files = _select_files(cfg)
    if not files:
        raise SystemExit(f"no PDFs under {cfg.archive}")
    print(f"[jpm] {len(files)} files, {cfg.workers} workers", flush=True)

    vol, otc, mat, skew, skew_atm = [], [], [], [], []
    per_report: dict[str, dict[str, Any]] = defaultdict(
        lambda: defaultdict(lambda: {"files_seen": 0, "page_present": 0,
                                     "parsed_ok": 0, "parsed_empty": 0,
                                     "failed": 0, "rows": 0}))
    failures: list[dict[str, Any]] = []
    gens: dict[str, int] = defaultdict(int)
    doc_dates: list[dict[str, Any]] = []
    #: report -> as_of dates on which the file exists but the page does not.
    #: This is a coverage fact, not a parse failure, and it is the only way to
    #: tell "JPM dropped the page that day" from "we failed to find it".
    absent: dict[str, list[str]] = defaultdict(list)

    payload = [(f, cfg.parse_skew) for f in files]
    done = 0
    with ProcessPoolExecutor(max_workers=cfg.workers) as ex:
        for r in ex.map(parse_one, payload, chunksize=cfg.chunksize):
            done += 1
            if done % 200 == 0:
                print(f"[jpm]   {done}/{len(files)}", flush=True)
            vol.extend(r["vol"]); otc.extend(r["otc"]); mat.extend(r["mat"])
            skew.extend(r["skew"]); skew_atm.extend(r["skew_atm"])
            gens[r["generation"] or "unknown"] += 1
            doc_dates.append({"file": r["file"], "as_of": r["doc_as_of"],
                              "business_date": r["doc_business"],
                              "generation": r["generation"],
                              "pages": r["pages"]})
            year = (r["doc_as_of"] or r["file"])[:4]
            rows_by_report: dict[str, int] = defaultdict(int)
            for bucket in ("vol", "otc", "mat", "skew"):
                for row in r[bucket]:
                    rows_by_report[row["report"]] += 1
            for title, _kind in _TARGETS:
                st = r["status"].get(title)
                if st is None:
                    continue
                cell = per_report[title][year]
                cell["files_seen"] += 1
                if st == "absent":
                    absent[title].append(r["doc_as_of"] or r["file"][:10])
                else:
                    cell["page_present"] += 1
                if st == "ok":
                    cell["parsed_ok"] += 1
                elif st == "empty":
                    cell["parsed_empty"] += 1
                elif st == "fail":
                    cell["failed"] += 1
                cell["rows"] += rows_by_report.get(title, 0)
            for f in r["failures"]:
                failures.append({"file": r["file"], **f})

    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    def _write(rows: list[dict], name: str, sort: list[str]) -> int:
        if not rows:
            print(f"[jpm] {name}: EMPTY, not written", flush=True)
            return 0
        df = pd.DataFrame(rows)
        for c in ("as_of", "business_date"):
            if c in df:
                df[c] = pd.to_datetime(df[c])
        # a metric that is missing on *every* parsed page (e.g. 2Yr Event Risk,
        # printed as "-" throughout the archive) would otherwise land as an
        # all-None object column; force the numeric ones to float
        for c in df.columns:
            if df[c].dtype == object and c.split("_")[0] in ("pct", "bp", "yc"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
        keys = [c for c in sort if c in df.columns]
        df = df.sort_values(keys).reset_index(drop=True)
        df.to_parquet(cfg.out_dir / name, index=False)
        print(f"[jpm] {name}: {len(df):,} rows x {df.shape[1]} cols", flush=True)
        return len(df)

    vol_df_rows = {"treasury": [], "stir": [], "midcurve": []}
    for row in vol:
        vol_df_rows[row["family"]].append(row)

    counts = {
        "jpm_pkg_treasury_vol.parquet": _write(
            vol_df_rows["treasury"], "jpm_pkg_treasury_vol.parquet",
            ["as_of", "product", "expiry_ym"]),
        "jpm_pkg_stir_vol.parquet": _write(
            vol_df_rows["stir"], "jpm_pkg_stir_vol.parquet",
            ["as_of", "product", "expiry_ym"]),
        "jpm_pkg_midcurve_vol.parquet": _write(
            vol_df_rows["midcurve"], "jpm_pkg_midcurve_vol.parquet",
            ["as_of", "product", "expiry_ym"]),
        "jpm_pkg_otc_exchange_ratio.parquet": _write(
            otc, "jpm_pkg_otc_exchange_ratio.parquet", ["as_of", "panel"]),
        "jpm_pkg_maturity_structure.parquet": _write(
            mat, "jpm_pkg_maturity_structure.parquet", ["as_of", "ratio"]),
        "jpm_pkg_skew.parquet": _write(
            skew, "jpm_pkg_skew.parquet",
            ["as_of", "product", "expiry_label", "strike"]),
        "jpm_pkg_skew_atm.parquet": _write(
            skew_atm, "jpm_pkg_skew_atm.parquet",
            ["as_of", "product", "expiry_label"]),
    }

    reason_counts: dict[str, int] = defaultdict(int)
    for f in failures:
        reason_counts[f["reason"]] += 1
    coverage = {
        "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "archive": str(cfg.archive),
        "files_parsed": len(files),
        "generations": dict(gens),
        "as_of_range": [min(d["as_of"] for d in doc_dates if d["as_of"]),
                        max(d["as_of"] for d in doc_dates if d["as_of"])],
        "outputs": counts,
        "per_report_per_year": {k: dict(v) for k, v in per_report.items()},
        "failure_reason_counts": dict(sorted(reason_counts.items(),
                                             key=lambda kv: -kv[1])),
        "failures": failures,
        "page_absent_dates": {k: sorted(v) for k, v in absent.items()},
        "document_dates": doc_dates,
    }
    with open(cfg.out_dir / "jpm_pkg_coverage.json", "w", encoding="utf-8") as fh:
        json.dump(coverage, fh, indent=1)
    print(f"[jpm] coverage -> {cfg.out_dir / 'jpm_pkg_coverage.json'}", flush=True)

    prim = per_report["Treasury Volatility Summary"]
    seen = sum(c["files_seen"] for c in prim.values())
    bad = sum(c["failed"] for c in prim.values())
    rate = bad / seen if seen else 0.0
    print(f"[jpm] Treasury Volatility Summary failure rate {bad}/{seen} = {rate:.4%}")
    return 0 if rate <= cfg.max_failure_rate else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--since", type=str, default=None)
    ap.add_argument("--until", type=str, default=None)
    ap.add_argument("--workers", type=int, default=CFG.workers)
    ap.add_argument("--no-skew", action="store_true")
    a = ap.parse_args()
    CFG.limit, CFG.since, CFG.until = a.limit, a.since, a.until
    CFG.workers = a.workers
    CFG.parse_skew = not a.no_skew
    raise SystemExit(main(CFG))
