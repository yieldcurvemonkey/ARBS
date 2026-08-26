"""Historical signal panels for the two W3 QDB reference strategies.

C2.5 layer of the CvxSuite (docs/cvxsuite/DESIGN.md sections 5-6): the
kink-screen is an AS-OF object (one date, repriced rent, MC first-passage);
the QDB strategies need the same statistics as HISTORY, cheap enough to build
over ~1,900 dates.  This module builds those panels from the leg history
(``docs/cvxsuite/leg_history.parquet``: date x lowercase-label forward rates
in BP) plus, for the harvest carry/breakeven block, a repriced per-leg panel
built through the offline curve store.  It composes kernels only — grids,
residuals, ou (``RVUtils.mean_reversion`` re-exports),
``ConvexityRV.strat3_strikeless_vol`` and ``BT.signals.cvx_strikeless.
build_curve_map`` (lazy) — and re-derives nothing.

The three builders and their strategy contracts
-----------------------------------------------
* :func:`build_leg_panel` -> ``(date, leg)`` frame ``rate_bp, dv01, gamma,
  roll_1y, roll_1d`` via ``strat3_strikeless_vol.leg_metrics`` (the repriced
  kernel: carry corr +0.991 vs Citi Fig-7; ``CARRY_AND_ROLL_BPS_RUNNING``
  scored -0.136 and is never used here).  Curves come chunk-wise from
  ``BT.signals.cvx_strikeless.build_curve_map`` — the exact bulk recipe with
  the refuse-today guard (``bulk_get_data`` coerces today to ``"live"``), the
  reference-date match and the ``from_curve_store`` assert.  Leg labels are
  STORED IN THE strat3 FORM ``"10Yx10Y"`` (the form ``parse_fwd`` and
  ``screen_panel_from_legs`` consume; the ``rac_build_leg_panel.py``
  precedent); the lowercase cache form ``"10y10y"`` is accepted on input and
  canonicalised.  Spot legs (fwd = 0) are REFUSED loudly: ``leg_metrics``
  would build ``fwd="0Y"`` where the engine's spot path is ``"0D"``.
* :func:`build_harvest_panel` -> ``(date, pair)`` frame for
  ``BT.signals.cvx_kink_harvest.episodes_from_panel`` (index names exactly
  ``("date", "pair")``; gate columns ``be_over_rv, zs, rac_net``; entries are
  read at t-1 by the strategy, this panel is un-lagged by design).
* :func:`build_dislocation_panel` -> ``(date, point)`` frame for
  ``BT.signals.cvx_fly_dislocation.episodes_from_panel`` (index names exactly
  ``("date", "point")``; gate columns ``zs, sign_agree, tag, edge_bp``;
  sizing columns ``leg_front/leg_belly/leg_back, w_front/w_belly/w_back``).

Harvest conventions (binding, documented per the task)
------------------------------------------------------
* **Pair level** = ``back_leg - front_leg`` in bp (pair written
  ``"front/back"``, shorter forward start first, e.g. ``"10y10y/15y10y"``).
  The harvest STRATEGY holds the STEEPENER — receive the front leg
  (bpv = -dv01), pay the back leg (bpv = +dv01) — whose P&L per bp is
  ``+d(level)``: the strategy is LONG this level.  strat3's screen prices the
  MIRROR (the Citi flattener: pay short/front, receive long/back), so its
  ``carry_1y_bp`` is the flattener's carry; this panel carries BOTH columns:
  ``carry_flat_1y_bp`` (verbatim strat3) and ``carry_lvl_1y_bp = -carry_flat_
  1y_bp`` — the carry of the level-long (steepener) side actually held.
* **zs** = rolling ``z_window`` (756) z of the pair level, ``min_periods =
  z_min_obs`` (252), ddof = 1, window ending AT each date (the kink-screen
  trailing convention).  Positive = level HIGH vs its own trailing window =
  ENTRY-ADVERSE for the level-long steepener; the strategy gate ``zs <=
  max_z`` refuses buying a level already high.  The level z-scored here is
  the RAW QUOTED ``back - front`` — a stated approximation, mirroring the
  dislocation builder's disclosure (DESIGN §6a item 6): the as-of screen
  z-scores convexity-ADJUSTED levels, but the CA of a smooth surface drifts
  slowly and the 756d z differences it out; adjusted-level plumbing (a
  ``ca_bp`` parameter) is future work — never a claim the CA is zero.
* **rac_net** = carry net of reversion drag AT THE MEASURED AR(1) HALF-LIFE
  HORIZON: ``rac_net = carry_lvl_1y_bp * (HL_d / 252) + rev_drag_bp`` with
  ``rev_drag_bp = (rolling_mean_756 - level) * (1 - 2**(-h/HL))`` evaluated
  at ``h = HL`` — the factor is exactly 0.5.  Orientation: the drag is the
  expected AR(1) move of the level toward its trailing mean, signed for the
  LEVEL-LONG (steepener) holder — level below mean ⇒ positive drag.  NOTE
  the citation honestly: ``CurveFlyScreener.add_risk_adjustment`` itself
  charges FULL reversion (``mean - last``, no scaling); the task pins the
  half-life-scaled form ``(1 - 2**(-h/HL))``, which at h = HL halves it.
  The rolling 756 mean is the walk-forward analogue of the screener's sample
  mean (a full-sample mean would be look-ahead in a historical panel).  A
  non-reverting window (AR(1) phi outside (0,1) -> HL NaN) refuses: rac_net
  NaN, never a substituted zero.  This is rac_net@HL — the as-of screen's
  rac_net@FPT uses the MC first-passage clock instead (stated divergence).
* **be_over_rv** comes from ``strat3.screen_panel_from_legs`` +
  ``add_screen_stats`` on the leg panel (be_daily_analytic of the FLATTENER
  package over the trailing 252d vol of the LONG leg's rate — Citi's own
  ruler), reindexed onto the panel; NaN wherever the leg panel does not
  cover the date (including the ~120-business-day realized-vol warmup at the
  leg panel's start).  When neither ``leg_panel`` nor ``curve_map`` is given
  the carry/be columns are all-NaN and the harvest gates refuse everything —
  a data statement, never a silent zero.

Dislocation conventions (binding, documented per the task)
----------------------------------------------------------
* Grid = the 15 INTERIOR points of ``grids.KINK_GRID`` (endpoints have no
  adjacent fly).  ``point`` labels are the lowercase belly leg labels.
* **Fly level** ``L = 2*belly - front - back`` on the QUOTED leg-history
  levels — the BELLY=+2 RULER (DESIGN §6a item 1: ONE fly ruler suite-wide,
  matching the kink screen), rate-space weights ``(-1, +2, -1)``: the
  constant approximation of the kink screen's DV01-neutral
  ``neutral_weights`` fly (same shape, belly at +2, no pricer).  Rescaling
  from the pre-amendment belly=+1 form doubles ``fly_bp``, ``e_rev_bp`` and
  ``carry_bp_day``; ``zs``, ``half_life_d``, ``e_fpt_d`` and ``p_hit_proxy``
  are scale-invariant and unchanged.
  Residuals and L are computed on the SAME level definition: RAW quoted
  levels by default; pass ``ca_bp`` (a date x label convexity-adjustment
  frame, bp, positive = quoted forward depressed) to run the whole panel on
  convexity-ADJUSTED levels instead.  The as-of screen always adjusts; this
  panel's raw default is a stated approximation — the fly of a smooth CA
  surface is second-difference small, and the 756d z differences out its
  slow drift — never a claim the CA is zero.
* **POLARITY (binding, agreed with the sibling kink_screen refactor):**
  ``zs = z(L, 756)`` and ``zs > 0`` = fly level HIGH = belly rate high vs
  wings = belly CHEAP (yield-space) = the mean-reversion fade RECEIVES the
  belly.  Direction seam, verified consistent on this worktree (2026-08-26):
  ``BT.signals.cvx_fly_dislocation._entry_signal`` maps ``zs > 0 ->
  direction = -1`` (receive belly) — exactly this polarity.  An earlier
  revision of that module mapped ``zs > 0 -> +1`` (pay); if the mapping ever
  regresses, the book silently trades the momentum side of every fade.  The
  panel implements the binding polarity verbatim and never compensates — the
  direction mapping belongs to the strategy layer.
* **OU on L**: vectorised rolling AR(1) (``mean_reversion.rolling_ar1``,
  window ``ou_window`` = 756, ``min_periods`` = ``ou_min_obs`` = 252 usable
  pairs) — the same calibrate_ou convention as the screen, vectorised.
* **e_fpt_d** — ANALYTIC, not MC (the screen's ``fpt_sample`` at sims 2000 x
  steps 504 per (date, point) is minutes per build; the section-6 MC config
  is an AS-OF cost).  Route: standardise ``z0 = (L - mu)/sigma_eq``; the
  passage to the halfway target ``(L + mu)/2`` is, by OU symmetry, the
  UP-crossing ``a = -|z0| -> m = -|z0|/2`` of the standardized OU, so
  ``e_fpt_d = expected_passage_time(-|z0|, -|z0|/2, kappa=kappa_day)``
  (Bertram-2010 series, Gamma in the numerator, MC-verified in
  ``mean_reversion`` and re-verified here: at z0 = 2 the series gives
  0.5233/kappa vs 0.5413/kappa by 4000-path MC at dt = 0.002 — the MC's
  +3% is discrete-monitoring overshoot).  The series is evaluated once per
  ROUNDED |z0| (2dp) at kappa = 1 and scaled by 1/kappa (exact identity);
  beyond ``fpt_z_cap`` = 6.0 the deterministic-decay limit ``e_fpt = HL``
  is used (measured: the series ratio to HL is 0.949 at z0 = 6 and loses
  precision by z0 = 8 — alternating-series cancellation).  Divergence from
  the screen, stated: this e_fpt is the UNCENSORED expectation; the screen's
  MC e_fpt folds censored paths in at 504 steps and is biased LOW when
  censoring is material.
* **e_rev_bp** = ``|L - mu_ou| * (1 - 2**(-h/HL))`` at ``h = HL`` =
  ``0.5 * |L - mu_ou|`` — identical to the screen's halfway-target
  ``e_rev_bp = |mu - x|/2``.
* **p_hit_proxy** = ``1 - exp(-h / e_fpt_d)`` at ``h = max_hold_bd = 63``
  (exponential passage-time approximation AT THE FROZEN BOOK'S OWN CLOCK —
  DESIGN §6a item 2: the strategy must exit at 63bd, so the edge credits
  only reversion reachable inside the hold, never the old 504-step cap) —
  the analytic stand-in for the screen's MC ``p_hit`` at the SAME horizon.
  ``e_fpt_d`` itself stays UNCAPPED as its own column.
* **carry_bp_day** — the ING STRIP-INTERPOLATION APPROXIMATION, PANEL-ONLY
  (stated loudly per the task; the as-of screen keeps the REPRICED
  aged-rate-identity carry): per leg the 3m roll-down is ``0.25 * (f(k) -
  f(k-1))`` with ``f(k-1)`` the forward strip linearly interpolated at
  abscissa ``k_coord - 1`` year; the level-LONG holder's carry is MINUS the
  roll-down (ageing marks the leg at the strip one year nearer), so
  ``carry_bp_day = -[ sum_i w_i * (f(k_i) - f_interp(k_i - 1)) ] / 252``
  with the RATE-SPACE weights ``w = (-1, +2, -1)`` (the belly=+2 ruler) —
  signed for the LONG-the-fly-level (pay belly) holder, the screen's carry
  convention.  The spot-1y leg has no ``k - 1`` on the strip: the 1y1y
  fly's carry is NaN (meeting zone; the strategy's ``tag == "clean"`` gate
  never trades it anyway).
* **edge_bp** = ``e_rev_bp * p_hit_proxy - |carry_bp_day| * min(e_fpt_d, h)
  - cost_rt_bp`` at ``h = max_hold_bd = 63`` — THE SHARED EDGE FORMULA
  (screen and panel alike, DESIGN §6a item 2): reversion credited at
  P(hit <= h), carry charged as a COST regardless of side over only the
  days actually held, ``min(E[FPT], h)``.  Cost default 2.3 bp — the middle
  of the measured 2.0-2.6 fly-package RT band, now correctly denominated on
  the belly=+2 L (§6a item 1; the suite's own 0.3bp/leg one-way anchor
  reproduces it on THIS ruler: total leg |DV01| = 2*dv01 against dv01/2 USD
  per bp of L, so 2 sides x 0.3bp x 4 = 2.4 ~ the band mid).  NaN
  propagates; NaN refuses at the strategy gate.
* **tag** = ``grids.classify_point`` (meeting / clean / convexity);
  ``leg_front/leg_belly/leg_back`` = the adjacent lowercase grid labels;
  ``w_front/w_belly/w_back`` = ``(-0.5, +1.0, -0.5)`` constants (belly > 0,
  wings < 0 — the orientation ``cvx_fly_dislocation`` validates).  These
  are the DOLLAR leg weights — per-leg DV01 as fractions of the strategy's
  ``package_dv01_usd`` (leg i trades ``bpv_i = direction * w_i * dv01``) —
  NOT the rate-space ``(-1, +2, -1)`` that defines L: the
  ``(-0.5, +1, -0.5) * dv01`` package pays ``dv01/2`` USD per bp of the
  belly=+2 L, which is what the strategy's fee is derived from.

What this module does NOT do: no entries, no lag (the strategies read t-1
themselves), no aliveness claims, no repriced gamma/theta over history (the
rent block is as-of only, by DESIGN), no vega.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.CvxSuite import grids
from RVUtils.CvxSuite.ou import expected_passage_time, rolling_ar1
from RVUtils.CvxSuite.residuals import (
    adjusted_levels,
    sign_agreement,
    walk_forward_pca_residuals,
    xsec_residuals,
)

__all__ = [
    "HARVEST_PAIRS",
    "HARVEST_LEGS",
    "CvxPanelCfg",
    "leg_to_strat3",
    "leg_to_lc",
    "parse_pair",
    "build_leg_panel",
    "build_harvest_panel",
    "build_dislocation_panel",
]

BUSINESS_DAYS = 252.0

#: DESIGN section 6 harvest pairs — forward-tenor family members of KINK_GRID,
#: written "front/back" (shorter forward start first), lowercase cache form.
HARVEST_PAIRS: Tuple[str, ...] = (
    "10y10y/15y10y", "10y10y/20y10y", "15y5y/20y10y")

#: The union of legs the section-6 harvest pairs need (lowercase form).
HARVEST_LEGS: Tuple[str, ...] = ("10y10y", "15y10y", "20y10y", "15y5y")

# "20Yx10Y" (strat3) | "20y10y" / "10y" (CurveFlyScreener cache form).
_S3_LABEL = re.compile(r"^(\d+(?:\.\d+)?)\s*Y\s*X\s*(\d+(?:\.\d+)?)\s*Y$",
                       re.IGNORECASE)
_LC_LABEL = re.compile(r"^(?:(\d+(?:\.\d+)?)y)?(\d+(?:\.\d+)?)y$")


def _parse_leg(label: str) -> Tuple[float, float]:
    """``"10y10y"`` | ``"10Yx10Y"`` | ``"10y"`` -> (fwd, tenor) years; loud otherwise."""
    s = str(label).strip()
    m = _S3_LABEL.match(s) or _LC_LABEL.match(s.lower())
    if m is None:
        raise ValueError(
            f"unparseable leg label {label!r}: expected '10Yx10Y', '10y10y' or '10y'")
    fwd = float(m.group(1)) if m.group(1) is not None else 0.0
    tenor = float(m.group(2))
    if not (math.isfinite(fwd) and math.isfinite(tenor)) or fwd < 0.0 or tenor <= 0.0:
        raise ValueError(f"leg label {label!r} has illegal coordinates ({fwd}, {tenor})")
    return fwd, tenor


def leg_to_strat3(label: str) -> str:
    """Canonical strat3 form ``"10Yx10Y"`` — what ``parse_fwd`` and the
    ``screen_panel_from_legs`` leg level consume.  Spot legs (fwd = 0) are
    REFUSED: ``leg_metrics`` would build ``fwd="0Y"`` where the engine's spot
    path is ``"0D"`` (the ``_fwd_arg`` trap recorded in the cvx_* modules)."""
    fwd, tenor = _parse_leg(label)
    if fwd == 0.0:
        raise ValueError(
            f"spot leg {label!r} (fwd=0) is not supported by the strat3 leg panel: "
            "leg_metrics would price fwd='0Y' where the engine's spot path is '0D'")
    return f"{fwd:g}Yx{tenor:g}Y"


def leg_to_lc(label: str) -> str:
    """Lowercase CurveFlyScreener cache form ``"10y10y"`` via ``grids.leg_label``."""
    fwd, tenor = _parse_leg(label)
    return grids.leg_label(grids.KinkPoint(fwd, tenor))


def parse_pair(pair: str) -> Tuple[str, str]:
    """``"10y10y/15y10y"`` -> (front, back), both legs validated."""
    parts = [p.strip() for p in str(pair).split("/")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"pair {pair!r} must be 'front/back' with exactly two legs")
    for p in parts:
        _parse_leg(p)
    return parts[0], parts[1]


@dataclasses.dataclass(frozen=True)
class CvxPanelCfg:
    """Frozen panel config.  Statistics windows are the DESIGN section-6
    numbers (z/OU trailing 756, PCA n_pcs 2 / window 756 / min 504 / monthly);
    ``z_min_obs``/``ou_min_obs`` = 252 is the kink screen's ``stats_min_obs``.
    ``max_hold_bd`` = 63 is the frozen book's exit clock
    (``FlyDislocationConfig.max_hold_bd``) — DESIGN §6a item 2 requires the
    edge's p_hit horizon AND its carry charge to run on it (the pre-amendment
    504-step p_hit cap and uncapped carry horizon priced a hold the 63bd book
    cannot run).  ``cost_rt_bp`` = 2.3 is the frozen mid of the measured
    2.0-2.6 bp 3-leg-package round-trip band, denominated on the belly=+2
    fly level L = 2b - f - k (§6a item 1).  ``fpt_z_cap`` is measured on
    this machine: the Bertram series is stable and monotone to |z0| = 6
    (ratio to HL 0.949) and loses precision by |z0| = 8; beyond the cap the
    deterministic-decay limit ``e_fpt = HL`` applies."""

    # trailing z (kink-screen convention: window ends AT the date, ddof=1)
    z_window: int = 756
    z_min_obs: int = 252
    # rolling AR(1)/OU
    ou_window: int = 756
    ou_min_obs: int = 252
    # cross-sectional fit (DESIGN section 6)
    xsec_variant: str = "spline"
    xsec_knots: Tuple[float, ...] = (1.0, 3.0, 7.0, 15.0, 27.0)
    # walk-forward PCA (DESIGN section 6)
    n_pcs: int = 2
    pca_window: int = 756
    pca_min_window: int = 504
    pca_refit: str = "M"
    sign_min_abs_bp: float = 0.5
    # analytic FPT
    fpt_z_cap: float = 6.0
    fpt_z_round: int = 2          # |z0| rounding for the series memo (2dp)
    # edge / costs (the §6a shared edge formula, h = the frozen book's clock)
    max_hold_bd: int = 63
    cost_rt_bp: float = 2.3
    # strat3 screen composition
    package_dv01_usd: float = 100_000.0
    business_days: float = BUSINESS_DAYS
    rlzd_vol_window: int = 252

    def __post_init__(self):
        if int(self.z_min_obs) > int(self.z_window):
            raise ValueError(f"z_min_obs {self.z_min_obs} > z_window {self.z_window}")
        if int(self.ou_min_obs) > int(self.ou_window):
            raise ValueError(f"ou_min_obs {self.ou_min_obs} > ou_window {self.ou_window}")
        if not (np.isfinite(self.fpt_z_cap) and self.fpt_z_cap > 0):
            raise ValueError(f"fpt_z_cap must be finite and > 0, got {self.fpt_z_cap}")
        if int(self.max_hold_bd) < 1:
            raise ValueError(f"max_hold_bd must be >= 1, got {self.max_hold_bd}")


# ---------------------------------------------------------------------------
# shared input discipline
# ---------------------------------------------------------------------------

def _check_hist(leg_hist_bp: pd.DataFrame, needed: Sequence[str], where: str,
                *, min_median_abs_bp: float = 20.0) -> pd.DataFrame:
    """DatetimeIndex + required columns + bp-scale guard; returns the slice."""
    if not isinstance(leg_hist_bp.index, pd.DatetimeIndex):
        raise TypeError(f"{where}: leg_hist_bp needs a DatetimeIndex, got "
                        f"{type(leg_hist_bp.index).__name__}")
    missing = [c for c in needed if c not in leg_hist_bp.columns]
    if missing:
        raise ValueError(f"{where}: leg_hist_bp is missing columns {missing}")
    if leg_hist_bp.index.has_duplicates:
        raise ValueError(f"{where}: leg_hist_bp index has duplicate dates")
    out = leg_hist_bp[list(needed)].sort_index()
    arr = out.to_numpy(dtype=float)
    if arr.size == 0 or np.all(np.isnan(arr)):
        raise ValueError(f"{where}: leg_hist_bp slice is empty or all-NaN")
    med = float(np.nanmedian(np.abs(arr)))
    if min_median_abs_bp > 0 and med < min_median_abs_bp:
        raise ValueError(
            f"{where}: panel median |level| = {med:.6g} is below the bp-scale "
            f"guard ({min_median_abs_bp:g}); the input looks like percent or "
            "decimal units, not bp")
    return out


def _roll_z(frame: pd.DataFrame, window: int, min_obs: int
            ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(z, rolling_mean): trailing z ending AT each row, ddof=1 (screen convention)."""
    r = frame.rolling(int(window), min_periods=int(min_obs))
    mu = r.mean()
    sd = r.std(ddof=1)
    z = (frame - mu) / sd.where(sd > 1e-12)
    return z, mu


