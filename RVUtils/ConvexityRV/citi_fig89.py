"""Citi *US Rates Vol Lab* (17-Jan-2017) Figures 8 and 9, reproduced on SOFR.

The two charts, verbatim from the note (``print (6).pdf.md`` lines 261-263):

    Figure 8. 3y1y implied vol is highly directional with the 2s5s10s fly...
    Figure 9. ... implying that convexity can be hedged with the fly

    180 normals 3y1y implied vol                20 bp Blues Cvx Adj
    scaled 2s5s10s fly:                         scaled 2s5s10s fly:
      59.7+60.5*(-0.71*2y+5y-0.18*10y)            10.2+21.4*(-0.73*2y+5y-0.47*10y)

and the claim they exist to support (p.5, lines 255-260):

    "3y1y vol is mostly driven by expectations of monetary policy, and therefore
     should be directional with the valuations of 5s on the curve. Indeed, the
     3y1y vol has been historically highly correlated with the 2s5s10s fly with
     DV01 weights shown in Figure 8 (**the correlation in levels being 90%**).
     ... we regressed Blues CA on 2y, 5y and 10y swap rates. ... the fitted value
     effectively being a 2s5s10s fly with -0.73/1/-0.47 DV01 weights (Figure 9)."


WHAT THE ANNOTATION MEANS, EXACTLY
==================================
Read ``y_fitted = alpha + beta * fly`` with

    fly = (-w2 * r2y + r5y - w10 * r10y)          rates in PERCENT

so ``fly`` is a DV01-weighted butterfly with the belly normalised to 1, and
``beta`` carries the units of the left-hand series per percent of fly (bp of
normal vol for Fig 8, bp of convexity adjustment for Fig 9). ``w2``/``w10`` are
DV01 weights, always quoted positive in the note and subtracted in the
expression.

**The two figures use DIFFERENT weights** (0.71/0.18 vs 0.73/0.47) because each
is fitted to its own left-hand series. They are not two views of one butterfly.

**Citi re-estimates at every publication.** Three weeks after Fig 9 the same
regression printed ``9.7+20.6*(-0.705*2y+5y-0.465*10y)`` ([TI-FEB9] Fig 6). So
:func:`refit` is the method and the printed constants are one sample of it;
both are produced here and the gap between them is a result, not an error.


THE ONE SELF-CONTAINED KNOWN-ANSWER CHECK
=========================================
[TI-FEB9] prints every term of its own line on its own entry date, so the
published alpha/beta can be verified with no market data at all:

    entry CA (Blues)                      8.8 bp
    entry fly level                     -18.2 bp   = -0.182 %
    published line               9.7 + 20.6 * fly
    => fitted                            5.951 bp
    => CA - fitted                       2.849 bp
    note text: "The CA is about 3bp (about 2 sigmas) wide to the fly"   OK

:data:`TI_FEB9_TIEOUT` carries those numbers and
:func:`ti_feb9_dislocation_bp` computes the 2.849.

**What that check does and does not pin**, measured rather than assumed (the
sensitivities are exact, since ``gap = CA - alpha - beta*fly`` is linear):

===================  ==========================  ==================================
term                 d(gap)/d(term) at fly=-.182 verdict against the 0.5bp band
===================  ==========================  ==================================
``alpha``            -1.0                        **tight** -- 1bp of alpha breaks it
``beta``             +0.182                      **loose** -- needs beta wrong by 2.75 (13%)
units (%, not bp)    --                          **hard** -- bp fly gives 3.7e2 bp of gap
===================  ==========================  ==================================

So it validates the *line at the traded fly level*, the intercept and above all
the percent-vs-bp convention; it is not an independent validation of ``beta`` to
better than ~13%. Stated because a known-answer test that would also pass under
a wrong implementation is worse than none.

The 13-Jan version is consistent with it but not self-contained: Blues CA was
9.96bp ([VL-JAN17] Fig 48) and the text says "about 4bp ... wide to the fly", so
the fly stood at about ``(9.96 - 4 - 10.2) / 21.4 = -0.198 %`` = -19.8bp, which
is 1.6bp from the -18.2bp printed three weeks later. Reported, not asserted.


THE ED -> SOFR MAPPING
======================
The 2017 note is Eurodollar-era: "Blues" there is the 4th ED pack, contracts
13-16 out the strip (on 1/12/17, H0-Z0). Here it is the **SOFR rank-13 pack
window** -- contracts 13..16 of the quarterly SR3 strip, first expiry ~3.25y --
which is the same position on the curve and the same object
``RVUtils.ConvexityRV.strat2_q20`` builds. Colour ladder used throughout:
Whites 1, Reds 5, Greens 9, **Blues 13**, Golds 17.


DATA PATHS -- WHAT THIS MODULE READS AND WHY
============================================
``load_rate_panel``
    2Y/5Y/10Y par swap rates off ``USD-SOFR-1D`` (``IRSwapsMDP(source=
    "CITIVELO_EXCEL")``) through ``TimeseriesBuilder`` + ``IRSwapsTB``.

    **``freq="nyc_eod"`` returns an EMPTY frame on this source** -- measured:
    "CITIVELO_EXCEL: no curve for 12 of 12 requested point(s) on 'USD-SOFR-1D'"
    for 2021-01-04..2021-01-20, because that alias builds tz-stamped 17:00
    reference points and the local CITIVELO store is keyed by plain date. The
    default (``freq=None`` -> ``pd.bdate_range``) resolves every date. Measured
    cost of the whole 2021-2026 pull: ~15 s, and it reproduces the independently
    built ``strat2_q20_rates.parquet`` to 4.4e-14 %.

``load_vol_3y1y``
    ATMF NORMAL vol in bp from the Citi Velocity swaption cube store, via
    ``swaption_cube.load_vol_panel`` / ``atmf_vol_series``.

    **Not ``IRSwaptionsTB``, and the reason is measured.** That router prices a
    QuantLib cube per date at ~1.33 s/value (``scripts/citivelo_swaption_ts_warm
    .py``, ``MEASURED_SECONDS_PER_VALUE``); its warmed grid is 3Mx10Y / 1Yx10Y /
    5Yx5Y, so **3Yx1Y is not in it**, and an unwarmed date falls through to the
    Citi Velocity Excel add-in over COM -- which is a network/Excel round trip.
    A 5-date probe at 3Yx1Y ATMF NVOL did not return inside 120 s. The cube
    store is the *same Citi Velocity data* the router would build from, read
    straight off local parquet: 1,404 dates over 2021-01-04..2026-08-14.

``load_ca_panel``
    The Blues/Greens/Golds convexity adjustment and its Ho-Lee model, from
    ``notebooks/data/convexity_rv/strat2_q20_panel.parquet`` (built offline by
    ``scripts/strat2_q20_build.py``) gated with ``strat2_q20.apply_gate`` and
    fitted with ``strat2_sofr_convexity.model_timeseries``. Gate first, then
    fit: the sigma model is a **cross-sectional** least squares over the day's
    ranked packs, so one inadmissible row contaminates every model value for
    that date, not just its own.

    Two documented deviations from Citi live in that panel and neither is
    fixable from local data:

    * the model sigma is fitted to the day's own CA term structure, not
      calibrated to cap/floor vols as Citi states. ``vs_model_bp`` is therefore
      a *cross-sectional* dislocation (this pack against the smooth curve
      through all of them), not a vol-market one.
    * the matched swap is ``USD-SOFR-1D``, not CME-cleared. The measured gap on
      2023-06-09 was about -3.9bp of CA level. ``ca_basis_bp`` is left at 0.0,
      so every CA here is ~3.9bp below the CME-basis number Citi prints. It
      shifts ``alpha`` and cancels out of ``beta``, the weights and every
      correlation.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "RATE_TENORS",
    "COLOUR_RANK",
    "FlyScaling",
    "FlyFit",
    "CITI_FIG8",
    "CITI_FIG9",
    "CITI_TI_FEB9",
    "TI_FEB9_TIEOUT",
    "ti_feb9_dislocation_bp",
    "fly_level",
    "scaled_fly",
    "refit",
    "corr_table",
    "rolling_corr",
    "dislocation_stats",
    "load_rate_panel",
    "load_vol_3y1y",
    "load_ca_panel",
    "colour_frame",
    "regression_table",
]

#: Column order used everywhere. ``fly_level`` indexes by these names, so a
#: panel must carry them exactly (``load_rate_panel`` names its queries so).
RATE_TENORS: Tuple[str, str, str] = ("2Y", "5Y", "10Y")

#: SOFR pack-window rank -> Citi colour. Rank is the 1-indexed position of the
#: FIRST contract of the four, so Blues = contracts 13..16, first expiry ~3.25y.
COLOUR_RANK: Dict[str, int] = {"Whites": 1, "Reds": 5, "Greens": 9,
                               "Blues": 13, "Golds": 17}


# ===========================================================================
# The scaled fly
# ===========================================================================
@dataclasses.dataclass(frozen=True)
class FlyScaling:
    """One ``alpha + beta * (-w2*2y + 5y - w10*10y)`` line.

    ``w2``/``w10`` are DV01 weights quoted POSITIVE, exactly as the note quotes
    them, and subtracted inside :meth:`fly`. ``beta`` is in units of the
    left-hand series per **percent** of fly; the note's rates are in percent and
    every published constant here inherits that.
    """

    w2: float
    w10: float
    alpha: float
    beta: float
    label: str = ""

    def fly(self, rates: pd.DataFrame) -> pd.Series:
        """The unscaled DV01-weighted fly, in percent."""
        return fly_level(rates, self.w2, self.w10)

    def scaled(self, rates: pd.DataFrame) -> pd.Series:
        """``alpha + beta * fly`` -- the series the chart plots against."""
        return self.alpha + self.beta * self.fly(rates)

    def annotation(self) -> str:
        """The chart annotation string, in Citi's own format."""
        return (f"{self.alpha:g}+{self.beta:g}*"
                f"(-{self.w2:g}*2y+5y-{self.w10:g}*10y)")

    def as_row(self) -> Dict[str, Any]:
        return {"source": self.label, "w2": self.w2, "w10": self.w10,
                "alpha": self.alpha, "beta": self.beta,
                "r_squared": np.nan, "n": np.nan}


