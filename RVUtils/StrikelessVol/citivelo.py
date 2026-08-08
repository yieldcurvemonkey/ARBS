"""Citi Velocity backend for the StrikelessVol study (plan Task 30).

The GS universe in :mod:`universe` was bounded by GS coverage (USD stops at a
30y point, history 2010+). The Citi banked par grids, measured 2026-08-08 on
this machine, serve **44 tenors to 50Y daily from 2005** for USD/EUR/GBP (JPY
from 2006, CAD long end from 2012), so pairs that were "absent by construction"
there are observable here — most notably USD ``10y10y/25y10y``, the best pair
in the Citi 2019 note (Sharpe 0.35), and the whole published 8-pair set.

Curves come through ``IRSwapsMDP(source="CITIVELO_EXCEL")`` whose EOD path
reads the warmed CurveStore (``<curve>-CITIVELOEXCEL`` assets) and never
touches Excel. Vols come from the local SwaptionCubeStore panel parquet
(USD only; ATM history 2015+, full smile 2020-01-24+).

Long-end data quirks, measured (mask, do not assume): GBP 25Y prints from
2007-05, 30Y from 2010-11 while 35Y/45Y print from 2005 — treat pre-2012
long-end history as suspect until the integrity gate passes; EUR pre-2019 is
Citi's vendor-spliced pre-ESTR history; JPY 35Y has gaps pre-2006.
"""
from __future__ import annotations

import datetime as dt
import math
import pathlib
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

CITIVELO_SOURCE = "CITIVELO_EXCEL"

#: Curve names as MDP/IRSwaps/CITIVELO_EXCEL/curve_names.py registers them.
CITIVELO_MARKET_CURVES: Dict[str, str] = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR-1D",
    "JPY": "JPY-TONAR-1D",
    "GBP": "GBP-SONIA-1D",
    "CAD": "CAD-CORRA-1D",
}

#: Measured banked coverage (probe 2026-08-08): all five markets serve 50Y.
CITIVELO_MAX_POINT_YEARS: Dict[str, float] = {m: 50.0 for m in CITIVELO_MARKET_CURVES}


def _pair(market: str, s_fwd: str, s_tail: str, l_fwd: str, l_tail: str) -> ForwardPair:
    return ForwardPair(
        market=market,
        curve_name=CITIVELO_MARKET_CURVES[market],
        short=ForwardLeg(s_fwd, s_tail),
        long=ForwardLeg(l_fwd, l_tail),
    )


#: The eight pairs of Citi "Trading long-dated convexity" (2019-05-09) Figure 4,
#: in the note's column order — published Sharpes 0.05..0.35 — plus the one
#: extra sv-study pair (5y10y/15y10y). Reproducing the note's table on Citi's
#: own curves is the positive control for this backend.
USD_CITIVELO_PAIRS = (
    _pair("USD", "10Y", "5Y", "15Y", "15Y"),
    _pair("USD", "10Y", "10Y", "15Y", "15Y"),
    _pair("USD", "10Y", "10Y", "20Y", "10Y"),
    _pair("USD", "10Y", "10Y", "20Y", "15Y"),
    _pair("USD", "10Y", "10Y", "25Y", "10Y"),
    _pair("USD", "15Y", "5Y", "20Y", "10Y"),
    _pair("USD", "15Y", "5Y", "20Y", "15Y"),
    _pair("USD", "20Y", "5Y", "25Y", "10Y"),
    _pair("USD", "5Y", "10Y", "15Y", "10Y"),
)

EUR_CITIVELO_PAIRS = (
    _pair("EUR", "10Y", "10Y", "20Y", "10Y"),
    _pair("EUR", "15Y", "5Y", "20Y", "10Y"),
    _pair("EUR", "10Y", "10Y", "25Y", "10Y"),
)

JPY_CITIVELO_PAIRS = (
    _pair("JPY", "10Y", "10Y", "20Y", "10Y"),
    _pair("JPY", "15Y", "5Y", "20Y", "10Y"),
    _pair("JPY", "10Y", "10Y", "25Y", "10Y"),
)

