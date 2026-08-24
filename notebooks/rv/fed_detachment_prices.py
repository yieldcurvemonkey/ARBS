r"""The price side of the detachment study: SR3 settles, ranks, and a roll-free book.

Three facts about SR3 shape everything in this module, and two of them make the
usual futures-backtest hazards go away rather than needing to be handled.

**Rank 1 is the front contract whose reference quarter has NOT yet started.**
``nth_quarterly_contract`` seeds on ``next_imm(ref)``, so on 2026-08-20 rank 1 is
``SR3U26`` (accrues 2026-09-16 -> 2026-12-16) and rank 3 is ``SR3H27`` -- which is
the contract the handover names. Excluding started contracts keeps partially-fixed
legs out of every structure; it is also the desk convention recorded in
``reference_sfr_fly_conventions``.

**Therefore a rank-N contract always has at least a quarter left to run.** Rank 1
selected at ``t`` expires at ``next_imm(t) + 3 months``, i.e. never sooner than
about thirteen weeks after ``t``. The longest holding period this study trades is
eight weeks, so **a trade opened on the rank-N contract never crosses that
contract's expiry**. There is no intra-trade roll, and therefore no roll-jump in
any P&L number here.

That matters more than it sounds. ``reference_imm_roll_fomc_collision`` records
that 22 of 33 SR3 rolls ARE FOMC decision dates, so a return series that diffs
across a roll carries a jump that is *correlated with the signal this study
trades*, not noise. The construction above means the question never arises: every
P&L is ``exit_settle - entry_settle`` on ONE contract. The always-on variant, which
does change contract when the rank changes, charges a full round trip at the
switch and is reported separately.

**Cost.** 0.25bp one-way per CONTRACT, so an outright round trip is 0.50bp, a
two-leg calendar spread 1.00bp and a four-contract pack 2.00bp. This follows the
corrected line in ``reference_sfr_fly_conventions`` ("cost is per CONTRACT, not
per leg ... 2.0bp round trip on a fly (4 contracts) ... 0.5bp on an outright").
The handover for this study says "a single-contract round trip is ~0.25bp", which
contradicts its own butterfly figure in the same sentence (2.0bp / 4 contracts =
0.5bp per contract round trip). The conservative reading is used as the frozen
default and the optimistic one is reported as a sensitivity.

Cache
-----
Settles are read from a STUDY-LOCAL parquet cache seeded from the shared
``BT/serff`` one. A refetch is merged, never substituted: a Barchart fetch that
comes back short would otherwise overwrite good history with less of it, and
``reference_backfill_runner_traps`` and ``reference_partial_cache_answer_hazard``
both record that a SHORT answer is the dangerous one, not an empty answer.
"""
from __future__ import annotations

import datetime
import os
import pathlib
import shutil
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from BT.serff.futures_data import _cache_dir as _shared_cache_dir  # noqa: E402
from BT.serff.mechanics import contract_window  # noqa: E402

#: One-way transaction cost per CONTRACT, in basis points of rate.
COST_BP_PER_CONTRACT_ONE_WAY = 0.25

#: The optimistic reading of the handover's cost line, kept for the sensitivity.
COST_BP_PER_CONTRACT_ONE_WAY_OPTIMISTIC = 0.125

#: SR3 is quoted 100 - rate, so one basis point of rate is 0.01 of price.
PX_PER_BP = 0.01

#: One SR3 contract is $25 per basis point.
USD_PER_BP_PER_CONTRACT = 25.0

_QUARTERLY_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


def study_cache_dir() -> pathlib.Path:
    base = os.environ.get("ARBS_DETACHMENT_CACHE")
    if base:
        d = pathlib.Path(base)
    else:
        try:
            from platformdirs import user_cache_dir

            d = pathlib.Path(user_cache_dir(appname="ARBS_fed_detachment"))
        except Exception:  # pragma: no cover
            d = pathlib.Path.home() / ".cache" / "ARBS_fed_detachment"
    out = d / "eod_settles"
    out.mkdir(parents=True, exist_ok=True)
    return out


