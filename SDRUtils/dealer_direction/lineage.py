"""Unwind lineage: which earlier print does this termination tear up?

The v3 tape has no ``Original Dissemination Identifier``. The raw DTCC file
does, on 100% of MODI / CORR / TERM / EROR / REVI rows and 0.00% of NEWT rows,
so lineage is recoverable outside the tape -- as a sidecar, not as a 610-day
delete-and-rewrite of a production table.

THERE ARE NOW TWO DTCC READERS IN THIS REPO AND THEY FILTER DIFFERENTLY
----------------------------------------------------------------------

``SDRUtils/data/builder.py::fetch_historical_reports`` masks each day's frame on
``Execution Timestamp.dt.date`` *before* persisting (``:422-424``), and the daily
service calls it with ``start == end == D``. A lifecycle row carries the
**original's** execution date (spec: #96 "remains unchanged throughout the life
of the UTI"), so it falls outside that mask and is never written. Measured on
2026-08-06 by re-fetching the same day's zip unfiltered:

===============  =======  =======  ===============
action           in zip    kept     lost
===============  =======  =======  ===============
all rows          18,520   16,601   1,919 (10.4%)
TERM                 624      367     257 (41.2%)
TERM / ETRM          411      247            39.9%
TERM / EXER           67        4            94.0%
MODI               2,014      993            50.7%
===============  =======  =======  ===============

and ``ignore_cache=True`` loses the *identical* 1,919 ids, because the mask is
inside the function that path still calls. Every one of the 257 lost
terminations has an execution date strictly before the file date -- median 89
days, p99 8.7 years.

So: ``sdr_cache`` is the **filtered** reader and is correct for flow work;
this module is the **unfiltered** reader and is the only one lineage may use.
They are deliberately kept in different trees (:data:`RAW_SUBDIR`) so a reader
cannot silently pick up the other one's frames and report clean coverage of a
population that is missing 41% of its terminations.

MULTI-HOP IS NOT AN OPTIMISATION
--------------------------------

Appendix F Example 1 draws a star: the second dissemination points at the
original. The data disagrees -- 43 TERM->TERM pointers in a single week, which
is a chain of partial terminations and which a star topology cannot represent.
Single-hop resolution stops at the middle termination and books the original as
unresolved, so the walk here is transitive with a cycle guard.

``SDRUtils/core/graph_resolver.build_synthetic_uti_mapping`` already clusters
these ids and is **not** used: it builds an *undirected* graph and anchors each
component on "earliest NEWT, else earliest timestamp". When the original is
outside the loaded window -- 24.5% of terminations by the measured reach-back --
the component contains no NEWT, so the anchor lands on the termination itself
and the pointer target is thrown away. Pinned by test.
"""
from __future__ import annotations

import asyncio
import datetime
import io
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from SDRUtils.dealer_direction.conventions import DEALER_PAID, DEALER_RECEIVED

logger = logging.getLogger(__name__)

# --- raw column names, spelled exactly as DTCC spells them ----------------
DI = "Dissemination Identifier"
ODI = "Original Dissemination Identifier"
ACTION = "Action type"
EVENT = "Event type"
EVENT_TS = "Event timestamp"
EXEC_TS = "Execution Timestamp"

#: The columns lineage resolution needs. Reading only these keeps a 60-day
#: union at a few hundred MB instead of a few GB -- the raw file has 111
#: columns and the walk uses six of them.
LINEAGE_COLUMNS = (DI, ODI, ACTION, EVENT, EVENT_TS, EXEC_TS,
                   "UPI FISN", "Notional currency-Leg 1", "Other payment amount",
                   "file_date")

#: Actions measured to carry a pointer on 100% of rows; NEWT on 0.00%.
POINTER_ACTIONS = ("MODI", "CORR", "TERM", "EROR", "REVI")

# --- where the sidecar lives ----------------------------------------------
STORE_ROOT_ENV = "DD_LINEAGE_STORE"
DEFAULT_STORE_ROOT = "./dd_lineage_store"
#: Deliberately not ``sdr_cache`` and deliberately self-describing.
RAW_SUBDIR = "raw_dtcc_unfiltered"
LINEAGE_SUBDIR = "lineage"
LEDGER_NAME = "_ledger.json"