# ---------------------------------------------------------------------------
# leg panel (repriced, offline curve store)
# ---------------------------------------------------------------------------

def build_leg_panel(dates: Sequence[Any], legs: Sequence[str], *,
                    curve_map: Optional[Mapping[Any, Any]] = None,
                    mdp: Any = None, n_jobs: int = 1, chunk_days: int = 60,
                    progress: bool = True) -> pd.DataFrame:
    """``(date, leg)`` repriced metrics panel: ``rate_bp, dv01, gamma,
    roll_1y, roll_1d`` — one ``strat3_strikeless_vol.leg_metrics`` call per
    leg per served day.

    * ``legs`` accepts lowercase or strat3 labels; the LEG LEVEL IS STORED IN
      strat3 FORM (``"10Yx10Y"``) — the form ``screen_panel_from_legs``
      consumes.  Spot legs refuse (see :func:`leg_to_strat3`).
    * Curves come from ``BT.signals.cvx_strikeless.build_curve_map`` (lazy
      import), CHUNKED ``chunk_days`` at a time so at most one chunk of
      store-backed pricers is alive at once (~1,400 pricers in one dict is a
      memory hazard).  The recipe's guards apply per chunk: refuse-today,
      reference-date match, ``from_curve_store`` assert (a quotes-rebuild
      fallback RAISES); holidays/unwarmed days are dropped by the bulk path
      and reported, never silently zero-filled.
    * A leg_metrics failure on a served day is COUNTED and that (date, leg)
      row is ABSENT (NaN downstream = refusal); the per-day roll horizons are
      the rac_build_leg_panel convention (``1y`` = +1 DateOffset year, ``1d``
      = +1 calendar day).  Zero rows overall raises.

    When ``curve_map`` is passed it is used as-is (no chunking, no fetching)
    — the guards are assumed already applied by ``build_curve_map``.
    """
    from RVUtils.ConvexityRV.strat3_strikeless_vol import leg_metrics

    labels_s3 = [leg_to_strat3(l) for l in legs]
    if len(set(labels_s3)) != len(labels_s3):
        raise ValueError(f"duplicate legs after canonicalisation: {labels_s3}")

    def _one_map(cmap: Mapping[Any, Any]) -> Tuple[List[dict], int]:
        rows: List[dict] = []
        n_fail = 0
        for d, pricer in sorted(cmap.items()):
            ts = pd.Timestamp(d).normalize()
            horizons = (("1y", ts + pd.DateOffset(years=1)),
                        ("1d", ts + pd.Timedelta(days=1)))
            for lab in labels_s3:
                try:
                    m = leg_metrics(pricer, lab, roll_horizons=horizons)
                except Exception:
                    n_fail += 1
                    continue
                rows.append({"date": ts, "leg": lab,
                             "rate_bp": float(m["rate_bp"]),
                             "dv01": float(m["dv01"]),
                             "gamma": float(m["gamma"]),
                             "roll_1y": float(m["roll_1y"]),
                             "roll_1d": float(m["roll_1d"])})
        return rows, n_fail

    t0 = time.time()
    all_rows: List[dict] = []
    n_fail = 0
    if curve_map is not None:
        all_rows, n_fail = _one_map(curve_map)
        n_req = len(curve_map)
    else:
        from BT.signals.cvx_strikeless import build_curve_map

        days = sorted({pd.Timestamp(d).date() for d in dates})
        n_req = len(days)
        if not days:
            raise ValueError("build_leg_panel: no dates requested")
        step = max(1, int(chunk_days))
        for i in range(0, len(days), step):
            chunk = days[i:i + step]
            cmap = build_curve_map(chunk, mdp=mdp, n_jobs=int(n_jobs))
            rows, nf = _one_map(cmap)
            all_rows.extend(rows)
            n_fail += nf
            del cmap
            if progress:
                print(f"  leg_panel: {min(i + step, len(days))}/{len(days)} days, "
                      f"{len(all_rows):,} rows, {n_fail} leg failures, "
                      f"{time.time() - t0:.0f}s", flush=True)

    if not all_rows:
        raise ValueError(
            f"build_leg_panel: nothing built for {n_req} requested days x "
            f"{len(labels_s3)} legs — is the curve store warmed for this window?")
    panel = (pd.DataFrame(all_rows)
             .drop_duplicates(subset=["date", "leg"], keep="last")
             .set_index(["date", "leg"]).sort_index())
    panel.index.names = ["date", "leg"]
    if n_fail:
        print(f"build_leg_panel: {n_fail} leg_metrics failures (rows absent, "
              "never zero-filled)", flush=True)
    return panel


