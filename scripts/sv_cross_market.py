# scripts/sv_cross_market.py
"""H8: do the signs hold in EUR, JPY and GBP, and is a multi-market book better?

One rulebook, four markets, run end to end on real curves: forward greeks panel
-> signal panel -> ``causal_signals`` -> ``run_pair`` -> ``report.portfolio``.

**The trap this script is written against.** A multi-market book beats the best
single market on Sharpe almost automatically, because averaging weakly-correlated
series raises the ratio whether or not the mechanism generalises. H8 asks whether
the SIGNS hold, so the answer has to rest on the per-market sign and magnitude of
the measured relationships. The book is reported second, and its improvement is
put through two controls that can refuse it:

* an **analytic decomposition** -- for a risk-parity book whose legs are each
  scaled to the same target vol, ``SR_book ~= (sum of per-market SR) /
  sqrt(1' C 1)`` with ``C`` the realised correlation matrix. If the realised book
  ratio matches that prediction, the improvement IS the arithmetic;
* a **circular-shift control** -- each market's daily series is rotated by a
  random offset, which preserves its own autocorrelation, mean, variance and
  drawdown propensity exactly while destroying the date correspondence between
  markets. If the shifted books improve on the best single market as much as the
  real book does, then the real book carries no cross-market information beyond
  the marginals. Same technique as ``scripts/sv_h2_h3.py``'s UMEP placebo.

**Ranking.** On vol correlation, ``harvest_pnl_share`` and carry sign, never on
Sharpe: both Task 13 placebo pairs out-Sharpe every real pair while running the
OPPOSITE carry sign, and a DV01-matched zero-convexity twin beats the real
package on skew, Sharpe and vol correlation with no gamma at all. Distributions
are compared on **max drawdown**, per the Task 13 amendment -- raw daily-P&L skew
is inherited from ``skew(d spread)`` and carries no information here.

**Three things that are substitutions, named as such.**

1. **There is no non-USD UMEP.** ``panels.umep_panel`` is the Dallas Fed / JPM
   ASW-vs-duration construction and needs a Treasury curve; no equivalent exists
   for EUR/JPY/GBP in this repo. Rather than run USD with a driver the other
   three cannot have -- which would make every cross-market difference partly a
   difference in the model -- **every market here runs on implied vol alone**,
   and USD is additionally run WITH umep so the size of the substitution is
   visible rather than assumed away (``--umep-contrast``).
2. **One cost schedule for four markets.** ``costs.CostSchedule``'s priors
   (0.875bp to initiate, 0.35bp per hedge/roll at a $100k clip) were drawn from
   a USD research brief. Nothing in this repo measures EUR/JPY/GBP bid/offer on
   an ultra-long forward slope. The schedule is applied unchanged, which is an
   ASSUMPTION, and the sensitivity is reported as the **break-even cost
   multiplier** per market -- the multiplier at which that market's net P&L
   reaches zero -- so a reader can see how much cost each market's result can
   carry rather than trusting one number.
3. **The samples are not common.** The swaption vol series that the driver, the
   ``iv_z`` gate and the valuation all rest on begins 2017-01-03 in all four
   markets (measured), and EUR-ESTR curves do not exist before 2019-10. Every
   table prints its own window, and the book is reported both on the union (with
   markets entering as they arrive) and on the all-four window.

**Why no ALIVE row is possible here, stated up front.** Requirement 6 (the
random-walk placebo) is Task 19's machinery and is not re-run per market in this
script, so every row is downgraded to INELIGIBLE by ``report.league_table``.
That is not a formality being skipped: Task 19 measured requirement 6 through
the genuine ``causal_signals -> run_pair`` composition and found it **NOT MET**
(20/20 nulls traded, 19 beat the headline, p = 0.952). No configuration of this
strategy is eligible for ALIVE on the evidence the study already has.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.backtest import causal_signals, run_pair
from RVUtils.StrikelessVol.conventions import FLATTENER, bp_day_to_annual_normals
from RVUtils.StrikelessVol.costs import CostSchedule, charge_usd
from RVUtils.StrikelessVol.factors import drift, expanding_changes_residual, residual_z
from RVUtils.StrikelessVol.greeks import greeks_panel
from RVUtils.StrikelessVol.panels import PANEL_DIR, umep_panel, vol_panel
from RVUtils.StrikelessVol.replication import CurvePricer, ReplicationConfig, simulate
from RVUtils.StrikelessVol.report import (
    PORTFOLIO_WINDOW,
    distribution_stats,
    ledger_attribution,
    league_table,
    portfolio,
    vol_beta,
)
from RVUtils.StrikelessVol.strategy import SignalConfig
from RVUtils.StrikelessVol.universe import ALL_PAIRS, MARKET_CURVES

MARKETS: Tuple[str, ...] = ("USD", "EUR", "JPY", "GBP")

#: The swaption-vol curve key per market. ``MARKET_CURVES`` names the RATE curve;
#: these name the vol surface, and for USD the two differ (OIS vs SOFR).
VOL_CURVE_KEYS: Dict[str, str] = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR",
    "JPY": "JPY-TONAR",
    "GBP": "GBP-SONIA",
}

#: The one structure every market publishes, so "one rulebook" is literally one
#: structure rather than four similar ones.
HEADLINE_LEGS = ("10Y10Y", "20Y10Y")

#: The driver and the gate, in the ``ASSET_IDS_MAP`` form.
VOL_STRUCTURE = "2y 10y"

#: Measured, not assumed: ``IR_SWAPTION_VOLS_V1_STANDARD`` starts 2017-01-03 in
#: every one of the four markets, and EUR-ESTR curves do not exist before
#: 2019-10. See ``_t21_vol_probe`` in the task report.
SAMPLE_START: Dict[str, dt.date] = {
    "USD": dt.date(2017, 1, 3),
    "EUR": dt.date(2019, 10, 1),
    "JPY": dt.date(2017, 1, 3),
    "GBP": dt.date(2017, 1, 3),
}
SAMPLE_END = dt.date(2026, 8, 3)

CACHE_DIR = PANEL_DIR / "cross_market"

#: Trailing window for the realized spread vol that sets ``be_over_realized``'s
#: denominator and the position size. Trailing by construction.
REALIZED_WINDOW = 63

#: Long enough that ``simulate``'s internal roll can never fire inside a segment
#: -- the roll is done by segmentation, as in ``scripts/sv_static_long_control``.
#:
#: **100 years, not that script's 1,000.** ``simulate`` computes
#: ``pd.Timestamp(d0) + pd.DateOffset(months=roll_months)``, and the result has
#: to be representable at the index's own resolution. ``pd.Timestamp`` built
#: from a ``datetime.date`` is SECOND resolution (range to year 2500+), which is
#: what a real curve map carries and why 12,000 has always worked there; a
#: ``pd.bdate_range`` index is NANOSECOND resolution, whose maximum is
#: 2262-04-11, and 12,000 months past 2020 raises ``OutOfBoundsDatetime``. The
#: study's longest sample is under ten years, so 1,200 is equally unreachable
#: and works at either resolution.
_NEVER_ROLL_MONTHS = 1_200

_FLOW_COLS = ["carry", "harvest", "mtm", "cross", "cost", "n_hedges", "n_rolls",
              "initiate_dv01_usd", "hedge_dv01_usd", "roll_dv01_usd"]
_STATE_COLS = ["long_notional", "short_notional", "position_age_years"]

#: Task 18's per-pair sweep, ``len(build_config_grid())``. Recorded as a constant
#: rather than recomputed so the DSR trial count below cannot silently shrink if
#: someone narrows an axis default.
TASK18_CONFIGS_PER_PAIR = 972


def headline_pair(market: str):
    return next(p for p in ALL_PAIRS
                if p.market == market
                and (p.short.label, p.long.label) == HEADLINE_LEGS)


# --------------------------------------------------------------------- curves


@dataclass(frozen=True)
class Coverage:
    market: str
    curve_name: str
    requested: int
    returned: int
    failed_chunks: Dict[str, str]
    first: Optional[dt.date]
    last: Optional[dt.date]

    @property
    def missing_frac(self) -> float:
        return 1.0 - (self.returned / self.requested) if self.requested else float("nan")


def fetch_curves(market: str, start: dt.date, end: dt.date,
                 *, n_jobs: int = 4) -> Tuple[dict, Coverage]:
    """Curves for one market, year by year, with a per-year failure isolated.

    Year chunks rather than one call because **one stale cache entry took the
    whole market down**: GBP-SONIA's 2026-07-31 payload was serialized by a
    rateslib older than the installed 2.7.1, and ``from_json`` raised
    ``JSONDecodeError`` on its ``convention`` field, failing the entire bulk
    request for 199 dates over one of them. A market that returns nothing looks
    exactly like a market with no data, which is the reading this study has been
    bitten by before -- so a failing chunk is recorded by name and the rest of
    the market still runs.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    curve_name = MARKET_CURVES[market]
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    out: dict = {}
    failures: Dict[str, str] = {}
    requested = 0
    for year in range(start.year, end.year + 1):
        lo = max(start, dt.date(year, 1, 1))
        hi = min(end, dt.date(year, 12, 31))
        if lo > hi:
            continue
        dates = pd.bdate_range(lo, hi).date.tolist()
        requested += len(dates)
        try:
            cm = mdp.bulk_get_data(
                {"curve_name": curve_name, "timestamps": dates, "n_jobs": n_jobs}
            )
        except Exception as exc:  # noqa: BLE001
            failures[str(year)] = f"{type(exc).__name__}: {exc}"
            continue
        for k, v in cm.items():
            if v is None or k == "live":
                continue
            out[pd.Timestamp(k)] = v
    dates_out = sorted(out)
    return out, Coverage(
        market=market, curve_name=curve_name, requested=requested,
        returned=len(out), failed_chunks=failures,
        first=dates_out[0].date() if dates_out else None,
        last=dates_out[-1].date() if dates_out else None,
    )


