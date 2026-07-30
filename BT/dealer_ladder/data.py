"""Read-time loaders for the dealer-ladder study.

Everything here is READ-ONLY against the prod DB. The study never writes.

Two things this module exists to get right, because both are easy to get wrong
silently:

**The venue gate.** ``venue_status`` is not wired into any production path — its
only caller in the repo is a diagnostic script — so ``arbs_stir_direction_v1`` and
``arbs_stir_ladder_prints_v1`` both contain ``VENUE_UNKNOWN`` units. The only gate
actually enforced upstream is ``l.venue = 'D2C'``, which merely means "platform is
not one of the six IDB codes" and lets a NULL platform through. So a signed
research universe has to apply the whitelist itself, which means re-joining
``platform_identifier`` from the tape — the ladder table does not carry it.

**The anchor-leg join.** For OUTRIGHT units ``unit_key == trade_id``, but the leg
row still carries a non-NULL ``package_id`` (the FK is NOT NULL, so single-leg
trades get a synthetic package). ``COALESCE(package_id, trade_id)`` is therefore
the WRONG way to rebuild ``unit_key``; you must branch on
``direction.package_id IS NULL``. For package units the anchor leg is the earliest
``(expiration_date, effective_date, trade_id)`` — all THREE keys, matching
``build_units``; the diagnostic script sorts on only two and can pick a different
leg when maturities tie.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import DIRECTION_TABLE
from SDRUtils._swappulse_scripts._stir_ladder_schema_v1 import (
    BOOK_MARKS_TABLE, LADDER_PRINTS_TABLE,
)
from SDRUtils.stir_flow.trade_selection import venue_status

from BT.dealer_ladder import config as cfg


def connect(pg_url=None):
    """Read-only psycopg2 connection to the tape/flow DB."""
    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    return psycopg2.connect(pg_url or resolve_pg_url())


# --------------------------------------------------------------------------
# ladder prints + direction metadata
# --------------------------------------------------------------------------
_PRINTS_SQL = f"""
SELECT p.unit_key, p.bucket_space, p.bucket_key, p.delta_dv01, p.as_of_date,
       p.execution_timestamp, p.visibility_timestamp, p.p_flip,
       p.direction_confidence, p.curve_suspect_trade, p.is_block, p.dv01,
       p.code_vintage,
       d.trade_id, d.package_id, d.trade_type, d.rate_index_clean,
       d.classification_method, d.dealer_direction, d.is_off_market,
       d.structure_dv01, d.spread_to_mid_bps, d.dealer_charge_bps,
       d.tenor_bucket, d.dv01_bucket, d.notional
FROM {LADDER_PRINTS_TABLE} p
JOIN {DIRECTION_TABLE} d USING (unit_key)
WHERE p.as_of_date BETWEEN %(start)s AND %(end)s
"""

_OUTRIGHT_PLATFORM_SQL = """
SELECT trade_id AS unit_key, platform_identifier, cleared, is_capped
FROM arbs_usd_swap_tape_legs_v2
WHERE trade_id = ANY(%(ids)s)
"""

_PKG_PLATFORM_SQL = """
SELECT package_id, platform_identifier, cleared, is_capped,
       expiration_date, effective_date, trade_id
