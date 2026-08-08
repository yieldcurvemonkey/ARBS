r"""Tie Citi Velocity's PUBLISHED swap spread out against this repo's computed one.

Two numbers that sound identical and are not:

``RATES.OIS.<index>.SWAP_SPREAD.<tenor>``
    A quote Citi disseminates. What Treasury it is spread against, whether that
    leg is matched-maturity or an interpolated benchmark, and which swap curve
    Citi used are **not published anywhere in the harvested catalog**.
``IRSwapValue.SPREADOVER`` (and ``MMSS``)
    Computed here, in ``MDP/IRSwapSpreads/IRSwapSpreadsMDP.py``, as
    ``(swap_rate_percent - bond_ytm_percent) * 100`` - swap minus cash, in basis
    points. ``SPREADOVER`` pairs a round-tenor par swap with the on-the-run note;
    ``MMSS`` pins the swap to a named bond's exact maturity.

This script measures the gap between them per tenor, and in doing so settles the
one thing that cannot be settled by reading code: **what unit Citi publishes in.**
``MDP/IRSwaps/CITIVELO_EXCEL/swap_spreads.py`` returns the served number unscaled
and records ``UNIT = "as_published"`` precisely because, as of 2026-08-08, zero
``SWAP_SPREAD`` tags were cached and Excel was unavailable. The table below prints
Citi's raw mean beside the repo's bp mean, so a 100x mismatch is visible at a
glance: a USD 10Y swap spread is tens of basis points, so ``|citi| > 1`` means bp
and ``|citi| < 1`` means it is not.

Two phases, and they are separable on purpose
---------------------------------------------
``fetch``
    The only phase that touches Excel. Samples Excel's working set FIRST and
    **aborts above ``--memory-abort-mb`` (default 3800)** without connecting -
    the add-in's cache only ever grows, a 528-window fetch has already wedged a
    5,249 MB process, and only a human restart clears it. Writes the raw served
    numbers to JSON, so a session lost afterwards costs time and not data.

    The gate FAILS CLOSED: an unreadable probe aborts. "No EXCEL.EXE" is reported
    as an affirmative ``0 MB`` and proceeds; a probe that timed out or could not
    run reports nothing about what is running, and the two states have opposite
    correct actions.
``compare``
    Pure local work: reads that JSON and prices the repo side. No Excel. It does
    need whatever the chosen ``--irs-source`` needs - the default,
    ``CITIVELO_EXCEL-RL``, reads the warmed CurveStore - and it needs the UST
    reference data and marks the ``--frb-source`` uses.

``fetch`` is ``DAILY`` only. ``CVTSHIST`` silently downsamples an ``MI01``
request whose SPAN exceeds six days, and the returned block looks identical
either way; the chunk-and-verify route is
``MDP.CitiVelocityExcel.windowed.fetch_windowed``, which is not what a
multi-month tie-out wants.

``--end`` defaults to TODAY, and Citi's DAILY series carries a row for the
current, incomplete session (measured 2026-08-07: a row stamped 2026-08-07 00:00
existed at 10:47 ET). ``swap_spread_history`` warns about that; the last row it
returns is a running level and differencing it against a settled repo-side
``SPREADOVER`` for the same date produces a residual that is nobody's mistake.
Pass ``--end <yesterday>`` for a clean table.

Run from the repo root, AFTER a human has restarted Excel::

    <env>/python.exe scripts/citivelo_swap_spread_tieout.py fetch --start 2026-01-01 --end 2026-08-07
    <env>/python.exe scripts/citivelo_swap_spread_tieout.py compare
    <env>/python.exe scripts/citivelo_swap_spread_tieout.py compare --max-days 20

Not run as of 2026-08-08: ``EXCEL.EXE`` (pid 51420, started 2026-08-07 17:24:33)
read **13,865 MB** on this script's own probe - 3.6x the 3,800 MB ceiling and 2.6x
the 5,249 MB that wedged it on 2026-08-07. Note the unit: this probe divides
``WorkingSet64`` by 1e6, so it reports decimal MB, and the same process shows
13,222 MiB to a ``Win32_Process`` query. The ceiling is in the probe's unit.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import pathlib
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_logger = logging.getLogger("citivelo_swap_spread_tieout")

#: Stop before asking Excel for anything. The standing instruction for this
#: machine; the recorded wedge was at 5,249 MB and the process cannot be
#: recycled from here - only a human restart returns that memory.
DEFAULT_MEMORY_ABORT_MB = 3800.0

#: Where ``fetch`` writes and ``compare`` reads.
DEFAULT_OUT = _REPO_ROOT / "MDP" / "CitiVelocityExcel" / "harvest" / "swap_spread_tieout"

DEFAULT_INDEX = "USD_SOFR"
DEFAULT_CURVE_NAME = "USD-SOFR-1D"
DEFAULT_IRS_SOURCE = "CITIVELO_EXCEL-RL"
DEFAULT_FRB_SOURCE = "USTS_FEDINVEST_WSJ_LIVE-QL"


# ------------------------------------------------------------------ #
#                          the memory guard                          #
# ------------------------------------------------------------------ #


#: The PowerShell the probe runs. ``Measure-Object -Sum`` over ZERO processes
#: sums to ``$null`` and prints an empty line - which is also what a command that
#: never ran prints, and the two have opposite correct actions. So the query emits
#: an explicit ``NONE`` for "no EXCEL.EXE", and anything the parser cannot make a
#: number of is an unreadable probe rather than an empty machine.
_PROBE = (
    "$s = (Get-Process EXCEL -ErrorAction SilentlyContinue | "
    "Measure-Object WorkingSet64 -Sum).Sum; "
    "if ($null -eq $s) { 'NONE' } else { $s }"
)


def excel_memory_mb() -> Optional[float]:
    """Excel's working set in MB. ``0.0`` when none is running, ``None`` when the
    probe itself FAILED.

    Those two are different facts and the old version of this returned ``None``
    for both, which is what made the gate above it fail open. A machine with no
    EXCEL.EXE is the safest state there is; a probe that timed out, could not find
    PowerShell, or was refused by execution policy says nothing at all about what
    is running - and on this machine what is running is a 13,865 MB add-in that
    only a human restart clears.

    Deliberately a standalone PowerShell probe rather than
    ``CitiVelocityExcelClient.excel_memory_mb``: that one is a method on a
    *connected* client, and connecting is the exact act this guard exists to
    prevent. Same query, no COM.
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _PROBE],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:  # noqa: BLE001 - an unreadable probe must not look like "fine"
        return None

    if getattr(out, "returncode", 1) != 0:
        return None
    raw = (out.stdout or "").strip()
    if raw == "NONE":
        return 0.0
    try:
        return float(raw) / 1e6
    except (TypeError, ValueError):
        return None


