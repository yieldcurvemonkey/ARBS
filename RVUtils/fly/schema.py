"""Weighting schemas for multi-leg rate structures (curves, flies, condors).

A :class:`WeightingSchema` is a small, frozen, hashable description of *how* the
leg weights of a package are to be derived from its own history - PCA, a
multivariable regression, a minimum-variance solve - and over *what* history.
It carries no data. :func:`RVUtils.fly.estimators.solve_weights` turns a schema
plus a leg panel into a ``T x n`` frame of weights.

The vocabulary follows the three methods set out in the Quant SE thread
*"How to adjust butterfly 2s5s10s swaps trade for directionality?"* (Attack68 /
dm63), which in turn follows Darbyshire, *Pricing and Trading Interest Rate
Derivatives*:

``pca``
    Divide the base trade risks elementwise by the first principal component's
    loadings, then rescale. For a zero-sum base (``-1, +2, -1``) this is exactly
    PC1-neutral, because ``sum_i (x_i / p_i) * p_i = sum_i x_i = 0``.
``pca_proj``
    The 2021 addendum: instead of dividing, seek the *minimal risk change*
    ``delta`` to the base risks subject to ``(x + delta)' p = 0``. The KKT system
    solves analytically to the orthogonal projection ``w = x - p (x'p)/(p'p)``,
    which is better behaved than ``pca`` when a loading is near zero.
``beta``
    dm63's multivariable least squares: regress the package on a set of factor
    portfolios (for a fly, the wing curve and the belly outright) and trade the
    residual, ``w = x - F beta`` with ``beta = (F' Q F)^-1 F' Q x``.
``minvar``
    Pin the belly (or whichever leg is the anchor) and choose the remaining legs
    to minimise the package's variance: ``w_H = -Q_HH^-1 Q_Ha x_a``.

Naming grammar for the presets exported from :mod:`RVUtils.fly`::

    {method}_{basis}[_{window}][_{modifier}...]

    pca_chgs          PC1 divide, covariance of daily CHANGES, whole sample
    pca_lvls          PC1 divide, covariance of LEVELS, whole sample
    pca_chgs_1m       ... refit on a rolling one-month window
    pca_proj_chgs_3m  minimal-change PC1 projection, rolling three months
    beta_chgs_1m      multivariable regression weights, rolling one month
    minvar_lvls_1y    minimum-variance wings, rolling one year

**A schema with no window is fitted in sample.** The weights are derived from
the whole window the caller asked ``TimeseriesBuilder`` for and then applied
back over that same window, so the resulting series is not a tradable signal -
it is the best-fit decomposition of the period, which is what the Stack Exchange
answer's own H1-fit/H2-test example deliberately avoided. Use a rolling window
(and, if the series feeds a P&L, ``lag=1``) for anything that has to be
honest about what was knowable at the time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence, Tuple

import pandas as pd

__all__ = [
    "METHODS",
    "BASES",
    "WindowSpec",
    "WeightingSchema",
    "parse_window",
    "parse_preset",
    "coerce",
    "weights",
]

#: Every weighting method. ``none`` keeps the package's own default weights and
#: exists so a caller can ask for "the ordinary fly" through the same seam.
METHODS: Tuple[str, ...] = ("none", "pca", "pca_proj", "beta", "minvar")

#: What the covariance is estimated on.
BASES: Tuple[str, ...] = ("lvls", "chgs")

_BASIS_ALIASES = {
    "lvls": "lvls",
    "lvl": "lvls",
    "levels": "lvls",
    "level": "lvls",
    "chgs": "chgs",
    "chg": "chgs",
    "changes": "chgs",
    "change": "chgs",
    "diffs": "chgs",
    "diff": "chgs",
}

_METHOD_ALIASES = {
    "none": "none",
    "static": "none",
    "default": "none",
    "pca": "pca",
    "pca_div": "pca",
    "pcadiv": "pca",
    "pca_proj": "pca_proj",
    "pcaproj": "pca_proj",
    "pca_kkt": "pca_proj",
    "pcakkt": "pca_proj",
    "proj": "pca_proj",
    "beta": "beta",
    "mvlsr": "beta",
    "reg": "beta",
    "regression": "beta",
    "ols": "beta",
    "minvar": "minvar",
    "min_var": "minvar",
    "minvariance": "minvar",
    "mv": "minvar",
    "minvar_": "minvar",
}

# Longest-first so ``pca_proj`` is not eaten by ``pca``.
_METHOD_TOKENS = sorted(_METHOD_ALIASES, key=len, reverse=True)
_BASIS_TOKENS = sorted(_BASIS_ALIASES, key=len, reverse=True)

_PRESET_RE = re.compile(
    r"^(?P<method>" + "|".join(re.escape(m) for m in _METHOD_TOKENS) + r")"
    r"_(?P<basis>" + "|".join(re.escape(b) for b in _BASIS_TOKENS) + r")"
    r"(?P<rest>(?:_[A-Za-z0-9]+)*)$"
)

_WINDOW_RE = re.compile(r"^(?P<n>\d+)\s*(?P<unit>[a-z]*)$")

#: ``d`` is calendar days on purpose - an observation count is spelled ``60n``.
_TIME_UNITS = {
    "d": ("days", 1),
    "day": ("days", 1),
    "days": ("days", 1),
    "w": ("weeks", 1),
    "wk": ("weeks", 1),
    "week": ("weeks", 1),
    "m": ("months", 1),
    "mo": ("months", 1),
    "month": ("months", 1),
    "q": ("months", 3),
    "y": ("years", 1),
    "yr": ("years", 1),
    "year": ("years", 1),
}

_OBS_UNITS = {"", "n", "obs", "pt", "pts", "p"}
_BDAY_UNITS = {"b", "bd", "bday", "bdays"}


@dataclass(frozen=True)
class WindowSpec:
    """How much history each refit sees.

    ``kind`` is one of:

    ``"static"``
        One fit over every usable row, broadcast to the whole index. In sample.
    ``"expanding"``
        Everything up to and including ``t``.
    ``"obs"``
        The last ``size`` usable observations, inclusive of ``t``.
    ``"time"``
        Every row in the half-open interval ``(t - offset, t]``. Calendar time,
        so a gap in the data shortens the sample rather than reaching further
        back - which is the behaviour you want when a holiday or an outage
        leaves a hole.
    """

    kind: str = "static"
    size: int = 0
    offset_kwargs: Tuple[Tuple[str, int], ...] = ()
    text: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("static", "expanding", "obs", "time"):
            raise ValueError(f"WindowSpec.kind must be static/expanding/obs/time, got {self.kind!r}")
        if self.kind == "obs" and self.size <= 0:
            raise ValueError("an observation window needs a positive size")
        if self.kind == "time" and not self.offset_kwargs:
            raise ValueError("a time window needs an offset")

    @property
    def is_static(self) -> bool:
        return self.kind == "static"

    @property
    def offset(self):
        """The :class:`pandas.DateOffset` a ``time`` window steps back by."""
        if self.kind != "time":
            raise AttributeError("only a time window has an offset")
        kwargs = dict(self.offset_kwargs)
        if "bdays" in kwargs:
            return pd.offsets.BusinessDay(int(kwargs["bdays"]))
        return pd.DateOffset(**{k: int(v) for k, v in kwargs.items()})

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.text or self.kind


STATIC_WINDOW = WindowSpec(kind="static", text="")


def parse_window(spec: Any) -> WindowSpec:
    """Coerce ``spec`` into a :class:`WindowSpec`.

    Accepts ``None``/``""``/``"static"``/``"full"`` (one in-sample fit),
    ``"expanding"``, an ``int`` or ``"60"``/``"60n"``/``"60obs"`` (observation
    count), ``"21b"`` (business days), and ``"1m"``/``"3m"``/``"2w"``/``"1q"``/
    ``"1y"``/``"90d"`` (calendar spans).

    The ``d``-vs-``n`` distinction is deliberate and the one thing to get right:
    ``"60d"`` is sixty *calendar days* (about 41 business observations on a
    daily panel, and sixty seconds' worth of rows on a minute panel), while
    ``"60n"`` is sixty *rows* whatever they are.
    """
    if isinstance(spec, WindowSpec):
        return spec
    if spec is None:
        return STATIC_WINDOW
    if isinstance(spec, bool):
        raise TypeError("a bool is not a window")
    if isinstance(spec, (int,)) and not isinstance(spec, bool):
        if int(spec) <= 0:
            raise ValueError(f"window must be positive, got {spec!r}")
        return WindowSpec(kind="obs", size=int(spec), text=f"{int(spec)}n")

    text = str(spec).strip().lower().replace(" ", "")
    if text in ("", "static", "full", "none", "all", "insample"):
        return STATIC_WINDOW
    if text in ("expanding", "expand", "cumulative"):
        return WindowSpec(kind="expanding", text="expanding")

    match = _WINDOW_RE.match(text)
    if not match:
        raise ValueError(
            f"unrecognised window {spec!r}; use e.g. '1m', '3m', '1y', '90d', '21b', '60n', "
            "'expanding', or None for a single in-sample fit"
        )
    n = int(match.group("n"))
    unit = match.group("unit")
    if n <= 0:
        raise ValueError(f"window must be positive, got {spec!r}")

    if unit in _OBS_UNITS:
        return WindowSpec(kind="obs", size=n, text=f"{n}n")
    if unit in _BDAY_UNITS:
        return WindowSpec(kind="time", offset_kwargs=(("bdays", n),), text=f"{n}b")
    if unit in _TIME_UNITS:
        key, mult = _TIME_UNITS[unit]
        return WindowSpec(kind="time", offset_kwargs=((key, n * mult),), text=f"{n}{unit}")
    raise ValueError(
        f"unrecognised window unit {unit!r} in {spec!r}; known units are "
        f"{sorted(set(_TIME_UNITS) | _BDAY_UNITS | (_OBS_UNITS - {''}))}"
    )


@dataclass(frozen=True)
class WeightingSchema:
    """A data-driven leg weighting for one multi-leg package.

    Parameters
    ----------
    method
        One of :data:`METHODS`. See the module docstring for what each solves.
    basis
        ``"chgs"`` estimates the covariance on ``diff(diff_periods)`` of the leg
        panel; ``"lvls"`` on the levels themselves. Changes is the desk default
        and the one the Stack Exchange code uses; levels answers a different
        question (what combination has been stationary) and will look very
        different on a trending sample.
    window
        Anything :func:`parse_window` accepts. ``None`` means a single fit over
        the whole requested history - **in sample**; see the module docstring.
    diff_periods
        Differencing horizon for ``basis="chgs"``. ``1`` is daily on a daily
        panel; ``5`` gives weekly changes on one.
    n_pc
        How many principal components ``pca_proj`` neutralises. ``pca`` uses PC1
        only and ignores this.
    factors
        Explicit factor portfolios for ``beta``, as a tuple of ``n``-length
        weight vectors over the legs. ``None`` uses :func:`default_factors`,
        which for three legs is the wing curve ``(-1, 0, 1)`` and the belly
        ``(0, 1, 0)`` - exactly dm63's ``2s10s`` and ``5y`` regressors.
    anchor
        Index of the leg whose weight is preserved by the normalisation, and
        which ``minvar`` pins. ``None`` picks the belly on an odd leg count and
        the back leg on an even one.
    normalize
        ``"anchor"`` rescales so the anchor leg's weight equals the base
        package's (belly stays at 2 on an ARBS fly - the Stack Exchange
        convention); ``"l1"`` matches total gross risk; ``"none"`` leaves the
        raw solve alone.
    combine_mode
        How the weights become ONE series, which matters far more than it
        sounds once the weights move. A hedged fly's weights do not sum to zero
        - that is the point of them - so ``sum_i w_i r_i`` carries a rate-level
        term of roughly ``(sum_i w_i) * level``. With static weights that is a
        harmless constant offset. With rolling weights it wanders as the weights
        do, and on measured USD SOFR data a monthly-refit PCA fly came out at
        **187 bp/day of standard deviation against the plain fly's 0.80** - all
        of it the weights moving, none of it the market.

        ``"level"``
            ``sum_i w_i(t) r_i(t)``. Exact, and the right thing when the weights
            are static.
        ``"pnl"``
            ``anchor + cumsum(sum_i w_i(t-1) * dr_i(t))``. What the position
            actually earned: you held yesterday's weights over today's move. No
            weight-drift term at all. Anchored so its first value equals what
            ``"level"`` would have shown, which keeps it on the same scale as
            the plain fly.
        ``"current"``
            ``sum_i w_i(T) r_i(t)`` - the LAST fitted weights applied to the
            whole history. The rich/cheap screen a desk actually looks at, and
            openly forward-looking about the weights.
        ``"auto"`` (the default)
            ``"level"`` for a static fit, ``"pnl"`` for a rolling one.
    matrix
        ``"cov"`` or ``"corr"``. ``"cov"`` keeps loadings in rate space so the
        weights read directly; ``"corr"`` standardises first, which is a
        different model, not a cosmetic switch.
    center
        Demean before forming the second-moment matrix. ``True`` reproduces an
        OLS with intercept; ``False`` reproduces the uncentred ``np.linalg.pinv``
        of the Stack Exchange snippet.
    min_obs
        Rows required before a window produces weights at all. ``None`` uses
        ``max(2 * n_legs + 1, 10)``.
    lag
        Shift the fitted weights forward by this many rows before they are
        applied. ``0`` uses the window ending at ``t`` to weight ``t`` itself,
        which is what a desk quotes; ``1`` makes the series strictly knowable
        one step ahead, which is what a backtest needs.
    refit_every
        Recompute only every ``k``-th usable row and hold the weights flat in
        between. A cost knob for minute panels; ``1`` refits everywhere.
    eps
        Relative floor below which a PC1 loading counts as zero and ``pca``
        refuses to divide.
    max_abs_ratio
        Reject a solve whose largest weight exceeds this multiple of the anchor
        weight. Guards the failure mode Thrastylon raised on the thread: a PC1
        with a near-zero element sends ``x_i / p_i`` to infinity, and an
        enormous weight reaching a P&L table is worse than a gap.
    warn_abs_ratio
        The softer rail below it. Weights this far from the anchor are kept but
        warned about, because on a short window they are usually the estimate
        breaking down rather than a view. Measured on USD SOFR ``1y5y/1y10y/1y30y``
        over 2026-03 to 2026-08, ``pca_chgs_1m`` put the back leg at **-6.01**
        against a belly of 2 on one day and that single day cost 34.6 bp;
        ``pca_proj_chgs_1m`` over the same window stayed inside
        ``(-1.14, 2, -1.02)`` throughout. If ``pca`` is warning at you, the
        projection variant is the answer.
    keep_legs
        Leave the fetched leg columns in the output frame instead of dropping
        them once the package has been recombined.
    emit_weights
        Add one ``... W1``/``W2``/... column per leg carrying the fitted weight
        path. The weights are always available in ``df.attrs["fly_weights"]``
        whether or not this is set.
    label
        Overrides the auto-derived tag used to name the output column.
    """

    method: str = "none"
    basis: str = "chgs"
    window: WindowSpec = STATIC_WINDOW
    diff_periods: int = 1
    n_pc: int = 1
    factors: Optional[Tuple[Tuple[float, ...], ...]] = None
    anchor: Optional[int] = None
    normalize: str = "anchor"
    combine_mode: str = "auto"
    matrix: str = "cov"
    center: bool = True
    min_obs: Optional[int] = None
    lag: int = 0
    refit_every: int = 1
    eps: float = 1e-8
    max_abs_ratio: float = 20.0
    warn_abs_ratio: float = 5.0
    keep_legs: bool = False
    emit_weights: bool = False
    label: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        method = _METHOD_ALIASES.get(str(self.method).strip().lower())
        if method is None:
            raise ValueError(f"unknown weighting method {self.method!r}; expected one of {METHODS}")
        basis = _BASIS_ALIASES.get(str(self.basis).strip().lower())
        if basis is None:
            raise ValueError(f"unknown weighting basis {self.basis!r}; expected one of {BASES}")
        if self.normalize not in ("anchor", "l1", "none"):
            raise ValueError(f"normalize must be anchor/l1/none, got {self.normalize!r}")
        if self.combine_mode not in ("auto", "level", "pnl", "current"):
            raise ValueError(f"combine_mode must be auto/level/pnl/current, got {self.combine_mode!r}")
        if self.matrix not in ("cov", "corr"):
            raise ValueError(f"matrix must be cov/corr, got {self.matrix!r}")
        if int(self.diff_periods) < 1:
            raise ValueError("diff_periods must be >= 1")
        if int(self.n_pc) < 1:
            raise ValueError("n_pc must be >= 1")
        if int(self.lag) < 0:
            raise ValueError("lag must be >= 0")
        if int(self.refit_every) < 1:
            raise ValueError("refit_every must be >= 1")

        object.__setattr__(self, "method", method)
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "window", parse_window(self.window))
        object.__setattr__(self, "diff_periods", int(self.diff_periods))
        object.__setattr__(self, "n_pc", int(self.n_pc))
        object.__setattr__(self, "lag", int(self.lag))
        object.__setattr__(self, "refit_every", int(self.refit_every))
        if self.factors is not None:
            object.__setattr__(
                self,
                "factors",
                tuple(tuple(float(v) for v in row) for row in self.factors),
            )
        if self.min_obs is not None:
            object.__setattr__(self, "min_obs", int(self.min_obs))
        if self.anchor is not None:
            object.__setattr__(self, "anchor", int(self.anchor))
        object.__setattr__(self, "label", self.label or self._derive_label())

    # ------------------------------------------------------------------ label

    def _derive_label(self) -> str:
        parts = [self.method if self.method != "none" else "base"]
        if self.method != "none":
            parts.append(self.basis)
            if self.window.text:
                parts.append(self.window.text)
            if self.basis == "chgs" and self.diff_periods != 1:
                parts.append(f"d{self.diff_periods}")
            if self.method == "pca_proj" and self.n_pc != 1:
                parts.append(f"pc{self.n_pc}")
            if self.matrix != "cov":
                parts.append(self.matrix)
            if not self.center:
                parts.append("nc")
            if self.normalize != "anchor":
                parts.append(f"n{self.normalize}")
            if self.combine_mode != "auto":
                parts.append(self.combine_mode)
            if self.lag:
                parts.append(f"lag{self.lag}")
            if self.anchor is not None:
                parts.append(f"a{self.anchor}")
        return "_".join(parts)

    # ------------------------------------------------------------- predicates

    @property
    def is_identity(self) -> bool:
        """``True`` when the schema leaves the package's own weights alone."""
        return self.method == "none"

    @property
    def is_in_sample(self) -> bool:
        """``True`` when every weight was fitted using data from after its own date."""
        if self.method == "none":
            return False
        return self.window.is_static or self.resolved_combine_mode == "current"

    @property
    def resolved_combine_mode(self) -> str:
        """``combine_mode`` with ``"auto"`` decided. See the field's docs."""
        if self.combine_mode != "auto":
            return self.combine_mode
        if self.is_identity or self.window.is_static:
            return "level"
        return "pnl"

    # -------------------------------------------------------------- modifiers

    def with_weights(self, emit: bool = True) -> "WeightingSchema":
        """Same schema, but the per-leg weight paths come back as columns too."""
        return replace(self, label=None, emit_weights=bool(emit))

    def with_legs(self, keep: bool = True) -> "WeightingSchema":
        """Same schema, but the fetched leg columns survive into the frame."""
        return replace(self, label=None, keep_legs=bool(keep))

    def lagged(self, lag: int = 1) -> "WeightingSchema":
        """Same schema with the fitted weights shifted forward ``lag`` rows."""
        return replace(self, label=None, lag=int(lag))

    def but(self, **changes: Any) -> "WeightingSchema":
        """Copy with fields overridden; the label re-derives unless given."""
        changes.setdefault("label", None)
        return replace(self, **changes)

    def compute(self, legs: pd.DataFrame, base: Sequence[float]) -> pd.DataFrame:
        """The ``T x n`` weight frame for ``legs`` under this schema."""
        from RVUtils.fly.estimators import solve_weights

        return solve_weights(legs, base, self)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.label or self.method


