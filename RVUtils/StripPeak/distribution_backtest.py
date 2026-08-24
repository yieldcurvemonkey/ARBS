"""Implied-distribution (Breeden-Litzenberger) mode divergence tracker for
strip-peak-fade.

Task 6 of the strip-peak-fade plan: the continuous-density analogue of Task 5's
JWS-style discrete butterfly grid (``RVUtils.StripPeak.vol_backtest``). Both
measure the same thing -- where the options-implied mode sits relative to the
contract's forward -- through different discretizations: Task 5 reads the
argmax off a coarse 6.25bp-body grid of butterfly settles, this module reads
the argmax of the continuous Breeden-Litzenberger risk-neutral density
(``RVUtils.ImpliedDistribution.SFRImpliedDistribution``) fitted to the same
listed smile.

Scope (Task 6 of the strip-peak-fade plan): this module builds the mode
tracker (``build_mode_series``) and runs it on a handful of dates, same as
Task 5. It deliberately does NOT implement
``backtest_mode_divergence(strip_df, peak_df, mdp, hold_days)`` -- a full
historical P&L backtest needs a rolling-contract strip (the peak contract
migrates across time; see task-4-report.md), which does not exist yet for
options. Same scoping ruling as task-5-report.md's "Scoping" section, same
underlying reason (see task-6-report.md).
"""
from __future__ import annotations

import datetime
import os
import warnings as _warnings
from typing import Any, List

# Same convention as strip_builder.py / vol_backtest.py: several modules in this
# repo (Caching.supabase_engine) read ARBS_SUPABASE_ENABLED as a module global at
# import time, so this must be set before anything that might import that chain --
# before the first ARBS-internal import below, and before any test file imports
# STIRFutureOptionMDP.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ImpliedDistribution import SFRImpliedDistribution  # noqa: E402

_COLUMNS = [
    "as_of",
    "symbol",
    "mode_rate",
    "forward_rate",
    "gap_bp",
    "mean_rate",
    "std_rate",
    "skewness",
    "forward_residual_bp",
    "strike_source",
    "n_strikes",
]


