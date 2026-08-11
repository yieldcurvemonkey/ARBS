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


# ---------------------------------------------------------------- verify
def coverage_report(raw: pd.DataFrame) -> pd.DataFrame:
    """Per contract: what was asked for, what is stored, and whether the shape
    of what is stored looks like a TRUNCATED fetch.

    A back-month contract that genuinely was not trading yet ramps UP -- a
    handful of bars a day at first, a full session later. Measured on ZFM22:
    48 bars across the 13 days from 2021-11-23, against ~870/day once it became
    the front contract.

    A fetch that stopped early looks nothing like that. ``barchart_timeseries_api``
    pages intraday BACKWARD in 5,000-row slices and gives up when a slice makes
    no progress, so an interrupted fetch loses the OLDEST end and leaves the
    first stored day already carrying a FULL session. Measured: FVM25 was stored
    with 10 days and exactly 10,000 rows -- 1,000 a day from the very first one
    -- where a re-fetch of the identical window returns 111 days and 87,482 rows.

    So the discriminator is bars-per-day at the START of what was stored, not
    the size of the gap.
    """
    G.load_bar_cache()
    span = symbols_needed(raw)
    by_sym: Dict[str, List[datetime.date]] = defaultdict(list)
    for (s, d) in G._BAR_CACHE:
        by_sym[s].append(d)

    rows = []
    for sym, want in sorted(span.items()):
        ds = sorted(by_sym.get(sym, []))
        if not ds:
            rows.append({"symbol": sym, "instrument": want["instrument"],
                         "want_first": want["first"], "got_first": None,
                         "days": 0, "rows": 0, "head_bars_per_day": 0.0,
                         "gap_days": None, "verdict": "no_bars"})
            continue
        n_rows = sum(len(G._BAR_CACHE[(sym, d)]) for d in ds)
        head = ds[:3]
        head_bpd = sum(len(G._BAR_CACHE[(sym, d)]) for d in head) / len(head)
        gap = (ds[0] - want["first"]).days
        if gap > 10 and head_bpd > 300:
            verdict = "TRUNCATED"
        elif gap > 10:
            verdict = "thin_back_month"
        else:
            verdict = "ok"
        rows.append({"symbol": sym, "instrument": want["instrument"],
                     "want_first": want["first"], "got_first": ds[0],
                     "days": len(ds), "rows": n_rows,
                     "head_bars_per_day": round(head_bpd, 1),
                     "gap_days": gap, "verdict": verdict})
    return pd.DataFrame(rows)


def stage_verify(raw: pd.DataFrame, *, repair: bool = True,
                 chunk_days: int = 100) -> pd.DataFrame:
    """Report coverage, and re-fetch anything that looks truncated in CHUNKS.

    Chunking is the repair, not a retry: a smaller window is a smaller backward
    page walk, so it cannot exhaust the slice budget. The cache is keyed per
    (symbol, day), so a second pass MERGES rather than replaces -- a repair can
    only add days.
    """
    rep = coverage_report(raw)
    bad = rep[rep.verdict.isin(["TRUNCATED", "no_bars"])]
    print(rep.groupby("verdict").size().to_string())
    if not len(bad) or not repair:
        return rep

    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=6)
    span = symbols_needed(raw)

    print(f"\nre-fetching {len(bad)} contracts in {chunk_days}-day chunks")
    for i, r in enumerate(bad.itertuples(), 1):
        sym = r.symbol
        inst = G.INSTRUMENTS[span[sym]["instrument"]]
        start = span[sym]["first"] - datetime.timedelta(days=3)
        end = span[sym]["last"] + datetime.timedelta(days=3)
        before = sum(1 for (s, _d) in G._BAR_CACHE if s == sym)
        cur = start
        while cur <= end:
            nxt = min(cur + datetime.timedelta(days=chunk_days), end)
            G.warm_symbol(fetcher, sym, cur, nxt, inst.tz)
            cur = nxt + datetime.timedelta(days=1)
        after = sum(1 for (s, _d) in G._BAR_CACHE if s == sym)
        print(f"[{i:>3}/{len(bad)}] {sym:<8} {before:>4} -> {after:>4} days "
              f"({after - before:+d})")
        if i % 10 == 0:
            G.save_bar_cache()

    G.save_bar_cache()
    rep2 = coverage_report(raw)
    print("\nafter repair:")
    print(rep2.groupby("verdict").size().to_string())
    still = rep2[rep2.verdict.isin(["TRUNCATED", "no_bars"])]
    if len(still):
        print(f"\n{len(still)} contracts still short after a chunked re-fetch "
              f"(the vendor has no more):")
        print(still[["symbol", "want_first", "got_first", "days", "rows",
                     "head_bars_per_day"]].to_string(index=False))
    return rep2


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


# ---------------------------------------------------------------- mdp cache
#: The pure-MDP notebook prices only USD STIR, so only these need priming.
#: Rank 3 is the configured leg; the others let the notebook price the strip
#: through the same provider without a second prime.
MDP_RANKS = (1, 2, 3, 4)


def stage_mdpcache(raw: pd.DataFrame, *, impacts: Sequence[str] = ("high", "medium")) -> None:
    """Write warmed Barchart bars into STIRFutureMDP's OWN cache.

    Barchart's fetcher cannot run inside a Jupyter kernel, so a notebook that
    drives the real MDP has to read from a cache somebody else filled. This
    fills it -- with genuine bars, under the MDP's own key contract, for exactly
    the minutes the backtest will request and no others.
    """
    import econ_fade_mdp as M

    n0 = G.load_bar_cache()
    print(f"bar cache: {n0:,} symbol-days")

    import econ_fade_config as C

    # The wrong-day placebo asks for DIFFERENT minutes, so it needs priming too.
    # Without this it would come back with an empty book and read as "the
    # placebo makes nothing" -- the most flattering possible failure.
    books = {"real": raw, "placebo +1bd": C.placebo_shift(raw, days=1)}

    mdp = M.open_mdp(armed=True)          # priming writes, it does not fetch
    total = {"written": 0, "no_bar": 0, "no_day": 0}
    for label, src in books.items():
        for rank in MDP_RANKS:
            cfg = M.merge_config({"instrument": {"root": "USD_STIR", "rank": rank},
                                  "events": {"impacts": list(impacts)}})
            wanted = M.wanted_timestamps(src, cfg)
            print(f"{label}, rank {rank}: {len(wanted):,} (symbol, minute) requests")
            st = M.prime_mdp_cache(mdp, wanted)
            for k, v in st.items():
                total[k] += v
            print(f"  written {st['written']:,}   no bar that minute {st['no_bar']:,}   "
                  f"no bars that day {st['no_day']:,}")

    print(f"\nTOTAL written {total['written']:,}   "
          f"minute had no print {total['no_bar']:,}   day not warmed {total['no_day']:,}")
    print("A minute with no print stays a miss on purpose: the notebook's gate is")
    print("'can the MDP price this', so an unprinted minute becomes a counted exclusion.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["events", "bars", "verify", "dv01", "mdpcache", "all", "symbols"])
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
    if a.stage in ("verify", "all"):
        rep = stage_verify(raw)
        rep.to_csv(G.CACHE / "coverage_report.csv", index=False)
        print(f"wrote {G.CACHE / 'coverage_report.csv'}")
    if a.stage in ("dv01", "all"):
        stage_dv01(raw)
    if a.stage in ("mdpcache", "all"):
        stage_mdpcache(raw)


if __name__ == "__main__":
    main()