@dataclasses.dataclass(frozen=True)
class FlyFit(FlyScaling):
    """A :class:`FlyScaling` recovered by OLS, with its fit statistics.

    The regression is run in its natural, unconstrained form::

        y = a + b2*r2 + b5*r5 + b10*r10

    and then rewritten as the note writes it::

        alpha = a          beta = b5
        w2    = -b2 / b5   w10  = -b10 / b5

    which is an identity, not an approximation:
    ``a + b5*(-(-b2/b5)*r2 + r5 - (-b10/b5)*r10) == a + b2*r2 + b5*r5 + b10*r10``.

    Two failure modes are *reported* rather than repaired, because both are
    findings about the relationship:

    ``beta`` near zero
        the belly carries no explanatory weight and ``w2 = -b2/beta`` explodes.
        (``strat2_sofr_convexity.Strat2Config.hedge_min_abs_beta`` refuses to
        trade such an epoch for the same reason.)
    a weight coming out NEGATIVE
        ``-w2*r2`` with ``w2 < 0`` is a same-sign wing, which cannot be
        expressed as a butterfly at all.
    """

    b2: float = np.nan
    b5: float = np.nan
    b10: float = np.nan
    r_squared: float = np.nan
    n: int = 0
    resid_sd: float = np.nan

    def as_row(self) -> Dict[str, Any]:
        return {"source": self.label, "w2": self.w2, "w10": self.w10,
                "alpha": self.alpha, "beta": self.beta,
                "r_squared": self.r_squared, "n": int(self.n)}


