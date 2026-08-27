"""Vol sources for the CvxSuite: cube ATM reads, realized vol, unit converters.

Everything at the ledger boundary is **bp/day**; the cube serves **bp/yr**
(annualised normal vol — ``vol_unit == "bp"``, annualised, per
``MDP/CitiVelocityExcel/vol/cube_data.py:287-292``); the only sqrt(252)
crossings live in :func:`bp_year_to_day` / :func:`bp_day_to_year` (DESIGN.md
section 1 conventions).

Data source (measured on this machine, recon "data layer" section 2)
--------------------------------------------------------------------
``SwaptionCubeStore.default()`` asset ``USD-SWAPTIONVOL-CITIVELOEXCEL``:
**2,711 stored days, 2015-10-08 .. 2026-08-24** (dir listing, this machine).
Citi published no strike offsets before **2020-01-24**: 1,067 ATM-only days
(1 offset, 153 rows/day), then the full smile (13 offsets, 1,989 rows/day)
(``MDP/IRSwaptions/CITIVELO/cube_store.py:22-34``). That early shape "looks
exactly like a cache miss" and is data — the ATM node is present throughout.

Quoted axes vary by day — measured this session: 2026-08-24 serves 17
expiries x 8 tenors = 136 ATM nodes (tenor axis has no 3Y/4Y/12Y that day),
against the historical 17 x 9 = 153-node grid. And the expiry axis has **no
25Y node** anywhere (``MDP/CitiVelocityExcel/vol/cube_data.py:136-140``:
1M..30Y in 17 steps). Consequence: interpolation must be built from *the
day's own stored frame*, never a hardcoded grid, and a 25y expiry is an
**interior** interpolation between 20Y and 30Y — inside the envelope, so it
passes ``gates.support_gate``; a 40y expiry is outside and must not price.

Interpolation rule (copied with attribution, not imported)
----------------------------------------------------------
Bilinear in (expiry_years, tenor_years): linear on tenor within each
bracketing expiry, then linear across expiry, **CLAMPED at the axis edges and
never extrapolated** — "extrapolating a vol surface off the end of its own
grid is how a backtest acquires prices no one quoted"
(``RVUtils/BasisVsVol/v3_panel.py:132-159`` ``_interp_grid``; that module is
project-scoped, not a DESIGN-listed kernel, so the 25-line rule is copied
here with this attribution rather than imported). ``clamp=False`` tightens
the same invariant: outside the day's quoted envelope the answer is NaN
instead of the edge value; inside, identical.

Reads are pinned ``read_day(..., _allow_l2=False)``: a miss with L2 allowed
costs 0.172 s per day against 0.0002 s without (measured,
``RVUtils/BasisVsVol/v3_panel.py:106-107``), and panel loops touch thousands
of days.

Units guard (the w3 pattern)
----------------------------
"A SOFR normal vol is order 50-200 bp/yr, i.e. 3-13 bp/day. If this ever
leaves in the wrong unit the numbers stay plausible-looking in isolation and
only the SPREAD against the long end goes wrong, which is the hardest place
to notice it" (``RVUtils/ConvexityRV/w3_ca_vs_longend.py:157-168``).
:func:`units_median_guard` raises naming the offending median. Divergence
from w3, deliberate: w3 skips the check on an empty series (``if len(s):``);
here an empty/all-NaN series **raises** — a guard that silently passes when
it has no evidence is not a guard.

What this is NOT
----------------
* :func:`realized_vol_bp_day` is NOT the annualised
  ``ConvexityRV.citi_screen.realized_vol_bp`` (that one multiplies by
  sqrt(252) and returns bp/yr); this one returns the raw trailing std of
  daily diffs in **bp/day**. Same ex-date mask semantics, no annualisation.
* :func:`cube_atm_bp_year` is NOT the priced-NVOL path
  (``IRSwaptionMDP``/Route 3) — it reads the *quoted* grid only, and it is
  NOT an extrapolator in either clamp mode.
* A cube vol is never the hedge pair: vol prices rent (DESIGN.md section 7;
  measured partial R-squared <= 0.044, ``reference_fly_not_a_vol_proxy``).
"""

from __future__ import annotations

import datetime
import math
import re
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from Caching.swaption_cube_store import SwaptionCubeStore