# ---------------------------------------------------------------------------
# harvest panel
# ---------------------------------------------------------------------------

def _screen_block(leg_panel: pd.DataFrame, pairs_lc: Sequence[str],
                  cfg: CvxPanelCfg) -> pd.DataFrame:
    """strat3 screen columns for the pairs, (date, pair) with LOWERCASE pairs.

    Composes ``screen_panel_from_legs`` + ``add_screen_stats`` and then
    RENAMES the pair level from the strat3 join form (``"10Yx10Y/15Yx10Y"``)
    to the lowercase contract form (``"10y10y/15y10y"``).

    LOAD-BEARING ASSERT (MUTATION: remove it and a lowercase-keyed or partial
    leg panel silently yields an EMPTY/partial screen — ``screen_panel_from_
    legs`` skips missing legs with ``except KeyError: continue`` — and every
    harvest gate would refuse forever while the build reports success):
    every requested pair must come back from the screen, and the frame must
    be non-empty.
    """
    from RVUtils.ConvexityRV.strat3_strikeless_vol import (
        add_screen_stats,
        screen_panel_from_legs,
    )

    if not isinstance(leg_panel.index, pd.MultiIndex) or \
            list(leg_panel.index.names) != ["date", "leg"]:
        raise ValueError(
            "leg_panel must be indexed (date, leg) with those exact names, got "
            f"{list(leg_panel.index.names)}")
    have = set(leg_panel.index.get_level_values("leg"))
    pairs_s3: List[Tuple[str, str]] = []
    lc_of: Dict[str, str] = {}
    for p in pairs_lc:
        f, b = parse_pair(p)
        f3, b3 = leg_to_strat3(f), leg_to_strat3(b)
        missing = [l for l in (f3, b3) if l not in have]
        if missing:
            raise ValueError(
                f"leg_panel is missing legs {missing} for pair {p!r} — the leg "
                f"level must be strat3-form labels (have e.g. {sorted(have)[:4]}); "
                "a lowercase-keyed panel would be skipped SILENTLY by "
                "screen_panel_from_legs")
        pairs_s3.append((f3, b3))
        lc_of[f"{f3}/{b3}"] = f"{leg_to_lc(f)}/{leg_to_lc(b)}"

    sp = screen_panel_from_legs(
        leg_panel, pairs_s3, package_dv01_usd=float(cfg.package_dv01_usd),
        business_days=float(cfg.business_days))
    got = set(sp.index.get_level_values("pair")) if len(sp) else set()
    want = set(lc_of)
    if len(sp) == 0 or got != want:
        raise AssertionError(
            f"screen_panel_from_legs returned pairs {sorted(got)} for requested "
            f"{sorted(want)} — a missing leg was skipped silently upstream")
    sp = add_screen_stats(sp, leg_panel,
                          z_windows=(("3y", int(cfg.z_window)),),
                          vol_window=int(cfg.rlzd_vol_window))
    sp = sp.rename(index=lc_of, level="pair")
    return sp[["carry_1y_bp", "be_daily_analytic", "rlzd_vol_bp", "be_over_rv"]]