#: [VL-JAN17] Fig 8, p.5 / [W-JAN13] Fig 21, p.13 -- 3y1y implied vol, close
#: 13-Jan-2017. Identical strings in both publications.
CITI_FIG8 = FlyScaling(w2=0.71, w10=0.18, alpha=59.7, beta=60.5,
                       label="Citi Fig 8 published (13-Jan-2017)")

#: [VL-JAN17] Fig 9, p.5 / [W-JAN13] Fig 22, p.13 -- Blues convexity adjustment.
CITI_FIG9 = FlyScaling(w2=0.73, w10=0.47, alpha=10.2, beta=21.4,
                       label="Citi Fig 9 published (13-Jan-2017)")

#: [TI-FEB9] Fig 6, p.3 -- the SAME regression three weeks later. Kept because
#: the drift 0.73/0.47/21.4 -> 0.705/0.465/20.6 in 27 days is the note's own
#: evidence that the constants are a snapshot of a procedure.
CITI_TI_FEB9 = FlyScaling(w2=0.705, w10=0.465, alpha=9.7, beta=20.6,
                          label="Citi TI Fig 6 published (9-Feb-2017)")

#: Every term of [TI-FEB9]'s own entry, as printed. See the module docstring.
TI_FEB9_TIEOUT: Dict[str, float] = {
    "ca_entry_bp": 8.8,          # "pay $2bn on a matched-maturity CME swap at 8.8bp of spread"
    "fly_entry_bp": -18.2,       # "at -18.2bp in terms of the level of the DV01-weighted fly"
    "stated_gap_bp": 3.0,        # "The CA is about 3bp (about 2 sigmas) wide to the fly"
    "stated_gap_tol_bp": 0.5,    # "about", so half a bp either side
}