__all__ = [
    "ASSET",
    "BUSINESS_DAYS",
    "tenor_years",
    "point_label",
    "quoted_axes",
    "cube_atm_bp_year",
    "cube_atm_panel",
    "realized_vol_bp_day",
    "bp_year_to_day",
    "bp_day_to_year",
    "units_median_guard",
]

#: The one asset with local coverage (USD only — recon data layer section 2a).
ASSET = "USD-SWAPTIONVOL-CITIVELOEXCEL"

#: The single annualisation constant. 252.0, same as citi_screen/w3.
BUSINESS_DAYS = 252.0
_SQRT_BDAYS = math.sqrt(BUSINESS_DAYS)

_TENOR_RE = re.compile(r"^(\d+)\s*([MY])$")


def tenor_years(label) -> float:
    """``"18M" -> 1.5``, ``"5Y" -> 5.0``; numerics pass through; else NaN.

    Mirrors ``RVUtils/BasisVsVol/v3_panel.py:86-91`` (same regex, same NaN
    convention for unparseable labels).
    """
    if isinstance(label, (int, float, np.integer, np.floating)):
        return float(label)
    m = _TENOR_RE.match(str(label).strip().upper())
    if not m:
        return float("nan")
    n, unit = int(m.group(1)), m.group(2)
    return n / 12.0 if unit == "M" else float(n)


def point_label(expiry_y: float, tail_y: float) -> str:
    """Column label for a cube point: ``(5.0, 10.0) -> "5yx10y"``.

    Deliberately the swaption shorthand (with the ``x``), NOT the
    CurveFlyScreener leg label ``"5y10y"`` — a cube point (option expiry x
    swap tail) and a forward swap leg (fwd start x tenor) are different
    instruments and must not share a label namespace.
    """
    return f"{float(expiry_y):g}yx{float(tail_y):g}y"


# ---------------------------------------------------------------------------
# Cube reads
# ---------------------------------------------------------------------------
def _read_atm_grid(store, asset: str, date) -> Optional[pd.DataFrame]:
    """The day's ATM sub-grid as (expiry_years, tenor_years, vol_bp), or None.

    ``read_day`` returns the raw long frame ``(expiry, tenor, offset_bp,
    vol_bp, ...)`` or None on any miss (never raises). The ATM filter is the
    ``np.isclose(offset_bp, 0.0)`` idiom of v3_panel.py:117, with the same
    ``fillna(9e9)`` sentinel so a non-numeric offset can never masquerade as
    ATM. Rows with unparseable axes or missing vols are dropped, matching
    v3_panel's finite-filter.
    """
    if store is None:
        store = SwaptionCubeStore.default()
    f = store.read_day(asset, date, _allow_l2=False)
    if f is None or len(f) == 0:
        return None
    off = pd.to_numeric(f["offset_bp"], errors="coerce").fillna(9e9)
    atm = f[np.isclose(off, 0.0)]
    if len(atm) == 0:
        return None
    g = pd.DataFrame({
        "expiry_years": [tenor_years(x) for x in atm["expiry"]],
        "tenor_years": [tenor_years(x) for x in atm["tenor"]],
        "vol_bp": pd.to_numeric(atm["vol_bp"], errors="coerce").to_numpy(),
    })
    g = g[np.isfinite(g["expiry_years"]) & np.isfinite(g["tenor_years"])
          & np.isfinite(g["vol_bp"])]
    return g if len(g) else None


def _interp_clamped(g: pd.DataFrame, t_exp: float, t_tail: float) -> float:
    """The v3_panel clamped bilinear rule (v3_panel.py:132-159), verbatim logic.

    Interpolate on tenor within each bracketing expiry, then across expiry;
    linear in years on both axes; CLAMPED at the edges, never extrapolated.
    """
    if g is None or len(g) == 0 or not np.isfinite(t_exp) or not np.isfinite(t_tail):
        return float("nan")
    exps = np.sort(g["expiry_years"].unique())
    lo = exps[exps <= t_exp].max() if (exps <= t_exp).any() else exps.min()
    hi = exps[exps >= t_exp].min() if (exps >= t_exp).any() else exps.max()

    def at(e: float) -> float:
        s = g[g["expiry_years"] == e]
        if len(s) == 0:
            return float("nan")
        x = s["tenor_years"].to_numpy(float)
        y = s["vol_bp"].to_numpy(float)
        o = np.argsort(x)
        return float(np.interp(np.clip(t_tail, x[o][0], x[o][-1]), x[o], y[o]))

    v_lo, v_hi = at(lo), at(hi)
    if not np.isfinite(v_lo):
        return v_hi
    if not np.isfinite(v_hi) or hi == lo:
        return v_lo
    w = (t_exp - lo) / (hi - lo)
    return float(v_lo + w * (v_hi - v_lo))