def build_mode_series(
    mdp,
    symbol: str,
    dates: List[datetime.date],
    **extract_kwargs: Any,
) -> pd.DataFrame:
    """Build a time series of the Breeden-Litzenberger implied-distribution mode.

    For each date, fetches the listed SABR smile (``mdp.fetch_sabr_smile``),
    runs ``SFRImpliedDistribution(**extract_kwargs).extract()`` to fit the BL
    smoothing spline, and reads the mode as the argmax of the fitted density
    (``bl.rnd_density`` over ``bl.strike_grid_rate``) -- the continuous-density
    analogue of ``vol_backtest.mode_vs_forward``'s discrete-grid argmax.

    ``forward_rate`` comes from ``bl.input.forward_rate``, not a second read
    off ``smile.params`` -- this is the exact forward the BL spline itself
    treated as the martingale mean (see
    ``BreedenLitzenbergerResult.forward_residual_bp``, which is defined as
    ``mean_rate - input.forward_rate``), and it is algebraically identical to
    ``100 - smile.params.forward_price`` (``STIRFutureOptionMDP`` derives
    ``params.forward_rate`` that way at the source, so this is not a different
    number, just one fewer independent attribute path to get wrong -- the
    task brief's own skeleton read ``smile.params.forward``, which does not
    exist on this MDP's params object; the real attributes are
    ``forward_price`` (price space) and ``forward_rate`` (rate space)).

    ``gap_bp > 0`` means the modal rate sits ABOVE the forward -- same sign
    convention as ``vol_backtest.mode_vs_forward``'s ``gap_bp``, so the two
    variants' outputs are directly comparable.

    Parameters
    ----------
    mdp : STIRFutureOptionMDP
        Must expose ``fetch_sabr_smile(request) -> STIRFutureOptionSABRSmile``.
    symbol : str
        Option-MDP symbol, e.g. "SFRU26" (SFR root + month code + 2-digit
        year) -- NOT the strip builder's "SR3..." form (replace "SR3" with
        "SFR" first, e.g. via ``vol_backtest.sr3_to_sfr_symbol``).
    dates : list of datetime.date
        Settlement dates to fetch. One options-smile network fetch + one BL
        spline fit per date, so keep this short -- same "2-3 dates" guidance
        as ``vol_backtest.mode_series``.
    **extract_kwargs
        Forwarded to ``SFRImpliedDistribution(**extract_kwargs)``, e.g.
        ``raw_market_open_interest_min=None`` to disable the OI liquidity
        screen on a sparser far-dated contract.

    Returns
    -------
    pd.DataFrame with columns: as_of, symbol, mode_rate, forward_rate, gap_bp,
    mean_rate, std_rate, skewness, forward_residual_bp, strike_source,
    n_strikes. NOT indexed by date (flat frame, ``as_of`` as a column) --
    matches ``vol_backtest.mode_series``'s shape so the two variants' output
    can be compared/merged directly on (as_of, symbol). ``strike_source``
    flags whether the density came from observed premiums ("market_jpm" or
    "market_listed") or a SABR-model fallback ("sabr_smile" /
    "sabr_extrapolated") -- see
    ``ImpliedDistributionSnapshot.strike_source``'s docstring: a model
    density is unimodal by construction, so a mode read off one cannot
    independently confirm a unimodality thesis. ``forward_residual_bp`` is
    ``bl.mean_rate - bl.input.forward_rate`` (should be ~0 under the
    risk-neutral martingale property); carried through here because it
    turned out, empirically, to be the diagnostic that explains WHEN this
    module's mode agrees with ``vol_backtest``'s discrete-grid mode and when
    it does not -- see task-6-report.md.

    A date that raises during smile fetch or BL extraction (e.g. too few
    surviving strikes for the spline -- see
    ``RVUtils.ImpliedDistribution._breeden_litzenberger``'s ``min_points``
    guard -- or a network/data-availability failure) is skipped, not raised,
    but LOUDLY: a ``UserWarning`` is emitted (``warnings.warn``, the same
    mechanism ``SFRImpliedDistribution.extract_timeseries`` uses internally)
    rather than silently continuing. This is stricter than
    ``vol_backtest.build_butterfly_grid``, which degrades gracefully to a
    shorter grid on sparse data instead of raising -- ``SFRImpliedDistribution
    .extract()`` is a different pipeline (a spline fit, not a lookup) that can
    genuinely raise on this input, and a silently-swallowed exception here
    would be indistinguishable from a boring "no data that day". Callers
    should check ``len(result) == len(dates)`` if they need to know whether
    any date dropped out (same convention ``vol_backtest.mode_series``
    documents).
    """
    dist = SFRImpliedDistribution(**extract_kwargs)
    records = []
    for d in dates:
        try:
            smile = mdp.fetch_sabr_smile(
                {"symbol": symbol, "as_of": d, "strike_offsets_bps": "listed"}
            )
            snap = dist.extract(smile)
            bl = snap.bl_result
            if bl is None:
                raise ValueError("extract() returned no bl_result (run_bl disabled?)")

            mode_rate = float(bl.strike_grid_rate[np.argmax(bl.rnd_density)])
            forward_rate = float(bl.input.forward_rate)

            records.append(
                {
                    "as_of": d,
                    "symbol": symbol,
                    "mode_rate": mode_rate,
                    "forward_rate": forward_rate,
                    "gap_bp": (mode_rate - forward_rate) * 100.0,
                    "mean_rate": float(bl.mean_rate),
                    "std_rate": float(bl.std_rate),
                    "skewness": float(bl.skewness),
                    "forward_residual_bp": float(bl.forward_residual_bp),
                    "strike_source": snap.strike_source,
                    "n_strikes": int(len(bl.input.strikes_price)),
                }
            )
        except Exception as exc:  # noqa: BLE001 -- see docstring: loud skip, not silent
            _warnings.warn(f"build_mode_series: skipping {symbol} {d}: {exc}")
            continue

    return pd.DataFrame(records, columns=_COLUMNS)
