"""Carry & roll-down module for a rates relative-value toolkit (data-agnostic).

Closure-factory pattern mirrors ``make_pca_rv_builder`` in pca_rv.py:
``make_carry_roll_builder`` returns a tuple of closures closed over a ``state``
dict; the first closure exposes ``.state`` for introspection.

DATA CONTRACT
-------------
- A *curve snapshot* is a ``pd.Series`` whose index is tenor-in-years (float) and
  values are yields in whatever units the caller supplies (typically percent).
- A *curve timeseries* is a wide ``pd.DataFrame`` with a ``DatetimeIndex`` and
  columns that are tenors-in-years (float or float-castable).
- All functions return values **in the same units as the input**; the caller is
  responsible for scaling to basis points if desired.
- No instrument pricing, no IO.

PERCENT CONVENTION
------------------
The ``forward_rate`` and ``carry`` functions accept a ``pct: bool`` argument
(default ``True``).  When ``pct=True`` the function assumes the yields on the
curve snapshot are in *percent* (e.g. 4.5 means 4.5 %).  Internally the
function divides by 100 before applying the compounding identity and multiplies
the result back by 100 so that output units match input units.  Pass
``pct=False`` when yields are already in decimal (e.g. 0.045).
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd


# ===========================================================================
# Low-level interpolation helper
# ===========================================================================

def _interp(curve_row: pd.Series, x: float, interp: str = "cubic") -> float:
    """Interpolate *curve_row* at a single point *x*.

    Parameters
    ----------
    curve_row : pd.Series
        Index = tenor-in-years (float), values = yields.
    x : float
        Tenor at which to evaluate.
    interp : {"linear", "cubic"}
        ``"linear"`` uses ``numpy.interp``; ``"cubic"`` uses
        ``scipy.interpolate.CubicSpline`` falling back to ``numpy.interp``
        when fewer than 4 knots are available.
    """
    tenors = np.array(curve_row.index, dtype=float)
    yields = np.array(curve_row.values, dtype=float)
    if interp == "cubic" and len(tenors) >= 4:
        from scipy.interpolate import CubicSpline
        cs = CubicSpline(tenors, yields)
        return float(cs(x))
    # linear (or fallback)
    return float(np.interp(x, tenors, yields))


# ===========================================================================
# Module-level public functions
# ===========================================================================

def roll_down(
    curve_row: pd.Series,
    tenor: float,
    horizon: float,
    interp: str = "cubic",
) -> float:
    """Roll-down of a single tenor over a given horizon on the current curve.

    ``roll = y(tenor) - y(tenor - horizon)``

    where ``y(.)`` interpolates *curve_row* over its tenor index.

    Parameters
    ----------
    curve_row : pd.Series
        Curve snapshot: index = tenor-in-years, values = yields.
    tenor : float
        Current tenor of the instrument in years.
    horizon : float
        Holding period in years over which the instrument rolls down.
    interp : {"linear", "cubic"}
        Interpolation method.  ``"cubic"`` falls back to ``"linear"`` when
        fewer than 4 knots are available.

    Returns
    -------
    float
        Roll-down in the same units as the input yields (positive = roll up
        in yield, i.e. price rolls against you on an upward-sloping curve).
    """
    y_now = _interp(curve_row, tenor, interp)
    y_future = _interp(curve_row, tenor - horizon, interp)
    return float(y_now - y_future)


def forward_rate(
    curve_row: pd.Series,
    start: float,
    tenor: float,
    compounding: str = "annual",
    pct: bool = True,
) -> float:
    """Par/zero forward rate via the annual-compounding identity.

    Computes::

        f = ((1 + s_{start+tenor})^{start+tenor} / (1 + s_{start})^{start})
            ^{1/tenor} - 1

    where ``s_.`` are spot rates interpolated from *curve_row*.

    Parameters
    ----------
    curve_row : pd.Series
        Curve snapshot: index = tenor-in-years, values = spot yields.
    start : float
        Start of the forward period in years.
    tenor : float
        Length of the forward period in years.
    compounding : str
        Currently only ``"annual"`` is supported.
    pct : bool, default True
        When ``True`` (the default) the function assumes *curve_row* values
        are in **percent** (e.g. 4.5 means 4.5 %).  It divides by 100 before
        the compounding arithmetic and multiplies the result by 100 so that
        the returned value is also in percent.  Pass ``pct=False`` when the
        yields are already in decimal form (e.g. 0.045).

    Returns
    -------
    float
        Forward rate in the same units as the input (percent if ``pct=True``,
        decimal if ``pct=False``).
    """
    if compounding != "annual":
        raise ValueError(f"Unsupported compounding: {compounding!r}. Only 'annual' is implemented.")

    s_end = _interp(curve_row, start + tenor)
    s_start = _interp(curve_row, start)

    if pct:
        s_end /= 100.0
        s_start /= 100.0

    total_end = start + tenor
    f = ((1.0 + s_end) ** total_end / (1.0 + s_start) ** start) ** (1.0 / tenor) - 1.0

    if pct:
        f *= 100.0

    return float(f)


def carry(
    curve_row: pd.Series,
    tenor: float,
    horizon: float,
    repo: Optional[float] = None,  # reserved for future use; ignored
    pct: bool = True,
) -> float:
    """Forward-decomposition carry for a single tenor.

    Carry = ``forward_rate(curve_row, start=horizon, tenor=tenor-horizon)``
    minus ``spot_yield(tenor)``.

    This equals the excess yield earned by holding the instrument for
    ``horizon`` years versus rolling at the short rate (pure forward
    decomposition; no repo/coupon-minus-financing path).

    The ``repo`` argument is accepted for API compatibility but is **out of
    scope** in this version — it is silently ignored.

    Parameters
    ----------
    curve_row : pd.Series
        Curve snapshot: index = tenor-in-years, values = yields.
    tenor : float
        Tenor of the instrument in years.
    horizon : float
        Holding period in years.
    repo : float, optional
        Ignored — reserved for a future coupon-minus-repo carry path.
    pct : bool, default True
        Passed through to ``forward_rate``; see that function's docstring.

    Returns
    -------
    float
        Carry in the same units as the input yields.
    """
    fwd = forward_rate(curve_row, start=horizon, tenor=tenor - horizon, pct=pct)
    spot = _interp(curve_row, tenor)
    return float(fwd - spot)


def curve_carry_roll(
    curve_row: pd.Series,
    t_short: float,
    t_long: float,
    horizon: float,
    pct: bool = True,
) -> dict:
    """Carry and roll-down of a two-legged curve (long minus short).

    Parameters
    ----------
    curve_row : pd.Series
        Curve snapshot.
    t_short, t_long : float
        Tenors of the short and long legs in years.
    horizon : float
        Holding period in years.
    pct : bool, default True
        Passed through to ``carry``/``forward_rate``.

    Returns
    -------
    dict with keys ``carry``, ``roll``, ``total``.
    """
    roll = roll_down(curve_row, t_long, horizon) - roll_down(curve_row, t_short, horizon)
    c = carry(curve_row, t_long, horizon, pct=pct) - carry(curve_row, t_short, horizon, pct=pct)
    return {"carry": float(c), "roll": float(roll), "total": float(c + roll)}


def fly_carry_roll(
    curve_row: pd.Series,
    legs: list[float],
    weights: list[float],
    horizon: float,
    pct: bool = True,
) -> dict:
    """Carry and roll-down of an arbitrary weighted fly / structure.

    ``roll  = sum(w_i * roll_down(leg_i, horizon))``
    ``carry = sum(w_i * carry(leg_i, horizon))``

    Parameters
    ----------
    curve_row : pd.Series
        Curve snapshot.
    legs : list of float
        Tenors of each leg in years.
    weights : list of float
        Weights aligned with *legs* (e.g. ``[-1, 2, -1]`` for a standard
        butterfly).
    horizon : float
        Holding period in years.
    pct : bool, default True
        Passed through to ``carry``.

    Returns
    -------
    dict with keys ``carry``, ``roll``, ``total``.
    """
    r = sum(w * roll_down(curve_row, t, horizon) for t, w in zip(legs, weights))
    c = sum(w * carry(curve_row, t, horizon, pct=pct) for t, w in zip(legs, weights))
    return {"carry": float(c), "roll": float(r), "total": float(c + r)}


def breakeven(cr: float, dv01: float) -> float:
    """Breakeven yield move = carry+roll (in same units) divided by DV01.

    Parameters
    ----------
    cr : float
        Carry + roll (e.g. in basis points or percent).
    dv01 : float
        Dollar value of a basis point (or unit sensitivity); must be non-zero.

    Returns
    -------
    float
    """
    if dv01 == 0.0:
        raise ZeroDivisionError("dv01 must be non-zero for breakeven calculation.")
    return float(cr / dv01)


def carry_to_vol(cr: float, vol: float) -> float:
    """Carry-to-volatility ratio = carry+roll divided by realised vol.

    Parameters
    ----------
    cr : float
        Carry + roll.
    vol : float
        Realized volatility (annualised or period, caller's choice); non-zero.

    Returns
    -------
    float
    """
    if vol == 0.0:
        raise ZeroDivisionError("vol must be non-zero for carry_to_vol calculation.")
    return float(cr / vol)


# ===========================================================================
# Builder
# ===========================================================================

def make_carry_roll_builder(
    curve_ts: pd.DataFrame,
    *,
    horizon: float,
    interp: str = "cubic",
    pct: bool = True,
):
    """Closure-factory for carry & roll-down time-series over a curve panel.

    Parameters
    ----------
    curve_ts : pd.DataFrame
        Wide DataFrame with DatetimeIndex and float tenor columns; values are
        yields (percent or decimal — consistent with *pct*).
    horizon : float
        Holding period in years applied to every row computation.
    interp : {"linear", "cubic"}
        Interpolation method passed to the module functions.
    pct : bool, default True
        Whether yields are in percent; passed through to ``carry`` /
        ``forward_rate``.

    Returns
    -------
    tuple of six closures:
        ``(roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data)``

        Each of ``roll_ts``, ``carry_ts``, ``total_ts`` accepts a *structure*
        argument:

        - ``("outright", tenor)`` — single tenor.
        - ``("curve", t_short, t_long)`` — long-minus-short spread.
        - ``("fly", [legs], [weights])`` — weighted fly.

        ``breakeven_ts(structure, dv01)`` divides ``total_ts`` by *dv01*.

        ``carry_to_vol_ts(structure, vol_window=60)`` divides ``total_ts`` by
        the rolling realised vol of the structure level.

        ``get_data()`` returns the original *curve_ts* DataFrame.

        The first closure (``roll_ts``) exposes a ``.state`` attribute dict for
        introspection, mirroring the ``fit.state`` pattern in ``pca_rv.py``.
    """
    data = curve_ts.copy()
    # Ensure columns are float
    data.columns = [float(c) for c in data.columns]
    data = data.sort_index()

    state: dict = {
        "curve_ts": data,
        "horizon": horizon,
        "interp": interp,
        "pct": pct,
    }

    # ------------------------------------------------------------------
    # Internal: compute a scalar metric for one row given a structure
    # ------------------------------------------------------------------

    def _row_roll(row: pd.Series, structure) -> float:
        kind = structure[0]
        if kind == "outright":
            _, tenor = structure
            return roll_down(row, float(tenor), state["horizon"], state["interp"])
        elif kind == "curve":
            _, ts, tl = structure
            return (roll_down(row, float(tl), state["horizon"], state["interp"])
                    - roll_down(row, float(ts), state["horizon"], state["interp"]))
        elif kind == "fly":
            _, legs, weights = structure
            return sum(w * roll_down(row, float(t), state["horizon"], state["interp"])
                       for t, w in zip(legs, weights))
        else:
            raise ValueError(f"Unknown structure kind: {kind!r}. Use 'outright', 'curve', or 'fly'.")

    def _row_carry(row: pd.Series, structure) -> float:
        kind = structure[0]
        if kind == "outright":
            _, tenor = structure
            return carry(row, float(tenor), state["horizon"], pct=state["pct"])
        elif kind == "curve":
            _, ts, tl = structure
            return (carry(row, float(tl), state["horizon"], pct=state["pct"])
                    - carry(row, float(ts), state["horizon"], pct=state["pct"]))
        elif kind == "fly":
            _, legs, weights = structure
            return sum(w * carry(row, float(t), state["horizon"], pct=state["pct"])
                       for t, w in zip(legs, weights))
        else:
            raise ValueError(f"Unknown structure kind: {kind!r}.")

    def _level_series(structure) -> pd.Series:
        """The structure's yield level for each date (used for vol computation)."""
        kind = structure[0]
        df = state["curve_ts"]
        if kind == "outright":
            _, tenor = structure
            return df.apply(lambda row: _interp(row, float(tenor), state["interp"]), axis=1)
        elif kind == "curve":
            _, ts, tl = structure
            return (df.apply(lambda row: _interp(row, float(tl), state["interp"]), axis=1)
                    - df.apply(lambda row: _interp(row, float(ts), state["interp"]), axis=1))
        elif kind == "fly":
            _, legs, weights = structure
            acc = None
            for t, w in zip(legs, weights):
                s = w * df.apply(lambda row: _interp(row, float(t), state["interp"]), axis=1)
                acc = s if acc is None else acc + s
            return acc
        else:
            raise ValueError(f"Unknown structure kind: {kind!r}.")

    # ------------------------------------------------------------------
    # Closures
    # ------------------------------------------------------------------

    def roll_ts(structure) -> pd.Series:
        """Roll-down time-series for *structure*.

        Parameters
        ----------
        structure : tuple
            ``("outright", tenor)``, ``("curve", t_short, t_long)``, or
            ``("fly", [legs], [weights])``.

        Returns
        -------
        pd.Series indexed by date.
        """
        df = state["curve_ts"]
        out = df.apply(lambda row: _row_roll(row, structure), axis=1)
        out.name = "roll"
        return out

    def carry_ts(structure) -> pd.Series:
        """Carry time-series for *structure*."""
        df = state["curve_ts"]
        out = df.apply(lambda row: _row_carry(row, structure), axis=1)
        out.name = "carry"
        return out

    def total_ts(structure) -> pd.Series:
        """Total carry+roll time-series for *structure*."""
        r = roll_ts(structure)
        c = carry_ts(structure)
        out = r + c
        out.name = "total"
        return out

    def breakeven_ts(structure, dv01: float) -> pd.Series:
        """Breakeven yield-move time-series = ``total_ts / dv01``."""
        out = total_ts(structure) / dv01
        out.name = "breakeven"
        return out

    def carry_to_vol_ts(structure, vol_window: int = 60) -> pd.Series:
        """Carry-to-volatility time-series = ``total_ts / rolling_vol(structure_level)``."""
        tot = total_ts(structure)
        lvl = _level_series(structure)
        rv = lvl.diff().rolling(int(vol_window)).std()
        out = tot / rv
        out.name = "carry_to_vol"
        return out

    def get_data() -> pd.DataFrame:
        """Return the original curve timeseries DataFrame."""
        return state["curve_ts"]

    # Expose state on the first closure, mirroring pca_rv's `fit.state`
    roll_ts.state = state

    return (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data)