# --- resolution status vocabulary -----------------------------------------
#: The terminal id is a print the tape ingested. The flippable population.
ST_RESOLVED_TAPE = "RESOLVED_TAPE"
#: The terminal id is present in the raw window but was not looked up in (or not
#: found in) the tape -- still lineage, just not joinable to a tape row.
ST_RESOLVED_RAW_ONLY = "RESOLVED_RAW_ONLY"
#: Numerically below the tape's first id. 5.6% of TERMs, and they resolved
#: 0/206 -- an internal consistency check, not a data defect.
ST_PRE_TAPE = "PRE_TAPE"
#: Inside the tape's id range and genuinely absent: a print the tape never
#: ingested (non-USD, non-swap, or a real ingestion miss).
ST_MISSING_IN_RANGE = "MISSING_IN_RANGE"
ST_ABOVE_RANGE = "ABOVE_RANGE"
#: No tape id range was supplied, so the above decomposition is not available.
ST_UNRESOLVED = "UNRESOLVED"
ST_CYCLE = "CYCLE"
ST_MAX_HOPS = "MAX_HOPS"
#: ``ODI == own DI``. 361 rows in the 2026-06-15..18 week, 193 of them TERM.
#: Not lineage: the "original" it names is the message itself.
ST_SELF_POINTER = "SELF_POINTER"

#: A chain of partial terminations is a handful of hops; anything past this is a
#: pathology, and an unbounded walk over 1.6M rows is a hang, not an error.
DEFAULT_MAX_HOPS = 16

# --- visibility provenance -------------------------------------------------
#: The measured DTCC publication time (intraday slice member mtime).
VISIBILITY_SLICE_MTIME = "DTCC_SLICE_MTIME"
#: 17 CFR Part 43 Appendix C legal delay, via the frozen ladder conventions.
VISIBILITY_APPENDIX_C = "PART43_APPENDIX_C"

#: The slice zip stamps its member in DTCC's own wall clock, which is Eastern.
#: Validated against the listing's ``dissemDTM`` on 10 live slices: ET->UTC sits
#: 2-4 s early, median |delta| 3.0 s, 10/10. Read as UTC it is four hours wrong
#: and entirely plausible.
SLICE_MEMBER_TZ = "America/New_York"


class EmptyDTCCDay(RuntimeError):
    """The upstream served nothing for a day the caller asked for.

    Raised rather than returning an empty frame. A backfill in this repo once
    recorded days as ``ok`` on exit code 0 while the upstream returned an empty
    frame, and six days of data were destroyed before anyone noticed; a zero-row
    parquet on disk is indistinguishable from a genuinely quiet day forever
    after.
    """


class EmptyLineageDay(RuntimeError):
    """Resolution produced no rows for a day. Same reasoning as above."""


# ==========================================================================
# 1. The unfiltered reader
# ==========================================================================

def store_root(root=None) -> Path:
    return Path(root if root is not None else os.getenv(STORE_ROOT_ENV, DEFAULT_STORE_ROOT))


def raw_day_path(day, *, root=None, agency="CFTC", asset_class="RATES") -> Path:
    d = _as_date(day)
    return (store_root(root) / RAW_SUBDIR / agency / asset_class
            / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.parquet")


def date_string(day) -> str:
    """DTCC's file-name date form, ``YYYY_MM_DD``."""
    return _as_date(day).strftime("%Y_%m_%d")


def cumulative_url(day, *, agency="CFTC", asset_class="RATES") -> str:
    return (f"https://pddata.dtcc.com/ppd/api/report/cumulative/{agency.lower()}/"
            f"{agency}_CUMULATIVE_{asset_class}_{date_string(day)}.zip")


def fetch_raw_day(day, *, root=None, zip_source=None, force=False,
                  agency="CFTC", asset_class="RATES") -> pd.DataFrame:
    """One day's cumulative DTCC file, **unfiltered**, cached as parquet.

    ``zip_source`` is injected so the whole module tests offline; the default
    reuses ``DTCCFetcher._fetch_dtcc_sdr_data_helper`` and
    ``_extract_dataframes_from_zip`` -- the two methods that never touch the
    parquet cache and never apply the execution-date mask -- rather than
    re-implementing the transport, its retry policy or its header set.

    No row is dropped on any date criterion. That is the entire point: see the
    module docstring for what the masked reader loses.
    """
    path = raw_day_path(day, root=root, agency=agency, asset_class=asset_class)
    if path.exists() and not force:
        return pd.read_parquet(path)

    src = zip_source if zip_source is not None else _dtcc_zip_source(agency, asset_class)
    buf = src(date_string(day))
    if buf is None:
        raise EmptyDTCCDay(f"DTCC served no {agency}/{asset_class} file for {_as_date(day)}")

    from SDRUtils.data.builder import DTCCFetcher

    frames = DTCCFetcher()._extract_dataframes_from_zip(
        buf, convert_key_into_dt=False, parallelize=False, use_pyarrow=True)
    frames = [f for f in frames.values() if f is not None and not f.empty]
    if not frames:
        raise EmptyDTCCDay(f"{agency}/{asset_class} zip for {_as_date(day)} held no rows")

    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0].copy()
    for col in (EVENT_TS, EXEC_TS):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    for col in (DI, ODI):
        if col in df.columns:
            df[col] = df[col].map(normalise_id).astype("string")
    df["file_date"] = _as_date(day)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)                       # atomic: a half-written day is not a day
    return df