def _memory_gate(limit_mb: float) -> bool:
    """True when it is safe to proceed. Prints the number either way.

    FAILS CLOSED. An unreadable probe aborts: a running-but-unreadable Excel and a
    machine with no Excel are indistinguishable to a probe that did not complete,
    and their correct actions are opposite - one must not be connected to, the
    other is the safest state there is. Only an affirmative reading proceeds, and
    "no EXCEL.EXE" is now an affirmative reading (``0.0``) rather than a silence.

    The failure this prevents is unrecoverable without a human: the add-in's cache
    only ever grows, a 528-window fetch wedged a 5,249 MB process on 2026-08-07,
    and this probe read 13,865 MB off the live process on 2026-08-08.
    """
    mem = excel_memory_mb()
    if mem is None:
        print(
            f"ABORT: could not read Excel's memory (probe failed, timed out, or PowerShell is\n"
            f"       unavailable). Ceiling {limit_mb:.0f} MB. A probe that did not complete says\n"
            "       NOTHING about what is running, and connecting into a wedged add-in is only\n"
            "       cleared by a human restart. Fix the probe, or confirm by hand with\n"
            "       Get-Process EXCEL and re-run."
        )
        return False
    print(f"Excel memory BEFORE: {mem:.0f} MB (ceiling {limit_mb:.0f})")
    if mem >= limit_mb:
        print(
            f"ABORT: Excel already at {mem:.0f} MB, above the {limit_mb:.0f} MB ceiling.\n"
            "       The add-in's cache is never released and only a HUMAN restart clears it.\n"
            "       Restart Excel, sign in to Velocity, and re-run."
        )
        return False
    return True