# --------------------------------------------------------------------- panels


def build_signal_panel(market: str, curves: dict, pair, *,
                       start: dt.date, end: dt.date,
                       with_umep: bool = False) -> dict:
    """Everything ``causal_signals`` needs, built causally, for one market.

    The five columns ``strategy.signal_state`` reads, and where each comes from:

    * ``be_over_realized`` -- the breakeven move from ``greeks.greeks_panel``
      (``sqrt(2|roll|/gamma)`` at h=25bp) over the TRAILING 63-day realized vol
      of the pair's own spread. Both legs are pointwise/trailing by
      construction; neither is certified by a shock probe (no probe in the
      engine covers ``be_over_realized``, and it sets the SIGN -- stated, not
      papered over).
    * ``drift_t`` -- a trailing 63-day Newey-West t of
      ``factors.expanding_changes_residual``, the walk-forward changes fit. The
      full-sample ``changes_regression`` is the leaky construction this study
      measured at 6.1 t-units of head movement against a veto gate of 2.0, and
      is deliberately not used.
    * ``residual_z`` -- overwritten by ``causal_signals`` from the audited
      walk-forward levels fit; whatever is put here is ignored.
    * ``spread_vol_bp_day`` -- the same trailing 63-day realized vol.
    * ``iv_z`` -- a trailing 252-day z of the market's own 2y10y ATM implied
      normal, in bp/day exactly as GS publishes it.

    ``drivers`` is implied vol alone in every market. USD can additionally carry
    ``umep``; that is the substitution the module docstring names, and it is off
    by default precisely so the four markets run the same model.
    """
    g = greeks_panel(curves, pair)
    if g.empty:
        raise ValueError(f"{market}: greeks_panel produced no rows")
    idx = g.index

    vols = vol_panel(VOL_CURVE_KEYS[market], [VOL_STRUCTURE], start, end,
                     cache_path=CACHE_DIR / "vol.parquet")
    iv_col = VOL_STRUCTURE.replace(" ", "")
    iv_bp_day = vols[iv_col].astype(float).reindex(idx)
    vol_ann = pd.Series(bp_day_to_annual_normals(iv_bp_day), index=idx, name="vol")

    spread_bp = g["spread_bp"].astype(float)
    realized = spread_bp.diff().rolling(REALIZED_WINDOW,
                                        min_periods=REALIZED_WINDOW).std(ddof=1)

    drivers: Dict[str, pd.Series] = {"vol": vol_ann}
    if with_umep:
        if market != "USD":
            raise ValueError(
                f"umep is USD-only (panels.umep_panel needs a Treasury curve); "
                f"asked for {market}"
            )
        umep_df = umep_panel(start, end, cache_path=str(CACHE_DIR / "tfp_history.parquet"))
        drivers["umep"] = (umep_df["umep_bp_per_year"].astype(float).reindex(idx)
                           if not umep_df.empty else pd.Series(np.nan, index=idx))

    changes_resid = expanding_changes_residual(spread_bp, drivers).residual
    drift_t = drift(changes_resid, window=63)["t_stat"]
    iv_z = residual_z(iv_bp_day, window=252, min_periods=126)

    panel = pd.DataFrame({
        "be_over_realized": g["breakeven_h25"].astype(float) / realized,
        "drift_t": drift_t.reindex(idx),
        # placeholder -- causal_signals overwrites this from the audited fit
        "residual_z": pd.Series(np.nan, index=idx),
        "spread_vol_bp_day": realized,
        "iv_z": iv_z.reindex(idx),
        "realized_vol_bp_day": realized,
        "breakeven_bp_day": g["breakeven_h25"].astype(float),
        "iv_bp_day": iv_bp_day,
        "gamma_h25": g["gamma_h25"].astype(float),
        "daily_roll_usd": g["daily_roll_usd"].astype(float),
        "spread_bp": spread_bp,
    }, index=idx)
    return {
        "panel": panel, "spread_bp": spread_bp, "drivers": drivers,
        "changes_resid": changes_resid, "iv_bp_day": iv_bp_day,
        "greeks": g, "vol_ann": vol_ann,
    }