def ti_feb9_dislocation_bp(spec: FlyScaling = CITI_TI_FEB9,
                           tieout: Mapping[str, float] = TI_FEB9_TIEOUT) -> float:
    """``CA - (alpha + beta*fly)`` from [TI-FEB9]'s OWN printed numbers.

    No market data. This is the check that the published alpha/beta really do
    describe Citi's fitted line: feed the note its own fly level and it returns
    its own stated 3bp of richness.
    """
    fly_pct = float(tieout["fly_entry_bp"]) / 100.0
    fitted = spec.alpha + spec.beta * fly_pct
    return float(tieout["ca_entry_bp"]) - fitted


def fly_level(rates: pd.DataFrame, w2: float, w10: float) -> pd.Series:
    """``-w2*r2y + r5y - w10*r10y`` in percent, from a ``date x tenor`` panel.

    Deliberately NOT built with ``IRSwapQuery(structure=FLY)``: the note
    specifies an explicit weighted combination of three par rates, which is
    exactly this expression, and ``IRSwapStructure._build_fly`` both hard-codes
    a ``-1/2/-1`` shape and MUTATES the ``risk_weights`` list it is handed.
    """
    missing = [t for t in RATE_TENORS if t not in rates.columns]
    if missing:
        raise KeyError(f"rate panel is missing {missing}; has {list(rates.columns)}")
    r2, r5, r10 = (pd.to_numeric(rates[t], errors="coerce") for t in RATE_TENORS)
    out = -float(w2) * r2 + r5 - float(w10) * r10
    out.name = f"fly(-{w2:g}/1/-{w10:g})"
    return out


def scaled_fly(rates: pd.DataFrame, spec: FlyScaling) -> pd.Series:
    """``alpha + beta * fly``, named for the chart legend."""
    out = spec.scaled(rates)
    out.name = f"scaled 2s5s10s fly: {spec.annotation()}"
    return out


