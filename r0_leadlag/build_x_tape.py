"""R0 / X — signed customer DV01 from the public SDR tape, 1-minute bins, per bucket,
on two clocks (execution and dissemination).

Pre-registration: ``r0_leadlag/r0_prereg.md`` (committed before any data was touched).
Deviations forced by the data: ``r0_leadlag/r0_deviations.md``.

WORKSTREAM ISOLATION
--------------------
This module deliberately imports NOTHING from ``SDRUtils/dealer_direction/`` or
``SDRUtils/stir_flow/`` and touches no curve stack. The only shared code it uses is
the read-only DB plumbing (``resolve_pg_url``) and the table-name constants
(``_tape_tables``). The direction label is derived from the tape's own printed fixed
rates and nothing else. Crudeness is the requirement, not a compromise: if R0 needed
the risk ladder to work, a negative R0 would be uninterpretable.

It also does NOT read ``arbs_stir_direction_v1``: those labels are ~78%
one-directional because of a half-basis-point curve bias in the mid they price
against, and importing that bias would make R0 a test of the bias.

STAGES (each resumable, each cached to disk, each written atomically)
---------------------------------------------------------------------
``harvest``  DTCC intraday slice ZIPs -> per-UTC-day parquet of
             (dissemination id, member mtime, S3 Last-Modified, slice seq).
``tape``     in-scope tape legs -> one parquet.
``build``    join + sign + bin -> ``data/x_signed_dv01.parquet``.
``all``      all three in order.

THE SPECIFICATION, FIXED IN ADVANCE
-----------------------------------
Everything below was written before the direction split or any coverage number was
computed, and is not revisited after seeing results.

Filters (minimal, and all of them):
  * ``economic_class = 'ECONOMIC_FLOW'``
  * ``contributes_to_flow``
  * ``rate_index_clean IN ('SOFR', 'FED_FUNDS')``  (USD)
  * ``fixed_rate IS NOT NULL``
  * ``notional IS NOT NULL``, ``notional < 1e19`` and ``notional > 0``. The upper
    bound drops the ``notional = 1e20`` "not available" sentinel rows. The lower
    bound drops 3 legs of 310,859 (0.001%) carrying ``notional = 0.0`` with
    ``fixed_rate = 0.0001`` — the same class of degenerate placeholder row. They
    contribute exactly zero DV01, but they produce a cell with ``gross_dv01 = 0``,
    which hands a downstream consumer a 0/0. See r0_deviations.md.
  * ``tenor_years > 0``
``is_block`` and the D2C/IDB class are carried as COLUMNS, never as filters.

Bucket map (fixed; boundaries documented, NOT optimised). Round numbers sitting near
each contract's CTD. Edge inclusivity, stated explicitly:
    tenor <= 1.5                -> SFR_FF
    1.5 <  tenor <= 3.0         -> TU
    3.0 <  tenor <= 7.0         -> FV
    7.0 <  tenor <= 12.0        -> TY_UXY     (tenor exactly 12.0 lands here)
           tenor >  12.0        -> US

DV01 (crude by requirement, documented, NOT tuned):
    dv01 = notional * tenor_years * 1e-4
i.e. a flat "one basis point on a par-ish annuity of `tenor_years`" approximation.
No discounting, no curve, no annuity factor. It systematically overstates long
tenors relative to a true annuity and overstates forward-starting swaps; both are
monotone in tenor and so cannot flip a bucket's sign.

Direction (tape-internal mid — the tick rule generalised, no curve at all):
    For each print, ``mid`` = the median of the printed ``fixed_rate`` of up to the
    last 10 prints sharing the same MID KEY, strictly earlier in execution order,
    within a trailing 24 hours, requiring at least 3 such predecessors.
        sign = +1 if rate > mid   (customer paid fixed)
        sign = -1 if rate < mid   (customer received fixed)
        sign =  0 if rate == mid, or fewer than 3 qualifying predecessors -> UNSIGNED
    The window (last 10, min 3, 24h) is FROZEN here and was chosen before the
    direction split was computed. It is short on purpose: a long trailing window in a
    trending market classifies nearly everything one way.

    MID KEY = (rate_index_clean, tenor_label, forward_start_key, is_mac).
      * The mid is keyed at FINE tenor granularity, not at the futures-bucket
        granularity. A median across a whole futures bucket (e.g. 7-12y) in an
        upward-sloping curve would label every 12y print "paid" and every 7y print
        "received", making the sign a proxy for tenor rather than for direction.
        The prereg does not pin the mid's key; this is the crude-but-not-broken
        reading of it.
      * ``forward_start_key`` separates spot from forward-starting swaps, whose fair
        rates differ. Derived here from ``forward_start_years`` with fixed round-number
        bins rather than from the tape's ``forward_bucket`` column (see
        r0_deviations.md).
      * ``is_mac`` isolates MAC swaps, whose printed fixed rate is a STANDARDISED
        coupon rather than the traded level (the economics sit in
        ``other_payment_amount``). Pooled with vanilla prints they would sit
        systematically on one side of the median. Keyed separately, MACs compare to
        MACs, mostly tie, and fall out as unsigned — which is honest.
      * Ties are UNSIGNED, not carried forward from the previous print. Classic
        tick-rule tie inheritance would propagate one stale sign across weeks of
        identical standardised coupons.
      * The mid is computed in EXECUTION order for both clocks, so a print carries the
        SAME sign on both panels and the two clocks differ only in the timestamp they
        are indexed by — which is exactly what the prereg's "built twice" asks for.

Clocks:
  * ``exec`` — ``execution_timestamp`` (CFTC field #96).
  * ``diss`` — real dissemination time, recovered from the DTCC intraday slice the
    listing first appeared in. The slice ZIP member's mtime is a naive
    America/New_York wall-clock stamp; MEASURED against the S3 object's
    ``Last-Modified`` header over a full day (2,168 slices), the offset is
    14401-14404 s, i.e. exactly 4 h (EDT) plus a 1-4 s write-to-upload latency
    (p50 2 s). The whole R0 window is inside EDT, so no DST edge arises.
    Prints with no matched slice fall back to ``execution + (median matched lag)``
    and are counted separately; the report states the real-vs-estimated fraction.

Output grain: (bucket, minute_utc, clock, is_block, venue_class).
  ``signed_dv01``  sum of sign*dv01 over SIGNED prints in the cell
  ``gross_dv01``   sum of dv01 over ALL in-scope prints in the cell
  ``n_prints``     count of ALL in-scope prints in the cell
The file is SPARSE — only cells containing at least one print are emitted. A consumer
that needs a regular grid must reindex onto the full (bucket x minute x clock) product
and fill 0.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import os
import sys
import time
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from email.utils import parsedate_to_datetime

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CACHE = HERE / "cache"
DATA = HERE / "data"
SLICE_CACHE = CACHE / "slices"
OUT_PARQUET = DATA / "x_signed_dv01.parquet"
# The per-print frame X was aggregated from, kept for addendum-1 diagnostic D1.
SIGNED_LEGS_CACHE = CACHE / "tape_legs_signed.parquet"

# --- the R0 window --------------------------------------------------------------
# Emitted bins. MBO overlap is 2026-05-07..2026-08-06; this is that plus a margin.
EMIT_START = pd.Timestamp("2026-05-01", tz="UTC")
EMIT_END = pd.Timestamp("2026-08-08", tz="UTC")  # exclusive
# Tape pull runs earlier so the trailing-24h mid window is warm on 2026-05-01.
TAPE_START = dt.date(2026, 4, 24)
TAPE_END = dt.date(2026, 8, 8)
# Slice harvest: dissemination always follows execution, so one calendar day before
# EMIT_START is enough to catch a late-2026-04-30 execution that published on 05-01.
HARVEST_START = dt.date(2026, 4, 30)
HARVEST_END = dt.date(2026, 8, 8)

SLICE_BASE = "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/slices"
# MEASURED: the slice ZIP member mtime is naive America/New_York; the R0 window is
# entirely inside EDT (US DST 2026: Mar 8 - Nov 1), so this is a constant.
ET_OFFSET = dt.timedelta(hours=4)

# Inter-dealer-broker MICs. Written from the public identity of each venue
# (Dealerweb, Tradition SEF, i-Swap/ICAP, BGC Derivative Markets, Tullett Prebon SEF)
# and then CROSS-CHECKED against the tape's own `venue` column at build time; the
# agreement rate is printed. Everything not in this set is classed D2C.
IDB_MICS = frozenset({"DWSF", "TSEF", "ISWV", "BGCD", "TPSE"})

MID_WINDOW_N = 10          # at most this many trailing same-key prints
MID_WINDOW_MIN_N = 3       # fewer than this -> unsigned
MID_WINDOW_MAX_AGE = pd.Timedelta("24h")


# =================================================================================
# THE SIGN CONVENTION — asserted in exactly ONE place, unit-tested in
# r0_leadlag/scratch_test_x_sign.py. Do not restate this logic anywhere else.
# =================================================================================
def predicted_futures_sign(customer_sign: int) -> int:
    """Map a customer-direction label to the futures flow the hedge channel predicts.

    The pre-registered chain (r0_prereg.md), in full::

        customer pays fixed
          -> dealer received fixed
          -> dealer is long duration
          -> dealer SELLS futures to hedge

    So ``customer_sign = +1`` (customer paid) predicts NEGATIVE signed futures flow,
    and a working hedge channel appears as ``beta_k < 0`` at small positive ``k``.
    A positive ``beta_k`` of the same magnitude is a different phenomenon, not a pass.

    ``customer_sign`` is +1 (paid fixed), -1 (received fixed) or 0 (unsigned).
    """
    return -customer_sign


def customer_sign_from_mid(rate: float, mid: float) -> int:
    """+1 if the customer paid fixed, -1 if it received, 0 if unsigned.

    The tape-internal tick rule: a print above the recent same-key median of printed
    fixed rates is a customer paying fixed. Returns 0 for an exact tie and for a
    missing mid; see ``predicted_futures_sign`` for what the sign then means for Y.
    """
    if mid is None or not np.isfinite(mid) or not np.isfinite(rate):
        return 0
    if rate > mid:
        return 1
    if rate < mid:
        return -1
    return 0


# =================================================================================
# Bucket map
# =================================================================================
BUCKETS = ("SFR_FF", "TU", "FV", "TY_UXY", "US")


def bucket_for_tenor(tenor_years: float) -> str:
    """Fixed tenor -> futures bucket map. Boundaries documented, NOT optimised.

    tenor <= 1.5 -> SFR_FF; (1.5, 3] -> TU; (3, 7] -> FV; (7, 12] -> TY_UXY; >12 -> US.
    """
    if tenor_years <= 1.5:
        return "SFR_FF"
    if tenor_years <= 3.0:
        return "TU"
    if tenor_years <= 7.0:
        return "FV"
    if tenor_years <= 12.0:
        return "TY_UXY"
    return "US"


def _bucket_series(t: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [t <= 1.5, t <= 3.0, t <= 7.0, t <= 12.0],
            ["SFR_FF", "TU", "FV", "TY_UXY"],
            default="US",
        ),
        index=t.index,
        dtype="object",
    )


def forward_start_key(fwd_years: float) -> str:
    """Fixed round-number forward-start bins for the mid key. Not optimised.

    Derived from ``forward_start_years``, NOT from the tape's ``forward_bucket``
    column (which disagrees with it; see r0_deviations.md / SHARED_BUGS.md).
    """
    if fwd_years is None or not np.isfinite(fwd_years) or fwd_years <= 0.02:
        return "spot"
    if fwd_years <= 0.25:
        return "0-3M"
    if fwd_years <= 0.5:
        return "3-6M"
    if fwd_years <= 1.0:
        return "6M-1Y"
    if fwd_years <= 2.0:
        return "1-2Y"
    if fwd_years <= 5.0:
        return "2-5Y"
    return "5Y+"


def _forward_key_series(f: pd.Series) -> pd.Series:
    v = f.fillna(0.0)
    return pd.Series(
        np.select(
            [v <= 0.02, v <= 0.25, v <= 0.5, v <= 1.0, v <= 2.0, v <= 5.0],
            ["spot", "0-3M", "3-6M", "6M-1Y", "1-2Y", "2-5Y"],
            default="5Y+",
        ),
        index=f.index,
        dtype="object",
    )


# =================================================================================
# Stage A — DTCC intraday slice harvest
# =================================================================================
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    ad = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3)
    s.mount("https://", ad)
    return s


def _slice_url(day: dt.date, seq: int) -> str:
    return f"{SLICE_BASE}/CFTC_SLICE_RATES_{day:%Y_%m_%d}_{seq}.zip"


def _max_seq(sess: requests.Session, day: dt.date) -> int:
    """Binary-search the highest existing slice sequence for a UTC day (0 if none).

    Measured, not assumed: 2026-08-06 has 2168 slices, not the ~1,333 quoted
    elsewhere, and a weekend day has only a handful. Costs ~2*log2(n) HEADs.
    """
    def exists(seq: int) -> bool:
        for _ in range(3):
            try:
                return sess.head(_slice_url(day, seq), timeout=20).status_code == 200
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"HEAD kept failing for {day} seq={seq}")

    if not exists(1):
        return 0
    lo, hi = 1, 2
    while exists(hi):
        lo, hi = hi, hi * 2
        if hi > 200_000:
            raise RuntimeError(f"runaway max-seq search on {day}")
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if exists(mid):
            lo = mid
        else:
            hi = mid
    return lo


def _fetch_slice(sess: requests.Session, day: dt.date, seq: int):
    """-> (found: bool, rows) where each row is
    (dissem_id, action_type, event_type, mtime_naive_et, lastmod_utc).

    ``found`` distinguishes "the slice does not exist" from "the slice exists and
    carries no rows"; harvest counts the former so a hole in the sequence is visible
    rather than silently absorbed.
    """
    url = _slice_url(day, seq)
    last_exc = None
    for attempt in range(4):
        try:
            r = sess.get(url, timeout=60)
        except Exception as exc:  # transient network
            last_exc = exc
            time.sleep(0.4 * (attempt + 1))
            continue
        if r.status_code in (403, 404):
            return False, []
        if r.status_code != 200:
            last_exc = RuntimeError(f"HTTP {r.status_code}")
            time.sleep(0.4 * (attempt + 1))
            continue
        try:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            info = z.infolist()[0]
            mtime = dt.datetime(*info.date_time)
            lastmod = parsedate_to_datetime(r.headers["Last-Modified"])
            text = z.read(info.filename).decode("utf-8", "replace")
        except Exception as exc:
            last_exc = exc
            time.sleep(0.4 * (attempt + 1))
            continue
        rows = []
        rdr = csv.DictReader(io.StringIO(text))
        for rec in rdr:
            did = (rec.get("Dissemination Identifier") or "").strip()
            if not did:
                continue
            rows.append(
                (did, (rec.get("Action type") or "").strip(),
                 (rec.get("Event type") or "").strip(), mtime, lastmod)
            )
        return True, rows
    raise RuntimeError(f"slice fetch failed {url}: {last_exc}")


def _slice_cache_path(day: dt.date) -> Path:
    return SLICE_CACHE / f"dissem_{day:%Y-%m-%d}.parquet"


def harvest_day(sess: requests.Session, day: dt.date, workers: int = 24) -> pd.DataFrame:
    """Harvest one UTC day of slices; cached, atomic, resumable."""
    path = _slice_cache_path(day)
    if path.exists():
        return pd.read_parquet(path)
    SLICE_CACHE.mkdir(parents=True, exist_ok=True)
    n = _max_seq(sess, day)
    recs, seqs = [], []
    n_holes = 0
    if n:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_fetch_slice, sess, day, s): s for s in range(1, n + 1)}
            for fut, s in futs.items():
                found, rows = fut.result()
                if not found:
                    n_holes += 1
                    continue
                for row in rows:
                    recs.append(row)
                    seqs.append(s)
    df = pd.DataFrame(
        recs, columns=["dissem_id", "action_type", "event_type", "mtime_naive_et", "lastmod_utc"]
    )
    df["slice_seq"] = seqs
    df["slice_day"] = str(day)
    df.attrs["max_seq"] = n
    df.attrs["n_holes"] = n_holes
    if n_holes:
        print(f"    WARNING {day}: {n_holes}/{n} slice sequences returned 404/403", flush=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return df


def stage_harvest(start: dt.date = HARVEST_START, end: dt.date = HARVEST_END) -> None:
    sess = _session()
    day = start
    t_all = time.time()
    while day <= end:
        path = _slice_cache_path(day)
        if path.exists():
            day += dt.timedelta(days=1)
            continue
        t0 = time.time()
        df = harvest_day(sess, day)
        print(f"  harvest {day}  slices_max_seq={df['slice_seq'].max() if len(df) else 0:>5} "
              f"rows={len(df):>6}  {time.time()-t0:5.1f}s", flush=True)
        day += dt.timedelta(days=1)
    print(f"harvest complete in {time.time()-t_all:.0f}s", flush=True)


def load_dissem_map(start: dt.date = HARVEST_START, end: dt.date = HARVEST_END) -> pd.DataFrame:
    """All harvested slice listings -> one dissem_id -> earliest publication row.

    A dissemination id can legitimately recur (the same listing carried in a later
    slice); the FIRST slice it appears in is its publication time, so duplicates
    collapse to the earliest mtime.
    """
    frames = []
    day = start
    missing = []
    while day <= end:
        p = _slice_cache_path(day)
        if p.exists():
            frames.append(pd.read_parquet(p))
        else:
            missing.append(str(day))
        day += dt.timedelta(days=1)
    if missing:
        raise RuntimeError(f"slice cache incomplete, missing {len(missing)} days: {missing[:5]}")
    df = pd.concat(frames, ignore_index=True)
    df["dissem_ts_utc"] = pd.to_datetime(df["mtime_naive_et"]) + ET_OFFSET
    df["dissem_ts_utc"] = df["dissem_ts_utc"].dt.tz_localize("UTC")
    df["lastmod_utc"] = pd.to_datetime(df["lastmod_utc"], utc=True)
    df = df.sort_values("dissem_ts_utc").drop_duplicates("dissem_id", keep="first")
    return df[["dissem_id", "dissem_ts_utc", "lastmod_utc", "action_type", "event_type", "slice_seq"]]


# =================================================================================
# Stage B — tape pull
# =================================================================================
TAPE_CACHE = CACHE / "tape_legs.parquet"

TAPE_SQL = """
SELECT trade_id, execution_timestamp, as_of_date,
       tenor_years, forward_start_years, tenor_label, notional, fixed_rate,
       rate_index_clean, platform_identifier, venue, is_block, is_mac,
       is_notional_capped, trade_type