def build_signals(built: dict, cfg: SignalConfig) -> pd.DataFrame:
    """``causal_signals`` with both certifiable sources wired.

    ``changes_resid_fn`` puts the drift source itself through
    ``audit_causal_betas``. ``iv_bp_day`` is passed WITHOUT ``iv_bp_day_fn``:
    the series IS the raw GS observable, and the engine refuses a pointwise
    builder by name -- the honest certificate there is
    ``iv_z(source uncertified)``, which is what this call earns.
    """
    return causal_signals(
        built["panel"], cfg,
        spread_bp=built["spread_bp"], drivers=built["drivers"],
        changes_resid=built["changes_resid"],
        changes_resid_fn=lambda y, x: expanding_changes_residual(y, x).residual,
        drift_window=63,
        iv_bp_day=built["iv_bp_day"],
        iv_z_window=252, iv_z_min_periods=126,
    )


# ------------------------------------------------------------- the unit ledger


def roll_segments(dates: Sequence, roll_months: int = 12) -> List[Tuple[int, int]]:
    """Inclusive index ranges of the roll periods, overlapping by one date.

    Copied in spirit from ``scripts/sv_static_long_control.roll_segments`` and
    imported from it, not re-implemented -- see :func:`unit_ledger`.
    """
    from scripts.sv_static_long_control import roll_segments as _rs

    return _rs(dates, roll_months)


def unit_ledger(curves: dict, pair, *, trigger_bp: float, roll_months: int,
                package_dv01_usd: float, sign: int,
                costs: CostSchedule) -> Tuple[pd.DataFrame, pd.Series]:
    """The unit ($100k-DV01) package ledger and its per-date long-leg DV01.

    The annual roll is done by SEGMENTATION -- one ``CurvePricer`` and one
    ``simulate`` per roll period, consecutive periods sharing their boundary
    date -- because ``CurvePricer`` ages ONE package and
    ``ReplicationConfig.roll_months`` inside it is a notional reset plus a fee,
    not a new package. Same construction as ``sv_static_long_control``.

    On a boundary date the traded risk is moved from ``initiate_dv01_usd`` to
    ``roll_dv01_usd``: ``run_pair`` overwrites the initiate column from its own
    turnover split, so a roll left on the initiate bucket would simply vanish
    from the fee rather than be mischarged -- which is worse.
    """
    all_dates = sorted(curves)
    seg_cfg = ReplicationConfig(
        trigger_bp=trigger_bp, roll_months=_NEVER_ROLL_MONTHS,
        package_dv01_usd=package_dv01_usd, sign=sign,
    )
    frames: List[pd.DataFrame] = []
    dv01_parts: List[pd.Series] = []
    for k, (i, j) in enumerate(roll_segments(all_dates, roll_months)):
        seg_dates = all_dates[i:j + 1]
        ctx = CurvePricer({d: curves[d] for d in seg_dates}, pair,
                          package_dv01_usd=package_dv01_usd, sign=sign)
        led = simulate(ctx, seg_dates, seg_cfg, costs)
        if k:
            led.iloc[0, led.columns.get_loc("initiate_dv01_usd")] = 0.0
            led.iloc[0, led.columns.get_loc("roll_dv01_usd")] = abs(package_dv01_usd)
            led.iloc[0, led.columns.get_loc("n_rolls")] = 1
        frames.append(led)
        dv01_parts.append(pd.Series(
            [abs(float(ctx.dv01(d, "long"))) for d in seg_dates], index=led.index))

    stacked = pd.concat(frames)
    unit = stacked.groupby(level=0)[_FLOW_COLS].sum()
    unit[_STATE_COLS] = stacked.groupby(level=0)[_STATE_COLS].last()
    unit["total"] = unit[["carry", "harvest", "mtm", "cross", "cost"]].sum(axis=1)
    unit = unit.sort_index()
    # `last` on the shared boundary date, matching how the state columns are
    # stitched: the new package is the one the following days are priced on.
    dv01 = pd.concat(dv01_parts).groupby(level=0).last().sort_index()
    return unit, dv01.reindex(unit.index)