FROM arbs_usd_swap_tape_legs_v2
WHERE package_id = ANY(%(ids)s)
"""


def load_platform_meta(conn, keys: pd.DataFrame) -> pd.DataFrame:
    """One (platform_identifier, cleared, is_capped) row per unit_key.

    ``keys`` needs ``unit_key`` and ``package_id``. Branches on ``package_id``
    being null, exactly as the two SQL statements require, and takes the anchor
    leg by the three-key sort for packages.
    """
    cols = ["unit_key", "platform_identifier", "cleared", "is_capped"]
    outright = sorted(keys.loc[keys["package_id"].isna(), "unit_key"]
                      .dropna().astype(str).unique().tolist())
    pkg = sorted(keys.loc[keys["package_id"].notna(), "package_id"]
                 .dropna().astype(str).unique().tolist())
    frames = []
    if outright:
        df = pd.read_sql(_OUTRIGHT_PLATFORM_SQL, conn, params={"ids": outright})
        frames.append(df.drop_duplicates(subset=["unit_key"], keep="first")[cols])
    if pkg:
        raw = pd.read_sql(_PKG_PLATFORM_SQL, conn, params={"ids": pkg})
        if not raw.empty:
            raw = raw.sort_values(["package_id", "expiration_date",
                                   "effective_date", "trade_id"])
            anchor = raw.groupby("package_id", as_index=False).first()
            frames.append(anchor.rename(columns={"package_id": "unit_key"})[cols])
    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True).drop_duplicates("unit_key", keep="first")


def attach_strata(prints: pd.DataFrame, platform: pd.DataFrame) -> pd.DataFrame:
    """Add venue / curve / market / vintage strata columns."""
    out = prints.merge(platform, on="unit_key", how="left")
    out["venue_bucket"] = out["platform_identifier"].apply(venue_status)
    out["curve_bucket"] = np.where(out["curve_suspect_trade"].fillna(False).astype(bool),
                                   "CURVE_SUSPECT", "CURVE_CLEAN")
    out["market_bucket"] = np.where(out["is_off_market"].fillna(False).astype(bool),
                                    "OFF_MARKET", "ON_MARKET")
    # p_flip arrives as numeric NaN (not NULL) for a large minority; make the
    # missingness explicit so its share can be reported rather than absorbed.
    out["has_p_flip"] = pd.to_numeric(out["p_flip"], errors="coerce").notna()
    return out


def load_prints(conn, window, universe=None, *, space=None) -> pd.DataFrame:
    """Ladder prints for ``window``, enriched and filtered to the signed universe.

    Returns EVERY row when ``universe`` is None, which is what the provenance
    diagnostics need — the filtering is a separate, inspectable step.
    """
    start, end = (window if isinstance(window, tuple)
                  else (window.start, window.end))
    prints = pd.read_sql(_PRINTS_SQL, conn, params={"start": start, "end": end})
    if prints.empty:
        return prints
    platform = load_platform_meta(conn, prints[["unit_key", "package_id"]].drop_duplicates())
    prints = attach_strata(prints, platform)
    if space is not None:
        prints = prints[prints["bucket_space"] == space]
    if universe is not None:
        prints = apply_universe(prints, universe)
    return prints.reset_index(drop=True)


def apply_universe(prints: pd.DataFrame, universe) -> pd.DataFrame:
    """Filter to the signed universe. Kept separate so exclusions can be counted."""
    df = prints
    if universe.directions:
        df = df[df["dealer_direction"].isin(universe.directions)]
    if universe.methods:
        df = df[df["classification_method"].isin(universe.methods)]
    if cfg.EXCLUDED_METHODS:
        df = df[~df["classification_method"].isin(cfg.EXCLUDED_METHODS)]
    if universe.exclude_curve_suspect:
        df = df[df["curve_bucket"] == "CURVE_CLEAN"]
    if universe.require_whitelisted_venue:
        df = df[df["venue_bucket"] == "D2C_WHITELISTED"]
    if universe.code_vintage is not None:
        df = df[df["code_vintage"] == universe.code_vintage]
    return df


def exclusion_ladder(prints: pd.DataFrame, universe) -> pd.DataFrame:
    """How many units each successive filter removes — the G0 provenance table.

    Applied cumulatively in a FIXED order, each row labelled with the filter it
    APPLIES. A single "N units survived" line hides which gate did the work, and
    which gate did the work is the interesting part: the venue whitelist removes
    only ~10% while curve-suspect exclusion removes ~40%.
    """
    gates = [
        ("direction in PAID/RECEIVED",
         lambda d: d[d["dealer_direction"].isin(universe.directions)]),
        ("classification method in universe",
         lambda d: d[d["classification_method"].isin(universe.methods)]),
        ("TICK_RULE excluded",
         lambda d: d[~d["classification_method"].isin(cfg.EXCLUDED_METHODS)]),
        ("curve-clean only",
         (lambda d: d[d["curve_bucket"] == "CURVE_CLEAN"])
         if universe.exclude_curve_suspect else (lambda d: d)),
        ("whitelisted D2C venue only",
         (lambda d: d[d["venue_bucket"] == "D2C_WHITELISTED"])
         if universe.require_whitelisted_venue else (lambda d: d)),
        ("single code vintage",
         (lambda d: d[d["code_vintage"] == universe.code_vintage])
         if universe.code_vintage is not None else (lambda d: d)),
    ]
    rows = [{"step": "start: all projected prints", "units": prints["unit_key"].nunique(),
             "removed": 0}]
    df = prints
    for label, fn in gates:
        before = df["unit_key"].nunique()
        df = fn(df)
        after = df["unit_key"].nunique()
        rows.append({"step": label, "units": after, "removed": before - after})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# book marks
# --------------------------------------------------------------------------
def load_marks(conn, window, kind=None) -> pd.DataFrame:
    start, end = (window if isinstance(window, tuple) else (window.start, window.end))
    sql = (f"SELECT unit_key, mark_ts, mark_kind, npv_usd, pnl_since_entry_usd, "
           f"curve_name, code_vintage FROM {BOOK_MARKS_TABLE} "
           "WHERE (mark_ts AT TIME ZONE 'America/New_York')::date "
           "BETWEEN %(start)s AND %(end)s")
    params = {"start": start, "end": end}
    if kind:
        sql += " AND mark_kind = %(kind)s"
        params["kind"] = kind
    return pd.read_sql(sql, conn, params=params)


# --------------------------------------------------------------------------
# decision grid
# --------------------------------------------------------------------------
def decision_grid(dates, signal_cfg) -> pd.DatetimeIndex:
    """Intraday decision timestamps, tz-aware ET, for the given session dates.

    Every point is a genuine decision instant: the grid is built from the session
    window, NOT from print times, so a session with no flow still contributes
    decisions (and therefore contributes to the placebo and no-lookahead audits).
    """
    out = []
    for d in pd.to_datetime(pd.Series(list(dates))).dt.date.unique():
        day = pd.Timestamp(d)
        lo = day + pd.Timedelta(hours=signal_cfg.session_start_hour)
        hi = day + pd.Timedelta(hours=signal_cfg.session_end_hour)
        out.append(pd.date_range(lo, hi, freq=f"{signal_cfg.grid_minutes}min",
                                 inclusive="left"))
    if not out:
        return pd.DatetimeIndex([], tz="America/New_York")
    idx = out[0].append(out[1:]) if len(out) > 1 else out[0]
    return idx.tz_localize("America/New_York")


def trading_days(window) -> pd.DatetimeIndex:
    """US business days in the window, federal holidays removed."""
    from pandas.tseries.holiday import USFederalHolidayCalendar

    start, end = (window if isinstance(window, tuple) else (window.start, window.end))
    days = pd.bdate_range(start, end)
    hol = USFederalHolidayCalendar().holidays(start=days.min(), end=days.max())
    return days[~days.isin(hol)]


# --------------------------------------------------------------------------
# the TARGET side: futures minute bars
# --------------------------------------------------------------------------
# There is exactly one real intraday bar source in the repo: Barchart's
# queryminutes endpoint, wrapped by BarchartFetcher.barchart_timeseries_api with
# interval=1. It returns full OHLCV and volume IS in CONTRACTS. Two things follow:
#
# 1. The Query/TimeseriesBuilder/MDP stack CANNOT carry volume -- STIRFutureValue
#    has RATE/NPV/PRICE/PV01/DV01/OPEN_INTEREST and no VOLUME member -- so volume
#    has to come from the fetcher directly.
# 2. There is NO trade-level data anywhere. The only sub-bar feed is
#    get_historical_bid_offer_quotes (quote updates: bid/offer price and size, no
#    trade prints). A true Lee-Ready signing is therefore IMPOSSIBLE here, and
#    G2's "signed aggressive flow" has to use the bar-direction proxy below. That
#    is a real weakening of the mechanism test and is reported as such.
#
# Symbols: the fetcher maps SR3/SFR/SQ -> SQ, SR1/SER/SL -> SL, ZQ/FF -> ZQ, so
# passing our bucket keys works, but the RETURNED keys are Barchart's ("SQU26"),
# which is why every read here maps them back.
def _to_barchart(symbols):
    from MDP.STIRFutures.STIRFutureMDP import _normalize_symbol, _to_barchart_symbol

    return [_to_barchart_symbol(_normalize_symbol(s) or s) for s in symbols]


def _from_barchart(columns):
    from MDP.STIRFutures.STIRFutureMDP import _from_barchart_symbol

    return [_from_barchart_symbol(c) for c in columns]


def bucket_to_cme(bucket_key: str) -> str:
    """Ladder bucket key -> CME symbol: 'SFRU26' -> 'SR3U26', 'FFN26' -> 'ZQN26'."""
    from MDP.STIRFutures.STIRFutureMDP import _normalize_symbol

    return _normalize_symbol(bucket_key) or bucket_key


def cme_to_bucket(cme_symbol: str) -> str:
    """CME symbol -> ladder bucket key: 'SR3U26' -> 'SFRU26', 'ZQN26' -> 'FFN26'.

    The ladder keys its buckets on Bloomberg-style roots (what ``bbg_id()``
    returns), while the Barchart fetcher round-trips to CME roots. Every join
    between the signal and the target crosses this boundary, so it gets one
    function rather than being inlined.
    """
    from SDRUtils.stir_flow.ladder import CME_TO_BBG

    s = str(cme_symbol).upper().strip()
    for cme_root, bbg_root in CME_TO_BBG.items():
        if s.startswith(cme_root):
            return f"{bbg_root}{s[len(cme_root):]}"
    return s


def load_futures_minutes(symbols, start, end, *, fields=("Close", "Volume"),
                         show_tqdm=False) -> dict:
    """Minute bars per contract over [start, end]. Returns {field: wide DataFrame}.

    ``start``/``end`` MUST be tz-aware — the fetcher raises on naive bounds, and
    the returned index is tz-converted to whatever tz they carry (bars are parsed
    as America/Chicago internally). Pass ET bounds to get an ET index. Columns come
    back as ladder-style symbols, not Barchart's.

    Uses the per-symbol return (``one_df=False``) and pivots here rather than
    asking the fetcher to merge. Two reasons: its ``one_df=True`` merge silently
    returned an EMPTY frame for the ZQ strip while the same symbols returned
    99-197 bars each individually; and one call yields every field at once instead
    of one call per field, which matters against a 55-request-per-minute quota.
    """
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    if pd.Timestamp(start).tzinfo is None or pd.Timestamp(end).tzinfo is None:
        raise ValueError("start/end must be tz-aware (the Barchart fetcher requires it)")
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=8)
    per_symbol = fetcher.barchart_timeseries_api(
        barchart_symbols=_to_barchart(symbols), start_date=start, end_date=end,
        interval=1, one_df=False, show_tqdm=show_tqdm,
    ) or {}

    out = {f: {} for f in fields}
    for bc_sym, frame in per_symbol.items():
        if frame is None or not len(frame):
            continue
        # columns are LADDER BUCKET KEYS, because that is what every join needs
        name = cme_to_bucket(_from_barchart([bc_sym])[0])
        for f in fields:
            if f in frame.columns:
                out[f][name] = frame[f].astype(float)
    result = {}
    for f in fields:
        cols = out[f]
        result[f] = (pd.DataFrame(cols).sort_index() if cols else pd.DataFrame())
    return result


def to_minute_grid(df: pd.DataFrame, *, ffill_limit_min=30):
    """Reindex sparse bars onto a complete 1-minute grid per ET session.

    Returns ``(gridded, staleness_min)``. Necessary because these contracts do not
    print every minute: on 2026-07-10 the SR3 front six had 409-493 bars out of
    639 minutes, and the ZQ front six had only 99-197. An exact-timestamp forward
    shift over data that sparse resolves almost nothing — measured 8% of ZQ
    60-minute horizons — so a horizon has to be evaluated against the last KNOWN
    price, which is also the honest answer to "what could you have transacted
    near at that moment".

    Forward-fill never crosses a session date, and is capped at
    ``ffill_limit_min``: beyond that the last print is too old to stand in for a
    price. ``staleness_min`` is returned so a study can condition on, or exclude,
    stale points rather than having staleness invisibly inflate its sample.
    """
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    idx = pd.DatetimeIndex(df.index)
    tz = idx.tz
    full = []
    for day, chunk in df.groupby(idx.tz_convert("America/New_York").date
                                 if tz is not None else idx.date):
        lo, hi = chunk.index.min(), chunk.index.max()
        full.append(pd.date_range(lo, hi, freq="1min"))
    grid = full[0].append(full[1:]) if len(full) > 1 else full[0]
    grid = pd.DatetimeIndex(grid).unique().sort_values()

    on_grid = df.reindex(grid)
    session = pd.Series(
        (grid.tz_convert("America/New_York") if tz is not None else grid).date,
        index=grid)
    filled = on_grid.groupby(session).ffill(limit=ffill_limit_min)

    # minutes since the last TRUE observation, per column
    obs = on_grid.notna()
    stale = pd.DataFrame(index=grid, columns=df.columns, dtype=float)
    for col in df.columns:
        seen = obs[col]
        last = pd.Series(np.where(seen, np.arange(len(grid)), np.nan),
                         index=grid).groupby(session).ffill()
        stale[col] = np.arange(len(grid)) - last
    stale = stale.where(filled.notna())
    return filled, stale


def to_grid_sum(minute_df: pd.DataFrame, grid) -> pd.DataFrame:
    """Aggregate a per-MINUTE flow panel onto a coarser decision grid by SUMMING.

    The counterpart to reindexing, and not interchangeable with it. A price is a
    level, so sampling it at the decision minute is exactly right. Volume is a flow
    over an interval, and `reindex` onto a 5-minute grid keeps the volume of one
    minute in five and discards the other four — measured at 21% of the true traded
    volume, which understated the capacity headline by 4.7x and gave the lead-lag
    test a signed-flow series whose volume came from a minute the price move did not
    touch.

    Each grid stamp gets the flow over the interval ENDING at it, closed on the right,
    so no volume from after the decision minute is ever included. Bars before the
    first grid stamp are dropped rather than folded into it, and NaN is preserved as
    "no data" rather than being summed to zero.
    """
    if minute_df is None or minute_df.empty:
        return pd.DataFrame()
    gi = pd.DatetimeIndex(grid).sort_values()
    if gi.size == 0:
        return pd.DataFrame(index=gi, columns=minute_df.columns, dtype=float)
    step = (int(pd.Series(gi).diff().dt.total_seconds().div(60).mode().iloc[0])
            if gi.size > 1 else 1)
    step = max(step, 1)
    src = minute_df.sort_index()
    # right-closed, right-labelled: the bar stamped t covers (t-step, t]
    agg = src.resample(f"{step}min", label="right", closed="right").sum(min_count=1)
    return agg.reindex(gi)


def price_to_rate_bp(prices: pd.DataFrame) -> pd.DataFrame:
    """Contract price -> implied rate in BASIS POINTS.

    rate% = 100 - price, so rate_bp = (100 - price) * 100. Working in rate space
    keeps the hypothesis sign readable: a positive ladder predicts the dealer must
    SELL futures, i.e. price DOWN and rate UP, so the predicted sign of the rate
    change is +sign(ladder).
    """
    return (100.0 - prices.astype(float)) * 100.0


def forward_rate_change_bp(rates_bp: pd.DataFrame, horizon_min: int) -> pd.DataFrame:
    """STRICTLY forward change in rate over ``horizon_min``, in bp.

    Feed this a COMPLETE minute grid from ``to_minute_grid``, not raw bars: it uses
    a time-based shift, so on sparse bars an exact t+horizon timestamp usually does
    not exist and the result would be almost entirely NaN (8% coverage measured on
    the ZQ strip). The shift is time-based rather than positional so a gap can
    never silently shorten the horizon.

    Never crosses a session: a change straddling the overnight break is dropped,
    since it is not a tradable intraday horizon.
    """
    shifted = rates_bp.shift(freq=pd.Timedelta(minutes=-horizon_min))
    out = shifted.reindex(rates_bp.index) - rates_bp
    idx = pd.DatetimeIndex(rates_bp.index)
    day_now = (idx.tz_convert("America/New_York") if idx.tz is not None else idx).date
    fut = idx + pd.Timedelta(minutes=horizon_min)
    day_fut = (fut.tz_convert("America/New_York") if idx.tz is not None else fut).date
    same_session = pd.Series(day_now == day_fut, index=idx)
    return out.where(same_session, other=np.nan)


def signed_volume(closes: pd.DataFrame, volumes: pd.DataFrame) -> pd.DataFrame:
    """Bar-direction-signed volume: sign(close_t - close_{t-1}) * volume_t.

    The honest substitute for Lee-Ready tick signing, which this data cannot
    support: no trade prints exist in the repo, only quote updates. Consequences
    to keep in mind when reading G2:
      - a bar that closes unchanged contributes ZERO signed volume regardless of
        how much traded inside it, which at the back of the strip (where the tick
        grid bites) is a large share of bars;
      - signing is at bar resolution, so it cannot distinguish an aggressive buyer
        from a passive seller inside the same minute.
    Both push the measured lead-lag toward zero, so this proxy is conservative.
    """
    closes = closes.astype(float)
    vol = volumes.astype(float).reindex(index=closes.index, columns=closes.columns)
    direction = np.sign(closes.diff())
    return direction * vol.fillna(0.0)


def near_expiry_mask(symbols, on_date, cost_cfg) -> dict:
    """{symbol: bool} — is the contract inside its final ``front_window_months``?

    Drives the front/back tick split in the cost model. Uses the contract's own
    maturity from the ladder's calendar grid, so it needs no vendor call.
    """
    from SDRUtils.stir_flow.ladder import contract_grid

    on = pd.Timestamp(on_date).date()
    cutoff_days = 30.5 * cost_cfg.front_window_months
    out = {}
    for space, root in cfg.SPACE_ROOT.items():
        for bbg, _eff, mat in contract_grid(on, root):
            if bbg in symbols or bucket_to_cme(bbg) in symbols:
                days_left = (pd.Timestamp(mat).date() - on).days
                out[bbg] = days_left <= cutoff_days
    return out