GBP_CITIVELO_PAIRS = (
    _pair("GBP", "15Y", "10Y", "25Y", "10Y"),
    _pair("GBP", "10Y", "10Y", "20Y", "10Y"),
)

CAD_CITIVELO_PAIRS = (
    _pair("CAD", "10Y", "10Y", "20Y", "10Y"),
)

ALL_CITIVELO_PAIRS = (
    USD_CITIVELO_PAIRS + EUR_CITIVELO_PAIRS + JPY_CITIVELO_PAIRS
    + GBP_CITIVELO_PAIRS + CAD_CITIVELO_PAIRS
)

#: Short-dated slopes where the convexity story should NOT hold (same shapes
#: as universe.PLACEBO_PAIRS, on the Citi curve).
CITIVELO_PLACEBO_PAIRS = (
    _pair("USD", "1Y", "5Y", "2Y", "5Y"),
    _pair("USD", "2Y", "2Y", "3Y", "2Y"),
)


def citivelo_pairs(markets: Optional[Iterable[str]] = None) -> List[ForwardPair]:
    if markets is None:
        return list(ALL_CITIVELO_PAIRS)
    wanted = {m.upper() for m in markets}
    return [p for p in ALL_CITIVELO_PAIRS if p.market in wanted]


def stored_dates(market: str, start: Optional[dt.date] = None,
                 end: Optional[dt.date] = None) -> List[dt.date]:
    """Days the warmed CurveStore holds for this market's EOD asset."""
    from Caching.curve_store import CurveStore

    asset = f"{CITIVELO_MARKET_CURVES[market.upper()]}-CITIVELOEXCEL"
    days = CurveStore.default().available_dates(asset)
    if start is not None:
        days = [d for d in days if d >= start]
    if end is not None:
        days = [d for d in days if d <= end]
    return days


# ---------------------------------------------------------------------------
# Vols (USD only — the cube asset). bp/day internally, per the sv convention.

_SQRT252 = math.sqrt(252.0)

_VOL_PANEL_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "notebooks" / "data" / "citivelo_rv" / "vol_panel.parquet"
)


def _cell_label(expiry: str, tenor: str) -> str:
    return f"{expiry}{tenor}".lower()


def citivelo_atm_vol_panel(
    cells: Sequence[str],
    *,
    start: Optional[dt.date] = None,
    end: Optional[dt.date] = None,
    panel_path: Optional[pathlib.Path] = None,
) -> pd.DataFrame:
    """ATM normal vols in **bp/day**, one column per cell label ("2y10y").

    Cube vols are stored ANNUAL normal bp (verified against the live snapshot:
    1Yx10Y 84.55 annual ≈ 5.33 bp/day); this converts at the boundary, once.
    ATM-only days are included — ATM cells are genuine quotes there.
    """
    path = panel_path or _VOL_PANEL_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing - rebuild with "
            "`conda run -n stir python notebooks/backtests/citivelo_rv/build_vol_panel.py`"
        )
    panel = pd.read_parquet(path, columns=["date", "expiry", "tenor", "offset_bp", "vol_bp"])
    atm = panel[panel["offset_bp"] == 0.0].copy()
    atm["cell"] = (atm["expiry"].str.lower() + atm["tenor"].str.lower())
    wanted = {c.lower() for c in cells}
    atm = atm[atm["cell"].isin(wanted)]
    out = (
        atm.pivot_table(index="date", columns="cell", values="vol_bp", aggfunc="last")
        .sort_index()
        / _SQRT252
    )
    out.index = pd.to_datetime(out.index)
    if start is not None:
        out = out[out.index >= pd.Timestamp(start)]
    if end is not None:
        out = out[out.index <= pd.Timestamp(end)]
    missing = wanted - set(out.columns)
    if missing:
        raise KeyError(f"cube panel has no cells {sorted(missing)}")
    return out
