r"""Backfill Citi Velocity intraday marks for the TLT 20-31y universe.

Layers, cheapest first
----------------------
``hourly``
    Whole universe, ``YIELD`` + ``PRICE``, back to the measured floor. This is
    the layer that answers the 15:00-versus-16:00 question: an hourly series
    carries both stamps, so it resolves the seam over the whole history for a
    fraction of the cost of minute data.
``asof``
    ``ASS_SOFR`` at ``HOURLY``. Kept separate because its intraday retention is
    MEASURED at roughly nine months where ``YIELD``/``PRICE`` reach 2019-11-17 -
    asking for it over the full range would spend five years of windows to
    receive five years of empty blocks.
``mi01``
    ``YIELD`` + ``PRICE`` at one minute, only over the month-turn blocks: the
    last 5 and first 3 business days of each month, which is one contiguous
    8-business-day run and therefore three windows rather than eight.

Two hazards this script is shaped around
----------------------------------------
**The tag cache's own incremental logic will poison an intraday layer.**
``CitiVeloTagCache.missing_spans`` answers a request that starts before what is
cached with ONE span running from the requested start to the cached first row.
The MI01 cache already holds 2026-08-04..07, so a request for a week in 2021
would be served as a single five-year span - and ``CVTSHIST`` downsamples by
span silently, so five years of DAILY rows would be written into the MI01 tree
looking exactly like minute data. Every fetch here therefore passes
``force_refresh=True``, which makes the requested span the ONLY span, and resume
is done from this script's own manifest instead.

**The request bound and the returned stamp are in different timezones.**
Measured on ``RATES.BOND.*`` 2026-08-20: a window ending ``2026-06-20 00:00``
returned its last row at ``2026-06-19 20:00`` and one ending ``2026-01-20 00:00``
returned ``2026-01-19 19:00`` - four hours in EDT, five in EST. The offset tracks
New York's UTC offset exactly, which is not a coincidence a rounding error can
produce: the bound is read as UTC and the stamps come back in America/New_York.
Windows tile regardless (a uniform shift moves the whole grid), so the fix is
padding at the ends of each requested RANGE rather than per window.

Verification is post-hoc, from the cache, and deliberately not at fetch time.
Bond MI01 is sparse - median gap two minutes at full resolution - so a median
spacing gate reports illiquidity as downsampling and throws away real history.
The MINIMUM gap is what proves resolution; ``etf_intraday_verify.py`` measures
both.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import pathlib
import sys
import time
from typing import Dict, List, Sequence, Tuple

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("etf_backfill")

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "notebooks" / "backtests" / "etf_rebalance" / "_data"

#: Excel's add-in memory only grows. Restart below the guard's own refuse-line so
#: the restart happens on our schedule rather than as a raised exception.
SOFT_CEILING_MB = 3300.0

#: How many tags go into one ``CVTSHIST``. Matches the client's own default, so
#: chunking here costs nothing and buys per-chunk resume.
CHUNK = 44

#: Measured floors (``etf_intraday_probe.py``, 2026-08-20).
FLOOR_PRICE_YIELD = datetime.date(2019, 11, 1)
FLOOR_ASS_SOFR = datetime.date(2025, 9, 1)


# ------------------------------------------------------------------ #
#                              windows                               #
# ------------------------------------------------------------------ #


def hourly_windows(start: datetime.date, end: datetime.date,
                   width_days: int = 90) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """Tile ``[start, end]`` newest-first in windows under the 120-day HOURLY cliff."""
    lo = datetime.datetime.combine(start, datetime.time(0, 0))
    hi = datetime.datetime.combine(end, datetime.time(0, 0))
    out = []
    cursor = hi
    width = datetime.timedelta(days=width_days)
    while cursor > lo:
        w0 = max(lo, cursor - width)
        out.append((w0, cursor))
        cursor = w0
    return out


def month_turn_blocks(start: datetime.date, end: datetime.date,
                      *, tail_bdays: int = 5, head_bdays: int = 3,
                      pad_days: int = 1) -> List[Tuple[datetime.date, datetime.date]]:
    """The last ``tail_bdays`` of each month plus the first ``head_bdays`` of the next.

    Returned as CALENDAR spans, newest-first, padded by ``pad_days`` on each side -
    the padding absorbs the UTC-bound/ET-stamp offset documented in the module
    docstring, and costs at most one extra window per block.
    """
    bdays = pd.bdate_range(start - pd.Timedelta(days=10), end + pd.Timedelta(days=10))
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    blocks = []
    for m in months:
        m_end = m.to_timestamp(how="end").normalize()
        tail = bdays[bdays <= m_end][-tail_bdays:]
        head = bdays[bdays > m_end][:head_bdays]
        if len(tail) == 0 or len(head) == 0:
            continue
        b0 = (tail[0] - pd.Timedelta(days=pad_days)).date()
        b1 = (head[-1] + pd.Timedelta(days=pad_days)).date()
        if b1 < start or b0 > end:
            continue
        blocks.append((b0, b1))
    return sorted(set(blocks), reverse=True)


def split_block(b0: datetime.date, b1: datetime.date,
                width_days: int = 5) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """One block into windows under the 6-day MI01 cliff, newest-first."""
    lo = datetime.datetime.combine(b0, datetime.time(0, 0))
    hi = datetime.datetime.combine(b1, datetime.time(0, 0))
    out = []
    cursor = hi
    width = datetime.timedelta(days=width_days)
    while cursor > lo:
        w0 = max(lo, cursor - width)
        out.append((w0, cursor))
        cursor = w0
    return out


# ------------------------------------------------------------------ #
#                              manifest                              #
# ------------------------------------------------------------------ #


class Manifest:
    """Append-only JSONL of every request issued. Resume reads it; nothing else does."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.done: set = set()
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # An ERROR is retryable; "ok" and "empty" are settled facts. A
                # window that genuinely holds nothing must be recorded, or every
                # re-run pays for it again.
                if rec.get("status") in {"ok", "empty"}:
                    self.done.add(self.key(rec["layer"], rec["w0"], rec["w1"], rec["chunk"]))
        self._fh = path.open("a", encoding="utf-8")

    @staticmethod
    def key(layer: str, w0: str, w1: str, chunk: int) -> str:
        return f"{layer}|{w0}|{w1}|{chunk}"

    def already(self, layer: str, w0: str, w1: str, chunk: int) -> bool:
        return self.key(layer, w0, w1, chunk) in self.done

    def record(self, rec: dict) -> None:
        self._fh.write(json.dumps(rec, default=str) + "\n")
        self._fh.flush()
        if rec.get("status") in {"ok", "empty"}:
            self.done.add(self.key(rec["layer"], rec["w0"], rec["w1"], rec["chunk"]))

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ #
#                               driver                               #
# ------------------------------------------------------------------ #


