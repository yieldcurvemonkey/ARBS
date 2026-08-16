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

**UST futures option SMILES -- still absent offline.** There is no UST
strike-by-strike option panel anywhere under ``notebooks/data``, and the only
code path to one (``USTFutureOptionMDP.sabr_smile``) is uncached and crawls
Barchart one HTTP call per strike. A 1,205-business-day x 28-contract cache-key
scan run by the orchestrator of this work found **0** cached STIR smiles and
**8** cached UST smiles (2 dates, both Mar-2026). :func:`load_ust_panel` still
raises :class:`ListedDataUnavailable` for that reason and must keep doing so.

**UST futures option ATM VOL -- present since the CM harvest.** What closed the
gap is a different endpoint: ``qs_timeseries`` takes a DATE RANGE and returns a
whole daily CONSTANT-MATURITY series in one call, so
``scripts/harvest_ust_listed_vol.py`` was able to pull
``notebooks/data/convexity_rv/ust_listed_vol.parquet`` -- 58,176 rows, 36 series,
six roots x {30, 60, 90}-day constant maturity x {ABPV, ATM}, 2019-01-02 to
2026-08-14. That is the long-end benchmark strategy 1 never had. It carries no
strikes, so it supports the note's **breakeven-vol** signal and not its
expected-payoff signal. See :func:`load_ust_cm_panel`.

Two value types are present and they are NOT the same kind of number:

``ABPV``
    QuikStrike's annualised basis-point vol: a **normal (Bachelier) vol of the
    underlying's YIELD, in bp/yr**. Directly comparable to a swaption normal vol
    and to the curve breakeven once both are divided by ``sqrt(252)``.
``ATM``
    a **lognormal vol of the futures PRICE**, as a decimal (US ~0.10, UL ~0.14,
    TU ~0.018).

``HistVol30D`` raises for every root and the 180-day constant maturity is empty
for every root, so this panel contains **no realised-vol series** -- the SFR
leg's ``sfr_realized_vol`` cross-check has no UST analogue here.

Both claims about ABPV are verified rather than assumed; see
:func:`ust_units_check_vs_swaptions` and :func:`ust_units_check_dv01` for the
two measurements and the module section "Is ABPV really a normal bp/yr yield
vol" below.


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


Is ABPV really a normal bp/yr yield vol? Two measurements, both PASS
--------------------------------------------------------------------
"ABPV is a normal bp/yr yield vol" is a claim about a column name, so it is
tested twice, by paths that share no inputs.

**(1) Against the swaption cube on matched sectors**
(:func:`ust_units_check_vs_swaptions`). If ABPV is a normal bp/yr vol of a
Treasury yield it must sit in the same range as the OTC normal vol of the
matched swap rate and co-move with it. Measured over the common window:

====================  =====  ===========  ========  =======  =======  =======
listed / OTC node         n   med listed   med OTC    ratio   r (lvl)  r (chg)
====================  =====  ===========  ========  =======  =======  =======
US_30  / 1Mx30Y       1,898        89.25     80.80    1.105     0.949    0.699
US_90  / 3Mx30Y       1,898        91.79     81.47    1.127     0.951    0.567
UL_30  / 1Mx30Y       1,647        84.48     81.46    1.037     0.936    0.476
UL_30  / 1Mx20Y       1,647        84.48     83.70    1.009     0.931    0.483
TY_30  / 1Mx10Y       1,898        90.12     83.44    1.080     0.975    0.790
TN_30  / 1Mx10Y         633        98.72     90.96    1.085     0.965    0.647
====================  =====  ===========  ========  =======  =======  =======

Every ratio lands in 1.01-1.13 and every level correlation in 0.93-0.98. A
mis-scaled column -- a percentage vol, a price vol, a daily rather than annual
number -- would be out by a factor of 10 or more, not by 4-13%.

**(2) Against the panel's own ATM column, through the CTD DV01**
(:func:`ust_units_check_dv01`). The two value types are related by the futures
DV01 and nothing else::

    sigma_price(points)   = ATM * P_fut
    ABPV(bp)              = sigma_price / FV01          FV01 in points per bp
    FV01                  = ModDur_ctd * DirtyPx_ctd / (1e4 * CF_ctd)

The inputs are all available OFFLINE from the repo's own UST basis-report store
(``%LOCALAPPDATA%/ARBS/Cache/ust_future_store/basis_reports``, 6,696 files,
800+ dates per root, 2018-06..2026-08): ``futures_price``, the ``is_ctd`` bond's
``clean_price``, ``ytm`` and ``invoice_cf``. ``ModDur`` is computed here by
:func:`bond_price_and_duration` -- and validated, not trusted, by repricing the
CTD from its own yield and comparing to the store's quoted clean price (median
error **0.0015 price points**, ~0.05 of a 32nd, over all 6,695 CTD rows).

Date-matched result at 30-day constant maturity, implied ABPV vs actual:

=====  =====  ============  =============  =======  ==============  ===============
root       n  actual ABPV   implied ABPV     ratio   ModDur (meas)   ModDur (impl)
=====  =====  ============  =============  =======  ==============  ===============
UL       332         84.65          83.80    0.993           16.73           16.71
US       792         94.16          93.52    0.988           11.58           11.57
TN       123         99.21          97.51    0.983            7.71            7.68
TY       797         98.35          96.40    0.974            5.85            5.75
FV       779        101.63          97.35    0.955            4.01            3.82
TU       725        107.56          95.09    0.887            1.85            1.63
=====  =====  ============  =============  =======  ==============  ===============

For the two roots the long end actually uses, **UL and US, the identity
reproduces ABPV to 0.7% and 1.2%** (5th-95th percentile 0.975-1.003 and
0.965-1.015). The check degrades monotonically towards the short end, which is
the expected direction: at 2 years the price/yield map's curvature is largest
relative to the duration, and TU's ATM column (~0.018) has the least resolution.

``ModDur (impl)`` is ``1e4 * ATM / ABPV``, the same identity with the futures
price algebraically cancelled (:func:`ust_implied_ctd_duration`). It needs no
price, no DV01 and no external data at all, and it lands within 4% of the
measured CTD duration for every root -- which is why it is the cheapest possible
regression test that this panel has not been silently rescaled.

**Verdict: PASS.** The residual is that listed UST vol runs 4-13% ABOVE the
matched swaption vol. That is a real basis with the expected sign -- a Treasury
yield is more volatile than the swap rate of the same tenor, and a futures option
also carries the delivery/CTD switch option, which is long vol and pushes the
implied number up. It is not a units error, and it does not flip a cheap/rich
verdict; it makes the listed benchmark the slightly HARDER one to look cheap
against.


