"""Build the Strategy-2 deep-pack panels off the Q20 STIR curve.

    C:/Users/chris/anaconda3/envs/stir/python.exe scripts/strat2_q20_build.py [workers]

Outputs, all under ``notebooks/data/convexity_rv/``:

``strat2_q20_panel.parquet``
    One row per (date, pack window). Carries **both** rate sources -- the Q20
    IMM x IMM forward and the raw SR3 settle -- their two convexity adjustments,
    the three gate conditions and every measurement the gate was derived from.
    Nothing is filtered here; the gate travels *with* the panel so a filter
    applied in one notebook is not a filter the next reader silently omits.

``strat2_q20_rates.parquet``
    Date -> 2y/5y/10y ``USD-SOFR-1D`` par rates, for the 2s5s10s hedge
    regression. Same shape ``strat2_sofr_convexity.build_panel`` returns.

``strat2_q20_settles.parquet``
    Date x contract SR3 settle PRICES. This is the input ``ca_staleness`` needs
    -- its three detectors run on the raw price panel, not on the adjustment,
    because that is where the defect lives.

``strat2_q20_skips.json``
    Skip tally by reason, plus the blocked-request count. The effective window
    is then an observable rather than an assumption.


NETWORK
=======
Every worker computes inside ``listed_cache_guard.cache_only()``: outbound HTTP
raises instead of being sent. This is not belt-and-braces, it is load-bearing --
``IRSwapsMDP.get_pricer`` for a ``*STIRT`` curve makes 52-57 Barchart requests
per date on this machine (the Q20 curve store is empty and the production
builder's fetcher points at the intraday source), so an unguarded 1,400-date run
is a ~75,000-request crawl. ``strat2_q20.build_q20_pricer`` avoids that path
entirely; the guard is what proves it stayed avoided, and the blocked count is
written to the sidecar. **It must be zero.**

The requests patch does not cross a process boundary, so the guard is applied
inside ``_chunk`` -- in the worker -- not around the executor.


UNIVERSE
========
``strat2_q20.strip_depth_by_date`` reads the SR3 diskcache's sqlite shards
directly and returns the length of the *contiguous* front strip per date. Depth
is variable and used as such: a date of depth 16 quotes pack windows up to rank
13 (Blues) and a date of depth 20 up to rank 17 (Golds). A fixed all-20 rule
would discard ~500 Blues dates for nothing.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

OUT = _REPO / "notebooks" / "data" / "convexity_rv"
PANEL = OUT / "strat2_q20_panel.parquet"
RATES = OUT / "strat2_q20_rates.parquet"
SETTLES = OUT / "strat2_q20_settles.parquet"
SIDECAR = OUT / "strat2_q20_skips.json"

#: Citi's published SOFR screen is windows 5..17 (Reds through Golds). The panel
#: is built for windows 1..(depth-3) regardless -- ranking uses a sub-range, but
#: the 3m roll of window ``r`` is measured against window ``r-1``, and the
#: cross-source comparison wants the near windows as the known-bad control.
RANK_START = 5
N_PACKS = 13

#: Two-year par tenors for the 2s5s10s regression.
HEDGE_TENORS = ("2Y", "5Y", "10Y")


def _worker_init() -> None:
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))


def _chunk(items) -> dict:
    """One chunk of ``(date, depth)`` pairs -> rows + tallies. Runs in a worker."""
    _worker_init()

    import RVUtils.ConvexityRV.strat2_q20 as Q
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.ConvexityRV.listed_cache_guard import cache_only, network_calls_blocked
    from RVUtils.ConvexityRV.packs import quarterly_imm_sequence
    from RVUtils.ConvexityRV.strat2_sofr_convexity import _swap_par_rate, futures_symbol

    cfg = Q.Q20Config()
    s2 = Q.deep_pack_config(rank_start=RANK_START, n_packs=N_PACKS)
    builder = Q.Q20Builder(cfg)
    swaps = IRSwapsMDP(source=cfg.swap_source)

    rows, rate_rows, settle_rows = [], [], []
    failed: list = []
    skips = {"ok": 0, "swap_curve": 0, "swap_ref_mismatch": 0, "q20_build": 0,
             "no_settles": 0, "error": 0, "q20_unbuilt": 0}
    n_blocked_0 = network_calls_blocked()

    for d, depth in items:
        try:
            try:
                pricer = swaps.get_pricer({"curve_name": cfg.swap_curve,
                                           "timestamp": d, "offline": True})
            except Exception:                                   # noqa: BLE001
                skips["swap_curve"] += 1
                failed.append((d, depth))
                continue
            ref = pricer.reference_date()
            ref = ref.date() if hasattr(ref, "date") else ref
            if ref != d:
                skips["swap_ref_mismatch"] += 1
                continue

            with cache_only():
                try:
                    r = Q.day_rows(d, depth, cfg=cfg, s2cfg=s2, builder=builder,
                                   swap_pricer=pricer)
                except Exception:                               # noqa: BLE001
                    skips["q20_build"] += 1
                    failed.append((d, depth))
                    continue
                setl = builder.settles(d, depth)

            if not r:
                skips["no_settles"] += 1
                failed.append((d, depth))
                continue
            # A date whose Q20 curve would not build is KEPT -- its settle rows
            # are real -- but it is counted, because a blocked request has to be
            # explainable and this is now the explanation for most of them.
            if not r[0].get("q20_built", True):
                skips["q20_unbuilt"] += 1
            rows.extend(r)

            row = {"date": pd.Timestamp(d)}
            for t in HEDGE_TENORS:
                row[t] = _swap_par_rate(pricer, cfg.swap_curve, tenor=t)
            rate_rows.append(row)

            seq = quarterly_imm_sequence(d, depth)
            for (y, m), rate in ((k, setl[k]) for k in seq if k in setl):
                settle_rows.append({"date": pd.Timestamp(d),
                                    "contract": futures_symbol(y, m, cfg.futures_root),
                                    "rank": seq.index((y, m)) + 1,
                                    "price": 100.0 - rate})
            skips["ok"] += 1
        except Exception:                                       # noqa: BLE001
            skips["error"] += 1
            failed.append((d, depth))
            continue

    skips["blocked_requests"] = network_calls_blocked() - n_blocked_0
    return {"rows": rows, "rates": rate_rows, "settles": settle_rows,
            "skips": skips, "failed": failed}


def build(workers: int = 6) -> pd.DataFrame:
    import RVUtils.ConvexityRV.strat2_q20 as Q

    t0 = time.time()
    cfg = Q.Q20Config()
    depths = Q.strip_depth_by_date(cfg)
    # THE RUNNING SESSION IS NOT A SETTLE. Both legs of the adjustment are still
    # moving today: the 17:00 EOD alias holds whatever the vendor served when it
    # was last requested, and the CITIVELO swap curve for today re-prices through
    # the session. Measured 2026-08-19 -- two builds forty minutes apart
    # disagreed on today's 10Y par rate by 0.046% while every one of the other
    # 1,945 dates agreed to 1e-9. Including it makes the panel unreproducible and
    # marks a live quote as a settlement mark; excluding it costs one date.
    today = dt.date.today()
    dropped_today = [d for d in depths if d >= today]
    items = sorted((d, v) for d, v in depths.items() if d < today)
    if dropped_today:
        print(f"excluding the running session: {dropped_today}", flush=True)
    print(f"universe: {len(items)} dates {items[0][0]}..{items[-1][0]} "
          f"({time.time() - t0:.0f}s)", flush=True)
    by_depth = pd.Series([v for _, v in items]).value_counts().sort_index()
    print("strip depth distribution:\n" + by_depth.to_string(), flush=True)
    for r in (5, 9, 13, 17):
        n = sum(1 for _, v in items if Q.max_rank_for_depth(v) >= r)
        print(f"  dates able to quote rank {r:>2d} "
              f"({Q.depth_for_rank(r)} contracts): {n}", flush=True)

    size = max(10, len(items) // (workers * 4))
    chunks = [items[i:i + size] for i in range(0, len(items), size)]
    print(f"scan: {len(chunks)} chunks x ~{size} dates, {workers} workers", flush=True)

    rows, rate_rows, settle_rows, skips = [], [], [], {}
    failed: list = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_chunk, c): k for k, c in enumerate(chunks)}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            rows.extend(r["rows"])
            rate_rows.extend(r["rates"])
            settle_rows.extend(r["settles"])
            failed.extend(r.get("failed", []))
            for k, v in r["skips"].items():
                skips[k] = skips.get(k, 0) + v
            done += 1
            print(f"  chunk {done}/{len(chunks)} ({len(rows)} rows, "
                  f"{time.time() - t0:.0f}s)", flush=True)

    # --- serial retry of every skipped date --------------------------------
    # Six workers share eight sqlite shards, and contention on them surfaces as a
    # cache MISS rather than as a lock error: the MDP shrugs, reaches for the
    # vendor, and `cache_only()` turns that into an exception. The result was a
    # build whose skipped dates changed from run to run -- 2022-06-22 dropped in
    # one pass and priced cleanly in the next, with 0 blocked requests. That
    # nondeterminism is fatal to a before/after comparison, so every skipped date
    # is retried ONCE, serially, in the parent. Dates that fail both times are
    # genuine (holidays whose swap curve serves the previous close, mostly) and
    # stay counted.
    if failed:
        print(f"\nretrying {len(failed)} skipped dates serially "
              f"({time.time() - t0:.0f}s)", flush=True)
        rr = _chunk(sorted(set(failed)))
        rows.extend(rr["rows"])
        rate_rows.extend(rr["rates"])
        settle_rows.extend(rr["settles"])
        skips["retry_recovered"] = int(rr["skips"]["ok"])
        skips["retry_failed"] = len(rr.get("failed", []))
        skips["retry_q20_build"] = int(rr["skips"]["q20_build"])
        skips["retry_swap_ref_mismatch"] = int(rr["skips"]["swap_ref_mismatch"])
        skips["q20_unbuilt"] = skips.get("q20_unbuilt", 0) + int(rr["skips"]["q20_unbuilt"])
        skips["blocked_requests"] = (skips.get("blocked_requests", 0)
                                     + rr["skips"].get("blocked_requests", 0))
        print(f"  recovered {skips['retry_recovered']}, still failing "
              f"{skips['retry_failed']}", flush=True)

    panel = pd.DataFrame(rows).sort_values(["date", "rank"]).reset_index(drop=True)
    rates = pd.DataFrame(rate_rows).set_index("date").sort_index()
    settles = (pd.DataFrame(settle_rows)
               .pivot_table(index="date", columns="contract", values="price",
                            aggfunc="last").sort_index())

    OUT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL)
    rates.to_parquet(RATES)
    settles.to_parquet(SETTLES)
    SIDECAR.write_text(json.dumps({
        "skips": skips,
        "n_rows": int(len(panel)),
        "n_dates": int(panel["date"].nunique()),
        "date_min": str(panel["date"].min()),
        "date_max": str(panel["date"].max()),
        "universe_dates": len(items),
        "rank_min": int(panel["rank"].min()),
        "rank_max": int(panel["rank"].max()),
        "gate": {c: float(panel[c].mean()) for c in panel.columns
                 if c.startswith("gate_")},
        "availability": {
            "rows_q20_built": int(panel["q20_built"].sum()) if "q20_built" in panel else None,
            "rows_settle_finite": int(np.isfinite(panel["ca_bp_settle"]).sum()),
            "dates_by_max_rank": {str(k): int(v) for k, v in
                                  panel.groupby("date")["max_rank_available"].max()
                                  .value_counts().sort_index().items()}
            if "max_rank_available" in panel else None,
        },
    }, indent=2))

    print(f"\n{len(panel)} rows x {panel['date'].nunique()} dates -> {PANEL} "
          f"({time.time() - t0:.0f}s)")
    print(f"skips: {skips}")

    # Two different statements, and conflating them hides a real defect.
    #
    #   blocked == 0  means nothing was even ATTEMPTED.
    #   blocked  > 0  means something was attempted and REFUSED -- nothing left
    #                 this machine either way, but a code path reached for the
    #                 vendor and that has to be explained.
    #
    # A date with genuinely no local data will always attempt once and fail;
    # that is the guard working. Since 2026-08-19 such a date is no longer
    # dropped -- ``day_rows`` degrades to settle-only rows and records
    # ``q20_built=False`` -- so the attempt is now explained by EITHER a skipped
    # date (``q20_build``) OR a kept-but-unbuilt one (``q20_unbuilt``). What must
    # never happen is a blocked request that neither explains, because that would
    # mean a fully successful row was assembled by a path willing to fetch.
    blocked = skips.get("blocked_requests", 0)
    failed = (skips.get("q20_build", 0) + skips.get("q20_unbuilt", 0)
              + skips.get("retry_failed", 0))
    assert not (blocked and not failed), (
        f"{blocked} outbound requests were blocked on dates that all succeeded -- "
        "a code path reached for the network on a good date. Investigate before "
        "trusting this panel.")
    print(f"blocked requests: {blocked} (attempted, refused, nothing sent) "
          f"across {failed} dates with no local Q20 curve")
    n_unbuilt = int((~panel["q20_built"]).sum()) if "q20_built" in panel else 0
    print(f"rows with no Q20 curve (settle-only, recorded as data): {n_unbuilt:,}")
    return panel


if __name__ == "__main__":
    build(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
