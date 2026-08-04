"""Daily panels: forward par rates, implied vols, and the funding factor.

Panels are constant-maturity by construction (today's 10Y10Y is priced fresh
every day). Positions age; panels do not. Never join one to the other without
going through ``replication``, which owns the aging.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from RVUtils.StrikelessVol.conventions import VolQuote, slope_bp
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

logger = logging.getLogger(__name__)

PANEL_DIR = Path(__file__).resolve().parents[2] / "notebooks" / "data" / "strikeless_vol"

_SWAPTION_VOL_DATASET = "IR_SWAPTION_VOLS_V1_STANDARD"

__all__ = [
    "PANEL_DIR",
    "forward_rate_panel",
    "spread_panel",
    "vol_panel",
    "implied_quote",
]


def forward_rate_panel(
    curve_name: str,
    dates: Sequence[dt.date],
    legs: Iterable[ForwardLeg],
    *,
    source: str = "GSQUANT-RL",
    mdp=None,
    cache_path: Optional[str | Path] = None,
    show_progress: bool = False,
    max_missing_frac: float = 0.2,
) -> pd.DataFrame:
    """Constant-maturity forward par rates (decimals), one column per leg.

    Dates the provider cannot serve are dropped. They are never forward-filled:
    a filled day is a manufactured zero-change observation, and every realized
    vol and every changes-regression in this package would inherit the bias.

    ``max_missing_frac`` (default 0.2) guards against mistaking a systemic
    failure for a quiet market: a ``bdate_range`` legitimately contains market
    holidays no provider serves (~10/year in USD, roughly 4%; more in some
    other markets), so a small drop rate is normal. If the dropped fraction
    exceeds this threshold, or the panel would come back empty while dates
    were requested, that means the MDP or the pricing path broke for
    (almost) everything asked for -- not that a handful of holidays were
    skipped -- and this raises ``ValueError`` rather than silently returning
    a near-empty panel the caller has no way to distinguish from a calm one.

    ``show_progress`` is accepted but not yet wired up; reserved for a later
    task's progress bar on long bulk fetches.

    ``cache_path`` is keyed by leg set, not used as a literal path: the
    effective file is derived by appending a fingerprint of the (sorted, so
    order-independent) requested leg labels, e.g. ``panel.parquet`` becomes
    ``panel__a3f19c2b.parquet``. A caller who passes the same ``cache_path``
    for two different leg sets gets two different files -- that is intended.
    One file ever holds exactly one column schema, which is what makes the
    completeness guards below sufficient rather than merely defensive: see
    ``_cache_path_for_legs`` and ``_write_panel_cache``.

    Independently of that, ``cache_path`` never serves or persists a partial
    row: a cached slice with any NaN in the requested columns is treated as a
    miss and re-fetched, and a merged write drops any row that is not
    complete across every column the file carries.
    """
    legs = list(legs)
    dates = list(dates)
    wanted_labels = [leg.label for leg in legs]
    leg_cache_path = _cache_path_for_legs(cache_path, wanted_labels) if cache_path else None

    if leg_cache_path and leg_cache_path.exists():
        cached = pd.read_parquet(leg_cache_path)
        cached.index = pd.to_datetime(cached.index)
        wanted = pd.to_datetime(pd.Index(dates))
        has_all_dates = wanted.isin(cached.index).all()
        # One file per leg set (see _cache_path_for_legs), so this is an
        # equality check, not a subset check: any file at this path was only
        # ever written for exactly this leg set.
        has_all_legs = set(cached.columns) == set(wanted_labels)
        if has_all_dates and has_all_legs:
            slice_ = cached.loc[cached.index.isin(wanted), wanted_labels]
            # A row is complete or it is absent, never partial -- a NaN cell
            # (e.g. a legacy cache file, or one written outside this module)
            # is a miss, not a silent bad value served to the caller.
            if not slice_.isna().to_numpy().any():
                return slice_

    if mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source=source)

    curve_map = mdp.bulk_get_data({"curve_name": curve_name, "timestamps": dates})

    rows: List[dict] = []
    for ts, curve in curve_map.items():
        if ts == "live":
            raise ValueError(
                f"forward_rate_panel('{curve_name}'): bulk_get_data returned the "
                "'live' key -- one of the requested dates matched today and the "
                "MDP resolved it to the live snapshot, which cannot be placed on "
                "a DatetimeIndex here. Pass an explicit historical date instead."
            )
        if curve is None:
            logger.warning("skipping %s on %s: no curve returned", curve_name, ts)
            continue
        rec: dict = {}
        try:
            for leg in legs:
                swap = curve.build_irswap(fwd=leg.fwd, tenor=leg.tail)
                rec[leg.label] = float(curve.fair_rate(swap))
        except Exception:  # a curve that cannot price a leg contributes nothing
            logger.warning("skipping %s on %s", curve_name, ts, exc_info=True)
            continue
        rec["date"] = ts.date() if hasattr(ts, "date") else ts
        rows.append(rec)

    requested = len(dates)
    produced = len(rows)
    dropped = requested - produced
    missing_frac = (dropped / requested) if requested else 0.0
    logger.info(
        "forward_rate_panel('%s'): %d/%d requested dates produced rows "
        "(%d dropped, %.1f%% missing)",
        curve_name, produced, requested, dropped, missing_frac * 100.0,
    )
    if requested and (produced == 0 or missing_frac > max_missing_frac):
        date_range = f"{min(dates)}..{max(dates)}"
        raise ValueError(
            f"forward_rate_panel('{curve_name}', {date_range}): only "
            f"{produced}/{requested} requested dates produced rows ({dropped} "
            f"dropped, {missing_frac:.1%} missing, threshold "
            f"{max_missing_frac:.1%}). This looks like a systemic pricing "
            "failure, not ordinary holiday/weekend gaps."
        )

    if not rows:
        return pd.DataFrame(columns=wanted_labels)

    panel = pd.DataFrame(rows).set_index("date").sort_index()
    panel.index = pd.to_datetime(panel.index)
    panel = panel[wanted_labels]

    if leg_cache_path:
        _write_panel_cache(panel, leg_cache_path)
    return panel


def _cache_path_for_legs(cache_path: str | Path, wanted_labels: Sequence[str]) -> Path:
    """Derive the leg-set-specific file backing ``cache_path``.

    Three rounds of cache bugs (a cross-schema merge, then NaN cells, then
    silent eviction of complete rows) all had the same shape: one file being
    asked to hold two different column sets. Keying the file by a fingerprint
    of the (sorted) leg labels means one file only ever holds one schema, so
    ``combine_first`` only ever merges identical columns and the
    completeness guards elsewhere can only ever fire on a genuinely partial
    row within that one schema -- the whole class of cross-schema bug is
    structurally impossible rather than guarded against.

    The fingerprint is stable across runs and independent of the order legs
    were passed in: ``[10Y10Y, 20Y10Y]`` and ``[20Y10Y, 10Y10Y]`` resolve to
    the same file. A hex digest of the joined, sorted labels, truncated to 8
    characters, mirrors this repo's own fingerprinted-asset naming (e.g.
    ``Caching/utils.py``'s ``to_filename_key``, and the ``asset=<name>__<hash>``
    directories under ``data/ts``) -- this is house style, not a one-off.
    """
    cache_path = Path(cache_path)
    fingerprint = hashlib.sha1("|".join(sorted(wanted_labels)).encode()).hexdigest()[:8]
    return cache_path.with_name(f"{cache_path.stem}__{fingerprint}{cache_path.suffix}")


def _write_panel_cache(panel: pd.DataFrame, cache_path: str | Path) -> None:
    """Persist ``panel`` to ``cache_path`` (already leg-set-specific -- see
    ``_cache_path_for_legs``), unioned with whatever is already on disk
    rather than overwritten.

    The natural incremental call pattern is "extend the panel by a day, same
    cache file". Overwriting would silently shrink the cache down to just the
    freshly fetched (narrower, date-wise) rows, forcing a full re-fetch of
    history the file already had on every subsequent call -- exactly the kind
    of redundant external fetch that has hit provider rate limits before in
    this repo. On any date overlap the freshly fetched value in ``panel``
    wins.

    Because ``cache_path`` is already keyed by leg set, ``panel`` and any
    existing file at this path always share the same columns, so
    ``combine_first`` only ever merges identical schemas -- it can no longer
    introduce a NaN column the way a cross-leg-set merge once did (``panel``
    itself is always complete per row: ``forward_rate_panel`` only appends a
    date once every requested leg has priced). The ``dropna(how="any")``
    below is now belt-and-braces on top of that structural fix rather than
    the load-bearing guard -- it still refuses to persist a row that is not
    complete, in case ``existing`` is a legacy or externally-written file
    that predates the per-leg-set keying.
    """
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        existing = pd.read_parquet(cache_path)
        existing.index = pd.to_datetime(existing.index)
        combined = panel.combine_first(existing)
    else:
        combined = panel
    combined = combined.dropna(how="any")
    combined.sort_index().to_parquet(cache_path)


def spread_panel(rates: pd.DataFrame, pair: ForwardPair) -> pd.Series:
    """The pair's slope in bp: longer forward minus shorter forward."""
    short = rates[pair.short.label].astype(float)
    long_ = rates[pair.long.label].astype(float)
    out = pd.Series(
        slope_bp(short_rate=short, long_rate=long_),
        index=rates.index,
        name=pair.name,
    )
    return out