# ------------------------------------------------------------------ #
#                               fetch                                #
# ------------------------------------------------------------------ #


def _out_path(out_dir: pathlib.Path, citi_index: str) -> pathlib.Path:
    return pathlib.Path(out_dir) / f"{citi_index}_swap_spread_daily.json"


def fetch(
    *,
    citi_index: str,
    start: datetime.date,
    end: datetime.date,
    tenors: Optional[Sequence[str]],
    out_dir: pathlib.Path,
    memory_abort_mb: float,
    force_refresh: bool,
) -> int:
    """Pull the whole ``SWAP_SPREAD`` axis over ``[start, end]`` and write it to JSON."""
    if not _memory_gate(memory_abort_mb):
        return 2

    # Lazy, like every heavy import here, so ``--help`` stays instant.
    import pandas as pd

    from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import (
        UNIT,
        swap_spread_history,
        swap_spread_tenors,
    )

    axis = list(swap_spread_tenors(citi_index))
    wanted = [str(t).strip().upper() for t in tenors] if tenors else axis
    unknown = [t for t in wanted if t not in axis]
    if unknown:
        print(
            f"ABORT: {', '.join(unknown)} are not on {citi_index}'s SWAP_SPREAD axis. "
            f"Accepted: {', '.join(axis)}."
        )
        return 2

    print(f"fetch: {citi_index} SWAP_SPREAD {len(wanted)} tenor(s) DAILY {start} .. {end}")
    frame = swap_spread_history(
        citi_index, wanted, start=start, end=end, force_refresh=force_refresh
    )
    after = excel_memory_mb()
    if frame is None or frame.empty:
        print("fetch: NOTHING SERVED. CVMETADATA cannot be used to check this family - it")
        print("       reports zero valid tenors and poisons its own batch. Validate with")
        print("       CitiVeloQuotes.validate, which goes through CVTSHIST with controls.")
        return 1

    # Account for every REQUESTED tenor, not just the ones that came back with a
    # column. ``swap_spread_history`` drops a tag that served nothing, so
    # iterating ``frame.columns`` would make a tenor that returned NOTHING
    # disappear from the report instead of showing up as n=0 - and per-tenor
    # accounting is the whole point of this script.
    served = {t: (int(frame[t].notna().sum()) if t in frame.columns else 0) for t in wanted}
    payload: Dict[str, Any] = {
        "meta": {
            "citi_index": citi_index,
            "freq": "DAILY",
            "unit_as_fetched": UNIT,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "fetched_at": datetime.datetime.now().astimezone().isoformat(),
            "excel_memory_mb_after": after,
            "rows": int(len(frame)),
            "rows_served_per_tenor": served,
        },
        "citi": {
            str(tenor): (
                {
                    pd.Timestamp(stamp).date().isoformat(): float(value)
                    for stamp, value in frame[tenor].dropna().items()
                }
                if tenor in frame.columns
                else {}
            )
            for tenor in wanted
        },
    }

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _out_path(out_dir, citi_index)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"fetch: {len(frame)} row(s) -> {path}")
    for tenor in wanted:
        col = frame[tenor].dropna() if tenor in frame.columns else None
        if col is None or col.empty:
            print(f"       {tenor:>4}  n=0   NOTHING SERVED")
            continue
        print(
            f"       {tenor:>4}  n={len(col):<5} raw mean {col.mean():>10.4f}  "
            f"min {col.min():>10.4f}  max {col.max():>10.4f}"
        )
    print(
        "       Units: the numbers above are AS PUBLISHED, unscaled. A USD 10Y swap spread\n"
        "       is tens of basis points, so |mean| > 1 says bp and |mean| < 1 says it is not."
    )
    if after is not None:
        print(f"Excel memory AFTER: {after:.0f} MB")
    return 0


