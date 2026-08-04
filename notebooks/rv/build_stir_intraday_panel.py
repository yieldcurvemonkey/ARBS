"""Build the 4-hour SR3 contract panel -- the intraday twin of ``build_sfr_fly_panel.py``.

Emits **the same schema** as the EOD builder so that
``RVUtils.MeanRev.panel.add_strip_slots`` / ``enumerate_structures`` -- the exact
code the EOD lab uses -- builds the intraday structures too. The EOD-vs-intraday
comparison is then apples to apples by construction rather than by care.

**Why this exists.** A first probe measured a *fixed* far-dated fly
(``2*SR3U27 - SR3U26 - SR3U28``) and found its 4h move was 0.876bp against a
2.0bp round trip. That is a lower bound, not the answer: for most of 2022-2024
all three legs sat in the quiet back of the strip, and the EOD lab's 12m fly was
a **rolling front-slot** basket that moved 2.55x further at h=21. Scaling
naively puts the front fly's 4h move around 2.2bp -- i.e. MARGINAL against cost,
not dead. The only way to settle it is to build the rolling panel.

**Marks are bar CLOSES, which are trade prints, not mids.** That matters and is
handled downstream rather than hidden here: bar closes alternate between bid and
offer, which is mechanically mean-reverting. Measured on the 12m fly, lag-1
autocorrelation is -0.318, implying a Roll effective spread of 1.68bp -- 84% of
the 2.0bp we charge, so the cost model is honest. And VR(2) = 1 + rho(1) = 0.682
against a measured 0.681, i.e. **one-bar reversion is entirely bounce**. It is
only past ~6 bars that the variance ratio keeps falling (0.275 at q=30) on
something other than microstructure.

**The bar clock.** Barchart stamps intraday bars in exchange-local time
(America/Chicago) and REJECTS naive bounds -- the EOD endpoint accepts them,
which is an easy trap. 240-minute bars land at 00/04/08/12/16/20 CT. They are
not interchangeable: the US bars (08, 12) carry roughly double the movement of
the overnight ones, and the 12 CT bar is the one containing both the 14:00 ET
FOMC decision and the 15:00 ET settle.

``as_of`` is written **tz-naive in Central** so it compares cleanly against the
naive IMM dates downstream; the wall-clock hour stays readable as the bar slot.

Outputs (``notebooks/data/stir_intraday/``):

* ``parts/<SYM>.parquet``  -- per-symbol OHLCV, checkpointed and skipped on re-run
* ``contracts.parquet``    -- long frame: as_of, code, settle, rate_pct, volume,
                              imm_start, imm_end, accruing, bar_hour_ct, unchanged
* ``panel_audit.txt``      -- coverage by rank, staleness, bar clock

Usage::

    conda run -n stir python notebooks/rv/build_stir_intraday_panel.py
    conda run -n stir python notebooks/rv/build_stir_intraday_panel.py --force
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import (
    STIRFutureMDP,
    _from_barchart_symbol,
    _to_barchart_symbol,
)

CME_TZ = pytz.timezone("America/Chicago")
QUARTERS = ["H", "M", "U", "Z"]
OUT_DIR = REPO / "notebooks" / "data" / "stir_intraday"
INTERVAL = 240


def imm_third_wednesday(year: int, month: int) -> datetime.date:
    """The IMM date: third Wednesday of the month."""
    d = datetime.date(year, month, 1)
    wed = d + datetime.timedelta(days=(2 - d.weekday()) % 7)
    return wed + datetime.timedelta(days=14)


def imm_window(code: str) -> tuple[datetime.date, datetime.date]:
    """Reference quarter of an SR3 contract: [IMM, next IMM)."""
    m = QUARTERS.index(code[3]) * 3 + 3
    y = 2000 + int(code[4:6])
    start = imm_third_wednesday(y, m)
    em, ey = (m + 3, y) if m < 12 else (3, y + 1)
    return start, imm_third_wednesday(ey, em)


def contract_codes(y0: int, y1: int) -> list[str]:
    return [f"SR3{q}{y % 100:02d}" for y in range(y0, y1 + 1) for q in QUARTERS]


def fetch(codes: list[str], start, end, *, force: bool) -> None:
    parts = OUT_DIR / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    todo = [c for c in codes if force or not (parts / f"{c}.parquet").exists()]
    if not todo:
        print(f"all {len(codes)} symbols already checkpointed")
        return
    print(f"fetching {len(todo)} of {len(codes)} symbols at {INTERVAL}min", flush=True)

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    bcf = mdp._get_barchart_fetcher(required_concurrency=min(len(todo), 8) + 1)
    # One call: the fetcher shares a single 55/60s intraday budget across the
    # fan-out. Splitting into batches here would defeat that and re-create the
    # 429 storm the shared limiter exists to prevent.
    frames = bcf.barchart_timeseries_api(
        barchart_symbols=[_to_barchart_symbol(c) for c in todo],
        start_date=start, end_date=end, interval=INTERVAL,
        one_df=False, show_tqdm=True)

    got = (frames.items() if isinstance(frames, dict)
           else zip([_to_barchart_symbol(c) for c in todo], frames))
    n_ok = 0
    for bsym, df in got:
        code = _from_barchart_symbol(bsym)
        if df is None or len(df) == 0:
            continue
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index(df.columns[0])
        df.sort_index().to_parquet(parts / f"{code}.parquet")
        n_ok += 1
    print(f"  checkpointed {n_ok} symbols", flush=True)


def assemble() -> pd.DataFrame:
    parts = sorted((OUT_DIR / "parts").glob("SR3*.parquet"))
    rows = []
    for p in parts:
        code = p.stem
        df = pd.read_parquet(p)
        if len(df) == 0:
            continue
        idx = df.index
        # Barchart returns exchange-local stamps; drop the tz so the column
        # compares cleanly with the naive IMM dates and the hour stays readable.
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(CME_TZ).tz_localize(None)
        s, e = imm_window(code)
        close = df["Close"].to_numpy(dtype=float)
        sub = pd.DataFrame({
            "as_of": idx,
            "code": code,
            "settle": close,
            "rate_pct": 100.0 - close,
            "volume": (df["Volume"].to_numpy(dtype=float)
                       if "Volume" in df else np.nan),
        })
        sub["imm_start"] = pd.Timestamp(s)
        sub["imm_end"] = pd.Timestamp(e)
        sub["accruing"] = sub["as_of"] >= pd.Timestamp(s)
        sub["bar_hour_ct"] = sub["as_of"].dt.hour
        sub["unchanged"] = sub["settle"].diff().abs().fillna(0) < 1e-12
        rows.append(sub)
    panel = pd.concat(rows, ignore_index=True)
    return panel.sort_values(["as_of", "imm_start"]).reset_index(drop=True)


def audit(panel: pd.DataFrame) -> str:
    from RVUtils.MeanRev.panel import add_strip_slots

    L = []
    w = L.append
    w("=" * 96)
    w("SR3 4-HOUR PANEL AUDIT")
    w("=" * 96)
    w(f"bars      : {panel['as_of'].nunique():,} distinct timestamps")
    w(f"contracts : {panel['code'].nunique()}")
    w(f"rows      : {len(panel):,}")
    w(f"span      : {panel['as_of'].min()} -> {panel['as_of'].max()}  (Central)")

    live = panel[~panel["accruing"]]
    slots = add_strip_slots(live)
    per = slots.groupby("as_of")["slot"].max()
    w(f"\npre-accrual contracts per bar: median {per.median():.0f}, "
      f"min {per.min():.0f}, max {per.max():.0f}")

    w("\nBAR CLOCK (Central)")
    for h, n in panel.groupby("bar_hour_ct").size().items():
        w(f"  {h:02d}:00  {n:>8,} rows")

    w("\nSTALENESS BY SLOT -- the number that decides whether a package is real")
    w("  A structure is a cross-contract object. If one leg prints in a bar and")
    w("  another does not, the package's move is one leg's move alone, and it")
    w("  reverts when the other catches up. That is not mean reversion.")
    g = (slots[slots["slot"] <= 16].groupby("slot")
         .agg(rows=("unchanged", "size"),
              pct_unchanged=("unchanged", "mean"),
              median_volume=("volume", "median")))
    w(g.round(3).to_string())

    w("\nSTALENESS BY BAR HOUR")
    g2 = (slots[slots["slot"] <= 8].groupby("bar_hour_ct")
          .agg(rows=("unchanged", "size"), pct_unchanged=("unchanged", "mean")))
    w(g2.round(3).to_string())
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--start-year", type=int, default=2021)
    ap.add_argument("--end-year", type=int, default=2031)
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    codes = contract_codes(a.start_year, a.end_year)
    end = CME_TZ.localize(datetime.datetime(2026, 7, 30, 23, 59))
    start = CME_TZ.localize(datetime.datetime(2021, 1, 1))

    fetch(codes, start, end, force=a.force)
    panel = assemble()
    panel.to_parquet(OUT_DIR / "contracts.parquet", index=False)
    txt = audit(panel)
    (OUT_DIR / "panel_audit.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt, flush=True)
    print(f"\nwrote {OUT_DIR / 'contracts.parquet'}  ({len(panel):,} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
