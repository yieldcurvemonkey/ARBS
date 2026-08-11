"""Warm everything a notebook kernel cannot fetch for itself.

Barchart's fetcher calls ``asyncio.run``. Inside a Jupyter kernel there is
already a running event loop, so it returns an un-awaited coroutine rather than
data -- and treating that as an empty day is how a whole sensitivity sweep ends
up computed from nothing. So the notebooks REFUSE to fetch, and this runs first
from a plain process.

    python econ_fade_prewarm.py --stage events
    python econ_fade_prewarm.py --stage bars
    python econ_fade_prewarm.py --stage dv01
    python econ_fade_prewarm.py --stage all

Bars are fetched by RANGE, one call per contract, not per day. Measured: a
3-month 1-minute window is 48,151 rows in 3.6s for SR3 and 79,044 for ZN.
Day-by-day the same coverage is thousands of calls against a 55-request/60s
ceiling.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent))

import pandas as pd  # noqa: E402

import econ_fade_common as G  # noqa: E402

EVENTS_PKL = G.CACHE / "events_raw.pkl"
LEDGER = G.CACHE / "warm_ledger.json"

DEFAULT_START = "2019-01-01"
DEFAULT_END = datetime.date.today().isoformat()

#: Which ranks to warm for each instrument. STIR goes deep along the strip
#: because that is the knob the notebook sweeps; UST holds the front two.
WARM_RANKS: Dict[str, Sequence[int]] = {
    "USD_STIR": (1, 2, 3, 4, 5, 6, 7, 8),
    "ZQ": (1, 2, 3, 4, 5, 6),
    "TU": (1, 2), "FV": (1, 2), "TY": (1, 2), "US": (1, 2),
}


def _load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"bars_done": [], "bars_empty": [], "dv01_done": []}


def _save_ledger(led: dict) -> None:
    LEDGER.write_text(json.dumps(led, indent=1, sort_keys=True))


# ---------------------------------------------------------------- events
def stage_events(start: str, end: str) -> pd.DataFrame:
    print(f"reading the ForexFactory store {start} -> {end} (local, no network)")
    cal = G.load_calendar(start, end)
    print(f"  {len(cal):,} calendar rows")
    raw = G.build_raw_events(cal, currencies=("USD",), impacts=G.TIER12)
    with open(EVENTS_PKL, "wb") as f:
        pickle.dump(raw, f, protocol=4)
    print(f"  {len(raw):,} release MINUTES on {raw['date'].nunique():,} days")
    print(f"  tier 1 minutes: {int((raw['impact_rank'] == 3).sum()):,}")
    print(f"  data releases : {int(raw['any_release'].sum()):,}  "
          f"(non-data: {int((~raw['any_release']).sum()):,})")
    print(f"  wrote {EVENTS_PKL}")
    return raw


def load_events() -> pd.DataFrame:
    if not EVENTS_PKL.exists():
        raise FileNotFoundError(
            f"{EVENTS_PKL} missing -- run `python econ_fade_prewarm.py --stage events`")
    with open(EVENTS_PKL, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------- symbols
def symbols_needed(raw: pd.DataFrame,
                   ranks: Dict[str, Sequence[int]] = None,
                   ) -> Dict[str, Dict[str, object]]:
    """symbol -> {instrument, first date needed, last date needed}.

    One entry per CONTRACT, so a symbol used by rank 3 in March and rank 2 in
    June is fetched once over the union of the two windows.
    """
    ranks = ranks or WARM_RANKS
    dates = sorted(raw["date"].unique())
    span: Dict[str, Dict[str, object]] = {}
    for key, rr in ranks.items():
        inst = G.INSTRUMENTS[key]
        lo = inst.bars_from
        for d in dates:
            if lo is not None and d < lo:
                continue
            for r in rr:
                sym = G.contract_for(inst, d, r)
                e = span.setdefault(sym, {"instrument": key, "first": d, "last": d})
                if d < e["first"]:
                    e["first"] = d
                if d > e["last"]:
                    e["last"] = d
    return span


# ---------------------------------------------------------------- bars
def stage_bars(raw: pd.DataFrame, *, only: Sequence[str] = (), force: bool = False) -> None:
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    G.load_bar_cache()
    led = _load_ledger()
    done = set(led["bars_done"]) | set(led["bars_empty"])

    span = symbols_needed(raw)
    if only:
        span = {s: v for s, v in span.items() if v["instrument"] in set(only)}
    todo = [s for s in sorted(span) if force or s not in done]
    print(f"{len(span)} contracts needed, {len(todo)} to fetch")

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=6)

    t0 = time.time()
    for i, sym in enumerate(todo, 1):
        e = span[sym]
        inst = G.INSTRUMENTS[e["instrument"]]
        # Pad so a release on the first or last day still has a full session.
        start = e["first"] - datetime.timedelta(days=3)
        end = e["last"] + datetime.timedelta(days=3)
        n = G.warm_symbol(fetcher, sym, start, end, inst.tz)
        if n:
            led["bars_done"].append(sym)
        else:
            led["bars_empty"].append(sym)
        print(f"[{i:>3}/{len(todo)}] {sym:<8} {start} -> {end}  {n:>4} days  "
              f"{'' if n else G.FETCH_FAILURES.get(sym, '')}  ({time.time()-t0:.0f}s)")
        if i % 10 == 0:
            G.save_bar_cache()
            _save_ledger(led)

    n = G.save_bar_cache()
    _save_ledger(led)
    print(f"\nbar cache: {n:,} symbol-days  ({time.time()-t0:.0f}s)")
    if led["bars_empty"]:
        print(f"no usable bars for {len(led['bars_empty'])} contracts: "
              f"{', '.join(sorted(set(led['bars_empty']))[:20])}")


# ---------------------------------------------------------------- dv01
def stage_dv01(raw: pd.DataFrame) -> None:
    """A UST price cannot be turned into basis points without its CTD's DV01.

    Measured once per CONTRACT, not per root: a 10-year future's DV01 ran
    $58.08 in 2022 and $69.05 in 2019, so a per-root constant would be a fifth
    wrong at the ends of the sample.
    """
    G.load_dv01()
    span = symbols_needed(raw)
    ust = sorted(s for s, v in span.items()
                 if G.INSTRUMENTS[v["instrument"]].family == "ust")
    todo = [s for s in ust if s not in G._DV01]
    print(f"{len(ust)} UST contracts, {len(todo)} to measure")
    if todo:
        t0 = time.time()
        G.measure_ust_dv01(todo)
        print(f"  measured in {time.time()-t0:.0f}s")
    n = G.save_dv01()
    print(f"DV01 table: {n} contracts -> {G.DV01_JSON}")
    if G._DV01:
        by_root = defaultdict(list)
        for s, v in G._DV01.items():
            by_root[s[:2]].append(v)
        for r, vs in sorted(by_root.items()):
            print(f"  {r}: {len(vs):>3} contracts, ${min(vs):.2f} - ${max(vs):.2f} /bp")
    failed = {k: v for k, v in G.FETCH_FAILURES.items() if k.startswith("dv01:")}
    if failed:
        print(f"FAILED {len(failed)}: {list(failed)[:10]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["events", "bars", "dv01", "all", "symbols"])
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--only", nargs="*", default=[],
                    help="restrict bar warm to these instrument keys")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    raw = stage_events(a.start, a.end) if a.stage in ("events", "all") else load_events()

    if a.stage == "symbols":
        span = symbols_needed(raw)
        for s, v in sorted(span.items()):
            print(f"{s:<8} {v['instrument']:<9} {v['first']} -> {v['last']}")
        print(f"\n{len(span)} contracts")
        return

    if a.stage in ("bars", "all"):
        stage_bars(raw, only=a.only, force=a.force)
    if a.stage in ("dv01", "all"):
        stage_dv01(raw)


if __name__ == "__main__":
    main()
