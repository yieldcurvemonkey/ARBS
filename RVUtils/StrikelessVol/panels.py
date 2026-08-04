"""Daily panels: forward par rates, implied vols, and the funding factor.

Panels are constant-maturity by construction (today's 10Y10Y is priced fresh
every day). Positions age; panels do not. Never join one to the other without
going through ``replication``, which owns the aging.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
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


def _interval_sidecar_path(cache_path: Path) -> Path:
    """The JSON file recording which ``[start, end]`` windows have actually
    been *queried* into ``cache_path`` -- see ``vol_panel``'s docstring for
    why a parquet's data extent alone cannot prove contiguous coverage.

    A sidecar next to the parquet, not parquet key-value metadata: it stays
    human-inspectable without a parquet reader, and avoids coupling this
    module to whichever parquet engine/version pandas resolves to for its
    custom-metadata API.
    """
    return Path(str(cache_path) + ".intervals.json")


def _load_fetched_intervals(sidecar_path: Path) -> List[tuple[dt.date, dt.date]]:
    if not sidecar_path.exists():
        return []
    import json

    with sidecar_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return [(dt.date.fromisoformat(s), dt.date.fromisoformat(e)) for s, e in raw]


def _save_fetched_intervals(sidecar_path: Path, intervals: List[tuple[dt.date, dt.date]]) -> None:
    import json

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    raw = [[s.isoformat(), e.isoformat()] for s, e in sorted(intervals)]
    with sidecar_path.open("w", encoding="utf-8") as f:
        json.dump(raw, f)


def _merge_fetched_interval(
    intervals: List[tuple[dt.date, dt.date]], new_start: dt.date, new_end: dt.date
) -> List[tuple[dt.date, dt.date]]:
    """Fold ``[new_start, new_end]`` into ``intervals``, merging only where it
    overlaps or abuts an existing interval -- its start is at most one
    calendar day past that interval's end, i.e. no date sits strictly
    between them. Disjoint intervals are kept apart: collapsing them into
    one bounding range would assert coverage for dates that were never
    fetched, which is exactly the bug this mechanism exists to rule out.

    Assumes ``intervals`` is already itself fully merged (the only way this
    function is ever called), so a single sorted pass is enough: once a
    stored interval is far enough past the growing merged window to be
    rejected, no later (even-further-out) stored interval can bridge back to
    it without an overlapping entry in between, which by that invariant
    cannot exist.
    """
    one_day = dt.timedelta(days=1)
    merged_start, merged_end = new_start, new_end
    remaining: List[tuple[dt.date, dt.date]] = []
    for s, e in sorted(intervals):
        if s <= merged_end + one_day and e >= merged_start - one_day:
            merged_start = min(merged_start, s)
            merged_end = max(merged_end, e)
        else:
            remaining.append((s, e))
    remaining.append((merged_start, merged_end))
    return sorted(remaining)


def _fetched_intervals_cover(
    intervals: List[tuple[dt.date, dt.date]], start: dt.date, end: dt.date
) -> bool:
    """Whether some *single* recorded interval fully contains ``[start, end]``.

    Deliberately not "the union of all intervals covers [start, end]": two
    disjoint fetches (e.g. one for 2015, an unrelated one for 2018) must
    never be read as a single 2015-2018 fetch just because their union
    happens to bracket a later request -- the calendar days between them
    were never actually queried, and reading them as covered is precisely
    the silent-gap bug this mechanism exists to close.
    """
    return any(s <= start and e >= end for s, e in intervals)


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

    Caching reuses ``forward_rate_panel``'s leg-set-fingerprint discipline
    (``_cache_path_for_legs`` / ``_write_panel_cache``) rather than forking a
    second, simpler cache: this panel's columns are structures instead of
    legs, but the schema hazard those helpers exist for -- one cache file
    being asked to hold two different column sets -- is identical here.
    Keying the file by the sorted, whitespace-stripped structure labels means
    one file only ever holds one structure set.

    Coverage is a genuinely different problem from ``forward_rate_panel``,
    though, because this panel is requested as a ``[start, end]`` **range**
    rather than an explicit date list. An *endpoint* check
    (``cached.index.min() <= start and cached.index.max() >= end``) is not
    safe: ``_write_panel_cache``'s ``combine_first`` will happily union two
    **disjoint** fetch windows into one file (e.g. an early-history window
    and an unrelated, much later one). A later request spanning both would
    pass the endpoint check, and the missing months/years in between produce
    *no NaN* to trip the "no NaN in the served slice" guard -- those dates
    are simply absent rows, not null cells, so that guard cannot see the
    hole either. This is the same failure shape Task 4 closed for
    ``forward_rate_panel`` (there, exact date-list membership makes it
    impossible for a gap to hide; a range interface loses that property for
    free and has to earn it back explicitly).

    The fix: coverage is tracked explicitly rather than inferred from the
    data. A JSON sidecar (``_interval_sidecar_path``) records the list of
    ``[start, end]`` windows that were actually *queried* -- not the
    (possibly narrower) range the returned data happens to span, since a
    market's own earliest-history boundary is not a gap, it is the market
    not existing yet; recording the queried window is also what lets a
    ``start`` earlier than a market's real history still hit cache on a
    repeat call. On write, a new window is merged into the stored list only
    when it overlaps or abuts an existing one (``_merge_fetched_interval``);
    disjoint windows stay separate entries -- never collapsed into one
    bounding range, which would assert coverage that was never fetched. On
    read, a hit requires the requested ``[start, end]`` to sit inside **one**
    stored interval (``_fetched_intervals_cover``): a request straddling two
    disjoint intervals is a miss, not a hit, because nothing on disk proves
    the gap between them was ever queried. The "no NaN in the served slice"
    guard still runs afterwards, belt-and-braces, exactly as it does in
    ``forward_rate_panel``.
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
    # request -- so the cache schema check below can never be permanently
    # unsatisfiable just because a caller asked for a structure this curve
    # doesn't have.
    wanted_labels = sorted({s.replace(" ", "") for s in wanted.values()})
    struct_cache_path = _cache_path_for_legs(cache_path, wanted_labels) if cache_path else None
    sidecar_path = _interval_sidecar_path(struct_cache_path) if struct_cache_path else None

    if struct_cache_path and struct_cache_path.exists() and sidecar_path.exists():
        fetched_intervals = _load_fetched_intervals(sidecar_path)
        if _fetched_intervals_cover(fetched_intervals, start, end):
            cached = pd.read_parquet(struct_cache_path)
            cached.index = pd.to_datetime(cached.index)
            # One file per structure set (see _cache_path_for_legs), so this
            # is an equality check, not a subset check -- any file at this
            # path was only ever written for exactly this structure set.
            has_all_structures = set(cached.columns) == set(wanted_labels)
            if has_all_structures:
                slice_ = cached.loc[str(start):str(end)]
                # Complete or absent, never partial -- belt-and-braces on top
                # of the interval check above, which is what actually rules
                # out a silently-missing-rows gap.
                if not slice_.isna().to_numpy().any():
                    return slice_

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

    if struct_cache_path:
        # Parquet first, sidecar second: if a crash lands between the two
        # writes, the sidecar under-reports coverage (a wasted re-fetch next
        # time) rather than over-reporting it (which would recreate the
        # exact silent-gap bug this mechanism exists to close).
        _write_panel_cache(panel, struct_cache_path)
        fetched_intervals = _load_fetched_intervals(sidecar_path)
        fetched_intervals = _merge_fetched_interval(fetched_intervals, start, end)
        _save_fetched_intervals(sidecar_path, fetched_intervals)
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