def load_raw_days(days, *, root=None, columns=LINEAGE_COLUMNS,
                  agency="CFTC", asset_class="RATES") -> pd.DataFrame:
    """The union of the cached raw days, for resolution.

    Resolution runs over the **union**, never day by day: a termination on day D
    can point at a MODI from D-3 that points at the NEWT from D-40, and a
    per-day resolve would book that as a broken chain rather than a two-hop one.
    """
    out = []
    for day in days:
        p = raw_day_path(day, root=root, agency=agency, asset_class=asset_class)
        if not p.exists():
            continue
        cols = None
        if columns:
            # asked-for columns intersected with what the file HAS: DTCC's schema
            # is not identical across years and a missing column is a hard
            # pyarrow error, which would take the whole union down for one day.
            have = set(_parquet_columns(p))
            cols = [c for c in columns if c in have]
        out.append(pd.read_parquet(p, columns=cols))
    if not out:
        return pd.DataFrame(columns=list(columns or []))
    df = pd.concat(out, ignore_index=True, sort=False)
    for col in (DI, ODI):
        if col in df.columns:
            df[col] = df[col].map(normalise_id).astype("string")
    return df


def _parquet_columns(path) -> list:
    import pyarrow.parquet as pq

    return list(pq.ParquetFile(path).schema.names)


def _dtcc_zip_source(agency, asset_class):
    def _src(ds: str):
        import httpx

        from SDRUtils.data.builder import DTCCFetcher

        async def run():
            f = DTCCFetcher(error_verbose=True)
            limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
            async with httpx.AsyncClient(limits=limits, timeout=180, verify=False,
                                         http2=True) as client:
                return await f._fetch_dtcc_sdr_data_helper(
                    client=client, date_string=ds, agency=agency,
                    asset_class=asset_class, max_retries=3, backoff_factor=2)

        return asyncio.run(run())

    return _src


# ==========================================================================
# 2. Multi-hop resolution
# ==========================================================================

