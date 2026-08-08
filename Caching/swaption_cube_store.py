r"""A dated store for swaption vol cubes, built the way :mod:`Caching.curve_store` is.

Same shape, same reasons: content-addressed parquet under
``<base>/vol_raw/asset=<NAME>/date=<YYYY-MM-DD>/<sha256>.parquet``, an atomic
temp-then-rename write, a miss that returns ``None`` rather than raising, and a
process-wide ``default()`` singleton.

What is stored, and why it is the DATA and not the pricer
---------------------------------------------------------
:class:`CurveStore` stores ``node_dates`` + ``discount_factors`` and rebuilds an
``rl.Curve`` from them; it does not pickle the curve. This does the same thing one
level up: it stores the **quoted volatility grid** -
``(expiry, tenor, offset_bp) -> vol in bp`` plus the units and provenance that
make it interpretable - and rebuilds a :class:`SwaptionCubeData` from it.

That is a deliberate choice over serialising a built
``rateslib.IRSplineCube``. rateslib 2.7's serialization page marks the feature
"experimental, and in development", lists ``PPSplineF64``/``Cal``/``FXRates`` and
friends, and says nothing at all about ``IRSplineCube``, ``IRSabrCube`` or even
``Curve``. A cache whose contents can only be read back by one patch release of
one library is not a cache. The quoted grid, by contrast, is just numbers with
units, and the object it rebuilds is chosen at read time - so the same stored day
serves the rateslib-native backend, the hand-built one and QuantLib.

It also means the store is **curve-free**. A vol cube and the curve its strikes
are measured from are different artefacts with different vintages; binding them
at write time would make every stored day a hostage to whichever curve happened
to be warm. :func:`reconstruct_cube` hands back the data, and the caller supplies
the curve.

Layout
------
``vol_raw/asset=<NAME>/date=<ISO>/<sha256>.parquet``
    one long row per node: ``expiry, tenor, offset_bp, vol_bp``, plus the
    constant columns (``as_of, currency, measure, skew_measure, served_unit,
    vol_unit, strike_unit, source, citi_index``) that
    :class:`SwaptionCubeData` needs to be rebuilt without a sidecar. They are
    dictionary-encoded by parquet, so the repetition is close to free and the
    file stays self-describing - which is the property that matters when someone
    finds one of these in three years.

The Supabase L2 tier is OPT-IN
------------------------------
:class:`CurveStore` and :class:`USTFutureStore` push their partitions to Supabase
by default. This one does not, and the asymmetry is the design rather than an
oversight: ``Caching.supabase_engine.SUPABASE_ENABLED`` defaults to **True** and
``get_database_url()`` falls back to hard-coded PRODUCTION pooler credentials, so
an always-on push would have a fresh checkout writing to the live database the
first time anybody built a cube - and ``scripts/citivelo_swaption_vol_warm.py``,
unlike the four Citi curve scripts, does not set ``ARBS_SUPABASE_ENABLED=0``.
``CurveStore``'s default is grandfathered - flipping it would silently stop
feeding production - but a new tier has nothing depending on the unsafe default,
so it gets the safe one.

Two gates, both of which must be open:

``ARBS_SWAPTION_CUBE_L2``
    ``off`` (default) / ``read`` / ``read_write``, parsed by
    :mod:`Caching.l2_policy` - strictly, so a typo means *off*, and at call time,
    so a ``--push-l2`` flag can turn it on after import (which
    ``citivelo_excel_warm.py --push-l2`` could never do).
``push_l2`` / ``l2`` arguments
    an explicit ``True``/``False`` on the store or the call overrides the
    environment in either direction.

Mechanics live in :mod:`Caching.supabase_blob_blocks`; the cube-specific part is
:mod:`Caching.supabase_swaption_cube_sync`. The one-partition-one-cube property
survives the round trip: a push whose remote sha differs raises rather than
upserting, exactly as :meth:`write_day` raises locally.

There is still no row-level tier, and that is still right: a vol surface has no
as-of-one-node reading the way a curve does, so rows would buy nothing.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

__all__ = [
    "SwaptionCubeStore",
    "asset_for",
    "CUBE_SCHEMA_VERSION",
]

logger = logging.getLogger(__name__)

DEFAULT_COMPRESSION = "zstd"

#: Bumped when the stored columns change meaning. Written into every file so a
#: reader can refuse a vintage it does not understand instead of guessing.
CUBE_SCHEMA_VERSION = 1

#: The columns that vary per node. Everything else is constant for a day.
_NODE_COLUMNS = ("expiry", "tenor", "offset_bp", "vol_bp")

#: Constant-per-day columns, all of them needed to rebuild a SwaptionCubeData.
_META_COLUMNS = (
    "as_of",
    "currency",
    "measure",
    "skew_measure",
    "served_unit",
    "vol_unit",
    "strike_unit",
    "source",
    "citi_index",
    "schema_version",
)


def _sanitize(name: str) -> str:
    """Filesystem-safe asset name.

    Prefers :func:`Caching.timeseries_cache._sanitize_symbol`, which is what
    :class:`USTFutureStore` uses: it caps at 48 characters and appends a hash
    beyond that, so a long asset name cannot push a Windows path past the limit.
    Falls back to :mod:`Caching.curve_store`'s plain rule if that helper moves.
    """
    try:
        from Caching.timeseries_cache import _sanitize_symbol

        return _sanitize_symbol(name)
    except Exception:  # noqa: BLE001
        return re.sub(r"[^\w.\-]", "_", name)


def asset_for(currency: str, *, provider: str = "CITIVELOEXCEL") -> str:
    """The store asset name for one currency's swaption vol.

    ``USD`` -> ``USD-SWAPTIONVOL-CITIVELOEXCEL``. Deliberately carries the
    provider, exactly as the curve assets do (``USD-SOFR-1D-CITIVELOEXCEL`` vs
    ``-CITIVELO`` vs ``-CITIVELOSTREAM``): this repo has a recorded incident where
    two variants shared one key and which answer you got depended on cache state.
    """
    return f"{str(currency).upper()}-SWAPTIONVOL-{str(provider).upper()}"


def _atomic_content_write(part_dir: Path, data: bytes, *, overwrite: bool = False) -> Optional[dict]:
    """Content-addressed atomic write. Returns metadata, or None if skipped.

    Lifted from :mod:`Caching.curve_store` on purpose - a second store that
    writes partitions a subtly different way is a second set of failure modes.
    """
    part_dir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    final_path = part_dir / f"{sha}.parquet"

    if final_path.exists() and not overwrite:
        return None  # identical content already there

    if overwrite:
        for old in part_dir.glob("*.parquet"):
            old.unlink()

    with tempfile.NamedTemporaryFile(dir=str(part_dir), delete=False, suffix=".tmp") as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)

    os.replace(tmp_path, final_path)
    return {"path": str(final_path), "size": len(data), "sha256": sha}


def _write_parquet_bytes(table: pa.Table, compression: str) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression=compression)
    return sink.getvalue().to_pybytes()


def _to_date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return pd.Timestamp(value).date()


def _coerce_l2(value: Any) -> Optional[Any]:
    """``None`` / bool / :class:`L2Mode` -> ``None`` or an ``L2Mode``.

    ``None`` is not "off": it is "no override, ask the environment". A bool is
    accepted because that is what a ``--push-l2`` flag hands you.
    """
    from Caching.l2_policy import L2Mode

    if value is None:
        return None
    if isinstance(value, L2Mode):
        return value
    if isinstance(value, bool):
        return L2Mode.READ_WRITE if value else L2Mode.OFF
    from Caching.l2_policy import parse_l2_mode

    return parse_l2_mode(str(value), var_name="l2")


class SwaptionCubeStore:
    """Dated swaption vol cubes on disk. See the module docstring."""

    _default_instance: Optional["SwaptionCubeStore"] = None
    _default_lock = threading.Lock()

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        compression: str = DEFAULT_COMPRESSION,
        l2: Optional[Any] = None,
    ) -> None:
        """``l2`` overrides ``ARBS_SWAPTION_CUBE_L2`` for this instance.

        ``None`` (the default) means "ask the environment at call time".
        ``False`` pins the store local-only whatever the environment says;
        ``True`` is read-write; an :class:`~Caching.l2_policy.L2Mode` is used as
        given. Pinning matters for a process pool: a worker that pushes its own
        partitions multiplies the 9-connection-per-process engine by the worker
        count, which is how a dev backfill exhausts the pooler.
        """
        if base_dir is None:
            base_dir = self._default_base_dir()
        self._base_dir = Path(base_dir)
        self._compression = compression
        self._raw_dir = self._base_dir / "vol_raw"
        self._l2_override = _coerce_l2(l2)

    @staticmethod
    def _default_base_dir() -> Path:
        """Its own leaf under the shared cache root.

        Same resolution chain as :meth:`CurveStore._default_base_dir` and
        :class:`USTFutureStore` - ``ARBS_CACHE_DIR``, then platformdirs, then the
        OS fallback - but a leaf of its own (``swaption_cube_store``). The
        precedent in this repo is that each store owns a directory: a second
        store writing into the first one's tree makes ``available_assets`` on
        either of them a lie.
        """
        root = os.getenv("ARBS_CACHE_DIR")
        if root:
            return Path(root) / "swaption_cube_store"
        try:
            import platformdirs

            return Path(platformdirs.user_cache_dir(appname="ARBS", appauthor=False)) / "swaption_cube_store"
        except Exception:  # noqa: BLE001 - platformdirs is optional
            local = os.getenv("LOCALAPPDATA")
            if local:
                return Path(local) / "ARBS" / "Cache" / "swaption_cube_store"
            return Path.home() / ".cache" / "arbs" / "swaption_cube_store"

    @classmethod
    def default(cls) -> "SwaptionCubeStore":
        """A module-wide singleton, like :meth:`CurveStore.default`."""
        if cls._default_instance is None:
            with cls._default_lock:
                if cls._default_instance is None:
                    cls._default_instance = cls()
        return cls._default_instance

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def _part_dir(self, asset: str, trading_date: datetime.date) -> Path:
        return self._raw_dir / f"asset={_sanitize(asset)}" / f"date={trading_date.isoformat()}"

    # ── L2 ─────────────────────────────────────────────────────────────

    def l2_sync(self, *, need: str = "read") -> Optional[Any]:
        """The L2 sync for this store, or ``None`` when policy says no.

        ``need="write"`` also returns ``None`` in read-only mode. Never raises:
        an unreachable or unconfigured L2 must degrade to local-only, because the
        local tier is complete on its own.
        """
        try:
            from Caching.supabase_swaption_cube_sync import resolve_cube_sync

            return resolve_cube_sync(self._base_dir, mode=self._l2_override, need=need)
        except Exception as exc:  # noqa: BLE001
            logger.warning("swaption cube L2 unavailable (%s); staying local.", exc)
            return None

    # ── Write ──────────────────────────────────────────────────────────

    @staticmethod
    def to_frame(cube: Any, *, citi_index: str = "") -> pd.DataFrame:
        """One long row per ``(expiry, tenor, offset_bp)`` node, plus the units.

        Reads through :meth:`SwaptionCubeData.vol`, so a node the cube refuses to
        serve is a node that does not get stored - the store cannot contain a
        number the data layer would not hand out.
        """
        rows: List[Dict[str, Any]] = []
        for expiry in cube.expiries():
            for tenor in cube.tenors():
                for off in cube.offsets():
                    rows.append(
                        {
                            "expiry": str(expiry),
                            "tenor": str(tenor),
                            "offset_bp": float(off),
                            "vol_bp": float(cube.vol(expiry, tenor, off)),
                        }
                    )
        frame = pd.DataFrame(rows)
        frame["as_of"] = pd.Timestamp(cube.as_of).date().isoformat()
        frame["currency"] = str(cube.currency).upper()
        frame["measure"] = str(cube.measure)
        frame["skew_measure"] = str(cube.skew_measure)
        frame["served_unit"] = str(cube.served_unit)
        frame["vol_unit"] = str(cube.vol_unit)
        frame["strike_unit"] = str(cube.strike_unit)
        frame["source"] = str(cube.source)
        frame["citi_index"] = str(citi_index or "")
        frame["schema_version"] = int(CUBE_SCHEMA_VERSION)
        return frame

    def write_day(
        self,
        asset: str,
        trading_date: Any,
        cube: Any,
        *,
        citi_index: str = "",
        overwrite: bool = False,
        push_l2: Optional[bool] = None,
    ) -> Optional[dict]:
        """Store one dated cube. Returns write metadata, or None if unchanged.

        ``push_l2=None`` follows the store's L2 mode (see the module docstring);
        ``True``/``False`` force it. The push is **synchronous** - unlike
        ``CurveStore``, which runs a background queue because its day blobs are
        hundreds of kilobytes. A cube day is ~19 KB, so a thread pool would buy a
        few milliseconds and cost a shutdown race.

        An L2 failure never fails the local write: the local partition is the
        source of truth and it is already on disk by then. A backfill that needs
        to *see* push failures should drive
        :class:`~Caching.supabase_swaption_cube_sync.SupabaseSwaptionCubeSync`
        directly, which raises.
        """
        day = _to_date(trading_date)
        frame = self.to_frame(cube, citi_index=citi_index)
        if frame.empty:
            return None
        table = pa.Table.from_pandas(frame, preserve_index=False)
        payload = _write_parquet_bytes(table, self._compression)
        part_dir = self._part_dir(asset, day)

        # A cube partition holds EXACTLY ONE cube, which is where this departs
        # from CurveStore. There, a partition may legitimately hold several
        # parquet files and readers concat them - the rows are different
        # timestamps within the day. Here one partition IS one surface, so a
        # second file would make the read ambiguous and content-addressing means
        # a differing cube lands under a different sha rather than replacing.
        #
        # Silently adding it and silently dropping it are both wrong, so a
        # genuine conflict raises and the caller decides. The warm never reaches
        # this: it skips days that are already present.
        existing = sorted(part_dir.glob("*.parquet")) if part_dir.exists() else []
        if existing and not overwrite:
            sha = hashlib.sha256(payload).hexdigest()
            if not any(f.name == f"{sha}.parquet" for f in existing):
                raise FileExistsError(
                    f"{asset} {day.isoformat()} is already stored with different content "
                    f"({existing[0].name[:12]}... vs {sha[:12]}...). A cube partition holds one "
                    "surface; pass overwrite=True to replace it, or invalidate_day() first. "
                    "Quotes for a past date changing is a restatement worth noticing, not a "
                    "write to apply quietly."
                )
        meta = _atomic_content_write(part_dir, payload, overwrite=overwrite)

        # Push even when `meta is None` (byte-identical local file already there):
        # a local hit says nothing about whether L2 has the day. push_day itself
        # skips when the remote sha already matches, so this costs one indexed
        # metadata read, not a re-upload.
        sync = self._write_sync(push_l2)
        if sync is not None:
            try:
                sync.push_day(asset, day, rewrite=overwrite)
            except Exception as exc:  # noqa: BLE001 - the local write stands
                logger.warning(
                    "swaption cube L2 push failed for %s %s (%s); the local partition "
                    "is written and is the source of truth.",
                    asset, day, exc,
                )
        return meta

    def _write_sync(self, push_l2: Optional[bool]) -> Optional[Any]:
        """Resolve the write-side sync for one call's ``push_l2`` argument."""
        if push_l2 is False:
            return None
        if push_l2 is None:
            return self.l2_sync(need="write")
        # push_l2 is True: an explicit argument outranks the environment, which
        # is what makes a CLI flag work without the caller having to have set an
        # env var before the first `Caching` import.
        try:
            from Caching.l2_policy import L2Mode
            from Caching.supabase_swaption_cube_sync import resolve_cube_sync

            return resolve_cube_sync(
                self._base_dir, mode=L2Mode.READ_WRITE, need="write"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("swaption cube L2 unavailable (%s); staying local.", exc)
            return None

    # ── Read ───────────────────────────────────────────────────────────

    def read_day(self, asset: str, trading_date: Any, *, _allow_l2: bool = True) -> Optional[pd.DataFrame]:
        """The raw stored frame for one day, or ``None`` on any miss.

        Never raises for a cold or damaged partition: like
        ``CurveStore._load_...``, a miss must degrade to "rebuild it from the
        quotes" rather than take the caller down.

        On a local miss this falls through to L2 **only when the L2 mode allows
        reads**, which is off by default. That is stricter than ``CurveStore``,
        where a read on an unconfigured checkout reaches production and runs DDL
        on the way. ``_allow_l2`` guards the single retry so a pull that lands
        nothing readable cannot recurse.
        """
        day = _to_date(trading_date)
        part_dir = self._part_dir(asset, day)
        if not part_dir.exists() or not any(part_dir.glob("*.parquet")):
            if _allow_l2 and self._pull_from_l2(asset, day):
                return self.read_day(asset, day, _allow_l2=False)
            return None
        files = sorted(part_dir.glob("*.parquet"))
        if not files:
            return None
        if len(files) > 1:
            # write_day refuses to create this, so it means the partition was
            # touched by something else. Newest wins, and say so - picking by
            # filename would be picking by sha, i.e. at random.
            logger.warning(
                "swaption cube store: %s has %d parquet files; one partition is one cube. "
                "Using the newest (%s). Run invalidate_day() and rewrite to make it "
                "unambiguous.",
                part_dir, len(files), files[-1].name,
            )
            files = sorted(files, key=lambda f: f.stat().st_mtime)
        try:
            return pq.read_table(files[-1]).to_pandas()
        except Exception as exc:  # noqa: BLE001
            logger.debug("swaption cube store: unreadable partition %s (%s)", files[-1], exc)
            return None

    def _pull_from_l2(self, asset: str, day: datetime.date) -> bool:
        sync = self.l2_sync(need="read")
        if sync is None:
            return False
        try:
            return bool(sync.pull_day(asset, day))
        except Exception as exc:  # noqa: BLE001 - a cold L2 must degrade, not raise
            logger.warning("swaption cube L2 pull failed for %s %s (%s)", asset, day, exc)
            return False

    def prefetch_range(
        self, asset: str, start: Any, end: Any, *, overwrite: bool = False
    ) -> List[datetime.date]:
        """Materialise every L2 day in ``[start, end]`` that is not already local.

        The resume for a fresh machine. Empty list when L2 reads are off. Costs
        one manifest query plus the payloads actually missing - it does not
        download the whole range to discover it already had it.
        """
        sync = self.l2_sync(need="read")
        if sync is None:
            return []
        return sync.prefetch_range(asset, _to_date(start), _to_date(end), overwrite=overwrite)

    def l2_coverage(self, asset: str) -> Optional[Dict[str, Any]]:
        """Local vs remote day sets and where their shas disagree, or ``None``."""
        sync = self.l2_sync(need="read")
        return None if sync is None else sync.coverage(asset)

    def reconstruct_cube(self, asset: str, trading_date: Any) -> Optional[Any]:
        """Rebuild the :class:`SwaptionCubeData` for one day, or ``None``.

        The rebuilt object is ``validate()``-d by its own constructor path, so a
        cube that comes out of here has passed the same unit, raggedness and
        positivity checks a freshly fetched one does.
        """
        frame = self.read_day(asset, trading_date)
        if frame is None or frame.empty:
            return None
        return self.cube_from_frame(frame)

    @staticmethod
    def cube_from_frame(frame: pd.DataFrame) -> Any:
        """Inverse of :meth:`to_frame`."""
        from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData

        version = int(frame["schema_version"].iloc[0]) if "schema_version" in frame else 0
        if version > CUBE_SCHEMA_VERSION:
            raise ValueError(
                f"swaption cube partition is schema v{version}; this build understands "
                f"v{CUBE_SCHEMA_VERSION}. Upgrade rather than read it wrong."
            )

        first = frame.iloc[0]
        # Preserve the axis order the cube was written with; sort_tenors is the
        # authority on maturity order and re-deriving it here could silently
        # reorder a surface.
        from MDP.CitiVelocityExcel.catalog import sort_tenors

        expiries = sort_tenors(frame["expiry"].unique())
        tenors = sort_tenors(frame["tenor"].unique())
        pivot = frame.pivot_table(
            index="expiry", columns="tenor", values="vol_bp", aggfunc="first"
        )

        atm_rows = frame[frame["offset_bp"] == 0.0]
        atm = atm_rows.pivot_table(
            index="expiry", columns="tenor", values="vol_bp", aggfunc="first"
        ).reindex(index=expiries, columns=tenors)

        skew: Dict[float, pd.DataFrame] = {}
        for off in sorted(o for o in frame["offset_bp"].unique() if float(o) != 0.0):
            block = frame[frame["offset_bp"] == off]
            skew[float(off)] = block.pivot_table(
                index="expiry", columns="tenor", values="vol_bp", aggfunc="first"
            ).reindex(index=expiries, columns=tenors)

        _ = pivot
        cube = SwaptionCubeData(
            as_of=datetime.date.fromisoformat(str(first["as_of"])),
            currency=str(first["currency"]),
            measure=str(first["measure"]),
            atm=atm,
            skew=skew,
            skew_measure=str(first["skew_measure"]),
            served_unit=str(first["served_unit"]),
            vol_unit=str(first["vol_unit"]),
            strike_unit=str(first["strike_unit"]),
            source=str(first["source"]),
        )
        return cube.validate()

    def reconstruct_cubes_batch(
        self, asset: str, trading_dates: Sequence[Any]
    ) -> Dict[datetime.date, Any]:
        """Rebuild many days. Missing or malformed days are simply absent.

        No thread pool: this is parquet reads and pandas pivots, not curve
        solving, and it measures at roughly a millisecond a day.
        """
        out: Dict[datetime.date, Any] = {}
        for stamp in trading_dates:
            day = _to_date(stamp)
            try:
                cube = self.reconstruct_cube(asset, day)
            except Exception as exc:  # noqa: BLE001 - one bad day must not kill a batch
                logger.debug("swaption cube store: %s unusable (%s)", day, exc)
                continue
            if cube is not None:
                out[day] = cube
        return out

    # ── Coverage ───────────────────────────────────────────────────────

    def has_day(self, asset: str, trading_date: Any) -> bool:
        part_dir = self._part_dir(asset, _to_date(trading_date))
        return part_dir.exists() and any(part_dir.glob("*.parquet"))

    def available_dates(self, asset: str) -> List[datetime.date]:
        asset_dir = self._raw_dir / f"asset={_sanitize(asset)}"
        if not asset_dir.exists():
            return []
        dates: List[datetime.date] = []
        for d in sorted(asset_dir.iterdir()):
            if d.is_dir() and d.name.startswith("date="):
                try:
                    dates.append(datetime.date.fromisoformat(d.name[5:]))
                except ValueError:
                    continue
        return dates

    def available_assets(self) -> List[str]:
        if not self._raw_dir.exists():
            return []
        return sorted(
            d.name[len("asset=") :] for d in self._raw_dir.iterdir()
            if d.is_dir() and d.name.startswith("asset=")
        )

    def invalidate_day(self, asset: str, trading_date: Any) -> bool:
        """Delete one day. Returns True if anything was removed."""
        part_dir = self._part_dir(asset, _to_date(trading_date))
        deleted = False
        if part_dir.exists():
            for f in part_dir.glob("*.parquet"):
                f.unlink()
                deleted = True
            try:
                part_dir.rmdir()
            except OSError:
                pass
        return deleted

    def coverage(self, asset: str) -> Dict[str, Any]:
        """``{n_days, first, last, gaps}`` - what is actually here."""
        days = self.available_dates(asset)
        if not days:
            return {"asset": asset, "n_days": 0, "first": None, "last": None, "gaps": 0}
        expected = pd.bdate_range(days[0], days[-1])
        have = set(days)
        gaps = [d.date() for d in expected if d.date() not in have]
        return {
            "asset": asset,
            "n_days": len(days),
            "first": days[0],
            "last": days[-1],
            "gaps": len(gaps),
            "gap_dates": gaps[:10],
        }

    def __repr__(self) -> str:
        return f"SwaptionCubeStore({self._base_dir})"
