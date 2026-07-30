# ERIS Live Intraday Curve Snapshot Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-session Windows daemon that polls the live ERIS SOFR curve every minute during US trading hours and upserts each fresh curve handle as one indexed row in `arbs_curve_snapshots_v1`, plus a new `IRSwapsMDP(source="eris_live_intraday")` read path that serves any stored minute back as a reconstructed rateslib curve.

**Architecture:** Reuse the existing CurveStore/Supabase plumbing. Writes go through two new public methods on `SupabaseCurveSync` (single-row upsert + indexed as-of pulls) — never `CurveStore.write_day` (which re-pushes the whole-day BYTEA blob). The daemon builds the live curve once per poll via the existing `ERIS_EOD_LIVE-RL_BASIC-NOJUMPS` source, dedups on the vendor stamp, and persists one row. The read path mirrors CITIVELO's shape but reads `snapshots_v1` by indexed SQL rather than the whole-day blob.

**Tech Stack:** Python 3 (conda env `stir`), rateslib, SQLAlchemy + psycopg2 (direct Postgres to Supabase), QuantLib (calendar), pytz, PowerShell + Windows Task Scheduler.

**Spec:** `docs/superpowers/specs/2026-07-23-eris-live-intraday-curve-snapshot-design.md`

## Global Constraints

- **Env**: every command runs under `conda run -n stir` (e.g. `conda run -n stir python -m pytest ...`).
- **Supabase engine must stay ON**: keep `ARBS_SUPABASE_ENABLED=1`. Setting it to `0` makes `get_engine()` return `None` and blocks our own writes. Kill the fetcher's dead per-poll KV write instead via `LayeredCacheMixin.L2_WRITE = False` **before** any `Caching` import.
- **Never call `CurveStore.write_day` in the loop** — it always enqueues a whole-day BYTEA blob re-push (`curve_store.py:514-522`), ~88 MB/minute by session end at 18k nodes. Persist via `SupabaseCurveSync.upsert_snapshot_row` (one ~150 KB indexed row).
- **Fresh request dict every poll**: `IRSwapsMDP.get_data` pops `curve_name`/`timestamp` (`IRSwapsMDP.py:1467-1474`) — reusing a dict raises `KeyError`.
- **Dedup + freshness key** = `curve.meta()["timestamp"]` (tz-aware ET vendor valuation stamp). A 200 OK ≠ fresh; assert the stamp is recent and `reference_date()` is today before persisting.
- **Fixed identifiers** (use verbatim): storage asset `USD-SOFR-1D-ERISLIVE`; `reference_key="USD-SOFR-1D"`; `source_variant="ERIS_RL_BASIC_NOJUMPS"`; `interpolation="log_linear"`; poll source string `ERIS_EOD_LIVE-RL_BASIC-NOJUMPS`; read source `eris_live_intraday`.
- **Fast gate** (must stay green): `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`. DB round-trips are `@pytest.mark.db`; live ERIS fetch is `@pytest.mark.network`.
- **Test isolation on prod DB**: `db`-marked tests write only under a throwaway asset `USD-SOFR-1D-ERISLIVE-TEST` and delete those rows in teardown. Never touch other assets.

---

### Task 1: `upsert_snapshot_row` — single untagged row write

**Files:**
- Modify: `Caching/supabase_curve_sync.py` (add module fn `_snapshot_insert_params` + method `SupabaseCurveSync.upsert_snapshot_row`)
- Test: `tests/test_supabase_curve_snapshot_rows.py`

**Interfaces:**
- Consumes: existing `CURVE_SNAPSHOTS_TABLE`, `_to_python_date`, `self._engine` (SQLAlchemy `Engine`); `Caching.curve_store.CurveSnapshot`.
- Produces:
  - `_snapshot_insert_params(snap: CurveSnapshot, curve_name: str) -> dict` — the bound-param dict for the INSERT (pure; `tags=[]`).
  - `SupabaseCurveSync.upsert_snapshot_row(self, snap: CurveSnapshot, curve_name: str) -> bool` — returns `True` if written, `False` if `self._engine is None`.

- [ ] **Step 1: Write the failing test (pure param builder)**

Create `tests/test_supabase_curve_snapshot_rows.py`:

```python
import datetime
import pytest

from Caching.curve_store import CurveSnapshot
from Caching.supabase_curve_sync import _snapshot_insert_params


def _make_snap():
    utc = datetime.timezone.utc
    return CurveSnapshot(
        timestamp_utc=datetime.datetime(2026, 7, 23, 14, 31, tzinfo=utc),
        timestamp_local=datetime.datetime(2026, 7, 23, 9, 31, tzinfo=utc),
        trading_date=datetime.date(2026, 7, 23),
        session_minute=571,
        curve_name="USD-SOFR-1D-ERISLIVE",
        cfg_hash="",
        reference_key="USD-SOFR-1D",
        interpolation="log_linear",
        source_variant="ERIS_RL_BASIC_NOJUMPS",
        node_dates=[datetime.date(2026, 7, 24), datetime.date(2026, 7, 25)],
        discount_factors=[0.99989, 0.99978],
    )


def test_snapshot_insert_params_shape():
    params = _snapshot_insert_params(_make_snap(), "USD-SOFR-1D-ERISLIVE")
    assert params["curve_name"] == "USD-SOFR-1D-ERISLIVE"
    assert params["tags"] == []  # untagged is legal (TEXT[] DEFAULT '{}')
    assert params["reference_key"] == "USD-SOFR-1D"
    assert params["source_variant"] == "ERIS_RL_BASIC_NOJUMPS"
    assert params["session_minute"] == 571 and isinstance(params["session_minute"], int)
    assert params["node_dates"] == [datetime.date(2026, 7, 24), datetime.date(2026, 7, 25)]
    assert all(isinstance(d, datetime.date) for d in params["node_dates"])
    assert params["discount_factors"] == [0.99989, 0.99978]
    assert all(isinstance(v, float) for v in params["discount_factors"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_supabase_curve_snapshot_rows.py::test_snapshot_insert_params_shape -v`
Expected: FAIL — `ImportError: cannot import name '_snapshot_insert_params'`.

- [ ] **Step 3: Implement `_snapshot_insert_params` + `upsert_snapshot_row`**

In `Caching/supabase_curve_sync.py`, add the module-level helper directly after `_to_python_date` (after line 38):

```python
def _snapshot_insert_params(snap, curve_name: str) -> dict:
    """Bound-param dict for a single untagged arbs_curve_snapshots_v1 upsert."""
    return {
        "curve_name": curve_name,
        "timestamp_utc": snap.timestamp_utc,
        "trading_date": snap.trading_date,
        "session_minute": int(snap.session_minute),
        "tags": [],  # untagged; TEXT[] NOT NULL DEFAULT '{}' accepts an empty list
        "cfg_hash": str(snap.cfg_hash),
        "reference_key": str(snap.reference_key),
        "interpolation": str(snap.interpolation),
        "source_variant": str(snap.source_variant),
        "node_dates": [_to_python_date(d) for d in snap.node_dates],
        "discount_factors": [float(v) for v in snap.discount_factors],
    }
```