# --------------------------------------------------------------------------
# contracts
# --------------------------------------------------------------------------
def next_imm(ref: datetime.date) -> datetime.date:
    """The next IMM (third-Wednesday, Mar/Jun/Sep/Dec) date STRICTLY after ``ref``.

    Transcribed rather than imported so the price layer does not depend on the
    ``econ_release_fade`` package, which pulls a calendar fetcher at import.
    Tied out against ``econ_fade_common.nth_quarterly_contract`` in the tests.
    """
    from BT.serff.mechanics import third_wednesday

    y, m = ref.year, ref.month
    for _ in range(6):
        m_q = ((m - 1) // 3) * 3 + 3
        if m_q > 12:
            m_q, y = m_q - 12, y + 1
        cand = third_wednesday(y, m_q)
        if cand > ref:
            return cand
        m = m_q + 1
        if m > 12:
            m, y = m - 12, y + 1
    raise RuntimeError(f"no IMM found after {ref}")


def rank_symbol(ref: datetime.date, rank: int, root: str = "SR3") -> str:
    """The ``rank``-th listed IMM quarterly as of ``ref``. Rank 1 = front."""
    if rank < 1:
        raise ValueError("rank is 1-based")
    d = ref
    for _ in range(rank):
        d = next_imm(d)
    return f"{root}{_QUARTERLY_CODES[d.month]}{str(d.year)[-2:]}"


def sr3_universe(start: datetime.date, end: datetime.date, max_rank: int = 4) -> List[str]:
    """Every SR3 quarterly any rank in ``1..max_rank`` can point at over the window."""
    syms = set()
    d = start
    while d <= end:
        for r in range(1, max_rank + 1):
            syms.add(rank_symbol(d, r))
        d += datetime.timedelta(days=1)
    return sorted(syms)


def build_rank_map(dates: Sequence[datetime.date], max_rank: int = 4) -> pd.DataFrame:
    """``date`` x ``rank`` -> contract symbol."""
    rows = []
    for d in dates:
        dd = pd.Timestamp(d).date()
        row = {"date": pd.Timestamp(d)}
        for r in range(1, max_rank + 1):
            row[f"rank{r}"] = rank_symbol(dd, r)
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------
def seed_local_cache(symbols: Optional[Iterable[str]] = None) -> Dict[str, int]:
    """Copy the shared ``BT/serff`` SR3 parquets into the study-local cache.

    Copy, not read-through: everything after this point may refetch and merge,
    and a study must never be able to shorten the shared cache other work reads.
    """
    src = _shared_cache_dir()
    dst = study_cache_dir()
    stats = {"copied": 0, "already": 0, "absent": 0}
    wanted = list(symbols) if symbols is not None else [
        p.stem for p in src.glob("SR3*.parquet")
    ]
    for sym in wanted:
        s = src / f"{sym}.parquet"
        d = dst / f"{sym}.parquet"
        if not s.exists():
            stats["absent"] += 1
            continue
        if d.exists():
            stats["already"] += 1
            continue
        shutil.copy2(s, d)
        stats["copied"] += 1
    return stats


def load_local(symbol: str) -> Optional[pd.DataFrame]:
    p = study_cache_dir() / f"{symbol.upper()}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:  # pragma: no cover
        return None
    df.index = pd.to_datetime(df.index).normalize()
    return df.sort_index()


def merge_history(old: Optional[pd.DataFrame], new: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Union of rows; ``new`` wins on a date both carry.

    A fetch that returns fewer rows than the cache holds is the failure mode
    this exists to survive. Unioning means a short answer costs nothing; taking
    the answer wholesale would cost the difference, silently.
    """
    if old is None or old.empty:
        return new.copy() if new is not None else pd.DataFrame()
    if new is None or new.empty:
        return old.copy()
    cols = list(dict.fromkeys(list(old.columns) + list(new.columns)))
    o = old.reindex(columns=cols)
    n = new.reindex(columns=cols)
    out = n.combine_first(o)
    return out.sort_index()


def refresh_settles(
    start: datetime.date,
    end: datetime.date,
    symbols: Sequence[str],
    *,
    batch_size: int = 6,
    max_concurrent: int = 2,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Refetch ``symbols`` from Barchart and MERGE into the study-local cache.

    Runs the repo's own ``_fetch_batch``. Must be called from a plain process --
    the fetcher calls ``asyncio.run``, which inside a live Jupyter loop returns
    an un-awaited coroutine that a caller can mistake for an empty day.
    """
    from BT.serff.futures_data import _fetch_batch

    dst = study_cache_dir()
    rows = []
    for i in range(0, len(symbols), batch_size):
        batch = list(symbols[i : i + batch_size])
        try:
            fetched = _fetch_batch(
                batch, start, end, max_concurrent=max_concurrent, show_progress=show_progress
            )
        except Exception as exc:  # noqa: BLE001
            print(f"batch {batch} FAILED: {type(exc).__name__}: {exc}", flush=True)
            for s in batch:
                rows.append({"symbol": s, "status": "fetch_failed", "n_before": _n(s),
                             "n_after": _n(s), "n_added": 0})
            continue
        for s in batch:
            before = load_local(s)
            n_before = 0 if before is None else len(before)
            new = fetched.get(s)
            if new is None or new.empty:
                rows.append({"symbol": s, "status": "empty_fetch", "n_before": n_before,
                             "n_after": n_before, "n_added": 0})
                continue
            merged = merge_history(before, new)
            merged.to_parquet(dst / f"{s}.parquet")
            rows.append({
                "symbol": s,
                "status": "shrunk_ignored" if len(new) < n_before else "ok",
                "n_before": n_before,
                "n_fetched": len(new),
                "n_after": len(merged),
                "n_added": len(merged) - n_before,
            })
        print(f"  batch {i // batch_size + 1}/{(len(symbols) + batch_size - 1) // batch_size} done",
              flush=True)
    return pd.DataFrame(rows)


def _n(symbol: str) -> int:
    df = load_local(symbol)
    return 0 if df is None else len(df)


# --------------------------------------------------------------------------
# panels
# --------------------------------------------------------------------------
def settle_panel(symbols: Sequence[str], price_col: str = "Close") -> pd.DataFrame:
    cols = {}
    for s in symbols:
        df = load_local(s)
        if df is None or df.empty or price_col not in df.columns:
            continue
        cols[s] = pd.to_numeric(df[price_col], errors="coerce")
    if not cols:
        return pd.DataFrame()
    panel = pd.DataFrame(cols).sort_index()
    panel.index = pd.to_datetime(panel.index).normalize()
    panel.index.name = "date"
    return panel


def gate_contract_history(
    symbols: Sequence[str], needed_from: Dict[str, pd.Timestamp]
) -> pd.DataFrame:
    """G-P1 -- every contract must carry history from the first date a rank needs it.

    The trap this closes is a PARTIAL Barchart fetch stored as if it were
    complete: the parquet exists, reads cleanly, and simply begins later than
    the study needs. It is detected by comparing the stored start against the
    first date any rank in the study points at the contract -- not by looking at
    the file, which cannot tell you what it is missing.
    """
    rows = []
    for s in symbols:
        df = load_local(s)
        want = needed_from.get(s)
        if df is None or df.empty:
            rows.append({"symbol": s, "n": 0, "first": pd.NaT, "last": pd.NaT,
                         "needed_from": want, "short_by_days": np.nan, "ok": False})
            continue
        first, last = df.index.min(), df.index.max()
        expiry = pd.Timestamp(contract_window(s).end)
        short = np.nan if want is None else float((first - want).days)
        gaps = df.index.to_series().diff().dt.days.dropna()
        rows.append({
            "symbol": s,
            "n": len(df),
            "first": first,
            "last": last,
            "expiry": expiry,
            "needed_from": want,
            "short_by_days": short,
            "max_gap_days": float(gaps.max()) if len(gaps) else np.nan,
            "ok": bool(want is None or first <= want),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# the 2y rate -- from the CURVE STORE, because the tag cache is poisoned
# --------------------------------------------------------------------------
#: Where the daily USD SOFR discount curves live. Read-only, no COM.
CURVE_STORE_ASSET = (
    pathlib.Path(os.environ.get(
        "ARBS_CURVE_STORE",
        pathlib.Path.home() / "AppData" / "Local" / "ARBS" / "Cache" / "curve_store"))
    / "raw" / "asset=USD-SOFR-1D-CITIVELOEXCEL")

#: A USD SOFR par rate outside this band is not a rate. From
#: ``project_citivelo_tagcache_vol_poison``, whose detection rule this is.
RATE_SANE_BAND = (-1.0, 15.0)


def curve_store_par_rate(tenor_years: int = 2, *,
                         asset_dir: Optional[pathlib.Path] = None) -> pd.Series:
    r"""Daily par OIS rate, in PERCENT, built from stored discount factors.

    **Why not the tag cache.** ``RATES.OIS.USD_SOFR.PAR.2Y`` in the shared Citi
    tag cache is poisoned: 2,600 of its 5,507 rows hold swaption normal vol
    (~60-165) instead of a par rate, interleaved day by day from 2015-10-08
    onwards, which is why the series still plots plausibly.
    ``project_citivelo_tagcache_vol_poison`` records the fingerprint and that the
    cache -- not the add-in -- is the wrong side. :func:`tag_cache_poison_report`
    measures it rather than citing it.

    **What this does instead.** The curve store holds the node dates and
    discount factors of the same Citi curve, 5,516 sessions from 2005-01-03, and
    those were written by a different path that the poisoning did not touch. The
    par rate is computed straight off them -- annual payments, ACT/360,
    log-linear in the discount factor, which is the curve's own declared
    interpolation:

    ``par = (1 - DF(T)) / sum_i tau_i * DF(t_i)``

    Known answer: on 2026-08-14 this returns **4.02772** where the tag-poison
    note records the CurveStore repricing to **4.02995** -- 0.22bp, which is
    roll and day-count detail. The poisoned tag said 67.1 that week.
    """
    import pyarrow.dataset as pads

    root = pathlib.Path(asset_dir or CURVE_STORE_ASSET)
    if not root.exists():
        raise FileNotFoundError(f"curve store asset missing: {root}")
    frame = pads.dataset(str(root), format="parquet", partitioning="hive").to_table(
        columns=["trading_date", "session_minute", "node_dates", "discount_factors"]
    ).to_pandas()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"])
    # one curve per session: the LAST snapshot of the day, so an intraday-warmed
    # asset and an EOD-only one give the same answer
    frame = frame.sort_values(["trading_date", "session_minute"]).groupby(
        "trading_date", as_index=False).tail(1)

    out: Dict[pd.Timestamp, float] = {}
    for _, r in frame.iterrows():
        v = _par_from_nodes(r["node_dates"], r["discount_factors"],
                            pd.Timestamp(r["trading_date"]), int(tenor_years))
        if np.isfinite(v):
            out[pd.Timestamp(r["trading_date"])] = v
    s = pd.Series(out, name=f"USD_SOFR_PAR_{tenor_years}Y").sort_index()
    s.index.name = "date"
    return s


def _par_from_nodes(node_dates, discount_factors, ref: pd.Timestamp,
                    tenor_years: int) -> float:
    nd = pd.to_datetime(pd.Series(list(node_dates)))
    d = np.asarray(list(discount_factors), dtype=float)
    days = (nd - ref).dt.days.to_numpy(float)
    ok = np.isfinite(d) & (d > 0) & (days >= 0)
    days, d = days[ok], d[ok]
    if len(days) < 3:
        return np.nan
    lg = np.log(d)
    pay = [ref + pd.DateOffset(years=y) for y in range(1, int(tenor_years) + 1)]
    if (pay[-1] - ref).days > days.max():
        return np.nan

    def _df(n: float) -> float:
        return float(np.exp(np.interp(n, days, lg)))

    prev, ann = ref, 0.0
    for p in pay:
        ann += ((p - prev).days / 360.0) * _df((p - ref).days)
        prev = p
    if ann <= 0:
        return np.nan
    return (1.0 - _df((pay[-1] - ref).days)) / ann * 100.0


def gate_rate_sanity(series: pd.Series, *, name: str = "rate") -> Dict[str, object]:
    """G-P2 -- every value must be inside a band a USD par rate can occupy.

    Cheap, and it is the exact check whose absence let a 47%-swaption-vol series
    be regressed against a sentiment index in two studies already on ``main``.
    """
    s = pd.Series(series).dropna()
    lo, hi = RATE_SANE_BAND
    bad = s[(s < lo) | (s > hi)]
    assert bad.empty, (
        f"G-P2 FAILED: {len(bad)} of {len(s)} {name} observations are outside "
        f"{RATE_SANE_BAND} (first {bad.index[0].date()} = {bad.iloc[0]:.3f}) -- "
        f"a USD SOFR par rate cannot be that number; see "
        f"project_citivelo_tagcache_vol_poison")
    return {"n": int(len(s)), "first": s.index.min(), "last": s.index.max(),
            "min": float(s.min()), "max": float(s.max()), "band": RATE_SANE_BAND}


def tag_cache_poison_report(tag: str = "RATES.OIS.USD_SOFR.PAR.2Y") -> Dict[str, object]:
    """Measure the poisoning in the shared tag cache rather than citing it.

    Returns ``None``-safe diagnostics: how many rows cannot be a rate, when the
    contamination starts and ends, and the same day's value from the clean curve
    store beside it.
    """
    import fed_sentiment_lead_data as _L

    s = _L.read_cached_rate(tag)
    if s is None or s.empty:
        return {"available": False}
    lo, hi = RATE_SANE_BAND
    bad = s[(s < lo) | (s > hi)]
    return {
        "available": True,
        "tag": tag,
        "n": int(len(s)),
        "n_impossible": int(len(bad)),
        "share_impossible": float(len(bad) / len(s)),
        "first_impossible": None if bad.empty else bad.index.min(),
        "last_impossible": None if bad.empty else bad.index.max(),
        "max_value": float(s.max()),
        "median_value": float(s.median()),
    }


def rank_price_frame(
    panel: pd.DataFrame, dates: Sequence[pd.Timestamp], max_rank: int = 4
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(price by rank, symbol by rank) on ``dates``.

    The price is the settle of the contract that rank points at ON THAT DATE.
    Consecutive rows can therefore refer to different contracts, so this frame
    must never be differenced -- it exists to look up an entry or exit price for
    a trade whose contract is fixed at entry. :func:`trade_pnl_bp` is the only
    consumer.
    """
    rmap = build_rank_map([pd.Timestamp(d).date() for d in dates], max_rank)
    rmap.index = pd.DatetimeIndex(dates)
    px = pd.DataFrame(index=rmap.index, columns=rmap.columns, dtype=float)
    for col in rmap.columns:
        for d, sym in rmap[col].items():
            if sym in panel.columns and d in panel.index:
                v = panel.at[d, sym]
                if pd.notna(v):
                    px.at[d, col] = float(v)
    return px, rmap
