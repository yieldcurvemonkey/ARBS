"""Data-driven leg weightings for multi-leg rate packages.

Import the module and use a preset::

    import RVUtils.fly                      # binds ``fly`` on the RVUtils namespace

    UnifiedQuery(
        curve="USD-SOFR-1D",
        tenor="1y5y/1y10y/1y30y",
        value=UnifiedValue.IRS_RATE,
        weighting=RVUtils.fly.pca_chgs_1m,
    )

``TimeseriesBuilder.get_timeseries`` sees the ``weighting=``, fetches the three
legs as outrights, fits the weights over the history it was asked for, and
returns ONE recombined column named after the preset - plus the whole ``T x n``
weight path in ``df.attrs["fly_weights"]``.

Preset grammar
--------------
``{method}_{basis}[_{window}][_{modifier}...]``

=============== ================================================================
method          ``pca`` divide by the PC1 loading; ``pca_proj`` minimal-change
                PC-neutral projection; ``beta`` multivariable regression on the
                curve and the belly; ``minvar`` pin the belly and minimise
                variance; ``none`` leave the package's own weights alone
basis           ``chgs`` (covariance of changes - the desk default) or ``lvls``
window          omitted for ONE IN-SAMPLE FIT over the requested history, or
                ``1m``/``3m``/``6m``/``1y``/``2y``/``90d``/``21b``/``60n``/
                ``expanding``
modifiers       ``level``/``pnl``/``current`` (how the weights become a series;
                default is ``level`` for a static fit and ``pnl`` for a rolling
                one - see below), ``lag1`` (weights knowable one row ahead),
                ``d5`` (weekly changes), ``pc2`` (neutralise PC1 and PC2),
                ``corr``, ``nc`` (uncentred, matching the Stack Exchange
                ``pinv`` snippet), ``w`` (also emit the weight columns),
                ``legs`` (keep the leg columns), ``l1``/``raw`` (alternate
                normalisations)
=============== ================================================================

**Why rolling weights need ``pnl``.** A hedged fly's weights do not sum to zero -
that is what the hedge is - so ``sum_i w_i r_i`` carries a rate-level term of
about ``(sum_i w_i) * level``. Static weights make that a constant offset.
Rolling weights make it wander: measured on USD SOFR ``1y5y/1y10y/1y30y``,
recombining a monthly-refit PCA fly on levels gave 187 bp/day of standard
deviation against the plain fly's 0.80, essentially all of it the weights
moving. So a rolling preset defaults to ``pnl`` - yesterday's weights over
today's move, anchored where ``level`` would have started - and a static one to
``level``. ``current`` puts the LAST fitted weights over the whole history,
which is the rich/cheap screen a desk looks at.

Any name matching the grammar resolves, whether or not it is in ``dir()``::

    RVUtils.fly.pca_chgs                # in-sample PC1 divide on changes
    RVUtils.fly.pca_lvls_1m             # rolling one-month, on levels
    RVUtils.fly.beta_chgs_1m            # rolling MVLSR
    RVUtils.fly.minvar_chgs_6m_lag1     # rolling min-variance, knowable a day early
    RVUtils.fly.pca_proj_chgs_1y_pc2    # PC1+PC2 neutral, minimal change
    RVUtils.fly.pca_chgs_1m_current     # today's weights over the whole history

or build one explicitly::

    RVUtils.fly.weights(method="beta", basis="chgs", window="1m", lag=1)

Method provenance: the Quant SE thread *"How to adjust butterfly 2s5s10s swaps
trade for directionality?"* - Attack68's PCA (both the divide-by-loading form
and the 2021 minimal-change KKT addendum) and minimum-VaR methods, dm63's
multivariable least squares - which follows Darbyshire, *Pricing and Trading
Interest Rate Derivatives*. ``tests/test_fly_weighting.py`` pins the first two
against the thread's own worked numbers and the second two against the
``numpy`` recipes in its code block.

**``pca`` is the unstable one.** Dividing by a PC1 loading blows up when that
loading is small, which is the objection Thrastylon raised on the thread and is
not hypothetical: on USD SOFR ``1y5y/1y10y/1y30y`` over 2026-03 to 2026-08,
``pca_chgs_1m`` put the back leg at **-6.01** against a belly of 2 on one day
and that day alone moved the series 34.6 bp, while ``pca_proj_chgs_1m`` stayed
inside ``(-1.14, 2, -1.02)`` all the way through. Weights past
``warn_abs_ratio`` are kept but warned about; past ``max_abs_ratio`` the window
is refused. If ``pca`` warns at you, reach for ``pca_proj``.

**In-sample warning.** A preset with no window fits one weight vector over the
entire history requested and applies it back across that same history. It shows
you what combination *was* market-neutral over the period; it is not something
you could have traded. Every rolling preset refits on data ending at ``t``; add
``lag1`` if the series has to be strictly knowable before ``t``.
"""
from __future__ import annotations

from typing import Any, List

from RVUtils.fly.estimators import (
    combine,
    default_anchor,
    default_factors,
    pc_loadings,
    second_moment,
    solve_weights,
    weights_from_moment,
)
from RVUtils.fly.schema import (
    BASES,
    METHODS,
    WeightingSchema,
    WindowSpec,
    coerce,
    parse_preset,
    parse_window,
    weights,
)

#: Windows the eagerly-built presets cover. Anything else still resolves
#: through ``__getattr__`` - this list only decides what ``dir()`` advertises.
COMMON_WINDOWS = ("", "1m", "3m", "6m", "1y", "2y", "expanding")

#: The package's own weights, untouched. Useful as a control column.
base = WeightingSchema(method="none")
none = base

_PRESETS: dict[str, WeightingSchema] = {"base": base, "none": none}

for _method in ("pca", "pca_proj", "beta", "minvar"):
    for _basis in ("chgs", "lvls"):
        for _window in COMMON_WINDOWS:
            _name = f"{_method}_{_basis}" + (f"_{_window}" if _window else "")
            _PRESETS[_name] = WeightingSchema(method=_method, basis=_basis, window=_window or None)

globals().update(_PRESETS)

__all__ = [
    "BASES",
    "COMMON_WINDOWS",
    "METHODS",
    "WeightingSchema",
    "WindowSpec",
    "coerce",
    "combine",
    "default_anchor",
    "default_factors",
    "parse_preset",
    "parse_window",
    "pc_loadings",
    "second_moment",
    "solve_weights",
    "weights",
    "weights_from_moment",
] + sorted(_PRESETS)


def __getattr__(name: str) -> Any:
    """Resolve any name matching the preset grammar, not just the common ones.

    ``dir()`` lists the eagerly-built grid; this is what makes the tail -
    ``pca_chgs_45d``, ``beta_lvls_2y_lag1``, ``minvar_chgs_500n`` - work without
    enumerating an infinite set.
    """
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    schema = parse_preset(name)
    globals()[name] = schema
    return schema


def __dir__() -> List[str]:
    """Keep tab-completion honest about the lazily-resolved names."""
    return sorted(set(globals()) | set(__all__))