def _inside_envelope(g: pd.DataFrame, expiry_y: float, tail_y: float) -> bool:
    e = g["expiry_years"]
    t = g["tenor_years"]
    return bool(float(e.min()) <= expiry_y <= float(e.max())
                and float(t.min()) <= tail_y <= float(t.max()))


def quoted_axes(date, *, store=None, asset: str = ASSET
                ) -> Optional[Tuple[Tuple[float, ...], Tuple[float, ...]]]:
    """The day's quoted (expiry_years, tenor_years) axes, or None when absent.

    This is the feed for ``gates.support_gate`` — per DESIGN section 3, "the
    KeyError axes come from the cube's own expiries()/tenors(): that IS the
    support gate". The axes VARY BY DAY (measured: 2026-08-24 has 8 tenors
    against the historical 9), so support must be gated against the day's own
    frame, never a hardcoded grid.
    """
    g = _read_atm_grid(store, asset, date)
    if g is None:
        return None
    return (tuple(np.sort(g["expiry_years"].unique()).tolist()),
            tuple(np.sort(g["tenor_years"].unique()).tolist()))


def cube_atm_bp_year(expiry_y: float, tail_y: float, date: datetime.date, *,
                     store=None, clamp: bool = True, asset: str = ASSET) -> float:
    """ATM normal vol in **bp/yr** at (expiry_y, tail_y) from the stored grid.

    Bilinear interpolation INSIDE the day's quoted axes (the clamped v3_panel
    rule — see module docstring). NaN when the day is absent from the store,
    when the frame has no ATM rows, or when either coordinate is non-finite.

    ``clamp`` (contract interpretation, flagged in the build report):
      * ``True`` (default): a point outside the quoted envelope returns the
        edge value (clamped, still never extrapolated).
      * ``False``: a point outside the envelope returns NaN; inside, the
        result is identical to ``clamp=True``.

    Never raises on a data miss and never extrapolates in either mode.
    """
    e, t = float(expiry_y), float(tail_y)
    if not (np.isfinite(e) and np.isfinite(t)):
        return float("nan")
    g = _read_atm_grid(store, asset, date)
    if g is None:
        return float("nan")
    if not clamp and not _inside_envelope(g, e, t):
        return float("nan")
    return _interp_clamped(g, e, t)


def cube_atm_panel(points: Sequence[Tuple[float, float]], dates, *,
                   store=None, clamp: bool = True, asset: str = ASSET
                   ) -> pd.DataFrame:
    """date x point panel of :func:`cube_atm_bp_year`, reading each day ONCE.

    ``points`` are (expiry_y, tail_y) tuples; columns are labelled by
    :func:`point_label` ("5yx10y"). The index is ``pd.Timestamp`` of each
    requested date, IN THE GIVEN ORDER; a day absent from the store keeps its
    row (all-NaN) — a dropped row would silently change downstream joins.

    One ``read_day`` per date regardless of the number of points: the read is
    the expensive part and the grid serves every point.
    """
    pts = [(float(e), float(t)) for e, t in points]
    cols = [point_label(e, t) for e, t in pts]
    idx, rows = [], []
    for d in dates:
        idx.append(pd.Timestamp(d))
        g = _read_atm_grid(store, asset, d)
        if g is None:
            rows.append([float("nan")] * len(pts))
            continue
        row = []
        for e, t in pts:
            if not (np.isfinite(e) and np.isfinite(t)):
                row.append(float("nan"))
            elif not clamp and not _inside_envelope(g, e, t):
                row.append(float("nan"))
            else:
                row.append(_interp_clamped(g, e, t))
        rows.append(row)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx), columns=cols)