class Driver:
    """Owns the one Excel session, and the restart policy that keeps it alive."""

    def __init__(self):
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        self._QuotesCls = CitiVeloQuotes
        self.quotes = CitiVeloQuotes()
        self.restarts = 0
        self.peak_mb = 0.0
        self.rescued: List[str] = []

    def memory(self) -> float:
        from MDP.CitiVelocityExcel import memory_guard

        mb = memory_guard.excel_memory_mb()
        if mb is not None:
            self.peak_mb = max(self.peak_mb, mb)
        return -1.0 if mb is None else mb

    def maybe_restart(self) -> None:
        mb = self.memory()
        if mb < SOFT_CEILING_MB:
            return
        from MDP.CitiVelocityExcel import supervisor

        log.warning("Excel at %.0f MB >= %.0f soft ceiling; restarting.", mb, SOFT_CEILING_MB)
        try:
            self.quotes.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("closing the old reader raised %s: %s", type(exc).__name__, exc)
        # NEVER force=True. If a human has unsaved work open, the rescue fails,
        # restart_excel raises, and this job stops - which is the correct trade.
        client = supervisor.restart_excel(workbook_tag="ETFWARM", logger=log)
        self.restarts += 1
        # A restarted Excel invalidates the old reader's cached COM handle, and a
        # dead handle raises errors that read exactly like data failures.
        self.quotes = self._QuotesCls(client=client)
        log.warning("restart #%d complete; Excel at %.0f MB", self.restarts, self.memory())

    def close(self) -> None:
        try:
            self.quotes.close()
        except Exception:  # noqa: BLE001
            pass


