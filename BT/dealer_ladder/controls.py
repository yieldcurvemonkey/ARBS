"""Conditioning and control panels for G3's matched-basis horse race.

The circularity worry is concrete: the ladder is built on a curve calibrated from
the SAME futures strip the study then tries to predict. So an apparent forecast can
be contemporaneous basis marking or curve-fit error rather than anything about
dealer hedging. Neutralising that needs the basis itself, plus curve shape,
momentum, volatility, liquidity, time of day, roll and FOMC proximity, in the
regression alongside the ladder.

Two design choices worth stating.

**The basis is computed per decision minute from the decision-time curve.** Not
approximated, not carried from a daily mark. For each contract, the curve-implied
contract rate comes from ``build_stirf`` on that minute's dense curve and the
market rate from the futures bar, so ``basis = implied - market`` is exactly the
quantity that would make the ladder circular. With the CurveStore warmed each read
is a local Parquet hit, which is what makes ~13,000 grid points affordable.

**Liquidity is contract-native.** The obvious candidate,
``arbs_stir_tick_size_v1.amihud``, is keyed by SWAP tenor bucket (`FOMC_JUL26`,
`2Y`) and mapping those onto futures contracts would be a guess. A futures Amihud
built from the contract's own minute bars measures the same thing without the
mapping, and is available for every contract-minute the target exists at.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def curve_implied_contract_rates(pricer, curve_name, grid, contracts) -> pd.DataFrame:
    """Curve-implied rate (bp) per contract per decision minute.

    ``contracts`` is ``[(bucket_key, effective_datetime, maturity_datetime, is_ser)]``
    — the same calendar grid the ladder projects onto, so a basis computed here is
    directly comparable to a ladder bucket.

    A minute whose curve is unavailable yields NaN for that whole row rather than a
    stale carry-forward: a control silently filled with yesterday's curve would
    make the horse race look cleaner than it is.
    """
    rows = {}
    for ts in pd.DatetimeIndex(grid):
        try:
            handle = pricer.handle(curve_name, ts)
            dense = handle.handle()
        except Exception:
            rows[ts] = {b: np.nan for b, *_ in contracts}
            continue
        fixings = handle.index()
        ref = pd.Timestamp(handle.reference_date())
        vals = {}
        for bucket, eff, mat, is_ser in contracts:
            # Fixings are only needed when the accrual period STARTS before the
            # curve's reference date -- true for the front monthly (ZQ) contract and
            # essentially never for a quarterly IMM one. Passing them anyway costs a
            # business-day mask over the full ~6,500-row fixings index per
            # instrument per minute, which across 12 contracts x ~13,000 decisions
            # dominates this loop.
            needs_fixings = pd.Timestamp(eff) < ref
            try:
                stirf = handle.build_stirf(
                    effective_date=eff, maturity_date=mat, is_ser=is_ser,
                    fixings=fixings if needs_fixings else None)
                vals[bucket] = float(stirf.rate(curves=dense).real) * 100.0
            except Exception:
                vals[bucket] = np.nan
        rows[ts] = vals
    return pd.DataFrame(rows).T.sort_index()


def basis_bp(implied_bp: pd.DataFrame, market_bp: pd.DataFrame) -> pd.DataFrame:
    """Swap-futures basis in bp: curve-implied contract rate minus market rate."""
    cols = [c for c in implied_bp.columns if c in market_bp.columns]
    idx = implied_bp.index.intersection(market_bp.index)
    return implied_bp.loc[idx, cols] - market_bp.loc[idx, cols]


def signed_basis_dv01(basis: pd.DataFrame, ladder_level: pd.DataFrame) -> pd.DataFrame:
    """``sign(basis) * |ladder|`` — the audit's explicit control.

    Included because a strategy that is really "trade the basis, sized by how much
    flow happened" would load on exactly this and on nothing else.
    """
    cols = [c for c in basis.columns if c in ladder_level.columns]
    idx = basis.index.intersection(ladder_level.index)
    return np.sign(basis.loc[idx, cols]) * ladder_level.loc[idx, cols].abs()


def curve_shape(rates_bp: pd.DataFrame, *, front=0, belly=None, back=-1) -> pd.DataFrame:
    """Level / slope / curvature of the futures strip itself, per minute.

    Uses the strip rather than the swap curve so the controls live in the same
    space as the target and need no extra curve reads.
    """
    cols = list(rates_bp.columns)
    if len(cols) < 3:
        return pd.DataFrame(index=rates_bp.index)
    belly = belly if belly is not None else len(cols) // 2
    f, m, b = rates_bp[cols[front]], rates_bp[cols[belly]], rates_bp[cols[back]]
    return pd.DataFrame({
        "level_bp": rates_bp.mean(axis=1),
        "slope_bp": b - f,
        "curvature_bp": 2.0 * m - f - b,
    }, index=rates_bp.index)


def trailing_return_bp(rates_bp: pd.DataFrame, lookback_min=60) -> pd.DataFrame:
    """Realised change over the PRECEDING ``lookback_min`` — momentum, not lookahead."""
    prior = rates_bp.shift(freq=pd.Timedelta(minutes=lookback_min)).reindex(rates_bp.index)
    return rates_bp - prior


def realized_vol_bp(rates_bp: pd.DataFrame, window_min=60, step_min=5) -> pd.DataFrame:
    """Rolling stdev of ``step_min`` rate changes over a trailing window, in bp.

    Shifted by one step so the value at ``t`` uses only changes completed strictly
    before ``t``.
    """
    steps = max(int(window_min // step_min), 2)
    diffs = rates_bp.diff()
    return diffs.rolling(steps, min_periods=max(steps // 2, 2)).std().shift(1)


def futures_amihud(rates_bp: pd.DataFrame, volumes: pd.DataFrame,
                   window_min=60) -> pd.DataFrame:
    """Contract-native Amihud: |rate change| per contract traded, trailing.

    Same construction as the tick table's Amihud (price impact per unit of traded
    size) but keyed on the futures contract, avoiding a guessed mapping from swap
    tenor buckets onto contracts. Shifted one step so it is knowable at ``t``.
    """
    cols = [c for c in rates_bp.columns if c in volumes.columns]
    absmove = rates_bp[cols].diff().abs().rolling(window_min, min_periods=5).sum()
    vol = volumes[cols].rolling(window_min, min_periods=5).sum()
    return (absmove / vol.replace(0.0, np.nan)).shift(1)


def time_of_day_min(grid) -> pd.Series:
    """Minutes since 00:00 ET — the plainest time-of-day control."""
    idx = pd.DatetimeIndex(grid)
    et = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    return pd.Series(et.hour * 60 + et.minute, index=idx, dtype=float)


def days_to_expiry(grid, contracts) -> pd.DataFrame:
    """Calendar days from each decision minute to each contract's maturity — the roll control."""
    idx = pd.DatetimeIndex(grid)
    et = (idx.tz_convert("America/New_York") if idx.tz is not None else idx)
    day = pd.Series(et.date, index=idx)
    out = {}
    for bucket, _eff, mat, *_ in contracts:
        m = pd.Timestamp(mat).date()
        out[bucket] = day.map(lambda d, m=m: (m - d).days).astype(float)
    return pd.DataFrame(out, index=idx)


