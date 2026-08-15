"""Exchange-listed rate vol, normalised into the swaption cube's units.

Strategy 1 (JPM, "An option by any other name") asks whether the yield curve or
the **swaption** is the cheaper source of long gamma. ``strat1_listed`` replaces
the OTC benchmark with **exchange-listed** vol, and this module is the layer
that makes the two comparable. It is deliberately the boring half of the job:
everything interesting about the strategy lives in ``strat1_listed.py``, and
everything that can silently corrupt the answer lives here.

Why the substitution is a real question and not a relabelling: swaption vol is
priced by structured-product and mortgage-convexity hedging flow; listed vol is
priced by macro funds and dealer gamma. The curve can be cheap against one and
rich against the other, and the OTC/listed vol basis is itself a traded thing.


The source that exists, and the one that does not
-------------------------------------------------
**SFR (3M SOFR futures) options -- present.**
``notebooks/data/sfr_rv_lab/quotes.parquet`` (199,319 rows, 540 daily dates
2024-07-01..2026-07-28, 14 quarterly contracts SFRH25..SFRH28) plus
``contracts.parquet`` (4,030 (date, symbol) rows carrying ``forward_rate``,
``expiry_date`` and ``tte``). The quote panel alone has no expiry and no
forward, so the two are always merged -- see :func:`load_sfr_panel`. Do not
infer an expiry from the symbol: SFRH25's expiry in this file is **2025-03-14**,
not the June IMM date a "H25 3M contract" naming convention suggests.

**UST futures options -- absent offline.** There is no UST option panel anywhere
under ``notebooks/data``, and the only code path to one
(``USTFutureOptionMDP.sabr_smile``) is uncached and crawls Barchart one HTTP
call per strike. A 1,205-business-day x 28-contract cache-key scan run by the
orchestrator of this work found **0** cached STIR smiles and **8** cached UST
smiles (2 dates, both Mar-2026). So the UST side of this module is an
**adapter with no data**: the conversion maths is implemented and unit-tested on
synthetic inputs with hand-computed answers, and the loader raises
:class:`ListedDataUnavailable` rather than reaching for the network. See
:func:`load_ust_panel` and :func:`ust_price_vol_to_yield_vol`.


What ``iv_bp`` actually is -- measured, not assumed
---------------------------------------------------
The column is named ``iv_bp`` and the natural assumption is "normal bp vol". It
is, but the *pricing convention* attached to it is not free -- the same number
means different premiums depending on whether the model discounts. Both were
tested over all 199,319 rows by repricing ``premium_bp`` with Bachelier in RATE
space at ``iv_bp``, ``tte`` from ``contracts.parquet`` and ``forward_rate`` as
the forward:

=========================  ================  ================  =============
discounting                mean rel. error   median rel error   median |err|
=========================  ================  ================  =============
none (undiscounted)             +3.71%            +3.58%          0.194 bp
``exp(-forward_rate*tte)``      +0.33%            +0.26%          0.011 bp
=========================  ================  ================  =============

Inverting the ATM rows for the discount factor implicitly used gives
3.7%-4.2% depending on the year -- i.e. contemporaneous OIS. So:

* ``iv_bp`` is an **annualised normal (Bachelier) vol of the RATE, in bp/yr**;
* ``premium_bp`` is the **discounted** European Bachelier value in bp of rate
  (equivalently 100 x the option's price in futures price points), consistent
  with CME's premium-paid-upfront settlement on SR3 options.

Independent cross-check against realised vol, from ``contracts.parquet``'s own
``forward_rate`` (per symbol, so the quarterly roll cannot contaminate it):
pooled realised **5.72 bp/day** against a pooled median ATM implied of
**5.77 bp/day** -- a ratio of 1.01. Per-symbol ratios run 0.91-1.40.

Consequences for this module, all of them load-bearing:

* bp/day = ``iv_bp / sqrt(252)``. **No ``tte`` enters that conversion** -- the
  quote is already annualised. Multiplying by ``sqrt(tte)`` would give the
  *terminal* standard deviation, which is not what the JPM note compares.
* The discount factor is needed **only** to reprice, never to read a vol. It
  appears in :func:`bachelier_price` as an argument and in
  :func:`sfr_reprice_check`, and nowhere else.


Price vol vs rate vol
---------------------
The SFR underlying is the futures **price** ``P = 100 - R``. ``dP = -dR``, so a
normal price vol in price points maps to a normal rate vol as
``sigma_R(bp) = sigma_P(points) * 100`` -- exact, because the map is affine
(:func:`sfr_price_vol_to_rate_vol`). This panel is already quoted in rate space,
so the conversion is here for callers holding a price-vol quote from elsewhere,
and as the SFR half of the price-vol/rate-vol pair the UST adapter needs.

The UST case is not affine. A bond future's price responds to yield through the
CTD's DV01, so ``sigma_y(bp) ~ sigma_P(points) / (DV01 in points per bp)`` is a
*local* linearisation (:func:`ust_price_vol_to_yield_vol`), and the resulting
"yield vol" is contaminated by the delivery option -- see that function.


Strike conventions in this panel
--------------------------------
``atm_offset_bps`` is the strike's distance **in bp of rate from the nearest
listed strike to the forward**, not from the forward itself. Verified exactly
over all rows: ``atm_offset_bps == (strike_rate - S0) * 100`` to 0.0 where
``S0`` is the unique strike carrying ``atm_offset_bps == 0`` (one per
(date, symbol), all 4,030). Since SR3 strikes are on a 6.25 bp rate grid, the
anchor sits up to 3.125 bp from the forward -- e.g. SFRH25 on 2024-07-01 has
``forward_rate`` 4.605% and an offset-0 strike of 4.625%, so the forward's own
offset is **-2.0 bp**. :func:`sfr_atm_vol_panel` therefore interpolates the vol
smile in ``atm_offset_bps`` to that forward offset instead of reading the
offset-0 quote, and reports both so the difference is visible.

Only OTM quotes are present, split by right: calls (on price = **receivers** on
rate) occupy ``atm_offset_bps <= 0`` and puts (**payers** on rate) occupy
``>= 0``. Measured: 90,579 C rows at negative offsets, 100,683 P rows at
positive offsets, 0 crossings, and both rights at offset 0 for 4,027 of the
4,030 (date, symbol) pairs. Six exact duplicate quote rows exist and are dropped
on load.
"""