def normalise_id(value):
    """One spelling for a dissemination id.

    ``123`` and ``123.0`` are the same print, and a float round trip through
    pandas is exactly how a pointer becomes unresolvable -- the join simply
    misses and the row is booked as a tape ingestion gap.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:                          # NaN
            return None
        if value.is_integer():
            return str(int(value))
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):                 # arrays / odd objects
        pass
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "<na>", "null"}:
        return None
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


LINEAGE_SCHEMA = ("dissemination_id", "pointer_id", "resolved_original_id", "hops",
                  "reach_back_days", "status", "action_type", "event_type",
                  "terminal_action", "event_timestamp", "original_execution_timestamp",
                  "file_date")


def resolve_lineage(raw: pd.DataFrame, *, exec_ts_lookup=None, tape_id_range=None,
                    max_hops=DEFAULT_MAX_HOPS) -> pd.DataFrame:
    """Walk every pointer back to the print it ultimately descends from.

    One row out per **pointer-carrying** row in; NEWT rows are nodes in the walk
    but never keys, because they carry a pointer on 0.00% of rows and writing
    them would triple the store with ids that can never be looked up.

    ``exec_ts_lookup`` maps a batch of terminal ids to the tape's
    ``execution_timestamp``; injected so this function -- and its tests -- need
    no database. Reach-back is ``unwind event timestamp - the original's
    execution timestamp``, the definition the 75.5% / 90.7% / 95.6% coverage at
    1 / 63 / 252 days was measured under.
    """
    if raw is None or raw.empty or DI not in raw.columns:
        return pd.DataFrame(columns=list(LINEAGE_SCHEMA))

    ids = raw[DI].map(normalise_id)
    pointers = (raw[ODI].map(normalise_id) if ODI in raw.columns
                else pd.Series([None] * len(raw), index=raw.index))
    actions = raw[ACTION] if ACTION in raw.columns else pd.Series([None] * len(raw), index=raw.index)
    events = raw[EVENT] if EVENT in raw.columns else pd.Series([None] * len(raw), index=raw.index)
    ev_ts = pd.to_datetime(raw[EVENT_TS], utc=True, errors="coerce") if EVENT_TS in raw.columns \
        else pd.Series(pd.NaT, index=raw.index)
    ex_ts = pd.to_datetime(raw[EXEC_TS], utc=True, errors="coerce") if EXEC_TS in raw.columns \
        else pd.Series(pd.NaT, index=raw.index)

    # parent holds ONLY rows that carry a pointer, so `cur in parent` answers
    # "does the walk continue" and `cur in known` answers "is this id a row we
    # have". Collapsing the two -- a single dict with None values -- makes an
    # in-window NEWT and an out-of-window original indistinguishable.
    parent, known, action_of, exec_of = {}, set(), {}, {}
    for i, di in ids.items():
        if di is None:
            continue
        known.add(di)
        action_of[di] = actions.get(i)
        exec_of[di] = ex_ts.get(i)
        p = pointers.get(i)
        if p is not None and p != di:
            parent[di] = p

    rows = []
    for i, di in ids.items():
        p = pointers.get(i)
        if di is None or p is None:
            continue
        cur, hops, seen, status = di, 0, {di}, None
        if p == di:
            # A message naming itself as its own original. Resolving that to
            # "itself" would look exactly like a one-hop success and hand the
            # consumer the unwind row in place of the trade it tears up.
            status = ST_SELF_POINTER
        while status is None:
            nxt = parent.get(cur)
            if nxt is None:
                break                                # terminal: no pointer, or not a row we hold
            if nxt in seen:
                status = ST_CYCLE
                break
            seen.add(nxt)
            cur, hops = nxt, hops + 1
            if hops >= max_hops:
                status = ST_MAX_HOPS
                break
        rows.append({
            "dissemination_id": di,
            "pointer_id": p,
            "resolved_original_id": cur,
            "hops": hops,
            "status": status,
            "action_type": actions.get(i),
            "event_type": events.get(i),
            "terminal_action": action_of.get(cur),
            "event_timestamp": ev_ts.get(i),
            "file_date": raw["file_date"].get(i) if "file_date" in raw.columns else None,
        })

    out = pd.DataFrame(rows, columns=[c for c in LINEAGE_SCHEMA if c not in
                                      ("reach_back_days", "original_execution_timestamp")])
    if out.empty:
        return pd.DataFrame(columns=list(LINEAGE_SCHEMA))

    # The original's execution time: the tape first, the raw window second.
    # Every terminal is looked up, including ones present in the window -- a
    # terminal that is in the raw file AND in the tape is the flippable case,
    # and short-circuiting on "already have a row for it" would file it as
    # RESOLVED_RAW_ONLY and hide it from exactly the population that matters.
    tape_ts = {}
    if exec_ts_lookup is not None:
        wanted = sorted({t for t, s in zip(out["resolved_original_id"], out["status"])
                         if s is None})
        tape_ts = {normalise_id(k): pd.Timestamp(v)
                   for k, v in (exec_ts_lookup(wanted) or {}).items() if v is not None}

    orig_ts, status_out = [], []
    for terminal, st in zip(out["resolved_original_id"], out["status"]):
        if st is not None:                            # CYCLE / MAX_HOPS keep their status
            orig_ts.append(pd.NaT)
            status_out.append(st)
            continue
        if terminal in tape_ts:
            orig_ts.append(tape_ts[terminal])
            status_out.append(ST_RESOLVED_TAPE)
        elif terminal in known:
            orig_ts.append(exec_of.get(terminal, pd.NaT))
            status_out.append(ST_RESOLVED_RAW_ONLY)
        else:
            orig_ts.append(pd.NaT)
            status_out.append(_unresolved_status(terminal, tape_id_range))
    out["status"] = status_out
    out["original_execution_timestamp"] = pd.to_datetime(pd.Series(orig_ts, index=out.index),
                                                         utc=True, errors="coerce")
    out["reach_back_days"] = ((out["event_timestamp"] - out["original_execution_timestamp"])
                              .dt.total_seconds() / 86400.0)
    return out[list(LINEAGE_SCHEMA)]


def _unresolved_status(terminal, tape_id_range) -> str:
    if tape_id_range is None:
        return ST_UNRESOLVED
    lo, hi = tape_id_range
    try:
        n = int(str(terminal))
    except (TypeError, ValueError):
        return ST_MISSING_IN_RANGE
    if n < int(lo):
        return ST_PRE_TAPE
    if n > int(hi):
        return ST_ABOVE_RANGE
    return ST_MISSING_IN_RANGE


def coverage_summary(lineage: pd.DataFrame, *, reach_days=(0, 1, 7, 63, 90, 252, 365)) -> dict:
    """The numbers the backfill prints and the report quotes.

    Reach-back percentiles are reported over the *resolved* rows only, which is
    the base the 75.5 / 90.7 / 95.6 figures were measured on.
    """
    if lineage is None or lineage.empty:
        return {"n": 0}
    resolved = lineage["status"].isin([ST_RESOLVED_TAPE, ST_RESOLVED_RAW_ONLY])
    out = {
        "n": int(len(lineage)),
        "by_status": lineage["status"].value_counts().to_dict(),
        "by_action": lineage["action_type"].value_counts().to_dict(),
        "resolved": int(resolved.sum()),
        "resolved_pct": round(100.0 * float(resolved.mean()), 2),
        "multi_hop": int((lineage["hops"] > 1).sum()),
        "max_hops": int(lineage["hops"].max()),
    }
    rb = lineage.loc[resolved, "reach_back_days"].dropna()
    if len(rb):
        out["reach_back_cum_pct"] = {f"<={d}d": round(100.0 * float((rb <= d).mean()), 2)
                                     for d in reach_days}
        out["reach_back_max_days"] = round(float(rb.max()), 1)
    return out


# ==========================================================================
# 3. The store
# ==========================================================================

class LineageStore:
    """Parquet per day, keyed on the dissemination id of the *pointing* row.

    Partitioned on the file date the pointer was disseminated on -- not on the
    original's date -- because that is the unit a backfill can resume on and the
    unit a consumer asks for.
    """

    def __init__(self, root=None):
        self._root = store_root(root)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, day) -> Path:
        d = _as_date(day)
        return (self._root / LINEAGE_SUBDIR / f"{d.year:04d}" / f"{d.month:02d}"
                / f"{d.isoformat()}.parquet")

    def write_day(self, day, frame: pd.DataFrame) -> int:
        if frame is None or frame.empty:
            raise EmptyLineageDay(
                f"lineage resolution produced zero rows for {_as_date(day)}; refusing to "
                "write an empty partition that would later read as a quiet day")
        path = self.path_for(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        frame.to_parquet(tmp, index=False)
        tmp.replace(path)
        return len(frame)

    def read_day(self, day) -> pd.DataFrame:
        p = self.path_for(day)
        return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=list(LINEAGE_SCHEMA))

    def read_range(self, start, end) -> pd.DataFrame:
        days = [d for d in self.covered_days() if _as_date(start) <= d <= _as_date(end)]
        frames = [self.read_day(d) for d in days]
        frames = [f for f in frames if not f.empty]
        return pd.concat(frames, ignore_index=True) if frames else \
            pd.DataFrame(columns=list(LINEAGE_SCHEMA))

    def covered_days(self) -> list:
        base = self._root / LINEAGE_SUBDIR
        if not base.exists():
            return []
        return sorted(datetime.date.fromisoformat(p.stem) for p in base.rglob("*.parquet"))

    def rows_for(self, day) -> int:
        """Row count from the file itself -- the authority for "is this day done"."""
        p = self.path_for(day)
        if not p.exists():
            return 0
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(p).metadata.num_rows)

    def days_needing_work(self, days) -> list:
        """Outstanding days, recomputed from the **target set**, not the ledger.

        The documented backfill trap in this repo is completion scoped to the
        ledger while days are silently absent from the range. A day counts as
        done only when its parquet exists and has rows in it.
        """
        return [_as_date(d) for d in days if self.rows_for(d) == 0]

    # --- the ledger is a record, never the authority ----------------------
    @property
    def ledger_path(self) -> Path:
        return self._root / LINEAGE_SUBDIR / LEDGER_NAME

    def read_ledger(self) -> dict:
        p = self.ledger_path
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("lineage ledger at %s is unreadable; treating as empty", p)
            return {}

    def record(self, day, *, rows: int, **extra) -> None:
        led = self.read_ledger()
        led[_as_date(day).isoformat()] = {
            "rows": int(rows),
            "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            **extra,
        }
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(led, indent=1, sort_keys=True))


# ==========================================================================
# 4. The publication clock
# ==========================================================================

def slice_date_strings(day, seqs) -> list:
    """``CFTC_SLICE_RATES_<ds>.zip`` name stems for one day's slice sequence.

    The listing API only shows a rolling 24 h, but the files themselves are
    still served for past dates, so the ~10-second publication clock is
    recoverable historically by enumerating sequence numbers.

    **A day runs to ~1,970 slices, not the ~1,333 the listing suggests** --
    bisected on three days: 1,896 (06-16), 1,930 (06-15), 1,969 (08-10). The
    listing count is a rolling window, not a calendar day, and stopping at
    1,333 silently covers only 73.7% of a day's prints while looking complete.
    Measured cost: 27.8 s for 1,333 slices at 8 workers, so ~40 s for a full
    day; see :data:`~scripts.build_dd_lineage_store.CODE_VINTAGE` runbook notes
    before promising the whole tape.
    """
    ds = date_string(day)
    return [f"{ds}_{int(s)}" for s in seqs]


def slice_publication_time(zip_buffer):
    """The real dissemination time: the zip member's mtime, ET -> UTC.

    The cumulative daily file has no publication column at all. This one does,
    and it was validated against the slice listing's own ``dissemDTM`` on 10
    live slices -- 2-4 s early, median |delta| 3.0 s, 10/10.
    """
    import pyzipper

    buf = io.BytesIO(zip_buffer) if isinstance(zip_buffer, (bytes, bytearray)) else zip_buffer
    pos = buf.tell() if hasattr(buf, "tell") else 0
    with pyzipper.AESZipFile(buf) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if not infos:
            return None
        stamp = infos[0].date_time
    if hasattr(buf, "seek"):
        buf.seek(pos)
    local = pd.Timestamp(datetime.datetime(*stamp)).tz_localize(SLICE_MEMBER_TZ)
    return local.tz_convert("UTC")


def fetch_slice_publications(day, seqs, *, workers=8, slice_source=None,
                             agency="CFTC", asset_class="RATES") -> pd.DataFrame:
    """``dissemination_id -> published_at`` for a set of slice sequence numbers.

    One HTTP round trip per slice, so this is priced per day, not per row --
    :mod:`scripts.build_dd_lineage_store` measures it before enabling it.
    """
    from SDRUtils.data.builder import DTCCFetcher

    fetcher = DTCCFetcher()
    src = slice_source if slice_source is not None else _slice_http_source(fetcher, agency, asset_class)

    def one(ds):
        # Per-slice defensive. Enumerating ~2,000 sequence numbers turns up
        # members the CSV reader cannot tokenise (one killed a whole day's scan
        # with a C-level out-of-memory inside `read_csv`), and one bad slice
        # must cost one slice, not the day.
        try:
            buf = src(ds)
            if buf is None:
                return None
            pub = slice_publication_time(buf)
            if pub is None:
                return None
            frames = fetcher._extract_dataframes_from_zip(buf, convert_key_into_dt=False,
                                                          use_pyarrow=True)
        except Exception as exc:  # noqa: BLE001 - a corrupt member is data, not a bug
            logger.warning("slice %s unreadable (%s: %s)", ds, type(exc).__name__, exc)
            return None
        frames = [f for f in frames.values() if f is not None and not f.empty]
        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        keep = [c for c in (DI, ODI, ACTION, EVENT, EVENT_TS, "UPI FISN",
                            "Notional currency-Leg 1") if c in df.columns]
        out = df[keep].copy()
        out["published_at"] = pub
        out["slice"] = ds
        return out

    names = slice_date_strings(day, seqs)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        got = [g for g in ex.map(one, names) if g is not None]
    if not got:
        return pd.DataFrame(columns=[DI, "published_at", "slice"])
    out = pd.concat(got, ignore_index=True)
    out[DI] = out[DI].map(normalise_id).astype("string")
    # a print can appear in several slices; the FIRST publication is the bound
    return out.sort_values("published_at").drop_duplicates(subset=[DI], keep="first")


def _slice_http_source(fetcher, agency, asset_class):
    import requests

    session = requests.Session()

    def _src(ds: str):
        url, headers = fetcher._get_dtcc_url_and_header(agency, asset_class, ds)
        try:
            r = session.get(url, headers=headers, timeout=90)
        except requests.RequestException:
            return None
        if r.status_code != 200 or not r.content:
            return None
        return io.BytesIO(r.content)

    return _src


class PublicationClock:
    """An availability clock ``types.Clocks.visibility`` can be built from.

    Two sources, and the row records which one it got: the measured DTCC
    publication time where a slice scan has one, and the Part 43 Appendix C
    legal estimate otherwise. They are not interchangeable -- measured
    NEWT/OIS/USD publication lag is 5.23 min median / 11.3 min p95, against a
    60-minute *indeterminate* legal delay -- so a consumer that cares must be
    able to gate on ``visibility_source``.
    """

    def __init__(self, published_at=None):
        self._by_id = {normalise_id(k): pd.Timestamp(v)
                       for k, v in dict(published_at or {}).items() if v is not None}

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, *, id_col=DI, ts_col="published_at"):
        if frame is None or frame.empty:
            return cls({})
        return cls(dict(zip(frame[id_col], pd.to_datetime(frame[ts_col], utc=True))))

    def __len__(self) -> int:
        return len(self._by_id)

    def published_at(self, dissemination_id):
        return self._by_id.get(normalise_id(dissemination_id))

    def visibility(self, dissemination_id, execution_ts, **appendix_c_kwargs):
        """``(timestamp, source)`` -- the measured time if there is one.

        A measured time *earlier* than the execution it publishes is refused and
        falls back. That is not a tighter bound, it is a broken one: it would
        let an aggregation see a print before it existed, which is the single
        error the visibility clock exists to prevent.
        """
        ts = self.published_at(dissemination_id)
        exec_ts = pd.Timestamp(execution_ts)
        if ts is not None and ts >= exec_ts:
            return ts, VISIBILITY_SLICE_MTIME
        from SDRUtils.stir_flow.ladder_conventions import visibility_timestamp

        return visibility_timestamp(exec_ts, **appendix_c_kwargs), VISIBILITY_APPENDIX_C


# ==========================================================================
# 5. The TERM <-> NEWT direction agreement check
# ==========================================================================

def unwind_implied_original_sign(npv_pay, upfront) -> int:
    """The dealer's side **in the original trade**, inferred from the TERM row.

    ``npv_pay`` is ``f = (mid - R) * A``, the NPV of the residual original swap
    in the fixed-*payer* frame at the unwind instant; ``upfront`` is the row's
    unsigned ``Other payment amount``.

    THE INEQUALITY RUNS THE OTHER WAY FROM THE ENTRY RULE. On entry the party
    taking the in-the-money side *pays* for it, so ``U < |f|`` means the dealer
    holds the ITM side -- which is what ``stir_flow/classifier.py:77`` encodes.
    On an unwind the ITM party is *paid out*, and the dealer prices the payout
    in its own favour: it pays a customer less than the position is worth, and
    charges a customer more than the position costs it to release. So

    ::

        U < |f|   =>   the ITM party was underpaid   =>   the CUSTOMER is ITM
        U > |f|   =>   the exit was overcharged      =>   the DEALER is ITM

    and the ITM side is pay-fixed exactly when ``f > 0``. Carrying the entry
    rule over to terminations inverts every call and produces a complete,
    plausible ladder that is exactly wrong.

    Returns :data:`~.conventions.DEALER_RECEIVED` / ``DEALER_PAID``, or ``0``
    when the fee ties the value exactly or an input is missing -- 0 is "no
    call", never a side.
    """
    if npv_pay is None or upfront is None:
        return 0
    try:
        f, u = float(npv_pay), abs(float(upfront))
    except (TypeError, ValueError):
        return 0
    if f != f or u != u or f == 0.0:
        return 0
    if u == abs(f):
        return 0
    customer_is_itm = u < abs(f)
    itm_is_pay_fixed = f > 0
    customer_paid_fixed = (customer_is_itm == itm_is_pay_fixed)
    # the pinned convention: customer pays fixed -> dealer RECEIVED fixed
    return DEALER_RECEIVED if customer_paid_fixed else DEALER_PAID


def unwind_dealer_sign(npv_pay, upfront) -> int:
    """The side the dealer takes **on the unwind transaction**.

    Tearing up a position is taking the other side of it, so this is the
    negation of :func:`unwind_implied_original_sign`. Both spellings exist
    because the two framings of the agreement check -- "flip the original and
    compare" versus "compare the two estimates of the original" -- are the same
    statement, and naming only one of them is how a double negation gets in.
    """
    return -unwind_implied_original_sign(npv_pay, upfront)


def direction_agreement(pairs: pd.DataFrame, *, original_col="original_dealer_sign",
                        unwind_col="unwind_dealer_sign") -> dict:
    """How often the unwind's own inference is the flip of the original's.

    The only quasi-labelled data in this program, and it bounds the classifier's
    *absolute* error rate rather than its agreement with another model. Three
    caveats travel with every number it produces:

    * only 15.7% of terminations carry an ``Other payment amount``, so the
      measured population is a small and possibly unrepresentative slice;
    * the flip inherits the original print's inference error **in full** -- a
      disagreement does not say which of the two was wrong;
    * it is a consistency check, not ground truth. Both inferences use a curve.
    """
    if pairs is None or len(pairs) == 0:
        return {"n_pairs": 0, "n_called": 0, "n_agree": 0, "agreement": None}
    o = pd.to_numeric(pairs[original_col], errors="coerce").fillna(0).astype(int)
    u = pd.to_numeric(pairs[unwind_col], errors="coerce").fillna(0).astype(int)
    called = (o != 0) & (u != 0)
    agree = called & (u == -o)
    n_called = int(called.sum())
    return {
        "n_pairs": int(len(pairs)),
        "n_called": n_called,
        "n_agree": int(agree.sum()),
        "agreement": (float(agree.sum()) / n_called) if n_called else None,
        "table": {f"orig{'+' if a > 0 else '-'}_unwind{'+' if b > 0 else '-'}":
                  int(((o == a) & (u == b)).sum())
                  for a in (1, -1) for b in (1, -1)},
    }


# ==========================================================================

def _as_date(day) -> datetime.date:
    if isinstance(day, datetime.datetime):
        return day.date()
    if isinstance(day, datetime.date):
        return day
    return pd.Timestamp(day).date()


__all__ = [
    "ACTION", "DEALER_PAID", "DEALER_RECEIVED", "DI", "EVENT", "EVENT_TS", "EXEC_TS",
    "EmptyDTCCDay", "EmptyLineageDay", "LINEAGE_COLUMNS", "LINEAGE_SCHEMA",
    "LineageStore", "ODI", "POINTER_ACTIONS", "PublicationClock", "RAW_SUBDIR",
    "ST_ABOVE_RANGE", "ST_CYCLE", "ST_MAX_HOPS", "ST_MISSING_IN_RANGE", "ST_PRE_TAPE",
    "ST_RESOLVED_RAW_ONLY", "ST_RESOLVED_TAPE", "ST_UNRESOLVED",
    "VISIBILITY_APPENDIX_C", "VISIBILITY_SLICE_MTIME", "coverage_summary",
    "cumulative_url", "date_string", "direction_agreement", "fetch_raw_day",
    "fetch_slice_publications", "load_raw_days", "normalise_id", "raw_day_path",
    "resolve_lineage", "slice_date_strings", "slice_publication_time", "store_root",
    "unwind_dealer_sign", "unwind_implied_original_sign",
]
