"""Build the ZQ (30-day Fed Funds) contract panel for the FF kink-fade lab.

Deliberately the monthly twin of ``build_sfr_fly_panel.py``: same Barchart EOD
path, same checkpointing, same output schema. The differences are the ones the
contract forces.

**Why ZQ and not SR3.** SR3 settles on a *compounded* average over a quarterly
IMM window, so policy meetings enter diluted and overlapping. ZQ settles on the
**arithmetic average of daily EFFR over a single calendar month** (CBOT Ch. 22
§22103), so meeting steps enter as clean day-count blends: a Dec-9 decision is
~8/31 pre and ~23/31 post in the December contract, and ~fully post in January
until the late-January meeting clips the tail. The January contract is therefore
the clean read on the December meeting, and "the calendar component" of any FF
spread is exactly computable rather than approximated.

**Accrual window.** The delivery month, first calendar day to last calendar day
inclusive -- NOT an IMM quarter. ``imm_start``/``imm_end`` keep those names so
the panel is a drop-in for ``RVUtils.MeanRev.panel.add_strip_slots`` and the
rest of the MeanRev toolkit; ``imm_end`` is the first day of the NEXT month, so
``(imm_end - imm_start).days`` is the day count the settlement average runs over.

**Symbols.** Barchart's root for Fed Funds is already ``ZQ``
(``MDP/STIRFutures/STIRFutureMDP._to_barchart_symbol``: ``SR3 -> SQ``,
``SR1 -> SL``, ``ZQ -> ZQ``), so no new mapping is needed -- only monthly rather
than quarterly contract codes.

Outputs (``--out-dir``, default ``notebooks/data/zq_kink_fade``):

* ``parts/ZQxNN.parquet`` -- per-symbol Close/Volume/OI, date-indexed
* ``contracts.parquet``   -- long frame: as_of, code, settle, rate_pct, volume,
                             open_interest, imm_start, imm_end, n_days
* ``build_log.txt``       -- progress, flushed (conda run buffers stdout)

Usage::

    conda run -n stir python notebooks/rv/build_zq_panel.py --fetch
    conda run -n stir python notebooks/rv/build_zq_panel.py --merge
"""
from __future__ import annotations

import argparse
import calendar
import datetime
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd

from MDP.STIRFutures.STIRFutureMDP import (
    STIRFutureMDP,
    _from_barchart_symbol,
    _to_barchart_symbol,
)

#: ZQ trades every calendar month, so all twelve CME month codes are live --
#: unlike SR3, which is quarterly (H M U Z only).
MONTHS = ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"]
MONTH_NUM = {c: i + 1 for i, c in enumerate(MONTHS)}

DEFAULT_OUT = REPO / "notebooks" / "data" / "zq_kink_fade"
VALUE_COLS = ("Close", "Volume", "Open Interest")


def monthly_codes(first: str, last: str) -> list[str]:
    """Inclusive list of monthly contract codes, e.g. 'F19' .. 'Z28'."""
    fm, fy = MONTHS.index(first[0]), int(first[1:])
    lm, ly = MONTHS.index(last[0]), int(last[1:])
    out, m, y = [], fm, fy
    while (y, m) <= (ly, lm):
        out.append(f"{MONTHS[m]}{y:02d}")
        m += 1
        if m == 12:
            m, y = 0, y + 1
    return out


def delivery_window(code: str) -> tuple[datetime.date, datetime.date, int]:
    """(first day of the delivery month, first day of the NEXT month, n_days).

    The settlement average runs over every calendar day of the delivery month,
    so the day count is the month length -- 28, 29, 30 or 31 -- and it is
    carried through the panel because the meeting-exposure weights divide by it.
    """
    m = MONTH_NUM[code[0]]
    y = 2000 + int(code[1:])
    start = datetime.date(y, m, 1)
    n = calendar.monthrange(y, m)[1]
    end = start + datetime.timedelta(days=n)
    return start, end, n


def last_business_day(year: int, month: int) -> datetime.date:
    """Last trading day of the delivery month -- when ZQ trading terminates
    (Ch. 22 §22102.F). Weekday-only; the exchange holiday calendar is applied
    where it matters, in the tick-size and cost model, not here."""
    d = datetime.date(year, month, calendar.monthrange(year, month)[1])
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


class Log:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("a", encoding="utf-8")

    def __call__(self, msg: str) -> None:
        line = f"{datetime.datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()