def _cache_path_for_window(
    cache_path: str | Path,
    curve_key: str,
    wanted_labels: Sequence[str],
    start: dt.date,
    end: dt.date,
) -> Path:
    """Derive the exact-window-and-curve-specific file backing ``cache_path``
    for ``vol_panel``.

    Unlike ``_cache_path_for_legs`` (structure/leg set only -- sufficient for
    ``forward_rate_panel``, whose explicit date list makes exact-date
    membership an available and load-bearing completeness check),
    ``vol_panel`` takes a ``[start, end]`` **range**. Every attempt to let a
    cache file answer an *arbitrary* sub-range of what it holds -- an
    endpoint-only min/max check, then an explicit fetched-interval sidecar --
    added its own way for the cache's metadata and its data to disagree:
    a cross-schema merge, then served NaN, then evicted rows, then a
    silently gapped read, and finally a sidecar that could outlive the
    parquet it described and resurrect a phantom coverage claim for data no
    longer on disk. Folding ``(curve_key, sorted wanted_labels, start, end)``
    into the file's identity removes the need to prove anything about
    coverage: the filename *is* the claim, and a hit requires an exact match
    on the whole request. The cost -- a changed window re-fetches instead of
    extending an existing file -- is deliberate: these builds are
    ``network``/``slow``-marked and run rarely, the repeated-identical-call
    case that actually matters in a research session still hits, and
    incremental extension is exactly the feature that produced every defect
    above. ``curve_key`` is part of the fingerprint so two curves that
    happen to share a structure label (e.g. two markets both quoting
    "2y 10y") and a ``cache_path`` prefix never collide on one file.
    """
    cache_path = Path(cache_path)
    key = "|".join([curve_key, *sorted(wanted_labels), start.isoformat(), end.isoformat()])
    fingerprint = hashlib.sha1(key.encode()).hexdigest()[:8]
    return cache_path.with_name(f"{cache_path.stem}__{fingerprint}{cache_path.suffix}")


