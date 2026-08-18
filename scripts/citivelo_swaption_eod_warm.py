r"""Offline, incremental EOD warm for Citi USD-SOFR swaption values.

The raw Citi CurveStore and SwaptionCubeStore are inputs, not priced values. This
module turns their common EOD dates into durable ``IRSWAPTION`` value rows so a
new notebook kernel can use DuckDB/Parquet immediately instead of rebuilding a
market context and pricing every day again.

The default manifest covers every expiry/tail point actually published by the
newest full Citi USD cube, for every supported standard package structure. The
``IRSwaptionsTB`` Citi EOD path derives those NVOLs from the raw smile (including
the costless 1x2/ladder root solve), so this is a sub-second incremental task,
not thousands of curve/pricer builds. Any non-standard package still persists
after its first pull through ``IRSwaptionsTB``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import pathlib
import sys
from typing import Any, Iterable, Sequence

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

LOG = logging.getLogger("citivelo_swaption_eod_warm")

CURVE_NAME = "USD-SOFR-1D"


class ExcelWasTouched(RuntimeError):
    """The nominally-offline warm attempted to enter the Citi COM client."""


def install_excel_tripwire() -> list[str]:
    """Fail visibly if a new store miss would otherwise use Excel over COM."""
    import MDP.CitiVelocityExcel.com_client as com
    from MDP.CitiVelocityExcel.errors import AddInNotSignedInError

    attempts: list[str] = []

    def _connect(*_args: Any, **_kwargs: Any):
        attempts.append("connect")
        raise AddInNotSignedInError()

    com.CitiVelocityExcelClient.connect = staticmethod(_connect)
    return attempts


def priceable_days(
    *,
    curve_name: str = CURVE_NAME,
    start: dt.date,
    end: dt.date,
) -> tuple[list[dt.date], list[dt.date]]:
    """Return CurveStore∩CubeStore days and the requested weekday gaps.

    A missing input day is reported to the caller instead of silently sending the
    value warm down a live fallback. Weekdays are used only for visibility; the
    returned priceable set is the authoritative source-of-truth.
    """
    from Caching.curve_store import CurveStore
    from Caching.swaption_cube_store import SwaptionCubeStore, asset_for
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import asset_for as curve_asset_for

    curve_days = set(CurveStore.default().available_dates(curve_asset_for(curve_name)))
    cube_days = set(SwaptionCubeStore.default().available_dates(asset_for("USD")))
    requested = [
        d
        for d in (start + dt.timedelta(days=i) for i in range((end - start).days + 1))
        if d.weekday() < 5
    ]
    priceable = sorted(d for d in requested if d in curve_days and d in cube_days)
    missing = [d for d in requested if d not in set(priceable)]
    return priceable, missing


def _surface_shorthands(days: Sequence[dt.date]) -> tuple[str, ...]:
    """Use actual cube axes rather than a stale hand-maintained tenor list."""
    from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

    for day in reversed(days):
        stored = load_stored_cubes("USD", [day]).get(day)
        if stored is None or not stored.has_smile:
            continue
        expiries = list(stored.data.expiries())
        tails = list(stored.data.tenors())
        if expiries and tails:
            return tuple(f"{expiry}x{tail}" for expiry in expiries for tail in tails)
    raise RuntimeError("No full-smile Citi USD swaption cube is available for the requested EOD range.")


def build_queries(
    *,
    days: Sequence[dt.date],
    curve_name: str = CURVE_NAME,
) -> list[Any]:
    """Build the complete published-node USD-SOFR EOD NVOL manifest.

    Static packages use fixed Citi smile offsets. Default 1x2s and ladders have
    a costless wing, but their forward/annuity/notional cancel in the Bachelier
    root equation; the TB therefore solves them directly from the native stored
    smile. Keep the query definitions conventional so their durable symbols are
    exactly the ones an interactive caller requests.
    """
    from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
    from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
    from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
    from TB.IRSwaptionsTB import _value_fingerprint

    queries: list[Any] = []
    for shorthand in _surface_shorthands(days):
        queries.append(IRSwaptionQuery(
            curve=curve_name,
            shorthand=shorthand,
            strike="ATMF",
            structure=IRSwaptionStructure.STRADDLE,
            value=IRSwaptionValue.NVOL,
        ))
        for strike, structure in (
            ("ATMF+25", IRSwaptionStructure.PAYER),
            ("ATMF-25", IRSwaptionStructure.RECEIVER),
        ):
            queries.append(IRSwaptionQuery(
                curve=curve_name,
                shorthand=shorthand,
                strike=strike,
                structure=structure,
                value=IRSwaptionValue.NVOL,
            ))
        for structure in IRSwaptionStructure:
            # Naked legs and the straddle are already represented over the full
            # cube grid above. Keeping them out of this tier avoids duplicates.
            if structure in {
                IRSwaptionStructure.PAYER,
                IRSwaptionStructure.RECEIVER,
                IRSwaptionStructure.STRADDLE,
            }:
                continue
            if structure in {
                IRSwaptionStructure.STRANGLE,
                IRSwaptionStructure.RISK_REVERSAL,
                IRSwaptionStructure.RECEIVER_1x2,
                IRSwaptionStructure.PAYER_1x2,
                IRSwaptionStructure.RECEIVER_LADDER,
                IRSwaptionStructure.PAYER_LADDER,
            }:
                structure_kwargs = {"wing_bps": 25.0}
            else:
                structure_kwargs = {"spread_bps": 25.0}
            queries.append(IRSwaptionQuery(
                curve=curve_name,
                shorthand=shorthand,
                strike="ATMF",
                structure=structure,
                value=IRSwaptionValue.NVOL,
                structure_kwargs=structure_kwargs,
            ))

    deduped: list[Any] = []
    seen: set[str] = set()
    for query in queries:
        key = _value_fingerprint(query)
        if key not in seen:
            seen.add(key)
            deduped.append(query)
    return deduped


def warm_eod_values(
    *,
    start: dt.date,
    end: dt.date,
    curve_name: str = CURVE_NAME,
    n_jobs: int = 8,
):
    """Price only persisted EOD inputs and return the resulting value frame."""
    from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
    from TB.IRSwaptionsTB import IRSwaptionsTB

    days, missing = priceable_days(curve_name=curve_name, start=start, end=end)
    if missing:
        LOG.warning(
            "Citi swaption EOD warm has %d weekday input gap(s) in %s..%s (first=%s); skipping them, never using Excel.",
            len(missing), start, end, missing[0],
        )
    if not days:
        raise RuntimeError(
            f"No common CurveStore/CubeStore EOD dates for {curve_name} in {start}..{end}; "
            "the value warm refuses the live Excel fallback."
        )

    attempts = install_excel_tripwire()
    queries = build_queries(days=days, curve_name=curve_name)
    LOG.info(
        "Warming %d Citi swaption value query(ies) on %d persisted day(s): %s..%s",
        len(queries), len(days), days[0], days[-1],
    )
    mdp = IRSwaptionMDP(
        source="CITIVELO-RL",
        curve_source="citivelo_excel_rl",
        request_defaults={"verify": False, "offline": True, "offline_only": True},
    )
    try:
        with IRSwaptionsTB(mdp, show_tqdm=True) as tb:
            frame = tb.get_timeseries(
                start=days[0],
                end=days[-1],
                queries=queries,
                timestamps=list(days),
                n_jobs=max(1, int(n_jobs)),
            )
    finally:
        close_cache = getattr(mdp, "close_cache", None)
        if callable(close_cache):
            try:
                close_cache()
            except Exception:
                pass

    if attempts:
        raise ExcelWasTouched(
            f"Offline Citi swaption value warm attempted {len(attempts)} Excel COM connection(s)."
        )
    return frame


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--n-jobs", type=int, default=8)
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    warm_eod_values(start=args.start, end=args.end, n_jobs=args.n_jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