def run_layer(driver: Driver, manifest: Manifest, layer: str, freq: str,
              tags: Sequence[str], windows: Sequence[Tuple[datetime.datetime, datetime.datetime]],
              *, max_seconds: float) -> Dict[str, int]:
    chunks = [list(tags[i:i + CHUNK]) for i in range(0, len(tags), CHUNK)]
    total = len(windows) * len(chunks)
    stats = {"issued": 0, "skipped": 0, "ok": 0, "empty": 0, "error": 0, "rows": 0}
    started = time.time()
    n = 0
    for w0, w1 in windows:
        for ci, chunk in enumerate(chunks):
            n += 1
            k0, k1 = w0.isoformat(), w1.isoformat()
            if manifest.already(layer, k0, k1, ci):
                stats["skipped"] += 1
                continue
            if time.time() - started > max_seconds:
                log.warning("%s: time budget of %.0f min exhausted at %d/%d requests.",
                            layer, max_seconds / 60.0, n, total)
                return stats
            driver.maybe_restart()
            failures: Dict[str, str] = {}
            t0 = time.time()
            rec = {"layer": layer, "freq": freq, "w0": k0, "w1": k1, "chunk": ci,
                   "n_tags_req": len(chunk)}
            try:
                frame = driver.quotes.frame(
                    chunk, freq, start=w0, end=w1, price_point="CLOSE",
                    force_refresh=True, failures=failures,
                )
                served = [c for c in frame.columns if frame[c].notna().any()]
                rec["n_tags_served"] = len(served)
                rec["n_rows"] = int(len(frame))
                if len(frame) >= 3:
                    d = pd.Series(frame.index).diff().dropna()
                    rec["min_gap_s"] = float(d.min().total_seconds())
                    rec["med_gap_s"] = float(d.median().total_seconds())
                rec["status"] = "ok" if served else "empty"
                rec["failures"] = {k: v for k, v in failures.items() if k in chunk}
                stats[rec["status"]] += 1
                stats["rows"] += int(len(frame))
            except Exception as exc:  # noqa: BLE001 - one bad window must not end a backfill
                rec["status"] = "error"
                rec["error"] = f"{type(exc).__name__}: {exc}"[:400]
                stats["error"] += 1
                log.warning("%s %s..%s chunk %d FAILED: %s", layer, w0.date(), w1.date(), ci,
                            rec["error"])
            rec["seconds"] = round(time.time() - t0, 2)
            rec["excel_mb"] = round(driver.memory(), 1)
            manifest.record(rec)
            stats["issued"] += 1
            if n % 10 == 0 or rec.get("status") != "ok":
                log.info("%s %d/%d  %s..%s c%d  %s rows=%s tags=%s %.1fs  excel=%.0fMB",
                         layer, n, total, w0.date(), w1.date(), ci, rec["status"],
                         rec.get("n_rows"), rec.get("n_tags_served"), rec["seconds"],
                         rec["excel_mb"])
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layers", nargs="+", default=["hourly", "asof", "mi01"],
                    choices=["hourly", "asof", "mi01"])
    ap.add_argument("--universe", default=str(DATA / "intraday_universe.csv"))
    ap.add_argument("--end", default=None)
    ap.add_argument("--hourly-start", default=FLOOR_PRICE_YIELD.isoformat())
    ap.add_argument("--asof-start", default=FLOOR_ASS_SOFR.isoformat())
    ap.add_argument("--mi01-start", default="2021-01-01")
    ap.add_argument("--max-minutes", type=float, default=600.0,
                    help="per-layer wall-clock budget")
    ap.add_argument("--limit-bonds", type=int, default=0, help="smoke-test knob")
    args = ap.parse_args()

    from MDP.CitiVelocityExcel import memory_guard

    mb = memory_guard.assert_safe_to_connect(what="the ETF intraday backfill")
    log.info("memory gate passed at %.0f MB", mb)

    uni = pd.read_csv(args.universe)
    isins = list(dict.fromkeys(uni["isin"].astype(str)))
    if args.limit_bonds:
        isins = isins[: args.limit_bonds]
    log.info("universe: %d bonds", len(isins))

    end = pd.Timestamp(args.end).date() if args.end else datetime.date.today()

    DATA.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(DATA / "intraday_backfill_manifest.jsonl")
    log.info("manifest: %d settled request(s) already on disk", len(manifest.done))

    driver = Driver()
    summary = {}
    try:
        if "hourly" in args.layers:
            tags = [f"RATES.BOND.{i}.{v}" for v in ("YIELD", "PRICE") for i in isins]
            wins = hourly_windows(pd.Timestamp(args.hourly_start).date(), end, 90)
            log.info("LAYER hourly: %d tags x %d windows = %d requests",
                     len(tags), len(wins), len(wins) * -(-len(tags) // CHUNK))
            summary["hourly"] = run_layer(driver, manifest, "hourly", "HOURLY", tags, wins,
                                          max_seconds=args.max_minutes * 60)
            log.info("LAYER hourly done: %s", summary["hourly"])

        if "asof" in args.layers:
            tags = [f"RATES.BOND.{i}.ASS_SOFR" for i in isins]
            wins = hourly_windows(pd.Timestamp(args.asof_start).date(), end, 90)
            log.info("LAYER asof: %d tags x %d windows", len(tags), len(wins))
            summary["asof"] = run_layer(driver, manifest, "asof", "HOURLY", tags, wins,
                                        max_seconds=args.max_minutes * 60)
            log.info("LAYER asof done: %s", summary["asof"])

        if "mi01" in args.layers:
            tags = [f"RATES.BOND.{i}.{v}" for v in ("YIELD", "PRICE") for i in isins]
            blocks = month_turn_blocks(pd.Timestamp(args.mi01_start).date(), end)
            wins = [w for b in blocks for w in split_block(*b, width_days=5)]
            log.info("LAYER mi01: %d tags x %d windows over %d month turns = %d requests",
                     len(tags), len(wins), len(blocks), len(wins) * -(-len(tags) // CHUNK))
            summary["mi01"] = run_layer(driver, manifest, "mi01", "MI01", tags, wins,
                                        max_seconds=args.max_minutes * 60)
            log.info("LAYER mi01 done: %s", summary["mi01"])
    finally:
        manifest.close()
        driver.close()
        log.info("PEAK Excel memory %.0f MB, %d restart(s)", driver.peak_mb, driver.restarts)
        print(json.dumps({"summary": summary, "peak_excel_mb": driver.peak_mb,
                          "restarts": driver.restarts}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