Add the method to `SupabaseCurveSync` (place it right after `_push_tagged_snapshots`, i.e. after line 251):

```python
    def upsert_snapshot_row(self, snap, curve_name: str) -> bool:
        """UPSERT one untagged curve snapshot into arbs_curve_snapshots_v1.

        Unlike push_day (whole-day BYTEA blob), this writes a single indexed
        row keyed (curve_name, timestamp_utc). Idempotent. Returns False when
        no engine is configured.
        """
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {CURVE_SNAPSHOTS_TABLE}
                        (curve_name, timestamp_utc, trading_date, session_minute,
                         tags, cfg_hash, reference_key, interpolation, source_variant,
                         node_dates, discount_factors)
                    VALUES
                        (:curve_name, :timestamp_utc, :trading_date, :session_minute,
                         :tags, :cfg_hash, :reference_key, :interpolation, :source_variant,
                         :node_dates, :discount_factors)
                    ON CONFLICT (curve_name, timestamp_utc) DO UPDATE SET
                        trading_date = EXCLUDED.trading_date,
                        session_minute = EXCLUDED.session_minute,
                        reference_key = EXCLUDED.reference_key,
                        interpolation = EXCLUDED.interpolation,
                        source_variant = EXCLUDED.source_variant,
                        node_dates = EXCLUDED.node_dates,
                        discount_factors = EXCLUDED.discount_factors
                """),
                _snapshot_insert_params(snap, curve_name),
            )
        return True
```

- [ ] **Step 4: Run the pure test to verify it passes**

Run: `conda run -n stir python -m pytest tests/test_supabase_curve_snapshot_rows.py::test_snapshot_insert_params_shape -v`
Expected: PASS.

- [ ] **Step 5: Add the DB round-trip test (marked `db`)**

Append to `tests/test_supabase_curve_snapshot_rows.py`:

```python
@pytest.mark.db
def test_upsert_snapshot_row_roundtrip():
    from sqlalchemy import text
    from Caching.supabase_curve_sync import SupabaseCurveSync

    TEST_ASSET = "USD-SOFR-1D-ERISLIVE-TEST"
    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")
    snap = _make_snap()
    try:
        assert sync.upsert_snapshot_row(snap, TEST_ASSET) is True
        # idempotent second write
        assert sync.upsert_snapshot_row(snap, TEST_ASSET) is True
        with sync._engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT node_dates, discount_factors, reference_key, tags
                    FROM arbs_curve_snapshots_v1
                    WHERE curve_name = :cn AND timestamp_utc = :ts
                """),
                {"cn": TEST_ASSET, "ts": snap.timestamp_utc},
            ).fetchone()
        assert row is not None
        assert [d for d in row.node_dates] == snap.node_dates
        assert [float(v) for v in row.discount_factors] == snap.discount_factors
        assert row.reference_key == "USD-SOFR-1D"
        assert list(row.tags) == []
    finally:
        with sync._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name = :cn"),
                {"cn": TEST_ASSET},
            )
```

- [ ] **Step 6: Run the DB test**

Run: `conda run -n stir python -m pytest tests/test_supabase_curve_snapshot_rows.py -v -m db`
Expected: PASS (or `skipped` if no engine). Confirms bit-exact `DATE[]`/`FLOAT8[]` round-trip and idempotency.

- [ ] **Step 7: Commit**

```bash
git add Caching/supabase_curve_sync.py tests/test_supabase_curve_snapshot_rows.py
git commit -m "feat(cache): single-row upsert into arbs_curve_snapshots_v1"
```

---

### Task 2: Indexed as-of read helpers

**Files:**
- Modify: `Caching/supabase_curve_sync.py` (add `_pick_nearest` + three pull methods)
- Test: `tests/test_supabase_curve_snapshot_rows.py`

**Interfaces:**
- Consumes: `self._engine`, `CURVE_SNAPSHOTS_TABLE`, `text`.
- Produces:
  - `_pick_nearest(target_utc: datetime.datetime, rows: list[dict]) -> Optional[dict]` — pure; returns the row with min `|timestamp_utc − target|`.
  - `SupabaseCurveSync.pull_snapshot_asof(self, curve_name: str, ts_utc: datetime.datetime, method: str = "asof") -> Optional[dict]`
  - `SupabaseCurveSync.pull_latest_snapshot(self, curve_name: str) -> Optional[dict]`
  - `SupabaseCurveSync.latest_snapshot_ts(self, curve_name: str, trading_date: datetime.date) -> Optional[datetime.datetime]`
  - Row dict keys: `curve_name, timestamp_utc, trading_date, session_minute, reference_key, interpolation, source_variant, node_dates, discount_factors`.

- [ ] **Step 1: Write the failing pure test**

Append to `tests/test_supabase_curve_snapshot_rows.py`:

```python
def test_pick_nearest():
    import datetime
    from Caching.supabase_curve_sync import _pick_nearest

    utc = datetime.timezone.utc
    rows = [
        {"timestamp_utc": datetime.datetime(2026, 7, 23, 14, 30, tzinfo=utc), "id": "a"},
        {"timestamp_utc": datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc), "id": "b"},
    ]
    target = datetime.datetime(2026, 7, 23, 14, 31, 10, tzinfo=utc)
    assert _pick_nearest(target, rows)["id"] == "a"
    assert _pick_nearest(target, [])  is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_supabase_curve_snapshot_rows.py::test_pick_nearest -v`
Expected: FAIL — `cannot import name '_pick_nearest'`.

- [ ] **Step 3: Implement `_pick_nearest` + pull methods**

Add module-level (after `_snapshot_insert_params`):

```python
def _pick_nearest(target_utc, rows: list) -> Optional[dict]:
    """Row with minimum absolute time distance to target_utc (None if empty)."""
    best = None
    best_delta = None
    for r in rows:
        delta = abs((r["timestamp_utc"] - target_utc).total_seconds())
        if best_delta is None or delta < best_delta:
            best, best_delta = r, delta
    return best
```

Add these three methods to `SupabaseCurveSync` (after `upsert_snapshot_row`). `_SNAPSHOT_COLS` keeps the SELECT list DRY:

