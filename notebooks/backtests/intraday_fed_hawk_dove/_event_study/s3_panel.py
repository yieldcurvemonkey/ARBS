"""STAGE 3 - the event-time panel.

BAR-INDEXING RULE (the whole study hangs off this)
--------------------------------------------------
Barchart minute bars are START-stamped: the bar labelled L covers [L, L+1), so
its CLOSE is a print from as late as L+1 and its OPEN is a print from as late as
L+1 too. Taking the close of the bar labelled T for "the price at T" therefore
imports up to a minute of POST-T information, which at offset 0 is precisely the
separation the chart is trying to demonstrate.

So:

    price(T) = Close of the LAST bar whose label L is STRICTLY BEFORE T,
               provided the information is no more than STALE_CAP_MIN old,
               where staleness = T - (L + 1 minute).   Otherwise NaN.

Every price in the panel is therefore a print that had already happened by T.
The rule is uniform across offsets, so it cannot create a discontinuity at 0; it
can only UNDERSTATE the reaction, which is the safe direction to be wrong in.
`stale_min` is stored per row so a downstream reader can tighten the cap without
rebuilding.

BASELINE: the cumulative path is measured from the price at offset -60 min, per
(event, contract_rank). An event-rank with no valid price at -60 carries NaN for
d_rate_bp_from_baseline and signed_d_bp at every offset.

SIGN: rate = 100 - price, rate_bp = (100 - price) * 100. A hawkish surprise
raises expected policy -> the implied rate RISES -> the futures price FALLS, so
d_rate_bp_from_baseline is POSITIVE for a hawkish move. signed_d_bp multiplies
that by stance_sign, so a "the speaker did what their prior stance implied"
outcome is POSITIVE for hawks and doves alike.

    python s3_panel.py --which real
    python s3_panel.py --which placebo
"""
from __future__ import annotations

import argparse
import datetime
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
LOCAL_BARS = HERE / "bars_event_study.pkl"

OFFSETS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0,
           5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300]
BASELINE_OFFSET = -60
STALE_CAP_MIN = 15.0
NS = 60_000_000_000          # nanoseconds in a minute

BAR_RULE = (f"price(T) = Close of the LAST bar labelled STRICTLY BEFORE T "
            f"(bars are start-stamped, so that close is a print at or before T); "
            f"NaN if staleness = T-(L+1min) exceeds {STALE_CAP_MIN:g} min. "
            f"Baseline for the cumulative path = offset {BASELINE_OFFSET} min.")

_ARR: dict = {}
#: symbol-days voided as a fabricated grid rather than data
PADDED: set = set()


def day_arrays(sym: str, day: datetime.date):
    """(int64 bar-label ns, float close) for one symbol-day, memoised.

    PADDED GRIDS ARE VOIDED HERE. Barchart fabricates a full 24x60 minute grid
    carrying ONE price on days the contract did not trade - the market being
    shut, most often. Measured across this cache: 115 such frames, every one of
    them exactly 1440 bars with exactly 1 distinct close and a constant volume,
    and not a single genuine frame looks like that (0 of 115 full grids carry
    more than 2 distinct closes). Left in, they pass every timestamp and
    staleness check and then book a GUARANTEED ZERO move at every offset, which
    is worse than missing data: it shrinks the standard error of a result that
    was never measured. 13 Saturday speeches priced 22/22 offsets before this.

    The test is the one `gate_events` already uses, so the panel and the
    existing backtest agree about what counts as a tradeable day.
    """
    k = (sym, day)
    if k not in _ARR:
        bars = G._BAR_CACHE.get(k)
        if bars is None or len(bars) == 0 or int(bars["Close"].nunique()) < 2:
            if bars is not None and len(bars):
                PADDED.add(k)
            _ARR[k] = (np.empty(0, dtype=np.int64), np.empty(0, dtype=float))
        else:
            _ARR[k] = (bars.index.view("int64").astype(np.int64),
                       bars["Close"].to_numpy(dtype=float))
    return _ARR[k]


_SPAN: dict = {}


def span_arrays(sym: str, days: tuple):
    k = (sym, days)
    if k not in _SPAN:
        parts = [day_arrays(sym, d) for d in days]
        ix = np.concatenate([p[0] for p in parts]) if parts else np.empty(0, np.int64)
        cl = np.concatenate([p[1] for p in parts]) if parts else np.empty(0, float)
        if len(ix) > 1:
            o = np.argsort(ix, kind="stable")
            ix, cl = ix[o], cl[o]
        _SPAN[k] = (ix, cl)
    return _SPAN[k]