def refit(y: pd.Series, rates: pd.DataFrame, *, label: str = "refit") -> FlyFit:
    """OLS ``y ~ 1 + r2 + r5 + r10`` on the overlapping dates, as a fly.

    Aligns on the intersection of the two indices and drops non-finite rows;
    ``n`` is what actually entered the regression, never what was requested.
    """
    idx = y.index.intersection(rates.index)
    yy = pd.to_numeric(y.reindex(idx), errors="coerce")
    xx = rates.reindex(idx)[list(RATE_TENORS)].apply(pd.to_numeric, errors="coerce")
    ok = yy.notna() & xx.notna().all(axis=1)
    n = int(ok.sum())
    if n < 4:
        return FlyFit(w2=np.nan, w10=np.nan, alpha=np.nan, beta=np.nan,
                      label=label, n=n)

    yv = yy[ok].to_numpy(float)
    xv = xx[ok].to_numpy(float)
    design = np.column_stack([np.ones(n), xv])
    coeffs, *_ = np.linalg.lstsq(design, yv, rcond=None)
    a, b2, b5, b10 = (float(c) for c in coeffs)

    resid = yv - design @ coeffs
    ss_res = float(resid @ resid)
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2_score = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    dof = max(n - 4, 1)

    return FlyFit(
        w2=(-b2 / b5) if b5 != 0 else np.nan,
        w10=(-b10 / b5) if b5 != 0 else np.nan,
        alpha=a,
        beta=b5,
        label=label,
        b2=b2, b5=b5, b10=b10,
        r_squared=r2_score,
        n=n,
        resid_sd=float(np.sqrt(ss_res / dof)),
    )


def corr_table(y: pd.Series, x: pd.Series, *, name: str = "") -> Dict[str, Any]:
    """Correlation of *y* and *x* in LEVELS and in DAILY CHANGES, with n.

    Both are reported because they answer different questions and Citi only
    quotes the first. A levels correlation can be 0.9 on two series that share a
    trend and nothing else; the changes correlation is what a hedge actually
    lives on day to day.

    Changes are ``.diff()`` on the ALIGNED, common index, so a gap in either
    series produces one NaN difference rather than a spurious jump across it.
    """
    idx = y.index.intersection(x.index)
    yy = pd.to_numeric(y.reindex(idx), errors="coerce")
    xx = pd.to_numeric(x.reindex(idx), errors="coerce")
    ok = yy.notna() & xx.notna()
    lv = float(yy[ok].corr(xx[ok])) if ok.sum() >= 3 else np.nan

    dy, dx = yy.diff(), xx.diff()
    okd = dy.notna() & dx.notna()
    ch = float(dy[okd].corr(dx[okd])) if okd.sum() >= 3 else np.nan

    return {"series": name, "corr_levels": lv, "n_levels": int(ok.sum()),
            "corr_changes": ch, "n_changes": int(okd.sum())}