```python
    _SNAPSHOT_COLS = (
        "curve_name, timestamp_utc, trading_date, session_minute, "
        "reference_key, interpolation, source_variant, node_dates, discount_factors"
    )

    def _snapshot_row_to_dict(self, row) -> dict:
        return {
            "curve_name": row.curve_name,
            "timestamp_utc": row.timestamp_utc,
            "trading_date": row.trading_date,
            "session_minute": row.session_minute,
            "reference_key": row.reference_key,
            "interpolation": row.interpolation,
            "source_variant": row.source_variant,
            "node_dates": list(row.node_dates),
            "discount_factors": [float(v) for v in row.discount_factors],
        }

    def pull_latest_snapshot(self, curve_name: str) -> Optional[dict]:
        """Most recent stored snapshot for curve_name (for timestamp='live')."""
        if self._engine is None:
            return None
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn
                    ORDER BY timestamp_utc DESC LIMIT 1
                """),
                {"cn": curve_name},
            ).fetchone()
        return self._snapshot_row_to_dict(row) if row is not None else None

    def pull_snapshot_asof(
        self, curve_name: str, ts_utc, method: str = "asof"
    ) -> Optional[dict]:
        """As-of / nearest / exact lookup keyed on (curve_name, timestamp_utc)."""
        if self._engine is None:
            return None
        with self._engine.begin() as conn:
            if method == "exact":
                row = conn.execute(
                    text(f"""
                        SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                        WHERE curve_name = :cn AND timestamp_utc = :ts LIMIT 1
                    """),
                    {"cn": curve_name, "ts": ts_utc},
                ).fetchone()
                return self._snapshot_row_to_dict(row) if row is not None else None

            before = conn.execute(
                text(f"""
                    SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn AND timestamp_utc <= :ts
                    ORDER BY timestamp_utc DESC LIMIT 1
                """),
                {"cn": curve_name, "ts": ts_utc},
            ).fetchone()
            if method == "asof":
                return self._snapshot_row_to_dict(before) if before is not None else None

            # nearest: also consider the first row strictly after ts
            after = conn.execute(
                text(f"""
                    SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn AND timestamp_utc > :ts
                    ORDER BY timestamp_utc ASC LIMIT 1
                """),
                {"cn": curve_name, "ts": ts_utc},
            ).fetchone()

        candidates = [self._snapshot_row_to_dict(r) for r in (before, after) if r is not None]
        return _pick_nearest(ts_utc, candidates)

    def latest_snapshot_ts(self, curve_name: str, trading_date):
        """High-water-mark timestamp_utc for (curve_name, trading_date); None if none."""
        if self._engine is None:
            return None
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT max(timestamp_utc) AS ts FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn AND trading_date = :td
                """),
                {"cn": curve_name, "td": trading_date},
            ).fetchone()
        return row.ts if row is not None else None
```

- [ ] **Step 4: Run the pure test to verify it passes**

Run: `conda run -n stir python -m pytest tests/test_supabase_curve_snapshot_rows.py::test_pick_nearest -v`
Expected: PASS.

- [ ] **Step 5: Add the DB round-trip read test (marked `db`)**

Append:

```python
@pytest.mark.db
def test_pull_snapshot_asof_roundtrip():
    import datetime
    from sqlalchemy import text
    from Caching.supabase_curve_sync import SupabaseCurveSync

    TEST_ASSET = "USD-SOFR-1D-ERISLIVE-TEST"
    utc = datetime.timezone.utc
    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")

    base = _make_snap()
    snaps = []
    for minute in (30, 31, 33):
        s = _make_snap()
        s.timestamp_utc = datetime.datetime(2026, 7, 23, 14, minute, tzinfo=utc)
        s.session_minute = 14 * 60 + minute
        snaps.append(s)
    try:
        for s in snaps:
            sync.upsert_snapshot_row(s, TEST_ASSET)

        # asof 14:32 -> the 14:31 row
        r = sync.pull_snapshot_asof(TEST_ASSET, datetime.datetime(2026, 7, 23, 14, 32, tzinfo=utc), "asof")
        assert r["timestamp_utc"] == datetime.datetime(2026, 7, 23, 14, 31, tzinfo=utc)
        # nearest 14:32:10 -> the 14:33 row is 50s away, 14:31 is 70s away -> 14:33
        r = sync.pull_snapshot_asof(TEST_ASSET, datetime.datetime(2026, 7, 23, 14, 32, 10, tzinfo=utc), "nearest")
        assert r["timestamp_utc"] == datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc)
        # exact miss
        assert sync.pull_snapshot_asof(TEST_ASSET, datetime.datetime(2026, 7, 23, 14, 32, tzinfo=utc), "exact") is None
        # latest
        assert sync.pull_latest_snapshot(TEST_ASSET)["timestamp_utc"] == datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc)
        # high-water-mark
        assert sync.latest_snapshot_ts(TEST_ASSET, datetime.date(2026, 7, 23)) == datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc)
    finally:
        with sync._engine.begin() as conn:
            conn.execute(text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name = :cn"), {"cn": TEST_ASSET})
```

- [ ] **Step 6: Run the DB test**

Run: `conda run -n stir python -m pytest tests/test_supabase_curve_snapshot_rows.py -v -m db`
Expected: PASS (or skipped).

- [ ] **Step 7: Commit**

```bash
git add Caching/supabase_curve_sync.py tests/test_supabase_curve_snapshot_rows.py
git commit -m "feat(cache): indexed as-of pull helpers for curve snapshot rows"
```

---

### Task 3: `IRSwapsMDP(source="eris_live_intraday")` read path

**Files:**
- Modify: `MDP/IRSwaps/IRSwapsMDP.py` (class attr near line 37; new method after `_load_citivelo_curve_store_point` ~line 217; dispatch branch before the `else` at line 2222)
- Test: `tests/test_eris_live_intraday_read.py`

**Interfaces:**
- Consumes: `SupabaseCurveSync.pull_snapshot_asof/pull_latest_snapshot` (Task 2), `CurveStore.reconstruct_curve` (`curve_store.py:815`), module-level `_fetch_fixings`, `self.force_refresh_fixings`, `RLIRSwapCurve`.
- Produces:
  - class attr `IRSwapsMDP._ERIS_LIVE_STORE_ASSET = "USD-SOFR-1D-ERISLIVE"`
  - `IRSwapsMDP._load_eris_live_intraday_point(self, *, requested_curve_name, timestamp, method="asof") -> Optional[_IRSwapGenericCurve]`
  - dispatch branch matching `source.upper() in ["ERIS_LIVE_INTRADAY", "ERIS_LIVE-INTRADAY"]`.

- [ ] **Step 1: Write the failing test (dispatch + no-EOD-validation)**

Create `tests/test_eris_live_intraday_read.py`:

```python
def test_eris_live_intraday_skips_eod_validation():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    mdp = IRSwapsMDP(source="eris_live_intraday")
    # source contains INTRADAY and not EOD -> strict EOD calendar validation off
    assert mdp._requires_strict_eod_calendar_validation() is False


def test_eris_live_intraday_store_asset_constant():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    assert IRSwapsMDP._ERIS_LIVE_STORE_ASSET == "USD-SOFR-1D-ERISLIVE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_eris_live_intraday_read.py -v`
Expected: FAIL — `AttributeError: ... _ERIS_LIVE_STORE_ASSET`.

- [ ] **Step 3: Add the class attribute**

In `MDP/IRSwaps/IRSwapsMDP.py`, directly after line 37 (`_CITIVELO_STORE_ASSET: str = "USD-SOFR-1D-CITIVELO"`), add:

```python
    _ERIS_LIVE_STORE_ASSET: str = "USD-SOFR-1D-ERISLIVE"
```

- [ ] **Step 4: Add `_load_eris_live_intraday_point`**

Insert immediately after `_load_citivelo_curve_store_point` (after line 217, before `_curve_store_source_family` at line 219):

```python
    def _load_eris_live_intraday_point(
        self,
        *,
        requested_curve_name: str,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        method: str = "asof",
    ) -> Optional["_IRSwapGenericCurve"]:
        """Serve a stored ERIS-live intraday curve from arbs_curve_snapshots_v1.

        Reads one row by indexed as-of SQL (no whole-day materialization),
        reconstructs the rl.Curve, and wraps it as an RLIRSwapCurve.
        Returns None when the store has no matching row.
        """
        import pytz

        from Caching.curve_store import CurveStore
        from Caching.supabase_curve_sync import SupabaseCurveSync
        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

        assert requested_curve_name == "USD-SOFR-1D", "ERIS live intraday is USD-SOFR-1D only"
        ASSET = self._ERIS_LIVE_STORE_ASSET
        NYC = pytz.timezone("America/New_York")
        sync = SupabaseCurveSync.from_defaults()

        if timestamp == "live":
            row = sync.pull_latest_snapshot(ASSET)
        else:
            ts = pd.Timestamp(timestamp)
            if ts.tzinfo is None:
                ts = ts.tz_localize(NYC)  # naive assumed ET
            row = sync.pull_snapshot_asof(ASSET, ts.tz_convert("UTC").to_pydatetime(), method)
        if row is None:
            return None

        rl_curve_handle = CurveStore.reconstruct_curve(row, cfg=None)

        snap_utc = pd.Timestamp(row["timestamp_utc"])
        if snap_utc.tzinfo is None:
            snap_utc = snap_utc.tz_localize("UTC")
        snap_et = snap_utc.tz_convert(NYC)
        ref = snap_et.date()
        ts_out = snap_et.to_pydatetime()

        sofr_fixings = _fetch_fixings(
            as_of_date=ref, curve_name=requested_curve_name, force_refresh=self.force_refresh_fixings
        ).sort_index()
        sofr_fixings = sofr_fixings[sofr_fixings.index.date < ref] * 100

        curve_id = f"{self.source.upper()}-{requested_curve_name}-{ts_out}"
        return RLIRSwapCurve(
            rl_curve_id=requested_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=sofr_fixings,
            meta_data={"timestamp": ts_out, "id": curve_id, "source": "eris_live_intraday"},
        )
```

- [ ] **Step 5: Add the dispatch branch**

In `_get_curve`, insert this `elif` immediately before the terminal `else:` at line 2222:

```python
        elif self.source.upper() in ["ERIS_LIVE_INTRADAY", "ERIS_LIVE-INTRADAY"]:
            assert curve_name == "USD-SOFR-1D", "SOFR!"
            method = kwargs.get("method", "asof")
            store_curve = self._load_eris_live_intraday_point(
                requested_curve_name=curve_name, timestamp=timestamp, method=method
            )
            if store_curve is not None:
                return store_curve
            raise RuntimeError(
                f"ERIS live intraday store (asset {self._ERIS_LIVE_STORE_ASSET}) has no data for "
                f"timestamp={timestamp!r}. Run the poller (scripts/eris_live_curve_service.py)."
            )
```

- [ ] **Step 6: Run the unit tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_eris_live_intraday_read.py -v`
Expected: PASS.

- [ ] **Step 7: Add a `db`-marked end-to-end read test**

Append to `tests/test_eris_live_intraday_read.py`:

```python
import datetime
import pytest


@pytest.mark.db
def test_eris_live_intraday_reads_seeded_row():
    from sqlalchemy import text
    from Caching.curve_store import CurveSnapshot
    from Caching.supabase_curve_sync import SupabaseCurveSync
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    ASSET = IRSwapsMDP._ERIS_LIVE_STORE_ASSET  # real asset; unique timestamp keeps it isolated
    utc = datetime.timezone.utc
    ts = datetime.datetime(2000, 1, 3, 20, 0, tzinfo=utc)  # far-past sentinel minute
    snap = CurveSnapshot(
        timestamp_utc=ts,
        timestamp_local=ts,
        trading_date=datetime.date(2000, 1, 3),
        session_minute=900,
        curve_name=ASSET,
        cfg_hash="",
        reference_key="USD-SOFR-1D",
        interpolation="log_linear",
        source_variant="ERIS_RL_BASIC_NOJUMPS",
        node_dates=[datetime.date(2000, 1, 4), datetime.date(2000, 1, 5), datetime.date(2001, 1, 4)],
        discount_factors=[0.9999, 0.9998, 0.95],
    )
    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")
    try:
        sync.upsert_snapshot_row(snap, ASSET)
        mdp = IRSwapsMDP(source="eris_live_intraday")
        curve = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": ts, "method": "asof"})
        handle = curve.handle()
        raw = handle.nodes._nodes if hasattr(handle.nodes, "_nodes") else dict(handle.nodes)
        assert len(raw) == 3
        assert curve.meta()["timestamp"].date() == datetime.date(2000, 1, 3)
    finally:
        with sync._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name = :cn AND timestamp_utc = :ts"),
                {"cn": ASSET, "ts": ts},
            )
