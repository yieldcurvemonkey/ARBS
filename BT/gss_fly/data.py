"""Curve data for the GSS butterfly book.

Two independent sources, because they answer different questions:

* :func:`build_curve_panel` — the **backtest** path. Per date it fits the ARBS cash spline and
  keeps the per-bond yield error, which is the ARBS equivalent of GSS's ``FittedZspread``. Runs
  entirely offline off ``USTS_FEDINVEST_WSJ_LIVE-QL``; no Excel, no add-in.
* :func:`fetch_curveset_snapshot` — the **CVSNAP** path. Pulls the whole UST curveset at one
  instant from Citi Velocity and merges the reference data onto it, so a curve can be reconstructed
  as it stood at a timestamp rather than at a close.

The snapshot path carries a guard worth naming: Citi's point-in-time read resolves *as-of*, so a
request for an instant the wire never published silently returns an earlier one. Every snapshot
here is returned with the stamp it actually resolved to, and :func:`fetch_curveset_snapshot` will
refuse a resolution further from the request than ``max_staleness``.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from BT.gss_fly.config import GSSConfig, UniverseConfig

logger = logging.getLogger(__name__)

__all__ = [
    "CurvePanel",
    "build_curve_panel",
    "apply_universe_filter",
    "fetch_curveset_snapshot",
    "warm_bond_snapshots",
    "BOND_SNAPSHOT_VALUES",
]

#: The Citi bond values worth pulling for a curveset snapshot. ``PRICE`` is clean and ``DURATION``
#: is modified — both established previously against Citi's own field dictionary.
BOND_SNAPSHOT_VALUES = ("YIELD", "PRICE", "DURATION", "DV01", "ASW", "ZSPREAD")


@dataclass
class CurvePanel:
    """Dates × bonds panels plus the per-date reference frame.

    ``s2c`` is the spline yield error in bp: **positive means cheap** (the bond yields more than
    the fitted curve says it should). GSS's ``FittedZspread`` has the same orientation.
    """

    s2c: pd.DataFrame
    ytm: pd.DataFrame
    ttm: pd.DataFrame
    reference: pd.DataFrame  # long: date, cusip, ttm, maturity, cpn, rank, issue_date, ...
    rmse: pd.Series

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.s2c.index)

    def curve_on(self, when) -> pd.DataFrame:
        """The per-bond frame for one date, indexed by cusip: ttm, maturity, cpn, rank, s2c."""
        ts = pd.Timestamp(when)
        ref = self.reference[self.reference["date"] == ts]
        if ref.empty:
            return pd.DataFrame(columns=["ttm", "maturity", "cpn", "rank", "s2c"])
        out = ref.set_index("cusip").copy()
        if ts in self.s2c.index:
            out["s2c"] = self.s2c.loc[ts].reindex(out.index)
        else:
            out["s2c"] = np.nan
        return out

    def summary(self) -> str:
        return (
            f"CurvePanel {len(self.s2c)} dates {self.dates.min().date()}..{self.dates.max().date()}, "
            f"{self.s2c.shape[1]} bonds, median RMSE {self.rmse.median():.2f}bp"
        )


def _maturity_years(maturity_date, asof) -> float:
    try:
        return (pd.Timestamp(maturity_date) - pd.Timestamp(asof)).days / 365.25
    except Exception:
        return float("nan")


def build_curve_panel(
    dates: Sequence[datetime.date],
    mdp,
    *,
    cache_path: Optional[Path] = None,
    show_progress: bool = True,
) -> CurvePanel:
    """Fit the cash spline on every date and assemble the dates × bonds panels.

    ``mdp`` is a :class:`~MDP.FixedRateBonds.FixedRateBondsMDP.FixedRateBondsMDP`. A date whose
    spline fails is skipped and logged rather than aborting the panel — a missing day costs one
    observation, an aborted panel costs the run.
    """
    dates = [pd.Timestamp(d).date() for d in dates]
    if cache_path is not None:
        cache_path = Path(cache_path)
        if cache_path.exists():
            logger.info("curve panel cache hit: %s", cache_path)
            return _load_panel(cache_path)

    s2c_rows: Dict[pd.Timestamp, pd.Series] = {}
    ytm_rows: Dict[pd.Timestamp, pd.Series] = {}
    ttm_rows: Dict[pd.Timestamp, pd.Series] = {}
    ref_frames: List[pd.DataFrame] = []
    rmse: Dict[pd.Timestamp, float] = {}

    iterator = dates
    if show_progress:
        try:
            import tqdm

            iterator = tqdm.tqdm(dates, desc="GSS curve panel", unit="day")
        except ImportError:
            pass

    for d in iterator:
        ts = pd.Timestamp(d)
        try:
            spline = mdp.fetch_cash_spline(d)
        except Exception as exc:  # noqa: BLE001 — logged, not hidden
            logger.warning("spline failed on %s: %s: %s", d, type(exc).__name__, exc)
            continue
        if spline is None or spline.yield_errors is None or spline.yield_errors.empty:
            logger.warning("spline empty on %s", d)
            continue

        frame = spline.to_frame().reset_index()
        if "cusip" not in frame.columns:
            frame = frame.rename(columns={frame.columns[0]: "cusip"})

        s2c_rows[ts] = pd.Series(frame["yield_error_bp"].to_numpy(), index=frame["cusip"])
        if "observed" in frame.columns:
            ytm_rows[ts] = pd.Series(frame["observed"].to_numpy(), index=frame["cusip"])
        ttm_rows[ts] = pd.Series(frame["ttm"].to_numpy(), index=frame["cusip"])
        rmse[ts] = float(spline.rmse) if spline.rmse is not None else np.nan

        try:
            ref = mdp.get_bond_reference_data(as_of_date=d)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reference data failed on %s: %s", d, exc)
            continue
        ref = ref.copy()
        ref["date"] = ts
        if "maturity_date" in ref.columns:
            ref["maturity"] = ref["maturity_date"].map(lambda m: _maturity_years(m, d))
        if "issue_date" in ref.columns:
            ref["seasoning_days"] = ref["issue_date"].map(
                lambda i: (pd.Timestamp(d) - pd.Timestamp(i)).days if pd.notna(i) else np.nan
            )
        ref_frames.append(ref)

    if not s2c_rows:
        raise RuntimeError("no dates produced a spline — check the MDP source and the date range")

    s2c = pd.DataFrame(s2c_rows).T.sort_index()
    ytm = pd.DataFrame(ytm_rows).T.sort_index() if ytm_rows else pd.DataFrame(index=s2c.index)
    ttm = pd.DataFrame(ttm_rows).T.sort_index()
    reference = pd.concat(ref_frames, ignore_index=True)
    panel = CurvePanel(s2c=s2c, ytm=ytm, ttm=ttm, reference=reference, rmse=pd.Series(rmse).sort_index())

    if cache_path is not None:
        _save_panel(panel, cache_path)
    return panel


def _save_panel(panel: CurvePanel, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    panel.s2c.to_parquet(path / "s2c.parquet")
    panel.ytm.to_parquet(path / "ytm.parquet")
    panel.ttm.to_parquet(path / "ttm.parquet")
    panel.reference.to_parquet(path / "reference.parquet")
    panel.rmse.to_frame("rmse").to_parquet(path / "rmse.parquet")
    logger.info("wrote curve panel cache -> %s", path)


def _load_panel(path: Path) -> CurvePanel:
    return CurvePanel(
        s2c=pd.read_parquet(path / "s2c.parquet"),
        ytm=pd.read_parquet(path / "ytm.parquet"),
        ttm=pd.read_parquet(path / "ttm.parquet"),
        reference=pd.read_parquet(path / "reference.parquet"),
        rmse=pd.read_parquet(path / "rmse.parquet")["rmse"],
    )


def apply_universe_filter(curve: pd.DataFrame, cfg: Optional[UniverseConfig] = None) -> pd.DataFrame:
    """``select_eligible_bonds`` — coupon, time-to-maturity, seasoning, and rank."""
    cfg = cfg or UniverseConfig()
    out = curve
    if "cpn" in out.columns:
        out = out[out["cpn"] < cfg.max_coupon]
    if "ttm" in out.columns:
        out = out[out["ttm"] >= cfg.min_ttm]
    if "seasoning_days" in out.columns:
        out = out[(out["seasoning_days"].isna()) | (out["seasoning_days"] >= cfg.min_seasoning_days)]
    if "rank" in out.columns and cfg.exclude_ranks:
        out = out[~out["rank"].isin(cfg.exclude_ranks)]
    return out


# --------------------------------------------------------------------------- CVSNAP curveset
def fetch_curveset_snapshot(
    when,
    *,
    isins: Optional[Sequence[str]] = None,
    reference: Optional[pd.DataFrame] = None,
    values: Sequence[str] = BOND_SNAPSHOT_VALUES,
    quotes=None,
    freq: str = "DAILY",
    max_staleness: Optional[datetime.timedelta] = None,
    strict: bool = True,
) -> pd.DataFrame:
    """The whole UST curveset at one instant, with reference data merged on.

    This is the CVSNAP path. It returns one row per bond and one column per requested Citi value,
    joined to whatever reference frame is supplied (cusip/isin, ttm, maturity, coupon, rank).

    Parameters
    ----------
    when
        The instant to resolve. Citi resolves **as-of**, so the value returned may pre-date the
        request; the resolved stamp is attached as the ``snap_stamp`` column.
    max_staleness
        Refuse (``strict``) or warn when the resolution is further back than this. Defaults to one
        day for daily data and fifteen minutes for intraday — the nearest-snapshot trap is silent
        otherwise and will happily serve yesterday's curve for today's request.

    Raises
    ------
    RuntimeError
        When the Citi Excel bridge is unavailable. That is not recoverable in-process: the add-in
        only registers its UDFs inside a human-authenticated Excel.
    """
    from MDP.CitiVelocityExcel import tags as cv_tags

    when = pd.Timestamp(when)
    if max_staleness is None:
        max_staleness = datetime.timedelta(days=1) if str(freq).upper().startswith("D") else datetime.timedelta(minutes=15)

    if isins is None:
        if reference is None:
            raise ValueError("supply either isins= or reference=")
        col = "isin" if "isin" in reference.columns else "cusip"
        isins = reference[col].dropna().astype(str).unique().tolist()

    if quotes is None:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()

    tag_map: Dict[str, Tuple[str, str]] = {}
    for isin in isins:
        for v in values:
            try:
                tag_map[cv_tags.bond(isin, v)] = (isin, v)
            except Exception:  # noqa: BLE001 — an unknown value for this bond is not fatal
                continue
    if not tag_map:
        raise ValueError("no resolvable bond tags were built")

    try:
        frame = quotes.frame(
            list(tag_map.keys()),
            freq,
            start=when - datetime.timedelta(days=10),
            end=when,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Citi Velocity snapshot unavailable ({type(exc).__name__}: {exc}). The bridge attaches "
            "to a human-authenticated Excel with the Velocity add-in signed in; it cannot spawn one."
        ) from exc

    if frame is None or frame.empty:
        raise RuntimeError(f"Citi returned no rows for the curveset at {when}")

    idx = pd.DatetimeIndex(frame.index)
    usable = idx[idx <= when]
    if len(usable) == 0:
        raise RuntimeError(f"no quote at or before {when}; earliest is {idx.min()}")
    stamp = usable.max()
    lag = when - stamp
    if lag > max_staleness:
        msg = (
            f"curveset snapshot for {when} resolved to {stamp} ({lag} stale, limit {max_staleness}). "
            "Citi resolves as-of, so this is an older curve, not the one requested."
        )
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)

    row = frame.loc[stamp]
    records: Dict[str, Dict[str, float]] = {}
    for tag, (isin, value) in tag_map.items():
        if tag not in row.index:
            continue
        v = row[tag]
        if pd.isna(v):
            continue
        records.setdefault(isin, {})[value.lower()] = float(v)

    out = pd.DataFrame.from_dict(records, orient="index")
    out.index.name = "isin"
    out = out.reset_index()
    out["snap_stamp"] = stamp
    out["snap_request"] = when

    if reference is not None:
        col = "isin" if "isin" in reference.columns else "cusip"
        out = out.merge(reference.rename(columns={col: "isin"}), on="isin", how="left")

    return out


def warm_bond_snapshots(
    isins: Sequence[str],
    start,
    end,
    *,
    values: Sequence[str] = BOND_SNAPSHOT_VALUES,
    quotes=None,
    freq: str = "DAILY",
    chunk: int = 200,
) -> Dict[str, int]:
    """Pull and cache the bond history so later snapshots resolve from disk.

    Returns ``{tag_family: rows}``. Chunked because the add-in wedges on very wide requests — a
    528-column fetch has been observed to take Excel to 5 GB.
    """
    from MDP.CitiVelocityExcel import tags as cv_tags

    if quotes is None:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()

    all_tags: List[str] = []
    for isin in isins:
        for v in values:
            try:
                all_tags.append(cv_tags.bond(isin, v))
            except Exception:  # noqa: BLE001
                continue

    counts: Dict[str, int] = {}
    for i in range(0, len(all_tags), chunk):
        block = all_tags[i : i + chunk]
        try:
            frame = quotes.frame(block, freq, start=start, end=end)
        except Exception as exc:  # noqa: BLE001 — one bad block must not kill the warm
            logger.warning("warm block %d-%d failed: %s", i, i + len(block), exc)
            continue
        counts[f"block_{i}"] = 0 if frame is None else int(frame.notna().sum().sum())
        logger.info("warmed %d tags (%d..%d), %s rows", len(block), i, i + len(block), counts[f"block_{i}"])
    return counts
