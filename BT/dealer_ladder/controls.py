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

NY = "America/New_York"


def _stamp_lag_min(handle, ts):
    """Minutes from the curve's OWN stamp to ``ts``. Negative ⟹ the curve is from
    the FUTURE relative to the decision minute. NaT stamp ⟹ NaN (unverifiable)."""
    try:
        meta = handle.meta() if hasattr(handle, "meta") else {}
        ct = pd.Timestamp(meta.get("timestamp"))
    except Exception:
        return np.nan
    if pd.isna(ct):
        return np.nan
    ct = (ct.tz_localize(NY) if ct.tzinfo is None else ct.tz_convert(NY))
    return (pd.Timestamp(ts).tz_convert(NY) - ct).total_seconds() / 60.0


def curve_implied_contract_rates(pricer, curve_name, grid, contracts, *,
                                 require_point_in_time=True,
                                 tolerance_min=0.0) -> pd.DataFrame:
    """Curve-implied rate (bp) per contract per decision minute.

    ``contracts`` is ``[(bucket_key, effective_datetime, maturity_datetime, is_ser)]``
    — the same calendar grid the ladder projects onto, so a basis computed here is
    directly comparable to a ladder bucket.

    A minute whose curve is unavailable yields NaN for that whole row rather than a
    stale carry-forward: a control silently filled with yesterday's curve would
    make the horse race look cleaner than it is.

    POINT-IN-TIME IS VERIFIED, NOT ASSUMED. The decision curve is calibrated from
    Barchart bars selected with ``method="nearest"`` and then ``ffill().bfill()``, so
    a request for a minute the vendor did not cover can legitimately resolve against
    a bar from AFTER it. Nothing about the ladder audits touches this path, because
    the leak is in the CONTROLS, not the signal — and a control carrying future
    information invalidates the horse race in either direction: it can absorb
    variance the signal should have explained, or manufacture a basis reversal that
    looks like the signal was really trading curve-fit error. So each row is checked
    against the handle's own stamp and dropped when that stamp is later than the
    decision minute. The drop and unverifiable counts are attached to ``.attrs`` and
    reported by G3; a row whose stamp cannot be read at all is KEPT and counted,
    because dropping every unverifiable row would silently empty the control panel
    on any pricer that does not expose ``meta()``.
    """
    rows, dropped, unknown = {}, 0, 0
    for ts in pd.DatetimeIndex(grid):
        try:
            handle = pricer.handle(curve_name, ts)
            dense = handle.handle()
        except Exception:
            rows[ts] = {b: np.nan for b, *_ in contracts}
            continue
        if require_point_in_time:
            lag = _stamp_lag_min(handle, ts)
            if pd.isna(lag):
                unknown += 1
            elif lag < -abs(tolerance_min):
                dropped += 1
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
    out = pd.DataFrame(rows).T.sort_index()
    n = max(len(rows), 1)
    out.attrs["future_curve_rows_dropped"] = dropped
    out.attrs["unverifiable_stamp_rows"] = unknown
    out.attrs["future_curve_drop_rate"] = dropped / n
    out.attrs["unverifiable_stamp_rate"] = unknown / n
    if dropped:
        print(f"  point-in-time: dropped {dropped}/{n} "
              f"({dropped / n:.1%}) decision minutes whose {curve_name} curve was "
              f"stamped AFTER the decision")
    return out


def basis_bp(implied_bp: pd.DataFrame, market_bp: pd.DataFrame) -> pd.DataFrame:
    """Swap-futures basis in bp: curve-implied contract rate minus market rate."""
    cols = [c for c in implied_bp.columns if c in market_bp.columns]
    idx = implied_bp.index.intersection(market_bp.index)
    return implied_bp.loc[idx, cols] - market_bp.loc[idx, cols]


def independent_implied_contract_rates(grid, contracts, *, source="citivelo",
                                       curve_name="USD-SOFR-1D") -> pd.DataFrame:
    """Contract rates implied by an INDEPENDENT (swap-quote-derived) curve.

    The point of the circularity gate is that our own basis control is built from the
    very curve that produced the signal, so it cannot by itself separate "the ladder
    forecasts" from "our curve was mispriced against the futures strip and both
    reverted". A basis measured against a curve calibrated from SWAP QUOTES rather
    than the futures strip can: if the ladder's coefficient survives our basis but
    dies against the independent one, the effect was curve-fit error.

    Only meaningful for SR3 (both independent sources are USD SOFR curves), and it
    inherits the source's coverage holes -- notably Friday afternoons for citivelo,
    where its reader silently returns the last snapshot. Those minutes come back NaN
    here rather than stale, via the staleness check below.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from SDRUtils.stir_flow.pricing import CurvePricer

    pricer = CurvePricer(mdp=IRSwapsMDP(source=source))
    out = curve_implied_contract_rates(pricer, curve_name, grid, contracts)
    # blank out minutes the independent source did not actually cover
    stale = _independent_staleness_min(pricer, curve_name, grid)
    if stale is not None:
        attrs = dict(out.attrs)
        mask = stale.abs() <= 5.0
        out = out.where(mask.reindex(out.index).to_numpy()[:, None])
        out.attrs.update(attrs)          # .where does not reliably carry attrs
    return out


def _independent_staleness_min(pricer, curve_name, grid):
    """Minutes between each decision minute and the independent curve's own stamp."""
    vals = []
    for ts in pd.DatetimeIndex(grid):
        try:
            vals.append(_stamp_lag_min(pricer.handle(curve_name, ts), ts))
        except Exception:
            vals.append(np.nan)
    return pd.Series(vals, index=pd.DatetimeIndex(grid))


