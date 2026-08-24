"""Vol butterfly grid (JWS-style) and mode-vs-forward tracker for strip-peak-fade.

Builds the 12.5bp-wing / 6.25bp-body butterfly grid described in JWS Macro #8
(23-Aug-2026) from a single day's SABR smile snapshot
(``STIRFutureOptionMDP.fetch_sabr_smile``), and reports where the grid's implied
mode sits relative to the contract's forward -- the options-market analogue of the
linear strip's "peak vs neighbors" measurement (Tasks 1-4).

Scope (Task 5 of the strip-peak-fade plan): this module builds the grid builder and
the mode-vs-forward tracker, plus a thin multi-date snapshot runner
(``mode_series``). It deliberately does NOT implement a full historical P&L
backtest of the vol butterfly -- that needs a rolling-contract strip (the peak
contract migrates over time, same issue Task 1 solved for the linear strip), which
does not exist yet for options. See task-5-report.md for the scoping ruling.
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, Iterable, Optional

# Same convention as strip_builder.py: several modules in this repo
# (Caching.supabase_engine) read ARBS_SUPABASE_ENABLED as a module global at import
# time, so this must be set before anything that might import that chain -- before
# the first ARBS-internal import below, and before any test file imports
# STIRFutureOptionMDP.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402


def sr3_to_sfr_symbol(sr3_symbol: str) -> str:
    """Convert a strip-builder SR3 symbol (e.g. "SR3U27") to the option MDP's SFR
    root (e.g. "SFRU27"). Both alias to the same CME Globex root ("SR3") inside
    STIRFutureOptionMDP._QS_STIR_ROOT_ALIAS_TO_GLOBEX -- this just matches the
    symbol spelling fetch_sabr_smile is documented/tested against ("SFRU26", not
    "SR3U26"). Non-"SR3"-prefixed input is passed through unchanged.
    """
    if sr3_symbol.startswith("SR3"):
        return "SFR" + sr3_symbol[3:]
    return sr3_symbol


def _get_call_price(
    calls: Dict[float, float],
    puts: Dict[float, float],
    strike: float,
    future_price: Optional[float],
) -> Optional[float]:
    """Call price at ``strike``.

    Direct market quote if the strike is listed as a call; otherwise put-call
    parity off the listed put at the same strike: ``C(K) = P(K) + F - K`` (discount
    factor taken as 1 -- these are <=2yr STIR expiries, negligible discounting over
    the option's own short life for a parity fill; see task-5-brief.md). Returns
    None if neither leg is listed at this strike (the exchange only lists options
    within +/-550bp of ATM, and only at 6.25bp spacing within +/-150bp -- see
    ``_SABR_SMILE_LISTED_OFFSET_CAP_BPS`` in STIRFutureOptionMDP.py -- so gaps are
    routine at the edges of the grid).
    """
    if strike in calls:
        return calls[strike]
    if strike in puts and future_price is not None:
        return puts[strike] + future_price - strike
    return None


def build_butterfly_grid(
    mdp,
    symbol: str,
    as_of: datetime.date,
    wing_width_bp: float = 12.5,
    body_step_bp: float = 6.25,
    body_lo: float = 94.5,
    body_hi: float = 97.0,
) -> pd.DataFrame:
    """Build the JWS-style butterfly grid for one contract on one date.

    For each body strike on the ``body_step_bp`` grid between ``body_lo`` and
    ``body_hi``, prices the 1x-2x-1x butterfly
    ``call(body - wing) - 2*call(body) + call(body + wing)`` from listed call
    quotes, filling deep-ITM calls via put-call parity off the listed put at the
    same strike (see ``_get_call_price``). A body is skipped (not included in the
    output) if any of its three legs has neither a listed call nor a listed put.

    Parameters
    ----------
    mdp : STIRFutureOptionMDP
        Must expose ``fetch_sabr_smile(request) -> STIRFutureOptionSABRSmile``.
    symbol : str
        Option-MDP symbol, e.g. "SFRU26" (SFR root + month code + 2-digit year).
        Use ``sr3_to_sfr_symbol`` to convert from the strip builder's "SR3..." form.
    as_of : datetime.date
        Settlement date to fetch.

    Returns
    -------
    pd.DataFrame with columns: body_price, body_yield, fly_settle, imp_prob.
    ``imp_prob = fly_settle / max_payout`` where ``max_payout = wing_width_bp/100``
    (0.125 at the default 12.5bp wings) -- NOT a normalized probability: adjacent
    bodies' triangular kernels overlap ~2x on this grid, so the column sums to
    ~2.0, not 1.0 (see reference_sofr_butterfly_grid memory note). ``grid.attrs``
    carries ``future_price``, ``quote_timestamp``, ``symbol``, ``as_of`` so callers
    (e.g. ``mode_vs_forward``) don't need a second fetch just for the forward.
    """
    req = {"symbol": symbol, "as_of": as_of, "strike_offsets_bps": "listed"}
    smile = mdp.fetch_sabr_smile(req)
    pts = smile.points
    future_price = getattr(smile.params, "forward_price", None)

    calls: Dict[float, float] = {
        round(p.strike_price, 4): p.market_price
        for p in pts
        if p.right == "C" and p.market_price is not None
    }
    puts: Dict[float, float] = {
        round(p.strike_price, 4): p.market_price
        for p in pts
        if p.right == "P" and p.market_price is not None
    }

    max_payout = wing_width_bp / 100.0
    body_step = body_step_bp / 100.0
    n_steps = int(round((body_hi - body_lo) / body_step))

    records = []
    for k in range(n_steps + 1):
        body = round(body_lo + k * body_step, 4)
        lower = round(body - max_payout, 4)
        upper = round(body + max_payout, 4)

        c_lower = _get_call_price(calls, puts, lower, future_price)
        c_body = _get_call_price(calls, puts, body, future_price)
        c_upper = _get_call_price(calls, puts, upper, future_price)
        if c_lower is None or c_body is None or c_upper is None:
            continue

        # Deep in the wings, c_lower/c_body/c_upper are each an O(1) put-call-parity
        # sum (put's floor-tick price + F - K) whose linear-in-K parts cancel exactly
        # in real arithmetic once combined into the fly -- but the cancellation is
        # only approximate in float64, leaving ~1e-14/1e-15 residue (observed on
        # SFRU27's sparser far-wing bodies). Round before use so those residues read
        # as the true 0.0 rather than a spurious tiny negative "crossed settle".
        fly_settle = round(c_lower - 2 * c_body + c_upper, 6)
        imp_prob = round(fly_settle / max_payout, 6) if max_payout > 0 else 0.0

        records.append(
            {
                "body_price": body,
                "body_yield": 100.0 - body,
                "fly_settle": fly_settle,
                "imp_prob": imp_prob,
            }
        )

    grid = pd.DataFrame(records, columns=["body_price", "body_yield", "fly_settle", "imp_prob"])
    grid.attrs["future_price"] = future_price
    grid.attrs["quote_timestamp"] = smile.quote_timestamp
    grid.attrs["symbol"] = symbol
    grid.attrs["as_of"] = as_of
    return grid


def mode_vs_forward(grid: pd.DataFrame, future_price: float) -> Dict[str, float]:
    """Compute the mode-forward gap from a butterfly grid.

    ``mode`` is the body with the highest ``imp_prob`` (an argmax over relative
    density, not a normalized probability -- see ``build_butterfly_grid``'s
    docstring). ``gap_bp > 0`` means the market-implied mode sits at a HIGHER yield
    than the forward (the strip's peak is "underpriced" relative to where the
    options book thinks the most likely outcome is); ``gap_bp < 0`` means the mode
    is below the forward in yield.
    """
    if grid.empty:
        raise ValueError("mode_vs_forward: grid is empty, nothing to find a mode of")
    mode_row = grid.loc[grid["imp_prob"].idxmax()]
    forward_yield = 100.0 - future_price
    return {
        "mode_yield": float(mode_row["body_yield"]),
        "forward_yield": float(forward_yield),
        "gap_bp": float((mode_row["body_yield"] - forward_yield) * 100.0),
        "mode_imp_prob": float(mode_row["imp_prob"]),
    }


def mode_series(
    mdp,
    symbol: str,
    dates: Iterable[datetime.date],
    **grid_kwargs: Any,
) -> pd.DataFrame:
    """Mode-vs-forward gap for ``symbol`` across a handful of ``dates``.

    A snapshot series, NOT a P&L backtest -- Task 5 is explicitly scoped to skip
    the full historical backtest (needs rolling contracts; see module docstring).
    One options-smile network fetch per date, so keep ``dates`` short (the task
    brief calls for 2-3 dates on the current peak contract).

    Returns a DataFrame with columns: as_of, symbol, mode_yield, forward_yield,
    gap_bp, mode_imp_prob, n_bodies. A date that returns an empty grid (e.g. no
    listed strikes matched, or the MDP has no quote for that as_of) is silently
    skipped, not raised -- callers should check ``len(result) == len(dates)`` if
    they need to know whether any date dropped out.
    """
    records = []
    for as_of in dates:
        grid = build_butterfly_grid(mdp, symbol, as_of, **grid_kwargs)
        if grid.empty:
            continue
        future_price = grid.attrs.get("future_price")
        if future_price is None:
            continue
        row = mode_vs_forward(grid, future_price)
        row["as_of"] = as_of
        row["symbol"] = symbol
        row["n_bodies"] = len(grid)
        records.append(row)

    cols = ["as_of", "symbol", "mode_yield", "forward_yield", "gap_bp", "mode_imp_prob", "n_bodies"]
    return pd.DataFrame(records, columns=cols)