def weights(
    method: str = "pca",
    basis: str = "chgs",
    window: Any = None,
    **kwargs: Any,
) -> WeightingSchema:
    """Build a :class:`WeightingSchema`; the presets are sugar over this."""
    return WeightingSchema(method=method, basis=basis, window=window, **kwargs)


def parse_preset(name: str) -> WeightingSchema:
    """Turn a preset name such as ``"pca_chgs_1m"`` into a schema.

    The grammar is ``{method}_{basis}[_{window}][_{modifier}...]``. Modifiers
    understood after the window: ``lag<k>``, ``d<k>`` (differencing horizon),
    ``pc<k>`` (components neutralised), ``corr``, ``nc`` (uncentred), ``w``
    (emit weight columns), ``legs`` (keep leg columns).
    """
    text = str(name).strip().lower()
    match = _PRESET_RE.match(text)
    if not match:
        raise AttributeError(
            f"{name!r} is not a RVUtils.fly preset; expected {{method}}_{{basis}}[_{{window}}], "
            f"e.g. 'pca_chgs', 'pca_lvls_1m', 'beta_chgs_1m', 'minvar_chgs_6m'. "
            f"Methods: {METHODS}; bases: {BASES}."
        )

    method = _METHOD_ALIASES[match.group("method")]
    basis = _BASIS_ALIASES[match.group("basis")]
    rest = [tok for tok in match.group("rest").split("_") if tok]

    window: Any = None
    kwargs: dict[str, Any] = {}
    for token in rest:
        if token == "corr":
            kwargs["matrix"] = "corr"
        elif token == "nc":
            kwargs["center"] = False
        elif token == "w":
            kwargs["emit_weights"] = True
        elif token == "legs":
            kwargs["keep_legs"] = True
        elif token in ("level", "pnl", "current"):
            kwargs["combine_mode"] = token
        elif token in ("l1", "raw"):
            kwargs["normalize"] = "l1" if token == "l1" else "none"
        elif token.startswith("lag") and token[3:].isdigit():
            kwargs["lag"] = int(token[3:])
        elif token.startswith("pc") and token[2:].isdigit():
            kwargs["n_pc"] = int(token[2:])
        elif re.fullmatch(r"d\d+", token):
            kwargs["diff_periods"] = int(token[1:])
        elif re.fullmatch(r"a\d+", token):
            kwargs["anchor"] = int(token[1:])
        elif window is None:
            window = parse_window(token)
        else:
            raise AttributeError(f"{name!r}: unrecognised modifier {token!r}")

    return WeightingSchema(method=method, basis=basis, window=window, **kwargs)


def coerce(spec: Any) -> Optional[WeightingSchema]:
    """Accept whatever a caller put in ``UnifiedQuery(weighting=...)``.

    ``None`` stays ``None``. A :class:`WeightingSchema` passes through. A string
    is a preset name. A mapping is splatted into the constructor. A sequence of
    numbers is a fixed custom weight vector, which is expressed as an identity
    schema whose base weights the caller supplies separately - see
    :func:`RVUtils.fly.estimators.solve_weights`.
    """
    if spec is None:
        return None
    if isinstance(spec, WeightingSchema):
        return spec
    if isinstance(spec, str):
        return parse_preset(spec)
    if isinstance(spec, Mapping):
        return WeightingSchema(**dict(spec))
    raise TypeError(
        f"cannot read {spec!r} as a weighting schema; pass a RVUtils.fly preset, "
        "a preset name, or a dict of WeightingSchema fields"
    )