```

- [ ] **Step 8: Run the db test**

Run: `conda run -n stir python -m pytest tests/test_eris_live_intraday_read.py -v -m db`
Expected: PASS (or skipped). Confirms round-trip reconstruct through the MDP read source.

- [ ] **Step 9: Commit**

```bash
git add MDP/IRSwaps/IRSwapsMDP.py tests/test_eris_live_intraday_read.py
git commit -m "feat(irswaps): eris_live_intraday MDP read source (indexed as-of)"
```

---

### Task 4: Daemon pure helpers (gating, freshness, snapshot build, lock)

**Files:**
- Create: `scripts/eris_live_curve_service.py` (constants + pure helpers only in this task)
- Test: `tests/test_eris_live_curve_service.py`

**Interfaces:**
- Consumes: `CurveSnapshot`, `RLIRSwapCurve`, QuantLib, pytz.
- Produces (module-level in `scripts/eris_live_curve_service.py`):
  - constants `ASSET_NAME`, `REFERENCE_KEY`, `SOURCE_VARIANT`, `SOURCE_STRING`, `SESSION_START_MIN`, `SESSION_END_MIN`
  - `is_business_day(d: datetime.date) -> bool`
  - `in_session(now_et: datetime.datetime, *, start_min: int, end_min: int) -> bool`
  - `should_persist(vendor_ts, now_et, ref_date, last_ts, *, max_lag_seconds: int = 90) -> tuple[bool, str]`
  - `build_snapshot(curve, vendor_ts) -> CurveSnapshot`
  - `SingleInstanceLock(name: str)` with `.acquire() -> bool` and `.release() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eris_live_curve_service.py`:

```python
import datetime
import pytz
import pytest

from scripts import eris_live_curve_service as svc

ET = pytz.timezone("America/New_York")
UTC = pytz.UTC


def _et(y, m, d, hh, mm):
    return ET.localize(datetime.datetime(y, m, d, hh, mm))


def test_in_session_boundaries():
    # window is [SESSION_START_MIN, SESSION_END_MIN)
    assert svc.in_session(_et(2026, 7, 23, 8, 0), start_min=8 * 60, end_min=17 * 60) is True
    assert svc.in_session(_et(2026, 7, 23, 7, 59), start_min=8 * 60, end_min=17 * 60) is False
    assert svc.in_session(_et(2026, 7, 23, 17, 0), start_min=8 * 60, end_min=17 * 60) is False


def test_is_business_day():
    assert svc.is_business_day(datetime.date(2026, 7, 23)) is True     # Thursday
    assert svc.is_business_day(datetime.date(2026, 7, 25)) is False    # Saturday
    assert svc.is_business_day(datetime.date(2026, 7, 4)) is False     # Independence Day (observed context)


def test_should_persist_dedup_and_freshness():
    now = _et(2026, 7, 23, 14, 31)
    fresh_ts = _et(2026, 7, 23, 14, 30, 30)  # 30s old
    ok, _ = svc.should_persist(fresh_ts, now, datetime.date(2026, 7, 23), last_ts=None)
    assert ok is True
    # unchanged stamp -> skip
    ok, reason = svc.should_persist(fresh_ts, now, datetime.date(2026, 7, 23), last_ts=fresh_ts)
    assert ok is False and "unchanged" in reason
    # stale stamp (10 min old) -> skip
    stale = _et(2026, 7, 23, 14, 21)
    ok, reason = svc.should_persist(stale, now, datetime.date(2026, 7, 23), last_ts=None)
    assert ok is False and "stale" in reason
    # naive stamp -> skip
    ok, reason = svc.should_persist(datetime.datetime(2026, 7, 23, 14, 30), now, datetime.date(2026, 7, 23), last_ts=None)
    assert ok is False and "tz" in reason
    # ref_date not today -> skip
    ok, reason = svc.should_persist(fresh_ts, now, datetime.date(2026, 7, 22), last_ts=None)
    assert ok is False and "reference_date" in reason


def test_build_snapshot_from_rl_curve():
    import rateslib as rl
    from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

    handle = rl.Curve(
        nodes={rl.dt(2026, 7, 24): 1.0, rl.dt(2026, 7, 25): 0.99989, rl.dt(2027, 7, 24): 0.95},
        id="USD-SOFR-1D", convention="act360", calendar="nyc", interpolation="log_linear",
    )
    vendor_ts = _et(2026, 7, 23, 14, 31)
    curve = RLIRSwapCurve(rl_curve_id="USD-SOFR-1D", rl_curve_handle=handle,
                          fixings=None, meta_data={"timestamp": vendor_ts})
    snap = svc.build_snapshot(curve, vendor_ts)
    assert snap.curve_name == "USD-SOFR-1D-ERISLIVE"
    assert snap.reference_key == "USD-SOFR-1D"
    assert snap.source_variant == "ERIS_RL_BASIC_NOJUMPS"
    assert snap.trading_date == datetime.date(2026, 7, 23)      # ET calendar date
    assert snap.session_minute == 14 * 60 + 31                  # ET minute-of-day
    assert snap.timestamp_utc.tzinfo is not None
    assert snap.node_dates == [datetime.date(2026, 7, 24), datetime.date(2026, 7, 25), datetime.date(2027, 7, 24)]
    assert len(snap.discount_factors) == 3


def test_single_instance_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.tempfile, "gettempdir", lambda: str(tmp_path))
    a = svc.SingleInstanceLock("eris-test")
    b = svc.SingleInstanceLock("eris-test")
    assert a.acquire() is True
    assert b.acquire() is False     # already held
    a.release()
    assert b.acquire() is True      # reclaimed after release
    b.release()
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_eris_live_curve_service.py -v`
Expected: FAIL — `ModuleNotFoundError: scripts.eris_live_curve_service` (or missing attrs).

- [ ] **Step 3: Create the script with env guard, constants, and pure helpers**

Create `scripts/eris_live_curve_service.py`:

```python
"""Poll the live ERIS SOFR curve every minute and persist each fresh curve
handle as one indexed row in arbs_curve_snapshots_v1 (asset USD-SOFR-1D-ERISLIVE).

Per-session daemon: starts in the morning, loops with a drift-free 60s cadence
during the US session, exits after --stop-at. Read back via
IRSwapsMDP(source="eris_live_intraday").

Usage:
    conda run -n stir python scripts/eris_live_curve_service.py run
    conda run -n stir python scripts/eris_live_curve_service.py run --once
"""
from __future__ import annotations

# ── MUST precede any Caching / fetcher import ──
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "1")  # engine ON for our writes

from Caching.layered_cache_mixin import LayeredCacheMixin

LayeredCacheMixin.L2_WRITE = False  # kill the fetcher's dead ~820KB/poll KV write

import argparse
import contextlib
import datetime
import logging
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Tuple

import pytz
import QuantLib as ql

from Caching.curve_store import CurveSnapshot

logger = logging.getLogger("eris_live_curve_service")

ASSET_NAME = "USD-SOFR-1D-ERISLIVE"
REFERENCE_KEY = "USD-SOFR-1D"
SOURCE_VARIANT = "ERIS_RL_BASIC_NOJUMPS"
SOURCE_STRING = "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS"
CURVE_NAME = "USD-SOFR-1D"
SESSION_START_MIN = 8 * 60   # 08:00 ET
SESSION_END_MIN = 17 * 60    # 17:00 ET

_ET = pytz.timezone("America/New_York")
_UTC = pytz.UTC
_CHI = pytz.timezone("America/Chicago")
_QL_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def is_business_day(d: datetime.date) -> bool:
    return _QL_CAL.isBusinessDay(ql.Date(d.day, d.month, d.year))


