"""Fast reader for the Citi Velocity swaption-vol store, plus the JPM
swaption-implied terminal distribution of rate shifts.

The store on disk is one parquet per day::

    %LOCALAPPDATA%/ARBS/Cache/swaption_cube_store/vol_raw/
        asset=USD-SWAPTIONVOL-CITIVELOEXCEL/date=YYYY-MM-DD/*.parquet

with columns ``expiry, tenor, offset_bp, vol_bp, ...``. Vols are NORMAL, quoted
in bp, and ``offset_bp`` is an absolute strike offset from ATMF
(``skew_measure = NORMALABSOLUTE``).

**Coverage, measured rather than assumed** (2019-01-01..2026-08-31, 1900 store
days, for the 1Yx30Y node the JPM note uses):

===================  =========  =======================================
series               coverage   available from
===================  =========  =======================================
ATMF vol             97.8%      2015-10-08
full OTM smile       83.9%      2020-03-25
===================  =========  =======================================

That gap is why strat 1 defaults to the note's **breakeven-vol** signal (needs
ATMF only, so it runs from Jan-2019) and treats the **expected-payoff** signal
(needs the smile) as a config knob covering Mar-2020 onward. Both are the note's
own; it presents them as two readings of the same comparison::

    "Both measures can be interpreted as a relative value signal for curve
     convexity trades versus swaptions."
"""

from __future__ import annotations

import datetime
import functools
import glob
import os
import pathlib
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "default_store_root",
    "load_vol_panel",
    "atmf_vol_series",
    "smile_on",
    "implied_shift_density",
    "STORE_ENV_VAR",
]

STORE_ENV_VAR = "ARBS_SWAPTION_CUBE_ROOT"

_DEFAULT_ASSET = "USD-SWAPTIONVOL-CITIVELOEXCEL"


def default_store_root(asset: str = _DEFAULT_ASSET) -> pathlib.Path:
    """Root directory of the day-partitioned vol store."""
    override = os.environ.get(STORE_ENV_VAR)
    if override:
        return pathlib.Path(override) / "vol_raw" / f"asset={asset}"
    local = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return pathlib.Path(local) / "ARBS" / "Cache" / "swaption_cube_store" / "vol_raw" / f"asset={asset}"


def _day_dirs(root: pathlib.Path) -> List[Tuple[datetime.date, pathlib.Path]]:
    out: List[Tuple[datetime.date, pathlib.Path]] = []
    for p in sorted(glob.glob(str(root / "date=*"))):
        m = re.search(r"date=(\d{4})-(\d{2})-(\d{2})$", p)
        if not m:
            continue
        out.append((datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), pathlib.Path(p)))
    return out


def load_vol_panel(
    pairs: Sequence[Tuple[str, str]],
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    *,
    asset: str = _DEFAULT_ASSET,
    root: Optional[pathlib.Path] = None,
    cache_path: Optional[pathlib.Path] = None,
) -> pd.DataFrame:
    """Tidy panel of ``(date, expiry, tenor, offset_bp, vol_bp)`` for *pairs*.

    Reading 2,700 daily parquets is ~a minute, so the filtered result is cached
    to ``cache_path`` when given. The cache key is the caller's responsibility --
    pass a path that encodes the pair list.
    """
    if cache_path is not None and pathlib.Path(cache_path).exists():
        df = pd.read_parquet(cache_path)
    else:
        root = pathlib.Path(root) if root is not None else default_store_root(asset)
        if not root.exists():
            raise FileNotFoundError(
                f"swaption cube store not found at {root}. Set ${STORE_ENV_VAR} to override."
            )
        want = {(str(e).upper(), str(t).upper()) for e, t in pairs}
        frames: List[pd.DataFrame] = []
        for day, d in _day_dirs(root):
            files = glob.glob(str(d / "*.parquet"))
            if not files:
                continue
            try:
                one = pd.read_parquet(files[0], columns=["expiry", "tenor", "offset_bp", "vol_bp"])
            except Exception:
                continue
            key = list(zip(one["expiry"].astype(str).str.upper(), one["tenor"].astype(str).str.upper()))
            mask = np.fromiter((k in want for k in key), dtype=bool, count=len(one))
            if not mask.any():
                continue
            sub = one.loc[mask].copy()
            sub["date"] = day
            frames.append(sub)
        if not frames:
            raise RuntimeError(f"no rows found for pairs={sorted(want)} under {root}")
        df = pd.concat(frames, ignore_index=True)
        df["date"] = pd.to_datetime(df["date"])
        df["expiry"] = df["expiry"].astype(str).str.upper()
        df["tenor"] = df["tenor"].astype(str).str.upper()
        if cache_path is not None:
            pathlib.Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_path, index=False)

    df["date"] = pd.to_datetime(df["date"])
    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["date"] <= pd.Timestamp(end)]
    return df.sort_values(["date", "expiry", "tenor", "offset_bp"]).reset_index(drop=True)