Which listed root prices which sector -- measured, not named
-------------------------------------------------------------
A contract's NAME is a poor guide to what rate its option prices. "US" is the
"30-year bond" contract, but its cheapest-to-deliver has a **median 15.9 years**
remaining, so a US option is a vol quote on a ~16-year Treasury yield, not a
30-year one. Measured from the basis store over 2019-01-01 onward:

=====  ======  ==============  ==============  ==================
root   basis   CTD maturity    CTD ModDur      swap point it prices
=====  ======  ==============  ==============  ==================
TU     TU        1.94 yrs         1.85            2Y
FV     FV        4.39 yrs         4.01            5Y
TY     TY        6.80 yrs         5.85            7Y
TN     UXY       9.61 yrs         8.12           10Y
US     US       15.86 yrs        11.58        15-20Y
UL     WN       25.59 yrs        17.14        25-30Y
=====  ======  ==============  ==============  ==================

:data:`UST_SECTOR_MAP` is built from that column and nothing else, which is why
**UL and not US** is the primary benchmark for 30Y/50Y, and why TY is carried
everywhere as a deliberate mismatch control.


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

import datetime
import glob
import math
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    # ----------------------------------------------------- UST constant maturity
    "UST_CM_PANEL_FILE",
    "UST_CM_ROOTS",
    "UST_ROOT_ALIAS",
    "UST_BASIS_ROOT",
    "UST_CTD_PROFILE",
    "UST_SECTOR_MAP",
    "default_ust_cm_path",
    "load_ust_cm_panel",
    "ust_cm_series",
    "ust_cm_wide",
    "ust_listed_atm_series",
    "ust_cm_term_structure",
    "ust_benchmarks_for",
    "ust_coverage_report",
    # ----------------------------------------------------- units verification
    "bond_price_and_duration",
    "parse_treasury_label",
    "default_ust_basis_root",
    "load_ctd_basis_frame",
    "ust_implied_ctd_duration",
    "ust_abpv_from_price_vol",
    "ust_units_check_dv01",
    "ust_units_check_vs_swaptions",
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
        #: Kept under its original name because callers and tests pin it. It has
        #: always meant "is there an offline UST option SMILE", and that is still
        #: False -- but the name alone now reads as "no UST data at all", which
        #: stopped being true when the constant-maturity ATM harvest landed. The
        #: explicit alias below is the one new code should read.
        "available_offline": False,
        "smiles_available_offline": False,
        "reason": ("no offline UST futures-option SMILE panel; "
                   "USTFutureOptionMDP.sabr_smile is uncached and crawls Barchart per "
                   "strike. Measured cache scan: 8 cached UST smiles on 2 dates "
                   "(Mar-2026), 0 STIR."),
        "atm_cm_available_offline": default_ust_cm_path().exists(),
        "atm_cm_path": str(default_ust_cm_path()),
        "atm_cm_note": ("constant-maturity ATM vol IS available via qs_timeseries -- "
                        "see load_ust_cm_panel. No strikes, so breakeven-vol only."),
    }
    return rep


# =============================================================================
#  UST constant-maturity ATM vol -- the long-end listed benchmark
# =============================================================================

#: Filename of the harvested constant-maturity panel, under the same
#: ``notebooks/data/convexity_rv`` directory every other convexity artifact uses.
UST_CM_PANEL_FILE = "ust_listed_vol.parquet"

_UST_CM_ROOT_ENV = "ARBS_UST_LISTED_VOL"
_UST_BASIS_ROOT_ENV = "ARBS_UST_FUTURE_STORE"

#: QuikStrike globex roots present in the harvest, long end first.
UST_CM_ROOTS: Tuple[str, ...] = ("UL", "US", "TN", "TY", "FV", "TU")

#: Every naming convention this repo uses for the same contract, folded onto the
#: QuikStrike globex root the panel is keyed by. ``USTFutureOptionMDP`` carries
#: the same map (``_QS_UST_ROOT_ALIAS_TO_GLOBEX``); it is repeated here so this
#: module does not import a networked MDP just to spell a root.
UST_ROOT_ALIAS: Dict[str, str] = {
    "TU": "TU", "ZT": "TU",
    "FV": "FV", "ZF": "FV",
    "TY": "TY", "ZN": "TY",
    "TN": "TN", "UXY": "TN", "OTN": "TN", "TNO": "TN",
    "US": "US", "ZB": "US",
    "UL": "UL", "WN": "UL",
}

#: QuikStrike globex root -> the root the UST basis-report store files it under.
#: The two disagree on exactly two contracts (UL/WN and TN/UXY), which is enough
#: to silently join the Ultra Bond's vol onto the 10-year's DV01 if it is done by
#: hand at each call site.
UST_BASIS_ROOT: Dict[str, str] = {
    "TU": "TU", "FV": "FV", "TY": "TY", "TN": "UXY", "US": "US", "UL": "WN",
}

#: What each contract's option actually prices, MEASURED rather than inferred
#: from the contract's name: median remaining maturity and modified duration of
#: the cheapest-to-deliver, and the swap point that maturity corresponds to.
#:
#: Reproduce exactly with::
#:
#:     ctd = load_ctd_basis_frame(start="2019-01-01")     # front_only=True
#:     ctd.groupby("root")["ctd_mod_duration"].median()
#:
#: i.e. FRONT contract only, 2019-01-01 onward to match the vol panel's window.
#: The back months sit ~0.5% away on duration, so a table built without
#: ``front_only`` will not tie out to the last decimal.
#:
#: These are descriptive constants for labelling and for the sector map's
#: justification. Nothing computes a vol from them -- :func:`ust_units_check_dv01`
#: re-derives duration per date from the store rather than reading this table.
UST_CTD_PROFILE: Dict[str, Dict[str, Any]] = {
    "TU": {"ctd_ttm_yrs": 1.94, "ctd_mod_duration": 1.85, "swap_point": "2Y"},
    "FV": {"ctd_ttm_yrs": 4.39, "ctd_mod_duration": 4.01, "swap_point": "5Y"},
    "TY": {"ctd_ttm_yrs": 6.80, "ctd_mod_duration": 5.85, "swap_point": "7Y"},
    "TN": {"ctd_ttm_yrs": 9.61, "ctd_mod_duration": 8.12, "swap_point": "10Y"},
    "US": {"ctd_ttm_yrs": 15.86, "ctd_mod_duration": 11.58, "swap_point": "15-20Y"},
    "UL": {"ctd_ttm_yrs": 25.59, "ctd_mod_duration": 17.14, "swap_point": "25-30Y"},
}

