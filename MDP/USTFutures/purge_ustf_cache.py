"""Purge cached UST futures snapshots / basis reports from the local store.

WHEN YOU NEED THIS
------------------
Most invalidation is automatic. Bumping ``_BASIS_REPORT_SCHEMA_VERSION`` in USTFuturesMDP retires
every cached basis report, and bumping ``_USTF_CACHE_VERSION`` / ``_USTF_BASKET_CACHE_VERSION``
retires the layered price cache and the basket-definition cache. Those are stamps rather than file
deletes on purpose: ``USTFutureStore._read_partition`` pulls a missing partition back from Supabase,
so deleting local files alone is silently undone by the next read.

The SNAPSHOT store has no such stamp -- its rows are just ``(symbol, timestamp_utc, trading_date,
session_minute, price)``. A snapshot poisoned by a wrong vendor root cannot be detected on read
either, because the value that was written looked like a plausible bond price. That is what this
tool is for.

    # see what would go
    python -m MDP.USTFutures.purge_ustf_cache --roots WN --kind snapshot --dry-run
    # do it
    python -m MDP.USTFutures.purge_ustf_cache --roots WN --kind snapshot

Deleting locally does not delete remotely. Where a Supabase sync is configured, a purged partition
will be re-pulled on the next read unless it is also overwritten there; the reliable way to replace
it is to re-run the read path with ``force_refresh=True``, which rewrites the partition (and pushes
it) rather than merely removing it.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

from Caching.ust_future_store import USTFutureStore

_KINDS = {"snapshot": "snapshots", "basis_report": "basis_reports"}


def _asset_root(symbol_dir: Path) -> str:
    name = symbol_dir.name
    if name.startswith("asset="):
        name = name[len("asset=") :]
    m = re.match(r"^([A-Z0-9]{1,3}?)[FGHJKMNQUVXZ]\d{1,2}$", name)
    return m.group(1) if m else name


def iter_partitions(base: Path, kind_dir: str, roots: Optional[Iterable[str]]) -> list[Path]:
    root_dir = base / kind_dir
    if not root_dir.exists():
        return []
    wanted = {r.strip().upper() for r in roots} if roots else None
    out: list[Path] = []
    for asset_dir in sorted(p for p in root_dir.iterdir() if p.is_dir()):
        if wanted is not None and _asset_root(asset_dir) not in wanted:
            continue
        out.append(asset_dir)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="*", default=None, help="internal roots, e.g. WN TY US. Omit for ALL.")
    ap.add_argument("--kind", default="snapshot", help="snapshot, basis_report, or both (comma-separated)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base-dir", default=None)
    args = ap.parse_args(argv)

    store = USTFutureStore.default() if args.base_dir is None else USTFutureStore(base_dir=args.base_dir)
    base = Path(store.base_dir)
    kinds = [k.strip() for k in str(args.kind).split(",") if k.strip()]
    unknown = [k for k in kinds if k not in _KINDS]
    if unknown:
        ap.error(f"unknown --kind {unknown}; choose from {sorted(_KINDS)}")

    print(f"store: {base}")
    total_days = 0
    for kind in kinds:
        assets = iter_partitions(base, _KINDS[kind], args.roots)
        print(f"\n{kind}: {len(assets)} matching asset(s)")
        for asset_dir in assets:
            days = sorted(asset_dir.glob("date=*"))
            total_days += len(days)
            print(f"  {'WOULD REMOVE' if args.dry_run else 'REMOVING'} {asset_dir.name}: {len(days)} day(s)")
            if not args.dry_run:
                shutil.rmtree(asset_dir, ignore_errors=True)
    print(f"\n{'would remove' if args.dry_run else 'removed'} {total_days} day-partition(s)")
    if not args.dry_run and total_days:
        print(
            "NOTE: where a Supabase sync is configured these will be re-pulled on next read.\n"
            "      Re-run the read path with force_refresh=True to overwrite them instead."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