# ----------------------------------------------------------------- one market


def run_market(market: str, *, start: dt.date, end: dt.date,
               cfg: SignalConfig, costs: CostSchedule,
               trigger_bp: float = 25.0, roll_months: int = 12,
               package_dv01_usd: float = 100_000.0, sign: int = FLATTENER,
               with_umep: bool = False, n_jobs: int = 4) -> dict:
    curves, cov = fetch_curves(market, start, end, n_jobs=n_jobs)
    if not curves:
        return {"market": market, "coverage": cov, "error": "no curves"}
    pair = headline_pair(market)
    built = build_signal_panel(market, curves, pair, start=start, end=end,
                               with_umep=with_umep)
    signals = build_signals(built, cfg)
    unit, dv01 = unit_ledger(curves, pair, trigger_bp=trigger_bp,
                             roll_months=roll_months,
                             package_dv01_usd=package_dv01_usd, sign=sign,
                             costs=costs)
    signals = signals.reindex(unit.index)
    # `reindex` fills the (empty) difference with NaN; the sign/size columns
    # must stay numeric or `run_pair`'s scale becomes NaN and the whole ledger
    # with it. Any date in the panel but not the ledger is a date the pricer
    # could not hold the package on, which is a flat day.
    signals["sign"] = signals["sign"].fillna(0).astype(int)
    signals["size"] = signals["size"].fillna(0.0).astype(float)
    signals["dv01_usd"] = signals["dv01_usd"].fillna(0.0).astype(float)
    signals["reason"] = signals["reason"].fillna("no curve")

    rep_cfg = ReplicationConfig(trigger_bp=trigger_bp, roll_months=roll_months,
                                package_dv01_usd=package_dv01_usd, sign=sign)
    res = run_pair(None, signals, rep_cfg=rep_cfg, costs=costs,
                   pair_name=pair.name, unit=unit, dv01_unit=dv01)

    monthly_pnl = res.ledger["total"].resample("ME").sum()
    monthly_dvol = built["iv_bp_day"].resample("ME").last().diff()
    vb = vol_beta(monthly_pnl, monthly_dvol)
    daily_dvol = built["iv_bp_day"].diff()

    return {
        "market": market, "pair": pair, "coverage": cov, "built": built,
        "signals": signals, "result": res, "unit": unit,
        "vol_beta_monthly": vb,
        "vol_changes_daily": daily_dvol,
        "start": res.ledger.index.min().date(),
        "end": res.ledger.index.max().date(),
    }


# ------------------------------------------------------------------ reporting


def bp_day_series(res) -> pd.Series:
    """Daily P&L in bp of the book's OWN realised DV01.

    ``report.portfolio``'s ``target_bp_day`` is in the input series' unit, and a
    dollar book is not comparable across markets whose realised DV01s differ --
    JPY's package is a different size in dollars for the same risk. So the book
    is assembled in bp.
    """
    dv01 = float(res.stats.get("realised_dv01_mean_usd", float("nan")))
    if not np.isfinite(dv01) or dv01 == 0.0:
        raise ValueError("cannot express P&L in bp: realised DV01 is not usable")
    return res.daily_pnl.astype(float) / dv01


def align_for_book(series_by_market: Dict[str, pd.Series]) -> pd.DataFrame:
    """Union calendar; a closed day inside a market's own span is a ZERO.

    Two genuinely different kinds of gap, and only one of them is a zero:

    * **outside** a market's own [first, last] span the market does not exist
      yet (EUR before 2019-10), and that stays NaN -- ``portfolio`` gives it no
      weight and the book simply has fewer legs;
    * **inside** the span, a missing date is that market's holiday. The book
      still holds the position; it earns nothing that day. Left as NaN it would
      blank 63 days of that market's weight for every single holiday, which on
      four different calendars deletes most of the book.

    The choice is stated because it is not free: filling zeros lowers each
    market's measured vol slightly and raises its weight. The alternative --
    dropping to the intersection calendar -- throws away every date any market
    is shut, which is a different and larger distortion.
    """
    frame = pd.DataFrame(series_by_market)
    for col, s in series_by_market.items():
        live = s.dropna()
        if live.empty:
            continue
        span = (frame.index >= live.index.min()) & (frame.index <= live.index.max())
        frame.loc[span, col] = frame.loc[span, col].fillna(0.0)
    return frame.sort_index()