def signed_basis_dv01(basis: pd.DataFrame, ladder_level: pd.DataFrame) -> pd.DataFrame:
    """``sign(basis) * |ladder|`` — the audit's explicit control.

    Included because a strategy that is really "trade the basis, sized by how much
    flow happened" would load on exactly this and on nothing else.
    """
    cols = [c for c in basis.columns if c in ladder_level.columns]
    idx = basis.index.intersection(ladder_level.index)
    return np.sign(basis.loc[idx, cols]) * ladder_level.loc[idx, cols].abs()


def curve_shape(rates_bp: pd.DataFrame, *, front_rank=None) -> pd.DataFrame:
    """Level / slope / curvature of the futures strip itself, per minute.

    Uses the strip rather than the swap curve so the controls live in the same space
    as the target and need no extra curve reads.

    Shape points are chosen PER MINUTE from the front-rank panel, not by column
    position. Positional picks over a window-union panel select whichever contract
    happens to sit first, middle and last in the column list -- which over a six-month
    window means the front pick is a contract that EXPIRES mid-window (NaN for the
    tail) and the back pick is the most deferred, whose minute coverage is far below
    the front six's. Both make slope and curvature structurally NaN for long stretches,
    and every such row then drops out of the controlled regression.

    Falls back to positional picks when no rank panel is supplied.
    """
    cols = list(rates_bp.columns)
    if len(cols) < 3:
        return pd.DataFrame(index=rates_bp.index)

    if front_rank is None or not len(front_rank):
        belly = len(cols) // 2
        f, m, b = rates_bp[cols[0]], rates_bp[cols[belly]], rates_bp[cols[-1]]
        level = rates_bp.mean(axis=1)
    else:
        rank = front_rank.reindex(index=rates_bp.index, columns=cols)
        n = int(np.nanmax(rank.to_numpy())) if np.isfinite(
            np.nanmax(rank.to_numpy())) else 0
        if n < 3:
            belly = len(cols) // 2
            f, m, b = rates_bp[cols[0]], rates_bp[cols[belly]], rates_bp[cols[-1]]
            level = rates_bp.mean(axis=1)
        else:
            mid = (n + 1) // 2

            def at_rank(k):
                pick = rank.eq(float(k))
                return rates_bp.where(pick).mean(axis=1)

            f, m, b = at_rank(1), at_rank(mid), at_rank(n)
            level = rates_bp.where(rank.notna()).mean(axis=1)
    return pd.DataFrame({
        "level_bp": level,
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


def front_rank_panel(grid, space, n_front, count=16) -> pd.DataFrame:
    """Per (minute, contract) front-rank, NaN when the contract is outside the front N.

    WHY THIS IS NEEDED. The ladder keys buckets on ABSOLUTE contracts, deliberately —
    persisting rank-keyed vectors would smear buckets across roll dates. But a
    research basket defined as "the front six" is a RANK statement, and over a
    six-month window the absolute contracts behind that rank change: as of
    2026-01-12 the SR3 front six is SFRH26..SFRM27, and by 2026-06-18 SFRH26 has
    expired and the front six is SFRU26..SFRZ27. Freezing the basket at the window
    start would therefore spend the last weeks trading a contract that no longer
    exists and would never appear in the ladder, and freezing it at the window END
    would silently look ahead.

    So the rank is recomputed per session from the same calendar the ladder uses,
    and the research masks its signal to the front N as of each date. This is the
    "rank views are derived at read time" the design spec calls for.
    """
    from SDRUtils.stir_flow.ladder import FUTURES_SPACE_SPEC, contract_grid

    root = FUTURES_SPACE_SPEC[space][0]
    idx = pd.DatetimeIndex(grid)
    et = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    days = pd.Series(et.date, index=idx)
    ranks = {}
    for day in pd.unique(days):
        for rank, (bucket, _eff, _mat) in enumerate(contract_grid(day, root, count)):
            ranks.setdefault(bucket, pd.Series(np.nan, index=idx))
            if rank < n_front:
                ranks[bucket][(days == day).to_numpy()] = float(rank + 1)
    return pd.DataFrame(ranks, index=idx) if ranks else pd.DataFrame(index=idx)


def window_contract_union(window, space, n_front, count=16) -> list:
    """Every contract that is in the front ``n_front`` on ANY session of the window.

    The set the target loader must fetch: a superset of every date's basket, so the
    per-date mask can then narrow it without a second vendor round trip.
    """
    from SDRUtils.stir_flow.ladder import FUTURES_SPACE_SPEC, contract_grid

    root, is_ser = FUTURES_SPACE_SPEC[space]
    start, end = (window if isinstance(window, tuple) else (window.start, window.end))
    seen, out = set(), []
    for day in pd.bdate_range(start, end):
        for bucket, eff, mat in contract_grid(day.date(), root, count)[:n_front]:
            if bucket not in seen:
                seen.add(bucket)
                out.append((bucket, eff, mat, is_ser))
    return out


def block_share_panel(prints: pd.DataFrame, grid, *, space="FUTURES",
                      half_lives=None, buckets=None) -> pd.DataFrame:
    """Share of the decayed |DV01| in each bucket coming from BLOCK prints.

    A conditioning split the audit asks for by name. It matters because blocks carry
    a longer legal delay and a longer assumed half-life, so a result driven entirely
    by block-heavy buckets is a result about a different (slower, more delayed)
    information channel than one driven by ordinary prints.
    """
    from BT.dealer_ladder import signals

    blocks = prints[prints["is_block"].fillna(False).astype(bool)]
    total = signals.print_intensity_panel(prints, grid, space=space,
                                          half_lives=half_lives)
    if buckets is not None:
        total = total.reindex(columns=buckets)
    if blocks.empty:
        return pd.DataFrame(0.0, index=total.index, columns=total.columns)
    blk = signals.print_intensity_panel(blocks, grid, space=space,
                                        half_lives=half_lives)
    blk = blk.reindex(index=total.index, columns=total.columns).fillna(0.0)
    return (blk / total.replace(0.0, np.nan)).fillna(0.0)


def funding_regime_series(grid):
    """Daily funding-regime label and SOFR-EFFR spread, broadcast to the grid.

    Reuses ``BT/serff/data.build_panel`` rather than rebuilding: it already carries
    the daily SOFR-EFFR spread in bp, H.4.1 reserves/RRP/TGA and five named funding
    regimes. Returns ``(regime_label, sofr_effr_bp)``, both indexed by the grid, or
    ``(None, None)`` if the panel is unavailable -- a missing conditioner must not
    take the gate down.
    """
    idx = pd.DatetimeIndex(grid)
    try:
        from BT.serff import data as serff_data

        panel = serff_data.build_panel()
    except Exception:
        return None, None
    if panel is None or not len(panel):
        return None, None
    et = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    day = pd.DatetimeIndex(pd.to_datetime(pd.Series(et.date)))
    p = panel.copy()
    p.index = pd.DatetimeIndex(p.index).tz_localize(None).normalize()
    regime_col = next((c for c in p.columns if "regime" in str(c).lower()), None)
    spread_col = next((c for c in p.columns
                       if "sofr" in str(c).lower() and "effr" in str(c).lower()), None)
    regime = (p[regime_col].reindex(day).to_numpy() if regime_col else None)
    spread = (p[spread_col].reindex(day).to_numpy() if spread_col else None)
    return (pd.Series(regime, index=idx) if regime is not None else None,
            pd.Series(spread, index=idx) if spread is not None else None)


def build_control_panels(*, rates_bp, volumes, implied_bp, ladder_level,
                         contracts, grid, independent_implied_bp=None,
                         block_share=None, front_rank=None) -> dict:
    """Every per-(minute, bucket) control, as a dict of panels ready for ``align_long``."""
    b = basis_bp(implied_bp, rates_bp)
    shape = curve_shape(rates_bp, front_rank=front_rank)
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
    if independent_implied_bp is not None and len(independent_implied_bp):
        ib = basis_bp(independent_implied_bp, rates_bp)
        panels["indep_basis_bp"] = ib
        panels["abs_indep_basis_bp"] = ib.abs()
    if block_share is not None and len(block_share):
        panels["block_share"] = block_share.reindex(
            index=rates_bp.index, columns=rates_bp.columns)
    # broadcast the per-minute (bucket-invariant) series across buckets
    regime, sofr_effr = funding_regime_series(grid)
    for name, series in (("level_bp", shape.get("level_bp")),
                         ("slope_bp", shape.get("slope_bp")),
                         ("curvature_bp", shape.get("curvature_bp")),
                         ("tod_min", tod), ("days_to_fomc", fomc),
                         ("sofr_effr_bp", sofr_effr)):
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

# The independent (swap-quote-derived) basis is kept OUT of DEFAULT_CONTROLS on
# purpose: it exists to be added in a SECOND horse race, so the report can show
# whether the ladder survives our own basis and then whether it also survives a basis
# our curve did not produce. Folding both into one regression would confound the two
# questions and, since the two bases are highly collinear, would inflate both SEs.
INDEPENDENT_CONTROLS = ("indep_basis_bp", "abs_indep_basis_bp")
# Conditioning splits -- reported as strata, not as regressors.
CONDITIONING_PANELS = ("block_share", "level_prox_bp", "realized_vol_bp", "amihud")
CONDITIONING_SERIES = ("sofr_effr_bp", "days_to_fomc", "tod_min")
