r"""Does Citi still serve a UST that matured YEARS ago? ANSWERED: yes, ten years back.

This began as the one open question a ten-year timeseries warm depended on. It was
answered while the script was being written, so what follows is the ANSWER first
and then what this tool is still for.

The answer, measured 2026-08-08 off the tag cache
--------------------------------------------------
A ten-year fetch was run and the parquets grouped by the axis the question is
about - **maturity year**, not "is it matured":

========  ==============  ==========================  ==========
mat year  bonds served    series ends at own maturity  med rows
========  ==============  ==========================  ==========
2016                  23                          23          53
2017                  50                          50         226
2018                  51                          51         476
2019                  52                          52         679
2020                  55                          55         825
2021                  54                          54         985
2022                  51                          51       1,052
2023                  54                          54       1,129
2024                  50                          50       1,131
2025                  54                          54       1,191
========  ==============  ==========================  ==========

**494 of 494**, every one ending within a week of its own redemption date. Citi's
retention on the per-bond tag path is at least the ten years asked for. The
universe LISTING excludes a matured bond - ``CVCURVEBOND`` asked at five
historical as-of dates returns today's set filtered, never the set as it stood -
but the TAG does not, and those are different mechanisms.

An earlier ten-bond sample had said the same thing for maturities in May-July
2026 (``catalog/bond_history_depth_probe.json``). That sample could not settle it:
a vendor keeping four months of post-maturity history is indistinguishable, on
four months of evidence, from one keeping ten years. The maturity-year table
above is what settles it.

So what is this script still for
--------------------------------
Re-asking, when there is reason to think retention changed. Vendor history
windows move, and the failure mode is silent: a warm that suddenly gets nothing
for the 2016 constituents produces a shorter series, not an error. This samples by
MATURITY YEAR - five strata, spread rather than contiguous, one bond per
original-issue term within each - because a stratum that serves in full and one
that serves not at all BRACKET the window, and a pooled average would hide the
boundary. The report therefore prints per stratum and never pools.

It also distinguishes three outcomes that a naive check would merge: a bond that
served, a bond Citi refused, and a request whose TRANSPORT failed. The last is
not evidence about retention at all, and letting one dropped COM session read as
a retention limit is exactly how a wrong conclusion gets recorded as measured.

Before you run this
-------------------
It TOUCHES EXCEL. That is the whole point and it is also why it is checked in
unrun: on 2026-08-08 ``EXCEL.EXE`` was at 9,651 MB against a 3,800 MB ceiling, and
the add-in's memory only ever grows - only a human restart clears it. The memory
gate below will refuse to start in that state, correctly.

Cost, projected from the sibling warm's measured EOD rate (52 tags over five
years for +1 MB): ``--per-stratum 4 --strata 5`` at two values is 40 tags, so
single-digit megabytes and seconds.

::

    python scripts/citivelo_ust_history_depth_probe.py
    python scripts/citivelo_ust_history_depth_probe.py --per-stratum 6 --values PRICE YIELD
    python scripts/citivelo_ust_history_depth_probe.py --out probe.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

log = logging.getLogger("citivelo-ust-depth-probe")

#: Same headroom as the warms. Below the 3,800 MB hard ceiling.
WORKING_CEILING_MB = 3500.0

#: PRICE and YIELD: the two values measured to carry a bond's whole life.
#: DURATION and SPREAD_TSY floor at 2020-04-01 on every bond measured, so they
#: would confound "Citi dropped the bond" with "Citi never had that value".
DEFAULT_VALUES: Tuple[str, ...] = ("PRICE", "YIELD")

#: Maturity years to sample. Spread rather than contiguous so a retention cliff
#: is bracketed by the first pass instead of needing five.
DEFAULT_STRATA: Tuple[int, ...] = (2017, 2019, 2021, 2023, 2025)


def matured_sample(
    strata: Sequence[int] = DEFAULT_STRATA,
    per_stratum: int = 4,
    *,
    as_of: Optional[datetime.date] = None,
) -> Dict[int, List[dict]]:
    """Bonds that redeemed in each stratum year, from Treasury's own record.

    Nothing here touches Citi: the point is to pick bonds *without* consulting
    the universe listing, since the listing's exclusion of them is the premise.

    Coupon-bearing notes and bonds only (the reference table carries no bills),
    spread across original-issue terms within a year so a stratum is not four
    2-year notes - a 30-year that matured in 2017 and a 2-year that matured in
    2017 are different retention questions if Citi keys retention off issue date
    rather than maturity.
    """
    import pandas as pd

    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
    from utils.identifiers import InvalidIdentifierError, cusip_to_isin

    today = as_of or datetime.date.today()
    ref = update_reference_data(source="fiscaldata")
    out: Dict[int, List[dict]] = {}
    for year in strata:
        rows = []
        seen_terms: set = set()
        frame = ref.copy()
        frame["_mat"] = pd.to_datetime(frame["maturity_date"], errors="coerce")
        frame = frame[frame["_mat"].dt.year == year]
        frame = frame[frame["_mat"].dt.date < today]
        # One per original-issue term first, then fill.
        for _, row in frame.sort_values("_mat").iterrows():
            term = str(row.get("oi") or "")
            if term in seen_terms:
                continue
            seen_terms.add(term)
            try:
                isin = cusip_to_isin(str(row["cusip"]), "US")
            except InvalidIdentifierError:
                continue
            rows.append(
                {
                    "isin": isin,
                    "cusip": str(row["cusip"]),
                    "label": str(row.get("label") or ""),
                    "oi": term,
                    "issue": str(row.get("issue_date")),
                    "maturity": str(row.get("maturity_date")),
                }
            )
            if len(rows) >= per_stratum:
                break
        if len(rows) < per_stratum:
            for _, row in frame.sort_values("_mat").iterrows():
                try:
                    isin = cusip_to_isin(str(row["cusip"]), "US")
                except InvalidIdentifierError:
                    continue
                if any(r["isin"] == isin for r in rows):
                    continue
                rows.append(
                    {
                        "isin": isin,
                        "cusip": str(row["cusip"]),
                        "label": str(row.get("label") or ""),
                        "oi": str(row.get("oi") or ""),
                        "issue": str(row.get("issue_date")),
                        "maturity": str(row.get("maturity_date")),
                    }
                )
                if len(rows) >= per_stratum:
                    break
        out[year] = rows
    return out


def probe(
    sample: Dict[int, List[dict]],
    values: Sequence[str] = DEFAULT_VALUES,
    *,
    ceiling_mb: float = WORKING_CEILING_MB,
) -> dict:
    """Ask each bond for its whole life, one stratum at a time.

    Requests go through ``CitiVeloQuotes.frame``, the CACHED seam, so a result is
    on disk afterwards and re-reading it costs nothing - and so a partial run is
    not thrown away. ``CitiVeloBondFetcher.fetch`` would be the wrong call here
    for the reason recorded on the sibling warm: its intraday transport bypasses
    the tag cache entirely.

    An empty series and a failed request are recorded separately. "Citi refuses
    this bond" and "the add-in dropped the session" are opposite answers and
    pooling them would let one bad minute read as a retention limit.
    """
    from MDP.CitiVelocityExcel import tags as T
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect, excel_memory_mb
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    # BEFORE anything connects. On 2026-08-08 this would refuse, and that refusal
    # is the correct behaviour rather than an obstacle to route around.
    mem0 = assert_safe_to_connect(ceiling_mb, what="the UST history-depth probe")
    log.info("Excel at %.0f MB before connecting (ceiling %.0f)", mem0, ceiling_mb)

    quotes = CitiVeloQuotes()
    result: dict = {
        "probed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "values": list(values),
        "mem_before": mem0,
        "strata": {},
    }
    try:
        for year in sorted(sample):
            bonds = sample[year]
            log.info("stratum %d: %d bond(s)", year, len(bonds))
            served = 0
            records = []
            for bond in bonds:
                mem = excel_memory_mb()
                if mem is None or mem >= ceiling_mb:
                    log.warning("STOPPING at %s: Excel at %s MB", bond["isin"], mem)
                    result["stopped_at"] = bond["isin"]
                    result["mem_after"] = mem
                    return result

                tags = [T.bond(bond["isin"], v) for v in values]
                failures: Dict[str, str] = {}
                record = dict(bond)
                try:
                    # No start/end: ask for everything the tag has. The whole
                    # question is where Citi's own floor and ceiling sit, and a
                    # bounded request would answer with our bounds instead.
                    frame = quotes.frame(tags, "DAILY", failures=failures)
                except Exception as exc:  # noqa: BLE001
                    record.update(served=False, error=f"{type(exc).__name__}: {exc}")
                    records.append(record)
                    continue

                per_value = {}
                for tag, value in zip(tags, values):
                    if tag not in getattr(frame, "columns", ()):
                        per_value[value] = {"rows": 0, "reason": failures.get(tag, "no column")}
                        continue
                    column = frame[tag].dropna()
                    per_value[value] = {
                        "rows": int(len(column)),
                        "first": None if column.empty else str(column.index.min().date()),
                        "last": None if column.empty else str(column.index.max().date()),
                    }
                any_rows = any(v.get("rows", 0) > 0 for v in per_value.values())
                served += bool(any_rows)
                record.update(served=any_rows, per_value=per_value, failures=dict(failures))
                records.append(record)

            result["strata"][str(year)] = {
                "tested": len(bonds), "served": served, "bonds": records,
            }
            log.info("  stratum %d: %d/%d served", year, served, len(bonds))
        result["mem_after"] = excel_memory_mb()
    finally:
        quotes.close()
    return result


def report(result: dict) -> str:
    """Per stratum, never pooled. The boundary is the answer."""
    lines = [f"probed {result.get('probed_at')} for {', '.join(result.get('values', []))}"]
    for year in sorted(result.get("strata", {}), key=int):
        block = result["strata"][year]
        lines.append(f"\nmatured {year}: {block['served']}/{block['tested']} served")
        for bond in block["bonds"]:
            spans = ", ".join(
                f"{v}={d.get('rows', 0)}"
                + (f" [{d.get('first')}..{d.get('last')}]" if d.get("rows") else f" ({d.get('reason','')})")
                for v, d in (bond.get("per_value") or {}).items()
            )
            lines.append(
                f"  {bond['isin']} {bond['label']:<20} {bond['oi']:<9} mat {bond['maturity']}  "
                + (spans or bond.get("error", "no answer"))
            )
    if result.get("stopped_at"):
        lines.append(f"\nSTOPPED at {result['stopped_at']} (Excel at {result.get('mem_after')} MB)")
    lines.append(
        "\nRead it as a BOUNDARY, not an average. A stratum that serves in full "
        "and one that serves not at all bracket Citi's retention window; the "
        "earliest fully-served year is the honest floor for a constant-maturity "
        "backfill, and everything before it is a shorter series that says so."
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--strata", nargs="*", type=int, default=list(DEFAULT_STRATA),
                   help="maturity years to sample")
    p.add_argument("--per-stratum", type=int, default=4)
    p.add_argument("--values", nargs="*", default=list(DEFAULT_VALUES))
    p.add_argument("--ceiling-mb", type=float, default=WORKING_CEILING_MB)
    p.add_argument("--out", type=pathlib.Path, default=None, help="write the raw result as JSON")
    p.add_argument("--dry-run", action="store_true",
                   help="print the sample and exit; touches nothing")
    args = p.parse_args(argv)

    sample = matured_sample(args.strata, args.per_stratum)
    if args.dry_run:
        for year in sorted(sample):
            print(f"matured {year}:")
            for bond in sample[year]:
                print(f"  {bond['isin']} {bond['label']:<20} {bond['oi']:<9} "
                      f"issued {bond['issue']} matured {bond['maturity']}")
        return

    result = probe(sample, args.values, ceiling_mb=args.ceiling_mb)
    print(report(result))
    if args.out:
        args.out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        log.info("wrote %s", args.out)


if __name__ == "__main__":
    main()