def scaled_legs(book: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    """Each market's contribution to the book: ``w_i * pnl_i``, on the book's index."""
    return pd.DataFrame(
        {c: book[f"w_{c}"] * frame[c] for c in frame.columns}, index=frame.index
    )


def book_start(frame: pd.DataFrame, *, window: int = PORTFOLIO_WINDOW):
    """First date the book could be run **at all**, lagged one day.

    ``portfolio`` returns a NaN weight for two different reasons and this is
    the one that separates them:

    * the trailing window is not yet complete -- the book genuinely cannot be
      sized, and those dates are not part of its life;
    * the trailing vol is **zero** -- which here means the market's own rule
      was flat for the whole window. That market is IDLE, not unsizeable. The
      book holds it at nothing and carries on.

    Reading "no weight" as "not started" conflates them, and measured on JPY
    2017-2020 that moved the book's start **391 rows** in (the rule does not
    trade at all until 2018-07) and its Sharpe from -1.95 to -3.95, purely by
    deleting flat days from a series that is then annualised by sqrt(252)
    anyway.

    Defined as: the first date at which SOME market's trailing ``window``
    observations are all present, plus the one-day lag ``portfolio`` applies.
    ``None`` if no market ever gets a complete window.
    """
    complete = frame.notna().rolling(int(window), min_periods=1).sum().eq(int(window))
    ready = complete.shift(1, fill_value=False).any(axis=1)
    return ready.idxmax() if bool(ready.any()) else None


def book_pnl(book: pd.DataFrame, frame: pd.DataFrame,
             *, window: int = PORTFOLIO_WINDOW) -> pd.Series:
    """The book's daily P&L **on the trading calendar: a flat day is a ZERO.**

    A day the book holds nothing earns nothing, and the rest of this study
    counts flat days (``run_pair`` scores the whole ledger, flat days included).
    So from :func:`book_start` onward, a missing book P&L is filled to 0.0.
    Before that date the book could not have been sized and stays out of the
    series entirely.

    Measured on JPY 2017-2020, where the rule is flat on 713 of 874 days and
    370 of the 63-day windows are all-zero: without this, ``min_count=1``
    returned NaN on 433 of 874 dates and ``distribution_stats`` scored the book
    on 441 days while still annualising by sqrt(252).
    """
    first = book_start(frame, window=window)
    if first is None:
        return book["pnl"]
    out = book["pnl"].copy()
    out.loc[first:] = out.loc[first:].fillna(0.0)
    return out.loc[first:]


def diversification_prediction(book: pd.DataFrame, frame: pd.DataFrame) -> dict:
    """How much of the book's ratio is arithmetic rather than mechanism.

    Computed on the ACTUAL scaled legs ``w_i * pnl_i``, not on the raw series:
    the weights are what make the legs comparable, and a decomposition of a book
    into objects the book is not made of is the shape of defect this study keeps
    finding.

    Two numbers, and the second one is the point:

    * ``realised_sharpe`` -- the book as it is.
    * ``independent_sharpe`` -- the same legs' means and vols with the
      correlation matrix replaced by the IDENTITY, i.e. ``sum(mu) /
      sqrt(sum(sigma^2))``. That is what a book of these legs would score if
      they shared nothing but their marginals. **Nothing in it knows whether
      the mechanism generalises**: n identical uncorrelated legs give
      ``sqrt(n)`` times a single leg's ratio for free.

    If ``realised`` sits at or below ``independent``, the book's advantage over
    a single market is the averaging, not a cross-market signal. The formal
    test is the circular-shift control; this is the closed-form reading of it.
    """
    legs = scaled_legs(book, frame).dropna()
    if len(legs) < 30 or legs.shape[1] < 2:
        return {"n": int(len(legs)), "independent_sharpe": float("nan"),
                "realised_sharpe": float("nan"), "per_market_sr": {},
                "mean_abs_corr": float("nan"), "leg_sd": {}}
    mu = legs.mean()
    sd = legs.std(ddof=1)
    C = legs.corr().to_numpy()
    ann = math.sqrt(252.0)
    total = legs.sum(axis=1)
    return {
        "n": int(len(legs)),
        "per_market_sr": {k: float(mu[k] / sd[k] * ann) for k in legs.columns},
        "leg_sd": {k: float(sd[k]) for k in legs.columns},
        "mean_abs_corr": float(np.abs(C[np.triu_indices_from(C, 1)]).mean()),
        "independent_sharpe": float(mu.sum() / math.sqrt(float((sd ** 2).sum())) * ann),
        "realised_sharpe": float(total.mean() / total.std(ddof=1) * ann),
    }


def circular_shift_control(frame: pd.DataFrame, *, target_bp_day: float,
                           n_draws: int = 200, seed: int = 7) -> pd.DataFrame:
    """Books built from independently rotated legs.

    A circular shift preserves a series' own autocorrelation, mean, variance and
    drawdown propensity exactly -- a rotation changes none of them -- while
    destroying its date correspondence to every other market. So a shifted book
    keeps all the diversification arithmetic and loses any genuine cross-market
    timing. If the real book's improvement sits inside this distribution, the
    improvement is the arithmetic.

    Shifts are drawn from [10%, 90%] of the length so no draw is a near-identity
    (which would leak the real alignment) or a near-full-cycle no-op -- the same
    restriction ``scripts/sv_h2_h3._circular_shift_placebos`` uses.

    **Every draw is a SEPARATE offset per market**, and the offsets and the
    realised mean pairwise correlation are returned as columns
    (``shift_<market>``, ``mean_abs_corr``). A control whose numbers are not
    observable is a control that cannot be shown to have done anything: a
    single shared offset, or a zero one, would leave the cross-market timing
    exactly as it was and every summary statistic would look the same.
    """
    rng = np.random.default_rng(seed)
    n = len(frame)
    lo, hi = max(21, n // 10), n - max(21, n // 10)
    rows = []
    for _ in range(int(n_draws)):
        offsets = {c: int(rng.integers(lo, hi)) for c in frame.columns}
        shifted = pd.DataFrame(
            {c: np.roll(frame[c].to_numpy(), offsets[c]) for c in frame.columns},
            index=frame.index,
        )
        bk = portfolio({c: shifted[c] for c in shifted.columns},
                       target_bp_day=target_bp_day)
        rec = book_stats(book_pnl(bk, shifted))
        rec.update({f"shift_{c}": v for c, v in offsets.items()})
        C = shifted.corr().to_numpy()
        rec["mean_abs_corr"] = (
            float(np.abs(C[np.triu_indices_from(C, 1)]).mean())
            if len(C) > 1 else float("nan"))
        rows.append(rec)
    return pd.DataFrame(rows)


def book_stats(pnl: pd.Series) -> dict:
    d = distribution_stats(pnl)
    return {"sharpe": d["sharpe_annualised"], "max_drawdown": d["max_drawdown"],
            "daily_vol": d["daily_pnl_vol"], "total": float(pd.Series(pnl).dropna().sum()),
            "n": d["n"]}


def breakeven_cost_multiplier(res, schedule: CostSchedule) -> float:
    """The cost multiplier at which this market's net P&L reaches zero.

    Gross is linear in nothing and cost is linear in the multiplier, so this is
    a closed form: ``gross / cost_at_1x``. Reported instead of a second assumed
    schedule, because no measurement of EUR/JPY/GBP bid-offer on an ultra-long
    forward slope exists in this repo -- the honest statement is how much cost
    the result can carry, not a guess at what it is.
    """
    led = res.ledger
    gross = float(led[["carry", "harvest", "mtm", "cross"]].sum().sum())
    one_x = float(charge_usd(led, schedule, multiplier=1.0).sum())
    if one_x == 0.0:
        return float("nan")
    return gross / one_x


def _fmt_signal_state(out: dict) -> str:
    sig = out["signals"].iloc[-1]
    p = out["built"]["panel"].iloc[-1]
    return (f"{out['market']:4s} {out['pair'].name:22s} "
            f"{out['signals'].index[-1].date()}  "
            f"sign {int(sig['sign']):+d} size {float(sig['size']):.3f} "
            f"dv01 ${float(sig['dv01_usd']):>10,.0f}\n"
            f"       reason: {sig['reason']}\n"
            f"       BE/RV {p['be_over_realized']:.3f}  "
            f"BE {p['breakeven_bp_day']:.3f}bp/d  RV {p['realized_vol_bp_day']:.3f}bp/d  "
            f"IV {p['iv_bp_day']:.3f}bp/d  iv_z {p['iv_z']:+.2f}  "
            f"drift_t {p['drift_t']:+.2f}  roll ${p['daily_roll_usd']:+,.0f}/d  "
            f"gamma {p['gamma_h25']:.1f}")


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markets", default=",".join(MARKETS))
    ap.add_argument("--end", default=SAMPLE_END.isoformat())
    ap.add_argument("--target-bp-day", type=float, default=1.0)
    ap.add_argument("--cost-multiplier", type=float, default=1.0)
    ap.add_argument("--n-jobs", type=int, default=4)
    ap.add_argument("--shift-draws", type=int, default=200)
    ap.add_argument("--umep-contrast", action="store_true",
                    help="also run USD with the umep driver, to size the "
                         "substitution the other three markets cannot make")
    args = ap.parse_args(argv)

    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    end = dt.date.fromisoformat(args.end)
    costs = CostSchedule(multiplier=float(args.cost_multiplier))
    cfg = SignalConfig()

    print("=== Convention ledger ===")
    print("spread = bp, longer forward - shorter forward (negative = inverted)")
    print("sign +1 = FLATTENER = receive the longer forward = long convexity")
    print("vols stored in bp/day exactly as GS publishes; annual normals only for drivers")
    print("P&L is DOLLARS in the ledger and bp of realised DV01 in the book")
    print(f"cost schedule {costs} -- USD priors applied unchanged to EUR/JPY/GBP "
          "(an ASSUMPTION; see breakeven multipliers below)")
    print(f"drivers: implied vol ALONE in every market -- no non-USD UMEP exists"
          + ("; USD umep contrast requested" if args.umep_contrast else ""))

    outs: Dict[str, dict] = {}
    for market in markets:
        start = SAMPLE_START[market]
        print(f"\n--- building {market} {start}..{end} ---", flush=True)
        out = run_market(market, start=start, end=end, cfg=cfg, costs=costs,
                         n_jobs=args.n_jobs)
        if "error" in out:
            print(f"{market}: {out['error']}")
            continue
        outs[market] = out
        cov = out["coverage"]
        print(f"{market}: {cov.returned}/{cov.requested} curves "
              f"({cov.missing_frac:.1%} missing) [{cov.first}..{cov.last}]"
              + (f"  FAILED CHUNKS {cov.failed_chunks}" if cov.failed_chunks else ""))
        g = out["built"]["greeks"]
        print(f"   greeks: {len(g)} rows, {g.attrs.get('n_dropped', 0)} dropped of "
              f"{g.attrs.get('dates_in', 0)}")
        print(f"   certified: {out['signals'].attrs.get('certified_signal_inputs')}")
        print(f"   uncertified: {out['signals'].attrs.get('uncertified_signal_inputs')}")

    if not outs:
        print("\nno market produced a result")
        return {}

    _report(outs, costs=costs, target_bp_day=float(args.target_bp_day),
            shift_draws=int(args.shift_draws))

    if args.umep_contrast and "USD" in outs:
        print("\n\n############ USD WITH UMEP -- the substitution, sized ############")
        usd_umep = run_market("USD", start=SAMPLE_START["USD"], end=end, cfg=cfg,
                              costs=costs, with_umep=True, n_jobs=args.n_jobs)
        _umep_contrast(outs["USD"], usd_umep)
        outs["USD_umep"] = usd_umep

    return outs


def _requirement_note(out: dict) -> str:
    flags = out["result"].requirements
    return "met" if flags.all_met else f"unmet: {', '.join(flags.unmet)}"


def _report(outs: Dict[str, dict], *, costs: CostSchedule,
            target_bp_day: float, shift_draws: int) -> None:
    print("\n\n================ (a) today's signal state, per market ================")
    for market, out in outs.items():
        print(_fmt_signal_state(out))

    print("\n\n================ (b) per market -- the H8 answer ================")
    print("H8 asks whether the SIGNS hold. These are the signs; the book is (c).")
    rows = []
    for market, out in outs.items():
        res = out["result"]
        led = res.ledger
        p = out["built"]["panel"]
        be = p["be_over_realized"].dropna()
        dt_ = p["drift_t"].dropna()
        vc_daily = vol_beta(res.daily_pnl, out["vol_changes_daily"])
        stats = res.stats
        att = ledger_attribution([res]).iloc[0]
        dv01 = float(stats.get("realised_dv01_mean_usd", float("nan")))
        rows.append({
            "market": market,
            "start": out["start"], "end": out["end"], "days": int(len(led)),
            "n_trades": int(len(res.trades)),
            "days_on": int((res.ledger["realised_dv01_usd"] > 0).sum()),
            "carry_sign": int(np.sign(float(led["carry"].sum()))),
            "carry_usd": float(led["carry"].sum()),
            "harvest_pnl_share": float(att["harvest_pnl_share"]),
            "harvest_usd": float(att["harvest"]),
            "vol_corr_monthly": float(out["vol_beta_monthly"]["corr"]),
            "vol_corr_daily": float(vc_daily["corr"]),
            "median_gamma_h25": float(p["gamma_h25"].median()),
            "median_roll_usd": float(p["daily_roll_usd"].median()),
            "median_be_over_rv": float(be.median()) if len(be) else float("nan"),
            "share_cheap": float((be < 0.8).mean()) if len(be) else float("nan"),
            "share_rich": float((be > 1.2).mean()) if len(be) else float("nan"),
            "share_drift_veto": float((dt_ > 2.0).mean()) if len(dt_) else float("nan"),
            "total_net_usd": float(led["total"].sum()),
            "total_net_bp": float(stats.get("total_net_bp", float("nan"))),
            "max_drawdown_bp": float(distribution_stats(bp_day_series(res))["max_drawdown"]),
            "sharpe": float(stats.get("sharpe_annualised", float("nan"))),
            "realised_dv01_usd": dv01,
            "breakeven_cost_mult": breakeven_cost_multiplier(res, costs),
            "requirements": _requirement_note(out),
        })
    table = pd.DataFrame(rows).set_index("market")
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(table.T.to_string())

    print("\n--- signs side by side (the H8 verdict material) ---")
    for market, r in table.iterrows():
        print(f"{market:4s} carry {int(r['carry_sign']):+d}  "
              f"harvest_share {r['harvest_pnl_share']:+.4f}  "
              f"vol_corr(m) {r['vol_corr_monthly']:+.4f}  "
              f"gamma {r['median_gamma_h25']:+8.1f}  "
              f"roll ${r['median_roll_usd']:+9.0f}/d  "
              f"BE/RV med {r['median_be_over_rv']:.3f}  "
              f"cheap {r['share_cheap']:.1%} rich {r['share_rich']:.1%}  "
              f"veto {r['share_drift_veto']:.1%}  "
              f"net {r['total_net_bp']:+.2f}bp  "
              f"breakeven cost x{r['breakeven_cost_mult']:.2f}")

    print("\n--- league table (one config per market, DSR on the multiplied count) ---")
    results = [out["result"] for out in outs.values()]
    grid = pd.DataFrame([{
        "pair": out["result"].pair_name,
        "sharpe": out["result"].stats.get("sharpe_annualised"),
        "total_net_bp": out["result"].stats.get("total_net_bp"),
    } for out in outs.values()])
    n_trials = TASK18_CONFIGS_PER_PAIR * len(outs)
    print(f"n_trials declared = {TASK18_CONFIGS_PER_PAIR} configs/pair x {len(outs)} "
          f"markets = {n_trials}. This is a LOWER BOUND on the study's search: it "
          "counts Task 18's per-pair grid once per market and ignores the pairs and "
          "families run in earlier tasks entirely.")
    lt = league_table(results, grid=grid, n_trials=n_trials, cost_schedule=costs,
                      rank_by=("harvest_pnl_share",),
                      vol_changes_by_pair={out["result"].pair_name:
                                           out["vol_changes_daily"]
                                           for out in outs.values()})
    cols = ["pair", "n_trades", "gross_bp", "net_1x_bp", "net_2x_bp", "carry_sign",
            "harvest_pnl_share", "vol_corr", "dsr_prob", "n_trials",
            "requirements_met", "verdict"]
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(lt[cols].to_string(index=False))

    # -------------------------------------------------------------- the book
    print("\n\n================ (c) the combined book ================")
    bp = {m: bp_day_series(out["result"]) for m, out in outs.items()}
    frame = align_for_book(bp)
    print("per-market bp/day series, aligned on the union calendar "
          "(a closed day INSIDE a market's own span is a zero; outside it is NaN):")
    for c in frame.columns:
        s = frame[c].dropna()
        print(f"   {c:4s} n={len(s):5d} [{s.index.min().date()}..{s.index.max().date()}] "
              f"sd {s.std(ddof=1):.4f} bp/day  mean {s.mean():+.5f}")
    print("\ncorrelation of the daily bp series (all-four rows only):")
    common = frame.dropna()
    print(common.corr().round(4).to_string())
    print(f"   rows where every market is live: {len(common)} "
          f"[{common.index.min().date()}..{common.index.max().date()}]"
          if len(common) else "   NO rows where every market is live")

    book = portfolio({c: frame[c] for c in frame.columns},
                     target_bp_day=target_bp_day)
    pnl = book_pnl(book, frame)
    print("\nrisk-parity book (weights = target / trailing 63d sd, lagged one day;")
    print("a day the book holds nothing is a ZERO, not a hole -- see book_pnl):")
    print(pd.Series(book_stats(pnl)).to_string())
    w_cols = [c for c in book.columns if c.startswith("w_")]
    print("weight diagnostics -- the weight is measured on a series that is mostly")
    print("zeros when the rule is flat, so an IDLE market reads as a LOW-VOL one:")
    for c in w_cols:
        m = c[2:]
        wsr = book[c]
        flat = float((frame[m].fillna(0.0) == 0).mean())
        print(f"   {c:8s} defined {wsr.notna().mean():6.1%} of dates  "
              f"median {wsr.median():8.3f}  last {wsr.iloc[-1]:8.3f}  "
              f"(market flat on {flat:.1%} of its dates)")

    # the same book on the window where every market is live -- the only
    # like-for-like comparison against a single market
    common_book = common_pnl = None
    if len(common) > 100:
        common_book = portfolio({c: common[c] for c in common.columns},
                                target_bp_day=target_bp_day)
        common_pnl = book_pnl(common_book, common)
        print("\nsame book restricted to the all-four window:")
        print(pd.Series(book_stats(common_pnl)).to_string())

    print("\nEQUAL-WEIGHT control (every market at weight 1.0, no vol scaling).")
    print("Each market is ALREADY vol-targeted inside its own rule "
          "(SignalConfig.target_vol_bp_day), so this is the natural null for the")
    print("cross-market weighting: if it gives the same verdict, the weighting "
          "scheme is not what is driving the answer.")
    eq = frame.sum(axis=1, min_count=1)
    print(pd.Series(book_stats(eq)).to_string())

    # ------------------------------------------------- (d) the comparison
    print("\n\n================ (d) book vs the best single market ================")
    print("Compared on MAX DRAWDOWN and the carry sign, not Sharpe (Task 13).")
    _compare(frame, pnl, target_bp_day=target_bp_day, label="union calendar")
    if common_pnl is not None:
        _compare(common, common_pnl, target_bp_day=target_bp_day,
                 label="all-four window")

    print("\n--- is the book's improvement DIVERSIFICATION ARITHMETIC? ---")
    src_book, src_frame = ((common_book, common) if common_book is not None
                           else (book, frame))
    pred = diversification_prediction(src_book, src_frame)
    print(f"   per-leg SR (on the SCALED legs w_i*pnl_i): "
          + "  ".join(f"{k} {v:+.4f}" for k, v in pred["per_market_sr"].items()))
    print(f"   per-leg realised sd: "
          + "  ".join(f"{k} {v:.4f}" for k, v in pred["leg_sd"].items())
          + f"   (target {target_bp_day})")
    print(f"   mean |pairwise corr| {pred['mean_abs_corr']:.4f} over n={pred['n']}")
    print(f"   book SR if the legs were INDEPENDENT (C = I): "
          f"{pred['independent_sharpe']:+.4f}")
    print(f"   book SR realised                             : "
          f"{pred['realised_sharpe']:+.4f}")
    print("   The independent number knows nothing about whether the mechanism "
          "generalises: n uncorrelated legs give sqrt(n) x a single leg's ratio "
          "for free. Realised at or below it means the advantage IS the averaging.")

    if len(common) > 200:
        print(f"\n--- circular-shift control ({shift_draws} draws, all-four rows) ---")
        ctrl = circular_shift_control(common, target_bp_day=target_bp_day,
                                      n_draws=shift_draws)
        real = book_stats(common_pnl)
        solo = {c: book_stats(book_pnl(
            portfolio({c: common[c]}, target_bp_day=target_bp_day),
            common[[c]])) for c in common.columns}
        best_sr = max(v["sharpe"] for v in solo.values())
        best_dd = max(v["max_drawdown"] for v in solo.values())
        for key, real_v in (("sharpe", real["sharpe"]),
                            ("max_drawdown", real["max_drawdown"])):
            q = float((ctrl[key] >= real_v).mean())
            print(f"   {key:13s} real {real_v:+.4f}  shifted median "
                  f"{ctrl[key].median():+.4f}  [{ctrl[key].quantile(0.05):+.4f}, "
                  f"{ctrl[key].quantile(0.95):+.4f}]  "
                  f"frac(shifted >= real) {q:.3f}   (higher is better)")
        print(f"   best single market on the same rows: sharpe {best_sr:+.4f}, "
              f"max_drawdown {best_dd:+.4f}")
        print("   A shifted book that improves on the best single market as much as "
              "the real one does means the improvement carries no cross-market "
              "timing -- only the marginals and the arithmetic.")


def _compare(frame: pd.DataFrame, pnl: pd.Series, *, target_bp_day: float,
             label: str) -> None:
    """Book against each single market, each scaled to the SAME target vol.

    An unscaled single market is not a comparison: the book is deliberately
    sized to ``target_bp_day`` and a raw leg is not, so a drawdown comparison
    would be reading the sizing. Each leg is therefore run through the identical
    one-market ``portfolio`` call, and through the same ``book_pnl`` flat-day
    convention -- otherwise the book and the legs would be scored on different
    calendars, which is the comparison quietly measuring something else.
    """
    print(f"\n[{label}]  every leg risk-scaled to the same target, so the "
          "comparison is not reading position size")
    rows = {}
    for c in frame.columns:
        solo = portfolio({c: frame[c]}, target_bp_day=target_bp_day)
        rows[c] = book_stats(book_pnl(solo, frame[[c]]))
    rows["BOOK"] = book_stats(pnl)
    out = pd.DataFrame(rows).T
    print(out.round(4).to_string())
    singles = out.drop(index="BOOK")
    best_dd_market = singles["max_drawdown"].idxmax()
    print(f"   best single market by max drawdown: {best_dd_market} "
          f"({singles.loc[best_dd_market, 'max_drawdown']:+.3f} bp) "
          f"vs BOOK {out.loc['BOOK', 'max_drawdown']:+.3f} bp "
          f"-- book is {'BETTER' if out.loc['BOOK', 'max_drawdown'] > singles['max_drawdown'].max() else 'WORSE'}")
    best_sr_market = singles["sharpe"].idxmax()
    print(f"   best single market by Sharpe (reported, NOT ranked on): "
          f"{best_sr_market} ({singles.loc[best_sr_market, 'sharpe']:+.4f}) "
          f"vs BOOK {out.loc['BOOK', 'sharpe']:+.4f}")


def _umep_contrast(base: dict, with_umep: dict) -> None:
    """What the USD-only driver is worth, so the substitution has a size."""
    for label, out in (("vol only", base), ("vol + umep", with_umep)):
        res = out["result"]
        led = res.ledger
        print(f"{label:11s} n_trades {len(res.trades):4d}  "
              f"net {float(led['total'].sum()):+12,.0f} USD  "
              f"net_bp {res.stats.get('total_net_bp', float('nan')):+.3f}  "
              f"carry_sign {int(np.sign(float(led['carry'].sum()))):+d}  "
              f"sharpe {res.stats.get('sharpe_annualised', float('nan')):+.4f}")
    a = base["signals"]["sign"]
    b = with_umep["signals"]["sign"].reindex(a.index)
    agree = float((a == b).mean())
    print(f"the two USD signals agree on {agree:.1%} of dates; the other three "
          "markets can only ever run the 'vol only' model, so every cross-market "
          "difference below is measured on that one.")


if __name__ == "__main__":
    main()
