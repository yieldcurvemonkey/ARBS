"""Is the pack convexity adjustment being calculated correctly? Four tests.

The adjustment is a *small difference of two large numbers* -- a few bp of spread
between a ~3-5% pack rate and a ~3-5% swap rate. Every convention error and every
stale quote lands in it at full size. Citi's own screen is quoted to 2dp on
values as small as 0.08bp. So "does it tie out to Citi on one date" is necessary
and nowhere near sufficient; this module provides the checks that do not need
Citi at all.

**1. The zero-convexity control (the decisive one).**
Recompute the identical arithmetic, but take the four quarterly rates from the
*swap curve's own IMM forwards* instead of from futures. Those contain no
convexity adjustment by construction -- they come from the same discount curve
the swap leg is priced off -- so

    CA_synthetic = mean(fwd_OIS[IMM_i, IMM_i+1]) - par_rate(matched 1y swap)

must be zero. Whatever it returns is *our own convention error*, measured
directly, with no external reference: arithmetic mean of quarterly forwards
versus the annuity-weighted average a par swap rate actually is, plus any
day-count, frequency or date-roll mismatch.

    CA_clean = CA_observed - CA_synthetic

Measured on this repo's data (36 pack-days across 2022-06, 2023-03, 2023-06):

    CA_synthetic   mean -0.137bp   median -0.119bp   sd 0.523bp
    CA_observed    mean +4.701bp   range -5.15 .. +18.85
    residual as a share of the signal:  median 2.2%

That is the evidence the conventions are right. The same run also shows the
annual-versus-quarterly swap gap at 4.25-9.47bp, *scaling with the rate level*
(9.47bp when the front is ~5%, ~4.5bp at ~3%) -- the ``r^2`` compounding
signature, which is why the matched swap must be quarterly and why the earlier
-4.31bp offset against Citi was never convexity.

**2. No-arbitrage sign.** The futures rate must exceed the matched forward, so
``CA >= 0``. A negative adjustment is not a small error, it is impossible, and in
practice means a stale settle on a deferred contract. Measured here on real
dates: e.g. 2023-03-15 H4-Z4 at -4.47bp with a synthetic control of 0.00bp -- so
not convention, data. This is the single most useful automatic filter.

**3. Term-structure shape.** Ho-Lee makes the adjustment quadratic in expiry, so
a log-log regression of CA on T1 should have slope ~2 and ``corr(CA, T1^2)``
should be near 1. A shape break flags either a data problem or a genuine
dislocation -- worth separating before trading it.

**4. Implied-vol plausibility.** Inverting a near-dated pack's tiny CA gives an
enormous vol (front packs here invert to 700bp+ against a realistic SOFR vol of
~100-250bp) because ``sigma = sqrt(2*CA/mean(T1^2))`` divides by a very small
number. This is why Citi's own tables start at Reds, not Whites. Near packs are
numerically unfit for vol inversion even when their CA is fine.

**5. Curve resolution -- the blind spot of test 1.** Added after the full-sample
scan. ``CA_synthetic`` compares an arithmetic mean of four quarterly forwards
against the par rate of the swap spanning them; if the discount curve carries no
node inside that window, log-linear interpolation makes all four forwards
identical and the two numbers agree *by construction*. The control then returns
0.00bp on a swap leg that is not a market observation at all. Measured: this
repo's ``USD-SOFR-1D`` runs on 26 nodes with a single 735-day segment covering
the whole front end until **2019-07-08**, when it jumps to 45. So the first six
months of the sample must be excluded on grounds the first four tests cannot
see. :func:`window_resolution` and :func:`control_power_bp` make it visible.

**6. The annual/quarterly gap is a prediction.** ``3/8 * q^2`` with no free
parameter (:data:`COMPOUNDING_GAP_SLOPE`); :func:`regress_gap_on_rate_squared`
tests it rather than asserting it.

**7. Inversion conditioning.** :func:`vol_sensitivity_bp_per_bp` returns
``dsigma/dCA = sigma/(2*CA)``, which turns a measured CA noise into a vol noise
and so sets the minimum usable pack rank from the data.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate
from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp
from RVUtils.ConvexityRV.packs import imm_date, matched_swap_dates, pack_t1s

__all__ = [
    "next_quarterly",
    "imm_forward_map",
    "synthetic_pack_rate",
    "decompose_ca",
    "flag_quality",
    "shape_diagnostics",
    "CADecomposition",
    "PLAUSIBLE_VOL_BP",
    "MIN_T1_FOR_VOL_YEARS",
    # --- extensions used by scripts/strat2_ca_quality_scan.py -----------
    "curve_nodes",
    "window_resolution",
    "annuity_weight_residual_bp",
    "control_power_bp",
    "compounding_gap_bp",
    "COMPOUNDING_GAP_SLOPE",
    "vol_sensitivity_bp_per_bp",
    "regress_gap_on_rate_squared",
]

#: A SOFR normal vol outside this band is not a market observation, it is an
#: inversion artefact or a bad print.
PLAUSIBLE_VOL_BP: Tuple[float, float] = (40.0, 350.0)

#: Below this first-expiry, sigma = sqrt(2*CA/mean(T1^2)) is too ill-conditioned
#: to quote. Citi's published screens start at Reds (~1y+) for this reason.
MIN_T1_FOR_VOL_YEARS = 0.75


def next_quarterly(year: int, month: int) -> Tuple[int, int]:
    """The quarterly IMM month after ``(year, month)``."""
    return (year, month + 3) if month < 10 else (year + 1, month - 9)


def imm_forward_map(
    pricer: Any, contracts: Sequence[Tuple[int, int]]
) -> Dict[Tuple[int, int], float]:
    """``(year, month) -> IMM x IMM quarterly forward rate`` (percent) off *pricer*.

    Computed once per date over the whole strip rather than once per pack:
    ten rolling pack windows share thirteen quarterly forwards, so the per-pack
    loop does 40 curve calls where 13 suffice **and** lets two overlapping packs
    disagree about the same quarter if anything is ever memoised per call.
    """
    out: Dict[Tuple[int, int], float] = {}
    for y, m in contracts:
        if (y, m) in out:
            continue
        a = imm_date(y, m)
        b = imm_date(*next_quarterly(y, m))
        out[(y, m)] = matched_forward_swap_rate(pricer, a, b)
    return out


def synthetic_pack_rate(
    pricer: Any,
    contracts: Sequence[Tuple[int, int]],
    *,
    forwards: Optional[Mapping[Tuple[int, int], float]] = None,
) -> float:
    """Arithmetic mean of the CURVE's own forward rates for the pack's quarters.

    The zero-convexity counterfactual: what the pack rate would print at if
    futures carried no convexity adjustment at all.

    Pass ``forwards`` (from :func:`imm_forward_map`) to reuse a strip that has
    already been priced; omit it and the four forwards are built on the spot.
    """
    if forwards is not None:
        return float(np.mean([forwards[k] for k in contracts]))
    rates: List[float] = []
    for y, m in contracts:
        a = imm_date(y, m)
        b = imm_date(*next_quarterly(y, m))
        rates.append(matched_forward_swap_rate(pricer, a, b))
    return float(np.mean(rates))


@dataclass(frozen=True)
class CADecomposition:
    """One pack on one date, split into signal and our own convention error."""

    pack: str
    as_of: datetime.date
    pack_rate_futures: float          # percent
    pack_rate_synthetic: float        # percent
    swap_rate: float                  # percent, quarterly/quarterly
    ca_observed_bp: float
    ca_synthetic_bp: float            # pure convention residual; target 0
    ca_clean_bp: float                # observed - synthetic
    t1_first: float
    implied_vol_bp: float
    implied_vol_clean_bp: float

    @property
    def residual_share(self) -> float:
        """Convention error as a fraction of the measured adjustment."""
        d = abs(self.ca_observed_bp)
        return float("nan") if d == 0 else abs(self.ca_synthetic_bp) / d


# ===========================================================================
# 5. Curve resolution -- the blind spot of test 1
# ===========================================================================
def curve_nodes(pricer: Any) -> List[datetime.date]:
    """The discount curve's node dates, ascending.

    Not cosmetic. The matched swap is priced *off this node grid*, and a par
    rate for a window that contains no node is an interpolation, not a market
    observation.
    """
    handle = pricer._rl_curve_handle
    curve = getattr(handle, "curve", handle)
    nodes = curve.nodes
    keys = nodes.keys if hasattr(nodes, "keys") and not callable(nodes.keys) else list(nodes)
    out: List[datetime.date] = []
    for k in keys:
        out.append(k.date() if isinstance(k, datetime.datetime) else k)
    return sorted(out)


def window_resolution(
    nodes: Sequence[datetime.date],
    start: datetime.date,
    end: datetime.date,
) -> Dict[str, float]:
    """How much curve there is inside ``[start, end]``.

    **This is the test the zero-convexity control cannot do.** The control
    compares the arithmetic mean of four quarterly forwards against the par rate
    of the swap that spans them. If the curve is *flat* across the window --
    because it has no node there and log-linear interpolation carries a single
    constant forward -- then those two numbers are equal by construction and
    ``CA_synthetic`` is exactly 0.00 no matter how wrong the swap leg is. A
    passing control on a flat segment is not evidence; it is an absence of
    evidence, and it looks identical.

    Measured on this repo's ``USD-SOFR-1D``: before **2019-07-08** the curve
    carries 26 nodes with the second at *start + ~735 days*, i.e. the entire
    first two years is one log-linear segment. Every IMM x IMM forward inside it
    prints the same rate to 4dp (2019-03-15: 2.2866% for all eight of the first
    two years) while the SR3 strip declines 2.4300 -> 2.1450 across the same
    span. On 2019-07-08 the grid jumps to 45 nodes (monthly to 1y, quarterly to
    2y, annual thereafter) and the front end becomes representable.

    Returns ``n_nodes_inside`` (strictly inside the window), ``segment_days``
    (the length of the node interval containing the window's midpoint) and
    ``spans_window`` (1.0 when a single node interval swallows the whole
    window, i.e. the control has no power).
    """
    ns = sorted(nodes)
    inside = [d for d in ns if start < d < end]
    mid = start + (end - start) / 2
    lo = max([d for d in ns if d <= mid], default=ns[0] if ns else start)
    hi = min([d for d in ns if d > mid], default=ns[-1] if ns else end)
    return {
        "n_nodes": float(len(ns)),
        "n_nodes_inside": float(len(inside)),
        "segment_days": float((hi - lo).days),
        "spans_window": float(lo <= start and hi >= end),
    }


def annuity_weight_residual_bp(
    forwards: Sequence[float], rate_percent: float, accrual: float = 0.25
) -> float:
    """The residual the zero-convexity control *should* return, in bp.

    ``CA_synthetic`` is not testing whether the arithmetic is right so much as
    the size of one known, second-order term: the pack rate is an **equally
    weighted** mean of four quarterly forwards, while the matched swap's par
    rate is the **annuity-weighted** one,

        par = sum_i w_i f_i,     w_i ∝ DF_i * tau_i

    Later quarters discount harder, so they carry slightly less weight than
    1/4. On an upward-sloping strip that makes the arithmetic mean exceed the
    par rate and the control residual positive; on an inverted strip, negative.
    The size is first order in ``r * tau`` and in the strip's own slope, which
    is why the residual is ~0 when the curve is flat and grows with dispersion.

    Returns ``sum_i (1/4 - w_i) * f_i * 100`` in bp, with ``DF_i`` taken as
    ``exp(-r * tau * i)`` off the swap rate itself. Approximate by construction
    -- it is a *prediction to compare the measurement against*, not a
    correction to apply.
    """
    f = np.asarray(list(forwards), dtype=float)
    n = f.size
    if n == 0 or not np.all(np.isfinite(f)) or not np.isfinite(rate_percent):
        return float("nan")
    r = float(rate_percent) / 100.0
    t = accrual * np.arange(1, n + 1)
    w = np.exp(-r * t)
    w = w / w.sum()
    return float(np.dot(1.0 / n - w, f) * 100.0)


def control_power_bp(forwards: Sequence[float]) -> float:
    """Curvature the zero-convexity control actually gets to see, in bp.

    The peak-to-trough spread of a pack's four quarterly forwards. The control
    residual ``CA_synthetic`` is an *arithmetic-mean minus annuity-weighted-mean*
    discrepancy, and that discrepancy is identically zero when the four forwards
    are identical. So a ``CA_synthetic`` of 0.00bp on a pack whose forwards
    spread 0.0bp says nothing at all, while the same 0.00bp on a pack whose
    forwards spread 150bp is a strong statement. Report the two together or the
    control is unfalsifiable.
    """
    f = np.asarray(list(forwards), dtype=float)
    if f.size == 0 or not np.all(np.isfinite(f)):
        return float("nan")
    return float((f.max() - f.min()) * 100.0)


# ===========================================================================
# 6. The annual-vs-quarterly compounding gap -- a *prediction*, not a fudge
# ===========================================================================
#: ``gap_bp = COMPOUNDING_GAP_SLOPE * rate_percent**2``.
#:
#: A 1y swap paying a fixed rate ``a`` annually is equivalent to one paying
#: ``q`` quarterly when ``(1 + q/4)^4 = 1 + a``, so
#: ``a = q + (6/16) q^2 + O(q^3)`` and the gap is ``3/8 * q^2`` in decimal.
#: With ``q`` in **percent** and the gap in **bp** the 1e4/1e4 scalings cancel
#: to a bare ``0.375``: at 5% that is 9.38bp, at 3.4% it is 4.34bp -- which is
#: the 4.25-9.47bp range measured on this repo's data, predicted with no free
#: parameter.
COMPOUNDING_GAP_SLOPE = 0.375


def compounding_gap_bp(rate_percent: Any) -> Any:
    """Predicted annual-minus-quarterly par-rate gap, bp, from the rate alone.

    Vectorised: a float in gives a float out, an array or Series gives the same
    shape back, because the whole point is to overlay it on a scatter of 11,900
    measured gaps.
    """
    if np.isscalar(rate_percent):
        return COMPOUNDING_GAP_SLOPE * float(rate_percent) ** 2
    return COMPOUNDING_GAP_SLOPE * np.asarray(rate_percent, dtype=float) ** 2


def regress_gap_on_rate_squared(
    gap_bp: Sequence[float], rate_percent: Sequence[float]
) -> Dict[str, float]:
    """OLS ``gap_bp ~ b * rate^2`` (no intercept) plus the free-intercept fit.

    The no-intercept slope is the number to compare with
    :data:`COMPOUNDING_GAP_SLOPE` = 0.375. The intercept version is the honesty
    check: a materially non-zero intercept would mean something *other* than
    compounding is in the gap.
    """
    g = np.asarray(list(gap_bp), dtype=float)
    r = np.asarray(list(rate_percent), dtype=float)
    ok = np.isfinite(g) & np.isfinite(r)
    g, r = g[ok], r[ok]
    if g.size < 3:
        out = {k: float("nan") for k in ("slope_no_intercept", "slope", "intercept", "r2")}
        out["n"] = float(g.size)
        return out
    x = r ** 2
    slope0 = float(np.dot(x, g) / np.dot(x, x))
    a = np.stack([x, np.ones_like(x)], axis=1)
    (slope, intercept), *_ = np.linalg.lstsq(a, g, rcond=None)
    pred = a @ np.array([slope, intercept])
    ss_res = float(np.sum((g - pred) ** 2))
    ss_tot = float(np.sum((g - g.mean()) ** 2))
    return {
        "slope_no_intercept": slope0,
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
        "n": float(g.size),
    }


# ===========================================================================
# 7. Conditioning of the vol inversion
# ===========================================================================
def vol_sensitivity_bp_per_bp(ca_bp: float, t1s: Sequence[float]) -> float:
    """``d(sigma)/d(CA)`` in bp of vol per bp of adjustment.

    ``sigma = sqrt(2*CA/M)`` so ``dsigma/dCA = sigma / (2*CA)``: the inversion's
    gain is inversely proportional to the size of the thing being inverted.
    That is the whole story of why near packs are unusable -- not the ``T1``
    directly, but that ``CA`` itself is tiny there.

    Combine with the *measured* CA noise (see the settle-timing test) to get a
    minimum tradeable rank from this data instead of from Citi's convention.
    """
    ca = float(ca_bp)
    if not np.isfinite(ca) or ca <= 0:
        return float("nan")
    sigma = implied_vol_from_ca_bp(ca, t1s)
    if not np.isfinite(sigma):
        return float("nan")
    return float(sigma / (2.0 * ca))


def decompose_ca(
    pricer: Any,
    as_of: datetime.date,
    contracts: Sequence[Tuple[int, int]],
    futures_rates: Mapping[Tuple[int, int], float],
    *,
    label: Optional[str] = None,
) -> Optional[CADecomposition]:
    """Full decomposition for one pack, or None if an input is missing."""
    if len(contracts) != 4:
        raise ValueError(f"a pack is 4 contracts, got {len(contracts)}")
    if any(k not in futures_rates for k in contracts):
        return None

    start, end = matched_swap_dates(contracts)
    swap = matched_forward_swap_rate(pricer, start, end)
    pack_fut = float(np.mean([futures_rates[k] for k in contracts]))
    pack_syn = synthetic_pack_rate(pricer, contracts)

    ca_obs = (pack_fut - swap) * 100.0
    ca_syn = (pack_syn - swap) * 100.0
    ca_cln = ca_obs - ca_syn
    t1s = pack_t1s(as_of, contracts)

    from RVUtils.ConvexityRV.packs import contract_code

    return CADecomposition(
        pack=label or f"{contract_code(*contracts[0])}-{contract_code(*contracts[3])}",
        as_of=as_of,
        pack_rate_futures=pack_fut,
        pack_rate_synthetic=pack_syn,
        swap_rate=swap,
        ca_observed_bp=ca_obs,
        ca_synthetic_bp=ca_syn,
        ca_clean_bp=ca_cln,
        t1_first=float(t1s[0]),
        implied_vol_bp=implied_vol_from_ca_bp(ca_obs, t1s),
        implied_vol_clean_bp=implied_vol_from_ca_bp(ca_cln, t1s),
    )


def flag_quality(
    df: pd.DataFrame,
    *,
    ca_col: str = "ca_bp",
    syn_col: Optional[str] = "ca_synthetic_bp",
    vol_col: Optional[str] = "implied_vol_bp",
    t1_col: Optional[str] = "t1_first",
    max_convention_bp: float = 1.0,
) -> pd.DataFrame:
    """Add boolean quality flags. ``ok`` is the conjunction of all of them.

    ``negative_ca`` is the important one: it is a no-arbitrage violation, not a
    tolerance, and on this data it fires on genuinely stale deferred settles
    rather than on anything the model could explain.
    """
    out = df.copy()
    out["flag_negative_ca"] = out[ca_col] < 0
    if syn_col and syn_col in out:
        out["flag_convention"] = out[syn_col].abs() > max_convention_bp
    else:
        out["flag_convention"] = False
    if vol_col and vol_col in out:
        lo, hi = PLAUSIBLE_VOL_BP
        v = out[vol_col]
        out["flag_implausible_vol"] = v.notna() & ((v < lo) | (v > hi))
    else:
        out["flag_implausible_vol"] = False
    if t1_col and t1_col in out:
        out["flag_vol_ill_conditioned"] = out[t1_col] < MIN_T1_FOR_VOL_YEARS
    else:
        out["flag_vol_ill_conditioned"] = False

    flags = ["flag_negative_ca", "flag_convention", "flag_implausible_vol"]
    out["ok"] = ~out[flags].any(axis=1)
    return out


def shape_diagnostics(df: pd.DataFrame, *, ca_col: str = "ca_bp",
                      t1_col: str = "t1_first") -> Dict[str, float]:
    """Ho-Lee shape test: log-log slope of CA on T1 (target 2) and corr(CA, T1^2).

    Returns NaNs rather than raising when there are too few usable points -- a
    day whose deferred contracts are all stale legitimately has no shape.
    """
    g = df[(df[ca_col] > 0) & df[t1_col].notna() & (df[t1_col] > 0)]
    g = g[np.isfinite(g[ca_col]) & np.isfinite(g[t1_col])]
    if len(g) < 4:
        return {"loglog_slope": float("nan"), "corr_t1_squared": float("nan"), "n": len(g)}
    x, y = np.log(g[t1_col].to_numpy()), np.log(g[ca_col].to_numpy())
    with np.errstate(invalid="ignore", divide="ignore"):
        try:
            slope = float(np.polyfit(x, y, 1)[0])
        except Exception:
            slope = float("nan")
        try:
            corr = float(np.corrcoef(g[t1_col].to_numpy() ** 2, g[ca_col].to_numpy())[0, 1])
        except Exception:
            corr = float("nan")
    return {"loglog_slope": slope, "corr_t1_squared": corr, "n": int(len(g))}