def in_session(now_et: datetime.datetime, *, start_min: int, end_min: int) -> bool:
    m = now_et.hour * 60 + now_et.minute
    return start_min <= m < end_min


def should_persist(
    vendor_ts, now_et, ref_date, last_ts, *, max_lag_seconds: int = 90
) -> Tuple[bool, str]:
    """Gate a poll result before writing. Returns (persist?, reason)."""
    if vendor_ts is None or getattr(vendor_ts, "tzinfo", None) is None:
        return False, "tz: vendor timestamp missing or naive"
    if last_ts is not None and vendor_ts == last_ts:
        return False, "unchanged: vendor timestamp same as last poll"
    lag = (now_et - vendor_ts.astimezone(now_et.tzinfo)).total_seconds()
    if lag > max_lag_seconds:
        return False, f"stale: vendor timestamp {lag:.0f}s old (> {max_lag_seconds}s)"
    if ref_date != now_et.date():
        return False, f"reference_date {ref_date} != today {now_et.date()}"
    return True, "ok"


def build_snapshot(curve, vendor_ts) -> CurveSnapshot:
    """Build a CurveSnapshot from a live RLIRSwapCurve + its vendor stamp."""
    from Caching.curve_store import _to_date

    handle = curve.handle()
    raw_nodes = handle.nodes._nodes if hasattr(handle.nodes, "_nodes") else dict(handle.nodes)
    nd_sorted = sorted(raw_nodes.keys())
    node_dates = [_to_date(d) for d in nd_sorted]
    discount_factors = [float(raw_nodes[d]) for d in nd_sorted]

    ts = vendor_ts
    if ts.tzinfo is None:
        ts = _ET.localize(ts)
    ts_utc = ts.astimezone(_UTC).replace(microsecond=0)
    ts_et = ts_utc.astimezone(_ET)
    return CurveSnapshot(
        timestamp_utc=ts_utc,
        timestamp_local=ts_utc.astimezone(_CHI),
        trading_date=ts_et.date(),
        session_minute=int(ts_et.hour * 60 + ts_et.minute),
        curve_name=ASSET_NAME,
        cfg_hash="",
        reference_key=REFERENCE_KEY,
        interpolation="log_linear",
        source_variant=SOURCE_VARIANT,
        node_dates=node_dates,
        discount_factors=discount_factors,
    )


class SingleInstanceLock:
    """O_CREAT|O_EXCL single-instance lock with stale-PID reclamation."""

    def __init__(self, name: str):
        lock_dir = Path(tempfile.gettempdir()) / "arbs_eris_live_curve"
        lock_dir.mkdir(parents=True, exist_ok=True)
        self._path = lock_dir / f"{name}.lock"
        self._fd = None

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def acquire(self) -> bool:
        try:
            self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # stale-PID reclaim
            try:
                pid = int(self._path.read_text().strip() or "-1")
            except (OSError, ValueError):
                pid = -1
            if pid > 0 and self._pid_alive(pid):
                return False
            with contextlib.suppress(OSError):
                self._path.unlink()
            try:
                self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        os.write(self._fd, str(os.getpid()).encode("utf-8"))
        return True

    def release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()