# ------------------------------------------------------------------ #
#                              compare                               #
# ------------------------------------------------------------------ #


def _repo_spread_bps(
    mdp: Any,
    *,
    curve_name: str,
    as_of: datetime.date,
    tenor: str,
    value: Any,
) -> float:
    """This repo's computed spread in bp for one (date, tenor), or raise.

    ``SPREADOVER`` takes a round tenor (``10Y``) and internally pairs it with the
    on-the-run note (``CT10``); ``MMSS`` needs a bond identifier and will not
    resolve a bare ``10Y``, which is why it is not the default here.
    """
    pricer = mdp.get_pricer(
        {"curve_name": curve_name, "timestamp": as_of, "tenor": tenor, "value": value}
    )
    return float(pricer.value_bps())


#: Above this, the repo side is broken rather than merely disagreeing: ten
#: times any swap spread that has ever traded. Measured cause is a curve that
#: failed to build or a bond that priced to nonsense; see compare().
_BROKEN_BP = 1000.0


def compare(
    *,
    citi_index: str,
    curve_name: str,
    out_dir: pathlib.Path,
    irs_source: str,
    frb_source: str,
    repo_value: str,
    max_days: Optional[int],
    tenors: Optional[Sequence[str]],
) -> int:
    """Price the repo side for every fetched (date, tenor) and print the table.

    No Excel. Per-tenor failures are counted and reported as ``n=0`` with the
    first reason, rather than taking the run down: the money-market end of Citi's
    axis (``1M 3M 6M 1Y`` for USD) has no on-the-run Treasury note to spread
    against, so those tenors are EXPECTED to produce nothing on the repo side and
    that is information, not an error.
    """
    import statistics

    # Checked BEFORE the heavy imports: "you have not run fetch yet" must not
    # arrive disguised as an import error from the pricing stack.
    path = _out_path(pathlib.Path(out_dir), citi_index)
    if not path.exists():
        print(f"ABORT: {path} does not exist. Run the fetch phase first (it needs Excel).")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    citi: Dict[str, Dict[str, float]] = payload["citi"]
    meta = payload.get("meta", {})

    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    try:
        value = IRSwapValue[str(repo_value).upper()]
    except KeyError:
        print(f"ABORT: {repo_value!r} is not an IRSwapValue.")
        return 2

    wanted = [str(t).strip().upper() for t in tenors] if tenors else list(citi)
    mdp = IRSwapSpreadsMDP(
        _irs_mdp=IRSwapsMDP(source=irs_source),
        _frb_mdp=FixedRateBondsMDP(source=frb_source),
    )

    print(
        f"compare: {citi_index} ({curve_name}) Citi SWAP_SPREAD vs {value.name}\n"
        f"         irs_source={irs_source}  frb_source={frb_source}\n"
        f"         fetched {meta.get('start')} .. {meta.get('end')}, "
        f"unit as fetched: {meta.get('unit_as_fetched')}"
    )

    per_day: dict = {}
    rows: List[Tuple[str, int, float, float, float, float, float, str]] = []
    for tenor in wanted:
        series = citi.get(tenor) or {}
        dates = sorted(series)
        if max_days:
            dates = dates[-int(max_days):]
        diffs: List[float] = []
        citi_vals: List[float] = []
        repo_vals: List[float] = []
        first_error = ""
        for iso in dates:
            as_of = datetime.date.fromisoformat(iso)
            try:
                repo = _repo_spread_bps(
                    mdp, curve_name=curve_name, as_of=as_of, tenor=tenor, value=value
                )
            except Exception as exc:  # noqa: BLE001 - a tenor that cannot price is data
                if not first_error:
                    first_error = f"{type(exc).__name__}: {exc}"[:110]
                continue
            citi_value = float(series[iso])
            citi_vals.append(citi_value)
            repo_vals.append(repo)
            diffs.append(citi_value - repo)

        if not diffs:
            rows.append((tenor, 0, float("nan"), float("nan"), float("nan"),
                         float("nan"), float("nan"), first_error or "no dates"))
            continue

        # The MEAN of these diffs is not a summary of the disagreement, and
        # reporting it as one would be actively misleading. Measured 2026-08-08
        # over 2026-07-08..08-07: the 3Y mean difference was 141,422 bp while the
        # MEDIAN was 0.86 bp. The repo's own SPREADOVER blows up on a minority of
        # days - a curve that failed to build, or a bond that priced to nonsense,
        # yields values like -151,276 bp, which is not a spread - and a handful of
        # those dominate any mean. So the median leads, the mean is kept only so
        # the divergence is visible, and days the repo could not price sanely are
        # COUNTED rather than quietly folded in.
        #
        # 1,000 bp is the cut: ten times any swap spread that has ever traded, so
        # it separates "the repo broke" from "the repo and Citi disagree" without
        # being tunable enough to flatter the answer.
        broken = [d for d in diffs if abs(d) > _BROKEN_BP]
        sane = [d for d in diffs if abs(d) <= _BROKEN_BP]
        note = ""
        if broken:
            note = f"{len(broken)}/{len(diffs)} repo days > {_BROKEN_BP:.0f}bp (excluded from median)"
        rows.append(
            (
                tenor,
                len(diffs),
                statistics.fmean(citi_vals),
                statistics.fmean(repo_vals),
                statistics.fmean(diffs),
                statistics.median(sane) if sane else float("nan"),
                max(diffs, key=abs),
                note,
            )
        )
        per_day[tenor] = {
            "dates": [iso for iso in dates][-len(diffs):],
            "citi": citi_vals,
            "repo": repo_vals,
            "diff": diffs,
            "n_broken": len(broken),
        }

    # "largest diff" is selected by |x| but PRINTED WITH ITS SIGN: which way the
    # worst day went is the whole diagnostic, and an absolute value throws it away.
    header = (
        f"{'tenor':>6} {'n':>5} {'citi raw':>11} {'repo bp':>11} "
        f"{'mean diff':>11} {'median':>11} {'largest':>11}  note"
    )
    print()
    print(header)
    print("-" * len(header))
    for tenor, n, citi_mean, repo_mean, mean_d, med_d, max_d, note in rows:
        if n == 0:
            print(f"{tenor:>6} {0:>5} {'-':>11} {'-':>11} {'-':>11} {'-':>11} {'-':>11}  {note}")
            continue
        print(
            f"{tenor:>6} {n:>5} {citi_mean:>11.4f} {repo_mean:>11.4f} "
            f"{mean_d:>11.4f} {med_d:>11.4f} {max_d:>11.4f}  {note}"
        )

    priced = [r for r in rows if r[1] > 0]
    if priced:
        biggest = max(abs(r[2]) for r in priced)
        print()
        print(
            "Units verdict: Citi's largest raw mean is "
            f"{biggest:.4f} -> "
            + (
                "BASIS POINTS (the same scale as the repo column)."
                if biggest > 1.0
                else "NOT basis points; it is ~100x too small, so it is a percent/decimal form."
            )
        )
        print(
            "  If it reads BASIS POINTS, set UNIT = 'bp' in "
            "MDP/IRSwaps/CITIVELO_EXCEL/swap_spreads.py and cite this run."
        )
    else:
        print("\nNothing priced on the repo side; the units question is still open.")

    out_path = pathlib.Path(out_dir) / f"{citi_index}_tieout_{value.name}.json"
    out_path.write_text(
        json.dumps(
            {
                "meta": {**meta, "repo_value": value.name, "irs_source": irs_source,
                         "frb_source": frb_source, "curve_name": curve_name,
                         "compared_at": datetime.datetime.now().astimezone().isoformat(),
                         "broken_bp_threshold": _BROKEN_BP},
                # Per-day series, not just the summary. Without these a reader
                # cannot tell a 141,422 bp "mean difference" (a handful of days
                # where the repo side failed to price) from a real disagreement,
                # and the summary alone invites quoting the former.
                "per_day": per_day,
                "rows": [
                    {
                        "tenor": t, "n": n, "citi_raw_mean": c, "repo_bp_mean": r,
                        "mean_diff": md, "median_diff": mdn,
                        "largest_diff_signed": mx, "note": note,
                    }
                    for t, n, c, r, md, mdn, mx, note in rows
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {out_path}")
    return 0


# ------------------------------------------------------------------ #
#                                cli                                 #
# ------------------------------------------------------------------ #


def _date(token: str) -> datetime.date:
    return datetime.date.fromisoformat(token)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="citivelo_swap_spread_tieout",
        description=(
            "Compare Citi Velocity's published RATES.OIS.<index>.SWAP_SPREAD.<tenor> "
            "against this repo's computed SPREADOVER/MMSS, per tenor, in bp."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("phase", choices=["fetch", "compare"])
    parser.add_argument("--citi-index", default=DEFAULT_INDEX,
                        help=f"Citi OIS index (default {DEFAULT_INDEX}).")
    parser.add_argument("--curve-name", default=DEFAULT_CURVE_NAME,
                        help=f"repo curve name for the swap leg (default {DEFAULT_CURVE_NAME}).")
    parser.add_argument("--tenors", nargs="*", default=None,
                        help="subset of the index's SWAP_SPREAD axis; default is the whole axis.")
    parser.add_argument("--start", type=_date, default=None,
                        help="fetch only: first date (ISO). Default: 1 year back.")
    parser.add_argument("--end", type=_date, default=None,
                        help="fetch only: last date (ISO). Default: today.")
    parser.add_argument("--out-dir", type=pathlib.Path, default=DEFAULT_OUT,
                        help=f"where the raw fetch JSON lives (default {DEFAULT_OUT}).")
    parser.add_argument("--memory-abort-mb", type=float, default=DEFAULT_MEMORY_ABORT_MB,
                        help=f"fetch only: refuse to start above this (default {DEFAULT_MEMORY_ABORT_MB:.0f}).")
    parser.add_argument("--force-refresh", action="store_true",
                        help="fetch only: bypass the tag cache.")
    parser.add_argument("--irs-source", default=DEFAULT_IRS_SOURCE,
                        help=f"compare only: IRSwapsMDP source (default {DEFAULT_IRS_SOURCE}).")
    parser.add_argument("--frb-source", default=DEFAULT_FRB_SOURCE,
                        help=f"compare only: FixedRateBondsMDP source (default {DEFAULT_FRB_SOURCE}).")
    parser.add_argument("--repo-value", default="SPREADOVER",
                        help="compare only: SPREADOVER (default) or MMSS. MMSS needs a bond "
                             "identifier per tenor and will not resolve a bare '10Y'.")
    parser.add_argument("--max-days", type=int, default=None,
                        help="compare only: use just the last N fetched dates per tenor.")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.phase == "fetch":
        end = args.end or datetime.date.today()
        start = args.start or (end - datetime.timedelta(days=365))
        if start > end:
            print(f"ABORT: --start {start} is after --end {end}.")
            return 2
        return fetch(
            citi_index=args.citi_index,
            start=start,
            end=end,
            tenors=args.tenors,
            out_dir=args.out_dir,
            memory_abort_mb=args.memory_abort_mb,
            force_refresh=args.force_refresh,
        )

    return compare(
        citi_index=args.citi_index,
        curve_name=args.curve_name,
        out_dir=args.out_dir,
        irs_source=args.irs_source,
        frb_source=args.frb_source,
        repo_value=args.repo_value,
        max_days=args.max_days,
        tenors=args.tenors,
    )


if __name__ == "__main__":
    raise SystemExit(main())
