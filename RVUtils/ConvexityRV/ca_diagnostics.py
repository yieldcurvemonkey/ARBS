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
    "synthetic_pack_rate",
    "decompose_ca",
    "flag_quality",
    "shape_diagnostics",
    "CADecomposition",
    "PLAUSIBLE_VOL_BP",
    "MIN_T1_FOR_VOL_YEARS",
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


def synthetic_pack_rate(pricer: Any, contracts: Sequence[Tuple[int, int]]) -> float:
    """Arithmetic mean of the CURVE's own forward rates for the pack's quarters.

    The zero-convexity counterfactual: what the pack rate would print at if
    futures carried no convexity adjustment at all.
    """
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
    try:
        slope = float(np.polyfit(x, y, 1)[0])
    except Exception:
        slope = float("nan")
    try:
        corr = float(np.corrcoef(g[t1_col].to_numpy() ** 2, g[ca_col].to_numpy())[0, 1])
    except Exception:
        corr = float("nan")
    return {"loglog_slope": slope, "corr_t1_squared": corr, "n": int(len(g))}