```

Also create `tests/__init__.py` is **not** needed (pytest rootdir handles `from scripts import ...` via the repo root on `sys.path`; if the import fails, add an empty `scripts/__init__.py` — check first with `conda run -n stir python -c "import scripts.eris_live_curve_service"`).

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_eris_live_curve_service.py -v`
Expected: PASS. (If `test_is_business_day` disagrees on the 2026-07-04 observed holiday, adjust the asserted date to a known NYSE/GovBond holiday such as `datetime.date(2026, 1, 1)` — New Year's Day — and keep the weekend + business-day asserts.)

- [ ] **Step 5: Commit**

```bash
git add scripts/eris_live_curve_service.py tests/test_eris_live_curve_service.py
git commit -m "feat(eris): daemon pure helpers (session gate, freshness, snapshot, lock)"
```

---

### Task 5: Daemon loop + CLI

**Files:**
- Modify: `scripts/eris_live_curve_service.py` (add poll + loop + `main`)
- Test: `tests/test_eris_live_curve_service.py`

**Interfaces:**
- Consumes: Task 4 helpers, `IRSwapsMDP`, `SupabaseCurveSync`.
- Produces:
  - `poll_once(mdp) -> object` — returns the live `RLIRSwapCurve` (raises on fetch/validation failure).
  - `run_service(*, poll_fn, now_fn, writer_fn, sleep_fn=time.sleep, stop_fn, poll_seconds=60, start_min=SESSION_START_MIN, end_min=SESSION_END_MIN) -> dict` — injectable loop; returns a counters dict `{"wrote","skipped","errors","polls"}`.
  - `main(argv=None) -> int` — CLI (`run`, flags `--once`, `--poll-seconds`, `--stop-at`, `--session-start`, `--session-end`, `--log-dir`).

- [ ] **Step 1: Write the failing loop test (fully injected, no network/db)**

Append to `tests/test_eris_live_curve_service.py`:

```python
def test_run_service_dedups_and_gates(monkeypatch):
    import datetime
    calls = {"writes": []}

    ticks = [
        _et(2026, 7, 23, 8, 0),   # in session
        _et(2026, 7, 23, 8, 1),   # in session, same vendor stamp -> skip
        _et(2026, 7, 23, 8, 2),   # in session, new stamp -> write
        _et(2026, 7, 23, 17, 30), # past stop -> loop ends
    ]
    stamps = [
        _et(2026, 7, 23, 7, 59, 40),
        _et(2026, 7, 23, 7, 59, 40),  # unchanged
        _et(2026, 7, 23, 8, 1, 40),   # new
    ]
    now_iter = iter(ticks)
    stamp_iter = iter(stamps)

    class FakeCurve:
        def __init__(self, ts):
            self._ts = ts
        def meta(self):
            return {"timestamp": self._ts}
        def reference_date(self):
            return None

    def now_fn():
        return next(now_iter)

    def poll_fn():
        return FakeCurve(next(stamp_iter))

    def writer_fn(curve, vendor_ts):
        calls["writes"].append(vendor_ts)

    def stop_fn(now_et):
        return now_et.hour >= 17  # stop after session

    # bypass the ref_date==today freshness leg for this synthetic clock:
    monkeypatch.setattr(svc, "should_persist",
                        lambda vt, now, ref, last, **k: (last != vt and (now - vt.astimezone(now.tzinfo)).total_seconds() <= 90, "unchanged" if last == vt else "ok"))

    counters = svc.run_service(poll_fn=poll_fn, now_fn=now_fn, writer_fn=writer_fn,
                               sleep_fn=lambda s: None, stop_fn=stop_fn, poll_seconds=0)
    assert len(calls["writes"]) == 1
    assert counters["wrote"] == 1 and counters["skipped"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_eris_live_curve_service.py::test_run_service_dedups_and_gates -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'run_service'`.

- [ ] **Step 3: Implement `poll_once`, `run_service`, `main`**

Append to `scripts/eris_live_curve_service.py`:

```python
def _build_mdp():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    return IRSwapsMDP(source=SOURCE_STRING, error_verbose=True)


def poll_once(mdp):
    """One live poll. Returns the RLIRSwapCurve; raises on failure."""
    return mdp.get_pricer({"curve_name": CURVE_NAME, "timestamp": "live"})  # fresh dict each call


def _default_writer(curve, vendor_ts):
    from Caching.supabase_curve_sync import SupabaseCurveSync
    snap = build_snapshot(curve, vendor_ts)
    SupabaseCurveSync.from_defaults().upsert_snapshot_row(snap, ASSET_NAME)


def run_service(
    *,
    poll_fn,
    now_fn,
    writer_fn,
    sleep_fn=time.sleep,
    stop_fn,
    poll_seconds: int = 60,
    start_min: int = SESSION_START_MIN,
    end_min: int = SESSION_END_MIN,
) -> dict:
    counters = {"wrote": 0, "skipped": 0, "errors": 0, "polls": 0}
    last_ts = None
    while True:
        now_et = now_fn()
        if stop_fn(now_et):
            break
        t0 = time.monotonic()
        if is_business_day(now_et.date()) and in_session(now_et, start_min=start_min, end_min=end_min):
            counters["polls"] += 1
            try:
                curve = poll_fn()
                vendor_ts = curve.meta().get("timestamp")
                ref_date = curve.reference_date().date() if curve.reference_date() is not None else now_et.date()
                ok, reason = should_persist(vendor_ts, now_et, ref_date, last_ts)
                if ok:
                    writer_fn(curve, vendor_ts)
                    last_ts = vendor_ts
                    counters["wrote"] += 1
                    logger.info("wrote snapshot ts=%s nodes<-curve", vendor_ts)
                else:
                    counters["skipped"] += 1
                    logger.info("skip: %s", reason)
            except ValueError as exc:  # non-business-day guard OR empty-fetch unpack
                counters["skipped"] += 1
                logger.warning("skip poll (ValueError): %s", exc)
            except Exception:  # network/fixings/parse — isolate the cycle
                counters["errors"] += 1
                logger.exception("poll failed; continuing")
        sleep_fn(max(0.0, poll_seconds - (time.monotonic() - t0)))
    return counters


def _configure_logging(log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(Path(log_dir) / "eris_live_curve_service.log",
                                  maxBytes=10 * 1024 * 1024, backupCount=7)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger("eris_live_curve_service").addHandler(handler)
    logging.getLogger("eris_live_curve_service").addHandler(logging.StreamHandler())
    logging.getLogger("eris_live_curve_service").setLevel(logging.INFO)


def _parse_hm(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ERIS live intraday curve snapshot service")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--once", action="store_true", help="single poll then exit")
    run.add_argument("--poll-seconds", type=int, default=60)
    run.add_argument("--session-start", default="08:00")
    run.add_argument("--session-end", default="17:00")
    run.add_argument("--stop-at", default="17:15")
    run.add_argument("--log-dir", default=str(Path("logs") / "eris_live_curve_service"))
    args = parser.parse_args(argv)

    _configure_logging(args.log_dir)
    lock = SingleInstanceLock("eris-live-curve")
    if not lock.acquire():
        logger.error("another instance holds the lock; exiting")
        return 3
    try:
        mdp = _build_mdp()
        if args.once:
            now_et = datetime.datetime.now(_ET)
            if not (is_business_day(now_et.date()) and in_session(
                now_et, start_min=_parse_hm(args.session_start), end_min=_parse_hm(args.session_end))):
                logger.warning("--once outside session/holiday; polling anyway for smoke")
            curve = poll_once(mdp)
            vendor_ts = curve.meta().get("timestamp")
            _default_writer(curve, vendor_ts)
            logger.info("--once wrote snapshot ts=%s", vendor_ts)
            return 0

        stop_min = _parse_hm(args.stop_at)

        def stop_fn(now_et):
            return (now_et.hour * 60 + now_et.minute) >= stop_min

        counters = run_service(
            poll_fn=lambda: poll_once(mdp),
            now_fn=lambda: datetime.datetime.now(_ET),
            writer_fn=_default_writer,
            stop_fn=stop_fn,
            poll_seconds=args.poll_seconds,
            start_min=_parse_hm(args.session_start),
            end_min=_parse_hm(args.session_end),
        )
        logger.info("session done: %s", counters)
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the loop test to verify it passes**

Run: `conda run -n stir python -m pytest tests/test_eris_live_curve_service.py::test_run_service_dedups_and_gates -v`
Expected: PASS.

- [ ] **Step 5: Run the whole fast gate for the new files**

Run: `conda run -n stir python -m pytest tests/test_eris_live_curve_service.py tests/test_eris_live_intraday_read.py tests/test_supabase_curve_snapshot_rows.py -v -m "not slow and not network and not db"`
Expected: PASS (db/network tests deselected).

- [ ] **Step 6: Live `--once` smoke (marked separately — run manually on a business day)**

Run (only on a US business day, during market hours):
`conda run -n stir python scripts/eris_live_curve_service.py run --once`
Expected: logs `--once wrote snapshot ts=<recent ET stamp>` and exits 0. Then verify one row landed:
`conda run -n stir python -c "from Caching.supabase_curve_sync import SupabaseCurveSync; s=SupabaseCurveSync.from_defaults(); import datetime; print(s.latest_snapshot_ts('USD-SOFR-1D-ERISLIVE', datetime.date.today()))"`
Expected: a recent timestamp printed. If outside market hours, expect a `ValueError`/no-data — that is correct behavior, note it and move on.

- [ ] **Step 7: Commit**

```bash
git add scripts/eris_live_curve_service.py tests/test_eris_live_curve_service.py
git commit -m "feat(eris): live curve snapshot daemon loop + CLI"
```

---

### Task 6: Windows Task Scheduler integration

**Files:**
- Create: `scripts/eris_live_curve_service.ps1` (conda wrapper)
- Create: `scripts/register_eris_live_curve_task.ps1` (Task Scheduler registration)

**Interfaces:**
- Consumes: `scripts/eris_live_curve_service.py`.
- Produces: two committed PowerShell scripts. No pytest coverage (shell); verified by parse + `-WhatIf`.

- [ ] **Step 1: Create the conda wrapper**

Create `scripts/eris_live_curve_service.ps1`:

```powershell
$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\chris\clee\ARBS'
Set-Location $repo

& 'C:\Users\chris\anaconda3\shell\condabin\conda-hook.ps1'
conda activate stir

$env:PYTHONUNBUFFERED = '1'
$env:ARBS_SUPABASE_ENABLED = '1'

$logDir = Join-Path $repo 'logs\eris_live_curve_service'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir ('wrapper_{0}.log' -f (Get-Date -Format 'yyyyMMdd'))

& python scripts/eris_live_curve_service.py run *> $outLog
exit $LASTEXITCODE
```

- [ ] **Step 2: Verify the wrapper parses**

Run: `powershell -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile('C:\Users\chris\clee\ARBS\scripts\eris_live_curve_service.ps1',[ref]$null,[ref]$errs); if($errs){$errs}else{'OK'}"`
Expected: `OK` (no parse errors).

- [ ] **Step 3: Create the registration script**

Create `scripts/register_eris_live_curve_task.ps1`:

```powershell
param(
    [string]$TaskName = 'ARBS-ErisLiveCurve-Intraday',
    [switch]$WhatIf
)

$repo = 'C:\Users\chris\clee\ARBS'
$wrapper = Join-Path $repo 'scripts\eris_live_curve_service.ps1'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $wrapper) `
    -WorkingDirectory $repo

# Two triggers: daily just before the session, and at startup (reboot recovery).
$daily   = New-ScheduledTaskTrigger -Daily -At 6:55am
$startup = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($WhatIf) {
    Write-Host "WhatIf: would register '$TaskName' -> $wrapper (Daily 06:55 + AtStartup)"
    return
}

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger @($daily, $startup) -Settings $settings `
    -Description 'Polls live ERIS SOFR curve every minute during the US session and persists snapshots to Supabase.' `
    -Force
Write-Host "Registered scheduled task '$TaskName'."
```

- [ ] **Step 4: Verify the registration script parses and dry-runs**

Run:
`powershell -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile('C:\Users\chris\clee\ARBS\scripts\register_eris_live_curve_task.ps1',[ref]$null,[ref]$errs); if($errs){$errs}else{'OK'}"`
Then: `powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\chris\clee\ARBS\scripts\register_eris_live_curve_task.ps1" -WhatIf`
Expected: `OK`, then the `WhatIf:` line. **Do not** run without `-WhatIf` in this task — actual registration is a manual deploy step (Step 6).

- [ ] **Step 5: Commit**

```bash
git add scripts/eris_live_curve_service.ps1 scripts/register_eris_live_curve_task.ps1
git commit -m "feat(eris): Task Scheduler wrapper + registration script"
```

- [ ] **Step 6: (Manual deploy — not part of TDD) register the task**

When ready to deploy on the host, run in an elevated PowerShell:
`powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\chris\clee\ARBS\scripts\register_eris_live_curve_task.ps1"`
Verify: `schtasks /query /tn ARBS-ErisLiveCurve-Intraday /v /fo LIST`

---

### Task 7: Final verification & wrap-up

**Files:** none new (verification + docs pointer).

- [ ] **Step 1: Full fast gate green**

Run: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
Expected: PASS (no regressions introduced by the new modules/imports).

- [ ] **Step 2: DB integration tests green (needs DATABASE_URL / Supabase)**

Run: `conda run -n stir python -m pytest tests/test_supabase_curve_snapshot_rows.py tests/test_eris_live_intraday_read.py -v -m db`
Expected: PASS (or skipped if no engine). Confirm all `USD-SOFR-1D-ERISLIVE-TEST` rows are cleaned up:
`conda run -n stir python -c "from Caching.supabase_curve_sync import SupabaseCurveSync; from sqlalchemy import text; s=SupabaseCurveSync.from_defaults(); c=s._engine.begin().__enter__().execute(text(\"SELECT count(*) FROM arbs_curve_snapshots_v1 WHERE curve_name LIKE 'USD-SOFR-1D-ERISLIVE-TEST%'\")).scalar(); print('leftover test rows:', c)"`
Expected: `leftover test rows: 0`.

- [ ] **Step 3: Session smoke (business-day, market hours) — optional live check**

Run for ~3 minutes: `conda run -n stir python scripts/eris_live_curve_service.py run --poll-seconds 60 --stop-at <now+3min>`
Expected: log shows ~2-3 `wrote snapshot` lines with advancing vendor stamps and no tracebacks; row count for today increments accordingly.

- [ ] **Step 4: Update the spec Status and commit**

Edit `docs/superpowers/specs/2026-07-23-eris-live-intraday-curve-snapshot-design.md` header: change `**Status**: Draft for review` → `**Status**: Implemented`.

```bash
git add docs/superpowers/specs/2026-07-23-eris-live-intraday-curve-snapshot-design.md
git commit -m "docs(spec): mark ERIS live intraday curve snapshot implemented"
```

- [ ] **Step 5: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to decide merge/PR/cleanup.

---

## Self-Review

**Spec coverage:**
- §4.2 write path (env toggles, snapshot construction, upsert helper) → Tasks 1, 4, 5. ✓
- §4.3 per-minute rows not blob → enforced by Global Constraints + Task 1 (no `write_day`). ✓
- §4.4 read path (dispatch branch, pull helpers, reconstruct, wrap) → Tasks 2, 3. ✓
- §4.5 daemon (session/holiday gate, freshness dedup, failure isolation, lock, logging) → Tasks 4, 5. ✓
- §4.6 Task Scheduler (.ps1 wrapper + registration) → Task 6. ✓
- §5 testing (fast/db/network split) → Tasks 1-5 tests + Task 7. ✓
- §7 risks (R1 per-session bound, R4 stale lock) → per-session `--stop-at` (Task 5), stale-PID reclaim (Task 4). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output. One conditional adjustment noted inline (Task 4 Step 4 holiday-date fallback) with the exact alternative given — not a placeholder.

**Type consistency:** `upsert_snapshot_row(snap, curve_name) -> bool`, `pull_snapshot_asof(curve_name, ts_utc, method="asof") -> dict|None`, `_load_eris_live_intraday_point(*, requested_curve_name, timestamp, method="asof")`, `build_snapshot(curve, vendor_ts) -> CurveSnapshot`, `run_service(*, poll_fn, now_fn, writer_fn, sleep_fn, stop_fn, poll_seconds, start_min, end_min) -> dict`, `should_persist(vendor_ts, now_et, ref_date, last_ts, *, max_lag_seconds=90) -> (bool,str)` — names/signatures identical wherever referenced across tasks. Constants (`ASSET_NAME`, `REFERENCE_KEY`, `SOURCE_VARIANT`, `_ERIS_LIVE_STORE_ASSET`) match the spec's fixed identifiers.
