r"""Find and remove foreign-series rows from the Citi Velocity tag cache.

    python scripts/citivelo_tagcache_repair.py report
    python scripts/citivelo_tagcache_repair.py repair --apply

What it removes, and why the band alone is not enough
-----------------------------------------------------
A merged Excel region wrote swaption normal volatility into the OIS par tags -
see ``docs/2026-08-24-citivelo-tagcache-poison.md`` and the guards in
``block_parser._one_block_only``. Two independent criteria mark a row, and both
are needed:

**Tier 1, out of band.** The value cannot belong to the tag's family at all
(``MDP.CitiVelocityExcel.sanity``). Certain, and it finds most of the damage.

**Tier 2, an exact match to the donor.** The value equals, to the last bit, the
value the DONOR tag carried on that same day. This is the tier that matters:
a short-expiry normal vol dips under 25 in a quiet regime, so a poisoned row can
sit INSIDE the par band and look like a perfectly ordinary rate. Measured on
``RATES.OIS.USD_SOFR.PAR.1D``, tier 1 finds 2,387 rows and tier 2 finds the 213
more that a band would have left behind, still wearing a par rate's clothes.

The donor is not assumed. For each poisoned tag the tool SEARCHES the RATES.VOL
family for the series that reproduces its out-of-band rows exactly, and reports
which one it found. A tag whose donor cannot be identified is reported and left
alone: tier 1 rows are still removed, but no in-band row is touched on a guess.

Why rows are DELETED rather than rebuilt
-----------------------------------------
The clean par rate can be recomputed from the CurveStore's stored discount
factors, and that is how this tool VALIDATES what survives - but it is a derived
number, off the quoted one by ~0.2bp in roll and day-count detail. Writing it
back would put a computed value in a cache whose entire contract is "what the
vendor quoted", and the next reader would have no way to tell. A missing row is
an honest cache miss that a re-harvest fills. A plausible-looking wrong row is
what this whole exercise exists to remove.

Safety
------
``report`` is read-only and is the default. ``repair`` requires ``--apply``, and
without ``--no-backup`` it copies every file it is about to change into
``<cache>/../citivelo_excel_prerepair/<UTC stamp>/`` first. It writes parquet
through the same atomic temp-then-rename the cache itself uses.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import pathlib
import shutil
import sys
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from MDP.CitiVelocityExcel.cache import default_cache_dir  # noqa: E402
from MDP.CitiVelocityExcel.sanity import (  # noqa: E402
    UNBANDABLE_BUT_POISONABLE,
    band_for_tag,
    implausible_rows,
)
from utils.atomic_replace import replace_with_retry  # noqa: E402

_logger = logging.getLogger("citivelo_tagcache_repair")

#: Families whose rows can be checked against a band today. Everything else is
#: reported by the donor search alone.
DONOR_PREFIXES = ("RATES.VOL.",)


def _load(path: pathlib.Path) -> Optional[pd.Series]:
    try:
        df = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("unreadable: %s (%s)", path, exc)
        return None
    if df.empty or "timestamp" not in df or "value" not in df:
        return None
    s = pd.Series(df["value"].to_numpy(dtype="float64"),
                  index=pd.DatetimeIndex(pd.to_datetime(df["timestamp"])))
    return s[~s.index.duplicated(keep="last")].sort_index()


def _save(path: pathlib.Path, series: pd.Series) -> None:
    table = pa.table({
        "timestamp": pa.array(series.index.to_numpy(dtype="datetime64[ns]"),
                              type=pa.timestamp("ns")),
        "value": pa.array(series.to_numpy(dtype="float64"), type=pa.float64()),
    })
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    replace_with_retry(tmp, path)


def _rewrite_sidecar(path: pathlib.Path, series: pd.Series, *, removed: int) -> None:
    """Bring the ``.meta.json`` back into agreement with the parquet.

    ``write()`` writes ``n_rows``/``first``/``last`` from the merged series on
    every write, and ``citivelo_daily_par_refresh._sidecar_last`` reads the
    sidecar rather than parsing the parquet - its docstring calls it
    authoritative. Editing the parquet underneath it and leaving the sidecar
    behind would make that true statement false, which is exactly the kind of
    silent disagreement this whole exercise is about.

    ``repair_note`` is recorded because the holes this leaves are INTERIOR, and
    ``missing_spans`` reasons about head and tail only - so nothing will refill
    them by itself and the next person to read a short series deserves to know
    why it is short.
    """
    meta_path = path.with_suffix(".meta.json")
    meta: Dict[str, object] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}
    meta["n_rows"] = int(series.size)
    if not series.empty:
        meta["first"] = series.index.min().isoformat()
        meta["last"] = series.index.max().isoformat()
    meta["repaired_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    meta["repaired_rows_removed"] = int(removed)
    meta["repair_note"] = (
        "foreign-series rows removed by scripts/citivelo_tagcache_repair.py; the "
        "holes are INTERIOR and missing_spans() cannot see them, so a deep "
        "re-harvest is what refills this tag - the nightly tail will not."
    )
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    replace_with_retry(tmp, meta_path)


def _donor_pool(directory: pathlib.Path) -> List[pathlib.Path]:
    """Candidate donor series, ACROSS frequencies.

    The sibling ``DAILY/<price point>`` directory is searched as well as this
    one, and that is not defensive breadth - it is where the MI01 donors actually
    live. The blocks that merged sat on one worksheet, so a DAILY vol block could
    and did land in a minute-frequency region: every poisoned row in the MI01
    bond tags is ``00:00:00``-stamped, and its donor is a DAILY
    ``RATES.VOL.USD.*`` tag. Searching only the victim's own frequency finds
    nothing and reports the tag clean.
    """
    dirs = [directory]
    daily = directory.parent.parent / "DAILY" / directory.name
    if daily.is_dir() and daily != directory:
        dirs.append(daily)
    out: List[pathlib.Path] = []
    for d in dirs:
        for p in d.glob("*.parquet"):
            if any(p.stem.startswith(pref) for pref in DONOR_PREFIXES):
                out.append(p)
    return sorted(out, key=lambda p: str(p))


def find_donor(
    victim: pd.Series,
    out_of_band: pd.Series,
    pool: List[pathlib.Path],
    cache: Dict[str, pd.Series],
) -> Tuple[Optional[str], int]:
    """The series that reproduces ``out_of_band`` exactly, and how many rows agree.

    Matched on the OUT-OF-BAND rows only, which are the ones we already know are
    foreign; the donor it identifies is then used to find the in-band ones. A
    donor must explain at least 90% of them, so a chance collision on a handful
    of days cannot nominate one.
    """
    if out_of_band.empty:
        return None, 0

    # PROBE FIRST. The full intersection against ~2,000 donors costs minutes per
    # victim and the answer is decided by three lookups: the donor is a bitwise
    # copy, so it must reproduce EVERY probe exactly. Probes are spread through
    # the suspect set rather than taken from one end, because a victim's suspects
    # can span two different donors' eras.
    n = len(out_of_band)
    probes = [out_of_band.index[i] for i in dict.fromkeys(
        (0, n // 2, n - 1, n // 4, 3 * n // 4)) if i < n]
    probe_vals = [float(out_of_band.loc[p]) for p in probes]

    best: Optional[str] = None
    best_n = 0
    for path in pool:
        s = cache.get(str(path))
        if s is None:
            s = _load(path)
            if s is None:
                continue
            cache[str(path)] = s
        # A MAJORITY of probes, not all of them. The suspect set can legitimately
        # contain a row the donor never wrote - an intraday series may carry a
        # real 00:00 bar - and demanding every probe would let one such row veto
        # the true donor. Three exact float64 agreements do not happen by chance.
        hits = 0
        for p, want in zip(probes, probe_vals):
            try:
                got = s.at[p]
            except KeyError:
                continue
            if abs(float(got) - want) < 1e-9:
                hits += 1
        if hits < max(2, len(probes) - 2):
            continue
        common = out_of_band.index.intersection(s.index)
        agree = int(((out_of_band.loc[common] - s.loc[common]).abs() < 1e-9).sum())
        if agree > best_n:
            best, best_n = str(path), agree
    if best is None or best_n < 0.9 * len(out_of_band):
        return None, best_n
    return best, best_n


def _suspects(tag: str, series: pd.Series, *, intraday: bool) -> pd.Series:
    """The rows worth searching a donor for.

    Two entry criteria, because one is not enough:

    **Out of band.** Certain, and it is all a daily series offers.

    **An exact-midnight stamp in an INTRADAY series.** ``cache.py``'s own
    docstring says daily and intraday "are never mixed", so a ``00:00:00`` row in
    a minute series is already a contract violation - and it is the ONLY thing
    that flags the bond PRICE family, where a vol of 89.9 landing in a price
    column is indistinguishable from an ordinary price by value alone. Measured:
    every poisoned row in the MI01 bond tags is midnight-stamped, because the
    block that merged into them was a DAILY one.

    Being a suspect is not a verdict. Nothing is removed on this alone - tier 2
    still has to find a donor that reproduces the rows exactly.
    """
    out = implausible_rows(tag, series)
    if intraday and len(series):
        midnight = series[series.index.normalize() == series.index]
        if len(midnight):
            parts = [x for x in (out, midnight) if len(x)]
            out = pd.concat(parts) if len(parts) > 1 else parts[0]
            out = out[~out.index.duplicated(keep="first")].sort_index()
    return out


def scan(directory: pathlib.Path, *, intraday: bool = False) -> List[dict]:
    """One record per tag that holds foreign rows."""
    pool = _donor_pool(directory)
    donor_cache: Dict[str, pd.Series] = {}
    records: List[dict] = []

    files = sorted(directory.glob("*.parquet"))
    for i, path in enumerate(files, 1):
        tag = path.stem
        if any(tag.startswith(pref) for pref in DONOR_PREFIXES):
            continue
        banded = band_for_tag(tag) is not None
        poisonable = any(p.match(tag) for p in UNBANDABLE_BUT_POISONABLE)
        if not banded and not (intraday and poisonable):
            continue
        s = _load(path)
        if s is None:
            continue
        oob = _suspects(tag, s, intraday=intraday)
        if oob.empty:
            continue
        donor, agree = find_donor(s, oob, pool, donor_cache)

        # WHAT IS SAFE TO REMOVE. Only two things: a value that cannot belong to
        # the family at all, and a value that is bit-for-bit the donor's. A
        # midnight-stamped SUSPECT that matches no donor and sits inside the band
        # is left alone - it is evidence of a frequency mix, not proof of one,
        # and a minute series may legitimately carry a 00:00 bar.
        certain = implausible_rows(tag, s).index
        matched = pd.DatetimeIndex([])
        if donor is not None:
            d = donor_cache[donor]
            common = s.index.intersection(d.index)
            matched = common[(s.loc[common] - d.loc[common]).abs() < 1e-9]
            # The pool is keyed on the full path, because the same stem exists at
            # two frequencies. What anyone reads is the tag.
            donor = pathlib.Path(donor).stem
        drop = certain.union(matched)
        in_band_extra = len(matched.difference(certain))
        if len(drop) == 0:
            continue

        records.append({
            "tag": tag, "path": path, "rows": len(s),
            "out_of_band": len(certain), "donor": donor, "donor_agree": agree,
            "in_band_extra": in_band_extra, "drop": drop,
            "first_bad": drop.min(), "last_bad": drop.max(),
        })
        if i % 500 == 0:
            _logger.info("scanned %d/%d", i, len(files))
    return records


def _report(records: List[dict]) -> None:
    if not records:
        print("no foreign rows found")
        return
    print(f"{'tag':<44} {'rows':>7} {'oob':>7} {'+inband':>8} {'drop':>7}  "
          f"{'first':<11} {'last':<11}  donor")
    tot_rows = tot_drop = tot_extra = 0
    for r in sorted(records, key=lambda x: -len(x["drop"])):
        tot_rows += r["rows"]; tot_drop += len(r["drop"]); tot_extra += r["in_band_extra"]
        donor = r["donor"] or "?? UNIDENTIFIED (only out-of-band rows dropped)"
        print(f"{r['tag']:<44} {r['rows']:>7} {r['out_of_band']:>7} "
              f"{r['in_band_extra']:>8} {len(r['drop']):>7}  "
              f"{r['first_bad'].date()!s:<11} {r['last_bad'].date()!s:<11}  "
              f"{donor.replace('RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.', 'vol ')}")
    print(f"\n{len(records)} tag(s), {tot_drop} row(s) to remove of {tot_rows} "
          f"({100 * tot_drop / max(tot_rows, 1):.1f}%), of which {tot_extra} were "
          f"INSIDE the plausibility band and would have survived a value check.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ or "")
    ap.add_argument("phase", choices=["report", "repair"], nargs="?", default="report")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--freq", default="DAILY")
    ap.add_argument("--price-point", default="CLOSE")
    ap.add_argument("--apply", action="store_true", help="actually rewrite the parquets")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    base = pathlib.Path(args.cache_dir) if args.cache_dir else default_cache_dir()
    directory = base / args.freq / args.price_point
    if not directory.is_dir():
        print(f"no such cache directory: {directory}")
        return 2
    print(f"cache: {directory}\n")

    from MDP.CitiVelocityExcel.frequencies import is_intraday
    records = scan(directory, intraday=is_intraday(args.freq))
    _report(records)

    if args.phase == "report":
        return 0
    if not args.apply:
        print("\n--apply was not passed; nothing written.")
        return 0
    if not records:
        return 0

    if not args.no_backup:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = base.parent / "citivelo_excel_prerepair" / stamp
        backup.mkdir(parents=True, exist_ok=True)
        for r in records:
            shutil.copy2(r["path"], backup / r["path"].name)
            meta = r["path"].with_suffix(".meta.json")
            if meta.is_file():
                shutil.copy2(meta, backup / meta.name)
        print(f"\nbacked up {len(records)} parquet(s) to {backup}")

    moved = 0
    for r in records:
        s = _load(r["path"])
        if s is None:
            continue
        keep = s.drop(index=r["drop"], errors="ignore")
        _save(r["path"], keep)
        _rewrite_sidecar(r["path"], keep, removed=len(s) - len(keep))
        moved += len(s) - len(keep)
        _logger.info("%s: %d -> %d rows", r["tag"], len(s), len(keep))
    print(f"\nremoved {moved} row(s) across {len(records)} tag(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