def _read_window_cache(cache_path: Path, wanted_labels: Sequence[str]) -> Optional[pd.DataFrame]:
    """Load ``cache_path`` if it exists, is an exact-column match for
    ``wanted_labels``, and has no NaN cell -- otherwise ``None`` (a miss).

    Both checks are defensive rather than load-bearing: the filename already
    encodes the exact structure set this file was written for (see
    ``_cache_path_for_window``), and every write already goes through
    ``dropna(how="any")`` in ``vol_panel`` before being persisted. This is
    the same "belt-and-braces on top of a structural guarantee" stance used
    throughout this module, in case of a legacy or hand-written file.
    """
    if not cache_path.exists():
        return None
    cached = pd.read_parquet(cache_path)
    cached.index = pd.to_datetime(cached.index)
    if set(cached.columns) != set(wanted_labels):
        return None
    if cached.isna().to_numpy().any():
        return None
    return cached


def _write_window_cache(panel: pd.DataFrame, cache_path: Path) -> None:
    """Write ``panel`` to ``cache_path`` atomically: build it at a temp file
    in the same directory, then ``os.replace`` into place.

    This cache no longer does incremental/merged writes (see
    ``_cache_path_for_window``), so there is nothing to combine on disk --
    but a partial write (process killed mid-``to_parquet``, or two callers
    racing on the same exact window) could otherwise leave a truncated or
    corrupt file at a name a later run would treat as a hit. ``os.replace``
    is atomic on both POSIX and Windows, so ``cache_path`` is always either
    absent or the complete new file, never a partial one in between.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=cache_path.parent, prefix=f".{cache_path.stem}.", suffix=".tmp"
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        panel.to_parquet(tmp_path)
        os.replace(tmp_path, cache_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def vol_panel(
    curve_key: str,
    structures: Sequence[str],
    start: dt.date,
    end: dt.date,
    *,
    cache_path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """ATM normal vols in **bp/day**, one column per structure ("2y10y").

    ``structures`` are given in the ``ASSET_IDS_MAP`` form ("2y 10y"); columns
    come back whitespace-stripped ("2y10y"). GS publishes
    ``impliedNormalVolatility`` as a daily bp vol -- it is stored here exactly
    as published, and converted to annual normals only at display boundaries
    (see ``conventions.VolQuote.annual_normals``).

    Caching is keyed by an exact-window fingerprint of ``(curve_key, sorted
    structures, start, end)`` (``_cache_path_for_window``): a hit requires
    an **exact match** on the whole request, nothing else. See that
    function's docstring for why -- in short, every attempt to let a cache
    file answer an arbitrary sub-range of what it holds added its own way
    for the cache's metadata and its data to disagree, and making the
    window part of the file's identity removes the need to prove anything.
    A changed window always re-fetches rather than extending an existing
    file; the repeated-identical-call case that matters in a research
    session still hits.

    Any row this function returns -- fresh or cached -- is guaranteed
    complete across every requested structure: the panel is
    ``dropna(how="any")``'d once, right after the pivot, before it is either
    returned or written to cache, so a date with a genuine data gap in even
    one structure is dropped for all of them rather than served with a NaN
    cell (matches ``forward_rate_panel``'s "never forward-filled, never
    partially filled" stance). Cache writes are atomic
    (``_write_window_cache``: write-to-temp, then ``os.replace``).
    """
    structures = list(structures)

    from definitions.IRSwaptions import ASSET_IDS_MAP

    if curve_key not in ASSET_IDS_MAP:
        raise KeyError(
            f"Curve '{curve_key}' not configured in definitions.IRSwaptions.ASSET_IDS_MAP"
        )

    asset_map = ASSET_IDS_MAP[curve_key]
    wanted = {a: s for a, s in asset_map.items() if s in set(structures)}
    if not wanted:
        raise KeyError(f"No assets for {structures} on {curve_key}")

    missing = set(structures) - set(wanted.values())
    if missing:
        logger.warning(
            "vol_panel('%s'): requested structures %s are not in "
            "ASSET_IDS_MAP and will be absent from the returned panel.",
            curve_key, sorted(missing),
        )

    # Derived from what the curve actually carries (`wanted`), not the raw
    # request -- so the cache key can never end up naming a structure that
    # no data was ever fetched for.
    wanted_labels = sorted({s.replace(" ", "") for s in wanted.values()})
    window_cache_path = (
        _cache_path_for_window(cache_path, curve_key, wanted_labels, start, end)
        if cache_path else None
    )

    if window_cache_path:
        cached = _read_window_cache(window_cache_path, wanted_labels)
        if cached is not None:
            return cached

    from gs_quant.data import Dataset

    from MDP.IRSwaptions.GSQUANT.ql.grid import _ensure_gs_session

    _ensure_gs_session()

    raw = Dataset(_SWAPTION_VOL_DATASET).get_data(start=start, end=end, assetId=list(wanted))
    if raw is None or raw.empty:
        raise ValueError(f"GS returned no swaption vols for {curve_key} {start}..{end}")

    df = raw.copy()
    if df.index.name is None:
        df.index.name = "date"
    df["structure"] = df["assetId"].map(wanted).str.replace(" ", "", regex=False)
    df["bp_day"] = pd.to_numeric(df["impliedNormalVolatility"], errors="coerce")
    df = df.dropna(subset=["structure", "bp_day"])
    panel = (
        df.reset_index()
        .pivot_table(index="date", columns="structure", values="bp_day", aggfunc="last")
        .sort_index()
    )
    panel.index = pd.to_datetime(panel.index)
    # Complete or absent, never partial: a date missing even one requested
    # structure is dropped for all of them, not served with a NaN cell.
    panel = panel.dropna(how="any")

    if window_cache_path:
        _write_window_cache(panel, window_cache_path)
    return panel


def implied_quote(
    panel: pd.DataFrame, structure: str, date, *, market: str
) -> VolQuote:
    """One labelled implied vol from ``panel``, still in bp/day."""
    return VolQuote(
        value_bp_day=float(panel.loc[date, structure]),
        measure="implied",
        underlying=f"{market} {structure} ATM swaption (normal)",
        window="atm",
    )
