"""The sign convention. Every other module in this package defers to this one.

This file exists because sign conventions are where direction implementations
silently break, and because the failure is invisible: a flipped sign produces a
complete, plausible ladder that is exactly wrong. ``stir_flow/ladder.py``'s own
HISTORY comment records a per-space sign dict that inverted three of four
bucket spaces and was caught only by a row count in a persisted table.

THE CONVENTION
--------------

::

    customer pays fixed  ->  dealer RECEIVED fixed
                         ->  dealer is long duration
                         ->  the pending hedge is SELLING futures
                         ->  delta_dv01 > 0

and the probability this package produces is always

::

    p = p(customer paid fixed) = p(dealer received fixed)

so ``p > 0.5`` pushes the ladder positive. Inherited unchanged from
``stir_flow/ladder_conventions.py`` so the tie-out means something.

TWO POLARITIES, DELIBERATELY DISTINGUISHED
------------------------------------------

There are two per-leg sign vectors in play and they are opposites. Conflating
them is the single most likely bug in this package, so they are named
differently and never share a variable:

``pay_signs``
    ``+1`` = this party PAYS fixed on this leg. Used for *orientation* and for
    the quoted price, because a price is what the payer pays.

``received_signs``
    ``+1`` = this party RECEIVED fixed on this leg. Used for *risk*, because
    the persisted ladder convention is ``+ = dealer received = long duration``.
    This is the polarity of ``stir_flow.ladder_conventions.dealer_leg_signs``,
    and :func:`dealer_received_signs` reproduces that function exactly (pinned
    by test).

They are related by a single negation, applied in exactly one place
(:func:`dealer_received_signs`).

THE GENERAL RULE
----------------

A unit has a **base orientation** ``o`` (``pay_signs``) and **quote weights**
``q`` with ``sign(q_i) == o_i``, chosen together so that

::

    P = sum(q_i * R_i)

is *the price paid by the base-orientation party*. Then, for every structure:

::

    P_traded > P_mid  =>  the base party overpaid
                      =>  the base party is the CUSTOMER
                      =>  the dealer holds -o

The choice of base orientation is arbitrary **provided** ``P`` is defined as
the price the base party pays -- the inferred global sign absorbs it. Only that
internal consistency has to be right, and it is unit-tested per structure
against the frozen predecessor.

This is what lets one inferred bit produce the whole signed key-rate profile,
and it is why there is no "direction" to name for a 17-leg package.
"""
from __future__ import annotations

# --- the dealer's global side ---------------------------------------------
DEALER_RECEIVED = 1
DEALER_PAID = -1

#: Structures whose base orientation is fixed by market convention.
OUTRIGHT = "OUTRIGHT"
CURVE = "CURVE"
FLY = "FLY"
PKG = "PKG"

#: The two inference rules. They use DIFFERENT base orientations for the same
#: unit, which is not an inconsistency -- see :func:`base_orientation`.
RULE_RATE = "RATE_VS_MID"
RULE_UPFRONT = "NPV_VS_UPFRONT"

# rateslib's solver delta is dNPV per +1bp bump of the instrument's own *rate*,
# so a payer swap has POSITIVE raw delta. Exactly one flip lands the persisted
# convention (+ = dealer long futures-equivalent = dealer RECEIVED fixed).
# ONE constant for EVERY bucket space -- `stir_flow/ladder.py` carried a
# per-space dict here once and it inverted three of the four spaces.
RL_DELTA_TO_FUTURES_EQ = -1.0


def base_orientation(kind: str, n_legs: int, rule: str) -> tuple[int, ...]:
    """``pay_signs`` for the base-orientation party: ``+1`` = pays fixed.

    The rate rule and the upfront rule genuinely need different orientations
    for the same unit, and that is not a bug:

    * the **rate** rule reads a *quoted structure price*, so its orientation is
      the structure's own (a curve is one payer and one receiver, by
      construction);
    * the **upfront** rule reads a *net NPV against a single fee*, so it works
      in the net-fixed frame where every leg carries the same sign. That is
      what ``stir_flow/ladder_conventions.dealer_leg_signs`` does for
      ``NPV_VS_UPFRONT`` (``[recv] * n_legs``), and it is right: one fee cannot
      resolve the internal orientation of a multi-leg package, only the
      package's net side.

    Legs are assumed sorted by ``(expiration_date, effective_date, trade_id)``,
    the total order ``trade_selection.build_units`` imposes -- so for a CURVE
    index 0 is the front leg, and for a FLY index 1 is the belly.
    """
    if n_legs < 1:
        raise ValueError(f"a unit needs at least one leg, got {n_legs}")
    if rule == RULE_UPFRONT:
        return (1,) * n_legs
    if rule != RULE_RATE:
        raise ValueError(f"unknown rule {rule!r}")
    if kind == OUTRIGHT and n_legs == 1:
        return (1,)
    if kind == CURVE and n_legs == 2:
        return (-1, 1)          # pay the back leg, receive the front
    if kind == FLY and n_legs == 3:
        return (-1, 1, -1)      # pay the belly, receive the wings
    raise UnorientableUnit(
        f"no market quote convention fixes the base orientation of a "
        f"{kind} with {n_legs} legs under the rate rule"
    )