#: Structure label -> which listed roots benchmark it, and why.
#:
#: ``primary`` is the root whose CTD maturity is closest to the rates the
#: structure's legs actually express; ``alt`` is the next-closest, carried so the
#: answer can be shown not to depend on one contract; ``control`` is a root that
#: is deliberately the WRONG sector. If the control scores as well as the
#: primary, the comparison is not measuring sector and the reader should be able
#: to see that -- which is why it is in the map rather than in a footnote.
#:
#: The mapping is driven by :data:`UST_CTD_PROFILE`'s measured ``ctd_ttm_yrs``
#: column and by nothing else. Note the consequence: the contract NAMED "30-year
#: bond" (US, CTD 15.9 yrs) is NOT the primary benchmark for 30Y/50Y -- the Ultra
#: Bond (UL, CTD 25.6 yrs) is.
UST_SECTOR_MAP: Dict[str, Dict[str, Any]] = {
    "30Y/50Y": {
        "primary": "UL", "alt": "US", "control": "TY",
        "why": ("legs are the 30Y and 50Y spot swap rates; UL's CTD is a 25.6-year "
                "Treasury, the longest listed yield quoted. US (15.9 yrs) is the "
                "next point in and is carried as the alt."),
    },
    "20Yx5Y/25Yx5Y": {
        "primary": "UL", "alt": "US", "control": "TY",
        "why": ("legs are 5Y swaps 20Y and 25Y forward, i.e. rates spanning the "
                "20-30Y sector; UL (25.6 yrs) brackets the far end and US (15.9) "
                "the near end."),
    },
    "10Yx10Y/20Yx10Y": {
        "primary": "US", "alt": "TN", "control": "TY",
        "why": ("legs are 10Y swaps 10Y and 20Y forward, i.e. rates spanning 10-30Y "
                "with a ~20Y centre of mass; US's CTD (15.9 yrs) is the closest "
                "single listed point, TN (9.6 yrs) brackets the near leg."),
    },
    "5Y/30Y": {
        "primary": "US", "alt": "UL", "control": "TY",
        "why": ("spot 5s30s spans the whole curve, so no single listed root matches "
                "it; US sits at the mid-point of the two legs' maturities. This "
                "structure is carried because it is the only one of the four whose "
                "cheap/rich verdict is not saturated."),
    },
}


def default_ust_cm_path() -> pathlib.Path:
    """Path to the harvested constant-maturity panel.

    ``$ARBS_UST_LISTED_VOL`` overrides with a full file path; otherwise
    ``<repo>/notebooks/data/convexity_rv/ust_listed_vol.parquet``. That directory
    is gitignored and the file is regenerable by
    ``scripts/harvest_ust_listed_vol.py`` -- which is a NETWORKED job and must not
    be run implicitly, so the loader raises rather than harvesting on a miss.
    """
    override = os.environ.get(_UST_CM_ROOT_ENV)
    if override:
        return pathlib.Path(override)
    return (pathlib.Path(__file__).resolve().parents[2]
            / "notebooks" / "data" / "convexity_rv" / UST_CM_PANEL_FILE)


def load_ust_cm_panel(
    path: Optional[Any] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    *,
    roots: Optional[Sequence[str]] = None,
    cm_days: Optional[Sequence[int]] = None,
    value_types: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """The tidy UST constant-maturity vol panel.

    Columns as harvested: ``date``, ``symbol`` (``"US_30"``), ``root``,
    ``cm_days``, ``value_type``, ``value``. Two columns are ADDED here and are
    the reason callers should come through this function rather than
    ``pd.read_parquet``:

    ``value_bp_day``
        ``value / sqrt(252)`` for ``ABPV`` rows and NaN for everything else.
        ATM is a lognormal price vol; dividing it by ``sqrt(252)`` produces a
        number that looks like a bp/day vol and is not one, and that mistake is
        invisible in a plot. It is therefore made impossible here instead of
        being warned about.
    ``swap_point``
        the swap tenor the root's CTD actually corresponds to, from
        :data:`UST_CTD_PROFILE` -- so a table of listed benchmarks carries "US
        prices the 15-20Y point" next to the number rather than inviting the
        reader to assume "US" means 30Y.

    ``roots`` accepts any alias in :data:`UST_ROOT_ALIAS` (``"ZB"``, ``"WN"``,
    ``"UXY"``, ...) and folds it onto the panel's globex key.
    """
    p = pathlib.Path(path) if path is not None else default_ust_cm_path()
    if not p.exists():
        raise ListedDataUnavailable(
            f"UST constant-maturity vol panel not found at {p}. Regenerate with "
            "`python scripts/harvest_ust_listed_vol.py` (NETWORKED -- it calls "
            f"QuikStrike qs_timeseries), or set ${_UST_CM_ROOT_ENV} to an existing "
            "file. This loader never fetches."
        )
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    df["root"] = df["root"].astype(str).str.upper().map(lambda r: UST_ROOT_ALIAS.get(r, r))
    df["cm_days"] = df["cm_days"].astype(int)
    df["value_type"] = df["value_type"].astype(str)

    if roots is not None:
        want = {UST_ROOT_ALIAS.get(str(r).upper(), str(r).upper()) for r in roots}
        df = df[df["root"].isin(want)]
    if cm_days is not None:
        df = df[df["cm_days"].isin({int(d) for d in cm_days})]
    if value_types is not None:
        df = df[df["value_type"].isin({str(v) for v in value_types})]
    df = _clip_ust_dates(df, start, end)

    is_abpv = df["value_type"].to_numpy() == "ABPV"
    df["value_bp_day"] = np.where(
        is_abpv, df["value"].to_numpy(dtype=float) / math.sqrt(BUSINESS_DAYS_PER_YEAR),
        np.nan)
    df["swap_point"] = df["root"].map(
        lambda r: UST_CTD_PROFILE.get(r, {}).get("swap_point"))
    return df.sort_values(["date", "root", "cm_days", "value_type"]).reset_index(drop=True)


def _clip_ust_dates(df: pd.DataFrame, start: Optional[Any], end: Optional[Any]) -> pd.DataFrame:
    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["date"] <= pd.Timestamp(end)]
    return df


