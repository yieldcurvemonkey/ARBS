r"""Fetch the FedLock datasets and rebuild the committed snapshots.

    conda run -n stir python notebooks/rv/fedlock_refresh.py          # V3 + V2
    conda run -n stir python notebooks/rv/fedlock_refresh.py --only v3

Kept out of the notebook on purpose. There is no COM hazard here -- it is a
plain HTTPS GET -- but the deeper reason from the surprise side applies with
more force:

**A FedLock refresh is a new vintage in which history moves.** The corpus grows
daily, new speeches enter the pairwise tournament, and TrueSkill re-rates
*existing* speeches against them. So re-running this does not append to the
series, it replaces it. The V2-vs-V3 comparison in the notebook measures how far
that can go: swapping the judge model moved a typical speech by half a standard
deviation.

V2 is the frozen Gemini-2.0-Flash predecessor, preserved by the project at
``/fedlock/v2/``. It is fetched only so the notebook can measure that movement.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import urllib.request

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(REPO), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fedlock_data import (  # noqa: E402
    DEFAULT_SNAPSHOT,
    DEFAULT_SNAPSHOT_V2,
    URL_V2,
    URL_V3,
    parse_payload,
)


def fetch(url: str, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ARBS-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode("utf-8"))


def build(url: str, out: pathlib.Path, label: str) -> None:
    payload = fetch(url)
    frame, prov = parse_payload(payload)
    frame.to_parquet(out, index=False)
    meta = {
        "dataset": label,
        "url": url,
        "fetched": datetime.datetime.now().isoformat(timespec="seconds"),
        "first": str(frame["date"].min().date()),
        "last": str(frame["date"].max().date()),
        **prov,
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str),
                                        encoding="utf-8")
    print(f"{label}: {len(frame)} dated speeches "
          f"({prov['n_undated']} undated dropped of {prov['n_rows']}), "
          f"{meta['first']} -> {meta['last']}, builtOn {prov.get('built_on')}")
    print(f"  -> {out} ({out.stat().st_size / 1024:.0f} KB)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=("v2", "v3"), default=None)
    args = ap.parse_args(argv)
    if args.only in (None, "v3"):
        build(URL_V3, DEFAULT_SNAPSHOT, "fedlock_v3")
    if args.only in (None, "v2"):
        build(URL_V2, DEFAULT_SNAPSHOT_V2, "fedlock_v2 (frozen Gemini run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