def quote_weights(kind: str, n_legs: int, rule: str) -> tuple[float, ...]:
    """``q`` such that ``P = sum(q_i * R_i)`` is the price the base party pays.

    ``sign(q_i) == base_orientation(...)[i]`` always; the magnitudes are the
    market's quote coefficients, which are NOT the DV01 hedge ratios. A fly is
    quoted ``2*belly - front - back`` whatever its DV01-neutral ratios happen
    to be.
    """
    o = base_orientation(kind, n_legs, rule)
    if rule == RULE_UPFRONT:
        # The upfront rule does not use a quoted price -- it compares a net NPV
        # to a fee. Returning the orientation itself keeps the invariant
        # sign(q) == o for callers that assert it, and any caller that actually
        # forms a price from these weights is using the wrong rule.
        return tuple(float(s) for s in o)
    if kind == FLY and n_legs == 3:
        return (-1.0, 2.0, -1.0)
    return tuple(float(s) for s in o)


def structure_price(rates_pct, kind: str, n_legs: int, rule: str) -> float:
    """The unit's price in **basis points**, from per-leg rates in **percent**.

    Percent in, bp out, matching ``stir_flow/classifier.py``, which multiplies
    by 100 at exactly this boundary. Keeping the conversion here means no other
    module has to remember which side of it it is on.
    """
    q = quote_weights(kind, n_legs, rule)
    if len(rates_pct) != len(q):
        raise ValueError(f"got {len(rates_pct)} rates for {len(q)} legs")
    return sum(w * float(r) for w, r in zip(q, rates_pct)) * 100.0


def dealer_side(price_to_mid_bps: float) -> int:
    """The dealer's global side from the unit's deviation from mid.

    ``P_traded > P_mid`` means the base party overpaid, so the base party is
    the customer and the dealer holds ``-o``.

    **There is a zero branch, on purpose.** ``stir_flow/classifier.py`` ends
    ``RECEIVED if s2m > 0 else PAID`` with no zero case, so the sign of a
    1e-13 float picks the side; the tie-out found three units on a single day
    sitting at exactly ``0.0``, all silently labelled PAID. Here an exact tie
    returns 0, and callers must treat 0 as "no call" rather than a side.
    """
    if price_to_mid_bps > 0:
        return DEALER_RECEIVED
    if price_to_mid_bps < 0:
        return DEALER_PAID
    return 0


def dealer_received_signs(kind: str, n_legs: int, rule: str,
                          dealer_sign: int) -> tuple[int, ...]:
    """Per-leg ``received_signs`` for the dealer: ``+1`` = dealer received fixed.

    The one place the two polarities meet. ``dealer_sign`` is
    :data:`DEALER_RECEIVED` / :data:`DEALER_PAID` from :func:`dealer_side`.

    Pinned by test to reproduce
    ``stir_flow.ladder_conventions.dealer_leg_signs`` exactly on every case
    that function supports.

    **The two negations cancel, and that is the trap.** Going from the base
    party to the dealer is one flip: ``dealer_sign = DEALER_RECEIVED`` means
    the price came in above mid, so the base party overpaid, so the base party
    is the *customer* and the dealer holds ``-o``. Going from pay-polarity to
    received-polarity is a second flip. Two flips is the identity, so

    ::

        dealer_pay_signs      = -dealer_sign * o
        dealer_received_signs = -dealer_pay_signs = dealer_sign * o

    Writing the first negation and forgetting that the second one undoes it
    inverts every leg of every structure at once -- which is exactly what the
    first draft of this function did, caught by the frozen-predecessor test.
    """
    if dealer_sign not in (DEALER_RECEIVED, DEALER_PAID):
        raise ValueError(
            f"cannot sign a position with dealer_sign={dealer_sign!r}; "
            "0 means no call was made and must be handled by the caller"
        )
    o = base_orientation(kind, n_legs, rule)
    return tuple(dealer_sign * s for s in o)


def signed_weight(p: float) -> float:
    """The DV01 multiplier for a trade with probability ``p``.

    ``E[side] = p*(+1) + (1-p)*(-1) = 2p - 1``.

    **Not ``p``.** Weighting DV01 by ``p`` directly makes a coin flip
    (``p = 0.5``) contribute *half a long position* rather than nothing, which
    is how a marginal call ends up moving the ladder. ``2p - 1`` is zero at
    0.5, which is what "contributes proportionally rather than as a coin flip"
    has to mean for it to be true.
    """
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be a probability, got {p!r}")
    return 2.0 * float(p) - 1.0


class UnorientableUnit(ValueError):
    """No convention fixes this unit's base orientation under this rule.

    Raised rather than guessed. A ``PKG-N`` with four or more legs has no
    standard quote, so forcing an orientation would manufacture a confident
    direction from nothing; those units are excluded from the ladder and their
    DV01 share is reported instead.
    """