# ---------------------------------------------------------------------------
# Realized vol (bp/day) and unit converters
# ---------------------------------------------------------------------------
def realized_vol_bp_day(levels_bp: pd.Series, *, window: int = 252,
                        min_periods: int = 100, ex_dates=None) -> pd.Series:
    """Trailing std (ddof=1) of daily diffs of a bp level series — **bp/day**.

    Mask semantics copied from ``ConvexityRV.citi_screen.realized_vol_bp``
    (citi_screen.py:167-176): the diff STAMPED at an excluded date (the
    change INTO that date) is masked to NaN — removed from the std and from
    the ``min_periods`` count while the window still advances — and the next
    day's diff (the change out of it) is kept. That is the roll-jump
    convention: "a constant-rank pack rate jumps at the roll because the
    contracts change, and a realized-vol column that counts that jump
    measures the roll, not the market" (citi_screen.py:123-126).

    ``ex_dates`` may be a boolean ``pd.Series`` (True = mask; reindexed to
    the levels index, missing -> False — citi_screen's exact idiom) or an
    iterable of date-likes (both sides are normalised through
    ``pd.DatetimeIndex`` so ``datetime.date`` entries match a Timestamp
    index; for an intraday-stamped index pass the boolean form).

    NOT annualised: citi_screen's function multiplies by sqrt(252) and
    returns bp/yr; this one does not — the ledger boundary is bp/day and the
    only sqrt(252) crossings are the named converters below.
    """
    d = pd.Series(levels_bp).astype(float).diff()
    if ex_dates is not None:
        if isinstance(ex_dates, pd.Series):
            # .eq(True): True/1 flags mask, missing/NaN/False do not — matches
            # citi_screen's fillna(False).astype(bool) for the documented
            # boolean (or 0/1) input, without the object-dtype downcast
            # FutureWarning. (Arbitrary numerics like 2.0 do NOT mask here;
            # pass booleans.)
            mask = ex_dates.reindex(d.index).eq(True)
        else:
            ex_list = list(ex_dates)
            try:
                ex_idx = pd.DatetimeIndex(pd.to_datetime(ex_list))
                own = pd.DatetimeIndex(pd.to_datetime(d.index))
                mask = pd.Series(own.isin(ex_idx), index=d.index)
            except (TypeError, ValueError):
                mask = pd.Series(d.index.isin(ex_list), index=d.index)
        d = d.where(~mask)
    return d.rolling(int(window), min_periods=int(min_periods)).std(ddof=1)


def bp_year_to_day(v):
    """bp/yr -> bp/day: divide by sqrt(252). Scalars and arrays/Series alike.

    Anchor: 100 bp/yr = 6.2994 bp/day; the w3 band 50-200 bp/yr maps to
    3.15-12.60 bp/day (inside the guard's 0.5-40)."""
    return v / _SQRT_BDAYS


def bp_day_to_year(v):
    """bp/day -> bp/yr: multiply by sqrt(252). Inverse of :func:`bp_year_to_day`."""
    return v * _SQRT_BDAYS


def units_median_guard(series_bp_day, lo: float = 0.5, hi: float = 40.0) -> None:
    """Raise ``ValueError`` naming the median unless it sits in [lo, hi] bp/day.

    The w3 pattern (``w3_ca_vs_longend.py:157-168``): a vol series in the
    wrong unit stays plausible-looking in isolation, so every SOFR-complex
    daily-vol series is median-checked at the ledger boundary. Bounds are
    inclusive. Divergence from w3 (deliberate): an empty or all-NaN series
    RAISES here rather than passing silently — no evidence is not a pass.
    """
    s = pd.Series(series_bp_day).astype(float)
    finite = s[np.isfinite(s)]
    med = float(finite.median()) if len(finite) else float("nan")
    if not np.isfinite(med):
        raise ValueError(
            "units_median_guard: series has no finite observations - cannot "
            "certify units (median is NaN). An empty guard input is a wiring "
            "bug, not a pass.")
    if not (float(lo) <= med <= float(hi)):
        raise ValueError(
            f"vol series median {med:.2f} is outside {lo:g}-{hi:g} bp/DAY. "
            "A SOFR-complex normal vol is order 50-200 bp/YEAR = 3-13 bp/day; "
            "a median this size usually means a bp/yr series crossed the "
            "ledger boundary unconverted - apply bp_year_to_day (divide by "
            "sqrt(252)) first.")
    return None