def atmf_vol_series(panel: pd.DataFrame, expiry: str, tenor: str) -> pd.Series:
    """Daily ATMF normal vol in bp/yr for one (expiry, tenor) node."""
    m = (
        (panel["expiry"] == str(expiry).upper())
        & (panel["tenor"] == str(tenor).upper())
        & (panel["offset_bp"] == 0.0)
    )
    s = panel.loc[m].set_index("date")["vol_bp"].sort_index()
    return s[~s.index.duplicated(keep="last")].dropna()


def smile_on(
    panel: pd.DataFrame,
    day: datetime.date,
    expiry: str,
    tenor: str,
) -> pd.DataFrame:
    """The ``(offset_bp, vol_bp)`` smile for one node on one day, or empty."""
    ts = pd.Timestamp(day)
    m = (
        (panel["date"] == ts)
        & (panel["expiry"] == str(expiry).upper())
        & (panel["tenor"] == str(tenor).upper())
    )
    out = panel.loc[m, ["offset_bp", "vol_bp"]].dropna().sort_values("offset_bp")
    return out.reset_index(drop=True)


def implied_shift_density(
    smile: pd.DataFrame,
    shifts_bp: Sequence[float],
    *,
    tte_years: float = 1.0,
    min_points: int = 5,
) -> np.ndarray:
    """Risk-neutral density of the TERMINAL RATE SHIFT, on the *shifts_bp* grid.

    This is JPM Exhibit 3's "swaption-implied distribution": the terminal
    distribution of rate shifts implied by ATMF and OTM pricing at a co-expiry
    node. It is built the standard way -- interpolate the normal-vol smile in
    strike space, price a Bachelier call at every strike, and take the second
    derivative (Breeden-Litzenberger).

    Everything is measured in bp *relative to the forward*, so the forward level
    cancels: strike offset ``k`` is the rate shift that ends at that strike.
    Returned weights are normalised over the supplied grid (which is truncated,
    like the note's own -250..+250 axis), so they are directly usable as
    ``weights`` in :func:`RVUtils.ConvexityRV.payoff.expected_payoff`.

    Returns an array of NaN when the smile is too sparse to differentiate --
    the caller must decide whether to fall back to the breakeven-vol signal
    rather than silently receive a lognormal-ish guess.
    """
    from RVUtils.ImpliedDistribution._bachelier import bachelier_call_price

    x = np.asarray(list(shifts_bp), dtype=float)
    if smile is None or len(smile) < min_points:
        return np.full(x.shape, np.nan)

    k = smile["offset_bp"].to_numpy(dtype=float)
    v = smile["vol_bp"].to_numpy(dtype=float)
    ok = np.isfinite(k) & np.isfinite(v) & (v > 0)
    k, v = k[ok], v[ok]
    if k.size < min_points:
        return np.full(x.shape, np.nan)

    # Fine strike grid spanning the quoted wings, with a small pad so the second
    # difference is defined at the edges of the requested shift grid.
    lo, hi = float(min(k.min(), x.min())), float(max(k.max(), x.max()))
    pad = 0.05 * max(hi - lo, 1.0)
    grid = np.linspace(lo - pad, hi + pad, 2001)
    h = float(grid[1] - grid[0])

    # Vol interpolated in strike space; flat extrapolation beyond the quoted
    # wings, which is the conservative choice (a linear extrapolation of a
    # normal-vol smile turns negative and produces a negative density).
    vol = np.interp(grid, k, v, left=v[0], right=v[-1])

    # Forward = 0 in shift space; strike = the shift. Bachelier in bp units.
    call = np.array(
        [bachelier_call_price(strike=float(s), forward=0.0, vol_normal=float(sig),
                              tte=float(tte_years), discount=1.0)
         for s, sig in zip(grid, vol)],
        dtype=float,
    )

    dens_grid = np.gradient(np.gradient(call, h), h)
    dens_grid = np.clip(dens_grid, 0.0, None)  # arbitrage/noise guard

    w = np.interp(x, grid, dens_grid)
    total = w.sum()
    if not np.isfinite(total) or total <= 0:
        return np.full(x.shape, np.nan)
    return w / total