def ust_cm_series(
    panel: pd.DataFrame,
    root: str,
    cm_days: int = 30,
    *,
    value_type: str = "ABPV",
) -> pd.Series:
    """Date-indexed series for one (root, constant maturity, value type).

    Returned in the panel's own units -- bp/yr for ``ABPV``, a lognormal decimal
    for ``ATM``. Use :func:`ust_listed_atm_series` when the destination is a
    bp/day comparison, so the unit conversion happens in one place.
    """
    r = UST_ROOT_ALIAS.get(str(root).upper(), str(root).upper())
    m = ((panel["root"] == r) & (panel["cm_days"] == int(cm_days))
         & (panel["value_type"] == str(value_type)))
    s = panel.loc[m].set_index("date")["value"].sort_index()
    return s[~s.index.duplicated(keep="last")].dropna()


def ust_cm_wide(panel: pd.DataFrame, value_type: str = "ABPV") -> pd.DataFrame:
    """``date`` x ``symbol`` matrix of one value type -- the plotting shape."""
    sub = panel[panel["value_type"] == str(value_type)]
    return sub.pivot_table(index="date", columns="symbol", values="value").sort_index()


def ust_listed_atm_series(
    panel: pd.DataFrame,
    root: str,
    cm_days: int = 30,
    *,
    dates: Optional[Sequence[Any]] = None,
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """The UST benchmark in the exact shape :func:`listed_atm_series` returns.

    This is the adapter that lets ``strat1_listed``'s machinery consume the UST
    panel with no change: same index (``date``), same column names
    (``listed_symbol``, ``listed_atm_bp_yr``, ``listed_atm_bp_day``, ...), so
    anything written against the SFR series accepts this one.

    Three columns differ in MEANING and are named so that difference cannot be
    lost:

    ``listed_tte``
        ``cm_days / 365``. A constant-maturity quote has no expiry to match, so
        ``listed_gap_days`` -- which for SFR is the distance from a real contract
        expiry to the curve horizon -- is instead the distance from this constant
        maturity to the horizon, and is LARGE by construction (a 30-day CM point
        against a 1-year horizon is -335 days). It is carried, not hidden: the
        term-structure question that gap raises is answered directly by
        :func:`ust_cm_term_structure`, and the answer is that the 30->90 day
        slope is a few percent.
    ``listed_symbol``
        ``"US_30"`` -- root and constant maturity, not a deliverable contract.
    ``listed_swap_point``
        what the root's CTD actually prices, from :data:`UST_CTD_PROFILE`.
    """
    r = UST_ROOT_ALIAS.get(str(root).upper(), str(root).upper())
    s = ust_cm_series(panel, r, cm_days, value_type="ABPV")
    if dates is not None:
        s = s.reindex(pd.DatetimeIndex([pd.Timestamp(d) for d in dates])).dropna()
    out = pd.DataFrame(index=s.index)
    out.index.name = "date"
    out["listed_symbol"] = f"{r}_{int(cm_days)}"
    out["listed_root"] = r
    out["listed_cm_days"] = int(cm_days)
    out["listed_expiry"] = pd.NaT           # constant maturity: no deliverable expiry
    out["listed_tte"] = float(cm_days) / 365.0
    out["listed_gap_days"] = float(cm_days) - 365.0
    out["listed_atm_bp_yr"] = s.to_numpy(dtype=float)
    out["listed_atm_bp_day"] = s.to_numpy(dtype=float) / math.sqrt(business_days_per_year)
    out["listed_swap_point"] = UST_CTD_PROFILE.get(r, {}).get("swap_point")
    return out.sort_index()


def ust_cm_term_structure(
    panel: pd.DataFrame,
    *,
    value_type: str = "ABPV",
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """The 30/60/90-day constant-maturity term structure and its slope, per root.

    The curve breakeven is a **1-year-horizon** number and these quotes are 30 to
    90 days, so the comparison rests on the listed term structure being close to
    flat. That is a measurement, not an assumption, and this is where it is made:
    one row per root with the median ABPV at each constant maturity, the 90-vs-30
    slope in bp/yr and in percent, and the same in bp/day.

    Read it before believing any cheap/rich verdict that depends on a margin
    smaller than the slope.
    """
    sub = panel[panel["value_type"] == str(value_type)]
    rows: List[Dict[str, Any]] = []
    for r, g in sub.groupby("root", sort=True):
        rec: Dict[str, Any] = {"root": r,
                               "swap_point": UST_CTD_PROFILE.get(r, {}).get("swap_point")}
        med: Dict[int, float] = {}
        for cm in (30, 60, 90):
            v = g.loc[g["cm_days"] == cm, "value"].to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            med[cm] = float(np.median(v)) if v.size else float("nan")
            rec[f"n_{cm}"] = int(v.size)
            rec[f"median_{cm}"] = med[cm]
            rec[f"median_{cm}_bp_day"] = (med[cm] / math.sqrt(business_days_per_year)
                                          if np.isfinite(med[cm]) else float("nan"))
        rec["slope_90_30"] = med[90] - med[30]
        rec["slope_90_30_bp_day"] = (med[90] - med[30]) / math.sqrt(business_days_per_year)
        rec["slope_90_30_pct"] = (100.0 * (med[90] / med[30] - 1.0)
                                  if med[30] else float("nan"))
        rows.append(rec)
    return pd.DataFrame(rows)


def ust_benchmarks_for(structure: str) -> Dict[str, Any]:
    """The primary / alt / control listed roots for one structure label.

    Raises on an unknown label rather than defaulting to a root, because a
    silently-defaulted benchmark is exactly the sector mismatch this map exists
    to prevent.
    """
    key = str(structure)
    if key not in UST_SECTOR_MAP:
        raise KeyError(f"no listed sector mapping for {structure!r}; "
                       f"known: {sorted(UST_SECTOR_MAP)}")
    out = dict(UST_SECTOR_MAP[key])
    out["structure"] = key
    out["roots"] = [out["primary"], out["alt"], out["control"]]
    return out


def ust_coverage_report(
    panel: pd.DataFrame,
    *,
    curve_dates: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """What the UST constant-maturity panel covers, per (root, cm, value type)."""
    rep: Dict[str, Any] = {
        "rows": int(len(panel)),
        "n_series": int(panel.groupby(["symbol", "value_type"]).ngroups),
        "value_types": sorted(panel["value_type"].unique().tolist()),
        "roots": sorted(panel["root"].unique().tolist()),
        "cm_days": sorted(int(x) for x in panel["cm_days"].unique()),
        "series": {},
    }
    for (sym, vt), g in panel.groupby(["symbol", "value_type"], sort=True):
        rep["series"][f"{sym}|{vt}"] = {
            "n": int(len(g)),
            "first": g["date"].min().date().isoformat(),
            "last": g["date"].max().date().isoformat(),
            "median": float(g["value"].median()),
        }
    if curve_dates is not None:
        cd = pd.DatetimeIndex([pd.Timestamp(d) for d in curve_dates])
        for r in sorted(panel["root"].unique()):
            days = pd.DatetimeIndex(sorted(pd.unique(
                panel.loc[(panel["root"] == r) & (panel["value_type"] == "ABPV"), "date"])))
            both = days.intersection(cd)
            rep.setdefault("overlap_with_curve", {})[r] = {
                "n_listed": int(len(days)),
                "n_overlap": int(len(both)),
                "first": both.min().date().isoformat() if len(both) else None,
                "last": both.max().date().isoformat() if len(both) else None,
            }
        rep["n_curve_dates"] = int(len(cd))
    return rep


# =============================================================================
#  Units verification -- proving what ABPV is, rather than reading its name
# =============================================================================

_TSY_FRACTION = {"1/8": 0.125, "1/4": 0.25, "3/8": 0.375, "1/2": 0.5,
                 "5/8": 0.625, "3/4": 0.75, "7/8": 0.875}
_TSY_MONTH = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

#: Day-of-month candidates a US Treasury coupon issue can mature on. Notes and
#: bonds mature on the 15th or at month end; the exact one is not in the basis
#: store's label, so :func:`load_ctd_basis_frame` RESOLVES it by repricing the
#: bond at its own quoted yield under each candidate and keeping the one that
#: reproduces the quoted clean price. That turns a guess into a measurement, and
#: the residual price error is returned so the resolution can be audited.
_TSY_MATURITY_DAYS: Tuple[int, ...] = (15, 31, 30, 28, 29, 1)


def parse_treasury_label(label: str) -> Tuple[float, int, int]:
    """``"T 4 1/2 Aug 39"`` -> ``(4.5, 8, 2039)`` -- coupon %, month, year.

    The basis store's ``label`` column is the street description and is the only
    place the CTD's coupon and maturity appear, so this parse sits underneath the
    whole DV01 units check. It raises on anything it does not recognise instead of
    returning a plausible-looking default.

    Three coupon spellings occur and all three are handled: ``"T 2 Nov 22"``
    (whole), ``"T 4 1/2 Aug 39"`` (whole plus eighth) and ``"T 7/8 Feb 27"`` --
    a sub-1% coupon, written as the fraction alone. The last is real (the
    2020-21 issuance is full of them) and a parser that assumed a leading whole
    number would raise on exactly the CTDs of that era.
    """
    toks = str(label).split()
    if len(toks) < 3 or toks[0].upper() != "T":
        raise ValueError(f"unrecognised treasury label {label!r}")
    mon, yr = toks[-2], toks[-1]
    if mon not in _TSY_MONTH:
        raise ValueError(f"unrecognised month in {label!r}")
    body = toks[1:-2]
    if not body:
        raise ValueError(f"no coupon in treasury label {label!r}")
    if len(body) == 1:
        tok = body[0]
        coupon = _TSY_FRACTION[tok] if tok in _TSY_FRACTION else float(tok)
    elif len(body) == 2:
        if body[1] not in _TSY_FRACTION:
            raise ValueError(f"unrecognised coupon fraction in {label!r}")
        coupon = float(body[0]) + _TSY_FRACTION[body[1]]
    else:
        raise ValueError(f"unrecognised coupon in treasury label {label!r}")
    if not 0.0 <= coupon < 25.0:
        raise ValueError(f"implausible coupon {coupon} in {label!r}")
    return coupon, _TSY_MONTH[mon], 2000 + int(yr)


def _prev_coupon(d: datetime.date) -> datetime.date:
    m, y = d.month - 6, d.year
    if m <= 0:
        m += 12
        y -= 1
    try:
        return datetime.date(y, m, d.day)
    except ValueError:
        return datetime.date(y, m, 28)


def bond_price_and_duration(
    coupon: float,
    maturity: datetime.date,
    settlement: datetime.date,
    ytm_pct: float,
) -> Tuple[float, float, float]:
    """``(dirty, clean, modified_duration)`` for a semiannual Treasury.

    Street convention: every remaining cash flow discounted at ``y/2`` over its
    distance from settlement in half-periods, with the stub handled by the
    fraction of the current coupon period still to run; accrued interest straight
    ACT/ACT within the period. Modified duration is the Macaulay duration in
    YEARS divided by ``1 + y/2``.

    Written out here rather than taken from rateslib because it is the
    independent leg of a units check: a duration read out of the same library
    that priced the future would not be independent evidence, and this function's
    only inputs are the four numbers the basis store already quotes.

    Verified against the closed form for a par bond -- a 10-year 4% semiannual
    bond yielding 4% has Macaulay 8.3393 and modified 8.1757 years -- and, far
    more usefully, against 6,695 real CTD rows whose clean price it reproduces to
    a median 0.0015 price points. See :func:`load_ctd_basis_frame`.
    """
    y = float(ytm_pct) / 100.0
    if maturity <= settlement:
        return float("nan"), float("nan"), float("nan")

    dates: List[datetime.date] = []
    d = maturity
    while d > settlement:
        dates.append(d)
        d = _prev_coupon(d)
    dates.sort()

    nxt = dates[0]
    prev = _prev_coupon(nxt)
    period = (nxt - prev).days
    if period <= 0:
        return float("nan"), float("nan"), float("nan")
    elapsed = (settlement - prev).days
    w = 1.0 - elapsed / period                     # half-periods to the next coupon

    c = float(coupon) / 2.0
    dirty = 0.0
    weighted = 0.0
    last = dates[-1]
    for i, dt in enumerate(dates):
        cf = c + (100.0 if dt == last else 0.0)
        t_half = w + i
        df = (1.0 + y / 2.0) ** (-t_half)
        dirty += cf * df
        weighted += (t_half / 2.0) * cf * df       # time in years
    if dirty <= 0:
        return float("nan"), float("nan"), float("nan")
    macaulay = weighted / dirty
    modified = macaulay / (1.0 + y / 2.0)
    accrued = c * elapsed / period
    return float(dirty), float(dirty - accrued), float(modified)


def default_ust_basis_root() -> pathlib.Path:
    """Root of the offline UST delivery-basket / basis-report store.

    ``$ARBS_UST_FUTURE_STORE`` overrides; otherwise
    ``%LOCALAPPDATA%/ARBS/Cache/ust_future_store/basis_reports``. This is a
    READ-ONLY consumer of a cache another part of the repo fills; nothing here
    triggers a fetch, which is the whole point of using it for the units check.
    """
    override = os.environ.get(_UST_BASIS_ROOT_ENV)
    if override:
        return pathlib.Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return pathlib.Path(local) / "ARBS" / "Cache" / "ust_future_store" / "basis_reports"


_UST_SYMBOL_RE = re.compile(r"^(?P<root>[A-Z0-9]+?)(?P<month>[FGHJKMNQUVXZ])(?P<year>\d{2})$")
_UST_MONTH_CODE = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                   "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}


def _symbol_delivery_month(symbol: str) -> Optional[pd.Timestamp]:
    m = _UST_SYMBOL_RE.match(str(symbol).upper())
    if not m:
        return None
    return pd.Timestamp(2000 + int(m.group("year")), _UST_MONTH_CODE[m.group("month")], 28)


def load_ctd_basis_frame(
    root: Optional[Any] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    *,
    roots: Optional[Sequence[str]] = None,
    front_only: bool = True,
) -> pd.DataFrame:
    """Per (root, date) CTD state and futures DV01, read from the offline store.

    One row per contract per date, carrying the store's own ``futures_price`` and
    the ``is_ctd`` bond's ``clean_price`` / ``ytm`` / ``invoice_cf``, plus three
    columns computed here:

    ``ctd_mod_duration``, ``ctd_dirty_price``
        from :func:`bond_price_and_duration`, with the maturity day-of-month
        resolved by repricing (see ``price_err_pts``).
    ``fv01_points_per_bp``
        ``ModDur * Dirty / (1e4 * CF)`` -- the same formula
        ``USTFutureOptionMDP._compute_fv01`` uses, so the units check is measured
        against the repo's own definition of a futures DV01 rather than a new one.
    ``price_err_pts``
        ``|clean_calculated - clean_quoted|`` under the winning maturity day. This
        is the check on the check: it is the residual of an independent repricing
        of the CTD from its own yield, and if the bond maths or the label parse
        were wrong it would be large. Measured over the 4,235 front-contract rows:
        median **0.00155 price points** (~0.05 of a 32nd), 99th percentile
        0.00736; 0.00149 / 0.00727 over all 6,695 rows including back contracts.

    ``front_only`` keeps, per (root, date), the contract with the nearest
    delivery month still ahead -- the one a constant-maturity option quote
    references. Set False to see the whole delivery ladder.

    Raises :class:`ListedDataUnavailable` when the store is absent, since a
    caller receiving an empty frame would report "the DV01 check passed on 0
    rows".
    """
    base = pathlib.Path(root) if root is not None else default_ust_basis_root()
    if not base.exists():
        raise ListedDataUnavailable(
            f"UST basis-report store not found at {base}. It is a local cache filled "
            f"by USTFuturesMDP; set ${_UST_BASIS_ROOT_ENV} to point at one. This "
            "function never fetches."
        )
    want = None
    if roots is not None:
        want = {UST_BASIS_ROOT.get(UST_ROOT_ALIAS.get(str(r).upper(), str(r).upper()),
                                   str(r).upper()) for r in roots}

    cols = ["label", "clean_price", "ytm", "invoice_cf", "is_ctd", "futures_price",
            "trading_date", "settlement_date", "symbol", "session_minute"]
    rows: List[Dict[str, Any]] = []
    for f in sorted(glob.glob(str(base / "asset=*" / "date=*" / "*.parquet"))):
        m = re.search(r"asset=([A-Z0-9]+)", f)
        if not m:
            continue
        sym = m.group(1)
        basis_root = re.sub(r"[FGHJKMNQUVXZ]\d\d$", "", sym)
        if want is not None and basis_root not in want:
            continue
        dm = re.search(r"date=(\d{4}-\d{2}-\d{2})", f)
        if dm is not None:
            day = pd.Timestamp(dm.group(1))
            if start is not None and day < pd.Timestamp(start):
                continue
            if end is not None and day > pd.Timestamp(end):
                continue
        try:
            d = pd.read_parquet(f, columns=cols)
        except Exception:
            continue
        d = d[d["is_ctd"].astype(bool)]
        if d.empty:
            continue
        r = d.sort_values("session_minute").iloc[-1].to_dict()
        r["basis_root"] = basis_root
        rows.append(r)

    if not rows:
        raise ListedDataUnavailable(
            f"no CTD rows found under {base} for roots={sorted(want) if want else 'ALL'}"
        )
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["trading_date"])
    df["delivery_month"] = df["symbol"].map(_symbol_delivery_month)

    inv = {v: k for k, v in UST_BASIS_ROOT.items()}
    df["root"] = df["basis_root"].map(lambda r: inv.get(r, r))

    dur, dirty_px, err, mat_day = [], [], [], []
    for r in df.itertuples():
        settle = r.settlement_date
        settle = settle.date() if isinstance(settle, (pd.Timestamp, datetime.datetime)) else settle
        try:
            coupon, mm, yy = parse_treasury_label(r.label)
        except Exception:
            dur.append(np.nan); dirty_px.append(np.nan); err.append(np.nan); mat_day.append(0)
            continue
        best = None
        for day in _TSY_MATURITY_DAYS:
            try:
                mat = datetime.date(yy, mm, day)
            except ValueError:
                continue
            dd, cc, md = bond_price_and_duration(coupon, mat, settle, float(r.ytm))
            if not np.isfinite(cc):
                continue
            e = abs(cc - float(r.clean_price))
            if best is None or e < best[0]:
                best = (e, day, dd, md)
        if best is None:
            dur.append(np.nan); dirty_px.append(np.nan); err.append(np.nan); mat_day.append(0)
        else:
            err.append(best[0]); mat_day.append(best[1])
            dirty_px.append(best[2]); dur.append(best[3])
    df["ctd_mod_duration"] = dur
    df["ctd_dirty_price"] = dirty_px
    df["price_err_pts"] = err
    df["ctd_maturity_day"] = mat_day

    cf = df["invoice_cf"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["fv01_points_per_bp"] = np.where(
            cf > 0,
            df["ctd_mod_duration"].to_numpy(dtype=float)
            * df["ctd_dirty_price"].to_numpy(dtype=float) / 1e4 / np.where(cf > 0, cf, 1.0),
            np.nan)

    if front_only:
        df = df[df["delivery_month"] >= df["date"]]
        df = (df.sort_values(["root", "date", "delivery_month"])
                .groupby(["root", "date"], as_index=False).first())
    keep = ["root", "basis_root", "date", "symbol", "delivery_month", "label",
            "clean_price", "ctd_dirty_price", "ytm", "invoice_cf", "futures_price",
            "ctd_mod_duration", "fv01_points_per_bp", "price_err_pts",
            "ctd_maturity_day"]
    return df[[c for c in keep if c in df.columns]].sort_values(
        ["root", "date"]).reset_index(drop=True)


def ust_implied_ctd_duration(
    panel: pd.DataFrame,
    *,
    by_cm: bool = False,
) -> pd.DataFrame:
    """Modified duration implied by the panel's OWN two columns: ``1e4*ATM/ABPV``.

    The cheapest units check available, because it needs nothing but the panel::

        sigma_price(points) = ATM * P            (ATM is a lognormal PRICE vol)
        ABPV(bp)            = sigma_price / FV01
        FV01                = ModDur * P / 1e4   (to first order, CF cancels)
        =>  ModDur          = 1e4 * ATM / ABPV   -- the price P cancels

    So if the two columns are what the harvest says they are, this ratio must be
    a modified duration in years, must be stable through time, and must NOT move
    with the option's constant maturity (duration is a property of the bond, not
    of the option). All three hold: measured medians are TU 1.65, FV 3.91,
    TY 5.84, TN 7.68, US 11.65, UL 16.61 with a 1-8% coefficient of variation,
    and the 30/60/90-day answers agree to within 0.03 years for every root except
    TY (0.14, where the CTD switches inside the sample).

    Compare against ``UST_CTD_PROFILE[root]["ctd_mod_duration"]``, or against a
    per-date measurement from :func:`load_ctd_basis_frame`, via
    :func:`ust_units_check_dv01`.
    """
    need = {"ABPV", "ATM"}
    have = set(panel["value_type"].unique())
    if not need <= have:
        raise ValueError(f"panel must carry both ABPV and ATM rows; has {sorted(have)}")
    idx = ["date", "root", "cm_days"]
    w = panel.pivot_table(index=idx, columns="value_type", values="value").reset_index()
    w = w.dropna(subset=["ABPV", "ATM"])
    w = w[w["ABPV"] > 0]
    w["implied_mod_duration"] = 1e4 * w["ATM"].to_numpy(dtype=float) / w["ABPV"].to_numpy(dtype=float)

    keys = ["root", "cm_days"] if by_cm else ["root"]
    g = w.groupby(keys)["implied_mod_duration"]
    out = pd.DataFrame({
        "n": g.size(),
        "implied_mod_duration": g.median(),
        "p05": g.quantile(0.05),
        "p95": g.quantile(0.95),
        "std": g.std(),
    }).reset_index()
    out["reference_mod_duration"] = out["root"].map(
        lambda r: UST_CTD_PROFILE.get(r, {}).get("ctd_mod_duration", float("nan")))
    out["ratio_to_reference"] = out["implied_mod_duration"] / out["reference_mod_duration"]
    out["swap_point"] = out["root"].map(
        lambda r: UST_CTD_PROFILE.get(r, {}).get("swap_point"))
    return out


def ust_abpv_from_price_vol(
    atm_lognormal: float,
    futures_price: float,
    fv01_points_per_bp: float,
) -> float:
    """Lognormal futures-price vol -> normal yield vol in bp/yr.

    ``ABPV = ATM * P / FV01``: the lognormal vol times the price is the normal
    price vol in points per year, and dividing by the futures DV01 in points per
    bp converts points to bp of yield. Scalar and hand-checkable on purpose --
    ``ATM=0.10, P=120, FV01=0.12`` is ``12 points / 0.12`` = exactly ``100.0``
    bp/yr, and ``ATM=0.14, P=150, FV01=0.25`` is ``84.0`` to floating point
    (``0.14`` is not representable in binary, so that one lands on
    ``84.00000000000001`` and must be compared with a tolerance).

    The same three caveats as :func:`ust_price_vol_to_yield_vol` apply, and the
    first one is why this check tolerates a few percent rather than demanding
    equality: the delivery/CTD switch option is inside the quoted vol and not
    inside the DV01.
    """
    a, p, f = float(atm_lognormal), float(futures_price), float(fv01_points_per_bp)
    if not (np.isfinite(a) and np.isfinite(p) and np.isfinite(f)) or f <= 0:
        return float("nan")
    return abs(a) * p / f


def ust_units_check_dv01(
    panel: pd.DataFrame,
    ctd: pd.DataFrame,
    *,
    cm_days: int = 30,
) -> pd.DataFrame:
    """Date-matched implied-vs-actual ABPV, per root. **Step 1b of the units check.**

    Joins the constant-maturity panel to the per-date CTD frame from
    :func:`load_ctd_basis_frame` and computes
    ``ABPV_implied = ATM * futures_price / FV01`` against the quoted ABPV.

    Returns one row per root: the count, the two medians, the median ratio and
    its 5th/95th percentiles, and the measured-vs-implied modified duration side
    by side. Measured at ``cm_days=30``: UL 0.993, US 0.988, TN 0.983, TY 0.974,
    FV 0.955, TU 0.887 -- i.e. within ~1% for the two long-end roots the strategy
    uses, degrading towards the short end where the price/yield map's curvature
    is largest relative to duration.
    """
    idx = ["date", "root", "cm_days"]
    w = panel.pivot_table(index=idx, columns="value_type", values="value").reset_index()
    w = w[w["cm_days"] == int(cm_days)].dropna(subset=["ABPV", "ATM"])

    c = ctd[["root", "date", "futures_price", "fv01_points_per_bp",
             "ctd_mod_duration", "label", "price_err_pts"]]
    j = w.merge(c, on=["root", "date"], how="inner").dropna(subset=["fv01_points_per_bp"])
    if j.empty:
        raise ValueError("no (root, date) overlap between the CM panel and the CTD frame")

    j["abpv_implied"] = (j["ATM"].to_numpy(dtype=float)
                         * j["futures_price"].to_numpy(dtype=float)
                         / j["fv01_points_per_bp"].to_numpy(dtype=float))
    j["ratio"] = j["abpv_implied"] / j["ABPV"]
    j["implied_mod_duration"] = 1e4 * j["ATM"] / j["ABPV"]

    g = j.groupby("root")
    out = pd.DataFrame({
        "n": g.size(),
        "abpv_actual": g["ABPV"].median(),
        "abpv_implied": g["abpv_implied"].median(),
        "ratio": g["ratio"].median(),
        "ratio_p05": g["ratio"].quantile(0.05),
        "ratio_p95": g["ratio"].quantile(0.95),
        "ctd_mod_duration_measured": g["ctd_mod_duration"].median(),
        "ctd_mod_duration_implied": g["implied_mod_duration"].median(),
        "fv01_points_per_bp": g["fv01_points_per_bp"].median(),
        "futures_price": g["futures_price"].median(),
        "ctd_reprice_err_pts": g["price_err_pts"].median(),
    }).reset_index()
    out["cm_days"] = int(cm_days)
    return out


def ust_units_check_vs_swaptions(
    panel: pd.DataFrame,
    otc_panel: pd.DataFrame,
    pairs: Sequence[Tuple[str, int, str, str]],
    *,
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Listed ABPV against matched swaption ATMF nodes. **Step 1a of the units check.**

    ``pairs`` is ``(root, cm_days, swaption_expiry, swaption_tenor)`` -- e.g.
    ``("US", 30, "1M", "30Y")``, a 30-day constant-maturity option on the bond
    future against the 1Mx30Y OTC node. ``otc_panel`` is
    ``swaption_cube.load_vol_panel``'s output.

    One row per pair: the overlap count, both medians in bp/yr AND bp/day, the
    level ratio, the correlation of levels and of daily CHANGES, and the mean
    difference. Both correlations are reported because they answer different
    questions -- levels can correlate through a shared trend while the two
    markets move independently day to day, and only the changes correlation
    would reveal that.

    A units error shows up as a ratio far from 1 (a factor of 10 for a
    percent/decimal slip, ~16 for an annual/daily slip). Measured here the worst
    pair is 1.13 and the best 1.01.
    """
    from RVUtils.ConvexityRV.swaption_cube import atmf_vol_series

    sq = math.sqrt(float(business_days_per_year))
    rows: List[Dict[str, Any]] = []
    for root, cm, exp, ten in pairs:
        r = UST_ROOT_ALIAS.get(str(root).upper(), str(root).upper())
        listed = ust_cm_series(panel, r, cm, value_type="ABPV")
        otc = atmf_vol_series(otc_panel, exp, ten)
        j = pd.concat([listed.rename("listed"), otc.rename("otc")], axis=1).dropna()
        if j.empty:
            rows.append({"listed_symbol": f"{r}_{int(cm)}", "otc_node": f"{exp}x{ten}",
                         "n": 0})
            continue
        dl, do = j["listed"].diff(), j["otc"].diff()
        rows.append({
            "listed_symbol": f"{r}_{int(cm)}",
            "otc_node": f"{exp}x{ten}",
            "swap_point": UST_CTD_PROFILE.get(r, {}).get("swap_point"),
            "n": int(len(j)),
            "first": j.index.min().date().isoformat(),
            "last": j.index.max().date().isoformat(),
            "median_listed_bp_yr": float(j["listed"].median()),
            "median_otc_bp_yr": float(j["otc"].median()),
            "median_listed_bp_day": float(j["listed"].median()) / sq,
            "median_otc_bp_day": float(j["otc"].median()) / sq,
            "ratio": float(j["listed"].median() / j["otc"].median()),
            "r_level": float(j["listed"].corr(j["otc"])),
            "r_change": float(dl.corr(do)),
            "mean_diff_bp_yr": float((j["listed"] - j["otc"]).mean()),
            "mean_diff_bp_day": float((j["listed"] - j["otc"]).mean()) / sq,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# REAL LISTED CONTRACTS (as opposed to constant maturity)
# ---------------------------------------------------------------------------
# Everything above this line is CONSTANT MATURITY: ``US_30`` is QuikStrike's
# interpolation across the expiry ladder, so it has no strike dimension and no
# expiry. That is enough for the breakeven-vol signal and not enough to size a
# straddle whose premium equals the curve carry, which needs a real contract
# with a real expiry, strike and premium.
#
# ``listed_contracts`` is the real-contract panel -- ``USM26``, ``TYZ25``,
# ``SFRH27``, each row carrying its own ``expiry_date`` and ``tte_years`` --
# built by ``scripts/harvest_listed_contract_vol.py``. It lives in its own
# module so that this one, and its callers in ``strat1_listed``,
# ``strat1_threeway`` and ``strat1_curve_gamma``, are untouched by it; the names
# are re-exported here so ``from ... import listed_vol`` remains the single
# entry point.
#
# The CM panel is the CONTROL for the real one, not a thing it replaces.
# Measured at matched time to expiry over 1,917 dates: real/CM ratio 0.999-1.000
# with a median absolute difference of 0.26 bp (US_30, ladder-interpolated), and
# the two diverging as a contract ages exactly as they should -- ratio 1.002 at
# 25-35 days to expiry rising to 1.066 at 150-250 days.
from RVUtils.ConvexityRV.listed_contracts import (  # noqa: E402,F401
    ListedContractsUnavailable,
    LISTED_CONTRACT_PANEL,
    SMILE_VALUE_TYPES,
    abpv_atm_scale,
    cm_replication_series,
    compare_to_cm,
    contract_coverage_report,
    default_listed_contract_path,
    expiry_ladder,
    interpolate_across_ladder,
    listed_contract_wide,
    load_listed_contract_panel,
    select_by_tte,
    smile_in_bp_yr,
    tte_matched_series,
    units_report,
)

__all__ += [
    # --------------------------------------------- real listed contracts
    "ListedContractsUnavailable",
    "LISTED_CONTRACT_PANEL",
    "SMILE_VALUE_TYPES",
    "default_listed_contract_path",
    "load_listed_contract_panel",
    "listed_contract_wide",
    "expiry_ladder",
    "select_by_tte",
    "tte_matched_series",
    "interpolate_across_ladder",
    "cm_replication_series",
    "abpv_atm_scale",
    "smile_in_bp_yr",
    "units_report",
    "compare_to_cm",
    "contract_coverage_report",
]