def build_harvest_panel(leg_hist_bp: pd.DataFrame, *, pairs: Sequence[str],
                        curve_map: Optional[Mapping[Any, Any]] = None,
                        cfg: Optional[CvxPanelCfg] = None,
                        leg_panel: Optional[pd.DataFrame] = None,
                        ) -> pd.DataFrame:
    """The kink-harvest signal panel, ``(date, pair)`` (names exactly that).

    Index: every ``leg_hist_bp`` date x every pair (lowercase
    ``"front/back"``).  Columns:

    ``level_bp``          back - front (bp) — the STRATEGY IS LONG THIS LEVEL
                          (steepener: receive front / pay back; module
                          docstring, "Harvest conventions").
    ``zs``                rolling z of level (window ``cfg.z_window``, min
                          ``cfg.z_min_obs``, ddof 1); positive = level high
                          = entry-adverse for the level-long steepener.  On
                          RAW QUOTED levels — a stated approximation
                          mirroring the dislocation builder's disclosure
                          (module docstring, "Harvest conventions"; §6a
                          item 6): the as-of screen adjusts for convexity,
                          this historical panel does not (ca_bp plumbing is
                          future work).
    ``half_life_d``       rolling AR(1) half-life of the level (756d fit),
                          business days; NaN = non-reverting window.
    ``rev_drag_bp``       ``(rolling_mean - level) * (1 - 2**(-h/HL))`` at
                          h = HL (factor exactly 0.5); level-long signed.
    ``carry_flat_1y_bp``  strat3 screen carry verbatim (the FLATTENER's).
    ``carry_lvl_1y_bp``   ``-carry_flat_1y_bp`` — the held (steepener) side.
    ``rac_net``           ``carry_lvl_1y_bp * (HL/252) + rev_drag_bp`` (bp);
                          NaN whenever HL or carry is NaN (refusal).
    ``be_daily_bp`` / ``rlzd_vol_bp`` / ``be_over_rv``
                          from ``strat3.screen_panel_from_legs`` +
                          ``add_screen_stats`` (flattener breakeven over the
                          long leg's trailing vol) — NaN off the leg-panel
                          window (including its ~120bd realized-vol warmup).

    ``leg_panel`` (a :func:`build_leg_panel` frame) takes precedence; else it
    is built from ``curve_map``; with neither, the carry/be columns are
    all-NaN (documented degraded mode — every harvest gate then refuses).
    The panel is UN-LAGGED: ``cvx_kink_harvest`` reads t-1 itself.
    """
    cfg = cfg or CvxPanelCfg()
    pairs = list(pairs)
    if not pairs:
        raise ValueError("build_harvest_panel: no pairs requested")
    parsed = [parse_pair(p) for p in pairs]
    legs_lc = sorted({leg_to_lc(l) for fb in parsed for l in fb})
    hist = _check_hist(leg_hist_bp, legs_lc, "build_harvest_panel")

    pair_lc = [f"{leg_to_lc(f)}/{leg_to_lc(b)}" for f, b in parsed]
    if len(set(pair_lc)) != len(pair_lc):
        raise ValueError(f"duplicate pairs after canonicalisation: {pair_lc}")
    lvl = pd.DataFrame(
        {plc: hist[leg_to_lc(b)] - hist[leg_to_lc(f)]
         for plc, (f, b) in zip(pair_lc, parsed)})
    z, mu = _roll_z(lvl, cfg.z_window, cfg.z_min_obs)
    hl = pd.DataFrame(
        {c: rolling_ar1(lvl[c], int(cfg.ou_window),
                        min_periods=int(cfg.ou_min_obs))["half_life"]
         for c in lvl.columns})
    # rev drag at h = HL: (1 - 2**(-h/HL)) == 0.5 exactly, defined only where
    # the AR(1) window mean-reverts (finite HL) — NaN refuses, never zero.
    drag = 0.5 * (mu - lvl).where(hl.notna())

    if leg_panel is None and curve_map is not None:
        leg_panel = build_leg_panel([], [l for fb in parsed for l in fb],
                                    curve_map=curve_map)
    if leg_panel is not None:
        screen = _screen_block(leg_panel, pair_lc, cfg)
    else:
        screen = None

    frames = {"level_bp": lvl, "zs": z, "half_life_d": hl, "rev_drag_bp": drag}
    long = {k: f.stack(future_stack=True) for k, f in frames.items()}
    out = pd.DataFrame(long)
    out.index.names = ["date", "pair"]
    out = out.sort_index()

    if screen is not None:
        sc = screen.reindex(out.index)
        out["carry_flat_1y_bp"] = sc["carry_1y_bp"]
        out["be_daily_bp"] = sc["be_daily_analytic"]
        out["rlzd_vol_bp"] = sc["rlzd_vol_bp"]
        out["be_over_rv"] = sc["be_over_rv"]
    else:
        out["carry_flat_1y_bp"] = np.nan
        out["be_daily_bp"] = np.nan
        out["rlzd_vol_bp"] = np.nan
        out["be_over_rv"] = np.nan
    out["carry_lvl_1y_bp"] = -out["carry_flat_1y_bp"]
    out["rac_net"] = (out["carry_lvl_1y_bp"] * out["half_life_d"]
                      / float(cfg.business_days) + out["rev_drag_bp"])

    out = out[["level_bp", "zs", "half_life_d", "rev_drag_bp",
               "carry_flat_1y_bp", "carry_lvl_1y_bp", "be_daily_bp",
               "rlzd_vol_bp", "be_over_rv", "rac_net"]]
    out.attrs["pairs"] = tuple(pair_lc)
    out.attrs["z_window"] = int(cfg.z_window)
    out.attrs["leg_panel_dates"] = (
        int(leg_panel.index.get_level_values("date").nunique())
        if leg_panel is not None else 0)
    return out


