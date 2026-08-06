# RVUtils/StrikelessVol/report.py
"""Distribution diagnostics -- and a measured warning about which ones mean anything.

**Read this before ranking anything on ``distribution_stats`` or ``vol_beta``.**

This module was written on the premise that a long-convexity position and its
short-convexity mirror can print the same Sharpe but must differ in the SHAPE
of their daily P&L (skew near zero against the short-vol signature of ~-3) and
in the sign of their response to changes in implied vol. **Both propositions
were tested on real curves in Task 13 and both are false for a forward-slope
package**, which is the instrument this package studies:

* Daily P&L skew does not separate them. Measured on USD 10Y10Y/20Y10Y over
  2017-2026: the long book prints +0.087 and its exact mirror -0.082. Both
  clear ``> -1``. A DV01-matched **zero-convexity** twin
  (``replication.ZeroConvexityPricer``: constant maturity, no gamma, no carry)
  prints +0.288 -- a BETTER skew than the convex book, on zero gamma.
* The vol correlation is not a property of the position at all. It is the
  market's own slope/vol comovement, which anything carrying this DV01
  inherits: ``corr(-d spread, d vol)`` computed straight from the curves with
  no position in the calculation is +0.6129, and the zero-convexity twin's
  ``vol_corr`` is +0.6129 to four decimals.

The reason is that a DV01-neutral forward-slope package is delta-hedged
against the LEVEL of rates but carries a full FIRST-ORDER exposure to the
SLOPE, and that linear term is ~96% of daily P&L variance. Every statistic
computed on the raw P&L is therefore dominated by it and reads the same way
for any book carrying the same DV01, convex or not.

``distribution_stats`` and ``vol_beta`` remain correct and useful as
DESCRIPTIONS of a P&L series -- they are used throughout the study for exactly
that. They are not evidence of convexity.

**Nor is anything else in this module.** :func:`residual_stats` was built as
the replacement and then failed its own calibration (1-for-2 on the cases where
the truth was independently known), and :func:`mirror_split` was built to
rescue it and turned out to be an arithmetic x2 rescaling. Both are kept as a
committed record of that, with their limits in their docstrings, and both are
report-only.

**To ask whether a package is convex, call** :func:`greeks.package_gamma` --
it answers directly, from a bump-and-reprice, and it settled the case these
statistics could not in a single call. **To ask whether that convexity was
realised, read the ledger's ``harvest`` bucket.**
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import TRADING_DAYS

__all__ = [
    "cost_table",
    "distribution_stats",
    "league_table",
    "ledger_attribution",
    "mirror_split",
    "per_year_attribution",
    "portfolio",
    "residual_stats",
    "vol_beta",
]


def distribution_stats(daily_pnl: pd.Series) -> dict:
    """Sharpe, skew, excess kurtosis, max drawdown and daily vol of a P&L series.

    ``daily_pnl`` is a series of DOLLAR P&L per day, not returns: the
    "Sharpe" reported here is therefore mean/sd of dollars, annualised by
    ``sqrt(TRADING_DAYS)``. That is scale-free in the package's DV01 (both
    numerator and denominator are linear in it) and so is directly
    comparable to a published Sharpe for the same strategy, but it is not a
    return on capital and must not be read as one.

    ``max_drawdown`` is measured on the CUMULATIVE dollar path (peak-to-
    trough of ``cumsum``), so it is negative and in dollars.
    """
    r = pd.Series(daily_pnl).astype(float).dropna()
    if r.empty:
        # Same key set as the populated return, so a caller indexing ["n"]
        # does not get a KeyError only on the empty path.
        out = {k: float("nan") for k in
               ("sharpe_annualised", "skew", "kurtosis", "max_drawdown", "daily_pnl_vol")}
        out["n"] = 0
        return out
    sd = float(r.std(ddof=1))
    cum = r.cumsum()
    dd = float((cum - cum.cummax()).min())
    return {
        "sharpe_annualised": float(r.mean() / sd * np.sqrt(TRADING_DAYS)) if sd else float("nan"),
        "skew": float(r.skew()),
        "kurtosis": float(r.kurtosis()),
        "max_drawdown": dd,
        "daily_pnl_vol": sd,
        "n": int(len(r)),
    }


RESIDUAL_DEGENERATE_FRAC: float = 1e-6

# Reporting thresholds on the linear fit. **These are NOT a validated gate.**
#
# They were drawn after the fact, inside the gap between the only two R^2
# regimes observed: 0.882, where the sign came out wrong, and 0.956, where it
# came out right. That is a 1-vs-1 in-sample separator fitted to the very rows
# that failed, never tested on a case it was not drawn from -- and in this
# sample Gamma is perfectly confounded with R^2 (the high-R^2 rows are also the
# 10x-Gamma rows), so the cut cannot even be attributed to fit quality rather
# than signal strength. Treat them as a reminder to look at min_r2, not as a
# criterion anything may be decided on.
RESID_R2_SIGN_USABLE: float = 0.93   # below this the sign is certainly not readable
RESID_R2_FLOOR: float = 0.90         # below this do not report the number at all


def residual_stats(daily_pnl: pd.Series, spread_changes: pd.Series) -> dict:
    """Shape of the P&L once its LINEAR exposure to the slope is removed.

    This exists because the raw distributional statistics were measured and
    found **non-discriminating** on this instrument (Task 13). A DV01-neutral
    forward-slope package is delta-hedged against the LEVEL of rates but
    carries a full first-order exposure to the SLOPE, and on real USD curves
    that linear term is ~96% of daily P&L variance. Raw skew is therefore
    essentially the skew of ``d(spread)``, which is a property of the market
    and reads the same way round for a long-convexity book, its
    short-convexity mirror, and a zero-convexity constant-maturity twin
    (:class:`replication.ZeroConvexityPricer`) that has no gamma at all. All
    three clear ``skew > -1``.

    Regressing the P&L on ``d(spread)`` and looking at what is left removes
    exactly the term all three share. What remains for a convex book is
    ``~0.5*Gamma*move**2``, which is strictly signed -- positive for long
    convexity, negative for short. Measured on the study pair that is what
    happens (+2.4767 long, -2.6558 mirror), and the zero-gamma twin correctly
    returns NaN.

    **It does not follow that the number tracks gamma in general.** Two placebo
    pairs with identical measured gamma (+20.31 and +20.34 $/bp^2, a tenth of
    the study pair's) printed +0.7835 and -0.4451 -- opposite signs for the
    same convexity. Whatever this statistic reads at low signal, it is not
    gamma. See :func:`mirror_split` for the domain where it can be trusted.

    ``spread_changes`` must be the change in the pair's OWN slope (a placebo
    pair is regressed on the placebo's slope, not on the study pair's).

    **REPORT IT; DO NOT ACT ON IT.** After calibration this statistic may be
    computed and shown alongside ``min_r2`` and the package's measured gamma.
    It may **not** serve as a gate, a ranking key, evidence for or against
    convexity, or a tiebreaker. The reasons are cumulative, and each is
    measured rather than argued:

    1. It is **1-for-2** on the only configurations where the truth is known
       independently: two placebo pairs with the same gamma, one right sign and
       one wrong.
    2. :func:`mirror_split` **adds nothing** -- ``simulate`` is exactly
       antisymmetric in ``sign``, so pairing is a x2 rescaling that cannot
       change a sign. The study pair and its mirror are one observation.
    3. The R^2 cuts are a **1-vs-1 in-sample separator** drawn because those
       rows failed, never tested out of sample, with gamma confounded with
       R^2 across the whole sample.
    4. It is **dominated** by :func:`greeks.package_gamma`, which answers the
       convexity question directly and settled the placebo case in one call,
       and by the ledger's ``harvest`` bucket, which answers whether that
       convexity was realised. Both are cheaper and neither can be fooled by
       the residual's shape.

    Its value is as a committed record of a measured defect in the original
    distributional criteria (see this module's docstring), not as a tool.

    **Scope note.** In this study ``daily_pnl`` is the ledger's ``total``,
    which includes carry and transaction costs, whereas the ``0.5*Gamma*x**2``
    argument concerns the price-move buckets only. Carry is slow-moving and
    largely absorbed into the intercept, and the cost spikes are few (60 in
    2,391 days) and negative -- so they bias ``resid_skew`` DOWNWARD if at all,
    against the long-convexity reading rather than for it. It is a purity point
    rather than a defect, but a caller wanting the cleanest read can pass
    ``ledger["mtm"] + ledger["harvest"]`` instead.

    ``resid_skew``/``resid_kurtosis`` are NaN when the fit is degenerate --
    residual sd below ``RESIDUAL_DEGENERATE_FRAC`` of the P&L's own sd, i.e.
    R^2 indistinguishable from 1. That is not a failure: it is the correct
    answer for a book whose P&L IS the linear term (the zero-convexity twin
    has R^2 = 1 by construction), and returning a skew computed on float noise
    there would invent a number.
    """
    df = pd.concat(
        [pd.Series(daily_pnl).astype(float).rename("p"),
         pd.Series(spread_changes).astype(float).rename("s")],
        axis=1,
    ).dropna()
    nan = float("nan")
    if len(df) < 5 or float(df["s"].std(ddof=1)) == 0.0:
        return {"beta": nan, "r2": nan, "resid_skew": nan, "resid_kurtosis": nan,
                "resid_sd": nan, "pnl_sd": nan, "n": int(len(df))}
    beta, alpha = np.polyfit(df["s"], df["p"], 1)
    resid = df["p"] - (beta * df["s"] + alpha)
    pnl_sd = float(df["p"].std(ddof=1))
    resid_sd = float(resid.std(ddof=1))
    degenerate = pnl_sd == 0.0 or resid_sd < RESIDUAL_DEGENERATE_FRAC * pnl_sd
    return {
        "beta": float(beta),
        "r2": float(df["p"].corr(df["s"]) ** 2),
        "resid_skew": nan if degenerate else float(resid.skew()),
        "resid_kurtosis": nan if degenerate else float(resid.kurtosis()),
        "resid_sd": resid_sd,
        "pnl_sd": pnl_sd,
        "n": int(len(df)),
    }


def mirror_split(
    pnl_long: pd.Series,
    pnl_short: pd.Series,
    spread_changes: pd.Series,
) -> dict:
    """``resid_skew(book) - resid_skew(its mirror)``. **A x2 rescaling. Adds nothing.**

    Kept only as committed documentation of a measured dead end. It was
    introduced on the theory that a book and its sign-flipped mirror share
    their model misfit, so differencing would cancel the contamination that
    made the unpaired ``resid_skew`` print a wrong sign. **That theory is
    false, and the reason is structural rather than empirical.**

    ``simulate`` is EXACTLY ANTISYMMETRIC in ``sign``. Per-unit ``dv01`` is
    sign-invariant (numerator and denominator both flip); the notionals flip;
    ``pv`` and ``theta`` are linear in the notionals; the trigger reads the
    sign-independent constant-maturity rate, so the two runs hedge on the same
    dates; and ``cost`` is a magnitude fee. Every P&L bucket therefore negates
    exactly and only the cost ledger is shared:

        resid_short = -resid_long - resid_cost
        split       = resid_long - resid_short  ~=  2 * resid_long

    So the "mirror" is not a second book carrying a common contaminant -- it
    is the arithmetic negation of the first, and there is nothing to cancel.
    Measured: on a synthetic engine-mirror with no costs the ratio
    ``split / resid_long`` is **2.000000** exactly; with costs 2.12; on the
    three real 2017-2026 runs 2.072 / 2.140 / 1.864. Pinned by
    ``test_the_mirror_is_the_negation_so_pairing_only_rescales``.

    A monotone positive rescaling cannot change a sign, so pairing **cannot
    rescue a wrong one** -- and indeed did not: the placebo that printed
    -0.4451 unpaired printed -0.8296 paired. The study pair and its mirror are
    ONE observation, not two.

    Use :func:`greeks.package_gamma` to ask whether a package is convex -- it
    answers directly, and it settled the placebo case in a single call. Use
    the ledger's ``harvest`` bucket to ask whether that convexity was actually
    realised. Neither goes through this function.
    """
    lo = residual_stats(pnl_long, spread_changes)
    sh = residual_stats(pnl_short, spread_changes)
    nan = float("nan")
    split = nan
    if np.isfinite(lo["resid_skew"]) and np.isfinite(sh["resid_skew"]):
        split = float(lo["resid_skew"] - sh["resid_skew"])
    r2s = [lo["r2"], sh["r2"]]
    finite_r2 = [r for r in r2s if np.isfinite(r)]
    return {
        "split": split,
        "resid_skew_long": lo["resid_skew"],
        "resid_skew_short": sh["resid_skew"],
        "r2_long": lo["r2"],
        "r2_short": sh["r2"],
        "min_r2": min(finite_r2) if finite_r2 else nan,
        "usable": bool(finite_r2) and min(finite_r2) >= RESID_R2_SIGN_USABLE,
        "readable": bool(finite_r2) and min(finite_r2) >= RESID_R2_FLOOR,
        "n": min(lo["n"], sh["n"]),
    }


def vol_beta(pnl: pd.Series, vol_changes: pd.Series) -> dict:
    """Regression of P&L on changes in implied vol -- the long-vol fingerprint.

    Aligns the two series on their shared index (so a monthly P&L series and
    a monthly change-in-implied-vol series need only agree on period ends)
    and drops any period either side is missing. A long-convexity position
    must show ``corr > 0``: vol going up is the environment it is paid in.
    """
    df = pd.concat(
        [pd.Series(pnl).astype(float).rename("p"),
         pd.Series(vol_changes).astype(float).rename("v")],
        axis=1,
    ).dropna()
    if len(df) < 5:
        return {"corr": float("nan"), "beta": float("nan"), "n": int(len(df))}
    beta = float(np.polyfit(df["v"], df["p"], 1)[0])
    return {"corr": float(df["p"].corr(df["v"])), "beta": beta, "n": int(len(df))}


# --------------------------------------------------------------- Task 18 panels

#: Ranking keys this module refuses, with the measurement that disqualified each.
FORBIDDEN_RANK_KEYS = {
    "sharpe": (
        "Sharpe is actively misleading on this instrument: both Task 13 placebo "
        "pairs out-Sharpe every real pair (+0.475, +0.343) while running the "
        "OPPOSITE carry sign, and a DV01-matched zero-convexity twin prints a "
        "better Sharpe than the convex book on zero gamma. Rank on vol_corr, "
        "harvest_pnl_share or carry_sign."
    ),
    "sharpe_annualised": "see 'sharpe'",
    "skew": (
        "Raw daily-P&L skew carries no information about convexity here: the "
        "zero-convexity twin prints +0.288 against the real package's +0.087, "
        "because ~95.6% of daily variance is unhedged first-order slope."
    ),
    "resid_skew": (
        "resid_skew may be REPORTED, never acted on -- not a gate, ranking key, "
        "evidence or tiebreaker. It was 1-for-2 on the only cases where the "
        "truth was known independently."
    ),
    "kurtosis": "a shape statistic on a series that is ~96% linear slope exposure",
    "t_stat": (
        "a monotone function of Sharpe on the same series (t = SR * sqrt(n) up "
        "to the HAC correction), so ranking on it is ranking on Sharpe through "
        "a side door. Same measurement disqualifies it."
    ),
}

_REQUIREMENT_PREFIX = "req_"


def _harvest_shares(led: pd.DataFrame) -> tuple:
    """``(flow_ratio, pnl_share)`` -- a book-size measure and a signed share.

    They are different objects and were once conflated under the single name
    ``harvest_to_mtm``: that quantity was built from gross daily ABSOLUTE
    flows, so it measured how big the increment book was, not what share of
    P&L it contributed. Both are reported, separately, and the old name is not
    reintroduced.
    """
    mtm_flow = float(led["mtm"].abs().sum())
    flow_ratio = float(led["harvest"].abs().sum() / mtm_flow) if mtm_flow else float("nan")
    denom = sum(abs(float(led[c].sum())) for c in ("carry", "harvest", "mtm"))
    pnl_share = float(led["harvest"].sum() / denom) if denom else float("nan")
    return flow_ratio, pnl_share


def _cost_at(res, multiplier: float, *, schedule=None, roll_charged: bool = True) -> float:
    """The run's charge at ``multiplier``, in dollars, as a positive number.

    With ``schedule`` given the fee is recomputed from the ledger's traded-risk
    volumes, which is the only correct route when the run itself used ``FREE``
    (scaling zero by two is still zero). Without it, the run's own realised
    charge is scaled -- the cheap path, and the one not to quote from a
    zero-cost run.
    """
    from RVUtils.StrikelessVol.costs import charge_usd

    if schedule is not None:
        return float(charge_usd(res.ledger, schedule, multiplier=multiplier,
                                roll_charged=roll_charged).sum())
    return float(-res.ledger["cost"].sum()) * float(multiplier)


def league_table(
    results,
    *,
    grid=None,
    n_trials=None,
    cost_multipliers=(0.0, 1.0, 2.0),
    cost_schedule=None,
    rank_by=None,
    vol_changes_by_pair=None,
) -> pd.DataFrame:
    """The honesty panel: costs at 0x/1x/2x, DSR on the FULL trial count, verdict.

    Three things this enforces rather than reports.

    **The DSR trial count.** ``grid`` must cover every pair being ranked, and
    the count handed to ``deflated_for_grid`` must be every configuration tried
    across every pair **and family**. Three ways that goes wrong, all closed:

    * a grid with no rows for a ranked pair -> raises;
    * a **single-pair grid with no declared count** -> raises, because that is
      the shape of the trap (ranking one pair against its own sweep deflates by
      1/n_pairs of the real search, silently). Declare ``n_trials`` or pass the
      concatenated grid;
    * ``n_trials`` below ``len(grid)`` -> raises. Above it is allowed and is the
      point: it is how a cross-family count gets declared, and it is passed
      through to ``deflated_for_grid`` rather than merely cross-checked.

    **The six requirements.** Every row reports each of them as ``req_*``, and a
    row that cannot report all six met is downgraded out of ``ALIVE`` to
    ``INELIGIBLE``. Task 15's +8.46bp/trade headline became -1.87bp once they
    were applied; a verdict issued without them is a verdict about a different
    strategy.

    **The ranking key.** ``rank_by`` refuses Sharpe, raw skew, kurtosis and
    ``resid_skew`` -- see ``FORBIDDEN_RANK_KEYS`` for the measurement behind
    each. Rank on ``vol_corr``, ``harvest_pnl_share`` and ``carry_sign``.

    ``verdict`` itself is ``RVUtils.SFRRVLab.stats.verdict``, reused verbatim:
    the taxonomy is repo-wide and this study does not get its own.
    """
    from RVUtils.SFRRVLab.stats import deflated_for_grid, nw_tstat, verdict

    if rank_by:
        for key in rank_by:
            if key in FORBIDDEN_RANK_KEYS:
                raise ValueError(
                    f"refusing to rank on {key!r}: {FORBIDDEN_RANK_KEYS[key]}"
                )

    effective_trials = None
    if grid is not None:
        if "sharpe" not in grid.columns:
            raise ValueError("grid must carry a 'sharpe' column for deflation")
        if n_trials is not None and int(n_trials) < len(grid):
            raise ValueError(
                f"n_trials={n_trials} is below the grid's {len(grid)} rows; the "
                "declared trial count cannot be smaller than the search shown"
            )
        if "pair" in grid.columns:
            grid_pairs = set(grid["pair"].astype(str))
            missing = {r.pair_name for r in results} - grid_pairs
            if missing:
                raise ValueError(
                    "grid looks like a per-pair slice: it has no rows for "
                    f"{sorted(missing)}. deflated_for_grid must receive the FULL "
                    "trial count across every pair and family, not one pair's."
                )
            if len(grid_pairs) <= 1 and n_trials is None:
                raise ValueError(
                    f"grid covers a single pair ({sorted(grid_pairs)}) and no "
                    "n_trials was declared. Deflating by one pair's own sweep "
                    "understates the search by a factor of the pair count -- "
                    "pass the concatenated grid for every pair and family, or "
                    "declare the full count as n_trials (n_trials >= len(grid) "
                    "is allowed precisely so a cross-family count can be stated)."
                )
        effective_trials = int(n_trials) if n_trials is not None else len(grid)

    median_net_bp = (float(grid["total_net_bp"].median())
                     if grid is not None and "total_net_bp" in grid.columns else 0.0)

    rows = []
    for res in results:
        trades = res.trades
        n = int(len(trades))
        gross_usd = float(trades["gross_usd"].sum()) if n else 0.0
        dv01 = res.stats.get("realised_dv01_mean_usd", float("nan"))
        usable_dv01 = bool(np.isfinite(dv01)) and dv01 != 0.0

        if cost_schedule is None and res.config.get("cost_multiplier") == 0:
            raise ValueError(
                f"{res.pair_name}: this result was run at cost multiplier 0, so "
                "its realised charge is zero and scaling it by 1x or 2x is still "
                "zero -- net_1x_bp and net_2x_bp would equal gross_bp and the "
                "ALIVE gate would be reading a cost-free number. Pass "
                "cost_schedule= to reprice from the ledger's traded-risk "
                "volumes, or run the pair at a real schedule."
            )
        cost_usd = {m: _cost_at(res, m, schedule=cost_schedule)
                    for m in cost_multipliers}
        one_x = cost_usd.get(1.0, float(-res.ledger["cost"].sum()))
        two_x = cost_usd.get(2.0, 2.0 * one_x)
        # m3: ONE divisor for every bp column on this row -- the run-level
        # realised mean DV01. gross_bp was previously the sum of per-EPISODE bp
        # figures while the cost was normalised at the run level, and the two
        # only compose when realised DV01 is stable across episodes, which Task
        # 13 measured that it is not ($52.7k-$148.9k). Per-episode bp still
        # lives on `trades`, where each row carries its own avg_dv01_usd.
        gross_bp = gross_usd / dv01 if usable_dv01 else float("nan")
        one_x_bp = one_x / dv01 if usable_dv01 else float("nan")
        two_x_bp = two_x / dv01 if usable_dv01 else float("nan")

        dsr = (deflated_for_grid(res.daily_pnl, grid, n_trials=effective_trials)
               if grid is not None else {"dsr_prob": float("nan")})
        net1_bp, net2_bp = gross_bp - one_x_bp, gross_bp - two_x_bp
        maker_bp = gross_bp - 0.5 * one_x_bp

        led = res.ledger
        flow_ratio, pnl_share = _harvest_shares(led)
        vol_corr = float("nan")
        if vol_changes_by_pair and res.pair_name in vol_changes_by_pair:
            vol_corr = vol_beta(res.daily_pnl, vol_changes_by_pair[res.pair_name])["corr"]

        base = verdict(
            net_bp_at_taker=net2_bp,
            net_bp_at_maker=maker_bp,
            dsr_prob=float(dsr.get("dsr_prob") or 0.0),
            median_net_bp=median_net_bp,
            n_trades=n,
        )
        flags = res.requirements
        if base == "ALIVE" and not flags.all_met:
            base = f"INELIGIBLE (requirements unmet: {', '.join(flags.unmet)})"

        row = {
            "pair": res.pair_name,
            "book": res.config.get("book", "package"),
            "config": res.config,
            "n_trades": n,
            "n_distinct_episodes": int(res.stats.get("n_distinct_episodes", n)),
            "hit": float((trades["net_usd"] > 0).mean()) if n else float("nan"),
            "gross_usd": gross_usd,
            "gross_bp": gross_bp,
            "net_1x_usd": gross_usd - one_x,
            "net_2x_usd": gross_usd - two_x,
            "net_1x_bp": net1_bp,
            "net_2x_bp": net2_bp,
            "cost_1x_usd": one_x,
            "realised_dv01_mean_usd": dv01,
            "t_stat": nw_tstat(res.daily_pnl.dropna(), lags=5),
            "sharpe": res.stats.get("sharpe_annualised"),
            "skew": res.stats.get("skew"),
            "carry_sign": int(np.sign(float(led["carry"].sum()))),
            "harvest_pnl_share": pnl_share,
            "harvest_flow_ratio": flow_ratio,
            "vol_corr": vol_corr,
            "dsr_prob": dsr.get("dsr_prob"),
            "n_trials": effective_trials if grid is not None else float("nan"),
            "requirements_met": bool(flags.all_met),
            "verdict": base,
        }
        row.update(flags.as_columns(_REQUIREMENT_PREFIX))
        rows.append(row)

    out = pd.DataFrame(rows)
    if rank_by and len(out):
        out = out.sort_values(list(rank_by), ascending=False).reset_index(drop=True)
    return out


def ledger_attribution(results) -> pd.DataFrame:
    """H10: is the harvest near-uniformly positive while total P&L is MTM-driven?

    ``harvest_flow_ratio`` is gross daily absolute harvest over gross daily
    absolute MTM -- a measure of the increment book's SIZE, not a share of P&L.
    ``harvest_pnl_share`` is the signed contribution share. Reporting only one
    of them (under either name) is what the amendment after Task 13 exists to
    prevent.
    """
    rows = []
    for res in results:
        led = res.ledger
        flow_ratio, pnl_share = _harvest_shares(led)
        rows.append({
            "pair": res.pair_name,
            "book": res.config.get("book", "package"),
            "carry": float(led["carry"].sum()),
            "harvest": float(led["harvest"].sum()),
            "mtm": float(led["mtm"].sum()),
            "cost": float(led["cost"].sum()),
            "cross": float(led["cross"].sum()),
            "total": float(led["total"].sum()),
            "harvest_positive_share": float((led["harvest"] > 0).mean()),
            "harvest_flow_ratio": flow_ratio,
            "harvest_pnl_share": pnl_share,
            "n_hedges": int(led["n_hedges"].sum()) if "n_hedges" in led else 0,
            "n_rolls": int(led["n_rolls"].sum()) if "n_rolls" in led else 0,
            "realised_dv01_mean_usd": res.stats.get("realised_dv01_mean_usd",
                                                    float("nan")),
        })
    return pd.DataFrame(rows)


def cost_table(
    results,
    *,
    schedule,
    multipliers=(0.0, 1.0, 2.0),
    roll_conventions=(True, False),
) -> pd.DataFrame:
    """Costs as their own result: 0x/1x/2x AND the roll-charge convention.

    Costs are first-order on this book -- 41% of gross at 1x on the static
    long, 83% at 2x -- so no P&L number in this study is quoted at one
    multiplier. Separately, **whether the annual roll is charged at all was
    measured at 67.5% of the static book's headline**, which makes it a row in
    this table rather than an assumption buried inside a total.

    The fee is recomputed from the ledger's traded-risk VOLUMES, so a run made
    at any schedule can be repriced at any other without re-simulating.
    """
    from RVUtils.StrikelessVol.costs import charge_usd

    rows = []
    for res in results:
        led = res.ledger
        gross = float(led[["carry", "harvest", "mtm", "cross"]].sum().sum())
        dv01 = res.stats.get("realised_dv01_mean_usd", float("nan"))
        usable = bool(np.isfinite(dv01)) and dv01 != 0.0
        for m in multipliers:
            for roll_charged in roll_conventions:
                cost = float(charge_usd(led, schedule, multiplier=m,
                                        roll_charged=bool(roll_charged)).sum())
                net = gross - cost
                rows.append({
                    "pair": res.pair_name,
                    "book": res.config.get("book", "package"),
                    "cost_multiplier": float(m),
                    "roll_charged": bool(roll_charged),
                    "gross_usd": gross,
                    "cost_usd": cost,
                    "net_usd": net,
                    "net_bp": net / dv01 if usable else float("nan"),
                    # a magnitude share: |cost| over |gross|, so a losing book
                    # does not report a negative "share of gross"
                    "cost_share_of_gross": (cost / abs(gross)) if gross else float("nan"),
                })
    out = pd.DataFrame(rows)
    if len(out):
        out["roll_charged"] = out["roll_charged"].astype(bool)
    return out


#: Default trailing window for the risk-parity weights, in observations.
PORTFOLIO_WINDOW: int = 63


def portfolio(
    results_by_market: dict,
    *,
    target_bp_day: float,
    caps: dict | None = None,
    window: int = PORTFOLIO_WINDOW,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """Risk-parity book across markets, weights from trailing P&L vol.

    Returns one ``w_<market>`` column per market plus ``pnl``, on the union of
    the inputs' indices.

    **Weights are lagged one day: today's weight cannot know today's
    volatility.** ``w = target_bp_day / sd(trailing ``window`` observations,
    ending yesterday)``, clipped above by ``caps`` where given.

    **The unit contract, and why the parameter is named ``_bp_day``.** The
    weight is a pure ratio, so ``target_bp_day`` must be in **the same unit as
    the input series**, and the book then realises that unit as its own daily
    sd (pinned by
    ``test_the_book_realises_the_target_when_the_legs_are_independent``). This
    study's ledgers are DOLLARS (:func:`distribution_stats` says so), and a
    dollar book is not comparable across markets whose realised DV01s differ --
    so the caller divides by each run's ``realised_dv01_mean_usd`` first and
    feeds bp/day. Feeding dollars is not an error this function can detect; it
    just makes the parameter's name a lie and the "risk parity" a parity of
    nothing.

    **A missing value is missing, not a flat day.** Any NaN inside the trailing
    window leaves that market's weight NaN for the rest of the window, and a
    market with no weight simply does not trade (``pnl`` sums what is present,
    ``min_count=1``). This matters cross-market because the calendars differ:
    JPY is closed on days USD trades, and treating those as zero-P&L days would
    shrink JPY's measured vol and hand it a bigger weight for being shut. The
    caller has to decide what a closed day is and say so; the two cases are
    genuinely different and only one of them is a zero.

    **This function does not answer H8, and must not be read as if it did.** A
    multi-market book beats the best single market on Sharpe almost
    automatically -- averaging weakly-correlated series raises the ratio whether
    or not the mechanism generalises, and this book is *constructed* to exploit
    that. Whether the signs hold across markets is a per-market question about
    the sign and magnitude of the measured relationships (carry sign,
    ``harvest_pnl_share``, vol correlation, valuation state); the aggregate
    ratio is downstream of the arithmetic, not evidence about the mechanism.
    Compare distributions on **max drawdown**, never on Sharpe -- see
    ``FORBIDDEN_RANK_KEYS`` and this module's docstring for the measurements
    behind that.

    Three refusals, each because the silent version reads as a pass:

    * an empty book -- there is no risk parity over no markets;
    * ``target_bp_day <= 0`` -- a zero target gives a zero book, which reports
      as a flawless flat P&L rather than as a mistake;
    * a cap naming a market that is not in the book -- a misspelled cap never
      binds, and "the cap was respected" is exactly what a never-binding cap
      looks like from the outside.
    """
    if not results_by_market:
        raise ValueError(
            "portfolio() needs at least one market: a risk-parity book over an "
            "empty set of markets is not an empty book, it is a mistake."
        )
    if not np.isfinite(target_bp_day) or float(target_bp_day) <= 0.0:
        raise ValueError(
            f"target_bp_day must be finite and positive, got {target_bp_day!r}. "
            "A non-positive target produces a zero or sign-flipped book, which "
            "reports as a flat (or inverted) P&L rather than as an error."
        )
    caps = dict(caps or {})
    frame = pd.DataFrame(
        {k: pd.Series(v).astype(float) for k, v in results_by_market.items()}
    )
    unknown = [m for m in caps if m not in frame.columns]
    if unknown:
        raise ValueError(
            f"caps name markets that are not in the book: {sorted(unknown)} "
            f"(book has {sorted(frame.columns)}). A cap on a market that is not "
            "there never binds, and an un-bound cap is indistinguishable from a "
            "respected one."
        )
    bad_caps = {m: c for m, c in caps.items()
                if not np.isfinite(c) or float(c) <= 0.0}
    if bad_caps:
        raise ValueError(
            f"every cap must be finite and positive, got {bad_caps}. A zero cap "
            "silently removes the market instead of limiting it."
        )

    window = int(window)
    mp = window if min_periods is None else int(min_periods)
    vol = frame.rolling(window, min_periods=mp).std(ddof=1).shift(1)
    weights = (float(target_bp_day) / vol).replace([np.inf, -np.inf], np.nan)
    for market, cap in caps.items():
        weights[market] = weights[market].clip(upper=float(cap))

    out = pd.DataFrame({f"w_{c}": weights[c] for c in frame.columns})
    out["pnl"] = (weights * frame).sum(axis=1, min_count=1)
    return out


def per_year_attribution(results) -> pd.DataFrame:
    """P&L by calendar year, and what the lifetime looks like without each one.

    The static long is concentrated: 2022 alone was +$5.1M of a +$0.7M lifetime
    total, i.e. materially NEGATIVE ex-2022. ``share_of_lifetime`` above 1 with a
    negative ``lifetime_ex_year_usd`` is how that shows up rather than being
    averaged away into a nine-year mean.
    """
    rows = []
    for res in results:
        pnl = pd.Series(res.daily_pnl).astype(float).dropna()
        if pnl.empty:
            continue
        total = float(pnl.sum())
        dv01 = res.stats.get("realised_dv01_mean_usd", float("nan"))
        usable = bool(np.isfinite(dv01)) and dv01 != 0.0
        for year, grp in pnl.groupby(pnl.index.year):
            y = float(grp.sum())
            rows.append({
                "pair": res.pair_name,
                "book": res.config.get("book", "package"),
                "year": int(year),
                "n_days": int(len(grp)),
                "pnl_usd": y,
                "pnl_bp": y / dv01 if usable else float("nan"),
                "share_of_lifetime": y / total if total else float("nan"),
                "lifetime_usd": total,
                "lifetime_ex_year_usd": total - y,
            })
    return pd.DataFrame(rows)
