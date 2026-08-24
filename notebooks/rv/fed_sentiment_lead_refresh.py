r"""Rebuild the Citi surprise snapshot the lead study reads.

The surprise side of this study is a ``CVTSHIST`` pull, not a static file, so it
is reachable live through the Citi Velocity add-in and the chart re-runs
tomorrow without a manual re-export. The tag list below is taken verbatim from
cell A1 of the hand-exported workbook::

    =CVTSHIST("<tags>", "DAILY", "MAX", , , "CLOSE")

**Why this is a separate command rather than a cell in the notebook.** Every
Velocity fetch runs through a human-logged-in Excel over COM; driving that from
inside ``nbconvert`` is a measured hazard in this repo (a holiday date bound
alone has taken Excel down). So the notebook reads a committed snapshot and
prints its provenance, and refreshing is an explicit act::

    # from the workbook already on disk (no Excel, no network)
    conda run -n stir python notebooks/rv/fed_sentiment_lead_refresh.py --xlsx

    # from the live add-in, into a STUDY-LOCAL tag cache
    conda run -n stir python notebooks/rv/fed_sentiment_lead_refresh.py --live

``--live`` writes into ``notebooks/rv/.citivelo_cache`` rather than the shared
``%LOCALAPPDATA%`` tag store. The shared store is read by the production
``citivelo_excel`` source; a series seeded here would be indistinguishable from
one it fetched itself, and this study does not need to put that question into
anyone else's data.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from notebooks.rv.fed_sentiment_lead_data import (  # noqa: E402
    DEFAULT_SNAPSHOT,
    DEFAULT_XLSX,
    SNAPSHOT_TAGS,
    read_surprise_xlsx,
)

#: Study-local Citi tag cache. Never the shared one.
LOCAL_CACHE = HERE / ".citivelo_cache"


def _write(frame: pd.DataFrame, meta: dict, out: pathlib.Path) -> None:
    keep = [c for c in SNAPSHOT_TAGS if c in frame.columns]
    missing = [c for c in SNAPSHOT_TAGS if c not in frame.columns]
    sub = frame[keep].copy()
    sub = sub.dropna(how="all")
    sub.to_parquet(out)
    meta = dict(meta)
    meta.update(
        {
            "built": datetime.datetime.now().isoformat(timespec="seconds"),
            "rows": int(len(sub)),
            "tags": len(keep),
            "missing_tags": missing,
            "first": str(sub.index.min().date()),
            "last": str(sub.index.max().date()),
        }
    )
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {out} -- {len(sub)} rows x {len(keep)} tags, "
          f"{sub.index.min().date()} -> {sub.index.max().date()}")
    if missing:
        print(f"  MISSING {len(missing)} tag(s): {missing}")


def from_xlsx(path: str, out: pathlib.Path) -> None:
    frame = read_surprise_xlsx(path)
    _write(frame, {"source": "xlsx", "path": path, "call": "CVTSHIST DAILY MAX CLOSE"}, out)


def from_live(out: pathlib.Path, *, freq: str = "DAILY", period: str = "MAX") -> None:
    """One ``CVTSHIST`` call per span, into the study-local cache, then snapshot.

    ``period`` must come from the add-in's CLOSED vocabulary -- an invalid value
    returns nothing at all, silently, which is indistinguishable from a tag with
    no data. ``MAX`` is the value cell A1 uses.
    """
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

    LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
    cache = CitiVeloTagCache(base_dir=LOCAL_CACHE)
    client = CitiVelocityExcelClient()
    try:
        def fetcher(tags, freq_token, span_start, span_end, point_token):
            kwargs = {"price_point": point_token}
            if span_start is None and span_end is None:
                kwargs["period"] = period
            else:
                kwargs["start"], kwargs["end"] = span_start, span_end
            return client.fetch_timeseries(list(tags), freq_token, **kwargs)

        series = cache.get(list(SNAPSHOT_TAGS), freq, fetcher=fetcher, force_refresh=True)
        failures = client.last_failures()
    finally:
        try:
            client.close()
        except Exception:
            pass
    if not series:
        raise SystemExit("live fetch returned nothing; snapshot NOT rewritten")
    frame = pd.concat(series, axis=1).sort_index()
    frame.index.name = "date"
    _write(
        frame,
        {
            "source": "live CVTSHIST",
            "cache": str(LOCAL_CACHE),
            "call": f"CVTSHIST {freq} {period} CLOSE",
            "failures": failures,
        },
        out,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", nargs="?", const=DEFAULT_XLSX, default=None,
                    help="rebuild from the hand-exported workbook")
    ap.add_argument("--live", action="store_true",
                    help="rebuild from the live Velocity add-in (needs Excel)")
    ap.add_argument("--out", default=str(DEFAULT_SNAPSHOT))
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    if args.live:
        from_live(out)
    elif args.xlsx:
        from_xlsx(args.xlsx, out)
    else:
        ap.error("pass --xlsx or --live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