from __future__ import annotations

import math
import os
import pathlib
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import optimize
from scipy.stats import norm

__all__ = [
    "ListedDataUnavailable",
    "BUSINESS_DAYS_PER_YEAR",
    "SFR_PRICE_POINT_BP",
    "UST_DV01_POINTS_PER_BP",
    "default_sfr_root",
    "load_sfr_panel",
    "load_sfr_contracts",
    "bachelier_price",
    "bachelier_implied_vol",
    "vol_bp_per_day",
    "vol_bp_per_year",
    "sfr_price_vol_to_rate_vol",
    "sfr_rate_vol_to_price_vol",
    "ust_price_vol_to_yield_vol",
    "ust_yield_vol_to_price_vol",
    "load_ust_panel",
    "sfr_smile_on",
    "sfr_atm_vol_panel",
    "sfr_term_structure",
    "match_listed_expiry",
    "listed_atm_series",
    "sfr_reprice_check",
    "sfr_realized_vol",
    "coverage_report",
]


class ListedDataUnavailable(RuntimeError):
    """Raised where a listed panel is genuinely not obtainable offline.

    Deliberately NOT a silent empty frame. The UST leg of this comparison has no
    offline history, and a caller that receives an empty DataFrame will happily
    report "0 days of UST coverage" as if that were a measurement.
    """


#: Annual <-> daily bridge. The JPM note quotes both sides of the comparison in
#: bp/day, which is what makes it horizon-agnostic to first order.
BUSINESS_DAYS_PER_YEAR = 252.0

#: One futures price point = 1% of rate = 100 bp. ``P = 100 - R``.
SFR_PRICE_POINT_BP = 100.0

#: Indicative CTD DV01 for the UST futures complex, in **price points per bp**
#: (i.e. $ DV01 per $100,000 face divided by $1,000 per point). Values move with
#: the CTD and with the level of rates by tens of percent, so these exist to
#: make the adapter runnable and testable, NOT to be used as if they were
#: observations. Always pass a measured ``dv01_points_per_bp`` when one is
#: available; :func:`ust_price_vol_to_yield_vol` requires it explicitly.
UST_DV01_POINTS_PER_BP: Dict[str, float] = {
    "TU": 0.0195,   # 2Y
    "FV": 0.0425,   # 5Y
    "TY": 0.0645,   # 10Y
    "UXY": 0.0880,  # Ultra 10Y
    "US": 0.1250,   # classic bond
    "WN": 0.1850,   # Ultra bond
}

_SFR_ROOT_ENV = "ARBS_SFR_QUOTES_ROOT"
_QUOTES_FILE = "quotes.parquet"
_CONTRACTS_FILE = "contracts.parquet"

_CONTRACT_COLS = ["as_of", "symbol", "forward_rate", "forward_price", "expiry_date", "tte"]


# ------------------------------------------------------------------ locations


def default_sfr_root() -> pathlib.Path:
    """Directory holding ``quotes.parquet`` / ``contracts.parquet``.

    ``$ARBS_SFR_QUOTES_ROOT`` overrides; otherwise
    ``<repo>/notebooks/data/sfr_rv_lab``. That directory is gitignored, so the
    parquets are a local artifact -- a missing file is a setup problem, not a
    code problem, and :func:`load_sfr_panel` says so by name.
    """
    override = os.environ.get(_SFR_ROOT_ENV)
    if override:
        return pathlib.Path(override)
    return pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "data" / "sfr_rv_lab"


# --------------------------------------------------------------------- loaders


def load_sfr_contracts(
    root: Optional[pathlib.Path] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
) -> pd.DataFrame:
    """Per-(date, symbol) contract state: forward, expiry, time to expiry.

    ``tte`` is the file's own ACT/365 year fraction from ``as_of`` to
    ``expiry_date`` (checked: SFRH25 on 2024-07-01 carries 0.701370 = 256/365).
    It is used as given rather than recomputed, so that any repricing done here
    is consistent with whatever produced ``iv_bp``.
    """
    root = pathlib.Path(root) if root is not None else default_sfr_root()
    path = root / _CONTRACTS_FILE
    if not path.exists():
        raise ListedDataUnavailable(
            f"SFR contract file not found at {path}. Set ${_SFR_ROOT_ENV} to the "
            f"directory holding {_QUOTES_FILE} and {_CONTRACTS_FILE}."
        )
    df = pd.read_parquet(path)
    keep = [c for c in _CONTRACT_COLS if c in df.columns]
    df = df[keep].copy()
    df["as_of"] = pd.to_datetime(df["as_of"])
    df["expiry_date"] = pd.to_datetime(df["expiry_date"])
    return _clip_dates(df, start, end).reset_index(drop=True)


