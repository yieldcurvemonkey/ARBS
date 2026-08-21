r"""W3 — the STIR convexity adjustment against the long end, as a vol RV trade.

Both legs of this trade are *curve-implied volatility*, measured on the same
ruler and sourced from two markets that never have to agree:

* **STIR.** A SOFR pack's convexity adjustment is a variance quantity — Ho-Lee
  gives ``CA = ½·σ²·mean(T1²)`` — so inverting the observed adjustment yields a
  normal vol in bp/day with **no fitted parameter anywhere in it**.
  :func:`RVUtils.ConvexityRV.holee.implied_vol_from_ca_bp` does the inversion.
* **The long end.** A DV01-neutral ultra-long forward flattener has a convex
  payoff, and the daily move that makes its convexity gain offset its negative
  carry is the *breakeven vol* — Citi's own column, in the same bp/day unit.

Neither is a traded option price. That is the point: they are two independent
readings of what the market is charging for convexity, one at the very front and
one at the very back, and the spread between them is the trade.

Why this is not `ca_vol_link`
-----------------------------
:mod:`RVUtils.ConvexityRV.ca_vol_link` asks whether the CA tracks *swaption*
vol at the matched expiry — a question about whether our CA construction is
sound. This module takes that as given and asks a different one: whether
front-end and long-end **curve-implied** vol move together well enough that
their spread mean-reverts. The first is a validation question, the second is a
trade.

What is measured before anything is traded
------------------------------------------
The honest failure mode here is that the two series simply have nothing to do
with each other, in which case their "spread" is two independent random walks
and any mean-reversion signal on it is fitting noise.
:func:`link_diagnostics` reports the correlation of levels **and of changes**,
and the changes number is the one that matters — two trending series correlate
in levels for reasons that have nothing to do with a tradable relationship.
This module reports it whether or not it is flattering.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "W3Config",
    "build_vol_spread_panel",
    "entry_state",
    "link_diagnostics",
    "stir_implied_vol_series",
]


@dataclass(frozen=True)
class W3Config:
    """Knobs, each with the reason for its default."""

    start: dt.date = dt.date(2021, 1, 1)
    end: dt.date = dt.date(2026, 8, 20)

    #: Pack colour supplying the STIR leg. Blues is Citi's own choice and the
    #: only colour whose positioning regression reproduced (t = +2.59).
    colour: str = "Blues"

    #: Long-end pair supplying the other leg. 15Yx5Y/20Yx10Y is the pair Citi
    #: traded and published a full round trip for.
    pair: str = "15Yx5Y/20Yx10Y"

    #: Trailing window for the z-score of the spread. 252 = one year.
    z_window: int = 252

    #: Entry when |z| exceeds this, exit when it reverts inside `exit_z`.
    entry_z: float = 1.5
    exit_z: float = 0.5

    #: Minimum trailing observations before a z-score is emitted at all.
    min_periods: int = 120

    #: Ho-Lee convention. "citi" is T1^2, pinned against eight published screens.
    holee_convention: str = "citi"

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["start"], d["end"] = str(self.start), str(self.end)
        return d


# ---------------------------------------------------------------------------
# The STIR leg
# ---------------------------------------------------------------------------
#: Business days per year. The two legs are quoted in different units and the
#: conversion between them is this, under the square root.
BUSINESS_DAYS = 252.0


def stir_implied_vol_series(panel: pd.DataFrame, cfg: W3Config = W3Config(),
                            *, ca_col: str = "ca_bp") -> pd.Series:
    """Ho-Lee vol implied by the pack's own convexity adjustment, **bp/day**.

    **The unit conversion here is the whole point and it is not cosmetic.**
    ``holee.implied_vol_from_ca_bp`` returns **bp per YEAR** — its docstring says
    so — while the long-end leg's ``be_daily_analytic`` is Citi's daily
    breakeven, in **bp per DAY**. Differencing or spreading them as they come
    compares quantities a factor of ``sqrt(252) ≈ 15.9`` apart.

    That is not hypothetical: the first run of this module printed a STIR leg
    averaging 100-135 and a long-end leg averaging 2.5-4.0, and a "spread" of
    about 100 bp that was almost entirely the unit mismatch. Correlation is
    scale-invariant so the link diagnostics survived it, but every level, spread
    and z-score did not. This package has the same trap on record twice already
    (``delta_abs`` in percent, ``ABPV/ATM`` differing by asset class).

    Both legs leave this module in **bp/day**.

    Keyed on **rank**, not on pack label, and stitched across labels — a colour
    is a constant-maturity slot and its label rolls with the strip. Reading one
    label's column instead collapses the series to that label's life, which in
    this package once turned 2,000 dates into 239 and produced a confident
    regression on eleven points.

    ``time_weight`` is the pack's ``mean(T1²)`` under the configured convention,
    so ``sqrt(time_weight)`` is the single pseudo-``T1`` that reproduces it
    exactly — the same substitution ``daily_screen`` makes.
    """
    from RVUtils.ConvexityRV.ca_signals import COLOUR_RANK
    from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp

    if cfg.colour not in COLOUR_RANK:
        raise KeyError(f"unknown colour {cfg.colour!r}")
    rank = COLOUR_RANK[cfg.colour]

    sub = panel[(panel["rank"] == rank)].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub[(sub["date"] >= pd.Timestamp(cfg.start))
              & (sub["date"] <= pd.Timestamp(cfg.end))]
    if sub.empty:
        return pd.Series(dtype=float)

    out = {}
    for _, r in sub.iterrows():
        ca, w = float(r[ca_col]), float(r["time_weight"])
        if not (np.isfinite(ca) and np.isfinite(w) and w > 0 and ca > 0):
            continue
        try:
            annual = float(implied_vol_from_ca_bp(
                ca, [math.sqrt(w)], convention=cfg.holee_convention))
        except Exception:                                        # noqa: BLE001
            continue
        if np.isfinite(annual):
            out[r["date"]] = annual / math.sqrt(BUSINESS_DAYS)   # bp/yr -> bp/day
    s = pd.Series(out).sort_index()
    s = s[~s.index.duplicated(keep="first")].rename(f"stir_iv_{cfg.colour}")

    # A guard, not a formality. A SOFR normal vol is order 50-200 bp/yr, i.e.
    # 3-13 bp/day. If this ever leaves in the wrong unit the numbers stay
    # plausible-looking in isolation and only the SPREAD against the long end
    # goes wrong, which is the hardest place to notice it.
    if len(s):
        med = float(s.median())
        if not (0.5 <= med <= 40.0):
            raise ValueError(
                f"STIR implied vol median {med:.2f} is outside 0.5-40 bp/DAY. "
                "holee.implied_vol_from_ca_bp returns bp/YEAR; this series must "
                "be divided by sqrt(252) before it can be compared with a daily "
                "breakeven.")
    return s


# ---------------------------------------------------------------------------
# Diagnostics that come BEFORE the trade
# ---------------------------------------------------------------------------
def link_diagnostics(stir: pd.Series, longend: pd.Series) -> Dict[str, float]:
    """Do the two legs have anything to do with each other?

    Reports level and change correlation. **The change correlation is the one
    that matters**: two trending series correlate in levels for reasons that
    have nothing to do with a tradable relationship, and a spread built on a
    levels-only link is two random walks wearing a signal's clothes.
    """
    df = pd.concat([stir.rename("stir"), longend.rename("long")], axis=1).dropna()
    if len(df) < 30:
        return {"n": float(len(df)), "corr_levels": float("nan"),
                "corr_changes": float("nan"), "beta_changes": float("nan"),
                "stir_mean": float("nan"), "long_mean": float("nan")}
    d = df.diff().dropna()
    beta = float(np.polyfit(d["long"], d["stir"], 1)[0]) if d["long"].std() > 0 else np.nan

    # Is the spread stationary? This is the question a z-score entry ASSUMES the
    # answer to. Two series with no change-correlation give a spread that is
    # itself a random walk, and a random walk does not revert -- so a signal
    # built on its z-score is fitting the sampling distribution of a unit root,
    # not a relationship. Reported whether or not it is flattering.
    adf_p, half_life = float("nan"), float("nan")
    try:
        from statsmodels.tsa.stattools import adfuller

        sp = (df["stir"] - df["long"]).dropna()
        if len(sp) >= 60:
            adf_p = float(adfuller(sp.to_numpy(), autolag="AIC")[1])
            # Ornstein-Uhlenbeck half-life from the AR(1) coefficient.
            lag = sp.shift(1).dropna()
            cur = sp.loc[lag.index]
            b = float(np.polyfit(lag.to_numpy(), (cur - lag).to_numpy(), 1)[0])
            if b < 0:
                half_life = float(-np.log(2.0) / b)
    except Exception:                                            # noqa: BLE001
        pass

    return {
        "n": float(len(df)),
        "corr_levels": float(df["stir"].corr(df["long"])),
        "corr_changes": float(d["stir"].corr(d["long"])),
        "beta_changes": beta,
        "stir_mean": float(df["stir"].mean()),
        "long_mean": float(df["long"].mean()),
        "stir_sd": float(df["stir"].std()),
        "long_sd": float(df["long"].std()),
        "spread_adf_p": adf_p,
        "spread_half_life_days": half_life,
    }


# ---------------------------------------------------------------------------
# The spread and its signal
# ---------------------------------------------------------------------------
def build_vol_spread_panel(stir: pd.Series, longend: pd.Series,
                           cfg: W3Config = W3Config()) -> pd.DataFrame:
    """``(date) -> spread, z, and the lagged versions the rule reads``.

    The spread is ``stir_iv − longend_be`` in bp/day, both legs already on the
    same ruler, so no scaling is fitted and there is nothing to get backwards.

    **Everything the rule reads is lagged one day.** The z-score is computed on
    the lagged spread, not lagged after the fact, so a caller cannot rank on
    same-day information by accident.
    """
    df = pd.concat([stir.rename("stir_iv"), longend.rename("long_be")],
                   axis=1).dropna().sort_index()
    if df.empty:
        return df
    df["spread"] = df["stir_iv"] - df["long_be"]
    df["spread_lag"] = df["spread"].shift(1)
    roll = df["spread_lag"].rolling(cfg.z_window, min_periods=cfg.min_periods)
    df["z"] = (df["spread_lag"] - roll.mean()) / roll.std(ddof=0)
    return df


def entry_state(spread_panel: pd.DataFrame, cfg: W3Config = W3Config()) -> pd.Series:
    """``+1`` / ``-1`` / ``0``: short the STIR leg, long it, or flat.

    ``+1`` means **the STIR-implied vol is rich against the long end** — sell
    the pack convexity, buy the long-end convexity. ``-1`` is the mirror. The
    rule is deliberately two-sided: a one-sided version of a spread trade is a
    directional position on one of its legs, which is the degeneracy this
    package has already had to unpick once.

    Hysteresis: enter at ``entry_z``, leave at ``exit_z``. Without it a z-score
    crossing its own threshold repeatedly produces a book of two-day trades, and
    on this package's own numbers a 0.5bp round trip eats that alive.
    """
    z = spread_panel.get("z")
    if z is None or z.empty:
        return pd.Series(dtype=int)
    state, cur = [], 0
    for v in z.to_numpy():
        if not np.isfinite(v):
            cur = 0
        elif cur == 0:
            if v >= cfg.entry_z:
                cur = 1
            elif v <= -cfg.entry_z:
                cur = -1
        elif cur == 1 and v <= cfg.exit_z:
            cur = 0
        elif cur == -1 and v >= -cfg.exit_z:
            cur = 0
        state.append(cur)
    return pd.Series(state, index=spread_panel.index, name="state", dtype=int)