FROM {legs}
WHERE as_of_date BETWEEN %(start)s AND %(end)s
  AND economic_class = 'ECONOMIC_FLOW'
  AND contributes_to_flow
  AND rate_index_clean IN ('SOFR', 'FED_FUNDS')
  AND fixed_rate IS NOT NULL
  AND notional IS NOT NULL
  AND notional < 1e19
  AND notional > 0
  AND tenor_years IS NOT NULL
  AND tenor_years > 0
  AND execution_timestamp IS NOT NULL
"""


def stage_tape(start: dt.date = TAPE_START, end: dt.date = TAPE_END) -> pd.DataFrame:
    if TAPE_CACHE.exists():
        return pd.read_parquet(TAPE_CACHE)
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    sys.path.insert(0, str(REPO))
    import psycopg2  # noqa: E402
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE  # noqa: E402

    CACHE.mkdir(parents=True, exist_ok=True)
    sql = TAPE_SQL.format(legs=LEGS_TABLE)
    t0 = time.time()
    conn = psycopg2.connect(resolve_pg_url())
    try:
        # The tape DB is remote PRODUCTION. R0 reads and writes nothing; make that
        # a property of the session rather than a promise.
        conn.set_session(readonly=True)
        df = pd.read_sql(sql, conn, params={"start": str(start), "end": str(end)})
    finally:
        conn.close()
    print(f"  tape pull: {len(df)} legs in {time.time()-t0:.0f}s from {LEGS_TABLE}", flush=True)
    for c in ("tenor_years", "forward_start_years", "notional", "fixed_rate"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    tmp = TAPE_CACHE.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, TAPE_CACHE)
    return df


# =================================================================================
# Stage C — sign + bin
# =================================================================================
def attach_mid_sign(df: pd.DataFrame) -> pd.DataFrame:
    """Tape-internal rolling-median mid -> per-print customer sign.

    Frozen window: median of up to the last MID_WINDOW_N same-key prints strictly
    earlier in execution order and no older than MID_WINDOW_MAX_AGE, requiring at
    least MID_WINDOW_MIN_N of them.
    """
    df = df.sort_values(["execution_timestamp", "trade_id"], kind="mergesort").reset_index(drop=True)
    df["mid_key"] = (
        df["rate_index_clean"].astype(str)
        + "|" + df["tenor_label"].astype(str)
        + "|" + df["fwd_key"].astype(str)
        + "|" + df["is_mac"].fillna(False).astype(bool).astype(str)
    )
    mid = np.full(len(df), np.nan)
    # Explicit dtype: a tz-aware series can hand back an object array of Timestamps
    # depending on the pandas version, which would make the age comparison below
    # silently slow or wrong.
    ts = df["execution_timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(
        dtype="datetime64[ns]"
    )
    rate = df["fixed_rate"].to_numpy(dtype=float)
    max_age = np.timedelta64(MID_WINDOW_MAX_AGE.value, "ns")

    for _, idx in df.groupby("mid_key", sort=False).indices.items():
        idx = np.asarray(idx)
        r = rate[idx]
        t = ts[idx]
        for j in range(MID_WINDOW_MIN_N, len(idx)):
            lo = max(0, j - MID_WINDOW_N)
            win_t = t[lo:j]
            win_r = r[lo:j]
            keep = (t[j] - win_t) <= max_age
            if keep.sum() < MID_WINDOW_MIN_N:
                continue
            mid[idx[j]] = np.median(win_r[keep])

    df["mid"] = mid
    s = np.zeros(len(df), dtype=np.int8)
    ok = np.isfinite(mid)
    s[ok & (df["fixed_rate"].to_numpy() > mid)] = 1
    s[ok & (df["fixed_rate"].to_numpy() < mid)] = -1
    # Single source of truth for the convention: assert the vectorised labels agree
    # with the scalar function on a sample, so the two can never silently diverge.
    _samp = np.random.default_rng(0).choice(len(df), size=min(2000, len(df)), replace=False)
    for i in _samp:
        assert s[i] == customer_sign_from_mid(float(rate[i]), float(mid[i])), "sign vectorisation drift"
    df["customer_sign"] = s
    return df


def stage_build() -> pd.DataFrame:
    tape = stage_tape()
    dissem = load_dissem_map()

    tape["fwd_key"] = _forward_key_series(tape["forward_start_years"])
    tape["bucket"] = _bucket_series(tape["tenor_years"])
    tape["dv01"] = tape["notional"] * tape["tenor_years"] * 1e-4
    tape["is_block"] = tape["is_block"].fillna(False).astype(bool)
    tape["venue_class"] = np.where(
        tape["platform_identifier"].isin(IDB_MICS), "IDB", "D2C"
    )
    tape["execution_timestamp"] = pd.to_datetime(tape["execution_timestamp"], utc=True)

    # --- validate the MIC map against the tape's own venue column -----------------
    tv = tape["venue"].map({"D2C": "D2C", "D2D": "IDB"})
    agree = (tv == tape["venue_class"]).mean()
    print(f"  venue_class vs tape `venue`: agreement {agree*100:.3f}% "
          f"({int((tv != tape['venue_class']).sum())} disagreements of {len(tape)})", flush=True)

    tape = attach_mid_sign(tape)

    # --- dissemination clock ------------------------------------------------------
    tape = tape.merge(
        dissem[["dissem_id", "dissem_ts_utc"]].rename(columns={"dissem_id": "trade_id"}),
        on="trade_id", how="left",
    )
    lag = (tape["dissem_ts_utc"] - tape["execution_timestamp"]).dt.total_seconds()
    # A matched slice earlier than the execution stamp is impossible; treat as unmatched.
    bad = lag.notna() & (lag < 0)
    n_bad = int(bad.sum())
    tape.loc[bad, "dissem_ts_utc"] = pd.NaT
    lag = (tape["dissem_ts_utc"] - tape["execution_timestamp"]).dt.total_seconds()
    matched = tape["dissem_ts_utc"].notna()
    med_lag = float(np.nanmedian(lag[matched])) if matched.any() else np.nan
    tape["dissem_is_real"] = matched
    tape.loc[~matched, "dissem_ts_utc"] = (
        tape.loc[~matched, "execution_timestamp"] + pd.Timedelta(seconds=med_lag)
    )

    # NB the headline real/estimated fraction must be scoped to the EMIT window.
    # The tape pull starts a week before HARVEST_START so the trailing-24h mid is warm
    # on 2026-05-01; those warm-up legs can never match a slice and would otherwise
    # inflate the "estimated" share of a file they contribute no rows to.
    in_win = (tape["execution_timestamp"] >= EMIT_START) & (tape["execution_timestamp"] < EMIT_END)
    print(f"  dissemination match (ALL pulled legs incl. mid warm-up): "
          f"{matched.sum()}/{len(tape)} = {matched.mean()*100:.2f}% real; "
          f"{n_bad} matches rejected as pre-execution", flush=True)
    print(f"  dissemination match (EMIT WINDOW only, the number that matters): "
          f"{(matched & in_win).sum()}/{in_win.sum()} = "
          f"{(matched[in_win]).mean()*100:.2f}% real, "
          f"{(~matched[in_win]).mean()*100:.2f}% estimated", flush=True)
    est_by_day = (~matched[in_win]).groupby(
        tape.loc[in_win, "execution_timestamp"].dt.date).mean().sort_values(ascending=False)
    worst = est_by_day[est_by_day > 0.01]
    if len(worst):
        print(f"  days with >1% estimated ({len(worst)} of {est_by_day.size}): "
              + ", ".join(f"{d} {v*100:.1f}%" for d, v in worst.head(8).items()), flush=True)
    if matched.any():
        qs = np.nanpercentile(lag[matched], [5, 25, 50, 75, 95, 99])
        print(f"  publication lag (min): p5={qs[0]/60:.2f} p25={qs[1]/60:.2f} "
              f"p50={qs[2]/60:.2f} p75={qs[3]/60:.2f} p95={qs[4]/60:.2f} p99={qs[5]/60:.2f}",
              flush=True)

    # --- bin ----------------------------------------------------------------------
    frames = []
    for clock, tscol in (("exec", "execution_timestamp"), ("diss", "dissem_ts_utc")):
        sub = tape[["bucket", "is_block", "venue_class", "dv01", "customer_sign", tscol]].copy()
        sub["minute_utc"] = sub[tscol].dt.floor("min")
        sub = sub[(sub["minute_utc"] >= EMIT_START) & (sub["minute_utc"] < EMIT_END)]
        sub["signed"] = sub["customer_sign"].astype(float) * sub["dv01"]
        g = sub.groupby(["bucket", "minute_utc", "is_block", "venue_class"], sort=False).agg(
            signed_dv01=("signed", "sum"),
            gross_dv01=("dv01", "sum"),
            n_prints=("dv01", "size"),
        ).reset_index()
        g["clock"] = clock
        frames.append(g)

    out = pd.concat(frames, ignore_index=True)
    out = out[["bucket", "minute_utc", "clock", "signed_dv01", "gross_dv01",
               "n_prints", "is_block", "venue_class"]]
    out = out.sort_values(["clock", "bucket", "minute_utc", "is_block", "venue_class"]).reset_index(drop=True)

    DATA.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PARQUET.with_suffix(".tmp.parquet")
    out.to_parquet(tmp, index=False)
    os.replace(tmp, OUT_PARQUET)

    # Persist the SIGNED PER-PRINT frame. X itself is the binned aggregate, but
    # addendum 1's D1 diagnostic needs `dev_median = fixed_rate - mid` per print,
    # which otherwise exists only transiently in here. Handing over the exact frame
    # X was built from removes any drift between "R0's actual input" and what D1
    # measures. This is a convenience artifact, not part of the X contract.
    legs_out = tape[[
        "trade_id", "execution_timestamp", "dissem_ts_utc", "dissem_is_real",
        "bucket", "tenor_years", "tenor_label", "fwd_key", "is_mac", "mid_key",
        "fixed_rate", "mid", "customer_sign", "dv01", "is_block", "venue_class",
        "platform_identifier", "trade_type", "is_notional_capped",
    ]].copy()
    legs_out["dev_median"] = legs_out["fixed_rate"] - legs_out["mid"]
    tmp = SIGNED_LEGS_CACHE.with_suffix(".tmp.parquet")
    legs_out.to_parquet(tmp, index=False)
    os.replace(tmp, SIGNED_LEGS_CACHE)
    print(f"  wrote signed per-print frame -> {SIGNED_LEGS_CACHE} ({len(legs_out)} legs)",
          flush=True)

    _report(tape, out)
    return out


def _report(tape: pd.DataFrame, out: pd.DataFrame) -> None:
    emit = tape[(tape["execution_timestamp"] >= EMIT_START) & (tape["execution_timestamp"] < EMIT_END)]
    print("\n================ R0 / X build report ================")
    print(f"N_prints (in-scope, exec clock in window) : {len(emit)}")
    print(f"N_days   (distinct UTC exec days)         : {emit['execution_timestamp'].dt.date.nunique()}")
    for clock in ("exec", "diss"):
        o = out[out["clock"] == clock]
        print(f"N_bins   [{clock}] cells={len(o)}  distinct minutes={o['minute_utc'].nunique()}")
    sg = emit["customer_sign"]
    n_signed = int((sg != 0).sum())
    print(f"\nDirection: signed {n_signed}/{len(emit)} ({n_signed/len(emit)*100:.1f}%), "
          f"unsigned {(len(emit)-n_signed)/len(emit)*100:.1f}%")
    if n_signed:
        print(f"  customer PAID fixed: {(sg==1).sum()/n_signed*100:.2f}% of signed prints "
              f"(50/50 is the neutral benchmark)")
    print(f"  dissemination: {emit['dissem_is_real'].mean()*100:.2f}% real, "
          f"{(~emit['dissem_is_real']).mean()*100:.2f}% estimated (emit window)")
    blk = emit["is_block"]
    print(f"  block prints: {blk.sum()} ({blk.mean()*100:.2f}%); "
          f"notional-capped: {emit['is_notional_capped'].fillna(False).mean()*100:.2f}%")
    print("\nPer-bucket coverage (exec clock, in window):")
    hdr = f"  {'bucket':8s} {'n_prints':>9s} {'%signed':>8s} {'%paid':>7s} {'dv01_sum_mm':>12s} {'n_minutes':>10s} {'%block':>7s} {'%IDB':>6s}"
    print(hdr)
    for b in BUCKETS:
        e = emit[emit["bucket"] == b]
        if not len(e):
            print(f"  {b:8s} {'0':>9s}   -- EMPTY BUCKET --")
            continue
        s = e["customer_sign"]
        ns = int((s != 0).sum())
        nm = out[(out["clock"] == "exec") & (out["bucket"] == b)]["minute_utc"].nunique()
        print(f"  {b:8s} {len(e):>9d} {ns/len(e)*100:>7.1f}% "
              f"{((s==1).sum()/ns*100) if ns else float('nan'):>6.2f}% "
              f"{e['dv01'].sum()/1e6:>12.1f} {nm:>10d} "
              f"{e['is_block'].mean()*100:>6.2f}% {(e['venue_class']=='IDB').mean()*100:>5.2f}%")
    print(f"\nwrote {OUT_PARQUET}  ({len(out)} rows)")
    print("NOTE: the file is SPARSE (only non-empty cells). Reindex onto the full")
    print("      (bucket x minute x clock x is_block x venue_class) grid and fill 0.")
    print("=====================================================")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["harvest", "tape", "build", "all"], default="all")
    args = ap.parse_args()
    if args.stage in ("harvest", "all"):
        stage_harvest()
    if args.stage in ("tape", "all"):
        stage_tape()
    if args.stage in ("build", "all"):
        stage_build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