def rolling_corr(y: pd.Series, x: pd.Series, *, window: int = 126,
                 min_periods: Optional[int] = None) -> pd.Series:
    """Rolling levels correlation on the common index. 126 bdays ~ 6 months.

    Exists so a relationship that DECAYS is visible instead of being averaged
    into a single flattering full-sample number.
    """
    idx = y.index.intersection(x.index)
    yy = pd.to_numeric(y.reindex(idx), errors="coerce")
    xx = pd.to_numeric(x.reindex(idx), errors="coerce")
    mp = int(min_periods if min_periods is not None else max(window // 2, 10))
    return yy.rolling(int(window), min_periods=mp).corr(xx)


def dislocation_stats(d: pd.Series, *, name: str = "") -> Dict[str, Any]:
    """Distribution of a dislocation series, plus how often it changes sign.

    ``sign_changes`` counts consecutive observations whose (non-zero) signs
    differ -- for ``CA - model`` that is the number of times the trade would
    have flipped from "sell convexity" to "buy convexity" over the sample, and
    it is the honest way to say whether a mean dislocation is a level or a
    coin flip.
    """
    s = pd.to_numeric(d, errors="coerce").dropna()
    if s.empty:
        return {"series": name, "n": 0}
    sg = np.sign(s.to_numpy(float))
    nz = sg[sg != 0]
    flips = int((nz[1:] != nz[:-1]).sum()) if nz.size > 1 else 0
    return {
        "series": name,
        "n": int(s.size),
        "mean": float(s.mean()),
        "sd": float(s.std(ddof=1)) if s.size > 1 else np.nan,
        "min": float(s.min()),
        "p05": float(s.quantile(0.05)),
        "median": float(s.median()),
        "p95": float(s.quantile(0.95)),
        "max": float(s.max()),
        "pct_positive": float((s > 0).mean() * 100.0),
        "sign_changes": flips,
        "sign_changes_per_year": (float(flips) / (s.size / 252.0)) if s.size else np.nan,
    }


# ===========================================================================
# Data
# ===========================================================================
def load_rate_panel(
    start: datetime.date,
    end: datetime.date,
    *,
    curve: str = "USD-SOFR-1D",
    source: str = "CITIVELO_EXCEL",
    tenors: Sequence[str] = RATE_TENORS,
    n_jobs: int = 12,
    show_tqdm: bool = False,
    curve_mdp: Any = None,
    ts_builder: Any = None,
    cache_path: Optional[pathlib.Path] = None,
) -> pd.DataFrame:
    """``date x {2Y,5Y,10Y}`` par swap rates in PERCENT, via the TB pattern.

    The house call shape (``BT/signals/sfr_cal_spread_rv.py::load_rate_panel``)::

        ts.get_timeseries(start=..., end=..., queries=[UnifiedQuery(...), ...],
                          n_jobs=12, routers={"IRS": IRSwapsTB(curve_mdp)},
                          ignore_cache_miss=True)

    with one deviation, measured rather than assumed: **``freq`` is left unset**.
    ``freq="nyc_eod"`` builds tz-aware 17:00 New York reference points, and the
    local ``CITIVELO_EXCEL`` store is keyed by plain date -- it returns an empty
    frame and logs "no curve for 12 of 12 requested point(s)". The default path
    is ``pd.bdate_range(start, end)``, which resolves.

    Each query is ``name=``d so the columns come back as "2Y"/"5Y"/"10Y" rather
    than generated ``col_name()`` strings -- :func:`fly_level` indexes by those
    names.
    """
    if cache_path is not None and pathlib.Path(cache_path).exists():
        out = pd.read_parquet(cache_path)
        out.index = pd.to_datetime(out.index)
        return out.sort_index()

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    curve_mdp = curve_mdp or IRSwapsMDP(source=source)
    ts_builder = ts_builder or TimeseriesBuilder()

    queries = [UnifiedQuery(curve=curve, tenor=str(t), value=UnifiedValue.IRS_RATE,
                            name=str(t)) for t in tenors]
    panel = ts_builder.get_timeseries(
        start=start, end=end, queries=queries, n_jobs=n_jobs,
        routers={"IRS": IRSwapsTB(curve_mdp, show_tqdm=show_tqdm)},
        ignore_cache_miss=True,
    )
    if panel is None or panel.empty:
        raise RuntimeError(
            f"empty rate panel for {curve}/{source} over {start}..{end} -- "
            "check the local curve store before assuming this is a code fault")

    panel = panel[[c for c in tenors if c in panel.columns]].copy()
    panel.index = pd.to_datetime(panel.index)
    panel.index.name = "date"
    for c in panel.columns:
        panel[c] = pd.to_numeric(panel[c], errors="coerce")
    panel = panel.dropna(how="all").sort_index()

    if cache_path is not None:
        pathlib.Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(cache_path)
    return panel


def load_vol_3y1y(
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    *,
    expiry: str = "3Y",
    tenor: str = "1Y",
    cache_path: Optional[pathlib.Path] = None,
) -> pd.Series:
    """Daily ATMF NORMAL vol in bp for one swaption node, off the cube store.

    ATMF is ``offset_bp == 0``; the store's ``skew_measure`` is NORMALABSOLUTE
    and ``vol_bp`` is already normal vol in bp, the unit Citi's "normals" axis
    uses. See the module docstring for why this is not ``IRSwaptionsTB``.
    """
    from RVUtils.ConvexityRV.swaption_cube import atmf_vol_series, load_vol_panel

    panel = load_vol_panel([(expiry, tenor)], start=start, end=end,
                           cache_path=cache_path)
    s = atmf_vol_series(panel, expiry, tenor)
    s.index = pd.to_datetime(s.index)
    s.name = f"{expiry}x{tenor} ATMF normal vol (bp)"
    return s.sort_index()


def load_ca_panel(
    panel_path: pathlib.Path,
    *,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    rank_start: int = 5,
    n_packs: int = 13,
    gated: bool = True,
    ca_col: str = "ca_bp_q20",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """The gated deep-pack CA panel and its Ho-Lee model fit.

    Returns ``(gated_panel, fit)`` where ``fit`` is the long frame
    ``model_timeseries`` produces -- one row per (date, pack) over the ranked
    window, carrying ``ca_bp``, ``ca_model_bp``, ``vs_model_bp``,
    ``sigma_model_bp`` and the rank/colour.

    ``rank_start=5, n_packs=13`` is **exactly Citi's published SOFR screen**
    (windows 5..17, Reds M4-H5 through Golds M7-H8). Dates whose strip is
    shallower simply contribute fewer rows to that day's cross-section; they are
    not dropped, and the polynomial variance fit needs only ``degree+1 = 3`` of
    them.

    **Gate BEFORE fit.** ``fit_sigma_model`` is a least squares across the day's
    ranked packs, so an inadmissible row moves the model value of every other
    pack that day. Filtering afterwards would leave contaminated model numbers
    on rows that passed.
    """
    from RVUtils.ConvexityRV.strat2_q20 import apply_gate, deep_pack_config
    from RVUtils.ConvexityRV.strat2_sofr_convexity import model_timeseries

    panel = pd.read_parquet(panel_path)
    panel["date"] = pd.to_datetime(panel["date"])
    if start is not None:
        panel = panel[panel["date"] >= pd.Timestamp(start)]
    if end is not None:
        panel = panel[panel["date"] <= pd.Timestamp(end)]
    panel = panel.copy()

    if gated:
        panel = apply_gate(panel)
    if ca_col != "ca_bp":
        if ca_col not in panel.columns:
            raise KeyError(f"{ca_col} not in panel; has {list(panel.columns)}")
        panel["ca_bp"] = panel[ca_col]

    cfg = deep_pack_config(rank_start=int(rank_start), n_packs=int(n_packs))
    model = model_timeseries(panel, cfg)
    return panel, model["fit"]


def colour_frame(fit: pd.DataFrame, colour: str,
                 cols: Sequence[str] = ("ca_bp", "ca_model_bp", "vs_model_bp",
                                        "sigma_model_bp", "pack")) -> pd.DataFrame:
    """One pack colour's rows out of the long fit frame, indexed by date.

    Selects on RANK, not on the ``colour`` column: the panel labels a colour
    only where the rank lands on one, which is the same thing, but rank is the
    definition and the label is derived from it.
    """
    rank = COLOUR_RANK[str(colour)]
    sub = fit[fit["rank"] == rank].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    keep = [c for c in cols if c in sub.columns]
    out = sub.set_index("date")[keep].sort_index()
    return out[~out.index.duplicated(keep="last")]


def regression_table(rows: Sequence[FlyScaling]) -> pd.DataFrame:
    """Published-vs-refitted comparison table, one row per :class:`FlyScaling`."""
    return pd.DataFrame([r.as_row() for r in rows])[
        ["source", "w2", "w10", "alpha", "beta", "r_squared", "n"]]