def days_to_next_fomc(grid) -> pd.Series:
    """Business days to the next FOMC announcement, reusing the repo's helper.

    Point-in-time safe: the helper reads a fixed announcement calendar, not a
    curve, so unlike ``SDRUtils/analytics/fomc.py`` it carries no ``date.today()``
    anchor. Returns NaN past the end of that calendar instead of the helper's 999
    sentinel, so a regression cannot silently treat "unknown" as "very far away".
    """
    from BT.signals.sfr_fly_triggers import days_to_next_fomc as _dtn

    idx = pd.DatetimeIndex(grid)
    et = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    vals = [float(_dtn(pd.Timestamp(t).to_pydatetime())) for t in et]
    s = pd.Series(vals, index=idx)
    return s.where(s < 900.0)


def level_proximity_bp(implied_bp: pd.DataFrame, *, grid_bp=25.0) -> pd.DataFrame:
    """Distance in bp to the nearest point on the 25bp policy grid.

    Written here because the repo has NO structural-grid implementation — it exists
    only as spec prose, and ``classify_meeting_proximity`` measures meeting COUNT
    distance, not distance in rate space. Signed so the direction of approach is
    preserved: positive means the implied rate sits above the nearest grid point.

    The grid is anchored on multiples of ``grid_bp`` in absolute rate space, which
    is the right anchor for policy-dated contracts whose settlement pins to
    realised policy increments.
    """
    nearest = (implied_bp / grid_bp).round() * grid_bp
    return implied_bp - nearest


def build_control_panels(*, rates_bp, volumes, implied_bp, ladder_level,
                         contracts, grid) -> dict:
    """Every per-(minute, bucket) control, as a dict of panels ready for ``align_long``."""
    b = basis_bp(implied_bp, rates_bp)
    shape = curve_shape(rates_bp)
    tod = time_of_day_min(grid)
    fomc = days_to_next_fomc(grid)
    panels = {
        "basis_bp": b,
        "abs_basis_bp": b.abs(),
        "signed_basis_dv01": signed_basis_dv01(b, ladder_level),
        "trailing_60m_bp": trailing_return_bp(rates_bp, 60),
        "realized_vol_bp": realized_vol_bp(rates_bp),
        "amihud": futures_amihud(rates_bp, volumes),
        "days_to_expiry": days_to_expiry(grid, contracts),
        "level_prox_bp": level_proximity_bp(implied_bp),
    }
    # broadcast the per-minute (bucket-invariant) series across buckets
    for name, series in (("level_bp", shape.get("level_bp")),
                         ("slope_bp", shape.get("slope_bp")),
                         ("curvature_bp", shape.get("curvature_bp")),
                         ("tod_min", tod), ("days_to_fomc", fomc)):
        if series is None:
            continue
        panels[name] = pd.DataFrame(
            {c: series.reindex(rates_bp.index) for c in rates_bp.columns},
            index=rates_bp.index)
    return panels


DEFAULT_CONTROLS = (
    "basis_bp", "abs_basis_bp", "signed_basis_dv01", "level_bp", "slope_bp",
    "curvature_bp", "trailing_60m_bp", "realized_vol_bp", "amihud",
    "tod_min", "days_to_expiry", "days_to_fomc",
)
