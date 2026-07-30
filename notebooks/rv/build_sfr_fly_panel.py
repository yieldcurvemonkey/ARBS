"""Build the SR3 contract panel the fly mean-reversion lab trades on.

Marks are **raw SR3 settlement prices**, not a fitted curve. The tradeable
object is a package of futures, so the P&L mark has to be the futures settle;
a curve is a smoothed model of those settles and would let the backtest trade
its own interpolation error. (The Q16STIRT curve was measured returning
bit-identical rates across strip slots 8-14 on 2026-07-27 — flat interpolation
where the fly is identically zero. It is kept as a cross-check panel, never as
a mark.)

One Barchart EOD history request per contract symbol covers the whole sample,
so the backfill is ~40 requests rather than ~40 x 1400. Each symbol is
checkpointed to ``parts/<SYM>.parquet`` and skipped on re-run.

Outputs (``--out-dir``, default ``notebooks/data/sfr_fly_meanrev``):

* ``parts/SR3xNN.parquet`` — per-symbol OHLC/volume/OI, date-indexed
* ``contracts.parquet``    — long frame: as_of, code, settle, rate_pct,
                             volume, open_interest, imm_start, imm_end
* ``build_log.txt``        — progress, flushed (conda run buffers stdout)

Usage::

    conda run -n stir python notebooks/rv/build_sfr_fly_panel.py --fetch
    conda run -n stir python notebooks/rv/build_sfr_fly_panel.py --merge
"""
from __future__ import annotations

import argparse
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

MONTHS = ["H", "M", "U", "Z"]
MONTH_NUM = {"H": 3, "M": 6, "U": 9, "Z": 12}
DEFAULT_OUT = REPO / "notebooks" / "data" / "sfr_fly_meanrev"

#: value columns pulled per symbol, in one merged frame each
VALUE_COLS = ("Close", "Volume", "Open Interest")


def quarterly_codes(first: str, last: str) -> list[str]:
    """Inclusive list of quarterly contract codes, e.g. 'H21' .. 'Z30'."""
    fm, fy = first[0], int(first[1:])
    lm, ly = last[0], int(last[1:])
    out, m, y = [], MONTHS.index(fm), fy
    while (y, m) <= (ly, MONTHS.index(lm)):
        out.append(f"{MONTHS[m]}{y:02d}")
        m += 1
        if m == 4:
            m, y = 0, y + 1
    return out


def imm_third_wednesday(year: int, month: int) -> datetime.date:
    """The IMM date: third Wednesday of the month."""
    d = datetime.date(year, month, 1)
    # weekday(): Mon=0 .. Wed=2
    first_wed = d + datetime.timedelta(days=(2 - d.weekday()) % 7)
    return first_wed + datetime.timedelta(days=14)


def imm_window(code: str) -> tuple[datetime.date, datetime.date]:
    """(reference-quarter start, end) for an SR3 contract code like 'U26'."""
    m = MONTH_NUM[code[0]]
    y = 2000 + int(code[1:])
    start = imm_third_wednesday(y, m)
    em, ey = (m + 3, y) if m + 3 <= 12 else (m - 9, y + 1)
    return start, imm_third_wednesday(ey, em)


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
    todo = [c for c in codes if force or not (parts / f"SR3{c}.parquet").exists()]
    log(f"fetch: {len(todo)}/{len(codes)} symbols to pull "
        f"({start} -> {end}), batch={batch}")
    if not todo:
        return

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    start_dt = datetime.datetime.combine(start, datetime.time(0, 1))
    end_dt = datetime.datetime.combine(end, datetime.time(23, 59))

    for b0 in range(0, len(todo), batch):
        chunk = todo[b0:b0 + batch]
        syms = [f"SR3{c}" for c in chunk]
        bsyms = [_to_barchart_symbol(s) for s in syms]
        t0 = time.time()
        frames: dict[str, pd.DataFrame] = {}
        for col in VALUE_COLS:
            df = None
            for kwargs in ({"force_rotate_proxy": False, "clear_session_tokens": False},
                           {"force_rotate_proxy": True, "clear_session_tokens": True}):
                bcf = mdp._get_barchart_fetcher(required_concurrency=len(bsyms) + 1, **kwargs)
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
        log(f"  batch {b0}-{b0+len(chunk)} done in {time.time()-t0:.1f}s")


def merge(out_dir: Path, log: Log) -> pd.DataFrame:
    parts = sorted((out_dir / "parts").glob("SR3*.parquet"))
    if not parts:
        raise SystemExit(f"no parts under {out_dir/'parts'} — run --fetch first")
    rows = []
    for p in parts:
        code = p.stem[3:]
        df = pd.read_parquet(p)
        imm_s, imm_e = imm_window(code)
        sub = pd.DataFrame({
            "as_of": df.index,
            "code": code,
            "settle": df["Close"].to_numpy(dtype=float),
            "volume": (df["Volume"].to_numpy(dtype=float) if "Volume" in df
                       else float("nan")),
            "open_interest": (df["Open Interest"].to_numpy(dtype=float)
                              if "Open Interest" in df else float("nan")),
        })
        sub["imm_start"] = imm_s
        sub["imm_end"] = imm_e
        rows.append(sub)
    panel = pd.concat(rows, ignore_index=True)
    panel["rate_pct"] = 100.0 - panel["settle"]
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    panel = panel.sort_values(["as_of", "imm_start"]).reset_index(drop=True)
    out = out_dir / "contracts.parquet"
    panel.to_parquet(out, index=False)
    log(f"merged {panel.shape} -> {out}")
    log(f"  dates {panel['as_of'].min().date()} -> {panel['as_of'].max().date()}, "
        f"{panel['as_of'].nunique()} sessions, {panel['code'].nunique()} contracts")
    return panel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=datetime.date.fromisoformat,
                    default=datetime.date(2019, 1, 1))
    ap.add_argument("--end", type=datetime.date.fromisoformat,
                    default=datetime.date(2026, 7, 29))
    ap.add_argument("--first-code", default="H19")
    ap.add_argument("--last-code", default="Z31")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--batch", type=int, default=12)
    a = ap.parse_args(argv)

    a.out_dir.mkdir(parents=True, exist_ok=True)
    log = Log(a.out_dir / "build_log.txt")
    codes = quarterly_codes(a.first_code, a.last_code)
    log(f"=== build_sfr_fly_panel {a.start} -> {a.end} | {len(codes)} codes "
        f"{codes[0]}..{codes[-1]} ===")

    if a.fetch or not (a.fetch or a.merge):
        fetch(codes, a.start, a.end, a.out_dir, log, batch=a.batch, force=a.force)
    if a.merge or not (a.fetch or a.merge):
        merge(a.out_dir, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
