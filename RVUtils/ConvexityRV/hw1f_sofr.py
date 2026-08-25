"""Hull-White 1-factor convexity for SOFR futures -- the compounded payoff.

``holee.py`` prices the adjustment Citi's screen prints: ``1/2 sigma^2 T1^2``,
no mean reversion, one volatility. This module is the enhanced model behind
``<LABEL>_MODEL2``. It changes three things, and each one is a separate,
checkable claim:

1. **Mean reversion.** Ho-Lee is Hull-White with ``a = 0`` (Burgess, SSRN
   2850320). Every formula here reduces to the Ho-Lee one as ``a -> 0``, which
   is a test, not a remark.

2. **The payoff SR3 actually settles on.** An SR3 contract settles on the
   *daily-compounded* SOFR over its reference quarter, not on a forward-looking
   term rate. That is a different expectation and it has a different time
   weight. Three payoffs are implemented and they are NOT interchangeable --
   in the ``a -> 0`` limit,

   =============  ==========================  =========================
   payoff         instrument                  Ho-Lee limit
   =============  ==========================  =========================
   ``compounded`` SR3 / SOFR 3M               ``1/2 sigma^2 (T2^2 - tau^2/3)``
   ``average``    SR1 / ZQ (arithmetic mean)  ``1/2 sigma^2 (T1 T2 + tau^2/3)``
   ``term``       ED / LIBOR (forward-looking) ``1/2 sigma^2 T1 T2``
   =============  ==========================  =========================

   Hull's textbook ``T1 T2`` is the **term** row; Citi's ``T1^2`` is smaller
   still. At ``T1 = 3.5y``, ``tau = 0.25``, ``sigma = 100bp`` those are 7.02,
   6.56 and 6.13 bp -- a 15% spread on the same volatility, which is larger
   than most of the richness anyone trades this against.

3. **A volatility mapping that knows what it was calibrated to.** ``sigma``
   here is the Hull-White short-rate volatility, not a quoted swaption vol.
   :func:`sigma_from_normal_vol` converts one to the other so the model
   reprices the ATM straddle it was calibrated to; at ``a = 0`` the conversion
   is the identity for any tail, which is why ``holee.py`` can take the quote
   directly.

   The conversion is also why mean reversion is a **second-order** knob here.
   It damps the adjustment (-13% at ``a = 3%`` on Golds at a fixed short-rate
   vol) but it also raises the sigma implied by a fixed ATM quote, and the two
   nearly cancel: recalibrated, ``a = 3%`` moves the level +2.5%. The payoff
   convention moves it 15%. Anyone reaching for ``a`` to explain a rich/cheap
   signal is turning the wrong dial.

**Why no smile.** Piterbarg and Renedo (SSRN 610223) show the smile matters for
the convexity adjustment, and Turfus and Romero-Bermudez (SSRN 4708715) give a
skew/smile-aware SOFR futures price. Turfus's own summary of that work, on the
"convexity - SOFR futures options" thread, is::

    "Basically I would advise using a Hull-White ATM-calibrated model for the
     futures convexity. The smile/skew makes no difference until you look at
     options."

So the default is ATM-calibrated Hull-White. A caller who wants a smile-implied
effective vol passes it in -- every entry point takes ``sigma`` and nothing
here reads a surface.

**What is deliberately left out**, because ``holee.py`` leaves it out too and
the two are compared against the same observed number:

* the forward discount factor: the exact compounded adjustment carries a
  ``1/D(T1,T2) = 1 + tau f`` factor, worth ``+1%`` at 4% rates. Pass
  ``fwd_discount`` to put it back;
* the ``(1 + S)`` level term in the swaption vol mapping, worth up to ``8%`` on
  the adjustment at 4% rates -- ``holee.py`` omits it identically by treating
  the quoted normal vol as the short-rate vol;
* ACT/365 vs the contract's own ACT/360 quoting basis (~1.4% on the level).

Every function is in **decimal rate units** internally with explicit ``_bp``
helpers at the boundary, exactly as ``holee.py`` does, because mixing the two
is the classic way to get a 100x error in a convexity number and not notice.

References
----------
Burgess, N. (2015). *The Hull-White 1 Factor Convexity Adjustment and the
    Special Case when the Hull-White and Ho-Lee Models are Equivalent.*
    SSRN 2850320. -- the HW1F term-payoff adjustment and its Ho-Lee limit.
Garcia-Lorite, D. and Merino, R. (2023). *Convexity adjustments a la
    Malliavin.* arXiv:2304.13402, Theorem 4.3 / Example 4.6. -- the OIS-futures
    (compounded and average) adjustment, **exact for Hull-White** by their
    Remark 4.4. Two transcription errors in that example are worked around
    here and documented in :func:`drift_term` and :func:`compounding_var`.
Turfus, C. and Romero-Bermudez, A. (2024). *Analytic Pricing of SOFR Futures
    Contracts with Smile and Skew.* SSRN 4708715. -- the SOFR framing, and
    Mercurio's Hull-White baseline this module implements.
Piterbarg, V. and Renedo, M. (2004). *Eurodollar Futures Convexity Adjustments
    in Stochastic Volatility Models.* SSRN 610223. -- why the smile matters,
    and the model-independent variance a caller can inject.
Hull, J. C. *Options, Futures and Other Derivatives*, 9th ed., Ch. 31.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

__all__ = [
    "ACCRUAL_3M",
    "PAYOFFS",
    "b_factor",
    "drift_term",
    "compounding_var",
    "futures_ca",
    "futures_ca_bp",
    "pack_ca",
    "pack_ca_bp",
    "holee_limit_ca",
    "holee_limit_ca_bp",
    "sigma_from_normal_vol",
    "sigma_from_normal_vol_bp",
    "normal_vol_from_sigma",
]

#: Accrual length of a 3M SOFR contract in years. Only a default: every entry
#: point takes ``t2`` explicitly, because the IMM-to-IMM accrual actually runs
#: 0.244-0.255 ACT/365 across the strip. That 2.2% spread is 0.28% on the
#: adjustment -- the weight is quadratic in ``T2``, not in ``tau`` -- which is
#: small but an order of magnitude above what the cache round-trips to.
ACCRUAL_3M = 0.25

#: The three settlement conventions this module prices. See the module note.
PAYOFFS = ("compounded", "average", "term")

#: Below this the closed forms lose too many digits to cancellation and the
#: series takes over. Chosen so both sides are good to ~1e-9 relative AT the
#: crossover, which ``test_convexity_rv_hw1f_sofr`` checks by evaluating both
#: branches either side of it.
_SERIES_ATAU = 1e-3


def b_factor(a: float, t: float) -> float:
    """``B(a, t) = (1 - e^{-a t}) / a``, the Hull-White duration factor.

    ``expm1`` rather than ``1 - exp``: the difference is the whole quantity
    when ``a t`` is small, and ``1 - exp(-1e-9)`` loses nine digits before the
    division makes it back. At ``a = 0`` this is ``t``.
    """
    a = float(a)
    t = float(t)
    if a == 0.0:
        return t
    return -math.expm1(-a * t) / a


def _j1(a: float, tau: float) -> float:
    """``int_0^tau B(a, w) dw``. Closed form ``(tau - B(tau)) / a``."""
    a, tau = float(a), float(tau)
    if abs(a) * tau < _SERIES_ATAU:
        u = a * tau
        return tau ** 2 * (0.5 - u / 6.0 + u * u / 24.0 - u ** 3 / 120.0)
    return (tau - b_factor(a, tau)) / a


def _j2(a: float, tau: float) -> float:
    """``int_0^tau B(a, w)^2 dw``.

    Closed form ``(tau - 2 B(tau) + B_2(tau)) / a^2`` with
    ``B_2 = (1 - e^{-2 a tau}) / (2a)``. That bracket is ``O(a^2 tau^3)`` built
    from terms of size ``tau``, so it is the one place in this module where the
    closed form is not usable all the way down and the series is not decoration.
    """
    a, tau = float(a), float(tau)
    if abs(a) * tau < _SERIES_ATAU:
        u = a * tau
        return tau ** 3 * (1.0 / 3.0 - u / 4.0 + 7.0 * u * u / 60.0 - u ** 3 / 24.0)
    b2 = -math.expm1(-2.0 * a * tau) / (2.0 * a)
    return (tau - 2.0 * b_factor(a, tau) + b2) / (a * a)


def drift_term(sigma: float, a: float, t1: float, t2: float) -> float:
    """``mu = E^Q[int_{T1}^{T2} r ds] + log D(T1,T2)``, the Hull-White drift.

    This is the deterministic piece by which the risk-neutral expectation of
    the accrued short rate exceeds what the initial curve implies -- Hull-White
    puts it in ``alpha(t) = f(0,t) + sigma^2 B(0,t)^2 / 2``, so::

        mu = (sigma^2 / 2) * int_{T1}^{T2} B(0,s)^2 ds

    Written as ``B(0,s) = B1 + e^{-a T1} B(w)`` with ``s = T1 + w``, which moves
    every cancellation-prone term into :func:`_j1` / :func:`_j2` where the
    series guards live, and leaves the ``T1`` dependence in ``expm1``-stable
    factors.

    Identical to ``E^Q[I(t0,t1)]`` in Example 4.6 of Garcia-Lorite and Merino
    (2023) -- the closed form there expands to the same expression term for
    term, which is the check that this is the standard result and not a private
    derivation.
    """
    sigma, a, t1, t2 = float(sigma), float(a), float(t1), float(t2)
    tau = t2 - t1
    if tau <= 0.0:
        raise ValueError(f"t2 must exceed t1; got t1={t1}, t2={t2}")
    b1 = b_factor(a, t1)
    e1 = math.exp(-a * t1)
    phi2 = b1 * b1 * tau + 2.0 * b1 * e1 * _j1(a, tau) + e1 * e1 * _j2(a, tau)
    return 0.5 * sigma * sigma * phi2


def compounding_var(sigma: float, a: float, t1: float, t2: float) -> float:
    """``Var^Q(int_{T1}^{T2} x_s ds)`` for the Hull-White state variable ``x``.

    ``x_s = sigma int_0^s e^{-a(s-u)} dW_u``, so the integral over the accrual
    is Gaussian with

    ``Var = sigma^2 [ B(tau)^2 (1 - e^{-2 a T1}) / (2a) + int_0^tau B(w)^2 dw ]``

    -- the first term is diffusion accumulated BEFORE the reference period
    starts, the second is diffusion inside it.

    This is ``int Gamma^2`` of Garcia-Lorite and Merino (2023) eq (19), whose
    definition matches this integrand exactly. Their Example 4.6 prints
    ``Gamma`` with an ``e^{-ks}`` prefactor where eq (19) gives ``e^{+ks}``, and
    their eq (17) prints ``exp(-1/2 int Gamma^2)`` where Jensen requires
    ``+1/2``: inverting their own eq (17) into their eq (18) reproduces (18)'s
    minus sign only if (17) carries a plus. Both are transcription errors; the
    Monte-Carlo check in ``test_convexity_rv_hw1f_sofr`` is what settles it.
    """
    sigma, a, t1, t2 = float(sigma), float(a), float(t1), float(t2)
    tau = t2 - t1
    if tau <= 0.0:
        raise ValueError(f"t2 must exceed t1; got t1={t1}, t2={t2}")
    bt = b_factor(a, tau)
    pre = bt * bt * (t1 if a == 0.0 else -math.expm1(-2.0 * a * t1) / (2.0 * a))
    return sigma * sigma * (pre + _j2(a, tau))


def futures_ca(
    sigma: float,
    t1: float,
    t2: float,
    a: float,
    *,
    payoff: str = "compounded",
    fwd_discount: float = 1.0,
) -> float:
    """Futures rate minus forward rate, in decimal rate units.

    ``sigma`` is the Hull-White SHORT-RATE volatility (see
    :func:`sigma_from_normal_vol`), ``a`` the mean reversion, ``t1``/``t2`` the
    reference period in years from the as-of date.

    ``payoff="compounded"`` (SR3, the default) is exact under Hull-White up to
    the continuous-compounding approximation of daily compounding::

        futures = (1/tau) (E^Q[exp(int r)] - 1)
                = (1/tau) ((1/D) exp(mu + v/2) - 1)
        forward = (1/tau) (1/D - 1)
        CA      = (1/tau) (1/D) (exp(mu + v/2) - 1)

    ``payoff="average"`` (SR1/ZQ) is ``mu / tau``: an arithmetic average of the
    overnight rate has no Jensen term of its own, so its whole adjustment is
    the drift. **Its comparator is the forward AVERAGE rate**
    ``(1/tau) int_{T1}^{T2} f(0,s) ds``, not the simple OIS forward
    ``(1/D - 1)/tau`` -- those two differ by ``tau f^2 / 2`` (about 2bp at 4%),
    which is a quoting convention, not convexity, and would swamp the number if
    it were folded in silently.

    ``payoff="term"`` (ED/LIBOR) is Burgess eq (4), kept because it is what
    QuantLib's ``HullWhite.convexityBias`` prices and so is the one branch an
    independent implementation can check exactly.

    ``fwd_discount`` is ``D(T1,T2) = P(0,T2)/P(0,T1)``; the default of 1.0 drops
    a ``1 + tau f`` factor (+1% at 4% rates) so that the number is comparable
    with ``holee.py``, which drops it too. Pass the real forward discount factor
    to put it back.
    """
    if payoff not in PAYOFFS:
        raise ValueError(f"payoff must be one of {PAYOFFS}; got {payoff!r}")
    sigma, t1, t2, a = float(sigma), float(t1), float(t2), float(a)
    tau = t2 - t1
    if tau <= 0.0:
        raise ValueError(f"t2 must exceed t1; got t1={t1}, t2={t2}")
    if t1 < 0.0:
        raise ValueError(f"t1 must be non-negative; got {t1}")
    if a < 0.0:
        raise ValueError(f"mean reversion must be non-negative; got {a}")
    if sigma < 0.0:
        raise ValueError(f"sigma must be non-negative; got {sigma}")

    if payoff == "term":
        bt, b1 = b_factor(a, tau), b_factor(a, t1)
        pre = t1 / 2.0 if a == 0.0 else -math.expm1(-2.0 * a * t1) / (4.0 * a)
        return (bt / tau) * sigma * sigma * (bt * pre + 0.5 * b1 * b1)

    mu = drift_term(sigma, a, t1, t2)
    if payoff == "average":
        return mu / tau
    v = compounding_var(sigma, a, t1, t2)
    return math.expm1(mu + 0.5 * v) / (tau * float(fwd_discount))


def futures_ca_bp(
    sigma_bp: float,
    t1: float,
    t2: float,
    a: float,
    *,
    payoff: str = "compounded",
    fwd_discount: float = 1.0,
) -> float:
    """:func:`futures_ca` with the volatility in bp/yr and the answer in bp."""
    return 1e4 * futures_ca(float(sigma_bp) / 1e4, t1, t2, a,
                            payoff=payoff, fwd_discount=fwd_discount)


def holee_limit_ca(sigma: float, t1: float, t2: float, *,
                   payoff: str = "compounded") -> float:
    """The ``a -> 0`` limit in closed form, decimal rate units.

    Not used to price -- :func:`futures_ca` handles ``a = 0`` on its own. This
    exists so the tests can assert the limit against an expression derived on
    paper rather than against the same code path with a small number in it.

    **Linearised**, as the literature prints it. The compounded branch of
    :func:`futures_ca` keeps the ``exp`` curvature, so it exceeds this by a
    factor ``1 + z/2`` with ``z = mu + v/2 ~ 1.8e-4`` -- 0.009% at a 100bp vol,
    which is why the limit tests carry a relative tolerance rather than an
    absolute one.
    """
    if payoff not in PAYOFFS:
        raise ValueError(f"payoff must be one of {PAYOFFS}; got {payoff!r}")
    sigma, t1, t2 = float(sigma), float(t1), float(t2)
    tau = t2 - t1
    half_s2 = 0.5 * sigma * sigma
    if payoff == "term":
        return half_s2 * t1 * t2
    if payoff == "average":
        return half_s2 * (t1 * t2 + tau * tau / 3.0)
    return half_s2 * (t2 * t2 - tau * tau / 3.0)


def holee_limit_ca_bp(sigma_bp: float, t1: float, t2: float, *,
                      payoff: str = "compounded") -> float:
    """:func:`holee_limit_ca` with the volatility in bp/yr and answer in bp."""
    return 1e4 * holee_limit_ca(float(sigma_bp) / 1e4, t1, t2, payoff=payoff)


def sigma_from_normal_vol(vol: float, a: float, expiry: float,
                          tail: float = 1.0) -> float:
    """Hull-White short-rate vol that reprices an ATM normal swaption quote.

    Under Hull-White a swap rate is Gaussian with
    ``Var(S_T) = (dS/dx)^2 Var(x_T)``, and

    ``dS/dx = B(a, tail) / tail``

    (dropping the ``1 + S`` level term, see the module note). For a
    single-payment tail that is exact; for a multi-payment one it is what the
    annuity-weighted form collapses to under the same flat-curve approximation
    used throughout. Matching to the quoted ``vol^2 * T`` gives

    ``sigma = vol * sqrt(T / V(T)) * tail / B(a, tail)``,
    ``V(T) = (1 - e^{-2 a T}) / (2a)``

    which is **the identity at a = 0 for ANY tail** -- so ``MODEL`` feeding a
    quoted normal vol straight into Ho-Lee is this mapping's own
    zero-mean-reversion case, not a different convention.

    **The ``/ tail`` is load-bearing and it hides.** With ``tail = 1`` it is 1,
    so a version without it prices a 1Y-tail straddle correctly and is out by
    ``1/tail`` -- 4x in sigma, 16x in the adjustment -- at a 3M tail, while
    staying discontinuous at ``a = 0``. The continuity test across ``a -> 0`` at
    a NON-unit tail is what catches that; a 1Y-tail test cannot.

    Direction, because it is easy to assume backwards: a longer tail moves LESS
    per unit of short-rate volatility under mean reversion, so reproducing the
    same quoted vol needs a LARGER sigma.
    """
    vol, a, expiry, tail = float(vol), float(a), float(expiry), float(tail)
    if expiry <= 0.0:
        raise ValueError(f"expiry must be positive; got {expiry}")
    if tail <= 0.0:
        raise ValueError(f"tail must be positive; got {tail}")
    if a == 0.0:
        return vol
    var_x = -math.expm1(-2.0 * a * expiry) / (2.0 * a)
    return vol * math.sqrt(expiry / var_x) * tail / b_factor(a, tail)


def sigma_from_normal_vol_bp(vol_bp: float, a: float, expiry: float,
                             tail: float = 1.0) -> float:
    """:func:`sigma_from_normal_vol` in bp/yr in and bp/yr out."""
    return 1e4 * sigma_from_normal_vol(float(vol_bp) / 1e4, a, expiry, tail)


def normal_vol_from_sigma(sigma: float, a: float, expiry: float,
                          tail: float = 1.0) -> float:
    """Inverse of :func:`sigma_from_normal_vol`. Round-trip is an identity."""
    sigma, a, expiry, tail = float(sigma), float(a), float(expiry), float(tail)
    if expiry <= 0.0:
        raise ValueError(f"expiry must be positive; got {expiry}")
    if a == 0.0:
        return sigma
    var_x = -math.expm1(-2.0 * a * expiry) / (2.0 * a)
    return sigma * math.sqrt(var_x / expiry) * b_factor(a, tail) / tail


def pack_ca(
    sigmas: Sequence[float] | float,
    t1s: Sequence[float],
    t2s: Sequence[float],
    a: float,
    *,
    payoff: str = "compounded",
    fwd_discounts: Sequence[float] | float = 1.0,
) -> float:
    """Mean of the member contracts' adjustments, decimal rate units.

    A pack rate is the simple average of its four contract rates, so its
    adjustment is the simple average of the four contract adjustments -- the
    same identity ``holee.pack_ca`` uses. Unlike Ho-Lee, each contract may carry
    its own volatility (Hull-White's is a term structure once you calibrate per
    expiry), so ``sigmas`` may be a scalar or one per contract.
    """
    t1a = np.asarray(t1s, dtype=float)
    t2a = np.asarray(t2s, dtype=float)
    if t1a.size == 0:
        raise ValueError("no contracts")
    if t1a.shape != t2a.shape:
        raise ValueError(f"t1s/t2s length mismatch: {t1a.shape} vs {t2a.shape}")
    sig = np.broadcast_to(np.asarray(sigmas, dtype=float), t1a.shape)
    dis = np.broadcast_to(np.asarray(fwd_discounts, dtype=float), t1a.shape)
    vals = [futures_ca(s, t1, t2, a, payoff=payoff, fwd_discount=d)
            for s, t1, t2, d in zip(sig, t1a, t2a, dis)]
    return float(np.mean(vals))


def pack_ca_bp(
    sigmas_bp: Sequence[float] | float,
    t1s: Sequence[float],
    t2s: Sequence[float],
    a: float,
    *,
    payoff: str = "compounded",
    fwd_discounts: Sequence[float] | float = 1.0,
) -> float:
    """:func:`pack_ca` with volatilities in bp/yr and the answer in bp."""
    sig = np.asarray(sigmas_bp, dtype=float) / 1e4
    return 1e4 * pack_ca(sig, t1s, t2s, a, payoff=payoff,
                         fwd_discounts=fwd_discounts)