def load_sfr_panel(
    root: Optional[pathlib.Path] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    *,
    require_contracts: bool = True,
) -> pd.DataFrame:
    """The SFR option smile panel, merged with contract state.

    Columns added on top of the raw quote file:

    ``forward_rate``, ``forward_price``, ``expiry_date``, ``tte``
        from ``contracts.parquet``. Without these there is no time to expiry and
        no forward, so nothing in this module can be checked -- hence
        ``require_contracts=True`` by default, which raises rather than
        returning a panel that silently cannot be repriced.
    ``moneyness_bp``
        ``(strike_rate - forward_rate) * 100`` -- the strike's distance from the
        TRUE forward in bp, as opposed to ``atm_offset_bps`` which is measured
        from the nearest listed strike. Both are kept; they differ by up to half
        a strike interval (3.125 bp).
    ``right_rate``
        ``"receiver"`` for a call on price, ``"payer"`` for a put on price. The
        panel is quoted on the futures PRICE and every calculation here is in
        RATE space, so the translation is done once, on load, rather than at
        each call site where it is easy to invert by accident.

    Six exact duplicate ``(as_of, symbol, right, strike_rate)`` rows exist in the
    file and are dropped (last wins).
    """
    root = pathlib.Path(root) if root is not None else default_sfr_root()
    path = root / _QUOTES_FILE
    if not path.exists():
        raise ListedDataUnavailable(
            f"SFR quote file not found at {path}. Set ${_SFR_ROOT_ENV} to the "
            f"directory holding {_QUOTES_FILE} and {_CONTRACTS_FILE}."
        )
    q = pd.read_parquet(path)
    q["as_of"] = pd.to_datetime(q["as_of"])
    q = q.drop_duplicates(subset=["as_of", "symbol", "right", "strike_rate"], keep="last")
    q = _clip_dates(q, start, end)

    if require_contracts:
        c = load_sfr_contracts(root)
        q = q.merge(c, on=["as_of", "symbol"], how="left")
        missing = int(q["tte"].isna().sum())
        if missing:
            raise ListedDataUnavailable(
                f"{missing} quote rows have no matching contract row (forward/tte). "
                "The panel cannot be repriced or normalised without them."
            )
        q["moneyness_bp"] = (q["strike_rate"] - q["forward_rate"]) * 100.0

    q["right_rate"] = np.where(q["right"].astype(str).str.upper() == "C", "receiver", "payer")
    return q.sort_values(["as_of", "symbol", "strike_rate"]).reset_index(drop=True)


def load_ust_panel(*args: Any, **kwargs: Any) -> pd.DataFrame:
    """Always raises: there is no offline UST futures-option history.

    Kept as a named, loud failure so that the UST arm of this comparison is a
    *documented gap* rather than an empty result that a downstream table would
    render as "0.0". The measurement behind the claim, run by the orchestrator
    of this work rather than re-run here (re-running it is exactly the thing
    that must not happen): a 1,205-business-day x 28-contract scan of the
    ``sabr_smile`` cache keys for ``STIRFutureOptionMDP`` and
    ``USTFutureOptionMDP`` found 0 cached STIR smiles and 8 cached UST smiles,
    on 2 dates, both in Mar-2026.

    ``USTFutureOptionMDP.sabr_smile`` is demand-driven and uncached: a miss goes
    to Barchart with **one HTTP call per strike**. Nothing in this package may
    call it in a loop, and nothing may call it with ``force_refresh``. When a
    panel does appear, give it the columns :func:`load_sfr_panel` returns plus a
    per-date CTD ``dv01_points_per_bp``, and the rest of this module works
    unchanged.
    """
    raise ListedDataUnavailable(
        "No offline UST futures-option panel exists in this repo. The only code "
        "path (USTFutureOptionMDP.sabr_smile) is uncached and crawls Barchart "
        "one HTTP call per strike; a measured 1,205-day x 28-contract key scan "
        "found 8 cached UST smiles on 2 dates (Mar-2026) and 0 cached STIR "
        "smiles. Treat UST as a documented GAP; do not fetch."
    )