# ---------------------------------------------------------------------------
# dislocation panel
# ---------------------------------------------------------------------------

def _analytic_efpt(z_abs: np.ndarray, kappa: np.ndarray, hl: np.ndarray,
                   cfg: CvxPanelCfg) -> np.ndarray:
    """Vector E[first passage to halfway] in days, memoised on rounded |z0|.

    ``expected_passage_time(-z, -z/2, kappa=1) / kappa`` (exact scaling
    identity).  |z0| > ``fpt_z_cap`` -> the deterministic-decay limit HL;
    |z0| ~ 0, non-finite z/kappa, or a failed series -> NaN.
    """
    out = np.full(z_abs.shape, np.nan)
    ok = np.isfinite(z_abs) & np.isfinite(kappa) & (kappa > 0) & (z_abs > 1e-9)
    capped = ok & (z_abs > float(cfg.fpt_z_cap))
    out[capped] = hl[capped]
    core = ok & ~capped
    if core.any():
        zr = np.round(z_abs[core], int(cfg.fpt_z_round))
        memo: Dict[float, float] = {}
        tau1 = np.empty(zr.shape)
        for i, zv in enumerate(zr):
            t = memo.get(zv)
            if t is None:
                t = expected_passage_time(-zv, -zv / 2.0, kappa=1.0)
                memo[zv] = t
            tau1[i] = t
        out[core] = tau1 / kappa[core]
    return out


