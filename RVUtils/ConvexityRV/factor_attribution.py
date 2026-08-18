"""One factor basis for every convexity strategy.

Why this module exists
----------------------

"How directional is it?" had been answered three different ways across the three
strategies, and the three answers are not comparable::

    strat 1 long-end   R^2 = 0.80-0.83 of gross P&L on a *gated curve move*
    strat 3            mtm share of net = 1.29, >= 0.88 for every one of 15 pairs
    strat 2            a gamma dollar figure, -$1,057,841 on rank 5

An R-squared, a ratio of accounting buckets, and a dollar greek. Ranking three
strategies on those is meaningless. This module puts all of them on ONE basis:

* a **daily PCA of the USD-SOFR par curve**, fitted once on the full window, on
  daily changes in bp -- so PC1/PC2/PC3 are the same objects for every strategy;
* a **convexity regressor that is quadratic, not linear**, in those factors, so
  a long-gamma position has somewhere to load that a directional one does not;
* a **carry regressor**, so the theta a structure pays or earns is not swept
  into the residual and mistaken for alpha.

Every strategy's P&L is then regressed on the same five columns, and the shares
of realised P&L are read off the same way.


The three measurement decisions that matter
-------------------------------------------

**1. Factor realisations are NOT the PCA's demeaned scores.**

``fit_curve_pca_from_timeseries`` demeans before projecting (``X_std = X - mean``),
which is correct for fitting the covariance and wrong for attribution. Over
2019-2026 the sample mean daily change is positive at every tenor -- the level
drifted up by hundreds of bp -- and a demeaned score throws that drift away.
Attributing a 1-year trade with demeaned scores books the entire directional
drift to the intercept and reports it as *alpha*. So the loadings ``V`` come
from the demeaned fit (standard PCA) and the factor series is built raw::

    F_t = dR_t @ V          (dR_t in bp, V orthonormal, no demeaning)

This is the single decision most likely to flip a "how directional is it"
answer, which is why it is stated first.

**2. The convexity regressor is the squared move over the accounting interval.**

A long-gamma position earns in ``|move|^2``. Which move, and over what window,
is not free:

* an **unhedged buy-and-hold** package (strat 1's 1-year cohorts) has a
  terminal-value payoff, so its second-order term is the SQUARED TERMINAL MOVE,
  ``(R_T - R_0)^2``;
* the **daily mark** of that same package earns ``(dR_t)^2`` each day;
* a **delta-hedged** book (strat 3 rebalances every 25bp) earns REALISED
  VARIANCE, ``sum_t (dR_t)^2``.

The unifying rule, and the one this module implements: *the convexity regressor
is the squared move of the level over exactly the interval the P&L is measured
over.* Daily P&L gets ``(dR_t)^2``; a trade-level P&L gets ``(R_exit-R_entry)^2``.
``realised_variance`` is provided for the delta-hedged sensitivity run.

"The level" here is the **parallel-equivalent shift**: the cross-sectional mean
of the rate change over the tenor grid, in bp. Not PC1 itself. The reason is a
tie-out: ``payoff_profile`` measures convexity by repricing the package on a
PARALLEL-shifted curve, so the gamma already on disk in ``strat1_signal_panel``
is a gamma with respect to exactly this quantity. That makes the fitted
coefficient checkable against an independently computed greek --
``beta_convexity`` should come out at ``0.5 * gamma`` -- rather than merely
plausible. (PC2's loadings sum to ~0, so the parallel component of a curve move
is ~PC1 alone; the module reports the correlation rather than asserting it.)

**3. Regressors are signed by the position's direction.**

A steepener is SHORT convexity. Regressing signed P&L on unsigned factor moves
would net a flattener's gamma against a steepener's, and report a long-gamma
book as flat. Every regressor -- including the squared one -- is multiplied by
the position's direction weight ``w_t``, which at the daily level is the net
number of live packages (long minus short), and at the trade level is the
cohort's own direction. A day with no position is dropped, not entered as a
zero-exposure observation.


How the shares are computed
---------------------------

OLS with an intercept makes the residuals sum to exactly zero, so realised P&L
decomposes without remainder::

    sum_t y_t  =  alpha * T  +  sum_k beta_k * sum_t x_k,t

The share attributed to factor ``k`` is ``beta_k * sum_t x_k,t / sum_t y_t``, and
"unexplained" is ``alpha * T / sum_t y_t``. This is a decomposition of the
DOLLARS actually earned, which is the question, and it is a different object
from the R^2 decomposition, which is a statement about variance. Both are
reported because they answer different things -- and they disagree loudly for
strategies whose P&L is a small residue of large offsetting flows.

That last case needs a guard rail. Strat 2 hedged nets +$16,537 out of legs that
swing by more than a million; dividing by a near-zero denominator produces
percentages in the thousands that mean nothing. Every row therefore carries
``denom_stability = |sum y| / sum_k |contribution_k|`` and a
``denom_unstable`` flag when that is below ``STABILITY_FLOOR``; a flagged row's
percentages must be read as the raw contributions next to them, never on their
own.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.df_based_pca_risk_model import CurvePCAModel, fit_curve_pca_from_timeseries

__all__ = [
    "FactorConfig",
    "FactorModel",
    "AttributionResult",
    "STABILITY_FLOOR",
    "FACTOR_ORDER",
    "build_rate_panel",
    "fit_factor_model",
    "classify_pcs",
    "interval_factors",
    "parallel_move",
    "convexity_from_parallel",
    "realised_variance",
    "attribute",
    "decisive_table",
    "package_pc_exposure",
    "dv01_neutral_ladder",
    "spot_ladder_for_leg",
    "annuity_dv01",
    "gamma_from_payoff_profile",
    "sizing_diagnosis",
    "StrategySeries",
    "daily_design",
    "trade_design",
    "BP_TO_USD",
    "STRAT1_STRUCTURES",
    "load_strat1_base",
    "load_strat1_longend",
    "load_strat2",
    "load_strat3",
    "load_all_strategies",
    "run_attribution",
    "exposure_tieout",
]

#: A row whose |sum P&L| is below this fraction of the gross factor
#: contributions has a denominator too small for percentages to mean anything.
STABILITY_FLOOR = 0.10

#: The regressor order the incremental-R^2 walk uses. Incremental R^2 is
#: order-dependent; this is the order the task specifies, stated so the reader
#: knows it is a choice and not a property of the data.
FACTOR_ORDER: Tuple[str, ...] = ("level", "slope", "curvature", "convexity", "carry")


# ===========================================================================
# Config
# ===========================================================================
@dataclass(frozen=True)
class FactorConfig:
    """Knobs for the factor basis. Defaults are the ones the report uses."""

    #: The curve every strategy in this package prices off.
    curve: str = "USD-SOFR-1D"
    #: Window. 2019-01-02 is the first day strat 1's cohorts can enter and the
    #: first day the SOFR curve carries a full 2Y..50Y grid locally.
    start: datetime.date = datetime.date(2019, 1, 2)
    end: datetime.date = datetime.date(2026, 8, 12)
    #: The PCA grid. Justified in the notebook: it spans every tenor any of the
    #: three strategies actually trades (strat 2 lives at 2Y-10Y, strat 1 and 3
    #: at 10Y-50Y), it is roughly log-spaced so no region is over-weighted by
    #: sheer count, and it INCLUDES 40Y/50Y because 30Y/50Y is a traded
    #: structure -- a grid that stops at 30Y cannot see its slope factor at all.
    tenors: Tuple[str, ...] = ("2Y", "3Y", "5Y", "7Y", "10Y", "15Y",
                               "20Y", "25Y", "30Y", "40Y", "50Y")
    #: Fetched and cached alongside, used only for grid-sensitivity checks.
    extra_tenors: Tuple[str, ...] = ("1Y",)
    #: Number of PCs carried into the attribution.
    n_pcs: int = 3
    #: 'cov' keeps the loadings in bp space so a DV01 ladder projects onto them
    #: directly (f = V^T r). A 'corr' fit would need per-tenor rescaling.
    matrix: str = "cov"
    #: Newey-West lag for daily regressions (one month of business days).
    hac_lag_daily: int = 21
    #: Newey-West lag for trade-level regressions. Strat 1's cohorts are entered
    #: monthly and held a year, so 12 consecutive observations overlap.
    hac_lag_trade: int = 12


# ===========================================================================
# 1. The rate panel
# ===========================================================================
def build_rate_panel(
    cfg: FactorConfig,
    *,
    mdp: Any = None,
    n_jobs: int = 8,
    show_tqdm: bool = False,
    tenors: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Daily par swap rates in **percent**, index=Date, columns=tenor labels.

    Goes through ``IRSwapsTB`` rather than repricing by hand so the values are
    the same par rates every other module in this package sees, and so the
    day-partitioned curve cache is shared.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    wanted = list(tenors) if tenors is not None else list(cfg.tenors) + list(cfg.extra_tenors)
    mdp = mdp or IRSwapsMDP(source="CITIVELO_EXCEL")
    ts = TimeseriesBuilder()
    queries = [IRSwapQuery(curve=cfg.curve, tenor=t, value=IRSwapValue.RATE) for t in wanted]
    raw = ts.get_timeseries(
        start=cfg.start, end=cfg.end, queries=queries, n_jobs=n_jobs,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=show_tqdm)},
    )
    # "USD-SOFR-1D 10Y OUTRIGHT RATE" -> "10Y"
    raw.columns = [str(c).split()[1] for c in raw.columns]
    out = raw.reindex(columns=[t for t in wanted if t in raw.columns])
    out.index = pd.to_datetime(out.index)
    out.index.name = "date"
    return out.sort_index()


# ===========================================================================
# 2. The factor model
# ===========================================================================
@dataclass
class FactorModel:
    """A fitted curve PCA plus the RAW (non-demeaned) factor realisations.

    ``scores`` is the attribution-grade series: ``dR @ V`` with no demeaning.
    ``scores_demeaned`` is what the PCA fit itself produces and is kept only so
    the difference can be shown rather than asserted.
    """

    model: CurvePCAModel
    tenors: List[str]
    rates_bp: pd.DataFrame          # levels, bp
    d_rates_bp: pd.DataFrame        # daily changes, bp
    scores: pd.DataFrame            # raw: dR @ V, bp
    scores_demeaned: pd.DataFrame   # (dR - mean) @ V, bp
    explained_variance: pd.Series
    parallel: pd.Series             # cross-sectional mean of dR, bp

    @property
    def loadings(self) -> pd.DataFrame:
        return self.model.loadings

    def pc_cols(self, n: int) -> List[str]:
        return [f"PC{i + 1}" for i in range(n)]


def fit_factor_model(rate_panel: pd.DataFrame, cfg: FactorConfig) -> FactorModel:
    """Fit the shared basis. ``rate_panel`` is in percent; everything else is bp.

    The panel is restricted to ``cfg.tenors`` and to rows where every one of
    them prices, then differenced. Both counts are returned on the model's
    frames so a silent truncation (a patchy 40Y early in the sample would do it)
    is visible rather than assumed away.
    """
    cols = [t for t in cfg.tenors if t in rate_panel.columns]
    missing = [t for t in cfg.tenors if t not in rate_panel.columns]
    if missing:
        raise KeyError(f"rate panel is missing configured tenors {missing}")

    lvl_bp = (rate_panel[cols] * 100.0).sort_index()
    lvl_bp = lvl_bp.dropna(how="any")
    d_bp = lvl_bp.diff().dropna(how="any")

    model, scores_dm = fit_curve_pca_from_timeseries(
        lvl_bp, use_changes=True, sort_by_tenor=False, matrix=cfg.matrix, pin_signs=True,
    )

    # RAW factor realisations -- see module docstring, decision 1.
    V = model.loadings.values
    scores = pd.DataFrame(d_bp[model.columns].values @ V,
                          index=d_bp.index, columns=model.loadings.columns)

    parallel = d_bp[cols].mean(axis=1)
    parallel.name = "parallel_bp"

    return FactorModel(
        model=model,
        tenors=cols,
        rates_bp=lvl_bp,
        d_rates_bp=d_bp,
        scores=scores,
        scores_demeaned=scores_dm,
        explained_variance=model.explained_variance(),
        parallel=parallel,
    )


def classify_pcs(loadings: pd.DataFrame, tenors: Sequence[str], n: int = 3) -> pd.DataFrame:
    """Test the level/slope/curvature reading instead of assuming it.

    A long-end-heavy grid can rotate PC2 and PC3, so each PC is scored on three
    shape statistics of its loading vector and given the label the evidence
    supports:

    ``same_sign``   fraction of loadings sharing the modal sign. ~1.0 => LEVEL.
    ``n_sign_flips`` sign changes walking the grid short-to-long.
                    1 => monotone SLOPE, 2 => CURVATURE (a wing/belly shape).
    ``corr_tenor``  correlation of the loading with log-tenor. Signs the slope.

    The label is assigned from ``n_sign_flips`` (0/1/2/more ->
    level/slope/curvature/higher) and ``same_sign``, which is a structural
    property of the vector, not a comparison against a prior.
    """
    years = np.array([_tenor_years(t) for t in tenors], dtype=float)
    rows = []
    for j in range(min(n, loadings.shape[1])):
        name = loadings.columns[j]
        v = loadings[name].reindex(list(tenors)).values.astype(float)
        signs = np.sign(v)
        nz = signs[signs != 0]
        same_sign = float(max((nz > 0).mean(), (nz < 0).mean())) if nz.size else np.nan
        flips = int((np.diff(nz) != 0).sum()) if nz.size > 1 else 0
        # A perfectly flat loading vector has zero variance, so the correlation
        # with log-tenor is undefined rather than zero. Report NaN, not a
        # divide-by-zero warning: an exactly flat PC1 is the ideal level factor.
        corr = (float(np.corrcoef(v, np.log(years))[0, 1])
                if np.std(v) > 0 else float("nan"))
        if flips == 0:
            label = "level"
        elif flips == 1:
            label = "slope"
        elif flips == 2:
            label = "curvature"
        else:
            label = f"higher_order({flips} flips)"
        rows.append({
            "pc": name, "label": label, "same_sign_frac": same_sign,
            "n_sign_flips": flips, "corr_with_log_tenor": corr,
            "loading_mean": float(v.mean()), "loading_sum": float(v.sum()),
            "short_end": float(v[0]), "long_end": float(v[-1]),
        })
    return pd.DataFrame(rows).set_index("pc")


_TENOR_YEARS = {"1Y": 1.0, "2Y": 2.0, "3Y": 3.0, "5Y": 5.0, "7Y": 7.0, "10Y": 10.0,
                "15Y": 15.0, "20Y": 20.0, "25Y": 25.0, "30Y": 30.0, "40Y": 40.0,
                "50Y": 50.0}


def _tenor_years(t: str) -> float:
    t = str(t).strip().upper()
    if t in _TENOR_YEARS:
        return _TENOR_YEARS[t]
    if t.endswith("Y"):
        return float(t[:-1])
    if t.endswith("M"):
        return float(t[:-1]) / 12.0
    raise ValueError(f"cannot read tenor {t!r} as years")


# ===========================================================================
# 3. Interval aggregation of the factors
# ===========================================================================
def interval_factors(
    fm: FactorModel,
    intervals: Sequence[Tuple[Any, Any]],
    *,
    n_pcs: int = 3,
) -> pd.DataFrame:
    """Cumulative factor moves over ``(entry, exit)`` windows.

    ``entry`` is exclusive and ``exit`` inclusive, because the daily change
    series is already ``R_t - R_{t-1}``: summing changes over ``(entry, exit]``
    gives exactly ``R_exit - R_entry`` with no double count of the entry day.

    Returns, per interval: ``PC1..PCn`` (cumulative), ``parallel`` (cumulative
    parallel-equivalent move in bp), ``parallel_sq`` (its square -- the
    buy-and-hold convexity regressor), ``realised_var`` (sum of squared DAILY
    parallel moves -- the delta-hedged one), and ``n_days``.
    """
    pcs = fm.pc_cols(n_pcs)
    idx = fm.scores.index
    sc = fm.scores[pcs]
    par = fm.parallel
    rows = []
    for entry, exit_ in intervals:
        e0, e1 = pd.Timestamp(entry), pd.Timestamp(exit_)
        m = (idx > e0) & (idx <= e1)
        sub_sc, sub_par = sc[m], par[m]
        cum = sub_sc.sum()
        p = float(sub_par.sum())
        rows.append({
            **{c: float(cum[c]) for c in pcs},
            "parallel": p,
            "parallel_sq": p * p,
            "realised_var": float((sub_par ** 2).sum()),
            "n_days": int(m.sum()),
        })
    return pd.DataFrame(rows)


def parallel_move(fm: FactorModel) -> pd.Series:
    """Daily parallel-equivalent curve move in bp (mean change across the grid)."""
    return fm.parallel


def convexity_from_parallel(parallel: pd.Series) -> pd.Series:
    """The daily convexity regressor: squared parallel move, bp^2.

    NOT demeaned. Its mean IS the average gamma earnings per day; demeaning it
    would move exactly that quantity into the intercept and report it as alpha.
    """
    out = parallel.astype(float) ** 2
    out.name = "convexity"
    return out


def realised_variance(parallel: pd.Series, window: int) -> pd.Series:
    """Rolling sum of squared daily parallel moves -- the delta-hedged variant."""
    out = (parallel.astype(float) ** 2).rolling(int(window)).sum()
    out.name = f"realised_var_{int(window)}d"
    return out


# ===========================================================================
# 4. The regression
# ===========================================================================
@dataclass
class AttributionResult:
    """One strategy on the shared basis, at one measurement level."""

    name: str
    level: str                      # 'trade' or 'daily'
    n_obs: int
    window: str
    total_pnl: float
    unit: str
    r2: float
    r2_adj: float
    coefs: pd.Series
    tstats: pd.Series
    pvalues: pd.Series
    incremental_r2: pd.Series
    contributions: pd.Series        # beta_k * sum(x_k), plus 'unexplained'
    shares: pd.Series               # contributions / total_pnl
    gross_shares: pd.Series         # contributions / sum_k |contribution_k|
    denom_stability: float
    denom_unstable: bool
    coverage: float = float("nan")
    off_calendar: float = 0.0
    fit: Any = None

    def summary_row(self) -> Dict[str, Any]:
        """One row of the decisive table, in three readings of the same fit.

        ``share_*``       fraction of the NET P&L. The task's literal question,
                          and the only one that closes to 100%. It can exceed
                          100% or go negative whenever the factors partly
                          offset -- which is the normal case, not a pathology.
        ``gross_*``       the same contributions over the SUM OF THEIR ABSOLUTE
                          VALUES. Bounded in [-1, 1], immune to a small net, and
                          therefore the column to read when two books have very
                          different P&L totals.
        ``incr_*``        incremental R^2. This is the RISK reading, not the
                          return reading, and the distinction is the whole point
                          of carrying both: a book can hold a huge, highly
                          significant slope exposure that happened to earn
                          nothing, and only the R^2 column shows it.
        """
        row: Dict[str, Any] = {
            "strategy": self.name, "level": self.level, "n_obs": self.n_obs,
            "window": self.window, "total_pnl": self.total_pnl, "unit": self.unit,
            "r2": self.r2,
        }
        for k in FACTOR_ORDER:
            row[f"share_{k}"] = float(self.shares.get(k, np.nan))
        row["share_unexplained"] = float(self.shares.get("unexplained", np.nan))
        for k in FACTOR_ORDER:
            row[f"gross_{k}"] = float(self.gross_shares.get(k, np.nan))
        row["gross_unexplained"] = float(self.gross_shares.get("unexplained", np.nan))
        for k in FACTOR_ORDER:
            row[f"incr_{k}"] = float(self.incremental_r2.get(k, np.nan))
        for k in FACTOR_ORDER:
            row[f"t_{k}"] = float(self.tstats.get(k, np.nan))
        for k in FACTOR_ORDER:
            row[f"contrib_{k}"] = float(self.contributions.get(k, np.nan))
        row["contrib_unexplained"] = float(self.contributions.get("unexplained", np.nan))
        row["pnl_coverage"] = self.coverage
        row["off_calendar_pnl"] = self.off_calendar
        row["denom_stability"] = self.denom_stability
        row["denom_unstable"] = self.denom_unstable
        return row


def attribute(
    y: pd.Series,
    X: pd.DataFrame,
    *,
    name: str,
    level: str,
    unit: str = "usd",
    hac_lag: int = 21,
    order: Sequence[str] = FACTOR_ORDER,
) -> AttributionResult:
    """Regress P&L on the shared factor columns and decompose the realised P&L.

    ``X`` carries whichever of ``FACTOR_ORDER`` apply; a strategy with no
    separable carry series simply omits that column and its share reads NaN
    rather than a fabricated zero.

    t-stats are Newey-West (HAC). They have to be: strat 1's cohorts are entered
    monthly and held for a year, so twelve consecutive trade-level observations
    share eleven months of the same market path, and an OLS t-stat on that panel
    is inflated by roughly sqrt(12).
    """
    import statsmodels.api as sm

    cols = [c for c in order if c in X.columns]
    if not cols:
        raise ValueError(f"{name}: no usable factor columns in {list(X.columns)}")
    df = pd.concat([y.rename("_y"), X[cols]], axis=1).replace(
        [np.inf, -np.inf], np.nan).dropna(how="any")
    if len(df) <= len(cols) + 1:
        raise ValueError(f"{name}: {len(df)} usable observations for {len(cols)} regressors")

    yv = df["_y"]
    Xv = sm.add_constant(df[cols], has_constant="add")
    lag = int(max(0, min(hac_lag, len(df) // 4)))
    fit = sm.OLS(yv, Xv).fit(cov_type="HAC", cov_kwds={"maxlags": lag})

    # Incremental R^2 in the stated order (OLS R^2 is cov-estimator independent).
    inc: Dict[str, float] = {}
    prev = 0.0
    for i, c in enumerate(cols):
        sub = sm.add_constant(df[cols[: i + 1]], has_constant="add")
        r2i = float(sm.OLS(yv, sub).fit().rsquared)
        inc[c] = r2i - prev
        prev = r2i

    total = float(yv.sum())
    contrib = {c: float(fit.params[c] * df[c].sum()) for c in cols}
    contrib["unexplained"] = float(fit.params["const"] * len(df))
    gross = float(sum(abs(v) for v in contrib.values()))
    stability = abs(total) / gross if gross > 0 else np.nan
    shares = {k: (v / total if total != 0 else np.nan) for k, v in contrib.items()}
    gross_shares = {k: (v / gross if gross > 0 else np.nan) for k, v in contrib.items()}

    return AttributionResult(
        name=name, level=level, n_obs=int(len(df)),
        window=f"{df.index.min()!s:.10}..{df.index.max()!s:.10}"
        if isinstance(df.index, pd.DatetimeIndex) else f"n={len(df)}",
        total_pnl=total, unit=unit,
        r2=float(fit.rsquared), r2_adj=float(fit.rsquared_adj),
        coefs=pd.Series({c: float(fit.params[c]) for c in cols + ["const"]}),
        tstats=pd.Series({c: float(fit.tvalues[c]) for c in cols + ["const"]}),
        pvalues=pd.Series({c: float(fit.pvalues[c]) for c in cols + ["const"]}),
        incremental_r2=pd.Series(inc),
        contributions=pd.Series(contrib),
        shares=pd.Series(shares),
        gross_shares=pd.Series(gross_shares),
        denom_stability=float(stability),
        denom_unstable=bool(np.isfinite(stability) and stability < STABILITY_FLOOR),
        fit=fit,
    )


def decisive_table(
    results: Sequence[AttributionResult],
    *,
    level: Optional[str] = None,
    rank_by: str = "share_convexity",
) -> pd.DataFrame:
    """The one table: % of P&L by factor, every strategy, ranked by convexity.

    Rows flagged ``denom_unstable`` are sorted to the bottom regardless of their
    convexity share -- a 4000% convexity share on a $16k denominator is not a
    ranking, it is a division artefact.
    """
    rows = [r.summary_row() for r in results if level is None or r.level == level]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["denom_unstable", rank_by], ascending=[True, False])
    return df.reset_index(drop=True)


# ===========================================================================
# 5. The sizing diagnosis
# ===========================================================================
def package_pc_exposure(dv01_ladder: Mapping[str, float], fm: FactorModel,
                        n_pcs: int = 3) -> pd.Series:
    """PC exposures ``f = V^T r`` of a DV01 ladder, in $ per unit of PC score.

    Units check: P&L = r . dR = r . (V F) = (V^T r) . F, with ``r`` in $/bp and
    ``F`` in bp. So ``f_k`` is dollars per one unit of ``PC_k``, and it is
    directly comparable with the regression's ``beta_k``. That comparison is the
    tie-out that binds section 5 back to section 2.
    """
    r = pd.Series(dv01_ladder, dtype=float).reindex(fm.model.columns).fillna(0.0)
    f = fm.loadings.T.values @ r.values
    out = pd.Series(f, index=fm.loadings.columns, name="pc_exposure_usd_per_unit")
    return out.iloc[:n_pcs]


def annuity_dv01(rate_bp: float, years: float, freq: int = 1) -> float:
    """DV01 per $1 notional of a par swap: the level annuity, $ per bp.

    ``A = (1 - (1+y/f)^(-f*T)) / y`` for a par swap at rate ``y``, times 1e-4.
    Used only to split a FORWARD leg into the two spot legs that replicate it;
    the ratio it feeds is a first-order sizing diagnosis, not a pricing.
    """
    y = float(rate_bp) / 1e4
    if abs(y) < 1e-10:
        return float(years) * 1e-4
    n = float(freq) * float(years)
    return (1.0 - (1.0 + y / freq) ** (-n)) / y * 1e-4


def spot_ladder_for_leg(leg: str, dv01: float, rates_bp: Mapping[str, float]) -> Dict[str, float]:
    """A leg's DV01 spread over SPOT par tenors.

    A spot leg is itself: ``{"30Y": dv01}``.

    A forward ``AxB`` receiving/paying fixed replicates as a long spot ``A+B``
    and a short spot ``A`` at the SAME notional, so its DV01 splits::

        w_long  = A_(A+B) / (A_(A+B) - A_A)     at tenor A+B
        w_short = -A_A    / (A_(A+B) - A_A)     at tenor A

    where ``A_T`` is the par annuity. The weights sum to 1, so the ladder
    carries the leg's whole DV01. Approximate -- it uses par annuities rather
    than the leg's own risk report -- and adequate for a ratio diagnosis, which
    is all section 5 asks of it.
    """
    leg = str(leg).strip()
    if "X" not in leg.upper():
        return {leg: float(dv01)}
    a_s, b_s = leg.upper().split("X")
    a, b = _tenor_years(a_s), _tenor_years(b_s)
    t_long = a + b
    lab_long, lab_short = _fmt_years(t_long), _fmt_years(a)
    y_long = float(rates_bp.get(lab_long, rates_bp.get(lab_short, 300.0)))
    y_short = float(rates_bp.get(lab_short, y_long))
    A_long = annuity_dv01(y_long, t_long)
    A_short = annuity_dv01(y_short, a)
    den = A_long - A_short
    if abs(den) < 1e-12:
        raise ValueError(f"degenerate forward leg {leg}: annuities coincide")
    out: Dict[str, float] = {}
    out[lab_long] = out.get(lab_long, 0.0) + float(dv01) * A_long / den
    out[lab_short] = out.get(lab_short, 0.0) - float(dv01) * A_short / den
    return out


def _fmt_years(y: float) -> str:
    iy = int(round(y))
    return f"{iy}Y"


def dv01_neutral_ladder(front: str, back: str, dv01: float,
                        rates_bp: Mapping[str, float]) -> Dict[str, float]:
    """A DV01-neutral FLATTENER: receive the back leg, pay the front leg.

    Sign convention is the one this package established empirically and states
    in ``RVUtils/ConvexityRV/__init__.py``: ``bpv < 0`` on the curve structure is
    the FLATTENER and it is LONG convexity. Here that is expressed directly --
    the back leg is received (negative DV01, gains as rates fall on the long
    end) and the front leg is paid (positive DV01) at equal and opposite size,
    which is what "DV01-neutral" means.
    """
    ladder: Dict[str, float] = {}
    for lab, sgn in ((front, +1.0), (back, -1.0)):
        for t, v in spot_ladder_for_leg(lab, sgn * float(dv01), rates_bp).items():
            ladder[t] = ladder.get(t, 0.0) + v
    return ladder


def gamma_from_payoff_profile(panel: pd.DataFrame, structure: str,
                              half_width_bp: float = 25.0) -> float:
    """Gamma in **bp of P&L per bp^2 of parallel shift**, from the payoff profile.

    Second central difference of the already-computed profile in
    ``strat1_signal_panel.parquet``::

        gamma = (P(+h) - 2 P(0) + P(-h)) / h^2

    The carry that ``payoff_profile(carry_ccy=...)`` adds is a LEVEL on the
    profile, so the second difference removes it exactly -- this is a clean
    gamma, not a gamma contaminated by theta. Averaged over the sample so it is
    the structure's typical convexity, not one day's.
    """
    h = float(half_width_bp)
    lo, mid, hi = f"payoff_bp_-{int(h)}", "payoff_bp_+0", f"payoff_bp_+{int(h)}"
    sub = panel[panel["structure"] == structure]
    if sub.empty:
        raise KeyError(f"no rows for structure {structure!r}")
    for c in (lo, mid, hi):
        if c not in sub.columns:
            raise KeyError(f"payoff profile column {c!r} not in panel")
    g = (sub[hi] - 2.0 * sub[mid] + sub[lo]) / (h * h)
    return float(g.mean())


def sizing_diagnosis(
    structures: Sequence[Tuple[str, str, str]],
    fm: FactorModel,
    signal_panel: pd.DataFrame,
    *,
    dv01: float = 100_000.0,
    n_pcs: int = 3,
    horizon_days: int = 252,
    half_width_bp: float = 25.0,
) -> pd.DataFrame:
    """What a DV01-neutral flattener's factor exposure actually IS.

    For each ``(label, front, back)``, at ``dv01`` of DV01-neutral package:

    ``pc1_usd..pc3_usd``   $ per unit of each PC score (``f = V^T r``).
    ``slope_pnl_1y``       |f2| x the 1-year sd of the PC2 move -- the dollars a
                           one-sigma slope move puts through the book.
    ``convex_pnl_1y``      ``0.5 * gamma * E[(parallel move over 1y)^2]``, with
                           gamma read off the payoff profile already on disk.
    ``slope_to_convex``    the ratio. This is the sizing answer: if it is large,
                           DV01-neutral sizing has bought a slope position with
                           a convexity garnish.

    ``pc1_usd`` is reported too and is the quieter finding: DV01-neutral is not
    even PC1-neutral, because PC1's loadings are not flat across the grid.

    ``var_pc1..var_pc3`` are the RISK decomposition and are the columns that
    actually settle the sizing question. An exposure in dollars-per-unit is not
    comparable across PCs, because the PCs do not move by the same amount: PC1
    carries 88% of the daily variance and PC3 under 1%. The share of the
    package's own variance coming from PC ``k`` is::

        f_k^2 * lambda_k / sum_j f_j^2 * lambda_j

    which is the honest answer to "what is this position actually exposed to".
    """
    rates_bp = fm.rates_bp.mean().to_dict()
    pcs = fm.pc_cols(n_pcs)
    # 1-year sd of each factor, from non-overlapping-equivalent scaling of the
    # daily sd. sqrt-time, stated as the approximation it is.
    sd_1y = fm.scores[pcs].std(ddof=1) * np.sqrt(float(horizon_days))
    par_var_1y = float((fm.parallel ** 2).mean()) * float(horizon_days)

    rows = []
    for label, front, back in structures:
        ladder = dv01_neutral_ladder(front, back, dv01, rates_bp)
        f = package_pc_exposure(ladder, fm, n_pcs=n_pcs)
        gamma_bp = gamma_from_payoff_profile(signal_panel, label,
                                             half_width_bp=half_width_bp)
        # gamma is bp-of-P&L per bp^2, on a package of `dv01` per bp:
        gamma_usd = gamma_bp * float(dv01)
        slope_pnl = abs(float(f["PC2"]) * float(sd_1y["PC2"]))
        curv_pnl = abs(float(f["PC3"]) * float(sd_1y["PC3"]))
        convex_pnl = 0.5 * gamma_usd * par_var_1y
        lam = fm.model.eigenvalues.reindex(pcs).values.astype(float)
        contrib = (f.values.astype(float) ** 2) * lam
        vshare = contrib / contrib.sum() if contrib.sum() > 0 else np.full(n_pcs, np.nan)
        row = {"structure": label,
               "front": front, "back": back,
               **{f"pc{i+1}_usd_per_unit": float(f[f"PC{i+1}"]) for i in range(n_pcs)},
               **{f"var_pc{i+1}": float(vshare[i]) for i in range(n_pcs)},
               "gamma_bp_per_bp2": gamma_bp,
               "slope_pnl_1sd_1y_usd": slope_pnl,
               "curv_pnl_1sd_1y_usd": curv_pnl,
               "convex_pnl_1y_usd": convex_pnl,
               "slope_to_convex": slope_pnl / convex_pnl if convex_pnl else np.nan,
               "curv_to_convex": curv_pnl / convex_pnl if convex_pnl else np.nan}
        # PC1 leakage: how much of a $100k DV01 outright's PC1 exposure survives
        # the DV01-neutral construction.
        outright = package_pc_exposure({back if "X" not in back.upper() else
                                        _fmt_years(sum(_tenor_years(p) for p in
                                                       back.upper().split("X"))): dv01},
                                       fm, n_pcs=n_pcs)
        row["pc1_leakage_vs_outright"] = (abs(float(f["PC1"])) / abs(float(outright["PC1"]))
                                          if float(outright["PC1"]) else np.nan)
        rows.append(row)
    out = pd.DataFrame(rows)
    return out.sort_values("slope_to_convex", ascending=False).reset_index(drop=True)


# ===========================================================================
# 6. Strategy loaders -- turning each book's artifacts into (y, w, carry)
# ===========================================================================
#: Every book in this package is sized to a $100,000 DV01 package, so a P&L
#: quoted in "bp" is bp OF THAT DV01 and converts at a flat $100k per bp. That
#: is what makes dollar contributions comparable across all three strategies
#: without any further normalisation -- verified on strat 1's cohort table,
#: where ``gross_pnl_ccy / gross_pnl_bp`` is exactly 1e5 on every row.
BP_TO_USD = 100_000.0

#: (label, front leg, back leg) for strat 1's four structures. Front is paid and
#: back is received in the flattener, per ``dv01_neutral_ladder``.
STRAT1_STRUCTURES: Tuple[Tuple[str, str, str], ...] = (
    ("5Y/30Y", "5Y", "30Y"),
    ("30Y/50Y", "30Y", "50Y"),
    ("20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y"),
    ("10Yx10Y/20Yx10Y", "10Yx10Y", "20Yx10Y"),
)


@dataclass
class StrategySeries:
    """One book's P&L plus everything needed to put it on the shared basis.

    ``weight`` is the position's signed size in $100k-DV01 packages. It is +1
    for a book that never flips -- which is most of them -- and the point of
    that choice is worth stating: the SIGN of the fitted convexity coefficient
    is then an OUTPUT of the regression rather than an assumption smuggled in
    through the regressor. Only where the book genuinely reverses (strat 1
    base's 5Y/30Y, the ``swaption_only`` gate) does ``weight`` carry a minus
    sign, and there +1 means the flattener, this package's long-convexity
    convention.

    ``carry`` is already in the same unit and sign as ``y``; None where the book
    has no separable carry series, which reads NaN in the table rather than a
    fabricated zero.
    """

    name: str
    level: str                                  # 'trade' | 'daily'
    y: pd.Series
    weight: pd.Series
    carry: Optional[pd.Series] = None
    intervals: Optional[List[Tuple[Any, Any]]] = None
    unit: str = "usd"
    note: str = ""
    #: The book's own total P&L before any calendar alignment or day filtering,
    #: so ``coverage`` in the decisive table can show what the regression saw.
    raw_total: float = float("nan")
    #: P&L on marks that fall past the factor calendar's last day and therefore
    #: have no factor observation to be attributed to. Reported, never hidden:
    #: it is why a coverage figure can land slightly above 100%.
    off_calendar: float = 0.0


def daily_design(fm: FactorModel, s: StrategySeries, *, n_pcs: int = 3) -> pd.DataFrame:
    """Design matrix for a DAILY P&L series: ``w_t`` times each daily factor.

    Days with no position (``w_t == 0``) are dropped. A flat day with no book is
    not an observation of zero factor exposure -- it carries no information
    about the coefficients and would only shrink the estimates toward zero.
    """
    pcs = fm.pc_cols(n_pcs)
    idx = s.y.index.intersection(fm.scores.index)
    w = s.weight.reindex(idx).astype(float).fillna(0.0)
    idx = idx[(w != 0.0).values]
    w = w.loc[idx]
    X = pd.DataFrame(index=idx)
    for name, col in zip(("level", "slope", "curvature"), pcs):
        X[name] = w.values * fm.scores.loc[idx, col].values
    X["convexity"] = w.values * (fm.parallel.loc[idx].values ** 2)
    if s.carry is not None:
        X["carry"] = s.carry.reindex(idx).astype(float).values
    return X


def trade_design(fm: FactorModel, s: StrategySeries, *, n_pcs: int = 3,
                 convexity: str = "parallel_sq") -> pd.DataFrame:
    """Design matrix for a TRADE-level P&L series over ``s.intervals``.

    ``convexity='parallel_sq'`` is the squared TERMINAL move -- correct for an
    unhedged buy-and-hold cohort. ``convexity='realised_var'`` is the sum of
    squared daily moves -- correct for a delta-hedged book, and the sensitivity
    the notebook runs.
    """
    if s.intervals is None:
        raise ValueError(f"{s.name}: trade_design needs intervals")
    if convexity not in ("parallel_sq", "realised_var"):
        raise ValueError(f"convexity must be parallel_sq or realised_var, got {convexity!r}")
    pcs = fm.pc_cols(n_pcs)
    ivf = interval_factors(fm, s.intervals, n_pcs=n_pcs)
    ivf.index = s.y.index
    w = s.weight.reindex(s.y.index).astype(float)
    X = pd.DataFrame(index=s.y.index)
    for name, col in zip(("level", "slope", "curvature"), pcs):
        X[name] = w.values * ivf[col].values
    X["convexity"] = w.values * ivf[convexity].values
    if s.carry is not None:
        X["carry"] = s.carry.reindex(s.y.index).astype(float).values
    return X


def align_to_factor_calendar(pnl: pd.Series, calendar: pd.DatetimeIndex
                             ) -> Tuple[pd.Series, float]:
    """Fold a daily P&L series onto the factor calendar WITHOUT losing P&L.

    The two calendars do not agree and the gap is not cosmetic. The backtests
    mark on ``pd.bdate_range``, which includes Good Friday; the curve panel does
    not price that day. A plain index intersection silently deletes those marks
    -- measured here at $17.7m on seven days for one strat 1 structure, which is
    30% of that book's P&L. So each unscored day's mark is carried FORWARD onto
    the next scored day, which is where its factor move actually shows up
    anyway: the 5-day change the curve panel records across a Good Friday
    already contains the move the backtest booked on it.

    Marks after the last scored day (the panel ends 2026-08-12, some equity
    curves run to 2026-08-14) have nowhere to go; they are returned as the
    second element rather than folded, so the loss is reported, not hidden.
    """
    pnl = pnl.sort_index()
    cal = pd.DatetimeIndex(calendar).sort_values()
    pos = cal.searchsorted(pnl.index, side="left")
    inside = pos < len(cal)
    dropped = float(pnl[~inside].sum())
    agg = pnl[inside].groupby(cal[pos[inside]]).sum()
    lo, hi = cal.searchsorted(pnl.index.min(), "left"), cal.searchsorted(pnl.index.max(), "left")
    out = agg.reindex(cal[lo: min(hi + 1, len(cal))]).fillna(0.0)
    out.name = pnl.name
    return out, dropped


def _active_weight(index: pd.DatetimeIndex, entries, exits, directions,
                   values=None) -> pd.Series:
    """Sum a per-cohort quantity over the cohorts live on each day.

    A cohort contributes on ``(entry, exit]`` -- the same half-open convention
    ``interval_factors`` uses, and the right one: the backtest adds the position
    at ``entry`` with a zero mark, so the first day it can move the equity is
    ``entry + 1``.
    """
    out = pd.Series(0.0, index=index)
    vals = [1.0] * len(list(entries)) if values is None else list(values)
    for e, x, d, v in zip(entries, exits, directions, vals):
        e, x = pd.Timestamp(e), pd.Timestamp(x)
        if not np.isfinite(d) or d == 0 or not np.isfinite(v):
            continue
        m = (index > e) & (index <= x)
        out.loc[m] += float(d) * float(v)
    return out


def _carry_at_entry(signal_panel: pd.DataFrame, structure: str) -> pd.Series:
    """1-year carry-and-roll in bp for one structure, indexed by date."""
    sub = signal_panel[signal_panel["structure"] == structure]
    s = sub.set_index(pd.to_datetime(sub["date"]))["carry_roll_bp"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index()


# --- strat 1 base ----------------------------------------------------------
def load_strat1_base(data_dir, signal_panel: pd.DataFrame,
                     calendar: pd.DatetimeIndex,
                     structures: Sequence[Tuple[str, str, str]] = STRAT1_STRUCTURES,
                     ) -> Dict[str, "StrategySeries"]:
    """Strat 1 base: four structures, signal-directed, monthly 1-year cohorts.

    Trade level uses CLOSED cohorts only (12 of 88 are still live at the end and
    have no realised P&L). Daily level uses every cohort in the book, live ones
    included, because they are marked in the equity curve.

    **The live cohorts carry a NaT exit, and that is a trap.** ``(index <= NaT)``
    is all-False, so a naive weight build silently gives the twelve open cohorts
    zero size and drops the final year of marks onto flat days -- measured at
    37% of one structure's P&L before the fix. Their exit is therefore set to the
    end of the calendar, which is what "still open on the last day" means.
    """
    import pathlib
    data_dir = pathlib.Path(data_dir)
    out: Dict[str, StrategySeries] = {}
    for label, _front, _back in structures:
        safe = label.replace("/", "-")
        coh = pd.read_parquet(data_dir / f"strat1_cohorts_{safe}.parquet")
        eq = pd.read_parquet(data_dir / f"strat1_equity_{safe}.parquet")
        eq.index = pd.to_datetime(eq.index)
        carry_bp = _carry_at_entry(signal_panel, label)

        cl = coh[coh["closed"]].reset_index(drop=True)
        entry, exit_ = pd.to_datetime(cl["entry"]), pd.to_datetime(cl["exit"])
        y = (cl["gross_pnl_bp"].astype(float) * BP_TO_USD).rename("pnl_usd")
        d = cl["direction"].astype(float)
        carry_tr = carry_bp.reindex(entry).values * d.values * BP_TO_USD
        out[f"strat1_base {label}"] = StrategySeries(
            name=f"strat1_base {label}", level="trade", y=y, weight=d,
            carry=pd.Series(carry_tr, index=y.index),
            intervals=list(zip(entry, exit_)), raw_total=float(y.sum()),
            note="signal-directed; closed cohorts only",
        )

        raw = eq["equity_usd"].astype(float).diff().dropna()
        dy, dropped = align_to_factor_calendar(raw, calendar)
        ce = pd.to_datetime(coh["entry"])
        cx = pd.to_datetime(coh["exit"]).fillna(pd.Timestamp(calendar[-1]))
        cd = coh["direction"].astype(float)
        w = _active_weight(dy.index, ce, cx, cd)
        cw = _active_weight(dy.index, ce, cx, cd,
                            values=carry_bp.reindex(ce).values) * BP_TO_USD / 252.0
        out[f"strat1_base {label} [daily]"] = StrategySeries(
            name=f"strat1_base {label}", level="daily", y=dy, weight=w, carry=cw,
            raw_total=float(raw.sum()), off_calendar=dropped,
            note="net live packages; carry = 1y carry-roll at entry / 252",
        )
    return out


# --- strat 1 long-end ------------------------------------------------------
def load_strat1_longend(data_dir, signal_panel: pd.DataFrame,
                        calendar: pd.DatetimeIndex,
                        gates: Sequence[str] = ("always", "swaption_only"),
                        structures: Sequence[Tuple[str, str, str]] = STRAT1_STRUCTURES,
                        ) -> Dict[str, "StrategySeries"]:
    """Strat 1 long-end: the ``always`` control and the ``swaption_only`` gate.

    ``gross_bp`` in these tables is the UNIT (always-flattener) P&L; the book's
    realised P&L is ``gate_direction * gross_bp``. Verified against the base
    run, where 30Y/50Y's ``direction`` is +1 throughout and the two gross series
    agree row for row. Cohorts with ``gate_direction == 0`` are not trades and
    are dropped rather than entered as zeros.

    Pooled across the four structures at trade level (they are one book), and
    the POOLED equity curve is used at daily level.
    """
    import pathlib
    data_dir = pathlib.Path(data_dir)
    out: Dict[str, StrategySeries] = {}
    for gate in gates:
        frames = []
        for label, _f, _b in structures:
            safe = label.replace("/", "-")
            c = pd.read_parquet(data_dir / f"strat1_le_cohorts_{safe}_{gate}.parquet")
            c["label"] = label
            c["carry_bp"] = _carry_at_entry(signal_panel, label).reindex(
                pd.to_datetime(c["entry"])).values
            frames.append(c)
        allc = pd.concat(frames, ignore_index=True)
        allc = allc[allc["traded"] & (allc["gate_direction"] != 0)]
        # The daily book holds every cohort it ever opened, closed or not. The
        # trade-level series can only use the closed ones -- an open cohort has
        # no realised P&L -- but restricting the DAILY weight the same way would
        # leave the last year of marks sitting on w == 0 and drop them.
        coh = allc[allc["closed"]].sort_values(["entry", "label"]).reset_index(drop=True)
        d = coh["gate_direction"].astype(float)
        y = (coh["gross_bp"].astype(float) * d * BP_TO_USD).rename("pnl_usd")
        out[f"strat1_LE {gate}"] = StrategySeries(
            name=f"strat1_LE {gate}", level="trade", y=y, weight=d,
            carry=(coh["carry_bp"].astype(float) * d * BP_TO_USD),
            intervals=list(zip(pd.to_datetime(coh["entry"]), pd.to_datetime(coh["exit"]))),
            raw_total=float(y.sum()),
            note="4 structures pooled; gate_direction-signed; gate=0 dropped",
        )

        eq = pd.read_parquet(data_dir / f"strat1_le_equity_POOLED_{gate}.parquet")
        eq.index = pd.to_datetime(eq.index)
        raw = eq["equity_usd"].astype(float).diff().dropna()
        dy, dropped = align_to_factor_calendar(raw, calendar)
        ce = pd.to_datetime(allc["entry"])
        cx = pd.to_datetime(allc["exit"]).fillna(pd.Timestamp(calendar[-1]))
        da = allc["gate_direction"].astype(float)
        w = _active_weight(dy.index, ce, cx, da)
        cw = _active_weight(dy.index, ce, cx, da,
                            values=allc["carry_bp"].astype(float).values) * BP_TO_USD / 252.0
        out[f"strat1_LE {gate} [daily]"] = StrategySeries(
            name=f"strat1_LE {gate}", level="daily", y=dy, weight=w, carry=cw,
            raw_total=float(raw.sum()), off_calendar=dropped,
            note="POOLED equity across the 4 structures",
        )
    return out


# --- strat 2 ---------------------------------------------------------------
def load_strat2(data_dir, epochs: pd.DataFrame,
                calendar: pd.DatetimeIndex) -> Dict[str, "StrategySeries"]:
    """Strat 2: the CA leg, the fly hedge alone, and the hedged total.

    ``strat2_equity`` carries two books. ``unhedged`` IS the CA leg -- the four
    SR3 futures legs against the DV01-matched matched-maturity swap, nothing
    else (``build_trade_queries`` adds the fly only when ``hedged=True``). So
    the third series, the hedge in isolation, is ``hedged - unhedged``, and it
    is worth separating: the fly is a 2s5s10s butterfly, an outright curve
    position, and lumping it in with the CA leg is precisely what would make a
    pure-RV leg look directional.

    The book never reverses: ``contracts_per_leg = round(ca_dv01 / 100)`` is
    positive for every epoch, so strat 2 is short convexity throughout, and
    ``weight`` is +1. The sign of the fitted convexity coefficient is therefore
    a result, and it should come out NEGATIVE if the CA leg is what it claims.

    P&L is net of the unwind fee, which lands as a fixed jump on each epoch's
    exit day and is absorbed by the intercept.
    """
    import pathlib
    eq = pd.read_parquet(pathlib.Path(data_dir) / "strat2_equity.parquet")
    eq.index = pd.to_datetime(eq.index)
    books = {"strat2 CA leg (unhedged)": eq["unhedged"].astype(float),
             "strat2 hedged": eq["hedged"].astype(float),
             "strat2 fly hedge only": (eq["hedged"] - eq["unhedged"]).astype(float)}
    ent, ext = pd.to_datetime(epochs["entry"]), pd.to_datetime(epochs["exit"])
    out: Dict[str, StrategySeries] = {}
    for name, curve in books.items():
        raw = curve.diff().dropna()
        dy, dropped = align_to_factor_calendar(raw, calendar)
        w = _active_weight(dy.index, ent, ext, np.ones(len(ent)))
        w = (w > 0).astype(float)      # epochs are contiguous; never stack
        out[f"{name} [daily]"] = StrategySeries(
            name=name, level="daily", y=dy, weight=w, carry=None,
            raw_total=float(raw.sum()), off_calendar=dropped,
            note="short convexity throughout; no separable carry series",
        )
        tr = pd.Series([float(curve.asof(b) - curve.asof(a))
                        for a, b in zip(ent, ext)], name="pnl_usd")
        out[name] = StrategySeries(
            name=name, level="trade", y=tr, weight=pd.Series(1.0, index=tr.index),
            carry=None, intervals=list(zip(ent, ext)),
            raw_total=float(tr.sum()), note="one observation per epoch",
        )
    return out


# --- strat 3 ---------------------------------------------------------------
def load_strat3(data_dir, pairs: Sequence[str], calendar: pd.DatetimeIndex,
                *, roll_months: int = 12, threshold_bp: float = 25.0,
                beta: float = 1.0, resize_mode: str = "neutral",
                trade_block: str = "QE",
                ) -> Dict[str, "StrategySeries"]:
    """Strat 3: delta-hedged forward flatteners, from the ledger already on disk.

    The ledger buckets each day into ``carry / harvest / mtm / cross / cost``,
    so GROSS is ``total + cost`` and CARRY is the ledger's own carry column --
    no proxy needed, which makes strat 3 the one book whose carry regressor is
    measured rather than approximated.

    The book is a continuously rolled flattener (``entry_rule='always'``), so
    ``weight`` is +1 and there is no natural trade unit.

    **Why the coarse level is a calendar quarter and not the roll segment.**
    The roll segment is the intuitive "trade" here -- one per ``roll_months`` --
    but at 12m rolls over 2019-2026 that is EIGHT observations against five
    regressors and an intercept. Two residual degrees of freedom will fit
    anything; the R^2 of 0.99 that comes back is a statement about arithmetic,
    not about the strategy. So the coarse interval is a calendar quarter
    (~30 non-overlapping blocks), which is long enough for the squared-move term
    to carry real signal and short enough to be identified. The roll-segment
    version is available by passing ``trade_block=None`` and is reported in the
    notebook only to show what over-fitting looks like.
    """
    import pathlib
    led = pd.read_parquet(pathlib.Path(data_dir) / "strat3_ledgers.parquet").reset_index()
    out: Dict[str, StrategySeries] = {}
    for pair in pairs:
        m = ((led["pair"] == pair) & (led["roll_months"] == roll_months)
             & (led["threshold_bp"] == threshold_bp) & (led["beta"] == beta)
             & (led["resize_mode"] == resize_mode))
        sub = led[m].copy()
        if sub.empty:
            raise KeyError(f"strat3: no ledger rows for {pair} roll={roll_months} "
                           f"thr={threshold_bp} beta={beta} {resize_mode}")
        sub.index = pd.to_datetime(sub["date"])
        sub = sub.sort_index()
        gross = (sub["total"].astype(float) + sub["cost"].astype(float)).rename("pnl_usd")
        carry_d = sub["carry"].astype(float)
        name = f"strat3 {pair}"
        g_al, dropped = align_to_factor_calendar(gross, calendar)
        c_al, _ = align_to_factor_calendar(carry_d, calendar)
        out[f"{name} [daily]"] = StrategySeries(
            name=name, level="daily", y=g_al, weight=pd.Series(1.0, index=g_al.index),
            carry=c_al, raw_total=float(gross.sum()), off_calendar=dropped,
            note=f"gross = total + cost; roll={roll_months}m thr={threshold_bp}bp "
                 f"beta={beta} {resize_mode}",
        )
        if trade_block:
            seg = pd.Series(sub.index, index=sub.index).dt.to_period(trade_block[0])
            block_note = f"one observation per calendar {trade_block[0]}"
        else:
            age = sub["position_age_years"].astype(float)
            seg = (age.diff().fillna(0.0) < -0.1).cumsum()
            block_note = f"one observation per {roll_months}m roll segment"
        keys = list(pd.unique(seg))
        edges = [(sub.index[(seg == k).values][0], sub.index[(seg == k).values][-1])
                 for k in keys]
        tr = gross.groupby(seg.values).sum().reindex(keys).reset_index(drop=True)
        car = carry_d.groupby(seg.values).sum().reindex(keys).reset_index(drop=True)
        out[name] = StrategySeries(
            name=name, level="trade", y=tr.rename("pnl_usd"),
            weight=pd.Series(1.0, index=tr.index), carry=car, intervals=edges,
            raw_total=float(tr.sum()), note=block_note,
        )
    return out


def exposure_tieout(fm: FactorModel, structures: Sequence[Tuple[str, str, str]],
                    results: Mapping[str, AttributionResult], *,
                    dv01: float = 100_000.0, n_pcs: int = 3) -> pd.DataFrame:
    """Regression betas vs the analytic ``f = V^T r`` of the same DV01 ladder.

    This is the check that binds sections 1, 2 and 5 together. If the fitted
    ``beta_slope`` of an always-on flattener book does not come back at the
    ladder's own PC2 exposure, then either the basis or the attribution is
    wrong, and nothing downstream can be trusted.

    Two tolerances, because a ratio on a near-zero denominator is exactly the
    trap this module flags elsewhere. ``ratio`` is informative only where the
    analytic exposure is large; ``rel_err`` normalises the ERROR VECTOR by the
    package's total factor exposure ``||f||`` and is the number to read.

    The residual gap is expected and has a cause: ``f`` is the exposure at
    inception, while ``beta`` is the average realised exposure of a book whose
    cohorts age (a year-old 30Y/50Y is a 29Y/49Y) and whose DV01-neutrality
    drifts as rates move.
    """
    rates_bp = fm.rates_bp.mean().to_dict()
    rows = []
    for label, front, back in structures:
        key = next((k for k in results if label in k), None)
        if key is None:
            continue
        r = results[key]
        lad = dv01_neutral_ladder(front, back, dv01, rates_bp)
        f = package_pc_exposure(lad, fm, n_pcs=n_pcs)
        b = np.array([r.coefs.get("level", np.nan), r.coefs.get("slope", np.nan),
                      r.coefs.get("curvature", np.nan)][:n_pcs], dtype=float)
        fv = f.values.astype(float)
        rows.append({
            "structure": label,
            "beta_level": b[0], "f_level": fv[0],
            "beta_slope": b[1], "f_slope": fv[1],
            "beta_curvature": b[2], "f_curvature": fv[2],
            "ratio_slope": b[1] / fv[1] if fv[1] else np.nan,
            "norm_f": float(np.linalg.norm(fv)),
            "rel_err": float(np.linalg.norm(b - fv) / np.linalg.norm(fv)),
            "cosine": float((b @ fv) / (np.linalg.norm(b) * np.linalg.norm(fv))),
        })
    return pd.DataFrame(rows)


def load_all_strategies(data_dir, signal_panel: pd.DataFrame,
                        strat2_epochs: pd.DataFrame, calendar: pd.DatetimeIndex,
                        strat3_pairs: Sequence[str] = ("15Yx5Y/20Yx10Y", "15Yx5Y/20Yx5Y"),
                        ) -> Dict[str, "StrategySeries"]:
    """Every book in one dict, keyed ``"<name>"`` / ``"<name> [daily]"``.

    ``calendar`` is ``FactorModel.scores.index`` -- the days on which a factor
    move exists. Every daily P&L is folded onto it, so what the regression sees
    and what the equity curve says are the same number.
    """
    out: Dict[str, StrategySeries] = {}
    out.update(load_strat1_base(data_dir, signal_panel, calendar))
    out.update(load_strat1_longend(data_dir, signal_panel, calendar))
    out.update(load_strat2(data_dir, strat2_epochs, calendar))
    out.update(load_strat3(data_dir, list(strat3_pairs), calendar))
    return out


def run_attribution(fm: FactorModel, series: Mapping[str, "StrategySeries"],
                    cfg: FactorConfig, *, n_pcs: int = 3,
                    convexity: str = "parallel_sq") -> List[AttributionResult]:
    """Put every book on the shared basis and return the attribution results."""
    results: List[AttributionResult] = []
    for _key, s in series.items():
        if s.level == "daily":
            X = daily_design(fm, s, n_pcs=n_pcs)
            y = s.y.reindex(X.index)
            lag = cfg.hac_lag_daily
        else:
            X = trade_design(fm, s, n_pcs=n_pcs, convexity=convexity)
            y = s.y
            lag = cfg.hac_lag_trade
        r = attribute(y, X, name=s.name, level=s.level, unit=s.unit, hac_lag=lag)
        if np.isfinite(s.raw_total) and s.raw_total != 0:
            r.coverage = float(r.total_pnl / s.raw_total)
        r.off_calendar = float(s.off_calendar)
        results.append(r)
    return results
