"""Panel loading and the derived series every SR3 RV framework shares.

Everything here is computed from the LISTED panels written by
``notebooks/rv/build_sfr_rv_panels.py`` — no model marks, no refetching.

The one piece of hygiene that gates all wing-based work is
:func:`parity_residuals`: for a strike quoted on both sides,
``C - P - (F - K)`` must be ~0 for an option on a future with premium-style
margining. Strikes that violate it are exchange model marks, not prices.
CME SOFR options are American, so the identity is an inequality for deep ITM
strikes; the residual is therefore only used as a *flag*, and the default gate
band is deliberately loose.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "load_panels", "parity_residuals", "attach_parity_flag", "pick_listed_strike",
    "atm_premium_panel", "realized_vol_bp", "constant_maturity_slots",
    "vertical_digital", "digital_panel", "FOMC_DATES", "meetings_between",
    "add_event_distance",
]

# FOMC decision dates (public calendar). Used for event windows and for
# day-weighting a meeting's effect on a reference quarter; verified against the
# Federal Reserve's published 2024-2027 schedules.
FOMC_DATES: Tuple[datetime.date, ...] = tuple(
    datetime.date(*t) for t in [
        (2024, 1, 31), (2024, 3, 20), (2024, 5, 1), (2024, 6, 12),
        (2024, 7, 31), (2024, 9, 18), (2024, 11, 7), (2024, 12, 18),
        (2025, 1, 29), (2025, 3, 19), (2025, 5, 7), (2025, 6, 18),
        (2025, 7, 30), (2025, 9, 17), (2025, 10, 29), (2025, 12, 10),
        (2026, 1, 28), (2026, 3, 18), (2026, 4, 29), (2026, 6, 17),
        (2026, 7, 29), (2026, 9, 16), (2026, 10, 28), (2026, 12, 9),
        (2027, 1, 27), (2027, 3, 17), (2027, 4, 28), (2027, 6, 16),
        (2027, 7, 28), (2027, 9, 22), (2027, 10, 27), (2027, 12, 8),
    ]
)


# ---------------------------------------------------------------------------
def load_panels(path: Path | str) -> Dict[str, pd.DataFrame]:
    """Read quotes/contracts/cdf parquets from a lab data directory."""
    d = Path(path)
    out: Dict[str, pd.DataFrame] = {}
    for kind in ("quotes", "contracts", "cdf"):
        f = d / f"{kind}.parquet"
        if not f.exists():
            continue
        df = pd.read_parquet(f)
        if "as_of" in df.columns:
            df["as_of"] = pd.to_datetime(df["as_of"])
        out[kind] = df
    return out


def parity_residuals(quotes: pd.DataFrame, contracts: pd.DataFrame) -> pd.DataFrame:
    """``C - P - (F - K)`` in bp per (as_of, symbol, strike_price) with both rights.

    All quantities are in bp of price: premiums already are, and ``(F - K)`` is
    ``(forward_price - strike_price) * 100``.
    """
    q = quotes[["as_of", "symbol", "strike_price", "right", "premium_bp"]].copy()
    wide = (q.pivot_table(index=["as_of", "symbol", "strike_price"],
                          columns="right", values="premium_bp", aggfunc="last")
            .reset_index())
    if "C" not in wide.columns or "P" not in wide.columns:
        return pd.DataFrame(columns=["as_of", "symbol", "strike_price", "parity_bp"])
    fwd = contracts.set_index(["as_of", "symbol"])["forward_price"]
    f = fwd.reindex(pd.MultiIndex.from_frame(wide[["as_of", "symbol"]])).to_numpy()
    wide["parity_bp"] = (wide["C"] - wide["P"]
                         - (f - wide["strike_price"].to_numpy()) * 100.0)
    return wide[["as_of", "symbol", "strike_price", "parity_bp"]]


def attach_parity_flag(
    quotes: pd.DataFrame, contracts: pd.DataFrame, *, tol_bp: float = 2.0
) -> pd.DataFrame:
    """Add ``parity_bp`` and ``parity_ok`` to the quotes panel.

    Strikes with only one side quoted get ``parity_bp = NaN`` and
    ``parity_ok = True`` (nothing to check), so the flag never silently drops a
    one-sided wing that is genuinely traded.
    """
    res = parity_residuals(quotes, contracts)
    out = quotes.merge(res, on=["as_of", "symbol", "strike_price"], how="left")
    out["parity_ok"] = out["parity_bp"].isna() | (out["parity_bp"].abs() <= tol_bp)
    return out


def pick_listed_strike(
    day_quotes: pd.DataFrame,
    right: str,
    target_rate: float,
    *,
    tol: float = 0.13,
    min_oi: float = 0.0,
) -> Optional[pd.Series]:
    """Nearest listed strike (in RATE space) to ``target_rate`` for ``right``.

    Returns the quote row, or None when nothing lands within ``tol`` (percent)
    or the open-interest floor is not met.
    """
    g = day_quotes[day_quotes["right"] == right]
    if min_oi > 0 and "oi" in g.columns:
        g = g[g["oi"] >= min_oi]
    if g.empty:
        return None
    i = (g["strike_rate"] - target_rate).abs().idxmin()
    if abs(float(g.loc[i, "strike_rate"]) - target_rate) > tol:
        return None
    return g.loc[i]


def atm_premium_panel(
    quotes: pd.DataFrame, contracts: pd.DataFrame, *, max_offset: float = 0.13
) -> pd.DataFrame:
    """Per (as_of, symbol): ATM straddle premium and ATM normal IV.

    ATM is the listed strike nearest the forward; the straddle premium is the
    sum of the call and put at that strike (both must print). ``atm_iv_bp`` is
    the average of the two legs' listed normal vols.
    """
    fwd = contracts.set_index(["as_of", "symbol"])[["forward_rate"]]
    rows = []
    for (ts, sym), g in quotes.groupby(["as_of", "symbol"], sort=False):
        try:
            f = float(fwd.loc[(ts, sym), "forward_rate"])
        except KeyError:
            continue
        c = pick_listed_strike(g, "C", f, tol=max_offset)
        p = pick_listed_strike(g, "P", f, tol=max_offset)
        if c is None or p is None:
            continue
        # use the common strike nearest the forward so the straddle is a real one
        k = c["strike_price"] if abs(c["strike_rate"] - f) <= abs(p["strike_rate"] - f) \
            else p["strike_price"]
        cc = g[(g["right"] == "C") & (g["strike_price"] == k)]
        pp = g[(g["right"] == "P") & (g["strike_price"] == k)]
        if cc.empty or pp.empty:
            continue
        rows.append({
            "as_of": ts, "symbol": sym, "forward_rate": f,
            "atm_strike": float(k),
            "atm_call_bp": float(cc["premium_bp"].iloc[0]),
            "atm_put_bp": float(pp["premium_bp"].iloc[0]),
            "atm_straddle_bp": float(cc["premium_bp"].iloc[0] + pp["premium_bp"].iloc[0]),
            "atm_iv_bp": float(np.nanmean([cc["iv_bp"].iloc[0], pp["iv_bp"].iloc[0]])),
        })
    return pd.DataFrame(rows)


def realized_vol_bp(
    rates: pd.Series, window: int = 21, *, annualise: float = 252.0
) -> pd.Series:
    """Trailing annualised bp vol of a contract-rate series (rates in percent)."""
    d = rates.astype(float).diff() * 100.0
    return d.rolling(window, min_periods=max(5, window // 2)).std(ddof=1) * np.sqrt(annualise)


def constant_maturity_slots(contracts: pd.DataFrame) -> pd.DataFrame:
    """Add ``cm_slot`` (1 = nearest expiry) per (as_of, symbol)."""
    out = contracts.copy()
    out["expiry_date"] = pd.to_datetime(out["expiry_date"])
    out["cm_slot"] = (out.sort_values(["as_of", "expiry_date"])
                      .groupby("as_of")["expiry_date"].rank(method="first").astype(int))
    return out


# ---------------------------------------------------------------------------
def vertical_digital(
    day_quotes: pd.DataFrame,
    strike_rate: float,
    *,
    right: str = "auto",
    tol: float = 0.02,
    forward_price: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    """Listed vertical spread straddling ``strike_rate``, normalised to a digital.

    In price space a **put** spread pays when price falls, i.e. when the rate
    rises: with ``P(K)`` the put premium at price-strike ``K``,
    ``[P(K_hi) - P(K_lo)] / (K_hi - K_lo) -> P(rate >= strike_rate)``.
    A centred difference across the two listed strikes bracketing the target is
    used, so the estimate is second-order accurate in the strike spacing.

    The panel carries only OTM options, so puts exist below the forward price
    and calls above it. ``right='auto'`` (the default) therefore picks the side
    that is actually listed at the target — puts for rates above the forward,
    calls for rates below — and falls back to the other side if the first has no
    bracket. The two sides agree because settle prices satisfy put-call parity
    to within a quarter-tick (measured on this panel), so choosing the OTM side
    costs nothing and always lands on the liquid wing.

    ``tol`` bounds ``|strike_rate - midpoint(k_lo, k_hi)|`` in percent — the
    normalised vertical estimates the digital at the bracket's midpoint, so that
    is the distance that matters. When the target lands exactly on a listed
    strike the two neighbouring strikes are used (a true centred difference)
    rather than a degenerate zero-width spread.

    Returns ``None`` when no usable bracket exists. The returned ``prob`` is the
    *listed vertical price normalised by its width* — the tradeable object, not
    a model value.
    """
    target_price = 100.0 - strike_rate
    if right == "auto":
        if forward_price is not None and np.isfinite(forward_price):
            order = ("P", "C") if target_price < forward_price else ("C", "P")
        else:
            order = ("P", "C")
        for r in order:
            out = vertical_digital(day_quotes, strike_rate, right=r, tol=tol)
            if out is not None:
                return out
        return None
    g = day_quotes[day_quotes["right"] == right]
    if g.empty:
        return None
    ks = np.sort(g["strike_price"].unique())
    if ks.size < 2:
        return None
    exact = np.isclose(ks, target_price, atol=1e-9)
    if exact.any():
        i = int(np.flatnonzero(exact)[0])
        if 0 < i < ks.size - 1:
            k_lo_v, k_hi_v = float(ks[i - 1]), float(ks[i + 1])
        elif i == 0:
            k_lo_v, k_hi_v = float(ks[0]), float(ks[1])
        else:
            k_lo_v, k_hi_v = float(ks[-2]), float(ks[-1])
    else:
        below = ks[ks < target_price]
        above = ks[ks > target_price]
        if below.size == 0 or above.size == 0:
            return None
        k_lo_v, k_hi_v = float(below[-1]), float(above[0])
    width = k_hi_v - k_lo_v
    if width <= 1e-9:
        return None
    if abs(target_price - 0.5 * (k_lo_v + k_hi_v)) > tol:
        return None
    k_lo = g[np.isclose(g["strike_price"], k_lo_v)].iloc[0]
    k_hi = g[np.isclose(g["strike_price"], k_hi_v)].iloc[0]
    prem_lo, prem_hi = float(k_lo["premium_bp"]), float(k_hi["premium_bp"])
    # Put side: [P(k_hi) - P(k_lo)] / w  ->  P(price <= K) = P(rate >= K).
    # Call side: [C(k_lo) - C(k_hi)] / w  ->  P(price > K) = P(rate < K), so the
    # complement is taken. Under put-call parity the two are exactly consistent:
    # C(k_lo) - C(k_hi) = w - [P(k_hi) - P(k_lo)].
    if right == "P":
        prob = (prem_hi - prem_lo) / (width * 100.0)
    else:
        prob = 1.0 - (prem_lo - prem_hi) / (width * 100.0)
    return {
        "prob": prob, "right": right,
        "k_lo": k_lo_v, "k_hi": k_hi_v,
        "prem_lo": prem_lo, "prem_hi": prem_hi,
        "width_bp": width * 100.0,
        "spread_bp": prem_hi - prem_lo if right == "P" else prem_lo - prem_hi,
        "oi_min": float(min(k_lo.get("oi", 0.0), k_hi.get("oi", 0.0))),
    }


def digital_panel(
    quotes: pd.DataFrame,
    strikes_rate: Sequence[float],
    *,
    right: str = "auto",
    tol: float = 0.02,
    min_oi: float = 0.0,
    contracts: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """``vertical_digital`` fanned across (as_of, symbol, strike_rate)."""
    fwd = (contracts.set_index(["as_of", "symbol"])["forward_price"]
           if contracts is not None else None)
    rows = []
    for (ts, sym), g in quotes.groupby(["as_of", "symbol"], sort=False):
        if min_oi > 0 and "oi" in g.columns:
            g = g[g["oi"] >= min_oi]
            if g.empty:
                continue
        fp = float(fwd.get((ts, sym), np.nan)) if fwd is not None else None
        for k in strikes_rate:
            d = vertical_digital(g, float(k), right=right, tol=tol,
                                 forward_price=fp)
            if d is None:
                continue
            rows.append({"as_of": ts, "symbol": sym, "strike_rate": float(k), **d})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
def meetings_between(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    return [d for d in FOMC_DATES if start <= d <= end]


def add_event_distance(df: pd.DataFrame, *, col: str = "as_of") -> pd.DataFrame:
    """Add ``days_to_fomc`` (signed, business-day-free calendar days, nearest meeting).

    Negative = meeting is in the future, positive = meeting has passed.
    """
    out = df.copy()
    ts = pd.to_datetime(out[col]).dt.date
    fomc = np.array([pd.Timestamp(d).value for d in FOMC_DATES])
    vals = np.array([pd.Timestamp(d).value for d in ts])
    idx = np.abs(vals[:, None] - fomc[None, :]).argmin(axis=1)
    nearest = fomc[idx]
    out["days_to_fomc"] = ((vals - nearest) / 86_400_000_000_000).astype(int)
    out["nearest_fomc"] = pd.to_datetime(nearest)
    return out