def _clip_dates(df: pd.DataFrame, start: Optional[Any], end: Optional[Any]) -> pd.DataFrame:
    if start is not None:
        df = df[df["as_of"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["as_of"] <= pd.Timestamp(end)]
    return df


# ------------------------------------------------------------------- Bachelier


def bachelier_price(
    forward_bp: float,
    strike_bp: float,
    tte_years: float,
    vol_bp_per_year: float,
    right_rate: str = "payer",
    *,
    discount: float = 1.0,
) -> float:
    """European normal-model option value, in the same bp units as the inputs.

    Everything is in RATE space and in bp: ``forward_bp`` and ``strike_bp`` are
    rates in bp (4.605% -> 460.5), ``vol_bp_per_year`` is an annualised normal
    vol in bp, and the result is a premium in bp of rate -- which for SR3 is
    also 100 x the price in futures price points.

    ``right_rate`` is the right **on the rate**: ``"payer"`` pays
    ``max(R - K, 0)`` (a PUT on the futures price), ``"receiver"`` pays
    ``max(K - R, 0)`` (a CALL on the futures price). Getting this backwards is
    invisible at the money and wrong by the whole intrinsic value in the wings,
    so :func:`load_sfr_panel` resolves it once on load.

    ``discount`` multiplies the undiscounted value. SR3 option premium is paid
    upfront, and the measured discount factor implicit in this panel is
    ``exp(-r*T)`` at a contemporaneous OIS ``r`` -- see the module docstring.
    Left at 1.0 by default because every *vol* in this module is read directly
    off ``iv_bp``; discounting is only needed to reprice.
    """
    F = float(forward_bp)
    K = float(strike_bp)
    T = float(tte_years)
    s = float(vol_bp_per_year)
    side = str(right_rate).lower()
    if side not in ("payer", "receiver"):
        raise ValueError(f"right_rate must be 'payer' or 'receiver', got {right_rate!r}")
    if not np.isfinite(F) or not np.isfinite(K) or not np.isfinite(T) or not np.isfinite(s):
        return float("nan")
    intrinsic = max(F - K, 0.0) if side == "payer" else max(K - F, 0.0)
    if T <= 0 or s <= 0:
        return float(discount) * intrinsic
    st = s * math.sqrt(T)
    d = (F - K) / st
    if side == "payer":
        val = (F - K) * norm.cdf(d) + st * norm.pdf(d)
    else:
        val = (K - F) * norm.cdf(-d) + st * norm.pdf(d)
    return float(discount) * float(val)


def bachelier_implied_vol(
    price_bp: float,
    forward_bp: float,
    strike_bp: float,
    tte_years: float,
    right_rate: str = "payer",
    *,
    discount: float = 1.0,
    lo: float = 0.1,
    hi: float = 2000.0,
) -> float:
    """Invert :func:`bachelier_price` for the annualised normal vol in bp/yr.

    Exists so that ``iv_bp`` can be checked against a vol derived *only* from
    ``premium_bp`` -- an independent path through the same convention. Returns
    NaN when the price is outside the model's no-arbitrage range for the
    bracket, which is the honest answer for a stale or crossed quote rather than
    a clamped endpoint.
    """
    p = float(price_bp)
    if not np.isfinite(p) or p <= 0 or tte_years <= 0:
        return float("nan")

    def f(sig: float) -> float:
        return bachelier_price(forward_bp, strike_bp, tte_years, sig,
                               right_rate, discount=discount) - p

    try:
        f_lo, f_hi = f(lo), f(hi)
    except Exception:
        return float("nan")
    if not (np.isfinite(f_lo) and np.isfinite(f_hi)) or f_lo * f_hi > 0:
        return float("nan")
    try:
        return float(optimize.brentq(f, lo, hi, xtol=1e-6, maxiter=200))
    except Exception:
        return float("nan")


# ------------------------------------------------------------ unit conversions


def vol_bp_per_day(
    vol_bp_annual: float,
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
) -> float:
    """Annualised normal bp vol -> the note's bp/day unit.

    ``sigma_day = sigma_year / sqrt(252)``. **No time to expiry enters.** The
    listed quote and the swaption quote and the curve breakeven are all
    annualised, and dividing by ``sqrt(252)`` is what makes them comparable
    across three different expiries without a term-structure assumption.
    """
    v = float(vol_bp_annual)
    if not np.isfinite(v):
        return float("nan")
    return v / math.sqrt(float(business_days_per_year))


def vol_bp_per_year(
    vol_bp_day: float,
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
) -> float:
    """Inverse of :func:`vol_bp_per_day`."""
    v = float(vol_bp_day)
    if not np.isfinite(v):
        return float("nan")
    return v * math.sqrt(float(business_days_per_year))


def sfr_price_vol_to_rate_vol(vol_price_points: float) -> float:
    """Normal PRICE vol (futures points/yr) -> normal RATE vol (bp/yr).

    The SR3 underlying is ``P = 100 - R`` with ``R`` in percent, so ``dP = -dR``
    exactly and one price point is 100 bp of rate::

        sigma_R(bp) = sigma_P(points) * 100

    Affine, so it is exact for a normal model and involves no linearisation --
    unlike the UST case. Sign is irrelevant: a standard deviation is unsigned.
    """
    v = float(vol_price_points)
    if not np.isfinite(v):
        return float("nan")
    return abs(v) * SFR_PRICE_POINT_BP


def sfr_rate_vol_to_price_vol(vol_bp: float) -> float:
    """Inverse of :func:`sfr_price_vol_to_rate_vol`."""
    v = float(vol_bp)
    if not np.isfinite(v):
        return float("nan")
    return abs(v) / SFR_PRICE_POINT_BP


def ust_price_vol_to_yield_vol(
    vol_price_points: float,
    dv01_points_per_bp: Optional[float] = None,
    *,
    contract: Optional[str] = None,
) -> float:
    """Normal PRICE vol on a UST future -> an approximate normal YIELD vol, bp/yr.

    ``sigma_y(bp) ~ sigma_P(points) / (DV01 in price points per bp)``.

    ``dv01_points_per_bp`` is the CTD's dollar duration expressed in the futures'
    own price units: ``$DV01 per $100,000 face / $1,000 per point``. A 10Y note
    future with a $64.50 CTD DV01 is 0.0645. Either pass it (preferred, and
    per-date) or name a ``contract`` to pick an INDICATIVE value out of
    :data:`UST_DV01_POINTS_PER_BP`; passing neither raises rather than guessing.

    **Three reasons the result is not a clean swap-rate vol, in decreasing order
    of size.** They are the reason this repo would report a UST-implied number
    with a caveat even if the data existed:

    1. **The delivery / CTD switch option.** A bond future is an option on which
       bond gets delivered. That embedded option is itself long vol, so its value
       is inside the futures price, and the switch makes the price/yield map
       kinked rather than smooth. Implied vol backed out of a futures option is
       therefore the vol of *the future*, which is the CTD's yield vol plus the
       delivery option's contribution -- an upward contamination that grows when
       the CTD is close to a switch (yields near the 6% notional coupon, or a
       flat/steep delivery basket).
    2. **DV01 is a local linearisation and moves.** The divisor is exact only for
       an infinitesimal move; across a 100 bp shift the CTD's own DV01 changes by
       several percent, and a CTD switch changes it discontinuously.
    3. **Basis, not swap.** Even a perfect CTD yield vol is a *Treasury* yield
       vol. The curve packages this repo prices are swaps, so the comparison
       carries the swap-spread vol as an unhedged residual.

    Returned unsigned; a standard deviation has no direction even though
    ``dP/dy < 0``.
    """
    v = float(vol_price_points)
    dv01 = dv01_points_per_bp
    if dv01 is None:
        if contract is None:
            raise ValueError(
                "ust_price_vol_to_yield_vol needs dv01_points_per_bp (preferred, "
                "measured per date) or contract= to pick an indicative value from "
                f"UST_DV01_POINTS_PER_BP ({sorted(UST_DV01_POINTS_PER_BP)})."
            )
        key = str(contract).upper()
        if key not in UST_DV01_POINTS_PER_BP:
            raise KeyError(f"unknown UST contract {contract!r}; "
                           f"known: {sorted(UST_DV01_POINTS_PER_BP)}")
        dv01 = UST_DV01_POINTS_PER_BP[key]
    dv01 = float(dv01)
    if not np.isfinite(v) or not np.isfinite(dv01) or dv01 <= 0:
        return float("nan")
    return abs(v) / dv01


def ust_yield_vol_to_price_vol(
    vol_bp: float,
    dv01_points_per_bp: Optional[float] = None,
    *,
    contract: Optional[str] = None,
) -> float:
    """Inverse of :func:`ust_price_vol_to_yield_vol`. Same caveats apply."""
    v = float(vol_bp)
    dv01 = dv01_points_per_bp
    if dv01 is None:
        if contract is None:
            raise ValueError("need dv01_points_per_bp or contract=")
        key = str(contract).upper()
        if key not in UST_DV01_POINTS_PER_BP:
            raise KeyError(f"unknown UST contract {contract!r}")
        dv01 = UST_DV01_POINTS_PER_BP[key]
    dv01 = float(dv01)
    if not np.isfinite(v) or not np.isfinite(dv01) or dv01 <= 0:
        return float("nan")
    return abs(v) * dv01


# ------------------------------------------------------------------ ATM / smile


def sfr_smile_on(
    panel: pd.DataFrame,
    day: Any,
    symbol: str,
    *,
    offset_col: str = "atm_offset_bps",
) -> pd.DataFrame:
    """``(offset_bp, vol_bp)`` for one contract on one day, both wings merged.

    The panel keeps only OTM quotes -- calls (rate receivers) at offsets <= 0,
    puts (rate payers) at >= 0 -- so the two rights are two halves of one smile
    and are simply concatenated. Where both exist at the same offset (offset 0,
    on 4,027 of 4,030 (date, symbol) pairs) the two vols are averaged; a
    put/call parity violation would show up as a jump at zero otherwise.

    Returned sorted by offset with the same column names ``smile_on`` uses in
    ``swaption_cube``, so anything written against the swaption smile -- e.g.
    ``implied_shift_density`` -- accepts this frame unchanged.
    """
    ts = pd.Timestamp(day)
    m = (panel["as_of"] == ts) & (panel["symbol"].astype(str) == str(symbol))
    sub = panel.loc[m, [offset_col, "iv_bp"]].dropna()
    if sub.empty:
        return pd.DataFrame(columns=["offset_bp", "vol_bp"])
    out = (sub.groupby(offset_col, as_index=False)["iv_bp"].mean()
              .rename(columns={offset_col: "offset_bp", "iv_bp": "vol_bp"}))
    return out.sort_values("offset_bp").reset_index(drop=True)


def _interp_at(x: np.ndarray, y: np.ndarray, x0: float) -> float:
    """Linear interpolation with flat extrapolation, NaN on an empty grid."""
    if x.size == 0:
        return float("nan")
    if x.size == 1:
        return float(y[0])
    order = np.argsort(x)
    return float(np.interp(float(x0), x[order], y[order]))


def sfr_atm_vol_panel(
    panel: pd.DataFrame,
    *,
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """One row per (date, symbol): the ATM-forward normal vol, in bp/yr and bp/day.

    Three quantities, deliberately all three:

    ``atm_vol_bp_yr``
        the smile interpolated in ``atm_offset_bps`` to the FORWARD's offset.
        This is the number the strategy uses.
    ``atm_strike_vol_bp_yr``
        the raw quote at ``atm_offset_bps == 0`` -- i.e. at the nearest listed
        strike, which sits up to 3.125 bp away from the forward.
    ``fwd_offset_bp``
        how far the forward is from that strike, so the size of the correction is
        auditable rather than buried. Measured across the panel it is within
        +/-3.125 bp by construction.

    Interpolation is linear in offset space with flat extrapolation, matching
    ``swaption_cube.implied_shift_density``'s treatment of the wings (a linear
    extrapolation of a normal-vol smile turns negative).
    """
    need = {"as_of", "symbol", "atm_offset_bps", "iv_bp", "forward_rate", "tte", "expiry_date"}
    missing = need - set(panel.columns)
    if missing:
        raise ValueError(f"panel is missing columns {sorted(missing)}; "
                         "load it with load_sfr_panel(require_contracts=True)")

    rows: List[Dict[str, Any]] = []
    for (ts, sym), g in panel.groupby(["as_of", "symbol"], sort=True):
        sm = (g.groupby("atm_offset_bps", as_index=False)["iv_bp"].mean()
                .sort_values("atm_offset_bps"))
        off = sm["atm_offset_bps"].to_numpy(dtype=float)
        vol = sm["iv_bp"].to_numpy(dtype=float)
        ok = np.isfinite(off) & np.isfinite(vol) & (vol > 0)
        off, vol = off[ok], vol[ok]

        zero = g.loc[g["atm_offset_bps"] == 0.0, "strike_rate"]
        fwd = float(g["forward_rate"].iloc[0])
        if len(zero):
            s0 = float(zero.iloc[0])
            fwd_off = (fwd - s0) * 100.0
            atm_strike_vol = _interp_at(off, vol, 0.0)
        else:
            # No offset-0 strike quoted: the forward's own offset is undefined in
            # this anchoring, so fall back to true-forward moneyness.
            fwd_off = 0.0
            atm_strike_vol = float("nan")

        v = _interp_at(off, vol, fwd_off)
        rows.append({
            "as_of": ts,
            "symbol": str(sym),
            "expiry_date": pd.Timestamp(g["expiry_date"].iloc[0]),
            "tte": float(g["tte"].iloc[0]),
            "forward_rate": fwd,
            "fwd_offset_bp": float(fwd_off),
            "atm_vol_bp_yr": float(v),
            "atm_strike_vol_bp_yr": float(atm_strike_vol),
            "atm_vol_bp_day": vol_bp_per_day(v, business_days_per_year),
            "n_quotes": int(len(g)),
            "offset_lo_bp": float(off.min()) if off.size else float("nan"),
            "offset_hi_bp": float(off.max()) if off.size else float("nan"),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["as_of", "tte"]).reset_index(drop=True)


def sfr_term_structure(atm_panel: pd.DataFrame, day: Any) -> pd.DataFrame:
    """The listed ATM vol term structure on one day, sorted by time to expiry.

    The curve breakeven is a 1-year-horizon number and a listed option has its
    own expiry, so the comparison is made in bp/day. That is exact only if the
    listed term structure is flat, and it is not -- so the slope is reported
    rather than assumed away. This is the per-day slice; the strategy panel
    carries the matched point and the notebook plots the surface.
    """
    ts = pd.Timestamp(day)
    sub = atm_panel[atm_panel["as_of"] == ts]
    cols = ["symbol", "expiry_date", "tte", "forward_rate",
            "atm_vol_bp_yr", "atm_vol_bp_day", "n_quotes"]
    return sub[cols].sort_values("tte").reset_index(drop=True)


# ------------------------------------------------------------- expiry matching


def match_listed_expiry(
    atm_panel: pd.DataFrame,
    day: Any,
    horizon_years: float = 1.0,
    *,
    max_gap_days: float = 60.0,
    min_tte_years: float = 0.02,
) -> Optional[Dict[str, Any]]:
    """Pick the listed contract whose expiry is closest to ``day + horizon``.

    Returns the matched row as a dict, with ``gap_days`` = ``tte*365 - horizon in
    days`` (signed: negative means the listed option expires BEFORE the curve
    horizon), or ``None`` when the nearest contract is further than
    ``max_gap_days`` away.

    Why match at all, when both sides are quoted in bp/day: because the listed
    term structure is not flat, so a 3-month option and a 3-year option on the
    same day disagree, and picking whichever contract happens to sort first
    would inject that slope into the signal as noise. Matching to the horizon
    makes the residual mismatch small and, more importantly, *reported* --
    ``gap_days`` is carried into the signal panel on every date.

    ``min_tte_years`` drops contracts within ~5 business days of expiry, where a
    normal vol backed out of a nearly-intrinsic premium is numerically unstable.
    """
    ts = pd.Timestamp(day)
    sub = atm_panel[(atm_panel["as_of"] == ts) & (atm_panel["tte"] >= float(min_tte_years))]
    sub = sub[np.isfinite(sub["atm_vol_bp_yr"].to_numpy(dtype=float))]
    if sub.empty:
        return None
    target_days = float(horizon_years) * 365.0
    gap = sub["tte"].to_numpy(dtype=float) * 365.0 - target_days
    i = int(np.argmin(np.abs(gap)))
    if abs(gap[i]) > float(max_gap_days):
        return None
    row = sub.iloc[i].to_dict()
    row["gap_days"] = float(gap[i])
    row["horizon_years"] = float(horizon_years)
    return row


def listed_atm_series(
    atm_panel: pd.DataFrame,
    horizon_years: float = 1.0,
    *,
    max_gap_days: float = 60.0,
    min_tte_years: float = 0.02,
    dates: Optional[Sequence[Any]] = None,
) -> pd.DataFrame:
    """Date-indexed frame of the horizon-matched listed ATM vol.

    One row per date with the matched ``symbol``, its ``expiry_date``, ``tte``,
    ``gap_days``, ``atm_vol_bp_yr`` and ``atm_vol_bp_day``. This is the object
    ``strat1_listed`` consumes; keeping the matched contract's identity in the
    frame is what makes "which expiry was used on which date" answerable after
    the fact instead of a modelling assumption.
    """
    days = (pd.DatetimeIndex(sorted(pd.unique(atm_panel["as_of"])))
            if dates is None else pd.DatetimeIndex([pd.Timestamp(d) for d in dates]))
    rows: List[Dict[str, Any]] = []
    for ts in days:
        r = match_listed_expiry(atm_panel, ts, horizon_years,
                                max_gap_days=max_gap_days, min_tte_years=min_tte_years)
        if r is None:
            continue
        rows.append({
            "date": ts,
            "listed_symbol": r["symbol"],
            "listed_expiry": pd.Timestamp(r["expiry_date"]),
            "listed_tte": float(r["tte"]),
            "listed_gap_days": float(r["gap_days"]),
            "listed_forward_rate": float(r["forward_rate"]),
            "listed_atm_bp_yr": float(r["atm_vol_bp_yr"]),
            "listed_atm_bp_day": float(r["atm_vol_bp_day"]),
            "listed_n_quotes": int(r["n_quotes"]),
        })
    if not rows:
        return pd.DataFrame(columns=["date", "listed_symbol", "listed_atm_bp_yr",
                                     "listed_atm_bp_day"]).set_index("date")
    return pd.DataFrame(rows).set_index("date").sort_index()


# ----------------------------------------------------------------- diagnostics


def sfr_reprice_check(
    panel: pd.DataFrame,
    *,
    discount: str = "forward_rate",
    invert: bool = False,
) -> pd.DataFrame:
    """Reprice every quote at its own ``iv_bp`` and report the error.

    This is the tie-out that proves what ``iv_bp`` *is*. Run it both ways --
    ``discount="none"`` and ``discount="forward_rate"`` -- and the convention
    falls out of the two error distributions: undiscounted overprices by ~3.7%
    across the whole panel, discounted at ``exp(-forward_rate*tte)`` lands within
    ~0.3%.

    ``discount``
        ``"none"`` (factor 1) or ``"forward_rate"`` (``exp(-f*T)`` with ``f`` the
        contract's own forward rate as a proxy for the OIS discount rate over the
        option's life -- crude, but it is a *check*, not a pricing model, and it
        is accurate to ~30 bp of rate which is worth ~0.02% of premium).
    ``invert``
        additionally back out a normal vol from ``premium_bp`` alone
        (``bachelier_implied_vol``) and report ``vol_err_bp`` against ``iv_bp``.
        Off by default -- it is a root solve per row, ~15 s for the full panel.

    Returns the panel with ``theo_bp``, ``err_bp``, ``rel_err``, ``disc_factor``
    (and ``vol_reimplied_bp`` / ``vol_err_bp`` when ``invert``).

    The Bachelier formula below is written out again rather than calling
    :func:`bachelier_price` in a loop -- 199,319 scalar calls is ~40 s against
    ~0.1 s vectorised. That duplication is a real hazard, so
    ``tests/test_convexity_rv_listed.py`` asserts the two paths agree row by row
    as well as pinning each one's discount handling separately; a mutation that
    changed only one of them was verified to slip past a test that checked only
    the other.
    """
    df = panel.copy()
    F = df["forward_rate"].to_numpy(dtype=float) * 100.0
    K = df["strike_rate"].to_numpy(dtype=float) * 100.0
    T = df["tte"].to_numpy(dtype=float)
    sig = df["iv_bp"].to_numpy(dtype=float)

    mode = str(discount).lower()
    if mode == "none":
        dfac = np.ones_like(T)
    elif mode in ("forward_rate", "fwd", "exp"):
        dfac = np.exp(-df["forward_rate"].to_numpy(dtype=float) / 100.0 * T)
    else:
        raise ValueError("discount must be 'none' or 'forward_rate'")

    st = sig * np.sqrt(np.maximum(T, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(st > 0, (F - K) / np.where(st > 0, st, 1.0), np.inf * np.sign(F - K))
    payer = (F - K) * norm.cdf(d) + st * norm.pdf(d)
    receiver = (K - F) * norm.cdf(-d) + st * norm.pdf(d)
    is_receiver = df["right_rate"].to_numpy() == "receiver"
    theo = np.where(is_receiver, receiver, payer) * dfac

    df["disc_factor"] = dfac
    df["theo_bp"] = theo
    df["err_bp"] = theo - df["premium_bp"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["rel_err"] = df["err_bp"] / df["premium_bp"].replace(0.0, np.nan)

    if invert:
        vols = [
            bachelier_implied_vol(p, f, k, t, r, discount=dd)
            for p, f, k, t, r, dd in zip(
                df["premium_bp"].to_numpy(dtype=float), F, K, T,
                df["right_rate"].to_numpy(), dfac)
        ]
        df["vol_reimplied_bp"] = np.asarray(vols, dtype=float)
        df["vol_err_bp"] = df["vol_reimplied_bp"] - df["iv_bp"]
    return df


def sfr_realized_vol(
    contracts: pd.DataFrame,
    *,
    by_symbol: bool = True,
    window: Optional[int] = None,
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Realised normal vol of the SFR forward rate, bp/day and bp/yr.

    Differences are taken **within a symbol**, so the quarterly roll never enters
    -- differencing a generic front-contract series would inject the roll gap as
    a fake move once a quarter. This is the second, model-free leg of the
    ``iv_bp`` verification: it is computed from ``contracts.parquet``'s own
    ``forward_rate`` and never touches ``iv_bp``, so agreement between the two is
    evidence and not an identity.

    Measured on the full panel: pooled realised **5.72 bp/day** against a pooled
    median ATM implied of **5.77 bp/day**.

    ``window`` (business days) makes it rolling instead of full-sample, returning
    one row per (symbol, date).
    """
    c = contracts.sort_values(["symbol", "as_of"]).copy()
    c["d_rate_bp"] = c.groupby("symbol")["forward_rate"].diff() * 100.0

    if window is None:
        if by_symbol:
            g = c.groupby("symbol")["d_rate_bp"]
            out = pd.DataFrame({
                "n_obs": g.count(),
                "realized_bp_day": g.std(),
            }).reset_index()
        else:
            out = pd.DataFrame({
                "symbol": ["ALL"],
                "n_obs": [int(c["d_rate_bp"].count())],
                "realized_bp_day": [float(c["d_rate_bp"].std())],
            })
        out["realized_bp_yr"] = out["realized_bp_day"] * math.sqrt(business_days_per_year)
        return out

    c["realized_bp_day"] = (c.groupby("symbol")["d_rate_bp"]
                             .rolling(int(window), min_periods=max(5, int(window) // 2))
                             .std().reset_index(level=0, drop=True))
    c["realized_bp_yr"] = c["realized_bp_day"] * math.sqrt(business_days_per_year)
    return c[["as_of", "symbol", "d_rate_bp", "realized_bp_day", "realized_bp_yr"]]


def coverage_report(
    panel: pd.DataFrame,
    atm_panel: Optional[pd.DataFrame] = None,
    *,
    curve_dates: Optional[Sequence[Any]] = None,
    horizon_years: float = 1.0,
    max_gap_days: float = 60.0,
) -> Dict[str, Any]:
    """What the listed panel actually covers, as numbers rather than adjectives.

    ``curve_dates`` (the swap-curve business-day grid) turns the report into the
    intersection that the strategy can actually run on -- which is the binding
    constraint, since the curve runs 2019-2026 and the listed panel only
    2024-07..2026-07.
    """
    days = pd.DatetimeIndex(sorted(pd.unique(panel["as_of"])))
    rep: Dict[str, Any] = {
        "quote_rows": int(len(panel)),
        "n_dates": int(len(days)),
        "first_date": days.min().date().isoformat() if len(days) else None,
        "last_date": days.max().date().isoformat() if len(days) else None,
        "n_symbols": int(panel["symbol"].nunique()),
        "symbols": sorted(panel["symbol"].astype(str).unique().tolist()),
        "contracts_per_date_median": float(
            panel.groupby("as_of")["symbol"].nunique().median()) if len(days) else float("nan"),
        "strikes_per_contract_median": float(
            panel.groupby(["as_of", "symbol"]).size().median()) if len(panel) else float("nan"),
    }
    if atm_panel is not None and len(atm_panel):
        matched = listed_atm_series(atm_panel, horizon_years, max_gap_days=max_gap_days)
        rep["n_dates_with_matched_expiry"] = int(len(matched))
        rep["matched_expiry_coverage"] = (float(len(matched)) / len(days)) if len(days) else float("nan")
        if len(matched):
            rep["matched_gap_days_abs_median"] = float(matched["listed_gap_days"].abs().median())
            rep["matched_gap_days_abs_max"] = float(matched["listed_gap_days"].abs().max())
            rep["matched_tte_median"] = float(matched["listed_tte"].median())
            rep["matched_symbols"] = sorted(matched["listed_symbol"].unique().tolist())
            rep["listed_atm_bp_day_median"] = float(matched["listed_atm_bp_day"].median())
    if curve_dates is not None:
        cd = pd.DatetimeIndex([pd.Timestamp(d) for d in curve_dates])
        both = days.intersection(cd)
        rep["n_curve_dates"] = int(len(cd))
        rep["n_overlap_dates"] = int(len(both))
        rep["overlap_first"] = both.min().date().isoformat() if len(both) else None
        rep["overlap_last"] = both.max().date().isoformat() if len(both) else None
        rep["listed_dates_without_curve"] = int(len(days.difference(cd)))
    rep["ust"] = {
        "available_offline": False,
        "reason": ("no offline UST futures-option panel; USTFutureOptionMDP.sabr_smile "
                   "is uncached and crawls Barchart per strike. Measured cache scan: "
                   "8 cached UST smiles on 2 dates (Mar-2026), 0 STIR."),
    }
    return rep