def price_at(ix: np.ndarray, cl: np.ndarray, t_ns: int):
    """-> (price, staleness_min, bar_label_ns). NaN beyond the staleness cap."""
    if len(ix) == 0:
        return np.nan, np.nan, 0
    i = int(np.searchsorted(ix, t_ns, side="left")) - 1     # label STRICTLY < T
    if i < 0:
        return np.nan, np.nan, 0
    stale = (t_ns - ix[i]) / NS - 1.0                        # close is stamped L+1
    if stale > STALE_CAP_MIN:
        return np.nan, float(stale), int(ix[i])
    return float(cl[i]), float(stale), int(ix[i])


def build(ev: pd.DataFrame, ranks, is_placebo: bool) -> pd.DataFrame:
    cfg = G.CB_CONFIGS["FED"]
    lo = datetime.timedelta(minutes=min(OFFSETS) - STALE_CAP_MIN - 1)
    hi = datetime.timedelta(minutes=max(OFFSETS))
    off_ns = np.array(OFFSETS, dtype=np.int64) * NS
    ib = OFFSETS.index(BASELINE_OFFSET)

    keep = ["event_id", "speaker", "role", "is_voter", "stance_score_exante",
            "stance_score_nopit", "stance_sign", "bucket", "is_overlapping",
            "n_other_in_window", "min_abs_gap_min", "days_to_fomc", "is_fomc_day",
            "is_cpi_day", "is_nfp_day", "title", "clock"]
    if is_placebo:
        keep.append("parent_event_id")

    # columns, not dicts: 400k+ per-row dicts is ~1GB of transient garbage for
    # nothing. Everything below appends flat scalars/arrays in the same order.
    nO = len(OFFSETS)
    col: dict[str, list] = {k: [] for k in keep}
    for k in ("speech_ts", "date", "is_placebo", "weekday", "contract_rank", "symbol",
              "offset_min"):
        col[k] = []
    px_a, st_a, rb_a, dr_a, sd_a, bl_a, bp_a = ([] for _ in range(7))

    t0 = time.time()
    for n, (_, r) in enumerate(ev.iterrows(), 1):
        ts = pd.Timestamp(r["speech_ts"])
        py = ts.to_pydatetime()
        d0, d1 = (py + lo).date(), (py + hi).date()
        days = tuple(d0 + datetime.timedelta(days=i) for i in range((d1 - d0).days + 1))
        t_ns = np.int64(ts.value) + off_ns
        edate = py.date()
        sgn = int(r["stance_sign"])

        for rank in ranks:
            sym = G.nth_quarterly_contract(cfg.root_for(edate), edate, rank)
            ix, cl = span_arrays(sym, days)
            px = np.full(nO, np.nan)
            st = np.full(nO, np.nan)
            lb = np.zeros(nO, dtype=np.int64)
            for j in range(nO):
                px[j], st[j], lb[j] = price_at(ix, cl, int(t_ns[j]))
            rate_bp = (100.0 - px) * 100.0
            b = rate_bp[ib]
            d = rate_bp - b if b == b else np.full(nO, np.nan)
            sd = d * sgn if sgn != 0 else np.full(nO, np.nan)

            for k in keep:
                col[k].extend([r[k]] * nO)
            col["speech_ts"].extend([ts] * nO)
            col["date"].extend([edate] * nO)
            col["is_placebo"].extend([is_placebo] * nO)
            col["weekday"].extend([py.weekday()] * nO)
            col["contract_rank"].extend([rank] * nO)
            col["symbol"].extend([sym] * nO)
            col["offset_min"].extend(OFFSETS)
            px_a.append(px); st_a.append(st); rb_a.append(rate_bp)
            dr_a.append(d); sd_a.append(sd); bl_a.append(lb)
            bp_a.append(np.full(nO, px[ib]))
        if n % 400 == 0:
            print(f"    {n}/{len(ev)}  ({time.time()-t0:.0f}s)", flush=True)

    out = pd.DataFrame(col)
    out["price"] = np.concatenate(px_a)
    out["rate_bp"] = np.concatenate(rb_a)
    out["d_rate_bp_from_baseline"] = np.concatenate(dr_a)
    out["signed_d_bp"] = np.concatenate(sd_a)
    out["stale_min"] = np.concatenate(st_a)
    out["baseline_price"] = np.concatenate(bp_a)
    # keep this in int64: a nanosecond epoch is ~1.8e18 and float64 only carries
    # 2^53 exactly, so routing it through np.nan/float would quietly round the label
    lbl = np.concatenate(bl_a)
    out["bar_label_ts"] = pd.Series(
        pd.to_datetime(lbl, unit="ns", utc=True).tz_convert(cfg.tz)
    ).where(lbl != 0, pd.NaT)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", default="real", choices=["real", "placebo"])
    ap.add_argument("--ranks", default="1,2,3,4,5")
    ap.add_argument("--bars", default=str(LOCAL_BARS))
    ap.add_argument("--limit", type=int, default=0, help="smoke test: first N events")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    ranks = [int(x) for x in args.ranks.split(",")]

    n = G.load_bar_cache(args.bars)
    print(f"bar cache: {n} symbol-days", flush=True)
    print(f"BAR RULE: {BAR_RULE}", flush=True)

    src = "events.parquet" if args.which == "real" else "placebo_events.parquet"
    dst = args.out or ("event_paths.parquet" if args.which == "real"
                       else "placebo_paths.parquet")
    ev = pd.read_parquet(HERE / src)
    if args.limit:
        ev = ev.head(args.limit)
    print(f"{src}: {len(ev)} events, ranks {ranks}", flush=True)

    panel = build(ev, ranks, is_placebo=(args.which == "placebo"))

    # "Drop events with no minute bars that day" - applied here, counted, and split
    # by reason, because an empty bar frame and a day whose bars are all too stale
    # mean different things and a single "dropped" number hides which one it was.
    if PADDED:
        wd = pd.Series([d.weekday() for _, d in PADDED]).value_counts().sort_index()
        print(f"VOIDED {len(PADDED)} symbol-days as fabricated flat grids "
              f"(1 distinct close); by weekday Mon=0 {wd.to_dict()}", flush=True)

    priced = panel.groupby("event_id")["price"].apply(lambda s: s.notna().any())
    dead = set(priced.index[~priced])
    if dead:
        d = panel[panel["event_id"].isin(dead)]
        nobar = d.groupby("event_id")["stale_min"].apply(lambda s: s.isna().all())
        n_empty = int(nobar.sum())
        wd = (d[d["offset_min"] == 0].drop_duplicates("event_id")["weekday"]
              .value_counts().sort_index().to_dict())
        print(f"DROPPED {len(dead)} of {panel['event_id'].nunique()} events with no priced "
              f"offset at any rank:", flush=True)
        print(f"    {n_empty} had NO bar frame at all on the day (weekend / no data)",
              flush=True)
        print(f"    {len(dead)-n_empty} had bars but nothing inside the "
              f"{STALE_CAP_MIN:g}-min staleness cap at any offset", flush=True)
        print(f"    by weekday (Mon=0): {wd}", flush=True)
        hr = (d[d["offset_min"] == 0].drop_duplicates("event_id")["speech_ts"]
              .apply(lambda t: pd.Timestamp(t).hour).value_counts().sort_index().to_dict())
        print(f"    by speech hour: {hr}", flush=True)
        panel = panel[~panel["event_id"].isin(dead)].reset_index(drop=True)

    cols = ["event_id", "speech_ts", "date", "speaker", "role", "is_voter",
            "stance_score_exante", "stance_sign", "bucket", "contract_rank", "symbol",
            "offset_min", "price", "rate_bp", "d_rate_bp_from_baseline", "signed_d_bp",
            "is_overlapping", "days_to_fomc", "is_fomc_day", "is_cpi_day", "is_nfp_day",
            "is_placebo"]
    extra = [c for c in panel.columns if c not in cols]
    panel = panel[cols + extra]
    # the baseline is a fact about the file, so it lives IN the file - both as a
    # column and in the parquet key-value metadata. df.attrs does NOT survive
    # to_parquet, which is how a stated convention quietly becomes an unstated one.
    panel.insert(len(cols), "baseline_offset_min", BASELINE_OFFSET)
    tbl = pa.Table.from_pandas(panel, preserve_index=False)
    meta = dict(tbl.schema.metadata or {})
    meta.update({
        b"bar_rule": BAR_RULE.encode(),
        b"baseline_offset_min": str(BASELINE_OFFSET).encode(),
        b"stale_cap_min": str(STALE_CAP_MIN).encode(),
        b"offsets_min": ",".join(str(o) for o in OFFSETS).encode(),
        b"sign_convention": (b"rate_bp = (100-price)*100; hawkish -> rate UP -> price DOWN "
                             b"-> d_rate_bp_from_baseline POSITIVE; "
                             b"signed_d_bp = d_rate_bp_from_baseline * stance_sign"),
        b"built_by": b"s3_panel.py (intraday_fed_hawk_dove/_event_study)",
    })
    pq.write_table(tbl.replace_schema_metadata(meta), HERE / dst)
    print(f"WROTE {dst}: {len(panel):,} rows, {panel['event_id'].nunique()} events, "
          f"{panel['contract_rank'].nunique()} ranks", flush=True)
    cov = panel.groupby("offset_min")["price"].apply(lambda s: s.notna().mean())
    print("coverage by offset:", {int(k): round(float(v), 3) for k, v in cov.items()},
          flush=True)


if __name__ == "__main__":
    main()