def fetch(codes: list[str], start: datetime.date, end: datetime.date,
          out_dir: Path, log: Log, *, batch: int = 12, force: bool = False) -> None:
    parts = out_dir / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    todo = [c for c in codes if force or not (parts / f"ZQ{c}.parquet").exists()]
    log(f"fetch: {len(todo)}/{len(codes)} symbols to pull "
        f"({start} -> {end}), batch={batch}")
    if not todo:
        return

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    start_dt = datetime.datetime.combine(start, datetime.time(0, 1))
    end_dt = datetime.datetime.combine(end, datetime.time(23, 59))

    for b0 in range(0, len(todo), batch):
        chunk = todo[b0:b0 + batch]
        syms = [f"ZQ{c}" for c in chunk]
        bsyms = [_to_barchart_symbol(s) for s in syms]
        t0 = time.time()
        frames: dict[str, pd.DataFrame] = {}
        for col in VALUE_COLS:
            df = None
            for kwargs in ({"force_rotate_proxy": False, "clear_session_tokens": False},
                           {"force_rotate_proxy": True, "clear_session_tokens": True}):
                bcf = mdp._get_barchart_fetcher(required_concurrency=len(bsyms) + 1,
                                                **kwargs)
                try:
                    df = bcf.barchart_timeseries_api(
                        barchart_symbols=bsyms, start_date=start_dt, end_date=end_dt,
                        interval=None, one_df=True, merge_val_col=col,
                        show_tqdm=False, max_concurrent_tasks=min(len(bsyms), 8) + 1,
                        max_keepalive_connections=max(16, len(bsyms)) + 1,
                        eod_server_side_dates=True,
                    )
                except Exception as exc:
                    log(f"  {col}: {type(exc).__name__}: {str(exc)[:120]}")
                    df = None
                finally:
                    try:
                        bcf.close()
                    except Exception:
                        pass
                if df is not None and not df.empty:
                    break
            if df is None or df.empty:
                log(f"  batch {b0}: NO DATA for {col}")
                continue
            df = df.copy()
            df.columns = [_from_barchart_symbol(c) for c in df.columns]
            frames[col] = df

        if "Close" not in frames:
            log(f"  batch {b0}: skipped (no Close)")
            continue

        for sym in syms:
            cols = {}
            for col, df in frames.items():
                if sym in df.columns:
                    cols[col] = pd.to_numeric(df[sym], errors="coerce")
            if "Close" not in cols or cols["Close"].dropna().empty:
                log(f"  {sym}: empty")
                continue
            out = pd.DataFrame(cols)
            out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
            out = out[~out.index.duplicated(keep="last")].sort_index()
            out = out.dropna(subset=["Close"])
            out.to_parquet(parts / f"{sym}.parquet")
            log(f"  {sym}: {len(out)} rows {out.index.min().date()} -> "
                f"{out.index.max().date()}")
        log(f"  batch {b0}-{b0 + len(chunk)} done in {time.time() - t0:.1f}s")


def merge(out_dir: Path, log: Log) -> pd.DataFrame:
    parts = sorted((out_dir / "parts").glob("ZQ*.parquet"))
    if not parts:
        raise SystemExit(f"no parts under {out_dir / 'parts'} -- run --fetch first")
    rows = []
    for p in parts:
        code = p.stem[2:]
        df = pd.read_parquet(p)
        s, e, n = delivery_window(code)
        sub = pd.DataFrame({
            "as_of": df.index,
            "code": code,
            "settle": df["Close"].to_numpy(dtype=float),
            "volume": (df["Volume"].to_numpy(dtype=float) if "Volume" in df
                       else float("nan")),
            "open_interest": (df["Open Interest"].to_numpy(dtype=float)
                              if "Open Interest" in df else float("nan")),
        })
        sub["imm_start"] = s
        sub["imm_end"] = e
        sub["n_days"] = n
        sub["last_trade"] = last_business_day(s.year, s.month)
        rows.append(sub)
    panel = pd.concat(rows, ignore_index=True)
    panel["rate_pct"] = 100.0 - panel["settle"]
    panel["as_of"] = pd.to_datetime(panel["as_of"])

    # A contract is only a FORWARD read on policy while its delivery month has
    # not started. Once it is accruing, part of the settle is realised fixings
    # and the "rate" is a blend of history and expectation -- the same rule
    # add_strip_slots applies to SR3, kept explicit here as a column so the
    # backtest can gate on it rather than rediscover it.
    panel["days_to_start"] = (pd.to_datetime(panel["imm_start"])
                              - panel["as_of"]).dt.days
    panel["accruing"] = panel["days_to_start"] <= 0

    panel = panel.sort_values(["as_of", "imm_start"]).reset_index(drop=True)
    out = out_dir / "contracts.parquet"
    panel.to_parquet(out, index=False)
    log(f"merged {panel.shape} -> {out}")
    log(f"  dates {panel['as_of'].min().date()} -> {panel['as_of'].max().date()}, "
        f"{panel['as_of'].nunique()} sessions, {panel['code'].nunique()} contracts")
    live = panel[~panel["accruing"]]
    per = live.groupby("as_of").size()
    log(f"  pre-accrual contracts per session: median {per.median():.0f}, "
        f"min {per.min()}, max {per.max()}")
    return panel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=datetime.date.fromisoformat,
                    default=datetime.date(2018, 1, 1))
    ap.add_argument("--end", type=datetime.date.fromisoformat,
                    default=datetime.date(2026, 7, 30))
    ap.add_argument("--first-code", default="F18")
    ap.add_argument("--last-code", default="Z28")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--batch", type=int, default=12)
    a = ap.parse_args(argv)

    a.out_dir.mkdir(parents=True, exist_ok=True)
    log = Log(a.out_dir / "build_log.txt")
    codes = monthly_codes(a.first_code, a.last_code)
    log(f"=== build_zq_panel {a.start} -> {a.end} | {len(codes)} codes "
        f"{codes[0]}..{codes[-1]} ===")

    if a.fetch or not (a.fetch or a.merge):
        fetch(codes, a.start, a.end, a.out_dir, log, batch=a.batch, force=a.force)
    if a.merge or not (a.fetch or a.merge):
        merge(a.out_dir, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