def build_dislocation_panel(leg_hist_bp: pd.DataFrame, *,
                            cfg: Optional[CvxPanelCfg] = None,
                            ca_bp: Optional[pd.DataFrame] = None,
                            ) -> pd.DataFrame:
    """The fly-dislocation signal panel, ``(date, point)`` (names exactly
    that), over the 15 INTERIOR points of ``grids.KINK_GRID``.

    All conventions — the binding zs polarity (zs > 0 = fly level HIGH =
    belly CHEAP = the fade RECEIVES the belly, including the strategy-layer
    direction seam note), the rate-space fly weights (-0.5, +1, -0.5), the
    analytic FPT route and its measured validity, the ING strip-interpolation
    carry APPROXIMATION (panel-only; the as-of screen keeps the repriced
    number) and the edge formula — are specified in the module docstring
    ("Dislocation conventions"); this docstring does not repeat them.

    ``ca_bp``: optional date x label convexity-adjustment frame (bp, positive
    = quoted forward depressed).  When given, ONE level definition feeds the
    whole panel: residuals, the fly level, the OU block and the carry strip
    all run on ``quoted + CA`` (``residuals.adjusted_levels``).  Default None
    = RAW quoted levels (stated approximation).

    Columns: ``res_x, res_pca, sign_agree, fly_bp, zs, ou_mu_bp,
    half_life_d, e_fpt_d, p_hit_proxy, e_rev_bp, carry_bp_day, edge_bp, tag,
    leg_front, leg_belly, leg_back, w_front, w_belly, w_back``.
    """
    cfg = cfg or CvxPanelCfg()
    points = list(grids.KINK_GRID)
    labels = [grids.leg_label(p) for p in points]
    ks = np.asarray([grids.k_coord(p) for p in points], dtype=float)
    hist = _check_hist(leg_hist_bp, labels, "build_dislocation_panel")
    if ca_bp is not None:
        hist = adjusted_levels(hist, ca_bp)

    # residual panels on the full 17-point cross-section
    res_x = xsec_residuals(hist, list(ks), cfg.xsec_variant, knots=cfg.xsec_knots)
    res_p, pca_info = walk_forward_pca_residuals(
        hist, n_pcs=int(cfg.n_pcs), window=int(cfg.pca_window),
        min_window=int(cfg.pca_min_window), refit=cfg.pca_refit)
    agree = sign_agreement(res_x, res_p, min_abs_bp=float(cfg.sign_min_abs_bp))

    interior = list(range(1, len(labels) - 1))
    bellies = [labels[i] for i in interior]

    # fly level L = 2*belly - front - back, rate space — the belly=+2 ruler
    # (DESIGN §6a item 1: one fly ruler suite-wide)
    fly = pd.DataFrame(
        {labels[i]: 2.0 * hist[labels[i]]
         - hist[labels[i - 1]] - hist[labels[i + 1]]
         for i in interior})
    z, _mu_roll = _roll_z(fly, cfg.z_window, cfg.z_min_obs)

    # OU block per point (vectorised rolling AR(1) — the calibrate_ou fit)
    ou = {c: rolling_ar1(fly[c], int(cfg.ou_window),
                         min_periods=int(cfg.ou_min_obs)) for c in fly.columns}
    mu = pd.DataFrame({c: ou[c]["mu"] for c in fly.columns})
    kap = pd.DataFrame({c: ou[c]["kappa"] for c in fly.columns})
    hl = pd.DataFrame({c: ou[c]["half_life"] for c in fly.columns})
    seq = pd.DataFrame({c: ou[c]["sigma_eq"] for c in fly.columns})

    gap = fly - mu
    e_rev = 0.5 * gap.abs()                      # (1 - 2**(-h/HL)) at h = HL
    z0_abs = (gap.abs() / seq.where(seq > 0)).to_numpy(dtype=float)
    efpt = pd.DataFrame(
        _analytic_efpt(z0_abs, kap.to_numpy(dtype=float),
                       hl.to_numpy(dtype=float), cfg),
        index=fly.index, columns=fly.columns)
    # P(hit <= h) at the frozen book's own clock h = max_hold_bd (§6a item 2)
    with np.errstate(over="ignore"):
        p_hit = 1.0 - np.exp(-float(cfg.max_hold_bd) / efpt.where(efpt > 0))

    # ING strip-interpolation carry: leg 1y roll-down = f(k) - f_interp(k-1);
    # level-long carry composes with MINUS sign (module docstring).
    F = hist[labels].to_numpy(dtype=float)
    roll1y = np.full(F.shape, np.nan)
    for r in range(F.shape[0]):
        row = F[r]
        if np.isnan(row).any():
            continue
        back1 = np.interp(ks - 1.0, ks, row)
        roll1y[r] = row - back1
    roll1y[:, 0] = np.nan                        # spot 1y: no k-1 on the strip
    roll_df = pd.DataFrame(roll1y, index=hist.index, columns=labels)
    carry = pd.DataFrame(
        {labels[i]: -(2.0 * roll_df[labels[i]]
                      - roll_df[labels[i - 1]] - roll_df[labels[i + 1]])
         / float(cfg.business_days)
         for i in interior})

    # THE SHARED EDGE FORMULA (§6a item 2, h = max_hold_bd = 63): reversion
    # credited at P(hit <= h), carry charged over min(E[FPT], h) only —
    # e_fpt itself stays uncapped as its own column (clip preserves NaN).
    edge = (e_rev * p_hit
            - carry.abs() * efpt.clip(upper=float(cfg.max_hold_bd))
            - float(cfg.cost_rt_bp))

    frames = {
        "res_x": res_x[bellies], "res_pca": res_p[bellies],
        "sign_agree": agree[bellies], "fly_bp": fly, "zs": z,
        "ou_mu_bp": mu, "half_life_d": hl, "e_fpt_d": efpt,
        "p_hit_proxy": p_hit, "e_rev_bp": e_rev, "carry_bp_day": carry,
        "edge_bp": edge,
    }
    out = pd.DataFrame({k: f.stack(future_stack=True) for k, f in frames.items()})
    out.index.names = ["date", "point"]
    out = out.sort_index()

    tag_of = {labels[i]: grids.classify_point(points[i]) for i in interior}
    legf = {labels[i]: labels[i - 1] for i in interior}
    legb = {labels[i]: labels[i + 1] for i in interior}
    pt = out.index.get_level_values("point")
    out["tag"] = pt.map(tag_of)
    out["leg_front"] = pt.map(legf)
    out["leg_belly"] = pt
    out["leg_back"] = pt.map(legb)
    # DOLLAR leg weights (per-leg DV01 fractions of the strategy's package
    # dv01) — NOT the rate-space (-1, +2, -1) that defines L (module
    # docstring: the package pays dv01/2 USD per bp of the belly=+2 L).
    out["w_front"] = -0.5
    out["w_belly"] = 1.0
    out["w_back"] = -0.5

    info_keys = sorted(pca_info)
    out.attrs["pca_n_refits"] = len(info_keys)
    out.attrs["pca_last_refit"] = (str(info_keys[-1].date()) if info_keys else None)
    out.attrs["levels"] = "adjusted" if ca_bp is not None else "raw"
    out.attrs["ruler"] = "belly=+2: L = 2b - f - k (DESIGN 6a item 1)"
    out.attrs["edge_horizon_bd"] = int(cfg.max_hold_bd)
    out.attrs["cost_rt_bp"] = float(cfg.cost_rt_bp)
    out.attrs["polarity"] = ("zs>0 = fly level high = belly cheap; the fade "
                             "of zs>0 is the RECEIVE-belly side")
    return out
